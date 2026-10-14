# Toravo OS – The AI Content Creator OS

Eine eigene Linux-Distribution **auf Basis von Arch Linux** mit Wayland + Hyprland, im Look des Trailers
„Toravo OS — Official Trailer“ (YouTube qPSta1YRV0M). Ziel: das einfachste OS für KI-Content-Produktion –
**Local. Open source. Free. Runs on your own GPU.**

> Toravo OS ist ein eigenständiges Projekt „based on Arch Linux“ und kein offizielles Arch-Linux-Produkt.
> Logo und Name sind Toravo-eigen. Das Arch-Logo wird nicht verwendet. Paketquellen sind die offiziellen Arch-Repos.

Stand: **0.1.0 (Phase 1+, 14.10.2026)** · Testanleitung für echte Hardware: [docs/TESTANLEITUNG.md](docs/TESTANLEITUNG.md)

---

## Was drin ist

| Bereich | Umsetzung |
|---|---|
| Boot | Plymouth-Theme `toravo` (T-Logo, TORAVO/OS, violetter Glow, Wellenform als Fortschritt); syslinux-Menü (BIOS) mit Toravo-Splash, systemd-boot-Menü (UEFI): *Live & Installieren* · *sichere Grafik (Lite, nomodeset)* · *einfache Sitzung (labwc)* · Memtest |
| Login | greetd + **ReGreet** in cage, Toravo-CSS + Hintergrund. Live: Auto-Login, nach dem Abmelden ReGreet. Installiert: ReGreet (Auto-Login optional im Installer) |
| Desktop | **Hyprland 0.56 (Lua-Konfiguration)**: Rundungen 12 px, Rahmen-Verlauf Violett→Blau→Cyan, dezente Animationen, keine Blur-/Glas-Effekte. Hintergrund selbst erzeugt (assets/gen_assets.py). Desktop-Widget mit großer Uhr + „THE AI CONTENT CREATOR OS“ |
| Leiste | Waybar oben, 30 px: TORAVO/OS · Arbeitsflächen · Fenstertitel · *Installieren* (nur live) · Render-Queue-Zähler · GPU % / VRAM / Temp · LIVE-Punkt · Lautstärke · Netz · Uhr · Power |
| Command Bar | **Super + Leertaste** – eigene GTK4-Layer-Shell-App (toravo-commandbar): Aktionen, App-Suche, Freitext → Plan (lokales LLM über Ollama, Regel-Planer als Fallback) → Jobs in die Render-Queue |
| Sperren | hyprlock: große Uhr, Claim, Datum, Passwortfeld im Panel-Look; hypridle: Sperre nach 10 min, Bildschirm aus nach 15 min, **kein** Auto-Suspend (Renderjobs) |
| Theme | GTK3/4 (adw-gtk3-dark + Toravo-Farben), Qt (qt6ct-Palette), Papirus-Dark, Inter + JetBrains Mono, kitty/foot-Farbschema, mako-Benachrichtigungen, fuzzel (Super + D) |
| Installer | **eigener 3-Schritt-Installer** (Vollbild, siehe unten) – offline, ohne Internet |
| Toravo Setup | Erststart-Assistent: erkennt GPU-Profil + VRAM, zeigt Modell×Profil-Plan mit Größen und Lizenzen, installiert Treiber + KI-Werkzeuge + Modelle mit Wellenform-Fortschritt (fortsetzbar) |
| Studio Local | Toravo Studio als lokale App (127.0.0.1:8890, eigenes Fenster): Heute (Queue, GPU-Kachel, Kalender, Streams, Werkzeuge), Song, Voice, Video, Shorts, Thumbnails A/B, Kalender mit Freigabe, Queue |
| Render-Queue | `toravo-queue` (systemd-User-Dienst): Jobs nacheinander auf der GPU, Abhängigkeiten, Suspend-Sperre während Jobs, Benachrichtigung bei Fertig/Fehler |
| System | btrfs (@, @home, @snapshots, @log, @pkg, zstd) + snapper/snap-pac (Snapshot vor jedem Paket-Update, Rollback), zram statt Swap-Partition, NetworkManager, PipeWire, Bluetooth |

## Bauen

