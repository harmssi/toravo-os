"""Toravo Update – tested, signed system updates that never break the running session (docs/UPDATES.md).

  toravo-update status [--json]              state for the UI / Waybar (also readable without root)
  toravo-update check [--force]              fetch + verify the signed channel manifest, download the update in the background
                                             (only when idle: no render job, no stream, on AC power) -> "ready"
  toravo-update apply-offline                (system-update.target) install the prepared update before the desktop starts
  toravo-update health                       (every boot) desktop + Toravo services up? -> keep, else automatic rollback
  toravo-update finish-rollback              (boot entry "previous version", toravo.rollback=1) make the old system permanent
  toravo-update rollback [--snapshot N]      back to the version before the last update (or a snapper snapshot) + reboot
  toravo-update set [--channel stable|rolling] [--auto on|off]
  toravo-update setup                        write pacman.conf / mirrorlist / keyring for Toravo Update (installer, migration)
  toravo-update cancel                       forget a prepared update

Channels: stable = Arch packages pinned to an Arch Linux Archive date that Toravo tested (signed manifest), rolling = live
Arch mirrors + the newest Toravo packages. Rollback: before installing, @ is snapshotted to the writable subvolume @rollback and
the kernel/initramfs to /boot/toravo-prev; snap-pac additionally creates the snapper pre/post snapshots.
"""
import json, os, re, shutil, subprocess, sys, tempfile, time, urllib.request
from .theme import tr

REPO = 'https://github.com/harmssi/toravo-os/releases/download/repo-{channel}'
CONF = '/etc/toravo/update.json'
VAR = '/var/lib/toravo-update'
# state lives on the @log subvolume: it must survive a rollback of @ (the system subvolume is swapped, @log is not)
STATE = '/var/log/toravo-update/state.json'
DB = VAR + '/db'
LOG = '/var/log/toravo-update.log'
KEYRING = '/usr/share/pacman/keyrings/toravo.gpg'
MIRRORS = '/etc/pacman.d/toravo-mirrorlist'
REPOFILE = '/etc/pacman.d/toravo-repo'
TOP = '/run/toravo-btrfs'
PREV = '/boot/toravo-prev'
ARCHIVE = 'https://archive.archlinux.org/repos/{date}/$repo/os/$arch'
CHANNELS = ('stable', 'rolling')
KERNEL_PKGS = ('linux', 'linux-headers')
NV_PREBUILT = ('nvidia-open', 'nvidia')
NV_DKMS = ('nvidia-open-dkms', 'nvidia-dkms')
UA = 'ToravoOS-Update/1.0'


# ------------------------------------------------------------------------------------------------ small helpers
def log(msg):
    line = time.strftime('%Y-%m-%d %H:%M:%S ') + str(msg)
    try:
        with open(LOG, 'a') as f:
            f.write(line + '\n')
    except OSError:
        pass
    print(line, flush=True)


def run(cmd, check=True, **kw):
    log('$ ' + ' '.join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    out = (r.stdout or '') + (r.stderr or '')
    if out.strip():
        try:
            with open(LOG, 'a') as f:
                f.write(out[-20000:] + ('\n' if not out.endswith('\n') else ''))
        except OSError:
            pass
    if check and r.returncode != 0:
        raise RuntimeError(f'{cmd[0]} exit {r.returncode}: {out.strip()[-400:]}')
    return r


def load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save(path, data, mode=0o644):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def conf():
    c = {'channel': 'stable', 'auto': True}
    c.update(load(CONF, {}))
    if c['channel'] not in CHANNELS:
        c['channel'] = 'stable'
    return c


def state():
    return load(STATE, {'status': 'idle'})


def set_state(**kw):
    st = state()
    st.update(kw)
    st['updated'] = time.time()
    save(STATE, st)
    return st


def installed_version():
    r = subprocess.run(['pacman', '-Q', 'toravo-os'], capture_output=True, text=True)
    return r.stdout.split()[1].split('-')[0] if r.returncode == 0 else '?'


def fetch(url, dest, timeout=60):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, 'wb') as f:
        shutil.copyfileobj(r, f)


