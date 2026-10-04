# Worklog — task_3067_alternative_data_underwriting_model_bank_partner_loan

## Step 1: Create Task Directory — 2026-09-29T00:00:00.000Z

Pre-allocated task directory verified at `./tasks/task_3067_alternative_data_underwriting_model_bank_partner_loan/` with `workspace/` inside. No new index computed; no other task_* directory created.

## Step 2: Generate Scaffold — 2026-09-29T20:09:30.000Z

Scaffold generation complete. Summary:

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_3067_alternative_data_underwriting_model_bank_partner_loan/`:

1. **SCAFFOLD.yaml** (§1.0–§1.7, no design keys) — Alternative-data underwriting (Upstart-style) platform
2. **SCAFFOLD_DIFFICULTY_DESIGN.yaml** (single top-level key `scaffold_difficulty_design`)
3. **SCAFFOLD_CORNER_DESIGN.yaml** (single top-level key `scaffold_corner_design`)

## Surface counts (Expert+ band, per the "much harder than expert" instruction)

- **12 entities**: ModelVersion, Partner, CreditBox, Applicant, Application, Verification, FairnessReview, Attestation, Loan, ServicingEvent (append-only, `common_fields: false`), SecuritizationPool, AllocationDecision
- **49 endpoints** including a `/_clock/set_current_utc` test-driving endpoint (default 2026-09-01T00:00:00Z)
- **24 error codes**; 13 ordered validation priorities
- **10 calculations** (risk scoring with cash-flow stress variant, approved-amount with manual-review haircut variant, 4-step allocation waterfall, payment waterfall with pinned bucket order, amortization, late fees, disparate impact, attestation, DTI, instant verification)
- **6 state machines** + 3 OCC concurrency rules (Partner/ModelVersion/Loan)
- **7 roles** with segregation-of-duties (creator≠validator, instant-checker≠manual-decider, partner-activator≠charge-off agent)

## §1.8 / §1.9 instance counts

- **§1.8: 18 instances** — exactly 2 per rule across all 9 Difficulty Rules; dual variants on different entity domains (scoring vs underwriting amount), combinatorial modes (a) and (b), different error-category pairs, different boundary metrics, different entity pairs, different interval semantics (instant-in-window vs calendar-month bucket), different conserved quantities (pool principal vs partner funded balance)
- **§1.9: 37 active instances** across 9 taxonomy sections (entities, state_machines, calculations, validations, endpoints, errors, roles_rbac, cross_cutting_layers, consistency_model) + **12 excluded_because stubs** pointing back at §1.8 instances

## Verification

- `scaffold_lint.py` verdict: **clean lint** — 567 calls scanned, all §1.8/§1.9 calls conform to §1.5, all FKs reverse-reachable
- Instance names unique across both design files; every `grounds:` reference resolves; every `${var}` placeholder is bound by an earlier `captures:`; OCC version inputs use `${var}` expressions (e.g., `${bank_v0} + 1`), never literals
- No forbidden concurrency vocabulary; numeric asserts pre-computed (score 50/49/95/100, approved 5000000 vs 3600000, monthly payment 166072, late fee 1500, attestation 5000/5500/−500 bps)
- No sibling task directories were read at any point

## Step 3: Copy Shared Files — 2026-09-29T20:09:45.000Z

Copied `./INSTRUCTION.md` → `tasks/task_3067_alternative_data_underwriting_model_bank_partner_loan/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-29T20:16:40.000Z

