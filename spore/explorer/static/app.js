// Spore Explorer — main application

import {
  formatDateTime,
  formatParam,
  getArtifact,
  getAncestor,
  getFeed,
  getChildren,
  getExperiment,
  getFrontier,
  getGraph,
  getHotTasks,
  getNodeDetail,
  getNodes,
  getPulse,
  getStat,
  getTask,
  getTaskFeed,
  getTasks,
  searchExperiment,
  searchNodes,
  shortCid,
  statusColor,
  timeAgo,
  escHtml,
} from './api.js';
import { initDag, renderDag, updateSelection, resetHighlight } from './dag.js';

const state = {
  graphData: { node: [], edge: [], frontier_id: [] },
  tasks: [],
  selectedTaskId: '',
  selectedExperimentId: null,
  selectedNodeId: null,
  selectedTaskDetailId: null,
  detailMode: 'empty',
  statusFilter: 'all',
  searchTimeout: null,
  pulse: null,
  storyFeed: [],
  hotTasks: [],
  nodeFilters: {
    activity: 'all',
    status: 'all',
    has_profile: 'all',
    sort: 'recent',
  },
  nodeDetailFilters: {
    status: 'all',
    verified_only: false,
    frontier_only: false,
  },
};

const detailTitle = document.getElementById('detail-title');
const detailSubtitle = document.getElementById('detail-subtitle');
const detailEmpty = document.getElementById('detail-empty');
const detailContent = document.getElementById('detail-content');
const searchInput = document.getElementById('search-input');
const searchResult = document.getElementById('search-result');
const taskSelect = document.getElementById('task-select');

const nodeFilterEls = {
  activity: document.getElementById('node-activity-filter'),
  status: document.getElementById('node-status-filter'),
  has_profile: document.getElementById('node-profile-filter'),
  sort: document.getElementById('node-sort-filter'),
};

function initialsFromName(name) {
  const source = (name || '').trim();
  if (!source) return 'SP';
  return source
    .split(/\s+/)
    .slice(0, 2)
    .map(part => part[0]?.toUpperCase() || '')
    .join('') || source.slice(0, 2).toUpperCase();
}

function safeUrl(url) {
  if (!url) return '';
  try {
    const parsed = new URL(url, window.location.origin);
    if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
      return parsed.href;
    }
  } catch (_) {
    return '';
  }
  return '';
}

function renderAvatar(url, label, size = 'md') {
  const safe = safeUrl(url);
  if (safe) {
    return `<img class="avatar avatar-${size}" src="${safe}" alt="${escHtml(label || 'Node avatar')}">`;
  }
  return `<div class="avatar avatar-${size} avatar-fallback">${escHtml(initialsFromName(label))}</div>`;
}

function activityClass(activity) {
  return activity || 'observer';
}

function renderActivityBadge(activity) {
  const label = activity || 'observer';
  return `<span class="activity-badge ${activityClass(label)}">${escHtml(label)}</span>`;
}

function renderFlagPills(record) {
  const pills = [];
  if (record.verified) pills.push('<span class="mini-pill verified">verified</span>');
  if (record.is_frontier) pills.push('<span class="mini-pill frontier">frontier</span>');
  return pills.join('');
}

function taskParams(extra = {}) {
  return state.selectedTaskId ? { task_id: state.selectedTaskId, ...extra } : extra;
}

function formatDurationCompact(seconds) {
  if (!seconds) return '0m';
  if (seconds >= 3600) return `${(seconds / 3600).toFixed(seconds >= 36000 ? 0 : 1)}h`;
  if (seconds >= 60) return `${Math.round(seconds / 60)}m`;
  return `${seconds}s`;
}

function formatSignedDelta(delta) {
  if (delta == null) return 'baseline';
  if (delta === 0) return 'flat';
  return `${delta > 0 ? '+' : ''}${delta.toFixed(6)}`;
}

function absoluteUrl(path) {
  return new URL(path, window.location.origin).toString();
}

async function copyText(value) {
  try {
    await navigator.clipboard.writeText(value);
  } catch (_) {
    // Ignore clipboard failures in unsupported contexts.
  }
}

function updateUrlState() {
  const params = new URLSearchParams(window.location.search);
  if (state.selectedTaskId) params.set('task', state.selectedTaskId);
  else params.delete('task');

  if (state.selectedExperimentId) params.set('experiment', state.selectedExperimentId);
  else params.delete('experiment');

  if (state.selectedNodeId) params.set('node', state.selectedNodeId);
  else params.delete('node');

  const query = params.toString();
  const next = query ? `${window.location.pathname}?${query}` : window.location.pathname;
  window.history.replaceState({}, '', next);
}

function renderShareActions(path, label = 'share link') {
  const url = absoluteUrl(path);
  return `
    <div class="profile-links">
      <button class="inline-link" onclick='window.__copyLink(${JSON.stringify(url)})'>${escHtml(label)}</button>
      <span class="muted-cid">${escHtml(url.replace(window.location.origin, ''))}</span>
    </div>
  `;
}

