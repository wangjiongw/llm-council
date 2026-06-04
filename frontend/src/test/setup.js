import { vi } from 'vitest';
import '@testing-library/jest-dom/vitest';

class TestIntersectionObserver {
  constructor(callback) {
    this.callback = callback;
  }

  observe(element) {
    this.callback([{ isIntersecting: true, target: element }]);
  }

  unobserve() {}

  disconnect() {}
}

class TestResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

Object.defineProperty(window, 'IntersectionObserver', {
  writable: true,
  configurable: true,
  value: TestIntersectionObserver,
});

Object.defineProperty(window, 'ResizeObserver', {
  writable: true,
  configurable: true,
  value: TestResizeObserver,
});

Object.defineProperty(window, 'requestIdleCallback', {
  writable: true,
  configurable: true,
  value: (callback) => window.setTimeout(() => callback({ didTimeout: false, timeRemaining: () => 16 }), 0),
});

Object.defineProperty(window, 'cancelIdleCallback', {
  writable: true,
  configurable: true,
  value: (id) => window.clearTimeout(id),
});

Element.prototype.scrollIntoView = vi.fn();
HTMLElement.prototype.scrollTo = vi.fn();

Object.defineProperty(navigator, 'clipboard', {
  writable: true,
  configurable: true,
  value: {
    writeText: vi.fn(async () => undefined),
  },
});

if (!URL.createObjectURL) {
  URL.createObjectURL = vi.fn(() => 'blob:mock-url');
}
if (!URL.revokeObjectURL) {
  URL.revokeObjectURL = vi.fn();
}

const storage = new Map();
Object.defineProperty(window, 'localStorage', {
  writable: true,
  configurable: true,
  value: {
    getItem: vi.fn((key) => storage.get(key) ?? null),
    setItem: vi.fn((key, value) => storage.set(key, String(value))),
    removeItem: vi.fn((key) => storage.delete(key)),
    clear: vi.fn(() => storage.clear()),
  },
});
