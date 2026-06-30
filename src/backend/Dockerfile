FROM python:3.11-slim

WORKDIR /app

COPY src/backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY src/backend/app /app/src/backend/app
COPY src/backend/services /app/src/backend/services

ENV PYTHONPATH=/app/src/backend/services:/app/src/backend/app
EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "/app/src/backend/app"]
