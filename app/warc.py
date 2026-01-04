"""
WARC (Web ARChive) export module for Speculum.
Exports archived sites in ISO 28500 WARC format.

WARC is the standard format used by:
- Internet Archive
- Library of Congress
- Most national web archives

References:
- ISO 28500:2017
- https://iipc.github.io/warc-specifications/
"""
import os
import gzip
import logging
from datetime import datetime
from urllib.parse import urlparse
import mimetypes

logger = logging.getLogger(__name__)

MIRRORS_BASE_PATH = os.environ.get('MIRRORS_PATH', '/mirrors')


class WARCWriter:
    """
    Simple WARC writer that creates valid WARC 1.1 files.
    Does not require external dependencies.
    """

    WARC_VERSION = 'WARC/1.1'

    def __init__(self, output_path, compress=True):
        """
        Initialize WARC writer.

        Args:
            output_path: Path to output WARC file
            compress: Whether to gzip compress (default True, creates .warc.gz)
        """
        self.output_path = output_path
        self.compress = compress
        self.record_count = 0
        self._file = None

    def __enter__(self):
        if self.compress:
            self._file = gzip.open(self.output_path, 'wb')
        else:
            self._file = open(self.output_path, 'wb')
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._file:
            self._file.close()

    def _generate_uuid(self):
        """Generate a UUID for WARC record ID."""
        import uuid
        return f'<urn:uuid:{uuid.uuid4()}>'

    def _format_date(self, dt=None):
        """Format datetime for WARC header."""
        if dt is None:
            dt = datetime.utcnow()
        return dt.strftime('%Y-%m-%dT%H:%M:%SZ')

    def write_warcinfo(self, software='Speculum', description=None):
        """Write the warcinfo record (metadata about the WARC file)."""
        content_lines = [
            f'software: {software}',
            'format: WARC File Format 1.1',
            f'conformsTo: http://bibnum.bnf.fr/WARC/WARC_ISO_28500_version1-1_latestdraft.pdf',
        ]
        if description:
            content_lines.append(f'description: {description}')

        content = '\r\n'.join(content_lines).encode('utf-8')

        headers = [
            self.WARC_VERSION,
            f'WARC-Type: warcinfo',
            f'WARC-Date: {self._format_date()}',
            f'WARC-Record-ID: {self._generate_uuid()}',
            f'Content-Type: application/warc-fields',
            f'Content-Length: {len(content)}',
        ]

        self._write_record(headers, content)

    def write_resource(self, uri, content, content_type=None, fetch_time=None):
        """
        Write a resource record (the actual archived content).

        Args:
            uri: Original URI of the resource
            content: The content bytes
            content_type: MIME type (will be guessed if not provided)
            fetch_time: When the content was fetched
        """
        if content_type is None:
            content_type = mimetypes.guess_type(uri)[0] or 'application/octet-stream'

        headers = [
            self.WARC_VERSION,
            f'WARC-Type: resource',
            f'WARC-Target-URI: {uri}',
            f'WARC-Date: {self._format_date(fetch_time)}',
            f'WARC-Record-ID: {self._generate_uuid()}',
            f'Content-Type: {content_type}',
            f'Content-Length: {len(content)}',
        ]

        self._write_record(headers, content)
        self.record_count += 1

    def write_metadata(self, uri, metadata_dict, refers_to=None):
        """Write a metadata record."""
        content_lines = [f'{k}: {v}' for k, v in metadata_dict.items()]
        content = '\r\n'.join(content_lines).encode('utf-8')

        headers = [
            self.WARC_VERSION,
            f'WARC-Type: metadata',
            f'WARC-Target-URI: {uri}',
            f'WARC-Date: {self._format_date()}',
            f'WARC-Record-ID: {self._generate_uuid()}',
            f'Content-Type: application/warc-fields',
            f'Content-Length: {len(content)}',
        ]

        if refers_to:
            headers.insert(5, f'WARC-Refers-To: {refers_to}')

        self._write_record(headers, content)

    def _write_record(self, headers, content):
        """Write a complete WARC record."""
        # Write headers
        header_block = '\r\n'.join(headers) + '\r\n\r\n'
        self._file.write(header_block.encode('utf-8'))

        # Write content
        self._file.write(content)

        # Write record separator (two CRLFs)
        self._file.write(b'\r\n\r\n')


