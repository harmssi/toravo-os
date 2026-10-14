"""Toravo Studio Local – the studio as a local app (127.0.0.1:8890 only). No accounts, no cloud, no uploads.

Song · Voice · Video · Shorts · Thumbnail · Kalender mit Freigabe · Render-Queue · GPU – all on top of the local
render queue (toravo.queue) and the AI stack installed by Toravo Setup. Publishing stays manual: approved posts are
prepared in ~/Toravo/Veröffentlichen/<datum>/ (no platform logins in Phase 1).
"""
import json, mimetypes, os, re, shutil, subprocess, sys, threading, time, urllib.parse, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .. import queue, stack, agent, executors

STATIC = os.path.join(os.path.dirname(__file__), 'static')
HOME = os.path.expanduser('~/Toravo')
KINDS = {'song': 'Songs', 'voice': 'Voice', 'video': 'Videos', 'shorts': 'Shorts', 'thumbnail': 'Thumbnails', 'publish': 'Veröffentlichen'}
CAL = os.path.expanduser('~/.local/share/toravo/calendar.json')
EXT = {'song': ('.flac', '.wav', '.mp3', '.ogg', '.m4a'), 'voice': ('.wav', '.mp3', '.flac', '.ogg'), 'video': ('.mp4', '.mkv', '.webm', '.mov'),
       'shorts': ('.mp4',), 'thumbnail': ('.png', '.jpg', '.jpeg', '.webp'), 'publish': ('.mp4', '.png', '.jpg', '.txt')}
LOCK = threading.Lock()


