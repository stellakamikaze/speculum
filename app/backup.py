"""
Backup module for MirrorRequest persistence.
Ensures requests are never lost through automatic JSON backup.
"""
import os
import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Backup directory inside mirrors volume
BACKUP_DIR = os.environ.get('BACKUP_PATH', '/mirrors/_backups')
MAX_BACKUPS = 30  # Keep last 30 backups


def get_backup_dir():
    """Get or create backup directory."""
    backup_path = Path(BACKUP_DIR)
    backup_path.mkdir(parents=True, exist_ok=True)
    return backup_path


def export_requests_json(db_session=None):
    """
    Export all MirrorRequest records to JSON file.

    Args:
        db_session: Optional database session (for use outside Flask context)

    Returns:
        Path to created backup file, or None if failed
    """
    try:
        from app.models import MirrorRequest

        # Query all requests
        requests = MirrorRequest.query.all()

        # Build export data
        export_data = {
            'exported_at': datetime.utcnow().isoformat(),
            'version': '1.0',
            'count': len(requests),
            'requests': []
        }

        for req in requests:
            req_data = {
                'id': req.id,
                'url': req.url,
                'name': req.name,
                'description': req.description,
                'category_suggestion': req.category_suggestion,
                'user_id': req.user_id,
                'requester_name': req.requester_name,
                'requester_email': req.requester_email,
                'status': req.status,
                'reviewed_by': req.reviewed_by,
                'reviewed_at': req.reviewed_at.isoformat() if req.reviewed_at else None,
                'admin_notes': req.admin_notes,
                'site_id': req.site_id,
                'created_at': req.created_at.isoformat() if req.created_at else None,
                'ip_address': req.ip_address
            }
            export_data['requests'].append(req_data)

        # Generate filename with timestamp
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        filename = f'requests_{timestamp}.json'
        filepath = get_backup_dir() / filename

        # Write to file
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)

        logger.info(f"Exported {len(requests)} requests to {filepath}")

        # Cleanup old backups
        cleanup_old_backups()

        return filepath

    except Exception as e:
        logger.error(f"Failed to export requests: {e}")
        return None


def import_requests_json(filepath, skip_existing=True):
    """
    Import MirrorRequest records from JSON backup.

    Args:
        filepath: Path to JSON backup file
        skip_existing: If True, skip requests that already exist (by URL)

    Returns:
        Tuple of (imported_count, skipped_count, errors)
    """
    try:
        from app.models import db, MirrorRequest

        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        imported = 0
        skipped = 0
        errors = []

        for req_data in data.get('requests', []):
            try:
                # Check if already exists
                if skip_existing:
                    existing = MirrorRequest.query.filter_by(url=req_data['url']).first()
                    if existing:
                        skipped += 1
                        continue

                # Create new request
                req = MirrorRequest(
                    url=req_data['url'],
                    name=req_data.get('name'),
                    description=req_data.get('description'),
                    category_suggestion=req_data.get('category_suggestion'),
                    user_id=req_data.get('user_id'),
                    requester_name=req_data.get('requester_name'),
                    requester_email=req_data.get('requester_email'),
                    status=req_data.get('status', 'pending'),
                    reviewed_by=req_data.get('reviewed_by'),
                    admin_notes=req_data.get('admin_notes'),
                    site_id=req_data.get('site_id'),
                    ip_address=req_data.get('ip_address')
                )

                # Handle dates
                if req_data.get('created_at'):
                    req.created_at = datetime.fromisoformat(req_data['created_at'])
                if req_data.get('reviewed_at'):
                    req.reviewed_at = datetime.fromisoformat(req_data['reviewed_at'])

                db.session.add(req)
                imported += 1

            except Exception as e:
                errors.append(f"Error importing request {req_data.get('url')}: {e}")

        db.session.commit()
        logger.info(f"Imported {imported} requests, skipped {skipped}, errors: {len(errors)}")

        return imported, skipped, errors

    except Exception as e:
        logger.error(f"Failed to import requests: {e}")
        return 0, 0, [str(e)]


def cleanup_old_backups():
    """Remove old backup files, keeping only the most recent MAX_BACKUPS."""
    try:
        backup_dir = get_backup_dir()
        backups = sorted(
            backup_dir.glob('requests_*.json'),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )

        # Remove old backups
        for old_backup in backups[MAX_BACKUPS:]:
            old_backup.unlink()
            logger.debug(f"Removed old backup: {old_backup}")

    except Exception as e:
        logger.warning(f"Failed to cleanup old backups: {e}")


def list_backups():
    """
    List available backup files.

    Returns:
        List of dicts with backup info (filename, size, created_at, count)
    """
    try:
        backup_dir = get_backup_dir()
        backups = []

        for filepath in sorted(backup_dir.glob('requests_*.json'), reverse=True):
            try:
                stat = filepath.stat()

                # Try to read count from file
                count = None
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        count = data.get('count')
                except Exception:
                    pass

                backups.append({
                    'filename': filepath.name,
                    'filepath': str(filepath),
                    'size_bytes': stat.st_size,
                    'size_human': _human_size(stat.st_size),
                    'created_at': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    'count': count
                })
            except Exception:
                continue

        return backups

    except Exception as e:
        logger.error(f"Failed to list backups: {e}")
        return []


def get_latest_backup():
    """Get the most recent backup file path."""
    backups = list_backups()
    return backups[0] if backups else None


def _human_size(size_bytes):
    """Convert bytes to human readable size."""
    if not size_bytes:
        return '0 B'
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"
