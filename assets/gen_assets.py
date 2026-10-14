#!/usr/bin/env python3
"""Toravo OS – erzeugt alle Bild-Assets aus den Design-Tokens (brand/tokens.css).

Laeuft im Build-Container (Arch, python-pillow, inter-font). Ausgabe: <out>/...
  wallpaper/toravo-{3840x2160,2560x1440,1920x1080}.png  Desktop (dunkel + violetter Glow + kleine Wortmarke)
  wallpaper/toravo-lock.png                              Lockscreen/Greeter-Hintergrund
  logo/toravo-t-{512,256,128,64,48,32}.png               "T"-Logo (abgerundetes Quadrat, violetter Glow)
  logo/toravo-wordmark.png                               TORAVO/OS + Claim
  plymouth/{background.png,wave-00..49.png,entry.png,bullet.png,lock.png}
  syslinux/splash.png                                    640x480 BIOS-Bootmenue
  slides/                                                (Vorschau-Bilder fuer README)
"""
import math, os, random, sys
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageChops

OUT = sys.argv[1] if len(sys.argv) > 1 else 'out-assets'
INTER = '/usr/share/fonts/inter/InterVariable.ttf'
MONO = '/usr/share/fonts/TTF/JetBrainsMono-Regular.ttf'

BG = (7, 7, 13); BG2 = (12, 12, 20); PANEL = (18, 17, 28); PANEL2 = (24, 22, 38); LINE = (36, 33, 58)
GLOW = (73, 49, 127); TEXT = (242, 242, 247); TEXT2 = (169, 168, 189); TEXT3 = (108, 106, 133)
VIOLET = (138, 92, 246); BLUE = (111, 155, 224); CYAN = (90, 176, 208); CORAL = (216, 128, 106)
TEAL_GLOW = (22, 58, 70)


def font(size, wght=400, path=INTER):
    f = ImageFont.truetype(path, size)
    try:
        axes = f.get_variation_axes()
        vals = []
        for ax in axes:
            name = ax.get('name', b'')
            name = name.decode() if isinstance(name, bytes) else str(name)
            vals.append(wght if 'eight' in name else (min(max(size, ax['minimum']), ax['maximum']) if 'ptical' in name else ax['default']))
        f.set_variation_by_axes(vals)
    except Exception:
        pass
    return f


def grad_color(t):
    """Verlauf violett -> blau (55 %) -> cyan."""
    t = max(0.0, min(1.0, t))
    if t < .55:
        a, b, u = VIOLET, BLUE, t / .55
    else:
        a, b, u = BLUE, CYAN, (t - .55) / .45
    return tuple(int(a[i] + (b[i] - a[i]) * u) for i in range(3))


