## Step 1: Create task directory — 2026-09-05T23:35:40.305290878Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2972_streaming_encoding_content_delivery_operations and its workspace/ subdirectory. Index 2972 was pre-assigned by the orchestrating prompt; no index scan was performed.


## Step 2: Generate scaffold — 2026-09-06T01:33:50.662Z

All three artifacts are complete and lint-clean.

## Files delivered (task dir `/home/ubuntu/github/CodingPRD/tasks/task_2972_streaming_encoding_content_delivery_operations/`)

| File | Lines | Top-level key(s) |
|---|---|---|
| `SCAFFOLD.yaml` | 3031 | 13 keys, §1.0–§1.7 only — no `scaffold_difficulty_design`, no `scaffold_corner_design` |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1332 | single key `scaffold_difficulty_design` |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4960 | single key `scaffold_corner_design` |

All three parse under `yaml.safe_load`. `workspace/` and `worklog.md` untouched; scratch confined to `.scratch/step2/`.

## Scaffold content (§1.0–§1.7)
`api_prefix "/"`; entity_topology flat; state_machine_shape parallel; role_model peer_roles; consistency_model immediate; complexity_layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, selector_policy]`. **13 entities**, **10 state machines**, **13 calculations** (2 dual-variant), **20 validation priorities**, **53 endpoints**, **58 error codes**, **7 roles** (ContentOps, QcAnalyst, EncodingEngineer, DrmOperator, DeliveryEngineer, PlatformAdmin, VendorOperator — PlatformAdmin deliberately not a superset). Logical clock defaults to `2026-08-01T00:00:00Z`; `POST /_clock/set_current_utc` transitions nothing, `POST /availability-sweep` applies four pinned phases and returns nine counters.

## §1.8 — 9 difficulty rules / 19 instances
dual_variant_calc (2), combinatorial_formula (3), non_linear_state_machine (2), transitive_cascade (2), priority_pair_validation_conflict (2), boundary_precision_check (2), cross_entity_state_dependency (2), resource_temporal_overlap (2), compensating_invariant (2).

## §1.9 — all 9 guide sections, 127 instances (96 real + 31 `excluded_because` stubs)
entities 15, state_machines 23 (8 stubs), calculations 31 (9), validations 14 (2), endpoints 9, errors 21 (8), rbac 4, cross_cutting_complexity_layers 8 (4), consistency_model 2. `selector_policy` has no row in the claim-extraction guide, so it contributes no `claim_type` (noted in a comment; its behaviour is asserted via the `routing_*` / `entitlement_*` calculation instances).

Coverage audit notes:
- **Error catalog fully accounted for**: the `errors` section opens with a comment mapping the 18 codes triggered by instances in other §1.9 sections to their covering instance name, carries real instances for the remaining ~32 (path 404s per entity family, body-FK 404s, three uniqueness codes incl. a RETIRED device_class, own-state 409s, reprocess referential/in-flight/terminal codes, live-reservation referential + license containment, routing duplicate + empty pool, region-not-served, the PATCH arm of `ERR_VENDOR_CAPACITY_EXCEEDED`, `ERR_DRM_SYSTEM_UNSUPPORTED`, duplicate entitlement triple, the two entitlement 403 denials), and stubs the 8 codes owned by §1.8.
- Every asserted numeric literal was recomputed with Decimal/ROUND_HALF_UP (e.g. `quality_index 68.50` from ratios 0.0500/0.0100 at qnf 1.00; projected egress 10.80 → 32.40 on resteer; device_compat 24.00 snapshot).
- Both §1.2.1 OCC rules get a stale-version instance with `${var}`-derived `expected_title_version`; every deliberately-rejecting instance is named to match the lint's negative-name exemption.

## One correction applied to `SCAFFOLD.yaml`
The scenario block still carried the leading directive line `Generate task harder than expert level!`, which would have propagated into PRD.md via the scenario key. I removed that line (and its blank line) so `scenario:` now begins `2972. Streaming Encoding & Content Delivery Operations …`; the descriptive text itself is unchanged and verbatim. File went 3033 → 3031 lines.

## Lint verdict (verbatim)
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2972_streaming_encoding_content_delivery_operations/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2972_streaming_encoding_content_delivery_operations/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2972_streaming_encoding_content_delivery_operations/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    53
  §1.1 entities declared:     13
  §1.8 instances scanned:     19
  §1.9 instances scanned:     96
  Calls scanned (§1.8+§1.9):  943

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

No sibling task directory was read, listed, or grepped at any point.

Orchestrator verification: all three YAMLs present with the stated line counts; `grep -rn "harder than expert"` over the task dir returns nothing, so the Step 2 difficulty directive did not leak into any artifact. `workspace/` and `worklog.md` survived intact.

## Step 3: Copy shared files — 2026-09-06T01:33:56.656Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md to tasks/task_2972_streaming_encoding_content_delivery_operations/workspace/INSTRUCTION.md (bash-only step, no subagent).

## Step 4: Generate PRD — 2026-09-06T01:53:00.755Z

Step 4 complete.

**Output:** `workspace/PRD.md` — 485 lines, ~16.7k words, 119,620 bytes. Built incrementally (Write + heredoc appends), verified after every append; nothing else in the task dir was touched (`worklog.md`, `INSTRUCTION.md`, all three `SCAFFOLD*.yaml` intact; the two withheld design files were never opened, and no sibling task directory was read). Scratch dir `.scratch/step4/` was created and left empty.

**Section outline**
- `# Streaming Encoding & Delivery Operations API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Operator Identity and RBAC; 2.2 API Response Structure (byte-verbatim from the skill's fixed block); 2.3 Pagination and List Ordering; 2.4 Resource Identity, Timestamps and Versioning; 2.5 The Logical Broadcast Clock and the Four-Phase Availability Sweep; 2.6 Request Validation Order; 2.7 Optimistic Concurrency on the Title Aggregate; 2.8 Numeric Precision and Rounding Discipline; 2.9 Cascades, Compensations and Conserved Quantities; 2.10 Two Interval Geometries
- `## 3. Business Logic & Workflows` — 3.1 Opening the Catalog: Titles, Budgets and Source Masters; 3.2 Quality Control: Verdicts, Remediation and Terminal Rejection; 3.3 The Device Matrix and the Encoding Ladder; 3.4 Locking a Ladder: the Five-Hop Staleness Cascade; 3.5 Rights, Packaging and Playback Entitlement; 3.6 Licensing Windows, Publication, Takedown and Expiry; 3.7 CDN Delivery: Vendor Roster, Traffic Steering and Quality Feedback; 3.8 Live Events: Capacity Reservation, Arming, Failover and Release; 3.9 Catalog Reprocessing and the Encode Budget
- `## 4. Endpoint Definitions` — 53-row 4-column table (Method, Path, Description, Authorized Role(s))
- `## 5. Error Code Catalogue` — 58-row 2-column table

**Final section heading:** `## 5. Error Code Catalogue`. **Verbatim last line:** `| `ERR_ENCODE_BUDGET_EXCEEDED` | 422 |` — a complete table, so the file ends at a real section boundary.

**Coverage vs scaffold declarations (documented / declared)**
- Entities 13/13 (Title, MezzanineAsset, QualityControlReport, EncodingLadder, DeviceProfile, DrmPackage, EntitlementRule, CdnVendor, RoutingPolicy, PlaybackMetricWindow, LiveEventReservation, AvailabilityWindow, ReprocessJob), including the three `common_fields: false` entities carrying only `id` and `created_at`.
- State machines 10/10, transitions 60/60 (Title.availability_state 8, Title.packaging_state 5, MezzanineAsset 5, EncodingLadder 4, DrmPackage 6, CdnVendor 4, RoutingPolicy 9, LiveEventReservation 8, AvailabilityWindow 6, ReprocessJob 5).
- Calculations 13/13, each reconstructible step-for-step, including both dual-variant pairs (`readiness_score_provisional`/`readiness_score_certified`, `health_score_rolling`/`health_score_contract`), both pinned rounding orders (round-per-rung-then-sum with the 48.62-vs-48.60 worked contrast; surcharge tier keyed on the rounded base cost), both conserved ledgers, both interval geometries, and both selector policies.
- Validation rungs 20/20 with error IDs, statuses and `applies_to` scopes (including the cascading rung-11 arm where `ERR_REPROCESS_NO_SOURCE_ASSET` 422 beats `ERR_LADDER_NOT_LOCKED`).
- Endpoints 53/53; errors 58/58; roles 7/7; concurrency rules 2/2.

**Hard Contracts — all PASS (script-verified, code fences excluded from tick extraction)**
- Contract 1 (Field-Name Coverage): 121 distinct scaffold field/`input` identifiers, 0 missing in backticks; also verified `id`, `created_at`, `updated_at`, `version`, `page`, `page_size`, `total_count`, `has_more`, `X-User-ID`, `X-User-Role`, `current_utc`, the nine sweep counters and the seven `entitlement_decision` output fields.
- Contract 2 (Rule Coverage): all 58 error IDs appear in §1–§3 prose (not only in the §5 table); all 7 role names appear; all declared enum value sets are enumerated; all 60 transitions have prose with preconditions and side effects.
- Contract 3 (§3 Path Purity): 0 backticked tokens in §3 begin with `/`, are a bare HTTP method, or combine method+path; also 0 raw unticked slash-paths in §3.

**Zero-Silence decisions (scaffold ambiguities resolved, all recorded in the PRD prose)**
1. `PlatformAdmin` vs the QC-report list — the `roles` block excludes it, the endpoint table includes it; resolved in favour of the endpoint table (`ContentOps`, `QcAnalyst`, `PlatformAdmin`).
2. Pagination naming — §2.2 is fixed-verbatim and shows `limit`/`offset`; §2.3 states this API's actual `page`/`page_size` contract and the four `meta` fields, leaving §2.2 byte-identical.
3. Window cancellation and `closed_at` — the field description says "null until CLOSED" while the cancel endpoint's `side_effects` says "closed_at set"; resolved in favour of the operation-level side effect, so cancelling stamps `closed_at`.
4. Failover source states — `ERR_RESERVATION_STATE_INVALID`'s condition text says failover requires `ARMED`, but the state machine declares both `ARMED -> FAILED_OVER` and `LIVE -> FAILED_OVER`; resolved in favour of the state machine (legal from `ARMED` and `LIVE`, refused from `RESERVED`, `FAILED_OVER`, `ENDED`, `CANCELLED`).
5. The arm-time guard `now < window_end_at` has no dedicated error in the catalogue; mapped to `ERR_RESERVATION_STATE_INVALID` (409) as the own-entity precondition family.
6. `abort_reason` on the abort endpoint is a caller input but the transition pins `OPERATOR_ABORT`; documented as operator-supplied with only `OPERATOR_ABORT` accepted (`ENCODE_FAILURE` sweep-only, `BUDGET_RECLAIM` system-reserved), mirroring the `takedown_reason`/`MANUAL_LEGAL` pattern.
7. `stale_reason` declares `CODEC_STANDARD_CHANGE` but no transition writes it; documented explicitly as a reserved value no operation sets.
8. Operator re-steer reaching `UNROUTABLE` — the transition table attributes `ACTIVE -> UNROUTABLE` and `STANDBY_ONLY -> UNROUTABLE` to the system auto-resteer, while validation priority 17 states an operator re-steer that exhausts the pool is accepted and drives `UNROUTABLE`; documented as reachable by both paths.

Orchestrator truncation check: `tail -25` shows PRD.md ending on a complete `## 5. Error Code Catalogue` table row, and the heading index runs cleanly from §1 to §5 with all nine §3 subsections present. Not truncated; no regeneration needed.

## Step 6: Generate implementation — 2026-09-06T02:32:57.224Z

Step 6 complete. Final verification: fresh boot on port 18974 gave 82/82 smoke assertions passing (`FAILURES: 0`), all modules compile, the URL map holds exactly 53 routes, and the store is empty at import.

## Step 6 — Implementation generation (Python + Flask)

**Location:** `workspace/implementation/`

### Module layout (3118 lines total, all `py_compile` clean)

