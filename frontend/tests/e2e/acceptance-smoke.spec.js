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
  const searchableConversation = conversations.find((conversation) => conversation.message_count > 0) || conversations[0];
  const firstTitleWord = searchableConversation?.title?.split(/\s+/).find(Boolean);
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


async function createControlledConversation(request, page, title) {
  const createResponse = await request.post('/api/conversations', { data: {} });
  expect(createResponse.ok()).toBeTruthy();
  const created = await createResponse.json();
  const updateResponse = await request.patch(`/api/conversations/${created.id}`, { data: { title } });
  expect(updateResponse.ok()).toBeTruthy();
  const conversation = await updateResponse.json();
  let messages = [];

  const currentConversation = () => ({ ...conversation, messages });
  const metadata = () => ({
    id: conversation.id,
    created_at: conversation.created_at,
    updated_at: new Date().toISOString(),
    title: conversation.title,
    title_source: conversation.title_source || 'manual',
    title_locked: conversation.title_locked || false,
    title_updated_at: conversation.title_updated_at || null,
    message_count: messages.length,
    turn_count: messages.filter((message) => message.role === 'user').length,
    favorite: false,
    archived: false,
    pinned: false,
    tags: [],
  });

  await page.route('**/api/conversations', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ json: [metadata()] });
      return;
    }
    await route.fallback();
  });
  await page.route(`**/api/conversations/${conversation.id}`, async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ json: currentConversation() });
      return;
    }
    await route.fallback();
  });
  await page.route(`**/api/conversations/${conversation.id}/context`, async (route) => {
    await route.fulfill({ json: { turns: [], turn_count: messages.filter((message) => message.role === 'user').length } });
  });

  return {
    conversation,
    appendTurn(content, mode) {
      messages = [
        ...messages,
        { role: 'user', content },
        {
          role: 'assistant',
          status: 'complete',
          stage1: mode === 'quick' ? [] : [{ model: 'mock/stage1', response: 'mock stage one', status: 'success' }],
          stage2: mode === 'quick' ? [] : [{ model: 'mock/stage2', ranking: 'mock ranking', status: 'success' }],
          stage3: { response: `${mode} response for ${content}`, status: 'success', model: 'mock/model' },
          metadata: { mode },
        },
      ];
    },
  };
}

function sse(events) {
  return events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join('');
}

async function openControlledConversation(page, title) {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.getByText(title).first().click();
  await expect(page.locator('.message-input')).toBeVisible();
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

  test('restores council draft on failed send and clears it on accepted send', async ({ page, request }) => {
    const title = 'E2E Council Draft Recovery';
    const controlled = await createControlledConversation(request, page, title);
    let failNext = true;
    let postCount = 0;

    await page.route(`**/api/conversations/${controlled.conversation.id}/message/stream`, async (route) => {
      postCount += 1;
      const body = JSON.parse(route.request().postData() || '{}');
      if (failNext) {
        failNext = false;
        await route.fulfill({ status: 500, body: JSON.stringify({ detail: 'mock send failure' }), contentType: 'application/json' });
        return;
      }
      controlled.appendTurn(body.content, 'council');
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: sse([
          { type: 'stage1_complete', data: [{ model: 'mock/stage1', response: 'mock stage one', status: 'success' }] },
          { type: 'stage2_complete', data: [{ model: 'mock/stage2', ranking: 'mock ranking', status: 'success' }], metadata: { mode: 'council' } },
          { type: 'stage3_complete', data: { response: `council response for ${body.content}`, status: 'success', model: 'mock/model' } },
          { type: 'complete' },
        ]),
      });
    });

    try {
      await openControlledConversation(page, title);
      const input = page.locator('.message-input');
      await input.fill('council draft survives');
      await page.getByLabel('Send to council').click();
      await expect(input).toHaveValue('council draft survives');

      await page.getByLabel('Send to council').click();
      await expect(input).toHaveValue('');
      await expect(page.getByText('council draft survives', { exact: true })).toBeVisible();
      await expect(page.getByText('council response for council draft survives')).toBeVisible();
      expect(postCount).toBe(2);
    } finally {
      await request.delete(`/api/conversations/${controlled.conversation.id}`);
    }
  });

  test('restores quick draft on failed send and does not duplicate rapid submits', async ({ page, request }) => {
    const title = 'E2E Quick Draft Recovery';
    const controlled = await createControlledConversation(request, page, title);
    let failNext = true;
    let postCount = 0;

    await page.route(`**/api/conversations/${controlled.conversation.id}/quick/stream`, async (route) => {
      postCount += 1;
      const body = JSON.parse(route.request().postData() || '{}');
      if (failNext) {
        failNext = false;
        await route.fulfill({ status: 500, body: JSON.stringify({ detail: 'mock quick failure' }), contentType: 'application/json' });
        return;
      }
      controlled.appendTurn(body.content, 'quick');
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: sse([
          { type: 'quick_start' },
          { type: 'quick_complete', data: { response: `quick response for ${body.content}`, status: 'success', model: 'mock/model' }, metadata: { mode: 'quick' } },
          { type: 'complete' },
        ]),
      });
    });

    try {
      await openControlledConversation(page, title);
      const input = page.locator('.message-input');
      await input.fill('quick draft survives');
      await page.getByLabel('Quick query').click();
      await expect(input).toHaveValue('quick draft survives');

      await page.getByLabel('Quick query').dblclick();
      await expect(input).toHaveValue('');
      await expect(page.getByText('quick draft survives', { exact: true })).toBeVisible();
      await expect(page.getByText('quick response for quick draft survives')).toBeVisible();
      expect(postCount).toBe(2);
    } finally {
      await request.delete(`/api/conversations/${controlled.conversation.id}`);
    }
  });
});
