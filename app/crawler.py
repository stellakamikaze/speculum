import subprocess
import os
import shutil
import json
import re
from datetime import datetime, timedelta
from urllib.parse import urlparse
from threading import Thread, Lock
from queue import Queue, Empty
import logging
import signal

logger = logging.getLogger(__name__)

MIRRORS_BASE_PATH = os.environ.get('MIRRORS_PATH', '/mirrors')

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAYS = [5, 15, 45]  # minuti tra i retry (backoff esponenziale)
DEFAULT_TIMEOUT = 3600  # 1 ora default
LARGE_SITE_TIMEOUT = 3600 * 4  # 4 ore per siti grandi

# Active crawl processes tracking
active_crawls = {}  # site_id -> {'process': Popen, 'thread': Thread, 'started': datetime}
crawls_lock = Lock()

# Errori recuperabili (retry)
RECOVERABLE_ERRORS = [
    'timed out', 'timeout', 'connection refused', 'connection reset',
    'temporary failure', 'service unavailable', '503', '502', '504',
    'too many requests', '429',
]

# Errori permanenti (no retry)
PERMANENT_ERRORS = [
    '404', '403', '401', 'not found', 'forbidden', 'unauthorized',
    'name or service not known', 'no such host', 'ssl certificate',
    'certificate verify failed',
]


def classify_error(error_message):
    if not error_message:
        return 'unknown'
    error_lower = error_message.lower()
    for pattern in PERMANENT_ERRORS:
        if pattern in error_lower:
            return 'permanent'
    for pattern in RECOVERABLE_ERRORS:
        if pattern in error_lower:
            return 'recoverable'
    return 'unknown'


def should_retry(site):
    retry_count = site.retry_count or 0
    if retry_count >= MAX_RETRIES:
        return False
    if classify_error(site.error_message) == 'permanent':
        return False
    return True


def get_retry_delay(retry_count):
    if retry_count < len(RETRY_DELAYS):
        return RETRY_DELAYS[retry_count]
    return RETRY_DELAYS[-1]


def get_timeout_for_site(site):
    if site.size_bytes and site.size_bytes > 100 * 1024 * 1024:
        return LARGE_SITE_TIMEOUT
    large_patterns = ['archive.org', 'wikipedia', 'magiclibrarities']
    for pattern in large_patterns:
        if pattern in site.url.lower():
            return LARGE_SITE_TIMEOUT
    return DEFAULT_TIMEOUT


def get_mirror_path(url, site_type='website', channel_id=None):
    if site_type == 'youtube' and channel_id:
        return os.path.join(MIRRORS_BASE_PATH, 'youtube', channel_id)
    parsed = urlparse(url)
    return os.path.join(MIRRORS_BASE_PATH, parsed.netloc)


def get_mirror_stats(path):
    """Get mirror size and HTML count in a single os.walk() pass"""
    total_size = 0
    html_count = 0
    if os.path.exists(path):
        for dirpath, dirnames, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if os.path.exists(fp):
                    total_size += os.path.getsize(fp)
                if f.endswith(('.html', '.htm')):
                    html_count += 1
    return total_size, html_count


# Backward-compatible wrappers (will be removed after updating callers)
def get_mirror_size(path):
    size, _ = get_mirror_stats(path)
    return size


def count_html_files(path):
    _, count = get_mirror_stats(path)
    return count


def is_youtube_url(url):
    return bool(re.search(r'(youtube\.com|youtu\.be)', url))


def get_youtube_channel_info(url):
    try:
        result = subprocess.run(
            ['yt-dlp', '--dump-json', '--playlist-items', '1', url],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout.strip())
            return {
                'channel_id': data.get('channel_id'),
                'channel': data.get('channel') or data.get('uploader'),
                'thumbnail': data.get('thumbnail')
            }
    except Exception as e:
        logger.error(f"Error getting channel info: {e}")
    return None


def normalize_url(url):
    """Normalize URL for crawling - extract root domain from deep URLs.

    Returns:
        tuple: (root_url, original_url) - root URL of the domain and original URL
    """
    parsed = urlparse(url)
    # Always include the scheme and netloc
    root_url = f"{parsed.scheme}://{parsed.netloc}/"
    return root_url, url


