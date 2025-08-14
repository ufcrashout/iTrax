#!/usr/bin/env python3
"""
iTrax Startup Script

This script can start both the tracker and web application together,
or run them separately based on command line arguments.
"""

import os
import sys
import time
import subprocess
import signal
import argparse
from pathlib import Path

def check_dependencies():
    """Check if required dependencies are installed"""
    try:
        import flask
        import pyicloud
        print("✅ All dependencies are installed")
        return True
    except ImportError as e:
        print(f"❌ Missing dependency: {e}")
        print("Please run: pip install -r requirements.txt")
        return False

def check_config():
    """Check if configuration is set up"""
    env_file = Path('.env')
    if not env_file.exists():
        print("❌ .env file not found")
        print("Please copy env_example.txt to .env and configure your credentials")
        return False
    
    # Check if required environment variables are set
    from config import Config
    if not Config.ICLOUD_EMAIL or not Config.ICLOUD_PASSWORD:
        print("❌ iCloud credentials not configured in .env file")
        return False
    
    print("✅ Configuration looks good")
    return True

def start_tracker():
    """Start the location tracker"""
    print("🚀 Starting iCloud location tracker...")
    try:
        subprocess.run([sys.executable, "tracker.py"], check=True)
    except KeyboardInterrupt:
        print("\n⏹️  Tracker stopped by user")
    except subprocess.CalledProcessError as e:
        print(f"❌ Tracker failed to start: {e}")

def start_webapp():
    """Start the web application"""
    print("🌐 Starting web application...")
    try:
        subprocess.run([sys.executable, "app.py"], check=True)
    except KeyboardInterrupt:
        print("\n⏹️  Web app stopped by user")
    except subprocess.CalledProcessError as e:
        print(f"❌ Web app failed to start: {e}")

def start_both():
    """Start both tracker and web app"""
    print("🚀 Starting iTrax (both tracker and web app)...")
    
    # Start tracker in background
    tracker_process = subprocess.Popen([sys.executable, "tracker.py"])
    print("✅ Tracker started in background")
    
    # Wait a moment for tracker to initialize
    time.sleep(2)
    
    # Start web app
    try:
        webapp_process = subprocess.Popen([sys.executable, "app.py"])
        print("✅ Web app started")
        print("🌐 Access the application at: http://localhost:5000")
        print("⏹️  Press Ctrl+C to stop both services")
        
        # Wait for either process to finish
        while True:
            if tracker_process.poll() is not None:
                print("❌ Tracker stopped unexpectedly")
                webapp_process.terminate()
                break
            if webapp_process.poll() is not None:
                print("❌ Web app stopped unexpectedly")
                tracker_process.terminate()
                break
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\n⏹️  Stopping services...")
        tracker_process.terminate()
        webapp_process.terminate()
        print("✅ Services stopped")

def main():
    parser = argparse.ArgumentParser(description='iTrax Startup Script')
    parser.add_argument('--tracker', action='store_true', help='Start only the tracker')
    parser.add_argument('--webapp', action='store_true', help='Start only the web app')
    parser.add_argument('--both', action='store_true', help='Start both tracker and web app (default)')
    parser.add_argument('--check', action='store_true', help='Check dependencies and configuration')
    
    args = parser.parse_args()
    
    print("🔍 iTrax Startup Script")
    print("=" * 40)
    
    # Check dependencies and config
    if not check_dependencies():
        sys.exit(1)
    
    if not check_config():
        sys.exit(1)
    
    if args.check:
        print("✅ All checks passed!")
        return
    
    # Determine what to start
    if args.tracker:
        start_tracker()
    elif args.webapp:
        start_webapp()
    else:
        # Default: start both
        start_both()

if __name__ == '__main__':
    main() 