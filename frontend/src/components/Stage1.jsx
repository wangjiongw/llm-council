import { useState, memo } from 'react';
import RichMarkdown from './RichMarkdown';
import './Stage1.css';

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
      title="Copy response"
      aria-label="Copy response"
    >
      {copied ? '✓' : '📋'}
    </button>
  );
};

function Stage1({ responses }) {
  const [activeTab, setActiveTab] = useState(0);

  if (!responses || responses.length === 0) {
    return null;
  }

  const activeResponse = responses[activeTab];
  const isFailed = activeResponse.status === 'failed';
  const failureDetails = [
    activeResponse.error_type && `Type: ${activeResponse.error_type}`,
    activeResponse.error && `Error: ${activeResponse.error}`,
    activeResponse.duration_seconds != null && `Duration: ${activeResponse.duration_seconds}s`,
    activeResponse.timeout_seconds != null && `Timeout: ${activeResponse.timeout_seconds}s`,
    activeResponse.status_code != null && `HTTP status: ${activeResponse.status_code}`,
  ].filter(Boolean).join('\n');

  return (
    <div className="stage stage1">
      <h3 className="stage-title">Stage 1: Individual Responses</h3>

      <div className="tabs">
        {responses.map((resp, index) => (
          <button
            key={index}
            className={`tab ${activeTab === index ? 'active' : ''} ${resp.status === 'failed' ? 'failed' : ''}`}
            onClick={() => setActiveTab(index)}
          >
            {resp.model.split('/')[1] || resp.model}
            {resp.status === 'failed' ? ' · failed' : ''}
          </button>
        ))}
      </div>

      <div className="tab-content">
        <div className="response-header">
          <div className="model-name">
            {activeResponse.model}
            {isFailed && <span className="status-failed">failed</span>}
          </div>
          {!isFailed && (
            <CopyButton
              content={activeResponse.response}
              onCopy={() => console.log(`Copied response from ${activeResponse.model}`)}
            />
          )}
        </div>
        {isFailed ? (
          <pre className="failure-details">{failureDetails}</pre>
        ) : (
          <RichMarkdown content={activeResponse.response} className="response-text" />
        )}
      </div>
    </div>
  );
}

export default memo(Stage1);
