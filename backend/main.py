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
from .council import run_full_council_with_history, generate_conversation_title, stage1_collect_responses_with_history, stage2_collect_rankings_with_history, stage3_synthesize_final_with_history, calculate_aggregate_rankings, quick_query
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
        stage3_result
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

    # Add assistant message (quick responses are stored in stage3 for consistency)
    storage.add_assistant_message(
        conversation_id,
        [],  # No stage1
        [],  # No stage2
        quick_result  # Store in stage3
    )

    # Return the quick response
    return {
        "quick": quick_result
    }


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

            # Start title generation in parallel (don't await yet)
            title_task = None
            if is_first_message:
                title_task = asyncio.create_task(generate_conversation_title(request.content))

            # Stage 1: Collect responses with history context
            yield f"data: {json.dumps({'type': 'stage1_start'})}\n\n"
            stage1_results = await stage1_collect_responses_with_history(request.content, conversation_history)
            yield f"data: {json.dumps({'type': 'stage1_complete', 'data': stage1_results})}\n\n"

            # Stage 2: Collect rankings with history context
            yield f"data: {json.dumps({'type': 'stage2_start'})}\n\n"
            stage2_results, label_to_model = await stage2_collect_rankings_with_history(request.content, stage1_results, conversation_history)
            aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)
            yield f"data: {json.dumps({'type': 'stage2_complete', 'data': stage2_results, 'metadata': {'label_to_model': label_to_model, 'aggregate_rankings': aggregate_rankings}})}\n\n"

            # Stage 3: Synthesize final answer with history context
            yield f"data: {json.dumps({'type': 'stage3_start'})}\n\n"
            stage3_result = await stage3_synthesize_final_with_history(request.content, stage1_results, stage2_results, conversation_history)
            yield f"data: {json.dumps({'type': 'stage3_complete', 'data': stage3_result})}\n\n"

            # Wait for title generation if it was started
            if title_task:
                title = await title_task
                storage.update_conversation_title(conversation_id, title)
                yield f"data: {json.dumps({'type': 'title_complete', 'data': {'title': title}})}\n\n"

            # Save complete assistant message
            storage.add_assistant_message(
                conversation_id,
                stage1_results,
                stage2_results,
                stage3_result
            )

            # Send completion event
            yield f"data: {json.dumps({'type': 'complete'})}\n\n"

        except Exception as e:
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


# File Upload Endpoints

@app.post("/api/conversations/{conversation_id}/message/files")
async def send_message_with_files(
    conversation_id: str,
    content: str = Form(...),
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
            file_metadata.append({
                'id': str(uuid.uuid4()),
                'name': f['filename'],
                'type': f['file_type'],
                'size': len(f['content']),
                'category': 'image' if f['file_type'].startswith('image/') else 'document'
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

        # 4. Run full council process
        raw_history = storage.get_conversation_history(conversation_id)
        conversation_history = None
        if raw_history:
            conversation_history = await storage.build_conversation_context(
                raw_history,
                conversation_id=conversation_id,
            )

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
            stage3_result
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
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
