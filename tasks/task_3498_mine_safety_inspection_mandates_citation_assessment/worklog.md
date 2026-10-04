# Worklog — task_3498_mine_safety_inspection_mandates_citation_assessment

## Step 1: Create task directory — 2026-10-02T18:42:00.000Z

Pre-allocated directory `tasks/task_3498_mine_safety_inspection_mandates_citation_assessment/` verified present with empty `workspace/` inside; used as-is (no new index computed, per invocation args).

## Step 2: Generate Scaffold — 2026-10-02T19:55:00.000Z

All three artifacts are complete, parse cleanly, and pass `scaffold_lint.py` with a clean verdict.

## Deliverables

| File | Lines | Key counts |
|---|---|---|
| `SCAFFOLD.yaml` | 1469 | 12 entities, 55 endpoints, 9 state machines, 8 calculations, 12 validations, 30 errors, 6 roles, 2 OCC concurrency rules |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1936 | 21 instances total, 21 non-stub (≥2 per each of the 9 Difficulty Rules) |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 2005 | 60 instances total, 54 non-stub, 6 `excluded_because` stubs |

Lint verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (858 calls scanned.) Additional audits passed: instance names unique across both design files, zero unbound `${var}` placeholders, all `grounds:` resolve, no forbidden concurrency vocabulary, every one of the 30 error ids is exercised by at least one design instance. All formula-derived assert literals (penalties 194063/174657/60000/450000/2062500/2250000/112500, POV scores 8/7/6/2, cycle windows) were precomputed by executing the pinned §1.3 formulas in exact Decimal arithmetic.

## Domain design (MSHA mine-safety program)

Twelve flat, FK-linked entities: Operator, Mine, Inspector, InspectionCycle, Inspection, Citation, PenaltyAssessment, ImminentDangerOrder, Contest, MinePlan, Accident, POVScreening. The penalty engine is a seven-factor tiered point table feeding a pinned 4-step pipeline (marginal dollar tiers → 1.15 repeat multiplier with round-half-up → 10% good-faith discount with a second rounding → statutory floor last), with proposed-vs-final dual variants; POV screening is the second dual-variant calculation (SCREENING counts unresolved contested citations, FINAL_DETERMINATION excludes them) over a rolling 365-day window with a >=8 threshold driving NONE→POTENTIAL_POV→POV_FINAL, where each new S&S citation auto-cascades to an imminent-danger order → mine halt → inspection suspensions. Non-linear state machines span Citation (independent abatement × contest axes), Inspection (reassignment cycle wiping the mandatory pre-entry file review), and Mine (idle↔active plus POV axes); statutory cycles use fixed 90/180-day contiguous windows that close DELINQUENT rather than forgiving shortfalls, with oldest-delinquent-first make-up crediting. Compliance difficulty concentrates in segregation-of-duties (verifier ≠ issuer), OCC on plan supersession and contest filing, half-open inspector scheduling vs closed-interval IDO re-issuance, and priority-arbitrated dual-failure validation pairs.

One notable fix during authoring: the lint's FK reverse-reachability check requires sub-resource paths to use the literal `{id}` placeholder, so the four sub-resource GETs (operator's mines, mine's cycles, mine's screenings, citation's assessments) use `{id}`; also added the initially-omitted `ERR_POV_SCORE_INSUFFICIENT` to the §1.6 catalog after the audit flagged it referenced-but-undeclared.

Orchestrator verification: all three files parse as YAML; api_prefix is `/msha`; 390 mine/inspector/citation mentions confirm on-domain content; line counts match the report (1469/1936/2005).

## Step 3: Copy shared files — 2026-10-02T19:57:10.000Z

Copied INSTRUCTION.md to workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T20:05:00.000Z

All checks pass. The PRD is complete and verified.

**Deliverable**: `workspace/PRD.md` — 290 lines, written in 4 Write/Edit operations (no mid-sentence truncation).

**Self-coverage sweep**
- Error IDs: **30/30** present in §2/§3 prose and the §5 catalogue
- Endpoints: **55/55** scaffold rows present in the §4 table (48 unique paths, all verified)
- Contract 1 (field names): 88 entity fields + 4 common fields, 50 request-body identifiers, 18 query params, 12 path params — all present in backticks (one miss, `verification_note`, found by the sweep and fixed)
- Contract 2 (rules): 12/12 validation tiers with first-failure-wins precedence; 2/2 OCC rules (`expected_mine_version`/`expected_citation_version` → `ERR_STALE_VERSION` 412); all 9 state machines with every transition, precondition, and side effect; all 8 calculations in reconstruction-safe prose (tier cents 11,250/22,500/37,500/52,500, ×1.15 repeat, 10% good-faith, floors 150,000/120,000/60,000 applied LAST; 730-day history and 365-day POV windows as exclusive-start/inclusive-end; 900s/7200s strict late-report; 90/180-day inclusive contiguous cycles; delinquent-first crediting; ceil-extension rendered as worked values 15/8/3/1 days)
- Contract 3 (§3 path purity): 521 backtick tokens scanned — 0 path/method violations
- §2.2 block verified byte-identical to `section-2.2-response-structure.md`; 72/72 enum/state values and 6/6 role names exact

