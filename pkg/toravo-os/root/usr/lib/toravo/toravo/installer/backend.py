"""Toravo OS install backend (runs as root, offline – copies the live system, no download needed).

usage: toravo-install-backend <config.json> [--json]
config: disk, mode (empty|alongside|erase), confirm (disk name, required for erase), fullname, user, password, hostname,
        autologin, lang, keymap, xkb_layout, xkb_variant, timezone
Layout: GPT · EFI 1 GiB (or existing ESP + 1 GiB XBOOTLDR when installing alongside) · btrfs (@ @home @snapshots @log @pkg)
        zstd · systemd-boot (UEFI) / GRUB (BIOS) · zram swap · snapper + snap-pac snapshots for rollback.
"""
import json, os, re, shutil, subprocess, sys, time
from . import disks as D
from ..theme import tr

T = '/mnt/toravo-target'
JSON = '--json' in sys.argv
LOG = '/var/log/toravo-install.log'
SRC_SQUASH = '/run/archiso/airootfs'
OFFLINE_REPO = '/opt/toravo/offline-repo'
STEPS = [('check', .02), ('partition', .05), ('format', .05), ('copy', .55), ('system', .15), ('drivers', .08), ('boot', .07), ('finish', .03)]


class Fail(Exception):
    pass


def emit(**ev):
    line = json.dumps(ev, ensure_ascii=False)
    with open(LOG, 'a') as f:
        f.write(line + '\n')
    if JSON:
        print(line, flush=True)
    elif ev.get('ev') in ('step', 'error', 'done'):
        print(ev, flush=True)


_prog = {'step': None}


def progress(step, frac, msg=''):
    done = 0.0
    for name, w in STEPS:
        if name == step:
            done += w * max(0.0, min(1.0, frac))
            break
        done += w
    emit(ev='progress', step=step, p=round(done, 4), msg=msg)


def sh(cmd, check=True, input=None, chroot=False):
    if chroot:
        cmd = ['arch-chroot', T] + cmd
    with open(LOG, 'a') as f:
        f.write('$ ' + ' '.join(cmd) + '\n')
    r = subprocess.run(cmd, capture_output=True, text=True, input=input)
    with open(LOG, 'a') as f:
        f.write((r.stdout or '')[-4000:] + (r.stderr or '')[-4000:])
    if check and r.returncode != 0:
        raise Fail(f'{" ".join(cmd[:4])} ' + tr('fehlgeschlagen', 'failed') + f': {(r.stderr or r.stdout).strip()[-300:]}')
    return r.stdout


def part_path(disk, n):
    return f'{disk}p{n}' if re.search(r'\d$', disk) else f'{disk}{n}'


def settle():
    sh(['partprobe'], check=False)
    sh(['udevadm', 'settle'], check=False)
    time.sleep(1)


def uuid_of(dev):
    return sh(['blkid', '-s', 'UUID', '-o', 'value', dev]).strip()


# ------------------------------------------------------------------------------------------------ steps
def check(c):
    progress('check', 0, tr('Prüfe Einstellungen …', 'Checking settings …'))
    for k in ('disk', 'mode', 'user', 'password'):
        if not c.get(k):
            raise Fail(tr('Angabe fehlt: ', 'Missing value: ') + k)
    if not re.match(r'^[a-z_][a-z0-9_-]{0,31}$', c['user']):
        raise Fail(tr('Ungültiger Benutzername', 'Invalid username'))
    ds = {d['path']: d for d in D.scan()}
    d = ds.get(c['disk'])
    if not d:
        raise Fail(tr('Platte nicht gefunden: ', 'Disk not found: ') + c['disk'])
    if d['boot_medium']:
        raise Fail(tr('Das ist der Toravo-Stick selbst.', 'That is the Toravo USB stick itself.'))
    if d['too_small']:
        raise Fail(tr(f'Platte zu klein (mindestens {D.MIN_GB} GB).', f'Disk too small (at least {D.MIN_GB} GB).'))
    mode = c['mode']
    if mode == 'empty' and not d['empty']:
        raise Fail(tr('Platte ist nicht leer – nichts wird gelöscht. Bitte neu wählen.', 'Disk is not empty – nothing is erased. Please choose again.'))
    if mode == 'erase' and c.get('confirm') != d['name']:
        raise Fail(tr('Löschen nicht bestätigt (Plattenname muss eingegeben werden).', 'Erase not confirmed (the disk name must be typed).'))
    if mode == 'alongside' and not d['can_alongside']:
        raise Fail(tr('Nicht genug freier Platz neben dem vorhandenen System.', 'Not enough free space next to the existing system.'))
    if mode in ('erase', 'empty') and d['mounted']:
        raise Fail(tr('Auf der Platte ist etwas eingehängt – bitte erst aushängen.', 'Something on the disk is mounted – please unmount it first.'))
    if not os.path.isdir(SRC_SQUASH) and not os.path.exists('/run/archiso/bootmnt'):
        raise Fail(tr('Live-System nicht gefunden (nur vom Toravo-Stick aus installierbar).', 'Live system not found (can only be installed from the Toravo stick).'))
    c['_disk'] = d
    c['_uefi'] = os.path.isdir('/sys/firmware/efi')
    progress('check', 1)


