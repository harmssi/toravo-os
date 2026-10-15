"""Toravo Companion service (15.10.2026) – HTTPS API v1 for the iPhone app "Toravo Companion" (contract: docs/COMPANION.md).

python3 -m toravo.companion.server   (systemd user unit toravo-companion.service; off by default, Studio › Connect phone turns it on)
- port 8891 (TORAVO_COMPANION_PORT), all interfaces (TORAVO_COMPANION_BIND), TLS with the PC's own key (the app pins its fingerprint)
- only clients from private networks (else 403); every request except hello/pair needs a device token (Bearer)
- the phone never sends a plan: it asks for one (/plan) and runs it by plan_id (made here, 15 min, once)
- pause = state 'paused' for queued jobs (the queue runner only takes 'queued'); events = queue state changes, seq = ms time
- Bonjour: avahi-publish _toravo._tcp if available (stopped by PID on exit)
"""
import base64, collections, hashlib, json, os, re, secrets, shutil, signal, socket, ssl, subprocess, sys, threading, time, traceback, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .. import queue, agent
from ..theme import tr
from ..studio import server as studio
from . import store

API = 1
MEDIA = ('shorts', 'thumbnail', 'video', 'song')  # ~/Toravo/{Shorts,Thumbnails,Videos,Songs}
VIDEO, IMAGE = ('.mp4', '.mkv', '.webm', '.mov'), ('.png', '.jpg', '.jpeg', '.webp')
MAX_BODY = 20 << 20
PLAN_TTL = 900
EVENT_KINDS = {'running': 'started', 'done': 'done', 'failed': 'failed', 'needs_tool': 'needs_tool', 'cancelled': 'cancelled'}
EVENT_INTERVAL = 1.0
RING = 200
JOBS_MAX = 50


def ev_path():
    d = os.path.expanduser('~/.local/state/toravo/companion')
    os.makedirs(d, mode=0o700, exist_ok=True)
    return os.path.join(d, 'events.json')


def cache_dir():
    d = os.path.expanduser('~/.cache/toravo/companion')
    os.makedirs(d, mode=0o700, exist_ok=True)
    return d


# ------------------------------------------------------------------------------------------------ media
def base(kind):
    return os.path.realpath(os.path.join(studio.HOME, studio.KINDS[kind]))


def mtype(name):
    n = name.lower()
    return 'video' if n.endswith(VIDEO) else 'image' if n.endswith(IMAGE) else 'audio'


def media_id(kind, rel):
    return base64.urlsafe_b64encode(f'{kind}/{rel}'.encode()).decode().rstrip('=')


def media_item(kind, rel, st):
    mid = media_id(kind, rel)
    return {'id': mid, 'kind': kind, 'name': rel.rsplit('/', 1)[-1], 'size': st.st_size, 'mtime': st.st_mtime, 'type': mtype(rel),
            'url': f'/api/v1/media/{mid}', 'poster': f'/api/v1/media/{mid}/poster'}


def resolve(mid):
    """Media id -> (kind, rel, full path) or None. Strict: known kind, no '..', no hidden parts, no absolute paths, no symlink
    anywhere below the base folder, the kind's file types only, a regular file."""
    if not re.fullmatch(r'[A-Za-z0-9_-]{4,2000}', mid or ''):
        return None
    try:
        s = base64.urlsafe_b64decode(mid + '=' * (-len(mid) % 4)).decode('utf-8')
    except (ValueError, UnicodeDecodeError):
        return None
    kind, _, rel = s.partition('/')
    if kind not in MEDIA or not rel or '\x00' in rel or '\\' in rel or rel.startswith('/'):
        return None
    parts = rel.split('/')
    if any(x in ('', '.', '..') or x.startswith('.') for x in parts) or not rel.lower().endswith(studio.EXT[kind]):
        return None
    b = base(kind)
    full = os.path.join(b, *parts)
    if os.path.realpath(full) != full or not full.startswith(b + os.sep) or not os.path.isfile(full):
        return None
    return kind, rel, full