| File | Lines | PRD coverage |
|---|---|---|
| `start.sh` | 10 | launcher: `set -euo pipefail`, `cd "$(dirname "$0")"`, pip install only if `import flask` fails, `exec python3 app.py`; reads `$PORT` (default 8000), binds `0.0.0.0`, runs in foreground |
| `requirements.txt` | 1 | `flask>=2.0` |
| `app.py` | 54 | app factory, 8 blueprints, `ApiError`/`HTTPException`/catch-all handlers, `threaded=False`, `use_reloader=False` |
| `errors.py` | 91 | §5 — all **58** error ids -> HTTP status, grouped by ladder rung; `ApiError` |
| `db.py` | 168 | §2.5 logical clock (`CLOCK_DEFAULT = 2026-08-01T00:00:00Z`), §2.9 audit fields, in-memory `Store` (13 dicts + `_seq`), Decimal helpers (`q2`/`q4`, ROUND_HALF_UP), `sort_rows` with insertion-order tie-break |
| `response.py` | 117 | §2.2 envelope (`meta`/`response_type`/`data`), `api_request_id` = `req_` + 20 uppercase alnum, ISO-8601 with exactly 3 fractional digits, §4 pagination (rejects out-of-range, never clamps) |
| `middleware.py` | 91 | §2.6 rungs 1–5: identity headers, role validity, role authorisation, and `VendorOperator` entity-backed self-scoping (4 scope kinds) |
| `validation.py` | 218 | §2.6 rung 6 engine: unknown/missing field rejection, all scalar kinds, arrays, scale/bounds, instants, unknown query-param rejection |
| `services/calc.py` | 503 | all pure calculations (see below) |
| `services/domain.py` | 330 | the five cascades, derived ledgers, `derive_packaging`, `refresh_vendor_health`, `resteer_policy`, `complete_job`/`fail_job`, `run_sweep()` |
| `routes/common.py` | 110 | enum tuples, region patterns, 11 lookup helpers, filtering, list emission |
| `routes/system.py` | 27 | §2.5 clock set, §3.10 availability sweep |
| `routes/titles.py` | 218 | §3.1 titles, §3.6 licensing windows, takedown |
| `routes/assets.py` | 151 | §3.2 source masters + QC reports |
| `routes/ladders.py` | 183 | §3.3 device profiles, §3.4 encoding ladders (validate/lock) |
| `routes/drm.py` | 292 | §3.5 DRM packages, entitlement rules, playback entitlement checks |
| `routes/delivery.py` | 233 | §3.7 CDN vendors, routing policies, playback metrics |
| `routes/live.py` | 180 | §3.8 live reservations (create/arm/failover/cancel) |
| `routes/jobs.py` | 141 | §3.9 reprocess jobs (create/run/abort) |

### Coverage counts
- **53 endpoints** — exact match to the PRD endpoint table (verified against `app.url_map`).
- **58 error ids** — every catalogue entry reachable, mapped to its declared status.
- **20-rung validation ladder** — evaluated in strict order, first violated rung wins; rungs 1–5 in `middleware.py`, rung 6 in `validation.py`, rungs 7–20 in the route bodies in PRD-declared precedence.
- **8 state machines** — title `availability_state`, derived `packaging_state`, source-master `qc_state`, ladder, DRM package, reservation, routing policy, job; plus vendor `state`.
- **Calculations:** readiness (provisional/certified, weights 0.50/0.20/0.30, gate 80.00), rung geometry/compat scan, reprocess cost (codec factors 1.00/1.35/2.10, rate 0.02, billable minutes = ceil(max non-rejected duration/60), per-rung rounded then summed), priority rank (trigger weights, cap 20.0), CDN selection (PERFORMANCE/COST/WEIGHTED composite), egress projection, playback quality index, vendor health (rolling newest-3 unweighted / contract play_attempts-weighted), entitlement rule matching + ranking, interval geometries (half-open licensing vs closed buffer-inflated capacity), two conserved ledgers (`reserved_gbps`, `encode_budget_remaining_usd`).
- **5 cascades:** ladder-lock (5 hops), metric ingest (health -> vendor state -> auto-resteer -> egress), job completion (depth 4), packaging-stale propagation, sweep-driven title transitions.
- **Sweep** returns exactly the nine declared integer counters and is idempotent for a fixed clock.
- **OCC** via `expected_title_version` on exactly two creates (ladder, job) -> `ERR_STALE_TITLE_VERSION` 412.

### Constraint compliance
- Storage is in-memory dicts only; the only file I/O in the tree is `json.dumps` for response bodies (grep-verified: no sqlite, no file writes, no /tmp).
- Nothing is seeded at import — `{k: len(v) for ...}` over the store at boot is `{}`; the logical clock's declared default is the sole constant.
- No test artefacts were read; scratch confined to `.scratch/step6/`; `worklog.md` untouched.

### Smoke test
Three runs on unusual ports, each server killed by PID/port only (never a broad pkill).
- Run 1 (port 18972): 5 failures, all proven to be wrong literals in my own script, not implementation defects — correct values are `quality_index` 74.80, both vendor health variants 74.80, `per_rung_cost_usd` `[3.14, 6.41, 13.23, 26.32]`, `cost_estimate_usd` 49.10, `encode_budget_remaining_usd` 4950.90. Script literals patched.
- Run 2 (port 18972): contaminated — a stale listener from run 1 survived because a compound restart command aborted on a relative redirect path before its `kill` took effect. Resolved by `lsof -ti tcp:18972` -> verifying `/proc/<pid>/cwd` was my own implementation dir -> `kill <pid>`. (A second `python3 app.py` on this host with cwd at the task root belongs to a concurrent step and was left alone.)
- Run 3 (port 18974, fresh boot, clock at default, store empty): **82 assertions, 0 failures.** Covers envelope/meta shape and logical-clock timestamps, title CRUD + duplicate-key 409, rungs 1–3 RBAC denials, master + QC attempt flow, device matrix, ladder OCC/validate/lock, licensing windows (in-past, overlap, legal block), DRM (widevine floor, HDCP floor, region-not-licensed, packaging gates), entitlement ALLOW + concurrency denial, vendor create/scopes, policy create -> resteer -> STANDBY_ONLY -> UNROUTABLE, metric ingest rewriting health, reservation create/arm/failover with bandwidth conservation, job create/run/abort with budget conservation, clock set + sweep (publish + idempotence), pagination meta, out-of-range page_size rejection, unknown query rejection, manual takedown.

