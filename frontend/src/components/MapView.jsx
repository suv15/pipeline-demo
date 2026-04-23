import React, { useEffect, useRef } from 'react';
import maplibregl from 'maplibre-gl';

const SEVERITY_COLOR = {
  high: '#ff3b47',
  medium: '#ffa726',
  low: '#4dd0e1',
};

const LAYER_IDS = [
  'buffer-5km-fill', 'buffer-5km-line',
  'buffer-1km-fill', 'buffer-1km-line',
  'pipeline-line', 'pipeline-glow',
  'tiles-line',
  'anomalies-halo', 'anomalies-fill',
];

function popupHtml(props) {
  const sev = props.severity;
  return `
    <div class="popup-id">${props.id}</div>
    <div class="popup-title">${props.type.replace('_', ' ')}</div>
    <div style="font-size:12px;color:var(--text-secondary)">${props.description}</div>
    <dl class="popup-grid">
      <dt>SEVERITY</dt><dd style="color:${SEVERITY_COLOR[sev]};font-weight:700">${sev.toUpperCase()}</dd>
      <dt>CONFIDENCE</dt><dd>${Math.round(props.confidence * 100)}%</dd>
      <dt>SOURCE</dt><dd>${props.source}</dd>
      <dt>AREA</dt><dd>${props.area_hectares} ha</dd>
      <dt>DIST TO RoW</dt><dd>${props.distance_to_pipeline_m} m</dd>
      <dt>TILE</dt><dd>${props.tile_id}</dd>
    </dl>
  `;
}

