import { useState, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { motion } from 'framer-motion';
import { Play, Activity, Terminal } from 'lucide-react';

export function Runner() {
  const { t } = useTranslation();
  const [logs, setLogs] = useState<string[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const terminalEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (terminalEndRef.current) {
      terminalEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [logs]);

  const runAction = (action: string) => {
    setIsRunning(true);
    setLogs([`> Starting ${action}...`]);
    
    const eventSource = new EventSource(`/api/actions/${action}`);
    
    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.text !== undefined) {
          setLogs(prev => [...prev, data.text]);
        }
        if (data.exit_code !== undefined) {
          setLogs(prev => [...prev, `> Process exited with code ${data.exit_code}`]);
          setIsRunning(false);
          eventSource.close();
        }
      } catch (e) {
        setLogs(prev => [...prev, event.data]);
      }
    };
    
    eventSource.onerror = () => {
      setLogs(prev => [...prev, '> Error connecting to stream']);
      setIsRunning(false);
      eventSource.close();
    };
  };

  return (
    <motion.div 
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 100px)' }}
    >
      <div className="hero-section" style={{ marginBottom: '2rem' }}>
        <h2>{t('runner.title')}</h2>
        <p>{t('runner.subtitle')}</p>
      </div>

      <div style={{ display: 'flex', gap: '1rem', marginBottom: '2rem' }}>
        <button 
          className="btn-secondary" 
          onClick={() => runAction('bootstrap')} 
          disabled={isRunning}
          style={{ width: 'auto', padding: '0.75rem 1.5rem' }}
        >
          <Activity size={18} /> {t('runner.bootstrap')}
        </button>
        <button 
          className="btn-secondary" 
          onClick={() => runAction('doctor')} 
          disabled={isRunning}
          style={{ width: 'auto', padding: '0.75rem 1.5rem' }}
        >
          <Activity size={18} /> {t('runner.doctor')}
        </button>
        <button 
          className="btn-primary" 
          onClick={() => runAction('run')} 
          disabled={isRunning}
          style={{ width: 'auto', padding: '0.75rem 1.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}
        >
          <Play size={18} /> {t('runner.run')}
        </button>
      </div>

      <div className="glass-panel" style={{ flexGrow: 1, display: 'flex', flexDirection: 'column', borderRadius: '1rem', overflow: 'hidden' }}>
        <div style={{ padding: '0.75rem 1.5rem', background: 'rgba(0,0,0,0.4)', borderBottom: '1px solid var(--panel-border)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <Terminal size={16} className="text-muted" />
          <span style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-muted)' }}>{t('runner.logs')}</span>
        </div>
        <div className="terminal-logs">
          {logs.map((log, i) => (
            <div key={i} className="log-line">{log}</div>
          ))}
          <div ref={terminalEndRef} />
        </div>
      </div>
    </motion.div>
  );
}
