# Speculum

Self-hosted web mirroring system for archiving websites and YouTube channels.

## Features

- **Website mirroring** via wget with full link conversion
- **YouTube channel archiving** via yt-dlp (video + thumbnail + metadata)
- **Bulk import** for adding multiple URLs at once
- **AI categorization** via Ollama for automatic metadata generation
- **External resources** option to include images/assets from other domains
- **Scheduled updates** with configurable intervals per site
- **Web UI** for browsing archived content

## Requirements

- Docker & Docker Compose
- ~2GB disk space for Ollama model (optional, for AI features)

## Quick Start
```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/speculum.git
cd speculum

# Configure
cp docker-compose.example.yml docker-compose.yml
# Edit docker-compose.yml with your paths and SECRET_KEY

# Start
docker-compose up -d --build

# (Optional) Download Ollama model for AI categorization
docker exec -it speculum-ollama ollama pull phi3:mini
```

Access the UI at `http://localhost:5050`

## Configuration

Environment variables in `docker-compose.yml`:

| Variable | Description | Default |
|----------|-------------|---------|
| `SECRET_KEY` | Flask secret key | (required) |
| `MIRRORS_PATH` | Path for archived content | `/mirrors` |
| `OLLAMA_URL` | Ollama API endpoint | `http://ollama:11434` |

## Volume Mounts

- `./data:/app/instance` — SQLite database
- `/path/to/mirrors:/mirrors` — Archived websites and videos
- `./ollama_data:/root/.ollama` — Ollama models (optional)

## Limitations

- Sites with anti-bot protection may fail or be incomplete
- Single Page Applications (SPAs) won't work properly
- Content behind login is not accessible
- JavaScript-generated content won't be captured

## License

MIT
