# Worklog — task_2806_packaging_machinery_manufacturing_field_service

## Step 1: Create task directory — 2026-09-05T00:04:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2806_packaging_machinery_manufacturing_field_service` and `workspace/` (index pre-assigned by the caller; no scan of ./tasks/ performed).

## Step 2: Generate scaffold — 2026-09-05T02:20:00.000Z

Note (orchestrator): the first Step 2 subagent was killed by an API timeout after ~77 min having written nothing to disk. It was resumed via SendMessage with an explicit instruction to write in <=250-line chunked `cat >>` appends and `wc -l` after each; it then completed. Recorded here because the recovery path (resume, don't respawn) is the reason the suite is self-consistent.

Subagent summary (verbatim):

All three scaffold artifacts are complete, parse cleanly, and pass the scaffold lint.

Files (absolute paths, line counts):
- `/home/ubuntu/github/CodingPRD/tasks/task_2806_packaging_machinery_manufacturing_field_service/SCAFFOLD.yaml` — 3095 lines (146 KB)
- `/home/ubuntu/github/CodingPRD/tasks/task_2806_packaging_machinery_manufacturing_field_service/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1824 lines (115 KB)
- `/home/ubuntu/github/CodingPRD/tasks/task_2806_packaging_machinery_manufacturing_field_service/SCAFFOLD_CORNER_DESIGN.yaml` — 6144 lines (369 KB)

SCAFFOLD.yaml inventory (§1.0–§1.7): `domain_name: packaging-machinery-oem`, `api_prefix: /packaging-oem`; 16 entities, 11 state machines, 2 §1.2.1 OCC concurrency rules (`build-slot-create-stale-order` → ERR_STALE_ORDER_VERSION 412, `stocking-recommendation-create-stale-machine` → ERR_STALE_MACHINE_VERSION 412), 17 calculations, 61 ordered validations (priorities 1–61, contiguous), 74 endpoints, 76 error codes, 6 roles. Top-level keys are exactly scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles — neither `scaffold_difficulty_design` nor `scaffold_corner_design` is present.

§1.8 (SCAFFOLD_DIFFICULTY_DESIGN.yaml): single top-level key, 9 rule_ids, 19 instances (>=2 per rule_id).

§1.9 (SCAFFOLD_CORNER_DESIGN.yaml): single top-level key, all 9 guide sections, 117 instances = 97 with full `test_recipe` + 20 `excluded_because` stubs. Per section: entities 12 (1 stub), state_machines 14 (6), calculations 15 (8), validations 7 (3), endpoints 4, rbac 4, cross_cutting_complexity_layers 6 (2), consistency_model 1, errors 54. `section:`/`claim_type:` values are drawn only from the claim-extraction guide's tables (no invented categories); the errors section uses `error_triggerable` since Table 6 declares no claim-type rows, and covers all 76 catalog codes.

Lint verdict (verbatim):
```
Coverage
  §1.5 endpoints declared:    74
  §1.1 entities declared:     16
  §1.8 instances scanned:     19
  §1.9 instances scanned:     97
  Calls scanned (§1.8+§1.9):  1470

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Additional audits beyond the lint: zero unbound `${...}` placeholders across both design files; no duplicate instance names across the union; every stub's `difficulty_instance` reference resolves to a real §1.8 instance and no stub carries a `test_recipe`; every `HTTP status ==` assert cross-checked against the §1.6 catalog with no mismatches; all 76 error codes triggerable.

Two notable design corrections made along the way: the originally-drafted `ERR_FAT_NOT_PASSED` validation was unreachable (SAT create already requires the order to be INSTALLED, which implies a PASSED FAT), so priority 18 was replaced with the reachable temporal rule `ERR_SAT_BEFORE_FAT` (422, "for kind == SAT, scheduled_on >= the scheduled_on of the order's PASSED FAT") in the validation list, the AcceptanceTest precondition, and the error catalog — error count stays 76. Also, per the known leak path, the meta-directive line "Generate task harder than expert level!" was stripped from the `scenario:` value so it cannot reach PRD.md; the domain scenario text itself is verbatim and unmodified, starting at "2806. Packaging Machinery Manufacturing & Field Service …".

No sibling `task_*/` directory was read, listed, or grepped at any point.

Orchestrator verification: all three files parse as YAML; SCAFFOLD.yaml top-level keys confirmed to exclude both design keys; `grep -rn "harder than expert" *.yaml` returns nothing — the difficulty directive did not leak.

## Step 3: Copy shared files — 2026-09-05T02:20:30.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-05T02:52:00.000Z

Subagent summary (verbatim):

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2806_packaging_machinery_manufacturing_field_service/workspace/PRD.md`.

**Final line count:** 515 lines (~94 KB), built in 8 chunked appends plus 5 targeted edits.

**Section list, in order**
1. Introduction (3 paragraphs)
2. Global Specifications & System-Wide Principles — 2.1 Actors and Role-Based Access Control · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 Resource Identity, Timestamps and Versioning · 2.5 The Logical Factory Clock · 2.6 Money, Percentages and Rounding Discipline · 2.7 Version Pinning on Slot Reservation and Stocking Publication · 2.8 Rejection Precedence and Resource Resolution Order · 2.9 Conserved Ledgers · 2.10 Cascades, Parallel Status Dimensions and Compensating Actions
3. Business Logic & Workflows — 3.1 Foundations (customers, catalog, lines, field force) · 3.2 Product Trials and Configuration Selection · 3.3 Passed Trial to Priced Order + Commercial Track · 3.4 Long-Lead Procurement and Build-Slot Scheduling · 3.5 Factory Acceptance, Guarantee and Rework Cascade · 3.6 Installation, Site Acceptance and Operator Training · 3.7 Aftermarket Kits and Spare-Parts Stocking · 3.8 Service Contracts, Coverage Posture and Visits · 3.9 Warranty Claims, Reviews, Adjudication and Goodwill
4. Endpoint Definitions (4-column table)
5. Error Code Catalogue (2-column table)

**Coverage** — 74/74 endpoints (table rows counted programmatically) · 61/61 validations with their full priority ordering 1->61 including every `applies_to` scope · 17/17 calculations in prose with constants, evaluation order, pinned rounding order and all 5 dual-variant branches · 76/76 error codes (all appear in §2/§3 narrative *and* the §5 table) · 16/16 entities, 102/102 entity field names · 11/11 state machines (all 60 transitions, both parallel `MachineOrder` dimensions, the trial retest cycle, the slot rework cycle, the claim fork-join with divergent branch side-effect sets) · 2/2 concurrency rules (`expected_machine_order_version` -> `ERR_STALE_ORDER_VERSION` 412; `expected_installed_machine_version` -> `ERR_STALE_MACHINE_VERSION` 412) · 6/6 roles with identity translation (5 opaque, `CustomerContact` entity-backed to `Customer`).

**Hard contracts (verified mechanically):**
```
Field coverage check:
- entities[].fields: 102 required, 102 present, 0 missing
- endpoints[].request_body: 69 required, 69 present, 0 missing
- endpoints[].query_params: 17 required, 17 present, 0 missing
- path_params: 16 required, 16 present, 0 missing
- nested component keys (part_number/lead_time_days/unit_price_cents/qty): 4/4 present
Status: PASS

Rule coverage check:
- validations[] with priority: 61 checked, 61 expressed in prose (ordered ladder), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (endpoint + occ field + error_id + 412), 0 missing
- state_machines[].transitions: 60 checked, 60 fully expressed, 0 missing
- calculations[]: 17 checked, 17 fully expressed, 0 missing
- validations[] conditions: 61 checked, 61 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 74 checked, 74 expressed, 0 missing
- entities[].fields[] structured content: 102 checked, 102 reconstructible, 0 missing
- sibling-branch symmetry: 6 groups (FAT/SAT finalize, PASS/RETEST/REJECT outcomes, RESERVED/CONFIRMED release, RESERVED/CONFIRMED displacement, two claim branches, APPROVE/REJECT) checked, 6 with equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 840
- tokens starting with `/`: 0; bare HTTP-method tokens: 0; method+path tokens: 0
Status: PASS
```

Also confirmed: §2.2 is byte-identical to `section-2.2-response-structure.md`; no fuzzy/approximating words remain; neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` nor any sibling task directory was opened. **Tail is a complete section boundary** — the document ends with the final `| \`ERR_POSTURE_RESTRICTED\` | 402 |` row of the §5 table, with no audit footer or contract-report block.

Orchestrator truncation guard (per the caller's known-failure warning): independently verified. PRD.md is 515 lines with all 5 top-level sections present in order; the §4 table region holds 74 endpoint rows and the §5 table holds 76 `ERR_*` rows; the file ends on a complete markdown table row (`| ERR_POSTURE_RESTRICTED | 402 |`) at a real section boundary, not mid-sentence. `grep "harder than expert\|expert level" PRD.md` returns nothing — the difficulty directive did not reach the PRD. No regeneration needed.

## Step 6: Generate implementation — 2026-09-05T03:24:00.000Z

Orchestrator note: Steps 5 and 6 were intended to launch in a single message for physical isolation, but landed in two consecutive messages ~40s apart. Isolation was preserved anyway on two independent grounds: (a) `test_suite/` did not yet exist (mtime 02:57) when the impl generator began writing (first impl file 02:56), and (b) the Step 6 prompt carried an absolute prohibition on reading, listing, globbing or grepping `test_helpers/` and `test_suite/` at any point, which the subagent confirmed it honoured.

Subagent summary (verbatim):

Implementation complete. Full Python + Flask server written to `/home/ubuntu/github/CodingPRD/tasks/task_2806_packaging_machinery_manufacturing_field_service/workspace/implementation/`.

## Files (3,029 lines total)

| File | Lines | Contents |
|---|---|---|
| `app.py` | 66 | Flask factory, 8 blueprints under `/packaging-oem`, `ApiError`/404/405/HTTPException/500 JSON handlers, `0.0.0.0:$PORT` (default 10000) |
| `start.sh` | 9 | `cd $(dirname $0)`, guarded `if ! python3 -c "import flask"` install, `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=2.0` |
| `store.py` | 147 | 16 in-memory dicts, logical clock (default `2026-08-01T00:00:00Z`), UUID ids, `insert/touch/rows` |
| `errors.py` / `envelope.py` / `nums.py` | 96 / 47 / 54 | 76-code catalogue, PRD §2.2 envelope, `Fraction` + half-up helpers |
| `validation.py` / `auth.py` | 235 / 49 | rung-3 shape checks, pagination (1..100 / >=0), rungs 1-2 + `CustomerContact` ownership |
| `calc.py` / `domain.py` | 207 / 185 | all pinned constants + calculations; ledgers, cascades, interval arithmetic |
| `routes_foundation / trials / orders / slots / tests / assets / service / claims` | 202 / 134 / 251 / 194 / 246 / 305 / 300 / 301 | the 74 endpoints |

## Coverage (verified programmatically, not by eye)

- **Endpoints: 74/74** — the registered URL map diffed exactly against the PRD §4 table (0 missing, 0 extra).
- **Error codes: 76/76** — every `error_id` and HTTP status diffed against PRD §5 (0 missing, 0 extra, 0 status mismatches).
- **Validations: 61** rungs implemented in PRD §2.8 order (which overrides the scaffold's precondition ordering where they disagree); OCC evaluated at rungs 30/31 *after* all state gates.
- **State machines: 11/11** (incl. MachineOrder's two parallel dimensions, the FAT-failure rework/displacement cascade, the claim fork-join where the first branch owns `status`).
- **Calculations: 17/17** — 11 in `calc.py`, 5 in `domain.py` (goodwill ledger, billability, both collision predicates, slot geometry, committed-days ledger), `slot_earliest_start` in `routes_slots.py`.
- **Entities 16, roles 6.**

## Smoke test (PORT 18806/18807, ~60 calls)

Ran the full plant lifecycle: customer -> model -> line -> engineer -> trial (PASS, `rate_ratio_pct` 96.0 / STANDARD) -> order (tier T1, fee 1,525,000, total 32,025,000) -> component PO/receive -> slot (12 days, end 2026-10-22) -> confirm -> build -> FAT (99.0, PASSED) -> ship -> install -> SAT -> ACCEPTED -> format kit (lead 30 d, price 707,500) -> stocking rec (45, then 135 after LAST_TIME_BUY) -> contract activate (pot 100,000, OPEN) -> 2 visits -> claim with 2 lines -> both reviews -> adjudicate (MACHINE_DEFECT, oem 84,000 / cust 16,000, goodwill 63,000, pot -> 37,000 RESTRICTED) -> void (pot back to exactly 100,000, OPEN, model defect counter back to 0).

Negative paths confirmed with the right codes: 401 `ERR_UNAUTHENTICATED`, 403 `ERR_UNAUTHORIZED_ROLE`/`ERR_NOT_RESOURCE_OWNER`, 400 `ERR_INVALID_REQUEST` (blank name, `limit=0`), 404 `ERR_CUSTOMER_NOT_FOUND`, 409 `ERR_DUPLICATE_IDENTIFIER`/`ERR_COMMERCIAL_STATUS_BLOCKS_CONFIRM`/`ERR_INVALID_CLAIM_STATE`/`ERR_ENGINEER_DOUBLE_BOOKED`, 412 `ERR_STALE_ORDER_VERSION`, 422 `ERR_CUSTOMER_PRODUCT_REQUIRED`/`ERR_INSUFFICIENT_CONTAINERS`/`ERR_OPERATOR_TRAINING_INCOMPLETE`/`ERR_ENGINEER_REQUIRED`/`ERR_CLAIM_HAS_NO_LINES`/`ERR_KIT_LEAD_TIME_NOT_ELAPSED`/`ERR_OBSOLESCENCE_REGRESSION`. Envelope shape confirmed on success, list (`limit`/`offset`/`total_count`/`has_more` in `meta`) and error; claim lines correctly expose only `id`/`created_at` with no `updated_at`/`version`; `_clock/set_current_utc` returns `{current_utc}`. Both servers were stopped by their own recorded port PID — no pattern-kill was used.

**Storage is in-memory only** (plain module-level dicts): a fresh boot on a second port reported `total_count: 0` and `grep -rn seed` finds only comments stating nothing is seeded.

**I never read, listed, globbed or grepped `test_helpers/` or `test_suite/`**, nor `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, or any sibling `task_*/` directory.

Two fidelity notes for your review: (1) `expected_installed_machine_version` is now **required** on `POST /stocking-recommendations` (PRD §2.7 calls both OCC fields "non-optional"; a missing field is rung 3, not 412); (2) where PRD prose and SCAFFOLD.yaml conflict I wrote the PRD — trial `record-result` always stores the measured rate, `start-build` from `REWORK_HOLD` still checks components, the defect branch from `PRODUCT_VARIATION_REVIEW` still requires a cost line, and adjudication requires an ACTIVE contract under `REJECT` as well as `APPROVE`.

## Step 5: Generate unit tests — 2026-09-05T04:07:00.000Z

Subagent summary (verbatim):

Suite complete and verified.

## Files written

**`/home/ubuntu/github/CodingPRD/tasks/task_2806_packaging_machinery_manufacturing_field_service/test_helpers/`** (Stage 1, 2331 lines)
`types.py` 472 · `fixtures.py` 644 · `api_client.py` 348 · `assertions.py` 280 · `factories.py` 263 · `api_errors.py` 167 · `constants.py` 82 · `test_users.py` 54 · `__init__.py` 21

**`.../test_suite/`** (Stage 2, `conftest.py` 26 + 16 test modules, **133 tests**)
| file | lines | tests |
|---|---|---|
| test_01_reference_data_and_catalog.py | 330 | 12 |
| test_02_product_trials.py | 413 | 13 |
| test_03_machine_order_engineering_and_pricing.py | 404 | 14 |
| test_04_procurement_and_slot_reservation.py | 369 | 11 |
| test_05_line_capacity_overlap_and_ledger.py | 258 | 7 |
| test_06_build_progression.py | 171 | 6 |
| test_07_acceptance_test_booking_and_evidence.py | 154 | 5 |
| test_08_performance_guarantee_and_rework_cascade.py | 343 | 11 |
| test_09_installation_and_site_acceptance.py | 197 | 5 |
| test_10_format_kits.py | 243 | 8 |
| test_11_spare_parts_stocking.py | 205 | 5 |
| test_12_service_contracts.py | 194 | 6 |
| test_13_visit_booking_and_engineer_assignment.py | 366 | 9 |
| test_14_visit_lifecycle_and_coverage_posture.py | 309 | 6 |
| test_15_warranty_claim_reviews_and_apportionment.py | 344 | 9 |
| test_16_goodwill_ledger_and_claim_reversal.py | 249 | 6 |

## Queue breakdown

- **Queue A (§1.8):** 19 rule instances x 2 facet tests = **38 tests**; every instance has >=2 tagged tests (verified programmatically).
- **Queue B (§1.9):** 117 instances - 20 stubs = 97 non-stub; **93 translated to 1 test each**, 4 skipped.
- Design tags: 133 tests, each with exactly one trailing `Design:` line, all resolving to a real instance; zero untagged, dual-tagged or dangling tags.

## Skipped instances (PRD-first filter, all `applies_to`-scope silence)

1. `Corner/errors/product_trial_create_for_obsolete_model_returns_409_model_obsolete` — PRD ladder rung 7 scopes `ERR_MODEL_OBSOLETE` to moving a trial onto the rig and engineering an order, never trial creation.
2. `Corner/errors/machine_order_create_with_submitted_trial_returns_409_trial_not_passed` — rung 9 and §3.3 place the PASSED-trial gate at the `engineer` transition, not at create.
3. `Corner/errors/machine_order_create_with_other_customers_trial_returns_422_mismatch` — `ERR_TRIAL_ORDER_MISMATCH` is rung 55 "when engineering an order".
4. `Corner/errors/service_contract_create_for_installed_only_machine_returns_409_machine_not_accepted` — rung 20 and §3.8 put the ACCEPTED requirement on *activation*; contract create is legal.

Also: the design's `stocking_recommendation_create_with_stale_machine_version_returns_412` asserts `recommended_qty == 250` where the PRD derives 300 for criticality A, so that test asserts the 412, the surviving ACTIVE row and the list count but deliberately omits the contradicted quantity.

## Verification run

- All 133 PRD citations re-checked against a whitespace-normalised `workspace/PRD.md` — 0 non-verbatim.
- `Design:` line count/position, docstring presence, helper-symbol existence, unused-import sweep, `py_compile` on all 17 files: all clean.
- No `pytest.mark.skip`/`skipif`/`xfail`, no mocking, no mention of "scaffold".

## Directory discipline

`ls -la` on the task root shows only `SCAFFOLD*.yaml`, `worklog.md`, `test_helpers/`, `test_suite/`, `workspace/`. `ls -la workspace/` shows only `INSTRUCTION.md`, `PRD.md`, `implementation/` — **no test directory landed under `workspace/`**, and nothing under `workspace/implementation/` was read or written. `__pycache__` dirs from compilation were removed.

## Step 7: Run tests and iterate — 2026-09-05T04:36:00.000Z

Subagent summary (verbatim):

Clean — no stray test dirs under `workspace/`, `worklog.md` untouched.

## Summary

**Iterations run:** 2

Iteration 1 (8 parallel rounds, `setsid nohup`, per-test-server isolation): 132/133 passing in every round, with a single **deterministic** failure — `test_a_rejected_claim_records_the_cause_but_spends_no_goodwill` (`assert 400000 == 0`) in all 8 rounds. No flakiness signal anywhere: no timeouts, no connection resets, no round-to-round divergence.

Iteration 2: **all 8 rounds 133/133 passed, 0 failed, 0 errors.**

**Tests deleted:** none wholesale. One assertion removed under the STEP 1c partial-coverage split:

- `test_suite/test_15_warranty_claim_reviews_and_apportionment.py:146` — `assert read_claim_line(...)["oem_line_share_cents"] == 0` on the **rejection** branch. **BRANCH-ASYMMETRIC SIDE EFFECT.** PRD §3.9 renders the approval branch fully (three-hop goodwill cascade plus the per-line share writes) but compresses the rejection branch to one clause that enumerates exactly three claim-level effects — `status` -> `REJECTED`, `oem_share_cents` -> 0, `customer_share_cents` -> full `claimed_cost_cents` — and never names `oem_line_share_cents`. Meanwhile the apportionment paragraph states verbatim: *"Cost apportionment also runs under both resolutions, and its rounding order is pinned … Each line's `oem_line_share_cents` is then its `amount_cents` multiplied by its effective percentage divided by one hundred, rounded half up to whole cents for that line."* Two divergent PRD-faithful readings exist: (i) apportionment runs on rejection too, so the line keeps its 400,000 share while only the claim-level aggregate collapses; (ii) "collapses to its extreme" sweeps the line shares to 0 as well. Reading (i) is in fact the better-supported one — §2.4 also says the line's *"apportioned share is filled in at adjudication time"*, and a rejection is an adjudication. Unique derivability broken, so the assertion goes. Driving scaffold rule: `Corner/calculations/claim_reject_charges_no_goodwill_and_leaves_budget_intact`.

The test's other seven assertions all trace to verbatim PRD prose (`REJECTED` status, `cause` still recorded, `claimed_cost_cents`, `oem_share_cents` 0, `customer_share_cents` full, `goodwill_charged_cents` 0, pot untouched at 300,000, posture `OPEN`) and were kept. The sibling approval-path assertions at lines 77-78, which assert exact per-line shares of 9,185 and 2,526, are fully covered and were left alone.

**Fixes applied to `test_helpers/`:** none. Audited `fixtures.py`, `factories.py`, `assertions.py`, `api_client.py`, `constants.py`, `test_users.py` against the failure — no fixture bug. Notably absent were both known prior-task failure modes: `factories.py` sends every money amount as an integer number of cents, and `store.iso_ms` emits exactly three fractional digits, so no ISO-precision canonicalisation was needed.

**Fixes applied to `implementation/`:** none. The implementation was already PRD-faithful on the one failing point — `routes_claims.adjudicate_warranty_claim` writes each line's `oem_line_share_cents` before branching on resolution, which is what *"Cost apportionment also runs under both resolutions"* requires, then correctly zeroes only the claim-level `oem_share_cents` on `REJECT`. Weakening that to satisfy the test would have stripped a PRD-required computation, so per the cardinal rules the unfair assertion was removed instead.

Orchestrator verification (Step 7 sweep artifacts checked independently, not taken on trust): all 8 `workspace/implementation/results.{1..8}.json` exist, are complete JSON, and every one reports `total: 133, passed: 133, failed: 0, errors: 0`.

Step 8 skip-condition adjudication: NOT skipped. Step 7 ran 2 iterations and made 1 `test_suite/` change, so the pipeline is past baseline. Implementation fixes were 0, so `PRD_FINALIZED.md` may legitimately come back byte-identical — but the removed assertion does mark a genuine PRD silence (the rejection branch's per-line apportionment side effect), which is exactly what Step 8 exists to pin, so the subagent is spawned.

## Step 8: Finalize PRD — 2026-09-05T04:39:00.000Z

Subagent summary (verbatim):

Done. `PRD_FINALIZED.md` written with exactly one revised sentence.

**Line counts:** PRD.md 515 lines / PRD_FINALIZED.md 515 lines — 0 line delta; 1 of 515 lines revised (0.19% of lines touched, +1 clause appended to §3.9's rejection sentence).

**Change:**
- §3.9 (Warranty Claims, rejection branch) — revise — appended one clause pinning that on `REJECT` the per-line `oem_line_share_cents` retains the apportioned value and is not zeroed; only the claim-level fields collapse — `implementation/routes_claims.py:241-249` (shares written for all lines at 241-242, *before* the `REJECT` branch at 243 zeroes only the claim-level `oem_share_cents`).

**Pre-edit search log (the single edit):**
- (a) **Subject:** the lifecycle of `claim_lines.oem_line_share_cents` — when it is written, by what, and whether any branch clears it.
- (b) **Impl paths enumerated:** `grep -rn "oem_line_share" implementation/` returned exactly two writers — `routes_claims.py:114` (creation, initialised to 0) and `routes_claims.py:242` (the adjudication apportionment write). Read in full: `routes_claims.py` (all claim endpoints — create line, list/read line, both review sign-offs, `adjudicate_warranty_claim`, `void_warranty_claim`, `_exhaustion_sweep`, `_release_holds`), `calc.py::claim_cost_apportionment` / `line_effective_pct` / `claim_goodwill_charge` / `coverage_posture`, `domain.py` (`claim_lines_of`, `recompute_claimed_cost`, `goodwill_ledger_value`, `recompute_machine_open_claims`), and `envelope.py` + `store.py` field shaping to confirm the field is serialised as stored rather than recomputed or filtered on read. Confirmed: `void_warranty_claim` resets only `goodwill_charged_cents`, `oem_share_cents`, `customer_share_cents` and never touches line shares; no other route, helper, or cascade writes the field; nothing re-runs apportionment.
- (c) **Wording adjustment:** scoped the new clause explicitly to the rejection branch ("The collapse is confined to those fields on the claim itself… a rejection does not zero it") instead of a general claim such as "line shares are never cleared." A universal never-cleared statement would have been a fresh assertion about the `VOID` path — which the impl leaves silent-but-unchanged and which PRD.md's void paragraph also does not mention — so the narrower phrasing keeps every enumerated path (creation-at-0, approval, rejection, void, read/list) consistent with the new sentence.

No implementation fixes existed in the Step 7 diff, and the deleted assertion was the only PRD-silence signal, so no other edits were made.

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` shows exactly one changed line (348) — the §3.9 rejection sentence with the new trailing clause appended, nothing else. Both files are 515 lines.

## Step 9: Complete PRD — 2026-09-05T05:00:00.000Z

Orchestrator note: Step 9 was run as THREE SEQUENTIAL module-partitioned passes over one shared `workspace/PRD_COMPLETED.md`, because a single agent scanning a 3029-line / 17-module implementation against a 515-line PRD reliably hits the ~64k output cap and returns a byte-identical file. Pass 1 did the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from `cp`/`Write` and edited in place. Partition: pass 1 = store/envelope/nums/errors/auth/validation/routes_foundation/routes_trials; pass 2 = routes_orders/routes_slots/routes_tests + the calc functions they reach; pass 3 = routes_assets/routes_service/routes_claims/domain + the remaining calc functions. Pass 1 found one item in pass 3's lane (`domain._apply` skipping `store.touch` on unchanged re-derivations, contradicting the global §2.4/§2.10 claims) and handed it forward rather than editing out of lane; pass 3 resolved it.

### Pass 1 summary (verbatim)

Pass 1 complete. `cp` from `PRD_FINALIZED.md` -> `PRD_COMPLETED.md` was done as the first action; all subsequent work was `Edit`-only against `PRD_COMPLETED.md`.

**Counts: 17 ambiguity-pins, 2 mismatch-revisions** (19 changed lines, all in-paragraph; file remains 515 lines, section/table structure byte-identical in shape).

- §2.1 (headers) — insert — ambiguity — "blank" defined as no non-whitespace char; both header values are whitespace-stripped before use (so a padded role/ID is accepted and ownership compares the trimmed ID); both-missing still reports `ERR_UNAUTHENTICATED` — auth.py:20-28
- §2.2 (`api_request_id`) — insert — ambiguity — format pinned as `req_` + exactly 20 chars from `A`-`Z` and `0`-`9` — store.py:109-111
- §2.2 (`api_request_timestamp`) — insert — ambiguity — read from the logical clock, not wall time, so responses without an intervening clock move carry identical timestamps — envelope.py:9-11
- §2.2 (`data`) — insert — ambiguity — internal bookkeeping keys (the insertion-sequence tie-break key) are stripped at every depth — envelope.py:14-22, store.py:120
- §2.2 (`meta`) — insert — ambiguity — pagination keys appear *only* on list responses; single-object success `meta` carries just the two base keys — envelope.py:25-41
- §2.3 (pagination params) — insert — ambiguity — `limit`/`offset` must parse as whole integers after trimming; `abc`/`10.5`/empty -> `ERR_INVALID_REQUEST` — validation.py:195-215
- §2.3 (ordering) — insert — ambiguity — `created_at` ties (routine, since the clock is logical) break by ascending insertion order; `offset` at/beyond `total_count` yields an empty array, not an error — store.py:138-140, validation.py:234
- §2.3 (filters) — insert — ambiguity — enum-valued filters are shape-validated (bad value -> 400, not empty result); id/free-text filters are exact-equality and never existence-resolved (unknown id -> empty page); listings and single reads are not role-scoped, so a `CustomerContact` sees other customers' rows — validation.py:218-231, routes_trials.py:45-64
- §2.4 (identity) — insert — ambiguity — `id` is a v4 UUID in canonical lower-case 36-char form; milliseconds are truncated not rounded, always 3 digits + `Z`; unrecognised body keys are silently ignored; storage is in-memory and never seeded — store.py:56-64, 100-122
- §2.5 (clock) — insert — ambiguity — `data` is exactly `{current_utc}`; `to_iso8601` accepts `Z`, numeric offsets (normalised to UTC), naive values (read as UTC) and any fractional width; the clock may be moved backwards without error — validation.py:156-171, routes_foundation.py:196-202
- §2.6 (money/percentages) — insert — ambiguity — percentages serialize as bare JSON numbers; client percentages must be JSON numbers (bool/string rejected) and are quantised half-up to 2dp *before* the range check (`40.004` accepted, `40.005` rejected); all arithmetic is exact-rational, never binary float — nums.py:11-48, validation.py:86-96, envelope.py:20-21
- §2.8 rung 3 — insert — ambiguity — five shape conventions: `null` == omitted; absent body == `{}` (non-object body rejected); integer fields accept integral floats but never booleans/strings; booleans accept only `true`/`false`; required strings length-checked raw but must hold a non-whitespace char — validation.py:19-127
- §2.8 rung 8 — **revise** — **mismatch** — the ladder ordered rung 6/7 above rung 8 unconditionally; impl resolves trial state first on start-testing (it selects the edge), so a trial outside `SUBMITTED`/`RETEST_REQUIRED` reports `ERR_INVALID_TRIAL_STATE` even with a suspended customer, and rungs 6/7/45 apply only to the `SUBMITTED` edge, rung 44 only to the `RETEST_REQUIRED` edge — routes_trials.py:73-100
- §3.1 (customers) — **revise** — **mismatch** — "a suspended customer's trial can no longer be moved onto the rig" qualified to "**from `SUBMITTED`**"; plus suspension is ungated/repeatable and still bumps `version`; `legal_name` is not unique — routes_foundation.py:46-52
- §3.1 (models) — insert — ambiguity — `max < min` diameter is `ERR_INVALID_REQUEST` (equal bounds legal); obsolete is ungated/repeatable and bumps `version`; `model_code` uniqueness spans all lifecycle statuses, exact and case-sensitive, checked after all shape rules — routes_foundation.py:70-104
- §3.1 (lines) — insert — ambiguity — maintenance-hold ungated/repeatable/one-way (no return to `OPEN`); `line_code` uniqueness identical in scope and ordering — routes_foundation.py:119-147
- §3.1 (engineers) — insert — ambiguity — `certifications` is optional (omitted -> `[]`), elements must be non-blank strings but are **not** constrained to the four families, duplicates kept, match is exact/case-sensitive; leave is ungated/repeatable/one-way and writes only `status` (no visit cascade) — routes_foundation.py:159-190
- §3.2 (trial creation) — insert — ambiguity — `measured_rate_cpm` and `rate_ratio_pct` both start at 0; FK resolution order is `customer_id` then `machine_model_id`, ownership after both; trial listings/reads are not ownership-scoped — routes_trials.py:22-42
- §3.2 (retest loop edge) — insert — ambiguity — the retest ceiling is the *only* guard; suspension, obsolescence and container fit are not re-examined on this edge — routes_trials.py:90-98
- §3.2 (record-result) — insert — ambiguity — a `PASS` that computes `NOT_FEASIBLE` is not an error: HTTP 200, figures written, `version` advances, trial stays in `TESTING` and may be re-recorded — routes_trials.py:126-134
- §5 (preamble) — insert — ambiguity — `message` is not contractual, each code has one status; the 76-row table is exhaustive for the business surface, while unrouteable paths answer `ERR_NOT_FOUND`/404 and undeclared methods `ERR_METHOD_NOT_ALLOWED`/405 in the same envelope; trailing slashes are insignificant — app.py:37-44, 26-27

Verified separately: the §5 catalogue and `errors.py` agree exactly — same 76 codes, same 76 HTTP statuses, no drift in either direction (no edit needed to the table itself). Also confirmed across all six non-partition route modules that every enum filter uses `query_enum` and every id/code filter uses `query_str`, so the §2.3 filter pin is true service-wide.

**Final `wc -l` of PRD_COMPLETED.md: 515.**

Note for passes 2/3: I deliberately left one item in their lane — `domain._apply` (domain.py:75-81) skips `store.touch` when a recomputed derived value is unchanged, which contradicts §2.4 ("recomputations of derived fields count as mutations") and §2.10 ("each row a cascade touches has its `version` incremented"). Whoever owns `domain.py` should pin that.

### Pass 2 summary (verbatim)

Pass 2 complete. All edits were made in place with the Edit tool — I did **not** `cp` or `Write` over `workspace/PRD_COMPLETED.md`, and all 19 of pass 1's changed-line hunks are still present (verified: no line got shorter, line count unchanged at 515).

**Counts: 17 ambiguity-pins, 3 mismatch-revisions (20 changes across 17 lines).**

- §3.3 create order — insert — ambiguity — suspension is the *only* gate at creation; trial `status`, model `lifecycle_status` and trial/customer/model coherence are all unexamined until engineering — `routes_orders.py:40-45`
- §3.3 engineer — insert — ambiguity — `open_order_count` re-derivation is write-only-if-different, so the customer row's `updated_at`/`version` do not move on this transition — `routes_orders.py:120`, `domain.py:75-90`
- §3.3 commercial-advance — insert — ambiguity — `target_status: QUOTED` clears the enum then fails `ERR_INVALID_ORDER_STATE` (not 400); `PAID`/`WRITTEN_OFF` impose no `fulfillment_status` condition — `routes_orders.py:142-149`
- §3.3 ship — insert — ambiguity — a money track short of `PO_RECEIVED` reports `ERR_INVALID_ORDER_STATE`, evaluated after the `FAT_PASSED` check and ahead of the component check; zero components satisfies vacuously — `routes_orders.py:159-169`
- §3.4 procurement line create — insert — ambiguity — no order-state gate at creation and the order row is not touched — `routes_orders.py:177-193`
- §3.4 release-po — insert — ambiguity — component `status` resolved first (`ERR_INVALID_COMPONENT_STATE`), order state second (`ERR_INVALID_ORDER_STATE`) — `routes_orders.py:222-228`
- §3.4 reserve / overlap — insert — ambiguity — the same order's outstanding `RESERVED` slot is a normal incumbent, so overlapping re-plans get `ERR_SLOT_OVERLAP` instead of superseding — `routes_slots.py:69-77`
- §3.4 reserve / capacity — insert — ambiguity — ledger read *before* this request's supersede effect (superseded days still count), ceiling inclusive — `routes_slots.py:78-81`
- §3.4 reserve / supersede effects — insert — ambiguity — sweep spans other lines, `CONFIRMED`+ slots never superseded, every affected line re-derived, write-only-if-changed — `routes_slots.py:92-102`
- §3.4 confirm — insert — ambiguity — non-`ENGINEERED` order -> `ERR_INVALID_ORDER_STATE`, checked third (line -> slot -> fulfillment -> commercial) — `routes_slots.py:136-146`
- §3.4 start-build — insert — ambiguity — slot status selects the guise and is resolved first; wrong order state -> `ERR_INVALID_ORDER_STATE` ahead of components; no geometry/ledger re-derivation — `routes_slots.py:158-174`
- §3.4 release — insert — ambiguity — walk-back applies only if the order still reads `SLOTTED` — `routes_slots.py:190-193`
- §3.5 booking — insert — ambiguity — latest-created `PASSED` FAT supplies the `ERR_SAT_BEFORE_FAT` floor; none => check skipped — `routes_tests.py:44-51`
- §3.5 booking — insert — ambiguity — `required_operators_trained` is accepted and stored on FAT bookings, never consulted — `routes_tests.py:30-31,65`
- §3.5 finalize — revise — mismatch — `operators_trained_count` is stored for both kinds (defaulting to 0); only SAT compares it — `routes_tests.py:130-149`
- §3.5 rework hop two — insert — ambiguity — geometry recomputed absolutely from `requested_slot_days` + cumulative `rework_days`; `start_date` never moves — `domain.py:173-179` via `routes_tests.py:204`
- §3.5 rework hop three — revise — mismatch — sweep window is inclusive at the reworked slot's `start_date` and exclusive at `end_date`+buffer; only the candidate's `start_date` is tested; other statuses/lines immune — `routes_tests.py:209-222`
- §3.5 abandonment — insert — ambiguity — hop one still writes `fat_failure_count`=3 and +7 `rework_days`; no geometry recompute, one ledger re-derive, no sweep, then `open_order_count` re-derived — `routes_tests.py:184-199`
- §3.1 `open_order_count` — revise — mismatch — trigger list was missing abandonment on the third FAT failure — `routes_tests.py:198`
- §3.6 SAT pass — insert — ambiguity — only the earliest-created machine of the order advances, and only from `INSTALLED` — `routes_tests.py:241-246`

`wc -l PRD_COMPLETED.md` = **515**; `diff PRD_FINALIZED.md PRD_COMPLETED.md | wc -l` = **142** (up from pass 1's 80; changed-line hunks now 15, 51-52, 54-55, 81, 83, 85, 89, 99, 103, 126, 134, 213, 215, 217, 219, 223, 227, 231, 234, 236, 240, 242, 246, 248, 256, 258-259, 261, 263, 267, 271, 277, 279, 288, 436). No new sections or paragraphs were added; pass 3's modules (`routes_assets.py`, `routes_service.py`, `routes_claims.py`, `domain.py` as a subject) were left untouched — §3.7-§3.9 and §2.9's goodwill paragraph are unedited.

### Pass 3 summary (verbatim)

All edits are complete and verified. Final integrity check passed.

**No `cp`, no `Write`, no recreation** — `workspace/PRD_COMPLETED.md` was edited in place with the Edit tool only (23 Edit calls landing on 22 distinct lines). All of passes 1 and 2's changed lines (15, 51-52, 54-55, 81, 83, 85, 89, 99, 103, 126, 134, 213-288, 436) are still present in the diff, untouched.

**Counts: 17 ambiguity-pins, 6 mismatch-revisions.**

- §2.4 — revise — mismatch — general `_apply` semantics: outright assignments (status/ledger/posture/price/lead time/geometry) always version the row; re-derivations of the five maintained aggregates write only when the figure differs, and are a total no-op otherwise — `domain.py:75-81`
- §2.10 — revise — mismatch — "each row a cascade touches is versioned" narrowed to "each row a cascade actually writes", with the aggregate-re-derivation exception carried over from §2.4 — `domain.py:75-81`
- §3.7 — insert — ambiguity — `components` is optional and defaults to empty (how an unquotable kit exists); elements must be objects; `part_number` 1-40 chars; lines persisted and echoed in draft order; drafting has no machine-status gate — `routes_assets.py:85-122`
- §3.7 — insert — ambiguity — quoting writes the kit alone (`version` +1), the covered machine is only read — `routes_assets.py:146-168`
- §3.7 — insert — ambiguity — kit-family comparison is exact and case-sensitive — `calc.py:120-122`
- §3.7 — insert/revise — ambiguity — acceptance date is internal bookkeeping (absent from payload per §2.2); lead-time comparison inclusive; `current_format_family` rewritten unconditionally, so a same-family refit still versions the machine — `routes_assets.py:181,193-204`
- §3.7 — insert — ambiguity — `part_number` 1-40 chars on stocking publication — `routes_assets.py:223`
- §3.7 — insert — ambiguity — new recommendation starts `obsolescence_status` `ACTIVE` (first qty at the 1.00 multiplier); *every* prior active row for the machine+part is superseded and versioned; the machine is written on every publication including the first — `routes_assets.py:241-259`
- §3.7 — insert — ambiguity — all four chain members incl. `ACTIVE` clear shape validation and fail as regression; lifecycle check precedes the chain check; notice versions the recommendation and never touches the machine — `routes_assets.py:291-305`
- §3.8 — insert — ambiguity — `pm_visits_used` starts at 0 — `routes_service.py:55`
- §3.8 — insert — ambiguity — a zero initial pot activates straight into `BUDGET_EXHAUSTED`; window bounds inclusive; activation writes the contract alone — `routes_service.py:96-106`
- §3.8 — insert — ambiguity — posture re-derived on exactly three occasions (activate, approved adjudication, void) and nowhere else — `calc.py:187-192`, `routes_service.py:103`, `routes_claims.py:262,290`
- §3.8 — insert — mismatch — expire/terminate also re-derive `pm_visits_used` (it drops), touch no pot/posture, and version the contract exactly once — `routes_service.py:120-142`
- §3.8 — insert — ambiguity — `start_ts`/`end_ts` parsed with §2.5 latitude (Z, offset, no zone, any fractional width) and stored in canonical millisecond form — `validation.py:148-166`, `routes_service.py:233-234`
- §3.8 — revise — mismatch — a `REMOTE_DIAGNOSTIC` visit *may* name an engineer: it is resolved, put through every engineer gate and stored; the engineer gates are skipped entirely when none is named — `routes_service.py:171-219`
- §3.8 — revise — mismatch — the double-booking scan excludes any visit carrying no engineer (not "remote sessions", which may carry one) — `routes_service.py:196-206`
- §3.8 — insert — ambiguity — `billable` written as part of creation (`version` stays 1); `pm_visits_used` re-derivation leaves the contract untouched for `CORRECTIVE`/`REMOTE_DIAGNOSTIC` bookings — `routes_service.py:229-240`
- §3.8 — revise — mismatch — completion: `end_ts` comparison inclusive, `findings_code` required, re-derivation never writes the contract (all three states counted), `billable` not recomputed; a `PM` cancellation does move the count — `routes_service.py:266-300`
- §3.9 — revise — ambiguity — cost lines admitted only from `SUBMITTED`, `PRODUCT_VARIATION_REVIEW`, `DEFECT_REVIEW` — `routes_claims.py:106`
- §3.9 — insert — ambiguity — the three adjudication gates run in §2.8 ladder order, contract-`ACTIVE` first — `routes_claims.py:218-228`
- §3.9 — insert — ambiguity — under either resolution the machine's `open_claim_count` is re-derived as the request's last effect — `routes_claims.py:248,267`
- §3.9 — insert — ambiguity — sweep only when the posture changed *in this request*; approval against an already-exhausted pot is legal, charges 0; the contract row is written on every approval — `routes_claims.py:261-266`
- §3.9 — insert — ambiguity — void: hold release conditional on having been exhausted; `cause`, `claimed_cost_cents` and per-line `oem_line_share_cents` survive; contract written on every void; `open_claim_count` re-derived (no change); released `billable` recomputed against the freshly re-derived posture; contract check precedes claim state — `routes_claims.py:199-207,282-300`

**The `domain._apply` adjudication.** Verified directly: `_apply` (domain.py:75-81) returns early without `store.touch` when `row[field] == value`, and it is the only write path for all five maintained aggregates (`open_order_count`, `committed_slot_days`, `open_claim_count`, `pm_visits_used`, `claimed_cost_cents`). Everything else — statuses via `set_order_fulfillment`, the goodwill balance, posture, prices, quoted lead times, slot geometry — writes unconditionally through `store.touch`. So the global claim was wrong only for aggregate re-derivations. I split §2.4's sentence into two rules (unconditional assignment vs. write-only-if-different re-derivation, naming the five aggregates) and kept the original goodwill-debit example, extending it to note the contract versions even at a 0 charge. §2.10 was narrowed from "each row a cascade touches" to "each row a cascade actually writes", pointing back at the §2.4 exception. Both are generalisations of — and so consistent with — the site-specific pins passes 1 and 2 committed at §3.1 (`open_order_count`), §3.3 (engineer), §3.4 (supersede sweep).

**Final integrity check: PASS.** `wc -l` = 515; `diff PRD_FINALIZED.md PRD_COMPLETED.md | wc -l` = **230** (up from 142, no prior-pass line lost); all 5 top-level sections present (`## 1`-`## 5`); 74 endpoint rows in §4; 76 `ERR_*` rows in §5; file ends on the last complete row of the §5 table (`ERR_POSTURE_RESTRICTED | 402`), not mid-sentence. Line count is unchanged because every edit was an in-paragraph insert or revision — no new paragraphs, no new sections.

### Step 9 orchestrator verification

- `cmp PRD_FINALIZED.md PRD_COMPLETED.md` -> differs (NOT byte-identical, so the scan genuinely ran); 59 lines changed relative to `PRD_FINALIZED.md`.
- Totals across the three passes: 51 ambiguity-pins, 11 mismatch-revisions.
- `PRD_COMPLETED.md` is 515 lines with all 5 top-level sections, 74 endpoint rows in §4, 76 `ERR_*` rows in §5, and ends on a complete §5 table row — no truncation.
- No `implementation/*.py` file has an mtime later than `results.1.json`, so Steps 8 and 9 were documentation-only and the verified 8/8 green sweep (133/133 each round) still describes the shipped implementation.

## Pipeline complete — 2026-09-05T05:00:00.000Z

All nine steps finished. Final state: 3095-line SCAFFOLD + 1824-line difficulty design + 6144-line corner design; 515-line PRD.md / PRD_FINALIZED.md / PRD_COMPLETED.md; 2331 lines of test_helpers across 9 modules; 133 tests across 16 test_suite modules; 3029-line Python/Flask implementation across 17 modules; 8/8 sweep rounds at 133/133.

## Post-run housekeeping — 2026-09-05T05:05:00.000Z

Bash cwd drift (known hazard) bit once: the Step 8 record was appended with a relative `worklog.md` path while the shell's cwd had persisted into `workspace/` from the preceding `diff` check, stranding that entry in `workspace/worklog.md`. Detected by a `find`-based stray sweep, spliced back into the root `worklog.md` in step order ahead of the Step 9 entry, and the stray file deleted — no content lost, nothing overwritten. All nine step entries now live in exactly one append-only worklog at the task root. `__pycache__` directories left by pytest and the generators were also removed.
