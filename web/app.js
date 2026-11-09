const $ = (id) => document.getElementById(id);
const state = {matters: [], matter: null, documents: [], doc: null, units: [], page: 1, view: 'original', busy: false, loadId: 0, matterLoadId: 0, citation: null, workspace: 'materials'};
const labels = {ready: '● 已解析', partial: '◐ 待核对', failed: '● 解析失败', pending: '○ 待解析', parsing: '◌ 解析中'};
const escapeHTML = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const prettySize = n => n < 1024 * 1024 ? `${Math.max(1, Math.round(n / 1024))} KB` : `${(n / 1024 / 1024).toFixed(1)} MB`;

async function api(path, options = {}) {
  const response = await fetch(path, {cache: 'no-store', ...options, headers: {'X-MatterLoom': '1', ...options.headers}});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '操作未完成，请重试。');
  return data;
}
const post = (url, data) => api(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)});
function toast(message) { $('toast').textContent = message; $('toast').hidden = false; clearTimeout(toast.timer); toast.timer = setTimeout(() => $('toast').hidden = true, 5000); }
function notice(message, success = false) { $('notice').textContent = message; $('notice').className = `notice${success ? ' success' : ''}`; $('notice').hidden = !message; }
function busy(value) { state.busy = value; document.body.classList.toggle('busy', value); ['choose-files','reparse','use-ocr','new-matter','samples-button','extract-all','add-fact','extraction-mode','external-consent'].forEach(id => $(id).disabled = value); $('file-input').disabled = value; }
function docUrl(suffix = '') { return `/api/matters/${state.matter.id}/documents/${state.doc.id}${suffix}`; }

async function refreshMatters() {
  const data = await api('/api/matters');
  state.matters = data.matters;
  $('ocr-status').textContent = data.ocr_available ? '已配置，需核验' : '未配置';
  $('matter-count').textContent = state.matters.length;
  $('matter-list').innerHTML = state.matters.map(m => `<button class="matter-item ${state.matter?.id === m.id ? 'active' : ''}" data-matter="${m.id}" aria-pressed="${state.matter?.id === m.id}"><span class="matter-symbol">▱</span><div><strong>${escapeHTML(m.name)}</strong><small>${m.document_count} 份材料${m.sample_key ? ' · 模拟事项' : ''}</small></div></button>`).join('');
  document.querySelectorAll('[data-matter]').forEach(el => el.addEventListener('click', () => { if (!state.busy) selectMatter(el.dataset.matter).catch(e => toast(e.message)); }));
}

