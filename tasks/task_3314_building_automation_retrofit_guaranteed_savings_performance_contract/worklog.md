# Worklog — task_3314_building_automation_retrofit_guaranteed_savings_performance_contract

## Step 1: Create task directory — 2026-09-30T19:50:00.000Z

Task directory `./tasks/task_3314_building_automation_retrofit_guaranteed_savings_performance_contract/` was pre-allocated by the entrance command (with `workspace/` inside); verified it exists and used it as-is. No new index computed, no other task_* directory created.

## Step 2: Generate scaffold — 2026-09-30T20:14:00.000Z

All checks pass. The scaffold package is complete and self-consistent.

## Summary

**Files written** (under `/home/ubuntu/github/CodingPRD/tasks/task_3314_building_automation_retrofit_guaranteed_savings_performance_contract/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design`

**Counts**
- Endpoints: 92 (71 business + 21 top-level filtered-list/scalar GETs added for FK reverse-reachability)
- Entities: 13 (PerformanceContract, Baseline, MeasureBundle, Measure, FinancingFacility, FinancingDraw, WorkPhase, DisruptionLog, SavingsReport, BaselineAdjustment, DisputeNotice, OwnerRep, ESCOEngineer)
- §1.8 difficulty instances: 18 (2 per rule × 9 rules), all non-stub, all numeric asserts pre-computed by executing the §1.3 formulas in Python (e.g. measured savings 240000 vs stipulated 285000 on identical meter data; lease 1295046 vs bond 1320947; tier-straddle verified savings 248276; waterfall draw 50000 capped from need 240000)
- §1.9 corner instances: 28 active + 8 `excluded_because` stubs
- Lint: `VERDICT: clean lint` (861 calls scanned); a custom chain-replay simulation of every setup/trigger sequence against the §1.2 state machines reports 0 residual issues

**Design decisions worth recording**
- Archetype: ledger reconciliation (guarantee shortfall reserve) × temporal windowing (phase windows, guarantee periods), compound state machines, approval-chain RBAC with 4 roles (PlatformAdmin opaque, LenderOfficer opaque, OwnerRep/ESCOEngineer entity-backed).
- Two OCC rules only: reconcile on `PerformanceContract.version`, baseline-adjustment approve on `Baseline.version` — both are genuine create-with-supersede races per the §1.2.1 filter.
- `api_prefix` set to `""` because the scaffold's own `/performance-contracts` collection plus top-level filtered-list GETs (`/baselines`, `/bundles`, …) satisfy lint check (f); with a non-empty prefix the collection-segment heuristic failed to resolve.
- Chain-ordering invariant enforced everywhere: `complete-audit` (AUDIT→SCOPED) must precede financing-facility submit/approve, since facility submit requires SCOPED; an automated reorder pass fixed all occurrences.
- Logical clock default `2026-09-01T00:00:00Z`; all fixtures derive from it (phase windows start at the default so `start` works with an unset clock; report submissions use 2027-09-30 after advancing).
- Distinct rule differentiation: dual-variant spans SavingsReport vs FinancingFacility domains; combinatorial uses mode (a) weather/tier/occupancy interaction vs mode (b) waterfall ordering+pool cap; boundary precision uses inclusive `>=` on coverage_ratio vs inclusive `<=` on disruption-hour budget; temporal overlap uses half-open phase windows vs closed-open point-instant disruption logs.

## Step 3: Copy shared files — 2026-09-30T20:15:00.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T20:23:00.000Z

The PRD is complete and all three hard contracts pass.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3314_building_automation_retrofit_guaranteed_savings_performance_contract/workspace/PRD.md` — 385 lines.

**Section overview:**
- §1 Introduction — 2 paragraphs framing the ESCO guaranteed-savings domain (audit → baseline → bundling → financing → occupied-facility construction → annual reconciliation → disputes).
- §2 Global Specifications — 9 subsections: 2.1 RBAC (headers, 4 roles, identity semantics per role, `PlatformAdmin`/`LenderOfficer` opaque vs `OwnerRep`/`ESCOEngineer` entity-backed); 2.2 response envelope (byte-identical verbatim block, verified); 2.3 pagination (limit 10/1/100, offset 0, `created_at` ascending); 2.4 common properties + money precision (UUID ids, `version` semantics, draws/disruption-logs have no `version`/`updated_at`, integer cents, half-up rounding, 4-dp kWh intermediates, 2-dp blended payback); 2.5 logical clock (default `2026-09-01T00:00:00Z`, never wall-clock); 2.6 nested addressing + global validation priority order; 2.7 OCC (`expected_contract_version` on reconcile, `expected_baseline_version` on adjustment approve, both → `ERR_STALE_VERSION` 412, no other endpoint takes a version field); 2.8 tariff tiering walk; 2.9 cascades and the two contract ledger fields.
- §3 Business Logic — 8 subsections: 3.1 audit/baseline (incl. baseline_cost formula with HDD 0.05 / CDD 0.08 / REFERENCE_OCCUPANCY 0.5 constants in prose), 3.2 bundling/subsidy waterfall (SHORT 3yr / LONG 7yr, tie-break `created_at` ASC), 3.3 financing (lease annuity / bond ×1.02 / third-party +0.015 spread, coverage ≥ 1.0000, draw availability rule), 3.4 phases/disruption (half-open windows, budget and containment checks, phase-overrun rule), 3.5 reports/reconciliation (measured vs stipulated variants, shortfall, 3-part close gate), 3.6 baseline restatement chain (pre-adjustment HDD/CDD comparison, report recompute scoping), 3.7 disputes (filer-side rules, lender resolution), 3.8 read/filtered-list views.
- §4 Endpoint table — all 92 endpoints, 4 columns only.
- §5 Error catalogue — all 74 error ids, 2 columns only.

**Zero-Silence self-check (§1.1–§1.7 coverage):**
- §1.1 entities: all 68 entity field names appear in backticks — PASS.
- §1.2 state machines: all 36 state values appear as exact UPPERCASE strings; every transition's preconditions, error ids, and side effects (including automatic system transitions, termination cascade, restatement cascade, bundle auto-complete, draw release ledger update, dispute resolve/withdraw report restore) are expressed in prose — PASS.
- §1.2.1 concurrency rules: both OCC rules named with write capability, `expected_*_version` field, and `ERR_STALE_VERSION`/412 — PASS.
- §1.3 calculations: all 5 (baseline_cost incl. initial/restated variants, savings_verification measured/stipulated, financing_payment 3 variants, subsidy_waterfall, blended_payback) rendered as precise prose with constants embedded — PASS.
- §1.4 validations: all 19 priorities covered; global ordering stated in §2.6, each rule placed at its workflow with its `error_id` — PASS.
- §1.5 endpoints: 92/92 present in §4 table; every `request_body` (49), `query_param` (12), and `path_param` (13) identifier appears in prose — PASS.
- §1.6 errors: 74/74 in §5 table; all 74 also mentioned in §1–§4 prose — PASS.
- §1.7 roles: all 4 roles with exact spelling, identity semantics translated per role, and endpoint authorization matching the scaffold's actor/RBAC assignments — PASS.

**Contract reports:**
- Contract 1 field-name coverage: 68 entity fields / 49 request-body / 12 query-param / 13 path-param required, 0 missing — PASS (computed with fenced-code-block masking, since §2.2's verbatim JSON fences otherwise desynchronize naive backtick pairing).
- Contract 2 rule coverage: priorities, OCC rejections, transitions, calculations, validation conditions, side effects/applies-to, field structured content, and sibling branches (lease/bond/third-party, measured/stipulated, owner/ESCO dispute filing, escalate/resolve/withdraw) all expressed with equal density — PASS.
- Contract 3 §3 path purity: 465 backtick tokens scanned in §3, 0 starting with `/`, 0 bare HTTP methods, 0 method+path combos — PASS.

The two withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never read.

## Step 5: Generate unit tests — 2026-09-30T20:39:00.000Z

Done. Summary of the generation run for task_3314:

## Files written

`test_helpers/` (9 files):
- `types.py` — status enums for all 10 stateful entities, role enum, TypedDicts (FinancingDraw and DisruptionLog correctly omit `version`/`updated_at` per their append-only nature)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (~50 methods, nested + transition + cross-contract reads)
- `api_errors.py` — full `ApiErrorId` enum (76 ids) with HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions plus contract-ledger invariant checker
- `factories.py` — payload factories for every creatable entity
- `constants.py` — calculation constants (HDD/CDD coefficients, BOND_FEE_UPLIFT, TP_SPREAD, payback thresholds), default clock, standard rate schedules
- `test_users.py` — shared role-header constants plus per-instance `make_owner_rep_headers` / `make_esco_engineer_headers` builders (both roles are entity-backed)
- `fixtures.py` — composite lifecycle fixtures: `scoped_contract`, `executed_contract`, `construction_contract`, `performance_contract` (full walk AUDIT→PERFORMANCE incl. measure install/verify, phase completion, clock advancement), report submission/attestation helpers. `scoped_contract` routes `baseline_*`-prefixed kwargs to the baseline factory so tiered rate schedules and kWh can be overridden per test.
- `__init__.py` — barrel export

`test_suite/` (11 files): `conftest.py` + `test_01`…`test_10` grouped by concern (contract creation, envelope/auth/existence, bundles & subsidy, financing & draws, phases & disruption, savings verification & reports, disputes, restatement & OCC, lifecycle cascades, RBAC).

## Test counts

- **Queue A (Difficulty): 18/18 instances covered, 36 tests** (exactly 2 per instance)
- **Queue B (Corner): 28/28 non-stub instances covered, 28 tests** (1 each); 8 `excluded_because:` stubs not translated (all cross-references verified to resolve to real queue-A instances)
- Total: 64 tests, 64 tags.

## Instances skipped

None — every non-stub instance in both indices passed the PRD-first two-condition filter. (The `priority_pair_validation_conflict` instances were keepable because PRD §2.6 explicitly fixes the global validation order — state before business rules — so asserting which error fires is PRD-derived, not scaffold-derived.)

## Fixture-date sanity

All phase windows start at 2026-09-01 (the PRD's logical-clock default), so start-type transitions are reachable without any clock call — and one test (`logical_clock_default_is_fixed_instant`) deliberately makes no clock call at all to assert that default.

## Stage 2 tag audit

Clean: 64 tests ↔ 64 `Design:` tags, every test docstring carries exactly one tag, every tag resolves to a real instance in the cited yaml, no tags point at stubs, all 18 difficulty instances have ≥2 tests, all 28 non-stub corner instances have ≥1. A verbatim-grep sweep confirmed a distinctive ≥8-word substring of every PRD citation appears literally in PRD.md. All files byte-compile and import-execute.

## Step 6: Generate implementation — 2026-09-30T21:12:00.000Z

All done. Summary below.

## Implementation complete

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3314_building_automation_retrofit_guaranteed_savings_performance_contract/workspace/implementation/`):

