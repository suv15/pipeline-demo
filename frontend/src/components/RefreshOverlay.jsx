import React, { useEffect, useState } from 'react';

const PHASES = [
  { at: 0,    msg: 'Initializing scan…' },
  { at: 10,   msg: 'Querying Copernicus STAC for Sentinel-1 GRD scenes…' },
  { at: 25,   msg: 'Computing SAR coherence change detection…' },
  { at: 45,   msg: 'Fetching Sentinel-2 L2A scenes…' },
  { at: 60,   msg: 'Running NDVI differencing across 25 tiles…' },
  { at: 75,   msg: 'Classifying change pixels with vision model…' },
  { at: 88,   msg: 'Aggregating anomalies and scoring confidence…' },
  { at: 97,   msg: 'Finalizing report…' },
];

export default function RefreshOverlay({ durationMs = 4000 }) {
  const [progress, setProgress] = useState(0);
  const [msgIdx, setMsgIdx] = useState(0);

  useEffect(() => {
    const start = Date.now();
    const tick = () => {
      const elapsed = Date.now() - start;
      const pct = Math.min(99, (elapsed / durationMs) * 100);
      setProgress(pct);

      let idx = 0;
      for (let i = 0; i < PHASES.length; i++) {
        if (pct >= PHASES[i].at) idx = i;
      }
      setMsgIdx(idx);

      if (pct < 99) requestAnimationFrame(tick);
    };
    const raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [durationMs]);

  return (
    <div className="refresh-overlay">
      <div className="refresh-status">
        <div className="refresh-status-label">FULL CORRIDOR SCAN IN PROGRESS</div>
        <div className="refresh-status-msg" key={msgIdx}>{PHASES[msgIdx].msg}</div>
        <div className="progress-track">
          <div className="progress-fill" style={{ width: `${progress}%` }} />
        </div>
        <div className="mono" style={{ marginTop: 12, fontSize: 11, color: 'var(--text-tertiary)', letterSpacing: '0.1em' }}>
          {Math.floor(progress)}% · 1,870 KM CORRIDOR · 25 TILES
        </div>
      </div>
    </div>
  );
}
