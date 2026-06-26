/**
 * MusicDL Web - Frontend Application
 * @version:  1.0.0
 * @requires: ES2020+ (Optional Chaining, Nullish Coalescing, async/await)
 * @author:   Architect
 *
 * Complexity Analysis (core operations):
 *   - Search debounce:  O(1) timer management
 *   - Song filter:      O(n) single-pass over results
 *   - Song selection:   O(1) Set lookup
 *   - IndexedDB CRUD:   O(log n) indexed lookup
 *   - SSE event dispatch: O(1) per event
 */

'use strict';

// ═══════════════════════════════════════════════════════════
// 0. IndexedDB Storage (History + Theme Prefs)
// ═══════════════════════════════════════════════════════════
const DB_NAME    = 'musicdl_db';
const DB_VERSION = 1;

/** @returns {Promise<IDBDatabase>} */
function openDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = (e) => {
      const db = /** @type {IDBDatabase} */ (e.target.result);
      if (!db.objectStoreNames.contains('history')) {
        db.createObjectStore('history', { keyPath: 'id', autoIncrement: true });
      }
      if (!db.objectStoreNames.contains('settings')) {
        db.createObjectStore('settings', { keyPath: 'key' });
      }
    };
    req.onsuccess = (e) => resolve(/** @type {IDBDatabase} */ (e.target.result));
    req.onerror   = (e) => reject(/** @type {Error} */ (e.target.error));
    req.onblocked = () => reject(new Error('DB blocked'));
  });
}

// ─── History CRUD ───
/** @param {string} keyword */
async function addHistory(keyword) {
  if (!keyword?.trim()) return;
  const db = await openDB();
  const tx = db.transaction('history', 'readwrite');
  const store = tx.objectStore('history');
  // Dedup: remove existing same keyword
  const all = await new Promise((res) => {
    const r = store.getAll();
    r.onsuccess = () => res(/** @type {Array} */ (r.result));
    r.onerror   = () => res([]);
  });
  for (const item of all) {
    if (item.keyword === keyword) store.delete(item.id);
  }
  store.add({ keyword, timestamp: Date.now() });
}

/** @returns {Promise<Array<{id:number, keyword:string, timestamp:number}>>} */
async function getHistory(limit = 20) {
  const db = await openDB();
  const tx = db.transaction('history', 'readonly');
  const store = tx.objectStore('history');
  return new Promise((res) => {
    const r = store.getAll();
    r.onsuccess = () => {
      const data = /** @type {Array} */ (r.result);
      data.sort((a, b) => b.timestamp - a.timestamp);
      res(data.slice(0, limit));
    };
    r.onerror = () => res([]);
  });
}

async function clearHistory() {
  const db = await openDB();
  const tx = db.transaction('history', 'readwrite');
  tx.objectStore('history').clear();
}

// ─── Theme Settings ───
async function getThemePreference() {
  try {
    const db = await openDB();
    const tx = db.transaction('settings', 'readonly');
    const store = tx.objectStore('settings');
    return new Promise((res) => {
      const r = store.get('theme');
      r.onsuccess = () => res(r.result?.value ?? null);
      r.onerror   = () => res(null);
    });
  } catch { return null; }
}

async function setThemePreference(theme) {
  try {
    const db = await openDB();
    const tx = db.transaction('settings', 'readwrite');
    tx.objectStore('settings').put({ key: 'theme', value: theme });
  } catch { /* offline - fine */ }
}

// ═══════════════════════════════════════════════════════════
// 1. State Management
// ═══════════════════════════════════════════════════════════
const STATE = {
  sessionId: crypto.randomUUID?.() || Date.now().toString(36) + Math.random().toString(36).slice(2, 8),
  theme: 'dark',
  sources: /** @type {string[]} */ ([]),
  allSources: /** @type {Record<string, string[]>} */ ({}),
  searchResults: /** @type {Array} */ ([]),
  selectedIds: /** @type {Set<number>} */ (new Set()),
  isSearching: false,
  es: /** @type {EventSource|null} */ (null),
};