def verify(sig, path):
    """Only the Toravo release key counts (not the whole pacman keyring with all Arch packagers)."""
    r = subprocess.run(['gpgv', '--keyring', KEYRING, sig, path], capture_output=True, text=True)
    return r.returncode == 0


def uefi():
    return os.path.isdir('/sys/firmware/efi')


# ------------------------------------------------------------------------------------------------ manifest + pacman setup
def repo_url(c=None):
    c = c or conf()
    return c.get('repo_url') or REPO.format(channel=c['channel'])


def manifest(c=None):
    """Signed channel manifest: {"channel","version","arch_snapshot":"YYYY/MM/DD"|null,"notes":{"de","en"},"date"}."""
    c = c or conf()
    url = c.get('manifest_url') or repo_url(c) + '/manifest.json'
    with tempfile.TemporaryDirectory() as td:
        m, s = os.path.join(td, 'manifest.json'), os.path.join(td, 'manifest.json.sig')
        fetch(url, m)
        fetch(url + '.sig', s)
        if not verify(s, m):
            raise RuntimeError(tr('Update-Manifest nicht korrekt signiert – nichts geändert.', 'Update manifest is not signed correctly – nothing changed.'))
        data = load(m, None)
    if not data or not re.match(r'^\d+\.\d+\.\d+', str(data.get('version', ''))):
        raise RuntimeError('bad manifest')
    snap = data.get('arch_snapshot')
    if snap and not re.match(r'^\d{4}/\d{2}/\d{2}$', snap):
        raise RuntimeError('bad arch_snapshot')
    return data


def mirrorlist_text(c, m):
    if c['channel'] == 'stable' and m.get('arch_snapshot'):
        return f"# Toravo Update – channel stable, Arch Linux Archive {m['arch_snapshot']} (tested by Toravo)\n" \
               f"Server = {ARCHIVE.format(date=m['arch_snapshot'])}\n"
    try:
        live = open('/etc/pacman.d/mirrorlist').read()
    except OSError:
        live = 'Server = https://geo.mirror.pkgbuild.com/$repo/os/$arch\n'
    return '# Toravo Update – channel rolling: live Arch mirrors (copy of /etc/pacman.d/mirrorlist)\n' + live


PACMAN_CONF = """# Toravo OS – written by toravo-update setup (backup of the previous file: /etc/pacman.conf.toravo-bak)
[options]
HoldPkg     = pacman glibc
Architecture = auto
CheckSpace
ParallelDownloads = 5
SigLevel    = Required DatabaseOptional
LocalFileSigLevel = Optional

# Toravo packages: signed repo on GitHub (channel in /etc/toravo/update.json, managed by Toravo Update)
[toravo]
SigLevel = Required DatabaseRequired
Include = /etc/pacman.d/toravo-repo

# Arch Linux: stable = tested Arch Linux Archive date, rolling = live mirrors
[core]
Include = /etc/pacman.d/toravo-mirrorlist

[extra]
Include = /etc/pacman.d/toravo-mirrorlist
"""


def setup(snapshot=None):
    """pacman.conf + repo/mirror files + keyring. snapshot: Arch date of the installed packages (ISO build date)."""
    c = conf()
    if os.path.exists('/etc/pacman.conf') and not open('/etc/pacman.conf').read().startswith('# Toravo OS – written by toravo-update'):
        shutil.copy2('/etc/pacman.conf', '/etc/pacman.conf.toravo-bak')
    with open('/etc/pacman.conf', 'w') as f:
        f.write(PACMAN_CONF)
    with open(REPOFILE, 'w') as f:
        f.write(f'Server = {repo_url(c)}\n')
    if not os.path.exists(MIRRORS):
        with open(MIRRORS, 'w') as f:
            f.write(mirrorlist_text(c, {'arch_snapshot': snapshot}))
    if not os.path.exists(CONF):
        save(CONF, {'channel': c['channel'], 'auto': c['auto']})
    run(['pacman-key', '--populate', 'toravo'], check=False)
    os.makedirs(VAR, exist_ok=True)
    if not os.path.exists(STATE):
        set_state(status='idle', version=installed_version(), channel=c['channel'], last_update=None, arch_snapshot=snapshot)


