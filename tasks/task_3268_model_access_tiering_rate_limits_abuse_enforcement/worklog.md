# Worklog — task_3268_model_access_tiering_rate_limits_abuse_enforcement

## Step 1: Create task directory — 2026-09-30T16:15:00.000Z

Task directory `./tasks/task_3268_model_access_tiering_rate_limits_abuse_enforcement/` was pre-allocated by the caller (workspace/ already present); verified it exists and is empty. No new index computed and no other task_* directory created, per instructions.

## Step 2: Generate scaffold — 2026-09-30T16:56:00.000Z

Initial scaffold subagent produced SCAFFOLD.yaml (1,935 lines, 60 endpoints), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1,203 lines, 18 §1.8 instances), SCAFFOLD_CORNER_DESIGN.yaml (908 lines, 31 §1.9 instances) — 13 entities, 9 state machines, 7 calculations, 19 validations, 20 errors, 5 roles, 2 OCC concurrency rules; lint clean. Orchestrator then directed the same subagent to trim endpoints to ≤40 (memory: >40 endpoints breaks impl-gen). Revision complete:

**New endpoint count: 39** (down from 60), lint-clean. Lint verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`

Endpoints removed/merged (21 net): removed sub-resource GETs redundant with collection GETs (`/organizations/{id}/enterprise-agreements`, `/model-versions/{id}/rate-limit-windows`, `/model-versions/{id}/queued-requests`, `/model-versions/{id}/invoice-lines`, `/safety-evaluations/{id}/model-versions`, `/safety-evaluations/{id}`); merged `GET /organizations/{id}/tier-preview` into `GET /organizations/{id}?preview=true`, `POST /invoices/{id}/lines` into `lines?` array on `POST /invoices`; dropped low-value writes with matching state-machine/enum/RBAC edits (`POST /payment-events/{id}/fail`, `POST /invoices/{id}/settle`+`/void`, `POST /enterprise-agreements/{id}/terminate`, `POST /appeals/{id}/deny`+`/withdraw`, `POST /abuse-cases/{id}/dismiss`+`/reopen`, `POST /queued-requests/{id}/admit` — queue admission now clock-driven via `POST /_clock/set_current_utc`, `PATCH /organizations/{id}` — OCC rule 1 dropped); swapped flat `GET /rate-limit-windows` + `GET /queued-requests` for org-scoped sub-resources; `model_version_id` on RateLimitWindow/QueuedRequest demoted from FK to plain scoping fields.

§1.8/§1.9 updates: rule 3 instance 1 → ModelVersion DRAFT↔GATED revision cycle; rule 7 instance 2 → countersign-requires-Organization-ACTIVE; rule 5 instance 2 → usage-record safety-vs-constraint priority; rule 9 instance 2 → clock-driven queue admission; preview calls via `?preview=true`; invoice lines via POST body; window/queue reads via org sub-resources.

**Final files on disk (orchestrator-verified):**
- `SCAFFOLD.yaml` — 1,654 lines; 13 entities, 9 state machines, 39 endpoints, 7 calculations, 19 validations, 20 errors, 5 roles, 1 concurrency rule
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1,238 lines; 18 instances (9 rules × 2)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 783 lines; 27 instances (22 with test recipes + 5 `excluded_because` stubs)

## Step 3: Copy shared files — 2026-09-30T16:58:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_3268_model_access_tiering_rate_limits_abuse_enforcement/workspace/INSTRUCTION.md` (1,424 bytes).

## Step 4: Generate PRD — 2026-09-30T17:10:00.000Z

All contracts pass. PRD.md is complete and verified on disk.

**Output**: `workspace/PRD.md` — 283 lines, ~42 KB.

