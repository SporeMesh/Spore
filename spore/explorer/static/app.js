// Spore Explorer — main application

import {
  getStat, getGraph, getFrontier, getExperiment, getAncestor,
  getChildren, getLeaderboard, getNodeReputation, searchExperiment, getArtifact,
  shortCid, formatParam, statusColor, timeAgo, escHtml,
} from './api.js';
import { initDag, renderDag, updateSelection, resetHighlight } from './dag.js';

// ===== STATE =====
let graphData = { node: [], edge: [], frontier_id: [] };
let selectedNode = null;
let statusFilter = 'all';
let searchTimeout = null;

// ===== TABS =====
document.querySelectorAll('.tab-bar button').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-bar button').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(btn.dataset.tab).classList.add('active');
  });
});

// ===== SEARCH =====
const searchInput = document.getElementById('search-input');
const searchResult = document.getElementById('search-result');

searchInput.addEventListener('input', () => {
  clearTimeout(searchTimeout);
  const q = searchInput.value.trim();
  if (q.length < 2) {
    searchResult.classList.remove('open');
    return;
  }
  searchTimeout = setTimeout(async () => {
    const results = await searchExperiment(q);
    renderSearchResult(results);
  }, 200);
});

searchInput.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    searchResult.classList.remove('open');
    searchInput.blur();
  }
});

document.addEventListener('click', (e) => {
  if (!e.target.closest('.search-wrap')) {
    searchResult.classList.remove('open');
  }
});

function renderSearchResult(results) {
  if (results.length === 0) {
    searchResult.classList.remove('open');
    return;
  }
  searchResult.innerHTML = results.map(r => `
    <div class="search-item" data-cid="${r.id}">
      <span class="status-badge ${r.status}">${r.status}</span>
      <span style="color:var(--cyan)">${shortCid(r.id)}</span>
      <span style="color:var(--text)">${r.val_bpb.toFixed(6)}</span>
      <span style="color:var(--text-dim);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1">${escHtml(r.description.slice(0, 60))}</span>
    </div>
  `).join('');
  searchResult.classList.add('open');

  searchResult.querySelectorAll('.search-item').forEach(el => {
    el.addEventListener('click', () => {
      selectExperiment(el.dataset.cid);
      searchResult.classList.remove('open');
      searchInput.value = '';
    });
  });
}

// ===== FILTER =====
document.querySelectorAll('.filter-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    statusFilter = btn.dataset.filter;
    renderDag(getFilteredGraph(), selectedNode);
  });
});

function getFilteredGraph() {
  if (statusFilter === 'all') return graphData;
  const filtered = graphData.node.filter(n => n.status === statusFilter);
  const ids = new Set(filtered.map(n => n.id));
  return {
    node: filtered,
    edge: graphData.edge.filter(e => ids.has(e.source) && ids.has(e.target)),
    frontier_id: graphData.frontier_id.filter(id => ids.has(id)),
  };
}

// ===== STATS =====
async function refreshStat() {
  const s = await getStat();
  document.getElementById('stat-total').textContent = s.experiment_count;
  document.getElementById('stat-frontier').textContent = s.frontier_size;
  document.getElementById('stat-best').textContent = s.best_val_bpb != null ? s.best_val_bpb.toFixed(6) : '—';
  document.getElementById('stat-peer').textContent = s.peer_count;
  document.getElementById('hdr-node').textContent = shortCid(s.node_id);
}

// ===== FRONTIER TABLE =====
async function refreshFrontier() {
  const data = await getFrontier();
  const tbody = document.querySelector('#frontier-table tbody');
  tbody.innerHTML = '';
  data.forEach(r => {
    const tr = document.createElement('tr');
    tr.className = 'clickable';
    tr.onclick = () => selectExperiment(r.id);
    tr.innerHTML = `
      <td style="color:var(--cyan)">${shortCid(r.id)}</td>
      <td style="color:var(--green)">${r.val_bpb.toFixed(6)}</td>
      <td>${r.depth}</td>
      <td>${r.gpu_model || '—'}</td>
      <td>${r.num_steps}</td>
      <td>${formatParam(r.num_params)}</td>
      <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis">${escHtml(r.description.slice(0, 80))}</td>
    `;
    tbody.appendChild(tr);
  });
}

