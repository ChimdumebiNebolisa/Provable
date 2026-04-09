# Provable

Provable collects receipt attachments from Gmail and organizes them by month and vendor.

The app supports two modes:

- Demo mode with zero Gmail API calls
- Real user mode with Gmail OAuth, encrypted refresh-token storage, scan triggers, and ZIP export

This repository implements the MVP defined by [guardrails.md](guardrails.md), [spec.md](spec.md), and [milestones.md](milestones.md).

## Stack

- Python 3.11
- Flask
- SQLite in WAL mode
- Local disk storage for PDFs and prebuilt demo exports

## Implemented Scope

- Demo session flow
- Seeded demo receipts and seeded demo PDF files
- Prebuilt demo ZIP exports
- Gmail OAuth with state validation
- Fernet encryption for refresh tokens before database insert
- Fixed-window Gmail scan
- Explicit receipt scoring
- File-level SHA256 deduplication per user
- Real-user ZIP export with file-count and size caps
- Disconnect cleanup for user rows and stored files

## Project Layout

```text
provable/
  app.py
  bootstrap.py
  config.py
  db.py
  demo_seed.py
  deploy.py
  exporter.py
  gmail.py
  gmail_scan.py
  oauth.py
  routes.py
  scan.py
  session_store.py
  storage.py
  validators.py
tests/
run.py
```

## Quick Start

### 1. Install

```powershell
cd C:\Users\Chimdumebi\Provable
python -m pip install -e ".[dev]"
```

### 2. Demo-safe local environment

Demo mode does not require Google credentials.

```powershell
$env:PROVABLE_ENV="development"
$env:PROVABLE_SECRET_KEY="dev-secret"
```

### 3. Bootstrap storage and seed demo data

```powershell
python -m provable.deploy
```

Expected result:

- SQLite database is created
- WAL mode is enabled
- demo receipts are seeded
- demo PDFs are written under local storage
- prebuilt demo ZIPs are written under local storage

### 4. Run the app

```powershell
python run.py
```

The app starts on `http://127.0.0.1:5000` by default.

Optional runner variables:

```powershell
$env:PROVABLE_HOST="127.0.0.1"
$env:PROVABLE_PORT="5000"
$env:PROVABLE_DEBUG="1"
```

## Automated Testing

Run the full test suite:

```powershell
pytest -q
```

Current local verification target:

- bootstrap and WAL mode
- demo flow
- OAuth flow with test doubles
- scan triggering and guards
- Gmail fetch logic with test doubles
- scoring and deduplication
- export
- disconnect cleanup
- deploy bootstrap
- landing page

## Manual Demo Testing

1. Start the app with `python run.py`
2. Open `http://127.0.0.1:5000`
3. Click `Enter Demo`
4. Confirm receipts load immediately
5. Download `http://127.0.0.1:5000/export/2024-01`
6. Reset the session with `POST /demo/reset`
7. Confirm receipts require a new session after reset
8. Confirm demo ZIPs still exist under storage after reset

## Real Gmail Testing

Real Gmail testing requires Google Cloud OAuth configuration.

### Required environment variables

```powershell
$env:GOOGLE_CLIENT_ID="your-client-id"
$env:GOOGLE_CLIENT_SECRET="your-client-secret"
$env:GOOGLE_REDIRECT_URI="http://127.0.0.1:5000/auth/callback"
$env:FERNET_KEY=(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
```

### Google Cloud requirements

- Gmail API enabled
- OAuth consent screen configured
- Testing mode enabled
- your Gmail address added as a test user
- redirect URI set to `http://127.0.0.1:5000/auth/callback`

### Manual real-user flow

1. Start the app
2. Open `/`
3. Click `Connect Gmail`
4. Complete OAuth
5. Confirm connect triggers an initial scan
6. Check `/scan/status`
7. Open `/receipts` and confirm scanned receipts appear
8. Trigger `POST /scan` and confirm overlap protection works
9. Download `/export/YYYY-MM`
10. Trigger `POST /auth/disconnect`
11. Confirm session clears and local user files are removed

## Endpoint Summary

| Method | Path | Purpose |
|------|------|------|
| GET | `/` | Landing page with mode selection |
| POST | `/demo` | Start demo session |
| POST | `/demo/reset` | Clear demo session only |
| GET | `/auth/login` | Start Google OAuth |
| GET | `/auth/callback` | OAuth callback with state validation |
| POST | `/auth/disconnect` | Delete real-user data and clear session |
| GET | `/receipts` | List current user receipts |
| POST | `/scan` | Trigger scan for the connected real user |
| GET | `/scan/status` | View current scan status |
| GET | `/export/<month>` | Download demo or real-user ZIP export |
| GET | `/health` | Health check |

## Storage

Production contract paths:

- `/app/storage/demo/`
- `/app/storage/demo_exports/`
- `/app/storage/users/<user_id>/...`

In local development, the app defaults to the repo-local `storage/` directory when `PROVABLE_ENV=development`.

## Important Guardrails Enforced

- Demo mode makes zero Gmail API calls
- Demo exports are served from prebuilt ZIP files
- Demo reset clears session only
- OAuth state is validated
- Refresh tokens are encrypted before insert
- `/scan` is session protected
- month validation uses strict regex and traversal rejection
- session cookies are `HttpOnly`, `SameSite=Lax`, and `Secure` in production
- deduplication is file-level SHA256 per user
- disconnect deletes user rows and user files
- Gmail failures return explicit error responses and never fall back to demo
- scan error handling clears `scan_in_progress` and records error status

## Useful Commands

```powershell
python -m provable.bootstrap
python -m provable.demo_seed
python -m provable.deploy
pytest -q
python run.py
```
