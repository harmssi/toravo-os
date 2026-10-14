#!/bin/bash
# re-run MV + shorts + thumbnail on the existing test song and export preview frames to /tmp
rm -rf ~/Toravo/Videos/* ~/Toravo/Shorts/* ~/Toravo/Thumbnails/*
toravo-queue clear-done
toravo-agent run "turn skyborne into a music video + 2 shorts + thumbnail" >/dev/null
for i in $(seq 1 120); do toravo-queue list | grep -q -E ' (queued|running) ' || break; sleep 5; done
toravo-queue list
ffmpeg -v error -y -ss 6 -i ~/Toravo/Shorts/skyborne-short-1.mp4 -frames:v 1 /tmp/short.png
ffmpeg -v error -y -ss 20 -i ~/Toravo/Videos/skyborne.mp4 -frames:v 1 /tmp/mv.png
cp ~/Toravo/Thumbnails/skyborne-A.png /tmp/thumbA.png; cp ~/Toravo/Thumbnails/skyborne-B.png /tmp/thumbB.png; chmod 644 /tmp/*.png
