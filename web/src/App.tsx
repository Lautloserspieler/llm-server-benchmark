import { useTranslation } from 'react-i18next';
import { AnimatePresence } from 'framer-motion';
import { Activity, Globe, LayoutDashboard, Settings, Play } from 'lucide-react';
import { BrowserRouter, Routes, Route, NavLink, useLocation } from 'react-router-dom';

import { Dashboard } from './views/Dashboard';
import { Configuration } from './views/Configuration';
import { Runner } from './views/Runner';
import './App.css';

function AppLayout() {
  const { t, i18n } = useTranslation();
  const location = useLocation();

  const toggleLanguage = () => {
    const newLang = i18n.language === 'en' ? 'de' : 'en';
    i18n.changeLanguage(newLang);
  };

  return (
    <div className="app-container">
      {/* Background gradients */}
      <div className="bg-gradient-top"></div>
      <div className="bg-gradient-bottom"></div>

      <div className="layout-grid">
        <aside className="sidebar glass-panel">
          <div className="sidebar-header">
            <Activity className="logo-icon glow-icon" size={28} />
            <h1>LLM Bench</h1>
          </div>
          
          <nav className="sidebar-nav">
            <NavLink to="/" className={({isActive}) => `nav-item ${isActive ? 'active' : ''}`}>
              <LayoutDashboard size={18} /> {t('sidebar.dashboard')}
            </NavLink>
            <NavLink to="/config" className={({isActive}) => `nav-item ${isActive ? 'active' : ''}`}>
              <Settings size={18} /> {t('sidebar.configuration')}
            </NavLink>
            <NavLink to="/runner" className={({isActive}) => `nav-item ${isActive ? 'active' : ''}`}>
              <Play size={18} /> {t('sidebar.runner')}
            </NavLink>
          </nav>
          
          <div className="sidebar-footer">
            <button className="lang-toggle w-100" onClick={toggleLanguage}>
              <Globe size={18} />
              <span>Language: {i18n.language.toUpperCase()}</span>
            </button>
          </div>
        </aside>

        <main className="main-content">
          <AnimatePresence mode="wait">
            <Routes location={location} key={location.pathname}>
              <Route path="/" element={<Dashboard />} />
              <Route path="/config" element={<Configuration />} />
              <Route path="/runner" element={<Runner />} />
            </Routes>
          </AnimatePresence>
        </main>
      </div>
    </div>
  );
}

function App() {
  return (
    <BrowserRouter>
      <AppLayout />
    </BrowserRouter>
  );
}

export default App;
