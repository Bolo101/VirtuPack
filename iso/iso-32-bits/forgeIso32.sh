#!/bin/bash

# Exit on any error
set -e

# Variables
ISO_NAME="$(pwd)/p2vConverter-v2.0-32bits.iso"
WORK_DIR="$(pwd)/debian-live-build"
CODE_DIR="$(pwd)/../../code"

echo "Installing live-build and required dependencies..."
sudo apt update
sudo apt install -y live-build python3 syslinux isolinux osinfo-db osinfo-db-tools

echo "Updating osinfo database for libvirt..."
sudo osinfo-db-import --local --latest

echo "Setting up live-build workspace..."
rm -rf "$WORK_DIR"
mkdir -p "$WORK_DIR"
cd "$WORK_DIR"

sudo lb clean --purge || true

echo "Configuring live-build for Debian Bullseye i386..."
lb config \
  --distribution=bullseye \
  --architectures=i386 \
  --linux-packages=linux-image \
  --linux-flavours=686 \
  --debian-installer=none \
  --bootappend-live="boot=live components config hostname=p2v-converter username=user locales=fr_FR.UTF-8 keyboard-layouts=fr" \
  --bootloaders="syslinux" \
  --binary-images=iso-hybrid
# NOTE: --debian-installer=none is intentional.
# Using --debian-installer=live on bullseye i386 triggers:
#   "flAbsPath on localArchive/aptdir/.../dpkg/status failed (realpath: No such file or directory)"
# This is a live-build bug on 32-bit bullseye. Since Calamares is not needed
# in this kiosk-only ISO, none is correct and avoids the error entirely.

# Repositories in chroot
mkdir -p config/archives
cat << 'EOF' > config/archives/debian.list.chroot
deb http://deb.debian.org/debian bullseye main contrib non-free
deb-src http://deb.debian.org/debian bullseye main contrib non-free
deb http://security.debian.org/debian-security bullseye-security main contrib non-free
deb-src http://security.debian.org/debian-security bullseye-security main contrib non-free
EOF

echo "Adding required packages..."
mkdir -p config/package-lists/
cat << 'EOF' > config/package-lists/custom.list.chroot
coreutils
parted
ntfs-3g
python3
python3-tk
qemu-utils
qemu-system-x86
virt-manager
bridge-utils
libvirt-daemon
libvirt-clients
dosfstools
firmware-linux-free
firmware-linux-nonfree
squashfs-tools
xorg
xserver-xorg-video-all
xserver-xorg-video-intel
xserver-xorg-video-ati
xserver-xorg-video-nouveau
xserver-xorg-video-vesa
xserver-xorg-video-fbdev
xserver-xorg-input-all
openbox
lightdm
network-manager
sudo
live-boot
live-config
live-tools
console-setup
keyboard-configuration
systemd
osinfo-db
osinfo-db-tools
pciutils
usbutils
acpi
EOF

echo "Configuring French AZERTY keyboard..."
mkdir -p config/includes.chroot/etc/default/
cat << 'EOF' > config/includes.chroot/etc/default/locale
LANG=fr_FR.UTF-8
LC_ALL=fr_FR.UTF-8
EOF

cat << 'EOF' > config/includes.chroot/etc/default/keyboard
XKBMODEL="pc105"
XKBLAYOUT="fr"
XKBVARIANT="azerty"
XKBOPTIONS=""
EOF

cat << 'EOF' > config/includes.chroot/etc/default/console-setup
ACTIVE_CONSOLES="/dev/tty[1-6]"
CHARMAP="UTF-8"
CODESET="Lat15"
XKBLAYOUT="fr"
XKBVARIANT="azerty"
EOF

echo "Disabling power management and suspend..."
mkdir -p config/includes.chroot/etc/systemd/logind.conf.d/
cat << 'EOF' > config/includes.chroot/etc/systemd/logind.conf.d/no-suspend.conf
[Login]
HandleSuspendKey=ignore
HandleHibernateKey=ignore
HandleLidSwitch=ignore
HandleLidSwitchExternalPower=ignore
HandleLidSwitchDocked=ignore
IdleAction=ignore
EOF