All contracts pass. PRD generation complete.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3067_alternative_data_underwriting_model_bank_partner_loan/workspace/PRD.md` — 280 lines.

**Section overview:**
- **§1 Introduction** (2 paragraphs) — alternative-data scoring, model governance, verification with manual fallback, allocation waterfall, servicing/collections, logical clock.
- **§2 Global Specifications** (10 subsections) — §2.1 RBAC with all seven roles (`PlatformAdmin`, `RiskOfficer`, `PartnerAdmin`, `VerificationOfficer`, `ServicingAgent`, `CollectionsAgent`, `Auditor`), each with opaque `X-User-ID` identity prose; §2.2 fixed response-envelope block emitted verbatim; §2.3 pagination (limit 10/1/100, offset 0, `created_at` ascending, plus list-filter parameters); §2.4 common resource properties including the `common_fields: false` exception for `ServicingEvent`/`AllocationDecision`; §2.5 logical clock (initial reading `2026-09-01T00:00:00Z`, `to_iso8601`/`current_utc`); §2.6 integer-cents money, APR-as-percent, basis points, round-half-up; §2.7 left-to-right path validation and body-FK resolution order; §2.8 the three OCC rules (`expected_model_version`, `expected_partner_version`, `expected_loan_version` → `ERR_STALE_VERSION`/412); §2.9 the full 13-layer validation priority ordering; §2.10 the three segregation-of-duties custody boundaries.
- **§3 Business Logic** (10 subsections) — model lifecycle and governance gates; fairness reviews and attestation math (500 bps base + 10 bps per point below 550, floor 0); partner/credit-box/pool lifecycle with offboard cascades and suspension eligibility exclusion; applicant registration and submission branching (floor-reject at clamped score below 300, `SUBMITTED`→`DECLINED` vs `VERIFICATION_PENDING`); risk-score weighted formula with the 0.9 cash-flow stress variant and round-then-clamp order; instant verification thresholds (nsf strictly below 3, tenure at least 3, bureau at least 500) and manual-review fallback with bubble-ups; affordability with the 0.40/0.32 DTI variants, ×30 term multiplier, and `AFFORDABILITY_ZERO`; disparate-impact four-fifths rule with exact-rational comparison; the five-step allocation waterfall with all ten reason codes in first-failure order; amortization, payment waterfall (late fees → interest → principal, no re-rounding), 30-day servicing advances, the 90→120 default step, capped 5%/1500-cent late fees, charge-off with securitization pool release, and the servicing-event ledger.
- **§4 Endpoint Definitions** — 4-column table, all 49 endpoints.
- **§5 Error Code Catalogue** — 2-column table, all 24 error IDs.

**Hard contract reports:**
- Field coverage: entity fields 78/78, request-body 47/47, query params 20/20, path params 3/3 — 0 missing. **PASS**
- Rule coverage: all state-machine transitions (preconditions + error IDs + side effects), all 9 calculations (precise prose, no pseudocode), all 13 validation priorities with ordering, all 3 OCC rules, all endpoint side effects, validation-priority prose, and sibling-branch symmetry verified manually against the scaffold. **PASS**
- §3 path purity: 0 backticked tokens in §3 matching path/method patterns (all §3 tokens are field names, state values, or error IDs). **PASS**

**Design-file constraint confirmed:** `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, read, grepped, or referenced. Only `SCAFFOLD.yaml`, the doc-generator skill files, and the reference `example-prd.md` were read.

## Step 5: Generate Unit Tests — 2026-09-29T20:38:00.000Z

