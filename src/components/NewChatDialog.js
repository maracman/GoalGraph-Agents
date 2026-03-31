import React, { useState, useEffect } from 'react';
import { X, MessageSquare, Users, Check } from 'lucide-react';
import { fetchAgentPresets, fetchSavedGraphs, createConfiguredChat } from '../services/api';
import { useSession } from '../contexts/SessionContext';

const NewChatDialog = ({ isOpen, onClose }) => {
  const { setSessionId, setSessionState, loadPastChats } = useSession();

  const [step, setStep] = useState(1);
  const [mode, setMode] = useState('');
  const [presets, setPresets] = useState([]);
  const [savedGraphs, setSavedGraphs] = useState([]);
  const [selectedPresetIds, setSelectedPresetIds] = useState([]);
  const [graphAssignments, setGraphAssignments] = useState({});

  useEffect(() => {
    if (isOpen) {
      setStep(1);
      setMode('');
      setSelectedPresetIds([]);
      setGraphAssignments({});
      loadData();
    }
  }, [isOpen]);

  const loadData = async () => {
    try {
      const [presetsData, graphsData] = await Promise.all([
        fetchAgentPresets(),
        fetchSavedGraphs()
      ]);
      setPresets(Array.isArray(presetsData) ? presetsData : presetsData.presets || []);
      setSavedGraphs(Array.isArray(graphsData) ? graphsData : graphsData.graphs || []);
    } catch (error) {
      console.error('Error loading dialog data:', error);
    }
  };

  const handleModeSelect = (selectedMode) => {
    setMode(selectedMode);
    setSelectedPresetIds([]);
    setGraphAssignments({});
    setStep(2);
  };

  const togglePresetSelection = (presetId) => {
    setSelectedPresetIds(prev => {
      if (prev.includes(presetId)) {
        const updated = prev.filter(id => id !== presetId);
        // Clean up graph assignment
        const newAssignments = { ...graphAssignments };
        delete newAssignments[presetId];
        setGraphAssignments(newAssignments);
        return updated;
      }

      if (mode === 'you_agent' && prev.length >= 1) {
        // Replace the selection for "You + Agent" mode
        const newAssignments = { ...graphAssignments };
        delete newAssignments[prev[0]];
        setGraphAssignments(newAssignments);
        return [presetId];
      }

      return [...prev, presetId];
    });
  };

  const handleGraphAssignment = (presetId, graphId) => {
    setGraphAssignments(prev => ({
      ...prev,
      [presetId]: graphId
    }));
  };

  const canProceedToStep3 = () => {
    if (mode === 'you_agent') return selectedPresetIds.length === 1;
    if (mode === 'agent_agent') return selectedPresetIds.length >= 2;
    return false;
  };

  const handleStartChat = async () => {
    try {
      const response = await createConfiguredChat(mode, selectedPresetIds, graphAssignments);
      if (response.success || response.session_id) {
        if (response.session_id) {
          setSessionId(response.session_id);
        }
        setSessionState(prev => ({
          ...prev,
          history: [],
          isPlaying: false,
          isUser: false,
          currentGeneration: 0,
          maxGenerations: 0,
          chat_mode: mode
        }));
        await loadPastChats();
        onClose();
      }
    } catch (error) {
      console.error('Error creating configured chat:', error);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="dialog-overlay" onClick={onClose}>
      <div className="dialog-card" onClick={(e) => e.stopPropagation()}>
        <div className="dialog-header">
          <h2>New Chat</h2>
          <button className="dialog-close-btn" onClick={onClose}>
            <X size={20} />
          </button>
        </div>

        <div className="dialog-body">
          {/* Step 1: Choose mode */}
          {step === 1 && (
            <div className="dialog-step">
              <h3>Choose Mode</h3>
              <div className="mode-buttons">
                <button
                  className="mode-button"
                  onClick={() => handleModeSelect('you_agent')}
                >
                  <MessageSquare size={32} />
                  <span className="mode-button-title">You + Agent</span>
                  <span className="mode-button-desc">Chat with one AI agent</span>
                </button>
                <button
                  className="mode-button"
                  onClick={() => handleModeSelect('agent_agent')}
                >
                  <Users size={32} />
                  <span className="mode-button-title">Agent vs Agent</span>
                  <span className="mode-button-desc">Watch agents converse</span>
                </button>
              </div>
            </div>
          )}

          {/* Step 2: Select agents */}
          {step === 2 && (
            <div className="dialog-step">
              <h3>
                Select Agent{mode === 'agent_agent' ? 's' : ''}{' '}
                <span style={{ fontWeight: 'normal', fontSize: '0.85em', color: '#888' }}>
                  {mode === 'you_agent' ? '(pick 1)' : '(pick 2 or more)'}
                </span>
              </h3>

              {presets.length === 0 && (
                <p style={{ color: '#888', fontStyle: 'italic' }}>
                  No agent presets found. Create some in the Agent Library first.
                </p>
              )}

              <div className="preset-selection-list">
                {presets.map((preset) => {
                  const isSelected = selectedPresetIds.includes(preset.preset_id);
                  return (
                    <div
                      key={preset.preset_id}
                      className={`preset-select-card ${isSelected ? 'selected' : ''}`}
                      onClick={() => togglePresetSelection(preset.preset_id)}
                    >
                      <div className="preset-select-check">
                        {isSelected && <Check size={16} />}
                      </div>
                      <div className="preset-select-info">
                        <strong>{preset.agent_name || preset.name}</strong>
                        {preset.provider && preset.model && (
                          <span className="preset-model-badge" style={{ marginLeft: 6, fontSize: 10 }}>
                            {preset.model}
                          </span>
                        )}
                        <p>{(preset.goal || 'No goal set').substring(0, 60)}</p>
                      </div>
                    </div>
                  );
                })}
              </div>

              <div className="dialog-nav-buttons">
                <button className="add-button" onClick={() => setStep(1)}>Back</button>
                <button
                  className="save-button"
                  disabled={!canProceedToStep3()}
                  onClick={() => setStep(3)}
                >
                  Next
                </button>
              </div>
            </div>
          )}

          {/* Step 3: Graph assignment */}
          {step === 3 && (
            <div className="dialog-step">
              <h3>Assign Graphs (Optional)</h3>

              <div className="graph-assignment-list">
                {selectedPresetIds.map((presetId) => {
                  const preset = presets.find(p => p.preset_id === presetId);
                  return (
                    <div key={presetId} className="graph-assignment-row">
                      <span className="graph-assignment-agent">
                        {preset ? (preset.agent_name || preset.name) : presetId}
                      </span>
                      <select
                        className="agent-selector"
                        value={graphAssignments[presetId] || ''}
                        onChange={(e) => handleGraphAssignment(presetId, e.target.value)}
                      >
                        <option value="">New Graph</option>
                        {savedGraphs.map((graph) => (
                          <option key={graph.id} value={graph.id}>
                            {graph.name}
                          </option>
                        ))}
                      </select>
                    </div>
                  );
                })}
              </div>

              <div className="dialog-nav-buttons">
                <button className="add-button" onClick={() => setStep(2)}>Back</button>
                <button className="save-button" onClick={handleStartChat}>
                  Start Chat
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default NewChatDialog;
