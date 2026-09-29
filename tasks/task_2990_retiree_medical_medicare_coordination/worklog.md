# Worklog — task_2990_retiree_medical_medicare_coordination

## Step 1: Create task directory — 2026-09-06T02:53:14.702570973Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2990_retiree_medical_medicare_coordination and its workspace/ subdirectory. Index 2990 was pre-assigned by the invoking command; no scan of ./tasks/ was performed.


## Step 2: Generate scaffold — 2026-09-06T04:30:16.865294719Z

All three scaffold artifacts are complete and the linter is clean.

**Verdict block (verbatim, final run):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    47
  §1.1 entities declared:     9
  §1.8 instances scanned:     19
  §1.9 instances scanned:     60
  Calls scanned (§1.8+§1.9):  851

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Deliverables** (all parse as valid YAML; `all three parse OK`)
- `SCAFFOLD.yaml` — 2898 lines, 13 top-level keys, no `scaffold_difficulty_design` / `scaffold_corner_design` key. 9 entities, 9 state machines, 2 concurrency rules, 16 calculations, 47 validations, 47 endpoints, 47 errors, 8 roles; `difficulty: expert`.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1879 lines, single key `scaffold_difficulty_design`, all 9 §0.5 rule_ids × 19 instances (≥2 each).
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4675 lines, single key `scaffold_corner_design`, all 9 taxonomy sections, 76 instances (60 full recipes + 16 `excluded_because` stubs): entities 10, state_machines 14, calculations 14, validations 20, errors 2, endpoints 6, rbac 4, cross_cutting_complexity_layers 5, consistency_model 1.

**Two real SCAFFOLD.yaml defects found and fixed while grounding the new sections:**
1. `created_by_user_id` was referenced by §1.4 priority 25 (ERR_SEGREGATION_OF_DUTIES) and by three endpoints' `side_effects`, but was declared on **no** entity — this was the single lint violation. Added it as a `system` field to `EligibilityDetermination`, `ElectionEvent` and `ReimbursementClaim`.
2. §1.4 priority 25 said appeal-decision compares against `created_by_user_id` while the `EligibilityDetermination` state machine's precondition compares against `certified_by_user_id`. Aligned §1.4 to the state machine (`created_by_user_id vs certify`, `certified_by_user_id vs appeal-decision`).

Also corrected two of my own asserts that named a nonexistent field `actuarial_margin_bps` → `equivalence_margin_bps`, and stripped the leading "Generate task harder than expert level!" directive line from `scenario:` so it cannot leak into PRD.md downstream.

**Independent cross-checks run:** all 47 error ids in the catalog are triggerable by some §1.8/§1.9 instance (0 uncovered); instance `name`s unique across the union of both design files; every stub's cited `difficulty_instance` exists by name in the difficulty file and carries no `test_recipe`; every `data.<field>` / `<Entity>.<field>` token in the corner file resolves to a declared §1.1 field; `${var}` placeholder closure verified in call order (not just as a set) for both design files. `worklog.md` untouched; scratch confined to `.scratch/step2/`.

**Orchestrator verification:** all three YAMLs present and non-empty (157KB / 128KB / 295KB); `grep -rn "harder than expert"` over the task dir returns nothing, confirming the difficulty directive did not leak.

## Step 3: Copy shared files — 2026-09-06T04:30:16.879429353Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-06T04:47:22.663Z

PRD complete and all three Hard Contracts pass.

**Output:** `workspace/PRD.md` — **489 lines**, ends at a real boundary (final complete row of the §5 error table, trailing newline, no mid-sentence cut).

Section headings (all present): §1 Introduction; §2 Global Specifications & System-Wide Principles (2.1 RBAC, 2.2 API Response Structure, 2.3 Pagination, 2.4 Common Resource Properties and the Logical Clock, 2.5 Optimistic Concurrency on Parent Records, 2.6 Money/Basis Points/Rounding Order, 2.7 Segregation of Duties Across the Control Chain, 2.8 Validation Precedence, 2.9 Interval and Window Semantics, 2.10 Ledger and Headcount Conservation, 2.11 Parallel State Dimensions and Cascade Discipline); §3 Business Logic & Workflows (3.1 Plan Year and Option Catalogue, 3.2 Actuarial Equivalence and Subsidy Certification Chain, 3.3 Retiree Records/Grandfather Cohorts/Eligibility Rule Sets, 3.4 Determination/Certification/Appeal/Supersession, 3.5 Election Windows/Adjudication/Enrollment, 3.6 Coordination of Benefits with Medicare, 3.7 Reimbursement Arrangement Funding/Claims/Year-End Close, 3.8 Premium Billing/Payment/Delinquency Chain, 3.9 Nightly Administration Sweep and Accounting Liability Valuation); §4 Endpoint Definitions (47 rows); §5 Error Code Catalogue (47 rows).

**Contract 1 — Field-Name Coverage: PASS** (two independent passes). Pass 1 (token-split): 124 distinct entity field names — 0 missing; 62 request-body inputs — 0 missing; 23 query params — 0 missing; 9 path params — 0 missing; 7 sweep/clock output fields — 0 missing; 47 error ids — 0 missing; 8 role names — 0 missing. Pass 2 (strict backtick-exact, different extractor): 0 field misses, 0 enum-value misses across every `enum` on every field. All 22 calculation constants verified present as values in prose (identifiers deliberately absent per the no-pseudocode rule): 7450, 10000, 350 bps (74500 → 2607 vs rejected 2702), 50000-cent cap, 8000/6000/4000 + 1000 long-service bump capped at 10000, 31-day life-event window, 3-period lapse threshold, 15/20/25 full-eligibility horizons +5. Note: an initial run appeared to show everything missing — that was the extractor's backtick parity being flipped by the ``` fences in §2.2, not a PRD defect.

