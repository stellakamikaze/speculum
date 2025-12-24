from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


def check_scheduled_crawls():
    """Check for sites that need to be crawled"""
    from app.models import db, Site
    from app.crawler import start_crawl
    from app import create_app
    
    app = create_app()
    
    with app.app_context():
        now = datetime.utcnow()
        
        # Find sites due for crawl
        sites = Site.query.filter(
            Site.next_crawl <= now,
            Site.status.in_(['ready', 'error'])  # Don't re-crawl if already crawling
        ).all()
        
        for site in sites:
            logger.info(f"Starting scheduled crawl for {site.url}")
            start_crawl(site.id)


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
        
        scheduler.start()
        logger.info("Scheduler started")


def shutdown_scheduler():
    """Shutdown the scheduler"""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler stopped")
