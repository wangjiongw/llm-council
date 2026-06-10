# LLM Council

![llmcouncil](header.jpg)

LLM Council is a local ChatGPT-like web app for running a question through multiple LLMs and then synthesizing the result. It supports both a normal **Quick mode** and a multi-model **Council mode**. The app is designed for single-user local or cloud-server deployment, with persistent local conversation history, file-aware context, rich Markdown rendering, search, and recovery tools.

The original idea is simple: instead of asking only one provider/model, you can group several models into your "LLM Council". A user question is sent to multiple models, the models review/rank each other's work, and a chairman model produces the final answer.

In Council mode, one query runs through three stages:

1. **Stage 1: First opinions**. The user query is sent to all configured council models. Their individual responses are collected and can be inspected.
2. **Stage 2: Review**. Each model reviews the other models' answers. Model identities are anonymized during review to reduce name-based bias.
3. **Stage 3: Final response**. The chairman model synthesizes the council outputs into the final answer shown to the user.

Quick mode skips the council workflow and asks one model for a lower-latency response.

## Current Features

### Chat Modes

- **Council mode**: multi-model Stage 1 / Stage 2 / Stage 3 workflow.
- **Quick mode**: single-model response for faster everyday questions.
- Quick and Council messages can appear in the same conversation.
- Completed/interrupted council stages are persisted so failed runs can be retried or resumed.
- Fallback attempts are recorded for model-call failures.

### Model and Provider Settings

- Settings modal for provider base URL, API key, model list, chairman model, and quick model.
- OpenAI-compatible provider API support, commonly used with OpenRouter.
- Model status display during streaming: pending, streaming, done, failed, duration, first-event time, and error type.
- Error classification for disabled models, auth errors, rate limits, network errors, timeouts, invalid responses, and context-size issues.

### Conversation Management

- Local conversation persistence under `data/conversations/`.
- Conversation rename, delete, fork/branch from a message, retry, and retry with edited user text.
- Active / Archived views.
- Favorite, pinned, tags, tag colors, tag filtering, and saved sidebar views.
- Batch favorite/archive/tag operations for selected conversations.
- AI title suggestions that try LLM title generation first and fall back to local extraction.
- Conversation export as Markdown or JSON.
- Time-based conversation grouping with collapsible groups.
- Conversation cards show turn counts, where a user prompt is one turn; raw message counts remain available through the API as `message_count`.
- Compact sidebar cards with two-line faded titles, tag chips, and grouped action controls.
- Resizable left sidebar with width persisted in local storage.
- Light/dark theme toggle in the title area with persisted preference.

### Search and Navigation

- Sidebar history search using `/api/conversations/search`.
- Search results grouped by conversation, with hit excerpts, source labels, badges, and match counts.
- Search filters for source, mode, files, failed runs, pinned/context-pinned content, and excluded context.
- Keyboard navigation in sidebar search: arrow keys select results, Enter opens, Escape clears.
- Clicking a search result opens the target conversation and jumps to the matched message.
- Current conversation search across user messages, assistant final answers, council details, and file metadata.
- In-conversation Prev/Next search navigation with target-message highlight.
- Turn navigation for long conversations: previous/next turn, top, and bottom.
- Virtualized long-message list with reliable far-message search/turn jump handling.

### Context and Memory

- Per-conversation context audit panel.
- Context preview before sending, for both Council and Quick mode.
- Context policy controls for history, summaries, pinned messages, and exclusions.
- Message-level pinning so specific messages are always considered for future context.
- Message-level context exclusion.
- User-managed conversation memory.
- Context replay/rebuild for a stored user turn to compare saved and current context payloads.

### File Mode

- Upload files into a conversation.
- Send messages with attached files.
- File queue persistence per conversation.
- Drag-and-drop and paste handling for supported files/images.
- File metadata is included in message rendering and searchable context.

### Rich Answer Rendering

Model answers are rendered through `RichMarkdown` and support:

- GitHub-flavored Markdown.
- Tables.
- Inline and block code.
- Syntax highlighting for common languages.
- Plain text code blocks rendered without oversized code UI.
- Code line numbers, long-code folding, code download, and diff-specific styling.
- LaTeX/KaTeX math rendering with formula copy.
- Mermaid diagrams with preview, copy SVG, download SVG, and download PNG.
- Table search, sorting, sticky headers, Markdown copy, and CSV download.
- Compact rendering and viewport/idle upgrades for expensive Markdown, KaTeX, Mermaid, and highlight.js work.

### Error Recovery and Diagnostics

- ErrorActionPanel for failed/interrupted assistant messages.
- Continue from saved stages when possible.
- Retry from scratch.
- Retry with edited user message.
- Context Policy shortcut for context-limit issues.
- LLM Settings shortcut for provider/model configuration issues.
- Folded technical details for diagnostics without overwhelming normal reading.
- Council/Quick run summary showing stage success counts, failed models, fallback attempts, token totals, and slowest duration when available.

### Testing and Acceptance

