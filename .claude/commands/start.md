# Start Development Servers

Run both frontend and backend in development mode.

## Purpose

This command helps you start the LLM Council development environment.

## Usage

```
/start
```

## Quick Start

### Backend (FastAPI)
```bash
# Using uv (recommended)
uv run uvicorn backend.main:app --reload --port 8001

# Using python directly
python -m uvicorn backend.main:app --reload --port 8001
```

Backend will be available at: **http://localhost:8001**

### Frontend (React + Vite)
```bash
cd frontend
npm run dev
```

Frontend will be available at: **http://localhost:5173**

## Running Both Simultaneously

### Option 1: Two terminal windows
```bash
# Terminal 1 - Backend
uv run uvicorn backend.main:app --reload --port 8001

# Terminal 2 - Frontend
cd frontend && npm run dev
```

### Option 2: Background processes
```bash
# Start backend in background
uv run uvicorn backend.main:app --reload --port 8001 &

# Start frontend
cd frontend && npm run dev
```

### Option 3: Using tmux
```bash
# Create tmux session
tmux new-session -d -s llmcouncil

# Split window
tmux split-window -h

# Run backend in left pane
tmux send-keys -t llmcouncil:0.0 'uv run uvicorn backend.main:app --reload --port 8001' Enter

# Run frontend in right pane
tmux send-keys -t llmcouncil:0.1 'cd frontend && npm run dev' Enter

# Attach to session
tmux attach-session -t llmcouncil
```

## Prerequisites

### Before starting, make sure:

1. **Backend dependencies installed:**
   ```bash
   uv sync
   ```

2. **Frontend dependencies installed:**
   ```bash
   cd frontend && npm install
   ```

3. **Environment variables configured:**
   ```bash
   # .env file should exist in project root
   OPENAI_API_KEY=sk-or-v1-...
   OPENAI_API_BASE_URL=https://openrouter.ai/api/v1
   ```

## Verification

### Check Backend
```bash
# Health check
curl http://localhost:8001/

# Expected output:
# {"status":"ok","service":"LLM Council API"}
```

### Check Frontend
Open browser: **http://localhost:5173**

You should see the LLM Council interface.

## Troubleshooting

### Backend won't start
```bash
# Check if port 8001 is in use
lsof -ti:8001

# Kill process on port 8001
lsof -ti:8001 | xargs kill -9

# Check dependencies
uv sync
```

### Frontend won't start
```bash
# Check if port 5173 is in use
lsof -ti:5173 | xargs kill -9

# Reinstall dependencies
cd frontend
rm -rf node_modules
npm install
```

### API connection errors
- Verify `.env` file has correct API keys
- Check backend is running on port 8001
- Check CORS configuration in `backend/main.py`
- Check console for error messages

## Production Deployment

For production, refer to `/deployment` command for:
- Building frontend static files
- Configuring production ASGI server
- Environment variable setup
- Reverse proxy configuration