def media_list(kind='all', limit=60):
    out = []
    for k in (MEDIA if kind == 'all' else (kind,)):
        b = base(k)
        for root, dirs, fs in os.walk(b):
            dirs[:] = [d for d in dirs if not d.startswith('.') and not os.path.islink(os.path.join(root, d))]
            for f in fs:
                p = os.path.join(root, f)
                if f.startswith('.') or not f.lower().endswith(studio.EXT[k]) or os.path.islink(p):
                    continue
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                out.append(media_item(k, os.path.relpath(p, b).replace(os.sep, '/'), st))
    return sorted(out, key=lambda m: -m['mtime'])[:limit]


def media_for_path(p):
    if not isinstance(p, str):
        return None
    for k in MEDIA:
        b = base(k)
        if p.startswith(b + os.sep) or os.path.realpath(p).startswith(b + os.sep):
            rel = os.path.relpath(os.path.realpath(p), b).replace(os.sep, '/')
            r = resolve(media_id(k, rel))
            if r:
                return media_item(k, rel, os.stat(r[2]))
    return None


POSTER_SEM = threading.BoundedSemaphore(2)


def poster(kind, rel, full):
    """JPEG preview: first frame (~1 s) of a video, the scaled picture, a waveform for songs. Cached by path + mtime + size."""
    st = os.stat(full)
    key = hashlib.sha256(f'{kind}/{rel}|{st.st_mtime_ns}|{st.st_size}'.encode()).hexdigest()[:32]
    out = os.path.join(cache_dir(), key + '.jpg')
    if os.path.exists(out):
        return out
    with POSTER_SEM:
        if os.path.exists(out):
            return out
        tmp = out + f'.{secrets.token_hex(4)}.tmp.jpg'
        scale = "scale='min(640,iw)':-2"
        t = mtype(rel)
        if t == 'video':
            cmds = [['-ss', ss, '-i', full, '-frames:v', '1', '-vf', scale] for ss in ('1', '0')]
        elif t == 'image':
            cmds = [['-i', full, '-frames:v', '1', '-vf', scale]]
        else:
            cmds = [['-i', full, '-filter_complex', 'showwavespic=s=640x360:colors=0x8a5cf6|0x5ab0d0,format=yuvj420p', '-frames:v', '1']]
        try:
            for c in cmds:
                try:
                    subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y', *c, '-q:v', '4', tmp], capture_output=True, timeout=60)
                except (OSError, subprocess.SubprocessError):
                    break
                if os.path.exists(tmp) and os.path.getsize(tmp) > 0:
                    os.replace(tmp, out)
                    return out
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
    return None


# ------------------------------------------------------------------------------------------------ jobs
def job_out(j):
    st = j.get('state', '')
    return {'id': j.get('id'), 'kind': j.get('kind'), 'title': j.get('title', ''), 'subject': j.get('subject', ''), 'state': st,
            'progress': float(j.get('progress') or 0), 'step': j.get('step', ''), 'created': j.get('created'), 'started': j.get('started'),
            'finished': j.get('finished'), 'error': j.get('error', ''), 'outputs': [m for m in map(media_for_path, j.get('outputs') or []) if m],
            'can_pause': st == 'queued', 'can_resume': st == 'paused', 'can_cancel': st in ('queued', 'paused', 'running')}


def jobs_view():
    """Active jobs first (running, queued, paused), then the newest finished ones – max. 50."""
    js = queue.jobs()
    act = [j for j in js if j.get('state') in ('running', 'queued', 'paused')]
    rest = sorted((j for j in js if j not in act), key=lambda j: -(j.get('finished') or j.get('created') or 0))
    act.sort(key=lambda j: (j.get('state') != 'running', j.get('created') or 0))
    return [job_out(j) for j in (act + rest)[:JOBS_MAX]]


def job_action(jid, act):
    """pause (queued -> paused), resume (paused -> queued), cancel (queued/paused/running -> cancelled, like the Studio).
    Returns (http code, body)."""
    try:
        j = queue.load(jid)
    except (OSError, ValueError):
        return 404, None
    st = j.get('state')
    if act == 'pause' and st == 'queued':
        queue.update(j, state='paused', step=tr('pausiert', 'paused'))
        time.sleep(.3)  # the runner may have taken the job in the same moment – then it is running, not paused
        try:
            j = queue.load(jid)
        except (OSError, ValueError):
            return 404, None
        if j.get('state') != 'paused':
            return 409, j
    elif act == 'resume' and st == 'paused':
        queue.update(j, state='queued', step=tr('wartet', 'waiting'))
    elif act == 'cancel' and st in ('queued', 'paused', 'running'):
        queue.update(j, state='cancelled', step=tr('abgebrochen', 'cancelled'))
    else:
        return 409, j
    return 200, j


