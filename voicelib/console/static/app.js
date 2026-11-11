'use strict';

const S = { characters: [], current: null, isNew: false, rules: [], pendingKind: null };

const $ = (s, r = document) => r.querySelector(s);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({ ok: false, error: '返回不是 JSON' }));
  if (!res.ok || data.ok === false) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function toast(msg, ms = 2600) {
  const el = $('#toast');
  el.textContent = msg;
  el.classList.add('on');
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove('on'), ms);
}

/* ───────────── 初始化 ───────────── */
document.addEventListener('DOMContentLoaded', init);

async function init() {
  $('#btn-new').onclick = newCharacter;
  $('#btn-rules').onclick = openRules;
  $('#btn-close-drawer').onclick = closeRules;
  $('#scrim').onclick = closeRules;
  $('#btn-check').onclick = runCheck;
  $('#search').oninput = renderList;
  $('#file').onchange = (e) => {
    const f = e.target.files[0];
    if (f && S.pendingKind) uploadRef(S.pendingKind, f);
    e.target.value = '';
  };
  await refresh();
}

async function refresh() {
  const d = await api('/api/state');
  S.characters = d.characters || [];
  renderStats();
  renderList();
}

function renderStats() {
  const c = S.characters;
  const active = c.filter((x) => x.status === 'active').length;
  const ready = c.filter((x) => x.refs_complete).length;
  $('#stats').innerHTML = `
    <span>角色 <b>${c.length}</b></span>
    <span>可发布 <b>${active}</b></span>
    <span>音频齐 <b>${ready}</b></span>`;
}

function renderList() {
  const kw = ($('#search').value || '').trim().toLowerCase();
  const list = S.characters.filter((c) =>
    !kw || [c.character_id, c.display_name, (c.timbre_tags || []).join(' ')].join(' ').toLowerCase().includes(kw)
  );
  if (!list.length) {
    $('#list').innerHTML = `<div style="padding:18px 10px;color:var(--ink3);font-size:12px">没有匹配的角色</div>`;
    return;
  }
  $('#list').innerHTML = list
    .map((c) => {
      const dot = { draft: 'var(--warn)', active: 'var(--ok)', retired: 'var(--ink3)' }[c.status] || 'var(--warn)';
      return `<div class="item ${S.current === c.character_id ? 'active' : ''}" data-id="${esc(c.character_id)}">
        <div class="n"><span class="dot" style="background:${dot}"></span>${esc(c.display_name || c.character_id)}</div>
        <div class="m">${esc(c.character_id)} · v${esc(c.version)}</div>
        <div class="t"><span>${esc((c.timbre_tags || []).join(' · ') || '无标签')}</span>
          · <span>音频 ${c.refs_ok}/3</span></div>
      </div>`;
    })
    .join('');
  $('#list').querySelectorAll('.item').forEach((el) => (el.onclick = () => select(el.dataset.id)));
}

/* ───────────── 读取 / 渲染 ───────────── */
async function select(id) {
  try {
    const d = await api('/api/character?id=' + encodeURIComponent(id));
    S.current = id;
    S.isNew = false;
    renderList();
    renderEditor(d);
  } catch (e) {
    toast('读取失败:' + e.message);
  }
}

function newCharacter() {
  S.current = null;
  S.isNew = true;
  renderList();
  renderEditor({
    card: {
      character_id: '',
      display_name: '',
      version: '0.1.0',
      status: 'draft',
      profile: { gender: 'female', age_range: '18-22', timbre_tags: [], archetype: '', register: '' },
      voice: { rate_baseline: 0.95, pitch_baseline_st: 0, breathiness: 0.3 },
      source: { type: 'commissioned_cv', license_ref: '', valid_until: '' },
      providers: { index_tts25: { ref: 'refs/calm.wav', attn_backend: 'sdpa', out_rate: 22050 } },
      fallback_order: ['index_tts25'],
      notes: '',
    },
    presets: {
      character_id: '',
      version: '0.1.0',
      presets: {
        calm: { rate: 0.95, emo: { calm: 0.6, melancholic: 0.15 }, intensity: 0.3, pause_after: 0.35, reverb: 'room_small' },
        intense: { rate: 1.05, emo: { angry: 0.55, disgusted: 0.1 }, intensity: 0.8, pause_after: 0.2, reverb: 'room_small' },
        whisper: { rate: 0.98, emo: { sad: 0.45, melancholic: 0.25 }, intensity: 0.25, pause_after: 0.45, gain_db: -4, reverb: 'close' },
      },
    },
    refs: {},
    validation: { card: [], presets: [], rules: [] },
  });
}

