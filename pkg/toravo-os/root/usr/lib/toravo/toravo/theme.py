"""Toravo OS design tokens (brand/tokens.css) + GTK4 stylesheet shared by all Toravo apps."""
import os

TOKENS = {
    'bg': '#07070d', 'bg2': '#0c0c14', 'panel': '#12111c', 'panel2': '#181626', 'line': '#24213a', 'glow': '#49317f',
    'text': '#f2f2f7', 'text2': '#a9a8bd', 'text3': '#6c6a85',
    'violet': '#8a5cf6', 'blue': '#6f9be0', 'cyan': '#5ab0d0', 'coral': '#d8806a', 'red': '#e5484d', 'green': '#4cc38a',
}
GRADIENT = ((0.0, '#8a5cf6'), (0.55, '#6f9be0'), (1.0, '#5ab0d0'))
SHARE = '/usr/share/toravo'
LOGO = SHARE + '/logo/toravo-t-128.png'
LOGO_GLOW = SHARE + '/logo/toravo-t-glow.png'


def rgb(hexcol):
    h = hexcol.lstrip('#')
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def grad_at(t):
    t = max(0.0, min(1.0, t))
    for (a, ca), (b, cb) in zip(GRADIENT, GRADIENT[1:]):
        if t <= b:
            u = (t - a) / (b - a)
            x, y = rgb(ca), rgb(cb)
            return tuple(x[i] + (y[i] - x[i]) * u for i in range(3))
    return rgb(GRADIENT[-1][1])


def lang():
    l = (os.environ.get('LANG') or os.environ.get('LC_ALL') or 'de').lower()
    return 'de' if l.startswith('de') or l in ('c', 'c.utf-8', 'posix') else 'en'


def tr(de, en):
    """Tiny i18n: German default, English for non-German locales."""
    return de if lang() == 'de' else en


