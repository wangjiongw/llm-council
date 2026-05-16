"""Configuration for the LLM Council."""

import os
from dotenv import load_dotenv

load_dotenv()

# OpenRouter API key
OPENROUTER_API_KEY = os.getenv("OPENAI_API_KEY")

# Council members - list of OpenRouter model identifiers
COUNCIL_MODELS = [
    "claude-opus-4-7",
    "gpt-5.5-xhigh",
    "gemini-3.1-pro-preview",
    "deepseek-v4-pro"
]

TITLE_MODEL = "gpt-5-nano"
# Chairman model - synthesizes final response
CHAIRMAN_MODEL = "gemini-3.1-pro-preview"
# Quick query model - for direct single-model responses
QUICK_MODEL = "gpt-5.4-nano"

# OpenRouter API endpoint
OPENROUTER_BASE_URL = os.getenv("OPENAI_API_BASE_URL")
OPENROUTER_API_URL = f"{OPENROUTER_BASE_URL}/chat/completions"
OPENROUTER_RESPONSE_URL = f"{OPENROUTER_BASE_URL}/responses"

# Data directory for conversation storage
DATA_DIR = "data/conversations"

# Conversation history settings
CONVERSATION_HISTORY_LIMIT = 10  # Number of recent turns to include in full context
CONVERSATION_SUMMARY_THRESHOLD = 20  # When to start summarizing older messages
SUMMARIZATION_MODEL = "gpt-5.4-nano"  # Fast model for summarization
SUMMARIZATION_FALLBACK_MODELS = []  # Runtime settings provide the implicit gpt-5-nano fallback.
