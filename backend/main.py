"""FastAPI backend for LLM Council."""

from fastapi import FastAPI, HTTPException, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any
import uuid
import json
import asyncio
import copy
from pathlib import Path

from . import storage
from .council import run_full_council_with_history, generate_conversation_title, stage1_collect_responses_streaming, stage2_collect_rankings_streaming, stage3_synthesize_final_with_history, calculate_aggregate_rankings, quick_query, has_successful_stage1_results, has_successful_stage2_results, build_label_to_model_from_stage1_results
from .llm_settings import public_llm_settings, update_llm_settings
from .openrouter import query_model

app = FastAPI(title="LLM Council API")

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CreateConversationRequest(BaseModel):
    """Request to create a new conversation."""
    pass


class SendMessageRequest(BaseModel):
    """Request to send a message in a conversation."""
    content: str


class ContextPreviewRequest(BaseModel):
    """Request to preview the model-facing context for the next turn."""
    content: str = ""
    mode: str = "council"


class RetryMessageRequest(BaseModel):
    """Request to retry a stored user message without duplicating it."""
    mode: str | None = None


class ContextReplayRequest(BaseModel):
    """Request to rebuild context for a stored user turn without mutating it."""
    mode: str | None = None


class PinMessageRequest(BaseModel):
    """Request to pin or unpin a message for future context builds."""
    pinned: bool


class ContextVisibilityRequest(BaseModel):
    """Request to include or exclude one message from future context builds."""
    excluded: bool


class ForkConversationRequest(BaseModel):
    """Request to fork one conversation at a message boundary."""
    message_index: int


class ContextPolicyRequest(BaseModel):
    """Partial per-conversation context policy update."""
    token_budget: int | None = None
    recent_turns: int | None = None
    message_char_limit: int | None = None
    summarize_older: bool | None = None
    use_pinned: bool | None = None
    pin_message_char_limit: int | None = None
    pin_max_chars: int | None = None
    use_memory: bool | None = None
    memory_item_char_limit: int | None = None
    memory_max_chars: int | None = None


class ContextMemoryRequest(BaseModel):
    """Request to create or update a durable conversation memory item."""
    content: str | None = None
    enabled: bool | None = None


class UpdateTitleRequest(BaseModel):
    """Request to update conversation title."""
    title: str


class UpdateFileQueueRequest(BaseModel):
    """Request to replace a conversation's pending file queue."""
    files: List[Dict[str, Any]]


class UpdateLLMSettingsRequest(BaseModel):
    """Partial runtime LLM settings update."""
    default_provider: Dict[str, Any] | None = None
    council_models: List[str] | None = None
    chairman_model: str | None = None
    chairman_fallback_models: List[str] | None = None
    quick_model: str | None = None
    quick_fallback_models: List[str] | None = None
    title_model: str | None = None
    title_fallback_models: List[str] | None = None
    summarization_model: str | None = None
    summarization_fallback_models: List[str] | None = None
    model_overrides: Dict[str, Dict[str, Any]] | None = None


class TestLLMSettingsRequest(BaseModel):
    """Request to test a configured model connection."""
    model: str


class ConversationMetadata(BaseModel):
    """Conversation metadata for list view."""
    id: str
    created_at: str
    title: str
    message_count: int


class Conversation(BaseModel):
    """Full conversation with all messages."""
    id: str
    created_at: str
    title: str
    messages: List[Dict[str, Any]]
    turns: List[Dict[str, Any]] | None = None
    context_summary: Dict[str, Any] | None = None
    context_policy: Dict[str, Any] | None = None
    context_memory: List[Dict[str, Any]] | None = None
    branch_parent_id: str | None = None
    branch_from_message_index: int | None = None
    branch_created_at: str | None = None


def _find_preceding_user_message(
    messages: List[Dict[str, Any]],
    assistant_index: int,
) -> tuple[int, Dict[str, Any]]:
    """Find the user message that belongs to a persisted assistant response."""
    if assistant_index < 0 or assistant_index >= len(messages):
        raise ValueError("Assistant message index out of range")

    assistant = messages[assistant_index]
    if assistant.get("role") != "assistant":
        raise ValueError("Selected message is not an assistant message")

    for index in range(assistant_index - 1, -1, -1):
        if messages[index].get("role") == "user":
            return index, messages[index]

    raise ValueError("No preceding user message found for assistant response")


def _stage3_is_complete(stage3: Any) -> bool:
    """Return True when a persisted Stage 3 result is usable."""
    return isinstance(stage3, dict) and stage3.get("status", "success") == "success" and bool(stage3.get("response"))


def _metadata_has_label_mapping(metadata: Any) -> bool:
    """Return True when Stage 2 metadata has the mapping needed by the UI."""
    return (
        isinstance(metadata, dict)
        and isinstance(metadata.get("label_to_model"), dict)
        and bool(metadata.get("label_to_model"))
    )


