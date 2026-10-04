# Worklog — task_3481_disaster_loan_application_damage_verification_servicing

## Step 1: Create task directory — 2026-10-02T13:30:00.000Z

Task directory pre-allocated by the caller: `./tasks/task_3481_disaster_loan_application_damage_verification_servicing/` with empty `workspace/` inside. Verified existence; no new index computed, no other task_* directory created. User instruction for scaffold difficulty: "Generate task much harder than expert level!" (applies to Step 2 only).

## Step 2: Generate scaffold — 2026-10-02T14:40:00.000Z

All audits pass. The three scaffold artifacts are complete and mutually consistent.

**Task**: `task_3481_disaster_loan_application_damage_verification_servicing` — SBA-style disaster loan declaration, intake, verification, staged disbursement, clawback, and servicing. Generated purely from the scenario + skill spec (no sibling tasks consulted).

**Design shape** (deliberately past Expert band, inside pipeline-safe limits): compliance_audit × workflow_orchestration archetype blend, 14 entities, 11 state machines (reconsideration cycle, dispute cycle, Loan with parallel lifecycle × servicing dimensions), 8 calculation rules, 23 ordered validations, 38 error codes, 8 roles with segregation-of-duties (milestone verifier ≠ damage verifier on the same loan), 2 OCC concurrency rules (modification-create, settlement-apply), logical clock with pinned default 2026-09-01T00:00:00Z.

**(1) Line counts**
- SCAFFOLD.yaml: 2085
- SCAFFOLD_DIFFICULTY_DESIGN.yaml: 1367
- SCAFFOLD_CORNER_DESIGN.yaml: 2276

**(2) API endpoints declared: 40** (held at the ≤40 pipeline-safety line; includes the unprefixed `POST /_clock/set_current_utc` test-driving endpoint).

**(3) Non-stub instances, counted from YAML**
- §1.8 difficulty: **18** (9 rules × exactly 2; every §0.5 differentiation clause honored — dual variants on DamageVerification vs Loan; combinatorial modes (a) and (c); cascades depth-3 vs depth-2 from different triggers; state×fiscal and temporal×referential priority pairs; collateral-amount vs credit-score boundaries on different endpoints; application×declaration and tranche×milestone cross-entity gates; half-open vs inclusive-closed interval semantics on different resources; principal-stock vs commitment-stock invariants)
- §1.9 corner: **38** non-stub (+4 `excluded_because` stubs citing §1.8 instances; 42 total), spanning all nine taxonomy sections

**(4) YAML validity**: all three files parse clean with `yaml.safe_load` (re-verified after every append). Official lint verdict, verbatim: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (684 calls scanned, 0 violations). Additional self-audits passed: all grounds refs resolve, all 38 error codes referenced by a validation/transition, no forbidden concurrency vocabulary, no name collisions across files, all formula-derived asserts are pre-computed integer literals (e.g., STANDARD payment 85675 vs DEFERRED_CAPITALIZED 88352; interest 28896 over 30 days on 11250000; late fee 4418; clawback excess 7250000).

**(5) Named constants** (all defined exactly once, in `calculations[].constants` or entity/validation prose):
- CLOCK default: 2026-09-01T00:00:00Z (startup, no wall-clock fallback)
- PHYSICAL_FILING_WINDOW_DAYS = 90; EIDL_FILING_WINDOW_DAYS = 270
- HOMEOWNER_PHYSICAL_CAP_CENTS = 50000000; RENTER_PHYSICAL_CAP_CENTS = 10000000; BUSINESS_PHYSICAL_CAP_CENTS = 200000000; EIDL_CAP_CENTS = 200000000
- PHYSICAL_COLLATERAL_THRESHOLD_CENTS = 2500000; EIDL_COLLATERAL_THRESHOLD_CENTS = 5000000 (strictly-greater)
- ESTIMATION_MAX_CENTS = 2500000; MAX_DEPRECIATION_PCT = 0.90
- MIN_CREDIT_SCORE = 640; MAX_DTI_PERCENT = 43 (inclusive, integer cross-multiplication)
- INTEREST_RATE_PERSONAL = 0.03125; INTEREST_RATE_BUSINESS = 0.04
- TERM_MONTHS_HOMEOWNER = 360; TERM_MONTHS_RENTER = 84; TERM_MONTHS_BUSINESS = 360; TERM_MONTHS_EIDL = 360
- DEFERRAL_MONTHS = 12; INITIAL_DISBURSEMENT_CAP_CENTS = 2500000
- DAYS_IN_YEAR = 365; LATE_FEE_GRACE_DAYS = 15; LATE_FEE_PCT = 0.05
- DELINQUENT_AFTER_DAYS = 30; DEFAULT_AFTER_DAYS = 120; CHARGE_OFF_AFTER_DAYS = 180 (all inclusive boundaries)
- EXCESS_FUNDS_DUE_DAYS = 30; DISPUTE_WINDOW_DAYS = 30 (inclusive); MAX_RECONSIDERATIONS = 2; ACCOMMODATION_MAX_DAYS = 360

Two self-audit fixes were applied mid-draft: a dead state-gate (`ERR_VERIFICATION_REQUIRED` was unreachable — rewired to gate approval when the latest verification is DISPUTED) and a shadowed rollup error (`ERR_DECLARATION_CLOSED` could never fire ahead of the per-purpose deadline errors — removed).

