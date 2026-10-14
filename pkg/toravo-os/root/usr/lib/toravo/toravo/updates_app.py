"""Toravo Updates – the "Updates" page in the trailer look: version, channel, auto on/off, check now, update ready (installed at
the next restart), back to the previous version, and optional AI model updates with sizes. Privileged steps via pkexec toravo-update."""
import json, os, subprocess, sys, threading, time
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib, Gio
from . import theme
from .theme import tr
from .widgets import logo, label, micro, chip, vbox, hbox, spacer

APP_ID = 'de.toravo.Updates'
CHANNELS = [('stable', tr('Stabil – von Toravo getestet', 'Stable – tested by Toravo')), ('rolling', tr('Rolling – immer das Neueste', 'Rolling – always the newest'))]
STATUS = {
    'idle': tr('Alles aktuell.', 'Up to date.'), 'checking': tr('Prüfe …', 'Checking …'), 'downloading': tr('Lädt im Hintergrund …', 'Downloading in the background …'),
    'waiting': tr('Wartet – gerade wird gerendert, gestreamt oder der Akku benutzt.', 'Waiting – a render, a stream or battery power is active.'),
    'ready': tr('Update bereit – wird beim nächsten Neustart installiert.', 'Update ready – installed on the next restart.'),
    'installing': tr('Wird installiert …', 'Installing …'), 'verifying': tr('Neue Version wird geprüft …', 'Checking the new version …'),
    'off': tr('Toravo Update ist auf diesem System nicht eingerichtet.', 'Toravo Update is not set up on this system.'),
    'rolled_back': tr('Zur vorherigen Version zurückgekehrt.', 'Went back to the previous version.'), 'error': tr('Prüfung fehlgeschlagen.', 'Check failed.'),
}


def when(ts):
    return time.strftime('%d.%m.%Y %H:%M' if theme.lang() == 'de' else '%b %d, %Y %H:%M', time.localtime(ts)) if ts else '—'


