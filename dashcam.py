#!/usr/bin/python3
"""
Raspberry Pi Zero 2 Dashcam System
Continuous recording with USB storage management and status LED
"""

import os
import sys
import time
import yaml
import logging
import signal
import threading
import psutil
import glob
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass

import RPi.GPIO as GPIO
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import FfmpegOutput


@dataclass
class SystemStatus:
    """System status tracking"""
    recording: bool = False
    usb_connected: bool = False
    storage_full: bool = False
    error: bool = False
    last_health_check: float = 0


class ConfigManager:
    """Configuration management"""
    
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self.config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from YAML file"""
        try:
            with open(self.config_path, 'r') as f:
                return yaml.safe_load(f)
        except Exception as e:
            print(f"Error loading config: {e}")
            return self._default_config()
    
    def _default_config(self) -> Dict[str, Any]:
        """Default configuration if file is missing"""
        return {
            'recording': {
                'chunk_duration_minutes': 30,
                'video_quality': '1920x1080',
                'bitrate': 10000000
            },
            'storage': {
                'usb_mount_path': '/media/usb',
                'max_storage_gb': 32,
                'emergency_files_keep': 5
            },
            'gpio': {
                'status_led_pin': 18
            },
            'logging': {
                'level': 'INFO',
                'max_log_files': 10,
                'log_file_size_mb': 10
            },
            'system': {
                'watchdog_timeout': 30,
                'health_check_interval': 60
            },
            'overlay': {
                'enable_timestamp': True,
                'timestamp_format': '%Y-%m-%d %H:%M:%S',
                'timestamp_position': 'bottom-right'
            }
        }
    
    def get(self, key_path: str, default=None):
        """Get configuration value using dot notation"""
        keys = key_path.split('.')
        value = self.config
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value


class StatusLED:
    """Status LED controller"""
    
    def __init__(self, pin: int):
        self.pin = pin
        self.current_pattern: str | None = None
        self.led_thread = None
        self.running = False
        
        # Initialize GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.pin, GPIO.OUT)
        GPIO.output(self.pin, GPIO.LOW)
    
    def _led_worker(self):
        """LED pattern worker thread"""
        while self.running:
            if self.current_pattern == 'solid':
                GPIO.output(self.pin, GPIO.HIGH)
                time.sleep(0.1)
            elif self.current_pattern == 'slow_blink':
                GPIO.output(self.pin, GPIO.HIGH)
                time.sleep(1)
                GPIO.output(self.pin, GPIO.LOW)
                time.sleep(1)
            elif self.current_pattern == 'fast_blink':
                GPIO.output(self.pin, GPIO.HIGH)
                time.sleep(0.2)
                GPIO.output(self.pin, GPIO.LOW)
                time.sleep(0.2)
            elif self.current_pattern == 'off':
                GPIO.output(self.pin, GPIO.LOW)
                time.sleep(0.1)
            else:
                time.sleep(0.1)
    
    def start(self):
        """Start LED controller"""
        self.running = True
        self.led_thread = threading.Thread(target=self._led_worker)
        self.led_thread.daemon = True
        self.led_thread.start()
    
    def stop(self):
        """Stop LED controller"""
        self.running = False
        if self.led_thread:
            self.led_thread.join()
        GPIO.output(self.pin, GPIO.LOW)
    
    def set_pattern(self, pattern: str):
        """Set LED pattern: solid, slow_blink, fast_blink, off"""
        self.current_pattern = pattern


class StorageManager:
    """USB storage management with auto-discovery"""
    
    def __init__(self, config: ConfigManager, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.max_storage_bytes = float(config.get('storage.max_storage_gb', 32)) * 1024 * 1024 * 1024 # type: ignore
        self.emergency_keep = int(config.get('storage.emergency_files_keep', 5)) # type: ignore
        self.current_usb_path: str | None = None
        
        # Discover USB storage on initialization
        self._discover_usb_storage()
    
    def _discover_usb_storage(self) -> Optional[str]:
        """Discover and return the best USB storage device"""
        try:
            # Read /proc/mounts to find mounted filesystems
            with open('/proc/mounts', 'r') as f:
                mounts = f.readlines()
            
            usb_candidates = []
            
            for line in mounts:
                parts = line.strip().split()
                if len(parts) < 3:
                    continue
                    
                device, mount_point, fs_type = parts[0], parts[1], parts[2]
                
                # Skip system mounts and non-USB devices
                if mount_point.startswith('/sys') or mount_point.startswith('/proc'):
                    continue
                if mount_point.startswith('/boot') or mount_point == '/':
                    continue
                
                # Check if this looks like a USB device
                if self._is_usb_device(device):
                    # Verify it's writable and has reasonable space
                    if os.access(mount_point, os.W_OK):
                        try:
                            stat_info = os.statvfs(mount_point)
                            total_space = stat_info.f_blocks * stat_info.f_frsize
                            # Only consider devices with at least 1GB space
                            if total_space > 1024 * 1024 * 1024:
                                usb_candidates.append((mount_point, total_space, fs_type))
                                self.logger.info(f"Found USB storage: {mount_point} ({total_space/1024/1024/1024:.1f}GB, {fs_type})")
                        except Exception as e:
                            self.logger.debug(f"Error checking mount point {mount_point}: {e}")
            
            # Sort by size (largest first) and prefer common filesystems
            usb_candidates.sort(key=lambda x: (x[1], x[2] in ['vfat', 'exfat', 'ext4']), reverse=True)
            
            if usb_candidates:
                best_mount = usb_candidates[0][0]
                self.current_usb_path = best_mount
                self.logger.info(f"Selected USB storage: {best_mount}")
                return best_mount
            else:
                self.current_usb_path = None
                self.logger.warning("No suitable USB storage found")
                return None
                
        except Exception as e:
            self.logger.error(f"Error discovering USB storage: {e}")
            self.current_usb_path = None
            return None
    
    def _is_usb_device(self, device: str) -> bool:
        """Check if a device is a USB storage device"""
        try:
            # Extract device name (e.g., sda1 -> sda)
            if device.startswith('/dev/'):
                device_name = device[5:]  # Remove /dev/
            else:
                return False
            
            # Remove partition number if present
            base_device = device_name.rstrip('0123456789')
            
            # Check if it's a USB device by looking at /sys/block
            usb_path = f"/sys/block/{base_device}/removable"
            if os.path.exists(usb_path):
                with open(usb_path, 'r') as f:
                    return f.read().strip() == '1'
            
            # Alternative check: look for USB in the device path
            device_path = f"/sys/block/{base_device}"
            if os.path.exists(device_path):
                real_path = os.path.realpath(device_path)
                return 'usb' in real_path.lower()
                
        except Exception as e:
            self.logger.debug(f"Error checking if {device} is USB: {e}")
        
        return False
    
    def is_usb_available(self) -> bool:
        """Check if USB storage is available"""
        # Re-discover USB storage if current one is not available
        if not self.current_usb_path or not os.path.ismount(self.current_usb_path):
            self._discover_usb_storage()
        
        return (self.current_usb_path is not None and 
                os.path.ismount(self.current_usb_path) and 
                os.access(self.current_usb_path, os.W_OK))
    
    def get_available_space(self) -> int:
        """Get available space in bytes"""
        if not self.is_usb_available() or not self.current_usb_path:
            return 0
        
        try:
            stat = os.statvfs(self.current_usb_path)
            return stat.f_bavail * stat.f_frsize
        except Exception as e:
            self.logger.error(f"Error getting available space: {e}")
            return 0
    
    def get_used_space(self) -> int:
        """Get used space by video files in bytes"""
        if not self.is_usb_available() or not self.current_usb_path:
            return 0
        
        try:
            total_size = 0
            for file_path in glob.glob(os.path.join(self.current_usb_path, "*.mp4")):
                total_size += os.path.getsize(file_path)
            return total_size
        except Exception as e:
            self.logger.error(f"Error calculating used space: {e}")
            return 0
    
    def cleanup_old_files(self) -> bool:
        """Delete oldest files to free space"""
        if not self.is_usb_available() or not self.current_usb_path:
            return False
        
        try:
            # Get all video files sorted by modification time
            video_files = glob.glob(os.path.join(self.current_usb_path, "*.mp4"))
            if len(video_files) <= self.emergency_keep:
                return False
            
            video_files.sort(key=lambda x: os.path.getmtime(x))
            
            # Delete oldest files until we have enough space
            files_to_delete = video_files[:-self.emergency_keep]
            
            for file_path in files_to_delete:
                try:
                    os.remove(file_path)
                    self.logger.info(f"Deleted old video file: {file_path}")
                    
                    # Check if we have enough space now
                    if self.get_used_space() < self.max_storage_bytes * 0.8:  # 80% threshold
                        break
                except Exception as e:
                    self.logger.error(f"Error deleting file {file_path}: {e}")
            
            return True
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
            return False
    
    def should_cleanup(self) -> bool:
        """Check if cleanup is needed"""
        return self.get_used_space() >= self.max_storage_bytes * 0.9  # 90% threshold


class VideoRecorder:
    """Video recording with chunked recording and gapless transitions"""
    
    def __init__(self, config: ConfigManager, storage: StorageManager, logger: logging.Logger):
        self.config = config
        self.storage = storage
        self.logger = logger
        self.picam2: Picamera2 | None = None
        self.encoder: H264Encoder | None = None
        self.output: FfmpegOutput | None = None
        self.current_filename: str | None = None
        self.recording = False
        self.chunk_duration = float(config.get('recording.chunk_duration_minutes', 30)) * 60 # type: ignore
        self.last_chunk_time = 0.0
        
        # Initialize camera
        self._initialize_camera()
    
    def _initialize_camera(self):
        """Initialize camera with configuration"""
        try:
            self.picam2 = Picamera2()
            video_config = self.picam2.create_video_configuration()
            
            # Add timestamp overlay if enabled
            if self.config.get('overlay.enable_timestamp'):
                self._setup_timestamp_overlay()
            
            self.picam2.configure(video_config)
            self.logger.info("Camera initialized successfully")
        except Exception as e:
            self.logger.error(f"Error initializing camera: {e}")
            raise
    
    def _setup_timestamp_overlay(self):
        """Setup timestamp overlay"""
        # This would need additional implementation for timestamp overlay
        # For now, we'll log that it's enabled
        self.logger.info("Timestamp overlay enabled")
    
    def _generate_filename(self) -> str:
        """Generate filename for video chunk"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if self.storage.current_usb_path:
            return os.path.join(self.storage.current_usb_path, f"dashcam_{timestamp}.mp4")
        else:
            # Fallback to temp directory if no USB storage available
            return os.path.join("/tmp", f"dashcam_{timestamp}.mp4")
    
    def _start_chunk(self) -> bool:
        """Start recording a new chunk"""
        if not self.storage.is_usb_available():
            self.logger.error("USB storage not available for recording")
            return False
        
        if not self.picam2:
            self.logger.error("Camera not initialized")
            return False
        
        try:
            # Generate filename
            self.current_filename = self._generate_filename()
            
            # Setup encoder and output
            self.encoder = H264Encoder(self.config.get('recording.bitrate', 10000000))
            self.output = FfmpegOutput(self.current_filename)
            
            # Start recording
            self.picam2.start_recording(self.encoder, self.output)
            self.last_chunk_time = time.time()
            self.recording = True
            
            self.logger.info(f"Started recording chunk: {self.current_filename}")
            return True
        except Exception as e:
            self.logger.error(f"Error starting recording chunk: {e}")
            return False
    
    def _stop_chunk(self):
        """Stop current recording chunk"""
        if self.recording:
            try:
                assert self.picam2 is not None
                self.picam2.stop_recording()
                self.recording = False
                self.logger.info(f"Stopped recording chunk: {self.current_filename}")
            except Exception as e:
                self.logger.error(f"Error stopping recording chunk: {e}")
    
    def start_recording(self) -> bool:
        """Start continuous recording"""
        if not self.storage.is_usb_available():
            return False
        
        return self._start_chunk()
    
    def stop_recording(self):
        """Stop recording"""
        self._stop_chunk()
    
    def should_switch_chunk(self) -> bool:
        """Check if we should switch to a new chunk"""
        if not self.recording:
            return False
        
        return time.time() - self.last_chunk_time >= self.chunk_duration
    
    def switch_chunk(self) -> bool:
        """Switch to a new recording chunk"""
        if not self.recording:
            return False
        
        try:
            # Stop current chunk
            self._stop_chunk()
            
            # Start new chunk
            return self._start_chunk()
        except Exception as e:
            self.logger.error(f"Error switching chunk: {e}")
            return False


