#!/usr/bin/env python3
"""
Physical to Virtual (P2V) Converter
Main entry point that supports both GUI and CLI modes
"""

import os
import sys
import argparse
from log_handler import log_info, log_error

def check_root_privileges():
    """Check if the program is running with root privileges"""
    if os.geteuid() != 0:
        print("❌ This program must be run as root!")
        print("   GUI mode: sudo python3 main.py")
        print("   CLI mode: sudo python3 main.py --cli")
        sys.exit(1)

def show_usage():
    """Show usage information"""
    print("Physical to Virtual (P2V) Converter")
    print("=" * 50)
    print()
    print("Usage:")
    print("  sudo python3 main.py           # Start GUI mode (default)")
    print("  sudo python3 main.py --cli     # Start CLI mode")
    print("  sudo python3 main.py --help    # Show this help")
    print()
    print("CLI Examples:")
    print("  # Interactive CLI")
    print("  sudo python3 main.py --cli")
    print()
    print("  # List disks")
    print("  sudo python3 main.py --cli --list-disks")
    print()
    print("  # Batch conversion")
    print("  sudo python3 main.py --cli -s /dev/sda -n my_vm -o /path/to/output")
    print()
    print("  # Batch with options")
    print("  sudo python3 main.py --cli -s /dev/sdb -n vm_name -o /output --yes --force")
    print()

def parse_initial_args():
    """Parse initial arguments to determine mode"""
    # Create a simple parser just to check for --cli flag and --help
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--cli", action="store_true", help="Run in CLI mode")
    parser.add_argument("--help", "-h", action="store_true", help="Show help")
    
    # Parse known args to avoid errors with CLI-specific arguments
    args, unknown = parser.parse_known_args()
    
    return args, unknown

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
        print("\n💡 Try using CLI mode instead:")
        print("   sudo python3 main.py --cli")
        return 1
    except Exception as e:
        print(f"❌ Error starting GUI: {str(e)}")
        log_error(f"GUI startup error: {str(e)}")
        return 1

def run_cli_mode():
    """Run the CLI mode"""
    try:
        from cli import run_cli_main
        
        log_info("P2V Converter CLI application started")
        
        return run_cli_main()
        
    except ImportError as e:
        print("❌ CLI module not found:")
        print(f"   {str(e)}")
        print("\n💡 Make sure cli.py is in the same directory")
        return 1
    except Exception as e:
        print(f"❌ Error starting CLI: {str(e)}")
        log_error(f"CLI startup error: {str(e)}")
        return 1

def main():
    """Main function to run the P2V converter"""
    # Parse initial arguments
    args, unknown = parse_initial_args()
    
    # Show help if requested
    if args.help:
        show_usage()
        return 0
    
    # Check for root privileges
    check_root_privileges()
    
    # Determine mode
    if args.cli:
        # CLI mode
        return run_cli_mode()
    else:
        # GUI mode (default)
        return run_gui_mode()

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n👋 Operation cancelled by user")
        log_info("Application terminated by user (Ctrl+C)")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        log_error(f"Unexpected application error: {str(e)}")
        sys.exit(1)