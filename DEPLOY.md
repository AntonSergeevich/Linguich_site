# Деплой на BEGET VPS

Домен `linguich.ru`, Ubuntu 22.04/24.04, nginx + gunicorn + systemd.
Всё, что нужно, лежит в `deploy/`. Команды выполняются по SSH на сервере.

---

## 0. Что понадобится под рукой

- IP-адрес VPS и root-доступ (BEGET присылает при создании сервера).
- Доступ к DNS домена в панели BEGET.
- Токен Telegram-бота (см. раздел «Telegram» ниже).
- Пароль от почтового ящика `noreply@linguich.ru` для SMTP.

---

## 1. DNS

В панели BEGET → **Домены → linguich.ru → DNS**:

| Тип | Имя | Значение |
|---|---|---|
| A | `@` | IP вашего VPS |
| A | `www` | IP вашего VPS |

Изменения расходятся 15–60 минут. Проверить: `dig +short linguich.ru`.
Пока DNS не обновился, сертификат получить не получится — это нормально.

---

## 2. Базовая настройка сервера

```bash
ssh root@ВАШ_IP

apt update && apt upgrade -y
apt install -y python3 python3-venv python3-pip python3-dev git nginx curl \
               build-essential libpq-dev certbot python3-certbot-nginx ufw

# Отдельный пользователь: приложение не должно работать от root.
adduser --system --group --home /srv/linguich --shell /bin/bash linguich
usermod -aG www-data linguich

# Файрвол
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable

# Часовой пояс сервера — чтобы логи совпадали с расписанием школы
timedatectl set-timezone Asia/Krasnoyarsk
```

---

## 3. Код и окружение

```bash
mkdir -p /srv/linguich && chown linguich:linguich /srv/linguich
sudo -u linguich -H bash

cd /srv/linguich
git clone https://github.com/AntonSergeevich/Linguich_site.git .
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

mkdir -p logs backups media
exit   # обратно в root
```

---

## 4. Файл `.env`

```bash
sudo -u linguich cp /srv/linguich/.env.example /srv/linguich/.env
# Сгенерировать секретный ключ:
sudo -u linguich /srv/linguich/.venv/bin/python -c \
  "from django.core.management.utils import get_random_secret_key as k; print(k())"
sudo -u linguich nano /srv/linguich/.env
```

Обязательный минимум:

```ini
DJANGO_SECRET_KEY=<вставить сгенерированный>
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=linguich.ru,www.linguich.ru
DJANGO_CSRF_TRUSTED_ORIGINS=https://linguich.ru,https://www.linguich.ru
SITE_URL=https://linguich.ru

EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.yandex.ru
EMAIL_PORT=465
EMAIL_HOST_USER=linguich@yandex.ru
EMAIL_HOST_PASSWORD=<пароль приложения, не пароль от почты>
DEFAULT_FROM_EMAIL=Лингвич <linguich@yandex.ru>

TELEGRAM_BOT_TOKEN=<токен вашего бота>
TELEGRAM_BOT_USERNAME=<имя бота без @>
TELEGRAM_LINK_API_KEY=<придумать длинную случайную строку>
```

Права: файл содержит пароли, читать его должно только приложение.

```bash
chmod 600 /srv/linguich/.env
chown linguich:linguich /srv/linguich/.env
```

> **Порт решает всё.** 465 — SSL сразу, 587 — STARTTLS; настройки выводятся
> из порта автоматически, руками `EMAIL_USE_SSL`/`EMAIL_USE_TLS` задавать не
> нужно. Это же верно для BEGET (`smtp.beget.com`, порт 465).
>
> **Яндекс требует пароль приложения.** Обычный пароль от почты SMTP не
> примет: `id.yandex.ru` → Безопасность → Пароли приложений → Почта.
> И адрес в `DEFAULT_FROM_EMAIL` обязан совпадать с `EMAIL_HOST_USER`.

---

## 5. PostgreSQL

```bash
apt install -y postgresql postgresql-contrib

# Пароль придумайте длинный. Спецсимволы можно любые — экранировать
# ничего не нужно, он попадёт в .env как есть.
sudo -u postgres psql <<'SQL'
CREATE USER linguich WITH PASSWORD 'ВАШ_ПАРОЛЬ_БД';
CREATE DATABASE linguich OWNER linguich ENCODING 'UTF8'
    LC_COLLATE 'ru_RU.UTF-8' LC_CTYPE 'ru_RU.UTF-8' TEMPLATE template0;
-- Django создаёт и удаляет тестовую базу, для этого нужно право createdb.
ALTER USER linguich CREATEDB;
SQL
```

Если `CREATE DATABASE` ругается на локаль — сгенерируйте её и повторите:

```bash
locale-gen ru_RU.UTF-8 && update-locale
systemctl restart postgresql
```

Добавьте в `/srv/linguich/.env`:

```ini
POSTGRES_DB=linguich
POSTGRES_USER=linguich
POSTGRES_PASSWORD=ВАШ_ПАРОЛЬ_БД
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
```

Проверка подключения:

```bash
cd /srv/linguich
sudo -u linguich .venv/bin/python manage.py check --database default
```

## 5.1. Миграции и первичное наполнение

```bash
cd /srv/linguich
sudo -u linguich .venv/bin/python manage.py migrate
sudo -u linguich .venv/bin/python manage.py load_placement_questions
sudo -u linguich .venv/bin/python manage.py collectstatic --noinput

# nginx работает от www-data и должен попасть в каталог приложения.
# adduser в Ubuntu 24.04 создаёт домашний каталог с режимом 0750 —
# без этого статика отдаётся с 403, а сайт открывается без стилей.
chmod 711 /srv/linguich
chmod -R a+rX /srv/linguich/staticfiles /srv/linguich/media

# Аккаунт владелицы
sudo -u linguich .venv/bin/python manage.py createsuperuser
```

