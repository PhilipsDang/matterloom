const kindNames = {person:'人物',organization:'机构',amount:'金额',date:'日期',event:'事件',claim:'主张',question:'待确认问题'};
const statusNames = {pending:'待审核',confirmed:'已确认',uncertain:'不确定',excluded:'已删除'};
const reviewState = {facts:[], runs:[], config:{}, editing:null, selected:null, matterId:null};
const factBase = () => `/api/matters/${state.matter.id}/facts`;
function informationText(value) {
  return `类型：${kindNames[value.kind]}\n标题：${value.label}\n内容：${value.value}\n规范值：${value.normalized_value || '未填写'}\n不确定处：${value.uncertainty || '未填写'}`;
}
function historyText(record) {
  if (!record) return '尚无记录';
  return `${informationText(record.current)}\n状态：${statusNames[record.status]}\n审核备注：${record.reviewer_note || '未填写'}\n引用：\n${record.evidence.map(e=>`${e.document_name} · ${e.locator}\n${e.quote}`).join('\n\n')}`;
}

function setWorkspace(view) {
  state.workspace = view;
  const reviewing = view === 'facts';
  $('facts-panel').hidden = !reviewing; $('extraction-toolbar').hidden = !reviewing;
  document.querySelector('.file-panel').hidden = reviewing;
  $('upload-zone').hidden = reviewing;
  $('document-layout').classList.toggle('review-layout', reviewing);
  $('materials-tab').classList.toggle('active-tab', !reviewing); $('facts-tab').classList.toggle('active-tab', reviewing);
  $('materials-tab').setAttribute('aria-pressed', !reviewing); $('facts-tab').setAttribute('aria-pressed', reviewing);
  $('breadcrumb').textContent = reviewing ? '事实审核' : '事项材料';
}

async function refreshFacts() {
  if (!state.matter) return;
  const id = state.matter.id;
  const data = await api(`/api/matters/${id}/facts`);
  if (state.matter?.id !== id) return;
  if (reviewState.matterId !== id) {
    reviewState.selected = null; $('fact-search').value = ''; $('fact-kind').value = ''; $('fact-status').value = 'active';
  }
  Object.assign(reviewState, data, {matterId:id});
  renderFacts(); updateMode();
}

function renderFacts() {
  const facts = reviewState.facts;
  const active = facts.filter(f => f.status !== 'excluded');
  $('facts-count').textContent = active.length;
  $('review-summary').textContent = `${active.length} 条记录 · ${active.filter(f=>f.eligible).length} 条已确认且引用有效 · ${active.filter(f=>f.status==='uncertain').length} 条不确定`;
  const search = $('fact-search').value.trim().toLowerCase(), kind = $('fact-kind').value, status = $('fact-status').value;
  const filtered = facts.filter(f => (!kind || f.current.kind === kind) &&
    (status === 'all' || (status === 'active' ? f.status !== 'excluded' : status === 'stale' ? !f.source_valid : f.status === status)) &&
    (!search || JSON.stringify([f.current, f.evidence, f.reviewer_note]).toLowerCase().includes(search)));
  $('fact-list').innerHTML = filtered.length ? filtered.map(f => `<article class="fact-card ${f.id===reviewState.selected?'selected':''}">
    <div class="fact-card-top"><span class="kind-pill">${kindNames[f.current.kind]}</span><span class="review-status ${f.status}">${statusNames[f.status]}</span>${!f.source_valid?'<span class="stale-label">原文变化</span>':''}</div>
    <h3>${escapeHTML(f.current.label)}</h3><p class="fact-value">${escapeHTML(f.current.value)}</p>${f.current.normalized_value?`<p class="normalized">规范值：${escapeHTML(f.current.normalized_value)}</p>`:''}
    ${f.current.uncertainty?`<p class="uncertainty">${escapeHTML(f.current.uncertainty)}</p>`:''}
    ${f.evidence.map((e,i)=>`<button class="citation-button" data-source-fact="${f.id}" data-evidence="${i}"><span>${escapeHTML(e.document_name)} · ${escapeHTML(e.locator)} ↗</span><q>${escapeHTML(e.quote)}</q>${e.method==='ocr'?'<small>OCR 原文 · 请核对图片</small>':''}</button>`).join('')}
    ${f.reviewer_note?`<p class="review-note">审核备注：${escapeHTML(f.reviewer_note)}</p>`:''}
    <div class="fact-actions"><button class="small-button" data-edit-fact="${f.id}">修改 / 审核</button><button class="text-button" data-history-fact="${f.id}">修改记录</button></div></article>`).join('') : '<div class="fact-empty"><h3>让每条信息，都有出处。</h3><p>点击上方“提取事项信息”生成候选；也可以选定原文，手动补充遗漏的信息。</p><p>筛选后没有结果时，请调整筛选条件。</p></div>';
  document.querySelectorAll('[data-source-fact]').forEach(button=>button.addEventListener('click',()=>locateFact(button.dataset.sourceFact,Number(button.dataset.evidence)).catch(e=>toast(e.message))));
  document.querySelectorAll('[data-edit-fact]').forEach(button=>button.addEventListener('click',()=>openFact(button.dataset.editFact)));
  document.querySelectorAll('[data-history-fact]').forEach(button=>button.addEventListener('click',()=>showHistory(button.dataset.historyFact).catch(e=>toast(e.message))));
  const runNames = {ready:'已完成',partial:'部分完成',failed:'失败',running:'提取中'};
  $('run-list').innerHTML = reviewState.runs.length ? reviewState.runs.map(r=>`<article><strong>${escapeHTML(r.document_name)}</strong><p>${runNames[r.status]} · ${r.mode==='local'?'本地规则':'GLM'} · 新增 ${r.added} / 重复 ${r.skipped}</p><p>${escapeHTML(r.engine)} · ${escapeHTML(new Date(r.created_at).toLocaleString())}</p>${r.details.rejected?`<p class="error">${r.details.rejected} 条模型候选未通过字段或引用校验，未保存。</p>`:''}${r.details.source_partial?'<p>原文件解析不完整，结果仅覆盖可用文字。</p>':''}${r.error?`<p class="error">${escapeHTML(r.error)}</p>`:''}</article>`).join('') : '<p>尚未提取。扫描件无可用文字时会明确提示，不能据此推断其中没有事实。</p>';
}