function field(label, id, value, opts = {}) {
  const { type = 'text', hint = '', readonly = false, step = '0.01', cls = '' } = opts;
  return `<div class="field ${cls}"><label for="${id}">${esc(label)}</label>
    <input id="${id}" type="${type}" ${type === 'number' ? `step="${step}"` : ''} ${readonly ? 'readonly' : ''}
      value="${esc(value ?? '')}" class="${opts.mono ? 'mono' : ''}">
    ${hint ? `<span class="hintline">${hint}</span>` : ''}</div>`;
}

function presetBlock(key, p) {
  const emo = Object.entries(p.emo || {}).map(([k, v]) => `${k}:${v}`).join(', ');
  return `<div class="preset" data-key="${esc(key)}">
    <div class="preset-head">
      <input class="p-key mono" value="${esc(key)}" placeholder="preset 名">
      <span class="spacer"></span>
      <button class="btn ghost small" data-act="del-preset">删除</button>
    </div>
    <div class="preset-grid">
      <div class="field"><label>rate</label><input class="p-rate" type="number" step="0.01" value="${esc(p.rate ?? 1)}"></div>
      <div class="field"><label>intensity</label><input class="p-int" type="number" step="0.05" value="${esc(p.intensity ?? 0.5)}"></div>
      <div class="field"><label>pause_after</label><input class="p-pause" type="number" step="0.05" value="${esc(p.pause_after ?? 0.3)}"></div>
      <div class="field"><label>reverb</label>
        <select class="p-rev">
          ${['none', 'close', 'room_small', 'room_large'].map((r) => `<option ${p.reverb === r ? 'selected' : ''}>${r}</option>`).join('')}
        </select>
      </div>
    </div>
    <div class="field" style="margin-top:10px"><label>emo</label>
      <input class="p-emo mono" value="${esc(emo)}" placeholder="calm:0.6, melancholic:0.15">
      <span class="hintline">具名键:值,各键之和 ≤0.8(L2-02)</span></div>
  </div>`;
}

function refSlot(kind, info) {
  const ok = info && info.ok;
  const present = info && info.present;
  const detail = present
    ? `${info.duration ?? '?'}s · ${info.sample_rate ?? '?'}Hz · ${info.channels ?? '?'}ch`
    : '未上传';
  return `<div class="slot ${present ? 'filled' : ''}">
    <div class="k">${kind}.wav</div>
    <div class="info ${ok ? 'ok' : present ? 'bad' : ''}">${esc(detail)}<br>${esc((info && info.reason) || '')}</div>
    <button class="btn ghost small" data-act="upload" data-kind="${kind}">${present ? '替换' : '上传 WAV'}</button>
  </div>`;
}

