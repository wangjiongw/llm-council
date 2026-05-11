import { useState, useEffect, useRef, useMemo, useCallback, memo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import Stage1 from './Stage1';
import Stage2 from './Stage2';
import Stage3 from './Stage3';
import ConversationContext from './ConversationContext';
import FileQueue from './FileQueue';
import UploadButton from './UploadButton';
import { formatFileSize } from '../utils/fileUtils';
import './ChatInterface.css';
import './FileQueue.css';

// Collapsible section component for Stage 1 and Stage 2
const CollapsibleStage = memo(function CollapsibleStage({
  title,
  icon,
  children,
  defaultCollapsed = true
}) {
  const [isCollapsed, setIsCollapsed] = useState(defaultCollapsed);

  return (
    <div className={`collapsible-stage ${isCollapsed ? 'collapsed' : 'expanded'}`}>
      <button
        className="collapsible-header"
        onClick={() => setIsCollapsed(!isCollapsed)}
        aria-expanded={!isCollapsed}
      >
        <span className="collapsible-icon">{isCollapsed ? '▶' : '▼'}</span>
        <span className="collapsible-title">{title}</span>
        <span className="collapsible-emoji">{icon}</span>
      </button>
      {!isCollapsed && (
        <div className="collapsible-content">
          {children}
        </div>
      )}
    </div>
  );
});

// Memoized message item to prevent re-renders when typing
const MessageItem = memo(function MessageItem({
  msg,
  turnNumber,
  hasPreviousTurns,
  conversationContext,
  isLoading,
  onRetryQuery,
  onEditMessage,
  isLastMessage,
}) {
  const isUserMessage = msg.role === 'user';

  return (
    <div className="message-group">
      {/* Turn indicator for user messages */}
      {isUserMessage && hasPreviousTurns && (
        <div className="turn-indicator">
          <span className="turn-number">Turn {turnNumber}</span>
          <span className="turn-continuation">
            {turnNumber === 1 ? 'Starting conversation' : 'Continuing conversation'}
          </span>
        </div>
      )}

      {isUserMessage ? (
        <div className="user-message">
          <div className="message-label">
            <span className="role-icon">👤</span>
            <span>You</span>
            {hasPreviousTurns && <span className="turn-badge">{turnNumber}</span>}
          </div>
          <div className="message-content">
            {msg.files && msg.files.length > 0 && (
              <div className="message-files-metadata">
                {msg.files.map((file, idx) => (
                  <div key={idx} className="file-metadata">
                    <span className="file-icon">
                      {file.category === 'image' ? '📸' : '📄'}
                    </span>
                    <span className="file-name" title={file.name}>{file.name}</span>
                    <span className="file-size">{formatFileSize(file.size)}</span>
                  </div>
                ))}
              </div>
            )}
            <div className="markdown-content">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
            </div>
          </div>
          {!isLoading && (
            <div className="message-actions">
              <button
                type="button"
                className="edit-message-button"
                onClick={() => onEditMessage(msg)}
                title="Edit this message in the input box"
                aria-label="Edit this message"
              >
                ✏️ Edit
              </button>
            </div>
          )}
        </div>
      ) : (
        <div className="assistant-message">
          <div className="message-label">
            <span className="role-icon">🤖</span>
            <span>LLM Council</span>
            {hasPreviousTurns && <span className="turn-badge">{turnNumber}</span>}
            {hasPreviousTurns && (
              <span className="context-indicator">
                {turnNumber === 1 ? 'First response' : 'Context-aware response'}
              </span>
            )}
          </div>

          {/* Enhanced loading states with context awareness */}
          {msg.loading?.stage1 && (
            <div className="stage-loading">
              <div className="spinner"></div>
              <span>
                {hasPreviousTurns
                  ? `Running Stage 1 with ${conversationContext.turnCount} previous turns of context...`
                  : 'Running Stage 1: Collecting individual responses...'
                }
              </span>
            </div>
          )}
          {msg.stage1 && (
            <CollapsibleStage title="Stage 1: Individual Responses" icon="💬" defaultCollapsed={true}>
              <Stage1 responses={msg.stage1} />
            </CollapsibleStage>
          )}

          {msg.loading?.stage2 && (
            <div className="stage-loading">
              <div className="spinner"></div>
              <span>
                {hasPreviousTurns
                  ? 'Running Stage 2: Peer rankings with conversation context...'
                  : 'Running Stage 2: Peer rankings...'
                }
              </span>
            </div>
          )}
          {msg.stage2 && (
            <CollapsibleStage title="Stage 2: Peer Rankings" icon="🗳️" defaultCollapsed={true}>
              <Stage2
                rankings={msg.stage2}
                labelToModel={msg.metadata?.label_to_model}
                aggregateRankings={msg.metadata?.aggregate_rankings}
                hasContext={hasPreviousTurns}
              />
            </CollapsibleStage>
          )}

          {msg.loading?.stage3 && (
            <div className="stage-loading">
              <div className="spinner"></div>
              <span>
                {hasPreviousTurns
                  ? 'Running Stage 3: Final synthesis with full conversation context...'
                  : 'Running Stage 3: Final synthesis...'
                }
              </span>
            </div>
          )}
          {msg.stage3 && <Stage3 finalResponse={msg.stage3} hasContext={hasPreviousTurns} />}

          {/* Retry button for completed assistant messages */}
          {msg.stage3 && !isLoading && isLastMessage && (
            <div className="message-actions">
              <button
                className="retry-button"
                onClick={onRetryQuery}
                title="Retry this query for a different response"
                aria-label="Retry this query"
              >
                🔄 Retry
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
});

export default function ChatInterface({
  conversation,
  onSendMessage,
  onSendQuickMessage,
  onStopQuery,
  onRetryQuery,
  isLoading,
  activeStreamId,
  attachedFiles,
  onFilesChange,
  onFileUpload,
  onDeleteFile,
}) {
  const [input, setInput] = useState('');
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);

  const messageContentToText = useCallback((content) => {
    if (typeof content === 'string') {
      return content;
    }
    if (Array.isArray(content)) {
      return content
        .filter(item => item?.type === 'text')
        .map(item => item.text || '')
        .join('\n')
        .trim();
    }
    return '';
  }, []);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [conversation]);

  // Memoize context calculation to avoid re-computing on every render
  const conversationContext = useMemo(() => {
    if (!conversation || conversation.messages.length === 0) {
      return null;
    }

    // Get completed turns (user + assistant pairs)
    // Uses sequential matching to handle irregular message patterns
    const turns = [];
    let i = 0;

    while (i < conversation.messages.length) {
      const msg = conversation.messages[i];

      // If this is a user message, look for its assistant response
      if (msg.role === 'user') {
        // Search forward for the next assistant message with stage3
        let j = i + 1;
        while (j < conversation.messages.length) {
          const nextMsg = conversation.messages[j];

          if (nextMsg.role === 'assistant' && nextMsg.stage3) {
            // Found a matching pair!
            turns.push({
              user: msg,
              assistant: nextMsg
            });
            i = j + 1;  // Continue after this assistant message
            break;
          } else if (nextMsg.role === 'user') {
            // Found another user message before a response
            // Skip the unmatched user message and continue from here
            i = j;
            break;
          } else {
            // Assistant message without stage3, keep looking
            j++;
          }
        }

        if (j >= conversation.messages.length) {
          // Reached end without finding assistant response
          break;
        }
      } else {
        // Skip non-user messages (shouldn't happen, but safety check)
        i++;
      }
    }

    // Get recent messages for context display
    const recentMessages = turns.slice(-3).flatMap(turn => [
      turn.user,
      {
        role: 'assistant',
        content: turn.assistant.stage3?.response || 'Processing response...'
      }
    ]);

    // Check if there's a currently loading message
    const lastMessage = conversation.messages[conversation.messages.length - 1];
    const isInProgress = lastMessage?.role === 'assistant' &&
                        (!lastMessage.stage3 || lastMessage.loading?.stage3);

    return {
      recentMessages,
      totalMessages: conversation.messages.length,
      turnCount: turns.length,
      isInProgress
    };
  }, [conversation]);

  const hasPreviousTurns = conversationContext && conversationContext.turnCount > 0;

  const adjustInputHeight = useCallback(() => {
    const textarea = inputRef.current;
    if (!textarea) return;

    const maxHeight = 300;
    textarea.style.height = 'auto';
    const nextHeight = Math.min(textarea.scrollHeight, maxHeight);
    textarea.style.height = `${nextHeight}px`;
    textarea.style.overflowY = textarea.scrollHeight > maxHeight ? 'auto' : 'hidden';
  }, []);

  useEffect(() => {
    adjustInputHeight();
  }, [input, adjustInputHeight]);

  // File handling functions
  const handleFileUploadLocal = useCallback(async (newFiles) => {
    await onFileUpload(newFiles);
  }, [onFileUpload]);

  const handleFileDeleteLocal = useCallback((fileId) => {
    onDeleteFile(fileId);
  }, [onDeleteFile]);

  const handleDragOver = useCallback((e) => {
    e.preventDefault();
    if (!isLoading) {
      e.dataTransfer.dropEffect = 'copy';
    }
  }, [isLoading]);

  const handleDrop = useCallback(async (e) => {
    e.preventDefault();
    if (!isLoading) {
      const files = Array.from(e.dataTransfer.files);
      if (files.length > 0) {
        await handleFileUploadLocal(files);
      }
    }
  }, [isLoading, handleFileUploadLocal]);

  const handlePaste = useCallback(async (e) => {
    if (!isLoading) {
      const items = e.clipboardData.items;
      const imageFiles = [];

      for (let i = 0; i < items.length; i++) {
        const item = items[i];
        if (item.type.startsWith('image/')) {
          const file = item.getAsFile();
          if (file) {
            imageFiles.push(file);
          }
        }
      }

      if (imageFiles.length > 0) {
        await handleFileUploadLocal(imageFiles);
      }
    }
  }, [isLoading, handleFileUploadLocal]);

  const handleSubmit = useCallback((e) => {
    e.preventDefault();
    if ((input.trim() || attachedFiles.length > 0) && !isLoading) {
      onSendMessage(input, attachedFiles);
      setInput('');
      // Note: Not clearing attachedFiles - they persist for next message
    }
  }, [input, attachedFiles, isLoading, onSendMessage]);

  const handleQuickSubmit = useCallback((e) => {
    e.preventDefault();
    if ((input.trim() || attachedFiles.length > 0) && !isLoading && onSendQuickMessage) {
      onSendQuickMessage(input, attachedFiles);
      setInput('');
      // Note: Not clearing attachedFiles - they persist for next message
    }
  }, [input, attachedFiles, isLoading, onSendQuickMessage]);

  const handleEditMessage = useCallback((msg) => {
    const text = messageContentToText(msg.content);
    setInput(text);
    window.requestAnimationFrame(() => {
      inputRef.current?.focus();
      adjustInputHeight();
    });
  }, [adjustInputHeight, messageContentToText]);

  const handleKeyDown = useCallback((e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      handleQuickSubmit(e);
      return;
    }

    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  }, [handleQuickSubmit, handleSubmit]);

  useEffect(() => {
    if (!isLoading || !onStopQuery) return undefined;

    const handleGlobalKeyDown = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'c') {
        e.preventDefault();
        onStopQuery();
      }
    };

    window.addEventListener('keydown', handleGlobalKeyDown);
    return () => window.removeEventListener('keydown', handleGlobalKeyDown);
  }, [isLoading, onStopQuery]);

  if (!conversation) {
    return (
      <div className="chat-interface">
        <div className="empty-state">
          <h2>Welcome to LLM Council</h2>
          <p>Create a new conversation to get started</p>
        </div>
      </div>
    );
  }

  return (
    <div className="chat-interface">
      <div className="messages-container">
        {conversation.messages.length === 0 ? (
          <div className="empty-state">
            <h2>Start a conversation</h2>
            <p>Ask a question to consult the LLM Council</p>
          </div>
        ) : (
          <>
            {/* Show conversation context for multi-turn conversations */}
            {hasPreviousTurns && (
              <div className="conversation-section">
                <ConversationContext
                  recentMessages={conversationContext.recentMessages}
                  totalMessages={conversationContext.totalMessages}
                  isInProgress={conversationContext.isInProgress}
                />
              </div>
            )}

            {/* Display all messages with turn indicators */}
            <div className="messages-history">
              {conversation.messages.map((msg, index) => (
                <MessageItem
                  key={index}
                  msg={msg}
                  turnNumber={Math.floor(index / 2) + 1}
                  hasPreviousTurns={hasPreviousTurns}
                  conversationContext={conversationContext}
                  isLoading={isLoading}
                  onRetryQuery={onRetryQuery}
                  onEditMessage={handleEditMessage}
                  isLastMessage={index === conversation.messages.length - 1}
                />
              ))}
            </div>
          </>
        )}

        {isLoading && (
          <div className="loading-indicator">
            <div className="spinner"></div>
            <span>
              {hasPreviousTurns
                ? 'Consulting the council with conversation context...'
                : 'Consulting the council...'
              }
            </span>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Enhanced input form with context hints */}
      <div className="input-section">
        {hasPreviousTurns && !isLoading && (
          <div className="input-context-hint">
            <span className="hint-icon">💭</span>
            <span className="hint-text">
              Your next message will include {conversationContext.turnCount} previous turns of context
            </span>
          </div>
        )}

        <form className="input-form" onSubmit={handleSubmit}>
          <div className="input-wrapper">
            <div className="input-main">
              <textarea
                ref={inputRef}
                className="message-input"
                placeholder={
                  isLoading
                    ? "Query in progress... (Ctrl+C to stop)"
                    : hasPreviousTurns
                      ? "Continue... (Enter Council, Ctrl+Enter Quick, Shift+Enter newline)"
                      : "Ask... (Enter Council, Ctrl+Enter Quick, Shift+Enter newline)"
                }
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                onPaste={handlePaste}
                disabled={isLoading}
                rows={3}
              />

              <FileQueue
                files={attachedFiles}
                onFilesChange={onFilesChange}
                onDragOver={handleDragOver}
                onDrop={handleDrop}
                disabled={isLoading}
                onDeleteFile={handleFileDeleteLocal}
              />
            </div>

            {isLoading && activeStreamId ? (
              <button
                type="button"
                className="stop-button"
                onClick={onStopQuery}
                title="Stop current query"
                aria-label="Stop current query"
              >
                ⏹️ Stop
              </button>
            ) : (
              <div className="button-group">
                {/* Upload Button */}
                <UploadButton
                  onUpload={handleFileUploadLocal}
                  disabled={isLoading}
                />

                {/* Action Buttons */}
                <button
                  type="button"
                  className="quick-button"
                  onClick={handleQuickSubmit}
                  disabled={(!input.trim() && attachedFiles.length === 0) || isLoading}
                  title="Quick single-model response"
                  aria-label="Quick query"
                >
                  ⚡ Quick
                </button>
                <button
                  type="submit"
                  className="send-button"
                  disabled={(!input.trim() && attachedFiles.length === 0) || isLoading}
                  title="Full 3-stage council response"
                  aria-label="Send to council"
                >
                  🏛️ Council
                </button>
              </div>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}
