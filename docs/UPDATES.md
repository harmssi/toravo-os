# Toravo Update

Toravo OS updates itself in the background, installs updates only while the machine restarts, and goes back to the previous
version on its own if the new one does not come up. This page describes how it works, how to use it and how releases are made.

## For users

- **Updates page:** Command Bar (Super + Space) → “Updates”, or the `⟳ UPDATE` badge in the top bar.
  Shows the version, channel, last update, auto on/off, “Check now”, “Back to the previous version” and optional AI model updates.
- **When an update is ready** you get one notification “Update ready – on next restart” with the release notes in one sentence.
  Nothing changes until you restart. You can keep working, rendering and streaming.
- **Channels:** `stable` (default) – Arch Linux packages pinned to an Arch Linux Archive date that Toravo tested together with the
  Toravo packages. `rolling` – the newest Arch packages from the live mirrors and the newest Toravo packages (for brave users).
- **CLI:** `toravo-update status`, `sudo toravo-update check --force`, `sudo toravo-update set --channel rolling --auto off`,
  `sudo toravo-update rollback`, `toravo-ai models-check`, `toravo-ai models-update <id>`.

### Systems installed with 0.1.0 (before Toravo Update)

Their `pacman.conf` is not managed by Toravo Update, so the updater stays off (`status: off`) until you migrate once:

```
curl -sLo /tmp/toravo.asc https://raw.githubusercontent.com/harmssi/toravo-os/main/pkg/toravo-keyring/toravo.asc
sudo pacman-key --add /tmp/toravo.asc
sudo pacman-key --lsign-key 136D83F5F135BC58D6CE0D582D15F6FB4E576F1E
B=https://github.com/harmssi/toravo-os/releases/download/repo-stable
sudo pacman -U $B/toravo-keyring-20261014-1-any.pkg.tar.zst $B/toravo-os-<version>-1-any.pkg.tar.zst
sudo toravo-update setup        # writes /etc/pacman.conf (backup: /etc/pacman.conf.toravo-bak)
```

## How it works

```
 timer (15 min after boot, then every 3 h)            next start                               start after that
 ┌──────────────────────────────────────┐  ┌──────────────────────────────────────┐  ┌──────────────────────────────┐
 │ idle? (no render job, no stream,     │  │ system-update.target (before the     │  │ new system, chosen once      │
 │ on AC, low load)                     │  │ desktop):                            │  │ (bootctl set-oneshot)        │
 │ signed manifest → pacman -Syuw into  │→ │ @ → snapshot @rollback, kernel →     │→ │ health check: greetd, session│
 │ a separate db (no partial upgrade)   │  │ /boot/toravo-prev, snapper pre/post  │  │ Waybar, render queue up?     │
 │ kernel/NVIDIA guard → "ready"        │  │ around pacman -Su, kernel check      │  │ ok → keep · fail → rollback  │
 └──────────────────────────────────────┘  └──────────────────────────────────────┘  └──────────────────────────────┘
```

1. **Signed repository.** `[toravo]` is a pacman repository on GitHub Releases of this project (`repo-stable`, `repo-rolling`).
   Packages, the repository database and the channel manifest are signed with the Toravo release key; the public key ships in
   `toravo-keyring` (`/usr/share/pacman/keyrings/toravo.gpg`). The manifest is checked with `gpgv` against that key only.
   The installer writes `/etc/pacman.conf` (`toravo-update setup`): `[toravo]` from `/etc/pacman.d/toravo-repo`, `[core]`/`[extra]`
   from `/etc/pacman.d/toravo-mirrorlist`, which the update writes per channel (stable: `archive.archlinux.org/repos/YYYY/MM/DD`).
2. **Background download** (`toravo-update.timer` → `toravo-update check --timer`) only when no Studio render job is queued or
   running, no stream is live, the machine is not on battery and the load is low. Sync databases go to `/var/lib/toravo-update/db`
   (the system databases stay untouched, so `pacman -S` in between never causes a partial upgrade). Packages go to the pacman cache.
3. **Kernel/NVIDIA guard.** With the prebuilt NVIDIA module (`nvidia-open`/`nvidia`) the kernel and the module are only updated
   together – if one of them is missing in an update, both are held back (shown on the Updates page). After installing, the
   module must exist for the new kernel (`modinfo -k`) and the initramfs must be fresh, otherwise the update is undone right away.
