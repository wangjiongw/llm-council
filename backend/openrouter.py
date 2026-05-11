"""OpenAI-compatible API client for making LLM requests."""

import httpx
from typing import List, Dict, Any, Optional
from .llm_settings import resolve_model_config


async def query_model(
    model: str,
    messages: List[Dict[str, Any]],
    timeout: Optional[float] = None
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
    try:
        model_config = resolve_model_config(model)
        if not model_config["enabled"]:
            print(f"Skipping disabled model {model}")
            return None

        request_timeout = timeout if timeout is not None else model_config["timeout"]
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

            # Return full OpenAI Response API format with metadata
            result = {
                'id': data.get('id'),
                'object': data.get('object'),
                'created': data.get('created'),
                'model': data.get('model'),
                'content': content,
                'reasoning_details': message.get('reasoning_details'),
                'finish_reason': choice.get('finish_reason'),
                'usage': data.get('usage', {}),
                'system_fingerprint': data.get('system_fingerprint'),
                # Backward compatibility alias
                'response': content
            }

            return result

    except Exception as e:
        print(f"Error querying model {model}: {e}")
        return None


async def query_models_parallel(
    models: List[str],
    messages: List[Dict[str, Any]]
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
    tasks = [query_model(model, messages) for model in models]

    # Wait for all to complete
    responses = await asyncio.gather(*tasks)

    # Map models to their responses
    return {model: response for model, response in zip(models, responses)}


async def query_model_with_fallbacks(
    models: List[str],
    messages: List[Dict[str, Any]],
    timeout: Optional[float] = None
) -> Dict[str, Any]:
    """Try models in order and return the first successful response with attempts."""
    attempts = []
    for model in [model for model in models if model]:
        response = await query_model(model, messages, timeout=timeout)
        attempts.append({"model": model, "ok": bool(response and response.get("content"))})
        if response and response.get("content"):
            response["attempts"] = attempts
            return response

    return {
        "content": None,
        "response": None,
        "attempts": attempts,
    }