Generation complete. All audits pass.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3067_alternative_data_underwriting_model_bank_partner_loan/`):

`test_helpers/` (Stage 1, 9 files):
- `types.py` — 14 status/type enums + 13 entity TypedDicts; ServicingEvent/AllocationDecision correctly modeled as immutable (id + created_at only, no updated_at/version)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (35 methods)
- `api_errors.py` — 24 `ApiErrorId` values + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (all roles opaque identity per PRD 2.1 — shared constants are canonical), `fixtures.py` (composite chains: `create_active_model` full governance walk, `attach_active_credit_box` with OCC version re-read, `pass_all_instant_checks`, `fail_income_instant_check`, `manual_pass_verification`, `setup_underwritten_application` incl. manual-review haircut path, `setup_funded_loan`, `setup_securitized_loan`, `advance_loan_periods`), `__init__.py` barrel

`test_suite/` (Stage 2, 7 files, **81 tests**):
- `conftest.py` + `test_01_model_governance.py`, `test_02_applications_scoring.py`, `test_03_partners_credit_boxes.py`, `test_04_allocation_waterfall.py`, `test_05_loan_servicing.py`, `test_06_attestation_and_security.py`

**Test counts per queue**: Queue A (Difficulty): 18/18 instances, each ≥2 tests (36 tags). Queue B (Corner): 25/25 non-stub instances, each ≥1 test (28 tags). 12 `excluded_because` stubs not translated — all cross-references resolve to real difficulty instances.

**Instances skipped: none.** Every non-stub instance passed the PRD-first two-condition filter. One queue-B instance (`securitization_pool_close_from_closed_is_rejected`) was initially missed and added in a fix pass before final audit.

**Notable adjudications**:
- `risk_score` formula docstring mismatch caught: the single-quote test's regex check surfaced my own docstring; the actual quote-audit is quote-aware.
- Priority-pair instances kept: PRD 2.9 states the full validation ordering explicitly, so both precedence tests are uniquely derivable.
- Attestation instance: wired `partner_admin_nine` as activator so the `pa-one`-created partner's charge-off SoD check can't false-fire (activator is `pa-nine`, charge-off by `ca-one`).
- Corner recipe's `${bank_v0}+1` version arithmetic replaced with re-read-current-version (identical outcome, more robust).

**Stage 1/Stage 2 audit results**:
- All 17 files compile; `pytest --collect-only` collects 81 tests cleanly.
- Tag audit: 81 Design tags, 0 unknown, 0 shortfalls, 0 dual/missing tags (each docstring ends with exactly one Design line as its last line).
- Citation audit: every test docstring carries at least one quoted citation whose normalized text matches PRD.md verbatim (133 quotes checked after quote-aware re-run; 4 initially failing quotes were corrected to verbatim PRD wording).
- Zero `pytest.mark.skip`/`skipif`/`xfail` markers.
- All `from test_helpers import ...` names resolve against the barrel; conftest `TEST_USERS` keys verified.

## Step 6: Generate Implementation — 2026-09-29T20:57:10.000Z

Clean. Final summary:

## Implementation complete — task_3067

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3067_alternative_data_underwriting_model_bank_partner_loan/workspace/implementation/`):

- `start.sh` — foreground launcher, guarded `pip install` (no-op once flask present), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask entry point, error handlers (ApiError → envelope; 404/405 → `ERR_NOT_FOUND`; unexpected → `ERR_VALIDATION` 400)
- `db.py` — in-memory store, logical clock pinned to `2026-09-01T00:00:00Z`, zero seeding
- `errors.py`, `response.py`, `middleware.py`, `helpers.py` — error catalog, envelope (`meta`/`response_type`/`data` + `limit/offset/total_count/has_more`), `X-User-ID`/`X-User-Role` auth + 7-role RBAC, pagination/serialization/input validation
- `services.py` — risk_score (weighted, 0.9 cash-flow stress, round-half-up then clamp), DTI, affordability (0.40/0.32 haircut variants, floor at each step), disparate impact (exact rational 4/5 rule), amortization, late fees, allocation waterfall, attestation bps
- `routes.py` — all 49 endpoints

**Endpoint count:** 49 routes registered (matches the 49-row endpoint table in PRD §4 exactly).

**Key behaviors verified via in-process test runs:**
- Model lifecycle with SoD (creator ≠ validator), governance gates (`ERR_FAIRNESS_GATE_BLOCKING` before `ERR_EXCLUSION_REVIEW_OPEN`), `ERR_MODEL_ALREADY_ACTIVE`, `ERR_MODEL_LOCKED`, OCC `expected_model_version`
- Partner lifecycle, credit-box activation window on the logical clock, OCC `expected_partner_version`, supersede cascade, offboard fiscal guard + box/pool cascades
- Application submission: model snapshot, floor-reject (clamped score ≥ floor but < 300 → DECLINED, no verifications), inline verification rows, referral structural rules, body-FK order
- Verification: instant thresholds (nsf<3, cashflow>0, months≥3, bureau≥500), bubble-ups, manual-review SoD, manual haircut approved amount (0.32 variant)
- Allocation waterfall: referral → retained (created_at order) → whole-loan (no volume cap) → securitization pools → UNALLOCATED with reason-code trail and `AFFORDABILITY_ZERO`
- Servicing: FUNDED→CURRENT on first clock advance (and immediately on day-1 funding), waterfall payments (fees→interest→principal, no re-round), delinquency 30/60/90→DEFAULTED at 120, late-fee cap 1500/period accumulating, catch-up to CURRENT, payoff events, charge-off SoD vs partner activator, securitization pool balance release, charged-off still counts toward `funded_balance_cents`
- Envelope, pagination meta, filters, left-to-right nested 404s, 401/403 ordering

