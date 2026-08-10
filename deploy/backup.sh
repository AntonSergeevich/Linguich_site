#!/usr/bin/env bash
# Ночная копия базы. Вызывается из cron, лежит в /srv/linguich/backups/.
#
# Тело в фигурной группе: выкатка может обновить этот файл ровно тогда,
# когда его выполняет cron, и bash дочитал бы новый файл со старого
# смещения. Группа заставляет разобрать файл целиком до первой команды.
{
set -euo pipefail

APP_DIR="/srv/linguich"
cd "$APP_DIR"
mkdir -p backups

# Пароль читаем из .env: в командной строке он был бы виден всем через ps.
# Именно построчным разбором, а не `. .env` — значения в файле не
# экранированы под шелл, и SECRET_KEY со скобками рушил весь скрипт.
source "$APP_DIR/deploy/env_value.sh"
DB_NAME=$(env_value POSTGRES_DB "$APP_DIR/.env")
DB_USER=$(env_value POSTGRES_USER "$APP_DIR/.env")
DB_HOST=$(env_value POSTGRES_HOST "$APP_DIR/.env")

STAMP=$(date +%Y%m%d)
PGPASSWORD="$(env_value POSTGRES_PASSWORD "$APP_DIR/.env")" pg_dump \
    -h "${DB_HOST:-localhost}" \
    -U "${DB_USER:-linguich}" \
    "${DB_NAME:-linguich}" \
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
}
