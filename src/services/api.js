// src/services/api.js

/**
 * Fetches the current session ID from the server
 * @returns {Promise<string>} The session ID
 */
export const fetchSessionId = async () => {
    try {
      const response = await fetch('/get_session_id');
      const data = await response.json();
      return data.session_id;
    } catch (error) {
      console.error('Error fetching session ID:', error);
      throw error;
    }
  };
  
  /**
   * Checks the current session status
   * @returns {Promise<Object>} Session information
   */
  export const checkSession = async () => {
    try {
      const response = await fetch('/check_session');
      return await response.json();
    } catch (error) {
      console.error('Error checking session:', error);
      throw error;
    }
  };
  
  /**
   * Fetches the list of past chats
   * @returns {Promise<Object>} Object containing past chats
   */
  export const fetchPastChats = async () => {
    try {
      const response = await fetch('/get_past_chats');
      return await response.json();
    } catch (error) {
      console.error('Error fetching past chats:', error);
      throw error;
    }
  };
  
  /**
   * Loads a specific chat by ID
   * @param {string} chatId The ID of the chat to load
   * @returns {Promise<Object>} The loaded chat data
   */
  export const loadChat = async (chatId) => {
    try {
      const response = await fetch(`/load_chat/${chatId}`);
      return await response.json();
    } catch (error) {
      console.error('Error loading chat:', error);
      throw error;
    }
  };
  
  /**
   * Submits a user message to the server
   * @param {string} message The user's message
   * @param {boolean} isUser Whether the message is from the user
   * @returns {Promise<Object>} The response containing updated history
   */
  export const submitMessage = async (message, isUser = true, maxTurns = null) => {
    try {
      const formData = new FormData();
      formData.append('user_message', message);
      formData.append('is_user', isUser);
      if (maxTurns != null) {
        formData.append('max_turns', maxTurns);
      }
  
      const response = await fetch('/submit', {
        method: 'POST',
        body: formData,
      });
  
      return await response.json();
    } catch (error) {
      console.error('Error submitting message:', error);
      throw error;
    }
  };
  
  /**
   * Generates a response from the agent
   * @returns {Promise<Object>} The generated response
   */
  export const generateResponse = async () => {
    try {
      const response = await fetch('/generate');
      return await response.json();
    } catch (error) {
      console.error('Error generating response:', error);
      throw error;
    }
  };
  
  /**
   * Interrupts the current agent task
   * @returns {Promise<Object>} The result of the interruption
   */
  export const interruptTask = async () => {
    try {
      const response = await fetch('/interrupt', {
        method: 'POST',
      });
      return await response.json();
    } catch (error) {
      console.error('Error interrupting task:', error);
      throw error;
    }
  };
  
  /**
   * Resets the current chat
   * @returns {Promise<Object>} The result of the reset
   */
  export const resetChat = async () => {
    try {
      const response = await fetch('/reset', {
        method: 'POST',
      });
      return await response.json();
    } catch (error) {
      console.error('Error resetting chat:', error);
      throw error;
    }
  };
  
  /**
   * Creates a new chat
   * @returns {Promise<Object>} The new chat data
   */
  export const createNewChat = async () => {
    try {
      const response = await fetch('/create_new_chat', {
        method: 'POST',
      });
      return await response.json();
    } catch (error) {
      console.error('Error creating new chat:', error);
      throw error;
    }
  };
  
  /**
   * Fetches the list of agents
   * @returns {Promise<Array>} Array of agent objects
   */
  export const fetchAgents = async () => {
    try {
      const response = await fetch('/get_agents');
      const data = await response.json();
      return data;
    } catch (error) {
      console.error('Error fetching agents:', error);
      throw error;
    }
  };
  
  /**
   * Saves agent settings
   * @param {string} agentId The ID of the agent
   * @param {Object} settings The settings to save
   * @returns {Promise<Object>} The result of the save operation
   */
  export const saveAgentSettings = async (agentId, settings) => {
    try {
      const response = await fetch('/save_agent_settings', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          agent_id: agentId,
          settings,
        }),
      });
      return await response.json();
    } catch (error) {
      console.error('Error saving agent settings:', error);
      throw error;
    }
  };
  
  /**
   * Deletes an agent
   * @param {string} agentId The ID of the agent to delete
   * @returns {Promise<Object>} The result of the delete operation
   */
  export const deleteAgent = async (agentId) => {
    try {
      const formData = new FormData();
      formData.append('agent_id', agentId);
  
      const response = await fetch('/delete_agent', {
        method: 'POST',
        body: formData,
      });
      return await response.json();
    } catch (error) {
      console.error('Error deleting agent:', error);
      throw error;
    }
  };
  
  /**
   * Adds a new agent
   * @returns {Promise<Object>} The result of the add operation
   */
  export const addNewAgent = async () => {
    try {
      const response = await fetch('/add_agent', {
        method: 'POST',
      });
      return await response.json();
    } catch (error) {
      console.error('Error adding new agent:', error);
      throw error;
    }
  };
  
  /**
   * Fetches agent graphs
   * @returns {Promise<Array>} Array of agent graph data
   */
  export const fetchAgentGraphs = async () => {
    try {
      const response = await fetch('/get_agent_graphs');
      return await response.json();
    } catch (error) {
      console.error('Error fetching agent graphs:', error);
      throw error;
    }
  };
  
  /**
   * Visualizes the graph for a specific agent
   * @param {string} agentId The ID of the agent
   * @returns {Promise<Object>} The graph visualization data
   */
  export const visualizeGraph = async (agentId) => {
    try {
      const response = await fetch(`/visualize_pyvis?agent_id=${agentId}`);
      return await response.json();
    } catch (error) {
      console.error('Error visualizing graph:', error);
      throw error;
    }
  };
  
  /**
   * Fetches logs since a specific timestamp
   * @param {number} since The timestamp to fetch logs from
   * @returns {Promise<Object>} The logs and current timestamp
   */
  export const fetchLogs = async (since = 0) => {
    try {
      const response = await fetch(`/logs?since=${since}`);
      return await response.json();
    } catch (error) {
      console.error('Error fetching logs:', error);
      throw error;
    }
  };
  
  /**
   * Fetches debug information about the current session
   * @returns {Promise<Object>} Debug information
   */
  export const debugSession = async () => {
    try {
      const response = await fetch('/debug_session');
      return await response.json();
    } catch (error) {
      console.error('Error debugging session:', error);
      throw error;
    }
  };
  
  /**
   * Updates the session with a new ID
   * @param {string} sessionId The new session ID
   * @returns {Promise<Object>} The result of the update
   */
  export const updateSession = async (sessionId) => {
    try {
      const response = await fetch('/update_session', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ session_id: sessionId }),
      });
      return await response.json();
    } catch (error) {
      console.error('Error updating session:', error);
      throw error;
    }
  };
  
  /**
   * Updates the last interaction time for a chat
   * @param {string} chatId The ID of the chat
   * @returns {Promise<Object>} The result of the update
   */
  export const updateLastInteraction = async (chatId) => {
    try {
      const response = await fetch('/update_last_interaction', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ chat_id: chatId }),
      });
      return await response.json();
    } catch (error) {
      console.error('Error updating last interaction:', error);
      throw error;
    }
  };

  export const toggleAgentMute = async (agentId) => {
    try {
      const formData = new FormData();
      formData.append('agent_id', agentId);
      const response = await fetch('/toggle_agent_mute', {
        method: 'POST',
        body: formData,
      });
      return await response.json();
    } catch (error) {
      console.error('Error toggling agent mute:', error);
      throw error;
    }
  };

  export const duplicateChat = async () => {
    try {
      const response = await fetch('/duplicate', {
        method: 'POST',
      });
      return await response.json();
    } catch (error) {
      console.error('Error duplicating chat:', error);
      throw error;
    }
  };

  export const deleteChat = async () => {
    try {
      const response = await fetch('/delete_chat', {
        method: 'POST',
      });
      return await response.json();
    } catch (error) {
      console.error('Error deleting chat:', error);
      throw error;
    }
  };

