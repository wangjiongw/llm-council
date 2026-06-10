import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ChatInterface from './ChatInterface';

const baseProps = {
  contextAudit: null,
  contextPolicy: null,
  onUpdateContextPolicy: vi.fn(),
  onAddContextMemory: vi.fn(),
  onUpdateContextMemory: vi.fn(),
  onDeleteContextMemory: vi.fn(),
  onSearchConversationHistory: vi.fn(),
  onPreviewContext: vi.fn(),
  onReplayMessageContext: vi.fn(),
  onClearContextSummary: vi.fn(),
  onRebuildContextSummary: vi.fn(),
  onSendMessage: vi.fn(),
  onSendQuickMessage: vi.fn(),
  onStopQuery: vi.fn(),
  onRetryQuery: vi.fn(),
  onResumeQuery: vi.fn(),
  onToggleMessagePin: vi.fn(),
  onToggleMessageContextExcluded: vi.fn(),
  onForkConversation: vi.fn(),
  onOpenSettings: vi.fn(),
  isLoading: false,
  activeStreamId: null,
  attachedFiles: [],
  onFilesChange: vi.fn(),
  onFileUpload: vi.fn(),
  onDeleteFile: vi.fn(),
  messageJumpTarget: null,
  onMessageJumpHandled: vi.fn(),
  draftToRestore: null,
  onDraftRestored: vi.fn(),
};

const assistantMessage = (response, extra = {}) => ({
  role: 'assistant',
  metadata: { mode: 'quick' },
  stage3: { response, status: 'success', model: 'local/test' },
  ...extra,
});

const renderChat = (conversation, props = {}) => render(
  <ChatInterface
    {...baseProps}
    {...props}
    conversation={conversation}
  />
);

