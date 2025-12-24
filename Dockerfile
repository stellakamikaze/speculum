FROM python:3.11-slim

# Install wget, yt-dlp, ffmpeg and other dependencies
RUN apt-get update && apt-get install -y \
    wget \
    ca-certificates \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install yt-dlp
RUN pip install --no-cache-dir yt-dlp

# Set working directory
WORKDIR /app

# Copy requirements first (for caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create directories
RUN mkdir -p /mirrors /app/instance

# Environment variables
ENV FLASK_APP=app
ENV PYTHONUNBUFFERED=1
ENV MIRRORS_PATH=/mirrors
ENV DATABASE_URL=sqlite:////app/instance/speculum.db

# Expose port
EXPOSE 5000

# Run with gunicorn using wsgi entrypoint
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "4", "--timeout", "120", "--preload", "wsgi:app"]
