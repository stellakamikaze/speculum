# CLAUDE.md - Speculum

Web archiving system per salvare e organizzare siti web.

## Stack

- **Backend**: Flask + SQLite
- **Crawler**: wget, yt-dlp, singlefile
- **AI**: Ollama (metadata generation)
- **Port**: 5050

## Comandi

```bash
docker compose up -d --build
docker compose logs -f speculum
```

## Struttura

- `app/__init__.py` - Flask routes
- `app/crawler.py` - Crawling engine
- `app/ai_metadata.py` - Ollama integration

## Sicurezza

- CSRF protection attiva
- Rate limiting su login e mirror requests
- Path traversal protection nel file serving
- Mai esporre Ollama pubblicamente

## Knowledge Loop

Quando scopri pattern ricorrenti o fix importanti, aggiorna questo file o segnala a `/log-success`.
