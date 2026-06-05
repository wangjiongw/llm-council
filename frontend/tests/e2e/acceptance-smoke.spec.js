import { expect, test } from '@playwright/test';

const requiredConversationKeys = ['id', 'title', 'message_count', 'favorite', 'archived', 'pinned', 'tags'];
const requiredSearchKeys = ['conversation_id', 'conversation_title', 'source', 'excerpt', 'score'];

async function conversationSeed(request) {
  const response = await request.get('/api/conversations');
  expect(response.ok()).toBeTruthy();
  const conversations = await response.json();
  expect(Array.isArray(conversations)).toBeTruthy();
  if (conversations.length > 0) {
    for (const key of requiredConversationKeys) {
      expect(conversations[0]).toHaveProperty(key);
    }
  }
  const firstTitleWord = conversations[0]?.title?.split(/\s+/).find(Boolean);
  return { conversations, query: firstTitleWord || 'New' };
}

async function openConversationFromSidebarSearch(page, request) {
  const { query } = await conversationSeed(request);
  const historySearch = page.getByLabel('Search conversation history');
  await expect(historySearch).toBeVisible();
  await historySearch.fill(query);

  const firstGroup = page.locator('.sidebar-search-group').first();
  await expect(firstGroup).toBeVisible();
  await expect(firstGroup.locator('.sidebar-search-group-meta')).toContainText(/hit/i);

  const firstResult = page.locator('.sidebar-search-result').first();
  await expect(firstResult).toBeVisible();
  await firstResult.click();
}

test.describe('deployed chatbox smoke', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      window.localStorage.clear();
    });
  });

  test('serves the deployed app and core API contracts', async ({ page, request }) => {
    const appResponse = await page.goto('/', { waitUntil: 'domcontentloaded' });
    expect(appResponse?.ok()).toBeTruthy();
    await expect(page.locator('.app')).toBeVisible();

    const { query } = await conversationSeed(request);
    const searchResponse = await request.get('/api/conversations/search', { params: { q: query, limit: '3' } });
    expect(searchResponse.ok()).toBeTruthy();
    const payload = await searchResponse.json();
    expect(payload).toHaveProperty('query');
    expect(Array.isArray(payload.results)).toBeTruthy();
    if (payload.results.length > 0) {
      for (const key of requiredSearchKeys) {
        expect(payload.results[0]).toHaveProperty(key);
      }
    }
  });

  test('can search history from the sidebar and open a result', async ({ page, request }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await openConversationFromSidebarSearch(page, request);

    await expect(page.getByLabel('Search in this conversation')).toBeVisible();
    await expect(page.locator('.messages-container')).toBeVisible();
  });

  test('can toggle theme and keep main chat controls visible', async ({ page, request }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await openConversationFromSidebarSearch(page, request);

    const toggle = page.locator('.theme-toggle-btn');
    await expect(toggle).toBeVisible();
    const before = await page.locator('html').getAttribute('data-theme');
    await toggle.click();
    await expect(page.locator('html')).not.toHaveAttribute('data-theme', before || '');

    await expect(page.getByLabel('Quick query')).toBeVisible();
    await expect(page.getByLabel('Send to council')).toBeVisible();
  });
});
