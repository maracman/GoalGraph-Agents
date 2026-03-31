import React, { useState, useEffect } from 'react';
import { Plus, Save, Trash, Edit2, ChevronDown, ChevronUp, X } from 'lucide-react';
import { fetchAgentPresets, createAgentPreset, updateAgentPreset, deleteAgentPreset } from '../services/api';

const EMPTY_FORM = {
  agent_name: '',
  description: '',
  goal: '',
  target_impression: '',
  provider: '',
  model: '',
  persistance: 3,
  patience: 6
};

const AgentLibrary = () => {
  const [presets, setPresets] = useState([]);
  const [editingId, setEditingId] = useState(null);
  const [formOpen, setFormOpen] = useState(false);
  const [providers, setProviders] = useState([]);
  const [models, setModels] = useState([]);
  const [formData, setFormData] = useState({ ...EMPTY_FORM });

  useEffect(() => {
    loadPresets();
    loadProviders();
  }, []);

  useEffect(() => {
    if (formData.provider) {
      loadModels(formData.provider);
    } else {
      setModels([]);
    }
  }, [formData.provider]);

  const loadPresets = async () => {
    try {
      const data = await fetchAgentPresets();
      setPresets(Array.isArray(data) ? data : data.presets || []);
    } catch (error) {
      console.error('Error loading agent presets:', error);
    }
  };

  const loadProviders = async () => {
    try {
      const response = await fetch('/get_llm_providers');
      const data = await response.json();
      if (data.success) {
        setProviders(data.providers || []);
      }
    } catch (error) {
      console.error('Error loading providers:', error);
    }
  };

  const loadModels = async (provider) => {
    try {
      const response = await fetch(`/get_llm_models?provider=${encodeURIComponent(provider)}`);
      const data = await response.json();
      if (data.success) {
        setModels(data.models || []);
      }
    } catch (error) {
      console.error('Error loading models:', error);
    }
  };

  const handleInputChange = (e) => {
    const { name, value } = e.target;
    setFormData(prev => {
      const updated = { ...prev, [name]: value };
      if (name === 'provider') {
        updated.model = '';
      }
      return updated;
    });
  };

  const handleSave = async () => {
    if (!formData.agent_name.trim()) {
      alert('Agent name is required.');
      return;
    }

    try {
      if (editingId) {
        await updateAgentPreset(editingId, formData);
      } else {
        await createAgentPreset(formData);
      }
      resetForm();
      await loadPresets();
    } catch (error) {
      console.error('Error saving agent preset:', error);
    }
  };

  const handleEdit = (preset) => {
    setEditingId(preset.preset_id || preset.id);
    setFormData({
      agent_name: preset.agent_name || preset.name || '',
      description: preset.description || '',
      goal: preset.goal || '',
      target_impression: preset.target_impression || '',
      provider: preset.provider || '',
      model: preset.model || '',
      persistance: preset.persistance ?? 3,
      patience: preset.patience ?? 6
    });
    setFormOpen(true);
  };

  const handleDelete = async (presetId) => {
    if (!window.confirm('Are you sure you want to delete this preset?')) return;
    try {
      await deleteAgentPreset(presetId);
      await loadPresets();
    } catch (error) {
      console.error('Error deleting agent preset:', error);
    }
  };

  const resetForm = () => {
    setEditingId(null);
    setFormData({ ...EMPTY_FORM });
    setFormOpen(false);
    setModels([]);
  };

  const toggleForm = () => {
    if (formOpen) {
      resetForm();
    } else {
      setEditingId(null);
      setFormData({ ...EMPTY_FORM });
      setFormOpen(true);
    }
  };

  const getProviderLabel = (providerId) => {
    const p = providers.find(pr => pr.id === providerId);
    return p ? p.name : providerId;
  };

  // --- Render -----------------------------------------------------------

  const renderForm = () => (
    <div className="agent-create-form">
      <div className="settings-form">
        <div className="setting-group">
          <label htmlFor="preset_agent_name">Agent Name</label>
          <input
            type="text"
            id="preset_agent_name"
            name="agent_name"
            value={formData.agent_name}
            onChange={handleInputChange}
            placeholder="Enter agent name"
            autoFocus
          />
        </div>

        <div className="setting-group">
          <label htmlFor="preset_description">Description</label>
          <textarea
            id="preset_description"
            name="description"
            value={formData.description}
            onChange={handleInputChange}
            rows={3}
            placeholder="Describe the agent's personality and behavior"
          ></textarea>
        </div>

        <div className="setting-group">
          <label htmlFor="preset_goal">Goal</label>
          <textarea
            id="preset_goal"
            name="goal"
            value={formData.goal}
            onChange={handleInputChange}
            rows={3}
            placeholder="What is the agent trying to achieve?"
          ></textarea>
        </div>

        <div className="setting-group">
          <label htmlFor="preset_target_impression">Target Impression</label>
          <textarea
            id="preset_target_impression"
            name="target_impression"
            value={formData.target_impression}
            onChange={handleInputChange}
            rows={2}
            placeholder="How should others perceive this agent?"
          ></textarea>
        </div>

        <div className="llm-settings-row">
          <div className="setting-group" style={{ flex: 1 }}>
            <label htmlFor="preset_provider">LLM Provider</label>
            <select
              id="preset_provider"
              name="provider"
              className="agent-selector"
              value={formData.provider}
              onChange={handleInputChange}
            >
              <option value="">Use session default</option>
              {providers.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </div>

          <div className="setting-group" style={{ flex: 1 }}>
            <label htmlFor="preset_model">Model</label>
            <select
              id="preset_model"
              name="model"
              className="agent-selector"
              value={formData.model}
              onChange={handleInputChange}
              disabled={!formData.provider}
            >
              <option value="">
                {formData.provider ? 'Select model...' : 'Choose provider first'}
              </option>
              {models.map((m) => (
                <option key={m.id} value={m.id}>{m.name}</option>
              ))}
            </select>
          </div>
        </div>

        <div className="llm-settings-row">
          <div className="setting-group" style={{ flex: 1 }}>
            <label htmlFor="preset_persistance">Persistence</label>
            <input
              type="number"
              id="preset_persistance"
              name="persistance"
              value={formData.persistance}
              onChange={(e) => setFormData(prev => ({ ...prev, persistance: Math.max(1, parseInt(e.target.value) || 1) }))}
              min={1}
              max={20}
            />
            <span className="setting-hint">Min turns before agent can abandon a subgoal</span>
          </div>
          <div className="setting-group" style={{ flex: 1 }}>
            <label htmlFor="preset_patience">Patience</label>
            <input
              type="number"
              id="preset_patience"
              name="patience"
              value={formData.patience}
              onChange={(e) => setFormData(prev => ({ ...prev, patience: Math.max(1, parseInt(e.target.value) || 1) }))}
              min={1}
              max={20}
            />
            <span className="setting-hint">Max turns before forced abandonment</span>
          </div>
        </div>

        <div className="buttons-row">
          <button className="save-button" onClick={handleSave}>
            <Save size={16} />
            <span>{editingId ? 'Update Agent' : 'Save Agent'}</span>
          </button>

          <button className="add-button" onClick={resetForm}>
            <X size={16} />
            <span>Cancel</span>
          </button>
        </div>
      </div>
    </div>
  );

  return (
    <div className="agent-settings-container">
      <h2>Agent Library</h2>

      <div className="agent-library-list">
        {/* Create Agent card at the top */}
        <div
          className={`agent-preset-card create-agent-card ${formOpen && !editingId ? 'active' : ''}`}
          onClick={(!formOpen || editingId) ? toggleForm : undefined}
          style={(!formOpen || editingId) ? { cursor: 'pointer' } : {}}
        >
          <div className="preset-card-header" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Plus size={18} />
              <strong>Create Agent</strong>
            </div>
            {formOpen && !editingId && (
              <button
                className="icon-button"
                onClick={(e) => { e.stopPropagation(); resetForm(); }}
                title="Close"
                style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '4px', color: '#888' }}
              >
                <ChevronUp size={16} />
              </button>
            )}
          </div>
          {formOpen && !editingId && renderForm()}
        </div>

        {/* Agent preset cards */}
        {presets.length === 0 && !formOpen && (
          <p style={{ color: '#888', fontStyle: 'italic', padding: '8px 0' }}>No saved agent presets yet.</p>
        )}
        {presets.map((preset) => {
          const id = preset.preset_id || preset.id;
          const isEditing = editingId === id && formOpen;
          return (
            <div key={id} className={`agent-preset-card ${isEditing ? 'active' : ''}`}>
              <div className="preset-card-header" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <strong>{preset.agent_name || preset.name}</strong>
                  {preset.provider && preset.model && (
                    <span className="preset-model-badge">
                      {preset.model}
                    </span>
                  )}
                </div>
                {isEditing && (
                  <button
                    className="icon-button"
                    onClick={(e) => { e.stopPropagation(); resetForm(); }}
                    title="Close"
                    style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '4px', color: '#888' }}
                  >
                    <ChevronUp size={16} />
                  </button>
                )}
              </div>
              {!isEditing && (
                <>
                  <div className="preset-card-body">
                    <p className="preset-goal-snippet">
                      {(preset.goal || '').length > 80
                        ? (preset.goal || '').substring(0, 80) + '...'
                        : preset.goal || 'No goal set'}
                    </p>
                    {preset.provider && (
                      <p className="preset-provider-label">
                        {getProviderLabel(preset.provider)}
                      </p>
                    )}
                  </div>
                  <div className="buttons-row" style={{ justifyContent: 'flex-end' }}>
                    <button className="save-button" onClick={() => handleEdit(preset)} title="Edit">
                      <Edit2 size={14} />
                      <span>Edit</span>
                    </button>
                    <button className="delete-button" onClick={() => handleDelete(id)} title="Delete">
                      <Trash size={14} />
                      <span>Delete</span>
                    </button>
                  </div>
                </>
              )}
              {isEditing && renderForm()}
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default AgentLibrary;
