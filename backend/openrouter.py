"""OpenAI-compatible API client for making LLM requests."""

import asyncio
import logging
import json
import time
import httpx
from typing import List, Dict, Any, Optional
from .llm_settings import resolve_model_config
from .provider_audit import emit_provider_request_audit, make_provider_request_audit

logger = logging.getLogger(__name__)


def _failure_result(
    model: str,
    error_type: str,
    error: str,
    *,
    timeout_seconds: Optional[float] = None,
    duration_seconds: Optional[float] = None,
    status_code: Optional[int] = None,
) -> Dict[str, Any]:
    """Build a non-secret failure result for persistence and debugging."""
    result: Dict[str, Any] = {
        "status": "failed",
        "model": model,
        "content": None,
        "response": None,
        "error_type": error_type,
        "error": error,
    }
    if timeout_seconds is not None:
        result["timeout_seconds"] = timeout_seconds
    if duration_seconds is not None:
        result["duration_seconds"] = round(duration_seconds, 3)
    if status_code is not None:
        result["status_code"] = status_code
    return result


def _stream_timeout(timeout_seconds: float) -> httpx.Timeout:
    """Use timeout for connect/write/pool, but do not cap stream reads."""
    return httpx.Timeout(
        timeout_seconds,
        connect=timeout_seconds,
        read=None,
        write=timeout_seconds,
        pool=timeout_seconds,
    )


async def _query_model_streaming(
    model: str,
    model_config: Dict[str, Any],
    messages: List[Dict[str, Any]],
    request_timeout: float,
    start: float,
    event_callback=None,
) -> Dict[str, Any]:
    """Collect an OpenAI-compatible chat/completions SSE stream."""
    headers = {
        "Authorization": f"Bearer {model_config['api_key']}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
    }

    chunks: List[str] = []
    reasoning_chunks: List[str] = []
    response_id = None
    response_model = None
    finish_reason = None
    usage: Dict[str, Any] = {}
    first_event_seconds = None

    async def process_line(line: str) -> bool:
        """Process one SSE line. Return True when the stream is complete."""
        nonlocal response_id, response_model, finish_reason, usage, first_event_seconds

        if not line or not line.startswith("data:"):
            return False

        data_text = line.removeprefix("data:").strip()
        if data_text == "[DONE]":
            return True

        data = json.loads(data_text)
        if first_event_seconds is None:
            first_event_seconds = round(time.perf_counter() - start, 3)
            if event_callback:
                maybe_awaitable = event_callback({
                    "status": "first_event",
                    "first_event_seconds": first_event_seconds,
                })
                if maybe_awaitable:
                    await maybe_awaitable

        response_id = data.get("id", response_id)
        response_model = data.get("model", response_model)
        usage = data.get("usage") or usage
        for choice in data.get("choices", []):
            finish_reason = choice.get("finish_reason") or finish_reason
            delta = choice.get("delta") or {}
            content = delta.get("content")
            if content:
                chunks.append(content)
            reasoning = delta.get("reasoning_content") or delta.get("reasoning")
            if reasoning:
                reasoning_chunks.append(reasoning)
        return False

    async with httpx.AsyncClient(timeout=_stream_timeout(request_timeout)) as client:
        async with client.stream(
            "POST",
            model_config["chat_url"],
            headers=headers,
            json=payload,
        ) as response:
            if response.is_error:
                # Streaming responses do not expose .text until the body is read.
                # Read error bodies eagerly so HTTPStatusError handling can persist
                # provider diagnostics instead of raising httpx.ResponseNotRead.
                await response.aread()
            response.raise_for_status()

            line_iter = response.aiter_lines().__aiter__()
            while first_event_seconds is None:
                try:
                    line = await asyncio.wait_for(line_iter.__anext__(), timeout=request_timeout)
                except StopAsyncIteration as exc:
                    raise ValueError("Stream ended before any decodable data event") from exc

                if await process_line(line):
                    break

            async for line in line_iter:
                if await process_line(line):
                    break

    if first_event_seconds is None:
        raise ValueError("Stream ended before any decodable data event")

    duration = time.perf_counter() - start
    content = "".join(chunks)
    return {
        "status": "success",
        "id": response_id,
        "object": "chat.completion.chunk",
        "created": None,
        "model": response_model or model,
        "content": content,
        "reasoning_details": "".join(reasoning_chunks) or None,
        "finish_reason": finish_reason,
        "usage": usage,
        "system_fingerprint": None,
        "duration_seconds": round(duration, 3),
        "first_event_seconds": first_event_seconds,
        "streamed": True,
        "response": content,
        "response_id": response_id,
    }


