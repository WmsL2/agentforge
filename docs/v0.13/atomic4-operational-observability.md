# AgentForge v0.13 — Atomic 4: Operational Observability

Date: 2026-11-27. Local implementation report for review; not Final Source Review
PASS, runtime verification PASS or Atomic 4 COMPLETE. Await ChatGPT Implementation
Report Review. Positioning follows the maintainer-approved 2026-11-26 Engineering
Hardening amendment; commercial production deployment is not a project requirement.

## 1. Exact baseline and prior evidence

Verified repository D:/agent_project/agentforge, remote
https://github.com/WmsL2/agentforge.git, branch main, HEAD
`3fd830671c6e946744dd989e0744c90e5a644c15`, historical peeled v0.12.0
`6e4cca6bc188d829bc09431080b08ad86e37f3fb`. Initial working tree/staging empty;
initial git diff --check passed. AGENTS.md and the requested tracked source,
frontend test conventions, audit and roadmap amendment were reviewed.

Supplied historical decisions: Atomic 3 COMPLETE, PR #42 merged, PR CI #203 SUCCESS,
Main CI #204 SUCCESS (16 jobs), local synchronization confirmed, Atomic 4
pre-implementation Source Review PASS. These supplied CI/review results were not
retrieved anew or used as new runtime evidence. Historical roadmap pending entries
remain their original dated records; this task does not rewrite them. Atomic 3's
blocked build and deferred production-runtime limitations remain preserved.

## 2. Verified findings, remediation and scope decisions

The current source matched the supplied implementation findings. Readiness used
the ordinary committing request-session dependency, wall-clock timing and no
explicit query timeout. DB/Redis failure codes were already sanitized by Atomic 2
and are preserved. RedisClient.ping already returns false on missing connection or
caught connection error; the readiness wrapper retains that behavior and adds its
own finite budget and missing-lifespan handling. LLM/Worker configuration was
incorrectly described as healthy; there was no operational metrics implementation.
Root-only PII filtering rewrote shared records and missed descendants' handlers,
structured fields and exception output. Request IDs were unvalidated. The system
page had illustrative 90-day percentages, a p50 label for a single latency,
unsupported services and a basic-health fallback; readiness had no Next.js route.

Installed/locked Flower 2.0.1 maps `/healthcheck` to monitor.Healthcheck, whose GET
writes OK without an authentication decorator. Celery's installed logging setup
emits after_setup_logger and after_setup_task_logger after installing its handlers;
these hooks are used rather than replacing its logging configuration. No actual
Worker, Beat or Flower process was started.

The only deps.py change is defensive API-key handling: non-ASCII input previously
could raise TypeError in compare_digest(str, str); it now fails closed with the
existing 403 contract and compares bytes. Missing keys still return 401. No auth/
RBAC redesign, new auth system or unrelated dependency changes were made.

## 3. Health contracts and probe lifecycle

| Endpoint | Contract |
| --- | --- |
| GET /api/v1/health | Public basic HTTP response: status healthy and max_upload_size_mb; no dependency calls |
| GET /api/v1/health/live | Public process response: alive, timestamp/service, actual app.__version__ and environment; no DB/Redis/Celery/Provider calls |
| GET /api/v1/health/ready | Concurrent PostgreSQL SELECT 1 and Redis ping; 200 ready only if both succeed, otherwise 503 not_ready |
| GET /api/v1/ready | Legacy alias for the same readiness contract |
| GET /api/v1/metrics | Existing ValidAPIKey authentication; JSON snapshot, no-store; not exposed through a frontend proxy |

Readiness retains nested checks and the existing top-level entries. It adds
embedding and knowledge_agent entries. database/redis are critical; llm, embedding,
worker and knowledge_agent are optional configuration indicators. Optional entries
use configured/not_configured with connectivity_checked=false; Knowledge Agent also
reports enabled. LLM uses LLM_API_KEY, provider and model configuration, never the
legacy OPENAI_API_KEY fallback. Embedding uses its own key/model/dimensions.
Knowledge Agent configuration combines enablement with both Provider capabilities.
Broker configuration is not Worker responsiveness or successful task execution.
No Provider client initialization/request or Celery control ping occurs in readiness.

