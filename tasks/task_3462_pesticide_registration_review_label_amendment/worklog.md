# Worklog — task_3462_pesticide_registration_review_label_amendment

## Step 1: Create Task Directory — 2026-10-02T08:15:00.000Z

Task directory `./tasks/task_3462_pesticide_registration_review_label_amendment/` was pre-allocated by the caller (with `workspace/` inside); verified it exists and no index computation was performed. Scenario: Pesticide Registration Review & Label Amendment (EPA). Difficulty instruction: "Generate task much harder than expert level!" (passed to prd-bench-scaffold-generator only).

## Step 2: Generate Scaffold — 2026-10-02T10:16:00.000Z

Scaffold generation complete. All three artifacts written and verified:

**Files written**
- `/home/ubuntu/github/CodingPRD/tasks/task_3462_pesticide_registration_review_label_amendment/SCAFFOLD.yaml` (§1.0–§1.7, ~109 KB)
- `/home/ubuntu/github/CodingPRD/tasks/task_3462_pesticide_registration_review_label_amendment/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (~134 KB)
- `/home/ubuntu/github/CodingPRD/tasks/task_3462_pesticide_registration_review_label_amendment/SCAFFOLD_CORNER_DESIGN.yaml` (~293 KB)

**Surface counts**: 14 entities, 12 state machines, 13 calculations, 12 validation priority bands, 55 endpoints, 47 error codes, 6 roles (all `opaque`; `RegistrantRepresentative` ownership via `Product.registrant_ref == X-User-ID`), 1 OCC concurrency rule (`amendment-create-stale-product` on `Product.version`).

**Design index sizes**: §1.8 = 19 non-stub instances (all 9 rules ≥ 2; `combinatorial_formula` carries 3, covering modes (a) tiered-conditionals, (b) round-per-commodity-then-sum, (c) renewal-fee evaluation-order). §1.9 = 69 non-stub instances + 11 `excluded_because:` stubs. 99 unique instance names across both files; every §1.6 error is exercised; `scaffold_lint.py` reports `VERDICT: clean lint` (1212 calls scanned, zero violations, all FKs reverse-reachable).

**Design decisions worth flagging downstream**
- **Endpoint count 55 exceeds the Expert band (20–32)** — deliberately, per the "much harder than expert" instruction; the Step-6 impl-gen prompt should pre-constrain (per-domain modules, one file per message) per known overshoot risk.
- **Logical clock**: `POST /_clock/set_current_utc` (unprefixed), default `2026-09-01T00:00:00Z`, monotonic-non-decreasing (equal is a no-op), runs a pinned 4-step sweep (cases open → DCIs delinquent → certs expire → state regs lapse) — this is the ops-run checkpoint and drives the depth-4 delinquency cascade.
- **All arithmetic/date literals in asserts were pre-computed with Python** (e.g., 2028-12-14 renewal carryover, 2028-07-31 695-day amendment timeline, dietary_rq 7.143 vs 0.429 screening/refined divergence).
- **Documented asymmetries** (intentional, testable): suspension vacatur restores nothing (reinstate is the only path back, gated on no EFFECTIVE proceeding + no unsatisfied DCIs); cancellation vacatur restores product/tolerances/use-sites via stored `pre_*_status` fields but never state registrations; the hop-3 amendment auto-rejection is tolerance-mediated only (METHOD_CHANGE amendments provably untouched).
- **Segregation of duties** fires on opaque user ids, not roles: proceeding initiator can't issue its order; the latest risk assessment's assessor can't approve the application (corner `application_approver_who_ran_latest_assessment_returns_sod` exercises it via same user id under a different role hat).
- Two interval semantics pinned: bulletins = closed calendar-month sets with wraparound (shared month = conflict); review cases = half-open `[opened_at, due_at)` (adjacency allowed).

Orchestrator verification: all three files exist and YAML-parse; SCAFFOLD.yaml top-level keys = scenario/domain_name/api_prefix/complexity_profile/entities/state_machines/concurrency_rules/calculations/validations/response_envelope/endpoints/errors/roles; api_prefix = `/pesticide-registry`; 234 domain-token (pesticide|registrant|tolerance|amendment) hits in SCAFFOLD.yaml — domain confirmed, no foreign-content contamination.

## Step 3: Copy Shared Files — 2026-10-02T10:20:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T10:35:00.000Z

All checks pass. The PRD is complete and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3462_pesticide_registration_review_label_amendment/workspace/PRD.md` — 369 lines (dense long-paragraph prose), ends cleanly at §5.

**Sections:** §1 Introduction (2 paragraphs); §2 Global Specifications — 2.1 RBAC with per-role `identity` translations, 2.2 API Response Structure (byte-identical verbatim block, confirmed programmatically), 2.3 Pagination (limit 10/1–100, offset 0, `created_at` ascending), 2.4 Logical Clock & the pinned 4-step sweep (default `2026-09-01T00:00:00Z`, strict vs inclusive comparisons), 2.5 Common Resource Properties, 2.6 Precision & Rounding, 2.7 OCC on amendment filing (`expected_product_version` / `ERR_STALE_PRODUCT_VERSION` 412, checked before business validation), 2.8 the 12-stage validation pipeline in priority order, 2.9 nested left-to-right resolution + the 5-commodity / 4-state reference sets; §3 Business Logic — 3.1 reference chemistry & product shell, 3.2 application filing/fees/deficiency loop, 3.3 studies & the three risk quotients + LOC, 3.4 tolerances & the approval cascade (signal-word map, `EPA-RR-` minting, first review case), 3.5 label amendments (payload shapes, timeline adders, expedited halving, `priia_category`), 3.6 ESA bulletins, 3.7 review cycle & DCI ledger/delinquency cascade, 3.8 suspension/cancellation/existing-stocks/vacatur/reinstatement, 3.9 certification & state registration renewal arithmetic; §4 endpoint index (55 rows, 4 columns); §5 error catalogue (47 rows, 2 columns).

