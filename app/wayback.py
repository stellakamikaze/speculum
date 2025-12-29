"""
Internet Archive Wayback Machine integration.
Automatically saves URLs to archive.org for redundancy.
"""
import os
import logging
import requests
from datetime import datetime

logger = logging.getLogger(__name__)

# Wayback Machine Save Page Now API
SPN_URL = 'https://web.archive.org/save'
SPN_STATUS_URL = 'https://web.archive.org/save/status'
AVAILABILITY_URL = 'https://archive.org/wayback/available'

# Request timeout
TIMEOUT = 30


class WaybackSaver:
    """Save URLs to Internet Archive Wayback Machine."""

    def __init__(self):
        # Optional S3-style credentials for higher rate limits
        self.access_key = os.environ.get('IA_ACCESS_KEY')
        self.secret_key = os.environ.get('IA_SECRET_KEY')

    def _get_headers(self):
        """Get request headers with optional authentication."""
        headers = {
            'User-Agent': 'Speculum/1.0 (Web Archiving Tool)'
        }
        if self.access_key and self.secret_key:
            headers['Authorization'] = f'LOW {self.access_key}:{self.secret_key}'
        return headers

    def save_url(self, url, capture_outlinks=False, capture_screenshot=True):
        """
        Submit a URL to Wayback Machine for archiving.

        Args:
            url: URL to save
            capture_outlinks: If True, also save linked pages
            capture_screenshot: If True, capture a screenshot

        Returns:
            Dict with job_id and status, or None if failed
        """
        try:
            headers = self._get_headers()

            data = {
                'url': url,
                'capture_all': '1',  # Capture even 4xx/5xx responses
                'capture_outlinks': '1' if capture_outlinks else '0',
                'capture_screenshot': '1' if capture_screenshot else '0',
                'skip_first_archive': '1',  # Speed up the process
                'delay_wb_availability': '1',  # Non-urgent availability
            }

            response = requests.post(
                SPN_URL,
                headers=headers,
                data=data,
                timeout=TIMEOUT
            )

            if response.status_code == 200:
                result = response.json()
                job_id = result.get('job_id')
                logger.info(f"Wayback save initiated for {url}: job_id={job_id}")
                return {
                    'job_id': job_id,
                    'status': 'pending',
                    'url': url
                }
            elif response.status_code == 429:
                logger.warning(f"Wayback rate limited for {url}")
                return {
                    'job_id': None,
                    'status': 'rate_limited',
                    'url': url
                }
            else:
                logger.warning(f"Wayback save failed for {url}: {response.status_code} {response.text}")
                return None

        except requests.Timeout:
            logger.warning(f"Wayback save timeout for {url}")
            return None
        except Exception as e:
            logger.error(f"Wayback save error for {url}: {e}")
            return None

    def check_status(self, job_id):
        """
        Check the status of a save job.

        Args:
            job_id: Job ID from save_url()

        Returns:
            Dict with status info, or None if failed
        """
        if not job_id:
            return None

        try:
            response = requests.get(
                f'{SPN_STATUS_URL}/{job_id}',
                headers=self._get_headers(),
                timeout=TIMEOUT
            )

            if response.status_code == 200:
                data = response.json()
                return {
                    'job_id': job_id,
                    'status': data.get('status'),  # 'pending', 'success', 'error'
                    'timestamp': data.get('timestamp'),
                    'original_url': data.get('original_url'),
                    'screenshot': data.get('screenshot'),
                    'duration': data.get('duration_sec'),
                    'message': data.get('message')
                }
            else:
                logger.warning(f"Wayback status check failed for job {job_id}: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"Wayback status check error for job {job_id}: {e}")
            return None

    def get_archive_url(self, url):
        """
        Get the most recent archived version of a URL.

        Args:
            url: Original URL to look up

        Returns:
            Archived URL string, or None if not found
        """
        try:
            response = requests.get(
                AVAILABILITY_URL,
                params={'url': url},
                timeout=TIMEOUT
            )

            if response.status_code == 200:
                data = response.json()
                snapshots = data.get('archived_snapshots', {})
                closest = snapshots.get('closest', {})

                if closest.get('available'):
                    return closest.get('url')

            return None

        except Exception as e:
            logger.error(f"Wayback availability check error for {url}: {e}")
            return None

    def get_archive_info(self, url):
        """
        Get detailed info about archived versions of a URL.

        Args:
            url: Original URL to look up

        Returns:
            Dict with archive info, or None if not found
        """
        try:
            response = requests.get(
                AVAILABILITY_URL,
                params={'url': url},
                timeout=TIMEOUT
            )

            if response.status_code == 200:
                data = response.json()
                snapshots = data.get('archived_snapshots', {})
                closest = snapshots.get('closest', {})

                if closest.get('available'):
                    return {
                        'available': True,
                        'url': closest.get('url'),
                        'timestamp': closest.get('timestamp'),
                        'status': closest.get('status')
                    }

            return {'available': False}

        except Exception as e:
            logger.error(f"Wayback info check error for {url}: {e}")
            return None


def save_site_to_wayback(site_id):
    """
    Save a site's URL to Wayback Machine and update the database.

    Args:
        site_id: Site ID to save

    Returns:
        True if save was initiated, False otherwise
    """
    try:
        from app.models import db, Site

        site = Site.query.get(site_id)
        if not site:
            logger.warning(f"Site {site_id} not found for Wayback save")
            return False

        saver = WaybackSaver()
        result = saver.save_url(site.url)

        if result:
            site.wayback_job_id = result.get('job_id')
            site.wayback_status = 'pending'
            db.session.commit()
            logger.info(f"Wayback save initiated for site {site_id}")
            return True
        else:
            site.wayback_status = 'failed'
            db.session.commit()
            return False

    except Exception as e:
        logger.error(f"Failed to save site {site_id} to Wayback: {e}")
        return False


def check_pending_wayback_jobs():
    """
    Check status of all pending Wayback jobs and update database.
    Should be called periodically by scheduler.

    Returns:
        Tuple of (checked, succeeded, failed)
    """
    try:
        from app.models import db, Site

        saver = WaybackSaver()
        checked = 0
        succeeded = 0
        failed = 0

        # Get all sites with pending Wayback jobs
        pending = Site.query.filter_by(wayback_status='pending').all()

        for site in pending:
            if not site.wayback_job_id:
                continue

            checked += 1
            status = saver.check_status(site.wayback_job_id)

            if status:
                if status.get('status') == 'success':
                    # Get the archived URL
                    archive_url = saver.get_archive_url(site.url)
                    site.wayback_url = archive_url
                    site.wayback_status = 'success'
                    site.wayback_saved_at = datetime.utcnow()
                    succeeded += 1
                    logger.info(f"Wayback save succeeded for site {site.id}: {archive_url}")

                elif status.get('status') == 'error':
                    site.wayback_status = 'failed'
                    failed += 1
                    logger.warning(f"Wayback save failed for site {site.id}: {status.get('message')}")

                # If still pending, leave as is

        db.session.commit()
        logger.info(f"Wayback job check: {checked} checked, {succeeded} succeeded, {failed} failed")

        return checked, succeeded, failed

    except Exception as e:
        logger.error(f"Failed to check Wayback jobs: {e}")
        return 0, 0, 0


def retry_failed_wayback_saves():
    """
    Retry Wayback saves that previously failed.
    Should be called periodically by scheduler.

    Returns:
        Number of retries initiated
    """
    try:
        from app.models import db, Site

        # Get failed saves that haven't been retried recently
        failed = Site.query.filter_by(wayback_status='failed').limit(10).all()

        retried = 0
        for site in failed:
            if save_site_to_wayback(site.id):
                retried += 1

        logger.info(f"Retried {retried} failed Wayback saves")
        return retried

    except Exception as e:
        logger.error(f"Failed to retry Wayback saves: {e}")
        return 0
