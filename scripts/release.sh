#!/bin/bash
# Toravo Update – release pipeline (docs/UPDATES.md). Build + signing happen on the release machine (BUILD_HOST, the private
# key never leaves it); publishing uses the GitHub CLI on this machine (gh, logged in).
#
#   scripts/release.sh key-init                                   once: create the release key on BUILD_HOST, print the public key
#   scripts/release.sh build <version> "<notes de>" "<notes en>"  package + sign + repo db + signed manifests (rolling/stable)
#   scripts/release.sh publish rolling <version>                  GitHub release "repo-rolling" (brave users, candidate)
#   scripts/release.sh test <version>                             throwaway Proxmox VM: install the newest ISO, update to <version>
#                                                                  with the candidate Arch date, reboot, smoke test (scripts/release-test.sh)
#   scripts/release.sh promote <version>                          only after a passed test: GitHub release "repo-stable"
#
# Variables: BUILD_HOST (ssh target, root), BUILD_DIR (/srv/toravo-os-build), GH_REPO (harmssi/toravo-os),
#            for test: PVE_HOST, DEV_ADDR (see scripts/pve-testvm.sh).
set -euo pipefail
cd "$(dirname "$0")/.."
HOST=${BUILD_HOST:?BUILD_HOST setzen}
W=${BUILD_DIR:-/srv/toravo-os-build}
GH_REPO=${GH_REPO:-harmssi/toravo-os}
MARK=.release-tested
cmd=${1:-}; shift || true

sync_src() {
    ssh "$HOST" "mkdir -p $W/src"
    rsync -a --delete --exclude screenshots --exclude content --exclude .DS_Store --exclude '__pycache__' --exclude '*.iso' \
        ./ "$HOST:$W/src/toravo-os/"
}

publish() {  # <channel> <version>
    local ch=$1 ver=$2 tmp
    [ -z "$(ssh "$HOST" "ls $W/release/$ver/BROKEN-TEST-BUILD-DO-NOT-PUBLISH 2>/dev/null")" ] || { echo "Test-Build – wird nie veröffentlicht" >&2; exit 1; }
    tmp=$(mktemp -d)
    scp -q "$HOST:$W/release/$ver/*" "$tmp/"
    cp "$tmp/manifest-$ch.json" "$tmp/manifest.json"
    cp "$tmp/manifest-$ch.json.sig" "$tmp/manifest.json.sig"
    if ! gh release view "repo-$ch" -R "$GH_REPO" >/dev/null 2>&1; then
        gh release create "repo-$ch" -R "$GH_REPO" --target main --prerelease --latest=false \
            --title "Toravo OS package repository ($ch)" \
            --notes "Signed pacman repository and update manifest for Toravo Update, channel \`$ch\`. Not meant for manual download – see docs/UPDATES.md."
    fi
    gh release upload "repo-$ch" -R "$GH_REPO" --clobber \
        "$tmp"/toravo-os-$ver-1-any.pkg.tar.zst "$tmp"/toravo-os-$ver-1-any.pkg.tar.zst.sig \
        "$tmp"/toravo-keyring-*.pkg.tar.zst "$tmp"/toravo-keyring-*.pkg.tar.zst.sig \
        "$tmp"/toravo.db "$tmp"/toravo.db.sig "$tmp"/toravo.files "$tmp"/toravo.files.sig \
        "$tmp"/manifest.json "$tmp"/manifest.json.sig
    # keep the current and the previous toravo-os package as assets, delete older ones
    gh release view "repo-$ch" -R "$GH_REPO" --json assets -q '.assets[].name' | grep -E '^toravo-os-[0-9.]+-[0-9]+-any\.pkg\.tar\.zst$' \
        | sort -V | awk '{a[NR]=$0} END {for (i = 1; i <= NR - 2; i++) print a[i]}' | while read -r old; do
            gh release delete-asset "repo-$ch" -R "$GH_REPO" "$old" -y; gh release delete-asset "repo-$ch" -R "$GH_REPO" "$old.sig" -y || true
        done
    rm -rf "$tmp"
    echo "veröffentlicht: repo-$ch → $ver"
}

case "$cmd" in
  key-init)
    ssh "$HOST" 'G=/root/.toravo-release-gnupg; [ -d $G ] || { install -d -m 700 $G; GNUPGHOME=$G gpg --batch --passphrase "" --quick-generate-key "Toravo OS Release Signing Key" ed25519 sign 3y; }
                 GNUPGHOME=$G gpg --armor --export'
    echo "→ öffentlichen Schlüssel nach pkg/toravo-keyring/toravo.asc, Fingerprint nach toravo-trusted (FPR:4:)" >&2
    ;;
  build)
    ver=${1:?version}; sync_src
    ssh "$HOST" "BUILD_ROOT=$W BREAK=${BREAK:-0} nice -n 10 bash $W/src/toravo-os/scripts/release-remote.sh $(printf '%q ' "$ver" "${2:-}" "${3:-}")"
    ;;
  publish)
    ch=${1:?rolling|stable}; ver=${2:?version}
    [ "$ch" = rolling ] || { echo "stable nur über: release.sh promote <version>" >&2; exit 1; }
    publish rolling "$ver"
    ;;
  test)
    ver=${1:?version}
    scripts/release-test.sh "$ver" && echo "$ver" >> "$MARK"
    ;;
  promote)
    ver=${1:?version}
    grep -qx "$ver" "$MARK" 2>/dev/null || { echo "$ver ist nicht getestet (scripts/release.sh test $ver)" >&2; exit 1; }
    publish stable "$ver"
    ;;
  *) sed -n 2,16p "$0"; exit 1 ;;
esac
