# Worklog — task_3467_federal_building_lease_procurement_occupancy_agreement_billing

## Step 1: Create task directory — 2026-10-02T09:57:15.000Z

Task directory was pre-allocated by the caller at `tasks/task_3467_federal_building_lease_procurement_occupancy_agreement_billing/` with `workspace/` inside; verified it exists and is empty. No new index computed, no other task_* directory created. Difficulty instruction: "Generate task much harder than expert level!" (passed to prd-bench-scaffold-generator).

## Step 2: Generate scaffold — 2026-10-02T10:35:00.000Z

Generated SCAFFOLD.yaml (12 entities, 10 state machines, 11 calculations, 12 validations, 53 endpoints, 27 errors, 5 roles, 2 OCC concurrency rules), SCAFFOLD_DIFFICULTY_DESIGN.yaml (9 rules x 2 = 18 instances), SCAFFOLD_CORNER_DESIGN.yaml (9 sections, 65 instances incl. 7 excluded_because stubs). Domain: GSA federal lease procurement + occupancy-agreement billing; primary archetype pricing_engine with temporal_windowing secondary; flat FK topology; logical clock default 2026-09-01T00:00:00Z with sweep-driven EXPIRING/EXPIRED cascades. All formula-derived asserts pre-computed as literals (TI annuity 649,470/mo on 58.5M over 120 months; April bill total 24,347,894; abated February 6,419,144; writeoff 3,052,345 after 6 payments of 519,160; option costs 2,834,450,000 / 2,918,600,000 / 2,478,100,000). scaffold_lint.py: VERDICT clean (972 calls scanned, 0 violations); grounds resolvability, name uniqueness (90), banned-vocabulary, and stub-reference audits all pass.

### Step 2 subagent verbatim summary (orchestrator-appended)

Scaffold generation for task_3467 is complete and fully verified.

**Deliverables** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3467_federal_building_lease_procurement_occupancy_agreement_billing/`):

- **SCAFFOLD.yaml** (1,504 lines) — §1.0–§1.7 only: 12 entities, 10 state machines, 11 calculations, 12 ordered validations, 53 endpoints, 27 error codes, 5 roles (AgencyManager entity-backed, 4 opaque), 2 OCC concurrency rules. Archetype: `pricing_engine` + `temporal_windowing`; flat FK topology with a self-referential `Lease.succeeds_lease_id`; logical clock at `/_clock/set_current_utc` (outside `/leasing` prefix) with pinned default `2026-09-01T00:00:00Z` driving the EXPIRING/EXPIRED sweep cascades.
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** (734 lines) — all 9 rules × 2 instances = 18, each with full structured `setup_api_calls` chains and pre-computed literal asserts (computed via Python: TI annuity 649,470/mo vs straight-line 780,000 month-1; April bill 24,347,894; abated February 6,419,144; CPI vs base-year-stop escalation 113,833 vs 341,500; writeoff 3,052,345 after six payments of 519,160; option costs 2,834,450,000 / 2,918,600,000 / 2,478,100,000).
- **SCAFFOLD_CORNER_DESIGN.yaml** (1,537 lines) — 65 instances (58 live + 7 `excluded_because` stubs) across all 9 taxonomy sections, covering all 27 error codes, terminal lockdowns, OCC stale-version paths, envelope shape, pagination, and the default-clock proof.

**Verification**: `scaffold_lint.py` verdict — `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (972 calls scanned, 0 violations). Additional audits passed: grounds resolvability, 90 unique instance names, banned-vocabulary scan, stub-reference integrity, enum-value closure (removed two dead enum values found in review), and call-by-call replay of the trickiest chains (lease-expiry cascade, OCC amend, deadline boundaries).

**One risk to flag downstream**: 53 endpoints exceeds the Expert band guideline (20–32) — deliberate, given the "much harder than expert" instruction and nine mandated workflows, but Step 6 (impl-gen) should be run with the pre-constraining prompt (one file per message, per-domain modules, no-truncation, self-smoke-test) per known endpoint-overshoot failure modes.

## Step 3: Copy shared files — 2026-10-02T11:31:35.000Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md (1,424 bytes).

## Step 4: Generate PRD — 2026-10-02T11:40:00.000Z