**Scaffold ambiguities resolved in prose** (flagged for downstream relitigation):
1. **Auto-IDO fields**: entity text says `inspection_id`/`issued_by_inspector_id` are "null for POV-auto-generated orders" but the citation endpoint's side effect pins both to the citing inspection/inspector. I rendered the endpoint rule (specific beats general).
2. **Unpinned error mappings**: `badge_number` uniqueness and citation-payload `mine_id` ≠ inspection's mine both lack catalog error_ids; both mapped to `ERR_INVALID_REQUEST` (400). Manual-IDO with a non-IN_PROGRESS `inspection_id` → `ERR_INVALID_STATE`; wrong inspector → `ERR_INSPECTOR_MISMATCH` (per the catalog's own wording).
3. **Known-ambiguity sites made explicit**: timestamp families (3-fraction-digit `created_at`/`updated_at`/`api_request_timestamp` vs domain timestamps rendering as the logical clock reads); error precedence cascade with two worked cross-tier examples; boundary inclusivity stated at every window (contest +30d inclusive vs finalize strictly-after; late-report strict `>`; on-time verify `<=` deadline; half-open scheduling; IDO closed-interval re-issuance); empty-list → 200 + empty array; unpublished public-report → 404-as-absent; reassignment re-checks only conflict+certification (scaffold silence on double-booking preserved deliberately); POV_FINAL auto-IDO cascade suspends the citing inspection itself ("every IN_PROGRESS inspection at the mine", rendered verbatim-faithful).

Orchestrator verification: PRD.md is 290 lines; penalty tier constants (11,250/22,500/37,500/52,500) and floors (150,000/120,000/60,000) present verbatim; 66 `ERR_` mentions incl. 5× `ERR_STALE_VERSION`; clock endpoint explicitly documented outside `/msha` prefix.

## Step 5a: Generate test helpers (Stage 1 of Step 5) — 2026-10-02T20:35:00.000Z

All checks pass. The package is complete and frozen. Final verification summary below.

## Stage 5a complete — `test_helpers/` frozen

**Files written** (all under `test_helpers/`):

| File | Lines | Contents |
|---|---|---|
| `types.py` | 367 | 19 status/role enums, 12 entity TypedDicts (all carry `id`/`created_at`/`updated_at`/`version` per PRD §2.4) |
| `constants.py` | 179 | All domain thresholds (trace map below) |
| `api_errors.py` | 87 | 30 `ApiErrorId` values + HTTP map, registered with `set_error_http_status_map` at import |
| `api_client.py` | 244 | `ApiClient(GenericApiClient)` with 55 endpoint methods (1 per PRD §4 row) + `api_client` singleton |
| `test_users.py` | 86 | `TEST_USERS` (4 opaque roles canonical + 2 entity-backed fallbacks) and per-instance `make_inspector_headers`/`make_operator_rep_headers` honoring PRD §2.1 identity |
| `factories.py` | 320 | 20 payload factories + date/datetime helpers (`cycle_period_end`, `add_seconds`, `abatement_extension_days`, …) |
| `assertions.py` | 459 | 12 `assert_{entity}` shape checkers, two timestamp-family checkers, `validate_created` (201 wrapper), and PRD §3.4/§3.7 reference math (`compute_points_total`, `compute_proposed_penalty_cents`, `compute_final_penalty_cents`, `statutory_floor_cents`, `compute_pov_weighted_score`) |
| `fixtures.py` | 850 | 63 composite fixtures: registry, inspection lifecycle, cycles (incl. `setup_mine_with_delinquent_cycle`), plan gate (`setup_required_plans`, `setup_regular_completion_ready`), citations/abatement/finalize, IDO lifecycle, contests, accidents, POV (`setup_potential_pov_mine`, `setup_pov_final_mine`) — all identity-threaded, clock moves explicit |
| `__init__.py` | 60 | Barrel: framework generics + all modules |

**Verification:** `python3 -m compileall` clean; real package import clean (no dangling imports); 44 critical exports present; self-check battery passed — every reference-math output matches the design indices' literal expected values (60000 floor raise, 194063 repeat half-up, 174657 good-faith final, 258750, 75→1687500, history-6→10 points→112500, POV 8-vs-7, abatement deadlines 2026-03-12/2026-02-18, cycle geometry 2026-01-01→2026-03-31 / 2026-04-01→2026-06-29). Client surface = 55 PRD endpoints + 4 framework conveniences.