def tmp_pacman_conf(nextlist):
    txt = open('/etc/pacman.conf').read().replace('Include = ' + MIRRORS, 'Include = ' + nextlist)
    p = os.path.join(VAR, 'pacman.conf')
    with open(p, 'w') as f:
        f.write(txt)
    return p


# ------------------------------------------------------------------------------------------------ "is now a good time?"
def busy_reason():
    """None if the machine may download now: no render job, no stream, not on battery, low load."""
    import glob
    for qd in glob.glob('/home/*/.local/share/toravo/queue'):
        for f in glob.glob(qd + '/*.json'):
            if load(f, {}).get('state') in ('running', 'queued'):
                return 'render-queue'
    for lf in glob.glob('/home/*/.local/state/toravo/live.json'):
        pid = load(lf, {}).get('pid')
        if pid and os.path.exists(f'/proc/{int(pid)}'):
            return 'stream'
    bats = [p for p in glob.glob('/sys/class/power_supply/*') if open(p + '/type').read().strip() == 'Battery']
    if bats:
        mains = [p for p in glob.glob('/sys/class/power_supply/*') if open(p + '/type').read().strip() in ('Mains', 'USB')]
        if not any(open(p + '/online').read().strip() == '1' for p in mains if os.path.exists(p + '/online')):
            return 'battery'
    if os.getloadavg()[0] > max(1.0, (os.cpu_count() or 1) * 0.5):
        return 'load'
    return None


# ------------------------------------------------------------------------------------------------ check / prepare
def pending_list(cfg):
    r = run(['pacman', '-Qu', '--dbpath', DB, '--config', cfg], check=False)
    ups = []
    for line in r.stdout.splitlines():
        p = line.split()
        if len(p) >= 4 and p[2] == '->':
            ups.append({'name': p[0], 'old': p[1], 'new': p[3]})
    return ups


def installed(name):
    return subprocess.run(['pacman', '-Q', name], capture_output=True).returncode == 0


def kernel_guard(ups):
    """Kernel and NVIDIA modules only together: prebuilt nvidia(-open) is built for exactly one kernel."""
    names = {u['name'] for u in ups}
    nv = next((p for p in NV_PREBUILT if installed(p)), None)
    if not nv:
        return [], ''
    k, n = 'linux' in names, nv in names
    if k == n:
        return [], ''
    hold = sorted(x for x in names if x in KERNEL_PKGS or x.startswith(('nvidia', 'opencl-nvidia', 'lib32-nvidia')))
    return hold, tr('Kernel und NVIDIA-Treiber passen in diesem Update nicht zusammen – beide bleiben auf dem alten Stand.',
                    'Kernel and NVIDIA driver do not match in this update – both stay on the current version.')


def set_up():
    try:
        return open('/etc/pacman.conf').read().startswith('# Toravo OS – written by toravo-update')
    except OSError:
        return False


