// === XSS 防护：把任意字符串安全插入 innerHTML ===
function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = String(str ?? '');
  return div.innerHTML;
}

// ΔE 分级（Figma match-de 配色）
function gradeClass(de) {
  return de < 1 ? 'excellent' : de < 3 ? 'good' : de < 6 ? 'fair' : 'poor';
}

// === API Key：localStorage 持久化 + 自动附带 x-api-key 头 ===
function apiFetch(url, options = {}) {
  const headers = new Headers(options.headers || {});
  const key = localStorage.getItem('colorflow_api_key');
  if (key) headers.set('x-api-key', key);
  options.headers = headers;
  return fetch(url, options);
}

// === 统一错误处理：对 fetch 的 TypeError 给出友好提示 ===
function fetchErrorMessage(e) {
  // TypeError: Failed to fetch → 服务器未启动 / CORS / 网络错误
  if (e && e.name === 'TypeError' && /failed to fetch/i.test(e.message)) {
    return '服务器连接失败（请确认 Flask 服务已启动：start.bat）';
  }
  return e ? String(e) : '未知错误';
}

// === Key 管理函数 ===
async function loadKeyList() {
  const list = document.getElementById('keyList');
  if (!list) return;
  try {
    const resp = await apiFetch('/api/keys');
    const data = await resp.json();
    if (!data.success || !data.keys || data.keys.length === 0) {
      list.innerHTML = '<div class="key-empty">暂无 Key · 点击上方按钮生成</div>';
      return;
    }
    list.innerHTML = data.keys.map(k => {
      const name = escapeHtml(k.name);
      const masked = escapeHtml(k.key_masked);
      const created = escapeHtml(k.created_at || '');
      const lastUsed = k.last_used ? escapeHtml(k.last_used) : '未使用';
      return `<div class="key-card">
        <div class="key-card-name">${name}</div>
        <div class="key-card-value">${masked}</div>
        <div class="key-card-meta">
          <span>创建: ${created} · ${lastUsed}</span>
          <button class="key-card-revoke" data-key-id="${escapeHtml(k.key_id)}">撤销</button>
        </div>
      </div>`;
    }).join('');
    // 绑定撤销按钮
    list.querySelectorAll('.key-card-revoke').forEach(btn => {
      btn.addEventListener('click', async () => {
        const keyId = btn.dataset.keyId;
        const resp = await apiFetch('/api/keys/' + encodeURIComponent(keyId), { method: 'DELETE' });
        const d = await resp.json();
        if (d.success) {
          // 如果撤销的是当前正在用的 key，清除 localStorage（按非敏感 key_id 比对）
          if (localStorage.getItem('colorflow_api_key_id') === keyId) {
            localStorage.removeItem('colorflow_api_key');
            localStorage.removeItem('colorflow_api_key_id');
          }
          loadKeyList();
          updateMcpConfig();
        } else {
          alert('撤销失败: ' + (d.error || ''));
        }
      });
    });
  } catch (e) {
    list.innerHTML = '<div class="key-empty">加载失败</div>';
  }
}

function updateMcpConfig() {
  const block = document.getElementById('mcpConfig');
  if (!block) return;
  const key = localStorage.getItem('colorflow_mcp_key')
    || localStorage.getItem('colorflow_api_key')
    || '（请先生成 Key）';
  const scriptPath = window.location.pathname.replace(/\/$/, '') || '.';
  const config = {
    mcpServers: {
      colorflow: {
        command: 'python',
        args: ['mcp_server.py'],
        env: { COLORFLOW_API_KEY: key }
      }
    }
  };
  block.textContent = JSON.stringify(config, null, 2);
}

// === Key 生成 ===
const generateKeyBtn = document.getElementById('generateKeyBtn');
const keyModal = document.getElementById('keyModal');
const newKeyDisplay = document.getElementById('newKeyDisplay');
const copyNewKeyBtn = document.getElementById('copyNewKeyBtn');

if (generateKeyBtn) {
  generateKeyBtn.addEventListener('click', async () => {
    const name = prompt('给这个 Key 起个名字（如：我的 Claude Code）', '');
    if (name === null) return;
    try {
      const resp = await apiFetch('/api/keys/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name || '未命名' }),
      });
      const data = await resp.json();
      if (data.success) {
        newKeyDisplay.value = data.key;
        localStorage.setItem('colorflow_api_key', data.key);
        if (data.key_id) localStorage.setItem('colorflow_api_key_id', data.key_id);
        keyModal.classList.remove('hidden');
        loadKeyList();
        updateMcpConfig();
      } else {
        alert('生成失败: ' + (data.error || ''));
      }
    } catch (e) {
      alert('请求失败: ' + fetchErrorMessage(e));
    }
  });
}

if (copyNewKeyBtn) {
  copyNewKeyBtn.addEventListener('click', () => {
    newKeyDisplay.select();
    document.execCommand('copy');
    copyNewKeyBtn.textContent = '✓ 已复制';
    setTimeout(() => { copyNewKeyBtn.textContent = '复制 Key'; }, 1500);
  });
}

// 点击弹窗外部关闭
if (keyModal) {
  keyModal.addEventListener('click', e => {
    if (e.target === keyModal) keyModal.classList.add('hidden');
  });
}

// === MCP 配置复制 ===
const copyMcpConfigBtn = document.getElementById('copyMcpConfigBtn');
if (copyMcpConfigBtn) {
  copyMcpConfigBtn.addEventListener('click', () => {
    const block = document.getElementById('mcpConfig');
    block.select ? block.select() : null;
    navigator.clipboard.writeText(block.textContent).then(() => {
      copyMcpConfigBtn.textContent = '✓ 已复制';
      setTimeout(() => { copyMcpConfigBtn.textContent = '复制配置'; }, 1500);
    });
  });
}

// === Sidebar（DeepSeek Harness 式左栏抽屉，≤960px） ===
const sidebar = document.getElementById('sidebar');
const scrim = document.getElementById('scrim');
const sidebarToggle = document.getElementById('sidebarToggle');
const sidebarClose = document.getElementById('sidebarClose');

function openSidebar() {
  sidebar.classList.add('open');
  scrim.classList.add('show');
}
function closeSidebar() {
  sidebar.classList.remove('open');
  scrim.classList.remove('show');
}

if (sidebarToggle) sidebarToggle.addEventListener('click', openSidebar);
if (sidebarClose) sidebarClose.addEventListener('click', closeSidebar);
if (scrim) scrim.addEventListener('click', closeSidebar);
window.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    closeSidebar();
    closeSettingsModal();
  }
});

// === Settings Modal ===
const settingsModal = document.getElementById('settingsModal');
const settingsToggle = document.getElementById('settingsToggle');
const settingsClose = document.getElementById('settingsClose');
const settingsBackdrop = document.getElementById('settingsBackdrop');

function openSettingsModal() {
  settingsModal.classList.add('open');
  loadKeyList();
  updateMcpConfig();
  loadGenBackends();
  loadLLMConfig();
}
function closeSettingsModal() {
  settingsModal.classList.remove('open');
}

if (settingsToggle) settingsToggle.addEventListener('click', openSettingsModal);
if (settingsClose) settingsClose.addEventListener('click', closeSettingsModal);
if (settingsBackdrop) settingsBackdrop.addEventListener('click', closeSettingsModal);

// === 设置页左侧导航栏切换 ===
document.querySelectorAll('.settings-nav-item').forEach(item => {
  item.addEventListener('click', () => {
    document.querySelectorAll('.settings-nav-item').forEach(i => i.classList.remove('active'));
    document.querySelectorAll('.settings-page').forEach(p => p.classList.remove('active'));
    item.classList.add('active');
    document.getElementById('nav-' + item.dataset.nav).classList.add('active');
  });
});

// === 通用设置：重启服务 & 清除 API Key ===
const restartBtn = document.getElementById('restartBtn');
const restartHint = document.getElementById('restartHint');
const clearApiKeyBtn = document.getElementById('clearApiKeyBtn');

if (restartBtn) {
  restartBtn.addEventListener('click', async () => {
    restartBtn.disabled = true;
    const origHTML = restartBtn.innerHTML;
    restartBtn.innerHTML = '<span class="btn-text">重启中...</span>';
    restartHint.textContent = '';
    try {
      const resp = await apiFetch('/api/restart', { method: 'POST' });
      const data = await resp.json();
      if (data.success) {
        restartHint.textContent = '✓ ' + data.message;
        restartHint.style.color = 'var(--success)';
        // 等 2 秒后自动跳转描图页
        setTimeout(() => {
          closeSettingsModal();
          const traceTab = document.querySelector('.tab[data-tab="trace"]');
          if (traceTab) traceTab.click();
        }, 2000);
      } else {
        restartHint.textContent = '✗ ' + (data.error || '重启失败');
        restartHint.style.color = 'var(--error)';
      }
    } catch (e) {
      restartHint.textContent = '✗ 请求失败: ' + fetchErrorMessage(e);
      restartHint.style.color = 'var(--error)';
    } finally {
      restartBtn.innerHTML = origHTML;
      restartBtn.disabled = false;
    }
  });
}

if (clearApiKeyBtn) {
  clearApiKeyBtn.addEventListener('click', () => {
    localStorage.removeItem('colorflow_api_key');
    localStorage.removeItem('colorflow_api_key_id');
    clearApiKeyBtn.textContent = '✓ 已清除';
    setTimeout(() => { clearApiKeyBtn.textContent = '清除本地 Key'; }, 1500);
    updateMcpConfig();
  });
}

// === Tab Navigation ===
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById('tab-' + tab.dataset.tab).classList.add('active');
    // 移动端点击导航后自动收起抽屉
    if (window.matchMedia('(max-width: 960px)').matches) closeSidebar();
  });
});

// === Cutout（位图抠图） ===
const cutoutUploadZone = document.getElementById('cutoutUploadZone');
const cutoutFile = document.getElementById('cutoutFile');
const cutoutPreviewImg = document.getElementById('cutoutPreviewImg');
const cutoutBtn = document.getElementById('cutoutBtn');
const cutoutPreview = document.getElementById('cutoutPreview');
const cutoutInfo = document.getElementById('cutoutInfo');
const cutoutSize = document.getElementById('cutoutSize');
const cutoutDownload = document.getElementById('cutoutDownload');