**Contract 2 — Rule Coverage: PASS.** All 47 validations present in the §2.8 ladder, numbering contiguous 1–47, each with correct HTTP status and an explicit `applies_to` scope clause. Both `concurrency_rules[]` OCC rejections covered (`expected_retiree_version` → `ERR_STALE_RETIREE_VERSION` 412 at priority 14; `expected_hra_account_version` → `ERR_STALE_HRA_ACCOUNT_VERSION` 412 at priority 15). 102 state tokens across all 9 state machines' 45 transitions — 0 missing; every `UPPER_SNAKE` enum/state/action literal in the scaffold appears in the PRD (only absentees are constant identifiers, prose words, and the PROVISIONAL/FINAL variant labels rendered as "provisional variant"/"final variant"). Cascading side effects covered: 6-hop delinquency chain, year-end-close claim shedding before forfeiture, HRA premium-offset transfer, headcount decrement, 4-phase nightly sweep with all 6 counters. Sibling-branch symmetry checked pairwise: APPROVE/DENY (election, claim), PAY/REVERSE, CERTIFY/REJECT, UPHOLD/REVERSE (appeal), RDS vs EGWP gating, ANNUAL_OPEN vs life-event window, both liability valuation methods, PROVISIONAL vs FINAL claim variant. 15 error ids do not appear in §3 prose — all cross-cutting auth/existence/pagination/OCC codes fully specified in §2.1, §2.3, §2.5, §2.8; intentional, not a gap.

**Contract 3 — §3 Path Purity: PASS.** §3 spans 180 lines with 1033 backtick tokens (285 distinct). Zero tokens start with `/`; zero bare HTTP-method tokens; zero method+path tokens; zero tokens containing `/` at all. Outside backticks: zero endpoint-path mentions and zero bare method words.

