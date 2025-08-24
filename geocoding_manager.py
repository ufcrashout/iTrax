#!/usr/bin/env python3
"""
Multi-Provider Geocoding Manager for iTrax

Provides reliable geocoding with automatic failover between multiple providers:
- OpenStreetMap/Nominatim (Free, 1 req/sec)
- Google Maps (Paid, high limits)
- MapBox (Freemium, 100k/month free)  
- Here (Freemium, 250k/month free)
- ArcGIS (Free tier available)
- Photon (Free, OpenStreetMap-based)

Features:
- Automatic failover when providers fail or hit rate limits
- Rate limit management
- Provider health monitoring
- Caching to reduce API calls
- Configurable retry strategies
"""

import logging
import time
import hashlib
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import requests

# GeoPy imports
from geopy.geocoders import Nominatim, GoogleV3, MapBox, HereV7, ArcGIS, Photon
from geopy.exc import GeocoderTimedOut, GeocoderServiceError, GeocoderRateLimited, GeocoderUnavailable

# Configuration import
try:
    from config import Config
except ImportError:
    # Fallback config if not available
    class Config:
        GOOGLE_GEOCODING_API_KEY = ""
        MAPBOX_API_KEY = ""
        HERE_API_KEY = ""
        GEOCODING_CACHE_SIZE = 1000

logger = logging.getLogger(__name__)

class ProviderStatus(Enum):
    HEALTHY = "healthy"
    RATE_LIMITED = "rate_limited" 
    ERROR = "error"
    UNAVAILABLE = "unavailable"

@dataclass
class ProviderConfig:
    name: str
    geocoder_class: type
    rate_limit: float  # requests per second
    api_key: Optional[str] = None
    user_agent: Optional[str] = None
    timeout: int = 10
    retry_after: int = 300  # seconds to wait after rate limit
    max_retries: int = 3
    priority: int = 1  # lower = higher priority