The session-factory dependency reuses async_session_maker and the existing engine/
pool. Each database check creates a dedicated short-lived session, executes SELECT
1 and closes it, rolling back the read transaction; it never commits. Session
creation/query failures and cleanup failures stay inside safe health handling,
avoiding the old request dependency's post-response commit. Both dependencies have
a 2-second cooperative asyncio budget, run concurrently and use perf_counter for
latency. Database close has a separate 250ms budget: nominal probe/cleanup work is
bounded by about 2.25s plus scheduling overhead, not a hard real-time SLA. This
assumes cooperative async clients, not arbitrary blocking code. Cancellation
propagates after bounded cleanup; no new long-lived engine/pool is introduced.

Stable public errors: DATABASE_CONNECTION_FAILED, DATABASE_TIMEOUT,
DATABASE_CLEANUP_TIMEOUT, DATABASE_CLEANUP_FAILED, REDIS_UNAVAILABLE,
REDIS_PING_FAILED, REDIS_TIMEOUT and REDIS_CONNECTION_FAILED. No raw exception,
connection URL, password, internal hostname or stack is returned. Factory/query/
close/timeouts, absent lifespan state and cancellation are tested with synthetic
objects, not real PostgreSQL/Redis evidence.

## 4. Request ID and HTTP lifecycle

RequestIDMiddleware is pure ASGI. ObservedFastAPI installs it outside the complete
Starlette middleware stack, including ServerErrorMiddleware; generated 500 response
headers/bodies therefore receive the same observation and correlation as normal
responses. Error response contracts, WWW-Authenticate and WebSocket behavior remain
unchanged. AppException log metadata omits the raw path; unexpected exception logs
contain a bounded type and safe correlation fields, not arbitrary exception text.

Accept exactly one X-Request-ID matching `[A-Za-z0-9][A-Za-z0-9._-]{0,63}`; otherwise
generate a UUID. Duplicate IDs, empty/oversized values, whitespace, control bytes,
non-ASCII and unsafe characters are replaced. Store the effective ID in request.state,
return it in the response header and set a request-local ContextVar. Reset its token
in finally on success, handled/unhandled errors, cancellation and incomplete streams.
Client IDs are untrusted metadata, never identity or authorization.

One INFO completion event per HTTP lifecycle contains only request_id, allowlisted
method (otherwise OTHER), status_code or null, monotonic duration_ms and outcome
(completed/cancelled/incomplete). No raw URL, query, body, cookie, authorization or
file/document content is included. No streaming body is buffered or changed. No
cross-task propagation, distributed tracing or execution Trace/RunStep redesign.
INFO events remain subject to the operator's logger levels; handlers are not forced
to INFO merely to emit them.

## 5. Effective logging coverage and limitations

PiiRedactionFilter returns a sanitized LogRecord copy (Python >=3.12). It does not
mutate the original record, interpolation data or nested business objects. Existing
output handlers get an idempotent RedactingFormatter wrapper that sanitizes before
the delegate formatter and again at the output boundary. Root and descendant
loggers, attached/non-propagating handlers, formatting args, structured/nested extras,
exception text/cached traceback and stack_info are covered in synthetic emitted-output
tests. Delegate levels/formatting are retained where practical; format failures emit
a fixed safe fallback. Celery root/task hooks reapply wrappers after initialization,
including Beat's root logging setup; no task execution or durability setting changes.

Supported patterns include email, JWT, Bearer, sk- and sk_ key families, password/
token/API-key pairs, authorization/cookie fields and credential-bearing connection
URLs. Sensitive structured keys redact the complete value. Arbitrary objects are
replaced rather than calling their str/repr. Exception source lines/details are
omitted; a safe exception type remains. Processing is bounded by 128 record fields,
a 128-node value budget, depth 5, 32 entries per nested container and 4,096-character
text/output limits. Cycles terminate; long records are truncated. Very long/custom
structured output may lose formatting under the bound; arbitrary formatter behavior
is not certified. Two narrow ty compatibility comments bridge the unchanged legacy
Python-3.11 type target and the required Python-3.12+ logging clone interface.