let currentCutoutBase64 = null;

cutoutUploadZone.addEventListener('click', () => cutoutFile.click());
cutoutUploadZone.addEventListener('dragover', e => { e.preventDefault(); cutoutUploadZone.classList.add('dragover'); });
cutoutUploadZone.addEventListener('dragleave', () => cutoutUploadZone.classList.remove('dragover'));
cutoutUploadZone.addEventListener('drop', e => {
  e.preventDefault();
  cutoutUploadZone.classList.remove('dragover');
  if (e.dataTransfer.files[0]) {
    cutoutFile.files = e.dataTransfer.files;
    handleCutoutFile(e.dataTransfer.files[0]);
  }
});

cutoutFile.addEventListener('change', e => {
  if (e.target.files[0]) handleCutoutFile(e.target.files[0]);
});

function handleCutoutFile(file) {
  if (!file.type.startsWith('image/')) {
    alert('请上传图片文件');
    return;
  }
  if (file.size > 10 * 1024 * 1024) {
    alert('图片不能超过 10MB');
    return;
  }
  const reader = new FileReader();
  reader.onload = e => {
    cutoutPreviewImg.src = e.target.result;
    cutoutPreviewImg.classList.remove('hidden');
    cutoutUploadZone.querySelector('.upload-placeholder').classList.add('hidden');
    cutoutBtn.disabled = false;
  };
  reader.readAsDataURL(file);
}

cutoutBtn.addEventListener('click', async () => {
  if (!cutoutFile.files[0]) return;
  cutoutBtn.disabled = true;
  cutoutBtn.querySelector('.btn-text').classList.add('hidden');
  cutoutBtn.querySelector('.btn-loader').classList.remove('hidden');
  cutoutPreview.innerHTML = '<div class="svg-placeholder">AI 抠图中...</div>';
  cutoutInfo.classList.add('hidden');

  const formData = new FormData();
  formData.append('image', cutoutFile.files[0]);
  // 抠图精度参数
  formData.append('model', document.getElementById('cutoutModel').value);
  formData.append('alpha_matting', document.getElementById('cutoutAlphaMatting').checked ? '1' : '0');
  formData.append('alpha_matting_foreground_threshold', document.getElementById('cutoutAMFG').value);
  formData.append('alpha_matting_background_threshold', document.getElementById('cutoutAMBG').value);
  formData.append('alpha_matting_erode_size', document.getElementById('cutoutAMErode').value);
  formData.append('decontaminate', document.getElementById('cutoutDecontaminate').checked ? '1' : '0');
  formData.append('post_process_mask', document.getElementById('cutoutPostProcess').checked ? '1' : '0');

  try {
    const resp = await apiFetch('/api/cutout', { method: 'POST', body: formData });
    const data = await resp.json();
    if (data.success) {
      currentCutoutBase64 = data.png_base64;
      cutoutPreview.innerHTML = `<img src="data:image/png;base64,${data.png_base64}" alt="抠图结果" />`;
      cutoutInfo.classList.remove('hidden');
      const modelLabel = data.model ? ` · ${data.model}` : '';
      cutoutSize.textContent = `${(data.size / 1024).toFixed(1)} KB · ${data.width}×${data.height}${modelLabel}`;
    } else {
      cutoutPreview.innerHTML = `<div class="svg-placeholder" style="color:var(--error)">错误: ${escapeHtml(data.error)}</div>`;
    }
  } catch (e) {
    cutoutPreview.innerHTML = `<div class="svg-placeholder" style="color:var(--error)">请求失败: ${escapeHtml(fetchErrorMessage(e))}</div>`;
  } finally {
    cutoutBtn.disabled = false;
    cutoutBtn.querySelector('.btn-text').classList.remove('hidden');
    cutoutBtn.querySelector('.btn-loader').classList.add('hidden');
  }
});

cutoutDownload.addEventListener('click', () => {
  if (!currentCutoutBase64) return;
  const a = document.createElement('a');
  a.href = 'data:image/png;base64,' + currentCutoutBase64;
  a.download = 'colorflow_cutout.png';
  a.click();
});

// === Cutout 精度面板交互 ===
const cutoutAdvancedToggle = document.getElementById('cutoutAdvancedToggle');
const cutoutAdvanced = document.getElementById('cutoutAdvanced');
const cutoutAlphaMatting = document.getElementById('cutoutAlphaMatting');
const cutoutAMThresholds = document.getElementById('cutoutAMThresholds');
const cutoutAMFG = document.getElementById('cutoutAMFG');
const cutoutAMFGVal = document.getElementById('cutoutAMFGVal');
const cutoutAMBG = document.getElementById('cutoutAMBG');
const cutoutAMBGVal = document.getElementById('cutoutAMBGVal');
const cutoutAMErode = document.getElementById('cutoutAMErode');
const cutoutAMErodeVal = document.getElementById('cutoutAMErodeVal');

if (cutoutAdvancedToggle) {
  cutoutAdvancedToggle.addEventListener('change', () => {
    cutoutAdvanced.classList.toggle('hidden', !cutoutAdvancedToggle.checked);
  });
}
if (cutoutAlphaMatting) {
  cutoutAlphaMatting.addEventListener('change', () => {
    cutoutAMThresholds.classList.toggle('hidden', !cutoutAlphaMatting.checked);
  });
}
if (cutoutAMFG) cutoutAMFG.addEventListener('input', () => { cutoutAMFGVal.textContent = cutoutAMFG.value; });
if (cutoutAMBG) cutoutAMBG.addEventListener('input', () => { cutoutAMBGVal.textContent = cutoutAMBG.value; });
if (cutoutAMErode) cutoutAMErode.addEventListener('input', () => { cutoutAMErodeVal.textContent = cutoutAMErode.value; });

// === Vector Trace ===
const uploadZone = document.getElementById('uploadZone');
const traceFile = document.getElementById('traceFile');
const previewImg = document.getElementById('previewImg');
const traceBtn = document.getElementById('traceBtn');
const svgPreview = document.getElementById('svgPreview');
const svgInfo = document.getElementById('svgInfo');
const downloadSvg = document.getElementById('downloadSvg');
const filterSpeckle = document.getElementById('filterSpeckle');
const speckleVal = document.getElementById('speckleVal');
const pathPrecision = document.getElementById('pathPrecision');
const precisionVal = document.getElementById('precisionVal');
const colorPrecision = document.getElementById('colorPrecision');
const colorPrecisionVal = document.getElementById('colorPrecisionVal');
const layerDifference = document.getElementById('layerDifference');
const layerDifferenceVal = document.getElementById('layerDifferenceVal');
const cornerThreshold = document.getElementById('cornerThreshold');
const cornerThresholdVal = document.getElementById('cornerThresholdVal');
const lengthThreshold = document.getElementById('lengthThreshold');
const lengthThresholdVal = document.getElementById('lengthThresholdVal');

let currentSvgBase64 = null;

filterSpeckle.addEventListener('input', () => speckleVal.textContent = filterSpeckle.value);
pathPrecision.addEventListener('input', () => precisionVal.textContent = pathPrecision.value);
colorPrecision.addEventListener('input', () => colorPrecisionVal.textContent = colorPrecision.value);
layerDifference.addEventListener('input', () => layerDifferenceVal.textContent = layerDifference.value);
cornerThreshold.addEventListener('input', () => cornerThresholdVal.textContent = cornerThreshold.value);
lengthThreshold.addEventListener('input', () => lengthThresholdVal.textContent = lengthThreshold.value);

uploadZone.addEventListener('click', () => traceFile.click());
uploadZone.addEventListener('dragover', e => { e.preventDefault(); uploadZone.classList.add('dragover'); });
uploadZone.addEventListener('dragleave', () => uploadZone.classList.remove('dragover'));
uploadZone.addEventListener('drop', e => {
  e.preventDefault();
  uploadZone.classList.remove('dragover');
  if (e.dataTransfer.files[0]) {
    traceFile.files = e.dataTransfer.files;
    handleFile(e.dataTransfer.files[0]);
  }
});

traceFile.addEventListener('change', e => {
  if (e.target.files[0]) handleFile(e.target.files[0]);
});

function handleFile(file) {
  if (!file.type.startsWith('image/')) {
    alert('请上传图片文件');
    return;
  }
  if (file.size > 10 * 1024 * 1024) {
    alert('图片不能超过 10MB');
    return;
  }
  const reader = new FileReader();
  reader.onload = e => {
    previewImg.src = e.target.result;
    previewImg.classList.remove('hidden');
    uploadZone.querySelector('.upload-placeholder').classList.add('hidden');
    traceBtn.disabled = false;
  };
  reader.readAsDataURL(file);
}

const traceMode = document.getElementById('traceMode');
const ignoreWhite = document.getElementById('ignoreWhite');
const paramHint = document.querySelector('.param-hint');

// 描图 / 抠图 双态切换入口 → 同步 traceMode 下拉
const modeBtns = document.querySelectorAll('.mode-btn');
function setModeButtons(mode) {
  modeBtns.forEach(b => b.classList.toggle('active', b.dataset.mode === mode));
}

// 抠图模式：自动输出透明背景，忽略白色开关被接管
function syncTraceMode() {
  const isCutout = traceMode.value === 'cutout';
  setModeButtons(traceMode.value);
  ignoreWhite.checked = isCutout;      // 抠图必然透明
  ignoreWhite.disabled = isCutout;
  ignoreWhite.closest('.checkbox-row').style.opacity = isCutout ? '0.55' : '1';
  if (isCutout && paramHint) paramHint.textContent = '抠图自动透明背景';
  else if (paramHint) paramHint.textContent = '去除白底，留透明通道';
  // 抠图精度面板：仅 mode=cutout 时显示
  const traceCutoutParams = document.getElementById('traceCutoutParams');
  if (traceCutoutParams) traceCutoutParams.classList.toggle('hidden', !isCutout);
}
traceMode.addEventListener('change', syncTraceMode);
modeBtns.forEach(btn => {
  btn.addEventListener('click', () => {
    traceMode.value = btn.dataset.mode;
    syncTraceMode();
  });
});
syncTraceMode();

