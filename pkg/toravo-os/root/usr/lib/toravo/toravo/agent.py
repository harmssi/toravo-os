"""Command-Bar agent: free text -> plan of steps -> jobs in the local render queue.

Providers (in this order, configurable in ~/.config/toravo/agent.json):
  "ollama"    local LLM (default; installed by Toravo Setup: qwen3 4B/8B, 1.7B on CPU) – no cloud
  "anthropic" OPTIONAL, only if the user chose it and stored an own API key file (never shipped, never ours)
  "rules"     built-in keyword planner (always works, also offline / without any model)

Interface (stable, also for Phase-2 integrations):
  toravo-agent plan "turn skyborne into a music video + 3 shorts + thumbnail"   -> JSON plan on stdout
  toravo-agent run  "<text>"                                                    -> plan + enqueue, prints job ids
  Python: agent.plan(text) -> {"title", "subject", "provider", "steps": [{"kind", "title", "params", "after": [idx]}]}
Step kinds: song, voice, video, shorts, thumbnail, stems, master, transcribe, stream, studio.
"""
import json, os, re, subprocess, sys, urllib.request
from . import stack

KINDS = ['song', 'voice', 'video', 'shorts', 'thumbnail', 'stems', 'master', 'transcribe', 'stream', 'studio']
CONF = os.path.expanduser('~/.config/toravo/agent.json')
SCHEMA = {
    'type': 'object', 'additionalProperties': False, 'required': ['title', 'subject', 'steps'],
    'properties': {
        'title': {'type': 'string'}, 'subject': {'type': 'string'},
        'steps': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False, 'required': ['kind', 'title', 'params', 'after'],
            'properties': {
                'kind': {'type': 'string', 'enum': KINDS}, 'title': {'type': 'string'},
                'params': {'type': 'object', 'additionalProperties': False, 'required': ['prompt', 'count', 'style', 'lyrics'],
                           'properties': {'prompt': {'type': 'string'}, 'count': {'type': 'integer'}, 'style': {'type': 'string'},
                                          'lyrics': {'type': 'string'}}},
                'after': {'type': 'array', 'items': {'type': 'integer'}}}}}}}
SYSTEM = (
    'You are the planner of Toravo OS, a local AI content creation OS. Turn the user request into a short ordered list of '
    'steps for local tools. Allowed step kinds: song (make a song with YuE2: style + lyrics), voice (speech / voice clone), '
    'video (music video from a song), shorts (vertical 9:16 cuts with captions, params.count = number), thumbnail (A/B '
    'thumbnails), stems (split stems), master (mastering), transcribe (subtitles), stream (start OBS stream), studio (open the app). '
    '"after" lists indices of earlier steps this step needs. subject = the song/project name in lowercase. Reuse an existing '
    'song if the user refers to one by name (then no song step). Keep titles short, in the language of the user. Only JSON.')


def load_conf():
    try:
        with open(CONF) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def existing_songs():
    d = os.path.expanduser('~/Toravo/Songs')
    try:
        return sorted({os.path.splitext(n)[0].lower() for n in os.listdir(d) if not n.startswith('.')})
    except OSError:
        return []


# ------------------------------------------------------------------------------------------------ rules
NUM = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'ein': 1, 'eins': 1, 'zwei': 2, 'drei': 3, 'vier': 4, 'fünf': 5}