- Backend pytest coverage for metadata, search, quick streaming, council failures, and resume behavior.
- Frontend Vitest + Testing Library component tests for Sidebar, ChatInterface, and RichMarkdown.
- Playwright smoke tests for real deployed app access on `18080`.
- E2E smoke does not call LLM providers and does not send real chat messages.

## Vibe Code Alert

This project started as a mostly vibe-coded weekend hack for exploring multiple LLMs side by side. It has since been extended into a more practical single-user local chatbox with conversation management, context controls, richer rendering, and deployment smoke tests. It is still a personal/local-first project, not a multi-user production service.

## Setup

### 1. Install Dependencies

The project uses [uv](https://docs.astral.sh/uv/) for Python project management and npm for the frontend.

**Backend:**

```bash
uv sync
```

**Frontend:**

```bash
cd frontend
npm install
cd ..
```

### 2. Configure Provider

You can configure the provider from the app settings UI after the server starts. To seed initial defaults from the environment, create a `.env` file in the project root:

```bash
OPENAI_API_KEY=
OPENAI_API_BASE_URL=
```

For OpenRouter, use `https://openrouter.ai/api/v1` as the base URL and paste the key in the frontend settings modal, or set it in `.env` before startup. Make sure the provider account has enough credits for the selected models.

### 3. Configure Models (Optional)

Edit `backend/config.py` to customize the council defaults:

```python
COUNCIL_MODELS = [
    "openai/gpt-5.1",
    "google/gemini-3-pro-preview",
    "anthropic/claude-sonnet-4.5",
    "x-ai/grok-4",
]

CHAIRMAN_MODEL = "google/gemini-3-pro-preview"
```

Runtime settings can also be changed in the frontend LLM Settings modal.

## Running the Application

**Option 1: Use the start script**

```bash
./start.sh
```

**Option 2: Run manually**

Terminal 1 (Backend):

```bash
uv run python -m backend.main
```

Terminal 2 (Frontend):

```bash
cd frontend
npm run dev
```

Then open:

```text
http://localhost:5173
```

## Native Compute Node Deployment

When deploying inside an Ubuntu compute-node instance that is reached through a management-node port mapping, use the native single-port setup:

```bash
cp .env.example .env
# edit APP_PORT/BACKEND_* if needed; provider settings can be entered in the UI
bash deploy/native/install.sh
```

Expose or map the management-node port to the compute-node `APP_PORT` and open:

```text
http://<management-node-ip>:<mapped-port>/
```

The frontend is served by system Nginx and calls the backend through same-origin `/api`, so users do not need direct access to backend port `8001`. See `deploy/native/README.md` for details.

If the compute-node instance was not booted with systemd, the native install script automatically runs the backend as a normal background process and writes its PID/log under `.run/` and `logs/`.

The current deployment smoke tests default to:

```text
http://127.0.0.1:18080
```

## Usage Guide

### Basic Chat

1. Open the app.
2. Create or select a conversation from the sidebar.
3. Type a message.
4. Use **Council** for multi-model synthesis, or **Quick** for lower latency.
5. Use `Enter` for Council, `Ctrl+Enter` / `Cmd+Enter` for Quick, and `Shift+Enter` for a newline.
6. During IME composition, Enter commits the composed text and is ignored by the send shortcut; press Enter again after composition to send.

### Manage Conversations

Use the sidebar to keep a single-user local deployment organized without a separate account system:

- Switch between Active and Archived conversations.
- Favorite or pin important conversations; pinned conversations sort first inside their time group.
- Add tags, choose tag colors, and filter by tag.
- Save common sidebar filter combinations as Saved Views.
- Select multiple conversations for batch favorite, archive/restore, or tag add/remove operations.
- Use the `AI` title action to generate a concise title; the backend uses LLM generation when available and local title extraction as fallback.
- Edit titles manually when the generated title is not accurate enough.
- Export a conversation as Markdown or JSON.
- The sidebar displays turn counts rather than raw stored message counts, so one user prompt plus its Quick/Council answer is treated as one turn.

### File Chat

1. Upload files with the upload button, drag-and-drop, or paste supported images.
2. Review the file queue before sending.
3. Send with Council or Quick mode.
4. Use Context Preview when the file payload or conversation history is large.

### Search History

Use the sidebar search box to search across stored conversations. Results show the conversation title, source, role/message index, badges, and excerpt. Clicking a message result opens the conversation and jumps to the matched message. Memory results jump to the Context area.

Search can be filtered by active/archived view, favorite, tag, source, mode, files, failed runs, pinned content, and context-excluded content.

### Search Current Conversation

Use **Search in this conversation** at the top of the message list. It searches user messages, assistant final answers, council details, and file metadata. Prev/Next buttons navigate between hits and highlight the target message. Long conversations use virtualized rendering but still support far-message search and turn jumps.

### Manage Context

- Pin important messages so they remain eligible for future context.
- Exclude messages that should not be sent in later context payloads.
- Use Context Preview before sending a large or sensitive turn.
- Use context replay/rebuild to inspect how a stored turn's context was constructed.
- Add durable memory from the Context panel when a reusable fact should persist.

### Recover Failed Runs

When a model call fails, the assistant message may show an ErrorActionPanel. Depending on the failure, use:

- **Continue** to resume from saved completed stages.
- **Retry** to rerun from scratch.
- **LLM Settings** for provider/model/key issues.
- **Context Policy** for context-limit issues.
- **Diagnostics** to inspect folded technical details.

### Rich Content Operations

- Copy or download code blocks.
- Expand long code blocks.
- Use table search/sort and CSV download.
- Preview Mermaid diagrams and download SVG/PNG.
- Copy formula source for math blocks.
- Switch between light and dark theme from the top-left title area.

## Testing and Verification

The current regression matrix is documented in [docs/regression-matrix.md](docs/regression-matrix.md). It separates quick checks, pre-commit checks, and release smoke. Conversation backup and recovery steps are documented in [docs/conversation-backup-recovery.md](docs/conversation-backup-recovery.md).

### Backend Checks

```bash
pytest tests/test_conversation_export_api.py tests/test_version_api.py tests/test_conversation_metadata_api.py -q
pytest tests/test_quick_stream.py tests/test_resume_stream.py tests/test_conversation_fork_api.py -q
```

### Frontend Checks

```bash
cd frontend
npm test -- ChatInterface.test.jsx RichMarkdown.test.jsx
npm run lint
npm run build
```

### Playwright Smoke for Deployed Service

Install Chromium once:

```bash
cd frontend
npm run test:e2e:install
```

If a headless cloud server is missing OS libraries, install Playwright's Chromium dependencies:

```bash
sudo npx playwright install-deps chromium
```

Run the deployed smoke against the single-port service:

```bash
cd frontend
E2E_BASE_URL=http://127.0.0.1:18080 npm run test:e2e
```

Covered smoke paths:

- app shell loads;
- `/api/conversations` contract works;
- `/api/conversations/search` contract works;
- sidebar search opens a result;
- theme toggle keeps main chat controls visible;
- ordinary and forked Council / Quick sends restore drafts on failure and clear drafts on success;
- formula and Mermaid messages render nonblank rich content without error placeholders.

Generated Playwright artifacts (`test-results/`, `playwright-report/`, `.blob-report/`) are ignored by git.

## Tech Stack

- **Backend:** FastAPI, Python 3.10+, async httpx, Pydantic, pypdf, python-multipart
- **Frontend:** React 19, Vite 7, react-markdown, remark-gfm
- **Rich Rendering:** highlight.js, KaTeX, Mermaid
- **Testing:** pytest, Vitest, Testing Library, jsdom, Playwright
- **Storage:** JSON files in `data/conversations/`
- **Package Management:** uv for Python, npm for JavaScript
- **Deployment:** native Ubuntu deploy script, Nginx same-origin frontend/backend proxy

## Roadmap

The project is currently optimized for a single-user local/cloud deployment. The next useful work is grouped by product value and day-to-day efficiency.

### Functional Improvements

- **Search productization:** richer result facets, source-specific grouping, saved search views, and more complete keyboard workflows.
- **Retry/edit workflow:** clearer diff display for retry-with-edit, safer branch-vs-overwrite choices, and stronger messaging around truncating later turns.
- **Council explainability:** per-model contribution summaries, clearer attribution when some models fail but the run succeeds, and better cost/duration accounting.
- **Diagnostics:** provider network diagnostics, Context Policy checks, API-key/rate-limit guidance, and model availability checks.
- **Rich content:** XLSX export, richer table filtering, code line copy, stronger Mermaid large-diagram handling, and more formula/source controls.
- **Conversation organization polish:** saved-view keyboard workflows, denser bulk-review panels, tag cleanup tools, export presets, and better archive review.

### Efficiency Improvements

- **Long conversation navigation:** message outline from headings/turns, hit-list side panel, per-message top/bottom controls, and better current-position feedback.
- **Input efficiency:** slash-command menu, prompt templates, recent prompts, and clearer draft save timestamps.
- **Frontend performance:** real Markdown AST cache, finer Mermaid/KaTeX cache invalidation, more viewport-based lazy rendering, and streaming-local rerender minimization.
- **Deployment stability:** one-command acceptance script, automatic smoke after service restart, health checks for `18080`, and clearer static asset version verification.
- **Context efficiency:** more readable context preview, visible include/exclude effects before sending, and diagnostics explaining why a past message was or was not included.

## Additional Docs

More detailed design and progress notes live under `docs/`:

- `docs/task-todo.md`: current engineering task progress and priorities.
- `docs/chatbox-feature-optimization-engineering-plan.md`: feature optimization audit and engineering plan.
- `docs/chatbox-conversation-management-report.md`: conversation history and context management report.
- `docs/chatbox-interaction-experience-report.md`: interaction experience optimization report.
- `docs/playwright-smoke.md`: Playwright smoke setup and usage.
