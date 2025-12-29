"""
Full-text search module using SQLite FTS5.
Indexes site content (HTML) and YouTube video metadata.
"""
import os
import re
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Maximum text to index per site (100KB)
MAX_CONTENT_SIZE = 100000
# Maximum text per HTML file (10KB)
MAX_FILE_SIZE = 10000


def init_fts_tables(db):
    """
    Initialize FTS5 virtual tables for full-text search.
    Should be called once at app startup.
    """
    try:
        from sqlalchemy import text

        with db.engine.connect() as conn:
            # Create FTS5 table for sites content
            conn.execute(text('''
                CREATE VIRTUAL TABLE IF NOT EXISTS content_fts USING fts5(
                    site_id UNINDEXED,
                    content_type,
                    name,
                    description,
                    url,
                    content,
                    tokenize='porter unicode61'
                )
            '''))

            # Create FTS5 table for videos (YouTube)
            conn.execute(text('''
                CREATE VIRTUAL TABLE IF NOT EXISTS videos_fts USING fts5(
                    video_id UNINDEXED,
                    site_id UNINDEXED,
                    title,
                    description,
                    tokenize='porter unicode61'
                )
            '''))

            conn.commit()
            logger.info("FTS5 tables initialized")

    except Exception as e:
        logger.error(f"Failed to initialize FTS5 tables: {e}")


def index_site(site_id, db=None):
    """
    Index a site's content for full-text search.
    Extracts text from HTML files in the mirror directory.

    Args:
        site_id: Site ID to index
        db: Optional database instance
    """
    try:
        from app.models import Site
        from sqlalchemy import text

        if db is None:
            from app.models import db

        site = Site.query.get(site_id)
        if not site:
            logger.warning(f"Site {site_id} not found for indexing")
            return False

        # Get mirror path
        mirror_path = _get_mirror_path(site)
        if not mirror_path or not mirror_path.exists():
            logger.warning(f"Mirror path not found for site {site_id}")
            return False

        # Extract text content from HTML files
        content = _extract_text_from_mirror(mirror_path)

        # Remove existing index for this site
        with db.engine.connect() as conn:
            conn.execute(
                text("DELETE FROM content_fts WHERE site_id = :site_id"),
                {'site_id': str(site_id)}
            )

            # Insert new index entry
            conn.execute(
                text('''
                    INSERT INTO content_fts (site_id, content_type, name, description, url, content)
                    VALUES (:site_id, :content_type, :name, :description, :url, :content)
                '''),
                {
                    'site_id': str(site_id),
                    'content_type': site.site_type,
                    'name': site.name or '',
                    'description': site.description or '',
                    'url': site.url,
                    'content': content[:MAX_CONTENT_SIZE]
                }
            )
            conn.commit()

        logger.info(f"Indexed site {site_id} ({len(content)} chars)")
        return True

    except Exception as e:
        logger.error(f"Failed to index site {site_id}: {e}")
        return False


def index_video(video_id, db=None):
    """
    Index a YouTube video for full-text search.

    Args:
        video_id: Video record ID (not YouTube video ID)
        db: Optional database instance
    """
    try:
        from app.models import Video
        from sqlalchemy import text

        if db is None:
            from app.models import db

        video = Video.query.get(video_id)
        if not video:
            logger.warning(f"Video {video_id} not found for indexing")
            return False

        # Remove existing index for this video
        with db.engine.connect() as conn:
            conn.execute(
                text("DELETE FROM videos_fts WHERE video_id = :video_id"),
                {'video_id': str(video_id)}
            )

            # Insert new index entry
            conn.execute(
                text('''
                    INSERT INTO videos_fts (video_id, site_id, title, description)
                    VALUES (:video_id, :site_id, :title, :description)
                '''),
                {
                    'video_id': str(video_id),
                    'site_id': str(video.site_id),
                    'title': video.title or '',
                    'description': (video.description or '')[:MAX_CONTENT_SIZE]
                }
            )
            conn.commit()

        logger.info(f"Indexed video {video_id}")
        return True

    except Exception as e:
        logger.error(f"Failed to index video {video_id}: {e}")
        return False


def search(query, limit=20, site_type=None):
    """
    Search indexed content.

    Args:
        query: Search query string
        limit: Maximum results to return
        site_type: Optional filter by site type ('website' or 'youtube')

    Returns:
        List of search results with site info and snippets
    """
    try:
        from app.models import Site, Video, db
        from sqlalchemy import text

        # Sanitize query for FTS5
        query = _sanitize_fts_query(query)
        if not query:
            return []

        results = []

        # Search in sites content
        with db.engine.connect() as conn:
            # Build site query
            site_sql = '''
                SELECT site_id,
                       snippet(content_fts, 5, '<mark>', '</mark>', '...', 32) as snippet,
                       bm25(content_fts) as score
                FROM content_fts
                WHERE content_fts MATCH :query
            '''
            if site_type:
                site_sql += ' AND content_type = :site_type'
            site_sql += ' ORDER BY score LIMIT :limit'

            params = {'query': query, 'limit': limit}
            if site_type:
                params['site_type'] = site_type

            site_results = conn.execute(text(site_sql), params).fetchall()

            for row in site_results:
                site = Site.query.get(int(row[0]))
                if site:
                    results.append({
                        'type': 'site',
                        'site_id': site.id,
                        'name': site.name,
                        'url': site.url,
                        'site_type': site.site_type,
                        'category': site.category.name if site.category else None,
                        'snippet': row[1],
                        'score': row[2]
                    })

            # Search in videos if not filtering for websites only
            if site_type != 'website':
                video_sql = '''
                    SELECT video_id, site_id,
                           snippet(videos_fts, 2, '<mark>', '</mark>', '...', 32) as title_snippet,
                           snippet(videos_fts, 3, '<mark>', '</mark>', '...', 32) as desc_snippet,
                           bm25(videos_fts) as score
                    FROM videos_fts
                    WHERE videos_fts MATCH :query
                    ORDER BY score
                    LIMIT :limit
                '''
                video_results = conn.execute(
                    text(video_sql),
                    {'query': query, 'limit': limit}
                ).fetchall()

                for row in video_results:
                    video = Video.query.get(int(row[0]))
                    if video:
                        results.append({
                            'type': 'video',
                            'video_id': video.id,
                            'youtube_id': video.video_id,
                            'site_id': video.site_id,
                            'title': video.title,
                            'title_snippet': row[2],
                            'description_snippet': row[3],
                            'score': row[4]
                        })

        # Sort combined results by score
        results.sort(key=lambda x: x['score'])

        return results[:limit]

    except Exception as e:
        logger.error(f"Search failed for query '{query}': {e}")
        return []


