FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY loaner_platform ./loaner_platform

# Hosts like Render/Railway inject PORT; default to 8000 for docker run.
ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT} --workers 2 --timeout 120 loaner_platform.webapp:app"]
