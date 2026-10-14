"""Toravo AI stack: resolve the model x profile table for this machine and install it (drivers, venvs, models).

CLI (toravo-ai):
  toravo-ai plan [--json]                  what fits this hardware (per tool: variant, size, license)
  toravo-ai install [--only a,b] [--json] [--dry-run] [--no-system] [--with cuda,rocm,ltx2]
  toravo-ai status [--json]                installed parts
  toravo-ai licenses                       license table
Progress with --json: one JSON object per line: {"ev": "item"|"log"|"plan"|"done", ...}
Models are never part of the ISO – they are downloaded here, resumable (.part files).
"""
import json, os, shutil, subprocess, sys, time, urllib.error, urllib.request
from . import hw
from .theme import tr, loc

STACK_FILE = '/usr/share/toravo/ai-stack.json'
HELPER = '/usr/lib/toravo/toravo-root-helper'
UA = 'ToravoOS-Setup/1.0'


def load_stack():
    with open(STACK_FILE) as f:
        return json.load(f)


def base_dir(stack=None):
    stack = stack or load_stack()
    return os.path.expanduser(stack.get('base_dir', '~/Toravo/AI'))


def state_path(stack=None):
    return os.path.join(base_dir(stack), 'state.json')


def load_state(stack=None):
    try:
        with open(state_path(stack)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {'components': {}, 'models': {}, 'tools': {}, 'system': {}}


def save_state(st, stack=None):
    p = state_path(stack)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(st, f, indent=2, ensure_ascii=False)
    os.replace(tmp, p)


def model_dest(stack, mid):
    m = stack['models'][mid]
    dest = m.get('dest', '')
    if dest == 'hf':
        dest = 'models/' + m['repo'].split('/')[-1]
    return os.path.join(base_dir(stack), dest)


def variant_fits(v, info):
    if info['profile'] not in v.get('profiles', []):
        return False
    if info['vram_gb'] + 0.01 < v.get('min_vram', 0):
        return False
    if info.get('ram_gb', 0) and info['ram_gb'] + 0.5 < v.get('min_ram', 0):
        return False
    if v.get('amd_needs_rocm') and info['profile'] == 'amd' and info.get('rocm') == 'no':
        return False
    return True


def resolve(info=None, stack=None, extras=()):
    """-> plan dict: system part + per tool chosen variant + needed components/models with sizes and licenses."""
    stack = stack or load_stack()
    info = info or hw.detect()
    prof = info['profile']
    sysdef = stack['system'][prof]
    system = {'id': 'system', 'title': loc(sysdef, 'title'), 'packages': list(sysdef['packages']), 'license': loc(sysdef, 'license'),
              'size_gb': sysdef.get('size_gb', 0), 'optional': {}}
    for k, pk in sysdef.get('optional', {}).items():
        on = k in extras or (k == 'cuda' and prof == 'nvidia') or (k == 'rocm' and info.get('rocm') in ('yes', 'override'))
        system['optional'][k] = {'packages': pk, 'enabled': on, 'size_gb': sysdef.get('optional_size_gb', {}).get(k, 0)}
    tools, comps, models = [], [], []
    for t in stack['tools']:
        chosen = next((v for v in t['variants'] if variant_fits(v, info)), None)
        entry = {'id': t['id'], 'title': loc(t, 'title'), 'area': loc(t, 'area'), 'engine': t['engine'], 'variant': chosen['id'] if chosen else None,
                 'label': loc(chosen, 'label') if chosen else tr('nicht verfügbar', 'not available'), 'off': bool(chosen and chosen.get('off')) or not chosen,
                 'lite': bool(chosen and (chosen.get('min_vram', 0) == 0 and len(t['variants']) > 1)), 'note': loc(chosen or {}, 'note'),
                 'components': [], 'models': []}
        sel = [chosen] if chosen else []
        for o in t.get('optional', []):
            if variant_fits(o, info) and (o.get('default') or o['id'] in extras):
                sel.append(o)
                entry.setdefault('optional', []).append(o['id'])
        for v in sel:
            for c in v.get('components', []):
                entry['components'].append(c)
                if c not in comps:
                    comps.append(c)
            for m in v.get('models', []):
                entry['models'].append(m)
                if m not in models:
                    models.append(m)
        tools.append(entry)
    comp_list = []
    for c in comps:
        d = stack['components'][c]
        comp_list.append({'id': c, 'title': loc(d, 'title'), 'license': loc(d, 'license'), 'size_gb': d.get('size_gb', 0), 'kind': d['kind']})
    model_list = []
    for m in models:
        d = stack['models'][m]
        model_list.append({'id': m, 'repo': d.get('repo') or d.get('ollama'), 'license': loc(d, 'license'), 'size_gb': d.get('size_gb', 0)})
    total = system['size_gb'] + sum(o['size_gb'] for o in system['optional'].values() if o['enabled']) + \
        sum(c['size_gb'] for c in comp_list) + sum(m['size_gb'] for m in model_list)
    return {'hardware': info, 'system': system, 'tools': tools, 'components': comp_list, 'models': model_list,
            'total_gb': round(total, 1), 'base_dir': base_dir(stack)}


# ------------------------------------------------------------------------------------------------ install runner
class Runner:
    def __init__(self, plan, stack, as_json=False, dry=False):
        self.plan, self.stack, self.json, self.dry = plan, stack, as_json, dry
        self.base = base_dir(stack)
        self.state = load_state(stack)
        self.prof = plan['hardware']['profile']
        self.failed = []

    # -- output
    def emit(self, **ev):
        if self.json:
            print(json.dumps(ev, ensure_ascii=False), flush=True)
        else:
            if ev.get('ev') == 'item':
                p = ev.get('p')
                print(f"[{ev['id']}] {ev['state']}" + (f" {p * 100:5.1f}%" if isinstance(p, (int, float)) else '') + (f"  {ev.get('msg', '')}" if ev.get('msg') else ''), flush=True)
            elif ev.get('ev') == 'log':
                print('   ', ev['msg'], flush=True)

    def log(self, msg):
        self.emit(ev='log', msg=str(msg)[-400:])

    def run(self, cmd, item, cwd=None, env=None, root=False):
        stdin_data = None
        if root:
            if os.geteuid() == 0:
                cmd = [HELPER] + cmd
            elif SUDO_PASS.get('pw') is not None:
                cmd = ['sudo', '-S', '-p', '', HELPER] + cmd
                stdin_data = SUDO_PASS['pw'] + '\n'
            elif subprocess.run(['sudo', '-n', 'true'], capture_output=True).returncode == 0:
                cmd = ['sudo', '-n', HELPER] + cmd
            else:
                cmd = ['pkexec', HELPER] + cmd
        self.log('$ ' + ' '.join(cmd))
        if self.dry:
            return True
        e = dict(os.environ)
        e.update(env or {})
        try:
            p = subprocess.Popen(cmd, cwd=cwd, env=e, stdin=subprocess.PIPE if stdin_data else subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        except OSError as ex:
            self.log(tr(f'Programm fehlt: {cmd[0]} ({ex})', f'Program missing: {cmd[0]} ({ex})'))
            return False
        if stdin_data:
            try:
                p.stdin.write(stdin_data)
                p.stdin.close()
            except OSError:
                pass
        last = 0.0
        for line in p.stdout:
            line = line.rstrip()
            if line and time.time() - last > .25:
                last = time.time()
                self.emit(ev='item', id=item, state='run', msg=line[-160:])
        p.wait()
        if p.returncode != 0:
            self.log(tr(f'Fehler (Exit {p.returncode}): ', f'Error (exit {p.returncode}): ') + ' '.join(cmd[:4]))
        return p.returncode == 0

    # -- steps
    def system(self):
        s = self.plan['system']
        pk = list(s['packages'])
        for o in s['optional'].values():
            if o['enabled']:
                pk += o['packages']
        self.emit(ev='item', id='system', state='run', p=None, msg=s['title'])
        pk = missing_packages(pk)
        if not pk and not (self.prof == 'nvidia' and not os.path.exists('/etc/mkinitcpio.conf.d/10-toravo-nvidia.conf')):
            self.emit(ev='item', id='system', state='skip', p=1.0, msg=tr('schon installiert', 'already installed'))
            self.state['system'] = {'profile': self.prof, 'packages': [], 'at': time.time(), 'reboot': False}
            return True
        ok = self.run(['install-packages'] + pk, 'system', root=True) if pk else True
        if ok and self.prof == 'nvidia':
            ok = self.run(['nvidia-post'], 'system', root=True)
        if ok:
            self.state['system'] = {'profile': self.prof, 'packages': pk, 'at': time.time(), 'reboot': self.prof == 'nvidia'}
        self.emit(ev='item', id='system', state='done' if ok else 'fail', p=1.0)
        return ok

    def uv(self):
        return shutil.which('uv') or 'uv'

    def venv(self, d, item, python='3.12'):
        vpy = os.path.join(d, '.venv', 'bin', 'python')
        if os.path.exists(vpy):
            return vpy
        os.makedirs(d, exist_ok=True)
        return vpy if self.run([self.uv(), 'venv', '--python', python, os.path.join(d, '.venv')], item) else None

    def torch(self, vpy, item, version=None):
        idx = self.stack['torch_index'][self.prof if not (self.prof == 'amd' and self.plan['hardware'].get('rocm') == 'no') else 'cpu']
        pkgs = ['torch' + ('==' + version if version else ''), 'torchvision', 'torchaudio']
        return self.run([self.uv(), 'pip', 'install', '--python', vpy, '--index-url', idx] + pkgs, item)

    def component(self, cid):
        d = self.stack['components'][cid]
        item = 'comp:' + cid
        if self.state['components'].get(cid, {}).get('ok'):
            self.emit(ev='item', id=item, state='skip', p=1.0, msg=tr('schon eingerichtet', 'already set up'))
            return True
        self.emit(ev='item', id=item, state='run', p=None, msg=d['title'])
        ok = True
        kind = d['kind']
        if kind == 'pkg':
            pk = d.get('packages') or d['packages_by_profile'].get(
                'amd_norocm' if self.prof == 'amd' and self.plan['hardware'].get('rocm') == 'no' else self.prof, [])
            pk = missing_packages(pk)
            ok = self.run(['install-packages'] + pk, item, root=True) if pk else True
            if ok and d.get('enable_service') and subprocess.run(['systemctl', 'is-active', '--quiet', d['enable_service']]).returncode != 0:
                ok = self.run(['enable-service', d['enable_service']], item, root=True)
        elif kind in ('git-venv', 'custom-node'):
            dest = os.path.join(self.base, d['dir'])
            if not os.path.isdir(os.path.join(dest, '.git')):
                ok = self.run(['git', 'clone', '--depth', '1', d['repo'], dest], item)
            if ok and kind == 'git-venv':
                vpy = self.venv(dest, item, d.get('python', '3.12'))
                ok = bool(vpy) and (not d.get('torch') or self.torch(vpy, item, d.get('torch_version')))
                if ok and d.get('requirements'):
                    ok = self.run([self.uv(), 'pip', 'install', '--python', vpy, '-r', os.path.join(dest, d['requirements'])], item)
                if ok and d.get('service'):
                    self.write_service(d['service'], dest, vpy)
            elif ok and kind == 'custom-node':
                parent = self.stack['components'][d['parent']]
                vpy = os.path.join(self.base, parent['dir'], '.venv', 'bin', 'python')
                if d.get('requirements') and os.path.exists(os.path.join(dest, d['requirements'])):
                    ok = self.run([self.uv(), 'pip', 'install', '--python', vpy, '-r', os.path.join(dest, d['requirements'])], item)
        elif kind == 'pip-venv':
            dest = os.path.join(self.base, d['dir'])
            vpy = self.venv(dest, item, d.get('python', '3.12'))
            ok = bool(vpy) and (not d.get('torch') or self.torch(vpy, item, d.get('torch_version')))
            pk = list(d.get('pip', []))
            if self.prof == 'nvidia':
                pk += d.get('pip_nvidia', [])
            if ok and d.get('pip_from_hf'):
                hfw = d['pip_from_hf']
                whl = os.path.join(dest, os.path.basename(hfw['file']))
                ok = self.download(hf_url(hfw['repo'], hfw['file']), whl, item, None)
                pk.append(whl)
            if ok and pk:
                ok = self.run([self.uv(), 'pip', 'install', '--python', vpy] + pk, item)
        self.state['components'][cid] = {'ok': ok, 'at': time.time()}
        save_state(self.state, self.stack) if not self.dry else None
        self.emit(ev='item', id=item, state='done' if ok else 'fail', p=1.0)
        return ok

    def write_service(self, name, dest, vpy):
        args = '--listen 127.0.0.1 --port 8188'
        if self.prof == 'cpu' or (self.prof == 'amd' and self.plan['hardware'].get('rocm') == 'no'):
            args += ' --cpu'
        env = ''
        if self.plan['hardware'].get('rocm') == 'override':
            env = 'Environment=HSA_OVERRIDE_GFX_VERSION=10.3.0\n'
        unit = (f"[Unit]\nDescription=ComfyUI (Toravo OS, lokal)\n\n[Service]\nType=simple\nWorkingDirectory={dest}\n{env}"
                f"ExecStart={vpy} {dest}/main.py {args}\nRestart=on-failure\nNice=5\n\n[Install]\nWantedBy=default.target\n")
        d = os.path.expanduser('~/.config/systemd/user')
        os.makedirs(d, exist_ok=True)
        if not self.dry:
            with open(os.path.join(d, name + '.service'), 'w') as f:
                f.write(unit)
            subprocess.run(['systemctl', '--user', 'daemon-reload'], capture_output=True)

    def download(self, url, path, item, total_hint, done_before=0, grand_total=None):
        """Resumable HTTP download with progress events. grand_total: bytes of the whole model (for multi-file)."""
        if self.dry:
            return True
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path) and (not total_hint or os.path.getsize(path) == total_hint):
            return True
        part = path + '.part'
        have = os.path.getsize(part) if os.path.exists(part) else 0
        headers = {'User-Agent': UA}
        tok = hf_token()
        if tok and 'huggingface.co' in url:
            headers['Authorization'] = 'Bearer ' + tok
        if have:
            headers['Range'] = f'bytes={have}-'
        for attempt in range(5):
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=60) as r:
                    if have and r.status != 206:
                        have = 0
                    size = int(r.headers.get('Content-Length') or 0) + have
                    mode = 'ab' if have else 'wb'
                    t0, last, got = time.time(), 0, have
                    with open(part, mode) as f:
                        while True:
                            chunk = r.read(1 << 20)
                            if not chunk:
                                break
                            f.write(chunk)
                            got += len(chunk)
                            now = time.time()
                            if now - last > .4:
                                last = now
                                gt = grand_total or size
                                p = (done_before + got) / gt if gt else None
                                speed = (got - have) / max(.1, now - t0)
                                self.emit(ev='item', id=item, state='run', p=p, bytes=done_before + got, total=gt,
                                          msg=f'{os.path.basename(path)} · {fmt_bytes(done_before + got)} / {fmt_bytes(gt)} · {fmt_bytes(speed)}/s')
                os.replace(part, path)
                return True
            except (urllib.error.URLError, OSError, ValueError) as e:
                self.log(tr(f'Download-Fehler ({attempt + 1}/5): {e}', f'Download error ({attempt + 1}/5): {e}'))
                time.sleep(3 * (attempt + 1))
                have = os.path.getsize(part) if os.path.exists(part) else 0
                if have:
                    headers['Range'] = f'bytes={have}-'
        return False

    def model(self, mid):
        d = self.stack['models'][mid]
        item = 'model:' + mid
        if self.state['models'].get(mid, {}).get('ok'):
            self.emit(ev='item', id=item, state='skip', p=1.0, msg=tr('schon geladen', 'already downloaded'))
            return True
        self.emit(ev='item', id=item, state='run', p=0.0, msg=d.get('repo') or d.get('ollama'))
        ok = True
        if d.get('ollama'):
            ok = self.run(['ollama', 'pull', d['ollama']], item)
        else:
            dest = model_dest(self.stack, mid)
            if d.get('snapshot'):
                files = hf_list(d['repo'])
                files = [f for f in files if not f['path'].startswith(('assets/', 'examples/')) and not f['path'].endswith(('.whl', '.mp3', '.png', '.pdf'))]
            elif d.get('files'):
                files = [{'path': p, 'size': 0} for p in d['files']]
            else:
                files = [{'path': d['file'], 'size': int(d.get('size_gb', 0) * 1e9)}]
            total = sum(f['size'] for f in files) or None
            done = 0
            for f in files:
                if d.get('snapshot'):
                    target = os.path.join(dest, f['path'])
                elif d.get('flatten') or d.get('file'):
                    target = os.path.join(dest, os.path.basename(f['path']))
                else:
                    target = os.path.join(dest, f['path'])
                ok = self.download(hf_url(d['repo'], f['path']), target, item, f['size'] if d.get('snapshot') else None, done, total)
                if not ok:
                    break
                done += f['size']
        self.state['models'][mid] = {'ok': ok, 'at': time.time()}
        save_state(self.state, self.stack) if not self.dry else None
        self.emit(ev='item', id=item, state='done' if ok else 'fail', p=1.0)
        return ok

    def go(self, only=None, system=True):
        self.emit(ev='plan', plan=self.plan)
        if system and (not only or 'system' in only):
            if not self.system():
                self.failed.append('system')
        for c in self.plan['components']:
            if only and c['id'] not in only and not any(t['id'] in only for t in self.plan['tools'] if c['id'] in t['components']):
                continue
            if not self.component(c['id']):
                self.failed.append(c['id'])
        for m in self.plan['models']:
            if only and m['id'] not in only and not any(t['id'] in only for t in self.plan['tools'] if m['id'] in t['models']):
                continue
            if not self.model(m['id']):
                self.failed.append(m['id'])
        self.state['tools'] = {t['id']: {'variant': t['variant'], 'off': t['off'], 'label': t['label']} for t in self.plan['tools']}
        self.state['profile'] = self.prof
        self.state['hardware'] = {k: self.plan['hardware'][k] for k in ('profile', 'tier', 'vram_gb', 'gpu', 'encoders', 'rocm')}
        if not self.dry:
            save_state(self.state, self.stack)
            write_env(self.base, self.plan['hardware'])
        self.emit(ev='done', ok=not self.failed, failed=self.failed, reboot=self.state.get('system', {}).get('reboot', False))
        return not self.failed


