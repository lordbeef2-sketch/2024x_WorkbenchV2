#!/usr/bin/env bash
set -euo pipefail

port=""
bind_host=""
no_browser=0
prepare_only=0
skip_install=0

usage() {
  cat <<'EOF'
Usage: bash ./launch.sh [--host HOST] [--port PORT] [--no-browser] [--prepare-only] [--skip-install]
EOF
}

write_phase() {
  printf '\n==> %s\n' "$1"
}

get_bootstrap_python() {
  local candidate

  for candidate in python3.11 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
        printf '%s\n' "$candidate"
        return 0
      fi
    fi
  done

  printf 'Python 3.11 or newer is required but was not found on PATH.\n' >&2
  exit 1
}

get_env_file_value() {
  local file_path="$1"
  local name="$2"

  if [ ! -f "$file_path" ]; then
    return 0
  fi

  awk -v key="$name" '
    $0 !~ /^[[:space:]]*#/ && $0 ~ "^[[:space:]]*" key "[[:space:]]*=" {
      sub(/^[[:space:]]*[^=]+=[[:space:]]*/, "", $0)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", $0)
      print
      exit
    }
  ' "$file_path"
}

get_latest_write_time() {
  local latest=0
  local path
  local candidate

  for path in "$@"; do
    if [ ! -e "$path" ]; then
      continue
    fi

    candidate=0
    if [ -d "$path" ]; then
      candidate="$(find "$path" -type f -printf '%T@\n' 2>/dev/null | sort -nr | head -n 1 || true)"
      candidate="${candidate%%.*}"
    else
      candidate="$(stat -c %Y "$path" 2>/dev/null || echo 0)"
    fi

    if [ -z "$candidate" ]; then
      candidate=0
    fi

    if [ "$candidate" -gt "$latest" ]; then
      latest="$candidate"
    fi
  done

  printf '%s\n' "$latest"
}

open_browser_when_ready() {
  local root_url="$1"
  local health_url="${root_url}/healthz"

  if ! command -v curl >/dev/null 2>&1; then
    return 0
  fi

  (
    local attempt
    for attempt in $(seq 1 60); do
      sleep 1
      if curl -fsS --max-time 2 "$health_url" >/dev/null 2>&1; then
        if command -v xdg-open >/dev/null 2>&1; then
          xdg-open "$root_url" >/dev/null 2>&1 || true
        fi
        exit 0
      fi
    done
  ) &
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --port)
      if [ "$#" -lt 2 ]; then
        printf '--port requires a value.\n' >&2
        usage
        exit 1
      fi
      port="$2"
      shift 2
      ;;
    --host)
      if [ "$#" -lt 2 ]; then
        printf '--host requires a value.\n' >&2
        usage
        exit 1
      fi
      bind_host="$2"
      shift 2
      ;;
    --no-browser)
      no_browser=1
      shift
      ;;
    --prepare-only)
      prepare_only=1
      shift
      ;;
    --skip-install)
      skip_install=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown argument: %s\n' "$1" >&2
      usage
      exit 1
      ;;
  esac
done

root_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
backend_dir="$root_dir/backend"
frontend_dir="$root_dir/frontend"
venv_dir="$root_dir/.venv"
venv_python="$venv_dir/bin/python"
backend_install_stamp="$venv_dir/.backend-install.stamp"
frontend_install_stamp="$frontend_dir/node_modules/.install.stamp"
frontend_build_stamp="$frontend_dir/dist/.build.stamp"
backend_env_file="$backend_dir/.env"
frontend_env_file="$frontend_dir/.env"

if [ ! -x "$venv_python" ]; then
  write_phase "Creating Python virtual environment in .venv"
  bootstrap_python="$(get_bootstrap_python)"
  "$bootstrap_python" -m venv "$venv_dir"
fi

if ! "$venv_python" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
  python_version="$($venv_python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  printf 'The virtual environment uses Python %s. Python 3.11 or newer is required.\n' "$python_version" >&2
  exit 1
fi

if [ ! -f "$backend_env_file" ] && [ -f "$backend_dir/.env.example" ]; then
  write_phase "Creating backend/.env from the example file"
  cp "$backend_dir/.env.example" "$backend_env_file"
fi

