FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" httpx
WORKDIR /app
COPY app.py index.html app.js style.css ./
COPY voice.js pwa.js sw.js manifest.webmanifest offline.html icon-192.png icon-512.png apple-touch-icon.png ./
EXPOSE 80
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "80", "--proxy-headers", "--forwarded-allow-ips", "*"]
