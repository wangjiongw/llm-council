import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Sidebar from './Sidebar';

const baseProps = {
  conversations: [
    { id: 'conv-1', title: 'Architecture Notes', created_at: '2026-06-01T00:00:00Z', updated_at: '2026-06-02T00:00:00Z', tags: ['context'], pinned: true, favorite: true },
    { id: 'conv-2', title: 'Other Notes', created_at: '2026-05-01T00:00:00Z', updated_at: '2026-05-02T00:00:00Z', tags: [], pinned: false, favorite: false },
  ],
  currentConversationId: 'conv-1',
  onSelectConversation: vi.fn(),
  onNewConversation: vi.fn(),
  onUpdateTitle: vi.fn(),
  onUpdateMetadata: vi.fn(),
  onDeleteConversation: vi.fn(),
  onOpenSettings: vi.fn(),
  onToggleTheme: vi.fn(),
  theme: 'light',
};

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('Sidebar search results', () => {
  it('groups search hits by conversation and opens the active hit with the query attached', async () => {
    const onSelectSearchResult = vi.fn();
    const onSearchConversationHistory = vi.fn(async () => [
      {
        conversation_id: 'conv-1',
        conversation_title: 'Architecture Notes',
        updated_at: '2026-06-02T00:00:00Z',
        source: 'message',
        role: 'assistant',
        message_index: 3,
        excerpt: 'The assembly decision belongs in context.',
        modes: ['council'],
        has_files: true,
        conversation_pinned: true,
        favorite: true,
      },
      {
        conversation_id: 'conv-1',
        conversation_title: 'Architecture Notes',
        updated_at: '2026-06-02T00:00:00Z',
        source: 'memory',
        role: 'memory',
        memory_id: 'mem-1',
        excerpt: 'Keep the architecture context pinned.',
        modes: ['quick', 'council'],
        has_files: true,
        conversation_pinned: true,
        favorite: true,
      },
    ]);

    const user = userEvent.setup();

    render(
      <Sidebar
        {...baseProps}
        onSearchConversationHistory={onSearchConversationHistory}
        onSelectSearchResult={onSelectSearchResult}
      />
    );

    await user.type(screen.getByLabelText('Search conversation history'), 'context');

    await waitFor(() => expect(onSearchConversationHistory).toHaveBeenCalledWith('context'));
    const group = screen.getByText('Architecture Notes').closest('.sidebar-search-group');
    expect(group).toBeTruthy();
    expect(within(group).getByText('2 hits')).toBeInTheDocument();
    expect(within(group).getByText('Pinned')).toBeInTheDocument();
    expect(within(group).getByText('Files')).toBeInTheDocument();

    await user.keyboard('{Enter}');
    expect(onSelectSearchResult).toHaveBeenCalledWith(expect.objectContaining({
      conversation_id: 'conv-1',
      message_index: 3,
      query: 'context',
    }));
  });
});