if [ ! -f "$frontend_env_file" ] && [ -f "$frontend_dir/.env.example" ]; then
  write_phase "Creating frontend/.env from the example file"
  cp "$frontend_dir/.env.example" "$frontend_env_file"
fi

configured_bind_host="$(get_env_file_value "$backend_env_file" "HOST")"
configured_port="$(get_env_file_value "$backend_env_file" "PORT")"

if [ -z "$bind_host" ]; then
  bind_host="${configured_bind_host:-0.0.0.0}"
fi

if [ -z "$port" ]; then
  port="${configured_port:-8000}"
fi

app_url="http://localhost:${port}"

if [ "$skip_install" -eq 0 ]; then
  backend_install_time=0
  if [ -f "$backend_install_stamp" ]; then
    backend_install_time="$(stat -c %Y "$backend_install_stamp")"
  fi

  needs_backend_install=0
  if [ ! -f "$backend_install_stamp" ] || [ "$(stat -c %Y "$backend_dir/pyproject.toml")" -gt "$backend_install_time" ]; then
    needs_backend_install=1
  fi

  if [ "$needs_backend_install" -eq 1 ]; then
    write_phase "Installing backend dependencies into .venv"
    "$venv_python" -m pip install -e "$backend_dir"
    date -u '+%Y-%m-%dT%H:%M:%SZ' > "$backend_install_stamp"
  fi

  frontend_install_time=0
  if [ -f "$frontend_install_stamp" ]; then
    frontend_install_time="$(stat -c %Y "$frontend_install_stamp")"
  fi

  needs_frontend_install=0
  if [ ! -d "$frontend_dir/node_modules" ] || [ ! -f "$frontend_install_stamp" ] || [ "$(stat -c %Y "$frontend_dir/package.json")" -gt "$frontend_install_time" ]; then
    needs_frontend_install=1
  fi

  if [ "$needs_frontend_install" -eq 1 ]; then
    if ! command -v npm >/dev/null 2>&1; then
      printf 'npm is required to install frontend dependencies. Install Node.js 20 or newer.\n' >&2
      exit 1
    fi

    write_phase "Installing frontend dependencies"
    (
      cd "$frontend_dir"
      npm install
    )

    mkdir -p "$frontend_dir/node_modules"
    date -u '+%Y-%m-%dT%H:%M:%SZ' > "$frontend_install_stamp"
  fi
fi

latest_frontend_source="$(get_latest_write_time \
  "$frontend_dir/src" \
  "$frontend_dir/index.html" \
  "$frontend_dir/package.json" \
  "$frontend_dir/tsconfig.json" \
  "$frontend_dir/tsconfig.app.json" \
  "$frontend_dir/tsconfig.node.json" \
  "$frontend_dir/vite.config.ts")"

frontend_build_time=0
if [ -f "$frontend_build_stamp" ]; then
  frontend_build_time="$(stat -c %Y "$frontend_build_stamp")"
fi

needs_frontend_build=0
if [ ! -f "$frontend_dir/dist/index.html" ] || [ "$latest_frontend_source" -gt "$frontend_build_time" ]; then
  needs_frontend_build=1
fi

if [ "$needs_frontend_build" -eq 1 ]; then
  if ! command -v npm >/dev/null 2>&1; then
    printf 'npm is required to build the frontend. Install Node.js 20 or newer.\n' >&2
    exit 1
  fi

  write_phase "Building the frontend bundle"
  (
    cd "$frontend_dir"
    npm run build
  )

  if [ ! -d "$frontend_dir/dist" ]; then
    printf 'Frontend build completed without producing frontend/dist.\n' >&2
    exit 1
  fi

  date -u '+%Y-%m-%dT%H:%M:%SZ' > "$frontend_build_stamp"
fi

export FRONTEND_ORIGIN="$app_url"
export HOST="$bind_host"
export PORT="$port"

write_phase "Prepared TWC Workbench for launch at $app_url"

if [ "$prepare_only" -eq 1 ]; then
  printf 'Preparation completed. Run bash ./launch.sh to start the server.\n'
  exit 0
fi

if [ "$no_browser" -eq 0 ]; then
  open_browser_when_ready "$app_url"
fi

write_phase "Starting the single-origin FastAPI server"
cd "$backend_dir"
exec "$venv_python" -m uvicorn app.main:app --host "$bind_host" --port "$port"