def get_crawl_urls(url):
    """Get list of URLs to crawl. Always includes root URL to capture homepage.

    When given a deep URL like example.com/page/subpage, we crawl:
    1. The root URL (example.com/) to get the homepage
    2. The original URL to ensure that specific page is captured

    Returns:
        list: URLs to crawl (root first, then original if different)
    """
    root_url, original_url = normalize_url(url)

    # If the original URL is already the root, just return it
    if original_url.rstrip('/') == root_url.rstrip('/'):
        return [root_url]

    # Return both: root first (to get homepage), then original
    return [root_url, original_url]


def build_wget_command(url, output_path, depth=1, include_external=False, archive_media=True):
    """Build wget command with best practices for complete site archiving.

    Best practices implemented:
    - Proper rate limiting to avoid server overload
    - Comprehensive error handling and retries
    - Proper content-type handling
    - Server-friendly headers
    - Full media archiving (videos, images, etc.) for complete preservation
    """
    cmd = [
        'wget', '--mirror', '--convert-links', '--adjust-extension',
        '--page-requisites', '--no-parent',
        # Rate limiting - be respectful to servers
        '--wait=1', '--random-wait',
        # Reliability settings
        '--tries=5', '--timeout=60', '--read-timeout=60',
        '--retry-connrefused', '--retry-on-http-error=503,429',
        # SSL handling
        '--no-check-certificate',
        # Crawl control
        '--execute=robots=off',  # Many archived sites have expired robots.txt
        '--max-redirect=10',
        # Content handling
        '--content-disposition',  # Use server-provided filenames
        '--trust-server-names',  # Trust server for URL to filename mapping
        # HTTP headers - mimic a real browser
        '--header=Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        '--header=Accept-Language: en-US,en;q=0.9,it;q=0.8',
        '--header=Accept-Encoding: identity',  # Avoid compressed responses for better archiving
        '--header=Connection: keep-alive',
        '--header=DNT: 1',
        '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        # Output settings
        '-P', output_path,
        '--no-verbose', '--show-progress',  # Cleaner output
    ]
    # depth=0 means infinite, depth>0 limits crawl depth
    if depth == 0:
        pass  # No -l flag = infinite depth
    else:
        cmd.extend(['-l', str(depth)])
    if include_external:
        cmd.append('--span-hosts')
        cmd.append('--domains=' + urlparse(url).netloc)

    # Media archiving: only reject potentially dangerous executables
    # Keep videos, PDFs, and other content that might be part of the site
    if archive_media:
        # Only reject dangerous/executable files
        cmd.extend(['--reject', '*.exe,*.msi,*.dmg,*.pkg,*.deb,*.rpm'])
    else:
        # Reject large files for quick archiving
        cmd.extend(['--reject', '*.exe,*.zip,*.tar.gz,*.rar,*.7z,*.iso,*.dmg,*.mp4,*.webm,*.avi,*.mov,*.mkv,*.flv'])

    cmd.append(url)
    return cmd


def _output_reader(pipe, queue):
    """Thread function to read process output without blocking"""
    try:
        for line in iter(pipe.readline, ''):
            queue.put(line)
    except (IOError, ValueError) as e:
        logger.debug(f"Output reader stopped: {e}")
    finally:
        try:
            pipe.close()
        except (IOError, ValueError):
            pass


def mark_crawl_success(site, crawl_log, size_bytes, page_count):
    """Mark site and log as successfully crawled"""
    site.status = 'ready'
    site.last_crawl = datetime.utcnow()
    site.next_crawl = datetime.utcnow() + timedelta(days=site.crawl_interval_days)
    site.size_bytes = size_bytes
    site.page_count = page_count
    site.error_message = None
    site.retry_count = 0

    crawl_log.finished_at = datetime.utcnow()
    crawl_log.status = 'success'
    crawl_log.pages_crawled = page_count
    crawl_log.size_bytes = size_bytes


