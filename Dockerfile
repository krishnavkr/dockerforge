# My Dockerfile for DockerForge
# I chose a lightweight python:3.11-slim base to ensure low container footprints
FROM python:3.11-slim

# Set active environment options
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set workspace folder
WORKDIR /app

# I install git and docker CLI so my agent can clone repos and talk to the docker socket
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    && curl -fsSL https://get.docker.com/ | sh \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency configs
COPY requirements.txt .

# Install dependencies inside container environment
RUN pip install --no-cache-dir -r requirements.txt

# Copy all application packages
COPY app/ ./app/

# Expose port 8000 for serving FastAPI developer console
EXPOSE 8000

# Start my application via uvicorn server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
