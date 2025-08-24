#!/usr/bin/env python3
"""
Database Management Tools for iTrax

This script provides utilities for database maintenance, analysis, and migration.
"""

import argparse
import sys
import getpass
import hashlib
from datetime import datetime, timedelta
from database import db
from config import Config

def show_statistics():
    """Display database statistics"""
    print("📊 Database Statistics")
    print("=" * 40)
    
    try:
        stats = db.get_statistics()
        
        print(f"Total Locations: {stats['total_locations']:,}")
        print(f"Unique Devices: {stats['unique_devices']}")
        print(f"Today's Locations: {stats['today_count']}")
        
        if stats['last_update']:
            print(f"Last Update: {stats['last_update']}")
        else:
            print("Last Update: Never")
        
        print("\n📱 Devices:")
        for device in stats['devices']:
            print(f"  • {device['device_name']}: {device['location_count']} locations")
            
    except Exception as e:
        print(f"❌ Error getting statistics: {e}")

def show_devices():
    """Show all devices in database with details"""
    print("📱 Device Details")
    print("=" * 40)
    
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT d.device_name, d.first_seen, d.last_seen, d.is_active,
                       COUNT(l.id) as location_count,
                       MAX(l.timestamp) as last_location
                FROM devices d
                LEFT JOIN locations l ON d.id = l.device_id
                GROUP BY d.id, d.device_name
                ORDER BY d.last_seen DESC
            ''')
            
            devices = cursor.fetchall()
            
            if not devices:
                print("No devices found in database")
                return
                
            for device in devices:
                status = "🟢 Active" if device['is_active'] else "🔴 Inactive"
                print(f"📱 {device['device_name']} ({status})")
                print(f"   📅 First Seen: {device['first_seen']}")
                print(f"   📅 Last Seen: {device['last_seen']}")
                print(f"   📍 Locations: {device['location_count']}")
                if device['last_location']:
                    print(f"   🕐 Last Location: {device['last_location']}")
                print()
                
    except Exception as e:
        print(f"❌ Error getting device details: {e}")

def show_recent_locations(limit=10):
    """Show recent location data"""
    print(f"📍 Recent Locations (last {limit})")
    print("=" * 40)
    
    try:
        locations = db.get_locations(limit=limit)
        
        for loc in locations:
            print(f"📱 {loc['device_name']}")
            print(f"   📍 {loc['latitude']:.6f}, {loc['longitude']:.6f}")
            print(f"   ⏰ {loc['timestamp']}")
            print()
            
    except Exception as e:
        print(f"❌ Error getting locations: {e}")

def cleanup_old_data(days=30):
    """Clean up old data"""
    print(f"🧹 Cleaning up data older than {days} days...")
    
    try:
        # Get count before cleanup
        stats_before = db.get_statistics()
        
        # Perform cleanup
        db.cleanup_old_data(days_to_keep=days)
        
        # Get count after cleanup
        stats_after = db.get_statistics()
        
        deleted = stats_before['total_locations'] - stats_after['total_locations']
        print(f"✅ Cleaned up {deleted:,} old location records")
        
    except Exception as e:
        print(f"❌ Error during cleanup: {e}")

def backup_database():
    """Create a database backup using the new backup system"""
    print("💾 Creating database backup...")
    
    try:
        from backup_scheduler import create_backup
        backup_path = create_backup()
        
        if backup_path:
            print(f"✅ Database backed up to: {backup_path}")
            
            # Show backup file size
            import os
            if os.path.exists(backup_path):
                size_mb = os.path.getsize(backup_path) / (1024 * 1024)
                print(f"📊 Backup size: {size_mb:.2f} MB")
        else:
            print("❌ Backup failed")
    except ImportError:
        # Fallback to old method if backup_scheduler not available
        backup_path = db.backup_database()
        if backup_path:
            print(f"✅ Database backed up to: {backup_path}")
        else:
            print("❌ Backup failed")
    except Exception as e:
        print(f"❌ Error creating backup: {e}")
        
def backup_info():
    """Show backup system information"""
    print("📊 Backup System Information")
    print("=" * 50)
    
    try:
        from backup_scheduler import get_backup_info
        info = get_backup_info()
        
        print(f"📁 Backup Directory: {info['backup_dir']}")
        print(f"📦 Total Backups: {info['total_count']}")
        print(f"💾 Total Size: {info['total_size_mb']} MB")
        print(f"⏰ Retention: {info['retention_days']} days")
        print()
        
        if info['backups']:
            print("Recent Backups:")
            print("-" * 50)
            for backup in info['backups'][:10]:  # Show last 10
                age = f"{backup['age_days']} days ago" if backup['age_days'] > 0 else "today"
                print(f"  {backup['filename']} - {backup['size_mb']} MB ({age})")
        else:
            print("No backups found")
            
    except ImportError:
        print("❌ New backup system not available")
    except Exception as e:
        print(f"❌ Error getting backup info: {e}")

def show_logs(level="INFO", limit=20):
    """Show recent logs"""
    print(f"📝 Recent {level} Logs (last {limit})")
    print("=" * 40)
    
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT level, message, timestamp, source
                FROM logs
                WHERE level = %s
                ORDER BY timestamp DESC
                LIMIT %s
            ''', (level, limit))
            
            logs = cursor.fetchall()
            
            for log in logs:
                print(f"[{log['timestamp']}] {log['level']} ({log['source']})")
                print(f"  {log['message']}")
                print()
                
    except Exception as e:
        print(f"❌ Error getting logs: {e}")

