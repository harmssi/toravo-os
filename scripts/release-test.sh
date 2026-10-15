#!/bin/bash
# Toravo Update – release test in a throwaway Proxmox VM (scripts/pve-testvm.sh):
#   1. newest ISO from BUILD_HOST -> test VM -> unattended install (installer backend, auto-login user "tester")
#   2. channel stable, but manifest + repo of the candidate (repo-rolling, or REPO_BASE for a local test server)
#   3. toravo-update.service (the same unit the timer starts) downloads -> reboot -> offline install -> reboot -> health check
#   4. smoke test: version, greetd, desktop session, Command Bar (agent plan), Studio Local (/api/ping), screenshot
#   release-test.sh <version>            exit 0 = passed. FW=bios tests a BIOS/GRUB machine, TEST_VMID=<id> reuses an installed test VM (skips 1),
#                                        KEEP=1 keeps the VM, EXPECT=rollback expects an automatic rollback instead.
# Variables: PVE_HOST, DEV_ADDR, BUILD_HOST, BUILD_DIR, GH_REPO; without DHCP on the test bridge: TEST_IP (a.b.c.d/nn), TEST_GW,
#            TEST_DNS (default 1.1.1.1); SHOTS (folder for screenshots, default ./screenshots/release-test).
set -euo pipefail
cd "$(dirname "$0")/.."
VER=${1:?version}
T=scripts/pve-testvm.sh
W=${BUILD_DIR:-/srv/toravo-os-build}
GH_REPO=${GH_REPO:-harmssi/toravo-os}
BASE=${REPO_BASE:-https://github.com/$GH_REPO/releases/download/repo-rolling}
SHOTS=${SHOTS:-screenshots/release-test}; mkdir -p "$SHOTS"
EXPECT=${EXPECT:-update}
log() { echo "[$(date +%H:%M:%S)] $*"; }
x() { "$T" exec "$ID" "$@"; }

wait_agent() {  # [seconds]
    local end=$((SECONDS + ${1:-900}))
    until x true >/dev/null 2>&1; do [ $SECONDS -lt $end ] || { log "Gast antwortet nicht"; return 1; }; sleep 5; done
}

net() {
    [ -n "${TEST_IP:-}" ] || return 0
    x "d=\$(nmcli -t -f DEVICE,TYPE dev | awk -F: '\$2==\"ethernet\"{print \$1; exit}'); nmcli con delete toravo-test >/dev/null 2>&1;
       nmcli con add type ethernet ifname \$d con-name toravo-test ipv4.method manual ipv4.addresses $TEST_IP ipv4.gateway $TEST_GW \
       ipv4.dns ${TEST_DNS:-1.1.1.1} >/dev/null && nmcli con up toravo-test >/dev/null" 120
}

cleanup() {
    if [ "${KEEP:-0}" != 1 ] && [ -z "${TEST_VMID:-}" ] && [ -n "${ID:-}" ]; then
        "$T" destroy "$ID" || true
        [ -n "${ISO_NAME:-}" ] && ssh -o BatchMode=yes "$PVE_HOST" "rm -f /var/lib/vz/template/iso/$ISO_NAME" || true
    fi
}
trap cleanup EXIT

if [ -n "${TEST_VMID:-}" ]; then
    ID=$TEST_VMID
else
    ISO=$(ssh "$BUILD_HOST" "ls -t $W/out/*.iso | head -1")
    ISO_NAME=test-release-$(basename "$ISO")
    "$T" fetch-iso "$ISO" "$ISO_NAME" >/dev/null
    ID=$("$T" create "$ISO_NAME" "${FW:-uefi}" 40)
    log "Test-VM $ID bootet das ISO"
    wait_agent
    sleep 20
    PW=$(openssl rand -hex 12)
    log "installiere (unbeaufsichtigt)"
    x "cat > /tmp/cfg.json <<'EOF'
{\"disk\": \"/dev/vda\", \"mode\": \"empty\", \"fullname\": \"Tester\", \"user\": \"tester\", \"password\": \"$PW\", \"hostname\": \"tester-toravo\",
 \"autologin\": true, \"lang\": \"en_US.UTF-8\", \"keymap\": \"us\", \"xkb_layout\": \"us\", \"xkb_variant\": \"\", \"timezone\": \"Europe/Berlin\"}
EOF
/usr/lib/toravo/toravo-install-backend /tmp/cfg.json --json | tail -2" 1800
    "$T" boot-disk "$ID"; "$T" restart "$ID" >/dev/null
    log "startet das installierte System"
    wait_agent
    net
fi

before=$(x "toravo-update status --json" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("version"))')
log "installiert: $before → Ziel $VER"
x "python3 - <<'PY'
import json
p = '/etc/toravo/update.json'
c = json.load(open(p))
c.update({'channel': 'stable', 'auto': True, 'manifest_url': '$BASE/manifest.json', 'repo_url': '$BASE'})
json.dump(c, open(p, 'w'), indent=2)
PY
printf 'Server = %s\n' '$BASE' > /etc/pacman.d/toravo-repo"

log "Hintergrund-Prüfung (toravo-update.service)"
for i in 1 2 3 4 5 6; do
    x "systemctl start toravo-update.service" 1800 || true
    s=$(x "toravo-update status --json" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("status"), (d.get("available") or {}).get("version"), d.get("waiting_for") or "")')
    log "Status: $s"
    case "$s" in ready\ $VER*) break ;; waiting*) sleep 60 ;; *) [ $i -ge 2 ] && { log "kein Update $VER bereit"; exit 1; }; sleep 20 ;; esac
