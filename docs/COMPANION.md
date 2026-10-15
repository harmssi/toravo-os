# Toravo Companion – phone app + PC service

Toravo Companion is a native iPhone app (SwiftUI, `apps/ios/ToravoCompanion`) that talks to a small service on your Toravo OS PC
(`toravo-companion`, systemd user service). No cloud, no accounts, no costs: the phone talks directly to your PC in your local network.

- **Pairing:** Toravo Studio → *Connect phone* shows a QR code. The app scans it (or you type the code). Every phone gets its own
  token; you can revoke each phone in the Studio at any time.
- **Encryption:** HTTPS with a certificate your PC creates for itself (self-signed). The app does not trust it blindly: the QR code
  contains the fingerprint of the PC's key and the app only talks to a server with exactly this key (pinning).
- **Finding the PC:** the service announces itself via Bonjour/mDNS as `_toravo._tcp` (needs `avahi-daemon`, optional). If the PC
  gets a new IP address, the app finds it again by its id + key fingerprint.
- **Local network only:** requests from public IP addresses are refused (private ranges, link-local, loopback, CGNAT/Tailscale only).
- **Notifications:** honest status – see "Notifications" below.

## Service

- Unit: `toravo-companion.service` (user), `python3 -m toravo.companion.server`, port **8891** (`TORAVO_COMPANION_PORT`), all interfaces.
- Off by default. The Studio button *Connect phone* turns it on (`systemctl --user enable --now toravo-companion`); *Turn off phone
  access* stops and disables it.
- State in `~/.config/toravo/companion/` (mode 0700): `server.key` (EC P-256), `server.crt` (self-signed, 10 years), `id` (random
  server id), `devices.json` (per device: id, name, model, created, last_seen, **sha256 of the token** – the token itself is never stored).

## Pairing link (QR code)

```
toravo://pair?v=1&h=<ip>[,<ip>…]&p=8891&c=<code>&fp=<sha256-hex>&id=<server-id>&n=<pc-name>
```

- `c` – one-time pairing code, 10 characters (`ABCDEFGHJKMNPQRSTUVWXYZ23456789`), valid 10 minutes, shown as `ABCDE-FGHJK`.
- `fp` – lowercase hex SHA-256 of the server public key as DER *SubjectPublicKeyInfo* (`openssl pkey -pubout -outform DER | sha256sum`).
- `h` – the PC's private IPv4 addresses, best first.

## API (v1)

All requests HTTPS, JSON. Except `/api/v1/hello` and `/api/v1/pair` every request needs `Authorization: Bearer <token>`.
Errors: `{"error": "<code>", "message": "<text>"}` with 400/401/403/404/409/413/416/429 (429 has `Retry-After`; 500 only on bugs).
Error codes: `bad_request`, `bad_code`, `unauthorized`, `forbidden_network`, `not_found`, `unknown_plan`, `bad_state`,
`too_many_devices`, `too_large`, `range`, `rate_limited`, `internal`.

| Method | Path | Body / query | Answer |
|---|---|---|---|
| GET | `/api/v1/hello` | – | `{name, version, id, api: 1}` |
| POST | `/api/v1/pair` | `{code, device, model}` | `{token, device_id, server: {name, id, version}}` |
| POST | `/api/v1/unpair` | – | `{ok: true}` (revokes the calling token) |
| GET | `/api/v1/status` | – | `{server, gpu, jobs: [Job], events_seq, time}` |
| GET | `/api/v1/events` | `?since=<seq>` | `{seq, events: [Event]}` |
| POST | `/api/v1/plan` | `{text}` | `{plan_id, title, subject, provider, ready, steps: [{kind, title, ready, engine?, count?}]}` |
| POST | `/api/v1/plans/<plan_id>/run` | – | `{jobs: [id]}` (only plans this server made, valid 15 min, once) |
| POST | `/api/v1/jobs/<id>/pause` | – | `{ok, job}` (queued → paused) |
| POST | `/api/v1/jobs/<id>/resume` | – | `{ok, job}` (paused → queued) |
| POST | `/api/v1/jobs/<id>/cancel` | – | `{ok, job}` (queued/paused/running → cancelled) |
| GET | `/api/v1/media` | `?kind=all\|shorts\|thumbnail\|video\|song&limit=60` (max 300) | `{items: [Media]}` newest first |
| GET | `/api/v1/media/<id>` | Range supported | the file (`Content-Disposition: attachment`) |
| GET | `/api/v1/media/<id>/poster` | – | JPEG preview (first frame for videos, scaled image for pictures, waveform for songs), max 640 px wide |

