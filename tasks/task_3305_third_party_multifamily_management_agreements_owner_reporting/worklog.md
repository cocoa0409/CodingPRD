# Worklog — task_3305_third_party_multifamily_management_agreements_owner_reporting

## Step 1: Create Task Directory — 2026-09-30T18:55:00.000Z

Pre-allocated task directory verified at ./tasks/task_3305_third_party_multifamily_management_agreements_owner_reporting/ with workspace/ inside (created per command-args; no new index computed, no other task_* directory created).

## Step 2: Generate Scaffold — 2026-09-30T19:17:00.000Z

All three files written, lint clean, additional self-consistency checks pass. Summary:

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_3305_third_party_multifamily_management_agreements_owner_reporting/SCAFFOLD.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_3305_third_party_multifamily_management_agreements_owner_reporting/SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_3305_third_party_multifamily_management_agreements_owner_reporting/SCAFFOLD_CORNER_DESIGN.yaml`

## Counts

| File | Contents |
|---|---|
| SCAFFOLD.yaml | 14 entities, 80 endpoints, 22 error codes, 8 calculations, 8 state machines, 10 validation priorities, 5 roles, 3 OCC concurrency rules |
| SCAFFOLD_DIFFICULTY_DESIGN.yaml | 9 rule groups x 2 instances = **18 difficulty instances** (all §0.5 rules at max differentiation) |
| SCAFFOLD_CORNER_DESIGN.yaml | **32 corner instances** across 9 guide sections (entities 5, state_machines 5, calculations 4, validations 4, endpoints 2, errors 3, rbac 3, cross_cutting 4, consistency 2); 754 total calls scanned |

## Lint verdict (verbatim)

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Additional replay checks I ran beyond the linter: placeholder closure (zero unbound `${var}` across 754 calls), instance-name uniqueness across both design files, grounds resolvability against §1.1–§1.6 (all resolve), error-catalog coverage (every error triggered by at least one validation/transition/OCC rule), RBAC role closure, and forbidden race-vocabulary scan (clean).

## Design decisions worth noting

- **Complexity profile**: ledger_reconciliation (primary) + compliance_audit (secondary); layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers; approval_chain role model with segregation-of-duties on budget decisions. Sits at the Expert band (14 entities, 80 endpoints — endpoint count is high because lint check (f) required 10 filtered-list reverse-reachability GETs; the business surface itself is ~45 endpoints).
- **Dual-variant calculations on different domains**: CASH vs ACCRUAL fee basis (MonthlyStatement) and OWNER/SHARED/MANAGER indemnification splits (Claim), plus cash/accrual NOI variants for the annual incentive.
- **Combinatorial modes (a) and (c)**: staffing allocation with cross-property regional pool + pinned two-step rounding (mode a); annual NOI incentive with normatively pinned evaluation order that changes the integer result if reordered (mode c).
- **Non-linear machines**: Budget reforecast create-with-supersede cycle; ManagementAgreement suspend/resume revert loop with staffing compensation cascade.
- **Cascades**: disposition -> agreement termination -> vendor termination (depth 3); statement close -> report generation + distribution waterfall (depth 2).
- **All fixture arithmetic was executed in Python before pinning literals** (e.g., 570240 payroll charge, 375000 fee tail, 384000/388000 cash-vs-accrual fees, 40000 NOI incentive, 27800000/29800000 distribution conservation figures).
- **Logical clock**: `POST /mgmt/_clock/set_current_utc` with the mandated fixed default `2026-09-01T00:00:00Z`; all fixture dates sit after it, and month-end gating plus annual December settlement are driven by clock + `advance_month` epoch endpoint.
- **Boundary probes**: strict `>` EGI threshold (equality yields 0, +10 cents yields exactly 1 cent after round_half_up) vs inclusive 10% owner-override band (220000 allowed, 220001 rejected) — different metrics, different endpoints, different comparison directions.

Orchestrator verification: all three files confirmed on disk (1565 + 1805 + 1794 lines), YAML parses, endpoint count = 80 confirmed. NOTE: 80 endpoints exceeds the >40 overshoot threshold in memory — Step 6 prompt will include explicit per-file write discipline and on-disk verification requirements.

## Step 3: Copy Shared Files — 2026-09-30T19:18:00.000Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-09-30T19:25:00.000Z

All checks pass. Final summary:

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3305_third_party_multifamily_management_agreements_owner_reporting/workspace/PRD.md` — 329 lines.

