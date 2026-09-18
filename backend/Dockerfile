# CyberDrishti AI — Backend Dockerfile
FROM python:3.11-slim

# System dependencies for PaddleOCR, WeasyPrint, Tesseract, Camelot
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-hin tesseract-ocr-eng \
    ghostscript libpango-1.0-0 libpangoft2-1.0-0 \
    libcairo2 libglib2.0-0 libffi-dev libssl-dev \
    poppler-utils libpoppler-dev pkg-config \
    gcc g++ git curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Create directories expected by the app
RUN mkdir -p uploads reports artifacts/chroma_db training_data synthetic_dataset models

RUN chmod +x start.sh

EXPOSE 8000

CMD ["./start.sh"]
