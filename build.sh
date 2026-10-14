#!/bin/bash
# Toravo OS – ISO auf einem Linux-Build-Host bauen. Zwei Modi:
#   BUILD_MODE=docker (Standard): x86_64-Host mit Docker, Build in einem privilegierten archlinux-Container
#   BUILD_MODE=native           : Arch-basierte Build-Maschine (z. B. eine Toravo-OS-/Arch-VM), mkarchiso direkt als root;
#                                 der pacman-Paket-Cache der Maschine bleibt erhalten
#   ./build.sh            Quellen synchronisieren + ISO bauen (Log: build.log.local)
#   ./build.sh --clean    Docker: Build-Container danach entfernen · native: Arbeitsordner work/ leeren
# Ergebnis: <BUILD_HOST>:$BUILD_DIR/out/toravo-os-<datum>-x86_64.iso
set -euo pipefail
HOST=${BUILD_HOST:?BUILD_HOST setzen, z. B. BUILD_HOST=root@buildhost ./build.sh}
W=${BUILD_DIR:-/srv/toravo-os-build}
MODE=${BUILD_MODE:-docker}
C=toravo-os-build
cd "$(dirname "$0")"
ssh "$HOST" "mkdir -p $W/src $W/out $W/pkgcache"
rsync -a --delete --exclude screenshots --exclude content --exclude .DS_Store --exclude '__pycache__' --exclude '*.iso' \
    ./ "$HOST:$W/src/toravo-os/"
case "$MODE" in
  docker)
    ssh "$HOST" "docker inspect $C >/dev/null 2>&1 || docker run -d --name $C --privileged --memory=6g --cpus=12 \
        -v $W:/build -v $W/pkgcache:/var/cache/pacman/pkg archlinux:latest sleep infinity; docker start $C >/dev/null"
    ssh "$HOST" "docker exec $C bash -c 'pacman-key --init >/dev/null 2>&1; pacman-key --populate archlinux >/dev/null 2>&1; true'"
    ssh "$HOST" "docker exec $C nice -n 10 bash /build/src/toravo-os/scripts/container-build.sh" 2>&1 | tee build.log.local
    if [ "${1:-}" = "--clean" ]; then ssh "$HOST" "docker rm -f $C"; fi
    ;;
  native)
    ssh "$HOST" "test -f /etc/arch-release" || { echo "BUILD_MODE=native braucht ein Arch-basiertes System" >&2; exit 1; }
    ssh "$HOST" "BUILD_ROOT=$W nice -n 10 bash $W/src/toravo-os/scripts/container-build.sh" 2>&1 | tee build.log.local
    if [ "${1:-}" = "--clean" ]; then ssh "$HOST" "rm -rf $W/work"; fi
    ;;
  *) echo "BUILD_MODE: docker oder native" >&2; exit 1 ;;
esac
