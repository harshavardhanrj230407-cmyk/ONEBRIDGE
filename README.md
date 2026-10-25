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
- No third-party package installation, Node.js, or Docker is required. See [requirements.txt](requirements.txt).

## Project structure

```text
ONEBRIDGE/
├── server.py              # Python HTTP server, JSON API, and SQLite workflow
├── web/                   # Responsive HTML, CSS, and JavaScript frontend
├── tests/                 # Unit and API workflow tests
├── docs/                  # Architecture, data model, and integration boundaries
├── data/                  # Generated local SQLite data (not committed)
├── .env.example           # Placeholder configuration reference
├── .gitignore
├── LICENSE
├── README.md
└── requirements.txt       # Documents standard-library-only dependencies
```

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
python -m py_compile server.py tests\test_server.py tests\test_workflow.py
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

### TrustShield verification

The current TrustShield demo reports four explainable completeness signals: a description was provided, a supported category was selected, a location was described, and an optional evidence note was provided. These are **not AI predictions, proof that an issue is genuine, or a fraud score**. An authorized person makes review decisions, provides a note, and can request additional evidence or escalate uncertainty for human review.

### Microsoft Azure integration plan

Azure is a future integration plan, not an implemented dependency. The `.env.example` values alone do not activate an Azure service. A production integration should be introduced as an explicitly configured provider with a clearly labeled local fallback:

1. **Azure AI Foundry:** optional, human-reviewed category and routing suggestions, with the factors behind recommendations explained.
2. **Azure AI Vision:** optional image relevance signals for an uploaded report. Never treat image analysis as proof of authenticity or completed work.
3. **Azure Maps:** optional geocoding and map display, with approximate public locations and access-controlled precise coordinates.
4. **Azure AI Speech and Translator:** optional English, Hindi, and Kannada input and translation, with the original report retained for review.
5. **Azure Blob Storage:** private evidence storage with strict upload validation, short-lived access, and a documented retention policy.

Any implementation must keep credentials server-side, prefer managed identities, document data handling and costs, and make unavailable integrations visible instead of pretending a service ran.

## Security and privacy notes

- Passwords use Python's built-in scrypt key derivation function with a random salt.
- Sessions are stored as SHA-256 token hashes in SQLite; cookies are `HttpOnly` and `SameSite=Strict`.
- Writes reject cross-origin `Origin` headers; APIs validate inputs and parameterize database queries.
- The local server uses HTTP, so its cookies are not marked `Secure`; use a properly configured HTTPS deployment before exposing user accounts.
- Session expiry, sign-in throttling, and report-submission throttling are basic demo protections, not a substitute for production identity, abuse prevention, monitoring, or privacy review.
- The demo does not accept or persist uploaded files.

See [Architecture and limitations](docs/architecture.md) for the data model and implementation boundaries.

## GitHub setup and future updates

This project is maintained in the public [ONEBRIDGE GitHub repository](https://github.com/harshavardhanrj230407-cmyk/ONEBRIDGE). Its configured `origin` should point to that repository. Check the repository root and working tree before making changes or pushing:

```powershell
git rev-parse --show-toplevel
git status --short --branch
git remote -v
```

Configure the author identity for this repository if needed:

```powershell
git config user.name "R J Harsha Vardhan"
git config user.email "harshavardhanrj230407@gmail.com"
```

Push future updates from the ONEBRIDGE folder only:

```powershell
git add .gitignore .env.example LICENSE README.md docs requirements.txt server.py tests web
git diff --cached --check
git commit -m "Describe the ONEBRIDGE update"
git push origin main
```

Review staged changes and never force-push. Do not stage local databases, `.env` files, or real user evidence.

## Project

Created by **R J Harsha Vardhan**. Licensed under the [MIT License](LICENSE).
