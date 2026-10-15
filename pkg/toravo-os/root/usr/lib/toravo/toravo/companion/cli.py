"""toravo-companion – phone access from the terminal (15.10.2026).

  toravo-companion status          service on/off, addresses, fingerprint, paired phones
  toravo-companion pair [--host A[,B]]  turns the service on and prints a pairing link + QR code (valid 10 minutes, single use);
                                   --host puts other addresses into the link (e.g. 127.0.0.1 behind an SSH tunnel)
  toravo-companion devices         paired phones
  toravo-companion revoke <id>     remove a phone (its token stops working at once)
  toravo-companion on | off        start + enable / stop + disable the service (toravo-companion.service, user unit)
"""
import sys, time
from . import store
from ..theme import tr


def fmt_t(t):
    return time.strftime('%d.%m.%Y %H:%M', time.localtime(t)) if t else '–'


def devices():
    ds = store.devices()
    if not ds:
        print(tr('Keine Handys gekoppelt.', 'No phones paired.'))
    for d in ds:
        print(f"{d['id']}  {d.get('name', ''):<24} {d.get('model', ''):<16} {tr('gekoppelt', 'paired')} {fmt_t(d.get('created'))} · "
              f"{tr('zuletzt', 'last seen')} {fmt_t(d.get('last_seen'))}")


def main():
    a = sys.argv[1:]
    cmd = a[0] if a else 'status'
    if cmd == 'status':
        ident = store.identity()
        print(f"Toravo Companion: {tr('an', 'on') if store.active() else tr('aus', 'off')} · {tr('Port', 'port')} {store.PORT}")
        print(f"{tr('Name', 'Name')}: {ident['name']} · id {ident['id']}")
        print(f"{tr('Adressen', 'Addresses')}: {', '.join(ident['ips']) or '–'}")
        print(f"{tr('Fingerabdruck', 'Fingerprint')} (SHA-256 SPKI): {ident['fp']}")
        devices()
    elif cmd == 'pair':
        if not store.active():
            ok, msg = store.turn_on()
            if not ok:
                print(tr('Dienst startet nicht: ', 'Service does not start: ') + msg, file=sys.stderr)
        ident = store.identity()
        if '--host' in a and a.index('--host') + 1 < len(a):
            ident['ips'] = [h for h in a[a.index('--host') + 1].split(',') if h]
        code, exp = store.new_code()
        lnk = store.link(ident, code)
        q = store.qr(lnk, 'ANSIUTF8')
        if q:
            print(q)
        print(lnk)
        print()
        print(f"{tr('Code', 'Code')}: {store.fmt_code(code)}  ·  {tr('gültig bis', 'valid until')} {time.strftime('%H:%M', time.localtime(exp))}  ·  "
              + tr('einmalig, nur im selben Netzwerk', 'single use, same network only'))
    elif cmd == 'devices':
        devices()
    elif cmd == 'revoke' and len(a) > 1:
        ok = store.revoke(a[1])
        print(tr('Entfernt.', 'Removed.') if ok else tr('Unbekannte Geräte-ID.', 'Unknown device id.'))
        sys.exit(0 if ok else 1)
    elif cmd in ('on', 'off'):
        ok, msg = store.turn_on() if cmd == 'on' else store.turn_off()
        print(msg or ('ok' if ok else 'error'))
        sys.exit(0 if ok else 1)
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == '__main__':
    main()
