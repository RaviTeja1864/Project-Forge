# ProjectForge

ProjectForge is a private, evidence-minded workspace for turning real-world problems into engineering projects. It provides email/password accounts, a PostgreSQL-backed workspace API, a source-backed problem catalogue, and a workspace-scoped local-model workflow for research, requirements, technology comparisons, and proposed system designs.

## Architecture

- **Frontend:** React 19, TypeScript 7, Vite 8, React Router 7, and a typed Fetch API client.
- **Backend:** Django 6.1, Django REST Framework, Django sessions, and Django ORM.
- **Database:** PostgreSQL 17 for the Compose development stack; SQLite is available only as an explicit local test option.
- **Authentication:** Django session cookies, HTTP-only for the session identifier; CSRF tokens are fetched from `/api/auth/csrf/` and sent in `X-CSRFToken` for state-changing requests. The frontend fetches a new CSRF token after sign-in/registration because Django rotates it when establishing the session. Sessions expire after 24 hours. Logout invalidates the session server-side. Cookie deployment across sites requires `SameSite=None`, `Secure`, and HTTPS.
- **Authorization:** Workspaces are private by default. Owners may grant an existing account read-only access; workspace reads are limited to owners and active collaborators, while all mutations remain owner-only. Missing and unrelated workspace IDs return 404.
- **Local model:** The backend calls an explicitly configured, host-allowlisted Ollama endpoint. It defaults to local Ollama and `qwen3:4b`; there is no cloud model fallback.
- **Generated work:** Research and subsequent design artifacts are stored with their workspace. Every generation creates a draft; users can edit, validate, and explicitly approve it. Approved artifacts are immutable; create a revision to change one.
- **Errors:** DRF returns JSON validation errors with field names and arrays of messages; authentication failures use a generic `detail` message. Health responses include application status and database readiness without internal details.

## Requirements