// ═══════════════════════════════════════════════════════════
// 2. DOM References
// ═══════════════════════════════════════════════════════════
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const DOM = {
  themeToggle:         $('#theme-toggle'),
  searchInput:         $('#search-input'),
  searchBtn:           $('#search-btn'),
  clearSearchBtn:      $('#clear-search-btn'),
  playlistInput:       $('#playlist-input'),
  parsePlaylistBtn:    $('#parse-playlist-btn'),
  sourceGrid:          $('#source-grid'),
  sourceCount:         $('#source-count'),
  sourceDetails:       $('#source-details'),
  selectAllSourcesBtn: $('#select-all-sources-btn'),
  deselectAllSourcesBtn: $('#deselect-all-sources-btn'),
  searchStatus:        $('#search-status'),
  resultsPanel:        $('#results-panel'),
  resultCount:         $('#result-count'),
  filterTabs:          $('#filter-tabs'),
  songList:            $('#song-list'),
  resultsEmpty:        $('#results-empty'),
  selectAllBtn:        $('#select-all-btn'),
  deselectAllBtn:      $('#deselect-all-btn'),
  downloadSelBtn:      $('#download-selected-btn'),
  progressBar:         $('#progress-bar'),
  progressFill:        $('#progress-fill'),
  progressText:        $('#progress-text'),
  downloadLog:         $('#download-log'),
  historyList:         $('#history-list'),
  clearHistoryBtn:     $('#clear-history-btn'),
  toastContainer:      $('#toast-container'),
};

// ═══════════════════════════════════════════════════════════
// 3. Toast Notifications
// ═══════════════════════════════════════════════════════════
/**
 * @param {'success'|'error'|'info'} type
 * @param {string} message
 * @param {number} [duration=3500]
 */
function showToast(type, message, duration = 3500) {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.setAttribute('role', 'alert');
  el.innerHTML = `<span>${message}</span>`;
  DOM.toastContainer.appendChild(el);

  setTimeout(() => {
    el.classList.add('removing');
    el.addEventListener('animationend', () => el.remove());
  }, duration);
}

// ═══════════════════════════════════════════════════════════
// 4. Theme Management
// ═══════════════════════════════════════════════════════════
function applyTheme(theme) {
  STATE.theme = theme;
  document.documentElement.setAttribute('data-theme', theme);
  DOM.themeToggle.setAttribute('aria-label', theme === 'dark' ? '切换到亮色主题' : '切换到暗色主题');
  setThemePreference(theme);
}

function toggleTheme() {
  applyTheme(STATE.theme === 'dark' ? 'light' : 'dark');
}

// ═══════════════════════════════════════════════════════════
// 5. Source Management
// ═══════════════════════════════════════════════════════════
async function fetchSources() {
  try {
    const resp = await fetch('/api/sources');
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    /** @type {Record<string, string[]>} */
    const data = await resp.json();
    STATE.allSources = data;
    // Flatten all source IDs
    STATE.sources = Object.values(data).flat();
    renderSourceChips();
  } catch (err) {
    console.error('Failed to fetch sources:', err);
    showToast('error', '无法获取音源列表，请检查服务是否启动');
  }
}

