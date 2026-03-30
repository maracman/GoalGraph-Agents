# Thinking Agents

Thinking Agents is an interactive multi-agent chat platform where you can create, configure, and interact with multiple AI agents. The platform provides a unique environment for agent-to-agent and user-to-agent conversations, with a powerful visualization system to track agent decision-making processes.

## Screenshots

### Chat Interface
![Chat Interface](screenshots/chat_interface.png)

### Graph Visualization
![Graph Visualization](screenshots/graph_visualization.png)

### Agent Settings
![Agent Settings](screenshots/agent_settings.png)

## Features

- **Multi-Agent Conversations**: Create and manage multiple AI agents with unique personalities, goals, and behaviors.
- **Agent Settings**: Configure agent parameters including name, description, goals, and generation variables.
- **Interactive Chat Interface**: Engage in conversations with agents or let agents interact with each other.
- **Decision Graph Visualization**: View and analyze agent decision-making processes through interactive graph visualizations.
- **Developer Tools**: Debug sessions, view logs, and track agent behavior in real-time.
- **Session Management**: Save, load, duplicate, and manage chat sessions.
- **Customizable Parameters**: Fine-tune parameters like temperature, max tokens, and more for each agent or globally.

## Architecture

The application is built with a modern stack:

- **Frontend**: React.js with a component-based architecture
- **Backend**: Python Flask API
- **LLM Integration**: Support for multiple language model providers (OpenAI, Anthropic, Cohere, HuggingFace, and local models)
- **Graph Visualization**: Network graph visualization using PyVis
- **Session Storage**: File-based session storage using JSON

## Project Structure

```
thinking-agents/
├── components/
│   ├── App.jsx                 # Main App component
│   ├── Sidebar.jsx             # Sidebar navigation
│   ├── ChatInterface.jsx       # Chat UI
│   ├── AgentSettings.jsx       # Agent configuration
│   ├── GraphView.jsx           # Graph visualization
│   ├── DeveloperTools.jsx      # Developer logs and tools
│   └── common/                 # Reusable components
│       ├── Button.jsx
│       ├── Dropdown.jsx
│       ├── Slider.jsx
│       └── Modal.jsx
├── contexts/
│   ├── SessionContext.jsx      # Global session state
│   └── AgentContext.jsx        # Agent-specific state
├── services/
│   ├── api.js                  # API communication
│   ├── graphService.js         # Graph visualization helpers
│   └── sessionService.js       # Session handling
├── styles/
│   ├── main.css                # Global styles
│   └── components/             # Component-specific styles
├── utils/
│   └── helpers.js              # Helper functions
├── agent/
│   ├── agent.py                # Agent logic implementation
│   ├── llm_service.py          # LLM provider integrations
│   └── schemas.py              # JSON schemas for LLM inputs
└── app.py                      # Flask application server
```

## Getting Started

### Prerequisites

- Node.js 14+ and npm/yarn
- Python 3.8+
- pip (Python package manager)

### Installation

1. Clone the repository:
   ```
   git clone https://github.com/maracman/thinking-agents.git
   cd thinking-agents
   ```

2. Install backend dependencies:
   ```
   pip install -r requirements.txt
   ```

3. Install frontend dependencies:
   ```
   cd src
   npm install
   ```

4. Set up environment variables:
   ```
   # Create a .env file in the root directory
   FLASK_SECRET_KEY=your_secret_key
   
   # Optional API keys for various LLM providers
   OPENAI_API_KEY=your_openai_key
   ANTHROPIC_API_KEY=your_anthropic_key
   COHERE_API_KEY=your_cohere_key
   HUGGINGFACE_API_KEY=your_huggingface_key
   
   # Local model path (optional, for offline mode)
   LOCAL_MODEL_PATH=/path/to/models
   LOCAL_MODEL_FILENAME=your_model_file.gguf
   ```

### Running the Application

1. Start the backend server:
   ```
   python src/app.py
   ```

2. Build the frontend assets:
   ```
   cd src
   npm run build
   ```

3. Access the application:
   Open your browser and navigate to `http://localhost:5000`

## Using the Application

### Creating Agents

1. Navigate to the "Agent" tab in the sidebar
2. Click "Add New Agent"
3. Configure your agent with a name, description, and goal
4. Adjust generation parameters as needed
5. Click "Save Settings"

### Starting Conversations

1. Switch to the "Chat" tab
2. Type a message and click "Send" to start a conversation
3. Use the "Play" button to let agents continue the conversation automatically
4. Use the "Pause" button to interrupt generation

### Viewing the Decision Graph

1. Go to the "Graph" tab to see agent decision-making processes
2. Select different agents from the dropdown to view their specific graphs
3. Explore the network visualization to understand agent reasoning paths

### Developer Tools

1. Navigate to the "Developer" tab
2. View session debug information and real-time logs
3. Use the refresh controls to monitor agent activities
4. Download logs for offline analysis

## Running in Offline Mode

The application can run in offline mode using local models:

1. Set `offline = True` in `app.py`
2. Ensure you have a compatible GGUF model file in your `LOCAL_MODEL_PATH`
3. The application will automatically use the local model for generations

## License

MIT License
Copyright (c) 2025 Marcus Anderson
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

