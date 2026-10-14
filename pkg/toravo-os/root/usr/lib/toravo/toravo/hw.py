"""Hardware detection -> Toravo hardware profile (nvidia | amd | intel | cpu) + VRAM tier (low <8 GB | mid 8-16 GB | high >=16 GB).

Used by the installer (drivers), toravo-session (Lite mode) and Toravo Setup (which AI models fit).
CLI: toravo-hw [--json]
"""
import glob, json, os, re, shutil, subprocess, sys
from .theme import tr

VENDORS = {'0x10de': 'nvidia', '0x1002': 'amd', '0x8086': 'intel', '0x1af4': 'virtio', '0x1234': 'qemu', '0x15ad': 'vmware',
           '0x80ee': 'virtualbox', '0x1a03': 'aspeed', '0x102b': 'matrox', '0x1414': 'hyperv'}
NO3D_DRIVERS = {'simpledrm', 'simplefb', 'efifb', 'vesafb', 'bochs-drm', 'bochs', 'cirrus', 'cirrus-qemu', 'ast', 'mgag200', 'hyperv_drm', 'vboxvideo'}

# VRAM by model name, for cards whose driver is not loaded yet (e.g. NVIDIA under nouveau in the live system)
VRAM_TABLE = [
    (r'RTX 5090', 32), (r'RTX 5080', 16), (r'RTX 5070 Ti', 16), (r'RTX 5070', 12), (r'RTX 5060 Ti', 16), (r'RTX 5060', 8),
    (r'RTX 4090', 24), (r'RTX 4080', 16), (r'RTX 4070 Ti SUPER', 16), (r'RTX 4070', 12), (r'RTX 4060 Ti', 16), (r'RTX 4060', 8),
    (r'RTX 3090', 24), (r'RTX 3080 Ti', 12), (r'RTX 3080', 10), (r'RTX 3070', 8), (r'RTX 3060 Ti', 8), (r'RTX 3060', 12), (r'RTX 3050', 8),
    (r'RTX 2080 Ti', 11), (r'RTX 2080', 8), (r'RTX 2070', 8), (r'RTX 2060', 6), (r'GTX 16[56]0', 6), (r'TITAN RTX', 24),
    (r'RTX A6000|RTX 6000', 48), (r'RTX A5000|RTX 5000', 24), (r'RTX A4000|RTX 4000', 16),
    (r'RX 7900 XTX', 24), (r'RX 7900 XT', 20), (r'RX 7900 GRE', 16), (r'RX 7800', 16), (r'RX 7700', 12), (r'RX 7600 XT', 16), (r'RX 7600', 8),
    (r'RX 9070', 16), (r'RX 9060 XT', 16), (r'RX 6950|RX 6900|RX 6800', 16), (r'RX 6750|RX 6700', 12), (r'RX 6650|RX 6600', 8),
    (r'Arc.*B580', 12), (r'Arc.*B570', 10), (r'Arc.*A770', 16), (r'Arc.*A750|Arc.*A580', 8), (r'Arc.*A3', 6),
]


def _read(path, default=''):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def _run(cmd, timeout=6):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ''


def gpus():
    out, seen = [], set()
    for card in sorted(glob.glob('/sys/class/drm/card[0-9]*')):
        if '-' in os.path.basename(card):
            continue
        dev = os.path.realpath(card + '/device')
        if dev in seen:
            continue
        seen.add(dev)
        vendor = VENDORS.get(_read(dev + '/vendor'), _read(dev + '/vendor'))
        devid = _read(dev + '/device')
        driver = os.path.basename(os.path.realpath(dev + '/driver')) if os.path.exists(dev + '/driver') else ''
        slot = os.path.basename(dev)
        name = ''
        if shutil.which('lspci') and re.match(r'^[0-9a-f]{4}:', slot):
            line = _run(['lspci', '-mm', '-s', slot]).strip()
            parts = re.findall(r'"([^"]*)"', line)
            if len(parts) >= 3:
                name = parts[2]
                m = re.search(r'\[([^\]]+)\]', name)
                if m:
                    name = m.group(1)
        vram = 0.0
        tot = _read(dev + '/mem_info_vram_total')
        if tot.isdigit():
            vram = int(tot) / 2**30
        out.append({'card': os.path.basename(card), 'vendor': vendor, 'device_id': devid, 'driver': driver, 'name': name or devid,
                    'boot_vga': _read(dev + '/boot_vga') == '1', 'vram_gb': round(vram, 1),
                    'render_node': bool(glob.glob(dev + '/drm/renderD*'))})
    if not out:  # no DRM at all (very old / headless): CPU profile
        out.append({'card': '', 'vendor': 'none', 'device_id': '', 'driver': '', 'name': tr('keine GPU erkannt', 'no GPU detected'), 'boot_vga': True, 'vram_gb': 0,
                    'render_node': False})
    return out


