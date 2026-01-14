#!/bin/bash

# Exit on any error
set -e

# Variables
ISO_NAME="$(pwd)/p2vConverter-v1.0-XFCE-64bits.iso"
WORK_DIR="$(pwd)/debian-live-build"
CODE_DIR="$(pwd)/../code"

# Install necessary tools
echo "Installing live-build and required dependencies..."
sudo apt update
sudo apt install -y live-build python3 calamares calamares-settings-debian syslinux isolinux osinfo-db osinfo-db-tools

# Update osinfo database for libvirt
echo "Updating osinfo database for libvirt..."
sudo osinfo-db-import --local --latest

# Create working directory
echo "Setting up live-build workspace..."
mkdir -p "$WORK_DIR"
cd "$WORK_DIR"

# Clean previous build
sudo lb clean --purge

# Configure live-build - Simple and stable configuration
echo "Configuring live-build for Debian Bullseye..."
lb config --distribution=bullseye --architectures=amd64 \
    --linux-packages=linux-image \
    --linux-flavours=amd64 \
    --debian-installer=live \
    --bootappend-live="boot=live components hostname=p2v-converter username=user locales=fr_FR.UTF-8 keyboard-layouts=fr" \
    --bootloaders="syslinux" \
    --binary-images=iso-hybrid

# Add Debian repositories for firmware
mkdir -p config/archives
cat << EOF > config/archives/debian.list.chroot
deb http://deb.debian.org/debian bullseye main contrib non-free
deb-src http://deb.debian.org/debian bullseye main contrib non-free
deb http://security.debian.org/debian-security bullseye-security main contrib non-free
deb-src http://security.debian.org/debian-security bullseye-security main contrib non-free
EOF

# Add required packages
echo "Adding required packages..."
mkdir -p config/package-lists/
cat << EOF > config/package-lists/custom.list.chroot
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
calamares
calamares-settings-debian
squashfs-tools
xorg
gparted
xfce4
xfce4-power-manager
network-manager
network-manager-gnome
sudo
live-boot
live-config
live-tools
console-setup
keyboard-configuration
systemd
osinfo-db
osinfo-db-tools
xserver-xorg-video-all
xserver-xorg-video-intel
xserver-xorg-video-ati
xserver-xorg-video-nouveau
xserver-xorg-video-vesa
xserver-xorg-video-fbdev
xserver-xorg-input-all
pciutils
usbutils
acpi
EOF

# Set system locale and keyboard layout to French AZERTY
echo "Configuring live system for French AZERTY keyboard..."
mkdir -p config/includes.chroot/etc/default/

cat << EOF > config/includes.chroot/etc/default/locale
LANG=fr_FR.UTF-8
LC_ALL=fr_FR.UTF-8
EOF

cat << EOF > config/includes.chroot/etc/default/keyboard
XKBMODEL="pc105"
XKBLAYOUT="fr"
XKBVARIANT="azerty"
XKBOPTIONS=""
EOF

cat << EOF > config/includes.chroot/etc/default/console-setup
ACTIVE_CONSOLES="/dev/tty[1-6]"
CHARMAP="UTF-8"
CODESET="Lat15"
XKBLAYOUT="fr"
XKBVARIANT="azerty"
EOF

# Disable power management and suspend
echo "Disabling power management and suspend..."
mkdir -p config/includes.chroot/etc/systemd/logind.conf.d/
cat << EOF > config/includes.chroot/etc/systemd/logind.conf.d/no-suspend.conf
[Login]
HandleSuspendKey=ignore
HandleHibernateKey=ignore
HandleLidSwitch=ignore
IdleAction=ignore
EOF

mkdir -p config/includes.chroot/etc/systemd/sleep.conf.d/
cat << EOF > config/includes.chroot/etc/systemd/sleep.conf.d/no-sleep.conf
[Sleep]
AllowSuspend=no
AllowHibernation=no
EOF

# Configure XFCE Power Manager
mkdir -p config/includes.chroot/etc/xdg/xfce4/xfconf/xfce-perchannel-xml/
cat << 'EOF' > config/includes.chroot/etc/xdg/xfce4/xfconf/xfce-perchannel-xml/xfce4-power-manager.xml
<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfce4-power-manager" version="1.0">
  <property name="xfce4-power-manager" type="empty">
    <property name="dpms-enabled" type="bool" value="false"/>
    <property name="blank-on-ac" type="int" value="0"/>
    <property name="blank-on-battery" type="int" value="0"/>
  </property>
</channel>
EOF

# Disable screen blanking
mkdir -p config/includes.chroot/etc/X11/xorg.conf.d/
cat << EOF > config/includes.chroot/etc/X11/xorg.conf.d/10-monitor.conf
Section "ServerFlags"
    Option "BlankTime" "0"
    Option "StandbyTime" "0"
    Option "SuspendTime" "0"
    Option "OffTime" "0"
