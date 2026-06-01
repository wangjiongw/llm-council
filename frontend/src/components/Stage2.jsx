import { useState, memo } from 'react';
import RichMarkdown from './RichMarkdown';
import './Stage2.css';

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
      title="Copy content"
      aria-label="Copy content"
    >
      {copied ? '✓' : '📋'}
    </button>
  );
};

function deAnonymizeText(text, labelToModel) {
  if (!labelToModel) return text;

  let result = text;
  // Replace each "Response X" with the actual model name
  Object.entries(labelToModel).forEach(([label, model]) => {
    const modelShortName = model.split('/')[1] || model;
    result = result.replace(new RegExp(label, 'g'), `**${modelShortName}**`);
  });
  return result;
}

function Stage2({ rankings, labelToModel, aggregateRankings, hasContext = false }) {
  const [activeTab, setActiveTab] = useState(0);

  if (!rankings || rankings.length === 0) {
    return null;
  }

  const activeRanking = rankings[activeTab];
  const isFailed = activeRanking.status === 'failed';
  const failureDetails = [
    activeRanking.error_type && `Type: ${activeRanking.error_type}`,
    activeRanking.error && `Error: ${activeRanking.error}`,
    activeRanking.duration_seconds != null && `Duration: ${activeRanking.duration_seconds}s`,
    activeRanking.timeout_seconds != null && `Timeout: ${activeRanking.timeout_seconds}s`,
    activeRanking.status_code != null && `HTTP status: ${activeRanking.status_code}`,
  ].filter(Boolean).join('\n');

  return (
    <div className="stage stage2">
      <h3 className="stage-title">
        Stage 2: Peer Rankings
        {hasContext && (
          <span className="context-badge">
            Context-aware
          </span>
        )}
      </h3>

      <h4>Raw Evaluations</h4>
      <p className="stage-description">
        Each model evaluated all responses{hasContext ? ' with conversation context' : ' (anonymized as Response A, B, C, etc.)'} and provided rankings.
        Below, model names are shown in <strong>bold</strong> for readability, but the original evaluation used anonymous labels.
      </p>

      <div className="tabs">
        {rankings.map((rank, index) => (
          <button
            key={index}
            className={`tab ${activeTab === index ? 'active' : ''} ${rank.status === 'failed' ? 'failed' : ''}`}
            onClick={() => setActiveTab(index)}
          >
            {rank.model.split('/')[1] || rank.model}
            {rank.status === 'failed' ? ' · failed' : ''}
          </button>
        ))}
      </div>

      <div className="tab-content">
        <div className="ranking-header">
          <div className="ranking-model">
            {activeRanking.model}
            {isFailed && <span className="status-failed">failed</span>}
          </div>
          {!isFailed && (
            <CopyButton
              content={deAnonymizeText(activeRanking.ranking, labelToModel)}
              onCopy={() => console.log(`Copied evaluation from ${activeRanking.model}`)}
            />
          )}
        </div>
        {isFailed ? (
          <pre className="failure-details">{failureDetails}</pre>
        ) : (
          <>
            <RichMarkdown
              content={deAnonymizeText(activeRanking.ranking, labelToModel)}
              className="ranking-content"
            />

            {activeRanking.parsed_ranking &&
             activeRanking.parsed_ranking.length > 0 && (
              <div className="parsed-ranking">
                <strong>Extracted Ranking:</strong>
                <ol>
                  {activeRanking.parsed_ranking.map((label, i) => (
                    <li key={i}>
                      {labelToModel && labelToModel[label]
                        ? labelToModel[label].split('/')[1] || labelToModel[label]
                        : label}
                    </li>
                  ))}
                </ol>
              </div>
            )}
          </>
        )}
      </div>

      {aggregateRankings && aggregateRankings.length > 0 && (
        <div className="aggregate-rankings">
          <h4>Aggregate Rankings (Street Cred)</h4>
          <p className="stage-description">
            Combined results across all peer evaluations (lower score is better):
          </p>
          <div className="aggregate-list">
            {aggregateRankings.map((agg, index) => (
              <div key={index} className="aggregate-item">
                <span className="rank-position">#{index + 1}</span>
                <span className="rank-model">
                  {agg.model.split('/')[1] || agg.model}
                </span>
                <span className="rank-score">
                  Avg: {agg.average_rank.toFixed(2)}
                </span>
                <span className="rank-count">
                  ({agg.rankings_count} votes)
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default memo(Stage2);
