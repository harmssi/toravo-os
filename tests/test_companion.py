"""Toravo Companion service – end-to-end tests over real HTTPS against the running server (random port, temporary HOME).

Run: python3 -m pytest -q tests/test_companion.py   (needs openssl + ffmpeg on PATH; qrencode optional)   15.10.2026
"""
import base64, hashlib, http.client, json, os, socket, ssl, subprocess, sys, tempfile, threading, time

import pytest

TMP = tempfile.mkdtemp(prefix='toravo-companion-test-')
os.environ['HOME'] = TMP
os.environ['TORAVO_LANG'] = 'en'
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, 'pkg/toravo-os/root/usr/lib/toravo')
sys.path.insert(0, LIB)

from toravo import queue, stack  # noqa: E402
from toravo.companion import store, server, panel  # noqa: E402

stack.STACK_FILE = os.path.join(ROOT, 'pkg/toravo-os/root/usr/share/toravo/ai-stack.json')
HOME = os.path.join(TMP, 'Toravo')


def b64(s):
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip('=')


@pytest.fixture(scope='module')
def srv():
    for d in ('Shorts', 'Thumbnails', 'Videos', 'Songs', 'Voice'):
        os.makedirs(os.path.join(HOME, d), exist_ok=True)
    server.EVENT_INTERVAL = 0.2
    s = server.make_server(port=0, bind='127.0.0.1')
    t = threading.Thread(target=s.serve_forever, daemon=True)
    t.start()
    yield s
    s.events.stop.set()
    s.shutdown()
    s.server_close()


@pytest.fixture(autouse=True)
def fresh_limits():
    server.LIMITS.reset()
    yield
    server.LIMITS.reset()


def req(srv, method, path, body=None, token=None, headers=None):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # the app pins the key fingerprint instead (test_fingerprint checks the same)
    c = http.client.HTTPSConnection('127.0.0.1', srv.server_address[1], context=ctx, timeout=30)
    h = dict(headers or {})
    if token:
        h['Authorization'] = 'Bearer ' + token
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h['Content-Type'] = 'application/json'
    c.request(method, path, body=data, headers=h)
    r = c.getresponse()
    raw = r.read()
    c.close()
    try:
        js = json.loads(raw) if r.getheader('Content-Type', '').startswith('application/json') else None
    except ValueError:
        js = None
    return r.status, js, raw, r


def pair(srv, name='Test iPhone'):
    code, _ = store.new_code()
    st, js, _, _ = req(srv, 'POST', '/api/v1/pair', {'code': store.fmt_code(code), 'device': name, 'model': 'iPhone16,1'})
    assert st == 200, js
    return js['token'], js['device_id']


@pytest.fixture
def tok(srv):
    t, did = pair(srv)
    yield t
    store.revoke(did)


# ------------------------------------------------------------------------------------------------ identity
def test_fingerprint_matches_openssl_and_tls(srv):
    ident = store.identity()
    der = subprocess.run(['openssl', 'pkey', '-in', ident['key'], '-pubout', '-outform', 'DER'], capture_output=True, check=True).stdout
    assert ident['fp'] == hashlib.sha256(der).hexdigest()
    ctx = ssl.create_default_context()
    ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
    with socket.create_connection(('127.0.0.1', srv.server_address[1])) as raw, ctx.wrap_socket(raw) as s:
        cert = s.getpeercert(binary_form=True)
    pem = subprocess.run(['openssl', 'x509', '-inform', 'DER', '-pubkey', '-noout'], input=cert, capture_output=True, check=True).stdout
    spki = subprocess.run(['openssl', 'pkey', '-pubin', '-outform', 'DER'], input=pem, capture_output=True, check=True).stdout
    assert hashlib.sha256(spki).hexdigest() == ident['fp']
    assert store.identity()['fp'] == ident['fp']  # key is kept
    d = store.cdir()
    assert os.stat(d).st_mode & 0o777 == 0o700
    assert os.stat(ident['key']).st_mode & 0o777 == 0o600


