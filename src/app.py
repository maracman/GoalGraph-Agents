import threading
import socket
import time
import re
import queue
import logging
import subprocess
import os
import sys
import json
import uuid
import networkx as nx
import numpy as np
from datetime import datetime
from flask import Flask, request, render_template, jsonify, session, Response, redirect, url_for, send_from_directory
from flask_session import Session
from werkzeug.local import LocalProxy
from functools import wraps
from pyvis.network import Network
import pandas as pd
from agent.schemas import json_schemas
import importlib
from agent.llm_service import llm_service


# Set up logging
logging.basicConfig(level=logging.DEBUG)
flask_logger = logging.getLogger('flask_app')

# Create necessary directories
os.makedirs('chat_cache', exist_ok=True)
os.makedirs('chat_cache/graphs', exist_ok=True)
os.makedirs('flask_session', exist_ok=True)
os.makedirs('static', exist_ok=True)
agent_library_dir = os.path.join('chat_cache', 'agent_library')
saved_graphs_dir = os.path.join('chat_cache', 'saved_graphs')
os.makedirs(agent_library_dir, exist_ok=True)
os.makedirs(saved_graphs_dir, exist_ok=True)

# Global variables
global_log_queue = queue.Queue()
offline = os.environ.get('OFFLINE_MODE', 'false').lower() == 'true'
VERSION = time.time()
current_device = None

# Create a QueueHandler for logging
class QueueHandler(logging.Handler):
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        self.log_queue.put(self.format(record))

def setup_logger(name, level=logging.DEBUG):
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not logger.handlers:
        # Queue Handler
        queue_handler = QueueHandler(global_log_queue)
        queue_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        logger.addHandler(queue_handler)

        # Console Handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        logger.addHandler(console_handler)

    return logger

# Setup the Flask logger
flask_logger = setup_logger('flask_app')
logger = setup_logger('agent_logger')

def get_logs():
    logs = []
    while not global_log_queue.empty():
        logs.append(global_log_queue.get())
    return '\n'.join(logs)

# Initialize Flask app
app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = os.path.join(os.getcwd(), 'flask_session')
app.config['SESSION_PERMANENT'] = False
app.config['SESSION_USE_SIGNER'] = True
app.secret_key = os.environ.get('FLASK_SECRET_KEY', os.urandom(24).hex())
Session(app)

# Cache directory path
cache_dir = os.path.join(os.getcwd(), 'chat_cache')
graph_directory = os.path.join(cache_dir, 'graphs')
agent_library_dir = os.path.join(cache_dir, 'agent_library')
saved_graphs_dir = os.path.join(cache_dir, 'saved_graphs')
os.makedirs(agent_library_dir, exist_ok=True)
os.makedirs(saved_graphs_dir, exist_ok=True)

# Model configuration
local_model_path = os.path.join(os.getcwd(), "local_model")
model_filename = os.path.join(local_model_path, "Meta-Llama-3-8B.Q8_0.gguf")
model_url = "https://huggingface.co/TheBloke/Meta-Llama-3-8B-GGUF/resolve/main/Meta-Llama-3-8B.Q8_0.gguf?download=true"

# Initialize LLM service configuration
from agent.llm_service import llm_service
llm_service.local_model_path = local_model_path
llm_service.local_model_filename = os.path.basename(model_filename)

def download_model():
    """Download the model if it doesn't exist"""
    os.makedirs(local_model_path, exist_ok=True)
    import requests
    
    response = requests.get(model_url)
    with open(model_filename, 'wb') as model_file:
        model_file.write(response.content)

    flask_logger.info(f"Model downloaded and saved to {model_filename}")

    # Create a barebones config file for the model
    config = {"model_type": "llama"}
    config_path = os.path.join(local_model_path, "config.json")
    with open(config_path, 'w') as config_file:
        json.dump(config, config_file)
    flask_logger.info(f"Config file saved at {config_path}")



import agent.agent as agent_module_ref

def reload_agent():
    """Reload the agent module dynamically"""
    try:
        importlib.reload(agent_module_ref)
        flask_logger.info("Agent module reloaded successfully")
        return agent_module_ref
    except Exception as e:
        flask_logger.error(f"Failed to reload agent: {str(e)}")
        raise

def visualize_graph_pyvis(graph_file_path, session_id):
    """Generate a visualization of the agent's decision graph"""
    try:
        # Load the graph from the GraphML file
        G = nx.read_graphml(graph_file_path)

        net = Network(notebook=True, directed=True, cdn_resources='in_line')

        # Separate "Go" and "NoGo" edges
        go_edges = [(u, v) for u, v, d in G.edges(data=True) if d['label'] == 'Go']
        nogo_edges = [(u, v) for u, v, d in G.edges(data=True) if d['label'] == 'NoGo']

        # Extract weights for "Go" edges
        go_weights = [G[u][v]['weight'] for u, v in go_edges]

        # Calculate the mean and standard deviation for "Go" weights
        mean_weight = np.mean(go_weights) if go_weights else 0
        std_weight = np.std(go_weights) if go_weights else 0

        # Calculate the length for "NoGo" edges
        nogo_length = (mean_weight - (std_weight * 2)) * 100 if mean_weight and std_weight else 100

        # Extract weights for "NoGo" edges
        nogo_weights = [G[u][v]['weight'] for u, v in nogo_edges]

        # Calculate the range for "NoGo" weights
        min_weight = min(nogo_weights, default=0)
        max_weight = max(nogo_weights, default=1)

        # Function to calculate color based on weight
        def weight_to_color(weight, min_weight, max_weight):
            if max_weight == min_weight:  # Avoid division by zero
                return 'lightgrey'
            normalized = (weight - min_weight) / (max_weight - min_weight)
            grey_value = int(255 * (1 - normalized))
            return f'#{grey_value:02x}{grey_value:02x}{grey_value:02x}'

        # Add nodes and edges to the network
        for node in G.nodes():
            incoming_edges = G.in_edges(node, data=True)
            if any(d['label'] == 'NoGo' for u, v, d in incoming_edges):
                weight = next(d['weight'] for u, v, d in incoming_edges if d['label'] == 'NoGo')
                color = weight_to_color(weight, min_weight, max_weight)
            else:
                color = 'blue'
            net.add_node(node, label=node, color=color)

        for u, v, data in G.edges(data=True):
            weight = data['weight']
            if data['label'] == 'NoGo':
                net.add_edge(u, v, label=data['label'], weight=weight, length=nogo_length)
            else:
                net.add_edge(u, v, label=data['label'], weight=weight, length=weight * 100)

        # Customize physics to better reflect distances
        net.set_options("""
        var options = {
          "physics": {
            "barnesHut": {
              "gravitationalConstant": -8000,
              "centralGravity": 0.3,
              "springLength": 95,
              "springConstant": 0.04,
              "damping": 0.09,
              "avoidOverlap": 0.1
            },
            "minVelocity": 0.75
          }
        }
        """)

        # Generate a unique filename for this graph visualization
        timestamp = int(time.time() * 1000)
        filename = f"graph_{session_id}_{timestamp}.html"

        # Save the graph visualization
        net.save_graph(os.path.join(app.static_folder, filename))

        return filename
    except Exception as e:
        flask_logger.error(f"Error visualizing graph: {str(e)}")
        return None

# Load default settings for initializing a new session
def load_default_settings(filename='defaults_session.json'):
    with open(filename, 'r') as file:
        defaults = json.load(file)
    
    # Add LLM settings if not already present
    if 'llm_settings' not in defaults:
        defaults['llm_settings'] = {
            'provider': 'openai-codex',
            'model': 'gpt-4o',
            'temperature': 0.7,
            'max_tokens': 250,
            'top_p': 0.9,
            'fallback_to_local': False
        }
    
    return defaults

# Generate unique session ID
def generate_session_id():
    return f"session_{uuid.uuid4()}"

# Generate unique agent ID
def generate_agent_id():
    return f"agent_{uuid.uuid4()}"

# Initialize agents DataFrame from defaults
def initialize_agents_df(default_agents):
    agents = []
    for agent in default_agents:
        agent['agent_id'] = generate_agent_id()
        agent['graph_file_path'] = os.path.join(graph_directory, f"{agent['agent_id']}_graph.graphml")
        # Initialize graph
        graph = nx.DiGraph()
        graph.add_node('start')
        nx.write_graphml(graph, agent['graph_file_path'])
        agents.append(agent)
    return pd.DataFrame(agents)

# Initialize single agent
def initialize_single_agent(default_agent):
    agent_id = generate_agent_id()
    default_agent['agent_id'] = agent_id
    default_agent['graph_file_path'] = os.path.join(graph_directory, f"{agent_id}_graph.graphml")
    # Initialize graph
    graph = nx.DiGraph()
    graph.add_node('start')
    nx.write_graphml(graph, default_agent['graph_file_path'])
    return default_agent

