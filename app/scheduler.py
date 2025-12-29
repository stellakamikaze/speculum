from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()

# Configuration
STUCK_CRAWL_THRESHOLD_HOURS = 6  # Mark crawl as stuck after this many hours


def check_scheduled_crawls():
    """Check for sites that need to be crawled (regular schedule)"""
    from app.models import db, Site
    from app.crawler import start_crawl
    from app import create_app

    app = create_app()

    with app.app_context():
        now = datetime.utcnow()

        # Find sites due for regular scheduled crawl
        sites = Site.query.filter(
            Site.next_crawl <= now,
            Site.status.in_(['ready', 'error'])  # Don't re-crawl if already crawling
        ).all()

        for site in sites:
            logger.info(f"Starting scheduled crawl for {site.url}")
            start_crawl(site.id)


def process_retry_queue():
    """Process sites in retry_pending status that are due for retry"""
    from app.models import db, Site
    from app.crawler import start_crawl
    from app import create_app

    app = create_app()

    with app.app_context():
        now = datetime.utcnow()

        # Find sites in retry_pending that are due for retry
        sites = Site.query.filter(
            Site.status == 'retry_pending',
            Site.next_crawl <= now
        ).all()

        for site in sites:
            logger.info(f"Processing retry for {site.url} (attempt {site.retry_count + 1})")
            start_crawl(site.id)


def reset_stuck_crawls():
    """Reset crawls that have been stuck in 'crawling' status for too long"""
    from app.models import db, Site
    from app import create_app

    app = create_app()

    with app.app_context():
        threshold = datetime.utcnow() - timedelta(hours=STUCK_CRAWL_THRESHOLD_HOURS)

        # Find sites stuck in crawling status
        stuck_sites = Site.query.filter(
            Site.status == 'crawling',
            Site.updated_at < threshold
        ).all()

        for site in stuck_sites:
            logger.warning(f"Resetting stuck crawl for {site.url} (stuck since {site.updated_at})")
            site.status = 'error'
            site.error_message = f"Crawl stuck for more than {STUCK_CRAWL_THRESHOLD_HOURS} hours, reset automatically"
            site.retry_count = (site.retry_count or 0) + 1

        if stuck_sites:
            db.session.commit()
            logger.info(f"Reset {len(stuck_sites)} stuck crawls")


def backup_mirror_requests():
    """Backup MirrorRequest records to JSON file"""
    from app import create_app

    app = create_app()

    with app.app_context():
        try:
            from app.backup import export_requests_json
            filepath = export_requests_json()
            if filepath:
                logger.info(f"MirrorRequest backup created: {filepath}")
            else:
                logger.warning("MirrorRequest backup failed")
        except Exception as e:
            logger.error(f"MirrorRequest backup error: {e}")


def check_wayback_jobs():
    """Check status of pending Wayback Machine save jobs"""
    from app import create_app

    app = create_app()

    with app.app_context():
        try:
            from app.wayback import check_pending_wayback_jobs
            checked, succeeded, failed = check_pending_wayback_jobs()
            if checked > 0:
                logger.info(f"Wayback job check: {succeeded} succeeded, {failed} failed out of {checked}")
        except Exception as e:
            logger.error(f"Wayback job check error: {e}")


def init_scheduler(app):
    """Initialize the scheduler with the Flask app"""
    if not scheduler.running:
        # Check for due crawls every hour
        scheduler.add_job(
            check_scheduled_crawls,
            CronTrigger(minute=0),  # Every hour at :00
            id='check_scheduled_crawls',
            replace_existing=True
        )

        # Process retry queue every 5 minutes
        scheduler.add_job(
            process_retry_queue,
            IntervalTrigger(minutes=5),
            id='process_retry_queue',
            replace_existing=True
        )

        # Check for stuck crawls every 30 minutes
        scheduler.add_job(
            reset_stuck_crawls,
            IntervalTrigger(minutes=30),
            id='reset_stuck_crawls',
            replace_existing=True
        )

        # Backup MirrorRequest every 6 hours
        scheduler.add_job(
            backup_mirror_requests,
            IntervalTrigger(hours=6),
            id='backup_mirror_requests',
            replace_existing=True
        )

        # Check Wayback Machine job status every 30 minutes
        scheduler.add_job(
            check_wayback_jobs,
            IntervalTrigger(minutes=30),
            id='check_wayback_jobs',
            replace_existing=True
        )

        scheduler.start()
        logger.info("Scheduler started with retry queue, stuck crawl detection, backup, and Wayback checks")


def shutdown_scheduler():
    """Shutdown the scheduler"""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler stopped")
