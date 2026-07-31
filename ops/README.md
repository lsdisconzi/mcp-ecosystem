# Ops-Dashboard — Service Monitoring & Control

> **Awareness-AI Ecosystem** · Flask · Port 9000 · Localhost Only

## Overview

Lightweight Flask dashboard for monitoring and controlling all Awareness-AI
platform services. Provides system metrics, service health checks, container
management (start/stop/restart), log viewing, nginx status, and project
file browsing — all behind a login gate.

## Features

- **System Info** — CPU, memory, disk, uptime
- **Service Registry** — health status for all 9 platform services
- **Container Control** — start, stop, restart via Docker API
- **Log Viewer** — tail container logs per service
- **Project Browser** — list key files for each project
- **Nginx Status** — reverse proxy health check

## Service Registry

| Service | Port | Type |
|---------|------|------|
| api-gateway | 80/443 | infra |
| ibsco | 8011 | app |
| garage-api | 8066 | app |
| argus | 8029 | app |
| manus | 8078 | app |
| legal | 8019 | app |
| qdrant | 6333 | data |
| certbot | — | infra |
| ollama | 11436 | infra |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET/POST | `/ops-login` | Dashboard login |
| GET | `/` | Dashboard index |
| GET | `/api/system` | System metrics (CPU, memory, disk) |
| GET | `/api/services` | All service statuses |
| GET | `/api/services/<svc>/logs` | Container logs |
| POST | `/api/services/<svc>/restart` | Restart container |
| POST | `/api/services/<svc>/stop` | Stop container |
| POST | `/api/services/<svc>/start` | Start container |
| GET | `/api/projects` | Project file listings |
| GET | `/api/nginx/status` | Nginx health |

## Quick Start

```bash
cd ops
pip install flask psutil docker
export OPS_PROJECT_ROOT=/awareness/ops
python app.py
# → http://localhost:9000
```

Login with `OPS_CODE` environment variable (default: `awareness-ops-2026`).

## Deployment

A systemd unit file is included:

```bash
cp ops-dashboard.service /etc/systemd/system/
systemctl enable --now ops-dashboard
```

## Environment Variables

```bash
OPS_SECRET=...              # Flask session secret
OPS_CODE=awareness-ops-2026 # Dashboard access code
```

---

*Awareness-AI · Ops Dashboard · Service Monitoring · 2026*
# ops