def check_session_state(passed_function="not specified"):
    flask_logger.debug(f"Session contents: {session}")
    flask_logger.info(f"check_session_state called by function: {passed_function}")
    
    if 'state' not in session:
        flask_logger.warning("Session state not found, initializing new session")
        new_state = initialize_session()
        session['state'] = new_state
        flask_logger.debug(f"New session state initialized: {new_state}")
    else:
        flask_logger.debug("Session state found")
    
    return session['state']

def initialize_session():
    flask_logger.debug("Entering initialize_session function")
    
    if 'state' in session and session['state'].get('session_id'):
        flask_logger.info(f"Valid session already exists with ID: {session['state']['session_id']}")
        return session['state']

    defaults = load_default_settings()
    flask_logger.debug(f"Loaded default settings: {defaults}")

    session_id = generate_session_id()
    agents_df = initialize_agents_df(defaults['agents_df'])

    session_state = {
        'session_id': session_id,
        'user_name': defaults['user_name'],
        'agent_mutes': [False] * len(agents_df),
        'agents_df': agents_df.to_dict('records'),
        'session_history': [],
        'len_last_history': defaults['len_last_history'],
        'settings': defaults['settings'],
        'play': False,
        'is_user': False,
        'max_generations': 0,
        'current_generation': 0,
        'user_message': '',
        'number_of_agents': len(agents_df)
    }

    flask_logger.info(f"New session initialized with ID: {session_id}")
    flask_logger.debug(f"Initial session state: {session_state}")
    save_current_session(session_state)
    session['state'] = session_state
    flask_logger.info(f"New session initialized, session state: {session['state']}")
    flask_logger.info(f"Checking persistence of session state")
    check_session_state()
    flask_logger.info("Exiting initialize_session function")

    if 'llm_settings' not in session_state:
        session_state['llm_settings'] = defaults.get('llm_settings', {
            'provider': 'openai-codex',
            'model': 'gpt-4o',
            'temperature': 0.7,
            'max_tokens': 250,
            'top_p': 0.9,
            'fallback_to_local': False
        })

    return session_state

def _sanitize_for_json(obj):
    """Replace NaN/Infinity values with None for valid JSON serialization."""
    import math
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    return obj

def save_current_session(session_state):
    session_id = session_state['session_id']
    filename = f"{session_id}_state.json"
    filepath = os.path.join(cache_dir, filename)
    with open(filepath, 'w') as f:
        json.dump(_sanitize_for_json(session_state), f)
    flask_logger.info(f"Session state saved: {session_id}")

def load_state(session_id):
    filename = f"{session_id}_state.json"
    filepath = os.path.join(cache_dir, filename)
    if os.path.exists(filepath):
        with open(filepath, 'r') as f:
            state = json.load(f)
            return state
    return None

# Adding a single agent to an existing session
def add_single_agent_to_session(default_agent):
    if 'state' not in session or not session['state']:
        flask_logger.error("No session found to add an agent to")
        return

    new_agent = initialize_single_agent(default_agent)
    agents_df = pd.DataFrame(session['state']['agents_df'])
    agents_df = pd.concat([agents_df, pd.DataFrame([new_agent])], ignore_index=True)
    session['state']['agents_df'] = agents_df.to_dict('records')
    session['state']['agent_mutes'].append(False)
    session['state']['number_of_agents'] += 1

    flask_logger.info("New agent added to the session")
    flask_logger.debug(f"Updated session state: {session['state']}")
    save_current_session(session['state'])

def handle_llm_error(error):
    """Handle LLM-related errors and return appropriate responses."""
    error_msg = str(error)
    status_code = 500
    
    # API key errors
    if "API key" in error_msg:
        if "not set" in error_msg:
            error_msg = "API key is not set for the selected provider. Please configure your API key in LLM Settings."
            status_code = 401
        elif "invalid" in error_msg.lower():
            error_msg = "Invalid API key. Please check your API key and try again."
            status_code = 401
    
    # Rate limit errors
    elif "rate limit" in error_msg.lower() or "too many requests" in error_msg.lower():
        error_msg = "Rate limit exceeded. Please wait a moment and try again."
        status_code = 429
    
    # Connectivity errors
    elif "connection" in error_msg.lower() or "timeout" in error_msg.lower():
        error_msg = "Connection error. Please check your internet connection and try again."
        status_code = 503
    
    # Model loading errors
    elif "model" in error_msg.lower() and ("not found" in error_msg.lower() or "loading" in error_msg.lower()):
        error_msg = "Error loading model. Please check that the model file exists and is accessible."
        status_code = 404
    
    # Fallback message
    else:
        error_msg = f"LLM error: {error_msg}"
    
    # Log the error for debugging
    flask_logger.error(f"LLM error ({status_code}): {error_msg}")
    
    return jsonify({
        "success": False,
        "error": error_msg,
        "error_type": "llm_error"
    }), status_code


@app.before_request
def before_request():
    flask_logger.debug(f"Before request for endpoint: {request.endpoint}")
    if request.endpoint in ['index', 'submit', 'get_past_chats']:
        check_session_state("before_request")

@app.route('/')
def index():
    if 'state' in session:
        return render_template('index.html', session_id=session['state']['session_id'])
    return render_template('index.html', session_id=None)

@app.route('/get_session_id', methods=['GET'])
def get_session_id():
    check_session_state("get_session_id")
    return jsonify({"session_id": session['state']['session_id']})

@app.route('/debug_session')
def debug_session():
    return jsonify(_sanitize_for_json(session.get('state', {})))

@app.route('/check_session')
def check_session():
    return jsonify(_sanitize_for_json({
        'session_id': session.get('state', {}).get('session_id'),
        'session_contents': session.get('state', {})
    }))

