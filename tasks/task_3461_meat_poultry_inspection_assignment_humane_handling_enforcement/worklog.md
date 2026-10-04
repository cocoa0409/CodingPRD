# Worklog — task_3461_meat_poultry_inspection_assignment_humane_handling_enforcement

## Step 1: Create task directory — 2026-10-02T08:15:29.536Z

Pre-allocated task directory verified at `tasks/task_3461_meat_poultry_inspection_assignment_humane_handling_enforcement/` with `workspace/` inside. No new index computed (per command args).
## Step 2: Generate scaffold — 2026-10-02T09:54:12.406Z

All three scaffold artifacts are complete, lint-clean, and verified. Summary:

**(a) Line counts** — `SCAFFOLD.yaml`: 1573; `SCAFFOLD_DIFFICULTY_DESIGN.yaml`: 1574; `SCAFFOLD_CORNER_DESIGN.yaml`: 2154. All under `/home/ubuntu/github/CodingPRD/tasks/task_3461_meat_poultry_inspection_assignment_humane_handling_enforcement/`.

**(b) Endpoint count** — 54 (53 under `/inspection` + 1 platform clock endpoint). This exceeds the >40 caution threshold from past runs — justified here by the scenario's 8 mandated subsystems (grants, staffing/coverage, NRs, enforcement, humane handling, sampling, labels, recalls, appeals); the 18 GETs are trivial and all FK-reverse-reachability is lint-verified.

**(c) Instance counts** — §1.8: 19 non-stub instances (2 per rule × 9 rules, with `combinatorial_formula` carrying 3 to cover modes a/b/c). §1.9: 49 non-stub + 6 `excluded_because` stubs; per-section full breakdown: entities 8, state_machines 12, calculations 4, validations 6, endpoints 5, errors 4, rbac 5, complexity_layers 4, consistency_model 1.

**(d) YAML integrity** — every append was parse-checked; final parses confirm: SCAFFOLD.yaml has no `scaffold_difficulty_design`/`scaffold_corner_design` keys; the other two files each have exactly their single required top-level key. `scaffold_lint.py` verdict, verbatim: "VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5" (694 calls scanned). An additional grounds-resolver I ran confirms every `grounds:` reference and every stub's `difficulty_instance` citation resolves.

**(e) api_prefix / entities** — `api_prefix: /inspection`. Entities (13): Establishment, GrantApplication, Inspector, ShiftWindow, ShiftAssignment, NoncomplianceRecord, EnforcementAction, HumaneHandlingEvent, PathogenSample, LabelApplication, Recall, RecallEffectivenessCheck, Appeal.

**(f) Named-but-unvalued symbolic constants** — none; all constants carry literal values. Pinned set: NR_ESCALATION_THRESHOLD=3 / NR_ESCALATION_WINDOW_DAYS=90; TRAVEL_BUFFER_MINUTES=30; SALMONELLA_STANDARD_RATE=0.10, CAMPYLOBACTER_STANDARD_RATE=0.15, SAMPLING_WINDOW_DAYS=90, MIN_SAMPLES_FOR_CATEGORIZATION=10; recall classes (10 @ 0.95 / 5 @ 0.80 / 4 @ 0.75); compliance penalty 10/3 per family with pinned round-then-sum order; enforcement priority 10/open-NR + 25/suspension, tiers 50/100, bonuses 5/10/15 with base-before-bonus order; risk weights 2/3/5/1/1 with 30/60/90 recency bands; label doc minimums 2/2/3/1; withdrawal rule 30-day abatement or 2 suspensions in 365 days.

**(g) Time model** — logical clock via `POST /_clock/set_current_utc` (input `to_iso8601`, role ProgramAdministrator), **outside** the `/inspection` prefix. Fixed startup default `2026-09-01T00:00:00Z` with no wall-clock fallback, stated in the endpoint description; all 90-day windows, future-observation checks, and recall/abatement day-counts evaluate against it.

Key design choices for the "harder than expert" directive: parallel state dimensions on Establishment (grant × inspection), cyclic machines on NR (appeal loop), GrantApplication and LabelApplication (resubmission loops) and Recall (re-classification cycle), a depth-3 cascade (egregious humane confirm → auto-SUSPENSION → establishment SUSPENDED → windows BLOCKED + labels HELD), a depth-2 cascade (sample result → CAT_3 → auto NOTICE), segregation-of-duties on appeals and humane confirmation, two OCC concurrency rules (establishment + shift window), and rounding/evaluation-order-pinned calculations whose alternatives produce measurably different literals (90.1 vs 90.0; 100 vs 105). Two mid-flight repairs worth noting: the GrantApplication `withdraw` endpoint was added after I caught its state-machine trigger dangling, and grant-of-inspection chains were inserted into 12 test recipes whose window/sample/humane-suspension steps would otherwise have failed the GRANTED gate (found by replaying each chain against §1.2/§1.4).

Orchestrator verification (post-hand-back, independent): all three files parse via yaml.safe_load; top-level-key checks pass; api_prefix=/inspection and all 13 entity names confirmed present in SCAFFOLD.yaml (no foreign-domain bleed); endpoint_count=54 (>40 → Step 6 prompt will be pre-constrained); clock endpoint `/_clock/set_current_utc` confirmed OUTSIDE api_prefix; measured non-stub instances: §1.8=19, §1.9=49, total=68.


## Step 3: Copy shared files — 2026-10-02T09:54:22.260Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-10-02T10:15:24.904Z

