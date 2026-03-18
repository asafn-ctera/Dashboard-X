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

## Security

Dashboard-X stores secrets in an encrypted local credential store, not in plaintext
`config.yaml`.

- **Store location (default):**
  - `~/.dashboard-x/credentials.enc` (encrypted payload)
  - `~/.dashboard-x/secret.key` (encryption key)
- **Custom location:** set `VSPHERE_DASH_DATA_DIR` to override the base directory.
- **Payload format:** a single encrypted JSON object with service entries, e.g.
  `vsphere.username/password` and `jenkins.user/token`.
- **Encryption primitive:** `cryptography.fernet.Fernet`, which provides authenticated
  encryption (AES-128-CBC + HMAC-SHA256, with versioning and timestamp in the token).
- **File permissions:** the app attempts to set owner-only permissions (`chmod 600`)
  for the key and encrypted credential files.
- **Migration behavior:**
  - If plaintext secrets are found in `config.yaml`, they are migrated into the
    encrypted store.
  - After migration, secrets are scrubbed from `config.yaml`.
  - Jenkins secrets from `~/.jenkins-config` are also migrated into the encrypted
    store when available.

Security note: because the key is stored locally on the same machine (in a separate
file), this protects against accidental plaintext exposure and source-control leaks,
but does not replace host-level security controls (OS account hardening, disk
encryption, endpoint protection, etc.).

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

## Jenkins Integration

Dashboard-X can trigger and monitor Jenkins builds. This requires a personal API token.

### Generating a Jenkins API Token

1. Log in to [jenkins.ctera.dev](https://jenkins.ctera.dev)
2. Go to **your user profile** → **Configure** (or visit `https://jenkins.ctera.dev/me/configure` directly)
3. Scroll to the **API Token** section
4. Click **Add new Token**, give it a name (e.g. `dashboard-x`), and click **Generate**
5. Copy the token immediately — it won't be shown again

### Providing the Token

You can provide Jenkins credentials in any of these ways (checked in order):

| Method | Details |
|---|---|
| **Encrypted store** (preferred) | Saved automatically after first successful use via the UI or any method below |
| **`config.yaml`** | Set `jenkins.user` and `jenkins.token` — they'll be migrated to the encrypted store and scrubbed from the file on next launch |
| **`~/.jenkins-config`** | A simple dotfile with `JENKINS_USER="..."` and `JENKINS_TOKEN="..."` — also migrated on first launch |

All credentials end up encrypted in `~/.dashboard-x/credentials.enc` (Fernet AES-128-CBC + HMAC-SHA256), the same store used for vSphere credentials.

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