// ===== LEADERBOARD =====
async function refreshLeaderboard() {
  const data = await getLeaderboard();
  const tbody = document.querySelector('#leaderboard-table tbody');
  tbody.innerHTML = '';
  if (data.length === 0) {
    const tr = document.createElement('tr');
    tr.innerHTML = '<td colspan="7" style="color:var(--text-dim);text-align:center">No reputation data yet</td>';
    tbody.appendChild(tr);
    return;
  }
  data.forEach((r, i) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${i + 1}</td>
      <td style="color:var(--cyan);cursor:pointer" onclick="window.__selectNode && window.__selectNode('${r.node_id}')">${shortCid(r.node_id)}</td>
      <td style="color:${r.score >= 0 ? 'var(--green)' : 'var(--red)'}">${r.score.toFixed(1)}</td>
      <td>${r.experiments_published}</td>
      <td>${r.experiments_verified}</td>
      <td>${r.disputes_won}</td>
      <td>${r.disputes_lost}</td>
    `;
    tbody.appendChild(tr);
  });
}

// ===== DETAIL PANEL =====
async function selectExperiment(cid) {
  selectedNode = cid;
  const r = await getExperiment(cid);
  if (r.error) return;
  const rep = await getNodeReputation(r.node_id);

  document.getElementById('detail-empty').style.display = 'none';
  const content = document.getElementById('detail-content');
  content.style.display = 'block';

  // Delta from parent
  let deltaHtml = '';
  if (r.parent) {
    const parent = await getExperiment(r.parent);
    if (!parent.error) {
      const delta = r.val_bpb - parent.val_bpb;
      const sign = delta <= 0 ? '' : '+';
      const cls = delta <= 0 ? 'keep' : 'discard';
      deltaHtml = ` <span class="value ${cls}" style="font-size:13px">(${sign}${delta.toFixed(6)})</span>`;
    }
  }

  // Diff
  let diffHtml = '';
  if (r.diff) {
    diffHtml = r.diff.split('\n').map(line => {
      if (line.startsWith('@@')) return `<span class="hunk">${escHtml(line)}</span>`;
      if (line.startsWith('+')) return `<span class="add">${escHtml(line)}</span>`;
      if (line.startsWith('-')) return `<span class="del">${escHtml(line)}</span>`;
      return escHtml(line);
    }).join('\n');
  }

  content.innerHTML = `
    <div class="detail-section">
      <div class="detail-field">
        <label>CID <button class="copy-btn" onclick="navigator.clipboard.writeText('${r.id}')">copy</button></label>
        <div class="value cid" style="font-size:10px;word-break:break-all">${r.id}</div>
      </div>
      <div class="detail-field">
        <label>Status</label>
        <span class="status-badge ${r.status}">${r.status}</span>
      </div>
      <div class="detail-field">
        <label>val_bpb</label>
        <div class="value bpb ${r.status}">${r.val_bpb.toFixed(6)}</div>${deltaHtml}
      </div>
    </div>

    <div class="detail-section">
      <div class="detail-field">
        <label>Description</label>
        <div class="value" style="line-height:1.4">${escHtml(r.description)}</div>
      </div>
      ${r.hypothesis && r.hypothesis !== '—' ? `<div class="detail-field"><label>Hypothesis</label><div class="value" style="line-height:1.4">${escHtml(r.hypothesis)}</div></div>` : ''}
    </div>

    <div class="detail-section">
      <div class="detail-field">
        <label>Parent</label>
        <div class="value cid" onclick="window.__select('${r.parent || ''}')">${r.parent ? shortCid(r.parent) : 'genesis'}</div>
      </div>
      <div class="detail-field">
        <label>Depth</label>
        <div class="value">${r.depth}</div>
      </div>
      <div id="children-section"></div>
    </div>

    ${r.diff ? `<div class="detail-section"><label style="font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.5px">Diff</label><div class="diff-block">${diffHtml}</div></div>` : ''}

    <div id="code-section"></div>

    <div class="detail-section">
      <div class="detail-field">
        <label>Hardware</label>
        <div class="value">${escHtml(r.gpu_model || '—')}</div>
      </div>
      <div class="detail-field">
        <label>VRAM</label>
        <div class="value">${r.peak_vram_mb.toFixed(0)} MB</div>
      </div>
      <div class="detail-field">
        <label>Training</label>
        <div class="value">${r.num_steps} steps · ${formatParam(r.num_params)} params · ${r.time_budget}s budget</div>
      </div>
      <div class="detail-field">
        <label>Agent</label>
        <div class="value">${escHtml(r.agent_model || '—')}</div>
      </div>
      <div class="detail-field">
        <label>Node</label>
        <div class="value cid" onclick="window.__selectNode && window.__selectNode('${r.node_id}')">${shortCid(r.node_id)}</div>
      </div>
      <div class="detail-field">
        <label>Reputation</label>
        <div class="value">${rep.score.toFixed(1)} · ${rep.experiments_published} published · ${rep.experiments_verified} verified</div>
      </div>
      <div class="detail-field">
        <label>Time</label>
        <div class="value">${new Date(r.timestamp * 1000).toLocaleString()}</div>
      </div>
    </div>
  `;

  // Load children
  loadChildren(cid);

  // Load ancestor chain + highlight path
  const ancestors = await getAncestor(cid);
  const pathIds = ancestors.map(a => a.id);

  if (ancestors.length > 1) {
    let chainHtml = '<div class="ancestor-chain"><label style="font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;display:block">Lineage</label>';
    ancestors.forEach((a, i) => {
      const dotColor = statusColor(a.status);
      const isCurrent = a.id === cid;
      chainHtml += `
        ${i > 0 ? '<div class="ancestor-item"><span class="line"></span></div>' : ''}
        <div class="ancestor-item ${isCurrent ? 'current' : ''}" onclick="window.__select('${a.id}')">
          <span class="dot" style="background:${dotColor}"></span>
          <span style="color:var(--cyan)">${shortCid(a.id)}</span>
          <span>${a.val_bpb.toFixed(6)}</span>
          <span style="color:var(--text-dim);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(a.description.slice(0, 40))}</span>
        </div>`;
    });
    chainHtml += '</div>';
    content.innerHTML += chainHtml;
  }

  // Load code artifact
  loadCode(r.code_cid);

  // Update DAG highlighting
  updateSelection(selectedNode, pathIds);
}

async function loadChildren(cid) {
  const kids = await getChildren(cid);
  const el = document.getElementById('children-section');
  if (!el || kids.length === 0) return;
  el.innerHTML = `
    <div class="detail-field">
      <label>Children (${kids.length})</label>
      ${kids.map(k => `
        <div style="display:flex;gap:6px;align-items:center;padding:2px 0;cursor:pointer" onclick="window.__select('${k.id}')">
          <span class="status-badge ${k.status}" style="font-size:9px">${k.status}</span>
          <span style="color:var(--cyan);font-size:11px">${shortCid(k.id)}</span>
          <span style="font-size:11px">${k.val_bpb.toFixed(6)}</span>
        </div>
      `).join('')}
    </div>
  `;
}

async function loadCode(codeCid) {
  const el = document.getElementById('code-section');
  if (!el || !codeCid) return;
  el.innerHTML = `
    <div class="detail-section">
      <label style="font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.5px;cursor:pointer" id="code-toggle">
        Code Snapshot ▸
      </label>
      <div id="code-content" style="display:none"></div>
    </div>
  `;
  document.getElementById('code-toggle').addEventListener('click', async () => {
    const contentEl = document.getElementById('code-content');
    if (contentEl.style.display === 'none') {
      document.getElementById('code-toggle').textContent = 'Code Snapshot ▾';
      const artifact = await getArtifact(codeCid);
      if (artifact.error) {
        contentEl.innerHTML = '<div style="color:var(--text-dim);padding:8px">Artifact not available</div>';
      } else {
        contentEl.innerHTML = `<div class="code-block">${escHtml(artifact.content)}</div>`;
      }
      contentEl.style.display = 'block';
    } else {
      contentEl.style.display = 'none';
      document.getElementById('code-toggle').textContent = 'Code Snapshot ▸';
    }
  });
}

// Global handlers for inline onclick
window.__select = (cid) => { if (cid) selectExperiment(cid); };
window.__selectNode = async (nodeId) => {
  searchInput.value = nodeId.slice(0, 8);
  const results = await searchExperiment(nodeId.slice(0, 8));
  renderSearchResult(results);
};

// ===== ACTIVITY FEED =====
function addActivity(record) {
  const feed = document.getElementById('activity-feed');
  const item = document.createElement('div');
  item.className = 'activity-item';
  item.innerHTML = `
    <span class="time">${timeAgo(record.timestamp)}</span>
    <span class="status-badge ${record.status}">${record.status}</span>
    <span class="cid-link" onclick="window.__select('${record.id}')">${shortCid(record.id)}</span>
    <span>${record.val_bpb.toFixed(6)}</span>
    <span class="desc">${escHtml(record.description.slice(0, 60))}</span>
  `;
  feed.prepend(item);
  while (feed.children.length > 100) feed.removeChild(feed.lastChild);
}

// ===== WEBSOCKET =====
function connectWs() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${proto}//${location.host}/ws`);

  ws.onopen = () => {
    document.getElementById('ws-dot').classList.add('connected');
  };

  ws.onclose = () => {
    document.getElementById('ws-dot').classList.remove('connected');
    setTimeout(connectWs, 2000);
  };

  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.event === 'experiment') {
      const record = msg.data;
      const existing = graphData.node.find(n => n.id === record.id);
      if (!existing) {
        graphData.node.push(record);
        if (record.parent) {
          graphData.edge.push({ source: record.parent, target: record.id });
        }
      }

      getFrontier().then(frontier => {
        graphData.frontier_id = frontier.map(f => f.id);
        renderDag(getFilteredGraph(), selectedNode);
      });

      addActivity(record);
      refreshStat();
      refreshFrontier();
    }
  };
}

// ===== KEYBOARD SHORTCUTS =====
document.addEventListener('keydown', (e) => {
  if (e.key === '/' && !e.ctrlKey && !e.metaKey && document.activeElement !== searchInput) {
    e.preventDefault();
    searchInput.focus();
  }
  if (e.key === 'Escape' && selectedNode) {
    selectedNode = null;
    resetHighlight();
    document.getElementById('detail-empty').style.display = 'block';
    document.getElementById('detail-content').style.display = 'none';
  }
});

// ===== INIT =====
async function init() {
  const dagPanel = document.getElementById('dag-panel');
  initDag(dagPanel, selectExperiment);

  const [graphResp] = await Promise.all([
    getGraph(),
    refreshStat(),
    refreshFrontier(),
    refreshLeaderboard(),
  ]);

  graphData = graphResp;

  graphData.node
    .sort((a, b) => b.timestamp - a.timestamp)
    .slice(0, 50)
    .forEach(addActivity);

  renderDag(graphData, null);
  connectWs();

  setInterval(() => {
    refreshStat();
    refreshFrontier();
    refreshLeaderboard();
  }, 10000);
}

init();
