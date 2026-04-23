import React from 'react';

function BrandMark({ accent }) {
  return (
    <svg width="32" height="32" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect x="1" y="1" width="30" height="30" rx="2" stroke={accent} strokeWidth="1" opacity="0.35" />
      <path d="M6 16 L11 16 L13 11 L15 21 L17 13 L19 19 L21 16 L26 16"
            stroke={accent} strokeWidth="1.6" strokeLinecap="square" strokeLinejoin="miter" fill="none" />
      <circle cx="6" cy="16" r="1.5" fill={accent} />
      <circle cx="26" cy="16" r="1.5" fill={accent} />
      <line x1="4" y1="4" x2="7" y2="4" stroke={accent} strokeWidth="1" opacity="0.5" />
      <line x1="4" y1="4" x2="4" y2="7" stroke={accent} strokeWidth="1" opacity="0.5" />
      <line x1="28" y1="28" x2="25" y2="28" stroke={accent} strokeWidth="1" opacity="0.5" />
      <line x1="28" y1="28" x2="28" y2="25" stroke={accent} strokeWidth="1" opacity="0.5" />
    </svg>
  );
}

function SunIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  );
}

function RefreshIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="square">
      <path d="M21 2v6h-6" />
      <path d="M3 12a9 9 0 0 1 15-6.7L21 8" />
      <path d="M3 22v-6h6" />
      <path d="M21 12a9 9 0 0 1-15 6.7L3 16" />
    </svg>
  );
}

function formatHoursSince(iso) {
  if (!iso) return '—';
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export default function Header({ stats, isRefreshing, onRefresh, theme, onToggleTheme }) {
  const accent = theme === 'dark' ? '#00d4aa' : '#1b5e52';

  return (
    <div className="header">
      <div className="brand">
        <div className="brand-mark">
          <BrandMark accent={accent} />
        </div>
        <div className="brand-text">
          <div className="brand-title">PIPELINE INTELLIGENCE</div>
          <div className="brand-subtitle">IOCL · SALAYA → MATHURA · 1870 KM</div>
        </div>
      </div>

      <div className="header-stats">
        <div className="stat">
          <div className="stat-label">Last Scan</div>
          <div className="stat-value mono">{formatHoursSince(stats?.last_scan_at)}</div>
        </div>
        <div className="stat">
          <div className="stat-label">Tiles Analyzed</div>
          <div className="stat-value mono accent">
            {stats?.tiles_processed ?? '—'}<span style={{ color: 'var(--text-tertiary)', fontSize: 13 }}>/{stats?.tiles_processed ?? '—'}</span>
          </div>
        </div>
        <div className="stat">
          <div className="stat-label">Total Anomalies</div>
          <div className="stat-value mono">{stats?.total_anomalies ?? '—'}</div>
          <div className="stat-breakdown">
            <span><span className="dot" style={{ background: 'var(--sev-high)' }} />{stats?.by_severity?.high ?? 0}</span>
            <span><span className="dot" style={{ background: 'var(--sev-medium)' }} />{stats?.by_severity?.medium ?? 0}</span>
            <span><span className="dot" style={{ background: 'var(--sev-low)' }} />{stats?.by_severity?.low ?? 0}</span>
          </div>
        </div>
        <div className="stat">
          <div className="stat-label">High Severity</div>
          <div className="stat-value mono high">{stats?.by_severity?.high ?? '—'}</div>
        </div>
      </div>

      <div className="header-actions">
        <div className="live-indicator">
          <span className="live-dot" />
          <span>LIVE</span>
        </div>
        <button className="refresh-btn" disabled={isRefreshing} onClick={onRefresh}>
          {isRefreshing ? (
            <>
              <span className="spinner" /> Scanning…
            </>
          ) : (
            <>
              <RefreshIcon /> Full Scan
            </>
          )}
        </button>
        <button className="icon-btn" onClick={onToggleTheme} aria-label="Toggle theme" title="Toggle theme">
          {theme === 'dark' ? <SunIcon /> : <MoonIcon />}
        </button>
      </div>
    </div>
  );
}
