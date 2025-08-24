import time
import json
import os
import logging
import http.cookiejar as cookiejar
import shutil
import pytz
from datetime import datetime, timedelta
from pyicloud import PyiCloudService
from pyicloud.exceptions import PyiCloudFailedLoginException, PyiCloudAPIResponseException
from config import Config
from database import db
from analytics import analytics

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(Config.LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class iCloudTracker:
    def __init__(self):
        self.api = None
        self.delay = Config.TRACKING_INTERVAL
        self.max_delay = Config.MAX_DELAY
        self.consecutive_failures = 0
        self.max_consecutive_failures = 5
        self.timezone = Config.get_timezone()
        
        # Migrate existing JSON data to database on first run
        self.migrate_existing_data()
        
    def get_current_time_cst(self):
        """Get current time in CST timezone"""
        utc_now = datetime.utcnow().replace(tzinfo=pytz.UTC)
        cst_now = utc_now.astimezone(self.timezone)
        return cst_now.isoformat()
    
    def convert_to_cst(self, timestamp_str):
        """Convert timestamp to CST"""
        try:
            # Parse timestamp (could be various formats)
            if isinstance(timestamp_str, str):
                if 'T' in timestamp_str:
                    if timestamp_str.endswith('Z'):
                        dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                    elif '+' in timestamp_str or timestamp_str.count(':') > 2:
                        dt = datetime.fromisoformat(timestamp_str)
                    else:
                        dt = datetime.fromisoformat(timestamp_str)
                        if dt.tzinfo is None:
                            dt = pytz.UTC.localize(dt)
                else:
                    dt = datetime.fromisoformat(timestamp_str)
                    if dt.tzinfo is None:
                        dt = pytz.UTC.localize(dt)
            else:
                dt = timestamp_str
                
            # Convert to CST
            if dt.tzinfo is None:
                dt = pytz.UTC.localize(dt)
            
            cst_dt = dt.astimezone(self.timezone)
            return cst_dt.isoformat()
        except Exception as e:
            logger.warning(f"Failed to convert timestamp to CST: {timestamp_str}, error: {e}")
            return timestamp_str
        
    def migrate_existing_data(self):
        """Migrate existing JSON data to database if it exists"""
        try:
            db.migrate_json_data()
        except Exception as e:
            logger.error(f"Failed to migrate existing data: {e}")
        
    def validate_location_data(self, location_data):
        """Validate location data before saving, filter out invalid entries and detect stale data"""
        required_fields = ['device_name', 'latitude', 'longitude', 'timestamp']
        valid_entries = []
        current_time = datetime.now()
        
        for entry in location_data:
            is_valid = True
            
            # Check required fields
            for field in required_fields:
                if field not in entry:
                    logger.warning(f"Missing required field '{field}' in location entry for {entry.get('device_name', 'Unknown')}")
                    is_valid = False
                    break
            
            if not is_valid:
                continue
                
            # Validate coordinates
            try:
                lat = float(entry['latitude'])
                lon = float(entry['longitude'])
                
                if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                    logger.warning(f"Invalid coordinates for {entry['device_name']}: {lat}, {lon}")
                    is_valid = False
                    
            except (ValueError, TypeError):
                logger.warning(f"Invalid coordinate format for {entry['device_name']}: {entry['latitude']}, {entry['longitude']}")
                is_valid = False
            
            if not is_valid:
                continue
                
            # Validate timestamp and check for stale data
            try:
                location_time = datetime.fromisoformat(entry['timestamp'].replace('Z', '+00:00'))
                
                # Check if location is older than 24 hours (likely stale)
                age_hours = (current_time - location_time.replace(tzinfo=None)).total_seconds() / 3600
                
                if age_hours > 24:
                    logger.warning(f"Potentially stale location data for {entry['device_name']}: {age_hours:.1f} hours old")
                    # Mark as potentially stale but still save it (users can decide)
                    entry['is_stale'] = True
                    entry['age_hours'] = round(age_hours, 1)
                else:
                    entry['is_stale'] = False
                    entry['age_hours'] = round(age_hours, 1)
                    
            except ValueError:
                logger.warning(f"Invalid timestamp format for {entry['device_name']}: {entry['timestamp']}")
                is_valid = False
            
            if is_valid:
                valid_entries.append(entry)
        
        if len(valid_entries) != len(location_data):
            logger.info(f"Filtered {len(location_data) - len(valid_entries)} invalid entries, {len(valid_entries)} valid entries remain")
        
        # Log stale data warnings
        stale_count = sum(1 for entry in valid_entries if entry.get('is_stale', False))
        if stale_count > 0:
            logger.warning(f"Detected {stale_count} potentially stale location entries (>24h old)")
        
        return valid_entries

    def backup_database(self):
        """Create a backup of the database"""
        try:
            db.backup_database()
        except Exception as e:
            logger.error(f"Failed to create database backup: {e}")

    def get_icloud_service(self):
        """Log in to iCloud and handle 2FA if necessary."""
        logger.info("Initializing iCloud service")
        
        if not Config.ICLOUD_EMAIL or not Config.ICLOUD_PASSWORD:
            logger.error("iCloud credentials not configured. Please set ICLOUD_EMAIL and ICLOUD_PASSWORD environment variables.")
            return None
            
        try:
            # Clean up expired sessions first
            db.cleanup_expired_sessions()
            
            # Try to load saved session from database first
            session_data = db.get_valid_session()
            if session_data:
                logger.debug("Loading saved session from database...")
                try:
                    api = PyiCloudService(Config.ICLOUD_EMAIL, Config.ICLOUD_PASSWORD)
                    # Parse session data and restore
                    session_cookies = json.loads(session_data)
                    # Restore cookies to session
                    for name, value in session_cookies.items():
                        api.session.cookies.set(name, value)
                    
                    # Test if session is still valid
                    try:
                        _ = api.devices
                        logger.info("Session restored successfully from database.")
                        return api
                    except (PyiCloudAPIResponseException, Exception) as e:
                        logger.warning(f"Session invalid ({e}), logging in again.")
                except Exception as e:
                    logger.error(f"Failed to load saved session: {e}")
            
            # If no session or session invalid, create new connection
            logger.info("Creating new iCloud session.")
            api = PyiCloudService(Config.ICLOUD_EMAIL, Config.ICLOUD_PASSWORD)
            
            # Check if 2FA is required
            if api.requires_2fa:
                logger.info("2FA authentication required.")
                code = input("Enter the 2FA verification code: ")
                if not api.validate_2fa_code(code):
                    logger.error("Failed to verify 2FA code.")
                    raise PyiCloudFailedLoginException("Failed to verify 2FA code.")
                logger.info("2FA verification successful.")
            
            # Verify login by accessing devices
            try:
                devices = api.devices
                device_list = list(devices)
                logger.info(f"Successfully authenticated. Found {len(device_list)} devices.")
            except Exception as e:
                logger.error(f"Failed to access devices after authentication: {e}")
                raise PyiCloudFailedLoginException(f"Authentication verification failed: {e}")
            
            # Save session to database with 30-day expiration
            try:
                session_cookies = {}
                for cookie in api.session.cookies:
                    session_cookies[cookie.name] = cookie.value
                
                # Set expiration to 30 days from now
                expires_at = (datetime.now() + timedelta(days=30)).isoformat()
                db.save_session(json.dumps(session_cookies), expires_at)
                logger.info("Session saved to database with 30-day expiration.")
            except Exception as e:
                logger.warning(f"Failed to save session: {e}")
            return api
            
        except PyiCloudFailedLoginException as e:
            logger.error(f"Login failed: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error during login: {e}")
            return None

    def log_rate_limit_headers(self, response):
        """Log rate limit headers if available"""
        if response is not None and response.headers:
            headers_to_log = ['X-Rate-Limit-Limit', 'X-Rate-Limit-Remaining', 'X-Rate-Limit-Reset']
            for header in headers_to_log:
                if header in response.headers:
                    logger.info(f"{header}: {response.headers[header]}")

    def save_location_data(self, location_data):
        """Save location data to database"""
        try:
            # Validate data before saving and get only valid entries
            valid_location_data = self.validate_location_data(location_data)
            if not valid_location_data:
                logger.error("No valid location data to save")
                return False
            
            # Create backup before modifying
            self.backup_database()
            
            # Save to database
            success = db.save_location_data(valid_location_data)
            
            if success:
                logger.info(f"Saved {len(valid_location_data)} location entries to database")
                
                # Check geofences for each location
                self.check_geofences(valid_location_data)
                
                return True
            else:
                logger.error("Failed to save location data to database")
                return False
            
        except Exception as e:
            logger.error(f"Error saving location data: {e}")
            return False

    def fetch_device_locations(self):
        """Fetch locations for all devices"""
        try:
            logger.debug("Fetching devices from iCloud API")
            devices = self.api.devices
            current_locations = []
            timestamp = self.get_current_time_cst()
            
            for device in devices:
                try:
                    # Try multiple methods to get device name
                    device_name = None
                    
                    # Method 1: Try device.name attribute
                    if hasattr(device, 'name') and device.name:
                        device_name = device.name
                        logger.debug(f"Method 1 - device.name: {device_name}")
                    
                    # Method 2: Try device['name'] if it's a dict-like object
                    if not device_name:
                        try:
                            device_name = device['name']
                            logger.debug(f"Method 2 - device['name']: {device_name}")
                        except (KeyError, TypeError):
                            pass
                    
                    # Method 3: Try device.status() and extract name
                    if not device_name:
                        try:
                            device_info = device.status()
                            if isinstance(device_info, dict) and 'name' in device_info:
                                device_name = device_info['name']
                                logger.debug(f"Method 3 - device.status()['name']: {device_name}")
                        except Exception as e:
                            logger.debug(f"Method 3 failed: {e}")
                    
                    # Method 4: Try other common name attributes
                    if not device_name:
                        for attr in ['device_name', 'deviceName', 'display_name', 'displayName']:
                            if hasattr(device, attr) and getattr(device, attr):
                                device_name = getattr(device, attr)
                                logger.debug(f"Method 4 - device.{attr}: {device_name}")
                                break
                    
                    # Default if all methods fail
                    if not device_name:
                        device_name = f"Unknown device ({type(device).__name__})"
                        
                    logger.debug(f"Final device name: {device_name}")
                    logger.debug(f"Device object type: {type(device)}")
                    logger.debug(f"Device attributes: {[attr for attr in dir(device) if not attr.startswith('_')]}")
                    
                    # Try multiple methods to get location data
                    location = None
                    
                    # Method 1: Try device.location() if it exists
                    if hasattr(device, 'location'):
                        try:
                            location = device.location()
                            logger.debug(f"Method 1 - device.location() returned: {location}")
                        except Exception as e:
                            logger.debug(f"Method 1 failed: {e}")
                    
                    # Method 2: Try device.status() and extract location
                    if not location:
                        try:
                            device_info = device.status()
                            location = device_info.get('location')
                            logger.debug(f"Method 2 - device.status()['location'] returned: {location}")
                        except Exception as e:
                            logger.debug(f"Method 2 failed: {e}")
                    
                    # Method 3: Try direct access to location property
                    if not location and hasattr(device, '_location'):
                        try:
                            location = device._location
                            logger.debug(f"Method 3 - device._location returned: {location}")
                        except Exception as e:
                            logger.debug(f"Method 3 failed: {e}")
                    
                    # Process location if found
                    if location:
                        logger.debug(f"Location object for {device_name}: {location}")
                        
                        # Try different ways to extract lat/lng
                        latitude = longitude = None
                        
                        # Try direct access
                        if isinstance(location, dict):
                            latitude = location.get('latitude')
                            longitude = location.get('longitude')
                        
                        # Try as object attributes
                        if latitude is None and hasattr(location, 'latitude'):
                            latitude = location.latitude
                        if longitude is None and hasattr(location, 'longitude'):
                            longitude = location.longitude
                            
                        # Try alternative names
                        if latitude is None and hasattr(location, 'lat'):
                            latitude = location.lat
                        if longitude is None and hasattr(location, 'lng'):
                            longitude = location.lng
                        
                        logger.debug(f"Extracted coordinates for {device_name}: lat={latitude}, lng={longitude}")
                        
                        if latitude is not None and longitude is not None:
                            # Try to extract additional device information
                            accuracy = None
                            battery_level = None
                            is_charging = None
                            
                            # Try to get device status for battery and charging info
                            try:
                                device_info = device.status()
                                if isinstance(device_info, dict):
                                    # Extract battery information
                                    if 'batteryLevel' in device_info:
                                        battery_level = device_info['batteryLevel']
                                    elif 'battery_level' in device_info:
                                        battery_level = device_info['battery_level']
                                    
                                    # Extract charging status
                                    if 'batteryStatus' in device_info:
                                        # batteryStatus can be "Charging", "NotCharging", "Unknown", etc.
                                        is_charging = device_info['batteryStatus'].lower() == 'charging'
                                    elif 'charging' in device_info:
                                        is_charging = device_info['charging']
                                    elif 'isCharging' in device_info:
                                        is_charging = device_info['isCharging']
                                    
                                    logger.debug(f"Device status for {device_name}: {device_info}")
                            except Exception as e:
                                logger.debug(f"Could not get device status for {device_name}: {e}")
                            
                            # Try to get location accuracy from location object
                            try:
                                if isinstance(location, dict):
                                    if 'horizontalAccuracy' in location:
                                        accuracy = location['horizontalAccuracy']
                                    elif 'accuracy' in location:
                                        accuracy = location['accuracy']
                                elif hasattr(location, 'horizontalAccuracy'):
                                    accuracy = location.horizontalAccuracy
                                elif hasattr(location, 'accuracy'):
                                    accuracy = location.accuracy
                                
                                logger.debug(f"Location accuracy for {device_name}: {accuracy}")
                            except Exception as e:
                                logger.debug(f"Could not get location accuracy for {device_name}: {e}")
                            
                            location_entry = {
                                'device_name': device_name,
                                'latitude': latitude,
                                'longitude': longitude,
                                'timestamp': timestamp,
                                'accuracy': accuracy,
                                'battery_level': battery_level,
                                'is_charging': is_charging
                            }
                            current_locations.append(location_entry)
                            
                            logger.info(f"Device {device_name} Location: {latitude}, {longitude} at {timestamp}")
                        else:
                            logger.warning(f"Invalid location coordinates for {device_name}: lat={latitude}, lng={longitude}")
                    else:
                        logger.warning(f"No location available for {device_name}")
                        
                except Exception as e:
                    logger.error(f"Error processing device {device}: {e}")
                    import traceback
                    logger.debug(f"Full traceback: {traceback.format_exc()}")
                    continue
            
            if current_locations:
                if self.save_location_data(current_locations):
                    self.consecutive_failures = 0  # Reset failure counter
                    self.delay = Config.TRACKING_INTERVAL  # Reset delay on success
                else:
                    self.consecutive_failures += 1
            else:
                logger.warning("No location data retrieved from any device")
                self.consecutive_failures += 1
                
        except PyiCloudAPIResponseException as e:
            logger.error(f"API error occurred: {e}")
            self.consecutive_failures += 1
            self.delay = min(self.delay * 2, self.max_delay)  # Exponential backoff
            logger.info(f"Increasing delay to {self.delay // 60} minutes due to rate limiting.")
        except Exception as e:
            logger.error(f"Unexpected error fetching locations: {e}")
            self.consecutive_failures += 1

    def should_restart_session(self):
        """Check if we should restart the iCloud session due to repeated failures"""
        return self.consecutive_failures >= self.max_consecutive_failures

    def cleanup_old_data(self):
        """Clean up old data to prevent database bloat"""
        try:
            # Clean up data older than 30 days
            db.cleanup_old_data(days_to_keep=30)
        except Exception as e:
            logger.error(f"Failed to cleanup old data: {e}")

    def run(self):
        """Main tracking loop with improved error handling"""
        logger.info("Starting iCloud location tracker")
        
        # Log startup to database
        db.log_message("INFO", "iTrax started", "tracker")
        
        while True:
            try:
                # Initialize or reinitialize iCloud service
                if not self.api or self.should_restart_session():
                    logger.info("Initializing iCloud service...")
                    self.api = self.get_icloud_service()
                    if not self.api:
                        logger.error("Failed to initialize iCloud service. Waiting before retry...")
                        db.log_message("ERROR", "Failed to initialize iCloud service", "tracker")
                        time.sleep(300)  # Wait 5 minutes before retrying
                        continue
                    
                    self.consecutive_failures = 0  # Reset failure counter
                    logger.info("iCloud service initialized successfully")
                    db.log_message("INFO", "iCloud service initialized successfully", "tracker")
                
                # Fetch device locations
                self.fetch_device_locations()
                
                # Periodic cleanup (every 24 hours)
                if datetime.now().hour == 2 and datetime.now().minute < 5:  # Run around 2 AM
                    self.cleanup_old_data()
                
                # Log status
                logger.info(f"Waiting {self.delay // 60} minutes before next request... (Failures: {self.consecutive_failures})")
                time.sleep(self.delay)
                
            except KeyboardInterrupt:
                logger.info("Tracker stopped by user")
                db.log_message("INFO", "Tracker stopped by user", "tracker")
                break
            except Exception as e:
                logger.error(f"Unexpected error in main loop: {e}")
                db.log_message("ERROR", f"Unexpected error in main loop: {e}", "tracker")
                self.consecutive_failures += 1
                time.sleep(60)  # Wait 1 minute before retrying
    
    def check_geofences(self, location_data):
        """Check geofences for new location data"""
        try:
            for location in location_data:
                device_name = location['device_name']
                latitude = float(location['latitude'])
                longitude = float(location['longitude'])
                
                # Check for geofence violations
                violations = analytics.check_geofence_violations(device_name, latitude, longitude)
                
                if violations:
                    logger.info(f"Geofence violations detected for {device_name}: {len(violations)} events")
                    for violation in violations:
                        logger.info(f"  {violation['type'].upper()}: {violation['geofence']['name']}")
                
        except Exception as e:
            logger.error(f"Error checking geofences: {e}")

def main():
    """Main entry point"""
    tracker = iCloudTracker()
    tracker.run()

if __name__ == '__main__':
    main() 