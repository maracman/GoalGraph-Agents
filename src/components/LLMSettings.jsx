import React, { useState, useEffect } from 'react';
import { Save, RefreshCw } from 'lucide-react';
import Dropdown from './common/Dropdown';
import Button from './common/Button';
import Slider from './common/Slider';
import llmService, { setProvider, setApiKey, listModels } from '../services/llmService';

const LLMSettings = () => {
  const [provider, setLLMProvider] = useState('openai');
  const [apiKeys, setApiKeys] = useState({
    openai: '',
    'openai-codex': '',
    anthropic: '',
    cohere: '',
    huggingface: ''
  });
  const [selectedModel, setSelectedModel] = useState('');
  const [availableModels, setAvailableModels] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(false);
  
  // Settings
  const [settings, setSettings] = useState({
    temperature: 0.7,
    max_tokens: 150,
    top_p: 0.9,
    fallback_to_local: true
  });
  
  // Provider options
  const providerOptions = [
    { value: 'openai', label: 'OpenAI (API Key)' },
    { value: 'openai-codex', label: 'OpenAI Codex (ChatGPT Subscription)' },
    { value: 'anthropic', label: 'Anthropic (Claude)' },
    { value: 'cohere', label: 'Cohere' },
    { value: 'huggingface', label: 'HuggingFace' },
    { value: 'local', label: 'Local Model' }
  ];
  
  // Load available models when provider changes
  useEffect(() => {
    loadModels();
  }, [provider]);
  
  // Load models for selected provider
  const loadModels = async () => {
    try {
      setLoading(true);
      setError(null);
      
      // If we have an API key for this provider, use it
      if (apiKeys[provider]) {
        setProvider(provider);
        setApiKey(provider, apiKeys[provider]);
      }
      
      // For 'local' or 'openai-codex' provider, no API key is needed
      if (provider === 'local' || provider === 'openai-codex') {
        setProvider(provider);
      }

      // Don't try to load models if we don't have an API key for non-local/non-codex provider
      if (provider !== 'local' && provider !== 'openai-codex' && !apiKeys[provider]) {
        setAvailableModels([]);
        setSelectedModel('');
        setLoading(false);
        return;
      }
      
      const models = await listModels();
      setAvailableModels(models.map(model => ({
        value: model.id,
        label: model.name
      })));
      
      // Select first model by default if none selected
      if (models.length > 0 && !selectedModel) {
        setSelectedModel(models[0].id);
      }
    } catch (err) {
      console.error('Error loading models:', err);
      setError('Failed to load models. Please check your API key and try again.');
      setAvailableModels([]);
    } finally {
      setLoading(false);
    }
  };
  
  // Handle provider change
  const handleProviderChange = (value) => {
    setLLMProvider(value);
    setSelectedModel('');
  };
  
  // Handle API key change
  const handleApiKeyChange = (e, providerKey) => {
    setApiKeys(prev => ({
      ...prev,
      [providerKey]: e.target.value
    }));
  };
  
  // Handle settings change
  const handleSettingChange = (setting, value) => {
    setSettings(prev => ({
      ...prev,
      [setting]: value
    }));
  };
  
  // Save settings
  const handleSave = async () => {
    try {
      setLoading(true);
      setError(null);
      setSuccess(false);
      
      // Set provider in the LLM service
      setProvider(provider);
      
      // Set API key if not using local model or codex proxy
      if (provider !== 'local' && provider !== 'openai-codex') {
        if (!apiKeys[provider]) {
          throw new Error(`API key is required for ${provider}`);
        }
        setApiKey(provider, apiKeys[provider]);
      }
      
      // Save settings to localStorage for persistence
      localStorage.setItem('llm_provider', provider);
      localStorage.setItem('llm_settings', JSON.stringify(settings));
      localStorage.setItem('llm_selected_model', selectedModel);
      
      // Don't store API keys in localStorage for security, but you could
      // store encrypted versions or use a more secure storage method
      
      setSuccess(true);
      
      // Clear success message after 3 seconds
      setTimeout(() => {
        setSuccess(false);
      }, 3000);
    } catch (err) {
      console.error('Error saving LLM settings:', err);
      setError(err.message || 'Failed to save settings');
    } finally {
      setLoading(false);
    }
  };
  
  // Test the current configuration
  const testConfiguration = async () => {
    try {
      setLoading(true);
      setError(null);
      setSuccess(false);
      
      // Set provider and API key
      setProvider(provider);
      if (provider !== 'local' && apiKeys[provider]) {
        setApiKey(provider, apiKeys[provider]);
      }
      
      // Simple test prompt
      const response = await llmService.complete(
        "Please respond with 'Configuration is working correctly'", 
        {
          model: selectedModel,
          temperature: settings.temperature,
          max_tokens: settings.max_tokens,
          top_p: settings.top_p
        }
      );
      
      setSuccess(`Test successful! Response: ${response}`);
      
      // Clear success message after 5 seconds
      setTimeout(() => {
        setSuccess(false);
      }, 5000);
    } catch (err) {
      console.error('Test failed:', err);
      setError(`Test failed: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };
  
  // Load saved settings on component mount
  useEffect(() => {
    const savedProvider = localStorage.getItem('llm_provider');
    const savedSettings = localStorage.getItem('llm_settings');
    const savedModel = localStorage.getItem('llm_selected_model');
    
    if (savedProvider) {
      setLLMProvider(savedProvider);
    }
    
    if (savedSettings) {
      try {
        setSettings(JSON.parse(savedSettings));
      } catch (err) {
        console.error('Error parsing saved settings:', err);
      }
    }
    
    if (savedModel) {
      setSelectedModel(savedModel);
    }
    
    // Load API keys from a secure source if available
    // This is just a placeholder - in a real app, you'd use a more secure method
    // like an encrypted storage or a backend service for API keys
  }, []);
  
  return (
    <div className="llm-settings-container">
      <h2>LLM Provider Settings</h2>
      
      {error && (
        <div className="error-message">
          {error}
        </div>
      )}
      
      {success && (
        <div className="success-message">
          {success}
        </div>
      )}
      
      <div className="settings-form">
        <div className="setting-group">
          <label htmlFor="provider">LLM Provider</label>
          <Dropdown
            id="provider"
            options={providerOptions}
            value={provider}
            onChange={handleProviderChange}
            placeholder="Select LLM Provider"
          />
        </div>
        
        {provider === 'openai-codex' && (
          <div className="setting-group">
            <div className="api-key-input">
              <small className="api-key-help">
                Uses your ChatGPT Plus/Pro subscription via the Codex OAuth proxy.
                Requires: <code>npx openai-oauth</code> running on localhost:10531.
                Authenticate first with: <code>npm install -g @openai/codex && codex login</code>
              </small>
            </div>
          </div>
        )}

        {provider !== 'local' && provider !== 'openai-codex' && (
          <div className="setting-group">
            <label htmlFor={`${provider}-api-key`}>API Key</label>
            <div className="api-key-input">
              <input
                type="password"
                id={`${provider}-api-key`}
                value={apiKeys[provider] || ''}
                onChange={(e) => handleApiKeyChange(e, provider)}
                placeholder={`Enter ${provider} API Key`}
              />
              <small className="api-key-help">
                This key is stored locally and used only for API requests
              </small>
            </div>
          </div>
        )}
        
        <div className="setting-group">
          <label htmlFor="model">Model</label>
          <Dropdown
            id="model"
            options={availableModels}
            value={selectedModel}
            onChange={setSelectedModel}
            placeholder={loading ? "Loading models..." : "Select Model"}
            disabled={loading || availableModels.length === 0}
          />
          <Button 
            onClick={loadModels} 
            variant="secondary" 
            size="small"
            icon={<RefreshCw size={16} />}
            disabled={loading}
          >
            Refresh Models
          </Button>
        </div>
        
        <div className="setting-group">
          <Slider
            id="temperature"
            label="Temperature"
            min={0}
            max={1}
            step={0.1}
            value={settings.temperature}
            onChange={(value) => handleSettingChange('temperature', value)}
          />
          <small className="setting-help">
            Controls randomness: Lower values are more deterministic, higher values are more creative
          </small>
        </div>
        
        <div className="setting-group">
          <Slider
            id="max_tokens"
            label="Maximum Tokens"
            min={10}
            max={2000}
            step={10}
            value={settings.max_tokens}
            onChange={(value) => handleSettingChange('max_tokens', value)}
          />
          <small className="setting-help">
            Maximum number of tokens to generate in the response
          </small>
        </div>
        
        <div className="setting-group">
          <Slider
            id="top_p"
            label="Top P"
            min={0.1}
            max={1}
            step={0.05}
            value={settings.top_p}
            onChange={(value) => handleSettingChange('top_p', value)}
          />
          <small className="setting-help">
            Nucleus sampling: only consider tokens with top_p cumulative probability
          </small>
        </div>
        
        <div className="setting-group checkbox-group">
          <label htmlFor="fallback_to_local">
            <input
              type="checkbox"
              id="fallback_to_local"
              checked={settings.fallback_to_local}
              onChange={(e) => handleSettingChange('fallback_to_local', e.target.checked)}
            />
            <span>Fallback to local model if API call fails</span>
          </label>
        </div>
        
        <div className="buttons-row">
          <Button 
            onClick={handleSave} 
            variant="primary" 
            icon={<Save size={16} />}
            disabled={loading}
          >
            Save Settings
          </Button>
          
          <Button 
            onClick={testConfiguration} 
            variant="secondary"
            disabled={loading || (provider !== 'local' && provider !== 'openai-codex' && !apiKeys[provider])}
          >
            Test Configuration
          </Button>
        </div>
      </div>
    </div>
  );
};

export default LLMSettings;