def check(force=False):
    c = conf()
    st = state()
    if not set_up():  # never touch a system whose pacman.conf is not managed by Toravo Update (run: toravo-update setup)
        log('check: pacman.conf not managed by Toravo Update – skipped')
        return set_state(status='off', message=tr('Toravo Update ist auf diesem System nicht eingerichtet (sudo toravo-update setup).',
                                                  'Toravo Update is not set up on this system (sudo toravo-update setup).'))
    if st.get('status') == 'ready' and os.path.lexists('/system-update') and not force:
        return st
    if not force:
        why = busy_reason()
        if why:
            log(f'check: later ({why})')
            return set_state(status=st.get('status') if st.get('status') == 'ready' else 'waiting', waiting_for=why, last_check=time.time())
    set_state(status='checking', last_check=time.time(), message='')
    try:
        m = manifest(c)
        nextlist = os.path.join(VAR, 'mirrorlist.next')
        with open(nextlist, 'w') as f:
            f.write(mirrorlist_text(c, m))
        with open(os.path.join(VAR, 'repo.next'), 'w') as f:
            f.write(f'Server = {repo_url(c)}\n')
        cfg = tmp_pacman_conf(nextlist)
        cfg_txt = open(cfg).read().replace('Include = ' + REPOFILE, 'Include = ' + os.path.join(VAR, 'repo.next'))
        open(cfg, 'w').write(cfg_txt)
        os.makedirs(DB + '/sync', exist_ok=True)
        if not os.path.islink(DB + '/local'):
            shutil.rmtree(DB + '/local', ignore_errors=True)
            os.symlink('/var/lib/pacman/local', DB + '/local')
        run(['pacman', '-Sy', '--dbpath', DB, '--config', cfg, '--noconfirm'])
        ups = pending_list(cfg)
        hold, note = kernel_guard(ups)
        ups = [u for u in ups if u['name'] not in hold]
        if not ups:
            return set_state(status='idle', available=None, manifest=m, message=note or tr('Alles aktuell.', 'Up to date.'),
                             channel=c['channel'], version=installed_version())
        cmd = ['pacman', '-Suw', '--dbpath', DB, '--config', cfg, '--noconfirm'] + (['--ignore', ','.join(hold)] if hold else [])
        set_state(status='downloading', available={'version': m['version'], 'count': len(ups)})
        run(cmd)
        kernel = any(u['name'] == 'linux' or u['name'] in NV_PREBUILT + NV_DKMS for u in ups)
        linux = any(u['name'] == 'linux' for u in ups)
        prepared = {'version': m['version'], 'notes': m.get('notes', {}), 'packages': ups, 'hold': hold, 'kernel': kernel, 'linux': linux,
                    'arch_snapshot': m.get('arch_snapshot'), 'channel': c['channel'], 'downgrade': bool(st.get('channel_changed')),
                    'prepared_at': time.time()}
        save(os.path.join(VAR, 'prepared.json'), prepared)
        if os.path.lexists('/system-update'):
            os.remove('/system-update')
        os.symlink(VAR, '/system-update')  # systemd offline update: installed at the next start, before the desktop
        log(f'ready: {m["version"]} ({len(ups)} packages)')
        return set_state(status='ready', available=prepared, message=note, waiting_for=None)
    except Exception as e:  # noqa: BLE001
        log(f'check failed: {e}')
        return set_state(status='error', message=str(e)[-300:])


def cancel():
    if os.path.lexists('/system-update'):
        os.remove('/system-update')
    set_state(status='idle', available=None)


# ------------------------------------------------------------------------------------------------ btrfs + boot helpers
def root_dev():
    return run(['findmnt', '-no', 'SOURCE', '/']).stdout.strip().split('[')[0]


def mount_top():
    os.makedirs(TOP, exist_ok=True)
    if subprocess.run(['mountpoint', '-q', TOP]).returncode != 0:
        run(['mount', '-o', 'subvolid=5', root_dev(), TOP])
    return TOP


def umount_top():
    subprocess.run(['umount', TOP], capture_output=True)


def entries_dir():
    return '/boot/loader/entries'


def loader_conf():
    for p in ('/efi/loader/loader.conf', '/boot/loader/loader.conf', '/boot/efi/loader/loader.conf'):
        if os.path.exists(p):
            return p
    return None


def main_entry():
    d = entries_dir()
    for n in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if re.match(r'^toravo(\+\d+(-\d+)?)?\.conf$', n):
            return os.path.join(d, n)
    return None


def set_loader_default(entry_id):
    p = loader_conf()
    if not p:
        return
    txt = open(p).read()
    txt = re.sub(r'^default .*$', f'default {entry_id}', txt, flags=re.M) if re.search(r'^default ', txt, re.M) else f'default {entry_id}\n' + txt
    with open(p, 'w') as f:
        f.write(txt)


def backup_boot():
    """Kernel + initramfs of the running system -> /boot/toravo-prev (they belong to @rollback)."""
    os.makedirs(PREV, exist_ok=True)
    for n in ('vmlinuz-linux', 'initramfs-linux.img'):
        if os.path.exists('/boot/' + n):
            shutil.copy2('/boot/' + n, os.path.join(PREV, n))


