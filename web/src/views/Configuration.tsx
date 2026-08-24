import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { motion } from 'framer-motion';
import { Save } from 'lucide-react';

export function Configuration() {
  const { t } = useTranslation();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [config, setConfig] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState(false);

  useEffect(() => {
    fetch('/api/config')
      .then(res => res.json())
      .then(data => {
        if (data.config) setConfig(data.config);
        setLoading(false);
      })
      .catch(err => {
        console.error(err);
        setLoading(false);
      });
  }, []);

  const handleSave = () => {
    setSaving(true);
    fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config: config })
    })
      .then(res => res.json())
      .then(() => {
        setSaving(false);
        setSuccess(true);
        setTimeout(() => setSuccess(false), 3000);
      })
      .catch(() => setSaving(false));
  };

  const updateConfig = (section: string, field: string, value: string | number | boolean) => {
    setConfig((prev: any) => ({
      ...prev,
      [section]: {
        ...prev[section],
        [field]: value
      }
    }));
  };

  if (loading || !config) {
    return (
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
        <div className="hero-section mb-4">
          <h2>{t('config.title')}</h2>
          <p>{t('config.subtitle')}</p>
        </div>
        <div className="glass-panel" style={{ padding: '2rem', textAlign: 'center' }}>
          {t('config.loading')}
        </div>
      </motion.div>
    );
  }

  return (
    <motion.div 
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      className="config-container"
    >
      <div className="hero-section" style={{ marginBottom: '2rem' }}>
        <h2>{t('config.title')}</h2>
        <p>{t('config.subtitle')}</p>
      </div>

      <div className="config-grid">
        {/* Project Settings */}
        <div className="glass-panel config-card">
          <h3>{t('config.project_settings')}</h3>
          
          <div className="form-group">
            <label>{t('config.fields.project_name')}</label>
            <input 
              type="text" 
              className="form-input"
              value={config.project?.name || ''} 
              onChange={e => updateConfig('project', 'name', e.target.value)} 
            />
          </div>

          <div className="form-group">
            <label>{t('config.fields.server_name')}</label>
            <input 
              type="text" 
              className="form-input"
              value={config.project?.server_name || ''} 
              onChange={e => updateConfig('project', 'server_name', e.target.value)} 
            />
          </div>
        </div>

        {/* Benchmark Settings */}
        <div className="glass-panel config-card">
          <h3>{t('config.benchmark_settings')}</h3>
          
          <div className="form-group">
            <label>{t('config.fields.repetitions')}</label>
            <input 
              type="number" 
              className="form-input"
              value={config.benchmark?.repetitions || 1} 
              onChange={e => updateConfig('benchmark', 'repetitions', parseInt(e.target.value) || 1)} 
            />
          </div>

          <div className="form-group">
            <label>{t('config.fields.batch_size')}</label>
            <select 
              className="form-input"
              value={config.benchmark?.batch_size || 512}
              onChange={e => updateConfig('benchmark', 'batch_size', parseInt(e.target.value))}
            >
              <option value={512}>512</option>
              <option value={1024}>1024</option>
              <option value={2048}>2048</option>
              <option value={4096}>4096</option>
            </select>
          </div>

          <div className="form-group-checkbox">
            <input 
              type="checkbox" 
              id="flash_attn"
              checked={['auto', 'on', 'true', true].includes(config.benchmark?.flash_attention)} 
              onChange={e => updateConfig('benchmark', 'flash_attention', e.target.checked ? 'auto' : 'off')} 
            />
            <label htmlFor="flash_attn">{t('config.fields.flash_attention')}</label>
          </div>
        </div>

        {/* Endpoint Settings */}
        <div className="glass-panel config-card">
          <h3>{t('config.endpoint_settings')}</h3>
          
          <div className="form-group-checkbox" style={{ marginBottom: '1rem' }}>
            <input 
              type="checkbox" 
              id="endpoint_enabled"
              checked={config.endpoint?.enabled || false} 
              onChange={e => updateConfig('endpoint', 'enabled', e.target.checked)} 
            />
            <label htmlFor="endpoint_enabled">{t('config.fields.endpoint_enabled')}</label>
          </div>

          <div className="form-group">
            <label>{t('config.fields.parallel_slots')}</label>
            <input 
              type="number" 
              className="form-input"
              disabled={!config.endpoint?.enabled}
              value={config.endpoint?.parallel_slots || 1} 
              onChange={e => updateConfig('endpoint', 'parallel_slots', parseInt(e.target.value) || 1)} 
            />
          </div>

          <div className="form-group">
            <label>{t('config.fields.temperature')}</label>
            <input 
              type="number" 
              step="0.1"
              className="form-input"
              disabled={!config.endpoint?.enabled}
              value={config.endpoint?.temperature ?? 0.0} 
              onChange={e => updateConfig('endpoint', 'temperature', parseFloat(e.target.value) || 0.0)} 
            />
          </div>
        </div>
      </div>

      <div className="config-footer glass-panel">
        {success && <span className="text-accent">{t('config.success')}</span>}
        <button className="btn-primary" onClick={handleSave} disabled={saving} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <Save size={18} />
          {saving ? '...' : t('config.save')}
        </button>
      </div>
    </motion.div>
  );
}
