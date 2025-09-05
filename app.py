from flask import Flask, render_template, redirect, url_for, request, flash, jsonify, session
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from functools import wraps
from flask_wtf.csrf import CSRFProtect, generate_csrf
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
try:
    from flask_compress import Compress
    COMPRESS_AVAILABLE = True
except ImportError:
    COMPRESS_AVAILABLE = False
import json
import os
import logging
from logging.handlers import TimedRotatingFileHandler
import pytz
import pymysql
from datetime import datetime, timedelta
from decimal import Decimal
from config import Config
from database import db
from analytics import analytics
from top_locations_scheduler import start_scheduler, stop_scheduler, top_locations_scheduler
from cache import (
    location_cache, analytics_cache, dashboard_cache, notification_cache,
    cached_query, invalidate_location_cache, QueryTimer, get_all_cache_stats
)
from timezone_utils import (
    convert_utc_to_user_timezone, convert_local_to_utc, format_datetime_for_user,
    get_current_time_in_timezone, validate_timezone
)
import hashlib
import time
from flask import g

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Ensure daily traceback logging to logs/traceback.<YYYY-MM-DD>
try:
    os.makedirs('logs', exist_ok=True)
    traceback_handler = TimedRotatingFileHandler(
        filename=os.path.join('logs', 'traceback'),
        when='midnight',
        interval=1,
        backupCount=14,
        encoding='utf-8'
    )
    traceback_handler.suffix = "%Y-%m-%d"
    traceback_handler.setLevel(logging.ERROR)
    traceback_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logging.getLogger().addHandler(traceback_handler)
except Exception as _e:
    logger.warning(f"Failed to initialize traceback daily logger: {_e}")

app = Flask(__name__)
app.config.from_object(Config)

# Enable response compression for better performance
compress = Compress(app)

# Configure compression settings
app.config['COMPRESS_MIMETYPES'] = [
    'text/html', 'text/css', 'text/xml', 'text/plain',
    'application/json', 'application/javascript',
    'application/xml', 'application/rss+xml'
]
app.config['COMPRESS_LEVEL'] = 6  # Good balance of compression vs CPU usage
app.config['COMPRESS_MIN_SIZE'] = 500  # Only compress responses > 500 bytes

# Cache functions using new caching system
def _get_cache_key(device_filter, start_date, end_date, limit, page):
    """Generate cache key for GPS logs query"""
    from cache import cache_key_generator
    return f"gps_logs:{cache_key_generator(device_filter, start_date, end_date, limit, page)}"

def _get_cached_logs(cache_key):
    """Get cached GPS logs if still valid"""
    return location_cache.get(cache_key)

def _cache_logs(cache_key, data):
    """Cache GPS logs data"""
    location_cache.set(cache_key, data)

# Timezone helper functions
def get_cst_now():
    """Get current time in CST"""
    utc_now = datetime.utcnow().replace(tzinfo=pytz.UTC)
    cst_now = utc_now.astimezone(Config.get_timezone())
    return cst_now

def convert_to_cst(timestamp_str):
    """Convert timestamp string to CST"""
    try:
        if isinstance(timestamp_str, str):
            # Handle various timestamp formats
            if timestamp_str.endswith('Z'):
                dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            elif '+' in timestamp_str or '-' in timestamp_str[-6:]:
                # Handle timezone-aware timestamps like "2025-08-09T15:32:09.710190-05:00"
                dt = datetime.fromisoformat(timestamp_str)
            else:
                # Handle timezone-naive timestamps
                dt = datetime.fromisoformat(timestamp_str)
                if dt.tzinfo is None:
                    dt = pytz.UTC.localize(dt)
        else:
            dt = timestamp_str
            
        # Convert to CST if not already timezone-aware
        if dt.tzinfo is None:
            dt = pytz.UTC.localize(dt)
            
        cst_dt = dt.astimezone(Config.get_timezone())
        return cst_dt
    except Exception as e:
        logger.warning(f"Failed to convert timestamp to CST: {timestamp_str}, error: {e}")
        # Return a more informative error for debugging
        return f"Error converting: {timestamp_str}"

# Legacy timezone conversion functions (deprecated - gradually being replaced by timezone_utils module)
# Note: These functions still in use by some routes, consider migrating to user-specific timezone handling

@app.template_filter('number_format')
def number_format_filter(value):
    """Template filter to format numbers with commas"""
    try:
        if value is None:
            return "0"
        return "{:,}".format(int(value))
    except (ValueError, TypeError):
        return str(value)

# Helper function to check if a route exists
def route_exists(endpoint):
    """Check if a Flask route endpoint exists"""
    try:
        url_for(endpoint)
        return True
    except:
        return False

# Make functions available in templates
@app.context_processor
def inject_timezone_functions():
    return dict(
        get_cst_now=get_cst_now,
        route_exists=route_exists
    )

# Serialization helper
def serialize_location_row(row: dict) -> dict:
    """Convert DB row values to JSON-serializable primitives."""
    if row is None:
        return {}
    def to_float(val):
        if isinstance(val, Decimal):
            return float(val)
        return float(val) if isinstance(val, (int, float)) else None
    def to_iso(val):
        try:
            if isinstance(val, datetime):
                return val.isoformat()
            # strings that look like datetimes are passed through
            return str(val) if val is not None else None
        except Exception:
            return None
    device_name = row.get('device_name')
    return {
        'id': row.get('id'),
        'device_id': row.get('device_id'),
        'device_name': device_name,
        'display_name': db.get_device_display_name(device_name) if device_name else device_name,
        'latitude': to_float(row.get('latitude')),
        'longitude': to_float(row.get('longitude')),
        'timestamp': to_iso(row.get('timestamp')),
        'accuracy': row.get('accuracy'),
        'battery_level': row.get('battery_level'),
        'is_charging': bool(row.get('is_charging')) if row.get('is_charging') is not None else None,
        'device_type': row.get('device_type'),
        'is_active': row.get('is_active'),
        'created_at': to_iso(row.get('created_at'))
    }

# Initialize extensions
csrf = CSRFProtect(app)

# Make CSRF token and utility functions available in all templates
@app.context_processor
def inject_csrf_token():
    return dict(csrf_token=generate_csrf, get_cst_now=get_cst_now)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.session_protection = 'strong'
login_manager.remember_cookie_duration = timedelta(days=30)

# Enable response compression if available
if COMPRESS_AVAILABLE:
    compress = Compress()
    compress.init_app(app)
    logger.info("Flask-Compress initialized")
else:
    logger.info("Running without compression - install Flask-Compress for better performance")

# Rate limiting with localhost exemption
def get_rate_limit_key():
    """Get rate limit key, but exempt localhost"""
    remote_addr = get_remote_address()
    # Exempt localhost/127.0.0.1 from rate limiting
    if remote_addr in ['127.0.0.1', '::1', 'localhost']:
        return None  # No rate limiting for localhost
    return remote_addr

limiter = Limiter(
    app=app,
    key_func=get_rate_limit_key,
    default_limits=["200 per day", "50 per hour"]
)

# Performance monitoring middleware
@app.before_request
def before_request():
    g.start_time = time.time()

@app.after_request
def after_request(response):
    if hasattr(g, 'start_time'):
        duration = time.time() - g.start_time
        if duration > 2.0:
            logger.warning(f"SLOW REQUEST: {request.endpoint} took {duration:.2f}s")
        elif duration > 1.0:
            logger.info(f"MEDIUM REQUEST: {request.endpoint} took {duration:.2f}s")
        else:
            logger.debug(f"REQUEST: {request.endpoint} took {duration:.3f}s")
    return response

# Template filters for timezone conversion
@app.template_filter('user_timezone')
def user_timezone_filter(dt):
    """Convert UTC datetime to user's timezone"""
    try:
        if not dt:
            return ''
        
        if current_user.is_authenticated:
            try:
                user_settings = db.get_user_settings(current_user.id)
                return format_datetime_for_user(dt, user_settings.get('timezone', 'America/Chicago'), 
                                              user_settings.get('date_format', '%Y-%m-%d %I:%M:%S %p'))
            except:
                # Fallback to default timezone if user settings fail
                return format_datetime_for_user(dt, 'America/Chicago', '%Y-%m-%d %I:%M:%S %p')
        else:
            # Default formatting for non-authenticated users
            return format_datetime_for_user(dt, 'America/Chicago', '%Y-%m-%d %I:%M:%S %p')
    except Exception as e:
        logger.error(f"Error in timezone filter: {e}")
        # Fallback to simple string representation
        if hasattr(dt, 'strftime'):
            try:
                return dt.strftime('%Y-%m-%d %H:%M:%S')
            except Exception as e:
                logger.warning(f"Failed to format datetime {dt}: {e}")
                # Continue to fallback string representation
        return str(dt) if dt else ''

@app.template_filter('device_display_name')
def device_display_name_filter(device_name):
    """Template filter to display device nickname if available, otherwise device name"""
    try:
        if not device_name:
            return device_name
        return db.get_device_display_name(device_name)
    except Exception as e:
        logger.error(f"Error getting device display name for {device_name}: {e}")
        return device_name

@app.template_filter('simple_timezone')
def simple_timezone_filter(dt, timezone_str='America/Chicago'):
    """Simple timezone conversion with specified timezone"""
    try:
        return format_datetime_for_user(dt, timezone_str, '%Y-%m-%d %I:%M:%S %p')
    except Exception as e:
        logger.error(f"Error in simple timezone filter: {e}")
        return str(dt) if dt else ''

@app.template_filter('as_datetime')
def as_datetime_filter(dt):
    """Convert various datetime formats to datetime object for template calculations"""
    if isinstance(dt, datetime):
        return dt
    elif isinstance(dt, str):
        try:
            # Try parsing common formats
            for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M:%S.%f']:
                try:
                    return datetime.strptime(dt, fmt)
                except ValueError:
                    continue
            # If no format works, try direct parsing
            return datetime.fromisoformat(dt.replace('Z', '+00:00'))
        except:
            return dt
    else:
        return dt

