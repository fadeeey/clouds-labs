#!/usr/bin/env bash
set -euo pipefail

image='nginx:1.29-alpine@sha256:5616878291a2eed594aee8db4dade5878cf7edcb475e59193904b198d9b830de'
suffix="$$"
network="clouds-lab-dns-check-$suffix"
backend_a="clouds-lab-dns-a-$suffix"
backend_b="clouds-lab-dns-b-$suffix"
proxy="clouds-lab-dns-proxy-$suffix"
tmp_dir="$(mktemp -d)"

cleanup() {
  docker rm -f "$proxy" "$backend_a" "$backend_b" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
  rm -rf "$tmp_dir"
}
trap cleanup EXIT

docker network create "$network" >/dev/null
subnet="$(docker network inspect -f '{{(index .IPAM.Config 0).Subnet}}' "$network" | cut -d/ -f1)"
prefix="${subnet%.*}"
backend_a_ip="$prefix.10"
backend_b_ip="$prefix.11"
proxy_ip="$prefix.12"
docker run -d --name "$backend_a" --network "$network" --ip "$backend_a_ip" --network-alias backend "$image" >/dev/null

cat > "$tmp_dir/default.conf" <<'NGINX'
upstream api {
    zone api 64k;
    server backend:80 resolve;
}
resolver 127.0.0.11 valid=2s ipv6=off;
server {
    listen 8080;
    location / {
        proxy_pass http://api;
        add_header X-Upstream $upstream_addr always;
    }
}
NGINX

docker run -d --name "$proxy" --network "$network" --ip "$proxy_ip" \
  -p 127.0.0.1::8080 \
  -v "$tmp_dir/default.conf:/etc/nginx/conf.d/default.conf:ro" "$image" >/dev/null

host_port="$(docker port "$proxy" 8080/tcp | awk -F: '{print $NF}')"
url="http://127.0.0.1:$host_port/"
read_response() {
  local code
  code="$(curl --max-time 3 -sS -D "$tmp_dir/headers" -o "$tmp_dir/body" -w '%{http_code}' "$url" || true)"
  printf '%s %s\n' "$code" "$(awk 'BEGIN{IGNORECASE=1} /^X-Upstream:/{gsub("\r", ""); print $2}' "$tmp_dir/headers")"
}

initial=''
for attempt in $(seq 1 15); do
  initial="$(read_response)"
  [[ "$initial" == "200 $backend_a_ip:80" ]] && break
  sleep 1
done
[[ "$initial" == "200 $backend_a_ip:80" ]] || {
  printf 'Initial backend did not become ready. Last response: %s\n' "$initial" >&2
  exit 1
}
printf 'Initial backend: %s (%s)\n' "$backend_a" "$backend_a_ip"

docker rm -f "$backend_a" >/dev/null
docker run -d --name "$backend_b" --network "$network" --ip "$backend_b_ip" --network-alias backend "$image" >/dev/null
[[ "$backend_a_ip" != "$backend_b_ip" ]]
printf 'Replacement backend: %s (%s)\n' "$backend_b" "$backend_b_ip"

for attempt in $(seq 1 15); do
  response="$(read_response)"
  if [[ "$response" == "200 $backend_b_ip:80" ]]; then
    printf 'Nginx discovered the replacement backend without reload (attempt %s): %s\n' "$attempt" "$response"
    exit 0
  fi
  sleep 1
done

printf 'Nginx did not discover replacement backend. Last response: %s\n' "$response" >&2
exit 1