All checks pass. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_3461_meat_poultry_inspection_assignment_humane_handling_enforcement/workspace/PRD.md`.

## Summary

**(a) Line count:** 353 lines — §1 Introduction (2 paragraphs), §2.1–2.11 global specifications, §3.1–3.9 business workflows, §4 endpoint table (54 rows), §5 error catalogue (35 rows). Ends at §5 with no audit footer.

**(b) Programmatic cross-check (Python vs parsed SCAFFOLD.yaml) — all PASS:**
- **Error IDs:** 35/35 present verbatim, each with its trigger condition stated in the §2.7 ten-tier validation pipeline or the relevant §3 workflow, including precedence (existence left-to-right before OCC before state before qualification before temporal before eligibility before referential before SoD; SoD explicitly evaluated after state so a non-`FILED` appeal reports `ERR_INVALID_STATE` first).
- **Field names:** 74/74 entity fields + 53/53 endpoint input/query identifiers appear in backticks.
- **Endpoint paths:** 54/54 in the §4 table (4 columns only).
- **Constants:** 18/18 semantic constant checks pass — 90-day rolling/sampling/escalation windows, 30/60/90 recency bands with factors 3/2/1, family weights 2/3/5/1/1, standards 0.10/0.15 with pinned boundary-equality rules, penalty 10/3 with pinned nested rounding (round each family penalty to 0.1 first, then subtract; scaffold's own 90.1-vs-90.0 discriminator included), benchmark 80.0, priority base 10/25 with tiers 100/50 and bonuses 15/10/5 (tier from base alone, never post-bonus), escalation threshold 3 exactly-at-threshold-fires, recall classes 10/0.95, 5/0.80, 4/0.75 with equality-closes-effective, label minimums 2/2/3/1 at-minimum-passes, withdrawal 30-day/2-suspension/365-day conditions, 30-minute travel buffer, 20-char abatement, 10-char grounds.
- **Enums/states:** 95/95 values present; 37/37 state-transition pairs expressed in §3 with trigger, actor, preconditions, and every cascade side-effect (suspension/withdrawal/lift cascades, egregious-humane auto-`IN_EFFECT` suspension, CAT_3 auto-notice, escalation auto-`PROPOSED` suspension, inspector-deactivation cancellation, recall re-classification counter reset).
- **§2.2** emitted byte-for-byte verbatim; **§3 path purity:** 597 backtick tokens scanned, 0 path/method violations.

**(c) Clock endpoint:** documented at its unprefixed path `POST /_clock/set_current_utc` in both §2.4 and §4, with input field `to_iso8601`, ProgramAdministrator-only authorization, fixed startup default `2026-09-01T00:00:00Z`, and explicit no-wall-clock-fallback. Confirmed no `/inspection/_clock` string exists.

**(d) Scaffold tensions rendered:**
1. `status_before_appeal`'s field description ("status the NR returns to if REMANDED") contradicts the state machine, which twice (NR transition APPEALED→OPEN and Appeal REMANDED side-effect) pins REMAND as returning the record to `OPEN` unconditionally. I rendered per the doubly-specified machine: the field records the status at filing time; REMAND returns the record to `OPEN`.
2. Validation priority groups 7 and 8 carry group-level HTTP statuses that disagree with the error catalog for individual errors (`ERR_ASSIGNMENT_OVERLAP`/`ERR_TRAVEL_BUFFER_VIOLATION` are 409 in the catalog vs the group's 422; `ERR_INSUFFICIENT_DOCUMENTATION` is 422 vs the group's 409). I rendered each error with its authoritative catalog status everywhere.

Orchestrator spot-check (independent): PRD.md 353 lines; clock endpoint present at unprefixed path (lines 82, 258); zero `inspection/_clock` leaks; all 35 scaffold error_ids and all 54 scaffold endpoint paths confirmed present in PRD via programmatic diff; constant tokens (2026-09-01T00:00:00Z, 0.10, 0.15, 90.1, to_iso8601) all present.


## Step 5a: Generate test helpers (Stage 1 of split Step 5) — 2026-10-02T10:47:00.955Z

Stage 5a is complete. All verification gates pass.

## (a) Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_3461_meat_poultry_inspection_assignment_humane_handling_enforcement/`)

| File | Lines |
|---|---|
| `test_helpers/__init__.py` | 183 |
| `test_helpers/types.py` | 431 |
| `test_helpers/api_client.py` | 277 |
| `test_helpers/api_errors.py` | 104 |
| `test_helpers/assertions.py` | 365 |
| `test_helpers/factories.py` | 390 |
| `test_helpers/constants.py` | 155 |
| `test_helpers/test_users.py` | 128 |
| `test_helpers/fixtures.py` | 879 |
| `test_suite/conftest.py` | 68 |

No `test_*.py` files written — that is Stage 5b's job.

## (b) Frozen public API surface (Stage 5b codes against this)

