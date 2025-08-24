#!/usr/bin/env python3
"""
Advanced Analytics Module for iTrax

Provides location analytics, address resolution, smart grouping, and insights.
"""

import logging
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import pytz
import pymysql
from geopy.distance import geodesic
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
from geocoding_manager import get_geocoding_manager, get_address_from_coordinates
from collections import defaultdict
import statistics
import folium
from folium.plugins import HeatMap
import tempfile
import os

from config import Config
from database import db

logger = logging.getLogger(__name__)

class LocationAnalytics:
    def __init__(self):
        self.timezone = Config.get_timezone()
        
    def get_address_from_coordinates(self, latitude: float, longitude: float, use_cache: bool = True) -> Optional[str]:
        """Get address from coordinates using multi-provider geocoding with SQL caching"""
        
        # Check SQL cache first
        if use_cache:
            cached_address = db.get_cached_address(latitude, longitude)
            if cached_address:
                return cached_address
        
        try:
            # Use the new multi-provider geocoding manager
            geocoding_manager = get_geocoding_manager()
            address = geocoding_manager.get_address_from_coordinates(latitude, longitude)
            
            if address:
                formatted_address = self._format_address(address)
                
                # Cache successful result in SQL database for 30 days
                if use_cache:
                    db.cache_address(latitude, longitude, formatted_address, cache_days=30)
                
                return formatted_address
            else:
                # Fallback address when no geocoding providers succeed
                fallback_address = f"Unknown Location ({latitude:.4f}, {longitude:.4f})"
                if use_cache:
                    db.cache_address(latitude, longitude, fallback_address, cache_days=7)
                return fallback_address
                
        except Exception as e:
            logger.error(f"Error in multi-provider geocoding: {e}")
            fallback_address = f"Error ({latitude:.4f}, {longitude:.4f})"
            if use_cache:
                db.cache_address(latitude, longitude, fallback_address, cache_days=0.25)
            return fallback_address
    
    def _format_address(self, raw_address: str) -> str:
        """Format and clean up address string"""
        # Remove country if it's USA
        address = raw_address.replace(", United States", "")
        
        # Split by comma and take first 3-4 meaningful parts
        parts = [part.strip() for part in address.split(',')]
        if len(parts) > 4:
            # Take house number + street, city, state, zip
            address = ', '.join(parts[:2] + parts[-2:])
        
        return address
    
    def group_locations_by_address(self, locations: List[Dict], distance_threshold: float = 0.0005) -> Dict:
        """Group locations by address with smart clustering"""
        address_groups = defaultdict(list)
        processed_coords = set()
        
        for location in locations:
            lat = float(location['latitude'])
            lng = float(location['longitude'])
            coord_key = f"{lat:.4f},{lng:.4f}"
            
            # Skip if we've already processed very similar coordinates
            if coord_key in processed_coords:
                continue
                
            # Find if this location is close to any existing group
            found_group = None
            for existing_address, group_locations in address_groups.items():
                if group_locations:
                    existing_lat = float(group_locations[0]['latitude'])
                    existing_lng = float(group_locations[0]['longitude'])
                    
                    # Calculate distance
                    distance = geodesic((lat, lng), (existing_lat, existing_lng)).kilometers
                    
                    if distance < 0.05:  # 50 meters threshold
                        found_group = existing_address
                        break
            
            if found_group:
                address_groups[found_group].append(location)
            else:
                # Get address for this location
                address = self.get_address_from_coordinates(lat, lng)
                address_groups[address].append(location)
            
            processed_coords.add(coord_key)
        
        return dict(address_groups)
    
    def calculate_time_spent_at_location(self, locations: List[Dict]) -> Dict:
        """Calculate time spent at each grouped location"""
        if len(locations) < 2:
            return {"total_time": 0, "visit_count": len(locations), "avg_time": 0}
        
        # Sort by timestamp
        sorted_locations = sorted(locations, key=lambda x: x['timestamp'])
        
        total_time = 0
        for i in range(1, len(sorted_locations)):
            try:
                time1 = datetime.fromisoformat(sorted_locations[i-1]['timestamp'].replace('Z', '+00:00'))
                time2 = datetime.fromisoformat(sorted_locations[i]['timestamp'].replace('Z', '+00:00'))
                time_diff = abs((time2 - time1).total_seconds() / 60)  # minutes
                
                # Only count if time difference is reasonable (< 4 hours)
                if time_diff < 240:
                    total_time += time_diff
            except Exception as e:
                logger.warning(f"Error calculating time difference: {e}")
                continue
        
        return {
            "total_time": total_time,
            "visit_count": len(locations),
            "avg_time": total_time / len(locations) if locations else 0
        }
    
    def get_device_analytics(self, device_name: str, start_date: str, end_date: Optional[str] = None) -> Dict:
        """Get comprehensive analytics for a device on a specific date"""
        if not end_date:
            # Default to 24 hours from start_date
            start_dt = datetime.fromisoformat(start_date + "T00:00:00")
            end_dt = start_dt + timedelta(hours=24)
            end_date = end_dt.isoformat()
        
        # Get locations for the date range
        locations = db.get_locations(
            start_time=start_date,
            end_time=end_date,
            device_name=device_name,
            limit=1000
        )
        
        if not locations:
            return {"error": "No location data found for this device and date range"}
        
        # Group locations by address
        address_groups = self.group_locations_by_address(locations)
        
        # Calculate analytics for each location
        location_analytics = []
        total_distance = 0
        
        for address, group_locations in address_groups.items():
            time_stats = self.calculate_time_spent_at_location(group_locations)
            
            # Get representative coordinates (average of the group)
            avg_lat = statistics.mean(float(loc['latitude']) for loc in group_locations)
            avg_lng = statistics.mean(float(loc['longitude']) for loc in group_locations)
            
            # Get first and last visit times
            timestamps = [loc['timestamp'] for loc in group_locations]
            timestamps.sort()
            
            location_analytics.append({
                "address": address,
                "latitude": avg_lat,
                "longitude": avg_lng,
                "visit_count": len(group_locations),
                "total_time_minutes": round(time_stats["total_time"], 1),
                "avg_time_minutes": round(time_stats["avg_time"], 1),
                "first_visit": timestamps[0],
                "last_visit": timestamps[-1],
                "locations": group_locations
            })
        
        # Calculate total distance traveled
        if len(locations) > 1:
            sorted_locs = sorted(locations, key=lambda x: x['timestamp'])
            for i in range(1, len(sorted_locs)):
                prev_loc = sorted_locs[i-1]
                curr_loc = sorted_locs[i]
                
                distance = geodesic(
                    (float(prev_loc['latitude']), float(prev_loc['longitude'])),
                    (float(curr_loc['latitude']), float(curr_loc['longitude']))
                ).kilometers
                
                # Only count reasonable distances (< 100km between points)
                if distance < 100:
                    total_distance += distance
        
        # Sort locations by visit count (most visited first)
        location_analytics.sort(key=lambda x: x['visit_count'], reverse=True)
        
        return {
            "device_name": device_name,
            "date_range": f"{start_date} to {end_date}",
            "total_locations": len(locations),
            "unique_addresses": len(location_analytics),
            "total_distance_km": round(total_distance, 2),
            "total_distance_miles": round(total_distance * 0.621371, 2),
            "location_analytics": location_analytics,
            "raw_locations": locations
        }
    
    def get_device_summary_stats(self, device_name: str, days: int = 7) -> Dict:
        """Get summary statistics for a device over the last N days"""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        locations = db.get_locations(
            start_time=start_date.isoformat(),
            end_time=end_date.isoformat(),
            device_name=device_name,
            limit=5000
        )
        
        if not locations:
            return {
                "device_name": device_name,
                "period_days": days,
                "total_tracking_points": 0,
                "daily_analytics": [],
                "avg_daily_points": 0,
                "avg_daily_distance": 0,
                "weekly_top_locations": [],
                "overall_top_locations": [],
                "error": "No location data found"
            }
        
        # Group by day
        daily_stats = defaultdict(list)
        for loc in locations:
            try:
                date_key = loc['timestamp'][:10]  # YYYY-MM-DD
                daily_stats[date_key].append(loc)
            except:
                continue
        
        # Calculate stats per day
        daily_analytics = []
        for date_key, day_locations in daily_stats.items():
            address_groups = self.group_locations_by_address(day_locations)
            
            total_distance = 0
            if len(day_locations) > 1:
                sorted_locs = sorted(day_locations, key=lambda x: x['timestamp'])
                for i in range(1, len(sorted_locs)):
                    prev_loc = sorted_locs[i-1]
                    curr_loc = sorted_locs[i]
                    
                    distance = geodesic(
                        (float(prev_loc['latitude']), float(prev_loc['longitude'])),
                        (float(curr_loc['latitude']), float(curr_loc['longitude']))
                    ).kilometers
                    
                    if distance < 100:
                        total_distance += distance
            
            daily_analytics.append({
                "date": date_key,
                "total_points": len(day_locations),
                "unique_locations": len(address_groups),
                "distance_km": round(total_distance, 2),
                "most_visited": max(address_groups.keys(), key=lambda x: len(address_groups[x])) if address_groups else "Unknown"
            })
        
        daily_analytics.sort(key=lambda x: x['date'], reverse=True)
        
        # Get top visited locations for the period and overall
        try:
            weekly_top_locations = self.get_top_visited_locations(device_name, days=days, limit=10)
        except Exception as e:
            logger.error(f"Error getting weekly top locations: {e}")
            weekly_top_locations = []
        
        try:
            overall_top_locations = self.get_top_visited_locations(device_name, days=None, limit=10)
        except Exception as e:
            logger.error(f"Error getting overall top locations: {e}")
            overall_top_locations = []
        
        return {
            "device_name": device_name,
            "period_days": days,
            "total_tracking_points": len(locations),
            "daily_analytics": daily_analytics,
            "avg_daily_points": len(locations) / len(daily_stats) if daily_stats else 0,
            "avg_daily_distance": sum(day['distance_km'] for day in daily_analytics) / len(daily_analytics) if daily_analytics else 0,
            "weekly_top_locations": weekly_top_locations,
            "overall_top_locations": overall_top_locations
        }
    
    def get_top_visited_locations(self, device_name: str, days: int = None, limit: int = 10) -> List[Dict]:
        """Get top visited locations with time spent analysis"""
        try:
            # Determine date range
            if days:
                end_date = datetime.now()
                start_date = end_date - timedelta(days=days)
                locations = db.get_locations(
                    start_time=start_date.isoformat(),
                    end_time=end_date.isoformat(),
                    device_name=device_name,
                    limit=10000
                )
            else:
                # Get all-time data
                locations = db.get_locations(
                    device_name=device_name,
                    limit=10000
                )
            
            if not locations:
                return []
            
            # Group locations by address and calculate visit statistics
            address_stats = defaultdict(lambda: {
                'visit_count': 0,
                'total_time_minutes': 0,
                'coordinates': [],
                'timestamps': [],
                'first_visit': None,
                'last_visit': None
            })
            
            # Group by address using existing clustering logic
            try:
                address_groups = self.group_locations_by_address(locations)
            except Exception as e:
                logger.error(f"Error grouping locations by address: {e}")
                return []
            
            for address, group_locations in address_groups.items():
                if not group_locations:
                    continue
                    
                # Sort by timestamp for time analysis
                sorted_locs = sorted(group_locations, key=lambda x: x['timestamp'])
                
                # Calculate visit sessions (gaps > 30 minutes = new visit)
                visit_sessions = []
                current_session = [sorted_locs[0]]
                
                for i in range(1, len(sorted_locs)):
                    prev_time = datetime.fromisoformat(sorted_locs[i-1]['timestamp'].replace('Z', '+00:00'))
                    curr_time = datetime.fromisoformat(sorted_locs[i]['timestamp'].replace('Z', '+00:00'))
                    
                    # If gap is more than 30 minutes, start new session
                    if (curr_time - prev_time).total_seconds() > 1800:  # 30 minutes
                        visit_sessions.append(current_session)
                        current_session = [sorted_locs[i]]
                    else:
                        current_session.append(sorted_locs[i])
                
                # Add the last session
                if current_session:
                    visit_sessions.append(current_session)
                
                # Calculate total time spent
                total_time_minutes = 0
                for session in visit_sessions:
                    if len(session) > 1:
                        start_time = datetime.fromisoformat(session[0]['timestamp'].replace('Z', '+00:00'))
                        end_time = datetime.fromisoformat(session[-1]['timestamp'].replace('Z', '+00:00'))
                        session_duration = (end_time - start_time).total_seconds() / 60
                        # Cap individual session time at 8 hours to avoid outliers
                        total_time_minutes += min(session_duration, 480)
                    else:
                        # Single point visits count as 5 minutes minimum
                        total_time_minutes += 5
                
                # Get representative coordinates (center of cluster)
                avg_lat = sum(float(loc['latitude']) for loc in group_locations) / len(group_locations)
                avg_lng = sum(float(loc['longitude']) for loc in group_locations) / len(group_locations)
                
                address_stats[address] = {
                    'visit_count': len(visit_sessions),
                    'total_time_minutes': round(total_time_minutes, 1),
                    'latitude': avg_lat,
                    'longitude': avg_lng,
                    'first_visit': sorted_locs[0]['timestamp'],
                    'last_visit': sorted_locs[-1]['timestamp'],
                    'total_points': len(group_locations)
                }
            
            # Sort by visit count and then by time spent
            top_locations = []
            for address, stats in address_stats.items():
                top_locations.append({
                    'address': address,
                    'visit_count': stats['visit_count'],
                    'total_time_minutes': stats['total_time_minutes'],
                    'total_time_hours': round(stats['total_time_minutes'] / 60, 1),
                    'latitude': stats['latitude'],
                    'longitude': stats['longitude'],
                    'first_visit': stats['first_visit'],
                    'last_visit': stats['last_visit'],
                    'total_points': stats['total_points'],
                    'avg_time_per_visit': round(stats['total_time_minutes'] / stats['visit_count'], 1) if stats['visit_count'] > 0 else 0
                })
            
            # Sort by visit count (primary) and total time (secondary)
            top_locations.sort(key=lambda x: (x['visit_count'], x['total_time_minutes']), reverse=True)
            
            return top_locations[:limit]
            
        except Exception as e:
            import traceback
            logger.error(f"Error getting top visited locations: {e}")
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return []
    
    def get_geocoding_status(self) -> Dict:
        """Get status of geocoding providers"""
        try:
            geocoding_manager = get_geocoding_manager()
            return {
                'provider_status': geocoding_manager.get_provider_status(),
                'stats': geocoding_manager.get_stats()
            }
        except Exception as e:
            logger.error(f"Error getting geocoding status: {e}")
            return {'error': str(e)}
    
    def generate_heatmap_data(self, device_name: str = None, days: int = 30) -> List[Tuple[float, float, int]]:
        """Generate heatmap data for frequently visited areas"""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        locations = db.get_locations(
            start_time=start_date.isoformat(),
            end_time=end_date.isoformat(),
            device_name=device_name,
            limit=10000
        )
        
        if not locations:
            return []
        
        # Group locations by proximity to create heat intensity
        heat_points = defaultdict(int)
        grid_size = 0.001  # ~100 meter grid
        
        for location in locations:
            lat = float(location['latitude'])
            lng = float(location['longitude'])
            
            # Round to grid
            grid_lat = round(lat / grid_size) * grid_size
            grid_lng = round(lng / grid_size) * grid_size
            
            heat_points[(grid_lat, grid_lng)] += 1
        
        # Convert to format expected by folium HeatMap: [lat, lng, weight]
        heatmap_data = []
        for (lat, lng), count in heat_points.items():
            # Apply logarithmic scaling for better visualization
            intensity = min(count * 2, 50)  # Cap at 50 for reasonable visualization
            heatmap_data.append([lat, lng, intensity])
        
        return heatmap_data
    
    def create_heatmap_html(self, device_name: str = None, days: int = 30) -> str:
        """Create a folium heatmap and return HTML content"""
        heatmap_data = self.generate_heatmap_data(device_name, days)
        
        if not heatmap_data:
            return self._create_no_data_map()
        
        # Calculate center point
        center_lat = sum(point[0] for point in heatmap_data) / len(heatmap_data)
        center_lng = sum(point[1] for point in heatmap_data) / len(heatmap_data)
        
        # Create folium map
        m = folium.Map(
            location=[center_lat, center_lng],
            zoom_start=12,
            tiles='OpenStreetMap'
        )
        
        # Add custom tiles for better visualization
        folium.TileLayer(
            tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
            attr='Esri',
            name='Satellite',
        ).add_to(m)
        
        # Create heatmap layer
        HeatMap(
            heatmap_data,
            min_opacity=0.3,
            max_zoom=18,
            radius=25,
            blur=15,
            gradient={
                0.0: 'blue',
                0.3: 'cyan', 
                0.5: 'lime',
                0.7: 'yellow',
                1.0: 'red'
            }
        ).add_to(m)
        
        # Add layer control
        folium.LayerControl().add_to(m)
        
        # Add title and info
        title_html = f'''
        <div style="position: fixed; 
                    top: 10px; left: 50px; width: 300px; height: 60px; 
                    background-color: white; border:2px solid grey; z-index:9999; 
                    font-size:16px; font-weight: bold; padding: 10px; border-radius: 10px;
                    box-shadow: 0 0 15px rgba(0,0,0,0.2);">
        <p style="margin: 0; color: #333;">🔥 Location Heatmap</p>
        <p style="margin: 0; font-size: 12px; color: #666;">
            {f"Device: {device_name}" if device_name else "All Devices"} | Last {days} days
        </p>
        </div>
        '''
        m.get_root().html.add_child(folium.Element(title_html))
        
        # Convert to HTML string
        return m._repr_html_()
    
    def _create_no_data_map(self) -> str:
        """Create a map showing no data available"""
        m = folium.Map(
            location=[37.7749, -122.4194],  # Default to San Francisco
            zoom_start=10,
            tiles='OpenStreetMap'
        )
        
        # Add message popup
        folium.Marker(
            [37.7749, -122.4194],
            popup=folium.Popup("No location data available for heatmap", max_width=250),
            icon=folium.Icon(color='red', icon='info-sign')
        ).add_to(m)
        
        title_html = '''
        <div style="position: fixed; 
                    top: 10px; left: 50px; width: 300px; height: 60px; 
                    background-color: white; border:2px solid grey; z-index:9999; 
                    font-size:16px; font-weight: bold; padding: 10px; border-radius: 10px;
                    box-shadow: 0 0 15px rgba(0,0,0,0.2);">
        <p style="margin: 0; color: #333;">🔥 Location Heatmap</p>
        <p style="margin: 0; font-size: 12px; color: #666;">No data available</p>
        </div>
        '''
        m.get_root().html.add_child(folium.Element(title_html))
        
        return m._repr_html_()
    
    def get_heatmap_stats(self, device_name: str = None, days: int = 30) -> Dict:
        """Get statistics about the heatmap data"""
        heatmap_data = self.generate_heatmap_data(device_name, days)
        
        if not heatmap_data:
            return {"error": "No data available"}
        
        # Calculate statistics
        intensities = [point[2] for point in heatmap_data]
        total_points = len(heatmap_data)
        total_intensity = sum(intensities)
        avg_intensity = total_intensity / total_points
        max_intensity = max(intensities)
        
        # Find hottest spots (top 5)
        sorted_points = sorted(heatmap_data, key=lambda x: x[2], reverse=True)
        hotspots = []
        
        for i, (lat, lng, intensity) in enumerate(sorted_points[:5]):
            address = self.get_address_from_coordinates(lat, lng)
            hotspots.append({
                "rank": i + 1,
                "latitude": lat,
                "longitude": lng,
                "intensity": intensity,
                "address": address
            })
        
        return {
            "device_name": device_name or "All Devices",
            "period_days": days,
            "total_heat_points": total_points,
            "total_intensity": total_intensity,
            "avg_intensity": round(avg_intensity, 2),
            "max_intensity": max_intensity,
            "hotspots": hotspots
        }
    
    def get_historical_playback_data(self, device_name: str = None, start_date: str = None, end_date: str = None) -> Dict:
        """Get location data formatted for historical playback animation"""
        # Default to last 24 hours if no dates provided
        if not end_date:
            end_dt = datetime.now()
            end_date = end_dt.isoformat()
        
        if not start_date:
            start_dt = datetime.fromisoformat(end_date) - timedelta(hours=24)
            start_date = start_dt.isoformat()
        
        # Get locations for the time range
        locations = db.get_locations(
            start_time=start_date,
            end_time=end_date,
            device_name=device_name,
            limit=5000
        )
        
        if not locations:
            return {"error": "No location data found for playback"}
        
        # Group by device and sort by timestamp
        device_tracks = defaultdict(list)
        
        for location in locations:
            try:
                # Parse timestamp
                timestamp = location['timestamp']
                if isinstance(timestamp, str):
                    if timestamp.endswith('Z'):
                        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    else:
                        dt = datetime.fromisoformat(timestamp)
                else:
                    dt = timestamp
                
                # Convert to CST for display
                if dt.tzinfo is None:
                    dt = pytz.UTC.localize(dt)
                cst_dt = dt.astimezone(self.timezone)
                
                device_tracks[location['device_name']].append({
                    'latitude': float(location['latitude']),
                    'longitude': float(location['longitude']),
                    'timestamp': location['timestamp'],
                    'timestamp_cst': cst_dt.strftime('%Y-%m-%d %I:%M:%S %p CST'),
                    'device_name': location['device_name'],
                    'unix_timestamp': int(dt.timestamp())
                })
            except Exception as e:
                logger.warning(f"Error processing location for playback: {e}")
                continue
        
        # Sort each device's track by timestamp
        for device in device_tracks:
            device_tracks[device].sort(key=lambda x: x['unix_timestamp'])
        
        # Calculate playback statistics
        all_points = []
        for device, points in device_tracks.items():
            all_points.extend(points)
        
        all_points.sort(key=lambda x: x['unix_timestamp'])
        
        # Calculate time span and suggested playback speed
        if len(all_points) >= 2:
            time_span_hours = (all_points[-1]['unix_timestamp'] - all_points[0]['unix_timestamp']) / 3600
            # Suggest speed to make playback ~30-60 seconds
            suggested_speed = max(1, int(time_span_hours * 60 / 45))  # seconds real time per second playback
        else:
            time_span_hours = 0
            suggested_speed = 1
        
        # Calculate center point for map
        if all_points:
            center_lat = statistics.mean(point['latitude'] for point in all_points)
            center_lng = statistics.mean(point['longitude'] for point in all_points)
        else:
            center_lat, center_lng = 37.7749, -122.4194  # Default to SF
        
        return {
            "device_tracks": dict(device_tracks),
            "all_points_chronological": all_points,
            "total_points": len(all_points),
            "device_count": len(device_tracks),
            "time_span_hours": round(time_span_hours, 1),
            "suggested_speed": suggested_speed,
            "start_time": all_points[0]['timestamp_cst'] if all_points else None,
            "end_time": all_points[-1]['timestamp_cst'] if all_points else None,
            "center_lat": center_lat,
            "center_lng": center_lng,
            "date_range": f"{start_date[:10]} to {end_date[:10]}"
        }
    
    def get_playback_timeline_data(self, device_name: str = None, start_date: str = None, end_date: str = None) -> List[Dict]:
        """Get simplified timeline data for playback scrubber"""
        playback_data = self.get_historical_playback_data(device_name, start_date, end_date)
        
        if 'error' in playback_data:
            return []
        
        timeline_points = []
        all_points = playback_data['all_points_chronological']
        
        # Sample points for timeline (max 100 points for performance)
        if len(all_points) > 100:
            step = len(all_points) // 100
            sampled_points = all_points[::step]
        else:
            sampled_points = all_points
        
        for i, point in enumerate(sampled_points):
            timeline_points.append({
                'index': i,
                'timestamp': point['timestamp_cst'],
                'unix_timestamp': point['unix_timestamp'],
                'device_name': point['device_name'],
                'latitude': point['latitude'],
                'longitude': point['longitude']
            })
        
        return timeline_points
    
    def create_geofence(self, name: str, center_lat: float, center_lng: float, radius_meters: int, 
                       device_filter: str = None, alert_types: list = None) -> Dict:
        """Create a geofence boundary"""
        if alert_types is None:
            alert_types = ['enter', 'exit']
        
        geofence_data = {
            'name': name,
            'center_lat': center_lat,
            'center_lng': center_lng,
            'radius_meters': radius_meters,
            'device_filter': device_filter,
            'alert_types': alert_types,
            'created_at': datetime.now().isoformat(),
            'is_active': True
        }
        
        # Store in database
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO geofences (name, center_lat, center_lng, radius_meters, 
                                         device_filter, alert_types, created_at, is_active)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ''', (name, center_lat, center_lng, radius_meters, 
                      device_filter, ','.join(alert_types), geofence_data['created_at'], True))
                
                geofence_id = cursor.lastrowid
                geofence_data['id'] = geofence_id
                
                db.log_message("INFO", f"Created geofence '{name}' with radius {radius_meters}m", "geofencing")
                return geofence_data
                
        except Exception as e:
            logger.error(f"Error creating geofence: {e}")
            return {"error": f"Failed to create geofence: {e}"}
    
    def get_geofences(self, include_inactive: bool = False) -> List[Dict]:
        """Get all geofences"""
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                
                if include_inactive:
                    cursor.execute('SELECT * FROM geofences ORDER BY created_at DESC')
                else:
                    cursor.execute('SELECT * FROM geofences WHERE is_active = TRUE ORDER BY created_at DESC')
                
                geofences = []
                for row in cursor.fetchall():
                    geofence = dict(row)
                    # Parse alert_types back to list
                    if geofence['alert_types']:
                        geofence['alert_types'] = geofence['alert_types'].split(',')
                    else:
                        geofence['alert_types'] = []
                    geofences.append(geofence)
                
                return geofences
                
        except Exception as e:
            logger.error(f"Error getting geofences: {e}")
            return []
    
    def check_geofence_violations(self, device_name: str, latitude: float, longitude: float) -> List[Dict]:
        """Check if a location violates any geofences and generate alerts"""
        violations = []
        geofences = self.get_geofences()
        
        for geofence in geofences:
            # Skip if device filter doesn't match
            if geofence['device_filter'] and geofence['device_filter'] != device_name:
                continue
            
            # Calculate distance from geofence center
            distance_km = geodesic(
                (latitude, longitude),
                (geofence['center_lat'], geofence['center_lng'])
            ).kilometers
            
            distance_meters = distance_km * 1000
            is_inside = distance_meters <= geofence['radius_meters']
            
            # Check device's last known status for this geofence
            last_status = self._get_device_geofence_status(device_name, geofence['id'])
            
            logger.debug(f"Geofence check: {device_name} at {geofence['name']} - "
                        f"currently_inside: {is_inside}, was_inside: {last_status['was_inside']}, "
                        f"distance: {distance_meters:.1f}m")
            
            # Determine if this is an entry or exit event
            violation = None
            if is_inside and not last_status['was_inside']:
                # Device just entered the geofence
                if 'enter' in geofence['alert_types']:
                    logger.info(f"GEOFENCE ENTRY: {device_name} entered {geofence['name']}")
                    violation = {
                        'type': 'enter',
                        'geofence': geofence,
                        'device_name': device_name,
                        'latitude': latitude,
                        'longitude': longitude,
                        'distance_meters': round(distance_meters, 1),
                        'timestamp': datetime.now().isoformat()
                    }
            elif not is_inside and last_status['was_inside']:
                # Device just exited the geofence
                if 'exit' in geofence['alert_types']:
                    logger.info(f"GEOFENCE EXIT: {device_name} exited {geofence['name']}")
                    violation = {
                        'type': 'exit',
                        'geofence': geofence,
                        'device_name': device_name,
                        'latitude': latitude,
                        'longitude': longitude,
                        'distance_meters': round(distance_meters, 1),
                        'timestamp': datetime.now().isoformat()
                    }
            
            if violation:
                violations.append(violation)
                self._log_geofence_event(violation)
                
                # Trigger notifications for this violation
                self.trigger_notifications(violation)
            
            # Update device status for this geofence
            self._update_device_geofence_status(device_name, geofence['id'], is_inside)
        
        return violations
    
    def _get_device_geofence_status(self, device_name: str, geofence_id: int) -> Dict:
        """Get the last known status of a device for a specific geofence"""
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT is_inside FROM device_geofence_status 
                    WHERE device_name = %s AND geofence_id = %s
                ''', (device_name, geofence_id))
                
                row = cursor.fetchone()
                if row:
                    return {'was_inside': bool(row['is_inside'])}
                else:
                    return {'was_inside': False}  # Default: device was outside
                    
        except Exception as e:
            logger.error(f"Error getting device geofence status: {e}")
            return {'was_inside': False}
    
    def _update_device_geofence_status(self, device_name: str, geofence_id: int, is_inside: bool):
        """Update device status for a specific geofence"""
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                # Use MySQL's INSERT ... ON DUPLICATE KEY UPDATE syntax
                cursor.execute('''
                    INSERT INTO device_geofence_status 
                    (device_name, geofence_id, is_inside, last_updated)
                    VALUES (%s, %s, %s, NOW())
                    ON DUPLICATE KEY UPDATE 
                    is_inside = VALUES(is_inside),
                    last_updated = NOW()
                ''', (device_name, geofence_id, int(is_inside)))
                
                logger.debug(f"Updated geofence status: {device_name} - geofence {geofence_id} - inside: {is_inside}")
                
        except Exception as e:
            logger.error(f"Error updating device geofence status: {e}")
    
    def _log_geofence_event(self, violation: Dict):
        """Log a geofence violation event"""
        try:
            event_type = violation['type'].upper()
            geofence_name = violation['geofence']['name']
            device_name = violation['device_name']
            
            message = f"Device '{device_name}' {event_type} geofence '{geofence_name}'"
            
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO geofence_events 
                    (device_name, geofence_id, event_type, latitude, longitude, distance_meters, timestamp)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                ''', (
                    device_name,
                    violation['geofence']['id'],
                    event_type,
                    violation['latitude'],
                    violation['longitude'],
                    violation['distance_meters'],
                    violation['timestamp']
                ))
            
            db.log_message("INFO", message, "geofencing")
            logger.info(f"Geofence event logged: {message}")
            
        except Exception as e:
            logger.error(f"Error logging geofence event: {e}")
    
    def get_geofence_events(self, device_name: str = None, geofence_id: int = None, 
                           limit: int = 100) -> List[Dict]:
        """Get geofence events history"""
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                
                query = '''
                    SELECT ge.*, g.name as geofence_name, g.radius_meters
                    FROM geofence_events ge
                    LEFT JOIN geofences g ON ge.geofence_id = g.id
                    WHERE 1=1
                '''
                params = []
                
                if device_name:
                    query += ' AND ge.device_name = ?'
                    params.append(device_name)
                
                if geofence_id:
                    query += ' AND ge.geofence_id = ?'
                    params.append(geofence_id)
                
                query += ' ORDER BY ge.timestamp DESC LIMIT ?'
                params.append(limit)
                
                cursor.execute(query, params)
                
                events = []
                for row in cursor.fetchall():
                    event = dict(row)
                    events.append(event)
                
                return events
                
        except Exception as e:
            logger.error(f"Error getting geofence events: {e}")
            return []
    
    def delete_geofence(self, geofence_id: int) -> bool:
        """Delete a geofence (soft delete by marking inactive)"""
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('UPDATE geofences SET is_active = FALSE WHERE id = %s', (geofence_id,))
                
                if cursor.rowcount > 0:
                    db.log_message("INFO", f"Deleted geofence ID {geofence_id}", "geofencing")
                    return True
                else:
                    return False
                    
        except Exception as e:
            logger.error(f"Error deleting geofence: {e}")
            return False
    
    def create_notification_rule(self, name: str, trigger_type: str, geofence_id: int = None, 
                                device_filter: str = None, notification_methods: list = None) -> Dict:
        """Create a notification rule for arrival/departure events"""
        if notification_methods is None:
            notification_methods = ['log']  # Default to logging
        
        rule_data = {
            'name': name,
            'trigger_type': trigger_type,  # 'arrival', 'departure', 'both'
            'geofence_id': geofence_id,
            'device_filter': device_filter,
            'notification_methods': notification_methods,  # ['log', 'email', 'webhook']
            'created_at': datetime.now().isoformat(),
            'is_active': True
        }
        
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO notification_rules 
                    (name, trigger_type, geofence_id, device_filter, notification_methods, created_at, is_active)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                ''', (name, trigger_type, geofence_id, device_filter, 
                      ','.join(notification_methods), rule_data['created_at'], 1))
                
                rule_id = cursor.lastrowid
                rule_data['id'] = rule_id
                
                db.log_message("INFO", f"Created notification rule '{name}' for {trigger_type}", "notifications")
                return rule_data
                
        except Exception as e:
            logger.error(f"Error creating notification rule: {e}")
            return {"error": f"Failed to create notification rule: {e}"}
    
    def get_notification_rules(self, include_inactive: bool = False) -> List[Dict]:
        """Get all notification rules"""
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                
                query = '''
                    SELECT nr.*, g.name as geofence_name, g.center_lat, g.center_lng, g.radius_meters
                    FROM notification_rules nr
                    LEFT JOIN geofences g ON nr.geofence_id = g.id
                '''
                
                if not include_inactive:
                    query += ' WHERE nr.is_active = 1'
                
                query += ' ORDER BY nr.created_at DESC'
                
                cursor.execute(query)
                
                rules = []
                for row in cursor.fetchall():
                    rule = dict(row)
                    # Parse notification_methods back to list
                    if rule['notification_methods']:
                        rule['notification_methods'] = rule['notification_methods'].split(',')
                    else:
                        rule['notification_methods'] = []
                    rules.append(rule)
                
                return rules
                
        except Exception as e:
            logger.error(f"Error getting notification rules: {e}")
            return []
    
    def trigger_notifications(self, violation: Dict):
        """Trigger notifications based on geofence violations"""
        try:
            geofence_id = violation['geofence']['id']
            event_type = violation['type']  # 'enter' or 'exit'
            device_name = violation['device_name']
            
            # Get matching notification rules
            rules = self.get_notification_rules()
            matching_rules = []
            
            for rule in rules:
                # Check if rule applies to this geofence
                if rule['geofence_id'] and rule['geofence_id'] != geofence_id:
                    continue
                
                # Check if rule applies to this device
                if rule['device_filter'] and rule['device_filter'] != device_name:
                    continue
                
                # Check if rule applies to this trigger type
                trigger_type = rule['trigger_type']
                if trigger_type == 'arrival' and event_type != 'enter':
                    continue
                elif trigger_type == 'departure' and event_type != 'exit':
                    continue
                
                matching_rules.append(rule)
            
            # Send notifications for matching rules
            for rule in matching_rules:
                self._send_notification(rule, violation)
                
            logger.info(f"Processed {len(matching_rules)} notification rules for {event_type} event")
            
        except Exception as e:
            logger.error(f"Error triggering notifications: {e}")
    
    def _send_notification(self, rule: Dict, violation: Dict):
        """Send a notification based on the rule and violation"""
        try:
            # Build notification message
            event_type = "arrived at" if violation['type'] == 'enter' else "left"
            geofence_name = violation['geofence']['name']
            device_name = violation['device_name']
            timestamp = violation['timestamp']
            
            message = f"🔔 {device_name} has {event_type} {geofence_name}"
            detailed_message = f"{message} at {datetime.fromisoformat(timestamp).strftime('%I:%M %p CST')}"
            
            # Send via each notification method
            for method in rule['notification_methods']:
                if method == 'log':
                    logger.info(f"NOTIFICATION: {detailed_message}")
                    db.log_message("INFO", f"NOTIFICATION: {detailed_message}", "notifications")
                
                elif method == 'browser':
                    self._send_browser_notification(rule['id'], violation, message)
                
                elif method == 'email':
                    self._send_email_notification(rule, detailed_message, violation)
                
                elif method == 'webhook':
                    self._send_webhook_notification(rule, detailed_message, violation)
            
            # Log the notification (for audit trail)
            self._log_notification(rule['id'], violation, message)
            
        except Exception as e:
            logger.error(f"Error sending notification: {e}")
    
    def _send_email_notification(self, rule: Dict, message: str, violation: Dict):
        """Send email notification (placeholder for future implementation)"""
        # TODO: Implement email sending with SMTP
        logger.info(f"EMAIL NOTIFICATION (not implemented): {message}")
    
    def _send_webhook_notification(self, rule: Dict, message: str, violation: Dict):
        """Send webhook notification (placeholder for future implementation)"""
        # TODO: Implement webhook POST request
        logger.info(f"WEBHOOK NOTIFICATION (not implemented): {message}")
    
    def _send_browser_notification(self, rule_id: int, violation: Dict, message: str):
        """Send in-browser notification"""
        try:
            # Determine priority based on violation type and rule settings
            priority = 'high' if violation['type'].upper() in ['ENTRY', 'EXIT'] else 'normal'
            
            # Create browser notification using new system
            db.create_notification(
                device_name=violation['device_name'],
                message=message,
                notification_type='geofence',
                priority=priority,
                rule_id=rule_id,
                geofence_id=violation['geofence']['id'],
                event_type=violation['type'].lower()
            )
            
            logger.info(f"BROWSER NOTIFICATION: {message}")
                
        except Exception as e:
            logger.error(f"Error sending browser notification: {e}")
    
    def _log_notification(self, rule_id: int, violation: Dict, message: str):
        """Log sent notification for audit trail"""
        try:
            # Log notification to sent_notifications table for audit purposes
            # (This is separate from browser notifications and is always logged)
            db.log_message("INFO", f"Notification sent for rule {rule_id}: {message}", "notifications")
                
        except Exception as e:
            logger.error(f"Error logging notification: {e}")
    
    def get_recent_notifications(self, limit: int = 50) -> List[Dict]:
        """Get recent sent notifications"""
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT sn.*, nr.name as rule_name, g.name as geofence_name
                    FROM sent_notifications sn
                    LEFT JOIN notification_rules nr ON sn.rule_id = nr.id
                    LEFT JOIN geofences g ON sn.geofence_id = g.id
                    ORDER BY sn.timestamp DESC
                    LIMIT ?
                ''', (limit,))
                
                notifications = []
                for row in cursor.fetchall():
                    notifications.append(dict(row))
                
                return notifications
                
        except Exception as e:
            logger.error(f"Error getting recent notifications: {e}")
            return []
    
    def delete_notification_rule(self, rule_id: int) -> bool:
        """Delete a notification rule (soft delete)"""
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('UPDATE notification_rules SET is_active = FALSE WHERE id = %s', (rule_id,))
                
                if cursor.rowcount > 0:
                    db.log_message("INFO", f"Deleted notification rule ID {rule_id}", "notifications")
                    return True
                else:
                    return False
                    
        except Exception as e:
            logger.error(f"Error deleting notification rule: {e}")
            return False
    
    def create_bookmark(self, name: str, latitude: float, longitude: float, address: str = None, 
                       description: str = None, category: str = 'general') -> Dict:
        """Create a location bookmark"""
        bookmark_data = {
            'name': name,
            'latitude': latitude,
            'longitude': longitude,
            'address': address or self.get_address_from_coordinates(latitude, longitude),
            'description': description,
            'category': category,
            'created_at': datetime.now().isoformat(),
            'is_active': True
        }
        
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO bookmarks (name, latitude, longitude, address, description, category, created_at, is_active)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ''', (name, latitude, longitude, bookmark_data['address'], description, 
                      category, bookmark_data['created_at'], 1))
                
                bookmark_id = cursor.lastrowid
                bookmark_data['id'] = bookmark_id
                
                db.log_message("INFO", f"Created bookmark '{name}' at {latitude}, {longitude}", "bookmarks")
                return bookmark_data
                
        except Exception as e:
            logger.error(f"Error creating bookmark: {e}")
            return {"error": f"Failed to create bookmark: {e}"}
    
    def get_bookmarks(self, category: str = None, include_inactive: bool = False) -> List[Dict]:
        """Get all bookmarks"""
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                
                query = 'SELECT * FROM bookmarks'
                params = []
                conditions = []
                
                if not include_inactive:
                    conditions.append('is_active = 1')
                
                if category:
                    conditions.append('category = ?')
                    params.append(category)
                
                if conditions:
                    query += ' WHERE ' + ' AND '.join(conditions)
                
                query += ' ORDER BY created_at DESC'
                
                cursor.execute(query, params)
                
                bookmarks = []
                for row in cursor.fetchall():
                    bookmarks.append(dict(row))
                
                return bookmarks
                
        except Exception as e:
            logger.error(f"Error getting bookmarks: {e}")
            return []
    
    def search_locations(self, query: str, device_name: str = None, 
                        start_date: str = None, end_date: str = None, 
                        radius_km: float = None, center_lat: float = None, 
                        center_lng: float = None) -> Dict:
        """Search locations with various filters"""
        try:
            search_results = {
                'query': query,
                'bookmarks': [],
                'location_matches': [],
                'address_matches': [],
                'total_results': 0
            }
            
            # Search bookmarks
            bookmarks = self.get_bookmarks()
            for bookmark in bookmarks:
                if query.lower() in bookmark['name'].lower() or \
                   (bookmark['address'] and query.lower() in bookmark['address'].lower()) or \
                   (bookmark['description'] and query.lower() in bookmark['description'].lower()):
                    search_results['bookmarks'].append(bookmark)
            
            # Search location history with addresses
            location_conditions = []
            location_params = []
            
            # Base query to get locations with recent data
            base_query = '''
                SELECT DISTINCT l.latitude, l.longitude, l.device_name, l.timestamp, 
                       COUNT(*) as visit_count,
                       MIN(l.timestamp) as first_visit,
                       MAX(l.timestamp) as last_visit
                FROM locations l
                WHERE 1=1
            '''
            
            if device_name:
                location_conditions.append('l.device_name = ?')
                location_params.append(device_name)
            
            if start_date:
                location_conditions.append('l.timestamp >= ?')
                location_params.append(start_date)
            
            if end_date:
                location_conditions.append('l.timestamp <= ?')
                location_params.append(end_date)
            
            # Add proximity search if center point provided
            if center_lat is not None and center_lng is not None and radius_km:
                # Simple bounding box search (approximation)
                lat_range = radius_km / 111.0  # 1 degree lat ≈ 111 km
                lng_range = radius_km / (111.0 * abs(center_lat / 90.0) + 0.1)  # Adjust for longitude
                
                location_conditions.extend([
                    'l.latitude BETWEEN ? AND ?',
                    'l.longitude BETWEEN ? AND ?'
                ])
                location_params.extend([
                    center_lat - lat_range, center_lat + lat_range,
                    center_lng - lng_range, center_lng + lng_range
                ])
            
            if location_conditions:
                base_query += ' AND ' + ' AND '.join(location_conditions)
            
            base_query += '''
                GROUP BY ROUND(l.latitude, 4), ROUND(l.longitude, 4), l.device_name
                HAVING visit_count >= 2
                ORDER BY visit_count DESC, last_visit DESC
                LIMIT 50
            '''
            
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(base_query, location_params)
                
                location_clusters = cursor.fetchall()
                
                # Get addresses and filter by search query
                for cluster in location_clusters:
                    lat = float(cluster['latitude'])
                    lng = float(cluster['longitude'])
                    
                    # Get address (with caching)
                    address = self.get_address_from_coordinates(lat, lng)
                    
                    # Check if query matches address
                    if query.lower() in address.lower():
                        search_results['address_matches'].append({
                            'latitude': lat,
                            'longitude': lng,
                            'address': address,
                            'device_name': cluster['device_name'],
                            'visit_count': cluster['visit_count'],
                            'first_visit': cluster['first_visit'],
                            'last_visit': cluster['last_visit'],
                            'match_type': 'address'
                        })
                    
                    # Also check device name matches
                    if query.lower() in cluster['device_name'].lower():
                        search_results['location_matches'].append({
                            'latitude': lat,
                            'longitude': lng,
                            'address': address,
                            'device_name': cluster['device_name'],
                            'visit_count': cluster['visit_count'],
                            'first_visit': cluster['first_visit'],
                            'last_visit': cluster['last_visit'],
                            'match_type': 'device'
                        })
            
            # Calculate total results
            search_results['total_results'] = (
                len(search_results['bookmarks']) + 
                len(search_results['location_matches']) + 
                len(search_results['address_matches'])
            )
            
            return search_results
            
        except Exception as e:
            logger.error(f"Error searching locations: {e}")
            return {"error": f"Failed to search locations: {e}"}
    
    def get_nearby_locations(self, latitude: float, longitude: float, 
                           radius_km: float = 1.0, limit: int = 20) -> List[Dict]:
        """Find locations near a given point"""
        try:
            # Simple bounding box search
            lat_range = radius_km / 111.0  # 1 degree lat ≈ 111 km
            lng_range = radius_km / (111.0 * abs(latitude / 90.0) + 0.1)
            
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT l.*, 
                           COUNT(*) as visit_count,
                           MIN(l.timestamp) as first_visit,
                           MAX(l.timestamp) as last_visit
                    FROM locations l
                    WHERE l.latitude BETWEEN %s AND %s
                      AND l.longitude BETWEEN %s AND %s
                    GROUP BY ROUND(l.latitude, 4), ROUND(l.longitude, 4), l.device_name
                    ORDER BY visit_count DESC
                    LIMIT %s
                ''', (
                    latitude - lat_range, latitude + lat_range,
                    longitude - lng_range, longitude + lng_range,
                    limit
                ))
                
                nearby = []
                for row in cursor.fetchall():
                    location_data = dict(row)
                    
                    # Calculate actual distance
                    distance_km = geodesic(
                        (latitude, longitude),
                        (location_data['latitude'], location_data['longitude'])
                    ).kilometers
                    
                    if distance_km <= radius_km:
                        location_data['distance_km'] = round(distance_km, 2)
                        location_data['address'] = self.get_address_from_coordinates(
                            location_data['latitude'], location_data['longitude']
                        )
                        nearby.append(location_data)
                
                # Sort by distance
                nearby.sort(key=lambda x: x['distance_km'])
                return nearby
                
        except Exception as e:
            logger.error(f"Error finding nearby locations: {e}")
            return []

    def generate_travel_report(self, device_name: str = None, start_date: str = None, 
                              end_date: str = None) -> Dict:
        """Generate comprehensive travel report"""
        try:
            report = {
                'device_name': device_name or 'All Devices',
                'period': f"{start_date} to {end_date}" if start_date and end_date else 'All Time',
                'summary': {},
                'daily_breakdown': [],
                'top_locations': [],
                'movement_stats': {},
                'distance_traveled': 0,
                'unique_locations': 0,
                'travel_patterns': {}
            }
            
            # Get location data for the period using database query that handles timezone-aware timestamps
            try:
                with db.get_connection() as conn:
                    cursor = conn.cursor()
                    
                    query = '''
                        SELECT l.*, d.device_type, d.is_active
                        FROM locations l
                        LEFT JOIN devices d ON l.device_id = d.id
                        WHERE 1=1
                    '''
                    params = []
                    
                    # Use date() function to handle timezone-aware timestamps
                    if start_date:
                        query += ' AND date(l.timestamp) >= date(?)'
                        params.append(start_date)
                    
                    if end_date:
                        query += ' AND date(l.timestamp) <= date(?)'
                        params.append(end_date)
                    
                    if device_name:
                        query += ' AND l.device_name = ?'
                        params.append(device_name)
                    
                    query += ' ORDER BY l.timestamp ASC LIMIT 5000'
                    
                    cursor.execute(query, params)
                    rows = cursor.fetchall()
                    locations = [dict(row) for row in rows]
                    
            except Exception as e:
                logger.error(f"Error getting location data for travel report: {e}")
                locations = []
            
            if not locations:
                return report
            
            # Calculate basic statistics
            report['summary'] = {
                'total_locations': len(locations),
                'unique_devices': len(set(loc['device_name'] for loc in locations)),
                'date_range': {
                    'start': min(loc['timestamp'] for loc in locations),
                    'end': max(loc['timestamp'] for loc in locations)
                },
                'most_active_device': max(set(loc['device_name'] for loc in locations),
                                        key=lambda x: sum(1 for loc in locations if loc['device_name'] == x))
            }
            
            # Calculate distance traveled
            total_distance = 0
            device_distances = {}
            
            # Group by device for distance calculation
            device_locations = {}
            for loc in locations:
                device = loc['device_name']
                if device not in device_locations:
                    device_locations[device] = []
                device_locations[device].append(loc)
            
            # Calculate distance for each device
            for device, device_locs in device_locations.items():
                device_locs.sort(key=lambda x: x['timestamp'])
                device_distance = 0
                
                for i in range(1, len(device_locs)):
                    prev_loc = device_locs[i-1]
                    curr_loc = device_locs[i]
                    
                    # Calculate distance using simple formula (convert to miles)
                    lat_diff = curr_loc['latitude'] - prev_loc['latitude']
                    lng_diff = curr_loc['longitude'] - prev_loc['longitude']
                    distance_km = ((lat_diff ** 2 + lng_diff ** 2) ** 0.5) * 111  # Rough km conversion
                    distance_miles = distance_km * 0.621371  # Convert km to miles
                    device_distance += distance_miles
                
                device_distances[device] = round(device_distance, 2)
                total_distance += device_distance
            
            report['distance_traveled'] = round(total_distance, 2)
            report['movement_stats']['device_distances'] = device_distances
            
            # Unique locations will be calculated from the smart clustering below
            # This placeholder will be updated after clustering
            
            # Smart grouping of locations (cluster nearby coordinates)
            location_clusters = []
            cluster_threshold = 0.0005  # ~50 meters clustering
            
            for loc in locations:
                # Find if this location belongs to an existing cluster
                found_cluster = False
                for cluster in location_clusters:
                    lat_diff = abs(loc['latitude'] - cluster['latitude'])
                    lng_diff = abs(loc['longitude'] - cluster['longitude'])
                    distance = (lat_diff ** 2 + lng_diff ** 2) ** 0.5
                    
                    if distance <= cluster_threshold:
                        # Add to existing cluster
                        cluster['visits'] += 1
                        cluster['devices'].add(loc['device_name'])
                        cluster['first_visit'] = min(cluster['first_visit'], loc['timestamp'])
                        cluster['last_visit'] = max(cluster['last_visit'], loc['timestamp'])
                        
                        # Update cluster center (weighted average)
                        total_visits = cluster['visits']
                        cluster['latitude'] = ((cluster['latitude'] * (total_visits - 1)) + loc['latitude']) / total_visits
                        cluster['longitude'] = ((cluster['longitude'] * (total_visits - 1)) + loc['longitude']) / total_visits
                        
                        found_cluster = True
                        break
                
                if not found_cluster:
                    # Create new cluster
                    location_clusters.append({
                        'latitude': loc['latitude'],
                        'longitude': loc['longitude'],
                        'visits': 1,
                        'devices': {loc['device_name']},
                        'first_visit': loc['timestamp'],
                        'last_visit': loc['timestamp'],
                        'address': None
                    })
            
            # Sort clusters by visit count and take top 10
            top_locations = sorted(location_clusters, key=lambda x: x['visits'], reverse=True)[:10]
            
            # Get address names for top locations
            for i, loc in enumerate(top_locations):
                loc['devices'] = list(loc['devices'])  # Convert set to list for JSON
                
                # Get address for this clustered location
                address = self.get_address_from_coordinates(loc['latitude'], loc['longitude'])
                if address:
                    loc['name'] = address
                else:
                    # Fallback to a more descriptive name
                    loc['name'] = f"Visited Location #{i+1}"
                    
            report['top_locations'] = top_locations
            
            # Update unique locations count from clustering
            report['unique_locations'] = len(location_clusters)
            
            # Daily breakdown
            daily_stats = defaultdict(lambda: {
                'date': '',
                'locations': 0,
                'devices': set(),
                'distance': 0
            })
            
            for loc in locations:
                date = loc['timestamp'][:10]  # Extract date part
                daily_stats[date]['date'] = date
                daily_stats[date]['locations'] += 1
                daily_stats[date]['devices'].add(loc['device_name'])
            
            # Convert daily stats to list
            daily_breakdown = []
            for date, stats in daily_stats.items():
                stats['devices'] = len(stats['devices'])
                daily_breakdown.append(stats)
            
            report['daily_breakdown'] = sorted(daily_breakdown, key=lambda x: x['date'])
            
            # Travel patterns analysis
            patterns = {
                'most_active_day': max(daily_breakdown, key=lambda x: x['locations']) if daily_breakdown else None,
                'least_active_day': min(daily_breakdown, key=lambda x: x['locations']) if daily_breakdown else None,
                'average_daily_locations': sum(d['locations'] for d in daily_breakdown) / len(daily_breakdown) if daily_breakdown else 0,
                'travel_frequency': 'High' if total_distance > 62 else 'Medium' if total_distance > 31 else 'Low'  # 100km = 62mi, 50km = 31mi
            }
            
            report['travel_patterns'] = patterns
            
            return report
            
        except Exception as e:
            logger.error(f"Error generating travel report: {e}")
            return {
                'device_name': device_name or 'All Devices',
                'period': 'Error',
                'summary': {},
                'daily_breakdown': [],
                'top_locations': [],
                'movement_stats': {},
                'distance_traveled': 0,
                'unique_locations': 0,
                'travel_patterns': {}
            }
    
    def delete_bookmark(self, bookmark_id: int) -> bool:
        """Delete a bookmark (soft delete)"""
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('UPDATE bookmarks SET is_active = FALSE WHERE id = %s', (bookmark_id,))
                
                if cursor.rowcount > 0:
                    db.log_message("INFO", f"Deleted bookmark ID {bookmark_id}", "bookmarks")
                    return True
                else:
                    return False
                    
        except Exception as e:
            logger.error(f"Error deleting bookmark: {e}")
            return False
    
    def get_bookmark_categories(self) -> List[str]:
        """Get all bookmark categories"""
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT DISTINCT category FROM bookmarks WHERE is_active = TRUE ORDER BY category')
                
                categories = [row['category'] for row in cursor.fetchall()]
                return categories
                
        except Exception as e:
            logger.error(f"Error getting bookmark categories: {e}")
            return ['general']

# Global analytics instance
analytics = LocationAnalytics()