`seed_demo` на боевом сервере **запускать не нужно** — он создаст выдуманных
учеников и платежи. Реальные данные заводятся через кабинет и админку.

## 6. gunicorn как служба

```bash
cp /srv/linguich/deploy/gunicorn.service /etc/systemd/system/linguich.service
systemctl daemon-reload
systemctl enable --now linguich
systemctl status linguich       # должно быть active (running)
```

Если не запустилось: `journalctl -u linguich -n 50 --no-pager`.

---

## 7. nginx и HTTPS

Сначала поднимаем только HTTP, иначе nginx не стартует — сертификата ещё нет.

```bash
cp /srv/linguich/deploy/nginx.conf /etc/nginx/sites-available/linguich
ln -sf /etc/nginx/sites-available/linguich /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
mkdir -p /var/www/certbot

# Временно закомментировать оба блока «listen 443», оставив только 80-й,
# и в нём заменить редирект на proxy_pass — либо просто:
certbot --nginx -d linguich.ru -d www.linguich.ru \
        --agree-tos -m linguich@ya.ru --redirect
```

`certbot --nginx` сам пропишет сертификаты и перезагрузит nginx. После этого
верните полный конфиг из `deploy/nginx.conf` (он уже рассчитан на пути
`/etc/letsencrypt/live/linguich.ru/`) и примените:

```bash
nginx -t && systemctl reload nginx
```

Автопродление certbot настраивает сам, проверить: `certbot renew --dry-run`.

---

## 8. Регулярные задачи

```bash
sudo -u linguich crontab /srv/linguich/deploy/crontab
sudo -u linguich crontab -l    # проверить
```

Без этого не будут уходить напоминания и не будут создаваться занятия групп.

Служба перезапускается из `deploy.sh` через `sudo`, поэтому разрешим это
без пароля — только для одной команды:

```bash
echo 'linguich ALL=(ALL) NOPASSWD: /bin/systemctl restart linguich' \
  > /etc/sudoers.d/linguich
chmod 440 /etc/sudoers.d/linguich
visudo -c        # проверка синтаксиса
```

---

## 9. Проверка

```bash
curl -I https://linguich.ru/                  # 200
curl -s https://linguich.ru/robots.txt        # Disallow: /cabinet/
curl -s https://linguich.ru/sitemap.xml | head
cd /srv/linguich && sudo -u linguich .venv/bin/python manage.py check --deploy
```

`check --deploy` не должен выдавать предупреждений. Дальше руками:

- главная открывается, логотип и шрифт на месте;
- заявка с формы приходит и появляется в CRM;
- вход в кабинет работает;
- тест уровня доходит до результата.

---

## 10. Обновления

Дальше выкатка — одна команда:

```bash
ssh linguich@ВАШ_IP
cd /srv/linguich && ./deploy/deploy.sh
```

Скрипт забирает изменения, ставит зависимости, прогоняет `check --deploy`,
делает резервную копию базы, применяет миграции, собирает статику,
перезапускает службу и ждёт ответа сайта. Если сайт не ответил за 30 секунд —
скрипт падает с ненулевым кодом и подсказывает, где смотреть логи.

Первый раз не забудьте: `chmod +x deploy/deploy.sh`.

---

## Резервные копии

`deploy/crontab` кладёт ночную копию базы в `/srv/linguich/backups/`
и хранит 30 последних. Это копия **на том же сервере** — она спасает от
неудачной миграции, но не от потери сервера. Раз в неделю стоит забирать
копию к себе:

```bash
# с вашего компьютера
scp linguich@ВАШ_IP:/srv/linguich/backups/nightly-*.sql.gz ./backups/
rsync -avz linguich@ВАШ_IP:/srv/linguich/media/ ./backups/media/
```

Восстановление из копии:

```bash
gunzip -c backups/nightly-20260806.sql.gz | sudo -u linguich psql linguich
```

Медиафайлы (аватары, домашние работы, материалы) в базе не лежат — их нужно
копировать отдельно.

---

## Обслуживание PostgreSQL

Ничего регулярного делать не нужно: автовакуум включён по умолчанию и для
базы такого размера справляется сам. Полезно знать две команды:

```bash
sudo -u postgres psql -c "\l+"                    # размер баз
sudo -u linguich psql linguich -c "\dt+"          # размер таблиц
```

Настройки по умолчанию рассчитаны на скромный сервер и вам подходят.
Трогать `postgresql.conf` при 2 ГБ памяти не нужно — значения из коробки
уже консервативны.

## Если что-то сломалось

| Симптом | Куда смотреть |
|---|---|
| 502 Bad Gateway | `journalctl -u linguich -n 50` — приложение не поднялось |
| 400 Bad Request | `DJANGO_ALLOWED_HOSTS` не содержит домен |
| CSRF verification failed | `DJANGO_CSRF_TRUSTED_ORIGINS` без `https://` |
| Статика без стилей | 403 в `linguich.error.log` → `chmod 711 /srv/linguich`; иначе `collectstatic` |
| Письма не уходят | пароль приложения, а не от почты; `From` = `EMAIL_HOST_USER`; `logs/cron.log` |
| Напоминания молчат | `sudo -u linguich crontab -l`, затем `logs/cron.log` |
| Не грузятся файлы домашек | права на `/srv/linguich/media/`, `client_max_body_size` |

Откат на предыдущую версию:

```bash
cd /srv/linguich
git log --oneline -5
git checkout <хеш предыдущего коммита>
sudo systemctl restart linguich
# базу — из backups/, если миграция была разрушительной
```
