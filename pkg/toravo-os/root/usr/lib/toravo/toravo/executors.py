"""Executors for queue jobs. Each returns {"state": "done"|"needs_tool"|"failed", "outputs": [...], "error": "..."}.

Heavy AI paths (YuE2, VoxCPM, ComfyUI/LTX, Qwen-Image) need Toravo Setup; Lite paths (FFmpeg music video, Shorts,
template thumbnails, Piper, Whisper small on CPU) run on any machine.
"""
import glob, json, math, os, random, re, shutil, struct, subprocess, time, urllib.request, uuid
from . import stack

HOME = os.path.expanduser('~/Toravo')
OUT = {k: os.path.join(HOME, v) for k, v in {'song': 'Songs', 'voice': 'Voice', 'video': 'Videos', 'shorts': 'Shorts',
                                             'thumbnail': 'Thumbnails', 'stems': 'Songs/Stems', 'master': 'Songs/Master',
                                             'transcribe': 'Projekte/Untertitel'}.items()}
RUNNERS = '/usr/lib/toravo/runners'
WORKFLOWS = '/usr/share/toravo/workflows'
COMFY = 'http://127.0.0.1:8188'
AUDIO_EXT = ('.flac', '.wav', '.mp3', '.ogg', '.m4a', '.opus')
VIDEO_EXT = ('.mp4', '.mkv', '.mov', '.webm')


def slug(s):
    s = re.sub(r'[^\w\-]+', '-', (s or 'projekt').strip().lower()).strip('-')
    return s[:48] or 'projekt'


def need(tool, why):
    return {'state': 'needs_tool', 'error': why + ' – Toravo Setup (Command Bar → „Toravo Setup“) richtet es ein, falls deine Hardware es kann.'}


def base():
    return stack.base_dir()


def venv_py(d):
    return os.path.join(base(), d, '.venv', 'bin', 'python')


def run_cmd(cmd, prog=None, step=None, env=None, parse=None, cwd=None):
    """Run a command, stream output into the job step. parse(line) -> progress float or None."""
    e = dict(os.environ)
    e.update(env or {})
    envsh = os.path.join(base(), 'env.sh')
    if os.path.exists(envsh):
        for line in open(envsh):
            m = re.match(r'export (\w+)=(.*)', line.strip())
            if m:
                e.setdefault(m.group(1), m.group(2))
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=e, cwd=cwd, bufsize=1)
    tail = []
    for line in p.stdout:
        line = line.rstrip()
        tail = (tail + [line])[-30:]
        if prog:
            pv = parse(line) if parse else None
            prog(pv, (step + ' · ' if step else '') + line[-90:] if line else None)
    p.wait()
    if p.returncode != 0:
        raise RuntimeError(f'{os.path.basename(cmd[0])} Exit {p.returncode}: ' + ' | '.join(tail[-4:])[-400:])


# ------------------------------------------------------------------------------------------------ inputs
def latest(folder, exts, subject=''):
    files = [f for f in glob.glob(os.path.join(folder, '**', '*'), recursive=True) if f.lower().endswith(exts)]
    if subject:
        pref = [f for f in files if slug(subject) in slug(os.path.basename(f))]
        files = pref or files
    return max(files, key=os.path.getmtime) if files else None


def find_input(job, deps, exts, folder):
    p = job['params'].get('input')
    if p and os.path.exists(os.path.expanduser(p)):
        return os.path.expanduser(p)
    for d in deps:
        for o in d.get('outputs', []):
            if o.lower().endswith(exts):
                return o
    return latest(folder, exts, job.get('subject', ''))


def duration(path):
    try:
        out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path], capture_output=True, text=True, timeout=30).stdout
        return float(out.strip())
    except (ValueError, OSError, subprocess.SubprocessError):
        return 0.0


# ------------------------------------------------------------------------------------------------ encoder
_ENC = {}


