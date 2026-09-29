# Worklog — task_2842_vehicle_sales_incentive_program_administration

## Step 1: Create task directory — 2026-09-05T05:26:03.180Z

Created `tasks/task_2842_vehicle_sales_incentive_program_administration/` and `tasks/task_2842_vehicle_sales_incentive_program_administration/workspace/`. Index 2842 was pre-assigned by the invoker; no scan of `./tasks/` was performed (concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-05T08:05:00.000Z

Subagent summary (verbatim):

Done. All three scaffold artifacts for task 2842 are complete and lint-clean.

## Files

| Path | Lines |
|---|---|
| `.../SCAFFOLD.yaml` | 2424 |
| `.../SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2490 |
| `.../SCAFFOLD_CORNER_DESIGN.yaml` | 6231 |

All three parse under `yaml.safe_load`. Top-level keys: SCAFFOLD.yaml has the §1.0–§1.7 keys only (no `scaffold_difficulty_design` / `scaffold_corner_design`); the two design files each carry exactly one top-level key.

## SCAFFOLD.yaml counts
12 entities, 7 state machines, 3 concurrency_rules, 13 calculations, 31 validations, 49 endpoints, 48 errors, 5 roles. Profile: `pricing_engine` / `ledger_reconciliation`, layers `[dual_variant_calculation, cascading_side_effects, rate_threshold_triggers, optimistic_concurrency]`, topology `graph`, shape `cyclic`, role model `segregation_of_duties`, consistency `immediate`.

## Design indices
- §1.8: 9 rule_ids, **20 instances** (2/2/2/2/2/3/3/2/2).
- §1.9: nine sections exactly as named in `references/claim-extraction-guide.md`, **86 rows = 66 full instances + 20 `excluded_because:` stubs** (every stub's `difficulty_instance` resolves to a real §1.8 instance name). Per section: entities 12, state_machines 14, calculations 15, validations 19, endpoints 7, errors 7, rbac 4, cross_cutting_complexity_layers 6, consistency_model 2.

## Lint verdict (verbatim, final run)
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    49
  §1.1 entities declared:     12
  §1.8 instances scanned:     20
  §1.9 instances scanned:     66
  Calls scanned (§1.8+§1.9):  1394

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Notable findings from this pass
- **Error catalogue is now fully triggerable**: all 48 error ids appear in at least one §1.8/§1.9 recipe (was 15 uncovered before the `errors` section, plus the two stale-version ids covered by the three OCC instances).
- **Two self-consistency defects in SCAFFOLD.yaml fixed while authoring §1.9**: (1) `RetailDelivery` REPORTED→VALIDATED and the UNWOUND cascade recomputed a `DealerObjective`'s derived fields without incrementing `DealerObjective.version`, which made `concurrency_rules.protest-resolve-stale-objective` unreachable by any §1.5 composition — version increments added to both the state machine and the two endpoint side-effect lists; (2) a formula comment cited `validations[priority=17]` for the objective-FINAL gate, which is priority 19.
- Enum/id corrections in the corner file: `ERR_CLAIM_DUPLICATE` → `ERR_DUPLICATE_CLAIM`; a DENIED protest's `resolved_units` is null (not the objective's units); an objective that has had a protest filed sits in PROTESTED, not PROPOSED; the MARGINAL stair-step payout recomputed from the real formula (60000, not 30000×units).
- Two deliberate ambiguities are now pinned by assertions rather than left to the implementer: resolving an already-DENIED protest returns `ERR_PROTEST_ALREADY_RESOLVED` (addressed resource wins over the parent objective's state guard), and `schedule-claims` is transactional all-or-nothing.
- **Heads-up for the next pipeline step**: `SCAFFOLD.yaml`'s `scenario:` still begins with the line `Generate task harder than expert level!` (kept because the task specified the scenario verbatim). Per the known leak path, strip that one line before PRD generation.

### Orchestrator post-step action

Acting on the subagent's heads-up (and the known difficulty-directive leak path), the orchestrator stripped the leading `Generate task harder than expert level!` line plus its blank line from `SCAFFOLD.yaml`'s `scenario:` block (2424 → 2422 lines). `grep -rn "harder than expert"` over the task dir now returns nothing, and SCAFFOLD.yaml still parses under `yaml.safe_load`. The difficulty directive therefore cannot reach PRD.md via the scaffold.

## Step 3: Copy shared files — 2026-09-05T08:07:19.886Z

Copied `INSTRUCTION.md` from the project root to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T08:19:00.000Z

Subagent summary (verbatim):

The PRD is complete and all three hard contracts pass.

**Output:** `.../workspace/PRD.md` — **443 lines**

**Top-level sections in order:**
1. `# Vehicle Sales Incentive Program Administration API — Product Requirements Document`
2. `## 1. Introduction` (3 paragraphs)
3. `## 2. Global Specifications & System-Wide Principles` — 2.1 User and Role-Based Access Control · 2.2 API Response Structure · 2.3 Pagination · 2.4 Resource Identity, Timestamps and the Version Counter · 2.5 Money in Cents, Rates in Basis Points, and the Rounding Contract · 2.6 The Logical Clock and Interval Conventions · 2.7 Request Screening Order: The Validation Ladder · 2.8 Optimistic Concurrency on Programs and Objectives · 2.9 Cascade Discipline and Ledger Conservation
4. `## 3. Business Logic & Workflows` — 3.1 Designing a Program: Money Levers, Eligibility Footprint and Stacking Edges · 3.2 The Approval Gate · 3.3 Dealer Registration, Standing, and Stair-Step Objective Proposal · 3.4 The Protest Cycle · 3.5 Retail Delivery Reporting, Back-Dated Sale Detection and Auditor Validation · 3.6 Claim Submission and the Stacking Waterfall · 3.7 Adjudication: The Payable Amount, Attainment Tiers and Budget Headroom · 3.8 Payment Batches · 3.9 Unwinds, Chargebacks, Accrual and the Program's Books
5. `## 4. Endpoint Definitions` (4 columns, 49 rows = all 49 scaffold endpoints)
6. `## 5. Error Code Catalogue` (2 columns, 48 rows = all 48 scaffold errors)

**Tail confirmed complete:** the file ends at a real section boundary — the last line is the final error row `| ERR_PROGRAM_BUDGET_EXHAUSTED | 402 |`, with no audit footer and nothing mid-sentence.

**Hard Contract Reports**

```
Field coverage check:
- entities[].fields: 109 required, 109 present, 0 missing
- endpoints[].input (request_body + query_params + path-supplied ids): 73 required, 73 present, 0 missing
- output-shape / nested-object identifiers (tier_index, threshold_bps, per_unit_bonus_cents,
  budget_remaining_cents, eligible_program_ids, blocked_program_ids, capped_out_program_ids,
  stacked_total_cents, current_utc, id, created_at, updated_at, version): 13 required, 13 present, 0 missing
- enum members + state values (all entity enums, all transition from/to, all terminal states): 0 missing
- errors[].id: 48 required, 48 present, 0 missing; roles[].name: 5 present
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 31 checked, 31 expressed in prose (full ordered ladder in §2.7, plus
  per-endpoint restatements of the claim-submission and adjudication orders in §3.6/§3.7), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_program_version /
  expected_objective_version + parent version mismatch + exact error_id + HTTP 412 all named; framed purely
  as stale-version, no "simultaneous"/"race" framing), 0 missing
- state_machines[].transitions: 29 checked, 29 fully expressed (all from/to pairs named as UPPERCASE state
  pairs; every precondition paired with its error_id; every side effect stated, including the 3-link
  SUPERSEDED cascade, the 4-link UPHELD cascade, the 4-link UNWOUND cascade, and the round_index-pinned
  DENIED destinations), 0 missing
- calculations[]: 13 checked, 13 fully expressed in operator-free prose with pinned rounding directions and
  all constants embedded in business context (MARKET_APR_BPS 799 as "7.99 percent", CANCEL_RESERVE_BPS 275 as
  "2.75 percent", MAX_TOTAL_UPLIFT_BPS 5000 as "50.00 percent", RESIDUAL_PASS_THROUGH_BPS 6000,
  MAX_REPORT_LAG_DAYS 10, MIN_OBJECTIVE_UNITS 1, MAX_PROTEST_ROUNDS 2, SETTLEMENT_BUFFER_DAYS 1), 0 missing
- validations[] conditions: 31 checked, 31 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 49 endpoints checked, all side-effect sets and all multi-endpoint
  applies_to scopes expressed, 0 missing
- entities[].fields[] structured content: 109 checked, defaults/initial values/sources reconstructible
  (incl. common_fields:false exception for EligibilityRule and StackabilityConstraint — no updated_at, no
  version — stated explicitly in §2.4), 0 missing
- sibling-branch symmetry: 6 groups checked (UPHELD vs DENIED protest resolution; round-1 vs round-2 denial
  destination; MARGINAL vs FULL_VOLUME payout; UNIT_BASED vs TAKE_RATE_BASED accrual; AS_SOLD_SNAPSHOT vs
  REPRICED_CURRENT rate basis; RECOVERED vs WRITTEN_OFF chargeback ledger effect), 6 with equal prose
  density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 918
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Two additional checks: §2.2 was appended by `cat` from `section-2.2-response-structure.md` and diffs byte-identical (only a trailing blank separator line differs). No fuzzy/approximating hedges appear in any numeric context — the only `about`/`around` hits are ordinary English ("anything else about the request", "built around a hard separation").

### Orchestrator post-step verification (anti-truncation guard)

`wc -l` = 443. `tail -25` ends on the final error-catalogue row `| ERR_PROGRAM_BUDGET_EXHAUSTED | 402 |` — a complete table row at a real section boundary, not mid-sentence. Top-level headings present in order: §1 Introduction (L3), §2 Global Specifications (L11), §3 Business Logic & Workflows (L176), §4 Endpoint Definitions (L334), §5 Error Code Catalogue (L390). `grep -ni "harder than expert\|scaffold"` over PRD.md returns nothing — no difficulty-directive leak and no scaffold references. No regeneration needed.

## Step 6: Generate implementation — 2026-09-05T09:00:00.000Z

(Steps 5 and 6 were launched to run concurrently for physical isolation — the impl generator was forbidden to read `test_helpers/` or `test_suite/`. Step 6 returned first; the Step 5 entry follows below.)

Subagent summary (verbatim):

Implementation is complete, compiling, and verified end-to-end. Server reaped — nothing left on port 39842.

## Files (`.../workspace/implementation/`)

| file | lines |
|---|---|
| `start.sh` | 10 |
| `requirements.txt` | 1 |
| `app.py` | 59 |
| `util.py` | 149 |
| `clock.py` | 34 |
| `errors.py` | 112 |
| `db.py` | 47 |
| `response.py` | 78 |
| `middleware.py` | 82 |
| `validate.py` | 188 |
| `serializers.py` | 233 |
| `services/__init__.py` | 0 |
| `services/calc.py` | 501 |
| `services/ledger.py` | 338 |
| `routes/__init__.py` | 0 |
| `routes/helpers.py` | 58 |
| `routes/programs.py` | 546 |
| `routes/objectives.py` | 200 |
| `routes/dealers.py` | 72 |
| `routes/deliveries.py` | 179 |
| `routes/claims.py` | 273 |
| `routes/batches.py` | 207 |
| `routes/clock_endpoint.py` | 20 |

3387 lines total. `python3 -m compileall` clean; `__pycache__` removed. Storage is in-memory dicts only, nothing seeded (fresh boot returns `total_count: 0`).

## Endpoints: 49/49

Enumerated from `app.url_map`: 48 under the `/incentives` prefix (18 program-scoped incl. the 2 objective-under-program routes, 4 objective + 2 protest, 3 dealer, 7 delivery, 6 claim, 2 chargeback, 6 payment-batch) plus the unprefixed `POST /_clock/set_current_utc`.

## Smoke results — 3 suites, 0 failures

- **Suite 1 (30 checks, happy path):** envelope/meta per §2.2, program lifecycle, dealer/delivery/claim/adjudication, batch open→schedule→lock→disburse, accrual arithmetic (145875), unwind cascade, chargeback recovery, pagination. `SMOKE_FAILURES: 0`
- **Suite 2 (26 checks, formulas + cascades):** stacking waterfall with a `CAPPED_TOTAL` pair cap, both OCC guards (stale program + stale objective version → 412), retroactive repricing (`affected_claim_count` 1, `net_adjustment_cents` 20000, claim flips to `REPRICED_CURRENT`), lease residual impact (660 bps via the five pinned floors), objective proposal (basis 10 → 13 units), protest uphold cascade (`resolved_units` 5), MARGINAL stair-step payout 50000, finalize, bonus claim, close. `SMOKE2_FAILURES: 0`
- **Suite 3 (70 checks, validation ladder):** authn→authz→404→shape→body-FK precedence, both segregation-of-duties rules, program-overlap refusal and the `ALLOWED`-edge waiver, `FORBIDDEN` pairing on claim submission, budget exhaustion (402, claim left `SUBMITTED`), back-dated detection (lag 46 → 422), TERMINATED gates vs SUSPENDED pass-through, protest round cap, accrual replay, batch period-overlap/buffer, chargeback applicability. `SMOKE3_FAILURES: 0`

## Two findings worth relaying

1. One real bug found and fixed during smoke 1: `calc.per_unit_spend` compared `claim["claim_type"]` against a tuple of *program* incentive types, so `claimed_units`/`per_unit_spend_cents` stayed 0. Now keyed on `CLAIM_TYPE_UNIT_INCENTIVE`.
2. Two smoke-2/3 "failures" were my own wrong expectations, not defects, and both confirm subtle PRD readings: (a) §3.6 makes the waterfall shared machinery that *hypothetically* accepts higher-ranked candidates before evaluating a candidate, so a lower-ranked program can be legitimately `ERR_STACK_CAP_EXCEEDED` on a delivery that has no claims yet; (b) §3.8's settlement buffer is measured from the new batch's `period_start` back to the nearest preceding same-region `period_end` (must be strictly greater than one day) — not between `period_end` and `scheduled_pay_date`.

`worklog.md` was not touched, and no test directory was read.

## Step 5: Generate unit tests — 2026-09-05T09:20:00.000Z

(Launched concurrently with Step 6; returned second, hence its entry appears after Step 6's above.)

Subagent summary (verbatim):

Test generation is complete for task 2842.

## Output locations (verified)
Both directories are at the **task root**, `/home/ubuntu/github/CodingPRD/tasks/task_2842_vehicle_sales_incentive_program_administration/`. `workspace/` contains only `INSTRUCTION.md`, `PRD.md` and the untouched `implementation/` — no `workspace/test_helpers` or `workspace/test_suite` exists. `__pycache__` cleaned from both dirs.

## `test_helpers/` — 9 files, 2217 lines
`__init__.py` 18 · `api_client.py` 281 (48 endpoint methods) · `api_errors.py` 111 (48 error ids + status map registration) · `assertions.py` 458 · `constants.py` 60 · `factories.py` 306 · `fixtures.py` 546 · `test_users.py` 76 · `types.py` 361

## `test_suite/` — conftest + 18 files, 10572 lines
conftest 71 · t01 427 · t02 381 · t03 368 · t04 454 · t05 450 · t06 470 · t07 459 · t08 299 · t09 421 · t10 902 · t11 1069 · t12 798 · t13 951 · t14 653 · t15 946 · t16 735 · t17 396 · t18 322

## Coverage
- **127 test functions**, **175 collected pytest cases** (parametrization), 0 collection errors.
- **Queue A: 20/20 difficulty instances translated**, every one with >=2 tests (range 2-5). 55 tests.
- **Queue B: 66/66 non-stub corner instances translated**, every one with >=1 test. 72 tests. The 20 `excluded_because:` stubs were **not** translated and all 20 `difficulty_instance` cross-references resolve.
- **SKIPPED instances: none.** Every instance passed the PRD-first two-condition filter.
- Auditor reports **0 problems**: no untagged/dual-tagged test, every `Design:` line is the last docstring line, no unknown-instance or section-mismatch tags, no stub translated, no `skip`/`skipif`/`xfail` markers, no scaffold vocabulary. Full suite compiles.

## Sub-assertions dropped (instance kept, narrower than the yaml recipe)
Roughly a dozen peripheral yaml expectations were dropped as non-uniquely-derivable, most repeatedly the same one: **`approved_amount_cents` on a non-rejected claim** — PRD §3.6 enumerates the fields that begin null and that is not among them, so translators substituted "version unchanged / value unchanged" no-op proofs. Others: dealer-A-reads-dealer-B outcome (PRD §1 vs §2.7 rung 4 conflict), `rate_basis` on a freshly submitted claim, `resolved_by_user_id` on a system-denied protest, re-schedulability of a claim released from a CANCELLED batch, and "the error message names the offending field".

## Design-index defects worth relaying upstream
1. **Every VIN literal in both yaml indices is 16 characters**; the PRD requires exactly 17. Reported independently by 7 of 10 agents. Tests use `factories.unique_vin()` (or a zero-padded variant) since VINs are setup inputs, not asserted outcomes. **The recipes as written cannot create a delivery.**
2. **At least 5 recipes set a clock that back-dates their own `sale_date` literals** (`reporting_lag_days` > 10 -> `back_dated_flag` true -> delivery cannot be validated), so their required VALIDATED preconditions are unreachable. Agents moved the clock; no expected literal depends on it.
3. **Absolute version chains are off by one** in several recipes — they ignore that appending an eligibility rule bumps the owning program's `version` (PRD §2.4). Asserted relationally instead.
4. **Segregation of duties pre-empts the intended error** in two `errors` recipes (they re-adjudicate as the delivery's own validator, so rung 3 fires before the target rung). Fixed by using a third auditor identity.
5. `state_machines/approving_a_successor...` setup would be refused at *submission* with `ERR_PROGRAM_WINDOW_OVERLAP` (the supersede exclusion applies only at approval); the successor was given a non-intersecting footprint.
6. `validations/duplicate_claim_check...` asserts "all four rows persist" but the refused duplicate creates nothing (asserted 3).

## One Stage 1 bug found and fixed
`test_helpers/assertions.py:assert_pagination_meta` asserted `meta["total"]` while the framework's `validate_paginated` emits `total_count` — the helper could never pass. Fixed to `total_count` (plus optional `has_more`). No test called it, so nothing else changed.

### Orchestrator post-step verification

`test_helpers/` (9 files) and `test_suite/` (19 files incl. conftest) both confirmed at the task root; `workspace/test_helpers` and `workspace/test_suite` do not exist. `workspace/` holds only `INSTRUCTION.md`, `PRD.md`, `implementation/`. Proceeding to Step 7.

## Step 7: Run tests and iterate — 2026-09-05T09:24:32.000Z

Subagent summary (verbatim):

Clean. Loop complete.

## Summary

**Iterations run:** 2 (iteration 1 surfaced 8 deterministic failures, identical in all 8 rounds — no flakiness anywhere; iteration 2 was fully green).

**Tests deleted:** none. All 8 failures traced either to a real implementation defect or to a test-side assertion that PRD did not cover; no test needed to be dropped wholesale.

**Fixes applied to `test_suite/`** (2 sites, both narrowing an over-reaching assertion — no weakening of any covered rule):

- `test_16_role_based_access_control.py:727` — `test_a_dealer_writes_freely_on_its_own_rows_and_reads_shared_programs` called `a.assert_claim_amounts(own_claim, 22000, 22000)`, whose 3rd parameter defaults to `None` and therefore silently asserted `approved_amount_cents is null` on a freshly submitted claim. **DEFAULT-VALUE SILENCE**: PRD §3.6 enumerates the claim's creation-time nulls exhaustively — "its `rejection_error_id`, `adjudicated_by_user_id` and `paid_at` are all null" — and never states what `approved_amount_cents` holds before adjudication. Replaced with direct `assert_money` on the two fields PRD does pin (`claimed_amount_cents`, `snapshot_per_unit_cents`). Note the canonical defaults test, `test_10::test_claim_system_fields_start_at_their_declared_defaults`, asserts exactly PRD's null list and deliberately omits this field — confirming the shared helper's default was the accident. This was the only `assert_claim_amounts` caller in the suite.
- `test_18_write_read_consistency.py::_consistency_world` — the fixture kept the approve write body, then submitted a claim (which PRD §3.6 requires to increment "the claimed program's `version` by 1"), so the test's `assert_echoes(world["approved"], approve_read, [..., "version"])` compared a stale write body against a read taken *after* an unrelated intervening write (4 vs 5). Fixture now captures the program read immediately after approval, keeping the assertion an exact write-body-versus-its-own-following-read check including `version`.

**Fixes applied to `implementation/`** (3 files):

- `routes/claims.py::adjudicate_claim` — `adjudicated_by_user_id` was stamped *before* the `ERR_PROGRAM_NOT_ACTIVE`, `ERR_DELIVERY_NOT_VALIDATED`, `ERR_OBJECTIVE_NOT_FINAL` and `ERR_PROGRAM_BUDGET_EXHAUSTED` gates, so a refused adjudication leaked a side effect onto the claim. Violates PRD §2.7 ("no side effect of any kind is applied to any entity once a check fails") and §3.7 ("nothing is written"). Now stamped inside each branch after its gates pass. Fixed 2 tests.
- `routes/programs.py::submit_program` — the three submission preconditions (no eligibility footprint row; `DEALER_STAIR_STEP` with empty `tier_schedule`; `LEASE_SUPPORT` with `residual_support_bps` 0) raised `ERR_INVALID_REQUEST`. Rung 6's `ERR_INVALID_REQUEST` scope is enumerated exhaustively in PRD §2.7 and covers only *payload* screening — submit carries no payload at all, and none of its clauses matches these gates. PRD §3.2 lists them as admission conditions on the program's own state in the same breath as the DRAFT check, making rung 10 the only rung that can carry them → `ERR_PROGRAM_INVALID_STATE` (409, matching the test's stated expectation). Fixed 3 parametrised cases.
- `routes/batches.py::schedule_claims` — the per-claim usability screen ran before the batch's own `OPEN` check, so scheduling an already-`SCHEDULED` claim into a `LOCKED` batch reported `ERR_CLAIM_NOT_VALIDATED` instead of `ERR_BATCH_INVALID_STATE`. Both codes sit on rung 10, but rung 10 screens "the **target resource**" — the batch named in the path — and rung 5 independently orders "the batch before the claims it is asked to schedule". Batch check moved ahead. Verified the other three `ERR_CLAIM_NOT_VALIDATED` assertion sites (test_03, test_11 x2, test_14) all use an `OPEN` batch, so none regressed. Fixed 1 test.

**Final per-round results (iteration 2):** rounds 1-8 all **175/175 passed**, 0 failed, 0 errors.

`worklog.md` untouched (orchestrator-owned); storage remains in-memory dicts only with no seeding and no disk persistence.

### Orchestrator post-step verification (sweep-artifact audit)

Per the known failure mode where a Step 7 agent claims a clean sweep without leaving artifacts, the orchestrator independently re-read the artifacts rather than trusting the claim:

- All 8 `workspace/implementation/results.{1..8}.json` exist, ~56 KB each, mtime 2026-09-05T09:20:07Z (four minutes before this entry).
- Parsed with `json.load`: every round reports `passed=175, failed=0, total=175, errors=0`, each round ~334.6 s wall time — consistent with 8 genuinely concurrent rounds rather than a serialized or partial run.
- Freshness cross-check: the newest edit anywhere in `implementation/`, `test_suite/` or `test_helpers/` is `test_suite/test_18_write_read_consistency.py` at epoch 1788599663 (~09:14:23Z), i.e. every Step 7 fix predates the final sweep's result files. The green sweep therefore reflects the current tree, not a pre-fix run.

Step 7 applied 3 `implementation/` fixes, so Step 8's skip condition does not hold — Step 8 will run with this entry inlined as `<step_7_diff>`.

## Step 8: Finalize PRD — 2026-09-05T09:31:00.000Z

Step 8 was NOT skipped: Step 7 applied 3 `implementation/` fixes and 2 `test_suite/` fixes, so the skip condition (zero fixes of any kind) did not hold. The Step 7 worklog entry above was inlined verbatim as `<step_7_diff>`.

Subagent summary (verbatim):

`$TASK/workspace/PRD_FINALIZED.md` is written. Three paragraphs changed; nothing else in the repo touched.

## Size
- `PRD.md`: 443 lines / 101,447 bytes
- `PRD_FINALIZED.md`: 443 lines / 102,228 bytes
- Line-count delta: 0% (3 of 443 lines revised, 0.68% of lines; +781 bytes, +0.77%)

## Changes
- **§3.2 (Approval Gate) — revise** — the four non-status submission admission conditions (no eligibility footprint row, `effective_to` not later than `effective_from`, `DEALER_STAIR_STEP` with empty `tier_schedule`, `LEASE_SUPPORT` with `residual_support_bps` 0) are now explicitly pinned to `ERR_PROGRAM_INVALID_STATE` (409) and explicitly *not* `ERR_INVALID_REQUEST`; PRD previously named the code only for the `DRAFT`-status check — `implementation/routes/programs.py:340-365`.
- **§3.6 (Claim Submission) — insert** — added `approved_amount_cents` starts at 0 (not null) on a freshly submitted claim, alongside PRD's existing creation-time null list — `implementation/routes/claims.py:90`.
- **§3.8 (Payment Batches) — revise** — moved the batch-`OPEN` sentence ahead of the per-claim usability screen and stated the precedence explicitly: a not-`OPEN` batch reports `ERR_BATCH_INVALID_STATE` even when a named claim is also unusable. PRD's prose previously ordered the claim screen first, which contradicted the impl — `implementation/routes/batches.py:98-117`.

**No edit made** for the `adjudicated_by_user_id` Step 7 item: PRD §2.7 ("no side effect of any kind is applied to any entity once a check fails") plus §3.7 ("nothing is written") already uniquely determine the post-fix behavior — it was a pure impl defect, not a PRD silence. Likewise no edit for the `test_18` fixture fix: §3.6's "the claimed program's `version` increments by 1" already pins it.

## Per-edit pre-edit search log

**Edit 1 — §3.2 submit error code**
- (a) Subject: which error code an unmet program-submission admission condition reports.
- (b) Enumerated: `grep -rn "ERR_INVALID_REQUEST\|ERR_PROGRAM_INVALID_STATE" routes/ services/ validate.py` — all 20 sites read. Confirmed `routes/programs.py:340,348,352,357,361` (submit, all five gates -> `ERR_PROGRAM_INVALID_STATE`); `routes/programs.py:105` (create-time `effective_to <= effective_from` -> `ERR_INVALID_REQUEST`); `routes/programs.py:214,294,298` (eligibility-row / stack-edge payload screens -> `ERR_INVALID_REQUEST`); `routes/programs.py:234,382,397,425,428` (other program state gates); `validate.py:15` (all rung-6 breaches); `routes/deliveries.py:56,60` and `routes/batches.py:34,39` (unrelated payload screens). Also `validate.body()` read to confirm a malformed body still yields `ERR_INVALID_REQUEST` at submit.
- (c) Adjustment: scoped the "never `ERR_INVALID_REQUEST`" claim to *the admission conditions* rather than to the submit endpoint as a whole, so it does not contradict `validate.body()`'s malformed-body 400 at the same endpoint, nor the create-time `ERR_INVALID_REQUEST` on the identical `effective_to`/`effective_from` and `tier_schedule` values (`programs.py:105`, rung 6).

**Edit 2 — §3.6 `approved_amount_cents` default**
- (a) Subject: the value of `approved_amount_cents` on a claim, at creation and thereafter.
- (b) Enumerated: `grep -rn "approved_amount_cents"` across the impl — 20 sites. Writes: `routes/claims.py:90` (creation, 0), `:165` (reject -> 0), `:187` (approve -> computed); `services/ledger.py:208` (supersede cascade rejects `SUBMITTED` claims -> 0), `:277` (upheld protest reduces it to the objective's new `payout_cents`), `:322` (retroactive repricing overwrites it). Reads: `services/calc.py:216-221` (`claim_running_contribution` — a `SUBMITTED` claim's stored 0 is deliberately bypassed in favor of `claim_payable`), `calc.py:473,487`, `ledger.py:27,35,58,82,178`, `routes/batches.py:171`, `routes/claims.py:200,207`. Also `serializers.py:133` (field always emitted, never omitted).
- (c) Adjustment: **material**. My first draft read "only adjudication ever moves that number" — false against `ledger.py:277` (protest uphold) and `ledger.py:322` (repricing), both of which move `approved_amount_cents` outside adjudication, and both already described in §3.4/§3.9. Rewritten to "starts at 0 rather than null, because a claim that has not yet been adjudicated has no approved money", which asserts only the creation-time value and makes no claim about later writers. Also confirmed the stated default does not conflict with `ledger.py:208`, which re-writes 0 over a value already 0.

**Edit 3 — §3.8 batch-state vs claim-screen precedence**
- (a) Subject: the position of the batch `OPEN` check within the schedule-claims screening order.
- (b) Enumerated: `routes/batches.py:91-125` (`schedule_claims`: batch path resolution -> `validate.body()` -> `claim_ids` shape -> per-claim 404 resolution at `:96` -> batch `OPEN` at `:103` -> per-claim usability at `:107-117`), plus every other batch-state gate to make sure the wording stays local: `:133` (lock, `OPEN` + `claim_count >= 1`), `:145` (disburse, `LOCKED`), `:196` (cancel, `OPEN`), and `services/ledger.py:314-328` (repricing's `OPEN`/`LOCKED` branch on a claim's batch). Confirmed `helpers.get_claim` raises `ERR_CLAIM_NOT_FOUND` and runs *before* the batch `OPEN` check.
- (c) Adjustment: kept PRD's "Every named claim must exist." *ahead* of the relocated batch sentence, and qualified the precedence as running before claims are "screened for usability" rather than before claims are screened at all — otherwise the new wording would have wrongly promoted `ERR_BATCH_INVALID_STATE` above the rung-7 `ERR_CLAIM_NOT_FOUND` that `batches.py:96` actually raises first. The region-code and `sale_date` sentences were left byte-identical (their error code is a separate PRD silence with no Step 7 trace, so out of scope here).

### Orchestrator post-step verification

`PRD_FINALIZED.md` exists (102,228 bytes vs PRD.md's 101,447) and `diff PRD.md PRD_FINALIZED.md` is non-empty — three revised lines at 198, 262 and the §3.8 site, matching the reported edits. Tail still ends on the complete error-catalogue table. Not byte-identical, so the Step 8 pass demonstrably ran.

## Step 9: Complete PRD — 2026-09-05T10:00:51.952Z

Step 9 always runs. Per the known failure mode where a single-shot Step 9 produces a PRD_COMPLETED.md byte-identical to its source (the scan never really ran), the orchestrator split it into **three sequential passes partitioned by implementation module**, all editing one shared `PRD_COMPLETED.md` in place. Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden to copy, and each was told the expected pre-pass size so it could detect a clobber. Partition:

- **Pass 1** — `app.py`, `middleware.py`, `response.py`, `validate.py`, `errors.py`, `util.py`, `clock.py`, `db.py`, `serializers.py`, `routes/helpers.py`, `routes/clock_endpoint.py`, `routes/programs.py`, `routes/dealers.py`
- **Pass 2** — `routes/objectives.py`, `routes/deliveries.py`, `routes/claims.py`, `services/calc.py`
- **Pass 3** — `routes/batches.py`, `services/ledger.py`

Each pass handed forward the silences it noticed in modules it did not own, and the receiving pass adjudicated them explicitly.

### Pass 1 summary (verbatim)

Pass 1 of 3 complete.

**File stats**
- `PRD_FINALIZED.md` (source): 443 lines / 102,228 chars
- `PRD_COMPLETED.md` (output): 443 lines / 108,143 chars — **+5,915 chars**, zero line-count change (all edits are in-paragraph)
- Tail intact: file still ends at the complete error-catalogue table (`ERR_PROGRAM_BUDGET_EXHAUSTED | 402`)

**Counts:** 22 ambiguity-pins, 5 mismatch-revisions (27 edits across 23 PRD lines)

**Changes**
- §2.1 — revise — mismatch — an empty `X-User-ID`/`X-User-Role` header is treated identically to an absent one (401), not as a present value — `middleware.py:30-33`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A`-`Z`/`0`-`9` — `util.py:30-32`
- §2.2 — insert — ambiguity — `api_request_timestamp` reads the logical clock, not wall time, so it is identical for every response at one clock reading — `response.py:15-19`
- §2.3 — insert — ambiguity — `offset` has no maximum; an offset past the end yields an empty page; an empty-string `limit`/`offset` takes its default — `response.py:46-66`
- §2.3 — insert — ambiguity — `created_at` ties break by server insertion order, never by id; enum filters 400 on undeclared values while id/`period_month` filters are matched literally with no existence or format check; empty-string filters are treated as omitted — `db.py:45-47`, `validate.py:163-188`, `programs.py:179-188,530-536`
- §2.4 — insert — ambiguity — `updated_at` equals `created_at` at creation — `db.py:33-41`
- §2.4 — insert — ambiguity — responses expose only declared fields; internal bookkeeping (the insertion counter) never appears — `serializers.py:11-23`
- §2.6 — revise — ambiguity — `to_iso8601` is required; the endpoint answers 200 with `data` holding exactly `current_utc`; the clock may be moved backwards — `routes/clock_endpoint.py:14-20`, `clock.py:26-28`
- §2.7 rung 6 — revise — **mismatch** — instants need only a timezone designator: 0-9 fractional digits and `±HH:MM`/`±HHMM` offsets are accepted and canonicalized to 3-digit UTC, sub-millisecond precision truncated (PRD previously demanded "three fractional digits") — `validate.py:84-93`, `util.py:16-19,51-78`
- §2.7 rung 6 — insert — ambiguity — a body-less request screens as an empty payload; non-JSON or non-object bodies are `ERR_INVALID_REQUEST`; a JSON boolean is not an integer — `validate.py:18-27,58-70`
- §2.7 rung 6 — insert — ambiguity — an explicit `null` is treated exactly as omission (takes the default, or reports missing when required) — `validate.py:30-36`
- §2.7 rung 11 — revise — **mismatch** — `ERR_PROGRAM_NOT_ACTIVE` also fires for the superseded program on program approval — `routes/programs.py:400-403`
- §2.9 — insert — ambiguity — an entity's `version` increments by exactly 1 per request however many cascade links touched it — `middleware.py:63-81`
- §3.1 — insert — ambiguity — `name` is required, >=1 char, no upper bound — `routes/programs.py:99`
- §3.1 — revise — ambiguity — `stack_group` is required and non-empty (previously read as a passive label) — `routes/programs.py:109`
- §3.1 — insert — ambiguity — `apr_buydown_bps`, `residual_support_bps`, `projected_take_rate_bps` may not be negative — `routes/programs.py:111-119`
- §3.1 — insert — ambiguity — tier elements: all three keys required, `tier_index` >= 1, `threshold_bps` >= 0, `per_unit_bonus_cents` >= 0 — `validate.py:134-136`
- §3.1 — insert — ambiguity — `stack_cap_cents` may not be negative — `routes/programs.py:120-122`
- §3.1 — insert — ambiguity — appending a footprint row to a non-`DRAFT` program is `ERR_PROGRAM_INVALID_STATE` (409), screened after payload shape and before the conflict check — `routes/programs.py:233-248`
- §3.1 — insert — ambiguity — `trim_code` is 1-16 chars when non-null; MSRP bounds may not be negative and `max` need not exceed `min` — `routes/programs.py:216-224`
- §3.1 — revise — **mismatch** — a stacking edge carries **no** status gate: it may be declared while either program sits in any status (PRD implied draft-only) — `routes/programs.py:282-320`
- §3.1 — insert — ambiguity — `cap_amount_cents` non-negative; a dangling `program_b_id` reports `ERR_PROGRAM_NOT_FOUND` before `ERR_INVALID_STACK_EDGE`; only the path program's `version` moves — `routes/programs.py:289-306,319`
- §3.2 — insert — ambiguity — approval's `supersedes_program_id` gates: `ERR_PROGRAM_NOT_FOUND` / `ERR_PROGRAM_NOT_ACTIVE`, evaluated after SoD+status and before overlap — `routes/programs.py:394-406`
- §3.2 — insert — ambiguity — closure breaches (non-`ACTIVE`, or a `SCHEDULED` claim) both report `ERR_PROGRAM_INVALID_STATE` — `routes/programs.py:424-428`
- §3.3 — insert — ambiguity — dealer `name` required >=1 char no max; `region_code` 1-8 chars; `market_opportunity_bps` non-negative — `routes/dealers.py:27-33`
- §3.3 — insert — **mismatch** — no dealer-standing value is terminal: any value may be set from any other (including reinstating `TERMINATED`), and a no-op set still bumps `version` — `routes/dealers.py:63-72`
- §3.9 — insert — ambiguity — the accrual-uniqueness scope counts only `ACCRUAL` rows (a `REVERSAL` never blocks a period), and a run refreshes `accrued_budget_cents` and bumps the program's `version` by 1 — `routes/programs.py:503-522`, `services/ledger.py:47-48`
- §4 — insert — ambiguity — paths match with or without a trailing slash — `app.py:22`
- §5 — revise — **mismatch** — the catalogue is business errors only; unrouted paths answer `ERR_NOT_FOUND` (404) and undeclared methods `ERR_METHOD_NOT_ALLOWED` (405) — `app.py:36-45`

**Notes for passes 2 and 3:** `routes/claims.py:91` initializes `rate_basis` to `None` at claim creation, which §3.6's list of initial nulls does not mention — left for the pass that owns `claims.py`. `services/ledger.py:124` stamps a `REVERSAL` row's `period_month` from the logical clock's month key, which §3.9 does not pin; I only pinned the accrual-uniqueness scope so as not to encroach.

### Pass 2 summary (verbatim)

PRD_COMPLETED.md pass 2 is complete. Summary below.

## Size
- Before: **108,143 chars** / 443 lines -> After: **111,961 chars** / 443 lines (+3,818). No new sections; every change is an in-paragraph insert or revision.

## Counts
- **ambiguity-pins: 15**, **mismatch-revisions: 6** (21 edits total)

## Changes
- §2.7 rung 7 — revise — mismatch — body FKs now pin that a claim resolves `delivery_id` **then** `program_id`, and add a retail delivery's own `dealer_id` to the list (it was absent, yet a bogus dealer yields `ERR_DEALER_NOT_FOUND`) — `routes/claims.py:42-43`, `routes/deliveries.py:63`
- §2.7 consequences ¶ — insert — ambiguity — rungs 3/4 need a resolvable row, so an unknown objective/claim/`delivery_id` answers the not-found code instead of `ERR_DEALER_MISMATCH`/`ERR_SEGREGATION_OF_DUTIES`, and a delivery payload with no `dealer_id` string falls through to rung 6 — `routes/objectives.py:108`, `routes/claims.py:33-35,139-148`, `routes/deliveries.py:31-33`
- §3.3 — insert — ambiguity — objective assignment does not gate `incentive_type` (non-stair-step programs keep `tier_attained`/`payout_cents` at 0), the (program, dealer) pairing is not unique, and "the matching objective" means the earliest created — `routes/objectives.py:37-43`, `services/calc.py:94-102,360-365`
- §3.3 — insert — ambiguity — the birth-time attainment computation is part of creation, so a new objective returns `version` 1 / `updated_at` == `created_at` — `routes/objectives.py:63`
- §3.4 — insert — ambiguity — `claimed_basis_units` is required and zero or greater — `routes/objectives.py:111`
- §3.5 — insert — ambiguity — delivery `model_code`/`trim_code` both required, 1-16 chars; `customer_region_code` 1-8 — `routes/deliveries.py:38-45`
- §3.5 — insert — ambiguity — `validated_by_user_id` and `unwound_at` start null — `routes/deliveries.py:93-94`
- §3.5 — insert — ambiguity — `back_dated_flag` filter accepts `true`/`false`/`1`/`0` in any case, else `ERR_INVALID_REQUEST` — `routes/deliveries.py:105`
- §3.5 — revise — mismatch — validation credits only objectives **of the reporting dealer** (PRD said "every dealer objective") — `routes/deliveries.py:140`, `services/calc.py:342`
- §3.5 — insert — ambiguity — reject's `reason` is required, >=1 char — `routes/deliveries.py:151`
- §3.6 — insert — ambiguity — an already-accepted candidate appears in none of the three projection lists — `services/calc.py:269`
- §3.6 — insert — ambiguity — a candidate's gross starts from the program's **current** `per_unit_amount_cents` (no snapshot exists yet) — `services/calc.py:202-213`
- §3.6 — insert — ambiguity — the three lists are in the walk's ranked order; a no-candidate delivery still reports the existing claims' `stacked_total_cents` — `services/calc.py:315-321`
- §3.6 — insert — ambiguity — `rate_basis` added to the claim's initial-nulls list (pass 1's deferred item) — `routes/claims.py:91`
- §3.6 — revise — mismatch — the stair-step "most recent VALIDATED delivery" is a convention the server records, not verifies — `routes/claims.py:80-99`
- §3.7 — revise — mismatch — rejection records the supplied `rejection_error_id` or null; no system-derived value on this path — `routes/claims.py:152-166`
- §3.7 — insert — ambiguity — a `STAIR_STEP_BONUS` claim still records the step-one `rate_basis`, and a stair-step candidate with no objective has gross 0 — `services/calc.py:193-199,208-212`
- §3.9 — revise — mismatch — a directly raised chargeback moves the claim to `CHARGED_BACK`/clears the batch only under the three full-recovery reasons; also names the dealer recompute — `routes/claims.py:226-233`
- §3.9 — insert — ambiguity — a direct chargeback whose arithmetic yields <=0 is refused `ERR_CHARGEBACK_NOT_APPLICABLE` (including `OBJECTIVE_REVISED` with no matching objective) — `routes/claims.py:198-222`
- §3.9 — insert — ambiguity — `REPRICING_ADJUSTMENT`'s new amount is recomputed with the basis forced to `REPRICED_CURRENT` in both the pass and the direct path — `routes/claims.py:206`
- §3.9 — revise — mismatch — `residual_impact_bps` refreshes whenever the program's other ledger fields recompute (approval, chargeback, either resolution, unwind), not only approval+unwind — `routes/claims.py:190,232,258`

