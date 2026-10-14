"""faster-whisper -> SRT (runs in ~/Toravo/AI/whisper/.venv). args: <media> <out.srt> <model_dir> <cpu|cuda> [--words]"""
import subprocess, sys
import numpy as np
from faster_whisper import WhisperModel

src, out, mdir, device = sys.argv[1:5]
words = '--words' in sys.argv
model = WhisperModel(mdir, device=device, compute_type='float16' if device == 'cuda' else 'int8')
# decode with FFmpeg ourselves (independent of the PyAV version faster-whisper pulls in)
pcm = subprocess.run(['ffmpeg', '-hide_banner', '-v', 'error', '-i', src, '-ac', '1', '-ar', '16000', '-f', 's16le', '-'],
                     capture_output=True, check=True).stdout
audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
segments, info = model.transcribe(audio, vad_filter=True, word_timestamps=words, condition_on_previous_text=False, no_speech_threshold=0.5)
print(f'Sprache {info.language} · {info.duration:.0f}s', flush=True)


def ts(t):
    h, r = divmod(max(0.0, t), 3600)
    m, s = divmod(r, 60)
    return f'{int(h):02d}:{int(m):02d}:{int(s):02d},{int((s - int(s)) * 1000):03d}'


n = 0
with open(out, 'w', encoding='utf-8') as f:
    for seg in segments:
        if words and seg.words:
            chunk = []
            for w in seg.words:  # short caption chunks (3 words) for Shorts
                chunk.append(w)
                if len(chunk) == 3:
                    n += 1
                    f.write(f'{n}\n{ts(chunk[0].start)} --> {ts(chunk[-1].end)}\n{"".join(x.word for x in chunk).strip().upper()}\n\n')
                    chunk = []
            if chunk:
                n += 1
                f.write(f'{n}\n{ts(chunk[0].start)} --> {ts(chunk[-1].end)}\n{"".join(x.word for x in chunk).strip().upper()}\n\n')
        else:
            n += 1
            f.write(f'{n}\n{ts(seg.start)} --> {ts(seg.end)}\n{seg.text.strip()}\n\n')
        print(f'{seg.end:.0f}/{info.duration:.0f}s', flush=True)
print('fertig', out, flush=True)
