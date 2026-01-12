#!/bin/bash

# Exit on any error
set -e

# Variables
ISO_NAME="$(pwd)/p2vConverter-v1.0-XFCE-32bits.iso"
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

# Configure live-build - Use Bullseye for better legacy hardware support
echo "Configuring live-build for Debian Bullseye (better legacy support)..."
lb config --distribution=bullseye --architectures=i386 \
    --linux-packages=linux-image \
    --linux-flavours=686-pae \
    --debian-installer=live \
    --bootappend-live="boot=live components hostname=p2v-converter username=user locales=fr_FR.UTF-8 keyboard-layouts=fr" \
    --bootloaders="syslinux,grub-efi" \
    --binary-images=iso-hybrid \
    --mode=debian \
    --system=live

# Add Debian repositories for firmware
mkdir -p config/archives
cat << EOF > config/archives/debian.list.chroot
deb http://deb.debian.org/debian bullseye main contrib non-free
deb-src http://deb.debian.org/debian bullseye main contrib non-free
deb http://security.debian.org/debian-security bullseye-security main contrib non-free
deb-src http://security.debian.org/debian-security bullseye-security main contrib non-free
EOF

# Pre-accept firmware licenses
mkdir -p config/preseed
cat << EOF > config/preseed/firmware.preseed
firmware-ipw2x00 firmware-ipw2x00/license/accepted boolean true
firmware-ivtv firmware-ivtv/license/accepted boolean true
EOF

# Add required packages with maximum hardware compatibility
echo "Adding required packages..."
mkdir -p config/package-lists/
cat << EOF > config/package-lists/custom.list.chroot
coreutils
parted
ntfs-3g
python3
qemu-utils
qemu-kvm
virt-manager
bridge-utils
libvirt-daemon
libvirt-clients
python3-tk
dosfstools
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
tasksel
tasksel-data
console-setup
keyboard-configuration
cryptsetup
dmsetup
caffeine
systemd
osinfo-db
osinfo-db-tools
calamares
calamares-settings-debian
firmware-linux-free
firmware-linux-nonfree
firmware-misc-nonfree
firmware-realtek
firmware-atheros
firmware-iwlwifi
firmware-bnx2
firmware-bnx2x
firmware-brcm80211
firmware-ralink
firmware-zd1211
xserver-xorg-video-all
xserver-xorg-video-intel
xserver-xorg-video-ati
xserver-xorg-video-nouveau
xserver-xorg-video-vesa
xserver-xorg-video-fbdev
xserver-xorg-video-cirrus
xserver-xorg-video-dummy
xserver-xorg-input-all
pciutils
usbutils
acpi
acpid
hdparm
smartmontools
lm-sensors
beep
edac-utils
i2c-tools
memtest86+
EOF

# Set system locale and keyboard layout to French AZERTY
echo "Configuring live system for French AZERTY keyboard..."
mkdir -p config/includes.chroot/etc/default/

# Set default locale to French
cat << EOF > config/includes.chroot/etc/default/locale
LANG=fr_FR.UTF-8
LC_ALL=fr_FR.UTF-8
EOF

# Set keyboard layout to AZERTY
cat << EOF > config/includes.chroot/etc/default/keyboard
XKBMODEL="pc105"
XKBLAYOUT="fr"
XKBVARIANT="azerty"
XKBOPTIONS=""
EOF

# Set console keymap for tty
cat << EOF > config/includes.chroot/etc/default/console-setup
ACTIVE_CONSOLES="/dev/tty[1-6]"
CHARMAP="UTF-8"
CODESET="Lat15"
XKBLAYOUT="fr"
XKBVARIANT="azerty"
EOF

# Disable all power management and suspend features
echo "Disabling power management and suspend..."
mkdir -p config/includes.chroot/etc/systemd/logind.conf.d/
cat << EOF > config/includes.chroot/etc/systemd/logind.conf.d/no-suspend.conf
[Login]
HandleSuspendKey=ignore
HandleHibernateKey=ignore
HandleLidSwitch=ignore
HandleLidSwitchExternalPower=ignore
HandleLidSwitchDocked=ignore
IdleAction=ignore
EOF

# Disable systemd sleep targets
mkdir -p config/includes.chroot/etc/systemd/sleep.conf.d/
cat << EOF > config/includes.chroot/etc/systemd/sleep.conf.d/no-sleep.conf
[Sleep]
AllowSuspend=no
AllowHibernation=no
AllowSuspendThenHibernate=no
AllowHybridSleep=no
EOF