## Integrity
- Tail intact: file still ends at the complete error catalogue (`ERR_PROGRAM_BUDGET_EXHAUSTED | 402`), 443 lines, char count grew.
- Pass 1 spot-checks both present: §2.2 "`req_` followed by exactly twenty characters..." and §5 "...answers `ERR_NOT_FOUND` with HTTP 404".

## For pass 3 (`services/ledger.py`, `routes/batches.py`)
I read ledger.py only as cross-reference and patched nothing on its behalf. Silences I noticed there:
1. `stair_step_claim_of` (ledger.py:237-254) — §3.4 link three never says *which* stair-step claim an upheld protest recovers against: impl takes the last-created `PAID` one, else the last-created live one. Worse, when none exists (ledger.py:274-282) impl raises no chargeback **and leaves `paid_payout_cents` un-reduced**, while §3.4 states the reduction unconditionally.
2. `append_reversal_row` (ledger.py:120-132) — the REVERSAL row's `period_month` is the calendar month of the **current logical clock**, plus `accrual_method` copied from the program and `unit_basis` 0. This is pass 1's deferred item.
3. `apply_retroactive_repricing` ends with `recompute_program(program, bump=False)` (ledger.py:337), so the repricing endpoint bumps the program's `version` exactly once overall — worth pinning against §2.9.
4. `reverse_claim_payment` -> `recompute_batch(bump=True)` (ledger.py:162-163) bumps the former batch's `version` and rewrites its totals even when that batch is `LOCKED` or `DISBURSED`; §3.8 declares a locked batch immutable only "to retroactive repricing" and is silent on the unwind/chargeback path.

