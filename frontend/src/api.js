/**
 * API client for the LLM Council backend.
 */

const API_BASE = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');

let currentAbortController = null;

function startAbortableRequest() {
  const controller = new AbortController();
  currentAbortController = controller;
  return controller;
}

function finishAbortableRequest(controller) {
  if (currentAbortController === controller) {
    currentAbortController = null;
  }
}

function normalizeAbortError(error) {
  if (error.name === 'AbortError' || error.message === 'Query stopped by user') {
    throw new Error('Query stopped by user');
  }
  throw error;
}

export function parseSSEBlock(block) {
  const dataLines = [];

  for (const line of block.split(/\r?\n/)) {
    if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).replace(/^ /, ''));
    }
  }

  if (dataLines.length === 0) {
    return null;
  }

  return JSON.parse(dataLines.join('\n'));
}

async function readSSEEvents(response, onEvent, controller) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  const processBuffer = (flush = false) => {
    const normalized = buffer.replace(/\r\n/g, '\n');
    const blocks = normalized.split('\n\n');
    buffer = flush ? '' : blocks.pop();
    const completeBlocks = flush ? blocks.filter(Boolean) : blocks;

    for (const block of completeBlocks) {
      if (!block.trim()) continue;
      try {
        const event = parseSSEBlock(block);
        if (event) {
          onEvent(event.type, event);
        }
      } catch (e) {
        console.error('Failed to parse SSE event:', e);
      }
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      buffer += decoder.decode();
      processBuffer(true);
      break;
    }

    if (controller.signal.aborted) {
      throw new Error('Query stopped by user');
    }

    buffer += decoder.decode(value, { stream: true });
    processBuffer();
  }
}

