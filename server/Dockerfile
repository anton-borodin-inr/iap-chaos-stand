# Build from the repository root:
#   docker build -f server/Dockerfile -t iap-chaos-stand/server:stand-v1 .
FROM python:3.12-slim

WORKDIR /app
COPY server/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY server/stand ./stand
COPY defects/registry.json ./defects/registry.json

ENV DATA_DIR=/data \
    STAND_DEFECT_REGISTRY=/app/defects/registry.json \
    PYTHONUNBUFFERED=1

EXPOSE 8080 8090
CMD ["python", "-m", "stand"]