function renderEditor(doc) {
  const c = doc.card || {};
  const profile = c.profile || {};
  const voice = c.voice || {};
  const src = c.source || {};
  const prov = c.providers || {};
  const it = prov.index_tts25 || {};
  const db = prov.doubao || {};
  const presets = (doc.presets && doc.presets.presets) || {};
  const refs = doc.refs || {};
  const v = doc.validation || { card: [], presets: [], rules: [] };
  const allFindings = [
    ...(v.card || []).map((m) => ['schema:card', m]),
    ...(v.presets || []).map((m) => ['schema:presets', m]),
    ...(v.rules || []).map((m) => ['rule', m]),
  ];
  const isEdit = !S.isNew;

  $('#editor').innerHTML = `
  <div class="doc-head">
    <div>
      <h1>${esc(c.display_name || '新角色')}</h1>
      <div class="doc-id">${esc(c.character_id || '— 未命名 —')}</div>
    </div>
    <div class="spacer"></div>
    <span class="badge ${esc(c.status || 'draft')}">${esc(c.status || 'draft')}</span>
    ${isEdit ? `<button class="btn ghost small danger" id="btn-del">删除</button>` : ''}
    <button class="btn primary" id="btn-save">保存</button>
  </div>

  ${allFindings.length
      ? `<div class="findings bad"><strong>${allFindings.length} 个问题</strong><ul>${allFindings
          .map(([s, m]) => `<li><span class="src">${esc(s)}</span>${esc(m)}</li>`)
          .join('')}</ul></div>`
      : `<div class="findings good">结构校验通过,规则检查无阻断项。</div>`}

  <div class="card">
    <h3>身份</h3>
    <div class="grid">
      ${field('character_id(永不复用)', 'f_id', c.character_id, { mono: true, readonly: isEdit, hint: '小写 + 下划线,3–32 位' })}
      ${field('显示名', 'f_name', c.display_name)}
      ${field('版本', 'f_version', c.version ?? '0.1.0', { mono: true })}
      <div class="field"><label for="f_status">状态</label>
        <select id="f_status">
          ${['draft', 'active', 'retired'].map((s) => `<option ${c.status === s ? 'selected' : ''}>${s}</option>`).join('')}
        </select>
        <span class="hintline">active 需三条音频齐全且授权在位</span></div>
    </div>
  </div>

  <div class="card">
    <h3>音色档案</h3>
    <div class="grid three">
      <div class="field"><label for="f_gender">性别</label>
        <select id="f_gender">${['female', 'male', 'neutral'].map((g) => `<option ${profile.gender === g ? 'selected' : ''}>${g}</option>`).join('')}</select></div>
      ${field('年龄段', 'f_age', profile.age_range ?? '18-22', { mono: true, hint: '格式 18-22' })}
      ${field('音区', 'f_register', profile.register)}
      ${field('音色标签(逗号分隔)', 'f_tags', (profile.timbre_tags || []).join(', '), { cls: 'full', hint: '2–6 个短词,用于选角检索' })}
      ${field('戏路', 'f_archetype', profile.archetype, { cls: 'full' })}
    </div>
  </div>

  <div class="card">
    <h3>声音参数</h3>
    <div class="grid three">
      ${field('rate_baseline', 'f_rate', voice.rate_baseline ?? 0.95, { type: 'number', hint: '库内语义:>1 更快' })}
      ${field('pitch_baseline_st', 'f_pitch', voice.pitch_baseline_st ?? 0, { type: 'number' })}
      ${field('breathiness', 'f_breath', voice.breathiness ?? 0.3, { type: 'number', step: '0.05' })}
    </div>
  </div>

  <div class="card">
    <h3>授权</h3>
    <div class="grid">
      <div class="field"><label for="f_src_type">声源类型</label>
        <select id="f_src_type">
          ${['commissioned_cv', 'self_recorded', 'licensed_api', 'designed'].map((t) => `<option ${src.type === t ? 'selected' : ''}>${t}</option>`).join('')}
        </select></div>
      ${field('授权文件', 'f_license', src.license_ref ?? `licenses/${c.character_id || '<id>'}.md`, { mono: true, hint: '必须存在,否则 E2002' })}
      ${field('授权到期', 'f_valid_until', src.valid_until ?? '', { mono: true, hint: '加引号,格式 2029-11-30' })}
    </div>
  </div>

  <div class="card">
    <h3>供应商映射</h3>
    <div class="grid three">
      ${field('index_tts25 · ref', 'f_ref_path', it.ref ?? 'refs/calm.wav', { mono: true })}
      ${field('index_tts25 · 后端', 'f_attn', it.attn_backend ?? 'sdpa', { mono: true })}
      ${field('index_tts25 · 输出率', 'f_outrate', it.out_rate ?? 22050, { type: 'number', step: '1' })}
      ${field('doubao · voice_id', 'f_doubao', db.voice_id ?? '', { mono: true })}
      ${field('fallback_order(逗号分隔)', 'f_fallback', (c.fallback_order || []).join(', '), { mono: true })}
    </div>
    <div class="field" style="margin-top:12px"><label for="f_notes">表演备注</label>
      <textarea id="f_notes">${esc(c.notes || '')}</textarea></div>
  </div>

  <div class="card">
    <h3>情绪预设 <button class="btn ghost small" id="btn-add-preset" style="margin-left:auto">+ 新增预设</button></h3>
    <div class="presets" id="presets">
      ${Object.entries(presets).map(([k, p]) => presetBlock(k, p)).join('')}
    </div>
  </div>

  <div class="card">
    <h3>参考音频(10–14 秒 / ≥44.1kHz / 单声道 / 无混响)</h3>
    <div class="slots">
      ${['calm', 'intense', 'whisper'].map((k) => refSlot(k, refs[k])).join('')}
    </div>
    <p class="hintline" style="margin-top:10px">上传后自动回填 registry 与 catalog。硬上限 15 秒,超出部分会被模型静默截断。</p>
  </div>

  <div class="card">
    <h3>试听(克隆)<span class="h3-note" id="s-status"></span></h3>
    <div class="grid">
      <div class="field"><label for="s-provider">供应商</label><select id="s-provider"></select></div>
      <div class="field"><label for="s-preset">预设</label>
        <select id="s-preset">${Object.keys(presets).map((k) => `<option>${esc(k)}</option>`).join('')}</select></div>
      <div class="field full"><label for="s-text">台词</label>
        <input id="s-text" type="text" value="雨夜,她以妖刀斩尽恶影。">
        <span class="hintline">数字自动转汉字;单句 ≤200 字</span></div>
    </div>
    <div class="row-end"><button class="btn primary" id="s-go">合成试听</button></div>
    <div id="s-out" style="margin-top:12px"></div>
  </div>
  `;

  $('#btn-save').onclick = save;
  const del = $('#btn-del');
  if (del) del.onclick = removeChar;
  $('#btn-add-preset').onclick = () => {
    const wrap = $('#presets');
    const div = document.createElement('div');
    div.innerHTML = presetBlock('new_preset', { rate: 1, intensity: 0.4, pause_after: 0.3, emo: { calm: 0.3 }, reverb: 'room_small' });
    wrap.appendChild(div.firstElementChild);
    bindPresetButtons();
  };
  bindPresetButtons();
  bindSynth();
  $('#editor').querySelectorAll('[data-act=upload]').forEach((b) => {
    b.onclick = () => {
      S.pendingKind = b.dataset.kind;
      $('#file').click();
    };
  });
}