Orchestrator verification (independent of subagent report): all three files re-parsed with yaml.safe_load — OK. Independent instance counts from YAML: difficulty 18 non-stub / 0 stub across 9 rules; corner 38 non-stub / 4 stub across 9 sections (entities 5, state_machines 9+1stub, calculations 5, validations 5, endpoints 3, rbac 3, cross_cutting_layers 2, consistency_model 1, errors 5+3stub). Every non-stub instance has a test_recipe.assert. api_prefix=/disaster-relief, domain matches task. Endpoints=40, errors=38, entities=14, state_machines=11, calculations=8.

## Step 3: Copy shared files — 2026-10-02T14:44:00.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T15:05:00.000Z

All checks pass. The PRD is complete and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3481_disaster_loan_application_damage_verification_servicing/workspace/PRD.md` — 310 lines, ending cleanly at §5 (verified by tail read).

**Endpoint coverage:** 40/40 scaffold endpoints appear verbatim as Method+Path rows in the §4 table (verified by parsing the scaffold YAML and regex-matching each pair against the PRD's table rows).

**Error coverage:** 38/38 error codes appear verbatim in the PRD, each with its exact HTTP status in the §5 table and its trigger rule in §2/§3 prose (verified programmatically; 0 missing).

**Constant coverage:** all 22 calculation constants plus the extras referenced in entity/state-machine prose appear with concrete values — 90/270-day filing windows, 640 min credit score, 43% DTI cap, 0.03125/0.04 rates, 360/84/360/360 terms, 12-month deferral, 2500000/5000000 collateral thresholds, 50000000/10000000/200000000/200000000 caps, 2500000 estimation max and initial tranche cap, 0.90 max depreciation, 30-day dispute window, 30-day receivable due window, 360-day accommodation max, 2 reconsiderations, 365-day accrual basis, 15/30/120/180 aging rungs, 0.05 late-fee rate, and the 2026-09-01T00:00:00Z clock default (verified programmatically; 0 missing).

**Hard-contract results:**
- Contract 1 (field names): 89 required entity/input/query identifiers, 89 present in backticks, 0 missing.
- Contract 2 (rules): validation priority ordering stated globally in §2.6 plus the three pinned per-endpoint orderings (deadlines before county eligibility; verification-state gate before fiscal checks on approval; overlap before default-admissibility on servicing approval); both OCC rules name endpoint + `expected_loan_version` + `ERR_STALE_VERSION`/412; all state-machine transitions, cascades (approval 2-hop, release 3-hop, DEFAULT cascades, settlement apply/void compensation, payment reversal), all 8 calculations with pinned evaluation orders, and sibling-branch symmetry rendered.
- Contract 3 (§3 path purity): 518 backticked tokens in §3, 0 path/method violations (all endpoint references use state-transition or role+verb framing).

**Ambiguities resolved:**
1. `declaration_number`/`email` uniqueness has no catalog error_id in the scaffold — stated as a prose uniqueness rule without inventing an error code.
2. Receivable-payment boundary: scaffold's `<=` precondition means exact-remaining payment is allowed and yields `PAID` — stated explicitly.
3. Submit-time gate order reconciled between the transition's precondition list and the global validation priorities (ownership → declaration existence → DRAFT state → deadline → county eligibility).
4. Late-fee rate given both as prose ("5 percent") and literal (0.05) to pin the constant unambiguously.
5. §2.2 emitted byte-verbatim from the skill's canonical block; fenced JSON blocks there required fence-stripping in the coverage checker (initial token-extraction false-alarmed on the ``` fences — resolved, not a document defect).

Orchestrator spot-check: PRD.md is 310 lines; clock endpoint present and UNPREFIXED (`POST /_clock/set_current_utc`, line 226); 38 unique ERR_* tokens; 40 endpoint table rows; collateral thresholds 2500000/5000000 and caps present with values; approved-amount 4-step order and approval 2-hop cascade rendered in prose.

## Step 5a: Generate test helpers (Stage 1 of split Step 5) — 2026-10-02T15:40:00.000Z

All checks pass. Stage 1 is complete.