function renderSourceChips() {
  DOM.sourceGrid.innerHTML = '';

  const categoryLabels = {
    huawei: '🇨🇳 大中华区',
    global: '🌍 全球流媒体',
    audio: '📻 音频电台',
    aggregator: '🔗 聚合搜索',
    scraper: '🌐 第三方源',
  };

  for (const [cat, sources] of Object.entries(STATE.allSources)) {
    if (!sources.length) continue;
    const label = document.createElement('div');
    label.className = 'source-category-label';
    label.style.cssText = 'grid-column:1/-1;font-size:0.7rem;font-weight:700;color:var(--color-text-muted);text-transform:uppercase;letter-spacing:0.05em;padding:4px 0 0;';
    label.textContent = categoryLabels[cat] || cat;
    DOM.sourceGrid.appendChild(label);

    for (const src of sources) {
      const chip = document.createElement('div');
      chip.className = `source-chip ${STATE.sources.includes(src) ? 'selected' : ''}`;
      chip.textContent = src.replace('MusicClient', '');
      chip.setAttribute('role', 'checkbox');
      chip.setAttribute('aria-checked', STATE.sources.includes(src) ? 'true' : 'false');
      chip.setAttribute('tabindex', '0');
      chip.dataset.source = src;
      chip.addEventListener('click', () => toggleSource(src, chip));
      chip.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleSource(src, chip); }
      });
      DOM.sourceGrid.appendChild(chip);
    }
  }
  updateSourceCount();
}

/**
 * Toggle a single source on/off
 * O(1) array splice
 */
function toggleSource(sourceId, chipEl) {
  const idx = STATE.sources.indexOf(sourceId);
  if (idx === -1) {
    STATE.sources.push(sourceId);
    chipEl.classList.add('selected');
    chipEl.setAttribute('aria-checked', 'true');
  } else {
    // Enforce minimum 1 source
    if (STATE.sources.length <= 1) {
      showToast('info', '至少保留一个音源');
      return;
    }
    STATE.sources.splice(idx, 1);
    chipEl.classList.remove('selected');
    chipEl.setAttribute('aria-checked', 'false');
  }
  updateSourceCount();
}

function updateSourceCount() {
  const count = STATE.sources.length;
  DOM.sourceCount.textContent = `(已选 ${count})`;
  DOM.sourceCount.style.color = count > 0 ? 'var(--color-primary)' : 'var(--color-error)';
}

function selectAllSources() {
  STATE.sources = Object.values(STATE.allSources).flat();
  renderSourceChips();
}

function deselectAllSources() {
  // Keep first source as minimum
  const allFlat = Object.values(STATE.allSources).flat();
  STATE.sources = allFlat.length > 0 ? [allFlat[0]] : [];
  renderSourceChips();
}

// ═══════════════════════════════════════════════════════════
// 6. Search
// ═══════════════════════════════════════════════════════════
/**
 * Debounced search trigger
 * O(1) timer management
 */
let searchDebounceTimer = null;
function onSearchInput() {
  clearTimeout(searchDebounceTimer);
  searchDebounceTimer = setTimeout(() => {
    if (DOM.searchInput.value.trim().length >= 2) {
      performSearch();
    }
  }, 400);
}

async function performSearch() {
  const keyword = DOM.searchInput.value.trim();
  if (!keyword) {
    showToast('info', '请输入搜索关键词');
    return;
  }
  if (STATE.isSearching) return;

  STATE.isSearching = true;
  DOM.searchBtn.disabled = true;
  DOM.searchStatus.innerHTML = '<span class="spinner"></span> 正在搜索...';
  DOM.searchStatus.className = 'status-bar loading';
  DOM.resultsPanel.style.display = '';
  DOM.resultsEmpty.style.display = 'none';

  try {
    const resp = await fetch('/api/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        keyword,
        sources: STATE.sources,
        session_id: STATE.sessionId,
      }),
    });

    if (!resp.ok) {
      const errData = await resp.json().catch(() => ({}));
      throw new Error(errData.error || `搜索失败 (HTTP ${resp.status})`);
    }

    const data = await resp.json();
    STATE.searchResults = data.songs.map((s, i) => ({ ...s, _idx: i }));
    STATE.selectedIds.clear();

    renderResults();
    renderFilterTabs();
    addHistory(keyword);
    renderHistory();

    DOM.searchStatus.textContent = `✅ 找到 ${data.total} 首歌曲`;
    DOM.searchStatus.className = 'status-bar success';
  } catch (err) {
    DOM.searchStatus.textContent = `❌ ${err.message}`;
    DOM.searchStatus.className = 'status-bar error';
    showToast('error', err.message);
  } finally {
    STATE.isSearching = false;
    DOM.searchBtn.disabled = false;
  }
}