function bindPresetButtons() {
  $('#editor').querySelectorAll('[data-act=del-preset]').forEach((b) => {
    b.onclick = () => b.closest('.preset').remove();
  });
}

/* ───────────── 收集与保存 ───────────── */
function parseEmo(text) {
  const out = {};
  (text || '').split(',').forEach((part) => {
    const [k, v] = part.split(':').map((s) => (s || '').trim());
    if (k && v !== undefined && v !== '') {
      const n = Number(v);
      if (!Number.isNaN(n)) out[k] = n;
    }
  });
  return out;
}

function listOrEmpty(v) {
  return (v || '').split(',').map((s) => s.trim()).filter(Boolean);
}

function num(id, fallback) {
  const v = Number($(id).value);
  return Number.isNaN(v) ? fallback : v;
}

function collect() {
  const presets = {};
  $('#editor').querySelectorAll('.preset').forEach((el) => {
    const key = el.querySelector('.p-key').value.trim();
    if (!key) return;
    const p = {
      rate: Number(el.querySelector('.p-rate').value) || 1,
      emo: parseEmo(el.querySelector('.p-emo').value),
      intensity: Number(el.querySelector('.p-int').value) || 0,
      pause_after: Number(el.querySelector('.p-pause').value) || 0,
      reverb: el.querySelector('.p-rev').value,
    };
    presets[key] = p;
  });

  const card = {
    character_id: $('#f_id').value.trim(),
    display_name: $('#f_name').value.trim(),
    version: $('#f_version').value.trim(),
    status: $('#f_status').value,
    profile: {
      gender: $('#f_gender').value,
      age_range: $('#f_age').value.trim(),
      timbre_tags: listOrEmpty($('#f_tags').value),
      archetype: $('#f_archetype').value.trim(),
      register: $('#f_register').value.trim(),
    },
    voice: {
      rate_baseline: num('#f_rate', 0.95),
      pitch_baseline_st: num('#f_pitch', 0),
      breathiness: num('#f_breath', 0.3),
    },
    source: {
      type: $('#f_src_type').value,
      license_ref: $('#f_license').value.trim(),
      valid_until: $('#f_valid_until').value.trim(),
    },
    providers: { index_tts25: { ref: $('#f_ref_path').value.trim(), attn_backend: $('#f_attn').value.trim(), out_rate: num('#f_outrate', 22050) } },
    fallback_order: listOrEmpty($('#f_fallback').value),
    notes: $('#f_notes').value,
  };
  const doubao = $('#f_doubao').value.trim();
  if (doubao) card.providers.doubao = { voice_id: doubao };

  Object.keys(card).forEach((k) => {
    if (card[k] === '' || (Array.isArray(card[k]) && !card[k].length && k !== 'fallback_order')) {
      if (k !== 'notes') delete card[k];
    }
  });
  if (!card.source.valid_until) delete card.source.valid_until;
  if (!card.profile.register) delete card.profile.register;
  if (!card.profile.archetype) delete card.profile.archetype;

  return { card, presets: { character_id: card.character_id, version: card.version, presets } };
}

