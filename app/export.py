"""
Export module for Ghost CMS integration.
Exports sites and collections in Ghost-compatible JSON format.
"""
import re
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def slugify(text):
    """Convert text to URL-safe slug."""
    if not text:
        return ''
    # Convert to lowercase and replace spaces/special chars with hyphens
    text = text.lower()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text).strip('-')
    return text[:100]  # Limit slug length


class GhostExporter:
    """Export sites to Ghost CMS JSON format."""

    def __init__(self, base_url='http://localhost:5050'):
        """
        Initialize exporter.

        Args:
            base_url: Base URL of Speculum instance for links/images
        """
        self.base_url = base_url.rstrip('/')

    def export_site(self, site):
        """
        Convert a Site to Ghost post format.

        Args:
            site: Site model instance

        Returns:
            Dict in Ghost post format
        """
        # Build HTML content
        html = self._build_html(site)

        # Get feature image (screenshot)
        feature_image = None
        if site.screenshot_path:
            feature_image = f'{self.base_url}/screenshot/{site.id}'

        # Build post data
        post = {
            'id': f'speculum_site_{site.id}',
            'title': site.name or site.url,
            'slug': slugify(site.name or site.url),
            'html': html,
            'plaintext': self._strip_html(html),
            'status': 'draft',  # Always export as draft for review
            'visibility': 'public',
            'created_at': self._format_date(site.created_at),
            'updated_at': self._format_date(site.updated_at),
            'published_at': self._format_date(site.last_crawl) if site.status == 'ready' else None,
            'custom_excerpt': (site.description or '')[:300],
            'meta_title': site.name,
            'meta_description': (site.description or '')[:300],
        }

        if feature_image:
            post['feature_image'] = feature_image

        # Add tags
        tags = []
        if site.category:
            tags.append({'name': site.category.name})
        if site.site_type == 'youtube':
            tags.append({'name': 'YouTube'})
        post['tags'] = tags

        return post

    def _build_html(self, site):
        """Build HTML content for a site including cultural metadata."""
        parts = []

        # Main description
        if site.description:
            parts.append(f'<p>{_escape_html(site.description)}</p>')

        # Site info
        parts.append('<h3>Informazioni Archivio</h3>')
        parts.append('<dl>')
        parts.append(f'<dt>URL Originale</dt><dd><a href="{site.url}">{site.url}</a></dd>')
        parts.append(f'<dt>Tipo</dt><dd>{site.site_type}</dd>')
        if site.last_crawl:
            parts.append(f'<dt>Ultimo Aggiornamento</dt><dd>{site.last_crawl.strftime("%d/%m/%Y")}</dd>')
        if site.size_bytes:
            parts.append(f'<dt>Dimensione</dt><dd>{_human_size(site.size_bytes)}</dd>')
        parts.append('</dl>')

        # Cultural metadata if available
        if hasattr(site, 'cultural_metadata') and site.cultural_metadata:
            cm = site.cultural_metadata
            parts.append('<h3>Metadati Culturali</h3>')
            parts.append('<dl>')

            if cm.dc_title:
                parts.append(f'<dt>Titolo Originale</dt><dd>{_escape_html(cm.dc_title)}</dd>')
            if cm.dc_creator:
                parts.append(f'<dt>Autore</dt><dd>{_escape_html(cm.dc_creator)}</dd>')
            if cm.dc_date:
                parts.append(f'<dt>Data</dt><dd>{_escape_html(cm.dc_date)}</dd>')
            if cm.historical_period:
                parts.append(f'<dt>Periodo Storico</dt><dd>{_escape_html(cm.historical_period)}</dd>')
            if cm.cultural_movement:
                parts.append(f'<dt>Movimento Culturale</dt><dd>{_escape_html(cm.cultural_movement)}</dd>')
            if cm.original_format:
                parts.append(f'<dt>Formato Originale</dt><dd>{_escape_html(cm.original_format)}</dd>')
            if cm.provenance:
                parts.append(f'<dt>Provenienza</dt><dd>{_escape_html(cm.provenance)}</dd>')
            if cm.dc_rights:
                parts.append(f'<dt>Licenza</dt><dd>{_escape_html(cm.dc_rights)}</dd>')
            if cm.risk_level:
                risk_labels = {'high': 'Alto', 'medium': 'Medio', 'low': 'Basso'}
                parts.append(f'<dt>Rischio Scomparsa</dt><dd>{risk_labels.get(cm.risk_level, cm.risk_level)}</dd>')
            if cm.dc_description:
                parts.append(f'<dt>Descrizione Estesa</dt><dd>{_escape_html(cm.dc_description)}</dd>')

            parts.append('</dl>')

        # Wayback link if available
        if site.wayback_url:
            parts.append(f'<p><a href="{site.wayback_url}">Versione su Internet Archive</a></p>')

        # Link to archive
        parts.append(f'<p><a href="{self.base_url}/sites/{site.id}">Visualizza Archivio Completo</a></p>')

        return '\n'.join(parts)

    def _strip_html(self, html):
        """Remove HTML tags for plaintext version."""
        text = re.sub(r'<[^>]+>', ' ', html)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    def _format_date(self, dt):
        """Format datetime for Ghost JSON."""
        if dt:
            return dt.strftime('%Y-%m-%dT%H:%M:%S.000Z')
        return None

    def export_all(self, site_type=None, category_id=None, status='ready'):
        """
        Export all sites matching criteria to Ghost format.

        Args:
            site_type: Filter by 'website' or 'youtube'
            category_id: Filter by category
            status: Filter by status (default: 'ready')

        Returns:
            Dict in Ghost import format
        """
        from app.models import Site, Category

        # Build query
        query = Site.query
        if status:
            query = query.filter_by(status=status)
        if site_type:
            query = query.filter_by(site_type=site_type)
        if category_id:
            query = query.filter_by(category_id=category_id)

        sites = query.all()
        categories = Category.query.all()

        # Build Ghost export
        export = {
            'db': [{
                'meta': {
                    'exported_on': int(datetime.utcnow().timestamp() * 1000),
                    'version': '5.0.0'
                },
                'data': {
                    'posts': [self.export_site(s) for s in sites],
                    'tags': [
                        {
                            'id': f'speculum_cat_{c.id}',
                            'name': c.name,
                            'slug': slugify(c.name),
                            'description': c.description or ''
                        }
                        for c in categories
                    ]
                }
            }]
        }

        logger.info(f"Exported {len(sites)} sites to Ghost format")
        return export

    def export_to_json(self, **kwargs):
        """
        Export to JSON string.

        Args:
            **kwargs: Arguments passed to export_all()

        Returns:
            JSON string
        """
        data = self.export_all(**kwargs)
        return json.dumps(data, indent=2, ensure_ascii=False)


def export_sites_for_ghost(base_url=None, **kwargs):
    """
    Convenience function to export sites for Ghost.

    Args:
        base_url: Base URL of Speculum instance
        **kwargs: Filter arguments (site_type, category_id, status)

    Returns:
        Dict in Ghost import format
    """
    if base_url is None:
        import os
        base_url = os.environ.get('SPECULUM_BASE_URL', 'http://localhost:5050')

    exporter = GhostExporter(base_url=base_url)
    return exporter.export_all(**kwargs)


def _escape_html(text):
    """Escape HTML special characters."""
    if not text:
        return ''
    return (text
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;'))


def _human_size(size_bytes):
    """Convert bytes to human readable size."""
    if not size_bytes:
        return '0 B'
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"
