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
   * Update conversation title.
   * @param {string} conversationId - The conversation ID
   * @param {string} title - The new title
   */
  async updateConversationTitle(conversationId, title) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}`,
      {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ title }),
      }
    );
    if (!response.ok) {
      throw new Error('Failed to update conversation title');
    }
    return response.json();
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
        console.log('Quick stream aborted by user');
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
        console.log('Stream aborted by user');
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
        console.log('Resume stream aborted by user');
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
