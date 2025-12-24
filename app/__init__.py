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
    from app.crawler import start_crawl, delete_mirror, get_mirror_path, is_youtube_url, MIRRORS_BASE_PATH
    
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
            depth = int(request.form.get('depth', 0))
            crawl_interval = int(request.form.get('crawl_interval', 30))
            include_external = request.form.get('include_external') == 'on'
            use_ai = request.form.get('use_ai') == 'on'
            
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
            
            # Parse URLs (one per line)
            urls = [u.strip() for u in urls_text.split('\n') if u.strip()]
            
            results = {
                'added': [],
                'skipped': [],
                'errors': []
            }
            
            # Get existing categories for AI
            existing_categories = [c.name for c in Category.query.all()]
            
            for url in urls:
                # Validate URL
                if not url.startswith(('http://', 'https://')):
                    url = 'https://' + url
                
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
                        depth=0,
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
    
    # ==================== MIRROR SERVING ====================
    
    @app.route('/mirror/<path:site_path>')
    def serve_mirror(site_path):
        """Serve mirrored site files"""
        parts = site_path.split('/', 1)
        domain = parts[0]
        file_path = parts[1] if len(parts) > 1 else 'index.html'
        
        full_path = os.path.join(MIRRORS_BASE_PATH, domain, file_path)
        
        if os.path.isdir(full_path):
            full_path = os.path.join(full_path, 'index.html')
            file_path = os.path.join(file_path, 'index.html')
        
        if not os.path.exists(full_path) and '.' not in os.path.basename(full_path):
            if os.path.exists(full_path + '.html'):
                full_path = full_path + '.html'
                file_path = file_path + '.html'
        
        if not os.path.exists(full_path):
            abort(404)
        
        directory = os.path.dirname(full_path)
        filename = os.path.basename(full_path)
        
        return send_from_directory(directory, filename)
    
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
    
    return app


# For running with gunicorn
app = create_app()

if __name__ == '__main__':
    from app.scheduler import init_scheduler
    init_scheduler(app)
    app.run(host='0.0.0.0', port=5000, debug=True)
