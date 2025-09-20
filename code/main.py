#!/usr/bin/env python3
"""
Physical to Virtual (P2V) Converter
Main entry point (GUI only, CLI removed)
"""

import os
import sys
from log_handler import log_info, log_error


def check_root_privileges():
    """Check if the program is running with root privileges"""
    if os.geteuid() != 0:
        print("❌ This program must be run as root!")
        print("   GUI mode: sudo python3 main.py")
        sys.exit(1)


def run_gui_mode():
    """Run the GUI mode"""
    try:
        import tkinter as tk
        from p2v_dialog import P2VConverterGUI

        log_info("P2V Converter GUI application started")

        root = tk.Tk()
        app = P2VConverterGUI(root)
        root.mainloop()

        return 0

    except ImportError as e:
        print("❌ GUI dependencies not available:")
        print(f"   {str(e)}")
        return 1
    except (RuntimeError, OSError) as e:
        print(f"❌ Runtime error starting GUI: {str(e)}")
        log_error(f"GUI startup runtime error: {str(e)}")
        return 1
    except KeyboardInterrupt:
        print("\n👋 GUI interrupted by user")
        log_info("GUI interrupted by user (Ctrl+C)")
        return 130
    except BaseException as e:  # catch-all for unexpected fatal errors
        print(f"❌ Unexpected GUI error: {str(e)}")
        log_error(f"Unexpected GUI startup error: {str(e)}")
        return 1


def main():
    """Main function to run the P2V converter in GUI mode"""
    # Check for root privileges
    check_root_privileges()

    # GUI mode only
    return run_gui_mode()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n👋 Operation cancelled by user")
        log_info("Application terminated by user (Ctrl+C)")
        sys.exit(130)
    except SystemExit:
        raise  # allow normal sys.exit propagation
    except (OSError, RuntimeError) as e:
        print(f"\n❌ System error: {e}")
        log_error(f"System error: {str(e)}")
        sys.exit(1)
    except BaseException as e:  # fallback for unexpected fatal errors
        print(f"\n❌ Unexpected fatal error: {e}")
        log_error(f"Unexpected fatal application error: {str(e)}")
        sys.exit(1)
