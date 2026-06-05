import { useEffect, useMemo, useState } from 'react';
import { formatTurnCount } from '../utils/conversationUtils';
import './Sidebar.css';


const SIDEBAR_STATE_STORAGE_KEY = 'llm-council:sidebar-state:v2';
const DEFAULT_SIDEBAR_STATE = {
  viewMode: 'active',
  favoriteOnly: false,
  tagFilter: '',
  historySearchQuery: '',
  historySearchSource: 'all',
  historySearchMode: 'all',
  searchFlags: {
    hasFiles: false,
    failedOnly: false,
    pinnedOnly: false,
    contextExcludedOnly: false,
  },
};

const DEFAULT_TAG_COLORS = ['#2563eb', '#16a34a', '#d97706', '#dc2626', '#7c3aed', '#0891b2', '#be123c', '#4f46e5'];

const fallbackTagColor = (tag) => {
  const source = String(tag || '').toLowerCase();
  const index = [...source].reduce((sum, char) => sum + char.charCodeAt(0), 0) % DEFAULT_TAG_COLORS.length;
  return DEFAULT_TAG_COLORS[index];
};

const readSidebarState = () => {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(SIDEBAR_STATE_STORAGE_KEY) || '{}');
    return {
      ...DEFAULT_SIDEBAR_STATE,
      ...parsed,
      searchFlags: {
        ...DEFAULT_SIDEBAR_STATE.searchFlags,
        ...(parsed.searchFlags || {}),
      },
    };
  } catch {
    return DEFAULT_SIDEBAR_STATE;
  }
};

const writeSidebarState = (state) => {
  try {
    window.localStorage.setItem(SIDEBAR_STATE_STORAGE_KEY, JSON.stringify(state));
  } catch {
    // Local storage can be unavailable in private or restricted browser contexts.
  }
};

const startOfDay = (date) => new Date(date.getFullYear(), date.getMonth(), date.getDate());

const groupConversationDate = (value) => {
  if (!value) return 'Older';

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Older';

  const today = startOfDay(new Date());
  const target = startOfDay(date);
  const dayDelta = Math.floor((today - target) / 86400000);

  if (dayDelta <= 0) return 'Today';
  if (dayDelta === 1) return 'Yesterday';
  if (dayDelta < 7) return 'Previous 7 days';
  if (dayDelta < 30) return 'Previous 30 days';
  return 'Older';
};


const sortConversations = (conversations) => [...conversations].sort((a, b) => {
  const pinnedDelta = Number(Boolean(b.pinned)) - Number(Boolean(a.pinned));
  if (pinnedDelta !== 0) return pinnedDelta;
  const bTime = new Date(b.updated_at || b.created_at || 0).getTime() || 0;
  const aTime = new Date(a.updated_at || a.created_at || 0).getTime() || 0;
  return bTime - aTime;
});

const groupConversations = (conversations, { archivedView = false } = {}) => {
  const groups = [];
  const groupMap = new Map();
  const sorted = sortConversations(conversations);
  const pinned = archivedView ? [] : sorted.filter((conversation) => conversation.pinned);
  const regular = archivedView ? sorted : sorted.filter((conversation) => !conversation.pinned);

  if (pinned.length > 0) {
    groups.push({ label: 'Pinned', conversations: pinned });
  }

  regular.forEach((conversation) => {
    const label = groupConversationDate(conversation.updated_at || conversation.created_at);
    if (!groupMap.has(label)) {
      const group = { label, conversations: [] };
      groupMap.set(label, group);
      groups.push(group);
    }
    groupMap.get(label).conversations.push(conversation);
  });

  return groups;
};

const TAG_SEPARATOR_PATTERN = /[,，、;；\n\r]+/;

const parseTags = (value) => value
  .split(TAG_SEPARATOR_PATTERN)
  .map((tag) => tag.trim())
  .filter(Boolean);

const escapeRegExp = (value) => String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

function HighlightedText({ text, query }) {
  const source = String(text || '');
  const cleanQuery = String(query || '').trim();
  if (!cleanQuery) return source;
  const pattern = new RegExp(`(${escapeRegExp(cleanQuery)})`, 'gi');
  return source.split(pattern).map((part, index) => (
    part.toLowerCase() === cleanQuery.toLowerCase()
      ? <mark className="search-hit" key={`${part}-${index}`}>{part}</mark>
      : part
  ));
}

const searchSourceLabel = (result) => {
  if (result.source === 'title') return 'Title';
  if (result.source === 'memory') return 'Memory';
  if (result.role === 'user') return `User message ${Number.isInteger(result.message_index) ? result.message_index + 1 : ''}`.trim();
  if (result.role === 'assistant') return `Assistant message ${Number.isInteger(result.message_index) ? result.message_index + 1 : ''}`.trim();
  return result.source || 'Result';
};


