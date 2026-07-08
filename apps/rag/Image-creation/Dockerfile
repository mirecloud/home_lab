FROM python:3.11-slim

ENV HF_HOME=/models \
    SENTENCE_TRANSFORMERS_HOME=/models \
    TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pré-télécharge e5-base DANS l'image (pas de pull HF au runtime → démarrage rapide, pas de dépendance réseau)
ENV TRANSFORMERS_OFFLINE=0 HF_HUB_OFFLINE=0
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('intfloat/multilingual-e5-base')"
ENV TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1

COPY main.py .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]