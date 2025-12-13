# P2V Converter – Turn Physical Machines into Virtual Ones

Transform physical disks into **qcow2 virtual machine images** ready for any hypervisor. Safety-focused tool with intuitive GUI, preventing accidental imaging of running systems. Build a **bootable ISO** for safe offline conversion of any physical machine.

***

## Features

### Core Conversion
- Converts physical disks to **compressed qcow2** images
- Real-time progress tracking with cancel capability
- Blocks conversion of active system disks and mounted partitions
- Intelligent space analysis based on actual usage
- Comprehensive logging to `/var/log/disk2qcow2.log`

### Advanced Tools
- **QCOW2 Resizer**: Optimize virtual disk size
- **Format Converter**: Convert between qcow2, vmdk, vdi, vpc, vhdx, raw
- **LUKS Encryption**: Secure VMs with password-protected containers
- **Export Manager**: Transfer images via RSYNC
- **File Manager**: Workspace cleanup
- **Virt-Manager Integration**: Direct VM management
- **External Storage Support**: Mount and use external drives

### Supported Operating Systems
- ✅ **Windows** (all versions - XP through 11, Server editions)
- ✅ **Linux** (all distributions - Ubuntu, Debian, Fedora, CentOS, Arch, etc.)

***

## Quick Start

### Download Pre-built ISO (Recommended)
**[Download P2V Converter ISO](https://archive.org/details/p2v-converter-iso)** *(insert actual link)*

### Or Build Your Own

```bash
cd iso/
make kde-iso     # KDE Plasma environment
make xfce-iso    # XFCE environment (lighter)
make clean       # Clean build files
```

***

## Requirements

### ISO Method (Recommended - No Configuration)
- USB drive (8GB+) or DVD
- External storage drive for output
- No additional setup needed

### Native Installation

**Ubuntu/Debian:**
```bash
sudo apt install qemu-utils python3-tk gparted rsync cryptsetup virt-manager libvirt-daemon-system
```

**Fedora/CentOS/RHEL:**
```bash
sudo dnf install qemu-img python3-tkinter gparted rsync cryptsetup virt-manager libvirt
```

**⚠️ Critical for External Storage:** Configure libvirt to access external drives:

```bash
sudo nano /etc/libvirt/qemu.conf

# Add/modify these lines:
user = "root"
group = "root"

cgroup_device_acl = [
    "/dev/null", "/dev/full", "/dev/zero",
    "/dev/random", "/dev/urandom",
    "/dev/ptmx", "/dev/kvm",
    "/dev/rtc", "/dev/hpet",
    "/dev/sdb", "/dev/sdc", "/dev/sdd",  # Your external drives
    "/dev/disk/by-uuid/*"
]

sudo systemctl restart libvirtd
sudo usermod -a -G libvirt $USER
```

***

## Usage Workflow

### 1. Boot from ISO
- Write ISO to USB: `sudo dd if=p2v-converter.iso of=/dev/sdX bs=4M status=progress`
- Boot target machine from USB
- Launch "P2V Converter" from desktop

### 2. Connect External Storage
- Plug in external USB drive (don't mount manually)

### 3. Configure Conversion

**Select Source:**
- Click **"Refresh Disks"**
- Select disk to convert (system disks blocked for safety)

**Mount External Storage:**
- Click **"Mount Disk"** button
- Select your external drive
- Choose mount point (e.g., `/mnt/external`)
- Click "Mount Selected Disk"
- Output directory updates automatically

**Verify Space:**
- Click **"Check Space Requirements"**
- Green indicator = sufficient space

### 4. Convert
- Click **"Start P2V Conversion"**
- Monitor progress (cancel anytime if needed)
- Typical time: 30-120 minutes depending on size

### 5. Optional Post-Processing
- **"QCOW2 Resize"**: Optimize disk size
- **"LUKS Encryption"**: Secure with password
- **"Format Converter"**: Convert to VMDK/VDI/VHD
- **"Export Image"**: Transfer via RSYNC
- **"Print Session Log"**: Generate PDF report

***

## Running Converted VMs

### Using virt-manager

```bash
# From ISO (auto-configured) or native installation:
virt-manager

# Then in GUI:
# 1. New VM → Import existing disk image
# 2. Browse to .qcow2 file
# 3. Select OS type (Windows or Linux)
# 4. Choose firmware:
#    - UEFI for modern systems (2010+)
#    - BIOS for legacy systems
# 5. DISABLE Secure Boot
# 6. Start VM
```

### Using QEMU CLI

**BIOS boot:**
```bash
qemu-system-x86_64 -m 4096 -drive file=vm.qcow2,format=qcow2 -enable-kvm
```

**UEFI boot:**
```bash
qemu-system-x86_64 -m 4096 \
  -drive file=vm.qcow2,format=qcow2 \
  -drive if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE.fd \
  -enable-kvm
```

**From external drive:**
```bash
sudo mount /dev/sdb1 /mnt/external
qemu-system-x86_64 -m 4096 -drive file=/mnt/external/vm.qcow2,format=qcow2 -enable-kvm
```

***

## Format Conversion

| Platform | Format | Command |
|----------|--------|---------|
| VMware | vmdk | `qemu-img convert -f qcow2 -O vmdk src.qcow2 output.vmdk` |
| VirtualBox | vdi | `qemu-img convert -f qcow2 -O vdi src.qcow2 output.vdi` |
| Hyper-V | vhdx | `qemu-img convert -f qcow2 -O vhdx src.qcow2 output.vhdx` |
| Generic | raw | `qemu-img convert -f qcow2 -O raw src.qcow2 output.img` |

Or use the GUI **"Format Converter"** tool.

***

## Troubleshooting

### Common Issues

**"Disk Unavailable"**
- Boot from ISO to convert system disks
- Unmount partitions: `sudo umount /dev/sdX1`

**"Insufficient Space"**
- Use "Mount Disk" for larger external drive
- Check available space matches requirement

**"Cannot Mount External Drive"**
- Verify detection: `lsblk`
- Unmount if already mounted: `sudo umount /dev/sdX1`

**"VM Won't Boot"**
- Try both UEFI and BIOS modes
- Disable Secure Boot
- Windows may need reactivation after conversion

**"Permission Denied" (native installation)**
- Configure libvirt as shown in Requirements
- Or run with: `sudo python3 code/main.py`

**"External Drive VM Fails to Start"**
- Native installation: Configure libvirt `cgroup_device_acl`
- ISO method: No configuration needed

### Windows-Specific Issues

**"Windows requires activation"**
- Normal after hardware change
- Use original product key to reactivate or **slmgr /rearm** command

**"Missing drivers after boot"**
- Install virtio drivers in guest
- Or use IDE disk mode in VM settings

**"BSOD on first boot"**
- Use BIOS mode instead of UEFI
- Disable virtio, use IDE initially

### Logs

Check `/var/log/disk2qcow2.log` for detailed diagnostics or use "Print Session Log" for PDF reports.

***

## Project Structure

```
disk2qcow2/
├── code/                      # Application (570 KB total)
│   ├── main.py                # Entry point
│   ├── p2v_dialog.py          # Main GUI (88 KB)
│   ├── vm.py                  # Conversion engine
│   ├── utils.py               # Disk utilities
│   ├── log_handler.py         # Logging & PDF
│   ├── disk_mount_dialog.py   # Mount manager
│   ├── qcow2_resize_dialog.py # Resize tool (153 KB)
│   ├── image_format_converter.py # Format converter
│   ├── ciphering.py           # LUKS encryption (47 KB)
│   ├── export.py              # RSYNC export
│   └── virt_launcher.py       # VM management
├── iso/                       # ISO builders
│   ├── forgeIsoKde.sh         # KDE ISO (12 KB)
│   ├── forgeIsoXfce.sh        # XFCE ISO (13 KB)
│   └── makefile               # Build automation
└── README.md
```


## Best Practices

✅ Use ISO method for safe conversions  
✅ Use USB 3.0+ external drives for performance  
✅ Create a backup before resizing partitions using **Backup** button
✅ Keep source disk intact until VM validated  
✅ Use LUKS encryption for sensitive systems  
✅ Generate PDF logs for documentation  


## Technical Details

- **Format**: QCOW2 with zlib compression
- **Source Support**: Windows & Linux, any filesystem
- **Log Location**: `/var/log/disk2qcow2.log`
- **GUI**: Python 3 + Tkinter
- **Tools**: qemu-img, cryptsetup, rsync, libvirt, virt-manager, qemu-utils
- **Target Platforms**: QEMU/KVM, VirtualBox, VMware, Hyper-V


## Quick Example

```bash
# 1. Boot from ISO → Launch P2V Converter
# 2. Click "Refresh Disks" → Select /dev/sda (Windows disk)
# 3. Click "Mount Disk" → Select external /dev/sdb1 → Mount at /mnt/external
# 4. Click "Check Space Requirements" → Verify green indicator
# 5. Click "Start P2V Conversion" → Wait ~45 min for 250GB disk
# 6. Click "Print Session Log" → Save PDF report
# 7. Transfer external drive to host system
# 8. Run: qemu-system-x86_64 -m 4096 -drive file=/mnt/external/sda_vm.qcow2 -enable-kvm
```


**Supported Systems:**
- ✅ Windows (XP, Vista, 7, 8, 10, 11, Server 2003-2022)
- ✅ Linux (Ubuntu, Debian, Fedora, CentOS, RHEL, Arch, openSUSE, etc.)


## License

Open source.

---

**Transform any Windows or Linux physical machine into a portable virtual environment.**

**[Download ISO](https://archive.org/details/p2v-converter-iso)** and start virtualizing today!
