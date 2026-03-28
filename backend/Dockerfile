# --------------------------------------------------------------------------
# TTS Web Backend — Docker image
# --------------------------------------------------------------------------
# Base:   Python 3.12 slim (Debian Bookworm)
# Extras: ffmpeg (required by pydub for MP3 merge)
# --------------------------------------------------------------------------

FROM python:3.12-slim-bookworm

# Install ffmpeg (system dependency for pydub)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install Python dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Expose the application port
EXPOSE 8000

# Run the FastAPI server with uvicorn
# --host 0.0.0.0 : bind to all interfaces (required for Docker)
# --reload       : auto-reload on code changes (works with volume mounts)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
