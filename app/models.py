from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Category(db.Model):
    __tablename__ = 'categories'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    sites = db.relationship('Site', backref='category', lazy=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'site_count': len(self.sites)
        }


class Site(db.Model):
    __tablename__ = 'sites'
    
    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String(500), nullable=False, unique=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'))
    
    # Site type: 'website' or 'youtube'
    site_type = db.Column(db.String(20), default='website')
    
    # YouTube specific fields
    channel_id = db.Column(db.String(100))  # YouTube channel ID
    thumbnail_url = db.Column(db.String(500))
    
    # Crawl settings
    depth = db.Column(db.Integer, default=0)  # 0 = infinite
    include_external = db.Column(db.Boolean, default=False)
    
    # Status: pending, crawling, ready, error, retry_pending, dead
    status = db.Column(db.String(50), default='pending')
    last_crawl = db.Column(db.DateTime)
    next_crawl = db.Column(db.DateTime)
    crawl_interval_days = db.Column(db.Integer, default=30)

    # Stats
    size_bytes = db.Column(db.BigInteger, default=0)
    page_count = db.Column(db.Integer, default=0)  # For websites: pages, for YouTube: videos
    error_message = db.Column(db.Text)

    # Retry tracking
    retry_count = db.Column(db.Integer, default=0)
    
    # AI-generated metadata
    ai_generated = db.Column(db.Boolean, default=False)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship to videos (for YouTube channels)
    videos = db.relationship('Video', backref='channel', lazy=True, cascade='all, delete-orphan')
    
    def to_dict(self):
        return {
            'id': self.id,
            'url': self.url,
            'name': self.name,
            'description': self.description,
            'category_id': self.category_id,
            'category_name': self.category.name if self.category else None,
            'site_type': self.site_type,
            'status': self.status,
            'last_crawl': self.last_crawl.isoformat() if self.last_crawl else None,
            'next_crawl': self.next_crawl.isoformat() if self.next_crawl else None,
            'crawl_interval_days': self.crawl_interval_days,
            'size_bytes': self.size_bytes,
            'size_human': self._human_size(self.size_bytes),
            'page_count': self.page_count,
            'error_message': self.error_message,
            'retry_count': self.retry_count,
            'mirror_path': self._get_mirror_path()
        }
    
    def _get_mirror_path(self):
        """Return the relative path to the mirror directory"""
        from urllib.parse import urlparse
        if self.site_type == 'youtube' and self.channel_id:
            return f"youtube/{self.channel_id}"
        parsed = urlparse(self.url)
        return parsed.netloc
    
    @staticmethod
    def _human_size(size_bytes):
        if not size_bytes:
            return '0 B'
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} PB"


class Video(db.Model):
    """YouTube video metadata"""
    __tablename__ = 'videos'
    
    id = db.Column(db.Integer, primary_key=True)
    site_id = db.Column(db.Integer, db.ForeignKey('sites.id'), nullable=False)
    
    video_id = db.Column(db.String(20), nullable=False)  # YouTube video ID
    title = db.Column(db.String(500))
    description = db.Column(db.Text)
    duration = db.Column(db.Integer)  # Duration in seconds
    upload_date = db.Column(db.Date)
    
    # File info
    filename = db.Column(db.String(500))
    thumbnail_filename = db.Column(db.String(500))
    size_bytes = db.Column(db.BigInteger, default=0)
    
    # Status
    status = db.Column(db.String(50), default='pending')  # pending, downloading, ready, error
    error_message = db.Column(db.Text)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'video_id': self.video_id,
            'title': self.title,
            'description': self.description,
            'duration': self.duration,
            'duration_human': self._human_duration(self.duration),
            'upload_date': self.upload_date.isoformat() if self.upload_date else None,
            'filename': self.filename,
            'thumbnail_filename': self.thumbnail_filename,
            'size_bytes': self.size_bytes,
            'size_human': Site._human_size(self.size_bytes),
            'status': self.status
        }
    
    @staticmethod
    def _human_duration(seconds):
        if not seconds:
            return '0:00'
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        if hours:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        return f"{minutes}:{secs:02d}"


class CrawlLog(db.Model):
    __tablename__ = 'crawl_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    site_id = db.Column(db.Integer, db.ForeignKey('sites.id'), nullable=False)
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    finished_at = db.Column(db.DateTime)
    status = db.Column(db.String(50))  # success, error, cancelled
    pages_crawled = db.Column(db.Integer, default=0)
    size_bytes = db.Column(db.BigInteger, default=0)
    error_message = db.Column(db.Text)
    wget_log = db.Column(db.Text)
    
    site = db.relationship('Site', backref='crawl_logs')
