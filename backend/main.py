"""FastAPI backend for LLM Council."""

from fastapi import FastAPI, HTTPException, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any
import uuid
import json
import asyncio

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

    # Get conversation history for context (only if not first message)
    conversation_history = None
    if not is_first_message:
        # Extract conversation history (user messages + assistant stage3 responses)
        raw_history = storage.get_conversation_history(conversation_id)
        if raw_history:
            # Build context with smart history management
            conversation_history = await storage.build_conversation_context(
                raw_history,
                conversation_id=conversation_id,
            )

    # Add user message after building history so the current question is not duplicated
    storage.add_user_message(conversation_id, request.content)

    # If this is the first message, generate a title
    if is_first_message:
        title = await generate_conversation_title(request.content)
        storage.update_conversation_title(conversation_id, title)

    # Run the 3-stage council process with conversation history
    stage1_results, stage2_results, stage3_result, metadata = await run_full_council_with_history(
        request.content, conversation_history
    )

    # Add assistant message with all stages
    storage.add_assistant_message(
        conversation_id,
        stage1_results,
        stage2_results,
        stage3_result,
        metadata=metadata,
    )

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

    # Get conversation history for context (only if not first message)
    conversation_history = None
    if not is_first_message:
        raw_history = storage.get_conversation_history(conversation_id)
        if raw_history:
            conversation_history = await storage.build_conversation_context(
                raw_history,
                conversation_id=conversation_id,
            )

    # Add user message after building history so the current question is not duplicated
    storage.add_user_message(conversation_id, request.content)

    # If this is the first message, generate a title
    if is_first_message:
        title = await generate_conversation_title(request.content)
        storage.update_conversation_title(conversation_id, title)

    # Run quick query
    quick_result = await quick_query(request.content, conversation_history)
    metadata = {
        "mode": "quick",
        **(quick_result.get("metadata") or {}),
    }

    # Add assistant message (quick responses are stored in stage3 for consistency)
    storage.add_assistant_message(
        conversation_id,
        [],  # No stage1
        [],  # No stage2
        quick_result,  # Store in stage3
        metadata=metadata,
    )

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

            conversation_history = None
            if not is_first_message:
                raw_history = storage.get_conversation_history(conversation_id)
                if raw_history:
                    conversation_history = await storage.build_conversation_context(
                        raw_history,
                        conversation_id=conversation_id,
                    )

            storage.add_user_message(conversation_id, request.content)
            assistant_message_index = storage.create_assistant_partial(conversation_id)

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

            metadata = {"mode": "quick"}
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

            metadata = {
                "mode": "quick",
                **(quick_result.get("metadata") or {}),
            }
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
                        "metadata": {"mode": "quick"},
                        "error": "Client disconnected before the quick response completed.",
                        "loading": {
                            "stage1": False,
                            "stage2": False,
                            "stage3": False,
                        },
                    },
                )
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
                        "metadata": {"mode": "quick"},
                        "error": str(e),
                        "loading": {
                            "stage1": False,
                            "stage2": False,
                            "stage3": False,
                        },
                    },
                )
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

            # Get conversation history for context (only if not first message)
            conversation_history = None
            if not is_first_message:
                # Extract conversation history (user messages + assistant stage3 responses)
                raw_history = storage.get_conversation_history(conversation_id)
                if raw_history:
                    # Build context with smart history management
                    conversation_history = await storage.build_conversation_context(
                        raw_history,
                        conversation_id=conversation_id,
                    )

            # Add user message after building history so the current question is not duplicated
            storage.add_user_message(conversation_id, request.content)
            assistant_message_index = storage.create_assistant_partial(conversation_id)

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
            persist_assistant({"status": "running", "loading": {"stage1": True}})
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
                metadata = {
                    "label_to_model": {},
                    "aggregate_rankings": [],
                    "warnings": ["All Stage 1 model calls failed."],
                }
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
            metadata = {
                "label_to_model": label_to_model,
                "aggregate_rankings": aggregate_rankings,
            }
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

            raw_history = storage.get_conversation_history(conversation_id, before_index=user_index)
            conversation_history = None
            if raw_history:
                conversation_history = await storage.build_conversation_context(
                    raw_history,
                    conversation_id=conversation_id,
                )

            current_conversation = storage.get_conversation(conversation_id)
            assistant = current_conversation["messages"][message_index]
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
                metadata = {
                    "label_to_model": {},
                    "aggregate_rankings": [],
                    "warnings": ["All Stage 1 model calls failed."],
                }
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
                metadata = {
                    "label_to_model": label_to_model,
                    "aggregate_rankings": aggregate_rankings,
                }
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

        mode = mode.strip().lower()
        if mode not in {"council", "quick"}:
            raise HTTPException(status_code=400, detail="File message mode must be 'council' or 'quick'")

        is_first_message = len(conversation["messages"]) == 0

        # Import file processor
        from .file_processor import process_uploaded_files

        # 1. Read and process files
        uploaded_files = []
        for file in files:
            content_bytes = await file.read()
            uploaded_files.append({
                'filename': file.filename,
                'content': content_bytes,
                'file_type': file.content_type
            })

        # 2. Process files (base64 encoding, text extraction)
        processed_files = await process_uploaded_files(uploaded_files)

        # 2.5 Extract file metadata for UI display
        file_metadata = []
        for f in uploaded_files:
            file_type = f['file_type'] or ''
            file_metadata.append({
                'id': str(uuid.uuid4()),
                'name': f['filename'],
                'type': file_type,
                'size': len(f['content']),
                'category': 'image' if file_type.startswith('image/') else 'document'
            })

        # 3. Build content array
        if processed_files:
            # Has files: build content array
            content_array = [
                {"type": "text", "text": content},
                *processed_files
            ]
        else:
            # No files: text only
            content_array = content

        # 4. Build prior conversation history before saving the current turn.
        raw_history = storage.get_conversation_history(conversation_id)
        conversation_history = None
        if raw_history:
            conversation_history = await storage.build_conversation_context(
                raw_history,
                conversation_id=conversation_id,
            )

        if mode == "quick":
            stage1_results = []
            stage2_results = []
            stage3_result = await quick_query(content_array, conversation_history)
            metadata = {
                "mode": "quick",
                **(stage3_result.get("metadata") or {}),
            }
        else:
            stage1_results, stage2_results, stage3_result, metadata = await run_full_council_with_history(
                content_array,
                conversation_history=conversation_history
            )

        # 5. Save user message (with file metadata)
        storage.add_user_message(conversation_id, content_array, files=file_metadata)

        # 6. Save assistant response
        storage.add_assistant_message(
            conversation_id,
            stage1_results,
            stage2_results,
            stage3_result,
            metadata=metadata,
        )

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
