#!/bin/bash
# Wegwerf-Test-VMs für Boot- und Installer-Tests auf einem Proxmox-VE-Host (per SSH, `qm`).
# Jede Test-VM: VMID im Bereich $TEST_MIN–$TEST_MAX, Name toravo-test-*, Tag toravo-test, Disk mit backup=0, nur die interne
# Bridge $TEST_BRIDGE, kein Autostart, niedrige cpuunits. `destroy` löscht NUR VMs, die alle drei Merkmale haben.
#
#   PVE_HOST=root@proxmox scripts/pve-testvm.sh fetch-iso <pfad-auf-build-vm> [name]   ISO holen (Standardname test-<datei>)
#   PVE_HOST=... scripts/pve-testvm.sh create <iso-name> [uefi|bios] [disk-GB]     Test-VM anlegen + starten → VMID
#   PVE_HOST=... scripts/pve-testvm.sh shot <vmid> <lokal.png>                       Screenshot (QMP screendump)
#   PVE_HOST=... scripts/pve-testvm.sh keys <vmid> <taste> [...]                     Tasten (qm sendkey, z. B. ret, tab, meta_l-spc)
#   PVE_HOST=... scripts/pve-testvm.sh exec <vmid> '<cmd>' [timeout]                  Befehl als root im Gast (qemu-guest-agent)
#   PVE_HOST=... scripts/pve-testvm.sh boot-disk <vmid> | restart <vmid>             nach der Installation von der Platte starten
#   PVE_HOST=... scripts/pve-testvm.sh list | destroy <vmid> | destroy-all
#
# Variablen: PVE_HOST (Pflicht), DEV_ADDR (Adresse der Build-VM aus Sicht des Proxmox, für fetch-iso), ISO_STORAGE (local),
# DISK_STORAGE (local), TEST_BRIDGE (vmbr1), TEST_MIN/TEST_MAX (9000/9099), TEST_MEM (4096), TEST_CORES (4), TEST_CPUUNITS (20).
set -euo pipefail
PVE=${PVE_HOST:?PVE_HOST setzen, z. B. PVE_HOST=root@proxmox}
ISO_STORAGE=${ISO_STORAGE:-local}
DISK_STORAGE=${DISK_STORAGE:-local}
BRIDGE=${TEST_BRIDGE:-vmbr1}
MIN=${TEST_MIN:-9000}; MAX=${TEST_MAX:-9099}
MEM=${TEST_MEM:-4096}; CORES=${TEST_CORES:-4}; UNITS=${TEST_CPUUNITS:-20}
p() { ssh -o BatchMode=yes "$PVE" "$@"; }

is_test() {  # <vmid> → 0, wenn Bereich + Name + Tag passen
    local id=$1 cfg
    [[ "$id" =~ ^[0-9]+$ ]] && [ "$id" -ge "$MIN" ] && [ "$id" -le "$MAX" ] || return 1
    cfg=$(p "qm config $id" 2>/dev/null) || return 1
    grep -q '^name: toravo-test-' <<<"$cfg" && grep -q '^tags:.*toravo-test' <<<"$cfg"
}

case "${1:-}" in
  fetch-iso)
    src=${2:?Pfad der ISO auf der Build-VM}; dev=${DEV_ADDR:?DEV_ADDR setzen}; name=${3:-test-$(basename "$src")}
    p "scp -q -o BatchMode=yes '$dev:$src' '/var/lib/vz/template/iso/$name' && cd /var/lib/vz/template/iso && sha256sum '$name'"
    ;;
  create)
    iso=${2:?ISO-Name im Storage $ISO_STORAGE}; fw=${3:-uefi}; disk=${4:-40}
    id=$(p "for i in \$(seq $MIN $MAX); do qm status \$i >/dev/null 2>&1 || pct status \$i >/dev/null 2>&1 || { echo \$i; break; }; done")
    [ -n "$id" ] || { echo "keine freie Test-VMID in $MIN–$MAX" >&2; exit 1; }
    bios=(--bios seabios); [ "$fw" = uefi ] && bios=(--bios ovmf --efidisk0 "$DISK_STORAGE:1,efitype=4m,pre-enrolled-keys=0")
    p "qm create $id --name toravo-test-$id --tags toravo-test --memory $MEM --cores $CORES --cpu host --cpuunits $UNITS \
        --machine q35 ${bios[*]} --scsihw virtio-scsi-single --virtio0 $DISK_STORAGE:$disk,format=qcow2,backup=0 \
        --net0 virtio,bridge=$BRIDGE --vga virtio --agent enabled=1 --onboot 0 --ostype l26 --tablet 1 \
        --ide2 $ISO_STORAGE:iso/$iso,media=cdrom --boot 'order=ide2;virtio0' >/dev/null && qm start $id" && echo "$id"
    ;;
  shot)
    id=${2:?vmid}; out=${3:?lokale PNG}; is_test "$id" || { echo "$id ist keine Test-VM" >&2; exit 1; }
    p "python3 - $id" <<'PY'
