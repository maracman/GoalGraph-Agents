/**
 * Service for interacting with various LLM providers
 * Supports OpenAI, Anthropic, Cohere, and others
 */

import axios from 'axios';

// Default configuration
const DEFAULT_CONFIG = {
  provider: 'openai', // Default provider
  timeout: 60000,     // 60 seconds
  retries: 2,         // Number of retry attempts
  retry_delay: 1000,  // Delay between retries in ms
  fallback: null,     // Fallback provider
};

/**
 * LLM Service class
 */
class LLMService {
  constructor(config = {}) {
    this.config = { ...DEFAULT_CONFIG, ...config };
    this.apiKeys = {};
    this.setProvider(this.config.provider);
  }

  /**
   * Set the LLM provider
   * @param {string} provider - Provider name (openai, anthropic, cohere, huggingface)
   * @returns {LLMService} The service instance for chaining
   */
  setProvider(provider) {
    if (!provider) {
      throw new Error('Provider is required');
    }

    const supportedProviders = ['openai', 'openai-codex', 'anthropic', 'cohere', 'huggingface', 'local'];
    if (!supportedProviders.includes(provider)) {
      throw new Error(`Unsupported provider: ${provider}. Supported providers are: ${supportedProviders.join(', ')}`);
    }

    this.provider = provider;
    return this;
  }

  /**
   * Set API key for a provider
   * @param {string} provider - Provider name
   * @param {string} apiKey - API key
   * @returns {LLMService} The service instance for chaining
   */
  setApiKey(provider, apiKey) {
    this.apiKeys[provider] = apiKey;
    return this;
  }

  /**
   * Get API key for current provider
   * @returns {string|null} The API key or null if not set
   */
  getApiKey() {
    return this.apiKeys[this.provider] || null;
  }

  /**
   * Get base URL for the current provider's API
   * @returns {string} Base URL
   */
  getBaseUrl() {
    switch (this.provider) {
      case 'openai':
        return 'https://api.openai.com/v1';
      case 'openai-codex':
        return 'http://127.0.0.1:10531/v1';
      case 'anthropic':
        return 'https://api.anthropic.com/v1';
      case 'cohere':
        return 'https://api.cohere.ai/v1';
      case 'huggingface':
        return 'https://api-inference.huggingface.co/models';
      case 'local':
        return process.env.LOCAL_LLM_URL || 'http://localhost:8000';
      default:
        throw new Error(`Unknown provider: ${this.provider}`);
    }
  }

  /**
   * Create headers for API requests
   * @returns {Object} Headers object
   */
  createHeaders() {
    const apiKey = this.getApiKey();
    if (!apiKey && this.provider !== 'local' && this.provider !== 'openai-codex') {
      throw new Error(`API key not set for provider: ${this.provider}`);
    }

    switch (this.provider) {
      case 'openai':
      case 'openai-codex':
        return {
          'Authorization': `Bearer ${apiKey || 'codex-oauth'}`,
          'Content-Type': 'application/json'
        };
      case 'anthropic':
        return {
          'x-api-key': apiKey,
          'Content-Type': 'application/json',
          'anthropic-version': '2023-06-01'
        };
      case 'cohere':
        return {
          'Authorization': `Bearer ${apiKey}`,
          'Content-Type': 'application/json'
        };
      case 'huggingface':
        return {
          'Authorization': `Bearer ${apiKey}`,
          'Content-Type': 'application/json'
        };
      case 'local':
        return {
          'Content-Type': 'application/json'
        };
      default:
        throw new Error(`Unknown provider: ${this.provider}`);
    }
  }