def nvidia_smi():
    if not shutil.which('nvidia-smi'):
        return []
    res = []
    for line in _run(['nvidia-smi', '--query-gpu=name,memory.total,driver_version', '--format=csv,noheader,nounits']).splitlines():
        p = [x.strip() for x in line.split(',')]
        if len(p) >= 2 and p[1].replace('.', '').isdigit():
            res.append({'name': p[0], 'vram_gb': round(float(p[1]) / 1024, 1), 'driver_version': p[2] if len(p) > 2 else ''})
    return res


def table_vram(name):
    for pat, gb in VRAM_TABLE:
        if re.search(pat, name or '', re.I):
            return gb
    return 0


def nvidia_supported(name):
    """Current Arch nvidia-open needs Turing (RTX 20 / GTX 16) or newer. Older cards stay on nouveau (CPU profile)."""
    n = (name or '').upper()
    if re.search(r'RTX|GTX 16|TITAN RTX|QUADRO RTX|\bA\d{2,4}\b|\bH\d{3}\b|\bL\d{1,2}\b|T4\b|T\d{3,4}\b', n):
        return True
    if re.search(r'GTX (10|9|7|6)\d{2}|TITAN X|QUADRO [KMP]|GT \d{3,4}', n):
        return False
    return True  # unknown names: assume modern


def rocm_support(name):
    n = (name or '').upper()
    if re.search(r'RX 7[6-9]00|RX 9\d{3}|W7[89]00|RX 6[89][05]0|W6800|INSTINCT|MI\d{2,3}', n):
        return 'yes'
    if re.search(r'RX 6[67][05]0|RX 6600|RX 7600', n):
        return 'override'  # needs HSA_OVERRIDE_GFX_VERSION
    return 'no'


def accel_3d(primary):
    """Real 3D acceleration available? llvmpipe/softpipe or framebuffer-only drivers -> no."""
    if not primary.get('render_node') or primary.get('driver') in NO3D_DRIVERS:
        return False
    if shutil.which('eglinfo'):
        out = _run(['eglinfo', '-B'], timeout=8).lower()
        if out:
            dev = ' '.join(l for l in out.splitlines() if 'renderer' in l or 'device' in l)
            if 'llvmpipe' in dev or 'softpipe' in dev or 'swrast' in dev:
                # eglinfo lists every platform; accept if at least one renderer is a real GPU
                real = [l for l in out.splitlines() if 'renderer' in l and not re.search('llvmpipe|softpipe|swrast', l)]
                return bool(real)
            return True
    if primary.get('driver') == 'virtio_gpu':
        return False  # virgl unknown -> be safe
    return True


