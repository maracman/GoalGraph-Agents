import React, { useState } from 'react';
import Sidebar from './Sidebar';
import ChatInterface from './ChatInterface';
import AgentLibrary from './AgentLibrary';
import GraphLibrary from './GraphLibrary';
import DeveloperTools from './DeveloperTools';
import LLMSettings from './LLMSettings';
import NewChatDialog from './NewChatDialog';
import { useSession } from '../contexts/SessionContext';
import { useAgent } from '../contexts/AgentContext';

const App = () => {
  // Use context instead of local state
  const { sessionId, sessionState } = useSession();
  const { agents } = useAgent();

  // Local UI state only
  const [activeTab, setActiveTab] = useState('chat');
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
      </main>

      <NewChatDialog isOpen={newChatDialogOpen} onClose={closeNewChatDialog} />
    </div>
  );
};

export default App;