# ------------------------------------------------------------------------------------------------ plans
PLANS, PLOCK = {}, threading.Lock()


def strip_studio(p):
    """'Open in Studio' makes no sense from the phone – drop those steps (and fix the 'after' indices). 15.10.2026: 'stream' too –
    going live is public and starts OBS on the PC; small local planners add it to unrelated requests, so the phone never starts it."""
    keep, idx = [], {}
    for i, s in enumerate(p.get('steps', [])):
        if s.get('kind') in ('studio', 'stream'):
            continue
        idx[i] = len(keep)
        keep.append(s)
    for s in keep:
        s['after'] = [idx[a] for a in s.get('after', []) if a in idx]
    p['steps'] = keep
    return p


def make_plan(text, dev_id):
    p = strip_studio(agent.plan(text))
    try:
        agent.readiness(p)
    except Exception:  # noqa: BLE001 – no AI stack definition (e.g. dev machine): show the plan, mark nothing ready
        for s in p['steps']:
            s.setdefault('ready', False)
    pid = secrets.token_urlsafe(16)
    now = time.time()
    with PLOCK:
        for k in [k for k, v in PLANS.items() if v[2] < now]:
            del PLANS[k]
        PLANS[pid] = (dev_id, p, now + PLAN_TTL)
    steps = []
    for s in p['steps']:
        o = {'kind': s['kind'], 'title': s['title'], 'ready': bool(s.get('ready'))}
        if s.get('engine'):
            o['engine'] = s['engine']
        if s['kind'] in ('shorts', 'thumbnail'):
            o['count'] = s.get('params', {}).get('count', 1)
        steps.append(o)
    return {'plan_id': pid, 'title': p.get('title', ''), 'subject': p.get('subject', ''), 'provider': p.get('provider', ''),
            'ready': bool(steps) and all(s['ready'] for s in steps), 'steps': steps}


def take_plan(pid, dev_id):
    with PLOCK:
        v = PLANS.get(pid)
        if not v or v[0] != dev_id or v[2] < time.time():
            return None
        del PLANS[pid]
        return v[1]


# ------------------------------------------------------------------------------------------------ events
class Events:
    """Watches the queue files and turns state changes into events. seq = ms timestamp (monotonic, also across restarts);
    ring buffer + last known states in ~/.local/state/toravo/companion/events.json, so changes while the service was off
    are reported after the start."""

    def __init__(self):
        d = store.read_json(ev_path(), {})
        self.events = d.get('events', [])[-RING:]
        self.seq = int(d.get('seq', 0))
        self.known = d.get('known')
        self.lock = threading.Lock()
        self.stop = threading.Event()

    def next_seq(self):
        self.seq = max(int(time.time() * 1000), self.seq + 1)
        return self.seq

    def scan(self):
        cur = {j['id']: j for j in queue.jobs() if j.get('id')}
        with self.lock:
            first, changed = self.known is None, False
            known = self.known or {}
            for jid, j in cur.items():
                st = j.get('state')
                if known.get(jid) == st:
                    continue
                changed = True
                if not first and st in EVENT_KINDS:
                    self.events.append({'seq': self.next_seq(), 'time': time.time(), 'type': EVENT_KINDS[st], 'job_id': jid,
                                        'title': j.get('title', ''), 'kind': j.get('kind', ''), 'outputs': list(j.get('outputs') or [])})
            if first or changed or set(known) - set(cur):
                self.known = {jid: j.get('state') for jid, j in cur.items()}
                self.events = self.events[-RING:]
                store.write_atomic(ev_path(), json.dumps({'seq': self.seq, 'events': self.events, 'known': self.known}, ensure_ascii=False))

    def since(self, seq):
        with self.lock:
            evs = [dict(e) for e in self.events if e['seq'] > seq]
            last = self.seq
        for e in evs:  # stored as paths, sent as Media (files may have been moved/deleted meanwhile)
            e['outputs'] = [m for m in map(media_for_path, e['outputs']) if m]
        return {'seq': last, 'events': evs}

    def run(self):
        while not self.stop.is_set():
            try:
                self.scan()
            except Exception:  # noqa: BLE001 – keep watching
                traceback.print_exc()
            self.stop.wait(EVENT_INTERVAL)


