# Worklog — task_2796_motor_vehicle_dealer_licensing_franchise_protest

## Step 1: Create task directory — 2026-09-04T22:37:07.328Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2796_motor_vehicle_dealer_licensing_franchise_protest` and its `workspace/` subdirectory. Index 2796 was pre-assigned by the orchestrating prompt; no scan of `./tasks/` was performed (other pipelines run concurrently on this host).

## Step 2: Generate scaffold — 2026-09-05T00:09:20.000Z

All three scaffold artifacts are complete, parse cleanly, and the linter is green.

## Files
- `/home/ubuntu/github/CodingPRD/tasks/task_2796_motor_vehicle_dealer_licensing_franchise_protest/SCAFFOLD.yaml` — 3029 lines
- `/home/ubuntu/github/CodingPRD/tasks/task_2796_motor_vehicle_dealer_licensing_franchise_protest/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1728 lines, single top-level key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_2796_motor_vehicle_dealer_licensing_franchise_protest/SCAFFOLD_CORNER_DESIGN.yaml` — 3948 lines, single top-level key `scaffold_corner_design`

`SCAFFOLD.yaml` top-level keys are exactly `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` — neither design key is present.

## §1.0–§1.7 counts
11 entities · 7 state machines · 2 §1.2.1 concurrency rules · 13 calculations · 58 ordered validations · 51 endpoints · 66 error codes · 6 roles. Domain `motor-vehicle-dealer-board`, prefix `/dealer-board`; profile: `multi_party_negotiation` / `compliance_audit`, layers `optimistic_concurrency, cascading_side_effects, dual_variant_calculation, ops_run_checkpoint`, `flat` topology, `cyclic` state machines, `segregation_of_duties` role model, `immediate` consistency.

## §1.8 — 9 rule ids × 2 instances = 18
`dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant` — 2 differentiated instances each.

## §1.9 — 9 sections, 97 instances (67 with recipes + 30 `excluded_because` stubs)
entities 11 · state_machines 17 · calculations 14 · validations 14 · endpoints 5 · errors 25 · rbac 4 · cross_cutting_complexity_layers 6 · consistency_model 1.

## Lint verdict (verbatim)
```
Coverage
  §1.5 endpoints declared:    51
  §1.1 entities declared:     11
  §1.8 instances scanned:     18
  §1.9 instances scanned:     67
  Calls scanned (§1.8+§1.9):  894

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(One lint fix was needed: a capture of `$.data.fee_final_cents`; the declared field is `fee_total_cents`.)

## Two scaffold corrections made while writing §1.9
- `FranchiseFiling.active_protest_count` counted `APPEALED`, which made priority 66 (`ERR_ACTIVE_PROTEST_BLOCKS_FINALIZE`) permanently shadow priority 67 (`ERR_APPEAL_PENDING`) — that code was unreachable. The count is now `{FILED, SCHEDULED, HEARD, SUSTAINED}` with the exclusion documented inline.
- Stripped the leading `Generate task harder than expert level!` line from `scenario:` (known leak path into PRD.md); the numbered scenario text itself is verbatim.

Also verified reachability while drafting: `ERR_RENEWAL_GRACE_EXPIRED` is only triggerable via `license-applications/{id}/submit` (the salesperson `/renewal` path is pre-empted by the expiry sweep), and priority 24 deliberately does not cover that endpoint — the recipe uses that route. No sibling task directory was read at any point.

**Orchestrator verification:** all three files present; `grep -rn "harder than expert"` over the task dir returns no match, so the difficulty directive did not leak into any scaffold artifact.

## Step 3: Copy shared files — 2026-09-05T00:09:47.549Z

Copied `./INSTRUCTION.md` → `tasks/task_2796_motor_vehicle_dealer_licensing_franchise_protest/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T00:27:35.125459885Z

PRD complete and verified.

**Output:** `workspace/PRD.md` — **468 lines**, written incrementally in 8 appends (no single oversized Write).

**Section list**
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Board Users and Role-Based Access Control · 2.2 API Response Structure (fixed block, copied byte-for-byte from `section-2.2-response-structure.md`) · 2.3 Pagination · 2.4 Common Record Properties and the Append-Only Evidence Logs · 2.5 The Logical Clock and the Operational Sweep · 2.6 Money, Percentages and Rounding Discipline · 2.7 Parallel State Dimensions and Cascade Propagation · 2.8 Stale-Version Guards on Filings and Hearing Rooms · 2.9 Path Resolution for Nested Records · 2.10 The Order in Which a Request Is Rejected · 2.11 Conserved Quantities: the Restitution Ledger and the Room-Slot Ledger
- `## 3. Business Logic & Workflows` — 3.1 Board Reference Data and the Dealership Record · 3.2 Dealer Licensure: the Revision Loop and the Board's Decision · 3.3 Salesperson Licensure, Renewal and the Discipline Dimension · 3.4 Franchise Filings: Notice, Amendment and Taking Effect · 3.5 Protesting a Filing: Standing and the Relevant Market · 3.6 The Hearing Docket: Scheduling, Exhibits and Convening · 3.7 Market Studies, the Good-Cause Standard and the Board's Protest Decision · 3.8 Warranty Reimbursement Rate Disputes · 3.9 Consumer Complaints, Sanctions and the Restitution Ledger
- `## 4. API Endpoints` — status-code paragraph + 4-column table (Method, Path, Description, Authorized Role(s)), **51 rows**
- `## 5. Error Codes` — 2-column table (Error ID, HTTP Status Code), **66 rows**

