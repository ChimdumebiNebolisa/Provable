# Provable Milestones

## Overview

Three-week plan to deliver Provable with demo mode and real user mode. Priorities: demo first, then OAuth and scan, then polish.

---

## Week 1: Demo Mode and OAuth Foundation

### Milestone 1.1: Data and Storage Setup

| Task | Priority | Verification |
|------|----------|--------------|
| Create SQLite schema (users, gmail_accounts, receipts, sessions, settings) | Must | Schema applies; WAL mode enabled |
| Add scan state fields on gmail_accounts (scan_in_progress, last_scan_at, last_scan_error optional) | Must | Fields present; usable for scan gating/status |
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
| Enforce one Gmail account per user (DB UNIQUE(user_id) or code guard) | Must | Second link attempt rejected or replaced deterministically |

**Acceptance:** OAuth completes; tokens encrypted; real user session works; one Gmail account per user enforced.

### Week 1 Day-by-Day (Grouped)

| Day | Focus | Tasks |
|-----|-------|-------|
| 1-2 | Setup | Schema, WAL, volume, export dirs, seed script |
| 3 | Demo | Demo mode, /receipts, /export, /demo/reset |
| 4 | OAuth | /auth/login, /auth/callback, token encryption |
| 5 | Integration | End-to-end demo; end-to-end OAuth; fix issues |

---

## Week 2: Scanning and Receipt Detection

### Milestone 2.1: Scan Triggering and Guarding (Session)

| Task | Priority | Verification |
|------|----------|--------------|
| Implement POST /scan (Session) to scan last N days for current user connected Gmail account | Must | Authenticated call triggers scan and returns scan outcome |
| Optional: implement GET /scan/status (Session) for current scan state | Optional | Returns current user scan status (idle/running/last outcome) when implemented |
| Implement per-user scan guard (DB flag or in-memory) to prevent concurrent scans | Must | Second scan while active returns 409 or 429 with clear message |
| Optional: add per-user scan rate limit (e.g., 1 scan per 2 minutes) if easy | Optional | Rapid repeated calls are throttled when enabled |
| Implement auto-scan on connect (OAuth callback kicks off scan) | Must | First real account link triggers scan automatically |
| Implement auto-scan on open if stale (e.g., on /receipts or app load) | Must | If `last_scan_at` older than `STALE_THRESHOLD`, scan is triggered |

**Acceptance:** Manual Scan Now works end-to-end; second scan request during active scan is rejected; auto-scan runs on connect and on open when stale.

### Milestone 2.2: Gmail Fetch (Fixed Window)

| Task | Priority | Verification |
|------|----------|--------------|
| Fetch messages from Gmail using fixed date filter (last 30 or 60 days) | Must | API calls always use fixed window query |
| Use Gmail internalDate for receipt_date | Must | Stored receipt dates come from Gmail internalDate |
| Store last_scan_at at end of scan | Must | `last_scan_at` updates on successful scan completion |
| Use short transactions | Must | No long-held locks |

**Acceptance:** Queries use fixed window; `last_scan_at` updates correctly.

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
| 1 | Scan API | POST /scan (Session), per-user scan guard, optional rate limit |
| 2-3 | Triggers + Gmail | Auto-scan on connect, auto-scan on open if stale, fixed-window fetch |
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
| Implement POST /auth/disconnect | Must | Deletes real user data and clears session |
| Optional: revoke token best-effort (if time) | Optional | Revoke attempted when configured; failures do not block cleanup |
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
| 2 | Disconnect | Delete files, delete rows, clear session; optional revoke |
| 3 | Deploy | Prebuild exports, seed script, idempotency |
| 4-5 | QA | End-to-end demo; end-to-end real user; edge cases |

---

## Priority Summary

| Priority | Items |
|----------|-------|
| Must | All demo mode, OAuth, one-Gmail-account enforcement, /scan triggers, scan guard + stale gating, fixed-window fetch, dedupe, export, disconnect cleanup |
| Optional | Amount parsing for top 3 vendors |

---

## Risk List

| Risk | Mitigation |
|------|------------|
| Gmail API quota during demo | Demo mode never calls Gmail; pre-seeded data only |
| OAuth consent screen / redirect URI misconfig | Demo mode unaffected; maintain test user list; use single stable callback URI |
| Long scan blocks request | Run scan as background job where possible or show UI loading state; fixed window reduces scan time |
| Repeated auto-scan loops | Enforce stale threshold gating and `scan_in_progress` guard |
| Demo reset deletes demo data | Explicit guard: reset only clears session; never DELETE demo rows/files |
| Path traversal in export | Regex ^\d{4}-(0[1-9]|1[0-2])$; reject path traversal |