**Hard contracts (all PASS, verified by script):**
- Contract 1 field coverage: 125 required identifiers (entity fields + endpoint inputs + query params + nested payload keys like `use_site_id`, `new_application_method`, `expedited`, `disposed_at`), 125 present in backticks, 0 missing.
- Contract 2 rule coverage: 12 validation priorities expressed as an ordered pipeline; 1/1 OCC rule fully named; all 12 state machines with every transition, precondition error, and side effect (including the 3-hop cancellation cascade, 4-hop delinquency cascade, vacatur restore/asymmetries, sibling-branch groups rendered with equal density); 13/13 calculations in precise prose with all constants embedded (fees, consumption values, runoff factors, LOC thresholds, 5475/180-day cycle, 8.0 lb/acre cap, 365/730 FIXED vs DEPLETION windows, late-fee formula); all 47 error IDs reachable from prose.
- Contract 3 §3 path purity: 797 backticked tokens scanned, 0 paths, 0 bare HTTP methods, 0 method+path combos.

**Judgment calls (scaffold left the error mapping implicit):** `ERR_PRODUCT_TERMINAL` was applied to amendment filing and tolerance proposal against a `CANCELLED` product (catalog condition is generic; approval/renewal sides pin it explicitly); state-registration creation against a non-`REGISTERED` product mapped to `ERR_PRODUCT_NOT_REGISTERED`; non-future `certified_until` at certification creation and non-future DCI `response_deadline` mapped to `ERR_INVALID_REQUEST`. No scaffold rule was omitted or reinterpreted beyond these unnamed-error assignments. The two forbidden design-index files were never opened.

Orchestrator verification: PRD.md = 369 lines; head/tail coherent (opens with EPA intro, closes with error catalogue); 47 unique `ERR_*` IDs present, matching scaffold count.

## Step 5a: Generate Test Helpers (Stage 1 of unit-test-generator, frozen) — 2026-10-02T11:15:00.000Z

Orchestrator pre-measurement of design indices (ground truth passed into prompt): Difficulty = 19 non-stub instances across 9 rules (dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 2, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2); Corner = 69 non-stub + 11 excluded stubs across 9 sections (entities 8, state_machines 16, calculations 4, validations 21, endpoints 2, errors 11, rbac 2, cross_cutting_layers 4, consistency_model 1). 88 total expected tests. Step 5 split into 5a (helpers, frozen) + 5b (tests) per oversized-generation playbook.

All verification passes. Stage 1 is complete and frozen.

### Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_3462_pesticide_registration_review_label_amendment/`)

| File | Lines | Contents |
|---|---|---|
| `test_helpers/types.py` | 458 | `UserRole` + 19 field enums + 11 status enums + 15 TypedDicts (all entities carry `id/created_at/updated_at/version` per PRD §2.5 — no append-only exceptions in this task) |
| `test_helpers/constants.py` | 148 | 29 constant groups, every literal PRD-grepped (audit below) |
| `test_helpers/api_client.py` | 241 | `ApiClient(GenericApiClient)` with all 55 endpoint methods + `api_client` singleton |
| `test_helpers/api_errors.py` | 122 | `ApiErrorId` (47 ids) + `HTTP_STATUS_CODES` + `set_error_http_status_map` registration at import |
| `test_helpers/calc.py` | 252 | `round_half_up`, ISO instant helpers (`parse_instant`/`format_instant`/`add_days`/`instants_equal`), and expected-value recomputers for dietary/occupational/ecological RQs, LOC, amendment timeline + priia_category, stocks deadlines (FIXED/DEPLETION), renewal fee, annual fee, EPA registration number |
| `test_helpers/assertions.py` | 303 | `assert_<entity>` for all 14 entities, `assert_common_fields`, `assert_iso_instant_equal` (instant-tolerant timestamp compare), `assert_dci_ledger_partition`, `assert_disposal_total` |
| `test_helpers/factories.py` | 360 | One factory per entity + amendment payload variant builders + order/decision/disposal/renewal/clock payloads; counter-unique names/CAS numbers |
| `test_helpers/test_users.py` | 79 | `TEST_USERS` (9 header dicts, 2 per SoD-relevant hat) + `make_<role>_headers(user_id)` builders for all six opaque-id roles + `user_id_of()` |
| `test_helpers/fixtures.py` | 815 | Composite fixtures (see below) |
| `test_helpers/__init__.py` | 36 | Barrel: framework generics + all PRD-specific modules |
| `test_suite/conftest.py` | 51 | Session-scoped `api` fixture + 9 role-header fixtures |

### Verification results
- **py_compile**: all 10 files + conftest compile clean.
- **Import smoke test** (from task root, real `import test_helpers`): singleton binds correctly (`from test_helpers import api_client` → `ApiClient` instance; `test_helpers.api_client` submodule still yields `ApiClient` class via `sys.modules`); error map registered (47/47 entries, e.g. `ERR_STALE_PRODUCT_VERSION`→412, `ERR_INCORRECT_FEE_PAYMENT`→402, `ERR_SEGREGATION_OF_DUTIES_VIOLATION`→403); all 55 endpoint methods present; `pytest --collect-only` on test_suite imports conftest without error.
- **Clock endpoint**: `CLOCK_PATH = "/_clock/set_current_utc"` unprefixed — verified against SCAFFOLD.yaml:1162 and PRD.md:85/260. Default clock `2026-09-01T00:00:00Z`.
- **calc vs pinned design-index literals** (all reproduced exactly): dietary 0.28→(3.5, 1.000 LOC-trip) / 0.27→(3.375, 0.964); round-per-commodity 5.834/1.667; REFINED divergence 1.5/0.429; amendment 695 days → 2028-07-31 and expedited 121 → 2027-01-04; stocks FIXED → 2028-02-29/2029-02-28, DEPLETION(12000@2000) → 2027-08-28/2028-02-24; renewal 26 days late on 35000 → fee 38500, due 2027-12-15→2028-12-14; cycle dates 2041-08-28 and 2056-08-24; `EPA-RR-000001`; occ 0.003/0.006, eco 0.001.
- **Constants-vs-PRD audit**: 29/29 groups matched verbatim at PRD lines 77, 85, 92, 136, 152, 154, 156, 170, 172, 174, 176, 186, 194, 220, 232, 248, 250. (Note: the §5 catalog has 47 error ids, not 48 — the enum matches PRD+scaffold exactly.)

