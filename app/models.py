from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

# Use scrypt for stronger password hashing (more resistant to GPU attacks)
PASSWORD_HASH_METHOD = 'scrypt:32768:8:1'  # N=32768, r=8, p=1

db = SQLAlchemy()


class User(db.Model):
    """User model for authentication"""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), nullable=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), default='user')  # 'admin', 'user', 'viewer'
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime, nullable=True)

    # Relationships
    mirror_requests = db.relationship('MirrorRequest', backref='requester', lazy=True, foreign_keys='MirrorRequest.user_id')

    def set_password(self, password):
        """Set password with validation. Minimum 8 characters required."""
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters long")
        self.password_hash = generate_password_hash(password, method=PASSWORD_HASH_METHOD)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def is_admin(self):
        return self.role == 'admin'

    def can_edit(self):
        return self.role in ('admin', 'user')

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'role': self.role,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None
        }


class MirrorRequest(db.Model):
    """Request for mirroring a site, submitted by users or anonymously"""
    __tablename__ = 'mirror_requests'

    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String(500), nullable=False)
    name = db.Column(db.String(200))
    description = db.Column(db.Text)
    category_suggestion = db.Column(db.String(100))

    # Requester info
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    requester_name = db.Column(db.String(100))  # For anonymous requests
    requester_email = db.Column(db.String(120))  # Optional contact

    # Status: pending, approved, rejected
    status = db.Column(db.String(20), default='pending', index=True)
    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)

    # If approved, link to created site
    site_id = db.Column(db.Integer, db.ForeignKey('sites.id'))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    ip_address = db.Column(db.String(45))  # For rate limiting anonymous requests

    # Review tracking
    reviewed_at = db.Column(db.DateTime)
    admin_notes = db.Column(db.Text)

    # Relationships
    site = db.relationship('Site', backref='mirror_request', foreign_keys=[site_id])
    reviewer = db.relationship('User', foreign_keys=[reviewed_by])

    def to_dict(self):
        return {
            'id': self.id,
            'url': self.url,
            'name': self.name,
            'description': self.description,
            'category_suggestion': self.category_suggestion,
            'requester_name': self.requester_name if not self.user_id else self.requester.username,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class Category(db.Model):
    __tablename__ = 'categories'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True, index=True)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Use selectin for efficient loading when accessing sites
    sites = db.relationship('Site', backref='category', lazy='selectin')

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
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), index=True)

    # Site type: 'website' or 'youtube'
    site_type = db.Column(db.String(20), default='website', index=True)

    # YouTube specific fields
    channel_id = db.Column(db.String(100))

    # Crawl settings
    depth = db.Column(db.Integer, default=0)  # 0 = infinite, higher = limited depth
    include_external = db.Column(db.Boolean, default=False)
    crawl_method = db.Column(db.String(20), default='wget')  # 'wget' or 'singlefile'

    # Status: pending, crawling, ready, error, retry_pending, dead
    status = db.Column(db.String(50), default='pending', index=True)
    last_crawl = db.Column(db.DateTime)
    next_crawl = db.Column(db.DateTime, index=True)
    crawl_interval_days = db.Column(db.Integer, default=30)

    # Stats
    size_bytes = db.Column(db.BigInteger, default=0)
    page_count = db.Column(db.Integer, default=0)  # For websites: pages, for YouTube: videos
    error_message = db.Column(db.Text)

    # Retry tracking
    retry_count = db.Column(db.Integer, default=0)

    # Screenshot
    screenshot_path = db.Column(db.String(500))  # Relative path to screenshot

    # Wayback Machine integration
    wayback_job_id = db.Column(db.String(100))  # Job ID from Internet Archive
    wayback_url = db.Column(db.String(500))  # Archived URL on Wayback Machine
    wayback_saved_at = db.Column(db.DateTime)  # Last successful save timestamp
    wayback_status = db.Column(db.String(20))  # pending, success, failed

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship to videos (for YouTube channels)
    videos = db.relationship('Video', backref='channel', lazy='selectin', cascade='all, delete-orphan')

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
            'screenshot_path': self.screenshot_path,
            'mirror_path': self._get_mirror_path(),
            'wayback_url': self.wayback_url,
            'wayback_status': self.wayback_status,
            'wayback_saved_at': self.wayback_saved_at.isoformat() if self.wayback_saved_at else None
        }

    def _get_mirror_path(self):
        """Return the relative path to the mirror directory"""
        from urllib.parse import urlparse
        if self.site_type == 'youtube' and self.channel_id:
            return f"youtube/{self.channel_id}"
        parsed = urlparse(self.url)
        return parsed.netloc

    def reset_crawl_state(self):
        """Reset site to pending state, clearing stats"""
        self.status = 'pending'
        self.size_bytes = 0
        self.page_count = 0
        self.screenshot_path = None
        self.error_message = None
        self.retry_count = 0

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
    site_id = db.Column(db.Integer, db.ForeignKey('sites.id'), nullable=False, index=True)

    video_id = db.Column(db.String(20), nullable=False)  # YouTube video ID
    title = db.Column(db.String(500))
    description = db.Column(db.Text)
    duration = db.Column(db.Integer)  # Duration in seconds
    upload_date = db.Column(db.Date)

    # File info
    filename = db.Column(db.String(500))
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
    site_id = db.Column(db.Integer, db.ForeignKey('sites.id'), nullable=False, index=True)
    started_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    finished_at = db.Column(db.DateTime)
    status = db.Column(db.String(50))  # success, error, cancelled
    pages_crawled = db.Column(db.Integer, default=0)
    size_bytes = db.Column(db.BigInteger, default=0)
    error_message = db.Column(db.Text)
    wget_log = db.Column(db.Text)

    site = db.relationship('Site', backref='crawl_logs')