def partition(c):
    disk, mode, uefi = c['disk'], c['mode'], c['_uefi']
    progress('partition', 0, tr('Partitioniere …', 'Partitioning …'))
    if mode in ('empty', 'erase'):
        sh(['swapoff', '-a'], check=False)
        sh(['wipefs', '-af', disk])
        sh(['sgdisk', '-Z', disk], check=False)
        if uefi:
            sh(['sgdisk', '-n1:0:+1G', '-t1:ef00', '-c1:TORAVO_EFI', '-n2:0:0', '-t2:8304', '-c2:TORAVO_ROOT', disk])
        else:
            sh(['sgdisk', '-n1:0:+1M', '-t1:ef02', '-c1:BIOS', '-n2:0:0', '-t2:8304', '-c2:TORAVO_ROOT', disk])
        settle()
        c['_esp'] = part_path(disk, 1) if uefi else None
        c['_esp_new'] = uefi
        c['_xboot'] = None
        c['_root'] = part_path(disk, 2)
    else:  # alongside: only unallocated space is used; existing partitions are never touched
        d = c['_disk']
        s, e = max(d['free'], key=lambda r: r[1] - r[0])
        sec = int(open(f'/sys/block/{d["name"]}/queue/logical_block_size').read())
        start = ((s + 2**20 - 1) // 2**20) * 2**20 // sec
        end = (e // sec) - 1
        used = [int(x) for x in re.findall(r'^\s*(\d+)\s', sh(['sgdisk', '-p', disk]), re.M)]
        n1 = max(used + [0]) + 1
        n2 = n1 + 1
        boot_sectors = 2**30 // sec
        if d['esp']:
            sh(['sgdisk', f'-n{n1}:{start}:{start + boot_sectors - 1}', f'-t{n1}:ea00', f'-c{n1}:TORAVO_BOOT',
                f'-n{n2}:{start + boot_sectors}:{end}', f'-t{n2}:8304', f'-c{n2}:TORAVO_ROOT', disk])
            c['_esp'], c['_esp_new'], c['_xboot'] = d['esp'], False, part_path(disk, n1)
        else:
            sh(['sgdisk', f'-n{n1}:{start}:{start + boot_sectors - 1}', f'-t{n1}:ef00', f'-c{n1}:TORAVO_EFI',
                f'-n{n2}:{start + boot_sectors}:{end}', f'-t{n2}:8304', f'-c{n2}:TORAVO_ROOT', disk])
            c['_esp'], c['_esp_new'], c['_xboot'] = part_path(disk, n1), True, None
        settle()
        c['_root'] = part_path(disk, n2)
    progress('partition', 1)


def fmt(c):
    progress('format', 0, tr('Formatiere …', 'Formatting …'))
    if c['_esp'] and c['_esp_new']:
        sh(['mkfs.fat', '-F32', '-n', 'TORAVO', c['_esp']])
    if c.get('_xboot'):
        sh(['mkfs.fat', '-F32', '-n', 'TORAVOBOOT', c['_xboot']])
    sh(['mkfs.btrfs', '-f', '-L', 'TORAVO_ROOT', c['_root']])
    os.makedirs(T, exist_ok=True)
    sh(['mount', c['_root'], T])
    for sv in ('@', '@home', '@snapshots', '@log', '@pkg'):
        sh(['btrfs', 'subvolume', 'create', f'{T}/{sv}'])
    sh(['umount', T])
    opts = 'noatime,compress=zstd:1,space_cache=v2'
    sh(['mount', '-o', f'subvol=@,{opts}', c['_root'], T])
    for sv, mp in (('@home', 'home'), ('@snapshots', '.snapshots'), ('@log', 'var/log'), ('@pkg', 'var/cache/pacman/pkg')):
        os.makedirs(f'{T}/{mp}', exist_ok=True)
        sh(['mount', '-o', f'subvol={sv},{opts}', c['_root'], f'{T}/{mp}'])
    if c['_uefi']:
        if c.get('_xboot'):
            os.makedirs(f'{T}/efi', exist_ok=True)
            os.makedirs(f'{T}/boot', exist_ok=True)
            sh(['mount', '-o', 'fmask=0077,dmask=0077', c['_esp'], f'{T}/efi'])
            sh(['mount', '-o', 'fmask=0077,dmask=0077', c['_xboot'], f'{T}/boot'])
        else:
            os.makedirs(f'{T}/boot', exist_ok=True)
            sh(['mount', '-o', 'fmask=0077,dmask=0077', c['_esp'], f'{T}/boot'])
    progress('format', 1)


def copy(c):
    progress('copy', 0, tr('Kopiere Toravo OS …', 'Copying Toravo OS …'))
    src = SRC_SQUASH if os.path.isdir(SRC_SQUASH + '/usr') else None
    if src:
        cmd = ['rsync', '-aHAX', '--numeric-ids', '--info=progress2', '--no-inc-recursive',
               '--exclude=/dev/*', '--exclude=/proc/*', '--exclude=/sys/*', '--exclude=/run/*', '--exclude=/tmp/*', '--exclude=/mnt/*',
               '--exclude=/boot/*', src + '/', T + '/']
        rx = re.compile(r'\s(\d{1,3})%\s')
    else:
        sfs = next((p for p in ('/run/archiso/bootmnt/arch/x86_64/airootfs.sfs', '/run/archiso/copytoram/airootfs.sfs') if os.path.exists(p)), None)
        if not sfs:
            raise Fail(tr('airootfs.sfs nicht gefunden', 'airootfs.sfs not found'))
        cmd = ['unsquashfs', '-f', '-percentage', '-d', T, sfs]
        rx = re.compile(r'^(\d{1,3})$')
    with open(LOG, 'a') as f:
        f.write('$ ' + ' '.join(cmd) + '\n')
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    buf, last = '', 0
    while True:
        ch = p.stdout.read(1)
        if not ch:
            break
        if ch in '\r\n':
            m = rx.search(buf)
            if m and time.time() - last > .3:
                last = time.time()
                progress('copy', int(m.group(1)) / 100, tr('Kopiere Toravo OS …', 'Copying Toravo OS …') + f' {m.group(1)} %')
            buf = ''
        else:
            buf += ch
    p.wait()
    if p.returncode not in (0, 24):  # 24 = vanished files
        raise Fail(tr(f'Kopieren fehlgeschlagen (Exit {p.returncode})', f'Copy failed (exit {p.returncode})'))
    for d in ('dev', 'proc', 'sys', 'run', 'tmp', 'mnt'):
        os.makedirs(f'{T}/{d}', exist_ok=True)
    os.chmod(f'{T}/tmp', 0o1777)
    kv = sorted(os.listdir(f'{T}/usr/lib/modules'))
    kern = next((f'{T}/usr/lib/modules/{k}/vmlinuz' for k in kv if os.path.exists(f'{T}/usr/lib/modules/{k}/vmlinuz')), None)
    if not kern:
        raise Fail(tr('Kernel nicht gefunden', 'Kernel not found'))
    shutil.copy2(kern, f'{T}/boot/vmlinuz-linux')
    progress('copy', 1)


def write(path, text, mode=0o644):
    os.makedirs(os.path.dirname(T + path), exist_ok=True)
    with open(T + path, 'w') as f:
        f.write(text)
    os.chmod(T + path, mode)


def system(c):
    progress('system', 0, tr('Richte das System ein …', 'Setting up the system …'))
    # live-only bits out
    lst = f'{T}/etc/toravo/live-only.txt'
    if os.path.exists(lst):
        for line in open(lst):
            pth = line.strip()
            if pth and not pth.startswith('#') and pth.startswith('/'):
                full = T + pth
                if os.path.islink(full) or os.path.isfile(full):
                    os.remove(full)
                elif os.path.isdir(full):
                    shutil.rmtree(full, ignore_errors=True)
        os.remove(lst)
    fst = sh(['genfstab', '-U', T])
    fst = re.sub(r',subvolid=\d+', '', fst)
    write('/etc/fstab', '# Toravo OS\n' + fst)
    progress('system', .1)
    host = c.get('hostname') or (c['user'] + '-toravo')
    write('/etc/hostname', host + '\n')
    write('/etc/hosts', f'127.0.0.1 localhost\n::1 localhost\n127.0.1.1 {host}.localdomain {host}\n')
    write('/etc/locale.conf', f'LANG={c.get("lang", "de_DE.UTF-8")}\n')
    write('/etc/vconsole.conf', f'KEYMAP={c.get("keymap", "de-latin1")}\n')
    write('/etc/toravo/xkb_layout', c.get('xkb_layout', 'de') + '\n')
    write('/etc/toravo/xkb_variant', c.get('xkb_variant', '') + '\n')
    write('/etc/X11/xorg.conf.d/00-keyboard.conf', 'Section "InputClass"\n  Identifier "system-keyboard"\n  MatchIsKeyboard "on"\n'
          f'  Option "XkbLayout" "{c.get("xkb_layout", "de")}"\n' + (f'  Option "XkbVariant" "{c["xkb_variant"]}"\n' if c.get('xkb_variant') else '') + 'EndSection\n')
    tz = c.get('timezone') or 'Europe/Berlin'
    if os.path.exists(f'{T}/usr/share/zoneinfo/{tz}'):
        if os.path.lexists(f'{T}/etc/localtime'):
            os.remove(f'{T}/etc/localtime')
        os.symlink(f'/usr/share/zoneinfo/{tz}', f'{T}/etc/localtime')
    sh(['hwclock', '--systohc'], check=False, chroot=True)
    progress('system', .2, tr('Lege deinen Benutzer an …', 'Creating your user …'))
    sh(['useradd', '-m', '-G', 'wheel,video,audio,input,render,storage', '-s', '/bin/bash', '-c', c.get('fullname', c['user']), c['user']], chroot=True)
    sh(['chpasswd'], input=f'{c["user"]}:{c["password"]}\n', chroot=True)
    sh(['passwd', '-l', 'root'], check=False, chroot=True)
    write('/etc/sudoers.d/10-toravo-wheel', '%wheel ALL=(ALL:ALL) ALL\n', 0o440)
    # login: greetd + ReGreet (optional auto-login)
    g = '[terminal]\nvt = 1\n\n[default_session]\ncommand = "/usr/bin/toravo-greeter"\nuser = "greeter"\n'
    if c.get('autologin'):
        g += f'\n[initial_session]\ncommand = "/usr/bin/toravo-session"\nuser = "{c["user"]}"\n'
    write('/etc/greetd/config.toml', g)
    progress('system', .35, tr('Schlüssel für Paket-Updates …', 'Keys for package updates …'))
    sh(['pacman-key', '--init'], chroot=True)
    sh(['pacman-key', '--populate', 'archlinux'], chroot=True)
    # Toravo Update (14.10.2026): signed [toravo] repo + channel "stable" pinned to the Arch date of this ISO
    snap = open('/etc/toravo/arch-snapshot').read().strip() if os.path.exists('/etc/toravo/arch-snapshot') else ''
    sh(['toravo-update', 'setup'] + (['--snapshot', snap] if re.match(r'^\d{4}/\d{2}/\d{2}$', snap) else []), check=False, chroot=True)
    progress('system', .6, tr('Snapshots, Swap, Dienste …', 'Snapshots, swap, services …'))
    snap_tpl = f'{T}/usr/share/snapper/config-templates/default'
    if os.path.exists(snap_tpl):
        conf = open(snap_tpl).read()
        conf = re.sub(r'^SUBVOLUME=.*$', 'SUBVOLUME="/"', conf, flags=re.M)
        conf = re.sub(r'^ALLOW_GROUPS=.*$', 'ALLOW_GROUPS="wheel"', conf, flags=re.M)
        conf = re.sub(r'^TIMELINE_CREATE=.*$', 'TIMELINE_CREATE="no"', conf, flags=re.M)
        conf = re.sub(r'^NUMBER_LIMIT=.*$', 'NUMBER_LIMIT="12"', conf, flags=re.M)
        conf = re.sub(r'^NUMBER_LIMIT_IMPORTANT=.*$', 'NUMBER_LIMIT_IMPORTANT="6"', conf, flags=re.M)
        write('/etc/snapper/configs/root', conf, 0o640)
        write('/etc/conf.d/snapper', 'SNAPPER_CONFIGS="root"\n')
        os.chmod(f'{T}/.snapshots', 0o750)
    write('/etc/systemd/zram-generator.conf', '[zram0]\nzram-size = min(ram / 2, 8192)\ncompression-algorithm = zstd\n')
    for unit in ('greetd.service', 'NetworkManager.service', 'systemd-timesyncd.service', 'fstrim.timer', 'snapper-cleanup.timer',
                 'bluetooth.service', 'reflector.timer'):
        sh(['systemctl', 'enable', unit], check=False, chroot=True)
    sh(['systemctl', 'set-default', 'graphical.target'], check=False, chroot=True)
    hwj = c.get('hardware')
    if hwj:
        write('/etc/toravo/hardware.json', json.dumps(hwj, indent=2))
    progress('system', 1)


def drivers(c):
    progress('drivers', 0, tr('Grafiktreiber …', 'Graphics driver …'))
    hwj = c.get('hardware') or {}
    nv = hwj.get('profile') == 'nvidia'
    if nv and os.path.isdir(OFFLINE_REPO):
        pk = [os.path.join(OFFLINE_REPO, f) for f in os.listdir(OFFLINE_REPO) if f.endswith('.pkg.tar.zst')]
        if pk:
            os.makedirs(f'{T}/tmp/toravo-nv', exist_ok=True)
            for f in pk:
                shutil.copy2(f, f'{T}/tmp/toravo-nv/')
            sh(['bash', '-c', 'pacman -U --noconfirm --needed /tmp/toravo-nv/*.pkg.tar.zst'], chroot=True)
            shutil.rmtree(f'{T}/tmp/toravo-nv', ignore_errors=True)
            write('/etc/mkinitcpio.conf.d/10-toravo-nvidia.conf', 'MODULES=(nvidia nvidia_modeset nvidia_uvm nvidia_drm)\n')
            write('/etc/modprobe.d/toravo-nvidia.conf', 'options nvidia_drm modeset=1 fbdev=1\noptions nvidia NVreg_PreserveVideoMemoryAllocations=1\n')
            for u in ('nvidia-suspend.service', 'nvidia-hibernate.service', 'nvidia-resume.service'):
                sh(['systemctl', 'enable', u], check=False, chroot=True)
            c['_nvidia'] = True
    progress('drivers', .4, tr('Startbild (initramfs) …', 'Boot image (initramfs) …'))
    hooks = 'base udev plymouth autodetect microcode modconf ' + ('' if c.get('_nvidia') else 'kms ') + \
        'keyboard keymap consolefont block filesystems fsck'
    write('/etc/mkinitcpio.conf.d/20-toravo.conf', f'HOOKS=({hooks})\nCOMPRESSION="zstd"\n')
    write('/etc/mkinitcpio.d/linux.preset', '# Toravo OS\nALL_kver="/boot/vmlinuz-linux"\nPRESETS=(\'default\' \'fallback\')\n'
          'default_image="/boot/initramfs-linux.img"\nfallback_image="/boot/initramfs-linux-fallback.img"\nfallback_options="-S autodetect"\n')
    sh(['plymouth-set-default-theme', 'toravo'], check=False, chroot=True)
    sh(['mkinitcpio', '-P'], chroot=True)
    progress('drivers', 1)


def boot(c):
    progress('boot', 0, 'Bootloader …')
    root_uuid = uuid_of(c['_root'])
    opts = f'root=UUID={root_uuid} rootflags=subvol=@ rw quiet splash loglevel=3 rd.udev.log_level=3 vt.global_cursor_default=0 panic=10'
    if c.get('_nvidia'):
        opts += ' nvidia_drm.modeset=1'
    if c['_uefi']:
        if c.get('_xboot'):
            sh(['bootctl', 'install', '--esp-path=/efi', '--boot-path=/boot'], chroot=True)
        else:
            sh(['bootctl', 'install', '--esp-path=/boot'], chroot=True)
        write('/boot/loader/entries/toravo.conf', f'title   Toravo OS\nsort-key toravo-1\nlinux   /vmlinuz-linux\ninitrd  /initramfs-linux.img\noptions {opts}\n')
        write('/boot/loader/entries/toravo-fallback.conf', f'title   Toravo OS ({tr("Notfall", "fallback")})\nsort-key toravo-3\nlinux   /vmlinuz-linux\ninitrd  /initramfs-linux-fallback.img\n'
              f'options root=UUID={root_uuid} rootflags=subvol=@ rw\n')
        loader = '/efi/loader/loader.conf' if c.get('_xboot') else '/boot/loader/loader.conf'
        write(loader, 'default toravo.conf\ntimeout 3\nconsole-mode max\neditor no\n')
        sh(['systemctl', 'enable', 'systemd-boot-update.service'], check=False, chroot=True)
    else:
        dflt = open(f'{T}/etc/default/grub').read() if os.path.exists(f'{T}/etc/default/grub') else ''
        dflt = re.sub(r'^GRUB_CMDLINE_LINUX_DEFAULT=.*$', f'GRUB_CMDLINE_LINUX_DEFAULT="quiet splash loglevel=3 panic=10{" nvidia_drm.modeset=1" if c.get("_nvidia") else ""}"', dflt, flags=re.M)
        dflt = re.sub(r'^GRUB_DISTRIBUTOR=.*$', 'GRUB_DISTRIBUTOR="Toravo OS"', dflt, flags=re.M)
        dflt = re.sub(r'^GRUB_TIMEOUT=.*$', 'GRUB_TIMEOUT=3', dflt, flags=re.M)
        write('/etc/default/grub', dflt)
        sh(['grub-install', '--target=i386-pc', c['disk']], chroot=True)
        sh(['grub-mkconfig', '-o', '/boot/grub/grub.cfg'], chroot=True)
    progress('boot', 1)


def finish(c):
    progress('finish', 0, tr('Erster Snapshot …', 'First snapshot …'))
    sh(['snapper', '--no-dbus', '-c', 'root', 'create', '-d', tr('Toravo OS installiert', 'Toravo OS installed')], check=False, chroot=True)
    sh(['cp', LOG, f'{T}/var/log/toravo-install.log'], check=False)
    sh(['sync'])
    sh(['umount', '-R', T], check=False)
    progress('finish', 1, tr('Fertig.', 'Done.'))


def cleanup():
    subprocess.run(['umount', '-R', T], capture_output=True)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args:
        print(__doc__)
        sys.exit(2)
    with open(args[0]) as f:
        c = json.load(f)
    os.environ['TORAVO_LANG'] = c.get('lang') or 'de_DE.UTF-8'  # messages in the language chosen in the installer
    if '--keep-config' not in sys.argv:
        try:
            os.remove(args[0])  # contains the password
        except OSError:
            pass
    open(LOG, 'w').close()
    os.chmod(LOG, 0o600)
    emit(ev='start', disk=c.get('disk'), mode=c.get('mode'))
    try:
        for fn in (check, partition, fmt, copy, system, drivers, boot, finish):
            emit(ev='step', step=fn.__name__)
            fn(c)
        emit(ev='done', ok=True)
    except Fail as e:
        emit(ev='error', msg=str(e))
        cleanup()
        emit(ev='done', ok=False, msg=str(e))
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        emit(ev='error', msg=f'{type(e).__name__}: {e}')
        cleanup()
        emit(ev='done', ok=False, msg=str(e))
        sys.exit(1)


if __name__ == '__main__':
    main()
