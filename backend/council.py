"""3-stage LLM Council orchestration."""

import asyncio
from typing import List, Dict, Any, Tuple, Union
from .openrouter import query_models_parallel, query_model, query_model_with_fallbacks
from .llm_settings import model_list, model_name


def get_council_models() -> List[str]:
    """Return currently configured council models."""
    return model_list("council_models")


def _is_successful_result(result: Dict[str, Any]) -> bool:
    """Return True when a stage result contains usable model content."""
    return result.get("status", "success") == "success"


def _successful_stage1_results(stage1_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Stage 1 records that can be used as peer-evaluation inputs."""
    return [
        result
        for result in stage1_results
        if _is_successful_result(result) and bool(result.get("response"))
    ]


def has_successful_stage1_results(stage1_results: List[Dict[str, Any]]) -> bool:
    """Return True when at least one Stage 1 response can be used downstream."""
    return bool(_successful_stage1_results(stage1_results))


def _successful_stage2_results(stage2_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Stage 2 records that can be used for synthesis and aggregation."""
    return [
        result
        for result in stage2_results
        if _is_successful_result(result) and bool(result.get("ranking"))
    ]


def _format_stage_failure(model: str, response: Dict[str, Any] | None) -> Dict[str, Any]:
    """Persist non-secret failure details for a model call."""
    response = response or {}
    failure = {
        "model": model,
        "status": "failed",
        "error_type": response.get("error_type", "no_response"),
        "error": response.get("error", "No response returned from model call"),
    }
    for key in ("timeout_seconds", "duration_seconds", "status_code"):
        if key in response:
            failure[key] = response[key]
    return failure


def _format_stage1_result(model: str, response: Dict[str, Any] | None) -> Dict[str, Any]:
    """Format a raw model response for Stage 1 persistence."""
    if not response or response.get("status", "success") != "success":
        return _format_stage_failure(model, response)

    return {
        "model": model,
        "status": "success",
        "response": response.get('content', ''),
        "response_id": response.get('id'),
        "usage": response.get('usage', {}),
        "finish_reason": response.get('finish_reason'),
        "duration_seconds": response.get("duration_seconds"),
        "first_event_seconds": response.get("first_event_seconds"),
        "streamed": bool(response.get("streamed")),
    }


def _format_stage2_result(model: str, response: Dict[str, Any] | None) -> Dict[str, Any]:
    """Format a raw model response for Stage 2 persistence."""
    if not response or response.get("status", "success") != "success":
        return _format_stage_failure(model, response)

    full_text = response.get('content', '')
    return {
        "model": model,
        "status": "success",
        "ranking": full_text,
        "parsed_ranking": parse_ranking_from_text(full_text),
        "response_id": response.get('id'),
        "usage": response.get('usage', {}),
        "finish_reason": response.get('finish_reason'),
        "duration_seconds": response.get("duration_seconds"),
        "first_event_seconds": response.get("first_event_seconds"),
        "streamed": bool(response.get("streamed")),
    }


def _metadata_warnings(stage1_results: List[Dict[str, Any]], stage2_results: List[Dict[str, Any]] | None = None) -> List[str]:
    """Build user/debug-visible warnings without feeding them into prompts."""
    warnings = []
    successful_stage1_count = len(_successful_stage1_results(stage1_results))
    if successful_stage1_count < len(stage1_results):
        warnings.append(
            f"Stage 1 had {len(stage1_results) - successful_stage1_count} failed model call(s)."
        )
    if successful_stage1_count < 2:
        warnings.append(
            f"Stage 1 only had {successful_stage1_count} successful response(s); peer ranking may be less reliable."
        )

    if stage2_results is not None:
        successful_stage2_count = len(_successful_stage2_results(stage2_results))
        if successful_stage2_count < len(stage2_results):
            warnings.append(
                f"Stage 2 had {len(stage2_results) - successful_stage2_count} failed model call(s)."
            )

    return warnings


async def _emit_stage_event(event_callback, event: Dict[str, Any]) -> None:
    """Emit a stage progress event to sync or async callbacks."""
    if not event_callback:
        return
    result = event_callback(event)
    if result:
        await result


def _build_stage1_messages(
    user_query: Union[str, List[Dict[str, Any]]],
    conversation_history: List[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Build Stage 1 messages with optional conversation context."""
    if conversation_history:
        context_text = "Previous conversation context:\n\n"
        for msg in conversation_history:
            role = "User" if msg["role"] == "user" else "Assistant"
            content = msg.get('content', '')
            if isinstance(content, list):
                text_parts = [c.get('text', '') for c in content if c.get('type') == 'text']
                content_text = ' '.join(text_parts)
            else:
                content_text = content
            context_text += f"{role}: {content_text}\n\n"

        if isinstance(user_query, str):
            context_text += f"Current question: {user_query}\n\nPlease provide your response considering the conversation history."
            return [{"role": "user", "content": context_text}]

        context_item = {"type": "text", "text": f"{context_text}\n\n"}
        return [{"role": "user", "content": [context_item, *user_query]}]

    return [{"role": "user", "content": user_query}]


def _query_text(user_query: Union[str, List[Dict[str, Any]]]) -> str:
    """Extract user-visible text from text or multimodal query content."""
    if isinstance(user_query, str):
        return user_query
    text_parts = [q.get('text', '') for q in user_query if q.get('type') == 'text']
    return ' '.join(text_parts)


def _content_text(content: Any) -> str:
    """Extract text from stored conversation content."""
    if isinstance(content, list):
        text_parts = [c.get('text', '') for c in content if c.get('type') == 'text']
        return ' '.join(text_parts)
    return content


def _build_stage2_messages(
    user_query: Union[str, List[Dict[str, Any]]],
    stage1_results: List[Dict[str, Any]],
    conversation_history: List[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """Build Stage 2 messages and label mapping from successful Stage 1 records."""
    rankable_stage1_results = _successful_stage1_results(stage1_results)
    labels = [chr(65 + i) for i in range(len(rankable_stage1_results))]
    label_to_model = {f"Response {label}": result["model"] for label, result in zip(labels, rankable_stage1_results)}
    query_text = _query_text(user_query)

    prompt_parts = []
    if conversation_history:
        prompt_parts.append("Previous conversation context:")
        for msg in conversation_history:
            role = "User" if msg["role"] == "user" else "Assistant"
            prompt_parts.append(f"{role}: {_content_text(msg.get('content', ''))}")
        prompt_parts.append("")

    prompt_parts.extend([
        f"Current question: {query_text}",
        "",
        "Here are the anonymized responses from the council members:",
        ""
    ])

    for label, result in zip(labels, rankable_stage1_results):
        prompt_parts.append(f"**Response {label}:**")
        prompt_parts.append(result["response"])
        prompt_parts.append("")

    prompt_parts.extend([
        "Please evaluate each response based on:",
        "1. Accuracy and factual correctness",
        "2. Insightfulness and depth",
        "3. Clarity and coherence",
        "4. Relevance to the question and conversation context",
        "",
        "Consider the conversation context when evaluating responses.",
        "",
        "After evaluating each response, please provide a final ranking from best to worst.",
        "",
        "**FINAL RANKING:**",
        "1. Response X (best)",
        "2. Response Y",
        "3. Response Z",
        "... (worst)",
        "",
        "Do not include any text after the ranking section."
    ])

    return [{"role": "user", "content": "\n".join(prompt_parts)}], label_to_model


async def _query_stage_model_with_events(
    *,
    stage: str,
    index: int,
    model: str,
    messages: List[Dict[str, Any]],
    formatter,
    event_callback,
) -> Tuple[int, Dict[str, Any]]:
    """Query one model and emit lifecycle status events."""
    await _emit_stage_event(event_callback, {
        "type": f"{stage}_model_start",
        "stage": stage,
        "model": model,
        "status": "started",
    })

    async def on_model_event(event: Dict[str, Any]) -> None:
        status = event.get("status", "running")
        await _emit_stage_event(event_callback, {
            "type": f"{stage}_model_{status}",
            "stage": stage,
            "model": model,
            **event,
        })

    response = await query_model(model, messages, event_callback=on_model_event)
    formatted = formatter(model, response)
    event_type = f"{stage}_model_failed" if formatted.get("status") == "failed" else f"{stage}_model_complete"
    await _emit_stage_event(event_callback, {
        "type": event_type,
        "stage": stage,
        "model": model,
        "status": formatted.get("status"),
        "error_type": formatted.get("error_type"),
        "error": formatted.get("error"),
        "duration_seconds": formatted.get("duration_seconds"),
        "first_event_seconds": formatted.get("first_event_seconds"),
        "streamed": formatted.get("streamed"),
    })
    return index, formatted


async def _query_stage_models_streaming(
    *,
    stage: str,
    models: List[str],
    messages: List[Dict[str, Any]],
    formatter,
    event_callback,
) -> List[Dict[str, Any]]:
    """Query stage models concurrently while emitting per-model progress."""
    tasks = [
        asyncio.create_task(_query_stage_model_with_events(
            stage=stage,
            index=index,
            model=model,
            messages=messages,
            formatter=formatter,
            event_callback=event_callback,
        ))
        for index, model in enumerate(models)
    ]
    results: List[Dict[str, Any] | None] = [None] * len(models)
    for task in asyncio.as_completed(tasks):
        index, formatted = await task
        results[index] = formatted
    return [result for result in results if result is not None]


async def stage1_collect_responses(user_query: str) -> List[Dict[str, Any]]:
    """
    Stage 1: Collect individual responses from all council models.

    Args:
        user_query: The user's question

    Returns:
        List of dicts with 'model', 'response', and additional metadata keys
    """
    messages = [{"role": "user", "content": user_query}]

    # Query all models in parallel
    council_models = get_council_models()
    responses = await query_models_parallel(council_models, messages)

    # Format results with full Response API metadata and failure status.
    stage1_results = [
        _format_stage1_result(model, response)
        for model, response in responses.items()
    ]

    return stage1_results


async def stage2_collect_rankings(
    user_query: str,
    stage1_results: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """
    Stage 2: Each model ranks the anonymized responses.

    Args:
        user_query: The original user query
        stage1_results: Results from Stage 1

    Returns:
        Tuple of (rankings list, label_to_model mapping)
    """
    # Create anonymized labels for responses (Response A, Response B, etc.)
    rankable_stage1_results = _successful_stage1_results(stage1_results)
    labels = [chr(65 + i) for i in range(len(rankable_stage1_results))]  # A, B, C, ...

    # Create mapping from label to model name
    label_to_model = {
        f"Response {label}": result['model']
        for label, result in zip(labels, rankable_stage1_results)
    }

    # Build the ranking prompt
    responses_text = "\n\n".join([
        f"Response {label}:\n{result['response']}"
        for label, result in zip(labels, rankable_stage1_results)
    ])

    ranking_prompt = f"""You are evaluating different responses to the following question:

Question: {user_query}

Here are the responses from different models (anonymized):

{responses_text}

Your task:
1. First, evaluate each response individually. For each response, explain what it does well and what it does poorly.
2. Then, at the very end of your response, provide a final ranking.

IMPORTANT: Your final ranking MUST be formatted EXACTLY as follows:
- Start with the line "FINAL RANKING:" (all caps, with colon)
- Then list the responses from best to worst as a numbered list
- Each line should be: number, period, space, then ONLY the response label (e.g., "1. Response A")
- Do not add any other text or explanations in the ranking section

Example of the correct format for your ENTIRE response:

Response A provides good detail on X but misses Y...
Response B is accurate but lacks depth on Z...
Response C offers the most comprehensive answer...

FINAL RANKING:
1. Response C
2. Response A
3. Response B

Now provide your evaluation and ranking:"""

    messages = [{"role": "user", "content": ranking_prompt}]

    # Get rankings from all council models in parallel
    council_models = get_council_models()
    responses = await query_models_parallel(council_models, messages)

    # Format results with full Response API metadata and failure status.
    stage2_results = [
        _format_stage2_result(model, response)
        for model, response in responses.items()
    ]

    return stage2_results, label_to_model


async def stage3_synthesize_final(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    stage2_results: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Stage 3: Chairman synthesizes final response.

    Args:
        user_query: The original user query
        stage1_results: Individual model responses from Stage 1
        stage2_results: Rankings from Stage 2

    Returns:
        Dict with 'model', 'response', and additional metadata keys
    """
    # Build comprehensive context for chairman
    stage1_text = "\n\n".join([
        f"Model: {result['model']}\nResponse: {result['response']}"
        for result in _successful_stage1_results(stage1_results)
    ])

    stage2_text = "\n\n".join([
        f"Model: {result['model']}\nRanking: {result['ranking']}"
        for result in _successful_stage2_results(stage2_results)
    ])

    chairman_prompt = f"""You are the Chairman of an LLM Council. Multiple AI models have provided responses to a user's question, and then ranked each other's responses.

Original Question: {user_query}

STAGE 1 - Individual Responses:
{stage1_text}

STAGE 2 - Peer Rankings:
{stage2_text}

Your task as Chairman is to synthesize all of this information into a single, comprehensive, accurate answer to the user's original question. Consider:
- The individual responses and their insights
- The peer rankings and what they reveal about response quality
- Any patterns of agreement or disagreement

Provide a clear, well-reasoned final answer that represents the council's collective wisdom:"""

    messages = [{"role": "user", "content": chairman_prompt}]

    # Query the chairman model
    chairman_model = model_name("chairman_model")
    response = await query_model(chairman_model, messages)

    if not response or response.get("status") == "failed":
        # Fallback if chairman fails
        return {
            "model": chairman_model,
            "status": "failed",
            "response": "Error: Unable to generate final synthesis.",
            "error_type": response.get("error_type") if response else "no_response",
            "error": response.get("error") if response else "No response returned from model call",
        }

    # Return with full Response API metadata
    return {
        "model": chairman_model,
        "status": "success",
        "response": response.get('content', ''),
        "response_id": response.get('id'),
        "usage": response.get('usage', {}),
        "finish_reason": response.get('finish_reason'),
        "duration_seconds": response.get("duration_seconds"),
        "first_event_seconds": response.get("first_event_seconds"),
        "streamed": bool(response.get("streamed")),
    }


def parse_ranking_from_text(ranking_text: str) -> List[str]:
    """
    Parse the FINAL RANKING section from the model's response.

    Args:
        ranking_text: The full text response from the model

    Returns:
        List of response labels in ranked order
    """
    import re

    # Look for "FINAL RANKING:" section
    if "FINAL RANKING:" in ranking_text:
        # Extract everything after "FINAL RANKING:"
        parts = ranking_text.split("FINAL RANKING:")
        if len(parts) >= 2:
            ranking_section = parts[1]
            # Try to extract numbered list format (e.g., "1. Response A")
            # This pattern looks for: number, period, optional space, "Response X"
            numbered_matches = re.findall(r'\d+\.\s*Response [A-Z]', ranking_section)
            if numbered_matches:
                # Extract just the "Response X" part
                return [re.search(r'Response [A-Z]', m).group() for m in numbered_matches]

            # Fallback: Extract all "Response X" patterns in order
            matches = re.findall(r'Response [A-Z]', ranking_section)
            return matches

    # Fallback: try to find any "Response X" patterns in order
    matches = re.findall(r'Response [A-Z]', ranking_text)
    return matches


def calculate_aggregate_rankings(
    stage2_results: List[Dict[str, Any]],
    label_to_model: Dict[str, str]
) -> List[Dict[str, Any]]:
    """
    Calculate aggregate rankings across all models.

    Args:
        stage2_results: Rankings from each model
        label_to_model: Mapping from anonymous labels to model names

    Returns:
        List of dicts with model name and average rank, sorted best to worst
    """
    from collections import defaultdict

    # Track positions for each model
    model_positions = defaultdict(list)

    for ranking in _successful_stage2_results(stage2_results):
        ranking_text = ranking['ranking']

        # Parse the ranking from the structured format
        parsed_ranking = parse_ranking_from_text(ranking_text)

        for position, label in enumerate(parsed_ranking, start=1):
            if label in label_to_model:
                model_name = label_to_model[label]
                model_positions[model_name].append(position)

    # Calculate average position for each model
    aggregate = []
    for model, positions in model_positions.items():
        if positions:
            avg_rank = sum(positions) / len(positions)
            aggregate.append({
                "model": model,
                "average_rank": round(avg_rank, 2),
                "rankings_count": len(positions)
            })

    # Sort by average rank (lower is better)
    aggregate.sort(key=lambda x: x['average_rank'])

    return aggregate


async def generate_conversation_title(user_query: str) -> str:
    """
    Generate a short title for a conversation based on the first user message.

    Args:
        user_query: The first user message

    Returns:
        A short title (3-5 words)
    """
    title_prompt = f"""Generate a very short title (3-5 words maximum) that summarizes the following question.
The title should be concise and descriptive. Do not use quotes or punctuation in the title.

Question: {user_query}

Title:"""

    messages = [{"role": "user", "content": title_prompt}]

    # Try up to 2 times to generate title
    for attempt in range(2):
        try:
            # Use gemini-2.5-flash for title generation (fast and cheap)
            models_to_try = [model_name("title_model"), *model_list("title_fallback_models")]
            response = await query_model_with_fallbacks(models_to_try, messages, timeout=30.0)

            if not response or not response.get("content"):
                if attempt == 0:
                    continue  # Retry once
                else:
                    # Fallback to a generic title
                    return "New Conversation"

            title = response.get('content', 'New Conversation').strip()

            # Clean up the title - remove quotes, limit length
            title = title.strip('"\'')

            # Truncate if too long
            if len(title) > 50:
                title = title[:47] + "..."

            return title

        except Exception as e:
            if attempt == 0:
                continue  # Retry once
            else:
                # Log error and return fallback
                print(f"Title generation failed after retries: {e}")
                return "New Conversation"


async def run_full_council(user_query: str) -> Tuple[List, List, Dict, Dict]:
    """
    Run the complete 3-stage council process.

    Args:
        user_query: The user's question

    Returns:
        Tuple of (stage1_results, stage2_results, stage3_result, metadata)
    """
    # Stage 1: Collect individual responses
    stage1_results = await stage1_collect_responses(user_query)

    # If no models responded successfully, return error while preserving failures.
    if not has_successful_stage1_results(stage1_results):
        return stage1_results, [], {
            "model": "error",
            "response": "All models failed to respond. Please try again."
        }, {"warnings": _metadata_warnings(stage1_results)}

    # Stage 2: Collect rankings
    stage2_results, label_to_model = await stage2_collect_rankings(user_query, stage1_results)

    # Calculate aggregate rankings
    aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)

    # Stage 3: Synthesize final answer
    stage3_result = await stage3_synthesize_final(
        user_query,
        stage1_results,
        stage2_results
    )

    # Prepare metadata
    metadata = {
        "label_to_model": label_to_model,
        "aggregate_rankings": aggregate_rankings,
        "warnings": _metadata_warnings(stage1_results, stage2_results),
    }

    return stage1_results, stage2_results, stage3_result, metadata


async def stage1_collect_responses_with_history(
    user_query: Union[str, List[Dict[str, Any]]],
    conversation_history: List[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """
    Stage 1 with optional conversation history context.

    Args:
        user_query: The user's question (text string or multimodal content array)
        conversation_history: List of previous conversation messages

    Returns:
        List of dicts with 'model' and 'response' keys
    """
    messages = _build_stage1_messages(user_query, conversation_history)

    # Query all models in parallel
    council_models = get_council_models()
    responses = await query_models_parallel(council_models, messages)

    # Format results with full Response API metadata and failure status.
    stage1_results = [
        _format_stage1_result(model, response)
        for model, response in responses.items()
    ]

    return stage1_results


async def stage1_collect_responses_streaming(
    user_query: Union[str, List[Dict[str, Any]]],
    conversation_history: List[Dict[str, Any]] = None,
    council_models: List[str] | None = None,
    event_callback=None,
) -> List[Dict[str, Any]]:
    """Stage 1 with per-model status events for SSE callers."""
    messages = _build_stage1_messages(user_query, conversation_history)
    models = council_models or get_council_models()
    return await _query_stage_models_streaming(
        stage="stage1",
        models=models,
        messages=messages,
        formatter=_format_stage1_result,
        event_callback=event_callback,
    )


async def stage2_collect_rankings_with_history(
    user_query: Union[str, List[Dict[str, Any]]],
    stage1_results: List[Dict[str, Any]],
    conversation_history: List[Dict[str, Any]] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """
    Stage 2 with optional conversation history context.

    Args:
        user_query: The original user query (text or multimodal content array)
        stage1_results: Results from Stage 1
        conversation_history: List of previous conversation messages

    Returns:
        Tuple of (rankings list, label_to_model mapping)
    """
    messages, label_to_model = _build_stage2_messages(user_query, stage1_results, conversation_history)

    # Query all models in parallel
    council_models = get_council_models()
    responses = await query_models_parallel(council_models, messages)

    # Format results with full Response API metadata and failure status.
    stage2_results = [
        _format_stage2_result(model, response)
        for model, response in responses.items()
    ]

    return stage2_results, label_to_model


async def stage2_collect_rankings_streaming(
    user_query: Union[str, List[Dict[str, Any]]],
    stage1_results: List[Dict[str, Any]],
    conversation_history: List[Dict[str, Any]] = None,
    council_models: List[str] | None = None,
    event_callback=None,
) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """Stage 2 with per-model status events for SSE callers."""
    messages, label_to_model = _build_stage2_messages(user_query, stage1_results, conversation_history)
    models = council_models or get_council_models()
    stage2_results = await _query_stage_models_streaming(
        stage="stage2",
        models=models,
        messages=messages,
        formatter=_format_stage2_result,
        event_callback=event_callback,
    )
    return stage2_results, label_to_model


async def stage3_synthesize_final_with_history(
    user_query: Union[str, List[Dict[str, Any]]],
    stage1_results: List[Dict[str, Any]],
    stage2_results: List[Dict[str, Any]],
    conversation_history: List[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Stage 3 with conversation history context.

    Args:
        user_query: The user's question (text or multimodal content array)
        stage1_results: Results from Stage 1
        stage2_results: Results from Stage 2
        conversation_history: List of previous conversation messages

    Returns:
        Dict with 'model' and 'response' keys
    """
    # Extract text from user_query if it's multimodal
    if isinstance(user_query, str):
        query_text = user_query
        has_files = False
    else:
        # Extract text parts from multimodal content
        text_parts = [q.get('text', '') for q in user_query if q.get('type') == 'text']
        query_text = ' '.join(text_parts)
        has_files = any(q.get('type') == 'image_url' for q in user_query)

    # Build synthesis prompt with conversation context
    prompt_parts = []

    if conversation_history:
        prompt_parts.append("Conversation History:")
        for msg in conversation_history:
            role = "User" if msg["role"] == "user" else "Assistant"
            # Extract text from multimodal content
            content = msg.get('content', '')
            if isinstance(content, list):
                text_parts = [c.get('text', '') for c in content if c.get('type') == 'text']
                content_text = ' '.join(text_parts)
            else:
                content_text = content
            prompt_parts.append(f"{role}: {content_text}")
        prompt_parts.append("")
        prompt_parts.append("---")

    prompt_parts.extend([
        "Current Exchange:",
        f"Question: {query_text}",
    ])

    # Note about file attachments
    if has_files:
        prompt_parts.append("(Note: This question includes file attachments which have been processed separately)")
    prompt_parts.append("")

    prompt_parts.extend([
        "",
        "STAGE 1 - Individual Responses:",
    ])

    # Add individual model responses with attribution
    for result in _successful_stage1_results(stage1_results):
        prompt_parts.append(f"**{result['model']}:**")
        prompt_parts.append(result['response'])
        prompt_parts.append("")

    prompt_parts.extend([
        "STAGE 2 - Peer Rankings:",
    ])

    # Add peer rankings
    for result in _successful_stage2_results(stage2_results):
        prompt_parts.append(f"**{result['model']}:**")
        prompt_parts.append(result['ranking'])
        prompt_parts.append("")

    # Add synthesis instructions with conversation context
    if conversation_history:
        prompt_parts.extend([
            "Please synthesize a comprehensive response to the current question that:",
            "1. Considers the ongoing conversation context and flow",
            "2. Integrates the best insights from the individual responses",
            "3. Takes into account the peer evaluations",
            "4. Provides a coherent, natural continuation of the conversation",
            "",
            "Your response should acknowledge the conversation history while providing a thorough answer to the current question."
        ])
    else:
        prompt_parts.extend([
            "Please synthesize a comprehensive response to the current question that:",
            "1. Integrates the best insights from the individual responses",
            "2. Takes into account the peer evaluations",
            "3. Provides a clear, coherent answer",
            "",
            "Your response should reflect the collective wisdom of the council while addressing the user's question directly."
        ])

    # Create final prompt
    messages = [{"role": "user", "content": "\n".join(prompt_parts)}]

    # Query chairman model
    chairman_model = model_name("chairman_model")
    response = await query_model(chairman_model, messages)

    # Return with full Response API metadata
    if response and response.get("status") != "failed":
        return {
            "model": chairman_model,
            "status": "success",
            "response": response.get('content', ''),
            "response_id": response.get('id'),
            "usage": response.get('usage', {}),
            "finish_reason": response.get('finish_reason'),
            "duration_seconds": response.get("duration_seconds"),
            "first_event_seconds": response.get("first_event_seconds"),
            "streamed": bool(response.get("streamed")),
        }
    else:
        return {
            "model": chairman_model,
            "status": "failed",
            "response": "Error: Unable to generate final synthesis.",
            "error_type": response.get("error_type") if response else "no_response",
            "error": response.get("error") if response else "No response returned from model call",
        }


async def run_full_council_with_history(
    user_query: Union[str, List[Dict[str, Any]]],
    conversation_history: List[Dict[str, Any]] = None
) -> Tuple[List, List, Dict, Dict]:
    """
    Run the complete 3-stage council process with conversation history support.

    Args:
        user_query: The user's question
        conversation_history: List of previous conversation messages

    Returns:
        Tuple of (stage1_results, stage2_results, stage3_result, metadata)
    """
    # Stage 1: Collect individual responses with history context
    stage1_results = await stage1_collect_responses_with_history(user_query, conversation_history)

    # If no models responded successfully, return error while preserving failures.
    if not has_successful_stage1_results(stage1_results):
        return stage1_results, [], {
            "model": "error",
            "response": "All models failed to respond. Please try again."
        }, {"warnings": _metadata_warnings(stage1_results)}

    # Stage 2: Collect rankings with history context
    stage2_results, label_to_model = await stage2_collect_rankings_with_history(
        user_query, stage1_results, conversation_history
    )

    # Calculate aggregate rankings
    aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)

    # Stage 3: Synthesize final answer with history context
    stage3_result = await stage3_synthesize_final_with_history(
        user_query, stage1_results, stage2_results, conversation_history
    )

    # Prepare metadata
    metadata = {
        "label_to_model": label_to_model,
        "aggregate_rankings": aggregate_rankings,
        "warnings": _metadata_warnings(stage1_results, stage2_results),
    }

    return stage1_results, stage2_results, stage3_result, metadata


async def quick_query(
    user_query: Union[str, List[Dict[str, Any]]],
    conversation_history: List[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Quick single-model query without the 3-stage council process.

    Args:
        user_query: The user's question (text or multimodal content array)
        conversation_history: List of previous conversation messages

    Returns:
        Dict with 'model', 'response', and Response API metadata
    """
    quick_model = model_name("quick_model")
    quick_models = [quick_model, *model_list("quick_fallback_models")]

    # Build messages with conversation context
    messages = []

    if conversation_history:
        # Add conversation context
        context_text = "Previous conversation context:\n\n"
        for msg in conversation_history:
            role = "User" if msg["role"] == "user" else "Assistant"
            # Extract text from multimodal content
            content = msg.get('content', '')
            if isinstance(content, list):
                text_parts = [c.get('text', '') for c in content if c.get('type') == 'text']
                content_text = ' '.join(text_parts)
            else:
                content_text = content
            context_text += f"{role}: {content_text}\n\n"

        # Handle user_query based on type
        if isinstance(user_query, str):
            context_text += f"Current question: {user_query}"
            messages.append({"role": "user", "content": context_text})
        else:
            # Multimodal content array
            # Prepend context as first text item
            context_item = {"type": "text", "text": f"{context_text}\n\n"}
            messages.append({"role": "user", "content": [context_item, *user_query]})
    else:
        # No conversation history
        if isinstance(user_query, str):
            messages = [{"role": "user", "content": user_query}]
        else:
            messages = [{"role": "user", "content": user_query}]

    # Query the quick model
    response = await query_model_with_fallbacks(quick_models, messages)

    if not response or not response.get("content"):
        return {
            "model": quick_model,
            "response": "Error: Model failed to respond. Please try again.",
            "response_id": None,
            "usage": {},
            "finish_reason": None,
            "metadata": {"attempts": (response or {}).get("attempts", [])},
        }

    return {
        "model": response.get("model") or quick_model,
        "response": response.get('content', ''),
        "response_id": response.get('id'),
        "usage": response.get('usage', {}),
        "finish_reason": response.get('finish_reason'),
        "metadata": {"attempts": response.get("attempts", [])},
    }
