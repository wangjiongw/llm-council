import { useState, useEffect, useRef, useMemo, useCallback, memo } from 'react';
import RichMarkdown from './RichMarkdown';
import Stage1 from './Stage1';
import Stage2 from './Stage2';
import Stage3 from './Stage3';
import ConversationContext from './ConversationContext';
import FileQueue from './FileQueue';
import UploadButton from './UploadButton';
import { formatFileSize } from '../utils/fileUtils';
import './ChatInterface.css';
import './FileQueue.css';

const contentToText = (content) => {
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
};

const DRAFT_STORAGE_PREFIX = 'llm-council:draft:';
const LONG_USER_MESSAGE_CHARS = 2200;
const LONG_USER_MESSAGE_LINES = 44;
const SEARCH_SCOPE_OPTIONS = [
  { value: 'all', label: 'All' },
  { value: 'user', label: 'User' },
  { value: 'assistant', label: 'Answer' },
  { value: 'council', label: 'Council' },
  { value: 'files', label: 'Files' },
];

const isLongText = (text, maxChars, maxLines) => (
  text.length > maxChars || text.split('\n').length > maxLines
);

const escapeRegExp = (value) => String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

const countOccurrences = (text, query) => {
  if (!query) return 0;
  const matches = String(text || '').match(new RegExp(escapeRegExp(query), 'gi'));
  return matches?.length || 0;
};

const HighlightedText = memo(function HighlightedText({ text, query }) {
  const source = String(text || '');
  const cleanQuery = String(query || '').trim();
  if (!cleanQuery) return source;

  const pattern = new RegExp(`(${escapeRegExp(cleanQuery)})`, 'gi');
  return source.split(pattern).map((part, index) => (
    part.toLowerCase() === cleanQuery.toLowerCase()
      ? <mark className="search-hit" key={`${part}-${index}`}>{part}</mark>
      : part
  ));
});

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

const ModelStatusList = memo(function ModelStatusList({ statuses }) {
  const items = Object.values(statuses || {});
  if (items.length === 0) return null;

  const labelFor = (status) => {
    if (status === 'first_event') return 'streaming';
    if (status === 'success') return 'done';
    return status || 'pending';
  };

  return (
    <div className="model-status-list">
      {items.map(item => (
        <div className={`model-status-item ${item.status === 'failed' ? 'failed' : ''}`} key={item.model}>
          <span className="model-status-name">{item.model.split('/')[1] || item.model}</span>
          <span className="model-status-state">{labelFor(item.status)}</span>
          {item.first_event_seconds != null && (
            <span className="model-status-meta">first event {item.first_event_seconds}s</span>
          )}
          {item.duration_seconds != null && (
            <span className="model-status-meta">total {item.duration_seconds}s</span>
          )}
          {item.error_type && (
            <span className="model-status-error">{item.error_type}</span>
          )}
        </div>
      ))}
    </div>
  );
});

const shortModelName = (model) => model?.split('/')?.[1] || model || 'unknown';

const summarizeResults = (results = [], contentKey) => {
  const total = results.length;
  const success = results.filter(result => result?.status !== 'failed' && Boolean(result?.[contentKey])).length;
  return { total, success, failed: Math.max(0, total - success) };
};

const formatStageSummary = (label, summary) => `${label} ${summary.success}/${summary.total || 0}${summary.failed ? `, ${summary.failed} failed` : ''}`;

const stageModelBreakdown = (items = [], contentKey) => items.map((item) => ({
  model: shortModelName(item?.model),
  status: item?.status === 'failed' || !item?.[contentKey] ? 'failed' : 'ok',
  errorType: item?.error_type || '',
  duration: item?.duration_seconds,
  tokens: item?.usage?.total_tokens || 0,
}));

const sumTokens = (...items) => items.flat().reduce((total, item) => {
  const usage = item?.usage || {};
  return total + (usage.total_tokens || 0);
}, 0);

const maxDuration = (...items) => {
  const durations = items.flat()
    .map(item => item?.duration_seconds)
    .filter(value => typeof value === 'number');
  return durations.length ? Math.max(...durations) : null;
};

const CouncilRunSummary = memo(function CouncilRunSummary({ msg }) {
  const isQuick = msg.metadata?.mode === 'quick';
  const stage1 = summarizeResults(msg.stage1 || [], 'response');
  const stage2 = summarizeResults(msg.stage2 || [], 'ranking');
  const attempts = msg.stage3?.metadata?.attempts || msg.metadata?.attempts || [];
  const warnings = msg.metadata?.warnings || [];
  const tokenTotal = sumTokens(msg.stage1 || [], msg.stage2 || [], [msg.stage3]);
  const slowestStageDuration = maxDuration(msg.stage1 || [], msg.stage2 || [], [msg.stage3]);
  const failedModels = [
    ...(msg.stage1 || []),
    ...(msg.stage2 || []),
    ...(attempts || []).filter(attempt => attempt && !attempt.ok),
  ]
    .filter(item => item?.status === 'failed' || item?.error || item?.error_type)
    .map(item => shortModelName(item.model))
    .filter(Boolean);
  const uniqueFailedModels = [...new Set(failedModels)];
  const hasData = stage1.total > 0 || stage2.total > 0 || msg.stage3 || attempts.length > 0 || warnings.length > 0;

  if (!hasData) return null;

  const stage1Breakdown = stageModelBreakdown(msg.stage1 || [], 'response');
  const stage2Breakdown = stageModelBreakdown(msg.stage2 || [], 'ranking');
  const stage3Tokens = msg.stage3?.usage?.total_tokens || 0;
  const hasBreakdown = stage1Breakdown.length > 0 || stage2Breakdown.length > 0 || attempts.length > 0 || stage3Tokens > 0;

  return (
    <div className="council-run-summary" aria-label={isQuick ? 'Quick run summary' : 'Council run summary'}>
      <div className="council-summary-main">
        <span className="council-summary-title">{isQuick ? 'Quick summary' : 'Council summary'}</span>
        {isQuick && msg.stage3?.status && <span className="council-summary-chip">Status {msg.stage3.status}</span>}
        {!isQuick && stage1.total > 0 && <span className="council-summary-chip">{formatStageSummary('Stage 1', stage1)}</span>}
        {!isQuick && stage2.total > 0 && <span className="council-summary-chip">{formatStageSummary('Stage 2', stage2)}</span>}
        {msg.stage3?.model && <span className="council-summary-chip">{isQuick ? 'Model' : 'Chair'} {shortModelName(msg.stage3.model)}</span>}
        {uniqueFailedModels.length > 0 && <span className="council-summary-chip warning">{uniqueFailedModels.length} model failure{uniqueFailedModels.length === 1 ? '' : 's'}</span>}
        {attempts.length > 1 && <span className="council-summary-chip">{attempts.length - 1} fallback attempt{attempts.length === 2 ? '' : 's'}</span>}
        {tokenTotal > 0 && <span className="council-summary-chip">{tokenTotal} tokens</span>}
        {slowestStageDuration != null && <span className="council-summary-chip">slowest {slowestStageDuration}s</span>}
      </div>
      {warnings.length > 0 && (
        <div className="council-summary-warnings">
          {warnings.map((warning, index) => <span key={`${warning}-${index}`}>{warning}</span>)}
        </div>
      )}
      {hasBreakdown && (
        <details className="council-summary-details">
          <summary>Model contribution and timing</summary>
          <div className="council-contribution-grid">
            {stage1Breakdown.map((item, index) => (
              <span className={item.status === 'failed' ? 'failed' : ''} key={`s1-${item.model}-${index}`}>
                Stage 1 · {item.model}: {item.status}{item.errorType ? ` · ${item.errorType}` : ''}{item.duration != null ? ` · ${item.duration}s` : ''}{item.tokens ? ` · ${item.tokens} tokens` : ''}
              </span>
            ))}
            {stage2Breakdown.map((item, index) => (
              <span className={item.status === 'failed' ? 'failed' : ''} key={`s2-${item.model}-${index}`}>
                Stage 2 · {item.model}: {item.status}{item.errorType ? ` · ${item.errorType}` : ''}{item.duration != null ? ` · ${item.duration}s` : ''}{item.tokens ? ` · ${item.tokens} tokens` : ''}
              </span>
            ))}
            {attempts.map((attempt, index) => (
              <span className={attempt.ok ? '' : 'failed'} key={`attempt-${attempt.model}-${index}`}>
                Stage 3 attempt {index + 1} · {shortModelName(attempt.model)}: {attempt.ok ? 'ok' : (attempt.error_type || 'failed')}
              </span>
            ))}
            {msg.stage3?.model && (
              <span>Final · {shortModelName(msg.stage3.model)}{stage3Tokens ? ` · ${stage3Tokens} tokens` : ''}{msg.stage3.duration_seconds != null ? ` · ${msg.stage3.duration_seconds}s` : ''}</span>
            )}
          </div>
        </details>
      )}
    </div>
  );
});

