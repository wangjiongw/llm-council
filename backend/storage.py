"""JSON-based storage for conversations."""

import copy
import json
import os
import shutil
import threading
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional, Union
from pathlib import Path
from .config import DATA_DIR


_lock_registry_guard = threading.Lock()
_conversation_locks: Dict[str, threading.RLock] = {}


def _conversation_lock(conversation_id: str) -> threading.RLock:
    with _lock_registry_guard:
        lock = _conversation_locks.get(conversation_id)
        if lock is None:
            lock = threading.RLock()
            _conversation_locks[conversation_id] = lock
        return lock


def _write_json_atomic(path: str, payload: Dict[str, Any]) -> None:
    tmp_path = f"{path}.tmp-{os.getpid()}-{threading.get_ident()}"
    with open(tmp_path, 'w') as f:
        json.dump(payload, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


def _attachment_dir(conversation_id: str) -> str:
    return os.path.join(DATA_DIR, "attachments", conversation_id)


def _attachment_path(conversation_id: str, attachment_id: str) -> str:
    return os.path.join(_attachment_dir(conversation_id), os.path.basename(str(attachment_id)))


def _iter_attachment_refs(value: Any):
    if isinstance(value, dict):
        ref = value.get("attachment_ref")
        if isinstance(ref, dict) and ref.get("id"):
            yield ref
        for child in value.values():
            yield from _iter_attachment_refs(child)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_attachment_refs(item)


def _attachment_ref_keys(value: Any, conversation_id: Optional[str] = None) -> set[tuple[str, str]]:
    keys = set()
    for ref in _iter_attachment_refs(value):
        ref_conversation_id = ref.get("conversation_id") or conversation_id
        attachment_id = ref.get("id")
        if ref_conversation_id and attachment_id:
            keys.add((str(ref_conversation_id), str(attachment_id)))
    return keys


def _rewrite_attachment_refs_for_branch(value: Any, source_conversation_id: str, branch_id: str) -> None:
    if isinstance(value, dict):
        ref = value.get("attachment_ref")
        if isinstance(ref, dict) and ref.get("id"):
            source_id = str(ref.get("conversation_id") or source_conversation_id)
            attachment_id = str(ref["id"])
            source_path = _attachment_path(source_id, attachment_id)
            target_path = _attachment_path(branch_id, attachment_id)
            if os.path.exists(source_path):
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                shutil.copy2(source_path, target_path)
                ref["conversation_id"] = branch_id
        for child in value.values():
            _rewrite_attachment_refs_for_branch(child, source_conversation_id, branch_id)
    elif isinstance(value, list):
        for item in value:
            _rewrite_attachment_refs_for_branch(item, source_conversation_id, branch_id)


def _delete_unreferenced_attachments(conversation_id: str, removed_payload: Any, remaining_payload: Any) -> None:
    removed_keys = _attachment_ref_keys(removed_payload, conversation_id)
    if not removed_keys:
        return
    remaining_keys = _attachment_ref_keys(remaining_payload, conversation_id)
    for ref_conversation_id, attachment_id in removed_keys - remaining_keys:
        if ref_conversation_id != conversation_id:
            continue
        path = _attachment_path(conversation_id, attachment_id)
        if os.path.exists(path):
            os.remove(path)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def default_context_policy() -> Dict[str, Any]:
    return {
        "token_budget": _clamp_int(_env_int("CONVERSATION_CONTEXT_TOKEN_BUDGET", 24000), 24000, 1000, 200000),
        "recent_turns": _clamp_int(_env_int("CONVERSATION_CONTEXT_RECENT_TURNS", 10), 10, 1, 100),
        "message_char_limit": _clamp_int(_env_int("CONVERSATION_CONTEXT_MESSAGE_CHAR_LIMIT", 16000), 16000, 1000, 120000),
        "summarize_older": True,
        "use_pinned": True,
        "pin_message_char_limit": _clamp_int(_env_int("CONVERSATION_CONTEXT_PIN_MESSAGE_CHAR_LIMIT", 4000), 4000, 200, 60000),
        "pin_max_chars": _clamp_int(_env_int("CONVERSATION_CONTEXT_PIN_MAX_CHARS", 8000), 8000, 0, 120000),
        "use_memory": True,
        "memory_item_char_limit": _clamp_int(_env_int("CONVERSATION_CONTEXT_MEMORY_ITEM_CHAR_LIMIT", 4000), 4000, 200, 60000),
        "memory_max_chars": _clamp_int(_env_int("CONVERSATION_CONTEXT_MEMORY_MAX_CHARS", 8000), 8000, 0, 120000),
    }


def normalize_context_policy(policy: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    defaults = default_context_policy()
    source = policy or {}
    return {
        "token_budget": _clamp_int(source.get("token_budget"), defaults["token_budget"], 1000, 200000),
        "recent_turns": _clamp_int(source.get("recent_turns"), defaults["recent_turns"], 1, 100),
        "message_char_limit": _clamp_int(source.get("message_char_limit"), defaults["message_char_limit"], 1000, 120000),
        "summarize_older": bool(source.get("summarize_older", defaults["summarize_older"])),
        "use_pinned": bool(source.get("use_pinned", defaults["use_pinned"])),
        "pin_message_char_limit": _clamp_int(source.get("pin_message_char_limit"), defaults["pin_message_char_limit"], 200, 60000),
        "pin_max_chars": _clamp_int(source.get("pin_max_chars"), defaults["pin_max_chars"], 0, 120000),
        "use_memory": bool(source.get("use_memory", defaults["use_memory"])),
        "memory_item_char_limit": _clamp_int(source.get("memory_item_char_limit"), defaults["memory_item_char_limit"], 200, 60000),
        "memory_max_chars": _clamp_int(source.get("memory_max_chars"), defaults["memory_max_chars"], 0, 120000),
    }


def ensure_data_dir():
    """Ensure the data directory exists."""
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)


def get_conversation_path(conversation_id: str) -> str:
    """Get the file path for a conversation."""
    return os.path.join(DATA_DIR, f"{conversation_id}.json")


MAX_CONVERSATION_TAGS = 20
MAX_CONVERSATION_TAG_LENGTH = 32


def _normalize_conversation_tags(tags: Any) -> List[str]:
    if not isinstance(tags, list):
        return []

    normalized = []
    seen = set()
    for tag in tags:
        clean_tag = str(tag or "").strip()
        if not clean_tag:
            continue
        clean_tag = " ".join(clean_tag.split())[:MAX_CONVERSATION_TAG_LENGTH]
        key = clean_tag.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(clean_tag)
        if len(normalized) >= MAX_CONVERSATION_TAGS:
            break
    return normalized


def _touch_conversation(conversation: Dict[str, Any], when: Optional[str] = None) -> str:
    timestamp = when or datetime.utcnow().isoformat()
    conversation["updated_at"] = timestamp
    return timestamp


def _ensure_conversation_metadata(conversation: Dict[str, Any]) -> Dict[str, Any]:
    if not conversation.get("created_at"):
        conversation["created_at"] = datetime.utcnow().isoformat()
    conversation["updated_at"] = str(conversation.get("updated_at") or conversation.get("created_at"))
    conversation["favorite"] = bool(conversation.get("favorite", False))
    conversation["archived"] = bool(conversation.get("archived", False))
    conversation["pinned"] = bool(conversation.get("pinned", False))
    conversation["tags"] = _normalize_conversation_tags(conversation.get("tags"))
    return conversation


def _conversation_metadata(conversation: Dict[str, Any]) -> Dict[str, Any]:
    normalized = _ensure_conversation_metadata(dict(conversation))
    return {
        "id": normalized["id"],
        "created_at": normalized["created_at"],
        "updated_at": normalized["updated_at"],
        "title": normalized.get("title", "New Conversation"),
        "message_count": len(normalized.get("messages") or []),
        "favorite": normalized["favorite"],
        "archived": normalized["archived"],
        "pinned": normalized["pinned"],
        "tags": normalized["tags"],
    }


def create_conversation(conversation_id: str) -> Dict[str, Any]:
    """
    Create a new conversation.

    Args:
        conversation_id: Unique identifier for the conversation

    Returns:
        New conversation dict
    """
    with _conversation_lock(conversation_id):
        ensure_data_dir()

        now = datetime.utcnow().isoformat()
        conversation = {
            "id": conversation_id,
            "created_at": now,
            "updated_at": now,
            "title": "New Conversation",
            "favorite": False,
            "archived": False,
            "pinned": False,
            "tags": [],
            "messages": [],
            "turns": [],
            "context_summary": _empty_summary_state(),
            "context_policy": normalize_context_policy(),
            "context_memory": [],
        }

        save_conversation(conversation)
        return conversation


def get_conversation(conversation_id: str) -> Optional[Dict[str, Any]]:
    """
    Load a conversation from storage.

    Args:
        conversation_id: Unique identifier for the conversation

    Returns:
        Conversation dict or None if not found
    """
    with _conversation_lock(conversation_id):
        path = get_conversation_path(conversation_id)

        if not os.path.exists(path):
            return None

        with open(path, 'r') as f:
            return json.load(f)


def save_conversation(conversation: Dict[str, Any]):
    """
    Save a conversation to storage.

    Args:
        conversation: Conversation dict to save
    """
    ensure_data_dir()

    conversation_id = conversation['id']
    with _conversation_lock(conversation_id):
        _ensure_conversation_metadata(conversation)
        path = get_conversation_path(conversation_id)
        _write_json_atomic(path, conversation)


def list_conversations() -> List[Dict[str, Any]]:
    """
    List all conversations (metadata only).

    Returns:
        List of conversation metadata dicts
    """
    ensure_data_dir()

    conversations = []
    for filename in os.listdir(DATA_DIR):
        if filename.endswith('.json'):
            path = os.path.join(DATA_DIR, filename)
            with open(path, 'r') as f:
                data = json.load(f)
                if "id" not in data or "messages" not in data:
                    continue
                conversations.append(_conversation_metadata(data))

    conversations.sort(
        key=lambda item: (
            bool(item.get("pinned")),
            item.get("updated_at") or item.get("created_at") or "",
        ),
        reverse=True,
    )

    return conversations


def _search_excerpt(text: str, terms: List[str], max_chars: int = 320) -> str:
    clean_text = " ".join(str(text or "").split())
    if len(clean_text) <= max_chars:
        return clean_text

    lowered = clean_text.lower()
    first_match = min(
        [idx for term in terms if term and (idx := lowered.find(term)) >= 0] or [0]
    )
    start = max(0, first_match - max_chars // 3)
    end = min(len(clean_text), start + max_chars)
    start = max(0, end - max_chars)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(clean_text) else ""
    return prefix + clean_text[start:end].strip() + suffix


def _search_score(text: str, terms: List[str]) -> int:
    lowered = str(text or "").lower()
    return sum(lowered.count(term) for term in terms if term)


def search_conversations(query: str, *, limit: int = 20) -> List[Dict[str, Any]]:
    """Search titles, memory, user messages, and final assistant responses."""
    clean_query = " ".join(str(query or "").split())
    if not clean_query:
        return []

    terms = [term.lower() for term in clean_query.split() if term]
    if not terms:
        return []

    limit = _clamp_int(limit, 20, 1, 100)
    ensure_data_dir()
    results: List[Dict[str, Any]] = []

    for filename in os.listdir(DATA_DIR):
        if not filename.endswith('.json'):
            continue
        path = os.path.join(DATA_DIR, filename)
        try:
            with open(path, 'r') as f:
                conversation = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue

        conversation_id = conversation.get("id")
        messages = conversation.get("messages") or []
        if not conversation_id or not isinstance(messages, list):
            continue

        title = conversation.get("title", "New Conversation")
        created_at = conversation.get("created_at")
        conversation_modes = sorted({
            str((message.get("metadata") or {}).get("mode") or "")
            for message in messages
            if isinstance(message, dict) and (message.get("metadata") or {}).get("mode")
        })
        conversation_search_metadata = {
            "updated_at": conversation.get("updated_at") or created_at,
            "favorite": bool(conversation.get("favorite")),
            "archived": bool(conversation.get("archived")),
            "conversation_pinned": bool(conversation.get("pinned")),
            "tags": _normalize_conversation_tags(conversation.get("tags")),
            "modes": conversation_modes,
            "has_files": any(bool(message.get("files")) for message in messages if isinstance(message, dict)),
            "has_failed_run": any(
                message.get("status") in {"failed", "interrupted"} or (message.get("stage3") or {}).get("status") in {"failed", "interrupted"}
                for message in messages
                if isinstance(message, dict)
            ),
        }
        title_score = _search_score(title, terms)
        if title_score:
            results.append({
                "conversation_id": conversation_id,
                "conversation_title": title,
                "created_at": created_at,
                "source": "title",
                "role": "conversation",
                "message_index": None,
                "memory_id": None,
                "content": title,
                "excerpt": _search_excerpt(title, terms),
                "score": title_score + 3,
                **conversation_search_metadata,
            })

        for memory in _normalize_context_memory(conversation.get("context_memory")):
            content = memory.get("content", "")
            score = _search_score(content, terms)
            if not score:
                continue
            results.append({
                "conversation_id": conversation_id,
                "conversation_title": title,
                "created_at": created_at,
                "source": "memory",
                "role": "memory",
                "message_index": None,
                "memory_id": memory.get("id"),
                "content": _truncate_text(content, 2000, "search result"),
                "excerpt": _search_excerpt(content, terms),
                "score": score + 2,
                "enabled": bool(memory.get("enabled")),
                **conversation_search_metadata,
            })

        for index, message in enumerate(messages):
            role = message.get("role")
            if role not in {"user", "assistant"}:
                continue
            entry = _message_context_entry(message, index)
            if not entry:
                continue
            content = entry.get("content", "")
            searchable = f"{title} {role} {content}"
            score = _search_score(searchable, terms)
            if not score:
                continue
            metadata = message.get("metadata") or {}
            stage3 = message.get("stage3") or {}
            results.append({
                "conversation_id": conversation_id,
                "conversation_title": title,
                "created_at": created_at,
                "source": "message",
                "role": role,
                "message_index": index,
                "memory_id": None,
                "content": _truncate_text(content, 2000, "search result"),
                "excerpt": _search_excerpt(content, terms),
                "score": score,
                "context_excluded": bool(message.get("context_excluded")),
                "pinned": bool(message.get("pinned")),
                "mode": metadata.get("mode") or stage3.get("metadata", {}).get("mode"),
                "status": message.get("status") or stage3.get("status"),
                "has_files": bool(message.get("files")),
                **conversation_search_metadata,
            })

    results.sort(key=lambda item: (item.get("score", 0), item.get("created_at") or ""), reverse=True)
    return results[:limit]


def add_user_message(
    conversation_id: str,
    content: Union[str, List[Dict[str, Any]]],
    files: Optional[List[Dict[str, Any]]] = None
):
    """
    Add a user message to a conversation.

    Args:
        conversation_id: Conversation identifier
        content: User message content (text or multimodal array)
        files: Optional list of file metadata for UI display
    """
    with _conversation_lock(conversation_id):
        conversation = get_conversation(conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        message = {
            "role": "user",
            "content": content
        }

        # Add file metadata if provided (for UI display, not sent to LLM)
        if files:
            message["files"] = files

        conversation["messages"].append(message)
        message_index = len(conversation["messages"]) - 1
        _touch_conversation(conversation)
        save_conversation(conversation)
        return message_index


def update_user_message_content(
    conversation_id: str,
    message_index: int,
    content: Union[str, List[Dict[str, Any]]],
) -> Dict[str, Any]:
    """Replace the content of an existing user message."""
    with _conversation_lock(conversation_id):
        conversation = get_conversation(conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        messages = conversation.get("messages", [])
        if message_index < 0 or message_index >= len(messages):
            raise ValueError("Message index out of range")

        if messages[message_index].get("role") != "user":
            raise ValueError("Selected message is not a user message")

        messages[message_index]["content"] = content
        _touch_conversation(conversation)
        save_conversation(conversation)
        return conversation


def add_assistant_message(
    conversation_id: str,
    stage1: List[Dict[str, Any]],
    stage2: List[Dict[str, Any]],
    stage3: Dict[str, Any],
    metadata: Optional[Dict[str, Any]] = None,
):
    """
    Add an assistant message with all 3 stages to a conversation.

    Args:
        conversation_id: Conversation identifier
        stage1: List of individual model responses
        stage2: List of model rankings
        stage3: Final synthesized response
    """
    with _conversation_lock(conversation_id):
        conversation = get_conversation(conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        message = {
            "role": "assistant",
            "status": "complete",
            "stage1": stage1,
            "stage2": stage2,
            "stage3": stage3,
            "loading": {
                "stage1": False,
                "stage2": False,
                "stage3": False,
            },
            "updated_at": datetime.utcnow().isoformat(),
        }
        if metadata is not None:
            message["metadata"] = metadata

        conversation["messages"].append(message)
        message_index = len(conversation["messages"]) - 1

        _touch_conversation(conversation)
        save_conversation(conversation)
        return message_index


def create_assistant_partial(conversation_id: str) -> int:
    """
    Add a persisted in-progress assistant placeholder.

    Returns:
        The message index for subsequent partial updates.
    """
    with _conversation_lock(conversation_id):
        conversation = get_conversation(conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        message = {
            "role": "assistant",
            "status": "running",
            "stage1": None,
            "stage2": None,
            "stage3": None,
            "metadata": None,
            "modelStatus": {
                "stage1": {},
                "stage2": {},
                "stage3": {},
            },
            "loading": {
                "stage1": False,
                "stage2": False,
                "stage3": False,
            },
            "updated_at": datetime.utcnow().isoformat(),
        }
        conversation["messages"].append(message)
        message_index = len(conversation["messages"]) - 1
        _touch_conversation(conversation)
        save_conversation(conversation)
        return message_index


def _empty_summary_state() -> Dict[str, Any]:
    return {
        "content": "",
        "covered_messages": 0,
        "updated_at": None,
    }


def truncate_conversation_messages(conversation_id: str, from_message_index: int) -> Dict[str, Any]:
    """Remove messages from an index onward and clear invalidated context state."""
    with _conversation_lock(conversation_id):
        conversation = get_conversation(conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        messages = conversation.get("messages", [])
        if from_message_index < 0 or from_message_index > len(messages):
            raise ValueError("Message index out of range")

        if from_message_index == len(messages):
            return conversation

        removed_messages = messages[from_message_index:]
        removed_turn_ids = {
            message.get("turn_id")
            for message in removed_messages
            if message.get("turn_id")
        }
        removed_turns = [
            turn for turn in conversation.get("turns", [])
            if turn.get("id") in removed_turn_ids
        ]
        conversation["messages"] = messages[:from_message_index]

        if removed_turn_ids:
            conversation["turns"] = [
                turn for turn in conversation.get("turns", [])
                if turn.get("id") not in removed_turn_ids
            ]
            for message in conversation["messages"]:
                if message.get("turn_id") in removed_turn_ids:
                    message.pop("turn_id", None)

        _delete_unreferenced_attachments(
            conversation_id,
            {"messages": removed_messages, "turns": removed_turns},
            conversation,
        )

        # Any cached summary can include text from the removed suffix or have stale
        # covered-message counts, so force the next context build to recompute it.
        conversation["context_summary"] = _empty_summary_state()
        _touch_conversation(conversation)
        save_conversation(conversation)
        return conversation



def fork_conversation(
    conversation_id: str,
    through_message_index: int,
    *,
    new_conversation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a new conversation branch containing messages up to one index."""
    with _conversation_lock(conversation_id):
        conversation = get_conversation(conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        messages = conversation.get("messages", [])
        if through_message_index < 0 or through_message_index >= len(messages):
            raise ValueError("Message index out of range")

        branch_messages = copy.deepcopy(messages[:through_message_index + 1])
        kept_turns = []
        kept_turn_ids = set()
        for turn in conversation.get("turns", []) or []:
            user_index = turn.get("user_message_index")
            assistant_index = turn.get("assistant_message_index")
            if (
                isinstance(user_index, int)
                and isinstance(assistant_index, int)
                and user_index <= through_message_index
                and assistant_index <= through_message_index
            ):
                cloned_turn = copy.deepcopy(turn)
                kept_turns.append(cloned_turn)
                kept_turn_ids.add(cloned_turn.get("id"))

        for message in branch_messages:
            if message.get("turn_id") and message.get("turn_id") not in kept_turn_ids:
                message.pop("turn_id", None)

        branch_id = new_conversation_id or str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        branch = {
            "id": branch_id,
            "created_at": now,
            "updated_at": now,
            "title": f"{conversation.get('title', 'New Conversation')} (branch)",
            "favorite": False,
            "archived": False,
            "pinned": False,
            "tags": _normalize_conversation_tags(conversation.get("tags")),
            "messages": branch_messages,
            "turns": kept_turns,
            "context_summary": _empty_summary_state(),
            "context_policy": normalize_context_policy(conversation.get("context_policy")),
            "context_memory": copy.deepcopy(conversation.get("context_memory") or []),
            "branch_parent_id": conversation_id,
            "branch_from_message_index": through_message_index,
            "branch_created_at": now,
        }
        _rewrite_attachment_refs_for_branch(branch, conversation_id, branch_id)

        ensure_data_dir()
        path = get_conversation_path(branch_id)
        if os.path.exists(path):
            raise ValueError(f"Conversation {branch_id} already exists")
        save_conversation(branch)
        return branch


def get_context_policy(conversation_id: str) -> Dict[str, Any]:
    with _conversation_lock(conversation_id):
        conversation = get_conversation(conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        policy = normalize_context_policy(conversation.get("context_policy"))
        if conversation.get("context_policy") != policy:
            conversation["context_policy"] = policy
            save_conversation(conversation)
        return policy


def update_context_policy(conversation_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    with _conversation_lock(conversation_id):
        conversation = get_conversation(conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        current = normalize_context_policy(conversation.get("context_policy"))
        merged = {**current}
        for key in current:
            if key in updates and updates[key] is not None:
                merged[key] = updates[key]
        policy = normalize_context_policy(merged)
        conversation["context_policy"] = policy
        _touch_conversation(conversation)
        save_conversation(conversation)
        return policy


def _normalize_context_memory_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.utcnow().isoformat()
    content = str(entry.get("content") or "").strip()
    return {
        "id": str(entry.get("id") or f"memory-{uuid.uuid4().hex[:12]}"),
        "content": content,
        "enabled": bool(entry.get("enabled", True)),
        "created_at": str(entry.get("created_at") or now),
        "updated_at": str(entry.get("updated_at") or entry.get("created_at") or now),
    }


def _normalize_context_memory(entries: Any) -> List[Dict[str, Any]]:
    if not isinstance(entries, list):
        return []
    normalized = []
    seen_ids = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        normalized_entry = _normalize_context_memory_entry(entry)
        if not normalized_entry["content"] or normalized_entry["id"] in seen_ids:
            continue
        seen_ids.add(normalized_entry["id"])
        normalized.append(normalized_entry)
    return normalized


def get_context_memory(conversation_id: str) -> List[Dict[str, Any]]:
    with _conversation_lock(conversation_id):
        conversation = get_conversation(conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        memory = _normalize_context_memory(conversation.get("context_memory"))
        if conversation.get("context_memory") != memory:
            conversation["context_memory"] = memory
            save_conversation(conversation)
        return memory


def add_context_memory(conversation_id: str, content: str, enabled: bool = True) -> Dict[str, Any]:
    clean_content = str(content or "").strip()
    if not clean_content:
        raise ValueError("Memory content cannot be empty")

    with _conversation_lock(conversation_id):
        conversation = get_conversation(conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        memory = _normalize_context_memory(conversation.get("context_memory"))
        now = datetime.utcnow().isoformat()
        entry = {
            "id": f"memory-{uuid.uuid4().hex[:12]}",
            "content": clean_content,
            "enabled": bool(enabled),
            "created_at": now,
            "updated_at": now,
        }
        memory.append(entry)
        conversation["context_memory"] = memory
        _touch_conversation(conversation)
        save_conversation(conversation)
        return entry


def update_context_memory(conversation_id: str, memory_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    with _conversation_lock(conversation_id):
        conversation = get_conversation(conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        memory = _normalize_context_memory(conversation.get("context_memory"))
        for entry in memory:
            if entry["id"] != memory_id:
                continue
            if "content" in updates and updates["content"] is not None:
                clean_content = str(updates["content"] or "").strip()
                if not clean_content:
                    raise ValueError("Memory content cannot be empty")
                entry["content"] = clean_content
            if "enabled" in updates and updates["enabled"] is not None:
                entry["enabled"] = bool(updates["enabled"])
            entry["updated_at"] = datetime.utcnow().isoformat()
            conversation["context_memory"] = memory
            _touch_conversation(conversation)
            save_conversation(conversation)
            return entry

        raise ValueError(f"Memory {memory_id} not found")


def delete_context_memory(conversation_id: str, memory_id: str) -> Dict[str, Any]:
    with _conversation_lock(conversation_id):
        conversation = get_conversation(conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        memory = _normalize_context_memory(conversation.get("context_memory"))
        next_memory = [entry for entry in memory if entry["id"] != memory_id]
        if len(next_memory) == len(memory):
            raise ValueError(f"Memory {memory_id} not found")
        conversation["context_memory"] = next_memory
        _touch_conversation(conversation)
        save_conversation(conversation)
        return {"deleted": True, "memory_id": memory_id}


def set_message_pinned(conversation_id: str, message_index: int, pinned: bool) -> Dict[str, Any]:
    """Toggle whether a message is always considered for future context builds."""
    with _conversation_lock(conversation_id):
        conversation = get_conversation(conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        messages = conversation.get("messages", [])
        if message_index < 0 or message_index >= len(messages):
            raise ValueError("Message index out of range")

        message = messages[message_index]
        message["pinned"] = bool(pinned)
        if pinned:
            message["pinned_at"] = datetime.utcnow().isoformat()
        else:
            message.pop("pinned_at", None)

        _touch_conversation(conversation)
        save_conversation(conversation)
        return conversation


def set_message_context_excluded(conversation_id: str, message_index: int, excluded: bool) -> Dict[str, Any]:
    """Toggle whether a message is intentionally excluded from future context builds."""
    with _conversation_lock(conversation_id):
        conversation = get_conversation(conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        messages = conversation.get("messages", [])
        if message_index < 0 or message_index >= len(messages):
            raise ValueError("Message index out of range")

        message = messages[message_index]
        message["context_excluded"] = bool(excluded)
        if excluded:
            message["context_excluded_at"] = datetime.utcnow().isoformat()
        else:
            message.pop("context_excluded_at", None)

        # The cached summary may contain a message that the user just excluded,
        # so force the next build to summarize from the active message set.
        conversation["context_summary"] = _empty_summary_state()
        _touch_conversation(conversation)
        save_conversation(conversation)
        return conversation


def update_assistant_partial(
    conversation_id: str,
    message_index: int,
    updates: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Update a persisted assistant placeholder with partial stage state.

    Dict fields such as loading/modelStatus are shallow-merged so callers can
    update one stage without erasing the others.
    """
    with _conversation_lock(conversation_id):
        conversation = get_conversation(conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        messages = conversation.get("messages", [])
        if message_index < 0 or message_index >= len(messages):
            raise ValueError(f"Assistant message index {message_index} not found")

        message = messages[message_index]
        if message.get("role") != "assistant":
            raise ValueError(f"Message at index {message_index} is not an assistant message")

        for key, value in updates.items():
            if key in {"loading", "modelStatus"} and isinstance(value, dict):
                current = message.get(key) or {}
                merged = dict(current)
                for subkey, subvalue in value.items():
                    if key == "modelStatus" and subvalue == {}:
                        merged[subkey] = {}
                    elif isinstance(subvalue, dict) and isinstance(merged.get(subkey), dict):
                        merged[subkey] = {**merged[subkey], **subvalue}
                    else:
                        merged[subkey] = subvalue
                message[key] = merged
            else:
                message[key] = value

        message["updated_at"] = datetime.utcnow().isoformat()
        _touch_conversation(conversation)
        save_conversation(conversation)
        return message



def _new_turn_id() -> str:
    return f"turn-{uuid.uuid4().hex[:12]}"


def _stage_run_from_result(stage: str, result: Dict[str, Any]) -> Dict[str, Any]:
    run = {
        "stage": stage,
        "model": result.get("model"),
        "status": result.get("status", "success"),
        "response_id": result.get("response_id") or result.get("id"),
        "usage": result.get("usage", {}),
    }
    for key in ("duration_seconds", "first_event_seconds", "streamed", "finish_reason", "error_type", "error"):
        if key in result and result.get(key) is not None:
            run[key] = result.get(key)
    return {key: value for key, value in run.items() if value is not None}


def _stage3_runs(stage3: Dict[str, Any], metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
    attempts = []
    if isinstance(stage3, dict):
        attempts.extend((stage3.get("metadata") or {}).get("attempts") or [])
    attempts.extend((metadata or {}).get("attempts") or [])

    if attempts:
        runs = []
        seen = set()
        for attempt in attempts:
            model = attempt.get("model")
            key = (model, attempt.get("ok"), attempt.get("error_type"), attempt.get("error"))
            if key in seen:
                continue
            seen.add(key)
            run = {
                "stage": "stage3",
                "model": model,
                "status": "success" if attempt.get("ok") else "failed",
            }
            for field in ("error_type", "error"):
                if attempt.get(field):
                    run[field] = attempt[field]
            if isinstance(stage3, dict) and model in {stage3.get("model"), stage3.get("model") or model} and attempt.get("ok"):
                run.update(_stage_run_from_result("stage3", stage3))
                run["status"] = "success"
            runs.append({key: value for key, value in run.items() if value is not None})
        return runs

    if isinstance(stage3, dict) and stage3:
        return [_stage_run_from_result("stage3", stage3)]
    return []


def extract_assistant_runs(assistant_message: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build non-secret model run summaries from a persisted assistant message."""
    runs: List[Dict[str, Any]] = []
    for result in assistant_message.get("stage1") or []:
        if isinstance(result, dict):
            runs.append(_stage_run_from_result("stage1", result))
    for result in assistant_message.get("stage2") or []:
        if isinstance(result, dict):
            runs.append(_stage_run_from_result("stage2", result))
    stage3 = assistant_message.get("stage3") or {}
    metadata = assistant_message.get("metadata") or {}
    runs.extend(_stage3_runs(stage3, metadata))
    return runs


def create_turn_record(
    conversation_id: str,
    *,
    user_message_index: int,
    assistant_message_index: int,
    mode: str,
    context_snapshot: Optional[Dict[str, Any]] = None,
    context_payload: Optional[Dict[str, Any]] = None,
    status: str = "running",
) -> Dict[str, Any]:
    """Create a durable turn record linking display messages to execution state."""
    with _conversation_lock(conversation_id):
        conversation = get_conversation(conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        messages = conversation.get("messages", [])
        if user_message_index < 0 or user_message_index >= len(messages):
            raise ValueError("User message index out of range")
        if assistant_message_index < 0 or assistant_message_index >= len(messages):
            raise ValueError("Assistant message index out of range")

        turn_id = _new_turn_id()
        now = datetime.utcnow().isoformat()
        turn = {
            "id": turn_id,
            "mode": mode,
            "status": status,
            "user_message_index": user_message_index,
            "assistant_message_index": assistant_message_index,
            "context_snapshot": context_snapshot or {},
            "context_payload": context_payload or {},
            "runs": [],
            "created_at": now,
            "updated_at": now,
        }

        messages[user_message_index]["turn_id"] = turn_id
        messages[assistant_message_index]["turn_id"] = turn_id
        conversation.setdefault("turns", []).append(turn)
        _touch_conversation(conversation, now)
        save_conversation(conversation)
        return turn


def update_turn_record(
    conversation_id: str,
    turn_id: str,
    *,
    status: Optional[str] = None,
    context_snapshot: Optional[Dict[str, Any]] = None,
    context_payload: Optional[Dict[str, Any]] = None,
    runs: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    with _conversation_lock(conversation_id):
        conversation = get_conversation(conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        for turn in conversation.setdefault("turns", []):
            if turn.get("id") == turn_id:
                if status is not None:
                    turn["status"] = status
                if context_snapshot is not None:
                    turn["context_snapshot"] = context_snapshot
                if context_payload is not None:
                    turn["context_payload"] = context_payload
                if runs is not None:
                    turn["runs"] = runs
                turn["updated_at"] = datetime.utcnow().isoformat()
                _touch_conversation(conversation)
                save_conversation(conversation)
                return turn

        raise ValueError(f"Turn {turn_id} not found")


def update_turn_from_assistant(
    conversation_id: str,
    turn_id: str,
    *,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    with _conversation_lock(conversation_id):
        conversation = get_conversation(conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        turn = next((item for item in conversation.get("turns", []) if item.get("id") == turn_id), None)
        if not turn:
            raise ValueError(f"Turn {turn_id} not found")

        assistant_index = turn.get("assistant_message_index")
        messages = conversation.get("messages", [])
        if not isinstance(assistant_index, int) or assistant_index < 0 or assistant_index >= len(messages):
            raise ValueError("Turn assistant message index out of range")

        assistant = messages[assistant_index]
        return update_turn_record(
            conversation_id,
            turn_id,
            status=status or assistant.get("status"),
            context_snapshot=(assistant.get("metadata") or {}).get("context_snapshot") or turn.get("context_snapshot") or {},
            runs=extract_assistant_runs(assistant),
        )


def get_context_audit(conversation_id: str) -> Dict[str, Any]:
    """Return persisted context/run audit data for a conversation."""
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")

    turns = conversation.get("turns") or []
    return {
        "conversation_id": conversation_id,
        "context_summary": conversation.get("context_summary") or {},
        "context_policy": normalize_context_policy(conversation.get("context_policy")),
        "context_memory": _normalize_context_memory(conversation.get("context_memory")),
        "turn_count": len(turns),
        "turns": turns,
    }


def update_conversation_metadata(conversation_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    """Update list-view metadata for a conversation."""
    allowed_keys = {"title", "favorite", "archived", "pinned", "tags"}
    with _conversation_lock(conversation_id):
        conversation = get_conversation(conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        for key, value in updates.items():
            if key not in allowed_keys or value is None:
                continue
            if key == "title":
                conversation["title"] = str(value).strip()
            elif key == "tags":
                conversation["tags"] = _normalize_conversation_tags(value)
            else:
                conversation[key] = bool(value)

        _touch_conversation(conversation)
        save_conversation(conversation)
        return conversation


def update_conversation_title(conversation_id: str, title: str):
    """
    Update the title of a conversation.

    Args:
        conversation_id: Conversation identifier
        title: New title for the conversation
    """
    update_conversation_metadata(conversation_id, {"title": title})


def get_conversation_history(
    conversation_id: str,
    limit: Optional[int] = None,
    before_index: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Extract conversation history for context building.

    Args:
        conversation_id: Conversation identifier
        limit: Maximum number of complete exchanges to extract
        before_index: Optional message index to stop before

    Returns:
        List of conversation messages (user + assistant stage3 only)
    """
    conversation = get_conversation(conversation_id)
    if conversation is None:
        return []

    history_messages = []
    messages = conversation.get("messages", [])
    if before_index is not None:
        messages = messages[:before_index]

    # Extract complete exchanges (user + assistant stage3). Excluded messages
    # remain visible in storage but must not leak through legacy context helpers.
    i = 0
    exchange_count = 0

    while i < len(messages):
        message = messages[i]

        if message["role"] == "user":
            if not message.get("context_excluded"):
                history_messages.append({
                    "role": "user",
                    "content": message["content"]
                })

            if i + 1 < len(messages) and messages[i + 1]["role"] == "assistant":
                assistant_msg = messages[i + 1]
                stage3 = assistant_msg.get("stage3") or {}
                if (
                    not assistant_msg.get("context_excluded")
                    and isinstance(stage3, dict)
                    and "response" in stage3
                ):
                    history_messages.append({
                        "role": "assistant",
                        "content": stage3["response"]
                    })
                    i += 1

            exchange_count += 1

            if limit and exchange_count >= limit:
                break

        i += 1

    return history_messages


def _content_to_text(content: Any) -> str:
    """Extract plain text from stored string or multimodal message content."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(str(item.get("text", "")))
        return " ".join(part for part in text_parts if part)
    return str(content or "")


def _get_summary_state(conversation_id: Optional[str]) -> Dict[str, Any]:
    if not conversation_id:
        return {"content": "", "covered_messages": 0, "updated_at": None}

    conversation = get_conversation(conversation_id)
    if not conversation:
        return {"content": "", "covered_messages": 0, "updated_at": None}

    return conversation.get("context_summary") or {
        "content": "",
        "covered_messages": 0,
        "updated_at": None,
    }


def _save_summary_state(conversation_id: Optional[str], content: str, covered_messages: int):
    if not conversation_id:
        return

    with _conversation_lock(conversation_id):
        conversation = get_conversation(conversation_id)
        if not conversation:
            return

        conversation["context_summary"] = {
            "content": content,
            "covered_messages": covered_messages,
            "updated_at": datetime.utcnow().isoformat(),
        }
        save_conversation(conversation)


def clear_context_summary(conversation_id: str) -> Dict[str, Any]:
    """Clear the cached conversation summary for one conversation."""
    with _conversation_lock(conversation_id):
        conversation = get_conversation(conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        conversation["context_summary"] = _empty_summary_state()
        save_conversation(conversation)
        return conversation["context_summary"]


def _summary_source_messages_for_policy(conversation_id: str) -> List[Dict[str, Any]]:
    """Return active older messages that the current policy would summarize."""
    policy = get_context_policy(conversation_id)
    recent_message_count = max(2, policy["recent_turns"] * 2)
    raw_entries = _get_context_history_entries(conversation_id)
    active_entries = [entry for entry in raw_entries if not entry.get("context_excluded")]
    if len(active_entries) <= recent_message_count:
        return []

    per_message_chars = policy["message_char_limit"]
    older_entries = active_entries[:-recent_message_count]
    return [
        {
            "role": entry.get("role", "user"),
            "content": _truncate_text(
                _context_content_from_stored(entry.get("content")),
                per_message_chars,
                f"{entry.get('role', 'message')} message",
            ),
        }
        for entry in older_entries
    ]


async def rebuild_context_summary(conversation_id: str) -> Dict[str, Any]:
    """Regenerate the cached summary for the older history covered by policy."""
    if get_conversation(conversation_id) is None:
        raise ValueError(f"Conversation {conversation_id} not found")

    messages = _summary_source_messages_for_policy(conversation_id)
    if not messages:
        return clear_context_summary(conversation_id)

    summary = await summarize_conversation_segment(messages)
    _save_summary_state(conversation_id, summary, len(messages))
    return _get_summary_state(conversation_id)


def _estimate_tokens(value: Any) -> int:
    """Approximate tokens from text using a conservative chars-per-token ratio."""
    return max(1, (len(_content_to_text(value)) + 3) // 4)


def _truncate_text(value: str, max_chars: int, label: str = "content") -> str:
    if len(value) <= max_chars:
        return value
    return value[:max_chars].rstrip() + f"\n\n[Truncated {label} to {max_chars} characters for context budget]"


def _context_content_from_stored(content: Any, *, include_images: bool = False, per_text_limit: int = 16000) -> str:
    """Normalize stored message content into safe text for historical context."""
    if isinstance(content, str):
        return _truncate_text(content, per_text_limit)

    if isinstance(content, list):
        parts = []
        omitted_images = 0
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                parts.append(_truncate_text(str(item.get("text", "")), per_text_limit, "text item"))
            elif item.get("type") == "image_url":
                if include_images:
                    parts.append("[Current image attachment included as image content]")
                else:
                    omitted_images += 1
        if omitted_images:
            parts.append(f"[{omitted_images} earlier image attachment(s) omitted from text history]")
        return "\n\n".join(part for part in parts if part)

    return str(content or "")


def _safe_context_message(message: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "role": message.get("role", "user"),
        "content": _context_content_from_stored(message.get("content")),
    }


def _content_chars(messages: List[Dict[str, Any]]) -> int:
    return sum(len(_content_to_text(message.get("content"))) for message in messages)


def _current_attachment_snapshot(current_content: Any) -> Dict[str, Any]:
    """Describe current-turn attachments without storing raw image data in metadata."""
    snapshot = {
        "text_chars": len(_context_content_from_stored(current_content, include_images=True)),
        "text_attachment_count": 0,
        "image_attachment_count": 0,
        "file_names": [],
        "file_contexts": [],
    }

    if not isinstance(current_content, list):
        return snapshot

    for item in current_content:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "image_url":
            snapshot["image_attachment_count"] += 1
        elif item.get("type") == "text":
            text = str(item.get("text", ""))
            if "[Attached file:" in text:
                snapshot["text_attachment_count"] += 1
                marker = "[Attached file:"
                start = text.find(marker)
                end = text.find("]", start)
                if start >= 0 and end > start:
                    snapshot["file_names"].append(text[start + len(marker):end].strip())
            if isinstance(item.get("file_context"), dict):
                snapshot["file_contexts"].append(item["file_context"])

    return snapshot


def _build_context_snapshot(
    *,
    mode: str,
    raw_message_count: int,
    included_messages: List[Dict[str, Any]],
    summary: str,
    summary_covered_messages: int,
    omitted_message_count: int,
    budget_tokens: int,
    truncated: bool,
    current_content: Any,
    excluded_message_count: int = 0,
    pinned_context: str = "",
    pinned_message_count: int = 0,
    included_pinned_messages: int = 0,
    omitted_pinned_messages: int = 0,
    memory_context: str = "",
    memory_count: int = 0,
    included_memory_count: int = 0,
    omitted_memory_count: int = 0,
    context_policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    recent_history_tokens = sum(_estimate_tokens(message.get("content")) for message in included_messages)
    summary_tokens = _estimate_tokens(summary) if summary else 0
    pinned_tokens = _estimate_tokens(pinned_context) if pinned_context else 0
    memory_tokens = _estimate_tokens(memory_context) if memory_context else 0
    estimated_tokens = recent_history_tokens + summary_tokens + pinned_tokens + memory_tokens
    current_turn = _current_attachment_snapshot(current_content)
    current_turn_tokens = _estimate_tokens(_context_content_from_stored(current_content, include_images=True))
    budget_breakdown = {
        "summary_tokens": summary_tokens,
        "pinned_tokens": pinned_tokens,
        "memory_tokens": memory_tokens,
        "recent_history_tokens": recent_history_tokens,
        "history_context_tokens": estimated_tokens,
        "current_turn_tokens": current_turn_tokens,
        "estimated_request_tokens": estimated_tokens + current_turn_tokens,
        "budget_tokens": budget_tokens,
        "remaining_context_tokens": max(0, budget_tokens - estimated_tokens),
        "over_context_budget": estimated_tokens > budget_tokens,
    }
    return {
        "strategy": "summary_recent_pinned_policy_v1",
        "mode": mode,
        "context_policy": normalize_context_policy(context_policy),
        "budget_tokens": budget_tokens,
        "estimated_context_tokens": estimated_tokens,
        "raw_history_messages": raw_message_count,
        "included_history_messages": len(included_messages),
        "omitted_history_messages": omitted_message_count,
        "excluded_history_messages": excluded_message_count,
        "summary_used": bool(summary),
        "summary_covered_messages": summary_covered_messages,
        "pinned_context_used": bool(pinned_context),
        "pinned_message_count": pinned_message_count,
        "included_pinned_messages": included_pinned_messages,
        "omitted_pinned_messages": omitted_pinned_messages,
        "memory_context_used": bool(memory_context),
        "memory_count": memory_count,
        "included_memory_items": included_memory_count,
        "omitted_memory_items": omitted_memory_count,
        "truncated": truncated,
        "current_turn": current_turn,
        "budget_breakdown": budget_breakdown,
        "created_at": datetime.utcnow().isoformat(),
    }


def _message_context_entry(message: Dict[str, Any], message_index: int) -> Optional[Dict[str, Any]]:
    role = message.get("role")
    if role == "user":
        content = message.get("content", "")
    elif role == "assistant":
        stage3 = message.get("stage3") or {}
        if not isinstance(stage3, dict) or "response" not in stage3:
            return None
        content = stage3.get("response", "")
    else:
        return None

    return {
        "role": role,
        "content": content,
        "message_index": message_index,
        "pinned": bool(message.get("pinned")),
        "context_excluded": bool(message.get("context_excluded")),
    }


def _get_context_history_entries(
    conversation_id: str,
    before_index: Optional[int] = None,
) -> List[Dict[str, Any]]:
    conversation = get_conversation(conversation_id)
    if conversation is None:
        return []

    entries = []
    for index, message in enumerate(conversation.get("messages", [])):
        if before_index is not None and index >= before_index:
            break
        entry = _message_context_entry(message, index)
        if entry:
            entries.append(entry)
    return entries


def _entry_to_context_message(entry: Dict[str, Any], *, include_source: bool = False) -> Dict[str, Any]:
    message = {
        "role": entry.get("role", "user"),
        "content": entry.get("content", ""),
    }
    if include_source:
        message["source"] = "history"
        message["message_index"] = entry.get("message_index")
        if entry.get("pinned"):
            message["pinned"] = True
    return message


def _build_memory_context(
    entries: List[Dict[str, Any]],
    *,
    per_memory_chars: int,
    max_chars: int,
) -> Dict[str, Any]:
    active_entries = [entry for entry in entries if entry.get("enabled") and str(entry.get("content") or "").strip()]
    if not active_entries or max_chars <= 0:
        return {"message": None, "content": "", "included": 0, "omitted": len(active_entries), "memory_ids": []}

    parts = []
    memory_ids = []
    used_chars = 0
    omitted = 0
    for entry in active_entries:
        remaining = max_chars - used_chars
        if remaining <= 200:
            omitted += 1
            continue

        memory_id = str(entry.get("id") or "memory")
        label = f"Memory {memory_id}"
        content = _truncate_text(str(entry.get("content", "")), min(per_memory_chars, remaining), label)
        block = f"[{label}]\n{content}"
        block_len = len(block) + 2
        if used_chars + block_len > max_chars:
            remaining_for_content = max(0, max_chars - used_chars - len(f"[{label}]\n") - 80)
            if remaining_for_content <= 200:
                omitted += 1
                continue
            content = _truncate_text(str(entry.get("content", "")), remaining_for_content, label)
            block = f"[{label}]\n{content}"
            block_len = len(block) + 2

        parts.append(block)
        memory_ids.append(memory_id)
        used_chars += block_len

    if not parts:
        return {"message": None, "content": "", "included": 0, "omitted": len(active_entries), "memory_ids": []}

    content = (
        "Conversation memory. These user-managed facts, preferences, and constraints "
        "should be treated as durable context for this conversation.\n\n"
        + "\n\n".join(parts)
    )
    if omitted:
        content += f"\n\n[{omitted} memory item(s) omitted due to context budget]"

    return {
        "message": {"role": "system", "content": content},
        "content": content,
        "included": len(parts),
        "omitted": omitted,
        "memory_ids": memory_ids,
    }


def _build_pinned_context(
    entries: List[Dict[str, Any]],
    *,
    per_pin_chars: int,
    max_chars: int,
) -> Dict[str, Any]:
    if not entries or max_chars <= 0:
        return {"message": None, "content": "", "included": 0, "omitted": len(entries), "source_message_indexes": []}

    parts = []
    source_message_indexes = []
    used_chars = 0
    omitted = 0
    for entry in entries:
        remaining = max_chars - used_chars
        if remaining <= 200:
            omitted += 1
            continue

        role = entry.get("role", "message")
        label = f"Pinned {role} message #{entry.get('message_index')}"
        content = _truncate_text(str(entry.get("content", "")), min(per_pin_chars, remaining), label)
        block = f"[{label}]\n{content}"
        block_len = len(block) + 2
        if used_chars + block_len > max_chars:
            remaining_for_content = max(0, max_chars - used_chars - len(f"[{label}]\n") - 80)
            if remaining_for_content <= 200:
                omitted += 1
                continue
            content = _truncate_text(str(entry.get("content", "")), remaining_for_content, label)
            block = f"[{label}]\n{content}"
            block_len = len(block) + 2

        parts.append(block)
        if isinstance(entry.get("message_index"), int):
            source_message_indexes.append(entry["message_index"])
        used_chars += block_len

    if not parts:
        return {"message": None, "content": "", "included": 0, "omitted": len(entries), "source_message_indexes": []}

    content = (
        "Pinned conversation context. These messages were marked by the user "
        "as important and should be treated as durable constraints or references.\n\n"
        + "\n\n".join(parts)
    )
    if omitted:
        content += f"\n\n[{omitted} pinned message(s) omitted due to context budget]"

    return {
        "message": {"role": "system", "content": content},
        "content": content,
        "included": len(parts),
        "omitted": omitted,
        "source_message_indexes": source_message_indexes,
    }


async def build_context_package(
    conversation_id: str,
    *,
    before_index: Optional[int] = None,
    current_content: Any = None,
    mode: str = "council",
    summarize_older: bool = True,
) -> Dict[str, Any]:
    """Build the model-facing context package and an auditable snapshot.

    The returned messages are for model prompts; the snapshot is safe to persist
    in assistant metadata so a run can later explain what context was included.
    """
    from .config import (
        CONVERSATION_HISTORY_LIMIT,
        CONVERSATION_SUMMARY_THRESHOLD,
    )

    policy = get_context_policy(conversation_id)
    budget_tokens = policy["token_budget"]
    budget_chars = budget_tokens * 4
    per_message_chars = policy["message_char_limit"]
    recent_turn_limit = policy["recent_turns"]
    per_pin_chars = policy["pin_message_char_limit"]
    max_pin_chars = policy["pin_max_chars"]
    per_memory_chars = policy["memory_item_char_limit"]
    max_memory_chars = policy["memory_max_chars"]
    effective_summarize_older = bool(summarize_older and policy["summarize_older"])
    use_pinned = bool(policy["use_pinned"])
    use_memory = bool(policy["use_memory"])

    memory_entries = get_context_memory(conversation_id) if use_memory else []
    active_memory_entries = [entry for entry in memory_entries if entry.get("enabled") and entry.get("content")]
    effective_memory_chars = min(max_memory_chars, max(200, budget_chars // 3))
    memory_context = _build_memory_context(
        active_memory_entries,
        per_memory_chars=max(200, min(per_memory_chars, effective_memory_chars)),
        max_chars=effective_memory_chars,
    )

    raw_entries = _get_context_history_entries(conversation_id, before_index=before_index)
    excluded_message_count = sum(1 for entry in raw_entries if entry.get("context_excluded"))
    active_entries = [entry for entry in raw_entries if not entry.get("context_excluded")]
    safe_entries = [
        {
            "role": entry.get("role", "user"),
            "content": _truncate_text(
                _context_content_from_stored(entry.get("content")),
                per_message_chars,
                f"{entry.get('role', 'message')} message",
            ),
            "message_index": entry.get("message_index"),
            "pinned": bool(entry.get("pinned")),
        }
        for entry in active_entries
    ]

    pinned_message_count = sum(1 for entry in safe_entries if use_pinned and entry.get("pinned"))
    if not safe_entries:
        messages: List[Dict[str, Any]] = []
        source_messages: List[Dict[str, Any]] = []
        if memory_context["message"]:
            messages.append(memory_context["message"])
            source_messages.append({
                **memory_context["message"],
                "source": "memory",
                "memory_ids": memory_context.get("memory_ids", []),
            })
        snapshot = _build_context_snapshot(
            mode=mode,
            raw_message_count=len(raw_entries),
            included_messages=[],
            summary="",
            summary_covered_messages=0,
            omitted_message_count=0,
            budget_tokens=budget_tokens,
            truncated=False,
            current_content=current_content,
            excluded_message_count=excluded_message_count,
            pinned_message_count=0,
            memory_context=memory_context["content"],
            memory_count=len(active_memory_entries),
            included_memory_count=memory_context["included"],
            omitted_memory_count=memory_context["omitted"],
            context_policy=policy,
        )
        return {
            "messages": messages,
            "source_messages": source_messages,
            "snapshot": snapshot,
            "current_content": current_content,
        }

    max_recent_messages = max(2, recent_turn_limit * 2)
    recent_entries = safe_entries[-max_recent_messages:]
    older_entries = safe_entries[:-max_recent_messages]

    truncated = False
    while len(recent_entries) > 2 and _content_chars([_entry_to_context_message(entry) for entry in recent_entries]) > budget_chars:
        recent_entries = recent_entries[1:]
        truncated = True

    summary = ""
    summary_covered_messages = 0
    older_messages = [_entry_to_context_message(entry) for entry in older_entries]
    if older_messages and effective_summarize_older and len(active_entries) >= CONVERSATION_SUMMARY_THRESHOLD:
        try:
            summary_state = _get_summary_state(conversation_id)
            covered_messages = int(summary_state.get("covered_messages") or 0)
            cached_summary = summary_state.get("content") or ""

            if cached_summary and covered_messages == len(older_messages):
                summary = cached_summary
            elif cached_summary and covered_messages < len(older_messages):
                incremental_messages = [
                    {
                        "role": "system",
                        "content": f"Existing conversation summary: {cached_summary}",
                    },
                    *older_messages[covered_messages:],
                ]
                summary = await summarize_conversation_segment(incremental_messages)
                _save_summary_state(conversation_id, summary, len(older_messages))
            else:
                summary = await summarize_conversation_segment(older_messages)
                _save_summary_state(conversation_id, summary, len(older_messages))
            summary_covered_messages = len(older_messages)
        except Exception as e:
            print(f"Failed to summarize conversation, falling back to budgeted recent messages only: {e}")
            truncated = True

    messages: List[Dict[str, Any]] = []
    source_messages: List[Dict[str, Any]] = []
    if memory_context["message"]:
        messages.append(memory_context["message"])
        source_messages.append({
            **memory_context["message"],
            "source": "memory",
            "memory_ids": memory_context.get("memory_ids", []),
        })
    if summary:
        summary_message = {
            "role": "system",
            "content": "Previous conversation summary:\n" + _truncate_text(summary, 2400, "conversation summary"),
        }
        messages.append(summary_message)
        source_messages.append({
            **summary_message,
            "source": "summary",
            "covered_message_count": summary_covered_messages,
        })

    included_recent_indexes = {entry.get("message_index") for entry in recent_entries}
    pinned_entries = [
        entry for entry in safe_entries
        if use_pinned and entry.get("pinned") and entry.get("message_index") not in included_recent_indexes
    ]
    effective_pin_chars = min(max_pin_chars, max(200, budget_chars // 3))
    pinned_context = _build_pinned_context(
        pinned_entries,
        per_pin_chars=max(200, min(per_pin_chars, effective_pin_chars)),
        max_chars=effective_pin_chars,
    )
    if pinned_context["message"]:
        messages.append(pinned_context["message"])
        source_messages.append({
            **pinned_context["message"],
            "source": "pinned",
            "source_message_indexes": pinned_context.get("source_message_indexes", []),
        })

    recent_messages = [_entry_to_context_message(entry) for entry in recent_entries]
    recent_source_messages = [_entry_to_context_message(entry, include_source=True) for entry in recent_entries]
    messages.extend(recent_messages)
    source_messages.extend(recent_source_messages)

    while len(messages) > 2 and _content_chars(messages) > budget_chars:
        remove_index = next((idx for idx, message in enumerate(messages) if message.get("role") != "system"), None)
        if remove_index is None:
            break
        messages.pop(remove_index)
        source_messages.pop(remove_index)
        truncated = True

    included_history_messages = [m for m in messages if m.get("role") != "system"]
    omitted_count = max(0, len(safe_entries) - len(included_history_messages))
    recent_pinned_included = sum(1 for entry in recent_entries if use_pinned and entry.get("pinned"))
    included_pinned_messages = recent_pinned_included + pinned_context["included"]
    snapshot = _build_context_snapshot(
        mode=mode,
        raw_message_count=len(raw_entries),
        included_messages=included_history_messages,
        summary=summary,
        summary_covered_messages=summary_covered_messages,
        omitted_message_count=omitted_count,
        budget_tokens=budget_tokens,
        truncated=truncated or bool(older_entries and not summary),
        current_content=current_content,
        excluded_message_count=excluded_message_count,
        pinned_context=pinned_context["content"],
        pinned_message_count=pinned_message_count,
        included_pinned_messages=included_pinned_messages,
        omitted_pinned_messages=max(0, pinned_message_count - included_pinned_messages),
        memory_context=memory_context["content"],
        memory_count=len(active_memory_entries),
        included_memory_count=memory_context["included"],
        omitted_memory_count=memory_context["omitted"],
        context_policy=policy,
    )
    return {
        "messages": messages,
        "source_messages": source_messages,
        "snapshot": snapshot,
        "current_content": current_content,
    }


async def build_conversation_context(
    conversation_history: List[Dict[str, Any]],
    limit: Optional[int] = None,
    summarize_older: bool = True,
    conversation_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Build context for LLM from conversation history.

    Args:
        conversation_history: List of conversation messages
        limit: Maximum number of recent exchanges to include in full context
        summarize_older: Whether to summarize older messages

    Returns:
        List of context messages for LLM consumption
    """
    from .config import (
        CONVERSATION_HISTORY_LIMIT,
        CONVERSATION_SUMMARY_THRESHOLD,
    )

    # Use configured limit if none provided
    if limit is None:
        limit = CONVERSATION_HISTORY_LIMIT

    threshold_messages = CONVERSATION_SUMMARY_THRESHOLD * 2

    if len(conversation_history) <= limit * 2:  # *2 for user+assistant pairs
        # All messages fit in limit, return as-is
        return conversation_history

    if not summarize_older or len(conversation_history) < threshold_messages:
        # Just truncate to most recent messages
        return conversation_history[-limit * 2:]

    # Need to summarize older messages
    split_point = len(conversation_history) - (limit * 2)

    if split_point <= 0:
        return conversation_history

    # Split into older and recent messages
    older_messages = conversation_history[:split_point]
    recent_messages = conversation_history[split_point:]

    # Create summary of older messages with error handling
    if older_messages:
        try:
            summary_state = _get_summary_state(conversation_id)
            covered_messages = int(summary_state.get("covered_messages") or 0)
            cached_summary = summary_state.get("content") or ""

            if cached_summary and covered_messages == len(older_messages):
                summary = cached_summary
            elif cached_summary and covered_messages < len(older_messages):
                incremental_messages = [
                    {
                        "role": "system",
                        "content": f"Existing conversation summary: {cached_summary}",
                    },
                    *older_messages[covered_messages:],
                ]
                summary = await summarize_conversation_segment(incremental_messages)
                _save_summary_state(conversation_id, summary, len(older_messages))
            else:
                summary = await summarize_conversation_segment(older_messages)
                _save_summary_state(conversation_id, summary, len(older_messages))

            # Return summary + recent messages
            context = [
                {
                    "role": "system",
                    "content": f"Previous conversation summary: {summary}"
                }
            ]
            context.extend(recent_messages)
            return context
        except Exception as e:
            print(f"Failed to summarize conversation, falling back to recent messages only: {e}")
            # If summarization fails, just return recent messages with a longer limit
            return conversation_history[-(limit + 5) * 2:]  # Include 5 more exchanges as fallback

    return recent_messages


async def summarize_conversation_segment(
    messages: List[Dict[str, Any]]
) -> str:
    """
    Summarize older conversation segments using LLM.

    Args:
        messages: List of conversation messages to summarize

    Returns:
        Summary string
    """
    from .llm_settings import model_list, model_name
    from .openrouter import query_model

    # Build conversation text for summarization (limit to avoid token limits)
    conversation_text = ""
    max_chars = 8000  # Limit characters to avoid hitting model token limits

    for msg in messages:
        role = "User" if msg["role"] == "user" else "Assistant"
        text = f"{role}: {_content_to_text(msg.get('content'))}\n\n"
        if len(conversation_text) + len(text) > max_chars:
            break
        conversation_text += text

    # Create summarization prompt as a message
    summarization_prompt = f"""Please summarize the following conversation in a concise way that preserves the key points and maintains the conversation flow:

{conversation_text}

Provide a summary that would help someone continue this conversation naturally. Focus on the main topics discussed and any important conclusions reached.

Please keep the summary under 300 words."""

    # Format as messages array for OpenRouter API
    messages_for_llm = [
        {
            "role": "user",
            "content": summarization_prompt
        }
    ]

    # Try primary model first
    models_to_try = [
        model_name("summarization_model"),
        *model_list("summarization_fallback_models"),
    ]

    for i, model in enumerate(models_to_try):
        try:
            print(f"Attempting to summarize {len(messages)} messages using model {i+1}/{len(models_to_try)}: {model}")
            response = await query_model(model, messages_for_llm)

            if response and response.get("content"):
                summary = response["content"].strip()
                print(f"Successfully generated summary using {model}: {summary[:100]}...")
                return summary
            else:
                print(f"Empty or invalid response from model {model}. Response: {response}")
                continue  # Try next model

        except Exception as e:
            print(f"Error summarizing conversation with model {model}: {e}")
            continue  # Try next model

    # All models failed, try simple fallback
    print("All summarization models failed, falling back to simple truncation-based summary")
    try:
        simple_summary = "Conversation covers: " + ", ".join([
            _content_to_text(msg.get('content'))[:50] + "..."
            if len(_content_to_text(msg.get('content'))) > 50
            else _content_to_text(msg.get('content'))
            for msg in messages[:5]  # First 5 messages only
        ])
        return simple_summary
    except Exception as fallback_error:
        print(f"Even fallback summary failed: {fallback_error}")
        return "Previous conversation summary unavailable"


def delete_conversation(conversation_id: str) -> bool:
    """
    Delete a conversation from storage.

    Args:
        conversation_id: Conversation identifier

    Returns:
        True if deleted successfully

    Raises:
        ValueError: If conversation doesn't exist
        OSError: If file deletion fails
    """
    with _conversation_lock(conversation_id):
        path = get_conversation_path(conversation_id)

        if not os.path.exists(path):
            raise ValueError(f"Conversation {conversation_id} not found")

        try:
            os.remove(path)
            attachment_dir = _attachment_dir(conversation_id)
            if os.path.exists(attachment_dir):
                shutil.rmtree(attachment_dir)
            return True
        except OSError as e:
            raise OSError(f"Failed to delete conversation {conversation_id}: {str(e)}")

# File Queue Management

def update_file_queue(conversation_id: str, file_queue: List[Dict[str, Any]]) -> None:
    """
    Update the file queue for a conversation.

    Args:
        conversation_id: Conversation identifier
        file_queue: List of file metadata dicts
    """
    with _conversation_lock(conversation_id):
        conversation = get_conversation(conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        conversation["file_queue"] = file_queue
        save_conversation(conversation)


def get_file_queue(conversation_id: str) -> List[Dict[str, Any]]:
    """
    Get the file queue for a conversation.

    Args:
        conversation_id: Conversation identifier

    Returns:
        List of file metadata dicts, or empty list if none exists
    """
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")

    return conversation.get("file_queue", [])
