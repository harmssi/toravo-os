#!/bin/bash
# Builds assets -> toravo-os package -> local repo -> ISO. Runs as root either INSIDE the privileged archlinux build container
# (BUILD_MODE=docker, work dir /build) or natively on an Arch-based build machine (BUILD_MODE=native, BUILD_ROOT=<work dir>).
set -euo pipefail
B=${BUILD_ROOT:-/build}
SRC=$B/src/toravo-os
log() { echo "[$(date +%H:%M:%S)] $*"; }
log "Pakete für den Build"
pacman -Syu --noconfirm --needed archiso base-devel python-pillow inter-font ttf-jetbrains-mono git >/dev/null
id builder >/dev/null 2>&1 || useradd -m builder

log "Assets erzeugen"
rm -rf $B/assets && python "$SRC/assets/gen_assets.py" $B/assets

log "Paket toravo-os bauen"
rm -rf $B/pkgbuild && cp -a "$SRC/pkg/toravo-os" $B/pkgbuild && cp -a $B/assets $B/pkgbuild/generated
chown -R builder $B/pkgbuild
(cd $B/pkgbuild && sudo -u builder makepkg -f --nodeps >$B/makepkg.log 2>&1) || { tail -30 $B/makepkg.log; exit 1; }
mkdir -p $B/repo && rm -f $B/repo/toravo*
cp $B/pkgbuild/toravo-os-*.pkg.tar.zst $B/repo/
repo-add -q $B/repo/toravo.db.tar.gz $B/repo/toravo-os-*.pkg.tar.zst

log "Profil vorbereiten"
rm -rf $B/profile && cp -a "$SRC/archiso" $B/profile
cp $B/assets/syslinux/splash.png $B/profile/syslinux/splash.png
sed -i "s#file:///build/repo#file://$B/repo#" $B/profile/pacman.conf   # local [toravo] repo in this work dir
OFF=$B/profile/airootfs/opt/toravo/offline-repo
mkdir -p "$OFF" $B/offline-cache
# NVIDIA packages for offline install (installed only by the installer, only when an NVIDIA GPU is detected)
pacman -Swdd --noconfirm --cachedir $B/offline-cache nvidia-open nvidia-utils nvidia-settings egl-wayland egl-gbm egl-x11 \
    libxnvctrl libva-nvidia-driver opencl-nvidia >/dev/null
for p in nvidia-open nvidia-utils nvidia-settings egl-wayland egl-gbm egl-x11 libxnvctrl libva-nvidia-driver opencl-nvidia; do
    f=$(ls -t $B/offline-cache/$p-[0-9]*.pkg.tar.zst 2>/dev/null | head -1); [ -n "$f" ] && cp "$f" "$OFF/"
done
ls "$OFF"

log "ISO bauen (mkarchiso)"
rm -rf $B/work
mkdir -p $B/out
mkarchiso -v -r -w $B/work -o $B/out $B/profile > $B/mkarchiso.log 2>&1 || { tail -40 $B/mkarchiso.log; exit 1; }
rm -rf $B/work
ls -la $B/out
log "fertig"
