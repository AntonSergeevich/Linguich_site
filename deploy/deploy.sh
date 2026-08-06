#!/usr/bin/env bash
# Выкатка новой версии. Запускать на сервере от пользователя linguich:
#   cd /srv/linguich && ./deploy/deploy.sh
set -euo pipefail

APP_DIR="/srv/linguich"
VENV="$APP_DIR/.venv"
SERVICE="linguich"

cd "$APP_DIR"

echo "==> Забираем изменения"
git pull --ff-only origin master

echo "==> Зависимости"
"$VENV/bin/pip" install -q -r requirements.txt

echo "==> Проверки перед миграцией"
# --deploy ловит забытый DEBUG=True, слабый SECRET_KEY и пустой ALLOWED_HOSTS.
"$VENV/bin/python" manage.py check --deploy --fail-level WARNING

echo "==> Резервная копия базы"
mkdir -p "$APP_DIR/backups"
STAMP=$(date +%Y%m%d-%H%M%S)
# Пароль берём из .env, чтобы не светить его в списке процессов.
set -a; . "$APP_DIR/.env"; set +a
PGPASSWORD="$POSTGRES_PASSWORD" pg_dump \
    -h "${POSTGRES_HOST:-localhost}" -U "$POSTGRES_USER" "$POSTGRES_DB" \
    | gzip > "$APP_DIR/backups/db-$STAMP.sql.gz"
# Держим последние 30 копий.
ls -1t "$APP_DIR/backups"/*.sql.gz 2>/dev/null | tail -n +31 | xargs -r rm --

echo "==> Миграции"
"$VENV/bin/python" manage.py migrate --noinput

echo "==> Статика"
"$VENV/bin/python" manage.py collectstatic --noinput
# collectstatic наследует umask, и свежие файлы бывают закрыты от nginx —
# он ходит под www-data и отдаёт 403 вместо стилей. Заглавная X добавляет
# +x только каталогам, файлы исполняемыми не становятся.
chmod -R a+rX "$APP_DIR/staticfiles"

echo "==> Перезапуск"
sudo systemctl restart "$SERVICE"

# Ждём, пока сокет ответит, и только потом рапортуем об успехе.
for i in $(seq 1 15); do
    if curl -fsS -o /dev/null https://linguich.ru/; then
        echo "==> Готово: сайт отвечает"
        exit 0
    fi
    sleep 2
done

echo "!! Сайт не ответил за 30 секунд. Смотрите: journalctl -u $SERVICE -n 50" >&2
exit 1
