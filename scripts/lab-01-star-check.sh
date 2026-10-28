#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
network="lab1-star-$$"
container="lab1-star-nginx-$$"
fixtures_source="$repo_root/labs/lab-01-star/fixtures"
fixture_dir="$(mktemp -d "${TMPDIR:-/tmp}/lab1-star-fixtures.XXXXXX")"
base=''
cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
  rm -rf "$fixture_dir"
}
trap cleanup EXIT

# Stage fixture files that are not ignored by Git. In particular, never copy a local
# ignored .env; the exposed dotfile is always the explicit test-only fixture.
while IFS= read -r -d '' fixture_path; do
  relative_path="${fixture_path#labs/lab-01-star/fixtures/}"
  mkdir -p "$fixture_dir/$(dirname "$relative_path")"
  cp "$repo_root/$fixture_path" "$fixture_dir/$relative_path"
done < <(git -C "$repo_root" ls-files -z --cached --others --exclude-standard -- labs/lab-01-star/fixtures)
cp "$fixture_dir/test-env.fixture" "$fixture_dir/.env"

docker network create "$network" >/dev/null
docker run -d --name "$container" --network "$network" \
  -p 127.0.0.1::8080 \
  -v "$repo_root/labs/lab-01-star/nginx.conf:/etc/nginx/conf.d/default.conf:ro" \
  -v "$fixture_dir:/usr/share/nginx/html:ro" \
  nginx:1.29-alpine@sha256:5616878291a2eed594aee8db4dade5878cf7edcb475e59193904b198d9b830de >/dev/null
port="$(docker port "$container" 8080/tcp | awk -F: 'NR == 1 { print $NF }')"
base="http://127.0.0.1:$port"

for _ in $(seq 1 20); do
  if curl -sS "$base/" -o /dev/null; then break; fi
  sleep 1
done

test_response() {
  local name="$1" path="$2" expected="$3" status body_file="$fixture_dir/$1.body"
  status="$(curl --path-as-is -sS -o "$body_file" -w '%{http_code}' "$base$path")"
  printf '%s: GET %s -> HTTP %s\n' "$name" "$path" "$status"
  [[ "$status" == "$expected" ]]
}

# Check 1: alias traversal reaches the fake file one directory above the image directory.
test_response traversal '/img../secret.txt' 200
grep -q 'TRAVERSAL_FIXTURE=only-for-local-lab' "$fixture_dir/traversal.body"

# Check 2: directory listing reveals names in the backup folder.
test_response listing '/backup/' 200
grep -q 'backup-note.txt' "$fixture_dir/listing.body"

# Check 3: an undisallowed dotfile is served as plain text; its content is fake.
test_response dotfile '/.env' 200
grep -q 'TEST_FIXTURE_ONLY=1' "$fixture_dir/dotfile.body"

printf 'Exposed test fixtures matched all three checks; no external host or real credentials were used.\n'
