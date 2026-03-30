import React, { useState, useEffect } from 'react';
import { Plus, Save, Trash } from 'lucide-react';
import { fetchAgents, saveAgentSettings, deleteAgent, addNewAgent } from '../services/api';
import { useSession } from '../contexts/SessionContext';

const AgentSettings = () => {
  const { sessionId, sessionState, setSessionState } = useSession();
  const [agents, setAgents] = useState([]);
  const [selectedAgentIndex, setSelectedAgentIndex] = useState(0);
  const [formData, setFormData] = useState({
    agent_name: '',
    agent_description: '',
    goal: '',
    target_impression: '',
    muted: false,
    use_agent_generation_variables: false,
    generation_variables: {
      seed: 42,
      temperature: 0.7,
      max_tokens: 150,
      top_p: 0.9,
      use_gpu: true
    }
  });
  
  useEffect(() => {
    loadAgents();
  }, []);
  
  useEffect(() => {
    if (agents.length > 0 && selectedAgentIndex < agents.length) {
      const agent = agents[selectedAgentIndex];
      setFormData({
        agent_name: agent.agent_name,
        agent_description: agent.description,
        goal: agent.goal,
        target_impression: agent.target_impression || '',
        muted: agent.muted,
        use_agent_generation_variables: agent.is_agent_generation_variables,
        generation_variables: {
          seed: agent.generation_variables?.seed || 42,
          temperature: agent.generation_variables?.temperature || 0.7,
          max_tokens: agent.generation_variables?.max_tokens || 150,
          top_p: agent.generation_variables?.top_p || 0.9,
          use_gpu: agent.generation_variables?.use_gpu || true
        }
      });
    }
  }, [selectedAgentIndex, agents]);
  
  const loadAgents = async () => {
    try {
      const agentsData = await fetchAgents();
      setAgents(agentsData);
      
      // Update global session state
      setSessionState(prev => ({
        ...prev,
        agentData: agentsData
      }));
    } catch (error) {
      console.error("Error loading agents:", error);
    }
  };
  
  const handleAgentChange = (e) => {
    setSelectedAgentIndex(Number(e.target.value));
  };
  
  const handleInputChange = (e) => {
    const { name, value, type, checked } = e.target;
    
    setFormData(prev => ({
      ...prev,
      [name]: type === 'checkbox' ? checked : value
    }));
  };
  
  const handleGenerationVariableChange = (e) => {
    const { name, value, type, checked } = e.target;
    const newValue = type === 'checkbox' ? checked : 
                     type === 'number' ? Number(value) : 
                     value;
    
    setFormData(prev => ({
      ...prev,
      generation_variables: {
        ...prev.generation_variables,
        [name]: newValue
      }
    }));
  };
  
  const handleSaveSettings = async () => {
    try {
      if (agents.length === 0 || selectedAgentIndex >= agents.length) {
        return;
      }
      
      const agentId = agents[selectedAgentIndex].agent_id;
      
      const updatedAgent = {
        ...agents[selectedAgentIndex],
        agent_name: formData.agent_name,
        description: formData.agent_description,
        goal: formData.goal,
        target_impression: formData.target_impression,
        muted: formData.muted,
        is_agent_generation_variables: formData.use_agent_generation_variables,
        generation_variables: formData.generation_variables
      };
      
      await saveAgentSettings(agentId, updatedAgent);
      
      // Refresh the agents list
      await loadAgents();
    } catch (error) {
      console.error("Error saving agent settings:", error);
    }
  };
  
  const handleDeleteAgent = async () => {
    try {
      if (agents.length <= 1) {
        alert("Cannot delete the last agent. At least one agent is required.");
        return;
      }
      
      const agentId = agents[selectedAgentIndex].agent_id;
      await deleteAgent(agentId);
      
      // Refresh the agents list and reset selection
      await loadAgents();
      setSelectedAgentIndex(0);
    } catch (error) {
      console.error("Error deleting agent:", error);
    }
  };
  
  const handleAddAgent = async () => {
    try {
      await addNewAgent();
      
      // Refresh the agents list and select the new agent
      const updatedAgents = await fetchAgents();
      setAgents(updatedAgents);
      setSelectedAgentIndex(updatedAgents.length - 1);
    } catch (error) {
      console.error("Error adding new agent:", error);
    }
  };
  
  return (
    <div className="agent-settings-container">
      <h2>Agent Settings</h2>
      
      <div className="agent-selector-wrapper">
        <select
          id="agent-selector"
          value={selectedAgentIndex}
          onChange={handleAgentChange}
          className="agent-selector"
        >
          {agents.map((agent, index) => (
            <option key={agent.agent_id} value={index}>
              {agent.agent_name}
            </option>
          ))}
        </select>
      </div>
      
      <div className="settings-form">
        <div className="setting-group">
          <label htmlFor="agent_name">Agent Name</label>
          <input
            type="text"
            id="agent_name"
            name="agent_name"
            value={formData.agent_name}
            onChange={handleInputChange}
            placeholder="Enter agent name"
          />
        </div>
        
        <div className="setting-group">
          <label htmlFor="agent_description">Agent Description</label>
          <textarea
            id="agent_description"
            name="agent_description"
            value={formData.agent_description}
            onChange={handleInputChange}
            rows={3}
            placeholder="Describe the agent's personality and behavior"
          ></textarea>
        </div>
        
        <div className="setting-group">
          <label htmlFor="goal">Goal</label>
          <textarea
            id="goal"
            name="goal"
            value={formData.goal}
            onChange={handleInputChange}
            rows={3}
            placeholder="What is the agent trying to achieve?"
          ></textarea>
        </div>
        
        <div className="setting-group">
          <label htmlFor="target_impression">Target Impression</label>
          <textarea
            id="target_impression"
            name="target_impression"
            value={formData.target_impression}
            onChange={handleInputChange}
            rows={2}
            placeholder="How should others perceive this agent?"
          ></textarea>
        </div>
        
        <div className="setting-group checkbox-group">
          <label htmlFor="muted">
            <input
              type="checkbox"
              id="muted"
              name="muted"
              checked={formData.muted}
              onChange={handleInputChange}
            />
            <span>Muted</span>
          </label>
        </div>
        
        <div className="setting-group checkbox-group">
          <label htmlFor="use_agent_generation_variables">
            <input
              type="checkbox"
              id="use_agent_generation_variables"
              name="use_agent_generation_variables"
              checked={formData.use_agent_generation_variables}
              onChange={handleInputChange}
            />
            <span>Use Agent-Specific Generation Variables</span>
          </label>
        </div>
        
        {formData.use_agent_generation_variables && (
          <div className="generation-variables">
            <h3>Generation Variables</h3>
            
            <div className="setting-group">
              <label htmlFor="seed">Seed</label>
              <input
                type="number"
                id="seed"
                name="seed"
                value={formData.generation_variables.seed}
                onChange={handleGenerationVariableChange}
                min={1}
              />
            </div>
            
            <div className="setting-group">
              <label htmlFor="temperature">Temperature</label>
              <div className="range-slider">
                <input
                  type="range"
                  id="temperature"
                  name="temperature"
                  className="range-slider__range"
                  min={0}
                  max={1}
                  step={0.1}
                  value={formData.generation_variables.temperature}
                  onChange={handleGenerationVariableChange}
                />
                <div className="range-slider__value">{formData.generation_variables.temperature}</div>
              </div>
            </div>
            
            <div className="setting-group">
              <label htmlFor="max_tokens">Max Tokens</label>
              <div className="range-slider">
                <input
                  type="range"
                  id="max_tokens"
                  name="max_tokens"
                  className="range-slider__range"
                  min={50}
                  max={500}
                  step={10}
                  value={formData.generation_variables.max_tokens}
                  onChange={handleGenerationVariableChange}
                />
                <div className="range-slider__value">{formData.generation_variables.max_tokens}</div>
              </div>
            </div>
            
            <div className="setting-group">
              <label htmlFor="top_p">Top P</label>
              <div className="range-slider">
                <input
                  type="range"
                  id="top_p"
                  name="top_p"
                  className="range-slider__range"
                  min={0}
                  max={1}
                  step={0.1}
                  value={formData.generation_variables.top_p}
                  onChange={handleGenerationVariableChange}
                />
                <div className="range-slider__value">{formData.generation_variables.top_p}</div>
              </div>
            </div>
            
            <div className="setting-group checkbox-group">
              <label htmlFor="use_gpu">
                <input
                  type="checkbox"
                  id="use_gpu"
                  name="use_gpu"
                  checked={formData.generation_variables.use_gpu}
                  onChange={handleGenerationVariableChange}
                />
                <span>Use GPU</span>
              </label>
            </div>
          </div>
        )}
        
        <div className="buttons-row">
          <button className="save-button" onClick={handleSaveSettings}>
            <Save size={16} />
            <span>Save Settings</span>
          </button>
          
          <button className="delete-button" onClick={handleDeleteAgent}>
            <Trash size={16} />
            <span>Delete Agent</span>
          </button>
          
          <button className="add-button" onClick={handleAddAgent}>
            <Plus size={16} />
            <span>Add New Agent</span>
          </button>
        </div>
      </div>
    </div>
  );
};

export default AgentSettings;