traceBtn.addEventListener('click', async () => {
  if (!traceFile.files[0]) return;
  traceBtn.disabled = true;
  traceBtn.querySelector('.btn-text').classList.add('hidden');
  traceBtn.querySelector('.btn-loader').classList.remove('hidden');

  const formData = new FormData();
  formData.append('image', traceFile.files[0]);
  formData.append('mode', document.getElementById('traceMode').value);
  formData.append('filter_speckle', filterSpeckle.value);
  formData.append('color_precision', colorPrecision.value);
  formData.append('layer_difference', layerDifference.value);
  formData.append('corner_threshold', cornerThreshold.value);
  formData.append('path_precision', pathPrecision.value);
  formData.append('ignore_white', document.getElementById('ignoreWhite').checked ? '1' : '0');
  formData.append('colormode', document.getElementById('traceColormode').value);
  formData.append('hierarchical', document.getElementById('traceHierarchical').value);
  formData.append('length_threshold', document.getElementById('lengthThreshold').value);
  if (document.getElementById('traceMode').value === 'cutout') {
    formData.append('model', document.getElementById('traceCutoutModel').value);
    formData.append('alpha_matting', document.getElementById('traceCutoutAM').checked ? '1' : '0');
    formData.append('alpha_matting_foreground_threshold', document.getElementById('traceCutoutAMFG').value);
    formData.append('alpha_matting_background_threshold', document.getElementById('traceCutoutAMBG').value);
    formData.append('alpha_matting_erode_size', document.getElementById('traceCutoutAMErode').value);
    formData.append('decontaminate', document.getElementById('traceCutoutDecontaminate').checked ? '1' : '0');
    formData.append('post_process_mask', document.getElementById('traceCutoutPostProcess').checked ? '1' : '0');
  }

  try {
    const resp = await apiFetch('/api/trace', { method: 'POST', body: formData });
    const data = await resp.json();
    if (data.success) {
      currentSvgBase64 = data.svg_base64;
      const svgEl = `<img src="data:image/svg+xml;base64,${data.svg_base64}" alt="SVG Output" />`;
      svgPreview.innerHTML = svgEl;
      svgInfo.classList.remove('hidden');
      svgInfo.querySelector('.svg-size').textContent = `${(data.size / 1024).toFixed(1)} KB`;
    } else {
      svgPreview.innerHTML = `<div class="svg-placeholder" style="color:var(--error)">错误: ${escapeHtml(data.error)}</div>`;
    }
  } catch (e) {
    svgPreview.innerHTML = `<div class="svg-placeholder" style="color:var(--error)">请求失败: ${escapeHtml(fetchErrorMessage(e))}</div>`;
  } finally {
    traceBtn.disabled = false;
    traceBtn.querySelector('.btn-text').classList.remove('hidden');
    traceBtn.querySelector('.btn-loader').classList.add('hidden');
  }
});

downloadSvg.addEventListener('click', () => {
  if (!currentSvgBase64) return;
  const a = document.createElement('a');
  a.href = 'data:image/svg+xml;base64,' + currentSvgBase64;
  a.download = 'colorflow_output.svg';
  a.click();
});

// === 导出印刷 PDF（export_print 前端入口） ===
const exportPdfBtn = document.getElementById('exportPdfBtn');
const exportPanel = document.getElementById('exportPanel');

exportPdfBtn.addEventListener('click', () => {
  if (!traceFile.files[0]) return;
  exportPanel.classList.remove('hidden');
  document.getElementById('exportPdfConfirm').disabled = false;
});

document.getElementById('exportPdfCancel').addEventListener('click', () => {
  exportPanel.classList.add('hidden');
});

document.getElementById('exportPdfConfirm').addEventListener('click', async () => {
  const w = parseFloat(document.getElementById('expWidth').value);
  const h = parseFloat(document.getElementById('expHeight').value);
  const b = parseFloat(document.getElementById('expBleed').value) || 0;
  if (!w || !h) { alert('请输入成品尺寸'); return; }
  const btn = document.getElementById('exportPdfConfirm');
  btn.disabled = true; btn.textContent = '生成中...';
  try {
    const formData = new FormData();
    formData.append('image', traceFile.files[0]);
    formData.append('width_mm', String(w));
    formData.append('height_mm', String(h));
    formData.append('bleed_mm', String(b));
    formData.append('mode', document.getElementById('traceMode').value);
    const resp = await apiFetch('/api/print/export', { method: 'POST', body: formData });
    if (!resp.ok) {
      const d = await resp.json().catch(() => ({}));
      alert('导出失败: ' + (d.error || resp.status));
      return;
    }
    const blob = await resp.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'colorflow_print.pdf';
    a.click();
    URL.revokeObjectURL(a.href);
  } catch (e) {
    alert('导出失败: ' + fetchErrorMessage(e));
  } finally {
    btn.disabled = false; btn.textContent = '生成印刷 PDF';
    exportPanel.classList.add('hidden');
  }
});

// === 一键流水线：提取主色 & Pantone 匹配 ===
const colorMatchBtn = document.getElementById('colorMatchBtn');
const paletteResults = document.getElementById('paletteResults');
let paletteExportData = null;

colorMatchBtn.addEventListener('click', async () => {
  if (!traceFile.files[0]) return;
  colorMatchBtn.disabled = true;
  colorMatchBtn.textContent = '提取中...';
  paletteResults.classList.remove('hidden');
  paletteResults.innerHTML = '<div class="match-placeholder">正在描图并提取主色...</div>';

  const formData = new FormData();
  formData.append('image', traceFile.files[0]);
  formData.append('mode', document.getElementById('traceMode').value);
  formData.append('filter_speckle', filterSpeckle.value);
  formData.append('color_precision', colorPrecision.value);
  formData.append('layer_difference', layerDifference.value);
  formData.append('corner_threshold', cornerThreshold.value);
  formData.append('path_precision', pathPrecision.value);
  formData.append('ignore_white', document.getElementById('ignoreWhite').checked ? '1' : '0');
  formData.append('colormode', document.getElementById('traceColormode').value);
  formData.append('hierarchical', document.getElementById('traceHierarchical').value);
  formData.append('length_threshold', document.getElementById('lengthThreshold').value);
  if (document.getElementById('traceMode').value === 'cutout') {
    formData.append('model', document.getElementById('traceCutoutModel').value);
    formData.append('alpha_matting', document.getElementById('traceCutoutAM').checked ? '1' : '0');
    formData.append('alpha_matting_foreground_threshold', document.getElementById('traceCutoutAMFG').value);
    formData.append('alpha_matting_background_threshold', document.getElementById('traceCutoutAMBG').value);
    formData.append('alpha_matting_erode_size', document.getElementById('traceCutoutAMErode').value);
    formData.append('decontaminate', document.getElementById('traceCutoutDecontaminate').checked ? '1' : '0');
    formData.append('post_process_mask', document.getElementById('traceCutoutPostProcess').checked ? '1' : '0');
  }

  try {
    const resp = await apiFetch('/api/trace/colors', { method: 'POST', body: formData });
    const data = await resp.json();
    if (!data.success) {
      paletteResults.innerHTML = `<div class="match-placeholder" style="color:var(--error)">错误: ${escapeHtml(data.error)}</div>`;
      return;
    }

    if (!data.palette || data.palette.length === 0) {
      paletteResults.innerHTML = '<div class="match-placeholder">未检测到可识别的主色（可能为单色或渐变图）</div>';
      return;
    }

    let html = '<div class="palette-title">检测到 ' + data.palette.length + ' 个主色 · Pantone 色卡</div>';

    data.palette.forEach((item, idx) => {
      const c = item.color;
      const top = item.pantone_matches[0] || null;
      const pct = Math.round((c.share || 0) * 100);
      const rgb = (c.rgb || []).join(',');

      html += `<div class="swatch-card">
        <div class="swatch-large" style="background:${escapeHtml(c.hex)}"></div>
        <div class="swatch-body">
          <div class="swatch-head">
            <span class="swatch-hex">${escapeHtml(c.hex)}</span>
            <span class="swatch-share">${pct}%</span>
          </div>
          ${top
            ? `<div class="swatch-pantone">${escapeHtml(top.name)}
                 <span class="match-de ${gradeClass(top.delta_e)}">ΔE ${escapeHtml(top.delta_e)}</span>
               </div>
               <div class="swatch-values">
                 <span>HEX ${escapeHtml(c.hex)}</span>
                 <span>CMYK ${escapeHtml(top.cmyk.join('/'))}</span>
                 <span>RGB ${escapeHtml(rgb)}</span>
               </div>
               ${item.pantone_matches.length > 1 ? `<button class="btn btn-small swatch-expand" data-i="${idx}">全部匹配 (${item.pantone_matches.length})</button>` : ''}`
            : `<div class="swatch-pantone">无匹配色</div>`}
          <div class="swatch-more hidden" data-more="${idx}">
            ${(item.pantone_matches || []).slice(1).map(m =>
              `<div class="swatch-more-row">${escapeHtml(m.name)} · ${escapeHtml(m.hex)}
                 <span class="match-de ${gradeClass(m.delta_e)}">ΔE ${escapeHtml(m.delta_e)}</span></div>`).join('')}
          </div>
        </div>
      </div>`;
    });
    paletteResults.innerHTML = html;

    // 导出印刷 PDF 按钮
    paletteResults.insertAdjacentHTML(
      'beforeend',
      '<div style="text-align:center;margin-top:14px;padding-top:12px;border-top:1px solid var(--border);">' +
      '<button class="btn btn-small btn-accent" id="paletteExportBtn">导出印刷 PDF</button>' +
      '</div>'
    );

    // 存储导出数据（SVG base64 + palette 数据）
    paletteExportData = {
      svg_base64: data.svg_base64,
      palette: data.palette,
    };

    document.getElementById('paletteExportBtn').addEventListener('click', async () => {
      const btn = document.getElementById('paletteExportBtn');
      btn.disabled = true;
      btn.textContent = '生成中...';
      try {
        const resp = await apiFetch('/api/pantone/export', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            type: 'palette',
            svg_base64: paletteExportData.svg_base64,
            palette: paletteExportData.palette,
          }),
        });
        if (!resp.ok) {
          const d = await resp.json().catch(() => ({}));
          alert('导出失败: ' + (d.error || resp.status));
          return;
        }
        const blob = await resp.blob();
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'colorflow_palette_report.pdf';
        a.click();
        URL.revokeObjectURL(a.href);
      } catch (e) {
        alert('导出失败: ' + fetchErrorMessage(e));
      } finally {
        btn.disabled = false;
        btn.textContent = '导出印刷 PDF';
      }
    });

    // 展开/收起 top-3 匹配
    paletteResults.querySelectorAll('.swatch-expand').forEach(btn => {
      btn.addEventListener('click', () => {
        const more = paletteResults.querySelector(`[data-more="${btn.dataset.i}"]`);
        more.classList.toggle('hidden');
        btn.textContent = more.classList.contains('hidden')
          ? `全部匹配 (${data.palette[Number(btn.dataset.i)].pantone_matches.length})` : '收起';
      });
    });
  } catch (e) {
    paletteResults.innerHTML = `<div class="match-placeholder" style="color:var(--error)">请求失败: ${escapeHtml(fetchErrorMessage(e))}</div>`;
  } finally {
    colorMatchBtn.disabled = false;
    colorMatchBtn.textContent = '提取主色 & Pantone 匹配';
  }
});

