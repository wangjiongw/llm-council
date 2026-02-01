"""JSON-based storage for conversations."""

import json
import os
from datetime import datetime
from typing import List, Dict, Any, Optional
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
        "messages": []
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


def add_user_message(conversation_id: str, content: str):
    """
    Add a user message to a conversation.

    Args:
        conversation_id: Conversation identifier
        content: User message content
    """
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")

    conversation["messages"].append({
        "role": "user",
        "content": content
    })

    save_conversation(conversation)


def add_assistant_message(
    conversation_id: str,
    stage1: List[Dict[str, Any]],
    stage2: List[Dict[str, Any]],
    stage3: Dict[str, Any]
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

    conversation["messages"].append({
        "role": "assistant",
        "stage1": stage1,
        "stage2": stage2,
        "stage3": stage3
    })

    save_conversation(conversation)


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
    limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Extract conversation history for context building.

    Args:
        conversation_id: Conversation identifier
        limit: Maximum number of complete exchanges to extract

    Returns:
        List of conversation messages (user + assistant stage3 only)
    """
    conversation = get_conversation(conversation_id)
    if conversation is None:
        return []

    history_messages = []
    messages = conversation.get("messages", [])

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
                if "stage3" in assistant_msg and "response" in assistant_msg["stage3"]:
                    history_messages.append({
                        "role": "assistant",
                        "content": assistant_msg["stage3"]["response"]
                    })
                    i += 1  # Skip the assistant message

            exchange_count += 1

            # Stop if we've reached the requested limit
            if limit and exchange_count >= limit:
                break

        i += 1

    return history_messages


async def build_conversation_context(
    conversation_history: List[Dict[str, Any]],
    limit: Optional[int] = None,
    summarize_older: bool = True
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
        CONVERSATION_HISTORY_LIMIT
    )

    # Use configured limit if none provided
    if limit is None:
        limit = CONVERSATION_HISTORY_LIMIT

    if len(conversation_history) <= limit * 2:  # *2 for user+assistant pairs
        # All messages fit in limit, return as-is
        return conversation_history

    if not summarize_older:
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
            summary = await summarize_conversation_segment(older_messages)

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
    from .config import SUMMARIZATION_MODEL, SUMMARIZATION_FALLBACK_MODELS
    from .openrouter import query_model

    # Build conversation text for summarization (limit to avoid token limits)
    conversation_text = ""
    max_chars = 8000  # Limit characters to avoid hitting model token limits

    for msg in messages:
        role = "User" if msg["role"] == "user" else "Assistant"
        text = f"{role}: {msg['content']}\n\n"
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
    models_to_try = [SUMMARIZATION_MODEL] + SUMMARIZATION_FALLBACK_MODELS

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
            msg['content'][:50] + "..." if len(msg['content']) > 50 else msg['content']
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
