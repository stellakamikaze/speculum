"""
Screenshot generation for mirrored sites.
Uses Playwright for high-quality screenshots of the local mirror.
"""
import os
import logging
from datetime import datetime
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

MIRRORS_BASE_PATH = os.environ.get('MIRRORS_PATH', '/mirrors')
SCREENSHOT_WIDTH = 1280
SCREENSHOT_HEIGHT = 800
THUMBNAIL_WIDTH = 400
THUMBNAIL_HEIGHT = 300

# Check if Playwright is available
PLAYWRIGHT_AVAILABLE = False
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    logger.warning("Playwright not installed - screenshots disabled")


def find_index_html(mirror_path: str) -> str | None:
    """Find the index.html file in a mirror directory"""
    if not os.path.isdir(mirror_path):
        return None

    # Check direct index.html
    direct = os.path.join(mirror_path, 'index.html')
    if os.path.exists(direct):
        return direct

    # Search subdirectories
    for root, dirs, files in os.walk(mirror_path):
        depth = root[len(mirror_path):].count(os.sep)
        if depth > 3:
            continue
        if 'index.html' in files:
            return os.path.join(root, 'index.html')

    return None


def capture_screenshot(html_path: str, output_path: str,
                       width: int = SCREENSHOT_WIDTH,
                       height: int = SCREENSHOT_HEIGHT) -> bool:
    """
    Capture a screenshot of a local HTML file using Playwright.

    Args:
        html_path: Path to the HTML file to screenshot
        output_path: Path where to save the screenshot
        width: Viewport width
        height: Viewport height

    Returns:
        True if successful
    """
    if not PLAYWRIGHT_AVAILABLE:
        logger.warning("Playwright not available for screenshots")
        return False

    if not os.path.exists(html_path):
        logger.error(f"HTML file not found: {html_path}")
        return False

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            # Use chromium in headless mode
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': width, 'height': height})

            # Load the local HTML file
            file_url = f"file://{os.path.abspath(html_path)}"
            page.goto(file_url, wait_until='networkidle', timeout=30000)

            # Wait a bit for any animations/lazy loading
            page.wait_for_timeout(1000)

            # Ensure output directory exists
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            # Take screenshot
            page.screenshot(path=output_path, full_page=False)

            browser.close()

        logger.info(f"Screenshot saved: {output_path}")
        return True

    except Exception as e:
        logger.error(f"Screenshot capture failed: {e}")
        return False


def generate_thumbnail(screenshot_path: str, thumb_path: str,
                       size: tuple = (THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT)) -> bool:
    """
    Generate a thumbnail from a screenshot.

    Args:
        screenshot_path: Path to the full screenshot
        thumb_path: Path for the thumbnail
        size: Thumbnail size as (width, height)

    Returns:
        True if successful
    """
    try:
        from PIL import Image

        with Image.open(screenshot_path) as img:
            # Convert to RGB if necessary (for PNG with transparency)
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')

            # Calculate resize to cover
            img_ratio = img.width / img.height
            target_ratio = size[0] / size[1]

            if img_ratio > target_ratio:
                # Image is wider, fit to height
                new_height = size[1]
                new_width = int(new_height * img_ratio)
            else:
                # Image is taller, fit to width
                new_width = size[0]
                new_height = int(new_width / img_ratio)

            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

            # Crop to exact size
            left = (new_width - size[0]) // 2
            top = 0  # Crop from top for websites
            img = img.crop((left, top, left + size[0], top + size[1]))

            # Ensure output directory exists
            os.makedirs(os.path.dirname(thumb_path), exist_ok=True)

            # Save as JPEG with good quality
            img.save(thumb_path, 'JPEG', quality=85)

        logger.info(f"Thumbnail saved: {thumb_path}")
        return True

    except ImportError:
        logger.warning("Pillow not installed - thumbnails disabled")
        return False
    except Exception as e:
        logger.error(f"Thumbnail generation failed: {e}")
        return False


def capture_site_screenshot(site_id: int) -> str | None:
    """
    Capture screenshot for a site and save it to the mirror directory.

    Args:
        site_id: The site ID to screenshot

    Returns:
        Relative path to the screenshot, or None if failed
    """
    from app.models import Site
    from app import create_app

    if not PLAYWRIGHT_AVAILABLE:
        return None

    app = create_app()

    with app.app_context():
        site = Site.query.get(site_id)
        if not site or site.site_type == 'youtube':
            return None

        if site.status != 'ready':
            logger.warning(f"Site {site_id} not ready for screenshot")
            return None

        # Get mirror path
        parsed = urlparse(site.url)
        mirror_path = os.path.join(MIRRORS_BASE_PATH, parsed.netloc)

        # Find index.html
        index_path = find_index_html(mirror_path)
        if not index_path:
            logger.warning(f"No index.html found for {site.url}")
            return None

        # Create _speculum directory for metadata files
        speculum_dir = os.path.join(mirror_path, '_speculum')
        os.makedirs(speculum_dir, exist_ok=True)

        screenshot_path = os.path.join(speculum_dir, 'screenshot.png')
        thumb_path = os.path.join(speculum_dir, 'thumbnail.jpg')

        # Capture screenshot
        if not capture_screenshot(index_path, screenshot_path):
            return None

        # Generate thumbnail
        generate_thumbnail(screenshot_path, thumb_path)

        # Return relative path
        return f"{parsed.netloc}/_speculum/screenshot.png"


def update_site_screenshot(site_id: int) -> bool:
    """
    Update a site's screenshot and save the path to the database.

    Args:
        site_id: The site ID to update

    Returns:
        True if successful
    """
    from app.models import db, Site
    from app import create_app

    screenshot_path = capture_site_screenshot(site_id)
    if not screenshot_path:
        return False

    app = create_app()

    with app.app_context():
        site = Site.query.get(site_id)
        if site:
            site.screenshot_path = screenshot_path
            site.screenshot_date = datetime.utcnow()
            db.session.commit()
            logger.info(f"Screenshot updated for site {site_id}")
            return True

    return False


def is_screenshot_available() -> bool:
    """Check if screenshot functionality is available"""
    return PLAYWRIGHT_AVAILABLE
