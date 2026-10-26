# ЛР3* — откат опубликованного релиза

В одном успешном GitHub Actions run проверен откат frontend к прежнему опубликованному образу. Критерий восстановления включает HTTP 200, чтение той же контрольной записи и неизменность backend, БД и тома. Просто снова открыть страницу для этого опыта недостаточно.

## Проверяемая схема

Один `workflow_dispatch` job на GitHub-hosted `ubuntu-24.04-arm` использует один Compose project и один PostgreSQL volume на протяжении всего опыта. Проверенная backend/frontend версия ЛР3 задаётся registry manifest digests из run [#39496839618](https://github.com/fadeeey/clouds-labs/actions/runs/39496839618), а не изменяемым тегом. Перед стартом job строит и сканирует намеренно неисправный frontend fixture из [Dockerfile.frontend-broken](../../docker/lab-03-star/Dockerfile.frontend-broken); fixture отвечает HTTP 503, не меняя backend или схему БД.

В одном job поднята и проверена рабочая версия, записана контрольная задача, запущен broken frontend по опубликованному manifest digest, зафиксированы HTTP 503 и `unhealthy`, затем одной командой восстановлен frontend image digest good release. После восстановления workflow проверил health endpoint и ту же запись в БД, а также сравнил идентификаторы backend/DB containers и имя/время создания тома. Cleanup ограничен временным Compose project самого runner.

Локальный предварительный тест fixture выполнен на ARM64: pinned Nginx image собрался, `nginx -t` завершился успешно, контейнер был `running` и отвечал `HTTP 503` на `/healthz`. Временный контейнер остановлен и удалён.

## Фактический запуск

Успешный запуск — [GitHub Actions #39499120264](https://github.com/fadeeey/clouds-labs/actions/runs/39499120264), commit workflow `f2ce8c7944be1c5ac162d2b3bf390e895153bda8`; job завершился за 2 мин 13 с, весь run — за 2 мин 20 с. Пошаговый [лог deploy/rollback](https://github.com/fadeeey/clouds-labs/actions/runs/39499120264/job/118891789228) содержит проверки refs и image IDs. Workflow закрепил рабочие образы из run ЛР3:

| Образ | Registry manifest digest | Trivy: Critical / High |
|---|---|---:|
| Backend | `ghcr.io/fadeeey/clouds-labs/backend@sha256:5a0d75d27bb81e37b909c21d69f25d3ee4fdaa17ec1313fbe8e68245d8f31814` | 0 / 48 |
| Рабочий frontend | `ghcr.io/fadeeey/clouds-labs/frontend@sha256:0e5da13191b2fcb1af6e49106b41fb02d57bc9b2366f99619529098c7b69c1bb` | 0 / 45 |
| Намеренно неисправный frontend | тег `lab03star-f2ce8c7944be1c5ac162d2b3bf390e895153bda8`; manifest `ghcr.io/fadeeey/clouds-labs/frontend@sha256:9f87c9637c97f05aa597cf585517dac4cb7a984c52f125fa51023d2885a134de` | 0 / 45 |

Сканирование всех трёх образов использовало Trivy DB с отметкой обновления `2026-10-20T19:12:26.430296739Z`. Идентификаторы рабочих backend и PostgreSQL, а также том `lab03star-39499120264-1_postgres_data` совпали до отказа и после отката. В БД создана контрольная запись `rollback-39499120264-1` с id `1`.

| Состояние | Наблюдение | Подтверждение |
|---|---|---|
| Рабочий релиз | HTTP 200; запущенный frontend совпал с закреплённым ref и image ID | [job log](https://github.com/fadeeey/clouds-labs/actions/runs/39499120264/job/118891789228) |
| Неисправный релиз | HTTP 503, `release_marker=controlled-broken`, frontend `unhealthy`; backend, БД и volume не менялись | [job log](https://github.com/fadeeey/clouds-labs/actions/runs/39499120264/job/118891789228) |
| Откат | Одна команда `docker compose --project-name "$DEPLOY_PROJECT" -f docker/lab-03/compose.deploy.yaml --env-file "$rollback_env" up -d --no-deps --no-build frontend`, где `rollback_env` содержит прежний digest; после неё HTTP 200 и восстановился тот же id/title записи | [job log](https://github.com/fadeeey/clouds-labs/actions/runs/39499120264/job/118891789228) |

Измеренный интервал от начала команды отката до восстановления health и контрольной записи: **0,552 с**, `2026-10-20T21:19:23Z` → `2026-10-20T21:19:24Z`. Это результат одного hosted run, а не гарантия времени восстановления в другой среде.

## Диагностика неудачных запусков

Первый hosted run [#39498264183](https://github.com/fadeeey/clouds-labs/actions/runs/39498264183) завершился до публикации и deploy: Python summary script не нашёл JSON Trivy по ошибочному host-пути `/scan/good-backend.json`. Вывод сканера находился в `$RUNNER_TEMP/scan`; workflow исправлен читать файл именно из этого смонтированного каталога.

Второй run [#39498491812](https://github.com/fadeeey/clouds-labs/actions/runs/39498491812) прошёл Critical scan и publish/pull broken image, поднял baseline и сохранил задачу, но запрос к frontend сразу после пересоздания получил `curl: (52) Empty reply from server`. Этот run не засчитан как rollback. Финальный run использует ограниченное ожидание health и отдельно подтверждает, что 503 пришёл именно от контролируемого broken image по его registry digest.

## Что считать восстановлением

Последовательность 200 → 503 → 200 выглядит законченной, если смотреть только на frontend. У пользователя другой вопрос: вернулась ли его запись. Обычный health с `SELECT 1` отвечает за соединение с БД, а не за содержимое таблицы. Новая пустая база прошла бы такую проверку вполне честно.

Поэтому до поломки в БД оставили контрольную задачу `rollback-39499120264-1`, id `1`. У неё самая пассивная роль в опыте: ничего не выполнять и оставаться на месте. Но именно она может испортить безупречный рассказ об откате — все контейнеры здоровы, а единственного участника, ради которого их запускали, забыли вернуть. После восстановления API прочитал тот же id и заголовок; совпали идентификаторы backend/БД и тома.

В ЛР0 неизменившаяся строка после перезапуска была малозаметным результатом. Здесь та же идея уже определяет, когда разрешено остановить секундомер. В данном run до health и чтения записи прошло 0,552 с. Проверка подтверждает сохранность контрольной задачи при откате только frontend; неизменность всей БД, восстановление после потери тома и обратимость миграций этим не доказаны.
