import subprocess
import os
import shutil
import json
import re
from datetime import datetime, timedelta
from urllib.parse import urlparse
from threading import Thread
import logging

logger = logging.getLogger(__name__)

MIRRORS_BASE_PATH = os.environ.get('MIRRORS_PATH', '/mirrors')


# ==================== UTILITY FUNCTIONS ====================

def get_mirror_path(url, site_type='website', channel_id=None):
    """Get the filesystem path for a site's mirror"""
    if site_type == 'youtube' and channel_id:
        return os.path.join(MIRRORS_BASE_PATH, 'youtube', channel_id)
    parsed = urlparse(url)
    return os.path.join(MIRRORS_BASE_PATH, parsed.netloc)


def get_mirror_size(path):
    """Calculate total size of a directory"""
    total = 0
    if os.path.exists(path):
        for dirpath, dirnames, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if os.path.exists(fp):
                    total += os.path.getsize(fp)
    return total


def count_html_files(path):
    """Count HTML files in a directory"""
    count = 0
    if os.path.exists(path):
        for dirpath, dirnames, filenames in os.walk(path):
            for f in filenames:
                if f.endswith(('.html', '.htm')):
                    count += 1
    return count


def count_video_files(path):
    """Count video files in a directory"""
    count = 0
    video_extensions = ('.mp4', '.webm', '.mkv', '.avi', '.mov')
    if os.path.exists(path):
        for dirpath, dirnames, filenames in os.walk(path):
            for f in filenames:
                if f.endswith(video_extensions):
                    count += 1
    return count


# ==================== YOUTUBE DETECTION ====================

def is_youtube_url(url):
    """Check if URL is a YouTube channel, playlist, or video"""
    youtube_patterns = [
        r'(youtube\.com|youtu\.be)',
    ]
    return any(re.search(p, url) for p in youtube_patterns)