**Key contract answers:**
- Logical-clock start (verbatim, PRD §2.4): **`2026-09-01T00:00:00Z`**
- Clock endpoint (verbatim, PRD §4): **`POST /_clock/set_current_utc`** — implemented unprefixed in `api_client.set_clock` / `fixtures.set_clock`; `CLOCK_ENDPOINT_PATH` asserted to not start with `/msha`.
- Timestamp families: `assert_system_timestamp` enforces exactly 3 fractional digits (created_at/updated_at/api_request_timestamp); `assert_domain_timestamp` accepts the clock's own rendering (fraction optional); `assert_iso_date` for the three calendar-date fields. Unit-checked both families.
- `validate_created(resp)` = 201 wrapper; framework `validate_success` default 200 documented in barrel + assertions docstrings; `validate_error_is_one_of` re-exported through the barrel.

**Constants traceability:** every constant in `constants.py` traces to a verbatim PRD literal (§2.3 pagination 10/1/100/0; §2.4 clock start; §2.6 90/180-day cycles; §3.2 baseline 1 + POV +1; §3.4 point tables, tiers 11,250/22,500/37,500/52,500, multiplier 1.15, discount 10%, floors 150,000/120,000/60,000, abatement 30/15/5/1 + ceil-half extension, contest +30d; §3.6 window; §3.7 900s/7200s, "50.10 LATE REPORT", 180-day plan revision, POV 365-day window 2/1/5 weights threshold 8). Nothing was carried from scaffold without a PRD match. `TEST_DEFAULTS` is explicitly labeled helper-layer convenience, not PRD rules. **No untraceable constants.**

**Caveats for Stage 5b:** (1) Both design indices pin the clock to dates *before* the 2026-09-01 startup reading (e.g. 2026-02-10) — helper defaults stay ≥ the startup reading per contract; whether backward clock sets are accepted is an impl question the sweep will settle. (2) Always `from test_helpers import api_client` — `import test_helpers.api_client` resolves to the instance, not the module (known shadowing footgun). (3) `fixtures.py` never moves the clock except `setup_mine_with_delinquent_cycle` and `advance_clock_past_contest_window`, both documented.

Orchestrator verification: 9 modules present (incl. `__init__.py`); `compileall` + real import clean; scripted scan found ZERO untraced numeric constants >100 in constants.py; clock start `2026-09-01T00:00:00Z` confirmed present in PRD.md.

Orchestrator note — Step 5 split into 5a/5b per prior-pipeline experience (oversized single-shot generation truncates). Queue sizes measured by orchestrator directly from YAML: Queue A (Difficulty) = 21 non-stub across 9 rules (dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 2, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 2); Queue B (Corner) = 54 non-stub across 9 sections (entities 10, state_machines 11, calculations 6, validations 7, endpoints 4, errors 5, rbac 6, complexity_layers 4, consistency_model 1; a second stub-only `state_machines` group of 6 excluded instances exists). Grand total 75 non-stub.

## Step 5b: Generate test suite (Stage 2 of Step 5) — 2026-10-02T21:20:00.000Z

Stage 5b is complete and fully audited. Final state of `test_suite/`:

**Files written (12, ~3000 lines):**
- `conftest.py` (50) — session `api` fixture + six role-header fixtures
- `test_01_registry.py` (181) — operator/mine creation defaults, shape closure, clock epoch
- `test_02_cycles.py` (218) — cycle geometry, early close, idle round-trip, oldest-DELINQUENT-first crediting
- `test_03_inspections.py` (426) — assignment gates, file-review loop, half-open windows, safety-vs-engagement priority, plan gate
- `test_04_citations.py` (254) — computed-field round-trip, pagination, filters, version deltas, immediate read-back
- `test_05_penalties.py` (486) — points/pipeline/rounding/floors, good-faith divergence, finalize window, extension rules
- `test_06_contests.py` (277) — dual citation axes, 30-day boundary, state-vs-temporal priority, fiscal payloads, OCC
- `test_07_imminent_danger.py` (230) — halt/suspend cascade, closed-interval reuse, terminal lockdown, SoD
- `test_08_pov.py` (260) — screening vs final-determination divergence, threshold 7/8, 365-day window edge, auto-IDO cascade
- `test_09_accidents.py` (192) — late-report auto-citation, 900s boundary, publication gate, public projection
- `test_10_mine_plans.py` (192) — supersession cardinality, REVISION_DUE clock flip, plan-type applicability, OCC
- `test_11_api_conventions.py` (236) — auth tiers, cascade ordering, envelopes, pagination defaults, ownership scope

