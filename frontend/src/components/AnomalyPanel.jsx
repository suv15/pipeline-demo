import React, { useMemo } from 'react';

const SEV_ORDER = { high: 0, medium: 1, low: 2 };
const SEV_COLOR = { high: 'var(--sev-high)', medium: 'var(--sev-medium)', low: 'var(--sev-low)' };

function PinIcon() {
  return (
    <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5a2.5 2.5 0 0 1 0-5 2.5 2.5 0 0 1 0 5z"/>
    </svg>
  );
}

function formatRel(iso) {
  const diffMs = Date.now() - new Date(iso).getTime();
  const hrs = Math.floor(diffMs / 3600000);
  if (hrs < 1) return 'now';
  if (hrs < 24) return `${hrs}h`;
  return `${Math.floor(hrs / 24)}d`;
}

export default function AnomalyPanel({
  anomalies,
  selectedId,
  onSelect,
  severityFilter,
  onToggleSeverity,
  counts,
}) {
  const sorted = useMemo(() => {
    if (!anomalies) return [];
    return [...anomalies.features]
      .filter((f) => severityFilter.includes(f.properties.severity))
      .sort((a, b) => {
        const sa = SEV_ORDER[a.properties.severity];
        const sb = SEV_ORDER[b.properties.severity];
        if (sa !== sb) return sa - sb;
        return b.properties.confidence - a.properties.confidence;
      });
  }, [anomalies, severityFilter]);

  const totalCount = anomalies?.features?.length ?? 0;

  return (
    <div className="panel">
      <div className="panel-header">
        <div className="panel-header-top">
          <div className="panel-title">
            <span>Anomaly Feed</span>
            <span className="panel-count mono">{sorted.length}/{totalCount}</span>
          </div>
          <div className="panel-sublabel">Sorted by severity</div>
        </div>
        <div className="filter-row">
          {['high', 'medium', 'low'].map((sev) => {
            const active = severityFilter.includes(sev);
            return (
              <button
                key={sev}
                className={`filter-chip ${active ? 'active' : ''}`}
                onClick={() => onToggleSeverity(sev)}
              >
                <span className="chip-dot" style={{ background: SEV_COLOR[sev] }} />
                <span>{sev}</span>
                <span className="chip-count">{counts?.[sev] ?? 0}</span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="anomaly-list">
        {sorted.length === 0 && (
          <div className="empty-state">
            NO ANOMALIES MATCH CURRENT FILTERS
          </div>
        )}
        {sorted.map((f) => {
          const p = f.properties;
          const isSelected = p.id === selectedId;
          return (
            <div
              key={p.id}
              className={`anomaly-item ${isSelected ? 'selected' : ''}`}
              onClick={() => onSelect(p.id)}
            >
              <div className={`anomaly-severity-bar ${p.severity}`} />
              <div className="anomaly-body">
                <div className="anomaly-id mono">{p.id}</div>
                <div className="anomaly-type">{p.type.replace('_', ' ')}</div>
                <div className="anomaly-desc">{p.description}</div>
                <div className="anomaly-meta">
                  <span><PinIcon /> {p.tile_id}</span>
                  <span>{p.distance_to_pipeline_m}m from RoW</span>
                  <span>{p.area_hectares} ha</span>
                  <span>{formatRel(p.detected_at)}</span>
                </div>
              </div>
              <div className="anomaly-right">
                <span className={`severity-badge ${p.severity}`}>{p.severity}</span>
                <span className="confidence mono">
                  <strong>{Math.round(p.confidence * 100)}%</strong> conf.
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
