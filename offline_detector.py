#!/usr/bin/env python3
"""
Phone Offline Detection Module
Detects when a phone is offline by analyzing GPS logs for unchanging accuracy radius.
When a phone goes offline, the GPS accuracy radius typically stays exactly the same
across multiple location updates, which is very unlikely in normal usage.
"""

import logging
import math
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

class OfflineDetector:
    def __init__(self, db=None):
        """Initialize the offline detector with database connection"""
        self.db = db
        if db is None:
            try:
                from database import Database
                self.db = Database()
            except Exception as e:
                logger.error(f"Failed to initialize database: {e}")
                self.db = None
    
    def calculate_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate distance between two GPS coordinates using Haversine formula"""
        # Convert latitude and longitude from degrees to radians
        lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
        
        # Haversine formula
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.asin(math.sqrt(a))
        
        # Radius of earth in meters
        r = 6371000
        return c * r
    
    def analyze_location_pattern(self, locations: List[Dict], min_samples: int = 5) -> Dict:
        """
        Analyze location pattern to detect offline behavior
        
        Args:
            locations: List of location records sorted by timestamp
            min_samples: Minimum number of samples needed for analysis
            
        Returns:
            Dictionary with analysis results
        """
        if len(locations) < min_samples:
            return {
                'is_offline': False,
                'confidence': 0,
                'reason': f'Insufficient data points ({len(locations)} < {min_samples})',
                'sample_count': len(locations)
            }
        
        # Check for identical accuracy values (main offline indicator)
        accuracy_values = []
        identical_accuracy_count = 0
        
        for loc in locations:
            accuracy = loc.get('accuracy')
            if accuracy is not None:
                accuracy_values.append(accuracy)
                
                # Check if this accuracy matches previous ones exactly
                if len(accuracy_values) > 1 and accuracy == accuracy_values[-2]:
                    identical_accuracy_count += 1
        
        # Calculate metrics
        total_accuracy_samples = len(accuracy_values)
        accuracy_variance = 0
        
        if total_accuracy_samples > 1:
            avg_accuracy = sum(accuracy_values) / total_accuracy_samples
            accuracy_variance = sum((x - avg_accuracy) ** 2 for x in accuracy_values) / total_accuracy_samples
        
        # Check for identical coordinates (secondary indicator)
        coordinate_pairs = [(loc['latitude'], loc['longitude']) for loc in locations]
        identical_coordinates = len(set(coordinate_pairs)) == 1
        
        # Check movement pattern
        total_distance = 0
        max_distance = 0
        
        for i in range(1, len(locations)):
            prev_loc = locations[i-1]
            curr_loc = locations[i]
            
            distance = self.calculate_distance(
                prev_loc['latitude'], prev_loc['longitude'],
                curr_loc['latitude'], curr_loc['longitude']
            )
            total_distance += distance
            max_distance = max(max_distance, distance)
        
        avg_distance = total_distance / max(1, len(locations) - 1)
        
        # Determine if phone is likely offline based on multiple factors
        offline_indicators = []
        confidence = 0
        
        # Primary indicator: Identical accuracy values
        if total_accuracy_samples >= min_samples:
            identical_ratio = identical_accuracy_count / (total_accuracy_samples - 1)
            if identical_ratio >= 0.8:  # 80% or more identical accuracy values
                offline_indicators.append(f'High identical accuracy ratio: {identical_ratio:.2%}')
                confidence += 50
            elif identical_ratio >= 0.6:  # 60% or more identical accuracy values
                offline_indicators.append(f'Medium identical accuracy ratio: {identical_ratio:.2%}')
                confidence += 30
        
        # Secondary indicator: Very low accuracy variance
        if accuracy_variance < 1.0 and total_accuracy_samples >= min_samples:
            offline_indicators.append(f'Very low accuracy variance: {accuracy_variance:.2f}')
            confidence += 20
        
        # Tertiary indicator: Identical coordinates
        if identical_coordinates:
            offline_indicators.append('All coordinates identical')
            confidence += 15
        
        # Movement pattern indicator: Very small movements
        if avg_distance < 5:  # Less than 5 meters average movement
            offline_indicators.append(f'Very small average movement: {avg_distance:.1f}m')
            confidence += 10
        
        # Time pattern indicator: Regular intervals (cached data)
        timestamps = []
        for loc in locations:
            try:
                ts = datetime.fromisoformat(str(loc['timestamp']).replace('Z', '+00:00'))
                timestamps.append(ts)
            except:
                pass
        
        if len(timestamps) >= min_samples:
            intervals = []
            for i in range(1, len(timestamps)):
                interval = (timestamps[i] - timestamps[i-1]).total_seconds()
                intervals.append(interval)
            
            # Check if intervals are suspiciously regular
            if intervals and max(intervals) - min(intervals) < 60:  # Within 1 minute variation
                offline_indicators.append('Suspiciously regular time intervals')
                confidence += 15
        
        is_offline = confidence >= 50
        
        return {
            'is_offline': is_offline,
            'confidence': min(confidence, 100),
            'reason': '; '.join(offline_indicators) if offline_indicators else 'No strong offline indicators',
            'sample_count': len(locations),
            'metrics': {
                'identical_accuracy_count': identical_accuracy_count,
                'total_accuracy_samples': total_accuracy_samples,
                'accuracy_variance': accuracy_variance,
                'identical_coordinates': identical_coordinates,
                'avg_distance_meters': avg_distance,
                'max_distance_meters': max_distance,
                'total_distance_meters': total_distance
            }
        }
    
    def check_device_offline_status(self, device_name: str, hours_back: int = 2) -> Dict:
        """
        Check if a specific device appears to be offline based on recent GPS logs
        
        Args:
            device_name: Name of the device to check
            hours_back: Number of hours back to analyze
            
        Returns:
            Analysis results dictionary
        """
        try:
            if not self.db:
                return {
                    'device_name': device_name,
                    'is_offline': False,
                    'confidence': 0,
                    'reason': 'Database connection not available',
                    'sample_count': 0,
                    'time_range': f'{hours_back} hours'
                }
                
            # Get recent location data for the device
            end_time = datetime.now()
            start_time = end_time - timedelta(hours=hours_back)
            
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                query = """
                    SELECT latitude, longitude, timestamp, accuracy, battery_level, is_charging
                    FROM locations
                    WHERE device_name = %s 
                    AND timestamp >= %s 
                    AND timestamp <= %s
                    ORDER BY timestamp ASC
                """
                
                cursor.execute(query, (device_name, start_time, end_time))
                locations = list(cursor.fetchall())
            
            if not locations:
                return {
                    'device_name': device_name,
                    'is_offline': False,
                    'confidence': 0,
                    'reason': 'No recent location data found',
                    'sample_count': 0,
                    'time_range': f'{hours_back} hours'
                }
            
            # Analyze the location pattern
            analysis = self.analyze_location_pattern(locations)
            analysis['device_name'] = device_name
            analysis['time_range'] = f'{hours_back} hours'
            
            return analysis
            
        except Exception as e:
            logger.error(f"Error checking offline status for {device_name}: {e}")
            return {
                'device_name': device_name,
                'is_offline': False,
                'confidence': 0,
                'reason': f'Error during analysis: {str(e)}',
                'sample_count': 0,
                'time_range': f'{hours_back} hours'
            }
    
    def check_all_devices_offline_status(self, hours_back: int = 2) -> List[Dict]:
        """
        Check offline status for all devices with recent activity
        
        Args:
            hours_back: Number of hours back to analyze
            
        Returns:
            List of analysis results for each device
        """
        try:
            if not self.db:
                return []
                
            # Get list of devices with recent activity
            end_time = datetime.now()
            start_time = end_time - timedelta(hours=hours_back)
            
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT DISTINCT device_name 
                    FROM locations 
                    WHERE timestamp >= %s 
                    ORDER BY device_name
                """, (start_time,))
                
                devices = [row['device_name'] for row in cursor.fetchall()]
            
            results = []
            for device_name in devices:
                analysis = self.check_device_offline_status(device_name, hours_back)
                results.append(analysis)
            
            return results
            
        except Exception as e:
            logger.error(f"Error checking offline status for all devices: {e}")
            return []
    
    def get_offline_summary_report(self, hours_back: int = 2) -> Dict:
        """
        Generate a summary report of offline devices
        
        Args:
            hours_back: Number of hours back to analyze
            
        Returns:
            Summary report dictionary
        """
        try:
            all_results = self.check_all_devices_offline_status(hours_back)
            
            offline_devices = [r for r in all_results if r['is_offline']]
            online_devices = [r for r in all_results if not r['is_offline']]
            
            # Sort by confidence for offline devices
            offline_devices.sort(key=lambda x: x['confidence'], reverse=True)
            
            return {
                'analysis_time': datetime.now().isoformat(),
                'time_range_hours': hours_back,
                'total_devices': len(all_results),
                'offline_devices_count': len(offline_devices),
                'online_devices_count': len(online_devices),
                'offline_devices': offline_devices,
                'online_devices': online_devices
            }
            
        except Exception as e:
            logger.error(f"Error generating offline summary report: {e}")
            return {
                'analysis_time': datetime.now().isoformat(),
                'time_range_hours': hours_back,
                'total_devices': 0,
                'offline_devices_count': 0,
                'online_devices_count': 0,
                'offline_devices': [],
                'online_devices': [],
                'error': str(e)
            }