**Boot smoke test:** `PORT=18167 bash start.sh` booted clean from a fresh process; `GET /platform/model-versions` without headers returned 401 `ERR_UNAUTHENTICATED`; `POST /platform/_clock/set_current_utc` as PlatformAdmin returned 200 with `current_utc`. Launcher PID killed; the two stray python child PIDs spawned during smoke testing were also killed by exact PID (verified ports free afterward — no other pipelines touched).

## Step 7: Test/Fix Iteration Loop — 2026-09-29T21:49:00.000Z

All 8 parallel rounds pass 81/81. Sweep complete.

## Summary

**Iterations run:** 5 eight-round sweeps (38 → 60 → 38 → 77 → 80 → 81 passing per round).

**Tests deleted:** none. Every failing test traced to a verbatim PRD sentence; all failures were fixture/test bugs or two genuine implementation bugs.

**Fixes applied to `test_helpers/`:**
- `factories.py` — `BUREAU_ONLY_VARIABLES` weight 1 → 6: the default applicant (bureau 575) now scores exactly 300. Root cause of ~43 cascading failures: the default fixtures produced score 50, which falls inside PRD 3.4's verbatim floor-reject band ("clamped risk_score at least score_floor but below 300 → DECLINED") for every possible model configuration (clamping forces stored score ≥ score_floor, so no floor setting both preserves a stored 50 and skips the band). The default applicant docstring and model payload comments updated to document the 300-scale derivation; score_floor/score_ceiling defaults stay 0/1000.
- `fixtures.py` — `advance_loan_periods`: the default logical clock starts 2026-09-01 (first of month), so loans enter CURRENT immediately at funding per PRD 3.10's first-of-month rule, and `periods` advances landed the loan at `(periods+1)*30` days (breaking late-fee, delinquency, DEFAULTED, charge-off, and attestation setups). Now moves the clock forward one day first so `periods` advances produce exactly `periods*30` days delinquent.

**Fixes applied to `test_suite/`:**
- `test_02_applications_scoring.py` — high-score / bureau-only / smuggled-fields tests: pinned `risk_score` 50 → 300 (the 50 was unreachable on the VERIFICATION_PENDING branch under the PRD floor-reject sentence). Cashflow stress test: bureau variable weight 6, expected score 95 → 345 (unstressed guard 100 → 350). Floor-reject test simplified to default model (score 0 already hits the branch). `test_manual_decision_rejected_until_instant_check_fails`: after failing only the INCOME instant check, the sibling IDENTITY verification is still PENDING, so PRD 3.6's "no verification still unresolved" clause keeps the application in DOCS_REQUIRED — the test now asserts DOCS_REQUIRED plus ERR_VERIFICATION_INVALID_STATE on re-deciding the MANUAL_PASSED verification.
- `test_04_allocation_waterfall.py` — min-score boundary tests moved to the 300 scale (box min_score 300 inclusive / 301 for one-below; a 299 score would floor-reject at submission). Three `loan["status"] == "FUNDED"` assertions → `"CURRENT"` (PRD 3.10: funding on the first of the month enters CURRENT immediately). Pool-cascade test: `originated_this_month_count` 1 → 0 — PRD 3.3 counts only PARTNER_RETAINED/REFERRAL_RETAINED loans, and this loan is SECURITIZATION.
- `test_06_attestation_and_security.py` — expected_default_rate_bps 5500 → 3000 and variance −500 → 2000 (held-book average risk_score is now 300: 500 + 10·(550−300)).
- `test_01_model_governance.py` — locked-edit guard asserts unchanged weight 6 (was 1) to match the new default variables.

