import os
import re
import secrets
import logging
from functools import wraps
from flask import Flask, render_template, request, jsonify, redirect, url_for, send_from_directory, abort, session, g, Response
from urllib.parse import urlparse
from datetime import datetime, timedelta
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize extensions
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address, default_limits=["200 per minute"])


def create_app():
    app = Flask(__name__,
                template_folder='../templates',
                static_folder='../static')

    # Configuration
    secret_key = os.environ.get('SECRET_KEY')
    if not secret_key:
        if os.environ.get('FLASK_ENV') == 'production':
            raise RuntimeError("SECRET_KEY environment variable is required in production!")
        # Generate a random key for development
        secret_key = secrets.token_hex(32)
        logger.warning("No SECRET_KEY set, using random key (sessions won't persist across restarts)")

    app.config['SECRET_KEY'] = secret_key
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///speculum.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

    # Telegram webhook configuration
    app.config['TELEGRAM_BOT_TOKEN'] = os.environ.get('TELEGRAM_BOT_TOKEN')
    app.config['TELEGRAM_CHAT_ID'] = os.environ.get('TELEGRAM_CHAT_ID')

    # Rate limiting (requests per minute)
    app.config['RATE_LIMIT'] = int(os.environ.get('RATE_LIMIT', 60))

    MIRRORS_PATH = os.environ.get('MIRRORS_PATH', '/mirrors')
    
    # Initialize extensions
    from app.models import db
    db.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    with app.app_context():
        db.create_all()

        # Migrate: add missing columns
        try:
            from sqlalchemy import inspect, text
            inspector = inspect(db.engine)

            # Sites table migrations
            if 'sites' in inspector.get_table_names():
                columns = [c['name'] for c in inspector.get_columns('sites')]
                if 'crawl_method' not in columns:
                    with db.engine.connect() as conn:
                        conn.execute(text("ALTER TABLE sites ADD COLUMN crawl_method VARCHAR(20) DEFAULT 'wget'"))
                        conn.commit()
                    app.logger.info("Added crawl_method column to sites table")

            # Users table migrations
            if 'users' in inspector.get_table_names():
                user_columns = [c['name'] for c in inspector.get_columns('users')]
                with db.engine.connect() as conn:
                    if 'email' not in user_columns:
                        conn.execute(text("ALTER TABLE users ADD COLUMN email VARCHAR(120)"))
                        app.logger.info("Added email column to users table")
                    if 'last_login' not in user_columns:
                        conn.execute(text("ALTER TABLE users ADD COLUMN last_login DATETIME"))
                        app.logger.info("Added last_login column to users table")
                    conn.commit()
        except Exception as e:
            app.logger.warning(f"Migration check failed: {e}")
    
    # Import models and utilities
    from app.models import Site, Category, CrawlLog, Video, User, MirrorRequest
    from app.crawler import (
        start_crawl, delete_mirror, get_mirror_path, is_youtube_url, MIRRORS_BASE_PATH,
        stop_crawl, get_active_crawls, get_crawl_live_log, get_crawl_progress
    )
    from app.helpers import (
        get_dashboard_stats, get_status_counts, get_categories_ordered,
        check_ollama_safe, get_or_create_category
    )

    # ==================== AUTHENTICATION ====================

    def get_current_user():
        """Get current logged-in user from session"""
        if 'user_id' in session:
            return User.query.get(session['user_id'])
        return None

    def login_required(f):
        """Decorator to require login for a route"""
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not get_current_user():
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'error': 'Login required'}), 401
                return redirect(url_for('login', next=request.url))
            return f(*args, **kwargs)
        return decorated_function

    def admin_required(f):
        """Decorator to require admin role"""
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user = get_current_user()
            if not user or not user.is_admin():
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'error': 'Admin access required'}), 403
                abort(403)
            return f(*args, **kwargs)
        return decorated_function

    def edit_required(f):
        """Decorator to require edit permission (admin or user role)"""
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user = get_current_user()
            if not user or not user.can_edit():
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'error': 'Edit permission required'}), 403
                abort(403)
            return f(*args, **kwargs)
        return decorated_function

    @app.before_request
    def load_user():
        """Load current user into g object for templates"""
        g.user = get_current_user()

    @app.context_processor
    def inject_user():
        """Make user available in all templates"""
        return {'current_user': g.get('user')}

    # Create default admin if no users exist
    with app.app_context():
        if User.query.count() == 0:
            admin_password = os.environ.get('ADMIN_PASSWORD', 'admin')
            admin = User(
                username='admin',
                role='admin'
            )
            admin.set_password(admin_password)
            db.session.add(admin)
            db.session.commit()
            logger.info("Created default admin user (username: admin)")

    @app.route('/login', methods=['GET', 'POST'])
    @limiter.limit("10 per minute")
    def login():
        """User login page"""
        if g.user:
            return redirect(url_for('index'))

        error = None
        if request.method == 'POST':
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')

            user = User.query.filter_by(username=username).first()
            if user and user.check_password(password) and user.is_active:
                session.permanent = True
                session['user_id'] = user.id
                user.last_login = datetime.utcnow()
                db.session.commit()

                next_url = request.args.get('next')
                # Security: validate redirect URL to prevent open redirect
                if next_url:
                    parsed = urlparse(next_url)
                    # Only allow relative URLs without scheme/netloc (prevents //evil.com)
                    if not parsed.netloc and not parsed.scheme and next_url.startswith('/') and not next_url.startswith('//'):
                        return redirect(next_url)
                return redirect(url_for('index'))
            else:
                error = 'Credenziali non valide'

        return render_template('login.html', error=error)

    @app.route('/logout')
    def logout():
        """User logout"""
        session.pop('user_id', None)
        return redirect(url_for('index'))

    @app.route('/admin/users')
    @admin_required
    def admin_users():
        """Admin: manage users"""
        users = User.query.order_by(User.username).all()
        return render_template('admin_users.html', users=users)

    @app.route('/admin/users/add', methods=['POST'])
    @admin_required
    def admin_add_user():
        """Admin: add new user"""
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        role = request.form.get('role', 'user')

        if not username or not password:
            return redirect(url_for('admin_users'))

        if User.query.filter_by(username=username).first():
            return redirect(url_for('admin_users'))

        user = User(username=username, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        return redirect(url_for('admin_users'))

    @app.route('/admin/users/<int:user_id>/delete', methods=['POST'])
    @admin_required
    def admin_delete_user(user_id):
        """Admin: delete user"""
        user = User.query.get_or_404(user_id)
        if user.id == g.user.id:
            return redirect(url_for('admin_users'))  # Can't delete yourself

        db.session.delete(user)
        db.session.commit()
        return redirect(url_for('admin_users'))

    @app.route('/admin/users/<int:user_id>/toggle', methods=['POST'])
    @admin_required
    def admin_toggle_user(user_id):
        """Admin: toggle user active status"""
        user = User.query.get_or_404(user_id)
        if user.id != g.user.id:  # Can't deactivate yourself
            user.is_active = not user.is_active
            db.session.commit()
        return redirect(url_for('admin_users'))

    # ==================== MIRROR REQUESTS ====================

    @app.route('/request-mirror', methods=['GET', 'POST'])
    @limiter.limit("5 per hour")
    def request_mirror():
        """Submit a mirror request (public, no login required)"""
        if request.method == 'POST':
            url = request.form.get('url', '').strip()
            name = request.form.get('name', '').strip()
            description = request.form.get('description', '').strip()
            category_suggestion = request.form.get('category', '').strip()
            requester_name = request.form.get('requester_name', '').strip()
            requester_email = request.form.get('requester_email', '').strip()

            # Basic validation
            if not url:
                return render_template('request_mirror.html', error='URL richiesto')

            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url

            # Check for duplicate pending requests
            existing = MirrorRequest.query.filter_by(url=url, status='pending').first()
            if existing:
                return render_template('request_mirror.html',
                    success='Questa richiesta è già in attesa di revisione')

            # Create request
            mirror_request = MirrorRequest(
                url=url,
                name=name or None,
                description=description or None,
                category_suggestion=category_suggestion or None,
                user_id=g.user.id if g.user else None,
                requester_name=requester_name or None,
                requester_email=requester_email or None,
                ip_address=request.remote_addr
            )
            db.session.add(mirror_request)
            db.session.commit()

            # Send Telegram notification
            try:
                from app.telegram import notify_new_mirror_request
                requester = requester_name or (g.user.username if g.user else None)
                notify_new_mirror_request(url, requester)
            except Exception as e:
                logger.warning(f"Failed to send Telegram notification: {e}")

            return render_template('request_mirror.html',
                success='Richiesta inviata! Verrà revisionata da un amministratore.')

        categories = get_categories_ordered(Category)
        return render_template('request_mirror.html', categories=categories)

    @app.route('/admin/requests')
    @admin_required
    def admin_mirror_requests():
        """Admin: view and manage mirror requests"""
        status_filter = request.args.get('status', 'pending')
        if status_filter == 'all':
            requests_list = MirrorRequest.query.order_by(MirrorRequest.created_at.desc()).all()
        else:
            requests_list = MirrorRequest.query.filter_by(status=status_filter).order_by(MirrorRequest.created_at.desc()).all()

        return render_template('admin_requests.html', requests=requests_list, status_filter=status_filter)

    @app.route('/admin/requests/<int:request_id>/approve', methods=['POST'])
    @admin_required
    def admin_approve_request(request_id):
        """Admin: approve a mirror request"""
        mirror_request = MirrorRequest.query.get_or_404(request_id)

        if mirror_request.status != 'pending':
            return redirect(url_for('admin_mirror_requests'))

        # Check if site already exists
        existing = Site.query.filter_by(url=mirror_request.url).first()
        if existing:
            mirror_request.status = 'rejected'
            mirror_request.reviewed_by = g.user.id
            db.session.commit()
            return redirect(url_for('admin_mirror_requests'))

        # Create site
        site_type = 'youtube' if is_youtube_url(mirror_request.url) else 'website'
        site = Site(
            url=mirror_request.url,
            name=mirror_request.name or urlparse(mirror_request.url).netloc,
            description=mirror_request.description,
            site_type=site_type,
            status='pending'
        )

        # Handle category
        if mirror_request.category_suggestion:
            cat = Category.query.filter_by(name=mirror_request.category_suggestion).first()
            if cat:
                site.category_id = cat.id

        db.session.add(site)
        db.session.flush()

        mirror_request.status = 'approved'
        mirror_request.site_id = site.id
        mirror_request.reviewed_by = g.user.id

        db.session.commit()

        # Start crawl
        start_crawl(site.id)

        return redirect(url_for('admin_mirror_requests'))

    @app.route('/admin/requests/<int:request_id>/reject', methods=['POST'])
    @admin_required
    def admin_reject_request(request_id):
        """Admin: reject a mirror request"""
        mirror_request = MirrorRequest.query.get_or_404(request_id)

        if mirror_request.status != 'pending':
            return redirect(url_for('admin_mirror_requests'))

        mirror_request.status = 'rejected'
        mirror_request.reviewed_by = g.user.id
        db.session.commit()

        return redirect(url_for('admin_mirror_requests'))

    # ==================== WEB ROUTES ====================
    
    @app.route('/')
    def index():
        """Main catalog page"""
        categories = get_categories_ordered(Category)
        uncategorized_sites = Site.query.filter_by(category_id=None).order_by(Site.name).all()
        stats = get_dashboard_stats(db, Site, Video)
        stats['categories'] = len(categories)

        return render_template('index.html',
                               categories=categories,
                               uncategorized_sites=uncategorized_sites,
                               stats=stats)
    
    @app.route('/sites')
    def sites_list():
        """List all sites"""
        filter_type = request.args.get('type', 'all')
        
        if filter_type == 'website':
            sites = Site.query.filter_by(site_type='website').order_by(Site.name).all()
        elif filter_type == 'youtube':
            sites = Site.query.filter_by(site_type='youtube').order_by(Site.name).all()
        else:
            sites = Site.query.order_by(Site.name).all()
        
        categories = get_categories_ordered(Category)
        return render_template('sites.html', sites=sites, categories=categories, filter_type=filter_type)
    
    @app.route('/sites/add', methods=['GET', 'POST'])
    @edit_required
    def add_site():
        """Add a new site"""
        if request.method == 'POST':
            url = request.form.get('url', '').strip()
            name = request.form.get('name', '').strip()
            description = request.form.get('description', '').strip()
            category_id = request.form.get('category_id')
            depth = int(request.form.get('depth', 1))
            crawl_interval = int(request.form.get('crawl_interval', 30))
            include_external = request.form.get('include_external') == 'on'
            use_ai = request.form.get('use_ai') == 'on'
            crawl_method = request.form.get('crawl_method', 'wget')
            
            # Validate URL
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url
            
            # Detect site type
            site_type = 'youtube' if is_youtube_url(url) else 'website'
            
            # Auto-generate name from domain if not provided
            if not name:
                name = urlparse(url).netloc
            
            # Check for duplicates
            existing = Site.query.filter_by(url=url).first()
            if existing:
                return render_template('add_site.html', 
                                       categories=Category.query.all(),
                                       error='Questo sito è già presente nel database')
            
            # AI metadata generation
            ai_category = None
            ai_description = None

            if use_ai:
                try:
                    from app.ollama_client import generate_site_metadata
                    existing_categories = [c.name for c in Category.query.all()]
                    metadata = generate_site_metadata(url, existing_categories)
                    if metadata:
                        ai_category = metadata.get('category')
                        ai_description = metadata.get('description')
                except Exception as e:
                    app.logger.warning(f"AI metadata generation failed: {e}")

            # Handle AI-suggested category
            if ai_category and not category_id:
                cat = get_or_create_category(db, Category, ai_category)
                if cat:
                    category_id = cat.id
            
            # Use AI description if no manual one provided
            if ai_description and not description:
                description = ai_description
            
            site = Site(
                url=url,
                name=name,
                description=description,
                category_id=int(category_id) if category_id else None,
                site_type=site_type,
                depth=depth,
                include_external=include_external,
                crawl_interval_days=crawl_interval,
                crawl_method=crawl_method,
                status='pending'
            )
            
            db.session.add(site)
            db.session.commit()
            
            # Start crawl immediately
            start_crawl(site.id)
            
            return redirect(url_for('sites_list'))
        
        categories = get_categories_ordered(Category)
        ollama_available = check_ollama_safe()
        return render_template('add_site.html', categories=categories, ollama_available=ollama_available)
    
    @app.route('/sites/bulk', methods=['GET', 'POST'])
    @edit_required
    def bulk_add_sites():
        """Bulk add multiple sites"""
        if request.method == 'POST':
            urls_text = request.form.get('urls', '').strip()
            category_id = request.form.get('category_id')
            crawl_interval = int(request.form.get('crawl_interval', 30))
            include_external = request.form.get('include_external') == 'on'
            use_ai = request.form.get('use_ai') == 'on'
            start_immediately = request.form.get('start_immediately') == 'on'

            # Use improved URL extraction and normalization
            from app.utils import extract_url, normalize_url, validate_url

            # Parse URLs (one per line) with improved validation
            raw_lines = [u.strip() for u in urls_text.split('\n') if u.strip()]
            urls = []
            for line in raw_lines:
                extracted = extract_url(line)
                if extracted:
                    normalized = normalize_url(extracted)
                    is_valid, _ = validate_url(normalized)
                    if is_valid:
                        urls.append(normalized)
            
            results = {
                'added': [],
                'skipped': [],
                'errors': []
            }
            
            # Get existing categories for AI
            existing_categories = [c.name for c in Category.query.all()]
            
            for url in urls:
                # URL is already validated and normalized by utils functions
                # Check for duplicates
                existing = Site.query.filter_by(url=url).first()
                if existing:
                    results['skipped'].append({'url': url, 'reason': 'già presente'})
                    continue
                
                try:
                    # Detect site type
                    site_type = 'youtube' if is_youtube_url(url) else 'website'
                    name = urlparse(url).netloc
                    description = None
                    site_category_id = category_id
                    
                    # AI metadata generation
                    if use_ai:
                        try:
                            from app.ollama_client import generate_site_metadata
                            metadata = generate_site_metadata(url, existing_categories)
                            if metadata:
                                if metadata.get('category') and not category_id:
                                    cat = get_or_create_category(db, Category, metadata['category'])
                                    if cat:
                                        existing_categories.append(metadata['category'])
                                        site_category_id = cat.id

                                if metadata.get('description'):
                                    description = metadata['description']
                        except Exception as e:
                            app.logger.warning(f"AI metadata generation failed for {url}: {e}")
                    
                    site = Site(
                        url=url,
                        name=name,
                        description=description,
                        category_id=int(site_category_id) if site_category_id else None,
                        site_type=site_type,
                        depth=1,  # First level only by default
                        include_external=include_external,
                        crawl_interval_days=crawl_interval,
                        status='pending'
                    )
                    
                    db.session.add(site)
                    db.session.flush()
                    
                    results['added'].append({
                        'url': url,
                        'name': name,
                        'site_id': site.id,
                        'type': site_type
                    })
                    
                except Exception as e:
                    results['errors'].append({'url': url, 'error': str(e)})
            
            db.session.commit()
            
            # Start crawls if requested
            if start_immediately:
                for item in results['added']:
                    start_crawl(item['site_id'])
            
            return render_template('bulk_results.html', results=results, start_immediately=start_immediately)

        categories = get_categories_ordered(Category)
        ollama_available = check_ollama_safe()
        return render_template('bulk_add.html', categories=categories, ollama_available=ollama_available)
    
    @app.route('/sites/<int:site_id>')
    def site_detail(site_id):
        """Site detail page"""
        site = Site.query.get_or_404(site_id)
        logs = CrawlLog.query.filter_by(site_id=site_id).order_by(CrawlLog.started_at.desc()).limit(10).all()
        categories = get_categories_ordered(Category)
        
        # Get videos if YouTube channel
        videos = []
        if site.site_type == 'youtube':
            videos = Video.query.filter_by(site_id=site_id).order_by(Video.upload_date.desc()).all()
        
        return render_template('site_detail.html', site=site, logs=logs, categories=categories, videos=videos)
    
    @app.route('/sites/<int:site_id>/crawl', methods=['POST'])
    @edit_required
    def trigger_crawl(site_id):
        """Manually trigger a crawl"""
        site = Site.query.get_or_404(site_id)
        if site.status != 'crawling':
            start_crawl(site.id)
        return redirect(url_for('site_detail', site_id=site_id))
    
    @app.route('/sites/<int:site_id>/delete', methods=['POST'])
    @edit_required
    def delete_site(site_id):
        """Delete a site and its mirror"""
        site = Site.query.get_or_404(site_id)
        
        # Delete mirror from disk
        delete_mirror(site.url, site.site_type, site.channel_id)
        
        # Delete from database (videos cascade automatically)
        CrawlLog.query.filter_by(site_id=site_id).delete()
        db.session.delete(site)
        db.session.commit()
        
        return redirect(url_for('sites_list'))
    
    @app.route('/sites/<int:site_id>/update', methods=['POST'])
    @edit_required
    def update_site(site_id):
        """Update site settings"""
        site = Site.query.get_or_404(site_id)
        
        site.name = request.form.get('name', site.name)
        site.description = request.form.get('description', site.description)
        category_id = request.form.get('category_id')
        site.category_id = int(category_id) if category_id else None
        site.depth = int(request.form.get('depth', site.depth))
        site.include_external = request.form.get('include_external') == 'on'
        site.crawl_interval_days = int(request.form.get('crawl_interval', site.crawl_interval_days))
        crawl_method = request.form.get('crawl_method')
        if crawl_method in ('wget', 'singlefile'):
            site.crawl_method = crawl_method
        
        if site.last_crawl:
            site.next_crawl = site.last_crawl + timedelta(days=site.crawl_interval_days)
        
        db.session.commit()
        
        return redirect(url_for('site_detail', site_id=site_id))
    
    @app.route('/categories')
    def categories_list():
        """List all categories"""
        categories = get_categories_ordered(Category)
        return render_template('categories.html', categories=categories)
    
    @app.route('/categories/add', methods=['POST'])
    @edit_required
    def add_category():
        """Add a new category"""
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        
        if name:
            existing = Category.query.filter_by(name=name).first()
            if not existing:
                category = Category(name=name, description=description)
                db.session.add(category)
                db.session.commit()
        
        return redirect(url_for('categories_list'))
    
    @app.route('/categories/<int:category_id>/delete', methods=['POST'])
    @edit_required
    def delete_category(category_id):
        """Delete a category (sites become uncategorized)"""
        category = Category.query.get_or_404(category_id)

        # Bulk update instead of N+1 loop
        Site.query.filter_by(category_id=category_id).update({'category_id': None})

        db.session.delete(category)
        db.session.commit()

        return redirect(url_for('categories_list'))

    # ==================== CRAWL DASHBOARD ====================

    @app.route('/dashboard')
    def crawl_dashboard():
        """Dashboard showing all crawl statuses"""
        # Get sites grouped by status (still need individual queries for display lists)
        crawling = Site.query.filter_by(status='crawling').order_by(Site.updated_at.desc()).all()
        pending = Site.query.filter_by(status='pending').order_by(Site.created_at.desc()).all()
        retry_pending = Site.query.filter_by(status='retry_pending').order_by(Site.next_crawl).all()
        error = Site.query.filter_by(status='error').order_by(Site.updated_at.desc()).all()
        dead = Site.query.filter_by(status='dead').order_by(Site.updated_at.desc()).all()
        ready = Site.query.filter_by(status='ready').order_by(Site.last_crawl.desc()).limit(20).all()

        # Get active crawls with live info
        active = get_active_crawls()

        # Use single grouped query for stats (optimized)
        stats = get_status_counts(db, Site)

        return render_template('dashboard.html',
                               crawling=crawling,
                               pending=pending,
                               retry_pending=retry_pending,
                               error=error,
                               dead=dead,
                               ready=ready,
                               active=active,
                               stats=stats)

    @app.route('/sites/<int:site_id>/stop', methods=['POST'])
    @edit_required
    def stop_site_crawl(site_id):
        """Stop an active crawl"""
        success, message = stop_crawl(site_id)
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': success, 'message': message})
        return redirect(url_for('site_detail', site_id=site_id))

    @app.route('/sites/<int:site_id>/retry', methods=['POST'])
    @edit_required
    def retry_site_crawl(site_id):
        """Reset error state and retry crawl"""
        site = Site.query.get_or_404(site_id)
        if site.status in ('error', 'dead', 'retry_pending'):
            site.status = 'pending'
            site.error_message = None
            site.retry_count = 0
            db.session.commit()
            start_crawl(site.id)
            message = "Retry avviato"
        else:
            message = "Il sito non è in stato di errore"

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'message': message})
        return redirect(url_for('site_detail', site_id=site_id))

    @app.route('/logs/<int:log_id>')
    def view_crawl_log(log_id):
        """View detailed crawl log"""
        log = CrawlLog.query.get_or_404(log_id)
        site = Site.query.get(log.site_id)
        return render_template('crawl_log.html', log=log, site=site)

    # ==================== MIRROR SERVING ====================

    def generate_auto_index(domain, base_path):
        """Generate an auto-index HTML page for mirrors without index.html"""
        html_files = []
        for root, dirs, files in os.walk(base_path):
            for f in files:
                if f.endswith(('.html', '.htm')) and not f.startswith('_'):
                    rel_path = os.path.relpath(os.path.join(root, f), base_path)
                    # Get title from file if possible
                    title = rel_path
                    try:
                        full_path = os.path.join(root, f)
                        with open(full_path, 'r', encoding='utf-8', errors='ignore') as hf:
                            content = hf.read(4096)  # Read first 4KB
                            import re
                            match = re.search(r'<title[^>]*>([^<]+)</title>', content, re.IGNORECASE)
                            if match:
                                title = match.group(1).strip()[:100]
                    except:
                        pass
                    html_files.append({'path': rel_path, 'title': title})

        # Sort by path
        html_files.sort(key=lambda x: x['path'])

        # Generate HTML
        html = f'''<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Archivio: {domain}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; padding: 2rem; max-width: 1200px; margin: 0 auto; background: #0a0a0a; color: #e0e0e0; }}
        h1 {{ font-size: 2rem; margin-bottom: 0.5rem; color: #fff; }}
        .subtitle {{ color: #888; margin-bottom: 2rem; }}
        .file-list {{ list-style: none; }}
        .file-item {{ border-bottom: 1px solid #222; padding: 0.75rem 0; }}
        .file-item a {{ color: #4a9eff; text-decoration: none; }}
        .file-item a:hover {{ text-decoration: underline; }}
        .file-path {{ font-size: 0.85rem; color: #666; margin-top: 0.25rem; font-family: monospace; }}
        .stats {{ background: #111; padding: 1rem; border-radius: 4px; margin-bottom: 2rem; }}
        .back-link {{ display: inline-block; margin-bottom: 1rem; color: #4a9eff; text-decoration: none; }}
    </style>
</head>
<body>
    <a href="/" class="back-link">← Torna a Speculum</a>
    <h1>📁 {domain}</h1>
    <p class="subtitle">Archivio automatico generato da Speculum</p>
    <div class="stats">{len(html_files)} pagine archiviate</div>
    <ul class="file-list">
'''
        for item in html_files:
            html += f'''        <li class="file-item">
            <a href="{item['path']}">{item['title']}</a>
            <div class="file-path">{item['path']}</div>
        </li>
'''
        html += '''    </ul>
</body>
</html>'''
        return html

    def find_index_html(base_path, max_depth=3):
        """Recursively find the first index.html in a directory tree"""
        if not os.path.isdir(base_path):
            return None
        # Check if index.html exists directly
        for index_name in ['index.html', 'index.htm']:
            direct = os.path.join(base_path, index_name)
            if os.path.exists(direct):
                return direct
        # Search subdirectories (limited depth)
        for root, dirs, files in os.walk(base_path):
            depth = root[len(base_path):].count(os.sep)
            if depth > max_depth:
                dirs[:] = []  # Don't recurse deeper
                continue
            for index_name in ['index.html', 'index.htm']:
                if index_name in files:
                    return os.path.join(root, index_name)
        return None

    def find_file_in_mirror(base_path, file_path):
        """Find a file in the mirror, handling wget's directory structure quirks"""
        # Try exact path first
        full_path = os.path.join(base_path, file_path) if file_path else base_path
        if os.path.exists(full_path):
            return full_path

        # wget sometimes creates nested domain directories
        # e.g., /mirrors/example.com/example.com/page.html
        if file_path:
            parts = file_path.split('/')
            for i in range(len(parts)):
                nested = os.path.join(base_path, *parts[i:])
                if os.path.exists(nested):
                    return nested

        # Try with .html extension
        if file_path and '.' not in os.path.basename(file_path):
            for ext in ['.html', '.htm']:
                with_ext = full_path + ext
                if os.path.exists(with_ext):
                    return with_ext

        return None

    def is_safe_path(base_path, requested_path):
        """Validate path to prevent directory traversal attacks"""
        if not requested_path:
            return False
        try:
            base_real = os.path.realpath(base_path)
            requested_real = os.path.realpath(requested_path)
            # Use commonpath for robust cross-platform checking
            common = os.path.commonpath([base_real, requested_real])
            return common == base_real
        except (ValueError, TypeError):
            return False

    @app.route('/mirror/<path:site_path>')
    def serve_mirror(site_path):
        """Serve mirrored site files"""
        # Remove trailing slash for consistent handling
        site_path = site_path.rstrip('/')

        # Validate path doesn't contain traversal attempts
        if '..' in site_path or site_path.startswith('/'):
            abort(403)

        parts = site_path.split('/', 1)
        domain = parts[0]
        file_path = parts[1] if len(parts) > 1 else ''

        # Validate domain name (alphanumeric, dots, hyphens only)
        if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9.-]*[a-zA-Z0-9]$|^[a-zA-Z0-9]$', domain):
            abort(403)

        domain_path = os.path.join(MIRRORS_BASE_PATH, domain)

        # Security check: ensure domain_path is within MIRRORS_BASE_PATH
        if not is_safe_path(MIRRORS_BASE_PATH, domain_path):
            abort(403)

        # Check if domain directory exists
        if not os.path.isdir(domain_path):
            abort(404)

        # Find the actual file
        full_path = find_file_in_mirror(domain_path, file_path)

        # If path not found directly, try to find index.html
        if full_path is None or os.path.isdir(full_path if full_path else domain_path):
            search_path = full_path if full_path and os.path.isdir(full_path) else domain_path
            found = find_index_html(search_path)
            if found:
                full_path = found
            else:
                # No index.html found - generate auto-index for root domain only
                if not file_path or file_path == '/':
                    auto_index = generate_auto_index(domain, domain_path)
                    return Response(auto_index, mimetype='text/html')
                abort(404)

        # Handle directory - serve index.html
        if os.path.isdir(full_path):
            index = find_index_html(full_path)
            if index:
                full_path = index
            else:
                # Generate auto-index for subdirectory
                auto_index = generate_auto_index(domain, full_path)
                return Response(auto_index, mimetype='text/html')

        if not full_path or not os.path.exists(full_path):
            abort(404)

        # Final security check: ensure full_path is within MIRRORS_BASE_PATH
        if not is_safe_path(MIRRORS_BASE_PATH, full_path):
            abort(403)

        directory = os.path.dirname(full_path)
        filename = os.path.basename(full_path)

        return send_from_directory(directory, filename)

    @app.route('/sites/<int:site_id>/clear-files', methods=['POST'])
    @admin_required
    def clear_site_files(site_id):
        """Delete crawled files but keep database entry"""
        site = Site.query.get_or_404(site_id)

        # Delete mirror from disk
        delete_mirror(site.url, site.site_type, site.channel_id)

        # Reset site status and stats using helper method
        site.reset_crawl_state()
        db.session.commit()

        return redirect(url_for('site_detail', site_id=site_id))
    
    @app.route('/video/<int:site_id>/<video_id>/<path:filename>')
    def serve_video(site_id, video_id, filename):
        """Serve YouTube video files"""
        # Security: validate inputs
        if '..' in video_id or '..' in filename:
            abort(403)

        site = Site.query.get_or_404(site_id)
        if site.site_type != 'youtube':
            abort(404)

        if not site.channel_id:
            abort(404)

        video_path = os.path.join(MIRRORS_BASE_PATH, 'youtube', site.channel_id, video_id)
        full_file_path = os.path.join(video_path, filename)

        # Security check
        if not is_safe_path(MIRRORS_BASE_PATH, full_file_path):
            abort(403)

        if not os.path.exists(full_file_path):
            abort(404)

        return send_from_directory(video_path, filename)

    @app.route('/screenshot/<int:site_id>')
    def serve_screenshot(site_id):
        """Serve site screenshot"""
        site = Site.query.get_or_404(site_id)
        if not site.screenshot_path:
            abort(404)

        # Security: validate path
        if '..' in site.screenshot_path:
            abort(403)

        screenshot_full_path = os.path.join(MIRRORS_BASE_PATH, site.screenshot_path)

        # Security check
        if not is_safe_path(MIRRORS_BASE_PATH, screenshot_full_path):
            abort(403)

        if not os.path.exists(screenshot_full_path):
            abort(404)

        directory = os.path.dirname(screenshot_full_path)
        filename = os.path.basename(screenshot_full_path)
        return send_from_directory(directory, filename)

    @app.route('/thumbnail/<int:site_id>')
    def serve_thumbnail(site_id):
        """Serve site thumbnail"""
        site = Site.query.get_or_404(site_id)
        if not site.screenshot_path:
            abort(404)

        # Thumbnail is in same dir as screenshot but named thumbnail.jpg
        parsed = urlparse(site.url)
        thumb_path = os.path.join(MIRRORS_BASE_PATH, parsed.netloc, '_speculum', 'thumbnail.jpg')

        if not os.path.exists(thumb_path):
            # Fallback to full screenshot
            screenshot_full_path = os.path.join(MIRRORS_BASE_PATH, site.screenshot_path)
            if os.path.exists(screenshot_full_path):
                directory = os.path.dirname(screenshot_full_path)
                filename = os.path.basename(screenshot_full_path)
                return send_from_directory(directory, filename)
            abort(404)

        directory = os.path.dirname(thumb_path)
        filename = os.path.basename(thumb_path)
        return send_from_directory(directory, filename)

    @app.route('/videos/<int:site_id>')
    def channel_videos(site_id):
        """List all videos for a YouTube channel"""
        site = Site.query.get_or_404(site_id)
        if site.site_type != 'youtube':
            abort(404)
        
        videos = Video.query.filter_by(site_id=site_id).order_by(Video.upload_date.desc()).all()
        return render_template('videos.html', site=site, videos=videos)
    
    @app.route('/watch/<int:video_id>')
    def watch_video(video_id):
        """Video player page"""
        video = Video.query.get_or_404(video_id)
        site = Site.query.get(video.site_id)
        return render_template('watch.html', video=video, site=site)
    
    # ==================== API ROUTES ====================
    
    @app.route('/api/sites')
    def api_sites():
        """API: List all sites"""
        sites = Site.query.order_by(Site.name).all()
        return jsonify([s.to_dict() for s in sites])
    
    @app.route('/api/sites/<int:site_id>')
    def api_site(site_id):
        """API: Get site details"""
        site = Site.query.get_or_404(site_id)
        return jsonify(site.to_dict())
    
    @app.route('/api/sites/<int:site_id>/status')
    def api_site_status(site_id):
        """API: Get site crawl status (for polling)"""
        site = Site.query.get_or_404(site_id)
        return jsonify({
            'status': site.status,
            'last_crawl': site.last_crawl.isoformat() if site.last_crawl else None,
            'error_message': site.error_message,
            'size_human': site._human_size(site.size_bytes),
            'page_count': site.page_count
        })
    
    @app.route('/api/categories')
    def api_categories():
        """API: List all categories"""
        categories = get_categories_ordered(Category)
        return jsonify([c.to_dict() for c in categories])
    
    @app.route('/api/stats')
    def api_stats():
        """API: Global statistics"""
        from sqlalchemy import func
        stats = get_dashboard_stats(db, Site, Video)
        stats['crawling_sites'] = Site.query.filter_by(status='crawling').count()
        stats['error_sites'] = Site.query.filter_by(status='error').count()
        stats['total_size_bytes'] = stats.pop('total_size')
        stats['total_pages'] = db.session.query(func.coalesce(func.sum(Site.page_count), 0)).scalar()
        return jsonify(stats)
    
    @app.route('/api/ollama/status')
    def api_ollama_status():
        """API: Check Ollama status"""
        try:
            from app.ollama_client import check_ollama_available, OLLAMA_MODEL
            available = check_ollama_available()
            return jsonify({
                'available': available,
                'model': OLLAMA_MODEL
            })
        except Exception as e:
            return jsonify({
                'available': False,
                'error': str(e)
            })

    @app.route('/api/crawls/active')
    def api_active_crawls():
        """API: Get all active crawls with live status"""
        return jsonify(get_active_crawls())

    @app.route('/api/crawls/<int:site_id>/progress')
    def api_crawl_progress(site_id):
        """API: Get progress of an active crawl"""
        progress = get_crawl_progress(site_id)
        if progress is None:
            return jsonify({'error': 'No active crawl for this site'}), 404
        return jsonify(progress)

    @app.route('/api/crawls/<int:site_id>/log')
    def api_crawl_live_log(site_id):
        """API: Get live log of an active crawl"""
        lines = request.args.get('lines', 50, type=int)
        log_lines = get_crawl_live_log(site_id, lines)
        if log_lines is None:
            # Try to get from database if not active
            log = CrawlLog.query.filter_by(site_id=site_id).order_by(CrawlLog.started_at.desc()).first()
            if log and log.wget_log:
                log_lines = log.wget_log.split('\n')[-lines:]
            else:
                return jsonify({'error': 'No log available'}), 404
        return jsonify({'lines': log_lines})

    @app.route('/api/dashboard/stats')
    def api_dashboard_stats():
        """API: Get dashboard statistics for polling (single query)"""
        stats = get_status_counts(db, Site)
        active = get_active_crawls()
        return jsonify({'stats': stats, 'active': active})

    @app.route('/api/sites/<int:site_id>/generate-metadata', methods=['POST'])
    @edit_required
    def api_generate_metadata(site_id):
        """API: Generate AI metadata for a site"""
        try:
            from app.ai_metadata import update_site_with_ai_metadata
            success = update_site_with_ai_metadata(site_id)
            if success:
                return jsonify({'success': True, 'message': 'Metadati AI generati'})
            return jsonify({'success': False, 'message': 'Generazione fallita'}), 400
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/sites/<int:site_id>/generate-metadata', methods=['POST'])
    @edit_required
    def generate_site_metadata(site_id):
        """Generate AI metadata for a site (web route)"""
        try:
            from app.ai_metadata import update_site_with_ai_metadata
            update_site_with_ai_metadata(site_id)
        except Exception as e:
            app.logger.error(f"AI metadata generation failed: {e}")
        return redirect(url_for('site_detail', site_id=site_id))

    # ==================== BULK OPERATIONS ====================

    @app.route('/admin/clear-all-files', methods=['POST'])
    @admin_required
    def clear_all_files():
        """Delete ALL crawled files but keep all site entries in database"""
        sites = Site.query.filter(Site.status == 'ready').all()
        cleared_count = 0

        for site in sites:
            try:
                # Delete mirror files
                delete_mirror(site.url, site.site_type, site.channel_id)

                # Reset site status using helper method
                site.reset_crawl_state()

                cleared_count += 1
            except Exception as e:
                app.logger.error(f"Error clearing {site.url}: {e}")

        db.session.commit()

        return redirect(url_for('crawl_dashboard'))

    @app.route('/admin/restart-all-crawls', methods=['POST'])
    @admin_required
    def restart_all_crawls():
        """Start crawl for all pending sites"""
        pending_sites = Site.query.filter(Site.status.in_(['pending', 'error', 'dead', 'retry_pending'])).all()

        for site in pending_sites[:10]:  # Limit to 10 at a time
            site.status = 'pending'
            site.error_message = None
            site.retry_count = 0
            start_crawl(site.id)

        db.session.commit()

        return redirect(url_for('crawl_dashboard'))

    # ==================== MEDIA GALLERY ====================

    @app.route('/sites/<int:site_id>/media')
    def site_media_gallery(site_id):
        """View all media files in a mirrored site"""
        site = Site.query.get_or_404(site_id)

        if site.status != 'ready' or site.site_type == 'youtube':
            return redirect(url_for('site_detail', site_id=site_id))

        # Get mirror path
        mirror_path = get_mirror_path(site.url)

        # Find all image files
        media_files = []
        image_extensions = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.ico')

        if os.path.exists(mirror_path):
            for root, dirs, files in os.walk(mirror_path):
                # Skip _speculum directory
                if '_speculum' in root:
                    continue
                for f in files:
                    if f.lower().endswith(image_extensions):
                        full_path = os.path.join(root, f)
                        rel_path = os.path.relpath(full_path, MIRRORS_PATH)
                        size = os.path.getsize(full_path)
                        media_files.append({
                            'name': f,
                            'path': rel_path,
                            'size': size,
                            'size_human': Site._human_size(size)
                        })

        # Sort by size descending
        media_files.sort(key=lambda x: x['size'], reverse=True)

        return render_template('media_gallery.html', site=site, media_files=media_files[:200])

    @app.route('/media/<path:file_path>')
    def serve_media(file_path):
        """Serve media files from mirrors"""
        # Security: validate path
        if '..' in file_path or file_path.startswith('/'):
            abort(403)

        full_path = os.path.join(MIRRORS_PATH, file_path)

        # Security check
        if not is_safe_path(MIRRORS_PATH, full_path):
            abort(403)

        if not os.path.exists(full_path):
            abort(404)

        directory = os.path.dirname(full_path)
        filename = os.path.basename(full_path)

        return send_from_directory(directory, filename)

    # ==================== WAYBACK MACHINE INTEGRATION ====================

    @app.route('/sites/<int:site_id>/wayback-screenshot', methods=['POST'])
    def fetch_wayback_screenshot(site_id):
        """Fetch screenshot from Wayback Machine"""
        import requests

        site = Site.query.get_or_404(site_id)

        try:
            # Check if URL is archived
            availability_url = f"https://archive.org/wayback/available?url={site.url}"
            response = requests.get(availability_url, timeout=10)
            data = response.json()

            if data.get('archived_snapshots', {}).get('closest'):
                snapshot = data['archived_snapshots']['closest']
                wayback_url = snapshot['url']

                # Get thumbnail from Wayback
                # Format: https://web.archive.org/web/TIMESTAMP/im_/URL
                timestamp = snapshot['timestamp']
                thumb_url = f"https://web.archive.org/web/{timestamp}im_/{site.url}"

                # Download thumbnail
                parsed = urlparse(site.url)
                speculum_dir = os.path.join(MIRRORS_PATH, parsed.netloc, '_speculum')
                os.makedirs(speculum_dir, exist_ok=True)

                thumb_path = os.path.join(speculum_dir, 'wayback_thumb.jpg')

                img_response = requests.get(thumb_url, timeout=30)
                if img_response.status_code == 200:
                    with open(thumb_path, 'wb') as f:
                        f.write(img_response.content)

                    site.screenshot_path = f"{parsed.netloc}/_speculum/wayback_thumb.jpg"
                    db.session.commit()

        except Exception as e:
            app.logger.error(f"Wayback screenshot failed for {site.url}: {e}")

        return redirect(url_for('site_detail', site_id=site_id))

    @app.route('/api/wayback/<int:site_id>')
    def api_wayback_info(site_id):
        """API: Get Wayback Machine info for a site"""
        import requests

        site = Site.query.get_or_404(site_id)

        try:
            availability_url = f"https://archive.org/wayback/available?url={site.url}"
            response = requests.get(availability_url, timeout=10)
            return jsonify(response.json())
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    return app


# For running with gunicorn
app = create_app()

if __name__ == '__main__':
    from app.scheduler import init_scheduler
    init_scheduler(app)
    app.run(host='0.0.0.0', port=5000, debug=True)
