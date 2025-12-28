"""
Centralized helper functions for Speculum.
Consolidates duplicate patterns from routes.
"""
import logging
from functools import lru_cache
from sqlalchemy import func

logger = logging.getLogger(__name__)


def get_dashboard_stats(db, Site, Video):
    """
    Get dashboard statistics using optimized database aggregation.
    Used by: index(), api_stats(), api_dashboard_stats()
    """
    return {
        'total_sites': Site.query.count(),
        'ready_sites': Site.query.filter_by(status='ready').count(),
        'total_size': db.session.query(func.coalesce(func.sum(Site.size_bytes), 0)).scalar(),
        'youtube_channels': Site.query.filter_by(site_type='youtube').count(),
        'total_videos': Video.query.count()
    }


def get_status_counts(db, Site):
    """
    Get site counts grouped by status in a single query.
    Used by: api_dashboard_stats()
    """
    results = db.session.query(
        Site.status, func.count(Site.id)
    ).group_by(Site.status).all()

    counts = {status: count for status, count in results}
    return {
        'crawling': counts.get('crawling', 0),
        'pending': counts.get('pending', 0),
        'retry_pending': counts.get('retry_pending', 0),
        'error': counts.get('error', 0),
        'dead': counts.get('dead', 0),
        'ready': counts.get('ready', 0)
    }


def get_categories_ordered(Category):
    """
    Get all categories ordered by name.
    Used in 11+ places throughout the app.
    """
    return Category.query.order_by(Category.name).all()


def check_ollama_safe():
    """
    Safely check if Ollama is available.
    Returns False on any error instead of raising.
    """
    try:
        from app.ollama_client import check_ollama_available
        return check_ollama_available()
    except Exception:
        return False


def get_or_create_category(db, Category, name):
    """
    Get existing category by name or create new one.
    Used by: add_site(), bulk_add_sites()

    Returns:
        Category instance (existing or newly created)
    """
    if not name:
        return None

    category = Category.query.filter_by(name=name).first()
    if not category:
        category = Category(name=name)
        db.session.add(category)
        db.session.flush()
    return category