### Pass 3 summary (verbatim)

Pass 3 of 3 complete. All edits were made in place with the Edit tool on the existing `PRD_COMPLETED.md`; no `cp`, no whole-file rewrite.

## Size
- Before: 111,961 chars / 443 lines -> After: **116,629 chars / 443 lines** (+4,668, grew). Tail still ends at the complete §5 error-catalogue table (`ERR_PROGRAM_BUDGET_EXHAUSTED | 402`).
- A line-by-line diff vs PRD_FINALIZED.md confirms I only touched lines 174, 208, 230, 290, 292, 294, 296, 306, 310, 318, 328; every other differing line is untouched prior-pass work.

## Counts
**12 ambiguity-pins, 8 mismatch-revisions** (20 subjects across 11 paragraph edits).

## Changes
- §2.9 — revise — mismatch — "both ... reduce the claim's `approved_amount_cents`" was false for repricing; now only the upheld protest reduces it, the locked-batch repricing leaves even that untouched — `services/ledger.py:320-331`
- §3.2 (closure cascade) — insert — ambiguity — a protest denied by the cascade leaves `resolved_by_user_id` null too, not the closing controller's id — `services/ledger.py:225-230`
- §3.4 link three — insert — ambiguity — pinned *which* stair-step claim: latest-created `PAID` match on `program_id`+`dealer_id`+`STAIR_STEP_BONUS`, else latest-created one neither `REJECTED` nor `CHARGED_BACK` — `services/ledger.py:237-254`
- §3.4 link three — revise — mismatch — when that rule finds no claim, link three raises nothing, `paid_payout_cents` is **left un-reduced** above `payout_cents`, and link four does not run; links one and two still stand — `services/ledger.py:274-282`
- §3.4 link three — revise — mismatch — the claim keeps *whatever* `payment_status` it held (ordinarily `PAID`), since the selected claim can be `UNPAID`/`SCHEDULED` — `services/ledger.py:277-278`
- §3.4 link four — insert — ambiguity — link four also recomputes the dealer's `paid_cents` and `open_chargeback_cents` — `services/ledger.py:282`
- §3.8 buffer check — insert — ambiguity — the "nearest preceding batch" is nearest among the three occupying statuses only; a `CANCELLED` batch is invisible to the buffer check as well as the overlap check — `routes/batches.py:46-61`
- §3.8 schedule-claims — insert — ambiguity — a region mismatch or an out-of-period `sale_date` is refused with the same `ERR_CLAIM_NOT_VALIDATED` and is an equally complete no-op (all four conditions screened before any attachment); an empty `claim_ids` array is accepted; the response body is the batch, not the claims — `routes/batches.py:96-125`
- §3.8 lock — insert — ambiguity — an `OPEN` batch with `claim_count` 0 is refused with `ERR_BATCH_INVALID_STATE` too — `routes/batches.py:133`
- §3.8 lock — insert — mismatch — the locked batch's immutability is repricing-specific: a later chargeback/unwind that detaches a claim still recomputes `claim_count`/`total_cents` and bumps `version`, `LOCKED` or already `DISBURSED` — `services/ledger.py:162-163`
- §3.8 disburse — insert — ambiguity — scheduled claims are paid in `created_at` ascending order and `paid_payout_cents` is overwritten (not accumulated), so a multi-bonus objective ends on the latest-created claim's amount — `routes/batches.py:151-171`
- §3.9 unwind link two — revise — mismatch — a claim with `approved_amount_cents` 0 is still driven to `CHARGED_BACK` and detached, but raises no chargeback and no reversal row — `services/ledger.py:136-137, 178-180`
- §3.9 unwind link four — revise — mismatch — "the matching dealer objective" -> **every** objective the delivery had been crediting (the §3.5 set: `VOID` skipped, two objectives under one program both move) — `services/ledger.py:194-195, 101-113`
- §3.9 unwind link four — insert — ambiguity — the reporting dealer's `paid_cents`/`open_chargeback_cents` and the objectives move on *every* unwind, while the program's figures and `version` move only when link one found a `SCHEDULED`/`PAID` claim — `services/ledger.py:187-192`
- §3.9 partial recoveries — revise — mismatch — the claim keeps exactly the state it held, ordinarily `PAID`/`SCHEDULED`, rather than universally those two — `services/ledger.py:274-278`
- §3.9 accrual ledger — insert — ambiguity — a `REVERSAL` row carries `unit_basis` 0, a copy of the program's `accrual_method` at chargeback time, and a `period_month` = calendar month of the **logical clock at that instant** (not the sale/claim/pay-period month) — `services/ledger.py:120-132`
- §3.9 repricing pass — revise — mismatch — "if the claim's batch is `LOCKED`" -> any batch that has left `OPEN`, including a `DISBURSED` batch still holding the claim in `SCHEDULED`; that batch's totals and `version` also stay put — `services/ledger.py:320-331`
- §3.9 repricing pass — insert — ambiguity — in that branch the claim's own `version` does not move (nothing on it changed); the dealer's `open_chargeback_cents` is recomputed once per charged-back dealer — `services/ledger.py:327-336`

