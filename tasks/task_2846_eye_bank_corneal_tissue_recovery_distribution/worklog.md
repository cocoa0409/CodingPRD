# Worklog — task_2846_eye_bank_corneal_tissue_recovery_distribution

## Step 1: Create task directory — 2026-09-05T05:51:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2846_eye_bank_corneal_tissue_recovery_distribution` and `workspace/` (pre-assigned path; no index auto-allocation performed).

## Step 2: Generate Scaffold — 2026-09-05T07:42:00.000Z

All three scaffold artifacts are complete and the lint is clean.

## Files (absolute paths)
- `SCAFFOLD.yaml` — 3427 lines, no `scaffold_difficulty_design` / `scaffold_corner_design` keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2142 lines, single top-level key
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4374 lines, single top-level key

## SCAFFOLD.yaml (§1.0–§1.7)
14 entities · 10 state machines (2 of them the parallel `CorneaTissue` disposition/custody dimensions) · 2 concurrency rules · 15 calculations · 49 validations · 64 endpoints · 58 error codes · 6 roles. `difficulty_level: expert_plus`; layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, selector_policy]`; topology `graph`; state-machine shape `parallel`; role model `segregation_of_duties`; consistency `immediate`. The "harder than expert level" directive line is not present in the `scenario` key.

## §1.8 SCAFFOLD_DIFFICULTY_DESIGN.yaml — 9 rule ids × 2 instances = 18
`dual_variant_calc` 2 · `combinatorial_formula` 2 · `non_linear_state_machine` 2 · `transitive_cascade` 2 · `priority_pair_validation_conflict` 2 · `boundary_precision_check` 2 · `cross_entity_state_dependency` 2 · `resource_temporal_overlap` 2 · `compensating_invariant` 2

## §1.9 SCAFFOLD_CORNER_DESIGN.yaml — 9 sections, 80 instances (61 with `test_recipe`, 19 `excluded_because` stubs)
`entities` 12 (0 stubs) · `state_machines` 11 (3) · `calculations` 10 (4) · `validations` 9 (2) · `endpoints` 6 (2) · `errors` 19 (5) · `rbac` 6 (0) · `cross_cutting_complexity_layers` 5 (2) · `consistency_model` 2 (1)

All 19 stub citations resolve to a real §1.8 instance name, and no name repeats across the union of the two design files.

## Error-catalog coverage
57 of 58 codes are triggered by a §1.9 instance or by a cited §1.8 instance. `ERR_SHIPMENT_INTEGRITY_FAILED` is documented in an in-file comment as structurally unreachable (an EXCURSION_MAJOR verdict already quarantines the tissue at delivery, so the implant-time integrity check sits behind `ERR_TISSUE_NOT_ELIGIBLE`/`ERR_TISSUE_CUSTODY_INVALID`).

## Lint verdict (verbatim)
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
Coverage line: 64 endpoints declared, 14 entities declared, 18 §1.8 instances scanned, 61 §1.9 instances scanned, 1073 calls scanned.

Two literal bugs were caught and fixed while finishing: a tissue disposition asserted as `PENDING_EVALUATION` (the §1.2 initial state is `UNGRADED`) and a `TATTOO_12M` screening weight asserted as 15 (the §1.3 weight table says 10). No sibling task directory was read at any point.

Orchestrator verification: all three files present; `grep "harder than expert"` over all three returns nothing (no difficulty-directive leak).

## Step 3: Copy Shared Files — 2026-09-05T07:43:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-05T08:05:00.000Z

PRD generation for task 2846 is complete.

**Output:** `workspace/PRD.md` — **493 lines**, written incrementally (one `Write` + eight `cat >>` appends). Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened or grepped, and no sibling task directory was read.

**Section list**
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 RBAC · 2.2 Response Structure (verbatim block) · 2.3 Pagination · 2.4 Logical Clock & Datetime · 2.5 Common Resource Properties · 2.6 Version Handshakes · 2.7 Two State Dimensions & Cascade Discipline (+ full nine-lifecycle inventory) · 2.8 Path Resolution · 2.9 Numeric Precision & Rounding · 2.10 The Order of Rejection (all 49 rungs) · 2.11 Conserved Quantities
- `## 3. Business Logic & Workflows` — 3.1 Referral/Recovery Window/Screening · 3.2 Consent, Serology, Release · 3.3 Roster, Dispatch Overlap, Preservation · 3.4 Grading · 3.5 Classification, Quality Score, Final Shelf Life · 3.6 Surgeons, Priority, Allocation Selector · 3.7 Confirmation, Billing, Shipping · 3.8 Delivery, Integrity Verdict, Implantation, Re-issue · 3.9 Quarantine, Disposal, Adverse Reactions, Lookback
- `## 4. Endpoint Definitions` — **64 endpoints**, 4 columns
- `## 5. Error Code Catalogue` — **58 error IDs**, 2 columns

**Tail:** ends at `| ERR_CLOCK_REWIND_FORBIDDEN | 422 |`, the final row of the §5 table — a clean section boundary, not mid-sentence. Table row count is 124 = 64 + 58 + 2 header separators.

**Hard Contract 1 — Field-Name Coverage**: entities[].fields 127/127; endpoints[].request_body 76/76; endpoints[].query_params 15/15. Status PASS.

