"""Toravo OS installer – "the simplest installer in the world": 3 screens, fullscreen, trailer look.

1 Willkommen / Welcome (language/keyboard detected, small "ändern"/"change" link – the UI follows the chosen language live)  2 Wohin installieren? (disk tiles, safest default)
3 Wer bist du? (name + password)  ->  Installieren (waveform progress)  ->  Neu starten
Everything else (partitions, btrfs + snapshots, zram, bootloader, timezone, drivers) happens without questions.
"""
import json, os, re, subprocess, sys, threading, unicodedata, urllib.request
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib, Gio, Pango
from .. import theme, hw
from ..theme import tr
from ..widgets import Wave, logo, wordmark, label, micro, vbox, hbox, spacer
from . import disks as D

LANGS = [('de_DE.UTF-8', 'Deutsch'), ('en_US.UTF-8', 'English (US)'), ('en_GB.UTF-8', 'English (UK)'), ('fr_FR.UTF-8', 'Français'),
         ('es_ES.UTF-8', 'Español'), ('it_IT.UTF-8', 'Italiano'), ('nl_NL.UTF-8', 'Nederlands'), ('pl_PL.UTF-8', 'Polski'),
         ('pt_PT.UTF-8', 'Português'), ('tr_TR.UTF-8', 'Türkçe')]
KEYBOARDS = [('de', '', 'de-latin1', 'Deutsch', 'German'), ('de', 'nodeadkeys', 'de-latin1-nodeadkeys', 'Deutsch (ohne Tottasten)', 'German (no dead keys)'),
             ('ch', 'de', 'de_CH-latin1', 'Schweiz (Deutsch)', 'Swiss (German)'), ('at', '', 'de-latin1', 'Österreich', 'Austrian'), ('us', '', 'us', 'English (US)'),
             ('gb', '', 'uk', 'English (UK)'), ('fr', '', 'fr-latin1', 'Français'), ('es', '', 'es', 'Español'), ('it', '', 'it', 'Italiano'),
             ('nl', '', 'nl', 'Nederlands'), ('pl', '', 'pl', 'Polski'), ('pt', '', 'pt-latin1', 'Português'), ('tr', '', 'trq', 'Türkçe')]
ZONES = ['Europe/Berlin', 'Europe/Vienna', 'Europe/Zurich', 'Europe/London', 'Europe/Paris', 'Europe/Madrid', 'Europe/Rome',
         'Europe/Amsterdam', 'Europe/Warsaw', 'Europe/Istanbul', 'America/New_York', 'America/Chicago', 'America/Los_Angeles', 'UTC']
LANG_KB = {'de': 0, 'en_US': 4, 'en_GB': 5, 'fr': 6, 'es': 7, 'it': 8, 'nl': 9, 'pl': 10, 'pt': 11, 'tr': 12}


def kb_name(k):
    return k[4] if len(k) > 4 and theme.lang() == 'en' else k[3]


def detect_locale():
    lang = os.environ.get('LANG') or 'de_DE.UTF-8'
    li = next((i for i, (k, _) in enumerate(LANGS) if k.split('.')[0] == lang.split('.')[0]), 0)
    code = LANGS[li][0].split('.')[0]
    ki = LANG_KB.get(code, LANG_KB.get(code.split('_')[0], 0))
    try:
        cur = open('/etc/toravo/xkb_layout').read().strip()
        ki = next((i for i, k in enumerate(KEYBOARDS) if k[0] == cur), ki)
    except OSError:
        pass
    return li, ki


def detect_timezone(cb):
    def work():
        tz = 'Europe/Berlin'
        try:
            with urllib.request.urlopen('https://ipapi.co/timezone', timeout=4) as r:
                t = r.read().decode().strip()
                if re.match(r'^[A-Za-z_]+/[A-Za-z_/]+$', t) and os.path.exists('/usr/share/zoneinfo/' + t):
                    tz = t
        except OSError:
            pass
        GLib.idle_add(cb, tz)
    threading.Thread(target=work, daemon=True).start()


def online():
    try:
        out = subprocess.run(['nmcli', '-t', 'networking', 'connectivity'], capture_output=True, text=True, timeout=4).stdout.strip()
        return out == 'full'
    except (OSError, subprocess.SubprocessError):
        return False