## Verdicts on the four handed-over items
1. `stair_step_claim_of` — **patched, both halves.** Selection rule pinned in §3.4 (ambiguity) and the no-claim case pinned as a mismatch fix: no chargeback, `paid_payout_cents` left un-reduced, link four skipped. Reachability verified: unwinding the paid bonus claim's delivery leaves `paid_payout_cents` set with no `PAID` and no live claim.
2. `append_reversal_row` — **patched** in §3.9's accrual paragraph (§3.9 line 318), covering `period_month`, `accrual_method` and `unit_basis`; `month_key_of` yields the same `YYYY-MM` shape the listing filter takes.
3. Repricing bumps `version` exactly once — **no change needed.** §2.9 already states the increment is "by exactly 1, however many links of the cascade happened to touch that same entity", and §3.9 already says the program's `version` increments by 1 when `per_unit_amount_cents` is overwritten; `recompute_program(bump=False)` at `ledger.py:337` is precisely that single bump, so no interpretation admits a second one. (`middleware.touch` is also idempotent per request, so no other path can double-bump either.)
4. `reverse_claim_payment` -> `recompute_batch(bump=True)` on a `LOCKED`/`DISBURSED` batch — **patched** in §3.8's lock paragraph, scoping immutability to retroactive repricing and stating that a detaching chargeback/unwind still recomputes totals and bumps `version` in either status.

