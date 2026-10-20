#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
local_dir="$repo_root/.local/nginx"
mkdir -p "$local_dir"
chmod 700 "$repo_root/.local" "$local_dir"

if [[ ! -s "$local_dir/tls.crt" || ! -s "$local_dir/tls.key" ]]; then
  config="$local_dir/openssl.cnf"
  cat > "$config" <<'CONFIG'
[req]
distinguished_name = dn
x509_extensions = v3_req
prompt = no
[dn]
CN = localhost
[v3_req]
subjectAltName = @alt_names
basicConstraints = CA:TRUE
keyUsage = digitalSignature, keyEncipherment, keyCertSign
extendedKeyUsage = serverAuth
[alt_names]
DNS.1 = localhost
DNS.2 = app.local
DNS.3 = companion.local
IP.1 = 127.0.0.1
CONFIG
  openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
    -keyout "$local_dir/tls.key" -out "$local_dir/tls.crt" -config "$config" >/dev/null 2>&1
  rm -f "$config"
  chmod 600 "$local_dir/tls.key"
fi

if [[ ! -s "$local_dir/.htpasswd" ]]; then
  password="$(openssl rand -base64 24)"
  hash="$(printf '%s' "$password" | openssl passwd -apr1 -stdin)"
  printf 'student:%s\n' "$hash" > "$local_dir/.htpasswd"
  printf '%s\n' "$password" > "$local_dir/admin-password.txt"
  unset password hash
  chmod 600 "$local_dir/.htpasswd"
  chmod 600 "$local_dir/admin-password.txt"
fi

echo 'Локальный сертификат и basic auth готовы в .local/nginx/ (каталог исключён из Git). Пароль student — в .local/nginx/admin-password.txt.'
