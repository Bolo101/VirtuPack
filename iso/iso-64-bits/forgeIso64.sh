#!/bin/bash
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║ forgeIso64.sh – ISO dual-boot P2V Converter (64-bit)                        ║
# ║                                                                              ║
# ║ Entrée 1 : Live → OpenBox kiosque (code/)                                    ║
# ║ Entrée 2 : Installer → copie sur disque + XFCE kiosque (code_installer/)    ║
# ║ Entrée 3 : Live Safe → Live + nomodeset                                     ║
# ║                                                                              ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

set -e

# ── Variables ──────────────────────────────────────────────────────────────────
ISO_NAME="$(pwd)/p2vConverter-v2.0-64bits.iso"
WORK_DIR="$(pwd)/debian-live-build"
CODE_DIR="$(pwd)/../../code"
CODE_INSTALLER_DIR="$(pwd)/../../code_installer"

# Paramètres de boot communs (réutilisés dans tous les menus)
BOOT_PARAMS="boot=live components config hostname=p2v-converter username=user locales=fr_FR.UTF-8 keyboard-layouts=fr"

echo "=== Installation des dépendances ==="
sudo apt update
sudo apt install -y live-build python3 syslinux isolinux xorriso rsync

echo "=== Mise en place du workspace live-build ==="
rm -rf "$WORK_DIR"
mkdir -p "$WORK_DIR"
cd "$WORK_DIR"

sudo lb clean --purge || true

# ── Configuration live-build ───────────────────────────────────────────────────
# --bootloaders="syslinux,grub-efi" :
# syslinux → boot BIOS / legacy MBR
# grub-efi → boot UEFI
echo "=== Configuration live-build (Debian Trixie amd64) ==="
lb config \
  --distribution=trixie \
  --architectures=amd64 \
  --linux-packages=linux-image \
  --debian-installer=none \
  --bootappend-live="${BOOT_PARAMS}" \
  --bootloaders="syslinux,grub-efi" \
  --binary-images=iso-hybrid

# ── Dépôts ─────────────────────────────────────────────────────────────────────
mkdir -p config/archives
cat << 'EOF' > config/archives/debian.list.chroot
deb http://deb.debian.org/debian trixie main contrib non-free non-free-firmware
deb-src http://deb.debian.org/debian trixie main contrib non-free non-free-firmware
deb http://security.debian.org/debian-security trixie-security main contrib non-free non-free-firmware
deb-src http://security.debian.org/debian-security trixie-security main contrib non-free non-free-firmware
EOF

# ── Paquets ────────────────────────────────────────────────────────────────────
echo "=== Déclaration des paquets ==="
mkdir -p config/package-lists/
cat << 'EOF' > config/package-lists/custom.list.chroot
coreutils
parted
ntfs-3g
python3
python3-tk
dosfstools
cryptsetup
util-linux
udev
pciutils
usbutils
acpi
sudo
rsync
gparted
grub-common
grub-pc-bin
grub-efi-amd64-bin
grub-pc
os-prober
whiptail
firmware-linux-free
firmware-linux-nonfree
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
xterm
xfce4-session
xfwm4
xfce4-terminal
live-boot
live-config
live-tools
squashfs-tools
console-setup
keyboard-configuration
systemd
evince
network-manager
# Paquets P2V / virtualisation
qemu-utils
qemu-system-x86
virt-manager
bridge-utils
libvirt-daemon
libvirt-clients
osinfo-db
osinfo-db-tools
EOF

# ── Locale française AZERTY ────────────────────────────────────────────────────
echo "=== Configuration AZERTY fr_FR ==="
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

# ── Anti-veille ────────────────────────────────────────────────────────────────
echo "=== Désactivation de la mise en veille ==="
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

mkdir -p config/includes.chroot/etc/X11/xorg.conf.d/
cat << 'EOF' > config/includes.chroot/etc/X11/xorg.conf.d/10-monitor.conf
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
EOF

