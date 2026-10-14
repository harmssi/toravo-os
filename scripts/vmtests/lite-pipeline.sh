#!/bin/bash
# VM functional test of the Lite pipeline (runs as the desktop user): Piper voice -> test song -> agent plan
# "turn skyborne into a music video + 2 shorts + thumbnail" -> queue -> outputs. Prints a short report.
set -u
cd ~
q() { toravo-queue "$@"; }
wait_idle() { for i in $(seq 1 120); do n=$(toravo-queue list | grep -c -E " (queued|running) "); [ "$n" = 0 ] && return 0; sleep 5; done; return 1; }
echo "== voice (Piper)"
q add voice "Sprachtest" '{"text": "Skyborne. Wir fliegen hoch über den Wolken. Skyborne, rise on the wind. Das ist Toravo OS, dein Studio für Songs, Videos und Shorts."}' >/dev/null
wait_idle
VO=$(ls -t ~/Toravo/Voice/*.wav 2>/dev/null | head -1); echo "voice: $VO $(ffprobe -v error -show_entries format=duration -of csv=p=0 "$VO" 2>/dev/null)"
echo "== test song (voice x6 over a synth bed, 60 s)"
ffmpeg -hide_banner -v error -y -f lavfi -i "sine=frequency=110:duration=60" -f lavfi -i "sine=frequency=165:duration=60" \
  -stream_loop 6 -i "$VO" -filter_complex "[0][1]amix=2,volume=0.25[bed];[2]atrim=0:60,volume=1.6[v];[bed][v]amix=2:duration=first,volume=2[a]" \
  -map "[a]" -ar 44100 ~/Toravo/Songs/skyborne.flac
echo "song: $(ffprobe -v error -show_entries format=duration -of csv=p=0 ~/Toravo/Songs/skyborne.flac)"
echo "== agent plan + run"
toravo-agent run "turn skyborne into a music video + 2 shorts + thumbnail" | python3 -c "import json,sys; p=json.load(sys.stdin); print(p['provider'], [s['title'] for s in p['steps']], p.get('jobs'))"
wait_idle || echo "TIMEOUT"
toravo-queue list
echo "== outputs"
ls -la ~/Toravo/Videos/*.mp4 ~/Toravo/Shorts/*.mp4 ~/Toravo/Thumbnails/*.png 2>/dev/null
for f in ~/Toravo/Videos/*.mp4 ~/Toravo/Shorts/*.mp4; do echo "$f: $(ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,width,height -show_entries format=duration -of csv=p=0 "$f" | tr '\n' ' ')"; done
ls ~/Toravo/Shorts/.work/*/ 2>/dev/null | head; cat ~/Toravo/Shorts/.work/*/seg0.srt 2>/dev/null | head -12
