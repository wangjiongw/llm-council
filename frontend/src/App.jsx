import { useState, useEffect } from 'react';
import Sidebar from './components/Sidebar';
import ChatInterface from './components/ChatInterface';
import LLMSettingsModal from './components/LLMSettingsModal';
import { api } from './api';
import { processUploadedFiles } from './utils/fileUtils';
import './App.css';

const THEME_STORAGE_KEY = 'llm-council-theme';

function App() {
  const [conversations, setConversations] = useState([]);
  const [currentConversationId, setCurrentConversationId] = useState(null);
  const [currentConversation, setCurrentConversation] = useState(null);
  const [currentContextAudit, setCurrentContextAudit] = useState(null);
  const [currentContextPolicy, setCurrentContextPolicy] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [activeStreamId, setActiveStreamId] = useState(null);
  const [inFlightDraft, setInFlightDraft] = useState(null);
  const [draftToRestore, setDraftToRestore] = useState(null);
  const [attachedFiles, setAttachedFiles] = useState([]);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [theme, setTheme] = useState(() => localStorage.getItem(THEME_STORAGE_KEY) || 'light');

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  }, [theme]);

  const handleToggleTheme = () => {
    setTheme((currentTheme) => (currentTheme === 'dark' ? 'light' : 'dark'));
  };

  // Load conversations on mount
  useEffect(() => {
    (async () => {
      try {
        const convs = await api.listConversations();
        setConversations(convs);
      } catch (error) {
        console.error('Failed to load conversations:', error);
      }
    })();
  }, []);

  const loadConversationDetails = async (conversationId) => {
    if (!conversationId) {
      setCurrentConversation(null);
      setCurrentContextAudit(null);
      setCurrentContextPolicy(null);
      return;
    }

    try {
      const [conv, audit] = await Promise.all([
        api.getConversation(conversationId),
        api.getConversationContext(conversationId).catch((error) => {
          console.warn('Failed to load conversation context audit:', error);
          return null;
        }),
      ]);
      setCurrentConversation(conv);
      setCurrentContextAudit(audit);
      setCurrentContextPolicy(audit?.context_policy || conv.context_policy || null);
    } catch (error) {
      console.error('Failed to load conversation:', error);
    }
  };

  // Load conversation details when selected
  useEffect(() => {
    loadConversationDetails(currentConversationId);
  }, [currentConversationId]);

  const handleNewConversation = async () => {
    try {
      const newConv = await api.createConversation();
      setConversations([
        {
          id: newConv.id,
          created_at: newConv.created_at,
          message_count: 0,
          title: newConv.title || 'New Conversation'
        },
        ...conversations,
      ]);
      setCurrentConversationId(newConv.id);
      setAttachedFiles([]); // Clear file queue for new conversation
      setCurrentContextAudit(null);
      setCurrentContextPolicy(newConv.context_policy || null);
    } catch (error) {
      console.error('Failed to create conversation:', error);
    }
  };

  const handleSelectConversation = (id) => {
    setCurrentConversationId(id);
    setCurrentContextAudit(null);
    setCurrentContextPolicy(null);
    setAttachedFiles([]);
  };

  const handleUpdateTitle = async (conversationId, newTitle) => {
    try {
      // Update on backend
      await api.updateConversationTitle(conversationId, newTitle);

      // Update in conversations list
      setConversations(prevConversations =>
        prevConversations.map(conv =>
          conv.id === conversationId
            ? { ...conv, title: newTitle }
            : conv
        )
      );

      // Update current conversation if it's the active one
      if (currentConversation?.id === conversationId) {
        setCurrentConversation(prev => ({
          ...prev,
          title: newTitle
        }));
      }
    } catch (error) {
      console.error('Failed to update title:', error);
      alert('Failed to update title. Please try again.');
    }
  };

  const handleUpdateContextPolicy = async (policyUpdates) => {
    if (!currentConversationId) return;

    try {
      const response = await api.updateContextPolicy(currentConversationId, policyUpdates);
      const policy = response.context_policy;
      setCurrentContextPolicy(policy);
      setCurrentConversation(prev => prev ? { ...prev, context_policy: policy } : prev);
      setCurrentContextAudit(prev => prev ? { ...prev, context_policy: policy } : prev);
      await loadConversationDetails(currentConversationId);
    } catch (error) {
      console.error('Failed to update context policy:', error);
      alert('Failed to update context policy. Please try again.');
    }
  };

  const applyContextMemory = (contextMemory) => {
    setCurrentConversation(prev => prev ? { ...prev, context_memory: contextMemory } : prev);
    setCurrentContextAudit(prev => prev ? { ...prev, context_memory: contextMemory } : prev);
  };

  const handleAddContextMemory = async (content) => {
    if (!currentConversationId) return;

    try {
      const response = await api.addContextMemory(currentConversationId, content, true);
      applyContextMemory(response.context_memory || []);
      await loadConversationDetails(currentConversationId);
    } catch (error) {
      console.error('Failed to add context memory:', error);
      alert('Failed to add memory. Please try again.');
    }
  };

  const handleUpdateContextMemory = async (memoryId, updates) => {
    if (!currentConversationId) return;

    try {
      const response = await api.updateContextMemory(currentConversationId, memoryId, updates);
      applyContextMemory(response.context_memory || []);
      await loadConversationDetails(currentConversationId);
    } catch (error) {
      console.error('Failed to update context memory:', error);
      alert('Failed to update memory. Please try again.');
    }
  };

  const handleDeleteContextMemory = async (memoryId) => {
    if (!currentConversationId) return;

    try {
      const response = await api.deleteContextMemory(currentConversationId, memoryId);
      applyContextMemory(response.context_memory || []);
      await loadConversationDetails(currentConversationId);
    } catch (error) {
      console.error('Failed to delete context memory:', error);
      alert('Failed to delete memory. Please try again.');
    }
  };

  const handlePreviewContext = async (content, files, mode) => {
    if (!currentConversationId) return null;
    return api.previewConversationContext(currentConversationId, content, mode, files || []);
  };

  const handleSearchConversationHistory = async (query) => {
    const response = await api.searchConversationHistory(query, 20);
    return response.results || [];
  };


  const handleReplayMessageContext = async (messageIndex, mode = null) => {
    if (!currentConversationId) return null;
    return api.replayMessageContext(currentConversationId, messageIndex, mode);
  };

  const applyContextSummary = (summary) => {
    setCurrentConversation(prev => prev ? { ...prev, context_summary: summary } : prev);
    setCurrentContextAudit(prev => prev ? { ...prev, context_summary: summary } : prev);
  };

  const handleClearContextSummary = async () => {
    if (!currentConversationId) return;

    try {
      const response = await api.clearContextSummary(currentConversationId);
      applyContextSummary(response.context_summary);
      await loadConversationDetails(currentConversationId);
    } catch (error) {
      console.error('Failed to clear context summary:', error);
      alert('Failed to clear context summary. Please try again.');
    }
  };

  const handleRebuildContextSummary = async () => {
    if (!currentConversationId) return;

    try {
      const response = await api.rebuildContextSummary(currentConversationId);
      applyContextSummary(response.context_summary);
      await loadConversationDetails(currentConversationId);
    } catch (error) {
      console.error('Failed to rebuild context summary:', error);
      alert('Failed to rebuild context summary. Please try again.');
    }
  };

  const handleForkConversation = async (messageIndex) => {
    if (!currentConversationId || isLoading) return;

    try {
      const branch = await api.forkConversation(currentConversationId, messageIndex);
      setConversations(prevConversations => [
        {
          id: branch.id,
          created_at: branch.created_at,
          message_count: branch.messages?.length || 0,
          title: branch.title || 'Branched Conversation',
        },
        ...prevConversations,
      ]);
      setCurrentConversationId(branch.id);
      setCurrentConversation(branch);
      setCurrentContextAudit(null);
      setCurrentContextPolicy(branch.context_policy || null);
      setAttachedFiles([]);
    } catch (error) {
      console.error('Failed to branch conversation:', error);
      alert('Failed to branch conversation. Please try again.');
    }
  };

  const handleToggleMessagePin = async (messageIndex, pinned) => {
    if (!currentConversationId) return;

    try {
      const response = await api.setMessagePinned(currentConversationId, messageIndex, pinned);
      if (response.conversation) {
        setCurrentConversation(response.conversation);
      }
      await loadConversationDetails(currentConversationId);
    } catch (error) {
      console.error('Failed to update message pin:', error);
      alert('Failed to update message pin. Please try again.');
    }
  };

  const handleToggleMessageContextExcluded = async (messageIndex, excluded) => {
    if (!currentConversationId) return;

    try {
      const response = await api.setMessageContextExcluded(currentConversationId, messageIndex, excluded);
      if (response.conversation) {
        setCurrentConversation(response.conversation);
      }
      await loadConversationDetails(currentConversationId);
    } catch (error) {
      console.error('Failed to update message context visibility:', error);
      alert('Failed to update message context visibility. Please try again.');
    }
  };

  const handleDeleteConversation = async (conversationId) => {
    // Show confirmation dialog
    const confirmed = window.confirm(
      'Are you sure you want to delete this conversation? This action cannot be undone.'
    );

    if (!confirmed) {
      return;
    }

    try {
      // Delete on backend
      await api.deleteConversation(conversationId);

      // Remove from conversations list
      setConversations(prevConversations =>
        prevConversations.filter(conv => conv.id !== conversationId)
      );

      // If deleting active conversation, handle navigation
      if (currentConversationId === conversationId) {
        const remainingConversations = conversations.filter(
          conv => conv.id !== conversationId
        );

        if (remainingConversations.length > 0) {
          // Navigate to most recent conversation
          setCurrentConversationId(remainingConversations[0].id);
        } else {
          // No conversations left, create new one
          const newConv = await api.createConversation();
          setConversations([
            {
              id: newConv.id,
              created_at: newConv.created_at,
              message_count: 0,
              title: newConv.title || 'New Conversation'
            }
          ]);
          setCurrentConversationId(newConv.id);
        }
      }

      // Clear current conversation state if it was deleted
      if (currentConversation?.id === conversationId) {
        setCurrentConversation(null);
      }

    } catch (error) {
      console.error('Failed to delete conversation:', error);

      // Show user-friendly error message
      if (error.message === 'Conversation not found') {
        alert('Conversation not found. It may have already been deleted.');
        // Refresh conversation list to sync state
        loadConversations();
      } else {
        alert('Failed to delete conversation. Please try again.');
      }
    }
  };

  // Helper function to reload conversations list
  const loadConversations = async () => {
    try {
      const convs = await api.listConversations();
      setConversations(convs);
    } catch (error) {
      console.error('Failed to load conversations:', error);
    }
  };

  // File upload handler
  const handleFileUpload = async (newFiles) => {
    try {
      const processedFiles = await processUploadedFiles(newFiles, attachedFiles);
      setAttachedFiles(prev => [...prev, ...processedFiles]);
    } catch (error) {
      alert(error.message);
    }
  };

  const handleDeleteFile = (fileId) => {
    setAttachedFiles(attachedFiles.filter(f => f.id !== fileId));
  };

  const handleStopQuery = () => {
    const draft = inFlightDraft;

    api.cancelStream();
    setIsLoading(false);
    setActiveStreamId(null);
    setInFlightDraft(null);
    if (draft) {
      setDraftToRestore({
        ...draft,
        restoreId: `${draft.id}-stopped-${Date.now()}`,
      });
    }

    // Only brand-new turns have optimistic user/assistant messages to remove.
    // Resumed turns operate on persisted history and must remain visible.
    if (draft) {
      setCurrentConversation((prev) => {
        if (!prev?.messages) return prev;
        const messages = [...prev.messages];

        if (messages.length > 0 && messages[messages.length - 1].role === 'assistant') {
          messages.pop();
        }
        if (messages.length > 0 && messages[messages.length - 1].role === 'user') {
          messages.pop();
        }

        return { ...prev, messages };
      });
    }
  };

  const handleRetryLastQuery = async () => {
    if (!currentConversationId || !currentConversation?.messages || isLoading) return;

    const messages = [...currentConversation.messages];
    let lastUserMessage = null;
    let lastUserIndex = -1;

    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === 'user') {
        lastUserMessage = messages[i];
        lastUserIndex = i;
        break;
      }
    }

    if (!lastUserMessage || lastUserIndex < 0) {
      console.error('No user message found to retry');
      return;
    }

    const nextAssistant = messages.slice(lastUserIndex + 1).find(msg => msg.role === 'assistant');
    const retryMode = nextAssistant?.metadata?.mode === 'quick' ? 'quick' : 'council';

    setIsLoading(true);
    const requestId = `retry-${Date.now()}`;
    setActiveStreamId(requestId);
    setInFlightDraft(null);
    setDraftToRestore(null);

    setCurrentConversation((prev) => ({
      ...prev,
      messages: prev.messages.slice(0, lastUserIndex + 1),
    }));

    try {
      const response = await api.retryMessage(currentConversationId, lastUserIndex, retryMode);
      if (response.conversation) {
        setCurrentConversation(response.conversation);
      } else {
        setCurrentConversation((prev) => ({
          ...prev,
          messages: [
            ...prev.messages,
            {
              role: 'assistant',
              stage1: response.stage1_results,
              stage2: response.stage2_results,
              stage3: response.stage3_result,
              metadata: response.metadata,
            },
          ],
        }));
      }
      loadConversations();
      await loadConversationDetails(currentConversationId);
    } catch (error) {
      console.error('Failed to retry message:', error);
      await loadConversationDetails(currentConversationId);
    } finally {
      setIsLoading(false);
      setActiveStreamId(null);
      setInFlightDraft(null);
    }
  };

  const updateStreamingAssistant = (messageIndex, updater) => {
    setCurrentConversation((prev) => {
      if (!prev?.messages) return prev;
      const messages = [...prev.messages];
      const assistantIndex = typeof messageIndex === 'number' ? messageIndex : messages.length - 1;
      const lastMsg = messages[assistantIndex];
      if (!lastMsg || lastMsg.role !== 'assistant') {
        return prev;
      }

      messages[assistantIndex] = {
        ...lastMsg,
        loading: { ...(lastMsg.loading || {}) },
        modelStatus: { ...(lastMsg.modelStatus || {}) },
      };
      updater(messages[assistantIndex]);
      return { ...prev, messages };
    });
  };

  const applyModelStatusEvent = (event, messageIndex = null) => {
    updateStreamingAssistant(messageIndex, (lastMsg) => {
      if (!event.stage || !event.model) {
        return;
      }

      const currentModelStatus = lastMsg.modelStatus || {};
      const currentStageStatus = currentModelStatus[event.stage] || {};
      lastMsg.modelStatus = {
        ...currentModelStatus,
        [event.stage]: {
          ...currentStageStatus,
          [event.model]: {
            ...(currentStageStatus[event.model] || {}),
            model: event.model,
            status: event.status,
            error_type: event.error_type,
            error: event.error,
            duration_seconds: event.duration_seconds,
            first_event_seconds: event.first_event_seconds,
            streamed: event.streamed,
          },
        },
      };
    });
  };

  const handleCouncilStreamEvent = (eventType, event, messageIndex = null) => {
    if (
      eventType.startsWith('stage1_model_') ||
      eventType.startsWith('stage2_model_') ||
      eventType.startsWith('stage3_model_') ||
      eventType.startsWith('quick_model_')
    ) {
      applyModelStatusEvent(event, messageIndex);
      return;
    }

    switch (eventType) {
      case 'stage1_start':
        updateStreamingAssistant(messageIndex, (lastMsg) => {
          lastMsg.status = 'running';
          lastMsg.error = null;
          lastMsg.loading.stage1 = true;
        });
        break;

      case 'stage1_complete':
        updateStreamingAssistant(messageIndex, (lastMsg) => {
          lastMsg.stage1 = event.data;
          lastMsg.loading.stage1 = false;
        });
        break;

      case 'stage2_start':
        updateStreamingAssistant(messageIndex, (lastMsg) => {
          lastMsg.status = 'running';
          lastMsg.error = null;
          lastMsg.loading.stage2 = true;
        });
        break;

      case 'stage2_complete':
        updateStreamingAssistant(messageIndex, (lastMsg) => {
          lastMsg.stage2 = event.data;
          lastMsg.metadata = event.metadata;
          lastMsg.loading.stage2 = false;
        });
        break;

      case 'stage3_start':
        updateStreamingAssistant(messageIndex, (lastMsg) => {
          lastMsg.status = 'running';
          lastMsg.error = null;
          lastMsg.loading.stage3 = true;
        });
        break;

      case 'quick_start':
        updateStreamingAssistant(messageIndex, (lastMsg) => {
          lastMsg.status = 'running';
          lastMsg.error = null;
          lastMsg.metadata = { ...(lastMsg.metadata || {}), mode: 'quick' };
          lastMsg.loading.stage1 = false;
          lastMsg.loading.stage2 = false;
          lastMsg.loading.stage3 = true;
        });
        break;

      case 'quick_complete':
        updateStreamingAssistant(messageIndex, (lastMsg) => {
          lastMsg.status = 'complete';
          lastMsg.stage1 = [];
          lastMsg.stage2 = [];
          lastMsg.stage3 = event.data;
          lastMsg.metadata = event.metadata || { mode: 'quick' };
          lastMsg.loading.stage3 = false;
        });
        break;

      case 'stage3_complete':
        updateStreamingAssistant(messageIndex, (lastMsg) => {
          lastMsg.status = 'complete';
          lastMsg.stage3 = event.data;
          lastMsg.loading.stage3 = false;
        });
        break;

      case 'title_complete':
        // Reload conversations to get updated title
        loadConversations();
        break;

      case 'complete':
        // Stream complete, reload conversations list and persisted turn audit.
        loadConversations();
        loadConversationDetails(currentConversationId);
        setIsLoading(false);
        setActiveStreamId(null);
        setInFlightDraft(null);
        break;

      case 'error':
        console.error('Stream error:', event.message);
        updateStreamingAssistant(messageIndex, (lastMsg) => {
          lastMsg.status = 'failed';
          lastMsg.error = event.message;
          lastMsg.loading.stage1 = false;
          lastMsg.loading.stage2 = false;
          lastMsg.loading.stage3 = false;
        });
        loadConversationDetails(currentConversationId);
        setIsLoading(false);
        setActiveStreamId(null);
        setInFlightDraft(null);
        break;

      default:
        console.log('Unknown event type:', eventType);
    }
  };

  const handleSendMessage = async (content, files = attachedFiles) => {
    if (!currentConversationId) return;

    const hasFiles = files.length > 0;
    setIsLoading(true);
    const streamId = Date.now().toString(); // Unique ID for this stream
    setActiveStreamId(streamId);
    setInFlightDraft({
      id: streamId,
      content,
      hasFiles,
    });
    setDraftToRestore(null);

    try {
      // Extract file metadata for UI display
      const fileMetadata = files.map(f => ({
        id: f.id,
        name: f.name,
        type: f.type,
        size: f.size,
        category: f.category
      }));

      // Optimistically add user message to UI (with file metadata)
      const userMessage = {
        role: 'user',
        content,
        ...(fileMetadata.length > 0 && { files: fileMetadata })
      };
      setCurrentConversation((prev) => ({
        ...prev,
        messages: [...prev.messages, userMessage],
      }));

      // Send message with streaming (or file upload if files present)
      if (hasFiles) {
        // Use file upload endpoint (non-streaming)
        const response = await api.sendMessageWithFiles(currentConversationId, content, files, 'council');

        // Add assistant response
        setCurrentConversation((prev) => ({
          ...prev,
          messages: [
            ...prev.messages,
            {
              role: 'assistant',
              stage1: response.stage1_results,
              stage2: response.stage2_results,
              stage3: response.stage3_result,
              metadata: response.metadata,
            },
          ],
        }));

        // Files are one-shot browser File objects. Sent file metadata stays on
        // the message; the pending queue is cleared after success.
        setAttachedFiles([]);

        // Reload conversations list and persisted turn audit.
        loadConversations();
        await loadConversationDetails(currentConversationId);
        setIsLoading(false);
        setActiveStreamId(null);
        setInFlightDraft(null);
      } else {
        // Create a partial assistant message that will be updated progressively
        const assistantMessage = {
          role: 'assistant',
          stage1: null,
          stage2: null,
          stage3: null,
          metadata: null,
          modelStatus: {
            stage1: {},
            stage2: {},
            stage3: {},
          },
          loading: {
            stage1: false,
            stage2: false,
            stage3: false,
          },
        };

        // Add the partial assistant message
        setCurrentConversation((prev) => ({
          ...prev,
          messages: [...prev.messages, assistantMessage],
        }));

        // Use streaming endpoint for text-only messages
        await api.sendMessageStream(currentConversationId, content, (eventType, event) => {
          handleCouncilStreamEvent(eventType, event);
        });
      }
    } catch (error) {
      console.error('Failed to send message:', error);

      // Check if it was a user cancellation
      if (error.message === 'Query stopped by user') {
        // Already handled in handleStopQuery
        return;
      }

      // Remove optimistic messages on error
      setCurrentConversation((prev) => ({
        ...prev,
        messages: prev.messages.slice(0, hasFiles ? -1 : -2),
      }));
      setIsLoading(false);
      setActiveStreamId(null);
      setInFlightDraft(null);
    }
  };

  const handleResumeSavedStages = async (messageIndex) => {
    if (!currentConversationId || isLoading) return;

    setIsLoading(true);
    const requestId = `resume-${Date.now()}`;
    setActiveStreamId(requestId);
    setInFlightDraft(null);
    setDraftToRestore(null);
    updateStreamingAssistant(messageIndex, (lastMsg) => {
      lastMsg.status = 'running';
      lastMsg.error = null;
      lastMsg.loading.stage1 = false;
      lastMsg.loading.stage2 = false;
      lastMsg.loading.stage3 = false;
    });

    try {
      await api.resumeMessageStream(currentConversationId, messageIndex, (eventType, event) => {
        handleCouncilStreamEvent(eventType, event, messageIndex);
      });
    } catch (error) {
      console.error('Failed to resume saved council stages:', error);

      if (error.message !== 'Query stopped by user') {
        updateStreamingAssistant(messageIndex, (lastMsg) => {
          lastMsg.status = 'failed';
          lastMsg.error = error.message;
          lastMsg.loading.stage1 = false;
          lastMsg.loading.stage2 = false;
          lastMsg.loading.stage3 = false;
        });
      }
    } finally {
      await loadConversationDetails(currentConversationId);
      setIsLoading(false);
      setActiveStreamId(null);
      setInFlightDraft(null);
    }
  };

  const handleSendQuickMessage = async (content, files = attachedFiles) => {
    if (!currentConversationId) return;

    setIsLoading(true);
    const requestId = Date.now().toString();
    setActiveStreamId(requestId);
    setInFlightDraft({
      id: requestId,
      content,
      hasFiles: files.length > 0,
    });
    setDraftToRestore(null);

    try {
      // Extract file metadata for UI display
      const fileMetadata = files.map(f => ({
        id: f.id,
        name: f.name,
        type: f.type,
        size: f.size,
        category: f.category
      }));

      // Optimistically add user message to UI
      const userMessage = {
        role: 'user',
        content,
        ...(fileMetadata.length > 0 && { files: fileMetadata })
      };
      setCurrentConversation((prev) => ({
        ...prev,
        messages: [...prev.messages, userMessage],
      }));

      if (files.length > 0) {
        const response = await api.sendMessageWithFiles(currentConversationId, content, files, 'quick');

        // Add assistant response in quick-compatible stage3 format
        setCurrentConversation((prev) => ({
          ...prev,
          messages: [
            ...prev.messages,
            {
              role: 'assistant',
              stage1: response.stage1_results,
              stage2: response.stage2_results,
              stage3: response.stage3_result,
              metadata: response.metadata,
            },
          ],
        }));

        // Files are one-shot browser File objects. Sent file metadata stays on
        // the message; the pending queue is cleared after success.
        setAttachedFiles([]);
      } else {
        const assistantMessage = {
          role: 'assistant',
          status: 'running',
          stage1: [],
          stage2: [],
          stage3: null,
          metadata: { mode: 'quick' },
          modelStatus: {
            stage1: {},
            stage2: {},
            stage3: {},
          },
          loading: {
            stage1: false,
            stage2: false,
            stage3: true,
          },
        };

        setCurrentConversation((prev) => ({
          ...prev,
          messages: [...prev.messages, assistantMessage],
        }));

        // No files, use quick streaming endpoint
        await api.sendQuickMessageStream(currentConversationId, content, (eventType, event) => {
          handleCouncilStreamEvent(eventType, event);
        });
      }

      // Reload conversations list and persisted turn audit.
      loadConversations();
      await loadConversationDetails(currentConversationId);
    } catch (error) {
      console.error('Failed to send quick message:', error);

      if (error.message === 'Query stopped by user') {
        return;
      }

      if (files.length > 0) {
        setCurrentConversation((prev) => ({
          ...prev,
          messages: prev.messages.slice(0, -1),
        }));
      } else {
        updateStreamingAssistant(null, (lastMsg) => {
          lastMsg.status = 'failed';
          lastMsg.error = error.message;
          lastMsg.stage1 = [];
          lastMsg.stage2 = [];
          lastMsg.stage3 = {
            model: 'quick',
            status: 'failed',
            response: `Error: ${error.message}`,
            error_type: 'quick_stream_error',
            error: error.message,
          };
          lastMsg.metadata = { ...(lastMsg.metadata || {}), mode: 'quick' };
          lastMsg.loading.stage1 = false;
          lastMsg.loading.stage2 = false;
          lastMsg.loading.stage3 = false;
        });
      }
    } finally {
      setIsLoading(false);
      setActiveStreamId(null);
      setInFlightDraft(null);
    }
  };

  return (
    <div className="app">
      <Sidebar
        conversations={conversations}
        currentConversationId={currentConversationId}
        onSelectConversation={handleSelectConversation}
        onNewConversation={handleNewConversation}
        onUpdateTitle={handleUpdateTitle}
        onDeleteConversation={handleDeleteConversation}
        onOpenSettings={() => setSettingsOpen(true)}
        theme={theme}
        onToggleTheme={handleToggleTheme}
      />
      <ChatInterface
        conversation={currentConversation}
        contextAudit={currentContextAudit}
        contextPolicy={currentContextPolicy}
        onUpdateContextPolicy={handleUpdateContextPolicy}
        onAddContextMemory={handleAddContextMemory}
        onUpdateContextMemory={handleUpdateContextMemory}
        onDeleteContextMemory={handleDeleteContextMemory}
        onSearchConversationHistory={handleSearchConversationHistory}
        onPreviewContext={handlePreviewContext}
        onReplayMessageContext={handleReplayMessageContext}
        onClearContextSummary={handleClearContextSummary}
        onRebuildContextSummary={handleRebuildContextSummary}
        onSendMessage={handleSendMessage}
        onSendQuickMessage={handleSendQuickMessage}
        onStopQuery={handleStopQuery}
        onRetryQuery={handleRetryLastQuery}
        onResumeQuery={handleResumeSavedStages}
        onToggleMessagePin={handleToggleMessagePin}
        onToggleMessageContextExcluded={handleToggleMessageContextExcluded}
        onForkConversation={handleForkConversation}
        isLoading={isLoading}
        activeStreamId={activeStreamId}
        attachedFiles={attachedFiles}
        onFilesChange={setAttachedFiles}
        onFileUpload={handleFileUpload}
        onDeleteFile={handleDeleteFile}
        draftToRestore={draftToRestore}
        onDraftRestored={() => setDraftToRestore(null)}
      />
      <LLMSettingsModal
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        api={api}
      />
    </div>
  );
}

export default App;