// ═══════════════════════════════════════════════════════════
// 7. Results Rendering
// ═══════════════════════════════════════════════════════════
let currentFilter = 'all';

function renderFilterTabs() {
  // Collect unique sources from results
  const sourceSet = new Set(STATE.searchResults.map(s => s.source).filter(Boolean));
  const sources = ['all', ...Array.from(sourceSet).sort()];

  DOM.filterTabs.innerHTML = sources.map(src => {
    const label = src === 'all' ? '全部' : src.replace('MusicClient', '');
    const active = src === currentFilter ? ' active' : '';
    return `<button class="filter-tab${active}" role="tab" data-filter="${src}" aria-selected="${src === currentFilter}">${label}</button>`;
  }).join('');

  // Bind events
  DOM.filterTabs.querySelectorAll('.filter-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      currentFilter = tab.dataset.filter;
      renderFilterTabs();
      renderResults();
    });
  });
}

function renderResults() {
  let filtered = STATE.searchResults;
  if (currentFilter !== 'all') {
    filtered = filtered.filter(s => s.source === currentFilter);
  }

  DOM.resultCount.textContent = `(${filtered.length} 首)`;
  DOM.songList.innerHTML = '';

  if (filtered.length === 0) {
    DOM.resultsEmpty.style.display = '';
    DOM.songList.style.display = 'none';
    return;
  }
  DOM.resultsEmpty.style.display = 'none';
  DOM.songList.style.display = '';

  // Use DocumentFragment for O(n) single DOM insertion
  const frag = document.createDocumentFragment();

  for (const song of filtered) {
    const row = document.createElement('div');
    row.className = `song-row${STATE.selectedIds.has(song._idx) ? ' selected' : ''}`;
    row.setAttribute('role', 'listitem');
    row.setAttribute('tabindex', '0');
    row.dataset.idx = song._idx;

    const metaBadges = [];
    if (song.ext) {
      const extLower = song.ext.toLowerCase();
      if (['flac', 'wav', 'alac', 'ape'].includes(extLower)) {
        metaBadges.push(`<span class="song-badge flac">${song.ext.toUpperCase()}</span>`);
      } else {
        metaBadges.push(`<span class="song-badge">${song.ext.toUpperCase()}</span>`);
      }
    }
    if (song.bitrate) {
      metaBadges.push(`<span class="song-badge hq">${Math.round(song.bitrate/1000)}kbps</span>`);
    }

    row.innerHTML = `
      <div class="check-circle" aria-hidden="true">${STATE.selectedIds.has(song._idx) ? '✓' : ''}</div>
      <div class="song-cover">
        ${song.cover_url
          ? `<img src="${escapeHTML(song.cover_url)}" alt="" loading="lazy" onerror="this.parentElement.innerHTML='<span class=\\'song-cover-fallback\\'>🎵</span>'">`
          : '<span class="song-cover-fallback">🎵</span>'}
      </div>
      <div class="song-info">
        <div class="song-name" title="${escapeHTML(song.song_name || '未知')}">${escapeHTML(song.song_name || '未知歌曲')}</div>
        <div class="song-meta">
          <span>${escapeHTML(song.singers || '未知歌手')}</span>
          ${metaBadges.join('')}
          <span>${escapeHTML(song.source || '').replace('MusicClient', '')}</span>
        </div>
      </div>
      <div class="song-duration">${escapeHTML(song.duration || '')} · ${escapeHTML(song.file_size || '')}</div>
    `;

    row.addEventListener('click', (e) => {
      // Don't toggle if clicking on cover image (prevent conflict)
      toggleSongSelection(song._idx, row);
    });
    row.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        toggleSongSelection(song._idx, row);
      }
    });

    frag.appendChild(row);
  }

  DOM.songList.appendChild(frag);

  // Update aria attributes
  DOM.resultCount.setAttribute('aria-label', `共 ${filtered.length} 首歌曲`);
}

