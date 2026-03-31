import React, { useState, useEffect } from 'react';
import { ChevronLeft, ChevronRight, Settings, MessageSquare, Activity, Code, Cloud, PlusCircle } from 'lucide-react';
import { useSession } from '../contexts/SessionContext';

const Sidebar = ({ activeTab, setActiveTab, collapsed, toggleSidebar, onNewChat }) => {
  const { sessionState, pastChats, loadPastChats } = useSession();
  const [sessionParamsOpen, setSessionParamsOpen] = useState(false);
  const [pastChatsOpen, setPastChatsOpen] = useState(false);
  
  useEffect(() => {
    if (pastChatsOpen) {
      loadPastChats();
    }
  }, [pastChatsOpen, loadPastChats]);
  
  const handleTabClick = (tab) => {
    setActiveTab(tab);
  };
  
  const toggleSessionParams = () => {
    setSessionParamsOpen(!sessionParamsOpen);
  };
  
  const togglePastChats = () => {
    setPastChatsOpen(!pastChatsOpen);
  };
  
  return (
    <div className={`sidebar ${collapsed ? 'collapsed' : ''}`}>
      <div className="burger-menu" onClick={toggleSidebar}>
        {collapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}
      </div>
      
      {!collapsed && (
        <div className="sidebar-content">
          <div className="tabs">
            <button
              className={activeTab === 'chat' ? 'active' : ''}
              onClick={() => handleTabClick('chat')}
            >
              <MessageSquare size={18} />
              <span className="tab-text">Chat</span>
            </button>
            
            <button
              className={activeTab === 'agent' ? 'active' : ''}
              onClick={() => handleTabClick('agent')}
            >
              <Settings size={18} />
              <span className="tab-text">Agent</span>
            </button>
            
            <button
              className={activeTab === 'graph' ? 'active' : ''}
              onClick={() => handleTabClick('graph')}
            >
              <Activity size={18} />
              <span className="tab-text">Graph</span>
            </button>
            
            <button
              className={activeTab === 'developer' ? 'active' : ''}
              onClick={() => handleTabClick('developer')}
            >
              <Code size={18} />
              <span className="tab-text">Developer</span>
            </button>
            
            {/* New LLM tab */}
            <button
              className={activeTab === 'llm' ? 'active' : ''}
              onClick={() => handleTabClick('llm')}
            >
              <Cloud size={18} />
              <span className="tab-text">LLM Settings</span>
            </button>
            
            {onNewChat && (
              <button
                className=""
                onClick={onNewChat}
                style={{ marginTop: '8px' }}
              >
                <PlusCircle size={18} />
                <span className="tab-text">New Chat</span>
              </button>
            )}

            <button
              className="sidebar-tab"
              onClick={toggleSessionParams}
            >
              Session Parameters
              <span className="collapse-icon">{sessionParamsOpen ? '−' : '+'}</span>
            </button>
            
            {sessionParamsOpen && (
              <div className="session-params">
                <div className="input-group compact">
                  <label htmlFor="temperature">Temperature:</label>
                  <div className="range-slider">
                    <input
                      type="range"
                      id="temperature"
                      className="range-slider__range"
                      min="0"
                      max="1"
                      step="0.1"
                      defaultValue={sessionState.settings.temperature || 0.7}
                    />
                    <div className="range-slider__value">{sessionState.settings.temperature || 0.7}</div>
                  </div>
                </div>
                
                <div className="input-group compact">
                  <label htmlFor="max_tokens">Max Tokens:</label>
                  <div className="range-slider">
                    <input
                      type="range"
                      id="max_tokens"
                      className="range-slider__range"
                      min="0"
                      max="500"
                      step="1"
                      defaultValue={sessionState.settings.max_tokens || 150}
                    />
                    <div className="range-slider__value">{sessionState.settings.max_tokens || 150}</div>
                  </div>
                </div>
                
                <div className="input-group compact">
                  <label htmlFor="top_p">Top P:</label>
                  <div className="range-slider">
                    <input
                      type="range"
                      id="top_p"
                      className="range-slider__range"
                      min="0"
                      max="1"
                      step="0.1"
                      defaultValue={sessionState.settings.top_p || 0.9}
                    />
                    <div className="range-slider__value">{sessionState.settings.top_p || 0.9}</div>
                  </div>
                </div>
              </div>
            )}
            
            <button 
              className="sidebar-tab"
              onClick={togglePastChats}
            >
              Past Chats
              <span className="collapse-icon">{pastChatsOpen ? '−' : '+'}</span>
            </button>
            
            {pastChatsOpen && (
              <div className="past-chats-content">
                {pastChats.map((chat) => (
                  <div 
                    key={chat.id}
                    className={`past-chat-item ${chat.is_current ? 'current-chat' : ''}`}
                    data-chat-id={chat.id}
                  >
                    <span className="chat-names">
                      {chat.user_name} with {chat.agent_names.join(', ')}
                    </span>
                    <span className="chat-date">{chat.last_interaction_formatted}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default Sidebar;