- Node.js 24 or a compatible Node.js release (Vite's supported runtime).
- Python 3.12+.
- Docker Compose v2 with access to pull the PostgreSQL image for the simplest full-stack setup.
- Alternatively, a local PostgreSQL server for application development.

The checked-in Python and npm manifests pin the resolved direct dependencies. `uv.lock` and `package-lock.json` record the dependency resolutions.

## Run locally with Docker Compose

1. Copy the environment template and create a high-entropy development secret:

   ```sh
   cp .env.example .env
   python3 -c 'import secrets; print(secrets.token_urlsafe(50))'
   ```

   Put the generated value in `SECRET_KEY` in `.env`, and replace the development PostgreSQL password. These example values are not operational credentials.

2. Install or start the local model separately. If it is not already installed, install Ollama using its official instructions and fetch the configured model:

   ```sh
   ollama pull qwen3:4b
   ollama serve
   ```

   For direct local backend development, the default `http://localhost:11434` works when Ollama is listening on the local interface. With Compose, set `OLLAMA_BASE_URL=http://host.docker.internal:11434` and add `host.docker.internal` to `OLLAMA_ALLOWED_HOSTS` in `.env`. Compose maps that hostname to the host gateway. Configure Ollama to listen on a host interface reachable from the container only if needed, and firewall that interface; do not expose its unauthenticated API to untrusted networks.

3. Start the database, backend, and frontend:

   ```sh
   docker compose up --build
   ```

   Compose waits for PostgreSQL readiness and applies Django migrations before starting the API. Open <http://localhost:5173>. The API is at <http://localhost:8000/api/> and its health/readiness check is <http://localhost:8000/api/health/>.

4. Stop services with `Ctrl+C`, then `docker compose down`. Database data is kept in the named `postgres_data` volume. To remove it, explicitly run `docker compose down -v`; this permanently deletes local development data.

### Run without Compose

Create a PostgreSQL database and role, then set `.env` values as appropriate. Install dependencies and start each service in a separate terminal:

```sh
uv sync --frozen
set -a; . ./.env; set +a
uv run python manage.py migrate
uv run python manage.py runserver
```

```sh
npm ci
npm run dev
```

The `DB_HOST` in `.env` is `localhost` for this setup. Set `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `CORS_ALLOWED_ORIGINS`, and secure cookie flags for the actual deployment origins. Do not use `DEBUG=true` or non-secure cookies in production.

## Configuration

`.env.example` lists all supported values. Important settings:

| Variable | Purpose |
| --- | --- |
| `SECRET_KEY` | Required Django signing secret; never commit a real value. |
| `DEBUG` | Development-only Django debug flag; defaults to false. |
| `ALLOWED_HOSTS` | Comma-separated Django host allowlist. |
| `CSRF_TRUSTED_ORIGINS` | Comma-separated trusted browser origins. |
| `CORS_ALLOWED_ORIGINS` | Explicit frontend-origin allowlist; credentials are enabled only for these origins. |
| `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` | Set to `true` behind HTTPS. |
| `SESSION_COOKIE_SAMESITE`, `CSRF_COOKIE_SAMESITE` | Defaults to `Lax`; use `None` only with secure cookies for a cross-site frontend/API deployment. |
| `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS` | Enable HTTPS redirects and HSTS only when HTTPS is correctly configured end to end. |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | PostgreSQL database and role; Compose requires all three. |
| `DB_HOST`, `DB_PORT` | Database location; Compose overrides host to `db`. |
| `DB_ENGINE`, `DB_NAME` | Set `DB_ENGINE=sqlite` only to run isolated local backend tests. PostgreSQL is the application default. |
| `VITE_API_BASE_URL` | Frontend API root, defaulting to `http://localhost:8000/api`. |
| `RELIEFWEB_APPNAME` | Required for source ingestion; must be an app name pre-approved by ReliefWeb. |
| `PROBLEM_SOURCE_HTTP_TIMEOUT` | ReliefWeb connection/read timeout in seconds; defaults to 15. |
| `PROBLEM_SIMILARITY_THRESHOLD` | Similarity-candidate threshold from 0 to 1; defaults to 0.35. This is not a probability. |
| `PROBLEM_SIMILARITY_LIMIT` | Maximum candidates returned, from 1 to 20; defaults to 5. |
| `OLLAMA_BASE_URL` | Explicit trusted local Ollama base URL; defaults to `http://localhost:11434`. |
| `OLLAMA_ALLOWED_HOSTS` | Exact host allowlist for Ollama requests; defaults to loopback hosts. User input cannot select an Ollama URL. |
| `OLLAMA_MODEL` | Ollama model name; defaults to `qwen3:4b`. No provider fallback is attempted. |
| `OLLAMA_CONNECT_TIMEOUT` | Ollama connection timeout in seconds; defaults to 3 (maximum 30). |
| `OLLAMA_GENERATION_TIMEOUT` | Ollama response timeout in seconds; defaults to 120 (maximum 600). |
| `OLLAMA_MAX_OUTPUT_TOKENS` | Maximum Ollama generated tokens; defaults to 2048 (maximum 4096). |
| `RESEARCH_MAX_SOURCES` | Maximum relevant catalogue evidence records supplied to one research generation; defaults to 8 (maximum 20). |

The local `.env` file is ignored by Git. Django refuses to start if `SECRET_KEY` is missing.

## Data model

- `accounts.User`: Django's `AbstractUser` with email login, normalized lowercase email, case-insensitive database uniqueness, timestamps, and Django password hashing. Username login is removed.
- `workspaces.ProjectWorkspace`: UUID primary key, owner foreign key with cascade on account deletion, required name (maximum 120 characters), optional description (maximum 2,000 characters), controlled planning/in-progress/completed status with database checks, timestamps, and an owner/updated-time index.
- `workspaces.WorkspaceCollaborator`: grant-event rows record the workspace/user, granting owner, grant timestamp, and optional revocation timestamp. A conditional unique constraint prevents multiple active grants for the same pair while retaining revoked grant history. Grants are private, authenticated-account-only and read-only; there are no public links or email invitations. The application does not treat account email as verified.
- `workspaces.WorkspaceArtifact`: workspace-owned, versioned artifact for research, requirements, technology comparisons, system designs, and composed engineering specifications; every version records its sequence number, lineage root, predecessor, optional author, approval state, source snapshots, and input-artifact lineage. Specification snapshots are deterministically composed from exact approved input versions, remain immutable, and can be explicitly approved. There is no automatic promotion or production-schema mutation.
- `workspaces.ImplementationTask`: owner-managed task tied to one approved requirements artifact version and stable requirement ID, with linked acceptance-criterion IDs, status, priority, same-workspace dependencies, and an outdated-source flag.
- `workspaces.ImplementationEvidence` and `workspaces.RequirementVerification`: append-only evidence records and per-requirement verification decisions. Evidence corrections create a linked record instead of changing history. Verification records preserve evidence IDs, criterion results, actor, rationale, and timestamp.

Account deletion cascades to that account's workspaces. Workspace deletion is explicit and irreversible; the UI asks for confirmation and the API deletes only the authenticated owner's requested workspace.

## API

All endpoints are rooted under `/api/`. Mutating requests use JSON and return JSON unless the status is `204`.

| Method | Endpoint | Authentication | Purpose |
| --- | --- | --- | --- |
| `GET` | `/health/` | No | Application liveness and actual database readiness (`checks.application`, `checks.database`); responds `503` if the database is unavailable. |
| `GET` | `/auth/csrf/` | No | Establishes the CSRF cookie and returns a CSRF token. |
| `POST` | `/auth/register/` | No | Register and sign in; accepts `email`, `password`; returns user with `201`. |
| `POST` | `/auth/login/` | No | Sign in; accepts `email`, `password`; invalid credentials have a generic response. |
| `POST` | `/auth/logout/` | Yes | Invalidates the session; returns `204`. |
| `GET` | `/auth/me/` | Yes | Returns the current user. |
| `GET` | `/workspaces/` | Yes | Lists workspaces owned by or actively shared with the current user, newest updated first; includes `access_role`; page-number pagination (`count`, `next`, `previous`, `results`), 12 per page. |
| `POST` | `/workspaces/` | Yes | Creates a workspace; accepts `name`, optional `description`, optional `status`. Ownership is assigned by the server. |
| `GET` | `/workspaces/{uuid}/` | Yes | Reads a workspace owned by or actively shared with the current user; includes `access_role` (`owner` or `collaborator`). |
| `PATCH` | `/workspaces/{uuid}/` | Yes | Updates an owned workspace. Ownership and timestamps cannot be changed by the client. |
| `DELETE` | `/workspaces/{uuid}/` | Yes | Deletes an owned workspace; returns `204`. |
| `GET` | `/workspaces/{uuid}/collaborators/` | Yes, owner only | Lists active and revoked grants for the workspace. |
| `POST` | `/workspaces/{uuid}/collaborators/` | Yes, owner only | Grants read-only access to an existing active account; accepts `{ "email": "account@example.org" }`. Repeating an active grant is idempotent; granting oneself or an unavailable/inactive account is rejected. |
| `DELETE` | `/workspaces/{uuid}/collaborators/{grant_id}/` | Yes, owner only | Revokes the grant immediately; returns `204`. |
| `GET` | `/workspaces/llm/status/` | Yes | Reports local Ollama availability and configured model using safe status states; never returns endpoint diagnostics. |
| `GET` | `/workspaces/{uuid}/artifacts/` | Yes | Lists all owner artifacts, or approved artifacts for collaborators. |
| `GET` | `/workspaces/{uuid}/artifacts/{artifact_uuid}/` | Yes | Reads a saved artifact and its evidence snapshot/input lineage; collaborators can read approved versions only. |
| `PATCH` | `/workspaces/{uuid}/artifacts/{artifact_uuid}/` | Yes | Validates and saves the current draft or explicitly approves that specific version. Approved and superseded versions are read-only. |
| `DELETE` | `/workspaces/{uuid}/artifacts/{artifact_uuid}/` | Yes | Deletes a current, unapproved draft only when it has no later versions; approved and historical versions are protected. |
| `POST` | `/workspaces/{uuid}/artifacts/{artifact_uuid}/revise/` | Yes | Creates the next sequential editable draft from that version, retaining its evidence snapshot and linking its predecessor. |
| `GET` | `/workspaces/{uuid}/artifacts/{artifact_uuid}/versions/` | Yes | Lists all versions in that artifact lineage in version order. |
| `GET` | `/workspaces/{uuid}/artifacts/{artifact_uuid}/versions/{version_uuid}/` | Yes | Retrieves one version only if it belongs to the requested artifact lineage. |
| `GET` | `/workspaces/{uuid}/artifacts/{artifact_uuid}/versions/compare/?left_version={uuid}&right_version={uuid}` | Yes | Compares two versions in the same lineage; returns changed paths and before/after values for content, evidence, inputs, and status. |
| `POST` | `/workspaces/{uuid}/specifications/` | Yes | Deterministically composes a new immutable draft snapshot from the latest approved research, requirements, technology comparison, and design versions; accepts an empty JSON body. |
| `GET` | `/workspaces/{uuid}/specifications/` | Yes | Lists specification snapshots, including version, approval state, and whether newer approved inputs make each snapshot potentially outdated. |
| `GET` | `/workspaces/{uuid}/specifications/{artifact_uuid}/` | Yes | Reads one immutable specification snapshot and its exact input artifact IDs/version numbers. |
| `GET` | `/workspaces/{uuid}/specifications/{artifact_uuid}/inputs/` | Yes | Returns the exact input artifact versions, their approval states, stored validation findings, and current outdated status. |
| `GET` | `/workspaces/{uuid}/specifications/{artifact_uuid}/export.md` | Yes | Downloads UTF-8 Markdown rendered from the selected persisted snapshot, including status and outdated metadata. |
| `GET` | `/workspaces/{uuid}/specifications/{artifact_uuid}/export.pdf` | Yes | Downloads a paginated PDF rendered locally from that same immutable snapshot. Mermaid source is included as text rather than sent to an external renderer. |
| `POST` | `/workspaces/{uuid}/implementation/tasks/generate/` | Yes, owner only | Accepts `{ "requirements_artifact_id": "<approved-requirements-uuid>" }`; deterministically creates at most one task per stable requirement ID for that exact artifact version, returns created/existing counts and any unmapped requirements. Repeating the request does not overwrite tasks or edits. |
| `GET` | `/workspaces/{uuid}/implementation/tasks/` | Yes | Lists workspace tasks with source requirement/version, acceptance-criteria IDs, dependencies, status, priority, and stale-source flag. |
| `POST` | `/workspaces/{uuid}/implementation/tasks/` | Yes, owner only | Creates an editable task linked to an approved requirements version and requirement ID; acceptance criteria are derived from that snapshot. |
| `GET` | `/workspaces/{uuid}/implementation/tasks/{task_id}/` | Yes | Retrieves a task belonging to the workspace. |
| `PATCH` | `/workspaces/{uuid}/implementation/tasks/{task_id}/` | Yes, owner only | Edits task title, description, priority, status, or dependencies; cross-workspace, self, and cyclic dependencies are rejected, and status changes follow the transition rules. |
| `GET` | `/workspaces/{uuid}/requirements/{artifact_uuid}/{requirement_id}/evidence/` | Yes | Lists evidence records, including superseded corrections, for the exact approved requirements version and requirement. |
| `POST` | `/workspaces/{uuid}/requirements/{artifact_uuid}/{requirement_id}/evidence/` | Yes, owner only | Records evidence type, description, optional literal source reference, result, review basis, optional task/criterion links, and optional `supersedes_id` correction. References are stored as claims and never fetched, executed, or read. |
| `GET` | `/workspaces/{uuid}/requirements/{artifact_uuid}/{requirement_id}/verification/` | Yes | Returns the current deterministic status and whether the latest recorded decision is stale. Before a decision is recorded, the response includes a computed preview and a null decision timestamp. |
| `POST` | `/workspaces/{uuid}/requirements/{artifact_uuid}/{requirement_id}/verification/` | Yes, owner only | Recomputes the requirement status from recorded evidence, appends an immutable decision with evidence and criterion snapshots, and returns the decision. No status may be supplied by the client. |
| `GET` | `/workspaces/{uuid}/requirements/{artifact_uuid}/{requirement_id}/verification/history/` | Yes | Lists verification decisions in reverse chronological order, preserving superseded decisions and flagging stale records. |
| `POST` | `/workspaces/{uuid}/generate/research/` | Yes | Accepts `{ "problem_id": "<published-problem-uuid>" }`; uses only stored catalogue evidence. |
| `POST` | `/workspaces/{uuid}/generate/requirements/` | Yes | Generates a draft from the latest approved research synthesis. |
| `POST` | `/workspaces/{uuid}/generate/technology/` | Yes | Accepts 2–8 user-chosen `{ "options": ["…", "…"] }` and requires approved requirements. |
| `POST` | `/workspaces/{uuid}/generate/design/` | Yes | Generates a proposed design from approved research, requirements, and technology comparison. |

Workspace statuses are `planning`, `in_progress`, and `completed`. Validation errors have a field-keyed shape such as `{"name":["This field is required."]}`. Not-found resources and resources belonging to an unrelated account both return `404`. Collaborators may read workspace details, approved artifacts and their approved version history, approved specifications, specification inputs, and Markdown/PDF exports. Drafts are hidden from collaborators. All editing, approval, generation, revision, deletion, and sharing operations are owner-only and rejected at the API boundary.

Collaborators can also view task plans, evidence records, and verification history tied to approved requirements versions. Task generation, task/evidence mutations, and verification decisions are owner-only. A task or verification tied to an older requirements snapshot is retained and flagged stale rather than silently updated.

Each workspace/artifact lineage has a unique sequential version number. Regeneration continues the latest lineage for that artifact type; an explicit revision names the version it copies, so a revision from any earlier version remains traceable. Version creation locks the workspace row and is protected by a database uniqueness constraint on `(lineage_root, version_number)`. Each version's status is independent: approving a draft does not alter any other version. Superseded drafts and approved versions cannot be edited or deleted through the API. Migration `0006_workspaceartifact_author_and_more` maps every existing Phase 3 artifact to version 1 of its own lineage and leaves its content, approval state, and provenance intact; author remains unknown (`null`) for those earlier records.

`POST /workspaces/{uuid}/specifications/` composes the latest approved version of each of the four engineering inputs without another model call. The snapshot retains the input artifact IDs, version numbers, approval states, evidence identifiers and full source metadata; it also carries validation findings and unresolved information. A recommendation/design technology mismatch or incompatible upstream input lineage is preserved as a conflict finding rather than resolved. Unknown evidence citations, invalid requirement cross-references, and unsafe/inconsistent diagrams prevent snapshot creation. Newer approved input versions mark existing snapshots potentially outdated but never modify their content; generate another snapshot to incorporate reviewed input versions. Specification snapshots begin as immutable drafts and use the existing artifact PATCH route to approve that specific snapshot. Migration `0007_remove_workspaceartifact_workspace_artifact_kind_valid_and_more` extends the artifact kind constraint and choices without changing existing rows.

Markdown and PDF downloads take the selected snapshot ID and render its stored content only; they do not recompose or call a model. Downloads include version/status, generated date, exact input IDs and versions, source references, Mermaid source, unresolved issues, and validation findings. Filenames are ASCII-normalized slugs with the snapshot version, so project names cannot inject paths or response headers. PDF generation is local through the pinned ReportLab dependency; a table of contents and page numbers are included. ReportLab's bundled Vera font covers common Latin Unicode characters; characters outside its font repertoire may not display as intended. No cloud conversion or external diagram rendering is used.

Implementation plans are generated from an explicitly selected approved requirements version, one task per stable requirement ID, and only its linked acceptance criteria. Generation is idempotent and does not replace edits on existing tasks. A later requirements artifact/version makes tasks and verification decisions tied to an older snapshot stale; their source is retained. Task dependencies must stay in the workspace, cannot include the task itself, and cannot form cycles. Tasks start in `todo`; supported statuses are `todo`, `in_progress`, `blocked`, and `completed`. A completed task can be explicitly reopened to `todo` or `in_progress`.

Evidence is appended against the exact approved requirements artifact and requirement. Correcting a record creates a new evidence row linked by `supersedes_id`; prior records and verification decisions remain inspectable. Source references (paths, URLs, endpoints, test output references, and notes) are stored literally and are never fetched, executed, or opened by ProjectForge. Evidence is labeled `self_reported` or `manually_reviewed`; manual review is not represented as automated verification. A requirement is `verified` only when each linked acceptance criterion has a passing `verification_check` recorded as manually reviewed, and no recorded verification check failed review. Partial passing coverage yields `partially_implemented`; explicit manually reviewed absence yields `missing`; self-reported, stale, absent, or inconclusive support remains `unverified`. Reverification appends a new audit record. This is deterministic evaluation of recorded evidence, not an independent inspection of repository contents or execution of tests.

Migrations `0009_implementationtask_implementationevidence_and_more` and `0010_implementationevidence_implementation_evidence_single_correction` add the task, evidence, and verification tables and enforce a single successor per corrected evidence row. Existing workspace/artifact data is not rewritten.

Migration `0008_workspacecollaborator` adds the workspace grant table without changing existing workspace or artifact rows. It uses a conditional unique constraint for active workspace/user pairs; revoked grant events remain recorded, and a later grant creates a new event row.

## Local research and project design workflow

The workspace detail page offers four ordered local-model steps. Select a published catalogue problem to generate research. The backend ranks and caps that problem's existing `EvidenceSource` records, snapshots source identifiers, original URLs, publisher/date/retrieval metadata, source type, and excerpts, and sends only this bounded context to Ollama. Duplicate evidence is removed only by stable source ID or canonical URL; text similarity alone never discards a source. Empty evidence produces a deterministic insufficiency report without calling the model. Every citation must resolve to a source in the supplied snapshot; supported claims without citations and fabricated source IDs are rejected.

Requirements generation consumes approved research and emits editable problem framing, objectives, user/stakeholder assumptions, scope, user stories, stable `US-###` / `FR-###` / `NFR-###` / `AC-###` identifiers, constraints, risks, dependencies, and acceptance criteria. Evidence-backed requirements must cite stored sources. Unsupported quantitative targets need user input rather than invented thresholds.

Technology comparison consumes approved requirements and user-provided alternatives (2–8). It uses qualitative compatibility ratings rather than numeric scoring, keeps evidence-backed claims tied to supplied source IDs, and records assumptions and missing information. Its recommendation is a reviewable proposal, not an objective ranking.

System design consumes the preceding approved artifacts and proposes architecture components, request/data flows, REST endpoint shapes, database entities and constraints, Mermaid flowcharts and an ER diagram, security/privacy/reliability considerations, failure handling, trade-offs, and unresolved decisions. Server validation checks bounded structure, citation/requirement references, endpoint paths, entity relationships, and Mermaid diagram type/entity consistency. Designs do not modify ProjectForge's actual schema or application routes.

Model/network failures return safe, actionable messages. Ollama calls are synchronous and bounded by configured connection/generation timeouts; large generations can take time and are not moved to a job queue. Source excerpts are untrusted prompt context, not instructions. Deterministic schema and citation validation cannot guarantee factual accuracy, so review every draft and source before approval. No second model, embedding store, arbitrary URL fetch, or cloud fallback is used.

## Problem catalogue and source ingestion

Phase 2.1 adds a read-only public-problem catalogue backed by stored source records. Ingestion is deliberately opt-in and available only as an operator-run management command; there is no browser-accessible ingestion endpoint.

The initial provider is the [ReliefWeb reports API](https://apidoc.reliefweb.int/). It is a documented read-only API. Use is subject to its [terms and quotas](https://apidoc.reliefweb.int/#tos): report material is contributed by information partners, source IP rights must be respected, the API requires a pre-approved `appname`, and the daily quota is 1,000 calls with up to 1,000 results per call. ProjectForge requests at most 100 reports in one call, does not automatically retry, retains attribution and a bounded excerpt, and links back to each report. Run ingestion deliberately and coordinate the daily call budget among operators.

Set `RELIEFWEB_APPNAME` in `.env` to an actual app name pre-approved by ReliefWeb. Do not use a guessed name. Then run:

```sh
set -a; . ./.env; set +a
uv run python manage.py ingest_reliefweb --limit 20
```

The command fails before making a request if the app name is missing and accepts a limit from 1 to 100. A request or response failure raises an explicit command error; individual reports missing an identifier, title, URL, or textual body are counted and reported as skipped instead of being filled with invented values. Publication dates and publishers missing from the response remain empty. The upstream report's `date.original`, title, source publishers, themes, URL, and HTML body are mapped only from fields returned by the API. Body markup is reduced to text; the problem difficulty remains `unspecified` because the provider does not supply an engineering-difficulty rating. Sector labels are the source's theme labels, not an independently verified sector taxonomy.

Repeated report IDs update the existing statement/source. Canonical HTTPS URLs (case-normalized host, trailing slash and fragment removed) are also unique, so the same report under a changed external ID does not create a duplicate. Each source retains its original URL, source identifier, source title, publisher when present, original publication date when present, retrieval timestamp, report type, and a 2,000-character maximum excerpt. The current importer does not crawl linked pages or call third-party publisher domains.

| Method | Endpoint | Authentication | Purpose |
| --- | --- | --- | --- |
| `GET` | `/problems/` | Yes | Paginated published catalogue (`count`, `next`, `previous`, `results`) with a real evidence-source count. `page_size` may be set up to 50. |
| `GET` | `/problems/{uuid}/` | Yes | Read one published problem statement and its linked evidence-source metadata. |
| `GET` | `/problems/{uuid}/similar/` | Yes | Ranked text-similarity candidates, matching signals, and the configured threshold. |
| `GET` | `/problems/{uuid}/sources/` | Yes | Paginated evidence sources for that problem. |
| `GET` | `/problems/{uuid}/sources/{source_uuid}/` | Yes | Read a source belonging to that problem. |

All catalogue endpoints require an authenticated session. Create/update/delete methods are not exposed. Only published problem statements appear in ordinary catalogue reads; archived statements are retained but hidden. The current provider creates one statement per ReliefWeb report, so separate reporting on the same underlying event is not merged automatically.

`GET /problems/` supports `q` (case-insensitive match in problem titles/descriptions and evidence title, publisher, excerpt, URL, or source type), exact `sector`, valid `difficulty` (including `unspecified`), inclusive `source_date_from` / `source_date_to` bounds (`YYYY-MM-DD`), and `ordering` (`created_at`, `-created_at`, `title`, `-title`, `sector`, `-sector`, `difficulty`, `-difficulty`). Blank `q` and blank filters are ignored; invalid difficulty, date, range, or ordering returns HTTP 400. Search text is limited to 200 characters. Date bounds select problems with at least one matching dated evidence row. These parameters combine with existing pagination.

Similarity normalizes Unicode (NFKC), case, whitespace, and punctuation. An exact normalized title scores 1.0; otherwise the score is a weighted token-set Jaccard similarity (65% title, 35% description). Different non-empty sectors are excluded; if either sector is blank, a candidate may still be compared. Results include matching term/exact-match explanations and are ranked by score, then UUID for stable ties. This lightweight scan is intended for the current small catalogue, has configurable threshold/cap, does not merge records, and is not a probability or proof of duplication. It has only an explicit synthetic unit-test set, not a representative labeled corpus; real-world accuracy is unknown.

Problem detail also returns nested evidence sources, while the separate source list remains paginated. Source ordering is retrieval timestamp descending with UUID tie-breaking. Publisher, publication date, and excerpt remain absent/empty when unknown; the frontend only renders source links for HTTPS URLs and uses `noopener noreferrer`.

## Migrations and checks

```sh
set -a; . ./.env; set +a
uv run python manage.py migrate
uv run python manage.py makemigrations --check --dry-run
uv run ruff check .
npm ci
npm run typecheck
npm run lint
npm test
npm run build
```

Run backend tests against a temporary SQLite test database (the test runner creates and destroys this isolated test database; it does not access PostgreSQL):

```sh
DB_ENGINE=sqlite SECRET_KEY=test-only uv run python manage.py test
```

PostgreSQL-specific migration and integration verification should be run with Compose or a dedicated test PostgreSQL instance. No production data or credentials should be used for tests.

## Security and operations

- Session cookies are HTTP-only, same-site `Lax` by default and last 24 hours. CSRF middleware and DRF session authentication guard authenticated state-changing requests.
- CORS uses an explicit allowlist; wildcard credentialed CORS is not enabled.
- Use HTTPS and set secure cookies, production `ALLOWED_HOSTS`, and actual frontend origins for deployment.
- Database connectivity failures are not disguised as a healthy readiness result. API responses do not expose SQL, secrets, or stack traces.
- No seed account, sample customer data, or fabricated workspace records are created.

## Current limitations

There is no password reset, email verification, account recovery, rate limiting, production static asset pipeline, or deployed environment. Workspace pages contain 12 records and can be browsed with pagination. Catalogue ingestion has only the ReliefWeb provider and was not run without a pre-approved app name. The importer does not crawl source links, merge reports about the same real-world event, or infer an engineering difficulty. Similarity quality has not been measured on representative human-labeled data. Local-model output is not fact-checked beyond structure and source-reference validation, and the qualitative technology comparison has no independently labeled evaluation corpus.

## Verification record

Backend verification can use SQLite by running `SECRET_KEY=test-only DB_ENGINE=sqlite .venv/bin/python manage.py test`; check migrations with `SECRET_KEY=test-only DB_ENGINE=sqlite .venv/bin/python manage.py makemigrations --check --dry-run`. Python lint uses `uv run ruff check .`. Frontend checks use `npm test`, `npm run typecheck`, `npm run lint`, and `npm run build`. Tests mock Ollama and never require model/network access. PostgreSQL, Docker Compose, and live Ollama checks must be reported separately from these test runs.