**Sections:**
- §1 Introduction (3 paragraphs)
- §2.1 Roles & RBAC · §2.2 Response envelope (verbatim block) · §2.3 Pagination · §2.4 Logical clock & epoch · §2.5 Common resource properties (incl. ClaimSettlement exception) · §2.6 Nested retrieval (+ path-param names) · §2.7 Monetary precision · §2.8 OCC (3 rules) · §2.9 Ledger & cash · §2.10 Validation priority order
- §3.1 Owners/Properties · §3.2 Agreement lifecycle · §3.3 Onboarding · §3.4 Budgets/reforecast/SoD · §3.5 Pricing/override band · §3.6 Monthly cycle (fee, incentive, staffing, NOI) · §3.7 Termination/disposition/fee tail · §3.8 Reports/distributions/lender · §3.9 Claims/settlement
- §4 Endpoint table (80 rows, 4 columns) · §5 Error catalogue (22 rows, 2 columns)

**Coverage checks (all PASS):**
- Field coverage: 94 required names (entities + request bodies + query/path params), 94 present in backticks, 0 missing.
- Rule coverage: all 9 state machines' transitions with preconditions/side-effects expressed; all 8 calculations (fee, incentive, annual NOI with pinned eval order, staffing two-step rounding with constants 4/0.20/0.32, owner distribution with 20000000/15000000 floors, fee tail with 6-month lookback, onboarding net position, claim shares with 100000000 cap and 0.25 shared pct) rendered in prose; all 3 OCC rules named (endpoint + `expected_*_version` + `ERR_STALE_VERSION`/412); validation priority ordering stated in §2.10; MAX_OVERRIDE_BAND_PCT 0.10 inclusive-boundary rule stated.
- Path purity: 0 path/method tokens in §3.
- All 22 error IDs mentioned in prose and tabulated; all state enum values present; 80/80 endpoints in §4.

Orchestrator verification: PRD.md confirmed on disk (329 lines, 106 table rows). Design files were withheld per protocol.

## Step 5: Generate Unit Tests — 2026-09-30T19:45:00.000Z

Generation complete for task_3305.

**Files written**
- `test_helpers/`: `types.py`, `api_client.py` (56 endpoint methods), `api_errors.py` (22 error IDs + status map registered), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (shared headers + `make_owner_rep_headers` entity-backed builder), `fixtures.py` (`setup_managed_property` full-stack composite + budget/pricing/claim helpers), `__init__.py`
- `test_suite/`: `conftest.py` + 10 test files (test_01…test_11)

**Test counts**: 68 test functions — 36 Difficulty-tagged, 32 Corner-tagged.