- **types.py** — `UserRole`; enums `SpeciesClass, RegulationFamily, GrantStatus, InspectionStatus, PathogenCategory, AdequacyDimension, AdequacyFinding, GrantDecision, GrantApplicationStatus, EmploymentStatus, ShiftType, ShiftWindowStatus, ShiftAssignmentStatus, NoncomplianceRecordStatus, VerifyOutcome, EnforcementActionType, EnforcementBasis, EnforcementActionStatus, HumaneSeverity, HumaneEventStatus, Pathogen, SampleResult, LabelClaim, LabelDecision, LabelApplicationStatus, RecallReasonCode, RecallClass, RecallStatus, EffectivenessOutcome, AppealOutcome, AppealStatus`; TypedDicts `Establishment, GrantApplication, Inspector, ShiftWindow, ShiftAssignment, NoncomplianceRecord, EnforcementAction, HumaneHandlingEvent, PathogenSample, LabelApplication, Recall, RecallEffectivenessCheck` (append-only: no `updated_at`/`version`), `Appeal`.
- **api_client.py** — `canonical_instant(value)`, `class ApiClient(GenericApiClient)` with 54 methods (one per scaffold endpoint — route audit: 54 declared = 54 implemented, zero diff). Highlights: `set_clock(payload, headers)`; CRUD/action methods named `create_establishment`, `get_establishment`, `create_grant_application`, `list_grant_applications(est_id, headers, params=None)`, `begin_grant_review`, `record_adequacy`, `decide_grant_application`, `resubmit_grant_application`, `withdraw_grant_application`, `create_inspector`, `deactivate_inspector`, `create_shift_window`, `list_shift_windows`, `get_shift_window`, `verify_coverage`, `create_assignment(window_id, payload, headers)`, `list_shift_assignments(headers, params)`, `get_shift_assignment`, `confirm_assignment`, `cancel_assignment`, `create_noncompliance_record`, `list_noncompliance_records(headers, params)`, `get_noncompliance_record`, `respond_to_nr`, `verify_nr_response`, `create_enforcement_action(est_id, payload, headers)`, `list_enforcement_actions(est_id, headers, params)`, `activate_enforcement_action`, `lift_enforcement_action`, `create_humane_event`, `list_humane_events`, `get_humane_event`, `confirm_humane_event`, `dismiss_humane_event`, `create_pathogen_sample`, `list_pathogen_samples`, `get_pathogen_sample`, `record_sample_result`, `create_label_application`, `list_label_applications(est_id, ...)`, `begin_label_review`, `decide_label_application`, `resubmit_label_application`, `create_recall`, `get_recall`, `list_recalls`, `determine_recall_class`, `record_effectiveness_check`, `list_effectiveness_checks`, `close_recall`, `create_appeal`, `list_appeals(nr_id, ...)`, `decide_appeal`. **No module-level singleton** — `test_helpers.api_client` is always the module (importlib-verified).
- **api_errors.py** — `ApiErrorId` (all 34 PRD §5 codes), `HTTP_STATUS_CODES`, registered via `set_error_http_status_map` at import.
- **assertions.py** — `validate_success(response, expected_status)` (**required arg, no default** — verified via signature introspection), `assert_instant`, `assert_instant_format`, `assert_envelope_meta`, `assert_list_page(meta, limit, offset, total_count, has_more)`, `assert_establishment` (+`assert_establishment_scores`), `assert_grant_application`, `assert_inspector`, `assert_shift_window`, `assert_shift_assignment`, `assert_noncompliance_record`, `assert_enforcement_action`, `assert_humane_event`, `assert_pathogen_sample`, `assert_label_application`, `assert_recall`, `assert_effectiveness_check` (asserts absence of `version`/`updated_at`), `assert_appeal`.
- **factories.py** — `iso_add_minutes/days/seconds`; defaults `DEFAULT_OBSERVED_AT/COLLECTED_AT/CHECKED_AT` (all strictly **before** the 2026-09-01 boot clock), `DEFAULT_SHIFT_START/END` (2026-09-02 06:00–14:00Z); payload builders `clock_payload, establishment_payload, grant_application_payload, adequacy_payload, grant_decision_payload, grant_resubmit_payload, inspector_payload` (auto-unique badge numbers via process-wide counter), `shift_window_payload, assignment_payload, nr_payload, nr_response_payload, verify_response_payload, enforcement_action_payload, lift_payload, humane_event_payload, pathogen_sample_payload, record_result_payload, label_application_payload, label_decision_payload, label_resubmit_payload, recall_payload, determine_class_payload, effectiveness_check_payload, appeal_payload, appeal_decision_payload`.
- **constants.py** — `CLOCK_START_ISO`, 7 `ROLE_*` + `ALL_ROLES`, pagination (10/1/100/0), risk (`RISK_ROLLING_WINDOW_DAYS=90`, weights 2/3/5/1/1 + `FAMILY_RISK_WEIGHTS`, recency bands 30/60 with factors 3/2/1), compliance (`NR_PENALTY_NUMERATOR=10`, `NR_PENALTY_DENOMINATOR=3`, `COMPLIANCE_PASS_THRESHOLD=80.0`), priority (`OPEN_NR_POINTS=10`, `SUSPENSION_POINTS=25`, tiers 100/50, bonuses 15/10/5), escalation (`NR_ESCALATION_THRESHOLD=3`, window 90), pathogen (`SAMPLING_WINDOW_DAYS=90`, `MIN_SAMPLES_FOR_CATEGORIZATION=10`, rates 0.10/0.15), recall classes (10/0.95, 5/0.80, 4/0.75 + `RECALL_CLASS_REQUIREMENTS`), label docs (2/2/3/1 + `LABEL_DOC_MINIMUMS`), `TRAVEL_BUFFER_MINUTES=30`, withdrawal (30 days / 2 suspensions / 365 days), `APPEAL_GROUNDS_MIN_CHARS=10`, `ABATEMENT_EVIDENCE_MIN_CHARS=20`.
- **test_users.py** — `TEST_USERS` (header-dict values), opaque constants `DISTRICT_MANAGER_HEADERS, LABEL_OFFICER_HEADERS, RECALL_COORDINATOR_HEADERS, PROGRAM_ADMINISTRATOR_HEADERS`; entity-backed builders `make_establishment_manager_headers(est_id)`, `make_inspector_headers(inspector_id)`, `make_supervisory_reviewer_headers(inspector_id)`; malformed-header probes `headers_without_role`, `headers_without_user_id`, `headers_with_undeclared_role`, `make_headers`.
- **fixtures.py** — 58 functions: `set_clock` (clock-first), `create_establishment/inspector/inspector_pair`, grant chain (`create_grant_application`, `begin_grant_review`, `record_adequacy`, `record_all_adequate`, `decide_grant`, `create_granted_establishment`), windows (`create_shift_window`, `setup_granted_with_window`, `add_assignment` with auto-fresh OCC version, `confirm_assignment`, `cancel_assignment`, `verify_coverage`, `create_and_confirm_assignment`, `setup_verified_covered_window`), NRs (`issue_nr`, `respond_to_nr`, `verify_nr`, `escalate_nr`, `get_nr`, `list_nrs`), enforcement (`create_enforcement_action` with auto-fresh OCC version, `list_enforcement_actions`, `activate_enforcement`, `lift_enforcement`), humane (`report_humane_event`, `confirm_humane_event`, `dismiss_humane_event`, `suspend_establishment_via_egregious_event`, `suspend_and_lift_via_egregious_event`), pathogen (`collect_pathogen_sample`, `collect_pathogen_samples`, `record_sample_result`, `categorize_pathogen(positives/negatives)`), labels (`submit_label_application`, `begin_label_review`, `decide_label`, `resubmit_label`, `create_label_in_review`, `create_approved_label`, `list_label_applications`), recalls (`create_recall` — not grant-gated, `determine_recall_class`, `record_effectiveness_check(s)`, `close_recall`, `create_class_determined_recall`, `create_closed_recall`), appeals (`file_appeal`, `decide_appeal`, `create_vacated_nr`), threshold targeting (`issue_and_escalate_nrs`). All ownership-pinned calls thread `make_*_headers(entity["id"])`.
- **conftest.py** — fixtures: `api` (function-scoped `ApiClient()`, reads `API_BASE_URL` from env; fresh Session per test against per-test server restarts), 4 opaque-role header fixtures, 3 fallback entity-backed header fixtures (documented non-ownership-only).

## (c) Constants defined-vs-referenced diff

Programmatic AST audit: 59 constants defined; referenced-but-undefined set is **EMPTY** (residual tokens were docstring words and `TEST_USERS`, which lives in test_users.py). Every constant traces to a PRD-pinned formula quoted in the module docstring and to at least one design-index instance.

## (d) Verification results

- AST parse of all 10 files: **0 syntax errors**.
- Import smoke test (`import test_helpers.{api_client, factories, fixtures, constants, assertions, api_errors, types, test_users}` with PYTHONPATH=task dir): **pass**.
- Route audit vs SCAFFOLD endpoints: 54/54 implemented, none extra.
- `pytest --collect-only test_suite/`: conftest loads cleanly (0 tests, as expected).
- `validate_success` signature check: `expected_status` has no default.

## (e) Clock exposure

`ApiClient.set_clock(payload, headers)` issues `self._request("POST", "/_clock/set_current_utc", ...)` — the literal unprefixed path, never routed through any `/inspection` helper. Fixtures advance time only via `fixtures.set_clock(api, iso)` (ProgramAdministrator headers); `create_granted_establishment`/`setup_*` accept a `clock=` kwarg that sets the clock **first**. No wall-clock use anywhere; no hardcoded port (base URL from `API_BASE_URL` env).

## (f) PRD ambiguities resolved

1. **Future-dated design-recipe literals (clock-unreachable setups).** Multiple recipes (e.g. D4's NRs at `2026-09-01T06:00:00Z`, D6/D8 humane events, CA2/C6 recall checks, D3 samples on 2026-09-03) place `observed_at`/`collected_at`/`checked_at` *after* the boot clock `2026-09-01T00:00:00Z`, which PRD §2.4 rejects: "An `observed_at`, `collected_at`, or `checked_at` that lies after the logical clock is rejected with `ERR_FUTURE_OBSERVATION` (HTTP 422)" — and corner instance V6 pins exactly that. Resolution: all fixture timestamp **defaults sit strictly before the boot clock** (2026-08-31/2026-08-20); Stage 5b must either use these defaults or call `set_clock` to a later instant **before** building such recipes, and re-derive the literal assertions (e.g. D4's `compliance_score == 90.1` requires the three NRs to actually exist).
2. **Reviewer identity must be a real Inspector row.** PRD §2.1: "When `X-User-Role` is `SupervisoryReviewer`, `X-User-ID` is likewise the `id` of an Inspector entity". A PRD reader could plausibly 404 a nonexistent reviewer id, so `create_inspector_pair` mints two real inspectors and SoD paths use the reviewer's actual id (never a bare constant).
3. **Recall creation is not grant-gated.** The corner recipes (C6, C8, SM5/6, CA2, EP3, RB3) create recalls on UNGRANTED establishments; PRD §3.8 names no grant gate for `POST /inspection/recalls` (unlike pathogen sampling, §3.6). `create_recall` therefore takes any establishment id without a grant chain.
4. **Timestamp comparison leniency.** PRD §2.9 mandates "three fractional digits" while design literals write `2026-09-01T00:00:00Z`; `canonical_instant` + `assert_instant` compare instants semantically so both spellings of one instant match.
5. **SupervisoryReviewer existence check**: recipes (RB4/RB5) pass real inspector ids for reviewers; fixtures follow suit.