export default function MapView({
  baseline,
  anomalies,
  selectedAnomalyId,
  onSelectAnomaly,
  severityFilter,
  theme,
}) {
  const mapRef = useRef(null);
  const mapInstance = useRef(null);
  const popupRef = useRef(null);
  const themeRef = useRef(theme);

  // --- Init map ---
  useEffect(() => {
    if (mapInstance.current) return;
    const styleUrl = theme === 'dark'
      ? 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json'
      : 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json';

    const map = new maplibregl.Map({
      container: mapRef.current,
      style: styleUrl,
      center: [73.5, 23.5],
      zoom: 5.6,
      attributionControl: false,
      pitch: 0,
    });

    map.addControl(new maplibregl.NavigationControl({ showCompass: false, visualizePitch: false }), 'top-left');
    map.addControl(new maplibregl.ScaleControl({ maxWidth: 100, unit: 'metric' }), 'bottom-right');

    mapInstance.current = map;

    return () => {
      map.remove();
      mapInstance.current = null;
    };
  }, []);

  // --- Handle theme change: swap basemap style, re-add our layers ---
  useEffect(() => {
    const map = mapInstance.current;
    if (!map || themeRef.current === theme) return;
    themeRef.current = theme;

    const styleUrl = theme === 'dark'
      ? 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json'
      : 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json';

    map.setStyle(styleUrl);
    // addBaselineLayers will re-run via its effect once style is loaded because
    // the source-data effect depends on baseline and fires after style is ready.
    map.once('styledata', () => {
      if (baseline) addBaselineLayers(map, baseline, theme);
      if (anomalies) upsertAnomalyLayer(map, anomalies, severityFilter);
    });
  }, [theme]); // eslint-disable-line react-hooks/exhaustive-deps

  // --- Add baseline layers when baseline data arrives ---
  useEffect(() => {
    const map = mapInstance.current;
    if (!map || !baseline) return;
    if (map.isStyleLoaded()) {
      addBaselineLayers(map, baseline, theme);
    } else {
      map.once('load', () => addBaselineLayers(map, baseline, theme));
    }
  }, [baseline]); // eslint-disable-line react-hooks/exhaustive-deps

  // --- Upsert anomaly layer when anomalies change ---
  useEffect(() => {
    const map = mapInstance.current;
    if (!map || !anomalies) return;
    if (map.isStyleLoaded()) {
      upsertAnomalyLayer(map, anomalies, severityFilter);
    } else {
      map.once('load', () => upsertAnomalyLayer(map, anomalies, severityFilter));
    }
  }, [anomalies, severityFilter]);

  // --- Fly to & popup when selected anomaly changes ---
  useEffect(() => {
    const map = mapInstance.current;
    if (!map || !selectedAnomalyId || !anomalies) return;
    const feat = anomalies.features.find((f) => f.properties.id === selectedAnomalyId);
    if (!feat) return;

    const [lng, lat] = feat.geometry.coordinates;
    map.flyTo({ center: [lng, lat], zoom: 10.5, speed: 1.4, curve: 1.6 });

    if (popupRef.current) popupRef.current.remove();
    popupRef.current = new maplibregl.Popup({ offset: 14, closeButton: true, closeOnClick: false })
      .setLngLat([lng, lat])
      .setHTML(popupHtml(feat.properties))
      .addTo(map);
  }, [selectedAnomalyId, anomalies]);

  // --- Click handler on anomaly layer ---
  useEffect(() => {
    const map = mapInstance.current;
    if (!map) return;

    const handler = (e) => {
      if (!e.features?.length) return;
      const id = e.features[0].properties.id;
      onSelectAnomaly(id);
    };

    const enter = () => { map.getCanvas().style.cursor = 'pointer'; };
    const leave = () => { map.getCanvas().style.cursor = ''; };

    map.on('click', 'anomalies-fill', handler);
    map.on('mouseenter', 'anomalies-fill', enter);
    map.on('mouseleave', 'anomalies-fill', leave);

    return () => {
      map.off('click', 'anomalies-fill', handler);
      map.off('mouseenter', 'anomalies-fill', enter);
      map.off('mouseleave', 'anomalies-fill', leave);
    };
  }, [onSelectAnomaly]);

  return (
    <div className="map-container">
      <div ref={mapRef} style={{ position: 'absolute', inset: 0 }} />
      <div className="map-legend">
        <div className="legend-title">Legend</div>
        <div className="legend-group">
          <div className="legend-item"><span className="legend-swatch line" style={{ background: '#00d4aa' }} />Pipeline</div>
          <div className="legend-item"><span className="legend-swatch" style={{ background: 'rgba(0,212,170,0.15)', border: '1px solid rgba(0,212,170,0.5)' }} />RoW Buffer (1 km)</div>
          <div className="legend-item"><span className="legend-swatch" style={{ background: 'rgba(0,212,170,0.04)', border: '1px solid rgba(0,212,170,0.25)' }} />Monitoring (5 km)</div>
        </div>
        <div className="legend-group">
          <div className="legend-item"><span className="legend-swatch dot" style={{ background: '#ff3b47' }} />High Severity</div>
          <div className="legend-item"><span className="legend-swatch dot" style={{ background: '#ffa726' }} />Medium Severity</div>
          <div className="legend-item"><span className="legend-swatch dot" style={{ background: '#4dd0e1' }} />Low Severity</div>
        </div>
      </div>
      <div className="map-attribution">© OpenStreetMap · CARTO · Sentinel-1/2</div>
    </div>
  );
}

// --- Helpers ---

