"""
oEmbed Provider for Speculum.
Enables rich embeds in Ghost CMS and other oEmbed consumers.
"""
import re
import os
import logging
from urllib.parse import urlparse, parse_qs
from PIL import Image

logger = logging.getLogger(__name__)

MIRRORS_BASE_PATH = os.environ.get('MIRRORS_PATH', '/mirrors')


class OEmbedProvider:
    """oEmbed provider that generates embed responses for Speculum content."""

    # URL patterns to match (relative paths)
    PATTERNS = [
        (r'^/sites/(\d+)$', 'site'),
        (r'^/sites/(\d+)/media$', 'gallery'),
        (r'^/mirror/(.+)$', 'mirror'),
        (r'^/media/(.+)$', 'media'),
        (r'^/watch/(\d+)$', 'video'),
        (r'^/search', 'search'),
    ]

    def __init__(self, base_url):
        """
        Initialize oEmbed provider.

        Args:
            base_url: Base URL of Speculum instance (e.g., http://localhost:5050)
        """
        self.base_url = base_url.rstrip('/')

    def get_oembed_response(self, url, maxwidth=600, maxheight=400):
        """
        Generate oEmbed response for a given URL.

        Args:
            url: Full URL to generate embed for
            maxwidth: Maximum width of embed
            maxheight: Maximum height of embed

        Returns:
            Dict with oEmbed response, or None if URL not supported
        """
        try:
            parsed = urlparse(url)
            path = parsed.path

            # Match against patterns
            for pattern, content_type in self.PATTERNS:
                match = re.match(pattern, path)
                if match:
                    groups = match.groups()

                    if content_type == 'site':
                        return self._site_response(int(groups[0]), maxwidth, maxheight)
                    elif content_type == 'gallery':
                        return self._gallery_response(int(groups[0]), maxwidth, maxheight)
                    elif content_type == 'mirror':
                        return self._mirror_response(groups[0], maxwidth, maxheight)
                    elif content_type == 'media':
                        return self._media_response(groups[0], maxwidth, maxheight)
                    elif content_type == 'video':
                        return self._video_response(int(groups[0]), maxwidth, maxheight)
                    elif content_type == 'search':
                        query = parse_qs(parsed.query).get('q', [''])[0]
                        return self._search_response(query, maxwidth, maxheight)

            return None

        except Exception as e:
            logger.error(f"oEmbed error for {url}: {e}")
            return None

    def _base_response(self):
        """Base response fields common to all types."""
        return {
            'version': '1.0',
            'provider_name': 'Speculum',
            'provider_url': self.base_url,
        }

    def _site_response(self, site_id, maxwidth, maxheight):
        """Generate oEmbed response for a site detail page."""
        from app.models import Site

        site = Site.query.get(site_id)
        if not site:
            return None

        # Calculate embed dimensions
        width = min(maxwidth, 600)
        height = min(maxheight, 200)

        response = self._base_response()
        response.update({
            'type': 'rich',
            'title': site.name or site.url,
            'author_name': site.category.name if site.category else None,
            'thumbnail_url': f'{self.base_url}/thumbnail/{site.id}' if site.screenshot_path else None,
            'thumbnail_width': 400,
            'thumbnail_height': 300,
            'html': f'<iframe src="{self.base_url}/embed/site/{site.id}" '
                    f'width="{width}" height="{height}" frameborder="0" '
                    f'style="border:1px solid #ccc;border-radius:4px;"></iframe>',
            'width': width,
            'height': height,
        })

        return response

    def _gallery_response(self, site_id, maxwidth, maxheight):
        """Generate oEmbed response for a site's media gallery."""
        from app.models import Site

        site = Site.query.get(site_id)
        if not site:
            return None

        width = min(maxwidth, 600)
        height = min(maxheight, 400)

        response = self._base_response()
        response.update({
            'type': 'rich',
            'title': f'Galleria: {site.name}',
            'thumbnail_url': f'{self.base_url}/thumbnail/{site.id}' if site.screenshot_path else None,
            'html': f'<iframe src="{self.base_url}/embed/gallery/{site.id}" '
                    f'width="{width}" height="{height}" frameborder="0" '
                    f'style="border:1px solid #ccc;border-radius:4px;"></iframe>',
            'width': width,
            'height': height,
        })

        return response

    def _mirror_response(self, path, maxwidth, maxheight):
        """Generate oEmbed response for a mirrored page."""
        # Extract domain from path
        parts = path.split('/', 1)
        domain = parts[0]

        width = min(maxwidth, 800)
        height = min(maxheight, 600)

        response = self._base_response()
        response.update({
            'type': 'rich',
            'title': f'Mirror: {domain}',
            'html': f'<iframe src="{self.base_url}/embed/mirror/{path}" '
                    f'width="{width}" height="{height}" frameborder="0" '
                    f'style="border:1px solid #ccc;border-radius:4px;"></iframe>',
            'width': width,
            'height': height,
        })

        return response

    def _media_response(self, path, maxwidth, maxheight):
        """Generate oEmbed response for an image file."""
        # Validate it's an image
        image_extensions = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg')
        if not path.lower().endswith(image_extensions):
            return None

        full_path = os.path.join(MIRRORS_BASE_PATH, path)
        if not os.path.exists(full_path):
            return None

        # Get image dimensions
        width, height = maxwidth, maxheight
        try:
            if not path.lower().endswith('.svg'):
                with Image.open(full_path) as img:
                    orig_width, orig_height = img.size
                    # Scale to fit within max dimensions
                    ratio = min(maxwidth / orig_width, maxheight / orig_height)
                    if ratio < 1:
                        width = int(orig_width * ratio)
                        height = int(orig_height * ratio)
                    else:
                        width, height = orig_width, orig_height
        except Exception:
            pass

        response = self._base_response()
        response.update({
            'type': 'photo',
            'url': f'{self.base_url}/media/{path}',
            'width': width,
            'height': height,
        })

        return response

    def _video_response(self, video_id, maxwidth, maxheight):
        """Generate oEmbed response for a YouTube video."""
        from app.models import Video

        video = Video.query.get(video_id)
        if not video:
            return None

        width = min(maxwidth, 640)
        height = min(maxheight, 360)

        # Maintain 16:9 aspect ratio
        if width / height > 16 / 9:
            width = int(height * 16 / 9)
        else:
            height = int(width * 9 / 16)

        response = self._base_response()
        response.update({
            'type': 'video',
            'title': video.title,
            'author_name': video.site.name if video.site else None,
            'thumbnail_url': f'{self.base_url}/video/{video.site_id}/{video.video_id}/thumbnail.jpg',
            'html': f'<iframe src="{self.base_url}/embed/video/{video.id}" '
                    f'width="{width}" height="{height}" frameborder="0" '
                    f'allowfullscreen style="border:1px solid #ccc;border-radius:4px;"></iframe>',
            'width': width,
            'height': height,
        })

        return response

    def _search_response(self, query, maxwidth, maxheight):
        """Generate oEmbed response for search results."""
        if not query:
            return None

        width = min(maxwidth, 600)
        height = min(maxheight, 400)

        from urllib.parse import quote
        encoded_query = quote(query)

        response = self._base_response()
        response.update({
            'type': 'rich',
            'title': f'Ricerca: {query}',
            'html': f'<iframe src="{self.base_url}/embed/search?q={encoded_query}" '
                    f'width="{width}" height="{height}" frameborder="0" '
                    f'style="border:1px solid #ccc;border-radius:4px;"></iframe>',
            'width': width,
            'height': height,
        })

        return response


def get_oembed_discovery_url(request_url, base_url):
    """
    Generate oEmbed discovery URL for a page.

    Args:
        request_url: Current page URL
        base_url: Base URL of Speculum

    Returns:
        oEmbed endpoint URL with encoded page URL
    """
    from urllib.parse import quote
    return f'{base_url}/oembed?url={quote(request_url)}&format=json'