const classifyError = (msg) => {
  const stage3 = msg.stage3 || {};
  const failedStage1 = (msg.stage1 || []).find(result => result?.status === 'failed');
  const failedStage2 = (msg.stage2 || []).find(result => result?.status === 'failed');
  const failedAttempt = (stage3.metadata?.attempts || []).find(attempt => !attempt.ok);
  const errorType = stage3.error_type || msg.error_type || failedAttempt?.error_type || failedStage1?.error_type || failedStage2?.error_type || 'unknown_error';
  const error = stage3.error || msg.error || failedAttempt?.error || failedStage1?.error || failedStage2?.error || '';

  if (/context|token|length/i.test(`${errorType} ${error}`)) {
    return { title: 'Context payload needs adjustment', detail: 'The request likely exceeded provider or policy context limits.', action: 'Open Context Policy or preview the context package before retrying.', settings: false, context: true };
  }
  if (errorType === 'disabled_model') {
    return { title: 'Model disabled', detail: 'One configured model is disabled or unavailable.', action: 'Open LLM settings and enable or replace the model.', settings: true, diagnostics: true };
  }
  if (errorType === 'http_status' && /401|403/.test(error)) {
    return { title: 'Provider authentication failed', detail: 'The provider rejected the request.', action: 'Check API key and base URL in LLM settings.', settings: true, diagnostics: true };
  }
  if (errorType === 'http_status' && /429/.test(error)) {
    return { title: 'Provider rate limited the request', detail: 'The model provider returned a rate limit response.', action: 'Retry later or switch to another fallback model.', settings: true, diagnostics: true };
  }
  if (errorType === 'timeout' || errorType === 'network_error') {
    return { title: 'Provider request did not complete', detail: 'The model call timed out or hit a network error.', action: 'Retry the turn, continue saved stages, or choose a faster fallback model.', settings: false, diagnostics: true };
  }
  if (errorType === 'all_stage1_models_failed') {
    return { title: 'All Stage 1 models failed', detail: 'No council member returned a usable first-stage response.', action: 'Retry after checking model availability and provider settings.', settings: true };
  }
  if (errorType === 'invalid_response') {
    return { title: 'Invalid provider response', detail: 'A provider response could not be parsed into usable model output.', action: 'Retry or switch the affected model.', settings: true };
  }
  return { title: 'Council run needs attention', detail: error || 'A model call failed or the saved run is incomplete.', action: 'Retry the turn or inspect context/model details below.', settings: false };
};

const errorDetailsForMessage = (msg) => {
  const stage3 = msg.stage3 || {};
  const failedStage1 = (msg.stage1 || []).filter(result => result?.status === 'failed' || result?.error);
  const failedStage2 = (msg.stage2 || []).filter(result => result?.status === 'failed' || result?.error);
  const failedAttempts = (stage3.metadata?.attempts || []).filter(attempt => attempt && !attempt.ok);
  return [
    msg.error_type && `message error_type: ${msg.error_type}`,
    msg.error && `message error: ${msg.error}`,
    stage3.error_type && `stage3 error_type: ${stage3.error_type}`,
    stage3.error && `stage3 error: ${stage3.error}`,
    ...failedStage1.map(result => `stage1 ${shortModelName(result.model)}: ${result.error_type || 'failed'} ${result.error || ''}`.trim()),
    ...failedStage2.map(result => `stage2 ${shortModelName(result.model)}: ${result.error_type || 'failed'} ${result.error || ''}`.trim()),
    ...failedAttempts.map(attempt => `fallback ${shortModelName(attempt.model)}: ${attempt.error_type || 'failed'} ${attempt.error || ''}`.trim()),
  ].filter(Boolean);
};

const ErrorActionPanel = memo(function ErrorActionPanel({ msg, canContinue, onContinue, onRetry, onOpenSettings, onOpenContextPolicy }) {
  const hasFailure = msg.status === 'failed' ||
    msg.status === 'interrupted' ||
    msg.stage3?.status === 'failed' ||
    msg.stage3?.status === 'interrupted';

  if (!hasFailure) return null;

  const info = classifyError(msg);
  const details = errorDetailsForMessage(msg);

  return (
    <div className="error-action-panel">
      <div className="error-action-copy">
        <strong>{info.title}</strong>
        <span>{info.detail}</span>
        <span>{info.action}</span>
        {details.length > 0 && (
          <details className="error-technical-details">
            <summary>Technical details</summary>
            <pre>{details.join('\n')}</pre>
          </details>
        )}
      </div>
      <div className="error-action-buttons">
        {canContinue && (
          <button type="button" className="continue-button" onClick={onContinue}>
            Continue
          </button>
        )}
        <button type="button" className="retry-button" onClick={onRetry}>
          Retry
        </button>
        {info.context && onOpenContextPolicy && (
          <button type="button" className="settings-inline-button" onClick={onOpenContextPolicy}>
            Context Policy
          </button>
        )}
        {info.settings && onOpenSettings && (
          <button type="button" className="settings-inline-button" onClick={onOpenSettings}>
            LLM Settings
          </button>
        )}
        {info.diagnostics && (
          <button type="button" className="settings-inline-button" onClick={() => document.querySelector('.error-technical-details summary')?.click()}>
            Diagnostics
          </button>
        )}
      </div>
    </div>
  );
});