@app.route('/get_llm_providers', methods=['GET'])
def get_llm_providers():
    """Get list of available LLM providers."""
    try:
        providers = [
            {'id': 'openai-codex', 'name': 'ChatGPT (Subscription)'},
            {'id': 'openai', 'name': 'OpenAI (API)'},
            {'id': 'anthropic', 'name': 'Anthropic (Claude)'},
            {'id': 'cohere', 'name': 'Cohere'},
            {'id': 'huggingface', 'name': 'HuggingFace'},
            {'id': 'local', 'name': 'Local Model'}
        ]
        
        return jsonify({
            "success": True,
            "providers": providers
        })
    except Exception as e:
        flask_logger.error(f"Error getting LLM providers: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
    
@app.route('/get_llm_models', methods=['GET'])
def get_llm_models():
    """Get list of available models for a provider."""
    try:
        provider = request.args.get('provider', 'local')
        
        # Set the provider in the LLM service
        llm_service.set_provider(provider)
        
        # Get the models
        models = llm_service.list_models(provider)
        
        return jsonify({
            "success": True,
            "models": models
        })
    except Exception as e:
        flask_logger.error(f"Error getting LLM models: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
    

@app.route('/get_llm_settings', methods=['GET'])
def get_llm_settings():
    """Get current LLM settings."""
    try:
        if 'state' not in session:
            return jsonify({"error": "No active session"}), 400
        
        session_state = session['state']
        llm_settings = session_state.get('llm_settings', {})
        
        # Default settings if not found
        if not llm_settings:
            llm_settings = {
                'provider': 'local',
                'model': None,
                'temperature': 0.7,
                'max_tokens': 150,
                'top_p': 0.9,
                'fallback_to_local': True
            }
        
        return jsonify({
            "success": True,
            "settings": llm_settings
        })
    except Exception as e:
        flask_logger.error(f"Error getting LLM settings: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
    
@app.route('/update_llm_settings', methods=['POST'])
def update_llm_settings():
    """Update LLM settings."""
    try:
        if 'state' not in session:
            return jsonify({"error": "No active session"}), 400
        
        # Get settings from request
        data = request.json
        if not data:
            return jsonify({
                "success": False,
                "error": "No data provided"
            }), 400
        
        provider = data.get('provider')
        model = data.get('model')
        temperature = data.get('temperature')
        max_tokens = data.get('max_tokens')
        top_p = data.get('top_p')
        fallback_to_local = data.get('fallback_to_local')
        
        # Update session state
        if 'llm_settings' not in session['state']:
            session['state']['llm_settings'] = {}
        
        llm_settings = session['state']['llm_settings']
        
        if provider:
            llm_settings['provider'] = provider
        if model:
            llm_settings['model'] = model
        if temperature is not None:
            llm_settings['temperature'] = float(temperature)
        if max_tokens is not None:
            llm_settings['max_tokens'] = int(max_tokens)
        if top_p is not None:
            llm_settings['top_p'] = float(top_p)
        if fallback_to_local is not None:
            llm_settings['fallback_to_local'] = bool(fallback_to_local)
        
        # Save API key if provided
        api_key = data.get('api_key')
        api_key_provider = data.get('api_key_provider', provider)
        
        if api_key and api_key_provider:
            # In a real application, you'd want to store this securely
            # For this example, we'll assume API keys are short-lived
            # and only kept in memory
            llm_service.set_api_key(api_key_provider, api_key)
        
        save_current_session(session['state'])
        
        return jsonify({
            "success": True,
            "settings": llm_settings
        })
    except Exception as e:
        flask_logger.error(f"Error updating LLM settings: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
    
@app.route('/test_llm_configuration', methods=['POST'])
def test_llm_configuration():
    """Test LLM configuration."""
    try:
        data = request.json
        if not data:
            return jsonify({
                "success": False,
                "error": "No data provided"
            }), 400
        
        provider = data.get('provider', 'local')
        model = data.get('model')
        api_key = data.get('api_key')
        
        # Set provider and API key in the LLM service
        llm_service.set_provider(provider)
        if api_key and provider != 'local':
            llm_service.set_api_key(provider, api_key)
        
        # Test prompt
        prompt = "Please respond with 'Configuration is working correctly'"
        
        # Options
        options = {
            'provider': provider,
            'model': model,
            'temperature': data.get('temperature', 0.7),
            'max_tokens': data.get('max_tokens', 50),
            'top_p': data.get('top_p', 0.9),
            'fallback_to_local': data.get('fallback_to_local', True),
            'offline_allowed': True  # Allow offline mode for testing
        }
        
        # Try to generate a completion
        response = llm_service.complete(prompt, options)
        
        return jsonify({
            "success": True,
            "response": response
        })
    except Exception as e:
        return handle_llm_error(e)
    
@app.route('/update_session', methods=['POST'])
def update_session():
    try:
        new_session_id = request.json['session_id']
        loaded_state = load_state(new_session_id)
        if loaded_state:
            session['state'] = loaded_state
            return jsonify({"status": "success", "message": "Session updated successfully", "new_session_id": new_session_id}), 200
        return jsonify({"status": "error", "message": "Session not found"}), 404
    except Exception as e:
        flask_logger.error(f"Error updating session: {str(e)}")
        return jsonify({"status": "error", "message": "Failed to update session"}), 500

@app.route('/static/<path:path>')
def send_static(path):
    return send_from_directory('static', path)

@app.route('/get_agents', methods=['GET'])
def get_agents():
    if 'state' not in session:
        return jsonify({"error": "No active session"}), 400

    session_state = session['state']
    agents_df = pd.DataFrame(session_state['agents_df'])

    agents = [{"id": row['agent_id'], "name": row['agent_name']} for _, row in agents_df.iterrows()]
    return jsonify(agents)

@app.route('/get_past_chats')
def get_past_chats():
    if 'state' not in session:
        return jsonify({"error": "No active session"}), 400

    past_chats = []
    current_chat_id = session['state']['session_id']
    for filename in os.listdir(cache_dir):
        if filename.endswith('_state.json'):
            file_path = os.path.join(cache_dir, filename)
            try:
                with open(file_path, 'r') as f:
                    state = json.load(f)
                    chat_id = filename.split('_')[0]
                    if chat_id == 'default':
                        continue  # Skip default settings file
                        
                    last_interaction = os.path.getmtime(file_path)

                    # Extract agent names from the state
                    agent_names = [agent['agent_name'] for agent in state.get('agents_df', [])]

                    past_chats.append({
                        'id': chat_id,
                        'user_name': state.get('user_name', 'User'),
                        'agent_names': agent_names,
                        'last_interaction': last_interaction,
                        'last_interaction_formatted': datetime.fromtimestamp(last_interaction).strftime('%Y-%m-%d %H:%M:%S'),
                        'is_current': chat_id == current_chat_id
                    })
            except Exception as e:
                flask_logger.error(f"Error loading chat file {filename}: {str(e)}")
                
    past_chats.sort(key=lambda x: x['last_interaction'], reverse=True)
    return jsonify(pastChats=past_chats)

@app.route('/load_chat/<chat_id>')
def load_chat(chat_id):
    session['state']['session_id'] = chat_id  # Update the current session ID
    state_file = os.path.join(cache_dir, f'{chat_id}_state.json')
    try:
        with open(state_file, 'r') as f:
            state = json.load(f)

        agent_data = state['agents_df']
        agent_id_to_name = {agent['agent_id']: agent['agent_name'] for agent in agent_data}

        def get_speaker_name(speaker_id):
            if speaker_id == 'user':
                return state['user_name']
            return agent_id_to_name.get(speaker_id, 'Unknown')

        chat_html = ''
        for entry in state['session_history']:
            speaker_id, message = entry
            speaker_name = get_speaker_name(speaker_id)
            if speaker_id == 'user':
                chat_html += f'<div class="message user"><p>{message}</p></div>'
            else:
                chat_html += f'<div class="message agent"><p><strong>{speaker_name}:</strong> {message}</p></div>'

        agent_names = [agent['agent_name'] for agent in agent_data]
        agent_descriptions = [agent['description'] for agent in agent_data]
        agent_goals = [agent['goal'] for agent in agent_data]
        
        # Update session state with loaded state
        session['state'] = state
        save_current_session(state)  # Update last interaction time

        # Return needed info for frontend
        return jsonify({
            'history': state['session_history'],
            'chatHtml': chat_html,
            'agentNames': agent_names,
            'agentDescriptions': agent_descriptions,
            'agentGoals': agent_goals,
            'settings': state['settings'],
            'userSettings': {
                'user_name': state['user_name']
            }
        })
        
    except Exception as e:
        flask_logger.error(f"Error loading chat {chat_id}: {str(e)}")
        return jsonify({"error": "Failed to load chat"}), 500

@app.route('/update_last_interaction', methods=['POST'])
def update_last_interaction():
    try:
        chat_id = request.form.get('chat_id')
        if not chat_id:
            return jsonify({"error": "No chat ID provided"}), 400
            
        state_file = os.path.join(cache_dir, f'{chat_id}_state.json')
        if os.path.exists(state_file):
            # Read the file
            with open(state_file, 'r') as f:
                state = json.load(f)
                
            # Write it back to update the modification time
            with open(state_file, 'w') as f:
                json.dump(state, f)
                
            return jsonify({"success": True})
        else:
            return jsonify({"error": "Chat file not found"}), 404
    except Exception as e:
        flask_logger.error(f"Error updating last interaction time: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/visualize_pyvis', methods=['GET'])
def visualize_pyvis_route():
    selected_agent_id = request.args.get('agent_id')
    selected_chat_id = request.args.get('chat_id')

    if 'state' not in session:
        return jsonify({"error": "No active session"}), 400

    session_state = session['state']
    agents_df = pd.DataFrame(session_state['agents_df'])

    if selected_agent_id:
        if selected_agent_id in agents_df['agent_id'].values:
            agent = agents_df[agents_df['agent_id'] == selected_agent_id].iloc[0]
            graph_file_path = agent['graph_file_path']
        else:
            return jsonify({"error": f"Agent not found: {selected_agent_id}"}), 404
    elif selected_chat_id:
        # Load the chat state to get agent graphs
        chat_state_file = os.path.join(cache_dir, f'{selected_chat_id}_state.json')
        if os.path.exists(chat_state_file):
            with open(chat_state_file, 'r') as f:
                chat_state = json.load(f)
                
            chat_agents_df = pd.DataFrame(chat_state['agents_df'])
            if len(chat_agents_df) > 0:
                graph_file_path = chat_agents_df.iloc[0]['graph_file_path']
            else:
                return jsonify({"error": "No agents found in selected chat"}), 404
        else:
            return jsonify({"error": f"Chat state file not found: {chat_state_file}"}), 404
    else:
        # If no agent is selected, use the first agent's graph
        if len(agents_df) > 0:
            graph_file_path = agents_df.iloc[0]['graph_file_path']
        else:
            return jsonify({"error": "No agents available"}), 404

    # Ensure the graph file exists
    if not os.path.exists(graph_file_path):
        # Create an empty graph file
        graph = nx.DiGraph()
        graph.add_node('start')
        nx.write_graphml(graph, graph_file_path)

    # Generate visualization
    try:
        session_id = session_state['session_id']
        output_filename = visualize_graph_pyvis(graph_file_path, session_id)
        if output_filename:
            app.logger.debug(f'Visualizing graph with PyVis for {selected_agent_id or selected_chat_id or "default"}')
            return jsonify({"graph_html": f"/static/{output_filename}"})
        else:
            return jsonify({"error": "Failed to generate graph visualization"}), 500
    except Exception as e:
        app.logger.error(f"Error visualizing graph: {str(e)}")
        return jsonify({"error": "Failed to visualize graph"}), 500

@app.route('/save_agent_settings', methods=['POST'])
def save_agent_settings():
    if 'state' not in session:
        return jsonify({"error": "No active session"}), 400
        
    try:
        agent_id = request.form.get('agent_id')
        agent_name = request.form.get('agent_name')
        description = request.form.get('description')
        goal = request.form.get('goal')
        muted = request.form.get('muted') == 'true'
        use_agent_vars = request.form.get('use_agent_generation_variables') == 'true'
        
        # Generation parameters
        gen_vars = {
            'seed': int(request.form.get('seed', 42)),
            'temperature': float(request.form.get('temperature', 0.7)),
            'max_tokens': int(request.form.get('max_tokens', 150)),
            'top_p': float(request.form.get('top_p', 0.9)),
            'use_gpu': request.form.get('use_gpu') == 'true',
            'llm': None
        }
        
        # Update agent in session
        agents_df = pd.DataFrame(session['state']['agents_df'])
        if agent_id and agent_id in agents_df['agent_id'].values:
            idx = agents_df[agents_df['agent_id'] == agent_id].index[0]
            agents_df.at[idx, 'agent_name'] = agent_name
            agents_df.at[idx, 'description'] = description
            agents_df.at[idx, 'goal'] = goal
            agents_df.at[idx, 'muted'] = muted
            agents_df.at[idx, 'is_agent_generation_variables'] = use_agent_vars
            agents_df.at[idx, 'generation_variables'] = gen_vars
        else:
            # Add new agent
            new_agent = {
                'agent_id': generate_agent_id(),
                'agent_name': agent_name,
                'description': description,
                'goal': goal,
                'muted': muted,
                'environment': 'default',
                'graph_file_path': f"agent_{generate_agent_id()}_graph.graphml",
                'persistance_count': 0,
                'persistance_score': None,
                'patience': 6,
                'persistance': 3,
                'last_response': '',
                'last_narration': '',
                'current_aim': None,
                'suggestion': '',
                'current_node_location': 'start',
                'personal_history': [],
                'is_agent_generation_variables': use_agent_vars,
                'generation_variables': gen_vars,
                'impression_of_others': '',
                'environment_changes': '',
                'new_information': ''
            }
            
            # Initialize agent graph
            graph = nx.DiGraph()
            graph.add_node('start')
            nx.write_graphml(graph, os.path.join(graph_directory, new_agent['graph_file_path']))
            
            agents_df = pd.concat([agents_df, pd.DataFrame([new_agent])], ignore_index=True)
            session['state']['agent_mutes'].append(False)
            session['state']['number_of_agents'] += 1
        
        session['state']['agents_df'] = agents_df.to_dict('records')
        save_current_session(session['state'])
        
        return jsonify({
            "success": True,
            "message": "Agent settings saved",
            "agents": [{"id": row['agent_id'], "name": row['agent_name']} for _, row in agents_df.iterrows()]
        })
        
    except Exception as e:
        flask_logger.error(f"Error saving agent settings: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/delete_agent', methods=['POST'])
def delete_agent():
    if 'state' not in session:
        return jsonify({"error": "No active session"}), 400
        
    agent_id = request.form.get('agent_id')
    session_state = session['state']
    agents_df = pd.DataFrame(session_state['agents_df'])

    if agent_id in agents_df['agent_id'].values:
        # Get the index of the agent to delete
        agent_index = agents_df[agents_df['agent_id'] == agent_id].index[0]
        agent = agents_df.loc[agent_index]

        # Delete graph file
        graph_file = agent['graph_file_path']
        if os.path.exists(graph_file):
            os.remove(graph_file)

        # Remove agent from DataFrame
        agents_df = agents_df.drop(agent_index).reset_index(drop=True)
        session_state['agents_df'] = agents_df.to_dict('records')
        session_state['number_of_agents'] -= 1

        # Remove corresponding mute status
        if len(session_state['agent_mutes']) > agent_index:
            session_state['agent_mutes'].pop(agent_index)

        save_current_session(session_state)

        return jsonify({
            "success": True, 
            "message": "Agent deleted successfully",
            "agents": [{"id": row['agent_id'], "name": row['agent_name']} for _, row in agents_df.iterrows()]
        })
    else:
        return jsonify({"success": False, "message": "Agent not found"}), 404

@app.route('/import_graph', methods=['POST'])
def import_graph_route():
    """Import one agent's graph into another agent's graph."""
    if 'state' not in session:
        return jsonify({"error": "No active session"}), 400

    from agent.graph_intelligence import import_graph as gi_import, link_similar_nodes

    target_agent_id = request.form.get('target_agent_id')
    source_agent_id = request.form.get('source_agent_id')
    namespace = request.form.get('namespace', '')  # empty = merge nodes by name
    link_similar = request.form.get('link_similar', 'true').lower() == 'true'

    agents_df = pd.DataFrame(session['state']['agents_df'])

    target_row = agents_df[agents_df['agent_id'] == target_agent_id]
    source_row = agents_df[agents_df['agent_id'] == source_agent_id]

    if target_row.empty or source_row.empty:
        return jsonify({"success": False, "message": "Agent not found"}), 404

    target_path = target_row.iloc[0]['graph_file_path']
    source_path = source_row.iloc[0]['graph_file_path']

    try:
        target_G = nx.read_graphml(target_path)
        source_G = nx.read_graphml(source_path)

        gi_import(target_G, source_G, namespace=namespace or None)

        if link_similar:
            link_similar_nodes(target_G, similarity_threshold=0.8)

        nx.write_graphml(target_G, target_path)

        return jsonify({
            "success": True,
            "message": f"Imported graph from {source_agent_id} into {target_agent_id}",
            "nodes": target_G.number_of_nodes(),
            "edges": target_G.number_of_edges()
        })
    except Exception as e:
        flask_logger.error(f"Error importing graph: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/combine_graphs', methods=['POST'])
def combine_graphs_route():
    """Combine multiple agents' graphs into a target agent's graph."""
    if 'state' not in session:
        return jsonify({"error": "No active session"}), 400

    from agent.graph_intelligence import combine_graphs as gi_combine, link_similar_nodes

    data = request.get_json() or {}
    target_agent_id = data.get('target_agent_id')
    source_agent_ids = data.get('source_agent_ids', [])
    link_similar = data.get('link_similar', True)

    agents_df = pd.DataFrame(session['state']['agents_df'])

    target_row = agents_df[agents_df['agent_id'] == target_agent_id]
    if target_row.empty:
        return jsonify({"success": False, "message": "Target agent not found"}), 404

    target_path = target_row.iloc[0]['graph_file_path']

    graphs = []
    names = []
    for aid in source_agent_ids:
        row = agents_df[agents_df['agent_id'] == aid]
        if row.empty:
            continue
        path = row.iloc[0]['graph_file_path']
        try:
            G = nx.read_graphml(path)
            graphs.append(G)
            names.append(row.iloc[0]['agent_name'])
        except Exception as e:
            flask_logger.warning(f"Could not read graph for {aid}: {e}")

    if not graphs:
        return jsonify({"success": False, "message": "No valid source graphs found"}), 400

    try:
        combined = gi_combine(graphs)

        if link_similar:
            link_similar_nodes(combined, similarity_threshold=0.8)

        nx.write_graphml(combined, target_path)

        return jsonify({
            "success": True,
            "message": f"Combined {len(graphs)} graphs into {target_agent_id}",
            "source_agents": names,
            "nodes": combined.number_of_nodes(),
            "edges": combined.number_of_edges()
        })
    except Exception as e:
        flask_logger.error(f"Error combining graphs: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/graph_info/<agent_id>', methods=['GET'])
def graph_info(agent_id):
    """Get info about an agent's graph: nodes, edges, and path to goal."""
    if 'state' not in session:
        return jsonify({"error": "No active session"}), 400

    from agent.graph_intelligence import find_path_to_goal

    agents_df = pd.DataFrame(session['state']['agents_df'])
    row = agents_df[agents_df['agent_id'] == agent_id]

    if row.empty:
        return jsonify({"error": "Agent not found"}), 404

    agent = row.iloc[0]
    graph_path = agent['graph_file_path']

    try:
        G = nx.read_graphml(graph_path)
    except Exception:
        return jsonify({"nodes": 0, "edges": 0, "path_to_goal": None})

    # Try finding a path to goal
    path_info = None
    current_node = agent['current_node_location']
    goal = agent['goal']

    result = find_path_to_goal(G, current_node, goal)
    if result:
        path, target, similarity = result
        path_info = {
            "path": path,
            "target_node": target,
            "similarity": round(similarity, 3)
        }

    # Collect node info
    go_nodes = []
    nogo_nodes = []
    for u, v, data in G.edges(data=True):
        if data.get('label') == 'Go':
            go_nodes.append(v)
        elif data.get('label') == 'NoGo':
            nogo_nodes.append(v)

    return jsonify({
        "nodes": G.number_of_nodes(),
        "edges": G.number_of_edges(),
        "current_node": current_node,
        "go_nodes": go_nodes,
        "nogo_nodes": nogo_nodes,
        "path_to_goal": path_info
    })


@app.route('/submit', methods=['POST'])
def submit():
    flask_logger.info("Entering submit function")
    try:
        # Load the agent module
        agent_module = reload_agent()
        main = agent_module.offline_main if offline else agent_module.main
        flask_logger.info("Agent module reloaded successfully")

        check_session_state("submit")

        # If play is true, interrupt the current generation
        if session['state'].get('play', False):
            session['state']['play'] = False
            flask_logger.info("Play was true, setting to false and returning")
            return jsonify({
                "success": True,
                "history": session['state']['session_history'],
                "play": False
            })

        # Get user message and is_user flag from client side
        user_message = request.form.get('user_message', '')
        is_user = request.form.get('is_user') == 'true'
        flask_logger.info(f"Received user message: '{user_message}', is_user: {is_user}")

        # Record user message in history if is_user is true
        if is_user and user_message:
            # In agent_agent mode the human acts as a narrator, not a participant
            if session['state'].get('chat_mode') == 'agent_agent':
                session['state']['session_history'].append(("narrator", str(user_message)))
            else:
                session['state']['session_history'].append(("user", str(user_message)))
            session['state']['is_user'] = is_user
            session['state']['user_message'] = user_message
            flask_logger.info(f"Added user message to session history: '{user_message}'")
        else:
            flask_logger.info("No user message added to session history")

        # Get the max_generations value
        # For multi-agent conversation: allow several rounds of back-and-forth
        num_agents = len(session['state']['agents_df'])
        max_rounds = 6  # Each agent speaks this many times
        max_generations = num_agents * max_rounds
        flask_logger.info(f"Set max_generations to {max_generations}")

        # Initialize the generation process
        session['state']['current_generation'] = 0
        session['state']['max_generations'] = max_generations
        session['state']['play'] = True
        flask_logger.info("Initialized generation process variables")
        
        # Save the session state
        save_current_session(session['state'])

        response = jsonify({
            "success": True,
            "max_generations": max_generations,
            "history": session['state']['session_history'],
            "play": session['state']['play']
        })
        flask_logger.info(f"Submit response prepared: {response.get_data(as_text=True)}")
        flask_logger.info("Exiting submit function successfully")
        return response

    except Exception as e:
        flask_logger.error(f"Error in submit function: {str(e)}", exc_info=True)
        return jsonify({
            "success": False, 
            "error": f"Error in submit function: {str(e)}"
        }), 500

@app.route('/generate', methods=['GET'])
def generate():
    flask_logger.info("Entering generate function")
    try:
        # Check if there's an active session
        if 'state' not in session:
            flask_logger.error("No active session in generate function")
            return jsonify({"error": "No active session"}), 400

        # Load the agent module
        agent_module = reload_agent()
        main = agent_module.offline_main if offline else agent_module.main

        # Check if generation should continue
        flask_logger.info(f"Current play status: {session['state']['play']}")
        if not session['state']['play']:
            flask_logger.info("Generation stopped due to play status")
            return jsonify({"complete": True, "play": False})

        # Check if max generations reached
        flask_logger.info(f"Current generation: {session['state']['current_generation']}, Max generations: {session['state']['max_generations']}")
        if session['state']['current_generation'] >= session['state']['max_generations']:
            flask_logger.info("Generation complete")
            session['state']['play'] = False
            save_current_session(session['state'])
            return jsonify({"complete": True, "play": False})

        # Prep variables for main function
        # After user submits, first generate call is user turn; subsequent calls are agent turns
        is_user = session['state']['is_user']
        if is_user:
            session['state']['is_user'] = False  # Next call will be agent turn
        agents_df = pd.DataFrame(session['state']['agents_df'])
        settings = session['state']['settings']
        user_name = session['state']['user_name']
        agent_mutes = session['state'].get('agent_mutes', [])
        len_last_history = session['state'].get('len_last_history', 0)

        # Get LLM settings from session state
        llm_settings = session['state'].get('llm_settings', {})
        if llm_settings:
            # Update settings with LLM configuration
            settings.update(llm_settings)
        
        # Pass current_generation so agent.main() can round-robin agents
        current_gen = session['state']['current_generation']

        # Call the main function
        flask_logger.info(f"Calling main function with: is_user={is_user}, user_name={user_name}, agent_mutes={agent_mutes}, len_last_history={len_last_history}, turn={current_gen}")
        new_history, new_agents_df, logs = main(
            session['state']['session_history'],
            agents_df,
            settings,
            user_name,
            is_user,
            agent_mutes,
            len_last_history,
            turn_index=current_gen
        )

        # Check if new response was generated
        if len(new_history) > len(session['state']['session_history']):
            latest_response = new_history[-1]
            flask_logger.info(f"New response generated: {latest_response}")
        else:
            flask_logger.info("No new response generated")

        # Update session state
        session['state']['session_history'] = new_history
        # Don't update len_last_history here — it's set on submit only
        # so agent.main() can use turn_index for multi-agent round-robin
        session['state']['agents_df'] = new_agents_df.to_dict('records')
        session['state']['current_generation'] += 1

        # Determine if generation should continue
        continue_generation = session['state']['current_generation'] < session['state']['max_generations']
        session['state']['play'] = continue_generation
        flask_logger.info(f"Updated play status: {session['state']['play']}")

        # Save the updated session
        save_current_session(session['state'])

        # Prepare and return response
        response = jsonify({
            "history": session['state']['session_history'],
            "logs": logs,
            "play": session['state']['play'],
            "clear_chatbox": True,
            "current_generation": session['state']['current_generation'],
            "max_generations": session['state']['max_generations']
        })
        flask_logger.info("Exiting generate function successfully")
        return response

    except Exception as e:
        flask_logger.error(f"Error in generate function: {str(e)}", exc_info=True)
        session['state']['play'] = False
        save_current_session(session['state'])
        return jsonify({
            "error": str(e), 
            "play": False
        }), 500

@app.route('/reset', methods=['POST'])
def reset_chat():
    """
    Reset the current chat - clears history and environment, but keeps agent settings.
    This follows the 'restart option' in the TODO list.
    """
    try:
        if 'state' not in session:
            return jsonify({"error": "No active session"}), 400
            
        # Keep the existing session ID and agent settings
        session_id = session['state']['session_id']
        agents_df = pd.DataFrame(session['state']['agents_df'])
        settings = session['state']['settings']
        user_name = session['state']['user_name']
        
        # Reset dynamic conversation elements
        for idx, agent in agents_df.iterrows():
            agents_df.at[idx, 'current_aim'] = None
            agents_df.at[idx, 'suggestion'] = ''
            agents_df.at[idx, 'persistance_count'] = 0
            agents_df.at[idx, 'persistance_score'] = None
            agents_df.at[idx, 'last_response'] = ''
            agents_df.at[idx, 'last_narration'] = ''
            agents_df.at[idx, 'personal_history'] = []
            agents_df.at[idx, 'current_node_location'] = 'start'
            agents_df.at[idx, 'impression_of_others'] = ''
            agents_df.at[idx, 'environment_changes'] = ''
            agents_df.at[idx, 'new_information'] = ''
        
        # Reset session state but keep settings
        session['state'] = {
            'session_id': session_id,
            'user_name': user_name,
            'agent_mutes': [False] * len(agents_df),
            'agents_df': agents_df.to_dict('records'),
            'session_history': [],
            'len_last_history': 0,
            'settings': settings,
            'play': False,
            'is_user': False,
            'max_generations': 0,
            'current_generation': 0,
            'user_message': '',
            'number_of_agents': len(agents_df)
        }
        
        # Save the reset state
        save_current_session(session['state'])
        
        return jsonify({
            "success": True,
            "message": "Chat reset successfully"
        })
    except Exception as e:
        flask_logger.error(f"Error resetting chat: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/duplicate', methods=['POST'])
def duplicate_chat():
    """
    Duplicate the current chat - creates a new chat with the same state.
    This follows the 'duplicate chat option' in the TODO list.
    """
    try:
        if 'state' not in session:
            return jsonify({"error": "No active session"}), 400
            
        # Copy the current state
        current_state = session['state'].copy()
        
        # Generate a new session ID
        new_session_id = generate_session_id()
        current_state['session_id'] = new_session_id
        
        # Save as a new chat
        save_current_session(current_state)
        
        # Update the session to use the new chat
        session['state'] = current_state
        
        return jsonify({
            "success": True,
            "message": "Chat duplicated successfully",
            "new_session_id": new_session_id
        })
    except Exception as e:
        flask_logger.error(f"Error duplicating chat: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/create_new_chat', methods=['POST'])
def create_new_chat():
    """
    Create a new chat.  Accepts an optional JSON body to configure agents
    from presets and optionally assign saved graphs:

        {
          "mode": "agent_agent" | "user_agent",
          "preset_ids": ["preset_abc", "preset_def"],
          "graph_assignments": {"preset_abc": "graph_123"}
        }

    When no body (or no preset_ids) is provided the route falls back to the
    original defaults_session.json behaviour so it stays backward-compatible.
    """
    try:
        import shutil

        data = request.get_json(silent=True) or {}
        preset_ids = data.get('preset_ids', [])

        if preset_ids:
            # ── Preset-driven session creation ──────────────────────────
            mode = data.get('mode', 'user_agent')
            graph_assignments = data.get('graph_assignments', {})

            defaults = load_default_settings()
            session_id = generate_session_id()

            agents = []
            for pid in preset_ids:
                preset_path = os.path.join(agent_library_dir, f"{pid}.json")
                if not os.path.exists(preset_path):
                    return jsonify({
                        "success": False,
                        "error": f"Preset {pid} not found"
                    }), 404
                with open(preset_path, 'r') as f:
                    preset = json.load(f)

                agent_id = generate_agent_id()
                graph_file_path = os.path.join(graph_directory, f"{agent_id}_graph.graphml")

                # If a saved graph is assigned, copy it; otherwise init empty
                assigned_graph_id = graph_assignments.get(pid)
                if assigned_graph_id:
                    src_gml = os.path.join(saved_graphs_dir, f"{assigned_graph_id}.graphml")
                    if os.path.exists(src_gml):
                        shutil.copy2(src_gml, graph_file_path)
                    else:
                        graph = nx.DiGraph()
                        graph.add_node('start')
                        nx.write_graphml(graph, graph_file_path)
                else:
                    graph = nx.DiGraph()
                    graph.add_node('start')
                    nx.write_graphml(graph, graph_file_path)

                # Build per-agent generation variables with provider/model if set
                agent_provider = preset.get('provider', '')
                agent_model = preset.get('model', '')
                has_custom_llm = bool(agent_provider and agent_model)

                gen_vars = {
                    'seed': 42,
                    'temperature': 0.7,
                    'max_tokens': 250,
                    'top_p': 0.9,
                    'use_gpu': True,
                    'llm': None
                }
                if has_custom_llm:
                    gen_vars['provider'] = agent_provider
                    gen_vars['model'] = agent_model

                agent = {
                    'agent_id': agent_id,
                    'agent_name': preset.get('agent_name', 'Unnamed Agent'),
                    'description': preset.get('description', ''),
                    'goal': preset.get('goal', ''),
                    'target_impression': preset.get('target_impression', ''),
                    'muted': False,
                    'environment': 'default',
                    'graph_file_path': graph_file_path,
                    'persistance_count': 0,
                    'persistance_score': None,
                    'patience': 8,
                    'persistance': 4,
                    'last_response': '',
                    'last_narration': '',
                    'current_aim': None,
                    'suggestion': '',
                    'current_node_location': 'start',
                    'personal_history': [],
                    'is_agent_generation_variables': has_custom_llm,
                    'generation_variables': gen_vars,
                    'impression_of_others': '',
                    'environment_changes': '',
                    'new_information': ''
                }
                agents.append(agent)

            agents_df = pd.DataFrame(agents)

            session_state = {
                'session_id': session_id,
                'user_name': defaults['user_name'],
                'agent_mutes': [False] * len(agents_df),
                'agents_df': agents_df.to_dict('records'),
                'session_history': [],
                'len_last_history': defaults['len_last_history'],
                'settings': defaults['settings'],
                'play': False,
                'is_user': False,
                'max_generations': 0,
                'current_generation': 0,
                'user_message': '',
                'number_of_agents': len(agents_df),
                'chat_mode': mode
            }

            if 'llm_settings' in defaults:
                session_state['llm_settings'] = defaults['llm_settings']

            save_current_session(session_state)
            session['state'] = session_state

            return jsonify({
                "success": True,
                "message": "New chat created from presets",
                "session_id": session_id,
                "chat_mode": mode,
                "redirect_to": "agent"
            })
        else:
            # ── Default behaviour (backward-compatible) ─────────────────
            new_session = initialize_session()
            session['state'] = new_session

            return jsonify({
                "success": True,
                "message": "New chat created",
                "session_id": new_session['session_id'],
                "redirect_to": "agent"
            })
    except Exception as e:
        flask_logger.error(f"Error creating new chat: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/delete_chat', methods=['POST'])
def delete_chat():
    """
    Delete the current chat from cache and create a new one.
    This follows the 'delete chat option' in the TODO list.
    """
    try:
        if 'state' not in session:
            return jsonify({"error": "No active session"}), 400
            
        # Get the current session ID
        session_id = session['state']['session_id']
        
        # Delete the cache file
        state_file = os.path.join(cache_dir, f'{session_id}_state.json')
        if os.path.exists(state_file):
            os.remove(state_file)
            
        # Create a new session
        new_session = initialize_session()
        session['state'] = new_session
        
        return jsonify({
            "success": True,
            "message": "Chat deleted and new chat created",
            "session_id": new_session['session_id'],
            "redirect_to": "agent"  # Redirect to settings page
        })
    except Exception as e:
        flask_logger.error(f"Error deleting chat: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/rename_chat', methods=['POST'])
def rename_chat():
    """
    Rename the current chat.
    This handles the chat renaming functionality mentioned in the TODO list.
    """
    try:
        if 'state' not in session:
            return jsonify({"error": "No active session"}), 400
            
        # Get the new name from the request
        new_name = request.form.get('new_name')
        if not new_name:
            return jsonify({
                "success": False,
                "error": "No name provided"
            }), 400
            
        # Update the chat name
        session['state']['chat_name'] = new_name
        save_current_session(session['state'])
        
        return jsonify({
            "success": True,
            "message": "Chat renamed successfully",
            "new_name": new_name
        })
    except Exception as e:
        flask_logger.error(f"Error renaming chat: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/update_user_settings', methods=['POST'])
def update_user_settings():
    """
    Update user settings for the current session.
    """
    try:
        if 'state' not in session:
            return jsonify({"error": "No active session"}), 400
            
        user_name = request.form.get('user_name')
        if user_name:
            session['state']['user_name'] = user_name
            
        # Update generation settings if provided
        for param in ['temperature', 'max_tokens', 'top_p', 'seed']:
            if param in request.form:
                try:
                    value = request.form.get(param)
                    if param in ['temperature', 'top_p']:
                        session['state']['settings'][param] = float(value)
                    else:
                        session['state']['settings'][param] = int(value)
                except ValueError:
                    flask_logger.warning(f"Invalid value for {param}: {value}")
        
        # Update use_gpu setting
        use_gpu = request.form.get('use_gpu')
        if use_gpu is not None:
            session['state']['settings']['use_gpu'] = use_gpu.lower() == 'true'
            
        # Save the updated session
        save_current_session(session['state'])
        
        return jsonify({
            "success": True,
            "message": "User settings updated successfully",
            "settings": session['state']['settings'],
            "user_name": session['state']['user_name']
        })
    except Exception as e:
        flask_logger.error(f"Error updating user settings: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/set_chat_mode', methods=['POST'])
def set_chat_mode():
    """
    Set the chat mode to either user-agent or agent-agent.
    This implements the functionality for "User x Agent" OR "Agent x Agent" option.
    """
    try:
        if 'state' not in session:
            return jsonify({"error": "No active session"}), 400
            
        mode = request.form.get('mode')
        if not mode or mode not in ['user_agent', 'agent_agent']:
            return jsonify({
                "success": False,
                "error": "Invalid chat mode specified"
            }), 400
            
        # Update the chat mode
        session['state']['chat_mode'] = mode
        
        # For agent-agent mode, ensure we have at least two agents
        if mode == 'agent_agent':
            agents_df = pd.DataFrame(session['state']['agents_df'])
            if len(agents_df) < 2:
                # Add a second agent if needed
                default_agent = load_default_settings()['agents_df'][1]  # Get the second default agent
                add_single_agent_to_session(default_agent)
                
        save_current_session(session['state'])
        
        return jsonify({
            "success": True,
            "message": f"Chat mode set to {mode}",
            "chat_mode": mode,
            "agent_count": session['state']['number_of_agents']
        })
    except Exception as e:
        flask_logger.error(f"Error setting chat mode: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/toggle_agent_mute', methods=['POST'])
def toggle_agent_mute():
    """
    Toggle mute status for a specific agent
    """
    try:
        if 'state' not in session:
            return jsonify({"error": "No active session"}), 400
            
        agent_id = request.form.get('agent_id')
        if not agent_id:
            return jsonify({
                "success": False,
                "error": "No agent ID provided"
            }), 400
            
        # Find the agent
        agents_df = pd.DataFrame(session['state']['agents_df'])
        if agent_id not in agents_df['agent_id'].values:
            return jsonify({
                "success": False,
                "error": "Agent not found"
            }), 404
            
        # Get the agent index
        agent_index = agents_df[agents_df['agent_id'] == agent_id].index[0]
        
        # Toggle mute status
        agents_df.at[agent_index, 'muted'] = not agents_df.at[agent_index, 'muted']
        session['state']['agents_df'] = agents_df.to_dict('records')
        
        # Update agent_mutes array to match
        session['state']['agent_mutes'][agent_index] = agents_df.at[agent_index, 'muted']
        
        save_current_session(session['state'])
        
        return jsonify({
            "success": True,
            "agent_id": agent_id,
            "muted": agents_df.at[agent_index, 'muted']
        })
    except Exception as e:
        flask_logger.error(f"Error toggling agent mute status: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/respond_as_agent', methods=['POST'])
def respond_as_agent():
    """
    Add a response to the chat as if it came from a specific agent.
    This enables manual interaction in agent-agent mode.
    """
    try:
        if 'state' not in session:
            return jsonify({"error": "No active session"}), 400
            
        agent_id = request.form.get('agent_id')
        message = request.form.get('message')
        
        if not agent_id or not message:
            return jsonify({
                "success": False,
                "error": "Agent ID and message are required"
            }), 400
            
        # Find the agent
        agents_df = pd.DataFrame(session['state']['agents_df'])
        if agent_id not in agents_df['agent_id'].values:
            return jsonify({
                "success": False,
                "error": "Agent not found"
            }), 404
            
        # Add the message to the history
        session['state']['session_history'].append((agent_id, message))
        session['state']['len_last_history'] = len(session['state']['session_history'])
        
        # Update agent personal histories
        for idx, agent in agents_df.iterrows():
            if not agent['muted']:
                personal_history = agent['personal_history']
                personal_history.append((agent_id, message))
                agents_df.at[idx, 'personal_history'] = personal_history
                
        session['state']['agents_df'] = agents_df.to_dict('records')
        save_current_session(session['state'])
        
        return jsonify({
            "success": True,
            "history": session['state']['session_history']
        })
    except Exception as e:
        flask_logger.error(f"Error adding agent response: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/delete_last_response', methods=['POST'])
def delete_last_response():
    """
    Delete the last response in the chat history.
    """
    try:
        if 'state' not in session:
            return jsonify({"error": "No active session"}), 400
            
        if not session['state']['session_history']:
            return jsonify({
                "success": False,
                "error": "No messages to delete"
            }), 400
            
        # Remove the last message
        session['state']['session_history'].pop()
        session['state']['len_last_history'] = len(session['state']['session_history'])
        
        # Update agent personal histories
        agents_df = pd.DataFrame(session['state']['agents_df'])
        for idx, agent in agents_df.iterrows():
            personal_history = agent['personal_history']
            if personal_history:
                personal_history.pop()
                agents_df.at[idx, 'personal_history'] = personal_history
                
        session['state']['agents_df'] = agents_df.to_dict('records')
        save_current_session(session['state'])
        
        return jsonify({
            "success": True,
            "history": session['state']['session_history']
        })
    except Exception as e:
        flask_logger.error(f"Error deleting last response: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/update_generation_parameters', methods=['POST'])
def update_generation_parameters():
    """
    Update advanced generation parameters for the session or specific agent.
    This implements the "additional generation parameters" requirement.
    """
    try:
        if 'state' not in session:
            return jsonify({"error": "No active session"}), 400
            
        agent_id = request.form.get('agent_id')
        
        # Parameters to update
        params = {}
        for param in ['temperature', 'max_tokens', 'top_p', 'seed', 'top_k', 'repetition_penalty']:
            if param in request.form:
                try:
                    value = request.form.get(param)
                    if param in ['temperature', 'top_p', 'repetition_penalty']:
                        params[param] = float(value)
                    else:
                        params[param] = int(value)
                except ValueError:
                    flask_logger.warning(f"Invalid value for {param}: {value}")
        
        if 'use_gpu' in request.form:
            params['use_gpu'] = request.form.get('use_gpu').lower() == 'true'
            
        # If agent_id is provided, update that specific agent
        if agent_id:
            agents_df = pd.DataFrame(session['state']['agents_df'])
            if agent_id in agents_df['agent_id'].values:
                idx = agents_df[agents_df['agent_id'] == agent_id].index[0]
                for param, value in params.items():
                    agents_df.at[idx, 'generation_variables'][param] = value
                session['state']['agents_df'] = agents_df.to_dict('records')
            else:
                return jsonify({
                    "success": False,
                    "error": "Agent not found"
                }), 404
        # Otherwise update session settings
        else:
            for param, value in params.items():
                session['state']['settings'][param] = value
        
        save_current_session(session['state'])
        
        return jsonify({
            "success": True,
            "message": f"Generation parameters updated for {'agent '+agent_id if agent_id else 'session'}"
        })
    except Exception as e:
        flask_logger.error(f"Error updating generation parameters: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/save_graph', methods=['POST'])
def save_graph():
    """
    Save the current graph to a file.
    This implements the "option to save down Graph" requirement.
    """
    try:
        if 'state' not in session:
            return jsonify({"error": "No active session"}), 400
            
        agent_id = request.form.get('agent_id')
        if not agent_id:
            return jsonify({
                "success": False,
                "error": "No agent ID provided"
            }), 400
            
        # Find the agent
        agents_df = pd.DataFrame(session['state']['agents_df'])
        if agent_id not in agents_df['agent_id'].values:
            return jsonify({
                "success": False,
                "error": "Agent not found"
            }), 404
            
        agent = agents_df[agents_df['agent_id'] == agent_id].iloc[0]
        graph_file_path = agent['graph_file_path']
        
        if not os.path.exists(graph_file_path):
            return jsonify({
                "success": False,
                "error": "Graph file not found"
            }), 404
            
        # Generate the visualization
        session_id = session['state']['session_id']
        output_filename = visualize_graph_pyvis(graph_file_path, session_id)
        
        if not output_filename:
            return jsonify({
                "success": False,
                "error": "Failed to generate graph visualization"
            }), 500
            
        # Create a download URL
        download_url = f"/static/{output_filename}"
        
        return jsonify({
            "success": True,
            "download_url": download_url,
            "agent_name": agent['agent_name']
        })
    except Exception as e:
        flask_logger.error(f"Error saving graph: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/export_chat_json', methods=['POST'])
def export_chat_json():
    """
    Export the current chat state as a JSON file.
    This implements the "option to save down Json" requirement.
    """
    try:
        if 'state' not in session:
            return jsonify({"error": "No active session"}), 400
            
        # Create a copy of the state to sanitize
        export_state = session['state'].copy()
        
        # Remove any sensitive or unnecessary information
        if 'llm' in export_state.get('settings', {}):
            export_state['settings']['llm'] = None
            
        for agent in export_state.get('agents_df', []):
            if 'llm' in agent.get('generation_variables', {}):
                agent['generation_variables']['llm'] = None
        
        # Generate a filename based on agent and user names
        user_name = export_state.get('user_name', 'User').replace(' ', '_')
        agent_names = '_'.join([agent['agent_name'].replace(' ', '_') for agent in export_state.get('agents_df', [])])
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{user_name}_{agent_names}_{timestamp}.json"
        
        # Save the file
        export_path = os.path.join(app.static_folder, filename)
        with open(export_path, 'w') as f:
            json.dump(export_state, f, indent=2)
        
        # Create a download URL
        download_url = f"/static/{filename}"
        
        return jsonify({
            "success": True,
            "download_url": download_url,
            "filename": filename
        })
    except Exception as e:
        flask_logger.error(f"Error exporting chat: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/interrupt', methods=['POST'])
def interrupt():
    """
    Interrupt the current generation process.
    """
    if 'state' in session:
        session['state']['play'] = False
        save_current_session(session['state'])
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "No active session"}), 400

@app.route('/add_agent', methods=['POST'])
def add_agent():
    if 'state' not in session:
        return jsonify({"error": "No active session"}), 400

    try:
        # Create a new agent with default settings
        agent_id = generate_agent_id()
        new_agent = {
            'agent_id': agent_id,
            'agent_name': 'New Agent',
            'muted': False,
            'description': 'A new intelligent agent',
            'environment': 'default',
            'graph_file_path': os.path.join(graph_directory, f"{agent_id}_graph.graphml"),
            'persistance_count': 0,
            'persistance_score': None,
            'patience': 6,
            'persistance': 3,
            'last_response': '',
            'last_narration': '',
            'goal': 'Complete a task',
            'current_aim': None,
            'suggestion': '',
            'current_node_location': 'start',
            'personal_history': [],
            'is_agent_generation_variables': True,
            'generation_variables': {
                'seed': 42,
                'temperature': 0.7,
                'max_tokens': 150,
                'top_p': 0.9,
                'use_gpu': True,
                'llm': None
            },
            'impression_of_others': '',
            'environment_changes': '',
            'new_information': ''
        }

        # Initialize agent graph
        graph = nx.DiGraph()
        graph.add_node('start')
        nx.write_graphml(graph, new_agent['graph_file_path'])

        # Add the new agent to the session
        agents_df = pd.DataFrame(session['state']['agents_df'])
        agents_df = pd.concat([agents_df, pd.DataFrame([new_agent])], ignore_index=True)
        session['state']['agents_df'] = agents_df.to_dict('records')
        session['state']['agent_mutes'].append(False)
        session['state']['number_of_agents'] += 1

        save_current_session(session['state'])

        return jsonify({
            "success": True,
            "message": "New agent added",
            "agent": {
                "id": new_agent['agent_id'],
                "name": new_agent['agent_name']
            }
        })
    except Exception as e:
        flask_logger.error(f"Error adding new agent: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/logs', methods=['GET'])
def get_logs_route():
    """Get application logs."""
    logs = get_logs()
    return jsonify({"logs": logs, "timestamp": time.time()})

@app.route('/get_agent_graphs', methods=['GET'])
def get_agent_graphs():
    """Get list of agents with their graph info."""
    if 'state' not in session:
        return jsonify({"error": "No active session"}), 400
    agents_df = pd.DataFrame(session['state']['agents_df'])
    graphs = [{"id": row['agent_id'], "name": row['agent_name']} for _, row in agents_df.iterrows()]
    return jsonify(graphs)

### ─── Agent Library CRUD ───────────────────────────────────────────────

@app.route('/api/agent_library', methods=['GET'])
def list_agent_presets():
    """List all saved agent presets."""
    try:
        presets = []
        for filename in os.listdir(agent_library_dir):
            if filename.endswith('.json'):
                filepath = os.path.join(agent_library_dir, filename)
                with open(filepath, 'r') as f:
                    preset = json.load(f)
                    presets.append(preset)
        return jsonify({"success": True, "presets": presets})
    except Exception as e:
        flask_logger.error(f"Error listing agent presets: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/agent_library', methods=['POST'])
def create_agent_preset():
    """Create a new agent preset."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400

        preset_id = f"preset_{uuid.uuid4()}"
        preset = {
            "preset_id": preset_id,
            "agent_name": data.get("agent_name", "Unnamed Agent"),
            "description": data.get("description", ""),
            "goal": data.get("goal", ""),
            "target_impression": data.get("target_impression", ""),
            "provider": data.get("provider", ""),
            "model": data.get("model", ""),
            "created_at": datetime.now().isoformat()
        }

        filepath = os.path.join(agent_library_dir, f"{preset_id}.json")
        with open(filepath, 'w') as f:
            json.dump(preset, f, indent=2)

        return jsonify({"success": True, "preset": preset}), 201
    except Exception as e:
        flask_logger.error(f"Error creating agent preset: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/agent_library/<preset_id>', methods=['PUT'])
def update_agent_preset(preset_id):
    """Update an existing agent preset."""
    try:
        filepath = os.path.join(agent_library_dir, f"{preset_id}.json")
        if not os.path.exists(filepath):
            return jsonify({"success": False, "error": "Preset not found"}), 404

        with open(filepath, 'r') as f:
            preset = json.load(f)

        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400

        for key in ["agent_name", "description", "goal", "target_impression", "provider", "model"]:
            if key in data:
                preset[key] = data[key]
        preset["updated_at"] = datetime.now().isoformat()

        with open(filepath, 'w') as f:
            json.dump(preset, f, indent=2)

        return jsonify({"success": True, "preset": preset})
    except Exception as e:
        flask_logger.error(f"Error updating agent preset: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/agent_library/<preset_id>', methods=['DELETE'])
def delete_agent_preset(preset_id):
    """Delete an agent preset."""
    try:
        filepath = os.path.join(agent_library_dir, f"{preset_id}.json")
        if not os.path.exists(filepath):
            return jsonify({"success": False, "error": "Preset not found"}), 404

        os.remove(filepath)
        return jsonify({"success": True, "message": f"Preset {preset_id} deleted"})
    except Exception as e:
        flask_logger.error(f"Error deleting agent preset: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


### ─── Graph Library ───────────────────────────────────────────────────

@app.route('/api/saved_graphs', methods=['GET'])
def list_saved_graphs():
    """List all saved graphs with their metadata."""
    try:
        graphs = []
        for filename in os.listdir(saved_graphs_dir):
            if filename.endswith('_meta.json'):
                filepath = os.path.join(saved_graphs_dir, filename)
                with open(filepath, 'r') as f:
                    meta = json.load(f)
                    graphs.append(meta)
        return jsonify({"success": True, "graphs": graphs})
    except Exception as e:
        flask_logger.error(f"Error listing saved graphs: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/saved_graphs/from_agent/<agent_id>', methods=['POST'])
def save_graph_from_agent(agent_id):
    """Save a running agent's graph to the graph library."""
    try:
        if 'state' not in session:
            return jsonify({"error": "No active session"}), 400

        agents_df = pd.DataFrame(session['state']['agents_df'])
        row = agents_df[agents_df['agent_id'] == agent_id]
        if row.empty:
            return jsonify({"success": False, "error": "Agent not found"}), 404

        agent = row.iloc[0]
        src_path = agent['graph_file_path']
        if not os.path.exists(src_path):
            return jsonify({"success": False, "error": "Agent graph file not found"}), 404

        graph_id = f"graph_{uuid.uuid4()}"
        data = request.get_json() or {}
        name = data.get("name", f"{agent['agent_name']}_graph")

        # Copy graphml
        import shutil
        dest_graphml = os.path.join(saved_graphs_dir, f"{graph_id}.graphml")
        shutil.copy2(src_path, dest_graphml)

        # Create metadata
        G = nx.read_graphml(dest_graphml)
        meta = {
            "graph_id": graph_id,
            "name": name,
            "source_agent_id": agent_id,
            "source_agent_name": agent['agent_name'],
            "nodes": G.number_of_nodes(),
            "edges": G.number_of_edges(),
            "created_at": datetime.now().isoformat()
        }
        meta_path = os.path.join(saved_graphs_dir, f"{graph_id}_meta.json")
        with open(meta_path, 'w') as f:
            json.dump(meta, f, indent=2)

        return jsonify({"success": True, "graph": meta}), 201
    except Exception as e:
        flask_logger.error(f"Error saving graph from agent: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/saved_graphs/merge', methods=['POST'])
def merge_saved_graphs():
    """Merge multiple saved graphs into a new one."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400

        graph_ids = data.get("graph_ids", [])
        name = data.get("name", "merged_graph")

        if len(graph_ids) < 2:
            return jsonify({"success": False, "error": "At least two graph_ids required"}), 400

        merged = nx.DiGraph()
        source_names = []
        for gid in graph_ids:
            gml_path = os.path.join(saved_graphs_dir, f"{gid}.graphml")
            if not os.path.exists(gml_path):
                return jsonify({"success": False, "error": f"Graph {gid} not found"}), 404
            G = nx.read_graphml(gml_path)
            merged = nx.compose(merged, G)

            meta_path = os.path.join(saved_graphs_dir, f"{gid}_meta.json")
            if os.path.exists(meta_path):
                with open(meta_path, 'r') as f:
                    source_names.append(json.load(f).get("name", gid))

        new_graph_id = f"graph_{uuid.uuid4()}"
        dest_graphml = os.path.join(saved_graphs_dir, f"{new_graph_id}.graphml")
        nx.write_graphml(merged, dest_graphml)

        meta = {
            "graph_id": new_graph_id,
            "name": name,
            "source_graph_ids": graph_ids,
            "source_names": source_names,
            "nodes": merged.number_of_nodes(),
            "edges": merged.number_of_edges(),
            "created_at": datetime.now().isoformat()
        }
        meta_path = os.path.join(saved_graphs_dir, f"{new_graph_id}_meta.json")
        with open(meta_path, 'w') as f:
            json.dump(meta, f, indent=2)

        return jsonify({"success": True, "graph": meta}), 201
    except Exception as e:
        flask_logger.error(f"Error merging graphs: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/saved_graphs/<graph_id>', methods=['DELETE'])
def delete_saved_graph(graph_id):
    """Delete a saved graph and its metadata."""
    try:
        gml_path = os.path.join(saved_graphs_dir, f"{graph_id}.graphml")
        meta_path = os.path.join(saved_graphs_dir, f"{graph_id}_meta.json")

        if not os.path.exists(meta_path) and not os.path.exists(gml_path):
            return jsonify({"success": False, "error": "Graph not found"}), 404

        if os.path.exists(gml_path):
            os.remove(gml_path)
        if os.path.exists(meta_path):
            os.remove(meta_path)

        return jsonify({"success": True, "message": f"Graph {graph_id} deleted"})
    except Exception as e:
        flask_logger.error(f"Error deleting saved graph: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.errorhandler(404)
def not_found_error(error):
    flask_logger.error(f'404 error: {request.url}')
    return jsonify({"error": "Not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    flask_logger.error(f'500 error: {error}')
    return jsonify({"error": "Internal server error"}), 500

if __name__ == '__main__':
    port = int(os.environ.get("FLASK_RUN_PORT", 5000))

    # Optionally download local model (non-blocking)
    if not os.path.exists(model_filename):
        flask_logger.info("Local model not found - skipping download. Use API providers or set OFFLINE_MODE=true.")

    # Ensure graph directory exists
    os.makedirs(graph_directory, exist_ok=True)
    test_graph = nx.DiGraph()
    test_graph.add_node('start')
    test_graph_path = os.path.join(graph_directory, 'test_graph.graphml')
    nx.write_graphml(test_graph, test_graph_path)

    flask_logger.info(f"Starting Flask app on port {port}")
    flask_logger.info(f"Offline mode: {offline}")
    from waitress import serve
    serve(app, host='0.0.0.0', port=port)