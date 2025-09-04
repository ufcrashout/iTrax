#!/usr/bin/env python3
"""
Top Locations Cache Scheduler

Background service that updates cached top 10 locations every 2-3 hours.
Provides much faster loading for top 10 all-time locations by pre-computing results.
"""

import logging
import time
import threading
from datetime import datetime, timedelta
from typing import List, Dict

from database import db
from analytics import analytics

logger = logging.getLogger(__name__)

class TopLocationsCacheScheduler:
    def __init__(self):
        self.running = False
        self.thread = None
        self.update_interval = 2.5 * 3600  # 2.5 hours in seconds
        
    def start(self):
        """Start the background scheduler"""
        if self.running:
            logger.warning("Scheduler is already running")
            return
            
        self.running = True
        self.thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self.thread.start()
        logger.info("Top locations cache scheduler started")
        
    def stop(self):
        """Stop the background scheduler"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=10)
        logger.info("Top locations cache scheduler stopped")
        
    def _run_scheduler(self):
        """Main scheduler loop"""
        logger.info("Cache scheduler thread started")
        
        # Run initial cache update for all devices
        self._update_all_caches()
        
        while self.running:
            try:
                # Wait for next update interval
                time.sleep(60)  # Check every minute for efficiency
                
                if not self.running:
                    break
                    
                # Check if any cache needs updating
                self._check_and_update_caches()
                
            except Exception as e:
                logger.error(f"Error in cache scheduler: {e}")
                time.sleep(300)  # Wait 5 minutes on error
                
        logger.info("Cache scheduler thread stopped")
        
    def _check_and_update_caches(self):
        """Check which devices need cache updates and update them"""
        try:
            # Check for expired weekly caches
            weekly_devices = db.get_devices_needing_cache_update('weekly')
            for device in weekly_devices:
                logger.info(f"Updating weekly cache for device: {device}")
                self._update_device_cache(device, 'weekly')
                
            # Check for expired all-time caches
            alltime_devices = db.get_devices_needing_cache_update('alltime')
            for device in alltime_devices:
                logger.info(f"Updating all-time cache for device: {device}")
                self._update_device_cache(device, 'alltime')
                
        except Exception as e:
            logger.error(f"Error checking cache updates: {e}")
            
    def _update_all_caches(self):
        """Update caches for all devices (initial run)"""
        try:
            # Get all devices with location data
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT DISTINCT device_name FROM locations")
                devices = [row['device_name'] for row in cursor.fetchall()]
                
            logger.info(f"Performing initial cache update for {len(devices)} devices")
            
            for device in devices:
                logger.info(f"Initial cache update for device: {device}")
                self._update_device_cache(device, 'weekly')
                self._update_device_cache(device, 'alltime')
                
        except Exception as e:
            logger.error(f"Error in initial cache update: {e}")
            
    def _update_device_cache(self, device_name: str, cache_type: str):
        """Update cache for a specific device and type"""
        try:
            start_time = time.time()
            
            # Get fresh top locations data
            if cache_type == 'weekly':
                locations = analytics.get_top_visited_locations(
                    device_name=device_name, 
                    days=7, 
                    limit=10
                )
            else:  # alltime
                locations = analytics.get_top_visited_locations(
                    device_name=device_name, 
                    days=None, 
                    limit=10
                )
                
            if locations:
                # Save to cache
                success = db.save_cached_top_locations(device_name, cache_type, locations)
                
                duration = time.time() - start_time
                if success:
                    logger.info(f"Updated {cache_type} cache for {device_name}: {len(locations)} locations in {duration:.2f}s")
                else:
                    logger.error(f"Failed to save {cache_type} cache for {device_name}")
            else:
                logger.warning(f"No locations found for {device_name} ({cache_type})")
                
        except Exception as e:
            logger.error(f"Error updating {cache_type} cache for {device_name}: {e}")
            import traceback
            logger.error(f"Cache update traceback: {traceback.format_exc()}")
            
    def force_update_device(self, device_name: str):
        """Force immediate cache update for a specific device"""
        logger.info(f"Force updating cache for device: {device_name}")
        self._update_device_cache(device_name, 'weekly')
        self._update_device_cache(device_name, 'alltime')
        
    def get_cache_status(self) -> Dict:
        """Get current cache status for all devices"""
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                
                # Get cache status
                cursor.execute("""
                    SELECT device_name, cache_type, updated_at, next_update,
                           COUNT(*) as cached_locations
                    FROM cached_top_locations
                    GROUP BY device_name, cache_type
                    ORDER BY device_name, cache_type
                """)
                
                cache_status = cursor.fetchall()
                
                return {
                    'running': self.running,
                    'update_interval_hours': self.update_interval / 3600,
                    'cache_status': cache_status
                }
                
        except Exception as e:
            logger.error(f"Error getting cache status: {e}")
            return {'running': self.running, 'error': str(e)}

# Global scheduler instance
top_locations_scheduler = TopLocationsCacheScheduler()

def start_scheduler():
    """Start the global scheduler instance"""
    top_locations_scheduler.start()

def stop_scheduler():
    """Stop the global scheduler instance"""
    top_locations_scheduler.stop()

if __name__ == "__main__":
    # For testing the scheduler standalone
    logging.basicConfig(level=logging.INFO)
    
    scheduler = TopLocationsCacheScheduler()
    
    try:
        scheduler.start()
        
        # Keep running for testing
        while True:
            time.sleep(30)
            status = scheduler.get_cache_status()
            print(f"Cache status: {status}")
            
    except KeyboardInterrupt:
        print("Stopping scheduler...")
        scheduler.stop()