## Hand-off notes for Stage 5b

Measured queues (verified programmatically, not from the index's own claims): **19 difficulty instances** (≥2 tests each, tag `Design: Difficulty/<rule_id>/<name>`) and **49 non-stub corner instances** (≥1 test each, tag `Design: Corner/<section>/<name>`); 6 corner stubs all resolve to real difficulty instances and are not translated. Creates return 201, everything else 200 — pass the status explicitly to `validate_success`.

Orchestrator verification (independent): all 10 helper files + conftest present on disk; error-code 3-way diff (PRD §5 vs SCAFFOLD catalog vs test_helpers/api_errors.py) — 35/35/35, all three sets identical (the subagent's "34 codes" prose miscounted; the file is complete).


## Step 5b: Generate test suite (Stage 2 of split Step 5) — 2026-10-02T11:36:25.302Z

Stage 5b complete. The frozen helper surface is untouched (all `test_helpers/` files retain their Stage 5a mtimes; only `test_suite/test_*.py` files were written).

## Summary

**(a) Test files written — 19 files, 3121 lines** (each in a single Write, all ≤ 239 lines, well under the cap):

Queue A (9 files, one per §1.8 rule): `test_difficulty_dual_variant_calc.py` (160), `test_difficulty_combinatorial_formula.py` (217), `test_difficulty_non_linear_state_machine.py` (171), `test_difficulty_transitive_cascade.py` (180), `test_difficulty_priority_pair.py` (~165), `test_difficulty_boundary_precision.py` (157), `test_difficulty_cross_entity_state.py` (145), `test_difficulty_resource_temporal_overlap.py` (164), `test_difficulty_compensating_invariant.py` (163).

Queue B (10 files, one per §1.9 section; state_machines split a/b): `test_corner_entities.py` (239), `test_corner_state_machines_a.py` (214), `test_corner_state_machines_b.py` (206), `test_corner_calculations.py` (152), `test_corner_validations.py` (205), `test_corner_endpoints.py` (133), `test_corner_errors.py` (119), `test_corner_rbac.py` (151), `test_corner_complexity_layers.py` (138), `test_corner_consistency_model.py` (40).

**(b) Total test functions: 86** (38 difficulty + 48 corner).

**(c) Tag audit (real AST walk against both YAMLs):** (i) Difficulty 19/19 instances with ≥2 tests each (38 tests); Corner 48/49 non-stub instances with ≥1 test (48 tests). (ii) One zero-test instance — the adjudicated skip below. (iii) Tags pointing at nonexistent instances: 0; stub citations: 0. (iv) Missing/duplicate/non-terminal-line tags: 0.

**(d) Skipped instance (1):** `Corner/endpoints/combined_filters_on_noncompliance_records` — fails unique derivability. The PRD never names query-filter parameters: §2.3 names only `limit`/`offset`, and the §4 row "List/filter noncompliance records" is endpoint-titular. The asserted conjunctive composition of `establishment_id` × `regulation_family` × `status` (2-of-4 rows) is not derivable by a PRD-only reader. (The sibling pagination instance survives because I translated it without any filter param — the single-establishment world makes the unfiltered list equivalent, and §2.3 pins all the asserted pagination math.)

**(e) Helper gaps: none blocking.** Two recipes asserted `GET …/noncompliance-records?establishment_id=…` row counts (also not PRD-named params) — expressed with the unfiltered `list_nrs()`/`validate_paginated` instead, equivalent because each test's world contains only its own rows. Clock-illegal recipe literals (observed_at/collected_at after the 2026-09-01 boot clock in D1/D6/D8/D15-style setups) were re-derived to pre-boot literals per the handoff note, except A2's rolling-window choreography which keeps its explicit `set_clock` chain (its asserted math depends on issuance dates). `state_beats_safety_on_assignment_create` was adjudicated TRANSLATE: §2.7 tier-5 "terminal-state lockdown" + §3.2's "Windows in VERIFIED_COVERED or BLOCKED are terminal" + the explicit "optimistic concurrency first, then state, then qualification" pipeline order jointly derive the 409/ERR_INVALID_STATE assertion.

**(f) Verification:** `pytest --collect-only` (PYTHONPATH=task dir) collects **86 tests with zero errors**; pyflakes clean; the verbatim-citation sweep matched all **132 quoted PRD citations** against PRD.md (three initially-abbreviated quotes were expanded to full sentences to satisfy C3). No `skip`/`xfail` markers anywhere.

Orchestrator verification (independent AST audit + collection): expected tags from YAMLs = 68; emitted = 86 test fns across 67 distinct tags; zero untagged; zero tags resolving to nonexistent instances; exactly one zero-test instance = the adjudicated skip above; `pytest --collect-only` independently re-run: 86 tests collected, 0 errors.


## Step 6: Generate implementation — 2026-10-02T12:24:01.790Z

Implementation complete and verified. Final report:

## Summary

### (a) File inventory — `workspace/implementation/` (absolute paths under `/home/ubuntu/github/CodingPRD/tasks/task_3461_meat_poultry_inspection_assignment_humane_handling_enforcement/workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | Launcher: guarded pip install, `exec python3 app.py`, `$PORT` (default 10000), `0.0.0.0` |
| `requirements.txt` | 1 | `flask==3.1.3` (only import) |
| `app.py` | 91 | Flask bootstrap, blueprint registration, `POST /_clock/set_current_utc`, error handlers |
| `store.py` | 178 | In-memory store (empty at every boot, zero seeding), logical clock (default `2026-09-01T00:00:00Z`, no wall-clock fallback), id/timestamp/version helpers, serializer |
| `errors.py` | 65 | ApiError + the full PRD §5 catalog with verbatim HTTP statuses |
| `envelope.py` | 107 | `meta`/`response_type`/`data` envelope, pagination meta, body parsing |
| `authz.py` | 46 | X-User-ID/X-User-Role extraction, 7-role RBAC, ownership pins |
| `validate.py` | 116 | Field-shape validators (all `ERR_INVALID_REQUEST` conditions) |
| `calc.py` | 324 | All 8 calculation rules (coverage gap, risk scores, compliance nested rounding, priority tiers, pathogen categorization as exact rationals, escalation count, recall class requirements, label minimums, enforcement eligibility) |
| `cascades.py` | 173 | Suspension/withdrawal/withhold/lift cascades, auto-action creators, deactivation cascade |
| `guards.py` | 42 | Existence + establishment state gates |
| `routes_establishments.py` | 63 | Register + read with derived scores |
| `routes_grants.py` | 167 | Grant application lifecycle (6 endpoints) |
| `routes_inspectors.py` | 49 | Onboard (unique badge) + deactivate |
| `routes_windows.py` | 117 | Shift windows + verify-coverage with dual gap variants and slaughter auto-NR |
| `routes_assignments.py` | 163 | Assignment creation under OCC with all 5 gate tiers, confirm, cancel, reads |
| `routes_nrs.py` | 134 | NR issuance, respond, verify/escalate with threshold auto-proposal |
| `routes_enforcement.py` | 125 | Propose (OCC) / activate (eligibility re-evaluated) / lift |
| `routes_humane.py` | 107 | Report, confirm/dismiss with SoD, egregious IN_EFFECT suspension cascade |
| `routes_pathogens.py` | 112 | Sampling, record-result, sticky categorization, per-pathogen CAT_3 transition notice |
| `routes_labels.py` | 132 | Label lifecycle with 3-gate approval and pre-hold status restore |
| `routes_recalls.py` | 176 | Recall lifecycle, append-only checks (id+created_at only), computed closure, reclassification cycle |
| `routes_appeals.py` | 99 | Filing (NR→APPEALED), supervisory decide with SoD |

Each file was written complete in a single Write call; no appends, no truncation.

### (b) Endpoint coverage
Programmatic diff of Flask url_map vs SCAFFOLD.yaml endpoint table: **54 declared, 54 implemented, 0 missing, 0 extra** (including the unprefixed `POST /_clock/set_current_utc`).

### (c) State-machine coverage
The §1.2 machine tables contain **50 transition rows** (Establishment 4, GrantApplication 7, Inspector 1, ShiftWindow 5, ShiftAssignment 2, NR 11, EnforcementAction 2, Humane 2, PathogenSample 2, Label 7, Recall 4, Appeal 3) — the "37" figure in the prompt undercounts the table. All 50 are implemented with their preconditions and side effects, and all were exercised live (grant review loop, deny→resubmit, withdraw, double-withdraw 409, coverage flag→re-verify, confirm/cancel, NR respond/escalate/appeal/remand/vacate paths, escalation auto-proposal, suspension activation+lift, withhold hold/restore, withdrawal freeze, egregious cascade, categorization cascade, recall close both ways + reclassification reset).

### (d) py_compile
`python3 -m py_compile` on all 20 `.py` files: **zero errors**.

### (e) Self-smoke-test transcript
- Port: **41813** (dynamically allocated via socket bind). Server launched via `PORT=41813 bash start.sh &`, readiness confirmed.
- (a) `POST /_clock/set_current_utc` `{"to_iso8601":"2026-09-02T12:00:00Z"}` as ProgramAdministrator → **HTTP 200**, `data.current_utc` echoed.
- (b) `POST /inspection/establishments` → **HTTP 201**, full envelope with computed fields (`compliance_score: 100.0`, `version: 1`, etc.).
- (c) `GET /inspection/shift-assignments` → **HTTP 200**, `response_type: "array"`, pagination meta (`limit/offset/total_count/has_more`).
- (d) `POST /inspection/establishments` with `{"name": 42, "species_classes": []}` → **HTTP 400**, `data.error_id == "ERR_INVALID_REQUEST"` in the error envelope.
- Killed exactly the server PID I started (`kill 1310986`); port confirmed closed. No pkill/killall/pgrep patterns used.
- Beyond the mandated 4: **65 additional end-to-end checks passed** against the live server covering every state machine, both OCC 412s, all cascade directions, the pinned 90.1 nested-rounding example, pathogen boundary rates (rate==standard→CAT_2, half→CAT_1, >standard→CAT_3+notice), travel-buffer boundary (29 min rejected, exactly 30 allowed, same-establishment exempt), SoD 403s, withdrawn freeze 409, and pagination meta.

### (f) Interpretation choices (for downstream adjudication)
1. **Entity timestamps stamp from the logical clock** (created_at/updated_at/issued_at/decided_at/resulted_at/effective_at, 3-fractional-digit format); only `meta.api_request_timestamp` uses wall clock. PRD §2.4 bans wall-clock fallback but §2.6 doesn't name the source.
2. **Clock endpoint echoes the client's `to_iso8601` string** as `current_utc` (parsed internally for the clock).
3. **Withdrawal blanket (§2.5 "any subsequent operational write")** applied to every mutating endpoint rooted at a withdrawn establishment, including grant-app filing/resubmit/withdraw, NR respond/verify, appeal file/decide, recall determine-class/check/close, assignment confirm/cancel — **except enforcement lift**, which §3.4 explicitly contemplates post-withdrawal ("a withdrawn grant is never restored by a lift").
4. **Tier-5 internal ordering**: WITHDRAWN → NOT_GRANTED → SUSPENDED; on assignment creation, §3.2's own order (inspector-active first).
5. **Pathogen-sample grant check at pipeline tier 9** per §2.7's explicit placement (overrides §2.5's looser grouping) — future `collected_at` (422) beats NOT_GRANTED (409).
6. **Ownership vs existence**: body-value-pinned ownership (creates) checked before FK existence (tier 2 < tier 3); entity-pinned ownership checked after that entity's 404 (unavoidable).
7. **Field-shape placement**: create endpoints — after path existence/ownership, before FK existence and OCC (missing `expected_*_version` → 400, stale → 412); action endpoints — target state gate before payload shape ("state legality outranks business rules"); assignment interval semantics and line range at tier 7 per scaffold priority 7.
8. **Eligibility errors**: `ERR_ESCALATION_THRESHOLD_NOT_MET` for all SUSPENSION basis ineligibility (including ADMINISTRATIVE-never) and ineligible WITHHOLD_MARKS; `ERR_WITHDRAWAL_CONDITIONS_NOT_MET` for WITHDRAWAL — §5 names no other eligibility errors.
9. **WITHHOLD_MARKS eligibility read as a 4-way disjunction** regardless of named basis.
10. **Escalation auto-proposal fires on every entry into ESCALATED** while qualifying count ≥ 3 (OPEN/RESPONSE_SUBMITTED count as qualifying — verified live: 1 ESC + 2 OPEN fires).
11. **Slaughter-gap auto-NR fires on every gapped verify** of a SLAUGHTER window; its `shift_window_id` left null (PRD enumerates only family/description/observed_at/issuer/status).
12. **Auto-created actions don't bump Establishment.version** (only the manual create endpoint declares that side effect); **categorization does bump it when the category changes** (per §2.8's own example).
13. **`pathogen_category` is sticky-stored**, recomputed only at record-result; "no pathogen has sufficient samples → unchanged" means aging samples never clear it.
14. **CAT_3 transition detection is per-pathogen** ("ANY pathogen's ... transitions to CAT_3 from a different value"), firing even when the overall category was already CAT_3 via the other pathogen.
15. **REMAND returns the NR to OPEN** always — PRD §3.9 wins over the scaffold field description implying return to `status_before_appeal` (which is recorded as history only).
16. **Recall close before determine-class → `ERR_INVALID_STATE`** (PRD §3.8 wins over the scaffold catalog condition listing close under `ERR_RECALL_CLASS_REQUIRED`; that error is used only for check-recording).
17. **Second SUSPENSION activation while already SUSPENDED is allowed** (idempotent cascade; the withdrawal "≥2 suspensions IN_EFFECT or LIFTED" prong presupposes it).
18. **Egregious auto-suspension bypasses the grant check** (§3.5 states the cascade unconditionally; humane reporting has no grant gate).
19. **Post-withdrawal suspension lift leaves dimensions frozen** (inspection moves only if actually SUSPENDED).
20. **`suspension_count` derived** (SUSPENSION actions in IN_EFFECT or LIFTED) — equivalent to the machine's `+= 1`.
21. **Travel buffer**: violation iff cross-establishment intervals overlap or gap < 30 min; gap == 30 allowed; same-establishment exempt.
22. **Pagination lenient**: bad values fall back to defaults, limit clamped [1,100] (PRD names bounds but no error).
23. **Scores serialized as JSON numbers** (`compliance_score`/`effectiveness_ratio` as floats, integer scores as ints).
24. **Header-only inspector identity (verify-coverage, verify-response, record-result) is not existence-checked** — tier 3 covers path ids and body FKs, and X-User-ID is a header. Flagged for adjudication.
25. **Defensive JSON envelopes for Flask 404/405/500** (ids `ERR_NOT_FOUND`/`ERR_METHOD_NOT_ALLOWED`/`ERR_INTERNAL`) — unreachable via declared routes, outside the PRD catalog.
26. **WITHDRAWAL 365-day prong uses action `created_at` age ≤ 365 days** against the logical clock.
27. **`regulation_family` accepted-but-optional for non-NR_LINKAGE bases**, required (400) only for NR_LINKAGE.
28. **Window status does not gate assignment creation** (no such PRD gate; suspension already bars it via the establishment gate).

