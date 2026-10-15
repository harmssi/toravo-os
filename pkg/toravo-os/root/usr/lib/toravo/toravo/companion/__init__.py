"""Toravo Companion – the PC side of the iPhone app (docs/COMPANION.md). 15.10.2026

store   key + self-signed certificate, server id, paired devices, one-time pairing codes (~/.config/toravo/companion, 0700)
server  HTTPS API v1 on port 8891 (systemd user unit toravo-companion.service, off by default)
panel   Studio Local › Connect phone (QR code, devices, off switch) – called from studio/server.py
cli     toravo-companion status | pair | devices | revoke <id> | on | off
"""