const searchResultTurnNumber = (result) => {
  if (Number.isInteger(result.turn_number)) return result.turn_number;
  if (Number.isInteger(result.message_index)) return Math.floor(result.message_index / 2) + 1;
  return null;
};

const searchResultKey = (result, index) => `${result.conversation_id}-${result.source}-${result.message_index ?? result.memory_id ?? 'meta'}-${index}`;

const formatSearchDate = (value) => {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
};

const searchBadgesFor = (result) => [
  result.conversation_pinned ? 'Pinned' : '',
  result.favorite ? 'Favorite' : '',
  result.has_files ? 'Files' : '',
  result.has_failed_run || ['failed', 'interrupted'].includes(result.status) ? 'Failed' : '',
  result.context_excluded ? 'Excluded' : '',
  Array.isArray(result.modes) && result.modes.length ? result.modes.join('/') : result.mode || '',
].filter(Boolean);

const groupSearchResults = (results) => {
  const groups = [];
  const byConversation = new Map();

  results.forEach((result, flatIndex) => {
    const conversationId = result.conversation_id || 'unknown';
    if (!byConversation.has(conversationId)) {
      const group = {
        conversationId,
        title: result.conversation_title || 'New Conversation',
        updatedAt: result.updated_at || result.created_at || '',
        results: [],
        badges: new Set(),
      };
      byConversation.set(conversationId, group);
      groups.push(group);
    }

    const group = byConversation.get(conversationId);
    group.results.push({ ...result, flatIndex });
    searchBadgesFor(result).forEach((badge) => group.badges.add(badge));
  });

  return groups.map((group) => ({
    ...group,
    badges: Array.from(group.badges).slice(0, 5),
  }));
};

