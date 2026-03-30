# Thinking Agents

An interactive multi-agent AI platform where agents pursue goals through conversation, with an LLM judge evaluating progress and a graph intelligence system that learns optimal paths over time.

Agents don't just chat — they work toward goals. A lightweight LLM judge rates each agent's progress on a 1–7 scale, triggering **Go** (goal achieved) or **NoGo** (abandon and retry) decisions that build a persistent decision graph. Over time, agents use sentence embeddings to find known paths through the graph toward their goals, avoiding previously failed approaches.

## Screenshots

### Chat Interface
![Chat Interface](screenshots/chat_interface.png)

### Graph Visualization
![Graph Visualization](screenshots/graph_visualization.png)

### Agent Settings
![Agent Settings](screenshots/agent_settings.png)

## How It Works

### Goal-Directed Agent Loop

Each generation cycle follows this flow:

1. **Subgoal Assignment** — If the agent has no active subgoal, the system first checks the decision graph for a known path (via embedding similarity search). If no path exists, the LLM generates a new subgoal, informed by previously failed approaches.

2. **Response Generation** — The agent generates an in-character response with its subgoal and suggested action as context. Responses include optional narration (deduplicated to avoid repetition).

3. **LLM Judge Review** — A lightweight LLM call rates goal progress on a 1–7 Likert scale:
   - Rating >= 6 → **Go**: Subgoal achieved. The graph advances, and `persistence_count` (number of attempts) becomes the edge weight.
   - Rating <= 2 → **NoGo**: Strong failure. The subgoal is abandoned after minimum persistence.
   - Score regression > 1 and <= 4 → **NoGo**: Progress is going backwards.
   - Exceeded patience limit → **NoGo**: Agent has been stuck too long.

4. **Graph Update** — Go/NoGo decisions create edges in a directed graph. Edge weight = number of turns spent on the subgoal, which maps to visual distance in the graph (`weight * 100`).

### Graph Intelligence

The decision graph isn't just a record — it's reusable knowledge:

- **Semantic Search**: Node labels are embedded with `all-MiniLM-L6-v2` (sentence-transformers). When an agent needs a new subgoal, the system finds the graph node most similar to the agent's goal via cosine similarity.
- **Pathfinding**: `nx.shortest_path` routes from the current node to the nearest goal node, weighting by `persistence_count` and penalizing NoGo edges 10x.
- **Graph Import**: One agent's graph can be imported into another, optionally with namespace prefixes to avoid node collisions.
- **Graph Merge**: Multiple agents' graphs can be combined into a shared knowledge graph.
- **Similarity Linking**: After merge, semantically similar nodes (cosine > 0.8) are connected with low-cost edges, enabling pathfinding across subgraphs even when node names don't match exactly.

### Persistence & Patience

Each agent has configurable persistence parameters:
- `persistance` (default: 3) — Minimum turns before a NoGo can trigger, even on bad scores.
- `patience` (default: 6) — Maximum turns before a forced NoGo, regardless of score.
- `persistance_count` — Tracks attempts on the current subgoal. Resets on Go or NoGo. Becomes the edge weight in the graph.

## Features

- **Multi-Agent Conversations** — Create and manage multiple AI agents with unique personalities, goals, and behaviors.
- **Goal-Directed Behavior** — Agents work toward goals with LLM-judged progress tracking and automatic subgoal generation.
- **Decision Graph** — Persistent directed graph of Go/NoGo decisions, visualized interactively with PyVis.
- **Graph Intelligence** — Embedding-based semantic search and shortest-path routing through the decision graph.
- **Graph Import/Merge** — Import, combine, and link graphs across agents for shared knowledge.
- **Multi-Provider LLM Support** — OpenAI, Anthropic, Cohere, HuggingFace, and local GGUF models with automatic fallback.
- **Session Management** — Save, load, duplicate, and delete chat sessions.
- **Developer Tools** — Debug sessions, view logs, and track agent behavior in real-time.
- **Offline Mode** — Run with simulated responses for development/testing (`OFFLINE_MODE=true`).

## Architecture

- **Frontend**: React 17 + Webpack 5, Context API for state management
- **Backend**: Flask + Waitress WSGI server
- **LLM Integration**: Abstraction layer supporting multiple providers with retry and fallback
- **Graph Engine**: NetworkX directed graphs + sentence-transformers embeddings
- **Graph Visualization**: PyVis (interactive HTML) served via iframe
- **Session Storage**: File-based JSON in `chat_cache/`