async function selectMatter(id) {
  const matterLoadId = ++state.matterLoadId;
  state.loadId++;
  const data = await api(`/api/matters/${id}/documents`);
  if (matterLoadId !== state.matterLoadId) return;
  state.matter = data.matter; state.documents = data.documents; state.doc = null; state.units = [];
  state.citation = null; $('external-consent').checked = false;
  localStorage.setItem('matterloom-last-matter', id);
  $('welcome').hidden = true; $('workspace').hidden = false;
  $('matter-title').textContent = state.matter.name;
  $('matter-description').textContent = state.matter.description || '将相关材料汇集在此，逐份查看并核对原文。';
  $('breadcrumb').textContent = '事项材料';
  $('file-search').value = ''; notice('');
  renderFiles(); showEmptyReader(); await refreshMatters();
  if (matterLoadId !== state.matterLoadId) return;
  await refreshFacts();
  if (matterLoadId !== state.matterLoadId) return;
  if (state.documents.length) await selectDocument(state.documents[0].id);
  setWorkspace(state.workspace);
}
async function refreshDocuments() {
  if (!state.matter) return;
  const data = await api(`/api/matters/${state.matter.id}/documents`);
  state.documents = data.documents; renderFiles();
}
function renderFiles() {
  const docs = state.documents;
  $('stat-docs').innerHTML = `${docs.length}<small>份</small>`;
  $('stat-ready').innerHTML = `${docs.filter(d => d.status === 'ready').length}<small>份</small>`;
  $('stat-review').innerHTML = `${docs.filter(d => d.status !== 'ready').length}<small>份</small>`;
  $('stat-pages').innerHTML = `${docs.reduce((n,d) => n + (d.page_count || 0), 0)}<small>页</small>`;
  $('tab-count').textContent = docs.length; $('file-count').textContent = `${docs.length} 份`;
  const query = $('file-search').value.trim().toLowerCase();
  const filtered = docs.filter(d => d.name.toLowerCase().includes(query));
  $('file-list').innerHTML = filtered.length ? filtered.map(d => `<button class="file-item ${d.id === state.doc?.id ? 'active' : ''}" data-doc="${d.id}" aria-pressed="${d.id === state.doc?.id}"><span class="file-glyph ${d.kind}">${d.kind === 'pdf' ? 'PDF' : 'DOC'}</span><span class="file-info"><strong>${escapeHTML(d.name)}</strong><span class="file-meta"><span>${d.kind === 'pdf' && d.page_count ? `${d.page_count} 页 · ` : ''}${prettySize(d.bytes)}</span><span class="badge ${d.status}">${labels[d.status] || '待检查'}</span></span></span></button>`).join('') : `<p class="file-empty">${query ? '没有匹配的文件。' : '还没有材料。<br>上传文件后，它们会保存在这里。'}</p>`;
  document.querySelectorAll('[data-doc]').forEach(el => el.addEventListener('click', () => selectDocument(el.dataset.doc).catch(e => toast(e.message))));
}
function showEmptyReader() { $('reader-empty').hidden = false; $('reader').hidden = true; }
async function selectDocument(id) {
  const loadId = ++state.loadId;
  const data = await api(`/api/matters/${state.matter.id}/documents/${id}/units`);
  if (loadId !== state.loadId) return;
  state.doc = data.document; state.units = data.units; state.page = 1;
  state.citation = null;
  state.view = state.doc.kind === 'pdf' ? 'original' : 'text';
  $('reader-empty').hidden = true; $('reader').hidden = false;
  $('reader-title').textContent = state.doc.name;
  $('reader-kind').textContent = state.doc.kind === 'pdf' ? 'PDF DOCUMENT' : 'WORD DOCUMENT';
  $('download-original').href = docUrl('/original');
  $('reader-warning').innerHTML = [state.doc.error, ...state.doc.warnings].filter(Boolean).map(t => `<p>${escapeHTML(t)}</p>`).join('');
  $('reader-warning').hidden = !$('reader-warning').textContent;
  $('page-select').innerHTML = Array.from({length: state.doc.page_count || 0}, (_,i) => `<option value="${i+1}">第 ${i+1} 页</option>`).join('');
  $('page-total').textContent = `/ ${state.doc.page_count || 0}`;
  $('view-original').hidden = state.doc.kind !== 'pdf';
  renderFiles(); renderReader();
}
function renderReader() {
  if (!state.doc) return;
  const pdf = state.doc.kind === 'pdf';
  const unit = state.units.find(u => u.page_number === state.page);
  $('active-citation').hidden = !state.citation;
  if (state.citation) $('active-citation').textContent = `${state.citation.locator} · ${state.citation.stale ? '原文已变化，以下是此前保存的引用' : '引用原文'}：${state.citation.quote}`;
  $('page-controls').hidden = !pdf || !state.doc.page_count;
  $('page-select').value = state.page;
  $('page-prev').disabled = state.page <= 1;
  $('page-next').disabled = state.page >= (state.doc.page_count || 0);
  $('view-original').classList.toggle('selected', state.view === 'original');
  $('view-text').classList.toggle('selected', state.view === 'text');
  $('page-view').hidden = !pdf || state.view !== 'original' || !state.doc.page_count;
  $('text-view').hidden = pdf && state.view !== 'text' && !!state.doc.page_count;
  if (pdf && state.doc.page_count && state.view === 'original') {
    $('page-image').alt = `${state.doc.name}，文件第 ${state.page} 页`;
    $('page-image').src = docUrl(`/pages/${state.page}`);
  }
  $('page-note').textContent = pdf ? `使用 PDF 文件页序号，与纸面印刷页码可能不同。${unit?.note ? ' ' + unit.note : ''}` : '按正文段落和表格单元格定位；DOCX 不提供固定页码。排版请下载原件查看。';
  if (pdf) {
    $('text-view').innerHTML = `<pre>${sourceMarkup(unit)}</pre>`;
  } else {
    $('text-view').innerHTML = state.units.length ? state.units.map(u => `<section class="source-block" data-unit="${escapeHTML(u.id)}"><small>${escapeHTML(u.locator)}</small><p>${sourceMarkup(u)}</p></section>`).join('') : '<p>暂无可用文字，请下载原件核对。</p>';
  }
  $('source-method').textContent = unit?.method === 'ocr' ? '本机 OCR · 请核对原页' : pdf ? '原文文字层 · 本机解析' : '正文与表格 · 本机解析';
}
function sourceMarkup(unit) {
  if (!unit) return '暂无可用文字。请查看原件或重新解析。';
  const citation = state.citation;
  const index = citation?.unit_id === unit.id && !citation.stale ? unit.text.indexOf(citation.quote) : -1;
  if (index < 0) return escapeHTML(unit.text);
  return escapeHTML(unit.text.slice(0,index)) + '<mark>' + escapeHTML(citation.quote) + '</mark>' + escapeHTML(unit.text.slice(index + citation.quote.length));
}
function setPage(page) { state.page = page; renderReader(); $('page-view').scrollTop = 0; $('text-view').scrollTop = 0; }

