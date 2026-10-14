#!/bin/bash
# Runs INSIDE the archlinux build container (privileged). Builds assets -> toravo-os package -> local repo -> ISO.
set -euo pipefail
SRC=/build/src/toravo-os
log() { echo "[$(date +%H:%M:%S)] $*"; }
log "Pakete für den Build"
pacman -Syu --noconfirm --needed archiso base-devel python-pillow inter-font ttf-jetbrains-mono git >/dev/null
id builder >/dev/null 2>&1 || useradd -m builder

log "Assets erzeugen"
rm -rf /build/assets && python "$SRC/assets/gen_assets.py" /build/assets

log "Paket toravo-os bauen"
rm -rf /build/pkgbuild && cp -a "$SRC/pkg/toravo-os" /build/pkgbuild && cp -a /build/assets /build/pkgbuild/generated
chown -R builder /build/pkgbuild
(cd /build/pkgbuild && sudo -u builder makepkg -f --nodeps >/build/makepkg.log 2>&1) || { tail -30 /build/makepkg.log; exit 1; }
mkdir -p /build/repo && rm -f /build/repo/toravo*
cp /build/pkgbuild/toravo-os-*.pkg.tar.zst /build/repo/
repo-add -q /build/repo/toravo.db.tar.gz /build/repo/toravo-os-*.pkg.tar.zst

log "Profil vorbereiten"
rm -rf /build/profile && cp -a "$SRC/archiso" /build/profile
cp /build/assets/syslinux/splash.png /build/profile/syslinux/splash.png
OFF=/build/profile/airootfs/opt/toravo/offline-repo
mkdir -p "$OFF" /build/offline-cache
# NVIDIA packages for offline install (installed only by the installer, only when an NVIDIA GPU is detected)
pacman -Swdd --noconfirm --cachedir /build/offline-cache nvidia-open nvidia-utils nvidia-settings egl-wayland egl-gbm egl-x11 \
    libxnvctrl libva-nvidia-driver opencl-nvidia >/dev/null
for p in nvidia-open nvidia-utils nvidia-settings egl-wayland egl-gbm egl-x11 libxnvctrl libva-nvidia-driver opencl-nvidia; do
    f=$(ls -t /build/offline-cache/$p-[0-9]*.pkg.tar.zst 2>/dev/null | head -1); [ -n "$f" ] && cp "$f" "$OFF/"
done
ls "$OFF"

log "ISO bauen (mkarchiso)"
rm -rf /build/work
mkdir -p /build/out
mkarchiso -v -r -w /build/work -o /build/out /build/profile > /build/mkarchiso.log 2>&1 || { tail -40 /build/mkarchiso.log; exit 1; }
rm -rf /build/work
ls -la /build/out
log "fertig"