def reindex_all():
    """Reindex all sites and videos. Use for rebuilding the search index."""
    try:
        from app.models import Site, Video

        # Reindex all ready sites
        sites = Site.query.filter_by(status='ready').all()
        for site in sites:
            index_site(site.id)

        # Reindex all ready videos
        videos = Video.query.filter_by(status='ready').all()
        for video in videos:
            index_video(video.id)

        logger.info(f"Reindexed {len(sites)} sites and {len(videos)} videos")
        return len(sites), len(videos)

    except Exception as e:
        logger.error(f"Reindex failed: {e}")
        return 0, 0


def delete_site_index(site_id):
    """Remove a site from the search index."""
    try:
        from app.models import db
        from sqlalchemy import text

        with db.engine.connect() as conn:
            conn.execute(
                text("DELETE FROM content_fts WHERE site_id = :site_id"),
                {'site_id': str(site_id)}
            )
            conn.commit()

        logger.info(f"Removed site {site_id} from search index")

    except Exception as e:
        logger.error(f"Failed to remove site {site_id} from index: {e}")


def _get_mirror_path(site):
    """Get the filesystem path to a site's mirror."""
    from urllib.parse import urlparse

    mirrors_base = os.environ.get('MIRRORS_PATH', '/mirrors')

    if site.site_type == 'youtube' and site.channel_id:
        return Path(mirrors_base) / 'youtube' / site.channel_id
    else:
        parsed = urlparse(site.url)
        return Path(mirrors_base) / parsed.netloc


def _extract_text_from_mirror(mirror_path):
    """
    Extract readable text from HTML files in a mirror directory.
    Uses simple regex-based extraction to avoid heavy dependencies.
    """
    text_parts = []
    total_size = 0

    try:
        for filepath in mirror_path.rglob('*.html'):
            if total_size >= MAX_CONTENT_SIZE:
                break

            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    html = f.read(MAX_FILE_SIZE * 2)  # Read a bit more than we need

                # Simple HTML text extraction
                text = _html_to_text(html)
                if text:
                    text_parts.append(text[:MAX_FILE_SIZE])
                    total_size += len(text_parts[-1])

            except Exception:
                continue

        # Also try .htm files
        for filepath in mirror_path.rglob('*.htm'):
            if total_size >= MAX_CONTENT_SIZE:
                break

            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    html = f.read(MAX_FILE_SIZE * 2)

                text = _html_to_text(html)
                if text:
                    text_parts.append(text[:MAX_FILE_SIZE])
                    total_size += len(text_parts[-1])

            except Exception:
                continue

    except Exception as e:
        logger.warning(f"Error extracting text from {mirror_path}: {e}")

    return ' '.join(text_parts)


def _html_to_text(html):
    """
    Convert HTML to plain text using regex.
    Simple extraction without external dependencies.
    """
    # Remove script and style elements
    html = re.sub(r'<script[^>]*>.*?</script>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?</style>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<nav[^>]*>.*?</nav>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<footer[^>]*>.*?</footer>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<header[^>]*>.*?</header>', ' ', html, flags=re.DOTALL | re.IGNORECASE)

    # Remove HTML comments
    html = re.sub(r'<!--.*?-->', ' ', html, flags=re.DOTALL)

    # Remove all HTML tags
    html = re.sub(r'<[^>]+>', ' ', html)

    # Decode common HTML entities
    html = html.replace('&nbsp;', ' ')
    html = html.replace('&amp;', '&')
    html = html.replace('&lt;', '<')
    html = html.replace('&gt;', '>')
    html = html.replace('&quot;', '"')
    html = html.replace('&#39;', "'")

    # Normalize whitespace
    html = re.sub(r'\s+', ' ', html)

    return html.strip()


def _sanitize_fts_query(query):
    """
    Sanitize a search query for FTS5.
    Removes special characters that could cause syntax errors.
    """
    if not query:
        return ''

    # Remove FTS5 special characters
    query = re.sub(r'[^\w\s\-]', ' ', query, flags=re.UNICODE)

    # Normalize whitespace
    query = ' '.join(query.split())

    # Add prefix matching for each term
    terms = query.split()
    if terms:
        # Use OR for multiple terms, with prefix matching
        return ' OR '.join(f'{term}*' for term in terms if term)

    return ''