class CulturalMetadata(db.Model):
    """Dublin Core metadata + Celeste extensions for cultural archiving"""
    __tablename__ = 'cultural_metadata'

    id = db.Column(db.Integer, primary_key=True)
    site_id = db.Column(db.Integer, db.ForeignKey('sites.id'), unique=True, nullable=False, index=True)

    # Dublin Core - relevant fields for web archiving
    dc_title = db.Column(db.String(500))  # Original title
    dc_creator = db.Column(db.String(500))  # Author/organization
    dc_date = db.Column(db.String(100))  # Original date (flexible: "1985", "anni 80", "2000-2010")
    dc_description = db.Column(db.Text)  # Extended description
    dc_subject = db.Column(db.Text)  # Keywords, topics (comma-separated)
    dc_type = db.Column(db.String(100))  # Type: website, blog, forum, zine, video, bbs
    dc_language = db.Column(db.String(10), default='it')  # Language code
    dc_rights = db.Column(db.String(200))  # License status
    dc_source = db.Column(db.String(500))  # Original source (if mirror of another archive)

    # Celeste extensions - Italian counterculture specific
    historical_period = db.Column(db.String(100))  # "pre-internet", "anni 80", "anni 90", "2000-2010"
    cultural_movement = db.Column(db.String(200))  # "cyberpunk", "autonomia", "punk", "squatter"
    original_format = db.Column(db.String(100))  # VHS, BBS, zine cartacea, CD-ROM, floppy
    provenance = db.Column(db.String(500))  # "Archivio Primo Moroni", "collezione privata", etc.
    risk_level = db.Column(db.String(20))  # high, medium, low
    risk_notes = db.Column(db.Text)  # Why is this at risk of disappearing

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship
    site = db.relationship('Site', backref=db.backref('cultural_metadata', uselist=False))

    def to_dict(self):
        return {
            'id': self.id,
            'site_id': self.site_id,
            # Dublin Core
            'dc_title': self.dc_title,
            'dc_creator': self.dc_creator,
            'dc_date': self.dc_date,
            'dc_description': self.dc_description,
            'dc_subject': self.dc_subject,
            'dc_type': self.dc_type,
            'dc_language': self.dc_language,
            'dc_rights': self.dc_rights,
            'dc_source': self.dc_source,
            # Celeste extensions
            'historical_period': self.historical_period,
            'cultural_movement': self.cultural_movement,
            'original_format': self.original_format,
            'provenance': self.provenance,
            'risk_level': self.risk_level,
            'risk_notes': self.risk_notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
