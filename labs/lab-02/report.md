# ЛР2 — результаты проверки

**Статус:** выполнено локально; преподавателю не отправлено.

**Цель:** собрать плохой и исправленный образы, запустить frontend, backend и PostgreSQL через Compose и проверить кэширование, разделение сетей и сохранение данных.

## Сборка и измерения

Оба образа собирались одним builder на `linux/arm64`:

```sh
docker --context=default buildx build --builder default --platform linux/arm64 --load -f docker/lab-02/Dockerfile.bad -t clouds-lab-backend:bad .
docker --context=default buildx build --builder default --platform linux/arm64 --load -f docker/lab-02/Dockerfile.good -t clouds-lab-backend:good .
```

Размеры сняты после сборки через `docker image inspect --format '{{.Size}}' <image>`:

| Вариант | Фактическое `.Size` | Пересчёт в MiB |
|---|---:|---:|
| bad | 421 400 431 B | 401,9 MiB |
| good | 53 626 340 B | 51,1 MiB |

Уменьшение по этому методу — около 87,3%. Значение `.Size` относится к локальному образу; объём скачиваемых слоёв отдельно не измерялся.

Для замера повторной сборки я добавил точку к `Учебные задачи` в заголовке `app/frontend/index.html`, замерил команды с ` /usr/bin/time -p`, а затем вернул исходную строку. Сборка bad заняла 7,16 с: после изменения контекста BuildKit повторно выполнил `pip install -r requirements.txt`. Сборка good заняла 0,31 с: слой с зависимостями остался в кэше, пересобрался только слой frontend-файлов. Это один замер на текущем Mac, он показывает поведение кэша, а не обещает такое же время на другой машине.

Плохой вариант честно собрался — именно поэтому сравнение кэша оказалось полезнее, чем просто смотреть на зелёный статус команды.

## Compose и проверки

В `compose.yaml` работают три сервиса. `frontend` находится в сети `frontend`; `backend` подключён к `frontend` и `database`; PostgreSQL подключён только к `database`. У БД есть именованный том `postgres_data`.

| Проверка | Наблюдение | Доказательство |
|---|---|---|
| Состав Compose | `db` и `backend` — `healthy`, `frontend` — `Up` | `docker compose ps` |
| Готовность БД через API | `{"database":"ok","status":"ok"}` | `curl -fsS http://127.0.0.1:5001/health` |
| Пользователь backend | `app` | `docker compose exec backend whoami` |
| Frontend не видит БД по сети | `wget: bad address 'db:5432'` | команда из README; frontend не подключён к `database` |
| Сохранение данных | запись с ID 6 осталась после удаления и повторного создания контейнеров | POST через `http://127.0.0.1:8080/api/tasks`, `docker compose down`, `docker compose up -d --no-build`, GET того же API |
| Интерфейс | Nginx отдаёт HTML, CSS и JS с кодом 200; статус «БАЗА НА СВЯЗИ» | [Снимок работающего интерфейса](evidence/app-compose.png) |
| Тесты API | 3/3 прошли с реальной PostgreSQL | `tests/test_api.py` запущен внутри backend-контейнера, где доступно имя БД `db` |

После первого снимка обнаружилось, что HTML загружался, но `/assets/styles.css` и `/assets/app.js` возвращали 404. В `docker/lab-02/nginx.conf` добавлено правило для `/assets/`; после пересборки frontend все три URL вернули 200, а в браузере отобразились стили и данные из PostgreSQL.

Запуск той же интеграционной проверки с хоста через `127.0.0.1:5433` не прошёл: порт указан в Compose, но в этой среде соединение с macOS получило `Connection refused`. Поэтому тесты выполнялись внутри backend-контейнера по внутренней сети; прямое подключение с хоста не заявляю как проверенное.

### Состояние после проверки

Обычный `docker compose down` и повторный запуск сохранили запись в `postgres_data`. На момент этой обычной ЛР2 (коммит `e4e356f`) в Compose ещё не было автоматического восстановления после падения, лимитов CPU/RAM и сценария OOM; эти проверки выполнены отдельно в [отчёте ЛР2*](../lab-02-star/report.md).
