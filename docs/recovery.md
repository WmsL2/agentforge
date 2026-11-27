# Paired database and private-media recovery

This is a runbook for a separately authorized operation. Atomic 5 exercised
offline failure injection only. **Paired restore drill: NOT RUN.** The revised
v0.13 roadmap treats a production disaster-recovery drill as optional.

## Durable inventory

- PostgreSQL 16 with the release-compatible pgvector extension is the system of
  record. It contains workspace access and document metadata, workflow runs and
  immutable definition snapshots, checkpoints, approvals and claim/lease
  generations, parsed knowledge content, indexing jobs, chunks and the active
  index generation. Record the actual extension and Alembic revisions.
- Private original media belongs to the matched database recovery point.
  Document rows hold relative storage keys and original hashes. Search/index
  recovery uses database parsed content and generations. That does not replace
  original files for authenticated download.
- Redis 7 serves as broker, cache and result backend under the current
  configuration. Its volume and durability settings are a separate concern.
  Workflow and index recovery scanners use durable database state to discover
  recoverable work. Broker queues and cache entries do not replace the paired
  backup.

## Capture a paired recovery point

1. Obtain authorization for the exact project, application release, database,
   storage root, account, maintenance window and destination. Verify sufficient
   storage and a compatible restore target. Use least privilege and an
   approved secret source. Keep credentials out of shell history and manifests.
2. Close admission for uploads, deletes, workflow submissions, approvals,
   indexing and other writers. Drain API requests, worker jobs and in-flight
   filesystem writes and database transactions, then stop or otherwise exclude
   relevant writers, including schedulers, jobs and administrative automation.
   Record any work that had to be interrupted. A local lock or boolean
   confirmation does not establish quiescence across processes.
3. During that same quiescent interval, record the release/tag, immutable image
   identity where available, Alembic revision, PostgreSQL major/extension
   versions and start/end times. Use a compatible PostgreSQL client and a
   logical dump such as pg_dump custom format for the named database. Inventory
   required roles and grants separately. Verify that the dump completed and
   its archive catalog is readable.
4. Copy the private media using a tool that preserves required access metadata
   and does not follow symlinks outside the storage boundary. Record relative
   paths, sizes and SHA-256 hashes. Validate the inventory against the database
   and record any unresolved missing references or unexplained files.
5. Give the database dump, media copy and manifest the same backup identity.
   Record artifact checksums, source release/revision, timestamps, verified
   writer exclusions and outstanding recovery work. Store the pair together
   under the approved retention policy, with encryption in transit and at rest,
   access controls and audited access. Choose retention and key-management
   policy for the environment. These are operational requirements and are not
   implemented backup automation.

Illustrative PostgreSQL commands are for a separately authorized maintenance
session. Replace every angled placeholder and supply credentials only through
the approved PostgreSQL client configuration. Verify the resolved source or
target before running any command.

```text
pg_dump --format=custom --file=<STAGED_BACKUP_ARCHIVE> --dbname=<APPROVED_SOURCE_SERVICE>
pg_restore --list <STAGED_BACKUP_ARCHIVE>
pg_restore --exit-on-error --single-transaction --dbname=<ISOLATED_DISPOSABLE_TARGET_SERVICE> <VERIFIED_BACKUP_ARCHIVE>
```

## Restore into isolation

1. Obtain separate authorization for an empty, disposable project/database,
   media root and broker. Keep ingress and automated workers/scanners closed
   during restore. Confirm target identity, application release compatibility,
   PostgreSQL major version and the pgvector version found in the manifest.
   Prepare required target roles before restore. Do not point at a live database.
2. Validate the manifest and both artifact hashes. Restore the database and
   media from the same manifest. Verify the Alembic revision directly from the
   restored database and the installed vector extension. Treat any later schema
   migration as a separately approved operation.
3. Compare every referenced storage path and digest with the restored original.
   Verify permissions and authenticated workspace-scoped download, including a
   denied cross-workspace request. Inspect active index generation and chunks,
   and check retrieval using separately approved, isolated dependencies.
4. Review pending or expired workflow and index work, immutable snapshots,
   approval state and checkpoint continuity. Use fresh isolated Redis state
   unless a separately reviewed plan proves an older queue is appropriate.
   Verify the bounded recovery scanners against disposable targets before
   reopening admission. Duplicate broker delivery is possible. Existing database
   fences protect committed state; external node effects may replay. Do not
   manually clear leases or change business status without a separate decision.
5. Reconciliation is preview-only. Its complete DB inventory can be stale by
   the time storage is listed. A candidate may be an upload in progress or a
   file retained after ambiguous commit. Any separately approved destructive
   maintenance requires all relevant writers and in-flight transactions and
   filesystem writes drained, refreshed inventory, candidate identity and
   containment checks, explicit approval of the reviewed list and a verified
   recovery point. There is no application apply command.

## Resume criteria and recovery objectives

Before resuming, require verified paired integrity, matching schema and
application release, appropriate API/dependency and worker health evidence,
authorized download/retrieval checks, expected scanner behavior and no
unresolved destructive cleanup. Record the results and owner approval before
restoring admission. An isolated verification does not itself authorize a
production cutover.

Recovery Point Objective (RPO) is the acceptable age of data loss at recovery.
Plan the paired capture cadence, retention and write-quiescence window around
that target. Recovery Time Objective (RTO) is the acceptable elapsed time to
resume service. Budget for authorization, provisioning, restore, integrity
checks, scanner verification and the return to service. Measure both in an
authorized exercise before asserting achievable values. No measurements were
made in Atomic 5.
