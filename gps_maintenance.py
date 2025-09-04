#!/usr/bin/env python3
"""
GPS Performance Maintenance Script
Cleans up address cache and optimizes database for better GPS log performance
"""

import logging
import sys
import os
from datetime import datetime, timedelta
from database import Database

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class GPSMaintenance:
    def __init__(self):
        self.db = Database()
    
    def cleanup_address_cache(self, keep_count: int = 10000):
        """Clean up old address cache entries"""
        logger.info("Starting address cache cleanup...")
        
        try:
            success = self.db.cleanup_address_cache(keep_count)
            if success:
                logger.info(f"✅ Address cache cleanup completed (kept top {keep_count} entries)")
            else:
                logger.error("❌ Address cache cleanup failed")
            return success
        except Exception as e:
            logger.error(f"❌ Error during address cache cleanup: {e}")
            return False
    
    def optimize_database_indexes(self):
        """Optimize database indexes for GPS performance"""
        logger.info("Optimizing database indexes...")
        
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                # Analyze tables to update statistics
                cursor.execute("ANALYZE TABLE locations")
                cursor.execute("ANALYZE TABLE address_cache")
                
                # Optimize tables
                cursor.execute("OPTIMIZE TABLE locations")
                cursor.execute("OPTIMIZE TABLE address_cache")
                
                logger.info("✅ Database optimization completed")
                return True
                
        except Exception as e:
            logger.error(f"❌ Database optimization failed: {e}")
            return False
    
    def vacuum_logs_table(self, days_to_keep: int = 365):
        """Remove old location records to keep database size manageable"""
        logger.info(f"Cleaning old location records (keeping last {days_to_keep} days)...")
        
        try:
            cutoff_date = datetime.now() - timedelta(days=days_to_keep)
            
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                # Count records to be deleted
                cursor.execute("""
                    SELECT COUNT(*) as old_count FROM locations 
                    WHERE timestamp < %s
                """, (cutoff_date,))
                
                result = cursor.fetchone()
                old_count = result['old_count'] if result else 0
                
                if old_count > 0:
                    logger.info(f"Found {old_count:,} old records to clean up")
                    
                    # Delete old records in batches to avoid locking
                    batch_size = 10000
                    deleted_total = 0
                    
                    while True:
                        cursor.execute("""
                            DELETE FROM locations 
                            WHERE timestamp < %s 
                            LIMIT %s
                        """, (cutoff_date, batch_size))
                        
                        deleted = cursor.rowcount
                        if deleted == 0:
                            break
                            
                        deleted_total += deleted
                        logger.info(f"Deleted {deleted_total:,} / {old_count:,} old records")
                        
                        # Small delay between batches
                        import time
                        time.sleep(0.1)
                    
                    logger.info(f"✅ Cleaned up {deleted_total:,} old location records")
                else:
                    logger.info("✅ No old records to clean up")
                
            return True
            
        except Exception as e:
            logger.error(f"❌ Error during logs cleanup: {e}")
            return False
    
    def generate_performance_report(self):
        """Generate a performance report"""
        logger.info("Generating performance report...")
        
        try:
            stats = self.db.get_statistics()
            
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                # Get table sizes
                cursor.execute("SHOW TABLE STATUS LIKE 'locations'")
                locations_info = cursor.fetchone()
                
                cursor.execute("SHOW TABLE STATUS LIKE 'address_cache'")
                cache_info = cursor.fetchone()
                
                # Get index information
                cursor.execute("SHOW INDEX FROM locations")
                indexes = cursor.fetchall()
                
                report = {
                    'timestamp': datetime.now().isoformat(),
                    'database_stats': stats,
                    'table_sizes': {
                        'locations': {
                            'rows': locations_info['Rows'] if locations_info else 0,
                            'data_size_mb': round((locations_info['Data_length'] or 0) / 1024 / 1024, 2) if locations_info else 0,
                            'index_size_mb': round((locations_info['Index_length'] or 0) / 1024 / 1024, 2) if locations_info else 0
                        },
                        'address_cache': {
                            'rows': cache_info['Rows'] if cache_info else 0,
                            'data_size_mb': round((cache_info['Data_length'] or 0) / 1024 / 1024, 2) if cache_info else 0
                        }
                    },
                    'indexes_count': len(indexes) if indexes else 0
                }
                
                # Print report
                print("\n📊 GPS PERFORMANCE REPORT")
                print("=" * 40)
                print(f"Generated: {report['timestamp']}")
                print("\n📈 Database Statistics:")
                print(f"   Total locations: {stats.get('total_locations', 0):,}")
                print(f"   Unique devices: {stats.get('unique_devices', 0)}")
                print(f"   Today's records: {stats.get('today_count', 0):,}")
                print(f"   Address cache size: {stats.get('address_cache_size', 0):,}")
                
                print("\n💾 Table Sizes:")
                locations_size = report['table_sizes']['locations']
                print(f"   Locations: {locations_size['rows']:,} rows, {locations_size['data_size_mb']} MB data, {locations_size['index_size_mb']} MB indexes")
                
                cache_size = report['table_sizes']['address_cache']
                print(f"   Address cache: {cache_size['rows']:,} rows, {cache_size['data_size_mb']} MB data")
                
                print(f"\n🔍 Indexes: {report['indexes_count']} total indexes")
                
                # Save report
                import json
                with open('gps_performance_report.json', 'w') as f:
                    json.dump(report, f, indent=2)
                
                logger.info("✅ Performance report generated and saved to gps_performance_report.json")
                return report
                
        except Exception as e:
            logger.error(f"❌ Error generating performance report: {e}")
            return None
    
    def run_maintenance(self, cleanup_cache=True, optimize_db=True, cleanup_old_data=False, days_to_keep=365):
        """Run full maintenance routine"""
        logger.info("🔧 Starting GPS performance maintenance")
        logger.info("=" * 50)
        
        success_count = 0
        total_tasks = 0
        
        # Generate initial report
        logger.info("\n📊 Initial performance report:")
        self.generate_performance_report()
        
        # Address cache cleanup
        if cleanup_cache:
            total_tasks += 1
            if self.cleanup_address_cache():
                success_count += 1
        
        # Database optimization
        if optimize_db:
            total_tasks += 1
            if self.optimize_database_indexes():
                success_count += 1
        
        # Old data cleanup (optional)
        if cleanup_old_data:
            total_tasks += 1
            if self.vacuum_logs_table(days_to_keep):
                success_count += 1
        
        # Generate final report
        logger.info("\n📊 Final performance report:")
        self.generate_performance_report()
        
        # Summary
        logger.info("\n🎉 MAINTENANCE COMPLETE")
        logger.info(f"✅ {success_count}/{total_tasks} tasks completed successfully")
        
        if success_count == total_tasks:
            logger.info("🏆 All maintenance tasks completed successfully!")
        else:
            logger.warning(f"⚠️  {total_tasks - success_count} tasks had issues. Check logs above.")
        
        return success_count == total_tasks

def main():
    """Main function to run maintenance"""
    import argparse
    
    parser = argparse.ArgumentParser(description='GPS Performance Maintenance')
    parser.add_argument('--skip-cache-cleanup', action='store_true', help='Skip address cache cleanup')
    parser.add_argument('--skip-optimize', action='store_true', help='Skip database optimization')
    parser.add_argument('--cleanup-old-data', action='store_true', help='Enable old data cleanup')
    parser.add_argument('--days-to-keep', type=int, default=365, help='Days of data to keep (default: 365)')
    parser.add_argument('--report-only', action='store_true', help='Only generate performance report')
    
    args = parser.parse_args()
    
    maintenance = GPSMaintenance()
    
    if args.report_only:
        logger.info("📊 Generating performance report only...")
        maintenance.generate_performance_report()
    else:
        success = maintenance.run_maintenance(
            cleanup_cache=not args.skip_cache_cleanup,
            optimize_db=not args.skip_optimize,
            cleanup_old_data=args.cleanup_old_data,
            days_to_keep=args.days_to_keep
        )
        
        sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()