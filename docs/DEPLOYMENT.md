# Hosted Deployment Target

This document defines the intended hosted architecture. The current JSON/filesystem/thread implementation remains the local testing adapter until the production boundaries are introduced.

## Cloudflare's role

Use Cloudflare for:

- DNS and managed TLS
- Proxy/WAF/rate limiting
- Pages hosting for the Vite build
- R2 object storage for source audio and generated assets
- Access for a private staging environment
- Turnstile for public abuse controls if needed

Do not run Demucs in Cloudflare Workers. Model loading, FFmpeg, long-running CPU/GPU inference, memory requirements, and local scratch space require ordinary containers or VMs.

## Target topology

```text
app.example.com       Cloudflare Pages (React/Vite)
api.example.com       Cloudflare proxy -> FastAPI containers
private R2 bucket     Sources, stems, logs, exports
PostgreSQL            Users, jobs, assets, rights, durable progress
Redis                 Job queue, leases, transient progress events
Worker containers     FFmpeg + Demucs + temporary scratch disk
```

The API and worker may initially share one host, but they must remain separate processes and deployment units.

## Production upload and processing flow

1. The authenticated browser creates an upload session through FastAPI.
2. FastAPI checks quotas and creates `job` and `asset` rows in PostgreSQL.
3. FastAPI returns short-lived signed R2 multipart-upload instructions.
4. The browser uploads directly to R2 and displays byte progress.
5. The browser finalizes the upload through FastAPI.
6. FastAPI verifies object ownership, size, checksum, and expected key before queuing the job.
7. A worker leases the job from Redis, downloads the source to isolated scratch space, and validates it with ffprobe.
8. The worker streams Demucs progress into PostgreSQL at a throttled rate and optionally publishes transient events through Redis.
9. The worker uploads stems/logs to R2, commits asset records, marks the job complete, acknowledges the queue message, and erases scratch files.
10. The browser polls `GET /api/jobs/:id`; completed playback/download uses short-lived signed R2 URLs.

Large media should not pass through Cloudflare Pages, a Worker, or the FastAPI request body. Direct R2 upload avoids plan-dependent proxy request-size and request-duration limits.

## Build-time and API origins

Prefer same-origin `/api` routing when convenient. If Pages and FastAPI use separate hostnames:

- build Vite with `VITE_API_BASE_URL=https://api.example.com`,
- start FastAPI with `KARAOKE_CORS_ORIGINS=https://app.example.com`,
- restrict CORS to exact staging/production origins rather than `*`,
- decide on bearer-token or cookie authentication before enabling cross-origin credentials.

## Persistence contracts

### JobRepository

Responsibilities:

- create and retrieve user-owned jobs
- enforce idempotent state transitions
- persist progress, ETA, attempts, errors, and worker heartbeat
- list only the authenticated user's jobs
- mark abandoned leases retryable

Adapters:

- `LocalJobRepository`: current `job.json` behavior
- `PostgresJobRepository`: hosted implementation

### MediaStorage

Responsibilities:

- create upload/download authorizations
- verify media metadata and ownership
- open worker download/upload streams
- delete all objects belonging to a job

Adapters:

- `LocalMediaStorage`: current job directories
- `R2MediaStorage`: S3-compatible R2 implementation

### JobQueue

Responsibilities:

- enqueue a job ID, not media bytes
- lease work with visibility timeout/heartbeat
- retry transient failures with a bounded backoff
- dead-letter permanent or exhausted failures

Adapters:

- `LocalJobQueue`: current single-worker executor
- `RedisJobQueue`: hosted worker queue

## Job state machine

```text
created -> uploading -> queued -> validating -> separating -> finalizing -> completed
                   \          \             \             \-> failed
                    \-> expired \-> cancelled
```

Transitions must be transactional and idempotent. A retry starts separation from the beginning because Demucs does not provide a mid-track checkpoint. Existing complete assets must never be exposed until the final database transaction succeeds.

## Initial production schema

### users

- `id`, authentication provider ID, email, created timestamp

### jobs

- `id`, `user_id`, original filename, quality profile
- status, progress, ETA, current/total pass
- attempt count, worker lease/heartbeat, error
- rights attestation timestamp
- created/updated/completed timestamps

### assets

- `id`, `job_id`, kind, R2 key
- MIME type, byte size, checksum, duration
- created timestamp and retention/deletion timestamp

### job_events (optional)

- append-only state changes and important processing events for support/auditing

## HTTP progress transport

Start with polling:

- one request every 1–2 seconds while active
- slow to 5–10 seconds while the tab is hidden
- return `Cache-Control: no-store`
- support ETag/`If-None-Match` or `updated_at` to reduce response payload
- stop polling at a terminal state

Polling is resilient across reloads and API replicas because PostgreSQL is authoritative. If active-job volume makes polling expensive, add Server-Sent Events backed by Redis Pub/Sub while retaining polling as reconnect/fallback behavior. WebSockets are not required for one-way job updates.

## Security requirements before public access

- Authenticate every job/media endpoint.
- Scope every query by `user_id`; never expose a global job list.
- Keep R2 buckets private and use short-lived signed URLs.
- Restrict R2 CORS to production/staging frontend origins and required methods.
- Validate object key, size, checksum, extension, decoded streams, and duration.
- Set per-user concurrent-job, daily processing-minute, upload-size, and retained-storage quotas.
- Rate-limit upload creation and job finalization.
- Run workers without cloud control-plane credentials except narrowly scoped R2 access.
- Use non-root containers, read-only base filesystems where practical, and bounded scratch volumes.
- Delete scratch media in `finally` paths and apply R2 lifecycle retention.
- Store secrets in the hosting provider's secret manager, never Vite variables.
- Add account deletion, audit logging, abuse reporting, and takedown handling.

## Deployment sequence

### 1. Production-compatible local stack

- Introduce repository/storage/queue interfaces.
- Add Docker images for API and worker.
- Run PostgreSQL, Redis, and an S3-compatible development store through Docker Compose.
- Keep the existing local adapters for fast offline development and tests.

### 2. Private staging

- Deploy Vite to Cloudflare Pages.
- Provision R2 and configure private bucket CORS/lifecycle rules.
- Deploy FastAPI and one CPU worker to the selected container/VM provider.
- Provision managed PostgreSQL and Redis.
- Put staging behind Cloudflare Access.
- Test browser reload, API restart, worker retry, duplicate finalization, cleanup, and large multipart uploads.

### 3. Public beta

- Add application authentication and ownership enforcement.
- Add quotas, rate limits, Turnstile where useful, monitoring, alerts, and backups.
- Benchmark cost and queue delay with CPU workers; add GPU workers only if latency/cost data supports it.
- Complete legal/terms/privacy/takedown review before accepting public uploads.

## Hosting decision still required

Cloudflare does not supply the Demucs compute in this design. Choose an origin/worker provider based on measured runtime, RAM, GPU need, and expected concurrency. Reasonable first options include:

- a single Docker-capable VPS for inexpensive private staging,
- a managed container platform for simpler operations,
- a cloud container service plus autoscaled CPU/GPU workers for larger production use.

Do not pick the final compute provider until real-song benchmarks establish CPU time, peak RAM, scratch usage, and desired queue latency for each quality profile.
