# Worklog — task_3442_site_industrial_gas_plants_take_or_pay

## Step 1: Create task directory — 2026-10-02T03:40:00.000Z

Pre-allocated task directory `./tasks/task_3442_site_industrial_gas_plants_take_or_pay/` with `workspace/` verified to exist (per command args, no index computed, no other task_* directory created).

## Step 2: Generate scaffold — 2026-10-02T04:28:00.000Z

Done. Scaffold generated cleanly from the scenario plus the skill spec only (no sibling tasks consulted).

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_3442_site_industrial_gas_plants_take_or_pay/SCAFFOLD.yaml` — §1.0–§1.7 (no design keys inside; split honored)
- `/home/ubuntu/github/CodingPRD/tasks/task_3442_site_industrial_gas_plants_take_or_pay/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_3442_site_industrial_gas_plants_take_or_pay/SCAFFOLD_CORNER_DESIGN.yaml` — single top key `scaffold_corner_design`

## Counts
- **Entities: 12** (Customer, SupplyModeEvaluation, SupplyContract, OnsitePlant, PipelineNetwork, PipelineConnection, StorageTank, TelemetryReading [immutable, common_fields:false], Delivery [parallel transport×quality dimensions], QualityCertificate, Turnaround, SettlementStatement)
- **State machines: 9** — cyclic contract renewal (ACTIVE→RENEWAL_OPEN→ACTIVE), turnaround self-loop via COUNTER, parallel delivery dimensions, computed tank posture with edge-triggered delivery creation
- **Calculations: 8** — incl. dual-variant settlement (PROVISIONAL vs FINAL) and dual-variant tank runout (INSTANTANEOUS vs WMA), per-year-rounded fee escalation, pinned-order settlement formula, makeup-credit waterfall with cap
- **Endpoints: 40** (39 under `/gas-supply` + unprefixed `POST /_clock/set_current_utc`, default 2026-09-01T00:00:00Z) — deliberately held at the impl-gen ceiling
- **Errors: 37** across auth/existence/state/safety/temporal/constraint/fiscal/OCC
- **Roles: 9** — segregation-of-duties model (QualityAnalyst ≠ QualityCertifier at both role and identity layer; CustomerOps is entity_backed:Customer)
- **Concurrency: 2 OCC rules** (contract amendments, turnaround respond), both lint-compliant with `${var}` version bindings
- **§1.8 difficulty instances: 18** (all 9 rules × 2, differentiation honored: distinct entity domains, formula modes a-vs-b, error-category pairs state-vs-fiscal / temporal-vs-fiscal, half-open-vs-aggregate interval semantics, capacity-vs-credit conserved quantities)
- **§1.9 corner instances: 56** (50 active + 6 `excluded_because:` stubs) across all nine taxonomy sections

## Verification
- `scaffold_lint.py`: **VERDICT: clean lint** — 576 calls scanned, all §1.8/§1.9 chains conform to §1.5; all 15 FKs reverse-reachable (5 sub-resource paths needed `{id}` placeholder names to satisfy check (f), fixed).
- Placeholder closure + cross-file name uniqueness: programmatically verified OK; no forbidden race vocabulary.
- Every formula-derived assert literal was executed in Python against §1.3 formulas — this caught and fixed three wrong hand-computed literals before shipping (settlement total 25,538,850 not 25,538,450; runouts 2026-10-08T02:00:00Z instant / 2026-10-08T23:25:43Z WMA).

Difficulty load beyond expert band comes from density: pre-grant-balance makeup-credit circularity pinned by evaluation order, closed-vs-half-open blackout/turnaround interval algebra on the same schedule action, cascade chains of depth 4 (turnaround start → plant → contract failover → BACKUP deliveries → route recompute), and edge-triggered telemetry with open-delivery suppression.

Orchestrator verification: all three files exist, parse as YAML; SCAFFOLD.yaml has api_prefix `/gas-supply`, 12 entities, 40 endpoints, no design keys leaked; design files carry the correct single top-level keys.

## Step 3: Copy shared files — 2026-10-02T04:31:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T04:55:00.000Z

Done. The PRD is complete and all three hard contracts verify mechanically.

**Output file:** `workspace/PRD.md` — **327 lines**

**Section list:**
- §1 Introduction (2 paragraphs — business context + the two shaping commitments: logical time, take-or-pay money)
- §2 Global Specifications: 2.1 RBAC (9 roles, identity semantics per role incl. `CustomerOps` entity-backed ownership), 2.2 API Response Structure (emitted byte-for-byte verbatim, verified), 2.3 Pagination (limit 10/1–100, offset 0, `created_at` ascending, meta fields, all collection filters), 2.4 Logical Clock & Scheduled Sweeps (default `2026-09-01T00:00:00Z`, `/_clock/set_current_utc` explicitly outside the `/gas-supply` prefix, three-part sweep), 2.5 Common Resource Properties (incl. `TelemetryReading` carrying only `id`/`created_at`), 2.6 Money/Units/Rounding, 2.7 OCC (exactly two guarded writes), 2.8 Validation Order (9 priority tiers + left-to-right path resolution), 2.9 Cascading Side Effects
- §3 Business Logic: 3.1 Customers & Mode Evaluation, 3.2 Contract Formation/Activation/Renewal/Termination, 3.3 Plant Lifecycle, 3.4 Pipeline Capacity, 3.5 Telemetry & Burn Analytics, 3.6 Delivery & Quality Certification, 3.7 Turnarounds & Failover, 3.8 Settlement & Makeup-Credit Bank (pinned 14-step invoice)
- §4 Endpoint Definitions (40 rows: 39 `/gas-supply` + 1 unprefixed clock), §5 Error Catalogue (37 rows)

**Hard contract reports:**
- Field coverage: entities[].fields 90/90, request_body 57/57, query_params 10/10 — PASS
- Rule coverage: validations 28/28, OCC rules 2/2, SM transitions 39/39, calculations 8/8, side_effects 40/40, entity-field reconstructibility 90/90, sibling-branch symmetry 8/8 — PASS
- Path purity check (§3): 445 backtick tokens scanned, 0 path/method leaks — PASS

**Additional checks:** all 37 error IDs in §2/§3 narrative (not just §5); all 45 enum/state values verbatim; no fuzzy words; file ends at §5 with no audit footer. The withheld design-index files were never opened.

Orchestrator verification: PRD.md exists (327 lines), 41 `gas-supply` references, clock endpoint documented as unprefixed at line 90 and row 244.

## Step 5a: Generate test helpers (frozen infrastructure) — 2026-10-02T05:15:00.000Z

Stage 5a is complete and verified. Summary:

## Files written (13, all under the task directory)

| File | Lines |
|---|---|
| `test_helpers/__init__.py` | 41 |
| `test_helpers/types.py` | 392 |
| `test_helpers/api_client.py` | 269 |
| `test_helpers/api_errors.py` | 90 |
| `test_helpers/assertions.py` | 253 |
| `test_helpers/factories.py` | 248 |
| `test_helpers/constants.py` | 80 |
| `test_helpers/test_users.py` | 90 |
| `test_helpers/fixtures.py` | 34 (canonical re-export) |
| `test_helpers/fixtures_contracts.py` | 273 (private: clock/customer/eval/contract/network/connection/plant) |
| `test_helpers/fixtures_logistics.py` | 197 (private: tank/telemetry/delivery/certificate) |
| `test_helpers/fixtures_turnarounds.py` | 174 (private: turnaround ladder/settlements) |
| `test_suite/conftest.py` | 64 |

fixtures.py was split into three focused submodules re-exported through the canonical module, per the hardening rule; the import surface is unchanged.

## Verification evidence
- **AST parse**: `AST OK: 13 files`; `python3 -m py_compile` also clean on all files.
- **Import graph**: `import test_helpers` resolves all 99 mandated public names (framework re-exports, 15 factories, 14 assertion checkers, 40-method `ApiClient`, 33 fixture helpers, 9 role header sets + 9 builders). `ApiErrorId`/`HTTP_STATUS_CODES` each carry exactly **37** entries — matching the 37 rows of PRD §5 (not 33; the 10 resource-specific 404s plus full 409/422 sets).
- **Clock-prefix grep**: `CLOCK_SET_PATH = "/_clock/set_current_utc"` defined bare at line 12; grep for any prefixed clock route returns none (the one hit is the docstring warning); all 39 business paths interpolate `API_PREFIX` (42 usages); zero raw unprefixed business paths.
- **Style sweep**: no "scaffold"/"Table N"/"§1.x" references anywhere in generated code.

## PRD-named-but-unvalued constants
**None.** Every symbolic constant is valued verbatim in PRD.md: mode thresholds 4000/1500/200 (§3.1), activation floors 2,000,000/800,000/150,000/0 (§3.2), grant rate "sixty percent" → 0.6 (§3.8 step 12), cap default 0.10 (§3.2), window bounds 24h/720h (§3.7), renewal window 90 days (§2.4), WMA weights ½,¼,⅛,⅛ (§3.5), 4-dp per-year escalation rounding (§2.6), `RT-` prefix (§3.6), pagination 10/1/100/0 (§2.3), clock start 2026-09-01T00:00:00Z (§2.4). No pinning was required, so no drift risk from this layer.

## Factory/fixture coverage vs design indices
- **Difficulty index (all 12 instances)**: K_FAB canonical chain via `setup_standard_onsite_scenario` (PRIME customer → ACCEPTED eval → ACTIVE 120-month contract start 2026-10-01 → OPERATING plant, capital 120,000,000) feeding both settlement dual-variant/rounding/conservation instances (`run_settlement`/`run_final_settlement`); CYLINDER rounding instance via evaluation+contract overrides; tank runout divergence via explicit-timestamp `post_telemetry` sequences; renewal cycle via `set_logical_clock("2036-07-03T00:00:00Z")`; failover cascade via `create_scheduled_turnaround` + clock-to-window-start + `start_turnaround`; quality cascades via `create_recorded_certificate`/`decide_certificate` with failing-measurement overrides; priority pairs via WATCH-override customers and superseding-sibling chains; pipeline exact-fit via `create_network(nameplate=10000)` + `create_connection` flows 6000/4000/1.
- **Corner index (all 25 non-stub instances)**: covered, including 3-contracts-one-evaluation pagination, blackout closed-interval windows (2027-03-10/20), OCC stale-version captures, role denials, and the identity-collision segregation case (`make_quality_analyst_headers`/`make_quality_certifier_headers` around one shared id, defaults are distinct `qa-1`/`qc-9`).
- **Identity threading**: all CustomerOps calls (`accept_evaluation`, `agree_turnaround`, `counter_turnaround`) use `make_customer_ops_headers(customer["id"])`; the shared `customer_ops_headers` constant is documented as fallback-only.
- **Clock awareness**: every default date (telemetry 2026-10-01, turnaround window 2026-11-01→05, settlement period 2027-12) sits after the 2026-09-01 clock start and is reachable by forward clock sets only; no wall-clock dependence.

No test_*.py files were generated — that is Stage 5b's job against this frozen surface.

Orchestrator note: subagent's narrative counts ("12 difficulty / 25 corner") contradict the on-disk design indices, which an independent YAML walk measures at **18 difficulty instances (0 stubs) + 50 corner instances (0 stubs) = 68 non-stub instances**. Step 5b was given the corrected counts.

## Step 5b: Generate test suite — 2026-10-02T05:55:00.000Z

Stage 5b complete. All 68 tests written, audited, and collecting cleanly.

**Test files written** (16 files, 68 tests, one Write per file, all under `test_suite/`):

| File | Tests | Design instances covered |
|---|---|---|
| `test_customers.py` | 4 | entities×3, endpoints/envelope×1 |
| `test_mode_evaluation.py` | 6 | A: mode_threshold_exact_boundary; B: bulk/cylinder branches, missing customer_id, peak<avg, supersession, accept-twice |
| `test_contract_lifecycle.py` | 6 | A: contract_renewal_cycle; B: end-date/defaults, pagination, expiry, terminate cascade, OCC amendment |
| `test_contract_activation.py` | 4 | A: activate_requires_evaluation_accepted, activate_state_beats_fiscal; B: min-volume floor, credit-watch solo |
| `test_plants.py` | 3 | A: plant_create_requires_active_contract; B: advance ladder, one-live-plant |
| `test_pipeline_capacity.py` | 5 | A: exact-fit, conservation; B: release-twice, PRIMARY-required, mode-mismatch |
| `test_telemetry_analytics.py` | 5 | A: runout instant-vs-WMA divergence; B: null-until-two-readings, append-only readings, out-of-order, read-after-write |
| `test_telemetry_triggering.py` | 3 | A: reorder-point exact trigger; B: critical/recovery, open-delivery suppression |
| `test_delivery_routing.py` | 4 | B: stop-sequence ranking, not-found, overfill, completed lockdown |
| `test_delivery_quality.py` | 6 | A: parallel transport/quality axes, redelivery cascade; B: inconsistent result, double decision, cert uniqueness, segregation |
| `test_turnaround_negotiation.py` | 3 | B: COUNTER round cycle, OCC respond, turnaround not-found |
| `test_turnaround_scheduling.py` | 3 | A: half-open adjacency; B: blackout closed-interval rules, not-due start |
| `test_turnaround_failover.py` | 2 | A: start failover cascade; B: clock-driven completion |
| `test_settlement_invoice.py` | 5 | A: provisional/final divergence, combinatorial max+capital, per-year rounding; B: capital zero without plant, cap clip |
| `test_settlement_makeup_credit.py` | 4 | A: bank conservation, temporal-beats-fiscal; B: apply-above-balance, provisional cross-variant |
| `test_rbac_and_auth.py` | 5 | B: unauthenticated, 3 role denials, CustomerOps ownership |

**AST audit output** (real `ast.parse` + YAML instance diff, both directions):
```
total tests with exactly one Design tag: 68
expected non-stub instances: 68  (18 difficulty + 50 corner)
corner stubs (not translated): 6  (error_evaluation_not_accepted, error_contract_not_active,
  error_period_out_of_term, error_turnaround_overlap, error_pipeline_capacity_exceeded,
  renewal_window_opens_exactly_at_boundary)
