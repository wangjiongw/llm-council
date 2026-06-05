import { useEffect, useRef, useState } from 'react';
import './CopyButton.css';

export default function CopyButton({ content, title = 'Copy content', ariaLabel = title }) {
  const [copied, setCopied] = useState(false);
  const resetTimerRef = useRef(null);

  useEffect(() => () => {
    if (resetTimerRef.current) {
      window.clearTimeout(resetTimerRef.current);
    }
  }, []);

  const markCopied = () => {
    if (resetTimerRef.current) {
      window.clearTimeout(resetTimerRef.current);
    }
    setCopied(true);
    resetTimerRef.current = window.setTimeout(() => {
      setCopied(false);
      resetTimerRef.current = null;
    }, 2000);
  };

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(content || '');
      markCopied();
    } catch (err) {
      console.error('Failed to copy:', err);
      const textArea = document.createElement('textarea');
      textArea.value = content || '';
      document.body.appendChild(textArea);
      textArea.select();
      try {
        document.execCommand('copy');
        markCopied();
      } catch (fallbackErr) {
        console.error('Fallback copy failed:', fallbackErr);
      } finally {
        document.body.removeChild(textArea);
      }
    }
  };

  return (
    <button
      className={`copy-button ${copied ? 'copied' : ''}`}
      onClick={handleCopy}
      title={title}
      aria-label={ariaLabel}
    >
      {copied ? '✓' : '📋'}
    </button>
  );
}