def _rebuild_stage2_metadata(
    stage1_results: List[Dict[str, Any]],
    stage2_results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Recreate Stage 2 metadata from persisted Stage 1/2 results."""
    label_to_model = build_label_to_model_from_stage1_results(stage1_results)
    return {
        "label_to_model": label_to_model,
        "aggregate_rankings": calculate_aggregate_rankings(stage2_results, label_to_model),
    }


def _context_messages(context_package: Dict[str, Any]) -> List[Dict[str, Any]] | None:
    """Return model-facing context messages or None for legacy council helpers."""
    messages = context_package.get("messages") or []
    return messages or None


AUDIT_PAYLOAD_TEXT_LIMIT = 16_000
AUDIT_PAYLOAD_ITEM_TEXT_LIMIT = 8_000


def _truncate_audit_text(value: str, limit: int, stats: Dict[str, Any]) -> str:
    stats["original_text_chars"] += len(value)
    if len(value) <= limit:
        stats["stored_text_chars"] += len(value)
        return value

    stats["truncated_text_items"] += 1
    truncated = value[:limit].rstrip() + f"\n\n[Truncated audit payload text to {limit} characters]"
    stats["stored_text_chars"] += len(truncated)
    return truncated


def _audit_safe_content(content: Any, stats: Dict[str, Any]) -> Any:
    if isinstance(content, str):
        return _truncate_audit_text(content, AUDIT_PAYLOAD_TEXT_LIMIT, stats)

    if isinstance(content, list):
        safe_items = []
        for item in content:
            if not isinstance(item, dict):
                safe_items.append(copy.deepcopy(item))
                continue

            if item.get("type") == "image_url":
                stats["redacted_image_items"] += 1
                safe_item = {"type": "image_url", "image_url": {"url": "[redacted image data URI]", "redacted": True}}
                if item.get("image_url", {}).get("detail"):
                    safe_item["image_url"]["detail"] = item["image_url"]["detail"]
                if item.get("attachment_ref"):
                    safe_item["attachment_ref"] = copy.deepcopy(item["attachment_ref"])
                safe_items.append(safe_item)
                continue

            safe_item = copy.deepcopy(item)
            if item.get("type") == "text" and "text" in item:
                safe_item["text"] = _truncate_audit_text(str(item.get("text", "")), AUDIT_PAYLOAD_ITEM_TEXT_LIMIT, stats)
            safe_items.append(safe_item)
        return safe_items

    if isinstance(content, dict):
        if content.get("type") == "image_url":
            stats["redacted_image_items"] += 1
            safe_content = {"type": "image_url", "image_url": {"url": "[redacted image data URI]", "redacted": True}}
            if content.get("attachment_ref"):
                safe_content["attachment_ref"] = copy.deepcopy(content["attachment_ref"])
            return safe_content
        safe_content = copy.deepcopy(content)
        if "content" in safe_content:
            safe_content["content"] = _audit_safe_content(safe_content["content"], stats)
        return safe_content

    return copy.deepcopy(content)


def _audit_safe_messages(messages: List[Dict[str, Any]], stats: Dict[str, Any]) -> List[Dict[str, Any]]:
    safe_messages = []
    for message in messages:
        safe_message = copy.deepcopy(message)
        safe_message["content"] = _audit_safe_content(message.get("content", ""), stats)
        safe_messages.append(safe_message)
    return safe_messages


def _persistent_user_content(content: Any) -> Any:
    """Return the version of user content safe to store in conversation JSON."""
    stats = {
        "redacted_image_items": 0,
        "truncated_text_items": 0,
        "original_text_chars": 0,
        "stored_text_chars": 0,
    }
    return _audit_safe_content(content, stats)


def _attachment_path(conversation_id: str, attachment_id: str) -> Path:
    return Path(storage.DATA_DIR) / "attachments" / conversation_id / attachment_id


def _store_uploaded_attachment(
    conversation_id: str,
    attachment_id: str,
    filename: str,
    content: bytes,
    file_type: str,
) -> Dict[str, Any]:
    path = _attachment_path(conversation_id, attachment_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return {
        "id": attachment_id,
        "filename": filename,
        "type": file_type,
        "size": len(content),
    }


def _restore_attachment_content(content: Any) -> Any:
    if isinstance(content, list):
        return [_restore_attachment_content(item) for item in content]

    if isinstance(content, dict):
        if content.get("type") == "image_url" and content.get("attachment_ref"):
            from .file_processor import FileProcessor

            attachment_ref = content["attachment_ref"]
            conversation_id = attachment_ref.get("conversation_id")
            attachment_id = attachment_ref.get("id")
            file_type = attachment_ref.get("type") or "image/png"
            if conversation_id and attachment_id:
                path = _attachment_path(conversation_id, attachment_id)
                if path.exists():
                    restored = copy.deepcopy(content)
                    restored["image_url"] = {
                        "url": FileProcessor.encode_image_to_base64(path.read_bytes(), file_type)
                    }
                    if content.get("image_url", {}).get("detail"):
                        restored["image_url"]["detail"] = content["image_url"]["detail"]
                    return restored
        restored = copy.deepcopy(content)
        if "content" in restored:
            restored["content"] = _restore_attachment_content(restored["content"])
        return restored

    return copy.deepcopy(content)


def _context_payload(context_package: Dict[str, Any]) -> Dict[str, Any]:
    """Persist an auditable context package without storing large binary payloads."""
    stats = {
        "redacted_image_items": 0,
        "truncated_text_items": 0,
        "original_text_chars": 0,
        "stored_text_chars": 0,
    }
    model_messages = context_package.get("messages") or []
    audit_messages = context_package.get("source_messages") or model_messages
    payload = {
        "schema": "context_payload_v1",
        "model_messages": _audit_safe_messages(model_messages, stats),
        "audit_messages": _audit_safe_messages(audit_messages, stats),
    }
    if "current_content" in context_package:
        payload["current_message"] = {
            "role": "user",
            "content": _audit_safe_content(context_package.get("current_content"), stats),
        }
    payload["compaction"] = {
        **stats,
        "compacted": stats["redacted_image_items"] > 0 or stats["truncated_text_items"] > 0,
    }
    return payload


def _content_text_for_compare(content: Any) -> str:
    if isinstance(content, str):
        return content
    try:
        return json.dumps(content, sort_keys=True, ensure_ascii=False)
    except TypeError:
        return str(content)


def _estimate_payload_tokens(messages: List[Dict[str, Any]]) -> int:
    return sum(max(1, len(_content_text_for_compare(message.get("content", ""))) // 4) for message in messages)


def _message_diff_key(message: Dict[str, Any]) -> tuple[str, str, str, str]:
    source = message.get("source") or ""
    message_index = "" if message.get("message_index") is None else str(message.get("message_index"))
    return (
        str(message.get("role") or ""),
        _content_text_for_compare(message.get("content", "")),
        str(source),
        message_index,
    )


def _message_diff_preview(message: Dict[str, Any]) -> Dict[str, Any]:
    content = _content_text_for_compare(message.get("content", ""))
    return {
        "role": message.get("role"),
        "source": message.get("source"),
        "message_index": message.get("message_index"),
        "content_preview": content[:240],
    }


def _context_payload_comparison(
    saved_messages: List[Dict[str, Any]],
    rebuilt_messages: List[Dict[str, Any]],
    saved_snapshot: Dict[str, Any] | None,
    rebuilt_snapshot: Dict[str, Any] | None,
) -> Dict[str, Any]:
    saved_keys = [_message_diff_key(message) for message in saved_messages]
    rebuilt_keys = [_message_diff_key(message) for message in rebuilt_messages]
    saved_key_set = set(saved_keys)
    rebuilt_key_set = set(rebuilt_keys)
    saved_only = [message for message, key in zip(saved_messages, saved_keys) if key not in rebuilt_key_set]
    rebuilt_only = [message for message, key in zip(rebuilt_messages, rebuilt_keys) if key not in saved_key_set]
    saved_tokens = _estimate_payload_tokens(saved_messages)
    rebuilt_tokens = _estimate_payload_tokens(rebuilt_messages)
    saved_policy = (saved_snapshot or {}).get("context_policy") or {}
    rebuilt_policy = (rebuilt_snapshot or {}).get("context_policy") or {}
    saved_snapshot_tokens = (saved_snapshot or {}).get("estimated_context_tokens")
    rebuilt_snapshot_tokens = (rebuilt_snapshot or {}).get("estimated_context_tokens")

    return {
        "available": True,
        "same_order": saved_keys == rebuilt_keys,
        "same_message_set": saved_key_set == rebuilt_key_set,
        "saved_message_count": len(saved_messages),
        "rebuilt_message_count": len(rebuilt_messages),
        "saved_only_count": len(saved_only),
        "rebuilt_only_count": len(rebuilt_only),
        "saved_estimated_tokens": saved_tokens,
        "rebuilt_estimated_tokens": rebuilt_tokens,
        "estimated_token_delta": rebuilt_tokens - saved_tokens,
        "snapshot_token_delta": (
            rebuilt_snapshot_tokens - saved_snapshot_tokens
            if isinstance(saved_snapshot_tokens, int) and isinstance(rebuilt_snapshot_tokens, int)
            else None
        ),
        "policy_changed": saved_policy != rebuilt_policy,
        "saved_only_preview": [_message_diff_preview(message) for message in saved_only[:5]],
        "rebuilt_only_preview": [_message_diff_preview(message) for message in rebuilt_only[:5]],
    }


def _preview_payload(context_package: Dict[str, Any], mode: str, extra: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Return the auditable next context package without running models."""
    messages = context_package.get("source_messages") or context_package.get("messages") or []
    payload = {
        "mode": mode,
        "messages": messages,
        "message_count": len(messages),
        "snapshot": context_package.get("snapshot") or {},
    }
    if extra:
        payload.update(extra)
    return payload


def _normalize_request_mode(mode: str | None) -> str:
    normalized = (mode or "council").strip().lower()
    if normalized not in {"council", "quick"}:
        raise ValueError("mode must be 'quick' or 'council'")
    return normalized


async def _content_array_from_uploads(
    content: str,
    files: List[UploadFile],
    *,
    conversation_id: str | None = None,
) -> tuple[Any, List[Dict[str, Any]]]:
    """Process uploads into the same current-content shape used by send."""
    from .file_processor import FileProcessor

    processed_files = []
    file_metadata = []
    for file in files:
        content_bytes = await file.read()
        file_type = file.content_type or ''
        attachment_id = str(uuid.uuid4())
        processed = FileProcessor.process_file(
            file.filename,
            content_bytes,
            file_type,
            query=content,
        )
        items = [processed] if isinstance(processed, dict) else list(processed)
        attachment_ref = None
        if file_type.startswith('image/') and conversation_id:
            attachment_ref = _store_uploaded_attachment(
                conversation_id,
                attachment_id,
                file.filename,
                content_bytes,
                file_type,
            )
            attachment_ref["conversation_id"] = conversation_id
            for item in items:
                if isinstance(item, dict) and item.get("type") == "image_url":
                    item["attachment_ref"] = copy.deepcopy(attachment_ref)

        processed_files.extend(items)
        file_metadata.append({
            'id': attachment_id,
            'name': file.filename,
            'type': file_type,
            'size': len(content_bytes),
            'category': 'image' if file_type.startswith('image/') else 'document',
            **({'attachment_id': attachment_id} if attachment_ref else {}),
        })

    if processed_files:
        return [{"type": "text", "text": content}, *processed_files], file_metadata
    return content, file_metadata


def _with_context_metadata(
    metadata: Dict[str, Any] | None,
    context_package: Dict[str, Any],
    *,
    mode: str | None = None,
) -> Dict[str, Any]:
    """Attach a safe context snapshot to assistant metadata."""
    merged = dict(metadata or {})
    if mode is not None:
        merged["mode"] = mode
    merged["context_snapshot"] = context_package.get("snapshot") or {}
    return merged


async def _build_context_package_for_request(
    conversation_id: str,
    *,
    current_content: Any,
    mode: str,
    before_index: int | None = None,
) -> Dict[str, Any]:
    return await storage.build_context_package(
        conversation_id,
        before_index=before_index,
        current_content=current_content,
        mode=mode,
    )


def _create_turn_record(
    conversation_id: str,
    *,
    user_message_index: int,
    assistant_message_index: int,
    mode: str,
    context_package: Dict[str, Any],
    status: str = "running",
) -> str:
    turn = storage.create_turn_record(
        conversation_id,
        user_message_index=user_message_index,
        assistant_message_index=assistant_message_index,
        mode=mode,
        context_snapshot=context_package.get("snapshot") or {},
        context_payload=_context_payload(context_package),
        status=status,
    )
    return turn["id"]


def _find_turn_for_user_message(conversation: Dict[str, Any], message_index: int) -> Dict[str, Any] | None:
    for turn in conversation.get("turns") or []:
        if turn.get("user_message_index") == message_index:
            return turn
    return None


def _infer_message_mode(messages: List[Dict[str, Any]], message_index: int, turn: Dict[str, Any] | None) -> str:
    if turn and turn.get("mode") in {"quick", "council"}:
        return turn["mode"]

    if message_index + 1 < len(messages):
        next_message = messages[message_index + 1]
        next_metadata = next_message.get("metadata") or {}
        if next_message.get("role") == "assistant" and next_metadata.get("mode") in {"quick", "council"}:
            return next_metadata["mode"]

    return "council"


def _refresh_turn_from_assistant(conversation_id: str, turn_id: str | None, status: str | None = None) -> None:
    if not turn_id:
        return
    try:
        storage.update_turn_from_assistant(conversation_id, turn_id, status=status)
    except Exception as exc:
        print(f"Failed to update turn audit record {turn_id}: {exc}")


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "LLM Council API"}


