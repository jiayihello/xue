#!/usr/bin/env bash
set -euo pipefail

# One-click validator for NAT66 dual-stack port mapping and IPv6 SNAT outbound
# Usage:
#   bash server/verify_nat66.sh <container_name> [internal_port] [protocol]
# Example:
#   bash server/verify_nat66.sh myct 18081 tcp
# Notes:
# - Requires the backend to be running with IPV6_MODE=NAT66 and NAT_LISTEN_IPV6 set in app.ini
# - Will try to start a temporary HTTP server in the container for inbound tests (best effort)
# - Cleans up the created port mapping and the temporary server on exit

CONTAINER_NAME=${1:-}
INTERNAL_PORT=${2:-18081}
PROTO=${3:-tcp}

if [[ -z "$CONTAINER_NAME" ]]; then
  echo "Usage: $0 <container_name> [internal_port=18081] [protocol=tcp]" >&2
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR/server" >/dev/null 2>&1 || true

# Helpers
read_ini() {
  local key="$1"
  grep -E "^${key}[:space:]*=" app.ini | head -n1 | awk -F'=' '{print $2}' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//'
}

HTTP_PORT=$(read_ini "HTTP_PORT")
[[ -z "$HTTP_PORT" ]] && HTTP_PORT=8060
TOKEN=$(read_ini "TOKEN")
MAIN_IF=$(read_ini "MAIN_INTERFACE")
NAT_V4=$(read_ini "NAT_LISTEN_IP")
IPV6_MODE=$(read_ini "IPV6_MODE")
NAT_V6=$(read_ini "NAT_LISTEN_IPV6")

if [[ -z "$TOKEN" ]]; then
  echo "ERROR: TOKEN not set in app.ini" >&2
  exit 1
fi

# Pick a random external port (avoid 1-1024)
DPORT=$(( (RANDOM % 20000) + 30000 ))

API() {
  local method="$1"; shift
  local path="$1"; shift
  local data="$*"
  if [[ "$method" == "GET" ]]; then
    curl -sS -H "apikey: $TOKEN" "http://127.0.0.1:${HTTP_PORT}${path}"
  else
    curl -sS -X "$method" -H "apikey: $TOKEN" -H "Content-Type: application/x-www-form-urlencoded" -d "$data" "http://127.0.0.1:${HTTP_PORT}${path}"
  fi
}

cleanup() {
  set +e
  echo "\n[Cleanup] Deleting NAT rule and stopping temp server..."
  API POST "/api/delport" "hostname=${CONTAINER_NAME}&dtype=${PROTO}&dport=${DPORT}&sport=${INTERNAL_PORT}" >/dev/null 2>&1 || true
  lxc exec "$CONTAINER_NAME" -- sh -lc 'PIDFILE=/tmp/.lxd_test_http.pid; [ -f "$PIDFILE" ] && kill $(cat "$PIDFILE") >/dev/null 2>&1 || true; rm -f "$PIDFILE"' >/dev/null 2>&1 || true
}
trap cleanup EXIT

# 1) API health
echo "[1/6] Checking API health..."
API GET "/api/check" | jq -r '.msg? // .message? // .status? // .code' 2>/dev/null || API GET "/api/check"

# 2) Try to start a tiny HTTP server in container (best effort)
echo "[2/6] Starting tiny HTTP server inside container on port ${INTERNAL_PORT} (best effort)..."
lxc exec "$CONTAINER_NAME" -- sh -lc '
  set -e
  PORT="'"${INTERNAL_PORT}"'"
  PIDFILE=/tmp/.lxd_test_http.pid
  # Prefer python3 http.server
  if command -v python3 >/dev/null 2>&1; then
    nohup python3 -m http.server "$PORT" >/dev/null 2>&1 & echo $! > "$PIDFILE"
  elif command -v python >/dev/null 2>&1; then
    nohup python -m SimpleHTTPServer "$PORT" >/dev/null 2>&1 & echo $! > "$PIDFILE"
  elif command -v busybox >/dev/null 2>&1; then
    nohup busybox httpd -f -p "$PORT" >/dev/null 2>&1 & echo $! > "$PIDFILE"
  else
    echo "WARN: No python3/python/busybox http server available; inbound test may still pass if service already running" >&2
    exit 0
  fi