async function save() {
  try {
    const payload = collect();
    if (!payload.card.character_id) return toast('先填 character_id');
    const d = await api('/api/character', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    S.characters = d.characters;
    S.current = d.character_id;
    S.isNew = false;
    renderStats();
    renderList();
    await select(d.character_id);
    const v = d.validation;
    const n = (v.card.length + v.presets.length + v.rules.length);
    toast(n ? `已保存,仍有 ${n} 个问题` : '已保存,校验通过');
  } catch (e) {
    toast('保存失败:' + e.message, 3600);
  }
}

async function removeChar() {
  if (!S.current) return;
  if (!confirm(`删除 ${S.current}?只能删 draft 且无音频的角色。`)) return;
  try {
    const d = await api('/api/delete?id=' + encodeURIComponent(S.current), { method: 'POST' });
    S.characters = d.characters;
    S.current = null;
    renderStats();
    renderList();
    $('#editor').innerHTML = `<div class="empty"><div class="empty-mark">◍</div><h2>已删除</h2></div>`;
    toast('已删除');
  } catch (e) {
    toast('删除失败:' + e.message, 3600);
  }
}

async function uploadRef(kind, file) {
  if (!S.current) return toast('先保存角色再上传音频');
  if (!/\.wav$/i.test(file.name)) return toast('只接受 WAV 无损文件');
  try {
    const buf = await file.arrayBuffer();
    const res = await fetch(`/api/upload?id=${encodeURIComponent(S.current)}&kind=${kind}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/octet-stream' },
      body: buf,
    });
    const d = await res.json();
    if (!d.ok) throw new Error(d.error || '上传失败');
    await select(S.current);
    const info = d.refs[kind];
    toast(info.ok ? `${kind}.wav 上传成功(${info.duration}s)` : `${kind}.wav 已上传,但不合规:${info.reason}`, 4000);
    await refresh();
  } catch (e) {
    toast('上传失败:' + e.message, 3600);
  }
}

/* ───────────── 规则抽屉 / 体检 ───────────── */
async function openRules() {
  if (!S.rules.length) {
    const d = await api('/api/rules');
    S.rules = d.rules || [];
  }
  $('#rules-body').innerHTML = S.rules
    .map(
      (r) => `<div class="ru"><code>${esc(r.id)}</code>
        <span class="th">${esc(r.title)}</span>
        <span class="val">${esc(r.threshold || '')}</span></div>`
    )
    .join('');
  $('#drawer').classList.add('open');
  $('#scrim').classList.add('on');
}

function closeRules() {
  $('#drawer').classList.remove('open');
  $('#scrim').classList.remove('on');
}

async function runCheck() {
  try {
    const d = await api('/api/check');
    const bad = Object.entries(d.report).filter(
      ([, v]) => v.card.length + v.presets.length + v.rules.length > 0
    );
    toast(bad.length ? `体检完成:${bad.length}/${d.count} 个角色有问题 → ${bad.map(([k]) => k).join(', ')}` : `体检完成:${d.count} 个角色全部通过`, 5000);
    await refresh();
  } catch (e) {
    toast('体检失败:' + e.message);
  }
}

/* ═════════════ 采集视图逻辑 ═════════════ */
let HJOB = null;
let HPoll = null;

document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.tab').forEach((t) => (t.onclick = () => switchView(t.dataset.view)));
  const start = $('#h-start');
  if (start) start.onclick = startHarvest;
  loadDeps();
});

function switchView(name) {
  document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('active', t.dataset.view === name));
  $('#view-harvest').hidden = name !== 'harvest';
  $('#view-roles').hidden = name !== 'roles';
  if (name === 'roles') refresh();
}

async function loadDeps() {
  try {
    const d = await api('/api/env');
    const x = d.deps || {};
    const item = (label, okval, title) =>
      `<span class="${okval ? 'on' : 'off'}" title="${esc(title || '')}">${label} ${okval ? '✓' : '✗'}</span>`;
    $('#dep-status').innerHTML =
      item('ffmpeg', !!x.ffmpeg) +
      item('yt-dlp', !!x.yt_dlp) +
      item('demucs', !!x.demucs, x.torch ? 'torch ' + x.torch : '未装 torch') +
      item('cuda', !!x.cuda, x.cuda ? 'GPU 可用' : 'CPU 模式(分离会慢)');
  } catch (e) {
    $('#dep-status').textContent = '';
  }
}

async function startHarvest() {
  const url = $('#h-url').value.trim();
  if (!url) return toast('先填视频链接或本地文件路径');
  const btn = $('#h-start');
  btn.disabled = true;
  btn.textContent = '采集中…';
  $('#h-log').textContent = '任务已提交…';
  $('#h-state').textContent = 'queued';
  $('#h-cands').innerHTML = '<p class="hintline">采集中,完成后这里会出现候选片段。</p>';
  try {
    const d = await api('/api/harvest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        url,
        cookies: $('#h-cookies').value.trim(),
        separate: $('#h-sep').checked,
      }),
    });
    HJOB = d.job;
    pollJob();
  } catch (e) {
    toast('提交失败:' + e.message, 4000);
    resetStartBtn();
  }
}

function resetStartBtn() {
  const btn = $('#h-start');
  btn.disabled = false;
  btn.textContent = '开始采集';
}

function pollJob() {
  clearTimeout(HPoll);
  HPoll = setTimeout(async () => {
    try {
      const d = await api('/api/job?id=' + encodeURIComponent(HJOB));
      const j = d.job;
      $('#h-state').textContent = j.state;
      const log = $('#h-log');
      log.textContent = (j.log || []).join('\n') || '…';
      log.scrollTop = log.scrollHeight;
      if (j.state === 'done') {
        resetStartBtn();
        renderCands(j.result.candidates || []);
      } else if (j.state === 'error') {
        resetStartBtn();
        toast('采集失败:' + (j.error || '未知错误'), 6000);
      } else {
        pollJob();
      }
    } catch (e) {
      resetStartBtn();
      toast('轮询失败:' + e.message, 4000);
    }
  }, 1200);
}

function renderCands(list) {
  const box = $('#h-cands');
  if (!list.length) {
    box.innerHTML = `<p class="hintline">没有达标片段。常见原因:整段是 BGM、说话太短、需要登录才能拿到原片。</p>`;
    return;
  }
  box.innerHTML = list
    .map((c) => {
      const cls = c.score >= 70 ? '' : 'low';
      const bad = (c.problems || []).map((p) => `<div class="tagline">✗ ${esc(p)}</div>`).join('');
      const warn = (c.warnings || []).map((w) => `<div class="warnline">! ${esc(w)}</div>`).join('');
      return `<div class="cand ${c.ok ? '' : 'no'}">
        <div class="cand-head">
          <span class="idx">#${c.index + 1}</span>
          <span class="sc ${cls}">${c.score}</span>
          <span class="dur">${c.duration}s</span>
          <span class="dur">峰值 ${c.peak_dbfs} dB</span>
          <span class="dur">静音 ${c.silence_ratio}%</span>
          ${c.separated ? '<span class="dur">已分离</span>' : '<span class="warnline">未分离</span>'}
        </div>
        ${bad}${warn}
        <audio controls preload="none" src="/api/clip?id=${encodeURIComponent(HJOB)}&i=${c.index}"></audio>
        <div class="cand-foot">
          <select class="kind">
            <option value="calm">calm</option>
            <option value="intense">intense</option>
            <option value="whisper">whisper</option>
          </select>
          <button class="btn primary small" data-i="${c.index}">用这段生成角色</button>
        </div>
      </div>`;
    })
    .join('');
  box.querySelectorAll('button[data-i]').forEach((b) => {
    b.onclick = () => commitCandidate(Number(b.dataset.i), b.parentElement.querySelector('.kind').value, b);
  });
}

async function commitCandidate(index, kind, btn) {
  const cid = $('#h-cid').value.trim();
  if (!/^[a-z][a-z0-9_]{2,31}$/.test(cid)) {
    return toast('character_id 不合法:小写开头,3–32 位,只含小写字母/数字/下划线');
  }
  btn.disabled = true;
  btn.textContent = '写入中…';
  try {
    const d = await api('/api/commit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        job: HJOB,
        index,
        kind,
        character_id: cid,
        display_name: $('#h-name').value.trim() || cid,
        gender: $('#h-gender').value,
        age_range: $('#h-age').value.trim(),
        tags: $('#h-tags').value.trim(),
      }),
    });
    const n = d.validation.card.length + d.validation.presets.length + d.validation.rules.length;
    toast(`${d.created ? '已创建' : '已追加'} ${cid} · ${kind}.wav${n ? ` · 仍有 ${n} 个问题` : ''}`, 4000);
    S.characters = d.characters;
    renderStats();
    renderList();
    switchView('roles');
    await select(cid);
  } catch (e) {
    toast('写入失败:' + e.message, 5000);
    btn.disabled = false;
    btn.textContent = '用这段生成角色';
  }
}

/* ───────────── 试听(合成)───────────── */
async function bindSynth() {
  const sel = $('#s-provider');
  const st = $('#s-status');
  const out = $('#s-out');
  if (!sel) return;

  try {
    const d = await api('/api/synth/providers');
    const list = d.providers || [];
    const ready = list.filter((p) => p.ready);
    sel.innerHTML = list
      .map(
        (p) =>
          `<option value="${esc(p.name)}" ${p.ready ? '' : 'disabled'}>${esc(p.display)}${
            p.ready ? '' : ' — 缺 ' + esc((p.missing || []).join(' / '))
          }</option>`
      )
      .join('');
    if (ready.length) {
      sel.value = ready[0].name;
      st.textContent = ready.length + ' 个可用';
      st.style.color = 'var(--ok)';
    } else {
      st.textContent = list.length ? '未配置 key' : '未配置供应商';
      st.style.color = 'var(--accent)';
    }
  } catch (e) {
    st.textContent = '读取失败';
  }

  const btn = $('#s-go');
  if (btn)
    btn.onclick = async () => {
      if (!S.current) return toast('先保存角色,再试听');
      const text = $('#s-text').value.trim();
      if (!text) return toast('先填台词');
      btn.disabled = true;
      btn.textContent = '合成中…';
      out.innerHTML = '<p class="hintline">合成中…</p>';
      try {
        const r = await api('/api/synth', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            character_id: S.current,
            text,
            preset: $('#s-preset').value,
            provider: sel.value,
          }),
        });
        out.innerHTML = `<audio controls autoplay src="${r.url}"></audio>
          <p class="hintline">${esc(r.provider)} · ${r.duration ?? '?'}s · ${r.sample_rate ?? '?'}Hz · ${Math.round((r.bytes || 0) / 1024)}KB</p>`;
        toast('合成成功');
      } catch (e) {
        out.innerHTML = `<div class="tagline">✗ ${esc(e.message)}</div>`;
      } finally {
        btn.disabled = false;
        btn.textContent = '合成试听';
      }
    };
}