Voraussetzung: ein x86_64-Linux-Host mit Docker (und KVM für die VM-Tests), per SSH erreichbar als `BUILD_HOST`. Alles läuft in einem privilegierten `archlinux:latest`-Container.

    ./build.sh            # synchronisiert die Quellen, baut Assets → Paket toravo-os → lokales Repo → ISO
    ./build.sh --clean    # dasselbe, danach Container entfernen

Alternativ auf einer **Arch-basierten Build-Maschine** (z. B. einer Arch- oder Toravo-OS-VM mit `archiso`, `git`, `base-devel`)
ohne Docker: `BUILD_MODE=native BUILD_HOST=root@buildvm BUILD_DIR=/srv/toravo-os-build ./build.sh` – `mkarchiso` läuft direkt als
root, der pacman-Paket-Cache der Maschine bleibt erhalten (Tipp: `BUILD_DIR` als eigenes btrfs-Subvolume, dann landet der
Build nicht in den snapper-Snapshots).

Ergebnis: `toravo-os-<datum>-x86_64.iso` im `out/`-Ordner auf dem Build-Host.

Ablauf (`scripts/container-build.sh`):
1. `assets/gen_assets.py` erzeugt Wallpaper (3840/2560/1920), Lock-Hintergrund, T-Logos, Wortmarke, Plymouth-Bilder (50 Wellenform-Stufen), syslinux-Splash – alles aus `brand/tokens.css`.
2. `pkg/toravo-os/PKGBUILD` → Paket `toravo-os` (Apps, Configs, Themes, Plymouth) → lokales Repo `[toravo]`.
3. NVIDIA-Pakete (nvidia-open 615.x, nvidia-utils, …) landen als **Offline-Repo** im ISO unter `/opt/toravo/offline-repo` – sie werden nur vom Installer und nur bei erkannter NVIDIA-GPU installiert (Live-System nutzt nouveau).
4. `mkarchiso` mit dem Profil `archiso/` (abgeleitet von releng).

VM-Test (im Container): `scripts/vmctl.py` (QEMU/KVM headless, QMP-Screenshots, Tasten, Befehle über qemu-guest-agent).
VM-Test auf einem Proxmox VE: `scripts/pve-testvm.sh` legt Wegwerf-Test-VMs per `qm` an (eigener VMID-Bereich, Tag `toravo-test`,
`backup=0`, nur die interne Bridge), macht Screenshots/Tasten und löscht sie wieder – nur VMs mit allen drei Merkmalen.

## Ordner

    archiso/                 archiso-Profil (profiledef.sh, packages.x86_64, pacman.conf, airootfs/, efiboot/, syslinux/)
    pkg/toravo-os/           PKGBUILD + root/ (alles, was ins Paket toravo-os geht)
      root/usr/lib/toravo/toravo/   Python-Paket: theme, widgets, hw, stack, setup_app, commandbar, desk, agent,
                                    queue, executors, bar, installer/{app,backend,disks}, studio/{server,launch,static}
      root/usr/lib/toravo/runners/  Läufer in den KI-venvs (VoxCPM, Whisper→SRT, Matchering, optional Claude-Planer)
      root/usr/share/toravo/        Hyprland-Lua, Waybar, labwc, Greeter, Qt-Palette, skel (Nutzer-Configs), ai-stack.json, workflows/
    assets/gen_assets.py     Bild-Assets aus den Design-Tokens
    brand/                   Trailer-Frames, tokens.css, STYLE.md (Quelle für den Look)
    scripts/                 container-build.sh, vmctl.py, pve-testvm.sh
    screenshots/             VM-Screenshots
    docs/TESTING.md          USB-Stick, Booten, Prüfliste

## Entscheidungen

