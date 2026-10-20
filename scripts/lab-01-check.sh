#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
base='https://app.local:8443'
companion='https://companion.local:8443'
resolve_app=(--resolve app.local:8443:127.0.0.1)
resolve_companion=(--resolve companion.local:8443:127.0.0.1)

check_code() {
  local expected="$1" url="$2"; shift 2
  local actual
  actual="$(curl -ksS "$@" -o /tmp/lab1-check-body -w '%{http_code}' "$url")"
  printf '%s -> HTTP %s (ожидалось %s)\n' "$url" "$actual" "$expected"
  [[ "$actual" == "$expected" ]]
}

printf '%s\n' '1. HTTP redirects to HTTPS:'
curl -sSI http://127.0.0.1:8080/ | awk 'BEGIN{IGNORECASE=1} /^HTTP\// || /^Location:/{gsub("\r",""); print}'

printf '\n%s\n' '2. Both backend IDs appear behind /api:'
: > /tmp/lab1-backend-ids
sleep 2
for _ in $(seq 1 20); do
  curl -ksS -D /tmp/lab1-headers "${resolve_app[@]}" -o /dev/null "$base/api/tasks"
  awk 'BEGIN{IGNORECASE=1} /^X-Backend-ID:/{gsub("\r",""); print $2}' /tmp/lab1-headers >> /tmp/lab1-backend-ids
  sleep 0.35
done
sort -u /tmp/lab1-backend-ids | tee /tmp/lab1-backend-ids.unique
grep -qx backend-1 /tmp/lab1-backend-ids.unique
grep -qx backend-2 /tmp/lab1-backend-ids.unique

printf '\n%s\n' '3. Alias and virtual hosts:'
check_code 200 "$base/docs/lab-notes.txt" "${resolve_app[@]}"
companion_body="$(curl -ksS "${resolve_companion[@]}" "$companion/")"
printf '%s\n' "$companion_body" | rg -q 'Соседний проект'
app_body="$(curl -ksS "${resolve_app[@]}" "$base/")"
printf '%s\n' "$app_body" | rg -q 'Учебные задачи'
check_code 404 "$companion/missing-page" "${resolve_companion[@]}"
grep -q 'В соседнем проекте такого адреса нет' /tmp/lab1-check-body

printf '\n%s\n' '4. Custom 404 and basic auth:'
check_code 404 "$base/missing-page" "${resolve_app[@]}"
grep -q '404 — страница не найдена' /tmp/lab1-check-body
check_code 401 "$base/admin" "${resolve_app[@]}"
check_code 401 "$base/admin/" "${resolve_app[@]}"
check_code 200 "$base/assets/app.js" "${resolve_app[@]}"
check_code 200 "$base/assets/styles.css" "${resolve_app[@]}"
check_code 404 "$base/assets/admin/index.html" "${resolve_app[@]}"
check_code 404 "$base/assets/docs/lab-notes.txt" "${resolve_app[@]}"
netrc="$(mktemp "$repo_root/.local/nginx/netrc.XXXXXX")"
trap 'rm -f "$netrc"' EXIT
printf 'machine app.local login student password %s\n' "$(cat .local/nginx/admin-password.txt)" > "$netrc"
chmod 600 "$netrc"
check_code 200 "$base/admin" "${resolve_app[@]}" --netrc-file "$netrc"
rm -f "$netrc"
trap - EXIT

printf '\n%s\n' '5. Rate limit returns 429 under a short burst:'
seq 1 24 | xargs -P 12 -I '{}' sh -c 'curl -ksS --resolve app.local:8443:127.0.0.1 -o /dev/null -w "%{http_code}\n" https://app.local:8443/api/tasks' > /tmp/lab1-rate-codes
rate_limited="$(grep -c '^429$' /tmp/lab1-rate-codes || true)"
printf 'HTTP 429 responses: %s / 24\n' "$rate_limited"
[[ "$rate_limited" -gt 0 ]]

printf '\n%s\n' '6. Stop one backend, API remains available:'
docker compose stop backend2 >/dev/null
check_code 200 "$base/api/tasks" "${resolve_app[@]}"
curl -ksS -D /tmp/lab1-failover-headers -o /dev/null "${resolve_app[@]}" "$base/api/tasks"
awk 'BEGIN{IGNORECASE=1} /^X-Backend-ID:/{gsub("\r",""); print "Live backend after stop:", $2}' /tmp/lab1-failover-headers
rg -qi '^X-Backend-ID: backend-1' /tmp/lab1-failover-headers
docker compose start backend2 >/dev/null
for _ in $(seq 1 20); do
  if [[ "$(docker inspect -f '{{.State.Health.Status}}' cloud-labs-backend2-1 2>/dev/null || true)" == healthy ]]; then break; fi
  sleep 2
done
[[ "$(docker inspect -f '{{.State.Health.Status}}' cloud-labs-backend2-1)" == healthy ]]

printf '\nAll Lab 1 checks passed.\n'