def test_cert_remade_with_same_key_when_addresses_change(srv):
    ident = store.identity()
    with open(store.path('cert.san'), 'w') as f:
        f.write('DNS:old.local\n')
    crt_before = open(ident['crt']).read()
    ident2 = store.identity()
    assert open(ident2['crt']).read() != crt_before and ident2['fp'] == ident['fp'] and ident2['id'] == ident['id']


def test_hello_needs_no_token(srv):
    st, js, _, _ = req(srv, 'GET', '/api/v1/hello')
    assert st == 200 and js['api'] == 1 and js['id'] == srv.ident['id'] and 'version' in js and 'name' in js


def test_allowed_networks():
    for a in ('10.1.2.3', '172.16.0.1', '172.31.255.1', '192.168.1.20', '127.0.0.1', '169.254.1.1', '100.100.1.1', '::1',
              'fe80::1%en0', 'fd00::1', '::ffff:192.168.1.5'):
        assert store.allowed(a), a
    for a in ('8.8.8.8', '172.32.0.1', '100.128.0.1', '2001:db8::1', '::ffff:8.8.8.8', '1.1.1.1', 'garbage', ''):
        assert not store.allowed(a), a


def test_public_ip_gets_403(srv, tok, monkeypatch):
    monkeypatch.setattr(store, 'NETS', [n for n in store.NETS if not n.network_address.is_loopback])
    assert req(srv, 'GET', '/api/v1/hello')[0] == 403
    st, js, _, _ = req(srv, 'GET', '/api/v1/status', token=tok)
    assert st == 403 and js['error'] == 'forbidden_network'


# ------------------------------------------------------------------------------------------------ pairing
def test_pairing_code_single_use_and_token(srv):
    code, exp = store.new_code()
    assert len(code) == 10 and all(c in store.ALPHABET for c in code) and exp - time.time() <= 600
    st, js, _, _ = req(srv, 'POST', '/api/v1/pair', {'code': code.lower(), 'device': 'Tobias iPhone', 'model': 'iPhone17,2'})
    assert st == 200 and js['token'] and js['device_id'] and js['server']['id'] == srv.ident['id']
    st2, js2, _, _ = req(srv, 'POST', '/api/v1/pair', {'code': code, 'device': 'x'})
    assert st2 == 400 and js2['error'] == 'bad_code'
    raw = open(store.path('devices.json')).read()
    assert js['token'] not in raw and hashlib.sha256(js['token'].encode()).hexdigest() in raw
    assert os.stat(store.path('devices.json')).st_mode & 0o777 == 0o600
    assert code not in open(store.path('pairing.json')).read()
    assert req(srv, 'GET', '/api/v1/status', token=js['token'])[0] == 200
    store.revoke(js['device_id'])


def test_expired_and_wrong_code(srv):
    code, _ = store.new_code()
    cs = json.load(open(store.path('pairing.json')))
    for c in cs:
        c['exp'] = time.time() - 1
    store.write_atomic(store.path('pairing.json'), json.dumps(cs))
    assert req(srv, 'POST', '/api/v1/pair', {'code': code})[0] == 400
    assert req(srv, 'POST', '/api/v1/pair', {'code': 'AAAAA-BBBBB'})[0] == 400
    assert req(srv, 'POST', '/api/v1/pair', {})[0] == 400


def test_pairing_rate_limit_429(srv):
    for _ in range(5):
        assert req(srv, 'POST', '/api/v1/pair', {'code': 'WRONGWRONG'})[0] == 400
    code, _ = store.new_code()
    st, js, _, r = req(srv, 'POST', '/api/v1/pair', {'code': code})  # even the right code is refused while locked
    assert st == 429 and js['error'] == 'rate_limited' and int(r.getheader('Retry-After')) > 0


def test_pairing_global_limit(srv):
    for i in range(20):
        server.LIMITS.fail(f'pair:10.0.0.{i}', 'pair:*')
    assert req(srv, 'POST', '/api/v1/pair', {'code': 'WRONGWRONG'})[0] == 429