export default function Sidebar({
  conversations,
  currentConversationId,
  onSelectConversation,
  onNewConversation,
  onUpdateTitle,
  onUpdateMetadata,
  conversationManagement = { tag_colors: {}, saved_views: [] },
  onBatchUpdateConversations,
  onUpdateTagColor,
  onSaveView,
  onDeleteView,
  onSuggestTitle,
  onExportConversation,
  onDeleteConversation,
  onSearchConversationHistory,
  onSelectSearchResult,
  onOpenSettings,
  theme,
  onToggleTheme,
  width = 260,
  minWidth = 220,
  maxWidth = 520,
  onResize,
}) {
  const [initialSidebarState] = useState(readSidebarState);
  const [editingId, setEditingId] = useState(null);
  const [editTitle, setEditTitle] = useState('');
  const [tagEditingId, setTagEditingId] = useState(null);
  const [tagInput, setTagInput] = useState('');
  const [collapsedGroups, setCollapsedGroups] = useState(() => new Set());
  const [viewMode, setViewMode] = useState(initialSidebarState.viewMode === 'archived' ? 'archived' : 'active');
  const [favoriteOnly, setFavoriteOnly] = useState(Boolean(initialSidebarState.favoriteOnly));
  const [tagFilter, setTagFilter] = useState(initialSidebarState.tagFilter || '');
  const [historySearchQuery, setHistorySearchQuery] = useState(initialSidebarState.historySearchQuery || '');
  const [historySearchSource, setHistorySearchSource] = useState(initialSidebarState.historySearchSource || 'all');
  const [historySearchMode, setHistorySearchMode] = useState(initialSidebarState.historySearchMode || 'all');
  const [searchFlags, setSearchFlags] = useState(initialSidebarState.searchFlags || DEFAULT_SIDEBAR_STATE.searchFlags);
  const [activeSearchResultIndex, setActiveSearchResultIndex] = useState(0);
  const [expandedSearchGroups, setExpandedSearchGroups] = useState(() => new Set());
  const [historySearchResults, setHistorySearchResults] = useState([]);
  const [historySearchLoading, setHistorySearchLoading] = useState(false);
  const [historySearchError, setHistorySearchError] = useState('');
  const [isResizing, setIsResizing] = useState(false);
  const [selectedConversationIds, setSelectedConversationIds] = useState(() => new Set());
  const [batchTagInput, setBatchTagInput] = useState('');
  const [savedViewName, setSavedViewName] = useState('');
  const [activeSavedViewId, setActiveSavedViewId] = useState('');
  const [titleSuggestions, setTitleSuggestions] = useState({});
  const [titleSuggestionLoadingId, setTitleSuggestionLoadingId] = useState(null);

  const allTags = useMemo(() => {
    const tags = new Set();
    conversations.forEach((conversation) => {
      (conversation.tags || []).forEach((tag) => tags.add(tag));
    });
    return [...tags].sort((a, b) => a.localeCompare(b));
  }, [conversations]);

  const tagColors = conversationManagement?.tag_colors || {};
  const savedViews = conversationManagement?.saved_views || [];
  const tagColorFor = (tag) => tagColors[tag] || fallbackTagColor(tag);

  const currentFilters = useMemo(() => ({
    viewMode,
    favoriteOnly,
    tagFilter,
    historySearchQuery,
    historySearchSource,
    historySearchMode,
    searchFlags,
  }), [favoriteOnly, historySearchMode, historySearchQuery, historySearchSource, searchFlags, tagFilter, viewMode]);

  const visibleConversations = useMemo(() => {
    return conversations.filter((conversation) => {
      if (viewMode === 'archived' && !conversation.archived) return false;
      if (viewMode === 'active' && conversation.archived) return false;
      if (favoriteOnly && !conversation.favorite) return false;
      if (tagFilter && !(conversation.tags || []).includes(tagFilter)) return false;
      return true;
    });
  }, [conversations, favoriteOnly, tagFilter, viewMode]);

  const conversationGroups = useMemo(
    () => groupConversations(visibleConversations, { archivedView: viewMode === 'archived' }),
    [visibleConversations, viewMode]
  );

  const visibleConversationIds = useMemo(
    () => new Set(visibleConversations.map((conversation) => conversation.id)),
    [visibleConversations]
  );

  const filteredSearchResults = useMemo(() => (historySearchResults || []).filter((result) => {
    if (!visibleConversationIds.has(result.conversation_id)) return false;
    if (historySearchSource === 'message' && result.source !== 'message') return false;
    if (historySearchSource === 'user' && result.role !== 'user') return false;
    if (historySearchSource === 'assistant' && result.role !== 'assistant') return false;
    if (!['all', 'message', 'user', 'assistant'].includes(historySearchSource) && result.source !== historySearchSource) return false;

    if (historySearchMode !== 'all') {
      const resultModes = Array.isArray(result.modes) ? result.modes : [];
      if (result.mode !== historySearchMode && !resultModes.includes(historySearchMode)) return false;
    }

    if (searchFlags.hasFiles && !result.has_files) return false;
    if (searchFlags.failedOnly && !(result.has_failed_run || ['failed', 'interrupted'].includes(result.status))) return false;
    if (searchFlags.pinnedOnly && !(result.pinned || result.conversation_pinned)) return false;
    if (searchFlags.contextExcludedOnly && !result.context_excluded) return false;
    return true;
  }), [historySearchResults, historySearchMode, historySearchSource, searchFlags, visibleConversationIds]);

  const groupedSearchResults = useMemo(() => groupSearchResults(filteredSearchResults), [filteredSearchResults]);
  const activeSearchResult = filteredSearchResults[Math.max(0, Math.min(activeSearchResultIndex, filteredSearchResults.length - 1))] || null;
  const activeExtraFilterCount = [
    historySearchMode !== 'all',
    searchFlags.hasFiles,
    searchFlags.failedOnly,
    searchFlags.pinnedOnly,
    searchFlags.contextExcludedOnly,
  ].filter(Boolean).length;

  const activeGroupLabel = useMemo(() => {
    const activeGroup = conversationGroups.find((group) =>
      group.conversations.some((conversation) => conversation.id === currentConversationId)
    );
    return activeGroup?.label || '';
  }, [conversationGroups, currentConversationId]);

  useEffect(() => {
    const query = historySearchQuery.trim();
    if (!query || !onSearchConversationHistory) {
      setHistorySearchResults([]);
      setHistorySearchError('');
      setHistorySearchLoading(false);
      return undefined;
    }

    let cancelled = false;
    setHistorySearchLoading(true);
    setHistorySearchError('');

    const timer = window.setTimeout(async () => {
      try {
        const results = await onSearchConversationHistory(query);
        if (!cancelled) setHistorySearchResults(Array.isArray(results) ? results : []);
      } catch (error) {
        if (!cancelled) {
          console.error('Failed to search conversations:', error);
          setHistorySearchResults([]);
          setHistorySearchError('Search failed');
        }
      } finally {
        if (!cancelled) setHistorySearchLoading(false);
      }
    }, 250);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [historySearchQuery, onSearchConversationHistory]);

  useEffect(() => {
    setActiveSearchResultIndex(0);
  }, [historySearchMode, historySearchQuery, historySearchSource, filteredSearchResults.length, searchFlags]);

  useEffect(() => {
    setExpandedSearchGroups(new Set());
  }, [historySearchQuery]);

  useEffect(() => {
    writeSidebarState({
      viewMode,
      favoriteOnly,
      tagFilter,
      historySearchQuery,
      historySearchSource,
      historySearchMode,
      searchFlags,
    });
  }, [favoriteOnly, historySearchMode, historySearchQuery, historySearchSource, searchFlags, tagFilter, viewMode]);

  const handleStartEdit = (conv) => {
    setEditingId(conv.id);
    setEditTitle(conv.title || 'New Conversation');
    setTagEditingId(null);
  };

  const handleSaveEdit = async (convId) => {
    if (editTitle.trim()) {
      await onUpdateTitle(convId, editTitle.trim());
      setEditingId(null);
    }
  };

  const handleCancelEdit = () => {
    setEditingId(null);
    setEditTitle('');
  };

  const handleKeyDown = (e, convId) => {
    if (e.key === 'Enter') {
      handleSaveEdit(convId);
    } else if (e.key === 'Escape') {
      handleCancelEdit();
    }
  };

  const handleStartTagEdit = (conv) => {
    setTagEditingId(conv.id);
    setTagInput((conv.tags || []).join(', '));
    setEditingId(null);
  };

  const handleSaveTags = async (convId) => {
    await onUpdateMetadata(convId, { tags: parseTags(tagInput) });
    setTagEditingId(null);
    setTagInput('');
  };

  const handleRemoveTag = async (event, conv, tagToRemove) => {
    event.stopPropagation();
    const removeKey = String(tagToRemove || '').toLowerCase();
    const nextTags = (conv.tags || []).filter((tag) => String(tag || '').toLowerCase() !== removeKey);
    await onUpdateMetadata(conv.id, { tags: nextTags });
  };

  const handleTagKeyDown = (e, convId) => {
    if (e.key === 'Enter') {
      handleSaveTags(convId);
    } else if (e.key === 'Escape') {
      setTagEditingId(null);
      setTagInput('');
    }
  };

  const handleDeleteConversation = (conversationId) => {
    onDeleteConversation(conversationId);
  };

  const toggleSearchFlag = (flagName) => {
    setSearchFlags((current) => ({
      ...current,
      [flagName]: !current[flagName],
    }));
  };

  const clearSearchFilters = () => {
    setHistorySearchSource('all');
    setHistorySearchMode('all');
    setSearchFlags(DEFAULT_SIDEBAR_STATE.searchFlags);
  };

  const handleApplySavedView = (view) => {
    if (!view) return;
    const filters = view.filters || {};
    setActiveSavedViewId(view.id || '');
    setViewMode(filters.viewMode === 'archived' ? 'archived' : 'active');
    setFavoriteOnly(Boolean(filters.favoriteOnly));
    setTagFilter(filters.tagFilter || '');
    setHistorySearchQuery(filters.historySearchQuery || '');
    setHistorySearchSource(filters.historySearchSource || 'all');
    setHistorySearchMode(filters.historySearchMode || 'all');
    setSearchFlags({
      ...DEFAULT_SIDEBAR_STATE.searchFlags,
      ...(filters.searchFlags || {}),
    });
  };

  const handleSaveView = async () => {
    const name = savedViewName.trim();
    if (!name || !onSaveView) return;
    const management = await onSaveView(name, currentFilters);
    const nextView = (management?.saved_views || []).find((view) => view.name.toLowerCase() === name.toLowerCase());
    setActiveSavedViewId(nextView?.id || '');
    setSavedViewName('');
  };

  const handleDeleteView = async () => {
    if (!activeSavedViewId || !onDeleteView) return;
    await onDeleteView(activeSavedViewId);
    setActiveSavedViewId('');
  };

  const toggleConversationSelection = (event, conversationId) => {
    event.stopPropagation();
    setSelectedConversationIds((current) => {
      const next = new Set(current);
      if (next.has(conversationId)) {
        next.delete(conversationId);
      } else {
        next.add(conversationId);
      }
      return next;
    });
  };

  const selectedConversationList = () => Array.from(selectedConversationIds);

  const handleBatchUpdate = async (updates, tagMode = 'replace') => {
    const ids = selectedConversationList();
    if (!ids.length || !onBatchUpdateConversations) return;
    await onBatchUpdateConversations(ids, updates, tagMode);
    if (!updates.tags) {
      setSelectedConversationIds(new Set());
    }
  };

  const handleBatchTags = async (tagMode) => {
    const tags = parseTags(batchTagInput);
    if (!tags.length) return;
    await handleBatchUpdate({ tags }, tagMode);
    setBatchTagInput('');
  };

  const handleSuggestTitle = async (event, conv) => {
    event.stopPropagation();
    if (!onSuggestTitle) return;
    setTitleSuggestionLoadingId(conv.id);
    try {
      const suggestions = await onSuggestTitle(conv.id);
      setTitleSuggestions((current) => ({ ...current, [conv.id]: suggestions }));
      const currentTitle = (conv.title || 'New Conversation').trim();
      const nextTitle = (suggestions || [])
        .map((title) => String(title || '').trim())
        .find((title) => title && title !== currentTitle);
      if (nextTitle && onUpdateTitle) {
        await onUpdateTitle(conv.id, nextTitle);
      }
    } finally {
      setTitleSuggestionLoadingId(null);
    }
  };

  const handleUseTitleSuggestion = async (event, convId, title) => {
    event.stopPropagation();
    await onUpdateTitle(convId, title);
    setTitleSuggestions((current) => ({ ...current, [convId]: [] }));
  };

  const handleMetadataClick = async (event, conv, updates) => {
    event.stopPropagation();
    await onUpdateMetadata(conv.id, updates);
  };

  const openSearchResult = (result) => {
    if (!result) return;
    const enrichedResult = { ...result, query: historySearchQuery.trim() };
    if (onSelectSearchResult) {
      onSelectSearchResult(enrichedResult);
    } else {
      onSelectConversation(result.conversation_id);
    }
  };

  const toggleSearchGroup = (conversationId) => {
    setExpandedSearchGroups((current) => {
      const next = new Set(current);
      if (next.has(conversationId)) {
        next.delete(conversationId);
      } else {
        next.add(conversationId);
      }
      return next;
    });
  };

  const handleSearchKeyDown = (event) => {
    if (!historySearchQuery.trim()) return;
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActiveSearchResultIndex((current) => Math.min(filteredSearchResults.length - 1, current + 1));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActiveSearchResultIndex((current) => Math.max(0, current - 1));
    } else if (event.key === 'Enter') {
      event.preventDefault();
      openSearchResult(activeSearchResult);
    } else if (event.key === 'Escape') {
      setHistorySearchQuery('');
    }
  };

  const toggleGroupCollapsed = (label) => {
    if (label === activeGroupLabel) return;

    setCollapsedGroups((current) => {
      const next = new Set(current);
      if (next.has(label)) {
        next.delete(label);
      } else {
        next.add(label);
      }
      return next;
    });
  };


  const handleResizePointerDown = (event) => {
    event.preventDefault();
    const pointerId = event.pointerId;
    const handle = event.currentTarget;
    const startX = event.clientX;
    const startWidth = width;

    setIsResizing(true);
    handle.setPointerCapture?.(pointerId);
    document.body.classList.add('sidebar-resizing');

    const handlePointerMove = (moveEvent) => {
      const nextWidth = Math.min(maxWidth, Math.max(minWidth, startWidth + moveEvent.clientX - startX));
      onResize?.(nextWidth);
    };

    const stopResize = () => {
      setIsResizing(false);
      document.body.classList.remove('sidebar-resizing');
      handle.releasePointerCapture?.(pointerId);
      window.removeEventListener('pointermove', handlePointerMove);
      window.removeEventListener('pointerup', stopResize);
      window.removeEventListener('pointercancel', stopResize);
    };

    window.addEventListener('pointermove', handlePointerMove);
    window.addEventListener('pointerup', stopResize);
    window.addEventListener('pointercancel', stopResize);
  };

  return (
    <div
      className={`sidebar ${isResizing ? 'resizing' : ''}`}
      style={{ '--sidebar-width': `${width}px` }}
    >
      <div className="sidebar-header">
        <div className="sidebar-title-row">
          <h1>LLM Council</h1>
          <button
            type="button"
            className="theme-toggle-btn"
            onClick={onToggleTheme}
            aria-pressed={theme === 'dark'}
            title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
          >
            {theme === 'dark' ? '☀' : '☾'}
          </button>
        </div>
        <button className="new-conversation-btn" onClick={onNewConversation}>
          + New Conversation
        </button>
        <button className="settings-btn" onClick={onOpenSettings}>
          LLM Settings
        </button>
        <div className="conversation-filter-bar" aria-label="Conversation filters">
          <button
            type="button"
            className={viewMode === 'active' ? 'active' : ''}
            onClick={() => setViewMode('active')}
          >
            Active
          </button>
          <button
            type="button"
            className={viewMode === 'archived' ? 'active' : ''}
            onClick={() => setViewMode('archived')}
          >
            Archived
          </button>
          <button
            type="button"
            className={favoriteOnly ? 'active' : ''}
            onClick={() => setFavoriteOnly((current) => !current)}
            title="Show favorites only"
          >
            ★
          </button>
        </div>
        {allTags.length > 0 && (
          <select
            className="conversation-tag-filter"
            value={tagFilter}
            onChange={(event) => setTagFilter(event.target.value)}
            aria-label="Filter conversations by tag"
          >
            <option value="">All tags</option>
            {allTags.map((tag) => (
              <option value={tag} key={tag}>{tag}</option>
            ))}
          </select>
        )}
        <div className="saved-view-controls" aria-label="Saved conversation views controls">
          <select
            className="saved-view-select"
            value={activeSavedViewId}
            onChange={(event) => {
              const view = savedViews.find((item) => item.id === event.target.value);
              if (view) {
                handleApplySavedView(view);
              } else {
                setActiveSavedViewId('');
              }
            }}
            aria-label="Saved conversation views"
          >
            <option value="">Saved views</option>
            {savedViews.map((view) => (
              <option value={view.id} key={view.id}>{view.name}</option>
            ))}
          </select>
          <input
            type="text"
            value={savedViewName}
            onChange={(event) => setSavedViewName(event.target.value)}
            onKeyDown={(event) => { if (event.key === 'Enter') handleSaveView(); }}
            placeholder="View name"
            aria-label="Saved view name"
            maxLength={48}
          />
          <button type="button" onClick={handleSaveView} disabled={!savedViewName.trim() || !onSaveView}>Save</button>
          <button type="button" onClick={handleDeleteView} disabled={!activeSavedViewId || !onDeleteView}>Del</button>
        </div>
        {allTags.length > 0 && (
          <div className="tag-color-row" aria-label="Tag colors">
            {allTags.map((tag) => (
              <label className="tag-color-control" key={tag} title={`Color for ${tag}`}>
                <span style={{ '--tag-color': tagColorFor(tag) }}>{tag}</span>
                <input
                  type="color"
                  value={tagColorFor(tag)}
                  onChange={(event) => onUpdateTagColor?.(tag, event.target.value)}
                  aria-label={`Color for ${tag}`}
                />
              </label>
            ))}
          </div>
        )}
        <div className="sidebar-search" role="search">
          <input
            type="search"
            value={historySearchQuery}
            onChange={(event) => setHistorySearchQuery(event.target.value)}
            onKeyDown={handleSearchKeyDown}
            placeholder="Search conversations"
            aria-label="Search conversation history"
          />
          {historySearchQuery && (
            <button
              type="button"
              onClick={() => setHistorySearchQuery('')}
              aria-label="Clear conversation search"
            >
              ×
            </button>
          )}
        </div>
        {historySearchQuery.trim() && (
          <div className="sidebar-search-controls">
            <select
              className="sidebar-search-filter"
              value={historySearchSource}
              onChange={(event) => setHistorySearchSource(event.target.value)}
              aria-label="Filter search result source"
            >
              <option value="all">All sources</option>
              <option value="title">Titles</option>
              <option value="message">Messages</option>
              <option value="user">User messages</option>
              <option value="assistant">Assistant answers</option>
              <option value="memory">Memory</option>
            </select>
            <select
              className="sidebar-search-filter"
              value={historySearchMode}
              onChange={(event) => setHistorySearchMode(event.target.value)}
              aria-label="Filter search result mode"
            >
              <option value="all">All modes</option>
              <option value="quick">Quick</option>
              <option value="council">Council</option>
            </select>
            <div className="sidebar-search-options" aria-label="Search result flags">
              <button type="button" className={searchFlags.hasFiles ? 'active' : ''} onClick={() => toggleSearchFlag('hasFiles')}>Files</button>
              <button type="button" className={searchFlags.failedOnly ? 'active' : ''} onClick={() => toggleSearchFlag('failedOnly')}>Failed</button>
              <button type="button" className={searchFlags.pinnedOnly ? 'active' : ''} onClick={() => toggleSearchFlag('pinnedOnly')}>Pinned</button>
              <button type="button" className={searchFlags.contextExcludedOnly ? 'active' : ''} onClick={() => toggleSearchFlag('contextExcludedOnly')}>Excluded</button>
              {activeExtraFilterCount > 0 && (
                <button type="button" className="clear" onClick={clearSearchFilters}>Clear filters</button>
              )}
            </div>
          </div>
        )}
      </div>

      {selectedConversationIds.size > 0 && (
        <div className="conversation-bulk-toolbar" aria-label="Selected conversation actions">
          <div className="bulk-toolbar-row">
            <strong>{selectedConversationIds.size} selected</strong>
            <button type="button" onClick={() => handleBatchUpdate({ favorite: true })}>Favorite</button>
            <button type="button" onClick={() => handleBatchUpdate({ favorite: false })}>Unfavorite</button>
            <button type="button" onClick={() => handleBatchUpdate({ archived: true })}>Archive</button>
            <button type="button" onClick={() => handleBatchUpdate({ archived: false })}>Restore</button>
            <button type="button" onClick={() => setSelectedConversationIds(new Set())}>Clear</button>
          </div>
          <div className="bulk-toolbar-row">
            <input
              type="text"
              value={batchTagInput}
              onChange={(event) => setBatchTagInput(event.target.value)}
              placeholder="tag-a, tag-b / 标签一，标签二"
              aria-label="Batch tags"
            />
            <button type="button" onClick={() => handleBatchTags('add')} disabled={!batchTagInput.trim()}>Add tags</button>
            <button type="button" onClick={() => handleBatchTags('remove')} disabled={!batchTagInput.trim()}>Remove tags</button>
          </div>
        </div>
      )}

      <div className="conversation-list">
        {historySearchQuery.trim() ? (
          <div className="sidebar-search-results">
            <div className="sidebar-search-status">
              {historySearchLoading
                ? 'Searching...'
                : historySearchError || `${filteredSearchResults.length} result${filteredSearchResults.length === 1 ? '' : 's'} in current filters`}
            </div>
            {!historySearchLoading && filteredSearchResults.length === 0 && (
              <div className="no-conversations">No matching results</div>
            )}
            {groupedSearchResults.map((group) => {
              const activeInGroup = group.results.some((result) => result.flatIndex === activeSearchResultIndex);
              const isExpanded = expandedSearchGroups.has(group.conversationId) || activeInGroup;
              const visibleResults = isExpanded ? group.results : group.results.slice(0, 3);
              const hiddenCount = Math.max(0, group.results.length - visibleResults.length);

              return (
                <section className="sidebar-search-group" key={group.conversationId}>
                  <div className="sidebar-search-group-header">
                    <div className="sidebar-search-group-title">
                      <HighlightedText text={group.title} query={historySearchQuery} />
                    </div>
                    <div className="sidebar-search-group-meta">
                      <span>{group.results.length} hit{group.results.length === 1 ? '' : 's'}</span>
                      {group.updatedAt && <span>{formatSearchDate(group.updatedAt)}</span>}
                    </div>
                    {group.badges.length > 0 && (
                      <div className="sidebar-search-group-badges">
                        {group.badges.map((badge) => <span key={badge}>{badge}</span>)}
                      </div>
                    )}
                  </div>
                  {visibleResults.map((result) => {
                    const turnNumber = searchResultTurnNumber(result);
                    return (
                      <button
                        type="button"
                        className={`sidebar-search-result ${result.flatIndex === activeSearchResultIndex ? 'active' : ''}`}
                        key={searchResultKey(result, result.flatIndex)}
                        onMouseEnter={() => setActiveSearchResultIndex(result.flatIndex)}
                        onClick={() => openSearchResult(result)}
                      >
                        <span className="sidebar-search-result-meta">
                          {searchSourceLabel(result)}{turnNumber ? ` · Turn ${turnNumber}` : ''}
                        </span>
                        <span className="sidebar-search-result-excerpt">
                          <HighlightedText text={result.excerpt || result.content || 'Matched conversation'} query={historySearchQuery} />
                        </span>
                      </button>
                    );
                  })}
                  {hiddenCount > 0 && (
                    <button type="button" className="sidebar-search-more" onClick={() => toggleSearchGroup(group.conversationId)}>
                      Show {hiddenCount} more match{hiddenCount === 1 ? '' : 'es'}
                    </button>
                  )}
                  {isExpanded && group.results.length > 3 && !activeInGroup && (
                    <button type="button" className="sidebar-search-more" onClick={() => toggleSearchGroup(group.conversationId)}>
                      Collapse matches
                    </button>
                  )}
                </section>
              );
            })}
          </div>
        ) : visibleConversations.length === 0 ? (
          <div className="no-conversations">
            {viewMode === 'archived' ? 'No archived conversations' : 'No conversations yet'}
          </div>
        ) : (
          conversationGroups.map((group) => {
            const isActiveGroup = group.label === activeGroupLabel;
            const isCollapsed = !isActiveGroup && collapsedGroups.has(group.label);

            return (
              <section className={`conversation-group ${isCollapsed ? 'collapsed' : ''}`} key={group.label}>
                <button
                  type="button"
                  className="conversation-group-header"
                  onClick={() => toggleGroupCollapsed(group.label)}
                  aria-expanded={!isCollapsed}
                  disabled={isActiveGroup}
                  title={isActiveGroup ? 'Current conversation group stays expanded' : isCollapsed ? 'Expand group' : 'Collapse group'}
                >
                  <span className="conversation-group-title">
                    <span className="conversation-group-caret" aria-hidden="true">{isCollapsed ? '▸' : '▾'}</span>
                    {group.label}
                  </span>
                  <span className="conversation-group-count">{group.conversations.length}</span>
                </button>
                {!isCollapsed && group.conversations.map((conv) => (
                  <div
                    key={conv.id}
                    className={`conversation-item ${conv.id === currentConversationId ? 'active' : ''} ${conv.pinned ? 'pinned' : ''}`.trim()}
                    onClick={() => editingId === conv.id || tagEditingId === conv.id ? null : onSelectConversation(conv.id)}
                  >
                    {editingId === conv.id ? (
                      <div className="conversation-title-edit" onClick={(e) => e.stopPropagation()}>
                        <input
                          type="text"
                          value={editTitle}
                          onChange={(e) => setEditTitle(e.target.value)}
                          onKeyDown={(e) => handleKeyDown(e, conv.id)}
                          className="title-input"
                          autoFocus
                          maxLength={100}
                        />
                        <div className="title-edit-actions">
                          <button className="title-save-btn" onClick={() => handleSaveEdit(conv.id)} title="Save (Enter)">
                            ✓
                          </button>
                          <button className="title-cancel-btn" onClick={handleCancelEdit} title="Cancel (Esc)">
                            ✕
                          </button>
                        </div>
                      </div>
                    ) : tagEditingId === conv.id ? (
                      <div className="conversation-title-edit" onClick={(e) => e.stopPropagation()}>
                        <input
                          type="text"
                          value={tagInput}
                          onChange={(e) => setTagInput(e.target.value)}
                          onKeyDown={(e) => handleTagKeyDown(e, conv.id)}
                          className="title-input"
                          autoFocus
                          placeholder="tag-a, tag-b / 标签一，标签二"
                          maxLength={240}
                        />
                        <div className="title-edit-actions">
                          <button className="title-save-btn" onClick={() => handleSaveTags(conv.id)} title="Save tags">
                            ✓
                          </button>
                          <button className="title-cancel-btn" onClick={() => setTagEditingId(null)} title="Cancel">
                            ✕
                          </button>
                        </div>
                      </div>
                    ) : (
                      <>
                        <div className="conversation-card-layout">
                          <div className="conversation-title-row">
                            <label className="conversation-select" onClick={(e) => e.stopPropagation()}>
                              <input
                                type="checkbox"
                                checked={selectedConversationIds.has(conv.id)}
                                onChange={(e) => toggleConversationSelection(e, conv.id)}
                                aria-label={`Select ${conv.title || 'New Conversation'}`}
                              />
                            </label>
                            <div className="conversation-title" title={conv.title || 'New Conversation'}>
                              {conv.title || 'New Conversation'}
                            </div>
                          </div>
                          <div className="conversation-actions" aria-label="Conversation actions">
                            <button
                              className={`conversation-action-btn ${conv.favorite ? 'active' : ''}`}
                              onClick={(e) => handleMetadataClick(e, conv, { favorite: !conv.favorite })}
                              title={conv.favorite ? 'Remove favorite' : 'Favorite conversation'}
                            >
                              ★
                            </button>
                            <button
                              className={`conversation-action-btn ${conv.pinned ? 'active' : ''}`}
                              onClick={(e) => handleMetadataClick(e, conv, { pinned: !conv.pinned })}
                              title={conv.pinned ? 'Unpin conversation' : 'Pin conversation'}
                            >
                              ⬆
                            </button>
                            <button
                              className="title-edit-btn"
                              onClick={(e) => handleSuggestTitle(e, conv)}
                              title={titleSuggestionLoadingId === conv.id ? 'Generating title...' : 'Auto title with LLM'}
                              aria-label="Auto title with LLM"
                              disabled={titleSuggestionLoadingId === conv.id}
                            >
                              {titleSuggestionLoadingId === conv.id ? '...' : 'AI'}
                            </button>
                            <button
                              className="title-edit-btn"
                              onClick={(e) => {
                                e.stopPropagation();
                                onExportConversation?.(conv.id, 'markdown');
                              }}
                              title="Export markdown"
                            >
                              ⇩
                            </button>
                            <button
                              className="title-edit-btn"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleStartEdit(conv);
                              }}
                              title="Edit title"
                            >
                              ✎
                            </button>
                            <button
                              className="conversation-delete-btn"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleDeleteConversation(conv.id);
                              }}
                              title="Delete conversation"
                            >
                              ×
                            </button>
                            <button
                              type="button"
                              className="conversation-archive-btn"
                              onClick={(e) => handleMetadataClick(e, conv, { archived: !conv.archived })}
                            >
                              {conv.archived ? 'Restore' : 'Archive'}
                            </button>
                          </div>
                          <div className="conversation-meta-row">
                            <span className="conversation-meta">{formatTurnCount(conv)}</span>
                            <div className="conversation-tags">
                              {(conv.tags || []).map((tag) => (
                                <span
                                  className="conversation-tag-item"
                                  key={tag}
                                  style={{ '--tag-color': tagColorFor(tag) }}
                                >
                                  <button
                                    type="button"
                                    className="conversation-tag"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setTagFilter(tag);
                                    }}
                                    title={`Filter by ${tag}`}
                                  >
                                    {tag}
                                  </button>
                                  <button
                                    type="button"
                                    className="conversation-tag-remove"
                                    onClick={(e) => handleRemoveTag(e, conv, tag)}
                                    aria-label={`Remove tag ${tag} from ${conv.title || 'New Conversation'}`}
                                    title={`Remove ${tag}`}
                                  >
                                    ×
                                  </button>
                                </span>
                              ))}
                              <button
                                type="button"
                                className="conversation-tag add"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleStartTagEdit(conv);
                                }}
                                aria-label={`Edit tags for ${conv.title || 'New Conversation'}`}
                                title="Edit tags"
                              >
                                Tags
                              </button>
                            </div>
                          </div>
                        </div>
                        {titleSuggestions[conv.id]?.length > 0 && (
                          <div className="title-suggestions" onClick={(e) => e.stopPropagation()}>
                            {titleSuggestions[conv.id].map((title) => (
                              <button
                                type="button"
                                key={title}
                                onClick={(e) => handleUseTitleSuggestion(e, conv.id, title)}
                                title="Use title suggestion"
                              >
                                {title}
                              </button>
                            ))}
                          </div>
                        )}
                      </>
                    )}
                  </div>
                ))}
              </section>
            );
          })
        )}
      </div>
      <button
        type="button"
        className="sidebar-resize-handle"
        onPointerDown={handleResizePointerDown}
        aria-label="Resize sidebar"
        title="Drag to resize sidebar"
      />
    </div>
  );
}

