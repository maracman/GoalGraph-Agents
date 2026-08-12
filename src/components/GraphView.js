import React, { useState, useEffect, useRef } from 'react';
import { fetchAgentGraphs, visualizeGraph } from '../services/api';
import { useSession } from '../contexts/SessionContext';
import GraphLegend from './common/GraphLegend';

const GraphView = () => {
  const { sessionId, sessionState } = useSession();
  const agentData = sessionState.agentData;
  const [agents, setAgents] = useState([]);
  const [selectedAgentId, setSelectedAgentId] = useState('');
  const [graphUrl, setGraphUrl] = useState('');
  const [hideNoGo, setHideNoGo] = useState(false);
  const [loading, setLoading] = useState(false);
  const iframeRef = useRef(null);

  useEffect(() => {
    loadAgentGraphs();
  }, [sessionId, agentData]);

  const loadAgentGraphs = async () => {
    try {
      const graphData = await fetchAgentGraphs();
      setAgents(graphData);
      
      // Select the first agent by default if there's no selection and agents are available
      if (!selectedAgentId && graphData.length > 0) {
        setSelectedAgentId(graphData[0].id);
        loadGraph(graphData[0].id);
      }
    } catch (error) {
      console.error("Error loading agent graphs:", error);
    }
  };

  const handleAgentChange = (e) => {
    const agentId = e.target.value;
    setSelectedAgentId(agentId);
    loadGraph(agentId);
  };

  // Refuted aims are usually the majority of nodes, so hiding them is often
  // the only way to see the route the agent actually took.
  const toggleNoGo = (e) => {
    const next = e.target.checked;
    setHideNoGo(next);
    if (selectedAgentId) loadGraphWith(selectedAgentId, next);
  };

  const loadGraphWith = async (agentId, hide) => {
    if (!agentId) return;
    setLoading(true);
    try {
      const graphData = await visualizeGraph(agentId, hide);
      setGraphUrl(graphData.graph_html);
    } catch (error) {
      console.error("Error visualizing graph:", error);
    } finally {
      setLoading(false);
    }
  };

  const loadGraph = async (agentId) => {
    if (!agentId) return;
    
    setLoading(true);
    try {
      const graphData = await visualizeGraph(agentId, hideNoGo);
      setGraphUrl(graphData.graph_html);
    } catch (error) {
      console.error("Error visualizing graph:", error);
    } finally {
      setLoading(false);
    }
  };

  const handleIframeLoad = () => {
    setLoading(false);
  };

  return (
    <div className="graph-view-container">
      <div className="graph-header">
        <h2>Graph Visualization</h2>
        <div className="agent-selector-wrapper">
          <select
            id="agent-graph-selector"
            value={selectedAgentId}
            onChange={handleAgentChange}
            className="agent-selector"
          >
            <option value="" disabled>Select an agent</option>
            {agents.map((agent) => (
              <option key={agent.id} value={agent.id}>
                {agent.name}
              </option>
            ))}
          </select>
        </div>
        <label className="setting-checkbox" htmlFor="hide-nogo">
          <input
            id="hide-nogo"
            type="checkbox"
            checked={hideNoGo}
            onChange={toggleNoGo}
          />
          <span>Hide ruled-out aims</span>
        </label>
      </div>

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
              title="Agent Graph"
              className="graph-iframe"
              onLoad={handleIframeLoad}
              frameBorder="0"
            ></iframe>
          ) : (
            <div className="no-graph-message">
              <p>Select an agent to view their interaction graph</p>
            </div>
          )}
        </div>
      </div>

      <GraphLegend />
    </div>
  );
};

export default GraphView;
