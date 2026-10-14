// Toravo Studio Local – single page app, no build step, no external requests.
const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const api = async (p, body) => {
  const r = await fetch(p, body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Toravo': '1'}, body: JSON.stringify(body)});
  return r.json();
};
const KIND = {song: 'YuE2', voice: 'VoxCPM', video: 'LTX · ComfyUI', shorts: 'auto-edit', thumbnail: 'Qwen-Image', stems: 'Demucs', master: 'Matchering', transcribe: 'Whisper'};
const STATE = {queued: 'wartet', running: 'läuft', done: 'fertig', failed: 'Fehler', needs_tool: 'Werkzeug fehlt', cancelled: 'abgebrochen',
  needs_approval: 'NEEDS APPROVAL', approved: 'freigegeben', ready: 'bereitgelegt'};
let timer = null;

function panel(title, right, inner, cls = '') {
  return `<section class="panel ${cls}"><div class="phead"><span class="label">${title}</span><span class="label c">${right || ''}</span></div>${inner}</section>`;
}

function queueRows(jobs, limit = 8) {
  const act = jobs.filter(j => ['running', 'queued', 'needs_tool', 'failed'].includes(j.state)).slice(0, limit);
  if (!act.length) return '<div class="empty">Keine Jobs. Sag oben einfach, was du willst.</div>';
  return act.map(j => `<div class="q"><span class="small">${esc(j.title)}</span><span class="chip">${esc(KIND[j.kind] || j.kind)}</span>
    <div><div class="bar"><i style="width:${Math.round((j.progress || 0) * 100)}%"></i></div><div class="mono dim small" style="margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(j.error || j.step || '')}</div></div>
    <span class="state st-${j.state}">${j.state === 'running' ? Math.round(j.progress * 100) + '%' : esc(STATE[j.state] || j.state)}</span></div>`).join('');
}

function gpuTile(g) {
  const bars = Array.from({length: 46}, (_, i) => `<i style="height:${8 + Math.abs(Math.sin(i * .7 + Date.now() / 900)) * (g.util || 5) / 100 * 20}px"></i>`).join('');
  return `<div class="gpu"><div class="row"><div><div class="big">${g.util}<small>%</small></div><div class="label">Compute</div></div>
    <div><div class="big">${g.vram_used || '–'}<small>GB</small></div><div class="label">VRAM / ${g.vram_total || '–'}</div></div>
    <div><div class="big">${g.temp || '–'}<small>°</small></div><div class="label">Temp</div></div></div><div class="spark">${bars}</div>
    <div class="mono dim small" style="margin-top:8px">${esc(g.name)}</div></div>`;
}

async function pageHome() {
  const [st, jobs, cal] = await Promise.all([api('/api/state'), api('/api/jobs'), api('/api/calendar')]);
  const running = jobs.filter(j => ['running', 'queued'].includes(j.state));
  const needs = cal.filter(c => c.state === 'needs_approval');
  const tools = st.tools.map(t => `<div class="tool"><span>${esc(t.title)} <span class="dim small">· ${esc(t.variant || t.engine)}</span></span>
    <span class="state ${t.ready ? 'st-done' : t.off ? 'st-needs_tool' : 'st-queued'}">${t.ready ? 'bereit' : t.off ? 'aus · cloud-optional' : 'nicht eingerichtet'}</span></div>`).join('');
  $('#main').innerHTML = `<div class="hero"><div><span class="label v">Toravo Studio · Local</span><h1>Heute.</h1></div>
    ${st.setup_done ? '' : '<button class="btn primary" onclick="api(\'/api/setup\',{})">KI-Werkzeuge einrichten</button>'}</div>
    <div class="grid g2">${panel('Render-Queue', `${running.length} Jobs`, queueRows(jobs))}${panel('GPU', esc(st.hardware.profile || ''), gpuTile(st.gpu))}</div>
    <div class="grid g3" style="margin-top:16px">
      ${panel('Publishing-Kalender', needs.length ? `NEEDS APPROVAL: ${needs.length}` : '', calRows(cal.slice(0, 5), true))}
      ${panel('Live-Streams', '24/7', (st.live.length ? st.live.map(l => `<div class="live"><span class="dot"></span>${esc(l.title)} <span class="mono dim">seit ${new Date(l.since * 1000).toLocaleTimeString().slice(0, 5)}</span></div>`).join('') : '<div class="empty">Kein Stream aktiv.</div>') + '<button class="btn sm" onclick="api(\'/api/stream/start\',{})">● Stream starten (OBS)</button>')}
      ${panel('Werkzeuge', st.hardware.gpu ? esc(st.hardware.gpu) : '', tools)}
    </div>`;
}

function calRows(items, compact) {
  if (!items.length) return '<div class="empty">Noch nichts geplant.</div>';
  return items.map(c => compact ? `<div class="tool"><span class="small"><span class="mono dim">${esc(c.date.slice(5))} ${esc(c.time)}</span> &nbsp;${esc(c.title)}</span><span class="state st-${c.state}">${esc(STATE[c.state] || c.state)}</span></div>` :
    `<div class="cal"><span class="mono">${esc(c.date)}</span><span class="mono">${esc(c.time)}</span><span>${esc(c.title)}<div class="mono dim small">${esc((c.file || '').split('/').pop())}</div></span>
     <span class="chip">${esc(c.platform)}</span><span class="state st-${c.state}">${esc(STATE[c.state] || c.state)}</span>
     <span>${c.state === 'needs_approval' ? `<button class="btn sm primary" onclick="calAct('${c.id}','approve')">Freigeben</button>` :
       c.state === 'approved' ? `<button class="btn sm" onclick="calAct('${c.id}','prepare')">Bereitlegen</button> <button class="btn sm" onclick="calAct('${c.id}','revoke')">Zurücknehmen</button>` :
       c.folder ? `<span class="mono dim small">${esc(c.folder.split('/').slice(-1)[0])}</span>` : ''}
       <button class="btn sm danger" onclick="calAct('${c.id}','delete')">✕</button></span></div>`).join('');
}

async function calAct(id, act) { await api(`/api/calendar/${id}/${act}`, {}); route(); }

async function fileList(kind, render) {
  const fs = await api('/api/files?kind=' + kind);
  return fs.length ? render(fs) : '<div class="empty">Noch keine Dateien.</div>';
}

function audioRow(f) {
  return `<div class="file"><span class="n">${esc(f.name)}</span><canvas class="wave" data-src="${f.url}" style="max-width:280px;height:34px"></canvas><audio controls preload="none" src="${f.url}"></audio></div>`;
}

async function drawWaves() {
  for (const c of document.querySelectorAll('canvas.wave[data-src]')) {
    const src = c.dataset.src; c.removeAttribute('data-src');
    try {
      const buf = await (await fetch(src)).arrayBuffer();
      const ac = new (window.AudioContext || window.webkitAudioContext)();
      const a = await ac.decodeAudioData(buf); const d = a.getChannelData(0);
      const W = c.width = c.clientWidth * 2, H = c.height = c.clientHeight * 2, n = 90, step = Math.floor(d.length / n), x = c.getContext('2d');
      const g = x.createLinearGradient(0, 0, W, 0); g.addColorStop(0, '#8a5cf6'); g.addColorStop(.55, '#6f9be0'); g.addColorStop(1, '#5ab0d0'); x.fillStyle = g;
      for (let i = 0; i < n; i++) { let m = 0; for (let k = 0; k < step; k += 64) m = Math.max(m, Math.abs(d[i * step + k] || 0)); const h = Math.max(2, m * H); x.fillRect(i * W / n, (H - h) / 2, W / n * .55, h); }
    } catch (e) { /* large files / no codec: skip waveform */ }
  }
}

async function addJob(kind, title, params, subject) { await api('/api/jobs', {kind, title, params, subject}); location.hash = 'queue'; }

async function pageSong() {
  const list = await fileList('song', fs => `<div class="files">${fs.map(audioRow).join('')}</div>`);
  $('#main').innerHTML = `<span class="label v">YuE2 · Local</span><h1>Make a song.</h1><div class="grid g2">
    ${panel('Neuer Song', '', `<div class="form"><div class="row2"><input id="s_t" placeholder="Titel, z. B. Skyborne"><input id="s_s" placeholder="Stil, z. B. epic fantasy anthem, 128 BPM, F# minor, female vocal"></div>
      <textarea id="s_l" placeholder="[verse]&#10;Lyrics … (leer lassen: das lokale LLM schreibt sie)"></textarea>
      <div><button class="btn primary" id="s_go">Song erzeugen</button> <span class="dim small">Danach in der Queue: Stems (Demucs) und Mastering (Matchering) mit einem Klick.</span></div></div>`)}
    ${panel('Werkzeuge', '', `<div class="form"><button class="btn" onclick="addJob('stems','Stems trennen',{},'')">≋ Stems vom neuesten Song (Demucs)</button>
      <button class="btn" onclick="addJob('master','Mastern',{},'')">◆ Neuesten Song mastern (Matchering, Referenz in ~/Toravo/Referenzen)</button>
      <button class="btn" onclick="addJob('transcribe','Lyrics transkribieren',{},'')">¶ Lyrics transkribieren (Whisper)</button></div>`)}</div>
    <div style="margin-top:16px">${panel('Songs', '~/Toravo/Songs', list)}</div>`;
  $('#s_go').onclick = () => { const t = $('#s_t').value || 'song'; addJob('song', `Song „${t}“`, {style: $('#s_s').value, lyrics: $('#s_l').value}, t); };
  drawWaves();
}

async function pageVoice() {
  const list = await fileList('voice', fs => `<div class="files">${fs.map(audioRow).join('')}</div>`);
  $('#main').innerHTML = `<span class="label v">VoxCPM · Local</span><h1>Give it a voice.</h1><div class="grid g2">
    ${panel('Sprechen / Stimme klonen', '', `<div class="form"><textarea id="v_t" placeholder="Text, der gesprochen werden soll …"></textarea>
      <div class="row2"><input type="file" id="v_f" accept="audio/*"><input id="v_rt" placeholder="Was in der Referenz gesagt wird (optional)"></div>
      <div><button class="btn primary" id="v_go">Erzeugen</button> <span class="dim small">Ohne Referenz: Standardstimme (bzw. Piper im Lite-Modus).</span></div></div>`)}
    ${panel('Hinweis', '', '<div class="small dim">Stimmen nur mit Einverständnis der Person klonen. Alles bleibt auf diesem Rechner.</div>')}</div>
    <div style="margin-top:16px">${panel('Aufnahmen', '~/Toravo/Voice', list)}</div>`;
  $('#v_go').onclick = async () => {
    let ref = '';
    const f = $('#v_f').files[0];
    if (f) { const r = await fetch('/api/upload?kind=voice', {method: 'POST', headers: {'X-Toravo': '1', 'X-Filename': f.name}, body: f}); ref = (await r.json()).path; }
    addJob('voice', 'Stimme', {text: $('#v_t').value, ref, ref_text: $('#v_rt').value}, 'stimme');
  };
  drawWaves();
}

async function pageVideo() {
  const songs = await api('/api/files?kind=song');
  const list = await fileList('video', fs => `<div class="vgrid">${fs.map(f => `<div><video controls preload="none" poster="${f.url.replace('/files/', '/poster/')}" src="${f.url}"></video><div class="small" style="margin-top:6px">${esc(f.name)}</div></div>`).join('')}</div>`);
  $('#main').innerHTML = `<span class="label v">LTX-Video · ComfyUI</span><h1>Turn it into a music video.</h1>
    ${panel('Neues Musikvideo', '', `<div class="form"><div class="row2"><select id="m_s">${songs.map(s => `<option value="${esc(s.path)}">${esc(s.name)}</option>`).join('') || '<option value="">– erst einen Song machen –</option>'}</select>
      <input id="m_style" placeholder="Bildstil, z. B. fantasy sky islands, golden hour, cinematic"></div>
      <div><button class="btn primary" id="m_go">Rendern</button> <span class="dim small">Ohne passende GPU: Lite-Musikvideo (Bild + Wellenform + Lyrics) mit FFmpeg.</span></div></div>`)}
    <div style="margin-top:16px">${panel('Videos', '~/Toravo/Videos', list)}</div>`;
  $('#m_go').onclick = () => { const s = $('#m_s').value; if (!s) return; const subj = s.split('/').pop().replace(/\.[^.]+$/, ''); addJob('video', `Musikvideo „${subj}“`, {input: s, style: $('#m_style').value}, subj); };
}

async function pageShorts() {
  const vids = await api('/api/files?kind=video');
  const list = await fileList('shorts', fs => `<div class="vgrid v916">${fs.map(f => `<div><video controls preload="none" poster="${f.url.replace('/files/', '/poster/')}" src="${f.url}"></video><div class="small" style="margin-top:6px">${esc(f.name)}</div></div>`).join('')}</div>`);
  $('#main').innerHTML = `<span class="label v">Shorts · Thumbnails</span><h1>Cut the Shorts.</h1>
    ${panel('Shorts-Cutter', 'auto 9:16 · captions', `<div class="form"><div class="row2"><select id="c_v">${vids.map(s => `<option value="${esc(s.path)}">${esc(s.name)}</option>`).join('') || '<option value="">– erst ein Video –</option>'}</select>
      <div class="row2"><input id="c_n" type="number" min="1" max="10" value="3"><input id="c_l" type="number" min="5" max="90" value="30"></div></div>
      <div><button class="btn primary" id="c_go">Shorts schneiden</button> <span class="dim small">beat-starke Stellen · 9:16 · Untertitel (Whisper) · HW-Encoder wenn vorhanden</span></div></div>`)}
    <div style="margin-top:16px">${panel('Shorts', '~/Toravo/Shorts', list)}</div>`;
  $('#c_go').onclick = () => { const v = $('#c_v').value; if (!v) return; const subj = v.split('/').pop().replace(/\.[^.]+$/, ''); addJob('shorts', `${$('#c_n').value} Shorts „${subj}“`, {input: v, count: +$('#c_n').value, length: +$('#c_l').value}, subj); };
}

async function pageThumb() {
  const vids = await api('/api/files?kind=video');
  const list = await fileList('thumbnail', fs => `<div class="thumbs">${fs.map(f => `<div><img src="${f.url}" loading="lazy"><div class="small" style="margin-top:6px">${esc(f.name)}</div></div>`).join('')}</div>`);
  $('#main').innerHTML = `<span class="label v">Qwen-Image · A/B</span><h1>Design the thumbnail.</h1>
    ${panel('Neues Thumbnail', '', `<div class="form"><div class="row2"><input id="t_t" placeholder="Titel auf dem Bild, z. B. FREE VOICE CLONE"><select id="t_v"><option value="">– ohne Video –</option>${vids.map(s => `<option value="${esc(s.path)}">${esc(s.name)}</option>`).join('')}</select></div>
      <input id="t_p" placeholder="Bildidee (für Qwen-Image), z. B. bold FREE, cyan rim light, keep NO SUBSCRIPTION badge">
      <div><button class="btn primary" id="t_go">A/B erzeugen</button> <span class="dim small">Ohne GPU: Vorlagen aus Videoframes.</span></div></div>`)}
    <div style="margin-top:16px">${panel('Thumbnails', '~/Toravo/Thumbnails', list)}</div>`;
  $('#t_go').onclick = () => { const t = $('#t_t').value || 'Toravo'; addJob('thumbnail', `Thumbnail „${t}“`, {title: t, prompt: $('#t_p').value, input: $('#t_v').value}, t); };
}

async function pageCalendar() {
  const [cal, vids, shorts, thumbs] = await Promise.all([api('/api/calendar'), api('/api/files?kind=video'), api('/api/files?kind=shorts'), api('/api/files?kind=thumbnail')]);
  const opts = [...vids, ...shorts].map(f => `<option value="${esc(f.path)}">${esc(f.name)}</option>`).join('');
  const needs = cal.filter(c => c.state === 'needs_approval').length;
  $('#main').innerHTML = `<span class="label v">Calendar · Approval</span><h1>Schedule it.</h1>
    ${panel('Neuer Termin', '', `<div class="form"><div class="row2"><input id="k_t" placeholder="Titel"><select id="k_f">${opts}</select></div>
      <div class="row2"><div class="row2"><input id="k_d" type="date"><input id="k_h" type="time" value="17:00"></div><div class="row2"><select id="k_p"><option>YouTube</option><option>YouTube Shorts</option><option>TikTok</option><option>Instagram</option></select>
      <select id="k_th"><option value="">– Thumbnail –</option>${thumbs.map(f => `<option value="${esc(f.path)}">${esc(f.name)}</option>`).join('')}</select></div></div>
      <div><button class="btn primary" id="k_go">Einplanen</button> <span class="dim small">Neue Termine brauchen deine Freigabe. Veröffentlicht wird in Phase 1 von Hand: „Bereitlegen“ legt alles in ~/Toravo/Veröffentlichen.</span></div></div>`)}
    <div style="margin-top:16px">${panel('Publishing-Kalender', needs ? `NEEDS APPROVAL: ${needs}` : '', calRows(cal, false))}</div>`;
  $('#k_d').value = new Date(Date.now() + 864e5).toISOString().slice(0, 10);
  $('#k_go').onclick = async () => { await api('/api/calendar', {title: $('#k_t').value, file: $('#k_f').value, date: $('#k_d').value, time: $('#k_h').value, platform: $('#k_p').value, thumb: $('#k_th').value}); route(); };
}

async function pageQueue() {
  const jobs = await api('/api/jobs');
  const rows = jobs.slice().reverse().map(j => `<div class="q" style="grid-template-columns:1.3fr 110px 1.6fr 110px 150px"><span>${esc(j.title)}<div class="mono dim small">${new Date(j.created * 1000).toLocaleString().slice(0, 17)}</div></span>
    <span class="chip">${esc(KIND[j.kind] || j.kind)}</span><div><div class="bar"><i style="width:${Math.round((j.progress || 0) * 100)}%"></i></div>
    <div class="mono dim small" style="margin-top:4px">${esc(j.error || j.step || '')}</div><div class="mono small">${(j.outputs || []).map(o => esc(o.split('/').pop())).join(' · ')}</div></div>
    <span class="state st-${j.state}">${esc(STATE[j.state] || j.state)}</span>
    <span>${['queued', 'running'].includes(j.state) ? `<button class="btn sm" onclick="jobAct('${j.id}','cancel')">Abbrechen</button>` : `<button class="btn sm" onclick="jobAct('${j.id}','retry')">Nochmal</button> <button class="btn sm danger" onclick="jobAct('${j.id}','delete')">✕</button>`}</span></div>`).join('');
  $('#main').innerHTML = `<span class="label v">Render-Queue</span><h1>Queue.</h1>${panel('Alle Jobs', `${jobs.length}`, rows || '<div class="empty">Leer.</div>')}`;
}

async function jobAct(id, act) { await api(`/api/jobs/${id}/${act}`, {}); route(); }

const PAGES = {'': pageHome, song: pageSong, voice: pageVoice, video: pageVideo, shorts: pageShorts, thumbnail: pageThumb, calendar: pageCalendar,
  queue: pageQueue, gpu: pageHome, streams: pageHome};

async function route() {
  const h = location.hash.slice(1);
  document.querySelectorAll('#nav a').forEach(a => a.classList.toggle('on', a.getAttribute('href') === '#' + h || (h === '' && a.getAttribute('href') === '#')));
  try { await (PAGES[h] || pageHome)(); } catch (e) { $('#main').innerHTML = `<div class="panel">Fehler: ${esc(e)}</div>`; }
  clearInterval(timer);
  if (['', 'queue', 'gpu', 'streams'].includes(h)) timer = setInterval(() => { if (!document.activeElement || !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) (PAGES[h] || pageHome)(); }, 3000);
}

$('#cmd').onsubmit = async e => {
  e.preventDefault();
  const text = $('#cmdin').value.trim(); if (!text) return;
  const box = $('#planbox'); box.classList.remove('hidden'); box.innerHTML = '<span class="label c">Command Bar</span><div class="empty">Plane …</div>';
  const p = await api('/api/plan', {text});
  box.innerHTML = `<div class="phead"><span class="label c">Command Bar</span><span class="label">${esc(p.provider || '')}</span></div><div class="mono small" style="margin-bottom:8px">❯ ${esc(text)}</div>` +
    p.steps.map(s => `<div class="step"><span class="ic">${s.ready ? '●' : '○'}</span><span style="flex:1">${esc(s.title)}</span><span class="chip">${esc(KIND[s.kind] || s.kind)}${s.engine === 'lite' ? ' · LITE' : ''}${s.ready ? '' : ' · FEHLT'}</span></div>`).join('') +
    `<div style="margin-top:12px;display:flex;gap:8px"><button class="btn primary" id="p_run">Ausführen</button><button class="btn" id="p_x">Schließen</button></div>`;
  $('#p_x').onclick = () => box.classList.add('hidden');
  $('#p_run').onclick = async () => { await api('/api/plan/run', {plan: p}); box.classList.add('hidden'); $('#cmdin').value = ''; location.hash = 'queue'; };
};

window.addEventListener('hashchange', route);
route();
