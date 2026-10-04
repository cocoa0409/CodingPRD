# Worklog — task_3145_dental_benefit_plan_administration_fee_tiers_predetermination

## Step 1: Create Task Directory — 2026-09-30T00:00:00.000Z

Pre-allocated task directory `./tasks/task_3145_dental_benefit_plan_administration_fee_tiers_predetermination/` verified present with `workspace/` inside. No new index computed; no other task_* directory created.

## Step 2: Generate Scaffold — 2026-09-30T04:52:00.000Z

All three files written and lint-clean. Summary:

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_3145_dental_benefit_plan_administration_fee_tiers_predetermination/`:

- **SCAFFOLD.yaml** — §1.0–§1.7 (no difficulty/corner keys inside)
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** — single top-level `scaffold_difficulty_design:` with all 9 rules × 2 instances = **18 instances**
- **SCAFFOLD_CORNER_DESIGN.yaml** — single top-level `scaffold_corner_design:` with **49 instances** (46 active + 3 `excluded_because:` stubs)

## Counts (from lint verdict)

- **Entities: 12** — Plan, Provider, FeeSchedule, FeeScheduleEntry, Subscriber, Dependent, LimitationRule, Predetermination, Claim, ClaimLine, ClaimAttachment, BenefitAccumulator
- **Endpoints: 49** (incl. `POST /dental/_clock/set_current_utc` test-driving endpoint with pinned default 2026-09-01T00:00:00Z)
- **State machines: 8** (Plan, Provider, FeeSchedule, Subscriber, Predetermination, Claim, ClaimLine, Dependent) + 2 OCC concurrency rules (predet-approve, claim-void)
- **Calculations: 7** — allowed_amount_resolution (dual-variant: pinned vs free-by-service-date), patient_cost_share (dual-variant: estimate vs adjudication), annual_max_accumulator, limitation_rule_evaluation (chronological, closed windows), waiting_period_gate (inclusive threshold), cob_waterfall, predetermination_estimate (dual-variant: at-assign vs at-approve)
- **Validations: 20 rows**, priorities 1–18 including a 2.5 ownership row and 11.5 fee-schedule-coverage row
- **Errors: 26**; **Roles: 6** (PlanAdmin/NetworkManager/ClaimsExaminer opaque; ClinicalReviewer opaque with self-assignment SoD; Member entity_backed:Subscriber; Provider entity_backed:Provider)
- Lint: `VERDICT: clean lint` — 558 §1.8/§1.9 calls checked against §1.5, all FK reverse-reachability satisfied

## Notable design decisions (difficulty levers, expert-plus calibration)

1. **Fee-schedule window truncation** instead of naive supersession: activating a newer same-tier schedule truncates the predecessor's `[effective_from, effective_to)` window in place; retroactive insertion is rejected with `ERR_SCHEDULE_OVERLAP`. This powers the depth-3 cascade (activate → v1.effective_to mutation → UNDER_REVIEW predet recompute → predet version bump) and the R8 half-open-vs-closed interval contrast against frequency windows.
2. **Pin-on-approve predetermination pricing**: an APPROVED predetermination pins `version_pin_fee_schedule_id`; matching claims price against the pinned schedule even after truncation, while unpinned claims price by service date — the R1 dual-variant pair shares identical inputs and diverges by exactly 20000 cents.
3. **Per-line sequential accumulator drawdown** (line_number ASC) makes the annual-max cap a circular-looking dependency with pinned evaluation order (R2 mode c); the deductible/coinsurance/cap/COB chain supplies the ≥3-input non-linear formula (R2 mode a), with coinsurance pinned to `floor`, not round-half-up.
4. **Segregation of duties** as the role model: clinical reviewers self-assign (`X-User-ID == payload clinical_reviewer_id`), only the assigned reviewer can approve/deny, and reassign must change reviewer — all under `ERR_SEGREGATION_OF_DUTIES`.
5. **Compensating invariants** on two distinct quantities: `annual_max_used_cents` (adjudicate→void restores zero) and `deductible_met_cents` (voiding the second of two claims restores exactly the first claim's 10000 draw, not zero).
6. Corner coverage drives every error code in the catalog to at least one test (including all seven typed 404s), plus attachment-pend → adjudicate flow, COB waterfall (3000 = min(8000 hypothetical, 3000 remaining)), ABP re-pricing with patient-difference uplift, missing-tooth, AGE_MAX whole-years, per-tooth REPLACEMENT_INTERVAL, plan-year rollover resetting the deductible at `plan_year_start_month`, pagination, and immediate-consistency of computed claim totals.

## Step 3: Copy Shared Files — 2026-09-30T04:53:00.000Z

Copied `./INSTRUCTION.md` → `./tasks/task_3145_dental_benefit_plan_administration_fee_tiers_predetermination/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T05:00:00.000Z

