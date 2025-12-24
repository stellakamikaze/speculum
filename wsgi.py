#!/usr/bin/env python3
"""
Entrypoint script that starts the scheduler before gunicorn
"""
import os
import sys

# Add app to path
sys.path.insert(0, '/app')

from app import create_app
from app.scheduler import init_scheduler

app = create_app()

# Initialize scheduler
with app.app_context():
    init_scheduler(app)

# This file is imported by gunicorn