// === Pantone Lookup ===
const pantoneInput = document.getElementById('pantoneInput');
const pantoneBtn = document.getElementById('pantoneBtn');
const pantoneResult = document.getElementById('pantoneResult');
const pantoneError = document.getElementById('pantoneError');
let pantoneLookupResult = null;

pantoneBtn.addEventListener('click', async () => {
  const name = pantoneInput.value.trim();
  if (!name) return;
  pantoneResult.classList.add('hidden');
  pantoneError.classList.add('hidden');

  try {
    const resp = await apiFetch(`/api/pantone/lookup?name=${encodeURIComponent(name)}`);
    const data = await resp.json();
    if (data.success) {
      const r = data.result;
      pantoneLookupResult = r;
      document.getElementById('pantoneSwatch').style.background = r.hex;
      document.getElementById('pantoneName').textContent = r.name;
      document.getElementById('pantoneHex').textContent = r.hex;
      document.getElementById('pantoneCmyk').textContent = `${r.c}/${r.m}/${r.y}/${r.k}`;
      document.getElementById('pantoneRgb').textContent = r.rgb || 'N/A';
      pantoneResult.classList.remove('hidden');
      document.getElementById('pantoneExportRow').classList.remove('hidden');
    } else {
      pantoneError.textContent = data.error || '查询失败';
      pantoneError.classList.remove('hidden');
    }
  } catch (e) {
    pantoneError.textContent = '请求失败: ' + fetchErrorMessage(e);
    pantoneError.classList.remove('hidden');
  }
});

pantoneInput.addEventListener('keydown', e => { if (e.key === 'Enter') pantoneBtn.click(); });

// 色号查询 — 导出色卡 PDF
const pantoneExportBtn = document.getElementById('pantoneExportBtn');
if (pantoneExportBtn) {
  pantoneExportBtn.addEventListener('click', async () => {
    if (!pantoneLookupResult) return;
    pantoneExportBtn.textContent = '生成中...';
    try {
      const resp = await apiFetch('/api/pantone/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          type: 'swatch',
          name: pantoneLookupResult.name,
          hex: pantoneLookupResult.hex,
          cmyk: [pantoneLookupResult.c, pantoneLookupResult.m, pantoneLookupResult.y, pantoneLookupResult.k],
          rgb: pantoneLookupResult.rgb ? pantoneLookupResult.rgb.split('/').map(s => parseInt(s.trim())) : [0, 0, 0],
        }),
      });
      if (!resp.ok) { const d = await resp.json().catch(() => ({})); alert('导出失败: ' + (d.error || resp.status)); return; }
      const blob = await resp.blob();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `pantone_${pantoneLookupResult.name.replace(/\s/g, '_')}.pdf`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) {
      alert('导出失败: ' + fetchErrorMessage(e));
    } finally {
      pantoneExportBtn.textContent = '导出色卡 PDF';
    }
  });
}

// === Color Match ===
const colorPicker = document.getElementById('colorPicker');
const hexInput = document.getElementById('hexInput');
const matchBtn = document.getElementById('matchBtn');
const matchResults = document.getElementById('matchResults');

colorPicker.addEventListener('input', () => { hexInput.value = colorPicker.value; });
hexInput.addEventListener('input', () => {
  if (hexInput.value.startsWith('#') && hexInput.value.length === 7) {
    colorPicker.value = hexInput.value;
  }
});

// 存储匹配结果供导出使用
let matchExportData = null;

matchBtn.addEventListener('click', async () => {
  let hex = hexInput.value.trim();
  if (!hex.startsWith('#')) hex = '#' + hex;
  if (hex.length !== 7) return;

  matchResults.innerHTML = '<div class="match-placeholder">查询中...</div>';

  try {
    const resp = await apiFetch('/api/pantone/match', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ hex_color: hex }),
    });
    const data = await resp.json();
    if (data.success && data.matches.length > 0) {
      matchExportData = { input_hex: hex, matches: data.matches };
      document.getElementById('matchExportRow').classList.remove('hidden');
      matchResults.innerHTML = '';
      data.matches.forEach(m => {
        const gradeClass = m.delta_e < 1 ? 'excellent' : m.delta_e < 3 ? 'good' : m.delta_e < 6 ? 'fair' : 'poor';
        matchResults.innerHTML += `
          <div class="match-item">
            <div class="match-swatch" style="background:${escapeHtml(m.hex)}"></div>
            <div class="match-info">
              <div class="match-name">${escapeHtml(m.name)}</div>
              <div class="match-hex">${escapeHtml(m.hex)} · CMYK ${escapeHtml(m.cmyk.join('/'))}</div>
            </div>
            <div class="match-de ${gradeClass}">ΔE ${escapeHtml(m.delta_e)}</div>
          </div>
        `;
      });
    } else {
      matchResults.innerHTML = '<div class="match-placeholder">未找到匹配颜色</div>';
    }
  } catch (e) {
    matchResults.innerHTML = `<div class="match-placeholder" style="color:var(--error)">请求失败: ${escapeHtml(fetchErrorMessage(e))}</div>`;
  }
});

// === Print Cost ===
// Initial color match load
matchBtn.click();

// 色号匹配 — 导出报告 PDF
const matchExportBtn = document.getElementById('matchExportBtn');
if (matchExportBtn) {
  matchExportBtn.addEventListener('click', async () => {
    if (!matchExportData) return;
    matchExportBtn.textContent = '生成中...';
    try {
      const resp = await apiFetch('/api/pantone/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          type: 'report',
          input_hex: matchExportData.input_hex,
          matches: matchExportData.matches.map(m => ({
            name: m.name,
            hex: m.hex,
            cmyk: m.cmyk,
            delta_e: m.delta_e,
          })),
        }),
      });
      if (!resp.ok) { const d = await resp.json().catch(() => ({})); alert('导出失败: ' + (d.error || resp.status)); return; }
      const blob = await resp.blob();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `pantone_match_report.pdf`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) {
      alert('导出失败: ' + fetchErrorMessage(e));
    } finally {
      matchExportBtn.textContent = '导出匹配报告 PDF';
    }
  });
}

// ============================================================
// 3D 灰度图（高度图 / 位移贴图）
// ============================================================
const g3dUploadZone = document.getElementById('g3dUploadZone');
const g3dFile = document.getElementById('g3dFile');
const g3dPreviewImg = document.getElementById('g3dPreviewImg');
const g3dBtn = document.getElementById('g3dBtn');
const g3dPreview = document.getElementById('g3dPreview');
const g3dInfo = document.getElementById('g3dInfo');
const g3dSize = document.getElementById('g3dSize');
const g3dDownload = document.getElementById('g3dDownload');
const g3dHist = document.getElementById('g3dHist');
const g3dHistMeta = document.getElementById('g3dHistMeta');
const g3dHistBar = document.getElementById('g3dHistBar');
const g3dContrast = document.getElementById('g3dContrast');
const g3dContrastVal = document.getElementById('g3dContrastVal');
const g3dGamma = document.getElementById('g3dGamma');
const g3dGammaVal = document.getElementById('g3dGammaVal');
const g3dSmooth = document.getElementById('g3dSmooth');
const g3dSmoothVal = document.getElementById('g3dSmoothVal');

let currentG3DBase64 = null;

g3dContrast.addEventListener('input', () => g3dContrastVal.textContent = g3dContrast.value);
g3dGamma.addEventListener('input', () => g3dGammaVal.textContent = g3dGamma.value);
g3dSmooth.addEventListener('input', () => g3dSmoothVal.textContent = g3dSmooth.value);

g3dUploadZone.addEventListener('click', () => g3dFile.click());
g3dUploadZone.addEventListener('dragover', e => { e.preventDefault(); g3dUploadZone.classList.add('dragover'); });
g3dUploadZone.addEventListener('dragleave', () => g3dUploadZone.classList.remove('dragover'));
g3dUploadZone.addEventListener('drop', e => {
  e.preventDefault();
  g3dUploadZone.classList.remove('dragover');
  if (e.dataTransfer.files[0]) {
    g3dFile.files = e.dataTransfer.files;
    handleG3DFile(e.dataTransfer.files[0]);
  }
});

g3dFile.addEventListener('change', e => {
  if (e.target.files[0]) handleG3DFile(e.target.files[0]);
});