function buildSharePath(params = {}) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value) search.set(key, value);
  });
  const query = search.toString();
  return query ? `/?${query}` : '/';
}

function renderNodeName(summary, opts = {}) {
  const display = summary.display_name || shortCid(summary.node_id);
  const subtitle = opts.hideSubtitle ? '' : `<div class="muted-cid">${shortCid(summary.node_id)}</div>`;
  return `
    <div class="entity">
      ${renderAvatar(summary.avatar_url, display, opts.avatarSize || 'sm')}
      <div class="entity-copy">
        <div class="entity-title">${escHtml(display)}</div>
        ${subtitle}
      </div>
    </div>
  `;
}

function setDetailHeader(title, subtitle = '') {
  detailTitle.textContent = title;
  detailSubtitle.textContent = subtitle;
}

function showDetail(html) {
  detailEmpty.style.display = 'none';
  detailContent.style.display = 'block';
  detailContent.innerHTML = html;
}

function clearDetail() {
  state.selectedExperimentId = null;
  state.selectedNodeId = null;
  state.selectedTaskDetailId = null;
  state.detailMode = 'empty';
  setDetailHeader('Detail', 'Choose a task, experiment, or node');
  detailContent.style.display = 'none';
  detailEmpty.style.display = 'block';
  resetHighlight();
  updateUrlState();
}

function getFilteredGraph() {
  if (state.statusFilter === 'all') return state.graphData;
  const filtered = state.graphData.node.filter(node => node.status === state.statusFilter);
  const ids = new Set(filtered.map(node => node.id));
  return {
    node: filtered,
    edge: state.graphData.edge.filter(edge => ids.has(edge.source) && ids.has(edge.target)),
    frontier_id: state.graphData.frontier_id.filter(id => ids.has(id)),
  };
}

function activateTab(tabId) {
  document.querySelectorAll('.tab-bar button').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tabId);
  });
  document.querySelectorAll('.tab-content').forEach(content => {
    content.classList.toggle('active', content.id === tabId);
  });
  if (tabId === 'nodes-tab') {
    refreshNodes();
  }
}

function renderSearchResult(experiments, nodes) {
  if (experiments.length === 0 && nodes.length === 0) {
    searchResult.classList.remove('open');
    return;
  }

  const nodeHtml = nodes.length ? `
    <div class="search-section-title">Nodes</div>
    ${nodes.map(node => `
      <div class="search-item search-item-node" data-kind="node" data-node-id="${node.node_id}">
        ${renderAvatar(node.avatar_url, node.display_name || node.node_id, 'xs')}
        <div class="search-stack">
          <div class="search-main">
            <span>${escHtml(node.display_name || shortCid(node.node_id))}</span>
            ${renderActivityBadge(node.activity)}
          </div>
          <div class="search-sub">${escHtml(node.bio || shortCid(node.node_id))}</div>
        </div>
      </div>
    `).join('')}
  ` : '';

  const experimentHtml = experiments.length ? `
    <div class="search-section-title">Experiments</div>
    ${experiments.map(record => `
      <div class="search-item" data-kind="experiment" data-cid="${record.id}">
        <span class="status-badge ${record.status}">${record.status}</span>
        <span style="color:var(--cyan)">${shortCid(record.id)}</span>
        <span style="color:var(--text)">${record.val_bpb.toFixed(6)}</span>
        <span style="color:var(--text-dim)">${escHtml(record.node_display_name || shortCid(record.node_id))}</span>
        <span class="search-desc">${escHtml(record.description.slice(0, 60))}</span>
      </div>
    `).join('')}
  ` : '';

  searchResult.innerHTML = nodeHtml + experimentHtml;
  searchResult.classList.add('open');

  searchResult.querySelectorAll('.search-item').forEach(el => {
    el.addEventListener('click', () => {
      if (el.dataset.kind === 'node') {
        selectNode(el.dataset.nodeId);
      } else {
        selectExperiment(el.dataset.cid);
      }
      searchResult.classList.remove('open');
      searchInput.value = '';
    });
  });
}

async function refreshStat() {
  const stat = await getStat(taskParams());
  if (!state.selectedTaskId && stat.active_task_id) {
    state.selectedTaskId = stat.active_task_id;
  }
  document.getElementById('stat-total').textContent = stat.experiment_count;
  document.getElementById('stat-tasks').textContent = stat.task_count ?? '—';
  document.getElementById('stat-nodes').textContent = stat.node_count ?? '—';
  document.getElementById('stat-frontier').textContent = stat.frontier_size;
  document.getElementById('stat-best').textContent = stat.best_val_bpb != null ? stat.best_val_bpb.toFixed(6) : '—';
  document.getElementById('stat-peer').textContent = stat.peer_count;
  document.getElementById('hdr-node').textContent = shortCid(stat.node_id);
}