**Section list**: §1 Introduction; §2 Global Specifications: 2.1 RBAC (5 roles, identity prose), 2.2 API Response Structure (verbatim fixed block), 2.3 Pagination (limit default 10/min 1/max 100, offset 0, `created_at` ascending), 2.4 Common Resource Properties (common_fields entities vs append-only entities), 2.5 The Logical Clock (default `2026-09-01T00:00:00Z`), 2.6 Tier Framework and Rate Ceilings (all five tiers' rpm/tpm), 2.7 Minute Windows, Burst Credits, and the Admission Test (BURST_MULTIPLIER 2, cumulative 3x/10-min variant), 2.8 Request Queueing (QUEUE_MAX_DEPTH 100, 120s TTL), 2.9 Monetary Precision and Rounding (pinned per-line then sum; batch discount rounded once), 2.10 Concurrency Discipline and Validation Order (OCC + full validation priority chain); §3 Business Logic: 3.1 Onboarding/Payments/Tier Progression, 3.2 Model Lifecycle and Safety Gate (0.70/0.90 inclusive thresholds, segregation), 3.3 Deprecation/Migration/Pinned (30-day window, three branches), 3.4 Usage Reporting and Rate-Limit Enforcement, 3.5 Invoicing and Credit (rounding order, 50% batch discount, min-debit credit), 3.6 Enterprise Agreements (countersign preconditions, expiry/termination cascades), 3.7 Abuse Detection and Graduated Enforcement (0.95 auto-throttle, full action-rank ladder with per-rank cascades), 3.8 Appeals and Reinstatement; §4 Endpoint Definitions — all endpoints, 4 columns; §5 Error Code Catalogue — all 20 errors, 2 columns.

**Zero-Silence Rule confirmation (scaffold §1.1–§1.7 coverage)**: §1.1 entities: all 13 entities and every field expressed in prose — mechanical check 67/67 field names present, 0 missing. §1.2 state machines: all 9 machines' transitions with `from → to` pairs, preconditions, error IDs, and every side effect; the single concurrency_rules entry rendered in §2.10 and §3.7 with `expected_abuse_case_version` + `ERR_STALE_VERSION` (HTTP 412). §1.3 calculations: all 7 in precise reconstruction-safe prose, no pseudocode. §1.4 validations: all 19 priority-ordered rules with error IDs; priority ordering stated in §2.10. §1.5 endpoints: all in §4 with method, path, description, roles; side effects narrated in §3. §1.6 errors: all 20 IDs in §5 and each mentioned in §2/§3 prose near its trigger. §1.7 roles: all 5 roles with exact spelling, identity semantics (entity-backed OrganizationAdmin vs opaque others), and exclusive-operation boundaries.

**Contract reports**: Field coverage 67/67 PASS; Rule coverage (19 validations, 1 OCC rule, 9 state machines, 7 calculations, endpoint side effects, 13 entities' structured fields, sibling branches symmetric) PASS; §3 path purity (298 backtick tokens, 0 path/method tokens) PASS.

**Orchestrator verification**: PRD.md on disk at 283 lines; endpoint table contains 39 rows matching the scaffold's 39 endpoints (subagent's "40" in its summary was a miscount; actual table count verified via grep).

## Step 5: Generate unit tests — 2026-09-30T17:40:00.000Z

Everything verifies. Generation complete.

**Files created** under `tasks/task_3268_model_access_tiering_rate_limits_abuse_enforcement/`:

`test_helpers/` (9 files, all compile, package imports cleanly):
- `types.py` — 14 status/role enums, 14 entity TypedDicts (append-only entities PaymentEvent/UsageRecord/RateLimitWindow/InvoiceLine/AbuseAction omit `updated_at`/`version`)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint
- `api_errors.py` — 20 `ApiErrorId` values + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py`, `factories.py`, `constants.py` (all PRD thresholds), `test_users.py` (shared constants + per-instance builders incl. `make_organization_admin_headers` for the entity-backed role), `fixtures.py` (composite helpers: activation, active model via safety gate, enterprise org, claimed cases/actions, restricted org + pending appeal, settled-spend accumulation, window filling, queue enqueue), `__init__.py` barrel export

`test_suite/` (6 files): `conftest.py` + 5 test files, **57 test functions**, each with a verbatim PRD citation and exactly one `Design:` tag.

**Coverage:**
- §1.8 difficulty: **18/18 instances translated, each with ≥2 tests** (36 difficulty-tagged tests).
- §1.9 corner: **18 of 23 instances translated** (19 corner-tagged tests, one instance has 2). **5 skipped** — all are `excluded_because:` stubs (`period_overlap_blocks_overlapping_invoice`, `err_rate_limited_triggered_at_cap`, `occ_stale_version_on_case_action`, `rate_threshold_cumulative_flag`, `cascading_side_effects_agreement_to_tier`); each stub's `difficulty_instance` pointer was verified to resolve to a real §1.8 instance (the OCC one resolves indirectly via the errors-section instance `err_stale_version_on_case_action`, which was translated). No non-stub instance was skipped.

**Verification performed on disk:** all files `py_compile` clean; 57 tests = 57 Design tags (1:1, no untagged/dual-tagged tests); every tag's instance name resolves via grep against the source yaml; every quoted PRD citation survives a normalized literal-substring match against `workspace/PRD.md`; zero `skip`/`skipif`/`xfail` markers.

## Step 6: Generate implementation — 2026-09-30T17:35:00.000Z

**Files created** under `workspace/implementation/`:

- `start.sh` (8 lines, executable) — guards `pip install` behind a flask-import check, `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000), foreground
- `requirements.txt` (1 line) — flask
- `app.py` (49) — Flask entry point, ApiError/404/405/500 handlers, blueprint registration
- `db.py` (66) — in-memory dicts (no seeding), logical clock defaulting to `2026-09-01T00:00:00Z`, ISO parse/format helpers
- `errors.py` (89) — all 20 error IDs from the catalog with exact HTTP statuses
- `response.py` (55) — envelope `{meta, response_type, data}`; pagination fields (`limit`, `offset`, `total_count`, `has_more`) in `meta`
- `middleware.py` (69) — `X-User-ID`/`X-User-Role` auth, role checks, limit/offset pagination (defaults 10/0, bounds 1–100)
- `services/domain.py` (360) — tier progression (settled + preview variants), rate-limit caps with THROTTLE 0.25-factor and burst pool (2×rpm), queue depth/TTL, invoice arithmetic (per-line round-half-up via Decimal, 50% batch discount rounded once at invoice level, credit debit capped at balance), migration-window availability check, clock-driven transitions (queue TTL, agreement expiry, model sunset, head-of-line queue admission at minute boundary), abuse cascades
- `services/util.py` (102) — id/timestamp stamping, typed body-field validators
- `routes/`: `clock.py` (23), `organizations.py` (199), `payments.py` (68), `models.py` (198), `usage.py` (103), `billing.py` (147), `agreements.py` (119), `abuse.py` (244)