**Tail confirmation:** the file ends with the final error row `| \`ERR_GOOD_CAUSE_NOT_ESTABLISHED\` | 422 |` — a complete table at a real section boundary, no mid-sentence or mid-table truncation.

**Hard Contracts**
- **Contract 1 Field-Name Coverage: PASS.** Two mechanical passes over all 158 identifiers (every `entities[].fields[].name`, every endpoint `input`/query param, every computed-read output key, both `expected_*_version` OCC fields, plus `id`/`created_at`/`updated_at`/`version`/pagination fields). Pass 1 found one gap — `acceptance_status` was described by its values but never named; repaired in §3.6. Pass 2: **0 missing**.
- **Contract 2 Rule Coverage: PASS.** All 66 error ids appear both in the narrative and in the §5 catalogue; all 58 validations' error ids present; all 62 declared state transitions' states described (34 stated in prose rather than arrow notation, all verified by inspection — sponsor cascades, sweep decay/roll-off, dispute and complaint forks); all 13 calculations rendered in prose with load-bearing step order (fee multiplier scope, per-order-mean vs aggregate-weighted rounding order, pre-weight component capping, subtotal-keyed surcharge tiers, prevailing-share remainder absorption); every constant present verbatim or as an exact prose equivalent (`1.25` → "one and a quarter times", weights → "four tenths / one quarter / one fifth / fifteen hundredths", rates → "five/eight/twelve percent", "30 percent"). No fuzzy quantifiers.
- **Contract 3 §3 Path Purity: PASS.** 0 violations across §3 (lines 172–340). Endpoint-to-role mapping in §4 was diffed against the scaffold: 51/51 rows match with **zero role discrepancies**.

The PRD makes no reference to the scaffold, difficulty, or any test suite. The two withheld design files were never opened, and no sibling task directory was read.

**Orchestrator verification:** `wc -l` = 468; `tail -25` ends on the complete final error-table row (no mid-sentence truncation); `grep -in "scaffold|harder than expert|difficulty level|test suite|test_recipe"` returns no match.

## Step 5: Generate unit tests — 2026-09-05T01:30:00.000Z

Generation is complete. Both output trees are at the task root, nothing under `workspace/`.

## Files written

**`test_helpers/`** (Stage 1, 2286 lines)
`__init__.py` 42, `api_client.py` 229, `api_errors.py` 145, `assertions.py` 315, `constants.py` 193, `factories.py` 320, `fixtures.py` 558, `test_users.py` 56, `types.py` 428.

**`test_suite/`** (Stage 2, 4576 lines, 105 tests)
`conftest.py` 44 · `test_01_warranty_rate_arithmetic.py` 206 · `test_02_licence_fee_and_renewal_terms.py` 170 · `test_03_good_cause_and_assessment.py` 192 · `test_04_salesperson_and_dealer_discipline.py` 298 · `test_05_filing_lifecycle_cascades.py` 311 · `test_06_hearing_room_slot_ledger.py` 199 · `test_07_restitution_ledger.py` 147 · `test_08_entity_records.py` 293 · `test_09_lifecycle_state_machines.py` 560 · `test_10_derived_arithmetic.py` 263 · `test_11_validation_ordering.py` 340 · `test_12_endpoint_round_trips.py` 200 · `test_13_not_found_and_reference_errors.py` 244 · `test_14_complaint_and_dispute_errors.py` 276 · `test_15_protest_docket_errors.py` 282 · `test_16_authorization_matrix.py` 266 · `test_17_concurrency_and_consistency.py` 285.

## Coverage per queue

- **Queue A (SCAFFOLD_DIFFICULTY_DESIGN.yaml §1.8):** 18 of 18 non-stub instances translated, 39 tests (test_01–test_07). No skips.
- **Queue B (SCAFFOLD_CORNER_DESIGN.yaml §1.9):** 65 of 67 non-stub instances translated, 66 tests (test_08–test_17). The 30 `excluded_because:` stubs were never touched.
- Every test carries exactly one trailing `Design:` line; audit reports `tests=105 distinct_tags=83 / difficulty_tags=18 corner_tags=65 / no citation problems`, zero dangling tags, and no design instance translated twice.

## Design instances SKIPPED (2)