# Context processor to make user settings available in all templates
@app.context_processor
def inject_user_settings():
    """Make user settings available in all templates"""
    default_settings = {
        'timezone': 'America/Chicago',
        'date_format': '%Y-%m-%d %I:%M:%S %p',
        'theme': 'light',
        'map_default_zoom': 10,
        'refresh_interval': 300
    }
    
    if current_user.is_authenticated:
        try:
            user_settings = db.get_user_settings(current_user.id)
            return {'user_settings': user_settings}
        except Exception as e:
            logger.debug(f"Error getting user settings: {e}")
            return {'user_settings': default_settings}
    return {'user_settings': default_settings}

# User class for Flask-Login
class User(UserMixin):
    def __init__(self, id):
        self.id = id
        self._user_data = None
    
    def get_user_data(self):
        """Get user data from database (cached)"""
        if self._user_data is None:
            self._user_data = db.get_user(self.id)
        return self._user_data
    
    def is_admin(self):
        """Check if user is admin"""
        user_data = self.get_user_data()
        return user_data and user_data.get('is_admin', False)
    
    def is_active_user(self):
        """Check if user is active"""
        user_data = self.get_user_data()
        return user_data and user_data.get('is_active', False)

@login_manager.user_loader
def load_user(user_id):
    # Verify user exists in database
    user_data = db.get_user(user_id)
    if user_data:
        return User(user_id)
    return None

# Admin required decorator
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('login'))
        if not current_user.is_admin():
            flash('Access denied. Admin privileges required.', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def login():
    """Login page with improved security"""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        if not username or not password:
            flash('Please provide both username and password.', 'error')
            return render_template('login.html')
        
        # Verify credentials against database
        if db.verify_user(username, password):
            user = User(username)
            login_user(user, remember=True)
            session.permanent = True  # Make session permanent
            logger.info(f"User {username} logged in successfully")
            db.log_message("INFO", f"User {username} logged in", "webapp")
            return redirect(url_for('dashboard'))
        else:
            logger.warning(f"Failed login attempt for username: {username}")
            db.log_message("WARNING", f"Failed login attempt for username: {username}", "webapp")
            flash('Invalid credentials, please try again.', 'error')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    """Logout route"""
    logger.info(f"User {current_user.id} logged out")
    db.log_message("INFO", f"User {current_user.id} logged out", "webapp")
    logout_user()
    flash('You have been logged out successfully.', 'success')
    return redirect(url_for('login'))

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    """User settings page"""
    try:
        if request.method == 'POST':
            # Get form data
            timezone = request.form.get('timezone', 'America/Chicago')
            date_format = request.form.get('date_format', '%Y-%m-%d %I:%M:%S %p')
            theme = request.form.get('theme', 'light')
            map_default_zoom = int(request.form.get('map_default_zoom', 10))
            refresh_interval = int(request.form.get('refresh_interval', 300))
            
            # Validate timezone
            if not validate_timezone(timezone):
                flash('Invalid timezone selected.', 'error')
                return redirect(url_for('settings'))
            
            # Prepare settings dict
            settings_data = {
                'timezone': timezone,
                'date_format': date_format,
                'theme': theme,
                'map_default_zoom': map_default_zoom,
                'refresh_interval': refresh_interval
            }
            
            # Update user settings
            if db.update_user_settings(current_user.id, settings_data):
                flash('Settings updated successfully!', 'success')
                logger.info(f"User {current_user.id} updated settings")
                db.log_message("INFO", f"User {current_user.id} updated settings", "webapp")
            else:
                flash('Failed to update settings. Please try again.', 'error')
            
            return redirect(url_for('settings'))
        
        # GET request - show settings form
        current_settings = db.get_user_settings(current_user.id)
        timezone_groups = db.get_available_timezones()
        
        return render_template('settings.html',
                             current_settings=current_settings,
                             timezone_groups=timezone_groups)
        
    except Exception as e:
        logger.error(f"Error in settings page: {e}")
        flash('An error occurred while loading settings.', 'error')
        return redirect(url_for('dashboard'))

@app.route('/')
@login_required
def dashboard():
    """Render the dashboard with iPhone locations on a map."""
    try:
        # Get parameters from request
        selected_date = request.args.get('date')  # Format: YYYY-MM-DD
        device_name = request.args.get('device')
        
        # If no date provided, default to today's date in user timezone
        if not selected_date:
            today = get_cst_now().strftime('%Y-%m-%d')
            selected_date = today

        # Show 24-hour movement for the selected date (or today if no date specified)
        if selected_date:
            try:
                # Determine user's timezone
                user_tz = 'America/Chicago'
                if current_user.is_authenticated:
                    try:
                        user_settings = db.get_user_settings(current_user.id)
                        user_tz = user_settings.get('timezone', 'America/Chicago')
                    except Exception:
                        pass

                # Build local day window [00:00, 23:59:59] in user's TZ and convert to UTC
                local_day_start_str = selected_date + 'T00:00:00'
                start_utc = convert_local_to_utc(local_day_start_str, user_tz)
                end_utc = start_utc + timedelta(days=1)

                # Get 24 hours of movement data with clustering using UTC window
                location_history = db.get_locations(
                    start_time=start_utc.isoformat(),
                    end_time=end_utc.isoformat(),
                    device_name=device_name,
                    limit=500,
                    cluster_locations=True
                )

                if not location_history:
                    # Fallback: try to get recent data if nothing found for selected date
                    recent_start_local = get_cst_now() - timedelta(hours=48)  # Try last 48 hours in local TZ
                    location_history = db.get_locations(
                        start_time=recent_start_local.isoformat(),
                        device_name=device_name,
                        limit=100,
                        cluster_locations=True
                    )
                    if not location_history:
                        flash(f'No location data found for {selected_date} or recent dates.', 'info')
                    else:
                        flash(f'No data for {selected_date}. Showing recent data instead.', 'info')

            except ValueError:
                flash('Invalid date format. Please select a valid date.', 'error')
                location_history = []

        # Get list of available devices for filter dropdown (only active devices, with display names)
        available_devices = []
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT DISTINCT l.device_name,
                           COALESCE(d.nickname, l.device_name) AS display_name
                    FROM locations l
                    LEFT JOIN devices d ON l.device_name = d.device_name
                    WHERE l.device_name IS NOT NULL AND l.device_name != ''
                      AND (d.is_active IS NULL OR d.is_active = TRUE)
                    ORDER BY display_name
                ''')
                rows = cursor.fetchall()
                available_devices = [
                    {'device_name': row['device_name'], 'display_name': row['display_name']}
                    for row in rows
                ]
        except Exception as e:
            logger.error(f"Error getting device list: {e}")

        # Ensure JSON-serializable location objects for the template, filter inactive devices
        safe_locations = [serialize_location_row(row) for row in (location_history or [])]
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT device_name FROM devices WHERE is_active = FALSE")
                inactive = {row['device_name'] for row in cursor.fetchall()}
        except Exception:
            inactive = set()
        if inactive:
            safe_locations = [loc for loc in safe_locations if loc.get('device_name') not in inactive]

        # Get statistics for dashboard display
        stats = db.get_statistics()
        # Determine offline devices (no recent update in last 2 hours)
        offline_devices = set()
        try:
            if stats and stats.get('devices'):
                now = datetime.now()
                for d in stats['devices']:
                    last_seen = d.get('last_seen')
                    name = d.get('device_name')
                    if last_seen and name:
                        try:
                            last_dt = last_seen if isinstance(last_seen, datetime) else datetime.fromisoformat(str(last_seen).replace('Z', '+00:00'))
                            age_hours = (now - last_dt).total_seconds() / 3600.0
                            if age_hours >= 2.0:
                                offline_devices.add(name)
                        except Exception:
                            pass
        except Exception as _e:
            logger.debug(f"offline_devices compute error: {_e}")
        
        return render_template('dashboard.html', 
                             location_history=safe_locations,
                             available_devices=available_devices,
                             selected_date=selected_date,
                             selected_device=device_name,
                             stats=stats,
                             offline_devices=offline_devices)
    
    except Exception as e:
        logger.error(f"Error loading dashboard: {e}")
        db.log_message("ERROR", f"Error loading dashboard: {e}", "webapp")
        flash('An error occurred while loading the dashboard.', 'error')
        return render_template('dashboard.html', 
                             location_history=[],
                             available_devices=[],
                             selected_date=None,
                             selected_device=None,
                             stats={'total_locations': 0, 'unique_devices': 0, 'today_count': 0})

@app.route('/api/locations')
@login_required
@limiter.limit("30 per minute")
def api_locations():
    """API endpoint for getting location data"""
    try:
        start_time = request.args.get('start')
        end_time = request.args.get('end')
        device_name = request.args.get('device')
        limit = int(request.args.get('limit', 1000))
        
        location_history = db.get_locations(
            start_time=start_time,
            end_time=end_time,
            device_name=device_name,
            limit=limit,
            cluster_locations=True
        )
        
        safe_locations = [serialize_location_row(row) for row in (location_history or [])]
        return jsonify(safe_locations)
    except Exception as e:
        logger.error(f"Error in API endpoint: {e}")
        db.log_message("ERROR", f"Error in API endpoint: {e}", "webapp")
        return jsonify({'error': 'Failed to load location data'}), 500

@app.route('/api/health')
def health_check():
    """Health check endpoint for monitoring"""
    try:
        # Get database statistics
        stats = db.get_statistics()
        
        # MariaDB doesn't have a single file size, use connection status instead
        db_size = 0  # MariaDB size would require separate query
        
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'database_size': db_size,
            'total_locations': stats['total_locations'],
            'unique_devices': stats['unique_devices'],
            'last_update': stats['last_update']
        })
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        db.log_message("ERROR", f"Health check failed: {e}", "webapp")
        return jsonify({'status': 'unhealthy', 'error': 'A server error occurred'}), 500

@app.route('/api/cache-stats')
@login_required
def cache_stats():
    """Get cache performance statistics"""
    try:
        stats = get_all_cache_stats()
        return jsonify({
            'success': True,
            'cache_stats': stats,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Error getting cache stats: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/stats')
@login_required
def api_stats():
    """API endpoint for getting statistics"""
    try:
        stats = db.get_statistics()
        return jsonify(stats)
    except Exception as e:
        logger.error(f"Error in stats API: {e}")
        db.log_message("ERROR", f"Error in stats API: {e}", "webapp")
        return jsonify({'error': 'Failed to load statistics'}), 500

@app.route('/api/devices')
@login_required
def api_devices():
    """API endpoint for getting device information"""
    try:
        devices = db.get_devices()
        return jsonify(devices)
    except Exception as e:
        logger.error(f"Error in devices API: {e}")
        db.log_message("ERROR", f"Error in devices API: {e}", "webapp")
        return jsonify({'error': 'Failed to load device data'}), 500

@app.route('/api/logs')
@login_required
def api_logs():
    """API endpoint for getting application logs"""
    try:
        level = request.args.get('level', 'INFO')
        limit = int(request.args.get('limit', 100))
        
        # Get logs from database
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT level, message, timestamp, source
                FROM logs
                WHERE level = %s
                ORDER BY timestamp DESC
                LIMIT %s
            ''', (level, limit))
            
            logs = list(cursor.fetchall())
        
        return jsonify(logs)
    except Exception as e:
        logger.error(f"Error in logs API: {e}")
        return jsonify({'error': 'Failed to load logs'}), 500