import json, socket, sys
vmid = sys.argv[1]
s = socket.socket(socket.AF_UNIX); s.connect(f'/var/run/qemu-server/{vmid}.qmp'); f = s.makefile('rw')
f.readline()
for cmd in ({'execute': 'qmp_capabilities'},
            {'execute': 'screendump', 'arguments': {'filename': f'/tmp/toravo-test-{vmid}.png', 'format': 'png'}}):
    f.write(json.dumps(cmd) + '\n'); f.flush()
    while True:
        r = json.loads(f.readline())
        if 'return' in r or 'error' in r: break
PY
    scp -q "$PVE:/tmp/toravo-test-$id.png" "$out" && p "rm -f /tmp/toravo-test-$id.png" && echo "$out"
    ;;
  keys)
    id=${2:?vmid}; shift 2; is_test "$id" || { echo "$id ist keine Test-VM" >&2; exit 1; }
    for k in "$@"; do p "qm sendkey $id $k"; sleep .2; done
    ;;
  exec)  # exec <vmid> '<shell command>' [timeout-s] – as root in the guest (qemu-guest-agent); prints stdout+stderr, exit code passes through
    id=${2:?vmid}; c=${3:?command}; to=${4:-600}; is_test "$id" || { echo "$id ist keine Test-VM" >&2; exit 1; }
    p "qm guest exec $id --timeout $to -- bash -c $(printf '%q' "$c") 2>&1" | python3 -c '
import json, sys
raw = sys.stdin.read()
try:
    r = json.loads(raw)
except ValueError:
    sys.stderr.write(raw); sys.exit(255)
sys.stdout.write(r.get("out-data", "")); sys.stderr.write(r.get("err-data", ""))
sys.exit(r.get("exitcode", 255) if r.get("exited") else 124)'
    ;;
  boot-disk)  # boot from the virtual disk from now on (after the installation)
    id=${2:?vmid}; is_test "$id" || { echo "$id ist keine Test-VM" >&2; exit 1; }
    p "qm set $id --boot order=virtio0 >/dev/null"
    ;;
  restart)  # hard stop + start (applies a changed boot order)
    id=${2:?vmid}; is_test "$id" || { echo "$id ist keine Test-VM" >&2; exit 1; }
    p "qm stop $id --skiplock 1 >/dev/null 2>&1; qm start $id"
    ;;
  list)
    p "qm list" | awk -v a="$MIN" -v b="$MAX" 'NR==1 || ($1>=a && $1<=b && $2 ~ /^toravo-test-/)'
    ;;
  destroy)
    id=${2:?vmid}; is_test "$id" || { echo "$id ist keine Test-VM – nichts gelöscht" >&2; exit 1; }
    p "qm stop $id --skiplock 1 >/dev/null 2>&1; qm destroy $id --purge 1 --destroy-unreferenced-disks 1" && echo "gelöscht: $id"
    ;;
  destroy-all)
    for id in $(p "qm list" | awk -v a="$MIN" -v b="$MAX" 'NR>1 && $1>=a && $1<=b && $2 ~ /^toravo-test-/ {print $1}'); do
        "$0" destroy "$id"
    done
    ;;
  *) sed -n '2,15p' "$0"; exit 1 ;;
esac
