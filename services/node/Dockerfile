#   docker build -f node/Dockerfile -t tevi-node .
FROM python:3.11-slim
WORKDIR /app/node
COPY node/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
# Вместе с приложением копируем app/services/rate_limiter.
COPY node/ ./
COPY config/ /app/config/
ENV CONFIG_PATH=/app/config/cluster.json
CMD ["python", "-m", "app.main"]
