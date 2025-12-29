# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Speculum is a self-hosted web mirroring system for archiving websites and YouTube channels. It runs as a Docker container with Flask/Gunicorn backend, SQLite database, and optional Ollama for AI-powered metadata generation.

## Development Commands

```bash
# Start the full stack (app + Ollama)
docker-compose up -d --build

# View logs
docker-compose logs -f speculum

# Access the app
# Web UI: http://localhost:5050

# Download Ollama model (optional, for AI categorization)
docker exec -it speculum-ollama ollama pull tinyllama

# Restart after code changes
docker-compose restart speculum

# Run Python syntax check (no test suite exists)
python -c "import ast; ast.parse(open('app/__init__.py', encoding='utf-8').read())"
```

## Architecture

### Core Components

**app/__init__.py** - Main Flask application factory (`create_app()`)
- Route definitions for web UI and REST API
- Authentication decorators: `@login_required`, `@admin_required`, `@edit_required`
- Security middleware: CSRF protection, rate limiting, security headers
- User session management via Flask sessions

**app/models.py** - SQLAlchemy models
- `User` - Authentication with scrypt password hashing, roles (admin/user/viewer)
- `Site` - Archived websites/YouTube channels with status tracking
- `Video` - YouTube video metadata (linked to Site)
- `MirrorRequest` - Public mirror submission queue
- `Category`, `CrawlLog`

**app/crawler.py** - Background crawling engine
- `start_crawl(site_id)` - Spawns background thread for crawling
- `crawl_website()` - wget-based mirroring with retry logic
- `crawl_youtube()` - yt-dlp for YouTube channels
- `crawl_singlefile()` - SingleFile CLI for JavaScript-heavy sites
- Active crawl tracking via `active_crawls` dict with thread-safe locks

**app/scheduler.py** - APScheduler background jobs
- Hourly check for scheduled re-crawls
- 5-minute retry queue processing
- 30-minute stuck crawl detection

### Crawl Methods

1. **wget** (default) - `build_wget_command()` creates wget mirror with rate limiting
2. **singlefile** - SingleFile CLI for fully-rendered single-page captures
3. **yt-dlp** - YouTube channel/video archiving

### Directory Structure

```
/mirrors/                    # Archived content (Docker volume)
  example.com/               # Website mirrors by domain
  youtube/{channel_id}/      # YouTube videos by channel
    {video_id}/              # Individual video folder
/app/instance/speculum.db    # SQLite database
```

### Authentication Flow

- Session-based auth with 7-day permanent sessions
- Admin created from `ADMIN_USERNAME`/`ADMIN_PASSWORD` env vars on startup
- Three roles: `admin` (full access), `user` (can edit), `viewer` (read-only)
- Public routes: `/`, `/sites`, `/request-mirror`, `/api/*` (read-only)

### API Endpoints

- `GET /api/sites` - List all sites
- `GET /api/sites/<id>/status` - Crawl status polling
- `GET /api/crawls/active` - Active crawl list
- `GET /api/crawls/<id>/log` - Live crawl log
- `POST /api/sites/<id>/generate-metadata` - Trigger AI metadata (requires auth)

## Key Patterns

### Error Handling in Crawler

Errors classified as:
- **Recoverable** (timeout, 503, 429) - Retry with exponential backoff (5/15/45 min)
- **Permanent** (404, 403, SSL errors) - Mark as "dead", no retry
- Max 3 retry attempts before giving up

### Site Status Flow

`pending` -> `crawling` -> `ready` (success)
                       -> `error` (recoverable)
                       -> `retry_pending` -> `crawling` (retry loop)
                       -> `dead` (permanent failure)

### Security Considerations

- CSRF tokens required on all POST forms (`{{ csrf_token() }}`)
- Path traversal protection via `is_safe_path()` in file serving
- Rate limiting: 10/min on login, 5/hour on mirror requests
- Security headers: X-Frame-Options, X-Content-Type-Options, HSTS

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SECRET_KEY` | Yes (prod) | Flask secret key |
| `ADMIN_USERNAME` | Yes (prod) | Admin account username |
| `ADMIN_PASSWORD` | Yes (prod) | Admin account password |
| `FLASK_ENV` | No | Set to "production" for secure cookies |
| `OLLAMA_URL` | No | Ollama API endpoint |
| `TELEGRAM_BOT_TOKEN` | No | For notification webhooks |

## Language

The application UI is in Italian (forms, buttons, error messages).
