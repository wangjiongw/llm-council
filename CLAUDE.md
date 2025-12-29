# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**LLM Council** - A multi-LLM query and ranking system that aggregates responses from multiple language models through a 3-stage council process.

### Architecture
- **Backend**: FastAPI serving REST API with streaming support
- **Frontend**: React 19 + Vite SPA for chat interface
- **LLM Provider**: OpenRouter API for model access
- **Storage**: JSON file-based conversation persistence

### How It Works
1. **Stage 1**: Query sent to all council models individually
2. **Stage 2**: Each model reviews and ranks anonymized responses
3. **Stage 3**: Chairman model synthesizes final answer from all inputs

## Development Commands

### Quick Start
```bash
# Backend (terminal 1)
uv run uvicorn backend.main:app --reload --port 8001

# Frontend (terminal 2)
cd frontend && npm run dev
```

### Backend (FastAPI)

#### Environment Setup
```bash
# Install dependencies with uv
uv sync

# Or activate existing venv
source .venv/bin/activate  # Linux/Mac
```

#### Running Backend
```bash
# Development server with auto-reload
uv run uvicorn backend.main:app --reload --port 8001

# Alternative: direct python
python -m uvicorn backend.main:app --reload --port 8001
```

Backend API available at: **http://localhost:8001**

#### Code Quality
```bash
# Check and fix issues
ruff check backend/ --fix

# Format code
ruff format backend/

# Check only (no modifications)
ruff check backend/
```

### Frontend (React + Vite)

#### Setup
```bash
cd frontend
npm install
```

#### Running Frontend
```bash
cd frontend
npm run dev  # http://localhost:5173
```

#### Build
```bash
npm run build       # Production build
npm run preview     # Preview production build
npm run lint        # Run ESLint
```

### Testing
```bash
# Run tests (when available)
pytest

# Run with coverage
pytest --cov=backend

# Run specific test
pytest tests/test_main.py -v
```

## Technology Stack

### Backend Dependencies
From `pyproject.toml`:
- **Python 3.10+** - Runtime
- **FastAPI 0.115+** - Web framework
- **Uvicorn 0.32+** - ASGI server
- **Pydantic 2.9+** - Data validation
- **httpx 0.27+** - Async HTTP client
- **python-dotenv 1.0+** - Environment variables

### Frontend Dependencies
From `frontend/package.json`:
- **React 19.2** - UI library
- **Vite 7.2** - Build tool + dev server
- **react-markdown 10.1** - Markdown rendering
- **remark-gfm 4.0** - GitHub Flavored Markdown
- **ESLint 9.39** - Code linting

### Development Tools
- **uv** - Fast Python package manager
- **ruff** - Fast Python linter/formatter
- **npm** - Frontend package manager

## uv Package Manager