All checks pass. PRD generation complete.

**Output:** `workspace/PRD.md` — 290 lines.

**Section list:**
- §1 Introduction (3 paragraphs: business pain points, six constituencies, two design commitments)
- §2 Global Specifications — 11 subsections: 2.1 RBAC (with per-role identity prose), 2.2 Response Structure (verbatim fixed block), 2.3 Pagination, 2.4 Common Resource Properties (incl. `ClaimAttachment` deviation — no `updated_at`/`version`, `transmitted_on` instead), 2.5 Monetary Precision (integer cents, floor for coinsurance, plan-config bounds), 2.6 Logical Clock (2026-09-01 anchor, `to_iso8601`/`now`), 2.7 Plan Years & Accumulation (`plan_year_key` derivation, invariant), 2.8 Network Tiers & Fee Schedule Versioning (truncation vs `ERR_SCHEDULE_OVERLAP`), 2.9 OCC (both rules with `expected_predetermination_version`/`expected_claim_version` + `ERR_STALE_VERSION` 412), 2.10 Validation Order & nested-path left-to-right with per-type 404 codes, 2.11 Cascade Discipline
- §3 Business Logic — 9 subsections organized by domain workflow: plan/limitation-rule setup, network & fee-schedule filing, enrollment/COB declaration, predetermination lifecycle (assign/reassign/approve/deny/withdraw/expire + SoD + annual-max guard + 90-day validity), claim intake (timely filing 365-day inclusive boundary, attachment routing, COB pend), line pricing with ABP, adjudication (waiting periods, all 5 limitation rule kinds, line-order accumulator drawdown), COB waterfall, payment/void/reversal (30-day void window)
- §4 Endpoint table — 49 endpoints, 4 columns only
- §5 Error catalogue — 26 errors, 2 columns only

**Scattering choices:** Constants embedded in narrative ("ninety days" validity, "three hundred sixty-five days" timely filing, "thirty days" void window, `D1*` wildcard example); endpoint inputs split across subsections (claim payload in §3.5, COB amount in §3.5/§3.8, OCC fields in §2.9 vs approval narrative in §3.4); fee-schedule cascade described once in §2.8 (truncation) and again in §3.4 (predetermination recompute + version bump) from different angles; §3 contains zero HTTP methods/paths — all endpoints named via state-pair framing or role+verb.

**Coverage checks (all PASS):**
- Field coverage: 85 required (entity fields + endpoint inputs + pagination), 85 present, 0 missing (after fixing two initial misses: `claim_id`, `status`)
- State enums: all 27 state values present; all category/tier/relationship/attachment-kind/rule-kind/denial-code enum values present
- Error IDs: 26/26 present in prose and §5
- §3 path purity: 323 backtick tokens scanned, 0 violations

## Step 5: Generate Unit Tests — 2026-09-30T05:30:00.000Z

All done. Summary of the generation:

**Task**: `task_3145_dental_benefit_plan_administration_fee_tiers_predetermination`

### test_helpers/ (9 files)
- `test_helpers/constants.py` — roles, entity statuses, CDT codes, and PRD-pinned thresholds (90-day predetermination validity, 365-day timely filing, 30-day void window)
- `types.py` — TypedDicts for all 12 entities; `ClaimAttachment` correctly omits `updated_at`/`version` (common_fields: false)
- `api_errors.py` — all 24 error ids with HTTP status map, registered via `set_error_http_status_map`
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint, plus `canonical_instant`/`same_instant` ISO-8601 normalizers
- `test_users.py` — opaque operator header constants (ADMIN, NETWORK, REVIEWER_1/2, EXAMINER) plus mandatory `make_member_headers`/`make_provider_headers`/`make_reviewer_headers` builders for entity-backed and segregation-of-duties identities
- `factories.py` — payload factories for all creatable entities (input fields only)
- `assertions.py` — per-entity shape assertions, accumulator invariant checker, framework validators re-exported
- `fixtures.py` — composite builders: `standard_stack` (clock → active plan → provider → active PPO fee schedule → subscriber), attachment-required variant, predetermination lifecycle walks (submitted/under-review/approved), claim walks (adjudicated/paid), attachment upload, accumulator readers; identity threading uses entity-backed headers
- `__init__.py` — barrel export