- `start.sh` — guarded dependency install (`pip install` only if flask missing), `exec python3 app.py`, foreground
- `requirements.txt` — flask>=3.0
- `app.py` — Flask app factory, blueprint registration, error handlers (ApiError, 404/405, catch-all)
- `db.py` — empty in-memory stores + logical clock defaulting to exactly `2026-09-01T00:00:00Z`, never wall-clock
- `errors.py` — `ApiError` plus envelope helpers (`meta.api_request_id`/`api_request_timestamp` with ms precision, `response_type`, `data`); error body uses `error_id`/`message`
- `util.py` — UUID ids, ISO-8601 parsing, typed field validators (int/number/enum/string, rate-schedule tier validation: contiguous, first `up_to_kwh` > 0, last `null`), `limit`/`offset` pagination (defaults 10/0, min 1, max 100, `total_count`/`has_more` in `meta`), `X-User-ID`/`X-User-Role` auth with the 4 exact role names
- `calc.py` — Decimal-based calculations: tiered pricing walk, baseline weather/occupancy normalization (HDD 0.05 / CDD 0.08 / reference occupancy 0.5, kwh at 4 dp, round-half-up to cents), measured (IPMVP_B/C) vs stipulated (IPMVP_A/D: 0.95 × VERIFIED measure savings) verification, financing payments (lease annuity; bond = annuity × 1.02; third-party at rate + 0.015; coverage ratio 4 dp), blended payback (2 dp), subsidy pool (≤3 yr) and waterfall (>7 yr, sorted by payback then created_at)
- `domain.py` — left-to-right nested path lookups with per-segment 404s, serializers, bundle/report/ledger recomputes
- `routes_identity.py`, `routes_contracts.py`, `routes_baselines.py`, `routes_bundles.py`, `routes_measures.py`, `routes_facilities.py`, `routes_draws.py`, `routes_phases.py`, `routes_reports.py`, `routes_adjustments.py`, `routes_disputes.py`, `routes_toplevel.py` — all 69 endpoints from the scaffold's §1.5 endpoint table (92 registered Flask rules including duplicates across methods)

