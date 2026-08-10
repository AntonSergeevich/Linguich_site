#!/usr/bin/env bash
# Чтение одной переменной из .env — без подключения файла шеллом.
#
# `set -a; . .env` выглядит удобно, но ломается на первом же значении со
# спецсимволом. Django генерирует SECRET_KEY из алфавита, куда входят
# скобки, а DEFAULT_FROM_EMAIL выглядит как «Лингвич <mail@yandex.ru>» —
# для bash это подстановка команды и перенаправление ввода. Скрипт падал
# с «syntax error near unexpected token», выкатка обрывалась до миграций,
# и об этом узнавали только по сломанному сайту.
#
# Значения здесь берутся буквально, ровно как их читает config/settings.py.
#
#   source deploy/env_value.sh
#   PASSWORD=$(env_value POSTGRES_PASSWORD /srv/linguich/.env)

env_value() {
    local name="$1"
    local file="${2:-/srv/linguich/.env}"
    [ -f "$file" ] || return 0
    # Первое вхождение, всё после первого «=», без обрамляющих пробелов.
    sed -n "s/^[[:space:]]*${name}[[:space:]]*=//p" "$file" \
        | head -n1 \
        | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
}
