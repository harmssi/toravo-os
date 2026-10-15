# Changelog – Toravo OS

## 0.1.6 – 2026-10-15 (Toravo Companion)

Anlass: Owner „Wie geil wäre das wenn unsere OS eine eigene Companion App hat“ → „eine echte app“.

- **Toravo Companion**: native iPhone-App (SwiftUI, iOS 27, `apps/ios/ToravoCompanion`) – Render-Queue + GPU live, Command Bar vom Handy
  (Plan ansehen → am PC starten), Jobs pausieren/fortsetzen/abbrechen, fertige Shorts/Videos/Thumbnails ansehen, in Fotos sichern oder teilen,
  Mitteilung bei fertigem Job (solange die App offen ist; im Hintergrund nach iOS-Ermessen). Zugeklappt eine Spalte, aufgeklappt (iPhone Duo)
  Queue links, Vorschau rechts (Breite + Scharnier-API von iOS 27.1). Noch nicht im App Store.
- Dienst `toravo-companion` (Benutzerdienst, Port 8891, standardmäßig aus): HTTPS mit eigenem Zertifikat, Kopplung per QR-Code (Einmal-Code,
  10 min), Gerätetoken (nur als SHA-256 gespeichert, im Studio widerrufbar), Schlüssel-Pinning in der App, nur private Netze, Rate-Limits,
  Bonjour `_toravo._tcp` (mit avahi), Livestreams nicht vom Handy startbar. CLI `toravo-companion`. Doku `docs/COMPANION.md`.
- Studio Local: „Handy verbinden“ (QR, Geräte, Aus-Schalter), Zustand „pausiert“ in der Queue. Neue Abhängigkeit `qrencode`.
- Tests: `tests/test_companion.py` (47, echte HTTPS-Tests), App-Unit-Tests + UI-Tests im iPhone-Duo-Simulator.

## Unveröffentlicht (14.10.2026)

- **Toravo Update** (0.1.1): eigenes signiertes Repo `[toravo]` auf GitHub Releases + Paket `toravo-keyring`; Kanäle stable
  (getestetes Arch-Archive-Datum per signiertem Manifest) und rolling; Download im Leerlauf (Queue leer, kein Stream, Netzteil),
  Offline-Installation beim Neustart, Snapshot `@rollback` + snap-pac, Kernel/NVIDIA nur gemeinsam, Boot-Prüfung (One-Shot-Eintrag +
  „vorherige Version“) und Health-Check mit automatischem Rollback, Seite „Updates“, Waybar-Hinweis, optionale KI-Modell-Updates.
  Release-Werkzeuge `scripts/release.sh`, `release-test.sh` (Wegwerf-VM), Doku `docs/UPDATES.md`.
- Sprache: alle eigenen Oberflächen zweisprachig (Deutsch für `de_*`, sonst Englisch) – Command Bar, Desktop-Uhr, Toravo Setup,
  Installer (folgt der gewählten Sprache sofort), Studio Local (`<html lang>` vom Server, Texttabelle in `app.js`), Render-Queue,
  Waybar-Tooltips, Power-Menü, labwc-Menü, Greeter-Begrüßung, Benachrichtigungen, `.desktop`-Dateien (`Name[de]`), polkit,
  `ai-stack.json` (`title_en`/`label_en`/`note_en`/`license_en`). Die Sitzung lädt `~/.config/locale.conf` bzw. `/etc/locale.conf`
  (`/usr/lib/toravo/locale.sh`), `TORAVO_LANG` überschreibt. Live-ISO: neuer Starteintrag „Toravo OS (English)“
  (`locale.LANG=en_US.UTF-8`, US-Tastatur); Standard bleibt Deutsch.
- Build: `BUILD_MODE=native` in `build.sh` – mkarchiso direkt auf einer Arch-basierten Build-Maschine (ohne Docker);
  `scripts/container-build.sh` nimmt den Arbeitsordner aus `BUILD_ROOT` (Standard `/build`). Getestet: ISO nativ in einer
  Toravo-OS-VM gebaut, bootet live bis zum Installer.
- `scripts/pve-testvm.sh`: Wegwerf-Test-VMs auf Proxmox VE für Boot- und Installer-Tests.
- Command Bar / Agent: plant das lokale Modell „short 1/2/3“ als drei Einzelschritte, werden sie jetzt zu einem Shorts-Schritt
  mit der gewünschten Anzahl zusammengefasst (vorher schnitt jeder Job denselben Moment in dieselbe Datei – aus 3 Shorts wurde 1).

## 0.1.0 – 2026-10-14 (Phase 1+, erstes bootbares ISO)

Ziel (14.10.): „Arch Linux Distro mit Wayland und Hyprland … total cool … unser ganzer KI-Kram integriert wie im Video …
das perfekte OS für KI-Content-Produktion“; Ergänzungen am selben Tag: echte Hardware (RTX 4090), AMD/Intel/schwache Grafik,
„der einfachste Installer der Welt“.

- archiso-Profil (abgeleitet von releng), Build im archlinux-Container auf einem Build-Host, `build.sh`.
- Look aus dem Trailer: Plymouth-Theme, syslinux/systemd-boot-Menü, ReGreet-Login, Hyprland (Lua-Config), hyprlock, Waybar,
  mako, kitty/foot, fuzzel, GTK/Qt-Farben, Wallpaper + Logos generiert aus `brand/tokens.css`.
- Command Bar (Super + Leertaste) mit Planer (Ollama lokal, Regel-Fallback, optional Claude mit eigenem Schlüssel) → Render-Queue.
- Render-Queue mit Executors: Song (YuE2), Stimme (VoxCPM2/Piper), Musikvideo (LTX-Video über ComfyUI / Lite-FFmpeg),
  Shorts (9:16, stärkste Stellen, Whisper-Untertitel, HW-Encoder), Thumbnails A/B (Qwen-Image / Vorlagen), Stems, Mastering, Untertitel.
- Toravo Setup: Hardware-Profile nvidia/amd/intel/cpu, VRAM-Stufen, Modell×Profil-Tabelle, Treiber + Modelle mit Fortschritt.
- Studio Local (Web-UI in eigenem Fenster): Heute, Song, Voice, Video, Shorts, Thumbnails, Kalender mit Freigabe, Queue.
- Eigener 3-Schritt-Installer (offline): btrfs + snapper, zram, systemd-boot/GRUB, NVIDIA offline, „neben Windows“ nur im freien Platz.
- Lite-Modus + labwc-Fallback-Sitzung, Bootmenü „sichere Grafik“.
- Nach VM-Tests behoben: Parted als Live-Nutzer (Platz neben Windows wurde nicht erkannt), Setup nutzt jetzt `sudo -S`
  mit Passwortfeld statt pkexec (Polkit-Dialog stürzte ohne 3D ab), bereits installierte Pakete werden übersprungen,
  Whisper dekodiert per FFmpeg (PyAV-Inkompatibilität), Shorts-Anzahl/-Länge, Wellenform im Lite-Video im Verlauf,
  Vorlagen-Hintergrund dunkel wie im Trailer, foot-Config für aktuelles foot, nbd/ntfsprogs/GStreamer-Plugins im ISO.