### (g) Contradictions found and resolutions
- Scaffold `status_before_appeal` description vs PRD §3.9 REMAND target → PRD wins (OPEN).
- Scaffold `ERR_RECALL_CLASS_REQUIRED` condition naming close vs PRD §3.8 → PRD wins (`ERR_INVALID_STATE`).
- PRD §2.5 (tier 5) vs §2.7 (tier 9) placement of the pathogen-sample grant check → §2.7 wins as the precedence authority.
- Nothing was found unimplementable; no PRD-stated check was dropped, and no guard the PRD does not state was added.

Orchestrator verification (independent): 23 files present (20 .py + start.sh + requirements.txt); py_compile clean; param-name-insensitive Flask url_map diff vs scaffold: 54/54 endpoints implemented, 0 missing, only extra is Flask's built-in /static (a naive exact-string diff false-alarms on parameter names — `<establishment_id>` vs `{id}` — as previously recorded).

## Step 7: Test-and-fix iteration loop — 2026-10-02T12:42:27.720Z

All green. Final summary:

## Summary

**Iterations run:** 2 (sweep 1: 13 unique failures, deterministic across all 8 rounds; sweep 2: all 8 rounds green, 86/86 each).

**Tests deleted:** none.

**Fixes to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_3461_meat_poultry_inspection_assignment_humane_handling_enforcement/test_helpers/fixtures.py` — `setup_granted_with_window()` gained a `name: str = "Granted Plant"` keyword, forwarded to `create_granted_establishment`. 12 failing tests across 9 files all died at setup with the identical `TypeError: ... unexpected keyword argument 'name'` — the helper simply didn't forward a kwarg its sibling already accepted. Classic upstream-fixture bug masquerading as 12 independent failures.

**Fixes to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_3461_meat_poultry_inspection_assignment_humane_handling_enforcement/test_suite/test_difficulty_priority_pair.py` — `test_terminal_window_reports_state_error_not_qualification` rewritten as `test_inactive_inspector_reports_state_error_not_qualification`. The original premise (creating an assignment on a VERIFIED_COVERED window is a tier-5 `ERR_INVALID_STATE` violation) fails unique derivability: PRD §3.2's assignment-create gate list is exhaustive (OCC → inspector-ACTIVE → establishment-not-SUSPENDED → qualification → overlap → travel buffer) with no window-state gate, and the terminal sentence is explicitly scoped — "Windows in `VERIFIED_COVERED` or `BLOCKED` are terminal and cannot be *re-verified*". Worklog Step 6 item 28 records the implementer's PRD-faithful reading. The precedence rule itself IS PRD-verbatim (§3.2 "optimistic concurrency first, then state, then qualification, then temporal rules"; §2.7 tier 6 "A deactivated inspector surfaces earlier, at tier 5, as `ERR_INSPECTOR_INACTIVE`"), so the test now exercises the same design instance (`state_beats_safety_on_assignment_create`) via the PRD-named tier-5 vehicle: a deactivated, POULTRY-only inspector against a CATTLE PLANNED window → asserts `ERR_INSPECTOR_INACTIVE` with shadow check `!= ERR_INSPECTOR_NOT_QUALIFIED` and zero assignments created.