done
[[ "$s" == ready\ $VER* ]] || exit 1
"$T" shot "$ID" "$SHOTS/$VER-1-ready.png" >/dev/null || true

log "Neustart → Offline-Installation"
x "systemctl reboot" 20 >/dev/null 2>&1 || true
sleep 30
wait_agent 1800
end=$((SECONDS + 1800))
while :; do
    st=$(x "toravo-update status --json" 2>/dev/null | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("status"), d.get("version"))' 2>/dev/null || echo "? ?")
    case "$st" in idle\ *|rolled_back\ *) break ;; esac
    [ $SECONDS -lt $end ] || { log "hängt in: $st"; exit 1; }
    sleep 15
done
if [[ "$st" == rolled_back* ]]; then  # the rollback reboots once more – wait until the restored system is up
    sleep 60; wait_agent 1200; sleep 30
    st=$(x "toravo-update status --json" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("status"), d.get("version"))')
fi
log "Ergebnis: $st"
x "tail -5 /var/log/toravo-update.log" || true
sleep 20
"$T" shot "$ID" "$SHOTS/$VER-2-after.png" >/dev/null || true

if [ "$EXPECT" = rollback ]; then
    [[ "$st" == rolled_back\ $before ]] || { log "Rollback erwartet, bekommen: $st"; exit 1; }
else
    [[ "$st" == idle\ $VER ]] || { log "erwartet idle $VER"; exit 1; }
fi

log "Rauchtest"
x "systemctl is-active greetd >/dev/null && (pgrep -x Hyprland || pgrep -x labwc) >/dev/null" 60 || { log "kein Desktop"; exit 1; }
x "sudo -u tester PYTHONPATH=/usr/lib/toravo python3 -c 'import toravo.commandbar, toravo.updates_app' && \
   sudo -u tester toravo-agent plan 'turn skyborne into a music video + 3 shorts + thumbnail' | python3 -c 'import json,sys; assert len(json.load(sys.stdin)[\"steps\"]) >= 3'" 300 \
   || { log "Command Bar / Agent kaputt"; exit 1; }
x "sudo -u tester XDG_RUNTIME_DIR=/run/user/\$(id -u tester) systemctl --user start toravo-studio.service; sleep 3; curl -sf http://127.0.0.1:8890/api/ping" 120 \
   || { log "Studio Local antwortet nicht"; exit 1; }
# 15.10.2026: Toravo Companion – service starts, pairing code works over HTTPS, token reaches /status, service off again
x "command -v toravo-companion >/dev/null || exit 0; U=\$(id -u tester); E=\"XDG_RUNTIME_DIR=/run/user/\$U\";
   sudo -u tester env \$E systemctl --user start toravo-companion.service; sleep 3;
   C=\$(sudo -u tester env \$E toravo-companion pair --host 127.0.0.1 | sed -n 's/.*[?&]c=\([A-Z0-9]*\).*/\1/p' | head -1);
   T=\$(curl -sk -X POST https://127.0.0.1:8891/api/v1/pair -H 'Content-Type: application/json' -d '{\"code\":\"'\$C'\",\"device\":\"release-test\",\"model\":\"vm\"}' \
        | python3 -c 'import json,sys; print(json.load(sys.stdin)[\"token\"])');
   curl -skf https://127.0.0.1:8891/api/v1/status -H \"Authorization: Bearer \$T\" | python3 -c 'import json,sys; assert \"jobs\" in json.load(sys.stdin)';
   r=\$?; sudo -u tester env \$E toravo-companion off >/dev/null 2>&1; exit \$r" 180 || { log "Companion-Dienst kaputt"; exit 1; }
log "BESTANDEN: $VER ($EXPECT)"