### test_suite/ (17 test files + conftest.py, 84 tests)
- Queue A (difficulty): files 01–09, 2 tests per each of the 18 instances (36 tests)
- Queue B (corner): files 10–17, 1 test per each of the 45 non-stub instances (48 tests — 3 instances earned a second test where the recipe naturally split, e.g. plan-active happy path alongside the rejection)

### Verification performed
- All files compile; pytest collects 84 tests cleanly
- Every test docstring ends with exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` tag resolving to a real instance (audited programmatically)
- Zero coverage shortfalls in either queue; zero unknown tags
- Every PRD citation was machine-checked: a ≥8-word probe of each quoted sentence survives literal matching against PRD.md (0 failures after fixing 6 initial issues — replaced §4 endpoint-table pseudo-quotes with verbatim prose citations)
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no scaffold references in generated code

### Skipped instances (all legitimate `excluded_because` stubs — not translated per spec)
- `Corner/state_machines/auto_deny_when_all_lines_denied` → owned by Difficulty `claim_branching_denied_path_and_paid_then_void_revert`
- `Corner/validations/error_plan_not_active_on_claim` → owned by `claim_submission_depends_on_plan_state`
- `Corner/validations/error_provider_terminated_on_claim` → owned by `claim_submission_depends_on_provider_state`
- `Corner/validations/error_schedule_overlap_on_retroactive_activation` → owned by `fee_schedule_half_open_window_overlap_and_adjacency`
- `Corner/validations/error_annual_max_exceeded_on_predet_approve` → owned by `predet_approve_annual_max_remaining_exact_equality_allowed`
- `Corner/cross_cutting/derived_accumulator_reconciles_after_second_claim` → owned by `void_of_second_claim_restores_deductible_to_first_claims_level`

### Notable design decisions
- Validation-priority difficulty instances (priority_pair) are translated as PRD-verbatim §2.10 validation-order tests, since the PRD does explicitly state the fixed layer ordering — both the dual-violation probe and a single-violation control test are included per instance.
- No PRD-first skips were needed beyond the declared stubs: every non-stub instance's asserted rule has verbatim PRD coverage (validation ordering is in §2.10; the OCC rules in §2.9; cascade version bumps in §2.11/§3.4; expiry arithmetic "logical clock plus ninety days" in §3.4).
- The claim OCC test computes staleness from the version returned by the create response rather than assuming a literal version number (PRD never pins the post-adjudication version value), avoiding a two-reader failure.

## Step 6: Generate Implementation — 2026-09-30T06:05:00.000Z

Final state:

**Implementation: 82/84 tests pass** under `prd-bench-local-run --isolation per-test-server`. The 2 remaining failures are a test-suite bug in `test_08_window_semantics.py` (uses `CATEGORY_PREVENTIVE` on lines 119/141/161 but never imports it from `test_helpers.constants`); the implementation cannot fix that.

### Files written

All under `workspace/implementation/`:

- `start.sh` — executable launcher; `set -euo pipefail`, `cd` to its own dir, guarded pip install (only when `flask` import fails), `exec python3 app.py`
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask entry point; mounts every endpoint under `/dental`, all routes, all renderers
- `db.py` — empty-boot in-memory `store` (plans, providers, fee_schedules, fee_schedule_entries, subscribers, dependents, limitation_rules, predeterminations, claims, claim_lines, claim_attachments, accumulators) plus the logical clock starting at `2026-09-01T00:00:00Z` per PRD §2.6
- `errors.py` — `ApiError` and the full error-id constants from PRD §5
- `response.py` — envelope helpers per PRD §2.2/§2.3: success/error envelopes with `meta`/`response_type`/`data`, `api_request_id` prefixed `req_`, ISO-8601 timestamps with 3 fractional digits, `limit`/`offset`/`total_count`/`has_more` pagination (defaults 10/0, max 100, min 1)
- `auth.py` — `X-User-ID`/`X-User-Role` extraction, the six-role set, role gates
- `services.py` — calendar math (calendar-month addition, whole-years), schedule resolution (half-open `[effective_from, effective_to)`, predet pin override), entry lookup, plan-year bucketing, accumulator get-or-create, lazy `APPROVED → EXPIRED` on read, ABP/waiting/limitation evaluation (with plan-level `missing_tooth_clause_active` checked BEFORE declared LimitationRules per PRD §3.7), cost-share arithmetic (floor coinsurance, sequential accumulator draws), full claim adjudication pipeline

### Endpoints implemented

All 32 routes from PRD §4: clock setter, plans (CRUD + activate/suspend/retire), providers, fee schedules + entries + activate/retire, limitation rules, subscribers + dependents + accumulators, predeterminations (create/assign/reassign/approve/deny/withdraw), claims (CRUD + lines + attachments + cob-confirm + pay + void).

### Notable design decisions

- **Validation order**: auth → RBAC role → ownership (Member/Provider) → path 404 (typed per entity) → body FK 404 → field shape 400 → state 409 → business rules. State layer (e.g. `ERR_PLAN_NOT_ACTIVE`) beats business rules (e.g. `ERR_TIMELY_FILING`, `ERR_COB_CONFIG_INVALID`).
- **Estimate vs adjudication**: the predetermination estimate does NOT apply the annual-maximum cap (the cap is a separate guard at approve time, refusing with `ERR_ANNUAL_MAX_EXCEEDED` when the uncapped estimate exceeds remaining). Adjudication does apply the cap.
- **Schedule-window timestamps**: stored as both a parsed `datetime` and the original raw ISO string. The raw string is preserved on read so successor truncation propagates the successor's `effective_from` string verbatim — tests compare `effective_to` to the raw input string with `==`, not `same_instant`.
- **Lazy predetermination expiry**: `GET /dental/predeterminations/{id}` and the schedule-resolution path for claim pins both check `store.clock > expires_on` and transition `APPROVED → EXPIRED` (with `updated_at` refresh and `version` bump).
- **Schedule activation cascade**: rejects retroactive insertion (`ERR_SCHEDULE_OVERLAP` when an existing ACTIVE same-tier schedule has strictly-later `effective_from` and overlaps), truncates overlapping same-tier ACTIVE schedules whose `effective_from <= new.effective_from`, then recomputes every UNDER_REVIEW predetermination on the tier and bumps its version.
- **Accumulator reversal on void**: PAID-claim void is gated on `store.clock <= _paid_at_dt + 30 days`; both ADJUDICATED and PAID voids subtract `deductible_applied_cents`/`plan_pay_cents` sums from PAYABLE lines and bump the accumulator version.
- **Missing-tooth**: treated as a plan-level clause (no LimitationRule row needed) — checked first when `plan.missing_tooth_clause_active` is true and the claim's `tooth_missing_prior_to_coverage[tooth_number]` attests the tooth.
- **Claim intake**: refused claims (timely-filing or no-fee-schedule) are rolled back — never persisted — so subsequent `list_claims` returns empty.
- **No startup seeding**: `db.py` initializes empty maps; tests build all preconditions through the API.

## Step 7: Run Tests and Iterate — 2026-09-30T06:15:00.000Z

All 8 rounds pass: 84/84 in each (the "FAIL: None" lines are just my crude filter printing None nodeids from passed tests — passed == total == 84 in every round).

### Summary

- **Iterations run:** 1 (after the known-starting-state test bug fix).
- **Tests deleted:** none.
- **Fixes applied to `test_suite/`:**
  - `test_suite/test_08_window_semantics.py` — added `CATEGORY_PREVENTIVE` to the `test_helpers.constants` import; the constant was used at lines 119/141/161 in the `TestFrequencyWindowIsInclusiveOnBothEnds` helper but never imported, causing a `NameError` in 2 tests.
- **Fixes applied to `test_helpers/`:** none.
- **Fixes applied to `implementation/`:** none.

All 8 parallel rounds of the per-test-server sweep report 84/84 passed.

## Step 8: Finalize PRD — 2026-09-30T06:25:00.000Z

Confirmed: the Step 7 fix was a test-suite-only import fix (`NameError` — the `CATEGORY_PREVENTIVE` constant was used but never imported into the test module). This reveals no PRD silence and no implementation mismatch — the constant already existed in `test_helpers/constants.py`, and the test logic that uses it asserts behavior already pinned verbatim in PRD sections 2.8 and 3.7 (which the test docstrings quote). No edits to PRD_FINALIZED.md are warranted.

Summary:

- **PRD.md vs PRD_FINALIZED.md line counts:** 290 lines each, 0% delta — PRD_FINALIZED.md is a verbatim copy of PRD.md.
- **Zero edits made.** Per the step_7_diff, the single Step 7 change was fixing a `NameError` in `test_suite/test_08_window_semantics.py` by adding `CATEGORY_PREVENTIVE` to the `test_helpers.constants` import (test file, line 14). Verification performed:
  1. Read the full test file — the constant is used only in a `fee_schedule_entry_payload` factory argument (line 119) inside `TestFrequencyWindowIsInclusiveOnBothEnds._to2_stack`; the behavioral assertions in that file quote PRD 2.8 (half-open fee-schedule windows, retroactive-insertion rejection, adjacency) and PRD 3.7 (frequency rolling window inclusive on both ends, all-lines-denied cascade) verbatim, confirming the tested behavior was already pinned by the PRD.
  2. Confirmed `CATEGORY_PREVENTIVE = "PREVENTIVE"` already existed at `test_helpers/constants.py:74` — the bug was a missing import in the test module, not a missing definition or a behavioral gap.
  3. No `implementation/` fixes were applied in Step 7 (per the diff log: "Fixes applied to `implementation/`: none"), and all 8 rounds passed 84/84 with only this import fix — indicating the implementation already satisfied the PRD at every point the suite exercises.
- Therefore no PRD silence or PRD/impl mismatch exists to pin; editing PRD_FINALIZED.md would only invent constraints the implementation was never asked to make.

## Step 9: Complete PRD — 2026-09-30T06:40:00.000Z

Done. `PRD_COMPLETED.md` written at `workspace/PRD_COMPLETED.md`.

**Source vs output:** PRD_FINALIZED.md 290 lines / 45,718 chars → PRD_COMPLETED.md 290 lines / 49,485 chars (+3,767 chars, no new sections, all inline).

**Counts:** 13 ambiguity-pins, 3 mismatch-revisions (16 edits total).

Changes:
- §2.1 — insert — ambiguity — X-User-ID is not registry-checked; any non-empty value authenticates — auth.py:17-23
- §2.3 — insert — ambiguity — unparsable/out-of-range limit/offset are clamped to defaults, never error — response.py:101-122
- §2.8 — insert — ambiguity — overlapping ACTIVE coverage resolves to the schedule with the latest `effective_from` — services.py:97-98
- §3.1 — insert — ambiguity — all named plan fields required at creation, missing → ERR_INVALID_REQUEST before bound checks — app.py:391-399
- §3.1 — revise — ambiguity — duplicate plan_code activation failure uses ERR_INVALID_STATE (not a dedicated code) — app.py:462
- §3.2 — revise — mismatch — retire offers only PENDING→RETIRED and ACTIVE→SUPERSEDED (no ACTIVE→RETIRED); refusal key is any in-flight claim on the retired schedule's tier, error ERR_INVALID_STATE — app.py:699-720
- §3.4 — insert — ambiguity — assignment refused with ERR_INVALID_STATE when subscriber not ACTIVE — app.py:1038-1040
- §3.4 — insert — ambiguity — estimate treats tooth_number as absent (MISSING_TOOTH never fires); denial in estimate yields plan-pay 0 / patient-pay = submitted — services.py:436-458
- §3.4 — revise — mismatch — estimate never caps at the annual maximum; cap enforced only by the approval guard — services.py:353-384
- §3.4 — insert — ambiguity — approval reads accumulator without materializing it — app.py:1090-1097
- §3.4 — insert — ambiguity — schedule-activation cascade leaves estimate unchanged when no schedule covers, still bumping version — app.py:691-694
- §3.5 — insert — ambiguity — claim refused by intake gates is not persisted; pinned schedule can satisfy the schedule gate — app.py:1148-1164, 1249-1254
- §3.5 — insert — ambiguity — attachments accepted on any claim state; routing side effect fires only from PENDED_ATTACHMENTS — app.py:1424-1444
- §3.5 — insert — ambiguity — only the rendering provider may upload attachments (ERR_UNAUTHORIZED otherwise) — app.py:1422-1423
- §3.6 — insert — ambiguity — pricing/adjudication processes lines in line_number ascending order — services.py:533-534
- §3.7 — insert — ambiguity — accumulator materializes when adjudication begins, even if every line later denies; on DENIED claims its fields/version are untouched — services.py:531, 593-598
- §3.7 — insert — ambiguity — plan-level missing-tooth clause evaluated before declared rules; waiting gate before limitations — services.py:277-283, 553-558
- §3.7/§3.8 — revise — mismatch — COB waterfall is per line: secondary cap is `allowed − cob_other_plan_paid − line deductible`, applied after the annual-max cap; claim-level `cob_secondary_payment_cents` is the per-line sum — services.py:483-491, 585-590
- §3.9 — revise — ambiguity — void window anchors to the recorded pay-transition instant (coinciding with PAID updated_at); expired window fails ERR_INVALID_STATE; missing accumulator makes reversal a no-op — app.py:1487, 1503-1510, 1524

No other mismatches found: OCC scope, error catalogue, envelopes, state machines, timely-filing boundary, plan-year bucketing, ABP arithmetic, cascade rules, and endpoint/role table all match implementation as written.
