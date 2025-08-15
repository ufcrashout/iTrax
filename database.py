import pymysql
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from config import Config
import os
import pytz
from cache import location_cache, dashboard_cache, cached_query, QueryTimer

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_config: Dict = None):
        """Initialize database connection"""
        if db_config is None:
            # Default MariaDB configuration
            self.db_config = {
                'host': os.getenv('DB_HOST', 'localhost'),
                'port': int(os.getenv('DB_PORT', 3306)),
                'user': os.getenv('DB_USER', 'icloud_app'),
                'password': os.getenv('DB_PASSWORD', ''),
                'database': os.getenv('DB_NAME', 'icloud_tracker'),
                'charset': 'utf8mb4',
                'cursorclass': pymysql.cursors.DictCursor,
                'autocommit': True
            }
        else:
            self.db_config = db_config
            # Ensure DictCursor is always used
            self.db_config['cursorclass'] = pymysql.cursors.DictCursor
        
        self.init_database()
        self.init_default_admin()
    
    def _convert_timestamp_for_mysql(self, timestamp_str: str) -> str:
        """Convert timezone-aware timestamp to MySQL-compatible format"""
        try:
            # Parse the timezone-aware timestamp
            if isinstance(timestamp_str, str):
                # Handle various formats
                if timestamp_str.endswith('Z'):
                    dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                elif '+' in timestamp_str[-6:] or '-' in timestamp_str[-6:]:
                    dt = datetime.fromisoformat(timestamp_str)
                else:
                    # Assume UTC if no timezone
                    dt = datetime.fromisoformat(timestamp_str)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=pytz.UTC)
            else:
                dt = timestamp_str
            
            # Convert to UTC and format for MySQL
            if dt.tzinfo is not None:
                utc_dt = dt.astimezone(pytz.UTC)
            else:
                utc_dt = dt.replace(tzinfo=pytz.UTC)
            
            # Return MySQL-compatible format (without timezone)
            return utc_dt.strftime('%Y-%m-%d %H:%M:%S')
            
        except Exception as e:
            logger.error(f"Error converting timestamp '{timestamp_str}': {e}")
            # Fallback: return current time
            return datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    
    def get_connection(self):
        """Get a database connection with dictionary cursor"""
        try:
            conn = pymysql.connect(**self.db_config)
            return conn
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            raise
    
    def init_database(self):
        """Initialize the database with required tables"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Users table
                cursor.execute("""CREATE TABLE IF NOT EXISTS users (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(255) UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    is_admin BOOLEAN DEFAULT FALSE,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_login TIMESTAMP NULL,
                    INDEX idx_username (username)
                ) ENGINE=InnoDB""")
                
                # Add is_admin column if it doesn't exist (for existing databases)
                try:
                    cursor.execute("""ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT FALSE""")
                    cursor.execute("""ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT TRUE""")
                except pymysql.Error:
                    # Columns already exist, which is fine
                    pass
                
                # User settings table
                cursor.execute("""CREATE TABLE IF NOT EXISTS user_settings (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id INT NOT NULL,
                    timezone VARCHAR(50) NOT NULL DEFAULT 'America/Chicago',
                    date_format VARCHAR(20) DEFAULT '%Y-%m-%d %I:%M:%S %p',
                    theme VARCHAR(20) DEFAULT 'light',
                    map_default_zoom INT DEFAULT 10,
                    refresh_interval INT DEFAULT 300,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    UNIQUE KEY unique_user_settings (user_id),
                    INDEX idx_user_id (user_id)
                ) ENGINE=InnoDB""")
                
                # Devices table
                cursor.execute("""CREATE TABLE IF NOT EXISTS devices (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    device_name VARCHAR(255) NOT NULL,
                    device_id VARCHAR(255) UNIQUE,
                    device_type VARCHAR(100),
                    nickname VARCHAR(255),
                    is_active BOOLEAN DEFAULT TRUE,
                    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_device_name (device_name),
                    INDEX idx_device_id (device_id)
                ) ENGINE=InnoDB""")
                
                # Locations table - main performance critical table with optimized indexes
                cursor.execute("""CREATE TABLE IF NOT EXISTS locations (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    device_id INT,
                    device_name VARCHAR(255) NOT NULL,
                    latitude DECIMAL(10,8) NOT NULL,
                    longitude DECIMAL(11,8) NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    accuracy FLOAT,
                    battery_level TINYINT UNSIGNED,
                    is_charging BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_device_name (device_name),
                    INDEX idx_timestamp_desc (timestamp DESC),
                    INDEX idx_location (latitude, longitude),
                    INDEX idx_device_time_desc (device_name, timestamp DESC),
                    INDEX idx_time_device_asc (timestamp ASC, device_name),
                    INDEX idx_created_at (created_at DESC),
                    INDEX idx_composite_analytics (device_name, timestamp DESC, latitude, longitude),
                    FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE
                ) ENGINE=InnoDB""")
                
                # Add performance optimized indexes for GPS logs queries (without function-based indexes)
                try:
                    cursor.execute("""CREATE INDEX IF NOT EXISTS idx_gps_logs_performance 
                                     ON locations (timestamp DESC, device_name, id)""")
                    # Note: MariaDB doesn't support DATE() function in index definitions directly
                    # We'll rely on timestamp-based indexes instead
                    logger.debug("Created GPS performance indexes successfully")
                except Exception as idx_error:
                    logger.debug(f"Index creation note (may already exist): {idx_error}")
                
                # Sessions table
                cursor.execute("""CREATE TABLE IF NOT EXISTS sessions (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    session_data TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP NULL,
                    is_valid BOOLEAN DEFAULT TRUE,
                    INDEX idx_expires (expires_at),
                    INDEX idx_valid (is_valid)
                ) ENGINE=InnoDB""")
                
                # Logs table
                cursor.execute("""CREATE TABLE IF NOT EXISTS logs (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    level VARCHAR(20) NOT NULL,
                    message TEXT NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    source VARCHAR(100),
                    INDEX idx_level (level),
                    INDEX idx_timestamp (timestamp),
                    INDEX idx_source (source)
                ) ENGINE=InnoDB""")
                
                # Geofences table
                cursor.execute("""CREATE TABLE IF NOT EXISTS geofences (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    center_lat DECIMAL(10,8) NOT NULL,
                    center_lng DECIMAL(11,8) NOT NULL,
                    radius_meters INT NOT NULL,
                    device_filter VARCHAR(255),
                    alert_types VARCHAR(255) DEFAULT 'enter,exit',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT TRUE,
                    INDEX idx_active (is_active),
                    INDEX idx_center (center_lat, center_lng)
                ) ENGINE=InnoDB""")
                
                # Device geofence status table
                cursor.execute("""CREATE TABLE IF NOT EXISTS device_geofence_status (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    device_name VARCHAR(255) NOT NULL,
                    geofence_id INT NOT NULL,
                    is_inside BOOLEAN DEFAULT FALSE,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY unique_device_geofence (device_name, geofence_id),
                    INDEX idx_device (device_name),
                    FOREIGN KEY (geofence_id) REFERENCES geofences(id) ON DELETE CASCADE
                ) ENGINE=InnoDB""")
                
                # Geofence events table
                cursor.execute("""CREATE TABLE IF NOT EXISTS geofence_events (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    device_name VARCHAR(255) NOT NULL,
                    geofence_id INT NOT NULL,
                    event_type VARCHAR(20) NOT NULL,
                    latitude DECIMAL(10,8) NOT NULL,
                    longitude DECIMAL(11,8) NOT NULL,
                    distance_meters FLOAT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_device (device_name),
                    INDEX idx_timestamp (timestamp),
                    INDEX idx_event_type (event_type),
                    FOREIGN KEY (geofence_id) REFERENCES geofences(id) ON DELETE CASCADE
                ) ENGINE=InnoDB""")
                
                # Notification rules table
                cursor.execute("""CREATE TABLE IF NOT EXISTS notification_rules (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    trigger_type VARCHAR(50) NOT NULL,
                    geofence_id INT,
                    device_filter VARCHAR(255),
                    notification_methods VARCHAR(255) DEFAULT 'log',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT TRUE,
                    INDEX idx_active (is_active),
                    INDEX idx_trigger (trigger_type),
                    FOREIGN KEY (geofence_id) REFERENCES geofences(id) ON DELETE CASCADE
                ) ENGINE=InnoDB""")
                
                # Sent notifications table - enhanced for in-browser notifications
                cursor.execute("""CREATE TABLE IF NOT EXISTS sent_notifications (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    rule_id INT DEFAULT NULL,
                    device_name VARCHAR(255) NOT NULL,
                    geofence_id INT DEFAULT NULL,
                    event_type VARCHAR(20) NOT NULL,
                    message TEXT NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_read BOOLEAN DEFAULT FALSE,
                    read_at TIMESTAMP NULL,
                    read_by VARCHAR(255) NULL,
                    notification_type ENUM('geofence', 'device', 'system') DEFAULT 'geofence',
                    priority ENUM('low', 'normal', 'high', 'urgent') DEFAULT 'normal',
                    delivery_method VARCHAR(50) DEFAULT 'browser',
                    INDEX idx_device (device_name),
                    INDEX idx_timestamp (timestamp),
                    INDEX idx_unread (is_read, timestamp),
                    INDEX idx_type_priority (notification_type, priority, timestamp),
                    FOREIGN KEY (rule_id) REFERENCES notification_rules(id) ON DELETE SET NULL,
                    FOREIGN KEY (geofence_id) REFERENCES geofences(id) ON DELETE SET NULL
                ) ENGINE=InnoDB""")
                
                # Add new columns to existing sent_notifications table
                try:
                    cursor.execute("""ALTER TABLE sent_notifications ADD COLUMN is_read BOOLEAN DEFAULT FALSE""")
                    cursor.execute("""ALTER TABLE sent_notifications ADD COLUMN read_at TIMESTAMP NULL""")
                    cursor.execute("""ALTER TABLE sent_notifications ADD COLUMN read_by VARCHAR(255) NULL""")
                    cursor.execute("""ALTER TABLE sent_notifications ADD COLUMN notification_type ENUM('geofence', 'device', 'system') DEFAULT 'geofence'""")
                    cursor.execute("""ALTER TABLE sent_notifications ADD COLUMN priority ENUM('low', 'normal', 'high', 'urgent') DEFAULT 'normal'""")
                    cursor.execute("""ALTER TABLE sent_notifications ADD COLUMN delivery_method VARCHAR(50) DEFAULT 'browser'""")
                    # Make foreign keys nullable for system notifications
                    cursor.execute("""ALTER TABLE sent_notifications MODIFY COLUMN rule_id INT DEFAULT NULL""")
                    cursor.execute("""ALTER TABLE sent_notifications MODIFY COLUMN geofence_id INT DEFAULT NULL""")
                except pymysql.Error:
                    # Columns already exist or modification not needed, which is fine
                    pass
                
                # Bookmarks table
                cursor.execute("""CREATE TABLE IF NOT EXISTS bookmarks (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    latitude DECIMAL(10,8) NOT NULL,
                    longitude DECIMAL(11,8) NOT NULL,
                    address TEXT,
                    description TEXT,
                    category VARCHAR(100) DEFAULT 'general',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT TRUE,
                    INDEX idx_active (is_active),
                    INDEX idx_category (category),
                    INDEX idx_location (latitude, longitude)
                ) ENGINE=InnoDB""")
                
                # Address cache table for geocoding results
                cursor.execute("""CREATE TABLE IF NOT EXISTS address_cache (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    latitude DECIMAL(10, 8) NOT NULL,
                    longitude DECIMAL(11, 8) NOT NULL,
                    address TEXT NOT NULL,
                    geocoded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP NOT NULL,
                    UNIQUE KEY unique_coordinates (latitude, longitude),
                    INDEX idx_coordinates (latitude, longitude),
                    INDEX idx_expires (expires_at)
                ) ENGINE=InnoDB""")
                
                # Add nickname column to devices table if it doesn't exist
                try:
                    cursor.execute("""
                        ALTER TABLE devices 
                        ADD COLUMN IF NOT EXISTS nickname VARCHAR(255)
                    """)
                except Exception as e:
                    # Column may already exist, that's okay
                    logger.debug(f"Nickname column may already exist: {e}")
                    
                # Basic table optimization (removed problematic buffer pool setting)
                try:
                    cursor.execute("ALTER TABLE locations ENGINE=InnoDB")
                except Exception as e:
                    logger.debug(f"Table optimization note: {e}")
                
                logger.info("MariaDB database initialized successfully with performance optimizations")
                
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise
    
    def save_location_data(self, location_data: List[Dict]) -> bool:
        """Save location data to database with bulk insert optimization"""
        if not location_data:
            return True
            
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Use bulk operations for better performance
                device_updates = []
                
                for location in location_data:
                    device_name = location['device_name']
                    timestamp = location['timestamp']
                    
                    # Convert timestamp to MySQL-compatible format
                    mysql_timestamp = self._convert_timestamp_for_mysql(timestamp)
                    
                    # Prepare device update with converted timestamp
                    device_updates.append((device_name, mysql_timestamp, device_name))
                
                # Ensure devices exist or are updated
                for device_name, mysql_timestamp, _ in device_updates:
                    cursor.execute("""
                        INSERT INTO devices (device_name, last_seen) 
                        VALUES (%s, %s) 
                        ON DUPLICATE KEY UPDATE last_seen = %s
                    """, (device_name, mysql_timestamp, mysql_timestamp))
                    
                logger.debug(f"Processed {len(device_updates)} device updates")
                
                # Bulk insert locations - fixed parameter mapping with timestamp conversion
                location_inserts = []
                for location in location_data:
                    device_name = location['device_name']
                    mysql_timestamp = self._convert_timestamp_for_mysql(location['timestamp'])
                    
                    location_inserts.append((
                        device_name,  # for device_id subquery
                        device_name,  # device_name
                        location['latitude'],
                        location['longitude'],
                        mysql_timestamp,  # converted timestamp
                        location.get('accuracy'),
                        location.get('battery_level'),
                        location.get('is_charging', False)
                    ))
                
                cursor.executemany("""
                    INSERT INTO locations (device_id, device_name, latitude, longitude, timestamp, accuracy, battery_level, is_charging)
                    VALUES (
                        (SELECT id FROM devices WHERE device_name = %s LIMIT 1),
                        %s, %s, %s, %s, %s, %s, %s
                    )
                """, location_inserts)
                
                conn.commit()
                logger.info(f"Saved {len(location_data)} location records to database")
                
                # Log some details for verification
                for location in location_data[:3]:  # Log first 3 for debugging
                    logger.debug(f"Saved location for {location['device_name']}: {location['latitude']}, {location['longitude']} at {location['timestamp']}")
                
                return True
                
        except Exception as e:
            logger.error(f"Failed to save location data: {e}")
            logger.error(f"Location data sample: {location_data[:1] if location_data else 'None'}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return False
    
    @cached_query(location_cache, ttl=180)  # Cache for 3 minutes
    def get_locations(self, start_time: Optional[str] = None, 
                     end_time: Optional[str] = None, 
                     device_name: Optional[str] = None,
                     limit: int = 1000,
                     cluster_locations: bool = False,
                     cluster_distance: float = 0.0005) -> List[Dict]:
        """Get location data with optional filtering and clustering"""
        try:
            with QueryTimer("get_locations"):
                with self.get_connection() as conn:
                    cursor = conn.cursor()
                    
                    query = """
                        SELECT l.*, d.device_type, d.is_active
                        FROM locations l
                        LEFT JOIN devices d ON l.device_id = d.id
                        WHERE 1=1
                    """
                    params = []
                    
                    if start_time:
                        query += ' AND l.timestamp >= %s'
                        params.append(start_time)
                    
                    if end_time:
                        query += ' AND l.timestamp <= %s'
                        params.append(end_time)
                    
                    if device_name:
                        query += ' AND l.device_name = %s'
                        params.append(device_name)
                    
                    query += ' ORDER BY l.timestamp ASC LIMIT %s'
                    params.append(limit)
                    
                    cursor.execute(query, params)
                    locations = list(cursor.fetchall())
                
                if cluster_locations and locations:
                    locations = self._cluster_locations(locations, cluster_distance)
                
                return locations
                
        except Exception as e:
            logger.error(f"Failed to get locations: {e}")
            return []
    
    def _cluster_locations(self, locations: List[Dict], distance_threshold: float = 0.0005) -> List[Dict]:
        """Cluster nearby locations to reduce pin density"""
        if not locations:
            return locations
        
        clustered = []
        
        # Group by device first
        device_locations = {}
        for loc in locations:
            device_name = loc['device_name']
            if device_name not in device_locations:
                device_locations[device_name] = []
            device_locations[device_name].append(loc)
        
        for device_name, device_locs in device_locations.items():
            if not device_locs:
                continue
                
            # Sort by timestamp
            device_locs.sort(key=lambda x: x['timestamp'])
            
            # First location is always included
            clustered.append(device_locs[0])
            last_included = device_locs[0]
            
            for loc in device_locs[1:]:
                # Calculate distance from last included location
                lat_diff = abs(float(loc['latitude']) - float(last_included['latitude']))
                lng_diff = abs(float(loc['longitude']) - float(last_included['longitude']))
                
                # Simple distance calculation
                distance = (lat_diff ** 2 + lng_diff ** 2) ** 0.5
                
                # Include if distance is significant or if it's been a while
                time_diff = self._get_time_diff_hours(last_included['timestamp'], loc['timestamp'])
                
                if distance > distance_threshold or time_diff > 2:
                    clustered.append(loc)
                    last_included = loc
        
        return sorted(clustered, key=lambda x: x['timestamp'], reverse=True)
    
    def _get_time_diff_hours(self, time1, time2) -> float:
        """Calculate time difference in hours between two timestamps"""
        try:
            if isinstance(time1, str):
                time1 = datetime.fromisoformat(time1.replace('Z', '+00:00'))
            if isinstance(time2, str):
                time2 = datetime.fromisoformat(time2.replace('Z', '+00:00'))
            return abs((time2 - time1).total_seconds() / 3600)
        except:
            return 0
    
    @cached_query(location_cache, ttl=300)  # Cache for 5 minutes
    def get_device_movement_24h(self, start_time: str, device_name: Optional[str] = None) -> List[Dict]:
        """Get 24 hours of movement data for devices with clustering"""
        from datetime import datetime, timedelta
        
        try:
            start_dt = datetime.fromisoformat(start_time)
            end_dt = start_dt + timedelta(hours=24)
            
            return self.get_locations(
                start_time=start_dt.isoformat(),
                end_time=end_dt.isoformat(),
                device_name=device_name,
                cluster_locations=True,
                limit=500
            )
        except Exception as e:
            logger.error(f"Failed to get 24h movement data: {e}")
            return []
    
    def get_cached_address(self, latitude: float, longitude: float) -> Optional[str]:
        """Get cached address for coordinates (rounded to reduce cache size)"""
        try:
            # Round coordinates to 4 decimal places (~11m precision)
            lat_rounded = round(latitude, 4)
            lng_rounded = round(longitude, 4)
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT address FROM address_cache 
                    WHERE lat_rounded = %s AND lng_rounded = %s
                """, (lat_rounded, lng_rounded))
                
                result = cursor.fetchone()
                if result:
                    # Update usage stats
                    cursor.execute("""
                        UPDATE address_cache 
                        SET use_count = use_count + 1, last_used = CURRENT_TIMESTAMP
                        WHERE lat_rounded = %s AND lng_rounded = %s
                    """, (lat_rounded, lng_rounded))
                    return result['address']
                    
        except Exception as e:
            logger.debug(f"Address cache lookup failed: {e}")
        
        return None
    
    def cache_address(self, latitude: float, longitude: float, address: str) -> bool:
        """Cache address for coordinates"""
        try:
            if not address or len(address) < 3:
                return False
                
            # Round coordinates to 4 decimal places
            lat_rounded = round(latitude, 4)
            lng_rounded = round(longitude, 4)
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO address_cache (lat_rounded, lng_rounded, address)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE 
                        address = VALUES(address),
                        use_count = use_count + 1,
                        last_used = CURRENT_TIMESTAMP
                """, (lat_rounded, lng_rounded, address))
                
                return True
                
        except Exception as e:
            logger.debug(f"Address cache store failed: {e}")
        
        return False
    
    def diagnose_location_save_issues(self) -> Dict:
        """Diagnose potential issues with location saving"""
        issues = []
        info = {}
        
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Check if tables exist
                cursor.execute("SHOW TABLES")
                tables = [row[list(row.keys())[0]] for row in cursor.fetchall()]
                info['tables'] = tables
                
                if 'locations' not in tables:
                    issues.append("locations table does not exist")
                if 'devices' not in tables:
                    issues.append("devices table does not exist")
                
                # Check locations table structure if it exists
                if 'locations' in tables:
                    cursor.execute("DESCRIBE locations")
                    columns = {col['Field']: col for col in cursor.fetchall()}
                    info['locations_columns'] = list(columns.keys())
                    
                    required_cols = ['device_name', 'latitude', 'longitude', 'timestamp']
                    for col in required_cols:
                        if col not in columns:
                            issues.append(f"locations table missing required column: {col}")
                
                # Check devices table structure
                if 'devices' in tables:
                    cursor.execute("DESCRIBE devices")
                    columns = {col['Field']: col for col in cursor.fetchall()}
                    info['devices_columns'] = list(columns.keys())
                    
                    if 'device_name' not in columns:
                        issues.append("devices table missing device_name column")
                
                # Check for recent activity
                if 'locations' in tables:
                    cursor.execute("SELECT COUNT(*) as count FROM locations WHERE timestamp >= DATE_SUB(NOW(), INTERVAL 1 DAY)")
                    recent_count = cursor.fetchone()['count']
                    info['recent_locations_24h'] = recent_count
                    
                    cursor.execute("SELECT COUNT(*) as count FROM locations")
                    total_count = cursor.fetchone()['count']
                    info['total_locations'] = total_count
                    
                    if total_count == 0:
                        issues.append("No location records found in database")
                    elif recent_count == 0:
                        issues.append("No recent location records (last 24 hours)")
                
                # Test a simple insert
                try:
                    test_device = f"test_device_{int(time.time())}"
                    cursor.execute("INSERT INTO devices (device_name) VALUES (%s)", (test_device,))
                    cursor.execute("DELETE FROM devices WHERE device_name = %s", (test_device,))
                    info['insert_test'] = 'passed'
                except Exception as e:
                    issues.append(f"Database insert test failed: {e}")
                    info['insert_test'] = f'failed: {e}'
                
        except Exception as e:
            issues.append(f"Database connection failed: {e}")
            info['connection_error'] = str(e)
        
        return {
            'issues': issues,
            'info': info,
            'status': 'healthy' if not issues else 'issues_found'
        }

    def cleanup_address_cache(self, keep_count: int = 10000) -> bool:
        """Clean up old address cache entries to prevent table bloat"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Keep only the most frequently used addresses
                cursor.execute("""
                    DELETE FROM address_cache 
                    WHERE id NOT IN (
                        SELECT id FROM (
                            SELECT id FROM address_cache 
                            ORDER BY use_count DESC, last_used DESC 
                            LIMIT %s
                        ) AS keeper
                    )
                """, (keep_count,))
                
                deleted = cursor.rowcount
                if deleted > 0:
                    logger.info(f"Cleaned up {deleted} old address cache entries")
                
                return True
                
        except Exception as e:
            logger.error(f"Address cache cleanup failed: {e}")
        
        return False

    def get_statistics(self) -> Dict:
        """Get application statistics with MariaDB optimizations"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Use single query with subqueries for better performance
                cursor.execute("""
                    SELECT 
                        (SELECT COUNT(*) FROM locations) as total_locations,
                        (SELECT COUNT(DISTINCT device_name) FROM locations) as unique_devices,
                        (SELECT COUNT(*) FROM locations WHERE DATE(timestamp) = CURDATE()) as today_count,
                        (SELECT timestamp FROM locations ORDER BY timestamp DESC LIMIT 1) as last_update
                """)
                stats = cursor.fetchone()
                
                # Get device statistics
                cursor.execute("""
                    SELECT device_name, COUNT(*) as location_count, 
                           MAX(timestamp) as last_seen
                    FROM locations 
                    GROUP BY device_name
                    ORDER BY last_seen DESC
                """)
                devices = list(cursor.fetchall())
                
                # Get address cache stats
                try:
                    cursor.execute("SELECT COUNT(*) as cache_size FROM address_cache")
                    cache_stats = cursor.fetchone()
                    cache_size = cache_stats['cache_size'] if cache_stats else 0
                except:
                    cache_size = 0
                
                return {
                    'total_locations': stats['total_locations'],
                    'unique_devices': stats['unique_devices'],
                    'today_count': stats['today_count'],
                    'last_update': stats['last_update'],
                    'devices': devices,
                    'address_cache_size': cache_size
                }
                
        except Exception as e:
            logger.error(f"Failed to get statistics: {e}")
            return {
                'total_locations': 0,
                'unique_devices': 0,
                'today_count': 0,
                'last_update': None,
                'devices': []
            }
    
    def get_devices(self) -> List[Dict]:
        """Get all tracked devices"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT d.*, COUNT(l.id) as location_count,
                           MAX(l.timestamp) as last_location
                    FROM devices d
                    LEFT JOIN locations l ON d.id = l.device_id
                    GROUP BY d.id
                    ORDER BY d.last_seen DESC
                """)
                
                return list(cursor.fetchall())
                
        except Exception as e:
            logger.error(f"Failed to get devices: {e}")
            return []
    
    def save_session(self, session_data: str, expires_at: Optional[str] = None):
        """Save iCloud session data"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Invalidate old sessions
                cursor.execute('UPDATE sessions SET is_valid = FALSE')
                
                # Insert new session
                cursor.execute("""
                    INSERT INTO sessions (session_data, expires_at)
                    VALUES (%s, %s)
                """, (session_data, expires_at))
                
                conn.commit()
                logger.info("Session saved to database")
                
        except Exception as e:
            logger.error(f"Failed to save session: {e}")
    
    def cleanup_expired_sessions(self):
        """Clean up expired sessions"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    UPDATE sessions 
                    SET is_valid = FALSE 
                    WHERE expires_at IS NOT NULL 
                    AND expires_at <= NOW()
                """)
                
                expired_count = cursor.rowcount
                conn.commit()
                
                if expired_count > 0:
                    logger.info(f"Cleaned up {expired_count} expired sessions")
                    
        except Exception as e:
            logger.error(f"Failed to cleanup expired sessions: {e}")
    
    def get_valid_session(self) -> Optional[str]:
        """Get the most recent valid session that hasn't expired"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT session_data FROM sessions 
                    WHERE is_valid = TRUE 
                    AND (expires_at IS NULL OR expires_at > NOW())
                    ORDER BY created_at DESC 
                    LIMIT 1
                """)
                
                result = cursor.fetchone()
                return result['session_data'] if result else None
                
        except Exception as e:
            logger.error(f"Failed to get session: {e}")
            return None
    
    def log_message(self, level: str, message: str, source: str = "application"):
        """Log a message to the database"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT INTO logs (level, message, source)
                    VALUES (%s, %s, %s)
                """, (level, message, source))
                
                conn.commit()
                
        except Exception as e:
            logger.error(f"Failed to log message to database: {e}")
    
    def cleanup_old_data(self, days_to_keep: int = 30):
        """Clean up old location data"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Delete old locations
                cursor.execute("""
                    DELETE FROM locations 
                    WHERE timestamp < DATE_SUB(NOW(), INTERVAL %s DAY)
                """, (days_to_keep,))
                
                deleted_count = cursor.rowcount
                
                # Delete old logs
                cursor.execute("""
                    DELETE FROM logs 
                    WHERE timestamp < DATE_SUB(NOW(), INTERVAL %s DAY)
                """, (days_to_keep,))
                
                deleted_logs = cursor.rowcount
                
                conn.commit()
                
                if deleted_count > 0 or deleted_logs > 0:
                    logger.info(f"Cleaned up {deleted_count} old locations and {deleted_logs} old logs")
                
        except Exception as e:
            logger.error(f"Failed to cleanup old data: {e}")
    
    def backup_database(self, backup_path: str = None):
        """Create a backup of the database using mysqldump"""
        if not backup_path:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_path = f"icloud_tracker_backup_{timestamp}.sql"
        
        try:
            import subprocess
            
            cmd = [
                'mysqldump',
                f"--host={self.db_config['host']}",
                f"--port={self.db_config['port']}",
                f"--user={self.db_config['user']}",
                f"--password={self.db_config['password']}",
                '--single-transaction',
                '--routines',
                '--triggers',
                self.db_config['database']
            ]
            
            with open(backup_path, 'w') as f:
                subprocess.run(cmd, stdout=f, check=True)
            
            logger.info(f"Database backed up to {backup_path}")
            return backup_path
        except Exception as e:
            logger.error(f"Failed to backup database: {e}")
            return None
    
    def create_user(self, username: str, password: str, is_admin: bool = False) -> bool:
        """Create a new user with hashed password"""
        import hashlib
        try:
            # Hash the password
            password_hash = hashlib.sha256(password.encode()).hexdigest()
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO users (username, password_hash, is_admin)
                    VALUES (%s, %s, %s)
                """, (username, password_hash, is_admin))
                logger.info(f"User {username} created successfully {'as admin' if is_admin else ''}")
                return True
        except Exception as e:
            logger.error(f"Failed to create user {username}: {e}")
            return False
    
    def verify_user(self, username: str, password: str) -> bool:
        """Verify user credentials against database"""
        import hashlib
        try:
            password_hash = hashlib.sha256(password.encode()).hexdigest()
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id FROM users 
                    WHERE username = %s AND password_hash = %s
                """, (username, password_hash))
                user = cursor.fetchone()
                
                if user:
                    # Update last login time
                    cursor.execute("""
                        UPDATE users SET last_login = CURRENT_TIMESTAMP 
                        WHERE username = %s
                    """, (username,))
                    return True
                return False
        except Exception as e:
            logger.error(f"Failed to verify user {username}: {e}")
            return False
    
    def get_user(self, username: str) -> Optional[Dict]:
        """Get user information from database"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, username, is_admin, is_active, created_at, last_login
                    FROM users WHERE username = %s AND is_active = TRUE
                """, (username,))
                return cursor.fetchone()
        except Exception as e:
            logger.error(f"Failed to get user {username}: {e}")
            return None
    
    def init_default_admin(self):
        """Initialize default admin user if no users exist"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) as count FROM users")
                result = cursor.fetchone()
                
                if result['count'] == 0:
                    # Create default admin user from environment variables
                    admin_username = os.getenv('ADMIN_USERNAME', 'admin')
                    admin_password = os.getenv('ADMIN_PASSWORD', 'change_me')
                    
                    if self.create_user(admin_username, admin_password, is_admin=True):
                        logger.info(f"Default admin user '{admin_username}' created")
                    else:
                        logger.error("Failed to create default admin user")
        except Exception as e:
            logger.error(f"Failed to initialize default admin: {e}")
    
    def get_all_users(self) -> List[Dict]:
        """Get all users from database"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, username, is_admin, is_active, created_at, last_login
                    FROM users ORDER BY created_at DESC
                """)
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"Failed to get all users: {e}")
            return []
    
    def update_user_admin_status(self, username: str, is_admin: bool) -> bool:
        """Update user admin status"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE users SET is_admin = %s WHERE username = %s
                """, (is_admin, username))
                if cursor.rowcount > 0:
                    logger.info(f"User {username} admin status updated to {is_admin}")
                    return True
                return False
        except Exception as e:
            logger.error(f"Failed to update admin status for {username}: {e}")
            return False
    
    def update_user_active_status(self, username: str, is_active: bool) -> bool:
        """Update user active status (disable/enable user)"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE users SET is_active = %s WHERE username = %s
                """, (is_active, username))
                if cursor.rowcount > 0:
                    logger.info(f"User {username} active status updated to {is_active}")
                    return True
                return False
        except Exception as e:
            logger.error(f"Failed to update active status for {username}: {e}")
            return False
    
    def delete_user(self, username: str) -> bool:
        """Delete a user from database"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM users WHERE username = %s", (username,))
                if cursor.rowcount > 0:
                    logger.info(f"User {username} deleted successfully")
                    return True
                return False
        except Exception as e:
            logger.error(f"Failed to delete user {username}: {e}")
            return False
    
    def change_user_password(self, username: str, new_password: str) -> bool:
        """Change user password"""
        import hashlib
        try:
            password_hash = hashlib.sha256(new_password.encode()).hexdigest()
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE users SET password_hash = %s WHERE username = %s
                """, (password_hash, username))
                if cursor.rowcount > 0:
                    logger.info(f"Password changed for user {username}")
                    return True
                return False
        except Exception as e:
            logger.error(f"Failed to change password for {username}: {e}")
            return False
    
    def create_notification(self, device_name: str, message: str, notification_type: str = 'system', 
                          priority: str = 'normal', rule_id: int = None, geofence_id: int = None, 
                          event_type: str = 'info') -> bool:
        """Create a new in-browser notification"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO sent_notifications 
                    (rule_id, device_name, geofence_id, event_type, message, notification_type, priority)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (rule_id, device_name, geofence_id, event_type, message, notification_type, priority))
                logger.info(f"Created {notification_type} notification for {device_name}: {message}")
                return True
        except Exception as e:
            logger.error(f"Failed to create notification: {e}")
            return False
    
    def get_user_notifications(self, username: str = None, unread_only: bool = False, limit: int = 50) -> List[Dict]:
        """Get notifications for user (or all if admin)"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                where_clause = ""
                params = []
                
                if unread_only:
                    where_clause = "WHERE is_read = FALSE"
                
                if username:
                    # For regular users, show notifications for devices they have access to
                    # For now, show all notifications (can be refined later with device permissions)
                    pass
                
                query = f"""
                    SELECT 
                        sn.id, sn.device_name, sn.message, sn.timestamp, sn.is_read, sn.read_at, 
                        sn.read_by, sn.notification_type, sn.priority, sn.event_type,
                        g.name as geofence_name, nr.name as rule_name
                    FROM sent_notifications sn
                    LEFT JOIN geofences g ON sn.geofence_id = g.id
                    LEFT JOIN notification_rules nr ON sn.rule_id = nr.id
                    {where_clause}
                    ORDER BY sn.timestamp DESC
                    LIMIT %s
                """
                params.append(limit)
                
                cursor.execute(query, params)
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"Failed to get notifications: {e}")
            return []
    
    def mark_notification_read(self, notification_id: int, username: str) -> bool:
        """Mark a notification as read"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE sent_notifications 
                    SET is_read = TRUE, read_at = CURRENT_TIMESTAMP, read_by = %s
                    WHERE id = %s
                """, (username, notification_id))
                if cursor.rowcount > 0:
                    logger.info(f"Notification {notification_id} marked as read by {username}")
                    return True
                return False
        except Exception as e:
            logger.error(f"Failed to mark notification as read: {e}")
            return False
    
    def mark_all_notifications_read(self, username: str) -> int:
        """Mark all notifications as read for a user"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE sent_notifications 
                    SET is_read = TRUE, read_at = CURRENT_TIMESTAMP, read_by = %s
                    WHERE is_read = FALSE
                """, (username,))
                count = cursor.rowcount
                if count > 0:
                    logger.info(f"Marked {count} notifications as read for {username}")
                return count
        except Exception as e:
            logger.error(f"Failed to mark all notifications as read: {e}")
            return 0
    
    def get_notification_count(self, username: str = None, unread_only: bool = True) -> int:
        """Get count of notifications"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                where_clause = ""
                params = []
                
                if unread_only:
                    where_clause = "WHERE is_read = FALSE"
                
                query = f"SELECT COUNT(*) as count FROM sent_notifications {where_clause}"
                cursor.execute(query, params)
                result = cursor.fetchone()
                return result['count'] if result else 0
        except Exception as e:
            logger.error(f"Failed to get notification count: {e}")
            return 0
    
    def cleanup_old_notifications(self, days: int = 30) -> int:
        """Clean up old read notifications"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    DELETE FROM sent_notifications 
                    WHERE is_read = TRUE AND timestamp < DATE_SUB(NOW(), INTERVAL %s DAY)
                """, (days,))
                count = cursor.rowcount
                if count > 0:
                    logger.info(f"Cleaned up {count} old notifications")
                return count
        except Exception as e:
            logger.error(f"Failed to cleanup old notifications: {e}")
            return 0
    
    def get_user_settings(self, username: str) -> Dict:
        """Get user settings, creating defaults if none exist"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Get user ID
                cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
                user = cursor.fetchone()
                if not user:
                    return self._get_default_settings()
                
                user_id = user['id']
                
                # Get existing settings
                cursor.execute("""
                    SELECT timezone, date_format, theme, map_default_zoom, refresh_interval 
                    FROM user_settings WHERE user_id = %s
                """, (user_id,))
                settings = cursor.fetchone()
                
                if settings:
                    return dict(settings)
                else:
                    # Create default settings for user
                    default_settings = self._get_default_settings()
                    self.update_user_settings(username, default_settings)
                    return default_settings
                    
        except Exception as e:
            logger.error(f"Failed to get user settings for {username}: {e}")
            return self._get_default_settings()
    
    def update_user_settings(self, username: str, settings: Dict) -> bool:
        """Update user settings"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Get user ID
                cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
                user = cursor.fetchone()
                if not user:
                    return False
                
                user_id = user['id']
                
                # Insert or update settings
                cursor.execute("""
                    INSERT INTO user_settings 
                    (user_id, timezone, date_format, theme, map_default_zoom, refresh_interval)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                    timezone = VALUES(timezone),
                    date_format = VALUES(date_format), 
                    theme = VALUES(theme),
                    map_default_zoom = VALUES(map_default_zoom),
                    refresh_interval = VALUES(refresh_interval),
                    updated_at = CURRENT_TIMESTAMP
                """, (
                    user_id,
                    settings.get('timezone', 'America/Chicago'),
                    settings.get('date_format', '%Y-%m-%d %I:%M:%S %p'),
                    settings.get('theme', 'light'),
                    settings.get('map_default_zoom', 10),
                    settings.get('refresh_interval', 300)
                ))
                
                logger.info(f"Updated settings for user {username}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to update user settings for {username}: {e}")
            return False
    
    def _get_default_settings(self) -> Dict:
        """Get default user settings"""
        return {
            'timezone': 'America/Chicago',
            'date_format': '%Y-%m-%d %I:%M:%S %p',
            'theme': 'light',
            'map_default_zoom': 10,
            'refresh_interval': 300
        }
    
    def get_available_timezones(self) -> List[Dict]:
        """Get list of available timezones grouped by region"""
        import pytz
        
        timezone_groups = {
            'US & Canada': [
                ('America/New_York', 'Eastern Time'),
                ('America/Chicago', 'Central Time'), 
                ('America/Denver', 'Mountain Time'),
                ('America/Phoenix', 'Arizona Time'),
                ('America/Los_Angeles', 'Pacific Time'),
                ('America/Anchorage', 'Alaska Time'),
                ('Pacific/Honolulu', 'Hawaii Time'),
                ('America/Toronto', 'Toronto'),
                ('America/Vancouver', 'Vancouver')
            ],
            'Europe': [
                ('Europe/London', 'London'),
                ('Europe/Paris', 'Paris'),
                ('Europe/Berlin', 'Berlin'),
                ('Europe/Rome', 'Rome'),
                ('Europe/Madrid', 'Madrid'),
                ('Europe/Amsterdam', 'Amsterdam'),
                ('Europe/Zurich', 'Zurich'),
                ('Europe/Moscow', 'Moscow')
            ],
            'Asia Pacific': [
                ('Asia/Tokyo', 'Tokyo'),
                ('Asia/Shanghai', 'Shanghai'),
                ('Asia/Singapore', 'Singapore'),
                ('Asia/Hong_Kong', 'Hong Kong'),
                ('Asia/Seoul', 'Seoul'),
                ('Asia/Kolkata', 'India'),
                ('Australia/Sydney', 'Sydney'),
                ('Australia/Melbourne', 'Melbourne')
            ],
            'Other': [
                ('UTC', 'UTC/GMT'),
                ('America/Sao_Paulo', 'São Paulo'),
                ('Africa/Cairo', 'Cairo'),
                ('Africa/Johannesburg', 'Johannesburg')
            ]
        }
        
        return timezone_groups
    
    def get_device_nickname(self, device_name: str) -> str:
        """Get device nickname or return device_name if no nickname set"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT nickname FROM devices 
                    WHERE device_name = %s AND nickname IS NOT NULL AND nickname != ''
                """, (device_name,))
                result = cursor.fetchone()
                return result['nickname'] if result else device_name
        except Exception as e:
            logger.error(f"Failed to get device nickname for {device_name}: {e}")
            return device_name
    
    def set_device_nickname(self, device_name: str, nickname: str) -> bool:
        """Set or update a device nickname"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # First, ensure the device exists in the devices table
                cursor.execute("""
                    INSERT INTO devices (device_name, nickname, first_seen, last_seen) 
                    VALUES (%s, %s, NOW(), NOW())
                    ON DUPLICATE KEY UPDATE 
                    nickname = VALUES(nickname), last_seen = NOW()
                """, (device_name, nickname))
                
                return True
        except Exception as e:
            logger.error(f"Failed to set nickname for device {device_name}: {e}")
            return False
    
    def remove_device_nickname(self, device_name: str) -> bool:
        """Remove a device nickname"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE devices 
                    SET nickname = NULL 
                    WHERE device_name = %s
                """, (device_name,))
                return True
        except Exception as e:
            logger.error(f"Failed to remove nickname for device {device_name}: {e}")
            return False
    
    def get_all_devices_with_nicknames(self) -> List[Dict]:
        """Get all devices with their nicknames"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT DISTINCT l.device_name,
                           d.nickname,
                           COALESCE(d.nickname, l.device_name) as display_name,
                           COUNT(l.id) as location_count,
                           MAX(l.timestamp) as last_location
                    FROM locations l
                    LEFT JOIN devices d ON l.device_name = d.device_name
                    GROUP BY l.device_name, d.nickname
                    ORDER BY display_name
                """)
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"Failed to get devices with nicknames: {e}")
            return []
    
    def get_device_display_name(self, device_name: str) -> str:
        """Get the display name for a device (nickname if available, otherwise device name)"""
        nickname = self.get_device_nickname(device_name)
        return nickname if nickname != device_name else device_name
    
    def get_cached_address(self, latitude: float, longitude: float, tolerance: float = 0.0005) -> Optional[str]:
        """Get cached address from database if not expired, with smart coordinate grouping
        
        Args:
            latitude: Target latitude
            longitude: Target longitude  
            tolerance: Coordinate tolerance for grouping (default ~55 meters at equator)
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # First try exact match
                cursor.execute("""
                    SELECT address FROM address_cache 
                    WHERE latitude = %s AND longitude = %s 
                    AND expires_at > NOW()
                """, (latitude, longitude))
                result = cursor.fetchone()
                if result:
                    return result['address']
                
                # If no exact match, try nearby coordinates within tolerance
                cursor.execute("""
                    SELECT address, latitude, longitude,
                           ABS(latitude - %s) + ABS(longitude - %s) as distance
                    FROM address_cache 
                    WHERE ABS(latitude - %s) <= %s 
                    AND ABS(longitude - %s) <= %s
                    AND expires_at > NOW()
                    ORDER BY distance
                    LIMIT 1
                """, (latitude, longitude, latitude, tolerance, longitude, tolerance))
                
                nearby_result = cursor.fetchone()
                if nearby_result:
                    logger.debug(f"Using nearby cached address for {latitude},{longitude} from {nearby_result['latitude']},{nearby_result['longitude']}")
                    return nearby_result['address']
                
                return None
        except Exception as e:
            logger.error(f"Failed to get cached address for {latitude}, {longitude}: {e}")
            return None
    
    def cache_address(self, latitude: float, longitude: float, address: str, cache_days: int = 30) -> bool:
        """Cache address in database with expiration"""
        try:
            from datetime import datetime, timedelta
            expires_at = datetime.now() + timedelta(days=cache_days)
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO address_cache (latitude, longitude, address, expires_at) 
                    VALUES (%s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE 
                    address = VALUES(address), 
                    geocoded_at = CURRENT_TIMESTAMP,
                    expires_at = VALUES(expires_at)
                """, (latitude, longitude, address, expires_at))
                return True
        except Exception as e:
            logger.error(f"Failed to cache address for {latitude}, {longitude}: {e}")
            return False
    
    def cleanup_expired_addresses(self) -> int:
        """Remove expired address cache entries and return count of deleted entries"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM address_cache WHERE expires_at <= NOW()")
                deleted_count = cursor.rowcount
                if deleted_count > 0:
                    logger.info(f"Cleaned up {deleted_count} expired address cache entries")
                return deleted_count
        except Exception as e:
            logger.error(f"Failed to cleanup expired address cache: {e}")
            return 0
    
    def get_address_cache_stats(self) -> Dict:
        """Get statistics about the address cache"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Get total cache entries
                cursor.execute("SELECT COUNT(*) as total FROM address_cache")
                total = cursor.fetchone()['total']
                
                # Get expired entries
                cursor.execute("SELECT COUNT(*) as expired FROM address_cache WHERE expires_at <= NOW()")
                expired = cursor.fetchone()['expired']
                
                # Get cache size
                cursor.execute("""
                    SELECT ROUND(SUM(LENGTH(address)) / 1024, 2) as size_kb 
                    FROM address_cache
                """)
                size_result = cursor.fetchone()
                size_kb = size_result['size_kb'] if size_result['size_kb'] else 0
                
                return {
                    'total_entries': total,
                    'active_entries': total - expired,
                    'expired_entries': expired,
                    'cache_size_kb': float(size_kb)
                }
        except Exception as e:
            logger.error(f"Failed to get address cache stats: {e}")
            return {
                'total_entries': 0,
                'active_entries': 0,
                'expired_entries': 0,
                'cache_size_kb': 0
            }

# Global database instance
db = Database()