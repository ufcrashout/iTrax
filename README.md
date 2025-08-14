# iTrax

<div align="center">

**A comprehensive location tracking and analytics platform for iPhone devices using iCloud Find My**

*Created by UF Cra⚡︎hOut*

[![License: MIT](https://img.shields.io/badge/License-Educational-blue.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/Python-3.8+-green.svg)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-2.0+-red.svg)](https://flask.palletsprojects.com/)

</div>

---

## 🌟 Overview

iTrax is a powerful, secure web application that provides comprehensive location tracking and analytics for iPhone devices through the iCloud Find My service. Built with Flask and featuring a modern, responsive interface, iTrax offers real-time location monitoring, advanced analytics, geofencing, notifications, and much more.

### ✨ Key Highlights

- 🔐 **Enterprise-grade security** with CSRF protection and session management
- 📊 **Advanced analytics** with address resolution and location intelligence
- 🗺️ **Interactive mapping** with multiple visualization modes
- 🏠 **Geofencing & alerts** for location-based notifications
- 📱 **Responsive design** that works on all devices
- 🚀 **Easy deployment** with systemd service integration

---

## 🎯 Core Features

### 🔒 Authentication & User Management
- **Secure login system** with MySQL database authentication
- **Multi-user support** with individual user accounts
- **Role-based access control** with admin and regular user roles
- **User management interface** for creating, editing, and deleting users
- **Admin promotion system** for elevating user privileges
- **Account status management** (active/disabled users)
- **Password management** with secure hashing (SHA-256)
- **CSRF protection** on all forms and API endpoints
- **Rate limiting** to prevent abuse and API overuse
- **Session management** with automatic cleanup
- **Environment-based configuration** for secure credential storage

### 📍 Location Tracking
- **Real-time location updates** from iCloud Find My
- **Multiple device support** with individual device tracking
- **Historical location data** with unlimited retention options
- **Automatic reconnection** and error recovery
- **Smart rate limiting** with exponential backoff

### 🗺️ Interactive Dashboard
- **Live location map** with Leaflet.js integration
- **Device clustering** to avoid overlapping markers
- **Movement paths** showing travel routes between locations
- **Time-based filtering** (24-hour, custom date ranges)
- **Device filtering** to focus on specific devices
- **Auto-refresh** every 5 minutes with manual refresh option

### 📊 Advanced Analytics
- **Address resolution** using reverse geocoding
- **Time spent analysis** at each location
- **Distance calculations** and travel patterns
- **Location grouping** by proximity
- **Statistical insights** and device summaries
- **Export capabilities** (JSON, CSV, KML formats)

### 🔥 Location Heatmaps
- **Interactive heatmap visualization** showing frequently visited areas
- **Configurable time ranges** (7, 30, 90 days or custom)
- **Device-specific heatmaps** or combined view
- **Intensity-based coloring** based on visit frequency
- **Hotspot identification** with ranking system

### ⏮️ Historical Playback
- **Timeline-based playback** of location history
- **Customizable date ranges** with precise time controls
- **Animated movement visualization** with speed controls
- **Multi-device playback** support
- **Playback speed adjustment** (0.5x to 4x speed)
- **Export playback data** for external analysis

### 🏠 Geofencing System
- **Create custom geofences** with point-and-click interface
- **Circular geofences** with configurable radius
- **Entry/exit event detection** with real-time monitoring
- **Device-specific geofence rules** or global rules
- **Geofence event history** with detailed logs
- **Visual geofence overlay** on maps

### 🔔 Smart Notifications & In-Browser Alerts
- **Site-wide real-time notifications** - Works on every page, not just dashboard
- **Global notification bell** with unread count in navigation bar on all pages
- **Interactive notification dropdown** with mark as read functionality
- **Consistent cross-page experience** - Same notification system across all views
- **Rule-based notification system** with multiple triggers
- **Geofence entry/exit alerts** for specific locations
- **Device activity notifications** for movement detection
- **Multiple delivery methods** (browser, email, webhook, SMS)
- **Priority-based notifications** (low, normal, high, urgent)
- **Visual notification indicators** with color coding and animations
- **Notification history** with delivery status tracking
- **Auto-polling** for new notifications every 30 seconds on all pages
- **Customizable notification rules** per device
- **Mark all as read** functionality
- **Time-based notification display** (just now, 5m ago, etc.)
- **Shared notification JavaScript component** for consistent behavior

### 🔍 Search & Bookmarks
- **Address-based location search** with autocomplete
- **Coordinate search** for precise location lookup
- **Location bookmarking** system for frequently accessed places
- **Nearby location discovery** within configurable radius
- **Search history** with quick access to recent searches
- **Bookmark management** with custom naming and descriptions

### 📈 Travel Reports
- **Comprehensive travel analysis** with daily/weekly/monthly views
- **Distance tracking** with total miles/kilometers traveled
- **Location visit summaries** with duration analysis
- **Travel pattern insights** and statistics
- **Custom report generation** for specific date ranges
- **Export reports** in multiple formats

### 📋 GPS Logs Viewer
- **Raw location data browser** with filtering capabilities
- **Pagination support** for large datasets
- **Device filtering** and date range selection
- **Location coordinate display** with precision
- **Timestamp information** in local timezone
- **Data export** functionality for analysis

### 👥 User Management System (Admin Only)
- **Complete user account management** with web interface
- **User creation and deletion** with form validation
- **Admin privilege management** - promote/demote users
- **Account status control** - enable/disable user accounts
- **Password management** - reset passwords for any user
- **User activity tracking** - view creation date and last login
- **Visual status indicators** - admin badges, activity status
- **Self-protection features** - admins cannot disable themselves
- **Audit logging** - all admin actions are logged
- **Command-line tools** for server-side user management

---

## 🛠️ Technical Architecture

### 📊 Database System
- **SQLite database** for reliable data storage
- **Automatic migrations** from legacy JSON data
- **Built-in backup system** with configurable retention
- **Database optimization tools** for performance
- **Comprehensive logging** with structured data

### 🔧 API Endpoints
- **RESTful API design** with consistent response formats
- **Authentication required** for all sensitive endpoints
- **Rate limiting** on all API endpoints
- **Health check endpoint** for monitoring
- **Comprehensive error handling** with detailed responses

#### Available API Endpoints:
```
# System & Monitoring
GET  /api/health           - System health check
GET  /api/stats            - Location and device statistics
GET  /api/devices          - List of tracked devices
GET  /api/logs             - Application logs

# Location Data
GET  /api/locations        - Location data with filtering
GET  /api/heatmap/stats    - Heatmap statistics
GET  /api/playback/data    - Historical playback data
GET  /api/nearby           - Find nearby locations
GET  /api/gps-logs/export  - Export GPS logs

# Geofencing
GET  /api/geofences        - Geofence management
POST /api/geofences        - Create new geofence
DEL  /api/geofences/<id>   - Delete geofence
GET  /api/geofence-events  - Geofence event history

# Notifications & Alerts
GET  /api/notification-rules - Notification rule management
POST /api/notification-rules - Create notification rule
DEL  /api/notification-rules/<id> - Delete rule
GET  /api/recent-notifications - Recent notification history
GET  /api/notifications     - Get user notifications (with filtering)
GET  /api/notifications/count - Get unread notification count
PUT  /api/notifications/<id>/read - Mark notification as read
PUT  /api/notifications/mark-all-read - Mark all notifications as read
POST /api/notifications     - Create notification (testing/system)

# Search & Bookmarks
GET  /api/search           - Location search
GET  /api/bookmarks        - Bookmark management
POST /api/bookmarks        - Create bookmark
DEL  /api/bookmarks/<id>   - Delete bookmark

# Reports
GET  /api/travel-report    - Generate travel reports

# User Management (Admin Only)
GET  /api/users            - List all users
POST /api/users            - Create new user
PUT  /api/users/<username>/admin   - Update admin status
PUT  /api/users/<username>/active  - Enable/disable user
PUT  /api/users/<username>/password - Change user password
DEL  /api/users/<username> - Delete user
```

### 🔄 Background Services
- **Location tracker service** with automatic recovery
- **Database cleanup service** for old data management
- **Session management** with automatic renewal
- **Geofence monitoring** with real-time violation detection
- **Notification delivery system** with retry logic

---

## 🚀 Installation & Setup

### 📋 Prerequisites
- Python 3.8 or higher
- iCloud account with Find My enabled
- Network access for iCloud API calls

### 📦 Quick Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd iTrax
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment variables**
   ```bash
   cp env_example.txt .env
   ```
   
   Edit `.env` with your configuration:
   ```env
   # iCloud Credentials
   ICLOUD_EMAIL=your_icloud_email@icloud.com
   ICLOUD_PASSWORD=your_icloud_password
   
   # Security Keys
   SECRET_KEY=your_generated_secret_key
   ADMIN_USERNAME=admin
   ADMIN_PASSWORD=your_secure_password
   
   # Database Configuration
   DB_HOST=localhost
   DB_USER=root
   DB_PASSWORD=your_db_password
   DB_NAME=itrax
   DATABASE_CLEANUP_DAYS=30
   DATABASE_BACKUP_RETENTION=5
   
   # Tracking Configuration
   TRACKING_INTERVAL=600
   MAX_DELAY=3600
   
   # Notification Settings (Optional)
   SMTP_SERVER=smtp.gmail.com
   SMTP_PORT=587
   SMTP_EMAIL=notifications@yourdomain.com
   SMTP_PASSWORD=your_email_password
   ```

4. **Generate secure secret key**
   ```python
   import secrets
   print(secrets.token_hex(32))
   ```

### 🔧 Deployment Options

#### Option 1: Quick Start Script (Recommended)
```bash
# Start both tracker and web app
python start.py

# Start components separately
python start.py --tracker    # Tracker only
python start.py --webapp     # Web app only  
python start.py --check      # Dependency check
```

#### Option 2: Manual Deployment
```bash
# Terminal 1: Location Tracker
python tracker.py

# Terminal 2: Web Application
python app.py
```

#### Option 3: Systemd Service (Production)
```bash
# Copy service file
sudo cp icloud-tracker.service /etc/systemd/system/itrax.service

# Edit service file with correct paths
sudo nano /etc/systemd/system/itrax.service

# Enable and start service
sudo systemctl enable itrax
sudo systemctl start itrax
sudo systemctl status itrax
```

### 🌐 Access the Application
- **Web Interface**: http://localhost:5000
- **Default Login**: admin / (your configured password)
- **Health Check**: http://localhost:5000/api/health

---

## 🔧 Database Management

iTrax uses SQLite for robust data storage with comprehensive management tools.

### 🛠️ Database Tools

```bash
# Database Management
python database_tools.py stats      # View database statistics
python database_tools.py locations --limit 20  # View recent locations
python database_tools.py cleanup --days 30     # Clean up old data
python database_tools.py backup     # Create database backup
python database_tools.py logs --level INFO --limit 50  # View logs
python database_tools.py export --format json  # Export data (JSON/CSV)
python database_tools.py optimize   # Optimize database performance
python database_tools.py devices    # Show device information

# User Management
python database_tools.py create-user           # Create new user (interactive)
python database_tools.py create-user --username john --admin  # Create admin user
python database_tools.py list-users            # List all users with status
python database_tools.py delete-user --username john         # Delete user
python database_tools.py change-password --username john     # Change password
python database_tools.py promote-admin --username john       # Promote to admin
python database_tools.py revoke-admin --username john        # Revoke admin
```

### 📊 Database Schema

| Table | Purpose | Key Fields |
|-------|---------|------------|
| `users` | User accounts & authentication | `id`, `username`, `password_hash`, `is_admin`, `is_active` |
| `devices` | Device information | `id`, `device_name`, `model`, `last_seen` |
| `locations` | Location tracking data | `id`, `device_name`, `latitude`, `longitude`, `timestamp` |
| `sessions` | iCloud session management | `id`, `session_data`, `created_at`, `expires_at` |
| `logs` | Application logging | `id`, `level`, `message`, `timestamp`, `source` |
| `geofences` | Geofence definitions | `id`, `name`, `center_lat`, `center_lng`, `radius` |
| `geofence_events` | Geofence violations | `id`, `geofence_id`, `device_name`, `event_type` |
| `notification_rules` | Alert configurations | `id`, `name`, `trigger_type`, `delivery_method` |
| `notifications` | Notification history | `id`, `rule_id`, `message`, `delivered_at` |
| `bookmarks` | Saved locations | `id`, `name`, `latitude`, `longitude`, `description` |

---

## ⚙️ Configuration Options

### 🔧 Environment Variables

| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `ICLOUD_EMAIL` | iCloud account email | Required | `user@icloud.com` |
| `ICLOUD_PASSWORD` | iCloud account password | Required | `password123` |
| `SECRET_KEY` | Flask secret key | Required | `hex_string_64_chars` |
| `ADMIN_USERNAME` | Admin login username | `admin` | `admin` |
| `ADMIN_PASSWORD` | Admin login password | Required | `SecurePass123!` |
| `TRACKING_INTERVAL` | Location check frequency | `600` | `300` (5 minutes) |
| `MAX_DELAY` | Max rate limit delay | `3600` | `1800` (30 minutes) |
| `DATABASE_CLEANUP_DAYS` | Data retention period | `30` | `90` |
| `DATABASE_BACKUP_RETENTION` | Backup file count | `5` | `10` |
| `DB_HOST` | Database host | `localhost` | `mysql.example.com` |
| `DB_USER` | Database user | `root` | `itrax_user` |
| `DB_PASSWORD` | Database password | Required | `db_password` |
| `DB_NAME` | Database name | `itrax` | `location_db` |

### 📱 Device Configuration

- **Find My**: Must be enabled on all tracked devices
- **Location Services**: Required for accurate tracking
- **iCloud**: Devices must be signed into the same iCloud account
- **Network**: Devices need internet connection for location updates

---

## 🔍 Usage Guide

### 📊 Dashboard
The main dashboard provides:
- **Real-time map** showing current device locations
- **Movement tracking** with 24-hour path visualization
- **Device statistics** including location count and last update
- **Quick filters** for date ranges and specific devices
- **Auto-refresh** functionality with manual refresh option

### 📈 Analytics
Access comprehensive analytics for each device:
- **Location timeline** with address resolution
- **Time spent analysis** at each location
- **Travel distance calculations**
- **Daily activity patterns**
- **Data export** in JSON, CSV, or KML formats

### 🔥 Heatmaps
Visualize location patterns:
- **Frequency-based coloring** showing most visited areas
- **Time range selection** from 7 days to custom periods
- **Device filtering** for individual or combined views
- **Interactive map** with zoom and pan capabilities

### ⏮️ Playback
Review historical movement:
- **Timeline controls** for specific date ranges
- **Playback speed adjustment** from 0.5x to 4x
- **Multi-device tracking** with color-coded paths
- **Export capabilities** for external analysis

### 🏠 Geofences
Set up location-based alerts:
- **Click-and-drag creation** directly on the map
- **Configurable radius** from 50m to 10km
- **Entry/exit notifications** with immediate alerts
- **Event history** with detailed logs

### 🔔 Notifications
Configure smart alerts:
- **Multiple trigger types**: geofence, movement, device status
- **Delivery methods**: email, webhook, SMS (with configuration)
- **Device-specific rules** or global notifications
- **Delivery status tracking** with retry logic

### 🔍 Search & Bookmarks
Find and save locations:
- **Address search** with autocomplete suggestions
- **Coordinate lookup** for precise locations
- **Bookmark system** for frequently accessed places
- **Nearby search** within configurable radius

---

## 🔐 Security Features

### 🛡️ Authentication & Authorization
- **Session-based authentication** with Flask-Login
- **CSRF protection** on all forms and state-changing operations
- **Password hashing** using secure algorithms
- **Session timeout** with configurable expiration

### 🚦 Rate Limiting
- **API endpoint protection** to prevent abuse
- **Configurable limits** per endpoint and user
- **Automatic throttling** with exponential backoff
- **Request tracking** and monitoring

### 🔒 Data Protection
- **Environment-based configuration** for sensitive data
- **Database encryption** options available
- **Secure session storage** with proper cleanup
- **Input validation** and sanitization throughout

### 📝 Security Best Practices
- **Never commit credentials** - Use environment variables
- **Enable 2FA** on your iCloud account
- **Use strong passwords** for admin access
- **Regular security updates** for dependencies
- **Network security** - Run on trusted networks only
- **Database backups** with secure storage
- **Log monitoring** for suspicious activity

---

## 🔧 API Documentation

### 🌐 Authentication
All API endpoints (except `/api/health`) require authentication. Include session cookies or use the web interface login.

### 📊 Response Format
```json
{
  "success": true,
  "data": { ... },
  "message": "Operation successful",
  "timestamp": "2025-01-13T10:30:00Z"
}
```

### 🔍 Error Handling
```json
{
  "success": false,
  "error": "Error description",
  "code": 400,
  "timestamp": "2025-01-13T10:30:00Z"
}
```

### 📍 Location Data Format
```json
{
  "id": 12345,
  "device_name": "iPhone 15 Pro",
  "latitude": 40.7128,
  "longitude": -74.0060,
  "timestamp": "2025-01-13T10:30:00Z",
  "accuracy": 5.0,
  "address": "New York, NY, USA"
}
```

---

## 🔍 Troubleshooting

### ❌ Common Issues

#### Authentication Problems
```bash
# Check credentials
python start.py --check

# View logs
python database_tools.py logs --level ERROR

# Reset session
rm -f session_cache.json
```

#### No Location Data
- Verify Find My is enabled on devices
- Check iCloud credentials are correct
- Ensure devices are online and connected
- Review tracker logs for errors

#### Database Issues
```bash
# Check database integrity
python database_tools.py integrity

# Optimize database
python database_tools.py optimize

# View database stats
python database_tools.py stats
```

#### Performance Issues
```bash
# Clean old data
python database_tools.py cleanup --days 30

# Optimize database
python database_tools.py optimize

# Check disk space and memory usage
```

### 📊 Monitoring

#### Health Check
```bash
curl http://localhost:5000/api/health
```

#### Log Analysis
```bash
# Application logs
tail -f app.log

# Database logs
python database_tools.py logs --limit 100

# System logs (if using systemd)
journalctl -u itrax -f
```

---

## 🏗️ Development

### 🧪 Development Setup
```bash
# Clone and setup
git clone <repo-url>
cd iTrax
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Setup development environment
cp env_example.txt .env
# Configure .env for development

# Run in development mode
export FLASK_ENV=development
python app.py
```

### 🏗️ Project Structure
```
iTrax/
├── 📄 app.py                 # Main Flask application
├── 📄 tracker.py             # iCloud location tracker
├── 📄 analytics.py           # Advanced analytics module
├── 📄 database.py            # Database management
├── 📄 database_tools.py      # Database utilities
├── 📄 start.py               # Application launcher
├── 📄 config.py              # Configuration management
├── 📄 gps_maintenance.py     # GPS data maintenance
├── 📄 requirements.txt       # Python dependencies
├── 📄 env_example.txt        # Environment template
├── 📄 icloud-tracker.service # Systemd service file
├── 📄 README.md              # This documentation
├── 📂 templates/             # HTML templates
│   ├── 🎨 dashboard.html     # Main dashboard
│   ├── 🎨 analytics.html     # Analytics interface
│   ├── 🎨 heatmap.html       # Heatmap visualization
│   ├── 🎨 playback.html      # Historical playback
│   ├── 🎨 geofences.html     # Geofence management
│   ├── 🎨 notifications.html # Notification rules
│   ├── 🎨 search.html        # Search & bookmarks
│   ├── 🎨 reports.html       # Travel reports
│   ├── 🎨 gps_logs.html      # GPS log viewer
│   ├── 🎨 device_analytics.html # Device-specific analytics
│   ├── 🎨 user_management.html # User management (admin)
│   ├── 🎨 login.html         # Login page
│   ├── 🎨 404.html           # Error page
│   └── 🎨 500.html           # Server error page
├── 📂 static/                # Static assets
│   └── 📂 js/                # JavaScript files
│       └── 📄 notifications.js # Cross-page notification system
└── 📊 itrax.db               # SQLite database (auto-created)
```

### 🔧 Technology Stack
- **Backend**: Python 3.8+, Flask 2.0+
- **Database**: SQLite 3 (with MySQL support)
- **Frontend**: HTML5, CSS3, JavaScript (ES6+)
- **Mapping**: Leaflet.js with OpenStreetMap
- **Charts**: Chart.js for analytics visualization
- **Styling**: Bootstrap 5 for responsive design
- **Authentication**: Flask-Login with session management
- **Security**: Flask-WTF for CSRF protection
- **Rate Limiting**: Flask-Limiter
- **Geocoding**: Geopy with Nominatim
- **Notifications**: SMTP, Webhooks

---

## 🤝 Contributing

We welcome contributions to iTrax! Here's how you can help:

### 🔄 Development Process
1. **Fork** the repository
2. **Create** a feature branch (`git checkout -b feature/amazing-feature`)
3. **Commit** your changes (`git commit -m 'Add amazing feature'`)
4. **Push** to the branch (`git push origin feature/amazing-feature`)
5. **Open** a Pull Request

### 🧪 Testing
```bash
# Run basic tests
python start.py --check

# Test database connectivity
python database_tools.py stats

# Test API endpoints
curl http://localhost:5000/api/health
```

### 📝 Code Standards
- Follow PEP 8 for Python code style
- Use type hints where appropriate
- Include docstrings for functions and classes
- Write comprehensive commit messages
- Test all new features thoroughly

---

## 📄 License

This project is provided for **educational purposes only**. Users are responsible for ensuring compliance with:
- Apple's Terms of Service
- Applicable privacy laws (GDPR, CCPA, etc.)
- Local regulations regarding location tracking

The developers are not responsible for any misuse of this application.

---

## ⚠️ Disclaimer

**Important**: This application is provided as-is for educational and personal use only. Please ensure you:
- Have proper authorization to track the devices
- Comply with all applicable laws and regulations
- Use the application responsibly and ethically
- Secure your installation and credentials properly

---

## 📞 Support

- **Documentation**: This README and inline code comments
- **Issues**: Use GitHub Issues for bug reports and feature requests  
- **Security**: Report security vulnerabilities privately
- **Updates**: Check releases for new features and security updates

---

<div align="center">

**iTrax** - *Comprehensive Location Intelligence Platform*

*Created with ❤️ by UF Cra⚡︎hOut*

[⭐ Star this project](https://github.com/your-username/iTrax) • [🐛 Report Bug](https://github.com/your-username/iTrax/issues) • [💡 Request Feature](https://github.com/your-username/iTrax/issues)

</div>