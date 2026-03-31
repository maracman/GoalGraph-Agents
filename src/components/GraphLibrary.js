import React, { useState, useEffect, useRef } from 'react';
import { Save, Trash, GitMerge } from 'lucide-react';
import {
  fetchAgentGraphs,
  visualizeGraph,
  fetchSavedGraphs,
  saveGraphFromAgent,
  mergeGraphs,
  deleteSavedGraph
} from '../services/api';
import { useSession } from '../contexts/SessionContext';

const GraphLibrary = () => {
  const { sessionState } = useSession();
  const agentData = sessionState.agentData;

  const [activeAgentGraphs, setActiveAgentGraphs] = useState([]);
  const [savedGraphs, setSavedGraphs] = useState([]);
  const [graphUrl, setGraphUrl] = useState('');
  const [loading, setLoading] = useState(false);
  const [selectedForMerge, setSelectedForMerge] = useState([]);
  const [mergeName, setMergeName] = useState('');
  const [showMergeInput, setShowMergeInput] = useState(false);
  const [saveNameInput, setSaveNameInput] = useState('');
  const [savingAgentId, setSavingAgentId] = useState(null);
  const iframeRef = useRef(null);

  useEffect(() => {
    loadAllGraphs();
  }, [agentData]);

  const loadAllGraphs = async () => {
    try {
      const [agentGraphs, saved] = await Promise.all([
        fetchAgentGraphs(),
        fetchSavedGraphs()
      ]);
      setActiveAgentGraphs(Array.isArray(agentGraphs) ? agentGraphs : []);
      setSavedGraphs(Array.isArray(saved) ? saved : saved.graphs || []);
    } catch (error) {
      console.error('Error loading graphs:', error);
    }
  };

  const handleVisualize = async (agentId) => {
    setLoading(true);
    try {
      const graphData = await visualizeGraph(agentId);
      setGraphUrl(graphData.graph_html);
    } catch (error) {
      console.error('Error visualizing graph:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleVisualizeSaved = async (graphId) => {
    setLoading(true);
    try {
      // Use the saved graph visualization endpoint; fall back to agent visualize
      const response = await fetch(`/api/saved_graphs/${graphId}/visualize`);
      const data = await response.json();
      setGraphUrl(data.graph_html);
    } catch (error) {
      console.error('Error visualizing saved graph:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleSaveFromAgent = async (agentId) => {
    if (savingAgentId === agentId) {
      // Submit the save
      if (!saveNameInput.trim()) {
        alert('Please enter a name for the saved graph.');
        return;
      }
      try {
        await saveGraphFromAgent(agentId, saveNameInput.trim());
        setSavingAgentId(null);
        setSaveNameInput('');
        await loadAllGraphs();
      } catch (error) {
        console.error('Error saving graph from agent:', error);
      }
    } else {
      // Show the name input
      const agent = activeAgentGraphs.find(a => a.id === agentId);
      setSavingAgentId(agentId);
      setSaveNameInput(agent ? `${agent.name}'s Graph` : 'Saved Graph');
    }
  };

  const handleDeleteSaved = async (graphId) => {
    if (!window.confirm('Are you sure you want to delete this saved graph?')) return;
    try {
      await deleteSavedGraph(graphId);
      setSelectedForMerge(prev => prev.filter(id => id !== graphId));
      await loadAllGraphs();
    } catch (error) {
      console.error('Error deleting saved graph:', error);
    }
  };

  const toggleMergeSelection = (graphId) => {
    setSelectedForMerge(prev =>
      prev.includes(graphId)
        ? prev.filter(id => id !== graphId)
        : [...prev, graphId]
    );
  };

  const handleMerge = async () => {
    if (!showMergeInput) {
      setShowMergeInput(true);
      setMergeName('Merged Graph');
      return;
    }
    if (!mergeName.trim()) {
      alert('Please enter a name for the merged graph.');
      return;
    }
    try {
      await mergeGraphs(selectedForMerge, mergeName.trim());
      setSelectedForMerge([]);
      setShowMergeInput(false);
      setMergeName('');
      await loadAllGraphs();
    } catch (error) {
      console.error('Error merging graphs:', error);
    }
  };

  return (
    <div className="graph-view-container">
      {/* Section 1: Active Agent Graphs */}
      <div className="graph-header">
        <h2>Active Agent Graphs</h2>
      </div>

      <div className="agent-library-list">
        {activeAgentGraphs.length === 0 && (
          <p style={{ color: '#888', fontStyle: 'italic' }}>No active agent graphs.</p>
        )}
        {activeAgentGraphs.map((agent) => (
          <div key={agent.id} className="agent-preset-card">
            <div className="preset-card-header">
              <strong>{agent.name}</strong>
              <span style={{ color: '#888', fontSize: '0.85em', marginLeft: '8px' }}>
                {agent.node_count != null ? `${agent.node_count} nodes` : ''}
              </span>
            </div>
            <div className="buttons-row" style={{ justifyContent: 'flex-end' }}>
              <button className="save-button" onClick={() => handleVisualize(agent.id)}>
                View
              </button>
              <button className="add-button" onClick={() => handleSaveFromAgent(agent.id)}>
                <Save size={14} />
                <span>{savingAgentId === agent.id ? 'Confirm' : 'Save to Library'}</span>
              </button>
            </div>
            {savingAgentId === agent.id && (
              <div className="setting-group" style={{ marginTop: '8px' }}>
                <input
                  type="text"
                  value={saveNameInput}
                  onChange={(e) => setSaveNameInput(e.target.value)}
                  placeholder="Graph name"
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') handleSaveFromAgent(agent.id);
                    if (e.key === 'Escape') { setSavingAgentId(null); setSaveNameInput(''); }
                  }}
                  autoFocus
                />
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Graph visualization */}
      <div className="graph-display">
        {loading && (
          <div className="loading-indicator">
            <div className="spinner"></div>
            <p>Loading graph...</p>
          </div>
        )}

        <div className="graph-iframe-container" style={{ opacity: loading ? 0.5 : 1 }}>
          {graphUrl ? (
            <iframe
              ref={iframeRef}
              src={graphUrl}
              title="Graph Visualization"
              className="graph-iframe"
              onLoad={() => setLoading(false)}
              frameBorder="0"
            ></iframe>
          ) : (
            <div className="no-graph-message">
              <p>Click "View" on a graph to visualize it</p>
            </div>
          )}
        </div>

        {graphUrl && (
          <div className="graph-legend-inline">
            <div className="legend-item">
              <div className="legend-color" style={{ backgroundColor: 'blue' }}></div>
              <span>Active subgoal</span>
            </div>
            <div className="legend-item">
              <div className="legend-color" style={{ backgroundColor: 'gray' }}></div>
              <span>Previous subgoal</span>
            </div>
            <div className="legend-item">
              <div className="legend-line" style={{ borderTop: '2px solid green' }}></div>
              <span>Go (success)</span>
            </div>
            <div className="legend-item">
              <div className="legend-line" style={{ borderTop: '2px dashed red' }}></div>
              <span>NoGo (fail)</span>
            </div>
          </div>
        )}
      </div>

      {/* Section 2: Saved Graphs */}
      <div className="graph-header" style={{ marginTop: '24px' }}>
        <h2>Saved Graphs</h2>
      </div>

      <div className="agent-library-list">
        {savedGraphs.length === 0 && (
          <p style={{ color: '#888', fontStyle: 'italic' }}>No saved graphs yet.</p>
        )}
        {savedGraphs.map((graph) => {
          const gid = graph.graph_id || graph.id;
          const isChecked = selectedForMerge.includes(gid);
          return (
            <div key={gid} className="agent-preset-card">
              <div className="preset-card-header" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <input
                  type="checkbox"
                  checked={isChecked}
                  onChange={() => toggleMergeSelection(gid)}
                  title="Select for merge"
                />
                <strong>{graph.name}</strong>
                <span style={{ color: '#888', fontSize: '0.85em', marginLeft: '8px' }}>
                  {graph.nodes != null ? `${graph.nodes} nodes` : ''}
                  {graph.edges != null ? ` / ${graph.edges} edges` : ''}
                </span>
              </div>
              {graph.source_agent_name && (
                <div className="preset-card-body">
                  <p className="preset-goal-snippet">Source: {graph.source_agent_name}</p>
                </div>
              )}
              <div className="buttons-row" style={{ justifyContent: 'flex-end' }}>
                <button className="save-button" onClick={() => handleVisualizeSaved(gid)}>
                  View
                </button>
                <button className="delete-button" onClick={() => handleDeleteSaved(gid)}>
                  <Trash size={14} />
                  <span>Delete</span>
                </button>
              </div>
            </div>
          );
        })}
      </div>

      {/* Merge controls */}
      {selectedForMerge.length >= 2 && (
        <div className="merge-controls" style={{ marginTop: '16px' }}>
          {showMergeInput && (
            <div className="setting-group" style={{ marginBottom: '8px' }}>
              <input
                type="text"
                value={mergeName}
                onChange={(e) => setMergeName(e.target.value)}
                placeholder="Merged graph name"
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleMerge();
                  if (e.key === 'Escape') { setShowMergeInput(false); setMergeName(''); }
                }}
                autoFocus
              />
            </div>
          )}
          <button className="save-button" onClick={handleMerge}>
            <GitMerge size={16} />
            <span>{showMergeInput ? 'Confirm Merge' : `Merge Selected (${selectedForMerge.length})`}</span>
          </button>
        </div>
      )}

    </div>
  );
};

export default GraphLibrary;