async function refreshFrontier() {
  const data = await getFrontier(taskParams());
  const tbody = document.querySelector('#frontier-table tbody');
  tbody.innerHTML = '';
  data.forEach(record => {
    const tr = document.createElement('tr');
    tr.className = 'clickable';
    tr.onclick = () => selectExperiment(record.id);
    tr.innerHTML = `
      <td style="color:var(--cyan)">${shortCid(record.id)}</td>
      <td style="color:var(--green)">${record.val_bpb.toFixed(6)}</td>
      <td>${record.depth}</td>
      <td>${escHtml(record.gpu_model || '—')}</td>
      <td>${record.num_steps}</td>
      <td>${formatParam(record.num_params)}</td>
      <td style="max-width:260px;overflow:hidden;text-overflow:ellipsis">${escHtml(record.description.slice(0, 90))}</td>
    `;
    tbody.appendChild(tr);
  });
}

function renderTaskSelect() {
  taskSelect.innerHTML = '';
  const auto = document.createElement('option');
  auto.value = '';
  auto.textContent = 'auto';
  taskSelect.appendChild(auto);
  state.tasks.forEach(task => {
    const option = document.createElement('option');
    option.value = task.task_id;
    option.textContent = `${task.name} (${shortCid(task.task_id)})`;
    taskSelect.appendChild(option);
  });
  taskSelect.value = state.selectedTaskId;
}

function renderStoryCard(event, compact = false) {
  const record = event.record;
  const metric = record?.val_bpb != null ? record.val_bpb.toFixed(6) : '—';
  const delta = formatSignedDelta(event.delta_bpb);
  return `
    <div class="story-card ${compact ? 'compact' : ''}">
      <div class="story-top">
        <span class="status-badge ${record?.status || 'keep'}">${escHtml(event.kind.replace('_', ' '))}</span>
        <span class="story-time">${timeAgo(event.timestamp)}</span>
      </div>
      <button class="story-headline" onclick="window.__select('${record?.id || ''}')">${escHtml(event.headline)}</button>
      <div class="story-summary">${escHtml(event.summary)}</div>
      <div class="story-meta">
        <button class="inline-link" onclick="window.__selectTask('${event.task_id}')">${escHtml(event.task_name)}</button>
        <span>${metric}</span>
        <span>${escHtml(delta)}</span>
        <button class="inline-link" onclick="window.__selectNode('${event.node_id}')">${escHtml(event.node_display_name)}</button>
      </div>
    </div>
  `;
}

function renderPulse(pulse) {
  const el = document.getElementById('pulse-metrics');
  const label = document.getElementById('pulse-window-label');
  label.textContent = `last ${formatDurationCompact(pulse.window_seconds)}`;
  el.innerHTML = `
    <div class="pulse-stat">
      <span class="label">Runs</span>
      <span class="value">${pulse.experiment_count_recent}</span>
    </div>
    <div class="pulse-stat">
      <span class="label">Compute</span>
      <span class="value">${formatDurationCompact(pulse.compute_seconds_recent)}</span>
    </div>
    <div class="pulse-stat">
      <span class="label">Keeps</span>
      <span class="value">${pulse.keep_count_recent}</span>
    </div>
    <div class="pulse-stat">
      <span class="label">Frontier moves</span>
      <span class="value">${pulse.frontier_move_count_recent}</span>
    </div>
    <div class="pulse-stat">
      <span class="label">Active nodes</span>
      <span class="value">${pulse.active_node_count_recent}</span>
    </div>
    <div class="pulse-stat">
      <span class="label">Tasks touched</span>
      <span class="value">${pulse.active_task_count_recent}</span>
    </div>
  `;
}

function renderHotTaskList(tasks) {
  const el = document.getElementById('hot-task-list');
  if (!tasks.length) {
    el.innerHTML = '<div class="empty-panel">No task momentum yet.</div>';
    return;
  }
  el.innerHTML = tasks.map(task => `
    <div class="story-card task-card">
      <div class="story-top">
        <span class="mini-pill frontier">${escHtml(task.task_type || 'task')}</span>
        <span class="story-time">${timeAgo(task.latest_activity)}</span>
      </div>
      <button class="story-headline" onclick="window.__selectTask('${task.task_id}')">${escHtml(task.name)}</button>
      <div class="story-summary">${escHtml(task.description || 'Task room')}</div>
      <div class="story-meta">
        <span>${task.recent_experiment_count} runs</span>
        <span>${task.recent_keep_count} keeps</span>
        <span>${task.participant_count} operators</span>
        <span>${task.best_val_bpb != null ? task.best_val_bpb.toFixed(6) : '—'}</span>
      </div>
    </div>
  `).join('');
}

function renderStoryFeed(events) {
  const targets = [
    document.getElementById('story-feed'),
    document.getElementById('activity-feed'),
  ];
  targets.forEach(target => {
    if (!target) return;
    if (!events.length) {
      target.innerHTML = '<div class="empty-panel">No recent stories yet.</div>';
      return;
    }
    target.innerHTML = events.map(event => renderStoryCard(event, target.id === 'activity-feed')).join('');
  });
}