**Endpoints implemented:** clock, 9 org routes (incl. activate + 6 reverse-reachability lists), 2 payment routes, 6 model-version routes (incl. deprecate, nested safety-evaluations + usage lists), open evaluation + submit verdict (with segregation-of-duties vs. opener, 0.70/0.90 thresholds), usage-records (admission + burst + model availability + org-status blocks), queued-requests (depth 100), invoices + lines + finalize (overlap check, rounding, credit debit), enterprise agreements (create/countersign/list/get, temporal window check, one-ACTIVE rule), abuse cases (auto-throttle at confidence ≥ 0.95), claim, OCC-guarded actions (`expected_abuse_case_version` → 412), graduated cascades (WARN/THROTTLE/RESTRICT/SUSPEND/TERMINATE with rank-vs-severity checks and TrustLead-only TERMINATE), appeals (filer-must-equal-org-id, one-PENDING rule, grant with SoD and status restore). (Subagent reported "40/40"; orchestrator grep counts 39 route decorators, matching the scaffold's 39 endpoints.)

**Smoke test:** booted via `bash start.sh` on PORT=19371 — org create 201 PROVISIONAL; payment create 201 PENDING; settle updated org aggregates (spend 5000, count 1, credit 5000); activate → ACTIVE; model register → DRAFT; missing headers → 401 ERR_UNAUTHENTICATED; wrong role → 403. Subagent killed only the PID it started. No seeding, no files, no SQLite — storage is dicts-only.

## Step 7: Run tests and iterate — 2026-09-30T18:15:00.000Z

Clean 8/8 sweep: 57/57 passed in every round. Loop exits.

**Summary**

- **Iterations run:** 5 full 8-round parallel sweeps (41/57 → 50/57 → 53-55/57 → 56/57 → 57/57 across all 8 rounds).
- **Tests deleted:** none. Every failing rule traced verbatim to PRD prose.
- **Fixes applied to `test_helpers/`** (`test_helpers/fixtures.py`):
  - `setup_restricted_org` and `setup_org_with_pending_appeal`: default severity `MEDIUM` → `HIGH`. Both fixtures issue a `RESTRICT` action, and PRD §3.7 requires "a case severity whose rank is at least that of `RESTRICT`"; `MEDIUM` (rank 2) cannot carry `RESTRICT` (rank 3), so every fixture consumer failed in setup.
- **Fixes applied to `test_suite/`** — all the same pattern: a case created with `severity="MEDIUM"` was used to issue `RESTRICT`, violating PRD §3.7's rank rule. Changed the case severity to `HIGH` (the minimum rank that admits `RESTRICT`), leaving the asserted behavior untouched:
  - `test_02_rate_limits_queueing.py`: `TestQueueInvariant._setup_queue_and_case`, `TestRestrictDropsQueuedRequests._setup_queued_org`, `TestValidationPriority.test_model_unavailable_beats_org_status_blocked`.
  - `test_01_tiering_payments_agreements.py`: `TestOrganizationBranching.test_restrict_then_suspend_across_two_cases` (first case MEDIUM → HIGH).
  - `test_05_enforcement_appeals.py`: `test_resolver_must_differ_from_action_issuer`, `TestAppealGrantCascade._setup_and_grant` (both MEDIUM → HIGH).
- **Fixes applied to `implementation/`**:
  - `services/domain.py` `ACTION_RANK`: `{WARN:1, THROTTLE:2, RESTRICT:3, SUSPEND:3, TERMINATE:4}` (was SUSPEND:4, TERMINATE:5). The contiguous mapping contradicted PRD §3.7's explicit permissions ("SUSPEND requires a case severity of HIGH or CRITICAL"; "TERMINATE … only on a CRITICAL case"), which uniquely determine SUSPEND rank = HIGH rank = 3 and TERMINATE rank = CRITICAL rank = 4.
  - `routes/abuse.py` `issue_action`: special-cased TERMINATE's rank check to require `severity == "CRITICAL"` (per PRD §3.7), and added `ERR_INVALID_STATE` gates requiring the organization to be in the cascade's source state (`ACTIVE` for RESTRICT/TERMINATE, `RESTRICTED` for SUSPEND) — PRD §3.7 defines each action only as that specific transition, and §2.10 makes inadmissible state transitions `ERR_INVALID_STATE` (previously the cascade silently no-op'd, so SUSPEND from ACTIVE returned 201).
  - `services/domain.py` `check_model_available`: no longer rejects `DRAFT`/`GATED` model versions for usage. PRD §3.3 names only two `ERR_MODEL_UNAVAILABLE` triggers (SUNSET; DEPRECATED for unpinned orgs without recent usage); the extra DRAFT/GATED rejection was scaffold-only and was breaking PRD-faithful rate-limit tests that post usage against freshly registered versions.
  - `services/domain.py` `admit`: burst-credit need is now `max(request_overage, token_overage)` instead of the sum. PRD §2.7: "One burst credit covers exactly one request slot **or** one token slot", so each credit covers one unit of either dimension and only the larger overage must be covered. This had wrongly rejected head-of-line queue admissions whose token budget exceeded the small throttled/derived tpm while the burst pool amply covered the request overage.
  - `services/domain.py` `run_clock_transitions` queue admission: admits only the head-of-line item per queue at each minute boundary (previously drained items while capacity remained). PRD §2.8: "a new window opens and **the head-of-line item** — the oldest by `enqueued_at` ascending — **is admitted**" (singular). Also changed the same-timestamp tie-break from random UUID to insertion order; ties are unreachable in practice (enqueue requires advancing the clock), so this resolves a flaky ambiguity without disturbing PRD-conformant orderings.

Key diagnosis note: the dominant failure cluster (12 of the original 16) was one shared root cause — fixtures/tests issuing `RESTRICT` on `MEDIUM` cases — which the triage hint correctly pointed at test_helpers. The remaining implementation bugs (rank table off-by-one, missing state gates, over-strict model availability, burst overage summation, queue drain vs head-of-line) were each confirmed against verbatim PRD sentences before fixing.

## Step 8: Finalize PRD — 2026-09-30T18:35:00.000Z

The diff is clean and minimal — 6 hunks, all in-place revisions, no new sections. Both files are 283 lines (0% line-count delta; all edits are inline within existing paragraphs/bullets).

Produced `workspace/PRD_FINALIZED.md` as a minimal patch of PRD.md.

**Line counts:** PRD.md 283 lines, PRD_FINALIZED.md 283 lines — 0% line-count delta (~1.4% of lines touched, 6 hunks).

### Changes (one bullet per edit)

- **§2.7 — revise** — appended a sentence pinning burst-credit need as the **larger** of the request-slot overage and the token-slot overage (never summed) — `implementation/services/domain.py:164-177` (`admit`: `need = max(...)`).
- **§2.8 — revise** — head-of-line admission now explicitly (a) applies the §2.7 admission test **including burst credits**, (b) admits **at most one item per queue per clock evaluation**, and (c) breaks equal-`enqueued_at` ties in favor of the item enqueued first — `implementation/services/domain.py:309-337` (`run_clock_transitions` admits only `items[0]` via `admit`, stable sort by `enqueued_at`).
- **§2.5 — revise** — replaced "the request queue is drained at each minute boundary crossed (see §3.6)" with "queue admission is evaluated for the minute window containing the new clock reading (see §2.8)" — `implementation/routes/clock.py:22`, `implementation/services/domain.py:264,313-337`. (Also fixes a stale cross-reference: §3.6 → §2.8; "drained" would have contradicted the new head-only rule.)
- **§3.3 — revise** — appended a sentence stating SUNSET and DEPRECATED-without-recent-usage are the **only two** `ERR_MODEL_UNAVAILABLE` triggers, and that usage against `DRAFT`/`GATED` versions is not availability-rejected — `implementation/services/domain.py:227-232` (`check_model_available` returns True for ACTIVE/DRAFT/GATED), sole callsite `implementation/routes/usage.py:47`.
- **§3.7 — revise** — replaced "strictly ranked … a LOW case admits only WARN, while only a CRITICAL case admits TERMINATE" with the full admissibility matrix: LOW→WARN; MEDIUM→WARN,THROTTLE; HIGH→WARN..SUSPEND (RESTRICT and SUSPEND share HIGH's rank); CRITICAL→all — `implementation/services/domain.py:40-41` (`ACTION_RANK` SUSPEND:3, TERMINATE:4), `implementation/routes/abuse.py:122-128` (TERMINATE special-cased to CRITICAL).
- **§3.7 — revise** — each of the RESTRICT / SUSPEND / TERMINATE bullets now states the required current organization status (ACTIVE / RESTRICTED / ACTIVE) and that any other status is an inadmissible transition rejected with `ERR_INVALID_STATE` (HTTP 409) — `implementation/routes/abuse.py:134-142`.

Step 7 items requiring **no** PRD edit: the `test_helpers/fixtures.py` severity changes and `test_suite/` severity changes (pure fixture/test bugs — PRD §3.7's rank rule already forced HIGH for RESTRICT); the `check_model_available` DRAFT/GATED removal is covered by the §3.3 edit above since §3.2's "serve general traffic" phrase could otherwise be misread.

### Per-edit pre-edit search log

1. **§2.7 burst max** — (a) subject: burst-credit need arithmetic in the admission test. (b) enumerated: `services/domain.py:150-178` (`admit`), callsites `routes/usage.py:51` (usage reporting) and `services/domain.py:332` (queue head-of-line admission); no other burst logic exists (`grep burst routes/` → only usage.py's call). (c) none — the sentence defines the shared admission test, which both callsites use.
2. **§2.8 queue admission** — (a) subject: head-of-line admission semantics. (b) enumerated: `services/domain.py:309-337` (single head admission per queue per call, stable sort → insertion-order tie-break, burst-inclusive via `admit`); `routes/clock.py:15-23` (single `run_clock_transitions()` per clock-set); queue-depth helper `domain.py:181-188` unaffected. (c) initially wrote "considered at each boundary" — revised to "at most one item per queue is admitted when the clock is set / at each such evaluation" because the impl evaluates once per clock-set call regardless of how many boundaries were crossed; "per boundary" would have mis-described a multi-minute jump.
3. **§2.5 clock sentence** — (a) subject: what setting the clock triggers for the queue. (b) enumerated: `routes/clock.py:22`, `domain.py:264-337`; cross-checked that §2.8 now fully governs admission so §2.5 can defer to it. (c) replaced "drained at each minute boundary crossed (see §3.6)" with wording that defers to §2.8 and fixes the stale §3.6 reference; kept the sentence otherwise verbatim.
4. **§3.3 availability triggers** — (a) subject: `ERR_MODEL_UNAVAILABLE` trigger set. (b) enumerated: `domain.py:227-257` (`check_model_available`), only callsite `routes/usage.py:47`; confirmed queue admission never consults model availability (`domain.py:320-337`); confirmed §3.2's "serve general traffic" is the only other prose that could be misread as blocking DRAFT/GATED, and scoped the new sentence to availability rejection to avoid redefining the safety gate. (c) added a parenthetical clarifying the safety gate governs release, not per-record admission.
5. **§3.7 rank matrix** — (a) subject: action↔severity rank admissibility. (b) enumerated: `domain.py:40-41` (rank tables), `routes/abuse.py:117-128` (only rank check; TERMINATE special-cased to CRITICAL; TrustLead bypasses assigned-analyst check but not rank), `errors.py:80` (message text only), and the auto-escalation path `routes/abuse.py:53-65` (system-issued THROTTLE, no rank check — sentence remains scoped to issued actions, so unaffected). (c) dropped "strictly" (implied 5 distinct ranks, contradicting SUSPEND=HIGH) and spelled out all four severity rows instead of endpoint-only examples.
6. **§3.7 state-source gates** — (a) subject: required current org status per action. (b) enumerated: `routes/abuse.py:137-142` (the three gates), cascades at `abuse.py:156-169`, appeal grant `abuse.py:252-255` (RESTRICTED/SUSPENDED→ACTIVE, which re-enables later RESTRICT/TERMINATE — consistent), auto-throttle `abuse.py:54-65` (leaves org ACTIVE — consistent), WARN/THROTTLE bullets (no org transition, no gate — untouched). (c) worded each gate as "must be X at issuance … rejected with `ERR_INVALID_STATE` (HTTP 409)" to mirror §2.10's state-machine-admissibility tier without implying a new validation phase.

No implementation changes were made; none are recommended.

**Orchestrator verification**: md5 snapshot of all 18 implementation files matches post-Step-7 state (Step 8 made zero implementation writes — the clean 8/8 sweep remains valid); PRD_FINALIZED.md exists, 283 lines, diff vs PRD.md is 16 changed lines (8 removed + 8 added), consistent with the reported 6 inline hunks.

## Step 9: Complete PRD — 2026-09-30T18:50:00.000Z

All 12 edits applied. Diff confirms only intended in-place paragraph changes; line count unchanged (283 → 283), char delta +1656.

**Source**: `PRD_FINALIZED.md` (283 lines, 43,734 chars) → `PRD_COMPLETED.md` (283 lines, 45,390 chars; +1,656 chars).

**Counts**: 9 ambiguity-pins, 3 mismatch-revisions (12 edits total).

- §2.3 Pagination — insert — ambiguity — pin `ERR_INVALID_REQUEST` for non-integer/out-of-range `limit`/`offset`, and `id`-ascending tie-break on equal `created_at` — implementation/middleware.py:43-56, services/util.py:87-88
- §2.4 Common Resource Properties — revise — mismatch — entity `created_at`/`updated_at` are whole-second-precision ISO 8601 UTC (from the logical clock), not three-fractional-digit; `version` starts at 1 — implementation/db.py:45-48, services/util.py:14-26
- §2.5 Logical Clock — revise — mismatch — agreement `effective_at >= expires_at` is `ERR_AGREEMENT_CONFLICT`, not `ERR_TEMPORAL_INVALID` (only the invoice period rule is `ERR_TEMPORAL_INVALID`) — implementation/routes/agreements.py:49-50, routes/billing.py:69-70
- §2.7 Admission — revise — mismatch — removed the trailing-ten-minute cumulative sustained-overload flagging sentence; no such mechanism exists anywhere in implementation/ — (no counterpart; previously PRD-only prose)
- §3.1 Onboarding — insert — ambiguity — pin rejection errors for `pinned_model_version_id`: nonexistent → `ERR_NOT_FOUND` 404; wrong status → `ERR_INVALID_REQUEST` 400 — implementation/routes/organizations.py:24-32
- §3.1 Tier preview — insert — ambiguity — pin accepted truthy spellings of the `preview` flag (`true`/`1`/`yes`, case-insensitive) — implementation/routes/organizations.py:81
- §3.1 Org list views — insert — ambiguity — pin `status` and `kind` filters on per-organization payment-events list — implementation/routes/organizations.py:111-116
- §3.2 Safety gate — insert — ambiguity — duplicate `OPEN` evaluation rejected with `ERR_INVALID_STATE` 409; opener recorded and exposed as `_opened_by` on the evaluation — implementation/routes/models.py:152-154, 161
- §3.3 Deprecation — insert — ambiguity — per-model safety-evaluations list supports a `status` filter — implementation/routes/models.py:118-120
- §3.4 Usage list views — insert — ambiguity — `batch` filter value parsing (`true`/`1`/`yes` case-insensitive) — implementation/routes/organizations.py:133, routes/models.py:137
- §3.6 Countersign — insert — ambiguity — countersign failures (not DRAFT, org not ACTIVE, outside effective window) → `ERR_INVALID_STATE` 409; one-ACTIVE-agreement rule re-checked at countersign → `ERR_AGREEMENT_CONFLICT` — implementation/routes/agreements.py:100-113
- §3.8 Appeals — insert — ambiguity — appealed action is the case's most recently created unrevoked action; org left unchanged when still `ACTIVE` (WARN/THROTTLE appeals); per-case appeals list has a `status` filter — implementation/routes/abuse.py:236-255, 191-193

No implementation changes were made. One observation for the orchestrator (no action taken): `routes/models.py:161` stores the segregation-of-duties reference as `_opened_by` and `simple_view` exposes it in API responses; PRD_COMPLETED now documents this as the adopted behavior rather than treating it as an impl bug.

**Orchestrator verification**: md5 snapshot of all 18 implementation files still matches post-Step-7 state (Step 9 made zero implementation writes — the clean 8/8 sweep remains valid and final); PRD_COMPLETED.md exists at 283 lines with 28 changed lines vs PRD_FINALIZED.md, consistent with the reported 12 inline edits.

## Pipeline complete — 2026-09-30T18:52:00.000Z

All 9 steps done. Final state: SCAFFOLD.yaml (1,654 lines, 13 entities / 9 state machines / 39 endpoints / 7 calculations / 19 validations / 20 errors / 5 roles / 1 OCC rule), SCAFFOLD_DIFFICULTY_DESIGN.yaml (18 instances), SCAFFOLD_CORNER_DESIGN.yaml (27 instances), test_helpers/ (9 files), test_suite/ (57 tests, all Design-tagged), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md}, implementation/ (18 files, 39 routes, in-memory only), and results.1–8.json all at 57/57 passing under `--isolation per-test-server` across 8 parallel stability-sweep rounds.