def status():
    r = subprocess.run(['toravo-update', 'status', '--json'], capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except ValueError:
        return {'status': 'error', 'message': r.stderr[-200:]}


class Updates(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title='Toravo Updates')
        self.set_default_size(1080, 820)
        self.busy = False
        sc = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.root = vbox(18, margin=34)
        sc.set_child(self.root)
        self.set_child(sc)
        self.build()
        GLib.timeout_add_seconds(5, self.tick)

    # ------------------------------------------------------------------ layout
    def build(self):
        while (c := self.root.get_first_child()) is not None:
            self.root.remove(c)
        st = self.st = status()
        self.root.append(hbox(16, logo(48), vbox(2, micro('TORAVO UPDATE', 'violet'), label('Updates.', 'tos-h1'))))
        # version + status tile
        tile = self.panel()
        v = Gtk.Label(xalign=0)
        v.set_markup(f'<span size="30000" weight="300">Toravo OS {GLib.markup_escape_text(str(st.get("version", "?")))}</span>')
        tile.append(hbox(14, v, spacer(False), chip(dict(CHANNELS)[st.get('channel', 'stable')].split(' – ')[0].upper())))
        s = st.get('status', 'idle')
        msg = STATUS.get(s, s)
        css = 'tos-body' + (' tos-warn' if s in ('rolled_back', 'error') else ' tos-ok' if s == 'idle' else '')
        self.status_lbl = label(msg, css, wrap=True)
        tile.append(self.status_lbl)
        if st.get('message') and s != 'ready':
            tile.append(label(st['message'], 'tos-small', wrap=True))
        tile.append(label(tr('Letztes Update: ', 'Last update: ') + when(st.get('last_update')) + '   ·   ' + tr('Zuletzt geprüft: ', 'Last check: ') + when(st.get('last_check'))
                          + (f"   ·   Arch {st['arch_snapshot']}" if st.get('arch_snapshot') else ''), 'tos-mono'))
        # ready
        if s == 'ready' and st.get('available'):
            a = st['available']
            rp = self.panel(accent=True)
            rp.append(micro(tr('UPDATE BEREIT', 'UPDATE READY'), 'cyan'))
            rp.append(label(f"Toravo OS {a.get('version')}", 'tos-h2'))
            notes = (a.get('notes') or {}).get(theme.lang()) or ''
            if notes:
                rp.append(label(notes, 'tos-body', wrap=True))
            n = len(a.get('packages', []))
            extra = tr(f"{n} {'Paket' if n == 1 else 'Pakete'} · schon heruntergeladen · Installation beim nächsten Neustart (vor dem Desktop, mit Snapshot)",
                       f"{n} {'package' if n == 1 else 'packages'} · already downloaded · installed on the next restart (before the desktop, with a snapshot)")
            rp.append(label(extra, 'tos-small', wrap=True))
            if a.get('hold'):
                rp.append(label(tr('Zurückgehalten: ', 'Held back: ') + ', '.join(a['hold']), 'tos-small tos-warn', wrap=True))
            now = Gtk.Button(label=tr('Jetzt neu starten', 'Restart now'))
            now.add_css_class('tos-primary')
            now.connect('clicked', lambda *_: subprocess.Popen(['systemctl', 'reboot']))
            rp.append(hbox(12, spacer(False), now))
        # settings
        sp = self.panel()
        sp.append(micro(tr('EINSTELLUNGEN', 'SETTINGS')))
        self.ch_dd = Gtk.DropDown.new_from_strings([n for _, n in CHANNELS])
        self.ch_dd.set_selected(next((i for i, (k, _) in enumerate(CHANNELS) if k == st.get('channel')), 0))
        self.ch_dd.connect('notify::selected', self.on_channel)
        self.auto_sw = Gtk.Switch(active=bool(st.get('auto', True)), valign=Gtk.Align.CENTER)
        self.auto_sw.connect('notify::active', self.on_auto)
        chk = Gtk.Button(label=tr('Jetzt prüfen', 'Check now'))
        chk.add_css_class('tos-big')
        chk.connect('clicked', lambda *_: self.priv(['check', '--force']))
        sp.append(hbox(14, label(tr('Kanal', 'Channel'), 'tos-body'), self.ch_dd, spacer(False),
                       label(tr('Automatisch im Hintergrund laden', 'Download automatically in the background'), 'tos-body'), self.auto_sw))
        sp.append(label(tr('Lädt nur, wenn nichts rendert oder streamt und der Rechner am Strom hängt. Installiert wird erst beim Neustart – nie mitten in der Arbeit.',
                           'Downloads only when nothing is rendering or streaming and the computer is plugged in. Installs only on restart – never in the middle of your work.'),
                        'tos-small', wrap=True))
        sp.append(hbox(12, spacer(False), chk))
        # rollback
        bp = self.panel()
        bp.append(micro(tr('SICHERHEIT', 'SAFETY')))
        bp.append(label(tr('Vor jedem Update macht Toravo einen Snapshot. Startet der Desktop nach einem Update nicht, geht Toravo automatisch zur vorherigen Version zurück.',
                           'Before every update Toravo takes a snapshot. If the desktop does not start after an update, Toravo goes back to the previous version automatically.'),
                        'tos-body', wrap=True))
        back = Gtk.Button(label=tr('Zurück zur vorherigen Version', 'Back to the previous version'))
        back.add_css_class('tos-danger')
        back.connect('clicked', self.on_rollback)
        bp.append(hbox(12, back, spacer(False)))
        # models
        mp = self.panel()
        mp.append(hbox(12, micro(tr('KI-MODELLE · OPTIONAL', 'AI MODELS · OPTIONAL'), 'violet'), spacer(False)))
        mp.append(label(tr('Neue Modell-Versionen sind getrennt vom System und werden nur geladen, wenn du es willst.',
                           'New model versions are separate from the system and are only downloaded when you want them.'), 'tos-small', wrap=True))
        self.models_box = vbox(6)
        self.models_box.append(label(tr('Prüfe Modelle …', 'Checking models …'), 'tos-small'))
        mp.append(self.models_box)
        threading.Thread(target=self.load_models, daemon=True).start()

    def panel(self, accent=False):
        """Card in the trailer look, appended to the page; returns the padded inner box."""
        outer = vbox(0)
        outer.add_css_class('tos-panel2' if accent else 'tos-panel')
        inner = vbox(10, margin=20)
        outer.append(inner)
        self.root.append(outer)
        return inner

    # ------------------------------------------------------------------ actions
    def priv(self, args, then=None):
        if self.busy:
            return
        self.busy = True
        self.status_lbl.set_text(tr('Bitte warten …', 'Please wait …'))

        def work():
            r = subprocess.run(['pkexec', '/usr/bin/toravo-update'] + args, capture_output=True, text=True)
            GLib.idle_add(self.done, r.returncode, then)
        threading.Thread(target=work, daemon=True).start()

    def done(self, rc, then):
        self.busy = False
        self.build()
        if then:
            then(rc)
        return False

    def on_channel(self, dd, _p):
        ch = CHANNELS[dd.get_selected()][0]
        if ch != self.st.get('channel'):
            self.priv(['set', '--channel', ch])

    def on_auto(self, sw, _p):
        if bool(sw.get_active()) != bool(self.st.get('auto', True)):
            self.priv(['set', '--auto', 'on' if sw.get_active() else 'off'])

    def on_rollback(self, *_):
        dlg = Gtk.Window(transient_for=self, modal=True, title=tr('Zurück zur vorherigen Version', 'Back to the previous version'))
        dlg.set_default_size(520, 220)
        b = vbox(14, margin=24)
        b.append(label(tr('Zurück zur vorherigen Version?', 'Go back to the previous version?'), 'tos-h2'))
        b.append(label(tr('Das System von vor dem letzten Update wird wiederhergestellt und der Rechner startet neu. Deine Dateien in ~ bleiben, wie sie sind.',
                          'The system from before the last update is restored and the computer restarts. Your files in ~ stay as they are.'), 'tos-body', wrap=True))
        no = Gtk.Button(label=tr('Abbrechen', 'Cancel'))
        no.connect('clicked', lambda *_: dlg.close())
        yes = Gtk.Button(label=tr('Zurück und neu starten', 'Go back and restart'))
        yes.add_css_class('tos-danger')
        yes.connect('clicked', lambda *_: (dlg.close(), self.priv(['rollback'])))
        b.append(hbox(12, spacer(False), no, yes))
        dlg.set_child(b)
        dlg.present()

    # ------------------------------------------------------------------ models
    def load_models(self):
        r = subprocess.run(['toravo-ai', 'models-check', '--json'], capture_output=True, text=True, timeout=180)
        try:
            ms = json.loads(r.stdout)
        except ValueError:
            ms = None
        GLib.idle_add(self.show_models, ms)

    def show_models(self, ms):
        while (c := self.models_box.get_first_child()) is not None:
            self.models_box.remove(c)
        if ms is None:
            self.models_box.append(label(tr('Modelle konnten nicht geprüft werden (offline?).', 'Could not check the models (offline?).'), 'tos-small tos-warn'))
            return False
        if not ms:
            self.models_box.append(label(tr('Noch keine Modelle installiert (Toravo Setup).', 'No models installed yet (Toravo Setup).'), 'tos-small'))
            return False
        for m in ms:
            row = hbox(12)
            t = label(m['name'], 'tos-body')
            t.set_hexpand(True)
            row.append(t)
            row.append(label(f"{m['size_gb']:.1f} GB", 'tos-mono'))
            if m['update']:
                btn = Gtk.Button(label=tr('Aktualisieren', 'Update'))
                btn.add_css_class('tos-link')
                btn.connect('clicked', self.on_model_update, m, btn)
                row.append(label(tr('NEUE VERSION', 'NEW VERSION'), 'tos-label-cyan'))
                row.append(btn)
            else:
                row.append(label(tr('AKTUELL', 'UP TO DATE'), 'tos-label'))
            self.models_box.append(row)
        return False

    def on_model_update(self, _b, m, btn):
        btn.set_sensitive(False)
        btn.set_label(tr('Lädt …', 'Downloading …'))

        def work():
            r = subprocess.run(['toravo-ai', 'models-update', m['id']], capture_output=True, text=True)
            GLib.idle_add(lambda: (btn.set_label(tr('Fertig', 'Done') if r.returncode == 0 else tr('Fehler', 'Error')), False)[1])
        threading.Thread(target=work, daemon=True).start()

    def tick(self):
        if not self.busy and status().get('status') != self.st.get('status'):
            self.build()
        return True


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_activate(self):
        if self.get_windows():
            self.get_windows()[0].present()
            return
        theme.apply_css()
        Updates(self).present()


def main():
    App().run([sys.argv[0]])


if __name__ == '__main__':
    main()