EndSection
EOF

# Configure libvirt
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

# Copy application files
echo "Copying application files..."
mkdir -p config/includes.chroot/usr/local/bin/
cp -r "$CODE_DIR"/* config/includes.chroot/usr/local/bin/ 2>/dev/null || true
chmod +x config/includes.chroot/usr/local/bin/* 2>/dev/null || true
ln -sf /usr/local/bin/main.py config/includes.chroot/usr/local/bin/d2q 2>/dev/null || true

# Allow sudo without password
mkdir -p config/includes.chroot/etc/sudoers.d/
echo "user ALL=(ALL) NOPASSWD: ALL" > config/includes.chroot/etc/sudoers.d/passwordless
chmod 0440 config/includes.chroot/etc/sudoers.d/passwordless

# Create USB flash drive udev rules
mkdir -p config/includes.chroot/etc/udev/rules.d/
cat << 'EOF' > config/includes.chroot/etc/udev/rules.d/usb-flash.rules
ATTR{removable}=="1", SUBSYSTEM=="block", SUBSYSTEMS=="usb", ACTION=="add", ATTR{queue/rotational}="0"
ATTR{removable}=="1", SUBSYSTEM=="block", SUBSYSTEMS=="usb", ACTION=="add", RUN+="/bin/beep -f 70 -r 2"
EOF

# Create application launcher
mkdir -p config/includes.chroot/usr/share/applications/
cat << EOF > config/includes.chroot/usr/share/applications/p2v_converter.desktop
[Desktop Entry]
Version=1.0
Name=P2V Converter
Comment=Transform physical disks into qcow2 virtual machine images
Exec=sudo /usr/local/bin/d2q
Icon=drive-harddisk
Terminal=true
Type=Application
Categories=System;
EOF

# Create XFCE autostart
mkdir -p config/includes.chroot/etc/xdg/autostart/
cat << EOF > config/includes.chroot/etc/xdg/autostart/p2v_converter.desktop
[Desktop Entry]
Type=Application
Name=P2V Converter
Exec=sudo /usr/local/bin/d2q
Terminal=true
OnlyShowIn=XFCE;
EOF

# Configure .bashrc
mkdir -p config/includes.chroot/etc/skel/
cat << 'EOF' > config/includes.chroot/etc/skel/.bashrc
if [ -f /etc/bashrc ]; then
    . /etc/bashrc
fi

echo "P2V Converter"
echo "Type 'sudo d2q' to use the P2V Converter program"

if grep -q "boot=live" /proc/cmdline; then
    if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
        echo "Live mode detected. Starting P2V Converter..."
        sudo /usr/local/bin/d2q
    fi
fi
EOF

# Set console encoding to ASCII mode to avoid display issues
mkdir -p config/includes.chroot/etc/kbd/
cat << 'EOF' > config/includes.chroot/etc/kbd/config
SCREEN_BLANKING=0
EOF

# Boot hook for libvirtd
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

# Simple boot menu - Only 2 modes
echo "Configuring boot menu..."
mkdir -p config/includes.binary/isolinux
cat << 'EOF' > config/includes.binary/isolinux/isolinux.cfg
UI vesamenu.c32
DEFAULT live
TIMEOUT 50

MENU TITLE P2V Converter - Boot Menu

LABEL live
    MENU LABEL Start Live Environment
    MENU DEFAULT
    KERNEL /live/vmlinuz
    APPEND initrd=/live/initrd.img boot=live components quiet

LABEL live-safe
    MENU LABEL Start Live Environment - Safe Mode
    KERNEL /live/vmlinuz
    APPEND initrd=/live/initrd.img boot=live components nomodeset

LABEL install
    MENU LABEL Install to Disk
    KERNEL /live/vmlinuz
    APPEND initrd=/live/initrd.img boot=live components calamares
EOF

# Auto-start Calamares if in installer mode
mkdir -p config/includes.chroot/etc/profile.d/
cat << 'EOF' > config/includes.chroot/etc/profile.d/autostart-calamares.sh
#!/bin/bash
if grep -q "calamares" /proc/cmdline; then
    calamares --debug
fi
EOF
chmod +x config/includes.chroot/etc/profile.d/autostart-calamares.sh

# Build the ISO
echo "Building the ISO..."
sudo lb build

# Move the ISO
if [ -f live-image-amd64.hybrid.iso ]; then
    mv live-image-amd64.hybrid.iso "$ISO_NAME"
elif [ -f live-image-amd64.iso ]; then
    mv live-image-amd64.iso "$ISO_NAME"
else
    echo "ERROR: Could not find generated ISO file"
    exit 1
fi

# Cleanup
sudo lb clean

echo "Done. ISO created at: $ISO_NAME"
