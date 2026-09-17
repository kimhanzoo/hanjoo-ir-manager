#!/bin/sh
set -eu
VERSION="0.6.4"
export HANJOO_VERSION="$VERSION"
SOURCE="/opt/hanjoo/integration/hanjoo_ir"
OPTIONS="/data/options.json"

if [ -d /config ]; then
  CONFIG_ROOT="/config"
elif [ -d /homeassistant ]; then
  CONFIG_ROOT="/homeassistant"
else
  echo "[HanJoo IR] ERROR: Home Assistant config mapping is not available."
  echo "[HanJoo IR] Expected /config or /homeassistant. Check add-on map: config:rw"
  exit 1
fi
TARGET="$CONFIG_ROOT/custom_components/hanjoo_ir"
MARKER="$TARGET/.hanjoo-managed"
RESTART_MARKER="/data/manager_restart_required"

opt_bool() {
  key="$1"; default="$2"
  if [ -f "$OPTIONS" ]; then
    value="$(sed -n 's/.*"'"$key"'"[[:space:]]*:[[:space:]]*\(true\|false\).*/\1/p' "$OPTIONS" | head -n1)"
    [ -n "$value" ] && { [ "$value" = "true" ] && return 0 || return 1; }
  fi
  [ "$default" = "true" ]
}

manifest_version() {
  f="$1/manifest.json"
  [ -f "$f" ] || { printf '%s' "not-installed"; return 0; }
  v="$(sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$f" | head -n1)"
  [ -n "$v" ] && printf '%s' "$v" || printf '%s' "unknown"
}

ensure_bootstrap() {
  cfg="$CONFIG_ROOT/configuration.yaml"
  [ -f "$cfg" ] || touch "$cfg"
  if grep -Eq '^[[:space:]]*hanjoo_ir[[:space:]]*:' "$cfg"; then
    echo "[HanJoo IR] Bootstrap already present in configuration.yaml"
    return 0
  fi
  cat >> "$cfg" <<'EOC'

# HanJoo IR bootstrap (managed by HanJoo IR Core add-on)
hanjoo_ir:
EOC
  echo "[HanJoo IR] Added 'hanjoo_ir:' bootstrap to configuration.yaml"
}

install_manager() {
  if ! opt_bool install_manager true; then
    echo "[HanJoo IR] Manager auto-install is disabled by add-on option."
    return 0
  fi
  mkdir -p "$CONFIG_ROOT/custom_components"
  src_ver="$(manifest_version "$SOURCE")"
  dst_ver="$(manifest_version "$TARGET")"
  managed=false; [ -f "$MARKER" ] && managed=true
  echo "[HanJoo IR] Bundled Manager version: $src_ver"
  echo "[HanJoo IR] Installed Manager version: $dst_ver (managed=$managed)"
  if [ "$src_ver" = "unknown" ] || [ "$src_ver" = "not-installed" ]; then
    echo "[HanJoo IR] ERROR: bundled Manager manifest is missing or invalid."
    exit 1
  fi
  if [ -d "$TARGET" ] && [ "$src_ver" = "$dst_ver" ]; then
    if [ "$managed" = true ]; then
      echo "[HanJoo IR] Manager $dst_ver already installed and managed by this add-on."
    else
      # install_manager=true means the add-on is the selected owner. Adopt the
      # matching copy without rewriting it; users preferring HACS should disable
      # install_manager in add-on options.
      printf '%s\n' "$VERSION" > "$MARKER"
      echo "[HanJoo IR] Existing matching Manager $dst_ver adopted by this add-on."
    fi
    ensure_bootstrap
    return 0
  fi
  if [ -d "$TARGET" ] && ! opt_bool auto_update_manager true; then
    echo "[HanJoo IR] Manager auto-update disabled; keeping installed $dst_ver"
    ensure_bootstrap
    return 0
  fi
  if [ -d "$TARGET" ] && [ "$managed" = false ]; then
    backup="$CONFIG_ROOT/custom_components/hanjoo_ir.backup-before-addon-$(date +%Y%m%d-%H%M%S)"
    echo "[HanJoo IR] Existing HACS/manual Manager $dst_ver found; backing it up to $backup"
    cp -a "$TARGET" "$backup"
  fi
  stage="$CONFIG_ROOT/custom_components/.hanjoo_ir.stage.$$"
  rm -rf "$stage"
  cp -a "$SOURCE" "$stage"
  find "$stage" -type d -name __pycache__ -prune -exec rm -rf {} \; 2>/dev/null || true
  find "$stage" -type f -name '*.pyc' -delete 2>/dev/null || true
  printf '%s\n' "$VERSION" > "$stage/.hanjoo-managed"
  rm -rf "$TARGET.old"
  [ -d "$TARGET" ] && mv "$TARGET" "$TARGET.old"
  if ! mv "$stage" "$TARGET"; then
    echo "[HanJoo IR] ERROR: failed to install Manager; restoring previous copy."
    [ -d "$TARGET.old" ] && mv "$TARGET.old" "$TARGET"
    exit 1
  fi
  rm -rf "$TARGET.old"
  ensure_bootstrap
  touch "$RESTART_MARKER"
  echo "[HanJoo IR] SUCCESS: Manager integration installed/updated to $src_ver"
  echo "[HanJoo IR] Restart Home Assistant Core once to load the new Manager version."
}

