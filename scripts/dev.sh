#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

dotenv_value() {
  local key="$1"
  local fallback="$2"
  local configured="${!key:-}"
  local line

  if [[ -n "${configured}" ]]; then
    printf '%s\n' "${configured}"
    return
  fi

  if [[ -f "${PROJECT_ROOT}/.env" ]]; then
    line="$(grep -E "^${key}=" "${PROJECT_ROOT}/.env" | tail -n 1 || true)"
    if [[ -n "${line}" ]]; then
      configured="${line#*=}"
      if [[ "${configured}" == \"*\" && "${configured}" == *\" ]]; then
        configured="${configured:1:${#configured}-2}"
      elif [[ "${configured}" == \'*\' && "${configured}" == *\' ]]; then
        configured="${configured:1:${#configured}-2}"
      fi
      printf '%s\n' "${configured}"
      return
    fi
  fi

  printf '%s\n' "${fallback}"
}

project_path() {
  local configured="$1"
  if [[ "${configured}" == /* ]]; then
    printf '%s\n' "${configured}"
  else
    printf '%s/%s\n' "${PROJECT_ROOT}" "${configured}"
  fi
}

RUNTIME_DIR="${PROJECT_ROOT}/.runtime"
BACKEND_PID_FILE="${RUNTIME_DIR}/backend.pid"
FRONTEND_PID_FILE="${RUNTIME_DIR}/frontend.pid"
BACKEND_LOG="${RUNTIME_DIR}/backend.log"
FRONTEND_LOG="${RUNTIME_DIR}/frontend.log"
BACKEND_HOST="$(dotenv_value DEV_BACKEND_HOST 0.0.0.0)"
BACKEND_PORT="$(dotenv_value DEV_BACKEND_PORT 8000)"
BACKEND_HEALTH_URL="$(dotenv_value DEV_BACKEND_HEALTH_URL "http://localhost:${BACKEND_PORT}/health")"
FRONTEND_HOST="$(dotenv_value DEV_FRONTEND_HOST 0.0.0.0)"
FRONTEND_PORT="$(dotenv_value DEV_FRONTEND_PORT 5173)"
FRONTEND_URL="$(dotenv_value DEV_FRONTEND_URL "http://localhost:${FRONTEND_PORT}")"
POSTGRES_CONTAINER="$(dotenv_value SHARED_POSTGRES_CONTAINER postgresql-for-all-projects)"
POSTGRES_COMPOSE="$(project_path "$(dotenv_value SHARED_POSTGRES_COMPOSE ../shared-postgresql/docker-compose.yml)")"
JAEGER_CONTAINER="$(dotenv_value SHARED_JAEGER_CONTAINER jaeger-for-all-projects)"
JAEGER_COMPOSE="$(project_path "$(dotenv_value SHARED_JAEGER_COMPOSE ../shared-observability/compose.yaml)")"
JAEGER_VOLUME="$(dotenv_value SHARED_JAEGER_VOLUME jaeger-for-all-projects-data)"
JAEGER_UI_URL="$(dotenv_value SHARED_JAEGER_UI_URL http://localhost:16686)"

log() {
  printf '[dev] %s\n' "$*"
}

fail() {
  printf '[dev] ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage: scripts/dev.sh <start|restart|stop|status|database>

  start    Start shared infrastructure if needed, apply migrations, and start
           missing application services.
  restart  Stop this project's application services, then start everything.
  stop     Stop this project's backend and frontend. Shared infrastructure stays up.
  status   Show shared infrastructure and application service status.
  database Start only the configured shared PostgreSQL service.
EOF
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

port_in_use() {
  local port="$1"
  ss -ltnH "sport = :${port}" 2>/dev/null | grep -q .
}

process_matches_directory() {
  local pid="$1"
  local expected_directory="$2"
  local process_directory

  process_directory="$(readlink -f "/proc/${pid}/cwd" 2>/dev/null || true)"
  [[ "${process_directory}" == "${expected_directory}" || "${process_directory}" == "${expected_directory}/"* ]]
}

managed_pid() {
  local pid_file="$1"
  local expected_directory="$2"
  local pid

  [[ -f "${pid_file}" ]] || return 1
  read -r pid < "${pid_file}" || return 1
  [[ "${pid}" =~ ^[0-9]+$ ]] || return 1
  kill -0 "${pid}" 2>/dev/null || return 1
  process_matches_directory "${pid}" "${expected_directory}" || return 1
  printf '%s\n' "${pid}"
}

listener_pids() {
  local port="$1"
  fuser -n tcp "${port}" 2>/dev/null || true
}

wait_for_url() {
  local name="$1"
  local url="$2"
  local attempts="${3:-40}"

  for ((attempt = 1; attempt <= attempts; attempt += 1)); do
    if curl --fail --silent --show-error "${url}" >/dev/null 2>&1; then
      log "${name} is ready at ${url}"
      return 0
    fi
    sleep 0.5
  done

  return 1
}

wait_for_container() {
  local container="$1"

  for ((attempt = 1; attempt <= 40; attempt += 1)); do
    local running
    local health
    running="$(docker inspect --format '{{.State.Running}}' "${container}" 2>/dev/null || true)"
    health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "${container}" 2>/dev/null || true)"
    if [[ "${running}" == "true" && ("${health}" == "healthy" || "${health}" == "none") ]]; then
      log "${container} is ready"
      return 0
    fi
    sleep 0.5
  done

  fail "Container did not become ready: ${container}"
}

ensure_postgres() {
  require_command docker
  docker info >/dev/null 2>&1 || fail "Docker is not reachable. Start Docker Desktop and enable WSL integration."

  if docker container inspect "${POSTGRES_CONTAINER}" >/dev/null 2>&1; then
    if [[ "$(docker inspect --format '{{.State.Running}}' "${POSTGRES_CONTAINER}")" != "true" ]]; then
      log "Starting ${POSTGRES_CONTAINER}"
      docker start "${POSTGRES_CONTAINER}" >/dev/null
    else
      log "${POSTGRES_CONTAINER} is already running"
    fi
  elif [[ -f "${POSTGRES_COMPOSE}" ]]; then
    log "Creating ${POSTGRES_CONTAINER} from the shared PostgreSQL project"
    docker compose -f "${POSTGRES_COMPOSE}" up -d
  else
    fail "PostgreSQL container is missing and ${POSTGRES_COMPOSE} was not found"
  fi
  wait_for_container "${POSTGRES_CONTAINER}"
}

ensure_jaeger() {
  [[ -f "${JAEGER_COMPOSE}" ]] || fail "Shared Jaeger configuration not found: ${JAEGER_COMPOSE}"
  if ! docker volume inspect "${JAEGER_VOLUME}" >/dev/null 2>&1; then
    log "Creating persistent Jaeger trace volume"
    docker volume create "${JAEGER_VOLUME}" >/dev/null
  fi
  log "Ensuring ${JAEGER_CONTAINER} is running"
  docker compose -f "${JAEGER_COMPOSE}" up -d
  wait_for_url "Jaeger" "${JAEGER_UI_URL}"
}

ensure_infrastructure() {
  ensure_postgres
  ensure_jaeger
}

run_migrations() {
  log "Applying database migrations"
  (
    cd "${PROJECT_ROOT}/backend"
    uv run alembic upgrade head
  )
}

start_service() {
  local name="$1"
  local directory="$2"
  local port="$3"
  local pid_file="$4"
  local log_file="$5"
  shift 5

  local pid
  if pid="$(managed_pid "${pid_file}" "${directory}")"; then
    log "${name} is already running (PID ${pid})"
    return 0
  fi
  rm -f "${pid_file}"

  if port_in_use "${port}"; then
    log "${name} is already listening on port ${port} outside this launcher"
    return 0
  fi

  mkdir -p "${RUNTIME_DIR}"
  log "Starting ${name}; log: ${log_file}"
  (
    cd "${directory}"
    exec setsid "$@" >>"${log_file}" 2>&1 </dev/null
  ) &
  pid=$!
  printf '%s\n' "${pid}" > "${pid_file}"
}

stop_managed_service() {
  local name="$1"
  local directory="$2"
  local pid_file="$3"
  local pid

  if ! pid="$(managed_pid "${pid_file}" "${directory}")"; then
    rm -f "${pid_file}"
    return 0
  fi

  log "Stopping ${name} (PID ${pid})"
  kill -TERM -- "-${pid}" 2>/dev/null || kill -TERM "${pid}" 2>/dev/null || true
  for ((attempt = 1; attempt <= 40; attempt += 1)); do
    if ! kill -0 "${pid}" 2>/dev/null; then
      rm -f "${pid_file}"
      return 0
    fi
    sleep 0.25
  done

  log "${name} did not stop cleanly; terminating its managed process group"
  kill -KILL -- "-${pid}" 2>/dev/null || kill -KILL "${pid}" 2>/dev/null || true
  rm -f "${pid_file}"
}

stop_unmanaged_project_service() {
  local name="$1"
  local directory="$2"
  local port="$3"
  local expected_pattern="$4"
  local raw_pids
  local pid
  local process_command
  local pgid
  local current_pgid
  local expected_process_found=false
  local -a process_groups=()

  port_in_use "${port}" || return 0
  raw_pids="$(listener_pids "${port}")"
  [[ -n "${raw_pids//[[:space:]]/}" ]] || fail "Port ${port} is in use, but its process could not be identified"

  for pid in ${raw_pids}; do
    process_matches_directory "${pid}" "${directory}" ||
      fail "Refusing to stop PID ${pid} on port ${port}; it is not running from ${directory}"
    process_command="$(tr '\0' ' ' < "/proc/${pid}/cmdline" 2>/dev/null || true)"
    if [[ "${process_command}" =~ ${expected_pattern} ]]; then
      expected_process_found=true
    fi
    pgid="$(ps -o pgid= -p "${pid}" | tr -d ' ')"
    [[ -n "${pgid}" ]] && process_groups+=("${pgid}")
  done

  [[ "${expected_process_found}" == "true" ]] ||
    fail "Refusing to stop port ${port}; no listener looks like the ${name} service"

  current_pgid="$(ps -o pgid= -p "$$" | tr -d ' ')"
  mapfile -t process_groups < <(printf '%s\n' "${process_groups[@]}" | sort -u)
  for pgid in "${process_groups[@]}"; do
    [[ "${pgid}" != "${current_pgid}" ]] || fail "Refusing to stop the launcher's own process group"
    log "Stopping previously launched ${name} process group ${pgid}"
    kill -TERM -- "-${pgid}"
  done

  for ((attempt = 1; attempt <= 40; attempt += 1)); do
    port_in_use "${port}" || return 0
    sleep 0.25
  done
  fail "${name} did not release port ${port}; inspect it before retrying"
}

stop_services() {
  stop_managed_service "frontend" "${PROJECT_ROOT}/frontend" "${FRONTEND_PID_FILE}"
  stop_managed_service "backend" "${PROJECT_ROOT}/backend" "${BACKEND_PID_FILE}"
  stop_unmanaged_project_service "frontend" "${PROJECT_ROOT}/frontend" "${FRONTEND_PORT}" 'vite|npm.*run.*dev'
  stop_unmanaged_project_service "backend" "${PROJECT_ROOT}/backend" "${BACKEND_PORT}" 'uvicorn.*app\.main:app'
  log "Application services are stopped; shared PostgreSQL and Jaeger remain running"
}

start_services() {
  require_command uv
  require_command npm
  require_command setsid
  require_command ss
  require_command fuser
  require_command curl

  [[ -d "${PROJECT_ROOT}/frontend/node_modules" ]] ||
    fail "Frontend dependencies are missing. Run: npm --prefix frontend install"

  start_service \
    "backend" "${PROJECT_ROOT}/backend" "${BACKEND_PORT}" "${BACKEND_PID_FILE}" "${BACKEND_LOG}" \
    env -u OPENAI_API_KEY uv run uvicorn app.main:app --reload --host "${BACKEND_HOST}" --port "${BACKEND_PORT}"
  if ! wait_for_url "Backend" "${BACKEND_HEALTH_URL}"; then
    tail -n 40 "${BACKEND_LOG}" >&2 || true
    fail "Backend failed to become ready"
  fi

  start_service \
    "frontend" "${PROJECT_ROOT}/frontend" "${FRONTEND_PORT}" "${FRONTEND_PID_FILE}" "${FRONTEND_LOG}" \
    npm run dev -- --host "${FRONTEND_HOST}" --port "${FRONTEND_PORT}"
  if ! wait_for_url "Frontend" "${FRONTEND_URL}"; then
    tail -n 40 "${FRONTEND_LOG}" >&2 || true
    fail "Frontend failed to become ready"
  fi
}

container_status() {
  local name="$1"
  local state
  state="$(docker inspect --format '{{if .State.Running}}running{{else}}stopped{{end}}' "${name}" 2>/dev/null || true)"
  printf '  %-32s %s\n' "${name}" "${state:-missing}"
}

service_status() {
  local name="$1"
  local directory="$2"
  local port="$3"
  local pid_file="$4"
  local pid

  if pid="$(managed_pid "${pid_file}" "${directory}")"; then
    printf '  %-32s running (managed PID %s)\n' "${name}" "${pid}"
  elif port_in_use "${port}"; then
    printf '  %-32s running (external PID%s: %s)\n' "${name}" "$(listener_pids "${port}" | wc -w | tr -d ' ')" "$(listener_pids "${port}")"
  else
    printf '  %-32s stopped\n' "${name}"
  fi
}

show_status() {
  printf 'Infrastructure:\n'
  if docker info >/dev/null 2>&1; then
    container_status "${POSTGRES_CONTAINER}"
    container_status "${JAEGER_CONTAINER}"
  else
    printf '  %-32s unavailable\n' "Docker"
  fi
  printf 'Application:\n'
  service_status "backend :${BACKEND_PORT}" "${PROJECT_ROOT}/backend" "${BACKEND_PORT}" "${BACKEND_PID_FILE}"
  service_status "frontend :${FRONTEND_PORT}" "${PROJECT_ROOT}/frontend" "${FRONTEND_PORT}" "${FRONTEND_PID_FILE}"
  printf 'Logs:\n'
  printf '  %s\n  %s\n' "${BACKEND_LOG}" "${FRONTEND_LOG}"
}

start_all() {
  ensure_infrastructure
  run_migrations
  start_services
  show_status
}

case "${1:-}" in
  start)
    start_all
    ;;
  restart)
    stop_services
    start_all
    ;;
  stop)
    stop_services
    show_status
    ;;
  status)
    require_command docker
    require_command ss
    require_command fuser
    show_status
    ;;
  database)
    ensure_postgres
    ;;
  *)
    usage
    exit 2
    ;;
esac