All checks pass. The PRD is complete and verified.

## Report

**Generated:** `/home/ubuntu/github/CodingPRD/tasks/task_3467_federal_building_lease_procurement_occupancy_agreement_billing/workspace/PRD.md` (329 lines) from `SCAFFOLD.yaml`, per `prd-bench-doc-generator`. The two forbidden design-index files were not opened.

**Structure:** §1 two-paragraph introduction (business context → system-as-pricing-engine angle); §2 with 11 subsections — domain-derived ones are 2.4 The Logical Clock (initial value `2026-09-01T00:00:00Z`, monotonic, sweep semantics, response fields), 2.5 Monetary Representation (integer cents, round-half-up, component-first), 2.6 Common Resource Properties, 2.7 OCC (both rules), 2.8 Nested Paths, 2.9 Space Inventory Conservation (both ownership invariants), 2.10 Validation Order (all 12 priorities in prose order), 2.11 Cascades/Ledgers; §3 with 9 subsections organized by lifecycle stage (portfolio → requirement → offering/award → commencement/rent/tax → OA/billing → alterations → services/SLA → utilization/reduction → expiration planning); §4 minimal 4-column table with all 53 endpoints (clock unprefixed at `/_clock/set_current_utc`); §5 two-column table with all 27 errors.

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 116 required, 116 present, 0 missing
- endpoints[].request_body: 82 required, 82 present, 0 missing
- endpoints[].query_params: 9 required, 9 present, 0 missing
- nested/aux (array-item + clock-response identifiers): 18 required, 18 present, 0 missing
- enum values: 63 required, 63 present, 0 missing
- errors[].id: 27 required, 27 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 12 checked, 12 expressed in prose (§2.10 ordered), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (amend/expected_oa_version, revise/expected_alteration_version, ERR_STALE_VERSION/412 each), 0 missing
- state_machines[].transitions: 35 checked, 35 fully expressed (from/to, preconditions with error ids, side effects), 0 missing
- calculations[]: 11 checked, 11 fully expressed in precise prose (incl. dual variants for tax escalation, TI amortization, utilization rate; pinned 13-step bill order; rounding orders), 0 missing
- validations[] conditions: 12 checked, 12 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 53 checked, 53 expressed, 0 missing
- entities[].fields[] structured content: 116 checked, 116 reconstructible, 0 missing
- sibling-branch symmetry: 6 groups checked (withdraw ×2, cancel ×3, plan-cancel ×2, pay ×3, execute branches ×3, lease-ending ×2), 6 with equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 538
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks: §2.2 matches `section-2.2-response-structure.md` byte-for-byte (prefix match verified); §4 has 53 rows = 53 scaffold endpoints; §5 has 27 rows = 27 errors; no pseudocode operators (`>=`, `==`, `min(`, etc.) or fuzzy words anywhere.

**Two drafting adjudications worth noting:** (1) the scaffold's error catalog explicitly lists OA amend under `ERR_OA_NOT_ACTIVE` while the state machine frames amend as an `ACTIVE → ACTIVE` transition — the PRD names `ERR_OA_NOT_ACTIVE` for amend-on-non-ACTIVE, matching the catalog; (2) the bill-month lower bound is stated only for leased OAs (lease commencement month), with the OA-end-month upper bound applied to all OAs, since the scaffold defines no commencement anchor for owned OAs.

## Step 5: Generate unit tests — 2026-10-02T12:05:00.000Z

Complete. Final state verified end to end.

## What was generated

**`test_helpers/`** (9 files) in `/home/ubuntu/github/CodingPRD/tasks/task_3467_federal_building_lease_procurement_occupancy_agreement_billing/test_helpers/`: types.py (12 entity TypedDicts, all enums), constants.py (PRD calculation thresholds + canonical fixture literals), api_errors.py (27 error ids → HTTP map, registered with the framework), api_client.py (all 53 endpoints; the logical clock is root-mounted at `/_clock/set_current_utc`, outside `/leasing`, per PRD §4), factories.py, test_users.py (AgencyManager is entity-backed — `make_agency_manager_headers(agency_id)` threaded through every ownership-gated call), assertions.py, fixtures.py (composite chains: soliciting requirement, awarded→commenced lease, active leased/owned OA, expiring lease with selected plan), __init__.py barrel.

