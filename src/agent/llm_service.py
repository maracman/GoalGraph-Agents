"""
LLM Service module with flexible provider support and graceful fallbacks
"""

import os
import json
import logging
import time
import requests
from typing import Union, List, Dict, Any, Optional
from pathlib import Path

# Set up logging
logger = logging.getLogger('llm_service_logger')

# Default configuration
DEFAULT_CONFIG = {
    'provider': 'openai',
    'model': None,
    'temperature': 0.7,
    'max_tokens': 150,
    'top_p': 0.9,
    'timeout': 60,
    'retries': 2,
    'retry_delay': 1,
    'fallback_enabled': True
}

# Known models per provider
PROVIDER_MODELS = {
    'openai': [
        {'id': 'gpt-4o', 'name': 'GPT-4o'},
        {'id': 'gpt-4o-mini', 'name': 'GPT-4o Mini'},
        {'id': 'gpt-4-turbo', 'name': 'GPT-4 Turbo'},
        {'id': 'gpt-3.5-turbo', 'name': 'GPT-3.5 Turbo'},
    ],
    'openai-codex': [
        {'id': 'gpt-4o', 'name': 'GPT-4o (Codex/Subscription)'},
        {'id': 'gpt-4o-mini', 'name': 'GPT-4o Mini (Codex/Subscription)'},
        {'id': 'o3-mini', 'name': 'o3-mini (Codex/Subscription)'},
    ],
    'anthropic': [
        {'id': 'claude-sonnet-4-20250514', 'name': 'Claude Sonnet 4'},
        {'id': 'claude-3-5-sonnet-20241022', 'name': 'Claude 3.5 Sonnet'},
        {'id': 'claude-3-5-haiku-20241022', 'name': 'Claude 3.5 Haiku'},
    ],
    'cohere': [
        {'id': 'command-r-plus', 'name': 'Command R+'},
        {'id': 'command-r', 'name': 'Command R'},
    ],
    'huggingface': [
        {'id': 'mistralai/Mistral-7B-Instruct-v0.2', 'name': 'Mistral 7B Instruct'},
    ],
    'local': [
        {'id': 'local', 'name': 'Local GGUF Model'},
    ]
}

# Custom base URLs for providers (overridable via env or set_base_url)
PROVIDER_BASE_URLS = {
    'openai-codex': os.environ.get(
        'OPENAI_CODEX_BASE_URL',
        'http://127.0.0.1:10531/v1/chat/completions'
    ),
}

LOCAL_MODELS = {}


