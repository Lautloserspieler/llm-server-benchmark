import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { motion, AnimatePresence } from 'framer-motion';
import { Activity, Cpu, Server, Clock, ChevronRight } from 'lucide-react';

interface Run {
  id: string;
  server_name: string;
  started_at: string;
  models_count: number;
  hardware: {
    cpu: string;
    gpus: string[];
  };
}

export function Dashboard() {
  const { t, i18n } = useTranslation();
  const [runs, setRuns] = useState<Run[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('/api/runs')
      .then(res => res.json())
      .then(data => {
        setRuns(data.runs || []);
        setLoading(false);
      })
      .catch(err => {
        console.error("Failed to fetch runs:", err);
        setLoading(false);
      });
  }, []);

  const containerVariants = {
    hidden: { opacity: 0 },
    show: {
      opacity: 1,
      transition: { staggerChildren: 0.1 }
    }
  };

  const itemVariants = {
    hidden: { opacity: 0, y: 20 },
    show: { opacity: 1, y: 0, transition: { type: "spring" as const, stiffness: 300, damping: 24 } }
  };

  return (
    <>
      <motion.div 
        className="hero-section"
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.7 }}
      >
        <h2>{t('hero.title')}</h2>
        <p>{t('hero.subtitle')}</p>
      </motion.div>

      <div className="runs-section">
        <div className="section-header">
          <h3>{t('runs.title')}</h3>
          <span className="badge">{t('runs.total', { count: runs.length })}</span>
        </div>

        <AnimatePresence mode="wait">
          {loading ? (
            <motion.div 
              key="loading"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="loading-state glass-panel"
            >
              <div className="spinner"></div>
              <span>{t('runs.loading')}</span>
            </motion.div>
          ) : runs.length === 0 ? (
            <motion.div 
              key="empty"
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              className="empty-state glass-panel"
            >
              <Activity size={48} className="text-muted mb-4" />
              <p>{t('runs.empty')}</p>
            </motion.div>
          ) : (
            <motion.div 
              key="grid"
              variants={containerVariants}
              initial="hidden"
              animate="show"
              className="runs-grid"
            >
              {runs.map(run => (
                <motion.div 
                  key={run.id} 
                  variants={itemVariants}
                  whileHover={{ y: -5, scale: 1.02 }}
                  className="run-card glass-panel"
                >
                  <div className="run-card-header">
                    <div className="run-server">
                      <Server size={18} className="text-primary" />
                      <span>{run.server_name || t('runs.unknown_server')}</span>
                    </div>
                    <div className="run-date">
                      <Clock size={14} />
                      <span>{new Date(run.started_at).toLocaleString(i18n.language)}</span>
                    </div>
                  </div>
                  
                  <div className="run-card-body">
                    <div className="info-row">
                      <Cpu size={16} className="text-muted" />
                      <span className="truncate" title={run.hardware?.cpu}>
                        {run.hardware?.cpu || t('runs.unknown_cpu')}
                      </span>
                    </div>
                    {run.hardware?.gpus && run.hardware.gpus.length > 0 && (
                      <div className="info-row">
                        <Activity size={16} className="text-muted" />
                        <span className="truncate" title={run.hardware.gpus.join(", ")}>
                          {run.hardware.gpus.length}x GPU ({run.hardware.gpus[0]})
                        </span>
                      </div>
                    )}
                    <div className="model-count">
                      {run.models_count === 1 
                        ? t('runs.models_tested_one', { count: 1 })
                        : t('runs.models_tested_other', { count: run.models_count })}
                    </div>
                  </div>

                  <div className="run-card-footer">
                    <button className="btn-secondary">
                      {t('runs.view_details')} <ChevronRight size={16} />
                    </button>
                  </div>
                </motion.div>
              ))}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </>
  );
}