**Fixes to `implementation/`:** none — the implementation was PRD-faithful on both counts (no window-state gate on assignment create; inspector-ACTIVE checked at tier 5 before qualification at tier 6 in `routes_assignments.py:create_assignment`).

**Artifacts:** all 8 `results.{1..8}.json` from the final clean sweep left in place in `workspace/implementation/` per the results-file preservation rule.

Orchestrator verification (independent): all 8 results files show passed=86/total=86/failed=0; results mtimes are NEWER than every test_suite/, test_helpers/, and implementation/ source file (final sweep post-dates all fixes); post-Step-7 AST tag audit re-run: 86 test functions, zero untagged, zero orphan tags, the only zero-test instance remains the Step 5b adjudicated skip `Corner/endpoints/combined_filters_on_noncompliance_records`; the rewritten priority-pair test is present.

Step 8 routing note: Step 7 produced 0 deletions, 0 implementation/ fixes, 1 test_helpers/ fix (pure fixture bug), 1 test_suite/ fix (premise rewrite against PRD §3.2). Step 8 is NOT skipped (test-side fixes exist), but per its own method both items may adjudicate as "PRD already determines behavior" — a zero-edit (byte-identical PRD_FINALIZED.md) outcome is plausible and permitted.

## Step 8: Finalize PRD — 2026-10-02T12:50:31.218Z

Done. The edit is a single intra-line sentence appended to §3.2's assignment-creation gate paragraph; everything else is byte-identical.

## Summary

**Line counts / delta:** PRD.md 353 lines vs PRD_FINALIZED.md 353 lines — 0% line delta; one intra-line insertion (one sentence) on line 167.