function toggleSongSelection(idx, rowEl) {
  if (STATE.selectedIds.has(idx)) {
    STATE.selectedIds.delete(idx);
    rowEl?.classList.remove('selected');
    if (rowEl) rowEl.querySelector('.check-circle').textContent = '';
  } else {
    STATE.selectedIds.add(idx);
    rowEl?.classList.add('selected');
    if (rowEl) rowEl.querySelector('.check-circle').textContent = '✓';
  }
  updateDownloadBtn();
}

function selectAll() {
  const filtered = getFilteredSongs();
  for (const s of filtered) STATE.selectedIds.add(s._idx);
  renderResults();
  updateDownloadBtn();
}

function deselectAll() {
  STATE.selectedIds.clear();
  renderResults();
  updateDownloadBtn();
}

function getFilteredSongs() {
  if (currentFilter === 'all') return STATE.searchResults;
  return STATE.searchResults.filter(s => s.source === currentFilter);
}

function getSelectedSongs() {
  return STATE.searchResults.filter(s => STATE.selectedIds.has(s._idx));
}

function updateDownloadBtn() {
  const count = STATE.selectedIds.size;
  DOM.downloadSelBtn.querySelector('span').textContent = count > 0 ? `下载选中 (${count})` : '下载选中';
  DOM.downloadSelBtn.disabled = count === 0;
}

// ═══════════════════════════════════════════════════════════
// 8. Download with SSE Progress
// ═══════════════════════════════════════════════════════════
async function startDownload() {
  const selected = getSelectedSongs();
  if (selected.length === 0) {
    showToast('info', '请先选择要下载的歌曲');
    return;
  }

  DOM.downloadSelBtn.disabled = true;
  DOM.downloadSelBtn.querySelector('span').textContent = '下载中…';

  // Clear log
  const logEl = DOM.downloadLog;
  logEl.innerHTML = '';

  // Start SSE listener before sending download request
  startSSEListener();

  try {
    const resp = await fetch('/api/download', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        songs: selected.map(s => ({
          source: s.source,
          song_name: s.song_name,
          singers: s.singers,
          ext: s.ext || 'mp3',
          download_url: s.download_url,
        })),
        session_id: STATE.sessionId,
      }),
    });

    if (!resp.ok) {
      const errData = await resp.json().catch(() => ({}));
      throw new Error(errData.error || '下载请求失败');
    }

    await resp.json(); // { job_id, status }
    appendLog('info', `开始下载 ${selected.length} 首歌曲...`);
    updateProgress(0, selected.length);
  } catch (err) {
    appendLog('error', `下载请求失败: ${err.message}`);
    showToast('error', err.message);
    stopSSEListener();
    DOM.downloadSelBtn.disabled = false;
    updateDownloadBtn();
  }
}

// ─── SSE ───
function startSSEListener() {
  stopSSEListener(); // Ensure only one

  const url = `/api/sse/${STATE.sessionId}`;
  STATE.es = new EventSource(url);

  STATE.es.addEventListener('connected', (e) => {
    console.log('[SSE] Connected:', JSON.parse(e.data));
    appendLog('info', '已连接到下载服务');
  });

  STATE.es.addEventListener('log', (e) => {
    try {
      const data = JSON.parse(e.data);
      appendLog(data.level || 'info', data.message);
    } catch { /* malformed event */ }
  });

  STATE.es.addEventListener('progress', (e) => {
    try {
      const data = JSON.parse(e.data);
      updateProgress(data.overall_completed ?? 0, data.overall_total ?? 0);
    } catch { /* ignore */ }
  });

  STATE.es.addEventListener('file_done', (e) => {
    try {
      const data = JSON.parse(e.data);
      appendLog('success', `✅ ${data.singers} - ${data.song_name} 下载完成 (${formatBytes(data.size || 0)})`);
    } catch { /* ignore */ }
  });

  STATE.es.addEventListener('done', (e) => {
    try {
      const data = JSON.parse(e.data);
      appendLog('success', `🎉 全部完成! 成功下载 ${data.completed}/${data.total} 首歌曲`);
      showToast('success', `下载完成: ${data.completed}/${data.total} 首`);
    } catch { /* ignore */ }
    cleanupAfterDownload();
  });

  STATE.es.onerror = () => {
    // SSE may reconnect automatically; only treat as error if connection fully fails
    appendLog('warning', '⚠️ 连接中断，正在重连...');
  };
}