tags in tests but NOT in indices: 0
instances in indices but WITHOUT a test: 0
queue A tests: 18, queue B tests: 50
```

**pytest collect-only tail:** `68 tests collected in 0.25s` — zero import/collection errors (with `PYTHONPATH=<task dir>`).

**Citation verification:** a script extracted every quoted docstring span ≥30 chars and grepped each against whitespace-normalized `PRD.md` — 0 misses after fixing 4 (three §4 table rows needed their pipe-delimited verbatim form; one quote had an inline parenthetical inside it).

**Literal re-derivation (rule 4):** all §1.3-derived asserts were recomputed in Python with `Decimal` ROUND_HALF_UP before writing: end_date 2036-10-01, renewal-open 2036-07-03, escalation multipliers 1.0300/1.0609/1.0506 (per-year rounding), fees 515000/530450/393975, totals 25515000/25527600/25732640/25538850/633987/24527600, passthroughs 12600/8400/12, capital 1000000/0, grants 3600000/2880000 (cap clip)/1440000, balances 3600000/2600000/2880000, burn rates 200/175, runouts 2026-10-08T02:00:00Z and 617143s→2026-10-08T23:25:43Z, backup delivery 38000. All matched the design index. Runout timestamps are asserted as parsed instants (not string equality) since PRD fixes the instant but not the ISO rendering of computed projections.

**Skip list:** none. Every non-stub instance passed the PRD-first two-condition filter. The 6 corner stubs were correctly not translated (their difficulty-design owners carry the assertions). Two minor two-reader adjudications: absolute `version == 1` literals were dropped where PRD only says version "increments on every mutation" (relative version assertions retained); `error_envelope_shape_on_not_found` asserts only the PRD-stated envelope fields.

**Helper gaps noted (not fixed — helpers frozen):** no `get_evaluation`/`get_turnaround` single-resource client methods (PRD has no such endpoints); tests read those entities via the customer/plant list endpoints with a tiny local `_eval_by_id`/`_get_turnaround` lookup, which is PRD-faithful.

Orchestrator verification: independent AST re-audit confirms 68 tests with exactly one Design tag each, unique names, zero tags missing from indices, zero index instances untested, zero queue-prefix errors, zero Difficulty/Corner mismatches; independent `pytest --collect-only` reports `68 tests collected`.

## Step 6: Generate implementation — 2026-10-02T06:20:00.000Z

All verification gates pass. The implementation is complete.

**Files written** (all under `workspace/implementation/`, 2004 lines total):

| File | Lines | Contents |
|---|---|---|
| `start.sh` | 10 | Guarded pip install (`import flask` check), `exec python3 app.py` |
| `requirements.txt` | 1 | `flask` |
| `app.py` | 36 | Flask assembly, `ApiError` handler, blueprint registration, `0.0.0.0:$PORT` (default 10000) |
| `store.py` | 136 | In-memory dict store, logical clock (default 2026-09-01T00:00:00Z), envelope/error helpers, `touch()` (updated_at+version), ISO dt parser |
| `helpers.py` | 235 | Auth (X-User-ID/X-User-Role, 9 roles), role gating, non-raising accessors + tier-9 structural validators, pagination (limit/offset/total_count/has_more), date/period helpers |
| `domain.py` | 330 | Mode recommendation, burn/runout (Fraction-exact INSTANTANEOUS + WMA), delivery creation + stop-sequence ranking, terminate/failover/completion cascades, clock sweep, pinned 14-step settlement + per-year 4dp escalation (Decimal ROUND_HALF_UP) |
| `clock_route.py` | 21 | `POST /_clock/set_current_utc` (unprefixed) + sweep |
| `customers.py` / `evaluations.py` | 57/92 | Customer CRUD, evaluation create/accept/list with supersession |
| `contracts.py` | 210 | Create/get/list/activate/amend/terminate with OCC, mode floors, credit gate |
| `plants.py` / `pipeline.py` | 104/150 | Plant lifecycle; networks/connections with capacity aggregation |
| `tanks.py` / `deliveries.py` | 134/64 | Tanks + telemetry ingestion, delivery confirm with overfill gate |
| `quality.py` / `turnarounds.py` / `settlements.py` | 113/183/128 | Certificates with SoD, turnaround negotiation windows, settlement create/list |

**Route-table grep evidence**: 40 total `@bp.route` registrations; exactly one contains `_clock` — `@bp.route("/_clock/set_current_utc", ...)` in `clock_route.py` with no prefix; the other 39 all start `"/gas-supply/"` (count-2 entries are GET+POST pairs on shared paths).

**Compile/import smoke**: `python3 -m py_compile` on all 15 modules → OK; `cd implementation && python3 -c "import app"` → `IMPORT_OK`.

**Dynamic-port boot smoke** (two fresh boots on ports 53003 and 37801, each killed by its exact saved PID afterward; no broad kills):
- Boot 1 (47/47 checks): clock POST → 200; customer 201 with envelope `meta/response_type/data`; full chain evaluation → accept → contract → activate → plant×3 advances → OPERATING; FINAL settlement math verified cent-exact (volume 24,000,000; power 6,300; fee 500,000; capital 1,000,000; subtotal 25,506,300; grant 3,600,000; bank updated); duplicate-settlement 409; makeup-exceeded 422; period-out-of-term 422; stale-version 412; amendment 200; telemetry burn instant 500.0 / WMA 250.0 / runout `2026-09-02T16:00:00.000Z`; out-of-order 422; edge-triggered auto-delivery (qty 6100, seq 1, no duplicate); overfill 422; SoD 422; certify → COMPLETED/CERTIFIED; turnaround propose/agree/schedule/start with NOT_DUE 422, failover cascade (plant TURNAROUND, backup delivery), clock-driven completion, terminate cascade (plant DECOMMISSIONED, BACKUP cancelled).
- Boot 2 (18/18): fresh-boot empty state; default clock on `created_at`; WATCH → 422 at activation; PIPELINE activation gate 409; BACKUP/PIPELINE mode mismatch 422; exact-fit capacity 201, +0 available, release restores; renewal opens exactly at end−90d, renewal amendment returns ACTIVE with new end_date, expiry sweep → EXPIRED; garbage-body settlement on EXPIRED → `ERR_CONTRACT_NOT_ACTIVE` (tier-4-beats-tier-9 ordering).
- Boot 3 checks (11/11 after correcting my script's own arithmetic — server was right): per-year escalation `1.0609` at 24 months (fee 106,090), negative power pass-through −90, PROVISIONAL↔FINAL supersession and duplicate rules, `apply_makeup_cents` on PROVISIONAL → 400.

**PRD interpretations I pinned myself** (candidate over-guard list):
1. CustomerOps ownership is enforced only on its two write endpoints (accept, respond) and evaluated *after* path existence (the customer must be resolved from the resource); GETs are unrestricted per "read access is broad".
2. Body-referenced ids (customer_id/evaluation_id/contract_id/network_id) are existence-checked at the tier-3 position (customer before evaluation/contract, mirroring the left-to-right precedence); non-string/missing ids defer to tier-9 `ERR_VALIDATION`.
3. Connection create against a contract outside DRAFT|ACTIVE → `ERR_INVALID_STATE_TRANSITION` 409 (PRD names no error for this).
4. Tank `current_level_liters == null` (no readings) is treated as 0 for headroom (BACKUP/REDELIVERY quantity = full capacity; overfill bound = capacity).
5. Every mutation (including sweep transitions, cascade touches, supersessions, failover flips, and changed stop_sequences) bumps `version` and `updated_at` per the §2.5 blanket rule; versions start at 1.
6. `end_date` is treated as midnight UTC for the renewal-open (`now >= end−90d`) and expiry (`now > end`) sweeps.
7. Delivery auto-trigger fires on any posture *change* landing in REORDER_DUE/CRITICAL — including CRITICAL→REORDER_DUE — following the PRD prose over the scaffold table (which omits that transition's side effect).
8. Clock-driven turnaround completion restores the plant only if it is still in TURNAROUND (a contract-terminated DECOMMISSIONED plant stays decommissioned); `failover_active` clears regardless.
9. Extra structural guards added as `ERR_VALIDATION` beyond the PRD's explicit list: `term_months >= 1`, non-negative money/volume/demand/power/escalation fields, `nameplate >= 1`, `capacity_liters >= 1`, ISO-format enforcement on `start_date`/`period_month`/datetimes.
10. Stop-sequence ties beyond the spec's tie-breaks (equal created_at under the logical clock) fall back to a monotonic creation sequence.
11. Input datetimes (`measured_at`, `window_start`, `sampled_at`, blackout `start_iso`/`end_iso`, `last_reading_at`) are echoed verbatim; all server-generated timestamps use canonical 3-fractional-digit UTC `Z` form; burn rates are emitted as JSON numbers from exact rational computation.

No entities are seeded at startup; storage is in-memory dicts only. `test_suite/`, `test_helpers/`, and the design YAMLs were never read.

Orchestrator verification: 17 files present in implementation/, `py_compile *.py` → COMPILE_OK, `import app` → IMPORT_OK, `_clock` appears only in clock_route.py + store.py, business modules reference `gas-supply` prefixes.

## Step 7: Test-and-fix iteration loop — 2026-10-02T06:45:00.000Z

Clean sweep on the first iteration — all 8 parallel rounds passed with zero failures, zero errors, zero flakes. All 8 `results.*.json` files remain on disk as sweep evidence.

**Summary**

- **Iterations run:** 1
- **Tests deleted:** none
- **Fixes applied to `test_helpers/`:** none
- **Fixes applied to `test_suite/`:** none
- **Fixes applied to `implementation/`:** none
- **Final sweep evidence** (`workspace/implementation/results.{1..8}.json`):
  - round 1: 68/68
  - round 2: 68/68
  - round 3: 68/68
  - round 4: 68/68
  - round 5: 68/68
  - round 6: 68/68
  - round 7: 68/68
  - round 8: 68/68

The implementation from Step 6 passed the full 68-test suite (18 difficulty + 50 corner instances) under per-test-server isolation with 8 concurrent rounds and no flakiness signal anywhere. No diagnostic steps were needed.

Orchestrator verification: independently parsed all 8 results files — every round reports passed=68, failed=0, errors=0, total=68.

## Step 8: Finalize PRD — 2026-10-02T06:46:00.000Z

SKIPPED per the skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline. `PRD_FINALIZED.md` is not produced; Step 9 starts from `PRD.md`.

## Step 9: Complete PRD — 2026-10-02T07:10:00.000Z

The diff shows exactly the 22 intended edits and nothing else. The task is complete.

**File stats** (`diff -q`: files differ):
- `workspace/PRD.md`: 327 lines, 47,889 chars
- `workspace/PRD_COMPLETED.md`: 329 lines, 51,988 chars (+4,099 chars, +2 lines)

**Counts:** 20 ambiguity-pins, 2 mismatch-revisions, 1 rule-strip candidate.

### Changes (one bullet each)
1. §2.3 — insert — ambiguity — out-of-range/non-integer `limit`/`offset` → `ERR_VALIDATION`; `created_at` ties break by creation sequence — implementation/helpers.py:212-235, 208-209
2. §2.4 — insert — ambiguity — clock setter places the clock unconditionally, no monotonicity guard — implementation/clock_route.py:17-19, store.py:57-58
3. §2.4 bullet 1 — revise — ambiguity — `end_date` read as midnight UTC at start of that day for renewal-open — implementation/domain.py:236-237
4. §2.4 bullet 2 — revise — ambiguity — expiry compares against midnight UTC of `end_date`; both contract rules run in the same set so ACTIVE can pass through RENEWAL_OPEN to EXPIRED in one set — implementation/domain.py:233-245
5. §2.4 bullet 3 — revise — ambiguity — turnaround completion returns plant to OPERATING only if still parked in TURNAROUND — implementation/domain.py:213-227
6. §2.5 — revise/insert — ambiguity — `version` starts at 1, `updated_at` initially equals `created_at`; client-supplied timestamps echoed verbatim; naive datetimes read as UTC — implementation/store.py:102-111, 122-136; tanks.py:108-110
7. §2.6 — insert — ambiguity — burn rates exposed on the API as ordinary JSON numbers computed from exact rationals — implementation/domain.py:98-99
8. §2.7 — revise — **mismatch** — stale-version fires on *any* inequality, not only when the resource "has advanced past" the client's value — implementation/contracts.py:150-154, turnarounds.py:100-104
9. §2.8 tier 2 — revise — **mismatch + rule-strip candidate** — removed the CustomerOps ownership comparison from tier 2 (see adjudication below) — implementation/evaluations.py:74-82, turnarounds.py:92-97
10. §2.8 tier 3 — insert — ambiguity — body-carried identifiers resolve at tier 3 in narrative order (customer before evaluation for contracts; network before contract for connections); absent/non-string identifiers defer to tier 9; CustomerOps ownership runs immediately after resolution, before tier-4 guards — implementation/pipeline.py:57-71, contracts.py:26-37, evaluations.py:21-23
11. §2.8 tier 9 — insert — ambiguity — JSON-type errors, ISO-format enforcement, integer-only whole-unit fields (integral floats accepted), `term_months`/nameplates/`capacity_liters` ≥ 1, non-negativity domains with the four exceptions (`required_purity_percent`, `measured_purity_percent`, `power_index_actual`, `makeup_credit_cap_pct` accept any number), unknown fields ignored — implementation/helpers.py:65-149; contracts.py:45-53
12. §3.1 — insert — ambiguity — blackout windows validated only for ISO well-formedness, no start/end ordering enforced — implementation/customers.py:30-38
13. §3.2 — revise — ambiguity — `end_date` month addition clamps the day to the target month's last day — implementation/helpers.py:196-202, contracts.py:58-59
14. §3.4 — insert — ambiguity — connection against a contract outside DRAFT|ACTIVE named as `ERR_INVALID_STATE_TRANSITION` — implementation/pipeline.py:72-75
15. §3.5 — insert — ambiguity — telemetry append answers 201 with the updated *tank* (not the reading) in `data` — implementation/tanks.py:125
16. §3.5 — insert — ambiguity — burn-rate fields null until at least two readings exist — implementation/domain.py:77-83
17. §3.5 — insert — ambiguity — any posture change landing in REORDER_DUE/CRITICAL is an entry edge, including CRITICAL→REORDER_DUE recovery — implementation/tanks.py:121-124
18. §3.5 — revise — ambiguity — headroom counts a null level as 0 — implementation/domain.py:61-63
19. §3.6 — insert — ambiguity — stop-sequence ties beyond spec tie-breaks fall back to monotonic creation sequence; unchanged ranks are not mutated (no version bump) — implementation/domain.py:121-137
20. §3.6 — revise — ambiguity — confirmation headroom counts a null level as 0 — implementation/deliveries.py:50-57
21. §3.6 — insert — ambiguity — a certificate can be decided only once; re-deciding draws `ERR_INVALID_STATE_TRANSITION` — implementation/quality.py:75-77
22. §3.7 — revise — ambiguity — completion restores the plant only if still in TURNAROUND (a mid-window decommission survives); `failover_active` clears either way — implementation/domain.py:213-227

### Rule-strip candidate (subagent-flagged)
- **§2.8 tier 2** — lost clause: *"Authorization: the role is permitted for the endpoint, **and — for `CustomerOps` — the caller owns the customer in question (`ERR_UNAUTHORIZED_ROLE`)**."* The original places ownership at tier 2, where it would mask tier-3 existence (403 before 404). The implementation evaluates ownership only *after* the target resource resolves (accept: evaluations.py:74-79; respond: turnarounds.py:92-97), so a nonexistent resource draws its 404 first. The revision relocates the rule to tier 3 rather than deleting it outright.

### Cross-reference findings
- **Raised-but-uncatalogued errors: none.** The implementation raises exactly 37 distinct `error_id`s; all 37 appear in PRD §5's catalogue, and every catalogued error is raised somewhere in the code (verified by grep over all 15 modules).
- **Dead checks: none.** Every helper/check function is called at least once (all `v_*` validators, `forbid`, `as_int`/`as_decimal`, `add_months`, all of domain.py including `escalation_multiplier` and `live_plant_for_contract`, and the turnarounds.py privates `_check_window`/`_contract_of`). No called-but-undefined functions; the app imports cleanly via `app.py`'s blueprint registry.

### Known-interpretation checklist disposition
All 11 items from the generation-time list are now PRD-pinned: (1) edits 9/10 + pre-existing §2.1 read-access sentence; (2) edit 10; (3) edit 14; (4) edits 18/20; (5) edit 6 + pre-existing §2.9 cascade-mutation sentence; (6) edits 3/4; (7) edit 17; (8) edits 5/22; (9) edit 11; (10) edit 19; (11) edits 6/7.

Everything else traced clean: all 41 endpoints in §4 exist with matching roles and 200/201 conventions; the 14-step settlement computation (domain.py:271-330) matches §3.8 step-for-step including per-year escalation rounding, floor capital recovery, 60% grant rate, and pre-grant-balance application; the termination and failover cascades match §3.2/§3.7; the WMA weight scheme (1/2, 1/4, 1/8, 1/8, no redistribution) matches §3.5; overlap/blackout interval semantics in turnarounds.py:149-163 match §3.7's formulas exactly.

## Orchestrator adjudication of Step 9 flags — 2026-10-02T07:15:00.000Z

- **§2.8 tier-2 rule-strip candidate: EXONERATED (revision accepted).** Adjudicated against SCAFFOLD.yaml: scaffold priority-2 check reads "for CustomerOps, X-User-ID must equal the acting Customer's id (ownership)". Both CustomerOps write endpoints (`POST /supply-mode-evaluations/{evaluationId}/accept`, `POST /turnarounds/{turnaroundId}/respond`) carry only the resource id in the path — never the customer id — so "the acting Customer" is only knowable by loading the resource. For a nonexistent resource the tier-2 ownership check is unevaluable: this is ownership-load coupling, an exonerating condition. The revision relocates rather than deletes the rule (ownership still 403s, before tier-4, wherever defined) and resolves the undefined nonexistent-resource case toward 404, consistent with the passing PRD-faithful tests (`turnaround_not_found_on_respond` → 404; `customer_accepting_others_evaluation_forbidden` → 403 on an existent resource). No impl fix; no sweep re-run.
- **§2.7 OCC mismatch revision: EXONERATED (restores scaffold intent).** Scaffold pins `expected_contract_version == SupplyContract.version` (equality); PRD-original's "advanced past" was doc-generator drift narrowing the check directionally. The revision aligns PRD with scaffold + impl.
- **Artifact verification:** PRD_COMPLETED.md exists and differs from PRD.md (`diff -q`: differ; 329 vs 327 lines). No `implementation/*.py` file is newer than `results.8.json` — no post-sweep impl writes, the green sweep remains valid.