def detect():
    gl = gpus()
    smi = nvidia_smi()
    dedicated = [g for g in gl if g['vendor'] in ('nvidia', 'amd', 'intel')]
    nv = [g for g in gl if g['vendor'] == 'nvidia']
    amd = [g for g in gl if g['vendor'] == 'amd']
    intel = [g for g in gl if g['vendor'] == 'intel']
    profile, vram, chosen, notes = 'cpu', 0.0, None, []
    if nv:
        chosen = nv[0]
        name = smi[0]['name'] if smi else chosen['name']
        chosen['name'] = name
        vram = smi[0]['vram_gb'] if smi else (chosen['vram_gb'] or table_vram(name))
        if nvidia_supported(name):
            profile = 'nvidia'
        else:
            notes.append(tr('NVIDIA-Karte älter als Turing: aktueller Treiber unterstützt sie nicht – läuft mit nouveau im CPU-Profil.',
                             'NVIDIA card older than Turing: the current driver does not support it – runs on nouveau in the CPU profile.'))
    if profile == 'cpu' and amd:
        big = max(amd, key=lambda g: g['vram_gb'] or table_vram(g['name']))
        v = big['vram_gb'] or table_vram(big['name'])
        if v >= 4:
            profile, chosen, vram = 'amd', big, v
        else:
            chosen = big
            notes.append(tr('AMD-iGPU / wenig VRAM: Lite-KI (CPU-Modelle), Video-Encoding per VAAPI.', 'AMD iGPU / little VRAM: Lite AI (CPU models), video encoding via VAAPI.'))
    if profile == 'cpu' and intel:
        arc = [g for g in intel if re.search(r'Arc|DG2|Battlemage|B5\d0|A[357]\d0', g['name'], re.I)]
        if arc:
            profile, chosen = 'intel', arc[0]
            vram = table_vram(arc[0]['name']) or 8
        else:
            chosen = chosen or intel[0]
            notes.append(tr('Intel-iGPU: Lite-KI (CPU-Modelle), Video-Encoding per QSV/VAAPI.', 'Intel iGPU: Lite AI (CPU models), video encoding via QSV/VAAPI.'))
    chosen = chosen or (dedicated[0] if dedicated else gl[0])
    tier = 'high' if vram >= 16 else 'mid' if vram >= 8 else 'low'
    if profile == 'cpu':
        tier = 'low'
    primary = next((g for g in gl if g['boot_vga']), gl[0])
    a3d = accel_3d(primary)
    vendor_hw = chosen.get('vendor')
    encoders = {'nvidia': ['h264_nvenc', 'hevc_nvenc', 'av1_nvenc'], 'amd': ['h264_vaapi', 'hevc_vaapi', 'h264_amf'],
                'intel': ['h264_qsv', 'hevc_qsv', 'h264_vaapi']}.get(profile, [])
    if profile == 'cpu' and vendor_hw in ('amd', 'intel'):
        encoders = ['h264_vaapi', 'hevc_vaapi']
    encoders.append('libx264')
    try:
        mem_gb = round(os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES') / 2**30, 1)
    except (ValueError, OSError):
        mem_gb = 0
    return {
        'profile': profile, 'tier': tier, 'vram_gb': round(float(vram), 1), 'gpu': chosen.get('name'), 'gpus': gl,
        'nvidia_driver_loaded': bool(smi), 'rocm': rocm_support(chosen.get('name')) if profile == 'amd' else 'no',
        'accel3d': a3d, 'lite': not a3d, 'ram_gb': mem_gb, 'cpu_threads': os.cpu_count() or 1, 'encoders': encoders,
        'virt': _run(['systemd-detect-virt']).strip() or 'none', 'notes': notes,
    }


DRIVER_PACKAGES = {
    'nvidia': ['nvidia-open', 'nvidia-utils', 'nvidia-settings', 'egl-wayland', 'libva-nvidia-driver', 'opencl-nvidia'],
    'amd': [],      # mesa, vulkan-radeon, libva are part of the base system
    'intel': [],    # mesa, vulkan-intel, intel-media-driver, vpl-gpu-rt are part of the base system
    'cpu': [],
}


def main():
    info = detect()
    if '--json' in sys.argv:
        print(json.dumps(info, indent=2, ensure_ascii=False))
        return
    print(tr('Profil', 'Profile') + f": {info['profile']}  " + tr('Stufe', 'Tier') + f": {info['tier']}  VRAM: {info['vram_gb']} GB  GPU: {info['gpu']}")
    print(tr('3D-Beschleunigung', '3D acceleration') + f": {tr('ja', 'yes') if info['accel3d'] else tr('nein (Lite-Modus)', 'no (Lite mode)')}  RAM: {info['ram_gb']} GB  Encoder: {', '.join(info['encoders'])}")
    for n in info['notes']:
        print(tr('Hinweis:', 'Note:'), n)


if __name__ == '__main__':
    main()