**Installer: eigener 3-Schritt-Installer (GTK4 + eigenes Root-Backend), nicht Calamares, nicht archinstall.**
Vorgabe „der einfachste Installer der Welt“: Calamares (AUR-Build 3.4.2 hat funktioniert, ist aber nicht im ISO) bringt eigene Modul-Logik und
Seiten mit, die man nur mühsam auf 3 Bildschirme drückt, und kennt unser „nie stillschweigend löschen“-Regelwerk nicht.
archinstall ist textbasiert und lädt alles aus dem Netz. Der eigene Installer kopiert das Live-System offline (rsync aus
dem squashfs) und macht genau drei Bildschirme:
1. **Willkommen** – Sprache/Tastatur aus dem Live-System, Zeitzone per Geo-IP (ipapi.co, Fallback Europe/Berlin); ändern nur über den kleinen Link „ändern“. Hinweis + „WLAN verbinden“, wenn offline.
2. **Wohin installieren?** – Platten als Kacheln (Größe, Modell, „leer“, „Windows gefunden“, „Linux gefunden“, „x GB frei“). Vorschlag immer die sicherste Wahl: leere Platte → sonst freier Platz neben einem anderen System (nur UEFI/GPT, ≥ 30 GB, vorhandene Partitionen werden nie verändert, eigene XBOOTLDR-Partition, damit die kleine Windows-EFI-Partition reicht) → sonst nichts vorausgewählt. „Ganze Platte löschen“ nur über roten Button **plus Eintippen des Plattennamens**. Der Installations-Stick wird nie angeboten.
3. **Wer bist du?** – Name + Passwort (+ optional Auto-Login). Anmeldename und Rechnername werden abgeleitet.
Danach Wellenform-Fortschritt und „Neu starten“. Ohne Fragen: GPT, EFI 1 GiB, btrfs mit Subvolumes + snapper, zram,
systemd-boot (UEFI) bzw. GRUB (BIOS), Zeitzone, Locale, NVIDIA-Treiber offline wenn erkannt, Plymouth, Spiegelserver (reflector-Timer).
Für Experten liegt archinstall weiterhin im ISO.

**Launcher: eigene Command Bar (GTK4 + gtk4-layer-shell, Python)** statt fuzzel/rofi/walker – nur so geht der Trailer-Look
mit Schrittliste und die Anbindung an Planer/Queue. fuzzel bleibt als schneller App-Starter (Super + D), im Toravo-Theme.

**Login: greetd + ReGreet (in cage)** – Wayland-nativ, per CSS voll themebar, kein Qt/SDDM nötig; Software-Rendering-Fallback (pixman) für schwache Grafik.

**Bootloader: systemd-boot** (einfach, erkennt Windows automatisch) bzw. **GRUB** nur für reine BIOS-Rechner.

**Lite-Modus / Fallback:** `toravo-session` prüft beim Login die 3D-Beschleunigung (`toravo-hw`, eglinfo). Ohne 3D → Hyprland ohne Schatten/Animationen (Blur ist immer aus), GTK mit Cairo-Renderer. Startet Hyprland gar nicht (Exit < 25 s) → automatisch **labwc** im Toravo-Theme. Im Login wählbar: „Toravo OS“ / „Toravo OS Lite“. Bootmenü: „sichere Grafik (Lite, nomodeset)“.

## Hardware-Profile & Mindestanforderungen

| Profil | Erkennung | Treiber | Encoder | Mindestens | Empfohlen |
|---|---|---|---|---|---|
| **NVIDIA** | PCI-ID 10de, Turing oder neuer (RTX 20/30/40/50, GTX 16) | nvidia-open + nvidia-utils (+ CUDA optional, Standard an) | NVENC | 8 GB VRAM, 16 GB RAM | 24 GB VRAM (RTX 3090/4090/5090), 32 GB RAM |
| **AMD** | 1002, dedizierte Karte ≥ 4 GB | mesa, vulkan-radeon, libva (+ ROCm bei RDNA2/3/4) | VAAPI / AMF | 8 GB VRAM | RX 7900 XTX (24 GB) |
| **Intel** | 8086, Arc A/B | mesa, vulkan-intel, intel-media-driver, vpl-gpu-rt, compute-runtime | QSV / VAAPI | Arc A750 (8 GB) | Arc A770 / B580 |
| **CPU / Lite** | alles andere, iGPUs, VMs, alte NVIDIA (vor Turing → nouveau) | mesa | x264 (bzw. VAAPI bei iGPU) | 4 Kerne, 8 GB RAM, 40 GB Platte | – |

VRAM-Stufen: **low < 8 GB**, **mid 8–16 GB**, **high ≥ 16 GB**. Alle Profile: x86_64, UEFI oder BIOS, 30 GB Platte für das System (+ 50–150 GB für Modelle).

### Modell × Profil (Datei: `pkg/toravo-os/root/usr/share/toravo/ai-stack.json` – erste passende Variante gewinnt)