# Create systemd override to mask suspend/hibernate targets
mkdir -p config/includes.chroot/etc/systemd/system/sleep.target.d/
cat << EOF > config/includes.chroot/etc/systemd/system/sleep.target.d/override.conf
[Unit]
ConditionPathExists=/dev/null
EOF

mkdir -p config/includes.chroot/etc/systemd/system/suspend.target.d/
cat << EOF > config/includes.chroot/etc/systemd/system/suspend.target.d/override.conf
[Unit]
ConditionPathExists=/dev/null
EOF

mkdir -p config/includes.chroot/etc/systemd/system/hibernate.target.d/
cat << EOF > config/includes.chroot/etc/systemd/system/hibernate.target.d/override.conf
[Unit]
ConditionPathExists=/dev/null
EOF

mkdir -p config/includes.chroot/etc/systemd/system/hybrid-sleep.target.d/
cat << EOF > config/includes.chroot/etc/systemd/system/hybrid-sleep.target.d/override.conf
[Unit]
ConditionPathExists=/dev/null
EOF

# Configure XFCE Power Manager to never suspend
mkdir -p config/includes.chroot/etc/xdg/xfce4/xfconf/xfce-perchannel-xml/
cat << 'EOF' > config/includes.chroot/etc/xdg/xfce4/xfconf/xfce-perchannel-xml/xfce4-power-manager.xml
<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfce4-power-manager" version="1.0">
  <property name="xfce4-power-manager" type="empty">
    <property name="power-button-action" type="uint" value="3"/>
    <property name="show-tray-icon" type="bool" value="true"/>
    <property name="logind-handle-lid-switch" type="bool" value="false"/>
    <property name="dpms-enabled" type="bool" value="false"/>
    <property name="blank-on-ac" type="int" value="0"/>
    <property name="blank-on-battery" type="int" value="0"/>
    <property name="dpms-on-ac-sleep" type="uint" value="0"/>
    <property name="dpms-on-ac-off" type="uint" value="0"/>
    <property name="dpms-on-battery-sleep" type="uint" value="0"/>
    <property name="dpms-on-battery-off" type="uint" value="0"/>
    <property name="brightness-on-ac" type="uint" value="9"/>
    <property name="brightness-on-battery" type="uint" value="9"/>
    <property name="inactivity-on-ac" type="uint" value="0"/>
    <property name="inactivity-on-battery" type="uint" value="0"/>
    <property name="inactivity-sleep-mode-on-ac" type="uint" value="1"/>
    <property name="inactivity-sleep-mode-on-battery" type="uint" value="1"/>
    <property name="lid-action-on-ac" type="uint" value="0"/>
    <property name="lid-action-on-battery" type="uint" value="0"/>
    <property name="lock-screen-suspend-hibernate" type="bool" value="false"/>
    <property name="critical-power-action" type="uint" value="1"/>
  </property>
</channel>
EOF

# Disable screen blanking and DPMS
mkdir -p config/includes.chroot/etc/X11/xorg.conf.d/
cat << EOF > config/includes.chroot/etc/X11/xorg.conf.d/10-monitor.conf
Section "ServerFlags"
    Option "BlankTime" "0"
    Option "StandbyTime" "0"
    Option "SuspendTime" "0"
    Option "OffTime" "0"
EndSection

Section "Monitor"
    Identifier "LVDS0"
    Option "DPMS" "false"
EndSection

Section "Device"
    Identifier "Card0"
    Driver "vesa"
    Option "UseFBDev" "true"
EndSection
EOF

# Configure libvirt to allow access to external drives
echo "Configuring libvirt for external drive access..."
mkdir -p config/includes.chroot/etc/libvirt/

# Create custom qemu.conf to allow access to /mnt and /media
cat << 'EOF' > config/includes.chroot/etc/libvirt/qemu.conf
# Run qemu as root to access external drives
user = "root"
group = "root"

# Disable security driver restrictions - needed for external drives
security_driver = "none"

# Allow dynamic ownership of files
dynamic_ownership = 0

# Set VNC listen address
vnc_listen = "0.0.0.0"

# Allow stdio in monitor
stdio_handler = "file"
EOF

