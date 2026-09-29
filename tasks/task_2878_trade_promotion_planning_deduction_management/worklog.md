# Worklog — task_2878_trade_promotion_planning_deduction_management

## Step 1: Create task directory — 2026-09-05T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2878_trade_promotion_planning_deduction_management` and `workspace/`. Index pre-assigned (2878) by the orchestrating command; no scan of ./tasks/ performed, per instructions (concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-05T12:40:00.000Z

All three scaffold artifacts are complete and the lint is clean.

## Files
- `/home/ubuntu/github/CodingPRD/tasks/task_2878_trade_promotion_planning_deduction_management/SCAFFOLD.yaml` — 3264 lines, §1.0–§1.7 only (no `scaffold_difficulty_design` / `scaffold_corner_design` key)
- `.../SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2022 lines, single key `scaffold_difficulty_design`
- `.../SCAFFOLD_CORNER_DESIGN.yaml` — 7147 lines, single key `scaffold_corner_design`

## Lint verdict (run from repo root)
```
Coverage
  §1.5 endpoints declared:    67
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     86
  Calls scanned (§1.8+§1.9):  1345

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Surface
13 entities (TradeProgram, Brand, Customer, BudgetAllocation, Promotion, PromotionTactic, RetailerDocument, VolumeFact, AccrualEntry, Deduction, Dispute, PostEventAnalysis, ComplianceAudit) · 67 endpoints · 14 calculations · 62 error codes · 6 roles (5 opaque staff + `entity_backed:Customer` portal) · profile: flat / cyclic / segregation_of_duties / immediate / expert_plus, layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers.

## §1.8 — 9 rules × 2 instances = 18
dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant.

## §1.9 — all nine guide sections, 103 instances (86 recipes + 17 `excluded_because` stubs)
entities 13 · state_machines 16 · calculations 14 · validations 10 · endpoints 6 · errors 25 · rbac 8 · cross-cutting complexity layers 9 · consistency model 2. Verified programmatically: all 62 §1.6 error ids are triggered somewhere across §1.8+§1.9; all instance names unique across both design files; every stub cites a real §1.8 instance name and carries no `test_recipe`.

