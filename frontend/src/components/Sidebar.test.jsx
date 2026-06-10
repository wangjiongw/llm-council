import { fireEvent, render, screen, waitFor, waitForElementToBeRemoved, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Sidebar from './Sidebar';

const baseProps = {
  conversations: [
    { id: 'conv-1', title: 'Architecture Notes', created_at: '2026-06-01T00:00:00Z', updated_at: '2026-06-02T00:00:00Z', message_count: 4, turn_count: 2, tags: ['context'], pinned: true, favorite: true },
    { id: 'conv-2', title: 'Other Notes', created_at: '2026-05-01T00:00:00Z', updated_at: '2026-05-02T00:00:00Z', message_count: 1, turn_count: 1, tags: [], pinned: false, favorite: false },
  ],
  currentConversationId: 'conv-1',
  onSelectConversation: vi.fn(),
  onNewConversation: vi.fn(),
  onUpdateTitle: vi.fn(),
  onUpdateMetadata: vi.fn(),
  conversationManagement: {
    tag_colors: { context: '#2563eb' },
    saved_views: [],
  },
  onBatchUpdateConversations: vi.fn(),
  onUpdateTagColor: vi.fn(),
  onSaveView: vi.fn(),
  onDeleteView: vi.fn(),
  onSuggestTitle: vi.fn(),
  onExportConversation: vi.fn(),
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

  it('expands and collapses all grouped search results', async () => {
    const user = userEvent.setup();
    const secondGroupHits = Array.from({ length: 4 }, (_, index) => ({
      conversation_id: 'conv-2',
      conversation_title: 'Other Notes',
      updated_at: '2026-05-02T00:00:00Z',
      source: 'message',
      role: index % 2 === 0 ? 'user' : 'assistant',
      message_index: index,
      excerpt: `Other grouped context hit ${index + 1}`,
    }));
    const onSearchConversationHistory = vi.fn(async () => [
      {
        conversation_id: 'conv-1',
        conversation_title: 'Architecture Notes',
        updated_at: '2026-06-02T00:00:00Z',
        source: 'message',
        role: 'assistant',
        message_index: 1,
        excerpt: 'Architecture grouped context hit',
      },
      ...secondGroupHits,
    ]);

    render(
      <Sidebar
        {...baseProps}
        onSearchConversationHistory={onSearchConversationHistory}
      />
    );

    await user.type(screen.getByLabelText('Search conversation history'), 'context');
    await waitFor(() => expect(onSearchConversationHistory).toHaveBeenCalledWith('context'));

    const actions = screen.getByLabelText('Search result group actions');
    const hasExcerpt = (text) => [...document.querySelectorAll('.sidebar-search-result-excerpt')]
      .some((node) => node.textContent.includes(text));
    expect(hasExcerpt('Other grouped context hit 4')).toBe(false);

    await user.click(within(actions).getByRole('button', { name: 'Expand all' }));
    expect(hasExcerpt('Other grouped context hit 4')).toBe(true);

    await user.click(within(actions).getByRole('button', { name: 'Collapse all' }));
    expect(hasExcerpt('Other grouped context hit 4')).toBe(false);
  });
});