**Changes:**
- §3.2 — insert — appended one sentence to the assignment-creation gate paragraph: "The window's own `status` is not among these gates: assignment creation never inspects it, so a window in any status — `PLANNED`, `COVERAGE_GAP_FLAGGED`, `VERIFIED_COVERED`, or `BLOCKED` — accepts new assignments whenever all of the operation's other specified checks pass." — pins the behavior of `implementation/routes_assignments.py:39-117` (`create_assignment` never reads `window["status"]`), which no test asserts after Step 7's rewrite of `test_difficulty_priority_pair.py`.

**Per-item adjudication:**
1. **`test_helpers/fixtures.py` (`setup_granted_with_window` `name` kwarg) — no edit, pure fixture bug.** PRD §3.1 already uniquely pins the field: "A `ProgramAdministrator` registers each establishment by supplying its `name`, the `species_classes` it handles — a non-empty array drawn from `CATTLE`, `SWINE`, `POULTRY`, and `SHEEP`…". Impl `routes_establishments.py:42` (`require_string(body, "name")`) matches. The failure was a helper not forwarding a kwarg its sibling accepted — no PRD silence.
2. **`test_suite/test_difficulty_priority_pair.py` rewrite — one edit (the sub-behavior the rewrite left unasserted).** The rewritten test's asserted precedence is already PRD-verbatim: §2.7 tier 6 "A deactivated inspector surfaces earlier, at tier 5, as `ERR_INSPECTOR_INACTIVE`" and §3.2 "optimistic concurrency first, then state, then qualification, then temporal rules" — no edit for that. But the now-unasserted behavior (creation on a `VERIFIED_COVERED`/`BLOCKED` window proceeds through the normal gates) was not uniquely derivable: §2.7 tier 5 names "terminal-state lockdown" as a generic tier-5 trigger, and §3.2's "Windows in `VERIFIED_COVERED` or `BLOCKED` are terminal and cannot be re-verified" composes with it to admit a window-state gate — the original Step-5 test derived exactly that, and Step 7's report states the premise "fails unique derivability." The clause pins the impl behavior.

