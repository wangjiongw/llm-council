import { useEffect, useMemo, useState } from 'react';
import './LLMSettingsModal.css';

const emptySettings = {
  default_provider: { base_url: '', api_key: '', timeout: 180, stream: true },
  council_models: [],
  chairman_model: '',
  chairman_fallback_models: [],
  quick_model: '',
  quick_fallback_models: [],
  title_model: '',
  title_fallback_models: [],
  summarization_model: '',
  summarization_fallback_models: [],
  model_overrides: {},
};

const splitLines = (value) =>
  value
    .split('\n')
    .map(item => item.trim())
    .filter(Boolean);

const joinLines = (value) => (Array.isArray(value) ? value.join('\n') : '');

const parseTimeout = (value) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : undefined;
};

const versionValue = (value) => value || '-';

const problemLabel = (problem) => ({
  missing_base_url: 'missing base URL',
  missing_api_key: 'missing API key',
  invalid_timeout: 'invalid timeout',
  disabled_model: 'disabled',
}[problem] || problem);

const rolesLabel = (roles = []) => roles.join(', ') || 'unassigned';

const probeStatusLabel = (value) => String(value || 'unknown').replace(/_/g, ' ');

export default function LLMSettingsModal({ open, onClose, api, backendVersion }) {
  const [settings, setSettings] = useState(emptySettings);
  const [defaultApiKey, setDefaultApiKey] = useState('');
  const [overrideModel, setOverrideModel] = useState('');
  const [overrideBaseUrl, setOverrideBaseUrl] = useState('');
  const [overrideApiKey, setOverrideApiKey] = useState('');
  const [overrideTimeout, setOverrideTimeout] = useState('');
  const [status, setStatus] = useState('');
  const [testModel, setTestModel] = useState('');
  const [testResult, setTestResult] = useState(null);
  const [diagnostics, setDiagnostics] = useState(null);
  const [probeResult, setProbeResult] = useState(null);
  const [isSaving, setIsSaving] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const [isRefreshingDiagnostics, setIsRefreshingDiagnostics] = useState(false);
  const [isRunningProbe, setIsRunningProbe] = useState(false);

  useEffect(() => {
    if (!open) return;

    (async () => {
      setStatus('Loading settings...');
      setTestResult(null);
      try {
        const [data, diagnosticsData] = await Promise.all([
          api.getLLMSettings(),
          api.getLLMProviderDiagnostics ? api.getLLMProviderDiagnostics() : Promise.resolve(null),
        ]);
        setSettings({ ...emptySettings, ...data });
        setDiagnostics(diagnosticsData);
        setProbeResult(null);
        setDefaultApiKey('');
        setStatus('');
      } catch (error) {
        setStatus(error.message);
      }
    })();
  }, [api, open]);

  const knownModels = useMemo(() => {
    const models = [
      ...settings.council_models,
      settings.chairman_model,
      ...settings.chairman_fallback_models,
      settings.quick_model,
      settings.title_model,
      settings.summarization_model,
      ...(diagnostics?.configured_models || []),
    ].filter(Boolean);
    return Array.from(new Set(models));
  }, [settings, diagnostics]);

  if (!open) return null;

  const updateField = (field, value) => {
    setSettings(prev => ({ ...prev, [field]: value }));
  };

  const updateDefaultProvider = (field, value) => {
    setSettings(prev => ({
      ...prev,
      default_provider: {
        ...prev.default_provider,
        [field]: value,
      },
    }));
  };

  const handleAddOverride = () => {
    const model = overrideModel.trim();
    if (!model) return;
    const timeout = parseTimeout(overrideTimeout);

    setSettings(prev => ({
      ...prev,
      model_overrides: {
        ...prev.model_overrides,
        [model]: {
          base_url: overrideBaseUrl.trim(),
          ...(overrideApiKey.trim() ? { api_key: overrideApiKey.trim() } : {}),
          ...(timeout ? { timeout } : {}),
        },
      },
    }));
    setOverrideModel('');
    setOverrideBaseUrl('');
    setOverrideApiKey('');
    setOverrideTimeout('');
  };

  const handleRemoveOverride = (model) => {
    setSettings(prev => {
      const nextOverrides = { ...prev.model_overrides };
      delete nextOverrides[model];
      return { ...prev, model_overrides: nextOverrides };
    });
  };

  const buildPayload = () => {
    const defaultTimeout = parseTimeout(settings.default_provider.timeout);
    const modelOverrides = Object.fromEntries(
      Object.entries(settings.model_overrides || {}).map(([model, override]) => [
        model,
        {
          ...(override.base_url ? { base_url: override.base_url } : {}),
          ...(override.api_key ? { api_key: override.api_key } : {}),
          ...(parseTimeout(override.timeout) ? { timeout: parseTimeout(override.timeout) } : {}),
          ...(override.enabled === false ? { enabled: false } : {}),
        },
      ])
    );

    const payload = {
      ...settings,
      default_provider: {
        base_url: settings.default_provider.base_url || '',
        ...(defaultTimeout ? { timeout: defaultTimeout } : {}),
        stream: settings.default_provider.stream !== false,
      },
      model_overrides: modelOverrides,
    };

    if (defaultApiKey.trim()) {
      payload.default_provider.api_key = defaultApiKey.trim();
    }

    return payload;
  };

  const handleSave = async () => {
    setIsSaving(true);
    setStatus('');
    try {
      const saved = await api.updateLLMSettings(buildPayload());
      setSettings({ ...emptySettings, ...saved });
      setDefaultApiKey('');
      setStatus('Saved. New calls will use these settings.');
      await refreshDiagnostics();
    } catch (error) {
      setStatus(error.message);
    } finally {
      setIsSaving(false);
    }
  };

  const refreshDiagnostics = async () => {
    if (!api.getLLMProviderDiagnostics) return;
    setIsRefreshingDiagnostics(true);
    try {
      setDiagnostics(await api.getLLMProviderDiagnostics());
    } catch (error) {
      setDiagnostics({ error: error.message });
    } finally {
      setIsRefreshingDiagnostics(false);
    }
  };

  const selectedProbeModel = () => (testModel || settings.quick_model || knownModels[0] || '').trim();

  const handleTest = async () => {
    const model = selectedProbeModel();
    if (!model) {
      setTestResult({ ok: false, error: 'Choose a model first.' });
      return;
    }

    setIsTesting(true);
    setTestResult(null);
    try {
      const result = await api.testLLMSettings(model);
      setTestResult(result);
    } catch (error) {
      setTestResult({ ok: false, error: error.message });
    } finally {
      setIsTesting(false);
    }
  };

  const handleRunDiagnosticsProbe = async () => {
    const model = selectedProbeModel();
    if (!model) {
      setProbeResult({ ok: false, error: 'Choose a model first.' });
      return;
    }
    if (!api.probeLLMProviderDiagnostics) {
      setProbeResult({ ok: false, error: 'Provider probe is unavailable in this frontend build.' });
      return;
    }

    setIsRunningProbe(true);
    setProbeResult(null);
    try {
      const result = await api.probeLLMProviderDiagnostics(model, { includeModelList: true });
      setProbeResult(result);
      await refreshDiagnostics();
    } catch (error) {
      setProbeResult({ ok: false, error: error.message });
    } finally {
      setIsRunningProbe(false);
    }
  };

  return (
    <div className="settings-modal-backdrop" role="presentation" onClick={onClose}>
      <div className="settings-modal" role="dialog" aria-modal="true" onClick={e => e.stopPropagation()}>
        <div className="settings-modal-header">
          <div>
            <h2>LLM Settings</h2>
            <p>Runtime provider routing for OpenAI-compatible servers.</p>
          </div>
          <button className="settings-close-btn" onClick={onClose} aria-label="Close settings">
            ×
          </button>
        </div>

        <div className="settings-grid">
          <section className="settings-section settings-version-section">
            <h3>Backend Status</h3>
            <dl className="settings-version-list">
              <div><dt>Commit</dt><dd>{versionValue(backendVersion?.commit)}</dd></div>
              <div><dt>PID</dt><dd>{versionValue(backendVersion?.pid)}</dd></div>
              <div><dt>Started</dt><dd>{versionValue(backendVersion?.started_at)}</dd></div>
              <div><dt>Bind</dt><dd>{versionValue(backendVersion?.backend_host)}:{versionValue(backendVersion?.backend_port)}</dd></div>
              <div><dt>Data</dt><dd>{versionValue(backendVersion?.data_dir)}</dd></div>
            </dl>
          </section>

          <section className="settings-section settings-diagnostics-section">
            <div className="settings-section-title-row">
              <h3>Provider Diagnostics</h3>
              <div className="settings-diagnostics-actions">
                <button className="settings-secondary-btn compact" onClick={refreshDiagnostics} disabled={isRefreshingDiagnostics}>
                  {isRefreshingDiagnostics ? 'Refreshing...' : 'Refresh'}
                </button>
                <button className="settings-secondary-btn compact" onClick={handleRunDiagnosticsProbe} disabled={isRunningProbe}>
                  {isRunningProbe ? 'Probing...' : 'Run Probe'}
                </button>
              </div>
            </div>
            {diagnostics?.error ? (
              <p className="settings-diagnostics-note">{diagnostics.error}</p>
            ) : diagnostics ? (
              <>
                <div className="provider-diagnostics-summary">
                  <span>{diagnostics.summary?.ready_model_count || 0} ready</span>
                  <span>{diagnostics.summary?.problem_model_count || 0} need attention</span>
                  <span>rate limit {diagnostics.checks?.rate_limit || 'unknown'}</span>
                  <span>connection {diagnostics.checks?.connection || 'unknown'}</span>
                </div>
                <div className="provider-diagnostics-list">
                  {(diagnostics.models || []).map(model => (
                    <div className={`provider-diagnostic-row ${model.problems?.length ? 'warn' : ''}`} key={model.model}>
                      <div>
                        <strong>{model.model}</strong>
                        <small>{rolesLabel(model.roles)} · {model.provider_source} provider</small>
                      </div>
                      <div>
                        <span>{model.base_url || 'no base URL'}</span>
                        <small>key {model.api_key_set ? 'set' : 'missing'} · timeout {model.timeout || '-'}s · stream {model.stream ? 'on' : 'off'} · {model.enabled ? 'enabled' : 'disabled'}</small>
                      </div>
                      <div className="provider-diagnostic-problems">
                        {model.problems?.length ? model.problems.map(problem => <span key={problem}>{problemLabel(problem)}</span>) : <span>ready</span>}
                      </div>
                    </div>
                  ))}
                </div>
                <p className="settings-diagnostics-note">{diagnostics.checks?.reason}</p>
                {probeResult && (
                  <div className={`provider-probe-result ${probeResult.error ? 'warn' : ''}`} aria-label="Provider probe result">
                    {probeResult.error ? (
                      <span>{probeResult.error}</span>
                    ) : (
                      <>
                        <strong>Probe {probeResult.model}</strong>
                        <span>connection {probeStatusLabel(probeResult.connection?.status)}</span>
                        <span>model list {probeStatusLabel(probeResult.model_list?.status)}{probeResult.model_list?.model_count != null ? ` · ${probeResult.model_list.model_count} models` : ''}</span>
                        <span>target {probeResult.model_list?.target_model_found ? 'found' : 'not confirmed'}</span>
                        <span>rate limit {probeStatusLabel(probeResult.rate_limit?.status)}</span>
                      </>
                    )}
                  </div>
                )}
              </>
            ) : (
              <p className="settings-diagnostics-note">Diagnostics unavailable.</p>
            )}
          </section>

          <section className="settings-section">
            <h3>Default Provider</h3>
            <label>
              Base URL
              <input
                value={settings.default_provider.base_url || ''}
                onChange={e => updateDefaultProvider('base_url', e.target.value)}
                placeholder="https://api.example.com/v1"
              />
            </label>
            <label>
              API Key
              <input
                value={defaultApiKey}
                onChange={e => setDefaultApiKey(e.target.value)}
                placeholder={settings.default_provider.api_key_set ? 'Configured, leave blank to keep' : 'Not configured'}
                type="password"
              />
            </label>
            <label>
              Default timeout (seconds)
              <input
                type="number"
                min="1"
                value={settings.default_provider.timeout || ''}
                onChange={e => updateDefaultProvider('timeout', e.target.value)}
                placeholder="180"
              />
            </label>
            <label className="settings-checkbox-label">
              <input
                type="checkbox"
                checked={settings.default_provider.stream !== false}
                onChange={e => updateDefaultProvider('stream', e.target.checked)}
              />
              Stream upstream LLM responses
            </label>
          </section>

          <section className="settings-section">
            <h3>Model Roles</h3>
            <label>
              Council Models
              <textarea
                rows={4}
                value={joinLines(settings.council_models)}
                onChange={e => updateField('council_models', splitLines(e.target.value))}
              />
            </label>
            <div className="settings-two-col">
              <label>
                Chairman
                <input value={settings.chairman_model} onChange={e => updateField('chairman_model', e.target.value)} />
              </label>
              <label>
                Quick
                <input value={settings.quick_model} onChange={e => updateField('quick_model', e.target.value)} />
              </label>
            </div>
            <div className="settings-two-col">
              <label>
                Title
                <input value={settings.title_model} onChange={e => updateField('title_model', e.target.value)} />
              </label>
              <label>
                Summary
                <input value={settings.summarization_model} onChange={e => updateField('summarization_model', e.target.value)} />
              </label>
            </div>
          </section>

          <section className="settings-section">
            <h3>Fallback Models</h3>
            <label>
              Chairman fallback
              <textarea
                rows={3}
                value={joinLines(settings.chairman_fallback_models)}
                onChange={e => updateField('chairman_fallback_models', splitLines(e.target.value))}
              />
            </label>
            <label>
              Quick fallback
              <textarea
                rows={3}
                value={joinLines(settings.quick_fallback_models)}
                onChange={e => updateField('quick_fallback_models', splitLines(e.target.value))}
              />
            </label>
            <label>
              Title fallback
              <textarea
                rows={3}
                value={joinLines(settings.title_fallback_models)}
                onChange={e => updateField('title_fallback_models', splitLines(e.target.value))}
              />
            </label>
            <label>
              Summary fallback
              <textarea
                rows={3}
                value={joinLines(settings.summarization_fallback_models)}
                onChange={e => updateField('summarization_fallback_models', splitLines(e.target.value))}
              />
            </label>
          </section>

          <section className="settings-section">
            <h3>Per-model Override</h3>
            <label>
              Model
              <input value={overrideModel} onChange={e => setOverrideModel(e.target.value)} placeholder="vendor/model" />
            </label>
            <label>
              Base URL
              <input value={overrideBaseUrl} onChange={e => setOverrideBaseUrl(e.target.value)} placeholder="Optional override" />
            </label>
            <label>
              API Key
              <input value={overrideApiKey} onChange={e => setOverrideApiKey(e.target.value)} type="password" placeholder="Optional override" />
            </label>
            <label>
              Timeout seconds
              <input
                type="number"
                min="1"
                value={overrideTimeout}
                onChange={e => setOverrideTimeout(e.target.value)}
                placeholder="Optional override, e.g. 600"
              />
            </label>
            <button className="settings-secondary-btn" onClick={handleAddOverride}>Add Override</button>
            <div className="override-list">
              {Object.entries(settings.model_overrides || {}).map(([model, override]) => (
                <div className="override-row" key={model}>
                  <span>{model}</span>
                  <small>
                    {override.base_url || 'default URL'} · {override.api_key_set || override.api_key ? 'key set' : 'default key'}
                    {override.timeout ? ` · timeout ${override.timeout}s` : ''}
                  </small>
                  <button onClick={() => handleRemoveOverride(model)}>Remove</button>
                </div>
              ))}
            </div>
          </section>
        </div>

        <div className="settings-test-row">
          <input
            value={testModel}
            onChange={e => setTestModel(e.target.value)}
            placeholder={settings.quick_model || knownModels[0] || 'Model to test'}
            list="known-llm-models"
          />
          <datalist id="known-llm-models">
            {knownModels.map(model => <option value={model} key={model} />)}
          </datalist>
          <button className="settings-secondary-btn" onClick={handleTest} disabled={isTesting}>
            {isTesting ? 'Testing...' : 'Test'}
          </button>
          {testResult && (
            <span className={`settings-test-result ${testResult.ok ? 'ok' : 'fail'}`}>
              {testResult.ok ? 'Connected' : testResult.error}
            </span>
          )}
        </div>

        <div className="settings-modal-footer">
          <span className="settings-status">{status}</span>
          <button className="settings-secondary-btn" onClick={onClose}>Close</button>
          <button className="settings-primary-btn" onClick={handleSave} disabled={isSaving}>
            {isSaving ? 'Saving...' : 'Save Settings'}
          </button>
        </div>
      </div>
    </div>
  );
}
