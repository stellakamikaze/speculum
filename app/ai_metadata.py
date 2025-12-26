"""
AI-powered metadata generation for crawled sites.
Analyzes downloaded HTML to generate name, description, and category.
"""
import os
import re
import logging
from html.parser import HTMLParser

logger = logging.getLogger(__name__)

MIRRORS_BASE_PATH = os.environ.get('MIRRORS_PATH', '/mirrors')


class HTMLMetadataParser(HTMLParser):
    """Extract metadata from HTML"""

    def __init__(self):
        super().__init__()
        self.title = None
        self.description = None
        self.keywords = None
        self.h1 = None
        self.og_title = None
        self.og_description = None
        self._in_title = False
        self._in_h1 = False
        self._h1_found = False

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)

        if tag == 'title':
            self._in_title = True

        elif tag == 'h1' and not self._h1_found:
            self._in_h1 = True

        elif tag == 'meta':
            name = attrs_dict.get('name', '').lower()
            prop = attrs_dict.get('property', '').lower()
            content = attrs_dict.get('content', '')

            if name == 'description':
                self.description = content
            elif name == 'keywords':
                self.keywords = content
            elif prop == 'og:title':
                self.og_title = content
            elif prop == 'og:description':
                self.og_description = content

    def handle_endtag(self, tag):
        if tag == 'title':
            self._in_title = False
        elif tag == 'h1':
            self._in_h1 = False
            self._h1_found = True

    def handle_data(self, data):
        if self._in_title and not self.title:
            self.title = data.strip()
        elif self._in_h1 and not self.h1:
            self.h1 = data.strip()


def extract_html_metadata(mirror_path: str) -> dict:
    """
    Extract metadata from the index.html of a mirrored site.

    Args:
        mirror_path: Path to the mirror directory

    Returns:
        dict with title, description, keywords, h1 keys
    """
    result = {
        'title': None,
        'description': None,
        'keywords': None,
        'h1': None
    }

    # Find index.html
    index_path = None
    if os.path.isdir(mirror_path):
        # Try direct index.html
        direct = os.path.join(mirror_path, 'index.html')
        if os.path.exists(direct):
            index_path = direct
        else:
            # Search subdirectories
            for root, dirs, files in os.walk(mirror_path):
                depth = root[len(mirror_path):].count(os.sep)
                if depth > 3:
                    continue
                if 'index.html' in files:
                    index_path = os.path.join(root, 'index.html')
                    break

    if not index_path or not os.path.exists(index_path):
        logger.warning(f"No index.html found in {mirror_path}")
        return result

    try:
        # Read HTML with error handling for encoding issues
        with open(index_path, 'r', encoding='utf-8', errors='ignore') as f:
            html = f.read()

        parser = HTMLMetadataParser()
        parser.feed(html)

        result['title'] = parser.og_title or parser.title
        result['description'] = parser.og_description or parser.description
        result['keywords'] = parser.keywords
        result['h1'] = parser.h1

        # Clean up title if it has common separators
        if result['title']:
            # Remove common suffix patterns like " | Site Name" or " - Site Name"
            result['title'] = re.split(r'\s*[\|–—-]\s*', result['title'])[0].strip()

    except Exception as e:
        logger.error(f"Error parsing HTML at {index_path}: {e}")

    return result