**Coverage: Queue A 21/21, Queue B 54/54 — 75 tests total, zero skipped instances.** The PRD carries the §2.5 validation cascade ordering, §2.7 rounding discipline, §2.8 OCC rules, and §2.4 clock/version contracts verbatim, so even the priority-pair and OCC instances pass the two-condition filter. The six `excluded_because` state_machines stubs were not translated (their Difficulty instances own the assertions).

**Audit results (all self-run, real AST + YAML parses):**
- Tag audit: 75 emitted == 75 expected, zero untagged / dual-tagged / dangling; every `Design:` tag is the docstring's last line and resolves to a real instance
- `python3 -m compileall`: clean
- `pytest --collect-only -q` (PYTHONPATH=task dir): **75 tests collected**, no import errors
- Verbatim citation check: 137 `PRD §…` quote blocks, every 8-word window greps PRD.md — all pass (8 quote-fidelity defects found and fixed during the sweep: trailing punctuation mismatches, one `...` elision, one parenthetical fused into a quote)
- Unused-import sweep: clean

**Clock rebasing (per the clock-reachability note):** all recipes pinned dates before the 2026-09-01T00:00:00Z startup reading; every test was rebased forward with relative intervals preserved. Recomputed literals: UG cycles [2026-09-01, 2026-11-29] / [2026-11-30, 2027-02-27], SURFACE cycle [2026-09-01, 2027-02-27], NO_INJURY deadline 2026-10-10T09:00:00Z (issued 2026-09-10T09:00), SERIOUS deadline 2026-09-15T09:00 → +3d extension → 2026-09-18T09:00, contest boundary 2026-10-01T10:00:00Z (issued 2026-09-01T10:00, inclusive at +30d, lapsed +1s), plan revision due 2027-03-09T00:00:00Z (approve 2026-09-10 + 180d), POV window edge 2026-09-10T00:00:00Z vs screening 2027-09-10T00:00:00Z (365d, leap-free span). Penalty cents are date-independent (194063/174657/2250000/258750/1687500/60000/112500/450000 match the index).

**Workarounds (helpers untouched, as required):**
1. Absolute version literals (`version == 1`, `Mine.version == 3`) are not uniquely derivable — PRD §2.4 pins only the +1-per-mutation delta, no start value. Those sub-assertions became exact +1 delta checks / `int >= 1` presence, documented in the docstrings (B1, B2, B11, A8, A9, B52).
2. Corner instance `cycle_close_early_requires_met_requirement`'s recipe sets the clock backward mid-setup; restructured (plan approval before the early-close attempt) so the clock moves strictly forward — asserted outcomes unchanged, noted in the test.

Orchestrator verification (independent re-run): `compileall` clean; `pytest --collect-only` = 75 collected; AST tag audit re-run from YAML: 75 tests, 75 unique tags, all resolve to real non-stub instances, 0 uncovered instances.

## Step 6: Generate implementation — 2026-10-02T21:55:00.000Z

Implementation complete and verified. Summary:

## Files written (23 files, 2,700 lines) — all under `workspace/implementation/`

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | Foreground launcher, guarded `pip install`, `exec python3 app.py`, `$PORT`/`0.0.0.0` |
| `requirements.txt` | 1 | `flask>=3.0` |
| `constants.py` | 137 | Every PRD-verbatim constant: tier cents 11,250/22,500/37,500/52,500, ×1.15 repeat, 10% good-faith, floors 150,000/120,000/60,000, windows 730/365/90/180d, 900s/7200s, threshold 8, weights 2/1/5, abatement 30/15/5/1d, contest 30d, plan 180d, clock start `2026-09-01T00:00:00Z`, all enum sets and roles |
| `errors.py` | 83 | All 30 catalog error_ids with pinned HTTP statuses + `ApiError` |
| `clock.py` | 94 | Logical clock (never wall-clock), parse/render with the TWO timestamp families |
| `store.py` | 54 | Plain-dict in-memory store, empty at boot (no seeding), dashed `uuid4()` ids, version/touch |
| `envelope.py` | 79 | `meta`/`response_type`/`data` envelope, `req_` ids, limit/offset/total_count/has_more pagination |
| `validate.py` | 138 | Tier 1-3 cascade (auth, roles, strict body shape: undeclared-field rejection, enums, int ranges, datetime/date parsing) |
| `serialize.py` | 230 | 12 entity serializers; created_at/updated_at at 3-digit millis, domain timestamps as clock reads, plain YYYY-MM-DD dates |
| `services_penalty.py` | 197 | 7-factor points, pinned pipeline (tiers → ×1.15 round-half-up → 10% round-half-up → floor LAST), proposed/final/MODIFIED/VACATED variants |
| `services_cycles.py` | 81 | Cycle geometry validation + delinquent-first quota crediting with CURED |
| `services_pov.py` | 44 | POV weighted score, SCREENING vs FINAL_DETERMINATION filters |
| `services_ido.py` | 77 | IDO one-active-order rule, halt/suspend and resume cascades |
| `routes_registry.py`, `routes_cycles.py`, `routes_inspections.py`, `routes_citations.py`, `routes_idos.py`, `routes_contests.py`, `routes_plans.py`, `routes_accidents.py`, `routes_pov.py` | 125/76/272/244/123/174/127/158/86 | 9 per-domain Flask Blueprints |
| `app.py` | 90 | App factory, error handlers, unprefixed `POST /_clock/set_current_utc` with REVISION_DUE flip |

