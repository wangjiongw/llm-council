import { useState, useEffect } from 'react';
import Sidebar from './components/Sidebar';
import ChatInterface from './components/ChatInterface';
import { api } from './api';
import './App.css';

function App() {
  const [conversations, setConversations] = useState([]);
  const [currentConversationId, setCurrentConversationId] = useState(null);
  const [currentConversation, setCurrentConversation] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [activeStreamId, setActiveStreamId] = useState(null);

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
        { id: newConv.id, created_at: newConv.created_at, message_count: 0 },
        ...conversations,
      ]);
      setCurrentConversationId(newConv.id);
    } catch (error) {
      console.error('Failed to create conversation:', error);
    }
  };

  const handleSelectConversation = (id) => {
    setCurrentConversationId(id);
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

  const handleStopQuery = () => {
    api.cancelStream();
    setIsLoading(false);
    setActiveStreamId(null);

    // Remove optimistic assistant message
    setCurrentConversation((prev) => {
      const messages = [...prev.messages];
      if (messages.length > 0 && messages[messages.length - 1].role === 'assistant') {
        return {
          ...prev,
          messages: messages.slice(0, -1)
        };
      }
      return prev;
    });
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

  const handleSendMessage = async (content) => {
    if (!currentConversationId) return;

    setIsLoading(true);
    const streamId = Date.now().toString(); // Unique ID for this stream
    setActiveStreamId(streamId);

    try {
      // Optimistically add user message to UI
      const userMessage = { role: 'user', content };
      setCurrentConversation((prev) => ({
        ...prev,
        messages: [...prev.messages, userMessage],
      }));

      // Create a partial assistant message that will be updated progressively
      const assistantMessage = {
        role: 'assistant',
        stage1: null,
        stage2: null,
        stage3: null,
        metadata: null,
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

      // Send message with streaming
      await api.sendMessageStream(currentConversationId, content, (eventType, event) => {
        switch (eventType) {
          case 'stage1_start':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.loading.stage1 = true;
              return { ...prev, messages };
            });
            break;

          case 'stage1_complete':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.stage1 = event.data;
              lastMsg.loading.stage1 = false;
              return { ...prev, messages };
            });
            break;

          case 'stage2_start':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.loading.stage2 = true;
              return { ...prev, messages };
            });
            break;

          case 'stage2_complete':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.stage2 = event.data;
              lastMsg.metadata = event.metadata;
              lastMsg.loading.stage2 = false;
              return { ...prev, messages };
            });
            break;

          case 'stage3_start':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.loading.stage3 = true;
              return { ...prev, messages };
            });
            break;

          case 'stage3_complete':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.stage3 = event.data;
              lastMsg.loading.stage3 = false;
              return { ...prev, messages };
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
            break;

          case 'error':
            console.error('Stream error:', event.message);
            setIsLoading(false);
            setActiveStreamId(null);
            break;

          default:
            console.log('Unknown event type:', eventType);
        }
      });
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
        messages: prev.messages.slice(0, -2),
      }));
      setIsLoading(false);
      setActiveStreamId(null);
    }
  };

  return (
    <div className="app">
      <Sidebar
        conversations={conversations}
        currentConversationId={currentConversationId}
        onSelectConversation={handleSelectConversation}
        onNewConversation={handleNewConversation}
      />
      <ChatInterface
        conversation={currentConversation}
        onSendMessage={handleSendMessage}
        onStopQuery={handleStopQuery}
        onRetryQuery={handleRetryLastQuery}
        isLoading={isLoading}
        activeStreamId={activeStreamId}
      />
    </div>
  );
}

export default App;
