"""Studio Local › Connect phone (15.10.2026): the Studio delegates /api/companion* here (studio/server.py stays 127.0.0.1 +
X-Toravo header). The Studio never talks to the phone itself – it only turns the companion service on/off, makes one-time
pairing codes (QR via qrencode) and lists/removes paired phones.

GET  /api/companion                          -> {on, port, name, hosts, devices}
POST /api/companion/pair                     -> turns the service on + new code: {link, code, expires, svg, hosts, on, name, port}
POST /api/companion/off                      -> stops + disables the service, drops open codes
POST /api/companion/devices/<id>/revoke      -> {ok}
"""
import re
from . import store


def state():
    ident_ips = store.private_ips()
    return {'on': store.active(), 'port': store.PORT, 'name': store.hostname(), 'hosts': ident_ips,
            'devices': [store.public(d) for d in store.devices()]}


def pair():
    ok, msg = (True, '') if store.active() else store.turn_on()
    ident = store.identity()
    code, exp = store.new_code()
    lnk = store.link(ident, code)
    return {'link': lnk, 'code': store.fmt_code(code), 'expires': exp, 'svg': store.qr(lnk, 'SVG'), 'hosts': ident['ips'],
            'name': ident['name'], 'port': store.PORT, 'on': store.active() or ok, 'message': '' if ok else msg[-300:]}


def handle(h, method, path, data=None):
    """Called from the Studio handler h (has send_json)."""
    if method == 'GET' and path == '/api/companion':
        return h.send_json(state())
    if method == 'POST':
        if path == '/api/companion/pair':
            return h.send_json(pair())
        if path == '/api/companion/off':
            ok, msg = store.turn_off()
            return h.send_json({'ok': ok, 'message': '' if ok else msg[-300:]})
        if path == '/api/companion/on':
            ok, msg = store.turn_on()
            return h.send_json({'ok': ok, 'message': '' if ok else msg[-300:]})
        m = re.fullmatch(r'/api/companion/devices/(\w{1,40})/revoke', path)
        if m:
            return h.send_json({'ok': store.revoke(m.group(1))})
    return h.send_json({'error': 'not_found'}, 404)
