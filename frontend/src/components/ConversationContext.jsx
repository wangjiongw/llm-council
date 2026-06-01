import React, { useEffect, useState } from 'react';
import RichMarkdown from './RichMarkdown';
import './ConversationContext.css';

function ContextStat({ label, value }) {
  return (
    <div className="context-stat">
      <span className="context-stat-label">{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function formatTokenCount(value) {
  return `${Math.max(0, Math.round(Number(value) || 0)).toLocaleString()} tokens`;
}

function ContextBudgetBreakdown({ snapshot }) {
  const breakdown = snapshot?.budget_breakdown;
  if (!breakdown) return null;

  const budget = Math.max(1, Number(breakdown.budget_tokens) || Number(snapshot?.budget_tokens) || 1);
  const items = [
    { key: 'summary', label: 'Summary', tokens: breakdown.summary_tokens || 0 },
    { key: 'pinned', label: 'Pinned', tokens: breakdown.pinned_tokens || 0 },
    { key: 'memory', label: 'Memory', tokens: breakdown.memory_tokens || 0 },
    { key: 'recent', label: 'Recent history', tokens: breakdown.recent_history_tokens || 0 },
    { key: 'current', label: 'Current turn', tokens: breakdown.current_turn_tokens || 0 },
  ].filter(item => item.tokens > 0 || item.key !== 'current');

  return (
    <div className="context-budget-breakdown" aria-label="Context budget breakdown">
      <div className="context-budget-head">
        <span>Budget breakdown</span>
        <strong>{formatTokenCount(breakdown.history_context_tokens)} / {formatTokenCount(budget)}</strong>
      </div>
      <div className="context-budget-bars">
        {items.map(item => {
          const width = Math.min(100, Math.max(2, (item.tokens / budget) * 100));
          return (
            <div className="context-budget-row" key={item.key}>
              <div className="context-budget-label">
                <span>{item.label}</span>
                <strong>{formatTokenCount(item.tokens)}</strong>
              </div>
              <div className="context-budget-track">
                <span className={`context-budget-fill ${item.key}`} style={{ width: `${width}%` }} />
              </div>
            </div>
          );
        })}
      </div>
      <div className="context-budget-foot">
        <span>Remaining history budget: {formatTokenCount(breakdown.remaining_context_tokens)}</span>
        <span>Estimated request: {formatTokenCount(breakdown.estimated_request_tokens)}</span>
      </div>
    </div>
  );
}

function previewText(content) {
  if (typeof content === 'string') {
    return content.length > 1200 ? `${content.slice(0, 1200)}\n\n[Preview truncated]` : content;
  }
  return JSON.stringify(content, null, 2).slice(0, 1200);
}

function ContextPreviewPanel({ preview, onJumpToMessage }) {
  if (!preview?.snapshot) return null;

  const snapshot = preview.snapshot;
  const messages = preview.messages || [];
  const currentTurn = snapshot.current_turn || {};
  const fileContexts = currentTurn.file_contexts || [];

  return (
    <details className="context-preview-panel" open>
      <summary>
        <span>Next {preview.mode || snapshot.mode || 'model'} context</span>
        <span>{snapshot.included_history_messages || 0} history</span>
        <span>{snapshot.estimated_context_tokens || 0} / {snapshot.budget_tokens || 0} tokens</span>
      </summary>
      <div className="context-preview-stats">
        <ContextStat label="Excluded" value={`${snapshot.excluded_history_messages || 0} messages`} />
        <ContextStat label="Pinned" value={`${snapshot.included_pinned_messages || 0} included`} />
        <ContextStat label="Summary" value={snapshot.summary_used ? 'used' : 'not used'} />
        <ContextStat label="Current files" value={`${currentTurn.text_attachment_count || 0} files`} />
      </div>
      <ContextBudgetBreakdown snapshot={snapshot} />
      {fileContexts.length > 0 && (
        <div className="context-preview-files">
          {fileContexts.map(fileContext => (
            <span key={`${fileContext.filename}-${fileContext.selected_chunks}`}>
              {fileContext.filename}: {fileContext.selected_chunks} / {fileContext.total_chunks} chunks
            </span>
          ))}
        </div>
      )}
      <div className="context-preview-messages">
        {messages.length === 0 ? (
          <div className="context-preview-empty">No prior history will be sent.</div>
        ) : messages.map((message, index) => {
          const directSourceIndex = Number.isInteger(message.message_index) ? message.message_index : null;
          const sourceIndexes = Array.isArray(message.source_message_indexes)
            ? message.source_message_indexes.filter(Number.isInteger)
            : [];
          const hasSources = directSourceIndex !== null || sourceIndexes.length > 0;

          return (
            <div className={`context-preview-message ${message.role || 'message'}`} key={`${message.role}-${index}`}>
              <div className="context-preview-role-row">
                <div className="context-preview-role">{message.role || 'message'}</div>
                {hasSources && onJumpToMessage && (
                  <div className="context-preview-source-list" aria-label="Context source messages">
                    {directSourceIndex !== null && (
                      <button
                        type="button"
                        className="context-preview-source-button"
                        onClick={() => onJumpToMessage(directSourceIndex)}
                      >
                        Message #{directSourceIndex + 1}
                      </button>
                    )}
                    {sourceIndexes.map(sourceIndex => (
                      <button
                        type="button"
                        className="context-preview-source-button"
                        key={sourceIndex}
                        onClick={() => onJumpToMessage(sourceIndex)}
                      >
                        Message #{sourceIndex + 1}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <RichMarkdown content={previewText(message.content)} mode="compact" />
            </div>
          );
        })}
      </div>
    </details>
  );
}

export default function ConversationContext({
  recentMessages,
  contextSummary,
  contextAudit,
  contextPolicy,
  onUpdateContextPolicy,
  onAddContextMemory,
  onUpdateContextMemory,
  onDeleteContextMemory,
  onSearchConversationHistory,
  onClearContextSummary,
  onRebuildContextSummary,
  nextContextPreview,
  latestTurn,
  totalMessages,
  isInProgress = false,
  onJumpToMessage
}) {
  const snapshot = latestTurn?.context_snapshot;
  const effectivePolicy = contextPolicy || contextAudit?.context_policy || snapshot?.context_policy || null;
  const [policyDraft, setPolicyDraft] = useState(effectivePolicy || {});
  const [isSavingPolicy, setIsSavingPolicy] = useState(false);
  const [isUpdatingSummary, setIsUpdatingSummary] = useState(false);
  const [isUpdatingMemory, setIsUpdatingMemory] = useState(false);
  const [newMemoryContent, setNewMemoryContent] = useState('');
  const [editingMemoryId, setEditingMemoryId] = useState(null);
  const [editingMemoryContent, setEditingMemoryContent] = useState('');
  const [historySearchQuery, setHistorySearchQuery] = useState('');
  const [historySearchResults, setHistorySearchResults] = useState([]);
  const [historySearchError, setHistorySearchError] = useState('');
  const [isSearchingHistory, setIsSearchingHistory] = useState(false);

  useEffect(() => {
    if (effectivePolicy) {
      setPolicyDraft(effectivePolicy);
    }
  }, [effectivePolicy]);

  const updatePolicyDraft = (field, value) => {
    setPolicyDraft(prev => ({ ...prev, [field]: value }));
  };

  const savePolicy = async () => {
    if (!onUpdateContextPolicy) return;
    setIsSavingPolicy(true);
    try {
      await onUpdateContextPolicy({
        token_budget: Number(policyDraft.token_budget),
        recent_turns: Number(policyDraft.recent_turns),
        message_char_limit: Number(policyDraft.message_char_limit),
        summarize_older: Boolean(policyDraft.summarize_older),
        use_pinned: Boolean(policyDraft.use_pinned),
        pin_message_char_limit: Number(policyDraft.pin_message_char_limit),
        pin_max_chars: Number(policyDraft.pin_max_chars),
        use_memory: Boolean(policyDraft.use_memory),
        memory_item_char_limit: Number(policyDraft.memory_item_char_limit),
        memory_max_chars: Number(policyDraft.memory_max_chars),
      });
    } finally {
      setIsSavingPolicy(false);
    }
  };

  const runSummaryAction = async (action) => {
    if (!action) return;
    setIsUpdatingSummary(true);
    try {
      await action();
    } finally {
      setIsUpdatingSummary(false);
    }
  };

  const runMemoryAction = async (action) => {
    if (!action) return;
    setIsUpdatingMemory(true);
    try {
      await action();
    } finally {
      setIsUpdatingMemory(false);
    }
  };

  const addMemory = async () => {
    const content = newMemoryContent.trim();
    if (!content || !onAddContextMemory) return;
    await runMemoryAction(async () => {
      await onAddContextMemory(content);
      setNewMemoryContent('');
    });
  };

  const startEditingMemory = (memory) => {
    setEditingMemoryId(memory.id);
    setEditingMemoryContent(memory.content || '');
  };

  const saveEditingMemory = async () => {
    const content = editingMemoryContent.trim();
    if (!content || !editingMemoryId || !onUpdateContextMemory) return;
    await runMemoryAction(async () => {
      await onUpdateContextMemory(editingMemoryId, { content });
      setEditingMemoryId(null);
      setEditingMemoryContent('');
    });
  };

  const searchHistory = async () => {
    const query = historySearchQuery.trim();
    if (!query || !onSearchConversationHistory) return;
    setIsSearchingHistory(true);
    setHistorySearchError('');
    try {
      const results = await onSearchConversationHistory(query);
      setHistorySearchResults(results || []);
    } catch (error) {
      console.error('Failed to search conversation history:', error);
      setHistorySearchError(error.message || 'Failed to search conversation history');
    } finally {
      setIsSearchingHistory(false);
    }
  };

  const saveSearchResultAsMemory = async (result) => {
    if (!onAddContextMemory) return;
    const content = [
      `From ${result.conversation_title || 'conversation'} (${result.source || 'history'}):`,
      result.content || result.excerpt || '',
    ].filter(Boolean).join('\n');
    await runMemoryAction(() => onAddContextMemory(content));
  };

  if (contextAudit) {
    const turnCount = contextAudit.turn_count || 0;
    const included = snapshot?.included_history_messages || 0;
    const omitted = snapshot?.omitted_history_messages || 0;
    const summaryUsed = Boolean(snapshot?.summary_used);
    const pinned = snapshot?.included_pinned_messages || 0;
    const excluded = snapshot?.excluded_history_messages || 0;
    const budget = snapshot?.budget_tokens || 0;
    const estimated = snapshot?.estimated_context_tokens || 0;
    const summaryState = contextAudit.context_summary || {};
    const summaryContent = summaryState.content || '';
    const contextMemory = contextAudit.context_memory || [];
    const enabledMemoryCount = contextMemory.filter(memory => memory.enabled).length;
    const policySummary = effectivePolicy
      ? `${effectivePolicy.recent_turns} turns, ${effectivePolicy.token_budget} tokens`
      : 'default';

    return (
      <div className="conversation-context compact">
        <div className="context-header">
          <span className="context-icon">💬</span>
          <span className="context-title">
            {isInProgress ? 'Context audit updating' : 'Context Management'}
          </span>
          <span className="context-badge">
            {turnCount} {turnCount === 1 ? 'turn' : 'turns'}
          </span>
        </div>

        <div className="context-content">
          <div className="context-stats-grid">
            <ContextStat label="Latest included" value={`${included} messages`} />
            <ContextStat label="Omitted" value={`${omitted} messages`} />
            <ContextStat label="Summary" value={summaryUsed ? 'used' : 'not used'} />
            <ContextStat label="Pinned" value={`${pinned} messages`} />
            <ContextStat label="Memory" value={`${enabledMemoryCount} active`} />
            <ContextStat label="Excluded" value={`${excluded} messages`} />
            <ContextStat label="Budget" value={budget ? `${estimated} / ${budget} tokens` : 'not recorded'} />
            <ContextStat label="Policy" value={policySummary} />
          </div>
          <ContextBudgetBreakdown snapshot={snapshot} />

          <ContextPreviewPanel preview={nextContextPreview} onJumpToMessage={onJumpToMessage} />

          <details className="context-history-search">
            <summary>Search history</summary>
            <div className="context-history-search-form">
              <input
                type="search"
                placeholder="Search previous conversations and memory"
                value={historySearchQuery}
                onChange={(event) => setHistorySearchQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault();
                    searchHistory();
                  }
                }}
                disabled={isSearchingHistory || !onSearchConversationHistory}
              />
              <button
                type="button"
                onClick={searchHistory}
                disabled={isSearchingHistory || !historySearchQuery.trim() || !onSearchConversationHistory}
              >
                {isSearchingHistory ? 'Searching...' : 'Search'}
              </button>
            </div>
            {historySearchError && <div className="context-history-search-error">{historySearchError}</div>}
            <div className="context-history-results">
              {historySearchResults.map((result, index) => (
                <div className="context-history-result" key={`${result.conversation_id}-${result.source}-${result.message_index ?? result.memory_id ?? index}`}>
                  <div className="context-history-result-meta">
                    <span>{result.conversation_title || 'Conversation'}</span>
                    <span>{result.source}{result.role ? ` / ${result.role}` : ''}</span>
                    {Number.isInteger(result.message_index) && <span>Message #{result.message_index + 1}</span>}
                  </div>
                  <div className="context-history-result-excerpt">{result.excerpt}</div>
                  <div className="context-history-result-actions">
                    <button
                      type="button"
                      onClick={() => saveSearchResultAsMemory(result)}
                      disabled={isUpdatingMemory || !onAddContextMemory}
                    >
                      Save as memory
                    </button>
                  </div>
                </div>
              ))}
              {historySearchQuery.trim() && !isSearchingHistory && historySearchResults.length === 0 && !historySearchError && (
                <div className="context-preview-empty">No matching history found.</div>
              )}
            </div>
          </details>

          <details className="context-memory-tools">
            <summary>Conversation memory</summary>
            <div className="context-memory-list">
              {contextMemory.length === 0 ? (
                <div className="context-preview-empty">No saved memory.</div>
              ) : contextMemory.map(memory => (
                <div className={`context-memory-item ${memory.enabled ? '' : 'disabled'}`} key={memory.id}>
                  {editingMemoryId === memory.id ? (
                    <textarea
                      value={editingMemoryContent}
                      onChange={(event) => setEditingMemoryContent(event.target.value)}
                      disabled={isUpdatingMemory}
                    />
                  ) : (
                    <div className="context-memory-content">{memory.content}</div>
                  )}
                  <div className="context-memory-actions">
                    <label className="context-memory-toggle">
                      <input
                        type="checkbox"
                        checked={Boolean(memory.enabled)}
                        onChange={(event) => runMemoryAction(() => onUpdateContextMemory?.(memory.id, { enabled: event.target.checked }))}
                        disabled={isUpdatingMemory || !onUpdateContextMemory}
                      />
                      <span>Enabled</span>
                    </label>
                    {editingMemoryId === memory.id ? (
                      <>
                        <button type="button" onClick={saveEditingMemory} disabled={isUpdatingMemory || !editingMemoryContent.trim()}>Save</button>
                        <button
                          type="button"
                          className="secondary"
                          onClick={() => { setEditingMemoryId(null); setEditingMemoryContent(''); }}
                          disabled={isUpdatingMemory}
                        >
                          Cancel
                        </button>
                      </>
                    ) : (
                      <button type="button" onClick={() => startEditingMemory(memory)} disabled={isUpdatingMemory}>Edit</button>
                    )}
                    <button
                      type="button"
                      className="secondary danger"
                      onClick={() => runMemoryAction(() => onDeleteContextMemory?.(memory.id))}
                      disabled={isUpdatingMemory || !onDeleteContextMemory}
                    >
                      Delete
                    </button>
                  </div>
                </div>
              ))}
            </div>
            <div className="context-memory-add">
              <textarea
                placeholder="Save durable project facts, preferences, or constraints for future turns"
                value={newMemoryContent}
                onChange={(event) => setNewMemoryContent(event.target.value)}
                disabled={isUpdatingMemory}
              />
              <button type="button" onClick={addMemory} disabled={isUpdatingMemory || !newMemoryContent.trim() || !onAddContextMemory}>
                {isUpdatingMemory ? 'Saving...' : 'Add memory'}
              </button>
            </div>
          </details>

          <details className="context-summary-tools">
            <summary>Summary cache</summary>
            <div className="context-summary-meta">
              <ContextStat label="Covered" value={`${summaryState.covered_messages || 0} messages`} />
              <ContextStat label="Updated" value={summaryState.updated_at ? new Date(summaryState.updated_at).toLocaleString() : 'never'} />
            </div>
            {summaryContent ? (
              <div className="context-summary-preview">
                <RichMarkdown content={previewText(summaryContent)} mode="compact" />
              </div>
            ) : (
              <div className="context-preview-empty">No cached summary.</div>
            )}
            <div className="context-summary-actions">
              <button
                type="button"
                onClick={() => runSummaryAction(onRebuildContextSummary)}
                disabled={isUpdatingSummary || !onRebuildContextSummary}
              >
                {isUpdatingSummary ? 'Updating...' : 'Rebuild summary'}
              </button>
              <button
                type="button"
                className="secondary"
                onClick={() => runSummaryAction(onClearContextSummary)}
                disabled={isUpdatingSummary || !onClearContextSummary || !summaryContent}
              >
                Clear summary
              </button>
            </div>
          </details>

          {effectivePolicy && (
            <details className="context-policy-editor">
              <summary>Context policy</summary>
              <div className="context-policy-grid">
                <label>
                  <span>Recent turns</span>
                  <input
                    type="number"
                    min="1"
                    max="100"
                    value={policyDraft.recent_turns || ''}
                    onChange={(event) => updatePolicyDraft('recent_turns', event.target.value)}
                    disabled={isSavingPolicy}
                  />
                </label>
                <label>
                  <span>Token budget</span>
                  <input
                    type="number"
                    min="1000"
                    max="200000"
                    step="1000"
                    value={policyDraft.token_budget || ''}
                    onChange={(event) => updatePolicyDraft('token_budget', event.target.value)}
                    disabled={isSavingPolicy}
                  />
                </label>
                <label>
                  <span>Message chars</span>
                  <input
                    type="number"
                    min="1000"
                    max="120000"
                    step="1000"
                    value={policyDraft.message_char_limit || ''}
                    onChange={(event) => updatePolicyDraft('message_char_limit', event.target.value)}
                    disabled={isSavingPolicy}
                  />
                </label>
                <label>
                  <span>Pin chars</span>
                  <input
                    type="number"
                    min="0"
                    max="120000"
                    step="1000"
                    value={policyDraft.pin_max_chars ?? ''}
                    onChange={(event) => updatePolicyDraft('pin_max_chars', event.target.value)}
                    disabled={isSavingPolicy}
                  />
                </label>
                <label>
                  <span>Memory chars</span>
                  <input
                    type="number"
                    min="0"
                    max="120000"
                    step="1000"
                    value={policyDraft.memory_max_chars ?? ''}
                    onChange={(event) => updatePolicyDraft('memory_max_chars', event.target.value)}
                    disabled={isSavingPolicy}
                  />
                </label>
                <label className="context-policy-toggle">
                  <input
                    type="checkbox"
                    checked={Boolean(policyDraft.summarize_older)}
                    onChange={(event) => updatePolicyDraft('summarize_older', event.target.checked)}
                    disabled={isSavingPolicy}
                  />
                  <span>Summarize older history</span>
                </label>
                <label className="context-policy-toggle">
                  <input
                    type="checkbox"
                    checked={Boolean(policyDraft.use_pinned)}
                    onChange={(event) => updatePolicyDraft('use_pinned', event.target.checked)}
                    disabled={isSavingPolicy}
                  />
                  <span>Use pinned context</span>
                </label>
                <label className="context-policy-toggle">
                  <input
                    type="checkbox"
                    checked={Boolean(policyDraft.use_memory)}
                    onChange={(event) => updatePolicyDraft('use_memory', event.target.checked)}
                    disabled={isSavingPolicy}
                  />
                  <span>Use conversation memory</span>
                </label>
              </div>
              <div className="context-policy-actions">
                <button type="button" onClick={savePolicy} disabled={isSavingPolicy || !onUpdateContextPolicy}>
                  {isSavingPolicy ? 'Saving...' : 'Save policy'}
                </button>
              </div>
            </details>
          )}

          {snapshot?.truncated && (
            <div className="context-note">Oldest recent messages were trimmed to fit the context budget.</div>
          )}

          {isInProgress && (
            <div className="context-processing">
              <div className="context-processing-text">
                <span className="processing-spinner"></span>
                Recording the current turn context snapshot...
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }

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
              <RichMarkdown content={contextSummary} mode="compact" />
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
                    <RichMarkdown content={msg.content} mode="compact" />
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
