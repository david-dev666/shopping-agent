import { PLATFORMS, offerKey, money, escapeHtml as h, safeUrl, emptyFilters, filterOffers, orderOffers, validTopPick, readRecent, salesLabel, provenance, moneyRange } from './helpers.mjs?v=20261017-identity2';
import { streamChat } from './stream.mjs';
import { evidencePanel, evidenceSummary } from './evidence.mjs';

const $ = selector => document.querySelector(selector);
const icon = name => `<svg class="icon" aria-hidden="true"><use href="#i-${name}"/></svg>`;
const state = { mode: 'agent', base: null, data: null, filters: emptyFilters(), applied: '', sort: 'recommended', selected: new Set(), busy: false, request: null, config: null, query: '', budget: null, preference: '', progress: {}, formErrors: {} };
const nodeNames = { intent: '理解需求', research: '跨平台采集', match: '相关性标注', filters: '筛选候选', decide: '评估与排序', recommend: '生成建议' };
const filtersSignature = () => JSON.stringify({ filters: state.filters, budget: state.budget, preference: state.preference });
const isStale = () => state.applied !== filtersSignature();
const visible = () => state.base ? filterOffers(state.base.offers, state.filters, state.base.specs) : [];
const badge = platform => `<span class="platform-badge ${h(platform)}">${h(PLATFORMS[platform] || platform)}</span>`;
function image(o) {
  const src = safeUrl(o.image);
  return `<div class="product-image" role="img" aria-label="${src ? '商品图片' : '暂无商品图片'}"><span class="image-placeholder" aria-hidden="true">${icon('bag')}<small>${src ? '图片暂不可用' : '暂无图片'}</small></span>${src ? `<img src="${h(src)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : ''}</div>`;
}
function productTitle(title, tag, className = '') {
  const text = h(title || '未提供商品标题');
  const heading = `<${tag} class="${className}">${text}</${tag}>`;
  return (title || '').length > 32
    ? `<details class="product-title"><summary title="展开或收起完整商品标题">${heading}<span class="title-toggle" aria-hidden="true">⌄</span></summary></details>`
    : heading;
}
function dateLabel(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '采集时间未知' : date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
}
function feedback(message = '', kind = 'info', retry = false) {
  $('#feedback').innerHTML = message ? `<div class="notice ${kind}"><span>${h(message)}</span>${retry ? '<button type="button" class="button small quiet" data-action="retry">重试查询</button>' : ''}</div>` : '';
}
function renderEnvironment() {
  $('#environment').innerHTML = state.base?.demo
    ? '<div class="notice sample-notice"><span><strong>正在查看样例</strong> · 小米手环9的固定快照，不代表当前价格。</span><button type="button" class="button small quiet" data-action="refresh">真实查询该商品</button></div>' : '';
}
async function loadStatus() {
  try {
    const response = await fetch('/api/status', { signal: AbortSignal.timeout(5000) });
    if (!response.ok) throw new Error('status');
    state.config = await response.json();
    $('#connection').title = '查看数据源与查询方式';
  } catch { $('#connection').title = '配置状态暂不可用，点击重试'; }
}
function showSources() {
  const config = state.config;
  $('#source-content').innerHTML = `<p class="source-intro">默认查询会采集平台报价。浏览器采集需要本机扩展和相应平台登录状态，配置成功不代表平台当前可访问。</p><div class="source-list">${Object.entries(PLATFORMS).map(([p,name]) => {
    const source = config?.sources?.find(s => s.platform === p);
    return `<div><strong>${name}</strong><span>${source ? source.source === 'api' ? '联盟 API 已配置' : '浏览器采集 · 需本机登录' : config ? '未配置' : '状态暂不可用'}</span></div>`;
  }).join('')}</div><div class="source-explainer"><h3>推荐如何生成</h3><p>${config?.llm_configured ? '已配置语义模型；不可用时自动降级为规则排序。' : '当前使用规则排序，配置语义模型后可理解更多选购偏好。'} 实际使用的方式会显示在结果中。</p><h3>为什么有时返回很快</h3><p>直接比价会复用 5 分钟内的相同查询，并标记“缓存报价”。点击“重新采集”可跳过缓存。智能选购目前每次执行完整链路，不使用这层缓存。</p><h3>样例与真实查询</h3><p>只有主动点击“体验选购样例”才展示固定快照；真实查询失败时会显示失败原因，不会换成样例数据。</p></div>`;
  $('#source-dialog').showModal();
}
$('#connection').addEventListener('click', async () => { if (!state.config) await loadStatus(); showSources(); });
function renderRecent() {
  let recent = [];
  try { recent = readRecent(localStorage); } catch { /* 浏览器禁用存储时正常查询 */ }
  $('#recent').innerHTML = recent.length ? `<span>最近查过</span>${recent.map(q => `<button type="button" data-example="${h(q)}">${h(q)}</button>`).join('')}` : '';
}
function remember(query) {
  try { localStorage.setItem('shopping-agent:recent', JSON.stringify([query, ...readRecent(localStorage).filter(q => q !== query)].slice(0, 5))); } catch { /* 存储为可选能力 */ }
  renderRecent();
}
function setBusy(busy, refining = false, source = 'live') {
  state.busy = busy;
  document.body.classList.toggle('is-busy', busy);
  $('#search-submit').disabled = busy;
  $('#loading').hidden = !busy;
  $('#welcome').hidden = busy || !!state.base;
  $('#workspace').hidden = !state.base;
  $('#workspace').inert = busy;
  $('#workspace').setAttribute('aria-busy', String(busy));
  $('#loading-title').textContent = source === 'sample' ? '正在打开选购样例' : refining ? '正在更新推荐' : state.mode === 'agent' ? '正在理解你的需求' : '正在查询平台报价';
  $('#loading-description').textContent = source === 'sample' ? '读取固定快照，不进行实时采集或模型调用。' : refining ? '复用已有报价，按照新预算和偏好重新评估。' : state.mode === 'agent' ? '进度来自实际执行节点，平台加载可能需要一些时间。' : '正在查询平台报价；若命中缓存，会在结果中明确标注。';
  $('#run-progress').hidden = source === 'sample' || refining || state.mode !== 'agent';
  document.querySelectorAll('[data-mode], [data-example], [data-action="sample"]').forEach(button => button.disabled = busy);
}
function renderProgress(event) {
  if (event) state.progress[event.node] = event;
  $('#run-progress').innerHTML = Object.entries(nodeNames).map(([key, name], index) => {
    const step = state.progress[key];
    const status = step?.status || 'pending';
    return `<li class="${status}"><svg class="progress-mark" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="11"/>${status === 'complete' ? '<path d="m7 12 3.2 3.2L17 8.5"/>' : `<text x="12" y="12" text-anchor="middle" dominant-baseline="central">${index + 1}</text>`}</svg><span class="progress-name">${name}</span><small>${status === 'complete' ? `${(step.elapsed_ms / 1000).toFixed(1)}s` : status === 'running' ? '进行中' : '待执行'}</small></li>`;
  }).join('');
  if (event?.status === 'running') $('#loading-title').textContent = `${nodeNames[event.node] || '执行'}中`;
}
async function post(path, body, signal) {
  const response = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = typeof data.detail === 'string' ? data.detail : response.status === 422 ? '输入格式有误，请检查搜索词和价格区间' : `请求失败（${response.status}）`;
    throw new Error(message);
  }
  return data;
}
async function search(query, refining = false, options = {}) {
  if (state.busy || !query.trim()) return;
  if (refining && ![...document.querySelectorAll('#requirements input, #filters input')].every(input => input.reportValidity())) return;
  const controller = new AbortController();
  state.request = controller;
  feedback();
  const source = refining ? (state.base?.demo ? 'sample' : 'live') : options.source || 'live';
  state.progress = {};
  renderProgress();
  setBusy(true, refining, source);
  const started = Date.now();
  $('#elapsed').textContent = '已等待 0 秒';
  const timer = setInterval(() => $('#elapsed').textContent = `已等待 ${Math.floor((Date.now() - started) / 1000)} 秒`, 1000);
  const applied = refining ? filtersSignature() : null;
  try {
    const body = refining ? { snapshot_id: state.base.snapshot_id, filters: { ...state.filters }, constraints: { budget: state.budget, preference: state.preference } } : { query: query.trim(), data_mode: source, refresh: !!options.refresh };
    const data = !refining && state.mode === 'agent'
      ? await streamChat(body, controller.signal, renderProgress)
      : await post(refining ? '/api/refine' : '/api/query', body, controller.signal);
    if (controller.signal.aborted) return;
    if (!Array.isArray(data.offers)) throw new Error('服务未返回有效报价列表');
    if (!refining) {
      state.base = data;
      state.filters = emptyFilters();
      state.budget = data.intent?.budget ?? null;
      state.preference = data.intent?.preference || '';
      state.selected.clear();
      state.query = query.trim();
      state.sort = state.mode === 'agent' ? 'recommended' : 'price';
      remember(query.trim());
      document.body.classList.add('has-results');
      window.scrollTo({ top: 0, behavior: 'instant' });
    }
    state.data = data;
    state.applied = applied ?? filtersSignature();
    render();
    if (refining) feedback(`已更新推荐，当前筛选保留 ${data.offers.length} 条候选。`);
  } catch (error) {
    if (error.name === 'AbortError') feedback('已停止本次任务；已发出的请求可能仍需结束，后续步骤不再继续。');
    else feedback(error.message, 'error', !refining);
  } finally {
    clearInterval(timer);
    state.request = null;
    setBusy(false);
    renderTray();
  }
}
$('#search-form').addEventListener('submit', event => { event.preventDefault(); search($('#query').value); });
$('#cancel').addEventListener('click', () => state.request?.abort());
document.addEventListener('click', event => {
  const example = event.target.closest('[data-example]');
  if (example && !state.busy) { $('#query').value = example.dataset.example; search(example.dataset.example); }
  const modeButton = event.target.closest('[data-mode]');
  if (modeButton && !state.busy) {
    state.mode = modeButton.dataset.mode;
    document.querySelectorAll('[data-mode]').forEach(b => { b.classList.toggle('selected', b === modeButton); b.setAttribute('aria-pressed', String(b === modeButton)); });
    $('#search-submit').innerHTML = `${state.mode === 'agent' ? '帮我选选' : '开始比价'}${icon('arrow')}`;
  }
  const action = event.target.closest('[data-action]')?.dataset.action;
  if (action === 'retry') search($('#query').value);
  if (action === 'refresh') { $('#query').value = state.query; search(state.query, false, { refresh: true }); }
  if (action === 'sample') { $('#query').value = '小米手环9'; search('小米手环9', false, { source: 'sample' }); }
  if (action === 'focus-search') { window.scrollTo({top:0,behavior:'smooth'}); $('#query').focus({preventScroll:true}); }
  if (action === 'close-source') $('#source-dialog').close();
  if (action === 'reset') resetFilters();
  if (action === 'refine') search(state.query, true);
  if (action === 'compare') openComparison();
  if (action === 'clear-compare') { state.selected.clear(); renderOffers(); renderTray(); }
});
function render() {
  state.formErrors = {};
  renderEnvironment();
  $('#welcome').hidden = true;
  $('#workspace').hidden = false;
  const data = state.base;
  const intent = data.intent || {};
  const source = provenance(data);
  $('#result-heading').innerHTML = `<div><div class="result-eyebrow"><span class="origin-badge ${source.kind}">${h(source.label)}</span><span>${h(source.kind === 'live' ? '未使用查询缓存' : source.description)}</span></div><h2>${h(intent.product || data.query || state.query)}</h2><div class="request-chips"><span>${data.offers.length} 条采集候选</span>${data.completed_at ? `<span>${h(dateLabel(data.completed_at))} 完成</span>` : ''}</div></div><button type="button" class="button quiet small" data-action="refresh">${icon('clock')}${data.demo ? '真实查询' : '重新采集'}</button>`;
  renderRequirements();
  $('#matching-summary').innerHTML = evidenceSummary(visible());
  renderFilters();
  renderRecommendation();
  renderPlatforms();
  renderOffers();
  renderTrace();
  renderTray();
  renderSourceErrors();
}
function renderRequirements() {
  const open = $('#requirements details')?.open ?? window.innerWidth > 800;
  const preferences = ['', '价格优先', '优先自营/旗舰'];
  if (state.preference && !preferences.includes(state.preference)) preferences.push(state.preference);
  $('#requirements').innerHTML = `<details class="requirements-editor" ${open ? 'open' : ''}><summary><span><strong>选购要求</strong><small>${state.budget == null ? '预算不限' : `预算 ¥${money(state.budget)}`} · ${h(state.preference || '综合考虑')}</small></span><span class="requirement-edit">${isStale() ? '待应用' : '调整'} ▾</span></summary><form id="requirements-form" class="requirements-bar"><div class="requirement-field"><label for="budget-limit">最高预算</label><div><span aria-hidden="true">¥</span><input id="budget-limit" type="number" min="0" step="0.01" placeholder="不限" aria-describedby="budget-error" value="${state.budget ?? ''}"></div><p id="budget-error" class="field-error" role="status" hidden></p></div><div class="requirement-field"><label for="preference">选购侧重</label><select id="preference">${preferences.map(pref => `<option value="${h(pref)}" ${pref === state.preference ? 'selected' : ''}>${h(pref || '综合考虑')}</option>`).join('')}</select></div><button type="submit" class="button primary" ${!isStale() || !state.base.offers.length ? 'disabled' : ''}>更新推荐 ${icon('arrow')}</button></form></details>`;
}
function changeRequirements(event) {
  if (event.target.id === 'budget-limit') {
    const result = moneyRange('', event.target.value, event.target.validity.badInput);
    fieldError('budget', [event.target], result.error);
    if (!result.error) state.budget = result.max;
  }
  if (event.target.id === 'preference') state.preference = event.target.value;
  filtersChanged();
}
$('#requirements').addEventListener('input', event => { if (event.target.id === 'budget-limit') changeRequirements(event); });
$('#requirements').addEventListener('change', event => { if (event.target.id === 'preference') changeRequirements(event); });
$('#requirements').addEventListener('submit', event => { event.preventDefault(); if (isStale()) search(state.query, true); });
function renderSourceErrors() {
  const errors = state.base?.errors || {};
  if (!Object.keys(errors).length) return;
  const names = Object.keys(errors).map(p => PLATFORMS[p] || p).join('、');
  const manual = Object.values(errors).some(e => String(e).includes('NEED_MANUAL_VERIFY'));
  feedback(manual ? `${names} 需要人工验证。请在对应平台页面完成验证后重试；已有报价仍可查看。` : `${names} 暂未成功获取报价，已保留其他平台结果。`, 'error', true);
}
function renderFilters() {
  const open = $('#filters details')?.open ?? window.innerWidth > 700;
  const offers = state.base.offers;
  const tags = [...new Set(offers.flatMap(o => o.tags || []))];
  const counts = Object.fromEntries(Object.keys(PLATFORMS).map(p => [p, offers.filter(o => o.platform === p).length]));
  $('#filters').innerHTML = `<div class="filter-head"><h3>缩小选择范围</h3><button type="button" class="text-button" data-action="reset">重置</button></div>
    <section class="filter-section platform-section"><h4>购买平台</h4><div class="filter-options"><button type="button" class="chip ${!state.filters.platforms.length ? 'selected' : ''}" data-platform="all" aria-pressed="${!state.filters.platforms.length}">全部</button>${Object.entries(PLATFORMS).map(([p, name]) => `<button type="button" class="chip ${state.filters.platforms.includes(p) ? 'selected' : ''}" data-platform="${p}" aria-pressed="${state.filters.platforms.includes(p)}">${name} ${counts[p]}</button>`).join('')}</div></section>
    <details class="filter-details" ${open ? 'open' : ''}><summary>规格、价格与警示筛选</summary>
      <section class="filter-section"><label class="filter-field-label" for="spec-filter">版本 / 标题特征</label><select id="spec-filter" class="chip"><option value="">全部特征</option>${Object.keys(state.base.specs || {}).map(spec => `<option value="${h(spec)}" ${state.filters.spec === spec ? 'selected' : ''}>${h(spec)}</option>`).join('')}</select></section>
      <section class="filter-section"><label class="filter-field-label" for="match-status">标题规格核对</label><select id="match-status" class="chip"><option value="">全部状态</option>${Object.entries({compatible:'已识别属性一致',insufficient:'规格信息不足',ambiguous:'混卖或多规格',conflict:'规格冲突'}).map(([value,label]) => `<option value="${value}" ${state.filters.match_status === value ? 'selected' : ''}>${label}</option>`).join('')}</select></section>
      <section class="filter-section"><h4>报价区间（元）</h4><div class="price-inputs"><label class="sr-only" for="price-min">最低报价</label><div class="price-field"><span aria-hidden="true">¥</span><input id="price-min" aria-describedby="price-error" type="number" min="0" step="0.01" placeholder="最低价" value="${state.filters.price_min ?? ''}"></div><span class="price-separator" aria-hidden="true">至</span><label class="sr-only" for="price-max">最高报价</label><div class="price-field"><span aria-hidden="true">¥</span><input id="price-max" aria-describedby="price-error" type="number" min="0" step="0.01" placeholder="最高价" value="${state.filters.price_max ?? ''}"></div></div><p id="price-error" class="field-error" role="status" hidden></p></section>
      <section class="filter-section"><h4>排除警示商品</h4><p class="filter-help">勾选后隐藏对应商品</p>${tags.length ? tags.map(tag => `<label class="checkbox-row"><input type="checkbox" data-tag="${h(tag)}" ${state.filters.exclude_tags.includes(tag) ? 'checked' : ''}><span class="checkbox-label">${h(tag)}</span><small class="filter-count">${offers.filter(o => (o.tags || []).includes(tag)).length}<span class="sr-only"> 条候选</span></small></label>`).join('') : '<span class="offer-meta">暂未检测到警示标签</span>'}</section>
    </details><div class="filter-foot"><button class="button primary" type="button" data-action="refine" ${!offers.length || !isStale() ? 'disabled' : ''}>更新推荐 ${icon('arrow')}</button><p>报价即时筛选。更新推荐后，首选与理由会同步调整。</p></div>`;
}
$('#filters').addEventListener('click', event => {
  const button = event.target.closest('[data-platform]');
  if (!button) return;
  state.filters.platforms = button.dataset.platform === 'all' ? [] : [button.dataset.platform];
  filtersChanged();
});
function changeFilters(event) {
  const el = event.target;
  if (el.id === 'spec-filter') state.filters.spec = el.value || null;
  if (el.id === 'match-status') state.filters.match_status = el.value || null;
  if (el.dataset.tag) {
    state.filters.exclude_tags = el.checked ? [...state.filters.exclude_tags, el.dataset.tag] : state.filters.exclude_tags.filter(t => t !== el.dataset.tag);
  }
  if (el.id === 'price-min' || el.id === 'price-max') {
    const inputs = [$('#price-min'), $('#price-max')];
    const result = moneyRange(inputs[0].value, inputs[1].value, inputs.some(input => input.validity.badInput));
    fieldError('price', inputs, result.error);
    if (!result.error) { state.filters.price_min = result.min; state.filters.price_max = result.max; }
  }
  filtersChanged();
}
$('#filters').addEventListener('change', event => { if (!['price-min','price-max'].includes(event.target.id)) changeFilters(event); });
$('#filters').addEventListener('input', event => { if (['price-min','price-max'].includes(event.target.id)) changeFilters(event); });
function fieldError(name, inputs, message) {
  state.formErrors[name] = message;
  const error = $(`#${name}-error`);
  error.textContent = message; error.hidden = !message;
  inputs.forEach(input => { input.setCustomValidity(message); input.setAttribute('aria-invalid', String(!!message)); });
}
function filtersChanged() {
  document.querySelectorAll('[data-platform]').forEach(button => {
    const selected = button.dataset.platform === 'all' ? !state.filters.platforms.length : state.filters.platforms.includes(button.dataset.platform);
    button.classList.toggle('selected', selected); button.setAttribute('aria-pressed', String(selected));
  });
  const budgetText = state.budget == null ? '预算不限' : `预算 ¥${money(state.budget)}`;
  const summary = $('#requirements summary small');
  if (summary) summary.textContent = `${budgetText} · ${state.preference || '综合考虑'}`;
  const edit = $('.requirement-edit');
  if (edit) edit.textContent = `${Object.values(state.formErrors).some(Boolean) ? '输入待修正' : isStale() ? '待应用' : '调整'} ▾`;
  document.querySelectorAll('#requirements button[type=submit], #filters [data-action=refine]').forEach(button => button.disabled = Object.values(state.formErrors).some(Boolean) || !isStale() || !state.base.offers.length);
  $('#matching-summary').innerHTML = evidenceSummary(visible());
  renderRecommendation(); renderPlatforms(); renderOffers();
}
function resetFilters() {
  if (!state.base) return;
  state.filters = emptyFilters();
  if (state.budget === (state.base.intent?.budget ?? null) && state.preference === (state.base.intent?.preference || '')) { state.data = state.base; state.applied = filtersSignature(); }
  feedback(); render();
}
function decEngine(data) { return data.decision?.engine === 'rules' ? '规则排序' : data.decision?.engine === 'llm' ? 'Agent 综合评估' : '候选建议'; }
function renderRecommendation() {
  const data = state.data;
  const stale = isStale();
  const top = validTopPick(data);
  const decision = data.decision || {};
  const note = stale ? '<div class="stale-note">选购要求已改变，当前显示上次推荐。更新后会重新评估预算、偏好与筛选条件。</div>' : '';
  if (!top) {
    $('#recommendation').innerHTML = `${note}<div class="no-pick"><h3>${!data.decision ? '报价已整理' : '当前没有可推荐的候选'}</h3><p>${h(decision.reason || '按平台、规格与价格筛选候选，也可以勾选商品进行对比。')}</p></div>`;
    return;
  }
  const url = safeUrl(top.url);
  const labels = decision.worth === 'buy' ? '本次可优先考虑' : '候选首选 · 购买前请确认';
  const reasons = [top.shop ? '店铺信息已采集' : '店铺信息待补充', data.intent?.budget != null ? '采集报价在预算内' : '未设置预算上限', '未命中现有警示规则', top.match_report?.status === 'insufficient' ? '标题规格仍待确认' : '查看下方标题规格证据'];
  $('#recommendation').innerHTML = `${note}<article class="pick-card"><div class="pick-label"><span>${icon('check')}${stale ? '上次推荐' : data.demo ? '样例候选' : labels}</span><small>${data.demo ? '样例排序' : decEngine(data)}</small></div><div class="pick-body">${image(top)}<div class="pick-info">${badge(top.platform)}${productTitle(top.title, 'h3')}<p class="pick-shop">${h(top.shop || '店铺未提供')}<br>${h(salesLabel(top.sales))} · ${h(dateLabel(top.ts))} 采集</p></div><div class="pick-price"><div><span class="price-caption">采集报价</span><span class="amount"><small>¥</small>${money(top.price)}</span></div>${url && !stale ? `<a class="button primary" href="${h(url)}" target="_blank" rel="noopener noreferrer">去平台确认 ${icon('external')}</a>` : ''}</div></div><div class="pick-evidence">${reasons.map(reason => `<span>${icon('check')}${h(reason)}</span>`).join('')}</div>${evidencePanel(top)}<details class="pick-details"><summary>为什么选它？查看依据与待确认项</summary><p>${h(decision.reason || '请结合规格和价格条件选择')}</p><ul><li>标签来自标题与规则识别，未命中警示不代表已验证同款或正品。</li><li>优惠资格、具体 SKU、运费与最终成交价需在平台确认。</li><li>${data.demo ? '此处为冻结样例，未调用模型重新验证。' : '暂无长期价格历史，无法判断历史最低价或未来涨跌。'}</li></ul></details></article>`;
}
function renderPlatforms() {
  const offers = visible();
  const ordered = orderOffers(offers, state.data.offers, state.data.rank_items, state.sort);
  $('#platforms').innerHTML = `<div class="platform-grid">${Object.entries(PLATFORMS).map(([p, name]) => {
    const group = offers.filter(o => o.platform === p);
    const comparable = ordered.filter(o => o.platform === p && !['conflict', 'ambiguous'].includes(o.match_report?.status));
    const best = state.sort === 'price' ? comparable[0] : comparable.find(o => !(o.tags || []).length) || comparable[0];
    const error = state.base.errors?.[p];
    return `<article class="platform-card ${p}"><div class="platform-card-head"><span class="platform-name"><span class="platform-dot"></span>${name}</span><span>${group.length} 条候选</span></div><div class="platform-amount">${best ? `¥${money(best.price)}` : '—'}</div><p>${best ? state.sort === 'price' ? '当前筛选最低采集报价' : '当前排序的平台候选' : group.length ? '候选规格冲突或混卖，暂无可比报价' : error ? '采集暂不可用' : state.base.offers.some(o => o.platform === p) ? '当前筛选无报价' : '本次未获取报价'}</p>${best ? `<small>${h(best.shop || '店铺未提供')}</small>` : ''}</article>`;
  }).join('')}</div>`;
}
function renderOffers() {
  if (!state.base) return;
  const ordered = orderOffers(visible(), state.data.offers, state.data.rank_items, state.sort);
  $('#offers-heading').innerHTML = `<h3>全部候选<span>${ordered.length} / ${state.base.offers.length} 条</span></h3><label class="sr-only" for="sort">报价排序</label><select id="sort"><option value="recommended" ${state.sort === 'recommended' ? 'selected' : ''}>推荐顺序</option><option value="price" ${state.sort === 'price' ? 'selected' : ''}>报价从低到高</option></select>`;
  if (!ordered.length) {
    $('#offers').innerHTML = `<div class="empty-state">${icon('search')}<h3>${state.base.offers.length ? '条件有点严格，换个范围试试' : '暂时没有找到可用报价'}</h3><p>${state.base.offers.length ? '放宽价格或规格要求，可能会有更多选择。' : '试试更具体的型号，或检查数据源和平台登录状态。'}</p><button type="button" class="button small" data-action="${state.base.offers.length ? 'reset' : 'retry'}">${state.base.offers.length ? '清空筛选' : '重试查询'}</button></div>`;
    return;
  }
  const ranks = new Map((state.data.rank_items || []).map(item => [offerKey(state.data.offers[item.index] || {}), item]));
  $('#offers').innerHTML = ordered.map(o => {
    const key = offerKey(o);
    const url = safeUrl(o.url);
    const reason = ranks.get(key)?.reason;
    const overBudget = state.budget != null && o.price > state.budget;
    return `<article class="offer-card" data-offer="${h(key)}">${image(o)}<div><div>${badge(o.platform)}${overBudget ? ' <span class="warning-tag">超出预算</span>' : ''}</div>${productTitle(o.title, 'h4', 'offer-title')}<div class="offer-meta">${h(o.shop || '店铺未提供')} · ${h(salesLabel(o.sales))}</div>${o.tags?.length ? `<div class="offer-tags">${o.tags.map(tag => `<span class="warning-tag">${h(tag)}</span>`).join('')}</div>` : ''}${reason && state.sort !== 'price' && !isStale() ? `<p class="offer-reason">${h(reason)}</p>` : ''}<div class="offer-actions"><span class="offer-meta">${h(dateLabel(o.ts))} 采集</span><button type="button" class="text-button" data-hide="${h(key)}">不相关</button></div>${evidencePanel(o)}</div><div class="offer-price"><span class="price-caption">采集报价</span><span class="amount"><small>¥</small>${money(o.price)}</span>${url ? `<a class="button small" href="${h(url)}" target="_blank" rel="noopener noreferrer">查看商品 ${icon('external')}</a>` : '<span class="offer-meta">暂无购买链接</span>'}<label class="compare-check"><input type="checkbox" data-compare="${h(key)}" ${state.selected.has(key) ? 'checked' : ''}>加入对比</label></div></article>`;
  }).join('');
}
$('#offers-heading').addEventListener('change', event => { if (event.target.id === 'sort') { state.sort = event.target.value; renderOffers(); renderPlatforms(); } });
$('#offers').addEventListener('change', event => {
  const key = event.target.dataset.compare;
  if (!key) return;
  if (event.target.checked && state.selected.size >= 3) { event.target.checked = false; feedback('一次最多对比 3 件商品，先移除一件再添加。'); return; }
  if (event.target.checked) state.selected.add(key); else state.selected.delete(key);
  renderTray();
});
$('#offers').addEventListener('click', async event => {
  const button = event.target.closest('[data-hide]');
  if (!button) return;
  const key = button.dataset.hide;
  const offer = state.base.offers.find(o => offerKey(o) === key);
  button.disabled = true;
  try {
    if (!state.base.demo) await post('/api/feedback', { platform: offer.platform, platform_id: offer.platform_id });
    state.base = { ...state.base, offers: state.base.offers.filter(o => offerKey(o) !== key), rank_items: [], top_pick: null, decision: { worth: 'wait', reason: '候选已改变，请更新推荐。' } };
    state.data = { ...state.base, decision: { reason: '候选已改变，请更新推荐。' } };
    state.applied = ''; state.selected.delete(key);
    feedback(state.base.demo ? '样例数据：本次已隐藏该商品，不会写入反馈记录。' : '已标记不相关，后续采集结果也会排除该商品。');
    render();
  } catch (error) { button.disabled = false; feedback(error.message, 'error'); }
});
function renderTrace() {
  const steps = state.data.trace || [];
  $('#trace').innerHTML = steps.length ? `<details class="trace-panel"><summary><span>${icon('layers')}${state.data.demo ? '查看样例执行记录' : '查看本次执行记录'}</span><small>${steps.length} 个步骤 · ${h(state.data.trace_id || '')} ＋</small></summary>${steps.map(step => `<section class="trace-step"><div class="trace-step-head"><strong>${h(nodeNames[step.node] || step.node)}</strong><small>${(step.elapsed_ms / 1000).toFixed(2)} 秒</small></div><p>输入：${h(step.input)}<br>输出：${h(step.output)}</p>${step.detail ? `<details><summary>技术详情</summary><pre>${h(step.detail)}</pre></details>` : ''}</section>`).join('')}</details>` : '';
}
function renderTray() {
  const count = state.selected.size;
  document.body.classList.toggle('has-comparison', count > 0);
  $('#compare-tray').hidden = !count || state.busy;
  $('#compare-tray').innerHTML = `<p>已选 ${count} 件商品<small>最多 3 件，把规格与价格并排看</small></p><div><button type="button" class="text-button" data-action="clear-compare">清空</button><button type="button" class="button" data-action="compare" ${count < 2 ? 'disabled' : ''}>开始对比 ${icon('arrow')}</button></div>`;
}
function openComparison() {
  const offers = state.base.offers.filter(o => state.selected.has(offerKey(o)));
  if (offers.length < 2) return;
  const rows = [
    ['采集报价', o => `<span class="amount"><small>¥</small>${money(o.price)}</span>`],
    ['平台 / 店铺', o => `${badge(o.platform)}<br>${h(o.shop || '未提供')}`],
    ['标题特征', o => h(Object.entries(state.base.specs || {}).find(([, keys]) => keys.includes(offerKey(o)))?.[0] || '未识别')],
    ['规格核对', o => evidencePanel(o) || '尚无规格证据'],
    ['销量', o => h(salesLabel(o.sales))],
    ['警示', o => h(o.tags?.join('、') || '未命中现有规则，仍需核对同款')],
    ['采集时间', o => h(dateLabel(o.ts))],
    ['价格条件', o => `${o.coupon ? `采集券额 ¥${money(o.coupon)}；` : ''}具体 SKU、优惠资格与成交价待平台确认`],
    ['购买入口', o => safeUrl(o.url) ? `<a class="button small" href="${h(safeUrl(o.url))}" target="_blank" rel="noopener noreferrer">去平台确认 ${icon('external')}</a>` : '未提供'],
  ];
  $('#compare-content').innerHTML = `<table class="compare-table"><caption>并排展示采集信息；不同标题特征不代表同款，购买前请确认具体规格。</caption><thead><tr><th scope="col">对比项</th>${offers.map(o => `<th scope="col">${image(o)}<p>${h(o.title)}</p></th>`).join('')}</tr></thead><tbody>${rows.map(([name, cell]) => `<tr><th scope="row">${name}</th>${offers.map(o => `<td>${cell(o)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
  $('#compare-dialog').showModal();
}
$('#close-dialog').addEventListener('click', () => $('#compare-dialog').close());
$('#compare-dialog').addEventListener('click', event => { if (event.target === $('#compare-dialog')) { const r = event.target.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) event.target.close(); } });
document.addEventListener('error', event => {
  if (event.target.tagName !== 'IMG') return;
  event.target.hidden = true;
  event.target.closest('.product-image')?.setAttribute('aria-label', '商品图片暂不可用');
}, true);
renderRecent();
loadStatus();