async function locateFact(id, index) {
  const fact = reviewState.facts.find(f=>f.id===id);
  if (!fact) return;
  const source = fact.evidence[index], matterId = state.matter.id;
  reviewState.selected = id; renderFacts();
  await selectDocument(source.document_id);
  if (state.matter?.id !== matterId || state.doc?.id !== source.document_id || reviewState.selected !== id) return;
  state.citation = {...source, stale:!fact.source_valid}; state.page = source.page_number || 1; state.view = 'text';
  renderReader();
  const mark = $('text-view').querySelector('mark');
  if (mark) mark.scrollIntoView({block:'nearest'});
  if (window.innerWidth < 781) document.querySelector('.reader-panel').scrollIntoView({block:'start'});
}

function updateMode() {
  const glm = $('extraction-mode').value === 'glm';
  $('external-consent-label').hidden = !glm;
  $('mode-description').textContent = glm ? (reviewState.config.glm_configured ? `使用 ${reviewState.config.model}；逐份发送解析文字，引用校验通过后进入待审核。` : 'GLM 尚未配置。按英文 README 设置密钥和具体模型标识并重启服务，或使用本地模式。') : '本地模式识别明确的名称、日期、金额与语句线索，可能遗漏或误分类，均需人工审核。';
}

async function extractAll() {
  if (state.busy || !state.matter) return;
  const mode = $('extraction-mode').value;
  if (mode==='glm' && !reviewState.config.glm_configured) return toast('请先按 README 配置 GLM，或选择本地提取。');
  if (mode==='glm' && !$('external-consent').checked) return toast('请先勾选文字发送许可，或选择本地提取。');
  if (!state.documents.length) return toast('请先在“事项材料”上传或载入文件。');
  busy(true); notice(''); $('extraction-progress').hidden = false;
  let added = 0, skipped = 0; const problems = [];
  const docs = [...state.documents], matterId = state.matter.id;
  try {
    for (let index=0; index<docs.length; index++) {
      const doc = docs[index];
      $('extraction-progress').textContent = `${index+1} / ${docs.length} · 正在提取 ${doc.name}${mode==='glm'?'（长文件可能需要几分钟）':''}`;
      try {
        const result = await post(`/api/matters/${matterId}/documents/${doc.id}/extract`, {mode,allow_external:mode==='glm' && $('external-consent').checked});
        added += result.added; skipped += result.skipped;
        if (result.status==='partial') problems.push(`${doc.name}：覆盖不完整或部分候选未通过校验，请查看提取记录。`);
      } catch(error) { problems.push(`${doc.name}：${error.message}`); }
      await refreshFacts();
    }
    notice(`新增 ${added} 条待审核信息；跳过 ${skipped} 条重复记录，已有修改已保留。${problems.length?'\n'+problems.join('\n'):''}`,!problems.length);
  } finally { busy(false); $('extraction-progress').hidden = true; }
}

