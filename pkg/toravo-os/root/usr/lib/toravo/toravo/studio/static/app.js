// Toravo Studio Local – single page app, no build step, no external requests.
const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const api = async (p, body) => {
  const r = await fetch(p, body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Toravo': '1'}, body: JSON.stringify(body)});
  return r.json();
};
// 14.10.2026: UI language from the server (<html lang> = session locale): German for de_*, English otherwise.
const LANG = document.documentElement.lang === 'de' ? 'de' : 'en';
const t = (de, en) => LANG === 'de' ? de : en;
const KIND = {song: 'YuE2', voice: 'VoxCPM', video: 'LTX · ComfyUI', shorts: 'auto-edit', thumbnail: 'Qwen-Image', stems: 'Demucs', master: 'Matchering', transcribe: 'Whisper'};
const STATE = LANG === 'de' ? {queued: 'wartet', running: 'läuft', done: 'fertig', failed: 'Fehler', needs_tool: 'Werkzeug fehlt', cancelled: 'abgebrochen',
  needs_approval: 'NEEDS APPROVAL', approved: 'freigegeben', ready: 'bereitgelegt'} :
  {queued: 'waiting', running: 'running', done: 'done', failed: 'error', needs_tool: 'tool missing', cancelled: 'cancelled',
  needs_approval: 'NEEDS APPROVAL', approved: 'approved', ready: 'prepared'};
let timer = null;

function panel(title, right, inner, cls = '') {
  return `<section class="panel ${cls}"><div class="phead"><span class="label">${title}</span><span class="label c">${right || ''}</span></div>${inner}</section>`;
}

function queueRows(jobs, limit = 8) {
  const act = jobs.filter(j => ['running', 'queued', 'needs_tool', 'failed'].includes(j.state)).slice(0, limit);
  if (!act.length) return `<div class="empty">${t('Keine Jobs. Sag oben einfach, was du willst.', 'No jobs. Just say what you want up top.')}</div>`;
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
  const tools = st.tools.map(tl => `<div class="tool"><span>${esc(tl.title)} <span class="dim small">· ${esc(tl.variant || tl.engine)}</span></span>
    <span class="state ${tl.ready ? 'st-done' : tl.off ? 'st-needs_tool' : 'st-queued'}">${tl.ready ? t('bereit', 'ready') : tl.off ? t('aus · cloud-optional', 'off · cloud optional') : t('nicht eingerichtet', 'not set up')}</span></div>`).join('');
  $('#main').innerHTML = `<div class="hero"><div><span class="label v">Toravo Studio · Local</span><h1>${t('Heute.', 'Today.')}</h1></div>
    ${st.setup_done ? '' : `<button class="btn primary" onclick="api('/api/setup',{})">${t('KI-Werkzeuge einrichten', 'Set up AI tools')}</button>`}</div>
    <div class="grid g2">${panel(t('Render-Queue', 'Render queue'), `${running.length} Jobs`, queueRows(jobs))}${panel('GPU', esc(st.hardware.profile || ''), gpuTile(st.gpu))}</div>
    <div class="grid g3" style="margin-top:16px">
      ${panel(t('Publishing-Kalender', 'Publishing calendar'), needs.length ? `NEEDS APPROVAL: ${needs.length}` : '', calRows(cal.slice(0, 5), true))}
      ${panel(t('Live-Streams', 'Live streams'), '24/7', (st.live.length ? st.live.map(l => `<div class="live"><span class="dot"></span>${esc(l.title)} <span class="mono dim">${t('seit', 'since')} ${new Date(l.since * 1000).toLocaleTimeString().slice(0, 5)}</span></div>`).join('') : `<div class="empty">${t('Kein Stream aktiv.', 'No stream running.')}</div>`) + `<button class="btn sm" onclick="api('/api/stream/start',{})">● ${t('Stream starten (OBS)', 'Start stream (OBS)')}</button>`)}
      ${panel(t('Werkzeuge', 'Tools'), st.hardware.gpu ? esc(st.hardware.gpu) : '', tools)}
    </div>`;
}

function calRows(items, compact) {
  if (!items.length) return `<div class="empty">${t('Noch nichts geplant.', 'Nothing scheduled yet.')}</div>`;
  return items.map(c => compact ? `<div class="tool"><span class="small"><span class="mono dim">${esc(c.date.slice(5))} ${esc(c.time)}</span> &nbsp;${esc(c.title)}</span><span class="state st-${c.state}">${esc(STATE[c.state] || c.state)}</span></div>` :
    `<div class="cal"><span class="mono">${esc(c.date)}</span><span class="mono">${esc(c.time)}</span><span>${esc(c.title)}<div class="mono dim small">${esc((c.file || '').split('/').pop())}</div></span>
     <span class="chip">${esc(c.platform)}</span><span class="state st-${c.state}">${esc(STATE[c.state] || c.state)}</span>
     <span>${c.state === 'needs_approval' ? `<button class="btn sm primary" onclick="calAct('${c.id}','approve')">${t('Freigeben', 'Approve')}</button>` :
       c.state === 'approved' ? `<button class="btn sm" onclick="calAct('${c.id}','prepare')">${t('Bereitlegen', 'Prepare')}</button> <button class="btn sm" onclick="calAct('${c.id}','revoke')">${t('Zurücknehmen', 'Revoke')}</button>` :
       c.folder ? `<span class="mono dim small">${esc(c.folder.split('/').slice(-1)[0])}</span>` : ''}
       <button class="btn sm danger" onclick="calAct('${c.id}','delete')">✕</button></span></div>`).join('');
}

async function calAct(id, act) { await api(`/api/calendar/${id}/${act}`, {}); route(); }

async function fileList(kind, render) {
  const fs = await api('/api/files?kind=' + kind);
  return fs.length ? render(fs) : `<div class="empty">${t('Noch keine Dateien.', 'No files yet.')}</div>`;
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
    ${panel(t('Neuer Song', 'New song'), '', `<div class="form"><div class="row2"><input id="s_t" placeholder="${t('Titel, z. B. Skyborne', 'Title, e.g. Skyborne')}"><input id="s_s" placeholder="${t('Stil, z. B.', 'Style, e.g.')} epic fantasy anthem, 128 BPM, F# minor, female vocal"></div>
      <textarea id="s_l" placeholder="[verse]&#10;${t('Lyrics … (leer lassen: das lokale LLM schreibt sie)', 'Lyrics … (leave empty: the local LLM writes them)')}"></textarea>
      <div><button class="btn primary" id="s_go">${t('Song erzeugen', 'Make song')}</button> <span class="dim small">${t('Danach in der Queue: Stems (Demucs) und Mastering (Matchering) mit einem Klick.', 'Then in the queue: stems (Demucs) and mastering (Matchering) in one click.')}</span></div></div>`)}
    ${panel(t('Werkzeuge', 'Tools'), '', `<div class="form"><button class="btn" onclick="addJob('stems','${t('Stems trennen', 'Split stems')}',{},'')">≋ ${t('Stems vom neuesten Song (Demucs)', 'Stems of the newest song (Demucs)')}</button>
      <button class="btn" onclick="addJob('master','${t('Mastern', 'Master')}',{},'')">◆ ${t('Neuesten Song mastern (Matchering, Referenz in ~/Toravo/Referenzen)', 'Master the newest song (Matchering, reference in ~/Toravo/References)')}</button>
      <button class="btn" onclick="addJob('transcribe','${t('Lyrics transkribieren', 'Transcribe lyrics')}',{},'')">¶ ${t('Lyrics transkribieren (Whisper)', 'Transcribe lyrics (Whisper)')}</button></div>`)}</div>
    <div style="margin-top:16px">${panel('Songs', '~/Toravo/Songs', list)}</div>`;
  $('#s_go').onclick = () => { const ti = $('#s_t').value || 'song'; addJob('song', t(`Song „${ti}“`, `Song “${ti}”`), {style: $('#s_s').value, lyrics: $('#s_l').value}, ti); };
  drawWaves();
}

async function pageVoice() {
  const list = await fileList('voice', fs => `<div class="files">${fs.map(audioRow).join('')}</div>`);
  $('#main').innerHTML = `<span class="label v">VoxCPM · Local</span><h1>Give it a voice.</h1><div class="grid g2">
    ${panel(t('Sprechen / Stimme klonen', 'Speak / clone a voice'), '', `<div class="form"><textarea id="v_t" placeholder="${t('Text, der gesprochen werden soll …', 'Text to speak …')}"></textarea>
      <div class="row2"><input type="file" id="v_f" accept="audio/*"><input id="v_rt" placeholder="${t('Was in der Referenz gesagt wird (optional)', 'What is said in the reference (optional)')}"></div>
      <div><button class="btn primary" id="v_go">${t('Erzeugen', 'Generate')}</button> <span class="dim small">${t('Ohne Referenz: Standardstimme (bzw. Piper im Lite-Modus).', 'Without a reference: default voice (Piper in Lite mode).')}</span></div></div>`)}
    ${panel(t('Hinweis', 'Note'), '', `<div class="small dim">${t('Stimmen nur mit Einverständnis der Person klonen. Alles bleibt auf diesem Rechner.', 'Only clone voices with the person’s consent. Everything stays on this computer.')}</div>`)}</div>
    <div style="margin-top:16px">${panel(t('Aufnahmen', 'Recordings'), '~/Toravo/Voice', list)}</div>`;
  $('#v_go').onclick = async () => {
    let ref = '';
    const f = $('#v_f').files[0];
    if (f) { const r = await fetch('/api/upload?kind=voice', {method: 'POST', headers: {'X-Toravo': '1', 'X-Filename': f.name}, body: f}); ref = (await r.json()).path; }
    addJob('voice', t('Stimme', 'Voice'), {text: $('#v_t').value, ref, ref_text: $('#v_rt').value}, 'stimme');
  };
  drawWaves();
}

async function pageVideo() {
  const songs = await api('/api/files?kind=song');
  const list = await fileList('video', fs => `<div class="vgrid">${fs.map(f => `<div><video controls preload="none" poster="${f.url.replace('/files/', '/poster/')}" src="${f.url}"></video><div class="small" style="margin-top:6px">${esc(f.name)}</div></div>`).join('')}</div>`);
  $('#main').innerHTML = `<span class="label v">LTX-Video · ComfyUI</span><h1>Turn it into a music video.</h1>
    ${panel(t('Neues Musikvideo', 'New music video'), '', `<div class="form"><div class="row2"><select id="m_s">${songs.map(s => `<option value="${esc(s.path)}">${esc(s.name)}</option>`).join('') || `<option value="">${t('– erst einen Song machen –', '– make a song first –')}</option>`}</select>
      <input id="m_style" placeholder="${t('Bildstil, z. B.', 'Visual style, e.g.')} fantasy sky islands, golden hour, cinematic"></div>
      <div><button class="btn primary" id="m_go">${t('Rendern', 'Render')}</button> <span class="dim small">${t('Ohne passende GPU: Lite-Musikvideo (Bild + Wellenform + Lyrics) mit FFmpeg.', 'Without a suitable GPU: Lite music video (image + waveform + lyrics) with FFmpeg.')}</span></div></div>`)}
    <div style="margin-top:16px">${panel('Videos', '~/Toravo/Videos', list)}</div>`;
  $('#m_go').onclick = () => { const s = $('#m_s').value; if (!s) return; const subj = s.split('/').pop().replace(/\.[^.]+$/, ''); addJob('video', t(`Musikvideo „${subj}“`, `Music video “${subj}”`), {input: s, style: $('#m_style').value}, subj); };
}

async function pageShorts() {
  const vids = await api('/api/files?kind=video');
  const list = await fileList('shorts', fs => `<div class="vgrid v916">${fs.map(f => `<div><video controls preload="none" poster="${f.url.replace('/files/', '/poster/')}" src="${f.url}"></video><div class="small" style="margin-top:6px">${esc(f.name)}</div></div>`).join('')}</div>`);
  $('#main').innerHTML = `<span class="label v">Shorts · Thumbnails</span><h1>Cut the Shorts.</h1>
    ${panel('Shorts-Cutter', 'auto 9:16 · captions', `<div class="form"><div class="row2"><select id="c_v">${vids.map(s => `<option value="${esc(s.path)}">${esc(s.name)}</option>`).join('') || `<option value="">${t('– erst ein Video –', '– make a video first –')}</option>`}</select>
      <div class="row2"><input id="c_n" type="number" min="1" max="10" value="3"><input id="c_l" type="number" min="5" max="90" value="30"></div></div>
      <div><button class="btn primary" id="c_go">${t('Shorts schneiden', 'Cut Shorts')}</button> <span class="dim small">${t('beat-starke Stellen · 9:16 · Untertitel (Whisper) · HW-Encoder wenn vorhanden', 'strongest beats · 9:16 · captions (Whisper) · HW encoder if available')}</span></div></div>`)}
    <div style="margin-top:16px">${panel('Shorts', '~/Toravo/Shorts', list)}</div>`;
  $('#c_go').onclick = () => { const v = $('#c_v').value; if (!v) return; const subj = v.split('/').pop().replace(/\.[^.]+$/, ''); addJob('shorts', t(`${$('#c_n').value} Shorts „${subj}“`, `${$('#c_n').value} Shorts “${subj}”`), {input: v, count: +$('#c_n').value, length: +$('#c_l').value}, subj); };
}

async function pageThumb() {
  const vids = await api('/api/files?kind=video');
  const list = await fileList('thumbnail', fs => `<div class="thumbs">${fs.map(f => `<div><img src="${f.url}" loading="lazy"><div class="small" style="margin-top:6px">${esc(f.name)}</div></div>`).join('')}</div>`);
  $('#main').innerHTML = `<span class="label v">Qwen-Image · A/B</span><h1>Design the thumbnail.</h1>
    ${panel(t('Neues Thumbnail', 'New thumbnail'), '', `<div class="form"><div class="row2"><input id="t_t" placeholder="${t('Titel auf dem Bild, z. B.', 'Title on the image, e.g.')} FREE VOICE CLONE"><select id="t_v"><option value="">${t('– ohne Video –', '– no video –')}</option>${vids.map(s => `<option value="${esc(s.path)}">${esc(s.name)}</option>`).join('')}</select></div>
      <input id="t_p" placeholder="${t('Bildidee (für Qwen-Image), z. B.', 'Image idea (for Qwen-Image), e.g.')} bold FREE, cyan rim light, keep NO SUBSCRIPTION badge">
      <div><button class="btn primary" id="t_go">${t('A/B erzeugen', 'Make A/B')}</button> <span class="dim small">${t('Ohne GPU: Vorlagen aus Videoframes.', 'Without a GPU: templates from video frames.')}</span></div></div>`)}
    <div style="margin-top:16px">${panel('Thumbnails', '~/Toravo/Thumbnails', list)}</div>`;
  $('#t_go').onclick = () => { const ti = $('#t_t').value || 'Toravo'; addJob('thumbnail', t(`Thumbnail „${ti}“`, `Thumbnail “${ti}”`), {title: ti, prompt: $('#t_p').value, input: $('#t_v').value}, ti); };
}

async function pageCalendar() {
  const [cal, vids, shorts, thumbs] = await Promise.all([api('/api/calendar'), api('/api/files?kind=video'), api('/api/files?kind=shorts'), api('/api/files?kind=thumbnail')]);
  const opts = [...vids, ...shorts].map(f => `<option value="${esc(f.path)}">${esc(f.name)}</option>`).join('');
  const needs = cal.filter(c => c.state === 'needs_approval').length;
  $('#main').innerHTML = `<span class="label v">Calendar · Approval</span><h1>Schedule it.</h1>
    ${panel(t('Neuer Termin', 'New slot'), '', `<div class="form"><div class="row2"><input id="k_t" placeholder="${t('Titel', 'Title')}"><select id="k_f">${opts}</select></div>
      <div class="row2"><div class="row2"><input id="k_d" type="date"><input id="k_h" type="time" value="17:00"></div><div class="row2"><select id="k_p"><option>YouTube</option><option>YouTube Shorts</option><option>TikTok</option><option>Instagram</option></select>
      <select id="k_th"><option value="">– Thumbnail –</option>${thumbs.map(f => `<option value="${esc(f.path)}">${esc(f.name)}</option>`).join('')}</select></div></div>
      <div><button class="btn primary" id="k_go">${t('Einplanen', 'Schedule')}</button> <span class="dim small">${t('Neue Termine brauchen deine Freigabe. Veröffentlicht wird in Phase 1 von Hand: „Bereitlegen“ legt alles in ~/Toravo/Veröffentlichen.', 'New slots need your approval. Publishing is manual in phase 1: “Prepare” puts everything into ~/Toravo/Publish.')}</span></div></div>`)}
    <div style="margin-top:16px">${panel(t('Publishing-Kalender', 'Publishing calendar'), needs ? `NEEDS APPROVAL: ${needs}` : '', calRows(cal, false))}</div>`;
  $('#k_d').value = new Date(Date.now() + 864e5).toISOString().slice(0, 10);
  $('#k_go').onclick = async () => { await api('/api/calendar', {title: $('#k_t').value, file: $('#k_f').value, date: $('#k_d').value, time: $('#k_h').value, platform: $('#k_p').value, thumb: $('#k_th').value}); route(); };
}

async function pageQueue() {
  const jobs = await api('/api/jobs');
  const rows = jobs.slice().reverse().map(j => `<div class="q" style="grid-template-columns:1.3fr 110px 1.6fr 110px 150px"><span>${esc(j.title)}<div class="mono dim small">${new Date(j.created * 1000).toLocaleString().slice(0, 17)}</div></span>
    <span class="chip">${esc(KIND[j.kind] || j.kind)}</span><div><div class="bar"><i style="width:${Math.round((j.progress || 0) * 100)}%"></i></div>
    <div class="mono dim small" style="margin-top:4px">${esc(j.error || j.step || '')}</div><div class="mono small">${(j.outputs || []).map(o => esc(o.split('/').pop())).join(' · ')}</div></div>
    <span class="state st-${j.state}">${esc(STATE[j.state] || j.state)}</span>
    <span>${['queued', 'running'].includes(j.state) ? `<button class="btn sm" onclick="jobAct('${j.id}','cancel')">${t('Abbrechen', 'Cancel')}</button>` : `<button class="btn sm" onclick="jobAct('${j.id}','retry')">${t('Nochmal', 'Retry')}</button> <button class="btn sm danger" onclick="jobAct('${j.id}','delete')">✕</button>`}</span></div>`).join('');
  $('#main').innerHTML = `<span class="label v">${t('Render-Queue', 'Render queue')}</span><h1>Queue.</h1>${panel(t('Alle Jobs', 'All jobs'), `${jobs.length}`, rows || `<div class="empty">${t('Leer.', 'Empty.')}</div>`)}`;
}

async function jobAct(id, act) { await api(`/api/jobs/${id}/${act}`, {}); route(); }

const PAGES = {'': pageHome, song: pageSong, voice: pageVoice, video: pageVideo, shorts: pageShorts, thumbnail: pageThumb, calendar: pageCalendar,
  queue: pageQueue, gpu: pageHome, streams: pageHome};

async function route() {
  const h = location.hash.slice(1);
  document.querySelectorAll('#nav a').forEach(a => a.classList.toggle('on', a.getAttribute('href') === '#' + h || (h === '' && a.getAttribute('href') === '#')));
  try { await (PAGES[h] || pageHome)(); } catch (e) { $('#main').innerHTML = `<div class="panel">${t('Fehler', 'Error')}: ${esc(e)}</div>`; }
  clearInterval(timer);
  if (['', 'queue', 'gpu', 'streams'].includes(h)) timer = setInterval(() => { if (!document.activeElement || !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) (PAGES[h] || pageHome)(); }, 3000);
}

$('#cmd').onsubmit = async e => {
  e.preventDefault();
  const text = $('#cmdin').value.trim(); if (!text) return;
  const box = $('#planbox'); box.classList.remove('hidden'); box.innerHTML = `<span class="label c">Command Bar</span><div class="empty">${t('Plane …', 'Planning …')}</div>`;
  const p = await api('/api/plan', {text});
  box.innerHTML = `<div class="phead"><span class="label c">Command Bar</span><span class="label">${esc(p.provider || '')}</span></div><div class="mono small" style="margin-bottom:8px">❯ ${esc(text)}</div>` +
    p.steps.map(s => `<div class="step"><span class="ic">${s.ready ? '●' : '○'}</span><span style="flex:1">${esc(s.title)}</span><span class="chip">${esc(KIND[s.kind] || s.kind)}${s.engine === 'lite' ? ' · LITE' : ''}${s.ready ? '' : t(' · FEHLT', ' · MISSING')}</span></div>`).join('') +
    `<div style="margin-top:12px;display:flex;gap:8px"><button class="btn primary" id="p_run">${t('Ausführen', 'Run')}</button><button class="btn" id="p_x">${t('Schließen', 'Close')}</button></div>`;
  $('#p_x').onclick = () => box.classList.add('hidden');
  $('#p_run').onclick = async () => { await api('/api/plan/run', {plan: p}); box.classList.add('hidden'); $('#cmdin').value = ''; location.hash = 'queue'; };
};

// static texts in index.html (German in the file, English via data-en)
if (LANG !== 'de') document.querySelectorAll('[data-en]').forEach(el => { el.textContent = el.dataset.en; });
if (LANG !== 'de' && $('#cmdin').dataset.enPlaceholder) $('#cmdin').placeholder = $('#cmdin').dataset.enPlaceholder;
window.addEventListener('hashchange', route);
route();