@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal server error: {error}")
    db.log_message("ERROR", f"Internal server error: {error}", "webapp")
    return render_template('500.html'), 500

@app.errorhandler(429)
def ratelimit_handler(e):
    return jsonify({'error': 'Rate limit exceeded'}), 429

@app.route('/api/address')
@login_required
@limiter.limit("60 per minute")
def api_address():
    """API endpoint for getting address from coordinates"""
    try:
        lat = request.args.get('lat', type=float)
        lng = request.args.get('lng', type=float)
        
        if lat is None or lng is None:
            return jsonify({'error': 'Missing lat or lng parameters'}), 400
        
        # Use analytics module to get address with caching
        from analytics import analytics
        address = analytics.get_address_from_coordinates(lat, lng, use_cache=True)
        
        return jsonify({'address': address})
    except Exception as e:
        logger.error(f"Error in address API endpoint: {e}")
        return jsonify({'error': 'Failed to get address'}), 500

@app.route('/analytics')
@login_required
def analytics_dashboard():
    """Analytics dashboard page"""
    try:
        # Get list of available devices
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT DISTINCT device_name, 
                       COUNT(*) as location_count,
                       MAX(timestamp) as last_seen
                FROM locations 
                GROUP BY device_name
                ORDER BY last_seen DESC
            ''')
            devices = list(cursor.fetchall())
        
        return render_template('analytics.html', devices=devices)
    except Exception as e:
        logger.error(f"Error loading analytics dashboard: {e}")
        flash('An error occurred while loading the analytics dashboard.', 'error')
        return redirect(url_for('dashboard'))

@app.route('/analytics/<device_name>')
@login_required
def device_analytics(device_name):
    """Detailed analytics for a specific device"""
    try:
        # Get date parameter (default to today)
        selected_date = request.args.get('date')
        if not selected_date:
            selected_date = get_cst_now().strftime('%Y-%m-%d')
        
        # Get device analytics
        analytics_data = analytics.get_device_analytics(device_name, selected_date)
        
        if 'error' in analytics_data:
            flash(f"No data found for {device_name} on {selected_date}", 'info')
            return redirect(url_for('analytics_dashboard'))
        
        # Get summary stats for the past week
        summary_stats = analytics.get_device_summary_stats(device_name, days=7)
        
        # Get cache information for top locations
        weekly_cache_info = analytics.get_cache_info(device_name, 'weekly')
        alltime_cache_info = analytics.get_cache_info(device_name, 'alltime')
        
        return render_template('device_analytics.html', 
                             device_name=device_name,
                             selected_date=selected_date,
                             analytics_data=analytics_data,
                             summary_stats=summary_stats,
                             weekly_cache_info=weekly_cache_info,
                             alltime_cache_info=alltime_cache_info)
    except Exception as e:
        logger.error(f"Error loading device analytics: {e}")
        flash('An error occurred while loading device analytics.', 'error')
        return redirect(url_for('analytics_dashboard'))

@app.route('/analytics/<device_name>/place/<int:place_id>')
@login_required
def view_place_visits(device_name, place_id):
    """View all visits for a specific device/place (stable place_id)."""
    try:
        # Pull visits
        visits = db.get_visits_for_place(device_name, place_id)
        # Get place info
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM device_location_places WHERE id = %s AND device_name = %s",
                (place_id, device_name)
            )
            place = cursor.fetchone()
        if not place:
            flash('Place not found.', 'error')
            return redirect(url_for('analytics_dashboard'))

        # Aggregate summary
        total_visits = len(visits)
        total_minutes = sum(v['duration_minutes'] for v in visits) if visits else 0
        first_visit = visits[0]['arrival'] if visits else None
        last_visit = visits[-1]['departure'] if visits else None

        return render_template('location_visits.html',
                             device_name=device_name,
                             place=place,
                             place_id=place_id,
                             visits=visits,
                             total_visits=total_visits,
                             total_minutes=total_minutes,
                             first_visit=first_visit,
                             last_visit=last_visit)
    except Exception as e:
        logger.error(f"Error viewing place visits: {e}")
        flash('An error occurred while loading visits for this place.', 'error')
        return redirect(url_for('analytics_dashboard'))

@app.route('/export/<device_name>')
@login_required
@limiter.limit("5 per minute")
def export_device_data(device_name):
    """Export device location data"""
    try:
        selected_date = request.args.get('date', get_cst_now().strftime('%Y-%m-%d'))
        format_type = request.args.get('format', 'json')  # json, csv, or kml
        
        analytics_data = analytics.get_device_analytics(device_name, selected_date)
        
        if 'error' in analytics_data:
            flash(f"No data to export for {device_name} on {selected_date}", 'error')
            return redirect(url_for('device_analytics', device_name=device_name))
        
        if format_type == 'csv':
            return export_as_csv(analytics_data)
        elif format_type == 'kml':
            return export_as_kml(analytics_data)
        else:
            return export_as_json(analytics_data)
            
    except Exception as e:
        logger.error(f"Error exporting device data: {e}")
        flash('An error occurred while exporting data.', 'error')
        return redirect(url_for('device_analytics', device_name=device_name))

@app.route('/heatmap')
@login_required
def heatmap_overview():
    """Location heatmap overview page"""
    try:
        # Get parameters
        days = int(request.args.get('days', 30))
        device_name = request.args.get('device', None)
        
        # Limit days to reasonable range
        days = max(1, min(days, 365))
        
        # Get available devices for filter dropdown
        available_devices = []
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT DISTINCT device_name 
                    FROM locations 
                    WHERE timestamp >= DATE_SUB(NOW(), INTERVAL 365 DAY)
                    ORDER BY device_name
                ''')
                available_devices = [row['device_name'] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting device list for heatmap: {e}")

        # Get heatmap statistics
        heatmap_stats = analytics.get_heatmap_stats(device_name, days)
        
        return render_template('heatmap.html',
                             days=days,
                             selected_device=device_name,
                             available_devices=available_devices,
                             heatmap_stats=heatmap_stats)
    except Exception as e:
        logger.error(f"Error loading heatmap overview: {e}")
        flash('An error occurred while loading the heatmap.', 'error')
        return redirect(url_for('dashboard'))

@app.route('/heatmap/data')
@login_required
@limiter.limit("10 per minute")
def heatmap_data():
    """Serve heatmap HTML data"""
    try:
        days = int(request.args.get('days', 30))
        device_name = request.args.get('device', None)
        
        # Limit days to reasonable range
        days = max(1, min(days, 365))
        
        # Generate heatmap HTML
        heatmap_html = analytics.create_heatmap_html(device_name, days)
        
        return heatmap_html
    except Exception as e:
        logger.error(f"Error generating heatmap data: {e}")
        return analytics._create_no_data_map()

@app.route('/api/heatmap/stats')
@login_required
@limiter.limit("30 per minute")
def api_heatmap_stats():
    """API endpoint for heatmap statistics"""
    try:
        days = int(request.args.get('days', 30))
        device_name = request.args.get('device', None)
        
        # Limit days to reasonable range
        days = max(1, min(days, 365))
        
        stats = analytics.get_heatmap_stats(device_name, days)
        return jsonify(stats)
    except Exception as e:
        logger.error(f"Error in heatmap stats API: {e}")
        return jsonify({'error': 'Failed to load heatmap statistics'}), 500

@app.route('/playback')
@login_required
def historical_playback():
    """Historical playback animation page"""
    try:
        # Get parameters
        device_name = request.args.get('device', None)
        start_date = request.args.get('start_date', None)
        end_date = request.args.get('end_date', None)
        
        # Default to yesterday if no dates provided
        if not start_date or not end_date:
            yesterday_cst = get_cst_now() - timedelta(days=1)
            today_cst = get_cst_now()
            start_date = yesterday_cst.strftime('%Y-%m-%d')
            end_date = today_cst.strftime('%Y-%m-%d')
        
        # Get available devices for filter dropdown
        available_devices = []
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT DISTINCT l.device_name,
                           COALESCE(d.nickname, l.device_name) as display_name
                    FROM locations l 
                    LEFT JOIN devices d ON l.device_name = d.device_name
                    WHERE l.device_name IS NOT NULL AND l.device_name != ''
                    ORDER BY display_name
                ''')
                available_devices = [{'device_name': row['device_name'], 'display_name': row['display_name']} for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting device list for playbook: {e}")
        
        return render_template('playback.html',
                             selected_device=device_name,
                             start_date=start_date,
                             end_date=end_date,
                             available_devices=available_devices)
    except Exception as e:
        logger.error(f"Error loading historical playback: {e}")
        flash('An error occurred while loading the playback view.', 'error')
        return redirect(url_for('dashboard'))

@app.route('/api/playback/data')
@login_required
@limiter.limit("20 per minute")
def api_playback_data():
    """API endpoint for historical playback data"""
    try:
        device_name = request.args.get('device', None)
        # Normalize empty device to None (treat as all devices)
        if device_name == '':
            device_name = None
        start_date = request.args.get('start_date', None)
        end_date = request.args.get('end_date', None)
        
        # Convert dates to full ISO format for database query
        if start_date:
            start_date = start_date + "T00:00:00"
        if end_date:
            end_date = end_date + "T23:59:59"
        
        playback_data = analytics.get_historical_playback_data(device_name, start_date, end_date)
        return jsonify(playback_data)
    except Exception as e:
        logger.error(f"Error in playback data API: {e}")
        return jsonify({'error': 'Failed to load playback data'}), 500

@app.route('/geofences')
@login_required
def geofences_overview():
    """Geofences management page"""
    try:
        # Get all geofences
        geofences = analytics.get_geofences()
        
        # Get recent events
        recent_events = analytics.get_geofence_events(limit=20)
        
        # Get available devices for filter dropdown and recent locations for map centering
        available_devices = []
        recent_locations = []
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT DISTINCT l.device_name,
                           COALESCE(d.nickname, l.device_name) as display_name
                    FROM locations l 
                    LEFT JOIN devices d ON l.device_name = d.device_name
                    WHERE l.device_name IS NOT NULL AND l.device_name != ''
                    ORDER BY display_name
                ''')
                available_devices = [{'device_name': row['device_name'], 'display_name': row['display_name']} for row in cursor.fetchall()]
                
                # Get recent device locations for map centering (if no geofences exist)
                if not geofences:
                    cursor.execute('''
                        SELECT latitude, longitude
                        FROM locations 
                        WHERE timestamp >= DATE_SUB(NOW(), INTERVAL 7 DAY)
                        ORDER BY timestamp DESC
                        LIMIT 10
                    ''')
                    recent_locations = [{'lat': row['latitude'], 'lng': row['longitude']} for row in cursor.fetchall()]
                    
        except Exception as e:
            logger.error(f"Error getting device list for geofences: {e}")
        
        return render_template('geofences.html',
                             geofences=geofences,
                             recent_events=recent_events,
                             available_devices=available_devices,
                             recent_locations=recent_locations)
    except Exception as e:
        logger.error(f"Error loading geofences page: {e}")
        flash('An error occurred while loading geofences.', 'error')
        return redirect(url_for('dashboard'))

