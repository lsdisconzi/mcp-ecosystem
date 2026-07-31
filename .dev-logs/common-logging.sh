#!/usr/bin/env bash
# common-logging.sh — Shared logging utilities for mcp-ecosystem
# Source this file in start.sh/stop.sh scripts: source "$ROOT/.dev-logs/common-logging.sh"

# Centralized log directory at root of mcp-ecosystem
DEV_LOGS_ROOT="${DEV_LOGS_ROOT:-/Users/dev/_sell/mcp-ecosystem/.dev-logs}"

# Ensure log directory exists
mkdir -p "$DEV_LOGS_ROOT"

# Get a log file path for a specific project
# Usage: get_log_file "project-name" "service-name"
get_log_file() {
    local project="$1"
    local service="${2:-main}"
    local timestamp=$(date '+%Y-%m-%d')
    echo "$DEV_LOGS_ROOT/${project}-${service}-${timestamp}.log"
}

# Get a PID file path for a specific project
# Usage: get_pid_file "project-name" "service-name"
get_pid_file() {
    local project="$1"
    local service="${2:-main}"
    echo "$DEV_LOGS_ROOT/${project}-${service}.pid"
}

# Log with timestamp to both stdout and log file
# Usage: log "project" "service" "message"
log() {
    local project="$1"
    local service="$2"
    local message="$3"
    local log_file=$(get_log_file "$project" "$service")
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] [$project:$service] $message" | tee -a "$log_file"
}

# Log info level
log_info() { log "$1" "$2" "INFO: $3"; }

# Log warning level
log_warn() { log "$1" "$2" "WARN: $3"; }

# Log error level
log_error() { log "$1" "$2" "ERROR: $3"; }

# Log success
log_ok() { log "$1" "$2" "OK: $3"; }

# Start logging a process output to log file
# Usage: start_logging "project" "service" "command" [args...]
start_logging() {
    local project="$1"
    local service="$2"
    shift 2
    local log_file=$(get_log_file "$project" "$service")
    local pid_file=$(get_pid_file "$project" "$service")

    # Run command with output to log file
    "$@" >>"$log_file" 2>&1 &
    local pid=$!
    echo $pid > "$pid_file"
    log_info "$project" "$service" "Started PID $pid, logging to $log_file"
    echo $pid
}

# Stop a process by PID file
# Usage: stop_by_pid_file "project" "service"
stop_by_pid_file() {
    local project="$1"
    local service="$2"
    local pid_file=$(get_pid_file "$project" "$service")

    if [[ -f "$pid_file" ]]; then
        local pid=$(cat "$pid_file" 2>/dev/null)
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null
            sleep 0.5
            if kill -0 "$pid" 2>/dev/null; then
                kill -9 "$pid" 2>/dev/null
                log_warn "$project" "$service" "Force killed PID $pid"
            else
                log_ok "$project" "$service" "Stopped PID $pid"
            fi
        fi
        rm -f "$pid_file"
    else
        log_warn "$project" "$service" "No PID file found at $pid_file"
    fi
}

# Kill process on port
# Usage: kill_port "project" "service" "port"
kill_port() {
    local project="$1"
    local service="$2"
    local port="$3"
    local pids=$(lsof -ti :"$port" 2>/dev/null || true)
    if [[ -n "$pids" ]]; then
        log_warn "$project" "$service" "Killing processes on port $port: $pids"
        kill $pids 2>/dev/null || true
        sleep 0.5
        local remaining=$(lsof -ti :"$port" 2>/dev/null || true)
        if [[ -n "$remaining" ]]; then
            kill -9 $remaining 2>/dev/null || true
            log_warn "$project" "$service" "Force killed remaining on port $port: $remaining"
        else
            log_ok "$project" "$service" "Freed port $port"
        fi
    fi
}

# Rotate logs older than N days
# Usage: rotate_logs "project" "service" [days]
rotate_logs() {
    local project="$1"
    local service="$2"
    local days="${3:-7}"
    find "$DEV_LOGS_ROOT" -name "${project}-${service}-*.log" -mtime +$days -delete 2>/dev/null || true
    log_info "$project" "$service" "Rotated logs older than $days days"
}

# Export functions for use in sourced scripts
export -f get_log_file get_pid_file log log_info log_warn log_error log_ok
export -f start_logging stop_by_pid_file kill_port rotate_logs
export DEV_LOGS_ROOT