def handle_crawl_error(site, crawl_log, error_message, db):
    logger.error(f"Crawl error for {site.url}: {error_message}")
    site.error_message = error_message
    site.retry_count = (site.retry_count or 0) + 1
    crawl_log.finished_at = datetime.utcnow()
    crawl_log.status = 'error'
    crawl_log.error_message = error_message
    
    if should_retry(site):
        delay = get_retry_delay(site.retry_count - 1)
        site.next_crawl = datetime.utcnow() + timedelta(minutes=delay)
        site.status = 'retry_pending'
        logger.info(f"Retry scheduled for {site.url} in {delay}min (attempt {site.retry_count}/{MAX_RETRIES})")
    else:
        error_type = classify_error(error_message)
        site.status = 'dead' if error_type == 'permanent' else 'error'
        logger.info(f"No retry for {site.url}: {error_type}")


def _run_wget_process(cmd, site_id, crawl_log_id, timeout, no_output_timeout=300):
    """Run a wget process with real-time output capture and timeout handling.

    Returns:
        tuple: (returncode, log_lines)
    """
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    # Set up non-blocking output reading via queue
    output_queue = Queue()
    reader_thread = Thread(target=_output_reader, args=(process.stdout, output_queue), daemon=True)
    reader_thread.start()

    # Register active crawl
    with crawls_lock:
        active_crawls[site_id] = {
            'process': process,
            'started': datetime.utcnow(),
            'log_lines': [],
            'crawl_log_id': crawl_log_id
        }

    # Read output non-blocking with timeout
    log_buffer = []
    start_time = datetime.utcnow()
    last_output_time = datetime.utcnow()

    while True:
        # Check if process finished
        if process.poll() is not None:
            # Drain remaining output
            while True:
                try:
                    line = output_queue.get_nowait()
                    if line:
                        log_buffer.append(line.strip())
                except Empty:
                    break
            break

        # Check total timeout
        elapsed = (datetime.utcnow() - start_time).total_seconds()
        if elapsed > timeout:
            process.kill()
            raise subprocess.TimeoutExpired(cmd, timeout)

        # Check stall timeout (no output for too long)
        stall_time = (datetime.utcnow() - last_output_time).total_seconds()
        if stall_time > no_output_timeout:
            logger.warning(f"Crawl stalled, no output for {no_output_timeout}s")
            process.kill()
            raise Exception(f"Crawl stalled - no output for {no_output_timeout}s")

        # Read available output (non-blocking)
        try:
            line = output_queue.get(timeout=1.0)
            if line:
                last_output_time = datetime.utcnow()
                log_buffer.append(line.strip())
                # Keep last 500 lines in memory for real-time viewing
                with crawls_lock:
                    if site_id in active_crawls:
                        active_crawls[site_id]['log_lines'].append(line.strip())
                        if len(active_crawls[site_id]['log_lines']) > 500:
                            active_crawls[site_id]['log_lines'] = active_crawls[site_id]['log_lines'][-500:]
        except Empty:
            pass  # No output available, continue loop

    # Wait for reader thread to finish
    reader_thread.join(timeout=5)

    return process.returncode, log_buffer