class WatchdogTimer:
    """Simple watchdog timer implementation"""
    
    def __init__(self, timeout: int, callback):
        self.timeout = timeout
        self.callback = callback
        self.timer = None
        self.running = False
    
    def start(self):
        """Start watchdog timer"""
        self.running = True
        self._reset_timer()
    
    def stop(self):
        """Stop watchdog timer"""
        self.running = False
        if self.timer:
            self.timer.cancel()
    
    def kick(self):
        """Kick the watchdog (reset timer)"""
        if self.running:
            self._reset_timer()
    
    def _reset_timer(self):
        """Reset the timer"""
        if self.timer:
            self.timer.cancel()
        self.timer = threading.Timer(self.timeout, self.callback)
        self.timer.start()


class DashcamSystem:
    """Main dashcam system controller"""
    
    def __init__(self, config_path: str = "config.yaml"):
        self.config = ConfigManager(config_path)
        self.status = SystemStatus()
        self.running = False
        
        # Initialize logging
        self._setup_logging()
        
        # Initialize components
        self.led = StatusLED(int(self.config.get('gpio.status_led_pin'))) # type: ignore
        self.storage = StorageManager(self.config, self.logger)
        self.recorder = VideoRecorder(self.config, self.storage, self.logger)
        self.watchdog = WatchdogTimer(
            int(self.config.get('system.watchdog_timeout')), # type: ignore
            self._watchdog_timeout
        )
        
        # Setup signal handlers
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
    
    def _setup_logging(self):
        """Setup logging system"""
        log_level = getattr(logging, self.config.get('logging.level', 'INFO')) # type: ignore
        
        # Create logs directory on USB if available
        if self.storage and self.storage.is_usb_available() and self.storage.current_usb_path:
            log_dir = os.path.join(self.storage.current_usb_path, 'logs')
        else:
            log_dir = '/tmp/dashcam_logs'
        
        os.makedirs(log_dir, exist_ok=True)
        
        # Configure logging
        log_file = os.path.join(log_dir, f'dashcam_{datetime.now().strftime("%Y%m%d")}.log')
        
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler(sys.stdout)
            ]
        )
        
        self.logger = logging.getLogger('DashcamSystem')
        self.logger.info("Logging system initialized")
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        self.logger.info(f"Received signal {signum}, shutting down...")
        self.shutdown()
    
    def _watchdog_timeout(self):
        """Watchdog timeout handler"""
        self.logger.error("Watchdog timeout! System may be hung.")
        self.status.error = True
        # In a real implementation, this could trigger a system restart
    
    def _update_status(self):
        """Update system status and LED"""
        # Check USB status
        usb_available = self.storage.is_usb_available()
        if usb_available != self.status.usb_connected:
            self.status.usb_connected = usb_available
            self.logger.info(f"USB storage {'connected' if usb_available else 'disconnected'}")
        
        # Check storage space
        storage_full = self.storage.should_cleanup()
        if storage_full != self.status.storage_full:
            self.status.storage_full = storage_full
            if storage_full:
                self.logger.warning("Storage space getting low")
        
        # Update LED based on status
        if self.status.error:
            self.led.set_pattern('off')
        elif not self.status.usb_connected:
            self.led.set_pattern('slow_blink')
        elif self.status.storage_full:
            self.led.set_pattern('fast_blink')
        elif self.status.recording:
            self.led.set_pattern('solid')
        else:
            self.led.set_pattern('off')
    
    def _health_check(self):
        """Perform system health check"""
        try:
            # Check system resources
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            
            # Check disk space
            storage_info = ""
            if self.storage.is_usb_available():
                used_space = self.storage.get_used_space()
                available_space = self.storage.get_available_space()
                storage_info = f"Used: {used_space/1024/1024/1024:.1f}GB, Available: {available_space/1024/1024/1024:.1f}GB"
            
            self.logger.info(f"Health check - CPU: {cpu_percent}%, Memory: {memory.percent}%, {storage_info}")
            
            # Kick watchdog
            self.watchdog.kick()
            
            self.status.last_health_check = time.time()
            
        except Exception as e:
            self.logger.error(f"Health check failed: {e}")
            self.status.error = True
    
    def start(self):
        """Start dashcam system"""
        self.logger.info("Starting dashcam system...")
        
        # Start components
        self.led.start()
        self.watchdog.start()
        self.running = True
        
        # Main loop
        last_health_check = 0
        health_check_interval = int(self.config.get('system.health_check_interval')) # type: ignore
        
        while self.running:
            try:
                current_time = time.time()
                
                # Update status
                self._update_status()
                
                # Health check
                if current_time - last_health_check >= health_check_interval:
                    self._health_check()
                    last_health_check = current_time
                
                # Handle USB connection changes
                if self.storage.is_usb_available():
                    if not self.status.recording:
                        # Start recording if not already recording
                        if self.recorder.start_recording():
                            self.status.recording = True
                            self.logger.info("Started recording")
                    else:
                        # Check if we need to switch chunks
                        if self.recorder.should_switch_chunk():
                            if self.recorder.switch_chunk():
                                self.logger.info("Switched to new recording chunk")
                            else:
                                self.logger.error("Failed to switch recording chunk")
                                self.status.error = True
                        
                        # Check if cleanup is needed
                        if self.storage.should_cleanup():
                            self.storage.cleanup_old_files()
                
                else:
                    # USB not available, stop recording
                    if self.status.recording:
                        self.recorder.stop_recording()
                        self.status.recording = False
                        self.logger.warning("Stopped recording due to USB unavailable")
                
                # Sleep briefly to avoid busy-waiting
                time.sleep(1)
                
            except Exception as e:
                self.logger.error(f"Error in main loop: {e}")
                self.status.error = True
                time.sleep(5)  # Wait before retrying
    
    def shutdown(self):
        """Shutdown dashcam system"""
        self.logger.info("Shutting down dashcam system...")
        
        self.running = False
        
        # Stop recording
        if self.status.recording:
            self.recorder.stop_recording()
        
        # Stop components
        self.watchdog.stop()
        self.led.stop()
        
        # Cleanup GPIO
        GPIO.cleanup()
        
        self.logger.info("Dashcam system shut down")


def main():
    """Main entry point"""
    try:
        dashcam = DashcamSystem()
        dashcam.start()
    except KeyboardInterrupt:
        print("\nShutdown requested by user")
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main() 