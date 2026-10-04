# Worklog — task_3404_pasture_raised_family_farm_network_audits_traceability

## Step 1: Create Task Directory — 2026-10-01T19:01:00.000Z

Task directory pre-allocated by the caller: `tasks/task_3404_pasture_raised_family_farm_network_audits_traceability/` with empty `workspace/` inside. Verified it exists; no index computation performed (per instructions). Difficulty instruction for scaffold generation: "Generate task much harder than expert level!"

Orchestrator constraint noted: this model endpoint duplicates parallel tool calls — all subagent launches are strictly sequential (one Agent call per message, never concurrent). Steps 5 and 6 will run sequentially, so the Step 6 prompt carries an explicit read ban on test artifacts.

## Step 2: Generate Scaffold — 2026-10-01T19:39:00.000Z

Scaffold generation complete and fully verified.

## Summary

**Files written (all parse as valid YAML):**
- `/home/ubuntu/github/CodingPRD/tasks/task_3404_pasture_raised_family_farm_network_audits_traceability/SCAFFOLD.yaml` — §1.0–§1.7 only (80 KB)
- `/home/ubuntu/github/CodingPRD/tasks/task_3404_pasture_raised_family_farm_network_audits_traceability/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design` (73.5 KB)
- `/home/ubuntu/github/CodingPRD/tasks/task_3404_pasture_raised_family_farm_network_audits_traceability/SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design` (129.8 KB)

**Counts:** 12 entities, 41 endpoints, 37 error codes, 6 roles, 8 calculations, 9 state machines, 13 ordered validation tiers, 1 OCC concurrency rule. Difficulty design: **18 instances** (2 per each of the 9 rules). Corner design: **51 active instances + 7 excluded_because stubs**.

**Design highlights (per the "harder than expert" instruction, within one in-memory Flask server):**
- Archetype: compliance/audit + temporal windowing; segregation-of-duties role model (a CA verifier must differ from the completing auditor); flat topology with cross-aggregate FKs
- Two dual-variant calcs in different domains: farmer payment (provisional contract base vs finalized actual base: 12000 vs 12750 cents) and production forecast (optimistic P50 vs conservative P90 weather hedge: 908 vs 841 dozen)
- Combinatorial formulas in two modes: tiered 3-factor forecast lookup (mode a) and pinned per-grade-subline rounding order with an observable 1-cent delta vs sum-then-round (mode b, 7077 vs 7076)
- Non-linear machines: Farm (cyclic PROBATION loop × parallel certification dimension) and EggLot (hold fork → RELEASE vs REJECT)
- Two depth-3+ transitive cascades from different triggers (clock-driven CRITICAL-CA overdue → suspend → skip stops → route-load recompute; incident-resolve removal → contract terminate → commitment cancel)
- Priority conflicts (state>temporal, safety>fiscal), boundary checks on distinct metrics/endpoints, two temporal-overlap semantics (30-day audit gap buffer vs route-date equality), two conservation invariants (lot dozens, route case capacity), OCC on contract supersede, logical clock with fixed default 2026-09-01T00:00:00Z

**Verification:** `scaffold_lint.py` verdict block: "VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5." (726 calls scanned). Additionally machine-checked: 76 unique instance names across both files, zero unbound `${var}` placeholders, monotonic clock chains in every recipe, all formula-derived assert literals recomputed and confirmed, every grounds reference resolves, every error code is cited by a validation/transition, no forbidden concurrency vocabulary. Two YAML indentation hazards (unquoted `?` optionals, bracketed grounds) were caught by the per-append parse discipline and fixed. No sibling task directory was read.

**Orchestrator spot-check (independent re-verification):** all three files parse via `yaml.safe_load`; SCAFFOLD.yaml top keys = {api_prefix, calculations, complexity_profile, concurrency_rules, domain_name, endpoints, entities, errors, response_envelope, roles, scenario, state_machines, validations} with NO scaffold_difficulty_design / scaffold_corner_design leak; DIFFICULTY top key = scaffold_difficulty_design only; CORNER top key = scaffold_corner_design only; 41 endpoint entries and 12 entity entries confirmed; domain tokens farm/audit/egg/lot/carton/route/contract/incident/grad all present in SCAFFOLD.yaml. Endpoint count 41 is at the known impl-gen risk threshold — Step 6 prompt will carry the pre-constraints (per-domain modules, one small file per message, no truncation, self-smoke-test).