# Ensure libvirtd starts and runs on boot
mkdir -p config/includes.chroot/etc/systemd/system/
cat << 'EOF' > config/includes.chroot/etc/systemd/system/libvirtd-startup.service
[Unit]
Description=Start libvirtd daemon on boot
After=network.target
Before=virt-manager.service

[Service]
Type=oneshot
ExecStart=/bin/systemctl start libvirtd
ExecStart=/bin/sleep 2
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

# Copy all files from CODE_DIR to /usr/local/bin
echo "Copying all files from $CODE_DIR to /usr/local/bin..."
mkdir -p config/includes.chroot/usr/local/bin/
cp -r "$CODE_DIR"/* config/includes.chroot/usr/local/bin/
chmod +x config/includes.chroot/usr/local/bin/*

# Create symbolic link 'd2q' -> main.py
ln -sf /usr/local/bin/main.py config/includes.chroot/usr/local/bin/d2q

# Allow sudo without password
echo "Configuring sudo to be passwordless..."
mkdir -p config/includes.chroot/etc/sudoers.d/
echo "user ALL=(ALL) NOPASSWD: ALL" > config/includes.chroot/etc/sudoers.d/passwordless
chmod 0440 config/includes.chroot/etc/sudoers.d/passwordless

# Create USB flash drive udev rules
echo "Creating USB flash drive udev rules..."
mkdir -p config/includes.chroot/etc/udev/rules.d/
cat << 'EOF' > config/includes.chroot/etc/udev/rules.d/usb-flash.rules
# Try to catch USB flash drives and set them as non-rotational
ATTR{queue/rotational}=="0", GOTO="skip"
ATTRS{queue_type}!="none", GOTO="skip"
ATTR{removable}=="1", SUBSYSTEM=="block", SUBSYSTEMS=="usb", ACTION=="add", ATTR{queue/rotational}="0"
ATTR{removable}=="1", SUBSYSTEM=="block", SUBSYSTEMS=="usb", ACTION=="add", RUN+="/bin/beep -f 70 -r 2"
LABEL="skip"
EOF

# Create application launcher for the installed version
echo "Creating application launcher..."
mkdir -p config/includes.chroot/usr/share/applications/
cat << EOF > config/includes.chroot/usr/share/applications/p2v_converter.desktop
[Desktop Entry]
Version=1.0
Name=P2V Converter
Comment=Transform physical disks into qcow2 virtual machine images ready for any hypervisor
Exec=sudo /usr/local/bin/d2q
Icon=drive-harddisk
Terminal=true
Type=Application
Categories=System;Security;
Keywords=p2v;v2v;virtualization;qcow2;migration;backup;image;disk;vm;qemu;kvm;convert;
EOF

chmod +x config/includes.chroot/usr/share/applications/p2v_converter.desktop

# Auto-start in live mode - Create XFCE autostart
mkdir -p config/includes.chroot/etc/xdg/autostart/
cat << EOF > config/includes.chroot/etc/xdg/autostart/p2v_converter.desktop
[Desktop Entry]
Type=Application
Name=P2V Converter
Comment=Start P2V Converter automatically in live mode
Exec=sudo /usr/local/bin/d2q
Terminal=true
Icon=drive-harddisk
Categories=System;Security;
OnlyShowIn=XFCE;
EOF

# Configure .bashrc to run main.py on login in live mode but not in installed mode
echo "Configuring .bashrc to run main.py in live mode..."
mkdir -p config/includes.chroot/etc/skel/
cat << 'EOF' > config/includes.chroot/etc/skel/.bashrc
# Source global definitions
if [ -f /etc/bashrc ]; then
    . /etc/bashrc
fi

# Display information about the P2V Converter
echo "P2V Converter"
echo "Type 'sudo d2q' to use the P2V Converter program"

# Check if we're in live mode
if grep -q "boot=live" /proc/cmdline; then
    # Only auto-start in terminals when in live mode
    if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
        echo "Live mode detected. Starting P2V Converter..."
        sudo /usr/local/bin/d2q
    fi
fi
EOF

# Create a boot hook script to ensure libvirtd starts properly and osinfo-db is updated
echo "Creating libvirtd boot initialization hook..."
mkdir -p config/includes.chroot/lib/live/boot
cat << 'EOF' > config/includes.chroot/lib/live/boot/9999-libvirt-init.sh
#!/bin/sh
# Initialize libvirtd for live system

echo "Initializing libvirt daemon for live system..."

# Create necessary directories
mkdir -p /var/lib/libvirt/images
mkdir -p /var/lib/libvirt/qemu
mkdir -p /var/run/libvirt

# Ensure directories have correct permissions
chmod 755 /var/lib/libvirt
chmod 755 /var/lib/libvirt/images
chmod 755 /var/lib/libvirt/qemu
chmod 755 /var/run/libvirt

# Update osinfo database if network is available
if ping -c 1 -W 2 8.8.8.8 >/dev/null 2>&1; then
    echo "Updating osinfo database..."
    osinfo-db-import --local --latest >/dev/null 2>&1 || true
fi

# Start libvirtd daemon
/usr/sbin/libvirtd -d

# Give it a moment to start
sleep 2

echo "libvirt daemon initialized"
EOF
chmod +x config/includes.chroot/lib/live/boot/9999-libvirt-init.sh

# Configure Boot Menu (Syslinux) with maximum compatibility options
echo "Configuring Syslinux boot menu with compatibility options..."
mkdir -p config/includes.binary/isolinux
cat << 'EOF' > config/includes.binary/isolinux/isolinux.cfg
UI vesamenu.c32
DEFAULT live
TIMEOUT 50
PROMPT 0

MENU TITLE P2V Converter - Boot Menu
MENU BACKGROUND splash.png
MENU COLOR screen 37;40 #80ffffff #00000000 std
MENU COLOR border 30;44 #40ffffff #a0000000 std
MENU COLOR title 1;36;44 #ffffffff #a0000000 std
MENU COLOR sel 7;37;40 #e0ffffff #20ffffff all
MENU COLOR unsel 37;44 #50ffffff #a0000000 std
MENU COLOR help 37;40 #c0ffffff #00000000 std
MENU COLOR timeout_msg 37;40 #80ffffff #00000000 std
MENU COLOR timeout 1;37;40 #c0ffffff #00000000 std
MENU COLOR msg07 37;40 #90ffffff #a0000000 std
MENU COLOR tabmsg 31;40 #ffDEDEDE #00000000 std

LABEL live
    MENU LABEL ^Start Live Environment (Default)
    MENU DEFAULT
    KERNEL /live/vmlinuz
    APPEND initrd=/live/initrd.img boot=live components quiet splash

LABEL live-nomodeset
    MENU LABEL Start Live Environment (Safe ^Graphics)
    KERNEL /live/vmlinuz
    APPEND initrd=/live/initrd.img boot=live components nomodeset quiet

LABEL live-failsafe
    MENU LABEL Start Live Environment (^Failsafe - Legacy Hardware)
    KERNEL /live/vmlinuz
    APPEND initrd=/live/initrd.img boot=live components nomodeset acpi=off noapic nosplash

LABEL live-acpioff
    MENU LABEL Start Live Environment (^ACPI Disabled)
    KERNEL /live/vmlinuz
    APPEND initrd=/live/initrd.img boot=live components nomodeset acpi=off quiet

LABEL live-noapic
    MENU LABEL Start Live Environment (^No APIC)
    KERNEL /live/vmlinuz
    APPEND initrd=/live/initrd.img boot=live components nomodeset noapic quiet

LABEL live-maxcompat
    MENU LABEL Start Live Environment (Ma^ximum Compatibility)
    KERNEL /live/vmlinuz
    APPEND initrd=/live/initrd.img boot=live components nomodeset acpi=off noapic nosplash irqpoll pci=nomsi

LABEL install
    MENU LABEL ^Install P2V Converter (Copy Live System)
    KERNEL /live/vmlinuz
    APPEND initrd=/live/initrd.img boot=live components quiet splash calamares

MENU SEPARATOR

LABEL hdt
    MENU LABEL ^Hardware Detection Tool (HDT)
    COM32 hdt.c32

LABEL memtest
    MENU LABEL ^Memory Test (Memtest86+)
    LINUX memtest

MENU SEPARATOR

LABEL reboot
    MENU LABEL ^Reboot
    COM32 reboot.c32

LABEL poweroff
    MENU LABEL ^Power Off
    COM32 poweroff.c32
EOF

# Configure GRUB Boot Menu with compatibility options
echo "Configuring GRUB boot menu with compatibility options..."
mkdir -p config/bootloaders/grub-pc
cat << 'EOF' > config/bootloaders/grub-pc/grub.cfg
set default=0
set timeout=5

insmod all_video
insmod gfxterm
set gfxmode=auto
terminal_output gfxterm

menuentry "Start Live Environment (Default)" {
    linux /live/vmlinuz boot=live components quiet splash
    initrd /live/initrd.img
}

menuentry "Start Live Environment (Safe Graphics)" {
    linux /live/vmlinuz boot=live components nomodeset quiet
    initrd /live/initrd.img
}

menuentry "Start Live Environment (Failsafe - Legacy Hardware)" {
    linux /live/vmlinuz boot=live components nomodeset acpi=off noapic nosplash
    initrd /live/initrd.img
}

menuentry "Start Live Environment (ACPI Disabled)" {
    linux /live/vmlinuz boot=live components nomodeset acpi=off quiet
    initrd /live/initrd.img
}

menuentry "Start Live Environment (No APIC)" {
    linux /live/vmlinuz boot=live components nomodeset noapic quiet
    initrd /live/initrd.img
}

menuentry "Start Live Environment (Maximum Compatibility)" {
    linux /live/vmlinuz boot=live components nomodeset acpi=off noapic nosplash irqpoll pci=nomsi
    initrd /live/initrd.img
}

menuentry "Install P2V Converter (Copy Live System)" {
    linux /live/vmlinuz boot=live components quiet splash calamares
    initrd /live/initrd.img
}
EOF

# Also configure GRUB EFI
mkdir -p config/bootloaders/grub-efi
cp config/bootloaders/grub-pc/grub.cfg config/bootloaders/grub-efi/grub.cfg

# Auto-start Calamares if in installer mode
mkdir -p config/includes.chroot/etc/profile.d/
cat << 'EOF' > config/includes.chroot/etc/profile.d/autostart-calamares.sh
#!/bin/bash
if [[ "$(cat /proc/cmdline)" == *"calamares"* ]]; then
    echo "Starting Calamares Installer..."
    calamares --debug
fi
EOF
chmod +x config/includes.chroot/etc/profile.d/autostart-calamares.sh

# Create modprobe configuration for better hardware compatibility
echo "Creating modprobe configuration for legacy hardware..."
mkdir -p config/includes.chroot/etc/modprobe.d/
cat << 'EOF' > config/includes.chroot/etc/modprobe.d/compatibility.conf
# Disable problematic modules on old hardware
options drm_kms_helper poll=0
options i915 modeset=0
options nouveau modeset=0
options radeon modeset=0

# Enable compatibility for old SATA/IDE controllers
options libata force=noncq
options libata atapi_enabled=1

# USB compatibility
options usbcore old_scheme_first=1
EOF

# Create kernel boot parameters helper script
mkdir -p config/includes.chroot/usr/local/sbin/
cat << 'EOF' > config/includes.chroot/usr/local/sbin/check-boot-params
#!/bin/bash
# Display current boot parameters for troubleshooting
echo "=== Current Boot Parameters ==="
cat /proc/cmdline
echo ""
echo "=== Loaded Kernel Modules ==="
lsmod | head -20
echo ""
echo "=== Hardware Detection ==="
lspci -nn | head -10
EOF
chmod +x config/includes.chroot/usr/local/sbin/check-boot-params

# Build the ISO
echo "Building the ISO..."
sudo lb build

# Move the ISO
if [ -f live-image-i386.hybrid.iso ]; then
    mv live-image-i386.hybrid.iso "$ISO_NAME"
    echo "Done. ISO created at: $ISO_NAME"
elif [ -f live-image-i386.iso ]; then
    mv live-image-i386.iso "$ISO_NAME"
    echo "Done. ISO created at: $ISO_NAME"
else
    echo "ERROR: Could not find generated ISO file"
    exit 1
fi

# Display ISO info
echo ""
echo "=== ISO Information ==="
echo "Filename: $ISO_NAME"
echo "Size: $(du -h "$ISO_NAME" | cut -f1)"
echo ""
echo "=== Boot Options Available ==="
echo "1. Start Live Environment (Default) - Standard boot"
echo "2. Safe Graphics - For video card issues (nomodeset)"
echo "3. Failsafe - For very old hardware (nomodeset acpi=off noapic)"
echo "4. ACPI Disabled - For ACPI-related issues"
echo "5. No APIC - For interrupt-related issues"
echo "6. Maximum Compatibility - All compatibility options enabled"
echo ""
echo "If you experience boot issues, try the options in this order: 2 → 3 → 6"

# Cleanup
sudo lb clean

echo "Done. ISO created at: $ISO_NAME"