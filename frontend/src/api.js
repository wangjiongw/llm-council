/**
 * API client for the LLM Council backend.
 */

const API_BASE = 'http://localhost:8001';

let currentAbortController = null;

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
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/message`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ content }),
      }
    );
    if (!response.ok) {
      throw new Error('Failed to send message');
    }
    return response.json();
  },

  /**
   * Send a quick message (single-model, no 3-stage council).
   */
  async sendQuickMessage(conversationId, content) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/quick`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ content }),
      }
    );
    if (!response.ok) {
      throw new Error('Failed to send quick message');
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
    const controller = abortController || new AbortController();
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

    const reader = response.body.getReader();
    const decoder = new TextDecoder();

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        if (controller.signal.aborted) {
          throw new Error('Query stopped by user');
        }

        const chunk = decoder.decode(value);
        const lines = chunk.split('\n');

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6);
            try {
              const event = JSON.parse(data);
              onEvent(event.type, event);
            } catch (e) {
              console.error('Failed to parse SSE event:', e);
            }
          }
        }
      }
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
