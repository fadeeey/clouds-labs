# Ресурсный опыт 28 октября 2026 года

Полный запуск `lab02star-20261028-bec2ca`, 16:19:53–16:24:36 UTC. Восемь клиентов читали весь `GET /api/tasks` из настоящего backend; в отдельной БД находились 4 000 фиктивных задач и одна контрольная запись. [Разбор результатов](../../report.md).

- [summary.json](summary.json) — все фазы, контрольная запись, идентификаторы БД/тома, проверка cleanup и итоговые gates.
- [docker-stats.csv](docker-stats.csv) — отсчёты CPU/RAM всех сервисов. Нули после остановки OOM-контейнера не являются его живым пиком.
- [commands.txt](commands.txt) — неизменённое содержимое исходного `commands.log`, сохранённое с расширением, которое не исключается `.gitignore`.
- [baseline](baseline-15s.json), [CPU 0,10](cpu-010-30s.json), [CPU 0,50](cpu-050-30s.json), [OOM 64 MiB](oom-064m-30s.json), [рабочие 128 MiB](working-128m-60s.json) — результаты фаз. Ошибки OOM-фазы сохранены, успешным проходом она не считается.
- [До OOM](oom-before-load-backend-inspect.json) и [после OOM](oom-after-load-backend-inspect.json) — состояние backend и реальные ограничения Docker.
- [Рабочий backend после нагрузки](working-128m-60s-after-load-backend-inspect.json), [созданная контрольная запись](control-task-created.json), [основные контейнеры до](main-containers-before.json) и [после](main-containers-after.json).
- [Версии Docker](docker-versions.txt) и [локальные image IDs](image-ids.txt). Образы для этого опыта собирались локально и не публиковались в registry.
- [runner.py](runner.py) и [experiment.compose.yaml](experiment.compose.yaml) — точные снимки исходников, использованных при запуске. Для повторения следует запускать основной [scripts/lab-02-star-experiment.py](../../../../scripts/lab-02-star-experiment.py) из корня репозитория; копия runner в этом каталоге служит свидетельством версии.
