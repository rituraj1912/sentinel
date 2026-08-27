# Sentinel — Face Attendance, production container for Render.
# Uses a full build toolchain so dlib compiles reliably on Linux,
# regardless of whether a precompiled wheel is available.

FROM python:3.11-slim

# System build tools dlib needs to compile from source
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    libopenblas-dev \
    liblapack-dev \
    libx11-dev \
    libgtk-3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (better Docker layer caching —
# this step only re-runs when requirements.txt actually changes)
COPY requirements.txt .
ENV CMAKE_BUILD_PARALLEL_LEVEL=1
ENV MAKEFLAGS="-j1"
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir gunicorn
# Now copy the rest of the application
COPY . .
RUN mkdir -p /app/data/photos

# Render provides $PORT at runtime; gunicorn binds to it here
CMD gunicorn --bind 0.0.0.0:$PORT --workers 1 --timeout 120 app:app
