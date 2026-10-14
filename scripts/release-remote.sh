#!/bin/bash
# Toravo Update – runs ON the release/build machine as root (called by scripts/release.sh build):
# builds toravo-os <version> + toravo-keyring, signs packages, repo database and the channel manifests with the release key.
#   release-remote.sh <version> <notes-de> <notes-en>      -> $BUILD_ROOT/release/<version>/
# The private key lives only here (GNUPGHOME, default /root/.toravo-release-gnupg). BREAK=1 builds a deliberately broken
# package (desktop session exits at once) – only for the rollback test, never published.
set -euo pipefail
VER=${1:?version}; NDE=${2:-}; NEN=${3:-}
B=${BUILD_ROOT:-/srv/toravo-os-build}
SRC=$B/src/toravo-os
export GNUPGHOME=${GNUPGHOME:-/root/.toravo-release-gnupg}
FPR=$(gpg --list-secret-keys --with-colons | awk -F: '/^fpr/{print $10; exit}')
[ -n "$FPR" ] || { echo "kein Release-Schlüssel in $GNUPGHOME" >&2; exit 1; }
[[ "$VER" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "Version wie 0.1.2" >&2; exit 1; }
OUT=$B/release/$VER
log() { echo "[$(date +%H:%M:%S)] $*"; }
id builder >/dev/null 2>&1 || useradd -m builder
rm -rf "$OUT" && mkdir -p "$OUT"

log "Assets"
rm -rf $B/assets && python "$SRC/assets/gen_assets.py" $B/assets >/dev/null

log "toravo-os $VER bauen"
rm -rf $B/relbuild && cp -a "$SRC/pkg/toravo-os" $B/relbuild && cp -a $B/assets $B/relbuild/generated
[ -f "$SRC/docs/UPDATES.md" ] && cp "$SRC/docs/UPDATES.md" $B/relbuild/generated/
sed -i -e "s/^pkgver=.*/pkgver=$VER/" -e "s/^pkgrel=.*/pkgrel=1/" $B/relbuild/PKGBUILD
if [ "${BREAK:-0}" = 1 ]; then
    printf '#!/bin/bash\n# BROKEN TEST BUILD – rollback test only\nexit 1\n' > $B/relbuild/root/usr/bin/toravo-session
fi
chown -R builder $B/relbuild
(cd $B/relbuild && sudo -u builder makepkg -f --nodeps >$B/makepkg-release.log 2>&1) || { tail -30 $B/makepkg-release.log; exit 1; }
cp $B/relbuild/toravo-os-$VER-1-any.pkg.tar.zst "$OUT/"

log "toravo-keyring bauen"
rm -rf $B/keyringbuild && cp -a "$SRC/pkg/toravo-keyring" $B/keyringbuild && chown -R builder $B/keyringbuild
(cd $B/keyringbuild && sudo -u builder makepkg -f --nodeps >$B/makepkg-keyring.log 2>&1) || { tail -30 $B/makepkg-keyring.log; exit 1; }
cp $B/keyringbuild/toravo-keyring-*.pkg.tar.zst "$OUT/"

log "signieren + Repo-Datenbank"
cd "$OUT"
for p in *.pkg.tar.zst; do gpg --batch --yes --local-user "$FPR" --detach-sign "$p"; done
repo-add -q --sign --key "$FPR" toravo.db.tar.gz *.pkg.tar.zst
for f in db files; do
    rm -f toravo.$f toravo.$f.sig
    cp toravo.$f.tar.gz toravo.$f && cp toravo.$f.tar.gz.sig toravo.$f.sig
done
rm -f toravo.db.tar.gz.old* toravo.files.tar.gz.old*

log "Manifeste"
SNAP=$(date -u -d yesterday +%Y/%m/%d)   # candidate Arch Linux Archive date – becomes "stable" only after the test
for ch in rolling stable; do
    python3 - "$ch" "$VER" "$SNAP" "$NDE" "$NEN" > manifest-$ch.json <<'PY'
import json, sys, time
ch, ver, snap, de, en = sys.argv[1:6]
print(json.dumps({'channel': ch, 'version': ver, 'date': time.strftime('%Y-%m-%d'), 'arch_snapshot': snap,
                  'notes': {'de': de, 'en': en}}, indent=2, ensure_ascii=False))
PY
    gpg --batch --yes --local-user "$FPR" --detach-sign manifest-$ch.json
done
[ "${BREAK:-0}" = 1 ] && touch BROKEN-TEST-BUILD-DO-NOT-PUBLISH
ls -la "$OUT"
log "fertig: $OUT"