### PRD ambiguities resolved (chosen reading)
1. Package **revoke** is available from PENDING/PACKAGED/STALE (PRD text), not PACKAGED only (scaffold).
2. **Failover** is permitted from ARMED **or** LIVE.
3. Undeclared-but-implied list filters admitted: `external_ref` on `GET /titles`; `region_code`/`subscription_tier`/`device_class_scope` on entitlement-rule list; both lineage links on `GET /encoding-ladders`.
4. `ERR_VENDOR_CAPACITY_EXCEEDED` also fires on `PATCH /cdn-vendors/{id}` when committed capacity is lowered below `reserved_gbps`; `ERR_ENCODE_BUDGET_EXCEEDED` also on `PATCH /titles/{id}`.
5. **Arm** precedence: state == RESERVED, then clock strictly before `window_end_at` (both `ERR_RESERVATION_STATE_INVALID`), then a PACKAGED package -> `ERR_PACKAGE_NOT_READY`, then the routable-policy guard, also mapped to `ERR_PACKAGE_NOT_READY` because the PRD names no error for it.
6. **Packaging** precedence: ladder LOCKED (`ERR_LADDER_NOT_LOCKED`, including a repackage naming a wrong-title ladder or omitting `ladder_id`), then master quality (`ERR_NO_PASSED_ASSET`, then `ERR_ASSET_REMEDIATION_PENDING`), then `entitlement_rule_count >= 1` -> `ERR_PACKAGE_NOT_READY` on the PENDING arm only, per the literal text.
7. **Job run** precedence: another job RUNNING -> `ERR_JOB_STATE_INVALID`; source ladder not LOCKED -> `ERR_LADDER_NOT_LOCKED`; then budget -> `ERR_ENCODE_BUDGET_EXCEEDED`.
8. Failover's three failure conditions (null failover vendor, DRAINED target, insufficient capacity) all answer `ERR_VENDOR_CAPACITY_EXCEEDED`.
9. Manual takedown has no declared error for a non-PUBLISHED title, so it is applied unconditionally.
10. `Title.version` bumps only on §2.7's eight enumerated operations — including every window schedule, per §2.7's unconditional phrasing, even though §3.6 mentions only the first window. Derived recomputations rewrite figures without bumping; sweep-driven title transitions refresh `updated_at` only.
11. Reservation containment is `window.start <= r.start and r.end <= window.end` (a single window must cover the whole reservation).
12. `studio_code`/`vendor_code` accept `[A-Z0-9]`.
13. `api_request_timestamp` is drawn from the logical clock, never the host wall clock.
14. `last_qc_report_id` is included on source-master representations.
15. QC reports are ordered `attempt_number` ASC (§2.3/§3.2 override §4's generic "newest first").
16. A phase-3 packaging-stale takedown counts in `titles_taken_down` and consumes that title's single phase-4 transition.
17. Unknown query parameters are rejected under rung 6.
18. Entitlement-check `subscription_tier` accepts the four-value set including `ANY`; `requested_streams` has minimum 1 and no maximum, so an over-ask yields a 403 decision rather than a 400.
19. Ladder validation writes the computed score and compatible-device count on the rejecting arm too.
20. Both readiness variants are recomputed together on every packaging/revoke path (§3.1).
21. Vendors are created with `health_score_rolling` and `health_score_contract` at 100.00 — the value the health calculation itself yields with zero measurement rows (not a seeded entity).

## Step 5: Generate unit tests — 2026-09-06T02:33:37.097Z

(Note: Steps 5 and 6 ran concurrently in a single assistant message, as the skill requires. Step 6 completed first and so was appended above; this entry is Step 5. The worklog is append-only, so the two entries appear out of numeric order.)

## Step 5 — Test suite generation for task_2972 (Streaming Encoding & Content Delivery Operations): COMPLETE

### Files written (all at the TASK ROOT, none under `workspace/`)

`test_helpers/` — 9 files, **2373 lines**: `__init__.py` 23, `api_client.py` 338, `api_errors.py` 167, `assertions.py` 436, `constants.py` 207, `factories.py` 382, `fixtures.py` 429, `test_users.py` 153, `types.py` 238.

`test_suite/` — 12 files, **12819 lines**: `conftest.py` 17, `test_01_variant_and_formula_depth.py` 722, `test_02_nonlinear_states_and_cascades.py` 724, `test_03_precedence_boundaries_and_guards.py` 794, `test_04_intervals_and_conserved_quantities.py` 786, `test_05_entities_and_identity.py` 1223, `test_06_state_machine_breadth.py` 1562, `test_07_calculation_breadth.py` 1938, `test_08_validation_order.py` 1114, `test_09_endpoints_and_consistency.py` 1186, `test_10_error_catalogue.py` 1631, `test_11_rbac_and_concurrency.py` 1122.

### Totals

**289 test functions emitted; 289 `Design:` tags** (per-file tag count equals per-file test count in all 11 files). Per file: 15 / 19 / 18 / 15 / 32 / 37 / 42 / 29 / 26 / 32 / 24.

**Collected: 298 tests, zero import or collection errors** (`python3 -m pytest test_suite --collect-only -q` from the task root, 0.17s). 298 > 289 because a few table-driven tests are parametrised, so one function expands to several cases.

### Coverage — every non-stub instance translated, zero skipped

- **Queue A (difficulty): 19 of 19 instances**, all 9 rule_ids. Minimum 3 tests per instance (requirement was 2); 79 tests total in `test_01`–`test_04`.
- **Queue B (corner): 96 of 96 non-stub instances**, all 9 sections — entities 15, state_machines 15, calculations 22, validations 12, endpoints 9, errors 13, rbac 4, cross_cutting_complexity_layers 4, consistency_model 2. Minimum 1 test per instance (6 instances have exactly 1, 58 have 2, 29 have 3, 2 have 4, 1 has 5); 210 tests total in `test_05`–`test_11`.
- **31 `excluded_because:` stub instances: nothing emitted**, and no tag anywhere names one.
- **SKIPPED under the PRD-first two-condition filter: NONE.** No instance failed both conditions outright; the one instance whose asserted outcome was not uniquely derivable was translated via a PRD-grounded substitute chain rather than dropped (see deviation D6 below).

### Audit verdict — clean (exit 0)

`.scratch/step5/audit_design_tags.py` re-parses both YAMLs (difficulty 19 instances/0 stubs; corner 127/31 — both figures match the indices) and AST-walks all 289 tests:

- untagged tests: **0**
- dual-tagged tests: **0**
- tags naming an instance absent from either YAML: **0**
- tags pointing at an `excluded_because:` stub: **0**
- difficulty instances under 2 tests: **0**; corner non-stub instances at 0 tests: **0**

`pytest.mark.skip` / `pytest.mark.xfail` grep over `test_suite/` and `test_helpers/`: **0 hits**.

Path check: `test_helpers/` and `test_suite/` both exist at the task root; `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation` — **no stray copy of either directory**.

### Cross-file consistency sweep — no issues, nothing fixed

`py_compile` clean over all 21 files. pyflakes over the whole suite reports **zero undefined names**, so the eleven isolated generators produced no symbol drift; every `api.*`, `fx.*`, `f.*`, `err.*` and assertion symbol they call exists in `test_helpers/`. Every module-level helper a test file defines is underscore-prefixed and private (e.g. `_build_readiness_reference_title`, `_qc_reports`), so nothing shadows a `test_helpers` symbol. `test_helpers/` was not modified by any generator. Residual cosmetic findings only, left alone: 4 unused imports (`test_05`: `get_success_data`, `assert_identity_fields`; `test_helpers/assertions.py`: `typing.Optional`, `validate_success`). No hard breakage was found, so no file was edited.

### Deviations, substitutions and PRD ambiguities (durable record for Step 7)

Confirmed literal substitutions:

- **D1** `content_type: "SERIES"` in difficulty `availability_window_half_open_adjacency` is not in the PRD enum (`MOVIE`/`EPISODE`/`LIVE_EVENT`) -> substituted `MOVIE` (the instance is about interval geometry). Verified: the string `SERIES` appears nowhere in the suite.
- **D2** corner `cancelling_last_active_window_takes_published_title_down` asserts `closed_at == null`; §3.6 says cancellation records `closed_at` at the clock's current instant -> asserted `assert_instant_equals(closed_at, INITIAL_CLOCK)`.
- **D3** rbac instance 1 asserted `Title.version` unchanged against a token captured before a setup ladder-create that §3.3 says bumps `version` -> version re-captured immediately before the trigger, then asserted unchanged.
- **D4** rbac instance 3's hard-coded principal id -> the suite's `VENDOR_OPERATOR_UNKNOWN` (built on `UUID_ABSENT`).
- **D5** `cascade_skips_a_revoked_package_when_the_ladder_is_superseded` asserted `locked_ladder_count == 2` after a lock, but §3.4 recomputes the count on `SUPERSEDED` -> asserted **1**; and its setup packaged two DRM packages with no entitlement rules, which §3.5 forbids -> routed through `fx.create_packaged_package`.
- **D6** `window_bounds_past_start_and_legal_takedown_are_rejected` takes down a **DRAFT** title expecting 200, but §3.6 defines manual takedown only as `PUBLISHED -> TAKEN_DOWN`, defines no error for a non-`PUBLISHED` source, and §5 has no `ERR_TITLE_STATE_INVALID` — the 200 is not uniquely derivable. Substituted the PRD-grounded chain `build_published_title` -> MANUAL_LEGAL takedown -> fresh non-overlapping GB window => `ERR_TITLE_LEGALLY_BLOCKED` 409, preserving the instance's point. Same DRAFT-takedown defect was hit by the cross_cutting instance and split into a `build_published_title`-based test.

PRD ambiguities flagged (Step 7 should adjudicate the PRD sentence, **not** weaken these assertions):

- **§3.4 ladder-lock double statement.** §3.4 enumerates exactly two cross-entity guards (`ERR_NO_PASSED_ASSET`, `ERR_ASSET_REMEDIATION_PENDING`) but its "Stated positively" sentence implies *every* master must be `QC_PASSED`. An `INGESTED` second master maps to neither error. `readiness_ignores_a_revoked_package_in_both_variants` was translated as written (lock succeeds). If that fixture fails with `ERR_NO_PASSED_ASSET`, it is this contradiction — keep the 100.00/45.00 -> 70.00/45.00 assertions.
- **qc-reports ordering conflict.** §4's Description says "newest first"; §2.3 and §3.2 both pin `attempt_number` ascending. Per the brief's precedence rule the rule-bearing sentence governs, so the whole suite (including `test_09`'s ordering test and `test_07`'s `_qc_reports` evidence reader) assumes **`attempt_number` ascending**.
- **Sweep counter for a cascade-closed window.** In `reprocess_completion_supersedes_source_and_stales_the_package` the §3.4 hop-5 cascade closes an `ACTIVE` window during Phase 3, and the PRD does not determine whether that increments the Phase-1 counter `windows_closed`. That one test asserts the four relevant counters field-by-field instead of via `assert_sweep_counters` (which would force `windows_closed == 0`); every other sweep assertion in the suite uses `assert_sweep_counters`, so unnamed counters are checked to be zero.
- **No clock GET exists** (§4 has only `POST /_clock/set_current_utc`), so the `ERR_WINDOW_IN_PAST` boundary is pinned behaviourally: a July interval refused, the same interval starting exactly at `2026-08-01T00:00:00Z` accepted 201 `SCHEDULED`.
- **§2.2 error envelope has no `details` field**, so error tests assert `error_id` + non-empty `message` via `assert_envelope(resp, "error")`.
- **§3.5 does not state `packaging_state` after revoking a PENDING package**; `UNPACKAGED` is derived from the §3.4 precedence sentence (quoted in that test).
- **No `GET /cdn-vendors` list endpoint** in §4, so "exactly one vendor" is proved by re-reading the vendor (`vendor_code`, `regions`, `committed_gbps`, `cost_per_gb_usd`, `version == 1`) rather than by listing.
- **Runner signature note:** `validate_error(response, expected_error_id, expected_status=None)` — status is passed positionally throughout; `status=409` would raise `TypeError`.
- **Infrastructure note:** the runner's own `validate_paginated` asserts `meta.limit`/`meta.offset` and is unusable against this PRD's `page`/`page_size` contract, so `test_helpers/assertions.py` provides PRD-correct `validate_paginated` (asserting `meta.page`, `page_size`, `total_count`, `has_more`) plus `validate_unpaginated`; all list tests use those.

Process note for the record: the coordinator's "all 11 have reported" was premature for `test_07` and `test_10` — both were still appending during my first audit pass (30->42 and 19->32 tests), which is why the first audit showed 12 apparently-uncovered corner instances. Both were told to finish cleanly and re-verify; the final figures above are from a re-run over the stable suite. Scratch artifacts left in place at `.scratch/step5/` (`GENERATOR_BRIEF.md`, `audit_design_tags.py`); nothing outside `.scratch/step5/` was touched, `worklog.md` was never opened, and `workspace/implementation/` was never read or written.

## Step 7: Run tests and iterate — 2026-09-06T03:04:41.080Z

Clean sweep. Iteration 2: all 8 rounds 298/298, 0 failed / 0 errors / 0 skipped, ~545 s per round.

---

## Summary — Step 7, task_2972_streaming_encoding_content_delivery_operations

### Iterations
**2 iterations.**

- **Iteration 1** (pre-fix): 293/298 in all 8 rounds. Union of failures = 5 tests, identical in every round (fully deterministic, no flakiness signal, no load-induced failures).
- **Iteration 2** (final): **298/298 in all 8 rounds** — round 1: 298/298, round 2: 298/298, round 3: 298/298, round 4: 298/298, round 5: 298/298, round 6: 298/298, round 7: 298/298, round 8: 298/298. Cross-checked against each `results.$i.json`: `total=298, passed=298, failed=0, errors=0, skipped=0`.

### Tests deleted
**None.** Every one of the 5 failures passed STEP 1a (PRD verbatim-covers) and STEP 1b (uniquely derivable); all 5 were test-artifact bugs resolved under STEP 2. No test was weakened, skipped, xfailed, or downgraded from an `error_id` assertion to an HTTP-status assertion.

### Fixes to `test_helpers/`
- **`test_helpers/assertions.py`** — `assert_instant_equals`. Signature drift: the helper was declared `assert_instant_equals(actual, expected)` while 4 call sites (in 3 tests) passed a third field-name label, so those tests died with `TypeError: assert_instant_equals() takes 2 positional arguments but 3 were given` — a symbol bug with no response body in the traceback, per the triage hint. Added the optional `name: str = "instant"` parameter and threaded it into both failure messages. Semantics unchanged (still millisecond-resolution comparison per §2.8); 23 two-argument call sites are unaffected. Fixed all three of:
  - `test_05_entities_and_identity.py::test_title_identity_fields_are_server_minted_at_version_one`
  - `test_05_entities_and_identity.py::test_renaming_a_title_bumps_the_version_and_preserves_created_at`
  - `test_05_entities_and_identity.py::test_qc_report_is_a_write_once_attempt_record`

### Fixes to `test_suite/`
Both in **`test_suite/test_10_error_catalogue.py`**, same root cause: each test hardcoded an absolute `CdnVendor.version` baseline that ignored the §2.9 cascade fired by the live reservation their own fixture books. PRD §2.9 states verbatim: *"The rule is that **every consequence is applied inside the originating request**, transitively, and each affected row's `updated_at` is refreshed and its `version` incremented, exactly as if it had been mutated directly."* §3.8 states the booking *"immediately recomputes the primary vendor's `reserved_gbps`"*, so the vendor row is an affected row and its version legitimately reaches 2 before the PATCH. The implementation was right; the expected literals were pre-cascade.
- `test_lowering_committed_capacity_below_the_held_hold_returns_vendor_capacity_exceeded` — dropped the `before["version"] == 1` literal and re-expressed the post-refusal check as `after["version"] == before["version"]`, which is the actual PRD rule under test ("nothing changes" on an `ERR_VENDOR_CAPACITY_EXCEEDED` refusal) rather than a fixture-dependent count.
- `test_lowering_committed_capacity_to_exactly_the_held_hold_is_accepted` — captured the pre-PATCH vendor and replaced `patched["version"] == 2` with `patched["version"] == before["version"] + 1`, which is §3.7's "each successful update increments the vendor's `version`" stated exactly. Added the §2.9 citation to the docstring and corrected its summary line.

### Fixes to `implementation/`
**None.** No implementation defect was found. All 54 endpoints, the 20-rung ladder, both conserved ledgers, both interval geometries, the four-phase sweep and the 59-entry error catalogue passed as authored.

### PRD ambiguities adjudicated
1. **Cascaded `version` bumps on non-title rows (§2.9 vs §3.7)** — *drove the two `test_suite/` fixes.* §3.7 pins vendor version increments to commercial-term updates; §2.9 says every cascaded row's version increments "exactly as if it had been mutated directly". Adjudicated in favour of §2.9's general rule: §3.7's sentence describes the direct-edit path, it does not exhaustively enumerate vendor version bumps. A reservation booking therefore takes the vendor from version 1 to 2.
2. **`Title.version` on sweep- and cancel-driven transitions (§2.9 vs §2.7)** — the reverse tension, resolved the other way, because §2.7 *is* explicitly exhaustive: *"What makes a captured token go stale is any mutation that bumps `Title.version`: editing title metadata or budget, scheduling a licensing window, taking a title down manually, creating a ladder, locking a ladder, creating a reprocessing job, running one, and aborting a running one."* Window cancellation and sweep publication/takedown/expiry are absent from that list, so the implementation's use of `stamp_only(title)` (refresh `updated_at`, no version bump) in `routes/titles.py::cancel_window` and `services/domain.py::run_sweep` Phase 4 is correct. No code change; **Step 8 should reconcile §2.9's blanket claim with §2.7's closed list**, since the two sections read as contradictory on their face.
3. **QC report list ordering (§2.3/§3.2 vs the §4 endpoint table)** — §2.3 and §3.2 both order a master's QC reports by `attempt_number` ascending; the §4 table row says "newest first". Two sections outvote one, and ascending attempt order is what an append-only attempt log means. `routes/assets.py::list_qc_reports` sorts ascending. No code change; the §4 table wording is the defect.
4. **Where the Phase-3 job-completion takedown lands (§2.5 vs §2.9/§3.9)** — §2.5 says a job completing in Phase 3 "causes the very same sweep to take the title down in **Phase 4** rather than publish it", but Phase 4's `PUBLISHED`->`TAKEN_DOWN` rule requires `packaging_state` to still be `PACKAGED`, which it no longer is once the depth-4 cascade has set it to `STALE`. Adjudicated in favour of §2.9 ("every consequence is applied inside the originating request, transitively") and §2.5's "at most one `availability_state` transition per title per sweep": `services/domain.py::complete_job` applies the §3.4 hop-5 takedown with reason `PACKAGING_STALE` inline, counts it in `titles_taken_down`, and adds the title to a `settled` set so Phase 4 does not fire a second transition. Net observable behaviour matches §2.5's prose (same sweep, taken down not published, one transition, counted once). No code change.
5. **Manual takedown of a non-`PUBLISHED` title (§3.6)** — §3.6 describes taking a `PUBLISHED` title down but §5 defines no title-state error identifier, so there is nothing to return for a `DRAFT`/`SCHEDULED` title. `routes/titles.py::takedown_title` accordingly does not gate on the current `availability_state`. No code change; **Step 8 may want to state this explicitly**, as it is the one state machine in the PRD with no stated guard.

### Operational notes
Both sweeps ran under the mandated `setsid nohup .../.scratch/step7/sweep.sh` launcher and were only ever judged complete on the `SWEEP_DONE` sentinel; no sweep was relaunched, and no diagnosis was taken from the spliced `workspace/sweep.log`. Failure detail was extracted from `results.$i.json` with a summarizer keyed on `"status"`. Three one-off reproductions used a private hand-started server on port 18972, killed by verified pid/port only (never a broad `pkill`); the port is free. `worklog.md` was neither read nor written, and nothing under `.scratch/` was deleted.

---

**Orchestrator independent verification of the final sweep** (not the subagent's own claim): a summarizer keyed on `tests[].status` over all eight `results.$i.json` reports `total=298 passed=298 failed=0 errors=0` for every round, with `{'passed': 298}` as the only status bucket and a cross-round union of non-passed tests of size **0**.

## Step 8: Finalize PRD — 2026-09-06T03:15:42.598Z

PRD_FINALIZED.md is complete.

## Summary

**Line counts:** PRD.md 485 lines / 119,620 bytes -> PRD_FINALIZED.md 485 lines / 124,089 bytes. Line delta 0% (every edit is inline inside an existing paragraph or table row); byte delta +3.7%. File ends at the complete §5 error-code table.

### Changes (one bullet per edit)

- **§2.5 (sweep ordering paragraph)** — revise — the Phase-3 job-completion takedown is now stated to land *inside* Phase 3 as hop 5 of §3.4 with `takedown_reason` `PACKAGING_STALE`, to be counted in `titles_taken_down`, to spend the title's one permitted `availability_state` transition so Phase 4 offers it nothing further, to stamp no `last_sweep_at`, and to close windows that are *not* counted in `windows_closed` — `services/domain.py:68-76,193-208,239,282-284,291-292,326-329`.
- **§2.7 (last paragraph)** — insert — the eight-operation list is declared exhaustive, and the operations that do *not* bump `Title.version` are enumerated (master register/resubmit, QC verdict, ladder validation, DRM create/package/revoke, rule attach, window cancellation, aborting a `QUEUED` job, and every sweep/cascade title transition) — `routes/titles.py:112,129,165,217`, `routes/ladders.py:104,150,172`, `routes/jobs.py:70,119,137-140`, `routes/assets.py:61,103,139`, `routes/drm.py:105-106,164-165,179-180,221`, `services/domain.py:75,328`.
- **§2.9 (cascade rule)** — revise — kept the blanket "every affected row's `updated_at` refreshed and `version` incremented" for non-title rows (with vendor-ledger and cascade-closed-window examples), then carved out the `Title` aggregate: cascades/derivations/sweep phases never bump `Title.version`, they refresh `Title.updated_at` only when they transition its `availability_state`, and leave it untouched for pure re-derivations — `db.py:139-151`, `services/domain.py:20-95,326-329`, `routes/titles.py:216-217`.
- **§2.9 (state-dimension paragraph)** — revise — `EXPIRED` qualified as terminal against the sweep and cascades, pointing at §3.6's unguarded manual takedown — `routes/titles.py:116-130`, `services/domain.py:290-330`.
- **§3.6 (EXPIRED bullet)** — revise — "there is no route out" -> no sweep phase or cascade routes a title out; only the unguarded manual takedown can — `services/domain.py:303-325` (no `EXPIRED` branch), `routes/titles.py:118-123`.
- **§3.6 (manual takedown paragraph)** — revise — stated explicitly that this is the one state machine with no state guard (§5 defines no title-state error), accepted from any `availability_state` including `DRAFT`, `SCHEDULED`, `TAKEN_DOWN` and `EXPIRED`; "moves from `PUBLISHED` to `TAKEN_DOWN`" -> "sets `availability_state` to `TAKEN_DOWN`" — `routes/titles.py:116-130`.
- **§3.7 (vendor commercial terms)** — insert — a vendor's `version` also moves when a cascade rewrites its `reserved_gbps` ledger or its two health figures — `services/domain.py:121-123,145-161`, `routes/delivery.py:101,206`.
- **§3.8 (successful booking)** — insert — the immediate `reserved_gbps` recompute is a §2.9 vendor-row mutation (refresh `updated_at`, increment `version`), as on every failover/cancel/sweep-end refresh — `routes/live.py:82,161-163,179`, `services/domain.py:121-123`.
- **§3.9 (sweep-completion bullet)** — revise — spelled out the in-Phase-3 takedown for a `PUBLISHED` title (state, reason, window closures, `titles_taken_down`, Phase 4 skip) and that a non-`PUBLISHED` title is instead evaluated by Phase 4 as usual — `services/domain.py:193-208,282-292`.
- **§4 endpoint table, `GET /mezzanine-assets/{id}/qc-reports`** — revise — "newest first" -> `attempt_number` ascending, per §2.3/§3.2 — `routes/assets.py:143-151`.
- **§4 endpoint table, `POST /titles/{id}/takedown`** — revise — "of a published title" -> "of a title, whatever its current `availability_state`" — `routes/titles.py:116-130`.

### Per-edit pre-edit search log

1. **§2.5 Phase-3 takedown.** (a) Subject: where a Phase-3 completion's title takedown is applied, its reason, its counters. (b) Read `services/domain.py` in full (`complete_job`, `derive_packaging`, `packaging_stale_cascade`, `close_active_windows`, `run_sweep` all four phases), plus `routes/ladders.py::lock_ladder` (the other hop-5 caller) and `routes/drm.py` (grepped `derive_packaging` callsites: create/package/revoke never produce a new `STALE`, so they never fire hop 5); grepped `last_sweep_at` repo-wide (only `domain.py:327` and title creation). (c) Widened "take the title down" to "take a **`PUBLISHED`** title down" because `packaging_stale_cascade` returns early for non-`PUBLISHED` titles; added the `last_sweep_at` and `windows_closed` clauses only after confirming both counters/stamps are Phase-1/Phase-4 exclusive.
2. **§2.7 exhaustive list.** (a) Subject: every site that can move `Title.version`. (b) Grepped `touch(`/`stamp_only` repo-wide and read every hit: `routes/titles.py:112,129,165,217`, `routes/ladders.py:104,172`, `routes/jobs.py:70,119,140`, plus every `recompute_readiness`/`derive_packaging`/`recompute_locked_count`/`recompute_budget` callsite (`routes/drm.py:105,164,179`, `routes/assets.py:61,103,139`, `routes/ladders.py:150`, `services/domain.py:113,201,206-207,218`) to confirm none of them touches the title. (c) Phrased the negative list as "leave a captured `expected_title_version` valid" rather than "change nothing on the title", because several of those paths do rewrite derived figures and some transition `availability_state`; explicitly split `QUEUED` vs `RUNNING` abort after seeing `routes/jobs.py:137-140` bumps only in the running case.
3. **§2.9 Title exception.** (a) Subject: which rows get `version`+`updated_at` on cascade and which get less. (b) Read `db.py::touch/stamp_only/new_row`; enumerated every cascade helper (`close_active_windows`, `supersede_ladder`, `refresh_vendor_reserved`, `resteer_policy`, `refresh_vendor_health`, `complete_job`, `fail_job`, sweep Phases 1/2) and confirmed all non-title rows use `touch`; confirmed `routes/delivery.py::create_policy` mutates only a brand-new row. (c) Scoped the exception to "the `version` half of the rule" and added the precise `updated_at` sentence (refreshed on an `availability_state` transition, untouched on pure re-derivation) after checking all three `stamp_only(title)` sites are availability transitions and that `recompute_readiness`-only paths never stamp; softened the vendor example to "a **freshly registered** vendor ... reads `version` 2" so it is not a false universal for previously-edited vendors.
4. **§2.9 `EXPIRED` terminal.** (a) Subject: routes out of `EXPIRED`. (b) `run_sweep` Phase 4 branch table (`SCHEDULED`/`PUBLISHED`/`TAKEN_DOWN` only — no `EXPIRED` branch), `packaging_stale_cascade` (early return unless `PUBLISHED`), `routes/titles.py::cancel_window` (only `PUBLISHED`), `routes/titles.py::takedown_title` (no state check at all). (c) Kept the word "terminal" and qualified it rather than deleting it, so the sweep/cascade claim stays exactly as strong as the code makes it.
5. **§3.6 `EXPIRED` bullet.** Same subject and same enumerated paths as edit 4. (c) Replaced only the four words "there is no route out"; left the entry conditions untouched.
6. **§3.6 manual takedown.** (a) Subject: the guard set on `POST /titles/{id}/takedown`. (b) `routes/titles.py:116-130` (no `availability_state` check, unconditional window closure loop, unconditional `touch`), `routes/common.py::get_title` (404 only), `middleware.py`/`errors.py` and §5 (no title-state error identifier exists), `routes/titles.py::schedule_window:138-139` (the sticky `MANUAL_LEGAL` consequence), §2.6 rung 10's endpoint list (titles absent — already consistent). (c) Rewrote the effect sentence as "sets `availability_state` to `TAKEN_DOWN`" instead of "moves from `PUBLISHED` to"; enumerated the source states rather than claiming a bare universal, and paired it with edits 4/5 so no section still asserts a guard the code lacks.
7. **§3.7 vendor `version`.** (a) Subject: everything that increments `CdnVendor.version`. (b) `routes/delivery.py::update_vendor:101` and `::ingest_metric:206`, `services/domain.py::refresh_vendor_reserved:121-123` and `::refresh_vendor_health:145-161`, all `refresh_vendor_reserved` callsites (`routes/live.py:82,162,163,179`, `services/domain.py:273`), `create_vendor` (new row, `version` 1). (c) Said "a cascade that rewrites ... its `reserved_gbps` ledger or its two health figures" rather than naming one endpoint, since health refresh fires on *every* metric ingest even when the scores do not change; softened the example to a freshly registered vendor.
8. **§3.8 booking ledger refresh.** (a) Subject: the vendor-row side effect of a booking and of every other ledger refresh. (b) Same `refresh_vendor_reserved` callsite set as edit 7, plus `run_sweep` Phase 2's `ENDED` arm (`domain.py:271-273`). (c) Added "as it is on every later ledger refresh driven by a failover, a cancellation or a sweep-driven end" so the sentence does not read as unique to creation.
9. **§4 QC-report ordering.** (a) Subject: the ordering of a master's QC report list. (b) `routes/assets.py::list_qc_reports:143-151` (sort on `attempt_number` ascending), `db.py::sort_rows` (insertion-order tie-break), and the two prose statements in §2.3 and §3.2 that already say ascending. (c) None — the table row was the sole defect; pointed it at §2.3/§3.2 instead of restating the rule.
10. **§4 takedown row.** (a) Subject: same as edit 6. (b) Re-read `routes/titles.py:116-130`; grepped the PRD for other descriptions of the takedown endpoint (§2.1 "issues legal takedowns" — role-scoped only, no state claim, left verbatim). (c) None.

### Step 7 items deliberately NOT patched

- **"Fixes to test_helpers/" (`assertions.py::assert_instant_equals` signature drift).** No PRD edit — flagged in the diff as a pure test-artifact symbol bug; millisecond-resolution instant comparison is already pinned by §2.8 and the implementation's `db.py::iso` emits exactly three fractional digits.
- **"Fixes to implementation/" — none.** Nothing to align.
- I made no edit to §3.4's hop-1/hop-5 prose, to §2.3's ordering paragraph, or to the two `test_10` vendor-version assertions' subject beyond §2.9/§3.7/§3.8, since those sections already describe the implementation verbatim.

---

**Orchestrator verification:** `cmp` confirms PRD_FINALIZED.md differs from PRD.md (485 lines both, 119,620 -> 124,089 bytes) and the file ends on the complete §5 error-code table, not mid-sentence.

## Step 9: PRD completeness scan — PRD_COMPLETED.md — 2026-09-06T04:02:44.234Z

**Orchestrator note on partitioning.** Step 9 was deliberately run as **four sequential subagent passes over one shared `workspace/PRD_COMPLETED.md`**, not as a single scan. A single-agent Step 9 on a PRD this size has twice produced a `PRD_COMPLETED.md` byte-identical to its input — i.e. the scan silently never ran. The partition was: pass 1 owns §1, all of §2, the §4 endpoint table and the §5 error table; pass 2 owns §3.1–§3.4 and §3.6; pass 3 owns §3.5, §3.7, §3.8, §3.9; pass 4 is reconciliation only. **Pass 1 alone performed the `cp` from `PRD_FINALIZED.md`**; passes 2–4 were explicitly forbidden from `cp`-ing or rewriting the file and used targeted `Edit` calls only, so no pass could clobber an earlier pass's work. Each pass was handed the previous passes' hand-off notes and their "judged already correct — do not re-litigate" lists verbatim, which is what kept passes 3 and 4 from churning ground already settled. Pass 4 exists because partitioned passes reliably *report* cross-partition contradictions rather than fixing them: it closed three, and re-verified all 22 cross-partition `rung N` citations that passes 2 and 3 had made against pass 1's §2.6 ladder.

**Orchestrator-applied edit (1).** Pass 4 reported one pre-existing internal inconsistency it declined to touch under its minimal-edit mandate: §2.6 rung 14 opened "Five referential rules, all 422:" and then enumerated six distinct error identifiers (`ERR_LADDER_TITLE_MISMATCH`, `ERR_VENDOR_REGION_NOT_SERVED`, `ERR_NOT_LIVE_EVENT_TITLE`, `ERR_FAILOVER_SAME_AS_PRIMARY`, `ERR_REPROCESS_CODEC_UNCHANGED`, `ERR_RULE_REGION_NOT_LICENSED`). Behaviorally inert, but Step 9's mandate is zero residual PRD-internal contradiction, so I changed the one word: "Five" → "Six". No other orchestrator edit was made to any PRD.

**Final independent verification (orchestrator, not delegated).**
- `PRD.md` 485 lines / 119,620 bytes → `PRD_FINALIZED.md` 485 / 124,089 → `PRD_COMPLETED.md` **487 lines / 154,849 bytes**.
- `cmp PRD_FINALIZED.md PRD_COMPLETED.md` → *differ: byte 7224, line 29*. **Not byte-identical**, so the scan demonstrably ran.
- Heading index complete and in order: 24 headings — `## 1`, `## 2` (+ §2.1–§2.10), `## 3` (+ §3.1–§3.9), `## 4`, `## 5`.
- Ends on the complete §5 table, final row `| ERR_ENCODE_BUDGET_EXCEEDED | 422 |` — no mid-sentence truncation.
- §4 table 53 data rows; §5 table 58 data rows (header + separator excluded).
- Leak grep for `harder than expert|SCAFFOLD|scaffold_difficulty|scaffold_corner|test_suite|test_helpers|worklog|Design: Difficulty|Design: Corner` → **zero hits**. The difficulty directive never reached the PRD, and no test-artifact reference leaked into it.

**Aggregate across the four passes:** 13 + ~30 + 20 + 4 = **~67 edits**; +5,626 / +13,321 / +10,027 / +1,787 / +1 bytes = **+30,760 bytes over `PRD_FINALIZED.md`**, in +2 lines (nearly every edit was an in-paragraph revision, which is why the heading line numbers never moved and each pass could verify its predecessors positionally).

The four passes' returned summaries follow verbatim.

---

Done. Summary below.

## Step 9 — PASS 1 (§1, §2.1–§2.10, §4 table, §5 table) — COMPLETE

**`cp` confirmed:** `cp workspace/PRD_FINALIZED.md workspace/PRD_COMPLETED.md` was the first action; I alone created the file.
- `PRD_FINALIZED.md`: 485 lines, 124,089 bytes
- `PRD_COMPLETED.md`: 485 lines, 129,715 bytes (**char-delta +5,626**; 13 lines revised in place, no lines added/removed)
- `cmp` differs at line 29; `tail -20` confirms it still ends on the complete `§5` table through `ERR_ENCODE_BUDGET_EXCEEDED | 422`.
- Scratch: used `.scratch/step9_pass1/`, removed only that subdir; `step2/4/5/6/7` siblings intact.

**Counts: 10 ambiguity-pins, 4 mismatch-revisions (13 edits total).**

### Changes
- **§2.1** — revise — ambiguity — `X-User-ID` is compared byte-for-byte for the `VendorOperator` lookup, no trimming/padding/case-folding after the blank test — `middleware.py:23-27,48-52`
- **§2.3** — insert — ambiguity — a `page` past the last page answers 200 with empty `data`, full `total_count`, `has_more` false (not an error) — `response.py:103-111`
- **§2.3** — insert — ambiguity — when `created_at` ties (routine under the logical clock), rows are returned in **insertion order**, and that insertion tie-break stays *ascending* inside the two descending orderings — `db.py:154-164`
- **§2.4** — insert — ambiguity — `api_request_id` = `req_` + exactly 20 chars from `A–Z0–9` (24 total); emitted instants truncate to 3 fractional digits rather than round — `response.py:14-18`, `db.py:62-68`
- **§2.4** — revise — **mismatch** — list-endpoint query identifiers are plain exact-match filters, **never** 404s (PRD claimed "body or query string" foreign keys both 404); FK resolution is body-only, in declared order — `routes/common.py:104-109` vs `routes/live.py:48-52`
- **§2.4** — revise — **mismatch** — the entitlement check's `ERR_DEVICE_PROFILE_NOT_FOUND` is reported only *after* a `PACKAGED` package is selected, so `ERR_NO_PACKAGED_DRM` wins — `routes/drm.py:249-261`
- **§2.5** — insert — ambiguity — `api_request_timestamp` is read from the **logical clock**, not wall time; `current_utc` is the clock endpoint's only accepted body field; its `data` is a single-field object, not a resource — `response.py:21-25`, `routes/system.py:14-20`
- **§2.5** — insert — ambiguity — the sweep takes no body input; any supplied field fails rung 6 — `routes/system.py:23-27`
- **§2.6 rung 6** — insert — ambiguity — unknown **query** parameters are refused like unknown body fields, and single-resource reads accept *no* query parameter at all, `page`/`page_size` included — `validation.py:186-194`, all 11 `parse_query([], allow_paging=False)` sites
- **§2.6 rung 6** — insert — ambiguity — a fourth key inside a rung object fails here; absent/empty body reads as `{}`; non-object or non-JSON body fails; exact accepted instant grammar (`.1`–`.9` digits, zone marker `Z`/`z`/`+00:00`/`-00:00` **or none**, whitespace trimmed, `+02:00` and date-only rejected) — `validation.py:36-46,154-156`, `db.py:19-21,71-87`
- **§2.6 rung 11** — revise — **mismatch** — added `ERR_NO_PACKAGED_DRM` as a seventh rung-11 arm (entitlement check) with its precedence over the device-profile 404 — `errors.py:41`, `routes/drm.py:251`
- **§2.6 closing** — insert — ambiguity — the three entitlement decision denials (`ERR_ENTITLEMENT_NO_RULE`, `ERR_CONCURRENCY_LIMIT_EXCEEDED`, `ERR_OFFLINE_PLAYBACK_DENIED`, all 403) sit outside the 20 rungs, after all of them — `errors.py:44-47`, `routes/drm.py:272-279`
- **§2.8** — revise — **mismatch** + pin — quantised figures serialise as JSON **numbers** (so `1000.00` emits as `1000.0`; scale is a rounding contract, not a rendering one); instant comparison is at the parsed precision (microsecond), replacing the false "millisecond resolution" claim — `response.py:28-33`, `db.py:71-87`
- **§4 preamble** — insert — ambiguity — clock/sweep `data` is not a resource; trailing slash accepted; off-table requests answer in the §2.2 envelope: unroutable path → `ERR_TITLE_NOT_FOUND` 404, wrong method → `ERR_INVALID_REQUEST` **400**, transport refusal → `ERR_INVALID_REQUEST` 400 — `app.py:20,28-38`
- **§4 table** — revise — **mismatch** — `GET /encoding-ladders` also accepts `superseded_by_ladder_id` (impl has 5 filters; the cell listed 4, contradicting §3.3) — `routes/ladders.py:120-126`

### HAND-OFF NOTES (§3 issues found, not edited)

**Pass 2 owns (§3.1–§3.4, §3.6):**
- `POST /titles/{id}/takedown` takes a **required** body enum `takedown_reason` whose only accepted value is `MANUAL_LEGAL` — omitting it is a rung-6 failure, not a default (`routes/titles.py:120`). Verify §3.6 pins "required", not "defaulted".
- `ERR_TITLE_LEGALLY_BLOCKED` on window scheduling fires only when `availability_state == TAKEN_DOWN` **and** `takedown_reason == MANUAL_LEGAL` (`routes/titles.py:139`).
- Phase 4 gates (`services/domain.py:291-329`), easy to get wrong: `PUBLISHED → TAKEN_DOWN` requires `not has_active` **and** `packaging_state == "PACKAGED"` (the `packaged` conjunct is on the takedown arm too); `SCHEDULED → EXPIRED`/`TAKEN_DOWN → EXPIRED` require ≥1 window, *all* windows in `CLOSED`/`CANCELLED`, and `now >= max(window_end_at)`; `TAKEN_DOWN → PUBLISHED` only when `takedown_reason != MANUAL_LEGAL`; titles in `DRAFT` or `EXPIRED` get **no** Phase 4 transition.
- `PATCH /titles/{id}` recomputes `encode_budget_remaining_usd` and calls `touch(title)` unconditionally — `version` bumps even for a body that changes nothing (`routes/titles.py:100-113`).
- `derive_packaging` precedence: any `STALE` package → `STALE`; else any `PACKAGED` → `PACKAGED`; else `locked_ladder_count >= 1` → `PACKAGING`; else `UNPACKAGED`. `PENDING` and `REVOKED` never satisfy the first two branches (`services/domain.py:79-95`).
- §3.4 hop 5 (`packaging_stale_cascade`, `services/domain.py:68-76`): fires only from `PUBLISHED`; uses `stamp_only` (refreshes `updated_at`, no `version` bump); closes only `ACTIVE` windows, leaving `SCHEDULED` ones alone.
- `supersede_ladder` (`services/domain.py:103-113`): only packages in exactly `PACKAGED` go `STALE` with `stale_reason = "LADDER_SUPERSEDED"`; `PENDING` packages are untouched.

**Pass 3 owns (§3.5, §3.7, §3.8, §3.9):**
- §3.5 entitlement check (`routes/drm.py:243-292`): input is a `device_class` **enum**, not a `device_profile_id`; `requested_streams` has minimum 1 and no maximum; `offline_requested` defaults false. Stage order: oldest `PACKAGED` package by `created_at` → `ACTIVE` profile for the class → `rule_matches` → `rank_rules` → concurrency gate → offline gate. Success `data` keys are exactly `decision` ("ALLOW"), `reason_code` ("MATCHED"), `matched_rule_id`, `package_id`, `max_concurrent_streams`, `offline_granted`, `effective_height_px`, where `effective_height_px = min(rule.max_playback_height_px, profile.max_height_px, ladder.peak_height_px)` and the ladder term is dropped if the bound ladder no longer exists; `offline_granted` requires all three of `offline_requested`, `rule.offline_playback_allowed`, `package.persistent_license_allowed`.
- §3.9 Phase 3 discriminator (`services/domain.py:277-288`): a `RUNNING` job **completes iff** its source ladder still exists **and** is still `LOCKED`; otherwise it **fails** with `abort_reason = "ENCODE_FAILURE"`. §2.5 Phase 3 only says "either completes or fails" — §3.9 must pin this.
- §3.9 `complete_job` (`services/domain.py:193-208`): the result ladder copies the source's `rungs` verbatim, `derived_from_ladder_id` = source id, `state` `LOCKED`, `validation_reason_code` `"OK"`, and it is **never scored** (`device_compat_score` 0.00, `compatible_device_count` 0). Completion does *not* call `recompute_budget`, so a `COMPLETED` job keeps its `committed_usd`.
- §3.7 `refresh_vendor_health` (`services/domain.py:145-166`): drain arm first; `DRAINED` never recovers; `touch(vendor)` is unconditional so every metric ingest bumps the vendor's `version`; dependent re-steer runs only when the state actually **changed** and the new state is `DEGRADED` or `DRAINED`, and only for policies whose `primary_vendor_id` is that vendor.
- §3.7 `resteer_policy` (`services/domain.py:126-142`): the outgoing primary is appended to `excluded_vendor_ids`, `resteer_count` increments even when selection lands nowhere, and `projected_egress_cost_usd` is recomputed each time.
- §3.8 `_capacity_ok` uses `q2(held + reserved_gbps) <= committed_gbps` (equality accepted), and create-time check order is NOT_LIVE_EVENT → FAILOVER_SAME_AS_PRIMARY → BOUNDS → IN_PAST → OUTSIDE_LICENSE → CAPACITY (`routes/live.py:31-68`).

### Judged already correct — do not re-litigate
- **§5 error table**: verified programmatically byte-equivalent to `errors.py::ERROR_STATUS` — same 58 ids, same statuses, same order. Zero edits needed.
- **§4 method/path/role matrix**: verified programmatically against all 53 registered Flask rules and their `@endpoint(...)` role lists — every method, path and role set matches. Only the ladders filter cell was wrong.
- **§2.3's ordering overrides** all match the actual `sort_rows` calls (windows `window_start_at`↑/`created_at`↑; QC reports `attempt_number`↑; metrics `window_start_at`↓/`created_at`↓; reservations `window_start_at`↑/`created_at`↑; rules `priority`↓/`created_at`↑; jobs `priority_rank`↓/`created_at`↑).
- **§2.4's three immutable resources** match exactly the three `new_row(versioned=False)` sites (QC report, entitlement rule, metric window).
- **§2.10** both geometries match `calc.windows_conflict` / `calc.capacity_held_against` verbatim, including per-side buffer inflation, closed comparison, self-exclusion on failover, and `buffer_minutes` default 15 / range 0–60.
- **§2.9** title-`updated_at` rule (stamped on `availability_state` transitions, untouched on mere re-derivation) matches the `stamp_only` vs no-stamp split in `packaging_stale_cascade` and Phase 4; both conserved-quantity ledgers match `calc.reserved_ledger` and `domain.recompute_budget`.
- **§2.6 rung 6** does not repeat the rung numeric ranges (240–2160 `height_px`, 200–40000 `bitrate_kbps`) because **§3.3 already states them** and `validation.check_rungs` enforces exactly those.
- **§2.2 known divergence, intentionally NOT edited** (fixed verbatim contract block): the block's `meta` example names `limit`/`offset`, but `response.py:107-111` emits `page`/`page_size`/`total_count`/`has_more`. §2.3 already pins the four real fields, so the contract is unambiguous overall.

---

Pass 2 complete. Only `workspace/PRD_COMPLETED.md` was modified.

## File state
- **487 lines, 143,036 bytes** (was 485 lines / 129,715 bytes → **+13,321 bytes, +2 lines**; the 2 new lines are one paragraph split in §3.3 plus its blank separator).
- **Pass 1's §2 edits survived intact.** §2 still occupies lines 11–171 with §2.1–§2.10 headers at their original line numbers; `api_request_id` appears 5×, and the distinctive pass-1 phrases (`req_` + twenty `A`–`Z`/`0`–`9` characters, out-of-range `page` answering 200 with an empty array, insertion-order tie-break, JSON-number-with-no-trailing-zeros, "leaves `updated_at` untouched when it merely re-derives") are all present verbatim.
- File still ends on the complete §5 error table (last row `| ERR_ENCODE_BUDGET_EXCEEDED | 422 |`). §4 table untouched.

## Counts
**24 changes: 16 ambiguity-pins, 8 mismatch-revisions.**

## Changes
- §3.1 — revise — mismatch — `studio_code` is 2–10 chars of `A`–`Z` **and digits `0`–`9`**, not "uppercase characters" — `routes/titles.py:28`
- §3.1 — revise — mismatch — title list also filters by **`external_ref`** (exact, case-sensitive equality) — `routes/titles.py:88`, `routes/common.py:104-110`
- §3.1 — revise — mismatch — `PATCH /titles/{id}`: all three fields optional; `encode_budget_remaining_usd` recomputed and `version`/`updated_at` bumped **unconditionally**, including an empty or no-op body — `routes/titles.py:98-113`
- §3.1 — insert — ambiguity — `frame_rate` is compared numerically, so `24`, `24.0`, `24.00` are all the accepted 24.0 — `validation.py:115`
- §3.1 — insert — ambiguity — a new master also stores `last_qc_report_id` of null, never cleared afterwards; registration is not gated on either title state dimension — `routes/assets.py:45,59`
- §3.1 — revise — ambiguity — inclusion sets are exhaustive: `REJECTED`/`SUPERSEDED` ladders and `REVOKED`/**`STALE`** packages count for neither readiness variant — `services/calc.py:74-90`
- §3.2 — insert — ambiguity — the attempt-count ceiling shares `ERR_ASSET_STATE_INVALID` with the state guard; the report's stored field list is exactly 9 fields incl. `blocking_defect_code` — `routes/assets.py:77-91`
- §3.2 — insert — ambiguity — third-attempt rejection still copies `severity_index` and the non-`NONE` `blocking_defect_code` onto the master; `last_qc_report_id` repointed on all three branches; readiness recomputation always rewrites **both** variants — `routes/assets.py:93-103`
- §3.2 — revise — ambiguity — resubmit: either precondition fails with `ERR_ASSET_STATE_INVALID`; explicit `[]` for `caption_languages` replaces rather than being read as omission; the other three measurements are rung-6 unknown fields — `routes/assets.py:32-38,124-133`
- §3.2 — revise — ambiguity — report list also exposes `blocking_defect_code`; loudness/caption penalties are stored nowhere and returned by nothing; the list takes no filter — `services/calc.py:139-148`, `routes/assets.py:146`
- §3.3 — insert — ambiguity — inverted bitrate window is a **rung-6 `ERR_INVALID_REQUEST`**, evaluated before the `device_class` uniqueness check — `routes/ladders.py:50-54`
- §3.3 — revise — ambiguity — profile `state` is **fixed at registration**; no update/retire operation exists — `routes/ladders.py` (no PATCH), `routes/ladders.py:34`
- §3.3 — insert — ambiguity — rung `label` is any non-empty string, no upper bound, compared case-sensitively; authoring deliberately does **not** check bitrate monotonicity — `validation.py:160-162`, `routes/ladders.py:93-100`
- §3.3 — insert — ambiguity — geometry sub-test order (bitrate strict-increase → duplicate height → height strict-increase), with the third also reporting `BITRATE_NOT_MONOTONIC`; `DUPLICATE_HEIGHT` is defined but **unreachable** because authoring pre-filters heights — `services/calc.py:204-214`, `routes/ladders.py:96`
- §3.3 — revise — mismatch — on `NO_COMPATIBLE_DEVICE`, `compatible_device_count` is **not** forced to 0: it can be ≥1 when every compatible profile carries `market_share_pct` 0.00 and `peak_height_px` < 2160 — `services/calc.py:191-201`, `routes/ladders.py:139-148`
- §3.3 — insert — mismatch — **both** validation arms bump the ladder's `version`/`updated_at` and recompute both readiness variants; neither touches the title's `version`/`updated_at` or re-derives `packaging_state` — `routes/ladders.py:149-150`
- §3.4 — revise — **mismatch (tension 1)** — the "every master must be `QC_PASSED`" claim is deleted; the guard is an existence test plus an absence test, with `ERR_NO_PASSED_ASSET` evaluated first — `routes/ladders.py:162-166`
- §3.4 — insert — ambiguity — hop 1 also bumps the ladder's own `version`; the one `Title.version` increment is the whole call's effect — `routes/ladders.py:169-172`, `services/domain.py:75`
- §3.4 — revise — ambiguity — hop 3 touches packages in **exactly** `PACKAGED`; `PENDING`/`STALE`/`REVOKED` packages bound to the superseded ladder are untouched — `services/domain.py:108-112`
- §3.4 — revise — mismatch — hop 4 recomputes **both** readiness variants, and provisional drops too since `STALE` satisfies neither package set — `routes/ladders.py:182`, `services/calc.py:78-80`
- §3.4 — insert — ambiguity — hop 5 is conditioned on the *change* into `STALE` (`previous != "STALE"`), so an already-stale title gets no fresh takedown; `SCHEDULED` windows survive — `services/domain.py:60-76,93-94`
- §3.4 — revise — mismatch — "two consequences" → **three**, plus the ladder's and packages' `version` bumps; this supersede is the only writer of a non-`NONE` `stale_reason` — `services/domain.py:103-113`
- §3.4 — revise — ambiguity — `PENDING` packages are as invisible to the packaging precedence as `REVOKED` ones; `locked_ladder_count` must be recomputed *before* re-derivation — `services/domain.py:79-95`
- §3.6 — insert — ambiguity — both halves of the legal block are required, and it is rung 11 so it outranks the rung-15/16 interval errors — `routes/titles.py:138-145`
- §3.6 — revise — **mismatch** — the title's `version` bumps on **every** successful window scheduling, not only the `DRAFT`→`SCHEDULED` one; `EXPIRED` added to the states that keep `availability_state` — `routes/titles.py:163-165`
- §3.6 — insert — ambiguity — the cancel-driven takedown is a cascade (refreshes `updated_at`, no `version` bump, no `last_sweep_at`); all other cancellations leave the title wholly untouched — `routes/titles.py:204-217`
- §3.6 — insert — ambiguity — `last_sweep_at` records the last *transition*, not the last evaluation, so a never-transitioned title stays null — `services/domain.py:326-328`
- §3.6 — insert — ambiguity — `DRAFT` and `EXPIRED` titles get **no** Phase 4 arm; `PUBLISHED` has no expiry arm; publish is evaluated before expiry but the two are mutually exclusive — `services/domain.py:303-325`
- §3.6 — revise — ambiguity — `takedown_reason` is a **required** body enum with the single value `MANUAL_LEGAL`; omission is a rung-6 missing-field error, not a default — `routes/titles.py:120`
- §3.6 — insert — ambiguity — manual takedown bumps each closed window's `version`, leaves `SCHEDULED` windows alone, and re-derives nothing else — `routes/titles.py:124-129`

## Verdicts on the two PRD-internal tensions
1. **§3.4 double statement — the negative form is right, the "stated positively" sentence was wrong.** `routes/ladders.py:163` is `if not any(m["qc_state"] == "QC_PASSED" …)` and `:165` is `if any(m["qc_state"] == "REMEDIATION_REQUESTED" …)`. There is no universal quantifier anywhere in the handler, so a title holding `INGESTED`, `QC_FAILED` or `QC_REJECTED` masters beside one `QC_PASSED` master locks. I rewrote the sentence to state the two-clause guard and to say explicitly that a universal pass is **not** required, and I pinned the guard order (`ERR_NO_PASSED_ASSET` first, from source line order).
2. **§3.2 third attempt — the master keeps both figures.** `routes/assets.py:94` sets `latest_severity_index` before the branch, and `:100` sets `blocking_defect_code = figures["blocking_defect_code"]` on the whole FAIL arm, which the `QC_REJECTED` case at `:101` shares. So the terminal master carries the failing attempt's `severity_index` and non-`NONE` blocking code permanently. I also pinned that `recompute_readiness` (`services/domain.py:20-23`) always writes both variants, which resolves the per-branch "only certified"/"only provisional" wording in §3.2 and §3.4 hop 4.

## HAND-OFF NOTES

**For pass 3 (§3.5 / §3.7 / §3.8 / §3.9):**
- §3.9 — `complete_job` (`services/domain.py:193-208`) builds the result ladder with `state` `LOCKED`, `validation_reason_code` `"OK"`, but `device_compat_score` 0.00 and `compatible_device_count` 0 (`build_ladder` hardcodes both at `:184-185`) — a locked, never-validated ladder that reports `OK` with zero compatibility. Check §3.9 pins this. Also `complete_job` calls `recompute_locked_count` **before** `supersede_ladder`, which recomputes it again, so the net count is correct but only via the second call.
- §3.9 — `complete_job` copies `source["rungs"]` verbatim into the result ladder (same rung geometry, different `codec_family`), and sets `derived_from_ladder_id` to the source id. Verify §3.9 pins the copy rather than a recomputation.
- §3.9 — `fail_job` (`services/domain.py:211-218`) zeroes `committed_usd` and calls `recompute_budget`, but does **not** touch the title's `version` (correct per §2.7) and does not re-derive packaging or readiness.
- §3.9 — `recompute_budget` (`:32-44`) and `committed_total` (`:47-57`) both sum **`cost_estimate_usd`** over `RUNNING`/`COMPLETED` jobs, and `recompute_budget` applies `q2()` twice (once to the sum, once to the difference). §3.1's PATCH prose says "sum of `committed_usd`", which is observationally identical because `routes/jobs.py:116` sets `committed_usd = cost_estimate_usd` on run — but pass 3 should confirm §3.9 does not describe a case where the two diverge for a `RUNNING`/`COMPLETED` job.
- §3.7 — `vendor_health` (`services/calc.py:408-424`) returns `contract` of 100.00 when `weight_total` is 0 (all metrics carry `play_attempts` 0), a distinct branch from the "no metrics" branch. Also `refresh_vendor_health` (`services/domain.py:145-166`) evaluates the drain arm first and re-steers only when the state actually *changed* into `DEGRADED`/`DRAINED`.
- §3.7 — `resteer_policy` (`services/domain.py:126-142`) appends the outgoing primary to `excluded_vendor_ids` only when it is not already present, and increments `resteer_count` on every call including one that lands on `UNROUTABLE`.
- §3.7 — `vendor_code` is described in §3.7 as "2 to 16 uppercase characters"; if its pattern is `^[A-Z0-9]{2,16}$` (as `studio_code`'s was), that wording is the same mismatch I fixed in §3.1.
- §3.8 — Phase 2 sets `released_gbps` on end and refreshes only the `active_vendor_id` carrier (`services/domain.py:267-274`).

**For pass 4 (reconciliation, touching §1/§2/§4/§5):**
- Nothing I changed contradicts §2, but three of my inserts lean on pass 1's §2 numbering and should be re-read together: §3.3's "rung-6 payload violation … evaluated before the `device_class` uniqueness check" (rung 6 vs rung 9), §3.6's "rung 11 … ahead of rungs 15 and 16", and §3.6/§3.4's version-vs-`updated_at` claims which defer to §2.9's cascade rule and §2.7's exhaustive `Title.version` list. §2.7 line 144 already lists "scheduling a licensing window" unconditionally, which is exactly what my §3.6 mismatch fix now agrees with — previously §3.6 and §2.7 contradicted each other.
- §4's `GET /titles` row already lists `external_ref` (pass 1 added it); my §3.1 prose now matches, so the two are consistent.
- §4's `GET /mezzanine-assets/{id}` row already names `last_qc_report_id`; §3.1/§3.2 now introduce the field, so it is no longer undefined prose.

## Judged already correct — do not re-litigate
- §3.1's readiness formula (weights 0.50/0.20/0.30, per-component rounding *before* weighting, 0.00 on an empty master set, certified ≤ provisional, 80.00 gate) matches `services/calc.py:51-91` exactly.
- §3.2's entire penalty/blocking/verdict calculation matches `services/calc.py:105-148` literal for literal, including the `> 6.0` strict boundary, the `>= 40.0` aggregate breach, and `WARN` on `severity > 0 or artifact_defect_count >= 3`.
- §3.3's three compatibility tests, the `rung_count / 5` coverage multiplier capped at 1.00, the "round only after multiplying" order, the 5.00 bonus gated on `peak_height_px >= 2160` **and** `count >= 1`, and the 100.00 cap all match `services/calc.py:180-201`.
- §3.4 hop 2's "same `title_id` **and** same `codec_family`, other locked ladders only" matches `routes/ladders.py:175-179`; a different-codec locked ladder genuinely coexists.
- §3.6's four Phase 4 bullets match `services/domain.py:305-325` condition for condition (I only added the missing source states and the precedence note).
- §3.6's "no state guard at all" claim about manual takedown is correct — `routes/titles.py:118-130` has no state check of any kind.
- §3.1's "sum of `committed_usd` across `RUNNING` and `COMPLETED` jobs" is observationally identical to the code's `cost_estimate_usd` sum; I left the wording alone deliberately (see hand-off note to pass 3).

---

Pass 3 complete.

## Result

`workspace/PRD_COMPLETED.md` — **487 lines** (unchanged; every edit was in-paragraph), **153,063 bytes** (+10,027 vs the 143,036 I started with). Section boundaries are byte-for-byte identical (§3.1 at 174 … §5 at 424), the file still ends on the complete §5 error table (`ERR_ENCODE_BUDGET_EXCEEDED | 422`), pass 1 survived (`api_request_id` / `req_RANDOMALPHANUM123456` intact in §2.2, §4 and §5 tables untouched), and pass 2 survived (§3.4 still carries its "emphatically **not** a requirement that every master of the title have passed" rewording).

**Counts: 12 ambiguity-pins, 8 mismatch-revisions (20 edits).**

### Changes
- §3.5 — revise — mismatch — rule list filters are `region_code`, `subscription_tier` **and** `device_class_scope`, all literal exact-match — `routes/drm.py:228-232`
- §3.5 — insert — ambiguity — rule attachment has no package-state guard (attachable to `PENDING`/`PACKAGED`/`STALE`/`REVOKED`), bumps the package's `version`, re-derives nothing, and is gated on the package's currently stored `hdcp_floor` — `routes/drm.py:184-222`
- §3.5 — revise — mismatch — the packaging master-quality gate is "≥1 `QC_PASSED` (`ERR_NO_PASSED_ASSET`) and no `REMEDIATION_REQUESTED` (`ERR_ASSET_REMEDIATION_PENDING`)", **not** "every master `QC_PASSED`" — `routes/drm.py:71-76`
- §3.5 — insert — ambiguity — on the `PENDING` path a supplied `ladder_id` is existence-checked at rung 8 but otherwise ignored — `routes/drm.py:133-146`
- §3.5 — insert — ambiguity — on the repackage path a wrong-title rebound ladder also yields `ERR_LADDER_NOT_LOCKED`; `ERR_LADDER_TITLE_MISMATCH` is never reported by this endpoint — `routes/drm.py:150-155`
- §3.5 — revise — mismatch — both readiness variants are recomputed on **both** packaging paths — `routes/drm.py:164-165`, `services/domain.py:20-23`
- §3.5 — revise — mismatch — revocation recomputes both variants from all three source states (incl. `PENDING`, dropping provisional by 30.00) — `routes/drm.py:179-180`
- §3.5 — insert — ambiguity — entitlement-check inputs: `region_code` is `^[A-Z]{2}$` (no wildcard), `subscription_tier` includes `ANY`, `device_class` is the six-value enum and never a profile id, `requested_streams` min 1 with no maximum, `offline_requested` defaults false — `routes/drm.py:41-48`
- §3.5 — insert — ambiguity — `device_class` is unique per rung 9, so stage 2 never picks between candidates; a retired-only class reports `ERR_DEVICE_PROFILE_NOT_FOUND` — `routes/ladders.py:50-53`, `routes/drm.py:254-260`
- §3.5 — insert — ambiguity — the response `data` is exactly those seven keys, no `evaluated_at`/`id`/input echo — `routes/drm.py:284-292`
- §3.7 — revise — mismatch — `vendor_code` is `^[A-Z0-9]{2,16}$`; digits are accepted — `routes/delivery.py:23`
- §3.7 — insert — ambiguity — an empty/absent PATCH body is an accepted no-op that still bumps `version`; state, health, breaches and `reserved_gbps` are not editable — `routes/delivery.py:29-34, 86-102`
- §3.7 — revise — ambiguity — `committed_gbps` **strictly** below `reserved_gbps` is refused, equality accepted, and nothing persists on refusal — `routes/delivery.py:91-95`
- §3.7 — insert — ambiguity — egress demand counts matching title+region windows with no vendor or device filter — `services/calc.py:341-343`
- §3.7 — insert — ambiguity — `ERR_VENDOR_REGION_NOT_SERVED` (rung 14) outranks the rung-15 interval/clock errors; vendor `state` is no ingest precondition — `routes/delivery.py:175-184`
- §3.7 — insert — ambiguity — an ingest that leaves the state unchanged re-steers nothing (cascade keyed on *change*, not on unhealthiness) — `services/domain.py:162`
- §3.7 — insert — ambiguity — `DRAINED` accepts further ingests that keep rewriting both figures and `breach_window_count` (which can fall back under 5) yet never leaves `DRAINED`; every ingest bumps `version` unconditionally — `services/domain.py:145-161`
- §3.8 — insert — ambiguity — `failover_vendor_id` is nullable: explicit `null` ≡ omission; non-null must resolve at rung 8 — `routes/live.py:22, 50-52`
- §3.8 — insert — ambiguity — booking checks neither vendor's `regions` nor either vendor's `state` — `routes/live.py:46-68`
- §3.8 — revise — mismatch — arming's clock guard is rung 10 and precedes both rung-11 content guards; the routing guard also answers `ERR_PACKAGE_NOT_READY`; packaging is reported first; any routable policy of the title suffices — `routes/live.py:118-132`
- §3.8 — insert — ambiguity — a `DEGRADED` standby is a legal failover target; only `DRAINED` (and a null standby) is refused, all under `ERR_VENDOR_CAPACITY_EXCEEDED` — `routes/live.py:145-153`
- §3.9 — insert — mismatch — creation's reported precedence puts `ERR_LADDER_TITLE_MISMATCH` ahead of `ERR_REPROCESS_CODEC_UNCHANGED` (both rung 14) — `routes/jobs.py:44-47`
- §3.9 — insert — mismatch — the result ladder is stored with `device_compat_score` 0.00, `compatible_device_count` 0, `superseded_by_ladder_id` null, and is never rescored — a shape no operator-authored lock can reach — `services/domain.py:174-190, 197-200`
- §3.9 — revise — mismatch — hop 4 re-derives `locked_ladder_count` and recomputes **both** readiness variants; completion runs no budget recomputation — `services/domain.py:201-208`
- §3.9 — insert — ambiguity — failure rewrites only `encode_budget_remaining_usd` on the title; packaging, locked count and both readiness variants stand — `services/domain.py:211-218`

### Verdicts on hand-off items
- **§3.5 entitlement (pass 1):** all confirmed against `routes/drm.py:243-292` — enum `device_class`, `requested_streams` min 1 no max, `offline_requested` default false, the five-stage order, the seven `data` keys, the three-way `min()`, and `offline_granted` needing all three flags. Pinned. **One exception:** the "ladder term dropped when the bound ladder no longer exists" guard (`drm.py:282`) is **unreachable** — nothing anywhere deletes a ladder (`grep 'del db\.\|\.pop('` over `implementation/` returns nothing), so I did not pin an unobservable branch. §3.5 does not contradict pass 1's §2.4/§2.6 facts.
- **§3.7 (passes 1+2):** all confirmed — drain arm first (`domain.py:154`), `DRAINED` never recovers, `touch(vendor)` unconditional (`:161`), cascade gated on `current != previous and current in ("DEGRADED","DRAINED")` (`:162`), scoped to `primary_vendor_id` matches only (`:164`); `resteer_policy` (`:126-142`) appends only when absent, always increments `resteer_count`, always recomputes egress. `vendor_code` regex confirmed as `^[A-Z0-9]{2,16}$` → wording fixed. **Dissent on one item:** `vendor_health`'s `weight_total == 0 → contract 100.00` branch (`calc.py:422`) is **unreachable** — `METRIC_CREATE` declares `play_attempts` with `minimum=1` (`delivery.py:49`), so any vendor with rows has `weight_total ≥ 1`. Not pinned.
- **§3.8 (passes 1+2):** all confirmed — `q2(held + reserved) <= committed` (`live.py:32`), create order NOT_LIVE_EVENT→FAILOVER_SAME→BOUNDS→IN_PAST→OUTSIDE_LICENSE→CAPACITY (`live.py:53-68`), Phase 2 end sets `released_gbps` and refreshes only the `active_vendor_id` carrier (`domain.py:267-274`). The create order already matches §2.6's rung 14→15→19 sequence, so no §3.8 edit was needed for it.
- **§3.9 (passes 1+2):** all confirmed — Phase 3 discriminator (`domain.py:280-288`), verbatim `rungs` copy with hardcoded zero compat figures (`:174-190`), no `recompute_budget` on completion, `recompute_locked_count` called twice (before `supersede_ladder`, which repeats it — net result correct, intermediate unobservable, so not pinned), `fail_job` zeroing and recomputing without touching `version` or packaging (`:211-218`). **`recompute_budget`/`committed_total` cannot diverge from `committed_usd`:** `jobs.py:116` sets `committed_usd = q2(cost_estimate_usd)` (already q2), completion never rewrites it, and abort/fail zero it in lockstep with the state leaving `RUNNING`/`COMPLETED` — so §3.9's line-113 invariant holds exactly and needed no change.

### HAND-OFF NOTES for pass 4 (found outside my partition, not edited)
1. **§3.1 (pass 2's):** if §3.1 still says the encode budget is "the sum of `committed_usd`", that is observationally correct but describes the wrong summand — `services/domain.py:34-44` and `:47-57` both sum **`cost_estimate_usd`** over `RUNNING`/`COMPLETED`. §3.9 line 113 already says `cost_estimate_usd`, so §3.1 and §3.9 may read as two different rules for one ledger. Worth reconciling to §3.9's wording.
2. **§3.3 (pass 2's):** `compat_figures` (`calc.py:170-177`) counts a profile's `required_drm_system` as satisfied by a package in `PENDING` **or** `PACKAGED` — but never by a `STALE` one, even though a `STALE` package still advertises the same `drm_systems`. Worth checking §3.3 pins the two-state set exactly.
3. **§3.4 (pass 2's):** `lock_ladder` (`routes/ladders.py:150-183`) calls `touch(title)` at hop 1 — the lock bumps `Title.version` **before** the supersede cascade runs, and §2.7 does list "locking a ladder". Consistent, just flagging the ordering in case §3.4 implies otherwise.
4. **§2.9 (pass 1's):** Phase-3 completion mutates the title's `packaging_state`, `locked_ladder_count` and both readiness variants with **no** `updated_at` refresh unless the hop-5 takedown fires (`domain.py:201-208`, `stamp_only` only inside `packaging_stale_cascade`). §2.9's existing sentence ("refreshes `updated_at` when it transitions the title's own `availability_state`, and leaves `updated_at` untouched when it merely re-derives…") already covers this exactly — **no change needed**, recorded so pass 4 does not re-open it.
5. **§4 table (pass 1's):** there is no `GET /cdn-vendors` list endpoint in `routes/delivery.py` (only read-by-id and PATCH). Pass 1 says it verified §4 programmatically; flagging only so pass 4 can confirm the table has no phantom row.

### Judged already correct despite looking suspicious (do not re-litigate)
- **Metric-ingest and reservation-create check orders.** §3.7's and §3.8's prose lists the guards in a reader-friendly order that differs from the evaluation order, but §2.6's rung ladder pins the real precedence uniquely in both cases. I added one clarifying sentence to §3.7 (mirroring §3.6's existing precedent) and rewrote §3.8's arming bullet where the divergence spanned two *different* rungs; the reservation-**create** order needed nothing.
- **Policy creation: `ERR_DUPLICATE_ROUTING_POLICY` before `ERR_NO_ELIGIBLE_VENDOR`.** Matches §2.6 rung 17 → rung 18. Left alone.
- **`rank_vendors`' double sort** (`calc.py:310-322`): the `_seq` pre-sort plus stable sorts yields exactly the documented "`created_at` ascending, then insertion order" tie-break chain. Correct as written.
- **The worked egress example (480.00 → 38.40 → 518.40) and the reprocess example (3.11 / 6.35 / 13.10 / 26.06 → 48.62).** I recomputed both under `Decimal` `ROUND_HALF_UP`; both are exactly right.
- **`billable_minutes` returning 0 for an all-`QC_REJECTED` title** (`calc.py:240-248`) is unreachable: rung 18's `ERR_REPROCESS_NO_SOURCE_ASSET` fires before `reprocess_cost` is called (`routes/jobs.py:51-56`). Not pinned.

---

All four passes' work verified intact; (D) complete. Below is the self-contained exit summary.

---

## PASS 4 of 4 — RECONCILIATION — EXIT SUMMARY

**File:** `/home/ubuntu/github/CodingPRD/tasks/task_2972_streaming_encoding_content_delivery_operations/workspace/PRD_COMPLETED.md`
**Final size:** 487 lines / **154,850 bytes** — delta from the 153,063-byte baseline: **+1,787 bytes, +0 lines** (every edit was an in-paragraph revision, so all heading line numbers are unchanged).
**Edits applied:** 4, all via targeted `Edit`. No `cp`, no rewrite. Nothing outside `PRD_COMPLETED.md` was modified.

### Passes 1–3 survived (grep evidence)
| Pass | Marker | Result |
|---|---|---|
| 1 | `api_request_id` in §2.2 | present at L40, L52, L65, L76, plus §2.4's L88 shape pin (`req_` + exactly 20 chars of `[A-Z0-9]`) |
| 2 | §3.4 dropping the "every master must be `QC_PASSED`" claim | present at L230: "It is emphatically **not** a requirement that every master of the title have passed." |
| 3 | `vendor_code` `^[A-Z0-9]{2,16}$` fix in §3.7 | present at L289 in prose form — "2 to 16 characters drawn from the uppercase letters `A`–`Z` and the digits `0`–`9`" — exactly matching `delivery.py:23` |
| 1 | §5 58-id table | 58 data rows, 58 unique codes, 0 duplicates, last row `ERR_ENCODE_BUDGET_EXCEEDED | 422` |
| 1 | §4 endpoint table | 53 route rows, unchanged |

Note: my first greps for pass 2 and pass 3 returned nothing because my patterns were wrong (missing `**not**` bold markers; regex written as prose). Both were re-located and confirmed — **no pass's work was lost.**

### (A) Hand-off items
- **A1 — RESOLVED, 1 edit (L180, §3.1).** §3.1 named the budget ceiling "the sum of `committed_usd`"; §2.9 L162 and §3.9 L356 name `cost_estimate_usd`. Code sums `cost_estimate_usd` (`domain.py::recompute_budget`, `domain.py::committed_total`). The two are equal by construction: `jobs.py:116` sets `committed_usd = q2(cost_estimate_usd)` on run, nothing rewrites it, and only `fail_job`/`abort_job` zero it — so §2.9's "remaining + Σ`committed_usd` = `encode_budget_usd`" identity also holds. Rewrote §3.1 to the code's field, stated the equality and its reason, and pinned the boundary `update_title` actually implements (`proposed < committed_total(...)`): **a proposed budget exactly equal to the committed total is accepted and leaves `encode_budget_remaining_usd` at 0.00.** The `committed_usd` wording was pre-existing in `PRD_FINALIZED.md`, not pass-introduced.
- **A2 — no edit needed.** §3.3 L220 already pins exactly `PENDING` or `PACKAGED` and states `STALE`/`REVOKED` never satisfy a DRM requirement — matching `calc._drm_satisfied`. §3.5 L246 agrees.
- **A3 — no edit needed.** §3.4 Hop 1 already places the `Title.version` bump at hop 1 and states "That single increment is the whole call's effect on `Title.version`" — matching `ladders.py::lock_ladder`, which does `touch(title)` at hop 1 *before* the supersede loop. §2.7's enumeration is exhaustive and exact: its 8 listed operations are precisely the 8 `touch(title)` call sites in the codebase.
- **A4 — no edit needed, verified programmatically.** Parsed all 53 `@bp.<method>` + `@endpoint([...], scope=)` pairs from `routes/*.py` against all 53 §4 rows: **0 phantom PRD rows, 0 unlisted impl routes, 0 role-list mismatches, 0 duplicates.** The non-existent `GET /cdn-vendors` is correctly absent from §4 as well. All five `scope=` routes are represented.
- **A5 — confirmed, left alone.** `stamp_only` has exactly three call sites (`packaging_stale_cascade`, sweep Phase 4, `cancel_window`'s CONTRACT_END takedown) — all three transition `availability_state`. Phase-3 completion re-derives `packaging_state`, `locked_ladder_count` and both readiness variants with no `updated_at` refresh unless hop 5 fires. §2.9's existing sentence covers this exactly.

### (B) Contradiction hunt
**Rung citations: all 22 non-definitional citations verified CORRECT against §2.6's numbered list and the code's real check order. Zero corrections required.** Verified: L96, L107 (rung 6, closed body specs on clock/sweep); L123 (rung 18 `ERR_REPROCESS_NO_SOURCE_ASSET`); L144 (rung 6, stray `expected_title_version`); L204 (rung-6 unknown field on resubmit); L210 (rung-6 inverted bitrate window *before* rung-9 uniqueness — matches `ladders.py:50-54`); L254 (rung 10 does not reach rule attachment — `create_rule` has no package-state guard); L256 (rung 8 `ERR_LADDER_NOT_FOUND` before the rung-10 state check — matches `drm.py:136-137`); L262 (`*` rejected at rung 6); L264 (rung 9 `device_class`); L272 (rung-11 `ERR_TITLE_LEGALLY_BLOCKED` ahead of rungs 15/16); L285 ×2 (rung-6 on manual takedown); L289 (rung 6 `vendor_code` pattern); L314 (rung-14 region rule ahead of rung-15 bounds/clock); L326 (rung 8 `failover_vendor_id`); L336 (rung 10 clock+state, rung 11 content guards); L348 (both rung-14, title-mismatch first). §2.6's own 20 rung definitions were also cross-checked against `errors.py`'s rung-grouping comments — consistent.

**Three genuine cross-section contradictions found and closed (3 edits):**
1. **§3.1 L186 vs §3.2/§3.5 (edit).** L186 (pre-existing) claimed both readiness variants are recomputed after *any* mutation of masters/ladders/packages. Two routes provably don't: `assets.py::request_remediation` and `drm.py::create_rule` (pass 2's L254 insert already said so for the latter). Both omissions are unobservable — `readiness_scores` counts only `INGESTED`/`QC_PASSED` (provisional) and `QC_PASSED` (certified), with the master count as denominator, and the package component reads `state` alone. Narrowed L186 to name the two exemptions and prove them invisible.
2. **§3.4 L242 vs §3.3 L226 / §3.5 L254 (edit).** L242 (pre-existing) claimed `packaging_state` is re-derived after *every* mutation of the title's ladders or packages. `validate_ladder` and `create_rule` don't call `derive_packaging`; neither changes any package `state` or `locked_ladder_count`, so re-deriving would be a no-op. Added the two exemptions with their reason.
3. **§3.9 L360 dangling cross-reference (edit).** "the depth-4 cascade of §2.9" — §2.9 names only two cascades (five-hop ladder-lock, metric-ingest) and no depth-4. Rewrote as "a four-hop cascade under the transitive rule of §2.9 — hops two through four are the same chain §2.9 names the ladder-lock cascade, entered here from a job completion rather than from an operator's lock."

**Verified consistent, no edit:** §2.9's `Title.version` exception vs §2.7's 8-operation list (exact); the vendor `reserved_gbps` ledger (§2.9 L160 / §3.8 L332 / L291 `version` 2 claim — all match `refresh_vendor_reserved` + `touch(vendor)`); the encode-budget ledger across §2.9 L162 / §3.1 / §3.9 L356 (now uniform); the two interval geometries (§2.10 vs §3.6 half-open, §3.8 closed buffer-inflated); the packaging staleness cascade hops in §3.4 vs §3.9 (locked-count re-derivation is idempotent at both cited points); §3.9 L361's "only field a failure rewrites" (`fail_job` calls only `recompute_budget`); §3.4's lock guards vs `lock_ladder` (order and both errors exact); §3.9 L360's result-ladder shape vs `build_ladder` (`device_compat_score` 0.00, `compatible_device_count` 0, born `LOCKED`/`OK`).

### (C) Unreachable-branch verdicts — **pass 3 was right on all three; all left unpinned**
- **`drm.py:282` missing-ladder guard — UNREACHABLE.** `grep -rn "del db\.\|\.pop(\|\.clear()\|reset()"` over `implementation/` returns only `db.py:26: self.reset()` (constructor). No ladder is ever deleted, and `package["ladder_id"]` is only ever written from a resolved ladder (`drm.py:94`, `drm.py:158`). No other section implies observability — §3.5 L268 states `effective_height_px` as "the smallest of three numbers" with no fallback.
- **`calc.py:422` `weight_total == 0 → 100.00` — UNREACHABLE.** `vendor_health` early-returns on `not metrics`, and `delivery.py:49` declares `play_attempts` with `minimum=1`, so `weight_total >= 1` whenever the `else` could be reached. §3.7 L318's "again 100.00 when no rows exist" correctly describes the *reachable* early return.
- **`calc.py:240-248` zero-`billable_minutes` path — UNREACHABLE.** `billable_minutes` is called only from `reprocess_cost` (`calc.py:252`), reached only after rung 18's `ERR_REPROCESS_NO_SOURCE_ASSET`, whose `_has_eligible_master` predicate (`jobs.py:29`) is byte-identical to `billable_minutes`' filter. §3.9 L348/L350 are consistent.

### (D) Integrity checklist
1. `wc -l -c` → 487 / 154,850; **+1,787 bytes** from baseline. ✓
2. `tail` → ends on the complete §5 table, final row `| ERR_ENCODE_BUDGET_EXCEEDED | 422 |`, not mid-sentence. ✓
3. Heading index → all 23 headings present, in order, none duplicated or missing (§1 L3; §2 L11 with §2.1–§2.10 at L13/31/80/86/94/109/136/146/152/164; §3 L172 with §3.1–§3.9 at L174/192/208/228/244/270/287/324/344; §4 L364; §5 L424). ✓
4. All three prior passes confirmed present (table above). ✓
5. `grep -c 'rung'` → 38 lines; every citation verified in (B). ✓
6. §4 → 53 route rows (0 diffs vs impl); §5 → 58 rows, 58 unique codes, 0 dupes. ✓
7. Leak grep for `harder than expert|SCAFFOLD|scaffold_difficulty|scaffold_corner|test_suite|test_helpers|worklog` → **exit 1, zero hits.** No leaks to remove. ✓

### Counts
- **Ambiguity-pins: 1** (budget exactly equal to the committed total is accepted → remaining 0.00)
- **Mismatch-revisions: 1** (A1: `committed_usd` → `cost_estimate_usd` as the budget-floor basis)
- **Contradiction-closures: 3** (§3.1 readiness "any mutation"; §3.4 packaging "every mutation"; §3.9 dangling "depth-4 cascade of §2.9")
- **Total edits: 4** (A1 carried both the mismatch-revision and the ambiguity-pin)

### One pre-existing nit reported, deliberately not edited
§2.6 rung 14 (L126) opens "Five referential rules, all 422:" then enumerates six distinct error identifiers. `difflib` confirms L126 was untouched by any pass (pre-existing in `PRD_FINALIZED.md`), so it is not a cross-pass seam; all six identifiers and their conditions are spelled out immediately after, so the clause-count phrasing has zero behavioral impact. Left alone per the minimal-edits mandate and pass 1's ownership of §2.

**Scratch hygiene:** `.scratch/step9_pass4/` was created empty and removed with `rmdir` (never `rm -rf`). Siblings `step2`, `step4`, `step5`, `step6`, `step7` verified intact. `worklog.md` was never read, created or written.

---

**Orchestrator closing note.** Pass 4's byte figure (154,850) predates my own one-word §2.6 rung-14 fix described at the top of this entry, which took the file to **154,849 bytes** ("Five" → "Six" is one byte shorter). That is the final state of `workspace/PRD_COMPLETED.md`. Step 9 is complete and the pipeline is finished: all nine steps have run, the 8-round stability sweep was 298/298 in every round with a cross-round union of zero non-passing tests, and `PRD_COMPLETED.md` differs from `PRD_FINALIZED.md` (first difference at line 29), confirming the completeness scan actually executed.
