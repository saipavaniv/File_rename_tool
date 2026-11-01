# Hop in a container (used for cloud hosting, e.g. Render). Tesseract OCR (English + German) included.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng tesseract-ocr-deu \
    && rm -rf /var/lib/apt/lists/* && useradd --create-home --uid 1000 renamer \
    && mkdir -p /data && chown renamer /data
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY run.py ./
USER renamer
ENV DATA_DIR=/data PORT=8000 HOST=0.0.0.0 ANALYSIS_WORKERS=1 WORKER_MAX_MEMORY_MB=400 PYTHONUNBUFFERED=1
VOLUME ["/data"]
EXPOSE 8000
CMD ["python", "run.py"]
