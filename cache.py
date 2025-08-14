"""
iTrax Caching System
High-performance caching layer for database queries and API responses
"""

import time
import hashlib
import json
import logging
from typing import Any, Dict, Optional, Tuple
from functools import wraps
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class PerformanceCache:
    """
    High-performance in-memory cache with TTL support and automatic cleanup
    """
    
    def __init__(self, default_ttl: int = 300, max_size: int = 1000):
        self._cache: Dict[str, Tuple[Any, float]] = {}
        self.default_ttl = default_ttl
        self.max_size = max_size
        self.hits = 0
        self.misses = 0
        self.last_cleanup = time.time()
        
    def _cleanup_expired(self):
        """Remove expired cache entries"""
        current_time = time.time()
        expired_keys = [
            key for key, (_, timestamp) in self._cache.items()
            if current_time - timestamp > self.default_ttl
        ]
        
        for key in expired_keys:
            del self._cache[key]
            
        # Cleanup every 5 minutes or when cache is large
        if current_time - self.last_cleanup > 300 or len(self._cache) > self.max_size:
            self.last_cleanup = current_time
            
        # If still too large, remove oldest entries
        if len(self._cache) > self.max_size:
            # Sort by timestamp and remove oldest 20%
            sorted_items = sorted(self._cache.items(), key=lambda x: x[1][1])
            remove_count = int(len(sorted_items) * 0.2)
            for key, _ in sorted_items[:remove_count]:
                del self._cache[key]
                
        logger.debug(f"Cache cleanup: removed {len(expired_keys)} expired entries, "
                    f"cache size: {len(self._cache)}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get value from cache"""
        self._cleanup_expired()
        
        if key in self._cache:
            value, timestamp = self._cache[key]
            if time.time() - timestamp < self.default_ttl:
                self.hits += 1
                logger.debug(f"Cache HIT: {key}")
                return value
            else:
                del self._cache[key]
                
        self.misses += 1
        logger.debug(f"Cache MISS: {key}")
        return default
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        """Set value in cache"""
        self._cache[key] = (value, time.time())
        
    def delete(self, key: str):
        """Delete key from cache"""
        if key in self._cache:
            del self._cache[key]
            
    def clear(self):
        """Clear all cache"""
        self._cache.clear()
        self.hits = 0
        self.misses = 0
        
    def get_stats(self) -> Dict:
        """Get cache statistics"""
        total_requests = self.hits + self.misses
        hit_rate = (self.hits / total_requests * 100) if total_requests > 0 else 0
        
        return {
            'size': len(self._cache),
            'hits': self.hits,
            'misses': self.misses,
            'hit_rate': round(hit_rate, 2),
            'max_size': self.max_size
        }

# Global cache instances
location_cache = PerformanceCache(default_ttl=180, max_size=500)  # 3 minutes for location data
analytics_cache = PerformanceCache(default_ttl=600, max_size=200)  # 10 minutes for analytics
notification_cache = PerformanceCache(default_ttl=60, max_size=100)  # 1 minute for notifications
dashboard_cache = PerformanceCache(default_ttl=120, max_size=100)  # 2 minutes for dashboard

def cache_key_generator(*args, **kwargs) -> str:
    """Generate consistent cache key from arguments"""
    key_data = {
        'args': args,
        'kwargs': kwargs
    }
    key_string = json.dumps(key_data, sort_keys=True, default=str)
    return hashlib.md5(key_string.encode()).hexdigest()

def cached_query(cache_instance: PerformanceCache, ttl: Optional[int] = None):
    """
    Decorator for caching database query results
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Generate cache key
            cache_key = f"{func.__name__}:{cache_key_generator(*args, **kwargs)}"
            
            # Try to get from cache
            cached_result = cache_instance.get(cache_key)
            if cached_result is not None:
                return cached_result
                
            # Execute function and cache result
            result = func(*args, **kwargs)
            cache_instance.set(cache_key, result, ttl)
            
            return result
        return wrapper
    return decorator

def invalidate_location_cache(device_name: Optional[str] = None):
    """Invalidate location-related cache entries"""
    if device_name:
        # Clear specific device cache entries
        keys_to_remove = [key for key in location_cache._cache.keys() if device_name in key]
        for key in keys_to_remove:
            location_cache.delete(key)
    else:
        # Clear all location cache
        location_cache.clear()
        
    # Also clear dashboard cache as it depends on location data
    dashboard_cache.clear()
    
def invalidate_analytics_cache():
    """Invalidate analytics cache"""
    analytics_cache.clear()
    
def invalidate_notification_cache():
    """Invalidate notification cache"""
    notification_cache.clear()

# Performance monitoring
class QueryTimer:
    """Context manager for timing database queries"""
    
    def __init__(self, query_name: str):
        self.query_name = query_name
        self.start_time = None
        
    def __enter__(self):
        self.start_time = time.time()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time:
            duration = time.time() - self.start_time
            if duration > 1.0:  # Log slow queries (> 1 second)
                logger.warning(f"SLOW QUERY: {self.query_name} took {duration:.2f}s")
            elif duration > 0.5:  # Log medium queries (> 0.5 second)
                logger.info(f"MEDIUM QUERY: {self.query_name} took {duration:.2f}s")
            else:
                logger.debug(f"QUERY: {self.query_name} took {duration:.3f}s")

def get_all_cache_stats() -> Dict:
    """Get statistics for all cache instances"""
    return {
        'location_cache': location_cache.get_stats(),
        'analytics_cache': analytics_cache.get_stats(),
        'notification_cache': notification_cache.get_stats(),
        'dashboard_cache': dashboard_cache.get_stats()
    }