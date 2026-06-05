import { fireEvent, render, screen, waitFor } from '@testing-library/react';
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
