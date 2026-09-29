# Worklog — task_2776_child_support_establishment_enforcement

## Step 1: Create task directory — 2026-09-04T20:11:51.395Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2776_child_support_establishment_enforcement` and `.../workspace` (pre-assigned path from orchestration args; no index scan performed).

## Step 2: Generate scaffold — 2026-09-04T23:11:00.000Z

Done. All three scaffold artifacts are complete and the linter is clean.

## Deliverables
`/home/ubuntu/github/CodingPRD/tasks/task_2776_child_support_establishment_enforcement/`
- `SCAFFOLD.yaml` — 4,218 lines (§1.0–§1.7 only; neither design key present)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2,477 lines (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 6,192 lines (single key `scaffold_corner_design`)

## SCAFFOLD.yaml counts
12 entities (flat topology) · 72 endpoints · 10 calculations · 67 validation rules across 48 distinct priority levels · 67 error ids over six HTTP statuses · 12 state-machine dimensions on 9 entities / 83 transitions · 8 roles · 2 OCC rules (`iwo-issue-stale-order`, `compromise-create-stale-case`).
`complexity_profile`: `compliance_audit` + `ledger_reconciliation`; layers `dual_variant_calculation`, `cascading_side_effects`, `rate_threshold_triggers`, `optimistic_concurrency`; `state_machine_shape: parallel`; `role_model: segregation_of_duties`; `consistency_model: immediate`.

## Design indexes
- §1.8 `scaffold_difficulty_design`: **9 rules, 21 instances** (dual_variant 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_conflict 2, boundary_precision 3, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2).
- §1.9 `scaffold_corner_design`: all **nine** sections, **69 entries = 57 instances + 12 stubs** — entities 12, state_machines 18 (12+6 stubs), calculations 12 (9+3), validations 12 (11+1), endpoints 5, errors 2, rbac 3, cross_cutting_complexity_layers 4 (2+2), consistency_model 1.
- Every stub carries `excluded_because` (no `test_recipe`) and cites a real §1.8 instance name; all 69 names are unique across the union of both files.

## Verification
- `scaffold_lint.py`: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (72 endpoints, 12 entities, §1.8 21 / §1.9 57 instances, **1,458 calls scanned**).
- **Error coverage: 67/67 error ids appear in the two design files, 0 uncovered.** The four sections written last were built to close the final six: `ERR_MISSING_AUTH_HEADERS`, `ERR_INVALID_ROLE`, `ERR_UNAUTHORIZED`, `ERR_NOT_CASE_PARTY`, `ERR_NOT_IWO_EMPLOYER`, `ERR_STALE_ORDER_VERSION`.
- All formula-derived asserts were pre-computed with a reference calculator (`/tmp/t2776/ref.py`) — e.g. the OCC instance's compromise offer (principal 224000 → monthly 74666 / final 74668, risk 46/MEDIUM) and the threshold instance's cap flip (arrears 225000 → 0.65/91000/wh 90000 vs 224999 → 0.60/84000/wh 84000).

## Corrections made along the way
- **Difficulty-directive line excluded from `scenario:`** per the auto-memory note; the "harder than expert level" instruction is captured only as `complexity_profile.difficulty_level: expert_plus`, so it cannot leak into PRD.md.
- Three earlier `SCAFFOLD.yaml` reachability repairs remain in force (priority-10 carve-outs making `ERR_RESCISSION_WINDOW_CLOSED` and `ERR_OFFER_SUPERSEDED` reachable; `COURT_ADJUDICATION` removed from `PaternityAction.method`).
- Format fixes: hyphenated FEINs (`^[0-9]{2}-[0-9]{7}$`), `remittance_fee_cents` held inside 0..500.
- The ledger endpoint declares `output: null`, so its instances use no `captures:` — its figures are asserted with the `trigger[n] HTTP 200 body: data.<field> == …` prose convention (0-indexed), consistent across both design files.
- **New this pass:** an audit found 7 charge payloads (5 in the corner file, 2 in the difficulty file) violating `period_start_date <= due_date < period_end_date`; all were repaired by shifting the period to contain the existing `due_date` (the interest anchor), keeping every interest/threshold literal intact and avoiding same-type `ERR_CHARGE_PERIOD_OVERLAP`. Re-audit reports 0 violations.

Orchestrator verification: all three YAML files present and non-trivial; `grep` for "harder than expert"/"expert level" in SCAFFOLD.yaml returned nothing, so the difficulty directive cannot reach PRD.md.

## Step 3: Copy INSTRUCTION.md — 2026-09-04T23:12:49.465Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T23:32:00.000Z

PRD generation complete.

## Output
`workspace/PRD.md` — **509 lines, 16,956 words, 127,026 bytes**. Ends cleanly at the final row of the §5 Error Code Catalogue table; no audit footer, no truncation, no mid-sentence break. Written across ~10 chunked `cat >>` appends to stay clear of the 64k output cap.

## Section list
- `# Child Support Enforcement API — Product Requirements Document`
- **§1 Introduction** (3 paragraphs)
- **§2 Global Specifications & System-Wide Principles** (10 subsections): 2.1 Caseworkers, Parties and RBAC · 2.2 API Response Structure (verbatim fixed contract) · 2.3 Pagination, List Ordering and Filters · 2.4 Resource Identity, Audit Stamps and the Logical Clock · 2.5 Money, Precision and Rounding · 2.6 Optimistic Concurrency on Parent Orders and Cases · 2.7 Two Statutory Measures of Accrued Interest · 2.8 Parallel Status Dimensions and Cascade Discipline · 2.9 Order of Precedence Among Validations · 2.10 Jurisdictions, Assignment and Good-Cause Confidentiality
- **§3 Business Logic & Workflows** (9 subsections): 3.1 Intake/locate/risk model · 3.2 Parentage · 3.3 Guideline worksheet, deviation, order entry · 3.4 Income withholding and the multi-state ceiling · 3.5 Obligation ledger, accrual, allocation waterfall · 3.6 Enforcement remedies · 3.7 Interstate cases and controlling order · 3.8 Modification review · 3.9 Arrears compromise and case closure
- **§4 Endpoint Definitions** (prose + 72-row table)
- **§5 Error Code Catalogue** (67-row table)

## Coverage counts (all machine-verified against SCAFFOLD.yaml)
| Item | Scaffold | Documented |
|---|---|---|
| Entities | 12 | 12 |
| Distinct field / input / path-param names | 191 | **191 (0 missing)** |
| Endpoints | 72 | 72 (all in §4 table with roles) |
| Calculations | 10 (+4 variants) | 10 (+4 variants) |
| Validation rules | 67 | 67 (all error IDs in §2/§3 prose, full precedence ordering in §2.9) |
| Error codes | 67 | 67 |
| State machines / transitions | 12 / 83 | 12 / 83 |
| Distinct states | 54 | 54 |
| Enum values (entity constraints) | 130 | **130 (0 missing)** |
| Concurrency rules | 2 | 2 (§2.6, endpoint + OCC field + error + 412 + rationale) |
| Roles | 8 | 8 |
| Calculation constants (numeric) | all | all present as literals |

## Hard Contracts
- **Contract 1 — Field-Name Coverage: PASS.** 191/191 required identifiers appear verbatim in backticks.
- **Contract 2 — Rule Coverage: PASS.** All 67 validations mapped to error IDs with HTTP statuses and full precedence ordering incl. the three carve-outs (case-status vs `ERR_PATERNITY_NOT_ESTABLISHED`; rescission vs `ERR_RESCISSION_WINDOW_CLOSED`; acceptance vs `ERR_OFFER_SUPERSEDED`). All 83 transitions documented with preconditions and side effects, including the dual `OPEN → VOID` paths, the two-path `REGISTERED` entry, the `NOTICE_SENT → RELEASED` flag-less conditional cascade, and the 4-level exclusion / supersession cascades. Both OCC rules fully expressed. All 10 calculations given as reconstructible prose with every constant.
- **Contract 3 — §3 Path Purity: PASS.** 416 distinct backticked tokens in §3; **0** start with `/`, are a bare HTTP method, or combine method+path. Paths appear only in §4.

## Notes / judgement calls
- Fixed two internal inconsistencies while verifying: `ERR_GOOD_CAUSE_BARS_DISCLOSURE` was stated as HTTP 403 in §3.6 (scaffold says 409) and §2.4 said "eleven" path params where twelve are listed. Both corrected.
- Three constants (`0.06`, `0.22`, `0.05`) were originally only spelled out in words; numerals added so the implementer cannot mis-derive them.
- `RETROACTIVE_SUPPORT_LIMIT_DAYS` is referenced in `SupportOrder.effective_date`'s scaffold description but has **no value anywhere in the scaffold**. No number was invented; the PRD states only that `effective_date` may precede the clock date because retroactive support is permitted.
- `IncomeWithholdingOrder.arrears_recovery_cents` is gated on case arrears in the entity table but unconditional in the `withholding_amount` formula; documented as gated at IWO level and unconditional at order level (`arrears_recovery_monthly_cents`), which is the only reading that satisfies both statements.
- Neither design YAML was opened, grepped, or referenced, and no sibling task directory was read.

Orchestrator verification (truncation guard): `wc -l` = 509; `tail -25` ends on a complete `| ERR_OFFER_SNAPSHOT_STALE | 409 |` table row at a real section boundary (end of §5), not mid-sentence; six top-level headings present (§1–§5). Grep for "harder than expert", "expert_plus", "difficulty_level", "test_recipe", "scaffold" in PRD.md returned zero hits — no scaffold or difficulty-directive leakage. PRD accepted without regeneration.

## Step 5: Generate unit tests — 2026-09-05T02:04:00.000Z

The suite is complete. Final state:

## Files emitted (task root, never under `workspace/`)

`test_helpers/` — 9 files, 3,939 lines: `__init__.py` 271, `api_client.py` 514, `api_errors.py` 196, `assertions.py` 307, `constants.py` 396, `factories.py` 711, `fixtures.py` 1,037, `test_users.py` 162, `types.py` 345.

`test_suite/` — `conftest.py` 67 plus 20 test modules, 9,980 lines total: `test_01` 247, `test_02` 329, `test_03` 380, `test_04` 350, `test_05` 265, `test_06` 330, `test_07` 348, `test_08` 363, `test_09` 407, `test_10` 944, `test_11` 828, `test_12` 692, `test_13` 287, `test_14` 593, `test_15` 807, `test_16` 707, `test_17` 702, `test_18` 271, `test_19` 483, `test_20` 580.

## Test counts

**177 tests: queue A (Difficulty) 63, queue B (Corner) 114.** Coverage check confirms **every live design instance has ≥1 test**: 21/21 Difficulty rule-instances, 57/57 non-stub Corner instances, 0 uncovered, 0 unknown/dangling tags. `python3 -m py_compile` passes over all 30 emitted `.py` files; the tag/citation audit reports AUDIT CLEAN (exactly one trailing `Design:` line per test resolving to a real instance, every citation line a literal substring of `workspace/PRD.md`, no `scaffold`, no section signs).

## Instances skipped

**None.** No live design instance was dropped. The only untranslated entries are the 12 Corner instances the design itself marks `excluded_because` (stubs, no recipe): `case_status_posture_and_interstate_role_move_independently`, `iwo_service_status_and_remittance_status_move_independently`, `paternity_acknowledgment_cycle_returns_to_aop_signed`, `order_vacatur_cascades_down_to_charges_and_withholding_orders`, `compromise_default_reverses_the_interest_write_off`, `compromise_acceptance_releases_only_the_remedies_it_should`, `ncp_risk_score_weight_vectors`, `interest_two_variants_diverge`, `interest_variant_is_chosen_by_the_figure_being_reported`, `two_rules_fire_on_one_compromise_request`, `both_interest_variants_disagree_on_one_case`, `one_write_moves_four_entities`.

One sub-assertion was dropped rather than weakened: in Corner/state_machines instance 11 the design's "ENFORCING-return refusal" asserts an error the PRD never names, so that single refusal is absent while the rest of the instance is tested.

## Design-vs-PRD deviations (setup adapted, assertions never weakened)

The dominant class, recurring across ~10 instances: the design posts charges due `2026-08-15` while the clock is pinned to `2026-08-01`, but PRD line 158/164 defines `arrears_principal_cents` over charges "due on or before the current logical clock date", so those setups would leave arrears at 0 and contradict the design's own asserted arrears, snapshots, `arrears_recovery_cents` and cap figures. Fixed by moving due dates to `2026-08-01` (or, once, advancing the clock to `2026-10-01`).

Other recorded adaptations: queue A rule 1/inst 2 `withholding_amount_cents` 82500 not 99000; rule 3/inst 1 `controlling_order_state_code` "TX"; rule 4/inst 1 `terminated_date` 2026-08-20; rule 6/inst 2 and rule 9/inst 1 dropped `total_collected_principal_cents` / `col_pre`-`col_post` (the field has no derivation rule in the PRD — only one mention); rule 9/inst 2 `active_iwo_count` asserted absolutely only for the served employer. Corner: entity defaults `notary_verified`/`rescission_count`/`genetic_cost_cents` dropped; state_machines inst 4 withholding 75000 with `arrears_recovery_cents == 0`, inst 3 order entered before transmittal with clock at 2026-08-12, inst 7 closes with `NO_JURISDICTION`, inst 1 drops `genetic_cost_liable_party == "NONE"`; calculations charge listing asserted in `created_at` order; validations inst 8's PROPERTY_LIEN refusal asserted as `ERR_ARREARS_BELOW_ENFORCEMENT_THRESHOLD`, inst 9's citation replaced (contained a section sign); endpoints test_06 service citation swapped to PRD line 248. In the final batch: the twelve-week-bump instance's three monthly charges were replaced by a `CURRENT_SUPPORT` 75000 + `ARREARS_JUDGMENT` 150000/149999 pair due on the clock date (225000 vs 224999 preserved exactly), and its post-service "one more cent of arrears" was posted as a 1-cent `MEDICAL_SUPPORT` charge because `ARREARS_JUDGMENT` for that month would trip `ERR_CHARGE_PERIOD_OVERLAP`; all asserted cap percentages (0.65/0.60), cap amounts (91000/84000) and withheld figures (90000/84000, 6000 apart) are unchanged.

## Step 6: Generate implementation — 2026-09-05T02:04:00.000Z

Implementation complete. All 72 endpoints are live and the whole thing boots and works end to end.

## Modules emitted (`workspace/implementation/`, 4,323 lines of Python)

Foundation: `app.py` 65, `util.py` 154, `errors.py` 155, `db.py` 148, `response.py` 83, `middleware.py` 80, `validate.py` 164, `serialize.py` 328, `common.py` 139
Services: `interest.py` 88, `risk.py` 127, `guideline.py` 75, `withholding.py` 114, `ledger.py` 132, `cascade.py` 192, `payments.py` 75, `controlling.py` 43
Routes: `clock.py` 36, `participants.py` 120, `cases.py` 216, `paternity.py` 253, `orders.py` 281, `employers.py` 68, `iwo.py` 199, `charges.py` 177, `reviews.py` 218, `enforcement.py` 230, `interstate.py` 177, `compromise.py` 186
Plus `start.sh` (executable, guarded `pip install`, `exec python3 app.py`) and `requirements.txt` (`Flask==3.0.3`).

## Verification
- **Endpoint coverage 72/72**, verified programmatically: the set of `(method, rule)` in `app.url_map` is exactly equal to the scaffold's 72 endpoints — zero missing, zero extra.
- `python3 -m py_compile` clean on all 29 `.py` files; `ls -la` + `wc -l` run on the tree.
- Three real smoke boots on explicit free ports (10877 / 10879 / 10881), each killed by its own recorded pid only — no broad `pkill`. Exercised: intake → presumed-marital paternity → guideline worksheet (125000 on 3M/5M/2 kids) → entry → charge posting (+ 409 overlap) → payment waterfall + distribution split → ledger read (both interest measures) → employer + IWO issuance (412 on stale `expected_order_version`) → service → remittance → clock set (`to_iso8601`) → accrual run (2,000,000 arrears for 5 months = 50,000 statutory, matching aggregate) → enforcement propose (certified 2,050,000 vs threshold 300,000) → notice → 409 premature activation → activation with participant flag flip (`license_suspension_active` true, licence cleared) → compromise offer maths (pre-waiver 151,500 → tier 0.25 → waiver 375 → settlement 151,125 → 25,187/25,190 split) → supersession + `ERR_OFFER_SUPERSEDED` → acceptance (STAYED, waiver written off, remedy released) → 422 short installment → 4 installments to COMPLETED → closure `ARREARS_SATISFIED` → 409 on any write to the closed case. Interstate transmittal → registration (controlling order MN) → return, and review screening, all correct.
- Storage is in-memory dicts only; nothing is seeded at import or boot (empty-list responses on a fresh boot confirm it). No file/SQLite/`/tmp` persistence. Never touched `test_helpers/`, `test_suite/`, `worklog.md`, or the two forbidden design YAMLs.

## PRD ambiguities resolved (choice made)
Withholding/ledger: `ccpa_cap_amount_cents` = **floor**(disposable × pct); `withholding_amount_cents` = max(0, min(requested, ccpa − remittance_fee)); `employer_fee_cents` = fee when withholding > 0 else 0 (all three follow PRD prose over the scaffold entity gloss); `arrears_recovery_cents` = 0 when no arrears principal; `interest_accrued_cents` and `active_iwo_count` are **stored/maintained** despite `source: computed`, because the PRD says the accrual run "writes" the former and that termination from `ISSUED` does not decrement the latter.

Charges/payments: `amount_cents` omitted on `ARREARS_JUDGMENT`/`GENETIC_TEST_COST` → `ERR_VALIDATION` (no default exists); voiding a non-OPEN charge → `ERR_CHARGE_PARTIALLY_PAID` when `paid_cents > 0`, else `ERR_INVALID_CASE_STATUS` (the catalogue has no charge-status error); zero `amount_cents` refused for every source, negative allowed only for `REVERSAL`; `COMPROMISE_INSTALLMENT` without an offer → `ERR_VALIDATION`, offer on another case → `ERR_REFERENCED_ENTITY_NOT_FOUND`.

Reviews: non-party `participant_id` → `ERR_PARTY_ROLE_MISMATCH`; `ERR_INFO_REQUEST_LIMIT` enforced on the information endpoint at `info_request_count > 2` (screening never raises it); the CEJ gate is checked **before** the effective-date gate on proposed-order, because §2.9 puts the referential band above the temporal one even though §3.8 narrates the date first; the successor order inherits `order_type`, `origin_state_code`, the medical amount and the predecessor's guideline inputs.

Enforcement: the `REGISTERED → ENFORCING` referral cascade fires **only** on the activation endpoint, not on an `UPHOLD` decision (PRD's "activation on the uncontested branch has one further reach" + the scaffold's side-effect lists, against the same section's "identical side effects" claim); the two-month delinquency floor is 0 when the case has no `ENTERED CURRENT_SUPPORT` order; good-cause is checked before `ERR_ENFORCEMENT_STAYED` on notice, and the contest window before it on activation (band order).

Interstate: every unspecified precondition failure (nothing `ENTERED` to transmit, a late acknowledgment registration, a `returned_reason` disallowed for the from-state, a premature `NO_ACK_RECEIVED`, a return from `DRAFT`) answers `ERR_INVALID_REFERRAL_STATUS`; the return clears `controlling_order_*` only from `REGISTERED`, literally as written, not from `ENFORCING`.

Compromise: `interest_due_snapshot_cents` is the **gross** aggregate month-end total (§2.7 names the measure, not the net receivable); the four gates run in §2.9 band order (active offer → assigned arrears → risk tier → arrears minimum) rather than §3.9's narrative order; acceptance sets `STAYED` *after* the cascade releases so posture settlement cannot undo it.

Carried over from earlier modules: `origin_state_code` optional defaulting to MN; `ERR_DUPLICATE_PATERNITY_ACTION` checked after the closed-case guard but above the general case-status check; order drafting requires NCP `LOCATED` (or merely not `UNLOCATABLE` on a good-cause case); interval-overlap on entry excludes the modification predecessor; timestamps come from the logical clock with a hidden `_seq` tiebreak; the CEJ gate closes on any `REGISTERED`/`ENFORCING` referral naming a non-MN controlling state.

Orchestrator verification: Steps 5 and 6 were launched concurrently in a single message, so the impl generator had physical isolation from `test_suite/` (the directory did not exist at its spawn). Confirmed on disk: `test_helpers/` (9 .py) and `test_suite/` (21 .py, 177 `def test_` functions) live at the TASK ROOT; no stray `workspace/test_helpers` or `workspace/test_suite`; `workspace/implementation/` contains `start.sh`, `requirements.txt`, foundation modules plus `routes/` and `services/` packages.

## Step 7: Run tests and iterate — 2026-09-05T02:27:00.000Z

Clean sweep confirmed: 8/8 parallel rounds at 177/177, zero union failures. No stray test dirs under `workspace/`, and `worklog.md` untouched.

## Summary

**Iterations run:** 2 (iteration 1: 159/177 in all 8 rounds; iteration 2: 177/177 in all 8 rounds).

Failures were fully deterministic — the identical 18 tests failed in all 8 rounds, so there was no flakiness to chase. 15 of the 18 shared one setup error (`ERR_INVALID_CASE_STATUS`), which per the triage hint pointed at a single upstream cause rather than 15 independent defects.

**Tests deleted:** none. No test failed the STEP 1 coverage or unique-derivability checks outright.

**Fixes applied to `implementation/`:**
- `workspace/implementation/routes/paternity.py`, `create_paternity_action` — the case-status band rejected an `OPENED` case without `good_cause_claim` for the `VOLUNTARY_ACKNOWLEDGMENT`/`GENETIC_TEST` tracks, so `ERR_INVALID_CASE_STATUS` (state band) pre-empted the locate gate. PRD §3.2 assigns that refusal to the locate check verbatim — "Outside that bypass, an obligor who is not `LOCATED` blocks both the opening of a paternity action and the drafting of a support order with `ERR_NCP_NOT_LOCATED`" — and §2.9's first refinement states the same pattern explicitly for the sibling operation ("when a support order is drafted on a case, the case-status check rejects only a `CLOSED` case; the requirement … is owned by the paternity-settlement check"). `require_located` in `routes/orders.py` already followed that pattern, making the paternity gate the lone outlier. Now only states from which `PATERNITY_PENDING` is unreachable are rejected on status grounds; the locate gate owns the rest. This fixed 16 tests (the 15 setup errors plus `test_15::test_10`, which asserts `ERR_NCP_NOT_LOCATED` on exactly this request).

**Fixes applied to `test_suite/`:**
- `test_15_validation_gates.py::test_09_good_cause_bars_the_two_disclosures_and_waives_the_locate_step` — STEP 2 test bug. The asserted rule (§2.10: transmitting an interstate request is refused with `ERR_GOOD_CAUSE_BARS_DISCLOSURE`) is PRD-verbatim, but the setup transmitted on a case with **no `ENTERED` support order**, violating another declared transmittal precondition ("that the case has at least one `ENTERED` support order to transmit"). The PRD assigns no error id to that precondition, so its band is reader-dependent and it could legitimately answer first. Setup now reads the good-cause refusal on a good-cause case that already carries an entered order, leaving confidentiality as the only failing precondition — a strictly more PRD-faithful precondition, with the assertion untouched.
- `test_17_endpoint_surface.py::test_09_a_located_obligor_opens_paternity_and_shuts_the_closure_door` — STEP 1c partial-coverage split: dropped the single assertion `unlocatable.get("employer_name") is None`. DEFAULT-VALUE SILENCE: PRD §3.1 says only that a locate result comes with "optionally attaching the `employer_name` the locate turned up", and never states what an omitted `employer_name` does to the previously stored value — a faithful reader may leave it intact or null it. All the test's other assertions (the `locate_status` outcomes, the `LOCATE → CLOSED` refusal for a located obligor, `ERR_NCP_NOT_LOCATED` for an unlocatable one) are PRD-verbatim and were kept.

**Fixes applied to `test_helpers/`:** none — the shared fixtures turned out to be PRD-faithful; the `OPENED`-case precondition they build is legitimate, and the implementation was the over-strict party.

Orchestrator verification (independent of the subagent's claim): all eight `workspace/implementation/results.{1..8}.json` exist on disk, written 2026-09-05T02:27, each ~54.5 KB, and each parses to `passed=177 / total=177 / failed=0`. Step 7 accepted. Because Step 7 applied one `implementation/` fix and two `test_suite/` fixes, the Step 8 skip condition does not hold — Step 8 runs.

## Step 8: Finalize PRD — 2026-09-05T02:35:00.000Z

PRD_FINALIZED.md is written: 3 lines revised, no lines added or removed.

**Line counts:** PRD.md 509 / PRD_FINALIZED.md 509 (0.0% line delta; 3 of 509 lines revised in place, ~0.6% of lines touched). File still ends at a real boundary — the closing rows of the §5 error-code table (`ERR_OFFER_SNAPSHOT_STALE | 409`).

**Changes**

- §3.2 (Settling the Question of Parentage), line 178 — revise — pinned the case-status band for opening a paternity action: the acknowledgment and genetic tracks accept a case in `OPENED` or `LOCATE`, the `LOCATED` requirement is owned by the locate check (so a non-good-cause `OPENED` case with an unlocated obligor answers `ERR_NCP_NOT_LOCATED`, never `ERR_INVALID_CASE_STATUS`), and `PRESUMED_MARITAL` accepts only `OPENED` — `implementation/routes/paternity.py:54-71`.
- §3.7 (interstate transmittal), line 308 — revise — pinned that the `INITIATING`-direction and "at least one `ENTERED` order" preconditions live in the referral-status band and fail with `ERR_INVALID_REFERRAL_STATUS` above the confidentiality check, so `ERR_GOOD_CAUSE_BARS_DISCLOSURE` surfaces only once an entered order exists — `implementation/routes/interstate.py:98-103`.
- §3.1 (locate result), line 162 — revise — pinned that an attached `employer_name` overwrites, while an omitted/null one leaves the stored value unchanged — `implementation/routes/participants.py:115-118`.

**Per-edit pre-edit search log**

1. Edit 1 — (a) Subject: the case-status precondition on `POST /cases/{id}/paternity-actions` and its precedence against the locate gate. (b) Enumerated/read: `routes/paternity.py` (all seven paternity endpoints — `create_paternity_action` status band 54-63 and locate gate 65-71; the five sub-operations, which use only `case_writable` + action-status), `common.case_writable` (CLOSED → `ERR_INVALID_CASE_STATUS`), `routes/orders.py:42-48,114-118` (`require_located` / `require_paternity` — the sibling pattern §2.9 refinement 1 describes), `routes/cases.py:95-150` (locate referral's `OPENED`/`LOCATE` band, closure's status band), grep of every `locate_status` / `ERR_NCP_NOT_LOCATED` site, PRD §2.2 case-status enum (line 124). (c) Adjustment: dropped my first draft's universal clause "and rejects any other `case_status` with `ERR_INVALID_CASE_STATUS`". `create_paternity_action` runs the duplicate-action check (`ERR_DUPLICATE_PATERNITY_ACTION`, paternity.py:51-52) *before* the status band, so on a `PATERNITY_PENDING`/`ORDER_ESTABLISHMENT`/`ENFORCEMENT` case — which by construction already has an action — the duplicate error wins, contradicting the universal claim. Reworded to state only the accepted origins, leaving the rejection error to §2.9's general rule.
2. Edit 2 — (a) Subject: the transmittal preconditions and which band answers when both the entered-order and good-cause preconditions fail. (b) Enumerated/read: `routes/interstate.py` in full (`transmit` 93-112, `register_referral`'s DRAFT foreign-order branch 121-132 which also yields `ERR_INVALID_REFERRAL_STATUS`, `return_referral` 145-177, `_entered_orders` 24-25), plus the two sibling good-cause disclosure sites for pattern consistency: `routes/cases.py:101-105` (status band then good-cause) and `routes/enforcement.py:143-146` (action-status band then good-cause); PRD lines 150, 306-320. (c) Adjustment: scoped the sentence to the transmittal operation only ("The first two of those preconditions…") rather than making a general statement about the good-cause band, so registration's own entered-order requirement and the other two disclosing operations are untouched by the wording.
3. Edit 3 — (a) Subject: the write semantics of `employer_name` when a payload omits it. (b) Enumerated/grepped: every `employer_name` site in the impl — `routes/participants.py:45,57` (create: absent → stored absent), `:101-105` (income update: `if employer_name is not None` → same merge semantics), `:109-120` (locate result, the Step 7 site), `serialize.py:35`; plus `validate.opt_str`/`validate.present` (`validate.py:24-49`), which treat an explicit JSON null as absent. (c) Adjustment: added "or sends it as null" because `present()` collapses null into absent, and added "including leaving it absent when nothing was stored" so the sentence stays true for a participant registered without an employer; kept the sentence scoped to the locate result even though the income-update merge is identical, to avoid a cross-endpoint universal not in scope.

Orchestrator verification: `wc -l` 509/509, `cmp` reports the files differ, and `diff` shows exactly three changed lines (162, 178, 308) — each an in-paragraph revision, no new sections, ending boundary intact.

## Step 9: Complete PRD — 2026-09-05T03:02:00.000Z

Run as THREE SEQUENTIAL module-partitioned passes over one shared `PRD_COMPLETED.md` (pass 1 did the `cp`; passes 2 and 3 were explicitly forbidden to copy, so no pass clobbered an earlier one). Partition: pass 1 = foundation modules + all of `services/`; pass 2 = `routes/clock,participants,cases,paternity,orders,employers`; pass 3 = `routes/iwo,charges,reviews,enforcement,interstate,compromise`. Each pass received the previous passes' hand-down notes so they neither re-pinned settled prose nor undid each other.

**Cumulative result:** PRD_FINALIZED.md 509 lines / 128,177 chars → PRD_COMPLETED.md 510 lines / 152,514 chars (**+1 line / +24,337 chars**, 55 lines revised in place). **61 changes total: 48 ambiguity-pins + 13 mismatch-revisions.** Headings byte-identical to PRD_FINALIZED.md; no new sections; document still ends at the §5 error-code table's final row.

### Pass 1 — foundation + services (17 pins, 3 mismatch-revisions)
- §2.1 — insert — ambiguity — whitespace-only auth header counts as absent; both header values trimmed; role match exact and case-sensitive — `middleware.py:28-34`
- §2.1 — insert — ambiguity — participant-read visibility for party callers: self, or any participant sharing a case where the caller holds its own party role; else `ERR_NOT_CASE_PARTY` — `middleware.py:61-74`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A`–`Z`/`0`–`9` — `util.py:18-20`
- §2.2 — insert — ambiguity — three transport-level error ids outside the §5 catalogue (`ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500); trailing slash not significant — `app.py:30-55,19`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` → `ERR_VALIDATION`; `offset` unbounded above; empty-string param = omitted — `response.py:57-75`
- §2.3 — insert — ambiguity — `created_at` ties broken by monotonic creation sequence, never by id — `db.py:74-76`
- §2.3 — insert — ambiguity — filters exact-match, empty value = omitted, unrecognised query params ignored; boolean filter accepts true/1/yes vs false/0/no any case, else `ERR_VALIDATION` — `common.py:111-138`
- §2.4 — insert — ambiguity — absent/malformed body read as empty object; non-object JSON body → `ERR_VALIDATION`; explicit `null` = omitted for optional, = missing for required — `validate.py:11-25`, `app.py:46-49`
- §2.7 — insert — ambiguity — exact "whole calendar months" rule: calendar-month difference reduced by one when the as-of day-of-month precedes the due day-of-month, floored at zero — `util.py:93-100`
- §2.9 — insert — ambiguity — types checked not coerced (integral floats accepted, booleans and numeric strings rejected, required strings non-empty); date fields keep leading 10 chars; instant fields accept offsets/`Z` normalised to UTC, bare date as midnight UTC — `validate.py:68-73`, `util.py:42-72`
- §3.1 — insert — ambiguity — payment-history component clamped into 0..100, so an overcollected case scores 0 — `risk.py:80-81`
- §3.3 — **revise — mismatch** — order-entry CEJ gate does not consult `interstate_role`; a foreign controlling order blocks entry on any case — `controlling.py:29-38`, `routes/orders.py:254`
- §3.4 — **revise — mismatch** — `active_iwo_count` is an incrementally maintained counter (+1 at service, −1 at termination of a served/amended row, floored at 0); an `ISSUED` row is not counted (`withholding.py:110 recount_active_iwos` is dead code) — `cascade.py:100-108`, `routes/iwo.py:112`
- §3.4 — insert — ambiguity — obligor with no income figure on file derives disposable income of zero — `withholding.py:29-34`
- §3.5 — insert — ambiguity — `total_collected_principal_cents` rises by buckets 1+2+3+5 (genetic-cost reimbursement counts as principal); interest and unapplied tracked only in their own counters — `ledger.py:124-132`
- §3.5 — insert — ambiguity — a negative `REVERSAL` runs the same six buckets; the whole negative goes to the first bucket with any candidate, falling through to negative `unapplied_credit_cents` only if none; `SATISFIED` charges never candidates — `ledger.py:49-61`
- §3.6 — **revise — mismatch** — caller-requested case closure releases no remedy (the paternity-exclusion cascade does); the `NOTICE_SENT` release writes only the action's row, moving no participant `version` — `cascade.py:76-82,148-155`
- §3.7 — insert — ambiguity — an empty candidate set leaves `controlling_order_id`/`controlling_order_state_code` absent and registration still succeeds — `controlling.py:8-11`
- §3.7 — insert — ambiguity — the gate reads every `REGISTERED`/`ENFORCING` referral with a present `controlling_order_state_code`, any one foreign code closes it; unconditional at order entry, `RESPONDING`-scoped for modification proposal — `controlling.py:29-38`
- §3.9 — insert — ambiguity — offer completion clears `next_installment_due_date`; remaining `OPEN` charges go to `SATISFIED` with balance zeroed and `paid_cents` untouched — `payments.py:19-27`

### Pass 2 — intake / paternity / order routes (13 pins, 6 mismatch-revisions)
- §2.4 — insert — ambiguity — clock-set ripening moves the case to `ORDER_ESTABLISHMENT` from whatever prior status, except a `CLOSED` case, left untouched while the action still establishes — `routes/clock.py:26-31`
- §3.1 — insert — ambiguity — income update requires both money and provenance; omitted/null `employer_name` preserves the stored value — `routes/participants.py:97-108`
- §3.1 — insert — ambiguity — neither the income update nor the locate result is a write against a case, so a closed case does not block them — `routes/participants.py:97,110`
- §3.1 — insert — ambiguity — locate result has no precondition at all: either `role_type`, any current `locate_status` including `UNLOCATABLE`, no referral needed, `locate_attempt_count` untouched — `routes/participants.py:110-120`
- §3.1 — **revise — mismatch** — "Creation recomputes `open_case_count`" replaced: nothing is written to either party row, so neither `updated_at` nor `version` moves — `routes/cases.py:69-71`
- §3.1 — insert — ambiguity — locate referral accepts only `OPENED`/`LOCATE` (else `ERR_INVALID_CASE_STATUS`); good-cause check sits below the state band — `routes/cases.py:101-105`
- §3.2 — insert — mismatch — the duplicate-action check is evaluated above the case-status band (only `CLOSED` outranks it) — `routes/paternity.py:50-52`
- §3.2 — insert — ambiguity — full creation defaults of the action row, incl. `NOT_REQUIRED` rows keeping `established_at`/`established_method` absent — `routes/paternity.py:73-92`
- §3.2 — **revise — mismatch** — `PRESUMED_MARITAL` is a second locate bypass: only `UNLOCATABLE` blocks it, not "not `LOCATED`" — `routes/paternity.py:66-71`
- §3.2 — insert — ambiguity — false `notary_verified` and a non-obligor signer are payload-band `ERR_VALIDATION`, not `ERR_PARTY_ROLE_MISMATCH`, and precede every state check — `routes/paternity.py:124-131`
- §3.2 — insert — ambiguity — the rejection limit blocks only a further rejection; a true chain of custody is accepted at count 2 — `routes/paternity.py:213-219`
- §3.2 — **revise — mismatch** — `genetic_probability_pct` stored/echoed exactly as supplied (not rounded to 2dp); bool/numeric-string rejected; chain-of-custody failure is `ERR_INVALID_PATERNITY_STATUS` — `routes/paternity.py:31-40,235`
- §3.3 — **revise — mismatch** — `requested_monthly_cents` is recorded only, never an input; entry always takes the guideline figure — `routes/orders.py:127,259`
- §3.3 — insert — ambiguity — `drafted_by_user_id` absent in `DRAFT`; stamped by the worksheet run — `routes/orders.py:141,191`
- §3.3 — **revise — mismatch** — removed the "both parties must have an income figure" worksheet precondition: there is none; missing CP income reads as zero, missing/unattributed NCP income imputes — `services/guideline.py:36-42`
- §3.3 — insert — ambiguity — absent `terminated_date` = infinite interval; modification predecessor excluded from the overlap test — `routes/orders.py:59-76,255-258`
- §3.3 — revise — ambiguity — the deviation-approve path runs neither the overlap test nor the CEJ test; everything else at the join point identical — `routes/orders.py:230-233,79-97`
- §3.3 — insert — ambiguity — vacatur accepts only `DRAFT` and `ENTERED`; `CALCULATED`/`PENDING_DEVIATION_FINDINGS`/terminal answer `ERR_INVALID_ORDER_STATUS` — `routes/orders.py:279-280`
- §3.4 — insert — ambiguity — employer `legal_name` 1–200 chars; malformed and duplicate `fein` both `ERR_VALIDATION`, uniqueness checked last; no update endpoint; `EmployerAgent` may read only its own row (`ERR_NOT_IWO_EMPLOYER`) and cannot list — `routes/employers.py:23-40,52-57`
- §3.5 — insert — ambiguity — full ledger response shape (`case_id`, echoed `as_of_date`, five `applied_*` buckets summed over all payments, both `total_*` figures, no id/version/stamps); malformed `as_of_date` → `ERR_VALIDATION`; the accrual run answers with the case row — `routes/cases.py:163-216`
- §3.9 — insert — ambiguity — every closure path precondition answers `ERR_INVALID_CASE_STATUS`; the `ARREARS_SATISFIED` fiscal check is reached only after it — `routes/cases.py:134-155`
- §3.9 — revise — ambiguity — closure writes both party rows (`updated_at` refreshed, `version` +1 each), unlike case creation — `services/cascade.py:124-130,155`

### Pass 3 — IWO / charges / reviews / enforcement / interstate / compromise routes (18 pins, 4 mismatch-revisions)
- §3.4 — insert — ambiguity — the figure actually used is written back onto the IWO's own `reported_disposable_income_cents`, so it is never absent on a stored row and is what an amendment compares against — `services/withholding.py:69`
- §3.4 — insert — ambiguity — fixed order of the three service checks: IWO status → parent order `ENTERED` → zero amount ⇒ `ERR_WITHHOLDING_CAP_EXHAUSTED` — `routes/iwo.py:97-102`
- §3.4 — **revise — mismatch** — an identical reported figure ⇒ `ERR_VALIDATION` checked after the `service_status` check; amendment bumps only the withholding order's `version` — `routes/iwo.py:123-141`
- §3.4 — insert — ambiguity — remittance takes a non-negative amount with zero accepted; one-month advance uses calendar arithmetic preserving time of day and clamping day-of-month; answers HTTP 201 carrying the new `PaymentTransaction` — `routes/iwo.py:150-164`
- §3.4 — insert — ambiguity — an unserved order gives the same `ERR_REMITTANCE_NOT_YET_DUE`; DEFAULTED/TERMINATED ⇒ `ERR_INVALID_IWO_STATUS`, never `ERR_IWO_DEFAULTED` — `routes/iwo.py:172-177`
- §3.5 — insert — ambiguity — no amount default for `ARREARS_JUDGMENT`/`GENETIC_TEST_COST`, so omission ⇒ `ERR_VALIDATION` in the payload band ahead of the order-status check — `routes/charges.py:51-60`
- §3.5 — insert — ambiguity — voidance zeroes `unpaid_balance_cents`; with no charge-status code, a non-OPEN charge with `paid_cents == 0` ⇒ `ERR_INVALID_CASE_STATUS`, and any `paid_cents != 0` ⇒ `ERR_CHARGE_PARTIALLY_PAID` whatever the status — `routes/charges.py:116-122`
- §3.5 — insert — ambiguity — `REVERSAL` accepts any non-zero amount (zero ⇒ `ERR_VALIDATION`); a cross-case offer ⇒ `ERR_REFERENCED_ENTITY_NOT_FOUND`; `COMPROMISE_INSTALLMENT` needs the offer id and an `ACCEPTED`/`ACTIVE` offer; other sources merely record the id — `routes/charges.py:131-156`
- §3.6 — insert — ambiguity — no `case_status` precondition beyond the CLOSED refusal and no `enforcement_posture` check at proposal time — `routes/enforcement.py:80-96`
- §3.6 — insert — ambiguity — a case with no `ENTERED` `CURRENT_SUPPORT` order reads the obligation as zero, making the two-month floor vacuous — `routes/enforcement.py:49-55`
- §3.7 — insert — ambiguity — drafting writes nothing to the case row, so its `updated_at`/`version` do not move — `routes/interstate.py:36-69`
- §3.7 — insert — ambiguity — a late acknowledgment ⇒ `ERR_INVALID_REFERRAL_STATUS` (boundary inclusive) — `routes/interstate.py:127-130`
- §3.7 — insert — ambiguity — the `ENFORCING` return path constrains no reason; every path precondition fails as `ERR_INVALID_REFERRAL_STATUS`; only the `REGISTERED` path clears the two controlling-order fields; "live" means status other than `RETURNED`, so a `DRAFT` still holds `interstate_role` — `routes/interstate.py:28-31,145-176`; `services/controlling.py:41-43`
- §3.8 — insert — ambiguity — an off-case participant ⇒ `ERR_PARTY_ROLE_MISMATCH` (after review-status, before the count limit); both income fields required; the response body is the review row — `routes/reviews.py:141-161`
- §3.8 — **insert+revise — mismatch** — full successor-order derivation (guideline components copied verbatim, `drafted_by_user_id` = proposing attorney) and the endpoint answers HTTP 200 with the updated review row — never 201, never the successor order — `routes/reviews.py:185-218`
- §4 — **revise — mismatch** — documented that single 200-instead-of-201 exception to the creation rule — `routes/reviews.py:218`
- §3.9 — insert — ambiguity — the four creation gates are evaluated in §2.9's precedence order, not the narrated order — `routes/compromise.py:60-71`
- §3.9 — insert — ambiguity — supersession bumps the older offer's own `version`; a refused creation supersedes nothing — `routes/compromise.py:83-86`
- §3.9 — **revise — mismatch** — on acceptance, participant and case `version` each rise by one more per released `ACTIVE` action (2 with one remedy, 3 with two); a `NOTICE_SENT` release writes only the action row; the stay is set after the releases — `routes/compromise.py:152-163`; `services/cascade.py:58-73`
- §3.9 — insert — ambiguity — default leaves `next_installment_due_date` standing, retains `compliance_payment_count`, writes no participant row, releases no action — `routes/compromise.py:179-185`
- §3.9 — insert — ambiguity — completion returns posture to `NORMAL` unconditionally rather than settling it against any surviving action — `services/payments.py:23`
- §3.9 — insert — ambiguity — each installment transition bumps the offer's `version` and the case's `version`; no participant row is written and the caller sees the payment, not the offer — `services/payments.py:30,74`

Pass 3 also confirmed four impl orderings already matched §2.9 and needed no edit (good-cause before STAYED at notice; contest window before STAYED at activation; CEJ before effective-date at proposed-order; aggregate cap before cap-exhausted at issuance), and deliberately left genuinely unreachable code unpinned (`post_charge`'s accrual-anchor fallback, `serve_iwo`'s zero-amount leg, `routes/cases.py:157-159`).

Orchestrator verification: `PRD_COMPLETED.md` is 510 lines / 152,514 chars vs `PRD_FINALIZED.md` 509 / 128,177 — NOT byte-identical (55 lines differ), so the scan demonstrably ran. Headings `diff` clean, tail ends on the §5 table's last row. `find` over `test_suite/`, `test_helpers/` and `workspace/implementation/` shows zero `.py` files modified after the 02:27 green sweep, so the verified 8/8 × 177/177 result still describes the shipped code — Steps 8 and 9 touched only PRD documents.

## Pipeline complete — 2026-09-05T03:05:00.000Z

All nine steps done. Final artifacts: SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml + SCAFFOLD_CORNER_DESIGN.yaml, test_helpers/ (9 modules), test_suite/ (21 modules, 177 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}, and workspace/implementation/results.{1..8}.json all at 177/177.