# ------------------------------------------------------------------------------------------------ limits
class Limits:
    """Token buckets (API per device, plans per device) + sliding windows for wrong pairing codes / bad tokens per IP."""

    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        self.buckets = {}
        self.fails = collections.defaultdict(collections.deque)

    def bucket(self, key, rate, burst):
        """0 if allowed, else seconds to wait."""
        now = time.monotonic()
        with self.lock:
            t, last = self.buckets.get(key, (burst, now))
            t = min(burst, t + (now - last) * rate)
            if t < 1:
                self.buckets[key] = (t, now)
                return (1 - t) / rate
            self.buckets[key] = (t - 1, now)
            return 0

    def blocked(self, keys_limits, window=600):
        """keys_limits: [(key, max)] – seconds until the oldest failure leaves the window, or 0."""
        now = time.monotonic()
        wait = 0
        with self.lock:
            for key, mx in keys_limits:
                q = self.fails[key]
                while q and q[0] <= now - window:
                    q.popleft()
                if len(q) >= mx:
                    wait = max(wait, q[0] + window - now)
        return wait

    def fail(self, *keys):
        now = time.monotonic()
        with self.lock:
            for k in keys:
                self.fails[k].append(now)


LIMITS = Limits()
API_RATE, API_BURST = 10, 30
PLAN_RATE, PLAN_BURST = 6 / 60, 6
PAIR_IP, PAIR_ALL = 5, 20
BADTOKEN_IP = 30


# ------------------------------------------------------------------------------------------------ HTTP
class ApiError(Exception):
    def __init__(self, code, error, message='', retry=None):
        super().__init__(error)
        self.code, self.error, self.message, self.retry = code, error, message, retry


MESSAGES = {'forbidden_network': 'Only from your local network', 'unauthorized': 'Not paired (or removed in the Studio)',
            'not_found': 'Not found', 'bad_code': 'Wrong or expired code', 'rate_limited': 'Too many requests – try again later',
            'too_many_devices': 'Already 10 phones paired – remove one in the Studio', 'bad_state': 'Not possible in this state',
            'bad_request': 'Bad request', 'too_large': 'Request too large', 'unknown_plan': 'Plan unknown, expired or already run',
            'range': 'Range not satisfiable', 'internal': 'Internal error'}


