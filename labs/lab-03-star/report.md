# ЛР3* — откат опубликованного релиза

**Статус:** выполняется. Workflow подготовлен, hosted эксперимент ещё не запускался; результат не засчитан.

## Проверяемая схема

Один `workflow_dispatch` job на GitHub-hosted `ubuntu-24.04-arm` использует один Compose project и один PostgreSQL volume на протяжении всего опыта. Проверенная backend/frontend версия ЛР3 задаётся registry manifest digests из run [#39496839618](https://github.com/fadeeey/clouds-labs/actions/runs/39496839618), а не изменяемым тегом. Перед стартом job строит и сканирует намеренно неисправный frontend fixture из [Dockerfile.frontend-broken](../../docker/lab-03-star/Dockerfile.frontend-broken); fixture отвечает HTTP 503, не меняя backend или схему БД.

В одном job планируется: поднять и проверить good release, записать контрольную задачу, запустить broken frontend по его опубликованному manifest digest, зафиксировать HTTP 503 и unhealthy healthcheck, затем одной командой восстановить frontend image digest good release. После восстановления workflow проверит health endpoint и ту же запись в БД, а также сравнит идентификаторы backend/DB containers и имя/время создания тома. Cleanup ограничен временным Compose project самого runner.

Локальный предварительный тест fixture выполнен на ARM64: pinned Nginx image собрался, `nginx -t` завершился успешно, контейнер был `running` и отвечал `HTTP 503` на `/healthz`. Временный контейнер остановлен и удалён.

## Пока не проверено

Пока нет фактического workflow run, поэтому digest broken release, его Trivy counts, HTTP/health наблюдения, сохранение контрольной записи и измеренное время восстановления остаются непроверенными.