def write_previous_entry():
    """UEFI: boot entry for the version before the update (old kernel, subvolume @rollback)."""
    me = main_entry()
    if not me or not uefi():
        return
    opts = next((l.split(None, 1)[1] for l in open(me) if l.startswith('options')), '').strip()
    opts = re.sub(r'rootflags=subvol=\S+', 'rootflags=subvol=@rollback', opts)
    opts = re.sub(r'\s*toravo\.rollback=1', '', opts) + ' toravo.rollback=1'
    with open(os.path.join(entries_dir(), 'toravo-previous.conf'), 'w') as f:
        f.write(f'title   {tr("Toravo OS (vorherige Version)", "Toravo OS (previous version)")}\nsort-key toravo-2\n'
                f'linux   /toravo-prev/vmlinuz-linux\ninitrd  /toravo-prev/initramfs-linux.img\noptions {opts}\n')


def ensure_panic_reboot():
    me = main_entry()
    if not me:
        return
    txt = open(me).read()
    if 'panic=' not in txt:
        txt = re.sub(r'^(options .*)$', r'\1 panic=10', txt, count=1, flags=re.M)
        open(me, 'w').write(txt)


def grub_previous_entry():
    """BIOS/GRUB: menu entry for @rollback (manual choice – GRUB cannot write its environment on btrfs, see docs)."""
    uuid = run(['findmnt', '-no', 'UUID', '/']).stdout.strip()
    with open('/etc/grub.d/42_toravo_previous', 'w') as f:
        f.write('#!/bin/sh\ncat <<EOF\n'
                f"menuentry '{tr('Toravo OS (vorherige Version)', 'Toravo OS (previous version)')}' {{\n"
                f'  search --no-floppy --fs-uuid --set=root {uuid}\n'
                f'  linux /@rollback/boot/vmlinuz-linux root=UUID={uuid} rootflags=subvol=@rollback rw quiet splash toravo.rollback=1\n'
                f'  initrd /@rollback/boot/initramfs-linux.img\n}}\nEOF\n')
    os.chmod('/etc/grub.d/42_toravo_previous', 0o755)
    run(['grub-mkconfig', '-o', '/boot/grub/grub.cfg'], check=False)


def reboot():
    # no logind/D-Bus during the offline update: skip the inhibitor check, PID 1 handles the reboot directly
    run(['systemctl', 'reboot', '--check-inhibitors=no'], check=False)


def plymouth(msg):
    subprocess.run(['plymouth', 'display-message', '--text=' + msg], capture_output=True)


# ------------------------------------------------------------------------------------------------ offline install
def kernel_ok(t0, linux=True):
    """After the transaction: initramfs fresh and, with NVIDIA, the module exists for the installed kernel."""
    kv = None
    for d in sorted(os.listdir('/usr/lib/modules')):
        if open(f'/usr/lib/modules/{d}/pkgbase').read().strip() == 'linux' if os.path.exists(f'/usr/lib/modules/{d}/pkgbase') else False:
            kv = d
    if not kv:
        return False, 'no kernel modules for linux'
    img = '/boot/initramfs-linux.img'
    if not os.path.exists(img) or os.path.getsize(img) < 1_000_000 or (linux and os.path.getmtime(img) < t0):
        return False, 'initramfs not rebuilt'
    if any(installed(p) for p in NV_PREBUILT + NV_DKMS):
        if subprocess.run(['modinfo', '-k', kv, 'nvidia'], capture_output=True).returncode != 0:
            return False, f'NVIDIA module missing for kernel {kv}'
    return True, kv