@app.route('/api/geofences', methods=['GET'])
@login_required
def api_get_geofences():
    """API endpoint to get geofences"""
    try:
        geofences = analytics.get_geofences()
        return jsonify(geofences)
    except Exception as e:
        logger.error(f"Error in geofences API: {e}")
        return jsonify({'error': 'Failed to load geofences'}), 500

@app.route('/api/geofences', methods=['POST'])
@login_required
@limiter.limit("10 per minute")
def api_create_geofence():
    """API endpoint to create a geofence"""
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['name', 'center_lat', 'center_lng', 'radius_meters']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing field: {field}'}), 400
        
        # Create geofence
        result = analytics.create_geofence(
            name=data['name'],
            center_lat=float(data['center_lat']),
            center_lng=float(data['center_lng']),
            radius_meters=int(data['radius_meters']),
            device_filter=data.get('device_filter'),
            alert_types=data.get('alert_types', ['enter', 'exit'])
        )
        
        if 'error' in result:
            return jsonify(result), 500
        else:
            return jsonify(result), 201
            
    except Exception as e:
        logger.error(f"Error creating geofence: {e}")
        return jsonify({'error': 'Failed to create geofence'}), 500

@app.route('/api/geofences/<int:geofence_id>', methods=['DELETE'])
@login_required
@limiter.limit("10 per minute")
def api_delete_geofence(geofence_id):
    """API endpoint to delete a geofence"""
    try:
        success = analytics.delete_geofence(geofence_id)
        if success:
            return jsonify({'message': 'Geofence deleted successfully'})
        else:
            return jsonify({'error': 'Geofence not found'}), 404
    except Exception as e:
        logger.error(f"Error deleting geofence: {e}")
        return jsonify({'error': 'Failed to delete geofence'}), 500

@app.route('/api/geofence-events')
@login_required
def api_geofence_events():
    """API endpoint for geofence events"""
    try:
        device_name = request.args.get('device')
        geofence_id = request.args.get('geofence_id')
        limit = int(request.args.get('limit', 50))
        
        events = analytics.get_geofence_events(
            device_name=device_name,
            geofence_id=int(geofence_id) if geofence_id else None,
            limit=limit
        )
        return jsonify(events)
    except Exception as e:
        logger.error(f"Error in geofence events API: {e}")
        return jsonify({'error': 'Failed to load geofence events'}), 500

