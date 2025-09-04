#!/usr/bin/env python3
"""
Clear analytics cache to force regeneration of data
"""

import sys
import os

try:
    from cache import analytics_cache
    print("✅ Successfully imported analytics cache")
    
    # Clear the cache
    analytics_cache.clear()
    print("✅ Analytics cache cleared successfully")
    print("🔄 Next analytics request will regenerate all data")
    
except Exception as e:
    print(f"❌ Error clearing cache: {e}")
    import traceback
    print(traceback.format_exc())

if __name__ == "__main__":
    print("🧹 Clearing Analytics Cache...")
    print("=" * 40)