async function refreshPulse() {
  const [pulse, stories, hot] = await Promise.all([
    getPulse(taskParams({ limit: 6 })),
    getFeed(taskParams({ limit: 10 })),
    getHotTasks({ limit: 6 }),
  ]);
  state.pulse = pulse;
  state.storyFeed = stories;
  state.hotTasks = pulse.hot_tasks?.length ? pulse.hot_tasks : hot;
  renderPulse(pulse);
  renderHotTaskList(state.hotTasks);
  renderStoryFeed(stories);
}

async function refreshTasks() {
  state.tasks = await getTasks();
  if (!state.selectedTaskId && state.tasks.length) {
    const active = state.tasks.find(task => task.is_active);
    state.selectedTaskId = (active || state.tasks[0]).task_id;
  }
  renderTaskSelect();
  const tbody = document.querySelector('#task-table tbody');
  tbody.innerHTML = '';
  state.tasks.forEach(task => {
    const tr = document.createElement('tr');
    tr.className = 'clickable';
    if (task.task_id === state.selectedTaskId) tr.classList.add('row-selected');
    tr.onclick = () => selectTask(task.task_id);
    tr.innerHTML = `
      <td>${escHtml(task.name)}<div class="muted-cid">${shortCid(task.task_id)}</div></td>
      <td>${escHtml(task.task_type || task.source)}</td>
      <td>${task.experiment_count}</td>
      <td>${task.frontier_size}</td>
      <td>${task.best_val_bpb != null ? task.best_val_bpb.toFixed(6) : '—'}</td>
      <td>${task.participant_count}</td>
      <td>${timeAgo(task.latest_activity)}</td>
    `;
    tbody.appendChild(tr);
  });
}

async function refreshNodes() {
  const params = taskParams({
    activity: state.nodeFilters.activity,
    status: state.nodeFilters.status,
    sort: state.nodeFilters.sort,
  });
  if (state.nodeFilters.has_profile !== 'all') {
    params.has_profile = state.nodeFilters.has_profile;
  }
  const data = await getNodes(params);
  const tbody = document.querySelector('#node-table tbody');
  tbody.innerHTML = '';

  if (data.length === 0) {
    const tr = document.createElement('tr');
    tr.innerHTML = '<td colspan="8" class="empty-row">No nodes match the current filters</td>';
    tbody.appendChild(tr);
    return;
  }

  data.forEach(node => {
    const tr = document.createElement('tr');
    tr.className = 'clickable';
    tr.onclick = () => selectNode(node.node_id);
    tr.innerHTML = `
      <td>${renderNodeName(node, { avatarSize: 'xs' })}</td>
      <td>${renderActivityBadge(node.activity)}</td>
      <td>${node.task_count}</td>
      <td>${node.experiment_count}</td>
      <td>${node.keep_count}</td>
      <td>${node.frontier_count}</td>
      <td title="${escHtml((node.gpu_models || []).join(', '))}">${escHtml((node.gpu_models || []).slice(0, 2).join(', ') || '—')}</td>
      <td>${timeAgo(node.last_seen)}</td>
    `;
    tbody.appendChild(tr);
  });
}

function renderNodeSummaryCard(node) {
  const identity = node.display_name || shortCid(node.node_id);
  const website = safeUrl(node.website);
  return `
    <div class="profile-card">
      <div class="profile-hero">
        ${renderAvatar(node.avatar_url, identity, 'lg')}
        <div class="profile-copy">
          <div class="profile-title-row">
            <h3>${escHtml(identity)}</h3>
            ${renderActivityBadge(node.activity)}
          </div>
          <div class="muted-cid">${node.node_id}</div>
          ${node.bio ? `<p class="profile-bio">${escHtml(node.bio)}</p>` : ''}
          <div class="profile-links">
            ${website ? `<a href="${website}" target="_blank" rel="noreferrer">website</a>` : ''}
            ${node.donation_address ? `<span>donation ${escHtml(node.donation_address)}</span>` : ''}
          </div>
        </div>
      </div>
      <div class="stat-grid">
        <div class="stat-card"><span class="label">Tasks</span><span class="value">${node.task_count}</span></div>
        <div class="stat-card"><span class="label">Experiments</span><span class="value">${node.experiment_count}</span></div>
        <div class="stat-card"><span class="label">Keep</span><span class="value">${node.keep_count}</span></div>
        <div class="stat-card"><span class="label">Frontier</span><span class="value">${node.frontier_count}</span></div>
        <div class="stat-card"><span class="label">Verified</span><span class="value">${node.verified_count}</span></div>
        <div class="stat-card"><span class="label">Last seen</span><span class="value">${timeAgo(node.last_seen)}</span></div>
      </div>
    </div>
  `;
}

function renderExperimentCard(record) {
  return `
    <div class="record-card clickable" onclick="window.__select('${record.id}')">
      <div class="record-card-top">
        <div>
          <span class="status-badge ${record.status}">${record.status}</span>
          ${renderFlagPills(record)}
        </div>
        <div class="muted-cid">${shortCid(record.id)}</div>
      </div>
      <div class="record-card-body">
        <div class="record-main-metric">${record.val_bpb.toFixed(6)}</div>
        <div class="record-meta">${escHtml(record.gpu_model || '—')} · ${record.num_steps} steps · ${timeAgo(record.timestamp)}</div>
        <div class="record-desc">${escHtml(record.description)}</div>
      </div>
    </div>
  `;
}

