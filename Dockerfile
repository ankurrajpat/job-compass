FROM python:3.10-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    HOME=/home/app HF_HOME=/home/app/.cache/huggingface \
    DENSE_SEARCH=1 REFRESH_HOURS=24 DATABASE_PATH=/tmp/compass/compass.db PORT=7860
RUN useradd --create-home --uid 1000 app
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=app:app . .
USER app
# Download the public embedding model during image construction, not first request.
RUN python -c "from fastembed import TextEmbedding; m=TextEmbedding(model_name='BAAI/bge-small-en-v1.5'); list(m.embed(['build check']))"
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:7860/api/health',timeout=4)"
CMD ["uvicorn", "compass.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "7860", "--workers", "1", "--proxy-headers"]
