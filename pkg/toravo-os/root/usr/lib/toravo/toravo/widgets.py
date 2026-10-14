"""Shared GTK4 widgets in the trailer look: waveform progress, logo, wordmark, labels."""
import math, os, random
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib
from . import theme


class Wave(Gtk.DrawingArea):
    """Waveform used as progress bar (lit part = violet->blue->cyan gradient, rest dim). progress=None -> animated idle."""

    def __init__(self, bars=96, height=56, seed=3, progress=0.0, animate=False):
        super().__init__()
        self.set_content_height(height)
        self.set_hexpand(True)
        rnd = random.Random(seed)
        self.vals = []
        for i in range(bars):
            t = i / bars
            env = .35 + .65 * abs(math.sin(t * math.pi * 3.2 + .4)) * (.6 + .4 * math.sin(t * 17))
            self.vals.append(max(.12, min(1.0, env * (.55 + .45 * rnd.random()))))
        self.progress = progress
        self.phase = 0.0
        self.set_draw_func(self._draw)
        if animate:
            GLib.timeout_add(60, self._tick)

    def _tick(self):
        self.phase += .07
        self.queue_draw()
        return True

    def set_progress(self, p):
        self.progress = max(0.0, min(1.0, p))
        self.queue_draw()

    def _draw(self, area, cr, w, h):
        if self.phase:  # running without known progress: a sweep moves through the wave
            self.progress = (self.phase * .35) % 1.0
        n = len(self.vals)
        bw = w / n
        cy = h / 2
        dim = theme.rgb('#2e2a4a')
        for i, v in enumerate(self.vals):
            t = i / max(1, n - 1)
            if self.phase:
                v = v * (.75 + .25 * math.sin(self.phase * 3 + i * .45))
            lit = t <= self.progress
            cr.set_source_rgb(*(theme.grad_at(t) if lit else dim))
            hh = max(1.5, v * (h / 2 - 1))
            x = i * bw + bw * .2
            ww = max(1.0, bw * .55)
            r = min(ww / 2, 2)
            # rounded bar
            cr.new_sub_path()
            cr.arc(x + ww - r, cy - hh + r, r, -math.pi / 2, 0)
            cr.arc(x + ww - r, cy + hh - r, r, 0, math.pi / 2)
            cr.arc(x + r, cy + hh - r, r, math.pi / 2, math.pi)
            cr.arc(x + r, cy - hh + r, r, math.pi, 3 * math.pi / 2)
            cr.close_path()
            cr.fill()


def logo(size=64, glow=False):
    path = theme.LOGO_GLOW if glow else theme.LOGO
    if not os.path.exists(path):
        lab = Gtk.Label(label='T')
        lab.add_css_class('tos-h1')
        return lab
    img = Gtk.Image.new_from_file(path)
    img.set_pixel_size(size)
    img.set_halign(Gtk.Align.CENTER)
    img.set_valign(Gtk.Align.CENTER)
    return img


def wordmark(size_pt=13, claim=False, halign=Gtk.Align.CENTER):
    lab = Gtk.Label()
    lab.set_markup(theme.wordmark_markup(size_pt, claim))
    lab.set_justify(Gtk.Justification.CENTER)
    lab.set_halign(halign)
    return lab


def label(text, css='tos-body', wrap=False, xalign=0.0, markup=False):
    lab = Gtk.Label()
    if markup:
        lab.set_markup(text)
    else:
        lab.set_text(text)
    for c in css.split():
        lab.add_css_class(c)
    lab.set_xalign(xalign)
    if wrap:
        lab.set_wrap(True)
        lab.set_max_width_chars(70)
    return lab


def micro(text, color=''):
    """Uppercase micro label with 0.32em tracking ('COMMAND BAR', 'YuE2 · LOCAL')."""
    return label(text.upper() if text.islower() else text, 'tos-label' + ('-' + color if color else ''))


def chip(text):
    return label(text, 'tos-chip')


def vbox(spacing=12, *children, margin=0):
    b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
    for c in children:
        b.append(c)
    if margin:
        for m in ('top', 'bottom', 'start', 'end'):
            getattr(b, 'set_margin_' + m)(margin)
    return b


def hbox(spacing=12, *children):
    b = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=spacing)
    for c in children:
        b.append(c)
    return b


def spacer(v=True):
    s = Gtk.Box()
    (s.set_vexpand if v else s.set_hexpand)(True)
    return s