function stopSSEListener() {
  if (STATE.es) {
    STATE.es.close();
    STATE.es = null;
  }
}

function cleanupAfterDownload() {
  setTimeout(() => {
    stopSSEListener();
    DOM.downloadSelBtn.disabled = false;
    updateDownloadBtn();
  }, 1500);
}

function updateProgress(completed, total) {
  const pct = total > 0 ? Math.round((completed / total) * 100) : 0;
  DOM.progressFill.style.width = `${pct}%`;
  DOM.progressBar.setAttribute('aria-valuenow', String(pct));
  DOM.progressText.textContent = `${completed}/${total} · ${pct}%`;
}

function appendLog(level, message) {
  const logEl = DOM.downloadLog;
  // Remove empty state
  const emptyEl = logEl.querySelector('.log-empty');
  if (emptyEl) emptyEl.remove();

  const time = new Date().toLocaleTimeString('zh-CN', { hour12: false });
  const entry = document.createElement('div');
  entry.className = `log-entry ${level}`;
  entry.innerHTML = `<span class="log-time">${time}</span><span>${escapeHTML(message)}</span>`;
  logEl.appendChild(entry);

  // Auto-scroll to bottom
  logEl.scrollTop = logEl.scrollHeight;

  // Limit log entries to 200 (O(1) removal from front)
  while (logEl.children.length > 200) {
    logEl.firstChild?.remove();
  }
}

// ═══════════════════════════════════════════════════════════
// 9. Playlist Parsing
// ═══════════════════════════════════════════════════════════
async function parsePlaylist() {
  const url = DOM.playlistInput.value.trim();
  if (!url) {
    showToast('info', '请输入歌单链接');
    return;
  }
  if (!url.startsWith('http')) {
    showToast('error', '无效的链接格式');
    return;
  }

  DOM.parsePlaylistBtn.disabled = true;
  DOM.parsePlaylistBtn.querySelector('span').textContent = '解析中…';
  DOM.searchStatus.innerHTML = '<span class="spinner"></span> 正在解析歌单...';
  DOM.searchStatus.className = 'status-bar loading';

  try {
    const resp = await fetch('/api/parse-playlist', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, session_id: STATE.sessionId }),
    });

    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || '解析失败');

    STATE.searchResults = data.songs.map((s, i) => ({ ...s, _idx: i }));
    STATE.selectedIds.clear();
    renderResults();
    renderFilterTabs();

    DOM.resultsPanel.style.display = '';
    DOM.resultsEmpty.style.display = 'none';
    DOM.searchStatus.textContent = `✅ 歌单解析完成，共 ${data.total} 首`;
    DOM.searchStatus.className = 'status-bar success';
    showToast('success', `解析到 ${data.total} 首歌曲`);
  } catch (err) {
    DOM.searchStatus.textContent = `❌ ${err.message}`;
    DOM.searchStatus.className = 'status-bar error';
    showToast('error', err.message);
  } finally {
    DOM.parsePlaylistBtn.disabled = false;
    DOM.parsePlaylistBtn.querySelector('span').textContent = '解析歌单';
  }
}

