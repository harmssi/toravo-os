# Toravo OS – Testanleitung (USB-Stick, Live-Test, Installation)

> **Wichtig:** Teste live vom Stick oder installiere auf eine **zweite, leere Platte**. „Ganze Platte löschen“ nie für die Platte deines bestehenden Systems wählen.

## 1. Stick erstellen (USB ≥ 8 GB, wird komplett überschrieben)

Dann eine der beiden Möglichkeiten:
- **Ventoy**: ISO einfach auf den Ventoy-Stick kopieren.
- **Mac, Terminal:** `diskutil list` → Stick finden (z. B. `/dev/disk4`), dann
  `diskutil unmountDisk /dev/disk4 && sudo dd if=~/Downloads/toravo-os-*.iso of=/dev/rdisk4 bs=4m status=progress`
  (Achtung: richtige Nummer! `dd` fragt nicht nach.)

## 2. Booten

1. Stick an den PC, einschalten, Boot-Menü öffnen (meist **F11**, **F12** oder **F8**; bei ASUS F8, bei MSI F11, bei Gigabyte F12).
2. Den Eintrag mit **UEFI: <Stick>** wählen.
3. **Secure Boot:** Toravo OS ist (noch) nicht signiert. Wenn der Stick nicht startet oder „Secure Boot Violation“ erscheint:
   ins BIOS/UEFI (Entf/F2) → *Boot* bzw. *Security* → **Secure Boot: Disabled** → speichern. Dein bestehendes System startet danach weiterhin normal.
   (Läuft auf dem PC schon Linux mit NVIDIA-Treiber, ist Secure Boot sehr wahrscheinlich bereits aus.)
4. Im Toravo-Bootmenü **„Toravo OS – Live & Installieren“** wählen. Falls das Bild schwarz bleibt: neu starten und
   **„sichere Grafik (Lite)“** nehmen.

## 3. Was du prüfen solltest (live, ohne etwas zu installieren)

| # | Prüfen | Erwartung |
|---|---|---|
| 1 | Bootsplash | „T“-Logo, TORAVO/OS, violetter Glow, Wellenform füllt sich |
| 2 | Desktop | Live-Benutzer startet automatisch; großer Willkommens-Bildschirm „Toravo OS installieren / Erst ausprobieren“ |
| 3 | „Erst ausprobieren“ | Dunkler Desktop, große Uhr + „THE AI CONTENT CREATOR OS“, oben schmale Leiste mit TORAVO/OS, GPU-Wert, Queue, Uhr |
| 4 | **Super + Leertaste** | Command Bar in der Mitte. Tippen: `turn skyborne into a music video + 3 shorts + thumbnail` → Tab → Schrittliste |
| 5 | Super + Enter | Terminal (kitty) im Toravo-Farbschema |
| 6 | Super + L | Sperrbildschirm mit großer Uhr; Passwort im Live-System: **toravo** |
| 7 | Super + S | Toravo Studio (Heute / Song / Voice / Video / Shorts / Thumbnails / Kalender / Queue) |
| 8 | Grafik | 4090 läuft live mit dem freien nouveau-Treiber (der NVIDIA-Treiber kommt erst bei der Installation). Leiste zeigt dann „CPU …“ statt GPU-Werten – das ist live normal |
| 9 | Monitor | richtige Auflösung/Bildwiederholrate? (Falls nicht: notieren, Phase-2-Punkt) |
| 10 | Netzwerk | Kabel → automatisch online; WLAN über Symbol oben rechts |

Bitte **Fotos/Screenshots** (Druck-Taste → `~/Bilder/Screenshots`) von allem machen, was komisch aussieht.

## 4. Installieren (nur auf eine leere zweite Platte!)

1. „Toravo OS installieren“ (Willkommen-Bildschirm oder Command Bar).
2. **Schritt 1 – Willkommen:** Sprache/Tastatur sind vorbelegt (Deutsch); „ändern“ nur falls nötig.
3. **Schritt 2 – Wohin installieren?** Toravo schlägt von sich aus die **leere** Platte vor. Prüfe Name und Größe der Kachel!
   Platten mit Linux/Windows werden als „Linux gefunden“ / „Windows gefunden“ angezeigt und nie ohne Bestätigung gelöscht.
4. **Schritt 3 – Wer bist du?** Name + Passwort.
5. „Installieren“ → Wellenform läuft (ca. 3–8 Minuten). Mit NVIDIA-Karte wird der NVIDIA-Treiber offline mitinstalliert.
6. „Neu starten“, Stick abziehen. Im UEFI-Bootmenü erscheint **„Linux Boot Manager“** (das ist Toravo OS, systemd-boot).
   Dein bestehendes System startest du wie bisher über die andere Platte (Boot-Menü F11/F12 oder BIOS-Bootreihenfolge).
7. Erster Start: Login (oder Auto-Login), dann öffnet sich **Toravo Setup**: zeigt „NVIDIA · 24 GB · Stufe ≥ 16“ und
   welche Modelle passen. „Einrichten“ lädt Treiber-Extras, CUDA, ComfyUI, LTX-Video, Qwen-Image, YuE2, VoxCPM2, Whisper,
   Demucs, Matchering, Ollama + Qwen3 (insgesamt ca. 110–130 GB Download, je nach Auswahl). „Später“ geht auch.

## 5. Was danach zu testen ist (echte Hardware – in der VM nicht möglich)

- `nvidia-smi` im Terminal; Waybar zeigt „GPU xx % · x/24 GB · xx°“.
- Studio → Song: Song erzeugen (YuE2) → landet in `~/Toravo/Songs`.
- Studio → Video: Musikvideo aus dem Song (LTX-Video über ComfyUI).
- Studio → Shorts: 3 Shorts mit Untertiteln (NVENC).
- Studio → Thumbnails: A/B mit Qwen-Image.
- Command Bar: `turn <song> into a music video + 3 shorts + thumbnail` → Ausführen → Studio → Queue.
- OBS: Command Bar → „Stream starten“ (vorher in OBS Stream-Schlüssel eintragen; NVENC als Encoder wählen).

Fehlerprotokolle: Installer `/var/log/toravo-install.log`, Setup `~/Toravo/AI/state.json`, Queue `~/.local/share/toravo/queue/`,
Sitzung `~/.local/state/toravo/hyprland.log`.

## 6. Zurück zum bestehenden System

Stick abziehen und neu starten – dein bestehendes System bleibt unverändert, solange du nicht dessen Platte gewählt hast.
Toravo von der zweiten Platte entfernen: Platte im bestehenden System mit `gnome-disks`/`parted` neu partitionieren.