const formatCount = (value, unit) => `${value || 0} ${unit}${value === 1 ? '' : 's'}`;

const ContextAuditDetails = memo(function ContextAuditDetails({ turnAudit, fallbackSnapshot, onReplayContext }) {
  const [replay, setReplay] = useState(null);
  const [replayError, setReplayError] = useState('');
  const [isReplayLoading, setIsReplayLoading] = useState(false);
  const snapshot = turnAudit?.context_snapshot || fallbackSnapshot;

  useEffect(() => {
    setReplay(null);
    setReplayError('');
    setIsReplayLoading(false);
  }, [turnAudit?.id]);

  if (!snapshot) return null;

  const runs = turnAudit?.runs || [];
  const currentTurn = snapshot.current_turn || {};
  const fileContexts = currentTurn.file_contexts || [];
  const included = snapshot.included_history_messages || 0;
  const omitted = snapshot.omitted_history_messages || 0;
  const summaryUsed = Boolean(snapshot.summary_used);
  const pinnedCount = snapshot.included_pinned_messages || 0;
  const excludedCount = snapshot.excluded_history_messages || 0;
  const mode = turnAudit?.mode || snapshot.mode;
  const status = turnAudit?.status;
  const canReplay = Boolean(onReplayContext && typeof turnAudit?.user_message_index === 'number');

  const handleReplayContext = async () => {
    if (!canReplay || isReplayLoading) return;
    setIsReplayLoading(true);
    setReplayError('');
    try {
      const payload = await onReplayContext(turnAudit.user_message_index, null);
      setReplay(payload);
    } catch (error) {
      console.error('Failed to rebuild context:', error);
      setReplayError(error.message || 'Failed to rebuild context');
    } finally {
      setIsReplayLoading(false);
    }
  };

  return (
    <details className="context-audit-details">
      <summary>
        <span className="context-audit-title">Context</span>
        <span className="context-audit-chip">{mode || 'mode unknown'}</span>
        <span className="context-audit-chip">{included} history messages</span>
        {summaryUsed && <span className="context-audit-chip">summary</span>}
        {pinnedCount > 0 && <span className="context-audit-chip">{pinnedCount} pinned</span>}
        {excludedCount > 0 && <span className="context-audit-chip">{excludedCount} excluded</span>}
      </summary>

      <div className="context-audit-grid">
        <div>
          <span className="context-audit-label">Status</span>
          <strong>{status || 'recorded'}</strong>
        </div>
        <div>
          <span className="context-audit-label">Budget</span>
          <strong>{snapshot.estimated_context_tokens || 0} / {snapshot.budget_tokens || 0} tokens</strong>
        </div>
        <div>
          <span className="context-audit-label">History</span>
          <strong>{included} included, {omitted} omitted</strong>
        </div>
        <div>
          <span className="context-audit-label">Current turn</span>
          <strong>
            {formatCount(currentTurn.text_attachment_count, 'file')}
            {currentTurn.image_attachment_count ? `, ${formatCount(currentTurn.image_attachment_count, 'image')}` : ''}
          </strong>
        </div>
        <div>
          <span className="context-audit-label">Pinned</span>
          <strong>{pinnedCount} included, {snapshot.omitted_pinned_messages || 0} omitted</strong>
        </div>
        <div>
          <span className="context-audit-label">Excluded</span>
          <strong>{excludedCount} excluded</strong>
        </div>
      </div>

      {(currentTurn.file_names?.length > 0 || fileContexts.length > 0) && (
        <div className="context-audit-files">
          {currentTurn.file_names?.map(name => <span key={name}>{name}</span>)}
          {fileContexts.map(fileContext => (
            <span key={`${fileContext.filename}-chunks`}>
              {fileContext.filename}: {fileContext.selected_chunks} / {fileContext.total_chunks} chunks
            </span>
          ))}
        </div>
      )}

      {canReplay && (
        <div className="context-replay-actions">
          <button
            type="button"
            className="context-replay-button"
            onClick={handleReplayContext}
            disabled={isReplayLoading}
          >
            {isReplayLoading ? 'Rebuilding context...' : 'Rebuild context for this turn'}
          </button>
          {replay && (
            <span className="context-replay-note">
              {replay.replay_kind === 'saved_context_payload' ? 'saved payload' : 'current-policy rebuild'}, {replay.message_count || 0} messages
            </span>
          )}
        </div>
      )}

      {replayError && <div className="context-replay-error">{replayError}</div>}

      {replay && (
        <div className="context-replay-panel">
          <div className="context-replay-stats">
            <span>mode {replay.mode || 'unknown'}</span>
            <span>rebuilt {replay.rebuilt_snapshot?.estimated_context_tokens ?? replay.snapshot?.estimated_context_tokens ?? 0} tokens</span>
            <span>saved {replay.saved_snapshot?.estimated_context_tokens ?? replay.snapshot?.estimated_context_tokens ?? snapshot.estimated_context_tokens ?? 0} tokens</span>
            {replay.saved_status && <span>saved status {replay.saved_status}</span>}
          </div>
          {replay.comparison?.available && (
            <div className="context-replay-drift">
              <span>{replay.comparison.same_order ? 'same order' : 'order changed'}</span>
              <span>{replay.comparison.same_message_set ? 'same messages' : 'message drift'}</span>
              <span>saved-only {replay.comparison.saved_only_count || 0}</span>
              <span>rebuilt-only {replay.comparison.rebuilt_only_count || 0}</span>
              <span>token delta {replay.comparison.estimated_token_delta || 0}</span>
              {replay.comparison.policy_changed && <span>policy changed</span>}
            </div>
          )}
          <div className="context-replay-messages">
            {(replay.messages || []).map((message, index) => (
              <div className={`context-replay-message ${message.role || 'unknown'}`} key={`${message.role}-${message.source || 'context'}-${index}`}>
                <div className="context-replay-role-row">
                  <span className="context-replay-role">{message.role || 'message'}</span>
                  {message.source && <span className="context-replay-source">{message.source}</span>}
                  {typeof message.message_index === 'number' && (
                    <span className="context-replay-source">#{message.message_index}</span>
                  )}
                </div>
                <RichMarkdown content={message.content || ''} />
              </div>
            ))}
          </div>
        </div>
      )}

      {runs.length > 0 && (
        <div className="context-run-list">
          {runs.map((run, index) => (
            <div className={`context-run-item ${run.status === 'failed' ? 'failed' : ''}`} key={`${run.stage}-${run.model}-${index}`}>
              <span className="context-run-stage">{run.stage}</span>
              <span className="context-run-model">{run.model || 'unknown model'}</span>
              <span className="context-run-status">{run.status || 'recorded'}</span>
              {run.usage?.total_tokens != null && (
                <span className="context-run-usage">{run.usage.total_tokens} tokens</span>
              )}
              {run.error_type && <span className="context-run-error">{run.error_type}</span>}
            </div>
          ))}
        </div>
      )}
    </details>
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
  onResumeQuery,
  onEditMessage,
  onToggleMessagePin,
  onToggleMessageContextExcluded,
  onForkConversation,
  onReplayMessageContext,
  onOpenSettings,
  onOpenContextPolicy,
  isLastMessage,
  messageIndex,
  turnAnchorRef,
  messageAnchorRef,
  turnAudit,
  isHighlighted = false,
}) {
  const isUserMessage = msg.role === 'user';
  const isQuickResponse = msg.metadata?.mode === 'quick';
  const isPinned = Boolean(msg.pinned);
  const isContextExcluded = Boolean(msg.context_excluded);
  const pinLabel = isPinned ? 'Pinned' : 'Pin';
  const contextToggleLabel = isContextExcluded ? 'Excluded' : 'Context';
  const userText = isUserMessage ? contentToText(msg.content) : '';
  const userMessageIsLong = isUserMessage && isLongText(userText, LONG_USER_MESSAGE_CHARS, LONG_USER_MESSAGE_LINES);
  const [isUserExpanded, setIsUserExpanded] = useState(false);
  const isUserCollapsed = userMessageIsLong && !isUserExpanded;
  const togglePin = () => onToggleMessagePin?.(messageIndex, !isPinned);
  const toggleContextExcluded = () => onToggleMessageContextExcluded?.(messageIndex, !isContextExcluded);
  const forkFromMessage = () => onForkConversation?.(messageIndex);
  const contextSnapshot = msg.metadata?.context_snapshot || turnAudit?.context_snapshot;
  const hasModelContext = !isUserMessage && Boolean(
    contextSnapshot && (
      contextSnapshot.included_history_messages > 0 ||
      contextSnapshot.summary_used ||
      contextSnapshot.raw_history_messages > 0
    )
  );
  const restoredStatusText = !isUserMessage && !isLoading && (
    msg.status === 'interrupted'
      ? 'This council run was interrupted. Completed stages were preserved.'
      : msg.status === 'failed'
        ? `This council run failed${msg.error ? `: ${msg.error}` : '.'}`
        : msg.status === 'running'
          ? 'This council run was in progress when the page loaded. If it does not continue, retry the query.'
          : ''
  );
  const canContinueSavedStages = !isUserMessage &&
    !isQuickResponse &&
    isLastMessage &&
    !isLoading &&
    onResumeQuery &&
    (
      msg.status === 'interrupted' ||
      msg.status === 'failed' ||
      msg.status === 'running' ||
      !msg.stage3 ||
      msg.stage3?.status === 'failed'
    );

  const groupRef = useCallback((node) => {
    turnAnchorRef?.(node);
    messageAnchorRef?.(node);
  }, [turnAnchorRef, messageAnchorRef]);

  return (
    <div className={`message-group ${isHighlighted ? 'context-highlighted' : ''}`} ref={groupRef}>
      {/* Turn indicator for user messages */}
      {isUserMessage && turnNumber > 1 && (
        <div className="turn-indicator">
          <span className="turn-number">Turn {turnNumber}</span>
          <span className="turn-continuation">Continuing conversation</span>
        </div>
      )}

      {isUserMessage ? (
        <div className="user-message">
          <div className="message-label">
            <span className="role-icon">👤</span>
            <span>You</span>
            {turnNumber > 1 && <span className="turn-badge">{turnNumber}</span>}
            {onToggleMessagePin && (
              <button
                type="button"
                className={`pin-message-button ${isPinned ? 'active' : ''}`}
                onClick={togglePin}
                aria-pressed={isPinned}
                title={isPinned ? 'Remove from pinned context' : 'Always include this message in context'}
              >
                {pinLabel}
              </button>
            )}
            {onToggleMessageContextExcluded && (
              <button
                type="button"
                className={`context-visibility-button ${isContextExcluded ? 'excluded' : ''}`}
                onClick={toggleContextExcluded}
                aria-pressed={isContextExcluded}
                title={isContextExcluded ? 'Allow this message in future context' : 'Exclude this message from future context'}
              >
                {contextToggleLabel}
              </button>
            )}
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
            <div className={`user-message-body ${isUserCollapsed ? 'collapsed' : ''}`}>
              <RichMarkdown content={userText} />
            </div>
            {userMessageIsLong && (
              <div className="long-message-controls">
                <button
                  type="button"
                  className="long-message-toggle"
                  onClick={() => setIsUserExpanded((expanded) => !expanded)}
                >
                  {isUserExpanded ? 'Collapse message' : 'Show full message'}
                </button>
                <span>{userText.length.toLocaleString()} chars</span>
              </div>
            )}
          </div>
          {!isLoading && (
            <div className="message-actions">
              {onForkConversation && (
                <button
                  type="button"
                  className="branch-message-button"
                  onClick={forkFromMessage}
                  title="Create a new conversation branch from this message"
                  aria-label="Branch conversation from this message"
                >
                  Branch
                </button>
              )}
              <button
                type="button"
                className="edit-message-button"
                onClick={() => onEditMessage(msg, messageIndex)}
                title="Edit and retry from this message"
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
            {turnNumber > 1 && <span className="turn-badge">{turnNumber}</span>}
            {hasModelContext && (
              <span className="context-indicator">Context-aware response</span>
            )}
            {onToggleMessagePin && (
              <button
                type="button"
                className={`pin-message-button ${isPinned ? 'active' : ''}`}
                onClick={togglePin}
                aria-pressed={isPinned}
                title={isPinned ? 'Remove from pinned context' : 'Always include this response in context'}
              >
                {pinLabel}
              </button>
            )}
            {onToggleMessageContextExcluded && (
              <button
                type="button"
                className={`context-visibility-button ${isContextExcluded ? 'excluded' : ''}`}
                onClick={toggleContextExcluded}
                aria-pressed={isContextExcluded}
                title={isContextExcluded ? 'Allow this response in future context' : 'Exclude this response from future context'}
              >
                {contextToggleLabel}
              </button>
            )}
          </div>
          {restoredStatusText && (
            <div className={`assistant-status-banner ${msg.status}`}>
              {restoredStatusText}
            </div>
          )}

          <CouncilRunSummary msg={msg} />

          <ErrorActionPanel
            msg={msg}
            canContinue={Boolean(canContinueSavedStages)}
            onContinue={() => onResumeQuery?.(messageIndex)}
            onRetry={() => onRetryQuery?.()}
            onOpenSettings={onOpenSettings}
            onOpenContextPolicy={onOpenContextPolicy}
          />

          {/* Enhanced loading states with context awareness */}
          {msg.loading?.stage1 && (
            <div className="stage-loading-block">
              <div className="stage-loading">
                <div className="spinner"></div>
                <span>
                  {hasPreviousTurns
                    ? `Running Stage 1 with ${conversationContext.turnCount} previous turns of context...`
                    : 'Running Stage 1: Collecting individual responses...'
                  }
                </span>
              </div>
              <ModelStatusList statuses={msg.modelStatus?.stage1} />
            </div>
          )}
          {msg.stage1 && (
            <CollapsibleStage title="Stage 1: Individual Responses" icon="💬" defaultCollapsed={true}>
              <Stage1 responses={msg.stage1} />
            </CollapsibleStage>
          )}

          {msg.loading?.stage2 && (
            <div className="stage-loading-block">
              <div className="stage-loading">
                <div className="spinner"></div>
                <span>
                  {hasPreviousTurns
                    ? 'Running Stage 2: Peer rankings with conversation context...'
                    : 'Running Stage 2: Peer rankings...'
                  }
                </span>
              </div>
              <ModelStatusList statuses={msg.modelStatus?.stage2} />
            </div>
          )}
          {msg.stage2 && (
            <CollapsibleStage title="Stage 2: Peer Rankings" icon="🗳️" defaultCollapsed={true}>
              <Stage2
                rankings={msg.stage2}
                labelToModel={msg.metadata?.label_to_model}
                aggregateRankings={msg.metadata?.aggregate_rankings}
                hasContext={hasModelContext}
              />
            </CollapsibleStage>
          )}

          {msg.loading?.stage3 && (
            <div className="stage-loading-block">
              <div className="stage-loading">
                <div className="spinner"></div>
                <span>
                  {hasPreviousTurns
                    ? (isQuickResponse
                      ? 'Running quick response with conversation context...'
                      : 'Running Stage 3: Final synthesis with full conversation context...')
                    : (isQuickResponse
                      ? 'Running quick response...'
                      : 'Running Stage 3: Final synthesis...')
                  }
                </span>
              </div>
              <ModelStatusList statuses={msg.modelStatus?.stage3} />
            </div>
          )}
          {msg.stage3 && <Stage3 finalResponse={msg.stage3} hasContext={hasModelContext} />}

          <ContextAuditDetails
            turnAudit={turnAudit}
            fallbackSnapshot={contextSnapshot}
            onReplayContext={onReplayMessageContext}
          />

          {canContinueSavedStages && (
            <div className="message-actions">
              <button
                className="continue-button"
                onClick={() => onResumeQuery(messageIndex)}
                title="Continue from saved completed stages"
                aria-label="Continue from saved stages"
              >
                ▶️ Continue
              </button>
              <button
                className="retry-button"
                onClick={onRetryQuery}
                title="Retry this query from Stage 1"
                aria-label="Retry from scratch"
              >
                🔄 Retry from scratch
              </button>
            </div>
          )}

          {/* Retry button for completed assistant messages */}
          {msg.stage3 && !canContinueSavedStages && !isLoading && isLastMessage && (
            <div className="message-actions">
              {onForkConversation && (
                <button
                  type="button"
                  className="branch-message-button"
                  onClick={forkFromMessage}
                  title="Create a new conversation branch from this response"
                  aria-label="Branch conversation from this response"
                >
                  Branch
                </button>
              )}
              <button
                className="retry-button"
                onClick={onRetryQuery}
                title="Retry this query from Stage 1"
                aria-label="Retry from scratch"
              >
                🔄 Retry from scratch
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
  contextAudit,
  contextPolicy,
  onUpdateContextPolicy,
  onAddContextMemory,
  onUpdateContextMemory,
  onDeleteContextMemory,
  onSearchConversationHistory,
  onPreviewContext,
  onReplayMessageContext,
  onClearContextSummary,
  onRebuildContextSummary,
  onSendMessage,
  onSendQuickMessage,
  onStopQuery,
  onRetryQuery,
  onResumeQuery,
  onToggleMessagePin,
  onToggleMessageContextExcluded,
  onForkConversation,
  onOpenSettings,
  isLoading,
  activeStreamId,
  attachedFiles,
  onFilesChange,
  onFileUpload,
  onDeleteFile,
  messageJumpTarget,
  onMessageJumpHandled,
  draftToRestore,
  onDraftRestored,
}) {
  const [input, setInput] = useState('');
  const [contextPreview, setContextPreview] = useState(null);
  const [contextPreviewError, setContextPreviewError] = useState('');
  const [isPreviewLoading, setIsPreviewLoading] = useState(false);
  const messagesContainerRef = useRef(null);
  const messagesEndRef = useRef(null);
  const contextPanelRef = useRef(null);
  const inputRef = useRef(null);
  const turnAnchorsRef = useRef(new Map());
  const messageAnchorsRef = useRef(new Map());
  const draftHydratedConversationRef = useRef(null);
  const [draftStatus, setDraftStatus] = useState('');
  const [currentTurnIndex, setCurrentTurnIndex] = useState(0);
  const [highlightedMessageIndex, setHighlightedMessageIndex] = useState(null);
  const [messageSearchQuery, setMessageSearchQuery] = useState('');
  const [messageSearchScope, setMessageSearchScope] = useState('all');
  const [activeSearchResultIndex, setActiveSearchResultIndex] = useState(0);
  const [editTarget, setEditTarget] = useState(null);

  const draftStorageKey = conversation?.id ? `${DRAFT_STORAGE_PREFIX}${conversation.id}` : null;

  const clearSavedDraft = useCallback(() => {
    if (!draftStorageKey) return;
    try {
      window.localStorage.removeItem(draftStorageKey);
    } catch {
      // Local storage may be unavailable in restricted browser contexts.
    }
    setDraftStatus('');
  }, [draftStorageKey]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [conversation]);

  useEffect(() => {
    setContextPreview(null);
    setContextPreviewError('');
  }, [conversation?.id]);

  useEffect(() => {
    if (!draftStorageKey || !conversation?.id) {
      draftHydratedConversationRef.current = null;
      setDraftStatus('');
      return;
    }

    try {
      const saved = window.localStorage.getItem(draftStorageKey);
      setInput(saved || '');
      setDraftStatus(saved ? 'Draft restored' : '');
    } catch {
      setDraftStatus('Draft storage unavailable');
    } finally {
      draftHydratedConversationRef.current = conversation.id;
    }
  }, [conversation?.id, draftStorageKey]);

  useEffect(() => {
    if (!draftStorageKey || !conversation?.id) return undefined;
    if (draftHydratedConversationRef.current !== conversation.id) return undefined;
    if (editTarget) return undefined;

    const timeoutId = window.setTimeout(() => {
      try {
        const value = input.trim() ? input : '';
        if (value) {
          window.localStorage.setItem(draftStorageKey, value);
          setDraftStatus('Draft saved locally');
        } else {
          window.localStorage.removeItem(draftStorageKey);
          setDraftStatus('');
        }
      } catch {
        setDraftStatus('Draft storage unavailable');
      }
    }, 250);

    return () => window.clearTimeout(timeoutId);
  }, [conversation?.id, draftStorageKey, editTarget, input]);

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
      turnCount: contextAudit?.turn_count ?? turns.length,
      visibleTurnCount: turns.length,
      isInProgress
    };
  }, [conversation, contextAudit]);

  const hasPreviousTurns = conversationContext && conversationContext.turnCount > 0;

  const turnAuditByAssistantIndex = useMemo(() => {
    const entries = new Map();
    for (const turn of contextAudit?.turns || []) {
      if (typeof turn.assistant_message_index === 'number') {
        entries.set(turn.assistant_message_index, turn);
      }
    }
    return entries;
  }, [contextAudit]);

  const latestTurnAudit = useMemo(() => {
    const turns = contextAudit?.turns || [];
    return turns.length > 0 ? turns[turns.length - 1] : null;
  }, [contextAudit]);

  const turnEntries = useMemo(() => {
    if (!conversation?.messages) return [];
    return conversation.messages
      .map((msg, index) => ({
        messageIndex: index,
        turnNumber: Math.floor(index / 2) + 1,
        role: msg.role,
      }))
      .filter(entry => entry.role === 'user');
  }, [conversation]);

  const messageSearchResults = useMemo(() => {
    const rawQuery = messageSearchQuery.trim();
    const query = rawQuery.toLowerCase();
    if (!query || !conversation?.messages) return [];

    return conversation.messages.reduce((results, msg, index) => {
      const fileText = (msg.files || []).map(file => [file?.name, file?.type, file?.category].filter(Boolean).join(' ')).join('\n');
      const assistantText = [msg.stage3?.response || ''].join('\n');
      const councilText = [
        ...(msg.stage1 || []).map(result => result?.response || result?.error || ''),
        ...(msg.stage2 || []).map(result => result?.ranking || result?.error || ''),
      ].join('\n');
      const userTextForSearch = contentToText(msg.content);
      const scopeText = {
        all: [userTextForSearch, assistantText, councilText, fileText].join('\n'),
        user: msg.role === 'user' ? userTextForSearch : '',
        assistant: msg.role === 'assistant' ? assistantText : '',
        council: msg.role === 'assistant' ? councilText : '',
        files: fileText,
      };
      const text = scopeText[messageSearchScope] ?? scopeText.all;
      const lowerText = text.toLowerCase();
      const matchIndex = lowerText.indexOf(query);
      if (matchIndex === -1) return results;

      const excerptStart = Math.max(0, matchIndex - 48);
      const excerpt = text.slice(excerptStart, matchIndex + rawQuery.length + 96).replace(/\s+/g, ' ').trim();
      results.push({
        messageIndex: index,
        role: msg.role,
        scope: messageSearchScope,
        matchCount: countOccurrences(text, rawQuery),
        turnNumber: Math.floor(index / 2) + 1,
        excerpt: `${excerptStart > 0 ? '...' : ''}${excerpt}${matchIndex + rawQuery.length + 96 < text.length ? '...' : ''}`,
      });
      return results;
    }, []);
  }, [conversation, messageSearchQuery, messageSearchScope]);

  const showTurnNavigator = turnEntries.length > 1;
  const boundedCurrentTurnIndex = Math.max(0, Math.min(currentTurnIndex, turnEntries.length - 1));
  const boundedSearchResultIndex = Math.max(0, Math.min(activeSearchResultIndex, messageSearchResults.length - 1));
  const activeSearchResult = messageSearchResults[boundedSearchResultIndex] || null;
  const messageSearchMatchTotal = messageSearchResults.reduce((total, result) => total + (result.matchCount || 0), 0);

  useEffect(() => {
    turnAnchorsRef.current.clear();
    messageAnchorsRef.current.clear();
    setHighlightedMessageIndex(null);
    setMessageSearchQuery('');
    setActiveSearchResultIndex(0);
    setEditTarget(null);
  }, [conversation?.id]);

  const registerTurnAnchor = useCallback((messageIndex, node) => {
    if (node) {
      turnAnchorsRef.current.set(messageIndex, node);
    } else {
      turnAnchorsRef.current.delete(messageIndex);
    }
  }, []);

  const registerMessageAnchor = useCallback((messageIndex, node) => {
    if (node) {
      messageAnchorsRef.current.set(messageIndex, node);
    } else {
      messageAnchorsRef.current.delete(messageIndex);
    }
  }, []);

  const scrollToMessage = useCallback((messageIndex) => {
    const anchor = messageAnchorsRef.current.get(messageIndex);
    if (!anchor) return false;

    anchor.scrollIntoView({ behavior: 'smooth', block: 'start' });
    setHighlightedMessageIndex(messageIndex);
    window.setTimeout(() => {
      setHighlightedMessageIndex(current => (current === messageIndex ? null : current));
    }, 1600);
    return true;
  }, []);

  const jumpToSearchResult = useCallback((nextIndex) => {
    if (messageSearchResults.length === 0) return;
    const boundedIndex = Math.max(0, Math.min(nextIndex, messageSearchResults.length - 1));
    const result = messageSearchResults[boundedIndex];
    setActiveSearchResultIndex(boundedIndex);
    scrollToMessage(result.messageIndex);
  }, [messageSearchResults, scrollToMessage]);

  useEffect(() => {
    setActiveSearchResultIndex(0);
  }, [messageSearchQuery, messageSearchScope, conversation?.id]);

  const scrollToTurn = useCallback((nextIndex) => {
    const boundedIndex = Math.max(0, Math.min(nextIndex, turnEntries.length - 1));
    const entry = turnEntries[boundedIndex];
    if (!entry) return;

    const anchor = turnAnchorsRef.current.get(entry.messageIndex);
    anchor?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    setCurrentTurnIndex(boundedIndex);
  }, [turnEntries]);

  const scrollMessagesToTop = useCallback(() => {
    messagesContainerRef.current?.scrollTo({ top: 0, behavior: 'smooth' });
    setCurrentTurnIndex(0);
  }, []);

  const scrollToContextPanel = useCallback(() => {
    contextPanelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, []);

  const scrollMessagesToBottom = useCallback(() => {
    scrollToBottom();
    setCurrentTurnIndex(Math.max(0, turnEntries.length - 1));
  }, [turnEntries.length]);

  useEffect(() => {
    if (messageSearchQuery.trim() && activeSearchResult) {
      scrollToMessage(activeSearchResult.messageIndex);
    }
  }, [activeSearchResult, messageSearchQuery, scrollToMessage]);

  useEffect(() => {
    if (!messageJumpTarget || messageJumpTarget.conversationId !== conversation?.id) return;
    if (!Number.isInteger(messageJumpTarget.messageIndex)) {
      onMessageJumpHandled?.();
      return;
    }

    const frame = window.requestAnimationFrame(() => {
      const didScroll = scrollToMessage(messageJumpTarget.messageIndex);
      if (didScroll) onMessageJumpHandled?.();
    });

    return () => window.cancelAnimationFrame(frame);
  }, [conversation?.id, conversation?.messages?.length, messageJumpTarget, onMessageJumpHandled, scrollToMessage]);

  const handleMessagesScroll = useCallback(() => {
    const container = messagesContainerRef.current;
    if (!container || turnEntries.length === 0) return;

    const containerTop = container.getBoundingClientRect().top;
    let activeIndex = 0;
    turnEntries.forEach((entry, index) => {
      const anchor = turnAnchorsRef.current.get(entry.messageIndex);
      if (!anchor) return;
      if (anchor.getBoundingClientRect().top - containerTop <= 96) {
        activeIndex = index;
      }
    });

    setCurrentTurnIndex(prev => (prev === activeIndex ? prev : activeIndex));
  }, [turnEntries]);

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

  useEffect(() => {
    if (!draftToRestore) return undefined;

    const frameId = window.requestAnimationFrame(() => {
      setInput(draftToRestore.content || '');
      inputRef.current?.focus();
      onDraftRestored?.(draftToRestore.restoreId || draftToRestore.id);
    });

    return () => window.cancelAnimationFrame(frameId);
  }, [draftToRestore, onDraftRestored]);

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

  const handleEditMessage = useCallback((msg, messageIndex) => {
    const text = contentToText(msg.content);
    setEditTarget({
      messageIndex,
      turnNumber: Math.floor(messageIndex / 2) + 1,
      originalContent: text,
    });
    setInput(text);
    window.requestAnimationFrame(() => {
      inputRef.current?.focus();
      adjustInputHeight();
    });
  }, [adjustInputHeight]);

  const cancelEditTarget = useCallback(() => {
    setEditTarget(null);
    setInput('');
    window.requestAnimationFrame(() => adjustInputHeight());
  }, [adjustInputHeight]);

  const submitEditedRetry = useCallback((mode) => {
    if (!editTarget || isLoading || !input.trim()) return;
    onRetryQuery?.({
      messageIndex: editTarget.messageIndex,
      editedContent: input,
      mode,
    });
    setEditTarget(null);
    setInput('');
    clearSavedDraft();
    setContextPreview(null);
    setContextPreviewError('');
  }, [clearSavedDraft, editTarget, input, isLoading, onRetryQuery]);

  const handleSubmit = useCallback((e) => {
    e.preventDefault();
    if (editTarget) {
      submitEditedRetry('council');
      return;
    }
    if ((input.trim() || attachedFiles.length > 0) && !isLoading) {
      onSendMessage(input, attachedFiles);
      setInput('');
      clearSavedDraft();
      setContextPreview(null);
      setContextPreviewError('');
      // App clears sent files after a successful response.
    }
  }, [input, attachedFiles, isLoading, onSendMessage, editTarget, submitEditedRetry, clearSavedDraft]);

  const handleQuickSubmit = useCallback((e) => {
    e.preventDefault();
    if (editTarget) {
      submitEditedRetry('quick');
      return;
    }
    if ((input.trim() || attachedFiles.length > 0) && !isLoading && onSendQuickMessage) {
      onSendQuickMessage(input, attachedFiles);
      setInput('');
      clearSavedDraft();
      setContextPreview(null);
      setContextPreviewError('');
      // App clears sent files after a successful response.
    }
  }, [input, attachedFiles, isLoading, onSendQuickMessage, editTarget, submitEditedRetry, clearSavedDraft]);

  const handlePreviewContext = useCallback(async (mode) => {
    if (!onPreviewContext || isLoading || isPreviewLoading) return;
    setIsPreviewLoading(true);
    setContextPreviewError('');
    try {
      const preview = await onPreviewContext(input, attachedFiles, mode);
      setContextPreview(preview);
    } catch (error) {
      console.error('Failed to preview context:', error);
      setContextPreviewError(error.message || 'Failed to preview context');
    } finally {
      setIsPreviewLoading(false);
    }
  }, [attachedFiles, input, isLoading, isPreviewLoading, onPreviewContext]);

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
      if (e.key === 'Escape' && !e.repeat) {
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
      <div className="messages-container" ref={messagesContainerRef} onScroll={handleMessagesScroll}>
        {conversation.messages.length === 0 ? (
          <div className="empty-state">
            <h2>Start a conversation</h2>
            <p>Ask a question to consult the LLM Council</p>
          </div>
        ) : (
          <>
            <div className="conversation-search-bar" role="search">
              <input
                type="search"
                value={messageSearchQuery}
                onChange={(event) => setMessageSearchQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault();
                    jumpToSearchResult(boundedSearchResultIndex + (event.shiftKey ? -1 : 1));
                  } else if (event.key === 'Escape') {
                    setMessageSearchQuery('');
                  }
                }}
                placeholder="Search in this conversation"
                aria-label="Search in this conversation"
              />
              <select
                className="conversation-search-filter"
                value={messageSearchScope}
                onChange={(event) => setMessageSearchScope(event.target.value)}
                aria-label="Search scope"
              >
                {SEARCH_SCOPE_OPTIONS.map((option) => (
                  <option value={option.value} key={option.value}>{option.label}</option>
                ))}
              </select>
              <span className="conversation-search-status">
                {messageSearchQuery.trim()
                  ? `${messageSearchResults.length ? boundedSearchResultIndex + 1 : 0} / ${messageSearchResults.length}${messageSearchMatchTotal ? ` · ${messageSearchMatchTotal} hits` : ''}`
                  : `${conversation.messages.length} messages`}
              </span>
              <button
                type="button"
                className="conversation-search-button"
                onClick={() => jumpToSearchResult(boundedSearchResultIndex - 1)}
                disabled={!messageSearchResults.length || boundedSearchResultIndex <= 0}
              >
                Prev
              </button>
              <button
                type="button"
                className="conversation-search-button"
                onClick={() => jumpToSearchResult(boundedSearchResultIndex + 1)}
                disabled={!messageSearchResults.length || boundedSearchResultIndex >= messageSearchResults.length - 1}
              >
                Next
              </button>
              {messageSearchQuery && (
                <button
                  type="button"
                  className="conversation-search-button compact"
                  onClick={() => setMessageSearchQuery('')}
                >
                  Clear
                </button>
              )}
            </div>
            {activeSearchResult && messageSearchQuery.trim() && (
              <button
                type="button"
                className="conversation-search-excerpt"
                onClick={() => jumpToSearchResult(boundedSearchResultIndex)}
              >
                <span>{activeSearchResult.role} · Turn {activeSearchResult.turnNumber}</span>
                <strong><HighlightedText text={activeSearchResult.excerpt} query={messageSearchQuery} /></strong>
              </button>
            )}

            {/* Show conversation context for multi-turn conversations */}
            {hasPreviousTurns && (
              <div className="conversation-section" ref={contextPanelRef}>
                <ConversationContext
                  recentMessages={conversationContext.recentMessages}
                  contextAudit={contextAudit}
                  contextPolicy={contextPolicy}
                  onUpdateContextPolicy={onUpdateContextPolicy}
                  onAddContextMemory={onAddContextMemory}
                  onUpdateContextMemory={onUpdateContextMemory}
                  onDeleteContextMemory={onDeleteContextMemory}
                  onSearchConversationHistory={onSearchConversationHistory}
                  onClearContextSummary={onClearContextSummary}
                  onRebuildContextSummary={onRebuildContextSummary}
                  nextContextPreview={contextPreview}
                  latestTurn={latestTurnAudit}
                  totalMessages={conversationContext.totalMessages}
                  isInProgress={conversationContext.isInProgress}
                  onJumpToMessage={scrollToMessage}
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
                  onResumeQuery={onResumeQuery}
                  onEditMessage={handleEditMessage}
                  onToggleMessagePin={isLoading ? null : onToggleMessagePin}
                  onToggleMessageContextExcluded={isLoading ? null : onToggleMessageContextExcluded}
                  onForkConversation={isLoading ? null : onForkConversation}
                  onReplayMessageContext={isLoading ? null : onReplayMessageContext}
                  onOpenSettings={onOpenSettings}
                  onOpenContextPolicy={scrollToContextPanel}
                  isLastMessage={index === conversation.messages.length - 1}
                  messageIndex={index}
                  turnAnchorRef={msg.role === 'user' ? (node) => registerTurnAnchor(index, node) : undefined}
                  messageAnchorRef={(node) => registerMessageAnchor(index, node)}
                  turnAudit={msg.role === 'assistant' ? turnAuditByAssistantIndex.get(index) : null}
                  isHighlighted={highlightedMessageIndex === index}
                />
              ))}
            </div>
          </>
        )}

        {showTurnNavigator && (
          <div className="turn-navigator" aria-label="Turn navigation">
            <button
              type="button"
              className="turn-nav-button"
              onClick={() => scrollToTurn(boundedCurrentTurnIndex - 1)}
              disabled={boundedCurrentTurnIndex <= 0}
            >
              ↑ Prev Turn
            </button>
            <span className="turn-nav-status">
              Turn {turnEntries[boundedCurrentTurnIndex]?.turnNumber || 1} / {turnEntries.length}
            </span>
            <button
              type="button"
              className="turn-nav-button"
              onClick={() => scrollToTurn(boundedCurrentTurnIndex + 1)}
              disabled={boundedCurrentTurnIndex >= turnEntries.length - 1}
            >
              ↓ Next Turn
            </button>
            <button type="button" className="turn-nav-button compact" onClick={scrollMessagesToTop}>
              Top
            </button>
            <button type="button" className="turn-nav-button compact" onClick={scrollMessagesToBottom}>
              Bottom
            </button>
          </div>
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
        {editTarget && !isLoading && (
          <div className="edit-retry-banner">
            <div>
              <strong>Editing Turn {editTarget.turnNumber}</strong>
              <span>Submitting will replace this user message, remove later messages, and regenerate from here.</span>
            </div>
            <button type="button" onClick={cancelEditTarget}>Cancel</button>
          </div>
        )}

        {hasPreviousTurns && !isLoading && !editTarget && (
          <div className="input-context-hint">
            <span className="hint-icon">💭</span>
            <span className="hint-text">
              Your next message will include {conversationContext.turnCount} previous turns of context
            </span>
            {onPreviewContext && (
              <div className="context-preview-actions">
                <button
                  type="button"
                  onClick={() => handlePreviewContext('council')}
                  disabled={isPreviewLoading}
                >
                  {isPreviewLoading ? 'Previewing...' : 'Preview Council'}
                </button>
                <button
                  type="button"
                  onClick={() => handlePreviewContext('quick')}
                  disabled={isPreviewLoading || !onSendQuickMessage}
                >
                  Preview Quick
                </button>
              </div>
            )}
          </div>
        )}

        {contextPreviewError && (
          <div className="context-preview-error">{contextPreviewError}</div>
        )}

        {draftStatus && !editTarget && !isLoading && (
          <div className="draft-status-row">
            <span>{draftStatus}</span>
            {input.trim() && (
              <button type="button" onClick={() => { setInput(''); clearSavedDraft(); }}>
                Clear draft
              </button>
            )}
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
                    ? "Query in progress... (Esc to stop)"
                    : editTarget
                      ? "Edit this message... (Enter retry Council, Ctrl+Enter retry Quick)"
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
                title="Stop current query (Esc)"
                aria-label="Stop current query (Esc)"
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
                  disabled={(editTarget ? !input.trim() : (!input.trim() && attachedFiles.length === 0)) || isLoading}
                  title={editTarget ? "Retry this edited message with quick mode" : "Quick single-model response"}
                  aria-label={editTarget ? "Retry edited message with quick mode" : "Quick query"}
                >
                  {editTarget ? '⚡ Retry Quick' : '⚡ Quick'}
                </button>
                <button
                  type="submit"
                  className="send-button"
                  disabled={(editTarget ? !input.trim() : (!input.trim() && attachedFiles.length === 0)) || isLoading}
                  title={editTarget ? "Retry this edited message with council mode" : "Full 3-stage council response"}
                  aria-label={editTarget ? "Retry edited message with council mode" : "Send to council"}
                >
                  {editTarget ? '🏛️ Retry Council' : '🏛️ Council'}
                </button>
              </div>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}