**`test_suite/`**: conftest.py + 19 test files, **82 tests** — 18 difficulty (queue A, 18/18 instances) + 64 corner (queue B, 64/65 live instances). All money literals re-verified numerically with Decimal round-half-up before encoding (alteration 130,359/130,322 over 102 months; cascade write-off 3,052,345 after six 519,160 payments; abated/full bills 6,419,144/24,347,894; CPI escalation 113,833; half-up fee edge 1,142,349).

## Audit results

- `pytest --collect-only`: 82 collected, zero import/collection errors.
- AST tag audit: 0 untagged, 0 dual-tagged, 0 phantom tags, 0 stubs translated. All 7 `excluded_because` stubs left untranslated with resolving cross-references.
- PRD citation pass: 174 citations extracted from docstrings, **all 174 survive literal grep** of PRD.md.
- No `skip`/`skipif`/`xfail` markers anywhere.

## One filter skip (gap stays a gap)

`Corner/entities/requirement_create_computed_field_input_ignored`: asserts a client-supplied `projected_headcount: 999` is ignored. The PRD never states unknown/computed-input handling for requirement create (the only "ignored" clause in the PRD covers OA rate inputs on leased agreements) — one faithful reader ignores the field, another rejects it with ERR_INVALID_REQUEST. Fails unique derivability → skipped, not weakened. Relatedly, in `agency_create_returns_defaults` the recipe's `version == 1` literal is under-determined by PRD §2.6 (increment rule pinned, initial value not); the test asserts the PRD-covered defaults and version's type, not the absolute start value.

## Three design-index defects found and adjudicated (PRD wins)

1. **Difficulty `tax_escalation_base_year_stop_vs_cpi_indexed`**: recipe posted `cpi_index` on the BASE_YEAR_STOP lease's tax statement — PRD §3.4 makes that ERR_INVALID_REQUEST. Fixture records the statement without `cpi_index` on lease A; asserted literals (341,500 vs 113,833) unaffected.
2. **Corner `ti_annuity_vs_straight_line_month_one_divergence`**: trigger billed 2027-02 (month_index 2) but asserted the month-1 STRAIGHT_LINE entry 780,000 and total 6,556,200 — PRD §3.4/§3.5 derive month 2 = 777,563. The literals are exactly right for month_index 1, so the billing month was corrected to 2027-01, keeping every asserted number verbatim.
3. **Corner `amortization_window_exactly_twelve_months_allowed`**: the recipe's two estimate windows overlap (would trip ERR_ALTERATION_WINDOW_CONFLICT before the fiscal gate is reachable). Second window moved to 2035-12-20..2036-01-05 (15-day gap ≥ 14), preserving the asserted 12-months-allowed / 11-months-rejected / LUMP_SUM-fallback claims.

## Orchestrator verification (independent re-audit)

- `pytest --collect-only`: 82 collected, 0 errors — matches.
- Orchestrator-run AST tag audit: 82 tests, 0 untagged, 0 dual-tagged, 0 phantom tags; exactly 1 of 83 valid live tags absent = the documented filter skip. Claims confirmed.

## Step 6: Generate implementation — 2026-10-02T12:45:00.000Z

Implementation complete and smoke-tested.

## What was built

`/home/ubuntu/github/CodingPRD/tasks/task_3467_federal_building_lease_procurement_occupancy_agreement_billing/workspace/implementation/` — Python + Flask, in-memory only, all 53 endpoints from the scaffold's endpoint table (verified: 53 route decorators across 11 blueprint modules):