function handleG3DFile(file) {
  if (!file.type.startsWith('image/')) {
    alert('请上传图片文件');
    return;
  }
  if (file.size > 10 * 1024 * 1024) {
    alert('图片不能超过 10MB');
    return;
  }
  const reader = new FileReader();
  reader.onload = e => {
    g3dPreviewImg.src = e.target.result;
    g3dPreviewImg.classList.remove('hidden');
    g3dUploadZone.querySelector('.upload-placeholder').classList.add('hidden');
    g3dBtn.disabled = false;
  };
  reader.readAsDataURL(file);
}

g3dBtn.addEventListener('click', async () => {
  if (!g3dFile.files[0]) return;
  g3dBtn.disabled = true;
  g3dBtn.querySelector('.btn-text').classList.add('hidden');
  g3dBtn.querySelector('.btn-loader').classList.remove('hidden');
  g3dPreview.innerHTML = '<div class="svg-placeholder">生成灰度图中...</div>';
  g3dHist.classList.add('hidden');
  g3dInfo.classList.add('hidden');

  const formData = new FormData();
  formData.append('image', g3dFile.files[0]);
  formData.append('invert', document.getElementById('g3dInvert').checked ? '1' : '0');
  formData.append('contrast', g3dContrast.value);
  formData.append('gamma', g3dGamma.value);
  formData.append('smooth', g3dSmooth.value);
  formData.append('auto_levels', document.getElementById('g3dAutoLevels').checked ? '1' : '0');
  formData.append('bit_depth', document.getElementById('g3dBitDepth').value);

  try {
    const resp = await apiFetch('/api/grayscale3d', { method: 'POST', body: formData });
    const data = await resp.json();
    if (data.success) {
      currentG3DBase64 = data.png_base64;
      g3dPreview.innerHTML = `<img src="data:image/png;base64,${data.png_base64}" alt="3D 灰度图" style="max-width:100%;max-height:220px;object-fit:contain;"/>`;
      g3dInfo.classList.remove('hidden');
      const bd = data.bit_depth || 8;
      g3dSize.textContent = `${(data.size / 1024).toFixed(1)} KB · ${data.width}×${data.height} · ${bd}-bit`;

      // 渲染直方图
      if (data.histogram && data.histogram.length === 256) {
        g3dHist.classList.remove('hidden');
        // 取最高 bin 的百分比作为比例
        const maxVal = data.max_value || 1;
        const minVal = data.min_value || 0;
        g3dHistMeta.textContent = `峰值 ${data.hist_peak} · 范围 ${minVal}–${maxVal}`;

        // 渲染 256 根柱子
        let histHtml = '';
        const hist = data.histogram;
        const histMax = Math.max(...hist) || 1;
        for (let i = 0; i < 256; i++) {
          const h = hist[i] / histMax;
          const pct = (h * 100).toFixed(1);
          histHtml += `<div class="hist-bin" style="height:${pct}%;" title="亮度 ${i}: ${(hist[i] * 100).toFixed(2)}%"></div>`;
        }
        g3dHistBar.innerHTML = histHtml;
      }
    } else {
      g3dPreview.innerHTML = `<div class="svg-placeholder" style="color:var(--error)">错误: ${escapeHtml(data.error)}</div>`;
    }
  } catch (e) {
    g3dPreview.innerHTML = `<div class="svg-placeholder" style="color:var(--error)">请求失败: ${escapeHtml(fetchErrorMessage(e))}</div>`;
  } finally {
    g3dBtn.disabled = false;
    g3dBtn.querySelector('.btn-text').classList.remove('hidden');
    g3dBtn.querySelector('.btn-loader').classList.add('hidden');
  }
});

g3dDownload.addEventListener('click', () => {
  if (!currentG3DBase64) return;
  const a = document.createElement('a');
  a.href = 'data:image/png;base64,' + currentG3DBase64;
  a.download = 'colorflow_3d_greyscale.png';
  a.click();
});

// ============================================================
// AI 生图（GEN 适配器层）
// ============================================================
const genPrompt = document.getElementById('genPrompt');
const genBackend = document.getElementById('genBackend');
const genN = document.getElementById('genN');
const genSize = document.getElementById('genSize');
const genBtn = document.getElementById('genBtn');
const genResults = document.getElementById('genResults');
const genHint = document.getElementById('genHint');
const genRefZone = document.getElementById('genRefZone');
const genRefFile = document.getElementById('genRefFile');
const genRefPreviewImg = document.getElementById('genRefPreviewImg');

let genRefFileObj = null;
let genResultsData = [];   // [{png_base64, width, height, backend, model}]
let genReverseFileObj = null;  // 反向闭环：图→prompt 用

// prompt 非空即启用生成按钮
if (genPrompt) {
  genPrompt.addEventListener('input', () => {
    genBtn.disabled = !genPrompt.value.trim();
  });
}

// 参考图上传区
if (genRefZone) {
  genRefZone.addEventListener('click', () => genRefFile.click());
  genRefZone.addEventListener('dragover', e => { e.preventDefault(); genRefZone.classList.add('dragover'); });
  genRefZone.addEventListener('dragleave', () => genRefZone.classList.remove('dragover'));
  genRefZone.addEventListener('drop', e => {
    e.preventDefault();
    genRefZone.classList.remove('dragover');
    if (e.dataTransfer.files[0]) handleGenRefFile(e.dataTransfer.files[0]);
  });
  genRefFile.addEventListener('change', e => {
    if (e.target.files[0]) handleGenRefFile(e.target.files[0]);
  });
}

function handleGenRefFile(file) {
  if (!file.type.startsWith('image/')) { alert('请上传图片文件'); return; }
  if (file.size > 10 * 1024 * 1024) { alert('图片不能超过 10MB'); return; }
  genRefFileObj = file;
  const reader = new FileReader();
  reader.onload = e => {
    genRefPreviewImg.src = e.target.result;
    genRefPreviewImg.classList.remove('hidden');
    genRefZone.querySelector('.upload-placeholder').classList.add('hidden');
  };
  reader.readAsDataURL(file);
}

// ── 反向闭环（图→prompt）──
const genReverseZone = document.getElementById('genReverseZone');
const genReverseFile = document.getElementById('genReverseFile');
const genReversePreviewImg = document.getElementById('genReversePreviewImg');
const genReverseBtn = document.getElementById('genReverseBtn');

if (genReverseZone) {
  genReverseZone.addEventListener('click', () => genReverseFile.click());
  genReverseZone.addEventListener('dragover', e => { e.preventDefault(); genReverseZone.classList.add('dragover'); });
  genReverseZone.addEventListener('dragleave', () => genReverseZone.classList.remove('dragover'));
  genReverseZone.addEventListener('drop', e => {
    e.preventDefault();
    genReverseZone.classList.remove('dragover');
    if (e.dataTransfer.files[0]) handleGenReverseFile(e.dataTransfer.files[0]);
  });
  genReverseFile.addEventListener('change', e => {
    if (e.target.files[0]) handleGenReverseFile(e.target.files[0]);
  });
}

function handleGenReverseFile(file) {
  if (!file.type.startsWith('image/')) { alert('请上传图片文件'); return; }
  if (file.size > 10 * 1024 * 1024) { alert('图片不能超过 10MB'); return; }
  genReverseFileObj = file;
  genReverseBtn.disabled = false;
  const reader = new FileReader();
  reader.onload = e => {
    genReversePreviewImg.src = e.target.result;
    genReversePreviewImg.classList.remove('hidden');
    genReverseZone.querySelector('.upload-placeholder').classList.add('hidden');
  };
  reader.readAsDataURL(file);
}

// 反向闭环：图→prompt 提取并回填到 prompt 框
if (genReverseBtn) {
  genReverseBtn.addEventListener('click', async () => {
    if (!genReverseFileObj) return;
    const btn = genReverseBtn;
    btn.disabled = true;
    btn.querySelector('.btn-text').classList.add('hidden');
    btn.querySelector('.btn-loader').classList.remove('hidden');
    try {
      const formData = new FormData();
      formData.append('image', genReverseFileObj);
      formData.append('backend', 'auto');
      formData.append('lang', 'en');
      formData.append('style', 'product');
      const resp = await apiFetch('/api/prompt/generate', { method: 'POST', body: formData });
      const data = await resp.json();
      if (!data.success) {
        alert('提取 prompt 失败：' + (data.error || '未知错误'));
        return;
      }
      if (genPrompt) {
        genPrompt.value = data.prompt;
        genBtn.disabled = false;
      }
      genHint.textContent = '🔁 prompt 已由图像自动提取（' + (data.backend || '-') + ' · ' + (data.elapsed_ms || 0) + 'ms），可直接生成或微调后再生成';
    } catch (e) {
      alert('提取 prompt 失败：' + fetchErrorMessage(e));
    } finally {
      btn.disabled = false;
      btn.querySelector('.btn-text').classList.remove('hidden');
      btn.querySelector('.btn-loader').classList.add('hidden');
    }
  });
}

// 后端状态面板（设置页 nav-gen）
async function loadGenBackends() {
  const list = document.getElementById('genBackendsList');
  if (!list) return;
  try {
    const resp = await apiFetch('/api/generate/backends');
    const data = await resp.json();
    if (!data.success) { list.innerHTML = '<div class="key-empty">加载失败</div>'; return; }
    if (!data.any_configured) {
      list.innerHTML = '<div class="key-empty">未配置任何生图后端 Key · 请设置环境变量后重启</div>';
      return;
    }
    list.innerHTML = data.backends.map(b => {
      const dot = b.available ? '✅' : '❌';
      return `<div class="gen-backend-row"><span class="gen-backend-dot">${dot}</span>
        <span class="gen-backend-label">${escapeHtml(b.label)}</span></div>`;
    }).join('');
    // 默认后端下拉同步
    if (data.default_backend && genBackend) genBackend.value = data.default_backend;
  } catch (e) {
    list.innerHTML = '<div class="key-empty">加载失败</div>';
  }
}

