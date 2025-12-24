import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './ConversationContext.css';

export default function ConversationContext({
  recentMessages,
  contextSummary,
  totalMessages,
  isInProgress = false
}) {
  if (!recentMessages && !contextSummary) {
    return null;
  }

  const shouldShowSummary = contextSummary && recentMessages && recentMessages.length >= 6;

  return (
    <div className="conversation-context">
      <div className="context-header">
        <span className="context-icon">💬</span>
        <span className="context-title">
          {isInProgress ? 'Processing with context' : 'Conversation Context'}
        </span>
        <span className="context-badge">
          {totalMessages} {totalMessages === 1 ? 'message' : 'messages'}
        </span>
      </div>

      <div className="context-content">
        {shouldShowSummary && (
          <div className="context-summary">
            <div className="summary-label">Previous conversation summary:</div>
            <div className="summary-content">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{contextSummary}</ReactMarkdown>
            </div>
          </div>
        )}

        {recentMessages && recentMessages.length > 0 && (
          <div className="recent-context">
            {!shouldShowSummary && (
              <div className="context-label">Recent conversation:</div>
            )}
            <div className="recent-messages">
              {recentMessages.slice(-4).map((msg, index) => (
                <div key={index} className={`context-message ${msg.role}`}>
                  <div className="context-message-role">
                    {msg.role === 'user' ? '👤 You' : '🤖 LLM Council'}
                  </div>
                  <div className="context-message-content">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {isInProgress && (
          <div className="context-processing">
            <div className="context-processing-text">
              <span className="processing-spinner"></span>
              Including this context in council deliberation...
            </div>
          </div>
        )}
      </div>
    </div>
  );
}