| Werkzeug | NVIDIA ≥ 16 GB | NVIDIA 8–16 GB | AMD (ROCm) ≥ 8 GB | Intel Arc ≥ 8 GB | < 8 GB / CPU |
|---|---|---|---|---|---|
| Musikvideo | LTX-Video 13B 0.9.8 distilled fp8 (+ optional LTX-2 19B) | LTX-Video 2B 0.9.8 | LTX-Video 2B | LTX-Video 2B (XPU, experimentell) | **Lite:** FFmpeg-Video (Bild + Wellenform + Lyrics); KI-Video Cloud-optional |
| Thumbnail | Qwen-Image fp8 (≥ 24 GB RAM) | Qwen-Image GGUF Q4_K_M (≥ 10 GB) | Qwen-Image GGUF | Qwen-Image GGUF | **Lite:** Vorlagen aus Videoframes (A/B) |
| Song | YuE2-3B | aus (Hersteller: 24-GB-GPU) | aus | aus | aus – Cloud-optional |
| Stimme | VoxCPM2 (Klonen) | VoxCPM2 | VoxCPM2 (experimentell) | Piper (CPU) | Piper TTS (CPU) |
| Untertitel | Whisper large-v3-turbo (CUDA) | Whisper large-v3-turbo | Whisper small (CPU) | Whisper small (CPU) | Whisper small (CPU int8) |
| Stems | Demucs (GPU) | Demucs (GPU) | Demucs (ROCm) | Demucs (CPU) | Demucs (CPU) |
| Mastering | Matchering | Matchering | Matchering | Matchering | Matchering |
| Agent (Command Bar) | Qwen3 8B (Ollama CUDA, ≥ 12 GB) | Qwen3 4B | Qwen3 4B (ollama-rocm/-vulkan) | Qwen3 4B (ollama-vulkan) | Qwen3 1.7B (CPU) |
| Shorts | FFmpeg NVENC + Whisper | NVENC | VAAPI | QSV/VAAPI | x264 – **läuft überall** |
| Streams | OBS + NVENC | NVENC | VAAPI | QSV | x264 – **läuft überall** |
| Kalender/Freigabe | überall | | | | |

„Cloud-optional“ heißt: lokal nicht möglich, eine Cloud-Anbindung ist **nicht** eingebaut und nie Pflicht.

## Kompatibilität (getestet / ungetestet)

| Ziel | Status |
|---|---|
| QEMU/KVM, virtio-vga ohne 3D, UEFI (OVMF) | **getestet**: Live, Installer (leere Platte + neben „Windows“), installiertes System, Setup (CPU-Profil), Lite-Pipeline |
| QEMU/KVM, BIOS (SeaBIOS) | **getestet**: syslinux-Menü, Live, Installation mit GRUB, Start des installierten Systems |
| Lite-Sitzung labwc (Bootmenü „einfache Sitzung“) | **getestet** in der VM |
| NVIDIA RTX 4090 | **ungetestet** – Test auf echter Hardware folgt (docs/TESTING.md) |
| andere NVIDIA (RTX 20–50) | ungetestet |
| AMD Radeon (RDNA2/3/4) | ungetestet |
| Intel Arc / Intel-iGPU | ungetestet |
| Secure Boot an | **nicht unterstützt** (ISO unsigniert) → im BIOS ausschalten |
| Dual-Boot neben Windows (freier Platz) | Logik in der VM mit Dummy-Partition getestet; mit echtem Windows ungetestet |

## Testergebnisse (QEMU/KVM-VM, 14.10.2026)

Alle Tests in QEMU/KVM (4 Kerne, 4 GB RAM, virtio-vga **ohne** 3D → Software-Rendering, Lite-Modus automatisch aktiv). Screenshots: `screenshots/`.

