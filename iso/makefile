# Define variables
SCRIPT_XFCE := ./forgeIsoXfce.sh
SCRIPT_KDE := ./forgeIsoKde.sh
SCRIPT_XFCE_32 := ./forgeIsoXfce32.sh
SCRIPT_KDE_32 := ./forgeIsoKde32.sh
BUILD_DIR := $(pwd)/debian-live-build

.PHONY: all clean

# Default target: run the script
all:
	chmod +x $(SCRIPT_XFCE)
	bash $(SCRIPT_XFCE)

kde:
	chmod +x $(SCRIPT_KDE)
	bash $(SCRIPT_KDE)

xfce32:
	chmod +x $(SCRIPT_XFCE_32)
	bash $(SCRIPT_XFCE_32)

kde32:
	chmod +x $(SCRIPT_KDE_32)
	bash $(SCRIPT_KDE_32)

# Clean target: remove the debian-live-build directory
clean:
	rm -rf $(BUILD_DIR)
