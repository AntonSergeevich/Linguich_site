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
if [ -f "$APP_DIR/db.sqlite3" ]; then
    # .backup корректно снимает копию даже при активных подключениях.
    sqlite3 "$APP_DIR/db.sqlite3" ".backup '$APP_DIR/backups/db-$STAMP.sqlite3'"
else
    "$VENV/bin/python" manage.py dumpdata --natural-foreign --natural-primary \
        -e contenttypes -e auth.Permission -e sessions \
        > "$APP_DIR/backups/dump-$STAMP.json"
fi
# Держим последние 30 копий.
ls -1t "$APP_DIR/backups"/* 2>/dev/null | tail -n +31 | xargs -r rm --

echo "==> Миграции"
"$VENV/bin/python" manage.py migrate --noinput

echo "==> Статика"
"$VENV/bin/python" manage.py collectstatic --noinput

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