**Hard Contract 2 — Rule Coverage**: validations 49/49 as §2.10 rungs 1-49; concurrency_rules 2/2 in §2.6 with field, write op, error id and 412; 10 state machines (CorneaTissue twice, one per dimension) with all value sets + initial + terminal states in §2.7, 141 distinct enum values all verbatim; calculations 15/15 with every constant, threshold and clamp order; 49/49 validation-condition→error_id matchable; §5 catalogues 58/58 ids with status codes; 64/64 endpoints tabled in §4; 127/127 entity fields with type, source, default, constraints; sibling-branch symmetry stated for both delivery branches, both return branches, both adjudication branches and both lookback closures. Status PASS.

**Hard Contract 3 — §3 Path Purity**: 1057 backtick tokens scanned, 0 starting with `/`, 0 bare HTTP-method tokens, 0 method+path tokens. Status PASS. Also verified globally: zero ASCII `->`, zero symbolic comparison/floor/min/max/boolean operators, zero fuzzy words.

**Scaffold contradictions resolved** (decisions baked in consistently):
- `quarantine_reason` on major-excursion delivery → `COLD_CHAIN_EXCURSION_MAJOR` (state machine wins over the endpoint's `SHIPMENT_EXCURSION_MAJOR`); on a failed unused-tissue return → the supplied `return_reason` (endpoint wins, else the input would be inert).
- Lookback OPEN cascade quarantines `{ELIGIBLE, RESERVED}` only; `ISSUED` surfaces via `notified_recipient_count`. `impacted_tissue_count` is unfiltered.
- `min_temp_c`/`max_temp_c` stated non-contradictorily: appends refresh them provisionally, delivery recomputes over the inclusive `[shipped_at, delivered_at]` window.
- Classification is **not** gated on reactive serology (validation rung 22 omits it and decision-table row 1 handles it) — stated explicitly so implementers don't add a phantom gate.
- `notified_recipient_count` uses the calculation's allocation-status set `{RESERVED, CONFIRMED, CONSUMED, RELEASED}`, not the endpoint's looser prose.

**One correctness note:** during a self-audit the generator found and fixed nine invented error IDs in its §3 drafts (e.g. `ERR_TECHNICIAN_INACTIVE`, `ERR_ECD_BELOW_REQUEST_FLOOR`, `ERR_LATERALITY_MISMATCH`). All now match the scaffold exactly, and every `ERR_*` token in the PRD is a member of the 58-code catalogue. `laterality_preference` is enforced **only** by the allocation run's match filter, never on the manual allocation path — the scaffold has no validation rule or error code for it — and the PRD says so explicitly.

Orchestrator verification (anti-truncation): `wc -l` = 493; `tail -25` ends at the final §5 error-table row `| ERR_CLOCK_REWIND_FORBIDDEN | 422 |`; five `##` sections present in order; grep for "harder than expert"/"scaffold_difficulty"/"scaffold_corner"/"test_recipe" returns nothing. PRD is NOT truncated — no regeneration needed.

## Step 6: Generate Implementation — 2026-09-05T08:44:43Z

Implementation complete and verified.

## Files written

All under `workspace/implementation/` — 23 files, 3860 lines total (20 `.py` files):

| file | lines | role |
|---|---|---|
| `requirements.txt` | 1 | `flask>=2.0.0` |
| `start.sh` | 10 | guarded install, reads `$PORT`, `exec python3 app.py` |
| `app.py` | 87 | factory, 11 blueprints, ApiError/HTTPException/Exception handlers |
| `store.py` | 174 | in-memory `DB` (14 dicts), logical clock, id/version/time helpers |
| `errors.py` | 89 | 58 error IDs → HTTP status |
| `envelope.py` | 76 | meta/response_type/data envelope, pagination, nested lists |
| `validate.py` | 177 | typed field extraction, FK resolution, filter validation |
| `serialize.py` | 252 | 14 entity serializers |
| `auth.py` | 65 | header auth, role gate, entity-backed actor resolution |
| `calc.py` | 505 | all 15 calculations |
| `cascade.py` | 145 | shared cascades (quarantine, release, lookback sweep) |
| `routes_donors.py` | 282 | donors + screening records |
| `routes_serology.py` | 126 | serology results/retest |
| `routes_technicians.py` | 75 | technicians |
| `routes_recoveries.py` | 241 | dispatch/arrive/complete/abort |
| `routes_tissues.py` | 408 | evaluation, classification, implant, return, disposal |
| `routes_surgeons.py` | 183 | surgeons + surgeon requests |
| `routes_allocations.py` | 408 | manual allocation, allocation runs, confirm, cancel |
| `routes_shipments.py` | 262 | shipments, temperature readings, dispatch, deliver |
| `routes_reports.py` | 152 | adverse reaction reports + adjudication |
| `routes_lookback.py` | 116 | lookback investigations, notify, close |
| `routes_clock.py` | 26 | `POST /_clock/set_current_utc` |

## Coverage

- **64 endpoints** (40 POST, 24 GET) — matches the scaffold count exactly.
- **58 error codes** implemented and mapped: 24x422, 15x409, 11x404, 3x403, 2x400, 2x412, 1x401.
- 14 entities, 10 state machines, 15 calculations, 49 validations; the ordered 49-rung rejection ladder from PRD §2.10 is followed literally so error precedence is deterministic.
- Storage is in-memory dicts only; nothing is seeded, and all 14 collections are empty at boot.

## Smoke-boot result

`AST OK 20 files` (clean parse). Fresh boot via `PORT=21295 bash start.sh` on a programmatically probed free port; server killed by its exact listener PID only (`ss -ltnp` extraction), never a broad pkill; port confirmed free afterwards.

Probes all returned the designed shape: clock set 200 / rewind 422 `ERR_CLOCK_REWIND_FORBIDDEN`; empty collection 200 with `limit:10, offset:0, total_count:0, has_more:false`; `limit=0` → 400 `ERR_INVALID_PAGINATION`; Surgeon on a coordinator route → 403 `ERR_FORBIDDEN_ROLE`; no headers → 401; bogus role `Wizard` → 401 (PRD line 15 requires exactly one of the six names); unknown id → 404 `ERR_DONOR_NOT_FOUND`; DELETE → 405 `ERR_METHOD_NOT_ALLOWED`.

An end-to-end functional walkthrough on an earlier boot confirmed the money and state math against the PRD's worked examples: processing fee **277464** for TRANSPLANT_OPTICAL + URGENT + DMEK + short-notice (exact PRD figure), priority base 70 / PLATINUM / score 85, recovery window 720 min, `death_to_preservation_minutes` 360 → WITHIN_STANDARD, quality 80 → TRANSPLANT_OPTICAL with FINAL_AT_CLASSIFICATION shelf life 264 h, allocation run creating 1 allocation with `expiry_margin_hours` 137, and the cold-chain path yielding `EXCURSION_MAJOR` (30 min over) → shipment REJECTED_ON_ARRIVAL, tissue QUARANTINED/`COLD_CHAIN_EXCURSION_MAJOR`/RETURNED_TO_BANK, allocation RELEASED, request back to OPEN, ledger credited 245000 leaving 277464 outstanding.

## Defect found and fixed

`routes_recoveries.py` `arrive` set `arrival_at` and bumped the version but never advanced `status` to `ON_SITE`, so `complete` always returned 409 `ERR_RECOVERY_STATE_INVALID` and no tissue could ever be created. Added `recovery["status"] = "ON_SITE"` before `store.touch(recovery)`.

## Notable PRD-vs-scaffold resolutions (PRD wins)

Delivery MAJOR quarantine reason is `COLD_CHAIN_EXCURSION_MAJOR` (not scaffold's `SHIPMENT_EXCURSION_MAJOR`); the lookback OPEN cascade quarantines only `{ELIGIBLE, RESERVED}` (ISSUED left alone, contra scaffold line 1552); closure sweeps exactly the tissues that investigation quarantined; the scaffold's extra NOTIFIED→CLOSED_NO_ACTION serology precondition is omitted (absent from the PRD, no error code exists for it). The allocation run is plan-then-apply so `ERR_NO_ELIGIBLE_TISSUE` persists nothing, and each request touched by a run receives at most one version bump.

## Step 5: Generate Unit Tests — 2026-09-05T10:05:00Z

Stage 1 + Stage 2 are complete and machine-verified.

## Files written (all at the TASK ROOT, nothing under `workspace/`)

`test_helpers/` — 9 files, 3157 lines: `__init__.py` 44, `api_client.py` 471, `api_errors.py` 148, `assertions.py` 278, `constants.py` 337, `factories.py` 539, `fixtures.py` 1093, `test_users.py` 165, `types.py` 82.

`test_suite/` — 14 files, 5992 lines, **97 tests**: `conftest.py` 30 · `test_01_dual_variant_and_combinatorial.py` 324 (8) · `test_02_state_machines_and_cascades.py` 417 (9) · `test_03_priority_and_boundary.py` 377 (8) · `test_04_cross_entity_and_overlap.py` 340 (8) · `test_05_compensating_invariants.py` 228 (4) · `test_06_entities.py` 476 (11) · `test_07_state_machines.py` 386 (8) · `test_08_calculations.py` 339 (6) · `test_09_validations.py` 313 (7) · `test_10_endpoints.py` 381 (4) · `test_11_errors.py` 1113 (14) · `test_12_rbac.py` 772 (6) · `test_13_cross_cutting_and_consistency.py` 496 (4).

## Coverage

- Queue A (difficulty index): **18/18 instances** translated, every one carrying **>=2** tagged tests (min count 2).
- Queue B (corner index): **60/61** non-stub instances translated, each with >=1 tagged test. Eight `excluded_because:` stubs (five in `errors`, three in `cross_cutting`/`consistency_model`) correctly not translated.
- 78 distinct `Design:` instances tagged across 97 tests; every docstring carries exactly one `Design:` line, last in the docstring, with >=1 verbatim PRD citation.

## SKIPPED (1)

- `Corner/entities/donor_create_with_client_supplied_id_extra_field_is_ignored` — **non-unique-derivability**. The PRD never states whether an unknown body field is ignored or rejected, so neither the 201-with-server-minted-id nor an `ERR_INVALID_REQUEST` outcome is uniquely derivable. Gap left as a gap; no placeholder, no xfail.

## Design-vs-PRD contradictions resolved in the PRD's favour (7)

1. Difficulty chains send `carrier: "COLDCHAIN_EXPRESS"`; PRD §3.7 allows only `COURIER`/`AIR` → `"COURIER"`.
2. Cold-chain cascade design says `SHIPMENT_EXCURSION_MAJOR`; PRD fixes `COLD_CHAIN_EXCURSION_MAJOR`.
3. Design asserts donor `serology_status == "NON_REACTIVE"`; PRD §3.2 republishes `NON_REACTIVE` as `NEGATIVE`.
4. Corner `errors/a_third_dispatch_of_a_twice_returned_tissue_yields_err_reissue_limit_reached` expects a successful third allocation and 422 on dispatch; PRD rung 43 makes the third `POST /eye-bank/allocations` return **409** with no third shipment.
5. Corner rbac asserts donor status `"CONSENTED"`; PRD enum is `CONSENT_OBTAINED`.
6. Surgeon `specialty: "CORNEA"` throughout the corner design; PRD §3.6 allows only `PK`/`DSAEK`/`DMEK`/`THERAPEUTIC` → `"PK"`.
7. Corner rbac `shared_reads...` asserts donor `APPROVED_FOR_RECOVERY` after its own setup completes the recovery; PRD §3.3 → `RECOVERED`.

Also normalised throughout: the designs' `$.meta.total_count` notation applies only to the eight paginated collections of PRD §2.3 (`total_count_of`/`page_of`/`assert_total_count`); nested listings (screening records, serology panels, tissue evaluations, a technician's evaluations, a surgeon's requests, a shipment's readings) are unpaginated and asserted with `len(get_success_data(...))`.

## Verification run

- `python3 /tmp/task_2846_tests/verify.py` (whole suite): `tests 97`, `issues:` **empty**, `tagged instances: 78`; every tag resolves to a real `- name:` in one of the two design yamls and every quoted sentence is a whitespace-normalised substring of `workspace/PRD.md`.
- `ast.parse` over all 23 py files: clean. `pyflakes` on the new `test_13`: clean (no unused imports).
- `ls -d workspace/test_*` → nothing; no test dirs leaked under `workspace/`. Stray `test_helpers/__pycache__` removed.
- `workspace/implementation/` was never read or written.

Orchestrator verification: `ls -d workspace/test_*` → no stray dirs; `grep -c "^def test_"` across test_suite/ → 97 tests. Steps 5 and 6 were launched as concurrent background agents; at Step 6's spawn time `test_suite/` did not yet exist, preserving the impl generator's physical isolation from the test suite.

## Step 7: Run Tests and Iterate — 2026-09-05T10:27:00Z

Clean 8-round sweep achieved: **96/96 passing in all 8 parallel rounds**, zero failures, zero skips.

## Summary

**Iterations run:** 2 (iteration 1 = 87/97 in all 8 rounds, 10 deterministic failures; iteration 2 = 96/96 in all 8 rounds).

Notably, all 10 failures were deterministic (8/8 rounds identically) — no flakiness surfaced, and no load-induced timeouts or connection failures.

**Tests deleted (1):**
- `test_suite/test_11_errors.py::test_a_transplant_override_on_a_research_only_donor_yields_err_consent_scope_violation` — deleted under STEP 1b **unique-derivability collapse**. The test asserts that `intended_use_override: "TRANSPLANT"` on a `RESEARCH_ONLY` donor is refused with `ERR_CONSENT_SCOPE_VIOLATION` at classification. PRD 3.5 enumerates classification's consent gate exhaustively and narrowly — "The donor's `consent_scope` must not be `NONE`, refused with `ERR_CONSENT_SCOPE_VIOLATION`" — and adds "Beyond that gate, `intended_use_override` does not itself alter the classification the decision table produces," while decision-table row 2 routes `RESEARCH_ONLY` to `RESEARCH`. The test's only support is the generic rung-21 phrase "and permits the use the operation implies" (2.10) plus a quote from 3.6 that governs *manual allocation*, not classification. A faithful PRD-only reader following 3.5 would accept the request and classify as `RESEARCH` — two legal readings, so the outcome is not uniquely determined.

**Fixes applied to `implementation/` (1):**
- `workspace/implementation/calc.py`, `recompute_screening_risk()` — removed `min(SCREENING_RISK_CEILING, raw)`. PRD 3.1 makes 50 a *threshold* the score is compared against ("A `screening_risk_score` of 50 or more is the bank's transplant risk ceiling"), never a cap on the stored figure; the clamp also contradicted "`screening_risk_score` becomes the `YES` total plus the `UNKNOWN` total, which ... is strictly larger than the interview-only figure". This one bug caused 2 failures (a 65-point reconciled score reported as 50, and a 60-point `CJD_FAMILY` score reported as 50).

**Fixes applied to `test_helpers/` (1):**
- `fixtures.py`, `recovered_tissues()` — the returned tissue list was ordered by an undetermined tie-break. Both tissues of one completion share the same logical-clock `created_at` *and* the same `preserved_at`, so neither the tissue list's declared "descending `preserved_at`" order nor the helper's `created_at` sort can distinguish them; the implementation's `_seq`-descending tie-break returned `OS` before `OD`. The helper now re-imposes the requested laterality order, which is what PRD 3.3 actually pins ("in the order the lateralities were listed"). Fixes `test_10_endpoints.py::test_the_allocation_run_matches_the_earliest_expiring_of_two_compatible_tissues` and removes latent order-dependence from ~6 other multi-laterality tests.

**Fixes applied to `test_suite/` (6 edits, 6 tests):**
- `test_02_state_machines_and_cascades.py::test_the_excursion_is_charged_from_the_last_good_sample_and_grades_major` — `assert_one_decimal(value, expected, label)` was called with the label in the `expected` slot (`ValueError: could not convert string to float: 'max_temp_c'`); now passes the actual expected temperatures, folding in the redundant follow-up equality asserts.
- `test_09_validations.py` — three misuses of `page_of()`, which returns a `(rows, meta)` tuple: `len(page_of(...)) == 1` compared 2 to 1, and two `for row in page_of(...)` loops raised `TypeError: list indices must be integers`. All three now unpack the tuple. Affects `test_donor_list_with_limit_one_hundred_and_one_yields_err_invalid_pagination`, `test_reusing_a_donor_code_yields_err_duplicate_donor_code`, `test_a_surgeon_request_whose_surgery_date_equals_now_yields_err_surgery_date_in_past`.
- `test_09_validations.py::test_a_donor_whose_death_at_is_after_now_yields_err_death_time_in_future` — the payload inherited the factory's default `body_cooled_at` (03:00), which sits *before* the test's future `death_at` (08:00). PRD 3.1 makes that inversion an invalid request, and rung 6 correctly pre-empts the rung-30 check under test, so the implementation rightly answered `ERR_INVALID_REQUEST`. Now sends `body_cooled_at=None`.
- `test_09_validations.py::test_a_death_at_exactly_equal_to_now_is_accepted_and_earns_the_full_cooling_credit` — hardcoded `recovery_deadline_at` literal was wrong. With `death_at = T_NOW = 06:00` and the 960-minute window the test itself asserts, the deadline is 22:00, not the 18:00 literal (which corresponded to a 02:00 death). Corrected to `2026-08-03T22:00:00.000Z`.

**Not touched:** `worklog.md` (orchestrator-owned), and no assertion was weakened — no `skip`/`xfail` added, no `error_id` check downgraded to an HTTP-status check, and no PRD-required implementation check removed.

Orchestrator verification: read all 8 `results.$i.json` directly — every round reports `passed=96 failed=0 total=96 skipped=0`; `grep -c "^def test_"` over test_suite/ = 96 (matches the 97 generated minus the 1 deletion); `grep` for `pytest.mark.skip|xfail` across test_suite/ returns nothing.

## Step 8: Finalize PRD — 2026-09-05T10:33:00Z

Done. `PRD_FINALIZED.md` is written.

## Line counts
- `PRD.md`: 493 lines → `PRD_FINALIZED.md`: 495 lines (+2 lines, **+0.41%**); 3 paragraphs revised in place, 1 paragraph inserted.

## Changes (one bullet each)

- **2.3 Pagination** — *insert* — new paragraph pinning the tie-break for every listing whose ordering key can tie: broken by row-write order, taken in the same direction as the listing (newest-written first in a descending listing, earliest-written first in an ascending one), with the worked `OD`-before-`OS` tissue-list example and the surgeon-request residual tie. — `store.py:168-174`, `routes_tissues.py:102`
- **2.10 rung 21** — *revise* — spelled out what "permits the use the operation implies" means per operation: at recovery completion and tissue classification the gate is satisfied by any scope other than `NONE`, including when `intended_use_override` is `TRANSPLANT`; the transplant-scope demand belongs to the allocation paths. — `routes_tissues.py:228`, `routes_recoveries.py:166`, `routes_allocations.py:111`
- **3.1 History screening** — *insert* — clarified that the 50-point "transplant risk ceiling" is a comparison threshold, never a cap: `screening_risk_score` is the full weighted total and is never clamped (CJD_FAMILY-only = 60; reconciled 65 = 65). — `calc.py:99-113`
- **3.5 Classification** — *insert* — stated that the screening-risk comparison is the whole of `intended_use_override`'s effect: it is never checked against `consent_scope`, so a `RESEARCH_ONLY`/`TRAINING_ONLY` donor's tissue with the override and risk below 50 is accepted and routed by rows 2/3; and that "other than `NONE`" is classification's only consent condition. — `routes_tissues.py:222-247`

**Step 7 items that needed no PRD change** (PRD already uniquely determined them): the `assert_one_decimal` label/expected swap; the three `page_of()` tuple-unpack misuses; the `body_cooled_at`/future-`death_at` payload (rung 6 already precedes rung 30 in 2.10, and 3.1 already calls the inversion an invalid request); the wrong `recovery_deadline_at` literal (3.1's arithmetic is fully pinned). The `calc.py` ceiling removal was an impl→PRD alignment, so only the anti-clamp clarification was added, no behavioral text changed.

## Per-edit pre-edit search log

**Edit 1 — 2.3 tie-break insert**
- (a) Subject: ordering of collection/nested listings, specifically the tie-break when the ordering key repeats.
- (b) Paths enumerated (grepped `sort_desc|sort_asc|by_created|by_seq|sorted(` across all modules, then read each): `store.sort_desc` (`(key,_seq)` reverse), `store.sort_asc`, `store.by_created` (`(created_at,_seq)` asc), `store.by_seq`; every listing callsite — `routes_donors.py:143` (desc created_at), `routes_donors.py:186-190` screening records (by_created), `routes_serology.py:82` (desc drawn_at), `routes_recoveries.py:120`, `routes_tissues.py:102` (desc preserved_at), `routes_tissues.py:213` (desc performed_at), `routes_technicians.py:74` (desc performed_at), `routes_allocations.py:197`, `routes_shipments.py:102`, `routes_shipments.py:150-155` + `calc.shipment_readings:368` (asc `(recorded_at, created_at, _seq)`), `routes_lookback.py:68`, `routes_reports.py:106`, `routes_surgeons.py:25` (`(-priority_score, created_at, _seq)`); plus the tissue-creation loop `routes_recoveries.py:185-207` that produces the equal-`created_at`/`preserved_at` pair, and `test_helpers/fixtures.py:784-823`.
- (c) Adjustment: initial wording would have said "newest first" universally; widened to *"in the same direction as the listing itself"* so the ascending temperature-reading list, the ascending-`created_at` default and the surgeon-request `(created_at, _seq)` ascending residual tie are all described correctly. Phrased on **row-write order** rather than `created_at`, since `created_at` is exactly what ties under the frozen logical clock.

**Edit 2 — 2.10 rung 21 revise**
- (a) Subject: the consent-scope gate and its per-operation strength; secondarily `intended_use_override`'s scope of effect.
- (b) Paths enumerated (grepped `consent_scope` across all modules, read each hit): `routes_recoveries.py:166` (`== "NONE"`), `routes_tissues.py:228` (`== "NONE"`), `routes_allocations.py:111` (`not in CONSENT_ALLOWS_TRANSPLANT`), `routes_allocations.py:201-238` (`_run_pool`/`_matches_request` — no consent predicate at all; non-transplant scopes are excluded implicitly via `classification`), `calc.tissue_classification:272-288` (rows 2/3/9), `routes_donors.py:200-209` (consent write; scope `NONE` rejected as invalid request, and consent is only writable from `SCREENING`, so a scope cannot later widen), `routes_donors.py:98` (initial `NONE`).
- (c) Adjustment: did not assert that the allocation run performs a consent check or that it does not — the run raises no `ERR_CONSENT_SCOPE_VIOLATION`, so rung 21's existing four-operation list was left untouched and the narrow demand attributed to "the allocation paths of section 3.6" rather than to any specific enforcement site. Also confirmed the closing paragraph of 2.10 (consent-before-serology emphasis) remains true under the new wording.

**Edit 3 — 3.1 anti-clamp insert**
- (a) Subject: the stored value of `screening_risk_score` and the meaning of the 50-point ceiling.
- (b) Paths enumerated (grepped `screening_risk|SCREENING_RISK_CEILING`): sole writer `calc.recompute_screening_risk:99-113` (stores `raw`, unclamped); initial value `routes_donors.py:103`; recompute triggers `routes_donors.py:179`, `routes_serology.py:70`, `routes_serology.py:117`; all readers compare only with `>= 50` — `calc.py:276` (row 4) and `routes_tissues.py:243` (rung 29); exposure `serialize.py:41`; confirmed no report or ledger re-derives or caps it. `calc.SCREENING_RISK_CEILING` now survives only as an unused constant.
- (c) Adjustment: none needed — every reader is a threshold comparison, so "never clamped" mis-describes no path. Kept the existing "transplant risk ceiling" sentence verbatim and appended the clarification rather than rewriting it.

**Edit 4 — 3.5 override-scope insert**
- (a) Subject: what `intended_use_override` is checked against at classification, and classification's consent condition.
- (b) Paths enumerated: `routes_tissues.py:222` (`opt_enum`, only value `TRANSPLANT`), `:224` disposition gate, `:228` consent `NONE`, `:230` serology `PENDING`, `:232` lookback, `:235-241` evaluation completeness, `:243` the sole override consumer (`>= 50` → `ERR_SCREENING_RISK_TOO_HIGH`), `:249-262` (quality, decision table, disposition, shelf life — none reads `override`); `calc.tissue_classification:268-288` (signature takes no override argument, confirming the override cannot alter the table); `validate.opt_enum`.
- (c) Adjustment: scoped the acceptance claim with "and a `screening_risk_score` below 50" so it cannot be read as overriding rung 29, and said "rows 2 and 3 ... route it to `RESEARCH` or `TRAINING`" rather than naming a single outcome, so both `RESEARCH_ONLY` and `TRAINING_ONLY` are covered without asserting anything about rows 1/4/5 that could fire first.

Orchestrator verification: `PRD.md` 493 lines vs `PRD_FINALIZED.md` 495 lines; `cmp` confirms they differ; `diff` shows 8 changed lines. Step 8 was not skipped because Step 7 applied 1 implementation fix, 1 test_helpers fix, 6 test_suite fixes and 1 deletion.

## Step 9: Complete PRD — 2026-09-05T11:05:00Z

Run as THREE sequential module-partitioned passes over one shared `PRD_COMPLETED.md` (pass 1 owned the `cp`; passes 2 and 3 were forbidden to repeat it and each verified the earlier passes' marker text survived).

### Pass 1 — cross-cutting core (app.py, store.py, errors.py, envelope.py, validate.py, serialize.py, auth.py, routes_clock.py, start.sh, requirements.txt)

`cp PRD_FINALIZED.md PRD_COMPLETED.md` done first. 495 lines / 125,223 chars → 497 lines / 130,474 chars (+2 lines, +5,251 chars), 14 diff hunks, all in-paragraph. **14 ambiguity-pins, 1 mismatch-revision.** The 58-code error→status map was cross-diffed programmatically (impl ↔ PRD table: exact match, zero discrepancies) and all 127 serialized field names were diffed against PRD prose (all mentioned). App booted on port 18461 to confirm envelope/fallback/coercion empirically; server stopped by pid.

Changes: §2.1 empty header value counts as absent for `ERR_UNAUTHENTICATED` (auth.py:46-49) · §2.2 `api_request_id` = `req_` + exactly 24 lowercase hex, fresh per response incl. errors (store.py:62-63) · §2.2 `api_request_timestamp` is the logical clock read at envelope composition, so a clock-set response reports the new instant (envelope.py:14-18) · §2.2 pagination `meta` keys also appear on nested listings (`limit`=`total_count`=row count, `offset` 0, `has_more` false) and are absent from single-resource/summary/error meta (envelope.py:26-33,73-76) · §2.3 unparseable `limit`/`offset` → `ERR_INVALID_PAGINATION`, empty value → default, `offset` >= `total_count` legal and empty (envelope.py:45-63) · §2.3 out-of-vocabulary enum filter → `ERR_INVALID_REQUEST`, evaluated before the pagination bounds check (validate.py:164-167) · §2.3 `lookback_flag` accepts `true/false/1/0` case-insensitively (validate.py:171-177) · §2.3 identifier-valued filters are exact-string-match, never existence-checked (routes_tissues.py:88-93) · §2.3 `limit`/`offset` on a nested listing are ignored not rejected (envelope.py:73-76) · §2.4 impossible calendar instants, non-string types and non-`Z` offsets are all `ERR_INVALID_REQUEST` (store.py:87-104) · §2.4 clock set returns 200 with `data` = single-key `{current_utc}`, persists no resource (routes_clock.py:25-26) · §2.5 all named fields always present, no value → JSON `null` never omitted, no unnamed bookkeeping field exposed (serialize.py:16-22,63-79) · §2.7 `created_at` ties in cascade iteration break by write order, earliest first (store.py:155-157) · §2.7 an investigation's quarantined-tissue id set is internal only (cascade.py:116) · §2.8 a body FK that is absent/`null`/non-string is skipped at rung 5 and falls through to rung 6 (validate.py:31-38) · §2.9 integers must be JSON integers, decimals accept number or numeric string and echo as shortest-form JSON number, booleans must be JSON booleans (validate.py:87-125) · §2.10 rung 6 absent/malformed/non-object body treated as `{}`, never 415 (auth.py:61-64) · §4 trailing slash accepted as equivalent (app.py:53) · **§5 MISMATCH** — PRD claimed every 4xx carries one of the 58 catalogue ids; impl also emits `ERR_NOT_FOUND` (404 unrouted), `ERR_METHOD_NOT_ALLOWED` (405) and `ERR_INTERNAL` (500) in the same envelope, now pinned as three out-of-catalogue transport codes (app.py:41-77).

### Pass 2 — calc.py (all 15 calculations), cascade.py, routes_donors.py, routes_serology.py, routes_technicians.py, routes_recoveries.py

Did NOT re-run the cp; pass 1's `api_request_id` edit confirmed present (4 occurrences) and all 14 pass-1 hunks survived. 497 → 497 lines, 130,474 → 137,657 chars (+7,183); diff line count 60 → 132, hunks 14 → 32. **16 ambiguity-pins, 2 mismatch-revisions.**

Changes: §2.3 **mismatch** technician-evaluation list was described both as newest-first and as descending `performed_at`; dropped from the newest-first clause (routes_technicians.py:74) · §2.7 **mismatch** `RULED_OUT` was flatly terminal but recovery completion writes `RECOVERED` over it; terminality qualified (routes_recoveries.py:209) · §3.1 recomputation runs inside the creating request so the 201 already carries the real `weight_applied`; no donor-status gate; donor `version` +1 on every record even a `NO` (routes_donors.py:177-180) · §3.2 `authorizing_party_name` optional 1–120 null when omitted, `consent_type` `NONE` submittable, re-consent after reinstatement overwrites all four fields and re-stamps `consent_obtained_at` (routes_donors.py:201-212) · §3.2 serology draw has no donor-status gate and `drawn_at` is compared neither to `death_at` nor the clock (routes_serology.py:22-28) · §3.2 variant reconciles on any verdict; the panel's `donor_version_after` is rewritten post-cascade (routes_serology.py:119) · §3.2 a `REFERRED` donor is not ruled out; the retest lookback is skipped without error when an `OPEN`/`NOTIFIED` investigation exists; donor `version` rises by 2 on the investigation-opening path (routes_serology.py:115-124) · §3.2 `deferral_reason` bounds 1–500 (routes_donors.py:222) · §3.3 `certification_expires_at` may already be lapsed at registration, deactivation aborts nothing, arrival/completion/abort never test technician status or certification, same-value roster write still bumps `version` (routes_technicians.py:24-61) · §3.3 dispatch instants not clock-compared, no deadline/lookback/consent gate, two concurrent live dispatches of one donor are legal (routes_recoveries.py:43-57) · §3.3 `arrival_at` must not precede `dispatched_at` at rung 6 ahead of ownership and state, not clock-compared, occupation interval unmoved (routes_recoveries.py:137-146) · §3.3 `preservation_at` not clock-compared (routes_recoveries.py:157-172) · §3.3 `tissues_recovered_count` set not accumulated, donor moves to `RECOVERED` from any status incl. `RULED_OUT`, no serology/lookback gate (routes_recoveries.py:209-211) · §3.3 `abort_reason` bounds 1–500 no vocabulary (routes_recoveries.py:226) · §3.8 empty included reading set (baseline-only shipment) short-circuits to null min/max, 0 minutes, `PASS`, skipping excursion analysis (calc.py:379) · §3.8 the released allocation's `cancel_reason` is the literal `COLD_CHAIN_EXCURSION_MAJOR` (cascade.py:56) · §3.9 lookback quarantine writes `quarantine_reason` `LOOKBACK_OPEN`, cascade-supplied, `custody_status` untouched (cascade.py:6,113) · §3.9 `NO_ACTION` closure clears `quarantine_reason` to null, `RECALL` retains `LOOKBACK_OPEN`, sweep confined to this investigation's own quarantine set (cascade.py:129-145).

Verified-consistent, no change needed: all 15 calculation formulas' constants, weight tables, thresholds and clamp orders (window credits/penalty/360-floor, screening weights + no-clamp ceiling, serology cascade, time bands, 60-min turnaround with half-open intervals, both shelf-life variants, quality-score component clamps, the 10-row classification table, three-step priority scoring, independently-rounded surcharges, per-segment excursion flooring, both ledgers, lookback status sets). `calc.tissue_availability_ledger` is dead code; §2.11 already frames the ledger as a client-side derivation from filtered `total_count`.

### Pass 3 — routes_tissues.py, routes_surgeons.py, routes_allocations.py (incl. calc #10 `expiry_margin_hours`), routes_shipments.py, routes_reports.py, routes_lookback.py

Did NOT re-run the cp; both `api_request_id` (pass 1) and `LOOKBACK_OPEN` (pass 2) confirmed present. 137,657 → 142,987 chars, 497 lines unchanged (all edits inline); hunks 32 → 48, diff line count 132 → 196. **20 ambiguity-pins, 3 mismatch-revisions.**

Changes: §3.4 a forbidden grade sent as JSON `null` counts as omitted not supplied (routes_tissues.py:121) · §3.9 `quarantine_reason` required 1–500 (routes_tissues.py:273) · §3.9 an existing `quarantine_reason` is retained not cleared on discard (routes_tissues.py:327) · §3.8 `return_reason` required 1–500 (routes_tissues.py:377) · §3.8 the ELIGIBLE return branch clears `quarantine_reason` to null (routes_tissues.py:396) · §3.8 "the delivering shipment" = most recently created `DELIVERED` shipment of the allocation, none at all → `ERR_SHIPMENT_INTEGRITY_FAILED` (routes_tissues.py:36) · §2.10 rung 17 **mismatch** only a `RESERVED`/`CONFIRMED` allocation is live and blocks request cancellation, so a request reopened by a release is cancellable (routes_surgeons.py:165) · §3.6 request `cancel_reason` required 1–500 (routes_surgeons.py:155) · §3.7 allocation `cancel_reason` required 1–500 (routes_allocations.py:393) · §3.6 manual allocation custody must be `IN_HOUSE`/`RETURNED_TO_BANK`, disposition gate first (routes_allocations.py:98) · §3.6 `expiry_margin_hours` pinned at creation never recomputed (routes_allocations.py:67) · §3.6 run step two **mismatch** PRD called `created_at` the final tie-break; residual tie is broken by write order earliest first (routes_allocations.py:271) · §3.6 run step three **mismatch** rungs 21/24 are pool predicates in the run not errors — a run never answers `ERR_DONOR_UNDER_LOOKBACK` or `ERR_CONSENT_SCOPE_VIOLATION` (routes_allocations.py:201) · §3.6 run step five residual tie after `created_at` broken by write order (routes_allocations.py:291) · §3.6 run step six a step-one-excluded request appears in neither result list (routes_allocations.py:284) · §3.6 run apply republishes priority to every request `OPEN` at run start but mutates the row only when a figure or the status actually changed (routes_allocations.py:305) · §3.6 run response is HTTP 200, `expiry_margin_hours` also pinned on the RUN path, `unmatched_request_ids` in processing order, `expired_request_ids` in ascending `created_at` (routes_allocations.py:337) · §3.9 `adjudication_note` required 1–2000 on both substantiate and dismiss (routes_reports.py:115) · §3.9 substantiation **mismatch** a `SERIOUS` report on a donor already `OPEN`/`NOTIFIED` opens no second investigation and still succeeds; donor `version` moves only on the investigation-opening path so a `MINOR` substantiation leaves the donor untouched (routes_reports.py:130) · §3.9 `notified_recipient_count` computed at notify time over the donor's current cohort not the opening snapshot (routes_lookback.py:84) · §3.9 `closure_note` required 1–2000 (routes_lookback.py:95) · §3.8 delivery custody check evaluated after rung 18 (delivery is absent from rung 15), `delivered_at` compared to neither the clock nor `shipped_at` (routes_shipments.py:231) · §3.6 surgeon credentialing bumps `version` even when the submitted `credential_status` is already held (routes_surgeons.py:67) · §3.7 `replaces_shipment_id` sent as JSON `null` equals omitted (routes_shipments.py:40).

Verified consistent as-is (no edit needed): all 39 endpoint role lists in the partition, every list ordering and filter vocabulary, the classification/quarantine/discard/implant rung orderings, confirmation's three re-checks with self-excluded day capacity, dispatch's rung 15→17→18→25→35→43→47 order, the integrity-verdict segment algorithm, and the fee-ledger recomputation.

### Step 9 totals

**50 ambiguity-pins + 6 mismatch-revisions = 56 changes** across the three passes. `PRD_FINALIZED.md` 495 lines / 125,223 chars → `PRD_COMPLETED.md` 497 lines / 142,987 chars (+2 lines, **+17,764 chars, +14.2%**), 48 diff hunks, no new sections.

Orchestrator verification: `cmp` confirms `PRD_COMPLETED.md` is NOT byte-identical to `PRD_FINALIZED.md` (48 diff hunks); marker greps confirm all three passes' edits coexist (`api_request_id` x4 from pass 1, `LOOKBACK_OPEN` x2 from pass 2, `expiry_margin_hours` x2 from pass 3); the file ends cleanly at the final §5 error-table row; grep for "harder than expert" returns 0.

## Pipeline complete — 2026-09-05T11:06:00Z

All nine steps done. Final state: 96/96 tests passing in all 8 parallel sweep rounds, `workspace/PRD_COMPLETED.md` written.
