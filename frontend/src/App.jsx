import React, { useEffect, useMemo, useState } from 'react';
import { api } from './lib/api.js';
import Header from './components/Header.jsx';
import MapView from './components/MapView.jsx';
import AnomalyPanel from './components/AnomalyPanel.jsx';
import RefreshOverlay from './components/RefreshOverlay.jsx';

const THEME_KEY = 'pipeline-demo-theme';

export default function App() {
  const [theme, setTheme] = useState(() => {
    try {
      return localStorage.getItem(THEME_KEY) || 'dark';
    } catch {
      return 'dark';
    }
  });

  const [baseline, setBaseline] = useState(null);
  const [anomalies, setAnomalies] = useState(null);
  const [stats, setStats] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [severityFilter, setSeverityFilter] = useState(['high', 'medium', 'low']);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState(null);

  // Apply theme
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    try { localStorage.setItem(THEME_KEY, theme); } catch (_) {}
  }, [theme]);

  // Initial load
  useEffect(() => {
    (async () => {
      try {
        const [bl, fs, md] = await Promise.all([
          api.getBaseline(),
          api.getFullScan(),
          api.getScanMetadata(),
        ]);
        setBaseline(bl);
        setAnomalies(fs);
        setStats(md.headline_stats);
      } catch (e) {
        console.error(e);
        setError('Failed to reach API. Ensure the backend is running.');
      }
    })();
  }, []);

  const counts = useMemo(() => {
    if (!anomalies) return { high: 0, medium: 0, low: 0 };
    const c = { high: 0, medium: 0, low: 0 };
    anomalies.features.forEach((f) => { c[f.properties.severity]++; });
    return c;
  }, [anomalies]);

  const handleToggleTheme = () => {
    setTheme((t) => (t === 'dark' ? 'light' : 'dark'));
  };

  const handleToggleSeverity = (sev) => {
    setSeverityFilter((prev) => {
      if (prev.includes(sev)) {
        // Don't let the user empty the filter entirely
        if (prev.length === 1) return prev;
        return prev.filter((s) => s !== sev);
      }
      return [...prev, sev];
    });
  };

  const handleRefresh = async () => {
    if (isRefreshing) return;
    setIsRefreshing(true);
    try {
      const result = await api.triggerRefresh();
      setAnomalies(result.results);
      setStats(result.headline_stats);
    } catch (e) {
      console.error(e);
      setError('Refresh failed.');
    } finally {
      setIsRefreshing(false);
    }
  };

  return (
    <div className="app-shell">
      <div className="app-header">
        <Header
          stats={stats}
          isRefreshing={isRefreshing}
          onRefresh={handleRefresh}
          theme={theme}
          onToggleTheme={handleToggleTheme}
        />
      </div>
      <div className="app-map" style={{ position: 'relative' }}>
        <MapView
          baseline={baseline}
          anomalies={anomalies}
          selectedAnomalyId={selectedId}
          onSelectAnomaly={setSelectedId}
          severityFilter={severityFilter}
          theme={theme}
        />
        {isRefreshing && <RefreshOverlay durationMs={4000} />}
        {error && (
          <div style={{
            position: 'absolute', top: 20, left: '50%', transform: 'translateX(-50%)',
            background: 'var(--bg-panel)', border: '1px solid var(--sev-high)',
            padding: '10px 18px', fontFamily: 'var(--font-mono)', fontSize: 11,
            color: 'var(--sev-high)', letterSpacing: '0.08em', textTransform: 'uppercase',
            borderRadius: 2, zIndex: 4,
          }}>
            {error}
          </div>
        )}
      </div>
      <div className="app-panel">
        <AnomalyPanel
          anomalies={anomalies}
          selectedId={selectedId}
          onSelect={setSelectedId}
          severityFilter={severityFilter}
          onToggleSeverity={handleToggleSeverity}
          counts={counts}
        />
      </div>
    </div>
  );
}
