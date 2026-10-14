# Changelog – Toravo OS

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
