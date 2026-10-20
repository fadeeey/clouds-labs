# ЛР1 — Nginx, HTTPS и два backend

В этой работе Nginx обслуживает статический интерфейс и принимает API-запросы, распределяя их между двумя экземплярами Flask. В Compose оба backend подключены к общей сети frontend/database; PostgreSQL остаётся отдельным сервисом из ЛР0/ЛР2.

## Локальный запуск

В корне репозитория сначала создайте локальные ключи и пароль Basic Auth, затем поднимите Compose:

```sh
./scripts/lab-01-setup-local.sh
# При первом запуске пароль student создаётся случайно и хранится только в .local/nginx/admin-password.txt.
docker compose up --build -d
docker compose ps
```

Откройте <http://localhost:8080>: Nginx перенаправит запрос на HTTPS-порт 8443. Сертификат самоподписанный; для браузерной проверки нужно вручную разрешить локальное предупреждение. Проверки в `scripts/lab-01-check.sh` используют `curl -k` и `--resolve`, не меняя DNS-настройки macOS. Пароль для `/admin` — локальный файл `.local/nginx/admin-password.txt`; его содержимое не включено в репозиторий и evidence.

Остановить стек, сохранив базу:

```sh
docker compose down
```

Не добавляйте `-v`, если хотите оставить данные в именованном томе PostgreSQL.

## Что проверяется

```sh
./scripts/lab-01-check.sh
```

Скрипт проверяет редирект HTTP→HTTPS, появление обоих значений `X-Backend-ID`, `/docs/` с `alias`, выдачу разного содержимого по `app.local` и `companion.local`, собственные 404-страницы, Basic Auth, ответ 429 на короткий burst запросов и доступность API при остановке `backend2`. После теста второй backend запускается обратно.

Точки настройки: [Nginx](../../docker/lab-01/nginx.conf), [Compose](../../compose.yaml), [идентификатор backend](../../app/backend/server.py). Секреты TLS/Basic Auth создаются скриптом в `.local/nginx/`, исключённом из Git.