function bindNodeDetailControls(nodeId) {
  detailContent.querySelectorAll('[data-node-status]').forEach(btn => {
    btn.addEventListener('click', () => {
      state.nodeDetailFilters.status = btn.dataset.nodeStatus;
      selectNode(nodeId);
    });
  });

  const verifiedToggle = detailContent.querySelector('#node-verified-toggle');
  const frontierToggle = detailContent.querySelector('#node-frontier-toggle');
  if (verifiedToggle) {
    verifiedToggle.addEventListener('change', () => {
      state.nodeDetailFilters.verified_only = verifiedToggle.checked;
      selectNode(nodeId);
    });
  }
  if (frontierToggle) {
    frontierToggle.addEventListener('change', () => {
      state.nodeDetailFilters.frontier_only = frontierToggle.checked;
      selectNode(nodeId);
    });
  }
}

async function selectTask(taskId) {
  state.selectedTaskId = taskId || '';
  state.selectedTaskDetailId = taskId || '';
  state.selectedExperimentId = null;
  state.selectedNodeId = null;
  state.detailMode = taskId ? 'task' : 'empty';
  renderTaskSelect();
  updateUrlState();

  if (!taskId) {
    clearDetail();
    await refreshAll();
    return;
  }

  const [task, feed] = await Promise.all([
    getTask(taskId),
    getTaskFeed(taskId, { limit: 12 }),
  ]);
  if (task.error) {
    clearDetail();
    return;
  }

  setDetailHeader('Task', `${task.name} · ${shortCid(task.task_id)}`);
  const frontierCards = task.frontier?.length
    ? task.frontier.slice(0, 4).map(renderExperimentCard).join('')
    : '<div class="empty-panel">No frontier experiments yet.</div>';
  const recentStories = feed.length
    ? feed.slice(0, 6).map(event => renderStoryCard(event, true)).join('')
    : '<div class="empty-panel">No recent task activity yet.</div>';

  showDetail(`
    <div class="profile-card">
      <div class="profile-title-row">
        <h3>${escHtml(task.name)}</h3>
        <span class="activity-badge hybrid">${escHtml(task.task_type || 'task')}</span>
      </div>
      <p class="profile-bio">${escHtml(task.description || 'Independent research objective')}</p>
      <div class="profile-links">
        <span>${escHtml(task.metric || 'val_bpb')} · ${escHtml(task.goal || 'minimize')}</span>
        <span>${task.participant_count} operators</span>
        <span>${task.experiment_count} experiments</span>
      </div>
      ${renderShareActions(buildSharePath({ task: task.task_id }), 'copy task link')}
    </div>

    <div class="detail-section">
      <div class="hero-stat-row">
        <div class="stat-card"><span class="label">Best</span><span class="value">${task.best_val_bpb != null ? task.best_val_bpb.toFixed(6) : '—'}</span></div>
        <div class="stat-card"><span class="label">Frontier</span><span class="value">${task.frontier_size}</span></div>
        <div class="stat-card"><span class="label">Updated</span><span class="value">${timeAgo(task.latest_activity)}</span></div>
      </div>
    </div>

    <div class="detail-section">
      <div class="detail-field">
        <label>Mission</label>
        <div class="value">${escHtml(task.description || '—')}</div>
      </div>
      <div class="detail-field">
        <label>Join locally</label>
        <div class="value">spore daemon --task ${escHtml(task.task_id)}</div>
      </div>
      <div class="detail-field">
        <label>Participants</label>
        <div class="value">${task.participants?.length ? escHtml(task.participants.map(shortCid).join(', ')) : '—'}</div>
      </div>
    </div>

    <div class="detail-section">
      <label>Current frontier</label>
      <div class="record-list">${frontierCards}</div>
    </div>

    <div class="detail-section">
      <label>Live task room</label>
      <div class="record-list">${recentStories}</div>
    </div>
  `);

  await refreshAll();
}