## Project Structure

```
thinking-agents/
├── src/
│   ├── app.py                      # Flask application server
│   ├── defaults_session.json        # Default session/agent configuration
│   ├── index.js                     # React entry point
│   ├── webpack.config.js            # Webpack build configuration
│   ├── package.json                 # Frontend dependencies
│   ├── agent/
│   │   ├── agent.py                 # Agent logic: subgoals, LLM judge, Go/NoGo
│   │   ├── graph_intelligence.py    # Embedding search, pathfinding, import/merge
│   │   ├── llm_service.py           # Multi-provider LLM abstraction
│   │   └── schemas.py               # JSON schemas (agent, session, judge, subgoal)
│   ├── components/
│   │   ├── App.js                   # Main App component
│   │   ├── Sidebar.jsx              # Sidebar navigation
│   │   ├── ChatInterface.js         # Chat UI with play/pause
│   │   ├── AgentSettings.js         # Agent configuration
│   │   ├── GraphView.js             # Graph visualization (PyVis iframe)
│   │   ├── DeveloperTools.js        # Developer logs and debug tools
│   │   ├── LLMSettings.jsx          # LLM provider/model configuration
│   │   └── common/                  # Reusable UI components
│   │       ├── Button.jsx
│   │       ├── Dropdown.jsx
│   │       ├── Modal.jsx
│   │       └── Slider.jsx
│   ├── contexts/
│   │   ├── SessionContext.jsx        # Global session state management
│   │   └── AgentContext.jsx          # Agent-specific state
│   ├── services/
│   │   ├── api.js                   # Backend API communication
│   │   ├── graphService.js          # Graph visualization helpers
│   │   ├── llmApiService.js         # Frontend LLM API helpers
│   │   ├── llmService.js            # Frontend LLM service
│   │   └── sessionService.js        # Session handling
│   ├── styles/
│   │   └── main.css                 # Component styles
│   ├── utils/
│   │   └── helpers.js               # Utility functions
│   └── static/                      # Built assets (bundle.js, main.css)
├── screenshots/                     # README screenshots
├── requirements.txt                 # Python dependencies
└── .gitignore
```

## Getting Started

### Prerequisites

- Python 3.8+
- Node.js 14+ and npm
- An API key for at least one LLM provider (OpenAI, Anthropic, Cohere, or HuggingFace)

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/maracman/thinking-agents.git
   cd thinking-agents
   ```

2. Set up a Python virtual environment and install dependencies:
   ```bash
   python -m venv venv
   source venv/bin/activate   # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. Install frontend dependencies and build:
   ```bash
   cd src
   npm install
   npm run build
   cd ..
   ```

4. Set up environment variables:
   ```bash
   # At least one API key is required for live mode
   export OPENAI_API_KEY=your_openai_key
   export ANTHROPIC_API_KEY=your_anthropic_key
   # Optional
   export COHERE_API_KEY=your_cohere_key
   export HUGGINGFACE_API_KEY=your_huggingface_key
   ```

### Running the Application

```bash
cd src
python app.py
```

Open your browser to `http://localhost:5000`.

To run in offline mode (simulated responses, no API key needed):

```bash
cd src
OFFLINE_MODE=true python app.py
```

## API Reference

### Core Routes

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/get_session_id` | Get or create a session ID |
| GET | `/check_session` | Get current session state |
| POST | `/submit` | Submit a user message |
| GET | `/generate` | Generate the next agent response |
| POST | `/interrupt` | Stop the current generation |

### Agent Management

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/get_agents` | List all agents |
| POST | `/add_agent` | Add or update an agent |
| POST | `/delete_agent` | Delete an agent |
| POST | `/toggle_agent_mute` | Mute/unmute an agent |

### Graph Operations

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/get_agent_graphs` | List agents with graph info |
| GET | `/visualize_graph` | Get PyVis HTML visualization |
| GET | `/graph_info/<agent_id>` | Get graph stats, nodes, and path-to-goal |
| POST | `/import_graph` | Import one agent's graph into another |
| POST | `/combine_graphs` | Merge multiple agents' graphs |

### Session Management

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/get_past_chats` | List saved chat sessions |
| POST | `/create_new_chat` | Create a new chat session |
| POST | `/duplicate` | Duplicate the current session |
| POST | `/delete_chat` | Delete the current session |
| POST | `/reset` | Reset the current chat |

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
