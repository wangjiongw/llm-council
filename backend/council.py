"""3-stage LLM Council orchestration."""

from typing import List, Dict, Any, Tuple
from .openrouter import query_models_parallel, query_model
from .config import TITLE_MODEL, COUNCIL_MODELS, CHAIRMAN_MODEL


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
    responses = await query_models_parallel(COUNCIL_MODELS, messages)

    # Format results with full Response API metadata
    stage1_results = []
    for model, response in responses.items():
        if response is not None:  # Only include successful responses
            stage1_results.append({
                "model": model,
                "response": response.get('content', ''),
                "response_id": response.get('id'),
                "usage": response.get('usage', {}),
                "finish_reason": response.get('finish_reason'),
            })

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
    labels = [chr(65 + i) for i in range(len(stage1_results))]  # A, B, C, ...

    # Create mapping from label to model name
    label_to_model = {
        f"Response {label}": result['model']
        for label, result in zip(labels, stage1_results)
    }

    # Build the ranking prompt
    responses_text = "\n\n".join([
        f"Response {label}:\n{result['response']}"
        for label, result in zip(labels, stage1_results)
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
    responses = await query_models_parallel(COUNCIL_MODELS, messages)

    # Format results with full Response API metadata
    stage2_results = []
    for model, response in responses.items():
        if response is not None:
            full_text = response.get('content', '')
            parsed = parse_ranking_from_text(full_text)
            stage2_results.append({
                "model": model,
                "ranking": full_text,
                "parsed_ranking": parsed,
                "response_id": response.get('id'),
                "usage": response.get('usage', {}),
                "finish_reason": response.get('finish_reason'),
            })

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
        for result in stage1_results
    ])

    stage2_text = "\n\n".join([
        f"Model: {result['model']}\nRanking: {result['ranking']}"
        for result in stage2_results
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
    response = await query_model(CHAIRMAN_MODEL, messages)

    if response is None:
        # Fallback if chairman fails
        return {
            "model": CHAIRMAN_MODEL,
            "response": "Error: Unable to generate final synthesis."
        }

    # Return with full Response API metadata
    return {
        "model": CHAIRMAN_MODEL,
        "response": response.get('content', ''),
        "response_id": response.get('id'),
        "usage": response.get('usage', {}),
        "finish_reason": response.get('finish_reason'),
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

    for ranking in stage2_results:
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

    # Use gemini-2.5-flash for title generation (fast and cheap)
    response = await query_model(TITLE_MODEL, messages, timeout=30.0)

    if response is None:
        # Fallback to a generic title
        return "New Conversation"

    title = response.get('content', 'New Conversation').strip()

    # Clean up the title - remove quotes, limit length
    title = title.strip('"\'')

    # Truncate if too long
    if len(title) > 50:
        title = title[:47] + "..."

    return title


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

    # If no models responded successfully, return error
    if not stage1_results:
        return [], [], {
            "model": "error",
            "response": "All models failed to respond. Please try again."
        }, {}

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
        "aggregate_rankings": aggregate_rankings
    }

    return stage1_results, stage2_results, stage3_result, metadata


async def stage1_collect_responses_with_history(
    user_query: str,
    conversation_history: List[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """
    Stage 1 with optional conversation history context.

    Args:
        user_query: The user's question
        conversation_history: List of previous conversation messages

    Returns:
        List of dicts with 'model' and 'response' keys
    """
    # Build messages with conversation context
    messages = []

    if conversation_history:
        # Add conversation context
        context_text = "Previous conversation context:\n\n"
        for msg in conversation_history:
            role = "User" if msg["role"] == "user" else "Assistant"
            context_text += f"{role}: {msg['content']}\n\n"

        context_text += f"Current question: {user_query}\n\nPlease provide your response considering the conversation history."
        messages.append({"role": "user", "content": context_text})
    else:
        # No conversation history, use original format
        messages = [{"role": "user", "content": user_query}]

    # Query all models in parallel
    responses = await query_models_parallel(COUNCIL_MODELS, messages)

    # Format results with full Response API metadata
    stage1_results = []
    for model, response in responses.items():
        if response is not None:  # Only include successful responses
            stage1_results.append({
                "model": model,
                "response": response.get('content', ''),
                "response_id": response.get('id'),
                "usage": response.get('usage', {}),
                "finish_reason": response.get('finish_reason'),
            })

    return stage1_results


async def stage2_collect_rankings_with_history(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    conversation_history: List[Dict[str, Any]] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """
    Stage 2 with optional conversation history context.

    Args:
        user_query: The original user query
        stage1_results: Results from Stage 1
        conversation_history: List of previous conversation messages

    Returns:
        Tuple of (rankings list, label_to_model mapping)
    """
    # Create anonymized labels for responses (Response A, Response B, etc.)
    labels = [chr(65 + i) for i in range(len(stage1_results))]  # A, B, C, ...
    label_to_model = {f"Response {label}": result["model"] for label, result in zip(labels, stage1_results)}

    # Build the ranking prompt with conversation context
    prompt_parts = []

    if conversation_history:
        prompt_parts.append("Previous conversation context:")
        for msg in conversation_history:
            role = "User" if msg["role"] == "user" else "Assistant"
            prompt_parts.append(f"{role}: {msg['content']}")
        prompt_parts.append("")

    prompt_parts.extend([
        f"Current question: {user_query}",
        "",
        "Here are the anonymized responses from the council members:",
        ""
    ])

    # Add anonymized responses
    for label, result in zip(labels, stage1_results):
        prompt_parts.append(f"**Response {label}:**")
        prompt_parts.append(result["response"])
        prompt_parts.append("")

    # Add evaluation instructions
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

    # Join all parts into the final prompt
    messages = [{"role": "user", "content": "\n".join(prompt_parts)}]

    # Query all models in parallel
    responses = await query_models_parallel(COUNCIL_MODELS, messages)

    # Format results with full Response API metadata
    stage2_results = []
    for model, response in responses.items():
        if response is not None:
            parsed_ranking = parse_ranking_from_text(response.get('content', ''))
            stage2_results.append({
                "model": model,
                "ranking": response.get('content', ''),
                "parsed_ranking": parsed_ranking,
                "response_id": response.get('id'),
                "usage": response.get('usage', {}),
                "finish_reason": response.get('finish_reason'),
            })

    return stage2_results, label_to_model


async def stage3_synthesize_final_with_history(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    stage2_results: List[Dict[str, Any]],
    conversation_history: List[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Stage 3 with conversation history context.

    Args:
        user_query: The user's question
        stage1_results: Results from Stage 1
        stage2_results: Results from Stage 2
        conversation_history: List of previous conversation messages

    Returns:
        Dict with 'model' and 'response' keys
    """
    # Build synthesis prompt with conversation context
    prompt_parts = []

    if conversation_history:
        prompt_parts.append("Conversation History:")
        for msg in conversation_history:
            role = "User" if msg["role"] == "user" else "Assistant"
            prompt_parts.append(f"{role}: {msg['content']}")
        prompt_parts.append("")
        prompt_parts.append("---")

    prompt_parts.extend([
        "Current Exchange:",
        f"Question: {user_query}",
        "",
        "STAGE 1 - Individual Responses:",
    ])

    # Add individual model responses with attribution
    for result in stage1_results:
        prompt_parts.append(f"**{result['model']}:**")
        prompt_parts.append(result['response'])
        prompt_parts.append("")

    prompt_parts.extend([
        "STAGE 2 - Peer Rankings:",
    ])

    # Add peer rankings
    for result in stage2_results:
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
    response = await query_model(CHAIRMAN_MODEL, messages)

    # Return with full Response API metadata
    if response:
        return {
            "model": CHAIRMAN_MODEL,
            "response": response.get('content', ''),
            "response_id": response.get('id'),
            "usage": response.get('usage', {}),
            "finish_reason": response.get('finish_reason'),
        }
    else:
        return {
            "model": CHAIRMAN_MODEL,
            "response": "Error: Unable to generate final synthesis."
        }


async def run_full_council_with_history(
    user_query: str,
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

    # If no models responded successfully, return error
    if not stage1_results:
        return [], [], {
            "model": "error",
            "response": "All models failed to respond. Please try again."
        }, {}

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
        "aggregate_rankings": aggregate_rankings
    }

    return stage1_results, stage2_results, stage3_result, metadata


async def quick_query(
    user_query: str,
    conversation_history: List[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Quick single-model query without the 3-stage council process.

    Args:
        user_query: The user's question
        conversation_history: List of previous conversation messages

    Returns:
        Dict with 'model', 'response', and Response API metadata
    """
    from .config import QUICK_MODEL

    # Build messages with conversation context
    messages = []

    if conversation_history:
        # Add conversation context
        context_text = "Previous conversation context:\n\n"
        for msg in conversation_history:
            role = "User" if msg["role"] == "user" else "Assistant"
            context_text += f"{role}: {msg['content']}\n\n"

        context_text += f"Current question: {user_query}"
        messages.append({"role": "user", "content": context_text})
    else:
        # No conversation history, use original format
        messages = [{"role": "user", "content": user_query}]

    # Query the quick model
    response = await query_model(QUICK_MODEL, messages)

    if response is None:
        return {
            "model": QUICK_MODEL,
            "response": "Error: Model failed to respond. Please try again.",
            "response_id": None,
            "usage": {},
            "finish_reason": None,
        }

    return {
        "model": QUICK_MODEL,
        "response": response.get('content', ''),
        "response_id": response.get('id'),
        "usage": response.get('usage', {}),
        "finish_reason": response.get('finish_reason'),
    }
