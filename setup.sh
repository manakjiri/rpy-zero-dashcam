#!/bin/bash

# Raspberry Pi Dashcam Setup Script
# Run this on your Raspberry Pi to set up the dashcam system

set -e

echo "Setting up Raspberry Pi Dashcam System..."

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    echo "Please run this script as a regular user, not root"
    exit 1
fi

# Create project directory
INSTALL_DIR="$HOME/dashcam"
echo "Creating project directory: $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"

# Copy files to installation directory
echo "Copying files..."
cp config.yaml "$INSTALL_DIR/"
cp dashcam.py "$INSTALL_DIR/"
cp pyproject.toml "$INSTALL_DIR/"

# Create virtual environment
echo "Creating virtual environment..."
cd "$INSTALL_DIR"
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install --upgrade pip
pip install -r <(grep -v "^#" pyproject.toml | grep -A100 "dependencies" | grep -v "dependencies" | sed 's/[",]//g' | head -20)

# Install systemd service
echo "Installing systemd service..."
sudo cp dashcam.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable dashcam.service

# Enable camera
echo "Enabling camera..."
sudo raspi-config nonint do_camera 0

# Create log directory
mkdir -p /tmp/dashcam_logs

echo ""
echo "Setup complete! Please:"
echo "1. Reboot your Raspberry Pi"
echo "2. Insert any USB drive (formatted as FAT32, exFAT, or ext4)"
echo "3. Connect status LED to GPIO pin 18 (or modify config.yaml)"
echo "4. The dashcam will automatically discover and use the USB drive"
echo "5. Recording starts automatically on boot when USB is detected"
echo ""
echo "To check status: sudo systemctl status dashcam"
echo "To view logs: sudo journalctl -u dashcam -f"
echo "To modify config: nano $INSTALL_DIR/config.yaml"
echo ""
echo "Reboot now? (y/n)"
read -r response
if [[ "$response" =~ ^[Yy]$ ]]; then
    sudo reboot
fi 