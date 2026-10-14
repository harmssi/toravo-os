"""toravo-studio [page] – starts the local Studio server (if needed) and opens it in its own window (WebKitGTK)."""
import os, subprocess, sys, time, urllib.request

URL = 'http://127.0.0.1:8890/'


def up():
    try:
        urllib.request.urlopen(URL + 'api/ping', timeout=1).read()
        return True
    except OSError:
        return False


def ensure_server():
    if up():
        return True
    if subprocess.run(['systemctl', '--user', 'start', 'toravo-studio.service'], capture_output=True).returncode != 0:
        subprocess.Popen([sys.executable, '-m', 'toravo.studio.server'], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        if up():
            return True
        time.sleep(.1)
    return False


def main():
    page = sys.argv[1] if len(sys.argv) > 1 else ''
    if not ensure_server():
        from ..theme import tr
        subprocess.Popen(['notify-send', '-a', 'Toravo', tr('Studio startet nicht', 'Studio does not start'),
                          tr('Siehe journalctl --user -u toravo-studio', 'See journalctl --user -u toravo-studio')])
        return
    url = URL + ('#' + page if page else '')
    try:
        import gi
        gi.require_version('Gtk', '4.0')
        gi.require_version('WebKit', '6.0')
        from gi.repository import Gtk, WebKit, Gio
    except (ValueError, ImportError):
        subprocess.Popen(['xdg-open', url])
        return

    class App(Gtk.Application):
        def __init__(self):
            super().__init__(application_id='de.toravo.Studio', flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
            self.view = None

        def do_command_line(self, cl):
            args = cl.get_arguments()
            pg = args[1] if len(args) > 1 else ''
            if self.view:
                self.view.evaluate_javascript(f"location.hash='{pg}'", -1, None, None, None, None, None)
                self.get_windows()[0].present()
                return 0
            w = Gtk.ApplicationWindow(application=self, title='Toravo Studio')
            w.set_default_size(1440, 900)
            self.view = WebKit.WebView()
            s = self.view.get_settings()
            s.set_property('enable-developer-extras', False)
            bg = __import__('gi.repository.Gdk', fromlist=['RGBA']).RGBA()
            bg.parse('#07070d')
            self.view.set_background_color(bg)
            self.view.load_uri(URL + ('#' + pg if pg else ''))
            w.set_child(self.view)
            w.present()
            return 0

    App().run([sys.argv[0]] + ([page] if page else []))


if __name__ == '__main__':
    main()
