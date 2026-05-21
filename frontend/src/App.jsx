import { useState, useEffect } from 'react';
import Sidebar from './components/Sidebar';
import ChatInterface from './components/ChatInterface';
import LLMSettingsModal from './components/LLMSettingsModal';
import { api } from './api';
import './App.css';

function App() {
  const [conversations, setConversations] = useState([]);
  const [currentConversationId, setCurrentConversationId] = useState(null);
  const [currentConversation, setCurrentConversation] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [activeStreamId, setActiveStreamId] = useState(null);
  const [inFlightDraft, setInFlightDraft] = useState(null);
  const [draftToRestore, setDraftToRestore] = useState(null);
  const [attachedFiles, setAttachedFiles] = useState([]);
  const [settingsOpen, setSettingsOpen] = useState(false);

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

  // Load conversation details when selected
  useEffect(() => {
    (async () => {
      if (currentConversationId) {
        try {
          const conv = await api.getConversation(currentConversationId);
          setCurrentConversation(conv);
        } catch (error) {
          console.error('Failed to load conversation:', error);
        }
      }
    })();
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
    } catch (error) {
      console.error('Failed to create conversation:', error);
    }
  };

  const handleSelectConversation = async (id) => {
    setCurrentConversationId(id);

    // Load file queue for this conversation
    try {
      const fileQueueData = await api.getFileQueue(id);
      setAttachedFiles(fileQueueData.files || []);
    } catch (error) {
      console.error('Failed to load file queue:', error);
      setAttachedFiles([]);
    }
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
    const { processUploadedFiles } = await import('./utils/fileUtils');
    try {
      const processedFiles = await processUploadedFiles(newFiles, attachedFiles);
      setAttachedFiles(prev => [...prev, ...processedFiles]);
    } catch (error) {
      alert(error.message);
    }
  };

  // File delete handler with backend sync
  const handleDeleteFile = async (fileId) => {
    const updatedFiles = attachedFiles.filter(f => f.id !== fileId);
    setAttachedFiles(updatedFiles);

    // Sync to backend if we have a current conversation
    if (currentConversationId) {
      try {
        await api.updateFileQueue(currentConversationId, updatedFiles);
      } catch (error) {
        console.error('Failed to update file queue on backend:', error);
      }
    }
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

  const handleRetryLastQuery = () => {
    if (!currentConversation || !currentConversation.messages) return;

    // Find the last user message
    const messages = [...currentConversation.messages];
    let lastUserMessage = null;

    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === 'user') {
        lastUserMessage = messages[i];
        break;
      }
    }

    if (!lastUserMessage) {
      console.error('No user message found to retry');
      return;
    }

    // Remove the last assistant message (if it exists)
    const lastMessage = messages[messages.length - 1];
    let updatedMessages = [...messages];

    if (lastMessage && lastMessage.role === 'assistant') {
      // Remove the last assistant message
      updatedMessages = updatedMessages.slice(0, -1);
    }

    // Update the conversation state without the assistant message
    setCurrentConversation((prev) => ({
      ...prev,
      messages: updatedMessages
    }));

    // Send the last user message again
    handleSendMessage(lastUserMessage.content);
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
      eventType.startsWith('stage3_model_')
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
        // Stream complete, reload conversations list
        loadConversations();
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
        const response = await api.sendMessageWithFiles(currentConversationId, content, files);

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
        setAttachedFiles(response.file_queue || []);

        // Reload conversations list
        loadConversations();
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
        // Files present, use file upload endpoint (runs full council)
        const response = await api.sendMessageWithFiles(currentConversationId, content, files);

        // Add assistant response (full council format)
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
        setAttachedFiles(response.file_queue || []);
      } else {
        // No files, use quick endpoint
        const response = await api.sendQuickMessage(currentConversationId, content);

        // Add assistant response (quick format)
        setCurrentConversation((prev) => ({
          ...prev,
          messages: [
            ...prev.messages,
            {
              role: 'assistant',
              stage1: null,
              stage2: null,
              stage3: response.quick,
              metadata: null,
            },
          ],
        }));
      }

      // Reload conversations list
      loadConversations();
    } catch (error) {
      console.error('Failed to send quick message:', error);

      if (error.message === 'Query stopped by user') {
        return;
      }

      // Remove optimistic messages on error
      setCurrentConversation((prev) => ({
        ...prev,
        messages: prev.messages.slice(0, -1),
      }));
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
      />
      <ChatInterface
        conversation={currentConversation}
        onSendMessage={handleSendMessage}
        onSendQuickMessage={handleSendQuickMessage}
        onStopQuery={handleStopQuery}
        onRetryQuery={handleRetryLastQuery}
        onResumeQuery={handleResumeSavedStages}
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
