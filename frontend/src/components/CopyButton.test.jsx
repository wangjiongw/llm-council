import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import CopyButton from './CopyButton';

beforeEach(() => {
  vi.useFakeTimers();
  navigator.clipboard.writeText.mockClear();
});

afterEach(() => {
  vi.runOnlyPendingTimers();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('CopyButton', () => {
  it('clears the copied feedback timer when unmounted', async () => {
    const clearTimeoutSpy = vi.spyOn(window, 'clearTimeout');
    const { unmount } = render(<CopyButton content="copy me" title="Copy final answer" />);

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Copy final answer' }));
    });

    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('copy me');
    expect(screen.getByRole('button', { name: 'Copy final answer' })).toHaveClass('copied');

    unmount();

    expect(clearTimeoutSpy).toHaveBeenCalled();
  });
});
