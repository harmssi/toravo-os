"""Waybar modules: toravo-bar gpu|queue|live|install  -> one JSON line {text, class, tooltip}."""
import glob, json, os, subprocess, sys
from .theme import tr


def out(text, cls='', tip=''):
    print(json.dumps({'text': text, 'class': cls, 'tooltip': tip}, ensure_ascii=False))


def rd(p):
    try:
        return open(p).read().strip()
    except OSError:
        return ''


def gpu():
    try:
        r = subprocess.run(['nvidia-smi', '--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,name',
                            '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=3)
        if r.returncode == 0 and r.stdout.strip():
            u, mu, mt, t, name = [x.strip() for x in r.stdout.splitlines()[0].split(',')]
            return out(f'GPU {u}% · {float(mu) / 1024:.1f}/{float(mt) / 1024:.0f} GB · {t}°', 'hot' if int(t) >= 82 else '', name)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    for dev in glob.glob('/sys/class/drm/card[0-9]/device'):
        busy = rd(dev + '/gpu_busy_percent')
        if busy:
            used, tot = rd(dev + '/mem_info_vram_used'), rd(dev + '/mem_info_vram_total')
            temp = next((rd(t) for t in glob.glob(dev + '/hwmon/hwmon*/temp1_input')), '')
            txt = f'GPU {busy}%'
            if used and tot:
                txt += f' · {int(used) / 2**30:.1f}/{int(tot) / 2**30:.0f} GB'
            if temp:
                txt += f' · {int(temp) // 1000}°'
            return out(txt, 'hot' if temp and int(temp) >= 85000 else '', 'AMD GPU')
    try:
        l1 = os.getloadavg()[0]
        return out(f'CPU {min(100, int(l1 / (os.cpu_count() or 1) * 100))}%', '', tr('keine GPU-Werte verfügbar', 'no GPU stats available'))
    except OSError:
        return out('GPU –')


def queue():
    qd = os.path.expanduser('~/.local/share/toravo/queue')
    jobs = []
    for f in glob.glob(qd + '/*.json'):
        try:
            jobs.append(json.load(open(f)))
        except (OSError, ValueError):
            pass
    act = [j for j in jobs if j.get('state') in ('queued', 'running')]
    run = [j for j in act if j.get('state') == 'running']
    if not act:
        return out('0 JOBS', 'idle', tr('Render-Queue leer', 'Render queue empty'))
    txt = f'▮ {len(act)} JOB{"S" if len(act) != 1 else ""}'
    if run:
        txt += f' · {int(run[0].get("progress", 0) * 100)}%'
    tip = '\n'.join(f'{"▶" if j["state"] == "running" else "·"} {j["title"]} – {j.get("step", "")}' for j in act[:8])
    out(txt, 'busy', tip)


def live():
    p = os.path.expanduser('~/.local/state/toravo/live.json')
    try:
        st = json.load(open(p))
        if os.path.exists(f'/proc/{int(st["pid"])}'):
            return out('● LIVE', 'live', tr('OBS streamt', 'OBS is streaming'))
        os.remove(p)
    except (OSError, ValueError, KeyError):
        pass
    out('')


def install():
    out(tr('Toravo OS installieren', 'Install Toravo OS') if os.path.isdir('/run/archiso') else '', 'install',
        tr('Toravo OS auf diesen Rechner installieren', 'Install Toravo OS on this computer'))


if __name__ == '__main__':
    {'gpu': gpu, 'queue': queue, 'live': live, 'install': install}.get(sys.argv[1] if len(sys.argv) > 1 else 'gpu', gpu)()