def crawl_website(site_id):
    from app.models import db, Site, CrawlLog
    from app import create_app
    app = create_app()

    with app.app_context():
        site = Site.query.get(site_id)
        if not site:
            return

        site.status = 'crawling'
        site.error_message = None
        db.session.commit()

        crawl_log = CrawlLog(site_id=site.id, started_at=datetime.utcnow(), status='running')
        db.session.add(crawl_log)
        db.session.commit()
        crawl_log_id = crawl_log.id

        mirror_path = get_mirror_path(site.url)
        timeout = get_timeout_for_site(site)

        # Get URLs to crawl (root + original if different)
        urls_to_crawl = get_crawl_urls(site.url)
        logger.info(f"Will crawl URLs: {urls_to_crawl}")

        try:
            all_log_buffer = []

            # Crawl each URL (root first to capture homepage, then original)
            for crawl_url in urls_to_crawl:
                cmd = build_wget_command(crawl_url, MIRRORS_BASE_PATH, site.depth, site.include_external, archive_media=True)
                logger.info(f"Starting crawl for {crawl_url}")

                returncode, log_buffer = _run_wget_process(cmd, site_id, crawl_log_id, timeout)
                all_log_buffer.extend(log_buffer)
                all_log_buffer.append(f"--- Finished crawling {crawl_url} (exit code: {returncode}) ---")

                # wget returns 0 on success, 8 on some errors that are recoverable
                if returncode not in [0, 8]:
                    logger.warning(f"wget returned {returncode} for {crawl_url}, continuing with next URL")

            # Save log to database
            crawl_log = CrawlLog.query.get(crawl_log_id)
            crawl_log.wget_log = '\n'.join(all_log_buffer[-1000:])  # Keep last 1000 lines

            # Check results
            size_bytes, page_count = get_mirror_stats(mirror_path)

            if page_count == 0 and size_bytes < 1000:
                raise Exception("No content downloaded")

            mark_crawl_success(site, crawl_log, size_bytes, page_count)
            logger.info(f"Crawl done: {site.url} - {page_count} pages, {size_bytes} bytes")

            # Generate AI metadata post-crawl
            try:
                from app.ai_metadata import update_site_with_ai_metadata
                db.session.commit()  # Commit crawl success first
                update_site_with_ai_metadata(site_id)
                logger.info(f"AI metadata generated for {site.url}")
            except Exception as e:
                logger.warning(f"AI metadata generation failed for {site.url}: {e}")

        except subprocess.TimeoutExpired:
            handle_crawl_error(site, crawl_log, f'Timeout after {timeout//3600}h', db)
        except Exception as e:
            crawl_log = CrawlLog.query.get(crawl_log_id)
            handle_crawl_error(site, crawl_log, str(e)[:1000], db)
        finally:
            # Remove from active crawls
            with crawls_lock:
                if site_id in active_crawls:
                    del active_crawls[site_id]
            db.session.commit()