### Fixture tiers (fixtures.py)
- **Pipeline**: `create_active_ingredient`, `create_product`, `create_application`, `create_required_studies`, `accept_study`/`reject_study`, `create_tolerance`, `submit_application` (exact fee by use pattern), `resubmit_application` (payment omitted), `run_risk_assessment`, `approve_application` (reviewer ≠ assessor by default), `setup_application_in_review(...)`, `create_registered_product(...)` → namespace `{active_ingredient, product(REGISTERED), application(APPROVED), studies, assessment, tolerance, use_sites(ACTIVE), review_case(SCHEDULED cycle-1), registrant/reviewer/assessor_headers}`.
- **Amendments (OCC)**: `file_amendment` (auto-fetches current product version when omitted), `file_new_use_amendment`, `file_rate_change_amendment`, `file_method_change_amendment`, `approve_amendment`, `get_product_version`.
- **Clock/cases/DCIs**: `set_clock`, `reset_clock`, `create_manual_review_case`, `open_case_via_clock`, `setup_open_review_case`, `complete_case`, `issue_dci`, `create_dci_study`, `respond_dci`, `setup_case_with_dci`, `setup_satisfied_dci`, `setup_delinquent_dci` (one clock set → DELINQUENT + REFERRED + SUSPENDED cascade).
- **Proceedings**: `initiate_proceeding`, `hold_hearing`, `issue_cancellation_order` / `issue_suspension_order` (issuer rr-2 ≠ initiator rr-1 by default — SoD-clean), `vacate_proceeding`, `record_disposal`, `setup_effective_cancellation`, `setup_effective_suspension`, `setup_cancelled_product`, `setup_suspended_product`, `reinstate_product`.
- **State layer**: `create_certification`, `renew_certification`, `apply_state_registration`, `grant_state_registration`, `setup_granted_state_registration` (auto-creates a valid cert for RESTRICTED_USE), `renew_state_registration` (auto-computes exact fee when `payment_cents` omitted and `clock_iso` given), plus `expected_next_cycle_opened_at` / `expected_case_due_at`.

### Import surface for Stage 2
Everything via `from test_helpers import ...` (never `import test_helpers.api_client as ac` — the package attribute is the client instance by design). Key signatures:

- `api_client.<method>`: `create_product(payload, headers)`, `submit_application(application_id, headers, payload=None)`, `decide_application(application_id, payload, headers)`, `create_study(payload, headers)`, `decide_study(study_id, payload, headers)`, `create_risk_assessment(payload, headers)`, `create_label_amendment(payload, headers)`, `set_clock(payload, headers)`, etc. — all return raw `requests.Response`.
- Validators: `validate_success(resp, expected_status=200)` — **pass 201 explicitly for all resource-creating POSTs** (active ingredients, products, applications, studies, risk assessments, tolerances, amendments, certifications, bulletins, review cases, DCIs, proceedings, state registrations); 200 for reads/actions/clock. `validate_error(resp, ApiErrorId.ERR_X)` auto-checks HTTP status via the registered map. `get_success_data(resp, 201)` in setups.
- `ApiErrorId.<ERR_NAME>`, `TEST_USERS["registrant_alice_headers" | "reviewer_1_headers" | ...]`, `make_reviewer_headers(uid)` / `make_assessor_headers(uid)` for SoD staging (same uid under both hats = violation).
- Fixtures and calc helpers as listed above; `assert_<entity>(data)` shape checkers; `assert_iso_instant_equal(actual, expected)` for timestamp assertions (compare instants, not strings).

No `test_*.py` files were written — that is Stage 2's scope.

Orchestrator spot-check: all 10 helper files + conftest.py exist (2822 lines total in test_helpers/), `CLOCK_PATH = "/_clock/set_current_utc"` confirmed unprefixed in api_client.py:13, `python3 -m py_compile` clean across all files.

## Step 5b: Generate Test Suite (Stage 2 of unit-test-generator) — 2026-10-02T11:55:00.000Z

Stage 2 complete. Final report:

## Files written (13 test files, 2929 lines total)

All under `/home/ubuntu/github/CodingPRD/tasks/task_3462_pesticide_registration_review_label_amendment/test_suite/`:

| File | Lines | Tests |
|---|---|---|
| test_01_creation_and_defaults.py | 249 | 8 (entities) |
| test_02_risk_assessment.py | 279 | 7 (4 difficulty + 3 calc corners) |
| test_03_label_amendments.py | 312 | 9 (amendments, OCC, ESA, timeline) |
| test_04_application_submission.py | 196 | 7 (submit gates, fee, ownership) |
| test_05_application_decisions.py | 248 | 8 (deficiency loop, approve gates, SoD, consistency) |
| test_06_proceedings.py | 197 | 7 (proceeding steps, SoD, FIXED/DEPLETION deadlines) |
| test_07_cancellation_stocks.py | 241 | 5 (cascade hops, vacatur restore, disposals) |
| test_08_review_cases.py | 174 | 6 (case/DCI state gates, windows) |
| test_09_review_cycle_cascades.py | 279 | 5 (cycles, delinquency cascade, DCI ledger) |
| test_10_state_registrations.py | 165 | 6 (grant fees, lapse, renewal carryover) |
| test_11_certifications_and_grants.py | 156 | 4 (cert boundary, renew cycle, RUP grant gate) |
| test_12_bulletins_and_clock.py | 202 | 5 (month windows, wrap, clock sweep) |
| test_13_platform_rbac_errors.py | 242 | 11 (RBAC, 404s, reference sets, pagination) |

test_helpers/ and test_suite/conftest.py untouched (mtimes predate this stage; no scaffold mentions in test code).

## Verification results

- **py_compile**: all 13 test files + conftest compile clean.
- **pytest --collect-only** (PYTHONPATH=., dummy API_BASE_URL): **87 tests collected, 0 import errors**. One mid-course fix: the frozen fixtures.py never exported `get_application`, so two files now read applications via `api_client.get_application` + `validate_success` through a module-local helper.
- **AST tag audit** (real `ast` parse, docstring walk): 87 tests, 87 unique `Design:` tags, every tag is the docstring's last line and resolves to a real non-stub instance; 0 duplicates; the only index instance without a test is the reported skip below. Expected 88 = 87 emitted + 1 skipped.
- **Verbatim citation audit**: 157 PRD citation groups extracted from docstrings, all survive whitespace-normalized substring match against workspace/PRD.md after fixing 4 groups that had used mid-quote elisions (now quoted in full).