**Extra verifications:** §4 table 47 rows, method+path sequence exactly identical to `endpoints[]` including order, all 47 role columns match `endpoints[].roles` exactly. §5 table 47 rows, ids and HTTP statuses match `errors[]` exactly, in order. §2.2 diffs byte-identical against the reference response-structure section. No fuzzy words or pseudocode operators anywhere. Withheld files honoured: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` never opened, grepped, or referenced.

**Scaffold self-contradictions adjudicated (do not "fix" back):**
1. `ERR_SUBSIDY_NOT_CERTIFIED` — state machine gated on `coverage_class == MEDICARE_GROUP_WRAP`; validations[28] + error catalogue gated on `subsidy_vehicle` in {`RDS`,`EGWP`}. Used validations/catalogue.
2. `ERR_OUTSTANDING_PREMIUM_BALANCE` — used validations[45] ("another enrollment of the same retiree carries a PAST_DUE invoice with non-zero balance"), not the state machine's same-enrollment reading.
3. Appeal `UPHOLD` — both branches resynchronise `eligibility_status` from the resulting `outcome`, since opening an appeal sets it to `UNDETERMINED`.
4. Retiree-role ownership mismatch had no declared error id → mapped to `ERR_UNAUTHORIZED`.
5. Certify's plan-year precondition had no error in `applies_to` → attached `ERR_PLAN_YEAR_NOT_OPEN`.
6. Supersession set → used the fuller state-machine set (any determination not already `SUPERSEDED`).
7. Claim `DENY` → releases the whole hold, then zeroes `eligible_cents` (merged both sources).
8. Internal slip fixed during drafting: §2.11 said "Four entities carry two independent state dimensions" while listing three; corrected to "Three".

**Orchestrator verification:** `tail -15 workspace/PRD.md` ends on a complete `| ERR_PAYMENT_EXCEEDS_BALANCE | 422 |` table row — a real section boundary, not a mid-sentence cut. No truncation; no regeneration needed. Leak grep for the difficulty directive and design-file tokens returns nothing.

## Step 5: Generate unit tests — 2026-09-06T06:15:55.784Z

Step 5 is complete. All test infrastructure and test cases are on disk at the task root.

**`test_helpers/`** (9 modules): `__init__.py` (re-exports the runner's `prd_bench_local_runner.testing` helpers plus local ones), `api_client.py`, `api_errors.py` (`ApiErrorId`, `HTTP_STATUS_CODES`), `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`. No `sys.path` manipulation anywhere; every fixture builds state through PRD endpoints only.

**`test_suite/`**: `conftest.py` + **18 test files, 97 test functions**.

Per-queue instance counts:
- Queue A — `SCAFFOLD_DIFFICULTY_DESIGN.yaml` §1.8: 19 non-stub instances, **19 translated**, 38 tests (files `test_01`–`test_09`).
- Queue B — `SCAFFOLD_CORNER_DESIGN.yaml` §1.9: 60 non-stub instances, **59 translated**, 59 tests (files `test_10`–`test_18`).

Queue B by section: entities 9/10, state_machines 10/10, calculations 9/9, validations 17/17, errors 2/2, endpoints 4/4, rbac 4/4, cross_cutting_complexity_layers 3/3, consistency_model 1/1. No `excluded_because` stub was ever translated.

Every test carries exactly one `Design:` line; a scratch AST auditor confirms **0 orphan tags, 0 untagged/dual-tagged tests**, and a citation auditor confirms **0 non-verbatim quotes and 0 section-label mismatches** across all 18 files. `py_compile` passes on every file; `pyflakes` is clean on `test_suite/`.

Files written in the final session segment: `test_16_rbac.py` — 4 tests (role-list refusals incl. the read-scoped `Retiree` by-id read; the `Actuary`'s exclusive attest plus the review/decide pair driven by both entitled roles; self-certify of a determination; actuary-turned-compliance-officer self-certify of a subsidy). `test_17_cross_cutting.py` — 3 tests (stale `expected_retiree_version` → 412 then fresh-read retry; stale `expected_hra_account_version` refused **before** the balance rung, ledger conserved at 184992 = 134992 + 50000; the delinquency counter walked 1 → reset 0 → 1 → **2 (the boundary)** → 3 with lapse at 2027-06-01 and `reinstatement_deadline` 2027-07-31). `test_18_consistency_model.py` — 1 test (approval side effects and HRA funding complete in their own responses, with no `/_ops/daily-run` anywhere in the recipe). Removed one unused import (`COUNSELOR_2`) from `test_13_validations.py`.

**SKIPPED instances (1):** `Corner/entities/retiree_grandfathered_group_input_ignored_and_recomputed` — computed-field silence. PRD 2.8 rung 12 never says whether a body field that is not a declared input is ignored or rejected, so the asserted "201 with the derived value, input discarded" is not uniquely derivable. Gap left as a gap; no weakened test, no xfail, no placeholder.

**Design-index vs PRD deviations (asserted the PRD, not the yaml):**
(a) `Difficulty/boundary_precision_check/rule_of_75_points_exactly_at_inclusive_threshold` — yaml asserts `eligibility_status` after a create-only trigger; asserted `eligibility_points` 75/74.
(b) `Corner/entities/retiree_retrieval_returns_stored_row_with_derived_group` and `.../hra_account_system_fields_generated_server_side` — yaml asserts `eligibility_points == 0` on a fresh retiree and `created_at == <logical clock>`; asserted 75 and ISO-format validity.
(c) `Corner/state_machines/plan_option_initial_state_is_draft_and_not_started` — dropped non-derivable null/false assertions (gross/net test flags, margin, attester, certifier, pending change type, notice instant).
(d) `Corner/calculations/grandfather_group_assigned_at_both_hire_date_cutoffs` (asserted 99/99/87/87, not 0) and `.../rule_set_code_selected_by_group_for_transition_b_and_standard_c` (asserted `UNDETERMINED` + points 92/82 from DRAFT determinations).
(e) `Corner/validations/election_creation_with_every_check_satisfied_succeeds` and `.../settlement_on_submitted_claim_rejected` — dropped `reviewed_by_user_id is null` sub-assertions (PRD §3.5/§3.7 enumerate creation-time nulls and neither lists that field).
(f) `Corner/endpoints/clock_endpoint_moves_logical_time_for_subsequent_writes` — dropped the `created_at`/`updated_at` == logical-clock-instant and cross-row ordering assertions; PRD 2.4 fixes only the three-digit rendering and "Setting the clock mutates no entity". Instance still translated via the `current_utc` echo, single-key body, format validity and no-mutation re-read.
(g) `Corner/endpoints/retiree_patch_updates_only_named_mutable_fields` — yaml puts the retiree at version 2 after a certified determination and keeps `eligibility_points` at 75 after `credited_service_months` → 143. PRD §3.4 increments on determination creation **and** certification (→ 3) and PRD §3.3 rewrites points "whenever `credited_service_months` changes" (→ 74). Asserted versions 3/4/5 and points 74; the determination's frozen `points` 75 carries the "frozen" half.

**Output-location and hygiene checks:** `find` over the task tree returns exactly two matches: `test_helpers` and `test_suite`, both at the task root. **No `workspace/test_helpers` or `workspace/test_suite` exists.** `workspace/implementation/` was never read or written. `worklog.md`, `SCAFFOLD*.yaml` and `workspace/PRD.md` untouched. Scratch confined to `.scratch/step5/`; sibling `.scratch/step2` and `.scratch/step4` intact. No servers started, no processes killed.

**Orchestrator verification:** md5 of all test files taken twice 45s apart is identical — the fan-out had fully settled, so no phantom-coverage risk. 18 test files + conftest.py; 97 test functions and exactly 97 `Design:` tags (1:1); `py_compile` clean over test_suite/ and test_helpers/; `find` confirms no stray copy under workspace/.

## Step 6: Generate implementation — 2026-09-06T06:15:55.784Z

Implementation is complete and verified.

`workspace/implementation/` — 20 files, 3003 lines, flat-module Python 3 + Flask:
`requirements.txt` (1, `Flask>=3.0.0`); `start.sh` (10, chmod +x); `auth.py` (74) — 8 roles, ladder steps 1–2, Retiree ownership; `app.py` (77) — app factory, 10 blueprints, `ApiError`/`HTTPException`/`Exception` envelope handlers; `store.py` (88) — in-memory dicts, logical clock, `iso()` 3-digit instants, `base_record`/`touch`/`order_asc`; `routes_enrollments.py` (107); `routes_hra.py` (127); `envelope.py` (128) — meta/`req_`+20-alnum id, object/array/error envelopes, pagination; `routes_invoices.py` (147); `routes_retirees.py` (157); `routes_ops.py` (163) — clock + 4-phase nightly sweep; `routes_plan_years.py` (179); `domain.py` (181) — existence resolvers, MSP application, ledger/headcount cascades; `errors.py` (185) — all 47 error ids with exact HTTP statuses; `routes_determinations.py` (188); `routes_plan_options.py` (204); `routes_elections.py` (213); `routes_claims.py` (227); `validate.py` (227) — ladder step 12 shape ladder; `calc.py` (320) — all 16 calculations, 8-branch MSP, waterfall, valuation.

**Verification:** `bash -n start.sh` clean; `python3 -m py_compile` clean on all 18 `.py` files. **Route map = exactly 47 endpoints**, matching PRD §4 (5 plan-year, 4 retiree, 7 plan-option, 6 determination, 5 election, 4 enrollment, 4 hra-account, 6 claim, 4 invoice, plus `POST /_clock/set_current_utc` and `POST /_ops/daily-run`). **Fresh boot is empty**: all 9 list endpoints return `total_count: 0`, `data: []`. No seeding, no on-disk state (only source files in the dir). **Live server** booted with `PORT=41049 bash start.sh`, captured pid 1855591: `ps` shows the captured pid *is* `python3 app.py` (start.sh `exec`s, so the harness's kill lands on the server itself); killing that exact pid freed the port with no orphan. Curls: unauthenticated `GET` → 401 `ERR_UNAUTHENTICATED`; `Actuary` write → 403 `ERR_UNAUTHORIZED`; `POST /retiree-benefits/plan-years` → 201 object envelope with derived defaults (`premium_grace_period_days` 31, `reinstatement_window_days` 60, `notice_lead_days` 60, `status` DRAFT, `version` 1); `GET ...?limit=1` → 200 array envelope with `limit/offset/total_count/has_more`; `limit=101` → 400 `ERR_INVALID_PAGINATION`; unknown retiree → 404 `ERR_RETIREE_NOT_FOUND`. All instants render `...T00:00:00.000Z`.

**Two end-to-end behavioural scripts** (run in-process, both "ALL EXPECTATIONS MET", ~70 assertions) walked: plan-year lifecycle + duplicate/transition refusals; retiree grandfathering; option activate/attest/subsidy-certification incl. gross-then-net 422 ordering and SoD 403; determination OCC 412, SoD certify, appeal → appeal-decision; election window (in/out), review, SoD decision, coverage-overlap 409, enrollment materialisation with MSP + waterfall; HRA funding, claim hold → review → pay → reverse; invoice assembly, overpay 422, ownership 403, partial payment; the full 6-hop past-due → suspend → lapse chain with account freeze and claim denial; delinquency unwind on payoff; reinstatement (RBAC 403, success, double-reinstate 409); manual terminate; year-end close forfeiture. Pinned arithmetic matched the PRD's worked examples exactly: HRA `209500/12 → 17458 × 7 = 122206`; admin fee `350bps of 74500 = 2607`; subsidy `8000bps of 77107 = 61685`; valuation `epbo 4571428`, PUC `apbo 2742856`, ATTRIBUTION `apbo 3657142`, service cost `228571`; close-year cap `0.25 × 120000 = 30000` → forfeited 90000. The 5-bucket ledger conservation and `enrolled_count` conservation held after every cascade.

Scratch dir `.scratch/step6/` removed; sibling `.scratch/step2|step4|step5` untouched; no stray listeners or processes left behind. Did not read `test_helpers/`, `test_suite/`, or either design YAML, and did not touch `worklog.md`, `PRD.md`, or `SCAFFOLD.yaml`.

**Orchestrator note:** Steps 5 and 6 were launched concurrently in a single assistant message, so the implementation generator started before `test_suite/` existed on disk — physical isolation from the tests, not merely instructed isolation.

## Step 7: Run tests and iterate — 2026-09-06T06:27:26.620Z

Done. All 8 rounds clean.

**Iterations run:** 2 (iteration 1 = diagnostic sweep, iteration 2 = verification sweep after fixes).

**Tests deleted:** none. Both failures survived STEP 1a (PRD verbatim-covers the rule) and STEP 1b (unique derivability holds), and both turned out to be STEP 2 test-artifact bugs where the test's own setup contradicted its assertion.

**Fixes applied to `test_helpers/`:** none. Iteration 1 produced only 2 failures, both isolated single-site assertion bugs in `test_suite/`, so no shared upstream fixture was implicated.

**Fixes applied to `implementation/`:** none. No implementation defect was found; the PRD-faithful implementation was correct on both counts (verified by mtimes — every impl file is untouched since Step 5/6).

**Fixes applied to `test_suite/`** (both STEP 2 "assertion mis-translates PRD wording"):

- `test_suite/test_16_rbac.py`, `test_no_role_may_reach_past_its_own_endpoint_list` — asserted `untouched_option["rx_gross_value_bps"] == 0` after a *refused* attest, but the test's own fixture (`f.med_wrap_payload`) creates MED-WRAP with `rx_gross_value_bps=10500`. PRD 3.1 has the create request supply that value and PRD 3.2 says the actuary's attested values "overwrite whatever the option carried before" — so "untouched" means still 10500, not 0. Changed to `== option["rx_gross_value_bps"]`, which is what "no refused call may leave a trace" actually asserts. (Failure was `assert 10500 == 0`.)

- `test_suite/test_09_compensating_invariant.py`, `test_terminating_the_new_enrollment_returns_the_headcount_to_one` — asserted R4's bystander enrollment was `ACTIVE`. Its shared setup helper approves R4's election while the clock stands at `2026-10-20`, strictly before the `2027-01-01` `coverage_effective_date`, so PRD 3.5 ("`coverage_status` is `ACTIVE` when the logical clock has already reached that `coverage_effective_date` and `PENDING` when it has not") requires `PENDING`. The clock only moves past that date afterwards, and only the sweep's Phase 1 activates a PENDING enrollment — no sweep runs in this test. Changed to `== "PENDING"` and corrected the helper's docstring. `PENDING` is one of the three coverage states PRD 2.10 counts, so every headcount assertion in the test (`enrolled_count == 1`, `len(covered) == 1`) was already consistent and is unaffected.

**Final per-round table (iteration 2):**

```
 round  total  passed  failed(listed)  verdict
     1     97      97               0  CLEAN
     2     97      97               0  CLEAN
     3     97      97               0  CLEAN
     4     97      97               0  CLEAN
     5     97      97               0  CLEAN
     6     97      97               0  CLEAN
     7     97      97               0  CLEAN
     8     97      97               0  CLEAN