class LLMService:
    """Service for interacting with various LLM providers with graceful fallbacks"""

    def __init__(self, config=None):
        """Initialize the LLM service with the given configuration."""
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self.api_keys = {}
        self.base_urls = dict(PROVIDER_BASE_URLS)  # copy defaults
        self.provider = self.config['provider']
        self.local_model_path = None
        self.local_model_filename = None

        # Try to load local model support - don't fail if not available
        self.has_local_support = False
        try:
            import llama_cpp
            self.has_local_support = True
            logger.info("Local model support is available")
        except ImportError:
            logger.info("Local model support is not available - will use API providers only")

        # Load API keys from environment variables
        self._load_api_keys_from_env()

    def _load_api_keys_from_env(self):
        """Load API keys from environment variables."""
        providers = ['openai', 'anthropic', 'cohere', 'huggingface']
        for provider in providers:
            env_var = f"{provider.upper()}_API_KEY"
            if env_var in os.environ:
                self.api_keys[provider] = os.environ[env_var]
                logger.info(f"Loaded API key for {provider}")

        # Load Codex OAuth token from ~/.codex/auth.json if available
        self._load_codex_auth()

    def _load_codex_auth(self):
        """Load OpenAI Codex OAuth credentials from ~/.codex/auth.json."""
        auth_path = os.path.expanduser('~/.codex/auth.json')
        try:
            if os.path.exists(auth_path):
                with open(auth_path, 'r') as f:
                    auth = json.load(f)
                token = auth.get('access_token')
                if token:
                    self.api_keys['openai-codex'] = token
                    logger.info("Loaded Codex OAuth token from ~/.codex/auth.json")
        except Exception as e:
            logger.warning(f"Could not load Codex auth: {e}")

    def set_provider(self, provider: str):
        """Set the active LLM provider."""
        self.provider = provider
        logger.info(f"Provider set to: {provider}")

    def set_api_key(self, provider: str, api_key: str):
        """Set an API key for a provider."""
        self.api_keys[provider] = api_key
        logger.info(f"API key set for {provider}")

    def set_base_url(self, provider: str, url: str):
        """Set a custom base URL for a provider."""
        self.base_urls[provider] = url
        logger.info(f"Base URL for {provider} set to: {url}")

    def list_models(self, provider: str = None) -> List[Dict[str, str]]:
        """List available models for a provider."""
        provider = provider or self.provider
        return PROVIDER_MODELS.get(provider, [])

    def make_api_request(self, url: str, data: Dict[str, Any], headers: Dict[str, str]) -> Dict[str, Any]:
        """Make an API request with retry logic."""
        retries = self.config.get('retries', 2)
        retry_delay = self.config.get('retry_delay', 1)
        timeout = self.config.get('timeout', 60)

        last_error = None
        for attempt in range(retries + 1):
            try:
                response = requests.post(url, json=data, headers=headers, timeout=timeout)
                response.raise_for_status()
                return response.json()
            except requests.exceptions.RequestException as e:
                last_error = e
                logger.warning(f"API request attempt {attempt + 1} failed: {str(e)}")
                if attempt < retries:
                    time.sleep(retry_delay)

        raise Exception(f"API request failed after {retries + 1} attempts: {str(last_error)}")

    def complete(self, prompt: Union[str, List[Dict[str, str]]], options: Dict[str, Any] = None) -> str:
        """Generate a completion with automatic fallback handling."""
        options = options or {}
        provider = options.get('provider', self.provider)

        # Handle local model case
        if provider == 'local':
            if not self.has_local_support:
                logger.warning("Local model support not available - falling back to API provider")
                provider = 'openai'
                options['provider'] = provider
            else:
                return self.complete_with_local_model(prompt, options)

        try:
            return self.complete_with_api(prompt, options)
        except Exception as e:
            logger.error(f"Error with provider {provider}: {str(e)}")
            if self.config['fallback_enabled']:
                alternative_providers = ['openai-codex', 'openai', 'anthropic', 'cohere']
                for alt_provider in alternative_providers:
                    if alt_provider != provider and alt_provider in self.api_keys:
                        try:
                            logger.info(f"Attempting fallback to {alt_provider}")
                            options['provider'] = alt_provider
                            return self.complete_with_api(prompt, options)
                        except Exception as fallback_error:
                            logger.error(f"Fallback to {alt_provider} failed: {str(fallback_error)}")

                if self.has_local_support:
                    try:
                        logger.info("Attempting fallback to local model")
                        return self.complete_with_local_model(prompt, options)
                    except Exception as local_error:
                        logger.error(f"Fallback to local model failed: {str(local_error)}")

            raise Exception(f"Failed to generate completion with all available providers: {str(e)}")

    def complete_with_api(self, prompt: Union[str, List[Dict[str, str]]], options: Dict[str, Any]) -> str:
        """Generate a completion using an API provider."""
        provider = options.get('provider', self.provider)

        url = self.get_base_url(provider)
        headers = self.create_headers(provider)
        data = self.format_request(prompt, options)

        response = self.make_api_request(url, data, headers)

        return self.parse_response(response, provider)

    def complete_with_local_model(self, prompt: str, options: Dict[str, Any]) -> str:
        """Generate a completion using a local model."""
        model_path = options.get('model_path', self.local_model_path)
        model_file = options.get('model_file', self.local_model_filename)

        if not model_file:
            model_files = list(Path(model_path).glob("*.gguf"))
            if not model_files:
                raise ValueError(f"No GGUF model files found in {model_path}")
            model_file = str(model_files[0])
        else:
            model_file = os.path.join(model_path, model_file)

        if not os.path.exists(model_file):
            raise FileNotFoundError(f"Model file not found: {model_file}")

        try:
            import llama_cpp

            model_key = model_file
            if model_key not in LOCAL_MODELS:
                logger.info(f"Loading local model: {model_file}")

                model_kwargs = {
                    'model_path': model_file,
                    'n_ctx': 2048,
                    'n_batch': 512,
                    'n_gpu_layers': 0
                }

                try:
                    import torch
                    if options.get('use_gpu', False) and torch.cuda.is_available():
                        model_kwargs['n_gpu_layers'] = -1
                        logger.info("Using GPU for local model inference")
                except ImportError:
                    pass

                LOCAL_MODELS[model_key] = llama_cpp.Llama(**model_kwargs)

            model = LOCAL_MODELS[model_key]

            max_tokens = options.get('max_tokens', 150)
            temperature = options.get('temperature', 0.7)
            top_p = options.get('top_p', 0.9)
            stop = options.get('stop', [])

            prompt_text = prompt if isinstance(prompt, str) else json.dumps(prompt)

            logger.info(f"Generating completion with local model, prompt length: {len(prompt_text)}")

            result = model(
                prompt_text,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                stop=stop
            )

            return result['choices'][0]['text']

        except Exception as e:
            logger.error(f"Error with local model: {str(e)}")
            raise

    def get_base_url(self, provider: str) -> str:
        """Get the base URL for the provider's API."""
        # Check for custom base URL first (e.g. openai-codex proxy)
        if provider in self.base_urls:
            return self.base_urls[provider]

        urls = {
            'openai': 'https://api.openai.com/v1/chat/completions',
            'anthropic': 'https://api.anthropic.com/v1/messages',
            'cohere': 'https://api.cohere.ai/v1/chat',
            'huggingface': 'https://api-inference.huggingface.co/models'
        }
        return urls.get(provider, '')

    def create_headers(self, provider: str) -> Dict[str, str]:
        """Create headers for API requests."""
        api_key = self.api_keys.get(provider)
        if not api_key:
            # For openai-codex via proxy, API key may not be required
            if provider == 'openai-codex':
                api_key = 'codex-oauth'  # Proxy handles auth
            else:
                raise ValueError(f"No API key found for provider: {provider}")

        headers = {
            'Content-Type': 'application/json'
        }

        if provider in ('openai', 'openai-codex'):
            headers['Authorization'] = f"Bearer {api_key}"
        elif provider == 'anthropic':
            headers['x-api-key'] = api_key
            headers['anthropic-version'] = '2023-06-01'
        elif provider == 'cohere':
            headers['Authorization'] = f"Bearer {api_key}"
        elif provider == 'huggingface':
            headers['Authorization'] = f"Bearer {api_key}"

        return headers

    def format_request(self, prompt: Union[str, List[Dict[str, str]]], options: Dict[str, Any]) -> Dict[str, Any]:
        """Format the request based on the provider's requirements."""
        provider = options.get('provider', self.provider)
        temperature = options.get('temperature', 0.7)
        max_tokens = options.get('max_tokens', 150)

        if provider in ('openai', 'openai-codex'):
            messages = [{'role': 'user', 'content': prompt}] if isinstance(prompt, str) else prompt
            default_model = 'gpt-4o-mini' if provider == 'openai' else 'gpt-4o'
            return {
                'model': options.get('model', default_model),
                'messages': messages,
                'temperature': temperature,
                'max_tokens': max_tokens
            }
        elif provider == 'anthropic':
            if isinstance(prompt, list):
                # Extract system message and user messages
                system_msg = ''
                messages = []
                for msg in prompt:
                    if msg['role'] == 'system':
                        system_msg = msg['content']
                    else:
                        messages.append(msg)
                # Ensure messages alternate user/assistant properly
                if not messages:
                    messages = [{'role': 'user', 'content': 'Hello'}]
            else:
                system_msg = ''
                messages = [{'role': 'user', 'content': prompt}]

            data = {
                'model': options.get('model', 'claude-sonnet-4-20250514'),
                'messages': messages,
                'max_tokens': max_tokens,
                'temperature': temperature,
            }
            if system_msg:
                data['system'] = system_msg
            return data
        elif provider == 'cohere':
            message = prompt if isinstance(prompt, str) else prompt[-1]['content'] if prompt else ''
            return {
                'model': options.get('model', 'command-r'),
                'message': message,
                'temperature': temperature,
                'max_tokens': max_tokens
            }
        elif provider == 'huggingface':
            text = prompt if isinstance(prompt, str) else prompt[-1]['content'] if prompt else ''
            return {
                'inputs': text,
                'parameters': {
                    'temperature': temperature,
                    'max_new_tokens': max_tokens
                }
            }

        return {'prompt': prompt if isinstance(prompt, str) else json.dumps(prompt)}

    def parse_response(self, response: Dict[str, Any], provider: str) -> str:
        """Parse the response from the provider."""
        try:
            if provider in ('openai', 'openai-codex'):
                return response['choices'][0]['message']['content'].strip()
            elif provider == 'anthropic':
                return response['content'][0]['text'].strip()
            elif provider == 'cohere':
                return response.get('text', '').strip()
            elif provider == 'huggingface':
                if isinstance(response, list) and response:
                    return response[0].get('generated_text', '').strip()
                return str(response)
            return str(response)
        except (KeyError, IndexError) as e:
            logger.error(f"Error parsing response from {provider}: {str(e)}")
            raise

# Create a singleton instance
llm_service = LLMService()