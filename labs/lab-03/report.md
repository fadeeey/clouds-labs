# ЛР3 — CI/CD, сканирование и deployment

**Статус:** hosted pipeline и разовый deployment проверены на GitHub Actions run #39495048433. Преподавателю не отправлено.

## Схема pipeline

Workflow `.github/workflows/lab-03.yml` выполняет lint и интеграционные тесты с PostgreSQL, собирает backend и frontend, сканирует оба образа закреплённым Trivy и публикует их в приватный GHCR только после прохождения Critical gate. Следующая job отдельно выполняет `docker compose pull` по registry digest, запускает изолированный стенд и проверяет готовность API и запись задачи.

Workflow использует GitHub-hosted `ubuntu-24.04-arm`, чтобы собирать и запускать ARM64 образы. Deploy job получает отдельную одноразовую VM; она не хранит состояние предыдущих запусков. Compose-проект, порт и volume имеют собственные имена; после проверки job удаляет только созданный им стенд. Основные локальные сервисы и их PostgreSQL volume не затрагиваются.

В `.github/workflows/lab-03-bad.yml` оставлен демонстрационный плохой pipeline: плавающая ссылка на checkout action, Dockerfile без зафиксированной версии и без тестов, cache и security gate. Он не публикует образы и не запускает deployment.

## Локальная проверка до GitHub run

| Проверка | Наблюдение | Доказательство |
|---|---|---|
| Ruff | `All checks passed!` | `ruff check app tests scripts/lab-03` |
| Интеграционные тесты | 3/3 прошли с настоящей PostgreSQL | `python -m unittest discover -s tests -v` внутри контейнера в Compose-сети `cloud-labs_database` |
| Изолированный deployment Compose | `up --no-build` запустил db/backend/frontend; `/healthz` вернул 200; POST→GET нашёл созданную запись | временный проект `l3-smoke`, отдельный volume удалён после проверки |
| Workflow/YAML | `actionlint` завершился с кодом 0; Compose-файл прошёл `docker compose config -q` | локальные команды до публикации ветки |

Запуск тестов с macOS-хоста к БД курса не состоялся: контейнер доступен только внутри Docker-сети, host-порт не опубликован. Тесты не выдаются за проверку host-подключения; корректный путь — запуск тестового процесса в той же контейнерной сети.

## Локальное сравнение уязвимостей

Trivy 0.74.0 использовал базу, обновлённую `2026-10-20T19:12:26Z`. Оба образа собраны под `linux/arm64`; digest ниже — локальный image config ID, а не registry manifest digest. Финальная CI-таблица будет дополнена registry digest для каждого опубликованного образа.

| Снимок backend | Базовый образ | Локальный image config ID | Critical | High |
|---|---|---|---:|---:|
| До обновления, Debian 12 | `python:3.14-slim-bookworm` | `sha256:d76b54540fbd7d7ffa0c0ec0c48c6ae428cab83b4887d8b97238f9cd31926f92` | 2 | 65 |
| После перехода, Debian 13 | `python:3.14-slim-trixie` | `sha256:dd15057d4af0da1c4a43778dbd353c4e48e41e13865a52cd911a15598eecf38f` | 0 | 48 |

Два исходных Critical finding в Bookworm были без доступной `FixedVersion`: `libsqlite3-0 3.40.1-2+deb12u2` (`CVE-2025-7458`) и `zlib1g 1:1.2.13.dfsg-1` (`CVE-2023-45853`). Для одного обоснованного исправления заменён закреплённый multi-arch base digest на официальный `python:3.14-slim-trixie`; повторный локальный scan показал 0 Critical. Это результат конкретного scan, не гарантия отсутствия уязвимостей в будущей базе.

На Trixie остаются 44 Debian High и 4 Python High. В Python target Trivy перечислил `msgpack 1.1.2 → 1.2.1` (`GHSA-6v7p-g79w-8964`), `setuptools 70.3.0 → 78.1.1` (`CVE-2025-47273`) и `urllib3 2.7.0 → 2.8.0` (`CVE-2026-97687`, `CVE-2026-97689`). JSON сообщает `Class=lang-pkgs`, `Type=python-pkg`, `PkgPath=null`, `Layer.DiffID=sha256:54d103c61570dcb43cbb7f20991a504ec35d806ec1cbb544d0ba472e888a5775`; он не даёт пути к SBOM или связи с конкретным установленным файлом. `pip list` внутри runtime image не показывает эти три дистрибутива, но это наблюдение само по себе не доказывает отсутствие вложенного компонента. Поэтому 4 finding оставлены неустранёнными, без игнорирования и без заявления, что весь образ чистый.

Trivy предупреждает, что сторонние SBOM могут давать неточные результаты; это контекст для дальнейшей проверки, а не основание убрать находки из отчёта. [Документация Trivy о сканировании контейнеров](https://trivy.dev/docs/v0.74/guide/target/container_image/).

## Результат hosted run

[Первый run #39494604671](https://github.com/fadeeey/clouds-labs/actions/runs/39494604671) завершил проверки, сборку, scan и публикацию, но deploy завершился с `curl: (56) Recv failure: Connection reset by peer` сразу после старта frontend-контейнера. В workflow добавил ограниченные повторные попытки для временных curl-ошибок и вывод логов frontend при окончательном сбое. [Повторный run #39495048433](https://github.com/fadeeey/clouds-labs/actions/runs/39495048433) завершился успешно за 2 мин 15 с: все три job зелёные, оба образа прошли Critical gate, deploy job отдельно скачал опубликованные манифесты по digest, проверил `/healthz` и выполнил API POST→GET для контрольной записи. Это доказывает проверку временного hosted стенда; публичный постоянно доступный сервис не создавался.

| Опубликованный образ, run #39495048433 | Registry manifest digest | Локальный image config ID | Critical / High |
|---|---|---|---:|
| Backend | `sha256:67ee461dbda94492683273dc3a7f0ba19e123a7cfa8b1e45fb8bdde378bd9ec6` | `sha256:db0498c8631a7530338f2e000b6da0a22286a428ac3270bc64c831b6caf9ef33` | 0 / 48 |
| Frontend | `sha256:f24db0f4305fe4ed02b44e7e6e9fbf5a5364bf8bcdd1e623dfa478447e9702c9` | `sha256:deae404a871cf747687eed8490aeba13e8c35e00b77ecd76fb4ea6c36db19bd7` | 0 / 45 |

Оба образа просканированы одним Trivy DB snapshot (`2026-10-20T19:12:26Z`). High findings остаются видимыми в summary; Critical gate настроен на обе публикуемые images и не ослаблен. GHCR publish log — источник manifest digest; локальный `docker image inspect` ID относится к конфигурации образа и не подменяет registry digest.