## Skipped instance (1 of 88) — reported, not papered over

- **Corner/endpoints/state_registrations_list_filters_by_product_and_status** — SKIPPED on unique derivability. The instance asserts composed query-filter behavior (`?product_id&status=GRANTED`, `?state_code=CA`, unknown-id filter miss) on `GET /state-registrations`, but the PRD never specifies that collection's filter parameters: §3.9 names list filters only for other collections, and the §4 table row is just "| GET | `/pesticide-registry/state-registrations` | List state registrations | All roles |". A faithful PRD-only implementer could ship no filters and fail the test. Gap category: unenumerated filter surface (adjacent to `applies_to-scope`).

No other instances were found unimplementable; all 19 difficulty and the remaining 68 corner instances have verbatim PRD coverage and uniquely-derived outcomes. Clock-reachability was checked per recipe: every `set_clock` target is ≥ the 2026-09-01 default, and intermediate sweep side effects (case openings at 2027-01-05, cert expiry at 2027-01-15T12:00:01Z, lapse at grace+30, DCI delinquency) are the intended transitions in each recipe, not accidental ones.

Orchestrator independent AST audit (real `ast` parse, re-run against both YAML indices): 88 expected non-stub instances; 87 tests found; 0 untagged; 0 duplicate tags; 0 unresolved tags; exactly 1 instance without a test = `Corner/endpoints/state_registrations_list_filters_by_product_and_status` (the reported skip). Confirmed.

## Step 6: Generate Implementation — 2026-10-02T12:35:00.000Z

All checks pass. The `__pycache__` dirs regenerate on boot and are harmless. Implementation complete — final report:

## Implementation complete: task_3462 pesticide registration review

**Location:** `/home/ubuntu/github/CodingPRD/tasks/task_3462_pesticide_registration_review_label_amendment/workspace/implementation/`

### Modules (28 Python files, 3360 lines total)
- **Foundation:** `constants.py` (127), `errors.py` (75 — full 47-error catalog), `db.py` (67 — in-memory dict store, empty at boot, no seeding), `clock.py` (55 — logical clock, default `2026-09-01T00:00:00Z`, monotonic), `envelope.py` (60 — PRD §2.2 meta/response_type/data envelope), `auth.py` (26 — X-User-ID/X-User-Role, stages 1-2), `validate.py` (196 — stage-3 schema: unknown-key rejection, type/enum/conditional checks, use-site validator, pagination)
- **Services:** `calcs.py` (184 — risk quotients with pinned 4dp→3dp rounding, amendment timeline, renewal fee, stocks deadlines, reg-number minting), `cascade.py` (204 — approval/suspension/cancellation/vacatur/delinquency cascades), `dci.py` (58 — obligation ledger partition), `sweep.py` (47 — pinned 4-step clock sweep)
- **Routes (14 blueprints):** `clock_route.py`, `active_ingredients.py`, `products.py`, `applications.py` (331), `studies.py`, `risk_assessments.py`, `tolerances.py`, `amendments.py` (291), `certifications.py`, `bulletins.py`, `review_cases.py`, `data_call_ins.py`, `proceedings.py` (293), `state_registrations.py`
- **`app.py`** (80 — thin factory, blueprint registration, ApiError/404/405/500 envelope handlers), **`start.sh`** (guarded pip install, `exec python3 app.py`, `$PORT`/0.0.0.0/foreground), **`requirements.txt`**

### Verification results
- **py_compile:** whole tree passes (28 files)
- **Import smoke:** `from app import create_app; create_app()` passes — package graph intact
- **Live boot smoke** (ports 35471–35475, all servers killed by exact listener PID afterward): full lifecycle verified — clock set/no-op/monotonic-400; application flow (submit gates, 402 fee, deficiency loop with `review_due_at` unchanged on resubmit); SCREENING 0.625/0.179 vs REFINED 0.125/0.036 math; APPROVE cascade (product REGISTERED, `EPA-RR-000001` after fixing a self-count bug the smoke caught, signal word, first case SCHEDULED at +5475d/+180d); SoD 403 on both approve and issue-order; OCC 412 stale / 201 current with product version bump; expedited METHOD_CHANGE ceil(91/2)=46d; bulletin wrap-overlap 409; PROHIBITED blocks NEW_USE; +60d bulletin adder; DCI issue→delinquency cascade (case REFERRED, auto EFFECTIVE SUSPENSION proceeding with `initiated_by_ref:"system"`, product SUSPENDED, state-reg denied); reinstate blocked → late cure → vacate → reinstate REGISTERED; cancellation hops 1–3 incl. commodity-matched NEW_USE auto-reject with `decided_at`; DEPLETION 12000@2000 → 180/360-day windows; disposal quantity 422 and window 422; vacatur restore (product/tolerances/ACTIVE sites restored, amendments/state-regs not); cert expiry + state-reg lapse sweeps; late renewal fee 35000×(1+0.10×14)=84000 with anniversary advancing +365d from previous value (never payment date)
- **Endpoint count:** 56 method+path routes = 55 business (all under `/pesticide-registry`) + 1 unprefixed `POST /_clock/set_current_utc` ✓
- **Constants audit:** 51 referenced `constants.*` names, all defined exactly once; 47/47 catalog error IDs emitted (plus one `ERR_INTERNAL` 500 catch-all fallback not in the catalog — only reachable on genuine server bugs); all 15 service functions have exactly one def and ≥1 call

