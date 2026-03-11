// Spore Explorer — API client and data layer

export async function fetchJson(url) {
  const res = await fetch(url);
  return res.json();
}

function buildQuery(params = {}) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '' || value === 'all') return;
    search.set(key, String(value));
  });
  const query = search.toString();
  return query ? `?${query}` : '';
}

export async function getStat(params = {}) {
  return fetchJson(`/api/stat${buildQuery(params)}`);
}

export async function getTasks() {
  return fetchJson('/api/tasks');
}

export async function getTask(taskId) {
  return fetchJson(`/api/task/${taskId}`);
}

export async function getTaskFeed(taskId, params = {}) {
  return fetchJson(`/api/task/${taskId}/feed${buildQuery(params)}`);
}

export async function getFeed(params = {}) {
  return fetchJson(`/api/feed${buildQuery(params)}`);
}

export async function getHotTasks(params = {}) {
  return fetchJson(`/api/tasks/hot${buildQuery(params)}`);
}

export async function getPulse(params = {}) {
  return fetchJson(`/api/pulse${buildQuery(params)}`);
}

export async function getGraph(params = {}) {
  return fetchJson(`/api/graph${buildQuery(params)}`);
}

export async function getFrontier(params = {}) {
  return fetchJson(`/api/frontier${buildQuery(params)}`);
}

export async function getExperiment(cid) {
  return fetchJson(`/api/experiment/${cid}`);
}

export async function getAncestor(cid) {
  return fetchJson(`/api/experiment/${cid}/ancestor`);
}

export async function getChildren(cid) {
  return fetchJson(`/api/experiment/${cid}/children`);
}

export async function getRecent(limit = 50, params = {}) {
  return fetchJson(`/api/recent${buildQuery({ limit, ...params })}`);
}

export async function getNodes(params = {}) {
  return fetchJson(`/api/nodes${buildQuery(params)}`);
}

export async function searchNodes(query, params = {}) {
  if (!query || query.length < 2) return [];
  return fetchJson(`/api/nodes/search${buildQuery({ q: query, ...params })}`);
}

export async function getNodeDetail(nodeId, params = {}) {
  return fetchJson(`/api/node/${nodeId}${buildQuery(params)}`);
}

export async function getNodeExperiment(nodeId, params = {}) {
  return fetchJson(`/api/node/${nodeId}/experiment${buildQuery(params)}`);
}

export async function getNodeProfile(nodeId) {
  return fetchJson(`/api/node/${nodeId}/profile`);
}

export async function searchExperiment(query, params = {}) {
  if (!query || query.length < 2) return [];
  return fetchJson(`/api/search${buildQuery({ q: query, ...params })}`);
}

export async function getArtifact(cid) {
  return fetchJson(`/api/artifact/${cid}`);
}

// --- Helpers ---

export function shortCid(cid) { return cid ? cid.slice(0, 8) : '—'; }

export function formatParam(n) {
  if (n >= 1e9) return (n / 1e9).toFixed(1) + 'B';
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
  return String(n);
}

export function statusColor(s) {
  return s === 'keep' ? '#4ade80' : s === 'discard' ? '#f87171' : '#fbbf24';
}

export function timeAgo(ts) {
  if (!ts) return '—';
  const sec = Math.floor(Date.now() / 1000 - ts);
  if (sec < 60) return sec + 's';
  if (sec < 3600) return Math.floor(sec / 60) + 'm';
  if (sec < 86400) return Math.floor(sec / 3600) + 'h';
  return Math.floor(sec / 86400) + 'd';
}

export function formatDateTime(ts) {
  if (!ts) return '—';
  return new Date(ts * 1000).toLocaleString();
}

export function escHtml(s) {
  const div = document.createElement('div');
  div.textContent = s;
  return div.innerHTML;
}
