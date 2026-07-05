FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps: build tools for some wheels (fastembed/onnx pull manylinux wheels,
# but keep gcc around for safety), curl for healthchecks.
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc g++ curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY synapse_backend ./synapse_backend
COPY proto ./proto

EXPOSE 50051 8000

# Default command is overridden per-service in docker-compose.yml.
CMD ["python", "-m", "synapse_backend.grpc_service.server"]