' || true
sleep 2

# 3) Add NAT rule via API
echo "[3/6] Adding NAT rule: ${PROTO} ${DPORT} -> ${INTERNAL_PORT} for ${CONTAINER_NAME}..."
ADD_RES=$(API POST "/api/addport" "hostname=${CONTAINER_NAME}&dtype=${PROTO}&dport=${DPORT}&sport=${INTERNAL_PORT}")
echo "$ADD_RES" | jq . 2>/dev/null || echo "$ADD_RES"

# 4) Verify devices and host listening sockets
echo "[4/6] Verifying LXD proxy devices and host sockets..."
LIST_RES=$(API GET "/api/natlist?hostname=${CONTAINER_NAME}")
echo "$LIST_RES" | jq . 2>/dev/null || echo "$LIST_RES"

sleep 2
V4_LISTEN_OK=$(ss -ltn 2>/dev/null | awk '{print $4}' | grep -E "[:\[]${DPORT}([\]]|$)" | head -n1 | wc -l | tr -d ' ')
if [[ "$V4_LISTEN_OK" == "1" ]]; then echo "  - IPv4 listen OK on *:${DPORT}"; else echo "  - IPv4 listen MISSING on *:${DPORT}"; fi

if [[ "${IPV6_MODE^^}" == "NAT66" && -n "${NAT_V6}" ]]; then
  # some systems show [::] or [addr] in ss output; we just check by port
  V6_LISTEN_OK=$(ss -ltn 2>/dev/null | awk '{print $4}' | grep -E "[:\[]${DPORT}([\]]|$)" | wc -l | tr -d ' ')
  if [[ "$V6_LISTEN_OK" -ge 2 ]]; then
    echo "  - IPv6 listen likely OK on [${NAT_V6%/*}]:${DPORT}"
  else
    echo "  - IPv6 listen MISSING on [${NAT_V6%/*}]:${DPORT}"
  fi
fi

# 5) Inbound test (v4 + v6)
echo "[5/6] Inbound test via host curl..."
V4_HTTP=$(curl -sS --max-time 3 "http://127.0.0.1:${DPORT}" || true)
if [[ -n "$V4_HTTP" ]]; then echo "  - IPv4 inbound OK"; else echo "  - IPv4 inbound FAILED (empty or timeout)"; fi

if [[ "${IPV6_MODE^^}" == "NAT66" && -n "${NAT_V6}" ]]; then
  V6_ADDR_NO_PREFIX=${NAT_V6%/*}
  V6_HTTP=$(curl -g -sS --max-time 5 "http://[${V6_ADDR_NO_PREFIX}]:${DPORT}" || true)
  if [[ -n "$V6_HTTP" ]]; then echo "  - IPv6 inbound OK"; else echo "  - IPv6 inbound FAILED (empty or timeout)"; fi
else
  echo "  - IPv6 inbound skipped (IPV6_MODE!=NAT66 or NAT_LISTEN_IPV6 not set)"
fi

# 6) Outbound test from container (IPv6 SNAT)
echo "[6/6] Outbound IPv6 test from container..."
OUT6=$(lxc exec "$CONTAINER_NAME" -- sh -lc '
  set +e
  if command -v curl >/dev/null 2>&1; then
    curl -6 -s --max-time 6 https://ifconfig.co || true
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- https://ifconfig.co || true
  elif command -v busybox >/dev/null 2>&1; then
    busybox wget -qO- https://ifconfig.co || true
  else
    # fallback: try ipv6 ping to public resolver
    (ping -6 -c1 2606:4700:4700::1111 >/dev/null 2>&1 && echo PING_OK) || true
  fi
') || true
if [[ -n "$OUT6" ]]; then echo "  - IPv6 outbound likely OK -> $OUT6"; else echo "  - IPv6 outbound FAILED (no tool or blocked)"; fi

echo "\nDone. Review the above checks. The NAT rule will now be removed and the temp server stopped."