@app.get("/api/settings/llm")
async def get_llm_settings():
    """Return runtime LLM settings with secrets redacted."""
    return public_llm_settings()


@app.patch("/api/settings/llm")
async def patch_llm_settings(request: UpdateLLMSettingsRequest):
    """Update runtime LLM settings."""
    updates = request.model_dump(exclude_none=True)
    return update_llm_settings(updates) and public_llm_settings()


@app.post("/api/settings/llm/test")
async def test_llm_settings(request: TestLLMSettingsRequest):
    """Test the currently configured provider for a model."""
    model = request.model.strip()
    if not model:
        raise HTTPException(status_code=400, detail="Model is required")

    response = await query_model(
        model,
        [{"role": "user", "content": "Reply with exactly: ok"}],
        timeout=30.0,
    )
    if response and response.get("content"):
        return {
            "ok": True,
            "model": response.get("model") or model,
            "content": response.get("content"),
            "usage": response.get("usage", {}),
        }

    return {
        "ok": False,
        "model": model,
        "error": "No response from configured provider",
    }


@app.get("/api/conversations", response_model=List[ConversationMetadata])
async def list_conversations():
    """List all conversations (metadata only)."""
    return storage.list_conversations()


@app.post("/api/conversations", response_model=Conversation)
async def create_conversation(request: CreateConversationRequest):
    """Create a new conversation."""
    conversation_id = str(uuid.uuid4())
    conversation = storage.create_conversation(conversation_id)
    return conversation


@app.get("/api/conversations/search")
async def search_conversation_history(q: str = "", limit: int = 20):
    """Search locally stored conversations for reusable context."""
    query = q.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Search query is required")
    return {"query": query, "results": storage.search_conversations(query, limit=limit)}


@app.patch("/api/conversations/{conversation_id}", response_model=Conversation)
async def update_conversation_title(conversation_id: str, request: UpdateTitleRequest):
    """
    Update the title of a conversation.

    Args:
        conversation_id: Conversation identifier
        request: Request body containing new title

    Request body:
        {
            "title": "New Title"
        }
    """
    new_title = request.title.strip()

    if not new_title:
        raise HTTPException(status_code=400, detail="Title cannot be empty")

    if len(new_title) > 100:
        raise HTTPException(status_code=400, detail="Title too long (max 100 characters)")

    try:
        # Update title using storage function
        storage.update_conversation_title(conversation_id, new_title)

        # Return updated conversation
        conversation = storage.get_conversation(conversation_id)
        return conversation
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update title: {str(e)}")


@app.get("/api/conversations/{conversation_id}", response_model=Conversation)
async def get_conversation(conversation_id: str):
    """Get a specific conversation with all its messages."""
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@app.post("/api/conversations/{conversation_id}/fork", response_model=Conversation)
async def fork_conversation(conversation_id: str, request: ForkConversationRequest):
    """Create a new conversation branch from the selected message."""
    try:
        return storage.fork_conversation(conversation_id, request.message_index)
    except ValueError as e:
        raise HTTPException(status_code=404 if "not found" in str(e).lower() else 400, detail=str(e))