def export_data(format="json"):
    """Export location data"""
    print(f"📤 Exporting location data to {format.upper()}...")
    
    try:
        locations = db.get_locations(limit=10000)  # Export last 10k records
        
        if format.lower() == "json":
            import json
            filename = f"export_locations_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(filename, 'w') as f:
                json.dump(locations, f, indent=2)
            print(f"✅ Data exported to {filename}")
            
        elif format.lower() == "csv":
            import csv
            filename = f"export_locations_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            with open(filename, 'w', newline='') as f:
                if locations:
                    writer = csv.DictWriter(f, fieldnames=locations[0].keys())
                    writer.writeheader()
                    writer.writerows(locations)
            print(f"✅ Data exported to {filename}")
            
        else:
            print("❌ Unsupported format. Use 'json' or 'csv'")
            
    except Exception as e:
        print(f"❌ Error exporting data: {e}")

def optimize_database():
    """Optimize database performance"""
    print("⚡ Optimizing database...")
    
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Analyze tables for better query planning
            cursor.execute("ANALYZE")
            
            # Vacuum to reclaim space
            cursor.execute("VACUUM")
            
            # Rebuild indexes
            cursor.execute("REINDEX")
            
            conn.commit()
            print("✅ Database optimized successfully")
            
    except Exception as e:
        print(f"❌ Error optimizing database: {e}")

def create_user(username=None, password=None, interactive=True):
    """Create a new user account"""
    print("👤 Creating New User Account")
    print("=" * 40)
    
    try:
        # Get username
        if not username and interactive:
            username = input("Enter username: ").strip()
        
        if not username:
            print("❌ Username is required")
            return False
            
        # Check if user already exists
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
            if cursor.fetchone():
                print(f"❌ User '{username}' already exists")
                return False
        
        # Get password
        if not password and interactive:
            password = getpass.getpass("Enter password: ")
            confirm_password = getpass.getpass("Confirm password: ")
            
            if password != confirm_password:
                print("❌ Passwords don't match")
                return False
        
        if not password:
            print("❌ Password is required")
            return False
        
        # Ask if user should be admin
        is_admin = False
        if interactive:
            admin_choice = input("Make this user an admin? (y/N): ").lower()
            is_admin = admin_choice == 'y'
        
        # Create user using database function
        if db.create_user(username, password, is_admin):
            admin_text = " as admin" if is_admin else ""
            print(f"✅ User '{username}' created successfully{admin_text}")
            return True
        else:
            print(f"❌ Failed to create user '{username}' (username may already exist)")
            return False
        
    except Exception as e:
        print(f"❌ Error creating user: {e}")
        return False