mkdir -p config/includes.chroot/etc/systemd/sleep.conf.d/
cat << 'EOF' > config/includes.chroot/etc/systemd/sleep.conf.d/no-sleep.conf
[Sleep]
AllowSuspend=no
AllowHibernation=no
AllowSuspendThenHibernate=no
AllowHybridSleep=no
EOF

for target in sleep suspend hibernate hybrid-sleep; do
  mkdir -p "config/includes.chroot/etc/systemd/system/${target}.target.d/"
  cat << EOF > "config/includes.chroot/etc/systemd/system/${target}.target.d/override.conf"
[Unit]
ConditionPathExists=/dev/null
EOF
done

echo "Disabling screen blanking..."
mkdir -p config/includes.chroot/etc/X11/xorg.conf.d/
cat << 'EOF' > config/includes.chroot/etc/X11/xorg.conf.d/10-monitor.conf
Section "ServerFlags"
  Option "BlankTime" "0"
  Option "StandbyTime" "0"
  Option "SuspendTime" "0"
  Option "OffTime" "0"
EndSection
EOF

echo "Configuring libvirt..."
mkdir -p config/includes.chroot/etc/libvirt/
cat << 'EOF' > config/includes.chroot/etc/libvirt/qemu.conf
user = "root"
group = "root"
security_driver = "none"
dynamic_ownership = 0
vnc_listen = "0.0.0.0"
EOF

mkdir -p config/includes.chroot/etc/systemd/system/
cat << 'EOF' > config/includes.chroot/etc/systemd/system/libvirtd-startup.service
[Unit]
Description=Start libvirtd daemon on boot
After=network.target

[Service]
Type=oneshot
ExecStart=/bin/systemctl start libvirtd
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

