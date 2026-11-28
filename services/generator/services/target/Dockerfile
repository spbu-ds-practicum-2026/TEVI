FROM python:3.13-slim

WORKDIR /app
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY app.py .

EXPOSE 8080
HEALTHCHECK --interval=5s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "from http.client import HTTPConnection; conn = HTTPConnection('127.0.0.1', 8080, timeout=2); conn.request('GET', '/health'); raise SystemExit(conn.getresponse().status != 200)"]

CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