**Task:** Stage 1 helper infrastructure for `task_3481_disaster_loan_application_damage_verification_servicing`. No `test_*.py` files were created (Stage 2's job).

### (1) File list with line counts

```
   42 test_helpers/__init__.py
  243 test_helpers/api_client.py
   94 test_helpers/api_errors.py
  292 test_helpers/assertions.py
  130 test_helpers/constants.py
  226 test_helpers/factories.py
  646 test_helpers/fixtures.py
  110 test_helpers/test_users.py
  370 test_helpers/types.py
   58 test_suite/conftest.py
```
All under `/home/ubuntu/github/CodingPRD/tasks/task_3481_disaster_loan_application_damage_verification_servicing/`.

### (2) py_compile / import-smoke results (verbatim)

```
IMPORT SMOKE OK          # python3 -c "import test_helpers.api_client, ..."
CONFTEST COMPILE OK      # python3 -m py_compile test_suite/conftest.py
factory sanity OK        # verification-pairing sentinel, unique emails, collateral inclusion, canonical declaration
```
Each file was also individually `py_compile`d right after writing (all OK). Endpoint audit: all 40 scaffold endpoint rows map to an ApiClient method (`missing: none`).

### (3) Unprefixed-path convention in api_client

`ApiClient._p(path)` prepends `API_PREFIX = "/disaster-relief"` and **raises ValueError if the path starts with `/_`**, so a platform path can never be prefixed by accident. The clock method posts to the literal root path: `set_clock(current_utc, headers)` → `POST /_clock/set_current_utc` (no prefix), matching PRD §2.4/§4.

### (4) Factory functions

- `create_declaration_payload` — canonical DR-4821 (declared 2026-10-01; counties 06037 both purposes, 06059 EIDL-only)
- `create_applicant_payload` — unique email per call via process counter
- `create_application_payload` — DRAFT create body (applicant_id never in body)
- `credit_review_payload` — credit_score + verified debt only
- `create_verification_payload` — `_UNSET` sentinel: depreciation_pct auto-included at 0.20 only for ACTUAL_CASH_VALUE; explicit None forces omission for negative tests
- `complete_verification_payload`, `application_decision_payload` (collateral only when given), `grant_award_payload`, `milestone_payload`, `milestone_decision_payload`, `modification_request_payload` (with `expected_loan_version` OCC field), `modification_decision_payload`, `settlement_payload`, `apply_settlement_payload`, `servicing_action_payload`, `servicing_action_decision_payload`, `payment_payload`, `receivable_payment_payload`

Composite fixtures (all return/extend a scenario ctx dict with fresh distinct staff identities incl. two different LossVerifier users for segregation): `set_clock`, `new_context`, `register_applicant`, `setup_declaration`, `create_draft`, `submit_draft`, `file_credit_review`, `open_verification`, `complete_verification` (with `at_clock`), `dispute_verification`, `find_verification`, `report_grant`, `decide_application` (auto-collateral when requested > purpose threshold), `setup_draft_application` (accepts `_ctx=` to add a second applicant/loan on the SAME declaration), `setup_submitted_application`, `setup_application_in_verification`, `setup_application_in_decision_pending` (skips verification for EIDL), `setup_declined_application`, `setup_approved_loan`, `accept_loan`, `setup_active_loan`, `release_stage`, `verify_milestone` (decided by the non-damage verifier), `setup_loan_with_t1_released`, `setup_loan_with_t1_t2_released`, `create_modification` / `decide_modification` (OCC version auto-read), `report_settlement` / `apply_settlement` / `void_settlement`, `setup_loan_with_applied_settlement`, `pay_receivable`, `request_servicing_action` / `decide_servicing_action`, `post_payment` / `reverse_payment`, plus readers `read_loan`, `loan_version`, `list_tranche_data`, `list_receivable_data`.

### (5) Uncoverable design-instance setup chains

None. All 56 non-stub instances (18 difficulty + 38 corner) were walked; every `setup_api_calls` chain composes from the helpers above. Two multi-entity patterns needed explicit support and got it: repeated drafts per applicant and two-applicant/two-loan tests (`_ctx` reuse so the unique DR-4821 is declared once). Constants: every value comes from PRD text plus `EXPECTED_SUCCESS_STATUS` keyed by operation name (creates 201, transitions/reads 200) for Stage 2's explicit-status assertions.

Orchestrator verification: re-ran py_compile over test_helpers/*.py + test_suite/conftest.py (OK), re-ran the full import smoke (OK), and diffed every numeric constant in constants.py against PRD.md text — zero constants missing verbatim from PRD. NOTE (orchestrator): helpers' canonical declaration uses declared_date 2026-10-01 while the PRD clock default is 2026-09-01 — this is a fixture date, not a clock contradiction; fixtures set the clock as needed. Will confirm no recipe is clock-unreachable at the Step 7 sweep.

## Step 5b-1: Generate difficulty tests (Stage 2, queue A) — 2026-10-02T16:15:00.000Z

All audits pass. Stage 2 (queue A) is complete.

**Files written** (all under `test_suite/`), one rule_id per file, 2 tests each, 18 total:

| File | Tests |
|---|---|
| test_difficulty_dual_variant_calc.py | 2 — valuation_basis_rcv_vs_acv_divergence, monthly_payment_standard_vs_deferred_capitalized |
| test_difficulty_combinatorial_formula.py | 2 — approved_amount_net_loss_minus_grants_binds, clawback_evaluation_order_pinned_steps |
| test_difficulty_non_linear_state_machine.py | 2 — application_reconsideration_cycle_bounded, loan_lifecycle_x_servicing_parallel_dimensions |
| test_difficulty_transitive_cascade.py | 2 — settlement_apply_cascade_commitment_tranche_receivable, milestone_verify_cascade_enables_next_tranche |
| test_difficulty_priority_pair_validation_conflict.py | 2 — decision_state_gate_beats_collateral_fiscal, submit_deadline_temporal_beats_county_referential |
| test_difficulty_boundary_precision_check.py | 2 — collateral_threshold_exact_vs_plus_one_cent, credit_score_640_passes_639_declines |
| test_difficulty_cross_entity_state_dependency.py | 2 — submit_gated_by_declaration_purpose_deadlines, tranche_release_gated_by_milestone_verification |
| test_difficulty_resource_temporal_overlap.py | 2 — servicing_action_half_open_adjacency_vs_overlap, declaration_incident_window_inclusive_overlap |
| test_difficulty_compensating_invariant.py | 2 — payment_reverse_conserve_principal_stock, settlement_void_restores_commitment_and_schedule |

**pytest --collect-only tail (verbatim):**
```
tasks/task_3481_disaster_loan_application_damage_verification_servicing/test_suite/test_difficulty_transitive_cascade.py::test_settlement_apply_cascade_commitment_tranche_receivable
tasks/task_3481_disaster_loan_application_damage_verification_servicing/test_suite/test_difficulty_transitive_cascade.py::test_milestone_verify_cascade_enables_next_tranche

18 tests collected in 0.29s
```

**Skipped instances:** none — all 18 passed the PRD-first two-condition filter (every asserted rule has verbatim PRD prose; every quote re-grepped clean in an automated pass).

**Helper gaps:** none. Setups compose entirely from frozen `test_helpers` fixtures (including `_ctx=` reuse for multi-applicant instances, which keeps the unique DR-4821 declaration); trigger steps call the frozen `ApiClient` methods directly so exact statuses (201 creates / 200 transitions per `EXPECTED_SUCCESS_STATUS`) and exact `error_id`s are asserted via `validate_success`/`validate_error`. OCC-guarded applies read a fresh `loan_version(ctx)` first.

**Interpretations beyond literal recipe text:**
- Computed-instant assertions (`next_due_date`, receivable `due_date`, `last_accrual_date`) use `startswith("…T00:00:00")` rather than exact-string equality: PRD §2.5 mandates three fractional digits on audit timestamps, so two faithful implementers could render computed instants with/without `.000`; the instant itself (midnight on the pinned date) is still asserted exactly. Design-YAML literals confirmed to that precision.
- All numeric literals were independently re-derived from PRD formulas with exact `Decimal` arithmetic and match the design YAML: verified losses 30000000/24000000, payments 85675/88352 (delta 2677) and 119427 and 7161, late fee 4418, 30-day accrual 28896, approved 8000000, waterfall T2→5500000 with T3 CANCELLED, commitment 4000000, receivable 7250000, payment split 0/28896/71104 with the 11250000 stock invariant.
- Instance 5's mid-loop DECLINE decisions rely on the PRD scoping the verification gate to approvals ("Before any money is computed…blocks approval"); declines from DECISION_PENDING proceed.
- No test mentions "scaffold", none use skip/xfail; AST audit confirms exactly one resolving `Design: Difficulty/...` tag per test.

## Step 5b-2: Generate corner tests (Stage 2, queue B) — 2026-10-02T16:50:00.000Z

Stage 2 (queue B) complete. Summary:

**(1) Files written** — 9 new files under `test_suite/`, one per §1.9 section, 38 corner tests total (frozen `test_helpers/`, `conftest.py`, and the 18 `test_difficulty_*.py` files untouched):
- `test_corner_entities.py`: 5
- `test_corner_state_machines.py`: 9
- `test_corner_calculations.py`: 5
- `test_corner_validations.py`: 5
- `test_corner_endpoints.py`: 3
- `test_corner_rbac.py`: 3
- `test_corner_cross_cutting_layers.py`: 2
- `test_corner_consistency_model.py`: 1
- `test_corner_errors.py`: 5

**(2) Collection tail (verbatim):**
```
tasks/task_3481_disaster_loan_application_damage_verification_servicing/test_suite/test_difficulty_transitive_cascade.py::test_settlement_apply_cascade_commitment_tranche_receivable
tasks/task_3481_disaster_loan_application_damage_verification_servicing/test_suite/test_difficulty_transitive_cascade.py::test_milestone_verify_cascade_enables_next_tranche

56 tests collected in 0.33s
```
Exactly 56 = 18 difficulty + 38 corner. AST tag audit: 38/38 non-stub instances carry exactly one `Design: Corner/<section>/<name>` line resolving to the YAML; 4 `excluded_because` stubs emitted nothing; no missing/extra/duplicate tags. A verbatim-grep sweep of every docstring quote against PRD.md passes (0 misses) after fixing three citation-format slips (table-pipe prefixes, stripped `**` bold markers) and extending a few fragmentary quotes to full sentences.

**(3) Skipped instances:** none — every non-stub instance has verbatim PRD coverage and unique derivability.

**(4) Helper gaps:** none — all recipes composed from the frozen fixtures/factories (`setup_application_in_decision_pending`, `setup_active_loan`, `setup_loan_with_t1_released`, `setup_loan_with_applied_settlement`, `_ctx` chaining for second applicants, etc.).

**(5) Interpretations beyond the literal recipe:**
- Date-typed response fields (`physical_filing_deadline`, `last_accrual_date`, `next_due_date`) asserted with `startswith("YYYY-MM-DDTHH:MM:SS")` rather than exact-string equality, following the frozen difficulty tests' precedent — the PRD pins the instant, not the serializer suffix.
- `modification_supersede_auto_denies_predecessor`: both creates share one logical instant, so `created_at` may tie; asserted by-id statuses plus non-decreasing `created_at` instead of the recipe's positional `$.data[0]/$.data[1]`.
- Used the framework's `NON_EXISTENT_UUID` in place of the recipe's hardcoded 404 UUID (same semantics), and `{}` headers for the unauthenticated-submit trigger (client then sends no `X-User-*` headers).
- All expected literals were independently re-derived from PRD formulas in exact Decimal math before writing (23871 EIDL payment, 114858 modified payment on 26812500 capitalized principal, 19905 renter payment, 6421 interest for 30 days on 2500000, 4418 late fee = round_half_up(0.05×88352), DTI boundary 18490000 = 43×430000, tranche splits [2500000,8750000,8750000] / [2500000] / [2500000,1250000,1250000]). Every value matched the design index, and 88352 matches the frozen difficulty suite — no cross-queue constant drift.

Orchestrator re-audit (independent AST parse): 56 non-stub instances in the two YAMLs ↔ 56 tests each carrying exactly one resolving Design: tag; no missing, no extra, no duplicates; `pytest --collect-only` = 56 collected.

## Step 6: Generate implementation — 2026-10-02T17:20:00.000Z

All checks pass. The implementation is complete.

**Deliverable.** Complete Python + Flask implementation in `workspace/implementation/` — 27 source files + `start.sh` + `requirements.txt`, in-memory storage only (dicts keyed by id, wiped on every `start.sh` re-invocation), zero seeding, foreground launcher reading `$PORT` (default 10000) bound to `0.0.0.0` with `exec` and a guarded dependency install.

**(1) File list with line counts**
| File | Lines | Role |
|---|---|---|
| `app.py` | 74 | entry point, error handlers, unprefixed `POST /_clock/set_current_utc` |
| `errors.py` | 56 | ApiError + full 38-code catalog |
| `store.py` | 51 | in-memory store, insertion ordering |
| `clock.py` | 14 | logical clock, default exactly 2026-09-01T00:00:00Z |
| `timeutil.py` | 54 | ISO parse/format (3 fractional digits), add_months, calendar-days |
| `envelope.py` | 80 | `meta`/`response_type`/`data` envelope, pagination fields `limit`/`offset`/`total_count`/`has_more` |
| `auth.py` | 45 | X-User-ID/X-User-Role guards, role authorization, Applicant ownership |
| `body.py` | 78 | shape validation (priority 5) |
| `calc.py` | 122 | monthly_payment (STANDARD + DEFERRED_CAPITALIZED, exact Decimal, round-half-up at final step), affordability-cap inversion (floor to cents), approved_amount_calc, verified/net loss, daily interest, late fee |
| `domain.py` | 78 | common fields, FK reverse lookups, latest-PASS-review / latest-COMPLETED-verification |
| `cascade.py` | 127 | tranche schedule (T1=min(2500000,approved); T2=floor(rem/2), T3=remainder; zero-amount skipped), eligibility walk, clawback waterfall (descending LIFO cancel-then-reduce), receivable top-up/create, release cascade |
| `sweep.py` | 126 | declaration rollup, servicing-action activation/expiry, delinquency aging (fee≥15, DELINQUENT≥30, DEFAULT≥120, CHARGED_OFF≥180), default cascades |
| `serializers.py` | 32 | internal `_`-keys stripped, datetimes formatted |
| 15 × `routes_*.py` | 39–129 each | all 40 endpoints |
| `start.sh` | 9 | guarded pip install, `exec python3 app.py` |
| `requirements.txt` | 1 | flask |

**(2) py_compile results.** Every file compiled immediately after writing; final sweep → ALL_COMPILED, no failures.

**(3) Self-smoke transcript (dynamic ports, server PID killed after each run).**
Run 1 (physical path): create declaration 201 → create applicant 201 → draft application 201 → submit 200 (SUBMITTED) → credit review 201 (verdict PASS) → open verification 201 → complete 200 (net_verified_loss 2500000) → approve 200 (APPROVED, loan_id set) → accept 200 (ACTIVE, T1 ELIGIBLE) → list tranches 200 → release T1 200 (RELEASED) → `POST /_clock/set_current_utc` 200 → read loan 200. SMOKE OK.
Run 2 (EIDL + failure paths): missing headers 401 ERR_UNAUTHENTICATED; declaration deadlines computed correctly (+90d/+270d); EIDL PASS review → straight to DECISION_PENDING; verification-create on EIDL 409 ERR_VERIFICATION_NOT_APPLICABLE; approve 200 (rate 0.04, term 360); stale modification 412 ERR_STALE_VERSION; modification on PENDING_ACCEPTANCE 409 ERR_LOAN_NOT_ACTIVE (OCC before state gate); cross-applicant read 403 ERR_FORBIDDEN_OWNER; Applicant on `/loans` list 403 ERR_UNAUTHORIZED; second modification auto-denied first (supersede) with loan version bump; approval appended delta tranche; settlement apply ran full clawback (verified_loss 0 → commitment 3,000,000→0, delta 3,000,000, excess 1,000,000, receivable OPEN); receivable payoff → loan PAID_IN_FULL; void restored commitment; clock jumps rolled declaration to FULLY_CLOSED; late EIDL submit 422 ERR_EIDL_FILING_CLOSED. SMOKE2 OK.

**(4) Interpretations chosen**
1. OCC before state gate (priority 6 < 8): stale-version on a non-ACTIVE loan returns ERR_STALE_VERSION.
2. Damage-verification create: purpose gate (priority 7, ERR_VERIFICATION_NOT_APPLICABLE) before state gate (priority 8, ERR_APPLICATION_NOT_IN_VERIFICATION).
3. Dispute ordering: state-family gates (COMPLETED, not APPROVED) before the 30-day window (priority 8 before 12).
4. Unpinned uniqueness (applicant email, declaration_number): prose-only rule with no catalog id → ERR_INVALID_REQUEST 400.
5. Application create does not check declaration existence — the scaffold pins that check at submit (ERR_NOT_FOUND there).
6. Approval affordability uses the latest PASS credit review's verified debt; if none exists (post-reconsideration after credit FAIL), falls back to the applicant's self-reported `monthly_debt_cents`.
7. Modification approval recomputes `monthly_payment_cents` in both delta directions.
8. Sweep version increments: one per status rung crossed (CURRENT→CHARGED_OFF = +3; fee/days-only change +1). A jump past both declaration deadlines is one rollup transition (+1).
9. Servicing-action activation (sweep and immediate-at-approval) applies only when `servicing_status == CURRENT`; DEFAULT is barred earlier by ERR_ACCOMMODATION_NOT_ALLOWED.
10. Sweep step 2 ordering: expire ACTIVE actions before activating APPROVED ones, then a second expiry pass.
11. Tranche eligibility after clawback: literal reading — every earlier stage must be RELEASED (a CANCELLED earlier stage blocks later eligibility; amounts of earlier stages still count toward the coverage threshold).
12. Late-fee idempotence: tracked per `next_due_date` value ("due-date cycle"); deferment shifting the due date opens a new cycle.
13. Cure condition: DELINQUENT→CURRENT when post-allocation late_fee_balance == 0 and accrued_interest_balance == 0; reversal does not un-cure (PRD silent).
14. Pagination: out-of-range limit/offset clamped to [1,100]/[0,∞); non-integer → 400. List filters match literally (unknown value → empty page).
15. Applicant list scoping: `GET /loan-applications` for an Applicant forced to `applicant_id == X-User-ID`.
16. `meta.api_request_timestamp` uses wall-clock receipt time; all entity timestamps use the logical clock.
17. Void restores tranches from a per-apply snapshot, skipping any tranche RELEASED since the apply.
18. 405 responses return the ERR_NOT_FOUND envelope.

**(5) PRD requirements not implemented.** None.

Orchestrator verification: independently re-ran py_compile over all 28 impl .py files (ALL_COMPILED), confirmed `@app.post("/_clock/set_current_utc")` unprefixed in app.py, booted on a dynamic port (57545), POSTed the clock endpoint as SystemAdmin → 200 with sweep executed, killed only my own saved PID.

## Step 7: Test-fix iteration loop — 2026-10-02T17:45:00.000Z

Clean sweep: all 8 rounds pass 56/56. All `results.*.json` files remain in `workspace/implementation/`.

- **Iterations run:** 2 (initial sweep → 1 consistent failure; fix → clean 8-round sweep).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `test_suite/`:**
  - `test_suite/test_corner_cross_cutting_layers.py` — `test_occ_settlement_apply_stale_version`: corrected the post-apply tranche-schedule expectation from `[2500000, 8750000, 8750000]` to `[2500000, 8750000, 7750000]`. The test was self-contradictory: it asserted commitment 19000000 while expecting the un-released schedule to still sum to 20000000. PRD §3.8 pins the waterfall: target = new commitment (19000000) − disbursed (0) = 19000000; walking descending, stage 3's cancellation test fails (20000000 − 8750000 = 11250000 < 19000000), so stage 3 "is instead reduced so the sum of un-released amounts lands exactly on the target" → 7750000. The implementation already computed exactly this; the test's "nothing released → schedule untouched" comment was a misreading (the waterfall runs unconditionally over un-released tranches; only the excess/receivable step is disbursement-dependent). The fix makes the assertion more faithful to PRD, not weaker — the `ERR_STALE_VERSION` and REPORTED-retention assertions were left exact.

- **Fixes applied to `implementation/`:** none — the implementation's `clawback_waterfall` (cascade.py) and `apply_settlement` (routes_settlements.py) already matched PRD §3.8's pinned six-step order exactly; sibling settlement cascade/void tests corroborated.

- **Deliverables confirmed:** all 8 `results.1.json` … `results.8.json` files remain in `workspace/implementation/`, each showing `passed == total == 56`, `failed == 0`.

Orchestrator verification: independently parsed all 8 results files — each passed=56/56 failed=0. Verified the fixed test now asserts `[2500000, 8750000, 7750000]` (line 82) and re-derived the waterfall from PRD §3.8 line 204 ("reduced so the sum of un-released amounts lands exactly on the target", target = 19000000 commitment − 0 disbursed): 20000000 − 8750000 = 11250000 < 19000000 → stage 3 reduced to 19000000 − 11250000 = 7750000. Fix is PRD-faithful.

## Step 8: Finalize PRD — 2026-10-02T17:55:00.000Z

Investigation complete. Zero-edit outcome confirmed.

**Line counts / delta:** PRD.md = 310 lines, PRD_FINALIZED.md = 310 lines, **byte-identical** (verified with `diff -q`). Zero changes.

**Justification (single diff item investigated):**

- `test_suite/test_corner_cross_cutting_layers.py::test_occ_settlement_apply_stale_version` — expectation corrected `[2500000, 8750000, 8750000]` → `[2500000, 8750000, 7750000]`. This was a pure test bug, not a PRD silence. No PRD edit needed.

**Investigation log:**

(a) **PRD passage covering it** — PRD.md §3.8, line 204, pins the settlement-apply cascade "in this exact, pinned order": (1) total insurance summed; (2) new net loss = verified loss − total insurance, floored at zero; (3) new commitment = min(`approved_amount_cents`, new net loss); (4) the waterfall walks un-released tranches in **descending** `stage_number`, cancelling whole tranches while "the sum of un-released amounts minus the tranche's amount stays at or above the target — the target being the new commitment minus `disbursed_total_cents`, floored at zero — and the tranche where that test fails is instead reduced so the sum of un-released amounts lands exactly on the target"; (5) excess = `disbursed_total_cents` − new commitment, floored at zero; (6) positive excess creates/tops up the receivable. The waterfall (step 4) is unconditional; only the excess step is disbursement-dependent — so the old test's "nothing released → schedule untouched" reading has no foothold in the text, and its expected schedule (sum 20000000 against commitment 19000000 with disbursed 0) was self-contradictory.

(b) **Impl paths enumerated and read** (per the no-new-mismatch rule, every path touching the clawback waterfall, not just the Step 7 site):
- `workspace/implementation/routes_settlements.py:55-98` (`apply_settlement`) — the Step 7 site: `new_commitment = min(approved, new_net_loss)` (line 78), `target = max(0, new_commitment − disbursed_total_cents)` (line 85), waterfall call (line 86), excess and receivable (lines 88-91). Exact match to PRD §3.8 steps 1-6.
- `workspace/implementation/cascade.py:69-86` (`clawback_waterfall`) — descending walk over SCHEDULED/ELIGIBLE tranches; cancel while `total − amount >= target`, else reduce current tranche by `total − target` and break. Trace of the test scenario (un-released sum 20000000, target 19000000): stage 3 cancellation test 20000000 − 8750000 = 11250000 < 19000000 fails → stage 3 reduced by 1000000 → 7750000. Exactly the corrected expectation.
- `workspace/implementation/routes_modifications.py:92-98` (modification-decrease path) — the waterfall's only other call site: `new_commitment = min(commitment, new approved)`, same `target = max(0, new_commitment − disbursed)`, same waterfall/excess/receivable sequence. Consistent with PRD §3.8 line 202, so the existing §3.8 wording is accurate for both call sites.
- Fixed test file `test_suite/test_corner_cross_cutting_layers.py:54-94` read to confirm the corrected numbers and that the `ERR_STALE_VERSION` / REPORTED-retention assertions were left exact.

(c) **Wording adjustment** — none. Every quantity the fixed test asserts (total insurance 6000000, net loss 19000000, commitment 19000000, target 19000000, reduced stage 3 = 7750000, zero excess, no receivable, stale-version rejection) is uniquely determined by the existing PRD §3.8 text and §2.7 OCC rule, and the implementation computes exactly that on both waterfall call sites. A fresh implementer reading PRD.md alone is forced to the shipped behavior; any pin would have been redundant prose.

**Output file:** `workspace/PRD_FINALIZED.md` (byte-identical copy of PRD.md).

Orchestrator verification: `diff -q workspace/PRD.md workspace/PRD_FINALIZED.md` → byte-identical confirmed. Post-sweep integrity: no implementation/*.py or test_*.py file is newer than the Step 7 sweep results (17:33:49) — Step 8 touched only PRD_FINALIZED.md; the clean sweep remains valid.

## Step 9: Complete PRD — full impl-vs-PRD scan — 2026-10-02T18:00:00.000Z

All checks complete. Final summary:

**File**: `workspace/PRD_COMPLETED.md`
**Source vs output**: PRD_FINALIZED.md 310 lines / 57,316 chars → PRD_COMPLETED.md 313 lines / 63,545 chars (**+3 lines, +6,229 chars**).

**Counts**: 33 ambiguity-pins, 0 mismatch-revisions, 0 IMPL BUGs.

### Changes (all ambiguity-pins; impl verified as alignment target)

- §2.2 — insert — `meta.api_request_timestamp` is wall-clock; only entity timestamps use the logical clock — envelope.py:19, timeutil.py:35
- §2.2 — insert — unknown path or unsupported method → ERR_NOT_FOUND envelope at HTTP 404; unhandled exception → ERR_INVALID_REQUEST envelope at HTTP 500 — app.py:46-59
- §2.3 — insert — out-of-range limit/offset clamped (limit→[1,100], offset→≥0); non-integer → ERR_INVALID_REQUEST 400; `total_count` is post-filter; `has_more` formula; created_at ties by insertion order — envelope.py:55-80
- §2.4 item 1 — revise — OPEN→FULLY_CLOSED double-jump is one transition, one version increment — sweep.py:24-35
- §2.4 item 2 — insert — sweep pass order expire→activate→expire (fully-past window transits ACTIVE→EXPIRED in one set); activation requires servicing_status CURRENT, else stays APPROVED; activation resets days_past_due — sweep.py:57-68 (smoke-verified)
- §2.4 — insert — backward clock sets permitted; declarations re-derive (may reopen), action/aging transitions never reverse — clock.py:13-14 (smoke-verified 200)
- §2.5 — revise — `version` starts at 1; date-only strings read as midnight UTC, offset-less datetimes as UTC — domain.py:7-9, timeutil.py:6-24
- §2.7 — revise — missing/non-integer `expected_loan_version` → ERR_INVALID_REQUEST 400 — routes_modifications.py:28-30, routes_settlements.py:58-60
- §2.8 — insert — calendar-month addition clamps day to target month's last day — timeutil.py:39-49
- §3.1 — insert — duplicate `declaration_number` → ERR_INVALID_REQUEST 400 — routes_declarations.py:57-59
- §3.1 — insert — county `eligible_purposes` may be empty — routes_declarations.py:37-40
- §3.2 — revise — duplicate applicant `email` → ERR_INVALID_REQUEST 400 — routes_applicants.py:27-29
- §3.2 — insert — application create does not check declaration existence (first enforced at submit) — routes_applications.py:24-44 vs 77-79
- §3.2 — insert — Applicant list scoped to own applications; `applicant_id` filter ignored for Applicant callers — routes_applications.py:50-56
- §3.4 — insert — verification create gate order: purpose → state → estimation-amount — routes_verifications.py:40-46
- §3.4 — revise — explicit JSON null `depreciation_pct` treated as omitted — routes_verifications.py:38
- §3.4 — insert — "latest" verification (completed or overall) is by creation order — domain.py:18-22
- §3.4 — insert — dispute: post-approval freeze evaluated before the 30-day window check — routes_verifications.py:111-117
- §3.6 — revise — collateral at/below threshold: approval payload need not include the fields; loan record carries them as null — routes_decision.py:78-87
- §3.6 — insert — affordability cap uses latest PASS review's verified debt; falls back to self-reported `monthly_debt_cents` when no PASS review exists — calc.py:119-120
- §3.7 — insert — milestone decision: REPORTED state check before segregation-of-duties — routes_milestones.py:62-68
- §3.7 — insert — later-release interest fold: pre-release outstanding × rate × calendar days / 365, half-up at each fold — cascade.py:115-120, calc.py:95-101
- §3.8 — insert — modification create: differs-from-current (well-formedness) → OCC → loan-state gate — routes_modifications.py:26-35
- §3.8 — revise — monthly_payment_cents recomputed (deferred-capitalized) on approved decrease as well as increase — routes_modifications.py:99-101
- §3.8 — insert — CANCELLED is terminal short of a void and permanently blocks later stages' eligibility — cascade.py:48-86
- §3.8 — revise — settlement apply: OCC before ERR_SETTLEMENT_NOT_REPORTED per §2.6 — routes_settlements.py:58-65
- §3.8 — revise — void restores tranches from the per-apply snapshot, skipping tranches released since — routes_settlements.py:110-115
- §3.8 — insert — receivable payment persists no separate row; responds 201 with the updated receivable — routes_receivables.py:39-48
- §3.9 — revise — late-fee cycle keyed to `next_due_date` value; a deferment shift starts a new cycle — sweep.py:101-105
- §3.9 — insert — immediate activation on approval requires servicing_status CURRENT, else action stays APPROVED — routes_servicing.py:88-89
- §3.9 — revise — DEFERMENT shifts `next_due_date` only when set — sweep.py:44-46
- §3.9 — insert — aging sweep version granularity: +1 per rung crossed (fees/dpd ride along); +1 for a dpd/fee-only sweep — sweep.py:106-126 (smoke-verified)
- §3.9 — insert — payment reversal does not un-cure: servicing_status/days_past_due untouched — routes_payments.py:99-110

### IMPL BUG list: none
Every PRD-clear behavior checked (deadline/county ordering on submit, verification-gate-before-fiscal on approval, overlap-before-DEFAULT on accommodation decision, OCC before state gates, clawback waterfall order, error-catalog coverage — all 38 catalog ids defined and used) matches implementation.

### Crash-path enumeration (nullable-field reads; dynamic-port live smoke, server killed by exact PID afterward)
- `last_accrual_date` null: payment on never-released ACTIVE loan → smoke-verified 422 ERR_PAYMENT_EXCEEDS_BALANCE; first-release branch sets it — safe.
- `next_due_date` null: aging sweep treats as dpd 0 (smoke-verified 200, dpd 0); DEFERMENT activation guarded — safe.
- `application.loan_id` null: grant ceiling guarded by `if app.get("loan_id")` — safe.
- Verification money fields null pre-completion: all readers select `completed_only=True` (grant ceiling, approved amount, settlement apply, milestone SoD) — safe.
- `milestone.verified_cost_cents` null: summed only over VERIFIED milestones — safe.
- Settlement `clawback_commitment_delta_cents`/`_tranche_snapshot`/`_receivable_id` null: void requires APPLIED (fields set at apply); smoke-verified apply→void on an EIDL loan — safe.
- Payment `_pre_last_accrual`/`_caused_pif`: set at creation; reverse gated on POSTED — safe.
- Receivable amount fields: always initialized at creation — safe.
- 405 / unknown path: smoke-verified 404 ERR_NOT_FOUND envelope; any unexpected exception is enveloped as ERR_INVALID_REQUEST 500 — no bare Flask error pages.

### Modification confirmation
No file under `implementation/`, `test_suite/`, or `test_helpers/` was modified (post-session-start mtime scan returned empty). Only `workspace/PRD_COMPLETED.md` was written.

## Final orchestrator verification — 2026-10-02T18:20:00.000Z

- All 8 pre-existing results files still valid 56/56; no impl/test .py newer than sweep; PRD_COMPLETED.md tail ends cleanly (error table complete).
- Re-ran the full 8-round parallel stability sweep MYSELF (fresh evidence, runner-managed ports): rounds 1–8 each `passed=56/56 failed=0`. FINAL VERDICT: ALL 8 ROUNDS CLEAN 56/56. Fresh `results.1..8.json` in `workspace/implementation/`.
- Final tree: SCAFFOLD.yaml / SCAFFOLD_DIFFICULTY_DESIGN.yaml / SCAFFOLD_CORNER_DESIGN.yaml / worklog.md / test_helpers/ (9 files) / test_suite/ (conftest + 18 test files = 56 tests) / workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md (byte-identical), PRD_COMPLETED.md, implementation/ (28 .py + start.sh + requirements.txt + results.1..8.json)}.
