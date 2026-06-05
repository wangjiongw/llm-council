import { useEffect, useMemo, useRef, useState, memo } from 'react';
import RichMarkdown from './RichMarkdown';
import './Stage3.css';

const LONG_ANSWER_CHARS = 3600;
const LONG_ANSWER_LINES = 72;

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

const extractHeadings = (content) => {
  const headings = [];
  let inCodeFence = false;

  String(content || '').split('\n').forEach((line) => {
    if (/^\s*```/.test(line)) {
      inCodeFence = !inCodeFence;
      return;
    }
    if (inCodeFence) return;

    const match = /^(#{1,4})\s+(.+?)\s*#*\s*$/.exec(line.trim());
    if (!match) return;

    headings.push({
      level: match[1].length,
      text: match[2].replace(/[*_`~]/g, '').trim(),
    });
  });

  return headings.slice(0, 12);
};

function Stage3({ finalResponse, hasContext = false, defaultCollapsed = false }) {
  const contentRef = useRef(null);
  const response = finalResponse?.response || '';
  const headings = useMemo(() => extractHeadings(response), [response]);
  const isLongAnswer = response.length > LONG_ANSWER_CHARS || response.split('\n').length > LONG_ANSWER_LINES;
  const [isManuallyOpen, setIsManuallyOpen] = useState(!defaultCollapsed);
  const isHistoryPreviewCollapsed = defaultCollapsed && !isManuallyOpen;
  const isLongPreviewCollapsed = !defaultCollapsed && isLongAnswer && !isManuallyOpen;
  const isPreviewCollapsed = isHistoryPreviewCollapsed || isLongPreviewCollapsed;
  const isExpanded = !isPreviewCollapsed;

  useEffect(() => {
    setIsManuallyOpen(!defaultCollapsed);
  }, [defaultCollapsed, response]);

  if (!finalResponse) {
    return null;
  }

  const jumpToHeading = (headingIndex) => {
    setIsManuallyOpen(true);
    window.requestAnimationFrame(() => {
      const nodes = contentRef.current?.querySelectorAll('h1, h2, h3, h4') || [];
      nodes[headingIndex]?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  };

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
            content={response}
            onCopy={() => console.log(`Copied final answer from ${finalResponse.model}`)}
          />
        </div>

        {(headings.length > 1 || isLongAnswer || defaultCollapsed) && (
          <div className="answer-navigation">
            {headings.length > 1 && isExpanded && (
              <div className="answer-outline" aria-label="Answer outline">
                <span>Outline</span>
                {headings.map((heading, index) => (
                  <button
                    type="button"
                    key={`${heading.level}-${heading.text}-${index}`}
                    className={`answer-outline-item level-${heading.level}`}
                    onClick={() => jumpToHeading(index)}
                    title={heading.text}
                  >
                    {heading.text}
                  </button>
                ))}
              </div>
            )}
            {(isLongAnswer || defaultCollapsed) && (
              <button
                type="button"
                className="answer-collapse-toggle"
                onClick={() => setIsManuallyOpen((open) => !open)}
              >
                {isExpanded ? 'Collapse answer' : 'Show full answer'}
              </button>
            )}
          </div>
        )}

        <div
          className={`final-text-shell ${isPreviewCollapsed ? 'collapsed' : ''} ${isHistoryPreviewCollapsed ? 'history-preview' : ''}`}
          ref={contentRef}
        >
          <RichMarkdown content={response} className="final-text" />
        </div>
        {isPreviewCollapsed && <div className="final-text-fade" aria-hidden="true" />}
      </div>
    </div>
  );
}

export default memo(Stage3);
