"""Matchering 2: master <target> like <reference> -> <out.wav> (runs in ~/Toravo/AI/matchering/.venv)."""
import sys
import matchering as mg

target, reference, out = sys.argv[1:4]
mg.log(print)
mg.process(target=target, reference=reference, results=[mg.pcm24(out)])
print('fertig', out, flush=True)