# ── Code Live ─────────────────────────────────────────────────────────────────
echo "=== Copie du code live ==="
mkdir -p config/includes.chroot/usr/local/bin/
cp -r "${CODE_DIR}"/* config/includes.chroot/usr/local/bin/ 2>/dev/null || true
chmod +x config/includes.chroot/usr/local/bin/*.py 2>/dev/null || true

cat << 'WRAPPER' > config/includes.chroot/usr/local/bin/d2q
#!/bin/bash
exec python3 /usr/local/bin/main.py "$@"
WRAPPER
chmod +x config/includes.chroot/usr/local/bin/d2q

# ── Code Installer ────────────────────────────────────────────────────────────
echo "=== Copie du code installer ==="
mkdir -p config/includes.chroot/usr/local/bin_installer/
cp -r "${CODE_INSTALLER_DIR}"/* config/includes.chroot/usr/local/bin_installer/ 2>/dev/null || true
chmod +x config/includes.chroot/usr/local/bin_installer/*.py 2>/dev/null || true

cat << 'WRAPPER' > config/includes.chroot/usr/local/bin_installer/d2q-installer
#!/bin/bash
exec python3 /usr/local/bin_installer/main.py "$@"
WRAPPER
chmod +x config/includes.chroot/usr/local/bin_installer/d2q-installer

mkdir -p config/includes.chroot/var/log/p2v_converter/
mkdir -p config/includes.chroot/var/lib/p2v_converter/
mkdir -p config/includes.chroot/etc/p2v_converter/

# ── Sudo ──────────────────────────────────────────────────────────────────────
mkdir -p config/includes.chroot/etc/sudoers.d/
echo "user ALL=(ALL) NOPASSWD: ALL" > config/includes.chroot/etc/sudoers.d/passwordless
chmod 0440 config/includes.chroot/etc/sudoers.d/passwordless

# ── udev USB ──────────────────────────────────────────────────────────────────
mkdir -p config/includes.chroot/etc/udev/rules.d/
cat << 'EOF' > config/includes.chroot/etc/udev/rules.d/usb-flash.rules
ATTR{queue/rotational}=="0", GOTO="skip"
ATTRS{queue_type}!="none", GOTO="skip"
ATTR{removable}=="1", SUBSYSTEM=="block", SUBSYSTEMS=="usb", ACTION=="add", ATTR{queue/rotational}="0"
LABEL="skip"
EOF

# ════════════════════════════════════════════════════════════════════════════════
# CONFIGURATION LIBVIRT – accès supports amovibles depuis virt-manager
# Permet de booter une ISO sur /dev/sdX en mode live ET installer
# ════════════════════════════════════════════════════════════════════════════════
echo "=== Configuration libvirt / qemu.conf (supports amovibles) ==="
mkdir -p config/includes.chroot/etc/libvirt/

# qemu.conf : exécution en root + ACL étendue aux blocs amovibles courants
# Note : les wildcards ne sont pas supportés dans cgroup_device_acl ;
#        ajouter /dev/sdX supplémentaires si nécessaire.
cat << 'EOF' > config/includes.chroot/etc/libvirt/qemu.conf
# P2V Converter – accès QEMU aux supports amovibles (virt-manager)
# Modifiez cgroup_device_acl si votre clé USB apparaît sur /dev/sdg ou au-delà.

user  = "root"
group = "root"

cgroup_device_acl = [
  "/dev/null",    "/dev/full",    "/dev/zero",
  "/dev/random",  "/dev/urandom",
  "/dev/ptmx",    "/dev/kvm",
  "/dev/rtc",     "/dev/hpet",
  "/dev/sdb",     "/dev/sdc",     "/dev/sdd",
  "/dev/sde",     "/dev/sdf"
]
EOF

# Service one-shot : ajoute l'utilisateur au groupe libvirt + redémarre libvirtd
mkdir -p config/includes.chroot/etc/systemd/system/
cat << 'EOF' > config/includes.chroot/etc/systemd/system/p2v-libvirt-setup.service
[Unit]
Description=P2V Converter – initialisation libvirt pour supports amovibles
After=libvirtd.service
Requires=libvirtd.service

[Service]
Type=oneshot
RemainAfterExit=yes
# Ajout de l'utilisateur live au groupe libvirt
ExecStart=/usr/sbin/usermod -a -G libvirt user
# Rechargement de libvirtd pour prendre en compte qemu.conf
ExecStartPost=/usr/bin/systemctl restart libvirtd

[Install]
WantedBy=multi-user.target
EOF

# Activation du service via un lien symbolique dans le target (sans systemctl enable)
mkdir -p config/includes.chroot/etc/systemd/system/multi-user.target.wants/
ln -sf /etc/systemd/system/p2v-libvirt-setup.service \
       config/includes.chroot/etc/systemd/system/multi-user.target.wants/p2v-libvirt-setup.service

echo " --> qemu.conf et p2v-libvirt-setup.service ecrits"

# ════════════════════════════════════════════════════════════════════════════════
# SESSION OPENBOX – dispatcher live / installer
# ════════════════════════════════════════════════════════════════════════════════
echo "=== Configuration OpenBox kiosque ==="

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

  <keyboard>
    <keybind key="A-F4">
      <action name="Close" />
    </keybind>
  </keyboard>

</openbox_config>
EOF

cat << 'EOF' > config/includes.chroot/usr/local/bin/p2v-session-live.sh
#!/bin/bash
xset s off -dpms 2>/dev/null || true
xset s noblank 2>/dev/null || true
openbox &
WM_PID=$!
sleep 1

if grep -q "installer=1" /proc/cmdline; then
  xterm -title "P2V Converter - Installateur" -fa "Monospace" -fs 12 \
    -e "sudo /usr/local/bin/install-to-disk.sh"
else
  sudo /usr/local/bin/d2q
fi

kill "$WM_PID" 2>/dev/null || true
EOF
chmod +x config/includes.chroot/usr/local/bin/p2v-session-live.sh

mkdir -p config/includes.chroot/usr/share/xsessions/
cat << 'EOF' > config/includes.chroot/usr/share/xsessions/p2v-live.desktop
[Desktop Entry]
Name=P2V Converter - Live
Comment=P2V Converter (mode live)
Exec=/usr/local/bin/p2v-session-live.sh
Type=Application
EOF

# ════════════════════════════════════════════════════════════════════════════════
# SESSION XFCE – système installé
# ════════════════════════════════════════════════════════════════════════════════
echo "=== Configuration XFCE kiosque (installer) ==="

cat << 'EOF' > config/includes.chroot/usr/local/bin/p2v-session-installer.sh
#!/bin/bash
xset s off -dpms 2>/dev/null || true
xset s noblank 2>/dev/null || true
xfwm4 --compositor=off &
WM_PID=$!
sleep 1
sudo /usr/local/bin_installer/d2q-installer
xterm -title "Session administrateur" -fa "Monospace" -fs 12 &
kill "$WM_PID" 2>/dev/null || true
EOF
chmod +x config/includes.chroot/usr/local/bin/p2v-session-installer.sh

cat << 'EOF' > config/includes.chroot/usr/share/xsessions/p2v-installer.desktop
[Desktop Entry]
Name=P2V Converter - Installé
Comment=P2V Converter (mode installé, kiosque XFCE)
Exec=/usr/local/bin/p2v-session-installer.sh
Type=Application
EOF

# ── LightDM autologin (LIVE) ──────────────────────────────────────────────────
mkdir -p config/includes.chroot/etc/lightdm/lightdm.conf.d/
cat << 'EOF' > config/includes.chroot/etc/lightdm/lightdm.conf.d/50-autologin.conf
[Seat:*]
autologin-user=user
autologin-session=p2v-live
autologin-user-timeout=0
EOF

mkdir -p config/includes.chroot/etc/skel/
cat << 'EOF' > config/includes.chroot/etc/skel/.dmrc
[Desktop]
Session=p2v-live
EOF

cat << 'EOF' > config/includes.chroot/etc/skel/.bashrc
if [ -f /etc/bashrc ]; then . /etc/bashrc; fi
echo "P2V Converter (64-bit)"
echo " sudo d2q -> mode live"
echo " sudo d2q-installer -> mode installe (test)"
EOF

# ════════════════════════════════════════════════════════════════════════════════
# SCRIPT D'INSTALLATION SUR DISQUE (avec override d2q -> code_installer)
# ════════════════════════════════════════════════════════════════════════════════
echo "=== Ecriture du script d'installation ==="
cat << 'INSTALLER' > config/includes.chroot/usr/local/bin/install-to-disk.sh
#!/bin/bash
set -e

TITLE="P2V Converter - Installation"
TARGET_MNT="/mnt/target"

part() {
  case "$1" in
    *nvme*|*mmcblk*) echo "${1}p${2}" ;;
    *) echo "${1}${2}" ;;
  esac
}

DISKS=$(lsblk -d -o NAME,SIZE,MODEL -n | grep -v "^loop" || true)
if [ -z "$DISKS" ]; then
  whiptail --title "$TITLE" --msgbox "Aucun disque detecte." 8 50
  exit 1
fi

MENU_ARGS=()
while IFS= read -r line; do
  name=$(echo "$line" | awk '{print $1}')
  rest=$(echo "$line" | awk '{$1=""; print $0}' | xargs)
  MENU_ARGS+=("/dev/$name" "$rest")
done <<< "$DISKS"

TARGET=$(whiptail --title "$TITLE" --menu \
"Choisir le disque d'installation - TOUTES LES DONNEES SERONT EFFACEES" \
20 70 10 \
"${MENU_ARGS[@]}" \
3>&1 1>&2 2>&3) || { echo "Installation annulee."; exit 0; }

whiptail --title "$TITLE" --yesno \
"AVERTISSEMENT FINAL

Toutes les donnees sur $TARGET seront definitivement effacees.
Le systeme sera configure en P2V Converter (kiosque XFCE).

Confirmer l'installation ?" \
12 60 || { echo "Installation annulee."; exit 0; }

UEFI=0
[ -d /sys/firmware/efi ] && UEFI=1

whiptail --title "$TITLE" --infobox "Partitionnement de $TARGET..." 5 56
wipefs -a "$TARGET"

if [ "$UEFI" -eq 1 ]; then
  parted -s "$TARGET" mklabel gpt
  parted -s "$TARGET" mkpart ESP fat32 1MiB 513MiB
  parted -s "$TARGET" set 1 esp on
  parted -s "$TARGET" mkpart root ext4 513MiB 100%
  EFI_PART="$(part "$TARGET" 1)"
  ROOT_PART="$(part "$TARGET" 2)"
else
  parted -s "$TARGET" mklabel msdos
  parted -s "$TARGET" mkpart primary ext4 1MiB 100%
  parted -s "$TARGET" set 1 boot on
  ROOT_PART="$(part "$TARGET" 1)"
fi

whiptail --title "$TITLE" --infobox "Formatage des partitions..." 5 50
mkfs.ext4 -F "$ROOT_PART"
[ "$UEFI" -eq 1 ] && mkfs.fat -F32 "$EFI_PART"

whiptail --title "$TITLE" --infobox "Montage du systeme de fichiers cible..." 5 56
mkdir -p "$TARGET_MNT"
mount "$ROOT_PART" "$TARGET_MNT"
[ "$UEFI" -eq 1 ] && { mkdir -p "$TARGET_MNT/boot/efi"; mount "$EFI_PART" "$TARGET_MNT/boot/efi"; }

whiptail --title "$TITLE" --infobox "Copie du systeme (quelques minutes)..." 5 60
rsync -aHAX \
  --exclude=/proc --exclude=/sys --exclude=/dev \
  --exclude=/run --exclude=/mnt --exclude=/media \
  --exclude=/tmp --exclude=/live \
  / "$TARGET_MNT"/

mkdir -p "$TARGET_MNT"/{proc,sys,dev,run,mnt,media,tmp}
chmod 1777 "$TARGET_MNT/tmp"

# IMPORTANT : sur le système installé, forcer d2q à utiliser code_installer
cat > "$TARGET_MNT/usr/local/bin/d2q" << 'WRAPPER'
#!/bin/bash
exec python3 /usr/local/bin_installer/main.py "$@"
WRAPPER
chmod +x "$TARGET_MNT/usr/local/bin/d2q"

ROOT_UUID=$(blkid -s UUID -o value "$ROOT_PART")

{
  echo "UUID=$ROOT_UUID / ext4 errors=remount-ro 0 1"
  if [ "$UEFI" -eq 1 ]; then
    EFI_UUID=$(blkid -s UUID -o value "$EFI_PART")
    echo "UUID=$EFI_UUID /boot/efi vfat umask=0077 0 1"
  fi
  echo "tmpfs /tmp tmpfs defaults,nosuid,nodev 0 0"
} > "$TARGET_MNT/etc/fstab"

for svc in live-boot live-config live-tools; do
  chroot "$TARGET_MNT" systemctl mask "$svc" 2>/dev/null || true
done
rm -f "$TARGET_MNT/etc/live/boot.conf" 2>/dev/null || true

cat > "$TARGET_MNT/etc/lightdm/lightdm.conf.d/50-autologin.conf" << 'LIGHTDM_EOF'
[Seat:*]
autologin-user=user
autologin-session=p2v-installer
autologin-user-timeout=0
LIGHTDM_EOF

cat > "$TARGET_MNT/etc/skel/.dmrc" << 'DMRC_EOF'
[Desktop]
Session=p2v-installer
DMRC_EOF

[ -f "$TARGET_MNT/home/user/.dmrc" ] && \
cat > "$TARGET_MNT/home/user/.dmrc" << 'DMRC_EOF'
[Desktop]
Session=p2v-installer
DMRC_EOF

mkdir -p "$TARGET_MNT/var/log/p2v_converter/"
mkdir -p "$TARGET_MNT/var/lib/p2v_converter/"
mkdir -p "$TARGET_MNT/etc/p2v_converter/"
chmod 750 "$TARGET_MNT/var/log/p2v_converter/" \
           "$TARGET_MNT/var/lib/p2v_converter/" \
           "$TARGET_MNT/etc/p2v_converter/"

cat > "$TARGET_MNT/etc/default/grub" << 'GRUBCFG'
GRUB_DEFAULT=0
GRUB_TIMEOUT=3
GRUB_DISTRIBUTOR="P2V Converter v2.0"
GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"
GRUB_CMDLINE_LINUX=""
GRUBCFG

whiptail --title "$TITLE" --infobox "Installation du chargeur d'amorcage..." 5 54
mount --bind /dev "$TARGET_MNT/dev"
mount --bind /proc "$TARGET_MNT/proc"
mount --bind /sys "$TARGET_MNT/sys"
[ "$UEFI" -eq 1 ] && \
mount --bind /sys/firmware/efi/efivars \
  "$TARGET_MNT/sys/firmware/efi/efivars" 2>/dev/null || true

if [ "$UEFI" -eq 1 ]; then
  chroot "$TARGET_MNT" grub-install \
    --target=x86_64-efi \
    --efi-directory=/boot/efi \
    --bootloader-id=P2VConverter \
    --recheck
else
  chroot "$TARGET_MNT" grub-install --target=i386-pc --recheck "$TARGET"
fi
chroot "$TARGET_MNT" update-grub

umount "$TARGET_MNT/sys/firmware/efi/efivars" 2>/dev/null || true
umount "$TARGET_MNT/sys"
umount "$TARGET_MNT/proc"
umount "$TARGET_MNT/dev"
[ "$UEFI" -eq 1 ] && umount "$TARGET_MNT/boot/efi"
umount "$TARGET_MNT"

whiptail --title "$TITLE" --msgbox \
"Installation terminee !

Le systeme P2V Converter v2.0 a ete installe sur $TARGET
en mode kiosque XFCE.

Retirez la cle USB / le CD et appuyez sur OK pour redemarrer." \
16 65

reboot
INSTALLER
chmod +x config/includes.chroot/usr/local/bin/install-to-disk.sh

# ════════════════════════════════════════════════════════════════════════════════
# MENUS DE BOOT (hook + xorriso) – identiques à la version précédente
# ════════════════════════════════════════════════════════════════════════════════

echo ""
echo "=== Ecriture du hook de menu de boot ==="
mkdir -p config/hooks/normal/

cat << 'HOOK' > config/hooks/normal/9999-bootmenu.hook.binary
#!/bin/bash
set -e

BOOT_PARAMS="boot=live components config hostname=p2v-converter username=user locales=fr_FR.UTF-8 keyboard-layouts=fr"

write_syslinux() {
  local DIR="$1"
  [ -d "$DIR" ] || return 0
  cat > "$DIR/isolinux.cfg" << SYSLINUX
UI vesamenu.c32
DEFAULT live
TIMEOUT 150
PROMPT 0

MENU TITLE P2V Converter v2.0 (64-bit) - Boot Menu

LABEL live
  MENU LABEL > Start P2V Converter v2.0 (Live)
  MENU DEFAULT
  KERNEL /live/vmlinuz
  APPEND initrd=/live/initrd.img ${BOOT_PARAMS}

LABEL install
  MENU LABEL > Install P2V Converter v2.0 to disk
  KERNEL /live/vmlinuz
  APPEND initrd=/live/initrd.img ${BOOT_PARAMS} installer=1

LABEL live-safe
  MENU LABEL > Start P2V Converter v2.0 - Safe Mode (nomodeset)
  KERNEL /live/vmlinuz
  APPEND initrd=/live/initrd.img ${BOOT_PARAMS} nomodeset
SYSLINUX
  echo "# replaced by custom boot menu" > "$DIR/live.cfg"
  echo "[hook] syslinux patche dans $DIR"
}

for DIR in binary/isolinux binary/boot/isolinux; do
  write_syslinux "$DIR"
done

write_grub() {
  local CFG="$1"
  [ -f "$CFG" ] || { echo "[hook] $CFG absent, ignore"; return 0; }
  cat > "$CFG" << GRUBMENU
set default=0
set timeout=15

if [ x\$feature_all_video_module = xy ]; then
  insmod all_video
fi

menuentry "Start P2V Converter v2.0 (Live)" {
  linux /live/vmlinuz ${BOOT_PARAMS}
  initrd /live/initrd.img
}

menuentry "Install P2V Converter v2.0 to disk" {
  linux /live/vmlinuz ${BOOT_PARAMS} installer=1
  initrd /live/initrd.img
}

menuentry "Start P2V Converter v2.0 - Safe Mode (nomodeset)" {
  linux /live/vmlinuz ${BOOT_PARAMS} nomodeset
  initrd /live/initrd.img
}
GRUBMENU
  echo "[hook] grub patche dans $CFG"
}

for CFG in binary/boot/grub/grub.cfg \
           binary/EFI/boot/grub.cfg \
           binary/boot/grub/x86_64-efi/grub.cfg; do
  write_grub "$CFG"
done
HOOK
chmod +x config/hooks/normal/9999-bootmenu.hook.binary

echo " --> hook 9999-bootmenu.hook.binary ecrit"

echo ""
echo "=== Construction de l'ISO (plusieurs minutes)... ==="
sudo lb build

echo ""
echo "=== Patch post-build via xorriso ==="

BUILT_ISO=""
if   [ -f "live-image-amd64.hybrid.iso" ]; then BUILT_ISO="live-image-amd64.hybrid.iso"
elif [ -f "live-image-amd64.iso" ];        then BUILT_ISO="live-image-amd64.iso"
else
  echo "ERREUR : ISO introuvable apres lb build"
  ls -lh ./*.iso 2>/dev/null || true
  exit 1
fi
echo "ISO source : $BUILT_ISO ($(du -h "$BUILT_ISO" | cut -f1))"

PATCH_DIR=$(mktemp -d)
trap 'rm -rf "$PATCH_DIR"' EXIT

BOOT_PARAMS="boot=live components config hostname=p2v-converter username=user locales=fr_FR.UTF-8 keyboard-layouts=fr"

cat > "$PATCH_DIR/isolinux.cfg" << SYSLINUX
UI vesamenu.c32
DEFAULT live
TIMEOUT 150
PROMPT 0

MENU TITLE P2V Converter v2.0 (64-bit) - Boot Menu

LABEL live
  MENU LABEL > Start P2V Converter v2.0 (Live)
  MENU DEFAULT
  KERNEL /live/vmlinuz
  APPEND initrd=/live/initrd.img ${BOOT_PARAMS}

LABEL install
  MENU LABEL > Install P2V Converter v2.0 to disk
  KERNEL /live/vmlinuz
  APPEND initrd=/live/initrd.img ${BOOT_PARAMS} installer=1

LABEL live-safe
  MENU LABEL > Start P2V Converter v2.0 - Safe Mode (nomodeset)
  KERNEL /live/vmlinuz
  APPEND initrd=/live/initrd.img ${BOOT_PARAMS} nomodeset
SYSLINUX

echo "# replaced by custom boot menu" > "$PATCH_DIR/live.cfg"

cat > "$PATCH_DIR/grub.cfg" << GRUBMENU
set default=0
set timeout=15

if [ x\$feature_all_video_module = xy ]; then
  insmod all_video
fi

menuentry "Start P2V Converter v2.0 (Live)" {
  linux /live/vmlinuz ${BOOT_PARAMS}
  initrd /live/initrd.img
}

menuentry "Install P2V Converter v2.0 to disk" {
  linux /live/vmlinuz ${BOOT_PARAMS} installer=1
  initrd /live/initrd.img
}

menuentry "Start P2V Converter v2.0 - Safe Mode (nomodeset)" {
  linux /live/vmlinuz ${BOOT_PARAMS} nomodeset
  initrd /live/initrd.img
}
GRUBMENU

echo "Inspection de l'ISO..."
ISO_FILES=$(xorriso -indev "$BUILT_ISO" -find / -type f 2>/dev/null | grep '^/' || true)

ISO_ISOL_CFG=$(echo "$ISO_FILES" | grep -i 'isolinux\.cfg$' | head -1)
ISO_LIVE_CFG=$(echo "$ISO_FILES" | grep -i '/isolinux/live\.cfg$' | head -1)
ISO_GRUB_CFG=$(echo "$ISO_FILES" | grep -i 'boot/grub/grub\.cfg$' | head -1)

[ -z "$ISO_ISOL_CFG" ] && ISO_ISOL_CFG="/isolinux/isolinux.cfg"
[ -z "$ISO_LIVE_CFG" ] && ISO_LIVE_CFG="/isolinux/live.cfg"
[ -z "$ISO_GRUB_CFG" ] && ISO_GRUB_CFG="/boot/grub/grub.cfg"

echo " isolinux.cfg : $ISO_ISOL_CFG"
echo " live.cfg     : $ISO_LIVE_CFG"
echo " grub.cfg     : $ISO_GRUB_CFG"

PATCHED_ISO="$PATCH_DIR/patched.iso"
echo "Application du patch xorriso..."

xorriso \
  -indev "$BUILT_ISO" \
  -outdev "$PATCHED_ISO" \
  -boot_image any replay \
  -map "$PATCH_DIR/isolinux.cfg" "$ISO_ISOL_CFG" \
  -map "$PATCH_DIR/live.cfg"     "$ISO_LIVE_CFG" \
  -map "$PATCH_DIR/grub.cfg"     "$ISO_GRUB_CFG"

ORIG_SIZE=$(stat -c%s "$BUILT_ISO")
PATCH_SIZE=$(stat -c%s "$PATCHED_ISO" 2>/dev/null || echo 0)

if [ "$PATCH_SIZE" -lt $(( ORIG_SIZE / 2 )) ]; then
  echo "ERREUR : ISO patchee anormalement petite ($PATCH_SIZE vs $ORIG_SIZE octets)"
  exit 1
fi
echo "Taille : $ORIG_SIZE -> $PATCH_SIZE octets"

VERIFY_GRUB="$PATCH_DIR/verify_grub.cfg"
xorriso -indev "$PATCHED_ISO" -osirrox on \
  -extract "$ISO_GRUB_CFG" "$VERIFY_GRUB" 2>/dev/null || true
if [ -f "$VERIFY_GRUB" ] && grep -q "installer=1" "$VERIFY_GRUB"; then
  echo " --> grub.cfg : entree installer=1 confirmee"
else
  echo " [!] grub.cfg : entree installer=1 non trouvee (le hook binary suffit)"
fi

VERIFY_ISOL="$PATCH_DIR/verify_isolinux.cfg"
xorriso -indev "$PATCHED_ISO" -osirrox on \
  -extract "$ISO_ISOL_CFG" "$VERIFY_ISOL" 2>/dev/null || true
if [ -f "$VERIFY_ISOL" ] && grep -q "installer=1" "$VERIFY_ISOL"; then
  echo " --> isolinux.cfg : entree installer=1 confirmee"
else
  echo " [!] isolinux.cfg : entree installer=1 non trouvee (le hook binary suffit)"
fi

mv "$PATCHED_ISO" "$BUILT_ISO"
echo "=== Patch xorriso applique ==="

if   [ -f "live-image-amd64.hybrid.iso" ]; then mv "live-image-amd64.hybrid.iso" "$ISO_NAME"
elif [ -f "live-image-amd64.iso" ];        then mv "live-image-amd64.iso"        "$ISO_NAME"
else echo "ERREUR : ISO introuvable pour le renommage final"; exit 1
fi

sudo lb clean
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║ ISO creee : $ISO_NAME"
echo "║"
echo "║ Menu de demarrage (BIOS syslinux ET UEFI GRUB) :"
echo "║ 1. Live       --> OpenBox kiosque (code/)"
echo "║ 2. Installer  --> Copie sur disque + XFCE kiosque (code_installer/)"
echo "║ 3. Live Safe  --> Live + nomodeset"
echo "╚══════════════════════════════════════════════════════════════╝"