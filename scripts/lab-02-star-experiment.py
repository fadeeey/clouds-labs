#!/usr/bin/env python3
"""Run the isolated 2026-10-28 Lab 2* resource experiment."""
from __future__ import annotations

import concurrent.futures
import csv
import datetime as dt
import http.client
import json
import secrets
import shlex
import statistics
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "labs/lab-02-star/experiment.compose.yaml"
EVIDENCE_ROOT = ROOT / "labs/lab-02-star/evidence"
SERVICES = ("db", "backend", "frontend")


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def parse_memory(value: str) -> float | None:
    value = value.strip()
    units = {"GiB": 1024, "MiB": 1, "KiB": 1 / 1024, "B": 1 / (1024 * 1024)}
    for unit, multiplier in units.items():
        if value.endswith(unit):
            try:
                return float(value[: -len(unit)]) * multiplier
            except ValueError:
                return None
    return None


class Experiment:
    def __init__(self, evidence: Path, env_file: Path, project: str, tag: str, password: str):
        self.evidence = evidence
        self.env_file = env_file
        self.project = project
        self.tag = tag
        self.password = password
        self.log_path = evidence / "commands.log"
        self.stats_path = evidence / "docker-stats.csv"
        self.summary: dict[str, object] = {
            "started_at_utc": now_utc(),
            "project": project,
            "image_tag": tag,
            "phases": [],
        }
        self.port: int | None = None
        with self.stats_path.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(
                ["timestamp_utc", "phase", "service", "container", "cpu_percent", "memory_usage", "memory_limit", "pids"]
            )

    def log(self, line: str) -> None:
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(line.rstrip() + "\n")

    def command(self, args: list[str], *, check: bool = True, record: bool = True, input_text: str | None = None) -> str:
        if record:
            self.log("$ " + shlex.join(args))
        result = subprocess.run(args, cwd=ROOT, input=input_text, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        output = result.stdout.rstrip()
        if record and output:
            self.log(output)
        if check and result.returncode:
            if not record:
                self.log(f"$ {shlex.join(args)} (exit {result.returncode})")
                if output:
                    self.log(output)
            raise RuntimeError(f"command failed ({result.returncode}): {shlex.join(args)}")
        return output

    def compose(self, *args: str, check: bool = True, record: bool = True, input_text: str | None = None) -> str:
        cmd = [
            "docker", "compose", "--project-name", self.project,
            "-f", str(COMPOSE_FILE), "--env-file", str(self.env_file), *args,
        ]
        return self.command(cmd, check=check, record=record, input_text=input_text)

    def recreate_application(self) -> bool:
        # Keep the same database container/volume, and refresh Nginx's startup DNS.
        self.compose("up", "-d", "--no-deps", "--force-recreate", "backend")
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            state = self.inspect_state("backend")
            if state.get("Health", {}).get("Status") == "healthy":
                self.compose("up", "-d", "--no-deps", "--force-recreate", "frontend")
                return self.wait_healthy(30)
            if state.get("Status") == "exited":
                return False
            time.sleep(2)
        return False

    def set_limits(self, cpu: str, memory: str, memswap: str = "512m") -> None:
        # Keep this file private and outside the repository; never include its contents in evidence.
        values = {
            "POSTGRES_PASSWORD": self.password,
            "EXPERIMENT_TAG": self.tag,
            "DB_CPUS": "0.50",
            "DB_MEM_LIMIT": "256m",
            "FRONTEND_CPUS": "0.25",
            "FRONTEND_MEM_LIMIT": "64m",
            "BACKEND_CPUS": cpu,
            "BACKEND_MEM_LIMIT": memory,
            "BACKEND_MEMSWAP_LIMIT": memswap,
        }
        self.env_file.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
        self.env_file.chmod(0o600)

    def container_id(self, service: str, include_stopped: bool = False) -> str:
        args = ["ps", "-q"]
        if include_stopped:
            args.append("-a")
        args.append(service)
        ids = self.compose(*args, record=False).strip().splitlines()
        if not ids:
            raise RuntimeError(f"no container id for {service}")
        return ids[0]

    def inspect_state(self, service: str) -> dict:
        container = self.container_id(service, include_stopped=True)
        raw = self.command(["docker", "inspect", "--format", "{{json .State}}", container], record=False)
        return json.loads(raw)

    def wait_healthy(self, timeout: int = 120) -> bool:
        deadline = time.monotonic() + timeout
        last = {}
        while time.monotonic() < deadline:
            for service in SERVICES:
                try:
                    last[service] = self.inspect_state(service)
                except Exception:
                    last[service] = {"status": "missing"}
            db_ok = last.get("db", {}).get("Health", {}).get("Status") == "healthy"
            backend_ok = last.get("backend", {}).get("Health", {}).get("Status") == "healthy"
            frontend_ok = last.get("frontend", {}).get("Health", {}).get("Status") == "healthy"
            if db_ok and backend_ok and frontend_ok:
                self.refresh_port()
                if self.wait_health_http(20):
                    return True
            if any(state.get("Status") == "exited" for state in last.values()):
                break
            time.sleep(2)
        self.log("Health wait ended: " + json.dumps(last, ensure_ascii=False))
        return False

    def refresh_port(self) -> None:
        container = self.container_id("frontend")
        raw = self.command(["docker", "inspect", "--format", "{{json .NetworkSettings.Ports}}", container], record=False)
        mappings = json.loads(raw).get("80/tcp") or []
        loopback = next((mapping for mapping in mappings if mapping.get("HostIp") == "127.0.0.1"), None)
        if not loopback or not loopback.get("HostPort"):
            raise RuntimeError("frontend has no assigned loopback host port")
        self.port = int(loopback["HostPort"])
        self.summary["frontend_loopback_port"] = self.port

    @property
    def base_url(self) -> str:
        if self.port is None:
            self.refresh_port()
        return f"http://127.0.0.1:{self.port}"

    def request(self, path: str, *, method: str = "GET", payload: dict | None = None, timeout: float = 15):
        data = json.dumps(payload).encode() if payload is not None else None
        headers = {"Content-Type": "application/json"} if data is not None else {}
        req = urllib.request.Request(self.base_url + path, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read()
            return response.status, body

    def wait_health_http(self, timeout: int) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                status, body = self.request("/healthz", timeout=3)
                if status == 200 and json.loads(body).get("status") == "ok":
                    return True
            except Exception:
                pass
            time.sleep(1)
        return False

    def snapshot_stats(self, phase: str) -> None:
        ids = []
        for service in SERVICES:
            try:
                ids.append((service, self.container_id(service)))
            except Exception:
                pass
        if not ids:
            return
        output = self.command(
            ["docker", "stats", "--no-stream", "--format", "{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}|{{.PIDs}}", *[cid for _, cid in ids]],
            check=False, record=False,
        )
        timestamp = now_utc()
        # Docker stats emits container names; retain a stable service column.
        name_map = {
            self.command(["docker", "inspect", "--format", "{{.Name}}", cid], record=False).lstrip("/"): service
            for service, cid in ids
        }
        with self.stats_path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            for line in output.splitlines():
                fields = line.split("|")
                if len(fields) != 4:
                    continue
                name, cpu, memory, pids = fields
                used, _, limit = memory.partition(" /")
                writer.writerow([timestamp, phase, name_map.get(name, name), name, cpu, used.strip(), limit.strip(), pids])

    def cgroup_cpu(self) -> dict[str, int] | None:
        try:
            raw = self.compose("exec", "-T", "backend", "cat", "/sys/fs/cgroup/cpu.stat", record=False)
            return {k: int(v) for k, v in (line.split() for line in raw.splitlines())}
        except Exception as exc:
            self.log(f"cpu.stat unavailable: {exc}")
            return None

    def load(self, phase: str, seconds: int, workers: int = 8) -> dict:
        self.snapshot_stats(phase + "_idle")
        stop = threading.Event()
        metrics = {"requests": 0, "bytes": 0, "statuses": {}, "error_count": 0, "errors": [], "latencies_ms": []}
        lock = threading.Lock()
        load_started = time.monotonic()
        deadline = load_started + seconds

        def worker() -> None:
            while time.monotonic() < deadline:
                started = time.monotonic()
                try:
                    status, body = self.request("/api/tasks", timeout=12)
                    elapsed = (time.monotonic() - started) * 1000
                    with lock:
                        metrics["requests"] += 1
                        metrics["bytes"] += len(body)
                        key = str(status)
                        metrics["statuses"][key] = metrics["statuses"].get(key, 0) + 1
                        metrics["latencies_ms"].append(elapsed)
                except urllib.error.HTTPError as exc:
                    body = exc.read()
                    elapsed = (time.monotonic() - started) * 1000
                    with lock:
                        metrics["requests"] += 1
                        metrics["bytes"] += len(body)
                        key = str(exc.code)
                        metrics["statuses"][key] = metrics["statuses"].get(key, 0) + 1
                        metrics["error_count"] += 1
                        if len(metrics["errors"]) < 20:
                            metrics["errors"].append({"type": "HTTPError", "message": f"HTTP {exc.code}", "latency_ms": round(elapsed, 1)})
                except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError, ValueError) as exc:
                    elapsed = (time.monotonic() - started) * 1000
                    with lock:
                        metrics["error_count"] += 1
                        if len(metrics["errors"]) < 20:
                            metrics["errors"].append({"type": type(exc).__name__, "message": str(exc)[:180], "latency_ms": round(elapsed, 1)})

        def collect_stats() -> None:
            while not stop.is_set():
                self.snapshot_stats(phase)
                stop.wait(1)

        stats_thread = threading.Thread(target=collect_stats, name=f"stats-{phase}", daemon=True)
        stats_thread.start()
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(worker) for _ in range(workers)]
                for future in futures:
                    future.result()
        finally:
            stop.set()
            stats_thread.join(timeout=4)
        latencies = metrics.pop("latencies_ms")
        metrics["duration_seconds"] = seconds
        metrics["elapsed_seconds"] = round(time.monotonic() - load_started, 3)
        metrics["workers"] = workers
        metrics["latency_ms"] = {
            "median": round(statistics.median(latencies), 1) if latencies else None,
            "p95": round(sorted(latencies)[int((len(latencies) - 1) * 0.95)], 1) if latencies else None,
            "max": round(max(latencies), 1) if latencies else None,
        }
        metrics["average_response_bytes"] = round(metrics["bytes"] / metrics["requests"]) if metrics["requests"] else 0
        self.log(f"LOAD {phase}: {json.dumps(metrics, ensure_ascii=False)}")
        return metrics

    def health_result(self) -> dict:
        try:
            status, body = self.request("/healthz", timeout=8)
            return {"http_status": status, "body": json.loads(body)}
        except Exception as exc:
            return {"error": type(exc).__name__, "message": str(exc)[:180]}

    def record_phase(self, name: str, result: dict) -> None:
        result["phase"] = name
        result["recorded_at_utc"] = now_utc()
        cast = self.summary["phases"]
        assert isinstance(cast, list)
        cast.append(result)
        (self.evidence / f"{name}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def record_container_state(self, label: str, service: str) -> dict:
        container = self.container_id(service, include_stopped=True)
        raw = self.command(["docker", "inspect", container], record=False)
        data = json.loads(raw)[0]
        state = data.get("State", {})
        out = {
            "service": service,
            "container_id": data.get("Id"),
            "name": data.get("Name", "").lstrip("/"),
            "image_id": data.get("Image"),
            "restart_count": data.get("RestartCount"),
            "limits": {key: data.get("HostConfig", {}).get(key) for key in ("NanoCpus", "Memory", "MemorySwap")},
            "state": state,
        }
        (self.evidence / f"{label}-{service}-inspect.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return out

    def volume_info(self) -> dict:
        name = f"{self.project}_postgres_data"
        raw = self.command(["docker", "volume", "inspect", "--format", "{{json .}}", name], record=False)
        data = json.loads(raw)
        return {"name": data.get("Name"), "driver": data.get("Driver"), "created_at": data.get("CreatedAt"), "labels": data.get("Labels")}

    def current_container_ids(self) -> dict[str, str]:
        ids = {}
        for service in SERVICES:
            try:
                ids[service] = self.container_id(service, include_stopped=True)
            except Exception:
                pass
        return ids


def capture_existing_main_ids(exp: Experiment, label: str) -> dict[str, str]:
    raw = exp.command(["docker", "ps", "-a", "--no-trunc", "--format", "{{.ID}}\t{{.Names}}"], record=False)
    rows = {}
    for line in raw.splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2 and (parts[1].startswith("cloud-labs-") or parts[1] == "lab4-postgres"):
            rows[parts[1]] = parts[0]
    (exp.evidence / f"main-containers-{label}.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    return rows


def summarize_baseline_stats(exp: Experiment) -> dict:
    grouped: dict[str, list[dict[str, str]]] = {}
    with exp.stats_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["phase"] not in {"baseline-15s_idle", "baseline-15s"}:
                continue
            grouped.setdefault(row["service"], []).append(row)
    metrics = {}
    for service, rows in grouped.items():
        load_rows = [row for row in rows if row["phase"] == "baseline-15s"]
        idle_rows = [row for row in rows if row["phase"] == "baseline-15s_idle"]
        cpu_values = [float(row["cpu_percent"].rstrip("%")) for row in load_rows if row["cpu_percent"].endswith("%")]
        idle_mem = [parse_memory(row["memory_usage"]) for row in idle_rows]
        load_mem = [parse_memory(row["memory_usage"]) for row in load_rows]
        idle_mem = [x for x in idle_mem if x is not None]
        load_mem = [x for x in load_mem if x is not None]
        metrics[service] = {
            "samples": len(load_rows),
            "peak_cpu_percent": max(cpu_values) if cpu_values else None,
            "idle_memory_mib": min(idle_mem) if idle_mem else None,
            "peak_memory_mib": max(load_mem) if load_mem else None,
            "memory_growth_mib": round(max(load_mem) - min(idle_mem), 2) if load_mem and idle_mem else None,
        }
    return metrics


def seed_database(exp: Experiment, project: str) -> int:
    prefix = f"fixture-{project}-"
    sql = "INSERT INTO tasks(title) SELECT :'seed_prefix' || lpad(n::text, 4, '0') || repeat('x', 200 - length(:'seed_prefix') - 4) FROM generate_series(1, 4000) AS series(n);"
    exp.log("Seed: 4000 synthetic titles, 200 characters each; SQL is sent on psql stdin.")
    exp.compose("exec", "-T", "db", "psql", "-X", "-U", "tasks", "-d", "tasks", "-v", "ON_ERROR_STOP=1", "-v", f"seed_prefix={prefix}", input_text=sql + "\n")
    return len(prefix) + 4 + (200 - len(prefix) - 4)


def acceptance_failures(summary: dict) -> list[str]:
    failures = []
    phases = {phase["phase"]: phase for phase in summary.get("phases", [])}
    tight_cpu = phases.get("cpu-010-30s", {})
    before, after = tight_cpu.get("cpu_stat_before"), tight_cpu.get("cpu_stat_after")
    if not before or not after or after.get("nr_throttled", 0) <= before.get("nr_throttled", 0):
        failures.append("CPU throttling was not observed in the tight CPU phase")
    for name in ("cpu-010-30s", "cpu-050-30s"):
        phase = phases.get(name, {})
        if not phase.get("healthy_before_load") or not phase.get("load", {}).get("requests"):
            failures.append(name + " did not complete a healthy API load phase")
    oom_phases = [phase for name, phase in phases.items() if name.startswith("oom-")]
    if not any(
        phase.get("healthy_before_load")
        and phase.get("state_after_load", {}).get("state", {}).get("OOMKilled") is True
        and phase.get("state_after_load", {}).get("state", {}).get("ExitCode") == 137
        for phase in oom_phases
    ):
        failures.append("No healthy-before-load backend ended with OOMKilled=true and exit 137")
    for key in ("working_limit_passed", "postgres_container_unchanged", "postgres_volume_unchanged", "control_task_verified_after_phases", "main_container_ids_unchanged", "experiment_volume_removed", "experiment_images_removed", "experiment_containers_removed", "experiment_networks_removed"):
        if not summary.get(key):
            failures.append(key + " was not confirmed")
    if summary.get("error"):
        failures.append(summary["error"])
    return failures


def main() -> int:
    suffix = secrets.token_hex(3)
    project = f"lab02star-20261028-{suffix}"
    tag = f"20261028-{suffix}"
    evidence = EVIDENCE_ROOT / f"2026-10-28-resource-experiment-{suffix}"
    evidence.mkdir(parents=True, exist_ok=False)
    temp = tempfile.TemporaryDirectory(prefix=f"{project}-")
    temp_root = Path(temp.name)
    env_file = temp_root / "experiment.env"
    temp_password = secrets.token_urlsafe(30)
    exp = Experiment(evidence, env_file, project, tag, temp_password)
    backend_id = f"lab02-star-control-{project}"
    control = {"title": backend_id}
    exp.summary.update({"compose_file": str(COMPOSE_FILE.relative_to(ROOT)), "backend_id": backend_id})
    exp.summary["git_head"] = exp.command(["git", "rev-parse", "HEAD"], record=False)
    exp.summary["source_state"] = "Resource runner and experiment Compose have uncommitted corrections; the source snapshot is included with this evidence."
    (evidence / "runner.py").write_text(Path(__file__).read_text(), encoding="utf-8")
    (evidence / "experiment.compose.yaml").write_text(COMPOSE_FILE.read_text(), encoding="utf-8")
    before_main = capture_existing_main_ids(exp, "before")
    version_text = exp.command(["docker", "version"], record=False)
    compose_version = exp.command(["docker", "compose", "version"], record=False)
    (evidence / "docker-versions.txt").write_text(version_text + "\n" + compose_version + "\n", encoding="utf-8")
    exp.set_limits("0.50", "256m", "512m")
    baseline_ids = {}
    baseline_volume = {}
    try:
        exp.compose("config", "--quiet", check=True)
        exp.compose("up", "-d", "--build")
        if not exp.wait_healthy(180):
            raise RuntimeError("baseline db/backend/frontend did not become healthy")
        exp.summary["frontend_loopback_port"] = exp.port
        baseline_ids = exp.current_container_ids()
        baseline_volume = exp.volume_info()
        exp.summary["initial_container_ids"] = baseline_ids
        exp.summary["initial_postgres_volume"] = baseline_volume
        image_info = {}
        for role in ("backend", "frontend"):
            image = f"clouds-lab02-star-{role}:{tag}"
            image_info[role] = exp.command(["docker", "image", "inspect", "--format", "{{.Id}}|{{json .RepoDigests}}", image], record=False)
        exp.summary["built_images"] = image_info
        (evidence / "image-ids.txt").write_text("".join(f"{name}: {value}\n" for name, value in image_info.items()), encoding="utf-8")
        control_status, control_body = exp.request("/api/tasks", method="POST", payload={"title": backend_id})
        if control_status != 201:
            raise RuntimeError(f"control task POST returned HTTP {control_status}")
        control_result = json.loads(control_body)
        control.update(control_result)
        (evidence / "control-task-created.json").write_text(json.dumps(control, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        seed_title_length = seed_database(exp, project)
        exp.summary["seed_rows"] = 4000
        exp.summary["seed_title_length"] = seed_title_length
        status, body = exp.request("/api/tasks", timeout=30)
        tasks = json.loads(body)
        if status != 200 or len(tasks) != 4001 or not any(x.get("id") == control["id"] for x in tasks):
            raise RuntimeError("initial GET did not return all seed rows and control task")
        exp.summary["seed_verification"] = {"http_status": status, "rows": len(tasks), "control_task_present": True}
        exp.record_phase("baseline-15s", {"limits": {"db": "0.50 CPU / 256m", "backend": "0.50 CPU / 256m", "frontend": "0.25 CPU / 64m"}, "health_before": exp.health_result(), "load": exp.load("baseline-15s", 15, 8), "health_after": exp.health_result()})

        for cpu in ("0.10", "0.50"):
            label = "cpu-010-30s" if cpu == "0.10" else "cpu-050-30s"
            exp.set_limits(cpu, "256m", "512m")
            healthy = exp.recreate_application()
            before = exp.cgroup_cpu() if healthy else None
            load = exp.load(label, 30, 8) if healthy else {"skipped": "backend not healthy"}
            after = exp.cgroup_cpu() if healthy else None
            exp.record_phase(label, {"limits": {"backend_cpu": cpu, "backend_memory": "256m"}, "healthy_before_load": healthy, "cpu_stat_before": before, "load": load, "cpu_stat_after": after, "health_after": exp.health_result()})

        exp.set_limits("0.50", "64m", "64m")
        oom_healthy = exp.recreate_application()
        oom_pre_state = exp.record_container_state("oom-before-load", "backend") if oom_healthy else None
        oom_load = exp.load("oom-064m-30s", 30, 8) if oom_healthy else {"skipped": "backend did not reach healthy before load"}
        oom_post_state = exp.record_container_state("oom-after-load", "backend") if exp.current_container_ids().get("backend") else {"state": "container missing"}
        oom_result = {"limits": {"backend_cpu": "0.50", "backend_memory": "64m", "backend_memswap": "64m"}, "healthy_before_load": oom_healthy, "state_before_load": oom_pre_state, "load": oom_load, "state_after_load": oom_post_state, "health_after": exp.health_result()}
        exp.record_phase("oom-064m-30s", oom_result)
        state = oom_post_state.get("state", {}) if isinstance(oom_post_state, dict) else {}
        oom_confirmed = state.get("OOMKilled") is True and state.get("ExitCode") == 137
        memory_load_workers = 8
        if oom_healthy and not oom_confirmed:
            exp.log("64m did not produce OOM; one calibration will increase API concurrency to 16 for 30s.")
            exp.set_limits("0.50", "64m", "64m")
            calibration_healthy = exp.recreate_application()
            calibration_load = exp.load("oom-calibration-16workers-30s", 30, 16) if calibration_healthy else {"skipped": "backend did not reach healthy"}
            calibration_state = exp.record_container_state("oom-calibration-after-load", "backend") if exp.current_container_ids().get("backend") else {"state": "container missing"}
            exp.record_phase("oom-calibration-16workers-30s", {"limits": {"backend_cpu": "0.50", "backend_memory": "64m", "backend_memswap": "64m"}, "workers": 16, "healthy_before_load": calibration_healthy, "load": calibration_load, "state_after_load": calibration_state, "health_after": exp.health_result()})
            memory_load_workers = 16

        working_candidates = ("128m", "256m", "512m")
        for memory in working_candidates:
            label = "working-" + memory.replace("m", "m-60s")
            exp.set_limits("0.50", memory, "512m")
            healthy = exp.recreate_application()
            before = exp.cgroup_cpu() if healthy else None
            load = exp.load(label, 60, memory_load_workers) if healthy else {"skipped": "backend did not reach healthy before load"}
            state_after = exp.record_container_state(label + "-after-load", "backend") if exp.current_container_ids().get("backend") else {"state": "container missing"}
            health_after = exp.health_result()
            exp.record_phase(label, {"limits": {"backend_cpu": "0.50", "backend_memory": memory}, "healthy_before_load": healthy, "cpu_stat_before": before, "load": load, "state_after_load": state_after, "health_after": health_after})
            phase_state = state_after.get("state", {}) if isinstance(state_after, dict) else {}
            load_errors = load.get("error_count", len(load.get("errors", []))) if isinstance(load, dict) else 0
            statuses = load.get("statuses", {}) if isinstance(load, dict) else {}
            acceptable = healthy and phase_state.get("Status") == "running" and not phase_state.get("OOMKilled") and state_after.get("restart_count") == 0 and health_after.get("http_status") == 200 and load_errors == 0 and load.get("requests", 0) > 0 and all(code == "200" for code in statuses)
            if acceptable:
                exp.summary["working_limit_passed"] = memory
                break
            exp.log(f"Working limit {memory} did not satisfy health/no-OOM/no-error gate; proceeding to the next approved memory candidate.")

        # Verify that the same isolated database container and volume persisted across all app recreations.
        final_ids = exp.current_container_ids()
        final_volume = exp.volume_info()
        exp.summary["final_container_ids_before_cleanup"] = final_ids
        exp.summary["final_postgres_volume_before_cleanup"] = final_volume
        exp.summary["postgres_container_unchanged"] = baseline_ids.get("db") == final_ids.get("db")
        exp.summary["postgres_volume_unchanged"] = baseline_volume.get("name") == final_volume.get("name") and baseline_volume.get("created_at") == final_volume.get("created_at")
        try:
            status, body = exp.request("/api/tasks", timeout=30)
            final_tasks = json.loads(body)
            observed = next((task for task in final_tasks if task.get("id") == control.get("id")), None)
            control_ok = observed == control
            exp.summary["control_task_verified_after_phases"] = control_ok
            exp.summary["control_task_final_read"] = observed
        except Exception as exc:
            exp.summary["control_task_verified_after_phases"] = False
            exp.summary["control_task_final_read_error"] = f"{type(exc).__name__}: {str(exc)[:180]}"
        exp.summary["finished_at_utc"] = now_utc()
    except Exception as exc:
        exp.summary["error"] = f"{type(exc).__name__}: {str(exc)}"
        exp.log("EXPERIMENT ERROR: " + exp.summary["error"])
        raise
    finally:
        try:
            exp.compose("down", "--volumes", "--remove-orphans", check=False)
        except Exception as exc:
            exp.log(f"CLEANUP ERROR: {type(exc).__name__}: {str(exc)[:180]}")
        image_names = [f"clouds-lab02-star-{role}:{tag}" for role in ("backend", "frontend")]
        exp.command(["docker", "image", "rm", *image_names], check=False)
        after_main = capture_existing_main_ids(exp, "after")
        exp.summary["main_container_ids_before"] = before_main
        exp.summary["main_container_ids_after"] = after_main
        exp.summary["main_container_ids_unchanged"] = before_main == after_main
        remaining = exp.command(["docker", "volume", "ls", "--format", "{{.Name}}"], check=False, record=False).splitlines()
        exp.summary["experiment_volume_removed"] = f"{project}_postgres_data" not in remaining
        remaining_images = exp.command(["docker", "image", "ls", "--format", "{{.Repository}}:{{.Tag}}"], check=False, record=False).splitlines()
        exp.summary["experiment_images_removed"] = all(name not in remaining_images for name in image_names)
        exp.summary["experiment_containers_removed"] = not exp.command(["docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={project}"], record=False).strip()
        exp.summary["experiment_networks_removed"] = not exp.command(["docker", "network", "ls", "-q", "--filter", f"label=com.docker.compose.project={project}"], record=False).strip()
        baseline_metrics = summarize_baseline_stats(exp)
        exp.summary["baseline_resource_metrics"] = baseline_metrics
        if baseline_metrics:
            exp.summary["highest_baseline_cpu_service"] = max(
                baseline_metrics, key=lambda service: baseline_metrics[service]["peak_cpu_percent"] or -1
            )
            exp.summary["highest_baseline_memory_growth_service"] = max(
                baseline_metrics, key=lambda service: baseline_metrics[service]["memory_growth_mib"] or -1
            )
        exp.summary["finished_at_utc"] = now_utc()
        exp.summary["acceptance_failures"] = acceptance_failures(exp.summary)
        exp.summary["accepted"] = not exp.summary["acceptance_failures"]
        (evidence / "summary.json").write_text(json.dumps(exp.summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        exp.log("SUMMARY: " + json.dumps(exp.summary, ensure_ascii=False))
        temp.cleanup()
    print(json.dumps({"evidence": str(evidence), "summary": exp.summary}, indent=2, ensure_ascii=False))
    return 0 if exp.summary["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