def apply_offline():
    if os.path.lexists('/system-update'):
        os.remove('/system-update')  # first thing (systemd.offline-updates): never loop
    p = load(os.path.join(VAR, 'prepared.json'), None)
    if not p:
        reboot()
        return
    set_state(status='installing')
    plymouth(tr('Toravo OS wird aktualisiert – bitte nicht ausschalten …', 'Updating Toravo OS – please do not switch off …'))
    t0 = time.time()
    ok, why = False, ''
    try:
        top = mount_top()
        if os.path.isdir(top + '/@rollback'):
            run(['btrfs', 'subvolume', 'delete', top + '/@rollback'])
        run(['btrfs', 'subvolume', 'snapshot', top + '/@', top + '/@rollback'])
        backup_boot()
        os.makedirs('/var/lib/pacman/sync', exist_ok=True)
        for n in os.listdir(DB + '/sync'):
            shutil.copy2(os.path.join(DB, 'sync', n), os.path.join('/var/lib/pacman/sync', n))
        shutil.copy2(os.path.join(VAR, 'mirrorlist.next'), MIRRORS)
        shutil.copy2(os.path.join(VAR, 'repo.next'), REPOFILE)
        cmd = ['pacman', '-Su' + ('u' if p.get('downgrade') else ''), '--noconfirm'] + (['--ignore', ','.join(p['hold'])] if p.get('hold') else [])
        # snapper pre/post ourselves: there is no D-Bus in system-update.target, so snap-pac's hooks would fail (SNAP_PAC_SKIP)
        desc = f'Toravo Update {p["version"]}'
        imp = ['--userdata', 'important=yes'] if p.get('kernel') else []
        pre = run(['snapper', '--no-dbus', '-c', 'root', 'create', '--type', 'pre', '--cleanup-algorithm', 'number', '--print-number',
                   '--description', desc] + imp, check=False).stdout.strip()
        run(cmd, env=dict(os.environ, SNAP_PAC_SKIP='y'))
        if pre.isdigit():
            run(['snapper', '--no-dbus', '-c', 'root', 'create', '--type', 'post', '--pre-number', pre, '--cleanup-algorithm', 'number',
                 '--description', desc] + imp, check=False)
        if p.get('kernel'):
            ok, why = kernel_ok(t0, p.get('linux', True))
        else:
            ok = True
    except Exception as e:  # noqa: BLE001
        why = str(e)[-300:]
    if not ok:
        log(f'update failed: {why} -> back to the previous version')
        plymouth(tr('Update fehlgeschlagen – zurück zur vorherigen Version …', 'Update failed – going back to the previous version …'))
        set_state(status='rolled_back', message=tr('Das Update ließ sich nicht sauber installieren und wurde zurückgenommen: ', 'The update could not be installed cleanly and was undone: ') + why,
                  available=None)
        swap_to_rollback(restore_boot=True)
        reboot()
        return
    if uefi():
        write_previous_entry()
        ensure_panic_reboot()
        set_loader_default('toravo-previous.conf')   # if the new system does not come up, the next start is the old one
        run(['bootctl', 'set-oneshot', os.path.basename(main_entry())], check=False)  # this one start: the new system
    else:
        grub_previous_entry()
    set_state(status='verifying', version=installed_version(), last_update=time.time(), installed=p, available=None,
              arch_snapshot=p.get('arch_snapshot'), channel_changed=False, health_pending=True, message='')
    umount_top()
    log(f'installed {p["version"]}, rebooting into it')
    reboot()


# ------------------------------------------------------------------------------------------------ health + rollback
def desktop_up():
    procs = subprocess.run(['ps', '-eo', 'comm='], capture_output=True, text=True).stdout.split()
    if subprocess.run(['systemctl', 'is-active', '--quiet', 'greetd.service']).returncode != 0:
        return False, 'greetd'
    autologin = '[initial_session]' in (open('/etc/greetd/config.toml').read() if os.path.exists('/etc/greetd/config.toml') else '')
    if autologin and not any(p in procs for p in ('Hyprland', 'labwc')):
        return False, 'desktop session (auto-login)'
    if not any(p in procs for p in ('Hyprland', 'labwc', 'regreet', 'cage')):
        return False, 'compositor/greeter'
    if any(p in procs for p in ('Hyprland', 'labwc')):
        args = subprocess.run(['ps', '-eo', 'args='], capture_output=True, text=True).stdout
        if 'toravo.queue' not in args or 'waybar' not in procs:
            return False, 'toravo services'
    return True, ''


def health(timeout=240):
    st = state()
    if not st.get('health_pending'):
        return 0
    t_end = time.time() + timeout
    why = ''
    while time.time() < t_end:
        ok, why = desktop_up()
        if ok:
            time.sleep(20)  # stays up?
            ok, why = desktop_up()
            if ok:
                if uefi():
                    set_loader_default('toravo.conf')
                set_state(status='idle', health_pending=False, message=tr('Update installiert: ', 'Update installed: ') + str(st.get('version')))
                log('health ok')
                return 0
        time.sleep(5)
    log(f'health failed: {why} -> rollback')
    set_state(status='rolled_back', health_pending=False,
              message=tr('Nach dem Update startete der Desktop nicht richtig – Toravo ist automatisch zur vorherigen Version zurückgekehrt.',
                         'After the update the desktop did not start properly – Toravo went back to the previous version automatically.') + f' ({why})')
    swap_to_rollback(restore_boot=True)
    reboot()
    return 1