// 后端状态面板（设置页 nav-llm）
async function loadVisionBackends() {
  const list = document.getElementById('visionBackendsList');
  if (!list) return;
  try {
    const resp = await apiFetch('/api/prompt/backends');
    const data = await resp.json();
    if (!data.success) { list.innerHTML = '<div class="key-empty">加载失败</div>'; return; }
    if (!data.any_configured) {
      list.innerHTML = '<div class="key-empty">未配置任何大模型 Key · 将使用 mock 降级</div>';
      return;
    }
    list.innerHTML = data.backends.map(b => {
      const dot = b.available ? '✅' : '❌';
      return `<div class="gen-backend-row"><span class="gen-backend-dot">${dot}</span>
        <span class="gen-backend-label">${escapeHtml(b.label)}</span></div>`;
    }).join('');
  } catch (e) {
    list.innerHTML = '<div class="key-empty">加载失败</div>';
  }
}

// 大模型 API 配置加载
async function loadLLMConfig() {
  try {
    const resp = await apiFetch('/api/config/llm');
    const data = await resp.json();
    if (!data.success) return;
    const oaiKey = document.getElementById('openaiKeyInput');
    const oaiBase = document.getElementById('openaiBaseInput');
    const cldKey = document.getElementById('claudeKeyInput');
    const cldBase = document.getElementById('claudeBaseInput');
    if (oaiKey) oaiKey.placeholder = data.openai.key_set
      ? '已配置：' + data.openai.key
      : 'sk-xxxxxxxx（可选，留空则用环境变量 OPENAI_API_KEY）';
    if (oaiBase) oaiBase.value = data.openai.base_url || '';
    if (cldKey) cldKey.placeholder = data.claude.key_set
      ? '已配置：' + data.claude.key
      : 'sk-ant-xxxxxxxx（可选，留空则用环境变量 ANTHROPIC_API_KEY）';
    if (cldBase) cldBase.value = data.claude.base_url || '';
    loadVisionBackends();
  } catch (e) { /* 静默失败 */ }
}

// 通用 Key 输入框保存/显示/隐藏
function setupKeyInput(keyId, baseId, saveField, baseField) {
  const keyInput = document.getElementById(keyId);
  const baseInput = document.getElementById(baseId);
  const saveBtn = document.getElementById(keyId.replace('Input', 'SaveBtn'));
  const toggleBtn = document.getElementById(keyId.replace('Input', 'Toggle'));
  const hint = document.getElementById(keyId.replace('Input', 'Hint'));
  if (!keyInput || !saveBtn) return;
  saveBtn.addEventListener('click', async () => {
    const payload = {};
    payload[saveField] = keyInput.value.trim();
    if (baseInput) payload[baseField] = baseInput.value.trim();
    try {
      const resp = await apiFetch('/api/config/llm', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await resp.json();
      if (data.success) {
        hint.textContent = '✅ 已保存'; hint.style.color = 'var(--success)';
        keyInput.value = ''; loadVisionBackends();
        setTimeout(() => { hint.textContent = ''; }, 2500);
      } else {
        hint.textContent = '❌ ' + (data.error || '保存失败');
        hint.style.color = 'var(--error)';
      }
    } catch (e) {
      hint.textContent = '❌ ' + fetchErrorMessage(e); hint.style.color = 'var(--error)';
    }
  });
  toggleBtn.addEventListener('click', () => {
    const isPwd = keyInput.type === 'password';
    keyInput.type = isPwd ? 'text' : 'password';
    toggleBtn.textContent = isPwd ? '隐藏' : '显示';
  });
}

// MCP API Key（存 localStorage）
function setupMcpApiKey() {
  const input = document.getElementById('mcpApiKeyInput');
  const saveBtn = document.getElementById('mcpApiKeySaveBtn');
  const toggleBtn = document.getElementById('mcpApiKeyToggle');
  const hint = document.getElementById('mcpApiKeyHint');
  if (!input) return;
  const saved = localStorage.getItem('colorflow_mcp_key');
  if (saved) { input.value = saved; input.placeholder = '已配置（' + saved.slice(0,6) + '…）'; }
  saveBtn.addEventListener('click', () => {
    const v = input.value.trim();
    if (v) { localStorage.setItem('colorflow_mcp_key', v); hint.textContent = '✅ 已保存'; }
    else { localStorage.removeItem('colorflow_mcp_key'); hint.textContent = '✅ 已清除'; }
    hint.style.color = 'var(--success)';
    input.value = ''; input.placeholder = 'cfk_xxxxxxxx（可选，留空则 MCP 无鉴权）';
    updateMcpConfig(); setTimeout(() => { hint.textContent = ''; }, 2500);
  });
  toggleBtn.addEventListener('click', () => {
    const isPwd = input.type === 'password';
    input.type = isPwd ? 'text' : 'password';
    toggleBtn.textContent = isPwd ? '隐藏' : '显示';
  });
}

// base64 → Blob
function genBase64ToBlob(b64, type = 'image/png') {
  const bin = atob(b64);
  const len = bin.length;
  const arr = new Uint8Array(len);
  for (let i = 0; i < len; i++) arr[i] = bin.charCodeAt(i);
  return new Blob([arr], { type });
}

// 送流水线：把生成图注入描图 Tab（DataTransfer 注入 file input）
function genInjectToTrace(b64, mode) {
  const traceTab = document.querySelector('.tab[data-tab="trace"]');
  if (traceTab) traceTab.click();
  const blob = genBase64ToBlob(b64);
  const file = new File([blob], 'colorflow_generated.png', { type: 'image/png' });
  const dt = new DataTransfer();
  dt.items.add(file);
  const traceFileEl = document.getElementById('traceFile');
  if (traceFileEl && dt.files) {
    traceFileEl.files = dt.files;
    if (typeof handleFile === 'function') handleFile(file);
  }
  if (mode) {
    const traceModeEl = document.getElementById('traceMode');
    if (traceModeEl) {
      traceModeEl.value = mode;
      if (typeof syncTraceMode === 'function') syncTraceMode();
    }
  }
}

// 生成（任务模式：POST /api/generate/jobs → 轮询 GET /api/generate/jobs/{id}）
const GEN_POLL_INTERVAL = 2000;      // 轮询间隔 2s
const GEN_POLL_TIMEOUT = 180000;     // 前端总超时 3 分钟

function genSleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function genShowError(msg, hint) {
  genResults.innerHTML = `<div class="svg-placeholder" style="color:var(--error)">错误: ${escapeHtml(msg)}${hint ? '（' + escapeHtml(hint) + '）' : ''}</div>`;
}

async function genPollJob(jobId) {
  const deadline = Date.now() + GEN_POLL_TIMEOUT;
  while (Date.now() < deadline) {
    await genSleep(GEN_POLL_INTERVAL);
    try {
      const resp = await apiFetch('/api/generate/jobs/' + encodeURIComponent(jobId));
      const job = await resp.json();
      if (job.status === 'done') {
        if (job.images && job.images.length > 0) {
          genResultsData = job.images;
          renderGenResults(job.images, job.elapsed_ms);
        } else {
          genShowError('生成完成但未返回图像');
        }
        return;
      }
      if (job.status === 'failed') {
        genShowError(job.error || '生成失败', job.retryable ? '可重试或更换后端' : '');
        return;
      }
      if (job.status === 'not_found') {
        genShowError('任务已过期，请重新生成');
        return;
      }
      // queued / running — 更新进度文案
      if (job.progress) {
        genResults.innerHTML = `<div class="svg-placeholder">${escapeHtml(job.progress)}</div>`;
      }
    } catch (e) {
      // 单次轮询失败不中断，继续重试直到总超时
    }
  }
  genShowError('生成超时，请重试');
}

// 注：genBtn 的点击 handler 在下方 S4-C 批量生图段落统一注册（onclick）
// 此处不再用 addEventListener，避免双触发

function renderGenResults(images, elapsedMs) {
  let html = `<div class="gen-results-meta">${images.length} 张 · ${elapsed_ms_label(elapsedMs)}</div>`;
  html += '<div class="gen-grid">';
  images.forEach((img, idx) => {
    const meta = `${escapeHtml(img.backend)} · ${escapeHtml(img.model || '-')} · ${img.width}×${img.height}`;
    html += `<div class="gen-card" data-idx="${idx}">
      <img src="data:image/png;base64,${img.png_base64}" class="gen-thumb" alt="生成图 ${idx + 1}"/>
      <div class="gen-card-meta">${meta}</div>
      <div class="gen-card-actions">
        <button class="btn btn-small" data-act="download">下载 PNG</button>
        <button class="btn btn-small" data-act="cutout-trace">抠图+描图</button>
        <button class="btn btn-small btn-accent" data-act="palette">提取主色&Pantone</button>
      </div>
    </div>`;
  });
  html += '</div>';
  genResults.innerHTML = html;
}

function elapsed_ms_label(ms) {
  if (ms == null) return '';
  if (ms < 1000) return ms + ' ms';
  return (ms / 1000).toFixed(1) + ' s';
}

// 结果区按钮事件委托
if (genResults) {
  genResults.addEventListener('click', e => {
    const btn = e.target.closest('button[data-act]');
    if (!btn) return;
    const card = btn.closest('.gen-card');
    const idx = Number(card.dataset.idx);
    const img = genResultsData[idx];
    if (!img) return;
    const act = btn.dataset.act;
    if (act === 'download') {
      const a = document.createElement('a');
      a.href = 'data:image/png;base64,' + img.png_base64;
      a.download = `colorflow_gen_${idx + 1}.png`;
      a.click();
    } else if (act === 'cutout-trace') {
      // 抠图+描图：注入描图 Tab 并切到 cutout 模式（rembg 抠图后描图，输出透明 SVG）
      genInjectToTrace(img.png_base64, 'cutout');
    } else if (act === 'palette') {
      // 提取主色：注入描图 Tab 并自动触发一键流水线
      genInjectToTrace(img.png_base64, 'color');
      setTimeout(() => {
        const cmb = document.getElementById('colorMatchBtn');
        if (cmb) cmb.click();
      }, 300);
    }
  });
}

// ============================================================
// 行业 Prompt 模板库（Phase 4 · 预制 prompt → GEN）
// ============================================================
const genTplToggle = document.getElementById('genTplToggle');
const genTplBody = document.getElementById('genTplBody');
const genTplSelect = document.getElementById('genTplSelect');
const genTplParams = document.getElementById('genTplParams');
const genTplApply = document.getElementById('genTplApply');
const genTplHint = document.getElementById('genTplHint');

let _genTplData = [];  // 已加载的模板数据

if (genTplToggle) {
  genTplToggle.addEventListener('click', () => {
    const hidden = genTplBody.classList.contains('hidden');
    genTplBody.classList.toggle('hidden');
    genTplToggle.textContent = hidden ? '收起' : '展开';
    if (hidden && _genTplData.length === 0) loadGenTemplates();
  });
}

async function loadGenTemplates() {
  try {
    const resp = await apiFetch('/api/prompt-templates');
    const data = await resp.json();
    if (!data.success) return;
    _genTplData = data.templates || [];
    // 合并自定义模板
    const custom = loadCustomTemplates();
    if (custom.length > 0) _genTplData = [..._genTplData, ...custom];
    renderTplSelect(data.categories || []);
  } catch (e) {
    genTplHint.textContent = '模板加载失败：' + fetchErrorMessage(e);
  }
}

function renderTplSelect(cats) {
  if (!genTplSelect) return;
  let html = '<option value="">— 选择模板 —</option>';
  cats.forEach(cat => {
    const tpls = _genTplData.filter(t => t.category === cat.id);
    if (tpls.length === 0) return;
    html += `<optgroup label="${cat.icon} ${cat.name}">`;
    tpls.forEach(t => {
      html += `<option value="${t.id}">${t.name}</option>`;
    });
    html += '</optgroup>';
  });
  // 自定义模板
  const custom = _genTplData.filter(t => t.category === 'custom');
  if (custom.length > 0) {
    html += '<optgroup label="⭐ 自定义模板">';
    custom.forEach(t => {
      html += `<option value="${t.id}">${t.name}</option>`;
    });
    html += '</optgroup>';
  }
  genTplSelect.innerHTML = html;
}

if (genTplSelect) {
  genTplSelect.addEventListener('change', () => {
    const sel = _genTplData.find(t => t.id === genTplSelect.value);
    if (!sel) {
      genTplParams.innerHTML = '';
      genTplApply.disabled = true;
      genTplHint.textContent = '';
      return;
    }
    // 获取完整模板定义（含 params）
    if (sel.id.startsWith('custom_')) {
      // 自定义模板：直接从 _genTplData 获取
      renderTplParams(sel);
    } else {
      apiFetch('/api/prompt-templates/' + encodeURIComponent(sel.id))
        .then(r => r.json())
        .then(data => {
          if (!data.success) return;
          renderTplParams(data.template);
        })
        .catch(e => { genTplHint.textContent = '模板详情加载失败'; });
    }
  });
}

function renderTplParams(template) {
  const params = template.params || {};
  let html = '';
  for (const [name, def] of Object.entries(params)) {
    const opts = (def.options || []).map(o => `<option value="${o}">${o}</option>`).join('');
    html += `<div class="param-row tpl-param-row">
      <label>${escapeHtml(def.label || name)}</label>
      <select class="tpl-param-select" data-param="${name}">
        <option value="${def.default}">${def.default}</option>
        ${opts}
      </select>
    </div>`;
  }
  html += '<p class="tpl-prompt-preview" id="genTplPreview"></p>';
  genTplParams.innerHTML = html;
  genTplApply.disabled = false;
  // 实时预览（占位符替换）
  genTplParams.querySelectorAll('.tpl-param-select').forEach(sel => {
    sel.addEventListener('change', () => updateTplPreview(template));
  });
  updateTplPreview(template);
}

function updateTplPreview(template) {
  let prompt = template.prompt || '';
  const selects = genTplParams.querySelectorAll('.tpl-param-select');
  const used = {};
  selects.forEach(sel => {
    const val = sel.value;
    used[sel.dataset.param] = val;
    prompt = prompt.replace('{' + sel.dataset.param + '}', val);
  });
  const preview = document.getElementById('genTplPreview');
  if (preview) preview.textContent = '📝 ' + prompt;
  genTplHint.textContent = '点击「应用模板」回填到上方 prompt 框';
}

if (genTplApply) {
  genTplApply.addEventListener('click', async () => {
    const sel = _genTplData.find(t => t.id === genTplSelect.value);
    if (!sel) return;
    // 收集参数
    const params = {};
    genTplParams.querySelectorAll('.tpl-param-select').forEach(s => {
      params[s.dataset.param] = s.value;
    });
    try {
      let resultPrompt;
      if (sel.id.startsWith('custom_')) {
        // 自定义模板：客户端渲染
        resultPrompt = sel.prompt || '';
        genTplParams.querySelectorAll('.tpl-param-select').forEach(s => {
          resultPrompt = resultPrompt.replace('{' + s.dataset.param + '}', s.value);
        });
      } else {
        // 内置模板：服务端渲染
        const formData = new FormData();
        formData.append('template_id', sel.id);
        Object.entries(params).forEach(([k, v]) => formData.append('param_' + k, v));
        const resp = await apiFetch('/api/prompt-templates/render', { method: 'POST', body: formData });
        const data = await resp.json();
        if (!data.success) { genTplHint.textContent = '渲染失败：' + (data.error || ''); return; }
        resultPrompt = data.prompt;
      }
      if (genPrompt) {
        genPrompt.value = resultPrompt;
        genBtn.disabled = false;
      }
      genHint.textContent = '🎨 prompt 已由模板「' + sel.name + '」生成，可直接生成或微调后再生成';
    } catch (e) {
      genTplHint.textContent = '渲染失败：' + fetchErrorMessage(e);
    }
  });
}

if (genTplSelect && !genTplSelect.value) {
  // 初始加载
  loadGenTemplates();
}

// ============================================================
// 设置页初始化：大模型 API + MCP Key
// ============================================================
setupKeyInput('openaiKeyInput', 'openaiBaseInput', 'openai_key', 'openai_base');
setupKeyInput('claudeKeyInput', 'claudeBaseInput', 'claude_key', 'claude_base');
setupMcpApiKey();

// ============================================================
// S4-C: 批量生图 + Prompt 优化 + 参考图库 + 模板市场
// ============================================================

// ── 模式切换（单张/批量）──
let _genMode = 'single';
const genModeBtns = document.querySelectorAll('.gen-mode-btn');
const genPromptLabel = document.getElementById('genPromptLabel');
genModeBtns.forEach(btn => {
  btn.addEventListener('click', () => {
    genModeBtns.forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    _genMode = btn.dataset.mode;
    if (_genMode === 'batch') {
      genPromptLabel.textContent = '生图描述（每行一个 prompt，最多 20 个）';
      genPrompt.placeholder = 'prompt 1\nprompt 2\nprompt 3';
      genPrompt.rows = 6;
    } else {
      genPromptLabel.textContent = '生图描述';
      genPrompt.placeholder = '红色天地盖礼盒，烫金logo，哑光材质，电商白底';
      genPrompt.rows = 3;
    }
  });
});

// ── Prompt 优化按钮 ──
const genOptimizeBtn = document.getElementById('genOptimizeBtn');
const genPromptHint = document.getElementById('genPromptHint');
if (genOptimizeBtn) {
  genOptimizeBtn.addEventListener('click', async () => {
    const prompt = genPrompt.value.trim();
    if (!prompt) { genPromptHint.textContent = '请先输入 prompt'; return; }
    genOptimizeBtn.disabled = true;
    genPromptHint.textContent = '✨ 优化中…';
    try {
      const resp = await apiFetch('/api/prompt/optimize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: prompt, backend: 'auto' }),
      });
      const data = await resp.json();
      if (data.success) {
        genPrompt.value = data.prompt;
        genPromptHint.textContent = `✅ 已优化（${data.backend}）`;
        genPromptHint.style.color = 'var(--success)';
      } else {
        genPromptHint.textContent = '❌ ' + (data.error || '优化失败');
        genPromptHint.style.color = 'var(--error)';
      }
    } catch (e) {
      genPromptHint.textContent = '❌ ' + fetchErrorMessage(e);
      genPromptHint.style.color = 'var(--error)';
    }
    genOptimizeBtn.disabled = false;
    setTimeout(() => { genPromptHint.textContent = ''; }, 4000);
  });
}

