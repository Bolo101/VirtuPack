# P2V Converter – Turn Physical Machines into Virtual Ones

Ever needed to convert an old physical computer into a virtual machine? Whether you want to preserve a legacy system or migrate seamlessly to virtualized infrastructure, this tool takes a physical disk and creates a **qcow2 virtual machine image** ready for most hypervisors.

The utility is safety-focused, prevents accidental imaging of running system disks, and provides a graphical interface. Optional scripts let you build a **bootable ISO** for safe offline conversion.

***

## Features

- Converts any physical disk to a **compressed qcow2** image compatible with most virtualization software.
- Progress bar and cancel button—see what's happening in real-time.
- Prevents accidental imaging of the currently running system.
- Optional mounting of extra disks for additional storage.
- Disk resize utilities.
- Detailed logging and optional PDF reporting.
- **Supports QEMU/KVM, virt-manager, VirtualBox, VMware, Hyper-V, and more.**

***

## Getting a Bootable ISO

**Option 1:** Download a pre-built ISO  
*(Update this URL in the future)*

**Option 2:** Build your own ISO

```sh
cd iso/
# For KDE Plasma:
./forgeIsoKde.sh

# For XFCE (lighter/faster):
./forgeIsoXfce.sh

# Or use the makefile:
make kde-iso     # KDE-based ISO
make xfce-iso    # XFCE-based ISO
make clean       # Clean build files
```

Each script builds a Linux live environment with the P2V converter installed.

***

## Requirements

**Running the converter (native install):**

- **On Ubuntu/Debian:**  
  `sudo apt install qemu-utils python3-tk gparted`
- **On Fedora/CentOS/RHEL:**  
  `sudo dnf install qemu-img tkinter gparted`

**For ISO building:**  
Install `debootstrap squashfs-tools xorriso` as needed (the build scripts check for required dependencies).

***

## Getting Started

**Using the bootable ISO:**

- Download or build the ISO.
- Write it to USB or DVD.
- Boot target machine from the ISO.
- The P2V Converter is available on the desktop or in the applications menu.

**Note:** Root privileges are needed for raw disk access.

***

## Workflow Overview

- **Choose source disk:**  
  Click "Refresh Disks" and select the physical disk for conversion; unsafe selections are blocked.

- **Choose output directory:**  
  Select where to store the new VM file. Use "Mount Disk" to attach extra storage.

- **Check available space:**  
  Use "Check Space Requirements" for a smart estimate based on used data.

- **Start conversion:**  
  Press "Start P2V Conversion"—your compressed qcow2 file will be created.

- **Resize partitions with GParted:**  
  After the initial image is created, the program offers to launch **GParted** to resize the virtual partitions. This lets you shrink or expand partitions before finalizing the QCOW2 image, helping generate a better-fitted and more compact virtual disk aligned with your partition changes.

  Using GParted inside a VM or live environment allows safe adjustment of each partition’s size (e.g., reducing unused space). After resizing, create a new image reflecting these changes to optimize storage and VM performance.

***

## Running The Converted VMs

### Using virt-manager

1. **Create a new VM in virt-manager**
   - Click "New VM" and select "Import existing disk image".
   - Browse to your qcow2 image.
   - Choose the matching OS type/version.
   - Allocate CPUs/RAM as required.
   - On the last page, check "Customize configuration before install".

2. **Set Firmware to match the source machine**
   - In the customization window, switch to the "Overview" panel.
   - Under "Firmware", select either:
     - **UEFI** (modern systems — often shown as "UEFI x86_64: OVMF")
     - **BIOS** (legacy systems)
   - Click "Apply" to confirm your firmware selection.

3. **Configure boot settings and Secure Boot**
   - Ensure the boot order prioritizes the virtual disk to avoid booting from network or other devices.
   - **Disable Secure Boot** in the virtual machine’s firmware settings or the host’s BIOS/UEFI, as most converted systems won’t boot with Secure Boot enabled.
   - If you restore the image to physical hardware, disable Secure Boot and adjust boot device order in that machine’s BIOS/UEFI accordingly.

4. **Start the VM**
   - Begin installation or boot as usual in virt-manager.

***

## Running VMs Using CLI with qemu-system-x86_64

Run your converted qcow2 VM via command line, specifying memory and boot firmware:

```bash
# For BIOS boot
qemu-system-x86_64 -m <memory_in_MB> -drive file=your_converted_vm.qcow2,format=qcow2 -boot menu=on
```

```bash
# For UEFI boot (replace OVMF paths if needed)
/usr/share/OVMF/OVMF_CODE.fd and /usr/share/OVMF/OVMF_VARS.fd are common locations.

qemu-system-x86_64 \
  -m <memory_in_MB> \
  -drive if=your_converted_vm.qcow2,format=qcow2,file=/usr/share/OVMF/OVMF_CODE_4M.fd \
  -boot menu=on
```

- Replace `<memory_in_MB>` with desired RAM allocation (e.g., 2048 for 2GB).
- The `-boot menu=on` enables boot device selection during VM start.
- Adjust OVMF paths for your distribution if necessary.
- Disable Secure Boot in VM or host BIOS/UEFI if boot fails.

***

## Using qemu-img: Convert qcow2 to Other Formats

Convert your image for various hypervisors and tools:

| Output Format | Command Example |
|---------------|-----------------|
| **raw** (generic)        | `qemu-img convert -f qcow2 -O raw  src.qcow2  output.img` |
| **vmdk** (VMware)        | `qemu-img convert -f qcow2 -O vmdk src.qcow2  output.vmdk` |
| **vdi** (VirtualBox)     | `qemu-img convert -f qcow2 -O vdi  src.qcow2  output.vdi` |
| **vpc** (Hyper-V)        | `qemu-img convert -f qcow2 -O vpc  src.qcow2  output.vhd` |
| **vhdx** (Hyper-V new)   | `qemu-img convert -f qcow2 -O vhdx src.qcow2  output.vhdx` |
| **qed**                  | `qemu-img convert -f qcow2 -O qed  src.qcow2  output.qed` |

Replace `src.qcow2` and output file names as needed.

***

## Boot Troubleshooting & Tips

- Always match your VM’s firmware (UEFI or BIOS) to the original system’s boot method.
- Check and configure the boot device order to boot from the correct disk first.
- Disable **Secure Boot** in VM or hardware firmware to avoid boot problems.
- If unsure, try both BIOS and UEFI modes to find the right one for your system.

***

## Project Structure

```
.
├── code/               # Main application (GUI, core modules)
├── iso/                # ISO build scripts and assets
└── README.md           # This file
```

***