echo "Copying application files..."
mkdir -p config/includes.chroot/usr/local/bin/
cp -r "${CODE_DIR}"/* config/includes.chroot/usr/local/bin/ 2>/dev/null || true
chmod +x config/includes.chroot/usr/local/bin/* 2>/dev/null || true
cat << 'WRAPPER' > config/includes.chroot/usr/local/bin/d2q
#!/bin/bash
exec python3 /usr/local/bin/main.py "$@"
WRAPPER
chmod +x config/includes.chroot/usr/local/bin/d2q

mkdir -p config/includes.chroot/etc/sudoers.d/
echo "user ALL=(ALL) NOPASSWD: ALL" > config/includes.chroot/etc/sudoers.d/passwordless
chmod 0440 config/includes.chroot/etc/sudoers.d/passwordless

mkdir -p config/includes.chroot/etc/udev/rules.d/
cat << 'EOF' > config/includes.chroot/etc/udev/rules.d/usb-flash.rules
ATTR{queue/rotational}=="0", GOTO="skip"
ATTRS{queue_type}!="none", GOTO="skip"
ATTR{removable}=="1", SUBSYSTEM=="block", SUBSYSTEMS=="usb", ACTION=="add", ATTR{queue/rotational}="0"
ATTR{removable}=="1", SUBSYSTEM=="block", SUBSYSTEMS=="usb", ACTION=="add", RUN+="/bin/beep -f 70 -r 2"
LABEL="skip"
EOF

# ─────────────────────────────────────────────────────────────────────────────
# KIOSK / FULLSCREEN SESSION
#
# openbox is the only WM — no KDE, no XFCE, no desktop at all.
# rc.xml forces every window fullscreen + borderless the moment it maps.
#
# Boot flow:
#   LightDM auto-login → p2v-kiosk XSession → p2v-session.sh
#     → openbox (WM, background) + d2q (app, fullscreen, foreground)
#   When the app exits the session ends and LightDM restarts it (Relogin).
# ─────────────────────────────────────────────────────────────────────────────

echo "Configuring openbox kiosk session..."

mkdir -p config/includes.chroot/etc/xdg/openbox/
cat << 'EOF' > config/includes.chroot/etc/xdg/openbox/rc.xml
<?xml version="1.0" encoding="UTF-8"?>
<openbox_config xmlns="http://openbox.org/3.4/rc"
                xmlns:xi="http://www.w3.org/2001/XInclude">
  <applications>
    <application class="*">
      <fullscreen>yes</fullscreen>
      <decor>no</decor>
      <maximized>yes</maximized>
      <layer>above</layer>
    </application>
  </applications>
</openbox_config>
EOF

cat << 'EOF' > config/includes.chroot/usr/local/bin/p2v-session.sh
#!/bin/bash
# P2V Converter kiosk session — called by LightDM.

xset s off -dpms 2>/dev/null || true
xset s noblank   2>/dev/null || true

openbox &
WM_PID=$!
sleep 1

sudo /usr/local/bin/d2q

kill "$WM_PID" 2>/dev/null || true
EOF
chmod +x config/includes.chroot/usr/local/bin/p2v-session.sh

mkdir -p config/includes.chroot/usr/share/xsessions/
cat << 'EOF' > config/includes.chroot/usr/share/xsessions/p2v-kiosk.desktop
[Desktop Entry]
Name=P2V Converter (Kiosk)
Comment=Launch P2V Converter fullscreen, no desktop
Exec=/usr/local/bin/p2v-session.sh
Type=Application
EOF

mkdir -p config/includes.chroot/etc/lightdm/lightdm.conf.d/
cat << 'EOF' > config/includes.chroot/etc/lightdm/lightdm.conf.d/50-autologin.conf
[Seat:*]
autologin-user=user
autologin-session=p2v-kiosk
autologin-user-timeout=0
EOF

mkdir -p config/includes.chroot/etc/skel/
cat << 'EOF' > config/includes.chroot/etc/skel/.dmrc
[Desktop]
Session=p2v-kiosk
EOF

cat << 'EOF' > config/includes.chroot/etc/skel/.bashrc
if [ -f /etc/bashrc ]; then
  . /etc/bashrc
fi
echo "P2V Converter (32-bit)"
echo "Type 'sudo d2q' to use the P2V Converter program"
EOF

# ─────────────────────────────────────────────────────────────────────────────

mkdir -p config/includes.chroot/lib/live/boot
cat << 'EOF' > config/includes.chroot/lib/live/boot/9999-libvirt-init.sh
#!/bin/sh
echo "Initializing libvirt daemon..."
mkdir -p /var/lib/libvirt/images /var/lib/libvirt/qemu /var/run/libvirt
chmod 755 /var/lib/libvirt /var/lib/libvirt/images /var/lib/libvirt/qemu /var/run/libvirt
/usr/sbin/libvirtd -d 2>/dev/null || true
sleep 2
echo "libvirt daemon initialized"
EOF
chmod +x config/includes.chroot/lib/live/boot/9999-libvirt-init.sh

echo "Configuring boot menu..."
mkdir -p config/includes.binary/isolinux
cat << 'EOF' > config/includes.binary/isolinux/isolinux.cfg
UI vesamenu.c32
DEFAULT live
TIMEOUT 50

MENU TITLE P2V Converter (32-bit) - Boot Menu

LABEL live
  MENU LABEL Start P2V Converter
  MENU DEFAULT
  KERNEL /live/vmlinuz
  APPEND initrd=/live/initrd.img boot=live config components

LABEL live-safe
  MENU LABEL Start P2V Converter - Safe Mode (nomodeset)
  KERNEL /live/vmlinuz
  APPEND initrd=/live/initrd.img boot=live config components nomodeset
EOF

echo "Building the ISO..."
sudo lb build

if [ -f live-image-i386.hybrid.iso ]; then
  mv live-image-i386.hybrid.iso "$ISO_NAME"
elif [ -f live-image-i386.iso ]; then
  mv live-image-i386.iso "$ISO_NAME"
else
  echo "ERROR: Could not find generated ISO file"
  exit 1
fi

sudo lb clean
echo "Done. ISO created at: $ISO_NAME"