## Design adjudications
1. Added `POST /trade-marketing/tactics/{tacticId}/cancel` plus a PLANNED→CANCELLED transition so `ERR_TACTIC_STATE_INVALID` is reachable (a line can be cancelled off a still-DRAFT promotion, so priority 43 passes while 44 fires).
2. Widened validation priority 43 to admit analyze from "ENDED **or** ANALYZED", otherwise `ERR_ANALYSIS_ALREADY_EXISTS` (p65) is permanently shadowed by `ERR_PROMOTION_STATE_INVALID`.
3. Added five filtered-list GETs purely for FK reverse-reachability (lint check f).
4. Chose `claim_type: error_triggerable` for the whole `errors` section — the claim-extraction guide gives that section no table of rows.
5. Skipped the `reconciliation` calculations row as genuinely N/A: `PostEventAnalysis.baseline_method` is pinned at first analysis and never switched.
6. OCC fields may not carry literals, so `stale_allocation_version_outranks_allocation_approval_state` captures version 2 from a *different, approved* allocation and applies it to a DRAFT allocation at version 1 — genuinely stale and still `${var}`-bound.
7. Kept every instance name neutral (no word matching the lint's `_NEGATIVE_NAME_RE`) so setup chains stay fully role/payload-checked; negativity is marked per call with `captures: { err: $.data.error_id }`. One legacy name (`allocation_rejects_a_brand_...`) was renamed to `allocation_needs_a_brand_from_its_own_program` for this reason.
8. Normalized all 17 stubs to the SKILL's canonical shape (`name` + `claim_type` + `grounds` + `excluded_because{difficulty_instance, rationale}`); 14 had claim_type/grounds nested inside `excluded_because` and no `name`.

One handoff note: `SCAFFOLD.yaml`'s `scenario:` block contains the verbatim "Generate task harder than expert level!" line as instructed. Per the known leak path, strip that single line before Step 3 so it cannot reach PRD.md.

**Orchestrator note:** acted on the handoff — deleted line 8 (the difficulty directive) plus its trailing blank line from `SCAFFOLD.yaml`'s `scenario:` block. Verified `grep -c "harder than expert" SCAFFOLD.yaml` == 0. The directive therefore cannot reach PRD.md.

## Step 3: Copy shared files — 2026-09-05T12:42:07.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T13:00:00.000Z

PRD generation complete.

**Output:** `workspace/PRD.md` — **501 lines / 112,302 bytes**, built in 6 verified increments (Write + 5 `cat >>` heredocs; line counts 154 → 206 → 252 → 288 → 324 → 358 → 501). File ends at the completed §5 error table, not mid-sentence.

**Section list**
- §1 Introduction (3 paragraphs, no numbered subsections)
- §2 Global Specifications & System-Wide Principles — 2.1 User and Role-Based Access Control; 2.2 API Response Structure (byte-verbatim, confirmed by string equality against the skill's fixed block); 2.3 Pagination; 2.4 Common Resource Properties, Audit Stamps and the Logical Clock; 2.5 Money, Volume and Rounding Discipline; 2.6 Optimistic Concurrency Control; 2.7 Flat Addressing and Reference Resolution; 2.8 The Order in Which Rules Are Evaluated; 2.9 Ledger Conservation and Cascade Propagation; 2.10 Segregation of Duties and the Compliance Penalty Ledger; 2.11 The Fiscal Week: Monday Alignment and Half-Open Windows
- §3 Business Logic & Workflows — 10 domain-named subsections: 3.1 programs/brands/retailers, 3.2 allocations + units invariant, 3.3 promotion plan + off-invoice allowance, 3.4 calendar protection + rate maintenance, 3.5 retailer paperwork + coverage, 3.6 director review, 3.7 volume facts/activation/accrual ledger, 3.8 deduction intake→settlement, 3.9 disputes/aging/resolution, 3.10 post-event analysis + compliance audits
- §4 API Endpoint Definitions (intro + table)
- §5 Error Code Catalogue (intro + table)

**Hard Contract 1 — Field-Name Coverage: PASS.** Required set = 120 entity field names ∪ 85 endpoint identifiers (path params + request inputs) = 146 distinct identifiers. All 146 appear inside backticks in §1–§3 prose; **0 missing** (verified twice, once before §4/§5 existed so the tables cannot be doing the work).

**Hard Contract 2 — Rule Coverage: PASS.** All 52 validations appear as an explicit 52-rung priority ladder in §2.8 (rung count mechanically confirmed = 52) and are restated at their workflows in §3. All 62 error identifiers appear in §1–§3 *prose*, not only in the §5 table (0 missing). All 13 state machines / 50 transitions covered — every from/to state appears in backticks. All 14 calculations expressed as prose formulas with rounding, ordering and boundary semantics; all 17 numeric constants present (10000.00/50000.00 tiers, 0.000/0.020/0.035 rates, SHIP_LEAD_DAYS 14, 0.9000/1.0000, 4/2 weeks, ROI_FLOOR 1.0000, 90 days, 10/5/10/10/25 points), plus MAX_REVISION_ROUNDS 2, MAX_DISPUTE_ROUNDS 2, WRITE_OFF_SELF_APPROVAL_LIMIT 500.00, FEATURE_COOLDOWN_DAYS 7, TPR cap 2. All 6 roles named. Both OCC rules and all four dual-variant calculations documented with symmetric treatment of each branch.

**Hard Contract 3 — §3 Path Purity: PASS.** Zero backticked tokens in §3 begin with `/`, contain `/trade-marketing`, or start with an HTTP method; zero bare method words (GET/POST/PATCH/PUT/DELETE) anywhere in §3; zero slash-path substrings. §3 uses role + action-verb + state-transition framing throughout.

**Table structure:** §4 = 67 rows, exactly 4 columns (every row `|`-count 5), matching the scaffold's 67 endpoints exactly — no missing, no extras. §5 = 62 rows, exactly 2 columns (`|`-count 3), no duplicates, every HTTP status matching the scaffold, no invented codes.

**Adjudications**
1. **`analysisId` has no not-found code.** The scaffold's priority-20 existence check omits `analysisId` from its resolution list and the catalogue has no `ERR_ANALYSIS_NOT_FOUND`. §2.7 therefore lists only the 12 path variables that map to named 404s, and `analysisId` is instead introduced in §3.10 as the read handle. No code was invented.
2. **§3 subsection count is 10, above the skill's 5–9 guidance.** Deliberate: 13 entities and 52 rules would not fit 9 sections without compressing rule statements. Rule coverage was prioritised over the soft count.
3. **`finding_code` / `recovery_amount` are endpoint inputs, not ComplianceAudit fields** — documented in §3.10 as the record-finding payload feeding `findings_count` and `recovery_claim_amount`.
4. **Withheld files were never opened.** `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were not read, grepped, or referenced; no sibling task directory was read. A leakage grep for `test_recipe`/`difficulty`/`expert_plus`/`corner case`/`SCAFFOLD` returns nothing, and a fuzzy-word grep (appropriate/reasonable/etc./TBD/approximately/where applicable) returns nothing.

**Orchestrator truncation check (per the known doc-generator failure mode):** independently verified — `wc -l` = 501, `tail` shows the file ending on the final `ERR_ACCRUAL_BALANCE_INSUFFICIENT | 422` table row of §5 (a real section boundary, not mid-sentence). `grep -ci "harder than expert|expert_plus|test_recipe|scaffold"` = 0, so the Step 2 difficulty directive did not leak. No regeneration needed.

## Step 6: Generate implementation — 2026-09-05T13:55:00.000Z

(Steps 5 and 6 ran concurrently; Step 6 returned first, so its entry is recorded first. Step 5's entry follows below.)

Smoke server on port 21878 killed by its listener PID (2656563, resolved via `ss -ltnp`); port confirmed closed. `__pycache__` dirs removed, so the implementation dir contains only source.

## Deliverable

`workspace/implementation/`

| module | lines |
|---|---|
| app.py | 81 |
| calc.py | 590 |
| db.py | 134 |
| errors.py | 147 |
| response.py | 67 |
| services.py | 268 |
| validators.py | 312 |
| routes/__init__.py | 0 |
| routes/allocations.py | 143 |
| routes/analyses.py | 90 |
| routes/audits.py | 135 |
| routes/common.py | 107 |
| routes/deductions.py | 462 |
| routes/documents.py | 144 |
| routes/ledger.py | 233 |
| routes/programs.py | 252 |
| routes/promotions.py | 291 |
| routes/tactics.py | 308 |
| **total** | **3764** |

Plus `start.sh` (guarded pip install, then `exec python3 app.py`, honours `$PORT`) and `requirements.txt` (`flask==3.0.3`).

**Endpoints: 67 implemented = 67 declared.** The PRD table has exactly 67 rows (incl. `POST /_clock/set_current_utc`); route decorators count 67 across 9 blueprints — programs 12, allocations 4, promotions 9, tactics 6, documents 5, analyses 4, ledger 7, deductions 14, audits 6.

**Storage.** One in-process `Store` of 13 dicts keyed by UUID (`db.py`), empty on every boot. No SQLite, no file/JSON dump, no /tmp cache, and no seeding, preloading or hardcoded entities anywhere — verified by re-reading `app.py` (nothing runs at import beyond `create_app()`).

**State machines.** Each entity carries two independent axes: stored lifecycle (`Promotion.lifecycle_status`, `Deduction.status`, `Dispute.status`, `Tactic.status`, `Customer.trading_status`/`audit_status`, `ComplianceAudit.status`) versus derived posture/health (`allocation.posture` = FROZEN > RESTRICTED > OPEN, `promotion.spend_status`/`spend_ratio`, `performance_flag`, `commitment_verified`, `aging_days`). Derived values are pure functions in `calc.py` recomputed on every read; only genuinely historical facts are stored (`_ever_overspent`, `overspend_event_count`, `compliance_penalty_points`, `revision_round`, `round_count`, PostEventAnalysis figures). The two cyclic loops are round-capped from stored counters (revision <= 2, dispute negotiation <= 2 sends, `round_count` never reset by the return leg). Batch sweeps (`run_activation`, `run_aging`) live in `services.py` and process rows in `created_at`/`opened_at` ascending order, activation before ending, so a wholly-past promotion traverses APPROVED -> LIVE -> ENDED in one call.

**Calculations.** All money is `Decimal` with `ROUND_HALF_UP`; `q2`/`q3`/`q4` helpers, per-line rounding before summation (tactic subtotal, weekly accrual breakdown). Dual-variant paths are single functions branching on the stored discriminator: accrual SHIPMENT (+14-day effective period, EDI 856 facts) vs CONSUMPTION (no shift, EDI 852), deduction valuation EVIDENCE_BASED (verified units x sum of live TPR rates) vs AGREEMENT_CAP (accrual balance), analysis TRAILING (4-week / 4) vs SEASONAL (brand constant). Time uses a logical clock (`db.clock_dt`, default 2026-08-01Z, settable) kept separate from wall-clock `created_at`/`updated_at`; weeks are half-open Monday-aligned. The four-hop cascade (promotion -> allocation -> customer -> analysis) is centralised in `services.apply_spend_cascade`/`rescore_customer`/`recompute_analysis`, and `db.touch()` is idempotent per row per request via `flask.g`, so version bumps land only on rows the PRD says are touched.

**Validation-priority ordering.** `validators.authenticate()` runs rungs 1-3 and `portal_guard()` rung 4 before any body parsing; every handler then evaluates the ladder in explicit PRD order with the rung number as an inline comment — shape/enum/range (rung 10) -> FK resolution in canonical order (rung 21) -> optimistic version (rungs 30/31) -> state (rungs 40-49) -> authority/SoD (rungs 50-53) -> uniqueness/scope (rungs 60-67) -> window/geometry (rungs 70-75) -> capacity and business ceilings (rungs 80-98). Counter-intuitive orderings are preserved and commented (81 after 73/74/80; 50 before 51; 95-98 last; 41 before 43 on submit; 47 before 53 on settle; 64 before 70 on volume facts). First failing rung wins because each raises immediately.

**py_compile: OK for all 18 .py files** (`python3 -m py_compile` over every module printed no errors -> `PY_COMPILE_OK`). `tail -15` on each file previously confirmed every module ends at a real structural boundary; files are unchanged since.

**Smoke test.** Booted once on PORT=21878 from `start.sh` and driven through three end-to-end passes (~150 assertions) covering the full happy path plus negative/ladder cases. Verified live figures: allowance banding (subtotal 12000.00 -> rate 0.020 -> total 12240.00), per-line accrual breakdown in created_at order (1800.00 + 3000.00 = 4800.00), SHIPMENT lead shift accepted at period 2026-08-17/2026-08-10 and correctly refused with `ERR_ACCRUAL_WINDOW_MISMATCH` at 2026-08-24 (effective date == exclusive window end), reversal mirror entry, EVIDENCE_BASED valuation (1500.00/900.00/0.00) and AGREEMENT_CAP valuation (600.00/600.00/4400.00), overspend cascade (ratio 1.5 -> OVERSPENT -> allocation posture RESTRICTED, overspend_event_count 1 -> customer 10 points -> CREDIT_HOLD -> subsequent promotion create refused `ERR_ALLOCATION_POSTURE_RESTRICTED`), dispute loop (2 sends then `ERR_DISPUTE_ROUND_LIMIT`), aging sweep at 111 days -> ESCALATED, +5 points, recovery/write-off ceilings, revision cap, DISPLAY exclusivity, FEATURE cooldown, TPR capacity, portal scoping (own data 200, foreign filter 403), audit findings, and pagination/param/auth error envelopes. Every deviation flagged by my scripts traced back to a wrong expectation in the script, not the implementation: the `tactic patch` case (window_start strictly in the future, so rung 75 must not fire), a `settle`/`dispute` sequence that assumed a credit hold which never occurred (ratio was 0.75), and the RESTRICTED-allocation promotion create above. No implementation change was needed after these runs.

## Step 5: Generate unit tests — 2026-09-05T14:35:00.000Z

Stage 1 and Stage 2 are complete and verified. Task root: `/home/ubuntu/github/CodingPRD/tasks/task_2878_trade_promotion_planning_deduction_management`

## Files delivered (12,146 lines total)

`test_helpers/` (Stage 1, 3,412 lines): `__init__.py` 41, `api_client.py` 361, `api_errors.py` 159, `assertions.py` 548, `constants.py` 120, `factories.py` 411, `fixtures.py` 1151, `test_users.py` 144, `types.py` 477

`test_suite/` (Stage 2, 8,734 lines): `conftest.py` 95, `test_01_programs_and_reference_data.py` 497, `test_02_allocations_and_ledger.py` 812, `test_03_promotion_planning_and_tactics.py` 778, `test_04_promotion_lifecycle.py` 796, `test_05_tactic_window_exclusivity.py` 598, `test_06_documents_and_commitment.py` 331, `test_07_volume_facts_and_accruals.py` 1051, `test_08_spend_status_and_analysis.py` 594, `test_09_deductions_and_validation.py` 807, `test_10_disputes_and_recovery.py` 834, `test_11_compliance_audits_and_penalties.py` 418, `test_12_error_ladder_and_precedence.py` 354, `test_13_rbac_and_concurrency.py` 769

## Tests

**138 test functions (149 collected cases after parametrization).** Queue A (difficulty): 45 tests. Queue B (corner): 93 tests.

## Coverage against the two design indices

- Difficulty index: 18 instances, 0 stubs — **all 18 covered, every one with >=2 tests** (several with 3).
- Corner index: 103 instances, 17 `excluded_because:` stubs -> 86 live — **all 86 covered with >=1 test**; no stub was translated.
- 104 distinct instances tagged = 86 + 18. Zero missing, zero duplicated, zero unresolvable tags.

**Instances skipped: none.** All 104 passed the PRD-first two-condition filter.

## Verification results

- `python3 -m py_compile` on all 22 `.py` files: **clean**.
- `pytest --collect-only`: **149 collected, 0 collection errors** — every import, fixture name and client method resolves.
- C4 (AST-checked): 138/138 tests have exactly one `Design:` line and it is the last line of the docstring. No untagged, no dual-tagged.
- C1: all **392** `PRD: "..."` quotations machine-verified as literal substrings of `workspace/PRD.md` — **0 non-verbatim**.
- No duplicate test function names across files. Every file ends at a complete statement.
- Zero occurrences of "scaffold" in any test or helper file.
- `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation` — no test dirs leaked there. `workspace/implementation/` was never read by me or any translator. `worklog.md`, `PRD.md` and the SCAFFOLD yamls are unmodified. `__pycache__` removed.

## Notable narrowings (asserted less than the index inferred, per the silence rules)

Nine assertions were dropped or weakened because the PRD does not declare the field or pin the value: `BudgetAllocation.approved_at`, `Promotion.submitted_at`, promotion-level `open_deduction_amount` (it is a Customer rollup), `Customer.recovered_ytd_amount`, `Deduction.write_off_amount` (the PRD stores it on the Dispute), post-write-off `Dispute.recovered_amount`, per-transition `version` arithmetic in a two-hop activation run, a post-rescore `credit_hold_reason`, and `updated_at` in the refused-cascade proof.

Two index/PRD divergences resolved in the PRD's favour: the corner index expected `accrual_method_default == CONSUMPTION` from a create that omits the field, but PRD §3.1 yields `SHIPMENT`; and the display-fee amortisation instance is only derivable on the `CONSUMPTION` basis, so that promotion is created with the basis explicit. One index setup was corrected because it would have tripped a different rule: the write-off cascade named the dispute's own opener as approver, which PRD §3.9 refuses with `ERR_SEGREGATION_OF_DUTIES`, so it now uses the distinct alternate specialist.

## Step 7: Run tests and iterate — 2026-09-05T15:35:00.000Z

Clean. Scratch server stopped, `worklog.md` untouched, storage is in-memory only, no stray test dirs.

## Summary

**Iterations run:** 2 (each a full 8-round parallel sweep under `setsid`).

- Iteration 1: 126/149 passed, **23 failures identical in all 8 rounds** (fully deterministic — no flakiness anywhere in the suite).
- Iteration 2: **149/149 passed in all 8 rounds.**

### Tests deleted
None. All 23 failures were either symbol/usage bugs in the test artifact or one genuine implementation defect.

### Assertions removed under STEP 1c (partial coverage)
- `test_suite/test_07_volume_facts_and_accruals.py` — removed the 4 `assert entry["effective_period_start"] == ...` lines (and the matching `AccrualEntry` TypedDict key in `test_helpers/types.py`). **COMPUTED-FIELD SILENCE:** the PRD names "the effective period" only as a formula intermediate in §3.7 (the 14-day shift and the `ERR_ACCRUAL_WINDOW_MISMATCH` check); the sentence enumerating the persisted entry ("The posted entry has `entry_type` `ACCRUAL`, `status` `POSTED`, its `fact_units` and `amount`... `tactic_line_amounts`... `method`... `reverses_entry_id` and `reversal_reason`") never exposes it as a response attribute, so a faithful reader could correctly omit it. Each test's substantive assertions (`method`, `fact_units`, `amount`, `period_start`, and the promotion ledger) were kept and all pass — the shipment-vs-consumption divergence is still fully exercised.

### Fixes applied to `test_suite/`
- `test_04_promotion_lifecycle.py`, `test_05_tactic_window_exclusivity.py`, `test_06_documents_and_commitment.py` — 14 references of the form `ApiErrorId.ERR_TPR_CAPACITY_EXCEEDED` rewritten to `ApiErrorId.TPR_CAPACITY_EXCEEDED`. The `ApiErrorId` enum members are unprefixed (the `ERR_` prefix lives in the `.value`), so these 13 tests died at `AttributeError` before ever reaching the server. Pure symbol-name correction — every asserted `error_id` string is unchanged.
- `test_10_disputes_and_recovery.py` — 5 call sites did `promotion = setup_approved_promotion(...)` and then `promotion["id"]`, but that fixture returns the **context** dict (`program`/`brand`/`customer`/`allocation`/`promotion`), which is how the other 7 call sites in the suite use it. Appended `["promotion"]`. This was the whole `KeyError: 'id'` cluster.

### Fixes applied to `test_helpers/`
- `types.py` — dropped the now-unused `effective_period_start` key from the `AccrualEntry` TypedDict (cosmetic; `total=False` meant it had no runtime effect).

### Fixes applied to `implementation/`
- `routes/programs.py`, `lock_program()` — after repostering every child allocation to `FROZEN`, now rescores each distinct affected customer via `services.rescore_customer()` (added the `import services`). PRD §2.10 states the score is "**recomputed** whenever an allocation's posture changes" and that "Allocations in `FROZEN` posture contribute nothing — a year-end program lock is not the retailer's fault", so a year-end lock must take back the 10 points a `RESTRICTED` cell had scored. The existing `calc.customer_penalty_points()` was already a correct pure recompute over current posture; only the lock path failed to invoke it. Verified live: points 10 -> 0 while `trading_status` correctly stays `CREDIT_HOLD` ("only ever moves it forward").

No implementation check was removed or weakened, no endpoint/field/side-effect was added without a verbatim PRD sentence, no skip/xfail was introduced, and no exact `error_id` assertion was downgraded.

**Orchestrator verification (per the known "clean sweep with no artifacts" failure mode):** independently confirmed all 8 `workspace/implementation/results.$i.json` exist and each reports `passed == total == 149`. Step 8 therefore does NOT skip — Step 7 applied 1 `implementation/` fix (`routes/programs.py::lock_program`) plus test-artifact fixes.

## Step 8: Finalize PRD — 2026-09-05T15:50:00.000Z

Done. `PRD_FINALIZED.md` written.

## Line counts
- `PRD.md`: 501 lines / 112,302 bytes
- `PRD_FINALIZED.md`: 501 lines / 113,681 bytes (**0.0% line delta**, +1.2% bytes — three sentences appended inline, no structural change)

## Changes
- **§3.1 (program lock)** — insert — the year-end lock, after reposturing every child allocation to `FROZEN`, re-scores every distinct customer named by those allocations as a full §2.10 recompute (so a `RESTRICTED` cell's 10 points come back out), `trading_status`/`credit_hold_reason` only ever move forward, and an unchanged customer is not written so its `version` does not move — `routes/programs.py:112-135`, `services.py:15-31`, `calc.py:156-168`
- **§3.2 (posture axis)** — revise — the enumeration of system-driven posture moves no longer implies that only the move into `RESTRICTED` re-scores; a move into `FROZEN` re-scores too, and `FROZEN` contributes nothing — `calc.py:175-181`, `services.py:15-31`
- **§3.7 (posted accrual entry)** — insert — the entry's `period_start` is the **requested** week on both bases, and the effective period is a computation intermediate only (line selection + rung 72), never stored on the entry nor present in its representation, so no `effective_period_start` attribute is returned — `routes/ledger.py:139-164`, `calc.py:502-518`, `services.py:164-191`
- Not patched (pure test-artifact bugs, no PRD silence): `ApiErrorId.ERR_TPR_*` symbol renames (`test_helpers/api_errors.py:68` already carries the `ERR_` prefix in `.value`), the `setup_approved_promotion(...)["promotion"]` call sites (`test_helpers/fixtures.py:484-500` returns the context dict), and the cosmetic `AccrualEntry` TypedDict key drop.

## Per-edit pre-edit search log
**Edit 1 — §3.1 lock re-score**
- (a) Subject: customer penalty re-scoring, `compliance_penalty_points`, `trading_status`/`credit_hold_reason` advancement, and customer `version` bumps.
- (b) Enumerated/read: `services.rescore_customer` (the only re-score primitive; recomputes from scratch, `touch()` only when points or trading_status changed), all four call sites — `services.apply_spend_cascade` (overspend hop 4), `services.run_aging` (escalation, uses the returned `changed` flag for `customers_penalized`), `routes/audits.py:119-134` (issue-findings; touches the customer for `audit_status` *and* then re-scores), `routes/programs.py:131-134` (the Step 7 fix); plus `calc.customer_penalty_points` (all three populations), `calc.allocation_posture` (only FROZEN/RESTRICTED sources), `routes/programs.py:252-263` (manual credit hold), `calc.customer_out`. Grepped for every `rescore_customer`/`compliance_penalty_points` occurrence.
- (c) Adjustments: scoped the "version does not move when nothing changed" clause **to the lock paragraph only**, because `issue_findings` touches the customer row unconditionally for `audit_status` before re-scoring — a global claim would have contradicted that path. Dropped an earlier draft phrase asserting the score always *falls* in favour of "a full recompute from current state" (the re-score can also raise points via disputes/audits). Omitted any statement about the order in which customers are re-scored (impl iterates allocation insertion order and de-dupes; the outcome is order-independent, so pinning an order would have been an unverifiable claim).

**Edit 2 — §3.2 `FROZEN` also re-scores**
- (a) Subject: which allocation posture transitions trigger a customer re-score.
- (b) Enumerated: `calc.allocation_posture` (FROZEN from `program.status == LOCKED`, RESTRICTED from `overspend_event_count >= 1`, else OPEN), every writer of `overspend_event_count` (`services.apply_spend_cascade` only) and of `program["status"]` (`routes/programs.py:lock_program` only) — confirming lock is the *sole* producer of `FROZEN`; `routes/allocations.py` approve/create paths do not move posture.
- (c) Adjustment: wrote "A move into `FROZEN` re-scores that customer just as much" rather than naming the lock endpoint, keeping §3.2's derived-axis framing intact and consistent with `posture` being recomputed on read.

**Edit 3 — §3.7 effective period not exposed**
- (a) Subject: the accrual entry's persisted/serialised field surface and the effective period.
- (b) Enumerated: `routes/ledger.py:145-157` (posted row keys), `routes/ledger.py:212-224` (REVERSAL mirror row keys — copies the original's `period_start` and `method`, also no effective field), `calc.accrual_out:502-518` (the single serialiser for both entry types), `services.accrual_context`/`accrual_components` (where `effective` lives and dies — used for tactic-line selection at `services.py:183`), rung-72 check at `routes/ledger.py:142`, and `list_accruals` filters (`promotion_id`, `reverses_entry_id`, `entry_type`, `status` — no period-derived filter). Repo-wide grep for `effective` found only `effective_from_period` on tactics, an unrelated field.
- (c) Adjustment: phrased the negative as "neither stored on the entry nor carried as a field of the entry's representation" so it covers the REVERSAL mirror as well as the posted entry, and explicitly kept the effective period's two live roles (line selection, rung 72) so the sentence cannot be read as deleting the 14-day shift.

## Step 9: Complete PRD — 2026-09-05T16:35:00.000Z

**Orchestrator decision (recorded per the AUTONOMY directive):** Step 9 was run as **three sequential passes partitioned by implementation module** over one shared, cumulatively-edited `PRD_COMPLETED.md`, rather than as a single subagent. Rationale: `implementation/` is 3,764 lines across 18 modules and the PRD is 501 lines / 113 KB — a single-shot exhaustive scan reliably degenerates into a near-no-op (the known failure mode is a byte-identical `PRD_COMPLETED.md`). Pass 1 owned the `cp`; passes 2 and 3 were explicitly forbidden from re-copying, and each was told which prior edits to preserve. Partition: P1 = app/db/errors/response/validators/routes{common,programs,allocations}; P2 = calc/services/routes{promotions,tactics,documents}; P3 = routes{ledger,deductions,analyses,audits}.

### Pass 1 — global envelope, auth/RBAC, programs, allocations

`cp PRD_FINALIZED.md PRD_COMPLETED.md` performed; `cmp` confirmed no longer byte-identical. 501 lines / 113,681 chars -> 502 lines / 117,309 chars (+3,628 chars; the +1 line is a new §5 table row). 16 edits: **12 ambiguity-pins, 4 mismatch-revisions.**

- §2.1 — revise — mismatch — ownership list dropped "allocation's `customer_id`"; no program/brand/budget-allocation endpoint admits a portal caller, so such a call dies at the role rung with `ERR_ROLE_NOT_PERMITTED`, not as a scope violation — `routes/allocations.py:94,101`, `routes/common.py:9-16`
- §2.1 — insert — ambiguity — a header carrying only whitespace also counts as absent (`ERR_UNAUTHENTICATED`) — `validators.py:44`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 upper-case letters/digits — `response.py:10,21`
- §2.2 — insert — ambiguity — `api_request_timestamp` comes from the host wall clock, not the logical clock — `response.py:27`, `db.py:66-69`
- §2.3 — insert — ambiguity — undeclared query params refused with `ERR_INVALID_REQUEST`; a declared param with an empty value is treated as omitted; non-integer `limit`/`offset` is 400; single-resource reads ignore query strings — `validators.py:261-282`, `routes/programs.py:94`
- §2.3 — insert — ambiguity — all orderings realised through the server's monotonic insertion sequence, which is also the tie-break for `period_start`/`opened_at` orderings — `db.py:101,129-130`, `routes/common.py:88-101`
- §2.4 — insert — ambiguity — one request advances a row's `version` by at most 1 however many effects touch it; `created_at`/`updated_at` are wall-clock stamps — `db.py:109-126,96-106`
- §2.4 — insert — ambiguity — the clock may be set to any instant (forwards or backwards), is echoed as a `current_utc` field of `data`, and `CustomerPortalUser` may not call it — `routes/programs.py:54-61`
- §2.5 — insert — ambiguity — integral JSON numbers (`12.0`) count as integers; instants take 1-9 fractional digits or none; numbers-as-strings and non-object bodies are malformed; an operation with no input fields rejects any body field; bodies parsed as JSON regardless of `Content-Type` — `validators.py:73-104,158-174,220-235`
- §2.5 — insert — ambiguity — an optional field sent as `null` is treated as omitted (takes the default, never clears a stored value) — `validators.py:123-124,141-142`; cross-checked `routes/tactics.py:252-256`
- §2.7 — revise — mismatch — path-variable and not-found enumerations now include `analysisId` / `ERR_ANALYSIS_NOT_FOUND` — `routes/common.py:76-77`, `errors.py:26`
- §2.8 rung 40 — revise — mismatch — rung 40's scope now also covers a second lock aimed at a program no longer `OPEN` — `routes/programs.py:117-118`
- §3.1 — insert — ambiguity — re-locking an already-`LOCKED` program is refused with `ERR_PROGRAM_LOCKED` (409) — `routes/programs.py:117-118`
- §3.1 — insert — ambiguity — customer registration is *not* gated by the program lock (unlike brand registration) — `routes/programs.py:196-207`
- §3.1 — insert — ambiguity — manual credit hold needs a `reason` of >=1 char and refuses a customer already `CREDIT_HOLD`/`SUSPENDED` with `ERR_CUSTOMER_CREDIT_HOLD` (409) — `routes/programs.py:255-259`
- §3.2 — insert — ambiguity — allocation approve tests the program lock before the allocation status; an already-`APPROVED` cell is refused with `ERR_ALLOCATION_NOT_APPROVED` (409) — `routes/allocations.py:135-140`
- §4 — insert — mismatch — trailing slashes address the same endpoint; an unlisted path is `ERR_INVALID_REQUEST` at 404 and an unmatched method `ERR_INVALID_REQUEST` at 405 — the only two cases where that identifier carries a status other than §5's 400 — `app.py:28,49-65`
- §5 — insert — mismatch — added the missing `ERR_ANALYSIS_NOT_FOUND` | 404 row (catalogue had 62 of the 63 ids in `errors.STATUS`) — `errors.py:26`

Verified programmatically that every other `error_id`/status pair in `errors.STATUS` matches §5 exactly.

### Pass 2 — calculations, cascades, promotions, tactics, documents

No re-copy (confirmed); all pass-1 and Step 8 edits verified still present. 502 lines / 117,309 chars -> 502 lines / 122,615 chars; 11 distinct lines touched, all in-paragraph. 15 edits: **13 ambiguity-pins, 2 mismatch-revisions.**

- §2.1 — revise — mismatch — the portal scope-before-existence rule was blanket; scoped it to where the customer identity is in the request (customer path id, `customer_id` filter), and pinned that promotion/deduction/dispute reads resolve the row first so an unknown id gives that resource's 404 — `routes/promotions.py:120-121` vs `routes/programs.py:226`
- §2.4 — insert — ambiguity — resolved "almost every resource carries `version`": the volume fact is the sole exclusion, carrying `created_at` alone — `calc.py:490-499`
- §2.6 — insert — ambiguity — both expected-version fields are whole numbers >= 0 checked at rung 10, so negative/fractional values are `ERR_INVALID_REQUEST`, not a stale-version refusal — `routes/promotions.py:71`, `routes/tactics.py:233`
- §2.7 — insert — ambiguity — identifier-valued list filters resolve (not-found, not an empty page); the promotion list resolves `allocation_id` -> `brand_id` -> `customer_id` — `routes/promotions.py:144-153`
- §2.10 — insert — ambiguity — one re-score applies both thresholds in sequence (ACTIVE -> SUSPENDED in a single pass), the SUSPENDED move never rewrites `credit_hold_reason`, and an unchanged re-score does not write the row — `services.py:15-31`
- §3.3 — insert — ambiguity — the unused one of `rate_per_case`/`fixed_fee` reads back as null rather than being absent — `calc.py:464-465`
- §3.4 — revise — ambiguity — tactic patch: all five fields optional so a version-only patch is a legal no-op that still bumps both versions; contention checks exclude the line itself; the forward-only test uses the *post-patch* `window_start` at `00:00:00Z` (clock exactly on it fails); supplying an unchanged rate/fee is not a change; `effective_from_period` takes the post-patch Monday — `routes/tactics.py:228-287`
- §3.5 — revise — mismatch — `received_at` was described as requiring three fractional digits; it accepts any precision §2.5 admits, is echoed with exactly three, and is constrained to no window — `routes/documents.py:53`, `calc.py:484`
- §3.5 — insert — ambiguity — an illegal `doc_class`/`doc_type` pairing is `ERR_INVALID_REQUEST` at rung 10, before `promotionId` resolves — `routes/documents.py:57-61`
- §3.5 — insert — ambiguity — a document attach does not write the promotion row (no `version`/`updated_at` move); verify is the operation that does — `routes/documents.py:79-80` vs `:140-143`
- §3.6 — insert — ambiguity — `change_notes`, `withdraw_reason` and `cancel_reason` are stored for audit but are not fields of any response body — `calc.py:426-473`
- §3.6 — insert — ambiguity — the withdrawal un-accrued refusal shares `ERR_PROMOTION_STATE_INVALID` with the lifecycle refusal, and a reversed-only accrual still blocks withdrawal because gross survives reversal — `routes/promotions.py:263-266`
- §3.7 — insert — ambiguity — the activation sweep only moves tactic lines under a promotion that is `LIVE` when the run reaches it; lines of `APPROVED`, `ENDED` or `ANALYZED` promotions are not revisited — `services.py:209-210`
- §3.7 — insert — ambiguity — every promotion pricing/ledger/spend/flag figure is derived on read and never stored, so a relative's change (e.g. a cascaded analysis recompute) shows up without the promotion's `version` moving — `calc.py:426-456`
- §3.9 — insert — ambiguity — `disputes_scanned` counts all candidates examined; `disputes_escalated` is in scan order; `customers_penalized` de-duplicates and omits customers whose re-score changed nothing — `services.py:244-268`

### Pass 3 — ledger, deductions, disputes, analyses, audits

No re-copy (confirmed); pass-1/pass-2 markers verified intact (§3.7 "computation intermediate only", §3.7 activation-sweep `LIVE`-scoping, §3.9 `disputes_scanned`, §2.1 `ERR_ROLE_NOT_PERMITTED`, §2.4 volume-fact "`created_at` alone", §2.10 re-score sequencing + `FROZEN` clause, `analysisId`/`ERR_ANALYSIS_NOT_FOUND` in §2.7 and the extra §5 row — 134 table rows vs 133 in FINALIZED). Section-heading count unchanged at 28; `tail -5` still ends on the §5 error table. 502 lines / 122,615 chars -> 502 lines / 126,819 chars. 17 edits: **13 ambiguity-pins, 4 mismatch-revisions.**

- §3.7 — insert — ambiguity — volume-fact intake does no cross-coherence check: `brand_id`/`customer_id` need not share a program, and `source` is never reconciled against `fact_type` — `routes/ledger.py:65-85`
- §3.7 — insert — ambiguity — a week with no matching fact and/or no window-covering live line still posts (`fact_units` 0, empty `tactic_line_amounts`, `amount` 0.00) rather than being refused — `services.py:171-191`
- §3.7 — revise — ambiguity — the reversal mirror copies `period_start` and `method` verbatim from the reversed entry, and the response is HTTP 201 — `routes/ledger.py:212-233`
- §3.8 — insert — ambiguity — `deduction_date` is any calendar date: no Monday alignment, no clock or window comparison — `routes/deductions.py:76`
- §3.8 — insert — ambiguity — `supersedes_deduction_id` is a pure back-reference (any customer, any status, target's `status`/`version` untouched; only feeds the list filter) — `routes/deductions.py:81-82,100`
- §3.8 — revise — mismatch — "Four conditions guard it **beyond** the state check" was backwards: rung 31 sits *ahead* of rung 47, so a replayed non-`MATCHED` claim with a stale version reports `ERR_STALE_PROMOTION_VERSION`; an unmatched claim has no version to compare and falls to the state refusal — `routes/deductions.py:206-210`
- §3.8 — revise — ambiguity — deduction list: a portal caller omitting `customer_id` is implicitly scoped to its own customer — `routes/deductions.py:129-133`
- §3.9 — revise — ambiguity — dispute list has no `customer_id` filter; portal caller omitting `deduction_id` is implicitly self-scoped, and a supplied `deduction_id` resolves first (404 before 403) — `routes/deductions.py:333-338`
- §3.9 — insert — ambiguity — `packet_notes` and `write_off_reason` are stored but are **not** fields of the dispute representation — `calc.py:541-556` vs `routes/deductions.py:309-310`
- §3.9 — revise — mismatch — the newly created dispute row carries `version` 1 (PRD said "the dispute's `version` ... incremented by 1") — `routes/deductions.py:296`
- §3.9 — revise — mismatch — write-off ordering: the rung-88 amount ceiling is evaluated **after** both authorisation gates, so an over-ceiling 600.00 from a specialist reports `ERR_WRITE_OFF_APPROVAL_REQUIRED` — `routes/deductions.py:417-428`
- §3.9 — revise — mismatch — recovery writes only the dispute and the deduction (not promotion/allocation); a recomputed analysis row's own `version` moves — `routes/deductions.py:395-406`
- §3.9 — revise — ambiguity — the aging sweep never writes the parent deductions: an escalated dispute's claim keeps `DISPUTED` and its `version` — `services.py:250-263`
- §3.10 — revise — ambiguity — `promo_consumption_units` and `post_period_units` are the only whole-number volume figures, and `promo_consumption_units` is 0 in the `INSUFFICIENT_DATA` branch (previously unlisted) — `services.py:98,102-115`
- §3.10 — insert — ambiguity — audit scope bounds need not be Monday-aligned; `scope_end <= scope_start` is `ERR_INVALID_REQUEST` 400 at rung 10 (never `ERR_WINDOW_NOT_WEEK_ALIGNED`), reported ahead of an unresolvable `customerId` — `routes/audits.py:45-47`
- §3.10 — revise — ambiguity — `finding_code` is a 1-120-char label validated then discarded (no finding resource, returned nowhere); `recovery_amount` may be 0.00 — `routes/audits.py:106-107,114`
- §3.10 — revise — ambiguity — the per-customer audit list is `created_at` ascending and accepts its own optional `status` filter (contrast the cross-customer DESC list) — `routes/audits.py:70-77`

Behaviors checked and found already uniquely pinned (no change): all four rung orderings on accrual post (43->66->70->72); `MATCHABLE_LIFECYCLES`; both valuation bases and their preconditions; settlement's non-recompute of the analysis and its exact three-row version set; `MAX_DISPUTE_ROUNDS` round-cap semantics with the non-resetting return leg; `WRITE_OFF_SELF_APPROVAL_LIMIT` inclusivity; `aging_days` floor-division and the inclusive 90-day threshold; the whole `compute_analysis_values` chain including both baseline variants, the clamped cannibalization and the null-`roi` rule; `analyze`'s lifecycle-then-uniqueness order; audit issuance's `FINDINGS_OPEN` + 10-point re-score.

### Step 9 totals and orchestrator verification

**48 edits across three passes — 38 ambiguity-pins, 10 mismatch-revisions.** `PRD_FINALIZED.md` 501 lines / 113,681 chars -> `PRD_COMPLETED.md` 502 lines / 126,819 chars (**+13,138 chars, +11.6%**; +1 line, the §5 `ERR_ANALYSIS_NOT_FOUND` row).

Independently verified by the orchestrator: `cmp` shows `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md` (so the scan genuinely ran); `tail` shows the file ending on the final `ERR_ACCRUAL_BALANCE_INSUFFICIENT | 422` row of §5, a real section boundary; `grep -ci "harder than expert|expert_plus|test_recipe|scaffold"` = 0, so no directive or scaffold leakage; all 8 `results.$i.json` still report 149/149; `worklog.md` exists only at the task root (no stray copies drifted into `workspace/`). Pipeline complete.