def generate_ai_metadata(site_id: int) -> dict | None:
    """
    Generate AI metadata for a site using its downloaded content.

    Args:
        site_id: The site ID to process

    Returns:
        dict with name, description, category, confidence keys, or None
    """
    from app.models import Site, Category
    from app import create_app
    from app.ollama_client import check_ollama_available, OLLAMA_URL, OLLAMA_MODEL
    import requests
    import json

    app = create_app()

    with app.app_context():
        site = Site.query.get(site_id)
        if not site:
            return None

        # Get mirror path
        from urllib.parse import urlparse
        if site.site_type == 'youtube':
            return None  # Skip YouTube channels

        parsed = urlparse(site.url)
        mirror_path = os.path.join(MIRRORS_BASE_PATH, parsed.netloc)

        # Extract HTML metadata
        html_meta = extract_html_metadata(mirror_path)

        if not any(html_meta.values()):
            logger.warning(f"No metadata found in HTML for {site.url}")
            return None

        if not check_ollama_available():
            # Fallback: use HTML title as name
            if html_meta['title']:
                return {
                    'name': html_meta['title'][:200],
                    'description': html_meta['description'][:500] if html_meta['description'] else None,
                    'category': None,
                    'confidence': 0.5
                }
            return None

        # Get existing categories
        existing_categories = [c.name for c in Category.query.all()]

        # Build prompt with extracted metadata
        prompt = f"""Analizza questi metadati di un sito web archiviato:

Titolo HTML: {html_meta['title'] or 'Non disponibile'}
Meta description: {html_meta['description'] or 'Non disponibile'}
Keywords: {html_meta['keywords'] or 'Non disponibile'}
Primo H1: {html_meta['h1'] or 'Non disponibile'}
URL: {site.url}

Categorie esistenti: {', '.join(existing_categories) if existing_categories else 'Nessuna'}

Rispondi SOLO con JSON valido:
{{"name": "nome breve e descrittivo in italiano (max 50 char)", "description": "descrizione del contenuto in italiano (max 200 char)", "category": "categoria esistente o nuova appropriata", "confidence": 0.0-1.0}}"""

        try:
            response = requests.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.3,
                        "num_predict": 200
                    }
                },
                timeout=120
            )

            if response.status_code == 200:
                result = response.json()
                text = result.get('response', '').strip()

                # Extract JSON from response
                start = text.find('{')
                end = text.rfind('}') + 1
                if start >= 0 and end > start:
                    json_str = text[start:end]
                    metadata = json.loads(json_str)
                    return {
                        'name': metadata.get('name', '')[:200],
                        'description': metadata.get('description', '')[:500],
                        'category': metadata.get('category', ''),
                        'confidence': float(metadata.get('confidence', 0.7))
                    }

        except Exception as e:
            logger.error(f"Error generating AI metadata: {e}")

        # Fallback
        if html_meta['title']:
            return {
                'name': html_meta['title'][:200],
                'description': html_meta['description'][:500] if html_meta['description'] else None,
                'category': None,
                'confidence': 0.3
            }

        return None


def update_site_with_ai_metadata(site_id: int) -> bool:
    """
    Update a site with AI-generated metadata.

    Args:
        site_id: The site ID to update

    Returns:
        True if updated successfully
    """
    from app.models import db, Site, Category
    from app import create_app

    metadata = generate_ai_metadata(site_id)
    if not metadata:
        return False

    app = create_app()

    with app.app_context():
        site = Site.query.get(site_id)
        if not site:
            return False

        # Update name if current is just the domain
        from urllib.parse import urlparse
        current_is_domain = site.name == urlparse(site.url).netloc
        if current_is_domain and metadata.get('name'):
            site.name = metadata['name']

        # Update description if empty
        if not site.description and metadata.get('description'):
            site.description = metadata['description']

        # Update category if empty and AI suggests one
        if not site.category_id and metadata.get('category'):
            cat_name = metadata['category']
            category = Category.query.filter_by(name=cat_name).first()
            if not category:
                category = Category(name=cat_name)
                db.session.add(category)
                db.session.flush()
            site.category_id = category.id

        site.ai_generated = True
        db.session.commit()

        logger.info(f"Updated site {site.id} with AI metadata: {metadata}")
        return True


def process_pending_ai_metadata():
    """
    Process all sites that are ready but don't have AI metadata.
    Intended for batch processing.
    """
    from app.models import Site
    from app import create_app

    app = create_app()

    with app.app_context():
        # Find sites that are ready but don't have AI-generated metadata
        sites = Site.query.filter(
            Site.status == 'ready',
            Site.ai_generated == False,
            Site.site_type == 'website'
        ).all()

        logger.info(f"Processing AI metadata for {len(sites)} sites")

        for site in sites:
            try:
                success = update_site_with_ai_metadata(site.id)
                if success:
                    logger.info(f"AI metadata generated for {site.url}")
            except Exception as e:
                logger.error(f"Error processing AI metadata for {site.url}: {e}")