def crawl_youtube(site_id):
    from app.models import db, Site, Video, CrawlLog
    from app import create_app
    app = create_app()
    
    with app.app_context():
        site = Site.query.get(site_id)
        if not site:
            return
        
        site.status = 'crawling'
        site.error_message = None
        db.session.commit()
        
        crawl_log = CrawlLog(site_id=site.id, started_at=datetime.utcnow(), status='running')
        db.session.add(crawl_log)
        db.session.commit()
        
        if not site.channel_id:
            info = get_youtube_channel_info(site.url)
            if info and info.get('channel_id'):
                site.channel_id = info['channel_id']
                site.name = info.get('channel', site.name)
                db.session.commit()
        
        mirror_path = get_mirror_path(site.url, 'youtube', site.channel_id)
        os.makedirs(mirror_path, exist_ok=True)
        timeout = LARGE_SITE_TIMEOUT * 3
        
        try:
            cmd = [
                'yt-dlp', '--format', 'bestvideo[height<=1080]+bestaudio/best',
                '--merge-output-format', 'mp4', '--write-info-json', '--write-thumbnail',
                '--output', os.path.join(mirror_path, '%(id)s/%(title)s.%(ext)s'),
                '--restrict-filenames', '--no-overwrites', '--ignore-errors',
                '--sleep-interval', '2', site.url
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            
            video_count = 0
            if os.path.exists(mirror_path):
                for vdir in os.listdir(mirror_path):
                    vpath = os.path.join(mirror_path, vdir)
                    if os.path.isdir(vpath):
                        for f in os.listdir(vpath):
                            if f.endswith('.info.json'):
                                try:
                                    with open(os.path.join(vpath, f)) as jf:
                                        info = json.load(jf)
                                    vid = info.get('id', vdir)
                                    if not Video.query.filter_by(site_id=site.id, video_id=vid).first():
                                        video = Video(site_id=site.id, video_id=vid, title=info.get('title','')[:500], status='ready')
                                        db.session.add(video)
                                        video_count += 1
                                except (json.JSONDecodeError, IOError, KeyError) as e:
                                    logger.warning(f"Failed to parse video info {f}: {e}")
            
            db.session.commit()
            size_bytes = get_mirror_size(mirror_path)
            page_count = Video.query.filter_by(site_id=site.id).count()
            mark_crawl_success(site, crawl_log, size_bytes, page_count)

        except subprocess.TimeoutExpired:
            handle_crawl_error(site, crawl_log, f'Timeout after {timeout//3600}h', db)
        except Exception as e:
            handle_crawl_error(site, crawl_log, str(e)[:1000], db)
        finally:
            db.session.commit()


def crawl_site(site_id):
    from app.models import Site
    from app import create_app
    app = create_app()
    with app.app_context():
        site = Site.query.get(site_id)
        if not site:
            return
        if site.site_type == 'youtube' or is_youtube_url(site.url):
            site.site_type = 'youtube'
            from app.models import db
            db.session.commit()
            crawl_youtube(site_id)
        elif site.crawl_method == 'singlefile':
            crawl_singlefile(site_id)
        else:
            crawl_website(site_id)


def start_crawl(site_id):
    thread = Thread(target=crawl_site, args=(site_id,))
    thread.daemon = True
    thread.start()
    return thread


def stop_crawl(site_id):
    """Stop an active crawl by killing its process"""
    from app.models import db, Site, CrawlLog
    from app import create_app

    with crawls_lock:
        if site_id not in active_crawls:
            return False, "Nessun crawl attivo per questo sito"

        crawl_info = active_crawls[site_id]
        process = crawl_info.get('process')
        crawl_log_id = crawl_info.get('crawl_log_id')

        if process:
            try:
                process.terminate()
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            except Exception as e:
                logger.error(f"Error stopping crawl: {e}")

        del active_crawls[site_id]

    # Update database
    app = create_app()
    with app.app_context():
        site = Site.query.get(site_id)
        if site:
            site.status = 'error'
            site.error_message = 'Crawl interrotto manualmente'

        if crawl_log_id:
            crawl_log = CrawlLog.query.get(crawl_log_id)
            if crawl_log:
                crawl_log.status = 'cancelled'
                crawl_log.finished_at = datetime.utcnow()
                crawl_log.error_message = 'Interrotto manualmente'

        db.session.commit()

    logger.info(f"Crawl stopped for site {site_id}")
    return True, "Crawl interrotto"


def get_active_crawls():
    """Get list of all active crawls with their status"""
    from app.models import Site
    from app import create_app

    result = []
    app = create_app()

    with app.app_context():
        with crawls_lock:
            for site_id, info in active_crawls.items():
                site = Site.query.get(site_id)
                if site:
                    elapsed = (datetime.utcnow() - info['started']).total_seconds()
                    result.append({
                        'site_id': site_id,
                        'url': site.url,
                        'name': site.name,
                        'started': info['started'].isoformat(),
                        'elapsed_seconds': int(elapsed),
                        'elapsed_human': format_duration(int(elapsed)),
                        'log_lines_count': len(info.get('log_lines', []))
                    })

    return result


def get_crawl_live_log(site_id, last_n=50):
    """Get the last N lines of the live log for an active crawl"""
    with crawls_lock:
        if site_id not in active_crawls:
            return None
        lines = active_crawls[site_id].get('log_lines', [])
        return lines[-last_n:] if lines else []


def format_duration(seconds):
    """Format seconds as human readable duration"""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}h {minutes}m"


