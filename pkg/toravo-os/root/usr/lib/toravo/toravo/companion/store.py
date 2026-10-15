"""Toravo Companion state (15.10.2026): key + self-signed certificate, server id, paired devices, one-time pairing codes.

Everything lives in ~/.config/toravo/companion/ (0700, files 0600). Device tokens and pairing codes are stored only as
sha256 – never in clear text, never logged. Shared by the service (port 8891), the Studio (Connect phone) and the CLI,
so every write happens under a file lock and is atomic (tmp + rename).
"""
import contextlib, fcntl, hashlib, hmac, ipaddress, json, os, re, secrets, socket, subprocess, threading, time, urllib.parse

PORT = int(os.environ.get('TORAVO_COMPANION_PORT', '8891'))
UNIT = 'toravo-companion.service'
ALPHABET = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'  # no 0/O, 1/I/L – easy to type from the screen
CODE_LEN, CODE_TTL, MAX_CODES = 10, 600, 3
MAX_DEVICES = 10
# private ranges only (RFC 1918, loopback, link-local, CGNAT/Tailscale, IPv6 loopback/link-local/ULA)
NETS = [ipaddress.ip_network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '127.0.0.0/8', '169.254.0.0/16',
                                          '100.64.0.0/10', '::1/128', 'fe80::/10', 'fc00::/7')]
VIRTUAL = ('docker', 'br-', 'veth', 'virbr', 'vnet', 'podman', 'cni', 'flannel', 'lxc')  # bridges the phone cannot reach

_TL = threading.RLock()
_depth = [0]


def cdir():
    d = os.path.expanduser('~/.config/toravo/companion')
    os.makedirs(d, mode=0o700, exist_ok=True)
    if os.stat(d).st_mode & 0o077:
        os.chmod(d, 0o700)
    return d


def path(name):
    return os.path.join(cdir(), name)


@contextlib.contextmanager
def locked():
    """Inter-process lock (flock) + thread lock; re-entrant inside one thread."""
    with _TL:
        if _depth[0]:
            _depth[0] += 1
            try:
                yield
            finally:
                _depth[0] -= 1
            return
        f = open(path('.lock'), 'a')
        try:
            fcntl.flock(f, fcntl.LOCK_EX)
            _depth[0] = 1
            yield
        finally:
            _depth[0] = 0
            f.close()


def write_atomic(p, data, mode=0o600):
    tmp = f'{p}.{os.getpid()}.{threading.get_ident()}.tmp'
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, 'wb' if isinstance(data, bytes) else 'w') as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)


def read_json(p, default):
    try:
        with open(p) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


# ------------------------------------------------------------------------------------------------ network
def allowed(addr):
    """True for clients from private networks (IPv4-mapped IPv6 is unwrapped first)."""
    try:
        ip = ipaddress.ip_address(str(addr).split('%')[0])
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return any(ip in n for n in NETS)


def hostname():
    return re.sub(r'[^A-Za-z0-9-]', '', socket.gethostname().split('.')[0]) or 'toravo'


