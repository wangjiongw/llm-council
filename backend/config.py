"""Configuration for the LLM Council."""

import os
from dotenv import load_dotenv

load_dotenv()

# OpenRouter API key
OPENROUTER_API_KEY = os.getenv("OPENAI_API_KEY")

# Council members - list of OpenRouter model identifiers
COUNCIL_MODELS = [
    "anthropic/claude-sonnet-4.5",
    "gpt-5.2-chat-latest",
    "gemini-3-pro-preview",
]

TITLE_MODEL = "gemini-2.5-flash"
# Chairman model - synthesizes final response
CHAIRMAN_MODEL = "gemini-3-pro-preview"
# Quick query model - for direct single-model responses
QUICK_MODEL = "gemini-2.5-flash"

# OpenRouter API endpoint
OPENROUTER_BASE_URL = os.getenv("OPENAI_API_BASE_URL")
OPENROUTER_API_URL = f"{OPENROUTER_BASE_URL}/chat/completions"
OPENROUTER_RESPONSE_URL = f"{OPENROUTER_BASE_URL}/responses"

# Data directory for conversation storage
DATA_DIR = "data/conversations"

# Conversation history settings
CONVERSATION_HISTORY_LIMIT = 10  # Number of recent turns to include in full context
CONVERSATION_SUMMARY_THRESHOLD = 20  # When to start summarizing older messages
SUMMARIZATION_MODEL = "gemini-2.5-flash"  # Fast model for summarization
SUMMARIZATION_FALLBACK_MODELS = ["openai/gpt-4o-mini", "anthropic/claude-haiku"]  # Backup models
