import React, { useState, useRef, useEffect } from 'react';
import { Send, Play, Pause, ChevronDown, PlusCircle, RefreshCw, Copy, Trash } from 'lucide-react';
import { submitMessage, generateResponse, interruptTask } from '../services/api';
import { useSession } from '../contexts/SessionContext';

const ChatInterface = () => {
  const { sessionId, sessionState, setSessionState } = useSession();
  const [userMessage, setUserMessage] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const chatBoxRef = useRef(null);
  
  useEffect(() => {
    // Scroll to bottom of chat when history changes
    if (chatBoxRef.current) {
      chatBoxRef.current.scrollTop = chatBoxRef.current.scrollHeight;
    }
  }, [sessionState.history]);
  
  const handleSubmit = async (e) => {
    e.preventDefault();
    
    if (sessionState.isPlaying) {
      // If playing, interrupt the generation
      await interruptTask();
      setSessionState(prev => ({ ...prev, isPlaying: false }));
      return;
    }
    
    if (!userMessage.trim() && !sessionState.isUser) {
      // Don't submit empty messages
      return;
    }
    
    try {
      setIsSubmitting(true);
      
      const response = await submitMessage(userMessage, true);
      if (response.success) {
        setSessionState(prev => ({
          ...prev,
          history: response.history,
          maxGenerations: response.max_generations,
          isPlaying: response.play,
          currentGeneration: 0,
          isUser: false
        }));
        
        setUserMessage('');
        
        // Start generation if play is true
        if (response.play) {
          generateAgentResponses();
        }
      }
    } catch (error) {
      console.error("Error submitting message:", error);
    } finally {
      setIsSubmitting(false);
    }
  };
  
  const generateAgentResponses = async () => {
    try {
      let keepGoing = true;
      while (keepGoing) {
        const response = await generateResponse();

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

        // Small delay to avoid hammering the server
        await new Promise(resolve => setTimeout(resolve, 100));
      }
    } catch (error) {
      console.error("Error generating responses:", error);
      setSessionState(prev => ({ ...prev, isPlaying: false }));
    }
  };
  
  const toggleDropdown = () => {
    setDropdownOpen(!dropdownOpen);
  };
  
  const createNewChat = async () => {
    // Implement create new chat functionality
    setDropdownOpen(false);
  };
  
  const duplicateChat = async () => {
    // Implement duplicate chat functionality
    setDropdownOpen(false);
  };
  
  const resetChat = async () => {
    // Implement reset chat functionality
    setDropdownOpen(false);
  };
  
  const deleteChat = async () => {
    // Implement delete chat functionality
    setDropdownOpen(false);
  };
  
  return (
    <div className="chat-container">
      <div className="chat-header">
        <div className="chat-title">
          <span>Conversation</span>
          <div className="dropdown">
            <button className="dropdown-toggle" onClick={toggleDropdown}>
              <ChevronDown size={18} />
            </button>
            {dropdownOpen && (
              <div className="dropdown-content">
                <button onClick={createNewChat}>
                  <PlusCircle size={16} />
                  <span>Create New Chat</span>
                </button>
                <button onClick={duplicateChat}>
                  <Copy size={16} />
                  <span>Duplicate Chat</span>
                </button>
                <button onClick={resetChat}>
                  <RefreshCw size={16} />
                  <span>Restart Chat</span>
                </button>
                <button onClick={deleteChat}>
                  <Trash size={16} />
                  <span>Delete Chat</span>
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
      
      <div className="chat-box-body" ref={chatBoxRef}>
        {sessionState.history.map((message, index) => (
          <div 
            key={index} 
            className={`message ${message[0] === 'user' ? 'user' : 'agent'}`}
          >
            <div className="message-content">
              <div className="message-header">
                <strong>{message[0] === 'user' ? 'You' : message[0]}</strong>
              </div>
              <div className="message-text">{message[1]}</div>
            </div>
          </div>
        ))}
        
        {sessionState.currentGeneration > 0 && sessionState.isPlaying && (
          <div className="generation-progress">
            <div className="progress-bar">
              <div 
                className="progress-fill" 
                style={{ width: `${(sessionState.currentGeneration / sessionState.maxGenerations) * 100}%` }}
              ></div>
            </div>
            <div className="progress-text">
              Generating: {sessionState.currentGeneration} / {sessionState.maxGenerations}
            </div>
          </div>
        )}
      </div>
      
      <form className="chat-box-footer" onSubmit={handleSubmit}>
        <input
          type="text"
          value={userMessage}
          onChange={(e) => setUserMessage(e.target.value)}
          placeholder="Type your message..."
          disabled={isSubmitting}
        />
        <button 
          type="submit" 
          className={`dynamic-button ${sessionState.isPlaying ? 'pause' : userMessage ? 'send' : 'play'}`}
          disabled={isSubmitting && !sessionState.isPlaying}
        >
          {sessionState.isPlaying ? (
            <>
              <Pause size={18} />
              <span className="button-text">Pause</span>
            </>
          ) : userMessage ? (
            <>
              <Send size={18} />
              <span className="button-text">Send</span>
            </>
          ) : (
            <>
              <Play size={18} />
              <span className="button-text">Play</span>
            </>
          )}
        </button>
      </form>
    </div>
  );
};

export default ChatInterface;