## Prior-pass edits survive (spot-checked three)
- Pass 1 §2.2: `api_request_id` "starts with `req_` followed by exactly twenty characters drawn from ... `A`-`Z` and the digits `0`-`9`" — present.
- Pass 1 §5 (line 392): "a request whose path matches no route at all answers `ERR_NOT_FOUND` with HTTP 404" — present.
- Pass 2 §3.6: "its `rate_basis`, `rejection_error_id`, `adjudicated_by_user_id` and `paid_at` are all null" — present.

No other file was written; `worklog.md`, `PRD.md`, `PRD_FINALIZED.md`, `implementation/`, `test_suite/` and `test_helpers/` were read-only (SCAFFOLD*.yaml and worklog.md never opened), and no server was booted.

### Orchestrator post-step verification (Step 9)

- `PRD_COMPLETED.md`: 443 lines / 116,629 chars, versus `PRD_FINALIZED.md` 443 / 102,228 and `PRD.md` 443 / 101,447. **+14,401 chars over its source.**
- `cmp` against both `PRD_FINALIZED.md` and `PRD.md` reports a difference in each case — the scan demonstrably ran and was not a silent no-op copy.
- `diff PRD_FINALIZED.md PRD_COMPLETED.md` shows 51 changed lines (102 diff lines), consistent with the three passes' reported 27 + 21 + 20 subjects landing as in-paragraph edits on ~51 distinct lines.
- All five top-level sections still present in order (§1 L3, §2 L11, §3 L176, §4 L334, §5 L390) and the file still ends on the complete final error row `| ERR_PROGRAM_BUDGET_EXHAUSTED | 402 |`. No truncation from any pass.
- Step 9 touched no code, so the green sweep recorded in Step 7 still describes the shipped implementation; all eight `results.{1..8}.json` (175/175 each) remain in place.
- Housekeeping: all `__pycache__` directories and `.pyc` files removed from the task tree; `worklog.md` exists only at the task root, with no stray copies under `workspace/`.

## Pipeline complete — 2026-09-05T10:00:51.952Z

Steps 1-9 all executed. Final artifacts: `SCAFFOLD.yaml` (2422 lines, difficulty directive stripped), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2490), `SCAFFOLD_CORNER_DESIGN.yaml` (6231), `test_helpers/` (9 files / 2217 lines), `test_suite/` (19 files / 10,572 lines, 175 collected cases), `workspace/implementation/` (3387 lines, 49 endpoints, in-memory only), and the PRD chain `PRD.md` -> `PRD_FINALIZED.md` -> `PRD_COMPLETED.md`. Test status: 8/8 sweep rounds at 175/175 passed, 0 failed, 0 errors.