// ── 批量生图 ──
// 替换原有的单张生图 handler，支持批量模式
if (genBtn) {
  genBtn.onclick = async () => {
    const promptText = genPrompt.value.trim();
    if (!promptText) { genPromptHint.textContent = '请先输入 prompt'; return; }
    genBtn.disabled = true;
    genBtn.querySelector('.btn-text').textContent = '提交中…';

    if (_genMode === 'batch') {
      // 批量模式
      const prompts = promptText.split('\n').map(s => s.trim()).filter(Boolean);
      if (prompts.length === 0) { genBtn.disabled = false; genBtn.querySelector('.btn-text').textContent = '✨ 生成效果图'; return; }
      genPromptHint.textContent = `📦 批量模式：${prompts.length} 个 prompt`;
      try {
        const formData = new FormData();
        prompts.forEach((p, i) => formData.append('prompts', p));
        formData.append('backend', document.getElementById('genBackend').value);
        formData.append('size', document.getElementById('genSize').value);
        formData.append('n', document.getElementById('genN').value);
        if (genRefFileObj) formData.append('ref_image', genRefFileObj);
        const resp = await apiFetch('/api/generate/batch', { method: 'POST', body: formData });
        const data = await resp.json();
        if (data.success) {
          await pollBatchJob(data.batch_id, prompts);
        } else {
          genPromptHint.textContent = '❌ ' + (data.error || '提交失败');
        }
      } catch (e) {
        genPromptHint.textContent = '❌ ' + fetchErrorMessage(e);
      }
    } else {
      // 单张模式（原有逻辑）
      genPromptHint.textContent = '✨ 生成中…';
      try {
        const formData = new FormData();
        formData.append('prompt', promptText);
        formData.append('backend', document.getElementById('genBackend').value);
        formData.append('size', document.getElementById('genSize').value);
        formData.append('n', document.getElementById('genN').value);
        if (genRefFileObj) formData.append('ref_image', genRefFileObj);
        const resp = await apiFetch('/api/generate/jobs', { method: 'POST', body: formData });
        const data = await resp.json();
        if (data.success) {
          await genPollJob(data.job_id);
        } else {
          genPromptHint.textContent = '❌ ' + (data.error || '提交失败');
        }
      } catch (e) {
        genPromptHint.textContent = '❌ ' + fetchErrorMessage(e);
      }
    }
    genBtn.disabled = false;
    genBtn.querySelector('.btn-text').textContent = '✨ 生成效果图';
  };
}