### Interpretations chosen (PRD wording required judgment)
1. **created_at/updated_at use wall-clock** (3-fractional-digit ISO per §2.5 format + example); §2.5's logical-clock enumeration lists only workflow stamps (`submitted_at`, `decided_at`, …). Sort is created_at-ascending with insertion-seq tiebreak.
2. **DCI respond bad study ids** (nonexistent, or linked to another DCI) → `ERR_STUDY_PARENT_MISMATCH` per §3.7's "any mismatch fails" sentence, rather than the generic stage-4 404.
3. **Amendment `use_site_id` nonexistent OR foreign-product** → `ERR_USE_SITE_PRODUCT_MISMATCH` (PRD: "does not name a use site of the same product"). No status gate on the target site (PRD states none).
4. **Study-create ownership** failure emits `ERR_STUDY_PARENT_MISMATCH` (§3.3 explicit) rather than `ERR_NOT_RESOURCE_OWNER`; DCI-respond ownership emits `ERR_NOT_RESOURCE_OWNER`.
5. **Missing `payment_cents`** on first submit / renewal → `ERR_INCORRECT_FEE_PAYMENT` (402), treating absent as unequal to the computed fee (scaffold ties presence to that error).
6. **Cancellation cascade ordering:** all PROPOSED/ESTABLISHED tolerances revoked *with* `pre_revocation_status` markers (required by the vacatur text "whether that prior status was PROPOSED or ESTABLISHED"); PROPOSED use sites removed with null markers per PRD hop-2 (PRD wins over the scaffold UseSite note saying the cascade marks them PROPOSED); restored rows have `revoked_at`/`removed_at` cleared along with the marker.
7. **State-registration filing/grant against a CANCELLED product** → `ERR_PRODUCT_NOT_REGISTERED` (§3.9 names only that error there, unlike renewal which explicitly distinguishes `ERR_PRODUCT_TERMINAL`); proceedings create against CANCELLED → `ERR_PRODUCT_TERMINAL` (§3.8 pattern).
8. **Issue-order check order:** step gate → SoD → stocks-conditional `ERR_INVALID_REQUEST` (scaffold precondition order; the stocks check needs the loaded proceeding's type so cannot be pure stage-3).
9. **Disposal check order:** quantity ceiling (stage 9) before window (stage 11) per pipeline priority; `units` typed as integer with no PRD-unstated lower bound (0 allowed).
10. **Pagination** out-of-range limit/offset clamped to [1,100]/[0,∞) (PRD states bounds but no error); sub-resource lists accept limit/offset with the same defaults.
11. **NEW_USE payload:** `tolerance_ppm` present requires `commodity_code` (schema); `commodity_code` alone is permitted and only drives the hop-3 cascade match. `cas_number` duplicates → `ERR_INVALID_REQUEST` (no catalog error exists for it). `final_classification` on DENY/DEFICIENCY is accepted-but-ignored (PRD forbids it nowhere).

Orchestrator verification: implementation tree compiles recursively (`compileall` clean); 14 route blueprints + 4 service modules present as reported; `start.sh` reads `$PORT`, binds via app.py, foreground `exec`, guarded pip install.

## Step 7: Run Tests and Iterate — 2026-10-02T13:13:00.000Z

All 8 rounds pass 87/87. The final sweep's `results.1..8.json` remain in `workspace/implementation/` per the output contract.

## Summary

**Iterations run:** 2 (sweep 1: 16 deterministic failures, identical across all 8 rounds; fixes applied; sweep 2: 8/8 rounds clean, 87/87 each).

**Tests deleted:** None outright. One assertion removed via STEP 1c partial-coverage split:
- `test_01_creation_and_defaults.py::test_active_ingredient_create_echoes_fields_and_stamps_system_fields` — removed `assert_iso_instant_equal(data["created_at"], DEFAULT_CLOCK, ...)`. **Silence category: DEFAULT-SOURCE SILENCE (STEP 1b collapse).** PRD §2.5 defines `created_at` as "an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created" but never pins its clock source; the "and their kin" sentence's subject is workflow stamps (`submitted_at`/`decided_at`/…), and the pinned three-fractional-digit format is degenerate under the day-granular logical clock — so wall-clock `created_at` (Step 6 interpretation #1) is a second PRD-faithful reading, failing unique derivability. Scaffold driver: `SCAFFOLD_CORNER_DESIGN.yaml` distinguishing_aspect "created_at/updated_at at the logical clock" — a scaffold-only rule (doc-generator Zero-Silence feedback: the common-fields clock source never reached PRD prose). All covered assertions (201, envelope, field echoes, `version == 1`) were kept.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`:**
- `test_04_application_submission.py` — module helper `_get_application` called nonexistent `api_client._get_application`; repointed to the existing public `api_client.get_application` (unblocked 6 tests).
- `test_05_application_decisions.py` — same helper-name fix (unblocked 6 tests).
- `test_09_review_cycle_cascades.py` — added missing imports `create_manual_review_case` and `get_proceeding` (both defined in `test_helpers/fixtures.py`; runtime NameError).
- `test_11_certifications_and_grants.py::test_certification_renew_with_past_date_returns_renewal_invalid` — renewal literal `2027-01-01` → `2026-08-31`. With the logical clock at its `2026-09-01` default, the old literal is strictly later than the clock, so PRD §3.9 ("new_certified_until must be strictly later than the logical clock, failing ERR_CERTIFICATION_RENEWAL_INVALID otherwise") requires *success* — the test asserted an error on a PRD-legal request. The new literal is genuinely not strictly later than the clock, restoring the cited PRD rule.
- `test_01_creation_and_defaults.py` — removed the non-derivable `created_at` assertion plus the then-unused module constant `DEFAULT_CLOCK` (see deletion note above).

**Fixes applied to `implementation/`:** none — the implementation was already PRD-faithful on every failing path; all 16 failures were test-artifact defects (2 helper-name typos, 2 missing imports, 1 clock-inconsistent fixture literal, 1 non-derivable assertion).

Orchestrator verification: all 8 `results.{1..8}.json` present in workspace/implementation/ with passed=87/87, failed=0; no `.py` source file newer than results.1.json (post-sweep edit check clean, `__pycache__` excluded); spot-checked fixes confirmed in files (test_11:124-126 has the 2026-08-31 literal with clock comment; test_04:36-64 repointed helper; test_01 has 0 `created_at` instant assertions and 0 `DEFAULT_CLOCK` references).

## Step 8: Finalize PRD — 2026-10-02T13:30:00.000Z

Done. The diff is exactly the two intended revisions; everything else in PRD_FINALIZED.md is verbatim PRD.md.

**Line counts / delta:** PRD.md 369 lines; PRD_FINALIZED.md 369 lines — 3 lines revised in place, 0 net lines (0.00% delta).

### Changes (2 edits)

- **§2.5 — revise** — `created_at`/`updated_at` bullets now pin the clock source: "stamped from the server's wall clock rather than the logical clock of §2.4" (created_at), "likewise stamped from the server's wall clock rather than the logical clock" (updated_at) — `implementation/db.py:37-39` (`wall_iso`), `db.py:44-48` (`new_row`), `db.py:57` (`touch`).
- **§2.3 — insert** — appended "Resources created at the same instant are returned in the order they were created." — `implementation/db.py:61-67` (`sort_key` = `(created_at, _seq)`), consumed by `validate.py:188-196` (`paginate`).

### Per-item disposition of `<step_7_diff>`

- **test_04 helper fix (`_get_application` → `get_application`)** — no edit — pure test bug; `test_helpers/api_client.py:65` defines `get_application`; no PRD behavior involved.
- **test_05 helper fix (same)** — no edit — same evidence; `test_suite/test_05_application_decisions.py:37-39` now calls the existing public helper.
- **test_09 missing imports** — no edit — pure test bug; `create_manual_review_case` (`test_helpers/fixtures.py:475`) and `get_proceeding` (`fixtures.py:654`) both exist.
- **test_11 renewal literal 2027-01-01 → 2026-08-31** — no edit — PRD §3.9 already pins "strictly later than the logical clock"; impl `routes/certifications.py:78` enforces exactly `new_certified_until <= clock.now()` → `ERR_CERTIFICATION_RENEWAL_INVALID`, and the clock default is 2026-09-01 (`clock.py:10`). The old literal was PRD-legal; test bug only.
- **test_01 created_at assertion removal** — EDIT MADE — the one genuine silence: PRD §2.5 pinned the three-fractional-digit format but never the clock source; impl stamps wall clock universally.

### Pre-edit search logs (NO-NEW-MISMATCH)

**Edit 1 — (a) subject:** clock source of system-managed `created_at`/`updated_at`. **(b) enumerated paths:** `db.py:new_row` is the sole creation stamper for all 14 collections (creation sites: `routes/active_ingredients.py:36`, `products.py:36`, `applications.py:84+103`, `studies.py:121`, `risk_assessments.py:56`, `tolerances.py:50`, `amendments.py:167+256+269`, `certifications.py:39`, `bulletins.py:83`, `review_cases.py:67`, `data_call_ins.py:73`, `proceedings.py:67`, `state_registrations.py:69`, `services/cascade.py:57+181`); `db.py:touch` is the sole mutation refresher (57 call sites across all 13 route/service files); grep confirmed zero writes to `created_at`/`updated_at` outside db.py; `envelope.py:serialize` passes the pre-stamped strings through (only datetimes — the workflow stamps — go through `clock.iso_z`); every workflow stamp uses `clock.now()` (verified across applications/studies/risk_assessments/state_registrations/review_cases/proceedings/amendments/bulletins/data_call_ins/sweep/cascade), so the untouched final §2.5 sentence stays true; `envelope.py:19` `api_request_timestamp` is also wall-clock but out of scope (§2.2, not a step-7 item, no claim made about it). **(c) wording adjustment:** scoped strictly to the two fields and left the workflow-stamps sentence verbatim; deliberately avoided any "no rule reads these fields" claim since `created_at` is read by the §2.3 sort — this keeps §2.4's "every time-dependent rule … never against wall-clock time" un-contradicted.

**Edit 2 — (a) subject:** list ordering when `created_at` values tie (orchestrator-note adjunct to the same silence item; §2.3 pins the sort key but not same-instant ties, so its "no edit needed" condition did not hold). **(b) enumerated paths:** `db.sorted_rows`/`sort_key` is the single ordering choke point, reached via `validate.paginate` from every list endpoint — `active_ingredients.py:54`, `products.py:61` (list) and `products.py:123` (all four sub-resource listings via `_sub_list`: use-sites/tolerances/bulletins/review-cases), `applications.py:127` (list), `:317` (studies sub-list), `:330` (risk-assessments sub-list), `studies.py:148`, `amendments.py:195`, `certifications.py:62`, `proceedings.py:102`, `state_registrations.py:97`, `review_cases.py:138` (data-call-ins sub-list); `services/sweep.py:20/30/35/41` iterates the same ordering intra-step; `applications.py:328` confirms risk-assessment list order coincides with `assessment_seq` order; the only other `sorted(` calls (`constants.py:101`, `validate.py:30`) are reference-set membership and error-message key listing, not resource ordering. **(c) wording adjustment:** mechanism-agnostic ("the order they were created", no `_seq` mention) and scoped to list responses ("are returned"), so it holds for filtered sub-lists (filters drop rows, never reorder) and makes no claim about sweep internals.

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` shows exactly the 3 revised lines claimed (§2.3 tiebreak sentence; §2.5 created_at + updated_at clock-source clauses) and nothing else; both files 369 lines.

## Step 9: Complete PRD — 2026-10-02T13:51:00.000Z

All 22 edits applied cleanly (22 diff hunks, all in-paragraph — line count unchanged). Final verification of the complete diff structure is done. Here is the summary.

**Source vs output:** `PRD_FINALIZED.md` 369 lines / 67,787 chars → `PRD_COMPLETED.md` 369 lines / 70,929 chars. Char-delta **+3,142**, line-delta **0** (all edits are in-paragraph inserts/revisions).

**Counts:** 19 ambiguity/silence pins, 3 mismatch revisions, 6 impl bugs reported.

### Ambiguity pins / silence fills (one bullet each)

- §2.1 — revise — mismatch — removed "submitting a study" from the `ERR_NOT_RESOURCE_OWNER` ownership list and added the carve-out: study-submission parent-ownership fails `ERR_STUDY_PARENT_MISMATCH`, fired at the ownership point — impl `routes/studies.py:99-104` (see mismatch revisions below).
- §2.3 — revise — ambiguity — out-of-range `limit`/`offset` are clamped to [1,100]/[0,∞), non-integer fails `ERR_INVALID_REQUEST` — impl `validate.py:163-185`.
- §2.5 — revise — ambiguity (silence) — `version` starts at 1 on creation — impl `db.py:42-51` (test_01 asserts `version == 1`).
- §2.5 — insert — silence — logical-clock timestamps serialize without fractional part when zero, 3 digits otherwise — impl `clock.py:43-47`, `envelope.py:29-30`.
- §2.8 stage 3 — insert — silence — explicit JSON null ≡ omission; empty string fails; malformed/non-object body fails this stage; entity-keyed conditional rules (stocks payload, resubmit payment omission) evaluated where §3 pins them — impl `validate.py:13-48`, `proceedings.py:169-200`, `applications.py:189-197`.
- §2.8 stage 10 — revise — ambiguity — parenthetical noting study-parent belonging fires earlier at the ownership point — impl `routes/studies.py:99-104`.
- §2.8 stage 11 — revise — silence — added certification-issuance instants and DCI response deadlines to the temporal list — impl `certifications.py:33-37`, `data_call_ins.py:62-63`.
- §2.8 stage 12 — revise — ambiguity — an omitted payment field counts as a mismatch (402) — impl `applications.py:143-146,175-180`, `state_registrations.py:193,215-220`.
- §2.9 — insert — silence — unknown path or unsupported method on a known path → 404 `ERR_NOT_FOUND` — impl `app.py:57-65`.
- §3.1 — revise — ambiguity — duplicate `cas_number` fails `ERR_INVALID_REQUEST` — impl `active_ingredients.py:33-34`.
- §3.2 — revise — ambiguity — drafting an application is gated only by ownership, not product status (the `UNREGISTERED` requirement bites at submission); `proposed_use_sites` may be empty — impl `applications.py:53-116`.
- §3.2 — revise — ambiguity — a resubmission carrying a payment value fails `ERR_INVALID_REQUEST`, checked before the studies re-check — impl `applications.py:189-197`.
- §3.3 — revise — ambiguity — study-create parent-ownership check fires ahead of the application-status gate — impl `routes/studies.py:99-115`.
- §3.4 — insert — silence — `final_classification` on DENY/DEFICIENCY is enum-validated but never stored — impl `applications.py:241-246,255-266`.
- §3.5 — insert — ambiguity — `tolerance_ppm` without `commodity_code` fails `ERR_INVALID_REQUEST`; `commodity_code` alone is accepted (no tolerance minted, no 180-day adder) — impl `amendments.py:47-56`, `calcs.py:123-124`.
- §3.6 — revise — ambiguity — `county_fips` carried as an opaque string, shape not validated — impl `bulletins.py:34` (`as_str` only).
- §3.7 — revise — silence — duplicate `required_study_types` entries collapse to first occurrence — impl `data_call_ins.py:65-71`.
- §3.7 — revise — silence — each response moves the call-in to `RESPONDED`; ledger arrays list types in `required_study_types` order — impl `data_call_ins.py:130-134`, `services/dci.py:9-30`.
- §3.7 — revise — silence — the auto-created delinquency proceeding also stamps `initiated_at` and captures `pre_effective_product_status` — impl `services/cascade.py:181-203`.
- §3.8 — revise — ambiguity — proceeding create vs CANCELLED → `ERR_PRODUCT_TERMINAL`, vs UNREGISTERED → `ERR_PRODUCT_NOT_REGISTERED`; proceedings list with `product_id`/`proceeding_type`/`status` filters — impl `proceedings.py:48-54,94-103`.
- §3.8 — revise — silence — vacatur moves the proceeding to `VACATED`, terminal — impl `proceedings.py:244-246` (test helpers already enumerate `VACATED`).
- §3.9 — insert — silence — state registrations list with `product_id`/`state_code`/`status` filters — impl `state_registrations.py:89-98`.

### Mismatch revisions (PRD wording defective; 3 sites)

- §2.1 + §3.3 + §2.8-stage-10 — **self-contradiction**: §2.1's blanket ownership sentence assigned study submission to `ERR_NOT_RESOURCE_OWNER` while §3.3 and §2.8 stage 10 assign it `ERR_STUDY_PARENT_MISMATCH`; impl (`studies.py:99-104`) fires `ERR_STUDY_PARENT_MISMATCH` at the ownership pipeline position, ahead of the stage-7 application-status gate. Revised all three passages to pin impl's resolution (specific beats general; matches the known-site resolution).
- §2.8 stage 3 + §3.8 — **unimplementable as stated**: the stage-3 placement of the existing-stocks conditional requiredness is keyed on the proceeding's persisted type, so it cannot run before existence resolution; impl necessarily evaluates it at issuance. Pinned the impl order in §3.8: step gate → segregation of duties → stocks payload rules (`proceedings.py:148-200`).
- §3.7 completion — **over-specification with identical observable behavior**: "no other non-terminal case remains" literally includes `SCHEDULED`, but impl counts only `OPEN`/`DCI_PENDING`/`UNDER_REVIEW` siblings (`review_cases.py:115-124`); the divergence is unreachable (a `SCHEDULED` sibling cannot coexist with a completable case while the product is `UNDER_REVIEW`) and impl's reading matches §3.8's reinstatement carve-out. Revised to impl's set.

### IMPL BUGS (PRD unchanged on these points)

The PRD consistently uses "recording" (parallel to "stamping", and §2.1's "recorded as" for persisted refs) for six optional annotations that the impl validates and then discards — none is persisted or exposed in the resource:

- §3.2 "optionally recording `deficiency_notes`" — validated at `applications.py:239-240`, never stored (application row, `applications.py:84-99`, has no such field).
- §3.5 "optionally recording `decision_notes`" (amendment decisions) — validated at `amendments.py:232-233`, never stored.
- §3.6 "optionally recording a `lift_reason`" — validated at `bulletins.py:108-109`, never stored (bulletin row `bulletins.py:83-97`).
- §3.7 "optionally recording a `completion_summary`" — validated at `review_cases.py:94-95`, never stored.
- §3.8 "optionally recording `hearing_notes`" — validated at `proceedings.py:118-119`, never stored.
- §3.9 "optionally recording a `reason`" (revocation) — validated at `state_registrations.py:173-174`, never stored.

(Request-side-verb fields — withdraw `reason` ×2, study `decision_notes` "may carry", `vacatur_reason` "supplying" — were adjudicated as request annotations and are consistent with impl.)

### Coverage evidence

All 47 endpoint rows in §4 plus the platform clock were walked: clock set; active-ingredient create/list; product create/list/get/reinstate + 4 sub-resource lists; application create/list/get/submit/withdraw/review-decisions + 2 sub-lists; study create/list/get/review-decisions; risk-assessment create; tolerance create; amendment create/list/get/withdraw/review-decisions; certification create/list/renew; bulletin create/lift; review-case create/get/complete + DCI sub-list; DCI create/get/respond; proceeding create/list/get/hear/issue-order/vacate/disposal; state-registration create/list/get/review-decisions/revoke/renew. Calculations verified: dietary exposure (SCREENING/REFINED/fallback, 4dp-term→sum→3dp order), all three quotients, LOC inclusive thresholds on rounded values, amendment timeline (base + 3 adders + expedited ceil-halving, `priia_category`), renewal fee (months-overdue formula, 10%/month half-up penalty, anniversary carryover from previous `renewal_due_at`), existing-stocks deadlines (FIXED 365/730, DEPLETION ceil + 2×), EPA-RR minting, bulletin wrap month set. State machines verified: all 12 entity graphs including the 4-step sweep order/operators, delinquency and cancellation cascades, vacatur restore markers, and per-route §2.8 pipeline check order. All known interpretation sites from the brief were confirmed already pinned except the ones now pinned above (proceedings-create vs CANCELLED, issue-order check order, pagination clamping, NEW_USE tolerance/commodity dependency, cas_number error id, final_classification-on-deny, missing-payment→402).

Orchestrator adjudication of the 3 mismatch revisions (per lost-scaffold-intent check): (1) §2.1 vs §3.3 verified as a genuine PRD self-contradiction — specific beats general is correct; (2) stage-3 stocks placement verified unimplementable pre-resolution — revision correct; (3) §3.7 completion set — verified PRD_FINALIZED §3.8 (line 240) already pinned the identical {OPEN, DCI_PENDING, UNDER_REVIEW} semantics for reinstatement, and manual case creation is refused while the product is UNDER_REVIEW (§3.7 line 210: manual create requires REGISTERED), so the divergence is genuinely unreachable and the revision aligns §3.7 with the already-pinned sibling. ACCEPTED all three. Orchestrator artifact check: PRD_COMPLETED.md = 369 lines / 70,929 chars; all 22 diff hunks reviewed line-by-line against the bullet list — no unstated changes, nothing stripped.

## Step 9b: Impl Fix for Step 9 IMPL BUGS + Re-sweep — 2026-10-02T14:05:00.000Z

Step 9b complete. All 6 PRD-mandated persistence fixes applied, smoke-verified live, and the 8-round sweep is green 87/87 in every round.

### The 6 edits (identical pattern: `if data.get(<field>) is not None: row[<field>] = data[<field>]`, inserted at the transition-stamp point)

All under `workspace/implementation/routes/`:

1. `applications.py:259` — DEFICIENCY branch of `decide_application`: stores `deficiency_notes` alongside `status`/`deficiency_count` (PRD §3.2).
2. `amendments.py:248` — `decide_amendment`: stores `decision_notes` right after the shared `decided_at` stamp, covering both APPROVE and REJECT (PRD §3.5).
3. `bulletins.py:120` — `lift_bulletin`: stores `lift_reason` with `lifted_at` (PRD §3.6).
4. `review_cases.py:113` — `complete_case`: stores `completion_summary` with `completed_at` (PRD §3.7).
5. `proceedings.py:129` — `hear_proceeding`: stores `hearing_notes` with `hearing_held_at` (PRD §3.8).
6. `state_registrations.py:184` — `revoke_state_registration`: stores `reason` with the REVOKED transition (PRD §3.9). Verified the create path has no pre-existing `reason` key, so no collision.

Excluded per adjudication: study `decision_notes` ("may carry"), application/amendment withdrawal `reason`, and `vacatur_reason` ("supplying") — left unpersisted. Verified `envelope.serialize` passes non-underscore row keys through verbatim before editing, so no serializer changes were needed. All 6 files pass `py_compile`. No changes to validation, status codes, creation-time keys, or any other behavior; no edits to PRD.md, PRD_COMPLETED.md, test_suite/, or test_helpers/ (test file mtimes all predate this session).

### Smoke evidence (live server on port 35777, killed exactly the PID started)

- Deficiency WITHOUT the field → GET application: `status=DATA_DEFICIENCY, deficiency_count=1`, `deficiency_notes` key **absent**.
- Resubmit (empty body), then DEFICIENCY with `{"deficiency_notes": "residue chemistry rationale incomplete"}` → GET: `deficiency_notes='residue chemistry rationale incomplete'`, `deficiency_count=2` — exact string persisted and returned.
- Resubmit, then DEFICIENCY with explicit `"deficiency_notes": null` → treated as omission (§2.8 stage 3): no write, no error; previously stored value retained (PRD defines no clearing rule).
- Bulletin flow: create bulletin (reviewer) → lift with `{"lift_reason": "consultation resolved; species delisted"}` → response `status=LIFTED, lift_reason='consultation resolved; species delisted'`.

### 8-round sweep (per-test-server isolation, 87 tests/round)

All 8 rounds: passed=87 total=87 failed=0. All 8 `results.{1..8}.json` files left in place at `workspace/implementation/`. The implementation now persists all six "optionally recording" annotations exactly as the PRD contracts; PRD_COMPLETED.md stands untouched.

Orchestrator verification: all 6 store sites confirmed in source (`applications.py:258-259`, `amendments.py:247-248`, `bulletins.py:119-120`, `review_cases.py:112-113`, `proceedings.py:128-129`, `state_registrations.py:183-184` — entity-named row variables, store-on-supply, null≡omission honored); all 8 results files re-read: 87/87/0 each; PRD_COMPLETED.md untouched (70,929 chars, mtime 13:51 predates 9b); no test_helper/test_suite .py file newer than PRD_COMPLETED.md; pre-fix safety check confirmed no exact-body dict-equality assertions exist in the suite (only set comparisons on subfields), so the new response keys could not break any test.
