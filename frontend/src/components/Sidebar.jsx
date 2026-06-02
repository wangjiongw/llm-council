import { useMemo, useState } from 'react';
import './Sidebar.css';

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

const groupConversations = (conversations) => {
  const groups = [];
  const groupMap = new Map();

  conversations.forEach((conversation) => {
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

export default function Sidebar({
  conversations,
  currentConversationId,
  onSelectConversation,
  onNewConversation,
  onUpdateTitle,
  onDeleteConversation,
  onOpenSettings,
  theme,
  onToggleTheme,
}) {
  const [editingId, setEditingId] = useState(null);
  const [editTitle, setEditTitle] = useState('');
  const [collapsedGroups, setCollapsedGroups] = useState(() => new Set());
  const conversationGroups = useMemo(() => groupConversations(conversations), [conversations]);
  const activeGroupLabel = useMemo(() => {
    const activeGroup = conversationGroups.find((group) =>
      group.conversations.some((conversation) => conversation.id === currentConversationId)
    );
    return activeGroup?.label || '';
  }, [conversationGroups, currentConversationId]);

  const handleStartEdit = (conv) => {
    setEditingId(conv.id);
    setEditTitle(conv.title || 'New Conversation');
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

  const handleDeleteConversation = (conversationId) => {
    onDeleteConversation(conversationId);
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

  return (
    <div className="sidebar">
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
      </div>

      <div className="conversation-list">
        {conversations.length === 0 ? (
          <div className="no-conversations">No conversations yet</div>
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
                  className={`conversation-item ${
                    conv.id === currentConversationId ? 'active' : ''
                  }`}
                  onClick={() => editingId === conv.id ? null : onSelectConversation(conv.id)}
                >
                  {editingId === conv.id ? (
                    // Inline edit form
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
                        <button
                          className="title-save-btn"
                          onClick={() => handleSaveEdit(conv.id)}
                          title="Save (Enter)"
                        >
                          ✓
                        </button>
                        <button
                          className="title-cancel-btn"
                          onClick={handleCancelEdit}
                          title="Cancel (Esc)"
                        >
                          ✕
                        </button>
                      </div>
                    </div>
                  ) : (
                    // Display mode with action buttons
                    <>
                      <div className="conversation-title-row">
                        <div className="conversation-title">
                          {conv.title || 'New Conversation'}
                        </div>
                        <div className="conversation-actions">
                          <button
                            className="title-edit-btn"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleStartEdit(conv);
                            }}
                            title="Edit title"
                          >
                            ✏️
                          </button>
                          <button
                            className="conversation-delete-btn"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleDeleteConversation(conv.id);
                            }}
                            title="Delete conversation"
                          >
                            🗑️
                          </button>
                        </div>
                      </div>
                      <div className="conversation-meta">
                        {conv.message_count} messages
                      </div>
                    </>
                  )}
                </div>
                ))}
              </section>
            );
          })
        )}
      </div>
    </div>
  );
}