SUDO_PASS = {'pw': None}


def missing_packages(pk):
    """Only packages that are not installed yet (pacman -T prints the unsatisfied ones)."""
    if not pk:
        return []
    r = subprocess.run(['pacman', '-T'] + list(pk), capture_output=True, text=True)
    return [x for x in r.stdout.split() if x]


def write_env(base, info):
    lines = ['# Toravo OS – Umgebung fuer lokale KI-Werkzeuge (von Toravo Setup erzeugt)', f'export TORAVO_PROFILE={info["profile"]}',
             f'export TORAVO_AI={base}', f'export HF_HOME={base}/hf-cache']
    if info.get('rocm') == 'override':
        lines.append('export HSA_OVERRIDE_GFX_VERSION=10.3.0')
    with open(os.path.join(base, 'env.sh'), 'w') as f:
        f.write('\n'.join(lines) + '\n')


def hf_url(repo, path):
    return f'https://huggingface.co/{repo}/resolve/main/{urllib.request.quote(path)}'


def hf_token():
    for p in (os.environ.get('HF_TOKEN_PATH', ''), os.path.expanduser('~/.cache/huggingface/token')):
        if p and os.path.exists(p):
            try:
                return open(p).read().strip()
            except OSError:
                pass
    return os.environ.get('HF_TOKEN', '')