@app.get("/api/conversations/{conversation_id}/context")
async def get_conversation_context_audit(conversation_id: str):
    """Return context snapshots and model-run audit records for a conversation."""
    try:
        return storage.get_context_audit(conversation_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/conversations/{conversation_id}/context/preview")
async def preview_conversation_context(conversation_id: str, request: ContextPreviewRequest):
    """Preview the next text-only model-facing context package without saving a turn."""
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    try:
        mode = _normalize_request_mode(request.mode)
        context_package = await _build_context_package_for_request(
            conversation_id,
            current_content=request.content,
            mode=mode,
        )
        return _preview_payload(context_package, mode)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/conversations/{conversation_id}/context/preview/files")
async def preview_conversation_context_with_files(
    conversation_id: str,
    content: str = Form(""),
    mode: str = Form("council"),
    files: List[UploadFile] = File(default=[]),
):
    """Preview the next context package for a message with attachments."""
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    try:
        normalized_mode = _normalize_request_mode(mode)
        content_array, file_metadata = await _content_array_from_uploads(content, files)
        context_package = await _build_context_package_for_request(
            conversation_id,
            current_content=content_array,
            mode=normalized_mode,
        )
        return _preview_payload(context_package, normalized_mode, {"file_metadata": file_metadata})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/conversations/{conversation_id}/messages/{message_index}/context/replay")
async def replay_message_context(conversation_id: str, message_index: int, request: ContextReplayRequest):
    """Rebuild the context package for a stored user turn without saving or calling models."""
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = conversation.get("messages", [])
    if message_index < 0 or message_index >= len(messages):
        raise HTTPException(status_code=400, detail="Message index out of range")

    user_message = messages[message_index]
    if user_message.get("role") != "user":
        raise HTTPException(status_code=400, detail="Selected message is not a user message")

    turn = _find_turn_for_user_message(conversation, message_index)
    try:
        mode = _normalize_request_mode(request.mode) if request.mode else _infer_message_mode(messages, message_index, turn)
        context_package = await _build_context_package_for_request(
            conversation_id,
            before_index=message_index,
            current_content=_restore_attachment_content(user_message.get("content", "")),
            mode=mode,
        )
        rebuilt_payload = _preview_payload(context_package, mode)
        base_extra = {
            "message_index": message_index,
            "turn_id": turn.get("id") if turn else None,
            "assistant_message_index": turn.get("assistant_message_index") if turn else None,
            "saved_status": turn.get("status") if turn else None,
            "saved_snapshot": turn.get("context_snapshot") if turn else None,
        }

        saved_context_payload = turn.get("context_payload") if turn else None
        if saved_context_payload:
            saved_messages = (
                saved_context_payload.get("audit_messages")
                or saved_context_payload.get("model_messages")
                or []
            )
            saved_snapshot = turn.get("context_snapshot") or {}
            rebuilt_messages = rebuilt_payload.get("messages") or []
            rebuilt_snapshot = rebuilt_payload.get("snapshot") or {}
            return {
                **rebuilt_payload,
                **base_extra,
                "replay_kind": "saved_context_payload",
                "messages": saved_messages,
                "message_count": len(saved_messages),
                "snapshot": saved_snapshot or rebuilt_snapshot,
                "saved_context_payload": saved_context_payload,
                "rebuilt_messages": rebuilt_messages,
                "rebuilt_message_count": rebuilt_payload.get("message_count") or 0,
                "rebuilt_snapshot": rebuilt_snapshot,
                "comparison": _context_payload_comparison(
                    saved_messages,
                    rebuilt_messages,
                    saved_snapshot,
                    rebuilt_snapshot,
                ),
            }

        return {
            **rebuilt_payload,
            **base_extra,
            "replay_kind": "current_policy_rebuild",
            "comparison": {"available": False, "reason": "No saved context payload for this turn."},
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/conversations/{conversation_id}/context-summary")
async def clear_conversation_context_summary(conversation_id: str):
    """Clear the cached summary used by future context packages."""
    try:
        summary = storage.clear_context_summary(conversation_id)
        return {"context_summary": summary}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/conversations/{conversation_id}/context-summary/rebuild")
async def rebuild_conversation_context_summary(conversation_id: str):
    """Regenerate the cached summary for older active history."""
    try:
        summary = await storage.rebuild_context_summary(conversation_id)
        return {"context_summary": summary}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/conversations/{conversation_id}/context-policy")
async def get_conversation_context_policy(conversation_id: str):
    """Return the effective context policy for one conversation."""
    try:
        return storage.get_context_policy(conversation_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.patch("/api/conversations/{conversation_id}/context-policy")
async def patch_conversation_context_policy(conversation_id: str, request: ContextPolicyRequest):
    """Update the per-conversation context policy."""
    try:
        updates = request.model_dump(exclude_unset=True)
        policy = storage.update_context_policy(conversation_id, updates)
        return {"context_policy": policy}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/conversations/{conversation_id}/context-memory")
async def get_conversation_context_memory(conversation_id: str):
    """Return durable user-managed memory items for one conversation."""
    try:
        return {"context_memory": storage.get_context_memory(conversation_id)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/conversations/{conversation_id}/context-memory")
async def add_conversation_context_memory(conversation_id: str, request: ContextMemoryRequest):
    """Add one durable memory item to future context packages."""
    try:
        memory = storage.add_context_memory(
            conversation_id,
            request.content or "",
            enabled=True if request.enabled is None else request.enabled,
        )
        return {"memory": memory, "context_memory": storage.get_context_memory(conversation_id)}
    except ValueError as e:
        raise HTTPException(status_code=404 if "not found" in str(e).lower() else 400, detail=str(e))


@app.patch("/api/conversations/{conversation_id}/context-memory/{memory_id}")
async def update_conversation_context_memory(
    conversation_id: str,
    memory_id: str,
    request: ContextMemoryRequest,
):
    """Update or enable/disable one durable memory item."""
    try:
        memory = storage.update_context_memory(
            conversation_id,
            memory_id,
            request.model_dump(exclude_unset=True),
        )
        return {"memory": memory, "context_memory": storage.get_context_memory(conversation_id)}
    except ValueError as e:
        raise HTTPException(status_code=404 if "not found" in str(e).lower() else 400, detail=str(e))


@app.delete("/api/conversations/{conversation_id}/context-memory/{memory_id}")
async def delete_conversation_context_memory(conversation_id: str, memory_id: str):
    """Delete one durable memory item."""
    try:
        result = storage.delete_context_memory(conversation_id, memory_id)
        return {**result, "context_memory": storage.get_context_memory(conversation_id)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.patch("/api/conversations/{conversation_id}/messages/{message_index}/pin")
async def pin_conversation_message(conversation_id: str, message_index: int, request: PinMessageRequest):
    """Pin or unpin one message so it can be included in future context packages."""
    try:
        conversation = storage.set_message_pinned(conversation_id, message_index, request.pinned)
        return {
            "conversation": conversation,
            "message_index": message_index,
            "pinned": request.pinned,
        }
    except ValueError as e:
        raise HTTPException(status_code=404 if "not found" in str(e).lower() else 400, detail=str(e))


@app.patch("/api/conversations/{conversation_id}/messages/{message_index}/context-visibility")
async def set_conversation_message_context_visibility(
    conversation_id: str,
    message_index: int,
    request: ContextVisibilityRequest,
):
    """Include or exclude one message from future context packages."""
    try:
        conversation = storage.set_message_context_excluded(conversation_id, message_index, request.excluded)
        return {
            "conversation": conversation,
            "message_index": message_index,
            "context_excluded": request.excluded,
        }
    except ValueError as e:
        raise HTTPException(status_code=404 if "not found" in str(e).lower() else 400, detail=str(e))


@app.post("/api/conversations/{conversation_id}/messages/{message_index}/retry")
async def retry_user_message(conversation_id: str, message_index: int, request: RetryMessageRequest):
    """Retry a stored user turn from scratch without duplicating the user message."""
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = conversation.get("messages", [])
    if message_index < 0 or message_index >= len(messages):
        raise HTTPException(status_code=400, detail="Message index out of range")

    user_message = messages[message_index]
    if user_message.get("role") != "user":
        raise HTTPException(status_code=400, detail="Selected message is not a user message")

    requested_mode = (request.mode or "").strip().lower()
    if requested_mode and requested_mode not in {"quick", "council"}:
        raise HTTPException(status_code=400, detail="Retry mode must be 'quick' or 'council'")

    inferred_mode = "council"
    if message_index + 1 < len(messages):
        next_message = messages[message_index + 1]
        if next_message.get("role") == "assistant" and (next_message.get("metadata") or {}).get("mode") == "quick":
            inferred_mode = "quick"
    mode = requested_mode or inferred_mode

    try:
        storage.truncate_conversation_messages(conversation_id, message_index + 1)
        current_content = _restore_attachment_content(user_message.get("content", ""))
        context_package = await _build_context_package_for_request(
            conversation_id,
            before_index=message_index,
            current_content=current_content,
            mode=mode,
        )
        conversation_history = _context_messages(context_package)

        if mode == "quick":
            stage1_results = []
            stage2_results = []
            stage3_result = await quick_query(current_content, conversation_history)
            metadata = _with_context_metadata({
                "mode": "quick",
                **(stage3_result.get("metadata") or {}),
            }, context_package, mode="quick")
        else:
            stage1_results, stage2_results, stage3_result, metadata = await run_full_council_with_history(
                current_content,
                conversation_history=conversation_history,
            )
            metadata = _with_context_metadata(metadata, context_package, mode="council")

        assistant_message_index = storage.add_assistant_message(
            conversation_id,
            stage1_results,
            stage2_results,
            stage3_result,
            metadata=metadata,
        )
        turn_id = _create_turn_record(
            conversation_id,
            user_message_index=message_index,
            assistant_message_index=assistant_message_index,
            mode=mode,
            context_package=context_package,
            status="complete",
        )
        _refresh_turn_from_assistant(conversation_id, turn_id, status="complete")

        return {
            "stage1_results": stage1_results,
            "stage2_results": stage2_results,
            "stage3_result": stage3_result,
            "metadata": metadata,
            "assistant_message_index": assistant_message_index,
            "conversation": storage.get_conversation(conversation_id),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retry message: {str(e)}")


@app.delete("/api/conversations/{conversation_id}/messages/from/{message_index}")
async def truncate_conversation_messages(conversation_id: str, message_index: int):
    """Delete a conversation suffix, used to keep edited/retried context clean."""
    try:
        return storage.truncate_conversation_messages(conversation_id, message_index)
    except ValueError as e:
        raise HTTPException(status_code=404 if "not found" in str(e).lower() else 400, detail=str(e))


@app.delete("/api/conversations/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: str):
    """
    Delete a conversation.

    Args:
        conversation_id: Conversation identifier

    Returns:
        204 No Content on success

    Raises:
        404: If conversation not found
        500: If deletion fails
    """
    try:
        storage.delete_conversation(conversation_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete conversation: {str(e)}")

    return None


@app.post("/api/conversations/{conversation_id}/message")
async def send_message(conversation_id: str, request: SendMessageRequest):
    """
    Send a message and run the 3-stage council process with conversation history support.
    Returns the complete response with all stages.
    """
    # Check if conversation exists
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check if this is the first message
    is_first_message = len(conversation["messages"]) == 0

    context_package = await _build_context_package_for_request(
        conversation_id,
        current_content=request.content,
        mode="council",
    )
    conversation_history = _context_messages(context_package)

    # Add user message after building history so the current question is not duplicated
    user_message_index = storage.add_user_message(conversation_id, request.content)

    # If this is the first message, generate a title
    if is_first_message:
        title = await generate_conversation_title(request.content)
        storage.update_conversation_title(conversation_id, title)

    # Run the 3-stage council process with conversation history
    stage1_results, stage2_results, stage3_result, metadata = await run_full_council_with_history(
        request.content, conversation_history
    )

    metadata = _with_context_metadata(metadata, context_package, mode="council")

    # Add assistant message with all stages
    assistant_message_index = storage.add_assistant_message(
        conversation_id,
        stage1_results,
        stage2_results,
        stage3_result,
        metadata=metadata,
    )
    turn_id = _create_turn_record(
        conversation_id,
        user_message_index=user_message_index,
        assistant_message_index=assistant_message_index,
        mode="council",
        context_package=context_package,
        status="complete",
    )
    _refresh_turn_from_assistant(conversation_id, turn_id, status="complete")

    # Return the complete response with metadata
    return {
        "stage1": stage1_results,
        "stage2": stage2_results,
        "stage3": stage3_result,
        "metadata": metadata
    }


@app.post("/api/conversations/{conversation_id}/quick")
async def send_quick_message(conversation_id: str, request: SendMessageRequest):
    """
    Send a message and get a quick single-model response without the 3-stage council process.
    """
    # Check if conversation exists
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check if this is the first message
    is_first_message = len(conversation["messages"]) == 0

    context_package = await _build_context_package_for_request(
        conversation_id,
        current_content=request.content,
        mode="quick",
    )
    conversation_history = _context_messages(context_package)

    # Add user message after building history so the current question is not duplicated
    user_message_index = storage.add_user_message(conversation_id, request.content)

    # If this is the first message, generate a title
    if is_first_message:
        title = await generate_conversation_title(request.content)
        storage.update_conversation_title(conversation_id, title)

    # Run quick query
    quick_result = await quick_query(request.content, conversation_history)
    metadata = _with_context_metadata({
        "mode": "quick",
        **(quick_result.get("metadata") or {}),
    }, context_package, mode="quick")

    # Add assistant message (quick responses are stored in stage3 for consistency)
    assistant_message_index = storage.add_assistant_message(
        conversation_id,
        [],  # No stage1
        [],  # No stage2
        quick_result,  # Store in stage3
        metadata=metadata,
    )
    turn_id = _create_turn_record(
        conversation_id,
        user_message_index=user_message_index,
        assistant_message_index=assistant_message_index,
        mode="quick",
        context_package=context_package,
        status="complete",
    )
    _refresh_turn_from_assistant(conversation_id, turn_id, status="complete")

    # Return the quick response
    return {
        "quick": quick_result
    }


@app.post("/api/conversations/{conversation_id}/quick/stream")
async def send_quick_message_stream(conversation_id: str, request: SendMessageRequest):
    """
    Send a message and stream the quick single-model response lifecycle.

    Quick mode still stores responses in stage3 for compatibility with the
    existing conversation renderer, but it avoids the 3-stage council process.
    """
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    is_first_message = len(conversation["messages"]) == 0

    async def event_generator():
        try:
            async def drain_model_events(task: asyncio.Task, queue: asyncio.Queue):
                while not task.done():
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=0.1)
                    except asyncio.TimeoutError:
                        continue
                    yield f"data: {json.dumps(event)}\n\n"

                while not queue.empty():
                    event = queue.get_nowait()
                    yield f"data: {json.dumps(event)}\n\n"

            async def enqueue_model_event(queue: asyncio.Queue, event: Dict[str, Any]) -> None:
                await queue.put({
                    key: value
                    for key, value in event.items()
                    if value is not None
                })

            context_package = await _build_context_package_for_request(
                conversation_id,
                current_content=request.content,
                mode="quick",
            )
            conversation_history = _context_messages(context_package)

            user_message_index = storage.add_user_message(conversation_id, request.content)
            assistant_message_index = storage.create_assistant_partial(conversation_id)
            turn_id = _create_turn_record(
                conversation_id,
                user_message_index=user_message_index,
                assistant_message_index=assistant_message_index,
                mode="quick",
                context_package=context_package,
            )

            def persist_assistant(updates: Dict[str, Any]) -> None:
                storage.update_assistant_partial(
                    conversation_id,
                    assistant_message_index,
                    updates,
                )

            async def enqueue_and_persist_model_event(queue: asyncio.Queue, event: Dict[str, Any]) -> None:
                await enqueue_model_event(queue, event)
                stage = event.get("stage")
                model = event.get("model")
                if stage and model:
                    persist_assistant({
                        "modelStatus": {
                            stage: {
                                model: {
                                    key: value
                                    for key, value in event.items()
                                    if value is not None
                                }
                            }
                        }
                    })

            title_task = None
            if is_first_message:
                title_task = asyncio.create_task(generate_conversation_title(request.content))

            metadata = _with_context_metadata({"mode": "quick"}, context_package, mode="quick")
            persist_assistant({
                "status": "running",
                "stage1": [],
                "stage2": [],
                "metadata": metadata,
                "loading": {
                    "stage1": False,
                    "stage2": False,
                    "stage3": True,
                },
            })
            yield f"data: {json.dumps({'type': 'quick_start'})}\n\n"

            quick_queue: asyncio.Queue = asyncio.Queue()
            quick_task = asyncio.create_task(quick_query(
                request.content,
                conversation_history,
                event_callback=lambda event: enqueue_and_persist_model_event(quick_queue, event),
            ))
            async for event_chunk in drain_model_events(quick_task, quick_queue):
                yield event_chunk
            quick_result = await quick_task

            metadata = _with_context_metadata({
                "mode": "quick",
                **(quick_result.get("metadata") or {}),
            }, context_package, mode="quick")
            persist_assistant({
                "status": "complete",
                "stage1": [],
                "stage2": [],
                "stage3": quick_result,
                "metadata": metadata,
                "loading": {"stage3": False},
                "error": None,
            })
            yield f"data: {json.dumps({'type': 'quick_complete', 'data': quick_result, 'metadata': metadata})}\n\n"
            _refresh_turn_from_assistant(conversation_id, turn_id, status="complete")

            if title_task:
                title = await title_task
                storage.update_conversation_title(conversation_id, title)
                yield f"data: {json.dumps({'type': 'title_complete', 'data': {'title': title}})}\n\n"

            yield f"data: {json.dumps({'type': 'complete'})}\n\n"

        except asyncio.CancelledError:
            if "assistant_message_index" in locals():
                storage.update_assistant_partial(
                    conversation_id,
                    assistant_message_index,
                    {
                        "status": "interrupted",
                        "metadata": _with_context_metadata({"mode": "quick"}, context_package, mode="quick") if "context_package" in locals() else {"mode": "quick"},
                        "error": "Client disconnected before the quick response completed.",
                        "loading": {
                            "stage1": False,
                            "stage2": False,
                            "stage3": False,
                        },
                    },
                )
                _refresh_turn_from_assistant(conversation_id, locals().get("turn_id"), status="interrupted")
            raise
        except Exception as e:
            if "assistant_message_index" in locals():
                error_result = {
                    "model": "quick",
                    "status": "failed",
                    "response": f"Error: {str(e)}",
                    "error_type": "quick_stream_error",
                    "error": str(e),
                }
                storage.update_assistant_partial(
                    conversation_id,
                    assistant_message_index,
                    {
                        "status": "failed",
                        "stage1": [],
                        "stage2": [],
                        "stage3": error_result,
                        "metadata": _with_context_metadata({"mode": "quick"}, context_package, mode="quick") if "context_package" in locals() else {"mode": "quick"},
                        "error": str(e),
                        "loading": {
                            "stage1": False,
                            "stage2": False,
                            "stage3": False,
                        },
                    },
                )
                _refresh_turn_from_assistant(conversation_id, locals().get("turn_id"), status="failed")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@app.post("/api/conversations/{conversation_id}/message/stream")
async def send_message_stream(conversation_id: str, request: SendMessageRequest):
    """
    Send a message and stream the 3-stage council process with conversation history support.
    Returns Server-Sent Events as each stage completes.
    """
    # Check if conversation exists
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check if this is the first message
    is_first_message = len(conversation["messages"]) == 0

    async def event_generator():
        try:
            async def drain_model_events(task: asyncio.Task, queue: asyncio.Queue):
                while not task.done():
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=0.1)
                    except asyncio.TimeoutError:
                        continue
                    yield f"data: {json.dumps(event)}\n\n"

                while not queue.empty():
                    event = queue.get_nowait()
                    yield f"data: {json.dumps(event)}\n\n"

            async def enqueue_model_event(queue: asyncio.Queue, event: Dict[str, Any]) -> None:
                await queue.put({
                    key: value
                    for key, value in event.items()
                    if value is not None
                })

            context_package = await _build_context_package_for_request(
                conversation_id,
                current_content=request.content,
                mode="council",
            )
            conversation_history = _context_messages(context_package)

            # Add user message after building history so the current question is not duplicated
            user_message_index = storage.add_user_message(conversation_id, request.content)
            assistant_message_index = storage.create_assistant_partial(conversation_id)
            turn_id = _create_turn_record(
                conversation_id,
                user_message_index=user_message_index,
                assistant_message_index=assistant_message_index,
                mode="council",
                context_package=context_package,
            )

            def persist_assistant(updates: Dict[str, Any]) -> None:
                storage.update_assistant_partial(
                    conversation_id,
                    assistant_message_index,
                    updates,
                )

            async def enqueue_and_persist_model_event(queue: asyncio.Queue, event: Dict[str, Any]) -> None:
                await enqueue_model_event(queue, event)
                stage = event.get("stage")
                model = event.get("model")
                if stage and model:
                    persist_assistant({
                        "modelStatus": {
                            stage: {
                                model: {
                                    key: value
                                    for key, value in event.items()
                                    if value is not None
                                }
                            }
                        }
                    })

            # Start title generation in parallel (don't await yet)
            title_task = None
            if is_first_message:
                title_task = asyncio.create_task(generate_conversation_title(request.content))

            # Stage 1: Collect responses with history context
            persist_assistant({
                "status": "running",
                "metadata": _with_context_metadata({}, context_package, mode="council"),
                "loading": {"stage1": True},
            })
            yield f"data: {json.dumps({'type': 'stage1_start'})}\n\n"
            stage1_queue: asyncio.Queue = asyncio.Queue()
            stage1_task = asyncio.create_task(stage1_collect_responses_streaming(
                request.content,
                conversation_history,
                event_callback=lambda event: enqueue_and_persist_model_event(stage1_queue, event),
            ))
            async for event_chunk in drain_model_events(stage1_task, stage1_queue):
                yield event_chunk
            stage1_results = await stage1_task
            persist_assistant({
                "stage1": stage1_results,
                "loading": {"stage1": False},
            })
            yield f"data: {json.dumps({'type': 'stage1_complete', 'data': stage1_results})}\n\n"

            if not has_successful_stage1_results(stage1_results):
                metadata = _with_context_metadata({
                    "label_to_model": {},
                    "aggregate_rankings": [],
                    "warnings": ["All Stage 1 model calls failed."],
                }, context_package, mode="council")
                stage2_results = []
                stage3_result = {
                    "model": "error",
                    "status": "failed",
                    "response": "All models failed to respond. Please try again.",
                    "error_type": "all_stage1_models_failed",
                    "error": "No Stage 1 model returned a usable response.",
                }
                persist_assistant({
                    "status": "complete",
                    "stage2": stage2_results,
                    "stage3": stage3_result,
                    "metadata": metadata,
                    "loading": {
                        "stage1": False,
                        "stage2": False,
                        "stage3": False,
                    },
                })
                yield f"data: {json.dumps({'type': 'stage2_complete', 'data': stage2_results, 'metadata': metadata})}\n\n"
                yield f"data: {json.dumps({'type': 'stage3_complete', 'data': stage3_result})}\n\n"
                _refresh_turn_from_assistant(conversation_id, turn_id, status="complete")

                if title_task:
                    title = await title_task
                    storage.update_conversation_title(conversation_id, title)
                    yield f"data: {json.dumps({'type': 'title_complete', 'data': {'title': title}})}\n\n"

                yield f"data: {json.dumps({'type': 'complete'})}\n\n"
                return

            # Stage 2: Collect rankings with history context
            persist_assistant({"loading": {"stage2": True}})
            yield f"data: {json.dumps({'type': 'stage2_start'})}\n\n"
            stage2_queue: asyncio.Queue = asyncio.Queue()
            stage2_task = asyncio.create_task(stage2_collect_rankings_streaming(
                request.content,
                stage1_results,
                conversation_history,
                event_callback=lambda event: enqueue_and_persist_model_event(stage2_queue, event),
            ))
            async for event_chunk in drain_model_events(stage2_task, stage2_queue):
                yield event_chunk
            stage2_results, label_to_model = await stage2_task
            aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)
            metadata = _with_context_metadata({
                "label_to_model": label_to_model,
                "aggregate_rankings": aggregate_rankings,
            }, context_package, mode="council")
            persist_assistant({
                "stage2": stage2_results,
                "metadata": metadata,
                "loading": {"stage2": False},
            })
            yield f"data: {json.dumps({'type': 'stage2_complete', 'data': stage2_results, 'metadata': metadata})}\n\n"

            # Stage 3: Synthesize final answer with history context
            persist_assistant({"loading": {"stage3": True}})
            yield f"data: {json.dumps({'type': 'stage3_start'})}\n\n"
            stage3_queue: asyncio.Queue = asyncio.Queue()
            stage3_task = asyncio.create_task(stage3_synthesize_final_with_history(
                request.content,
                stage1_results,
                stage2_results,
                conversation_history,
                event_callback=lambda event: enqueue_and_persist_model_event(stage3_queue, event),
            ))
            async for event_chunk in drain_model_events(stage3_task, stage3_queue):
                yield event_chunk
            stage3_result = await stage3_task
            persist_assistant({
                "status": "complete",
                "stage3": stage3_result,
                "loading": {"stage3": False},
            })
            yield f"data: {json.dumps({'type': 'stage3_complete', 'data': stage3_result})}\n\n"
            _refresh_turn_from_assistant(conversation_id, turn_id, status="complete")

            # Wait for title generation if it was started
            if title_task:
                title = await title_task
                storage.update_conversation_title(conversation_id, title)
                yield f"data: {json.dumps({'type': 'title_complete', 'data': {'title': title}})}\n\n"

            # Send completion event
            yield f"data: {json.dumps({'type': 'complete'})}\n\n"

        except asyncio.CancelledError:
            if "assistant_message_index" in locals():
                storage.update_assistant_partial(
                    conversation_id,
                    assistant_message_index,
                    {
                        "status": "interrupted",
                        "error": "Client disconnected before the council run completed.",
                        "loading": {
                            "stage1": False,
                            "stage2": False,
                            "stage3": False,
                        },
                    },
                )
                _refresh_turn_from_assistant(conversation_id, locals().get("turn_id"), status="interrupted")
            raise
        except Exception as e:
            if "assistant_message_index" in locals():
                storage.update_assistant_partial(
                    conversation_id,
                    assistant_message_index,
                    {
                        "status": "failed",
                        "error": str(e),
                        "loading": {
                            "stage1": False,
                            "stage2": False,
                            "stage3": False,
                        },
                    },
                )
                _refresh_turn_from_assistant(conversation_id, locals().get("turn_id"), status="failed")
            # Send error event
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@app.post("/api/conversations/{conversation_id}/messages/{message_index}/resume/stream")
async def resume_message_stream(conversation_id: str, message_index: int):
    """
    Resume a persisted partial council response from the earliest missing stage.

    This reuses completed Stage 1/2 results when available and updates the same
    assistant message in storage instead of appending a duplicate response.
    """
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    try:
        user_index, user_message = _find_preceding_user_message(
            conversation.get("messages", []),
            message_index,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    assistant_message = conversation["messages"][message_index]
    if _stage3_is_complete(assistant_message.get("stage3")):
        raise HTTPException(status_code=400, detail="Assistant response is already complete")

    user_query = user_message.get("content", "")

    async def event_generator():
        try:
            async def drain_model_events(task: asyncio.Task, queue: asyncio.Queue):
                while not task.done():
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=0.1)
                    except asyncio.TimeoutError:
                        continue
                    yield f"data: {json.dumps(event)}\n\n"

                while not queue.empty():
                    event = queue.get_nowait()
                    yield f"data: {json.dumps(event)}\n\n"

            async def enqueue_model_event(queue: asyncio.Queue, event: Dict[str, Any]) -> None:
                await queue.put({
                    key: value
                    for key, value in event.items()
                    if value is not None
                })

            def persist_assistant(updates: Dict[str, Any]) -> None:
                storage.update_assistant_partial(conversation_id, message_index, updates)

            async def enqueue_and_persist_model_event(queue: asyncio.Queue, event: Dict[str, Any]) -> None:
                await enqueue_model_event(queue, event)
                stage = event.get("stage")
                model = event.get("model")
                if stage and model:
                    persist_assistant({
                        "modelStatus": {
                            stage: {
                                model: {
                                    key: value
                                    for key, value in event.items()
                                    if value is not None
                                }
                            }
                        }
                    })

            context_package = await _build_context_package_for_request(
                conversation_id,
                before_index=user_index,
                current_content=user_query,
                mode="council_resume",
            )
            conversation_history = _context_messages(context_package)

            current_conversation = storage.get_conversation(conversation_id)
            assistant = current_conversation["messages"][message_index]
            turn_id = assistant.get("turn_id")
            if turn_id:
                storage.update_turn_record(
                    conversation_id,
                    turn_id,
                    status="running",
                    context_snapshot=context_package.get("snapshot") or {},
                    context_payload=_context_payload(context_package),
                )
            else:
                turn_id = _create_turn_record(
                    conversation_id,
                    user_message_index=user_index,
                    assistant_message_index=message_index,
                    mode="council_resume",
                    context_package=context_package,
                )
            stage1_results = assistant.get("stage1")
            stage2_results = assistant.get("stage2")

            persist_assistant({
                "status": "running",
                "error": None,
                "loading": {
                    "stage1": False,
                    "stage2": False,
                    "stage3": False,
                },
            })

            if not has_successful_stage1_results(stage1_results or []):
                persist_assistant({
                    "stage1": None,
                    "stage2": None,
                    "stage3": None,
                    "metadata": None,
                    "modelStatus": {
                        "stage1": {},
                        "stage2": {},
                        "stage3": {},
                    },
                    "loading": {"stage1": True},
                })
                yield f"data: {json.dumps({'type': 'stage1_start'})}\n\n"
                stage1_queue: asyncio.Queue = asyncio.Queue()
                stage1_task = asyncio.create_task(stage1_collect_responses_streaming(
                    user_query,
                    conversation_history,
                    event_callback=lambda event: enqueue_and_persist_model_event(stage1_queue, event),
                ))
                async for event_chunk in drain_model_events(stage1_task, stage1_queue):
                    yield event_chunk
                stage1_results = await stage1_task
                persist_assistant({
                    "stage1": stage1_results,
                    "loading": {"stage1": False},
                })
                yield f"data: {json.dumps({'type': 'stage1_complete', 'data': stage1_results})}\n\n"

            if not has_successful_stage1_results(stage1_results or []):
                metadata = _with_context_metadata({
                    "label_to_model": {},
                    "aggregate_rankings": [],
                    "warnings": ["All Stage 1 model calls failed."],
                }, context_package, mode="council_resume")
                stage2_results = []
                stage3_result = {
                    "model": "error",
                    "status": "failed",
                    "response": "All models failed to respond. Please try again.",
                    "error_type": "all_stage1_models_failed",
                    "error": "No Stage 1 model returned a usable response.",
                }
                persist_assistant({
                    "status": "complete",
                    "stage2": stage2_results,
                    "stage3": stage3_result,
                    "metadata": metadata,
                    "loading": {
                        "stage1": False,
                        "stage2": False,
                        "stage3": False,
                    },
                })
                yield f"data: {json.dumps({'type': 'stage2_complete', 'data': stage2_results, 'metadata': metadata})}\n\n"
                yield f"data: {json.dumps({'type': 'stage3_complete', 'data': stage3_result})}\n\n"
                _refresh_turn_from_assistant(conversation_id, turn_id, status="complete")
                yield f"data: {json.dumps({'type': 'complete'})}\n\n"
                return

            if not has_successful_stage2_results(stage2_results or []):
                persist_assistant({
                    "stage2": None,
                    "stage3": None,
                    "metadata": None,
                    "modelStatus": {
                        "stage2": {},
                        "stage3": {},
                    },
                    "loading": {"stage2": True},
                })
                yield f"data: {json.dumps({'type': 'stage2_start'})}\n\n"
                stage2_queue: asyncio.Queue = asyncio.Queue()
                stage2_task = asyncio.create_task(stage2_collect_rankings_streaming(
                    user_query,
                    stage1_results,
                    conversation_history,
                    event_callback=lambda event: enqueue_and_persist_model_event(stage2_queue, event),
                ))
                async for event_chunk in drain_model_events(stage2_task, stage2_queue):
                    yield event_chunk
                stage2_results, label_to_model = await stage2_task
                aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)
                metadata = _with_context_metadata({
                    "label_to_model": label_to_model,
                    "aggregate_rankings": aggregate_rankings,
                }, context_package, mode="council_resume")
                persist_assistant({
                    "stage2": stage2_results,
                    "metadata": metadata,
                    "loading": {"stage2": False},
                })
                yield f"data: {json.dumps({'type': 'stage2_complete', 'data': stage2_results, 'metadata': metadata})}\n\n"
            else:
                metadata = assistant.get("metadata") or {}
                if not _metadata_has_label_mapping(metadata):
                    metadata = _rebuild_stage2_metadata(stage1_results, stage2_results)
                metadata = _with_context_metadata(metadata, context_package, mode="council_resume")
                persist_assistant({"metadata": metadata})

            persist_assistant({
                "stage3": None,
                "modelStatus": {"stage3": {}},
                "loading": {"stage3": True},
            })
            yield f"data: {json.dumps({'type': 'stage3_start'})}\n\n"
            stage3_queue: asyncio.Queue = asyncio.Queue()
            stage3_task = asyncio.create_task(stage3_synthesize_final_with_history(
                user_query,
                stage1_results,
                stage2_results,
                conversation_history,
                event_callback=lambda event: enqueue_and_persist_model_event(stage3_queue, event),
            ))
            async for event_chunk in drain_model_events(stage3_task, stage3_queue):
                yield event_chunk
            stage3_result = await stage3_task
            persist_assistant({
                "status": "complete",
                "stage3": stage3_result,
                "metadata": metadata,
                "loading": {"stage3": False},
            })
            yield f"data: {json.dumps({'type': 'stage3_complete', 'data': stage3_result})}\n\n"
            _refresh_turn_from_assistant(conversation_id, turn_id, status="complete")
            yield f"data: {json.dumps({'type': 'complete'})}\n\n"

        except asyncio.CancelledError:
            storage.update_assistant_partial(
                conversation_id,
                message_index,
                {
                    "status": "interrupted",
                    "error": "Client disconnected before the council resume completed.",
                    "loading": {
                        "stage1": False,
                        "stage2": False,
                        "stage3": False,
                    },
                },
            )
            _refresh_turn_from_assistant(conversation_id, locals().get("turn_id"), status="interrupted")
            raise
        except Exception as e:
            storage.update_assistant_partial(
                conversation_id,
                message_index,
                {
                    "status": "failed",
                    "error": str(e),
                    "loading": {
                        "stage1": False,
                        "stage2": False,
                        "stage3": False,
                    },
                },
            )
            _refresh_turn_from_assistant(conversation_id, locals().get("turn_id"), status="failed")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


# File Upload Endpoints

@app.post("/api/conversations/{conversation_id}/message/files")
async def send_message_with_files(
    conversation_id: str,
    content: str = Form(...),
    mode: str = Form("council"),
    files: List[UploadFile] = File(default=[])
):
    """
    Send message with file attachments (images/PDFs).

    Args:
        conversation_id: Conversation identifier
        content: Text message content
        files: List of uploaded files

    Returns:
        Council results with stage1, stage2, stage3 responses
    """
    try:
        conversation = storage.get_conversation(conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

        mode = _normalize_request_mode(mode)
        is_first_message = len(conversation["messages"]) == 0

        content_array, file_metadata = await _content_array_from_uploads(
            content,
            files,
            conversation_id=conversation_id,
        )

        # Build prior conversation context package before saving the current turn.
        context_package = await _build_context_package_for_request(
            conversation_id,
            current_content=content_array,
            mode=mode,
        )
        conversation_history = _context_messages(context_package)

        if mode == "quick":
            stage1_results = []
            stage2_results = []
            stage3_result = await quick_query(content_array, conversation_history)
            metadata = _with_context_metadata({
                "mode": "quick",
                **(stage3_result.get("metadata") or {}),
            }, context_package, mode="quick")
        else:
            stage1_results, stage2_results, stage3_result, metadata = await run_full_council_with_history(
                content_array,
                conversation_history=conversation_history
            )
            metadata = _with_context_metadata(metadata, context_package, mode="council")

        # 5. Save user message (with file metadata). Binary image payloads are not persisted.
        user_message_index = storage.add_user_message(
            conversation_id,
            _persistent_user_content(content_array),
            files=file_metadata,
        )

        # 6. Save assistant response
        assistant_message_index = storage.add_assistant_message(
            conversation_id,
            stage1_results,
            stage2_results,
            stage3_result,
            metadata=metadata,
        )
        turn_id = _create_turn_record(
            conversation_id,
            user_message_index=user_message_index,
            assistant_message_index=assistant_message_index,
            mode=mode,
            context_package=context_package,
            status="complete",
        )
        _refresh_turn_from_assistant(conversation_id, turn_id, status="complete")

        if is_first_message:
            title = await generate_conversation_title(content)
            storage.update_conversation_title(conversation_id, title)

        # 7. Clear pending file queue after a successful send. Sent files remain
        # attached to the user message via metadata.
        storage.update_file_queue(conversation_id, [])

        return {
            "stage1_results": stage1_results,
            "stage2_results": stage2_results,
            "stage3_result": stage3_result,
            "metadata": metadata,
            "file_metadata": file_metadata,
            "file_queue": []
        }

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send message with files: {str(e)}")


@app.get("/api/conversations/{conversation_id}/file_queue")
async def get_file_queue(conversation_id: str):
    """
    Get the file queue for a conversation.

    Args:
        conversation_id: Conversation identifier

    Returns:
        Dict with files list
    """
    try:
        files = storage.get_file_queue(conversation_id)
        return {"files": files}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get file queue: {str(e)}")


@app.patch("/api/conversations/{conversation_id}/file_queue")
async def update_file_queue_endpoint(
    conversation_id: str,
    request: UpdateFileQueueRequest
):
    """
    Update the file queue for a conversation.

    Args:
        conversation_id: Conversation identifier
        request.files: List of file metadata dicts

    Returns:
        Success confirmation

    Used when user manually deletes files from the queue
    """
    try:
        storage.update_file_queue(conversation_id, request.files)
        return {"success": True}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update file queue: {str(e)}")


if __name__ == "__main__":
    import os
    import uvicorn

    host = os.getenv("BACKEND_HOST", "0.0.0.0")
    port = int(os.getenv("BACKEND_PORT", "8001"))
    uvicorn.run(app, host=host, port=port)
