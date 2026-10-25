# ONEBRIDGE

**Every Problem Deserves a Solution.**

ONEBRIDGE is a community problem-reporting and resolution-tracking demo. Residents can submit local issues, follow a transparent human-review workflow, and confirm whether a resolution worked. Authorized reviewers can assess reports and assign them to a resolver.

> **Honest scope:** this repository contains a runnable, local-first vertical slice, not the full production stack in the original specification. It uses Python's standard library, SQLite, and a responsive browser UI. It does **not** include React, Express, PostgreSQL, Prisma, Azure service calls, image uploads, email, or external government integrations. AI verification, image proof, and map geocoding are not implemented. See [Architecture and limitations](docs/architecture.md).

## What works

- Citizen registration and sign-in; new accounts always receive the citizen role.
- Password storage with salted scrypt hashes and opaque, HttpOnly, SameSite session cookies.
- Citizen-only report submission with input validation, tracking IDs, and a per-account submission limit.
- Report privacy: GPS is requested only after you opt in and grant browser permission. Shared coordinates are visible only to the reporter, an administrator, or the resolver assigned to that report; they are never shown on a public map.
- Human review outcomes, evidence requests, audit events, in-app notifications, and reviewer/resolver role checks.
- Admin assignment to an authorized resolver, resolver progress updates, and a resolution submission that the reporter can confirm or dispute.
- Rules-based TrustShield completeness signals with explanations; no fabricated AI score and no automated fraud finding.
- Local community-report list, role-specific dashboards, filters, and category statistics calculated from stored reports.
- Fictional demo accounts and sample issues for a local walkthrough.

## Requirements

- Python 3.10 or newer (tested with Python 3.13).
- No package installation or Node.js is required.

## Run locally

From the project directory:

```powershell
python server.py --seed-demo
python server.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). Stop the server with `Ctrl+C`.

The SQLite database is created at `data/onebridge.sqlite3`. To choose a different database path before starting:

```powershell
$env:ONEBRIDGE_DATABASE = "data/local-demo.sqlite3"
python server.py
```

The server binds to `127.0.0.1` by default so the local demo is not exposed to the network. Configure `ONEBRIDGE_HOST` or `ONEBRIDGE_PORT` only when you understand the exposure. This standard-library HTTP server has not been hardened for production deployment.

### Demo accounts

| Role | Email | Password |
|---|---|---|
| Citizen | `citizen@onebridge.local` | `CitizenDemo!2026` |
| Authorized resolver | `resolver@onebridge.local` | `ResolverDemo!2026` |
| Platform administrator | `admin@onebridge.local` | `AdminDemo!2026` |

These credentials are deliberately public demo credentials. Do not deploy the demo database or reuse these passwords. Registration creates citizen accounts only; elevated roles must be granted by a separately designed, secure administrative process.

To reset demo state, stop the server, remove the specific local file `data/onebridge.sqlite3`, then run `python server.py --seed-demo` again. Never commit this database.

## Test

Run the standard-library unit tests:

```powershell
python -m unittest discover -s tests -v
```

Run Python syntax checks:

```powershell
python -m py_compile server.py tests\test_server.py
```

## Workflow walkthrough

1. Sign in as the citizen and submit a report.
2. Sign in as the platform administrator. Open **Operations**, then open the new report.
3. Add a human review note and mark the report supported by evidence.
4. Assign the supported report to the demo resolver account.
5. Sign in as the resolver, post a progress update, then submit a resolution note.
6. Sign in again as the citizen to confirm or dispute the proposed resolution.

No agency is contacted. Assignment and notification actions only update this application's local database.

## Configuration and integrations

`.env.example` documents optional settings, but Python's standard library does not load `.env` files automatically; set environment variables in your shell. The Azure environment-variable names are placeholders only and are **not read to invoke Azure services**. There are no external network calls from the application.

Image evidence uploads, password reset, multilingual/voice input, Azure AI Vision, Azure Maps, Blob Storage, PostgreSQL, Prisma migrations, email, and deployment are not implemented. Do not put secrets into the frontend or commit them to source control.

## Security and privacy notes

- Passwords use Python's built-in scrypt key derivation function with a random salt.
- Sessions are stored as SHA-256 token hashes in SQLite; cookies are `HttpOnly` and `SameSite=Strict`.
- Writes reject cross-origin `Origin` headers; APIs validate inputs and parameterize database queries.
- The local server uses HTTP, so its cookies are not marked `Secure`; use a properly configured HTTPS deployment before exposing user accounts.
- Session expiry, sign-in throttling, and report-submission throttling are basic demo protections, not a substitute for production identity, abuse prevention, monitoring, or privacy review.
- The demo does not accept or persist uploaded files.

See [Architecture and limitations](docs/architecture.md) for the data model and implementation boundaries.

## Project

Created by **R J Harsha Vardhan**. Licensed under the [MIT License](LICENSE).
