# Provable Milestones

## Overview

Three-week plan to deliver Provable with demo mode and real user mode. Priorities: demo first, then OAuth and scan, then polish.

---

## Week 1: Demo Mode and OAuth Foundation

### Milestone 1.1: Data and Storage Setup

| Task | Priority | Verification |
|------|----------|--------------|
| Create SQLite schema (users, gmail_accounts, receipts, sessions, scan_locks, settings) | Must | Schema applies; WAL mode enabled |
| Enable WAL mode on DB connection | Must | `PRAGMA journal_mode=WAL` returns WAL |
| Set up Railway volume path for PDFs | Must | Path writable at runtime |
| Create /app/storage/demo_exports/ for prebuilt demo ZIPs | Must | Dir exists; writable |

**Acceptance:** Database and volume ready; WAL mode confirmed.

### Milestone 1.2: Demo Mode End-to-End

| Task | Priority | Verification |
|------|----------|--------------|
| Seed demo user and demo receipts in SQLite | Must | Query returns demo receipts |
| Seed demo PDFs at /app/storage/demo/ | Must | Files exist at expected paths |
| Implement POST /demo and session handling | Must | Demo session created; no Gmail API calls |
| Implement GET /receipts for demo user | Must | Returns receipts grouped by month/vendor |
| Implement GET /export/{month} for demo (serve prebuilt ZIP from /app/storage/demo_exports/) | Must | Month regex validated; prebuilt ZIP returned |
| Implement POST /demo/reset (session clear only) | Must | Session cleared; demo data and exports intact |

**Acceptance:** Demo flow works; zero Gmail API calls; demo reset safe.

### Milestone 1.3: Gmail OAuth

| Task | Priority | Verification |
|------|----------|--------------|
| Implement /auth/login (redirect to Google) | Must | Redirects with correct scope |
| Implement /auth/callback with state validation | Must | Rejects invalid state; exchanges code |
| Encrypt refresh token with Fernet; store in gmail_accounts.refresh_token_encrypted | Must | Token not stored in plaintext |
| Create session for real user after OAuth | Must | Session cookie set; user can access receipts |

**Acceptance:** OAuth completes; tokens encrypted; real user session works.

### Week 1 Day-by-Day (Grouped)

| Day | Focus | Tasks |
|-----|-------|-------|
| 1-2 | Setup | Schema, WAL, volume, export dirs, seed script |
| 3 | Demo | Demo mode, /receipts, /export, /demo/reset |
| 4 | OAuth | /auth/login, /auth/callback, token encryption |
| 5 | Integration | End-to-end demo; end-to-end OAuth; fix issues |

---

## Week 2: Scanning and Receipt Detection

### Milestone 2.1: Internal Scan Endpoint

| Task | Priority | Verification |
|------|----------|--------------|
| Implement POST /internal/scan | Must | Returns 200 with {"scanned": N} and returns 401 without X-Cron-Secret (use scanned count for manual testing) |
| Validate X-Cron-Secret header | Must | Wrong/missing secret returns 401 |
| Use scan_locks(id=1,last_run) as a 5 minute gate | Must | Reject if last_run within 5 minutes; prevents overlapping runs by rejecting calls inside the window; single instance; no distributed locking |
| Scan only non-demo accounts with status connected_active; cap 50 accounts per run | Must | Demo users skipped; cap enforced |

**Acceptance:** Cron endpoint protected; scan_locks enforces a 5 minute minimum interval and prevents overlapping runs by rejecting calls within that window.

### Milestone 2.2: Gmail Fetch and Incremental Scan

| Task | Priority | Verification |
|------|----------|--------------|
| Fetch messages from Gmail with date filter | Must | API calls use date range query |
| Apply overlap window to date range | Must | Range extended by N days for edge cases |
| Store last_scan_at per account in gmail_accounts | Must | Next scan starts from last_scan_at - overlap |
| Use short transactions | Must | No long-held locks |