  /**
   * Format prompt for specific provider
   * @param {string|Array} prompt - Prompt text or messages array
   * @param {Object} options - Provider-specific options
   * @returns {Object} Formatted request body
   */
  formatPrompt(prompt, options = {}) {
    switch (this.provider) {
      case 'openai':
      case 'openai-codex': {
        const messages = Array.isArray(prompt)
          ? prompt
          : [{ role: 'user', content: prompt }];
        const defaultModel = this.provider === 'openai-codex' ? 'gpt-4o' : 'gpt-3.5-turbo';

        return {
          model: options.model || defaultModel,
          messages,
          temperature: options.temperature ?? 0.7,
          max_tokens: options.max_tokens ?? 150,
          top_p: options.top_p ?? 1,
          frequency_penalty: options.frequency_penalty ?? 0,
          presence_penalty: options.presence_penalty ?? 0,
          stream: options.stream ?? false,
        };
      }
      
      case 'anthropic': {
        const formattedPrompt = Array.isArray(prompt) 
          ? prompt.map(m => `${m.role === 'user' ? 'Human' : 'Assistant'}: ${m.content}`).join('\n\n')
          : `Human: ${prompt}\n\nAssistant:`;
          
        return {
          model: options.model || 'claude-2',
          prompt: formattedPrompt,
          max_tokens_to_sample: options.max_tokens ?? 150,
          temperature: options.temperature ?? 0.7,
          top_p: options.top_p ?? 1,
          stop_sequences: options.stop_sequences || ["\n\nHuman:"],
          stream: options.stream ?? false,
        };
      }
      
      case 'cohere': {
        const formattedPrompt = Array.isArray(prompt) 
          ? prompt.map(m => `${m.role === 'user' ? 'User' : 'Chatbot'}: ${m.content}`).join('\n')
          : prompt;
          
        return {
          model: options.model || 'command',
          prompt: formattedPrompt,
          max_tokens: options.max_tokens ?? 150,
          temperature: options.temperature ?? 0.7,
          p: options.top_p ?? 1,
          k: options.top_k ?? 0,
          stop_sequences: options.stop_sequences || [],
          return_likelihoods: options.return_likelihoods || 'NONE',
        };
      }
      
      case 'huggingface': {
        const formattedPrompt = Array.isArray(prompt) 
          ? prompt.map(m => `${m.role === 'user' ? 'Human' : 'Assistant'}: ${m.content}`).join('\n\n')
          : prompt;
          
        return {
          inputs: formattedPrompt,
          parameters: {
            max_new_tokens: options.max_tokens ?? 150,
            temperature: options.temperature ?? 0.7,
            top_p: options.top_p ?? 1,
            top_k: options.top_k ?? 50,
            repetition_penalty: options.repetition_penalty ?? 1.0,
            do_sample: options.do_sample ?? true,
          }
        };
      }
      
      case 'local': {
        const formattedPrompt = Array.isArray(prompt) 
          ? prompt.map(m => `${m.role === 'user' ? 'User' : 'Assistant'}: ${m.content}`).join('\n\n')
          : prompt;
          
        return {
          prompt: formattedPrompt,
          max_tokens: options.max_tokens ?? 150,
          temperature: options.temperature ?? 0.7,
          top_p: options.top_p ?? 1,
          seed: options.seed ?? 42,
          stop: options.stop || [],
        };
      }
      
      default:
        throw new Error(`Unknown provider: ${this.provider}`);
    }
  }

  /**
   * Parse response from LLM provider
   * @param {Object} response - Response from provider
   * @returns {string} Generated text
   */
  parseResponse(response) {
    switch (this.provider) {
      case 'openai':
      case 'openai-codex':
        return response.data.choices[0].message.content.trim();
      case 'anthropic':
        return response.data.completion.trim();
      case 'cohere':
        return response.data.generations[0].text.trim();
      case 'huggingface':
        return response.data[0].generated_text.trim();
      case 'local':
        return response.data.response.trim();
      default:
        throw new Error(`Unknown provider: ${this.provider}`);
    }
  }

  /**
   * Complete a prompt using the current provider
   * @param {string|Array} prompt - Prompt text or messages array
   * @param {Object} options - Provider-specific options
   * @returns {Promise<string>} Generated text
   */
  async complete(prompt, options = {}) {
    try {
      const url = this.getEndpointUrl(options.model);
      const headers = this.createHeaders();
      const data = this.formatPrompt(prompt, options);
      
      const config = {
        method: 'post',
        url,
        headers,
        data,
        timeout: this.config.timeout,
      };
      
      const response = await this.makeRequest(config, this.config.retries);
      return this.parseResponse(response);
    } catch (error) {
      // Try fallback provider if configured
      if (this.config.fallback && this.provider !== this.config.fallback) {
        console.warn(`Primary provider ${this.provider} failed, falling back to ${this.config.fallback}`);
        const originalProvider = this.provider;
        this.setProvider(this.config.fallback);
        
        try {
          const result = await this.complete(prompt, options);
          this.setProvider(originalProvider); // Restore original provider
          return result;
        } catch (fallbackError) {
          this.setProvider(originalProvider); // Restore original provider
          throw fallbackError; // Re-throw if fallback also fails
        }
      }
      
      throw this.handleError(error);
    }
  }

  /**
   * Get appropriate API endpoint URL based on model and provider
   * @param {string} model - Model name
   * @returns {string} Endpoint URL
   */
  getEndpointUrl(model) {
    const baseUrl = this.getBaseUrl();
    
    switch (this.provider) {
      case 'openai':
      case 'openai-codex':
        return `${baseUrl}/chat/completions`;
      case 'anthropic':
        return `${baseUrl}/complete`;
      case 'cohere':
        return `${baseUrl}/generate`;
      case 'huggingface':
        // For HuggingFace, the model is part of the URL
        return `${baseUrl}/${model || 'gpt2'}`;
      case 'local':
        return `${baseUrl}/generate`;
      default:
        throw new Error(`Unknown provider: ${this.provider}`);
    }
  }

