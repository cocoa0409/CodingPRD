# Worklog — task_2810_device_installment_annual_upgrade_program

## Step 1: Create task directory — 2026-09-05T00:37:13.937Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2810_device_installment_annual_upgrade_program` and its `workspace/` subdirectory. Index 2810 was pre-assigned by the orchestrating caller (no scan of ./tasks/ performed, per instructions — concurrent pipelines on this host make auto-allocation unsafe).

## Step 2: Generate Scaffold — 2026-09-05T02:06:00.000Z

Scaffold generation is complete and lint-clean.

Verdict block (verbatim):

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2810_device_installment_annual_upgrade_program/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2810_device_installment_annual_upgrade_program/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2810_device_installment_annual_upgrade_program/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    40
  §1.1 entities declared:     13
  §1.8 instances scanned:     24
  §1.9 instances scanned:     51
  Calls scanned (§1.8+§1.9):  895

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Files:
- SCAFFOLD.yaml — 3378 lines, 165 KB
- SCAFFOLD_DIFFICULTY_DESIGN.yaml — 2693 lines, 170 KB (single top-level key `scaffold_difficulty_design`)
- SCAFFOLD_CORNER_DESIGN.yaml — 4300 lines, 256 KB (single top-level key `scaffold_corner_design`)

All three parse with `yaml.safe_load`; SCAFFOLD.yaml contains zero occurrences of `scaffold_difficulty_design`/`scaffold_corner_design`.

SCAFFOLD.yaml (§1.0–§1.7): `domain_name: device-installment-upgrade-program`, `api_prefix: "/"`, archetypes ledger_reconciliation + workflow_orchestration, layers `dual_variant_calculation, cascading_side_effects, rate_threshold_triggers, optimistic_concurrency`, topology flat, SM shape parallel, role model segregation_of_duties, consistency immediate, difficulty expert_plus.

13 entities (Customer, CarrierAccount, DeviceModel, DeviceUnit, CreditApplication, InstallmentLoan, Installment, PaymentPosting, DelinquencyEvent, UpgradeRequest, TradeIn, DiagnosticReport, PayoffQuote) · 12 state-machine dimensions · 1 §1.2.1 OCC rule (`upgrade-request-create-stale-loan`, `expected_loan_version`, ERR_STALE_LOAN_VERSION 412) · 10 calculations (6 with dual variants) · 62 ordered validations (priorities 1–107) · 40 endpoints · 52 errors · 6 roles. Logical clock is server-owned via `POST /_clock/set_current_utc` (monotonic, ProgramAdmin-only) and the servicing calendar via `POST /servicing/daily-run`.

§1.8 — 24 instances, all nine rules >=2: dual_variant_calc 2 · combinatorial_formula 3 · non_linear_state_machine 3 · transitive_cascade 2 · priority_pair_validation_conflict 3 · boundary_precision_check 4 · cross_entity_state_dependency 3 · resource_temporal_overlap 2 · compensating_invariant 2.

§1.9 — 75 instances across all nine claim-extraction sections: entities 11 · state_machines 15 · calculations 13 · validations 8 · endpoints 6 · errors 9 · cross-cutting complexity layers 6 · consistency model 2 · rbac 5. Split: 51 full test recipes + 24 `excluded_because` stubs, every stub citing an existing §1.8 instance by exact name and carrying no `test_recipe`. All 99 instance names are unique across the two design files. All 52 error codes are triggerable somewhere in the §1.8/§1.9 union.

