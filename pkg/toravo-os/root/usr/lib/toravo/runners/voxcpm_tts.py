"""VoxCPM2 text-to-speech / voice clone (runs in ~/Toravo/AI/voxcpm/.venv). Untested on real GPU in Phase 1."""
import argparse, os
import soundfile as sf
from voxcpm import VoxCPM

ap = argparse.ArgumentParser()
ap.add_argument('--model', required=True)
ap.add_argument('--text', required=True)
ap.add_argument('--out', required=True)
ap.add_argument('--ref')
ap.add_argument('--ref-text')
a = ap.parse_args()
try:
    model = VoxCPM.from_pretrained(a.model)
except TypeError:
    model = VoxCPM(voxcpm_model_path=a.model)
kw = dict(text=a.text, cfg_value=2.0, inference_timesteps=10, normalize=True)
if a.ref:
    kw.update(prompt_wav_path=a.ref, prompt_text=a.ref_text or None)
print('VoxCPM: generiere …', flush=True)
wav = model.generate(**kw)
sr = getattr(getattr(model, 'tts_model', None), 'sample_rate', None) or 48000
sf.write(a.out, wav, sr)
print('fertig', a.out, flush=True)
