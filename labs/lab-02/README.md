# ЛР2 — Docker и Compose

Условие: [Общее/DevOps-лабы-2-курс.docx](../../../Общее/DevOps-лабы-2-курс.docx), раздел «Лабораторная работа № 2».

## Запуск

Из корня репозитория:

```sh
cp .env.example .env
# Задайте собственный локальный POSTGRES_PASSWORD в .env.
docker compose up --build -d
docker compose ps
```

Откройте <http://127.0.0.1:8080>. Nginx отдаёт интерфейс и проксирует `/api/` в backend; backend обращается к PostgreSQL по закрытой сети `database`. Для проверки backend и его соединения с БД:

```sh
curl -fsS http://127.0.0.1:5001/health
docker compose exec backend whoami
```

Для проверки, что frontend не видит БД напрямую:

```sh
docker compose exec frontend sh -lc 'wget -T 2 -O /dev/null http://db:5432'
```

Команда должна завершиться ошибкой разрешения имени `db`: frontend подключён только к сети `frontend`. Данные PostgreSQL хранятся в именованном томе `postgres_data`; `docker compose down` удаляет контейнеры и сети, сохраняя том. Не используйте `docker compose down -v`, если нужно сохранить данные.

## Контейнеры

| Сервис | Образ | Сети | Назначение |
|---|---|---|---|
| `frontend` | `clouds-lab-frontend:local` | `frontend` | Nginx, статика и прокси `/api/` |
| `backend` | `clouds-lab-backend:local` | `frontend`, `database` | Flask API и запросы к БД |
| `db` | `postgres:17.6-alpine` с digest в `compose.yaml` | `database` | PostgreSQL и том `postgres_data` |

## Проверка bad/good Dockerfile

`docker/lab-02/Dockerfile.bad` намеренно показывает несколько проблем: плавающий `python:3.14`, запуск от root, копирование всего контекста до установки зависимостей и отсутствие `.dockerignore`, multi-stage-сборки и `HEALTHCHECK`. В `Dockerfile.good` закреплён digest базового multi-arch образа, зависимости отделены от кода, runtime запускается от пользователя `app`, добавлены `.dockerignore` и `HEALTHCHECK`.

| Образ | Размер по `docker image inspect .Size` | Изменение одной строки HTML, тёплый кэш |
|---|---:|---:|
| bad | 421 400 431 B (401,9 MiB) | 7,16 с |
| good | 53 626 340 B (51,1 MiB) | 0,31 с |

Размер указан как точное значение поля `.Size` локального образа для `linux/arm64`; это не измерение скачивания. Для времени оба образа собирались одним `default` Buildx builder, `linux/arm64`, после добавления точки к заголовку в `app/frontend/index.html`. В bad-образе из-за порядка слоёв повторно выполнился `pip install`; в good-образе слой зависимостей остался в кэше. Это один локальный замер, а не универсальная оценка времени сборки.

## Результаты

- В Compose работают три отдельных сервиса; `backend` и `db` перешли в состояние `healthy`, frontend отдаёт интерфейс и API через Nginx.
- `docker compose exec backend whoami` вернул `app`.
- Попытка frontend обратиться к `db:5432` завершилась `wget: bad address 'db:5432'`.
- Добавленная через API запись осталась в PostgreSQL после `docker compose down` и повторного `up`; использован обычный `down`, без удаления тома.
- [Отчёт и доказательства](report.md), включая снимок реально работающего интерфейса.

Плохой Dockerfile тоже собрался с первого раза; разница стала заметна не по самому факту успеха, а по размеру образа и повторной сборке.
