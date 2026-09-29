# Worklog — task_2791_community_health_needs_assessment_implementation

## Step 1: Create task directory — 2026-09-04T21:55:20.869Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2791_community_health_needs_assessment_implementation/` and its `workspace/` subdirectory. Output path was pre-assigned by the caller (index fixed by scenario number 2791); no index scan performed, no other task directory created.

## Step 2: Generate scaffold — 2026-09-04T23:15:30.000Z

All three scaffold artifacts are complete and the lint is clean.

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints declared:    62
  §1.1 entities declared:     13
  §1.8 instances scanned:     25
  §1.9 instances scanned:     56
  Calls scanned (§1.8+§1.9):  1150
```

### Files
| file | lines | bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 3197 | 163306 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2375 | 165389 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3669 | 247755 |

### SCAFFOLD.yaml (§1.0–§1.7)
- 13 entities, 12 state machines, 2 `concurrency_rules`, 13 calculations, 47 validation rules, **62 endpoints** (33 POST / 29 GET), 56 errors, 6 roles, `api_prefix: "/"`.
- `complexity_profile`: archetype `compliance_audit` / `multi_party_negotiation`, `entity_topology: graph`, `state_machine_shape: posture_driven`, `role_model: segregation_of_duties`, `consistency_model: immediate`, layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation, rate_threshold_triggers.
- Contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`; the "harder than expert level" directive line is not present anywhere in the three files.

### §1.8 — 9 rule ids / 25 instances
`dual_variant_calc` 2, `combinatorial_formula` 3, `non_linear_state_machine` 3, `transitive_cascade` 3, `priority_pair_validation_conflict` 3, `boundary_precision_check` 3, `cross_entity_state_dependency` 3, `resource_temporal_overlap` 2, `compensating_invariant` 3.

### §1.9 — 9 sections / 80 instances (56 with full `test_recipe`, 24 `excluded_because` stubs)
entities 11 (11 real), state_machines 16 (8 real + 8 stubs), calculations 14 (5 + 9), validations 10 (5 + 5), endpoints 5 (5 real), errors 10 (10 real), rbac 6 (6 real), cross_cutting_complexity_layers 6 (4 + 2), consistency_model 2 (2 real).

### Key findings from the §1.5 audit pass
- The lint's FK reverse-reachability check only recognises sub-resource GETs whose path param is literally `{id}`, so three FKs (`IndicatorDataPoint.indicator_id`, `StrategyObjective.strategy_id`, `ProgressEvaluation.cycle_id`) failed despite having `/health-indicators/{indicator_id}/data-points`-style lists. Resolved at ladder rung 2 by adding three filtered collection GETs — `GET /indicator-data-points`, `GET /strategy-objectives`, `GET /progress-evaluations` (endpoint count 59 → 62). `PublicViewer` was deliberately kept off the new global evaluation list so its read surface stays exactly four endpoints.
- Because `as:` must be a declared role of the endpoint, ERR_UNAUTHENTICATED and cross-role ERR_UNAUTHORIZED denials cannot be expressed as structured calls; those instances issue a valid-role baseline call and state the header/role variants as `assert` prose. Conditional denials (advance actor by `to_status`, sign side by role, SoD by `X-User-ID`) *are* fully structural.
- Design consequence worth flagging for the PRD/test phases: FILED ⇒ posture FROZEN blocks evaluation publication, so an ANNUAL ProgressEvaluation must be published *before* `file-return`, otherwise `ERR_ANNUAL_REPORT_MISSING` on advance-to-CLOSED is an unrecoverable dead end. This is captured deliberately in `filing_sequence_requires_locked_report_then_published_annual_evaluation` (errors) with the successful ordering in `cycle_close_out_cascade_finalizes_active_and_revised_objectives` (state_machines).
- All 56 §1.6 error ids are referenced by real (non-comment) design content; name uniqueness across both design files verified; every stub's cited `difficulty_instance` resolves to an existing §1.8 instance name; no non-schema keys remain.

## Step 3: Copy shared files — 2026-09-04T23:16:42.297Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T23:37:55.694Z

**Output:** `workspace/PRD.md` — **477 lines**, 104,735 bytes. Written in 10 chunked `cat >> ... <<'EOF'` appends (no single giant Write); no other file was created or modified.