def login_from(name):
    first = (name.strip().split() or ['creator'])[0]
    s = unicodedata.normalize('NFKD', first.lower()).encode('ascii', 'ignore').decode()
    s = re.sub(r'[^a-z0-9_-]', '', s)
    if not s or not re.match(r'^[a-z_]', s):
        s = 'creator'
    return s[:24]


class Installer(Gtk.ApplicationWindow):
    def __init__(self, app, welcome_mode=False):
        super().__init__(application=app, title=tr('Toravo OS installieren', 'Install Toravo OS'))
        self.welcome_mode = welcome_mode
        self.li, self.ki = detect_locale()
        self.tz = 'Europe/Berlin'
        self.disks, self.sel, self.mode = [], None, None
        self.hwinfo = None
        self.pages = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT, transition_duration=260)
        overlay = Gtk.Overlay()
        bg = Gtk.Picture.new_for_filename('/usr/share/toravo/wallpaper/toravo-lock.png')
        bg.set_content_fit(Gtk.ContentFit.COVER) if hasattr(bg, 'set_content_fit') else None
        overlay.set_child(bg)
        overlay.add_overlay(self.pages)
        self.set_child(overlay)
        self.build_pages()
        detect_timezone(self.set_tz)
        threading.Thread(target=self.load_hw, daemon=True).start()
        self.fullscreen()

    def build_pages(self):
        for n in ('welcome', 'disk', 'user', 'progress'):
            old = self.pages.get_child_by_name(n)
            if old is not None:
                self.pages.remove(old)
        self.pages.add_named(self.p_welcome(), 'welcome')
        self.pages.add_named(self.p_disk(), 'disk')
        self.pages.add_named(self.p_user(), 'user')
        self.pages.add_named(self.p_progress(), 'progress')

    def relabel(self):
        """14.10.2026 (owner: Toravo OS must also show English): the chosen language applies to the installer at once."""
        self.set_title(tr('Toravo OS installieren', 'Install Toravo OS'))
        self.build_pages()
        self.pages.set_visible_child_name('welcome')
        return False

    def load_hw(self):
        try:
            self.hwinfo = hw.detect()
        except Exception:  # noqa: BLE001
            self.hwinfo = None

    def set_tz(self, tz):
        self.tz = tz
        if tz in ZONES:
            self.tz_dd.set_selected(ZONES.index(tz))
        self.update_locale_label()

    # -------------------------------------------------------------- frame
    def frame(self, step, title, body, content, back=None, nxt=None, nxt_label=None):
        nxt_label = nxt_label or tr('Weiter', 'Next')
        outer = vbox(0)
        outer.set_halign(Gtk.Align.CENTER)
        outer.set_valign(Gtk.Align.FILL)
        outer.set_size_request(980, -1)
        top = hbox(14, logo(36), wordmark(12, halign=Gtk.Align.START), spacer(False))
        if step:
            dots = hbox(8)
            for i in (1, 2, 3):
                d = Gtk.Label(label='●' if i == step else '○')
                d.add_css_class('tos-label-violet' if i <= step else 'tos-label')
                dots.append(d)
            dots.append(label(tr(f'SCHRITT {step} VON 3', f'STEP {step} OF 3'), 'tos-label'))
            top.append(dots)
        top.set_margin_top(36)
        outer.append(top)
        outer.append(spacer())
        tl = label(title, 'tos-hero', xalign=0)
        outer.title_label = tl
        outer.append(tl)
        if body:
            b = label(body, 'tos-body', wrap=True)
            b.set_margin_top(6)
            outer.append(b)
        content.set_margin_top(30)
        outer.append(content)
        outer.append(spacer())
        nav = hbox(14)
        if back:
            bb = Gtk.Button(label=tr('Zurück', 'Back'))
            bb.add_css_class('tos-big')
            bb.connect('clicked', lambda *_: back())
            nav.append(bb)
        nav.append(spacer(False))
        if nxt:
            self.next_btn = nb = Gtk.Button(label=nxt_label)
            nb.add_css_class('tos-primary')
            nb.connect('clicked', lambda *_: nxt())
            nav.append(nb)
            outer.next_btn = nb
        nav.set_margin_bottom(44)
        outer.append(nav)
        return outer

    # -------------------------------------------------------------- 1 welcome
    def p_welcome(self):
        c = vbox(22)
        btns = hbox(16)
        inst = Gtk.Button(label=tr('Toravo OS installieren', 'Install Toravo OS'))
        inst.add_css_class('tos-primary')
        inst.connect('clicked', lambda *_: self.go_disk())
        btns.append(inst)
        tryb = Gtk.Button(label=tr('Erst ausprobieren', 'Try it first'))
        tryb.add_css_class('tos-big')
        tryb.connect('clicked', lambda *_: self.close())
        btns.append(tryb)
        c.append(btns)
        self.loc_lbl = label('', 'tos-small')
        chg = Gtk.MenuButton(label=tr('ändern', 'change'))
        chg.add_css_class('tos-link')
        chg.set_popover(self.locale_popover())
        c.append(hbox(6, self.loc_lbl, chg))
        self.net_row = hbox(8)
        c.append(self.net_row)
        GLib.timeout_add(600, self.check_net)
        self.update_locale_label()
        hero = vbox(0)
        hero.append(logo(96, glow=True))
        f = self.frame(1, tr('Willkommen bei Toravo OS.', 'Welcome to Toravo OS.'),
                       tr('Dein Rechner wird zum KI-Studio für Songs, Stimmen, Musikvideos, Shorts, Thumbnails und Streams. '
                          'Lokal. Open Source. Kostenlos. Die Installation dauert etwa 5 Minuten und braucht nur 3 Schritte.',
                          'Your computer becomes an AI studio for songs, voices, music videos, Shorts, thumbnails and streams. '
                          'Local. Open source. Free. Installing takes about 5 minutes and only 3 steps.'), c)
        return f

    def locale_popover(self):
        pop = Gtk.Popover()
        b = vbox(10, margin=14)
        self.lang_dd = Gtk.DropDown.new_from_strings([n for _, n in LANGS])
        self.lang_dd.set_selected(self.li)
        self.kb_dd = Gtk.DropDown.new_from_strings([kb_name(k) for k in KEYBOARDS])
        self.kb_dd.set_selected(self.ki)
        self.tz_dd = Gtk.DropDown.new_from_strings(ZONES)
        self.tz_dd.set_selected(ZONES.index(self.tz) if self.tz in ZONES else 0)
        for lbl, w in ((tr('SPRACHE', 'LANGUAGE'), self.lang_dd), (tr('TASTATUR', 'KEYBOARD'), self.kb_dd), (tr('ZEITZONE', 'TIME ZONE'), self.tz_dd)):
            b.append(micro(lbl))
            b.append(w)
        self.lang_dd.connect('notify::selected', lambda *_: self.on_locale())
        self.kb_dd.connect('notify::selected', lambda *_: self.on_locale())
        self.tz_dd.connect('notify::selected', lambda *_: self.on_locale())
        test = Gtk.Entry(placeholder_text=tr('Testen: äöü ß @ €', 'Test: @ # € £ ~'))
        b.append(test)
        pop.set_child(b)
        return pop

    def on_locale(self):
        new_li = self.lang_dd.get_selected()
        lang_changed = new_li != self.li
        self.li = new_li
        new_ki = self.kb_dd.get_selected()
        if new_ki != self.ki:
            self.ki = new_ki
            k = KEYBOARDS[self.ki]
            if os.environ.get('HYPRLAND_INSTANCE_SIGNATURE'):
                subprocess.run(['hyprctl', 'keyword', 'input:kb_layout', k[0]], capture_output=True)
                subprocess.run(['hyprctl', 'keyword', 'input:kb_variant', k[1]], capture_output=True)
        self.tz = ZONES[self.tz_dd.get_selected()]
        self.update_locale_label()
        if lang_changed:
            before = theme.lang()
            os.environ['TORAVO_LANG'] = LANGS[self.li][0]
            if theme.lang() != before:
                GLib.idle_add(self.relabel)

    def update_locale_label(self):
        if hasattr(self, 'loc_lbl'):
            self.loc_lbl.set_text(tr(f'Sprache: {LANGS[self.li][1]}  ·  Tastatur: {kb_name(KEYBOARDS[self.ki])}  ·  Zeitzone: {self.tz}',
                                     f'Language: {LANGS[self.li][1]}  ·  Keyboard: {kb_name(KEYBOARDS[self.ki])}  ·  Time zone: {self.tz}'))

    def check_net(self):
        while (ch := self.net_row.get_first_child()) is not None:
            self.net_row.remove(ch)
        if online():
            self.net_row.append(label('● Online', 'tos-small tos-ok'))
        else:
            self.net_row.append(label(tr('Kein Internet – nicht nötig für die Installation, aber für Uhrzeit, Updates und KI-Modelle.',
                                         'No internet – not needed to install, but for the clock, updates and AI models.'), 'tos-small'))
            w = Gtk.Button(label=tr('WLAN verbinden', 'Connect Wi-Fi'))
            w.add_css_class('tos-link')
            w.connect('clicked', lambda *_: self.wifi_dialog())
            self.net_row.append(w)
        return False

    def wifi_dialog(self):
        dlg = Gtk.Window(transient_for=self, modal=True, title=tr('WLAN', 'Wi-Fi'))
        dlg.set_default_size(460, 420)
        b = vbox(10, margin=20)
        b.append(label(tr('WLAN verbinden', 'Connect Wi-Fi'), 'tos-h2'))
        lb = Gtk.ListBox()
        sc = Gtk.ScrolledWindow(vexpand=True)
        sc.set_child(lb)
        b.append(sc)
        pw = Gtk.PasswordEntry(show_peek_icon=True)
        pw.set_property('placeholder-text', tr('Passwort', 'Password'))
        b.append(pw)
        st = label('', 'tos-small')
        b.append(st)
        con = Gtk.Button(label=tr('Verbinden', 'Connect'))
        con.add_css_class('tos-primary')
        b.append(con)
        dlg.set_child(b)
        out = subprocess.run(['nmcli', '-t', '-f', 'SSID,SIGNAL,SECURITY', 'dev', 'wifi', 'list', '--rescan', 'yes'], capture_output=True, text=True).stdout
        seen = set()
        for line in out.splitlines():
            p = line.split(':')
            if p[0] and p[0] not in seen:
                seen.add(p[0])
                r = Gtk.ListBoxRow()
                r.set_child(label(f'{p[0]}   ·   {p[1]} %', 'tos-body'))
                r.ssid = p[0]
                lb.append(r)
        if not seen:
            st.set_text(tr('Kein WLAN gefunden (oder kein WLAN-Adapter).', 'No Wi-Fi found (or no Wi-Fi adapter).'))

        def connect(*_):
            r = lb.get_selected_row()
            if not r:
                return
            cmd = ['nmcli', 'dev', 'wifi', 'connect', r.ssid] + (['password', pw.get_text()] if pw.get_text() else [])
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode == 0:
                dlg.close()
                self.check_net()
            else:
                st.set_text(tr('Verbindung fehlgeschlagen: ', 'Connection failed: ') + (res.stderr or res.stdout).strip()[-120:])
        con.connect('clicked', connect)
        dlg.present()

    # -------------------------------------------------------------- 2 disk
    def p_disk(self):
        self.tiles_box = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=3, column_spacing=16, row_spacing=16,
                                     homogeneous=True)
        c = vbox(18)
        c.append(self.tiles_box)
        self.disk_info = label('', 'tos-body', wrap=True)
        c.append(self.disk_info)
        self.erase_box = vbox(10)
        c.append(self.erase_box)
        return self.frame(2, tr('Wohin installieren?', 'Where to install?'),
                          tr('Wähle eine Platte. Toravo nimmt von sich aus immer die sicherste Möglichkeit – '
                             'es wird nie etwas gelöscht, ohne dass du es ausdrücklich bestätigst.',
                             'Pick a disk. Toravo always takes the safest option on its own – '
                             'nothing is ever erased unless you explicitly confirm it.'), c,
                          back=lambda: self.pages.set_visible_child_name('welcome'), nxt=self.go_user)

    def go_disk(self):
        self.disks = D.scan()
        name, mode = D.recommend(self.disks)
        self.sel, self.mode = name, mode
        self.render_tiles()
        self.pages.set_visible_child_name('disk')

    def render_tiles(self):
        while (ch := self.tiles_box.get_first_child()) is not None:
            self.tiles_box.remove(ch)
        for d in self.disks:
            btn = Gtk.Button()
            btn.add_css_class('tos-tile')
            if d['name'] == self.sel:
                btn.add_css_class('selected')
            b = vbox(6)
            icon = '⛁' if d['tran'] != 'usb' else '⏏'
            b.append(hbox(10, label(icon, 'tos-h1'), vbox(0, label(d['size_h'], 'tos-h1'), label(d['model'], 'tos-small'))))
            ct = label(d['content'], 'tos-body')
            if d['windows']:
                ct.add_css_class('tos-warn')
            b.append(ct)
            b.append(label(f'/dev/{d["name"]}', 'tos-mono'))
            btn.set_child(b)
            btn.set_size_request(290, 150)
            btn.set_sensitive(not d['boot_medium'] and not d['too_small'])
            btn.connect('clicked', self.pick, d)
            self.tiles_box.append(btn)
        self.describe()

    def pick(self, _b, d):
        self.sel = d['name']
        self.mode = 'empty' if d['empty'] else ('alongside' if d['can_alongside'] else None)
        self.render_tiles()

    def disk(self):
        return next((d for d in self.disks if d['name'] == self.sel), None)

    def describe(self):
        while (ch := self.erase_box.get_first_child()) is not None:
            self.erase_box.remove(ch)
        d = self.disk()
        nb = getattr(self, 'next_btn', None)
        if not self.disks:
            self.disk_info.set_text(tr('Keine Platte gefunden.', 'No disk found.'))
            self.set_next(False)
            return
        if not d:
            self.disk_info.set_text(tr('Keine leere Platte und kein freier Platz gefunden. Wähle eine Platte – sie müsste dann komplett gelöscht werden.',
                                       'No empty disk and no free space found. Pick a disk – it would then have to be erased completely.'))
            self.set_next(False)
            return
        if self.mode == 'empty':
            self.disk_info.set_markup(tr(f'<b>Empfohlen:</b> Toravo OS kommt auf die leere Platte <b>{d["model"]}</b> ({d["size_h"]}). Andere Platten bleiben unberührt.',
                                         f'<b>Recommended:</b> Toravo OS goes onto the empty disk <b>{d["model"]}</b> ({d["size_h"]}). Other disks stay untouched.'))
            self.set_next(True)
        elif self.mode == 'alongside':
            other = 'Windows' if d['windows'] else tr('dem vorhandenen System', 'the existing system')
            self.disk_info.set_markup(tr(f'<b>Neben {other}:</b> Toravo nutzt nur den freien Platz ({d["free_h"]}). Beim Start wählst du, welches System startet. '
                                         'Vorhandene Partitionen werden nicht verändert.',
                                         f'<b>Next to {other}:</b> Toravo only uses the free space ({d["free_h"]}). At startup you choose which system boots. '
                                         'Existing partitions are not changed.'))
            self.set_next(True)
            self.add_erase_option(d)
        elif self.mode == 'erase':
            self.erase_confirm(d)
        else:
            free = tr(f' Es gibt nur {d["free_h"]} freien Platz (mindestens {D.MIN_GB} GB nötig).',
                      f' There is only {d["free_h"]} of free space (at least {D.MIN_GB} GB needed).') if d['free_h'] else ''
            hint = tr(' Tipp: In Windows unter „Datenträgerverwaltung → Volume verkleinern“ Platz freigeben, dann kann Toravo daneben.',
                      ' Tip: free up space in Windows under “Disk Management → Shrink Volume”, then Toravo fits next to it.') if d['windows'] else ''
            self.disk_info.set_markup(tr(f'Auf <b>{d["model"]}</b> ist schon etwas', f'<b>{d["model"]}</b> is not empty') +
                                      f' ({GLib.markup_escape_text(d["content"])}).{free}{hint}')
            self.set_next(False)
            self.add_erase_option(d)

    def add_erase_option(self, d):
        b = Gtk.Button(label=tr('Ganze Platte löschen und nur Toravo OS installieren …', 'Erase the whole disk and install only Toravo OS …'))
        b.add_css_class('tos-danger')
        b.set_halign(Gtk.Align.START)
        b.connect('clicked', lambda *_: (setattr(self, 'mode', 'erase'), self.describe()))
        self.erase_box.append(b)

    def erase_confirm(self, d):
        warn = tr(f'Achtung: Alles auf {d["model"]} ({d["size_h"]}) wird gelöscht', f'Warning: everything on {d["model"]} ({d["size_h"]}) will be erased')
        self.disk_info.set_markup(f'<span foreground="{theme.T["red"]}"><b>{warn}</b></span> – '
                                  f'{GLib.markup_escape_text(d["content"])}. ' + tr('Das kann nicht rückgängig gemacht werden.', 'This cannot be undone.'))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.add_css_class('tos-panel')
        inner = vbox(8, margin=16)
        inner.append(label(tr('Zum Bestätigen den Namen der Platte eintippen:', 'Type the disk name to confirm:') + f'  {d["name"]}', 'tos-body'))
        e = Gtk.Entry(placeholder_text=tr('Plattenname', 'Disk name'))
        e.connect('changed', lambda en: self.set_next(en.get_text().strip() == d['name'], danger=True))
        inner.append(e)
        cancel = Gtk.Button(label=tr('Doch nicht löschen', 'Don’t erase'))
        cancel.add_css_class('tos-link')
        cancel.set_halign(Gtk.Align.START)
        cancel.connect('clicked', lambda *_: (setattr(self, 'mode', 'empty' if d['empty'] else ('alongside' if d['can_alongside'] else None)), self.describe()))
        inner.append(cancel)
        box.append(inner)
        self.erase_box.append(box)
        self.confirm_entry = e
        self.set_next(False, danger=True)

    def set_next(self, ok, danger=False):
        nb = self.pages.get_child_by_name('disk').next_btn if self.pages.get_child_by_name('disk') else None
        if nb:
            nb.set_sensitive(ok)
            nb.set_label(tr('Löschen bestätigt – weiter', 'Erase confirmed – next') if danger else tr('Weiter', 'Next'))

    # -------------------------------------------------------------- 3 user
    def p_user(self):
        c = vbox(14)
        c.set_size_request(520, -1)
        c.set_halign(Gtk.Align.START)
        self.name_e = Gtk.Entry(placeholder_text=tr('Dein Name, z. B. Alex', 'Your name, e.g. Alex'))
        self.pw1 = Gtk.PasswordEntry(show_peek_icon=True)
        self.pw1.set_property('placeholder-text', tr('Passwort', 'Password'))
        self.pw2 = Gtk.PasswordEntry()
        self.pw2.set_property('placeholder-text', tr('Passwort wiederholen', 'Repeat password'))
        self.auto = Gtk.CheckButton(label=tr('Ohne Passwort-Abfrage starten (automatisch anmelden)', 'Start without asking for the password (log in automatically)'))
        self.user_hint = label('', 'tos-small')
        for w in (micro('NAME'), self.name_e, micro(tr('PASSWORT', 'PASSWORD')), self.pw1, self.pw2, self.auto, self.user_hint):
            c.append(w)
        for w in (self.name_e, self.pw1, self.pw2):
            w.connect('changed', lambda *_: self.validate_user())
        f = self.frame(3, tr('Wer bist du?', 'Who are you?'), tr('Nur Name und Passwort – den Rest macht Toravo.', 'Just name and password – Toravo does the rest.'), c,
                       back=lambda: self.pages.set_visible_child_name('disk'), nxt=self.start, nxt_label=tr('Installieren', 'Install'))
        self.inst_btn = f.next_btn
        self.inst_btn.set_sensitive(False)
        return f

    def go_user(self):
        self.pages.set_visible_child_name('user')
        self.name_e.grab_focus()

    def validate_user(self):
        n, p1, p2 = self.name_e.get_text().strip(), self.pw1.get_text(), self.pw2.get_text()
        msg, ok = '', False
        if n:
            login = login_from(n)
            msg = tr(f'Anmeldename: {login}  ·  Rechnername: {login}-toravo', f'Username: {login}  ·  Computer name: {login}-toravo')
        if p1 and len(p1) < 4:
            msg += tr('   ·   Passwort: mindestens 4 Zeichen', '   ·   Password: at least 4 characters')
        elif p1 and p2 and p1 != p2:
            msg += tr('   ·   Passwörter sind verschieden', '   ·   Passwords do not match')
        ok = bool(n and p1 and len(p1) >= 4 and p1 == p2)
        self.user_hint.set_text(msg)
        self.inst_btn.set_sensitive(ok)

    # -------------------------------------------------------------- 4 progress
    def p_progress(self):
        c = vbox(16)
        self.wave = Wave(bars=150, height=110, seed=9)
        c.append(self.wave)
        self.pmsg = label(tr('Starte …', 'Starting …'), 'tos-mono')
        c.append(self.pmsg)
        self.pct = label('0 %', 'tos-h1')
        c.append(self.pct)
        self.done_box = hbox(14)
        c.append(self.done_box)
        f = self.frame(0, tr('Toravo OS wird installiert …', 'Installing Toravo OS …'), tr('Lehn dich zurück. Das dauert ein paar Minuten.', 'Sit back. This takes a few minutes.'), c)
        self.prog_title = f.title_label
        return f

    def start(self):
        d = self.disk()
        n = self.name_e.get_text().strip()
        login = login_from(n)
        k = KEYBOARDS[self.ki]
        cfg = {'disk': d['path'], 'mode': self.mode, 'confirm': self.confirm_entry.get_text().strip() if self.mode == 'erase' else '',
               'fullname': n, 'user': login, 'password': self.pw1.get_text(), 'hostname': f'{login}-toravo',
               'autologin': self.auto.get_active(), 'lang': LANGS[self.li][0], 'keymap': k[2], 'xkb_layout': k[0], 'xkb_variant': k[1],
               'timezone': self.tz, 'hardware': self.hwinfo}
        rd = os.environ.get('XDG_RUNTIME_DIR', '/tmp')
        path = os.path.join(rd, 'toravo-install.json')
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as f:
            json.dump(cfg, f)
        self.pages.set_visible_child_name('progress')
        threading.Thread(target=self.worker, args=(path,), daemon=True).start()

    def worker(self, path):
        cmd = ['sudo', '-n', '/usr/lib/toravo/toravo-install-backend', path, '--json']
        if os.geteuid() == 0:
            cmd = cmd[2:]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        for line in p.stdout:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            GLib.idle_add(self.on_ev, ev)
        p.wait()

    def on_ev(self, ev):
        if ev.get('ev') == 'progress':
            self.wave.set_progress(ev['p'])
            self.pct.set_text(f'{int(ev["p"] * 100)} %')
            if ev.get('msg'):
                self.pmsg.set_text(ev['msg'])
        elif ev.get('ev') == 'done':
            if ev.get('ok'):
                self.wave.set_progress(1.0)
                self.pct.set_text(tr('Fertig.', 'Done.'))
                self.prog_title.set_text(tr('Toravo OS ist installiert.', 'Toravo OS is installed.'))
                self.pmsg.set_text(tr('Toravo OS ist installiert. Stick abziehen und neu starten – beim ersten Start richtet Toravo Setup deine KI-Werkzeuge ein.',
                                       'Toravo OS is installed. Remove the USB stick and restart – on first start Toravo Setup sets up your AI tools.'))
                rb = Gtk.Button(label=tr('Neu starten', 'Restart'))
                rb.add_css_class('tos-primary')
                rb.connect('clicked', lambda *_: subprocess.Popen(['systemctl', 'reboot']))
                tb = Gtk.Button(label=tr('Weiter ausprobieren', 'Keep trying it'))
                tb.add_css_class('tos-big')
                tb.connect('clicked', lambda *_: self.close())
                self.done_box.append(rb)
                self.done_box.append(tb)
            else:
                self.pct.set_text(tr('Abgebrochen', 'Aborted'))
                self.pct.add_css_class('tos-warn')
                self.pmsg.set_text(tr('Fehler: ', 'Error: ') + ev.get('msg', '') + tr('  (Protokoll: /var/log/toravo-install.log)', '  (log: /var/log/toravo-install.log)'))
                bb = Gtk.Button(label=tr('Zurück', 'Back'))
                bb.add_css_class('tos-big')
                bb.connect('clicked', lambda *_: self.pages.set_visible_child_name('disk'))
                self.done_box.append(bb)
        return False


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='de.toravo.Installer', flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_activate(self):
        if self.get_windows():
            self.get_windows()[0].present()
            return
        theme.apply_css(CSS)
        w = Installer(self, '--welcome' in sys.argv)
        w.present()
        page = next((a.split('=')[1] for a in sys.argv if a.startswith('--page=')), None)
        if page == 'disk':
            w.go_disk()
        elif page == 'user':
            w.go_disk()
            w.go_user()


CSS = f"""
.tos-tile .tos-h1 {{ font-size: 26px; }}
menubutton.tos-link > button {{ background: none; border: none; color: {theme.T['text3']}; padding: 2px 6px; font-size: 12px; }}
menubutton.tos-link > button:hover {{ color: {theme.T['violet']}; }}
"""


def main():
    App().run([sys.argv[0]])


if __name__ == '__main__':
    main()
