#!/usr/bin/env python3
"""
Debug script to test analytics functionality
"""

import logging
import sys
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

try:
    from analytics import analytics
    from database import db
    print("✅ Successfully imported analytics and database modules")
except Exception as e:
    print(f"❌ Error importing modules: {e}")
    sys.exit(1)

def test_analytics():
    """Test analytics functionality"""
    print("\n🔍 Testing Analytics Functionality")
    print("=" * 50)
    
    # Get list of available devices
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT device_name, COUNT(*) as count, 
                       MAX(timestamp) as last_seen 
                FROM locations 
                GROUP BY device_name 
                ORDER BY count DESC 
                LIMIT 5
            """)
            devices = cursor.fetchall()
        
        if not devices:
            print("❌ No devices found in database")
            return
        
        print(f"📱 Found {len(devices)} devices:")
        for i, device in enumerate(devices, 1):
            print(f"  {i}. {device['device_name']} ({device['count']} points, last: {device['last_seen']})")
        
        # Test with first device
        test_device = devices[0]['device_name']
        print(f"\n🧪 Testing analytics with device: {test_device}")
        
        # Test 1: Get device summary stats
        print("\n1️⃣ Testing get_device_summary_stats...")
        try:
            summary_stats = analytics.get_device_summary_stats(test_device, days=7)
            print(f"✅ Summary stats retrieved")
            print(f"   - Total points: {summary_stats.get('total_tracking_points', 0)}")
            print(f"   - Daily analytics entries: {len(summary_stats.get('daily_analytics', []))}")
            print(f"   - Weekly top locations: {len(summary_stats.get('weekly_top_locations', []))}")
            print(f"   - Overall top locations: {len(summary_stats.get('overall_top_locations', []))}")
            
            if summary_stats.get('weekly_top_locations'):
                print("   📍 Weekly top locations:")
                for i, loc in enumerate(summary_stats['weekly_top_locations'][:3], 1):
                    print(f"      {i}. {loc['address']} ({loc['visit_count']} visits, {loc['total_time_minutes']:.1f}m)")
            else:
                print("   ⚠️ No weekly top locations found")
                
        except Exception as e:
            print(f"❌ Error in get_device_summary_stats: {e}")
            import traceback
            print(traceback.format_exc())
        
        # Test 2: Get top visited locations directly
        print("\n2️⃣ Testing get_top_visited_locations...")
        try:
            weekly_top = analytics.get_top_visited_locations(test_device, days=7, limit=5)
            print(f"✅ Weekly top locations: {len(weekly_top)} found")
            for i, loc in enumerate(weekly_top, 1):
                print(f"   {i}. {loc['address']} - {loc['visit_count']} visits")
            
            overall_top = analytics.get_top_visited_locations(test_device, days=None, limit=5)
            print(f"✅ Overall top locations: {len(overall_top)} found")
            for i, loc in enumerate(overall_top, 1):
                print(f"   {i}. {loc['address']} - {loc['visit_count']} visits")
                
        except Exception as e:
            print(f"❌ Error in get_top_visited_locations: {e}")
            import traceback
            print(traceback.format_exc())
        
        # Test 3: Test address grouping
        print("\n3️⃣ Testing address grouping...")
        try:
            # Get recent locations for the device
            recent_locations = db.get_locations(
                device_name=test_device,
                limit=100
            )
            
            if recent_locations:
                print(f"✅ Retrieved {len(recent_locations)} recent locations")
                
                # Test grouping
                address_groups = analytics.group_locations_by_address(recent_locations)
                print(f"✅ Grouped into {len(address_groups)} address groups")
                
                for i, (address, locations) in enumerate(list(address_groups.items())[:5], 1):
                    print(f"   {i}. {address} - {len(locations)} points")
            else:
                print("❌ No recent locations found")
                
        except Exception as e:
            print(f"❌ Error in address grouping: {e}")
            import traceback
            print(traceback.format_exc())
        
    except Exception as e:
        print(f"❌ Database error: {e}")
        import traceback
        print(traceback.format_exc())

def test_database_connection():
    """Test database connection"""
    print("🔌 Testing Database Connection")
    print("=" * 50)
    
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Test basic query
            cursor.execute("SELECT COUNT(*) as total FROM locations")
            result = cursor.fetchone()
            print(f"✅ Database connected - Total locations: {result['total']}")
            
            # Test recent data
            cursor.execute("""
                SELECT COUNT(*) as recent FROM locations 
                WHERE timestamp >= DATE_SUB(NOW(), INTERVAL 7 DAY)
            """)
            result = cursor.fetchone()
            print(f"✅ Recent data (7 days): {result['recent']} locations")
            
            return True
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return False

def main():
    """Run all tests"""
    print("🧪 Analytics Debug Tool")
    print("=" * 60)
    
    # Test database connection first
    if not test_database_connection():
        print("\n❌ Cannot proceed without database connection")
        return
    
    # Test analytics
    test_analytics()
    
    print("\n🎯 Debug Summary:")
    print("- Check the logs above for any error messages")
    print("- If top locations are empty, there might be an issue with:")
    print("  * Address geocoding (check geocoding_manager.py)")
    print("  * Location grouping logic")
    print("  * Database queries")
    print("  * Timestamp parsing")

if __name__ == "__main__":
    main()