1. `Corner/instances/dealer_create_rejects_client_supplied_computed_fields` — **PRD silent on unknown/computed-field body rejection.** The recipe wants `POST /dealers` carrying `disciplinary_points` and `license_status` to draw 400 `ERR_INVALID_REQUEST`. The PRD's §2.10 stage 5 names request validity but nowhere states that a body carrying a computed or system field is refused rather than ignored, so the asserted 400 is not uniquely derivable.
2. `Corner/rbac/undisclosed_discipline_blocks_renewal_approval_without_waiver` — **PRD scopes the rule to a different operation.** §3.3 confines the `ERR_UNDISCLOSED_DISCIPLINE` waiver gate to "An initial approval", in deliberate contrast to "Every approval, initial or renewal, requires the sponsoring dealership's `license_status` to be `LICENSED`". On a renewal approval from `RENEWAL_PENDING` with 6 rolling points the only point gate §3.3 supplies is the 9-point `ERR_SALESPERSON_DISCIPLINE_BAR`, which 6 points clears, so the recipe's 422 is not uniquely derivable.

## Verification performed

- `python3 -m py_compile` on all 26 generated `.py` files: clean.
- `python3 -m pyflakes` on all generated modules: clean (unused imports pruned from test_01/03/05/09/17 and `fixtures.py`; `test_helpers/__init__.py` re-export warnings are intentional).
- `pytest test_suite --collect-only`: 105 tests collected, no import or collection errors.
- `ls -d` confirms both directories at the task root; `ls workspace/` shows only `INSTRUCTION.md`, `PRD.md`, `implementation` — no stray test dirs. `__pycache__`/`.pytest_cache` removed. Nothing under `workspace/implementation/` was read or written.

## Two recipe literals overridden by the PRD (worth flagging to whoever reviews the design indices)

- `rbac/every_role_performs_its_own_exclusive_operation` asserts `franchise_status == TERMINATION_PENDING` after merely *creating* a TERMINATION filing; §3.4 puts that movement on **service**, so the test serves the notice (still a Manufacturer-exclusive act) before asserting it.
- `cross_cutting/filing_version_advances_once_per_write_and_never_on_a_read` asserts `version == 0` at creation and `active_filing_count == 1` while the filing is `DRAFT`. §2.4 says `version` "starts at 1", and §3.1 defines `active_filing_count` as filings in `NOTICE_SERVED` or `PROTEST_PENDING` only — so the test asserts 1→2→3 and 0-then-1. The same §2.4 finding also corrected a stale `version == 0` assertion I had left in `test_13_not_found_and_reference_errors.py`.

## Step 6: Generate implementation — 2026-09-05T01:30:00.000Z

Implementation is complete, smoke-tested end to end, and the smoke server has been shut down (port 17963 free; killed by recorded pid only).

## Files written

`workspace/implementation/`

| file | lines | role |
|---|---|---|
| `app.py` | 72 | Flask app factory, blueprint mount at `/dealer-board`, `ApiError`/`HTTPException`/`Exception` handlers, `app.run(host="0.0.0.0", port=$PORT)` |
| `db.py` | 166 | in-memory dict store, logical clock (epoch `2026-08-01T00:00:00Z`), `insert/get/where/ordered/touch`, ISO helpers |
| `response.py` | 90 | envelope (`req_`+20 alnum id, 3-fractional-digit ISO Z), object/array/error responses, pagination |
| `errors.py` | 103 | `ApiError` + the full error-id → HTTP-status table |
| `middleware.py` | 85 | `X-User-ID`/`X-User-Role` auth, role guards, owner scoping (writes only) |
| `validation.py` | 251 | typed field readers, enum/range/decimal-place checks, query parsers |
| `calc.py` | 449 | all arithmetic: fee, sufficiency scan, distance, penetration, good-cause weighting, cost assessment, rate variants, sanctions, point window — `Decimal` + `ROUND_HALF_UP` only |
| `derive.py` | 158 | derived counters recomputed from surviving rows |
| `cascade.py` | 174 | multi-link transactional cascades (sponsor suspension/reinstatement, docket release, termination finalisation, point thresholds, settlement restore) |
| `sweep.py` | 94 | operational sweep batch run on every clock advance |
| `serializers.py` | 260 | entity representations |
| `enums.py` | 57 | enum vocabularies |
| `routes/` | `reference.py` 201, `applications.py` 299, `salespersons.py` 169, `filings.py` 257, `protests.py` 559, `disputes.py` 226, `complaints.py` 217, `__init__.py` 0 | the 51 endpoints |
| `requirements.txt` / `start.sh` | 1 / 10 | `flask==3.0.3`; foreground `exec python3 app.py`, guarded pip install, binds 0.0.0.0, reads `$PORT` |

**3898 lines total.** All modules pass `python3 -m py_compile`. Endpoint set diffed programmatically against the PRD table: **51/51 exact match, no extras, no omissions.** Storage is in-memory only; a grep for `sqlite3|open(|json.dump|pickle|/tmp|seed` finds only the two docstring mentions of "not seeded".

## Bug found and fixed during smoke testing

