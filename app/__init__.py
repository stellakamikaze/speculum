import os
from flask import Flask, render_template, request, jsonify, redirect, url_for, send_from_directory, abort
from urllib.parse import urlparse
from datetime import datetime, timedelta

def create_app():
    app = Flask(__name__, 
                template_folder='../templates',
                static_folder='../static')
    
    # Configuration
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'speculum-dev-key-change-in-production')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///speculum.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    MIRRORS_PATH = os.environ.get('MIRRORS_PATH', '/mirrors')
    
    # Initialize extensions
    from app.models import db
    db.init_app(app)
    
    with app.app_context():
        db.create_all()
    
    # Import models and utilities
    from app.models import Site, Category, CrawlLog, Video
    from app.crawler import (
        start_crawl, delete_mirror, get_mirror_path, is_youtube_url, MIRRORS_BASE_PATH,
        stop_crawl, get_active_crawls, get_crawl_live_log, get_crawl_progress
    )
    
    # ==================== WEB ROUTES ====================
    
    @app.route('/')
    def index():
        """Main catalog page"""
        categories = Category.query.order_by(Category.name).all()
        uncategorized_sites = Site.query.filter_by(category_id=None).order_by(Site.name).all()
        
        all_sites = Site.query.all()
        stats = {
            'total_sites': len(all_sites),
            'ready_sites': sum(1 for s in all_sites if s.status == 'ready'),
            'total_size': sum(s.size_bytes or 0 for s in all_sites),
            'categories': len(categories),
            'youtube_channels': sum(1 for s in all_sites if s.site_type == 'youtube'),
            'total_videos': Video.query.count()
        }
        
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
        
        categories = Category.query.order_by(Category.name).all()
        return render_template('sites.html', sites=sites, categories=categories, filter_type=filter_type)
    
    @app.route('/sites/add', methods=['GET', 'POST'])
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
                # Check if category exists, create if not
                cat = Category.query.filter_by(name=ai_category).first()
                if not cat:
                    cat = Category(name=ai_category)
                    db.session.add(cat)
                    db.session.flush()
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
                status='pending',
                ai_generated=use_ai and (ai_category or ai_description)
            )
            
            db.session.add(site)
            db.session.commit()
            
            # Start crawl immediately
            start_crawl(site.id)
            
            return redirect(url_for('sites_list'))
        
        categories = Category.query.order_by(Category.name).all()
        
        # Check if Ollama is available
        ollama_available = False
        try:
            from app.ollama_client import check_ollama_available
            ollama_available = check_ollama_available()
        except:
            pass
        
        return render_template('add_site.html', categories=categories, ollama_available=ollama_available)
    
    @app.route('/sites/bulk', methods=['GET', 'POST'])
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
                                    # Check if category exists, create if not
                                    cat = Category.query.filter_by(name=metadata['category']).first()
                                    if not cat:
                                        cat = Category(name=metadata['category'])
                                        db.session.add(cat)
                                        db.session.flush()
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
                        status='pending',
                        ai_generated=use_ai
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
        
        categories = Category.query.order_by(Category.name).all()
        
        # Check if Ollama is available
        ollama_available = False
        try:
            from app.ollama_client import check_ollama_available
            ollama_available = check_ollama_available()
        except:
            pass
        
        return render_template('bulk_add.html', categories=categories, ollama_available=ollama_available)
    
    @app.route('/sites/<int:site_id>')
    def site_detail(site_id):
        """Site detail page"""
        site = Site.query.get_or_404(site_id)
        logs = CrawlLog.query.filter_by(site_id=site_id).order_by(CrawlLog.started_at.desc()).limit(10).all()
        categories = Category.query.order_by(Category.name).all()
        
        # Get videos if YouTube channel
        videos = []
        if site.site_type == 'youtube':
            videos = Video.query.filter_by(site_id=site_id).order_by(Video.upload_date.desc()).all()
        
        return render_template('site_detail.html', site=site, logs=logs, categories=categories, videos=videos)
    
    @app.route('/sites/<int:site_id>/crawl', methods=['POST'])
    def trigger_crawl(site_id):
        """Manually trigger a crawl"""
        site = Site.query.get_or_404(site_id)
        if site.status != 'crawling':
            start_crawl(site.id)
        return redirect(url_for('site_detail', site_id=site_id))
    
    @app.route('/sites/<int:site_id>/delete', methods=['POST'])
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
        categories = Category.query.order_by(Category.name).all()
        return render_template('categories.html', categories=categories)
    
    @app.route('/categories/add', methods=['POST'])
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
    def delete_category(category_id):
        """Delete a category (sites become uncategorized)"""
        category = Category.query.get_or_404(category_id)

        for site in category.sites:
            site.category_id = None

        db.session.delete(category)
        db.session.commit()

        return redirect(url_for('categories_list'))

    # ==================== CRAWL DASHBOARD ====================

    @app.route('/dashboard')
    def crawl_dashboard():
        """Dashboard showing all crawl statuses"""
        # Get sites grouped by status
        crawling = Site.query.filter_by(status='crawling').order_by(Site.updated_at.desc()).all()
        pending = Site.query.filter_by(status='pending').order_by(Site.created_at.desc()).all()
        retry_pending = Site.query.filter_by(status='retry_pending').order_by(Site.next_crawl).all()
        error = Site.query.filter_by(status='error').order_by(Site.updated_at.desc()).all()
        dead = Site.query.filter_by(status='dead').order_by(Site.updated_at.desc()).all()
        ready = Site.query.filter_by(status='ready').order_by(Site.last_crawl.desc()).limit(20).all()

        # Get active crawls with live info
        active = get_active_crawls()

        stats = {
            'crawling': len(crawling),
            'pending': len(pending),
            'retry_pending': len(retry_pending),
            'error': len(error),
            'dead': len(dead),
            'ready': Site.query.filter_by(status='ready').count()
        }

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
    def stop_site_crawl(site_id):
        """Stop an active crawl"""
        success, message = stop_crawl(site_id)
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': success, 'message': message})
        return redirect(url_for('site_detail', site_id=site_id))

    @app.route('/sites/<int:site_id>/retry', methods=['POST'])
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

    @app.route('/mirror/<path:site_path>')
    def serve_mirror(site_path):
        """Serve mirrored site files"""
        # Remove trailing slash for consistent handling
        site_path = site_path.rstrip('/')

        parts = site_path.split('/', 1)
        domain = parts[0]
        file_path = parts[1] if len(parts) > 1 else ''

        domain_path = os.path.join(MIRRORS_BASE_PATH, domain)

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
                abort(404)

        # Handle directory - serve index.html
        if os.path.isdir(full_path):
            index = find_index_html(full_path)
            if index:
                full_path = index
            else:
                abort(404)

        if not full_path or not os.path.exists(full_path):
            abort(404)

        directory = os.path.dirname(full_path)
        filename = os.path.basename(full_path)

        return send_from_directory(directory, filename)

    @app.route('/sites/<int:site_id>/clear-files', methods=['POST'])
    def clear_site_files(site_id):
        """Delete crawled files but keep database entry"""
        site = Site.query.get_or_404(site_id)

        # Delete mirror from disk
        delete_mirror(site.url, site.site_type, site.channel_id)

        # Reset site status and stats
        site.status = 'pending'
        site.size_bytes = 0
        site.page_count = 0
        site.screenshot_path = None
        site.screenshot_date = None
        site.error_message = None
        site.retry_count = 0

        db.session.commit()

        return redirect(url_for('site_detail', site_id=site_id))
    
    @app.route('/video/<int:site_id>/<video_id>/<path:filename>')
    def serve_video(site_id, video_id, filename):
        """Serve YouTube video files"""
        site = Site.query.get_or_404(site_id)
        if site.site_type != 'youtube':
            abort(404)
        
        video_path = os.path.join(MIRRORS_BASE_PATH, 'youtube', site.channel_id, video_id)
        
        if not os.path.exists(os.path.join(video_path, filename)):
            abort(404)
        
        return send_from_directory(video_path, filename)

    @app.route('/screenshot/<int:site_id>')
    def serve_screenshot(site_id):
        """Serve site screenshot"""
        site = Site.query.get_or_404(site_id)
        if not site.screenshot_path:
            abort(404)

        screenshot_full_path = os.path.join(MIRRORS_BASE_PATH, site.screenshot_path)
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
        from urllib.parse import urlparse
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

    @app.route('/sites/<int:site_id>/screenshot', methods=['POST'])
    def generate_screenshot(site_id):
        """Generate screenshot for a site"""
        try:
            from app.screenshot import update_site_screenshot, is_screenshot_available
            if not is_screenshot_available():
                return redirect(url_for('site_detail', site_id=site_id))
            update_site_screenshot(site_id)
        except Exception as e:
            app.logger.error(f"Screenshot generation failed: {e}")
        return redirect(url_for('site_detail', site_id=site_id))

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
        categories = Category.query.order_by(Category.name).all()
        return jsonify([c.to_dict() for c in categories])
    
    @app.route('/api/stats')
    def api_stats():
        """API: Global statistics"""
        sites = Site.query.all()
        return jsonify({
            'total_sites': len(sites),
            'ready_sites': sum(1 for s in sites if s.status == 'ready'),
            'crawling_sites': sum(1 for s in sites if s.status == 'crawling'),
            'error_sites': sum(1 for s in sites if s.status == 'error'),
            'total_size_bytes': sum(s.size_bytes or 0 for s in sites),
            'total_pages': sum(s.page_count or 0 for s in sites),
            'youtube_channels': sum(1 for s in sites if s.site_type == 'youtube'),
            'total_videos': Video.query.count()
        })
    
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
        """API: Get dashboard statistics for polling"""
        stats = {
            'crawling': Site.query.filter_by(status='crawling').count(),
            'pending': Site.query.filter_by(status='pending').count(),
            'retry_pending': Site.query.filter_by(status='retry_pending').count(),
            'error': Site.query.filter_by(status='error').count(),
            'dead': Site.query.filter_by(status='dead').count(),
            'ready': Site.query.filter_by(status='ready').count()
        }
        active = get_active_crawls()
        return jsonify({'stats': stats, 'active': active})

    @app.route('/api/sites/<int:site_id>/generate-metadata', methods=['POST'])
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
    def clear_all_files():
        """Delete ALL crawled files but keep all site entries in database"""
        import shutil

        sites = Site.query.filter(Site.status == 'ready').all()
        cleared_count = 0

        for site in sites:
            try:
                # Delete mirror files
                delete_mirror(site.url, site.site_type, site.channel_id)

                # Reset site status
                site.status = 'pending'
                site.size_bytes = 0
                site.page_count = 0
                site.screenshot_path = None
                site.screenshot_date = None
                site.error_message = None
                site.retry_count = 0

                cleared_count += 1
            except Exception as e:
                app.logger.error(f"Error clearing {site.url}: {e}")

        db.session.commit()

        return redirect(url_for('crawl_dashboard'))

    @app.route('/admin/restart-all-crawls', methods=['POST'])
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
        full_path = os.path.join(MIRRORS_PATH, file_path)

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
                from urllib.parse import urlparse
                parsed = urlparse(site.url)
                speculum_dir = os.path.join(MIRRORS_PATH, parsed.netloc, '_speculum')
                os.makedirs(speculum_dir, exist_ok=True)

                thumb_path = os.path.join(speculum_dir, 'wayback_thumb.jpg')

                img_response = requests.get(thumb_url, timeout=30)
                if img_response.status_code == 200:
                    with open(thumb_path, 'wb') as f:
                        f.write(img_response.content)

                    site.screenshot_path = f"{parsed.netloc}/_speculum/wayback_thumb.jpg"
                    site.screenshot_date = datetime.utcnow()
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