**Acceptance:** Incremental scan works; no duplicate full scans.

### Milestone 2.3: Receipt Detection and Deduplication

| Task | Priority | Verification |
|------|----------|--------------|
| Implement explicit receipt scoring (KNOWN_VENDORS, invoice/receipt, negative terms) | Must | score >= 4 high_confidence; score 3 review queue; score <= 2 skipped |
| Compute SHA256 of PDF before store | Must | Hash stored in receipts |
| Enforce UNIQUE (user_id, file_sha256) | Must | Duplicate file skipped |
| Use Gmail internalDate for receipt date | Must | Date from message, not PDF parse |
| Optional: amount parse for top 3 vendors | Optional | If present, stored in metadata |

**Acceptance:** Only likely receipts stored; no duplicates per user.

### Week 2 Day-by-Day (Grouped)

| Day | Focus | Tasks |
|-----|-------|-------|
| 1 | Internal | POST /internal/scan, X-Cron-Secret, scan_locks rate limit |
| 2-3 | Gmail | Fetch messages, incremental scan, overlap window |
| 4 | Receipts | Scoring, SHA256 dedupe, internalDate |
| 5 | Integration | Full scan cycle; verify deduplication |

---

## Week 3: Polish and Safety

### Milestone 3.1: Real User Export

| Task | Priority | Verification |
|------|----------|--------------|
| Generate ZIP on demand for real users | Must | ZIP contains receipts for month |
| Validate month with regex ^\d{4}-(0[1-9]|1[0-2])$ and parse %Y-%m | Must | Invalid format returns 400 |
| Prevent path traversal in month param | Must | `../` etc. rejected |
| Enforce max_files = 500 per export | Must | Cap applied |
| Enforce max_size_mb = 100 per export | Must | Cap applied |

**Acceptance:** Real export works; validation and caps enforced.

### Milestone 3.2: Disconnect and Cleanup

| Task | Priority | Verification |
|------|----------|--------------|
| Implement POST /auth/disconnect | Must | Revokes token best-effort; deletes real user data |
| Delete user PDF files from volume | Must | Files removed |
| Delete user rows from receipts, gmail_accounts, and users | Must | DB cleaned |
| Clear session | Must | User logged out |

**Acceptance:** Disconnect removes all user data; session cleared.

### Milestone 3.3: Demo Script and Prebuild

| Task | Priority | Verification |
|------|----------|--------------|
| Prebuild demo export ZIPs at /app/storage/demo_exports/{month}.zip | Must | ZIPs exist for demo months |
| Deploy script seeds DB and files | Must | Idempotent; safe to re-run |
| Verify POST /demo/reset never deletes seeded data or demo exports | Must | Reset clears session only |

**Acceptance:** Deploy produces working demo; reset safe.

### Week 3 Day-by-Day (Grouped)

| Day | Focus | Tasks |
|-----|-------|-------|
| 1 | Export | Real user ZIP, validation, caps |
| 2 | Disconnect | Revoke, delete files, delete rows |
| 3 | Deploy | Prebuild exports, seed script, idempotency |
| 4-5 | QA | End-to-end demo; end-to-end real user; edge cases |

---

## Priority Summary

| Priority | Items |
|----------|-------|
| Must | All demo mode, OAuth, scan, dedupe, export, disconnect, security |
| Optional | Amount parsing for top 3 vendors |

---

## Risk List

| Risk | Mitigation |
|------|------------|
| Gmail API quota during demo | Demo mode never calls Gmail; pre-seeded data only |
| Cron endpoint exposed | Require X-Cron-Secret; fail closed on missing/wrong |
| Scan lock deadlock | Use short transactions; timeout on lock acquire |
| Demo reset deletes demo data | Explicit guard: reset only clears session; never DELETE demo rows/files |
| Path traversal in export | Regex ^\d{4}-(0[1-9]|1[0-2])$; reject path traversal |