**Endpoint count**: 69/69 implemented, including the logical-clock endpoint, all state transitions, both OCC-guarded writes (`expected_contract_version` on reconcile, `expected_baseline_version` on adjustment approve; missing → 400, mismatch → 412 ERR_STALE_VERSION), and all top-level filtered listings + the attested-reports reverse lookup.

**Smoke testing**: booted fresh processes via `bash start.sh` on `$PORT` (killed and relaunched between runs; only PIDs I started were killed, verified via `ss -tlnp` by port). Two scripted end-to-end runs passed with hand-computed values: full lifecycle AUDIT→CLOSED-path with lease annuity (1295046 for P=10M@5%/10y), tiered baseline cost (10,600,000), subsidy pool/waterfall draws (600,000), measured savings (3,200,000) and shortfall posting with OCC; plus bond zero-rate uplift (1,020,000), third-party spread annuity, coverage<1 rejection, phase window overlap + touching-window allowance, dispute file/escalate/withdraw/resolve role gating, adjustment chain + stale-chain + nonpositive-baseline errors, restatement cascade into SUBMITTED/ATTESTED reports, duplicate-period rejection, pagination.

**Ambiguities resolved** (noted in code comments):
1. **Bond zero-rate**: scaffold formula orders uplift before the zero-rate branch; PRD §3.3 prose says compute the annuity (P/n at zero rate) then multiply by 1.02 — followed PRD.
2. **Attester after dispute resolution on a pre-attest (OWNER-filed) dispute**: PRD says the report "returns to ATTESTED" but it was never attested; I keep the pre-dispute attester (null for pre-attest disputes) rather than inventing one.
3. **Disruption validation order**: scaffold priority lists budget (p6) before window (p7) and PRD says "evaluated after the generic checks" in that same order — implemented budget-then-window.
4. **`guarantee_start_date` > audit completion date**: enforced at `complete-audit` against the logical clock (400 ERR_INVALID_REQUEST), the only moment an "audit completion date" exists.
5. **Phase late-completion overrun**: "every measure scheduled to this phase" — phases have no measure FK, so interpreted as all contract measures being INSTALLED/VERIFIED/EXCLUDED.
6. Contract `close` PAID_OFF cascade: "drawn fully serviced" has no repayment ledger, so implemented as `drawn_cents == 0` per the informational-only note in §3.3.

