"""
Storage management module for Speculum.
Provides disk usage stats, alerts, and cleanup functionality.
"""
import os
import shutil
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

MIRRORS_BASE_PATH = os.environ.get('MIRRORS_PATH', '/mirrors')

# Alert thresholds (percentage)
STORAGE_WARNING_THRESHOLD = 80
STORAGE_CRITICAL_THRESHOLD = 90


def get_disk_usage(path=None):
    """
    Get disk usage statistics for the mirrors volume.

    Returns:
        dict with total, used, free bytes and percentages
    """
    if path is None:
        path = MIRRORS_BASE_PATH

    try:
        usage = shutil.disk_usage(path)
        used_percent = (usage.used / usage.total) * 100 if usage.total > 0 else 0

        return {
            'total_bytes': usage.total,
            'used_bytes': usage.used,
            'free_bytes': usage.free,
            'used_percent': round(used_percent, 1),
            'free_percent': round(100 - used_percent, 1),
            'total_human': _human_size(usage.total),
            'used_human': _human_size(usage.used),
            'free_human': _human_size(usage.free),
            'path': path
        }
    except Exception as e:
        logger.error(f"Error getting disk usage: {e}")
        return {
            'error': str(e),
            'path': path
        }


def get_site_sizes():
    """
    Get size of each site's mirror directory.

    Returns:
        List of dicts with site info and size
    """
    from app.models import Site

    sites_with_sizes = []

    try:
        sites = Site.query.all()

        for site in sites:
            mirror_path = site._get_mirror_path()
            full_path = os.path.join(MIRRORS_BASE_PATH, mirror_path)

            if os.path.exists(full_path):
                size = _get_directory_size(full_path)
                file_count = _count_files(full_path)
            else:
                size = 0
                file_count = 0

            sites_with_sizes.append({
                'id': site.id,
                'name': site.name,
                'url': site.url,
                'status': site.status,
                'site_type': site.site_type,
                'db_size': site.size_bytes or 0,
                'actual_size': size,
                'size_human': _human_size(size),
                'file_count': file_count,
                'mirror_path': mirror_path,
                'last_crawl': site.last_crawl.isoformat() if site.last_crawl else None,
                'size_mismatch': abs((site.size_bytes or 0) - size) > 1024 * 1024  # >1MB difference
            })

        # Sort by size descending
        sites_with_sizes.sort(key=lambda x: x['actual_size'], reverse=True)

    except Exception as e:
        logger.error(f"Error getting site sizes: {e}")

    return sites_with_sizes


def get_storage_alerts():
    """
    Check storage and return any active alerts.

    Returns:
        List of alert dicts
    """
    alerts = []
    disk = get_disk_usage()

    if 'error' in disk:
        alerts.append({
            'level': 'error',
            'message': f"Impossibile leggere lo storage: {disk['error']}",
            'timestamp': datetime.utcnow().isoformat()
        })
        return alerts

    used_percent = disk['used_percent']

    if used_percent >= STORAGE_CRITICAL_THRESHOLD:
        alerts.append({
            'level': 'critical',
            'message': f"Spazio disco critico: {used_percent}% utilizzato ({disk['free_human']} liberi)",
            'timestamp': datetime.utcnow().isoformat(),
            'threshold': STORAGE_CRITICAL_THRESHOLD
        })
    elif used_percent >= STORAGE_WARNING_THRESHOLD:
        alerts.append({
            'level': 'warning',
            'message': f"Spazio disco in esaurimento: {used_percent}% utilizzato ({disk['free_human']} liberi)",
            'timestamp': datetime.utcnow().isoformat(),
            'threshold': STORAGE_WARNING_THRESHOLD
        })

    return alerts


def get_storage_summary():
    """
    Get complete storage summary for dashboard.

    Returns:
        dict with disk usage, site sizes, and alerts
    """
    disk = get_disk_usage()
    sites = get_site_sizes()
    alerts = get_storage_alerts()

    # Calculate totals
    total_mirror_size = sum(s['actual_size'] for s in sites)

    return {
        'disk': disk,
        'sites': sites,
        'alerts': alerts,
        'summary': {
            'total_sites': len(sites),
            'total_mirror_size': total_mirror_size,
            'total_mirror_size_human': _human_size(total_mirror_size),
            'largest_site': sites[0] if sites else None,
            'sites_with_issues': len([s for s in sites if s['size_mismatch']])
        },
        'thresholds': {
            'warning': STORAGE_WARNING_THRESHOLD,
            'critical': STORAGE_CRITICAL_THRESHOLD
        }
    }


def cleanup_orphan_directories():
    """
    Find directories in mirrors that don't have corresponding sites in DB.

    Returns:
        List of orphan directory paths
    """
    from app.models import Site

    orphans = []

    try:
        # Get all site mirror paths
        sites = Site.query.all()
        valid_paths = set()
        for site in sites:
            mirror_path = site._get_mirror_path()
            # Add both the direct path and parent directories
            valid_paths.add(mirror_path.split('/')[0])  # Domain or 'youtube'

        # Scan mirrors directory
        if os.path.exists(MIRRORS_BASE_PATH):
            for item in os.listdir(MIRRORS_BASE_PATH):
                item_path = os.path.join(MIRRORS_BASE_PATH, item)
                if os.path.isdir(item_path) and item not in valid_paths:
                    # Check if it's not a special directory
                    if item not in ['_speculum', 'temp', 'logs']:
                        size = _get_directory_size(item_path)
                        orphans.append({
                            'path': item,
                            'full_path': item_path,
                            'size': size,
                            'size_human': _human_size(size)
                        })

    except Exception as e:
        logger.error(f"Error finding orphan directories: {e}")

    return orphans


def _get_directory_size(path):
    """Calculate total size of a directory."""
    total = 0
    try:
        for dirpath, dirnames, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if os.path.exists(fp) and not os.path.islink(fp):
                    total += os.path.getsize(fp)
    except Exception as e:
        logger.error(f"Error calculating directory size for {path}: {e}")
    return total


def _count_files(path):
    """Count files in a directory."""
    count = 0
    try:
        for _, _, filenames in os.walk(path):
            count += len(filenames)
    except Exception:
        pass
    return count


def _human_size(size_bytes):
    """Convert bytes to human readable size."""
    if not size_bytes:
        return '0 B'
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"