```
Job   = {id, kind, title, subject, state, progress (0..1), step, created, started, finished, error, outputs: [Media],
         can_pause, can_resume, can_cancel}
        state: queued | paused | running | done | failed | needs_tool | cancelled
Media = {id, kind, name, size, mtime, type: video|image|audio, url: "/api/v1/media/<id>", poster: "/api/v1/media/<id>/poster"}
        id = base64url("<kind>/<path relative to ~/Toravo/<folder>>"), no padding – only files inside ~/Toravo/{Shorts,Thumbnails,Videos,Songs}
Event = {seq, time, type: started|done|failed|needs_tool|cancelled, job_id, title, kind, outputs: [Media]}
GPU   = {name, util, vram_used, vram_total, temp}   (GB, °C; CPU fallback without a GPU)
```

Pausing works for jobs that have not started yet (a running GPU job can only be cancelled – it cannot be frozen safely).

Details (as implemented, 15.10.2026):
- `status.jobs`: running/queued/paused first, then the newest finished jobs, at most 50. `events_seq` is `0` until the first event.
- Job actions in the wrong state answer 409 `bad_state` and include the current `job`. Pausing in the very moment the queue starts
  the job also gives 409 (the job is then `running`).
- Plans belong to the phone that asked for them (another phone gets 404 `unknown_plan`). "Open in Studio" and "start stream" steps are left out (going live stays a decision at the PC).
- Events: `seq` is a millisecond timestamp, strictly increasing, also across restarts; the last 200 events and the last known
  job states are kept in `~/.local/state/toravo/companion/events.json`, so jobs that finished while the service was off are
  reported after its start. `outputs` are Media (files that no longer exist are left out).
- Media downloads: one byte range per request (`bytes=a-b`, `a-`, `-n`; 206 + `Content-Range`, 416 if outside the file), `HEAD`
  works, `ETag` + `If-Range`. Hidden files, symlinks, other folders and other file types are 404.

## Limits

- Pairing: 5 wrong codes per IP per 10 minutes, 20 overall, then 429. Codes are single use.
- API: token bucket per device (10 requests/s, burst 30); plan requests 6 per minute.
- At most 10 paired phones (409 `too_many_devices`); at most 20 MB request body (413, no uploads from the phone in v1).
- Wrong/revoked tokens: 30 per IP per 10 minutes, then 429.

## Bonjour, CLI, Studio

- Bonjour: `avahi-publish -s "Toravo <pc-name>" _toravo._tcp 8891 v=1 id=<server-id> fp=<first 16 hex of fp>` while the service
  runs (only if `avahi-publish` exists; package optdepend `avahi`).
- CLI: `toravo-companion status | pair | devices | revoke <id> | on | off` – `pair` turns the service on and prints the link,
  the code and a QR code in the terminal.
- The certificate is made again (same key, same fingerprint) when the PC's addresses change; SAN = `<pc-name>.local`, `localhost`,
  the private IPv4 addresses and `127.0.0.1`.
- Studio Local (127.0.0.1:8890, `X-Toravo: 1` for POST): `GET /api/companion`, `POST /api/companion/pair` (turns the service on,
  new code + QR SVG), `POST /api/companion/off`, `POST /api/companion/devices/<id>/revoke`.
- A user preset (`80-toravo-companion.preset`) keeps the unit disabled by default.

## Notifications – what works without a cloud server

- **While the app is open** (or was just in the background) it polls `/api/v1/events` and shows a local notification when a job is
  done ("Done: Cut 3 Shorts"). This needs nothing but your network.
- **In the background** iOS decides when an app may refresh (Background App Refresh – minutes to hours, not guaranteed). The app
  asks for it, but it is best effort.
- **Real push** (instant, app closed) needs Apple Push Notification service, and that needs a provider key bound to the app
  developer account. Such a key does not belong into a distribution that everyone can download, so Toravo OS does not do it.
  If it ever comes, it will be optional and documented.
