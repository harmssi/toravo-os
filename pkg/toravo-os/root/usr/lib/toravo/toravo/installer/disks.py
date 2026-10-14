"""Disk detection for the Toravo installer: which disks exist, what is on them, how much free space, what is safe."""
import json, os, re, subprocess

ESP_GUID = 'c12a7328-f81f-11d2-ba4b-00a0c93ec93b'
MS_BASIC = 'ebd0a0a2-b9e5-4433-87c0-68b6b72699c7'
MS_RESERVED = 'e3c9e316-0b5c-4db8-817d-f92df00215ae'
MIN_GB = 30          # minimum size for Toravo OS (system ~ 8 GB + room for projects; AI models want much more)
REC_GB = 120


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True).stdout


def boot_disks():
    """Disks that hold the running live medium (never offered as target)."""
    out = set()
    for mp in ('/run/archiso/bootmnt', '/run/archiso/img_dev'):
        src = run(['findmnt', '-no', 'SOURCE', mp]).strip()
        if src:
            pk = run(['lsblk', '-no', 'PKNAME', src]).strip().splitlines()
            out.add(pk[0] if pk and pk[0] else os.path.basename(src))
    for line in run(['lsblk', '-rno', 'NAME,LABEL,PKNAME']).splitlines():
        p = line.split(' ')
        if len(p) >= 2 and p[1].startswith('TORAVO_') and p[1] != 'TORAVO_ROOT':
            out.add(p[2] if len(p) > 2 and p[2] else p[0])
    return out


def free_regions(dev):
    """[(start_bytes, end_bytes)] of unallocated space (parted)."""
    res = []
    cmd = ['parted', '-m', '-s', dev, 'unit', 'B', 'print', 'free']
    if os.geteuid() != 0:
        cmd = ['sudo', '-n'] + cmd  # reading the partition table needs root (live user has passwordless sudo)
    for line in run(cmd).splitlines():
        f = line.rstrip(';').split(':')
        if len(f) >= 5 and f[4] == 'free':
            try:
                s, e = int(f[1].rstrip('B')), int(f[2].rstrip('B'))
            except ValueError:
                continue
            if e - s > 64 * 2**20:
                res.append((s, e))
    return res


def human(n):
    gb = n / 1e9
    return f'{gb / 1000:.1f} TB' if gb >= 1000 else f'{gb:.0f} GB'


def scan():
    data = json.loads(run(['lsblk', '-J', '-b', '-o', 'NAME,PATH,SIZE,TYPE,MODEL,TRAN,RM,RO,PTTYPE,FSTYPE,LABEL,PARTTYPE,PARTLABEL,MOUNTPOINTS']) or '{"blockdevices": []}')
    skip = boot_disks()
    uefi = os.path.isdir('/sys/firmware/efi')
    disks = []
    for d in data.get('blockdevices', []):
        if d.get('type') != 'disk' or d['name'].startswith(('zram', 'loop', 'sr', 'fd')) or d.get('ro'):
            continue
        parts = d.get('children') or []
        size = int(d['size'])
        info = {'name': d['name'], 'path': d['path'], 'size': size, 'size_h': human(size),
                'model': (d.get('model') or '').strip() or d['name'], 'tran': d.get('tran') or '', 'removable': bool(d.get('rm')),
                'pttype': d.get('pttype') or '', 'parts': len(parts), 'windows': False, 'linux': False, 'other': False,
                'esp': None, 'mounted': False, 'free': [], 'boot_medium': d['name'] in skip, 'signature': d.get('fstype') or ''}
        for p in parts:
            pt = (p.get('parttype') or '').lower()
            fs = (p.get('fstype') or '').lower()
            if pt == ESP_GUID:
                info['esp'] = p['path']
            elif fs == 'ntfs' or pt in (MS_BASIC, MS_RESERVED) or fs == 'bitlocker':
                info['windows'] = True
            elif fs in ('ext4', 'btrfs', 'xfs', 'f2fs', 'swap', 'crypto_luks'):
                info['linux'] = True
            elif fs:
                info['other'] = True
            if any(m for m in (p.get('mountpoints') or []) if m):
                info['mounted'] = True
        info['empty'] = not parts and not info['signature']
        info['free'] = free_regions(d['path']) if parts and info['pttype'] == 'gpt' else []
        biggest = max((e - s for s, e in info['free']), default=0)
        info['free_max'] = biggest
        info['free_h'] = human(biggest) if biggest else ''
        info['can_alongside'] = bool(uefi and info['pttype'] == 'gpt' and biggest >= MIN_GB * 1e9 and not info['boot_medium'])
        info['too_small'] = size < MIN_GB * 1e9
        if info['boot_medium']:
            content = 'Toravo-Installationsmedium'
        elif info['empty']:
            content = 'leer'
        else:
            found = [x for x, k in (('Windows', 'windows'), ('Linux', 'linux'), ('Daten', 'other')) if info[k]]
            content = (' + '.join(found) + ' gefunden') if found else f'{len(parts)} Partition(en)'
            if biggest >= 1e9:
                content += f' · {human(biggest)} frei'
        info['content'] = content
        disks.append(info)
    return disks


def recommend(disks):
    """Safest default: empty disk (largest) > alongside other system in free space > nothing (user must choose + confirm)."""
    ok = [d for d in disks if not d['boot_medium'] and not d['too_small']]
    empty = sorted([d for d in ok if d['empty']], key=lambda d: -d['size'])
    if empty:
        return empty[0]['name'], 'empty'
    along = sorted([d for d in ok if d['can_alongside']], key=lambda d: -d['free_max'])
    if along:
        return along[0]['name'], 'alongside'
    return None, None


if __name__ == '__main__':
    ds = scan()
    print(json.dumps({'disks': ds, 'recommend': recommend(ds), 'uefi': os.path.isdir('/sys/firmware/efi')}, indent=2))
