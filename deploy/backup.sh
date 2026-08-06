#!/usr/bin/env bash
# Ночная копия базы. Вызывается из cron, лежит в /srv/linguich/backups/.
set -euo pipefail

APP_DIR="/srv/linguich"
cd "$APP_DIR"
mkdir -p backups

# Пароль читаем из .env: в командной строке он был бы виден всем через ps.
set -a; . "$APP_DIR/.env"; set +a

STAMP=$(date +%Y%m%d)
PGPASSWORD="$POSTGRES_PASSWORD" pg_dump \
    -h "${POSTGRES_HOST:-localhost}" \
    -U "$POSTGRES_USER" \
    "$POSTGRES_DB" \
    | gzip > "backups/nightly-$STAMP.sql.gz"

# Пустой дамп означает, что что-то пошло не так, — такой файл лучше убрать,
# чтобы он не вытеснил рабочую копию при ротации.
if [ ! -s "backups/nightly-$STAMP.sql.gz" ]; then
    rm -f "backups/nightly-$STAMP.sql.gz"
    echo "$(date -Is) БЭКАП НЕ СОЗДАН: дамп пустой" >&2
    exit 1
fi

ls -1t backups/nightly-*.sql.gz | tail -n +31 | xargs -r rm --
echo "$(date -Is) бэкап готов: nightly-$STAMP.sql.gz ($(du -h backups/nightly-$STAMP.sql.gz | cut -f1))"
