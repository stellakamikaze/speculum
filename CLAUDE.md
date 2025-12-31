# Speculum

Web mirroring system for archiving websites and YouTube channels.

## Quick Start

```bash
# Start
colima start --cpu 4 --memory 6 --disk 80
docker compose up -d --build

# Access
open http://localhost:5050

# Logs
docker compose logs -f speculum
```

## Architecture

```
app/
├── __init__.py      # Flask app factory, routes, middleware
├── models.py        # SQLAlchemy models (User, Site, Video, etc.)
├── crawler.py       # wget/yt-dlp/singlefile crawling engine
├── search.py        # SQLite FTS5 full-text search
├── backup.py        # Database export/import
├── export.py        # Ghost CMS export
├── wayback.py       # Archive.org integration
├── scheduler.py     # APScheduler background jobs
├── telegram.py      # Notifications
└── ai_metadata.py   # Ollama-powered metadata generation
```

## Key Models

| Model | Purpose |
|-------|---------|
| `Site` | Archived websites/YouTube channels |
| `Video` | YouTube video metadata |
| `MirrorRequest` | Public submission queue |
| `CulturalMetadata` | Extended cultural fields (Celeste) |

## Crawl Methods

- **wget** (default): Recursive mirroring with rate limiting
- **singlefile**: JS-rendered single-page capture
- **yt-dlp**: YouTube channels/videos

## Site Status Flow

```
pending → crawling → ready (success)
                  → error → retry_pending → crawling (max 3 retries)
                  → dead (permanent failure)
```

## API Endpoints

```
GET  /api/sites              # List all
GET  /api/sites/<id>/status  # Crawl status
GET  /api/search?q=keyword   # Full-text search
POST /api/sites/<id>/generate-metadata  # AI metadata (auth required)
```

## Features Implemented

- Full-text search (SQLite FTS5)
- Database backup/export
- Ghost CMS export
- Wayback Machine integration
- AI metadata generation (Ollama)
- Telegram notifications
- oEmbed support

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SECRET_KEY` | Yes | Flask secret |
| `ADMIN_USERNAME` | Yes | Admin login |
| `ADMIN_PASSWORD` | Yes | Admin password |
| `OLLAMA_URL` | No | Default: `http://host.docker.internal:11434` |
| `TELEGRAM_BOT_TOKEN` | No | For notifications |

## Development

```bash
# Syntax check
python -c "import ast; ast.parse(open('app/__init__.py', encoding='utf-8').read())"

# Rebuild after changes
docker compose restart speculum
```

## Security

- CSRF protection on all forms
- Rate limiting (10/min login, 5/hour mirror requests)
- Path traversal protection in file serving
- Scrypt password hashing

## Development Workflow

This project uses **beads** (`bd`) for task tracking.

```bash
bd ready          # Check available tasks
bd create "Task"  # Create new issue
bd close <id>     # Complete task
```

### When implementing features:
1. `/brainstorm` - Explore approach
2. `/write-plan` - Detail implementation steps
3. TDD: test first, then implement
4. `verification-before-completion` - Verify before claiming done

## Roadmap

See `NEXT_STEPS.md` for full roadmap including Celeste integration.