def list_users():
    """List all users in the database"""
    print("👥 User Accounts")
    print("=" * 40)
    
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT username, created_at, last_login
                FROM users
                ORDER BY created_at DESC
            ''')
            
            users = cursor.fetchall()
            
            if not users:
                print("No users found in database")
                return
                
            for user in users:
                print(f"👤 {user['username']}")
                print(f"   📅 Created: {user['created_at']}")
                if user['last_login']:
                    print(f"   🔑 Last Login: {user['last_login']}")
                else:
                    print(f"   🔑 Last Login: Never")
                print()
                
    except Exception as e:
        print(f"❌ Error listing users: {e}")

def delete_user(username=None, interactive=True):
    """Delete a user account"""
    print("🗑️  Delete User Account")
    print("=" * 40)
    
    try:
        # Get username
        if not username and interactive:
            username = input("Enter username to delete: ").strip()
        
        if not username:
            print("❌ Username is required")
            return False
            
        # Check if user exists
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
            if not cursor.fetchone():
                print(f"❌ User '{username}' not found")
                return False
        
        # Confirm deletion
        if interactive:
            confirm = input(f"Are you sure you want to delete user '{username}'? (y/N): ")
            if confirm.lower() != 'y':
                print("❌ Deletion cancelled")
                return False
        
        # Delete user using database function
        if db.delete_user(username):
            print(f"✅ User '{username}' deleted successfully")
        else:
            print(f"❌ Failed to delete user '{username}'")
        return True
        
    except Exception as e:
        print(f"❌ Error deleting user: {e}")
        return False

def change_password(username=None, interactive=True):
    """Change user password"""
    print("🔐 Change User Password")
    print("=" * 40)
    
    try:
        # Get username
        if not username and interactive:
            username = input("Enter username: ").strip()
        
        if not username:
            print("❌ Username is required")
            return False
            
        # Check if user exists
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
            if not cursor.fetchone():
                print(f"❌ User '{username}' not found")
                return False
        
        # Get new password
        if interactive:
            password = getpass.getpass("Enter new password: ")
            confirm_password = getpass.getpass("Confirm new password: ")
            
            if password != confirm_password:
                print("❌ Passwords don't match")
                return False
        else:
            password = getpass.getpass(f"Enter new password for {username}: ")
        
        if not password:
            print("❌ Password is required")
            return False
            
        # Hash password
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        
        # Update password using database function
        if db.change_user_password(username, password):
            print(f"✅ Password updated for user '{username}'")
        else:
            print(f"❌ Failed to update password for user '{username}'")
        return True
        
    except Exception as e:
        print(f"❌ Error changing password: {e}")
        return False

def list_users():
    """List all users in the database"""
    print("👥 User List")
    print("=" * 60)
    
    try:
        users = db.get_all_users()
        
        if not users:
            print("No users found in the database.")
            return
        
        print(f"{'ID':<5} {'Username':<20} {'Admin':<8} {'Active':<8} {'Created':<12} {'Last Login'}")
        print("-" * 60)
        
        for user in users:
            admin_status = "Yes" if user['is_admin'] else "No"
            active_status = "Yes" if user['is_active'] else "No"
            created = user['created_at'].strftime('%Y-%m-%d') if user['created_at'] else 'N/A'
            last_login = user['last_login'].strftime('%Y-%m-%d') if user['last_login'] else 'Never'
            
            print(f"{user['id']:<5} {user['username']:<20} {admin_status:<8} {active_status:<8} {created:<12} {last_login}")
        
        print(f"\nTotal users: {len(users)}")
        
    except Exception as e:
        print(f"❌ Error listing users: {e}")

def promote_admin(username=None, interactive=True):
    """Promote user to admin"""
    print("👑 Promote User to Admin")
    print("=" * 40)
    
    try:
        # Get username
        if not username and interactive:
            username = input("Enter username to promote: ").strip()
        
        if not username:
            print("❌ Username is required")
            return False
        
        # Check if user exists
        user = db.get_user(username)
        if not user:
            print(f"❌ User '{username}' not found")
            return False
        
        if user['is_admin']:
            print(f"ℹ️  User '{username}' is already an admin")
            return True
        
        # Confirm promotion
        if interactive:
            confirm = input(f"Promote user '{username}' to admin? (y/N): ")
            if confirm.lower() != 'y':
                print("❌ Operation cancelled")
                return False
        
        # Promote user
        if db.update_user_admin_status(username, True):
            print(f"✅ User '{username}' promoted to admin")
            return True
        else:
            print(f"❌ Failed to promote user '{username}'")
            return False
            
    except Exception as e:
        print(f"❌ Error promoting user: {e}")
        return False

def revoke_admin(username=None, interactive=True):
    """Revoke admin privileges from user"""
    print("👑 Revoke Admin Privileges")
    print("=" * 40)
    
    try:
        # Get username
        if not username and interactive:
            username = input("Enter username to revoke admin from: ").strip()
        
        if not username:
            print("❌ Username is required")
            return False
        
        # Check if user exists
        user = db.get_user(username)
        if not user:
            print(f"❌ User '{username}' not found")
            return False
        
        if not user['is_admin']:
            print(f"ℹ️  User '{username}' is not an admin")
            return True
        
        # Confirm revocation
        if interactive:
            confirm = input(f"Revoke admin privileges from user '{username}'? (y/N): ")
            if confirm.lower() != 'y':
                print("❌ Operation cancelled")
                return False
        
        # Revoke admin privileges
        if db.update_user_admin_status(username, False):
            print(f"✅ Admin privileges revoked from user '{username}'")
            return True
        else:
            print(f"❌ Failed to revoke admin privileges from user '{username}'")
            return False
            
    except Exception as e:
        print(f"❌ Error revoking admin: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description='iTrax Database Management Tools')
    parser.add_argument('command', choices=[
        'stats', 'devices', 'locations', 'cleanup', 'backup', 'backup-info', 'logs', 'export', 'optimize',
        'create-user', 'list-users', 'delete-user', 'change-password', 'promote-admin', 'revoke-admin'
    ], help='Command to execute')
    
    parser.add_argument('--limit', type=int, default=10, help='Limit for queries')
    parser.add_argument('--days', type=int, default=30, help='Days for cleanup')
    parser.add_argument('--level', default='INFO', help='Log level')
    parser.add_argument('--format', default='json', help='Export format (json/csv)')
    parser.add_argument('--username', help='Username for user management commands')
    parser.add_argument('--password', help='Password for non-interactive user creation')
    parser.add_argument('--admin', action='store_true', help='Create user as admin (for create-user command)')
    
    args = parser.parse_args()
    
    print("🔧 iTrax Database Tools")
    print("=" * 40)
    
    if args.command == 'stats':
        show_statistics()
    elif args.command == 'devices':
        show_devices()
    elif args.command == 'locations':
        show_recent_locations(args.limit)
    elif args.command == 'cleanup':
        cleanup_old_data(args.days)
    elif args.command == 'backup':
        backup_database()
    elif args.command == 'backup-info':
        backup_info()
    elif args.command == 'logs':
        show_logs(args.level, args.limit)
    elif args.command == 'export':
        export_data(args.format)
    elif args.command == 'optimize':
        optimize_database()
    elif args.command == 'create-user':
        create_user(args.username, args.password, not args.username or not args.password)
    elif args.command == 'list-users':
        list_users()
    elif args.command == 'delete-user':
        delete_user(args.username, not args.username)
    elif args.command == 'change-password':
        change_password(args.username, not args.username)
    elif args.command == 'promote-admin':
        promote_admin(args.username, not args.username)
    elif args.command == 'revoke-admin':
        revoke_admin(args.username, not args.username)
    else:
        print("❌ Unknown command")

if __name__ == '__main__':
    main() 