Notes for downstream steps:
- The scenario key holds the verbatim scenario text **minus** the leading "Generate task harder than expert level!" directive line, deliberately, so the difficulty instruction cannot leak into PRD.md via the scaffold; the intent is carried by `difficulty_level: expert_plus` instead.
- Three SCAFFOLD.yaml consistency fixes made during generation: `UNLOCK_MIN_PAID_INSTALLMENTS: 6` is now actually consumed by the unlock precondition; `DeviceModel.reserved_slot_count` semantics were de-contradicted (increment on request creation, release on SUPERSEDED/EXPIRED/COMPLETED); REVERSAL postings are now mandated to report `installments_satisfied_count: 0` and `overpayment_cents: 0`.
- Reusable reference arithmetic is embedded in the recipes (Handset B 89900/999/24mo -> principal 89900, installments 1-23 = 4745, #24 = 4741, obligation 113876; 56940 payment -> 12 PAID, obligation 56936; EARLY_CANCELLATION at 0 paid = 70822; UPGRADE_ROLLOVER at 12 paid = 38714 vs EARLY_CANCELLATION 36659).

Orchestrator verification: `grep -rn "harder than expert"` across all three scaffold files returns nothing — no difficulty-directive leak.

## Step 3: Copy shared files — 2026-09-05T02:25:01.641Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T02:44:00.000Z

PRD generated at `workspace/PRD.md` — **432 lines**, 111,306 bytes, built with 11 incremental heredoc appends. The file ends cleanly at the final row of the §5 table (`| ERR_ROLLOVER_SHORTFALL_EXCEEDS_LIMIT | 422 |`), with no audit footer and no trailing prose fragment. Last heading: `## 5. Error Code Catalogue`.

Section list:
- `# Device Installment Upgrade Program API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 User and Role-Based Access Control; 2.2 API Response Structure (fixed block, verified byte-identical to `section-2.2-response-structure.md`); 2.3 Pagination; 2.4 Resource Identity, Audit Fields and the Logical Clock; 2.5 Cents, Basis Points and Rounding Discipline; 2.6 Guarding the Loan Ledger Against a Stale Read; 2.7 The Screening Order of Every Request; 2.8 Parallel Status Dimensions and Cascade Discipline; 2.9 Sub-Collection Reads and Reverse Reachability; 2.10 Segregation of Duties and the Financing Lock
- `## 3. Business Logic & Workflows` — 3.1 Enrolment, the Catalog and Carrier Registration; 3.2 Credit Application and the Underwriting Decision; 3.3 Origination: Principal, Schedule and Handset; 3.4 Putting the Handset on a Network, and Getting It Unlocked; 3.5 Money In: The Allocation Waterfall and Its Reversal; 3.6 The Servicing Calendar: Ageing, Late Fees, Default and the Financing Lock; 3.7 Pricing a Payoff, and Leaving the Program; 3.8 The Annual Upgrade: Earning It, and Reserving a Window; 3.9 Trade-In, Bench Grading, Disputes and the Successor Loan (9 subsections, within the 5-9 range)
- `## 4. Endpoint Definitions` — 4-column table, 40 data rows
- `## 5. Error Code Catalogue` — 2-column table, 52 data rows

Coverage confirmation:
- §1.1 entities: all 13 entities rendered in prose.
- §1.2 concurrency: the `expected_loan_version` OCC rule rendered in §2.6 and re-anchored in §3.8.
- §1.3 calculations: all 10 calculations rendered, including every variant (`rule_of_78`/`pro_rata`, `upgrade_rollover`/`early_cancellation`, `declared_estimate`/`final_graded`). All 28 named constants rendered as literal prose values.
- §1.4 validations: all 62 validations rendered as the 11-band priority ladder in §2.7; all 52 distinct error IDs present in prose.
- §1.5 endpoints: all 40 endpoints in §4, methods/paths/roles/status semantics matched against the scaffold.
- §1.6 errors: all 52 error IDs with scaffold-exact HTTP statuses.
- §1.7 roles: all 6 roles (`Customer`, `RetailAssociate`, `CreditUnderwriter`, `ServiceTechnician`, `CollectionsOfficer`, `ProgramAdmin`) named and scoped.
- State machines: all 12 machines, all declared states and all 77 transitions' endpoint states appear in prose.

Hard Contract reports:
- **Contract 1 — Field-Name Coverage: PASS.** 174/174 `entities[].fields[].name` appear verbatim in backticks (0 missing). 56/56 distinct endpoint `input` identifiers appear verbatim in backticks (0 missing), after normalising the scaffold's trailing-`?` optional marker. Reverse pass found 164 backticked snake_case tokens of which only 14 are not declared fields/inputs — `api_request_id`, `api_request_timestamp`, `response_type`, `error_id`, `total_count`, `has_more`, `req_` (envelope), `current_utc` (clock input), and `processed_loan_count`, `late_fees_assessed_cents`, `transitioned_loan_count`, `defaulted_loan_count`, `expired_upgrade_request_count`, `expired_quote_count` (daily-run summary output) — all sourced from the scaffold, so no identifier was invented.
- **Contract 2 — Rule Coverage: PASS.** Validation priority ordering and `applies_to` scopes rendered as the explicit 11-band ladder in §2.7; the loan-version OCC rule with its "after existence and cross-reference, before every state precondition" placement in §2.6/§2.7; cross-entity side effects rendered as named cascade links (diagnostic-failure band downgrade + conditional financing lock, compensating PASS-regrade restoration, completion's handset-release and carrier-repoint cascades, trade-in cancellation cascades); field-level structured content rendered (condition multipliers, screen/battery deduction tiers, origination-fee tiers, credit limits per band, downgrade ladder); sibling-branch symmetry rendered for `rule_of_78`/`pro_rata`, `upgrade_rollover`/`early_cancellation`, `declared_estimate`/`final_graded`, and PASS/FAIL grading. All 12 state machines, 77 transitions, 10 calculations, 62 validations and their endpoint side effects are represented.
- **Contract 3 — §3 Path Purity: PASS.** 1,124 backticked tokens (342 distinct) in §3; 0 violations. Supplementary unbackticked scan for path-like `/segment` strings inside §3 also returned zero hits.

Orchestrator truncation check (per the known doc-generator failure mode): `tail -c 1200` shows the file terminating on a complete §5 error-table row; `grep -n "^#"` shows all 5 top-level sections plus 10 §2 subsections and 9 §3 subsections present. Not truncated — no regeneration needed. Leak check `grep -in "harder than expert|expert_plus|scaffold"` on PRD.md returns nothing.

## Step 5: Generate Unit Tests — 2026-09-05T03:29:00.000Z

Test generation is complete and audited.

Output (all at the TASK ROOT — verified nothing under `workspace/`): `ls -d .../{test_helpers,test_suite}` resolves; `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation` (untouched by me). `worklog.md` untouched (mtime 02:44, predates this session's writes).

**`test_helpers/` — 9 files, 2329 lines** (`__init__.py` 46, `types.py` 463, `api_client.py` 172, `api_errors.py` 118, `constants.py` 233, `factories.py` 244, `test_users.py` 84, `assertions.py` 352, `fixtures.py` 617).

**`test_suite/` — 9 files, 8149 lines, 132 tests**: `conftest.py` 62; `test_01_pricing_and_formulas.py` 667 (11), `test_02_lifecycles_and_cascades.py` 1094 (13), `test_03_precedence_and_boundaries.py` 971 (15), `test_04_dependencies_overlap_compensation.py` 956 (16), `test_05_entity_contracts.py` 881 (16), `test_06_state_transitions.py` 890 (15), `test_07_calculations_and_endpoints.py` 915 (12), `test_08_errors_rbac_consistency.py` 1713 (34).

Coverage — complete, zero instances skipped:
- Queue A (§1.8): **24/24 non-stub instances, all with >=2 tests** (2 difficulty instances carry `excluded_because` and are stubs).
- Queue B (§1.9): **51/51 non-stub instances, all with >=1 test** (24 stubs skipped silently).
- No instance failed the PRD-first filter. What *was* dropped is ~15 individual sub-assertions inside otherwise-covered instances, each recorded against a Silence pattern — dominantly **computed-field** (`projected_rollover_balance_cents` / `credit_shortfall_cents` / `funding_flag`, defined off "the rollover payoff evaluated at the last recompute" when no rollover quote exists yet), **cross-entity-cascade** (a loan's `version` after a sweep that only clears its `upgrade_hold_flag`), **error-precedence** (intra-sweep DelinquencyEvent ordering), **default-value** (`requested_term_months` omission, given the stated 24-month default), and **branch-asymmetry** (`condition_multiplier_bps` on a FAIL report).

Automated acceptance audit (`/tmp/audit_2810.py`) — 0 problems, 0 warnings. Every test: exactly one `Design:` line, last in the docstring, resolving to a literal `name:` in the right queue/section (no dangling, dual, or stub-targeted tags); at least one whitespace-normalised **verbatim PRD sentence** per docstring; no `skip`/`xfail`/placeholder; no `data["data"]` double-unwrap; no money-as-string; every `test_helpers` import resolves. All 18 `.py` files `py_compile` clean. Status assertions are consistent across all 8 files (every creating endpoint 201, everything else the 200 default), matching PRD §4's stated rule.

Notable findings for downstream steps:
- **One helper defect, found and fixed by the generator:** `fixtures.setup_second_customer` ignored its `model_id`, so it silently published a *new* model and could never build a shared-model/shared-capacity scenario. No test used it (two writers worked around it inline). It now takes whole `model`/`target_model` records, and `setup_active_loan` gained `existing_model`/`existing_target_model` (purely additive; re-audited clean after the change).
- **Design-index vs PRD contradictions, resolved in the PRD's favour** (worth knowing during Step 7 triage): `ERR_NOTHING_TO_ALLOCATE` is 409 not 422; `ERR_CLOCK_NOT_MONOTONIC`/`ERR_INVALID_REQUEST` are 400 not 422; `ERR_FULFILLMENT_WINDOW_ELAPSED` is 409 not 422; regrade answers 201 not 200; a fresh `DECLARED` trade-in has `credit_final_cents` **null**, not 0; declaring a trade-in moves possession to `RETURN_PENDING`, not `WITH_CUSTOMER`; quotes supersede only within the same `quote_type`; `Customer.version` is 2 (not 1) after a credit decision writes the band back.
- **One PRD-internal ambiguity** flagged independently by three writers: §2.6/§3.6 say the sweep leaves an unchanged loan's `version` alone, while §2.8 says a cascade bumps the touched entity's `version` — these collide for a loan whose only sweep-side change is `upgrade_hold_flag`. No test asserts a version delta in that shape.
- Fixture caveat for whoever extends the suite: `setup_active_loan(credit_score_band="SUBPRIME")` cannot originate unaided (89900 principal exceeds the 80000 limit -> `CONDITIONAL_APPROVED`); it needs `down_payment_cents=9900`.

## Step 6: Generate Implementation — 2026-09-05T03:24:00.000Z

Implementation complete and verified.

Deliverable: `workspace/implementation/` — 3538 lines of Python across 27 files: `start.sh` (10, executable, guarded pip install + `exec python3 app.py`), `requirements.txt` (1, `flask==3.0.3`), `app.py` (61), `constants.py` (246), `errors.py` (120), `clock.py` (99), `db.py` (84), `response.py` (58), `middleware.py` (43), `validate.py` (195), `calc.py` (211), `serialize.py` (236), `lookups.py` (51), `routes/customers.py` (88), `routes/catalog.py` (70), `routes/applications.py` (130), `routes/loans.py` (267), `routes/postings.py` (50), `routes/devices.py` (132), `routes/upgrades.py` (295), `routes/tradeins.py` (198), `routes/servicing.py` (36), `services/cascades.py` (226), `services/loans.py` (143), `services/payments.py` (177), `services/servicing.py` (184), `services/upgrades.py` (138). In-memory dicts only; nothing seeded at boot; logical clock fixed at `2026-08-01T00:00:00Z` per process.

Verification performed:
- **40/40 endpoints** registered — path-by-path match against PRD §4 (route dump diffed against the table, zero missing/extra).
- **Entity field parity**: all 13 scaffold entities' field lists match the serializers exactly (0 missing, 0 extra).
- **Error catalogue**: all 52 error IDs and HTTP statuses match both scaffold `errors[]` and the PRD §5 table; every one is actually raised somewhere in the code.
- **RBAC**: every endpoint's role list matches the scaffold; POST input field sets (incl. optional markers) match scaffold `input` exactly.
- **Response codes**: every endpoint's status matches scaffold `code`.
- **End-to-end smoke** (high port, killed by exact PID; no broad pkill): enrol -> model publish -> carrier account -> application -> PRIME decision -> origination (24-row schedule, `4167`+`900` = `5067`) -> activation -> 12 payments -> clock advance -> unlock request -> sweep counters -> upgrade request -> OCC 412 on stale version -> trade-in declaration -> receipt -> diagnostic (GOOD/40000) -> dispute -> SoD 403 on same technician -> regrade (EXCELLENT/50000) -> UPGRADE_ROLLOVER quote -> completion (successor `principal_cents` 136880 = 140000 - 5620 excess credit + 2500 fee, `rolled_over_balance_cents` 0, predecessor `ROLLED_OVER`/`UPGRADE_ROLLOVER`) -> EARLY_CANCELLATION quote -> amount-mismatch 422 -> cancellation `PAID_OFF`. Plus 401 unknown role, 403 cross-customer read, 404 unknown path. All assertions passed. `bash start.sh` booted clean twice and answered on `0.0.0.0:$PORT`.

PRD ambiguities resolved:
1. **`UPGRADE_ROLLOVER` quote with no live upgrade request** -> `ERR_UPGRADE_REQUEST_NOT_FOUND` (404). PRD §3.7 states the requirement but names no error; no other catalogue entry fits.
2. **POST /upgrade-requests body-reference order**: `target_device_model_id` resolves *before* `loan_id`, following the exact enumeration order of PRD §2.7 band 4.
3. **`ERR_DUPLICATE_MODEL_ON_CUSTOMER` excludes the addressed loan** (scaffold priority 93 says "no *other* ACTIVE loan on the same model"), so upgrading into the same model is admissible.
4. **Trade-in declaration's unstated handset-possession gate** -> `ERR_DEVICE_ALREADY_ACTIVATED` (the only handset-possession error declared), checked after `ERR_UPGRADE_REQUEST_NOT_AWAITING_TRADE_IN`.
5. **Completion's "trade-in GRADED and not disputed"** -> `ERR_TRADE_IN_INVALID_STATE`, placed in band 7 between `ERR_UPGRADE_REQUEST_NOT_COMPLETABLE` and `ERR_PAYOFF_QUOTE_NOT_ISSUED`.
6. **Successor loan** carries `credit_application_id = null` (no application exists) and `down_payment_cents = 0`; the additional down payment is recorded on the UpgradeRequest.
7. **Quote marked `CONSUMED` before** `close_as_rolled_over`, else the terminal-status supersession sweep would move it to `SUPERSEDED`.
8. **CarrierAccount at completion** resets to `PENDING`, `active_device_imei` re-pointed at `target_imei`, `activated_at` cleared. `activated_at` is stamped on any transition into `ACTIVATED`.
9. **No loan-`ACTIVE` precondition on unlock requests** — PRD band 7 lists loan-ACTIVE only for posting, pricing, cancelling, upgrade creation and completion.
10. **`ERR_NOTHING_TO_ALLOCATE` (band 10) precedes `ERR_INVALID_POSTING_AMOUNT` (band 11)**, so amount 0 on a fully-paid loan yields NOTHING_TO_ALLOCATE.
11. **`reverses_posting_id`** is required (400) when `posting_type == REVERSAL`, forced to null otherwise.
12. **`/_clock/set_current_utc`**: missing/non-string `to_iso8601` -> `ERR_INVALID_REQUEST`; present-but-unparseable or backwards -> `ERR_CLOCK_NOT_MONOTONIC`; equal to the current reading is accepted (forward-only, not strictly increasing).
13. **List endpoints are not ownership-filtered** — PRD §2.1's ownership screen enumerates single-resource reads and writes only. `GET /device-units` supports all five filters and `GET /loans` supports `delinquency_state` (PRD §3 prose, beyond what the §4 descriptions name).
14. Carried forward: no `FULL_PAYOFF` enum (any non-`UPGRADE_ROLLOVER` quote at completion is a type mismatch); sweep bumps loan `version` only for changed loans; diagnostic-failure lock voids applications but does not expire upgrade requests; body FK UUID malformedness -> 400 while path segments -> 404; malformed `imei` -> `ERR_IMEI_ALREADY_REGISTERED`.

Orchestrator verification after Steps 5/6: `test_helpers/` (9 files) and `test_suite/` (9 files) are both at the task root; `find workspace -maxdepth 2` shows no stray `test_helpers`, `test_suite`, or `worklog.md` inside `workspace/`; `workspace/implementation/start.sh` is executable.

## Step 7: Run Tests and Iterate — 2026-09-05T03:55:00.000Z

Clean 8-round sweep achieved.

**Iterations run:** 2 (baseline sweep -> 5 fixes -> confirming sweep).

**Iteration 1 baseline:** all 8 rounds 127/132, with the *identical* 5 failures in every round — deterministic, no flakiness, no load artefacts, no reaping (durations and results were consistent across rounds).

**Tests deleted:** none. All 5 failures traced to test-artifact bugs (STEP 2), not to PRD silence and not to the implementation. No implementation change was needed.

**Fixes applied to `test_suite/`:**

- `test_suite/test_03_precedence_and_boundaries.py`
  - `test_origination_succeeds_at_exactly_the_conditional_down_payment` — `validate_success(create_loan(...))` omitted the expected status, so it demanded 200 from a resource-creating endpoint. PRD §4: "Endpoints that bring a new resource into existence answer with HTTP 201". Added `, 201`.
  - `test_twelfth_installment_closed_by_one_cent_meets_the_upgrade_threshold_exactly` — same omission on `create_upgrade_request`. Added `, 201`.
  - `test_rollover_exactly_on_the_carry_forward_ceiling_completes` — same omission on `complete_upgrade`; PRD §4 names completion explicitly: "completing an upgrade answers 201 because it mints a successor loan". Added `, 201`.
- `test_suite/test_05_entity_contracts.py`
  - `_originate_model_a_loan_with_down_payment` (fixture used by `test_loan_computed_money_fields_derive_from_model_and_down_payment`) asserted `application["status"] == "ORIGINATED"` against the *decision* response captured before origination ran, so it necessarily saw `APPROVED`. The rule is PRD-covered ("Origination closes by advancing the source application to `ORIGINATED`"), so the fixture now re-reads the application after the loan is booked rather than the assertion being weakened.

**Fixes applied to `test_helpers/`:**

- `test_helpers/assertions.py` — `assert_loan()` unconditionally required `credit_application_id` to be a UUID. PRD §3.9 mints the successor loan from the rollover quote, trade-in and target model and names no credit application for it (only §3.3 origination "records the `credit_application_id` it originated from"), so a successor loan legitimately carries null. Made the check null-tolerant. This was the sole cause of `test_successor_loan_fee_tier_reads_pre_fee_base_below_one_hundred_thousand` failing with a bare `AssertionError`.

**Fixes applied to `implementation/`:** none. The implementation was already PRD-faithful on all 132 assertions; every failure was in the test artifact.

**Final sweep evidence** (`workspace/implementation/results.$i.json`, all 8 rounds launched concurrently under `setsid nohup`, joined with `wait`, `--isolation per-test-server`):

| round | passed/total | failed | errors | duration |
|---|---|---|---|---|
| 1 | 132/132 | 0 | 0 | 254s |
| 2 | 132/132 | 0 | 0 | 254s |
| 3 | 132/132 | 0 | 0 | 254s |
| 4 | 132/132 | 0 | 0 | 254s |
| 5 | 132/132 | 0 | 0 | 254s |
| 6 | 132/132 | 0 | 0 | 254s |
| 7 | 132/132 | 0 | 0 | 254s |
| 8 | 132/132 | 0 | 0 | 254s |

`worklog.md` was not touched by the subagent. Its temporary debug server (port 18811, PID captured and killed by port) is shut down; no broad pattern kills were used.

Orchestrator independent verification: re-read all 8 `results.$i.json` (mtime 03:50) with `json.load` — every round reports `passed=132 total=132 failed=0 errors=0`. The clean sweep is real, not a subagent claim.

Step 8 skip-condition adjudication: Step 7 made 0 deletions and 0 `implementation/` fixes, but 4 `test_suite/` fixes and 1 `test_helpers/` fix, so the skip condition (which requires all four counts at zero) is NOT met and Step 8 runs. Note that with 0 implementation fixes, a byte-identical `PRD_FINALIZED.md` would be a legitimate Step 8 outcome — every Step 7 item was a pure test-artifact bug, and the PRD sentences the fixes cited (§4's 201-on-creation rule, §3.3's `credit_application_id` recording, §3.9's successor-loan minting) were already the authority the fixes were made *against*, i.e. the PRD was already correct at those sites.

## Step 8: Finalize PRD — 2026-09-05T03:57:27.845Z

PRD_FINALIZED.md is written. One edit total.

**Line counts:** PRD.md 432 lines -> PRD_FINALIZED.md 432 lines (0.0% line delta; +239 bytes, one sentence inserted mid-paragraph in §3.9).

**Changes:**
- §3.9 (Trade-In, Bench Grading, Disputes and the Successor Loan) — insert — the successor loan's `credit_application_id` is null, present in the payload, never copied forward from the predecessor — `implementation/routes/upgrades.py:258` (`credit_application_id=None`), `implementation/serialize.py:137` (field always serialized).

**Per-edit pre-edit search log:**
- (a) Subject: the `credit_application_id` field on a Loan, specifically its value on an upgrade-minted successor loan.
- (b) Paths enumerated (`grep -rn credit_application_id --include=*.py`, then read each): `services/loans.py:23,32` — the single `mint_loan` helper that writes the field; `routes/loans.py:66` — origination passes `application["id"]`; `routes/upgrades.py:258` — completion passes `None`; confirmed via `grep -rn mint_loan` that these are the *only* two mint sites in the codebase, so there is no third loan-creation path; `serialize.py:137` `LOAN_FIELDS` — field is unconditionally included by `_pick`, so it surfaces as JSON `null` rather than being omitted; `routes/loans.py:90` + the equality filter loop at `routes/loans.py:97-99` — a `credit_application_id` query filter is plain `==`, so a null-carrying successor simply never matches a UUID filter (no special-casing to describe); `PRD.md:113` — body-reference resolution for `credit_application_id` applies only to origination, not completion.
- (c) Wording adjustment: added "it is present in the loan payload like any other field" so the sentence cannot be read as "the field is absent from the successor's representation" (which would contradict `serialize.py`'s unconditional `LOAN_FIELDS` pick), and scoped the negative claim to "never copied forward from the predecessor" rather than any broader statement about how loans acquire the field, so §3.3's origination behavior stays intact.

**Items with no edit:**
- The three `validate_success(..., 201)` fixes (`test_03_precedence_and_boundaries.py`) — no PRD silence. §4 already states "Endpoints that bring a new resource into existence answer with HTTP 201" and names completion explicitly; impl returns 201 at `routes/loans.py:80` (origination), `routes/upgrades.py:121` (upgrade request), `routes/upgrades.py:295` (completion). Pure test-artifact omissions.
- The `_originate_model_a_loan_with_down_payment` fixture fix (`test_05_entity_contracts.py`) — no PRD silence. PRD §3.3 already says "Origination closes by advancing the source application to `ORIGINATED`", and impl does exactly that at `routes/loans.py:77`. The fixture was reading a stale pre-origination response; the PRD was already the correct authority.

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` shows exactly one changed line (line 326, the §3.9 completion-cascade paragraph), inserting the `credit_application_id`-is-null sentence. Not byte-identical, and the single edit is properly scoped — consistent with Step 7 having made zero implementation fixes.

## Step 9: Complete PRD — 2026-09-05T04:24:00.000Z

Run as **three sequential file-partitioned passes** over one shared `PRD_COMPLETED.md` (pass 1 owned the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden to copy, and each verified the prior passes' edits survived). Partition was by implementation module, not by PRD section, so no two passes contended for the same PRD prose.

Final size: **432 lines, 134,136 bytes** vs `PRD_FINALIZED.md`'s 432 lines / 111,527 bytes — **+22,609 bytes, 0 lines** (every edit strictly in-paragraph; no new sections). 38 changed lines, 41 total edits: **30 ambiguity-pins, 11 mismatch-revisions**.

### Pass 1 — core + intake (`app.py`, `constants.py`, `errors.py`, `clock.py`, `db.py`, `response.py`, `middleware.py`, `validate.py`, `calc.py`, `serialize.py`, `lookups.py`, `routes/customers.py`, `routes/catalog.py`, `routes/applications.py`)
432 -> 432 lines, 111,527 -> 115,341 chars (+3,814). 8 ambiguity-pins, 2 mismatch-revisions.
- §2.2 — revise — ambiguity — `api_request_id` pinned as `req_` + exactly 20 uppercase-letter/digit characters, freshly generated per response including errors — `response.py:15-26`
- §2.3 — revise — ambiguity — `created_at`-ascending ordering now pins the tie-break (creation order, first-written first), which matters because the frozen logical clock makes identical `created_at` the norm — `db.py:66-68`
- §2.4 — revise — ambiguity — `updated_at` equals `created_at` at mint; `version` advances by exactly 1 per operation no matter how many writes that one operation makes to the row — `db.py:41-63`
- §2.7 band 2 — insert — ambiguity — ownership derived by resolving a resource that does not exist falls through to the 404 band, while a `Customer` path segment is compared to `X-User-ID` before existence (403 even for an unknown id) — `middleware.py:28-39`, `routes/applications.py:88-90`, `routes/customers.py:47`
- §2.7 band 3 — insert — ambiguity — empty/whitespace-only required strings violate the band; explicit JSON `null` treated as omitted; JSON booleans are not integers; ISO 8601 accepted with `Z`/offset/none and normalised to UTC; non-JSON or non-object bodies fail, absent/empty body reads as `{}` — `validate.py:17-33,53-60,123-128`
- §2.9 — insert — ambiguity — filter semantics (enum outside the enum → `ERR_INVALID_REQUEST`; boolean must be `true`/`false` case-insensitively; integer must parse; identifier filters literal → empty page, not 404) and that flat-collection lists are never implicitly narrowed to the acting `Customer` — `validate.py:165-190`, `routes/applications.py:66-82`, `routes/catalog.py:50-63`
- §2.10 — revise — **mismatch** — customer `status` enum was documented as `ACTIVE`/`FINANCING_LOCKED`/`CLOSED`; impl has only the two, `CLOSED` exists nowhere — `constants.py:50-51`
- §3.1 — revise — ambiguity — `email` uniqueness is exact case-sensitive string comparison; `mobile_number` required non-empty with no format constraint — `routes/customers.py:25-29`
- §3.1 — revise — ambiguity — `generation_year` is a required integer with no range constraint and no clock relation — `routes/catalog.py:31`
- §5 intro — insert — **mismatch** — table implied `ERR_INVALID_REQUEST` is always 400; impl also emits it at 404 for unrouted paths and 405 for undefined methods, and authentication is still evaluated first (401 wins over an unknown path) — `app.py:30-51`

Pass 1 handoff: `calc.py` (all §3.2/3.3/3.6/3.7/3.8/3.9 arithmetic) matched the PRD exactly — no edits needed. `errors.py` is byte-for-byte consistent with the §5 table (52 ids, identical statuses), verified programmatically. Open item forwarded: `DEFAULT_TERM_MONTHS = 24` (`constants.py:88`) is dead code while §3.3 claims a 24-month default.

### Pass 2 — servicing + money (`routes/loans.py`, `routes/postings.py`, `routes/devices.py`, `routes/servicing.py`, `services/loans.py`, `services/payments.py`, `services/servicing.py`)
115,341 -> 126,076 chars (+10,735), 432 lines unchanged. 11 ambiguity-pins, 3 mismatch-revisions. Confirmed no `cp`; pass 1's 10 lines (48, 80, 86, 111, 112, 138, 146, 154, 158, 377) verbatim intact with zero overlap.
- §3.3 — revise — **mismatch** — `DEFAULT_TERM_MONTHS = 24` is dead code; `requested_term_months` is a required application field always already 12 or 24, so no default term is ever applied — `routes/applications.py:34`, `routes/loans.py:72`
- §3.3 — insert — ambiguity — origination's `down_payment_cents` is not reconciled against `declared_down_payment_cents` and is not capped at `retail_price_cents`; a collection above the price is accepted and yields a **negative** `principal_cents` and negative schedule components — `routes/loans.py:40,56`
- §3.3 — insert — ambiguity — the customer's two "recomputed" figures are read-time derived; what origination writes is `updated_at` + `version` +1 on the application and customer rows, and `decision_reason`/`decided_at` are untouched — `routes/loans.py:77-79`
- §3.4 — insert — ambiguity — activation also stamps the carrier account's own `activated_at` and advances the account's `version` by 1 — `routes/devices.py:91-92`
- §3.4 — revise — **mismatch** — there is no "carrier acknowledgement window" between the two unlock steps; the second call is admissible at the same logical instant and re-evaluates the identical four gates; `active_device_imei` is not cleared on `PORT_ELIGIBLE` — `routes/devices.py:121-131`
- §3.5 — revise — **mismatch** — a caller *may* name `posting_type` `PAYOFF` on `POST /loans/{id}/payments`; it behaves exactly as a `PAYMENT` (same waterfall, same `ERR_NOTHING_TO_ALLOCATE` gate, reversible) and closes nothing — `routes/loans.py:169,190-193`, `services/payments.py:166-169`
- §3.5 — insert — ambiguity — amount rules are fiscal-band (last); negative `amount_cents` → `ERR_INVALID_REQUEST` 400, exactly zero → `ERR_INVALID_POSTING_AMOUNT` 422. `reverses_posting_id` on a `PAYMENT`/`PAYOFF` is resolved and cross-checked, then discarded, and the stored row records null — `routes/loans.py:170-174,191,195`
- §3.5 — insert — ambiguity — the single status re-derivation rule that governs both paths, incl. the case the enumeration misses: a reversal removing only a late-fee credit still retreats `PAID → PARTIALLY_PAID` — `services/payments.py:13-31`
- §3.5 — insert — ambiguity — a non-curing `PAYMENT`/`PAYOFF` refreshes `days_past_due` but leaves `delinquency_state` untouched and appends no event — `services/servicing.py:74-84`
- §3.5 — insert — ambiguity — the reversal label recompute is fully general (any label in either direction, any of the four authorized roles), not `DEFAULT`-only nor restricted to `CollectionsOfficer`/`ProgramAdmin` — `services/servicing.py:87-94`
- §3.6 — insert — ambiguity — `expired_upgrade_request_count`/`expired_quote_count` are portfolio-wide before/after diffs, so the former also counts default-cascade expiries with reason `CUSTOMER_FINANCING_LOCKED` — `services/servicing.py:100-101,170-175`
- §3.6 — insert — ambiguity — the sweep's version advance is exactly 1 per loan per run regardless of how many fields moved, and `upgrade_hold_flag` cleared by stale-paper expiry refreshes `updated_at` without advancing `version` — `services/servicing.py:145,152,161`
- §3.7 — insert — ambiguity — an `UPGRADE_ROLLOVER` quote on a loan with no live request is refused `ERR_UPGRADE_REQUEST_NOT_FOUND` (404), evaluated after the loan-`ACTIVE` check — `routes/loans.py:215-221`
- §3.7 — insert — ambiguity — the cancellation `PAYOFF` posting's exact figures (pre-closure late fee / pre-closure unpaid principal / zero premium / zero count / zero overpayment, `allocated_*` need not sum to `amount_cents`); `paid_premium_cents` left in place so a cancelled loan settles with a **non-zero** `obligation_balance_cents`; voided installments keep their figures; auto-unlock covers `UNLOCK_REQUESTED` and the carrier move is conditional on `ACTIVATED` — `services/loans.py:99-131`, `routes/loans.py:264-266`, `services/cascades.py:70-77`

Pass 2 notes: every endpoint in its partition follows the §2.7 ladder exactly, including internal orderings within bands 7, 9, 10, 11. §3.4/§3.5 prose lists checks in a different order than §2.7, but §2.7 is explicit that it governs, so the prose was left alone rather than reordered. `calc.py` arithmetic re-verified by live probe — matched.

### Pass 3 — upgrades + trade-ins + cascades (`routes/upgrades.py`, `routes/tradeins.py`, `services/upgrades.py`, `services/cascades.py`)
126,076 -> 134,136 bytes (+8,060), 432 lines unchanged. 11 ambiguity-pins, 6 mismatch-revisions. Confirmed no `cp` over the shared file (a `/tmp` backup of the pass-2 state was taken for its own diff check); 15 changed lines (104, 146, 204, 242, 280, 284, 286, 290, 296, 308, 314, 316, 318, 324, 326), none touching a line passes 1/2 had edited.
- §3.4 — revise — **mismatch** — auto-unlock on closure also moves `UNLOCK_REQUESTED`, not just `LOCKED`; carrier `PORT_ELIGIBLE` move conditional on `ACTIVATED`; an already-`UNLOCKED` handset is not written at all — `cascades.py:64-78` *(cross-partition handoff item 1 from pass 2)*
- §2.6 — revise — **mismatch** — "six operations, each by exactly 1" is false for a superseding creation: it clears then re-sets `upgrade_hold_flag`, advancing the loan `version` by 2 — `routes/upgrades.py:94-120` + `cascades.py:122-130`
- §2.10 — insert — ambiguity — locking an already-`FINANCING_LOCKED` customer is a total no-op: reason not overwritten, `financing_locked_at` not re-stamped, row not written, cascades don't re-run — `cascades.py:172-184`
- §3.8 — insert — ambiguity — `reserved_slot_count` is derived on read, so the model row only gets `updated_at` + `version` +1 — `serialize.py:51-54`
- §3.8 — insert — ambiguity — funding projection is computed at creation too (opens with the full rollover payoff, possibly `REQUIRES_DOWN_PAYMENT`), rests on a hypothetically-priced quote, and is not refreshed at completion — `services/upgrades.py:35-46`, `routes/upgrades.py:117`
- §3.8 — insert — ambiguity — supersession's two writes advance the loan `version` by 2 — `cascades.py:143-148`
- §3.9 — insert — ambiguity — declaration's `WITH_CUSTOMER` possession gate is refused with `ERR_DEVICE_ALREADY_ACTIVATED` (409) — `routes/upgrades.py:168-169`
- §3.9 — revise — **mismatch** — receipt does **not** re-check the owning request's `TRADE_IN_DECLARED` status; no such refusal exists — `routes/tradeins.py:87-94`
- §3.9 — revise — **mismatch** — the whole FAIL cascade is gated on the handset standing in `RETURNED`, so a second consecutive failing regrade costs nothing; a `SUBPRIME` customer's limit is not rewritten and the row is not written; the diagnostic lock **does** void credit applications but does **not** expire live upgrade requests — `services/upgrades.py:88-116`
- §3.9 — insert — ambiguity — the compensating regrade does not un-void `VOIDED_BY_LOCK` applications, lifts only a lock that grading itself applied, and always writes the customer row — `services/upgrades.py:119-128`
- §3.9 — insert — ambiguity — cancellation clears `returned_at`, accepts `RETURN_FAILED`, zeroes only `credit_final_cents` (leaving `credit_variance_cents`/`dispute_*` intact), and never undoes the band downgrade or the lock — `cascades.py:104-117`
- §3.9 — revise — **mismatch** — `FULL_PAYOFF` is not a `quote_type` (only `EARLY_CANCELLATION`/`UPGRADE_ROLLOVER`); completion's trade-in gate is `ERR_TRADE_IN_INVALID_STATE` — `constants.py:215-217`, `routes/upgrades.py:220-222`
- §3.9 — insert — ambiguity — a `ROLLED_OVER` closure writes no posting, does **not** zero `outstanding_late_fee_cents`, leaves `paid_premium_cents`/`delinquency_state`/`days_past_due`/`paid_installment_count` alone (non-zero `obligation_balance_cents`), and supersedes other `ISSUED` quotes — `services/loans.py:134-143` *(cross-partition handoff item 2 from pass 2)*
- §3.9 — revise — **mismatch** — carrier re-point fires only from `ACTIVATED`/`PORT_ELIGIBLE` (a `PENDING` account is untouched, keeping its old `active_device_imei`); `activated_at` cleared; account written twice → `version` +2, and the predecessor handset likewise when grading had left it `RETURN_FAILED` — `routes/upgrades.py:271-277`
- §3.9 — insert — ambiguity — successor handset opens `UNACTIVATED`/`LOCKED`/`WITH_CUSTOMER` with null timestamps; successor `down_payment_cents` is 0 regardless of `additional_down_payment_cents`; `upgrade_window_opens_at` restarts at +330 days — `services/loans.py:23-87`, `routes/upgrades.py:256-269`
- §3.9 — insert — ambiguity — the four customer aggregates are derived on read (`completed_upgrade_count` = requests in `COMPLETED`, `last_upgrade_completed_at` = latest `completed_at`), so the row only gets `updated_at` + `version` +1 — `serialize.py:88-101`
- §3.6 — insert — ambiguity — when the borrower is already `FINANCING_LOCKED`, only the strike lands: no reason/timestamp rewrite, no `FINANCING_LOCK_APPLIED` event, and effects 2-5 don't re-run — `cascades.py:213-227`

Pass 3 deliberately left §2.7's screening ladder alone: it already pins the full evaluation order for all six of its endpoints, verified band-by-band, including body-reference resolution order (`target_device_model_id` before `loan_id`), the capacity-before-threshold interaction, and `ERR_IMEI_ALREADY_REGISTERED` covering uniqueness **and shape** (so a 14-digit `target_imei` → 409 was already pinned). §2.7 band 9 already excludes dispute/regrade from the fulfillment-window gate, matching impl.

### Orchestrator final verification

- `cmp PRD_FINALIZED.md PRD_COMPLETED.md` → **differs** (38 changed lines). Not byte-identical, so the scan genuinely ran.
- Structure: 5 top-level `## ` sections, 10 `### 2.x` subsections, 9 `### 3.x` subsections; §4 table 40 data rows, §5 table 52 data rows; file terminates on the complete final row `| ERR_ROLLOVER_SHORTFALL_EXCEEDS_LIMIT | 422 |`.
- `find test_suite test_helpers workspace/implementation -name "*.py" -newer workspace/implementation/results.1.json` → **empty**: no test or implementation source changed after the green sweep, so the verified 8×132/132 result still describes the shipped artifact. Step 9 edited documentation only.
- No stray `worklog.md` outside the task root, no `.bak` files, `workspace/` holds exactly `INSTRUCTION.md`, `PRD.md`, `PRD_FINALIZED.md`, `PRD_COMPLETED.md`, `implementation/`, `sweep.log`.

**Pipeline complete.** `workspace/PRD_COMPLETED.md` written.