T = TOKENS
CSS = f"""
* {{ font-family: "Inter", "Inter Variable", sans-serif; }}
window, .tos-root {{ background-color: {T['bg']}; color: {T['text']}; }}
window.tos-transparent {{ background-color: transparent; }}
.tos-panel {{ background-color: {T['panel']}; border: 1px solid {T['line']}; border-radius: 12px; }}
.tos-panel2 {{ background-color: {T['panel2']}; border: 1px solid {T['line']}; border-radius: 12px; }}
.tos-label {{ color: {T['text3']}; font-size: 11px; font-weight: 600; letter-spacing: 3.5px; }}
.tos-label-violet {{ color: {T['violet']}; font-size: 11px; font-weight: 600; letter-spacing: 3.5px; }}
.tos-label-cyan {{ color: {T['cyan']}; font-size: 11px; font-weight: 600; letter-spacing: 3.5px; }}
.tos-label-coral {{ color: {T['coral']}; font-size: 11px; font-weight: 600; letter-spacing: 3.5px; }}
.tos-hero {{ font-size: 44px; font-weight: 800; letter-spacing: -1px; color: {T['text']}; }}
.tos-h1 {{ font-size: 30px; font-weight: 800; letter-spacing: -0.5px; color: {T['text']}; }}
.tos-h2 {{ font-size: 19px; font-weight: 700; color: {T['text']}; }}
.tos-body {{ font-size: 15px; color: {T['text2']}; }}
.tos-small {{ font-size: 12px; color: {T['text3']}; }}
.tos-mono {{ font-family: "JetBrains Mono", monospace; font-size: 12px; color: {T['text2']}; }}
.tos-clock {{ font-size: 112px; font-weight: 300; color: {T['text']}; letter-spacing: -2px; }}
.tos-ok {{ color: {T['green']}; }}
.tos-warn {{ color: {T['coral']}; }}
.tos-err {{ color: {T['red']}; }}
.tos-dim {{ color: {T['text3']}; }}
.tos-chip {{ background-color: {T['panel2']}; border: 1px solid {T['line']}; border-radius: 6px; padding: 1px 7px;
             font-family: "JetBrains Mono", monospace; font-size: 10px; color: {T['text3']}; }}
button {{ background-image: none; background-color: {T['panel2']}; color: {T['text']}; border: 1px solid {T['line']};
          border-radius: 10px; padding: 8px 16px; box-shadow: none; text-shadow: none; }}
button:hover {{ background-color: #201d33; border-color: #3a3560; }}
button:focus-visible {{ outline: 2px solid {T['violet']}; outline-offset: 1px; }}
button.tos-primary {{ background-image: linear-gradient(90deg, #8a5cf6 0%, #6f9be0 55%, #5ab0d0 100%);
          color: #ffffff; border: none; font-weight: 700; font-size: 17px; padding: 14px 30px; border-radius: 12px; }}
button.tos-primary:hover {{ background-image: linear-gradient(90deg, #9a70ff 0%, #80aaf0 55%, #6bc0e0 100%); }}
button.tos-primary:disabled {{ background-image: none; background-color: {T['panel2']}; color: {T['text3']}; }}
button.tos-big {{ font-size: 17px; font-weight: 600; padding: 14px 30px; border-radius: 12px; }}
button.tos-danger {{ background-color: #2a1216; color: #ffb4b6; border: 1px solid #5c2128; font-weight: 700; }}
button.tos-danger:hover {{ background-color: #3a161b; }}
button.tos-link {{ background: none; border: none; color: {T['text3']}; padding: 2px 6px; font-size: 12px; }}
button.tos-link:hover {{ color: {T['violet']}; }}
button.tos-tile {{ background-color: {T['panel']}; border: 1px solid {T['line']}; border-radius: 14px; padding: 18px 20px; }}
button.tos-tile:hover {{ background-color: {T['panel2']}; border-color: #3a3560; }}
button.tos-tile.selected {{ border: 2px solid {T['violet']}; background-color: #17142a; }}
button.tos-tile:disabled {{ opacity: 0.45; }}
entry, .tos-entry {{ background-color: {T['bg2']}; color: {T['text']}; border: 1px solid {T['line']}; border-radius: 10px;
          padding: 10px 14px; font-size: 16px; caret-color: {T['violet']}; box-shadow: none; }}
entry:focus-within {{ border-color: {T['violet']}; }}
entry.tos-cmd {{ background-color: transparent; border: none; font-size: 17px; padding: 6px 2px; }}
checkbutton, switch {{ color: {T['text2']}; }}
switch {{ background-color: {T['panel2']}; border: 1px solid {T['line']}; }}
switch:checked {{ background-color: {T['violet']}; }}
switch slider {{ background-color: {T['text']}; }}
check {{ background-color: {T['bg2']}; border: 1px solid {T['line']}; }}
check:checked {{ background-color: {T['violet']}; border-color: {T['violet']}; color: white; }}
list, listview, .tos-list {{ background-color: transparent; }}
list row, listview row {{ background-color: transparent; border-radius: 8px; padding: 6px 10px; }}
list row:selected, listview row:selected {{ background-color: {T['panel2']}; box-shadow: inset 2px 0 0 {T['violet']}; }}
list row:hover {{ background-color: #15131f; }}
scrollbar {{ background: transparent; }}
scrollbar slider {{ background-color: {T['line']}; border-radius: 4px; min-width: 4px; }}
textview, textview text {{ background-color: {T['bg2']}; color: {T['text2']}; font-family: "JetBrains Mono", monospace; font-size: 11px; }}
dropdown button, combobox button {{ padding: 6px 10px; }}
popover contents, popover > arrow {{ background-color: {T['panel']}; border: 1px solid {T['line']}; color: {T['text']}; }}
separator {{ background-color: {T['line']}; min-height: 1px; }}
progressbar trough {{ background-color: {T['panel2']}; min-height: 4px; border-radius: 2px; }}
progressbar progress {{ background-image: linear-gradient(90deg, #8a5cf6, #6f9be0 55%, #5ab0d0); border-radius: 2px; min-height: 4px; }}
.tos-dot-live {{ color: {T['red']}; }}
.tos-step-icon {{ color: {T['violet']}; font-family: "JetBrains Mono", monospace; }}
"""


def apply_css(extra=''):
    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Gdk', '4.0')
    from gi.repository import Gtk, Gdk
    prov = Gtk.CssProvider()
    data = CSS + extra
    if hasattr(prov, 'load_from_string'):
        prov.load_from_string(data)
    else:
        prov.load_from_data(data.encode(), -1)
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 10)
    settings = Gtk.Settings.get_default()
    if settings is not None:
        settings.set_property('gtk-application-prefer-dark-theme', True)


def wordmark_markup(size_pt=13, claim=False):
    """Pango markup for TORAVO/OS with letter spacing; slash in violet."""
    sp = int(size_pt * 1024 * 0.34)
    m = (f'<span font_family="Inter" font_weight="semibold" size="{size_pt * 1024}" letter_spacing="{sp}" foreground="{T["text"]}">TORAVO'
         f'<span foreground="{T["violet"]}">/</span>OS</span>')
    if claim:
        cs = max(7, int(size_pt * .32))
        m += (f'\n<span font_family="Inter" font_weight="medium" size="{cs * 1024}" letter_spacing="{int(cs * 1024 * .45)}" '
              f'foreground="{T["text3"]}">THE AI CONTENT CREATOR OS</span>')
    return m


def software_rendering():
    """True if we run without real 3D (VM/llvmpipe) – set by toravo-session in TORAVO_LITE."""
    return os.environ.get('TORAVO_LITE') == '1'
