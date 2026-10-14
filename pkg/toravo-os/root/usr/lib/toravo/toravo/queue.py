"""Toravo render queue: local jobs run one after another on the GPU (systemd user service toravo-queue).

Jobs are JSON files in ~/.local/share/toravo/queue/<id>.json – readable by the Studio, the Waybar module and scripts.
States: queued -> running -> done | failed | needs_tool | cancelled. Dependencies via "after" (job ids).
CLI: toravo-queue list [--json] | add <kind> <title> [params-json] | cancel <id> | retry <id> | clear-done | run
"""
import json, os, signal, subprocess, sys, threading, time, traceback, uuid
from .theme import tr

QDIR = os.path.expanduser('~/.local/share/toravo/queue')
ACTIVE = ('queued', 'running')


def _path(jid):
    return os.path.join(QDIR, jid + '.json')


def save(job):
    os.makedirs(QDIR, exist_ok=True)
    tmp = _path(job['id']) + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(job, f, indent=2, ensure_ascii=False)
    os.replace(tmp, _path(job['id']))


def load(jid):
    with open(_path(jid)) as f:
        return json.load(f)


def jobs():
    out = []
    try:
        names = os.listdir(QDIR)
    except OSError:
        return out
    for n in names:
        if n.endswith('.json'):
            try:
                with open(os.path.join(QDIR, n)) as f:
                    out.append(json.load(f))
            except (OSError, ValueError):
                pass
    return sorted(out, key=lambda j: j.get('created', 0))


def add(kind, title, params=None, after=(), subject='', plan_id=None):
    j = {'id': uuid.uuid4().hex[:12], 'kind': kind, 'title': title, 'params': params or {}, 'after': list(after), 'subject': subject,
         'plan_id': plan_id, 'state': 'queued', 'progress': 0.0, 'step': tr('wartet', 'waiting'), 'created': time.time(), 'outputs': [], 'error': ''}
    save(j)
    return j


def enqueue_plan(plan):
    """Plan from the Command Bar / agent -> jobs with dependencies. Returns the job ids."""
    pid = uuid.uuid4().hex[:8]
    ids = []
    for s in plan['steps']:
        if s['kind'] == 'stream':
            from . import executors
            executors.start_stream()
            ids.append(None)
            continue
        if s['kind'] == 'studio':
            subprocess.Popen(['toravo-studio'])
            ids.append(None)
            continue
        after = [ids[a] for a in s.get('after', []) if a < len(ids) and ids[a]]
        j = add(s['kind'], s['title'], s.get('params', {}), after, plan.get('subject', ''), pid)
        ids.append(j['id'])
    return [i for i in ids if i]


def update(job, **kw):
    job.update(kw)
    save(job)


class Progress:
    def __init__(self, job):
        self.job = job
        self.last = 0

    def __call__(self, p=None, step=None):
        now = time.time()
        if p is not None:
            self.job['progress'] = max(0.0, min(1.0, float(p)))
        if step:
            self.job['step'] = step
        if now - self.last > .5 or p == 1.0:
            self.last = now
            try:
                cur = load(self.job['id'])
                if cur.get('state') == 'cancelled':
                    raise Cancelled()
            except (OSError, ValueError):
                pass
            save(self.job)


class Cancelled(Exception):
    pass


def ready(job, alljobs):
    by = {j['id']: j for j in alljobs}
    for a in job.get('after', []):
        d = by.get(a)
        if d is None:
            continue
        if d['state'] in ('failed', 'cancelled', 'needs_tool'):
            return 'blocked'
        if d['state'] != 'done':
            return False
    return True


def run_forever():
    from . import executors
    os.makedirs(QDIR, exist_ok=True)
    for j in jobs():  # crashed while running -> queue again
        if j['state'] == 'running':
            update(j, state='queued', step=tr('neu eingereiht nach Neustart', 're-queued after restart'))
    while True:
        alljobs = jobs()
        nxt = None
        for j in alljobs:
            if j['state'] != 'queued':
                continue
            r = ready(j, alljobs)
            if r == 'blocked':
                update(j, state='failed', error=tr('Vorheriger Schritt fehlgeschlagen', 'Previous step failed'), step=tr('übersprungen', 'skipped'))
                continue
            if r:
                nxt = j
                break
        if not nxt:
            time.sleep(2)
            continue
        inhibit = None
        try:
            inhibit = subprocess.Popen(['systemd-inhibit', '--what=sleep:idle', '--who=Toravo', '--why=' + tr('Render-Job läuft', 'Render job running'), 'sleep', 'infinity'],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass
        update(nxt, state='running', started=time.time(), step=tr('startet', 'starting'))
        try:
            deps = [load(a) for a in nxt.get('after', []) if os.path.exists(_path(a))]
            res = executors.run(nxt, deps, Progress(nxt))
            st = res.get('state', 'done')
            update(nxt, state=st, progress=1.0 if st == 'done' else nxt.get('progress', 0), outputs=res.get('outputs', []),
                   step=res.get('step', tr('fertig', 'done') if st == 'done' else nxt.get('step')), error=res.get('error', ''), finished=time.time())
            notify(nxt)
        except Cancelled:
            update(nxt, state='cancelled', step=tr('abgebrochen', 'cancelled'), finished=time.time())
        except Exception as e:  # noqa: BLE001
            update(nxt, state='failed', error=f'{type(e).__name__}: {e}', step=tr('Fehler', 'error'), finished=time.time(),
                   trace=traceback.format_exc()[-2000:])
            notify(nxt)
        finally:
            if inhibit:
                inhibit.terminate()


def notify(job):
    if job['state'] == 'done':
        title, body = tr('Fertig: ', 'Done: ') + job['title'], ', '.join(os.path.basename(o) for o in job.get('outputs', [])[:3])
    elif job['state'] == 'needs_tool':
        title, body = tr('Werkzeug fehlt: ', 'Tool missing: ') + job['title'], job.get('error', '')
    else:
        title, body = tr('Fehler: ', 'Error: ') + job['title'], job.get('error', '')[:200]
    try:
        subprocess.Popen(['notify-send', '-a', 'Toravo', title, body], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def main():
    a = sys.argv[1:]
    cmd = a[0] if a else 'list'
    if cmd == 'run':
        run_forever()
    elif cmd == 'list':
        js = jobs()
        if '--json' in a:
            print(json.dumps(js, indent=2, ensure_ascii=False))
        else:
            for j in js:
                print(f"{j['id']}  {j['state']:<10} {j['progress'] * 100:5.1f}%  {j['kind']:<10} {j['title']}  · {j.get('step', '')}")
    elif cmd == 'add':
        j = add(a[1], a[2] if len(a) > 2 else a[1], json.loads(a[3]) if len(a) > 3 else {})
        print(j['id'])
    elif cmd == 'cancel':
        j = load(a[1])
        update(j, state='cancelled', step=tr('abgebrochen', 'cancelled'))
    elif cmd == 'retry':
        j = load(a[1])
        update(j, state='queued', step=tr('erneut eingereiht', 're-queued'), error='', progress=0.0)
    elif cmd == 'clear-done':
        for j in jobs():
            if j['state'] in ('done', 'cancelled'):
                os.remove(_path(j['id']))
    else:
        print(__doc__)


if __name__ == '__main__':
    main()
