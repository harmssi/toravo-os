"""Toravo Setup – first-start assistant: detects the GPU, shows what fits (model x profile table), installs drivers + AI stack
with waveform progress. Backend: toravo.stack (also usable headless: toravo-ai install)."""
import json, os, subprocess, sys, threading, time
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib, Gio
from . import theme, stack, hw
from .widgets import Wave, logo, wordmark, label, micro, chip, vbox, hbox, spacer

APP_ID = 'de.toravo.Setup'
PROFILE_NAMES = {'nvidia': 'NVIDIA · CUDA · NVENC', 'amd': 'AMD · ROCm/Vulkan · VAAPI', 'intel': 'Intel · oneAPI/Vulkan · QSV', 'cpu': 'Nur CPU · Lite'}


def online():
    try:
        import socket
        socket.create_connection(('huggingface.co', 443), timeout=4).close()
        return True
    except OSError:
        return False


class Setup(Gtk.ApplicationWindow):
    def __init__(self, app, first_run=False, dry=False):
        super().__init__(application=app, title='Toravo Setup')
        self.set_default_size(1180, 800)
        self.first_run, self.dry = first_run, dry
        self.extras = set()
        self.stack_def = stack.load_stack()
        self.info = hw.detect()
        self.plan = stack.resolve(self.info, self.stack_def)
        self.rows = {}
        self.pages = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=220)
        self.set_child(self.pages)
        self.pages.add_named(self.page_overview(), 'overview')
        self.pages.add_named(self.page_install(), 'install')

    # ---------------------------------------------------------------- page 1
    def page_overview(self):
        info, plan = self.info, self.plan
        root = vbox(18, margin=34)
        head = hbox(16, logo(48), vbox(2, micro('TORAVO SETUP', 'violet'), label('Dein KI-Studio einrichten.', 'tos-h1')))
        root.append(head)
        root.append(label('Toravo hat deinen Rechner erkannt und wählt passende Modelle. Alles läuft lokal auf deiner Hardware – '
                          'Modelle werden jetzt geladen, nicht mitgeliefert.', 'tos-body', wrap=True))
        # hardware tile
        tile = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=28)
        tile.add_css_class('tos-panel')
        for m in ('top', 'bottom', 'start', 'end'):
            getattr(tile, 'set_margin_' + m)(0)
        inner = hbox(36)
        inner.set_margin_top(16); inner.set_margin_bottom(16); inner.set_margin_start(20); inner.set_margin_end(20)
        def stat(lbl, val, unit=''):
            b = vbox(2, micro(lbl))
            v = Gtk.Label(); v.set_markup(f'<span size="22000" weight="300">{GLib.markup_escape_text(str(val))}</span>'
                                         f'<span size="11000" foreground="{theme.T["text3"]}"> {unit}</span>'); v.set_xalign(0)
            b.append(v)
            return b
        inner.append(vbox(4, micro('GPU'), label(info.get('gpu') or '—', 'tos-h2'), label(PROFILE_NAMES[info['profile']], 'tos-label-cyan')))
        inner.append(stat('VRAM', info['vram_gb'] or '—', 'GB'))
        inner.append(stat('RAM', info['ram_gb'], 'GB'))
        inner.append(stat('STUFE', {'high': '≥ 16', 'mid': '8–16', 'low': '< 8'}[info['tier']], 'GB'))
        inner.append(vbox(4, micro('ENCODER'), label(' · '.join(info['encoders'][:3]), 'tos-mono')))
        tile.append(inner)
        root.append(tile)
        for n in info.get('notes', []):
            root.append(label('Hinweis: ' + n, 'tos-small tos-warn', wrap=True))
        # tools table
        sc = Gtk.ScrolledWindow(vexpand=True)
        lst = vbox(6)
        sysd = plan['system']
        lst.append(self.tool_row('TREIBER', sysd['title'], ', '.join(sysd['packages'][:4]) + (' …' if len(sysd['packages']) > 4 else ''),
                                 sysd['license'], sysd['size_gb'], 'on'))
        for k, o in sysd['optional'].items():
            sw = Gtk.Switch(active=o['enabled'], valign=Gtk.Align.CENTER)
            if o['enabled']:
                self.extras.add(k)
            sw.connect('notify::active', self.on_extra, k)
            lst.append(self.tool_row('OPTIONAL', {'cuda': 'CUDA Toolkit', 'rocm': 'ROCm Runtime'}.get(k, k), ' '.join(o['packages']),
                                     '', o['size_gb'], 'switch', sw))
        for t in plan['tools']:
            size = sum(self.stack_def['models'][m].get('size_gb', 0) for m in t['models']) + \
                sum(self.stack_def['components'][c].get('size_gb', 0) for c in t['components'])
            lic = ', '.join(sorted({self.stack_def['models'][m]['license'].split(' (')[0] for m in t['models']}))
            state = 'off' if t['off'] else ('lite' if t['lite'] else 'on')
            lst.append(self.tool_row(t['area'], t['title'], t['label'] + (f" – {t['note']}" if t['note'] else ''), lic, size, state))
        for t in self.stack_def['tools']:
            for o in t.get('optional', []):
                if stack.variant_fits(o, info):
                    sw = Gtk.Switch(active=False, valign=Gtk.Align.CENTER)
                    sw.connect('notify::active', self.on_extra, o['id'])
                    size = sum(self.stack_def['models'][m].get('size_gb', 0) for m in o['models'])
                    lst.append(self.tool_row('OPTIONAL', o['label'], 'zusätzlich zum Standard', self.stack_def['models'][o['models'][0]]['license'].split(' (')[0],
                                             size, 'switch', sw))
        sc.set_child(lst)
        root.append(sc)
        # footer
        self.total_lbl = label('', 'tos-body')
        self.update_total()
        self.net_lbl = label('', 'tos-small tos-warn')
        later = Gtk.Button(label='Später')
        later.add_css_class('tos-big')
        later.connect('clicked', self.on_later)
        self.pw = Gtk.PasswordEntry(show_peek_icon=True)
        self.pw.set_property('placeholder-text', 'Dein Passwort (für Treiber & Programme)')
        self.pw.set_size_request(300, -1)
        self.need_pw = not os.path.isdir('/run/archiso') and subprocess.run(['sudo', '-n', 'true'], capture_output=True).returncode != 0
        go = Gtk.Button(label='Einrichten')
        go.add_css_class('tos-primary')
        go.connect('clicked', self.on_go)
        foot = hbox(14, vbox(2, self.total_lbl, self.net_lbl), spacer(False))
        if self.need_pw:
            foot.append(self.pw)
            self.pw.connect('activate', self.on_go)
        foot.append(later)
        foot.append(go)
        root.append(foot)
        if not online():
            self.net_lbl.set_text('Keine Internetverbindung – bitte WLAN/Kabel verbinden (oben rechts im Balken).')
        return root

    def tool_row(self, area, title, detail, lic, size, state, widget=None):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        row.add_css_class('tos-panel')
        inner = hbox(16)
        inner.set_margin_top(10); inner.set_margin_bottom(10); inner.set_margin_start(16); inner.set_margin_end(16)
        a = micro(area, 'violet')
        a.set_size_request(110, -1)
        inner.append(a)
        txt = vbox(2, label(title, 'tos-h2'), label(detail, 'tos-small', wrap=True))
        txt.set_hexpand(True)
        inner.append(txt)
        if lic:
            inner.append(chip(lic))
        inner.append(label(f'{size:.1f} GB' if size else '—', 'tos-mono'))
        if widget is not None:
            inner.append(widget)
        else:
            st = {'on': ('AN', 'tos-label-cyan'), 'lite': ('LITE', 'tos-label'), 'off': ('AUS · CLOUD-OPTIONAL', 'tos-label-coral')}[state]
            l = label(st[0], st[1])
            l.set_size_request(150, -1)
            l.set_xalign(1)
            inner.append(l)
        row.append(inner)
        return row

    def on_extra(self, sw, _p, key):
        (self.extras.add if sw.get_active() else self.extras.discard)(key)
        self.plan = stack.resolve(self.info, self.stack_def, tuple(self.extras))
        self.update_total()

    def update_total(self):
        self.total_lbl.set_markup(f'Download und Installation: <b>ca. {self.plan["total_gb"]:.0f} GB</b> · Ziel: '
                                  f'<span font_family="JetBrains Mono">{GLib.markup_escape_text(self.plan["base_dir"])}</span>')

    def on_later(self, *_):
        os.makedirs(os.path.expanduser('~/.config/toravo'), exist_ok=True)
        open(os.path.expanduser('~/.config/toravo/setup-later'), 'w').close()
        subprocess.Popen(['notify-send', '-a', 'Toravo', 'Toravo Setup', 'Jederzeit über die Command Bar (Super + Leertaste) → „Toravo Setup“.'])
        self.close()

    # ---------------------------------------------------------------- page 2
    def page_install(self):
        root = vbox(16, margin=34)
        root.append(hbox(16, logo(44), vbox(2, micro('TORAVO SETUP · LOCAL', 'violet'), label('Richte dein Studio ein …', 'tos-h1'))))
        self.overall = Wave(bars=140, height=84, seed=5)
        root.append(self.overall)
        self.overall_lbl = label('Starte …', 'tos-mono')
        root.append(self.overall_lbl)
        sc = Gtk.ScrolledWindow(vexpand=True)
        self.items_box = vbox(6)
        sc.set_child(self.items_box)
        root.append(sc)
        self.logbuf = Gtk.TextBuffer()
        tv = Gtk.TextView(buffer=self.logbuf, editable=False, monospace=True)
        exp = Gtk.Expander(label='Protokoll')
        lsc = Gtk.ScrolledWindow(min_content_height=140)
        lsc.set_child(tv)
        exp.set_child(lsc)
        root.append(exp)
        self.done_btn = Gtk.Button(label='Fertig')
        self.done_btn.add_css_class('tos-primary')
        self.done_btn.set_sensitive(False)
        self.done_btn.connect('clicked', self.on_done)
        root.append(hbox(12, spacer(False), self.done_btn))
        return root

    def item_row(self, iid, title):
        if iid in self.rows:
            return self.rows[iid]
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        row.add_css_class('tos-panel')
        top = hbox(12)
        top.set_margin_top(10); top.set_margin_start(16); top.set_margin_end(16)
        t = label(title, 'tos-h2')
        t.set_hexpand(True)
        st = label('wartet', 'tos-label')
        top.append(t); top.append(st)
        wv = Wave(bars=110, height=26, seed=abs(hash(iid)) % 97)
        wv.set_margin_start(16); wv.set_margin_end(16)
        msg = label('', 'tos-mono')
        msg.set_margin_start(16); msg.set_margin_bottom(10)
        msg.set_ellipsize(3)
        row.append(top); row.append(wv); row.append(msg)
        self.items_box.append(row)
        self.rows[iid] = (row, st, wv, msg)
        return self.rows[iid]

    def on_go(self, *_):
        pw = self.pw.get_text() if self.need_pw else None
        if self.need_pw:
            chk = subprocess.run(['sudo', '-S', '-p', '', '-v'], input=(pw or '') + '\n', capture_output=True, text=True)
            if chk.returncode != 0:
                self.net_lbl.set_text('Passwort stimmt nicht.')
                return
        self.sudo_pw = pw
        self.pages.set_visible_child_name('install')
        titles = {'system': self.plan['system']['title']}
        for c in self.plan['components']:
            titles['comp:' + c['id']] = c['title']
        for m in self.plan['models']:
            titles['model:' + m['id']] = (m['repo'] or m['id'])
        self.titles = titles
        self.order = list(titles)
        for iid in self.order:
            self.item_row(iid, titles[iid])
        cmd = [sys.executable, '-m', 'toravo.stack', 'install', '--json']
        if self.extras:
            cmd += ['--with', ','.join(sorted(self.extras))]
        if self.dry:
            cmd.append('--dry-run')
        if self.sudo_pw is not None:
            cmd.append('--sudo-stdin')
        env = dict(os.environ, PYTHONPATH='/usr/lib/toravo' + (':' + os.environ['PYTHONPATH'] if os.environ.get('PYTHONPATH') else ''))
        threading.Thread(target=self.worker, args=(cmd, env), daemon=True).start()

    def worker(self, cmd, env):
        try:
            p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env, bufsize=1)
            if self.sudo_pw is not None:
                p.stdin.write(self.sudo_pw + '\n')
            p.stdin.close()
        except OSError as e:
            GLib.idle_add(self.on_event, {'ev': 'done', 'ok': False, 'failed': [str(e)]})
            return
        for line in p.stdout:
            try:
                ev = json.loads(line)
            except ValueError:
                ev = {'ev': 'log', 'msg': line.rstrip()}
            GLib.idle_add(self.on_event, ev)
            if ev.get('ev') == 'done':
                self.got_done = True
        p.wait()
        if not getattr(self, 'got_done', False):
            GLib.idle_add(self.on_event, {'ev': 'done', 'ok': False, 'failed': [f'Abbruch (Exit {p.returncode}) – Protokoll ansehen']})

    def on_event(self, ev):
        k = ev.get('ev')
        if k == 'log':
            self.logbuf.insert(self.logbuf.get_end_iter(), ev.get('msg', '') + '\n')
        elif k == 'item':
            iid = ev['id']
            row, st, wv, msg = self.item_row(iid, self.titles.get(iid, iid))
            state = ev.get('state')
            p = ev.get('p')
            if state == 'run':
                st.set_text('LÄDT' if iid.startswith('model:') else 'LÄUFT')
                st.set_css_classes(['tos-label-cyan'])
                if isinstance(p, (int, float)):
                    wv.phase = 0
                    wv.set_progress(p)
                elif not wv.phase:
                    wv.phase = .01
                    GLib.timeout_add(60, self._anim, wv, iid)
            elif state in ('done', 'skip'):
                wv.phase = 0
                wv.set_progress(1.0)
                st.set_text('FERTIG' if state == 'done' else 'SCHON DA')
                st.set_css_classes(['tos-label'])
            elif state == 'fail':
                wv.phase = 0
                st.set_text('FEHLER')
                st.set_css_classes(['tos-label-coral'])
            if ev.get('msg'):
                msg.set_text(ev['msg'])
            done = sum(1 for i in self.order if self.rows[i][1].get_text() in ('FERTIG', 'SCHON DA', 'FEHLER'))
            self.overall.set_progress(done / max(1, len(self.order)))
            self.overall_lbl.set_text(f'{done} von {len(self.order)} Schritten · {self.titles.get(iid, iid)}')
        elif k == 'done':
            self.reboot = ev.get('reboot')
            ok = ev.get('ok')
            self.overall.set_progress(1.0)
            if ok:
                self.overall_lbl.set_text('Fertig. Dein Studio ist eingerichtet.' + (' Bitte einmal neu starten (Grafiktreiber).' if self.reboot else ''))
                os.makedirs(os.path.expanduser('~/.config/toravo'), exist_ok=True)
                open(os.path.expanduser('~/.config/toravo/setup-done'), 'w').close()
            else:
                self.overall_lbl.set_text('Teilweise fertig – fehlgeschlagen: ' + ', '.join(ev.get('failed', [])) + '. Erneut starten setzt fort.')
            self.done_btn.set_label('Neu starten' if (ok and self.reboot) else 'Fertig')
            self.done_btn.set_sensitive(True)
        return False

    def _anim(self, wv, iid):
        if not wv.phase:
            return False
        wv.phase += .03
        wv.queue_draw()
        return True

    def on_done(self, *_):
        if getattr(self, 'reboot', False) and self.done_btn.get_label() == 'Neu starten':
            subprocess.Popen(['systemctl', 'reboot'])
        self.close()


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE)

    def do_activate(self):
        theme.apply_css()
        w = Setup(self, first_run='--first-run' in sys.argv, dry='--dry-run' in sys.argv)
        w.present()
        if '--auto' in sys.argv:
            GLib.timeout_add(800, lambda: (w.on_go(), False)[1])


def main():
    App().run([sys.argv[0]])


if __name__ == '__main__':
    main()