@app.route('/notifications')
@login_required
def notifications_overview():
    """Notifications management page"""
    try:
        # Initialize with empty defaults to prevent template errors
        notification_rules = []
        recent_notifications = []
        geofences = []
        available_devices = []
        
        # Get notification rules
        try:
            logger.info("Getting notification rules...")
            notification_rules = analytics.get_notification_rules()
            logger.info(f"Retrieved {len(notification_rules)} notification rules")
        except Exception as e:
            logger.error(f"Error getting notification rules: {e}")
            notification_rules = []
        
        # Get recent notifications
        try:
            logger.info("Getting recent notifications...")
            recent_notifications = analytics.get_recent_notifications(limit=10)  # Reduced limit
            logger.info(f"Retrieved {len(recent_notifications)} recent notifications")
        except Exception as e:
            logger.error(f"Error getting recent notifications: {e}")
            recent_notifications = []  # Ensure it's still a list for template
        
        # Get geofences for dropdown
        try:
            logger.info("Getting geofences...")
            geofences = analytics.get_geofences()
            logger.info(f"Retrieved {len(geofences)} geofences")
        except Exception as e:
            logger.error(f"Error getting geofences: {e}")
            geofences = []
        
        # Get available devices for filter dropdown
        try:
            logger.info("Getting available devices...")
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT DISTINCT l.device_name,
                           COALESCE(d.nickname, l.device_name) as display_name
                    FROM locations l 
                    LEFT JOIN devices d ON l.device_name = d.device_name
                    WHERE l.device_name IS NOT NULL AND l.device_name != ''
                    ORDER BY display_name
                    LIMIT 100
                ''')
                rows = cursor.fetchall()
                available_devices = []
                for row in rows:
                    try:
                        device_info = {'device_name': row['device_name'], 'display_name': row['display_name']}
                        available_devices.append(device_info)
                    except KeyError as ke:
                        logger.error(f"Column not found in row: {ke}. Available columns: {list(row.keys()) if hasattr(row, 'keys') else 'N/A'}")
                        # Fallback
                        available_devices.append({'device_name': row.get('device_name', 'Unknown'), 'display_name': row.get('display_name', 'Unknown')})
                logger.info(f"Retrieved {len(available_devices)} available devices")
        except Exception as e:
            logger.error(f"Error getting device list for notifications: {e}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            available_devices = []
        
        return render_template('notifications.html',
                             notification_rules=notification_rules,
                             recent_notifications=recent_notifications,
                             geofences=geofences,
                             available_devices=available_devices)
    except Exception as e:
        logger.error(f"Error loading notifications page: {e}")
        flash('An error occurred while loading notifications.', 'error')
        return redirect(url_for('dashboard'))

@app.route('/notifications/all')
@login_required  
def all_notifications():
    """Full notifications history page with filtering and pagination"""
    try:
        # Get pagination parameters
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 50, type=int)
        
        # Get filter parameters
        device_filter = request.args.get('device', '')
        priority_filter = request.args.get('priority', '')
        type_filter = request.args.get('type', '')
        start_date = request.args.get('start_date', '')
        end_date = request.args.get('end_date', '')
        unread_only = request.args.get('unread_only', '') == 'true'
        
        # Calculate offset
        offset = (page - 1) * per_page
        
        # Build query with filters
        where_conditions = ['1=1']
        params = []
        
        if device_filter:
            where_conditions.append('device_name = %s')
            params.append(device_filter)
            
        if priority_filter:
            where_conditions.append('priority = %s')
            params.append(priority_filter)
            
        if type_filter:
            where_conditions.append('notification_type = %s')
            params.append(type_filter)
            
        if start_date:
            where_conditions.append('DATE(timestamp) >= DATE(%s)')
            params.append(start_date)
            
        if end_date:
            where_conditions.append('DATE(timestamp) <= DATE(%s)')
            params.append(end_date)
            
        if unread_only:
            where_conditions.append('is_read = FALSE')
        
        where_clause = ' AND '.join(where_conditions)
        
        # Get notifications with pagination
        notifications = []
        total_count = 0
        
        with db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get total count
            count_query = f'SELECT COUNT(*) FROM sent_notifications WHERE {where_clause}'
            cursor.execute(count_query, params)
            total_count = cursor.fetchone()[0]
            
            # Get notifications
            query = f'''
                SELECT id, device_name, message, notification_type, priority, 
                       timestamp, is_read, read_at, rule_id, geofence_id, event_type
                FROM sent_notifications 
                WHERE {where_clause}
                ORDER BY timestamp DESC 
                LIMIT %s OFFSET %s
            '''
            params.extend([per_page, offset])
            cursor.execute(query, params)
            
            for row in cursor.fetchall():
                notifications.append(dict(row))
        
        # Calculate pagination info
        total_pages = (total_count + per_page - 1) // per_page
        has_prev = page > 1
        has_next = page < total_pages
        
        # Get available devices and types for filters
        available_devices = []
        available_types = []
        priorities = ['low', 'normal', 'high', 'urgent']
        
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT DISTINCT device_name FROM sent_notifications ORDER BY device_name')
            available_devices = [row[0] for row in cursor.fetchall()]
            
            cursor.execute('SELECT DISTINCT notification_type FROM sent_notifications ORDER BY notification_type') 
            available_types = [row['notification_type'] for row in cursor.fetchall()]
        
        return render_template('all_notifications.html',
                             notifications=notifications,
                             total_count=total_count,
                             page=page,
                             per_page=per_page,
                             total_pages=total_pages,
                             has_prev=has_prev,
                             has_next=has_next,
                             device_filter=device_filter,
                             priority_filter=priority_filter,
                             type_filter=type_filter,
                             start_date=start_date,
                             end_date=end_date,
                             unread_only=unread_only,
                             available_devices=available_devices,
                             available_types=available_types,
                             priorities=priorities)
                             
    except Exception as e:
        logger.error(f"Error loading all notifications page: {e}")
        flash('An error occurred while loading notifications.', 'error')
        return redirect(url_for('notifications_overview'))

@app.route('/api/notification-rules', methods=['GET'])
@login_required
def api_get_notification_rules():
    """API endpoint to get notification rules"""
    try:
        rules = analytics.get_notification_rules()
        return jsonify(rules)
    except Exception as e:
        logger.error(f"Error in notification rules API: {e}")
        return jsonify({'error': 'Failed to load notification rules'}), 500

@app.route('/api/notification-rules', methods=['POST'])
@login_required
@limiter.limit("10 per minute")
def api_create_notification_rule():
    """API endpoint to create a notification rule"""
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['name', 'trigger_type']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing field: {field}'}), 400
        
        # Create notification rule
        result = analytics.create_notification_rule(
            name=data['name'],
            trigger_type=data['trigger_type'],
            geofence_id=data.get('geofence_id'),
            device_filter=data.get('device_filter'),
            notification_methods=data.get('notification_methods', ['log'])
        )
        
        if 'error' in result:
            return jsonify(result), 500
        else:
            return jsonify(result), 201
            
    except Exception as e:
        logger.error(f"Error creating notification rule: {e}")
        return jsonify({'error': 'Failed to create notification rule'}), 500

@app.route('/api/notification-rules/<int:rule_id>', methods=['DELETE'])
@login_required
@limiter.limit("10 per minute")
def api_delete_notification_rule(rule_id):
    """API endpoint to delete a notification rule"""
    try:
        success = analytics.delete_notification_rule(rule_id)
        if success:
            return jsonify({'message': 'Notification rule deleted successfully'})
        else:
            return jsonify({'error': 'Notification rule not found'}), 404
    except Exception as e:
        logger.error(f"Error deleting notification rule: {e}")
        return jsonify({'error': 'Failed to delete notification rule'}), 500

@app.route('/api/recent-notifications')
@login_required
def api_recent_notifications():
    """API endpoint for recent notifications"""
    try:
        limit = int(request.args.get('limit', 30))
        notifications = analytics.get_recent_notifications(limit=limit)
        return jsonify(notifications)
    except Exception as e:
        logger.error(f"Error in recent notifications API: {e}")
        return jsonify({'error': 'Failed to load recent notifications'}), 500

@app.route('/search')
@login_required
def search_overview():
    """Location search and bookmarks page"""
    try:
        # Get bookmarks
        bookmarks = analytics.get_bookmarks()
        
        # Get bookmark categories
        categories = analytics.get_bookmark_categories()
        
        # Get available devices for search filters
        available_devices = []
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT DISTINCT device_name 
                    FROM locations 
                    WHERE timestamp >= DATE_SUB(NOW(), INTERVAL 365 DAY)
                    ORDER BY device_name
                ''')
                available_devices = [row['device_name'] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting device list for search: {e}")
        
        return render_template('search.html',
                             bookmarks=bookmarks,
                             categories=categories,
                             available_devices=available_devices)
    except Exception as e:
        logger.error(f"Error loading search page: {e}")
        flash('An error occurred while loading the search page.', 'error')
        return redirect(url_for('dashboard'))

@app.route('/api/search')
@login_required
@limiter.limit("30 per minute")
def api_search():
    """API endpoint for location search"""
    try:
        query = request.args.get('q', '').strip()
        device_name = request.args.get('device')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        center_lat = request.args.get('center_lat', type=float)
        center_lng = request.args.get('center_lng', type=float)
        radius_km = request.args.get('radius_km', type=float, default=5.0)
        
        if not query:
            return jsonify({'error': 'Search query is required'}), 400
        
        # Perform search
        results = analytics.search_locations(
            query=query,
            device_name=device_name,
            start_date=start_date,
            end_date=end_date,
            center_lat=center_lat,
            center_lng=center_lng,
            radius_km=radius_km
        )
        
        return jsonify(results)
    except Exception as e:
        logger.error(f"Error in search API: {e}")
        return jsonify({'error': 'Failed to perform search'}), 500

@app.route('/api/bookmarks', methods=['GET'])
@login_required
def api_get_bookmarks():
    """API endpoint to get bookmarks"""
    try:
        category = request.args.get('category')
        bookmarks = analytics.get_bookmarks(category=category)
        return jsonify(bookmarks)
    except Exception as e:
        logger.error(f"Error in bookmarks API: {e}")
        return jsonify({'error': 'Failed to load bookmarks'}), 500

@app.route('/api/bookmarks', methods=['POST'])
@login_required
@limiter.limit("20 per minute")
def api_create_bookmark():
    """API endpoint to create a bookmark"""
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['name', 'latitude', 'longitude']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing field: {field}'}), 400
        
        # Create bookmark
        result = analytics.create_bookmark(
            name=data['name'],
            latitude=float(data['latitude']),
            longitude=float(data['longitude']),
            address=data.get('address'),
            description=data.get('description'),
            category=data.get('category', 'general')
        )
        
        if 'error' in result:
            return jsonify(result), 500
        else:
            return jsonify(result), 201
            
    except Exception as e:
        logger.error(f"Error creating bookmark: {e}")
        return jsonify({'error': 'Failed to create bookmark'}), 500

@app.route('/api/bookmarks/<int:bookmark_id>', methods=['DELETE'])
@login_required
@limiter.limit("20 per minute")
def api_delete_bookmark(bookmark_id):
    """API endpoint to delete a bookmark"""
    try:
        success = analytics.delete_bookmark(bookmark_id)
        if success:
            return jsonify({'message': 'Bookmark deleted successfully'})
        else:
            return jsonify({'error': 'Bookmark not found'}), 404
    except Exception as e:
        logger.error(f"Error deleting bookmark: {e}")
        return jsonify({'error': 'Failed to delete bookmark'}), 500

@app.route('/api/nearby')
@login_required
@limiter.limit("30 per minute")
def api_nearby_locations():
    """API endpoint for nearby locations"""
    try:
        latitude = float(request.args.get('lat'))
        longitude = float(request.args.get('lng'))
        radius_km = float(request.args.get('radius', 1.0))
        limit = int(request.args.get('limit', 20))
        
        nearby = analytics.get_nearby_locations(latitude, longitude, radius_km, limit)
        return jsonify(nearby)
    except Exception as e:
        logger.error(f"Error in nearby locations API: {e}")
        return jsonify({'error': 'Failed to find nearby locations'}), 500

@app.route('/reports')
@login_required
def travel_reports():
    """Travel reports and summaries page"""
    try:
        # Get available devices for filtering
        available_devices = []
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT DISTINCT l.device_name,
                           COALESCE(d.nickname, l.device_name) as display_name
                    FROM locations l
                    LEFT JOIN devices d ON l.device_name = d.device_name
                    ORDER BY display_name
                ''')
                rows = cursor.fetchall()
                available_devices = [{'device_name': row['device_name'], 'display_name': row['display_name']} for row in rows]
        except Exception as e:
            logger.error(f"Error getting device list for reports: {e}")
        
        # Check if we have report parameters
        device_filter = request.args.get('device')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        report_data = None
        if device_filter or start_date or end_date:
            # Generate report
            logger.info(f"Generating travel report for device='{device_filter}', start_date='{start_date}', end_date='{end_date}'")
            try:
                report_data = analytics.generate_travel_report(
                    device_name=device_filter,
                    start_date=start_date,
                    end_date=end_date
                )
                logger.info(f"Travel report generated successfully with {report_data.get('summary', {}).get('total_locations', 0)} locations")
            except Exception as e:
                logger.error(f"Error generating travel report: {e}")
                flash(f'Error generating travel report: {str(e)}', 'error')
        
        return render_template('reports.html',
                             available_devices=available_devices,
                             report_data=report_data,
                             selected_device=device_filter,
                             start_date=start_date,
                             end_date=end_date)
                             
    except Exception as e:
        logger.error(f"Error loading reports page: {e}")
        flash('An error occurred while loading the reports page.', 'error')
        return redirect(url_for('dashboard'))

@app.route('/api/travel-report')
@login_required
@limiter.limit("10 per minute")
def api_travel_report():
    """API endpoint for generating travel reports"""
    try:
        device_name = request.args.get('device')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        # Generate report
        report = analytics.generate_travel_report(
            device_name=device_name,
            start_date=start_date,
            end_date=end_date
        )
        
        return jsonify(report)
        
    except Exception as e:
        logger.error(f"Error generating travel report: {e}")
        return jsonify({'error': 'Failed to generate travel report'}), 500

@app.route('/gps-logs')
@login_required
def gps_logs():
    """GPS logs page with filtering, caching, and export options"""
    try:
        # Get filter parameters
        device_filter = request.args.get('device', '')
        start_date = request.args.get('start_date', '')
        end_date = request.args.get('end_date', '')
        hide_stale = request.args.get('hide_stale', '') == '1'
        limit = int(request.args.get('limit', 500))
        page = int(request.args.get('page', 1))
        
        # Optimize limit to prevent performance issues
        limit = min(max(limit, 10), 1000)  # Reduced max limit from 2000 to 1000
        offset = (page - 1) * limit
        
        # Check cache first
        cache_key = _get_cache_key(device_filter, start_date, end_date, limit, page)
        cached_result = _get_cached_logs(cache_key)
        
        if cached_result:
            logs_data, total_count, available_devices = cached_result
        else:
            # Get available devices for filtering (with display names)
            available_devices = []
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT DISTINCT l.device_name,
                           COALESCE(d.nickname, l.device_name) AS display_name
                    FROM locations l
                    LEFT JOIN devices d ON l.device_name = d.device_name
                    WHERE l.device_name IS NOT NULL AND l.device_name != ''
                    ORDER BY display_name
                ''')
                rows = cursor.fetchall()
                available_devices = [
                    {'device_name': row['device_name'], 'display_name': row['display_name']}
                    for row in rows
                ]
        except Exception as e:
            logger.error(f"Error getting device list for GPS logs: {e}")
        
        # Build optimized query with filters and pagination
        logs_data = []
        total_count = 0
        
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                
                # Build base WHERE clause
                where_conditions = ['1=1']
                params = []
                
                if device_filter:
                    where_conditions.append('device_name = %s')
                    params.append(device_filter)
                
                if start_date:
                    where_conditions.append('DATE(timestamp) >= DATE(%s)')
                    params.append(start_date)
                
                if end_date:
                    where_conditions.append('DATE(timestamp) <= DATE(%s)')
                    params.append(end_date)
                
                # Filter out stale data if requested
                if hide_stale:
                    where_conditions.append('timestamp >= DATE_SUB(NOW(), INTERVAL 24 HOUR)')
                
                where_clause = ' AND '.join(where_conditions)
                
                # Use window function for efficient pagination with total count
                optimized_query = f'''
                    SELECT 
                        id, device_name, latitude, longitude, timestamp, 
                        accuracy, battery_level, is_charging, created_at,
                        COUNT(*) OVER() as total_count
                    FROM locations 
                    WHERE {where_clause}
                    ORDER BY timestamp DESC 
                    LIMIT %s OFFSET %s
                '''
                
                params.extend([limit, offset])
                
                cursor.execute(optimized_query, params)
                rows = cursor.fetchall()
                logs_data = list(rows)
                
            # Extract total count from first row if available
            if logs_data:
                total_count = logs_data[0]['total_count']
                # Remove total_count from each row and calculate age
                current_time = datetime.now()
                for log in logs_data:
                    del log['total_count']
                    
                    # Calculate age of location data
                    if log.get('timestamp'):
                        try:
                            # Convert timestamp to datetime if it's a string
                            if isinstance(log['timestamp'], str):
                                log_time = datetime.fromisoformat(log['timestamp'].replace('Z', '+00:00')).replace(tzinfo=None)
                            else:
                                log_time = log['timestamp']
                            
                            age_hours = (current_time - log_time).total_seconds() / 3600
                            log['age_hours'] = round(age_hours, 1)
                            log['is_stale'] = age_hours > 24
                        except (ValueError, TypeError) as e:
                            logger.warning(f"Error calculating age for timestamp {log['timestamp']}: {e}")
                            log['age_hours'] = 0
                            log['is_stale'] = False
            else:
                total_count = 0
            
            # Optimize address lookup - only for visible records and use batch processing
            if logs_data:
                # Add addresses in batches to avoid overwhelming reverse geocoding APIs
                batch_size = 10
                for i in range(0, len(logs_data), batch_size):
                    batch = logs_data[i:i+batch_size]
                    for log in batch:
                        try:
                            # Check address cache first
                            cached_address = db.get_cached_address(log['latitude'], log['longitude'])
                            if cached_address:
                                log['address'] = cached_address
                            else:
                                # Use a simplified address format for better performance
                                log['address'] = f"{log['latitude']:.4f}, {log['longitude']:.4f}"
                                
                                # Only do reverse geocoding for first few records to avoid API limits
                                if i < 3:  # Reduced from 5 to 3 for better performance
                                    try:
                                        full_address = analytics.get_address_from_coordinates(log['latitude'], log['longitude'])
                                        if full_address and len(full_address) > 10:  # Valid address
                                            log['address'] = full_address
                                            # Cache the result for future use
                                            db.cache_address(log['latitude'], log['longitude'], full_address)
                                    except Exception as e:
                                        logger.debug(f"Failed to get address from coordinates {log['latitude']}, {log['longitude']}: {e}")
                                        # Keep coordinate format on API failure
                        except Exception as e:
                            logger.debug(f"Could not process address for {log['latitude']}, {log['longitude']}: {e}")
                            log['address'] = f"({log['latitude']:.4f}, {log['longitude']:.4f})"
            
            # Cache the result for future requests
            _cache_logs(cache_key, (logs_data, total_count, available_devices))
                
        except Exception as e:
            logger.error(f"Error getting GPS logs data: {e}")
            flash('Error retrieving GPS logs data.', 'error')
            # Use empty defaults on error
            logs_data = []
            total_count = 0
            available_devices = []
        
        # Calculate pagination info
        total_pages = (total_count + limit - 1) // limit
        has_prev = page > 1
        has_next = page < total_pages
        
        # Check if this is an AJAX request for address prefetching
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.args.get('addresses_only'):
            # Enhanced address loading for prefetching
            enhanced_logs = []
            for log in logs_data:
                enhanced_log = dict(log)
                
                # Try to get better address if coordinates are shown
                if 'address' in enhanced_log and (',' in enhanced_log['address'] and '.' in enhanced_log['address'] and len(enhanced_log['address']) < 20):
                    try:
                        full_address = analytics.get_address_from_coordinates(enhanced_log['latitude'], enhanced_log['longitude'])
                        if full_address and len(full_address) > 10:
                            enhanced_log['address'] = full_address
                            # Cache for future use
                            db.cache_address(enhanced_log['latitude'], enhanced_log['longitude'], full_address)
                    except Exception as e:
                        logger.debug(f"Failed to get address from coordinates {enhanced_log['latitude']}, {enhanced_log['longitude']}: {e}")
                        # Keep existing format if geocoding fails
                
                enhanced_logs.append(enhanced_log)
            
            return jsonify({
                'success': True,
                'logs': enhanced_logs,
                'page': page,
                'total_pages': total_pages,
                'total_count': total_count
            })
        
        # Regular HTML response
        return render_template('gps_logs.html',
                             logs_data=logs_data,
                             available_devices=available_devices,
                             device_filter=device_filter,
                             start_date=start_date,
                             end_date=end_date,
                             hide_stale=hide_stale,
                             limit=limit,
                             page=page,
                             total_count=total_count,
                             total_pages=total_pages,
                             has_prev=has_prev,
                             has_next=has_next)
                             
    except Exception as e:
        logger.error(f"Error loading GPS logs page: {e}")
        flash('An error occurred while loading the GPS logs page.', 'error')
        return redirect(url_for('dashboard'))

