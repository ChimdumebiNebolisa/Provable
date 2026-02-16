# Provable Guardrails

## Purpose

Non-negotiable rules for demo reliability, data safety, correctness, and scope. All implementation must comply with these guardrails.

---

## Demo Guardrails

| Rule | Mechanism |
|------|-----------|
| Demo mode makes zero Gmail API calls | Demo endpoints never call Gmail API; demo data served from seeded DB and disk |
| Demo data is DB seeded and file seeded at deploy | Seed script populates users, receipts, and PDFs at /app/storage/demo/ before first request |
| Demo exports are prebuilt ZIPs on disk | ZIPs at /app/storage/demo_exports/{month}.zip; GET /export serves file, does not generate |
| Demo reset must not delete seeded demo receipts | POST /demo/reset clears session only; no DELETE on demo receipts |
| Demo reset must not delete demo exports | Reset never removes files in /app/storage/demo_exports/ |
| Demo must be instant | No network calls; no heavy computation; read from local storage |

---

## Security Guardrails

| Rule | Mechanism |
|------|-----------|
| Refresh tokens encrypted at rest | Fernet encryption before DB insert in gmail_accounts.refresh_token_encrypted |
| OAuth state validated on callback | Reject callback if state does not match session/cookie |
| Cron endpoint protected | Static X-Cron-Secret header only; return 401 if missing or wrong |
| Static cron secret only | No dynamic HMAC; env var compared as string |
| Month validation | Validate month with regex `^\d{4}-(0[1-9]|1[0-2])$`. If it fails, reject. If it passes, parse with %Y-%m. Construct export filename from validated month only. No user-controlled path segments are used. Defense in depth: reject inputs containing `..`, `/`, or `\`. |
| Session cookies hardened | HttpOnly, SameSite=Lax, Secure in production |

---

## Data Correctness Guardrails

| Rule | Mechanism |
|------|-----------|
| Receipt deduplication by SHA256 per user | UNIQUE(user_id, file_sha256) in receipts; insert fails or upsert skips on duplicate |
| Deduplication is file-level | Hash of PDF bytes; same content = same hash |
| Seeding is idempotent | Seed script can run multiple times without corrupting data |
| Disconnect deletes all user data | Delete receipts, gmail_accounts, users rows; delete PDF files |
| Disconnect revokes token best-effort | Call revoke endpoint; proceed with deletion even if revoke fails |
| Receipt scoring explicit | KNOWN_VENDORS +3, invoice/receipt +2 each, negative terms -2, non-PDF/image -2; score >= 4 save high_confidence; score 3 review queue; score <= 2 skip |

---

## Operational Guardrails

| Rule | Mechanism |
|------|-----------|
| SQLite runs in WAL mode | `PRAGMA journal_mode=WAL` on connection |
| Short transactions | No long-held locks; commit quickly |
| Scan gate for /internal/scan | scan_locks(id=1,last_run) enforces a 5 minute minimum interval and prevents overlapping runs by rejecting calls within that window; single instance; no distributed locking |
| Rate limiting storage | scan_locks is the DB-backed gate; no separate rate limiting table |
| Scan scope | Only non-demo accounts with status connected_active; cap 50 accounts per run |
| /internal/scan response for manual testing | Returns 200 with {"scanned": N} on success |
| Export caps for real users | max_files = 500, max_size_mb = 100 per export |
| Single instance assumed | No distributed locking; hackathon scope |

---

## Scope Guardrails

We are **not** building:

- Support for more than 5 real users (Gmail Testing mode limit)
- Multi-instance or horizontal scaling
- HMAC or signed cron requests
- Amount parsing for all vendors (only top 3 best-effort)
- Receipt date extraction from PDF body (use Gmail internalDate primarily)
- SMTP or non-Gmail email sources
- Recall-optimized receipt detection (precision over recall)
---

## Formatting and Style

- No em dashes in any documentation
- Use concrete mechanisms, not vague terms like "robust" or "secure"
- Keep docs consistent across spec.md, milestones.md, and guardrails.md
