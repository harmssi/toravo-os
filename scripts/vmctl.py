#!/usr/bin/env python3
"""QEMU test helper (runs inside the build container): start a headless VM, take screenshots, type keys, run commands via
the QEMU guest agent. Usage:
  vmctl.py start <iso|-> [--disk img] [--uefi] [--mem 4096] [--boot-disk]
  vmctl.py shot <out.png>          screenshot (QMP screendump)
  vmctl.py keys <key> [...]        e.g. meta_l-spc ret tab esc
  vmctl.py type "<text>"           types text (US keymap in QEMU -> mapped)
  vmctl.py exec "<shell cmd>"      runs as root in the guest (qemu-guest-agent), prints output
  vmctl.py user "<shell cmd>"      runs in the live/installed user's Wayland session
  vmctl.py stop
"""
import base64, json, os, socket, subprocess, sys, time

RUN = '/build/vm'
QMP, QGA, PIDF = f'{RUN}/qmp.sock', f'{RUN}/qga.sock', f'{RUN}/qemu.pid'


def qmp(cmd, args=None):
    s = socket.socket(socket.AF_UNIX)
    s.connect(QMP)
    f = s.makefile('rw')
    f.readline()
    f.write(json.dumps({'execute': 'qmp_capabilities'}) + '\n'); f.flush(); f.readline()
    f.write(json.dumps({'execute': cmd, **({'arguments': args} if args else {})}) + '\n'); f.flush()
    while True:
        r = json.loads(f.readline())
        if 'return' in r or 'error' in r:
            s.close()
            return r


def qga(cmd, args=None, timeout=60):
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(timeout)
    s.connect(QGA)
    f = s.makefile('rw')
    f.write(json.dumps({'execute': 'guest-sync', 'arguments': {'id': 4242}}) + '\n'); f.flush()
    while '4242' not in f.readline():
        pass
    f.write(json.dumps({'execute': cmd, **({'arguments': args} if args else {})}) + '\n'); f.flush()
    r = json.loads(f.readline())
    s.close()
    return r


def gexec(sh, timeout=600):
    r = qga('guest-exec', {'path': '/bin/bash', 'arg': ['-c', sh], 'capture-output': True})
    pid = r['return']['pid']
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = qga('guest-exec-status', {'pid': pid})['return']
        if st.get('exited'):
            out = base64.b64decode(st.get('out-data', '')).decode(errors='replace')
            err = base64.b64decode(st.get('err-data', '')).decode(errors='replace')
            return st.get('exitcode'), out + err
        time.sleep(1)
    return None, 'timeout'


def start(a):
    os.makedirs(RUN, exist_ok=True)
    iso = a[0]
    mem = a[a.index('--mem') + 1] if '--mem' in a else '4096'
    cmd = ['qemu-system-x86_64', '-enable-kvm', '-machine', 'q35', '-cpu', 'host', '-smp', '4', '-m', mem,
           '-device', 'virtio-vga', '-display', 'none', '-vnc', '127.0.0.1:5', '-qmp', f'unix:{QMP},server,nowait',
           '-chardev', f'socket,path={QGA},server=on,wait=off,id=qga0', '-device', 'virtio-serial',
           '-device', 'virtserialport,chardev=qga0,name=org.qemu.guest_agent.0',
           '-netdev', 'user,id=n0', '-device', 'virtio-net-pci,netdev=n0', '-device', 'qemu-xhci', '-device', 'usb-tablet',
           '-audiodev', 'none,id=snd0', '-pidfile', PIDF, '-daemonize', '-serial', f'file:{RUN}/serial.log']
    if '--uefi' in a:
        vars_ = f'{RUN}/OVMF_VARS.fd'
        if not os.path.exists(vars_) or '--fresh-vars' in a:
            subprocess.run(['cp', '/usr/share/edk2/x64/OVMF_VARS.4m.fd', vars_], check=True)
        cmd += ['-drive', 'if=pflash,format=raw,readonly=on,file=/usr/share/edk2/x64/OVMF_CODE.4m.fd', '-drive', f'if=pflash,format=raw,file={vars_}']
    if '--disk' in a:
        cmd += ['-drive', f'file={a[a.index("--disk") + 1]},if=virtio,format=qcow2']
    if iso != '-':
        cmd += ['-drive', f'file={iso},media=cdrom,if=none,id=cd0,readonly=on', '-device', 'ide-cd,drive=cd0,bootindex=' + ('9' if '--boot-disk' in a else '0')]
    subprocess.run(cmd, check=True)
    print('started', open(PIDF).read().strip())


def shot(out):
    ppm = out + '.ppm'
    r = qmp('screendump', {'filename': ppm})
    if 'error' in r:
        sys.exit(r['error'])
    from PIL import Image
    Image.open(ppm).save(out)
    os.remove(ppm)
    print(out)


KEYMAP = {' ': 'spc', '\n': 'ret', '.': 'dot', ',': 'comma', '-': 'minus', '/': 'slash', '+': ('shift', 'equal'), '"': ('shift', 'apostrophe'),
          ':': ('shift', 'semicolon'), '_': ('shift', 'minus'), '!': ('shift', '1'), '@': ('shift', '2')}