## Verification results
- `python3 -m compileall -q .` → COMPILE_OK; `import app` → IMPORT_OK, **56 URL rules** = 55 API routes (54 under `/msha` + unprefixed clock) + Flask's built-in `/static`. Note: the scaffold's endpoint table contains **54 business routes + 1 clock = 55 total** (the prompt's "55 business endpoints" counts the clock); every table row is implemented.
- Self-smoke-test on dynamically allocated ports (39801, 53059), launched via `bash start.sh`, killed only the saved `$!` PIDs: 401 `ERR_UNAUTHENTICATED` envelope without headers; `POST /_clock/set_current_utc` → 200 `{"current_utc":"2026-09-01T00:00:00Z"}`; operator create → 201 dashed-UUID; mine create → 201 with ACTIVE/NORMAL/NONE defaults; mine read-back → 200; empty citation list → 200 with `total_count:0`; wrong-span cycle → 422 `ERR_CYCLE_PERIOD_INVALID`; valid 90-day cycle → 201 (`cycle_index:1, required_inspections:1`); second OPEN cycle → 409 `ERR_CYCLE_OPEN_EXISTS`; operator mines listing → 200.

## Interpretations chosen (PRD admitted >1 reading)
1. **Version/updated_at bumps (§2.4 vs scaffold side_effects)** — §2.4 ("version increments by exactly one on *every* mutation") applied uniformly, including scaffold transitions with empty `side_effects` (file-review, start, complete, close, CURED, REVISION_DUE flip). PRD wins over the scaffold's selective annotations.
2. **Citation-create mine-match (§3.4)** — the `ERR_INVALID_REQUEST` mine-vs-inspection coherence check is placed immediately after tier-4 existence, before tier-6 inspector-mismatch and tier-7 state (it needs the resolved inspection, so it cannot live in tier 3).
3. **Body FK resolution order (§2.5 tier 4)** — the scaffold's parenthetical omits `inspection_id`; citations resolve `inspection_id` then `mine_id`.
4. **Tier-11 intra-tier order (cycle create)** — `ERR_CYCLE_OPEN_EXISTS` before `ERR_CYCLE_PERIOD_INVALID` (scaffold listing order).
5. **`good_faith_applied` flag (§3.4)** — true only when the good-faith condition held AND the floor did not overwrite the discounted net ("whether a stored final figure *reflects* the discount").
6. **No-input POST endpoints** — a non-empty JSON object body → `ERR_INVALID_REQUEST`; absent/empty body OK.
7. **Pagination out-of-range** — limit <1 or >100, negative offset, or non-integer → `ERR_INVALID_REQUEST` (min/max read as constraints).
8. **List filter semantics** — invalid enum/FK filter values match nothing (§2.10 "a filter that matches nothing returns 200 empty"); `significant_and_substantial` accepts only `true`/`false`, else 400.
9. **POV notice with insufficient score** — rejected with `ERR_POV_SCORE_INSUFFICIENT` and NO POVScreening row is persisted (rejection = no creation).
10. **Auto-IDO at POV_FINAL** — hazard text is `AUTO_IDO_HAZARD_DESCRIPTION` (PRD pins the behavior, not the text); the one-active-order/strictly-after-terminated gate is NOT applied to auto-IDOs (unreachable anyway: an IN_PROGRESS inspection implies no active IDO at the mine).
11. **Reassign double-booking** — not re-checked on reassignment (scaffold preconditions list only conflict + certification); the window is unchanged and §3.3 lists the booking gate only for assignment.
12. **IDO verify/confirm identity** — confirm-withdrawal has no identity check (any Inspector, per scaffold); verify enforces only SoD vs the issuer; a nonexistent inspector id passes SoD (PRD requires no existence check on the verifier).
13. **System-issued late-report citation** — verifiable by any inspector (issuer is null); it does not trigger the POV_FINAL auto-IDO (not S&S); its assessment runs the standard proposed pipeline from the fixed factors.
14. **Public projection** — returns the full serialized Accident once REPORT_PUBLISHED (PRD does not enumerate a reduced field set).
15. **Input datetime normalization** — `planned_start_at`/`occurred_at` etc. are normalized to UTC and rendered with `Z` (the clock's rendering family); naive inputs treated as UTC; date-only strings rejected for date fields unless exactly `YYYY-MM-DD`.
16. **Clock-set flip direction** — any `APPROVED` plan with `next_revision_due_at <=` new clock flips to REVISION_DUE regardless of set direction; the flip never reverts (state machine has no exit).
17. **405 handling** — unknown-method on a known path renders the error envelope as `ERR_NOT_FOUND`/405 (outside the catalog; unreachable via declared surface).

## Contradictory / unimplementable requirements
None found. The PRD and scaffold agreed on all reachable behavior; no requirements were dropped.

Orchestrator hand-off verification: entity ids use dashed `str(uuid.uuid4())` (the only `.hex` use is `req_` envelope ids — not resource ids); clock route registered unprefixed at app.py:60; scripted literal cross-check — 11250/22500/37500/52500/150000/120000/60000/1.15/`2026-09-01T00:00:00Z` all present in impl constants.py AND test_helpers/constants.py AND PRD.md (zero drift); compileall clean.

## Step 7: Run tests and iterate — 2026-10-02T22:15:00.000Z

All 8 rounds pass 75/75 — clean sweep achieved. Results files left in place as pipeline evidence.

## Summary

- **Iterations run:** 2 (sweep 1: 74/75 in all 8 rounds, single deterministic failure; sweep 2 after fix: 75/75 in all 8 rounds).

- **Tests deleted:** none.

- **Fixes applied to `test_suite/`:**
  - `test_suite/test_05_penalties.py` — `test_penalty_points_tiered_multi_input_total`: corrected expected `points_total` 90 → 85 and `proposed_penalty_cents` 2250000 → 2062500 (plus comments). The test's own component list (MODERATE 25 + REASONABLY_LIKELY 15 + SERIOUS 20 + persons(3) 5 + S&S 15 + history 0 + size(120000t) 5) sums to 85; the 90 expectation traces to an arithmetic slip in the scaffold design instance (`SCAFFOLD_DIFFICULTY_DESIGN.yaml` line 266: "25+15+20+5+15+0+5 = 90"). PRD §3.4 states every factor table and the marginal tier conversion verbatim, and uniquely derives 85 points → 20×11250 + 40×22500 + 25×37500 = 2062500 cents. STEP 1a covered, STEP 1b uniquely derivable, STEP 2 verdict: TEST IS WRONG (wrong expected constants, not a missing rule).

- **Fixes applied to `test_helpers/`:** none (fixture chain verified faithful — tonnage 120000 reaches the operator payload correctly).

- **Fixes applied to `implementation/`:** none. Live replay against a manual server confirmed the implementation computes the PRD-correct 85 points and 2062500 cents; the implementation was PRD-faithful throughout.

Orchestrator verification: all 8 `results.*.json` present, each passed=75/total=75/failed=0; the 2062500 correction is in test_05_penalties.py:133; no .py source file in implementation/, test_suite/, or test_helpers/ is newer than the sweep results (no post-sweep edits).

## Step 8: Finalize PRD — 2026-10-02T22:30:00.000Z

Zero-edit outcome confirmed. All verification is complete.

## Summary

**Output**: `workspace/PRD_FINALIZED.md` — **byte-identical copy** of PRD.md.

- Line counts: PRD.md 290 lines, PRD_FINALIZED.md 290 lines, 0% delta.
- `diff -q` output: no differences reported (files are identical).

**Zero-edit justification, per diff item:**

- **test_suite/ fix — `test_05_penalties.py::test_penalty_points_tiered_multi_input_total` (expected `points_total` 90→85, `proposed_penalty_cents` 2250000→2062500).** Verified this reveals NO PRD silence and NO PRD/impl mismatch; the PRD already uniquely derives the corrected values:
  - PRD §3.4 (PRD.md:159) pins every factor table verbatim: "25 for MODERATE", "15 for REASONABLY_LIKELY", "20 for SERIOUS", "5 for two through five persons", "a 15-point surcharge" for S&S, history "0 points for up to five such citations", size "5 from 50,000 up to 499,999". Test inputs (MODERATE, REASONABLY_LIKELY, SERIOUS, persons_affected=3, S&S=true, fresh mine → history 0, tonnage=120,000) yield exactly 25+15+20+5+15+0+5 = **85**.
  - PRD §3.4 (PRD.md:161) pins the marginal tier conversion verbatim: "the first twenty points at 11,250 cents each, the next forty points (points 21 through 60) at 22,500 cents each, the following forty (points 61 through 100) at 37,500 cents each". For 85 points: 20×11,250 + 40×22,500 + 25×37,500 = 225,000 + 900,000 + 937,500 = **2,062,500** cents. The old 2,250,000 expectation equals the 90-point conversion (30 third-tier points), confirming the source test's arithmetic slip, not a spec gap.
  - Impl matches the PRD exactly: factor tables in `implementation/constants.py:42-66` (NEGLIGENCE_POINTS, LIKELIHOOD_POINTS, SEVERITY_POINTS, SS_SURCHARGE=15, HISTORY_BANDS, SIZE_BANDS); `implementation/services_penalty.py:36-42` (`persons_points(3)`→5), `:52-56` (`size_points(120000)`→5 via SIZE_BANDS), `:59-89` (`compute_points_total` sums all seven factors, excluding the new citation and VACATED ones from history), `:92-97` (`tiered_gross_cents(85)` = 2,062,500), `:128-145` (proposed variant runs steps 1, 2, 4 — no good-faith), with issuance-time computation wired at `implementation/routes_citations.py:101,114`. Floor check: S&S CITATION floor 120,000 < 2,062,500 → `statutory_floor_applied` False, matching both PRD ("the greater of the computed net and the floor") and the test.
- No other diff items exist (no test deletions, no test_helpers/ fixes, no implementation/ fixes).

Since the only Step 7 change corrected a test-side arithmetic error against a PRD that already uniquely determined the behavior, and the implementation was PRD-faithful, no PRD edit is warranted. No per-edit search log applies (zero edits made).

Orchestrator verification: `diff -q workspace/PRD.md workspace/PRD_FINALIZED.md` → byte-identical (290/290 lines); no implementation/ source file is newer than the Step 7 sweep results (Step 8 touched nothing outside workspace/PRD_FINALIZED.md).

## Step 9: Complete PRD — 2026-10-02T23:10:00.000Z

All 13 edits landed as in-paragraph revisions (26 diff lines = 13 replaced paragraphs; line count unchanged). The work is complete. Final summary:

## Output
- **Source**: `workspace/PRD_FINALIZED.md` — 290 lines, 56,916 chars
- **Produced**: `workspace/PRD_COMPLETED.md` — 290 lines, 58,568 chars (char-delta **+1,652**; 13 paragraphs touched, no sections added/removed)

**Counts**: 12 ambiguity-pins, 1 mismatch-revision.

## Changes (one bullet each)
- §2.1 — revise — **mismatch** — "All six roles may read the business surface" → "The five business roles (all but PublicReader)". The sentence contradicted §2.1's own explicit PublicReader restriction and §4's per-endpoint table (5 roles on every business GET); the impl (validate.py `BUSINESS_READ_ROLES`, routes_accidents.py:153 `ALL_ROLES` only on public-report) follows the specific pins. The "all six" reading is self-contradictory in-document, so the specific reading stands.
- §2.3 — insert — ambiguity — ties on `created_at` retain creation (insertion) order — envelope.py:76 (sorts by `(created_at, _seq)`).
- §2.4 — revise — ambiguity — `created_at`/`updated_at` stamped from the logical clock; `version` starts at 1 — store.py:42-45 (tests confirmed logical-clock sourcing; version start deliberately unpinned test-side, impl uses 1).
- §2.4 — revise — ambiguity — clock endpoint is a set-to operation (no monotonicity constraint) answering 200 with `data.current_utc` — app.py:60-77.
- §2.5 tier 4 — revise — ambiguity — added `inspection_id` to the body-FK set; each endpoint resolves its keys in payload-narrative order (citation issuance: `inspection_id` before `mine_id`) — routes_citations.py:69-70, routes_idos.py:30-33.
- §3.2 — insert — ambiguity — cycle exclusivity check evaluated before geometry within tier 11; double violation → `ERR_CYCLE_OPEN_EXISTS` — routes_cycles.py:24-27.
- §3.3 — insert — ambiguity — `cycle_id`/`accident_id` resolved for existence only (no same-mine cross-check); crediting driven by the inspection's own mine — routes_inspections.py:118-121, 236.
- §3.4 — insert — ambiguity — `abatement_note`/`justification`/`verification_note` are required request annotations, validated for presence, not persisted — routes_citations.py:161,175,196 (no such fields in serialize.py's citation).
- §3.4 — revise — ambiguity — `good_faith_applied` true only when the discount applied AND the floor did not overwrite the discounted net — services_penalty.py:171.
- §3.4 — insert — ambiguity — `significant_and_substantial` list filter encoded as query strings `true`/`false`, else `ERR_INVALID_REQUEST` — routes_citations.py:143-154.
- §3.5 — insert — ambiguity — POV_FINAL auto-IDO carries the fixed hazard description `AUTO-ISSUED: S&S citation at a POV_FINAL mine` — constants.py:137, routes_citations.py:117-118.
- §3.6 — revise — ambiguity — MODIFIED: `good_faith_applied` false, `statutory_floor_applied` = floor exceeded supplied amount; VACATED: zero cents with both flags false — services_penalty.py:176-190.
- §3.7 — insert — ambiguity — a rejected POV notice (posture or score) creates no `POVScreening` record — routes_pov.py:67-78 (raise precedes `_new_screening`).

## IMPL BUGS
**None found.** Every PRD-pinned rule checked has a matching impl behavior; every divergence candidate resolved to genuine PRD silence (pinned above) or PRD self-contradiction (the one revision).

## Targeted-sweep results
1. **Prose-only uniqueness** — only `badge_number` (§3.1): enforced at create via store scan → `ERR_INVALID_REQUEST` (routes_registry.py:110-111). No inspector update endpoint exists in §4 or impl, so there is no second path to enforce. No other uniqueness declarations. Clean.
2. **Nullable-field reads** — enumerated all nullable fields (auto-IDO/system-citation `inspection_id`/`issued_by_inspector_id`, pre-event timestamps, `terminated_at`, `next_revision_due_at`, contest decision fields, accident report fields, `final_penalty_cents`) and walked every read: serializers None-guard (`_dom`/`_date`/`_sys`), list filters guard (`x.get(p) is not None`), SOD comparison against a None issuer is safe (None ≠ uid string), `good_faith_eligible` guards `verified_at`, clock-set flip guards `next_revision_due_at`, `assert_issuable` guards `terminated_at`. No crash path on PRD-legal states.
3. **"recording X" vs "may carry"** — every "records X as/in `<field>`" claim persists (filed_by_operator_id, issued/verified_by, supersedes_plan_id, ss_citation_count, points_total, both flags). The three notes are "with the request"-style annotations with no named field and no serializer slot → adjudicated as carry, pinned in §3.4.
4. **Dead checks** — all 30 catalog error_ids are raised on reachable paths; every raised id exists in errors.py (`ERR_INTERNAL` is the defined 500 catch-all, no catalog KeyError possible); every guarded field has a writer (pov_status←screening/notice, production_status←cascades, abatement_extended←extend, next_revision_due_at←approve, etc.). No dead or orphaned checks.
5. **Cascade completeness** — IDO halt/suspend on both manual (routes_idos.py:52) and auto (routes_citations.py:117) issuance via services_ido.halt_cascade; resume only on last-order terminate (services_ido.py:58-77); POV_FINAL auto-IDO; late-report auto-citation (routes_accidents.py:100-101); REVISION_DUE flip on clock-set (app.py:69-76); delinquent-first crediting + CURED (services_cycles.py:44-81); accident REPORTED→UNDER_INVESTIGATION on AI start; contest file/decide/withdraw propagation to citation axis + assessment; plan supersede + mine version bump. All PRD-stated members present.
6. **Calculation literals** — recomputed from PRD prose and matched impl: 15-pt repeat example → 168,750 ×1.15 = 194,062.5 → half-up 194,063; discount round-half-up(19,406.3)=19,406 → net **174,657** ✓; floor raise 5-pt → 60,000 ✓; tiers 85-pt → 2,062,500 ✓; abatement base 30/15/5/1 ✓; extension ceil-half (base+1)//2 → 15/8/3/1 ✓; POV ≥8 threshold, 2/1/5 weights, 365-day strict-after window ✓; 730-day history window exclusive-open/inclusive-close ✓; 90/180 inclusive-day geometry ✓; 900s/7200s strict-greater late report ✓; contest 30-day inclusive vs finalize strictly-later ✓.

No tests were run and no implementation/test files were modified, per instructions.

Orchestrator adjudication of the single mismatch-revision (§2.1 "all six roles" → "five business roles"): EXONERATED — the original sentence directly contradicts the same section's own PublicReader restriction and the §4 per-endpoint table (PRD self-contradiction); the revision preserves the more specific stated rule and matches impl. Orchestrator verification: PRD_COMPLETED.md = 290 lines, 13 paragraph-level diffs matching the report; no implementation/, test_suite/, or test_helpers/ source file is newer than the Step 7 sweep (no re-sweep required); all 8 results.*.json evidence files present. Zero impl bugs → no Step 9b fix-and-re-sweep needed.