def glow_layer(size, blobs, scale=8):
    """Weiche Lichtwolken: auf kleiner Flaeche zeichnen, stark weichzeichnen, hochskalieren."""
    w, h = size
    sw, sh = max(1, w // scale), max(1, h // scale)
    img = Image.new('RGB', (sw, sh), BG)
    for (cx, cy, rx, ry, color, strength) in blobs:
        layer = Image.new('RGB', (sw, sh), (0, 0, 0))
        d = ImageDraw.Draw(layer)
        x, y, a, b = cx * sw, cy * sh, rx * sw, ry * sh
        c = tuple(int(v * strength) for v in color)
        d.ellipse([x - a, y - b, x + a, y + b], fill=c)
        layer = layer.filter(ImageFilter.GaussianBlur(radius=max(a, b) * .45))
        img = ImageChops.add(img, layer)
    img = img.filter(ImageFilter.GaussianBlur(radius=2))
    img = img.resize((w, h), Image.BICUBIC)
    return add_noise(img, 2)


def add_noise(img, amount):
    """Leichtes Rauschen gegen Banding im dunklen Verlauf."""
    rnd = random.Random(7)
    w, h = img.size
    n = Image.new('L', (w // 2, h // 2))
    n.putdata([128 + rnd.randint(-amount, amount) for _ in range((w // 2) * (h // 2))])
    n = n.resize((w, h), Image.NEAREST)
    noise = Image.merge('RGB', (n, n, n))
    return ImageChops.add(img, noise, 1.0, -128)


def spaced_text(draw, xy, text, fnt, fill, tracking, anchor_center=False):
    """Text mit Sperrung (tracking in em)."""
    em = fnt.size
    widths = [draw.textlength(ch, font=fnt) for ch in text]
    total = sum(widths) + tracking * em * (len(text) - 1)
    x, y = xy
    if anchor_center:
        x -= total / 2
    for ch, cw in zip(text, widths):
        draw.text((x, y), ch, font=fnt, fill=fill)
        x += cw + tracking * em
    return total


def text_width(fnt, text, tracking):
    d = ImageDraw.Draw(Image.new('L', (1, 1)))
    return sum(d.textlength(ch, font=fnt) for ch in text) + tracking * fnt.size * (len(text) - 1)


def wordmark(draw, cx, y, size, claim=True, alpha=1.0):
    """TORAVO/OS – gesperrte Versalien, Schraegstrich violett; Claim darunter."""
    f = font(size, 640)
    tr = .34
    parts = [('TORAVO', TEXT), ('/', VIOLET), ('OS', TEXT)]
    total = sum(text_width(f, p, tr) for p, _ in parts) + tr * size * 2
    x = cx - total / 2
    def col(c):
        return tuple(int(v * alpha + BG[i] * (1 - alpha)) for i, v in enumerate(c))
    for p, c in parts:
        w = spaced_text(draw, (x, y), p, f, col(c), tr)
        x += w + tr * size
    if claim:
        fc = font(max(8, int(size * .26)), 500)
        spaced_text(draw, (cx, y + size * 1.38), 'THE AI CONTENT CREATOR OS', fc, col(TEXT3), .42, anchor_center=True)


def t_logo(px, glow=True):
    """Abgerundetes dunkles Quadrat mit 'T' im Verlauf + violetter Glow. Liefert RGBA (Kantenlaenge px*2 bei glow)."""
    pad = px // 2 if glow else 0
    W = px + 2 * pad
    img = Image.new('RGBA', (W, W), (0, 0, 0, 0))
    if glow:
        g = Image.new('RGBA', (W, W), (0, 0, 0, 0))
        gd = ImageDraw.Draw(g)
        gd.rounded_rectangle([pad - px * .1, pad - px * .1, pad + px * 1.1, pad + px * 1.1], radius=px * .3, fill=VIOLET + (150,))
        g = g.filter(ImageFilter.GaussianBlur(px * .28))
        img = Image.alpha_composite(img, g)
    box = Image.new('RGBA', (W, W), (0, 0, 0, 0))
    bd = ImageDraw.Draw(box)
    r = px * .22
    bd.rounded_rectangle([pad, pad, pad + px - 1, pad + px - 1], radius=r, fill=(26, 23, 44, 255), outline=(52, 46, 84, 255), width=max(1, px // 64))
    img = Image.alpha_composite(img, box)
    # T als Maske, gefuellt mit vertikalem Verlauf (violett oben -> blau unten, wie im Trailer)
    f = font(int(px * .56), 760)
    mask = Image.new('L', (W, W), 0)
    md = ImageDraw.Draw(mask)
    md.text((W / 2, W / 2 + px * .02), 'T', font=f, fill=255, anchor='mm')
    fill = Image.new('RGBA', (W, W))
    fd = ImageDraw.Draw(fill)
    for yy in range(W):
        t = (yy - pad) / max(1, px)
        c = tuple(int(VIOLET[i] * (1 - t) * .35 + BLUE[i] * (.65 + .35 * t)) for i in range(3)) if 0 <= t <= 1 else BLUE
        fd.line([(0, yy), (W, yy)], fill=c + (255,))
    img.paste(fill, (0, 0), mask)
    return img


def waveform_bars(n, seed=3):
    rnd = random.Random(seed)
    vals = []
    for i in range(n):
        t = i / n
        env = .35 + .65 * abs(math.sin(t * math.pi * 3.2 + .4)) * (.6 + .4 * math.sin(t * 17))
        vals.append(max(.12, min(1.0, env * (.55 + .45 * rnd.random()))))
    return vals


def draw_wave(img, box, progress=1.0, bars=96, seed=3, dim=(46, 42, 74), mirror=True):
    x0, y0, x1, y1 = box
    d = ImageDraw.Draw(img)
    vals = waveform_bars(bars, seed)
    bw = (x1 - x0) / bars
    cy = (y0 + y1) / 2
    hmax = (y1 - y0) / 2
    for i, v in enumerate(vals):
        t = i / (bars - 1)
        lit = t <= progress
        c = grad_color(t) if lit else dim
        x = x0 + i * bw + bw * .2
        h = max(1.5, v * hmax)
        d.rounded_rectangle([x, cy - h, x + max(1.0, bw * .55), cy + h], radius=max(1, bw * .25), fill=c)


def wallpaper(w, h, path, lock=False):
    blobs = [
        (.52, -.02 if not lock else .36, .34, .30, GLOW, .62),  # violetter Lichtkegel oben
        (.80, -.04, .18, .14, (60, 40, 110), .35),
        (.04, 1.02, .22, .18, TEAL_GLOW, .55),                  # kalter Rest unten links (Trailer)
    ]
    img = glow_layer((w, h), blobs)
    d = ImageDraw.Draw(img)
    if lock:
        pass  # Uhr/Claim zeichnet hyprlock live
    else:
        s = h / 1080
        wordmark(d, w / 2, h - 46 * s, int(13 * s), claim=False, alpha=.45)
    img.save(path, optimize=True)


def plymouth(outdir):
    os.makedirs(outdir, exist_ok=True)
    W, H = 1920, 1080
    img = glow_layer((W, H), [(.5, .42, .20, .26, GLOW, .78), (.70, .16, .12, .10, (55, 38, 100), .35),
                              (.06, 1.0, .20, .16, TEAL_GLOW, .55)])
    img = img.convert('RGBA')
    logo = t_logo(104)
    img.alpha_composite(logo, (W // 2 - logo.width // 2, 400 - logo.height // 2))
    d = ImageDraw.Draw(img)
    wordmark(d, W / 2, 492, 50)
    img.convert('RGB').save(os.path.join(outdir, 'background.png'), optimize=True)
    # Wellenform-Fortschritt: 50 Stufen
    for k in range(50):
        wv = Image.new('RGBA', (360, 44), (0, 0, 0, 0))
        draw_wave(wv, (0, 2, 360, 42), progress=k / 49, bars=72, seed=11, dim=(44, 40, 72))
        wv.save(os.path.join(outdir, 'wave-%02d.png' % k), optimize=True)
    # Passwort-Eingabe (fuer verschluesselte Systeme) – schlichtes Panel
    e = Image.new('RGBA', (420, 52), (0, 0, 0, 0))
    ImageDraw.Draw(e).rounded_rectangle([0, 0, 419, 51], radius=12, fill=PANEL + (255,), outline=LINE + (255,), width=1)
    e.save(os.path.join(outdir, 'entry.png'))
    b = Image.new('RGBA', (12, 12), (0, 0, 0, 0))
    ImageDraw.Draw(b).ellipse([1, 1, 10, 10], fill=VIOLET + (255,))
    b.save(os.path.join(outdir, 'bullet.png'))
    t_logo(40, glow=False).save(os.path.join(outdir, 'lock.png'))


def syslinux_splash(path):
    W, H = 640, 480
    img = glow_layer((W, H), [(.5, .26, .30, .30, GLOW, .75), (.05, 1.0, .25, .2, TEAL_GLOW, .5)], scale=4).convert('RGBA')
    logo = t_logo(40)
    img.alpha_composite(logo, (W // 2 - logo.width // 2, 70 - logo.height // 2 + 10))
    d = ImageDraw.Draw(img)
    wordmark(d, W / 2, 112, 20)
    img.convert('RGB').save(path)


def wordmark_png(path):
    W, H = 900, 200
    img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    wordmark(ImageDraw.Draw(img), W / 2, 60, 56)
    img.save(path)


def main():
    for sub in ('wallpaper', 'logo', 'plymouth', 'syslinux'):
        os.makedirs(os.path.join(OUT, sub), exist_ok=True)
    for w, h in ((3840, 2160), (2560, 1440), (1920, 1080)):
        wallpaper(w, h, os.path.join(OUT, 'wallpaper', 'toravo-%dx%d.png' % (w, h)))
    wallpaper(2560, 1440, os.path.join(OUT, 'wallpaper', 'toravo-lock.png'), lock=True)
    for s in (512, 256, 128, 64, 48, 32):
        t_logo(s, glow=False).save(os.path.join(OUT, 'logo', 'toravo-t-%d.png' % s))
    t_logo(160).save(os.path.join(OUT, 'logo', 'toravo-t-glow.png'))
    wordmark_png(os.path.join(OUT, 'logo', 'toravo-wordmark.png'))
    plymouth(os.path.join(OUT, 'plymouth'))
    syslinux_splash(os.path.join(OUT, 'syslinux', 'splash.png'))
    print('assets ok ->', OUT)


if __name__ == '__main__':
    main()
