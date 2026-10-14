"""Toravo Command Bar (Super + Space): "Just say what you want."

Layer-shell overlay, centered like in the trailer. Empty -> Toravo actions; typing -> filters actions + apps;
free text -> "Plan erstellen" (local LLM via Ollama, rule fallback) -> step list -> Enter = jobs into the render queue.
"""
import os, subprocess, sys, threading
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib, Gio, Gdk, Pango
from . import theme
try:
    gi.require_version('Gtk4LayerShell', '1.0')
    from gi.repository import Gtk4LayerShell as LS
except (ValueError, ImportError):
    LS = None

LIVE = os.path.isdir('/run/archiso')


def sh(*cmd):
    subprocess.Popen(list(cmd), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def stream():
    from . import executors
    executors.start_stream()


def comfy():
    sh('bash', '-c', 'systemctl --user start toravo-comfyui.service; for i in $(seq 60); do curl -s -o /dev/null http://127.0.0.1:8188 && break; sleep 1; done; xdg-open http://127.0.0.1:8188')


ACTIONS = [
    # (title, micro tag, keywords, callable)
    ('Song machen', 'YuE2 · LOCAL', 'song lied musik track yue make', lambda: sh('toravo-studio', 'song')),
    ('Musikvideo rendern', 'LTX-VIDEO · COMFYUI', 'video musikvideo mv ltx render', lambda: sh('toravo-studio', 'video')),
    ('Shorts schneiden', '9:16 · UNTERTITEL', 'shorts short reels tiktok vertical cut', lambda: sh('toravo-studio', 'shorts')),
    ('Thumbnail', 'QWEN-IMAGE · A/B', 'thumbnail bild cover vorschaubild', lambda: sh('toravo-studio', 'thumbnail')),
    ('Stimme', 'VOXCPM · WHISPER', 'voice stimme sprechen tts clone whisper untertitel', lambda: sh('toravo-studio', 'voice')),
    ('Kalender & Freigabe', 'CALENDAR', 'kalender plan posting freigabe calendar', lambda: sh('toravo-studio', 'calendar')),
    ('Stream starten', 'OBS · 24/7', 'stream live obs twitch youtube', stream),
    ('Render-Queue', 'QUEUE', 'queue jobs render warteschlange', lambda: sh('toravo-studio', 'queue')),
    ('Toravo Studio öffnen', 'STUDIO', 'studio app', lambda: sh('toravo-studio')),
    ('ComfyUI öffnen', 'COMFYUI', 'comfy comfyui nodes workflow', comfy),
    ('Toravo Setup', 'KI-WERKZEUGE EINRICHTEN', 'setup treiber nvidia cuda modelle install ki', lambda: sh('toravo-setup')),
    ('Terminal', 'KITTY', 'terminal shell konsole', lambda: sh('foot' if theme.software_rendering() else 'kitty')),
    ('Dateien', 'THUNAR', 'dateien files ordner explorer', lambda: sh('thunar', os.path.expanduser('~/Toravo'))),
    ('Browser', 'FIREFOX', 'browser web firefox internet', lambda: sh('firefox')),
    ('WLAN & Netzwerk', 'NETZWERK', 'wlan wifi netzwerk internet network', lambda: sh('toravo-network')),
    ('Sperren', 'LOCK', 'sperren lock', lambda: sh('loginctl', 'lock-session')),
    ('Neu starten', 'POWER', 'neustart reboot restart', lambda: sh('systemctl', 'reboot')),
    ('Ausschalten', 'POWER', 'ausschalten herunterfahren shutdown poweroff', lambda: sh('systemctl', 'poweroff')),
]
if LIVE:
    ACTIONS.insert(0, ('Toravo OS installieren', 'INSTALLER · 3 SCHRITTE', 'install installieren installer', lambda: sh('toravo-installer')))

ICONS = {'song': '♫', 'voice': '◉', 'video': '▶', 'shorts': '▮', 'thumbnail': '▣', 'stems': '≋', 'master': '◆', 'transcribe': '¶',
         'stream': '●', 'studio': '◇'}
TAGS = {'song': 'YuE2', 'voice': 'VoxCPM', 'video': 'LTX · ComfyUI', 'shorts': 'auto-edit · Whisper', 'thumbnail': 'Qwen-Image',
        'stems': 'Demucs', 'master': 'Matchering', 'transcribe': 'Whisper', 'stream': 'OBS', 'studio': 'Studio'}


def score(q, title, kw):
    q = q.lower().strip()
    t = (title + ' ' + kw).lower()
    if not q:
        return 1
    if title.lower().startswith(q):
        return 100
    if all(w in t for w in q.split()):
        return 60
    # fuzzy subsequence
    i = 0
    for ch in t:
        if i < len(q) and ch == q[i]:
            i += 1
    return 20 if i == len(q) else 0


class Bar(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='de.toravo.CommandBar', flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.win = None
        self.plan = None
        self.apps = []

    def do_activate(self):
        if self.win:
            self.win.close()
            return
        theme.apply_css(CSS)
        self.apps = [a for a in Gio.AppInfo.get_all() if a.should_show()]
        w = Gtk.ApplicationWindow(application=self)
        w.add_css_class('tos-transparent')
        self.win = w
        if LS and LS.is_supported():
            LS.init_for_window(w)
            LS.set_layer(w, LS.Layer.OVERLAY)
            LS.set_namespace(w, 'toravo-commandbar')
            LS.set_keyboard_mode(w, LS.KeyboardMode.EXCLUSIVE)
            LS.set_anchor(w, LS.Edge.TOP, True)
            mon = Gdk.Display.get_default().get_monitors().get_item(0)
            h = mon.get_geometry().height if mon else 1080
            LS.set_margin(w, LS.Edge.TOP, int(h * .30))
        else:
            w.set_decorated(False)
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        panel.add_css_class('cb-panel')
        panel.set_size_request(760, -1)
        panel.set_valign(Gtk.Align.START)
        row = Gtk.Box(spacing=10)
        row.add_css_class('cb-input-row')
        prompt = Gtk.Label(label='❯')
        prompt.add_css_class('cb-prompt')
        self.entry = Gtk.Entry(hexpand=True)
        self.entry.add_css_class('tos-cmd')
        self.entry.set_placeholder_text('Sag einfach, was du willst …   z. B. „turn skyborne into a music video + 3 shorts + thumbnail“')
        self.entry.connect('changed', self.on_changed)
        self.entry.connect('activate', self.on_enter)
        row.append(prompt)
        row.append(self.entry)
        panel.append(row)
        sep = Gtk.Separator()
        panel.append(sep)
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.list.add_css_class('cb-list')
        self.list.connect('row-activated', lambda lb, r: self.activate_row(r))
        sc = Gtk.ScrolledWindow(propagate_natural_height=True, max_content_height=430, hscrollbar_policy=Gtk.PolicyType.NEVER)
        sc.set_child(self.list)
        panel.append(sc)
        foot = Gtk.Box(spacing=10)
        foot.add_css_class('cb-foot')
        l1 = Gtk.Label()
        l1.set_markup(f'<span letter_spacing="{int(9 * 1024 * .36)}" size="9216" weight="600" foreground="{theme.T["cyan"]}">COMMAND BAR</span>')
        self.status = Gtk.Label(hexpand=True, xalign=1)
        self.status.set_markup(self.hint())
        foot.append(l1)
        foot.append(self.status)
        panel.append(foot)
        w.set_child(panel)
        keys = Gtk.EventControllerKey()
        keys.connect('key-pressed', self.on_key)
        w.add_controller(keys)
        self.fill('')
        w.present()
        self.entry.grab_focus()
        if len(sys.argv) > 1 and sys.argv[1] == '--demo':
            self.entry.set_text('turn skyborne into a music video + 3 shorts + thumbnail')
            GLib.timeout_add(500, lambda: (self.make_plan(), False)[1])

    def hint(self, extra=''):
        return (f'<span size="9216" foreground="{theme.T["text3"]}">{extra}<span font_family="JetBrains Mono">↵</span> ausführen   '
                f'<span font_family="JetBrains Mono">Tab</span> Plan   <span font_family="JetBrains Mono">Esc</span> schließen</span>')

    # -------------------------------------------------------------- list
    def clear(self):
        while (r := self.list.get_row_at_index(0)) is not None:
            self.list.remove(r)

    def add_row(self, title, tag, data, icon='', sub=''):
        r = Gtk.ListBoxRow()
        b = Gtk.Box(spacing=12)
        b.add_css_class('cb-row')
        ic = Gtk.Label(label=icon or '›')
        ic.add_css_class('cb-icon')
        ic.set_size_request(18, -1)
        b.append(ic)
        tb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        t = Gtk.Label(label=title, xalign=0)
        t.add_css_class('cb-title')
        t.set_ellipsize(Pango.EllipsizeMode.END)
        tb.append(t)
        if sub:
            s = Gtk.Label(label=sub, xalign=0)
            s.add_css_class('cb-sub')
            s.set_ellipsize(Pango.EllipsizeMode.END)
            tb.append(s)
        b.append(tb)
        if tag:
            c = Gtk.Label(label=tag)
            c.add_css_class('cb-tag')
            b.append(c)
        r.set_child(b)
        r.data = data
        self.list.append(r)
        return r

    def fill(self, q):
        self.plan = None
        self.clear()
        items = []
        for a in ACTIONS:
            s = score(q, a[0], a[2])
            if s:
                items.append((s + 5, ('action', a), a[0], a[1], '◇'))
        if q.strip():
            for app in self.apps:
                s = score(q, app.get_display_name(), (app.get_description() or '') + ' ' + (app.get_executable() or ''))
                if s >= 20:
                    items.append((s, ('app', app), app.get_display_name(), 'APP', '▫'))
        items.sort(key=lambda x: -x[0])
        if q.strip() and (len(q.split()) >= 3 or not items or items[0][0] < 60):
            self.add_row(f'Plan erstellen: „{q.strip()}“', 'AGENT · LOCAL', ('plan', q), '✦', 'Toravo zerlegt deinen Wunsch in Schritte für die lokalen Werkzeuge')
        for it in items[:9]:
            self.add_row(it[2], it[3], it[1], it[4])
        first = self.list.get_row_at_index(0)
        if first:
            self.list.select_row(first)

    def on_changed(self, e):
        self.fill(e.get_text())
        self.status.set_markup(self.hint())

    def on_key(self, ctl, keyval, code, state):
        if keyval == Gdk.KEY_Escape:
            if self.plan:
                self.fill(self.entry.get_text())
                self.status.set_markup(self.hint())
                return True
            self.win.close()
            return True
        if keyval in (Gdk.KEY_Down, Gdk.KEY_Up):
            r = self.list.get_selected_row()
            i = (r.get_index() if r else -1) + (1 if keyval == Gdk.KEY_Down else -1)
            n = self.list.get_row_at_index(max(0, i))
            if n:
                self.list.select_row(n)
            return True
        if keyval == Gdk.KEY_Tab:
            if self.entry.get_text().strip():
                self.make_plan()
            return True
        return False

    def on_enter(self, *_):
        if self.plan:
            return self.run_plan()
        r = self.list.get_selected_row()
        if r:
            self.activate_row(r)

    def activate_row(self, r):
        kind, val = r.data
        if kind == 'action':
            self.win.close()
            val[3]()
        elif kind == 'app':
            self.win.close()
            val.launch([], None)
        elif kind == 'plan':
            self.make_plan()
        elif kind == 'run':
            self.run_plan()

    # -------------------------------------------------------------- plan
    def make_plan(self):
        text = self.entry.get_text().strip()
        if not text:
            return
        self.clear()
        self.add_row('Plane …', 'AGENT', ('noop', None), '✦', 'lokales Modell denkt nach')
        self.status.set_markup(self.hint('Plan wird erstellt …   '))

        def work():
            from . import agent
            try:
                p = agent.readiness(agent.plan(text))
            except Exception as e:  # noqa: BLE001
                p = {'steps': [], 'error': str(e)}
            GLib.idle_add(self.show_plan, p)
        threading.Thread(target=work, daemon=True).start()

    def show_plan(self, p):
        self.clear()
        self.plan = p
        if not p.get('steps'):
            self.add_row('Kein Plan möglich', '', ('noop', None), '!', p.get('error', ''))
            return False
        for i, s in enumerate(p['steps']):
            ready = s.get('ready', True)
            tag = TAGS.get(s['kind'], s['kind']) + ('' if ready else ' · FEHLT')
            if s.get('engine') == 'lite':
                tag += ' · LITE'
            sub = '' if ready else 'Werkzeug nicht eingerichtet – Toravo Setup öffnen'
            r = self.add_row(s['title'], tag, ('noop', None), ICONS.get(s['kind'], '·'), sub)
            if not ready:
                r.get_child().add_css_class('cb-missing')
        prov = {'ollama': 'lokales LLM', 'anthropic': 'Claude (eigener Schlüssel)', 'rules': 'Regel-Planer'}.get(p.get('provider'), p.get('provider'))
        run = self.add_row(f'Ausführen · {len(p["steps"])} Schritte in die Render-Queue', prov.upper(), ('run', None), '↵')
        run.get_child().add_css_class('cb-run')
        self.list.select_row(run)
        self.status.set_markup(self.hint('Plan bereit   '))
        return False

    def run_plan(self):
        from . import queue
        ids = queue.enqueue_plan(self.plan)
        sh('notify-send', '-a', 'Toravo', 'In der Render-Queue', f'{len(ids)} Jobs · {self.plan.get("title", "")}')
        self.win.close()
        return True


CSS = f"""
window.tos-transparent {{ background: transparent; }}
.cb-panel {{ background-color: rgba(18,17,28,0.97); border: 1px solid {theme.T['line']}; border-radius: 14px;
             box-shadow: 0 30px 90px rgba(0,0,0,0.6), 0 0 0 1px rgba(138,92,246,0.10); }}
.cb-input-row {{ padding: 14px 18px 12px 18px; }}
entry.tos-cmd, entry.tos-cmd:focus-within, entry.tos-cmd:focus {{ border: none; background: transparent; box-shadow: none; outline: none; }}
.cb-prompt {{ color: {theme.T['violet']}; font-size: 20px; font-weight: 700; }}
.cb-list {{ padding: 6px 8px; }}
.cb-list row {{ border-radius: 9px; padding: 0; }}
.cb-row {{ padding: 8px 10px; }}
.cb-icon {{ color: {theme.T['violet']}; font-size: 13px; }}
.cb-title {{ color: {theme.T['text']}; font-size: 14px; }}
.cb-sub {{ color: {theme.T['text3']}; font-size: 11.5px; }}
.cb-tag {{ background-color: {theme.T['bg2']}; border: 1px solid {theme.T['line']}; border-radius: 6px; padding: 1px 8px;
           color: {theme.T['text3']}; font-family: "JetBrains Mono"; font-size: 10px; }}
.cb-missing .cb-title {{ color: {theme.T['text3']}; }}
.cb-missing .cb-icon {{ color: {theme.T['coral']}; }}
.cb-run .cb-title {{ color: #ffffff; font-weight: 700; }}
.cb-run .cb-icon {{ color: {theme.T['cyan']}; }}
.cb-foot {{ padding: 8px 18px 10px 18px; border-top: 1px solid {theme.T['line']}; }}
"""


def main():
    Bar().run([sys.argv[0]])


if __name__ == '__main__':
    main()