**Fixes applied to `implementation/`:**
- `services.py` — `run_allocation`: retained-channel banks/credit unions are evaluated in creation order regardless of status, so a SUSPENDED partner is recorded with `PARTNER_INACTIVE` (PRD 3.9 "each rejection … is recorded"; PRD 3.3 suspension still excludes the box from eligibility). `create_loan`: stamps `_interest_per_period_cents` (per-period scheduled interest at funding per PRD 3.10) for catch-up computation.
- `routes.py` — `post_payment`: cure condition now implements PRD 3.10's "covers the accrued late fees in full and the scheduled interest in full for every elapsed unpaid period" — fees fully drained AND interest paid ≥ per-period interest × elapsed unpaid periods (days_delinquent/30); the post-payment `recompute_scheduled_interest` call was removed since the waterfall forbids re-rounding (it was silently zeroing a one-cent interest shortfall and wrongly curing the loan).

No endpoints, fields, or checks were added beyond PRD scope; storage remains in-memory only. No stray server processes were left running (all smoke-test PIDs killed individually).

## Step 8: Finalize PRD — 2026-09-29T21:52:00.000Z

Both edits are in place. Line counts are equal (279 each; in-place sentence revisions), with 4 changed lines total (2 removed + 2 added).

## Summary

**PRD.md vs PRD_FINALIZED.md:** 279 lines → 279 lines (0% line-count delta; 2 sentences revised in place, no sections added).

**Changes (2 total):**
- **§3.9 (Allocation Waterfall, retained channel)** — revise — candidacy wording changed from "every partner of type `BANK` or `CREDIT_UNION` in `ACTIVE` status is considered in order of creation" to "every partner of type `BANK` or `CREDIT_UNION` is considered in order of creation … regardless of its current status — so that a partner not in `ACTIVE` status is still evaluated and its rejection is recorded"; eligibility requirement "the partner is `ACTIVE`" retained — `implementation/services.py:303-311` (bank/CU filter has no status filter; `consider_partner` at services.py:260-262 records `PARTNER_INACTIVE` for non-ACTIVE partners).
- **§3.10 (Loan Funding, Amortization, and Servicing, cure condition)** — revise — added two sentences after the cure sentence pinning the catch-up computation: elapsed unpaid periods = current `days_delinquent` divided by thirty; scheduled interest due = per-period interest computed at funding on the then-outstanding principal (frozen, never recomputed as principal amortizes) times elapsed periods; explicitly states no interest recomputation happens when a payment is posted — `implementation/routes.py:937-948` (`elapsed_periods = days_delinquent // 30`; `interest_due = _interest_per_period_cents * elapsed_periods`) and `implementation/services.py:184` (`_interest_per_period_cents` stamped at funding).

**Step-7 diff items assessed but requiring no PRD edit (pure fixture/test bugs, or behavior PRD already pinned verbatim):**
- `factories.py` weight 1→6 and all test score-scale moves (50→300, 95→345, min_score 300) — fixture bugs; PRD 3.5 scoring formula already matches `services.py:47-77` exactly.
- `fixtures.py` `advance_loan_periods` +1 day and `FUNDED`→`CURRENT` test assertions — fixture bug; PRD 3.10/2.5 already pin "immediately at funding when the funding day is the first of the month" matching `services.py:188-191` and `routes.py:57-63`.
- `originated_this_month_count` 1→0 — PRD 3.3 already restricts the counter to PARTNER_RETAINED/REFERRAL_RETAINED, matching `services.py:19-30`.
- `test_06` expected_default_rate_bps/variance — PRD 3.2 formula matches `routes.py:308-330` verbatim.
- `test_manual_decision_rejected_until_instant_check_fails` (DOCS_REQUIRED + ERR_VERIFICATION_INVALID_STATE) — PRD 3.6 already pins both the unresolved-verification clause and the INSTANT_FAILED/MANUAL_REVIEW-only decision set, matching `routes.py:789-798, 838-841`.
- `test_01` locked-edit weight 6 — fixture-driven, no behavioral content.

**Per-edit pre-edit search log:**