def test_max_devices(srv):
    made = []
    try:
        while len(store.devices()) < store.MAX_DEVICES:
            made.append(store.add_device('x', 'y')[1]['id'])
        code, _ = store.new_code()
        st, js, _, _ = req(srv, 'POST', '/api/v1/pair', {'code': code})
        assert st == 409 and js['error'] == 'too_many_devices'
    finally:
        for d in made:
            store.revoke(d)


def test_token_required_and_revoke(srv):
    assert req(srv, 'GET', '/api/v1/status')[0] == 401
    assert req(srv, 'GET', '/api/v1/status', token='nope')[0] == 401
    t, did = pair(srv)
    assert req(srv, 'GET', '/api/v1/media', token=t)[0] == 200
    assert store.revoke(did)
    st, js, _, _ = req(srv, 'GET', '/api/v1/media', token=t)
    assert st == 401 and js['error'] == 'unauthorized'
    t2, _ = pair(srv)
    assert req(srv, 'POST', '/api/v1/unpair', token=t2)[0] == 200
    assert req(srv, 'GET', '/api/v1/status', token=t2)[0] == 401


def test_bad_token_flood_429(srv):
    codes = [req(srv, 'GET', '/api/v1/status', token='bad')[0] for _ in range(32)]
    assert codes[0] == 401 and codes[-1] == 429


def test_status_shape(srv, tok):
    st, js, _, _ = req(srv, 'GET', '/api/v1/status', token=tok)
    assert st == 200 and set(js) >= {'server', 'gpu', 'jobs', 'events_seq', 'time'}
    assert set(js['gpu']) >= {'name', 'util', 'vram_used', 'vram_total', 'temp'}


# ------------------------------------------------------------------------------------------------ media
@pytest.fixture(scope='module')
def files(srv):
    sh = os.path.join(HOME, 'Shorts', 'skyborne')
    os.makedirs(sh, exist_ok=True)
    vid = os.path.join(sh, 'skyborne-short-1.mp4')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc=size=360x640:rate=25:duration=2', '-pix_fmt', 'yuv420p', vid], check=True)
    img = os.path.join(HOME, 'Thumbnails', 'thumb A.png')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc=size=1280x720', '-frames:v', '1', img], check=True)
    song = os.path.join(HOME, 'Songs', 'skyborne.wav')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=d=2', song], check=True)
    secret = os.path.join(TMP, 'secret.mp4')
    open(secret, 'wb').write(b'SECRET' * 100)
    open(os.path.join(HOME, 'Shorts', '.hidden.mp4'), 'wb').write(b'x')
    os.symlink(secret, os.path.join(HOME, 'Shorts', 'link.mp4'))
    os.makedirs(os.path.join(TMP, 'outside'), exist_ok=True)
    open(os.path.join(TMP, 'outside', 'o.mp4'), 'wb').write(b'o')
    os.symlink(os.path.join(TMP, 'outside'), os.path.join(HOME, 'Shorts', 'linkdir'))
    os.makedirs(os.path.join(HOME, 'Voice'), exist_ok=True)
    open(os.path.join(HOME, 'Voice', 'v.wav'), 'wb').write(b'v')
    open(os.path.join(HOME, 'Shorts', 'notes.txt'), 'wb').write(b't')
    return {'vid': vid, 'img': img, 'song': song}


def test_media_list(srv, tok, files):
    st, js, _, _ = req(srv, 'GET', '/api/v1/media?kind=all&limit=60', token=tok)
    names = [m['name'] for m in js['items']]
    assert st == 200 and {'skyborne-short-1.mp4', 'thumb A.png', 'skyborne.wav'} <= set(names)
    assert not {'.hidden.mp4', 'link.mp4', 'o.mp4', 'v.wav', 'notes.txt'} & set(names)
    m = next(x for x in js['items'] if x['name'] == 'skyborne-short-1.mp4')
    assert m['kind'] == 'shorts' and m['type'] == 'video' and m['url'] == '/api/v1/media/' + m['id'] and m['poster'].endswith('/poster')
    assert base64.urlsafe_b64decode(m['id'] + '==').decode() == 'shorts/skyborne/skyborne-short-1.mp4'
    st, js, _, _ = req(srv, 'GET', '/api/v1/media?kind=thumbnail', token=tok)
    assert [x['kind'] for x in js['items']] == ['thumbnail']
    assert req(srv, 'GET', '/api/v1/media?kind=publish', token=tok)[0] == 400