Not covered as a universal guarantee: unlabelled/novel secrets, handlers installed
after setup without reinstallation, malicious custom handlers/formatters, pre-setup
bootstrap logs, direct stdout/stderr, subprocess or external-service logging. Uvicorn
raw access-log privacy is not certified: application completion events omit paths,
but access logs can still contain request paths. Redaction does not authorize
logging private payloads or claim GDPR/universal secret compliance. Real Worker/Beat
log output under production containers remains NOT RUN.

## 6. Protected metrics schema and precise semantics

Empty-instance JSON schema/example (no uptime, percentiles or SLA measurement):

```json
{
  "scope": "api_process_application_instance",
  "persistent": false,
  "http_requests_completed_total": 0,
  "http_responses_by_status_class": {"1xx": 0, "2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0},
  "http_request_duration_seconds": {"count": 0, "sum": 0.0},
  "http_server_errors_total": 0,
  "http_requests_cancelled_total": 0,
  "http_requests_incomplete_total": 0
}
```

Each application instance owns one lock-protected fixed set of counters. No raw
path, ID, request ID, exception, document or model-output labels/collections exist.
Completed means the final response-body message was successfully sent. Streaming
counts once at final-body completion; duration ends there and excludes later
background work. Pre-completion cancellation increments cancelled only. An incomplete
stream/other termination without a final body increments incomplete only. A generated
HTTP 500 with final body counts once in completed/5xx. Server errors mean completed
5xx responses, not every Python exception: failure after a completed 200 is not
rewritten as a 500 or double-counted. Incomplete/cancelled lifecycles are excluded
from duration count/sum. Metrics requests, including rejected API keys and the trailing
slash redirect, are excluded. Tests verify auth, exact counts/classes, durations,
concurrency isolation, cancellation/streaming and no self-observation.

Metrics are per API process/application instance, reset on restart, not persistent
and not aggregated across Uvicorn workers. Four production API workers therefore
have separate snapshots. This is not v0.7 execution observability or new workflow
recovery counters; no Redis aggregation or monitoring dependency was introduced.

## 7. Role-specific source contracts

| Role | Probe and boundary |
| --- | --- |
| API | Dockerfile invokes operational_probe api; local /api/v1/health, HTTP 2xx only, explicit 2s HTTP timeout, Docker hard timeout 10s; not readiness restart semantics |
| Worker | operational_probe worker targets celery@socket.gethostname(); control.ping destination/reply timeout 2s, exactly the intended pong required; Docker timeout 10s also bounds broker transport stalls; control plane only, no business task |
| Beat | Inherited API probe remains disabled; running process is not scheduler/delivery progress |
| Flower | operational_probe flower checks local /healthcheck, 2xx only/2s HTTP timeout/Docker 10s; HTTP responsiveness only, not authentication/broker/Worker certification |
| Migrate | Probe disabled; one-shot exit status remains the migration gate |
| Frontend | Production Compose Bun fetch /api/health with AbortSignal.timeout(5000), redirects rejected and 2xx required, Docker 10s; includes backend basic HTTP availability |

Shared backend image identity, preflight-before-stop, migration dependencies, project
resources, network topology, secure cookies, credentials and volumes are preserved.
Deployment tests change only the intentional Worker/Flower/frontend probe contracts
and retain unrelated Atomic 3 assertions. HTTP probe functions execute against
synthetic HTTP responses/errors; targeted Worker reply tests cover success, missing/
wrong/malformed replies and broker failure. The exact production Bun expression is
executed with synthetic fetch for success/failure/timeout rejection. No Docker Engine
or actual Celery remote control ran. Development and frontend-verification Compose
files are unchanged; they are not silently represented as the new production probes.

## 8. Truthful frontend health

The basic /api/health route retains healthy/upload-limit compatibility and adds a
3s abort budget, no-store and sanitized failures. New /api/health/ready reuses
backendFetch/BackendApiError with a 6s abort budget, no-store and redirect rejection.
An allowlisted parser preserves valid 503 not_ready nested checks/top-level entries,
rejects malformed/inconsistent bodies, bounds fields and drops unknown fields/raw
upstream errors. The parser keeps only known dependency codes or a fixed generic
failure code. No API key or metrics proxy is added.

