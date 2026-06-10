import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import LLMSettingsModal from './LLMSettingsModal';

const settingsPayload = {
  default_provider: { base_url: 'https://default.example/v1', api_key_set: true, timeout: 45, stream: true },
  council_models: ['model-a'],
  chairman_model: 'model-a',
  chairman_fallback_models: [],
  quick_model: 'model-b',
  quick_fallback_models: [],
  title_model: 'model-a',
  title_fallback_models: [],
  summarization_model: 'model-a',
  summarization_fallback_models: [],
  model_overrides: {},
};

const diagnosticsPayload = {
  schema: 'llm_provider_diagnostics_v1',
  read_only: true,
  configured_models: ['model-a', 'model-b'],
  summary: { ready_model_count: 1, problem_model_count: 1 },
  checks: {
    connection: 'not_run',
    model_list: 'configured_only',
    rate_limit: 'not_checked',
    reason: 'Read-only diagnostics do not call the provider or expose secrets.',
  },
  models: [
    {
      model: 'model-a',
      roles: ['council', 'chairman'],
      provider_source: 'default',
      base_url: 'https://default.example/v1',
      api_key_set: true,
      timeout: 45,
      stream: true,
      enabled: true,
      problems: [],
    },
    {
      model: 'model-b',
      roles: ['quick'],
      provider_source: 'override',
      base_url: '',
      api_key_set: false,
      timeout: null,
      stream: false,
      enabled: false,
      problems: ['missing_base_url', 'missing_api_key', 'disabled_model'],
    },
  ],
};

describe('LLMSettingsModal provider diagnostics', () => {
  it('loads and renders read-only provider diagnostics without exposing secrets', async () => {
    const api = {
      getLLMSettings: vi.fn().mockResolvedValue(settingsPayload),
      getLLMProviderDiagnostics: vi.fn().mockResolvedValue(diagnosticsPayload),
      updateLLMSettings: vi.fn(),
      testLLMSettings: vi.fn(),
    };

    render(
      <LLMSettingsModal
        open
        onClose={vi.fn()}
        api={api}
        backendVersion={{ commit: 'abc123', pid: 10 }}
      />
    );

    expect(await screen.findByText('Provider Diagnostics')).toBeInTheDocument();
    expect(screen.getByText('1 ready')).toBeInTheDocument();
    expect(screen.getByText('1 need attention')).toBeInTheDocument();
    expect(screen.getByText('rate limit not_checked')).toBeInTheDocument();
    expect(screen.getByText('connection not_run')).toBeInTheDocument();
    expect(screen.getAllByText('model-a').length).toBeGreaterThan(0);
    expect(screen.getAllByText('model-b').length).toBeGreaterThan(0);
    expect(screen.getByText('missing API key')).toBeInTheDocument();
    expect(screen.getAllByText('disabled').length).toBeGreaterThan(0);
    expect(screen.queryByText(/default-key|override-key/)).not.toBeInTheDocument();
  });

  it('refreshes provider diagnostics on demand', async () => {
    const user = userEvent.setup();
    const api = {
      getLLMSettings: vi.fn().mockResolvedValue(settingsPayload),
      getLLMProviderDiagnostics: vi.fn()
        .mockResolvedValueOnce(diagnosticsPayload)
        .mockResolvedValueOnce({
          ...diagnosticsPayload,
          summary: { ready_model_count: 2, problem_model_count: 0 },
          models: diagnosticsPayload.models.map(model => ({ ...model, problems: [] })),
        }),
      updateLLMSettings: vi.fn(),
      testLLMSettings: vi.fn(),
    };

    render(<LLMSettingsModal open onClose={vi.fn()} api={api} backendVersion={{}} />);

    await screen.findByText('1 need attention');
    await user.click(screen.getByRole('button', { name: /Refresh/i }));

    await waitFor(() => {
      expect(api.getLLMProviderDiagnostics).toHaveBeenCalledTimes(2);
    });
    expect(await screen.findByText('2 ready')).toBeInTheDocument();
  });
});