export const api = {
  /**
   * List all conversations.
   */
  async listConversations() {
    const response = await fetch(`${API_BASE}/api/conversations`);
    if (!response.ok) {
      throw new Error('Failed to list conversations');
    }
    return response.json();
  },

  /**
   * Create a new conversation.
   */
  async createConversation() {
    const response = await fetch(`${API_BASE}/api/conversations`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({}),
    });
    if (!response.ok) {
      throw new Error('Failed to create conversation');
    }
    return response.json();
  },

  /**
   * Get a specific conversation.
   */
  async getConversation(conversationId) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}`
    );
    if (!response.ok) {
      throw new Error('Failed to get conversation');
    }
    return response.json();
  },

  /**
   * Create a new conversation branch from a selected message.
   */
  async forkConversation(conversationId, messageIndex) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/fork`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ message_index: messageIndex }),
      }
    );
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || 'Failed to branch conversation');
    }
    return response.json();
  },

  /**
   * Get context snapshots and model-run audit records for a conversation.
   */
  async getConversationContext(conversationId) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/context`
    );
    if (!response.ok) {
      throw new Error('Failed to get conversation context');
    }
    return response.json();
  },

  /**
   * Search locally stored conversation history for reusable context.
   */
  async searchConversationHistory(query, limit = 20) {
    const params = new URLSearchParams({ q: query || '', limit: String(limit) });
    const response = await fetch(`${API_BASE}/api/conversations/search?${params.toString()}`);
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || 'Failed to search conversation history');
    }
    return response.json();
  },

  /**
   * Preview the model-facing context package for the next turn.
   */
  async previewConversationContext(conversationId, content = '', mode = 'council', files = []) {
    if (files.length > 0) {
      const formData = new FormData();
      formData.append('content', content || '');
      formData.append('mode', mode);
      files.forEach(file => {
        formData.append('files', file.rawFile || file);
      });

      const response = await fetch(
        `${API_BASE}/api/conversations/${conversationId}/context/preview/files`,
        {
          method: 'POST',
          body: formData,
        }
      );
      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(errorText || 'Failed to preview context');
      }
      return response.json();
    }

    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/context/preview`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ content: content || '', mode }),
      }
    );
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || 'Failed to preview context');
    }
    return response.json();
  },

  /**
   * Rebuild the context package for a stored user message without mutating it.
   */
  async replayMessageContext(conversationId, messageIndex, mode = null) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/messages/${messageIndex}/context/replay`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ mode }),
      }
    );
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || 'Failed to rebuild context');
    }
    return response.json();
  },


  /**
   * Clear the cached context summary for a conversation.
   */
  async clearContextSummary(conversationId) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/context-summary`,
      { method: 'DELETE' }
    );
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || 'Failed to clear context summary');
    }
    return response.json();
  },

  /**
   * Rebuild the cached context summary for a conversation.
   */
  async rebuildContextSummary(conversationId) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/context-summary/rebuild`,
      { method: 'POST' }
    );
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || 'Failed to rebuild context summary');
    }
    return response.json();
  },

  /**
   * Get the effective context policy for one conversation.
   */
  async getContextPolicy(conversationId) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/context-policy`
    );
    if (!response.ok) {
      throw new Error('Failed to get context policy');
    }
    return response.json();
  },

  /**
   * Update the per-conversation context policy.
   */
  async updateContextPolicy(conversationId, policy) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/context-policy`,
      {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(policy),
      }
    );
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || 'Failed to update context policy');
    }
    return response.json();
  },

  /**
   * Add durable user-managed memory to a conversation.
   */
  async addContextMemory(conversationId, content, enabled = true) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/context-memory`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ content, enabled }),
      }
    );
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || 'Failed to add context memory');
    }
    return response.json();
  },

  /**
   * Update durable user-managed memory.
   */
  async updateContextMemory(conversationId, memoryId, updates) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/context-memory/${memoryId}`,
      {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(updates),
      }
    );
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || 'Failed to update context memory');
    }
    return response.json();
  },

  /**
   * Delete durable user-managed memory.
   */
  async deleteContextMemory(conversationId, memoryId) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/context-memory/${memoryId}`,
      { method: 'DELETE' }
    );
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || 'Failed to delete context memory');
    }
    return response.json();
  },

  /**
   * Update conversation metadata.
   * @param {string} conversationId - The conversation ID
   * @param {object} updates - Partial metadata updates
   */
  async updateConversation(conversationId, updates) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}`,
      {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(updates),
      }
    );
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || 'Failed to update conversation');
    }
    return response.json();
  },

  /**
   * Get saved conversation-management preferences.
   */
  async getConversationManagement() {
    const response = await fetch(`${API_BASE}/api/conversations/management`);
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || 'Failed to load conversation management');
    }
    return response.json();
  },

  /**
   * Update metadata for multiple conversations at once.
   */
  async batchUpdateConversations(conversationIds, updates, tagMode = 'replace') {
    const response = await fetch(`${API_BASE}/api/conversations/batch`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ conversation_ids: conversationIds, updates, tag_mode: tagMode }),
    });
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || 'Failed to update selected conversations');
    }
    return response.json();
  },

  /**
   * Persist a color for one conversation tag.
   */
  async updateTagColor(tag, color) {
    const response = await fetch(`${API_BASE}/api/conversations/tag-colors`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ tag, color }),
    });
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || 'Failed to update tag color');
    }
    return response.json();
  },

  /**
   * Save or replace a reusable conversation sidebar view.
   */
  async saveConversationView(name, filters) {
    const response = await fetch(`${API_BASE}/api/conversations/saved-views`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ name, filters }),
    });
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || 'Failed to save conversation view');
    }
    return response.json();
  },

  /**
   * Delete a saved conversation sidebar view.
   */
  async deleteConversationView(viewId) {
    const response = await fetch(`${API_BASE}/api/conversations/saved-views/${viewId}`, { method: 'DELETE' });
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || 'Failed to delete conversation view');
    }
    return response.json();
  },

  /**
   * Request local title suggestions from the stored conversation content.
   */
  async suggestConversationTitles(conversationId) {
    const response = await fetch(`${API_BASE}/api/conversations/${conversationId}/title-suggestions`, {
      method: 'POST',
    });
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || 'Failed to suggest titles');
    }
    return response.json();
  },

  /**
   * Download a conversation export.
   */
  async exportConversation(conversationId, format = 'markdown') {
    const params = new URLSearchParams({ format });
    const response = await fetch(`${API_BASE}/api/conversations/${conversationId}/export?${params.toString()}`);
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || 'Failed to export conversation');
    }

    const blob = await response.blob();
    const disposition = response.headers.get('Content-Disposition') || '';
    const filenameMatch = disposition.match(/filename="?([^";]+)"?/i);
    const filename = filenameMatch?.[1] || `conversation-${conversationId}.${format === 'json' ? 'json' : 'md'}`;
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
    return { filename };
  },
  /**
   * Update conversation title.
   * @param {string} conversationId - The conversation ID
   * @param {string} title - The new title
   * @param {{source?: string, locked?: boolean}} options - Optional title provenance metadata
   */
  async updateConversationTitle(conversationId, title, options = {}) {
    return this.updateConversation(conversationId, {
      title,
      ...(options.source ? { title_source: options.source } : {}),
      ...(options.locked !== undefined ? { title_locked: options.locked } : {}),
    });
  },

  /**
   * Delete a conversation.
   * @param {string} conversationId - The conversation ID
   */
  async deleteConversation(conversationId) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}`,
      {
        method: 'DELETE',
        headers: {
          'Content-Type': 'application/json',
        },
      }
    );

    if (!response.ok) {
      if (response.status === 404) {
        throw new Error('Conversation not found');
      }
      throw new Error('Failed to delete conversation');
    }

    return true;
  },

  /**
   * Send a message in a conversation.
   */
  async sendMessage(conversationId, content) {
    const controller = startAbortableRequest();

    try {
      const response = await fetch(
        `${API_BASE}/api/conversations/${conversationId}/message`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ content }),
          signal: controller.signal,
        }
      );
      if (!response.ok) {
        throw new Error('Failed to send message');
      }
      return response.json();
    } catch (error) {
      normalizeAbortError(error);
    } finally {
      finishAbortableRequest(controller);
    }
  },

  /**
   * Pin or unpin a message so it is considered durable context.
   */
  async setMessagePinned(conversationId, messageIndex, pinned) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/messages/${messageIndex}/pin`,
      {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ pinned }),
      }
    );
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || 'Failed to update message pin');
    }
    return response.json();
  },

  /**
   * Include or exclude a message from future model context.
   */
  async setMessageContextExcluded(conversationId, messageIndex, excluded) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/messages/${messageIndex}/context-visibility`,
      {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ excluded }),
      }
    );
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || 'Failed to update message context visibility');
    }
    return response.json();
  },

  /**
   * Retry a stored user message without appending a duplicate user turn.
   */
  async retryMessage(conversationId, messageIndex, mode = null, editedContent = null) {
    const controller = startAbortableRequest();
    const payload = { mode };
    if (editedContent !== null) {
      payload.edited_content = editedContent;
    }

    try {
      const response = await fetch(
        `${API_BASE}/api/conversations/${conversationId}/messages/${messageIndex}/retry`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(payload),
          signal: controller.signal,
        }
      );
      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(errorText || 'Failed to retry message');
      }
      return response.json();
    } catch (error) {
      normalizeAbortError(error);
    } finally {
      finishAbortableRequest(controller);
    }
  },

  /**
   * Send a quick message (single-model, no 3-stage council).
   */
  async sendQuickMessage(conversationId, content) {
    const controller = startAbortableRequest();

    try {
      const response = await fetch(
        `${API_BASE}/api/conversations/${conversationId}/quick`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ content }),
          signal: controller.signal,
        }
      );
      if (!response.ok) {
        throw new Error('Failed to send quick message');
      }
      return response.json();
    } catch (error) {
      normalizeAbortError(error);
    } finally {
      finishAbortableRequest(controller);
    }
  },

  /**
   * Send a quick message and receive streaming lifecycle updates.
   */
  async sendQuickMessageStream(conversationId, content, onEvent, abortController = null) {
    const controller = abortController || startAbortableRequest();
    currentAbortController = controller;

    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/quick/stream`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ content }),
        signal: controller.signal,
      }
    );

    if (!response.ok) {
      if (controller.signal.aborted) {
        throw new Error('Query stopped by user');
      }
      throw new Error('Failed to send quick message');
    }

    try {
      await readSSEEvents(response, onEvent, controller);
    } catch (error) {
      if (error.name === 'AbortError' || error.message === 'Query stopped by user') {
        console.debug('Quick stream aborted by user');
        throw new Error('Query stopped by user');
      }
      throw error;
    } finally {
      if (currentAbortController === controller) {
        currentAbortController = null;
      }
    }
  },

  /**
   * Send a message with file attachments (images/PDFs).
   * @param {string} conversationId - The conversation ID
   * @param {string} content - The text message content
   * @param {Array} files - Array of File objects to upload
   * @param {string} mode - Either 'council' or 'quick'
   * @returns {Promise<Object>} Response with stage1_results, stage2_results, stage3_result, metadata, file_metadata
   */
  async sendMessageWithFiles(conversationId, content, files, mode = 'council') {
    const controller = startAbortableRequest();
    const formData = new FormData();
    formData.append('content', content);
    formData.append('mode', mode);

    files.forEach(file => {
      formData.append('files', file.rawFile || file);
    });

    try {
      const response = await fetch(
        `${API_BASE}/api/conversations/${conversationId}/message/files`,
        {
          method: 'POST',
          body: formData,
          signal: controller.signal,
        }
      );

      if (!response.ok) {
        const errorText = await response.text();
        console.error('File upload failed:', {
          status: response.status,
          statusText: response.statusText,
          body: errorText,
        });
        throw new Error(`Failed to send message with files: ${response.status} ${response.statusText}`);
      }

      return response.json();
    } catch (error) {
      normalizeAbortError(error);
    } finally {
      finishAbortableRequest(controller);
    }
  },

  /**
   * Get the file queue for a conversation.
   * @param {string} conversationId - The conversation ID
   * @returns {Promise<Object>} Object with files array
   */
  async getFileQueue(conversationId) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/file_queue`
    );

    if (!response.ok) {
      throw new Error('Failed to get file queue');
    }

    return response.json();
  },

  /**
   * Update the file queue for a conversation.
   * @param {string} conversationId - The conversation ID
   * @param {Array} files - Array of file metadata objects
   * @returns {Promise<Object>} Success response
   */
  async updateFileQueue(conversationId, files) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/file_queue`,
      {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ files }),
      }
    );

    if (!response.ok) {
      throw new Error('Failed to update file queue');
    }

    return response.json();
  },

  /**
   * Get runtime LLM settings.
   */
  async getLLMSettings() {
    const response = await fetch(`${API_BASE}/api/settings/llm`);
    if (!response.ok) {
      throw new Error('Failed to get LLM settings');
    }
    return response.json();
  },

  /**
   * Update runtime LLM settings.
   */
  async updateLLMSettings(settings) {
    const response = await fetch(`${API_BASE}/api/settings/llm`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(settings),
    });
    if (!response.ok) {
      throw new Error('Failed to update LLM settings');
    }
    return response.json();
  },

  /**
   * Test a configured model connection.
   */
  async testLLMSettings(model) {
    const response = await fetch(`${API_BASE}/api/settings/llm/test`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ model }),
    });
    if (!response.ok) {
      throw new Error('Failed to test LLM settings');
    }
    return response.json();
  },

  /**
   * Send a message and receive streaming updates.
   * @param {string} conversationId - The conversation ID
   * @param {string} content - The message content
   * @param {function} onEvent - Callback function for each event: (eventType, data) => void
   * @param {AbortController} abortController - Optional AbortController to cancel the request
   * @returns {Promise<void>}
   */
  async sendMessageStream(conversationId, content, onEvent, abortController = null) {
    const controller = abortController || startAbortableRequest();
    currentAbortController = controller;

    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/message/stream`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ content }),
        signal: controller.signal,
      }
    );

    if (!response.ok) {
      if (controller.signal.aborted) {
        throw new Error('Query stopped by user');
      }
      throw new Error('Failed to send message');
    }

    try {
      await readSSEEvents(response, onEvent, controller);
    } catch (error) {
      if (error.name === 'AbortError' || error.message === 'Query stopped by user') {
        console.debug('Stream aborted by user');
        throw new Error('Query stopped by user');
      }
      throw error;
    } finally {
      if (currentAbortController === controller) {
        currentAbortController = null;
      }
    }
  },

  /**
   * Resume a persisted partial council response from its earliest missing stage.
   */
  async resumeMessageStream(conversationId, messageIndex, onEvent, abortController = null) {
    const controller = abortController || startAbortableRequest();
    currentAbortController = controller;

    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/messages/${messageIndex}/resume/stream`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        signal: controller.signal,
      }
    );

    if (!response.ok) {
      if (controller.signal.aborted) {
        throw new Error('Query stopped by user');
      }
      const errorText = await response.text();
      throw new Error(errorText || 'Failed to resume message');
    }

    try {
      await readSSEEvents(response, onEvent, controller);
    } catch (error) {
      if (error.name === 'AbortError' || error.message === 'Query stopped by user') {
        console.debug('Resume stream aborted by user');
        throw new Error('Query stopped by user');
      }
      throw error;
    } finally {
      if (currentAbortController === controller) {
        currentAbortController = null;
      }
    }
  },

  /**
   * Cancel the current streaming request.
   */
  cancelStream() {
    if (currentAbortController) {
      currentAbortController.abort();
      currentAbortController = null;
    }
  },

  /**
   * Check if there's an active stream.
   */
  isStreaming() {
    return currentAbortController !== null;
  },
};