ALL 8 ROUNDS CLEAN — passed == total everywhere.
```

**Hygiene:** `worklog.md`, `workspace/PRD.md` and all three SCAFFOLD files are untouched (verified via `git diff`). No flakiness appeared in either sweep — both iteration-1 failures were deterministic across all 8 rounds, and iteration 2 was clean in all 8. `.scratch/step7/` was removed; sibling `.scratch/step2|step4|step5` left intact.

**Orchestrator verification (not taken on trust):** re-ran `summarize_sweep.py` against the on-disk artifacts — 8 `results.$i.json` files all present, all timestamped 06:25 from the same sweep (not stale), every round 97/97 with `passed == total`, union of failures empty, and the listed-failure count reconciles against `total - passed` in every round. `test_suite/` still holds 97 test functions, matching Step 5's output exactly — corroborating the zero-deletions claim.

**Step 8 skip decision:** NOT skipped. The skip condition requires all four counters at zero; Step 7 recorded 0 deletions / 0 `test_helpers/` fixes / 0 `implementation/` fixes but **2 `test_suite/` fixes**, so Step 8 runs with those two sites as its `<step_7_diff>` focus list. Both were assertion mis-translations against PRD prose that already pinned the behavior, so a byte-identical or near-identical `PRD_FINALIZED.md` is a legitimate outcome here — the diff had no `implementation/` fix behind it to align to.

## Step 8: Finalize PRD — 2026-09-06T06:35:10.669Z

`workspace/PRD_FINALIZED.md` written as a byte-identical copy of `PRD.md`.

- PRD.md: 489 lines. PRD_FINALIZED.md: 489 lines. Delta: **0 lines, 0.0%** (md5 `790bdce0e26600db1407e250e515499e` on both).
- **Zero edits made.** `<step_7_diff>` contains zero `implementation/` fixes, zero test deletions and zero `test_helpers/` fixes; the only two changes were single-site assertion corrections in `test_suite/`, and the subagent verified from source that PRD.md already uniquely determines both behaviors as implemented.

**Evidence — Site 1 (`test_16_rbac.py::test_no_role_may_reach_past_its_own_endpoint_list`, `rx_gross_value_bps` after a refused attest).** Subject: the value of `rx_gross_value_bps` on a `PlanOption` at creation, and whether a 403-refused attest mutates it. Impl paths enumerated (all `rx_*_bps` writers/readers across the tree — 8 hits, all in one file): `routes_plan_options.py:45-46,62-63` create reads `body.bps("rx_gross_value_bps")`/`rx_net_value_bps` and stores them verbatim, with no zero default and no reset in the `record.update({...})` initialiser at 64-76; `validate.py:127-129` + `:97-116` `Body.bps` defaults to `required=True`, so both fields are mandatory create inputs and an option can never exist with an implicit 0; `routes_plan_options.py:143-144` attest is the only other writer and overwrites both, matching PRD 3.2's "overwrite whatever the option carried before"; `routes_plan_options.py:120` `require_caller((ROLE_ACTUARY,))` runs before `read_body()` and before any mutation, so a non-Actuary 403 leaves the record untouched with no partial-write path; `certify_subsidy` (`:154-173`) and `issue_change_notice` (`:176-204`) never touch the `rx_*` fields. PRD coverage: §3.1 line 213 enumerates both fields among what each option "carries" at definition, and the same sentence's closing clause lists the *only* three fields with a fixed initial value ("A new option starts with `status` `DRAFT`, `subsidy_certification_status` `NOT_STARTED` and `enrolled_count` 0") — the rx values are conspicuously absent; §3.2 line 223 pins overwrite semantics; §2.1 line 15 + §2.8 rung 2 pin that an unauthorized request is rejected with `ERR_UNAUTHORIZED` and performs no work. Already determined; no edit.

**Evidence — Site 2 (`test_09_compensating_invariant.py::test_terminating_the_new_enrollment_returns_the_headcount_to_one`, bystander PENDING vs ACTIVE).** Subject: the `coverage_status` an approval-materialised `Enrollment` opens in, and what may later move it to `ACTIVE`. Impl paths enumerated (all 16 `coverage_status` sites): `routes_elections.py:193` `"coverage_status": "ACTIVE" if clock >= proposed_start else "PENDING"` is the sole birth site; `routes_ops.py:51-55` sweep Phase 1 is the only unconditional `PENDING → ACTIVE` promoter; `routes_ops.py:87-88` (Phase 2 `ACTIVE → SUSPENDED`), `routes_invoices.py:144-145` (full payment of a past-due invoice, `SUSPENDED → ACTIVE` only) and `routes_enrollments.py:90` (reinstatement, gated at `:66` on `TERMINATED` + `LAPSED`) can none of them lift a `PENDING` row to `ACTIVE`, so with no sweep in the test the bystander stays `PENDING`; `routes_enrollments.py:50-52` and `domain.py:179` accept `PENDING` as terminable, and `domain.py:106` / `routes_ops.py:137,151` / `calc.ACTIVE_COVERAGE_STATUSES` all count `PENDING` in the covered set, so the test's `enrolled_count == 1` and `len(covered) == 1` are unaffected. PRD coverage: §3.5 line 285 states verbatim that `coverage_status` is "`ACTIVE` when the logical clock has already reached that `coverage_effective_date` and `PENDING` when it has not"; §3.9 Phase 1 (line 363) is the only activation rule; §2.10 line 193 counts `PENDING` in `enrolled_count`. Already determined; no edit.

No wording adjustments were required because no sentence was written. `PRD.md`, `worklog.md`, `test_suite/`, `test_helpers/` and `implementation/` are unmodified.

**Orchestrator adjudication:** a byte-identical `PRD_FINALIZED.md` is the correct and expected result at Step 8 when Step 7 produced no `implementation/` fixes and no deletions — there was no impl behavior to align the prose to. This is explicitly NOT acceptable for Step 9, whose full impl-vs-PRD scan must actually run; Step 9 is therefore being executed as module-partitioned sequential passes over one shared `PRD_COMPLETED.md` (pass 1 performs the `cp`, later passes must not), followed by a narrow cross-pass reconciliation pass.

## Step 9: Complete PRD — 2026-09-06T07:10:57.966Z

Step 9 was executed as **four sequential subagent passes over one shared `workspace/PRD_COMPLETED.md`**, partitioned by implementation module, followed by a narrow reconciliation pass. Pass 1 alone performed the initial `cp` from `PRD_FINALIZED.md`; passes 2–4 were explicitly forbidden from re-copying (which would have silently destroyed prior edits). **Total: 60 edits.** Final file 491 lines / 121,619 chars vs source 489 lines / 101,658 chars; md5 `d313161377f871a0f2b73214906725b0` vs source `790bdce0e26600db1407e250e515499e` — **not identical**, so the scan demonstrably ran.

### Pass 1 — app.py, store.py, envelope.py, errors.py, auth.py, validate.py, calc.py (12 edits: 11 ambiguity-pins, 1 mismatch-revision)
- §2.1 — revise — ambiguity — header emptiness now covers whitespace-only values; role matching pinned as exact/case-sensitive with no whitespace tolerance — `auth.py:57-62`
- §2.1 — insert — ambiguity — ownership scoped to exactly the 5 `Retiree` write ops (election submit, appeal open, claim submit, substantiation, premium payment); read/list endpoints admitting `Retiree` are explicitly *not* ownership-scoped — `auth.py:70-74` + 5 call sites
- §2.2 — revise — ambiguity — `api_request_id` = `req_` + exactly 20 chars from `[A-Z0-9]` — `envelope.py:12,21-22`
- §2.3 — revise — ambiguity — pagination params ignore surrounding whitespace; empty/fractional/non-integer text rejected — `envelope.py:83-94`
- §2.3 — insert — ambiguity — creation order is the stable tie-break for equal `created_at`, governing every cascade fan-out — `store.py:82-84`
- §2.4 — revise — ambiguity — clock may move backwards (non-monotonic); `current_utc` normalised to UTC, rendered with 3 fractional digits — `store.py:43-45,52-60`
- §2.6 — revise — **mismatch** — "Instant fields are compared at millisecond resolution" replaced: instants compared exactly with no pre-comparison ms rounding; pins accepted input forms (offset-less → UTC, bare `YYYY-MM-DD` → midnight UTC) and truncated 3-digit rendering — `validate.py:31-51`, `store.py:52-60`
- §2.8 step 12 — insert — ambiguity — absent/unparseable body treated as `{}`; non-object JSON body itself `ERR_INVALID_REQUEST`; undeclared body fields ignored — `validate.py:13-19,63-68`
- §2.9 — insert — ambiguity — whole-day lead time is a **floor**, not truncation toward zero, so a past `effective_date` fails even at `notice_lead_days` 0 — `calc.py:110-113`
- §3.7 — insert — ambiguity — leap-day edge of the expense window: a 29 Feb `coverage_start` shifts to 28 Feb next year before the one-day subtraction — `calc.py:127-134`
- §4 intro — insert — ambiguity — paths match with or without a trailing slash — `app.py:41`
- §5 intro — insert — ambiguity — `ERR_RESOURCE_NOT_FOUND` (404) for unmatched routes and `ERR_METHOD_NOT_ALLOWED` (405) for undeclared methods sit outside the 47-id catalogue, in the standard error envelope — `app.py:51-62`

Judged already-pinned (coverage, not oversight): all 47 error ids/statuses/order verified programmatically identical to §5; store defaults (clock `2026-08-01T00:00:00Z`, no wall-clock fallback, UUID with no prefix, `version` from 1 and +1 per mutation incl. cascades, `updated_at` refresh); envelope shapes, `response_type`, error-`meta` limits, `has_more = offset + len(window) < total_count`, limit/offset defaults and bounds, `_`-prefixed key stripping; the 8 role names, ladder order 401→403, `ALL_ROLES_EXCEPT_RETIREE` for `GET /retirees`; every `_cents` field through `cents()` with `minimum=0` (all 7 call sites — §2.6's universal claim holds), `_bps` non-negative, `carryover_cap_pct` in [0,1], strict date regex, start < end, `submitted_cents` > 0, all documented bounds; **all 16 calculations verified against PRD prose with no change needed** — completed age, service years, whole-months, grandfather half-open cutoffs, the 3 rule sets incl. Rule-of-75's three inclusive conditions, `eligibility_points`, all 8 MSP branches incl. inclusive 20/100 thresholds + `size == 0` fall-through + strict `< 30` boundary, gross/net benchmarks 10000/7450 and signed `equivalence_margin_bps`, HRA floor-per-month-then-multiply (209500/7 → 122206 reproduces exactly), carryover cap floor, forfeiture, provisional vs final variants incl. 5000 bps dental/vision + 50000-cent cap + `+ provisional` add-back, subsidy bps 8000/6000/4000 + 1000 long-service bump capped at 10000, the 8-step waterfall incl. 350 bps fee-exclusive admin fee (74500 → 2607 reproduces), EPBO/APBO/service-cost under both methods with per-retiree flooring, half-open coverage vs closed billing collision rules, the coverage-class × Medicare-posture matrix.

### Pass 2 — routes_plan_years.py, routes_retirees.py, routes_plan_options.py, routes_determinations.py (21 edits: 19 ambiguity-pins, 2 mismatch-revisions)
- §3.1 — insert — ambiguity — `coverage_start` validated only as a well-formed instant, no ordering constraint against either annual-window endpoint — `routes_plan_years.py:33,47`
- §3.1 — insert — ambiguity — the still-`OPEN`-account block on `ARCHIVED` refused with the same `ERR_INVALID_PLAN_YEAR_TRANSITION`, evaluated after the successor check — `routes_plan_years.py:109-116`
- §3.1 — insert — ambiguity — option creation admitted whatever the plan year's `status`; only activation gates on it — `routes_plan_options.py:31-51`
- §3.1 — insert — ambiguity — initial `gross_test_passed`/`net_test_passed` false and `equivalence_margin_bps` 0 regardless of supplied bps (creation runs neither test), plus the six null fields — `routes_plan_options.py:65-75`
- §3.1 — insert — ambiguity — activation takes no body; non-`DRAFT` → `ERR_PLAN_OPTION_NOT_ACTIVE` checked *before* the plan year → `ERR_PLAN_YEAR_NOT_OPEN` — `routes_plan_options.py:104-111`
- §3.1 — revise — **mismatch** — PRD said `new_monthly_premium_cents` "is absent for a `PLAN_TERMINATION`"; impl admits and discards it — `routes_plan_options.py:183,201-202`
- §3.1 — insert — ambiguity — a second notice over an unapplied pending change is admitted and overwrites all four staged fields — `routes_plan_options.py:198-203`
- §3.2 — insert — ambiguity — neither attestation nor certification consults the plan year's `status` — `routes_plan_options.py:118-173`
- §3.2 — insert — ambiguity — `RETIRED` → `ERR_PLAN_OPTION_NOT_ACTIVE`; a refused attestation writes nothing, stored bps included — `routes_plan_options.py:133-141`
- §3.2 — insert — ambiguity — non-entry state → `ERR_INVALID_REQUEST` after the `NONE` check but *before* the availability check; re-attestation does not clear `certified_by_user_id` — `routes_plan_options.py:126-135,169`
- §3.2 — insert — ambiguity — non-`ATTESTED` → `ERR_INVALID_REQUEST`, preceding the SoD comparison — `routes_plan_options.py:161-167`
- §3.3 — insert — ambiguity — `medicare_status` may be seeded to any member at creation (incl. `MEDICARE_ENROLLED` with null Part B); the three dates carry no mutual ordering constraint — `routes_retirees.py:39-44`
- §3.3 — insert — ambiguity — partial-update semantics: omitted = unchanged; only the two nullable dates clearable via explicit `null`; an empty patch is a successful update — `routes_retirees.py:105-147`
- §3.3 — insert — ambiguity — illegal Medicare move and missing Part B both → `ERR_INVALID_REQUEST` (400), not 409; same-status is an accepted no-op; `MEDICARE_ENROLLED` terminal — `routes_retirees.py:122-132`
- §3.3 — revise — **mismatch** — PRD said "Whichever move fires"; impl re-runs MSP on *every* admitted patch (even `credited_service_months`-only or empty) and versions every active enrollment whether or not the result changed — `routes_retirees.py:152-154`
- §3.4 — insert — ambiguity — the five null fields on a new determination — `routes_determinations.py:67-71`
- §3.4 — insert — ambiguity — supersession guarantees at most one non-`SUPERSEDED` determination per retiree-and-plan-year, so "*the* `CERTIFIED` determination" is unique and no selection ever arises — `routes_determinations.py:42-48`
- §3.4 — insert — ambiguity — certify takes no body; gate order determination `status` → plan-year `status` → SoD — `routes_determinations.py:104-116`
- §3.4 — insert — ambiguity — `appeal_reason` accepts any string incl. empty; ownership checked after path resolution but before body and state, so `ERR_UNAUTHORIZED` wins; no plan-year requirement — `routes_determinations.py:136-142`
- §3.4 — insert — ambiguity — no plan-year requirement on appeal decision; `certified_by_user_id` and `appeal_reason` survive a decision (barring the original certifier from every future appeal); no plan-year `version` bump — `routes_determinations.py:158-188`
- §3.9 valuation — insert — ambiguity — no plan-year `status` precondition; an empty cohort is not an error and still stamps `liability_method`/`liability_valued_at` — `routes_plan_years.py:145-178`
- §4 ×4 — revise — ambiguity — named the actual filter sets for its four list rows, and stated once that a non-matching filter value yields an empty page rather than an error and undeclared params are ignored — `routes_plan_years.py:92-97`, `routes_retirees.py:90-93`, `routes_plan_options.py:91-95`, `routes_determinations.py:92-95`
- §2.8 rungs 17/18 — revise — both had *closed* endpoint enumerations impl contradicts across partitions; made both explicitly non-exhaustive deferring to §3, rather than enumerate unverified pass-3 sites.

Judged already-pinned: RBAC for all 16 endpoints matching `require_caller`; plan-year bounds/defaults (31/60/60), `DRAFT` initial state, three-successor chain, `OPEN → CLOSED` two-hop catalogue cascade with the already-`CLOSED_TO_NEW` carve-out, `ARCHIVED` terminal; plan-option `plan_code` uniqueness, enum domains, `NONE → gross → net` gate order, both inclusive benchmarks, negative `equivalence_margin_bps`, `RDS` gated on gross alone, `REJECTED → ATTESTED` reusability, SoD vs `attested_by_user_id`, notice error order matching ladder 12 < 18 < 38; retiree bounds, grandfather half-open cutoffs, when `eligibility_points` is recomputed, the eight patchable fields, `hire_date`/`grandfathered_group` immutability; determination `expected_retiree_version` 412, strict `OPEN` at creation, all frozen fields, supersession set and ordering, SoD on certify and appeal-decision, `UPHOLD` vs `REVERSE` handling, ladder-consistent 404 → shape → 412 → 409.

### Pass 3 — routes_elections.py, routes_enrollments.py, routes_hra.py, routes_claims.py, routes_invoices.py, routes_ops.py, domain.py (22 edits: 14 ambiguity-pins, 8 mismatch-revisions)
- §2.8 rung 2 — insert — ambiguity — the `Retiree` ownership check does *not* sit at rung 2: it runs after existence rungs 3–11 and before shape rung 12, still reporting 403; skipped entirely when the naming body field is absent or non-string. Universal across all 5 sites — `routes_elections.py:40-41`, `routes_claims.py:39,116`, `routes_invoices.py:110`, `routes_determinations.py:136`
- §2.8 rung 12 — insert — ambiguity — an absent/wrongly-typed body-carried FK is never resolved so rungs 3–11 skip it and rung 12 reports (`domain.py:55-64`); the six endpoints declaring no body fields never inspect the body at all
- §2.8 rung 17 — revise — **mismatch** — ladder ordering was outright wrong: on any operation mutating a pre-existing record, that record's own state rung (18–24) is evaluated **before** the plan-year rung — `routes_elections.py:124-130`, `routes_hra.py:105-110`, `routes_determinations.py:105-110`, `routes_plan_options.py:104-110`
- §2.8 rung 18 — insert — ambiguity — added the approving-election-decision site — `routes_elections.py:168`
- §3.5 — insert — ambiguity — all five body fields required including `event_date` on `ANNUAL_OPEN`, stored but unused by the window computation — `routes_elections.py:46-47,57-61`
- §3.5 — insert — ambiguity — `reviewed_by_user_id` opens null — `routes_elections.py:93`
- §3.5 — insert — ambiguity — `denial_reason_code` accepts exactly `COUNSELOR_DENIAL`/`PLAN_CLOSED`, enum-validated on `APPROVE` too — `routes_elections.py:25,144-145`
- §3.5 — insert — ambiguity — termination moves the coverage dimension only (`billing_status` and all five delinquency counters untouched), so terminating a `SUSPENDED` enrollment strands it `TERMINATED`+`DELINQUENT` and unreinstatable; `PAST_DUE` invoices are *not* written off here — `routes_enrollments.py:50-58`, `domain.py:156-160,177-182`
- §3.6 — revise + new paragraph — **mismatch** — "whenever a retiree's Medicare or other-coverage attributes are updated" widened to "on every admitted retiree update", with a paragraph distinguishing the four triggers: the PATCH is blunt (any admitted patch rewrites and versions every active enrollment regardless of whether the result moved), the sweep is discriminating, approval/reinstatement take no extra increment — `routes_retirees.py:95-156`, `routes_ops.py:149-163`, `domain.py:89-96`
- §3.7 — insert — ambiguity — `REQUEST_SUBSTANTIATION` is the one branch that does not mutate the account, so it does not advance the account's `version`; `eligible_cents` stays provisional — `routes_claims.py:160-163`
- §3.7 — insert — ambiguity — the year-end-close claim-denial cascade releases the hold but leaves each claim's `eligible_cents` standing (asymmetric with a reviewer's `DENY`), and the account takes one `version` increment for the whole close, not one per claim — `domain.py:125-136`, `routes_hra.py:115-126`
- §3.8 — insert — ambiguity — the enrollment's coverage/billing state is not a precondition for invoicing; the only non-shape refusals are plan-year status and period overlap; `billing_period_*` are instants — `routes_invoices.py:26-47`
- §3.8 — insert — ambiguity — `amount_cents` is not strictly positive; a 0 payment is accepted and moves `ISSUED` → `PARTIALLY_PAID` — `routes_invoices.py:112`, `validate.py:118-125`
- §3.8 — revise — **mismatch** — PRD asserted "reaches 0 — *equivalently*, no invoice left in `PAST_DUE`"; impl requires **both** conjunctively. Also pinned the floor at 0 and corrected the `version` scope (enrollment versioned on *every* full payment of a past-due invoice, not only when the clear conditions hold) — `routes_invoices.py:132-147`
- §3.8 — insert — ambiguity — `reinstatement_deadline` deliberately **not** cleared; the `FROZEN`→`OPEN` hop skipped without error when no `FROZEN` account exists; one enrollment `version` increment total — `routes_enrollments.py:85-107`
- §3.9 — insert — ambiguity — already-`SUSPENDED`/`PENDING`/`TERMINATED` enrollments are neither moved nor counted; hops 2–4 advance `version` by exactly 1 *per processed invoice* — `routes_ops.py:87-96`
- §3.9 — insert — ambiguity — the lapse guard is `>= 3` **and** `billing_status != "LAPSED"`, so a lapsed enrollment that keeps accruing past-due invoices lapses and is counted exactly once — `routes_ops.py:92-94`
- §4 ×5 — revise — **mismatch** — undeclared list filters named for its five rows: election-events `+status,event_type`; enrollments `+coverage_status,billing_status`; hra-accounts `+status`; claims `+status,expense_category`; invoices `+status`

Disposition of the 5 items handed to pass 3: (1) **the handoff's description was wrong** — `routes_elections.py:41` *is* guarded by `body.present(...) and isinstance(..., str)`, so a missing/non-string `retiree_id` yields 400 not 403; the real fact (ownership sits between rungs 11 and 12) was pinned once at §2.8 rung 2, which also closes the gap pass 2's §3.4 appeal prose would have left. (2) `open_account_for`'s `[0]` — **unobservable, no edit**: `routes_hra.py:39-44` refuses a second account for a (retiree, plan_year) pair in *any* status with no delete path anywhere, so at most one candidate can exist; §3.7 already pins that uniqueness. (3) `write_off_invoices` — both callers' status sets already pinned; strengthened §3.5 to state the `PAST_DUE` exclusion and the ordering. `adjust_enrolled_count`'s missing-option no-op is **unreachable** (options are never deleted, every call site passes a live FK) — no edit, since pinning it would invent behavior. (4) §3.6 widened as described. (5) rungs 17/18 — pass 2's non-exhaustive framing preserved verbatim, three sites added.

Judged already-pinned: election create role pair, 3 body-FK resolution order, the full gate sequence 17→18→29/30→31/32→33→34→35, both window computations and both `coverage_effective_date` derivations; review's `UNDER_REVIEW`+`reviewed_by_user_id` and absence of SoD; `_approve`'s option/subsidy/determination/overlap gauntlet, the all-enrollments-all-statuses overlap candidate set and half-open semantics, `ACTIVE`-vs-`PENDING`, the steps-1-6 waterfall, `enrolled_count`+1; reinstate's three gates; HRA create's three `ERR_DUPLICATE_HRA_ACCOUNT` sub-checks and floor-then-multiply funding; close-year's cascade-then-forfeiture order, cap-on-this-year's-credit-only, terminality; claims' 412/`OPEN`/window/balance gates and provisional hold, substantiation's resubmit counter and unbounded cycle, review's three branches incl. `DENY` zeroing `eligible_cents`, settlement's PAY/REVERSE exact inverse; all ten invoice assembly steps, the closed-interval overlap with `WRITTEN_OFF` excluded, `PAID`-at-0-net; clock endpoint's no-mutation, all four sweep phase orderings and every counter condition, `_lapse`'s six hops, phase 3's idempotence via the uncleared `change_notice_issued_at`; all 9 domain existence resolvers, `apply_msp`, `deny_held_claims`' three held statuses, `outstanding_balance`, `terminate_coverage`.

### Pass 4 — reconciliation (5 edits)
- §2.8 rung 12 — revise — **resolved the pass-1/pass-3 contradiction**. Adjudicated from source: *both* claims were true and the conflict was purely one of scope. `validate.py:14-19` `read_body()` fails a non-dict with `ERR_INVALID_REQUEST`, so pass 1 is right for every endpoint that calls it; exactly six POST endpoints never call it — `routes_determinations.py:100` certify, `routes_elections.py:120` review, `routes_enrollments.py:62` reinstate, `routes_hra.py:101` close-year, `routes_plan_options.py:100` activate, `routes_ops.py:28` daily-run — so pass 3 is right for those. Pass 1's unqualified sentence was scoped to "on an endpoint that reads the request body at all". (`/_clock/set_current_utc` *does* call `read_body`, so it is correctly absent from the six.)
- §2.8 opening — insert — the rung-17 carve-out did **not** read cleanly against "the rule that appears earliest in the following ladder produces the response", and there are now two such deviations (rung 2's ownership half, rung 17). Rather than weaken "total", added a two-sentence qualifier naming both and stating that a rung fixing its own position governs — §2.8 remains a single authoritative order. Carve-out verified at five sites — `routes_elections.py:123-130`, `routes_hra.py:104-109`, `routes_plan_options.py:104-110`, `routes_determinations.py:104-111`, `routes_enrollments.py:66`
- §3.5 `APPROVE` — insert — clause stating the paragraph is narrated, not sequential, and that subsidy precedes the determination checks — `routes_elections.py:165`
- §3.7 claim review — insert — clause pinning that both state gates precede the SoD comparison — `routes_claims.py:143`
- §3.7 settlement — insert — clause pinning that account and per-action state gates precede the SoD comparison — `routes_claims.py:196`

Pass-4 verdicts on the other referred items: **rungs 17/18** — no edit needed, pass 2's non-exhaustive framing survived intact and the enumerations verify against impl. **Rung 2** — no edit needed, stated exactly once and consistent with §2.1, which only says an ownership mismatch is a 403 and never says where in the ladder it fires; all five call sites verified. **(C) narrative-vs-evaluation order** — pass 4 chose to **edit all three** rather than defer to §2.8, because each collision is directly observable in the returned `error_id` and §3.5's ordinal language ("Finally the new coverage interval…") actively invites reading the list as sequential; each fix is one pointer clause, not a reordering, and in all three cases §2.8 already matched impl. **(D) pass 3's new §3.6 paragraph** — kept as its own paragraph: it covers a distinct topic (per-trigger `version` semantics) from the preceding one (payer order is derived, not stored), §3.6 is already multi-paragraph, and folding would weld two unrelated ideas into ~450 words. Its factual content was independently re-verified (`routes_retirees.py:152-154` unconditional `touch` per active enrollment vs `routes_ops.py:157-163` `_phase_msp_refresh` `continue`ing when the recomputed pair is unchanged) because pass-3 claims had proved fallible elsewhere. **(E)** — adjudicated from source in pass 3's favour: the `isinstance` guard is real, so the rung-2 sentence stands.

Pass 4 integrity report: §4 endpoint table 47 rows; §5 error catalogue 47 rows, 47 unique, ending at `ERR_PAYMENT_EXCEEDS_BALANCE | 422`; 25 headings matching `PRD_FINALIZED.md` with no renumbering and no new sections; duplicate-sentence scan clean; no mid-sentence damage at any edit site; both JSON envelope fenced blocks intact.

**Orchestrator verification:** independently re-checked the final artifact — `PRD_COMPLETED.md` 491 lines, md5 `d313161377f871a0f2b73214906725b0` differing from `PRD_FINALIZED.md`'s `790bdce0e26600db1407e250e515499e` (so the scan is not the no-op failure mode); `diff` shows 120 changed/added lines; §4 table holds 47 endpoint rows (49 lines incl. header + separator) and §5 holds 47 error rows ending at `ERR_PAYMENT_EXCEEDS_BALANCE | 422`; file tail is a complete table row. `find -newer results.1.json` over `implementation/`, `test_suite/` and `test_helpers/` returns nothing — no source file was touched after the clean 8-round sweep, so the green result still stands over the delivered code.

**PIPELINE COMPLETE.** All nine steps finished; `workspace/PRD_COMPLETED.md` written.
