import { useState, useEffect, useRef, useMemo, useCallback, memo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import Stage1 from './Stage1';
import Stage2 from './Stage2';
import Stage3 from './Stage3';
import ConversationContext from './ConversationContext';
import './ChatInterface.css';

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
            <div className="markdown-content">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
            </div>
          </div>
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
}) {
  const [input, setInput] = useState('');
  const messagesEndRef = useRef(null);

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
    const turns = [];
    for (let i = 0; i < conversation.messages.length - 1; i += 2) {
      if (conversation.messages[i].role === 'user' &&
          i + 1 < conversation.messages.length &&
          conversation.messages[i + 1].role === 'assistant' &&
          conversation.messages[i + 1].stage3) {
        turns.push({
          user: conversation.messages[i],
          assistant: conversation.messages[i + 1]
        });
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

  const handleSubmit = useCallback((e) => {
    e.preventDefault();
    if (input.trim() && !isLoading) {
      onSendMessage(input);
      setInput('');
    }
  }, [input, isLoading, onSendMessage]);

  const handleQuickSubmit = useCallback((e) => {
    e.preventDefault();
    if (input.trim() && !isLoading && onSendQuickMessage) {
      onSendQuickMessage(input);
      setInput('');
    }
  }, [input, isLoading, onSendQuickMessage]);

  const handleKeyDown = useCallback((e) => {
    // Submit on Enter (without Shift)
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  }, [handleSubmit]);

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
            <textarea
              className="message-input"
              placeholder={
                isLoading
                  ? "Query in progress... (Use stop button to interrupt)"
                  : hasPreviousTurns
                    ? "Continue the conversation... (Shift+Enter for new line, Enter to send)"
                    : "Ask your question... (Shift+Enter for new line, Enter to send)"
              }
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={isLoading}
              rows={3}
            />
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
                <button
                  type="button"
                  className="quick-button"
                  onClick={handleQuickSubmit}
                  disabled={!input.trim() || isLoading}
                  title="Quick single-model response"
                  aria-label="Quick query"
                >
                  ⚡ Quick
                </button>
                <button
                  type="submit"
                  className="send-button"
                  disabled={!input.trim() || isLoading}
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
