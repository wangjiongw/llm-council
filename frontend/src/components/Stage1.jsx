import { useState, memo } from 'react';
import CopyButton from './CopyButton';
import RichMarkdown from './RichMarkdown';
import './Stage1.css';

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
              title="Copy response"
              ariaLabel="Copy response"
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