async def _query_model_non_streaming(
    model: str,
    model_config: Dict[str, Any],
    messages: List[Dict[str, Any]],
    request_timeout: float,
    start: float,
) -> Dict[str, Any]:
    """Run a standard non-streaming OpenAI-compatible chat/completions call."""
    headers = {
        "Authorization": f"Bearer {model_config['api_key']}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": messages,
    }

    async with httpx.AsyncClient(timeout=request_timeout) as client:
        response = await client.post(
            model_config["chat_url"],
            headers=headers,
            json=payload
        )
        response.raise_for_status()

        data = response.json()
        message = data['choices'][0]['message']
        choice = data['choices'][0]
        content = message.get('content')
        duration = time.perf_counter() - start

        # Return full OpenAI Response API format with metadata
        result = {
            'status': 'success',
            'id': data.get('id'),
            'object': data.get('object'),
            'created': data.get('created'),
            'model': data.get('model'),
            'content': content,
            'reasoning_details': message.get('reasoning_details'),
            'finish_reason': choice.get('finish_reason'),
            'usage': data.get('usage', {}),
            'system_fingerprint': data.get('system_fingerprint'),
            'duration_seconds': round(duration, 3),
            'streamed': False,
            # Backward compatibility alias
            'response': content
        }

        return result


async def query_model(
    model: str,
    messages: List[Dict[str, Any]],
    timeout: Optional[float] = None,
    event_callback=None,
    provider_audit_callback=None,
    audit_context: Optional[Dict[str, Any]] = None,
    call_kind: str = "model",
    stage: str = "model",
    provider_function: str = "query_model",
    attempt: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Query a single model via OpenRouter API.

    Args:
        model: OpenRouter model identifier (e.g., "openai/gpt-4o")
        messages: List of message dicts with 'role' and 'content'
                   Content can be a string (text-only) or array (multimodal)
        timeout: Request timeout in seconds

    Returns:
        Response dict with 'content' and optional 'reasoning_details', or None if failed
    """
    start = time.perf_counter()
    request_timeout = timeout

    try:
        model_config = resolve_model_config(model)
        if not model_config["enabled"]:
            duration = time.perf_counter() - start
            logger.warning("Skipping disabled model %s after %.3fs", model, duration)
            return _failure_result(
                model,
                "disabled_model",
                f"Model {model} is disabled in LLM settings",
                timeout_seconds=request_timeout,
                duration_seconds=duration,
            )

        request_timeout = timeout if timeout is not None else model_config["timeout"]
        stream = bool(model_config.get("stream", True))
        audit_context = audit_context or {}
        await emit_provider_request_audit(
            provider_audit_callback,
            make_provider_request_audit(
                model=model,
                messages=messages,
                stream=stream,
                call_kind=call_kind,
                stage=stage,
                provider_function=provider_function,
                source_map=audit_context.get("source_map"),
                turn_lineage=audit_context.get("turn_lineage"),
                attempt=attempt,
                metadata=audit_context.get("metadata"),
            ),
        )
        if stream:
            return await _query_model_streaming(model, model_config, messages, request_timeout, start, event_callback)

        return await _query_model_non_streaming(model, model_config, messages, request_timeout, start)

    except httpx.TimeoutException:
        duration = time.perf_counter() - start
        logger.exception(
            "LLM request timed out for model %s after %.3fs (timeout=%s)",
            model,
            duration,
            request_timeout,
        )
        return _failure_result(
            model,
            "timeout",
            f"Request timed out after {request_timeout} seconds",
            timeout_seconds=request_timeout,
            duration_seconds=duration,
        )
    except httpx.HTTPStatusError as e:
        duration = time.perf_counter() - start
        status_code = e.response.status_code if e.response is not None else None
        if e.response is not None:
            try:
                response_text = e.response.text[:500]
            except httpx.ResponseNotRead:
                response_text = str(e)[:500]
        else:
            response_text = str(e)[:500]
        logger.exception(
            "LLM request HTTP error for model %s after %.3fs (status=%s)",
            model,
            duration,
            status_code,
        )
        return _failure_result(
            model,
            "http_status",
            response_text,
            timeout_seconds=request_timeout,
            duration_seconds=duration,
            status_code=status_code,
        )
    except httpx.RequestError as e:
        duration = time.perf_counter() - start
        logger.exception("LLM request network error for model %s after %.3fs", model, duration)
        return _failure_result(
            model,
            "network_error",
            str(e),
            timeout_seconds=request_timeout,
            duration_seconds=duration,
        )
    except (KeyError, IndexError, ValueError) as e:
        duration = time.perf_counter() - start
        logger.exception("LLM response parse error for model %s after %.3fs", model, duration)
        return _failure_result(
            model,
            "invalid_response",
            str(e),
            timeout_seconds=request_timeout,
            duration_seconds=duration,
        )
    except Exception as e:
        duration = time.perf_counter() - start
        logger.exception("LLM request failed for model %s after %.3fs", model, duration)
        return _failure_result(
            model,
            "unknown_error",
            str(e),
            timeout_seconds=request_timeout,
            duration_seconds=duration,
        )


async def query_models_parallel(
    models: List[str],
    messages: List[Dict[str, Any]],
    provider_audit_callback=None,
    audit_context: Optional[Dict[str, Any]] = None,
    call_kind: str = "parallel_model",
    stage: str = "model",
) -> Dict[str, Optional[Dict[str, Any]]]:
    """
    Query multiple models in parallel.

    Args:
        models: List of OpenRouter model identifiers
        messages: List of message dicts to send to each model
                  Content can be a string (text-only) or array (multimodal)

    Returns:
        Dict mapping model identifier to response dict (or None if failed)
    """
    import asyncio

    # Create tasks for all models
    audit_context = audit_context or {}
    tasks = [
        query_model(
            model,
            messages,
            provider_audit_callback=provider_audit_callback,
            audit_context={
                **audit_context,
                "metadata": {
                    **(audit_context.get("metadata") or {}),
                    "parallel_index": index,
                    "parallel_model_count": len(models),
                },
            },
            call_kind=call_kind,
            stage=stage,
            provider_function="query_models_parallel",
            attempt={"index": index + 1, "total": len(models), "fallback": False},
        )
        for index, model in enumerate(models)
    ]

    # Wait for all to complete
    responses = await asyncio.gather(*tasks)

    # Map models to their responses
    return {model: response for model, response in zip(models, responses)}


async def query_model_with_fallbacks(
    models: List[str],
    messages: List[Dict[str, Any]],
    timeout: Optional[float] = None,
    provider_audit_callback=None,
    audit_context: Optional[Dict[str, Any]] = None,
    call_kind: str = "fallback_model",
    stage: str = "model",
) -> Dict[str, Any]:
    """Try models in order and return the first successful response with attempts."""
    attempts = []
    active_models = [model for model in models if model]
    for index, model in enumerate(active_models):
        response = await query_model(
            model,
            messages,
            timeout=timeout,
            provider_audit_callback=provider_audit_callback,
            audit_context=audit_context,
            call_kind=call_kind,
            stage=stage,
            provider_function="query_model_with_fallbacks",
            attempt={"index": index + 1, "total": len(active_models), "fallback": index > 0},
        )
        attempt = {"model": model, "ok": bool(response and response.get("content"))}
        if response and response.get("status") == "failed":
            attempt["error_type"] = response.get("error_type")
            attempt["error"] = response.get("error")
        attempts.append(attempt)
        if response and response.get("content"):
            response["attempts"] = attempts
            return response

    return {
        "content": None,
        "response": None,
        "attempts": attempts,
    }