class H(BaseHTTPRequestHandler):
    server_version = 'ToravoCompanion/1'
    sys_version = ''
    protocol_version = 'HTTP/1.1'
    timeout = 60

    def log_message(self, fmt, *a):
        pass

    def log_request(self, code='-', size='-'):  # no query strings, no headers, no bodies (tokens / codes never appear in logs)
        if isinstance(code, int) and code >= 400 or str(code)[:1] in ('4', '5'):
            print(f'{self.command} {urllib.parse.urlparse(self.path).path[:80]} {code}', file=sys.stderr, flush=True)

    def send_json(self, obj, code=200, headers=()):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(b)))
        self.send_header('Cache-Control', 'no-store')
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(b)

    def err(self, e):
        hd = [('Retry-After', str(max(1, int(e.retry + .999))))] if e.retry is not None else []
        self.send_json({'error': e.error, 'message': e.message or MESSAGES.get(e.error, e.error)}, e.code, hd)

    def do_GET(self):
        self.dispatch()

    def do_HEAD(self):
        self.dispatch()

    def do_POST(self):
        self.dispatch()

    def dispatch(self):
        try:
            self.route()
        except ApiError as e:
            self.err(e)
        except (BrokenPipeError, ConnectionResetError, ssl.SSLError, TimeoutError):
            self.close_connection = True
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            self.close_connection = True
            try:
                self.err(ApiError(500, 'internal'))
            except OSError:
                pass

    def read_body(self):
        if self.headers.get('Transfer-Encoding'):
            self.close_connection = True
            raise ApiError(400, 'bad_request', 'Chunked bodies are not supported')
        try:
            n = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            n = -1
        if n < 0 or n > MAX_BODY:
            self.close_connection = True
            raise ApiError(413, 'too_large')
        return self.rfile.read(n) if n else b''

    def json_body(self, raw):
        if not raw:
            return {}
        try:
            d = json.loads(raw)
        except ValueError:
            raise ApiError(400, 'bad_request', 'Invalid JSON') from None
        if not isinstance(d, dict):
            raise ApiError(400, 'bad_request', 'JSON object expected')
        return d

    def auth(self):
        ip = self.client_address[0]
        h = self.headers.get('Authorization') or ''
        tok = h[7:].strip() if h[:7].lower() == 'bearer ' else ''
        dev = store.match_token(tok, self.server.devices()) if tok else None
        if not dev:  # many bad tokens from one address -> 429 (guessing is pointless with 256-bit tokens, but keeps noise down)
            wait = LIMITS.blocked([('tok:' + ip, BADTOKEN_IP)])
            if wait:
                raise ApiError(429, 'rate_limited', retry=wait)
            LIMITS.fail('tok:' + ip)
            raise ApiError(401, 'unauthorized')
        wait = LIMITS.bucket('api:' + dev['id'], API_RATE, API_BURST)
        if wait:
            raise ApiError(429, 'rate_limited', retry=wait)
        self.server.seen(dev['id'])
        return dev

    def route(self):
        ip = self.client_address[0]
        if not store.allowed(ip):
            self.close_connection = True
            raise ApiError(403, 'forbidden_network')
        raw = self.read_body() if self.command == 'POST' else b''
        u = urllib.parse.urlparse(self.path)
        p, q = urllib.parse.unquote(u.path), urllib.parse.parse_qs(u.query)  # 15.10.2026: clients may percent-encode "-" in ids
        m, S = self.command, self.server
        if m == 'HEAD' and not p.startswith('/api/v1/media/'):
            m = 'GET'
        if p == '/api/v1/hello' and m == 'GET':
            return self.send_json({'name': S.ident['name'], 'version': store.version(), 'id': S.ident['id'], 'api': API})
        if p == '/api/v1/pair' and m == 'POST':
            return self.pair(ip, self.json_body(raw))
        if not p.startswith('/api/v1/'):
            raise ApiError(404, 'not_found')
        dev = self.auth()
        if p == '/api/v1/unpair' and m == 'POST':
            store.revoke(dev['id'])
            return self.send_json({'ok': True})
        if p == '/api/v1/status' and m == 'GET':
            return self.send_json({'server': S.info(), 'gpu': S.gpu(), 'jobs': jobs_view(), 'events_seq': S.events.seq, 'time': time.time()})
        if p == '/api/v1/events' and m == 'GET':
            try:
                since = int((q.get('since') or ['0'])[0])
            except ValueError:
                raise ApiError(400, 'bad_request', 'since must be a number') from None
            return self.send_json(S.events.since(since))
        if p == '/api/v1/plan' and m == 'POST':
            text = str(self.json_body(raw).get('text') or '').strip()[:2000]
            if not text:
                raise ApiError(400, 'bad_request', 'text missing')
            wait = LIMITS.bucket('plan:' + dev['id'], PLAN_RATE, PLAN_BURST)
            if wait:
                raise ApiError(429, 'rate_limited', retry=wait)
            return self.send_json(make_plan(text, dev['id']))
        mm = re.fullmatch(r'/api/v1/plans/([A-Za-z0-9_-]{8,64})/run', p)
        if mm and m == 'POST':
            plan = take_plan(mm.group(1), dev['id'])  # the body is ignored – the phone never sends a plan
            if not plan:
                raise ApiError(404, 'unknown_plan')
            return self.send_json({'jobs': queue.enqueue_plan(plan)})
        mm = re.fullmatch(r'/api/v1/jobs/(\w{1,40})/(pause|resume|cancel)', p)
        if mm and m == 'POST':
            code, j = job_action(*mm.groups())
            if code == 404:
                raise ApiError(404, 'not_found')
            if code == 409:
                return self.send_json({'error': 'bad_state', 'message': MESSAGES['bad_state'], 'job': job_out(j)}, 409)
            return self.send_json({'ok': True, 'job': job_out(j)})
        if p == '/api/v1/media' and m == 'GET':
            kind = (q.get('kind') or ['all'])[0]
            if kind != 'all' and kind not in MEDIA:
                raise ApiError(400, 'bad_request', 'unknown kind')
            try:
                limit = max(1, min(300, int((q.get('limit') or ['60'])[0])))
            except ValueError:
                limit = 60
            return self.send_json({'items': media_list(kind, limit)})
        mm = re.fullmatch(r'/api/v1/media/([A-Za-z0-9_-]+)(/poster)?', p)
        if mm and self.command in ('GET', 'HEAD'):
            r = resolve(mm.group(1))
            if not r:
                raise ApiError(404, 'not_found')
            if mm.group(2):
                out = poster(*r)
                if not out:
                    raise ApiError(404, 'not_found', 'No preview for this file')
                return self.send_file(out, 'image/jpeg', cache='private, max-age=86400')
            return self.send_file(r[2], None, name=os.path.basename(r[2]))
        raise ApiError(404, 'not_found')

    def pair(self, ip, d):
        wait = LIMITS.blocked([('pair:' + ip, PAIR_IP), ('pair:*', PAIR_ALL)])
        if wait:
            raise ApiError(429, 'rate_limited', retry=wait)
        if not store.take_code(d.get('code')):
            LIMITS.fail('pair:' + ip, 'pair:*')
            raise ApiError(400, 'bad_code')
        try:
            token, dev = store.add_device(d.get('device'), d.get('model'))
        except store.TooMany:
            raise ApiError(409, 'too_many_devices') from None
        print(f'paired: {dev["name"]} ({dev["id"]})', file=sys.stderr, flush=True)
        self.send_json({'token': token, 'device_id': dev['id'], 'server': self.server.info()})

    def send_file(self, path, ctype, name=None, cache='private, no-cache'):
        st = os.stat(path)
        size = st.st_size
        ctype = ctype or {'.mp4': 'video/mp4', '.mov': 'video/quicktime', '.mkv': 'video/x-matroska', '.webm': 'video/webm', '.png': 'image/png',
                          '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.mp3': 'audio/mpeg', '.m4a': 'audio/mp4',
                          '.wav': 'audio/wav', '.flac': 'audio/flac', '.ogg': 'audio/ogg'}.get(os.path.splitext(path)[1].lower(), 'application/octet-stream')
        etag = f'"{size:x}-{st.st_mtime_ns:x}"'
        start, end, code = 0, size - 1, 200
        rng = self.headers.get('Range')
        if rng and (not self.headers.get('If-Range') or self.headers.get('If-Range') == etag):
            m = re.fullmatch(r'\s*bytes\s*=\s*(\d*)\s*-\s*(\d*)\s*', rng)
            if m and (m.group(1) or m.group(2)):  # one range; several ranges / garbage -> whole file (allowed by RFC 9110)
                if m.group(1):
                    start = int(m.group(1))
                    end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
                else:
                    start, end = max(0, size - int(m.group(2))), size - 1
                    if int(m.group(2)) == 0:
                        start = size
                if start >= size or start > end:
                    return self.send_json({'error': 'range', 'message': MESSAGES['range']}, 416, [('Content-Range', f'bytes */{size}')])
                code = 206
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(end - start + 1))
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('ETag', etag)
        self.send_header('Cache-Control', cache)
        if code == 206:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        if name:
            ascii_name = re.sub(r'[^A-Za-z0-9._ -]', '_', name)
            self.send_header('Content-Disposition', f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{urllib.parse.quote(name)}')
        self.end_headers()
        if self.command == 'HEAD':
            return
        with open(path, 'rb') as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = f.read(min(1 << 20, left))
                if not chunk:
                    break
                self.wfile.write(chunk)
                left -= len(chunk)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 32

    def __init__(self, addr, ident, ctx):
        self.ident, self.ctx = ident, ctx
        self.events = Events()
        self._dev = (None, [])
        self._seen = {}
        self._gpu = (0, None)
        self.dlock = threading.Lock()
        if ':' in addr[0]:
            self.address_family = socket.AF_INET6
        super().__init__(addr, H)

    def finish_request(self, request, client_address):  # TLS handshake in the worker thread, not in the accept loop
        request.settimeout(20)
        try:
            tls = self.ctx.wrap_socket(request, server_side=True)
        except (ssl.SSLError, OSError):
            return
        try:
            self.RequestHandlerClass(tls, client_address, self)
        finally:
            try:
                tls.close()
            except OSError:
                pass

    def handle_error(self, request, client_address):
        pass

    def info(self):
        return {'name': self.ident['name'], 'id': self.ident['id'], 'version': store.version()}

    def devices(self):
        """devices.json, re-read when it changes (revoke in the Studio works at once)."""
        p = store.path('devices.json')
        try:
            st = os.stat(p)
            key = (st.st_mtime_ns, st.st_size, st.st_ino)
        except OSError:
            return []
        with self.dlock:
            if self._dev[0] != key:
                self._dev = (key, store.devices())
            return self._dev[1]

    def seen(self, did):
        now = time.time()
        if now - self._seen.get(did, 0) > 60:
            self._seen[did] = now
            threading.Thread(target=store.touch, args=(did,), daemon=True).start()

    def gpu(self):
        with self.dlock:
            if time.time() - self._gpu[0] < 2 and self._gpu[1]:
                return self._gpu[1]
        g = studio.gpu_stats()
        with self.dlock:
            self._gpu = (time.time(), g)
        return g


def make_server(port=None, bind=None):
    ident = store.identity()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(ident['crt'], ident['key'])
    port = store.PORT if port is None else port
    srv = Server((bind or os.environ.get('TORAVO_COMPANION_BIND', '0.0.0.0'), port), ident, ctx)
    srv.events.scan()
    threading.Thread(target=srv.events.run, daemon=True, name='events').start()
    return srv


class Bonjour(threading.Thread):
    """Announces _toravo._tcp via avahi-publish (optional). avahi-publish ends when avahi-daemon is not running (or restarts) –
    then it is reaped and tried again every minute. Stopped by PID on exit, never by name."""

    def __init__(self, ident, port):
        super().__init__(daemon=True, name='bonjour')
        self.cmd = ['-s', f'Toravo {ident["name"]}', '_toravo._tcp', str(port), 'v=1', f'id={ident["id"]}', f'fp={ident["fp"][:16]}']
        self.exe = shutil.which('avahi-publish')
        self.proc, self.halt, self.up, self.warned, self.lock = None, threading.Event(), False, False, threading.Lock()

    def run(self):
        while self.exe and not self.halt.is_set():
            with self.lock:
                if self.halt.is_set():
                    break
                try:
                    self.proc = subprocess.Popen([self.exe, *self.cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                except OSError:
                    return
            t0 = time.time()
            while self.proc.poll() is None and not self.halt.wait(2):
                if not self.up and time.time() - t0 > 3:
                    self.up, self.warned = True, False
                    print(f'Bonjour: _toravo._tcp announced (avahi-publish pid {self.proc.pid})', file=sys.stderr, flush=True)
            if self.halt.is_set():
                break
            self.proc.wait()  # reap – no zombie
            if not self.warned:
                self.warned = True
                print('Bonjour: avahi-publish ended (avahi-daemon not running?) – trying again every minute', file=sys.stderr, flush=True)
            self.up = False
            self.halt.wait(60)
        self.close()

    def close(self):
        self.halt.set()
        with self.lock:
            p = self.proc
            if p and p.poll() is None:
                os.kill(p.pid, signal.SIGTERM)  # by PID – never by name pattern
                try:
                    p.wait(5)
                except subprocess.TimeoutExpired:
                    os.kill(p.pid, signal.SIGKILL)
                    p.wait()


def main():
    srv = make_server()
    port = srv.server_address[1]
    ad = Bonjour(srv.ident, port)
    ad.start()
    print(f'Toravo Companion: https://{srv.server_address[0]}:{port} · id {srv.ident["id"]} · fp {srv.ident["fp"][:16]}…'
          + ('' if ad.exe else ' · no Bonjour (avahi-publish missing)'), flush=True)

    def stop(*_):
        threading.Thread(target=srv.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        srv.serve_forever()
    finally:
        srv.events.stop.set()
        ad.close()
        srv.server_close()


if __name__ == '__main__':
    main()