def get_crawl_progress(site_id):
    """Get detailed progress info for an active crawl"""
    with crawls_lock:
        if site_id not in active_crawls:
            return None

        info = active_crawls[site_id]
        elapsed = (datetime.utcnow() - info['started']).total_seconds()
        lines = info.get('log_lines', [])

        # Parse last lines for file info
        current_file = None
        files_downloaded = 0
        for line in reversed(lines[-100:]):
            if ' -> "' in line or ' => "' in line or 'Saving to:' in line:
                files_downloaded += 1
            if not current_file and ('Saving to:' in line or ' -> "' in line):
                # Extract filename
                if ' -> "' in line:
                    parts = line.split(' -> "')
                    if len(parts) > 1:
                        current_file = parts[1].rstrip('"')
                elif 'Saving to:' in line:
                    parts = line.split('Saving to:')
                    if len(parts) > 1:
                        current_file = parts[1].strip().strip("'\"")

        return {
            'site_id': site_id,
            'elapsed_seconds': int(elapsed),
            'elapsed_human': format_duration(int(elapsed)),
            'current_file': current_file,
            'files_count': files_downloaded,
            'last_lines': lines[-20:] if lines else []
        }


def delete_mirror(url, site_type='website', channel_id=None):
    mirror_path = get_mirror_path(url, site_type, channel_id)
    if os.path.exists(mirror_path):
        shutil.rmtree(mirror_path)
        logger.info(f"Deleted mirror at {mirror_path}")


def crawl_singlefile(site_id):
    """Crawl a JavaScript-heavy site using SingleFile CLI.
    SingleFile captures the fully-rendered page as a single HTML file with embedded resources.
    """
    from app.models import db, Site, CrawlLog
    from app import create_app
    app = create_app()

    with app.app_context():
        site = Site.query.get(site_id)
        if not site:
            return

        site.status = 'crawling'
        site.error_message = None
        db.session.commit()

        crawl_log = CrawlLog(site_id=site.id, started_at=datetime.utcnow(), status='running')
        db.session.add(crawl_log)
        db.session.commit()
        crawl_log_id = crawl_log.id

        mirror_path = get_mirror_path(site.url)
        os.makedirs(mirror_path, exist_ok=True)
        output_path = os.path.join(mirror_path, 'index.html')

        try:
            # Check if single-file CLI is available
            check_result = subprocess.run(['single-file', '--version'], capture_output=True, text=True)
            if check_result.returncode != 0:
                raise Exception("SingleFile CLI not installed. Install with: npm install -g single-file-cli")

            # Build SingleFile command
            cmd = [
                'single-file',
                '--browser-executable-path', '/usr/bin/chromium',
                '--browser-headless',
                '--browser-args', '["--no-sandbox", "--disable-dev-shm-usage"]',
                '--filename-conflict-action', 'overwrite',
                '--output-directory', mirror_path,
                site.url
            ]

            logger.info(f"Starting SingleFile crawl for {site.url}")

            # Run SingleFile with timeout
            timeout = 300  # 5 minutes per page
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )

            # Check output
            log_output = result.stdout + '\n' + result.stderr
            crawl_log = CrawlLog.query.get(crawl_log_id)
            crawl_log.wget_log = log_output[-5000:]  # Keep last 5000 chars

            if result.returncode == 0:
                # Rename output file to index.html if needed
                html_files = [f for f in os.listdir(mirror_path) if f.endswith('.html')]
                if html_files and html_files[0] != 'index.html':
                    old_path = os.path.join(mirror_path, html_files[0])
                    new_path = os.path.join(mirror_path, 'index.html')
                    os.rename(old_path, new_path)

                size_bytes, page_count = get_mirror_stats(mirror_path)

                if page_count == 0:
                    raise Exception("No content captured by SingleFile")

                mark_crawl_success(site, crawl_log, size_bytes, page_count)
                logger.info(f"SingleFile crawl done: {site.url} - {page_count} pages, {size_bytes} bytes")
            else:
                raise Exception(f"SingleFile failed: {result.stderr[:500]}")

        except subprocess.TimeoutExpired:
            handle_crawl_error(site, CrawlLog.query.get(crawl_log_id), 'SingleFile timeout', db)
        except FileNotFoundError:
            handle_crawl_error(site, CrawlLog.query.get(crawl_log_id), 'SingleFile CLI not found - install with: npm install -g single-file-cli', db)
        except Exception as e:
            crawl_log = CrawlLog.query.get(crawl_log_id)
            handle_crawl_error(site, crawl_log, str(e)[:1000], db)
        finally:
            db.session.commit()