**Coverage audit (Stage 2 self-check)**
- All 18 difficulty instances have ≥2 tests each (18 rules' instances × 2).
- All 19 non-stub corner instances have ≥1 test each; no `excluded_because` stubs exist in this corner index (verified programmatically).
- Zero unknown/dangling Design tags; zero `skip`/`skipif`/`xfail` markers; zero "scaffold" references in generated code.
- Verbatim citation pass: every docstring quote contains an ≥8-word substring surviving a normalized grep of PRD.md (0 failures).

**Instances skipped**: none — all 37 instances passed the PRD-first filter and were translated.

**Notes / deliberate adaptations**
- `occ_stale_version_on_agreement_activate` setup uses the create-version (its YAML's "stale = current−1, fresh = current" arithmetic applied to the actual captured version).
- `annual_noi_incentive` asserts the pinned 40000-cent result via the `advance_month` response's `annual_noi_incentive` field (the only observation point the API exposes for the settlement); a below-hurdle companion test accepts 0-or-absent for the zero case.
- `claim_reserve_hold_and_release` restates (rather than re-generating) to recompute the report's distribution after settlement, matching the recipe's trigger sequence.

Orchestrator verification: subagent's "19 non-stub corner instances" figure contradicted the source — actual corner index has 32 instances (verified by parsing SCAFFOLD_CORNER_DESIGN.yaml directly: entities 5, state_machines 5, calculations 4, validations 4, endpoints 2, errors 3, rbac 3, cross_cutting 4, consistency 2; 0 stubs). Grep of test_suite/ Design tags confirms 36 Difficulty-tagged (18 instances × 2) + 32 Corner-tagged (32 instances × 1) = 68 tests — full instance coverage; only the subagent's summary number was wrong. All 12 test_suite files + 9 test_helpers files compile clean with py_compile.

## Step 6: Generate Implementation — 2026-09-30T19:55:00.000Z

Done. Implementation complete at `/home/ubuntu/github/CodingPRD/tasks/task_3305_third_party_multifamily_management_agreements_owner_reporting/workspace/implementation/`.

Files:
- `start.sh` — guarded pip install, `exec python3 app.py`, PORT env, 0.0.0.0.
- `requirements.txt` — Flask.
- `app.py` — Flask app, blueprint registration, error handlers.
- `db.py` — in-memory Store, UUIDs, logical clock (default `2026-09-01T00:00:00Z`).
- `errors.py` — all 22 error IDs with exact HTTP statuses.
- `response.py` — envelope (`meta`/`response_type`/`data`), pagination (`limit`/`offset`/`total_count`/`has_more`, defaults 10/0, max 100).
- `middleware.py` — X-User-ID/X-User-Role auth, RBAC, body field validators, month helpers.
- `calc.py` — round-half-up money; basis revenue, base/incentive fee, staffing allocation (two pinned roundings), fee tail, owner distribution waterfall, annual NOI incentive, claim settlement shares.
- `routes_owners.py` — Owners, Properties (incl. disposition lifecycle), Agreements (activate/suspend/resume/terminate/complete_termination with OCC + cascades).
- `routes_onboarding.py` — Onboarding pipeline (INTAKE→…→ACTIVATED/ABORTED), Residents, VendorContracts (resolve, window validity).
- `routes_budgets.py` — Budgets with REFORECAST OCC create, SoD on approve/reject, SUPERSEDED cascade.
- `routes_pricing.py` — Pricing windows, half-open overlap, override band ±10% inclusive, live-window withdraw guard.
- `routes_staff_ledger.py` — StaffPositions, LedgerEntries (signed amounts, cash effects on collection).
- `routes_statements.py` — OPEN preview, close with period guard + fee/payroll freeze + cash + report cascade, restate with books-locked check.
- `routes_reports.py` — DRAFT→GENERATED→DELIVERED, distribution grace window, distribution posting as EXPENSE entry.
- `routes_claims.py` — Claim lifecycle, reserve hold/release, OCC settle, settlement shares, ClaimSettlement endpoints.
- `routes_clock.py` — `set_current_utc`, `advance_month` (expiry, December NOI settlement, lender-overdue).

Boot check: server boots via `bash start.sh` on a test port; verified end-to-end smoke (owner→property→agreement→OCC activate→onboarding pipeline→MANAGED→ledger→statement guard `ERR_STATEMENT_PERIOD_OPEN`→clock set→close with correct base fee 500000 / incentive 100000 / total 600000), auth 400/403, 404, pagination envelope, and `advance_month`. All 15 modules pass `python3 -m py_compile`. No seed data; store starts empty.

Orchestrator verification: 17 files confirmed on disk (16 .py + start.sh + requirements.txt; 2787 total .py lines), all compile clean, start.sh is executable. Isolation rule was included verbatim in the prompt (subagent read only INSTRUCTION.md, SCAFFOLD.yaml, PRD.md).

## Step 7: Run Tests and Iterate — 2026-09-30T20:12:00.000Z

All 8 rounds pass: 66/66 in every round. Clean sweep achieved.

Summary:

- **Iterations run:** 3 sweeps (initial diagnosis sweep + 2 verification sweeps after fixes). Final sweep: all 8 parallel rounds at 66/66 passed, 0 failed, 0 errors.

- **Tests deleted (2):**
  1. `test_10_ops.py::TestAnnualNoiIncentive::test_annual_noi_incentive_mode_c_pinned_evaluation_order` — COMPUTED-FIELD SILENCE: the test asserted the `POST /mgmt/advance_month` response body carries an `annual_noi_incentive` field equal to 40000. PRD §3.6 covers the pinned evaluation-order formula verbatim, but no PRD sentence names any response field, ledger entry, or cash effect through which the annual incentive value is observable; additionally "when the epoch advance closes a December period" does not uniquely map to the test's Jan→Feb advance (the natural Dec→Jan advance reading yields no settlement on that call). Two-reader divergence on both channel and timing. Scaffold rule: `calculations/annual_noi_incentive` (trigger: advance_month when period_month is December).
  2. `test_11_compensating.py::TestClaimReserveConservation::test_claim_reserve_hold_and_release_conserves_distributable_cash` — UNIQUE-DERIVABILITY collapse (contradictory composed formulas): the held-state distribution assertion (27800000) requires reading §3.9's "cash available is reduced by reserved_amount_cents" and §3.8's waterfall "minus the claim holds" as a single subtraction, while §2.9 defines cash available as already "minus reserves held" — a literal composition double-subtracts (22800000). The released-state assertion (29800000) additionally required a restate→package-distribution-recompute cascade that PRD never states (§3.6 restate recomputes statement fields only). No concrete asserted value in the test was uniquely derivable; the PRD-covered residue (fee computation, settle success) is covered by other tests. Scaffold rule: `Difficulty/compensating_invariant/claim_reserve_hold_and_release_conserves_distributable_cash`.

- **Fixes to `test_helpers/`:** none.

- **Fixes to `implementation/`:** none — the implementation was PRD-faithful on every failing point; both failures were test-side derivability defects.

Orchestrator verification: results.1–8.json all present (fresh, 20:12), each {total: 66, passed: 66, failed: 0, errors: 0}. Test count on disk = 66 (was 68; 2 deletions confirmed). No implementation .py modified after Step 6 (latest mtime 19:55:18, before Step 7's sweeps) — the clean sweep is valid against the current code.

## Step 8: Finalize PRD — 2026-09-30T20:20:00.000Z

All five edits applied cleanly; the diff is exactly five localized line replacements, no other lines touched.

## Summary

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_3305_third_party_multifamily_management_agreements_owner_reporting/workspace/PRD_FINALIZED.md`

**Line counts:** PRD.md 329 lines → PRD_FINALIZED.md 329 lines (0% line-count delta; 5 lines revised inline, no sections added or removed).

### Changes (one bullet per edit)

- **§2.4** — revise — pinned that month advance moves the logical clock to the first day of the next calendar month, that a successful advance returns `epoch_month` (YYYY-MM) and nothing else, defined "closing period" as the month that just ended, and pinned the lender-overdue rule (`status != DELIVERED` and `period_month` strictly earlier than the new epoch month) and its rejection-of-the-advance behavior — `implementation/routes_clock.py:36-46, 92-108`.
- **§2.9** — revise — replaced the "sum of POSTED credits minus charges … minus reserves currently held" derivation (which double-subtracted reserves when composed with §3.9) with running-balance semantics: cash available is the running balance mutated by the guarded transitions — `implementation/calc.py:145-157`, `routes_staff_ledger.py:144-152`, `routes_statements.py:143`, `routes_claims.py:117,164-165`, `routes_onboarding.py:179`, `routes_clock.py:74`, `routes_reports.py:148`.
- **§3.6 (restate paragraph)** — insert — pinned that a permitted restatement recomputes the statement's computed fields only: no cash cascade and no re-generation of report packages; `GENERATED` packages keep their frozen `distribution_amount_cents` — `implementation/routes_statements.py:165-182` (restate calls `_refresh_computed` only).
- **§3.6 (annual NOI paragraph)** — insert — pinned the December trigger (the advance whose new epoch month is January) and the observability channel: when the incentive is > 0, cash available is reduced and a POSTED `EXPENSE` ledger entry is posted with `accrual_month` = the December period and `collected_month` = the new epoch month; the amount is not on the advance response — `implementation/routes_clock.py:65-90`.
- **§3.8 (waterfall paragraph)** — revise — replaced the re-stated derivation with single-subtraction semantics: floor, lender holdback, and claim holds each subtract exactly once from the §2.9 running balance, so a standing hold reduces the distribution by exactly `reserved_amount_cents` (held-state 27800000 math) — `implementation/calc.py:186-201`.

### Per-edit pre-edit search log

1. **§2.4 edit** — (a) subject: advance_month epoch semantics and response. (b) Enumerated: `routes_clock.py` (whole file — advance body, overdue check, response); `db.py:6,22-31` (default clock matches PRD's 2026-09-01); test usages `test_03_agreements.py:75-94` (advance from default clock; under my wording the clock lands 2026-10-01 and the term_end 2026-09-30 agreement expires — consistent), `test_10_ops.py:238-245` (only tolerant `.get("annual_noi_incentive") in (0, None)` — consistent with `{"epoch_month"}` body). (c) Wording scoped to "successful advance returns `epoch_month`" to avoid claiming the body on the error path.
2. **§2.9 edit** — (a) subject: definition of cash available. (b) Enumerated via repo-wide grep for `cash_available`: all 8 mutation sites listed above plus `routes_owners.py:117` (init 0) — every one is a running-balance delta, none re-derives from the ledger; `calc.cash_available_cents` reads the stored value. (c) Removed "minus reserves currently held" from the definition and described it as a running balance moved by the guarded transitions, so §3.9's begin_review hold is the single subtraction.
3. **§3.8 edit** — (a) subject: waterfall composition with cash available. (b) Enumerated: `calc.owner_distribution_cents` (`calc.py:186-201` — single subtraction of claim holds from the stored balance); both computation call sites (`routes_statements.py:155`, `routes_reports.py:124`); surviving compensating test `test_11_compensating.py:17-47` (no-claim baseline 32800000) recomputed against impl and consistent. (c) Stated "each subtract exactly once" rather than a new formula, avoiding any re-definition of the balance itself.
4. **§3.6 restate edit** — (a) subject: restatement side effects. (b) Enumerated: `routes_statements.py:166-182` (restate: `_refresh_computed` + version bump only), `routes_statements.py:124-162` (close: the only report-cascade site), `routes_reports.py:112-129` (explicit generate: the only other `distribution_amount_cents` writer), `routes_reports.py:132-170` (deliver: reads it). (c) Wording says restate "does not re-run generation" and packages keep their value "computed when they were generated" — true for both generation paths.
5. **§3.6 annual NOI edit** — (a) subject: trigger timing and observability of the annual incentive. (b) Enumerated: `routes_clock.py:65-90` (prev-month==12 check, cash debit, EXPENSE entry with `accrual_month=f"{prev_y}-12"`, `collected_month=new_month`); `calc.annual_noi_incentive_cents` (`calc.py:206-258` — formula already verbatim in PRD); surviving test `test_10_ops.py:195-245` (Dec→Jan advance from clock 2027-01-01 — my parenthetical resolves the Jan→Feb ambiguity exactly as impl behaves). (c) Conditioned the payment sentence on "greater than zero" (impl skips zero incentives) and said "not on the advance response" rather than asserting anything about the response body, staying consistent with the surviving tolerant test.

No edits were needed for test_helpers (none were fixed in Step 7), and no behavior was invented beyond what the implementation exhibits.

Orchestrator note: Step 8 was run (not skipped) because Step 7 had 2 test deletions whose reasons named concrete PRD ambiguities; diff verified minimal — exactly 5 inline line replacements, 10 diff lines, both files 329 lines.

## Step 9: Complete PRD — 2026-09-30T20:35:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_3305_third_party_multifamily_management_agreements_owner_reporting/workspace/PRD_COMPLETED.md` is written — a minimal patch over `PRD_FINALIZED.md` (329 lines both; +5,239 chars; 21 edited paragraphs, no new sections).

## Summary

- **Source**: `PRD_FINALIZED.md` (329 lines / 55,872 chars) → `PRD_COMPLETED.md` (329 lines / 61,111 chars, +5,239).
- **Counts**: 19 ambiguity-pins, 3 mismatch-revisions (one mismatch touched both §2.8 and §3.4).

### Changes (section — insert|revise — ambiguity|mismatch — what changed — impl ref)

1. §2.3 — insert — ambiguity — invalid limit/offset → `ERR_INVALID_REQUEST`; sort tie-break `id` asc; `has_more` formula — response.py:56-80
2. §2.4 — insert — ambiguity — clock-set returns `current_utc`; malformed `to_iso8601` → `ERR_INVALID_REQUEST`; rejected advance still moves clock and keeps expiry/NOI side effects (lender check runs last) — routes_clock.py:21-108
3. §2.8 — revise — mismatch — reforecast `expected_base_budget_version` is enforced only when supplied (impl skips check when omitted) — routes_budgets.py:48-49,64-65
4. §3.1 — insert — ambiguity — `distribution_day_of_month` default 10 when omitted or null, range violation → `ERR_INVALID_REQUEST`; `unit_count` non-negative — routes_owners.py:55-59,105-107
5. §3.2 — insert — ambiguity — agreement create: `term_end_date` strictly after `effective_date`, non-negative fee/threshold amounts → `ERR_INVALID_REQUEST` — routes_owners.py:210-215
6. §3.2 — revise — ambiguity — suspension flips only ACTIVE positions; resume restores exactly the suspension-inactivated ones — routes_owners.py:299-328
7. §3.3 — revise — ambiguity — starting onboarding places no precondition on prior posture; balances must be non-negative; `net_position_cents` absent until import — routes_onboarding.py:48-80
8. §3.3 — insert — ambiguity — import balancing entries: `RECOVERY` credits (deposits, prepaid) + `RENT` charge (delinquency), zero amounts skipped, both month keys = takeover month, cash moves by net position — routes_onboarding.py:155-179
9. §3.3 — revise — mismatch — abort allowed only from `INTAKE` (later states → `ERR_INVALID_STATE_TRANSITION`) — routes_onboarding.py:236-250
10. §3.3 — insert — ambiguity — vendor contract `monthly_cost_cents` non-negative — routes_onboarding.py:322-324
11. §3.4 — revise — mismatch — reforecast create: `ERR_REFORECAST_REQUIRES_APPROVED_BASE` on bad/missing base; stale supplied expected version → `ERR_STALE_VERSION`, omitted skips the check — routes_budgets.py:38-50,67-72
12. §3.4 — insert — ambiguity — submitter recorded as `_submitted_by`; SoD compares acting `X-User-ID` string directly against it — routes_budgets.py:146-160,181
13. §3.5 — insert — ambiguity — `final_rent_cents`/`override_rent_cents` null until publication; `recommended_rent_cents` and `override_rent_cents` non-negative — routes_pricing.py:38-39,141-143
14. §3.6 — revise — ambiguity — charge kinds pinned (`RENT/FEE/RECOVERY/EXPENSE/PAYROLL` non-negative, `CONCESSION` either sign); `resident_id` must belong to the property; cash effects pinned: revenue kinds/`CONCESSION` by signed amount when `collected_month` set, `EXPENSE`/`PAYROLL` always deducted at posting — routes_staff_ledger.py:110-152
15. §3.6 — insert — ambiguity — statement open requires posture `MANAGED`/`TRANSITIONING_OUT`; no `period_month` uniqueness; OPEN-statement reads recompute live — routes_statements.py:49-50,78-80
16. §3.6 — insert — ambiguity — fee math uses most recently created agreement regardless of status; no agreement → base and incentive zero — calc.py:55-61,75-83
17. §3.6 — insert — ambiguity — staffing: non-negative hours/cost; zero payroll when no active positions; regional pool = union of the property's active positions' region codes — calc.py:96-140
18. §3.6 — revise — ambiguity — close cascade order pinned: cash reduced first, then package generation computes distribution from reduced cash — routes_statements.py:141-161
19. §3.6 — insert — ambiguity — annual NOI: zero when no agreement / <12 CLOSED statements / no APPROVED ANNUAL budget; expenses keyed by `accrual_month`; revenue summed only over majority-basis statements; 6-6 tie → `CASH`; incentive ledger entry has no `resident_id` — calc.py:206-258, routes_clock.py:65-90
20. §3.7 — insert — ambiguity — non-terminal onboarding blocks completion with `ERR_INVALID_STATE_TRANSITION`; posture `DISPOSED` only when property already `CLOSED`; disposition completion also cascades `ASSIGNED_TO_MANAGER` vendor contracts; expiry boundary = post-advance clock ≥ `term_end_date` — routes_owners.py:370-405, routes_clock.py:50-63
21. §3.8/§3.9 — insert — ambiguity — lender holdback applies when any `LENDER` package for the period exists in any status; delivery window compares day-of-month only; distribution entry months both = `period_month`, no entry when zero; settle only from `UNDER_REVIEW` with non-negative `amount_cents`; no agreement → `ERR_INCIDENT_OUTSIDE_TERM`; `reserved_amount_cents` non-negative; `UNDER_REVIEW` claims cannot be closed — calc.py:186-201, routes_reports.py:132-170, routes_claims.py:41-66,126-189

Orchestrator verification: PRD_COMPLETED.md confirmed on disk (329 lines, 61,320 chars vs PRD_FINALIZED.md 56,045 chars; 58 diff lines, all in-paragraph; no new sections — still 5 `##` headings).

Pipeline complete. Final artifacts: SCAFFOLD.yaml + 2 design indices, PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, 66-test suite (36 Difficulty + 30 Corner after 2 PRD-silence deletions), full Flask implementation (17 files, 2787 lines), 8/8 clean stability sweep at 66/66.
