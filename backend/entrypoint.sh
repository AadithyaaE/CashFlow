#!/bin/sh
set -e

# `docker run --env-file` (unlike python-dotenv, which the app itself uses
# for non-Docker runs) does not strip surrounding quotes from values. If the
# .env file was authored with quoted values (e.g. JWT_SECRET_KEY="abc123"),
# those literal quote characters would otherwise leak into the running
# process's environment and silently corrupt values the app expects to be
# unquoted. Strip one matching pair of leading/trailing quotes per variable,
# if present, before anything else starts.
strip_quotes() {
    var_name="$1"
    eval "val=\"\${$var_name-}\""
    case "$val" in
        \"*\") val="${val#\"}"; val="${val%\"}" ;;
        \'*\') val="${val#\'}"; val="${val%\'}" ;;
    esac
    eval "export $var_name=\"\$val\""
}

for v in DATABASE_URL GOOGLE_API_KEY JWT_SECRET_KEY CORS_ORIGINS FRONTEND_URL \
         AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_REGION AWS_S3_BUCKET; do
    strip_quotes "$v"
done

echo "Applying Alembic migrations..."
alembic upgrade head

echo "Starting FastAPI (uvicorn) on port ${PORT:-8000}..."
exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"