def rules(text):
    t = text.lower()
    steps = []
    m = re.search(r'(?:turn|make|mach(?:e)?(?:\s+aus)?|aus)\s+["\'„“]?([\w\- ]+?)["\'“”]?\s+(?:into|zu|in|ein|einen|eine)\b', t)
    subject = (m.group(1).strip() if m else '') or next((s for s in existing_songs() if s and s in t), '') or 'projekt'
    have_song = subject in existing_songs()

    def add(kind, title, after=(), **params):
        p = {'prompt': text, 'count': 1, 'style': '', 'lyrics': ''}
        p.update(params)
        steps.append({'kind': kind, 'title': title, 'params': p, 'after': list(after)})
        return len(steps) - 1

    wants_video = re.search(r'music ?video|musikvideo|\bmv\b|video', t)
    song_i = None
    if re.search(r'\bsong\b|\blied\b|track', t) or (wants_video and not have_song):
        if not have_song:
            song_i = add('song', f'Song „{subject}“ erzeugen', style=subject)
    if re.search(r'voice|stimme|clone|klon|sprech', t):
        add('voice', 'Stimme klonen / sprechen')
    vid_i = None
    if wants_video:
        vid_i = add('video', 'Musikvideo rendern', [song_i] if song_i is not None else [])
    m = re.search(r'(\d+|' + '|'.join(NUM) + r')\s*(?:x\s*)?(?:vertical\s+)?shorts?', t)
    if m or 'short' in t:
        n = int(m.group(1)) if m and m.group(1).isdigit() else NUM.get(m.group(1), 3) if m else 3
        add('shorts', f'{n} Shorts schneiden (9:16 + Untertitel)', [vid_i] if vid_i is not None else [], count=n)
    if 'thumb' in t or 'vorschaubild' in t:
        add('thumbnail', 'Thumbnail A/B', [vid_i] if vid_i is not None else [], count=2)
    if 'stem' in t or 'spur' in t:
        add('stems', 'Stems trennen', [song_i] if song_i is not None else [])
    if 'master' in t:
        add('master', 'Mastern', [song_i] if song_i is not None else [])
    if re.search(r'untertitel|subtitle|transkri|transcri', t):
        add('transcribe', 'Untertitel erzeugen')
    if re.search(r'stream|live', t):
        add('stream', 'Stream starten (OBS)')
    if not steps:
        add('studio', 'Im Studio öffnen')
    return {'title': text.strip()[:80], 'subject': subject, 'steps': steps}


# ------------------------------------------------------------------------------------------------ LLMs
def ollama(text, model=None):
    model = model or llm_model()
    if not model:
        return None
    ctx = 'Existing songs: ' + (', '.join(existing_songs()[:40]) or 'none')
    body = {'model': model, 'stream': False, 'format': SCHEMA, 'options': {'temperature': 0.2},
            'messages': [{'role': 'system', 'content': SYSTEM + '\n' + ctx}, {'role': 'user', 'content': text}]}
    if 'qwen3' in model:
        body['think'] = False
    req = urllib.request.Request('http://127.0.0.1:11434/api/chat', data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=90) as r:
        out = json.load(r)
    return json.loads(out['message']['content'])


def llm_model():
    st = stack.load_state()
    t = st.get('tools', {}).get('llm')
    if not t or not stack.tool_ready('llm', st):
        return None
    s = stack.load_stack()
    v = next(v for v in next(x for x in s['tools'] if x['id'] == 'llm')['variants'] if v['id'] == t['variant'])
    return s['models'][v['models'][0]]['ollama']


def anthropic(text, conf):
    """Optional, user-chosen: runs the official Anthropic SDK in its own venv with the USER's key file."""
    py = os.path.expanduser(conf.get('python', '~/Toravo/AI/agent-anthropic/.venv/bin/python'))
    keyfile = os.path.expanduser(conf.get('api_key_file', ''))
    if not (os.path.exists(py) and keyfile and os.path.exists(keyfile)):
        return None
    payload = json.dumps({'system': SYSTEM, 'text': text, 'schema': SCHEMA, 'model': conf.get('model', 'claude-opus-5-5'),
                          'key_file': keyfile, 'songs': existing_songs()[:40]})
    p = subprocess.run([py, '/usr/lib/toravo/runners/claude_plan.py'], input=payload, capture_output=True, text=True, timeout=180)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip()[-300:])
    return json.loads(p.stdout)


def clean(plan):
    steps = []
    for i, s in enumerate(plan.get('steps', [])[:12]):
        if s.get('kind') not in KINDS:
            continue
        p = s.get('params') or {}
        steps.append({'kind': s['kind'], 'title': str(s.get('title') or s['kind'])[:80],
                      'params': {'prompt': str(p.get('prompt', '')), 'count': max(1, min(10, int(p.get('count') or 1))),
                                 'style': str(p.get('style', '')), 'lyrics': str(p.get('lyrics', ''))},
                      'after': [a for a in s.get('after', []) if isinstance(a, int) and 0 <= a < i]})
    return {'title': str(plan.get('title', ''))[:80], 'subject': str(plan.get('subject', 'projekt'))[:40] or 'projekt', 'steps': steps}


