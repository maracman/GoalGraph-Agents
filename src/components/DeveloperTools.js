import React, { useState, useEffect, useRef } from 'react';
import { fetchLogs, debugSession } from '../services/api';
import { RefreshCw, Download, Trash } from 'lucide-react';
import { useSession } from '../contexts/SessionContext';

const DeveloperTools = () => {
  const { sessionId } = useSession();
  const [logs, setLogs] = useState([]);
  const [sessionDebugInfo, setSessionDebugInfo] = useState({});
  const [lastLogTimestamp, setLastLogTimestamp] = useState(0);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [refreshInterval, setRefreshInterval] = useState(3000); // 3 seconds
  const logsEndRef = useRef(null);
  const intervalRef = useRef(null);

  useEffect(() => {
    // Initial fetch
    fetchLogData();
    fetchDebugData();
    
    // Set up auto refresh
    if (autoRefresh) {
      intervalRef.current = setInterval(fetchLogData, refreshInterval);
    }
    
    return () => {
      // Clean up the interval when component unmounts
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [autoRefresh, refreshInterval]);

  useEffect(() => {
    // Scroll to bottom when logs update
    scrollToBottom();
  }, [logs]);

  const fetchLogData = async () => {
    try {
      const logsData = await fetchLogs(lastLogTimestamp);
      if (logsData.logs && logsData.logs.length > 0) {
        // Add new logs and update timestamp
        setLogs(prevLogs => [...prevLogs, ...logsData.logs]);
        setLastLogTimestamp(logsData.timestamp);
      }
    } catch (error) {
      console.error("Error fetching logs:", error);
    }
  };

  const fetchDebugData = async () => {
    try {
      const debugData = await debugSession();
      setSessionDebugInfo(debugData);
    } catch (error) {
      console.error("Error fetching debug info:", error);
    }
  };

  const handleRefreshClick = () => {
    fetchLogData();
    fetchDebugData();
  };

  const toggleAutoRefresh = () => {
    if (!autoRefresh) {
      // Starting auto-refresh
      intervalRef.current = setInterval(fetchLogData, refreshInterval);
    } else {
      // Stopping auto-refresh
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    }
    setAutoRefresh(!autoRefresh);
  };

  const handleRefreshIntervalChange = (e) => {
    const newInterval = parseInt(e.target.value, 10);
    setRefreshInterval(newInterval);
    
    // Reset the interval with the new value if auto-refresh is on
    if (autoRefresh && intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = setInterval(fetchLogData, newInterval);
    }
  };

  const clearLogs = () => {
    setLogs([]);
  };

  const downloadLogs = () => {
    const logsText = logs.join('\n');
    const blob = new Blob([logsText], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `agent_logs_${new Date().toISOString()}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const scrollToBottom = () => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  return (
    <div className="developer-tools-container">
      <div className="developer-tools-header">
        <h2>Developer Tools</h2>
        <div className="developer-controls">
          <div className="refresh-controls">
            <button 
              className="refresh-button" 
              onClick={handleRefreshClick}
              title="Refresh logs"
            >
              <RefreshCw size={16} />
              <span>Refresh</span>
            </button>
            
            <label className="auto-refresh-control">
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={toggleAutoRefresh}
              />
              <span>Auto-refresh</span>
            </label>
            
            {autoRefresh && (
              <select 
                value={refreshInterval} 
                onChange={handleRefreshIntervalChange}
                className="refresh-interval"
              >
                <option value={1000}>1s</option>
                <option value={3000}>3s</option>
                <option value={5000}>5s</option>
                <option value={10000}>10s</option>
              </select>
            )}
          </div>
          
          <div className="log-actions">
            <button 
              className="download-button"
              onClick={downloadLogs}
              title="Download logs"
              disabled={logs.length === 0}
            >
              <Download size={16} />
              <span>Download</span>
            </button>
            
            <button 
              className="clear-button"
              onClick={clearLogs}
              title="Clear logs"
              disabled={logs.length === 0}
            >
              <Trash size={16} />
              <span>Clear</span>
            </button>
          </div>
        </div>
      </div>
      
      <div className="developer-tools-content">
        <div className="session-debug-info">
          <h3>Session Debug Information</h3>
          <div className="debug-info-content">
            <pre>{JSON.stringify(sessionDebugInfo, null, 2)}</pre>
          </div>
        </div>
        
        <div className="logs-container">
          <h3>Logs</h3>
          <div className="logs-content">
            {logs.length > 0 ? (
              logs.map((log, index) => (
                <div key={index} className="log-entry">
                  {log}
                </div>
              ))
            ) : (
              <div className="no-logs-message">
                No logs available
              </div>
            )}
            <div ref={logsEndRef} />
          </div>
        </div>
      </div>
    </div>
  );
};

export default DeveloperTools;