def get_youtube_channel_id(url):
    """Extract channel ID from YouTube URL using yt-dlp"""
    try:
        result = subprocess.run(
            ['yt-dlp', '--print', 'channel_id', '--playlist-items', '1', url],
            capture_output=True,
            text=True,
            timeout=60
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception as e:
        logger.error(f"Error extracting channel ID: {e}")
    return None


def get_youtube_channel_info(url):
    """Get channel metadata using yt-dlp"""
    try:
        result = subprocess.run(
            ['yt-dlp', '--dump-json', '--playlist-items', '1', url],
            capture_output=True,
            text=True,
            timeout=60
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout.strip())
            return {
                'channel_id': data.get('channel_id'),
                'channel': data.get('channel') or data.get('uploader'),
                'channel_url': data.get('channel_url'),
                'thumbnail': data.get('thumbnail')
            }
    except Exception as e:
        logger.error(f"Error getting channel info: {e}")
    return None


# ==================== WEBSITE CRAWLING ====================

def build_wget_command(url, output_path, depth=0, include_external=False):
    """Build the wget command for mirroring a site"""
    cmd = [
        'wget',
        '--mirror',
        '--convert-links',
        '--adjust-extension',
        '--page-requisites',
        '--no-parent',
        '--wait=0.5',
        '--random-wait',
        '--tries=3',
        '--timeout=30',
        '--no-check-certificate',
        '--execute=robots=off',
        '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        '-P', output_path,
    ]
    
    if depth > 0:
        cmd.extend(['-l', str(depth)])
    
    if include_external:
        cmd.append('--span-hosts')
        cmd.append('--domains=' + urlparse(url).netloc)
    
    cmd.extend([
        '--reject', '*.exe,*.zip,*.tar.gz,*.rar,*.7z,*.iso,*.dmg',
        '--reject-regex', '(logout|signout|login|signin|auth|session)',
    ])
    
    cmd.append(url)
    
    return cmd


def crawl_website(site_id):
    """Crawl a website using wget"""
    from app.models import db, Site, CrawlLog
    from app import create_app
    
    app = create_app()
    
    with app.app_context():
        site = Site.query.get(site_id)
        if not site:
            logger.error(f"Site {site_id} not found")
            return
        
        site.status = 'crawling'
        site.error_message = None
        db.session.commit()
        
        crawl_log = CrawlLog(
            site_id=site.id,
            started_at=datetime.utcnow(),
            status='running'
        )
        db.session.add(crawl_log)
        db.session.commit()
        
        mirror_path = get_mirror_path(site.url)
        
        try:
            cmd = build_wget_command(
                site.url,
                MIRRORS_BASE_PATH,
                depth=site.depth,
                include_external=site.include_external
            )
            
            logger.info(f"Starting crawl for {site.url}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3600 * 6
            )
            
            if result.returncode in [0, 8]:
                size_bytes = get_mirror_size(mirror_path)
                page_count = count_html_files(mirror_path)
                
                site.status = 'ready'
                site.last_crawl = datetime.utcnow()
                site.next_crawl = datetime.utcnow() + timedelta(days=site.crawl_interval_days)
                site.size_bytes = size_bytes
                site.page_count = page_count
                site.error_message = None
                
                crawl_log.finished_at = datetime.utcnow()
                crawl_log.status = 'success'
                crawl_log.pages_crawled = page_count
                crawl_log.size_bytes = size_bytes
                crawl_log.wget_log = result.stderr[-10000:] if result.stderr else None
                
                logger.info(f"Crawl completed for {site.url}: {page_count} pages")
            else:
                raise Exception(f"wget failed with return code {result.returncode}: {result.stderr[-2000:]}")
                
        except subprocess.TimeoutExpired:
            site.status = 'error'
            site.error_message = 'Crawl timed out after 6 hours'
            crawl_log.finished_at = datetime.utcnow()
            crawl_log.status = 'error'
            crawl_log.error_message = 'Timeout'
            
        except Exception as e:
            site.status = 'error'
            site.error_message = str(e)[:1000]
            crawl_log.finished_at = datetime.utcnow()
            crawl_log.status = 'error'
            crawl_log.error_message = str(e)[:1000]
            logger.error(f"Crawl error for {site.url}: {e}")
        
        finally:
            db.session.commit()


# ==================== YOUTUBE DOWNLOADING ====================

def build_ytdlp_command(url, output_path):
    """Build yt-dlp command for downloading videos with metadata and thumbnails"""
    cmd = [
        'yt-dlp',
        '--format', 'bestvideo[height<=1080]+bestaudio/best[height<=1080]/best',
        '--merge-output-format', 'mp4',
        '--write-info-json',           # Save metadata JSON
        '--write-thumbnail',           # Save thumbnail
        '--convert-thumbnails', 'jpg', # Convert thumbnail to jpg
        '--embed-thumbnail',           # Embed thumbnail in video
        '--add-metadata',              # Add metadata to file
        '--output', os.path.join(output_path, '%(id)s/%(title)s [%(id)s].%(ext)s'),
        '--restrict-filenames',        # Safe filenames
        '--no-overwrites',             # Don't re-download existing videos
        '--ignore-errors',             # Continue on errors
        '--sleep-interval', '2',       # Be polite
        '--max-sleep-interval', '5',
        url
    ]
    return cmd


def crawl_youtube(site_id):
    """Download YouTube channel/playlist videos"""
    from app.models import db, Site, Video, CrawlLog
    from app import create_app
    
    app = create_app()
    
    with app.app_context():
        site = Site.query.get(site_id)
        if not site:
            logger.error(f"Site {site_id} not found")
            return
        
        site.status = 'crawling'
        site.error_message = None
        db.session.commit()
        
        crawl_log = CrawlLog(
            site_id=site.id,
            started_at=datetime.utcnow(),
            status='running'
        )
        db.session.add(crawl_log)
        db.session.commit()
        
        # Get or create channel directory
        if not site.channel_id:
            channel_info = get_youtube_channel_info(site.url)
            if channel_info and channel_info.get('channel_id'):
                site.channel_id = channel_info['channel_id']
                if not site.name or site.name == urlparse(site.url).netloc:
                    site.name = channel_info.get('channel', site.name)
                site.thumbnail_url = channel_info.get('thumbnail')
                db.session.commit()
        
        mirror_path = get_mirror_path(site.url, 'youtube', site.channel_id)
        os.makedirs(mirror_path, exist_ok=True)
        
        try:
            cmd = build_ytdlp_command(site.url, mirror_path)
            
            logger.info(f"Starting YouTube download for {site.url}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3600 * 12  # 12 hour timeout for large channels
            )
            
            # Parse downloaded videos from output directory
            video_count = 0
            total_size = 0
            
            if os.path.exists(mirror_path):
                for video_dir in os.listdir(mirror_path):
                    video_path = os.path.join(mirror_path, video_dir)
                    if os.path.isdir(video_path):
                        # Look for info.json
                        for f in os.listdir(video_path):
                            if f.endswith('.info.json'):
                                try:
                                    with open(os.path.join(video_path, f), 'r') as jf:
                                        info = json.load(jf)
                                    
                                    video_id = info.get('id', video_dir)
                                    
                                    # Check if video already exists in DB
                                    existing = Video.query.filter_by(
                                        site_id=site.id,
                                        video_id=video_id
                                    ).first()
                                    
                                    if not existing:
                                        # Find video file
                                        video_file = None
                                        thumb_file = None
                                        video_size = 0
                                        
                                        for vf in os.listdir(video_path):
                                            if vf.endswith(('.mp4', '.webm', '.mkv')):
                                                video_file = vf
                                                video_size = os.path.getsize(os.path.join(video_path, vf))
                                            elif vf.endswith(('.jpg', '.png', '.webp')):
                                                thumb_file = vf
                                        
                                        # Parse upload date
                                        upload_date = None
                                        if info.get('upload_date'):
                                            try:
                                                upload_date = datetime.strptime(info['upload_date'], '%Y%m%d').date()
                                            except:
                                                pass
                                        
                                        video = Video(
                                            site_id=site.id,
                                            video_id=video_id,
                                            title=info.get('title', '')[:500],
                                            description=info.get('description', ''),
                                            duration=info.get('duration'),
                                            upload_date=upload_date,
                                            filename=video_file,
                                            thumbnail_filename=thumb_file,
                                            size_bytes=video_size,
                                            status='ready'
                                        )
                                        db.session.add(video)
                                        video_count += 1
                                        total_size += video_size
                                        
                                except Exception as e:
                                    logger.warning(f"Error parsing video info: {e}")
            
            db.session.commit()
            
            # Update site stats
            site.status = 'ready'
            site.last_crawl = datetime.utcnow()
            site.next_crawl = datetime.utcnow() + timedelta(days=site.crawl_interval_days)
            site.size_bytes = get_mirror_size(mirror_path)
            site.page_count = Video.query.filter_by(site_id=site.id).count()
            site.error_message = None
            
            crawl_log.finished_at = datetime.utcnow()
            crawl_log.status = 'success'
            crawl_log.pages_crawled = video_count
            crawl_log.size_bytes = total_size
            
            logger.info(f"YouTube download completed for {site.url}: {video_count} new videos")
            
        except subprocess.TimeoutExpired:
            site.status = 'error'
            site.error_message = 'Download timed out after 12 hours'
            crawl_log.finished_at = datetime.utcnow()
            crawl_log.status = 'error'
            crawl_log.error_message = 'Timeout'
            
        except Exception as e:
            site.status = 'error'
            site.error_message = str(e)[:1000]
            crawl_log.finished_at = datetime.utcnow()
            crawl_log.status = 'error'
            crawl_log.error_message = str(e)[:1000]
            logger.error(f"YouTube download error for {site.url}: {e}")
        
        finally:
            db.session.commit()


# ==================== MAIN CRAWL DISPATCHER ====================

def crawl_site(site_id):
    """
    Main crawl dispatcher - determines site type and calls appropriate crawler
    """
    from app.models import Site
    from app import create_app
    
    app = create_app()
    
    with app.app_context():
        site = Site.query.get(site_id)
        if not site:
            logger.error(f"Site {site_id} not found")
            return
        
        if site.site_type == 'youtube' or is_youtube_url(site.url):
            site.site_type = 'youtube'
            from app.models import db
            db.session.commit()
            crawl_youtube(site_id)
        else:
            crawl_website(site_id)


def start_crawl(site_id):
    """Start a crawl in a background thread"""
    thread = Thread(target=crawl_site, args=(site_id,))
    thread.daemon = True
    thread.start()
    return thread


def delete_mirror(url, site_type='website', channel_id=None):
    """Delete a site's mirror from disk"""
    mirror_path = get_mirror_path(url, site_type, channel_id)
    if os.path.exists(mirror_path):
        shutil.rmtree(mirror_path)
        logger.info(f"Deleted mirror at {mirror_path}")