async function selectNode(nodeId) {
  state.selectedNodeId = nodeId;
  state.selectedExperimentId = null;
  state.selectedTaskDetailId = null;
  state.detailMode = 'node';
  updateUrlState();

  const payload = await getNodeDetail(nodeId, taskParams(state.nodeDetailFilters));
  if (payload.error) return;

  const node = payload.node;
  setDetailHeader('Node', `${node.display_name || shortCid(node.node_id)} · ${shortCid(node.node_id)}`);

  const best = node.best_experiment ? `
    <div class="detail-field">
      <label>Best experiment</label>
      ${renderExperimentCard(node.best_experiment)}
    </div>
  ` : '';

  const latest = node.latest_experiment ? `
    <div class="detail-field">
      <label>Latest experiment</label>
      ${renderExperimentCard(node.latest_experiment)}
    </div>
  ` : '';

  const experiments = payload.experiments
    .slice()
    .sort((a, b) => (b.timestamp - a.timestamp) || (b.depth - a.depth) || b.id.localeCompare(a.id));

  const experimentCards = experiments.length ? experiments.map(renderExperimentCard).join('') : `
    <div class="empty-panel">No experiments match the current node filters.</div>
  `;

  showDetail(`
    ${renderNodeSummaryCard(node)}
    ${renderShareActions(buildSharePath({ task: state.selectedTaskId, node: node.node_id }), 'copy node link')}
    <div class="detail-section">
      <div class="detail-field">
        <label>Hardware</label>
        <div class="value">${escHtml((node.gpu_models || []).join(', ') || '—')}</div>
      </div>
      <div class="detail-field">
        <label>Agents</label>
        <div class="value">${escHtml((node.agent_models || []).join(', ') || '—')}</div>
      </div>
      <div class="detail-field">
        <label>Window</label>
        <div class="value">${formatDateTime(node.first_seen)} to ${formatDateTime(node.last_seen)}</div>
      </div>
      <div class="detail-field">
        <label>Contribution</label>
        <div class="value">${node.experiment_count} experiments · ${node.verified_count} verified · ${node.frontier_count} frontier</div>
      </div>
      ${best}
      ${latest}
    </div>

    <div class="detail-section">
      <div class="section-row">
        <label>Experiments (${payload.total_experiments})</label>
        <div class="pill-group">
          <button class="mini-filter ${state.nodeDetailFilters.status === 'all' ? 'active' : ''}" data-node-status="all">all</button>
          <button class="mini-filter ${state.nodeDetailFilters.status === 'keep' ? 'active' : ''}" data-node-status="keep">keep</button>
          <button class="mini-filter ${state.nodeDetailFilters.status === 'discard' ? 'active' : ''}" data-node-status="discard">discard</button>
          <button class="mini-filter ${state.nodeDetailFilters.status === 'crash' ? 'active' : ''}" data-node-status="crash">crash</button>
        </div>
      </div>
      <div class="toggle-row">
        <label><input type="checkbox" id="node-verified-toggle" ${state.nodeDetailFilters.verified_only ? 'checked' : ''}> verified only</label>
        <label><input type="checkbox" id="node-frontier-toggle" ${state.nodeDetailFilters.frontier_only ? 'checked' : ''}> frontier only</label>
      </div>
      <div class="record-list">${experimentCards}</div>
    </div>
  `);

  bindNodeDetailControls(nodeId);
  resetHighlight();
}

function buildDiffHtml(diff) {
  if (!diff) return '';
  return diff.split('\n').map(line => {
    if (line.startsWith('@@')) return `<span class="hunk">${escHtml(line)}</span>`;
    if (line.startsWith('+')) return `<span class="add">${escHtml(line)}</span>`;
    if (line.startsWith('-')) return `<span class="del">${escHtml(line)}</span>`;
    return escHtml(line);
  }).join('\n');
}

async function loadCode(codeCid) {
  const el = document.getElementById('code-section');
  if (!el || !codeCid) return;
  el.innerHTML = `
    <div class="detail-section">
      <label class="detail-section-title" id="code-toggle">Code Snapshot ▸</label>
      <div id="code-content" style="display:none"></div>
    </div>
  `;
  document.getElementById('code-toggle').addEventListener('click', async () => {
    const contentEl = document.getElementById('code-content');
    if (contentEl.style.display === 'none') {
      document.getElementById('code-toggle').textContent = 'Code Snapshot ▾';
      const artifact = await getArtifact(codeCid);
      contentEl.innerHTML = artifact.error
        ? '<div class="empty-panel">Artifact not available</div>'
        : `<div class="code-block">${escHtml(artifact.content)}</div>`;
      contentEl.style.display = 'block';
    } else {
      contentEl.style.display = 'none';
      document.getElementById('code-toggle').textContent = 'Code Snapshot ▸';
    }
  });
}