def encoder():
    """Best working H.264 encoder: NVENC > VAAPI > QSV > x264. Tested once per process."""
    if 'v' in _ENC:
        return _ENC['v']
    st = stack.load_state().get('hardware', {})
    cands = list(st.get('encoders') or [])
    order = ['h264_nvenc', 'h264_vaapi', 'h264_qsv', 'libx264']
    cands = [c for c in order if c in cands or c == 'libx264']
    render = sorted(glob.glob('/dev/dri/renderD*'))
    for c in cands:
        args = enc_args(c, render[0] if render else None)
        test = ['ffmpeg', '-hide_banner', '-v', 'error'] + args['pre'] + ['-f', 'lavfi', '-i', 'color=c=black:s=256x256:d=0.2'] + \
            (['-vf', args['vf']] if args['vf'] else []) + args['codec'] + ['-f', 'null', '-']
        try:
            if subprocess.run(test, capture_output=True, timeout=30).returncode == 0:
                _ENC['v'] = (c, render[0] if render else None)
                return _ENC['v']
        except (OSError, subprocess.SubprocessError):
            pass
    _ENC['v'] = ('libx264', None)
    return _ENC['v']


def enc_args(c, dev=None):
    if c == 'h264_nvenc':
        return {'pre': [], 'vf': '', 'codec': ['-c:v', 'h264_nvenc', '-preset', 'p5', '-cq', '20', '-b:v', '0']}
    if c == 'h264_vaapi':
        return {'pre': ['-vaapi_device', dev or '/dev/dri/renderD128'], 'vf': 'format=nv12,hwupload', 'codec': ['-c:v', 'h264_vaapi', '-qp', '20']}
    if c == 'h264_qsv':
        return {'pre': [], 'vf': '', 'codec': ['-c:v', 'h264_qsv', '-global_quality', '22']}
    return {'pre': [], 'vf': '', 'codec': ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p']}


def ffmpeg_encode(inputs, filtergraph, maps, out, prog=None, total=0.0, extra=()):
    """Encode with the best encoder; VAAPI gets hwupload appended to the final video label."""
    c, dev = encoder()
    a = enc_args(c, dev)
    fg = filtergraph
    vmap = maps[0]
    if a['vf']:
        fg += f';{vmap}{a["vf"]}[venc]'
        vmap = '[venc]'
    elif c == 'libx264':
        pass
    cmd = ['ffmpeg', '-hide_banner', '-y'] + a['pre'] + inputs + ['-filter_complex', fg, '-map', vmap] + \
        sum((['-map', m] for m in maps[1:]), []) + a['codec'] + ['-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart'] + list(extra) + \
        ['-progress', 'pipe:1', '-nostats', out]

    def parse(line):
        m = re.match(r'out_time_ms=(\d+)', line)
        if m and total:
            return min(.99, int(m.group(1)) / 1e6 / total)
        return None
    try:
        run_cmd(cmd, prog, 'FFmpeg ' + c, parse=parse)
    except RuntimeError:
        if c == 'libx264':
            raise
        _ENC['v'] = ('libx264', None)  # HW encoder failed on this input -> software
        return ffmpeg_encode(inputs, filtergraph, maps, out, prog, total, extra)


# ------------------------------------------------------------------------------------------------ comfyui
def comfy_up(prog):
    def alive():
        try:
            urllib.request.urlopen(COMFY + '/system_stats', timeout=3).read()
            return True
        except OSError:
            return False
    if alive():
        return True
    subprocess.run(['systemctl', '--user', 'start', 'toravo-comfyui.service'], capture_output=True)
    for i in range(90):
        prog(None, f'ComfyUI startet … {i * 2}s')
        if alive():
            return True
        time.sleep(2)
    return False


def fill(obj, values):
    if isinstance(obj, dict):
        return {k: fill(v, values) for k, v in obj.items() if not k.startswith('_')}
    if isinstance(obj, list):
        return [fill(v, values) for v in obj]
    if isinstance(obj, str) and obj.startswith('{{') and obj.endswith('}}'):
        return values.get(obj[2:-2], obj)
    if isinstance(obj, str) and '{{' in obj:
        for k, v in values.items():
            obj = obj.replace('{{' + k + '}}', str(v))
    return obj


def comfy_run(workflow, values, outdir, prog, label):
    with open(os.path.join(WORKFLOWS, workflow)) as f:
        wf = fill(json.load(f), values)
    body = json.dumps({'prompt': wf, 'client_id': 'toravo-' + uuid.uuid4().hex[:8]}).encode()
    req = urllib.request.Request(COMFY + '/prompt', data=body, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as r:
        pid = json.load(r)['prompt_id']
    t0 = time.time()
    while True:
        time.sleep(2)
        with urllib.request.urlopen(f'{COMFY}/history/{pid}', timeout=30) as r:
            hist = json.load(r)
        if pid in hist:
            h = hist[pid]
            if h.get('status', {}).get('status_str') == 'error':
                raise RuntimeError('ComfyUI-Fehler: ' + json.dumps(h['status'].get('messages', []))[-300:])
            files = []
            for node in h.get('outputs', {}).values():
                for key in ('images', 'videos', 'gifs', 'audio'):
                    for it in node.get(key, []):
                        q = urllib.parse.urlencode({'filename': it['filename'], 'subfolder': it.get('subfolder', ''), 'type': it.get('type', 'output')})
                        dst = os.path.join(outdir, it['filename'])
                        with urllib.request.urlopen(f'{COMFY}/view?{q}', timeout=120) as r, open(dst, 'wb') as f:
                            shutil.copyfileobj(r, f)
                        files.append(dst)
            return files
        prog(None, f'{label} · ComfyUI rechnet … {int(time.time() - t0)}s')


import urllib.parse  # noqa: E402


# ------------------------------------------------------------------------------------------------ LLM helpers
def llm(prompt, fallback):
    try:
        from .agent import llm_model
        model = llm_model()
        if not model:
            return fallback
        body = {'model': model, 'stream': False, 'think': False, 'options': {'temperature': 0.8},
                'messages': [{'role': 'user', 'content': prompt}]}
        req = urllib.request.Request('http://127.0.0.1:11434/api/chat', data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=120) as r:
            txt = json.load(r)['message']['content'].strip()
        return txt or fallback
    except Exception:  # noqa: BLE001
        return fallback


# ------------------------------------------------------------------------------------------------ song
def do_song(job, deps, prog):
    if not stack.tool_ready('song'):
        return need('song', 'YuE2 ist nicht eingerichtet (braucht NVIDIA mit ≥ 16 GB VRAM)')
    p = job['params']
    subject = job.get('subject') or 'song'
    style = p.get('style') or subject
    lyrics = p.get('lyrics') or llm(
        f'Write song lyrics for a song called "{subject}". Style: {style}. Use section tags [verse], [chorus], [bridge] on their own '
        f'lines, 2 verses, chorus twice, English, no commentary.',
        f'[verse]\n{subject}, rise on the wind\nevery light is calling me\n\n[chorus]\n{subject}, {subject}\nwe were made to fly\n')
    os.makedirs(OUT['song'], exist_ok=True)
    work = os.path.join(OUT['song'], '.work', job['id'])
    os.makedirs(work, exist_ok=True)
    lf = os.path.join(work, 'lyrics.txt')
    open(lf, 'w').write(lyrics)
    out = os.path.join(OUT['song'], slug(subject) + '.flac')
    if os.path.exists(out):
        out = os.path.join(OUT['song'], f'{slug(subject)}-{time.strftime("%H%M%S")}.flac')
    yue = os.path.join(base(), 'yue2', '.venv', 'bin', 'yue2')
    model = stack.model_dest(stack.load_stack(), 'yue2-3b')
    vae = stack.model_dest(stack.load_stack(), 'yue2-vae')
    run_cmd([yue, 'generate', '--model', model, '--vae', vae, '--offline', '--style', style, '--lyrics-file', lf, '--output', out],
            prog, 'YuE2', env={'HF_HUB_OFFLINE': '1'})
    return {'outputs': [out, lf]}


# ------------------------------------------------------------------------------------------------ voice
def do_voice(job, deps, prog):
    p = job['params']
    text = p.get('text') or p.get('prompt') or ''
    os.makedirs(OUT['voice'], exist_ok=True)
    out = os.path.join(OUT['voice'], f'{slug(job.get("subject") or "stimme")}-{time.strftime("%Y%m%d-%H%M%S")}.wav')
    st = stack.load_state()
    variant = st.get('tools', {}).get('voice', {}).get('variant')
    if variant and variant.startswith('voxcpm') and stack.tool_ready('voice', st):
        model = stack.model_dest(stack.load_stack(), 'voxcpm2')
        args = [venv_py('voxcpm'), os.path.join(RUNNERS, 'voxcpm_tts.py'), '--model', model, '--text', text, '--out', out]
        if p.get('ref'):
            args += ['--ref', os.path.expanduser(p['ref'])] + (['--ref-text', p['ref_text']] if p.get('ref_text') else [])
        run_cmd(args, prog, 'VoxCPM2')
    elif stack.tool_ready('voice', st):
        voices = os.path.join(base(), 'piper', 'voices')
        lang = 'de' if re.search(r'[äöüß]|\b(und|der|die|das|ist)\b', text.lower()) else 'en'
        onnx = glob.glob(os.path.join(voices, ('de_DE' if lang == 'de' else 'en_US') + '*.onnx'))
        if not onnx:
            return need('voice', 'Piper-Stimme fehlt')
        prog(.3, 'Piper spricht …')
        piper = os.path.join(base(), 'piper', '.venv', 'bin', 'piper')
        r = subprocess.run([piper, '-m', onnx[0], '-f', out], input=text, text=True, capture_output=True)
        if r.returncode != 0:
            raise RuntimeError(r.stderr[-300:])
    else:
        return need('voice', 'Keine Sprach-Engine eingerichtet')
    return {'outputs': [out]}


# ------------------------------------------------------------------------------------------------ transcribe
def transcribe(src, out_srt, prog, words=False):
    st = stack.load_state()
    if not stack.tool_ready('whisper', st):
        return False
    s = stack.load_stack()
    var = st['tools']['whisper']['variant']
    v = next(x for x in next(t for t in s['tools'] if t['id'] == 'whisper')['variants'] if x['id'] == var)
    mdir = stack.model_dest(s, v['models'][0])
    run_cmd([venv_py('whisper'), os.path.join(RUNNERS, 'whisper_srt.py'), src, out_srt, mdir, v.get('device', 'cpu')] + (['--words'] if words else []),
            prog, 'Whisper')
    return True


def do_transcribe(job, deps, prog):
    src = find_input(job, deps, AUDIO_EXT + VIDEO_EXT, HOME)
    if not src:
        return {'state': 'failed', 'error': 'Keine Audio-/Videodatei gefunden.'}
    os.makedirs(OUT['transcribe'], exist_ok=True)
    out = os.path.join(OUT['transcribe'], os.path.splitext(os.path.basename(src))[0] + '.srt')
    if not transcribe(src, out, prog):
        return need('whisper', 'Whisper ist nicht eingerichtet')
    return {'outputs': [out]}


# ------------------------------------------------------------------------------------------------ stems / master
def do_stems(job, deps, prog):
    if not stack.tool_ready('stems'):
        return need('stems', 'Demucs ist nicht eingerichtet')
    src = find_input(job, deps, AUDIO_EXT, OUT['song'])
    if not src:
        return {'state': 'failed', 'error': 'Kein Song gefunden.'}
    os.makedirs(OUT['stems'], exist_ok=True)
    run_cmd([os.path.join(base(), 'demucs', '.venv', 'bin', 'demucs'), '-n', 'htdemucs', '-o', OUT['stems'], src], prog, 'Demucs',
            parse=lambda l: (int(m.group(1)) / 100) if (m := re.search(r'(\d+)%\|', l)) else None)
    d = os.path.join(OUT['stems'], 'htdemucs', os.path.splitext(os.path.basename(src))[0])
    return {'outputs': sorted(glob.glob(os.path.join(d, '*')))}


def do_master(job, deps, prog):
    if not stack.tool_ready('master'):
        return need('master', 'Matchering ist nicht eingerichtet')
    src = find_input(job, deps, AUDIO_EXT, OUT['song'])
    ref = os.path.expanduser(job['params'].get('reference') or '')
    if not ref or not os.path.exists(ref):
        ref = latest(os.path.join(HOME, 'Referenzen'), AUDIO_EXT)
    if not src or not ref:
        return {'state': 'failed', 'error': 'Song oder Referenz-Track fehlt (Referenzen in ~/Toravo/Referenzen ablegen).'}
    os.makedirs(OUT['master'], exist_ok=True)
    out = os.path.join(OUT['master'], os.path.splitext(os.path.basename(src))[0] + '-master.wav')
    run_cmd([venv_py('matchering'), os.path.join(RUNNERS, 'matchering_run.py'), src, ref, out], prog, 'Matchering')
    return {'outputs': [out]}


# ------------------------------------------------------------------------------------------------ images (Pillow)
def grad_strip(path, w, h):
    from PIL import Image
    im = Image.new('RGB', (w, 1))
    for x in range(w):
        t = x / max(1, w - 1)
        a, b, u = ((138, 92, 246), (111, 155, 224), t / .55) if t < .55 else ((111, 155, 224), (90, 176, 208), (t - .55) / .45)
        im.putpixel((x, 0), tuple(int(a[i] + (b[i] - a[i]) * u) for i in range(3)))
    im.resize((w, h)).save(path)
    return path


def toravo_card(path, w, h, title, sub='', frame=None, variant=0, center=False):
    """Template image in Toravo look: dark, violet glow, big bold title. Used for Lite thumbnails + Lite music video bg."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    if frame and os.path.exists(frame):
        img = Image.open(frame).convert('RGB')
        r = max(w / img.width, h / img.height)
        img = img.resize((int(img.width * r) + 1, int(img.height * r) + 1)).crop((0, 0, w, h))
        shade = Image.new('RGB', (w, h), (7, 7, 13))
        mask = Image.linear_gradient('L').rotate(90 if variant else -90).resize((w, h))
        img = Image.composite(shade, img, mask.point(lambda v: int(v * .85)))
    else:
        img = Image.new('RGB', (w, h), (7, 7, 13))
        sw, sh = w // 8, h // 8
        g = Image.new('RGB', (sw, sh), (0, 0, 0))
        d = ImageDraw.Draw(g)
        cx = sw // 2 if center else (int(sw * .75) if variant else int(sw * .62))
        d.ellipse([cx - sw * .30, -sh * .35, cx + sw * .30, sh * .40], fill=(66, 44, 118))   # violet bloom (top)
        d.ellipse([-sw * .18, sh * .80, sw * .22, sh * 1.25], fill=(18, 48, 58))             # cold teal rest (bottom left)
        g = g.filter(ImageFilter.GaussianBlur(sw / 10)).resize((w, h), Image.BICUBIC)
        from PIL import ImageChops
        img = ImageChops.add(img, g)
    d = ImageDraw.Draw(img)

    def font(size, wght):
        f = ImageFont.truetype('/usr/share/fonts/inter/InterVariable.ttf', size)
        try:
            axes = f.get_variation_axes()
            f.set_variation_by_axes([wght if b'eight' in (a.get('name') or b'') or 'eight' in str(a.get('name')) else a['default'] for a in axes])
        except Exception:  # noqa: BLE001
            pass
        return f
    words = (title or '').upper().split()
    size = int(h * (.17 if variant else .15))
    f = font(size, 900)
    lines, cur = [], ''
    for wd in words:
        t = (cur + ' ' + wd).strip()
        if d.textlength(t, font=f) > w * .82 and cur:
            lines.append(cur)
            cur = wd
        else:
            cur = t
    if cur:
        lines.append(cur)
    lines = lines[:3]
    y = h * (.36 if center else (.52 if variant else .30)) - len(lines) * size * .55
    x = w * .07
    for i, ln in enumerate(lines):
        col = (242, 242, 247) if i < len(lines) - 1 or len(lines) == 1 else (138, 92, 246)
        lx = (w - d.textlength(ln, font=f)) / 2 if center else x
        d.text((lx + 4, y + 5), ln, font=f, fill=(0, 0, 0))
        d.text((lx, y), ln, font=f, fill=col)
        y += size * 1.05
    if sub:
        sf = font(int(h * .035), 600)
        sx = (w - d.textlength(sub.upper(), font=sf)) / 2 if center else x
        d.text((sx, y + size * .2), sub.upper(), font=sf, fill=(169, 168, 189))
    if center:
        img.save(path)
        return path
    # gradient bar
    for i in range(int(w * .25)):
        t = i / (w * .25)
        c = (int(138 + (90 - 138) * t), int(92 + (176 - 92) * t), int(246 + (208 - 246) * t))
        d.line([(x + i, h * .9), (x + i, h * .9 + max(4, h // 120))], fill=c)
    img.save(path)
    return path


def frame_at(video, t, out):
    subprocess.run(['ffmpeg', '-hide_banner', '-v', 'error', '-y', '-ss', str(t), '-i', video, '-frames:v', '1', out], capture_output=True)
    return out if os.path.exists(out) else None


def do_thumbnail(job, deps, prog):
    subject = job.get('subject') or 'Toravo'
    title = job['params'].get('title') or subject
    os.makedirs(OUT['thumbnail'], exist_ok=True)
    outs = []
    st = stack.load_state()
    if stack.tool_ready('thumbnail', st) and st['tools']['thumbnail']['variant'].startswith('qwen'):
        s = stack.load_stack()
        v = next(x for x in next(t for t in s['tools'] if t['id'] == 'thumbnail')['variants'] if x['id'] == st['tools']['thumbnail']['variant'])
        if not comfy_up(prog):
            return {'state': 'failed', 'error': 'ComfyUI startet nicht.'}
        prompt = job['params'].get('prompt') or f'YouTube thumbnail background for "{subject}", cinematic, dramatic light, high contrast, no text'
        for k, seed in enumerate((random.randint(1, 2**31), random.randint(1, 2**31))):
            prog(.1 + .4 * k, f'Qwen-Image Variante {"AB"[k]}')
            files = comfy_run(v['workflow'], {'PROMPT': prompt, 'NEG': 'text, watermark, logo, blurry', 'SEED': seed, 'W': 1664, 'H': 928,
                                              'UNET': v['unet'], 'PREFIX': 'toravo/thumb'}, OUT['thumbnail'], prog, 'Thumbnail')
            if files:
                outs.append(toravo_card(os.path.join(OUT['thumbnail'], f'{slug(subject)}-{"AB"[k]}.png'), 1280, 720, title, '', files[0], k))
        return {'outputs': outs}
    # Lite: two template variants from video frames (or the plain Toravo background)
    vid = find_input(job, deps, VIDEO_EXT, OUT['video'])
    if vid and st.get('tools', {}).get('video', {}).get('variant', 'slideshow') == 'slideshow' and not job['params'].get('input'):
        vid = None  # frames of a Lite music video already carry the title – use the clean template instead
    tmp = os.path.join(OUT['thumbnail'], '.frames')
    os.makedirs(tmp, exist_ok=True)
    dur = duration(vid) if vid else 0
    for k in range(2):
        prog(.2 + .4 * k, f'Vorlage {"AB"[k]}')
        fr = frame_at(vid, dur * (.35 if k == 0 else .62), os.path.join(tmp, f'{job["id"]}-{k}.png')) if vid else None
        outs.append(toravo_card(os.path.join(OUT['thumbnail'], f'{slug(subject)}-{"AB"[k]}.png'), 1280, 720, title,
                                'Toravo', fr, k))
    return {'outputs': outs}


# ------------------------------------------------------------------------------------------------ video
def do_video(job, deps, prog):
    song = find_input(job, deps, AUDIO_EXT, OUT['song'])
    if not song:
        return {'state': 'failed', 'error': 'Kein Song für das Musikvideo gefunden (vorher „Song machen“ oder Datei in ~/Toravo/Songs).'}
    subject = job.get('subject') or os.path.splitext(os.path.basename(song))[0]
    os.makedirs(OUT['video'], exist_ok=True)
    out = os.path.join(OUT['video'], f'{slug(subject)}.mp4')
    total = duration(song)
    st = stack.load_state()
    var = st.get('tools', {}).get('video', {}).get('variant', 'slideshow')
    work = os.path.join(OUT['video'], '.work', job['id'])
    os.makedirs(work, exist_ok=True)
    srt = os.path.join(work, 'lyrics.srt')
    has_srt = False
    try:
        prog(.02, 'Lyrics-Untertitel (Whisper) …')
        has_srt = transcribe(song, srt, None)
    except RuntimeError:
        has_srt = False
    if var.startswith('ltxv') and stack.tool_ready('video', st):
        return video_ltx(job, song, subject, total, out, work, srt if has_srt else None, prog, var)
    # Lite: Toravo background + waveform + lyrics
    bg = toravo_card(os.path.join(work, 'bg.png'), 1920, 1080, subject, 'Toravo', None, 0, center=True)
    grad = grad_strip(os.path.join(work, 'grad.png'), 1920, 240)
    sub = f",subtitles='{srt}':force_style='FontName=Inter,FontSize=22,Bold=1,PrimaryColour=&H00F7F2F2,OutlineColour=&H000D0707,Outline=2,MarginV=40'" if has_srt else ''
    fg = (f"[1:a]showwaves=s=1920x240:mode=cline:rate=30:colors=white:scale=sqrt:draw=full,format=gray[m];"
          f"[2:v]format=rgba[g];[g][m]alphamerge[w];"
          f"[0:v]scale=1920:1080,format=rgba[b];[b][w]overlay=0:H-h-200:shortest=1{sub},format=yuv420p[v]")
    ffmpeg_encode(['-loop', '1', '-framerate', '30', '-i', bg, '-i', song, '-loop', '1', '-framerate', '30', '-i', grad], fg, ['[v]', '1:a'], out,
                  prog, total, ['-shortest', '-r', '30'])
    return {'outputs': [out], 'step': 'fertig (Lite-Musikvideo)'}


def video_ltx(job, song, subject, total, out, work, srt, prog, var):
    s = stack.load_stack()
    v = next(x for x in next(t for t in s['tools'] if t['id'] == 'video')['variants'] if x['id'] == var)
    if not comfy_up(prog):
        return {'state': 'failed', 'error': 'ComfyUI startet nicht.'}
    clip_s = 97 / 24
    n = max(4, min(60, int(math.ceil(total / clip_s)))) if total else 12
    style = job['params'].get('style') or subject
    raw = llm(f'Write {n} short visual scene descriptions (one per line, no numbering) for a music video of the song "{subject}", style: {style}. '
              f'Cinematic, consistent main character and world, varied camera moves.', '')
    scenes = [l.strip(' -*0123456789.') for l in raw.splitlines() if len(l.strip()) > 12][:n]
    while len(scenes) < n:
        scenes.append(f'cinematic music video scene for "{subject}", {style}, shot {len(scenes) + 1}, dramatic light, camera slowly moving')
    clips = []
    for i, sc in enumerate(scenes):
        prog(i / n * .9, f'Szene {i + 1}/{n} · LTX-Video')
        files = comfy_run(v['workflow'], {'PROMPT': sc, 'NEG': 'worst quality, blurry, jittery, distorted, text, watermark', 'SEED': random.randint(1, 2**31),
                                          'W': 768, 'H': 512, 'FRAMES': 97, 'CKPT': v['ckpt'], 'PREFIX': f'toravo/{job["id"]}/clip'},
                          work, prog, f'Szene {i + 1}/{n}')
        clips += [f for f in files if f.lower().endswith(VIDEO_EXT)]
    lst = os.path.join(work, 'clips.txt')
    with open(lst, 'w') as f:
        for c in clips:
            f.write(f"file '{c}'\n")
    sub = f",subtitles='{srt}':force_style='FontName=Inter,FontSize=24,Bold=1,Outline=2'" if srt else ''
    fg = f'[0:v]scale=1920:1080:flags=lanczos,fps=30{sub},format=yuv420p[v]'
    ffmpeg_encode(['-f', 'concat', '-safe', '0', '-stream_loop', '-1', '-i', lst, '-i', song], fg, ['[v]', '1:a'], out, prog, total, ['-shortest'])
    return {'outputs': [out]}


# ------------------------------------------------------------------------------------------------ shorts
def loudness(path, step=1.0):
    """RMS per second (mono, 8 kHz) – picks the strongest moments for Shorts."""
    p = subprocess.run(['ffmpeg', '-hide_banner', '-v', 'error', '-i', path, '-ac', '1', '-ar', '8000', '-f', 's16le', '-'], capture_output=True)
    data = p.stdout
    n = len(data) // 2
    per = int(8000 * step)
    vals = []
    for i in range(0, n - per, per):
        chunk = struct.unpack_from('<%dh' % per, data, i * 2)
        vals.append(math.sqrt(sum(x * x for x in chunk[::8]) / (per // 8)))
    return vals


def pick_windows(vals, length, count):
    if not vals:
        return []
    L = max(1, int(length))
    sums = [sum(vals[i:i + L]) for i in range(0, max(1, len(vals) - L + 1))]
    picks = []
    for i in sorted(range(len(sums)), key=lambda k: -sums[k]):
        if all(abs(i - p) >= L for p in picks):
            picks.append(i)
        if len(picks) >= count:
            break
    return sorted(picks)


def do_shorts(job, deps, prog):
    src = find_input(job, deps, VIDEO_EXT, OUT['video'])
    if not src:
        return {'state': 'failed', 'error': 'Kein Video gefunden (vorher „Musikvideo rendern“ oder Datei in ~/Toravo/Videos).'}
    count = int(job['params'].get('count') or 3)
    length = float(job['params'].get('length') or 30)
    subject = job.get('subject') or os.path.splitext(os.path.basename(src))[0]
    os.makedirs(OUT['shorts'], exist_ok=True)
    prog(.03, 'suche die stärksten Momente …')
    total = duration(src)
    length = min(length, max(5.0, total))
    if total and count * length >= total - 1:  # not enough material for N separate cuts -> shorter cuts
        length = max(5.0, total / count - 1)
    starts = pick_windows(loudness(src), length, count) or [0]
    outs = []
    work = os.path.join(OUT['shorts'], '.work', job['id'])
    os.makedirs(work, exist_ok=True)
    for k, st in enumerate(starts):
        base_p = k / len(starts)
        seg = os.path.join(work, f'seg{k}.wav')
        subprocess.run(['ffmpeg', '-hide_banner', '-v', 'error', '-y', '-ss', str(st), '-t', str(length), '-i', src, '-vn', '-ac', '1', '-ar', '16000', seg], capture_output=True)
        srt = os.path.join(work, f'seg{k}.srt')
        has = False
        try:
            has = transcribe(seg, srt, lambda p, s: prog(base_p + .3 / len(starts), s), words=True)
        except RuntimeError:
            has = False
        out = os.path.join(OUT['shorts'], f'{slug(subject)}-short-{k + 1}.mp4')
        fit_pre = job['params'].get('fit') or ('blur' if stack.load_state().get('tools', {}).get('video', {}).get('variant', 'slideshow') == 'slideshow' else 'crop')
        title = subject.upper().replace("'", '').replace(':', ' ')
        cap = (f",subtitles='{srt}':force_style='FontName=Inter,FontSize=15,Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
               f"Outline=3,Shadow=0,Alignment=2,MarginV={300 if fit_pre == 'blur' else 110}'") if has else ''
        fit = job['params'].get('fit') or ('blur' if stack.load_state().get('tools', {}).get('video', {}).get('variant', 'slideshow') == 'slideshow' else 'crop')
        if fit == 'blur':
            base = ("[0:v]split[a][b];[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=24:2,eq=brightness=-0.08[bg];"
                    "[b]scale=1080:-2[fgv];[bg][fgv]overlay=(W-w)/2:(H-h)/2")
        else:
            base = "[0:v]crop=ih*9/16:ih,scale=1080:1920:flags=lanczos"
        fg = (f"{base}{cap},"
              f"drawtext=fontfile=/usr/share/fonts/inter/InterVariable.ttf:text='{title}':fontcolor=0xf2f2f7:fontsize=54:x=(w-text_w)/2:y=170:"
              f"box=1:boxcolor=0x07070dcc:boxborderw=22,format=yuv420p[v]")
        ffmpeg_encode(['-ss', str(st), '-t', str(length), '-i', src], fg, ['[v]', '0:a?'], out,
                      lambda p, s: prog(base_p + (p or 0) / len(starts), f'Short {k + 1}/{len(starts)} · {s or ""}'), length)
        outs.append(out)
    return {'outputs': outs, 'step': f'{len(outs)} Shorts fertig' + ('' if stack.tool_ready('whisper') else ' (ohne Untertitel – Whisper fehlt)')}


# ------------------------------------------------------------------------------------------------ stream
def start_stream():
    """Start OBS (streaming with the user's OBS profile). Live state for the Waybar dot."""
    state = os.path.expanduser('~/.local/state/toravo')
    os.makedirs(state, exist_ok=True)
    if not shutil.which('obs'):
        subprocess.Popen(['notify-send', '-a', 'Toravo', 'OBS fehlt', 'Toravo Setup → Streams (OBS) einrichten.'])
        return None
    p = subprocess.Popen(['obs', '--startstreaming', '--minimize-to-tray', '--disable-shutdown-check'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with open(os.path.join(state, 'live.json'), 'w') as f:
        json.dump({'pid': p.pid, 'since': time.time(), 'title': 'OBS'}, f)
    return p.pid


EXEC = {'song': do_song, 'voice': do_voice, 'video': do_video, 'shorts': do_shorts, 'thumbnail': do_thumbnail,
        'stems': do_stems, 'master': do_master, 'transcribe': do_transcribe}


def run(job, deps, prog):
    fn = EXEC.get(job['kind'])
    if not fn:
        return {'state': 'failed', 'error': 'Unbekannte Job-Art: ' + job['kind']}
    return fn(job, deps, prog)