async function runBatch(items, operation) {
  if (state.busy) return;
  busy(true); notice(''); $('progress-panel').hidden = false;
  $('upload-progress').max = items.length; $('upload-progress').value = 0;
  let completed = 0, duplicate = 0;
  const problems = [];
  try {
    for (let i = 0; i < items.length; i++) {
      $('progress-message').textContent = `正在保存并解析：${items[i].name}`;
      $('progress-count').textContent = `${i + 1} / ${items.length}`;
      try {
        const result = await operation(items[i]);
        if (result.duplicate) duplicate++; else completed++;
        if (result.document.status !== 'ready') problems.push(`${items[i].name}：${labels[result.document.status]}`);
      } catch (error) { problems.push(`${items[i].name}：${error.message}`); }
      $('upload-progress').value = i + 1;
      await refreshDocuments();
    }
    await refreshMatters();
    await refreshFacts();
    notice(`已保存 ${completed} 份材料${duplicate ? `；${duplicate} 份重复文件已跳过` : ''}。${problems.length ? '\n' + problems.join('\n') : ' 可以开始查看原文。'}`, !problems.length);
    if (state.documents.length) await selectDocument(state.doc?.id || state.documents[0].id);
  } finally { busy(false); $('progress-panel').hidden = true; $('file-input').value = ''; }
}
async function upload(files) {
  if (!state.matter || state.busy || !files.length) return;
  await runBatch([...files], file => {
    if (!/\.(pdf|docx)$/i.test(file.name)) throw new Error('仅支持 PDF 和 DOCX。');
    if (!file.size || file.size > 20 * 1024 * 1024) throw new Error('文件为空或超过 20 MB。');
    const form = new FormData(); form.append('file', file); form.append('ocr', $('use-ocr').checked);
    return api(`/api/matters/${state.matter.id}/documents`, {method: 'POST', body: form});
  });
}
async function showSamples() {
  const data = await api('/api/samples');
  $('sample-cards').innerHTML = data.matters.map(c => `<article class="sample-card"><h3>${escapeHTML(c.name)}</h3><p>${escapeHTML(c.description)}</p><button class="small-button" data-sample="${escapeHTML(c.key)}">载入 ${c.files.length} 份材料 →</button></article>`).join('');
  document.querySelectorAll('[data-sample]').forEach(el => el.addEventListener('click', async () => {
    try {
      $('samples-dialog').close();
      const result = await post('/api/samples/import', {key: el.dataset.sample});
      await selectMatter(result.id);
      await runBatch(result.files, file => post(`/api/matters/${result.id}/sample`, {name: file.name, ocr: $('use-ocr').checked}));
    } catch (error) { toast(error.message); busy(false); }
  }));
  $('samples-dialog').showModal();
}
function showNew() { $('matter-form').reset(); $('form-error').textContent = ''; $('matter-dialog').showModal(); }
['new-matter','welcome-new'].forEach(id => $(id).addEventListener('click', showNew));
['samples-button','welcome-samples'].forEach(id => $(id).addEventListener('click', () => showSamples().catch(e => toast(e.message))));
$('cancel-matter').addEventListener('click', () => $('matter-dialog').close());
$('close-samples').addEventListener('click', () => $('samples-dialog').close());
$('matter-form').addEventListener('submit', async event => {
  event.preventDefault();
  const button = event.submitter; button.disabled = true;
  try { const result = await post('/api/matters', Object.fromEntries(new FormData(event.target))); $('matter-dialog').close(); await selectMatter(result.id); }
  catch (error) { $('form-error').textContent = error.message; }
  finally { button.disabled = false; }
});
$('choose-files').addEventListener('click', () => $('file-input').click());
$('file-input').addEventListener('change', event => upload(event.target.files).catch(e => toast(e.message)));
['dragover','drop'].forEach(name => window.addEventListener(name, e => e.preventDefault()));
$('upload-zone').addEventListener('dragover', () => $('upload-zone').classList.add('dragover'));
$('upload-zone').addEventListener('dragleave', () => $('upload-zone').classList.remove('dragover'));
$('upload-zone').addEventListener('drop', event => { $('upload-zone').classList.remove('dragover'); upload(event.dataTransfer.files).catch(e => toast(e.message)); });
$('file-search').addEventListener('input', renderFiles);
$('view-original').addEventListener('click', () => { state.view = 'original'; renderReader(); });
$('view-text').addEventListener('click', () => { state.view = 'text'; renderReader(); });
$('page-prev').addEventListener('click', () => setPage(state.page - 1));
$('page-next').addEventListener('click', () => setPage(state.page + 1));
$('page-select').addEventListener('change', e => setPage(Number(e.target.value)));
$('reparse').addEventListener('click', async () => {
  if (state.busy || !state.doc) return;
  const docId = state.doc.id; const url = docUrl('/parse'); busy(true); toast('正在重新解析，请稍候。');
  try { await post(url, {ocr: $('use-ocr').checked}); await refreshDocuments(); await selectDocument(docId); await refreshMatters(); await refreshFacts(); toast('解析结果已更新。'); }
  catch (e) { toast(e.message); } finally { busy(false); }
});
$('page-image').addEventListener('error', () => { $('page-note').textContent = '页面预览未成功加载，请重试或下载原件查看。'; });
window.addEventListener('beforeunload', e => { if (state.busy) { e.preventDefault(); e.returnValue = ''; } });
document.addEventListener('DOMContentLoaded', () => {
  (async () => { await refreshMatters(); const previous = localStorage.getItem('matterloom-last-matter'); const id = state.matters.find(m => m.id === previous)?.id || state.matters[0]?.id; if (id) await selectMatter(id); })().catch(e => toast(e.message));
});