async function selectExperiment(cid) {
  state.selectedExperimentId = cid;
  state.selectedNodeId = null;
  state.selectedTaskDetailId = null;
  state.detailMode = 'experiment';

  const record = await getExperiment(cid);
  if (record.error) return;
  state.selectedTaskId = record.task_id || state.selectedTaskId;
  renderTaskSelect();
  updateUrlState();

  const [ancestors, children, nodePayload, taskPayload] = await Promise.all([
    getAncestor(cid),
    getChildren(cid),
    getNodeDetail(record.node_id, taskParams()),
    getTask(record.task_id),
  ]);

  let deltaHtml = '';
  if (record.parent) {
    const parent = await getExperiment(record.parent);
    if (!parent.error) {
      const delta = record.val_bpb - parent.val_bpb;
      const sign = delta <= 0 ? '' : '+';
      const cls = delta <= 0 ? 'keep' : 'discard';
      deltaHtml = `<span class="value ${cls}" style="font-size:13px">(${sign}${delta.toFixed(6)})</span>`;
    }
  }

  const node = nodePayload.node || {
    node_id: record.node_id,
    display_name: record.node_display_name || '',
    avatar_url: record.node_avatar_url || '',
    bio: '',
    website: '',
    donation_address: '',
    activity: 'observer',
    reputation: { score: 0, experiments_published: 0, experiments_verified: 0, verifications_performed: 0 },
    experiment_count: 0,
    keep_count: 0,
    frontier_count: 0,
  };

  const lineageHtml = ancestors.length > 1 ? `
    <div class="ancestor-chain">
      <label>Lineage</label>
      ${ancestors.map((ancestor, index) => `
        ${index > 0 ? '<div class="ancestor-item"><span class="line"></span></div>' : ''}
        <div class="ancestor-item ${ancestor.id === cid ? 'current' : ''}" onclick="window.__select('${ancestor.id}')">
          <span class="dot" style="background:${statusColor(ancestor.status)}"></span>
          <span style="color:var(--cyan)">${shortCid(ancestor.id)}</span>
          <span>${ancestor.val_bpb.toFixed(6)}</span>
          <span class="ancestor-desc">${escHtml(ancestor.description.slice(0, 44))}</span>
        </div>
      `).join('')}
    </div>
  ` : '';

  const childrenHtml = children.length ? `
    <div class="detail-field">
      <label>Children (${children.length})</label>
      <div class="record-list compact-list">${children.map(renderExperimentCard).join('')}</div>
    </div>
  ` : '';

  const website = safeUrl(node.website);
  setDetailHeader('Experiment', `${record.description.slice(0, 48) || shortCid(record.id)}`);
  showDetail(`
    <div class="detail-section">
      <div class="hero-stat-row">
        <div class="detail-field">
          <label>CID <button class="copy-btn" onclick="navigator.clipboard.writeText('${record.id}')">copy</button></label>
          <div class="value cid" style="font-size:10px;word-break:break-all">${record.id}</div>
        </div>
        <div class="detail-field">
          <label>Status</label>
          <div>${renderFlagPills(record)} <span class="status-badge ${record.status}">${record.status}</span></div>
        </div>
        <div class="detail-field">
          <label>val_bpb</label>
          <div class="value bpb ${record.status}">${record.val_bpb.toFixed(6)}</div>
          ${deltaHtml}
        </div>
      </div>
    </div>

    <div class="profile-card compact">
      <div class="profile-hero">
        ${renderAvatar(node.avatar_url, node.display_name || node.node_id, 'md')}
        <div class="profile-copy">
          <div class="profile-title-row">
            <h3>${escHtml(node.display_name || shortCid(node.node_id))}</h3>
            ${renderActivityBadge(node.activity)}
          </div>
          <div class="muted-cid" onclick="window.__selectNode('${node.node_id}')">${node.node_id}</div>
          ${node.bio ? `<p class="profile-bio">${escHtml(node.bio)}</p>` : ''}
          <div class="profile-links">
            ${website ? `<a href="${website}" target="_blank" rel="noreferrer">website</a>` : ''}
            ${node.donation_address ? `<span>donation ${escHtml(node.donation_address)}</span>` : ''}
          </div>
          <div class="profile-links">
            <button class="inline-link" onclick="window.__selectNode('${node.node_id}')">open node</button>
            <span>${shortCid(record.task_id)} task</span>
            <span>${node.experiment_count} experiments</span>
          </div>
        </div>
      </div>
      ${renderShareActions(buildSharePath({ task: record.task_id, experiment: record.id }), 'copy experiment link')}
    </div>

    <div class="detail-section">
      <div class="detail-field">
        <label>Description</label>
        <div class="value">${escHtml(record.description)}</div>
      </div>
      ${record.hypothesis && record.hypothesis !== '—' ? `<div class="detail-field"><label>Hypothesis</label><div class="value">${escHtml(record.hypothesis)}</div></div>` : ''}
    </div>

    <div class="detail-section">
      <div class="detail-field">
        <label>Parent</label>
        <div class="value cid" onclick="window.__select('${record.parent || ''}')">${record.parent ? shortCid(record.parent) : 'genesis'}</div>
      </div>
      <div class="detail-field">
        <label>Task</label>
        <div class="value">${escHtml(taskPayload?.name || shortCid(record.task_id))}</div>
      </div>
      <div class="detail-field">
        <label>Hardware</label>
        <div class="value">${escHtml(record.gpu_model || '—')} · ${record.peak_vram_mb.toFixed(0)} MB</div>
      </div>
      <div class="detail-field">
        <label>Training</label>
        <div class="value">${record.num_steps} steps · ${formatParam(record.num_params)} params · ${record.time_budget}s budget</div>
      </div>
      <div class="detail-field">
        <label>Agent</label>
        <div class="value">${escHtml(record.agent_model || '—')}</div>
      </div>
      <div class="detail-field">
        <label>Time</label>
        <div class="value">${formatDateTime(record.timestamp)}</div>
      </div>
      ${childrenHtml}
    </div>

    ${record.diff ? `<div class="detail-section"><label>Diff</label><div class="diff-block">${buildDiffHtml(record.diff)}</div></div>` : ''}
    <div id="code-section"></div>
    ${lineageHtml}
  `);

  loadCode(record.code_cid);
  updateSelection(cid, ancestors.map(item => item.id));
}