@pytest.mark.parametrize('rel', ['shorts/../../secret.mp4', 'shorts/..%2F..%2Fsecret.mp4', '/etc/passwd', 'shorts//etc/hosts.mp4',
                                 'shorts/.hidden.mp4', 'shorts/link.mp4', 'shorts/linkdir/o.mp4', 'voice/v.wav', 'publish/x.mp4',
                                 'shorts/notes.txt', 'shorts/skyborne/../skyborne/skyborne-short-1.mp4', 'shorts/./skyborne/skyborne-short-1.mp4',
                                 'Shorts/skyborne/skyborne-short-1.mp4', 'shorts/missing.mp4', 'shorts\\..\\secret.mp4', 'shorts/a\x00.mp4'])
def test_media_escapes_404(srv, tok, files, rel):
    mid = b64(rel)
    assert req(srv, 'GET', '/api/v1/media/' + mid, token=tok)[0] == 404
    assert req(srv, 'GET', '/api/v1/media/' + mid + '/poster', token=tok)[0] == 404


def test_media_garbage_ids(srv, tok, files):
    for mid in ('..', '%2e%2e', 'a', '!!!!', 'x' * 3000):
        assert req(srv, 'GET', '/api/v1/media/' + mid, token=tok)[0] == 404


def test_download_and_ranges(srv, tok, files):
    mid = b64('shorts/skyborne/skyborne-short-1.mp4')
    data = open(files['vid'], 'rb').read()
    st, _, raw, r = req(srv, 'GET', '/api/v1/media/' + mid, token=tok)
    assert st == 200 and raw == data and r.getheader('Accept-Ranges') == 'bytes' and 'attachment' in r.getheader('Content-Disposition')
    st, _, raw, r = req(srv, 'GET', '/api/v1/media/' + mid, token=tok, headers={'Range': 'bytes=0-1'})
    assert st == 206 and raw == data[:2] and r.getheader('Content-Range') == f'bytes 0-1/{len(data)}'
    st, _, raw, _ = req(srv, 'GET', '/api/v1/media/' + mid, token=tok, headers={'Range': 'bytes=100-'})
    assert st == 206 and raw == data[100:]
    st, _, raw, _ = req(srv, 'GET', '/api/v1/media/' + mid, token=tok, headers={'Range': 'bytes=-10'})
    assert st == 206 and raw == data[-10:]
    st, _, _, r = req(srv, 'GET', '/api/v1/media/' + mid, token=tok, headers={'Range': f'bytes={len(data)}-'})
    assert st == 416 and r.getheader('Content-Range') == f'bytes */{len(data)}'
    st, _, raw, r = req(srv, 'HEAD', '/api/v1/media/' + mid, token=tok)
    assert st == 200 and raw == b'' and int(r.getheader('Content-Length')) == len(data)
    assert req(srv, 'GET', '/api/v1/media/' + mid)[0] == 401
    st, _, raw, _ = req(srv, 'GET', '/api/v1/media/' + b64('thumbnail/thumb A.png'), token=tok)
    assert st == 200 and raw[:8] == b'\x89PNG\r\n\x1a\n'


def test_posters(srv, tok, files):
    for rel in ('shorts/skyborne/skyborne-short-1.mp4', 'thumbnail/thumb A.png', 'song/skyborne.wav'):
        st, _, raw, r = req(srv, 'GET', '/api/v1/media/' + b64(rel) + '/poster', token=tok)
        assert st == 200 and raw[:3] == b'\xff\xd8\xff' and r.getheader('Content-Type') == 'image/jpeg', rel
    assert any(f.endswith('.jpg') for f in os.listdir(os.path.join(TMP, '.cache/toravo/companion')))