The actual system page renders ready/not_ready/unavailable critical API status,
healthy/unhealthy dependency probes and separate configured/not_configured/unknown
optional capabilities. PostgreSQL/pgvector is one database entry; SELECT 1 does not
verify the extension. It removes Stripe/separate vector service, illustrative 90d
percentages and unmeasured p50 labels. Single-probe latency is labeled as such.
There is no basic-health fallback. Failed refresh clears previous readiness rather
than continuing to show it as current. One active request, an 8s browser abort,
controller identity/mounted guards and abort-on-unmount prevent overlaps/stale
replacement; manual and 30s periodic refresh remain. Tests render the actual page
with mocked transport and real Button, not a substitute page or real browser E2E.

## 9. Actual verification and execution boundaries

All backend collection/imports ran in a subprocess environment allowlist containing
only Windows PATH/SYSTEMROOT/WINDIR/TEMP/TMP plus explicit synthetic settings:
AGENTFORGE_ENV_FILE=none, ENVIRONMENT=local, DEBUG/DB_ECHO=false, synthetic required
credentials, loopback port1 DB/Redis, offline_no_connect DB, empty Provider keys and
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1. Anyio was explicitly loaded before collection.
The existing .venv tooling was used; no dependency install/upgrade. Windows asyncio/
Git-shell support required unsandboxed offline execution, not real DB access.
Frontend commands used installed package scripts with Bun --no-env-file and the
same allowlist. Initial frontend execution was corrected to explicitly disable
Bun dotenv autoload; no private configuration was inspected or credential values
printed. Full real-infrastructure suites and browser E2E were not invoked.

Exact successful backend invocations (cwd backend, isolated launcher calls pytest.main):

```text
.venv/Scripts/python.exe -c "import pytest,sys;sys.exit(pytest.main(['-p','anyio.pytest_plugin']+sys.argv[1:]))" tests/api/test_health.py tests/api/test_metrics.py tests/api/test_exceptions.py tests/core/test_operational_observability.py tests/core/test_deployment_contract.py -q --tb=short
.venv/Scripts/python.exe -c "import pytest,sys;sys.exit(pytest.main(['-p','anyio.pytest_plugin']+sys.argv[1:]))" tests/api tests/core tests/worker tests/workflow tests/knowledge tests/agent_runtime tests/composition tests/integrations tests/tool tests/schemas tests/workspace tests/test_core.py tests/test_version.py -q --tb=short
.venv/Scripts/ruff.exe check app tests cli
.venv/Scripts/ruff.exe format --check app tests cli
.venv/Scripts/ty.exe check
```

| Actual final check | Result |
| --- | --- |
| Backend focused command above | Exit 0; 132 passed, 54 existing Pydantic warnings, no failures/errors/skips |
| Backend broader selected offline command above | Exit 0; 1,269 passed, 150 Pydantic warnings, no failures/errors/skips; not the whole repository suite |
| Ruff check app/tests/cli | Exit 0, all checks passed |
| Ruff format --check app/tests/cli | Exit 0, 511 files already formatted |
| ty check | Exit 0, only two existing warnings in unchanged workflow durability/executor code |
| Frontend focused command below | Exit 0; 16 passed in 2 files, no failures/skips |
| Frontend complete configured Vitest unit command below | Exit 0; 1,034 passed in 40 files, no failed/skipped files/tests; excludes e2e by existing configuration |
| Frontend lint | Exit 0; 0 errors, 13 warnings from unchanged files, including an existing ignored coverage artifact |
| Frontend type-check | Exit 0 |

Exact successful frontend invocations (cwd frontend):

```text
bun --no-env-file run test:run --pool=forks --maxWorkers=1 --minWorkers=1 src/lib/health.test.ts "src/app/[locale]/(dashboard)/admin/system/page.test.tsx"
bun --no-env-file run test:run --pool=forks --maxWorkers=1 --minWorkers=1
bun --no-env-file run lint
bun --no-env-file run type-check
```

