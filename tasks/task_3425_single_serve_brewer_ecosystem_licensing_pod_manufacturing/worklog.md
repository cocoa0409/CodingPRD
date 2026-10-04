# Worklog — task_3425_single_serve_brewer_ecosystem_licensing_pod_manufacturing

## Step 1: Create task directory — 2026-10-01T23:27:00.000Z

Pre-allocated task directory `./tasks/task_3425_single_serve_brewer_ecosystem_licensing_pod_manufacturing/` with `workspace/` inside verified to exist. No new index computed, no other task directory created.

## Step 2: Generate scaffold — 2026-10-02T00:55:00.000Z

All three artifacts are written, parse as valid YAML, and pass the full audit suite. (`worklog.md` and `workspace/` predate my run — left untouched.)

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3425_single_serve_brewer_ecosystem_licensing_pod_manufacturing/`):
- `SCAFFOLD.yaml` — §1.0–§1.7, no design keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single `scaffold_difficulty_design` key
- `SCAFFOLD_CORNER_DESIGN.yaml` — single `scaffold_corner_design` key

**SCAFFOLD.yaml counts:** 15 entities, 7 state machines, 2 OCC concurrency rules, 8 calculations, 12 validation priorities, 41 endpoints, 28 error codes, 9 roles.

**§1.8:** 23 instances — every §0.5 rule ≥2: dual_variant_calc 2 (royalty provisional-vs-final 930000 vs 772800 cents; household forward 120.00 vs trailing 185.00), combinatorial_formula 3 covering modes (a) tiered+multiplier stacking →470250, (b) per-slot-round-then-sum 70001 vs 70002, (c) subsidy snapshot evaluation order 0 vs 30 cents, non_linear_state_machine 3 (license suspend/reinstate cycle, brewer warranty×operational independent dimensions, statement dispute/reissue cycle), transitive_cascade 3 (audit-FAIL depth-4, terminate depth-3, replacement depth-3), priority_pair 2 (state-beats-fiscal, temporal-beats-constraint), boundary 3 (1,000,000th-unit tier edge →750000 then 1 cent, descale ==200 boundary, empty slots), cross_entity 3 (Run→Variety, Statement→Agreement, Audit→Agreement), temporal_overlap 2 (half-open+changeover-buffer lines vs closed day-interval territories), compensating_invariant 2 (capacity reserve/cancel, installed-base register/replace).

**§1.9:** 66 active instances + 3 `excluded_because` stubs across 8 sections (entities 12, state_machines 11, calculations 6, validations 24, errors 1, rbac 5, layers 6, consistency 1).

**Hardness levers beyond expert baseline:** lazy clock-driven evaluations (license expiry, warranty expiry, 60-day dormancy) with exact-equality boundaries; a fixed logical clock defaulting to 2026-09-01T00:00:00Z; marginal royalty brackets on cumulative annual units with three pinned-order multipliers; changeover-buffered half-open line windows vs closed territory intervals; amendment-chain territory exemption with SUPERSEDED source; cascade-conditioned cancellation (IN_PROGRESS runs spared); auto-denied warranty claims when descale-overdue; firmware compatibility blocking unlicensed-brand pods.

**Verification:** `scaffold_lint.py` verdict clean on first run (562 calls checked: endpoints/roles/payloads/captures/OCC dynamism/FK reverse-reachability); all 28 errors reachable by an active recipe; zero unbound `${var}` placeholders; 92 unique instance names across both design files; no forbidden concurrency vocabulary; every `grounds:` reference resolves.

Orchestrator spot-check: all three files exist and parse as valid YAML; top-level keys verified (`scaffold_difficulty_design` / `scaffold_corner_design` present only in their own files, absent from SCAFFOLD.yaml); `domain_name: single-serve-brewer-ecosystem`, 253 pod|brewer|licens matches — domain matches the scenario.

## Step 3: Copy shared files — 2026-10-02T00:57:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T01:15:00.000Z

All audits pass. The PRD is complete and shipped.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3425_single_serve_brewer_ecosystem_licensing_pod_manufacturing/workspace/PRD.md` — 306 lines.