  /**
   * Make HTTP request with retry logic
   * @param {Object} config - Axios request config
   * @param {number} retries - Number of retries left
   * @returns {Promise<Object>} Response object
   */
  async makeRequest(config, retries) {
    try {
      return await axios(config);
    } catch (error) {
      if (retries > 0 && this.isRetryableError(error)) {
        console.warn(`Request failed, retrying... (${retries} attempts left)`);
        await new Promise(resolve => setTimeout(resolve, this.config.retry_delay));
        return this.makeRequest(config, retries - 1);
      }
      throw error;
    }
  }

  /**
   * Check if an error is retryable
   * @param {Error} error - The error to check
   * @returns {boolean} Whether the error is retryable
   */
  isRetryableError(error) {
    // Network errors, timeouts, and rate limits are retryable
    if (!error.response) return true;
    
    const status = error.response.status;
    return status === 429 || status >= 500;
  }

  /**
   * Format error message based on provider
   * @param {Error} error - The error object
   * @returns {Error} Formatted error
   */
  handleError(error) {
    if (!error.response) {
      return new Error(`Network error: ${error.message}`);
    }
    
    const status = error.response.status;
    const data = error.response.data;
    
    let message;
    
    switch (this.provider) {
      case 'openai':
      case 'openai-codex':
        message = data.error?.message || 'Unknown OpenAI error';
        break;
      case 'anthropic':
        message = data.error?.message || 'Unknown Anthropic error';
        break;
      case 'cohere':
        message = data.message || 'Unknown Cohere error';
        break;
      case 'huggingface':
        message = data.error || 'Unknown HuggingFace error';
        break;
      case 'local':
        message = data.error || 'Unknown Local LLM error';
        break;
      default:
        message = 'Unknown error';
    }
    
    const enhancedError = new Error(`${this.provider} API error (${status}): ${message}`);
    enhancedError.status = status;
    enhancedError.provider = this.provider;
    enhancedError.originalError = error;
    return enhancedError;
  }

  /**
   * List available models for the current provider
   * @returns {Promise<Array>} List of available models
   */
  async listModels() {
    try {
      const baseUrl = this.getBaseUrl();
      const headers = this.createHeaders();
      
      let url;
      switch (this.provider) {
        case 'openai':
          url = `${baseUrl}/models`;
          break;
        case 'openai-codex':
          // Return hardcoded list of models available via Codex subscription
          return Promise.resolve([
            { id: 'gpt-4o', name: 'GPT-4o' },
            { id: 'gpt-4o-mini', name: 'GPT-4o Mini' },
            { id: 'o3-mini', name: 'o3-mini' },
          ]);
        case 'anthropic':
          // Anthropic doesn't have a models endpoint, return hardcoded list
          return Promise.resolve([
            { id: 'claude-2', name: 'Claude 2' },
            { id: 'claude-instant-1', name: 'Claude Instant 1' }
          ]);
        case 'cohere':
          // Cohere doesn't have a public models endpoint, return hardcoded list
          return Promise.resolve([
            { id: 'command', name: 'Command' },
            { id: 'command-light', name: 'Command Light' },
            { id: 'generate', name: 'Generate' }
          ]);
        case 'huggingface':
          // For HuggingFace we'd need to implement a separate mechanism
          return Promise.resolve([
            { id: 'gpt2', name: 'GPT-2' },
            { id: 'distilgpt2', name: 'DistilGPT-2' },
            { id: 'gpt-neo', name: 'GPT-Neo' }
          ]);
        case 'local':
          url = `${baseUrl}/models`;
          break;
        default:
          throw new Error(`Unknown provider: ${this.provider}`);
      }
      
      const response = await axios.get(url, { headers });
      
      // Format response based on provider
      switch (this.provider) {
        case 'openai':
        case 'openai-codex':
          return response.data.data.map(model => ({
            id: model.id,
            name: model.id,
            description: model.description || ''
          }));
        case 'local':
          return response.data.models.map(model => ({
            id: model.id || model.name,
            name: model.name,
            description: model.description || ''
          }));
        default:
          return [];
      }
    } catch (error) {
      throw this.handleError(error);
    }
  }
}

// Create singleton instance
const llmService = new LLMService();

export default llmService;

// Named exports for specific functionality
export const setProvider = (provider) => llmService.setProvider(provider);
export const setApiKey = (provider, key) => llmService.setApiKey(provider, key);
export const complete = (prompt, options) => llmService.complete(prompt, options);
export const listModels = () => llmService.listModels();