Initial backend focused result was 118 passed/1 failed: repeated redaction lost a
safe exception type, fixed without revealing exception details. Initial style/type
issues were corrected, including the explicit Python logging type-stub bridge.
Initial frontend type check found three test-only possible-undefined accesses;
corrected. Several page-test invocations were interrupted while diagnosing the
mock/barrel import boundary and an accidental returned beforeEach mock registered
as async cleanup. A single-503 debug run failed in that hook; the hook was corrected,
not product assertions removed. Diagnostic -t runs skipped unselected tests; these
are not the final coverage counts. Completed final commands above have no skips.
Frontend broad output includes existing React Query missing-queryFn, zustand storage
and Vite CJS deprecation diagnostics, not suppressed or reclassified as failures.

Ignored local artifacts/launcher/results are under .cache/atomic4-offline; they are
not new supported repository CLI or portable CI evidence. No historical tests/CI
have been relabeled as this task's executed checks.

## 10. Finding disposition and remaining verification

| Finding | Source/test disposition | Remaining runtime limitation |
| --- | --- | --- |
| P1-06 | Status-aware basic API HTTP probe with timeout; executable synthetic tests | Actual image/container probe NOT RUN |
| P1-07 | Worker/Flower role probes, disabled Beat/migrate inherited probe | Actual Worker/Flower/Beat/container behavior NOT RUN |
| P1-08 | Production frontend bounded Bun probe, exact synthetic expression execution | Actual production frontend probe NOT RUN |
| P1-09 | Optional configuration semantics; DB/Redis critical only; no Provider calls | Actual Worker/Provider connectivity NOT RUN |
| P1-10 | Atomic 2 safe codes retained, timeouts/acquisition/cleanup failures added | Real production dependency-failure exercise NOT RUN |
| P1-11 | Protected fixed-cardinality local metrics, schema/count/auth tests | Multi-process aggregation intentionally absent; no monitoring deployment |
| P1-12 | Output-handler/delegate redaction and Celery hooks, emitted-output tests | Production logging/bootstrap/third-party boundaries remain as documented |
| P2-02 | Basic/ready/role/correlation/metrics docs match source | No new production certification |
| Additional frontend finding | Explicit 503-preserving proxy and truthful actual page tests | Connected browser workflow and production runtime NOT RUN |

No Docker/WSL start, pull/build/container lifecycle, real DB/Redis access, migrations,
real Celery remote-control, commercial Provider call, network/proxy setting change,
monitoring infrastructure install, dependency/lock/CI/version change or Atomic 5
work. Atomic 3 resources/evidence are untouched. No branch/stage/commit/amend/push/
merge/PR/tag/Release operation. All changes local and unstaged; overall runtime
verification and Final Source Review remain pending.

## 11. Exact changed paths and handoff

```text
Makefile
backend/Dockerfile
backend/app/api/deps.py
backend/app/api/exception_handlers.py
backend/app/api/routes/v1/health.py
backend/app/core/logging.py
backend/app/core/metrics.py
backend/app/core/middleware.py
backend/app/main.py
backend/app/services/health.py
backend/app/services/operational_probe.py
backend/app/worker/celery_app.py
backend/tests/api/test_health.py
backend/tests/api/test_metrics.py
backend/tests/core/test_deployment_contract.py
backend/tests/core/test_operational_observability.py
docker-compose.prod.yml
docs/configuration.md
docs/deploy.md
docs/v0.13/atomic4-operational-observability.md
frontend/src/app/[locale]/(dashboard)/admin/system/page.test.tsx
frontend/src/app/[locale]/(dashboard)/admin/system/page.tsx
frontend/src/app/api/health/ready/route.ts
frontend/src/app/api/health/route.ts
frontend/src/lib/health.test.ts
frontend/src/lib/health.ts
```

Exact scope: 26 paths. Other tracked source, test infrastructure, durability/Agent/Tool/MCP/Knowledge business code, migrations, dependencies/locks, version metadata and historical Atomic/roadmap documents remain unchanged. Makefile changes only the stale prod help description. Final verification: main at the required HEAD/tag, empty staging, exact 18 modified tracked + 8 authorized untracked paths, git diff --check exit 0 and whitespace checks for all 8 untracked files passed. Final status and file hashes are recorded in the implementation handoff (.cache/atomic4-offline/final-verification.json).

Await ChatGPT Implementation Report Review; do not declare Final Source Review PASS or Atomic 4 COMPLETE.