@app.route('/api/gps-logs/export')
@login_required
@limiter.limit("5 per minute")
def api_export_gps_logs():
    """API endpoint to export GPS logs as CSV"""
    try:
        # Get filter parameters
        device_filter = request.args.get('device', '')
        start_date = request.args.get('start_date', '')
        end_date = request.args.get('end_date', '')
        format_type = request.args.get('format', 'csv')
        
        # Build query with filters
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                
                query = '''
                    SELECT device_name, latitude, longitude, timestamp, 
                           accuracy, battery_level, is_charging, created_at
                    FROM locations 
                    WHERE 1=1
                '''
                params = []
                
                if device_filter:
                    query += ' AND device_name = %s'
                    params.append(device_filter)
                
                if start_date:
                    query += ' AND DATE(timestamp) >= DATE(%s)'
                    params.append(start_date)
                
                if end_date:
                    query += ' AND DATE(timestamp) <= DATE(%s)'
                    params.append(end_date)
                
                query += ' ORDER BY timestamp DESC LIMIT 10000'  # Limit exports
                
                cursor.execute(query, params)
                rows = cursor.fetchall()
                logs_data = list(rows)
                
                # Add addresses to logs data for export
                for log in logs_data:
                    try:
                        log['address'] = analytics.get_address_from_coordinates(log['latitude'], log['longitude'])
                    except Exception as e:
                        logger.debug(f"Could not get address for {log['latitude']}, {log['longitude']}: {e}")
                        log['address'] = f"({log['latitude']:.4f}, {log['longitude']:.4f})"
                
        except Exception as e:
            logger.error(f"Error getting GPS logs for export: {e}")
            return jsonify({'error': 'Failed to retrieve GPS logs'}), 500
        
        if format_type == 'json':
            from flask import Response
            import json
            
            filename = f"gps_logs_{device_filter or 'all'}_{start_date or 'all'}_{end_date or 'all'}.json"
            
            response = Response(
                json.dumps(logs_data, indent=2, default=str),
                mimetype='application/json'
            )
            response.headers['Content-Disposition'] = f'attachment; filename={filename}'
            return response
            
        else:  # CSV format
            from flask import Response
            import csv
            import io
            
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=[
                'device_name', 'address', 'latitude', 'longitude', 'timestamp',
                'accuracy', 'battery_level', 'is_charging', 'created_at'
            ])
            
            writer.writeheader()
            for row in logs_data:
                writer.writerow(row)
            
            filename = f"gps_logs_{device_filter or 'all'}_{start_date or 'all'}_{end_date or 'all'}.csv"
            
            response = Response(
                output.getvalue(),
                mimetype='text/csv'
            )
            response.headers['Content-Disposition'] = f'attachment; filename={filename}'
            return response
            
    except Exception as e:
        logger.error(f"Error exporting GPS logs: {e}")
        return jsonify({'error': 'Failed to export GPS logs'}), 500

def export_as_json(analytics_data):
    """Export analytics data as JSON"""
    from flask import Response
    import json
    
    filename = f"{analytics_data['device_name']}_{analytics_data['date_range'].split()[0]}_locations.json"
    
    response = Response(
        json.dumps(analytics_data, indent=2),
        mimetype='application/json'
    )
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    return response

def export_as_csv(analytics_data):
    """Export analytics data as CSV"""
    from flask import Response
    import io
    import csv
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write headers
    writer.writerow(['Address', 'Latitude', 'Longitude', 'Visit Count', 'Total Time (min)', 'First Visit', 'Last Visit'])
    
    # Write location data
    for location in analytics_data['location_analytics']:
        writer.writerow([
            location['address'],
            location['latitude'],
            location['longitude'],
            location['visit_count'],
            location['total_time_minutes'],
            location['first_visit'],
            location['last_visit']
        ])
    
    filename = f"{analytics_data['device_name']}_{analytics_data['date_range'].split()[0]}_locations.csv"
    
    response = Response(
        output.getvalue(),
        mimetype='text/csv'
    )
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    return response