def private_ips():
    """Private IPv4 addresses of this PC the phone can reach, best first (the one with the default route first)."""
    found, skip = [], set()
    try:  # no packet is sent – only asks the kernel which source address the default route uses (TEST-NET-1)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('192.0.2.1', 9))
        found.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        r = subprocess.run(['ip', '-j', '-4', 'addr'], capture_output=True, text=True, timeout=3)
        for itf in json.loads(r.stdout or '[]'):
            for a in itf.get('addr_info', []):
                (skip.add if itf.get('ifname', '').startswith(VIRTUAL) else found.append)(a.get('local'))
    except (OSError, ValueError, subprocess.SubprocessError):
        try:
            found += [ai[4][0] for ai in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
        except OSError:
            pass
    out = []
    for a in found:
        try:
            ip = ipaddress.ip_address(a or '')
        except ValueError:
            continue
        if a in skip or ip.is_loopback or ip.is_link_local or not allowed(a) or a in out:
            continue
        out.append(a)
    return out


# ------------------------------------------------------------------------------------------------ identity
def _openssl(*args, data=None):
    r = subprocess.run(['openssl', *args], input=data, capture_output=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError('openssl ' + args[0] + ': ' + r.stderr.decode(errors='replace').strip()[-300:])
    return r.stdout


def fingerprint(key_or_cert):
    """Lowercase hex SHA-256 over the DER SubjectPublicKeyInfo (what the app pins)."""
    with open(key_or_cert, 'rb') as f:
        pem = f.read()
    if b'CERTIFICATE' in pem:
        pem = _openssl('x509', '-pubkey', '-noout', data=pem)
        der = _openssl('pkey', '-pubin', '-outform', 'DER', data=pem)
    else:
        der = _openssl('pkey', '-pubout', '-outform', 'DER', data=pem)
    return hashlib.sha256(der).hexdigest()


def identity():
    """Creates what is missing: EC P-256 key (kept forever, so the pin survives), self-signed certificate (10 years; made
    again with the same key when the PC's addresses change), random server id. Returns {id, fp, key, crt, name, ips}."""
    with locked():
        key, crt = path('server.key'), path('server.crt')
        if not os.path.exists(key):
            tmp = key + '.new'
            if os.path.exists(tmp):
                os.remove(tmp)
            old = os.umask(0o077)
            try:
                _openssl('genpkey', '-algorithm', 'EC', '-pkeyopt', 'ec_paramgen_curve:P-256', '-out', tmp)
            finally:
                os.umask(old)
            os.chmod(tmp, 0o600)
            os.replace(tmp, key)
            for stale in (crt, path('cert.san')):
                if os.path.exists(stale):
                    os.remove(stale)
        try:
            sid = open(path('id')).read().strip()
        except OSError:
            sid = ''
        if not re.fullmatch(r'[0-9a-f]{16}', sid):
            sid = secrets.token_hex(8)
            write_atomic(path('id'), sid + '\n')
        name, ips = hostname(), private_ips()
        san = ','.join([f'DNS:{name}.local', 'DNS:localhost'] + [f'IP:{i}' for i in ips + ['127.0.0.1'] if i])
        try:
            have = open(path('cert.san')).read().strip()
        except OSError:
            have = ''
        if not os.path.exists(crt) or have != san:
            _openssl('req', '-new', '-x509', '-key', key, '-out', crt + '.new', '-days', '3650', '-sha256', '-subj', f'/CN=Toravo {name}',
                     '-addext', f'subjectAltName={san}', '-addext', 'basicConstraints=critical,CA:FALSE',
                     '-addext', 'keyUsage=critical,digitalSignature', '-addext', 'extendedKeyUsage=serverAuth')
            os.chmod(crt + '.new', 0o644)
            os.replace(crt + '.new', crt)
            write_atomic(path('cert.san'), san + '\n')
        return {'id': sid, 'fp': fingerprint(key), 'key': key, 'crt': crt, 'name': name, 'ips': ips}


_ver = []


def version():
    if not _ver:
        try:
            r = subprocess.run(['pacman', '-Q', 'toravo-os'], capture_output=True, text=True, timeout=5)
            _ver.append(r.stdout.split()[1].split('-')[0] if r.returncode == 0 else '?')
        except (OSError, IndexError, subprocess.SubprocessError):
            _ver.append('?')
    return _ver[0]


# ------------------------------------------------------------------------------------------------ devices
def devices():
    return read_json(path('devices.json'), [])


def public(d):
    return {k: d.get(k) for k in ('id', 'name', 'model', 'created', 'last_seen')}


def clean_text(s, n=60):
    return re.sub(r'[\x00-\x1f\x7f<>]', '', str(s or ''))[:n].strip()


class TooMany(Exception):
    pass


def add_device(name, model):
    """New phone -> (token, device). Only the sha256 of the token is stored."""
    token = secrets.token_urlsafe(32)
    with locked():
        ds = devices()
        if len(ds) >= MAX_DEVICES:
            raise TooMany()
        now = time.time()
        d = {'id': secrets.token_hex(6), 'name': clean_text(name) or 'iPhone', 'model': clean_text(model), 'created': now,
             'last_seen': now, 'token_sha256': sha(token)}
        ds.append(d)
        write_atomic(path('devices.json'), json.dumps(ds, indent=2, ensure_ascii=False))
    return token, d


def revoke(did):
    with locked():
        ds = devices()
        keep = [d for d in ds if d.get('id') != did]
        if len(keep) == len(ds):
            return False
        write_atomic(path('devices.json'), json.dumps(keep, indent=2, ensure_ascii=False))
        return True


def touch(did):
    with locked():
        ds = devices()
        for d in ds:
            if d.get('id') == did:
                d['last_seen'] = time.time()
        write_atomic(path('devices.json'), json.dumps(ds, indent=2, ensure_ascii=False))


def match_token(token, ds):
    """Constant-time lookup: compares the token hash with every device (no early exit)."""
    h, hit = sha(token or ''), None
    for d in ds:
        if hmac.compare_digest(h, str(d.get('token_sha256', ''))):
            hit = d
    return hit


# ------------------------------------------------------------------------------------------------ pairing codes
def new_code():
    """One-time pairing code (10 characters, 10 minutes). Returns (code, expires). Older codes stay valid until they expire
    (max. 3 open codes)."""
    code = ''.join(secrets.choice(ALPHABET) for _ in range(CODE_LEN))
    exp = time.time() + CODE_TTL
    with locked():
        cs = [c for c in read_json(path('pairing.json'), []) if c.get('exp', 0) > time.time()][-(MAX_CODES - 1):]
        cs.append({'h': sha(code), 'exp': exp})
        write_atomic(path('pairing.json'), json.dumps(cs))
    return code, exp


def norm_code(code):
    return re.sub(r'[\s-]', '', str(code or '')).upper()


def take_code(code):
    """True if the code is valid; it is used up at once (single use)."""
    h, hit = sha(norm_code(code)), None
    with locked():
        cs = [c for c in read_json(path('pairing.json'), []) if c.get('exp', 0) > time.time()]
        for c in cs:
            if hmac.compare_digest(h, str(c.get('h', ''))):
                hit = c
        if hit:
            cs.remove(hit)
        write_atomic(path('pairing.json'), json.dumps(cs))
    return hit is not None


def clear_codes():
    with locked():
        write_atomic(path('pairing.json'), '[]')


def fmt_code(code):
    return code[:5] + '-' + code[5:]


def link(ident, code, port=None):
    q = urllib.parse.urlencode({'v': 1, 'h': ','.join(ident['ips']), 'p': port or PORT, 'c': code, 'fp': ident['fp'],
                                'id': ident['id'], 'n': ident['name']}, safe=',')
    return 'toravo://pair?' + q


def qr(text, kind='SVG'):
    """QR code via qrencode (SVG for the Studio, ANSIUTF8 for the terminal) – None if qrencode is missing."""
    try:
        r = subprocess.run(['qrencode', '-t', kind, '-m', '2', '-l', 'M', '-o', '-', text], capture_output=True, text=True, timeout=10)
        return r.stdout if r.returncode == 0 and r.stdout else None
    except (OSError, subprocess.SubprocessError):
        return None


# ------------------------------------------------------------------------------------------------ service on/off
def systemctl(*args):
    try:
        r = subprocess.run(['systemctl', '--user', *args], capture_output=True, text=True, timeout=20)
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)


def active():
    ok, out = systemctl('is-active', UNIT)
    return ok and out.splitlines()[-1:] == ['active']


def turn_on():
    return systemctl('enable', '--now', UNIT)


def turn_off():
    clear_codes()
    return systemctl('disable', '--now', UNIT)
