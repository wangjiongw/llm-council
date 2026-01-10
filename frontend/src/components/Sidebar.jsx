import { useState } from 'react';
import './Sidebar.css';

export default function Sidebar({
  conversations,
  currentConversationId,
  onSelectConversation,
  onNewConversation,
  onUpdateTitle,
}) {
  const [editingId, setEditingId] = useState(null);
  const [editTitle, setEditTitle] = useState('');

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

  return (
    <div className="sidebar">
      <div className="sidebar-header">
        <h1>LLM Council</h1>
        <button className="new-conversation-btn" onClick={onNewConversation}>
          + New Conversation
        </button>
      </div>

      <div className="conversation-list">
        {conversations.length === 0 ? (
          <div className="no-conversations">No conversations yet</div>
        ) : (
          conversations.map((conv) => (
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
                // Display mode with edit button
                <>
                  <div className="conversation-title-row">
                    <div className="conversation-title">
                      {conv.title || 'New Conversation'}
                    </div>
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
                  </div>
                  <div className="conversation-meta">
                    {conv.message_count} messages
                  </div>
                </>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