| Test | Ergebnis |
|---|---|
| Boot UEFI (systemd-boot-Menü) + BIOS (syslinux mit Toravo-Splash) | ok |
| Plymouth-Bootsplash (T-Logo, Wortmarke, Wellenform) | ok (UEFI-Live und installiertes System) |
| Live-Sitzung: Hyprland 0.56 mit Software-Rendering, Waybar, Desktop-Uhr, mako, hypridle | ok – Hyprland läuft auch ohne 3D, Lite-Erkennung greift |
| Command Bar: Aktionen, Freitext → Plan (Regel-Planer und **lokales LLM Qwen3 1.7B über Ollama, CPU, ~60 s**) | ok |
| Lockscreen (hyprlock) + Entsperren | ok |
| Installer GUI, leere Platte (UEFI): 3 Bildschirme → Installation → Neustart → ReGreet-Login → Desktop | ok (~4 min) |
| Installer GUI, **neben „Windows“** (ESP + MSR + Datenpartition, 43 GB frei): XBOOTLDR + btrfs im freien Platz | ok – MSR/Datenpartition bit-gleich (Prüfsummen + Marker), Windows-ESP nur um systemd-boot ergänzt, „Windows Boot Manager“ im Bootmenü, Auto-Login ok |
| „Ganze Platte löschen“: roter Button + Plattenname eintippen | Dialog ok (Löschen selbst nicht ausgeführt) |
| Installer-Backend BIOS/GRUB (leere Platte) | ok, bootet |
| Toravo Setup (CPU-Profil): Piper, faster-whisper, Demucs, Matchering, Ollama + Qwen3 1.7B, Modelle mit Fortschritt | ok (~9 GB) |
| Lite-Pipeline: Piper-Stimme → Lite-Musikvideo (Wellenform + Whisper-Lyrics) → Shorts 9:16 mit Untertiteln → Thumbnails A/B | ok |
| Studio Local (WebKit-Fenster) | lädt, Seiten ok; Videovorschau in der VM ohne GPU nicht geprüft (Poster-Bilder ab Build 4) |
| labwc-Lite-Sitzung | ok |
| **Nicht getestet** | echte Hardware; NVIDIA-Treiber (offline-Repo), CUDA, NVENC/VAAPI/QSV; YuE2, VoxCPM2, LTX-Video, Qwen-Image, ComfyUI-Workflows; AMD/Intel-Profile; OBS-Streaming; kitty (Lite nutzt foot); Plymouth mit NVIDIA-proprietär |

## KI-Werkzeugkasten & Lizenzen

Nichts davon liegt im ISO; Toravo Setup lädt es nach (`~/Toravo/AI`). Lizenzen geprüft am 14.10.2026 (Hugging-Face-Modellkarten bzw. Repos):

| Komponente | Lizenz | Hinweis |
|---|---|---|
| ComfyUI | GPL-3.0 | |
| ComfyUI-GGUF | Apache-2.0 | nur für Qwen-Image GGUF |
| LTX-Video 0.9.8 (2B/13B) | LTX-Video Open Weights License 0.X | frei für Firmen < 10 Mio. USD Jahresumsatz, darüber kommerzielle Lizenz |
| LTX-2 19B (optional) | LTX-2 Community License | wie oben (< 10 Mio. USD) |
| Gemma 3 12B (Text-Encoder LTX-2, optional) | Gemma Terms of Use | |
| T5-XXL (Text-Encoder LTX-Video) | Apache-2.0 | |
| Qwen-Image (+ Text-Encoder, VAE, GGUF) | Apache-2.0 | |
| YuE2-3B + YuE2-Vae | CC-BY-NC-4.0 | Code `yue2-infer` aus dem Modell-Repo |
| VoxCPM2 | Apache-2.0 | Stimmen nur mit Einverständnis klonen |
| Piper TTS / Stimmen | MIT / je Stimme (Thorsten: CC0) | |
| faster-whisper / Whisper-Modelle | MIT | |
| Demucs | MIT | |
| Matchering | GPL-3.0 | |
| Ollama | MIT | |
| Qwen3 (1.7B/4B/8B) | Apache-2.0 | |
| OBS Studio | GPL-2.0 | |
| FFmpeg (Arch-Build) | GPL | NVENC/VAAPI/QSV/AMF zur Laufzeit |
| NVIDIA-Treiber | proprietär (Kernelmodul open) | |
| Hyprland | BSD-3 · Waybar MIT · greetd GPL-3 · ReGreet GPL-3 · labwc GPL-2 | |

## Command Bar & Agent-Schnittstelle

