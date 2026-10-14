#!/bin/sh
# Toravo OS identity (based on Arch Linux; ID_LIKE keeps Arch tooling working).
cat > /etc/os-release <<'OS'
NAME="Toravo OS"
PRETTY_NAME="Toravo OS (based on Arch Linux)"
ID=toravo
ID_LIKE=arch
BUILD_ID=rolling
ANSI_COLOR="38;2;138;92;246"
HOME_URL="https://toravo.de/"
LOGO=toravo
OS
printf 'Toravo OS (based on Arch Linux) \\r (\\l)\n\n' > /etc/issue