def restore_boot_files():
    for n in ('vmlinuz-linux', 'initramfs-linux.img'):
        if os.path.exists(os.path.join(PREV, n)):
            shutil.copy2(os.path.join(PREV, n), '/boot/' + n)


def swap_to_rollback(restore_boot=True):
    """@ -> @old-<time>, @rollback -> @ (renaming mounted subvolumes is fine on btrfs), old kernel back to /boot."""
    top = mount_top()
    if not os.path.isdir(top + '/@rollback'):
        raise RuntimeError('no @rollback')
    old = top + time.strftime('/@old-%Y%m%d-%H%M%S')
    os.rename(top + '/@', old)
    os.rename(top + '/@rollback', top + '/@')
    if restore_boot:
        restore_boot_files()
    if uefi():
        set_loader_default('toravo.conf')
        p = os.path.join(entries_dir(), 'toravo-previous.conf')
        if os.path.exists(p):
            os.remove(p)
    else:
        if os.path.exists('/etc/grub.d/42_toravo_previous'):
            os.remove('/etc/grub.d/42_toravo_previous')
    prune_old(top)
    log(f'rollback: @ is the previous version again, broken system kept as {os.path.basename(old)}')


def prune_old(top, keep=1):
    olds = sorted(n for n in os.listdir(top) if n.startswith('@old-'))
    for n in olds[:-keep] if len(olds) > keep else []:
        subprocess.run(['btrfs', 'subvolume', 'delete', os.path.join(top, n)], capture_output=True)


def finish_rollback():
    """Booted via "previous version" (rootflags=subvol=@rollback): make it the normal system again."""
    if 'toravo.rollback=1' not in open('/proc/cmdline').read():
        return 0
    top = mount_top()
    if os.path.isdir(top + '/@rollback'):
        old = top + time.strftime('/@old-%Y%m%d-%H%M%S')
        os.rename(top + '/@', old)
        os.rename(top + '/@rollback', top + '/@')
    restore_boot_files()
    if uefi():
        set_loader_default('toravo.conf')
        p = os.path.join(entries_dir(), 'toravo-previous.conf')
        if os.path.exists(p):
            os.remove(p)
    prune_old(top)
    set_state(status='rolled_back', health_pending=False, version=installed_version(),
              message=tr('Das neue System startete nicht – Toravo ist automatisch zur vorherigen Version zurückgekehrt.',
                         'The new system did not start – Toravo went back to the previous version automatically.'))
    log('finish-rollback: previous version is permanent again')
    return 0


def snapshots():
    """Snapper pre snapshots of the root config (newest first) for the manual rollback list."""
    r = subprocess.run(['snapper', '--no-dbus', '--machine-readable', 'json', '-c', 'root', 'list'], capture_output=True, text=True)
    try:
        data = json.loads(r.stdout).get('root', [])
    except ValueError:
        return []
    out = [{'number': s['number'], 'date': s.get('date', ''), 'description': s.get('description', ''), 'type': s.get('type')}
           for s in data if s.get('type') == 'pre']
    return sorted(out, key=lambda s: -s['number'])[:10]


