# Optional: run in a container. Tesseract (OCR) with English + German included.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng tesseract-ocr-deu \
    && rm -rf /var/lib/apt/lists/* && useradd --create-home --uid 1000 renamer
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY run.py ./
USER renamer
ENV DATA_DIR=/data PORT=8443
VOLUME ["/data"]
EXPOSE 8443
CMD ["python", "run.py"]