// Agent Library
export const fetchAgentPresets = async () => {
  const response = await fetch('/api/agent_library');
  return response.json();
};

export const createAgentPreset = async (data) => {
  const response = await fetch('/api/agent_library', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });
  return response.json();
};

export const updateAgentPreset = async (presetId, data) => {
  const response = await fetch(`/api/agent_library/${presetId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });
  return response.json();
};

export const deleteAgentPreset = async (presetId) => {
  const response = await fetch(`/api/agent_library/${presetId}`, {
    method: 'DELETE'
  });
  return response.json();
};

// Graph Library
export const fetchSavedGraphs = async () => {
  const response = await fetch('/api/saved_graphs');
  return response.json();
};

export const saveGraphFromAgent = async (agentId, name) => {
  const response = await fetch(`/api/saved_graphs/from_agent/${agentId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name })
  });
  return response.json();
};

export const mergeGraphs = async (graphIds, name) => {
  const response = await fetch('/api/saved_graphs/merge', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ graph_ids: graphIds, name })
  });
  return response.json();
};

export const deleteSavedGraph = async (graphId) => {
  const response = await fetch(`/api/saved_graphs/${graphId}`, {
    method: 'DELETE'
  });
  return response.json();
};

// New chat with configuration
export const createConfiguredChat = async (mode, presetIds, graphAssignments) => {
  const response = await fetch('/create_new_chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode, preset_ids: presetIds, graph_assignments: graphAssignments || {} })
  });
  return response.json();
};