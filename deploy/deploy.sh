#!/usr/bin/env bash
# Выкатка новой версии. Запускать на сервере от пользователя linguich:
#   cd /srv/linguich && ./deploy/deploy.sh
set -euo pipefail

APP_DIR="/srv/linguich"
VENV="$APP_DIR/.venv"
SERVICE="linguich"

# От root выкатка ломает установку тихо и надолго: git ругается на чужого
# владельца репозитория, а collectstatic и __pycache__ создают файлы,
# принадлежащие root, — служба потом не может их перезаписать.
if [ "$(id -u)" -eq 0 ]; then
    cat >&2 <<'MSG'
!! Выкатку запускают от пользователя linguich, а не от root.

   sudo -u linguich -H bash -c 'cd /srv/linguich && ./deploy/deploy.sh'

   Если что-то уже запускалось от root, сначала верните владение:
   chown -R linguich:linguich /srv/linguich
MSG
    exit 1
fi

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
# Читаем через env_value, а не через `. .env`: значения там не экранированы
# под шелл, и SECRET_KEY со скобками обрывал выкатку до миграций.
source "$APP_DIR/deploy/env_value.sh"
DB_NAME=$(env_value POSTGRES_DB "$APP_DIR/.env")
DB_USER=$(env_value POSTGRES_USER "$APP_DIR/.env")
DB_HOST=$(env_value POSTGRES_HOST "$APP_DIR/.env")
PGPASSWORD="$(env_value POSTGRES_PASSWORD "$APP_DIR/.env")" pg_dump \
    -h "${DB_HOST:-localhost}" -U "${DB_USER:-linguich}" "${DB_NAME:-linguich}" \
    | gzip > "$APP_DIR/backups/db-$STAMP.sql.gz"

if [ ! -s "$APP_DIR/backups/db-$STAMP.sql.gz" ]; then
    echo "!! Резервная копия пустая — выкатку останавливаю, чтобы было куда откатиться." >&2
    rm -f "$APP_DIR/backups/db-$STAMP.sql.gz"
    exit 1
fi
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
