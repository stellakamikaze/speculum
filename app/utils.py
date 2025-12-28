"""
Utility functions for URL validation and normalization.
"""
import re
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
import logging

logger = logging.getLogger(__name__)

# Tracking parameters to remove during normalization
TRACKING_PARAMS = {
    'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
    'fbclid', 'gclid', 'msclkid', 'dclid',
    'ref', 'source', 'mc_cid', 'mc_eid',
    '_ga', '_gl', 'fb_action_ids', 'fb_action_types',
}

# Regex for extracting URLs from mixed text
URL_PATTERN = re.compile(
    r'https?://'  # http:// or https://
    r'(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+'  # domain
    r'[a-zA-Z]{2,}'  # TLD
    r'(?::\d+)?'  # optional port
    r'(?:/[^\s\)\]\}"\'<>]*)?',  # optional path
    re.IGNORECASE
)


def extract_url(text: str) -> str | None:
    """
    Extract a valid URL from a line of mixed text.

    Args:
        text: A line that may contain a URL mixed with other text

    Returns:
        The extracted URL or None if no valid URL found
    """
    if not text or not text.strip():
        return None

    text = text.strip()

    # Try to find a URL in the text
    match = URL_PATTERN.search(text)
    if not match:
        return None

    url = match.group(0)

    # Strip trailing punctuation that's not part of URL
    url = url.rstrip('.,;:!?\'"')

    # Handle trailing parentheses (common in markdown)
    while url.endswith(')') and url.count(')') > url.count('('):
        url = url[:-1]

    # Validate the extracted URL
    is_valid, _ = validate_url(url)
    if not is_valid:
        return None

    return url


def normalize_url(url: str) -> str:
    """
    Normalize a URL by:
    - Converting to lowercase domain
    - Removing trailing slashes
    - Removing tracking parameters
    - Ensuring https when possible

    Args:
        url: The URL to normalize

    Returns:
        The normalized URL
    """
    if not url:
        return url

    try:
        parsed = urlparse(url)

        # Lowercase the domain
        netloc = parsed.netloc.lower()

        # Remove www. prefix for consistency (optional, comment out if not wanted)
        # if netloc.startswith('www.'):
        #     netloc = netloc[4:]

        # Remove tracking parameters
        if parsed.query:
            params = parse_qs(parsed.query, keep_blank_values=True)
            filtered_params = {
                k: v for k, v in params.items()
                if k.lower() not in TRACKING_PARAMS
            }
            query = urlencode(filtered_params, doseq=True)
        else:
            query = ''

        # Remove trailing slash from path (but keep root /)
        path = parsed.path
        if path != '/' and path.endswith('/'):
            path = path.rstrip('/')

        # Reconstruct URL
        normalized = urlunparse((
            parsed.scheme,
            netloc,
            path,
            parsed.params,
            query,
            ''  # Remove fragment
        ))

        return normalized

    except Exception as e:
        logger.warning(f"Failed to normalize URL {url}: {e}")
        return url


def is_internal_url(hostname: str) -> bool:
    """
    Check if a hostname points to an internal/private network address.
    Used to prevent SSRF attacks.
    """
    if not hostname:
        return True

    hostname = hostname.lower()

    # Localhost variants
    if hostname in ('localhost', '127.0.0.1', '0.0.0.0', '::1'):
        return True

    # Private IP ranges
    if hostname.startswith('192.168.') or hostname.startswith('10.'):
        return True
    if hostname.startswith('172.'):
        # 172.16.0.0 - 172.31.255.255
        try:
            second_octet = int(hostname.split('.')[1])
            if 16 <= second_octet <= 31:
                return True
        except (ValueError, IndexError):
            pass

    # Link-local addresses
    if hostname.startswith('169.254.'):
        return True

    # Internal Docker/container hostnames
    if hostname in ('host.docker.internal', 'gateway.docker.internal'):
        return True

    # Metadata endpoints (cloud providers)
    if hostname in ('metadata.google.internal', '169.254.169.254'):
        return True

    return False


def validate_url(url: str) -> tuple[bool, str]:
    """
    Validate a URL for basic correctness and security.

    Args:
        url: The URL to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not url:
        return False, "URL vuoto"

    # Must start with http:// or https://
    if not url.startswith(('http://', 'https://')):
        return False, "URL deve iniziare con http:// o https://"

    try:
        parsed = urlparse(url)

        # Must have a valid scheme
        if parsed.scheme not in ('http', 'https'):
            return False, "Schema non valido"

        # Must have a domain
        if not parsed.netloc:
            return False, "Dominio mancante"

        # Extract hostname (without port)
        hostname = parsed.hostname or ''

        # Domain must have at least one dot (TLD)
        if '.' not in hostname:
            return False, "Dominio non valido (manca TLD)"

        # SECURITY: Block internal/private URLs (SSRF protection)
        if is_internal_url(hostname):
            return False, "URL interno non consentito"

        # Check for common malformed URLs
        if ' ' in url:
            return False, "URL contiene spazi"

        if hostname.startswith('-') or hostname.endswith('-'):
            return False, "Dominio non valido"

        return True, ""

    except Exception as e:
        return False, f"Errore parsing URL: {str(e)}"
