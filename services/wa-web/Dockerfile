FROM python:3.11-slim
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" httpx
WORKDIR /app
COPY app.py index.html ./
EXPOSE 80
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "80", "--proxy-headers", "--forwarded-allow-ips", "*"]