describe('Sidebar conversation management controls', () => {
  it('filters conversation list by file, failure, memory, and pinned facets', async () => {
    const user = userEvent.setup();
    render(
      <Sidebar
        {...baseProps}
        conversations={[
          { ...baseProps.conversations[0], has_files: true, has_failed_run: false, has_memory: false, pinned_message_count: 1 },
          { ...baseProps.conversations[1], title: 'Plain Notes', has_files: false, has_failed_run: false, has_memory: false },
          { id: 'conv-3', title: 'Broken Memory Run', created_at: '2026-06-03T00:00:00Z', updated_at: '2026-06-03T00:00:00Z', message_count: 2, turn_count: 1, tags: [], pinned: false, favorite: false, has_files: false, has_failed_run: true, has_memory: true },
        ]}
      />
    );

    const facets = screen.getByLabelText('Conversation facets');
    expect(screen.getByText('Architecture Notes')).toBeInTheDocument();
    expect(screen.getByText('Broken Memory Run')).toBeInTheDocument();

    await user.click(within(facets).getByRole('button', { name: 'Failed' }));
    expect(screen.getByText('Broken Memory Run')).toBeInTheDocument();
    expect(screen.queryByText('Architecture Notes')).not.toBeInTheDocument();

    await user.click(within(facets).getByRole('button', { name: 'Memory' }));
    expect(screen.getByText('Broken Memory Run')).toBeInTheDocument();

    await user.click(within(facets).getByRole('button', { name: 'Clear' }));
    await user.click(within(facets).getByRole('button', { name: 'Files' }));
    expect(screen.getByText('Architecture Notes')).toBeInTheDocument();
    expect(screen.queryByText('Broken Memory Run')).not.toBeInTheDocument();

    await user.click(within(facets).getByRole('button', { name: 'Clear' }));
    await user.click(within(facets).getByRole('button', { name: 'Pinned' }));
    expect(screen.getByText('Architecture Notes')).toBeInTheDocument();
    expect(screen.queryByText('Plain Notes')).not.toBeInTheDocument();
  });

  it('batch-updates selected conversations', async () => {
    const onBatchUpdateConversations = vi.fn(async () => ({ conversations: [] }));
    const user = userEvent.setup();

    render(
      <Sidebar
        {...baseProps}
        onBatchUpdateConversations={onBatchUpdateConversations}
      />
    );

    expect(screen.getByText('2 turns')).toBeInTheDocument();

    await user.click(screen.getByLabelText('Select Architecture Notes'));
    await user.click(screen.getByRole('button', { name: 'Favorite' }));

    expect(onBatchUpdateConversations).toHaveBeenCalledWith(['conv-1'], { favorite: true }, 'replace');
  });

  it('edits and removes tags on a single conversation', async () => {
    const onUpdateMetadata = vi.fn(async () => {});
    const user = userEvent.setup();

    render(
      <Sidebar
        {...baseProps}
        onUpdateMetadata={onUpdateMetadata}
      />
    );

    await user.click(screen.getByLabelText('Remove tag context from Architecture Notes'));
    expect(onUpdateMetadata).toHaveBeenCalledWith('conv-1', { tags: [] });

    await user.click(screen.getByLabelText('Edit tags for Architecture Notes'));
    const input = screen.getByPlaceholderText('tag-a, tag-b / 标签一，标签二');
    await user.clear(input);
    await user.type(input, 'context，review、论文；上下文');
    await user.keyboard('{Enter}');

    expect(onUpdateMetadata).toHaveBeenCalledWith('conv-1', { tags: ['context', 'review', '论文', '上下文'] });
  });

  it('saves current filters and updates tag colors', async () => {
    const onSaveView = vi.fn(async () => ({
      tag_colors: { context: '#123abc' },
      saved_views: [{ id: 'view-1', name: 'Context only', filters: { tagFilter: 'context' } }],
    }));
    const onUpdateTagColor = vi.fn(async () => ({ tag_colors: { context: '#123abc' }, saved_views: [] }));
    const user = userEvent.setup();

    render(
      <Sidebar
        {...baseProps}
        onSaveView={onSaveView}
        onUpdateTagColor={onUpdateTagColor}
      />
    );

    await user.click(within(screen.getByLabelText('Conversation facets')).getByRole('button', { name: 'Memory' }));
    await user.type(screen.getByLabelText('Saved view name'), 'Context only');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(onSaveView).toHaveBeenCalledWith('Context only', expect.objectContaining({
      viewMode: 'active',
      tagFilter: '',
      listFacets: expect.objectContaining({ hasMemory: true }),
    }));

    fireEvent.change(screen.getByLabelText('Color for context'), { target: { value: '#123abc' } });
    expect(onUpdateTagColor).toHaveBeenCalledWith('context', '#123abc');
  });

  it('applies title suggestions to a conversation when requested', async () => {
    const onSuggestTitle = vi.fn(async () => ['Context Architecture']);
    const onUpdateTitle = vi.fn(async () => {});
    const user = userEvent.setup();

    render(
      <Sidebar
        {...baseProps}
        onSuggestTitle={onSuggestTitle}
        onUpdateTitle={onUpdateTitle}
      />
    );

    await user.click(screen.getAllByTitle('Auto title with LLM')[0]);

    expect(onSuggestTitle).toHaveBeenCalledWith('conv-1');
    await waitFor(() => {
      expect(onUpdateTitle).toHaveBeenCalledWith('conv-1', 'Context Architecture', { source: 'local', locked: false });
    });
    expect(await screen.findByRole('button', { name: 'Context Architecture' })).toBeInTheDocument();
  });

  it('shows a status when generated titles match the current title', async () => {
    const onSuggestTitle = vi.fn(async () => ({ suggestions: ['Architecture Notes'], source: 'local' }));
    const onUpdateTitle = vi.fn(async () => {});
    const user = userEvent.setup();

    render(
      <Sidebar
        {...baseProps}
        onSuggestTitle={onSuggestTitle}
        onUpdateTitle={onUpdateTitle}
      />
    );

    await user.click(screen.getAllByTitle('Auto title with LLM')[0]);

    expect(onSuggestTitle).toHaveBeenCalledWith('conv-1');
    await waitFor(() => expect(screen.getByText('No better title found')).toBeInTheDocument());
    expect(onUpdateTitle).not.toHaveBeenCalled();
  });

  it('shows a dismissible status when title generation fails', async () => {
    const onSuggestTitle = vi.fn(async () => {
      throw new Error('provider unavailable');
    });
    const onUpdateTitle = vi.fn(async () => {});
    const user = userEvent.setup();

    render(
      <Sidebar
        {...baseProps}
        onSuggestTitle={onSuggestTitle}
        onUpdateTitle={onUpdateTitle}
      />
    );

    await user.click(screen.getAllByTitle('Auto title with LLM')[0]);

    await waitFor(() => expect(screen.getByText('Title generation failed')).toBeInTheDocument());
    expect(onUpdateTitle).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'Dismiss title status' }));
    expect(screen.queryByText('Title generation failed')).not.toBeInTheDocument();
  });

  it('auto-dismisses completed title statuses', async () => {
    const onSuggestTitle = vi.fn(async () => ({ suggestions: ['Architecture Notes'], source: 'local' }));
    const onUpdateTitle = vi.fn(async () => {});
    const user = userEvent.setup();

    render(
      <Sidebar
        {...baseProps}
        onSuggestTitle={onSuggestTitle}
        onUpdateTitle={onUpdateTitle}
      />
    );

    await user.click(screen.getAllByTitle('Auto title with LLM')[0]);

    await waitFor(() => expect(screen.getByText('No better title found')).toBeInTheDocument());
    await waitForElementToBeRemoved(() => screen.queryByText('No better title found'), { timeout: 4500 });
  }, 7000);
});