- Tasten: **Super + Leertaste** öffnen/schließen · tippen filtert · **Tab** = Plan aus dem Freitext · **Enter** = ausführen · **Esc** = zurück/schließen.
- Planer (`toravo-agent`, Python `toravo.agent`): Reihenfolge laut `~/.config/toravo/agent.json` (Standard `ollama`) → Regel-Planer.
- CLI: `toravo-agent plan "turn skyborne into a music video + 3 shorts + thumbnail"` → JSON; `toravo-agent run "…"` → Jobs.
- Plan-Format: `{"title", "subject", "provider", "steps": [{"kind": song|voice|video|shorts|thumbnail|stems|master|transcribe|stream|studio, "title", "params": {"prompt","count","style","lyrics"}, "after": [Index]}]}`.
- Jobs: `~/.local/share/toravo/queue/<id>.json` (`toravo-queue list|add|cancel|retry`), Studio-API `POST /api/plan`, `/api/plan/run`, `/api/jobs`.
- **Optional, nur auf Wunsch des Nutzers:** Claude als Planer mit **eigenem** API-Schlüssel. Kein Schlüssel im Image, nie Pflicht:

      uv venv ~/Toravo/AI/agent-anthropic/.venv && uv pip install --python ~/Toravo/AI/agent-anthropic/.venv/bin/python anthropic
      echo '<eigener Schlüssel>' > ~/.config/toravo/anthropic.key && chmod 600 ~/.config/toravo/anthropic.key
      echo '{"provider": "anthropic", "api_key_file": "~/.config/toravo/anthropic.key"}' > ~/.config/toravo/agent.json

  Standardmodell `claude-opus-5-5` (Feld `model` änderbar), strukturierte JSON-Ausgabe, serverseitiger Fallback bei Ablehnung ist aktiv; scheitert der Aufruf, plant der lokale Planer.

## Studio Local vs. Toravo Studio (Server)

Das bestehende Toravo-Studio ist an unsere eigene Server- und Konten-Infrastruktur gebunden und wird **nicht** ins Image übernommen; **Studio Local** ist eine eigenständige Neuentwicklung nach denselben Ideen, ohne Server, Konten oder Schlüssel.

## Secure Boot

Das ISO und der installierte Bootloader sind **nicht signiert**. Secure Boot im BIOS ausschalten. (Phase 2: shim-signiert
oder eigene Schlüssel per `sbctl`.)

## Offene Punkte (Phase 2)

- Echte Hardware: RTX 4090 – NVIDIA-Treiber offline, CUDA, NVENC, alle KI-Pfade (YuE2, VoxCPM2, LTX, Qwen-Image) **ungetestet**.
- ComfyUI-Workflows (LTX-Video, Qwen-Image) sind aus den Node-Namen von Hand geschrieben → am ersten echten Lauf prüfen, ggf. per „Save (API)“ ersetzen (`/usr/share/toravo/workflows/`).
- Studio Local: Veröffentlichen (YouTube/TikTok-OAuth je Nutzer), Szenen-Editor, Wiederaufnahme der Server-Funktionen (Deep-QA, Cast-Check).
- Eigenes Paket-Repo für Updates von `toravo-os` (jetzt nur im ISO).
- Secure Boot (signierte Kette), Übersetzung der Oberflächen (aktuell Deutsch).
- Installer: verschlüsselte Installation (LUKS), Windows-Partition verkleinern (bewusst nicht drin – Risiko).

## Lizenz

Der Code und die Konfiguration in diesem Repository stehen unter der **GNU General Public License v3.0 oder neuer** (siehe `LICENSE`):
Jeder darf Toravo OS nutzen, verändern und weitergeben – veränderte Versionen müssen ebenfalls offen unter der GPL bleiben.
Es gibt keine Gewährleistung (Abschnitt 15–16 der Lizenz).

Nicht von dieser Lizenz erfasst:
- **Name und Logo „Toravo“ / „Toravo OS“** (Wortmarke, „T“-Logo): Forks bitte unter eigenem Namen und Logo veröffentlichen.
- **Drittsoftware und KI-Modelle**, die Toravo Setup nachlädt (Arch-Linux-Pakete, YuE2, VoxCPM, LTX-Video, Qwen-Image u. a.):
  Es gelten deren eigene Lizenzen (Tabelle oben). Toravo OS ist „based on Arch Linux“ und steht in keiner Verbindung zum Arch-Linux-Projekt.
