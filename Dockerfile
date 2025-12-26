FROM python:3.11-slim

# Install wget, yt-dlp, ffmpeg and Playwright dependencies
RUN apt-get update && apt-get install -y \
    wget \
    ca-certificates \
    ffmpeg \
    # Playwright dependencies
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Install yt-dlp
RUN pip install --no-cache-dir yt-dlp

# Set working directory
WORKDIR /app

# Copy requirements first (for caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers (chromium only to save space)
RUN playwright install chromium

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