def export_as_kml(analytics_data):
    """Export analytics data as KML for Google Earth"""
    from flask import Response
    
    kml_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>{analytics_data['device_name']} Locations - {analytics_data['date_range'].split()[0]}</name>
    <description>Location data exported from iTrax</description>
'''
    
    for location in analytics_data['location_analytics']:
        kml_content += f'''
    <Placemark>
      <name>{location['address']}</name>
      <description>
        Visits: {location['visit_count']}
        Total Time: {location['total_time_minutes']} minutes
        First Visit: {location['first_visit']}
        Last Visit: {location['last_visit']}
      </description>
      <Point>
        <coordinates>{location['longitude']},{location['latitude']},0</coordinates>
      </Point>
    </Placemark>'''
    
    kml_content += '''
  </Document>
</kml>'''
    
    filename = f"{analytics_data['device_name']}_{analytics_data['date_range'].split()[0]}_locations.kml"
    
    response = Response(
        kml_content,
        mimetype='application/vnd.google-earth.kml+xml'
    )
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    return response

# User Management Routes and API Endpoints
@app.route('/admin/users')
@login_required
@admin_required
def user_management():
    """User management page (admin only)"""
    try:
        users = db.get_all_users()
        return render_template('user_management.html', users=users)
    except Exception as e:
        logger.error(f"Error loading user management page: {e}")
        flash('An error occurred while loading the user management page.', 'error')
        return redirect(url_for('dashboard'))

@app.route('/api/users')
@login_required
@admin_required
@limiter.limit("20 per minute")
def api_get_users():
    """API endpoint to get all users (admin only)"""
    try:
        users = db.get_all_users()
        # Format users for JSON response
        formatted_users = []
        for user in users:
            formatted_users.append({
                'id': user['id'],
                'username': user['username'],
                'is_admin': bool(user['is_admin']),
                'is_active': bool(user['is_active']),
                'created_at': user['created_at'].isoformat() if user['created_at'] else None,
                'last_login': user['last_login'].isoformat() if user['last_login'] else None
            })
        
        return jsonify({
            'success': True,
            'users': formatted_users
        })
    except Exception as e:
        logger.error(f"Error getting users: {e}")
        return jsonify({
            'success': False,
            'error': 'Failed to retrieve users'
        }), 500

@app.route('/api/users', methods=['POST'])
@login_required
@admin_required
@limiter.limit("10 per minute")
def api_create_user():
    """API endpoint to create a new user (admin only)"""
    try:
        data = request.get_json()
        username = data.get('username', '').strip()
        password = data.get('password', '')
        is_admin = data.get('is_admin', False)
        
        if not username or not password:
            return jsonify({
                'success': False,
                'error': 'Username and password are required'
            }), 400
        
        if len(password) < 6:
            return jsonify({
                'success': False,
                'error': 'Password must be at least 6 characters long'
            }), 400
        
        if db.create_user(username, password, is_admin):
            logger.info(f"Admin {current_user.id} created user {username}")
            db.log_message("INFO", f"Admin {current_user.id} created user {username}", "webapp")
            return jsonify({
                'success': True,
                'message': f'User {username} created successfully'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to create user. Username may already exist.'
            }), 400
            
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        return jsonify({
            'success': False,
            'error': 'Failed to create user'
        }), 500

@app.route('/api/users/<username>/admin', methods=['PUT'])
@login_required
@admin_required
@limiter.limit("10 per minute")
def api_update_user_admin(username):
    """API endpoint to update user admin status (admin only)"""
    try:
        data = request.get_json()
        is_admin = data.get('is_admin', False)
        
        # Prevent admin from removing their own admin status
        if username == current_user.id and not is_admin:
            return jsonify({
                'success': False,
                'error': 'Cannot remove admin status from yourself'
            }), 400
        
        if db.update_user_admin_status(username, is_admin):
            action = 'promoted to admin' if is_admin else 'removed from admin'
            logger.info(f"Admin {current_user.id} {action} user {username}")
            db.log_message("INFO", f"Admin {current_user.id} {action} user {username}", "webapp")
            return jsonify({
                'success': True,
                'message': f'User {username} admin status updated'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to update user admin status'
            }), 400
            
    except Exception as e:
        logger.error(f"Error updating user admin status: {e}")
        return jsonify({
            'success': False,
            'error': 'Failed to update user admin status'
        }), 500

@app.route('/api/users/<username>/active', methods=['PUT'])
@login_required
@admin_required
@limiter.limit("10 per minute")
def api_update_user_active(username):
    """API endpoint to enable/disable user (admin only)"""
    try:
        data = request.get_json()
        is_active = data.get('is_active', True)
        
        # Prevent admin from disabling themselves
        if username == current_user.id and not is_active:
            return jsonify({
                'success': False,
                'error': 'Cannot disable yourself'
            }), 400
        
        if db.update_user_active_status(username, is_active):
            action = 'enabled' if is_active else 'disabled'
            logger.info(f"Admin {current_user.id} {action} user {username}")
            db.log_message("INFO", f"Admin {current_user.id} {action} user {username}", "webapp")
            return jsonify({
                'success': True,
                'message': f'User {username} {action} successfully'
            })
        else:
            return jsonify({
                'success': False,
                'error': f'Failed to {"enable" if is_active else "disable"} user'
            }), 400
            
    except Exception as e:
        logger.error(f"Error updating user active status: {e}")
        return jsonify({
            'success': False,
            'error': 'Failed to update user status'
        }), 500

@app.route('/api/users/<username>/password', methods=['PUT'])
@login_required
@admin_required
@limiter.limit("5 per minute")
def api_change_user_password(username):
    """API endpoint to change user password (admin only)"""
    try:
        data = request.get_json()
        new_password = data.get('password', '')
        
        if len(new_password) < 6:
            return jsonify({
                'success': False,
                'error': 'Password must be at least 6 characters long'
            }), 400
        
        if db.change_user_password(username, new_password):
            logger.info(f"Admin {current_user.id} changed password for user {username}")
            db.log_message("INFO", f"Admin {current_user.id} changed password for user {username}", "webapp")
            return jsonify({
                'success': True,
                'message': f'Password updated for user {username}'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to change password'
            }), 400
            
    except Exception as e:
        logger.error(f"Error changing user password: {e}")
        return jsonify({
            'success': False,
            'error': 'Failed to change password'
        }), 500

@app.route('/api/users/<username>', methods=['DELETE'])
@login_required
@admin_required
@limiter.limit("5 per minute")
def api_delete_user(username):
    """API endpoint to delete user (admin only)"""
    try:
        # Prevent admin from deleting themselves
        if username == current_user.id:
            return jsonify({
                'success': False,
                'error': 'Cannot delete yourself'
            }), 400
        
        if db.delete_user(username):
            logger.info(f"Admin {current_user.id} deleted user {username}")
            db.log_message("INFO", f"Admin {current_user.id} deleted user {username}", "webapp")
            return jsonify({
                'success': True,
                'message': f'User {username} deleted successfully'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to delete user'
            }), 400
            
    except Exception as e:
        logger.error(f"Error deleting user: {e}")
        return jsonify({
            'success': False,
            'error': 'Failed to delete user'
        }), 500

# In-Browser Notification System
@app.route('/api/notifications')
@login_required
@limiter.limit("30 per minute")
def api_get_notifications():
    """API endpoint to get user notifications"""
    try:
        unread_only = request.args.get('unread_only', 'false').lower() == 'true'
        limit = min(int(request.args.get('limit', 50)), 100)  # Max 100 notifications
        
        notifications = db.get_user_notifications(
            username=current_user.id,
            unread_only=unread_only,
            limit=limit
        )
        
        # Format notifications for JSON response
        formatted_notifications = []
        for notification in notifications:
            device_name = notification['device_name']
            formatted_notifications.append({
                'id': notification['id'],
                'device_name': device_name,
                'display_name': db.get_device_display_name(device_name) if device_name else device_name,
                'message': notification['message'],
                'timestamp': notification['timestamp'].isoformat() if notification['timestamp'] else None,
                'is_read': bool(notification['is_read']),
                'read_at': notification['read_at'].isoformat() if notification['read_at'] else None,
                'notification_type': notification['notification_type'],
                'priority': notification['priority'],
                'event_type': notification['event_type'],
                'geofence_name': notification.get('geofence_name'),
                'rule_name': notification.get('rule_name')
            })
        
        return jsonify({
            'success': True,
            'notifications': formatted_notifications,
            'count': len(formatted_notifications)
        })
    except Exception as e:
        logger.error(f"Error getting notifications: {e}")
        return jsonify({
            'success': False,
            'error': 'Failed to retrieve notifications'
        }), 500

@app.route('/api/notifications/count')
@login_required
@limiter.limit("60 per minute")
def api_get_notification_count():
    """API endpoint to get unread notification count"""
    try:
        count = db.get_notification_count(username=current_user.id, unread_only=True)
        return jsonify({
            'success': True,
            'unread_count': count
        })
    except Exception as e:
        logger.error(f"Error getting notification count: {e}")
        return jsonify({
            'success': False,
            'error': 'Failed to get notification count'
        }), 500

@app.route('/api/notifications/<int:notification_id>/read', methods=['PUT'])
@login_required
@limiter.limit("30 per minute")
def api_mark_notification_read(notification_id):
    """API endpoint to mark notification as read"""
    try:
        if db.mark_notification_read(notification_id, current_user.id):
            return jsonify({
                'success': True,
                'message': 'Notification marked as read'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Notification not found or already read'
            }), 404
    except Exception as e:
        logger.error(f"Error marking notification as read: {e}")
        return jsonify({
            'success': False,
            'error': 'Failed to mark notification as read'
        }), 500

@app.route('/api/notifications/mark-all-read', methods=['PUT'])
@login_required
@limiter.limit("10 per minute")
def api_mark_all_notifications_read():
    """API endpoint to mark all notifications as read"""
    try:
        count = db.mark_all_notifications_read(current_user.id)
        return jsonify({
            'success': True,
            'message': f'Marked {count} notifications as read',
            'count': count
        })
    except Exception as e:
        logger.error(f"Error marking all notifications as read: {e}")
        return jsonify({
            'success': False,
            'error': 'Failed to mark notifications as read'
        }), 500

@app.route('/api/notifications', methods=['POST'])
@login_required
@limiter.limit("20 per minute")
def api_create_notification():
    """API endpoint to create a notification (for testing or system notifications)"""
    try:
        data = request.get_json()
        device_name = data.get('device_name', 'System')
        message = data.get('message', '')
        notification_type = data.get('notification_type', 'system')
        priority = data.get('priority', 'normal')
        event_type = data.get('event_type', 'info')
        
        if not message:
            return jsonify({
                'success': False,
                'error': 'Message is required'
            }), 400
        
        if db.create_notification(
            device_name=device_name,
            message=message,
            notification_type=notification_type,
            priority=priority,
            event_type=event_type
        ):
            return jsonify({
                'success': True,
                'message': 'Notification created successfully'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to create notification'
            }), 500
            
    except Exception as e:
        logger.error(f"Error creating notification: {e}")
        return jsonify({
            'success': False,
            'error': 'Failed to create notification'
        }), 500

# Service Worker Route
@app.route('/static/sw.js')
def serve_service_worker():
    """Serve the service worker with proper headers"""
    response = app.send_static_file('sw.js')
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    response.headers['Service-Worker-Allowed'] = '/'
    return response

# Push Notification API Endpoints
@app.route('/api/push/vapid-public-key', methods=['GET'])
@login_required
def api_get_vapid_public_key():
    """Get VAPID public key for push notifications"""
    try:
        # Generate or get VAPID keys - for production, store these securely
        public_key = os.getenv('VAPID_PUBLIC_KEY', 'BEl62iUYgUivxIkv69yViEuiBIa40HI0DLI5kz5Fs0cEiw7MrKp9t0pNDhLRCb7cWfpVRYvx3VfP-J3LNlLBxL4')
        return jsonify({
            'success': True,
            'publicKey': public_key
        })
    except Exception as e:
        logger.error(f"Error getting VAPID public key: {e}")
        return jsonify({
            'success': False,
            'error': 'Failed to get VAPID public key'
        }), 500

@app.route('/api/push/subscribe', methods=['POST'])
@login_required
def api_push_subscribe():
    """Subscribe to push notifications"""
    try:
        data = request.get_json()
        subscription = data.get('subscription')
        
        if not subscription or 'endpoint' not in subscription:
            return jsonify({
                'success': False,
                'error': 'Invalid subscription data'
            }), 400
        
        # Get current user ID
        user_id = current_user.id
        user_agent = request.headers.get('User-Agent', '')
        ip_address = request.remote_addr
        
        # Save subscription to database
        if db.save_push_subscription(user_id, subscription, user_agent, ip_address):
            return jsonify({
                'success': True,
                'message': 'Push subscription saved successfully'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to save push subscription'
            }), 500
            
    except Exception as e:
        logger.error(f"Error saving push subscription: {e}")
        return jsonify({
            'success': False,
            'error': 'Failed to save push subscription'
        }), 500

@app.route('/api/push/unsubscribe', methods=['POST'])
@login_required
def api_push_unsubscribe():
    """Unsubscribe from push notifications"""
    try:
        data = request.get_json()
        endpoint = data.get('endpoint')
        
        if not endpoint:
            return jsonify({
                'success': False,
                'error': 'Endpoint is required'
            }), 400
        
        # Remove subscription from database
        if db.remove_push_subscription(endpoint):
            return jsonify({
                'success': True,
                'message': 'Push subscription removed successfully'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to remove push subscription'
            }), 500
            
    except Exception as e:
        logger.error(f"Error removing push subscription: {e}")
        return jsonify({
            'success': False,
            'error': 'Failed to remove push subscription'
        }), 500

# Device Nickname Management API Endpoints
@app.route('/api/devices/nicknames', methods=['GET'])
@login_required
def api_get_device_nicknames():
    """Get all devices with their nicknames"""
    try:
        devices = db.get_all_devices_with_nicknames()
        return jsonify({
            'success': True,
            'devices': devices
        })
    except Exception as e:
        logger.error(f"Error getting device nicknames: {e}")
        return jsonify({
            'success': False,
            'error': 'Failed to get device nicknames'
        }), 500

@app.route('/api/devices/<device_name>/nickname', methods=['PUT'])
@login_required
def api_set_device_nickname(device_name):
    """Set or update a device nickname"""
    try:
        data = request.get_json()
        nickname = data.get('nickname', '').strip()
        
        if not nickname:
            return jsonify({
                'success': False,
                'error': 'Nickname cannot be empty'
            }), 400
        
        success = db.set_device_nickname(device_name, nickname)
        
        if success:
            return jsonify({
                'success': True,
                'message': f'Nickname set successfully for {device_name}'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to set nickname'
            }), 500
            
    except Exception as e:
        logger.error(f"Error setting device nickname: {e}")
        return jsonify({
            'success': False,
            'error': 'Failed to set device nickname'
        }), 500

@app.route('/api/devices/<device_name>/nickname', methods=['DELETE'])
@login_required
def api_remove_device_nickname(device_name):
    """Remove a device nickname"""
    try:
        success = db.remove_device_nickname(device_name)
        
        if success:
            return jsonify({
                'success': True,
                'message': f'Nickname removed for {device_name}'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to remove nickname'
            }), 500
            
    except Exception as e:
        logger.error(f"Error removing device nickname: {e}")
        return jsonify({
            'success': False,
            'error': 'Failed to remove device nickname'
        }), 500

@app.route('/api/devices/<device_name>/active', methods=['PUT'])
@login_required
@admin_required
def api_set_device_active(device_name):
    """Enable or disable future recording for a device."""
    try:
        data = request.get_json() or {}
        is_active = bool(data.get('is_active', True))
        if db.update_device_active(device_name, is_active):
            return jsonify({'success': True, 'message': f"Recording {'enabled' if is_active else 'disabled'} for {device_name}"})
        return jsonify({'success': False, 'error': 'Failed to update device status'}), 500
    except Exception as e:
        logger.error(f"Error updating device active status: {e}")
        return jsonify({'success': False, 'error': 'Server error'}), 500

@app.route('/api/devices/<device_name>/locations', methods=['DELETE'])
@login_required
@admin_required
def api_delete_device_locations(device_name):
    """Delete all location rows for a specific device."""
    try:
        deleted = db.delete_device_locations(device_name)
        return jsonify({'success': True, 'deleted': deleted})
    except Exception as e:
        logger.error(f"Error deleting locations for device {device_name}: {e}")
        return jsonify({'success': False, 'error': 'Failed to delete locations'}), 500

@app.route('/device-management')
@login_required
def device_management():
    """Device management page with nickname editing"""
    try:
        logger.info("Loading device management page...")
        devices = db.get_all_devices_with_nicknames()
        logger.info(f"Device management loaded with {len(devices)} devices")
        return render_template('device_management.html', devices=devices)
    except Exception as e:
        logger.error(f"Error loading device management page: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        flash('An error occurred while loading device management.', 'error')
        return redirect(url_for('dashboard'))

@app.route('/api/cache/addresses/cleanup', methods=['POST'])
@login_required
def api_cleanup_address_cache():
    """API endpoint to cleanup expired address cache entries"""
    try:
        deleted_count = db.cleanup_expired_addresses()
        return jsonify({
            'success': True,
            'message': f'Cleaned up {deleted_count} expired address cache entries',
            'deleted_count': deleted_count
        })
    except Exception as e:
        logger.error(f"Error cleaning up address cache: {e}")
        return jsonify({
            'success': False,
            'error': 'Failed to cleanup address cache'
        }), 500

@app.route('/api/cache/addresses/stats')
@login_required
def api_address_cache_stats():
    """API endpoint to get address cache statistics"""
    try:
        stats = db.get_address_cache_stats()
        return jsonify({
            'success': True,
            'stats': stats
        })
    except Exception as e:
        logger.error(f"Error getting address cache stats: {e}")
        return jsonify({
            'success': False,
            'error': 'Failed to get cache statistics'
        }), 500

@app.route('/api/backup/info')
@login_required
@admin_required
def api_backup_info():
    """Get backup system information"""
    try:
        from backup_scheduler import get_backup_info
        info = get_backup_info()
        return jsonify({
            'success': True,
            'backup_info': info
        })
    except ImportError:
        return jsonify({
            'success': False,
            'error': 'Backup scheduler not available'
        }), 500
    except Exception as e:
        logger.error(f"Error getting backup info: {e}")
        return jsonify({
            'success': False,
            'error': 'Failed to get backup information'
        }), 500

@app.route('/api/backup/create', methods=['POST'])
@login_required
@admin_required
def api_create_backup():
    """Force create a backup"""
    try:
        from backup_scheduler import create_backup
        backup_path = create_backup()
        
        if backup_path:
            return jsonify({
                'success': True,
                'message': 'Backup created successfully',
                'backup_path': backup_path
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to create backup'
            }), 500
            
    except ImportError:
        return jsonify({
            'success': False,
            'error': 'Backup scheduler not available'
        }), 500
    except Exception as e:
        logger.error(f"Error creating backup: {e}")
        return jsonify({
            'success': False,
            'error': 'Failed to create backup'
        }), 500

# Automatic cache cleanup - run at application startup and periodically
def cleanup_caches_on_startup():
    """Run cache cleanup on application startup"""
    try:
        deleted_count = db.cleanup_expired_addresses()
        if deleted_count > 0:
            logger.info(f"Startup: Cleaned up {deleted_count} expired address cache entries")
    except Exception as e:
        logger.error(f"Error during startup cache cleanup: {e}")

# Run cleanup on startup
cleanup_caches_on_startup()

# Start the top locations cache scheduler
try:
    start_scheduler()
    logger.info("Top locations cache scheduler started successfully")
except Exception as e:
    logger.error(f"Failed to start top locations cache scheduler: {e}")

# Shutdown handler for scheduler
import atexit
atexit.register(stop_scheduler)

if __name__ == '__main__':
    try:
        app.run(host='0.0.0.0', port=5000, debug=False)
    finally:
        stop_scheduler()