def merge_shorts(p, r):
    """14.10.2026 (VM test): the local LLM often plans "short 1", "short 2", "short 3" as three steps with count 1 – each job
    then cut the same strongest moment into the same file (<subject>-short-1.mp4), so 3 Shorts became 1. Merge them into one
    shorts step; its count comes from the rule planner (the number the user typed) or the sum of the merged steps."""
    idx = [i for i, s in enumerate(p['steps']) if s['kind'] == 'shorts']
    if len(idx) < 2:
        return p
    want = next((s['params']['count'] for s in r.get('steps', []) if s['kind'] == 'shorts'), None)
    keep = idx[0]
    p['steps'][keep]['params']['count'] = max(1, min(10, int(want or sum(p['steps'][i]['params']['count'] for i in idx))))
    p['steps'][keep]['title'] = f'{p["steps"][keep]["params"]["count"]} Shorts schneiden (9:16 + Untertitel)'
    drop = set(idx[1:])
    new_index, n = {}, 0
    for i in range(len(p['steps'])):
        if i in drop:
            new_index[i] = None
        else:
            new_index[i] = n; n += 1
    steps = []
    for i, s in enumerate(p['steps']):
        if i in drop:
            continue
        after = []
        for a in s['after']:
            a2 = new_index.get(keep if a in drop else a)
            if a2 is not None and a2 not in after and a2 < new_index[i]:
                after.append(a2)
        steps.append({**s, 'after': after})
    p['steps'] = steps
    return p


def harmonize(p, text):
    """LLM plans from small local models get the subject / song dependency wrong now and then – fix with the rule planner."""
    r = rules(text)
    if r['subject'] and r['subject'] != 'projekt':
        p['subject'] = r['subject']
    merge_shorts(p, r)
    kinds = [s['kind'] for s in p['steps']]
    if 'video' in kinds and 'song' not in kinds and p['subject'] not in existing_songs():
        p['steps'].insert(0, {'kind': 'song', 'title': f'Song „{p["subject"]}“ erzeugen',
                              'params': {'prompt': text, 'count': 1, 'style': p['subject'], 'lyrics': ''}, 'after': []})
        for s in p['steps'][1:]:
            s['after'] = [a + 1 for a in s['after']]
            if s['kind'] == 'video' and 0 not in s['after']:
                s['after'].insert(0, 0)
    return p


def plan(text, provider=None):
    conf = load_conf()
    order = [provider] if provider else [conf.get('provider', 'ollama'), 'rules']
    errors = []
    for prov in order:
        try:
            if prov == 'ollama':
                res = ollama(text, conf.get('model'))
            elif prov == 'anthropic':
                res = anthropic(text, conf)
            else:
                res = rules(text)
            if res:
                out = clean(res)
                if prov != 'rules' and out['steps']:
                    out = harmonize(out, text)
                if out['steps']:
                    out['provider'] = prov
                    if errors:
                        out['notes'] = errors
                    return out
        except Exception as e:  # noqa: BLE001 – planner must never crash the command bar
            errors.append(f'{prov}: {e}')
    out = clean(rules(text))
    out['provider'] = 'rules'
    out['notes'] = errors
    return out


TOOL_OF = {'song': 'song', 'voice': 'voice', 'video': 'video', 'shorts': 'shorts', 'thumbnail': 'thumbnail', 'stems': 'stems',
           'master': 'master', 'transcribe': 'whisper'}


def readiness(p):
    """Annotate steps with whether the local tool is installed (Lite variants count)."""
    st = stack.load_state()
    for s in p['steps']:
        tool = TOOL_OF.get(s['kind'])
        if s['kind'] in ('shorts', 'stream', 'studio'):
            s['ready'] = True
        elif tool in ('video', 'thumbnail'):
            s['ready'] = True  # Lite variants (FFmpeg / templates) always work
            var = st.get('tools', {}).get(tool, {}).get('variant')
            s['engine'] = 'ki' if stack.tool_ready(tool, st) and var not in ('slideshow', 'templates') else 'lite'
        else:
            s['ready'] = stack.tool_ready(tool, st)
    return p


def main():
    a = sys.argv[1:]
    if len(a) < 2 or a[0] not in ('plan', 'run'):
        print(__doc__)
        sys.exit(2)
    p = readiness(plan(' '.join(a[1:])))
    if a[0] == 'run':
        from . import queue
        p['jobs'] = queue.enqueue_plan(p)
    print(json.dumps(p, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
