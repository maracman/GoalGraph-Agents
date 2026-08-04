import React, { useState } from 'react';
import Sidebar from './Sidebar';
import ChatInterface from './ChatInterface';
import AgentLibrary from './AgentLibrary';
import GraphLibrary from './GraphLibrary';
import DeveloperTools from './DeveloperTools';
import LLMSettings from './LLMSettings';
import GraphSettings from './GraphSettings';
import NewChatDialog from './NewChatDialog';
import { useSession } from '../contexts/SessionContext';
import { useAgent } from '../contexts/AgentContext';

const App = () => {
  // Use context instead of local state
  const { sessionId, sessionState } = useSession();
  const { agents } = useAgent();

  // Local UI state only
  // Deep-link a panel with ?tab=graphsettings. Makes a view reproducible from
  // a URL, which is what screenshots and bug reports both need.
  const [activeTab, setActiveTab] = useState(() => {
    const requested = new URLSearchParams(window.location.search).get('tab');
    const known = ['chat', 'agent', 'graph', 'developer', 'llm', 'graphsettings'];
    return known.includes(requested) ? requested : 'chat';
  });
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [newChatDialogOpen, setNewChatDialogOpen] = useState(false);

  const toggleSidebar = () => {
    setSidebarCollapsed(!sidebarCollapsed);
  };

  const openNewChatDialog = () => {
    setNewChatDialogOpen(true);
  };

  const closeNewChatDialog = () => {
    setNewChatDialogOpen(false);
  };

  return (
    <div className="app-container">
      <Sidebar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        collapsed={sidebarCollapsed}
        toggleSidebar={toggleSidebar}
        onNewChat={openNewChatDialog}
      />

      <main className={`main-content ${sidebarCollapsed ? 'sidebar-collapsed' : ''}`}>
        {activeTab === 'chat' && (
          <ChatInterface />
        )}

        {activeTab === 'agent' && (
          <AgentLibrary />
        )}

        {activeTab === 'graph' && (
          <GraphLibrary />
        )}

        {activeTab === 'developer' && (
          <DeveloperTools />
        )}

        {activeTab === 'llm' && (
          <LLMSettings />
        )}

        {activeTab === 'graphsettings' && (
          <GraphSettings />
        )}
      </main>

      <NewChatDialog isOpen={newChatDialogOpen} onClose={closeNewChatDialog} />
    </div>
  );
};

export default App;