**Section list:**
- §1 Introduction (2 paragraphs, razor-and-blades economics angle)
- §2 Global Specifications: 2.1 RBAC (9 roles, BrandManager entity-backed vs. 8 opaque), 2.2 API Response Structure (**byte-identical verbatim block**, verified programmatically), 2.3 Pagination, 2.4 Logical Clock & Lazy State Evaluation (startup default `2026-09-01T00:00:00Z`), 2.5 Common Resource Properties (incl. explicit `updated_at`/`version` absence for QualityAudit and ConsumptionRecord), 2.6 Money/Units/Rounding, 2.7 OCC, 2.8 Nested Retrieval, 2.9 Cascading State, 2.10 Validation Priority Ordering (all 12 priority classes as explicit ordered prose)
- §3 Business Logic (8 subsections): licensing/territory map, quality audits & suspension cascade, pod catalog & recyclable transition, manufacturing & production runs, installed base & consumption, warranty/descaling/service desk, retail assortment, royalty statements
- §4 Endpoint Definitions (41 rows, 4 columns, all with correct shape)
- §5 Error Code Catalogue (28 rows, 2 columns)

**Coverage audit (Contract 1 — Field-Name Coverage): PASS.** Programmatic diff of scaffold vs. PRD backtick tokens: 79 entity fields, 64 endpoint input/query/path identifiers, 5 structured-payload sub-fields (`up_to_units`, `millicents_per_pod`, `facings`, `clearance_flag`, `current_utc`) — 93 required, 93 present, 0 missing. All 28 error IDs and all 9 role names present; all enum/state values present as exact strings.

**Contract 2 — Rule Coverage: PASS.** Validation priority ordering stated explicitly (12 classes, ordering language); both OCC rules expressed with endpoint + `expected_*_version` field + `ERR_STALE_VERSION`/412 and no race framing; all state-machine transitions expressed with sibling asymmetries preserved (e.g. terminate-from-`ACTIVE` delists {ACTIVE, SUPPLY_BLOCKED, PHASE_OUT} vs. terminate-from-`SUSPENDED` delists {SUPPLY_BLOCKED, PHASE_OUT}); all 8 calculations rendered as precise prose with constants embedded (15¢/brewer subsidy derivation, 20,000¢ cap, 50,000-unit slow-mover floor, 90-day windows, 60-day dormancy, 200/500 ppm defect thresholds, 8/10/5% multipliers in pinned order, 3/2/1 trailing weights); all endpoint side effects and `applies_to` scopes covered (two gaps found and repaired mid-audit: amend-time window/territory validation, household computed-field recompute-on-read).

**Contract 3 — §3 Path Purity: PASS.** 539 backtick tokens scanned in §3; zero tokens starting with `/`, zero bare HTTP methods, zero method+path combos. No fuzzy/approximating words and no pseudocode operators anywhere in prose (the only "Around" hit is a sentence starter, not numeric approximation).

## Step 5: Generate unit tests — 2026-10-02T02:05:00.000Z

All verification passes are green. Generation is complete.

**Files written (22 total, 4352 lines)**

`test_helpers/` (1276 lines): `types.py` (364), `fixtures.py` (237), `assertions.py` (193), `factories.py` (177), `api_client.py` (168 — one method per PRD §4 endpoint), `api_errors.py` (71 — all 28 error IDs with §5 HTTP map registered via `set_error_http_status_map`), `test_users.py` (27 — 8 opaque roles + mandatory `make_brand_manager_headers(brand_id)` for the entity-backed BrandManager), `constants.py` (9 — only `DEFAULT_CLOCK_ISO`; all other thresholds are asserted as PRD literals at call sites), `__init__.py` (30).

`test_suite/` (3076 lines): `conftest.py` (61) + 12 test files: `test_01_api_envelope_and_listings` (152), `test_02_catalog_and_variety_lifecycle` (218), `test_03_rbac_and_auth` (125), `test_04_license_agreements` (365), `test_05_quality_audits_and_license_cascades` (205), `test_06_production_windows_and_runs` (354), `test_07_line_compatibility_and_variety_gates` (183), `test_08_households_and_consumption` (198), `test_09_brewers_telemetry_and_clocks` (255), `test_10_service_events` (172), `test_11_retail_assortment` (389), `test_12_royalty_statements` (399).

**Coverage**
- Queue A (Difficulty): **23/23 instances, 46 tests** (exactly 2 each), 0 skipped.
- Queue B (Corner): **66/66 non-stub instances, 66 tests**, 0 skipped. The 3 `excluded_because` stubs were not translated; their `difficulty_instance` cross-references were verified to resolve (`subsidy_snapshot_evaluation_order`, `audit_fail_depth4_cascade`, `temporal_beats_overlap_on_run_create`).
- Total: **112 tests**.

