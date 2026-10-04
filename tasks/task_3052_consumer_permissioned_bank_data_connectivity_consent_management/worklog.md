# Worklog — task_3052_consumer_permissioned_bank_data_connectivity_consent_management

## Step 1: Create task directory — 2026-09-29T18:20:00.000Z

Pre-allocated task directory `./tasks/task_3052_consumer_permissioned_bank_data_connectivity_consent_management/` with `workspace/` verified to exist (per command args; no new index computed).

## Step 2: Generate scaffold — 2026-09-29T18:45:00.000Z

All three files exist, are non-empty, and pass lint. Here's the summary:

**Files written (all three required, verified non-empty via `wc -l`):**
- SCAFFOLD.yaml — 1402 lines
- SCAFFOLD_DIFFICULTY_DESIGN.yaml — 1277 lines
- SCAFFOLD_CORNER_DESIGN.yaml — 1413 lines

**SCAFFOLD.yaml (§1.0–§1.7) counts:**
- Entities: 13 (Institution, InstitutionAgreement, Recipient, ConsentRecord, Connection, DataScopeGrant, DataProductTier, RefreshJob, WebhookEvent, BreakageEvent, DataDeletionRequest, RecipientTierAssignment, AuditLog)
- State machines: 7 (Recipient — branching with appeal/suspend cycles; ConsentRecord — REVOKED/EXPIRED/SUPERSEDED terminals; Connection — cyclic ACTIVE↔REAUTH_REQUIRED/BROKEN + MIGRATING branch; RefreshJob; DataDeletionRequest; Institution health — ACTIVE↔DEGRADED↔BROKEN; InstitutionMigration)
- Calculations: 8 (health thresholds with dual variants, 3-input scope coverage, rolling-window rate limit, cadence gate, tiered monthly cost with provisional/final variants, reauth cooldown, deletion propagation, webhook fanout)
- Validations: 20 (priorities 1–20, spanning auth/existence/state/SoD/consent-gating/minimization/tier/agreement/temporal/fiscal/uniqueness/referential)
- Endpoints: 47 (including `/_clock/set_current_utc` with pinned default 2026-09-01T00:00:00Z)
- Errors: 20
- Roles: 4 (PlatformAdmin opaque, ComplianceReviewer opaque, Consumer opaque w/ consumer_ref, Recipient entity_backed:Recipient) — segregation_of_duties model
- Complexity profile: access_control_matrix + event_sourcing; layers: cascading_side_effects, derived_field_reconciliation, optimistic_concurrency, scheduled_actions; 2 OCC concurrency rules

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8): 18 instances** — 2 per each of the 9 difficulty rules, all with structured `setup_api_calls`/`trigger` chains and pre-computed literal asserts (e.g. provisional cost 400 vs final 0; health BROKEN→ACTIVE post-recover; boundary at exactly 3600s cadence; closed-vs-half-open interval contrast).

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9): 33 instances** — 30 active test recipes + 3 `excluded_because` stubs citing §1.8 instances. Sections: entities (5), state_machines (5), calculations (3), validations (5 active + 1 stub), endpoints (3 active + 1 stub), errors (4), rbac (2), cross_cutting_complexity_layers (2 active + 1 stub), consistency_model (1).