// ═══════════════════════════════════════════════════════════
// 10. History Rendering
// ═══════════════════════════════════════════════════════════
async function renderHistory() {
  const items = await getHistory(15);
  const listEl = DOM.historyList;

  if (items.length === 0) {
    listEl.innerHTML = '<p class="log-empty">暂无搜索历史。</p>';
    return;
  }

  listEl.innerHTML = items.map(item => `
    <div class="history-chip" role="listitem" tabindex="0" data-keyword="${escapeHTML(item.keyword)}" aria-label="搜索: ${escapeHTML(item.keyword)}">
      <span>${escapeHTML(item.keyword)}</span>
    </div>
  `).join('');

  // Bind click to re-search
  listEl.querySelectorAll('.history-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      DOM.searchInput.value = chip.dataset.keyword;
      performSearch();
    });
    chip.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        DOM.searchInput.value = chip.dataset.keyword;
        performSearch();
      }
    });
  });
}

// ═══════════════════════════════════════════════════════════
// 11. Utility Functions
// ═══════════════════════════════════════════════════════════
/**
 * Escape HTML special chars to prevent XSS
 * O(n) where n = string length
 * @param {string} str
 * @returns {string}
 */
function escapeHTML(str) {
  if (!str) return '';
  const map = { '&': '&', '<': '<', '>': '>', '"': '"', "'": ''' };
  return String(str).replace(/[&<>"']/g, (c) => map[c] || c);
}

/**
 * Format bytes to human-readable
 * @param {number} bytes
 * @returns {string}
 */
function formatBytes(bytes) {
  if (bytes <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
}

// ═══════════════════════════════════════════════════════════
// 12. Event Bindings
// ═══════════════════════════════════════════════════════════
function bindEvents() {
  // Theme
  DOM.themeToggle.addEventListener('click', toggleTheme);

  // Search
  DOM.searchBtn.addEventListener('click', performSearch);
  DOM.searchInput.addEventListener('input', onSearchInput);
  DOM.searchInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); performSearch(); }
  });
  DOM.clearSearchBtn.addEventListener('click', () => {
    DOM.searchInput.value = '';
    DOM.searchInput.focus();
  });

  // Playlist
  DOM.parsePlaylistBtn.addEventListener('click', parsePlaylist);
  DOM.playlistInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); parsePlaylist(); }
  });

  // Source quick actions
  DOM.selectAllSourcesBtn.addEventListener('click', selectAllSources);
  DOM.deselectAllSourcesBtn.addEventListener('click', deselectAllSources);

  // Selection
  DOM.selectAllBtn.addEventListener('click', selectAll);
  DOM.deselectAllBtn.addEventListener('click', deselectAll);
  DOM.downloadSelBtn.addEventListener('click', startDownload);

  // History
  DOM.clearHistoryBtn.addEventListener('click', async () => {
    await clearHistory();
    await renderHistory();
    showToast('success', '搜索历史已清除');
  });

  // Keyboard shortcut: Ctrl+K to focus search
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
      e.preventDefault();
      DOM.searchInput.focus();
      DOM.searchInput.select();
    }
  });
}

// ═══════════════════════════════════════════════════════════
// 13. Initialization
// ═══════════════════════════════════════════════════════════
async function init() {
  // Restore theme preference from IndexedDB
  const savedTheme = await getThemePreference();
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  applyTheme(savedTheme || (prefersDark ? 'dark' : 'light'));

  // Listen for system theme changes
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
    if (!(await getThemePreference())) {
      applyTheme(e.matches ? 'dark' : 'light');
    }
  });

  // Fetch sources
  await fetchSources();

  // Render history
  await renderHistory();

  // Bind all events
  bindEvents();

  console.log(`🎵 MusicDL Web v1.0.0 initialized | Session: ${STATE.sessionId} | Theme: ${STATE.theme}`);
}

// Start
document.addEventListener('DOMContentLoaded', init);
