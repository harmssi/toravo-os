"""Desktop widget (layer-shell, background): big clock + claim like the trailer ("15:42 / THE AI CONTENT CREATOR OS")."""
import sys, time
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib, Gio
from . import theme
try:
    gi.require_version('Gtk4LayerShell', '1.0')
    from gi.repository import Gtk4LayerShell as LS
except (ValueError, ImportError):
    LS = None


class Desk(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='de.toravo.Desk', flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_activate(self):
        theme.apply_css('window.tos-transparent, window.tos-transparent > * { background: transparent; }')
        w = Gtk.ApplicationWindow(application=self)
        w.add_css_class('tos-transparent')
        if LS and LS.is_supported():
            LS.init_for_window(w)
            LS.set_layer(w, LS.Layer.BOTTOM)
            LS.set_namespace(w, 'toravo-desk')
            LS.set_anchor(w, LS.Edge.TOP, True)
            LS.set_margin(w, LS.Edge.TOP, 120)
            LS.set_keyboard_mode(w, LS.KeyboardMode.NONE)
            LS.set_exclusive_zone(w, -1)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.clock = Gtk.Label()
        self.clock.add_css_class('tos-clock')
        claim = Gtk.Label()
        claim.set_markup(f'<span letter_spacing="{int(11 * 1024 * .42)}" size="11264" weight="500" foreground="{theme.T["text3"]}">'
                         'THE AI CONTENT CREATOR OS</span>')
        hint = Gtk.Label()
        hint.set_markup(f'<span size="10240" foreground="{theme.T["text3"]}"><span font_family="JetBrains Mono" foreground="{theme.T["violet"]}">'
                        f'Super + Leertaste</span>   Sag einfach, was du willst.</span>')
        hint.set_margin_top(18)
        box.append(self.clock)
        box.append(claim)
        box.append(hint)
        w.set_child(box)
        self.tick()
        GLib.timeout_add_seconds(1, self.tick)
        w.present()

    def tick(self):
        self.clock.set_text(time.strftime('%H:%M'))
        return True


def main():
    Desk().run([sys.argv[0]])


if __name__ == '__main__':
    main()
