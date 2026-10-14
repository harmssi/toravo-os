#!/bin/bash
# Toravo OS – ISO auf einem Linux-Build-Host (x86_64, Docker, KVM für Tests) in einem privilegierten archlinux-Container bauen.
#   ./build.sh            Quellen synchronisieren + ISO bauen (Log: $BUILD_DIR/build.log)
#   ./build.sh --clean    Build-Container danach entfernen
# Ergebnis: <BUILD_HOST>:$W/out/toravo-os-<datum>-x86_64.iso
set -euo pipefail
HOST=${BUILD_HOST:?BUILD_HOST setzen, z. B. BUILD_HOST=root@buildhost ./build.sh}
W=${BUILD_DIR:-/srv/toravo-os-build}
C=toravo-os-build
cd "$(dirname "$0")"
ssh "$HOST" "mkdir -p $W/src $W/out $W/pkgcache"
rsync -a --delete --exclude screenshots --exclude .DS_Store --exclude '__pycache__' ./ "$HOST:$W/src/toravo-os/"
ssh "$HOST" "docker inspect $C >/dev/null 2>&1 || docker run -d --name $C --privileged --memory=6g --cpus=12 \
    -v $W:/build -v $W/pkgcache:/var/cache/pacman/pkg archlinux:latest sleep infinity; docker start $C >/dev/null"
ssh "$HOST" "docker exec $C bash -c 'pacman-key --init >/dev/null 2>&1; pacman-key --populate archlinux >/dev/null 2>&1; true'"
ssh "$HOST" "docker exec $C nice -n 10 bash /build/src/toravo-os/scripts/container-build.sh" 2>&1 | tee build.log.local
if [ "${1:-}" = "--clean" ]; then ssh "$HOST" "docker rm -f $C"; fi
