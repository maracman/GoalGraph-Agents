import React, { createContext, useState, useEffect, useContext, useRef, useCallback } from 'react';
import { 
  fetchSessionId, 
  checkSession, 
  fetchPastChats, 
  submitMessage, 
  generateResponse, 
  interruptTask,
  resetChat,
  createNewChat,
  duplicateChat as duplicateChatAPI,
  deleteChat as deleteChatAPI,
  loadChat
} from '../services/api';

// Create context
const SessionContext = createContext();

export const SessionProvider = ({ children, initialSessionId }) => {
  // Session state
  const [sessionId, setSessionId] = useState(initialSessionId || null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  
  // Session data
  const [sessionState, setSessionState] = useState({
    history: [],
    settings: {},
    agentData: [],
    isPlaying: false,
    isUser: false,
    userMessage: '',
    maxGenerations: 0,
    currentGeneration: 0
  });
  
  // UI state
  const [pastChats, setPastChats] = useState([]);

  // Cancellation ref for the generation loop
  const generationCancelledRef = useRef(false);
  
  // Initialize session — only on first mount
  // Chat switching is handled by switchToChat, which updates state directly.
  const initializedRef = useRef(false);
  useEffect(() => {
    if (initializedRef.current) return;
    initializedRef.current = true;

    const initializeSession = async () => {
      try {
        setLoading(true);

        // If no session ID is provided, fetch one
        let currentSessionId = sessionId;
        if (!currentSessionId) {
          currentSessionId = await fetchSessionId();
          setSessionId(currentSessionId);
        }

        // Get session state
        const sessionData = await checkSession();
        if (sessionData.session_contents) {
          setSessionState(prevState => ({
            ...prevState,
            isUser: sessionData.session_contents.is_user || false,
            isPlaying: sessionData.session_contents.play || false,
            history: sessionData.session_contents.session_history || [],
            settings: sessionData.session_contents.settings || {},
            agentData: sessionData.session_contents.agents_df || [],
            chat_mode: sessionData.session_contents.chat_mode || 'you_agent'
          }));
        }

        // Load past chats
        loadPastChats();

        setError(null);
      } catch (err) {
        console.error("Error initializing session:", err);
        setError("Failed to initialize session");
      } finally {
        setLoading(false);
      }
    };

    initializeSession();
  }, []);
  
  // Load past chats — memoized to prevent infinite re-render loops
  const loadPastChats = useCallback(async () => {
    try {
      const chatsData = await fetchPastChats();
      setPastChats(chatsData.pastChats || []);
    } catch (err) {
      console.error("Error loading past chats:", err);
    }
  }, []);
  
  // Handle user message submission
  const handleSubmitMessage = async (message, isUser = true) => {
    try {
      // If playing, interrupt generation
      if (sessionState.isPlaying) {
        await interruptTask();
        setSessionState(prev => ({ ...prev, isPlaying: false }));
        return { success: true };
      }
      
      // Don't submit empty messages
      if (!message.trim() && !sessionState.isUser) {
        return { success: false, error: "Message cannot be empty" };
      }
      
      const response = await submitMessage(message, isUser);
      
      if (response.success) {
        setSessionState(prev => ({
          ...prev,
          history: response.history,
          maxGenerations: response.max_generations,
          isPlaying: response.play,
          currentGeneration: 0,
          isUser: false
        }));
        
        // Start generation if play is true
        if (response.play) {
          generateAgentResponses();
        }
        
        return { success: true };
      } else {
        return { success: false, error: response.error || "Failed to submit message" };
      }
    } catch (err) {
      console.error("Error submitting message:", err);
      return { success: false, error: err.message || "Failed to submit message" };
    }
  };
  
  // Stop any running generation
  const stopGeneration = async () => {
    generationCancelledRef.current = true;
    try {
      await interruptTask();
    } catch (e) {
      // ignore
    }
    setSessionState(prev => ({ ...prev, isPlaying: false }));
  };

  // Generate agent responses
  const generateAgentResponses = async () => {
    generationCancelledRef.current = false;
    try {
      let keepGoing = true;
      while (keepGoing) {
        // Check cancellation before each request
        if (generationCancelledRef.current) {
          setSessionState(prev => ({ ...prev, isPlaying: false }));
          break;
        }

        const response = await generateResponse();

        // Check cancellation after each request
        if (generationCancelledRef.current) {
          setSessionState(prev => ({ ...prev, isPlaying: false }));
          break;
        }

        if (response.error) {
          console.error("Generation error:", response.error);
          setSessionState(prev => ({ ...prev, isPlaying: false }));
          break;
        }

        if (response.complete) {
          setSessionState(prev => ({ ...prev, isPlaying: false }));
          break;
        }

        keepGoing = response.play === true;

        setSessionState(prev => ({
          ...prev,
          history: response.history || prev.history,
          isPlaying: keepGoing,
          currentGeneration: response.current_generation,
          maxGenerations: response.max_generations
        }));

        if (!keepGoing) {
          break;
        }

        await new Promise(resolve => setTimeout(resolve, 100));
      }
    } catch (err) {
      console.error("Error generating responses:", err);
      setSessionState(prev => ({ ...prev, isPlaying: false }));
    }
  };
  
  // Reset the current chat
  const resetCurrentChat = async () => {
    try {
      const response = await resetChat();
      if (response.success) {
        setSessionState(prev => ({
          ...prev,
          history: [],
          isPlaying: false,
          isUser: false,
          currentGeneration: 0,
          maxGenerations: 0
        }));
        return { success: true };
      } else {
        return { success: false, error: response.error || "Failed to reset chat" };
      }
    } catch (err) {
      console.error("Error resetting chat:", err);
      return { success: false, error: err.message || "Failed to reset chat" };
    }
  };
  
  // Create new chat
  const createNewChatSession = async () => {
    try {
      const response = await createNewChat();
      if (response.success) {
        setSessionId(response.session_id);
        setSessionState(prev => ({
          ...prev,
          history: [],
          isPlaying: false,
          isUser: false,
          currentGeneration: 0,
          maxGenerations: 0
        }));
        await loadPastChats();
        return { success: true, redirect: response.redirect_to };
      } else {
        return { success: false, error: response.error || "Failed to create new chat" };
      }
    } catch (err) {
      console.error("Error creating new chat:", err);
      return { success: false, error: err.message || "Failed to create new chat" };
    }
  };
  
  // Duplicate chat
  const duplicateChat = async () => {
    try {
      const response = await duplicateChatAPI();
      if (response.success) {
        setSessionId(response.new_session_id);
        await loadPastChats();
        return { success: true };
      } else {
        return { success: false, error: response.error || "Failed to duplicate chat" };
      }
    } catch (err) {
      console.error("Error duplicating chat:", err);
      return { success: false, error: err.message || "Failed to duplicate chat" };
    }
  };
  
  // Delete chat
  const deleteChat = async () => {
    try {
      const response = await deleteChatAPI();
      if (response.success) {
        setSessionId(response.session_id);
        setSessionState(prev => ({
          ...prev,
          history: [],
          isPlaying: false,
          isUser: false,
          currentGeneration: 0,
          maxGenerations: 0
        }));
        await loadPastChats();
        return { success: true, redirect: response.redirect_to };
      } else {
        return { success: false, error: response.error || "Failed to delete chat" };
      }
    } catch (err) {
      console.error("Error deleting chat:", err);
      return { success: false, error: err.message || "Failed to delete chat" };
    }
  };
  
  // Switch to a past chat
  const switchToChat = async (chatId) => {
    try {
      // Stop any running generation first
      await stopGeneration();

      const response = await loadChat(chatId);
      if (response.error || !response.success) {
        return { success: false, error: response.error || 'Failed to load chat' };
      }
      setSessionId(chatId);
      setSessionState(prev => ({
        ...prev,
        history: response.history || [],
        settings: response.settings || prev.settings,
        agentData: response.agents_df || prev.agentData,
        chat_mode: response.chat_mode || prev.chat_mode || 'you_agent',
        isPlaying: false,
        isUser: false,
        currentGeneration: 0,
        maxGenerations: 0
      }));
      // Update past chats list and mark the new chat as current locally
      // (avoids relying on the server session cookie roundtrip timing)
      setPastChats(prev => prev.map(chat => ({
        ...chat,
        is_current: chat.id === chatId
      })));
      // Also refresh from server for full accuracy
      loadPastChats();
      return { success: true };
    } catch (err) {
      console.error("Error switching chat:", err);
      return { success: false, error: err.message || "Failed to load chat" };
    }
  };

  // Update session settings
  const updateSessionSettings = (newSettings) => {
    setSessionState(prev => ({
      ...prev,
      settings: {
        ...prev.settings,
        ...newSettings
      }
    }));
  };
  
  // Value to be provided by the context
  const value = {
    sessionId,
    setSessionId,
    sessionState,
    setSessionState,
    pastChats,
    loading,
    error,
    loadPastChats,
    handleSubmitMessage,
    resetCurrentChat,
    createNewChatSession,
    duplicateChat,
    deleteChat,
    switchToChat,
    stopGeneration,
    updateSessionSettings
  };
  
  return (
    <SessionContext.Provider value={value}>
      {children}
    </SessionContext.Provider>
  );
};

// Custom hook for using the session context
export const useSession = () => {
  const context = useContext(SessionContext);
  if (!context) {
    throw new Error('useSession must be used within a SessionProvider');
  }
  return context;
};

export default SessionContext;