**Adjudications worth noting**
- `territory_closed_day_intervals`: asserted `ERR_TERRITORY_WINDOW_CONFLICT` at agreement *creation* — PRD §3.1 states the collision check in the creation paragraph ("must not collide... The same overlap check runs again at activation"); the recipe's activate-only capture would have produced a 404 instead.
- Clock-default assertions use a `"2026-09-01T00:00:00"` prefix match, since PRD §2.5's three-fractional-digit format leaves exact serialization open (two-reader defense).
- The subsidy instance's "no retroactive recomputation" sub-assertion was dropped as non-observable (BrewerModel has no GET endpoint); snapshot-vs-live semantics are still fully discriminated by model A (base 0 → subsidy 0) vs model B (base 2 → subsidy 30).
- Priority-pair instances were kept because PRD §2.10 verbatim states the deterministic priority order ("An earlier failure in this ordering masks every later one").

**Verification results**
1. `python3 -m py_compile`: all 22 files pass.
2. `pytest --collect-only` (with conftest, `PYTHONPATH=.`): **112 tests collected**, zero import errors.
3. AST tag-diff vs both design indices: **missing=none, extra=none**; every test carries exactly one `Design:` tag resolving to a real instance; every difficulty instance has ≥2 tests.
4. Additional sweeps: verbatim citation audit (every ≥8-word quoted span must literally grep in PRD.md after whitespace normalization) — 0 failures; dead-constant audit — clean; `validate_success(..., 201)` AST audit on all create call sites — clean; no `skip`/`skipif`/`xfail` markers anywhere.

Orchestrator spot-check: independent `pytest --collect-only -q test_suite` reports **112 tests collected** — matches the subagent's claim.

## Step 6: Generate implementation — 2026-10-02T03:05:00.000Z

All 41 routes are implemented and the smoke test passes. Here is the complete report.

### Implementation complete — task_3425 (single-serve brewer ecosystem)

**Files written (all under `workspace/implementation/`):**

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | Foreground launcher, guarded `pip install`, `exec python3 app.py`, `$PORT` (default 10000), `0.0.0.0` |
| `requirements.txt` | 1 | flask |
| `store.py` | 43 | In-memory dict store (15 collections), logical clock defaulting to 2026-09-01T00:00:00Z, insertion sequence |
| `helpers.py` | 250 | ApiError, success/error envelope (`meta`/`response_type`/`data`), auth decorator (`X-User-ID`/`X-User-Role`, 9 roles), field/datetime/period validators, pagination (`limit`/`offset`/`total_count`/`has_more`), `touch`/`init_common` |
| `calc.py` | 232 | Marginal bracket walk (2dp slice rounding), final royalty (pinned exclusivity→quality→unlicensed multipliers), velocity/slow-mover, subsidy snapshot (15¢/brewer, cap 20000), household forward/trailing models, month arithmetic, lazy expiry/dormancy/warranty |
| `serializers.py` | 177 | Per-entity public representations (audits/consumption omit `updated_at`/`version`) |
| `routes_clock.py` / `routes_brands.py` | 16 / 23 | clock set; brand create |
| `routes_licensing.py` | 291 | agreements CRUD/transition/amend, territory closed-interval check with amendment-chain exemption, suspend/reinstate/terminate cascades |
| `routes_audits.py` | 60 | audit create (PASS/FAIL compute, FAIL→suspension cascade) + list (audited_at DESC, created_at DESC) |
| `routes_varieties.py` | 115 | variety CRUD/transition incl. CONVERT_RECYCLABLE same-state conversion |
| `routes_models.py` | 36 | brewer model registration with creation-time subsidy snapshot |
| `routes_facilities.py` | 61 | facilities + filling lines, computed total capacity |
| `routes_runs.py` | 156 | run reservation (overlap/changeover/capability/capacity battery) + lifecycle |
| `routes_households.py` | 64 | households + immutable consumption records |
| `routes_brewers.py` | 100 | brewer registration, lazy dormancy/warranty, record-brews (firmware block, reactivation) |
| `routes_service.py` | 84 | service events (auto-DENIED on descale-overdue claims) + resolve cascades |
| `routes_retail.py` | 166 | accounts + plans (OCC, LOCKED supersede ban, per-slot productivity rounding, slow-mover clearance gate) |
| `routes_statements.py` | 124 | royalty statements (provisional at create, final at ISSUED, dispute loop with corrected inputs) |
| `app.py` | 61 | app factory, blueprint registration, ApiError/404/405/500 handlers |