# ------------------------------------------------------------------------------------------------ plans
def test_plan_only_by_id_and_once(srv, tok, files):
    st, p, _, _ = req(srv, 'POST', '/api/v1/plan', {'text': 'turn skyborne into 3 shorts + thumbnail'}, token=tok)
    assert st == 200 and p['plan_id'] and p['steps'] and {'kind', 'title', 'ready'} <= set(p['steps'][0])
    assert any(s['kind'] == 'shorts' and s['count'] == 3 for s in p['steps'])
    before = {j['id'] for j in queue.jobs()}
    evil = {'plan': {'steps': [{'kind': 'stream', 'title': 'x', 'params': {}, 'after': []}]}}  # ignored – the phone never sends a plan
    st, js, _, _ = req(srv, 'POST', f"/api/v1/plans/{p['plan_id']}/run", evil, token=tok)
    assert st == 200 and len(js['jobs']) == len(p['steps'])
    new = [j for j in queue.jobs() if j['id'] not in before]
    assert sorted(j['kind'] for j in new) == sorted(s['kind'] for s in p['steps'])
    assert req(srv, 'POST', f"/api/v1/plans/{p['plan_id']}/run", token=tok)[0] == 404
    assert req(srv, 'POST', '/api/v1/plans/AAAAAAAAAAAAAAAAAAAAAA/run', token=tok)[0] == 404
    t2, did2 = pair(srv, 'other phone')
    st, p2, _, _ = req(srv, 'POST', '/api/v1/plan', {'text': '2 shorts from skyborne'}, token=tok)
    assert req(srv, 'POST', f"/api/v1/plans/{p2['plan_id']}/run", token=t2)[0] == 404  # plans belong to the phone that asked
    server.PLANS[p2['plan_id']] = (server.PLANS[p2['plan_id']][0], server.PLANS[p2['plan_id']][1], time.time() - 1)
    assert req(srv, 'POST', f"/api/v1/plans/{p2['plan_id']}/run", token=tok)[0] == 404  # expired
    store.revoke(did2)
    for j in new:
        os.remove(queue._path(j['id']))


def test_plan_id_percent_encoded(srv, tok, files):
    """15.10.2026: the app encoded '-' as %2D -> 404, the start button did nothing. Encoded ids must work too."""
    for _ in range(6):
        st, p, _, _ = req(srv, 'POST', '/api/v1/plan', {'text': '2 shorts from skyborne'}, token=tok)
        if '-' in p['plan_id'] or '_' in p['plan_id']:
            break
    enc = p['plan_id'].replace('-', '%2D').replace('_', '%5F')
    st, js, _, _ = req(srv, 'POST', f'/api/v1/plans/{enc}/run', token=tok)
    assert st == 200 and js['jobs']


def test_plan_needs_text(srv, tok):
    assert req(srv, 'POST', '/api/v1/plan', {'text': '  '}, token=tok)[0] == 400


def test_strip_stream_steps():
    p = server.strip_studio({'steps': [{'kind': 'shorts', 'after': []}, {'kind': 'stream', 'after': [0]}, {'kind': 'thumbnail', 'after': [0]}]})
    assert [s['kind'] for s in p['steps']] == ['shorts', 'thumbnail'] and p['steps'][1]['after'] == [0]


def test_strip_studio_steps():
    p = server.strip_studio({'steps': [{'kind': 'studio', 'after': []}, {'kind': 'song', 'after': []}, {'kind': 'video', 'after': [0, 1]}]})
    assert [s['kind'] for s in p['steps']] == ['song', 'video'] and p['steps'][1]['after'] == [0]


def test_plan_rate_limit(srv, tok):
    codes = [req(srv, 'POST', '/api/v1/plan', {'text': '3 shorts from skyborne'}, token=tok)[0] for _ in range(7)]
    assert codes[:6] == [200] * 6 and codes[6] == 429