def gpu_stats():
    try:
        r = subprocess.run(['nvidia-smi', '--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,name',
                            '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=3)
        if r.returncode == 0 and r.stdout.strip():
            u, mu, mt, t, n = [x.strip() for x in r.stdout.splitlines()[0].split(',')]
            return {'name': n, 'util': int(u), 'vram_used': round(float(mu) / 1024, 1), 'vram_total': round(float(mt) / 1024, 1), 'temp': int(t)}
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    import glob
    for dev in glob.glob('/sys/class/drm/card[0-9]/device'):
        try:
            busy = int(open(dev + '/gpu_busy_percent').read())
            used = int(open(dev + '/mem_info_vram_used').read()) / 2**30
            tot = int(open(dev + '/mem_info_vram_total').read()) / 2**30
            temp = 0
            for t in glob.glob(dev + '/hwmon/hwmon*/temp1_input'):
                temp = int(open(t).read()) // 1000
            return {'name': 'AMD GPU', 'util': busy, 'vram_used': round(used, 1), 'vram_total': round(tot, 1), 'temp': temp}
        except (OSError, ValueError):
            continue
    try:
        load = os.getloadavg()[0] / (os.cpu_count() or 1) * 100
    except OSError:
        load = 0
    return {'name': 'CPU', 'util': int(min(100, load)), 'vram_used': 0, 'vram_total': 0, 'temp': 0}


def files(kind):
    base = os.path.join(HOME, KINDS[kind])
    out = []
    for root, dirs, fs in os.walk(base):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for f in fs:
            if f.lower().endswith(EXT[kind]) and not f.startswith('.'):
                p = os.path.join(root, f)
                rel = os.path.relpath(p, base)
                st = os.stat(p)
                out.append({'name': f, 'rel': rel, 'path': p, 'size': st.st_size, 'mtime': st.st_mtime,
                            'url': f'/files/{kind}/' + urllib.parse.quote(rel)})
    return sorted(out, key=lambda x: -x['mtime'])[:300]


def cal_load():
    try:
        with open(CAL) as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def cal_save(items):
    os.makedirs(os.path.dirname(CAL), exist_ok=True)
    tmp = CAL + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(items, f, indent=2, ensure_ascii=False)
    os.replace(tmp, CAL)


def tools_state():
    st = stack.load_state()
    s = stack.load_stack()
    res = []
    for t in s['tools']:
        cur = st.get('tools', {}).get(t['id'], {})
        res.append({'id': t['id'], 'title': t['title'], 'area': t['area'], 'engine': t['engine'], 'variant': cur.get('label') or '',
                    'ready': stack.tool_ready(t['id'], st) if cur else False, 'off': cur.get('off', False)})
    return {'tools': res, 'hardware': st.get('hardware') or {}, 'setup_done': os.path.exists(os.path.expanduser('~/.config/toravo/setup-done'))}


class H(BaseHTTPRequestHandler):
    server_version = 'ToravoStudio/1'

    def log_message(self, *a):
        pass

    def send_json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(b)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(b)

    def body(self):
        n = int(self.headers.get('Content-Length') or 0)
        return self.rfile.read(n) if n else b''

    def serve_file(self, path):
        if not os.path.isfile(path):
            return self.send_error(404)
        size = os.path.getsize(path)
        ctype = mimetypes.guess_type(path)[0] or 'application/octet-stream'
        rng = self.headers.get('Range')
        start, end = 0, size - 1
        if rng and (m := re.match(r'bytes=(\d*)-(\d*)', rng)):
            if m.group(1):
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else size - 1
            else:
                start = size - int(m.group(2))
            self.send_response(206)
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        else:
            self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Length', str(end - start + 1))
        self.end_headers()
        with open(path, 'rb') as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = f.read(min(1 << 20, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                left -= len(chunk)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        p = u.path
        q = urllib.parse.parse_qs(u.query)
        if p == '/api/ping':
            return self.send_json({'ok': True})
        if p == '/api/state':
            d = tools_state()
            d['gpu'] = gpu_stats()
            d['live'] = live_state()
            return self.send_json(d)
        if p == '/api/jobs':
            return self.send_json(queue.jobs())
        if p == '/api/files':
            k = (q.get('kind') or ['song'])[0]
            return self.send_json(files(k) if k in KINDS else [])
        if p == '/api/calendar':
            return self.send_json(sorted(cal_load(), key=lambda x: (x.get('date', ''), x.get('time', ''))))
        if p.startswith('/poster/'):  # first frame of a video as JPEG (cached) – no video decoding needed in the page
            parts = p.split('/', 3)
            if len(parts) == 4 and parts[2] in KINDS:
                base = os.path.realpath(os.path.join(HOME, KINDS[parts[2]]))
                full = os.path.realpath(os.path.join(base, urllib.parse.unquote(parts[3])))
                if full.startswith(base + os.sep) and os.path.isfile(full):
                    cache = os.path.expanduser('~/.cache/toravo/posters')
                    os.makedirs(cache, exist_ok=True)
                    key = re.sub(r'[^\w.-]', '_', parts[2] + '_' + parts[3]) + f'_{int(os.path.getmtime(full))}.jpg'
                    out = os.path.join(cache, key)
                    if not os.path.exists(out):
                        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', '3', '-i', full, '-frames:v', '1', '-vf', 'scale=480:-2', out],
                                       capture_output=True, timeout=60)
                    if os.path.exists(out):
                        return self.serve_file(out)
            return self.send_error(404)
        if p.startswith('/files/'):
            parts = p.split('/', 3)
            if len(parts) == 4 and parts[2] in KINDS:
                base = os.path.realpath(os.path.join(HOME, KINDS[parts[2]]))
                full = os.path.realpath(os.path.join(base, urllib.parse.unquote(parts[3])))
                if full.startswith(base + os.sep):
                    return self.serve_file(full)
            return self.send_error(404)
        if p in ('/', '/index.html'):
            return self.serve_file(os.path.join(STATIC, 'index.html'))
        if p.startswith('/static/'):
            full = os.path.realpath(os.path.join(STATIC, p[len('/static/'):]))
            if full.startswith(os.path.realpath(STATIC) + os.sep):
                return self.serve_file(full)
        if p.startswith('/brand/'):
            full = os.path.realpath(os.path.join('/usr/share/toravo/logo', os.path.basename(p)))
            return self.serve_file(full)
        self.send_error(404)

    def do_POST(self):
        if self.headers.get('X-Toravo') != '1':  # blocks cross-site requests from web pages (custom header => CORS preflight)
            return self.send_error(403)
        p = urllib.parse.urlparse(self.path).path
        try:
            data = json.loads(self.body() or b'{}') if not p.startswith('/api/upload') else None
        except ValueError:
            return self.send_json({'error': 'bad json'}, 400)
        if p == '/api/jobs':
            j = queue.add(data['kind'], data.get('title') or data['kind'], data.get('params') or {}, data.get('after') or [], data.get('subject', ''))
            return self.send_json(j)
        m = re.match(r'^/api/jobs/(\w+)/(cancel|retry|delete)$', p)
        if m:
            jid, act = m.groups()
            try:
                j = queue.load(jid)
            except OSError:
                return self.send_json({'error': 'unknown'}, 404)
            if act == 'cancel':
                queue.update(j, state='cancelled', step='abgebrochen')
            elif act == 'retry':
                queue.update(j, state='queued', step='erneut eingereiht', error='', progress=0.0)
            else:
                os.remove(queue._path(jid))
            return self.send_json({'ok': True})
        if p == '/api/plan':
            return self.send_json(agent.readiness(agent.plan(data.get('text', ''))))
        if p == '/api/plan/run':
            return self.send_json({'jobs': queue.enqueue_plan(data['plan'])})
        if p == '/api/stream/start':
            return self.send_json({'pid': executors.start_stream()})
        if p == '/api/setup':
            subprocess.Popen(['toravo-setup'], start_new_session=True)
            return self.send_json({'ok': True})
        if p.startswith('/api/upload'):
            name = os.path.basename(self.headers.get('X-Filename') or f'upload-{uuid.uuid4().hex[:6]}')
            kind = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get('kind', ['song'])[0]
            if kind not in KINDS:
                return self.send_json({'error': 'kind'}, 400)
            d = os.path.join(HOME, KINDS[kind], 'Importiert')
            os.makedirs(d, exist_ok=True)
            dst = os.path.join(d, re.sub(r'[^\w.\- ]', '_', name))
            with open(dst, 'wb') as f:
                f.write(self.body())
            return self.send_json({'path': dst})
        if p == '/api/calendar':
            with LOCK:
                items = cal_load()
                it = {'id': uuid.uuid4().hex[:10], 'date': data.get('date') or time.strftime('%Y-%m-%d'), 'time': data.get('time') or '17:00',
                      'title': data.get('title') or 'Neuer Post', 'platform': data.get('platform') or 'YouTube',
                      'file': data.get('file') or '', 'thumb': data.get('thumb') or '', 'state': 'needs_approval', 'created': time.time()}
                items.append(it)
                cal_save(items)
            return self.send_json(it)
        m = re.match(r'^/api/calendar/(\w+)/(approve|revoke|delete|prepare)$', p)
        if m:
            cid, act = m.groups()
            with LOCK:
                items = cal_load()
                it = next((x for x in items if x['id'] == cid), None)
                if not it:
                    return self.send_json({'error': 'unknown'}, 404)
                if act == 'approve':
                    it['state'] = 'approved'
                    it['approved_at'] = time.time()
                elif act == 'revoke':
                    it['state'] = 'needs_approval'
                elif act == 'delete':
                    items.remove(it)
                elif act == 'prepare':
                    if it['state'] != 'approved':
                        return self.send_json({'error': 'erst freigeben'}, 409)
                    tslug = re.sub(r'[^\w-]+', '-', it['title'].lower())[:40]
                    d = os.path.join(HOME, KINDS['publish'], f"{it['date']}-{tslug}")
                    os.makedirs(d, exist_ok=True)
                    for key in ('file', 'thumb'):
                        if it.get(key) and os.path.exists(it[key]):
                            shutil.copy2(it[key], d)
                    with open(os.path.join(d, 'post.txt'), 'w') as f:
                        f.write(f"{it['title']}\n{it['platform']} · {it['date']} {it['time']}\n")
                    it['state'] = 'ready'
                    it['folder'] = d
                cal_save(items)
            return self.send_json({'ok': True})
        self.send_error(404)


def live_state():
    try:
        st = json.load(open(os.path.expanduser('~/.local/state/toravo/live.json')))
        if os.path.exists(f'/proc/{int(st["pid"])}'):
            return [{'title': st.get('title', 'OBS'), 'since': st['since']}]
    except (OSError, ValueError, KeyError):
        pass
    return []


def main():
    for k in KINDS.values():
        os.makedirs(os.path.join(HOME, k), exist_ok=True)
    port = int(os.environ.get('TORAVO_STUDIO_PORT', '8890'))
    srv = ThreadingHTTPServer(('127.0.0.1', port), H)
    print(f'Toravo Studio Local auf http://127.0.0.1:{port}', flush=True)
    srv.serve_forever()


if __name__ == '__main__':
    main()
