#!/usr/bin/env python3
"""
Backup Scheduler for iTrax
Handles scheduled database backups 3 times daily with rotation and cleanup
"""

import os
import time
import threading
import logging
import schedule
from datetime import datetime, timedelta
from pathlib import Path
from config import Config
from database import db

logger = logging.getLogger(__name__)

class BackupScheduler:
    """Handles scheduled database backups with retention management"""
    
    def __init__(self, backup_dir: str = None, retention_days: int = None):
        """
        Initialize backup scheduler
        
        Args:
            backup_dir: Directory to store backups (default: ./backups)
            retention_days: Days to keep backups (default: from config)
        """
        self.backup_dir = Path(backup_dir) if backup_dir else Path("backups")
        self.retention_days = retention_days or getattr(Config, 'DATABASE_BACKUP_RETENTION_DAYS', 14)
        self.is_running = False
        self.scheduler_thread = None
        
        # Create backup directory if it doesn't exist
        self.backup_dir.mkdir(exist_ok=True)
        logger.info(f"Backup directory: {self.backup_dir.absolute()}")
        logger.info(f"Backup retention: {self.retention_days} days")
        
    def create_backup(self):
        """Create a database backup with timestamp"""
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_filename = f"itrax_backup_{timestamp}.sql"
            backup_path = self.backup_dir / backup_filename
            
            logger.info(f"Creating scheduled backup: {backup_filename}")
            
            # Create the backup
            result = db.backup_database(str(backup_path))
            
            if result:
                logger.info(f"✅ Backup created successfully: {backup_path}")
                
                # Clean up old backups
                self.cleanup_old_backups()
                
                return str(backup_path)
            else:
                logger.error(f"❌ Failed to create backup: {backup_filename}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Error creating backup: {e}")
            return None
    
    def cleanup_old_backups(self):
        """Remove backup files older than retention period"""
        try:
            cutoff_date = datetime.now() - timedelta(days=self.retention_days)
            removed_count = 0
            
            for backup_file in self.backup_dir.glob("itrax_backup_*.sql"):
                try:
                    # Extract timestamp from filename
                    filename_parts = backup_file.stem.split('_')
                    if len(filename_parts) >= 3:
                        date_str = filename_parts[2]
                        time_str = filename_parts[3] if len(filename_parts) > 3 else "000000"
                        
                        # Parse timestamp
                        backup_datetime = datetime.strptime(f"{date_str}_{time_str}", '%Y%m%d_%H%M%S')
                        
                        # Remove if older than retention period
                        if backup_datetime < cutoff_date:
                            backup_file.unlink()
                            removed_count += 1
                            logger.info(f"Removed old backup: {backup_file.name}")
                            
                except (ValueError, OSError) as e:
                    logger.warning(f"Error processing backup file {backup_file}: {e}")
                    continue
            
            if removed_count > 0:
                logger.info(f"Cleaned up {removed_count} old backup files")
                
        except Exception as e:
            logger.error(f"Error cleaning up old backups: {e}")
    
    def get_backup_info(self):
        """Get information about existing backups"""
        try:
            backups = []
            total_size = 0
            
            for backup_file in sorted(self.backup_dir.glob("itrax_backup_*.sql"), reverse=True):
                try:
                    file_size = backup_file.stat().st_size
                    total_size += file_size
                    
                    # Parse timestamp from filename
                    filename_parts = backup_file.stem.split('_')
                    if len(filename_parts) >= 3:
                        date_str = filename_parts[2]
                        time_str = filename_parts[3] if len(filename_parts) > 3 else "000000"
                        backup_datetime = datetime.strptime(f"{date_str}_{time_str}", '%Y%m%d_%H%M%S')
                        
                        backups.append({
                            'filename': backup_file.name,
                            'path': str(backup_file),
                            'size': file_size,
                            'size_mb': round(file_size / (1024 * 1024), 2),
                            'created': backup_datetime,
                            'age_days': (datetime.now() - backup_datetime).days
                        })
                        
                except (ValueError, OSError) as e:
                    logger.warning(f"Error processing backup file {backup_file}: {e}")
                    continue
            
            return {
                'backups': backups,
                'total_count': len(backups),
                'total_size_mb': round(total_size / (1024 * 1024), 2),
                'backup_dir': str(self.backup_dir.absolute()),
                'retention_days': self.retention_days
            }
            
        except Exception as e:
            logger.error(f"Error getting backup info: {e}")
            return {
                'backups': [],
                'total_count': 0,
                'total_size_mb': 0,
                'backup_dir': str(self.backup_dir.absolute()),
                'retention_days': self.retention_days,
                'error': str(e)
            }
    
    def schedule_backups(self):
        """Schedule backups 3 times daily"""
        try:
            # Clear any existing schedule
            schedule.clear()
            
            # Schedule backups at 06:00, 14:00, and 22:00
            schedule.every().day.at("06:00").do(self.create_backup)
            schedule.every().day.at("14:00").do(self.create_backup)
            schedule.every().day.at("22:00").do(self.create_backup)
            
            logger.info("✅ Backup schedule configured: 06:00, 14:00, 22:00 daily")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error scheduling backups: {e}")
            return False
    
    def run_scheduler(self):
        """Run the backup scheduler in background thread"""
        logger.info("🔄 Starting backup scheduler...")
        
        while self.is_running:
            try:
                schedule.run_pending()
                time.sleep(60)  # Check every minute
            except Exception as e:
                logger.error(f"Error in backup scheduler: {e}")
                time.sleep(300)  # Wait 5 minutes on error
    
    def start(self):
        """Start the backup scheduler"""
        if self.is_running:
            logger.warning("Backup scheduler is already running")
            return False
        
        try:
            # Schedule the backups
            if not self.schedule_backups():
                return False
            
            # Start the scheduler thread
            self.is_running = True
            self.scheduler_thread = threading.Thread(target=self.run_scheduler, daemon=True)
            self.scheduler_thread.start()
            
            logger.info("✅ Backup scheduler started successfully")
            
            # Create initial backup if none exist
            if not list(self.backup_dir.glob("itrax_backup_*.sql")):
                logger.info("No existing backups found, creating initial backup...")
                self.create_backup()
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to start backup scheduler: {e}")
            self.is_running = False
            return False
    
    def stop(self):
        """Stop the backup scheduler"""
        try:
            self.is_running = False
            schedule.clear()
            
            if self.scheduler_thread and self.scheduler_thread.is_alive():
                self.scheduler_thread.join(timeout=5)
            
            logger.info("✅ Backup scheduler stopped")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error stopping backup scheduler: {e}")
            return False
    
    def force_backup(self):
        """Force create a backup immediately"""
        logger.info("🔄 Creating forced backup...")
        return self.create_backup()

# Global backup scheduler instance
_backup_scheduler = None

def get_backup_scheduler() -> BackupScheduler:
    """Get global backup scheduler instance"""
    global _backup_scheduler
    if _backup_scheduler is None:
        _backup_scheduler = BackupScheduler()
    return _backup_scheduler

def start_backup_scheduler():
    """Start the global backup scheduler"""
    return get_backup_scheduler().start()

def stop_backup_scheduler():
    """Stop the global backup scheduler"""
    return get_backup_scheduler().stop()

def create_backup():
    """Create a backup using the global scheduler"""
    return get_backup_scheduler().create_backup()

def get_backup_info():
    """Get backup information using the global scheduler"""
    return get_backup_scheduler().get_backup_info()

if __name__ == "__main__":
    # For testing
    logging.basicConfig(level=logging.INFO)
    
    scheduler = BackupScheduler()
    print("Testing backup scheduler...")
    
    # Test backup creation
    backup_path = scheduler.create_backup()
    if backup_path:
        print(f"✅ Test backup created: {backup_path}")
    else:
        print("❌ Test backup failed")
    
    # Test backup info
    info = scheduler.get_backup_info()
    print(f"📊 Backup info: {info['total_count']} backups, {info['total_size_mb']} MB total")