def export_site_to_warc(site, output_dir=None):
    """
    Export a site's mirror to WARC format.

    Args:
        site: Site model instance
        output_dir: Output directory (default: /mirrors/_warc)

    Returns:
        Path to created WARC file, or None on error
    """
    if output_dir is None:
        output_dir = os.path.join(MIRRORS_BASE_PATH, '_warc')

    os.makedirs(output_dir, exist_ok=True)

    # Build output filename
    safe_name = ''.join(c if c.isalnum() or c in '-_' else '_' for c in site.name[:50])
    timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
    output_path = os.path.join(output_dir, f'{safe_name}_{timestamp}.warc.gz')

    # Get mirror path
    mirror_path = site._get_mirror_path()
    full_mirror_path = os.path.join(MIRRORS_BASE_PATH, mirror_path)

    if not os.path.exists(full_mirror_path):
        logger.error(f"Mirror path does not exist: {full_mirror_path}")
        return None

    try:
        with WARCWriter(output_path, compress=True) as writer:
            # Write warcinfo
            writer.write_warcinfo(
                software=f'Speculum Web Archive',
                description=f'Archive of {site.url}'
            )

            # Write metadata about the site
            metadata = {
                'speculum-site-id': str(site.id),
                'speculum-site-name': site.name,
                'speculum-site-type': site.site_type,
                'speculum-crawl-date': site.last_crawl.isoformat() if site.last_crawl else '',
                'speculum-original-url': site.url,
            }
            if site.description:
                metadata['speculum-description'] = site.description

            writer.write_metadata(site.url, metadata)

            # Walk through all files in the mirror
            base_url = site.url.rstrip('/')
            parsed = urlparse(site.url)

            for root, dirs, files in os.walk(full_mirror_path):
                # Skip special directories
                dirs[:] = [d for d in dirs if not d.startswith('_')]

                for filename in files:
                    # Skip special files
                    if filename.startswith('_') or filename.startswith('.'):
                        continue

                    file_path = os.path.join(root, filename)
                    rel_path = os.path.relpath(file_path, full_mirror_path)

                    # Reconstruct URL
                    if site.site_type == 'youtube':
                        resource_uri = f'{base_url}/{rel_path}'
                    else:
                        # For websites, use the domain structure
                        resource_uri = f'{parsed.scheme}://{rel_path}'

                    try:
                        with open(file_path, 'rb') as f:
                            content = f.read()

                        writer.write_resource(
                            uri=resource_uri,
                            content=content,
                            fetch_time=site.last_crawl
                        )
                    except Exception as e:
                        logger.warning(f"Error reading {file_path}: {e}")
                        continue

            logger.info(f"Created WARC with {writer.record_count} records: {output_path}")

        # Get file size
        warc_size = os.path.getsize(output_path)

        return {
            'path': output_path,
            'filename': os.path.basename(output_path),
            'size': warc_size,
            'size_human': _human_size(warc_size),
            'record_count': writer.record_count
        }

    except Exception as e:
        logger.error(f"Error creating WARC for site {site.id}: {e}")
        if os.path.exists(output_path):
            os.remove(output_path)
        return None


def list_warc_files():
    """List all WARC files in the export directory."""
    warc_dir = os.path.join(MIRRORS_BASE_PATH, '_warc')

    if not os.path.exists(warc_dir):
        return []

    files = []
    for filename in os.listdir(warc_dir):
        if filename.endswith('.warc.gz') or filename.endswith('.warc'):
            file_path = os.path.join(warc_dir, filename)
            stat = os.stat(file_path)
            files.append({
                'filename': filename,
                'path': file_path,
                'size': stat.st_size,
                'size_human': _human_size(stat.st_size),
                'created': datetime.fromtimestamp(stat.st_mtime).isoformat()
            })

    # Sort by creation time descending
    files.sort(key=lambda x: x['created'], reverse=True)
    return files


def _human_size(size_bytes):
    """Convert bytes to human readable size."""
    if not size_bytes:
        return '0 B'
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"