*Edit 1 (§3.9 retained channel):*
- (a) Subject: which BANK/CREDIT_UNION partners enter the retained-channel evaluation loop and how non-ACTIVE partners are recorded.
- (b) Enumerated paths: `services.py:249-361` `run_allocation` (all four channel steps), `consider_partner` (services.py:257-271, the `PARTNER_INACTIVE` recording used by both REFERRAL_RETAINED and PARTNER_RETAINED), `retained_reject_reasons` (services.py:203-224), `buyer_reject_reasons` (services.py:227-246, ACTIVE-only filter at services.py:317 — untouched by edit), pool filter (services.py:326-331), referral step (services.py:293-296, evaluates any existing referral partner — consistent with the new "regardless of status" wording for retained channels), `routes.py:759` allocate call site, PRD 3.3 suspension semantics (services.py:260-262 vs retained_reject_reasons).
- (c) Wording adjustment: added the rationale clause "so that a partner not in `ACTIVE` status is still evaluated and its rejection is recorded" and kept "Eligibility … requires … the partner is `ACTIVE`" verbatim so the sentence covers both recording behavior (new) and exclusion-from-eligibility (PRD 3.3, unchanged).

*Edit 2 (§3.10 cure condition):*
- (a) Subject: definition of "scheduled interest in full for every elapsed unpaid period" and whether scheduled interest is recomputed at payment time.
- (b) Enumerated paths: `routes.py:895-951` `post_payment` (waterfall, payoff branch resetting delinquency, delinquent cure branch, PAYMENT_APPLIED/PAYOFF_RECORDED events), `services.py:155-157` `recompute_scheduled_interest` (called only at loan creation, services.py:187), `services.py:184` `_interest_per_period_cents` stamped at funding, `services.py:160-192` `create_loan` (FUNDED→CURRENT first-of-month), all `days_delinquent` mutations (`routes.py:924, 938, 947, 963, 970, 974`; `services.py:179`), `advance_servicing` (routes.py:954-982), `charge_off` (routes.py:985-1008), clock advance (routes.py:57-63).
- (c) Wording adjustment: scoped the "never recomputed" claim to the per-period amount "for catch-up purposes" (rather than claiming `scheduled_interest_cents` is never recomputed anywhere — it is recomputed once at creation, and the same value results anyway); phrased "computed at funding on the then-outstanding principal" to stay true even if a future path re-derived the field, and kept the existing "per-payment split is never re-rounded" sentence untouched to avoid double-statement conflicts.

## Step 9: PRD Completeness Scan — 2026-09-29T22:04:00.000Z

Task complete. `PRD_COMPLETED.md` was produced at `/home/ubuntu/github/CodingPRD/tasks/task_3067_alternative_data_underwriting_model_bank_partner_loan/workspace/PRD_COMPLETED.md` as a minimal patch over `PRD_FINALIZED.md`.

**Source vs output:** `PRD_FINALIZED.md` 279 lines / 47,273 chars → `PRD_COMPLETED.md` 279 lines / 53,288 chars (net +6,015 chars; +8,478 added / −2,499 removed). No new sections; all changes are in-paragraph inserts/revisions.

**Counts:** 18 ambiguity-pins, 2 mismatch-revisions (20 changes total).

Changes:

- §2.2 — insert — ambiguity — `api_request_timestamp` pinned to host wall clock (not the §2.5 logical clock) — implementation/response.py:17-19
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` rejected with `ERR_VALIDATION`; `has_more` defined as `offset + len(items) < total_count` — helpers.py:89-104, response.py:43
- §2.4 — insert — ambiguity — `created_at`/`updated_at` explicitly read from the logical clock — helpers.py:56-58, 68, 76
- §2.5 — insert — ambiguity — clock setter accepts any ISO instant (no monotonicity), applies FUNDED→CURRENT on every set in loan creation order, returns `current_utc` with 3 fractional digits — routes.py:45-65
- §2.8 — revise — mismatch — version fields on the three OCC endpoints are optional (absent → no check); PRD said "require" — routes.py:146-148, 566-568, 907-909
- §3.1 — insert — ambiguity — model create: `calibration_note` optional/nullable, empty `variables` and unvalidated weights allowed at create; creator recorded as `created_by_user_id`; all lifecycle mutations and fairness-report restamps increment `version` per §2.4 — routes.py:88-113, helpers.py:75-78
- §3.1 — insert — ambiguity — model edit: `ERR_MODEL_LOCKED` checked before `ERR_STALE_VERSION` — routes.py:141-148
- §3.1 — insert — ambiguity — pinned `fairness_report` object shape (`approval_rate_group_a`, `approval_rate_group_b`, `disparate_impact_ratio` as floats, `outcome`) — services.py:129-134
- §3.2 — insert — ambiguity — fairness reviews re-decidable (later decision overwrites); DISPARATE_IMPACT decision restamps `fairness_report` only while model is `VALIDATED`/`ACTIVE` — routes.py:280-287
- §3.2 — revise — mismatch — attestation issuable in any model/partner state (removed "once a model is in service"); `period_label` is free-form; replaced "floored at zero" with "no adjustment when average ≥ 550" (impl's `max(0, 550-avg)` clamps the shortfall, not the rate) — routes.py:295-343
- §3.3 — insert — ambiguity — new partner pins `active_credit_box_id`/`activated_by_user_id` null; reactivation overwrites `activated_by_user_id`; partner responses expose computed `originated_this_month_count` and `funded_balance_cents` on get and list — routes.py:369-420, 431-432
- §3.3 — insert — ambiguity — offboard restricted to `ACTIVE` partners; cascade also clears `active_credit_box_id` to null when its box left `ACTIVE` — routes.py:456-475
- §3.3 — insert — ambiguity — credit-box activation check order pinned (box DRAFT → partner ACTIVE → bands → window → version) — routes.py:556-568
- §3.3 — insert — ambiguity — pool creation resolves `trust_partner_id` existence (`ERR_REFERENCED_NOT_FOUND`) but does not enforce `SECURITIZATION_TRUST` type — routes.py:1034-1036
- §3.4 — insert — ambiguity — PARTNER_REFERRAL: missing referral id → `ERR_INVALID_REQUEST`, unresolvable → `ERR_REFERENCED_NOT_FOUND` — routes.py:667-674
- §3.5 — insert — ambiguity — degenerate `min == max` variable contributes full `weight × 100`; unknown applicant field treated as 0; contributions computed in floating point — services.py:54-66
- §3.6 — insert — ambiguity — instant-check bubble-up generalized (all other verifications `INSTANT_PASSED`); checker recorded as `instant_checker_user_id`; manual decision requires application `DOCS_REQUIRED`, segregation check precedes outcome validation, outcome matched case-insensitively (`PASS`/`PASSED`/`MANUAL_PASSED`, `FAIL`/`FAILED`/`MANUAL_FAILED`) — routes.py:801-866
- §3.9 — insert — ambiguity — allocate rejects non-`UNDERWRITTEN` with `ERR_APPLICATION_INVALID_STATE`; buyer rejection codes pinned to the retained code set (incl. `NO_ACTIVE_CREDIT_BOX`); pool evaluation records the trust partner id in `candidate_partner_ids`; both pool checks fail → `POOL_SINGLE_LOAN_EXCEEDED` first — routes.py:757, services.py:227-246, 275, 277-281
- §3.9 — insert — ambiguity — securitization placement pins loan `apr` to `0` (no allocating credit box); unallocated trail appends `AFFORDABILITY_ZERO` when approved amount ≤ 0 — services.py:348, 354-355
- §3.10 — insert — ambiguity — zero-APR amortization (principal/term rounded half up); new-loan initial fields (`late_fee_accrued_cents`/`days_delinquent` 0, `outstanding_principal_cents` = principal) — services.py:164-167, 177-184
- §3.10 — insert — ambiguity — payment amount must be a positive integer; payoff resets `days_delinquent`/`late_fee_accrued_cents` and records both `PAYMENT_APPLIED` and `PAYOFF_RECORDED` with the posted amount; `scheduled_interest_cents` bucket is not reduced by principal paydown; `funded_balance_cents` is a computed read over principals, so payment "recomputation" never changes it — routes.py:903-949
- §3.10 — insert — ambiguity — charge-off pool release targets the holder trust partner's still-`OPEN` pool — routes.py:1001-1006

Notable verified non-changes (PRD already uniquely pinned): scoring formula order/clamp, DTI formula, affordability 40%/32% ×30, disparate-impact rational arithmetic, allocation waterfall priority and reason-code order, late-fee cap formula, default at exactly 90→120, servicing event vocabulary, endpoint table, and error catalogue.