def keys(seq):
    for k in seq:
        parts = k.split('-')
        qmp('send-key', {'keys': [{'type': 'qcode', 'data': p} for p in parts]})
        time.sleep(.15)


def type_text(t, de=True):
    """Guest keyboard layout is German by default: swap y/z etc. for qcodes."""
    for ch in t:
        if ch.isalpha() and ch.isascii():
            c = ch.lower()
            if de and c in 'yz':
                c = 'z' if c == 'y' else 'y'
            seq = (['shift', c] if ch.isupper() else [c])
        elif ch.isdigit():
            seq = [ch]
        else:
            m = KEYMAP.get(ch)
            if m is None:
                continue
            seq = list(m) if isinstance(m, tuple) else [m]
            if de and ch == '-':
                seq = ['slash']
            if de and ch == '/':
                seq = ['shift', '7']
            if de and ch == '+':
                seq = ['bracket_right']
        qmp('send-key', {'keys': [{'type': 'qcode', 'data': p} for p in seq]})
        time.sleep(.06)


USER_ENV = ('U=$(loginctl list-sessions --no-legend | awk \'$3!="greeter" && $3!="root" {print $3; exit}\'); UID_=$(id -u $U); '
            'export XDG_RUNTIME_DIR=/run/user/$UID_; export WAYLAND_DISPLAY=$(ls $XDG_RUNTIME_DIR | grep -E "^wayland-[0-9]+$" | head -1); '
            'export HYPRLAND_INSTANCE_SIGNATURE=$(ls $XDG_RUNTIME_DIR/hypr 2>/dev/null | head -1); export DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus; ')


def main():
    a = sys.argv[1:]
    c = a[0]
    if c == 'start':
        start(a[1:])
    elif c == 'shot':
        shot(a[1])
    elif c == 'keys':
        keys(a[1:])
    elif c == 'type':
        type_text(a[1])
    elif c == 'exec':
        rc, out = gexec(a[1], int(a[2]) if len(a) > 2 else 600)
        print(out, end='')
        print(f'[exit {rc}]')
    elif c == 'user':
        sh = USER_ENV + f'sudo -E -u $U env XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR WAYLAND_DISPLAY=$WAYLAND_DISPLAY HYPRLAND_INSTANCE_SIGNATURE=$HYPRLAND_INSTANCE_SIGNATURE DBUS_SESSION_BUS_ADDRESS=$DBUS_SESSION_BUS_ADDRESS TORAVO_LITE=${{TORAVO_LITE:-1}} GSK_RENDERER=cairo PYTHONPATH=/usr/lib/toravo bash -c {json.dumps(a[1])}'
        rc, out = gexec(sh, int(a[2]) if len(a) > 2 else 120)
        print(out, end='')
        print(f'[exit {rc}]')
    elif c == 'click':  # click x y (screen pixels of a 1280x800 screenshot by default; --size WxH)
        W, H = (1280, 800)
        if '--size' in a:
            W, H = map(int, a[a.index('--size') + 1].split('x'))
        x, y = int(a[1]), int(a[2])
        ev = [{'type': 'abs', 'data': {'axis': 'x', 'value': int(x * 32767 / (W - 1))}}, {'type': 'abs', 'data': {'axis': 'y', 'value': int(y * 32767 / (H - 1))}}]
        qmp('input-send-event', {'events': ev})
        time.sleep(.15)
        qmp('input-send-event', {'events': [{'type': 'btn', 'data': {'down': True, 'button': 'left'}}]})
        time.sleep(.08)
        qmp('input-send-event', {'events': [{'type': 'btn', 'data': {'down': False, 'button': 'left'}}]})
    elif c == 'push':  # push <local> <remote> (root-owned, mode 0755)
        data = open(a[1], 'rb').read()
        h = qga('guest-file-open', {'path': a[2], 'mode': 'wb'})['return']
        qga('guest-file-write', {'handle': h, 'buf-b64': base64.b64encode(data).decode()})
        qga('guest-file-close', {'handle': h})
        gexec(f'chmod 755 {a[2]}')
        print('pushed', a[2])
    elif c == 'pull':  # pull <remote> <local>
        h = qga('guest-file-open', {'path': a[1], 'mode': 'rb'})['return']
        out = b''
        while True:
            r = qga('guest-file-read', {'handle': h, 'count': 1 << 20})['return']
            out += base64.b64decode(r.get('buf-b64', ''))
            if r.get('eof') or not r.get('count'):
                break
        qga('guest-file-close', {'handle': h})
        open(a[2], 'wb').write(out)
        print('pulled', a[2], len(out))
    elif c == 'ping':
        print(qga('guest-ping'))
    elif c == 'stop':
        try:
            pid = int(open(PIDF).read())
            os.kill(pid, 15)
            print('stopped', pid)
        except (OSError, ValueError) as e:
            print('not running', e)


if __name__ == '__main__':
    main()
