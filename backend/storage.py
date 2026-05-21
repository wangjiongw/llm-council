"""JSON-based storage for conversations."""

import json
import os
from datetime import datetime
from typing import List, Dict, Any, Optional, Union
from pathlib import Path
from .config import DATA_DIR


def ensure_data_dir():
    """Ensure the data directory exists."""
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)


def get_conversation_path(conversation_id: str) -> str:
    """Get the file path for a conversation."""
    return os.path.join(DATA_DIR, f"{conversation_id}.json")


def create_conversation(conversation_id: str) -> Dict[str, Any]:
    """
    Create a new conversation.

    Args:
        conversation_id: Unique identifier for the conversation

    Returns:
        New conversation dict
    """
    ensure_data_dir()

    conversation = {
        "id": conversation_id,
        "created_at": datetime.utcnow().isoformat(),
        "title": "New Conversation",
        "messages": [],
        "context_summary": {
            "content": "",
            "covered_messages": 0,
            "updated_at": None,
        },
    }

    # Save to file
    path = get_conversation_path(conversation_id)
    with open(path, 'w') as f:
        json.dump(conversation, f, indent=2)

    return conversation


def get_conversation(conversation_id: str) -> Optional[Dict[str, Any]]:
    """
    Load a conversation from storage.

    Args:
        conversation_id: Unique identifier for the conversation

    Returns:
        Conversation dict or None if not found
    """
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

    path = get_conversation_path(conversation['id'])
    with open(path, 'w') as f:
        json.dump(conversation, f, indent=2)


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
                # Return metadata only
                conversations.append({
                    "id": data["id"],
                    "created_at": data["created_at"],
                    "title": data.get("title", "New Conversation"),
                    "message_count": len(data["messages"])
                })

    # Sort by creation time, newest first
    conversations.sort(key=lambda x: x["created_at"], reverse=True)

    return conversations


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
    save_conversation(conversation)


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

    save_conversation(conversation)


def create_assistant_partial(conversation_id: str) -> int:
    """
    Add a persisted in-progress assistant placeholder.

    Returns:
        The message index for subsequent partial updates.
    """
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
    save_conversation(conversation)
    return message_index


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
    save_conversation(conversation)
    return message


def update_conversation_title(conversation_id: str, title: str):
    """
    Update the title of a conversation.

    Args:
        conversation_id: Conversation identifier
        title: New title for the conversation
    """
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")

    conversation["title"] = title
    save_conversation(conversation)


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

    # Extract complete exchanges (user + assistant stage3)
    i = 0
    exchange_count = 0

    while i < len(messages):
        message = messages[i]

        if message["role"] == "user":
            # Add user message
            history_messages.append({
                "role": "user",
                "content": message["content"]
            })

            # Check if next message is an assistant with stage3
            if i + 1 < len(messages) and messages[i + 1]["role"] == "assistant":
                assistant_msg = messages[i + 1]
                stage3 = assistant_msg.get("stage3") or {}
                if isinstance(stage3, dict) and "response" in stage3:
                    history_messages.append({
                        "role": "assistant",
                        "content": stage3["response"]
                    })
                    i += 1  # Skip the assistant message

            exchange_count += 1

            # Stop if we've reached the requested limit
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

    conversation = get_conversation(conversation_id)
    if not conversation:
        return

    conversation["context_summary"] = {
        "content": content,
        "covered_messages": covered_messages,
        "updated_at": datetime.utcnow().isoformat(),
    }
    save_conversation(conversation)


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
    path = get_conversation_path(conversation_id)

    if not os.path.exists(path):
        raise ValueError(f"Conversation {conversation_id} not found")

    try:
        os.remove(path)
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