function connectWs() {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${proto}//${window.location.host}/ws`);

  ws.onopen = () => {
    document.getElementById('ws-dot').classList.add('connected');
  };

  ws.onclose = () => {
    document.getElementById('ws-dot').classList.remove('connected');
    setTimeout(connectWs, 2000);
  };

  ws.onmessage = async event => {
    const msg = JSON.parse(event.data);
    if (msg.event !== 'experiment') return;

    const record = msg.data;
    if (state.selectedTaskId && record.task_id !== state.selectedTaskId) {
      return;
    }
    const existing = state.graphData.node.find(node => node.id === record.id);
    if (!existing) {
      state.graphData.node.push(record);
      if (record.parent) {
        state.graphData.edge.push({ source: record.parent, target: record.id });
      }
    }

    const frontier = await getFrontier(taskParams());
    state.graphData.frontier_id = frontier.map(item => item.id);
    renderDag(getFilteredGraph(), state.selectedExperimentId);

    await Promise.all([refreshStat(), refreshFrontier(), refreshTasks(), refreshPulse()]);
    if (document.getElementById('nodes-tab').classList.contains('active') || state.detailMode === 'node') {
      await refreshNodes();
    }
    if (state.detailMode === 'node' && state.selectedNodeId === record.node_id) {
      await selectNode(state.selectedNodeId);
    }
    if (state.detailMode === 'task' && state.selectedTaskDetailId === record.task_id) {
      await selectTask(state.selectedTaskDetailId);
    }
  };
}

function bindEvents() {
  document.querySelectorAll('.tab-bar button').forEach(btn => {
    btn.addEventListener('click', () => activateTab(btn.dataset.tab));
  });

  searchInput.addEventListener('input', () => {
    clearTimeout(state.searchTimeout);
    const query = searchInput.value.trim();
    if (query.length < 2) {
      searchResult.classList.remove('open');
      return;
    }
    state.searchTimeout = setTimeout(async () => {
      const [experiments, nodes] = await Promise.all([
        searchExperiment(query, taskParams()),
        searchNodes(query, taskParams()),
      ]);
      renderSearchResult(experiments, nodes);
    }, 180);
  });

  searchInput.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      searchResult.classList.remove('open');
      searchInput.blur();
    }
  });

  document.addEventListener('click', e => {
    if (!e.target.closest('.search-wrap')) {
      searchResult.classList.remove('open');
    }
  });

  document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.filter-btn').forEach(other => other.classList.remove('active'));
      btn.classList.add('active');
      state.statusFilter = btn.dataset.filter;
      renderDag(getFilteredGraph(), state.selectedExperimentId);
    });
  });

  Object.entries(nodeFilterEls).forEach(([key, el]) => {
    el.addEventListener('change', () => {
      state.nodeFilters[key] = el.value;
      refreshNodes();
    });
  });

  taskSelect.addEventListener('change', () => {
    selectTask(taskSelect.value);
  });

  document.addEventListener('keydown', e => {
    if (e.key === '/' && !e.ctrlKey && !e.metaKey && document.activeElement !== searchInput) {
      e.preventDefault();
      searchInput.focus();
    }
    if (e.key === 'Escape' && state.detailMode !== 'empty') {
      clearDetail();
      renderDag(getFilteredGraph(), null);
    }
  });
}

async function applyUrlState() {
  const params = new URLSearchParams(window.location.search);
  const taskId = params.get('task') || '';
  const experimentId = params.get('experiment');
  const nodeId = params.get('node');

  if (taskId) {
    state.selectedTaskId = taskId;
    renderTaskSelect();
  }

  if (experimentId) {
    await selectExperiment(experimentId);
    return;
  }
  if (nodeId) {
    await selectNode(nodeId);
    return;
  }
  if (taskId) {
    await selectTask(taskId);
  }
}

window.__select = cid => {
  if (cid) selectExperiment(cid);
};

window.__selectNode = nodeId => {
  if (nodeId) selectNode(nodeId);
};

window.__selectTask = taskId => {
  if (taskId !== undefined) selectTask(taskId);
};

window.__copyLink = url => {
  if (url) copyText(url);
};

async function init() {
  bindEvents();
  initDag(document.getElementById('dag-panel'), selectExperiment);

  await refreshTasks();
  const [graphData] = await Promise.all([
    getGraph(taskParams()),
    refreshStat(),
    refreshFrontier(),
    refreshNodes(),
    refreshPulse(),
  ]);

  state.graphData = graphData;
  renderDag(getFilteredGraph(), null);
  await applyUrlState();
  connectWs();

  window.setInterval(() => {
    refreshAll();
  }, 10000);
}

async function refreshAll() {
  await Promise.all([refreshTasks(), refreshStat(), refreshFrontier(), refreshNodes(), refreshPulse()]);
  state.graphData = await getGraph(taskParams());
  renderDag(getFilteredGraph(), state.selectedExperimentId);
  updateUrlState();
}

init();