4. **Offline install** (`/system-update` → `toravo-update-offline.service` in `system-update.target`, Plymouth message): writable
   snapshot `@` → `@rollback`, kernel + initramfs → `/boot/toravo-prev`, snapper pre snapshot, `pacman -Su` from the prepared
   databases, snapper post snapshot (created by the updater itself – snap-pac needs D-Bus, which does not run during an offline
   update; manual `pacman` runs still get their snap-pac snapshots), then reboot.
5. **Boot assessment (UEFI, systemd-boot).** After the install the loader default becomes the entry
   “Toravo OS (previous version)” (old kernel from `/boot/toravo-prev`, `rootflags=subvol=@rollback`, `toravo.rollback=1`) and
   the new system is selected for exactly one start with `bootctl set-oneshot` – a boot counter with one try. Kernel panics
   reboot after 10 s (`panic=10`).
   - New system starts and `toravo-health.service` sees greetd, the session (with auto-login: Hyprland/labwc), Waybar and the
     render queue → the default goes back to “Toravo OS”. Done.
   - Desktop does not come up within 4 minutes → automatic rollback (`@` ↔ `@rollback`, old kernel back), reboot.
   - New system does not boot at all (panic, hang → switch off/on) → the next start is the previous version;
     `toravo-rollback-finish.service` makes it permanent (`@rollback` → `@`, broken system kept as `@old-<time>`).
6. **Manual rollback.** Updates page → “Back to the previous version” (`toravo-update rollback`): restores the state before the
   last update, or with `--snapshot N` any snapper pre snapshot (the kernel of that snapshot is copied to `/boot` and its
   initramfs rebuilt inside it with `arch-chroot`). Your files in `/home` (`@home`) are never touched.

### BIOS / GRUB

GRUB cannot write its environment block on btrfs, so a one-time boot entry that resets itself is not possible there. On BIOS
machines: the offline install, the snapshots, the kernel/NVIDIA guard and the **health-check rollback** (desktop does not come up →
automatic rollback) work the same. If the new system does not boot at all, choose **“Toravo OS (previous version)”** in the GRUB
menu (Esc/Shift during start); that start makes the old version permanent automatically.

## AI model updates (optional)

`toravo-ai models-check` compares the installed models with their source (Hugging Face commit, Ollama manifest digest); the first
check records the current revision. Updates are never automatic: the Updates page lists new versions with their size, and
`toravo-ai models-update <id>` downloads the new version next to the old one – the old files are only removed when the download
is complete.

## Releases (maintainers)

```
scripts/release.sh key-init                                  # once, on the release machine (private key stays there)
scripts/release.sh build 0.1.3 "<Notiz DE>" "<note EN>"      # package + sign + repo db + signed manifests
scripts/release.sh publish rolling 0.1.3                     # repo-rolling (candidate, brave users)
scripts/release.sh test 0.1.3                                # throwaway VM: install ISO, update via the candidate, smoke test
scripts/release.sh promote 0.1.3                             # repo-stable – refused unless the test passed
```

`release-test.sh` installs the newest ISO unattended in a throwaway Proxmox VM (`scripts/pve-testvm.sh`), points the VM's channel
at the candidate (`manifest_url`/`repo_url` in `/etc/toravo/update.json` – also usable with a local test server via `REPO_BASE`),
starts `toravo-update.service`, reboots through the offline install and checks: version, greetd, desktop session, Command Bar /
agent plan and Studio Local. `EXPECT=rollback` with a deliberately broken build (`BREAK=1 scripts/release.sh build …`, which can
never be published) checks the automatic rollback. The candidate's Arch Linux Archive date (yesterday at build time) becomes the
stable date only through `promote`.

Files: `toravo/update.py` (`toravo-update`), `toravo/updates_app.py` (`toravo-updates`), units `toravo-update.{service,timer}`,
`toravo-update-offline.service`, `toravo-health.service`, `toravo-rollback-finish.service`, polkit `de.toravo.update`,
state in `/var/log/toravo-update/state.json` (on the `@log` subvolume, so it survives a rollback), log `/var/log/toravo-update.log`.