function openFact(id=null) {
  if (state.busy) return;
  const fact = id ? reviewState.facts.find(f=>f.id===id) : null;
  if (!fact && !state.units.some(u=>u.text.trim())) return toast('请先在“事项材料”选择一份有可用文字的文件，再手动补充。');
  reviewState.editing = fact;
  $('fact-form').reset(); $('fact-error').textContent = '';
  $('fact-dialog-title').textContent = fact?'审核信息':'从当前文件补充信息';
  $('edit-kind').innerHTML = Object.entries(kindNames).map(([value,label])=>`<option value="${value}">${label}</option>`).join('');
  $('edit-kind').value = fact?.current.kind || 'event';
  for (const [id,key] of [['edit-label','label'],['edit-value','value'],['edit-normalized','normalized_value'],['edit-uncertainty','uncertainty']]) $(id).value = fact?.current[key] || '';
  $('edit-status').value = fact?.status || 'pending'; $('edit-note').value = fact?.reviewer_note || '';
  $('manual-evidence').hidden = !!fact; $('review-fields').hidden = !fact; $('original-details').hidden = !fact;
  $('edit-evidence').innerHTML = fact ? fact.evidence.map(e=>`<p><strong>${escapeHTML(e.document_name)} · ${escapeHTML(e.locator)}</strong><br>${escapeHTML(e.quote)}</p>`).join('') + (!fact.source_valid?'<p class="error">原文已变化或不可用。请重新提取，审核新记录后将这条旧记录标为已删除；当前不能确认。</p>':'') : `<p>来源：${escapeHTML(state.doc.name)}。保存后进入待审核。</p>`;
  $('original-fact').textContent = fact ? informationText(fact.original) : '';
  $('save-fact').textContent = fact?.status === 'confirmed' ? '保存并确认' : '保存';
  if (!fact) {
    $('manual-unit').innerHTML = state.units.filter(u=>u.text.trim()).map(u=>`<option value="${escapeHTML(u.id)}">${escapeHTML(u.locator)}</option>`).join('');
    const visible = state.units.find(u=>u.page_number===state.page && u.text.trim());
    if (visible) $('manual-unit').value = visible.id;
    fillManualQuote();
  }
  $('fact-dialog').showModal();
}
function fillManualQuote() { $('manual-quote').value = state.units.find(u=>u.id===$('manual-unit').value)?.text.slice(0,1600) || ''; }

$('fact-form').addEventListener('submit',async event=>{
  event.preventDefault(); const button=event.submitter; button.disabled=true;
  try {
    const data={kind:$('edit-kind').value,label:$('edit-label').value,value:$('edit-value').value,normalized_value:$('edit-normalized').value.trim() || null,uncertainty:$('edit-uncertainty').value};
    const fact=reviewState.editing;
    if (fact) await post(`${factBase()}/${fact.id}`,{...data,version:fact.version,status:$('edit-status').value,reviewer_note:$('edit-note').value});
    else await post(factBase(),{...data,evidence:[{unit_id:$('manual-unit').value,quote:$('manual-quote').value}]});
    $('fact-dialog').close(); await refreshFacts(); toast('已保存，原始提取和修改记录均已保留。');
  } catch(error) { $('fact-error').textContent=error.message; }
  finally { button.disabled=false; }
});

async function showHistory(id) {
  const matterId=state.matter.id;
  const data=await api(`${factBase()}/${id}/history`);
  if(state.matter?.id!==matterId) return;
  const actions={review:'人工审核',extracted:'自动提取',manual_add:'手动补充',source_changed:'原文变化，自动退回不确定'};
  $('fact-history').innerHTML=data.history.map(h=>`<article class="history-entry"><strong>${actions[h.action] || escapeHTML(h.action)} · 版本 ${h.after.version}</strong><small>${escapeHTML(new Date(h.created_at).toLocaleString())}</small><p>${escapeHTML(h.after.current.label)}：${escapeHTML(h.after.current.value)}</p><p>${statusNames[h.after.status]}${h.after.reviewer_note?' · '+escapeHTML(h.after.reviewer_note):''}</p><details><summary>查看修改前后</summary><h4>修改前</h4><pre>${escapeHTML(historyText(h.before))}</pre><h4>修改后</h4><pre>${escapeHTML(historyText(h.after))}</pre></details></article>`).join('');
  $('history-dialog').showModal();
}

$('materials-tab').addEventListener('click',()=>setWorkspace('materials'));
$('facts-tab').addEventListener('click',()=>setWorkspace('facts'));
['fact-kind','fact-status'].forEach(id=>$(id).addEventListener('change',renderFacts));
$('fact-search').addEventListener('input',renderFacts);
$('extraction-mode').addEventListener('change',()=>{ $('external-consent').checked=false; updateMode(); });
$('extract-all').addEventListener('click',()=>extractAll().catch(e=>toast(e.message)));
$('add-fact').addEventListener('click',()=>openFact());
$('manual-unit').addEventListener('change',fillManualQuote);
$('cancel-fact').addEventListener('click',()=>$('fact-dialog').close());
$('edit-status').addEventListener('change',()=>{ $('save-fact').textContent = $('edit-status').value === 'confirmed' ? '保存并确认' : '保存'; });
$('close-history').addEventListener('click',()=>$('history-dialog').close());