- **Foundation**: `store.py` (dict store, logical clock pinned at `2026-09-01T00:00:00Z`, version/seq/timestamp helpers, no seeding), `errors.py`, `envelope.py` (exact `meta`/`response_type`/`data` envelope, `error_id`/`message` error body, `limit`/`offset`/`total_count`/`has_more` pagination), `middleware.py` (`X-User-ID`/`X-User-Role` auth, 5-role RBAC, AgencyManager entity-backed scope), `dates.py` (month arithmetic with day-clamping, whole-months formula).
- **Domain logic**: `calc.py` (all 9 calculation families with `Decimal` round-half-up: headcount projection, ISC security bands with SCIF floor, dual tax-escalation variants, dual TI amortization variants, the pinned 13-step monthly bill, alteration amortization with final-month residual, dual utilization variants, option scoring with tie-priority, SLA credits), `cascade.py` (space-inventory reconciliation for both ownership types, OA terminal cascade, clock sweep with lease/OA/plan transitions).
- **Routes**: per-domain blueprints — agencies/buildings, requirements, offers, leases, plans, OAs, bills, alterations, services, utilization, clock. `app.py` thin bootstrap with envelope error handlers; `start.sh` with guarded pip install + `exec`, `0.0.0.0:$PORT`.

## Key decisions traced to PRD/scaffold

- Clock endpoint mounted **outside** `/leasing` at `/_clock/set_current_utc`; monotonic, echoes the raw input as `current_utc`; sweep supports COMMENCED→EXPIRING→EXPIRED in one jump, with full OA/alteration/plan cascades.
- `available_sf` stored + reconciled on every pool-changing event, version bumped on change (PRD §2.6 counts computed-field recomputation as mutation).
- Validation priority order honored per §2.10 (headers → role → scope → existence → shape → state → gates → security → temporal → referential → capacity/uniqueness → fiscal); OCC (`expected_oa_version` / `expected_alteration_version`) required and returning 412.
- Leased-OA window check skipped while lease is AWARDED, applied from commencement onward; owned OA reserves space at DRAFT creation.
- `created_at`/`updated_at` and all business stamps read the logical clock (SLA math needs it); `meta.api_request_timestamp` uses wall clock.

## Smoke test (dynamic port, killed afterward)