async function pollBatchJob(batchId, prompts) {
  const deadline = Date.now() + 120000;
  while (Date.now() < deadline) {
    await new Promise(r => setTimeout(r, 2000));
    try {
      const resp = await apiFetch('/api/generate/batch/' + batchId);
      const job = await resp.json();
      if (job.status === 'done') {
        renderBatchResults(job);
        return;
      }
      if (job.status === 'failed') {
        genPromptHint.textContent = '❌ ' + (job.error || '批量失败');
        return;
      }
      genPromptHint.textContent = job.progress || '批量处理中…';
    } catch (e) { /* 继续轮询 */ }
  }
  genPromptHint.textContent = '⏰ 批量超时，请重试';
}

function renderBatchResults(job) {
  const results = document.getElementById('genResults');
  if (!results) return;
  const images = job.images || [];
  const errors = job.errors || [];
  let html = `<div class="gen-batch-summary">📦 ${job.prompt_count} 个 prompt → ${images.length} 张图` +
    (errors.length ? ` · ${errors.length} 个失败` : '') + ` · ${(job.elapsed_ms / 1000).toFixed(1)}s</div>`;
  html += '<div class="gen-grid">';
  images.forEach((img, idx) => {
    const promptLabel = escapeHtml((img.prompt || '').slice(0, 60));
    html += `<div class="gen-card" data-idx="${idx}">
      <img src="data:image/png;base64,${img.png_base64}" class="gen-thumb" alt="批量图 ${idx + 1}"/>
      <div class="gen-card-meta">${escapeHtml(img.backend)} · ${img.width}×${img.height}</div>
      <div class="gen-card-prompt" title="${promptLabel}">${promptLabel}</div>
      <div class="gen-card-actions">
        <button class="btn btn-small" data-act="download">下载 PNG</button>
      </div>
    </div>`;
  });
  html += '</div>';
  if (errors.length) {
    html += '<div class="gen-batch-errors">';
    errors.forEach(e => {
      html += `<div class="gen-batch-error-item">❌ ${escapeHtml((e.prompt || '').slice(0, 40))}: ${escapeHtml(e.error || '')}</div>`;
    });
    html += '</div>';
  }
  results.innerHTML = html;
  results.querySelectorAll('.gen-card-actions .btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const card = btn.closest('.gen-card');
      const idx = Number(card.dataset.idx);
      const img = images[idx];
      if (img) {
        const a = document.createElement('a');
        a.href = 'data:image/png;base64,' + img.png_base64;
        a.download = `batch_${idx + 1}.png`;
        a.click();
      }
    });
  });
}

// ── 参考图库（localStorage）──
const REF_GALLERY_KEY = 'colorflow_ref_gallery';

function loadRefGallery() {
  const items = document.getElementById('genRefGalleryItems');
  const empty = document.getElementById('genRefGalleryEmpty');
  if (!items) return;
  let gallery = [];
  try { gallery = JSON.parse(localStorage.getItem(REF_GALLERY_KEY) || '[]'); } catch (e) {}
  if (gallery.length === 0) {
    items.innerHTML = '<div class="key-empty">暂无保存的参考图</div>';
    return;
  }
  items.innerHTML = gallery.map((item, i) =>
    `<div class="gen-ref-gallery-item" data-idx="${i}" title="点击加载到反向闭环">
      <img src="${item.dataUrl}" alt="参考图 ${i + 1}"/>
      <button class="gen-ref-del" data-del="${i}" title="删除">×</button>
    </div>`
  ).join('');
  items.querySelectorAll('.gen-ref-gallery-item').forEach(el => {
    el.addEventListener('click', e => {
      if (e.target.classList.contains('gen-ref-del')) return;
      const idx = Number(el.dataset.idx);
      const item = gallery[idx];
      if (item && genReverseZone && genReverseFile) {
        // 加载到反向闭环上传区
        const resp = fetch(item.dataUrl).then(r => r.blob());
        resp.then(blob => {
          const file = new File([blob], item.name || 'reference.png', { type: 'image/png' });
          const dt = new DataTransfer();
          dt.items.add(file);
          genReverseFile.files = dt.files;
          genReverseFile.dispatchEvent(new Event('change'));
        });
      }
    });
  });
  items.querySelectorAll('.gen-ref-del').forEach(btn => {
    btn.addEventListener('click', e => {
      e.stopPropagation();
      const idx = Number(btn.dataset.del);
      gallery.splice(idx, 1);
      localStorage.setItem(REF_GALLERY_KEY, JSON.stringify(gallery));
      loadRefGallery();
    });
  });
}

// 保存参考图到图库
const genSaveRefBtn = document.getElementById('genSaveRefBtn');
if (genSaveRefBtn) {
  genSaveRefBtn.addEventListener('click', () => {
    if (!genReverseFile || !genReverseFile.files || !genReverseFile.files[0]) return;
    const file = genReverseFile.files[0];
    const reader = new FileReader();
    reader.onload = e => {
      let gallery = [];
      try { gallery = JSON.parse(localStorage.getItem(REF_GALLERY_KEY) || '[]'); } catch (err) {}
      gallery.push({ name: file.name, dataUrl: e.target.result, size: file.size });
      localStorage.setItem(REF_GALLERY_KEY, JSON.stringify(gallery));
      loadRefGallery();
      genPromptHint.textContent = `💾 已保存到图库（${gallery.length} 张）`;
      genPromptHint.style.color = 'var(--success)';
      setTimeout(() => { genPromptHint.textContent = ''; }, 2500);
    };
    reader.readAsDataURL(file);
  });
}

// 清空图库
const genRefGalleryClear = document.getElementById('genRefGalleryClear');
if (genRefGalleryClear) {
  genRefGalleryClear.addEventListener('click', () => {
    if (confirm('确定清空所有保存的参考图？')) {
      localStorage.removeItem(REF_GALLERY_KEY);
      loadRefGallery();
    }
  });
}

// ── Prompt 模板市场（自定义模板 + 导入/导出）──
const CUSTOM_TPL_KEY = 'colorflow_custom_templates';

function loadCustomTemplates() {
  try { return JSON.parse(localStorage.getItem(CUSTOM_TPL_KEY) || '[]'); }
  catch (e) { return []; }
}

function saveCustomTemplates(tpls) {
  localStorage.setItem(CUSTOM_TPL_KEY, JSON.stringify(tpls));
}

function mergeAllTemplates() {
  return [..._genTplData, ...loadCustomTemplates()];
}

// 自定义模板创建
const genTplCustomBtn = document.getElementById('genTplCustomBtn');
if (genTplCustomBtn) {
  genTplCustomBtn.addEventListener('click', () => {
    const name = prompt('模板名称：', '我的模板');
    if (!name) return;
    const desc = prompt('模板描述（可选）：', '') || '';
    const promptText = prompt('模板 Prompt（用 {} 定义参数）：', 'A {style} {color} gift box with {material} finish');
    if (!promptText) return;
    const params = prompt('参数列表（逗号分隔，格式：name=label）：', 'style=风格,color=主色,material=材质');
    const paramDefs = {};
    if (params) {
      params.split(',').map(s => s.trim()).filter(Boolean).forEach(p => {
        const [name, label] = p.split('=');
        paramDefs[name.trim()] = { label: label || name.trim(), default: '', options: [] };
      });
    }
    const tpls = loadCustomTemplates();
    tpls.push({
      id: 'custom_' + Date.now(),
      name: name,
      category: 'custom',
      description: desc,
      prompt: promptText,
      params: paramDefs,
      param_names: Object.keys(paramDefs),
    });
    saveCustomTemplates(tpls);
    _genTplData = mergeAllTemplates();
    renderTplSelect();
    genPromptHint.textContent = `✅ 已创建自定义模板「${name}」`;
    genPromptHint.style.color = 'var(--success)';
    setTimeout(() => { genPromptHint.textContent = ''; }, 2500);
  });
}

// 导出模板
const genTplExportBtn = document.getElementById('genTplExportBtn');
if (genTplExportBtn) {
  genTplExportBtn.addEventListener('click', () => {
    const tpls = loadCustomTemplates();
    if (tpls.length === 0) { alert('暂无自定义模板可导出'); return; }
    const blob = new Blob([JSON.stringify(tpls, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'colorflow_templates.json';
    a.click();
  });
}

// 导入模板
const genTplImportBtn = document.getElementById('genTplImportBtn');
const genTplImportFile = document.getElementById('genTplImportFile');
if (genTplImportBtn) {
  genTplImportBtn.addEventListener('click', () => genTplImportFile.click());
}
if (genTplImportFile) {
  genTplImportFile.addEventListener('change', e => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = ev => {
      try {
        const imported = JSON.parse(ev.target.result);
        if (!Array.isArray(imported)) throw new Error('格式错误');
        const existing = loadCustomTemplates();
        // 去重（按 id）
        const ids = new Set(existing.map(t => t.id));
        const merged = [...existing, ...imported.filter(t => !ids.has(t.id))];
        saveCustomTemplates(merged);
        _genTplData = mergeAllTemplates();
        renderTplSelect();
        genPromptHint.textContent = `✅ 已导入 ${imported.length} 个模板`;
        genPromptHint.style.color = 'var(--success)';
      } catch (err) {
        genPromptHint.textContent = '❌ 导入失败：' + err.message;
        genPromptHint.style.color = 'var(--error)';
      }
      setTimeout(() => { genPromptHint.textContent = ''; }, 3000);
    };
    reader.readAsText(file);
  });
}
