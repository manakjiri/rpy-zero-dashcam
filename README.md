# Raspberry Pi Zero 2 Dashcam System

A robust, continuous recording dashcam system built for Raspberry Pi Zero 2 with Camera Module v2. Features chunked recording, USB hot-plug support, storage management, and status LED indication.

## Features

- **Continuous Recording**: 30-minute video chunks with gapless transitions
- **USB Auto-Discovery**: Automatically finds and uses any USB flash drive (no fixed mount path needed)
- **Storage Management**: Automatic cleanup of old files when storage limit is reached
- **Status LED**: Visual indication of system status (recording, storage issues, etc.)
- **Timestamp Overlay**: Date/time overlay on video recordings
- **Watchdog Timer**: System recovery mechanism for unexpected crashes
- **Logging**: Comprehensive logging to USB storage for troubleshooting
- **Power Loss Protection**: Designed to handle sudden power cuts gracefully

## Hardware Requirements

- Raspberry Pi Zero 2 W
- Camera Module v2 (or compatible)
- USB flash drive (32GB recommended)
- Status LED connected to GPIO pin 18 (or configured pin)
- MicroSD card (8GB minimum, read-only file system recommended)

## Status LED Patterns

- **Solid On**: Recording normally
- **Slow Blink (1Hz)**: No USB storage detected
- **Fast Blink (5Hz)**: Low disk space warning
- **Off**: System error or not recording

## Installation

### Quick Setup

1. Clone this repository to your Raspberry Pi Zero 2
2. Make the setup script executable:
   ```bash
   chmod +x setup.sh
   ```
3. Run the setup script:
   ```bash
   ./setup.sh
   ```
4. Follow the prompts and reboot when asked

### Manual Installation

1. **Install Dependencies**:
   ```bash
   sudo apt update
   sudo apt install python3-pip python3-venv git
   ```

2. **Create Project Directory**:
   ```bash
   mkdir -p /home/pi/dashcam
   cd /home/pi/dashcam
   ```

3. **Setup Virtual Environment**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install PyYAML RPi.GPIO psutil picamera2
   ```

4. **Copy Files**:
   ```bash
   cp config.yaml dashcam.py pyproject.toml /home/pi/dashcam/
   ```

5. **Enable Camera**:
   ```bash
   sudo raspi-config nonint do_camera 0
   ```

6. **USB Auto-Discovery**:
   ```bash
   # No setup needed - USB storage is automatically discovered
   ```

7. **Install Service**:
   ```bash
   sudo cp dashcam.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable dashcam.service
   ```

## Configuration

Edit `config.yaml` to customize the dashcam behavior:

```yaml
recording:
  chunk_duration_minutes: 30    # Length of each video file
  bitrate: 10000000            # Video bitrate (10 Mbps)

storage:
  max_storage_gb: 32           # Maximum storage to use
  emergency_files_keep: 5      # Recent files to never delete
  # USB storage is auto-discovered - no mount path needed

gpio:
  status_led_pin: 18           # GPIO pin for status LED

system:
  watchdog_timeout: 30         # Watchdog timeout in seconds
  health_check_interval: 60    # Health check interval

overlay:
  enable_timestamp: true       # Enable timestamp on video
  timestamp_format: "%Y-%m-%d %H:%M:%S"
```

## Operation

### Starting the Service

The dashcam starts automatically on boot. You can also control it manually:

```bash
# Start the service
sudo systemctl start dashcam

# Stop the service
sudo systemctl stop dashcam

# Check status
sudo systemctl status dashcam

# View logs
sudo journalctl -u dashcam -f
```

### USB Storage

1. Format USB drive as FAT32, exFAT, or ext4
2. Insert into Raspberry Pi
3. System automatically discovers and uses the USB drive
4. Recording starts immediately when USB storage is detected
5. Video files are saved as `dashcam_YYYYMMDD_HHMMSS.mp4`
6. Logs are saved in `<usb_mount_point>/logs/`

**Auto-Discovery Features:**
- Automatically finds any USB flash drive (no configuration needed)
- Prefers larger capacity drives if multiple USB devices are connected
- Supports common filesystems: FAT32, exFAT, ext4
- Minimum 1GB storage requirement for device selection

### File Management

- Videos are automatically deleted when storage is 90% full
- The 5 most recent files are always preserved
- Each video file is approximately 30 minutes long
- Filenames include timestamp for easy identification

## Troubleshooting

### Common Issues

1. **Camera Not Detected**:
   ```bash
   # Check camera connection
   vcgencmd get_camera
   
   # Enable camera if needed
   sudo raspi-config nonint do_camera 0
   ```

2. **USB Not Detected**:
   ```bash
   # Check USB devices
   lsblk
   
   # Check if USB is recognized
   dmesg | grep -i usb
   
   # Restart dashcam service to re-scan
   sudo systemctl restart dashcam
   ```

3. **Service Not Starting**:
   ```bash
   # Check service status
   sudo systemctl status dashcam
   
   # Check logs
   sudo journalctl -u dashcam
   ```

### Log Files

Logs are stored in:
- `<auto-discovered-usb-path>/logs/` (when USB is available)
- `/tmp/dashcam_logs/` (fallback location when no USB detected)

### Performance Optimization

For Raspberry Pi Zero 2, consider these optimizations:

1. **Video Settings**:
   - Default 1920x1080 at 10 Mbps works well
   - Reduce bitrate if performance issues occur
   - Consider 1280x720 for better performance

2. **System**:
   - Use Class 10 or better microSD card
   - Enable GPU memory split: `gpu_mem=128`
   - Disable unnecessary services

## Power Considerations

This system is designed for automotive use where power may be cut suddenly:

- Root filesystem should be read-only to prevent corruption
- All recordings and logs are stored on USB
- File operations use sync writes for data integrity
- System handles power loss gracefully

### Setting Up Read-Only Root

To make the root filesystem read-only:

```bash
# Edit /boot/cmdline.txt and add:
# fastboot noswap ro

# Edit /etc/fstab to mount root as read-only
```

## License

This project is open source. Use and modify as needed for your dashcam project.

## Contributing

Feel free to submit issues and pull requests to improve the system.

## Safety Notice

- Ensure proper mounting of the camera and Pi
- Check local laws regarding dashcam usage
- Regularly check and maintain the system
- Use appropriate power supply and wiring