**Withheld files honored:** `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced. No sibling task directory was accessed.

**Section list**
- §1 Introduction
- §2 Global Specifications & System-Wide Principles — 2.1 Role-Based Access Control · 2.2 API Response Structure (fixed block, byte-verbatim) · 2.3 Pagination and List Filtering · 2.4 Cycle Posture · 2.5 Record Identity, Timestamps and Versioning · 2.6 Left-to-Right Resolution of Path and Body References · 2.7 Stale-Read Protection · 2.8 Segregation of Duties · 2.9 Cents, Basis Points, Ratios and Rounding · 2.10 The Logical Clock and Calendar Windows · 2.11 Order of Rule Evaluation (24-rung ladder)
- §3 Business Logic & Workflows — 3.1 Opening a Cycle and Its Phases · 3.2 Health Indicators and Observations · 3.3 Facilitators, Sessions and Concern Ratings · 3.4 Scoring, Selecting, Deferring · 3.5 Strategies and Objectives · 3.6 Partners, Pledges and Commitments · 3.7 Board Review, Adoption and the Three-Link Cascade · 3.8 Execution Tracking, Progress Reporting, Mid-Cycle Adjustment · 3.9 Community Benefit Accounting, Publication, Filing, Close-Out
- §4 Endpoint Definitions (62-row table)
- §5 Error Code Catalogue (56-row table) — document ends here, no audit footer

**Endpoint coverage: 62 / 62.** Programmatic set-equality on (method, path) against the scaffold's §1.5 list: exact match, zero missing, zero extras. Authorized-role sets also compared per row: **0 mismatches** across all 62.

**Hard Contracts (all PASS, verified mechanically)**
1. **Field-Name Coverage** — 154 required identifiers (entity fields + endpoint inputs + 13 path params, incl. both `occ_field`s): **0 missing**. Also reverse-checked: every ALL-CAPS literal used in PRD backticks exists in the scaffold — **0 invented enum members**.
2. **Rule Coverage** — all 56 error IDs appear in §2/§3 prose *before* §5; all 51 state-machine transition states present; all 13 calculations expressed; all rule-block numeric constants present; §5 error IDs and HTTP statuses match the scaffold in order and value. Anti-pattern scans clean: no fuzzy words, no forbidden OCC framings ("simultaneously", "first-writer-wins", "race winner"), no pseudocode operators (`==`, `>=`, `+=`), no `round_half_up(`/`min(`/`sum(`.
3. **§3 Path Purity** — 1,048 inline code spans in §3: **zero** paths in backticks, **zero** bare HTTP methods anywhere in §3, **zero** method+path combinations.

**Truncation guard:** final line is a complete §5 table row, `| ERR_OBJECTIVE_PROGRESS_MISSING | 409 |`, the 56th and last error — a genuine end-of-document boundary, not a mid-sentence cut. Orchestrator independently re-verified with `wc -l` (477) and `tail -8`.

**Two scaffold inconsistencies found and resolved (passed forward to Steps 5/7):**
1. **FROZEN gate on observation retraction.** `validations[priority=9]` exempts the void endpoint from the FROZEN gate, but the `IndicatorDataPoint` `ACTIVE → VOID` transition's own preconditions state `posture != FROZEN, else ERR_CYCLE_FROZEN`, and its `note` says the exemption is from **RESTRICTED** only. The transition is the more specific and self-consistent authority, so the PRD states: retraction is permitted while `RESTRICTED`, blocked when `FROZEN`. The only never-gated operation is the cycle phase advance itself (which is what lets a `FILED` cycle advance to `CLOSED`).
2. **`ExpensePosting.status` enum.** Draft had `VOIDED`; the scaffold enum is `POSTED | VOID`. Corrected to `VOID`.

Also fixed during verification: scoring weights now state the decimals explicitly (`0.25` each for `EQUAL_WEIGHT`; `0.20`/`0.30`/`0.35`/`0.15` for `COMMUNITY_WEIGHTED`); a miscounted "Three creation endpoints" → "Seven"; a stray `fiscal_year` filter claim on the reports list row; and missing blank lines before 8 headings at chunk seams.

Orchestrator leak check on PRD.md: zero matches for "harder than expert", "scaffold_difficulty", "scaffold_corner", "test_recipe".

## Step 6: Generate implementation — 2026-09-05T00:08:30.000Z

Implementation complete. Full end-to-end smoke run passes.

### Files created — `workspace/implementation/`

| File | Lines |
|---|---|
| `start.sh` (executable, guarded pip install, `exec python3 app.py`) | 10 |
| `requirements.txt` | 1 |
| `app.py` (blueprint registration, `ApiError`/404/405/500 handlers, `0.0.0.0:$PORT`) | 71 |
| `consts.py` (roles, header names, every enum, numeric constants, cascade reason literals) | 135 |
| `core.py` (Store, logical clock, error catalogue → HTTP map, hand-written Decimal-preserving `dumps`, envelope helpers, auth, validators, pagination) | 576 |
| `derive.py` (lookups, reachability, posture gates, all recomputations, scoring, attainment, the four cascades) | 514 |
| `routes_cycles.py` | 249 |
| `routes_indicators.py` | 150 |
| `routes_parties.py` | 42 |
| `routes_interviews.py` | 153 |
| `routes_candidates.py` | 158 |
| `routes_strategies.py` | 248 |
| `routes_partnerships.py` | 259 |
| `routes_reports.py` | 196 |
| `routes_evaluations.py` (4 evaluation endpoints + `POST /_clock/set_current_utc`) | 119 |
| **total** | **2881** |

All 13 `.py` files `python3 -m py_compile` clean; `__pycache__` removed.

### Endpoint coverage: 62 / 62
Verified programmatically by walking `app.url_map` — the 62 concrete method+path pairs registered are an exact one-for-one match with the PRD §4 endpoint table (including the cycle-scoped `GET /assessment-cycles/{cycle_id}/progress-evaluations` and the logical-clock endpoint). Every body-field name was cross-checked against SCAFFOLD.yaml's `input:` lists and matches exactly.

### Smoke test: PASS
Booted via `bash start.sh` on port 32502, then drove a complete lifecycle (57 assertions, every one on the expected status code), killed afterwards by its specific PID — no pattern kill:

- clock set → cycle create (`0.4500` echoed as a literal 4-place JSON number) → 401 on bad role → 404 `ERR_CYCLE_NOT_FOUND`
- DATA_COLLECTION → indicator + 3 observations → `severity_score 75.00`, `disparity_ratio 1.78`, `data_state SUFFICIENT`
- INPUT_GATHERING → parties → interview, second interview rejected `ERR_FACILITATOR_WINDOW_CONFLICT` (30-min buffer) → complete
- PRIORITIZATION → candidate → score `COMMUNITY_WEIGHTED` = `74.00` from 75.00/78.00/100.00/80.00 → select
- STRATEGY_DEVELOPMENT → strategy (OCC accepted; a bad token gave 412 `ERR_STALE_CANDIDATE_VERSION`) → objective → agreement → both signatures → `EXECUTED`/`PLEDGED` → commitment `PENDING` → submit
- BOARD_REVIEW → `ADOPT` → three-link adoption cascade verified: cycle `ADOPTED`, strategy `APPROVED`/`ON_TRACK`, `budget_available_cents 4000000`
- report open → charge-basis posting `valued_cents 450000` at ratio `0.4500`, report `grand_total 472500` at tier-1 overhead `0.05`; `ERR_POSTING_BASIS_MISMATCH` and `ERR_SEGREGATION_OF_DUTIES` both fire → finalize revalues at `0.4200` → `420000`/`441000`, `LOCKED`
- evaluations: duplicate rejected `ERR_DUPLICATE_EVALUATION_PERIOD`; ANNUAL publish bumps `annual_report_count`; MID_CYCLE publish revises the 25.00%-attainment objective (`objectives_revised_count 1`) and moves its strategy `ON_TRACK → BEHIND`
- publish → file-return → `FILED`, `posture FROZEN`, a subsequent child write refused `ERR_CYCLE_FROZEN` → advance `CLOSED` → close-out cascade verified: strategy `CLOSED_OUT`, objective `FINALIZED_NOT_MET`

Wire format confirmed on raw bytes: all `_cents` fields are integer JSON numbers, ratios keep their declared decimal places (`0.4500`, `0.4200`), pagination lives in `meta` as `limit`/`offset`/`total_count`/`has_more`, and every timestamp is `YYYY-MM-DDTHH:MM:SS.mmmZ` off the logical clock (default `2026-08-01T00:00:00Z`, never wall-clock). No entity is seeded at startup.

### One deliberate ordering choice flagged by the generator
On `POST /implementation-strategies/{strategy_id}/execution-status` it evaluates `ERR_STRATEGY_NOT_APPROVED` **before** execution-axis legality (`ERR_INVALID_STATE`), i.e. approval-axis first. Rationale: §2.11 rung 12 describes `ERR_STRATEGY_NOT_APPROVED` as a *cross-entity* prerequisite (the expense-posting `strategy_id` case), whereas on this endpoint the approval axis is the target row's own state and so belongs at rung 11; §3.8's prose also states the approval requirement first. Strict 11-before-12 would render the error nearly unreachable here. Two other within-rung-11 orderings follow §2.11's own listing order: `ERR_STRATEGY_LOCKED` precedes the creation-time parent-phase gate on both `POST .../objectives` and `POST /resource-commitments`.

Where SCAFFOLD.yaml and PRD.md disagreed, the PRD won — activation is neutral on both conserved quantities (§3.7), and data-point void is FROZEN-gated but RESTRICTED-exempt (§2.4/§3.2), contradicting the scaffold's exemption list in both cases.

## Step 5: Generate unit tests — 2026-09-05T01:07:00.000Z

Stage 2 complete. Full test infrastructure and suite on disk, verified.

### Files created (all at TASK ROOT, nothing under `workspace/` — orchestrator re-verified)

`test_helpers/` — 2,587 lines
| file | lines |
|---|---|
| `__init__.py` | 46 |
| `api_client.py` | 482 |
| `api_errors.py` | 134 |
| `assertions.py` | 391 |
| `constants.py` | 141 |
| `factories.py` | 301 |
| `fixtures.py` | 527 |
| `test_users.py` | 78 |
| `types.py` | 487 |

`test_suite/` — 6,041 lines, **158 tests**
| file | lines | tests |
|---|---|---|
| `conftest.py` | 52 | – |
| `test_01_entities_and_defaults.py` | 589 | 18 |
| `test_02_state_machines.py` | 585 | 16 |
| `test_03_calculations.py` | 364 | 10 |
| `test_04_validations.py` | 376 | 10 |
| `test_05_endpoints.py` | 362 | 10 |
| `test_06_errors.py` | 644 | 17 |
| `test_07_rbac.py` | 489 | 11 |
| `test_08_cross_cutting.py` | 389 | 8 |
| `test_09_consistency.py` | 206 | 4 |
| `test_10_dual_variant_and_formulas.py` | 305 | 11 |
| `test_11_state_machines_nonlinear.py` | 232 | 6 |
| `test_12_transitive_cascades.py` | 291 | 8 |
| `test_13_validation_precedence.py` | 190 | 6 |
| `test_14_boundary_precision.py` | 222 | 6 |
| `test_15_cross_entity_state.py` | 245 | 6 |
| `test_16_temporal_overlap.py` | 270 | 5 |
| `test_17_compensating_invariants.py` | 230 | 6 |

### Coverage — every non-stub instance translated, nothing skipped
Queue A (Difficulty, §1.8) — 25/25 instances, 54 tests, every instance ≥2 tests:
dual_variant_calc 2→5, combinatorial_formula 3→6, non_linear_state_machine 3→6, transitive_cascade 3→8, priority_pair_validation_conflict 3→6, boundary_precision_check 3→6, cross_entity_state_dependency 3→6, resource_temporal_overlap 2→5, compensating_invariant 3→6.

Queue B (Corner, §1.9) — 56/56 non-stub instances, 104 tests, every instance ≥1 test:
entities 11→18, state_machines 8→16, calculations 5→10, validations 5→10, endpoints 5→10, errors 10→17, rbac 6→11, cross_cutting_complexity_layers 4→8, consistency_model 2→4. The 24 `excluded_because:` stubs (8 state_machines, 9 calculations, 5 validations, 2 cross_cutting) were **not** translated.

### Verification (final sweep)
- `python3 -m py_compile` on all 27 files: clean.
- `pytest --collect-only`: **158 tests collected**, 0 errors.
- Tag audit: `INVALID TAGS: []`, `STUBS TRANSLATED: []`, `UNDER-COVERED: 0`, `TOTAL TESTS TAGGED: 158` (= collected count, so every test carries exactly one `Design:` line).
- Quote audit: 212 PRD quotes checked, `ALL QUOTES VERBATIM`.
- Import/attribute audit: `CLEAN`.
- `__pycache__`/`.pytest_cache` removed; `worklog.md` untouched; `workspace/implementation/` never read.

### Design-index vs PRD conflicts resolved (PRD wins)
1. Field-name typos → PRD spellings `financial_assistance_cents`, `subsidized_services_cents`, `grand_total_cents` (design writes `*_total_cents`).
2. Non-existent recipe fields (`committed_funding_cents`, `severity_snapshot`, `disparity_snapshot`, `latest_actual_value`, `reported_at`, `grand_total_benefit_cents`) → real PRD fields (`budget_available_cents`/`funded_cents`, `severity_input`, `disparity_points`, `actual_value`, `as_of_date`, `grand_total_cents`).
3. Invalid enum literals in recipes (`sector: "HOUSING"`, `"FOOD_SECURITY"`, `"NEIGHBORHOOD_GROUP"`, `source_type: "SURVEY"`) → valid members, except `entities` instance 9 where `ERR_VALIDATION` *is* the assertion.
4. `entities/input_type_and_range_constraints...`: the three-decimal-ratio sub-assertion is not uniquely derivable from the PRD → that sub-assertion alone dropped.
5. `errors/filing_sequence_...` trigger call 8 (data-point void returning 200 on a FILED cycle) contradicts the FROZEN posture → dropped; the test stops at the `ERR_CYCLE_FROZEN` evaluation create.
6. `rbac/paired_report_steps_...` trigger call 4 (finalize succeeding after the only posting was voided) contradicts `ERR_REPORT_EMPTY` → split into two tests sharing the tag, the finalize test keeping a live posting.
7. Design asserts posting `valuation_basis_at_posting == FINAL` after finalize; PRD freezes it at posting time → tests assert `PROVISIONAL` (report-level `valuation_basis == FINAL` is asserted, per §3.9).
8. PRD internal contradiction — §3.9 prose "three published annual evaluations" vs §3.1 "at least one" → §3.1 governs; tests use ≥1.
9. Recipes omitting required setup calls had the minimum legal setup reconstructed through the fixture tiers.

Fixture hygiene as mandated: all money emitted as integer-cent JSON numbers; ISO-8601 comparison goes through `canonical_iso`/`same_instant` in `api_client.py` so sub-second precision width cannot cause a false failure.

## Step 7: Run tests and iterate — 2026-09-05T01:37:30.000Z

**Iterations run:** 4 sweeps (8 parallel rounds each).

**Tests deleted:** none. Every failure traced to a fixture bug or a genuine implementation defect; no PRD-silent or non-uniquely-derivable assertion was found. No `pytest.mark.skip`/`xfail` anywhere; 158 tests still collected.

**Fixes applied to `test_helpers/`**
- `test_helpers/types.py` — replaced `from typing_extensions import TypedDict` with `typing.TypedDict`. `typing_extensions` is absent from the runner's environment, so `conftest.py` raised `ImportError` and all 8 rounds collected 0 tests (`errors: 1`).
- `test_helpers/constants.py` — `PRIOR_YEAR_RATIO` / `AUDITED_RATIO` changed from floats `0.32` / `0.28` to `Decimal("0.3200")` / `Decimal("0.2800")`, plus a new `ALT_PRIOR_YEAR_RATIO = Decimal("0.3000")`. PRD §2.9 states verbatim that a cost-to-charge ratio "with more **or fewer** than four decimal places is an `ERR_VALIDATION` failure", so the fixture was sending a request the PRD-faithful implementation correctly rejected. **Numeric values are unchanged**, so every hard-coded expected valuation (322, 395061, 1245061, 622222, …) stayed valid.
- `test_helpers/api_client.py` — added `encode_body()` (a `Decimal`-aware JSON encoder using a sentinel-substitution pass) and an `ApiClient._request` override that serialises write bodies with `data=` instead of `json=`. `json.dumps(0.32)` emits `0.32`; a float literally cannot carry the trailing zeros the PRD demands, so the ratio had to reach the wire as exact text `0.3200`. The implementation already parses bodies with `parse_float=Decimal`, so it sees the true four-place precision.
- `test_suite/test_01_entities_and_defaults.py:329` — the second cycle's inline `prior_year_cost_to_charge_ratio=0.3` (one decimal place) now uses `C.ALT_PRIOR_YEAR_RATIO`.

**Fixes applied to `test_suite/`**
- `test_suite/test_04_validations.py` (2 call sites, the two evidence-window edge tests) — `validate_success(api.set_clock(...))` asserted HTTP 200, but PRD §2.10 and §4 both state the logical-clock capability "returns HTTP 204 with no body". Changed to assert `status_code == 204`. This makes the assertion *more* faithful to PRD, not less.

**Fixes applied to `implementation/`**
- `workspace/implementation/derive.py`, `value_posting()` — removed the line rewriting `post["valuation_basis_at_posting"] = rep["valuation_basis"]`. `value_posting` is called both on posting creation and on finalization's revaluation, so finalization was flipping the field from `PROVISIONAL` to `FINAL`. PRD §3.9: "Every posting also **freezes** `valuation_basis_at_posting` to the report's `valuation_basis` as it stood at the moment of posting, so a reader can tell which numbers were provisional when they were entered", and the finalization paragraph names only `valued_cents` and `ratio_applied` as revalued. The create path (`routes_reports.py:143`) already stamps the field, so the frozen value is now written exactly once.

**Final sweep (all 8 rounds, 281s each):**

| Round | Passed/Total | Failed | Errors | Skipped |
|---|---|---|---|---|
| 1 | 158/158 | 0 | 0 | 0 |
| 2 | 158/158 | 0 | 0 | 0 |
| 3 | 158/158 | 0 | 0 | 0 |
| 4 | 158/158 | 0 | 0 | 0 |
| 5 | 158/158 | 0 | 0 | 0 |
| 6 | 158/158 | 0 | 0 | 0 |
| 7 | 158/158 | 0 | 0 | 0 |
| 8 | 158/158 | 0 | 0 | 0 |

No flakiness: the union of failing tests across all 8 rounds is empty. Storage remains in-memory only; nothing was seeded, no endpoint or response field was added, and `worklog.md` was not touched.

**Orchestrator independent verification:** read all 8 `workspace/implementation/results.*.json` directly — every file reports `passed == total == 158`. (Baseline sweep at 01:16 had shown a consistent 157/158, i.e. the single deterministic `valuation_basis_at_posting` defect above.)

## Step 8: Finalize PRD — 2026-09-05T01:48:10.000Z

`PRD_FINALIZED.md` is written. One edit was warranted; the other four Step 7 items had no PRD analogue or were cases where the PRD already determined the behavior and Step 7 moved the *fixture/impl* toward the PRD rather than exposing a gap.

**Line counts:** PRD.md 477 lines / 104,735 bytes → PRD_FINALIZED.md 477 lines / 105,379 bytes. Line delta 0 (0.0%); byte delta +644 (+0.61%). Exactly one line changed (§2.9, line 140).

**Changes**
- §2.9 — revise (in-line extension of the cost-to-charge-ratio sentence) — pins that a decimal-place count is read from the JSON numeric literal as transmitted (trailing zeros significant: `0.3200` accepted, `0.32` and bare `1` rejected under the exactly-four rule; fewer-than-limit literals, integers included, accepted under an at-most rule), and that such a field must arrive as a JSON number, not a quoted string — `implementation/core.py:401` (`_places`), `core.py:408` (`_as_decimal`), `core.py:424` (`v_num`), `core.py:~300` (`body_or_empty`, `json.loads(..., parse_float=Decimal)`), `routes_cycles.py:53`, `routes_reports.py:77`.

**Per-edit pre-edit search log**

Edit 1 (§2.9 decimal-place mechanism)
- (a) Subject: client-supplied non-integer numeric validation — how "exactly four" / "at most N" decimal places is counted, and which JSON types are accepted.
- (b) Enumerated and read: `core.py` `body_or_empty` (parses every request body with `parse_float=Decimal`, so literal scale survives), `_as_decimal` (accepts `int` and `Decimal`, rejects `bool`, `float`-as-string, and `str` → `ERR_VALIDATION`), `_places` (scale from `Decimal.as_tuple().exponent`), `v_num` (`exact_places` vs `places`), plus every `v_num` callsite found by grep: `routes_cycles.py:53` (`prior_year_cost_to_charge_ratio`, exact 4), `routes_reports.py:77` (`audited_cost_to_charge_ratio`, exact 4), `routes_indicators.py:23` (`benchmark_value`, ≤4), `routes_indicators.py:74` (observation `value`, ≤4), `routes_strategies.py:112,113` (`baseline_value`, `target_value`, ≤4), `routes_strategies.py:172` (`actual_value`, ≤4), `routes_candidates.py:22` (`hospital_capacity_score`, ≤2), `routes_partnerships.py:24` (`shared_accountability_pct`, ≤2). Also checked `v_int` (integer-cents fields reject any non-`int`, e.g. `100.00`) so the new sentence stays clear of money fields.
- (c) Adjustment: first draft said integer literals are rejected, full stop — false for the at-most fields (`hospital_capacity_score: 40` is accepted at `routes_candidates.py:22`). Re-scoped into two explicit clauses (exactly-four vs at-most). Also deliberately phrased as "wherever this document constrains a field's decimal places" rather than enumerating fields, because `actual_value` is validated at ≤4 places by `routes_strategies.py:172` but is absent from §2.9's existing list — the generic phrasing avoids asserting that list is exhaustive in either direction.

**Items deliberately not patched**
- `test_helpers/types.py` `typing_extensions` → runner-environment import bug, no PRD analogue.
- `test_04_validations.py` `set_clock` 200→204 → §2.10 and §4 already state 204 with no body; `routes_evaluations.py:113-119` returns `no_content()`. Verbatim prose kept.
- `derive.py value_posting()` `valuation_basis_at_posting` removal → §3.9 already says the field is *frozen* at posting time and names only `valued_cents`/`ratio_applied` as revalued; the impl was fixed toward the PRD. Confirmed the only two `value_posting` callsites (`routes_reports.py:94` finalize, `:150` create) and that the field is stamped exactly once at `routes_reports.py:143`, so the existing wording is already accurate — no edit.

## Step 9: Complete PRD — 2026-09-05T02:22:40.000Z

Run as **three sequential module-partitioned passes** over one shared `PRD_COMPLETED.md` (pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 edited in place and were explicitly forbidden from re-copying). Partition: pass 1 = `app.py`/`consts.py`/`core.py`/`start.sh`; pass 2 = `derive.py`/`routes_cycles.py`/`routes_indicators.py`/`routes_parties.py`; pass 3 = `routes_interviews.py`/`routes_candidates.py`/`routes_strategies.py`/`routes_partnerships.py`/`routes_reports.py`/`routes_evaluations.py`.

**Totals: 51 edits — 39 ambiguity-pins, 12 mismatch-revisions.** Source `PRD_FINALIZED.md` 477 lines / 105,379 bytes → `PRD_COMPLETED.md` 479 lines / 122,986 bytes (+2 lines, +17,607 chars). Orchestrator verified the two files are NOT byte-identical (98 changed lines under diff) and that the document still ends at the real §5 catalogue boundary.

### Pass 1 — global mechanics (11 ambiguity-pins, 1 mismatch-revision)
- §2.1 — insert — ambiguity — header present but empty/whitespace-only counts as absent; role matched exactly and case-sensitively; any other non-empty `X-User-ID` accepted verbatim, never parsed — `core.py:326-337`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` plus exactly 20 upper-case-alphanumeric characters — `core.py:250-254`
- §2.2 — insert — ambiguity — `api_request_timestamp` read from the logical clock, not host wall time, so it repeats until the clock moves — `core.py:257-258`, `core.py:106-107`
- §2.3 — insert — ambiguity — non-integer/fractional `limit`/`offset` are `ERR_VALIDATION`; `offset` unbounded (past-the-end = empty page); empty-string parameter = omitted; undeclared query params ignored — `core.py:520-536`
- §2.3 — insert — ambiguity — identical `created_at` values are routine and ties break on internal storage sequence, reversed for the descending cycle list; that sequence is never a response field — `core.py:563-568`, `core.py:317`
- §2.3 — insert — ambiguity — empty collection returns empty `data` with `total_count` 0 / `has_more` false; state in-memory only, nothing seeded — `core.py:25-48`, `app.py:1-6`
- §2.3 — insert — ambiguity — filters are exact-equality and unvalidated against enums (unknown value ⇒ empty page, not `ERR_VALIDATION`); empty-string filter = omitted; only `fiscal_year` integer-coerced — `core.py:548-560`
- §2.5 — revise — **mismatch** — "increments by exactly 1 on every mutation" contradicted the once-per-record-per-request rule; now pins that a cascade touching one record at two links leaves `version` one higher, `updated_at` refreshed — `core.py:305-314` (observable in `derive.py:462-489`)
- §2.6 — insert — ambiguity — identifiers opaque: non-string/empty body ids fail at the shape rung, any non-empty string resolving to nothing is the dedicated NOT_FOUND code, no UUID-form check — `core.py:487-493`
- §2.6 — insert — ambiguity — an empty `concern_ratings` object passes the shape check — `core.py:496-512`
- §2.6 — insert — ambiguity — five shape conventions: undeclared body fields ignored; explicit `null` treated as absent; absent/empty/`null`/non-object body handling; booleans and `NaN`/`Infinity` never valid numbers; character-count string lengths with no trimming — `core.py:345-357,368-373,389-444,376-386`
- §2.9 — insert — ambiguity — outbound serialization emits numbers as JSON numeric literals at fixed scale with trailing zeros (`50.00`, `0.3200`), never quoted — `core.py:222-243`
- §2.10 — insert — ambiguity — accepted `to_iso8601` grammar: optional seconds and fraction, `T` or space separator, numeric offset converted to UTC, missing offset read as UTC, else `ERR_VALIDATION` — `core.py:55-83,477-484`
- §4 — insert — ambiguity — trailing slash accepted; unknown path ⇒ 404 `ERR_NOT_FOUND`, wrong method ⇒ 405 `ERR_METHOD_NOT_ALLOWED`, unhandled fault ⇒ 500 `ERR_INTERNAL`, none in the §5 catalogue, all decided before auth — `app.py:36,48-61`
- Cross-check: impl's `HTTP_FOR_ERROR` map is exactly the §5 catalogue — same 56 ids, same statuses, every id actually raised — so no catalogue edits needed.

### Pass 2 — derive + cycle/indicator/party routes (11 ambiguity-pins, 6 mismatch-revisions)
- §2.4 — revise — mismatch — "phase advance is the one operation posture never gates" was wrong: board action, publish and file-return are equally ungated (otherwise `BOARD_REVIEW`'s own `RESTRICTED` posture makes adoption unreachable) — `routes_cycles.py:123,167,206,225`
- §2.5 — insert — ambiguity — a recompute landing on the value already held is not a mutation (no `version`/`updated_at` bump) for party FTE, strategy budget/objective count, agreement funding, cycle counters/posture; indicator re-derivation and report re-aggregation are unconditional — `derive.py:186-193,236-271,306`
- §2.6 — revise — mismatch — corrected pass 1: required FKs use a plain non-empty-string check (untrimmed), so `" "` passes shape and returns `ERR_..._NOT_FOUND`; only the two *optional* FKs (`strategy_id` on a posting, `partnership_id` on a commitment) reject it — `routes_indicators.py:20` vs `routes_reports.py:112`, `routes_partnerships.py:161`
- §2.11 — revise — mismatch — party registration has no cycle and no gate; reduced to three `FROZEN`-only creation endpoints — `routes_parties.py:14-28`
- §3.1 — insert — ambiguity — new-cycle initial `public_availability_met` false and the nine null adoption/publication/filing fields — `routes_cycles.py:17-44`
- §3.1 — insert — ambiguity — `to_status` must be one of the ten cycle statuses; the actor refinement reads raw `to_status` before shape check and path resolution, so absent/unknown demands `CommunityBenefitOfficer` and malformed JSON beats `ERR_CYCLE_NOT_FOUND` on this endpoint — `routes_cycles.py:127-141`
- §3.1 — insert — ambiguity — close-out releases no commitment and only drives `active_objective_count` to 0 — `derive.py:500-517`
- §3.2 — insert — ambiguity — fresh indicator's `latest_overall_value`, `severity_score`, `disparity_ratio` all null — `routes_indicators.py:39-41`
- §3.2 — revise — mismatch — "1 to 60 characters in upper snake case" is not enforced; only length bounds are — `routes_indicators.py:72`
- §3.2 — revise — mismatch — indicator-name uniqueness is exact, case-sensitive, untrimmed, cycle-scoped — `routes_indicators.py:29-31`
- §3.2 — insert — ambiguity — `_newest` third tie-break: tie on both `collected_on` and `created_at` settled by storage sequence, latest-stored winning — `derive.py:196-199`
- §3.2 — insert — ambiguity — void-cascade link two leaves `scoring_variant` and `concern_input_dirty` as they stood — `derive.py:446-451`
- §3.5 — insert — ambiguity — `active_objective_count` counts objectives with `status` exactly `ACTIVE`, refreshed only by the adoption and close-out cascades, so a mid-cycle `ACTIVE`→`REVISED` objective stays counted — `derive.py:259-263`
- §3.7 — insert — ambiguity — `votes_for`/`votes_against` integers ≥ 0, no upper bound; `note` any-length string (empty allowed), validated then discarded, never persisted — `routes_cycles.py:172-176`
- §3.7 — insert — ambiguity — a `DEFER` leaves `adopted_at`, `adoption_board_user_id` and both `votes_*_at_adoption` null — `routes_cycles.py:185-192`
- §3.9 — insert — ambiguity — finalization's revaluation never rewrites `valuation_basis_at_posting` — `derive.py:300-303`
- §3.9 — insert — ambiguity — `public_url`, `public_comment_channel`, `return_form_id` required non-empty strings of unbounded length, never syntax-checked — `routes_cycles.py:211-212,230`
- §3.9 — revise — mismatch — "once its three published annual evaluations are on the record" → at least one published `ANNUAL` evaluation — `routes_cycles.py:146-149`
- Notable non-changes: `compute_posture`, reachability, severity/disparity/concern-index/composite/attainment formulas with round-then-clamp order, the evidence window, RESTRICTED-exempt retraction, the adoption cascade's three causal links, and all four advance readiness gates were already pinned uniquely.

### Pass 3 — remaining routes (17 ambiguity-pins, 5 mismatch-revisions)
- §2.6 — insert — ambiguity — the mandatory free-text `reason` family (interview cancel, candidate defer, agreement terminate, commitment release, observation retract, posting void) plus `selection_rationale` pinned as required strings ≥1 char, no upper bound, no trimming — `routes_interviews.py:140`, `routes_candidates.py:111,137`, `routes_partnerships.py:129,251`, `routes_reports.py:179`
- §2.7 — insert — ambiguity — both concurrency tokens are required JSON integers ≥ 0; non-integer/negative is rung-4 `ERR_VALIDATION` — `routes_strategies.py:21`, `routes_reports.py:113`
- §2.11 rung 12 — insert — mismatch — the ladder now records that execution-status change evaluates rung 12 before rung 11 — `routes_strategies.py:205`
- §2.11 — revise — mismatch — scoped the exhaustiveness claim to the foot of the ladder so it no longer contradicts the two pinned inversions — `routes_strategies.py:118,205`
- §3.3 — insert — ambiguity — interview `starts_at`/`ends_at` read under §2.10's grammar and echoed normalized to 3-digit UTC; exactly 240 minutes accepted — `routes_interviews.py:32-37`, `core.py:98`
- §3.3 — revise — ambiguity — `organization_name` uniqueness exact, case-sensitive, untrimmed — `routes_interviews.py:60`
- §3.4 — revise — ambiguity — candidate's `indicator_id` resolved for existence only, not required to share the cycle; `selection_rationale`/`defer_reason` added to the null-defaults list — `routes_candidates.py:25,42-43`
- §3.4 — insert — ambiguity — candidate-deferral supersession leaves `superseded_by_strategy_id` null, releases no commitment, moves neither conserved quantity, preserves score fields — `routes_candidates.py:151-156`
- §3.5 — insert — ambiguity — `strategy_count` only ever rises — `routes_strategies.py:63`
- §3.5 — insert — ambiguity — `target_date` grammar-checked only, past dates accepted — `routes_strategies.py:114`
- §3.5 — insert — mismatch — `ERR_STRATEGY_LOCKED` precedes the cycle-phase gate for both objectives and commitments — `routes_strategies.py:118`, `routes_partnerships.py:175`
- §3.6 — insert — ambiguity — signatory-side refinement read from raw body before `{agreement_id}` and before the enum check; unrecognized side clears rung 2 and fails at rung 4 — `routes_partnerships.py:79-88`
- §3.6 — revise — ambiguity — commitment's `partnership_id` resolved for existence only, no single-cycle requirement — `routes_partnerships.py:171`
- §3.8 — revise — ambiguity — `to_execution_state` enum-bounded; `execution_note` any length incl. empty, and omission/null leaves the prior note rather than clearing it — `routes_strategies.py:195-196,238-239`
- §3.8 — insert — mismatch — `ERR_STRATEGY_NOT_APPROVED` evaluated before execution-axis legality — `routes_strategies.py:205`
- §3.8 — insert — ambiguity — `NOT_STARTED`, `SUSPENDED_PENDING_REVIEW`, `CLOSED_OUT` are never legal destinations — `routes_strategies.py:223-224`
- §3.8 — insert — ambiguity — a move to `COMPLETED` releases nothing — `routes_strategies.py:242`
- §3.8 — revise — mismatch — a suspended strategy moved to `DISCONTINUED` also changes posture — `routes_strategies.py:242-247`
- §3.8 — revise — ambiguity — `actual_value` ≥ 0 at most 4 dp; `as_of_date` compared against nothing — `routes_strategies.py:172-173`
- §3.8 — revise — ambiguity — evaluation `period_year` not compared to the cycle; `findings_summary` optional non-empty string, null when omitted — `routes_evaluations.py:24-25`
- §3.8 — revise — ambiguity — evaluation `public_url` required non-empty, any length, no syntax check — `routes_evaluations.py:73`
- §3.9 — revise — ambiguity — report `fiscal_year` not compared to the cycle's — `routes_reports.py:21`
- §3.9 — insert — ambiguity — posting's `strategy_id` consults only the approval axis, no execution-state or same-cycle requirement — `routes_reports.py:125`
- §3.9 — revise — mismatch — finalization's revaluation bumps `version`/`updated_at` on every `POSTED` posting, cost-based rows included; `VOID` rows untouched — `routes_reports.py:93-95`

### Final artifact state
`workspace/` holds `INSTRUCTION.md`, `PRD.md`, `PRD_FINALIZED.md`, `PRD_COMPLETED.md`, `implementation/`, `sweep.log`. `workspace/implementation/` holds the 13 modules, `start.sh`, `requirements.txt`, and `results.1.json`–`results.8.json` from the final all-passing sweep (158/158 each). `test_helpers/` (9 files) and `test_suite/` (18 files, 158 tests) sit at the task root, not under `workspace/`. `__pycache__` removed. Only one `worklog.md` exists, at the task root — no cwd-drift strays.
