const API_BASE = import.meta.env.VITE_API_BASE || '/api';

async function req(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, options);
  if (!res.ok) throw new Error(`${options.method || 'GET'} ${path} failed: ${res.status}`);
  return res.json();
}

export const api = {
  getBaseline: () => req('/baseline'),
  getFullScan: () => req('/full_scan'),
  getScanMetadata: () => req('/scan_metadata'),
  triggerRefresh: () => req('/refresh', { method: 'POST' }),
};
