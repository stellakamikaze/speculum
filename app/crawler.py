import subprocess
import os
import shutil
import json
import re
from datetime import datetime, timedelta
from urllib.parse import urlparse
from threading import Thread, Lock
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


def get_mirror_size(path):
    total = 0
    if os.path.exists(path):
        for dirpath, dirnames, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if os.path.exists(fp):
                    total += os.path.getsize(fp)
    return total


def count_html_files(path):
    count = 0
    if os.path.exists(path):
        for dirpath, dirnames, filenames in os.walk(path):
            for f in filenames:
                if f.endswith(('.html', '.htm')):
                    count += 1
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


def build_wget_command(url, output_path, depth=0, include_external=False):
    cmd = [
        'wget', '--mirror', '--convert-links', '--adjust-extension',
        '--page-requisites', '--no-parent', '--wait=0.5', '--random-wait',
        '--tries=3', '--timeout=30', '--no-check-certificate',
        '--execute=robots=off',
        '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        '-P', output_path,
    ]
    if depth > 0:
        cmd.extend(['-l', str(depth)])
    if include_external:
        cmd.append('--span-hosts')
        cmd.append('--domains=' + urlparse(url).netloc)
    cmd.extend(['--reject', '*.exe,*.zip,*.tar.gz,*.rar,*.7z,*.iso,*.dmg'])
    cmd.append(url)
    return cmd


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
        process = None

        try:
            cmd = build_wget_command(site.url, MIRRORS_BASE_PATH, site.depth, site.include_external)
            logger.info(f"Starting crawl for {site.url}")

            # Start process with real-time output capture
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

            # Register active crawl
            with crawls_lock:
                active_crawls[site_id] = {
                    'process': process,
                    'started': datetime.utcnow(),
                    'log_lines': [],
                    'crawl_log_id': crawl_log_id
                }

            # Read output in real-time
            log_buffer = []
            try:
                while True:
                    line = process.stdout.readline()
                    if not line and process.poll() is not None:
                        break
                    if line:
                        log_buffer.append(line.strip())
                        # Keep last 500 lines in memory for real-time viewing
                        with crawls_lock:
                            if site_id in active_crawls:
                                active_crawls[site_id]['log_lines'].append(line.strip())
                                if len(active_crawls[site_id]['log_lines']) > 500:
                                    active_crawls[site_id]['log_lines'] = active_crawls[site_id]['log_lines'][-500:]
            except Exception as e:
                logger.warning(f"Error reading wget output: {e}")

            # Wait for process with timeout
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                raise

            returncode = process.returncode

            # Save log to database
            crawl_log = CrawlLog.query.get(crawl_log_id)
            crawl_log.wget_log = '\n'.join(log_buffer[-1000:])  # Keep last 1000 lines

            if returncode in [0, 8]:
                size_bytes = get_mirror_size(mirror_path)
                page_count = count_html_files(mirror_path)

                if page_count == 0 and size_bytes < 1000:
                    raise Exception("No content downloaded")

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
                logger.info(f"Crawl done: {site.url} - {page_count} pages")
            else:
                raise Exception(f"wget failed with code {returncode}")

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
                                except:
                                    pass
            
            db.session.commit()
            site.status = 'ready'
            site.last_crawl = datetime.utcnow()
            site.next_crawl = datetime.utcnow() + timedelta(days=site.crawl_interval_days)
            site.size_bytes = get_mirror_size(mirror_path)
            site.page_count = Video.query.filter_by(site_id=site.id).count()
            site.retry_count = 0
            crawl_log.finished_at = datetime.utcnow()
            crawl_log.status = 'success'
            crawl_log.pages_crawled = video_count
            
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