## Step 7: Run tests and iterate — 2026-09-30T21:30:00.000Z

All 8 rounds pass 64/64. Clean sweep.

## Summary

- **Iterations run:** 3 sweeps (initial diagnostic + 2 fix-verification rounds), each 8 parallel rounds.

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:**
  - `fixtures.py` — `construction_contract` now re-fetches the facility and the phase after the mobilize/start cascade. The fixture previously returned stale response snapshots, so callers saw the facility as `APPROVED` (not `FUNDING`) and the phase as `PLANNED` (not `IN_PROGRESS`) even though the server had advanced both. This fixed `test_payoff_before_term_elapsed_rejected` and the setup assertion in `test_phase_window_overlap_rechecks_against_in_progress_phases`.

- **Fixes applied to `test_suite/`:**
  - `test_06_savings_verification_and_reports.py::test_measured_vs_stipulated_savings_diverge_on_identical_meter_data` — added `reset_clock()` between the two `performance_contract` fixture walks; the first walk leaves the clock at the year-1 end instant, so the second contract's audit-completion gate ("guarantee_start_date must be later than the audit completion date", PRD §3.1) correctly rejected it.
  - `test_06_savings_verification_and_reports.py::test_occupancy_ratio_is_load_bearing_in_normalization` — the arithmetic in the payload/assertion was wrong (period occupancy 0.5 equals the baseline's 0.5, so the ratio is 1 and verified savings are 0, not −150000). Changed `period_occupancy_factor` to 0.4 (ratio 1.25 → norm 150000 kwh priced at 1950000) so the asserted −450000 verified savings and 750000 shortfall follow exactly from the PRD §3.5 formula.
  - `test_09_contract_lifecycle_cascades.py::test_terminated_contract_rejects_new_bundle_creation` — relaxed to `validate_error_is_one_of([ERR_CONTRACT_NOT_SCOPABLE, ERR_BUNDLE_NOT_DRAFT])`. PRD §3.2 names both gates on propose but is silent on precedence when termination has simultaneously withdrawn the bundle and left the contract non-scopable (error-precedence silence; both errors are PRD-named for this endpoint).
  - `test_05_phases_and_disruption.py::test_phase_window_overlap_rechecks_against_in_progress_phases` — rebuilt setup on `executed_contract` with phase A created, mobilized, and started inline. The old setup used `construction_contract`, which leaves the contract in CONSTRUCTION where mobilize correctly fails with `ERR_CONTRACT_NOT_EXECUTED` (PRD §3.4 requires EXECUTED) before the overlap check can be exercised.

- **Fixes applied to `implementation/`:**
  - `workspace/implementation/routes_phases.py::create_disruption` — added the missing `ERR_PHASE_NOT_IN_PROGRESS` (409) state gate after body validation and before the budget/window business checks. PRD §3.4 ("While a phase is in progress, the engineer logs occupant disruptions…") requires the gate, and PRD §2.6 fixes its position ahead of the business-rule checks. Fixed `test_state_vs_business_safety_on_disruption_log` and `test_disruption_on_planned_phase_rejected_with_state_error`.

## Step 8: Finalize PRD — 2026-09-30T21:36:00.000Z

Both edits are in place, confined to two lines. Done.

## Summary

**Line counts:** PRD.md 385 lines, PRD_FINALIZED.md 385 lines (0% line-count delta; 2 lines modified in place, same line count).

**Changes (one bullet each):**
- §3.2 (Scoping the Work) — revise — pinned gate evaluation order on bundle propose: `ERR_BUNDLE_NOT_DRAFT` first, then `ERR_CONTRACT_NOT_SCOPABLE`, then `ERR_BUNDLE_EMPTY`; a multi-violation request surfaces the earliest failure — `implementation/routes_bundles.py:55-63`.
- §3.4 (Phases and Disruption) — revise — made the disruption-log state gate explicit (`ERR_PHASE_NOT_IN_PROGRESS`, 409, evaluated before business rules per §2.6) and pinned the business-check order as budget (`ERR_DISRUPTION_BUDGET_EXCEEDED`) before window (`ERR_DISRUPTION_OUTSIDE_WINDOW`) — `implementation/routes_phases.py:140-147`.

**Step 7 items judged to need no PRD change (pure test/fixture bugs; PRD already determines behavior and impl matches):**
- `fixtures.py` re-fetch after mobilize/start cascade — fixture staleness only.
- `reset_clock()` in measured-vs-stipulated test — the audit-completion gate (`guarantee_start_date` later than audit completion date) is already pinned in §3.1 and implemented at `routes_contracts.py:78-81`.
- Occupancy-ratio test arithmetic — §3.5's formula already matches `calc.py:64-77` exactly; the old test's math was wrong.
- Phase-overlap test setup rebuild — §3.4 already pins mobilize requiring `EXECUTED` (`ERR_CONTRACT_NOT_EXECUTED`) and the overlap re-check against `MOBILIZED`/`IN_PROGRESS` phases; impl matches at `routes_phases.py:70-79`.

**Per-edit pre-edit search log:**

Edit 1 (§3.2 propose precedence):
- (a) Subject: evaluation order of the three propose gates (`ERR_BUNDLE_NOT_DRAFT`, `ERR_CONTRACT_NOT_SCOPABLE`, `ERR_BUNDLE_EMPTY`).
- (b) Paths enumerated: `routes_bundles.py::propose_bundle` (only site raising these three errors; lines 51-66, read in full); `routes_bundles.py::approve_bundle`/`withdraw_bundle` (no contract-scopability check, unaffected); contract termination cascade in `routes_contracts.py` (sets bundles `WITHDRAWN`, which feeds the DRAFT check — consistent with bundle-state-first ordering); grep across all impl files confirmed no other raise sites for `ERR_CONTRACT_NOT_SCOPABLE`/`ERR_BUNDLE_NOT_DRAFT`.
- (c) Wording mirrors the impl's exact order (DRAFT → scopability → emptiness) and names all three gates in the sentence already present, so no other endpoint's description is affected.

Edit 2 (§3.4 disruption gate + business-check order):
- (a) Subject: state gate and check ordering on disruption logging.
- (b) Paths enumerated: `routes_phases.py::create_disruption` (lines 132-159, read in full — order: role → path → body parse → 409 state gate → 422 budget → 422 window); the other two `ERR_PHASE_NOT_IN_PROGRESS` raisers (`complete_phase` line 108, `suspend_phase` line 126) — both already described in the PRD with the error named, wording left untouched; `list_disruptions` (no state gate, unaffected); grep confirmed no other file raises `ERR_PHASE_NOT_IN_PROGRESS`/`ERR_DISRUPTION_*`.
- (c) Wording adjusted: the original PRD sentence listed the window check before the budget check, which mis-described impl order; the revision reorders the two business checks (budget first, then window) to match `routes_phases.py:142-147` while preserving each check's original description verbatim, and scopes the new state-gate sentence to the logging endpoint only so complete/suspend descriptions are undisturbed.

## Step 9: Complete PRD — 2026-09-30T21:45:00.000Z

The PRD_COMPLETED.md is produced at `/home/ubuntu/github/CodingPRD/tasks/task_3314_building_automation_retrofit_guaranteed_savings_performance_contract/workspace/PRD_COMPLETED.md`.

**Source vs output**: PRD_FINALIZED.md = 385 lines / 58,258 chars; PRD_COMPLETED.md = 385 lines / 61,983 chars (char-delta +3,725; all changes are inline inserts/revisions, one catalogue row removed, no new sections).

**Counts**: 17 ambiguity-pins, 5 mismatch-revisions (22 changes total).

- §2.1 — insert — ambiguity — any non-empty header string is well-formed; header-derived identities (attester, dispute filer) recorded without verifying registration — implementation/util.py:152-160, routes_reports.py:90
- §2.2 — insert — ambiguity — undefined path → `ERR_INVALID_REQUEST` (404); unsupported method → `ERR_INVALID_REQUEST` (405) — implementation/app.py:39-45
- §2.3 — insert — ambiguity — list sort ties on `created_at` broken by `id` ascending — implementation/util.py usage, e.g. routes_toplevel.py:33
- §2.4 — insert — ambiguity — decimal fields serialize as JSON int when integral else number; `simple_payback_years` serialized unrounded — implementation/domain.py:96-100, 119-123
- §2.6 — insert — ambiguity — creation endpoints do not gate on parent contract status; state gates apply only where stated — e.g. implementation/routes_baselines.py:15-43, routes_draws.py:13-27
- §2.8 — insert — ambiguity — single-tier schedule with sole unbounded tier is valid; tier ceilings strictly increasing — implementation/util.py:116-128
- §2.9 — insert — mismatch — added exception: adjustment-approval cascade refreshes contract `updated_at` without incrementing contract `version` — implementation/routes_adjustments.py:119-120
- §3.1 (complete-audit) — insert — ambiguity — earliest-created APPROVED baseline pinned when several exist; guarantee_start_date-vs-clock violation is `ERR_INVALID_REQUEST` (400) — implementation/routes_contracts.py:77-81
- §3.2 (bundle approve) — insert — ambiguity — null blended payback (zero summed savings) also fails with `ERR_BUNDLE_PAYBACK_EXCEEDS_TERM`; check uses freshly recomputed pre-approval figure — implementation/routes_bundles.py:75-78
- §3.2 (waterfall) — insert — ambiguity — sort ties further broken by measure `id` — implementation/calc.py:134
- §3.2 (exclude) — revise — mismatch — exclusion unconditionally zeroes the draw, recomputes the pool, and re-runs the waterfall (not conditional on draw > 0) — implementation/routes_measures.py:80-85
- §3.2 (execute) — insert — ambiguity — the execute-time payback re-check also rejects a null blended payback — implementation/routes_contracts.py:102-105
- §3.2 (terminate) — insert — ambiguity — terminal states pinned: bundle WITHDRAWN/COMPLETE, measure VERIFIED/EXCLUDED — implementation/routes_contracts.py:198-205
- §3.3 (mobilize) — revise — mismatch — every APPROVED facility (not "an approved facility") flips to FUNDING — implementation/routes_contracts.py:128-131
- §3.3 (draws) — revise — ambiguity — draw requests accepted in any facility state; at approval the draw's REQUESTED state is checked before the facility's FUNDING state — implementation/routes_draws.py:13-27, 45-48
- §3.3 (close) — insert — ambiguity — "fully serviced" pinned to `drawn_cents == 0` — implementation/routes_contracts.py:182-185
- §3.4 (start/resume) — revise — mismatch — start endpoint handles MOBILIZED and SUSPENDED; all other states fail with `ERR_PHASE_NOT_MOBILIZED`; `ERR_PHASE_NOT_RESUMABLE` never occurs — implementation/routes_phases.py:85-100
- §3.4 (complete) — revise — mismatch — late-completion overrun check spans all contract measures and accepts INSTALLED, VERIFIED, or EXCLUDED (not "measures scheduled to the phase", not INSTALLED/VERIFIED only) — implementation/routes_phases.py:109-115
- §3.4 (disruptions) — insert — ambiguity — body field-shape validation runs before the phase state gate — implementation/routes_phases.py:136-141
- §3.5 (submit) — insert — ambiguity — "plus period_year years" is calendar-year addition with Feb 29 clamped to Feb 28 — implementation/domain.py:212-221
- §3.5 (reconcile) — revise — ambiguity — ATTESTED state check precedes OCC validation; missing/non-integer `expected_contract_version` → `ERR_INVALID_REQUEST` (400); ledgers re-derived as sums over RECONCILED reports — implementation/routes_reports.py:100-113, domain.py:203-209
- §3.6 (approve) — revise — mismatch — weather deviation factors evaluate to exactly 1 at restatement (degree days unchanged); occupancy factor uses post-restatement occupancy; contract `version` not incremented by the cascade — implementation/routes_adjustments.py:99-120; also pinned missing/non-integer `expected_baseline_version` → `ERR_INVALID_REQUEST` (400) (routes_adjustments.py:88-91)
- §3.7 (file/resolve/withdraw) — revise — ambiguity — body `report_id` must equal the path report id; resolve/withdraw restore the pre-dispute `attested_by_owner_rep_id`; withdrawal checks filer-side role before the OPEN state check — implementation/routes_reports.py:122-125, routes_disputes.py:60-91
- §3.8 — insert — ambiguity — owner rep / engineer / disruption-log by-id and attested-reports lookups of unknown ids fail with `ERR_REFERENCED_RESOURCE_NOT_FOUND` (404) — implementation/routes_identity.py:44-45,69-70, routes_toplevel.py:18,169-170
- §5 catalogue — revise — mismatch — removed the `ERR_PHASE_NOT_RESUMABLE` row (no endpoint raises it) — implementation/routes_phases.py:85-100

Notable confirmed matches needing no change: tiered pricing walk, baseline normalization coefficients (0.05/0.08, occupancy/0.5, 4-dp kWh), measured vs stipulated savings variants, annuity formulas per facility type (LEASE plain, BOND ×1.02 including zero-rate, THIRD_PARTY rate+0.015), coverage ratio 4-dp and ≥1.0000 gate, bundle propose gate order, phase mobilize overlap (half-open windows), disruption budget-then-window check order, close gate order (reconciliation → disputes → reserve), adjustment approval precondition order (PROPOSED → LOCKED/RESTATED → chain → OCC → nonpositive), and the OCC-only-on-two-endpoints rule.