**Lint verdict (verbatim):**
```
Coverage
  §1.5 endpoints declared:    47
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     30
  Calls scanned (§1.8+§1.9):  448

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Additional manual checks passed: all 20 error codes referenced by validations/designs, instance names unique across both design files, all `grounds` resolve, no forbidden concurrency vocabulary, all call roles match endpoint roles, and all OCC `expected_*_version` payloads are `${var}` placeholders (or `${var} - 1` expressions for deliberate stale-version negative tests).

**Difficulty-maximizing mechanics embedded:** dual-variant calculations on two different entity domains (institution health window semantics; connection billing finalized-vs-provisional with ceil-projection), a depth-3 cascade (recipient suspend → consent revoke → connection disconnect → webhook fanout), state-vs-OCC and safety-vs-constraint validation priority conflicts, refresh-state gate interplay (BROKEN connections block refresh so institution health accumulation requires reauth interleaves), institution-level breakage cascade prompting re-auth fleet-wide, and closed-vs-half-open interval contrast between migration windows and consent expiry.

(First Step 2 subagent attempt exited without writing files; retried successfully.)

## Step 3: Copy shared files — 2026-09-29T18:55:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_3052_consumer_permissioned_bank_data_connectivity_consent_management/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-29T19:01:00.000Z

All checks pass. The PRD is complete and verified at `workspace/PRD.md`.

**Line count:** 306 lines.

**Per-scaffold-section coverage audit:**

- **§1.0 Response envelope** — rendered verbatim as §2.2 (fixed canonical block, byte-identical including `req_RANDOMALPHANUM123456` and empty `"data": { }`); pagination defaults (limit 10/min 1/max 100, offset 0, `created_at` ascending sort, meta fields) in §2.3.
- **§1.1 Entities (13, 49 fields)** — every field name appears in backticks (mechanical diff: 49/49 entity fields, 38/38 endpoint input identifiers, 8/8 path params present, 0 missing). Entity attributes are scattered across §3.1–§3.12 narratives (institution fields in §3.1, recipient in §3.2, tier in §3.3, consent in §3.4–3.5, connection in §3.6, refresh job in §3.7, webhook in §3.10, deletion request in §3.11, audit log in §2.6). `common_fields: false` entities (DataScopeGrant, WebhookEvent, BreakageEvent, AuditLog) are explicitly stated in §2.5 to lack `updated_at` and `version`.
- **§1.2 State machines (7)** — all transitions rendered with exact state strings: Recipient (6 transitions incl. SoD preconditions and full rejection/suspension cascades), ConsentRecord (revoke/expire/supersede with identical cascade machinery and fan-out rule), Connection (12 transitions incl. all five consent-driven DISCONNECTED edges and the failed-reauth BROKEN/REAUTH_REQUIRED sibling), RefreshJob (QUEUED→SUCCEEDED/FAILED with all five gates and per-failure-reason effects), DataDeletionRequest (PENDING→PROPAGATING, both ack branches, ACKED_BY_ALL→COMPLETED), Institution health (5 transitions incl. the ACTIVE→BROKEN jump and lazy DEGRADED→ACTIVE aging), InstitutionMigration (start/complete with completion gate).
- **§1.2.1 Concurrency rules (2)** — both OCC rules in §2.7 with exact `expected_recipient_version`/`expected_institution_version` fields, parent entities, `ERR_STALE_VERSION`/412, and stale-view framing (no race-condition language).
- **§1.3 Calculations (8)** — all rendered as precise prose: health thresholds (3/5 over 86400 s, inclusive boundary, post-recovery exclusion), scope coverage (set-difference semantics with STRICT/STANDARD/BROAD forbidden sets), rate-limit window (trailing 3600 s, any-status executions, equality rejects), cadence gate (exactly 3600 passes, 3599 fails, null passes), monthly cost (full unit-cost matrix 2/1, 4/2, 8/3; free allowances 10/20/40; 100 cents/unit; calendar-month UTC bounds; `include_pending` provisional variant with 604800-second week ceiling), reauth cooldown (equality passes), deletion propagation set difference, webhook fan-out count. All constants embedded with unit conversions (86400 s = one full day).
- **§1.4 Validations (20)** — all 20 checks rendered with error_id pairing; the full priority ordering is explicit in §2.9 (numbered 1–20 with prose rationale and worked precedence examples).
- **§1.5 Endpoints (47)** — §4 table has exactly 47 rows, 4 columns each, roles matching scaffold; status-code rules (201 creates / 200 modifications) stated above the table.
- **§1.6 Errors (20)** — all 20 ids appear in §2/§3 narrative trigger contexts and in the 2-column §5 table.
- **§1.7 Roles (4)** — all four roles spelled exactly; §2.1 translates each `identity:` field (three opaque roles incl. Consumer's `X-User-ID == consumer_ref` semantics, Recipient entity-backed); exclusive vs shared operations reflected in the §4 Authorized Role(s) column.

**Hard contract reports:**

```
Field coverage check:
- entities[].fields: 49 required, 49 present, 0 missing
- endpoints[].request_body: 38 required, 38 present, 0 missing
- endpoints[].query_params/path_params: 8 required, 8 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] priority: 20 checked, 20 expressed (full §2.9 ordering), 0 missing
- concurrency_rules[] OCC: 2 checked, 2 expressed (endpoint + expected_*_version + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: 41 checked, 41 expressed, 0 missing
- calculations[]: 8 checked, 8 expressed, 0 missing
- validations[] conditions: 20 checked, 20 matchable to error_id, 0 missing
- endpoints[].side_effects / applies_to: checked, expressed, 0 missing
- sibling-branch symmetry: ack branches, failure-reason branches, reauth valid/invalid branches, 5 DISCONNECTED edges — all symmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 406
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Zero-silence risk areas deliberately expanded:** the `QUEUED` initial state of RefreshJob (added explicitly in §3.7 after the first audit flagged it); the non-final ack self-transition on DataDeletionRequest (made explicit); the `post_recover_reset` health variant (`last_recovered_at` exclusion); the direct `ACTIVE`→`BROKEN` burst transition; the webhook fan-out count definition; per-failure-reason behavior of `TRANSIENT`/`RATE_LIMITED` (no connection move); and agreement-before-method gate ordering at connection create/complete_auth.

## Step 5: Generate unit tests — 2026-09-29T19:25:00.000Z

## Files written

**`test_helpers/` (9 files):**
- `test_helpers/__init__.py` — barrel export (framework generics + PRD-specific)
- `types.py` — entity TypedDicts (append-only DataScopeGrant/WebhookEvent/BreakageEvent/AuditLog omit `updated_at`/`version`) + status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint + `canonical_instant` ISO-8601 normalizer
- `api_errors.py` — `ApiErrorId` enum (20 errors) + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions + connectivity-mode/single-active-agreement invariants
- `factories.py` — payload factories (input fields only)
- `constants.py` — thresholds (86400 window, 3/5 breakage, 3600 cadence/rate windows, unit costs, free allowances, minimization forbidden sets, clock default)
- `test_users.py` — opaque admin/reviewer header builders, `make_consumer_headers(consumer_ref)`, entity-backed `make_recipient_headers(recipient_id)`
- `fixtures.py` — composite fixtures: `create_institution_with_agreement`, `create_approved_recipient` (SoD-safe creator/reviewer), `capture_consent` (OCC version re-read), `setup_active_stack`, `drive_consecutive_failures` (auto-reauth on BROKEN), `add_active_connection`, `open_deletion_request`

**`test_suite/` (19 files):** `conftest.py` + 18 test files (`test_01`–`test_09` difficulty, `test_10`–`test_18` corner by section).

## Test counts (orchestrator-verified on disk)

- **Total: 63 tests** — `grep -rh "^def test_"` = 63; every docstring ends with exactly one valid `Design:` tag; all tags resolve to existing instances.
- **Queue A (§1.8 difficulty): 34 tests** — 17 instances × 2 tests each.
- **Queue B (§1.9 corner): 29 tests** — 29 instances × 1 test each.

## Instances skipped (two-condition filter failures)

1. **Queue A — `Difficulty/priority_pair_validation_conflict/conflict_state_beats_stale_version_on_consent_create`**: PRD does not uniquely derive the asserted outcome. PRD §3.4 maps consent-capture against a non-APPROVED (SUSPENDED) recipient to `ERR_PARENT_NOT_OPERABLE` (422), never to the asserted `ERR_INVALID_STATE` (409); and per PRD §2.9 ordering the OCC check (priority 6) precedes parent operability (priority 8), so a PRD-only reader could return `ERR_STALE_VERSION`. No weakening applied — instance skipped.
2. **Queue B — `Corner/endpoints/migrate_rejected_before_window_opens`**: the scenario fails the temporal condition (clock before window) and the `migration_state == IN_PROGRESS` condition simultaneously. PRD §3.8 maps temporal failures to `ERR_MIGRATION_WINDOW_CLOSED` "or" state conditions to `ERR_INVALID_STATE` without pinning precedence between them, so the asserted `ERR_MIGRATION_WINDOW_CLOSED` is not uniquely derivable — skipped.

## Stubs not translated (as specified)

- `Corner/validations/agreement_scope_not_permitted_on_connection_create` (cross-ref verified: resolves to difficulty instance `dependency_connection_create_requires_consent_active`, which is covered)
- `Corner/endpoints/cost_summary_computed_read_matches_formula` (covered by `dual_variant_connection_cost_final_vs_provisional`)
- `Corner/cross_cutting_complexity_layers/occ_stale_version_on_consent_create_after_suspend` (points to the skipped instance above — pointer resolves, no test emitted)

## Confirmations

- Every test docstring ends with exactly one `Design: Difficulty/<rule_id>/<instance>` or `Design: Corner/<section>/<instance>` line, copied verbatim from the yaml `name:` fields (AST-verified: 63/63; orchestrator re-verified via grep — 34 difficulty tags ×2, 29 corner tags ×1).
- All PRD docstring citations spot-checked with literal `grep` against `workspace/PRD.md` — all matched.
- No `skip`/`skipif`/`xfail` markers; no scaffold references in generated code comments/docstrings.
- All `test_suite` imports resolve against `test_helpers` exports; both packages compile and `import test_helpers` succeeds.
- No freelance tests — every test traces to exactly one design-index instance.

(Note: subagent's self-reported counts were internally inconsistent in its prose; orchestrator verified authoritative numbers directly from disk: 63 tests, 34 A + 29 B, all tags unique-resolving.)

## Step 6: Generate implementation — 2026-09-29T19:45:00.000Z

**Task:** task_3052_consumer_permissioned_bank_data_connectivity_consent_management — Python + Flask implementation generated from PRD.md + SCAFFOLD.yaml (test_suite/ and test_helpers/ were not read).

**Files written (all via Write/Edit, all under `workspace/implementation/`):**
- `start.sh` (executable, guarded pip install, `exec python3 app.py`, `$PORT` default 10000, binds 0.0.0.0)
- `requirements.txt`, `app.py`, `db.py` (in-memory dicts only, logical clock default 2026-09-01T00:00:00Z, no seeding), `errors.py` (20 error IDs), `response.py` (envelope: `meta`/`response_type`/`data`, pagination `limit`/`offset`/`total_count`/`has_more` in meta), `middleware.py` (X-User-ID/X-User-Role auth)
- `services/core.py` (clock, consent termination cascades, institution health recompute, audit/webhook helpers), `services/serializers.py`
- `routes/`: `clock.py`, `institutions.py`, `recipients.py`, `tiers.py`, `consents.py`, `connections.py`, `webhooks.py`, `deletion.py`, `audit.py`

**Endpoints implemented:** all 47 from the endpoint table, including `POST /_clock/set_current_utc` (eager expiry sweep + institution aging).

**State machines:** all 7 — Recipient (6 transitions w/ SoD), ConsentRecord (REVOKE/EXPIRE/SUPERSEDE w/ re-point-or-disconnect), Connection (13 transitions), RefreshJob (sync execute), DataDeletionRequest (PENDING→PROPAGATING→COMPLETED), Institution health (rolling 86400s window, thresholds 3/5, inclusive boundary, recovery reset), InstitutionMigration (NOT_STARTED→IN_PROGRESS→COMPLETE).

**Calculations:** all 8 — health status, scope coverage (minimization + tier + agreement), rate limit window (3600s, `>=` rejection), refresh cadence (3600s, exact boundary passes), monthly refresh cost (unit-cost matrix LOW/MEDIUM/HIGH, free allowances 10/20/40, `include_pending` weekly-projection variant with `ceil(gap/604800)`), reauth cooldown (equality passes), deletion propagation (required = DATA_DELETED webhook recipients), webhook fanout count.

**Validation priority handling:** implemented in PRD §2.9 order — auth(1) → authz(2) → path existence L-to-R(3) → SoD(4, checked for current state's prior decision actor before state legality) → state(5) → OCC(6: `expected_recipient_version`, `expected_institution_version`) → consent gating(7) → parent operability(8) → minimization(9) → tier coverage(10) → agreement coverage(11) → migration window(12) → reauth cooldown(13) → rate limit(14) → cadence(15) → method legality(16) → uniqueness(17) → migration completion gate(18) → ack integrity(19) → field validity(20).

**Boot verification evidence:** launched `PORT=18753 bash start.sh` (PID 4085488), full end-to-end smoke passed: institution+agreement create (201, version OCC 412 on stale), recipient create/review (SoD 422 on same-actor, APPROVED by different reviewer), tier+assignment, consent capture (ACTIVE, grants materialized), connection create/complete_auth (ACTIVE + initial FULL job), refresh SUCCEEDED with TRANSACTIONS_AVAILABLE webhook, cost_summary correct (units=4 for 2 FULL LOW jobs), clock set returned `now_iso8601` + `expired_consent_ids`, revoke cascade (REVOKED + connections DISCONNECTED + CONSENT_REVOKED webhook), refresh-after-revoke → ERR_INVALID_STATE, deletion request PROPAGATING → recipient ack → COMPLETED with grants purged (0 on re-read), audit log contained `recipient.approve`, `consent.revoke`, `deletion.completed`. Killed exactly PID 4085488; confirmed stopped.

## Step 7: Test-iterate fix loop — 2026-09-29T20:15:00.000Z

All 8 rounds pass 63/63. Sweep is clean.

**Iterations run:** 2 (first sweep: 60/63 × 8 rounds with identical 3 failures; second sweep after fixes: 63/63 × 8 rounds, clean).

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — `drive_consecutive_failures`: the auto-reauth that reopens a BROKEN connection now only fires between failures (`i < count - 1`), never after the final one. Previously the helper reopened the connection even after the last failure, so `test_institution_degraded_at_three_breakage_events` observed ACTIVE/cf=0 instead of the PRD §3.7-mandated BROKEN. Docstring updated to record the new contract.

**Fixes applied to `test_suite/`:**
- `test_suite/test_05_difficulty_priority_conflicts.py` — `_strict_recipient_on_balance_only_tier`: removed the orphaned direct `create_tier("BalOnly", ...)` call. `create_approved_recipient(..., tier_name="BalOnly")` already creates the tier internally; the pre-create produced a duplicate `tier_name` that the implementation correctly rejects with `ERR_DUPLICATE_ACTIVE` (PRD line 155: tier_name is unique). The direct `tier` variable was never used.

**Fixes applied to `implementation/`:** none — the implementation was PRD-faithful in both cases (verified by manual end-to-end repro against fresh servers before touching any code).

**Key diagnostic findings:**
- Both bugs reproduced deterministically against a fresh single server via the exact helper path, but not via equivalent raw-curl/manual sequences — isolating them as test-artifact bugs rather than implementation or runner-isolation bugs.
- Forensic trace (`/tmp/prd_bench_server_<port>.log` correlated by boot count) confirmed the server really restarted per test and the 409/BROKEN responses came from within a single fresh boot, ruling out cross-test state bleed.

(Orchestrator verified all 8 results.{1..8}.json files: 63/63 in every round.)

## Step 8: Finalize PRD — 2026-09-29T20:20:00.000Z

Done. `PRD_FINALIZED.md` exists at `workspace/PRD_FINALIZED.md` as a verbatim copy of `PRD.md` — a zero-diff outcome.

**Line counts / %-delta:** PRD.md = 306 lines, PRD_FINALIZED.md = 306 lines, 0% delta (files identical).

**Changes:** None. Both Step 7 items were pure test-artifact bugs against behavior the PRD already pins; the implementation was PRD-faithful in both cases (Step 7's own conclusion, confirmed by my code reading).

- **Item 1 — `drive_consecutive_failures` fixture fix (no PRD edit):** The helper previously re-opened a BROKEN connection even after the final failure, masking the terminal BROKEN state. The behavior the test wanted to observe is already pinned: PRD §3.7 (line 197) says an `INSTITUTION_DOWN` failure bringing `consecutive_failures` to 2 moves the connection to `BROKEN`, and §3.1 (line 139) pins BROKEN at 5+ breakage events in the trailing 86400s window. Implementation matches at `implementation/routes/connections.py:148-151` and `implementation/services/core.py:179-184`. No PRD silence or mismatch.
- **Item 2 — `_strict_recipient_on_balance_only_tier` test fix (no PRD edit):** The orphaned duplicate `create_tier("BalOnly", ...)` was correctly rejected with `ERR_DUPLICATE_ACTIVE` because PRD §3.3 (line 155) already declares `tier_name` unique, and §2.9 priority 17 assigns uniqueness constraints to `ERR_DUPLICATE_ACTIVE`. Implementation matches at `implementation/routes/tiers.py:48-50`. No PRD silence or mismatch.

**Per-edit pre-edit search log** (mandatory enumeration even though no edit was committed):

- *Candidate edit subject: tier `tier_name` uniqueness.* Impl paths enumerated: `create_tier` (`implementation/routes/tiers.py:27-60`) — the only path touching `tier_name`; uniqueness is checked against **all** tiers (`db.tiers.values()`), active or not. Parallel uniqueness patterns confirmed at `implementation/routes/institutions.py:62-64` (institution `name`) and `implementation/routes/recipients.py:57-59` (recipient `name`), both already pinned by PRD lines 135 and 145. Wording adjustment: none needed — the existing PRD text ("a unique `tier_name`") is unqualified and therefore already consistent with the implementation's global uniqueness check; any inserted clarification risked narrowing it (e.g. "unique among active tiers" would have been a new false claim).
- *Candidate edit subject: connection BROKEN transition on consecutive INSTITUTION_DOWN failures and institution health thresholds.* Impl paths enumerated: `_execute_refresh` (`implementation/routes/connections.py:85-155`, esp. 148-151 — connection → BROKEN only from ACTIVE at consecutive_failures ≥ 2), `complete_auth` failure path (`connections.py:300-315`), `recompute_institution_health` (`implementation/services/core.py:159-196` — window `>= clock-86400`, strictly after last recovery, BROKEN ≥ 5 / DEGRADED 3-4 / ACTIVE < 3), `_institution_broken_side_effects` (`core.py:199-210` — ACTIVE/MIGRATING connections → REAUTH_REQUIRED plus `INSTITUTION_BROKEN` webhooks), and `recover_institution` (`implementation/routes/institutions.py:108-118` — flips to ACTIVE, stamps recovery, bumps version; connections stay REAUTH_REQUIRED). Every enumerated path matches the existing §3.1/§3.7 prose verbatim, so no wording change was committed.

## Step 9: PRD completeness scan — 2026-09-29T20:40:00.000Z

Done. `workspace/PRD_COMPLETED.md` is written.

**Source**: `PRD_FINALIZED.md` (306 lines / 46,907 chars) → `PRD_COMPLETED.md` (308 lines / 52,375 chars, +5,443 chars, 19 edit sites).

**Coverage of the impl walk**: all 9 route files (clock, institutions, recipients, tiers, consents, connections, webhooks, deletion, audit), both service modules (core.py — cascades, health recompute, OCC, cost math; serializers.py), middleware (auth + pagination), response envelope, and app-level error handlers — every endpoint, gate order, state transition, default, and error path was cross-checked against the PRD.

**Counts**: 18 ambiguity-pins, 3 mismatch-revisions (one edit site contains both).

Per-change bullets:

- §2.9 item 17 — insert — ambiguity — name uniqueness for institutions/recipients/tiers classified under `ERR_DUPLICATE_ACTIVE` — implementation/routes/institutions.py:62-64, recipients.py:57-59, tiers.py:48-50
- §2.9 item 8 — insert — ambiguity — ownership gates (`consumer_ref`/webhook-target match) evaluated at the parent-operability layer, after state legality — implementation/routes/connections.py:279, consents.py:210-214, deletion.py:36-42, webhooks.py:21-22
- §3.1 — insert — ambiguity — `connectivity_mode` is a derived read-only field on every institution representation — implementation/services/serializers.py:11-14
- §3.1 — insert — ambiguity — institution-name collision → `ERR_DUPLICATE_ACTIVE` after field validity — implementation/routes/institutions.py:43-64
- §3.1 — insert+revise — mismatch — lazy health recompute also fires BROKEN side effects (connections→REAUTH_REQUIRED + INSTITUTION_BROKEN webhooks) and runs before the recovery precondition, so an aged-out recover yields `ERR_INVALID_STATE`; recompute refreshes `updated_at` but not `version` — implementation/services/core.py:186-210, routes/institutions.py:112-114
- §3.2 — insert — ambiguity — recipient-name collision → `ERR_DUPLICATE_ACTIVE` after field validity — implementation/routes/recipients.py:50-59
- §3.3 — insert — ambiguity — tier-name collision → `ERR_DUPLICATE_ACTIVE`; enrollment into inactive tier → `ERR_INVALID_REQUEST` — implementation/routes/tiers.py:48-50, 117-119
- §3.4 — insert — ambiguity — recipient with no ACTIVE tier assignment fails tier coverage with `ERR_SCOPE_EXCEEDS_TIER` — implementation/routes/consents.py:85-88
- §3.6 — revise — mismatch — unconditional agreement supersession means two ACTIVE agreements can never persist; removed the unreachable `ERR_DUPLICATE_ACTIVE` sentence; malformed `permitted_fields_by_scope` → `ERR_INVALID_REQUEST` — implementation/routes/institutions.py:176-188
- §3.6 — insert — ambiguity — complete_auth `simulate_failure`: handed to initial FULL refresh on the initial proof; ignored on migration re-proof; INSTITUTION_DOWN simulation executes a second failure driving connection to BROKEN; CREDENTIALS_INVALID initial failure moves fresh connection to REAUTH_REQUIRED — implementation/routes/connections.py:300-330
- §3.7 — insert — ambiguity — RefreshJob field set (`requested_at`, `executed_at`, `failure_reason`, `new_transaction_count`, `attempt_count`) and job object as refresh response — implementation/routes/connections.py:92-101, 488
- §3.7 — insert — ambiguity — no ACTIVE agreement ⇒ no rate ceiling, gate passes — implementation/routes/connections.py:451-452
- §3.7 — insert+revise — mismatch — failed refresh on REAUTH_REQUIRED connection preserves existing `reauth_not_before` (never re-armed by refresh); INSTITUTION_DOWN on a MIGRATING connection never moves the connection — implementation/routes/connections.py:138-153
- §3.8 — insert — ambiguity — per-connection migrate error split: already-on-target → `ERR_INVALID_STATE`; program not IN_PROGRESS or outside window → `ERR_MIGRATION_WINDOW_CLOSED` — implementation/routes/connections.py:402-410
- §3.9 — insert — ambiguity — no ACTIVE assignment ⇒ LOW rate-class fallback; `include_pending` parsed case-insensitively, only literal "true" enables — implementation/routes/connections.py:514-526
- §3.9 — insert — ambiguity — provisional variant reports projected units in the `units` field — implementation/routes/connections.py:545-559
- §3.10 — insert — ambiguity — webhook delivery is not idempotent; redelivery re-stamps and re-increments — implementation/routes/webhooks.py:23-24
- §3.11 — insert — ambiguity — single DATA_DELETED webhook attached to the consent's first connection or null `connection_id` if none — implementation/routes/deletion.py:62-73
- §3.11 — insert — ambiguity — ack state check precedes ack-integrity (valid recipient acking a COMPLETED request → `ERR_INVALID_STATE`); first valid ack always completes (single required recipient) — implementation/routes/deletion.py:108-121
- §2.5 — insert — ambiguity — "mutation" includes cascade-driven cross-entity changes (touch → version bump); health recompute excepted; RefreshJob version stays 1 — implementation/services/core.py:100-103, 188-193
- §2.2 — revise — mismatch — error envelope covers 4xx and 5xx (impl's 500 handler uses the envelope) — implementation/app.py:41-43
- §2.3 — insert — ambiguity — malformed/out-of-range limit/offset → `ERR_INVALID_REQUEST` — implementation/middleware.py:32-46

Deliberately not pinned (deemed impl-internal rather than PRD-visible): internal `_`-prefixed bookkeeping fields, id-tiebreaker ordering on identical timestamps, the in-memory store, and the impl's field-validation-before-rate/cadence practicality on malformed refresh inputs (consequence-free, since malformed inputs fail at priority 20 either way).