# ------------------------------------------------------------------------------------------------ jobs + events
def test_pause_resume_cancel(srv, tok):
    j = queue.add('shorts', 'Cut 3 Shorts', {'count': 3})
    act = lambda a: req(srv, 'POST', f"/api/v1/jobs/{j['id']}/{a}", token=tok)  # noqa: E731
    st, js, _, _ = act('pause')
    assert st == 200 and js['job']['state'] == 'paused' and js['job']['can_resume'] and not js['job']['can_pause']
    assert queue.load(j['id'])['state'] == 'paused'
    assert act('pause')[0] == 409
    assert queue.ready(queue.add('thumbnail', 'T', after=[j['id']]), queue.jobs()) is False  # dependants wait, nothing fails
    st, js, _, _ = act('resume')
    assert st == 200 and js['job']['state'] == 'queued'
    assert act('resume')[0] == 409
    act('pause')
    st, js, _, _ = act('cancel')
    assert st == 200 and js['job']['state'] == 'cancelled' and not js['job']['can_cancel']
    assert act('cancel')[0] == 409 and act('resume')[0] == 409
    r = queue.add('video', 'Render')
    queue.update(r, state='running')
    assert req(srv, 'POST', f"/api/v1/jobs/{r['id']}/pause", token=tok)[0] == 409  # running GPU jobs cannot be frozen
    assert req(srv, 'POST', f"/api/v1/jobs/{r['id']}/cancel", token=tok)[1]['job']['state'] == 'cancelled'
    assert req(srv, 'POST', '/api/v1/jobs/doesnotexist/cancel', token=tok)[0] == 404
    assert req(srv, 'POST', '/api/v1/jobs/..%2F..%2Fx/cancel', token=tok)[0] == 404
    st, js, _, _ = req(srv, 'GET', '/api/v1/status', token=tok)
    assert any(x['id'] == j['id'] for x in js['jobs'])