Total: 2070 lines across 18 modules.

**Endpoint diff vs PRD §4:** 41 of 41 implemented, zero missing, zero extra (verified by grepping registered routes and diffing against the §4 table).

**Interpretations chosen (audit targets):**
1. **Lazy persistence**: reads report lazily-flipped state without persisting; writes persist the flip (+1 version) even when the write then fails with ERR_AGREEMENT_EXPIRED (dormancy rule's "persisted when the observing request is a write" applied uniformly to all three lazy dimensions).
2. **Stored-EXPIRED writes**: an agreement-scoped write on an already-EXPIRED agreement fails ERR_AGREEMENT_EXPIRED (409), not ERR_INVALID_STATE.
3. **All timestamps read the logical clock** (`created_at`, `updated_at`, `api_request_timestamp`), formatted with 3 fractional digits — `created_at` must be clock-comparable for slow_mover.
4. **Statement period-in-window**: first day of the period month must lie in the closed `[effective_start, effective_end]`; violation → ERR_INVALID_REQUEST 400 (no dedicated error exists).
5. **Plan period exempt from the future-month check** (PRD §3.7 omits it while §3.5/§3.8 state it; scaffold's generic priority-5 note disagrees — flagged).
6. **Changeover buffer is pairwise both directions** — inserting a new run *before* an existing different-spec run requires the later run to satisfy `later.start >= earlier.end + changeover_hours`.
7. Overlap/changeover consider only non-terminal runs (RESERVED, IN_PROGRESS) per calc `input_set`.
8. COMPLETED with missing `actual_units` → 400; out-of-range → ERR_CAPACITY_EXCEEDED 409.
9. Variety transition on nonexistent id → 404 (existence must precede ownership in practice); creation checks ownership from payload first (missing/non-string `brand_id` → 403).
10. Body-FK existence runs before other shape checks when the FK value is present (priority 4 < 5).
11. Pagination: `limit < 1` or non-integer → 400; `limit > 100` clamped; `offset < 0`/non-integer → 400.
12. List filter values are not enum-validated; unknown values yield empty pages.
13. Auto-denied warranty claims are created DENIED/AUTO_DENIED_DESCALE with `resolved_at` = creation clock, version 1.
14. Resolving APPROVED on a REPLACEMENT event of an already-DECOMMISSIONED brewer is not blocked (PRD gates creation only); side effect idempotent.
15. Priority-11 order for record-brews: variety-DELISTED → ERR_POD_BLOCKED → decommissioned, per scaffold listing order; lazy brewer eval (persisted) runs before payload validation on this write.
16. No range guards on `sell_in_units`/`sell_through_units`/`defect_rate_ppm`/`education_notices_sent` beyond integer type (not in PRD's enumerated ranges); education ≥ 1 enforced as ERR_EDUCATION_REQUIRED at priority 11.
17. Corrected `sell_through_units`/`unlicensed_share_pct` accepted on any →ISSUED transition (incl. DRAFT→ISSUED), applied before recomputation.
18. Subsidy snapshot counts stored ACTIVE/DORMANT brewers (lazy evaluation cannot change the count — both states count).
19. Household computed fields recomputed on read, never persisted → household `version` never increments (no direct household mutation endpoint exists).
20. Naive datetimes treated as UTC; `dispute_reason` must be a string (empty accepted); 405 → ERR_NOT_FOUND 404 envelope; unexpected exceptions → 500 `ERR_INTERNAL` (out-of-catalog fallback).

**Guard self-audit:** No invented gates beyond the interpretations above (each traces to a PRD/scaffold sentence); no PRD-stated gate knowingly dropped. Closest-to-invented items, all listed: stored-EXPIRED→ERR_AGREEMENT_EXPIRED (#2), bidirectional changeover (#6), pagination range 400s (#11), plan-period future-check exemption (#5). Window-shape and brand-LICENSED checks are re-run at activation per PRD §3.1.

**Self-smoke-test result:** Dynamic ports 44929 (first boot) and 37517 (after one fix); server killed by exact PID afterwards, port freed. Exercised: clock set (200), brand create (201), variety create as BrandManager (201, defaults correct), variety list with pagination meta (200), unknown route (404 ERR_NOT_FOUND), missing headers (401), wrong role (403), agreement create→activate→statement create (provisional **625** = hand-computed) → issue (final **481** = 550×0.92=506, ×0.95=480.7→481), subsidy snapshot 0→15 across brewer registration (margins 1000/985), household metrics (CHURNED→ENGAGED 90.0 → LAPSED 36.0 after +61d clock advance), record-brews reactivation DORMANT→ACTIVE (version 2). One real bug found and fixed during the smoke (`ok` missing from `routes_households.py` imports → 500 on GET /households/{id}); verified fixed after restart. No seeding; storage is in-memory dicts only; the test suite/design files were never read.

Orchestrator spot-check: 18 modules + start.sh + requirements.txt present; grep for `test_suite|test_helpers|SCAFFOLD_DIFFICULTY|SCAFFOLD_CORNER` across implementation/ returns 0 hits — isolation rule respected.

## Step 7: Test-fix iteration loop — 2026-10-02T03:25:00.000Z

**Summary**

- **Iterations run:** 2 (first sweep: 109/112 in all 8 rounds, 3 deterministic failures; second sweep after fixes: 112/112 in all 8 rounds).
- **Tests deleted:** none.
- **Fixes applied to `test_helpers/`:** none.
- **Fixes applied to `test_suite/`** (both were STEP 2 test bugs — fixtures inconsistent with PRD preconditions; the implementation was PRD-faithful in both cases):
    - `test_suite/test_04_license_agreements.py` — `test_territory_window_sharing_end_day_conflicts`: the incumbent agreement window (2026-01-01..2026-06-30) ended before the fixed startup clock (2026-09-01, PRD §2.4), so the incumbent was lazily EXPIRED when the challenger was created and the territory legitimately free. Shifted the incumbent to 2026-01-01..2026-12-31 (covers the clock, stays ACTIVE) and the challenger to start 2026-12-31 (ON the incumbent's inclusive end day), preserving the asserted closed-interval rule verbatim from PRD §3.1. Also fixed the sibling `test_territory_window_starting_day_after_end_is_legal` (same clock-unreachable design recipe `territory_closed_day_intervals`): it was passing vacuously against an expired incumbent; its challenger window moved to 2027-01-01..2027-06-30 so the "day after end is legal" branch is genuinely exercised against an ACTIVE incumbent.
    - `test_suite/test_11_retail_assortment.py` — `_variety_with_velocity_45001` (shared setup for `test_assortment_productivity_rounds_per_slot_then_sums` and `test_assortment_productivity_70001_fails_a_70002_floor`): the helper reserved a run at an absolute window (2026-09-10) and then advanced the clock into that window, so the *second* invocation in each test reserved a window_start in the past → `ERR_WINDOW_IN_PAST` (PRD §2.10.9) during setup. Parameterized the helper's `window_start`/`window_end`/`mid_window_instant` and gave the second call in each test a later window (2026-09-11T00:00–12:00, mid 06:00); both completed runs' `window_end`s remain inside the trailing 90-day velocity window at the approval clock (2026-09-12), keeping the asserted per-slot-rounding arithmetic (52501 + 17500 = 70001) exactly as derived from PRD §3.7.
- **Fixes applied to `implementation/`:** none — all three failures were test-fixture bugs; the implementation's lazy-expiry and window-in-past behavior matched PRD verbatim.
- **Evidence preserved:** all 8 final `results.{1..8}.json` files (each showing passed=112, total=112) remain in `workspace/implementation/`.

Orchestrator verification: all 8 `results.*.json` present and show passed=112/total=112/failed=0; newest implementation source file (`routes_households.py`, 02:59) predates the oldest results file (03:20) — no post-sweep impl writes; the two test-suite fixes are clock-fixture repairs consistent with prior clock-unreachable-recipe incidents.

## Step 8: Finalize PRD — 2026-10-02T03:40:00.000Z

**Result: byte-identical copy (zero-edit outcome).** `workspace/PRD_FINALIZED.md` is an exact copy of PRD.md — 305 lines vs 305 lines, 0.0% delta, identical md5 (`abc462ff1f16b04fffe1055e3389a048`). No edits were committed.

**Changes:** none. Both step_7_diff items are pure test-fixture bugs; every behavior they touch is already uniquely determined by PRD prose and the implementation matches it verbatim, so any edit would have manufactured a new mismatch.

**Per-diff-item evidence log:**

*Item 1 — test_04_license_agreements.py territory-window fixtures (incumbent window ended before the 2026-09-01 startup clock, so lazy expiry freed the territory).*
- (a) Subjects: territory-conflict scope (which incumbent states block), closed-interval day-granularity rule, lazy agreement expiry, fixed startup clock.
- (b) Impl paths read: `implementation/routes_licensing.py` — `territory_conflict` lines 70-88 (lazy-evaluates each candidate via `eval_agreement_lazy(other, persist=True)` at line 79, skips any not in `("ACTIVE","SUSPENDED")` at line 80, closed-interval test `start <= o_end and o_start <= end` at line 86, amendment-chain exemption via `_chain_root` lines 55-67); callsites `create_agreement` line 162, `transition_agreement` activation branch lines 219-241, `amend_agreement` lines 279-282; `agreement_write_gate` lines 135-141. `implementation/calc.py` — `eval_agreement_lazy` lines 50-61 (ACTIVE→EXPIRED when `get_clock().date() > effective_end`; DRAFT never expires). PRD passages read: §2.4 (startup clock exactly `2026-09-01T00:00:00Z`; on every agreement-scoped read or write an ACTIVE agreement whose `effective_end` date has been passed becomes EXPIRED; lazy evaluation runs before state-machine checks), §3.1 (collision only "with an existing `ACTIVE` or `SUSPENDED` agreement"; closed-interval rule with both branches spelled out — day-after-end legal, same-final-day conflict; amendment-chain exemption).
- (c) Conclusion: no edit. The failing fixtures assumed a stored-ACTIVE incumbent whose window ended 2026-06-30 would still block; PRD §2.4 + §3.1 uniquely determine that it is lazily EXPIRED and therefore outside the conflict scope. Impl matches PRD verbatim on all four subjects; the fixed tests assert the PRD's closed-interval rule unchanged.

*Item 2 — test_11_retail_assortment.py `_variety_with_velocity_45001` (second invocation reserved a `window_start` in the past after the clock advanced into the first window).*
- (a) Subjects: `ERR_WINDOW_IN_PAST` trigger, run start/completion window gates, per-slot-rounding-then-sum productivity, trailing-90-day velocity window.
- (b) Impl paths read: `implementation/routes_runs.py` — `create_run` lines 31-104 (`ws < get_clock()` → `ERR_WINDOW_IN_PAST` 422 at lines 53-55; `ERR_INVALID_WINDOW` at 49-51; capacity via `window_days` at 93-96), `transition_run` lines 130-156 (IN_PROGRESS requires `run["_ws"] <= clock < run["_we"]` at 142-146). `implementation/routes_retail.py` — APPROVED branch lines 145-157 (per-slot `facings * velocity * margin / 90` quantized `ROUND_HALF_UP` to whole cents, then summed as ints; floor shortfall → `ERR_PRODUCTIVITY_FLOOR_UNMET` 422). `implementation/calc.py` — `variety_velocity` lines 157-169 (COMPLETED runs with `window_end` in `[clock-90d, clock]`, inclusive both ends), `window_days` lines 44-46. PRD passages read: §2.10 item 9 and §3.4 (`window_start` before the logical clock is `ERR_WINDOW_IN_PAST` 422; start transition window gates), §3.7 and §2.6 (per-slot half-up rounding first, then sum; sum-then-round explicitly not the contract), §3.3 (velocity window inclusive both ends).
- (c) Conclusion: no edit. The helper's absolute 2026-09-10 window collided with the clock it itself advanced — a fixture sequencing bug. The asserted arithmetic (52501 + 17500 = 70001 vs the sum-then-round 70002) is derived exactly from PRD §3.7's pinned rounding order, which the impl implements literally. All four subjects are uniquely determined by PRD; impl matches.

**Per-edit pre-edit search log:** no edits were committed, so no pre-edit searches were required beyond the enumeration above (which confirmed no PRD wording change was warranted at either site).

Orchestrator verification: `diff -q PRD.md PRD_FINALIZED.md` confirms byte-identical (305 = 305 lines). The zero-edit outcome was explicitly permitted in the prompt because the Step 7 diff was fixture-only (0 implementation fixes, 0 deletions).

## Step 9: Complete PRD — 2026-10-02T04:05:00.000Z

All edits verified. The task is complete. Final summary:

**Source vs output:** `PRD_FINALIZED.md` 305 lines / 57,093 chars → `PRD_COMPLETED.md` 308 lines / 61,323 chars (**+3 lines, +4,230 chars**; files differ, 18 diff hunks covering 20 edits). File: `workspace/PRD_COMPLETED.md`

**Counts:** 16 ambiguity-pins, 4 mismatch-revisions, 0 omission-style mismatches.

**Changes (one per bullet):**
- §2.2 — insert — ambiguity — unknown-path and wrong-method requests answered as `ERR_NOT_FOUND`/404 in the standard envelope; unexpected failures as `ERR_INTERNAL`/500 — implementation/app.py:40-53
- §2.3 — insert — ambiguity — limit<1 / offset<0 / non-integer → `ERR_INVALID_REQUEST` 400; limit>100 clamped to 100, not rejected — implementation/helpers.py:219-242
- §2.3 — insert — ambiguity — `created_at` ties break by creation order (descending listings: later-created first); filter values never validated, unrecognized values just match nothing — implementation/helpers.py + all list routes (e.g. routes_varieties.py:66-80)
- §2.4 — insert — ambiguity — clock-set accepts any well-formed timestamp (no monotonicity constraint); offset-less datetimes read as UTC; all server timestamps (`api_request_timestamp`, `created_at`, `updated_at`, lifecycle stamps) come from the logical clock — implementation/routes_clock.py:10-16, helpers.py:158-170, helpers.py:42-47
- §2.4 — insert — ambiguity — a lazy flip observed by a read is reported but carries no `version`/`updated_at` change; only write-observed flips persist bookkeeping — implementation/calc.py:50-92 (`persist` flag), routes_licensing.py:182
- §2.10 item 4 — insert — ambiguity — array-nested foreign keys (slot `variety_id`s) resolve right after the array's structural shape validation, ahead of later steps — implementation/routes_retail.py:75-79
- §2.10 item 5 — **revise — mismatch** — blanket "period not after the current clock month" scoped to consumption records and royalty statements; assortment plan periods are exempt (impl never calls `period_not_future` for plans) — implementation/routes_retail.py:74 vs routes_households.py:40, routes_statements.py:52
- §2.10 item 7 — insert — ambiguity — a `target_state`/`outcome` outside the endpoint's declared vocabulary fails step-5 shape as `ERR_INVALID_REQUEST`, never reaching the state-machine check — implementation/routes_licensing.py:16,214; routes_varieties.py:16,91; routes_runs.py:16,135; routes_retail.py:16,133; routes_statements.py:16,103; routes_service.py:65
- §2.10 item 9 — **revise — mismatch** — the lazy-expiry rejection (`ERR_AGREEMENT_EXPIRED`) fires at lazy-evaluation time, ahead of the step-7 state-machine check, so expired-agreement writes never report `ERR_INVALID_STATE` — implementation/routes_licensing.py:135-141 (`agreement_write_gate` called before `_DECLARED` check at line 215), routes_audits.py:30, routes_statements.py:57
- §3.1 — **revise — mismatch** — territory-conflict exemption covers any two agreements whose `amendment_of_id` ancestry shares a root (whole chain), not just immediate parent–child pairs — implementation/routes_licensing.py:55-88 (`_chain_root`)
- §3.1 — **revise — mismatch** — amend: a non-`ACTIVE` source is `ERR_INVALID_STATE`; only a version mismatch on an `ACTIVE` source is `ERR_STALE_VERSION` (was "otherwise `ERR_STALE_VERSION`" for both) — implementation/routes_licensing.py:273-278
- §3.4 — insert — ambiguity — only `RESERVED`/`IN_PROGRESS` runs hold windows for overlap and changeover; `COMPLETED` and `CANCELLED` release theirs — implementation/routes_runs.py:23-28
- §3.4 — insert — ambiguity — changeover comparison reads each run's roast/material from its variety's *current* state, so a post-reservation material conversion changes compatibility — implementation/routes_runs.py:62-66
- §3.5 — insert — ambiguity — record-brews gates fire delisting → firmware → decommissioning (decommissioned+delisted reports `ERR_VARIETY_NOT_ACTIVE`; decommissioned+restrictive+unlicensed reports `ERR_POD_BLOCKED`) — implementation/routes_brewers.py:83-94
- §3.5 — insert — ambiguity — the four household fields are computed on read, never stored; brewer/consumption/service mutations do not bump the household's `version`/`updated_at` — implementation/serializers.py:103-110, calc.py:186-232 (no `touch` on households anywhere)
- §3.6 — revise — ambiguity — auto-denied warranty claim is born terminal in `DENIED` with `resolved_at` stamped from the logical clock at creation — implementation/routes_service.py:35-38
- §3.6 — insert — ambiguity — warranty month addition clamps day-of-month to the target month's length (Jan 31 + 1mo → Feb 28) — implementation/calc.py:37-41
- §3.7 — insert — ambiguity — plan `period` may name a future month (cross-references the §2.10 exemption) — implementation/routes_retail.py:74
- §3.8 — revise — ambiguity — period-in-window rule pinned: the first day of the period month must lie on/between `effective_start` and `effective_end`; violation is `ERR_INVALID_REQUEST` 400 — implementation/routes_statements.py:37-43
- §3.8 — insert — ambiguity — dispute and settle transitions are not gated on agreement state; only issuance/re-issuance are — implementation/routes_statements.py:112-121
- §5 — insert — ambiguity — added `ERR_INTERNAL` | 500 row to the error catalogue — implementation/app.py:50-53

**Rediscovered audit-target coverage:** all 14 hinted targets addressed — lazy-persistence, stored-EXPIRED writes, timestamp sourcing, statement period-in-window, plan-period exemption, pagination clamping, filter non-validation, auto-denied shape, record-brews order, household recompute-on-read, naive datetimes, and 405/500 fallbacks were pinned; the bidirectional changeover buffer was verified already pinned by the PRD's later/earlier language (routes_runs.py:68-75, no change needed); the subsidy snapshot counting rule was verified PRD-consistent (stored-state vs lazy-evaluated counting is unobservable since both ACTIVE and DORMANT count — calc.py:179-182, no change needed).

**OMISSION-STYLE MISMATCHES:** none. Every PRD-stated hard requirement is implemented: all cascades touch-and-bump affected resources (routes_licensing.py:91-132), all §2.10 ranges/enums match, all error IDs and HTTP statuses match the §5 catalogue, all endpoint/role pairs in §4 match the blueprints, both OCC guards exist, and the provisional/final royalty split with pinned multiplier order is implemented exactly (calc.py:96-153). Dead-code sweep: no defined-but-never-called functions; two guards are unreachable in practice — the `DRAFT→PROPOSED` empty-slots re-check (routes_retail.py:139, slots can never become empty post-creation) and the activation-time window re-check (routes_licensing.py:222, stored dates are always pre-validated) — but both are explicitly PRD-mandated re-assertions, so they are intentional, not omissions.

Orchestrator adjudication of the 4 mismatch revisions (per lost-scaffold-intent check):
1. §2.10 item 5 plan-period exemption — ACCEPTED. Scaffold priority-5 reads "period ... not after the current clock month ... applies_to: all write endpoints", but the corner design's only future-period instance targets statements (which impl does reject), no test covers plan periods, and PRD §3.7 itself omitted the check while §3.5/§3.8 stated it. The revision reconciles §2.10 with §3.7's own prose; per Key Principle 1 PRD beats scaffold. No impl fix needed; sweep not invalidated.
2. §2.10 item 9 ERR_AGREEMENT_EXPIRED precedence — matches Step 6 interpretation #2 and scaffold priority-9 listing; impl behavior unchanged.
3. §3.1 amendment-chain whole-chain exemption — matches scaffold ("amendment-chain territory exemption with SUPERSEDED source"); codifies impl behavior.
4. §3.1 amend ERR_INVALID_STATE vs ERR_STALE_VERSION ordering — a priority pin consistent with §2.10's ordering; impl unchanged.
Step 9 touched only PRD_COMPLETED.md — verified: newest implementation source mtime still 02:59 (Step 6), so the Step 7 clean sweep remains the valid final evidence. `diff -q` confirms PRD_COMPLETED.md differs from PRD_FINALIZED.md (not a silent no-op).
