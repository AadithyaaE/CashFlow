# CashPilot backend — FastAPI + Alembic (Neon Postgres is external, never containerized).

FROM python:3.11-slim

WORKDIR /app

# Dependency layer first so it's cached across builds unless requirements.txt changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application source (see .dockerignore for what's excluded — no venv, no .env, no secrets).
COPY . .

RUN chmod +x entrypoint.sh

ENV PORT=8000
EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