This project uses [uv](https://docs.astral.sh/uv/) for fast Python package management.

### Common Commands

#### Installation
```bash
# Install uv (macOS/Linux)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install uv (Windows)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# Or with pip
pip install uv
```

#### Dependency Management
```bash
# Install all dependencies from pyproject.toml
uv sync

# Add a dependency
uv add fastapi

# Add development dependency
uv add --dev pytest

# Remove a dependency
uv remove fastapi

# Upgrade all dependencies
uv sync --upgrade

# Upgrade specific package
uv add fastapi@latest
```

#### Running Python
```bash
# Run Python with uv
uv run python script.py

# Run with uvicorn
uv run uvicorn backend.main:app --reload

# Run specific Python version
uv run python3.10 script.py
```

#### Virtual Environment
```bash
# Create project with venv
uv venv

# Activate (uv manages .venv automatically)
source .venv/bin/activate  # Linux/Mac
.venv\Scripts\activate     # Windows

# uv sync automatically creates/uses .venv
```

#### Project Scripts (Optional)
Add to `pyproject.toml`:
```toml
[project.scripts]
dev = "uvicorn backend.main:app --reload"
lint = "ruff check backend/ --fix"
```

Then run:
```bash
uv run dev
uv run lint
```

### Benefits over pip
- **10-100x faster** than pip
- Lock file (`uv.lock`) for reproducible installs
- Unified dependency management (no separate pip-tools)
- Built-in virtual environment management

## Project Structure

### File Organization
```
llm-council/
├── backend/                    # FastAPI application
│   ├── __init__.py
│   ├── main.py                # FastAPI app (port 8001)
│   ├── council.py             # 3-stage council logic
│   ├── storage.py             # Conversation persistence
│   ├── config.py              # Model & API configuration
│   └── openrouter.py          # OpenRouter API client
│
├── frontend/                   # React + Vite SPA
│   ├── src/
│   │   ├── main.jsx           # Entry point
│   │   ├── App.jsx            # Root component
│   │   └── ...                # Components
│   ├── index.html
│   ├── vite.config.js
│   ├── eslint.config.js
│   └── package.json
│
├── data/                       # Conversation storage
│   └── conversations/         # JSON conversation files
│
├── main.py                     # Simple hello entry point
├── pyproject.toml              # Python dependencies (uv)
├── uv.lock                    # Dependency lock file
├── .python-version             # Python 3.10
├── .env                        # API keys (not in git)
├── .claude/                    # Claude Code configuration
│   ├── settings.json
│   └── commands/
│
└── start.sh                    # Quick start script
```

### Backend Structure Details

**`backend/main.py`** - FastAPI application with endpoints:
- `GET /` - Health check
- `GET /api/conversations` - List conversations
- `POST /api/conversations` - Create conversation
- `GET /api/conversations/{id}` - Get conversation
- `POST /api/conversations/{id}/message` - Send message (3-stage)
- `POST /api/conversations/{id}/quick` - Quick single-model query
- `POST /api/conversations/{id}/message/stream` - SSE streaming

**`backend/council.py`** - Core council logic:
- `run_full_council_with_history()` - Execute all 3 stages
- `stage1_collect_responses_with_history()` - Collect initial responses
- `stage2_collect_rankings_with_history()` - Rank responses
- `stage3_synthesize_final_with_history()` - Synthesize final answer
- `quick_query()` - Single model response
- `calculate_aggregate_rankings()` - Aggregate rankings
- `generate_conversation_title()` - Generate conversation titles

**`backend/config.py`** - Configuration:
- Council models list
- Chairman model
- OpenRouter API settings
- Conversation history limits
- Summarization settings

**`backend/storage.py`** - Data persistence:
- Conversation CRUD operations
- History context building
- JSON file storage

## Naming Conventions
- **Files/Modules**: Use snake_case (`user_profile.py`)
- **Classes**: Use PascalCase (`UserProfile`)
- **Functions/Variables**: Use snake_case (`get_user_data`)
- **Constants**: Use UPPER_SNAKE_CASE (`API_BASE_URL`)
- **Private methods**: Prefix with underscore (`_private_method`)

## Python Guidelines

### Type Hints
- Use type hints for function parameters and return values
- Import types from `typing` module when needed
- Use `Optional` for nullable values
- Use `Union` for multiple possible types
- Document complex types with comments

### Code Style
- Follow PEP 8 style guide
- Use meaningful variable and function names
- Keep functions focused and single-purpose
- Use docstrings for modules, classes, and functions
- Limit line length to 100 characters

### Best Practices
- Use async/await for I/O operations (FastAPI/httpx)
- Prefer `pathlib` over `os.path` for file operations
- Use context managers (`with` statements) for resource management
- Handle exceptions appropriately with try/except blocks
- Use `logging` module instead of print statements

## Testing Standards

### Test Structure
- Organize tests to mirror source code structure
- Use descriptive test names that explain the behavior
- Follow AAA pattern (Arrange, Act, Assert)
- Use fixtures for common test data
- Group related tests in classes

### Coverage Goals
- Aim for 80%+ test coverage
- Write unit tests for business logic
- Use integration tests for external dependencies
- Mock external services (OpenRouter API) in tests
- Test error conditions and edge cases

## Environment Configuration

### Required Environment Variables

Create a `.env` file in the project root:
```bash
# OpenRouter API configuration
OPENAI_API_KEY=sk-or-v1-...
OPENAI_API_BASE_URL=https://openrouter.ai/api/v1
```

Get API key at: https://openrouter.ai/

### Development Environment
```bash
# Install all dependencies
uv sync

# Frontend dependencies
cd frontend && npm install
```

## Backend-Specific Guidelines (FastAPI)

### Running the Backend
```bash
# Development (port 8001)
uv run uvicorn backend.main:app --reload --port 8001

# Production
uv run uvicorn backend.main:app --host 0.0.0.0 --port 8001 --workers 4
```

### CORS Configuration
Frontend origins allowed:
- `http://localhost:5173` (Vite dev server)
- `http://localhost:3000` (alternative port)

### API Endpoints
See `backend/main.py` for full endpoint list with request/response schemas.

## Frontend-Specific Guidelines (React + Vite)

### Development Server
```bash
cd frontend
npm run dev  # http://localhost:5173
```

### Building for Production
```bash
npm run build  # Output: frontend/dist/
```

The built frontend can be served by the FastAPI backend or a static file server.

## Security Guidelines

### Dependencies
- Use `uv` for fast, secure dependency management
- Pin versions in `pyproject.toml`
- Keep dependencies updated with `uv sync --upgrade`

### Code Security
- Validate input data with Pydantic models
- Use environment variables for sensitive configuration (`.env`)
- API keys stored in `.env` (gitignored)
- Enable CORS only for development origins
- Use HTTPS for production deployments

### OpenRouter API
- Rate limiting handled by OpenRouter
- Implement retry logic for failed requests
- Handle API errors gracefully

## Development Workflow

### Before Starting
1. Ensure Python 3.10+ is installed
2. Install dependencies: `uv sync`
3. Configure `.env` with API keys
4. Start backend: `uv run uvicorn backend.main:app --reload --port 8001`
5. Start frontend: `cd frontend && npm run dev`

### During Development
1. Use type hints for better code documentation
2. Run ruff to check code quality
3. Test API endpoints with the frontend or curl
4. Use meaningful commit messages

### Before Committing
1. Run linter: `ruff check backend/ --fix`
2. Format code: `ruff format backend/`
3. Test manually with running servers
4. Check `.env` is not committed (already in .gitignore)