class GeocodingManager:
    """Multi-provider geocoding manager with automatic failover"""
    
    def __init__(self, user_agent: str = "iTrax-LocationTracker", cache_size: int = None):
        self.user_agent = user_agent
        self.cache = {}  # Simple in-memory cache
        self.cache_max_size = cache_size or getattr(Config, 'GEOCODING_CACHE_SIZE', 1000)
        
        # Provider status tracking
        self.provider_status = {}
        self.provider_last_attempt = {}
        self.provider_consecutive_failures = {}
        
        # Statistics
        self.stats = {
            'requests': 0,
            'cache_hits': 0,
            'successful_geocodes': 0,
            'failed_geocodes': 0,
            'provider_usage': {}
        }
        
        # Initialize providers
        self.providers = self._initialize_providers()
        
    def _initialize_providers(self) -> List[ProviderConfig]:
        """Initialize all available geocoding providers"""
        providers = [
            # Free providers (higher priority)
            ProviderConfig(
                name="Nominatim",
                geocoder_class=Nominatim,
                rate_limit=1.0,  # 1 request per second
                user_agent=self.user_agent,
                timeout=10,
                priority=1
            ),
            ProviderConfig(
                name="Photon", 
                geocoder_class=Photon,
                rate_limit=10.0,  # More generous rate limit
                user_agent=self.user_agent,
                timeout=10,
                priority=2
            ),
            ProviderConfig(
                name="ArcGIS",
                geocoder_class=ArcGIS,
                rate_limit=5.0,  # Free tier limit
                user_agent=self.user_agent, 
                timeout=10,
                priority=3
            )
            
        ]
        
        # Add paid providers if API keys are configured
        if hasattr(Config, 'GOOGLE_GEOCODING_API_KEY') and Config.GOOGLE_GEOCODING_API_KEY:
            providers.append(ProviderConfig(
                name="GoogleV3",
                geocoder_class=GoogleV3,
                rate_limit=50.0,
                api_key=Config.GOOGLE_GEOCODING_API_KEY,
                timeout=10,
                priority=4
            ))
            
        if hasattr(Config, 'MAPBOX_API_KEY') and Config.MAPBOX_API_KEY:
            providers.append(ProviderConfig(
                name="MapBox",
                geocoder_class=MapBox,
                rate_limit=10.0,
                api_key=Config.MAPBOX_API_KEY,
                timeout=10,
                priority=5
            ))
            
        if hasattr(Config, 'HERE_API_KEY') and Config.HERE_API_KEY:
            providers.append(ProviderConfig(
                name="HereV7",
                geocoder_class=HereV7,
                rate_limit=5.0,
                api_key=Config.HERE_API_KEY,
                timeout=10,
                priority=6
            ))
        
        # Sort by priority
        providers.sort(key=lambda p: p.priority)
        
        # Initialize status tracking
        for provider in providers:
            self.provider_status[provider.name] = ProviderStatus.HEALTHY
            self.provider_last_attempt[provider.name] = 0
            self.provider_consecutive_failures[provider.name] = 0
            self.stats['provider_usage'][provider.name] = {'requests': 0, 'successes': 0, 'failures': 0}
        
        logger.info(f"Initialized {len(providers)} geocoding providers: {[p.name for p in providers]}")
        return providers
    
    def _generate_cache_key(self, lat: float, lng: float) -> str:
        """Generate cache key for coordinates"""
        # Round to 4 decimal places for cache efficiency (~11m precision)
        coord_str = f"{lat:.4f},{lng:.4f}"
        return hashlib.md5(coord_str.encode()).hexdigest()
    
    def _get_from_cache(self, cache_key: str) -> Optional[str]:
        """Get address from cache if available and not expired"""
        if cache_key in self.cache:
            cached_data = self.cache[cache_key]
            # Check if cache entry is less than 24 hours old
            if datetime.now() - cached_data['timestamp'] < timedelta(hours=24):
                self.stats['cache_hits'] += 1
                return cached_data['address']
            else:
                # Remove expired entry
                del self.cache[cache_key]
        return None
    
    def _add_to_cache(self, cache_key: str, address: str):
        """Add address to cache"""
        # Implement simple LRU by removing oldest entries when cache is full
        if len(self.cache) >= self.cache_max_size:
            # Remove oldest entry
            oldest_key = min(self.cache.keys(), key=lambda k: self.cache[k]['timestamp'])
            del self.cache[oldest_key]
        
        self.cache[cache_key] = {
            'address': address,
            'timestamp': datetime.now()
        }
    
    def _is_provider_available(self, provider: ProviderConfig) -> bool:
        """Check if provider is available for use"""
        status = self.provider_status[provider.name]
        
        if status == ProviderStatus.HEALTHY:
            return True
        
        # Check if enough time has passed since last failure
        if status in [ProviderStatus.RATE_LIMITED, ProviderStatus.ERROR]:
            time_since_last = time.time() - self.provider_last_attempt[provider.name]
            if time_since_last > provider.retry_after:
                # Reset status to healthy for retry
                self.provider_status[provider.name] = ProviderStatus.HEALTHY
                self.provider_consecutive_failures[provider.name] = 0
                logger.info(f"Provider {provider.name} is available for retry")
                return True
        
        return False
    
    def _create_geocoder(self, provider: ProviderConfig):
        """Create geocoder instance for provider"""
        try:
            kwargs = {
                'user_agent': provider.user_agent or self.user_agent,
                'timeout': provider.timeout
            }
            
            if provider.api_key and provider.geocoder_class in [GoogleV3, MapBox, HereV7]:
                kwargs['api_key'] = provider.api_key
            
            return provider.geocoder_class(**kwargs)
            
        except Exception as e:
            logger.error(f"Failed to create geocoder for {provider.name}: {e}")
            return None
    
    def _geocode_with_provider(self, provider: ProviderConfig, lat: float, lng: float) -> Optional[str]:
        """Attempt geocoding with specific provider"""
        geocoder = self._create_geocoder(provider)
        if not geocoder:
            return None
        
        try:
            # Rate limiting
            time_since_last = time.time() - self.provider_last_attempt[provider.name]
            min_interval = 1.0 / provider.rate_limit
            if time_since_last < min_interval:
                sleep_time = min_interval - time_since_last
                logger.debug(f"Rate limiting: sleeping {sleep_time:.2f}s for {provider.name}")
                time.sleep(sleep_time)
            
            self.provider_last_attempt[provider.name] = time.time()
            
            # Attempt geocoding
            logger.debug(f"Geocoding ({lat:.4f}, {lng:.4f}) with {provider.name}")
            location = geocoder.reverse(f"{lat}, {lng}")
            
            if location and location.address:
                # Success
                self.provider_status[provider.name] = ProviderStatus.HEALTHY
                self.provider_consecutive_failures[provider.name] = 0
                self.stats['provider_usage'][provider.name]['successes'] += 1
                self.stats['successful_geocodes'] += 1
                
                logger.debug(f"Successfully geocoded with {provider.name}: {location.address}")
                return location.address
            else:
                logger.warning(f"No address found with {provider.name}")
                return None
                
        except GeocoderRateLimited as e:
            logger.warning(f"Rate limited by {provider.name}: {e}")
            self.provider_status[provider.name] = ProviderStatus.RATE_LIMITED
            self.provider_consecutive_failures[provider.name] += 1
            self.stats['provider_usage'][provider.name]['failures'] += 1
            return None
            
        except (GeocoderTimedOut, GeocoderServiceError, GeocoderUnavailable) as e:
            logger.warning(f"Geocoding error with {provider.name}: {e}")
            self.provider_consecutive_failures[provider.name] += 1
            
            # Mark as unavailable if too many consecutive failures
            if self.provider_consecutive_failures[provider.name] >= provider.max_retries:
                self.provider_status[provider.name] = ProviderStatus.ERROR
                logger.error(f"Provider {provider.name} marked as unavailable after {provider.max_retries} failures")
            
            self.stats['provider_usage'][provider.name]['failures'] += 1
            return None
            
        except Exception as e:
            logger.error(f"Unexpected error with {provider.name}: {e}")
            self.provider_consecutive_failures[provider.name] += 1
            self.provider_status[provider.name] = ProviderStatus.ERROR
            self.stats['provider_usage'][provider.name]['failures'] += 1
            return None
        
        finally:
            self.stats['provider_usage'][provider.name]['requests'] += 1
    
    def get_address_from_coordinates(self, lat: float, lng: float, max_providers: int = None) -> Optional[str]:
        """
        Get address from coordinates using multiple providers with failover
        
        Args:
            lat: Latitude
            lng: Longitude 
            max_providers: Maximum number of providers to try (None = try all)
            
        Returns:
            Address string or None if all providers fail
        """
        self.stats['requests'] += 1
        
        # Check cache first
        cache_key = self._generate_cache_key(lat, lng)
        cached_address = self._get_from_cache(cache_key)
        if cached_address:
            logger.debug(f"Cache hit for ({lat:.4f}, {lng:.4f}): {cached_address}")
            return cached_address
        
        # Try providers in priority order
        providers_tried = 0
        max_to_try = max_providers or len(self.providers)
        
        for provider in self.providers:
            if providers_tried >= max_to_try:
                break
                
            if not self._is_provider_available(provider):
                logger.debug(f"Skipping unavailable provider: {provider.name}")
                continue
            
            providers_tried += 1
            logger.debug(f"Trying provider {provider.name} ({providers_tried}/{max_to_try})")
            
            address = self._geocode_with_provider(provider, lat, lng)
            if address:
                # Cache successful result
                self._add_to_cache(cache_key, address)
                logger.info(f"Successfully geocoded ({lat:.4f}, {lng:.4f}) with {provider.name}")
                return address
        
        # All providers failed
        logger.warning(f"All available providers failed for coordinates ({lat:.4f}, {lng:.4f})")
        self.stats['failed_geocodes'] += 1
        return None
    
    def get_provider_status(self) -> Dict:
        """Get status of all providers"""
        status = {}
        for provider in self.providers:
            status[provider.name] = {
                'status': self.provider_status[provider.name].value,
                'consecutive_failures': self.provider_consecutive_failures[provider.name],
                'last_attempt': self.provider_last_attempt[provider.name],
                'usage_stats': self.stats['provider_usage'][provider.name]
            }
        return status
    
    def get_stats(self) -> Dict:
        """Get geocoding statistics"""
        return {
            **self.stats,
            'cache_size': len(self.cache),
            'provider_status': self.get_provider_status()
        }
    
    def reset_provider(self, provider_name: str):
        """Reset a provider's status to healthy"""
        if provider_name in self.provider_status:
            self.provider_status[provider_name] = ProviderStatus.HEALTHY
            self.provider_consecutive_failures[provider_name] = 0
            logger.info(f"Reset provider {provider_name} to healthy status")
    
    def clear_cache(self):
        """Clear the geocoding cache"""
        cache_size = len(self.cache)
        self.cache.clear()
        logger.info(f"Cleared geocoding cache ({cache_size} entries)")

# Global instance
_geocoding_manager = None

def get_geocoding_manager() -> GeocodingManager:
    """Get global geocoding manager instance"""
    global _geocoding_manager
    if _geocoding_manager is None:
        _geocoding_manager = GeocodingManager()
    return _geocoding_manager

def get_address_from_coordinates(lat: float, lng: float) -> Optional[str]:
    """Convenience function for geocoding"""
    return get_geocoding_manager().get_address_from_coordinates(lat, lng)