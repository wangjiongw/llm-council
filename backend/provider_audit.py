"""Audit-safe provider request payload helpers."""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
from typing import Any, Callable, Dict, List, Optional

AUDIT_PAYLOAD_TEXT_LIMIT = 16_000
AUDIT_PAYLOAD_ITEM_TEXT_LIMIT = 8_000
REDACTION_POLICY_VERSION = "provider_audit_redaction_v1"


def _stats() -> Dict[str, Any]:
    return {
        "redacted_image_items": 0,
        "truncated_text_items": 0,
        "original_text_chars": 0,
        "stored_text_chars": 0,
    }


def truncate_audit_text(value: str, limit: int, stats: Dict[str, Any]) -> str:
    stats["original_text_chars"] += len(value)
    if len(value) <= limit:
        stats["stored_text_chars"] += len(value)
        return value

    stats["truncated_text_items"] += 1
    truncated = value[:limit].rstrip() + f"\n\n[Truncated audit payload text to {limit} characters]"
    stats["stored_text_chars"] += len(truncated)
    return truncated


def audit_safe_content(content: Any, stats: Dict[str, Any] | None = None) -> Any:
    """Return an audit-safe copy of OpenAI-compatible message content."""
    stats = stats if stats is not None else _stats()
    if isinstance(content, str):
        return truncate_audit_text(content, AUDIT_PAYLOAD_TEXT_LIMIT, stats)

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
                safe_item["text"] = truncate_audit_text(str(item.get("text", "")), AUDIT_PAYLOAD_ITEM_TEXT_LIMIT, stats)
            safe_items.append(safe_item)
        return safe_items

    if isinstance(content, dict):
        if content.get("type") == "image_url":
            stats["redacted_image_items"] += 1
            safe_content = {"type": "image_url", "image_url": {"url": "[redacted image data URI]", "redacted": True}}
            if content.get("image_url", {}).get("detail"):
                safe_content["image_url"]["detail"] = content["image_url"]["detail"]
            if content.get("attachment_ref"):
                safe_content["attachment_ref"] = copy.deepcopy(content["attachment_ref"])
            return safe_content
        safe_content = copy.deepcopy(content)
        if "content" in safe_content:
            safe_content["content"] = audit_safe_content(safe_content["content"], stats)
        return safe_content

    return copy.deepcopy(content)


def audit_safe_messages(messages: List[Dict[str, Any]], stats: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    stats = stats if stats is not None else _stats()
    safe_messages = []
    for message in messages:
        safe_message = copy.deepcopy(message)
        safe_message["content"] = audit_safe_content(message.get("content", ""), stats)
        safe_messages.append(safe_message)
    return safe_messages


def redaction_policy(stats: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return {
        "version": REDACTION_POLICY_VERSION,
        "image_data": "redacted",
        "max_text_chars": AUDIT_PAYLOAD_TEXT_LIMIT,
        "max_item_text_chars": AUDIT_PAYLOAD_ITEM_TEXT_LIMIT,
        **({"stats": copy.deepcopy(stats)} if stats is not None else {}),
    }


def canonical_digest(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def provider_payload_preview(
    *,
    model: str,
    messages: List[Dict[str, Any]],
    stream: bool,
    stats: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    stats = stats if stats is not None else _stats()
    payload = {
        "model": model,
        "messages": audit_safe_messages(messages, stats),
    }
    if stream:
        payload["stream"] = True
    return payload


def default_source_map(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    message_refs = []
    for package_index, message in enumerate(messages):
        ref = {"provider_message_index": package_index, "role": message.get("role")}
        if message.get("source") is not None:
            ref["source"] = message.get("source")
        if message.get("message_index") is not None:
            ref["message_index"] = message.get("message_index")
        if message.get("pinned") is not None:
            ref["pinned"] = bool(message.get("pinned"))
        message_refs.append(ref)
    return {"message_refs": message_refs}


def provider_source_map(
    messages: List[Dict[str, Any]],
    *,
    context_source_map: Optional[Dict[str, Any]] = None,
    turn_lineage: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Map the actual provider messages while retaining context-package lineage."""
    source_map = default_source_map(messages)
    context_refs = (context_source_map or {}).get("message_refs") or []
    current_index = (turn_lineage or {}).get("user_message_index")
    turn_id = (turn_lineage or {}).get("turn_id")

    current_provider_ref = None
    for ref in source_map["message_refs"]:
        if context_refs:
            ref["includes_context_package"] = True
        if ref.get("role") == "user":
            current_provider_ref = ref

    if current_index is not None and current_provider_ref is not None:
        current_provider_ref["includes_current_user_message"] = True
        current_provider_ref["current_user_message_index"] = current_index
        if turn_id is not None:
            current_provider_ref["turn_id"] = turn_id

    if context_refs:
        source_map["context_package_message_refs"] = copy.deepcopy(context_refs)
    if current_index is not None:
        current_ref = {
            "source": "current_user_turn",
            "message_index": current_index,
        }
        if turn_id is not None:
            current_ref["turn_id"] = turn_id
        source_map["current_message_ref"] = current_ref
    return source_map


def make_provider_request_audit(
    *,
    model: str,
    messages: List[Dict[str, Any]],
    stream: bool,
    call_kind: str,
    stage: str,
    provider_function: str,
    source_map: Optional[Dict[str, Any]] = None,
    turn_lineage: Optional[Dict[str, Any]] = None,
    attempt: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    stats = _stats()
    preview = provider_payload_preview(model=model, messages=messages, stream=stream, stats=stats)
    return {
        "schema": "provider_request_audit_v1",
        "call_kind": call_kind,
        "stage": stage,
        "model": model,
        "provider_function": provider_function,
        "digest": canonical_digest(preview),
        "payload_preview": preview,
        "source_map": provider_source_map(
            messages,
            context_source_map=source_map,
            turn_lineage=turn_lineage,
        ),
        "turn_lineage": copy.deepcopy(turn_lineage) if turn_lineage is not None else {},
        "attempt": copy.deepcopy(attempt) if attempt is not None else None,
        "metadata": copy.deepcopy(metadata) if metadata is not None else {},
        "redaction_policy": redaction_policy(stats),
        "canonicalization": "json_sha256_sort_keys_redacted_payload_v1",
    }


async def emit_provider_request_audit(callback: Optional[Callable[[Dict[str, Any]], Any]], entry: Dict[str, Any]) -> None:
    if not callback:
        return
    result = callback(entry)
    if inspect.isawaitable(result):
        await result