**Pre-edit search log (the single edit):**
- (a) Subject: whether shift-window `status` gates assignment creation (`POST /inspection/shift-windows/{id}/assignments`).
- (b) Impl paths enumerated and read/grepped: `implementation/routes_assignments.py:39-117` (create_assignment — full read; gates are OCC:57-58, inspector-ACTIVE:61-62, not-withdrawn:63, not-suspended:64, qualification:67-69, interval/line range:72-79, overlap:81-89, travel buffer:91-102; no window-status read); `routes_assignments.py:139-163` (confirm/cancel — assignment status + establishment-not-withdrawn only); `routes_windows.py:28-60` (window born PLANNED); `routes_windows.py:82-117` (`verify_coverage:86` is the codebase's only window-status gate — clause stays silent on verification); `cascades.py:26-30` (writes BLOCKED on suspension/withdrawal); `cascades.py:171-172` (deactivation cancels SCHEDULED assignments regardless of window status); `errors.py` full catalog grep (no window-state error exists); global grep confirming `VERIFIED_COVERED` appears only at `routes_windows.py:95` (a write, never a gate).
- (c) Wording adjustment: dropped a draft parenthetical gate list to avoid exhaustive-list hazard (impl also enforces `line_index` range and field-shape checks not cleanly categorizable); final wording is non-enumerative ("all of the operation's other specified checks") so the withdrawn/suspended gates at `routes_assignments.py:63-64` and all off-site paths remain accurately described.

Files: `workspace/PRD_FINALIZED.md` (produced), source `workspace/PRD.md` (untouched).

Orchestrator verification (independent): `diff PRD.md PRD_FINALIZED.md` shows exactly one changed line (line 167) with exactly the reported sentence appended; both files 353 lines.

## Step 9: Complete PRD — 2026-10-02T13:19:10.083Z

The work is complete. PRD_COMPLETED.md is written and verified.

## Summary

**Source vs output:** `PRD_FINALIZED.md` 353 lines / 63,016 chars → `PRD_COMPLETED.md` 353 lines / 69,740 chars. Char delta **+6,690**; 21 paragraphs touched, all in-paragraph inserts or revisions; no new sections, no deletions.

**Counts:** 21 ambiguity-pins (18 pure inserts, 3 in-place revisions) · 0 mismatch-revisions (0 PRD DEFECTs) · **1 impl bug reported** (not edited into the PRD).

### Changes (one bullet each)

- §2.1 — insert — ambiguity — `X-User-ID` is never existence-checked against persisted entities; only path ids and body-supplied FKs are resolved — `routes_windows.py:84` (verifier id used without lookup), `routes_nrs.py:51`, `routes_humane.py:60`
- §2.2 — insert — ambiguity — `api_request_timestamp` is server **wall** clock; logical clock governs domain timestamps only — `envelope.py:25`, `store.py:68-70`
- §2.3 — insert — ambiguity — lenient pagination parse (non-integer→default, limit clamped [1,100], offset clamped ≥0), `created_at` ties break by creation sequence, `has_more` formula — `envelope.py:82-107`
- §2.4 — insert — ambiguity — clock accepts any parseable instant forward/backward (`Z`/offset honored, naive=UTC), echoes `to_iso8601` verbatim as `current_utc`; every trailing window is boundary-inclusive with no lower age bound — `app.py:49-63`, `store.py:19-51`, `calc.py:60-66`
- §2.6 — insert — ambiguity — `created_at`/`updated_at` stamp from the **logical** clock — `store.py:112-127`
- §2.7 — insert — ambiguity — field-shape positioning (creates: after path-existence, before body-FK existence; transitions: state/SOD before body validation; recall class-gate before tier-7 temporal), withdrawal freeze before resource state within tier 5, ownership-pin vs existence ordering by where the pinned value lives — `routes_grants.py:104-109`, `routes_appeals.py:71-78`, `routes_recalls.py:117-124`, `routes_assignments.py:43-54`
- §2.10 — revise — ambiguity — recency bands made continuous (≤30d→3, 30<≤60d→2, 60<≤90d→1; 30.5 days falls in band 2) — `calc.py:166-181`
- §2.10 — insert — ambiguity — computed fields also accompany the 201 registration response — `routes_establishments.py:56`
- §3.1 — insert — ambiguity — grant resubmission does not reset `decided_at` — `routes_grants.py:132-154`
- §3.2 — insert — ambiguity — within-tier gate order on assignment creation (employment→withdrawn→suspended; interval-shape→line-range→overlap→travel) — `routes_assignments.py:57-102`
- §3.2 — insert — ambiguity — travel buffer is strict: exactly-30-min gap passes; adjacency/overlap across establishments violates and reports `ERR_TRAVEL_BUFFER_VIOLATION` (never `ERR_ASSIGNMENT_OVERLAP`) — `routes_assignments.py:91-102`
- §3.2 — insert — ambiguity — the auto-issued coverage-gap NR carries `shift_window_id` null — `routes_windows.py:101-115`
- §3.3 — revise — ambiguity — "reaches 3" → "is at least 3"; threshold re-tested on every entry into `ESCALATED`, so a 4th+ escalation auto-proposes again — `cascades.py:130-142`
- §3.4 — insert — ambiguity — `WITHHOLD_MARKS`/any-`SUSPENSION`-basis eligibility failures (incl. `ADMINISTRATIVE`) → `ERR_ESCALATION_THRESHOLD_NOT_MET`; `regulation_family` optional on non-`NR_LINKAGE` bases — `calc.py:260-312`, `routes_enforcement.py:36-40`
- §3.4 — insert — ambiguity — suspension activation does not require `ACTIVE`; a concurrent second suspension re-applies the cascade and still bumps establishment `version` — `cascades.py:36-44`, `routes_enforcement.py:86-108`
- §3.4 — insert — ambiguity — suspension lift restores `ACTIVE` + releases held labels only while still `SUSPENDED`; otherwise only the action changes — `cascades.py:92-102`
- §3.4 — revise — ambiguity — `WITHHOLD_MARKS` lift releases **every** `HELD` label of the establishment to its own pre-hold status; holds don't record the causing action — `cascades.py:103-110`
- §3.5 — insert — ambiguity — egregious-confirm cascade does not re-check `grant_status` (consistent with §2.5's enumeration of grant-gated ops); auto action carries `regulation_family` null — `routes_humane.py:29-44`, `cascades.py:145-152`
- §3.6 — insert — ambiguity — CAT_3 notice carries `regulation_family` null; a recompute landing on the stored category mutates nothing (no version bump) — `cascades.py:155-165`, `routes_pathogens.py:96-103`
- §3.8 — insert — ambiguity — recall reclassification retains the append-only check records; only counters/ratio reset — `routes_recalls.py:103-107,127-134`
- §4 — insert — ambiguity — enumerated the equality-filter query parameters impl supports on each list endpoint — `routes_*.py` list handlers (e.g. `routes_nrs.py:84-88`)
- §5 — insert — ambiguity — non-JSON/non-object body → `ERR_INVALID_REQUEST`; absent body tolerated on no-input endpoints; transport-level `ERR_NOT_FOUND`(404)/`ERR_METHOD_NOT_ALLOWED`(405)/`ERR_INTERNAL`(500) sit outside the catalogue but use the §2.2 envelope — `app.py:73-86`, `envelope.py:64-79`

### IMPL BUGS (reported, not edited)

- **Humane-event confirm/dismiss omit the withdrawal freeze.** PRD §2.5: "Withdrawal of the grant is terminal: `grant_status` becomes `WITHDRAWN`, `inspection_status` becomes `INACTIVE`, and both dimensions freeze — any subsequent operational write against a withdrawn establishment is rejected with `ERR_ESTABLISHMENT_WITHDRAWN` (HTTP 409)." Evidence: `implementation/routes_humane.py:29-44` (`_decide`, backing both `/confirm` and `/dismiss`) performs no `require_not_withdrawn` — every other establishment-scoped write endpoint has it (`routes_labels.py:79,92,121`, `routes_recalls.py:93,117,162`, `routes_appeals.py:33,71`, `routes_nrs.py:56,104,119`, `routes_grants.py:38-162`, `routes_pathogens.py:40,82`, `routes_assignments.py:63,145,158`, `routes_enforcement.py:47,94`, `routes_windows.py:41`, `routes_humane.py:61` for creation). Reachable sequence: report an `EGREGIOUS` event on a granted establishment → withdraw the establishment → confirm the still-`REPORTED` event → `cascades.py:145-152` → `cascade_suspension` (`cascades.py:36-44`) sets `inspection_status = "SUSPENDED"` and bumps `version` on an establishment §2.5 declares frozen (`INACTIVE`→`SUSPENDED` on a `WITHDRAWN` grant). Why the PRD reading is the only reasonable one: the freeze sentence is unconditional, §3.5's "requires the event to be `REPORTED`" governs the event's own state (not the establishment's), nothing anywhere exempts humane decisions, and the impl itself applies the guard on all 20+ sibling write endpoints — this is an omission on one path, not an alternative interpretation. (Adjacent non-issue: `verify-coverage` also lacks the guard, but withdrawal blocks all `PLANNED`/`COVERAGE_GAP_FLAGGED` windows, so §3.2's own `ERR_INVALID_STATE` rule always fires first there and no frozen state is ever mutated — already covered by PRD text, no bug, no edit.)

**Confidence note for the single-bug result:** the walk covered all 54 endpoints handler-by-handler (role sets verified row-by-row against §4, all matching), both OCC endpoints, the full gate inventory of §2.5 (grant-gated: window plan, sample log, label approve, suspension activate — exactly the impl's four `require_granted` sites; suspension-gated: the four `require_not_suspended` sites), all 8 calculation rules incl. rounding order and boundary inclusivity (`calc.py`), all cascades (`cascades.py`), all 35 catalog errors (all defined and raised), state-machine transition sets per endpoint, envelope/pagination/clock plumbing, and write/read symmetry of guard fields (`status_before_appeal`, `_status_before_hold`, `suspension_count` derivation).

Orchestrator verification (independent): PRD_COMPLETED.md exists at 353 lines / 69,740 chars (matches reported +6,690 delta); diff vs PRD_FINALIZED.md shows 42 changed diff-lines (21 hunks, all in-paragraph); Step 8's frozen §3.2 sentence survives verbatim (1 occurrence); not byte-identical (real work confirmed via diff -q).

## Step 9b: Impl-bug fix + re-sweep — 2026-10-02T13:19:10.083Z

Step 9's single IMPL BUG adjudicated CONFIRMED by the orchestrator before fixing: `routes_humane.py:29-44` `_decide` (backing both `/confirm` and `/dismiss`) lacked `require_not_withdrawn` while all 20+ sibling establishment-scoped write paths carry it, and PRD §2.5's freeze sentence is unconditional ("any subsequent operational write against a withdrawn establishment is rejected with `ERR_ESTABLISHMENT_WITHDRAWN` (HTTP 409)"). Verified by direct grep: `require_not_withdrawn` present at `routes_humane.py:61` (create) but absent from `_decide`; sibling modules: grants 7, labels 5, recalls 5, nrs 4, assignments 4, pathogens 3, enforcement 3, appeals 3, windows 2 call sites.

Fix applied (orchestrator, targeted, PRD-ward — PRD_COMPLETED.md untouched since the impl moved toward the PRD): `workspace/implementation/routes_humane.py` `_decide` — hoisted `establishment = establishment_or_404(event["establishment_id"])` and inserted `require_not_withdrawn(establishment)` BEFORE the REPORTED state check, matching the sibling convention (role → 404 → withdrawal freeze → state gate, per §2.5/§2.7's pinned "withdrawal freeze before resource state within tier 5") and reusing the hoisted lookup in the egregious-confirm cascade branch.

Post-fix re-sweep (full 8-round parallel stability sweep, regenerating the results artifacts the impl edit invalidated): **86/86 passed in all 8 rounds, 0 failed** — the guard addition broke no existing test (none relied on the missing guard), and `results.{1..8}.json` in `workspace/implementation/` now reflect the final, post-fix code. `python3 -m py_compile` clean on the edited module.
