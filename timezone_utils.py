"""
Timezone utilities for iTrax
Handles timezone conversion and formatting
"""

import pytz
from datetime import datetime
from typing import Optional, Union
import logging

logger = logging.getLogger(__name__)

def convert_utc_to_user_timezone(utc_datetime: Union[datetime, str], user_timezone: str = 'America/Chicago') -> datetime:
    """
    Convert UTC datetime to user's timezone
    
    Args:
        utc_datetime: UTC datetime object or ISO string
        user_timezone: User's timezone string (e.g., 'America/Chicago')
    
    Returns:
        datetime object in user's timezone
    """
    try:
        # Handle string input
        if isinstance(utc_datetime, str):
            if utc_datetime.endswith('Z'):
                utc_datetime = utc_datetime[:-1] + '+00:00'
            utc_datetime = datetime.fromisoformat(utc_datetime.replace('Z', '+00:00'))
        
        # Ensure UTC timezone is set
        if utc_datetime.tzinfo is None:
            utc_datetime = pytz.UTC.localize(utc_datetime)
        elif utc_datetime.tzinfo != pytz.UTC:
            utc_datetime = utc_datetime.astimezone(pytz.UTC)
        
        # Convert to user timezone
        user_tz = pytz.timezone(user_timezone)
        local_datetime = utc_datetime.astimezone(user_tz)
        
        return local_datetime
        
    except Exception as e:
        logger.error(f"Error converting timezone: {e}")
        # Fallback to original datetime
        return utc_datetime if isinstance(utc_datetime, datetime) else datetime.now()

def convert_local_to_utc(local_datetime: Union[datetime, str], user_timezone: str = 'America/Chicago') -> datetime:
    """
    Convert local datetime to UTC
    
    Args:
        local_datetime: Local datetime object or string
        user_timezone: User's timezone string
    
    Returns:
        UTC datetime object
    """
    try:
        # Handle string input
        if isinstance(local_datetime, str):
            local_datetime = datetime.fromisoformat(local_datetime)
        
        # Set timezone if not already set
        if local_datetime.tzinfo is None:
            user_tz = pytz.timezone(user_timezone)
            local_datetime = user_tz.localize(local_datetime)
        
        # Convert to UTC
        utc_datetime = local_datetime.astimezone(pytz.UTC)
        
        return utc_datetime
        
    except Exception as e:
        logger.error(f"Error converting to UTC: {e}")
        return datetime.utcnow()

def format_datetime_for_user(dt: Union[datetime, str], user_timezone: str = 'America/Chicago', 
                           date_format: str = '%Y-%m-%d %I:%M:%S %p') -> str:
    """
    Format datetime for display to user in their timezone
    
    Args:
        dt: Datetime object or string (assumed to be UTC)
        user_timezone: User's timezone string
        date_format: Strftime format string
    
    Returns:
        Formatted datetime string
    """
    try:
        # Convert to user timezone
        local_dt = convert_utc_to_user_timezone(dt, user_timezone)
        
        # Format according to user preference
        formatted = local_dt.strftime(date_format)
        
        # Add timezone abbreviation
        tz_abbrev = local_dt.strftime('%Z')
        if tz_abbrev:
            formatted += f" {tz_abbrev}"
        
        return formatted
        
    except Exception as e:
        logger.error(f"Error formatting datetime: {e}")
        # Fallback formatting
        if isinstance(dt, str):
            return dt
        return dt.strftime('%Y-%m-%d %H:%M:%S UTC')

def get_current_time_in_timezone(user_timezone: str = 'America/Chicago') -> datetime:
    """
    Get current time in user's timezone
    
    Args:
        user_timezone: User's timezone string
    
    Returns:
        Current datetime in user's timezone
    """
    try:
        utc_now = datetime.utcnow().replace(tzinfo=pytz.UTC)
        return convert_utc_to_user_timezone(utc_now, user_timezone)
    except Exception as e:
        logger.error(f"Error getting current time: {e}")
        return datetime.now()

def validate_timezone(timezone_str: str) -> bool:
    """
    Validate if timezone string is valid
    
    Args:
        timezone_str: Timezone string to validate
    
    Returns:
        True if valid, False otherwise
    """
    try:
        pytz.timezone(timezone_str)
        return True
    except pytz.exceptions.UnknownTimeZoneError:
        return False

def get_timezone_offset(timezone_str: str) -> str:
    """
    Get timezone offset string (e.g., '-06:00')
    
    Args:
        timezone_str: Timezone string
    
    Returns:
        Offset string
    """
    try:
        tz = pytz.timezone(timezone_str)
        now = datetime.now(tz)
        offset = now.strftime('%z')
        
        # Format as +/-HH:MM
        if len(offset) == 5:
            return f"{offset[:3]}:{offset[3:]}"
        return offset
        
    except Exception as e:
        logger.error(f"Error getting timezone offset: {e}")
        return "+00:00"

def get_user_friendly_timezone_name(timezone_str: str) -> str:
    """
    Get user-friendly timezone name
    
    Args:
        timezone_str: Timezone string (e.g., 'America/Chicago')
    
    Returns:
        Friendly name (e.g., 'Central Standard Time')
    """
    try:
        tz = pytz.timezone(timezone_str)
        now = datetime.now(tz)
        
        # Get long timezone name
        tzname = now.strftime('%Z %z')
        return tzname
        
    except Exception as e:
        logger.error(f"Error getting timezone name: {e}")
        return timezone_str

# Common timezone mappings for quick access
COMMON_TIMEZONES = {
    'America/New_York': 'Eastern Time (US/Canada)',
    'America/Chicago': 'Central Time (US/Canada)', 
    'America/Denver': 'Mountain Time (US/Canada)',
    'America/Phoenix': 'Arizona Time (No DST)',
    'America/Los_Angeles': 'Pacific Time (US/Canada)',
    'America/Anchorage': 'Alaska Time',
    'Pacific/Honolulu': 'Hawaii Time',
    'UTC': 'Coordinated Universal Time',
    'Europe/London': 'Greenwich Mean Time',
    'Europe/Paris': 'Central European Time',
    'Asia/Tokyo': 'Japan Standard Time',
    'Australia/Sydney': 'Australian Eastern Time'
}

def get_common_timezones() -> dict:
    """Get dictionary of common timezones with friendly names"""
    return COMMON_TIMEZONES