function addBaselineLayers(map, baseline, theme) {
  const pipeColor = '#00d4aa';

  // Sources
  if (!map.getSource('pipeline')) {
    map.addSource('pipeline', { type: 'geojson', data: baseline.pipeline });
  } else {
    map.getSource('pipeline').setData(baseline.pipeline);
  }
  if (!map.getSource('buffer-1km')) {
    map.addSource('buffer-1km', { type: 'geojson', data: baseline.buffer_1km });
  } else {
    map.getSource('buffer-1km').setData(baseline.buffer_1km);
  }
  if (!map.getSource('buffer-5km')) {
    map.addSource('buffer-5km', { type: 'geojson', data: baseline.buffer_5km });
  } else {
    map.getSource('buffer-5km').setData(baseline.buffer_5km);
  }
  if (!map.getSource('tiles')) {
    map.addSource('tiles', { type: 'geojson', data: baseline.tiles });
  } else {
    map.getSource('tiles').setData(baseline.tiles);
  }

  // Remove any old versions of our layers (e.g. after style swap)
  LAYER_IDS.forEach((id) => { if (map.getLayer(id)) map.removeLayer(id); });

  // 5 km buffer (outer)
  map.addLayer({
    id: 'buffer-5km-fill',
    type: 'fill',
    source: 'buffer-5km',
    paint: { 'fill-color': pipeColor, 'fill-opacity': theme === 'dark' ? 0.04 : 0.06 },
  });
  map.addLayer({
    id: 'buffer-5km-line',
    type: 'line',
    source: 'buffer-5km',
    paint: { 'line-color': pipeColor, 'line-opacity': 0.25, 'line-width': 0.6, 'line-dasharray': [2, 2] },
  });

  // 1 km buffer (RoW)
  map.addLayer({
    id: 'buffer-1km-fill',
    type: 'fill',
    source: 'buffer-1km',
    paint: { 'fill-color': pipeColor, 'fill-opacity': theme === 'dark' ? 0.12 : 0.14 },
  });
  map.addLayer({
    id: 'buffer-1km-line',
    type: 'line',
    source: 'buffer-1km',
    paint: { 'line-color': pipeColor, 'line-opacity': 0.55, 'line-width': 0.9 },
  });

  // Tiles (hair-thin grid, shown only when zoomed in a bit)
  map.addLayer({
    id: 'tiles-line',
    type: 'line',
    source: 'tiles',
    paint: {
      'line-color': pipeColor,
      'line-opacity': ['interpolate', ['linear'], ['zoom'], 5, 0, 7, 0.15, 9, 0.3],
      'line-width': 0.5,
      'line-dasharray': [3, 3],
    },
  });

  // Pipeline glow + main line
  map.addLayer({
    id: 'pipeline-glow',
    type: 'line',
    source: 'pipeline',
    paint: {
      'line-color': pipeColor,
      'line-width': ['interpolate', ['linear'], ['zoom'], 5, 4, 10, 10],
      'line-opacity': theme === 'dark' ? 0.35 : 0.2,
      'line-blur': 4,
    },
    layout: { 'line-cap': 'round', 'line-join': 'round' },
  });
  map.addLayer({
    id: 'pipeline-line',
    type: 'line',
    source: 'pipeline',
    paint: {
      'line-color': pipeColor,
      'line-width': ['interpolate', ['linear'], ['zoom'], 5, 1.5, 10, 3],
      'line-opacity': 1,
    },
    layout: { 'line-cap': 'round', 'line-join': 'round' },
  });
}

function upsertAnomalyLayer(map, anomalies, severityFilter) {
  // Filter features client-side
  const filtered = {
    ...anomalies,
    features: anomalies.features.filter((f) => severityFilter.includes(f.properties.severity)),
  };

  if (!map.getSource('anomalies')) {
    map.addSource('anomalies', { type: 'geojson', data: filtered });
  } else {
    map.getSource('anomalies').setData(filtered);
  }

  if (map.getLayer('anomalies-halo')) return; // already added

  map.addLayer({
    id: 'anomalies-halo',
    type: 'circle',
    source: 'anomalies',
    paint: {
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 5, 8, 12, 20],
      'circle-color': [
        'match', ['get', 'severity'],
        'high', '#ff3b47',
        'medium', '#ffa726',
        'low', '#4dd0e1',
        '#888',
      ],
      'circle-opacity': 0.18,
      'circle-blur': 0.6,
    },
  });

  map.addLayer({
    id: 'anomalies-fill',
    type: 'circle',
    source: 'anomalies',
    paint: {
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 5, 3.5, 12, 7],
      'circle-color': [
        'match', ['get', 'severity'],
        'high', '#ff3b47',
        'medium', '#ffa726',
        'low', '#4dd0e1',
        '#888',
      ],
      'circle-stroke-color': '#ffffff',
      'circle-stroke-width': 1.2,
      'circle-stroke-opacity': 0.9,
    },
  });
}
