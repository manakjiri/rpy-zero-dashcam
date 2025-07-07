#!/usr/bin/python3
"""
Test script for USB auto-discovery functionality
Run this to verify USB storage detection works correctly
"""

import os
import sys
import logging
from pathlib import Path

# Add the current directory to the path so we can import our modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dashcam import ConfigManager, StorageManager


def test_usb_discovery():
    """Test USB discovery functionality"""
    print("Testing USB Auto-Discovery...")
    print("=" * 50)
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger('USBTest')
    
    # Create config and storage manager
    config = ConfigManager()
    storage = StorageManager(config, logger)
    
    # Test discovery
    print(f"Current USB path: {storage.current_usb_path}")
    print(f"USB available: {storage.is_usb_available()}")
    
    if storage.is_usb_available():
        print(f"Available space: {storage.get_available_space() / (1024**3):.2f} GB")
        print(f"Used space: {storage.get_used_space() / (1024**3):.2f} GB")
        print(f"Should cleanup: {storage.should_cleanup()}")
    else:
        print("No USB storage detected")
    
    # Test re-discovery
    print("\nTesting re-discovery...")
    storage._discover_usb_storage()
    print(f"After re-discovery: {storage.current_usb_path}")
    
    # List all mounted filesystems for reference
    print("\nAll mounted filesystems:")
    try:
        with open('/proc/mounts', 'r') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 3:
                    device, mount_point, fs_type = parts[0], parts[1], parts[2]
                    if not mount_point.startswith('/sys') and not mount_point.startswith('/proc'):
                        print(f"  {device} -> {mount_point} ({fs_type})")
    except Exception as e:
        print(f"Error reading mounts: {e}")


if __name__ == "__main__":
    try:
        test_usb_discovery()
    except KeyboardInterrupt:
        print("\nTest interrupted by user")
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc() 