#!/usr/bin/env bash
# Toravo OS – archiso profile (derived from Arch Linux releng). Toravo OS is based on Arch Linux; it is not an official Arch product.
# shellcheck disable=SC2034
iso_name="toravo-os"
iso_label="TORAVO_$(date --date="@${SOURCE_DATE_EPOCH:-$(date +%s)}" +%Y%m)"
iso_publisher="Toravo <https://toravo.de>"
iso_application="Toravo OS Live/Installer – The AI Content Creator OS (based on Arch Linux)"
iso_version="$(date --date="@${SOURCE_DATE_EPOCH:-$(date +%s)}" +%Y.%m.%d)"
install_dir="arch"
buildmodes=('iso')
bootmodes=('bios.syslinux' 'uefi.systemd-boot')
pacman_conf="pacman.conf"
airootfs_image_type="squashfs"
airootfs_image_tool_options=('-comp' 'zstd' '-Xcompression-level' '15' '-b' '1M')
file_permissions=(
  ["/etc/shadow"]="0:0:400"
  ["/etc/sudoers.d"]="0:0:750"
  ["/etc/sudoers.d/00-toravo-live"]="0:0:440"
  ["/root"]="0:0:750"
  ["/root/.gnupg"]="0:0:700"
  ["/usr/local/bin/choose-mirror"]="0:0:755"
  ["/usr/lib/toravo/live-user-setup"]="0:0:755"
)