beforeEach(() => {
  window.localStorage.clear();
  Element.prototype.scrollIntoView.mockClear();
  HTMLElement.prototype.scrollTo.mockClear();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('ChatInterface conversation efficiency controls', () => {
  it('searches within the current conversation and scrolls to the active message hit', async () => {
    const user = userEvent.setup();
    const conversation = {
      id: 'conv-search',
      messages: [
        { role: 'user', content: 'First question' },
        assistantMessage('First answer'),
        { role: 'user', content: 'Second question' },
        assistantMessage('The useful needle appears in this answer.'),
      ],
    };

    renderChat(conversation);
    Element.prototype.scrollIntoView.mockClear();

    await user.type(screen.getByLabelText('Search in this conversation'), 'needle');

    expect(await screen.findByText('1 / 1 · 1 hits')).toBeInTheDocument();
    expect(screen.getByText(/assistant · Turn 2/i)).toBeInTheDocument();
    await waitFor(() => {
      expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth', block: 'start' });
    });
  });

  it('renders and positions a far search hit when the message list is virtualized', async () => {
    const user = userEvent.setup();
    const messages = Array.from({ length: 90 }, (_, index) => (
      index % 2 === 0
        ? { role: 'user', content: index === 88 ? 'far target needle in a long conversation' : 'Question ' + index }
        : assistantMessage('Answer ' + index)
    ));
    const conversation = { id: 'conv-virtual', messages };

    renderChat(conversation);
    Element.prototype.scrollIntoView.mockClear();
    HTMLElement.prototype.scrollTo.mockClear();

    await user.type(screen.getByLabelText('Search in this conversation'), 'far target');

    await waitFor(() => {
      expect(HTMLElement.prototype.scrollTo).toHaveBeenCalledWith(expect.objectContaining({
        behavior: 'smooth',
        top: expect.any(Number),
      }));
    });
    await waitFor(() => {
      expect(screen.getAllByText(/far target needle in a long conversation/).length).toBeGreaterThan(0);
    });
    await waitFor(() => {
      expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth', block: 'start' });
    });
  });

  it('previews historical assistant answers and keeps the latest answer expanded', () => {
    const conversation = {
      id: 'conv-collapse',
      messages: [
        { role: 'user', content: 'Old question' },
        assistantMessage('Historical answer preview should stay visible.'),
        { role: 'user', content: 'New question' },
        assistantMessage('Latest generated answer remains visible.'),
      ],
    };

    const { container } = renderChat(conversation);
    const renderedFinalAnswers = [...container.querySelectorAll('.final-text')]
      .map((node) => node.textContent || '')
      .join('\n');

    expect(renderedFinalAnswers).toMatch(/Historical answer preview should stay visible/i);
    expect(renderedFinalAnswers).toMatch(/Latest generated answer remains visible/i);
    expect(screen.getAllByRole('button', { name: /Show full answer/i }).length).toBeGreaterThan(0);
  });

  it('keeps the draft when the active conversation rejects a council send', async () => {
    const user = userEvent.setup();
    const onSendMessage = vi.fn(() => false);
    const conversation = { id: 'conv-pending', messages: [] };

    renderChat(conversation, { onSendMessage });
    const input = screen.getByPlaceholderText(/Ask/i);

    await user.type(input, 'follow up question');
    await user.click(screen.getByRole('button', { name: /Send to council/i }));

    expect(onSendMessage).toHaveBeenCalledWith('follow up question', []);
    expect(input).toHaveValue('follow up question');
  });

  it('keeps the draft when the active conversation rejects a quick send', async () => {
    const user = userEvent.setup();
    const onSendQuickMessage = vi.fn(() => false);
    const conversation = { id: 'conv-quick-pending', messages: [] };

    renderChat(conversation, { onSendQuickMessage });
    const input = screen.getByPlaceholderText(/Ask/i);

    await user.type(input, 'quick follow up');
    await user.click(screen.getByRole('button', { name: /Quick query/i }));

    expect(onSendQuickMessage).toHaveBeenCalledWith('quick follow up', []);
    expect(input).toHaveValue('quick follow up');
  });

  it('clears the draft only after a council send is accepted', async () => {
    const user = userEvent.setup();
    const onSendMessage = vi.fn(() => true);
    const conversation = { id: 'conv-success', messages: [] };

    renderChat(conversation, { onSendMessage });
    const input = screen.getByPlaceholderText(/Ask/i);

    await user.type(input, 'accepted question');
    await user.click(screen.getByRole('button', { name: /Send to council/i }));

    expect(onSendMessage).toHaveBeenCalledWith('accepted question', []);
    expect(input).toHaveValue('');
  });

  it('clears the draft only after a quick send is accepted', async () => {
    const user = userEvent.setup();
    const onSendQuickMessage = vi.fn(() => true);
    const conversation = { id: 'conv-quick-success', messages: [] };

    renderChat(conversation, { onSendQuickMessage });
    const input = screen.getByPlaceholderText(/Ask/i);

    await user.type(input, 'accepted quick question');
    await user.click(screen.getByRole('button', { name: /Quick query/i }));

    expect(onSendQuickMessage).toHaveBeenCalledWith('accepted quick question', []);
    expect(input).toHaveValue('');
  });

  it('restores an unsent draft back into the input and reports restoration', async () => {
    const onDraftRestored = vi.fn();
    const conversation = { id: 'conv-restore', messages: [] };
    const { rerender } = renderChat(conversation, { onDraftRestored });

    rerender(
      <ChatInterface
        {...baseProps}
        conversation={conversation}
        onDraftRestored={onDraftRestored}
        draftToRestore={{ id: 'draft-restore', restoreId: 'restore-1', content: 'restore this draft' }}
      />
    );

    await waitFor(() => {
      expect(screen.getByPlaceholderText(/Ask/i)).toHaveValue('restore this draft');
    });
    expect(onDraftRestored).toHaveBeenCalledWith('restore-1');
  });

  it('persists and restores draft text with the selected send mode', async () => {
    const user = userEvent.setup();
    const conversation = { id: 'conv-mode-draft', messages: [] };

    const { unmount } = renderChat(conversation);
    const modeToggle = screen.getByLabelText('Draft send mode');
    await user.click(within(modeToggle).getByRole('button', { name: 'Quick' }));
    await user.type(screen.getByPlaceholderText(/Ask/i), 'mode-aware draft');

    await waitFor(() => {
      expect(window.localStorage.getItem('llm-council:draft:conv-mode-draft')).toContain('mode-aware draft');
      expect(window.localStorage.getItem('llm-council:draft:conv-mode-draft')).toContain('quick');
    });

    unmount();
    renderChat(conversation);

    await waitFor(() => {
      expect(screen.getByPlaceholderText(/Ask/i)).toHaveValue('mode-aware draft');
    });
    expect(within(screen.getByLabelText('Draft send mode')).getByRole('button', { name: 'Quick' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('restores older raw text drafts without mode metadata', async () => {
    const conversation = { id: 'conv-legacy-draft', messages: [] };
    window.localStorage.setItem('llm-council:draft:conv-legacy-draft', 'legacy raw draft');

    renderChat(conversation);

    await waitFor(() => {
      expect(screen.getByPlaceholderText(/Ask/i)).toHaveValue('legacy raw draft');
    });
    expect(within(screen.getByLabelText('Draft send mode')).getByRole('button', { name: 'Council' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('uses the selected mode for Enter and the alternate mode for Ctrl+Enter', async () => {
    const user = userEvent.setup();
    const onSendMessage = vi.fn(() => true);
    const onSendQuickMessage = vi.fn(() => true);
    const conversation = { id: 'conv-mode-submit', messages: [] };

    renderChat(conversation, { onSendMessage, onSendQuickMessage });
    const input = screen.getByPlaceholderText(/Ask/i);
    await user.click(within(screen.getByLabelText('Draft send mode')).getByRole('button', { name: 'Quick' }));
    await user.type(input, 'selected quick');
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' });

    expect(onSendQuickMessage).toHaveBeenCalledWith('selected quick', []);
    expect(onSendMessage).not.toHaveBeenCalled();

    await user.type(input, 'alternate council');
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter', ctrlKey: true });

    expect(onSendMessage).toHaveBeenCalledWith('alternate council', []);
  });

  it('inserts local prompt templates into the draft', async () => {
    const user = userEvent.setup();
    const conversation = { id: 'conv-template', messages: [] };

    renderChat(conversation);
    await user.selectOptions(screen.getByLabelText('Prompt template'), 'code-review');

    expect(screen.getByPlaceholderText(/Ask/i).value).toContain('Review the following code for correctness');
  });

  it('shows retry-with-edit preview and submits the selected retry mode', async () => {
    const user = userEvent.setup();
    const onRetryQuery = vi.fn();
    const conversation = {
      id: 'conv-retry-preview',
      messages: [
        { role: 'user', content: 'original question' },
        assistantMessage('original answer'),
      ],
    };

    renderChat(conversation, { onRetryQuery });
    await user.click(screen.getByRole('button', { name: 'Edit this message' }));

    expect(screen.getByText(/Retry preview: Council mode/)).toBeInTheDocument();
    await user.click(within(screen.getByLabelText('Draft send mode')).getByRole('button', { name: 'Quick' }));
    expect(screen.getByText(/Retry preview: Quick mode/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /Retry edited message with quick mode/i }));
    expect(onRetryQuery).toHaveBeenCalledWith(expect.objectContaining({
      messageIndex: 0,
      editedContent: 'original question',
      mode: 'quick',
    }));
  });

  it('shows a council run summary with model failures, fallback attempts, tokens, and timings', () => {
    const conversation = {
      id: 'conv-council-summary',
      messages: [
        { role: 'user', content: 'Explain reliability' },
        {
          role: 'assistant',
          metadata: { mode: 'council', warnings: ['Stage 1 had 1 failed model call.'] },
          stage1: [
            { model: 'vendor/model-a', response: 'A', status: 'success', usage: { total_tokens: 12 }, duration_seconds: 4 },
            { model: 'vendor/model-b', status: 'failed', error_type: 'timeout', error: 'slow' },
          ],
          stage2: [
            { model: 'vendor/judge', ranking: 'A wins', status: 'success', usage: { total_tokens: 8 }, duration_seconds: 5 },
          ],
          stage3: {
            response: 'Final synthesis',
            status: 'success',
            model: 'vendor/chair',
            usage: { total_tokens: 20 },
            duration_seconds: 6,
            metadata: {
              attempts: [
                { model: 'vendor/primary-chair', ok: false, error_type: 'timeout', error: 'slow' },
                { model: 'vendor/chair', ok: true },
              ],
            },
          },
        },
      ],
    };

    renderChat(conversation);

    expect(screen.getByLabelText('Council run summary')).toBeInTheDocument();
    expect(screen.getByText('Stage 1 1/2, 1 failed')).toBeInTheDocument();
    expect(screen.getByText('Stage 2 1/1')).toBeInTheDocument();
    expect(screen.getByText('Chair chair')).toBeInTheDocument();
    expect(screen.getByText('2 model failures')).toBeInTheDocument();
    expect(screen.getByText('1 fallback attempt')).toBeInTheDocument();
    expect(screen.getByText('40 tokens')).toBeInTheDocument();
    expect(screen.getByText('slowest 6s')).toBeInTheDocument();
    expect(screen.getByText('Stage 1 had 1 failed model call.')).toBeInTheDocument();
  });

  it('opens provider diagnostics from provider-related error actions', async () => {
    const user = userEvent.setup();
    const onOpenSettings = vi.fn();
    const conversation = {
      id: 'conv-provider-error',
      messages: [
        { role: 'user', content: 'Why did this fail?' },
        {
          role: 'assistant',
          metadata: { mode: 'council' },
          status: 'failed',
          stage1: [],
          stage2: [],
          stage3: { status: 'failed', response: '', model: 'vendor/chair', error_type: 'timeout', error: 'provider timed out' },
        },
      ],
    };

    renderChat(conversation, { onOpenSettings });

    expect(screen.getByText('Provider request did not complete')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Provider Diagnostics/i }));
    expect(onOpenSettings).toHaveBeenCalledTimes(1);
  });

  it('does not submit when Enter commits IME composition', async () => {
    const onSendMessage = vi.fn();
    const conversation = { id: 'conv-ime', messages: [] };

    renderChat(conversation, { onSendMessage });
    const input = screen.getByPlaceholderText(/Ask/i);

    fireEvent.change(input, { target: { value: 'english from ime' } });
    fireEvent.compositionStart(input);
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter', isComposing: true, keyCode: 229, which: 229 });
    expect(onSendMessage).not.toHaveBeenCalled();

    fireEvent.compositionEnd(input);
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' });
    expect(onSendMessage).not.toHaveBeenCalled();

    await new Promise((resolve) => window.setTimeout(resolve, 150));
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' });
    expect(onSendMessage).toHaveBeenCalledWith('english from ime', []);
  });
});