`response.page()` returns `(window, total)`, but **eight list endpoints** across `routes/{applications,salespersons,filings,protests,disputes,complaints}.py` unpacked it as a single value (`window = response.page(...)`), so every one of them 500'd with `list indices must be integers or slices, not str`. Only `routes/reference.py` was correct. Fixed to `window, total = ...`; all 13 list/nested-list endpoints (including `?status=`, `?dealer_id=`, `limit/offset` variants and the two nested collections) now return 200 with correct `total_count`/`has_more`.

Also fixed before that: `Caller.role` attribute access in `protests._require_protest_party` (was subscripting a `__slots__` object) and `Decimal` `labor_hours` in the dispute serializer (would have 500'd on every dispute read).

## Boot/serve confirmation

Cold-booted three times via `PORT=17963 bash start.sh`, each time listening on `0.0.0.0:17963`, and verified the store is **empty on every fresh boot** (all nine collections `total_count: 0`). Verified live: licence application → fee `184000` (tier 1.25 ×, +2 line-make surcharge, −facility credit), approval → dealer `LICENSED`/`FRANCHISED` with term `2026-08-01 → 2028-07-30`; deficiency-notice/resubmit cure loop; notice service (92-day period, window `2026-08-31`); amend restarting notice + window and the `ERR_AMENDMENT_LIMIT_REACHED` cap; protest standing rules; buffered room collision 409 vs. capacity ordering; stale-version 412 on both comparands; late evidence with/without leave (`LATE_ACCEPTED`); good-cause score `63.36` (hand-checked component by component); assessment `119880` split `35964`/`83916`; appeal freeze; dispute `declared 12400` / `counter 12100` / `spread 2.48` / `approved 12400` effective +30 days; complaint sanction (`points 3`, penalty `240000`), segregation-of-duties 403, overpayment 422, delinquency sweep → dealer `SUSPENDED/RESTITUTION_DELINQUENT` + salesperson `SUSPENDED_BY_SPONSOR`, then settlement → full reinstatement; licence-expiry sweeps. Error shapes for missing headers, bad role, unknown route, 405, malformed JSON and unknown ids all conform to the envelope.

**Orchestrator verification:** `test_helpers/` and `test_suite/` both confirmed at the task root; `ls workspace/` shows only `INSTRUCTION.md`, `PRD.md`, `implementation` (no stray test dirs); `workspace/implementation/start.sh` present.

## Step 7: Run tests and iterate — 2026-09-05T01:58:00.000Z

Clean 8-round sweep achieved.

## Summary

**Iterations run:** 2 (iteration 1: 99/105 in all 8 rounds, 6 deterministic failures; iteration 2: 105/105 in all 8 rounds).

**Final per-round numbers:** rounds 1–8 all **105/105 passed**. No flakiness surfaced — the failure set was identical (8/8 rounds) in iteration 1 and empty in iteration 2.

**Tests deleted:** none. Every failing test's rule was verbatim-covered by PRD; the defects were three real implementation/test-fidelity issues plus two over-specified-spelling assertions handled by STEP 1c partial-coverage splitting.

**Fixes applied to `implementation/`:**
- `routes/filings.py`, `finalize_filing()` — the state gate rejected `PROTEST_PENDING`, so a live protest reported `ERR_INVALID_FILING_STATE`. PRD §3.4 refuses only `DRAFT`, `EFFECTIVE`, `BARRED`, and §2.10 spells out that a `PROTEST_PENDING` filing "clears the state gate and then fails" the active-protest check. Gate inverted to a refused-set so `ERR_ACTIVE_PROTEST_BLOCKS_FINALIZE` is reachable.

**Fixes applied to `test_suite/`** (no `test_helpers/` changes were needed):
- `test_09_lifecycle_state_machines.py::TestSustainedProtestBarsTheFiling` — assertion `active_protest_count == 0` after a sustain contradicted PRD §3.5's own definition of the counter ("the number of protests against the filing standing in `FILED`, `SCHEDULED`, `HEARD` or `SUSTAINED`"); §3.7 recomputes it to 0 only on the *denied* branch. Corrected to `== 1`.
- `test_09_lifecycle_state_machines.py::test_points_aging_out_reinstate_the_discipline_dimension_alone` — the setup paid restitution on 2026-09-06, which per PRD §3.9 re-stamps `resolved_at` and therefore moves the complaint's *sanction date* off the 2026-09-05 the test's 730/731-day boundary probes assumed. Payment clock moved to 2026-09-05T12:00:00Z so the sanction date stays where the docstring says it is; the boundary assertions themselves are unchanged.
- `test_13_not_found_and_reference_errors.py::TestFilingFieldShapeAndLineMake` — the `ADDITIONAL_POINT`-names-a-dealer probe used a `BOREAS` dealership, so both `ERR_LINE_MAKE_MISMATCH` (PRD §2.10 orders line-make agreement *first*) and `ERR_FILING_FIELDS_INCONSISTENT` were defensible readings — not uniquely derivable. Probe now names an `AURORA` incumbent, isolating the "an `ADDITIONAL_POINT` must omit `affected_dealer_id`" rule the test exists to cover.
- `test_13_.../TestClockIsForwardOnly` and `test_17_.../TestClockSweepExpiresOneTermOnly` — both asserted `current_utc` by exact string (`"...T00:00:01Z"`) while the server renders three fractional digits. PRD fixes three-digit width for record `created_at`/`updated_at` (§2.4) and `api_request_timestamp` (§2.2) but is silent on the spelling of the clock endpoint's `current_utc` (§2.5 only requires that it report the resulting instant), so both spellings are PRD-faithful. Switched to the existing `assert_same_instant` helper, which compares by instant; the `ERR_CLOCK_NOT_MONOTONIC` and sweep-counter assertions are untouched.

**Key finding worth flagging:** the `active_protest_count` and sanction-date issues are both cases where the test author read one PRD section (§3.7, §3.3) without reconciling it against the definition stated in another (§3.5, §3.9). The implementation was correct on both.

**Orchestrator verification:** all 8 `workspace/implementation/results.{1..8}.json` exist (~35 KB each, written 01:57) and each reports `passed=105 total=105 failed=0`. Step 8 is NOT skipped — Step 7 applied one `implementation/` fix.

## Step 8: Finalize PRD — 2026-09-05T02:02:00.000Z

`PRD_FINALIZED.md` is written: 3 lines revised, 0 lines added/removed.

**Line counts:** PRD.md 468 → PRD_FINALIZED.md 468 (0.0% delta; 3 of 468 lines touched, 0.64% of lines).

## Changes

- **§2.5 (Logical Clock)** — revise — pins the rendering of the clock-advance response's `current_utc` to ISO 8601 UTC with three fractional digits (PRD previously fixed the width only for record `created_at`/`updated_at` in §2.4 and `api_request_timestamp` in §2.2, leaving `current_utc` unspelled) — `implementation/routes/reference.py:39` via `implementation/db.py:67-78`.
- **§3.4 (franchise filing creation)** — revise — adds that the affected-dealership line-make agreement is tested whenever a supplied `affected_dealer_id` resolves, including on an `ADDITIONAL_POINT` that should have omitted it, and ahead of all five conditional-field rules — `implementation/routes/filings.py:86-101`.
- **§3.4 (Finalising a filing)** — revise — restates the finalisation state gate as a refused set (`DRAFT`, `EFFECTIVE`, `BARRED`) with `NOTICE_SERVED`, `PROTEST_PENDING` and `PROTEST_RESOLVED` all clearing it, replacing the positive allow-list that contradicted the section's own `PROTEST_PENDING` clause — `implementation/routes/filings.py:202-206`.

## Per-edit pre-edit search log

1. **§2.5 `current_utc` width.** (a) Subject: format of instant-valued output fields, specifically `current_utc`. (b) Enumerated: `routes/reference.py:39` (only `current_utc` producer); `db.py:iso_instant` (always three digits, passes through pre-formatted strings); every `iso_instant` callsite in `serializers.py` (`created_at`, `updated_at`, `submitted_at`, `decided_at`, `hearing_start_at`, `hearing_end_at`, `evidence_deadline_at`, `received_at`, `resolved_at`); `validation._instant_value` (all instant inputs parsed to `datetime`, so nothing is echoed back in the caller's spelling); `db.iso_date` for date-only fields. (c) Wording scoped to `current_utc` alone and phrased as "the same notation §2.4 fixes", so no claim is made about date-only fields or about echoing input spellings.

2. **§3.4 line-make ordering.** (a) Subject: `ERR_LINE_MAKE_MISMATCH` applicability/ordering vs `ERR_FILING_FIELDS_INCONSISTENT`. (b) Enumerated: grepped both error ids across `implementation/` — only two mismatch sites, `routes/filings.py:87` (filing create) and `routes/protests.py:88` (protestant vs filing line make); all five `ERR_FILING_FIELDS_INCONSISTENT` raises at `routes/filings.py:90-101`; `amend_filing` (no line-make or field-shape re-check); FK resolution order at `routes/filings.py:78-85`. (c) Restricted the sentence to "a supplied `affected_dealer_id` [that] resolves to a dealership" and to "the conditional-field rules just listed", so the protest-side line-make check and the 404 path are untouched.

3. **§3.4 finalisation state gate.** (a) Subject: the finalisation state gate and `ERR_INVALID_FILING_STATE` for filings. (b) Enumerated: `finalize_filing` gate `routes/filings.py:205`; `serve_notice` gate `:128`; `amend_filing` gates `:159-165` (including the moved-on-protest `ERR_INVALID_FILING_STATE`); `enums.FILING_STATUSES` (six members, so the refused set plus the three named statuses is exhaustive); the four post-gate conditions `:208-218`; `routes/protests.py` filing open-to-protest gate. (c) First draft said `NOTICE_SERVED` and `PROTEST_RESOLVED` "go on to succeed" — that is a false universal (a `PROTEST_RESOLVED` filing can still carry a `SUSTAINED` protest in `active_protest_count`, and both can still fail the window/effective-date checks), so it was rewound to "clears the gate and is carried on to the conditions below".

Two Step 7 items produced **no** PRD edit, deliberately: the `active_protest_count == 1`-after-sustain fix (§3.5's counter definition plus `derive.ACTIVE_PROTEST_STATES` already include `SUSTAINED`, and §3.7 recomputes to 0 only on the denied branch) and the restitution-payment sanction-date fix (§3.9 already states that settling stamps `resolved_at`, and that the sanction date is the date part of `resolved_at`; `routes/complaints.py:176` matches). Both were test-fixture defects, not PRD silences.

**Orchestrator verification:** `PRD_FINALIZED.md` present at 468 lines; `diff PRD.md PRD_FINALIZED.md` yields 6 changed lines (3 revised pairs) — not byte-identical, so the pass genuinely ran.

## Step 9: Complete PRD — 2026-09-05T02:30:00.000Z

Run as **three sequential module-partitioned passes** over one shared `PRD_COMPLETED.md` (pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 edited in place and were explicitly forbidden to re-copy). Orchestrator decision, recorded here per the autonomy directive: a single agent scanning 3,898 implementation lines against a 468-line PRD reliably under-covers, and the partition makes each pass's coverage claim auditable. Partition: pass 1 = `app.py, db.py, response.py, errors.py, middleware.py, validation.py, enums.py, serializers.py, routes/reference.py`; pass 2 = `calc.py, derive.py, cascade.py, sweep.py, routes/applications.py, routes/salespersons.py`; pass 3 = `routes/{filings,protests,disputes,complaints}.py`.

**Aggregate:** `PRD_FINALIZED.md` 468 lines / 97,736 chars → `PRD_COMPLETED.md` 468 lines / 113,240 chars (**char-delta +15,504**, +15.9%). Line count unchanged throughout — every patch was an in-paragraph insert or in-sentence revision; no new sections or paragraphs. Totals: **47 ambiguity-pins, 5 mismatch-revisions**.

### Pass 1 — core modules (11 ambiguity-pins, 3 mismatch-revisions; 97,736 → 104,033 chars)
- §2.1 — revise — ambiguity — a whitespace-only `X-User-ID`/`X-User-Role` counts as empty, and the role is matched exactly/case-sensitively against the six — `middleware.py:49-54`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A-Z0-9` (24 total) — `response.py:21`
- §2.2 — revise — ambiguity — `api_request_timestamp` is the sole field read from host wall-clock time, not the logical clock — `response.py:24-35`
- §2.3 — revise — ambiguity — non-integer/blank/fractional `limit`/`offset` are `ERR_INVALID_REQUEST` (leading sign tolerated); offset has no upper bound; enum filters reject undeclared values rather than returning empty; empty-string free-text filter treated as absent; undeclared query params ignored — `response.py:63-85`, `validation.py:238-251`
- §2.3 — revise — ambiguity — `created_at` ties (routine, since the clock stands still between advances) are broken by insertion sequence; the four pagination `meta` fields appear only on list responses — `db.py:158`, `response.py:39-51`
- §2.4 — revise — ambiguity — `id` is a canonical lowercase hyphenated UUIDv4; `created_at`/`updated_at` are stamped from the logical clock, so records created between advances share a `created_at` to the millisecond — `db.py:101,115-117`
- §2.4 — revise — **mismatch** — the unit of mutation is the request, not the field: a record touched repeatedly in one request (directly or via cascade) advances `version` by exactly 1 — `db.py:131-142`
- §2.5 — revise — ambiguity — the clock moves first and the sweep then runs against the new instant, so swept records carry the new instant as `updated_at` — `routes/reference.py:37-38`
- §2.6 — revise — ambiguity — two-place decimals travel as JSON numbers with no trailing zeros (`12.50` → `12.5`); an undetermined decimal is `null`, never `0` — `calc.py:33-37`, `serializers.py:54-55`
- §2.10 stage 5 — revise — ambiguity — absent/empty body reads as `{}`; non-object JSON body rejected; explicit `null` treated as absent; no type coercion, booleans never accepted as numbers, excess decimal places rejected not rounded; dates exactly `YYYY-MM-DD`; instants accept `Z` or numeric offset and normalise to UTC, naive read as UTC — `validation.py:18-40,43-44,107-113,147-163,181-213`
- §3.1 (franchisor) — revise — ambiguity — service starts with an empty store and the clock at its epoch; `legal_name` 1–200 chars; list filters are the query params `state_registration_status` and `line_make`, matched exactly — `routes/reference.py:51,85-95`, `db.py:16-42`
- §3.1 (hearing room) — revise — ambiguity — `room_code` has no character-class constraint and is compared exactly; hearing rooms are the one collection listed with no filters; no endpoint updates a room's capacity or docket settings — `routes/reference.py:105-136`
- §3.1 (dealership) — revise — **mismatch** — `legal_name` 1–200 chars; `line_make` accepts the empty string, defaults to `""` when omitted, and is *not* cross-checked against `dealer_type` at creation; list filters exact-equality and conjunctive; no endpoint updates a dealership directly — `routes/reference.py:146-151,185-201`
- §4 (intro) — revise — **mismatch** — trailing slash insignificant; unrouted path and unsupported method answer `ERR_INVALID_REQUEST` at HTTP 404 / 405 (the two exceptions to the 400 in §5), decided before authentication — `app.py:29,48-59`

### Pass 2 — calculations, cascades, sweep, applications, salespersons (13 ambiguity-pins, 2 mismatch-revisions; 104,033 → 108,212 chars)
- §2.5 — insert — ambiguity — the sweep re-ages dealer/salesperson points and restitution against the new date and applies **no dealer point threshold in either direction**; all four counters are counts of *distinct records moved*, not actions, and a delinquent complaint is counted even when its dealership was already outside `LICENSED` — `sweep.py:22-25,30,42,49,58-73,85,90-93`
- §2.7 — insert — ambiguity — `set_counter` is idempotent: a counter recomputing to its stored value is not a write, so the blanket post-write pass alone moves no `updated_at`/`version` — `derive.py:14-18,145-158`
- §2.10 stage 3 — insert — ambiguity — ownership is tested only where the row resolves (otherwise the stage-6 404), and on a create an absent/non-string owning id falls through to stage 5 — `routes/applications.py:29-34,61-63`, `routes/salespersons.py:31-33,122-125`
- §3.2 — revise — **mismatch** — `relocation_site_*`/`new_owner_name` are *recorded and echoed* for other application types, not "ignored"; absence on the required type is `ERR_INVALID_REQUEST` — `routes/applications.py:80-86,111-113`
- §3.2 — insert — ambiguity — submit's revoked/cancelled bar carries `ERR_DEALER_LICENSE_NOT_ACTIVE` and follows the state gate — `routes/applications.py:134-137`
- §3.2 — insert — ambiguity — `deficiency_note` required, 1–2,000 chars; both deficiency-notice refusals are `ERR_INVALID_APPLICATION_STATE` — `routes/applications.py:155-160`
- §3.2 — insert — ambiguity — a resubmission re-tests none of the three renewal date rules — `routes/applications.py:168-208`
- §3.2 — insert — ambiguity — all three renewal date rules are skipped when the licensee has no `license_expires_on`; an absent `requested_term_start_on` fails contiguity — `routes/applications.py:44-55,238-240`
- §3.2 — insert — ambiguity — a renewal approval with no `requested_term_start_on` falls back to the decision date — `routes/applications.py:254-257`
- §3.2 — insert — ambiguity — an approval returning a dealership to `LICENSED` from `PROSPECTIVE`/`EXPIRED` runs the sponsor-reinstatement cascade; one on an already-`LICENSED` dealership does not — `routes/applications.py:253,270-271`
- §3.3 — insert — ambiguity — `waiver_granted` is persisted whenever supplied (approval **or** denial), an omitted/null flag leaves it untouched, and no waiver relieves the renewal point bar — `routes/salespersons.py:92-97`
- §3.4 — revise — **mismatch** — the amendment docket release also clears `evidence_deadline_at` — `cascade.py:64`
- §3.6 — revise — **mismatch** — the dismissal branch also clears `evidence_deadline_at` — `cascade.py:64`
- §3.7 — insert — ambiguity — a full three-key tie between controlling-study candidates is broken by filing order (earliest wins) — `calc.py:193-207`
- §3.7 — insert — ambiguity — the growth component is capped but **not** floored, so it can go negative and drag `good_cause_score` below 0.00 (access is the only clamped component) — `calc.py:216-223,239`
- §3.8 — insert — ambiguity — a `REBUT` excluding every qualifying line leaves `counter_rate_cents` and `spread_pct` unset, so the board may only approve the declared rate — `calc.py:342-344,353-356`

Pass 2 also resolved both of pass 1's handoff questions: the sweep counters are Python sets of record ids (so distinct-record semantics confirmed — a salesperson suspended by sponsor in step 1 and expired in step 3 counts once; `swept_complaint_count` is the one counter not gated on a state change), and **no create response reaches `version: 2`** (`POST /license-applications` never re-derives; `POST /salespersons` does, but a new `PENDING` salesperson with 0 points changes no sponsor counter, so `set_counter` never touches the row) — pass 1's §2.4 wording needed no amendment.

### Pass 3 — filings, protests, disputes, complaints routes (23 ambiguity-pins, 0 mismatch-revisions; 108,212 → 113,240 chars)
All 23 were silences, not conflicts — the PRD never described behaviour contrary to this partition.
- §2.8 — a guard comparand below 1 is `ERR_INVALID_REQUEST` at stage 5, not a stale-version refusal — `protests.py:71,154`
- §2.10 stage 4 — segregation needs the row on file, so a resolution naming a nonexistent complaint 404s ahead of stage 5; same precedence for the two no-body operations (finalize, convene) — `complaints.py:99-105`, `filings.py:199-200`, `protests.py:374-375`
- §2.10 stage 5 — `statewide_line_make_share_pct` required on `STATEWIDE_AVERAGE`; `denial_reason_code` must accompany a dispute denial — `protests.py:241-245`, `disputes.py:155-156`
- §3.4 — `termination_cause_code` 1–200 chars; filing site coords −500..500 to 2 dp; `ERR_MANUFACTURER_NOT_FOUND` precedes `ERR_DEALER_NOT_FOUND` — `filings.py:74-85`
- §3.4 — serve-notice admitted only from `DRAFT` (`ERR_INVALID_FILING_STATE`) and carries no body inputs, so it tests the `proposed_effective_on` already standing — `filings.py:127-136`
- §3.5 — `grounds_code` is recorded as asserted and never cross-checked against `filing_type` — `protests.py:70`
- §3.6 — an exhibit tendered into a still-`FILED` protest is `ACCEPTED` (no `evidence_deadline_at` exists yet, `leave_granted` irrelevant) — `protests.py:319-323`
- §3.6 — every dismissal recomputes the filing's `active_protest_count` and bumps its `version` — `protests.py:400-403`
- §3.7 — study-log gate error id is `ERR_INVALID_PROTEST_STATE`; studies require no licence standing (unlike exhibits); the log is listable with a `submitted_by_party` filter — `protests.py:252-253,283`
- §3.7 — `comparable_market_shares_pct` at most 200 entries, each 0.00–100.00 to 2 dp — `protests.py:227,236-240`
- §3.7 — good-cause analysis with no probative protestant study returns all-null components + `good_cause_established: false`, still reports the manufacturer study id and threshold, and never refuses; threshold read from the filing type — `protests.py:500-515`
- §3.7 — `findings_note` 1–2,000 chars; omission leaves the stored value standing — `protests.py:414,433-434`
- §3.7 — either decision outcome re-stamps the filing's `version` even when the count is unchanged — `protests.py:460`
- §3.7 — `court_docket_number` 1–100 chars — `protests.py:473`
- §3.7 — an appeal leaves the filing's status untouched but still recomputes its count and bumps `version` — `protests.py:481-486`
- §3.8 — the excluded-index range spans the whole sample (0..n−1), and on `ACCEPT` supplied indexes are discarded so `excluded_line_indexes` stays empty — `disputes.py:122-123,137-139`
- §3.8 — `denial_reason_code` 1–500 chars, required on a denial, and reported ahead of the state gate — `disputes.py:154-156`
- §3.9 — `complainant_name` 1–200 chars — `complaints.py:34`
- §3.9 — `findings_code` is required free text 1–100 chars, not an enum; the `CANCELLED` bar is `ERR_DEALER_LICENSE_NOT_ACTIVE`; no other licence status bars an investigation — `complaints.py:79,85-86`
- §3.9 — substantiating over `NO_VIOLATION_FOUND` findings is `ERR_INVALID_COMPLAINT_STATE`, tested immediately after the state gate — `complaints.py:111-115`
- §3.9 — `amount_cents` must be at least 1 — `complaints.py:166`
- §3.9 — dealership point thresholds are applied before the named salesperson's discipline advance — `complaints.py:150-151`
- §3.9 — the outstanding-restitution ledger is recomputed before the restoration is tested, and only the settling payment attempts the reversal — `complaints.py:182-187`

Pass 3 deliberately declined to pin two states unreachable through the API (a `PROSPECTIVE` protestant at convene time, a null `protest_window_ends_on` on a protestable filing) rather than invent behaviour.

**Orchestrator verification:** `PRD_COMPLETED.md` is 468 lines / 113,240 chars and is **not** byte-identical to `PRD_FINALIZED.md` (96 changed lines under `diff`), so the scan genuinely ran. The file still ends on the complete final §5 error-table row (`ERR_GOOD_CAUSE_NOT_ESTABLISHED | 422`) — no truncation. `grep -in "scaffold|harder than expert"` returns no match, so nothing leaked into the delivered PRD. Steps 8 and 9 touched documentation only; the Step 7 green sweep (`results.{1..8}.json`, all `passed=105 total=105 failed=0`) remains the state of the implementation and test suite.

## Pipeline complete — 2026-09-05T02:30:00.000Z

All nine steps done. Final artifacts: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_helpers/` (9 files, 2,286 lines), `test_suite/` (18 files, 4,576 lines, 105 tests), `workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md}`, `workspace/implementation/` (3,898 lines + `start.sh`) and `workspace/implementation/results.{1..8}.json` all green at 105/105.
