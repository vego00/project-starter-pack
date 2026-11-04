FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv

ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy
WORKDIR /app

COPY pyproject.toml uv.lock .python-version ./
COPY backend/pyproject.toml backend/
RUN uv sync --locked --no-dev --package starter-pack-backend

COPY backend/app backend/app

RUN useradd --create-home app
USER app
EXPOSE 8000
CMD [".venv/bin/uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000"]