## Step 3: Copy Shared Files — 2026-10-01T20:21:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-01T20:41:00.000Z

PRD generation complete. Summary:

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3404_pasture_raised_family_farm_network_audits_traceability/workspace/PRD.md` — 282 lines, ends cleanly with the §5 error table (verified tail; no truncation).

**Section list:**
- §1 Introduction (2 paragraphs: brand promise + system scope, `/farm-network` mount, logical clock)
- §2 Global Specifications: 2.1 RBAC (6 roles with per-role identity translation), 2.2 API Response Structure (byte-identical to canonical source — verified), 2.3 Pagination, 2.4 Common Resource Properties & OCC (incl. the `common_fields: false` exception for Carton and ProductionForecast), 2.5 Logical Clock & Time-Driven Sweeps (boot `2026-09-01T00:00:00Z`, monotonic, 3-sweep order), 2.6 Nested Resource Retrieval, 2.7 Dual Farm State Dimensions (certification derivation, 365-day boundary), 2.8 Bird Capacity Arithmetic (108.0 / 1.2 / 5, floor-before-min), 2.9 Conservation of Cases and Dozens, 2.10 Precision & Rounding, 2.11 Validation Order and Error Precedence
- §3 Business Logic (8 subsections): 3.1 Recruiting/Contracting/Activation, 3.2 Audits & Certification Cycle, 3.3 Corrective Actions & Segregation of Duties, 3.4 Welfare Incidents & Removal Cascade, 3.5 Collection Routes & Egg Lot Birth, 3.6 Grading/Holds/Packing, 3.7 Retailers/Forecasts/Commitments, 3.8 Weekly Settlement & Farmer Payment
- §4 Endpoint Definitions (4-column table, 41 rows), §5 Error Code Catalogue (2-column table, 37 rows)

**Coverage self-audit (all mechanical checks run against the file):**
- Endpoints: 41/41 in §4 table; every one also narrated in §3 by state-pair/role-verb/capability framing
- State machines: 9/9 — every transition's from/to, guards, and side effects expressed (incl. the 6-step removal cascade in order, the probation-does-not-skip-stops rule, the FAILED-audit probation side effect, and the rework loop with unchanged `due_at`)
- Calculations: 8/8 — all constants with numeric values (lay rates 0.82/0.78/0.72/0.61, weather factors 1.00/0.95/0.88 vs 0.98/0.88/0.75, 30 dozen/case, 1 dozen/carton, grade thresholds 95.0/85.0/70.0 inclusive, quality multipliers 1.10/1.00/0.85, CA due days 90/30/7, audit window −3/+7 days, 30-day audit gap, 365-day cert validity strictly-greater lapse, 0.9 commit ratio floor, 0.85 fill threshold floor, 4-decimal round-half-up fill rate, per-grade-subline rounding order pinned)
- Error codes: 37/37 named in §2/§3 prose with trigger conditions, and in the §5 table
- Contract 1 (field coverage): 98/98 required names in backticks, 0 missing (two passes; second pass caught `lines` and the `laid_start_date` error-id attachment, both repaired)
- Contract 2 (rule coverage): validation priority ordering stated explicitly in §2.11; the single OCC rule fully expressed (endpoint, `expected_farm_version`, stale-view framing, `ERR_STALE_VERSION` 412, no other endpoint takes a version field); cross-entity cascades enumerated; sibling branches (3 audit outcomes, 4 dispositions, 3 severities) given equal density
- Contract 3 (§3 path purity): 546 backtick tokens scanned — 0 paths, 0 bare HTTP methods, 0 method+path combos

The two withheld design-index files were never opened or referenced.

**Orchestrator spot-check (independent re-verification):** 282 lines confirmed; all §1–§5 headings present with expected subsections; constant greps hit for 0.82, 0.61, 95.0, 108.0, 2026-09-01, ERR_STALE_VERSION (×4), expected_farm_version (×2), 412 (×3), 30 dozen (×2), 0.9, 0.85 (×2), 365 (×2), 90 days; "round half up" phrasing present at §2.10/§3.8 (my first grep used the wrong hyphenated literal); §4 table = 43 rows = header + separator + 41 endpoint rows, matching the scaffold count.

## Step 5: Generate Unit Tests — 2026-10-01T21:05:00.000Z

Generation complete. Final report:

## File inventory (4113 lines total)

**test_helpers/ (Stage 1, frozen before any test file existed):**
- `types.py` (340) — 12 entity TypedDicts, 17 enums; Carton/ProductionForecast correctly omit `updated_at`/`version`
- `api_client.py` (146) — `ApiClient(GenericApiClient)`, 41 endpoint methods covering the full §4 table
- `api_errors.py` (88) — all 38 PRD §5 error IDs + HTTP map, registered via `set_error_http_status_map`
- `assertions.py` (204) — per-entity asserts + `assert_lot_conservation` / `assert_route_conservation` (PRD §2.9 invariants)
- `factories.py` (174), `test_users.py` (47, incl. `make_retailer_buyer_headers` for the entity-backed role), `fixtures.py` (344 — base chain farm→audit→PASSED→contract(OCC)→activate, plus route/lot/commitment/settlement composites), `constants.py` (17), `__init__.py` (38)

**test_suite/ (Stage 2):** `conftest.py` (40) + 10 test files (128–382 lines each) = **87 test functions**: 36 difficulty tests (18 instances × 2) + 51 corner tests (51 non-stub instances × 1). Creation endpoints assert explicit 201; mutations 200.

## Audit results
- **Tag audit (AST + yaml.safe_load):** 87 tests; 0 orphan tags; 0 untagged; 0 dual/misplaced tags; 0 non-stub instances missing a test; 0 difficulty instances with <2 tests. All 7 `excluded_because:` stubs correctly untranslated, and every stub's `difficulty_instance` cross-reference resolves.
- **Citation audit:** 132 `PRD §x.y` quotes across docstrings — 100% verbatim against PRD.md after whitespace normalization (one ellipsis-fused quote was caught and split into two verbatim sentences).
- **Constants vs PRD:** all values grep-verified against PRD prose (108.0/1.2/5/30/95.0/85.0/70.0/lay rates/weather factors/0.9/0.85/365d/30d/3d/7d/90-30-7d); post-freeze, the 27 constants no test referenced were deleted and the 4 live ones (`GRADE_AA_MIN`, `GRADE_B_MIN`, `DOZENS_PER_CASE`, `MIN_FILL_RATE`) were wired into tests. No drift.
- **pytest --collect-only:** 87 tests collected, 0 errors. No skip/xfail markers anywhere.
- IEEE-754 pre-check: every design-recipe float chain (barn÷1.2 floors, forecast products, round-half-up sublines) lands exactly on the design's precomputed literals.

## PRD-filter adjudications (no instance skipped)
- `not_found_sweep_child_resources`: commitment payload has *both* body refs bogus and PRD §2.6 doesn't pin body-ref order — that one sub-check uses `validate_error_is_one_of([ERR_RETAILER_NOT_FOUND, ERR_FARM_NOT_FOUND])`; the other four sub-checks assert exact IDs.
- `route_complete_with_open_stop_returns_422`: instance name says 422 but its own assert and PRD §3.5/§5 say 409 — test asserts 409 per PRD.
- Timestamp asserts (`last_passed_audit_at`, `packed_at`) compare the second-precision prefix — PRD pins the instant, not fractional-second serialization.
- Priority-pair instances (state-beats-window, cert-beats-cap) are emitted as asserted tests because PRD §2.11 explicitly fixes the evaluation sequence — they are not silence-pattern skips here.

**Orchestrator independent re-verification:** `pytest --collect-only -q` → 87 tests collected, 0 errors; skip/xfail grep across test_suite/ + test_helpers/ → 0 hits; my own AST+yaml tag audit (both design YAMLs parsed directly; corner list = 11 sections with `section`+`instances` keys, difficulty list = 9 rules with `rule_id`+`instances`) → 87 tests, 69 unique tags, 69 expected non-stub instances, 7 stubs; **0 orphan tags, 0 missing tests, 0 stub-tagged**; the 18 repeated tags are exactly the 18 difficulty instances × 2 tests each (by design, not dual-tagging). (First audit attempt false-alarmed because my path reconstruction included the literal `instances` key — same false-positive class as route-diff normalization; corrected before adjudicating.)

## Step 6: Generate Implementation — 2026-10-01T21:44:00.000Z

Both test servers are stopped (only my own saved PIDs were killed). The implementation is complete and verified.

## Summary

### Module inventory — `workspace/implementation/` (2414 lines total)
- `app.py` (60) — Flask wiring, blueprint registration, envelope error handlers, `0.0.0.0:$PORT` (default 10000)
- `start.sh` (10, executable) — guarded `pip install` (no-op when flask present), `exec python3 app.py` foreground
- `constants.py` (96) — single definition site for all 38 named constants (capacity mins, lay rates, weather factors, grade thresholds, quality multipliers, CA due days, audit gap/window, fill rate, cert validity, dozens conversions, pagination bounds, role/enum sets)
- `errors.py` (16) — `ApiError` carrier
- `clock.py` (65) — logical clock (boots `2026-09-01T00:00:00Z`, monotonic), strict date/datetime parsing, millisecond-Z formatting
- `store.py` (29) — 12 empty in-memory dicts + lot-code/insertion sequences; zero seeding
- `responses.py` (47) — object/array/list/error envelopes per PRD §2.2, pagination fields inside `meta`
- `validation.py` (136) — priority-6 field validators (str/int/num/enum/date/datetime) and pagination parsing
- `auth.py` (26) — `X-User-ID`/`X-User-Role` authentication + role authorization
- `domain.py` (334) — capacity (Decimal, floors 2.4/1.2→2 correctly), certification derivation, covering-contract lookup, forecast variants, commitment cap, route-load reconciliation, stop-skip/suspension/removal cascades, clock sweeps, payment sublines (round-half-up per grade), fill evaluation, sorted paging
- `serialize.py` (220) — 12 entity serializers; cartons/forecasts carry only `id`+`created_at` (PRD 2.4)
- Per-domain route modules: `routes_farms.py` (167), `routes_contracts.py` (80, OCC+supersede), `routes_audits.py` (175), `routes_cas.py` (81, SoD), `routes_incidents.py` (102), `routes_routes.py` (204), `routes_lots.py` (162), `routes_retailers.py` (38), `routes_commitments.py` (127), `routes_forecasts.py` (65), `routes_settlements.py` (141), `routes_clock.py` (32)

### Verification evidence
- `py_compile` clean on all 19 files; `import app` loads the full cross-module graph (42 URL rules = 41 endpoints + Flask static)
- Constant trace: all 36 `C.X` references resolve to exactly one definition in `constants.py` (CLOCK_BOOT_ISO imported directly by clock.py); zero defined-but-unused
- Error trace: all 37 catalogue `ERR_*` ids have a raise site; every raise site uses a catalogue id (fallback handlers for undeclared paths use ERR_NOT_FOUND/ERR_METHOD_NOT_ALLOWED/ERR_INTERNAL and are unreachable from declared routes)
- Boot smoke test on dynamic ports 33147, then a fresh reboot: store verifiably empty after restart (old ids 404), clock back at boot instant, monotonic rejection works
- Curl chain (all passed): 401 unauthenticated; 403 wrong-role; farm 201 with correct envelope (`meta.api_request_id`/`api_request_timestamp` 3-digit Z, `response_type`, `data`); capacity min(100,100,500)=100; activate→422 `ERR_CERTIFICATION_REQUIRED`; audit gap→422 `ERR_AUDIT_TOO_SOON`; audit PASSED stamps `auditor_user_id`/`completed_at` and flips cert to CERTIFIED; contract OCC 412 `ERR_STALE_VERSION` then 201 at correct version; forecast AUTUMN/NONE = 42/41 dozen (hand-verified); commitment 40→422 `ERR_COMMITMENT_EXCEEDS_FORECAST`, 36 at cap→201; route stop→collect minted `LOT-000001` with 60 dozen; grade 96→AA; 60 cartons `LOT-000001-C001..C060` then lot PACKED; RetailerBuyer carton traceability 200; settlement provisional 23100¢ (60×350×1.10), finalize with actual 250 → 26400¢; commitment FILLED, fill_rate 1.6667; buyer scoping 403 without own retailer_id; CRITICAL CA overdue sweep → farm SUSPENDED + stop SKIPPED + load restored (committed 0/available 10); SOD verify 403, second auditor VERIFY_CLOSED, reinstate ACTIVE; audit EXPIRED sweep; CERT_LAPSED at >365d while farm stays ACTIVE; lapsed cert blocks stop-add with 422 `ERR_CERTIFICATION_NOT_CURRENT`; removal cascade → DECERTIFIED + contract TERMINATED; mutation on REMOVED → 409 `ERR_FARM_TERMINAL`

### Interpretation choices (PRD admitted more than one reading)
1. `version` starts at **1** on creation (§2.4 "starts on creation and increments")
2. Farm `certification_status` **derived on read** (pure function of status/last_passed_audit_at/now, §2.7); the lapse sweep writes nothing and does not bump farm.version (§2.4 ties version to mutations)
3. Existence of body references resolves **before** body well-formedness (§2.11 priorities 5→6); absent reference fields are 400 (unresolvable); commitment references resolve retailer_id then farm_id (validations-table order)
4. `ERR_FARM_TERMINAL` applies to mutations under `/farms/{id}/*`; for stop-add/forecast/commitment the scaffold's explicit mapping gives **`ERR_FARM_NOT_ACTIVE`** for a REMOVED (non-ACTIVE) farm
5. FAILED audits record `non_conformities_count = len(findings)` (entity field description; scaffold pins it only for CORRECTIVE_ACTION_REQUIRED)
6. `collected_cases` accepts 0 (no PRD minimum; planned_cases is the >0 one); `carton_count` requires ≥1
7. Settlement lines **skip** a farm whose packed cartons have no covering contract for the week (line requires the latest covering contract; none exists → no payable line)
8. Cascade mutations bump the mutated resource's `version` once per reconciling event, including one route-version bump per stop-skip cascade event (§2.4)
9. Incident-driven REMOVAL sets `removal_reason` from `resolution_notes`, else `"WELFARE_INCIDENT_REMOVAL"`; direct `/remove` requires a non-empty `reason`
10. CA verify order: 404 → SOD 403 → body 400 → state 409 (SOD cannot be evaluated without the CA + parent audit)
11. `scheduled_for` and date fields echo raw input strings; all server-written timestamps come from the logical clock in `...SS.mmmZ` form
12. A zero-stop route may complete (vacuous all-terminal); out-of-range/non-integer `limit`/`offset` → 400 `ERR_INVALID_REQUEST` (§2.3 "rejected")
13. Default port **10000** per INSTRUCTION.md (the harness always sets `$PORT`; start.sh foregrounds via `exec`)

Isolation rule honored: never opened SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, test_suite/, or test_helpers/, and never ran the test suite. No broad kill patterns used — only the two PIDs started were killed.

**Orchestrator spot-check:** 19 .py files + start.sh + requirements.txt present; start.sh is executable, `set -euo pipefail`, guarded pip install, `exec python3 app.py` foreground; `python3 -m py_compile *.py` clean; 2403 total .py lines.

## Step 7: Run Tests and Iterate — 2026-10-01T22:01:00.000Z

All 8 rounds pass cleanly: 87/87 in every round, 0 failures, 0 errors. No fixes needed.

Summary:
- Iterations run: 1 (clean 8-round parallel sweep on first iteration).
- Tests deleted: none.
- Fixes applied to `test_helpers/`: none.
- Fixes applied to `implementation/`: none.

The implementation passed all 87 tests across all 8 concurrent rounds under `--isolation per-test-server`, with results files `results.1.json` through `results.8.json` retained in `workspace/implementation/` per the output contract. No flakiness surfaced.

**Orchestrator independent re-verification:** read all 8 `results.{1..8}.json` directly — every file: total=87, passed=87, failed=0, errors=0, zero non-passed entries; mtimes 22:01 (fresh, this iteration). ALL_CLEAN.

## Step 8: Finalize PRD — SKIPPED — 2026-10-01T22:02:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the implementation exhibits; no `PRD_FINALIZED.md` produced. Step 9 will read `PRD.md` directly.

## Step 9: Complete PRD — 2026-10-01T22:23:00.000Z

All verification passes complete. Final state confirmed.

## Summary

**Source vs output**: `PRD.md` 282 lines / 53,998 bytes → `PRD_COMPLETED.md` 284 lines / 59,731 bytes (+2 lines, +5,733 chars). 24 single-line diff hunks, all in-paragraph inserts/revisions; no new sections.

**Counts**: 20 ambiguity-pins (across 24 hunks), 0 mismatch-revisions, 0 `implementation/` fixes (no PRD sentence was found violated — every check traced to code that honors it).

**PRD changes** (section — insert/revise — ambiguity — what changed — impl ref):
- §2.2 — revise — ambiguity — `api_request_id` pinned as `req_` + 24 lowercase hex chars — responses.py:17
- §2.3 — revise — ambiguity — `limit`/`offset` must be integers (negative `offset` → `ERR_INVALID_REQUEST` 400); `created_at` ties break by creation sequence; `has_more` = `offset + len(items) < total_count` — validation.py:114-136, domain.py:331-334, responses.py:38
- §2.4 — revise — ambiguity — `version` starts at 1 on creation (interp #1) — routes_farms.py:52 and all creators
- §2.4 — insert — ambiguity — client date fields stored/echoed verbatim (exact `YYYY-MM-DD`), `scheduled_for` echoed raw; only server timestamps get 3-fractional-digit UTC (interp #11) — serialize.py:42-43,56, validation.py:88-111
- §2.5 — insert — ambiguity — lapse sweep is a pure re-derivation: writes nothing, bumps no `version`/`updated_at` (interp #2) — domain.py:323-324, serialize.py:26
- §2.6 — revise — ambiguity — body refs resolve before remaining well-formedness; commitment resolves `retailer_id` then `farm_id` (interp #3); stop payload's `farm_id` likewise — routes_commitments.py:27-38, routes_routes.py:68-71
- §2.11 — insert — ambiguity — SOD/scoping run immediately after the guarded record resolves; nonexistent CA/commitment 404s first (interp #10) — routes_cas.py:60-66, routes_commitments.py:123-126
- §3.1 — revise — ambiguity — amendments re-apply registration field constraints; a well-formed no-change PATCH still bumps `version`/`updated_at` — routes_farms.py:74-99
- §3.1 — insert — ambiguity — `ERR_FARM_TERMINAL` blanket scoped to farm-addressed operations; stop-add/forecast/commitment answer a REMOVED farm with `ERR_FARM_NOT_ACTIVE` (interp #4) — routes_routes.py:78-79, routes_forecasts.py:30-31, routes_commitments.py:43-44
- §3.2 — insert — ambiguity — audit scheduling allowed in any non-REMOVED farm state (only REMOVED → `ERR_FARM_TERMINAL`) — routes_audits.py:35-36
- §3.2 — revise — ambiguity — findings entries: severity ∈ {MINOR,MAJOR,CRITICAL}, non-empty description; FAILED also records `non_conformities_count = len(findings)` (interp #5) — routes_audits.py:91-106, 168
- §3.3 — revise — ambiguity — REJECT retains `evidence_notes`, leaves `verified_by_user_id`/`closed_at` null — routes_cas.py:77-78
- §3.4 — insert — ambiguity — incidents reportable in any non-REMOVED state; REMOVAL disposition on an already-REMOVED farm resolves without a second cascade — routes_incidents.py:33-34, 98-100
- §3.4 — revise — ambiguity — direct `/remove` requires non-empty `reason` (else 400); incident-driven removal sets `removal_reason` from `resolution_notes` else literal `WELFARE_INCIDENT_REMOVAL` (interp #9) — routes_farms.py:163, routes_incidents.py:99
- §3.5 — revise — ambiguity — non-empty `driver_name`; stop shape pinned (5 fields, `collected_cases` null until collected); add answers 201 with the route; `collected_cases` may be 0 (interp #6); collect answers 201 with the minted lot; skip `reason` not persisted; zero-stop route may complete (interp #12) — routes_routes.py:33, 102-112, 122, 168, 178-187, 197-200
- §3.6 — revise — ambiguity — `quality_score` range-only enforcement (>2 decimals accepted, compared exactly); `carton_count` ≥ 1 (interp #6); pack answers 201 with array of created cartons; lot-list filters are `farm_id`/`route_id`/`status` — routes_lots.py:60, 109, 143, 33-35
- §3.7 — revise — ambiguity — retailer `name`/`banner` must be non-empty strings — routes_retailers.py:23-24
- §3.8 — revise — ambiguity — farms with packed cartons but no covering contract contribute no line (interp #7); lines ordered by `farm_id` ascending; equal-`start_date` tie resolves to most recently created contract — routes_settlements.py:60-63, domain.py:146
- §4 — insert — ambiguity — activation, reinstatement, route completion take no payload and ignore any body — routes_farms.py:103-154, routes_routes.py:190-204

**Implementation fixes**: none — py_compile not needed (no file touched; newest impl source mtime 22:01 predates this session).

**Over-implementation findings** (no PRD basis; flagged, not legitimized):
- app.py:44-52 — Flask fallback handlers emit `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405), `ERR_INTERNAL` (500), none of which are in the §5 catalogue (trivial mechanical necessity).
- Optional list filters beyond PRD text: `contracts?status`, `audits?status&audit_type`, `incidents?status&severity`, `corrective-actions?status&severity`, `forecasts?week_start` (routes_contracts.py:75-78, routes_audits.py:73-79, routes_incidents.py:64-69, routes_cas.py:28-34, routes_forecasts.py:60-63).
- Default port 10000 (app.py:60) is pinned by INSTRUCTION.md, not the PRD — no PRD prose added.

**Scan evidence** (all modules walked): app.py (wiring + fallback handlers — flagged), auth.py (6 roles, 401/403 — matches §2.1), clock.py (boot 2026-09-01T00:00:00Z, strict `YYYY-MM-DD`, Z/offset parsing, `iso_ms` — matches §2.5), constants.py (all rates/thresholds/days/enum sets verified verbatim against §2.3/2.5/2.7/2.8/3.2/3.3/3.6/3.7/3.8 — all match), domain.py (capacity floor-min via Decimal, cert derivation order, covering-contract latest-start rule, forecast variants floor-after-product, cap floor(0.9×conservative), route conservation, suspension/removal cascades, half-up subline-then-sum, fill threshold/rate, sweep order 1-2 with 3 as pure derivation — all match), validation.py (MISSING sentinel, type/bool/NaN guards, pagination — matches §2.11 tier 6 + §2.3), responses.py/serialize.py (envelopes, field shapes, raw echo — pinned where open), store.py (lot-code sequence, insertion tiebreak — pinned), routes_farms/contracts/audits/cas/incidents/routes/lots/retailers/commitments/forecasts/settlements/clock.py (every endpoint's roles vs §4 table, check order vs §2.11 priorities, state gates, side effects, version bumps, status codes 201-vs-200 — all verified individually; 13/13 implementer interpretation choices confirmed in code and pinned where the PRD was open; #8 was already PRD-pinned in §2.4; #13 belongs to INSTRUCTION.md).

**Orchestrator independent re-verification:** PRD_COMPLETED.md exists (59,731 bytes) and `diff -q` confirms it differs from PRD.md (no mid-flight no-op); spot-checked pins present verbatim (`version` starts at 1 at line 74; `has_more` formula at lines 33/44); line counts 282 → 284 match the claim. Implementation sweep validity: `find implementation -name '*.py' -newer results.1.json` (excluding __pycache__) → no matches; newest impl source is app.py at 21:49, predating the 22:01 sweep — the 87/87 × 8 sweep remains authoritative, no re-run needed.