def wait_events(srv, tok, since, jid, typ, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        js = req(srv, 'GET', f'/api/v1/events?since={since}', token=tok)[1]
        if any(e['job_id'] == jid and e['type'] == typ for e in js['events']):
            return js
        time.sleep(.2)
    return js


def test_events_on_state_changes(srv, tok, files):
    seq0 = req(srv, 'GET', '/api/v1/status', token=tok)[1]['events_seq']
    j = queue.add('shorts', 'Cut 3 Shorts', {'count': 3})
    time.sleep(.5)
    queue.update(j, state='running', started=time.time())
    js = wait_events(srv, tok, seq0, j['id'], 'started')
    ev = [e for e in js['events'] if e['job_id'] == j['id']]
    assert ev and ev[0]['type'] == 'started' and ev[0]['title'] == 'Cut 3 Shorts' and ev[0]['kind'] == 'shorts'
    seq1 = js['seq']
    assert seq1 > seq0
    queue.update(j, state='done', progress=1.0, outputs=[files['vid']], finished=time.time())
    js = wait_events(srv, tok, seq1, j['id'], 'done')
    assert [e['type'] for e in js['events']] == ['done']
    assert js['events'][0]['outputs'][0]['name'] == 'skyborne-short-1.mp4' and js['events'][0]['seq'] > seq1
    assert req(srv, 'GET', f"/api/v1/events?since={js['seq']}", token=tok)[1]['events'] == []
    assert req(srv, 'GET', '/api/v1/events?since=abc', token=tok)[0] == 400
    st = req(srv, 'GET', '/api/v1/status', token=tok)[1]
    done = next(x for x in st['jobs'] if x['id'] == j['id'])
    assert done['outputs'][0]['type'] == 'video' and done['state'] == 'done'
    saved = json.load(open(os.path.join(TMP, '.local/state/toravo/companion/events.json')))  # survives restarts
    assert saved['seq'] == js['seq'] and saved['known'][j['id']] == 'done'


def test_events_seq_monotonic_after_restart(srv):
    e = server.Events()
    e.seq = int(time.time() * 1000) + 10_000_000  # clock went backwards
    s1 = e.next_seq()
    assert e.next_seq() > s1


# ------------------------------------------------------------------------------------------------ limits + misc
def test_api_rate_limit(srv, tok):
    codes = []
    ctx = ssl.create_default_context()
    ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
    c = http.client.HTTPSConnection('127.0.0.1', srv.server_address[1], context=ctx, timeout=30)  # keep-alive
    for _ in range(60):
        c.request('GET', '/api/v1/events?since=0', headers={'Authorization': 'Bearer ' + tok})
        r = c.getresponse()
        r.read()
        codes.append(r.status)
        if r.status == 429:
            assert int(r.getheader('Retry-After')) >= 1
            break
    c.close()
    assert codes.count(200) >= 30 and codes[-1] == 429


def test_unknown_paths_and_body_limit(srv, tok):
    assert req(srv, 'GET', '/', token=tok)[0] == 404
    assert req(srv, 'GET', '/api/v1/nope', token=tok)[0] == 404
    assert req(srv, 'GET', '/api/v1/pair')[0] == 401  # wrong method falls through to the token check
    st, js, _, _ = req(srv, 'POST', '/api/v1/plan', None, token=tok, headers={'Content-Length': str(30 << 20)})
    assert st == 413


def test_studio_panel_pair(srv, monkeypatch):
    monkeypatch.setattr(store, 'systemctl', lambda *a: (True, 'active'))

    class FakeHandler:
        def send_json(self, obj, code=200):
            self.out = (code, obj)

    h = FakeHandler()
    panel.handle(h, 'POST', '/api/companion/pair', {})
    code, d = h.out
    assert code == 200 and len(d['code']) == 11 and d['code'][5] == '-' and d['expires'] > time.time()
    assert d['link'].startswith('toravo://pair?v=1&') and f"fp={srv.ident['fp']}" in d['link'] and f"id={srv.ident['id']}" in d['link']
    assert f'p={store.PORT}' in d['link'] and f"c={d['code'].replace('-', '')}" in d['link']
    st, js, _, _ = req(srv, 'POST', '/api/v1/pair', {'code': d['code'], 'device': 'Studio test'})
    assert st == 200
    panel.handle(h, 'GET', '/api/companion')
    assert any(x['id'] == js['device_id'] for x in h.out[1]['devices']) and 'token_sha256' not in json.dumps(h.out[1])
    panel.handle(h, 'POST', f"/api/companion/devices/{js['device_id']}/revoke", {})
    assert h.out[1]['ok'] and req(srv, 'GET', '/api/v1/status', token=js['token'])[0] == 401
    panel.handle(h, 'POST', '/api/companion/off', {})
    assert json.load(open(store.path('pairing.json'))) == []


def test_no_secrets_in_logs(srv, capfd):
    code, _ = store.new_code()
    st, js, _, _ = req(srv, 'POST', '/api/v1/pair', {'code': code, 'device': 'log test'})
    req(srv, 'GET', '/api/v1/status?x=1', token='badtoken123')
    out, err = capfd.readouterr()
    assert code not in out + err and js['token'] not in out + err and 'badtoken123' not in out + err
    store.revoke(js['device_id'])


@pytest.mark.parametrize('body', ['exec sleep 30', 'exit 1'])
def test_bonjour_stopped_by_pid_and_reaped(srv, monkeypatch, body):
    d = tempfile.mkdtemp(dir=TMP)
    exe = os.path.join(d, 'avahi-publish')
    with open(exe, 'w') as f:
        f.write('#!/bin/sh\n' + body + '\n')
    os.chmod(exe, 0o755)
    monkeypatch.setenv('PATH', d + os.pathsep + os.environ['PATH'])
    b = server.Bonjour(srv.ident, 8891)
    assert b.exe == exe and f"fp={srv.ident['fp'][:16]}" in b.cmd and '_toravo._tcp' in b.cmd
    b.start()
    end = time.time() + 5
    while time.time() < end and not (b.proc and (body == 'exec sleep 30' or b.warned)):
        time.sleep(.05)
    p = b.proc
    b.close()
    b.join(5)
    assert p.returncode is not None and not b.is_alive()  # ended and reaped (no zombie)