Full pipeline verified live: agency→building→requirement→submit→validate (projection 108, SCIF-floored level 4, 16,700 sf)→survey→offer→evaluate→select (lease created, building 100,000→83,300)→commence (end_date 2036-09-30, TI principal 3.3M, annuity 36,637/mo — consistent with the scaffold's pinned example)→OA→activate→bills (month-1 free-rent abatement 4,000,000; fee 39,332; total 825,969 — hand-verified)→partial payment→clock sweeps (EXPIRING at 2035-04-01, EXPIRED cascade at 2036-10-02, building restored to 100,000)→error paths (role/scope/404/monotonic/tenancy all correct IDs and statuses).

## Orchestrator verification

- All 21 .py files compile (`py_compile`); start.sh present; 53 route decorators across 48 unique paths — matches scaffold endpoint count.

## Step 7: Run tests and iterate — 2026-10-02T13:05:00.000Z

Clean sweep: all 8 rounds pass 82/82.

**Summary**

- **Iterations run:** 2 (initial sweep: 81/82 in all 8 rounds, one deterministic failure; post-fix sweep: 82/82 in all 8 rounds).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `implementation/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_3467_federal_building_lease_procurement_occupancy_agreement_billing/workspace/implementation/calc.py` — `bill_components()`: the AMORTIZED alteration balance was advanced only when a bill was generated for a covered month, so the final month's residual depended on billing history (9,985,888 instead of 130,322 when only 2 of 102 schedule months were billed). PRD §3.6 builds the schedule at completion ("each month before the last, the balance grows by one month of interest and the level payment is subtracted") and §3.5 step 7 bills "that month's scheduled charge" — a per-month determined value. Fixed by replaying the exact unrounded balance from `estimated_cost_cents` through all schedule months preceding the billing month (1-based position derived from `amortization_start_month`), then charging the level payment or, for the agreement's end month, the rounded residual. Verified numerically that the replay model also reproduces the cascade writeoff expectation (3,052,345 after six consecutive billed payments in `test_lease_expiry_cascades_oa_alteration_writeoff`), which still passes.

- **Diagnosis trail:** STEP 0 failure `assert 9985888 == 130322` on `test_alteration_amortization_monthly_first_rounding_residual_final`; STEP 1a PRD verbatim coverage at PRD.md line 209 (§3.6) and line 189 (§3.5 step 7); STEP 1b unique derivability held (schedule is a pure function of month index — Decimal replay confirmed 130,322 expected vs 9,985,888 lazy-billing value); STEP 2 test faithful; STEP 3 implementation bug, fixed as above.

## Orchestrator verification

- All 8 `results.{1..8}.json` files present in workspace/implementation/, each `passed=82 total=82 failed=0` — confirmed by direct JSON read.

## Step 8: Finalize PRD — 2026-10-02T13:20:00.000Z

**Adjudication complete: ZERO-EDIT outcome.** PRD_FINALIZED.md is a byte-identical copy of PRD.md (verified `diff -q` → IDENTICAL).

## Summary

**Line counts / delta:** PRD.md 329 lines; PRD_FINALIZED.md 329 lines; 0.0% delta (byte-identical).

**Changes:** none — zero edits. The single Step 7 diff item (implementation/calc.py `bill_components()` replay fix) is already uniquely determined by existing PRD prose.

### Evidence that the PRD uniquely pins the fixed behavior

PRD.md line 209 (§3.6), verbatim: "completion builds the alteration's amortization schedule. The principal is the `estimated_cost_cents`; … the term `amortization_months` is the count of months from the month after the completion month through the agreement's end month, inclusive; … The level `monthly_amort_cents` is computed first — the principal times the monthly rate, divided by one minus the quantity one-plus-the-monthly-rate raised to the negative power of the term — and rounded half up to whole cents before anything else. The `amortization_balance_cents` then tracks the exact, unrounded remaining balance: **each month before the last, the balance grows by one month of interest and the level payment is subtracted; the final month — the agreement's end month — bills the remaining balance grown by one more month of interest, rounded half up**, so the residual is absorbed by the last month. Computing the total first and dividing is expressly forbidden."

PRD.md line 189 (§3.5 step 7), verbatim: "`alteration_amortization_cents` sums, over the agreement's `COMPLETED` amortized alterations whose billed span — from `amortization_start_month` through the agreement's end month — covers the billing month, **that month's scheduled charge**: the level `monthly_amort_cents` for every month of a schedule except its final month, which bills its residual amount instead (§3.6)."

The three candidate gaps are all pinned:
- **Replay-from-completion:** §3.6 builds the schedule at completion from principal `estimated_cost_cents`, with the balance recurrence stated unconditionally per schedule month ("each month before the last") — calendar-indexed, not billing-event-indexed (the term itself is a calendar month count). Matches calc.py:132-134 (`bal = Decimal(estimated_cost_cents)`; `bal = bal*(1+ALT_R) - monthly` for k-1 months).
- **Final-month residual:** §3.6 pins it as "the remaining balance grown by one more month of interest, rounded half up" in "the agreement's end month" — a determined value (130,322 for the fixture). The buggy 9,985,888 (balance advanced only on billed months) satisfies no reading of this recurrence. Matches calc.py:135-137 (`billing_month == oa_end_month` → `rhu(bal*(1+ALT_R))`).
- **Independence from billing history:** §3.5 step 7 bills "that month's scheduled charge" for any month in the span — the charge is a property of (schedule, month index), and the unconditional span-coverage rule would be undefined for a month whose predecessors went unbilled under the lazy-advance reading. Matches calc.py:129-130 (1-based position k derived purely from `amortization_start_month` and billing month).

### Pre-edit search log (mandatory for the single adjudicated diff item)

- **(a) Subject:** alteration AMORTIZED amortization schedule — per-month charge, final-month residual, and the `amortization_balance_cents` recurrence, including billing-history independence.
- **(b) Impl paths enumerated and read/grepped** (grep over all `.py` for `amortization_balance_cents|monthly_amort_cents|amortization_start_month|amortization_months|alteration_amortization` — no other readers/writers exist):
  1. `implementation/calc.py:123-142` — the Step 7 fix site (replay, final-month branch, exact-balance writeback at line 140).
  2. `implementation/calc.py:169-175` — `alteration_amortization(P, n)`: level payment rounded half up first; initial exact balance = principal.
  3. `implementation/routes_alterations.py:188-213` — completion endpoint: term = calendar month count, start month = month after completion, fields seeded (lines 205-210).
  4. `implementation/routes_alterations.py:147` — approval gate `ERR_AMORTIZATION_WINDOW_TOO_SHORT` (≥12-month runway; PRD line 207, unaffected).
  5. `implementation/cascade.py:48-54` — terminal writeoff accelerates `rhu(exact balance)` into `terminal_writeoff_cents`; consistent with PRD line 179 ("exact remaining `amortization_balance_cents` … accelerated, rounded half up") and with the fixed writeback — the diff's numerical check confirms the replay model reproduces the cascade test's 3,052,345 expectation.
- **(c) Wording adjustment:** none — no edit was made, so no wording needed reconciliation across the enumerated paths; all five paths are consistent with the existing §3.5 step 7 / §3.6 prose as it stands.

Output file: `/home/ubuntu/github/CodingPRD/tasks/task_3467_federal_building_lease_procurement_occupancy_agreement_billing/workspace/PRD_FINALIZED.md` (byte-identical to PRD.md).

## Orchestrator verification

- `diff -q PRD.md PRD_FINALIZED.md` → byte-identical, confirmed independently.
- No implementation/*.py file is newer than results.8.json — the clean sweep post-dates all impl writes.

## Step 9: Complete PRD — 2026-10-02T14:25:00.000Z

All 21 edit sites landed cleanly with no unintended changes. The work is complete.

## Summary

**Source vs output:** `PRD_FINALIZED.md` (329 lines, 57,386 chars) → `PRD_COMPLETED.md` (331 lines, 60,978 chars). Char-delta: **+3,592**. File: `/home/ubuntu/github/CodingPRD/tasks/task_3467_federal_building_lease_procurement_occupancy_agreement_billing/workspace/PRD_COMPLETED.md`

**Counts:** 20 ambiguity-pins, 2 mismatch-revisions (21 edit sites; one site is a 2-line insert, rest are inline).

**Changes (one bullet each):**
- §2.1 — insert — ambiguity — header values are whitespace-stripped; whitespace-only counts as empty — implementation/middleware.py:17-26
- §2.1 — insert — ambiguity — read (GET) endpoints are not agency-scoped; any recognized role may read any agency's resources — implementation/routes_oas.py:113-128 (and all other GET routes)
- §2.2 — insert — ambiguity — `api_request_timestamp` is wall-clock request metadata, not the logical clock — implementation/envelope.py:16-19
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST` (400); equal `created_at` ties broken by creation order — implementation/middleware.py:54-80, implementation/store.py:97-99
- §2.4 — insert — ambiguity — clock response `current_utc` echoes the supplied `to_iso8601` verbatim — implementation/routes_clock.py:26-33
- §2.6 — insert — ambiguity — all server-written timestamps (`created_at`, `updated_at`, `awarded_date`, `amended_at`, `paid_at`, `resolved_at`, `verified_at`, `executed_at`) read the logical clock; client-supplied fields stored verbatim — implementation/store.py:63-79
- §2.7 — insert — ambiguity — missing/non-integer expected-version field → `ERR_INVALID_REQUEST`; *any* version mismatch (not only an advance) → `ERR_STALE_VERSION`; stale check ordered after §2.10 steps 6–7, before temporal/referential/capacity/fiscal — implementation/routes_oas.py:164-186, implementation/routes_alterations.py:165-174
- §2.8 — insert — ambiguity — unknown path or unsupported method → `ERR_NOT_FOUND` (404) — implementation/app.py:47-54
- §2.10 item 3 — insert — ambiguity — agency-scope comparison applies only when the agency-carrying resource resolves; unresolvable identifier yields `ERR_NOT_FOUND` — implementation/routes_services.py:19-27
- §2.10 item 10 — **revise — mismatch** — "(422 family)" → "(statuses per §5)"; PRD was internally inconsistent with its own canonical §5 catalog (`ERR_OA_NOT_ACTIVE` is 409, `ERR_INVALID_REQUEST` 400); impl follows the catalog, so prose fixed per adjudication rule (b) — implementation/routes_services.py:38-42
- §3.1 — insert — ambiguity — duplicate `bureau_code` → `ERR_INVALID_REQUEST` (400); catalog has no dedicated id — implementation/routes_agencies_buildings.py:22-24
- §3.4 — insert — ambiguity — commencement window upper bound is award date + 24 months via day-clamped month arithmetic, compared at date granularity — implementation/routes_leases.py:64-68
- §3.4 — revise — ambiguity — STRAIGHT_LINE interest is rounded half-up to whole cents *before* being added to the equal principal (rounding attaches to the interest) — implementation/calc.py:60-68
- §3.4 — insert — ambiguity — recording a tax statement returns the updated lease with 201; recompute "context year" = current logical-clock year — implementation/routes_leases.py:114-125
- §3.5 — revise — ambiguity — owned-space rates: integer ≥ 0 when present; on leased agreements ignored for pricing, stored null, still domain-checked if supplied — implementation/routes_oas.py:57-62, 98-99
- §3.5 — insert — ambiguity — terminal cascade zeroes the alteration's `amortization_balance_cents` as it accelerates into `terminal_writeoff_cents` — implementation/cascade.py:48-54
- §3.5 — insert — ambiguity — partial payment on a `PARTIALLY_PAID` bill leaves it `PARTIALLY_PAID` with `amount_paid_cents` increased — implementation/routes_bills.py:106-112
- §3.6 — insert — ambiguity — `amortization_balance_cents` may carry fractional cents; set to principal at completion, advanced to exact post-charge balance at each bill covering a schedule month — implementation/calc.py:132-141, implementation/routes_alterations.py:202-210
- §3.9 — insert — ambiguity — all nine cost parameters required on every select-option, each an integer ≥ 0 — implementation/routes_plans.py:80-84
- §3.9 — insert — ambiguity — succeeding lease keeps expiring lease's `requirement_id`, null `offer_id`, copies `base_year_tax_per_sf_yr_cents`/`escalation_method`/`free_rent_months`, zero `ti_allowance_total_cents`, logical-clock `awarded_date` — implementation/routes_plans.py:147-179
- §3.9 — **revise — mismatch** — spawned requirement copies *all* development inputs (title, headcount, growth, year, sf/person, special_needs, region, ISC points), not just "headcount and square-footage fields"; PRD phrase was loose shorthand, impl's full-copy is the only pipeline-consistent reading — implementation/routes_plans.py:102-129

## IMPL BUGS

None. I walked every endpoint, role gate, state transition, formula (TI annuity/straight-line, tax escalation both methods, alteration amortization with residual-absorbing final month, SLA credit blocks/cap, utilization rates, option scoring with tie priority), cascade (OA termination/expiry, lease end, plan lapse), capacity check, validation-order tier, and error-id/status mapping against the PRD. Everywhere the PRD names an exact rule, the implementation honors it — including the subtle ones: 14-clear-day alteration gap with exactly-14 allowed, strict SLA breach inequality, 0.6000-not-qualifying utilization threshold on the rounded rate, `whole_months_between` deadline formula, date-granularity clock sweeps with double transition in one jump, and component-first bill rounding order. All mismatches found were PRD-side ambiguity or loose prose, pinned above.

## Orchestrator adjudication of the 2 mismatch-revisions (against SCAFFOLD.yaml)

- §2.10 item 10 "(422 family)" → "(statuses per §5)": ACCEPTED — PRD self-contradiction with its own canonical §5 status catalog; impl follows the catalog. Self-contradiction exonerates the revision.
- §3.9 spawned-requirement copy scope: ACCEPTED — scaffold line 407 says "headcount/sf fields copied" and original PRD said "headcount and square-footage fields copied", but neither is restrictive (neither says ONLY those fields are copied nor names the other fields' values, leaving them ambiguous). The design index asserts only `base_headcount == 400`, which both readings satisfy, so no test signal exists. Full-copy is the only internally-consistent reading: the requirement entity's own contract (§3.1) carries title/growth/year/sf_per_person/special_needs/region/ISC points with domain constraints (points each 0–25), so a subset-copy would leave system-spawned requirements with nulls violating their own field domains. The revision retains the scaffold-mandated claim (headcount/sf ARE copied) and only pins the previously ambiguous remainder — no scaffold intent deleted.
- Re-verified after Step 9: 0 implementation/*.py files newer than results.8.json (sweep still valid); PRD_COMPLETED.md differs from PRD_FINALIZED.md (+3,592 chars, matching report).
