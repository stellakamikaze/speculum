FROM python:3.11-slim

# Install wget, yt-dlp, ffmpeg, Node.js and browser dependencies
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    ca-certificates \
    ffmpeg \
    gnupg \
    # Browser dependencies for SingleFile
    chromium \
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

# Install Node.js for SingleFile CLI
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install SingleFile CLI globally
RUN npm install -g single-file-cli

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