def rollback(snapshot=None):
    """Manual "back to the previous version": @rollback (state before the last update) or a snapper pre snapshot."""
    top = mount_top()
    if not snapshot and not os.path.isdir(top + '/@rollback'):
        pre = snapshots()  # @rollback already used (automatic rollback) -> newest snapper pre snapshot
        if not pre:
            raise RuntimeError(tr('Keine vorherige Version gefunden.', 'No previous version found.'))
        snapshot = pre[0]['number']
    if snapshot:
        src = f'{top}/@snapshots/{int(snapshot)}/snapshot'
        if not os.path.isdir(src):
            raise RuntimeError(f'snapshot {snapshot} not found')
        if os.path.isdir(top + '/@rollback'):
            run(['btrfs', 'subvolume', 'delete', top + '/@rollback'])
        run(['btrfs', 'subvolume', 'snapshot', src, top + '/@rollback'])
        swap_to_rollback(restore_boot=False)
        rebuild_initramfs(top + '/@')
    else:
        swap_to_rollback(restore_boot=True)
    set_state(status='rolled_back', health_pending=False, message=tr('Zur vorherigen Version zurückgekehrt.', 'Went back to the previous version.'))
    reboot()


def rebuild_initramfs(root):
    """Kernel of an older snapshot: vmlinuz from its /usr/lib/modules, initramfs built inside it (arch-chroot)."""
    kv = next((d for d in sorted(os.listdir(root + '/usr/lib/modules'))
               if os.path.exists(f'{root}/usr/lib/modules/{d}/pkgbase') and open(f'{root}/usr/lib/modules/{d}/pkgbase').read().strip() == 'linux'), None)
    if not kv:
        raise RuntimeError('snapshot has no linux kernel')
    shutil.copy2(f'{root}/usr/lib/modules/{kv}/vmlinuz', '/boot/vmlinuz-linux')
    if uefi():
        run(['mount', '--bind', '/boot', root + '/boot'], check=False)
    run(['arch-chroot', root, 'mkinitcpio', '-p', 'linux'], check=False)
    subprocess.run(['umount', root + '/boot'], capture_output=True)


# ------------------------------------------------------------------------------------------------ CLI
def status_json():
    st = state()
    c = conf()
    st['version'] = installed_version()  # always the running system (the state file survives rollbacks, the system does not)
    st['channel'] = c['channel']
    st['auto'] = c['auto']
    st['pending_reboot'] = os.path.lexists('/system-update')
    return st


def main():
    a = sys.argv[1:]
    cmd = a[0] if a else 'status'
    if cmd == 'status':
        st = status_json()
        if '--json' in a:
            print(json.dumps(st, indent=2, ensure_ascii=False))
        else:
            print(f"Toravo OS {st.get('version')} · {st['channel']} · auto {'on' if st['auto'] else 'off'} · {st.get('status')}"
                  + (f" · {st.get('message')}" if st.get('message') else ''))
        return 0
    if os.geteuid() != 0:
        print('toravo-update: needs root (pkexec toravo-update …)', file=sys.stderr)
        return 1
    os.makedirs(VAR, exist_ok=True)
    if os.path.isdir('/run/archiso') and cmd in ('check', 'apply-offline', 'health', 'rollback'):
        print('toravo-update: not in the live system', file=sys.stderr)
        return 0
    if cmd == 'check':
        c = conf()
        if not c['auto'] and '--force' not in a and '--timer' in a:
            log('check: auto updates off')
            return 0
        st = check(force='--force' in a)
        return 0 if st.get('status') in ('ready', 'idle', 'waiting', 'off') else 1
    if cmd == 'apply-offline':
        apply_offline()
    elif cmd == 'health':
        return health()
    elif cmd == 'finish-rollback':
        return finish_rollback()
    elif cmd == 'rollback':
        rollback(a[a.index('--snapshot') + 1] if '--snapshot' in a else None)
    elif cmd == 'snapshots':
        print(json.dumps(snapshots(), indent=2))
    elif cmd == 'set':
        c = conf()
        if '--channel' in a:
            ch = a[a.index('--channel') + 1]
            if ch not in CHANNELS:
                print('channel: stable | rolling', file=sys.stderr)
                return 2
            if ch != c['channel']:
                c['channel'] = ch
                cancel()
                set_state(channel_changed=True)
                with open(REPOFILE, 'w') as f:
                    f.write(f'Server = {repo_url(c)}\n')
        if '--auto' in a:
            c['auto'] = a[a.index('--auto') + 1] in ('on', '1', 'true', 'yes')
        save(CONF, c)
    elif cmd == 'setup':
        setup(a[a.index('--snapshot') + 1] if '--snapshot' in a else None)
    elif cmd == 'cancel':
        cancel()
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)