def main():
    """Command line interface for offline detection"""
    import argparse
    import json
    
    parser = argparse.ArgumentParser(description='Phone Offline Detection Tool')
    parser.add_argument('--device', type=str, help='Check specific device by name')
    parser.add_argument('--hours', type=int, default=2, help='Hours back to analyze (default: 2)')
    parser.add_argument('--all', action='store_true', help='Check all devices')
    parser.add_argument('--summary', action='store_true', help='Generate summary report')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    
    args = parser.parse_args()
    
    detector = OfflineDetector()
    
    if args.device:
        # Check specific device
        result = detector.check_device_offline_status(args.device, args.hours)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"\n📱 Offline Analysis for {args.device}")
            print("=" * 50)
            print(f"Status: {'📴 OFFLINE' if result['is_offline'] else '📶 ONLINE'}")
            print(f"Confidence: {result['confidence']}%")
            print(f"Reason: {result['reason']}")
            print(f"Samples: {result['sample_count']}")
            print(f"Time Range: {result['time_range']}")
    
    elif args.all or args.summary:
        # Check all devices or generate summary
        report = detector.get_offline_summary_report(args.hours)
        
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(f"\n📊 Device Offline Status Report")
            print("=" * 50)
            print(f"Analysis Time: {report['analysis_time']}")
            print(f"Time Range: {report['time_range_hours']} hours")
            print(f"Total Devices: {report['total_devices']}")
            print(f"Online Devices: {report['online_devices_count']}")
            print(f"Offline Devices: {report['offline_devices_count']}")
            
            if report['offline_devices']:
                print("\n📴 OFFLINE DEVICES:")
                for device in report['offline_devices']:
                    print(f"  • {device['device_name']} ({device['confidence']}% confidence)")
                    print(f"    Reason: {device['reason']}")
            
            if report['online_devices']:
                print("\n📶 ONLINE DEVICES:")
                for device in report['online_devices']:
                    print(f"  • {device['device_name']}")
    else:
        print("Use --device <name>, --all, or --summary. See --help for options.")


if __name__ == "__main__":
    main()