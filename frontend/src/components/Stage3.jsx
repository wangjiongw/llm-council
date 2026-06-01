import { useState, memo } from 'react';
import RichMarkdown from './RichMarkdown';
import './Stage3.css';

const CopyButton = ({ content, onCopy }) => {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
      onCopy?.();
    } catch (err) {
      console.error('Failed to copy:', err);
      // Fallback for browsers that don't support clipboard API
      const textArea = document.createElement('textarea');
      textArea.value = content;
      document.body.appendChild(textArea);
      textArea.select();
      try {
        document.execCommand('copy');
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
        onCopy?.();
      } catch (fallbackErr) {
        console.error('Fallback copy failed:', fallbackErr);
      }
      document.body.removeChild(textArea);
    }
  };

  return (
    <button
      className={`copy-button ${copied ? 'copied' : ''}`}
      onClick={handleCopy}
      title="Copy final answer"
      aria-label="Copy final answer"
    >
      {copied ? '✓' : '📋'}
    </button>
  );
};

function Stage3({ finalResponse, hasContext = false }) {
  if (!finalResponse) {
    return null;
  }

  return (
    <div className="stage stage3">
      <h3 className="stage-title">
        Stage 3: Final Council Answer
        {hasContext && (
          <span className="context-badge">
            Context-aware
          </span>
        )}
      </h3>
      <div className="final-response">
        <div className="final-header">
          <div className="chairman-label">
            Chairman: {finalResponse.model.split('/')[1] || finalResponse.model}
            {hasContext && (
              <span className="context-indicator-small">
                with conversation context
              </span>
            )}
          </div>
          <CopyButton
            content={finalResponse.response}
            onCopy={() => console.log(`Copied final answer from ${finalResponse.model}`)}
          />
        </div>
        <RichMarkdown content={finalResponse.response} className="final-text" />
      </div>
    </div>
  );
}

export default memo(Stage3);
