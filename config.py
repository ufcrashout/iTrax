import os
from datetime import timedelta
import pytz
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    # Flask Configuration
    SECRET_KEY = os.environ.get('SECRET_KEY') or os.urandom(32).hex()
    
    # iCloud Configuration
    ICLOUD_EMAIL = os.environ.get('ICLOUD_EMAIL', '')
    ICLOUD_PASSWORD = os.environ.get('ICLOUD_PASSWORD', '')
    
    # User Authentication
    USERS = {
        os.environ.get('ADMIN_USERNAME', 'admin'): os.environ.get('ADMIN_PASSWORD', 'change_me')
    }
    
    # Geocoding API Configuration (all optional, free providers used by default)
    GOOGLE_GEOCODING_API_KEY = os.environ.get('GOOGLE_GEOCODING_API_KEY', '')
    MAPBOX_API_KEY = os.environ.get('MAPBOX_API_KEY', '')
    HERE_API_KEY = os.environ.get('HERE_API_KEY', '')
    
    # Geocoding Settings
    GEOCODING_CACHE_HOURS = int(os.environ.get('GEOCODING_CACHE_HOURS', 24))
    GEOCODING_CACHE_SIZE = int(os.environ.get('GEOCODING_CACHE_SIZE', 1000))
    GEOCODING_MAX_PROVIDERS = int(os.environ.get('GEOCODING_MAX_PROVIDERS', 3))
    
    # File Paths
    LOCATION_FILE = "iphone_locations_history.json"  # For migration purposes
    SESSION_FILE = "icloud_session.cookies"  # For migration purposes
    LOG_FILE = "api_rate_limit.log"
    DATABASE_FILE = "icloud_tracker.db"
    
    # Tracking Configuration
    TRACKING_INTERVAL = int(os.environ.get('TRACKING_INTERVAL', 600))  # 10 minutes default
    MAX_DELAY = int(os.environ.get('MAX_DELAY', 3600))  # 1 hour max delay
    
    # Database Configuration
    DATABASE_HOST = os.environ.get('DB_HOST', 'localhost')
    DATABASE_PORT = int(os.environ.get('DB_PORT', 3306))
    DATABASE_USER = os.environ.get('DB_USER', 'icloud_app')
    DATABASE_PASSWORD = os.environ.get('DB_PASSWORD', '')
    DATABASE_NAME = os.environ.get('DB_NAME', 'icloud_tracker')
    DATABASE_CLEANUP_DAYS = int(os.environ.get('DATABASE_CLEANUP_DAYS', 30))
    DATABASE_BACKUP_RETENTION = int(os.environ.get('DATABASE_BACKUP_RETENTION', 5))
    DATABASE_BACKUP_RETENTION_DAYS = int(os.environ.get('DATABASE_BACKUP_RETENTION_DAYS', 14))
    BACKUP_DIRECTORY = os.environ.get('BACKUP_DIRECTORY', 'backups')
    BACKUP_SCHEDULE_TIMES = os.environ.get('BACKUP_SCHEDULE_TIMES', '06:00,14:00,22:00').split(',')
    
    # Flask-Login Configuration
    REMEMBER_COOKIE_DURATION = timedelta(days=30)
    REMEMBER_COOKIE_SECURE = False  # Set to True if using HTTPS
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = 'Lax'
    SESSION_PROTECTION = 'strong'
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)
    
    # Security
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600
    
    # Timezone Configuration
    TIMEZONE = os.environ.get('TIMEZONE', 'America/Chicago')  # CST/CDT
    
    @classmethod
    def get_timezone(cls):
        """Get the configured timezone object"""
        return pytz.timezone(cls.TIMEZONE) 