http_ok() {
  url="$1"
  node -e 'const http=require("node:http");const u=process.argv[1];const r=http.get(u,x=>{let raw="";x.on("data",c=>raw+=c);x.on("end",()=>{try{const j=JSON.parse(raw||"{}");process.exit(x.statusCode===200&&j.ok===true?0:1)}catch{process.exit(1)}})});r.on("error",()=>process.exit(1));r.setTimeout(700,()=>{r.destroy();process.exit(1)})' "$url" >/dev/null 2>&1
}

wait_http() {
  name="$1"; url="$2"; pid="$3"; logfile="$4"
  i=0
  while [ "$i" -lt 40 ]; do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "[HanJoo IR] ERROR: $name exited during startup."
      [ -f "$logfile" ] && { echo "----- $name log -----"; cat "$logfile"; echo "---------------------"; }
      return 1
    fi
    if http_ok "$url"; then
      echo "[HanJoo IR] $name healthy: $url"
      return 0
    fi
    i=$((i+1)); sleep 0.25
  done
  echo "[HanJoo IR] ERROR: $name did not become healthy within 10 seconds."
  [ -f "$logfile" ] && { echo "----- $name log -----"; cat "$logfile"; echo "---------------------"; }
  return 1
}

dump_log() {
  label="$1"; file="$2"
  [ -f "$file" ] && { echo "----- $label log -----"; tail -n 120 "$file"; echo "----------------------"; }
}

cleanup(){
  kill "${probe_pid:-}" "${brain_pid:-}" "${core_pid:-}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "============================================================"
echo "[HanJoo IR] Starting unified add-on $VERSION"
echo "[HanJoo IR] Config root: $CONFIG_ROOT"
echo "============================================================"
install_manager

node /opt/hanjoo/probe_server.cjs 8101 >/tmp/hanjoo-ir-probe.log 2>&1 & probe_pid=$!
node /opt/hanjoo/brain_runtime.cjs 8102 >/tmp/hanjoo-ir-brain.log 2>&1 & brain_pid=$!
node /opt/hanjoo/core_runtime.cjs 8099 >/tmp/hanjoo-ir-core.log 2>&1 & core_pid=$!

echo "[HanJoo IR] Protocol sidecar process started on :8101 (pid=$probe_pid)"
echo "[HanJoo IR] Brain process started on :8102 (pid=$brain_pid)"
echo "[HanJoo IR] Core gateway process started on :8099 (pid=$core_pid)"

wait_http "Protocol sidecar" "http://127.0.0.1:8101/health" "$probe_pid" /tmp/hanjoo-ir-probe.log || exit 1
wait_http "Brain service" "http://127.0.0.1:8102/health" "$brain_pid" /tmp/hanjoo-ir-brain.log || exit 1
wait_http "Core gateway" "http://127.0.0.1:8099/health" "$core_pid" /tmp/hanjoo-ir-core.log || exit 1
echo "[HanJoo IR] All services healthy (Core :8099, Protocol :8101, Brain :8102)."

# Keep PID 1 as the supervisor for all three children. If any service exits or
# stops answering health checks, fail the add-on so Home Assistant can restart it.
while :; do
  sleep 10
  for item in "Protocol sidecar|$probe_pid|http://127.0.0.1:8101/health|/tmp/hanjoo-ir-probe.log" \
              "Brain service|$brain_pid|http://127.0.0.1:8102/health|/tmp/hanjoo-ir-brain.log" \
              "Core gateway|$core_pid|http://127.0.0.1:8099/health|/tmp/hanjoo-ir-core.log"; do
    name=$(printf '%s' "$item" | cut -d'|' -f1)
    pid=$(printf '%s' "$item" | cut -d'|' -f2)
    url=$(printf '%s' "$item" | cut -d'|' -f3)
    logfile=$(printf '%s' "$item" | cut -d'|' -f4)
    if ! kill -0 "$pid" 2>/dev/null || ! http_ok "$url"; then
      echo "[HanJoo IR] ERROR: $name became unavailable; stopping add-on for Supervisor restart."
      dump_log "$name" "$logfile"
      exit 1
    fi
  done
done