def hf_list(repo):
    req = urllib.request.Request(f'https://huggingface.co/api/models/{repo}/tree/main?recursive=true', headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    return [{'path': f['path'], 'size': int(f.get('size', 0))} for f in data if f.get('type') == 'file']


def fmt_bytes(n):
    n = float(n or 0)
    for u in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024 or u == 'TB':
            return f'{n:.1f} {u}' if u not in ('B', 'KB') else f'{n:.0f} {u}'
        n /= 1024


def tool_ready(tool_id, state=None):
    """Is a tool installed (all components/models ok)? Used by Command Bar / Studio / queue."""
    stack = load_stack()
    st = state or load_state(stack)
    t = st.get('tools', {}).get(tool_id)
    if not t or t.get('off'):
        return False
    tdef = next(x for x in stack['tools'] if x['id'] == tool_id)
    v = next((x for x in tdef['variants'] if x['id'] == t['variant']), None)
    if not v:
        return False
    return all(st['components'].get(c, {}).get('ok') for c in v.get('components', [])) and \
        all(st['models'].get(m, {}).get('ok') for m in v.get('models', []))


def main():
    a = sys.argv[1:]
    cmd = a[0] if a else 'plan'
    as_json = '--json' in a
    extras = ()
    if '--with' in a:
        extras = tuple(a[a.index('--with') + 1].split(','))
    stack = load_stack()
    if cmd == 'plan':
        plan = resolve(stack=stack, extras=extras)
        if as_json:
            print(json.dumps(plan, indent=2, ensure_ascii=False))
            return
        h = plan['hardware']
        print(tr('Profil', 'Profile') + f" {h['profile']} · {h['tier']} · {h['vram_gb']} GB VRAM · {h['gpu']}")
        for t in plan['tools']:
            print(f"  {t['title']:<28} {tr('AUS', 'OFF') if t['off'] else tr('an ', 'on ')}  {t['label']}")
        print(tr('Download/Installation gesamt: ca. ', 'Download/install total: approx. ') + f"{plan['total_gb']} GB")
    elif cmd == 'install':
        only = set(a[a.index('--only') + 1].split(',')) if '--only' in a else None
        plan = resolve(stack=stack, extras=extras)
        if '--sudo-stdin' in a:
            SUDO_PASS['pw'] = sys.stdin.readline().rstrip('\n')
        ok = Runner(plan, stack, as_json, '--dry-run' in a).go(only, system='--no-system' not in a)
        sys.exit(0 if ok else 1)
    elif cmd == 'status':
        st = load_state(stack)
        print(json.dumps(st, indent=2, ensure_ascii=False) if as_json else
              '\n'.join(f"{k}: {'ok' if v.get('ok') else tr('fehlt', 'missing')}" for sec in ('components', 'models') for k, v in st.get(sec, {}).items()) or tr('nichts installiert', 'nothing installed'))
    elif cmd == 'licenses':
        for cid, c in stack['components'].items():
            print(f"{loc(c, 'title'):<28} {loc(c, 'license')}")
        for mid, m in stack['models'].items():
            print(f"{(m.get('repo') or m.get('ollama')):<45} {loc(m, 'license')}")
    else:
        print(__doc__)


if __name__ == '__main__':
    main()
