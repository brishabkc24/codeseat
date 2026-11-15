# One image for the whole of CodeSeat: the built website and the server that
# serves it, the API and the class sockets from a single address.

# ---- build the website
FROM node:22-slim AS site
WORKDIR /site
# The install step copies the Python runtime into public/pyodide (scripts/copy-pyodide.mjs).
COPY frontend/package.json frontend/package-lock.json ./
COPY frontend/scripts ./scripts
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- the server
FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CODESEAT_STATIC=/srv/static
WORKDIR /srv
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY --from=site /site/dist ./static

# The host says which port to listen on. It sits behind the host's HTTPS proxy,
# so the proxy's headers are trusted: that is how the server knows the page is
# on https and marks the session cookie Secure.
EXPOSE 10000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000} --proxy-headers --forwarded-allow-ips='*'"]
