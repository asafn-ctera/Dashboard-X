# Dashboard-X

Local web dashboard for viewing and managing vSphere VMs.

## Quick Start

```bash
pip install -r requirements.txt
cp config.yaml.example config.yaml   # set vCenter server + folders
python3 run.py                        # opens http://localhost:8585
```

On first launch (or when disconnected), the UI prompts for vSphere username/password.
Credentials are saved encrypted locally on your machine.

## Configuration

Edit `config.yaml` to set your vCenter connection details and which VM folders to monitor:

```yaml
vsphere:
  server: "vc.ctera.local"
  user: ""        # optional, can be provided via login modal
  password: ""    # optional, can be provided via login modal
  allow_unverified_ssl: true

folders:
  - "Technical Teams/Engineering/AsafN"
  - "Technical Teams/Engineering/Portal Sandbox/AsafN"

dashboard:
  port: 8585
  cache_ttl_seconds: 60
  connect_url_scheme: "https"
```

## Project Structure

```
app/
  main.py              FastAPI application
  config.py            YAML config loader
  vsphere_client.py    pyVmomi vSphere connection & queries
  models.py            Pydantic data models
  routers/vms.py       /api/vms endpoints
static/
  index.html           Dashboard UI
  css/style.css        Styles
  js/app.js            Frontend logic
scripts/               Jenkins CLI tools (independent)
```

## API

- `GET /api/auth/status` — authentication/connectivity status
- `POST /api/auth/login` — connect with username/password and save encrypted credentials
- `GET /api/vms` — list all VMs (optional `?folder=...&refresh=true`)
- `GET /api/folders` — VMs grouped by folder
- `GET /api/status` — connection health check
- Interactive docs at `/docs` (FastAPI auto-generated)

## Docker

Build and run with Docker Compose:

```bash
docker compose up -d --build
```

Then open `http://localhost:8585`.

Notes:
- Mounts `./config.yaml` into the container for server/folder config.
- Stores encrypted credentials in `./.dashboard-x-data` on host.
