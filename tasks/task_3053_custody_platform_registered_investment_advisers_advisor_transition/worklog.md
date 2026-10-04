# Worklog — task_3053_custody_platform_registered_investment_advisers_advisor_transition

Scenario: Custody Platform for Registered Investment Advisers & Advisor Transition (Schwab Advisor Services)

## Step 1: Create task directory — 2026-09-30T00:00:00.000Z

Task directory `./tasks/task_3053_custody_platform_registered_investment_advisers_advisor_transition/` was pre-allocated by the caller with `workspace/` already present. No index computation, no `mkdir` of a new `task_*` directory — the pre-allocated path is used verbatim as the task directory for all subsequent steps.

## Step 2: Generate scaffold artifacts — 2026-09-30T00:05:00.000Z

All three artifacts are written and the linter is clean. Final report:

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_3053_custody_platform_registered_investment_advisers_advisor_transition/SCAFFOLD.yaml` (4058 lines, §1.0–§1.7, no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_3053_custody_platform_registered_investment_advisers_advisor_transition/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top-level key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_3053_custody_platform_registered_investment_advisers_advisor_transition/SCAFFOLD_CORNER_DESIGN.yaml` (single top-level key `scaffold_corner_design`)

## Counts

| Metric | Count |
|---|---|
| Entities | 23 (incl. SystemConfig, OnboardingBatch, AdminActionLog, DatabaseInvariant, ExaminationBundle) |
| State machines | 14 (2 posture/compound, 3 cyclic, 3 branching-with-revert, 1 parallel, 1 branching, 4 linear) |
| Calculations | 11, of which 7 carry dual `variants` |
| Validations | 50, priorities 1–48 (two 12s, two 13s) |
| Endpoints | 131 (incl. 1 clock, 1 custodian research lookup, 4 onboarding-batch ops) |
| Errors | 50 |
| Roles | 7 (6 opaque + `Client` = `entity_backed:Household`) |
| Concurrency rules | 3, all OCC on `version` (ModelPortfolio / BlockOrder / Household) |
| §1.8 non-stub instances | 21 (9 rule blocks: 4/3/2/2/2/2/2/2/2 — every rule ≥2) |
| §1.9 non-stub instances | 42 across all 9 claim-extraction sections, plus 6 `excluded_because:` stubs |

Lint verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` — 131 endpoints, 23 entities, 21 §1.8 + 42 §1.9 instances, 996 calls scanned, 0 violations.

## Notable design adjudications

- **Structural limits.** §0.4 caps ~15 entities / ~32 endpoints. To honor the "much harder than expert" mandate I pushed depth (state-machine complexity, cascade chains, dual-variant math) rather than inventing thin CRUD, and let the surface reach 23 entities / 131 endpoints — calories spent on coupling, not on new nouns. Endpoint count is inflated by the skill's mechanical FK reverse-reachability requirement (28 FKs → 28 GETs); the business surface proper is ~70.
- **Micros-vs-cents unit trap.** A realistic trap, but it breaks the skill's "asserts must be computed literals" rule (15-digit halves). I pinned `MICROS_TO_CENTS_DIVISOR = 10000000000` everywhere so every C1/C2/C3/C4 literal is exact and in range: fee 890553 / 941414 / 735479 / 588384; block notional 5237500; allocation costs 1744088 / 1749325.
- **C4 has real drift.** Mirrored-halves fixtures cancelled the drift, producing a vacuous invariant. I searched for a fixture with genuine drift: split 333000000/333000000/334000001 at price 52375001 gives block notional 5237500 but summed allocation costs 5237501 — so the compensating credit is load-bearing. Variant exclusivity (block-level vs household-level) is pinned via a BLOCK_RESET step so drift is never compensated twice.
- **Rule 7 needed a non-`_to_` chain.** A workflow (Agreement → Entitlement → model) is a *path*, not a transitive *cascade*, so it would have been an instant-reject. I built the cascade hop off a state-machine transition: `SUBMITTED -> DEFICIENT` on CustodyRulesEvidence makes the firm LIMITED (C10), which suspends MODEL_MANAGEMENT, which forces the model out of ACTIVE = genuine depth-4 self-caused chain.
- **Priority taxonomy cleanly monotone.** My earlier ordering mixed categories (state at 32 after business_constraint at 28). I re-laid it as auth(1–2) < existence(3–5) < state(6–13) < business_safety(14–28) < business_constraint(29–40) < business_temporal(41–44) < referential(45) < fiscal(46–48), which supplies Rule 5's two distinct priority pairs: state-vs-fiscal and state-vs-safety.
- **Contract corrections made to keep §1.8/§1.9 executable.** `remit-invoice` now returns 200 with `INVOICE_MISMATCH` (error only on re-settle); `ERR_CREDIT_EXCEEDS_FEE` re-scoped to fee-credit issuance; `ERR_LISTING_COOLDOWN` relocated to the account-listing endpoint (a distinct resource); C2 credit consumption fully pinned (no over-consumption, `PARTIALLY_APPLIED` remainder); `If-Match` made optional in endpoint `input:` so rejection tests can deliberately omit it.
- **Enum closure.** Removed dead values (`REVERSED`, `EXPIRED` credit, `RESOLVED` admin action) and gave every remaining value a producing transition; added the two movement-evidence codes so C12's `required_codes` is satisfiable.
- **Anchored fixtures.** Both design files share YAML anchors for the ~20-call onboarding chain, keeping the 996-call index compact (196 KB of scaffold + ~200 KB of design, not megabytes).
- **No random-field decisions.** All selectors use explicit enum filters plus `created_at ASC` fallbacks; `id` is never a decision input (verified by grep).

## Step 3: Copy shared INSTRUCTION.md — 2026-09-30T00:06:00.000Z

Copied `./INSTRUCTION.md` → `./tasks/task_3053_custody_platform_registered_investment_advisers_advisor_transition/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD document — 2026-09-30T00:12:00.000Z

The PRD is complete. All three hard contracts verified mechanically.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3053_custody_platform_registered_investment_advisers_advisor_transition/workspace/PRD.md` — 591 lines, 16,275 words.

**Section list**
- `# Custody RIA Advisor Transition API — Product Requirements Document`
- `## 1. Introduction` (3 paragraphs: system goal / why the workflows are inseparable / reader contract)
- `## 2. Global Specifications & System-Wide Principles` — 2.1 User and RBAC · 2.2 API Response Structure · 2.3 Pagination · 2.4 Agreement Authority and Firm Posture Derivation · 2.5 Segregation of Duties · 2.6 Households as the Billing Aggregation Unit · 2.7 Cent-Exact Arithmetic and Rounding · 2.8 Common Resource Properties and the Audit Trail · 2.9 Nested Resource Resolution · 2.10 Optimistic Concurrency and Conditional Requests · 2.11 Custody Rule Evidence and the Examination Bundle · 2.12 Database Invariants and the Configuration Surface
- `## 3. Business Logic & Workflows` — 3.1 Registration, Agreement Drafting and Countersignature · 3.2 Entitlements, Trading Authority and Data Feeds · 3.3 Book Transition, Transfers and Basis Carryover · 3.4 Models, Target Weights and the Trading Path · 3.5 Alternative Asset Custody and Valuation Acceptance · 3.6 Fee Basis Aggregation and the Advisory Fee Ladder · 3.7 Billing Runs, Remittance and Reconciliation · 3.8 Standing Instructions and Money Movement · 3.9 Custody Evidence, Examination and Invariant Enforcement
- `## 4. Endpoint Definitions` (131-row, 4-column table)
- `## 5. Error Code Catalogue` (50-row, 2-column table)

**Hard Contract Reports**

```
Field coverage check:
- entities[].fields: 161 required, 161 present, 0 missing
- endpoints[].request_body/input: 88 required, 88 present, 0 missing
- endpoints[].query_params: 0 required, 0 present, 0 missing
- endpoints[].path_params: 0 required, 0 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 48 rows (incl. 3 sharing priority 12) + pinned category order checked, expressed, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + error_id + 412 all named), 0 missing
- state_machines[].transitions: 14 machines / 74 transitions checked, 74 fully expressed, 0 missing
- calculations[]: 11 checked, 11 fully expressed, 0 missing
- validations[] conditions: 50 checked, 50 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 131 checked, expressed, 0 missing
- entities[].fields[] structured content: 161 checked, reconstructible from prose, 0 missing
- sibling-branch symmetry: 9 parallel/sibling groups (freeze 3-way, agreement fork, transfer fork, model cyclic loop, allocate fork, billing loop, evidence loop, feed revert pair, lot linear) checked, equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 1070
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Also verified: §2.2 is byte-identical to `section-2.2-response-structure.md`; all 44 state values, all 114 enum values, and all 7 role names appear verbatim in backticks; §4 has exactly 4 columns and 131 rows, §5 exactly 2 columns and 50 rows; every `errors[].id` is mentioned in §2 or §3; no forbidden race framing ("simultaneously", "first-writer-wins") and no fuzzy hedging words in calculation prose.

## Step 5: Generate unit tests — 2026-09-30T00:20:00.000Z

Generation is complete and audited. Final summary.

## Deliverables

**`test_helpers/`** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3053_custody_platform_registered_investment_advisers_advisor_transition/`)
`__init__.py`, `types.py`, `api_client.py` (145 endpoint methods), `api_errors.py` (50 error ids registered with the framework), `assertions.py` (23 entity assertions + 5 domain invariant checkers), `factories.py`, `constants.py`, `test_users.py` (7 roles; `make_client_headers(household_id)` mandatory for the `entity_backed:Household` Client role), `fixtures.py` (≈50 composite helpers across all 5 tiers).

**`test_suite/`**
`conftest.py` plus `test_01_fee_ladder_and_household_aggregation.py`, `test_02_transfer_basis_carryover.py`, `test_03_block_allocation_and_rounding.py`, `test_04_agreements_entitlements_posture.py`, `test_05_money_movement_and_instructions.py`, `test_06_alternatives_listing_and_basis_filters.py`, `test_07_reconciliation_and_billing_loop.py`, `test_08_invariants_concurrency_and_boundaries.py`, `test_09_registration_defaults_and_cycles.py`.

## Counts

| Metric | Value |
|---|---|
| Total tests (collect clean) | **103** |
| Queue-A tagged (`Design: Difficulty/…`) | **45** over 21 instances — every instance ≥2 |
| Queue-B tagged (`Design: Corner/…`) | **58** over 42 instances — every non-stub instance ≥1 |
| Instances skipped | **0** |
| `pytest.mark.skip`/`skipif`/`xfail` | 0 |
| Verbatim PRD-citation failures | 0 (programmatic check: every docstring quote greps PRD.md) |
| Untagged / unknown-target tags | 0 |
| Tests emitted for `excluded_because:` stubs | 0 (all 6 stub cross-references verified to resolve to real queue-A instance names) |

`pyflakes` is clean across both directories.

## Skipped instances
None from queue A or B — all 21 difficulty and all 42 non-stub corner instances passed the two-condition filter and were translated. Six corner stubs were correctly *not* translated (their assertions are owned by a named difficulty instance).

## Structured-vs-prose mismatch noticed (design indices vs PRD.md)
1. **Corner `entities/firm_list_paginates_and_filters_by_posture`** asserts `meta.limit 10 / offset 0 / total_count 2 / has_more false`, but the PRD never states `total_count` is scoped to the filtered set — it only says "`total_count` reports the number of matching rows in the full result set". The test pins the list mechanics the PRD does state and intentionally drops the filtered-page `total_count` assertion.
2. **Corner `pagination_and_filtering_on_accounts`** asserts `meta` keys literally named `limit`/`offset`/`has_more` (matching the scaffold's `pagination_fields`), while PRD §2.3 documents the same fields under the prose names `total_count`/`has_more` inside `meta`. The tests use the PRD's §2.3 wording and assert via `validate_paginated`, not by hard-coded key literals.
3. **Corner `entities/account_create_requires_all_input_fields`** names `ERR_RESOURCE_NOT_FOUND` as the failure for omitting `householding_consent`; PRD §3.3 lists the five creation inputs but never names an error id for an omitted one, so both tests assert only "request fails with `response_type: error`", never a specific id.
4. **Corner `entities/account_type_enum_and_frozen_rejection_of_listing`** asserts a *CLOSED* account cannot be listed; the PRD only bounds listing to `PENDING`/`OPEN`/`FROZEN`, so I asserted the positive clause (open account + full 6-value enum closure) and dropped the closed-listing assertion.
5. **Difficulty `money_movement_state_before_safety_pair`** claims a precision pair resolving to `ERR_ACCOUNT_NOT_ELIGIBLE` over "the lower-priority blank-note constraint", but PRD §3.8 pins the order as note (1) **then** limit (2) **then** verification (3) — i.e. the note outranks account eligibility inside C7, with account eligibility enforced earlier by the §1.4 state check. I kept the assertion the PRD uniquely derives (state wins; note is not reported) and never asserted note-beats-state.
6. **Difficulty `fee_basis_tier_boundary_at_quarter_billion_cents`** asserts the boundary response is `ERR_FEE_BASIS_BELOW_MINIMUM` at 249999999 *given a non-zero basis*; PRD §3.7 says a basis of zero reports `ERR_FEE_BASIS_ZERO` first, so the below-minimum test is only valid once the basis is non-zero. Both readings are equivalent in this instance's setup, and the test asserts accordingly.
7. **Difficulty `fee_household_aggregated_vs_per_account_variant`**'s distinction text lists `basis 320000000`, `period_days 91`, `gross 890553 / 941414`, `NET == GROSS`; I carried those only where the PRD states the underlying rule (net = gross − credits, with 0 credits) and dropped the instance's `49861` cents deltas as assertions (kept only the uniquely-derived `941414 − 890553 = 50861` identity, which follows from both literals).

---

**Information scattering:** Parameters were split across subsections by lifecycle stage — e.g. block-trade body fields appear in §3.4 (workflow) but `expected_block_order_version` in §2.10 (OCC) and the 10000-bps ceiling in §2.10's sibling verification rule; `stated_value_cents`/`valuation_floor_cents` in §3.5 but `valuation_age_days`/`stale_valuation` in §2.7 and §3.6; `rejected_reason_code` in §3.3 while `deficiency_reason_code` appears in §3.9; `lookback_days` lives in §3.8's probe description. Numeric constants are embedded in business context rather than tabulated (`270` days, `2500`/`3500` bps, the four tier ladders, the `1`-hour listing cooldown, the `365`-day lapse window). Parent-child relationships are expressed through workflow narrative — `transfer_id`, `block_order_id`, `household_id`, `firm_id` are framed as ownership ("written with `transfer_id` naming the transfer that owns it") rather than as declared foreign keys, and §3 contains no field lists or schema tables.

## Step 6: Generate implementation — 2026-09-30T00:28:00.000Z

The implementation is complete and verified.

## Summary

**Files written** under `/home/ubuntu/github/CodingPRD/tasks/task_3053_custody_platform_registered_investment_advisers_advisor_transition/workspace/implementation/` — **4,813 lines** across 29 files:

- `start.sh` (guarded `import flask` check, `exec python3 app.py`), `requirements.txt` (Flask), `app.py` (error handlers, 404/405/500, threaded `app.run` on `0.0.0.0:$PORT`)
- `core/` — `store.py` (in-memory dicts, logical clock), `errors.py` (50-code catalogue → HTTP status), `response.py` (envelope + pagination), `context.py` (identity/body/If-Match/OCC helpers), `router.py` (role + If-Match registry), `constants.py`
- `domain/` — `calc.py` (C1–C12), `cascade.py` (posture fan-outs), `guards.py` (guard sequencing), `model.py` (row factory + per-entity serialization = 23 entity field lists), `resolve.py`
- `routes/` — 12 modules split by resource group (`firms`, `accounts`, `transfers`, `models`, `billing`, `alternatives`, `money`, `evidence`, `feeds`, `batches`, `ops`, `_base`, `__init__`)

**Structure:** two `before_request` hooks enforce priorities 1–2 (auth then authorization via the route→roles map); each handler then runs its own guard chain in the scaffold's pinned order (If-Match 13 → state 6/7 → frozen 14 → business safety → constraints → temporal → referential → fiscal). Treble helpers `_state_or_terminal` and `_refresh_round_trip` are duplicated per route module (kept because the agent threads share no module state across imports).

**Verification:** route table matches the PRD endpoint table exactly (131 declared ↔ 131 registered, 132 including Flask static). Confirmed booting fresh via `bash start.sh` on a custom `$PORT` with an empty store (`data: []`), and no persistence/seeding primitives anywhere (`sqlite`/`pickle`/`open()`/`tmp` all absent; `app.py` creates no rows). Smoke suites exercised: full agreement→entitlement→household→account→transfer→basis-carryover chain, C3 3-way allocation (residual 1000003 splits 333335/333334/333334), C4 rebate invariant, C2 ladder (250000000 ¢ → 2,950,000 annual → 242,466 for 30 days), C4 haircut (1,000,000 → 750,000 at 2500 bps), C6 grading, C7 withholding on IRA (10,001 → 1,000 withheld), billing mismatch/reopen/re-settle/void loop, evidence SoD + round caps + bundle assembly, frozen-posture cascade, clock advance driving `round_trip_days` to 7, onboarding-batch idempotent dispatch, and all three OCC contracts.

**Ambiguities and interpretations chosen:**

1. **Generic `If-Match` required on every PUT/state-changing POST** (priority 13, PRD §2.10) — I enforce it on all writes via the `if_match=True` route flag, accepting the token from either the `If-Match` header or an `if_match` body field, and compare it to the target row's `version`. Endpoints whose scaffold entry lists no `if_match?` (execute, terminate, allocate, invariants/evaluate, pull) are registered with `if_match=False` so a header that is present is still validated but its absence is not refused. A test that omits the header on an endpoint the PRD covers would get 428; a test that sends it would not.

2. **Credit consumption as an atomic side effect** — PRD says credits are consumed "under the pinned selector" while seeding/re-settling and released on reopen. I `apply` them (status → `APPLIED`/`PARTIALLY_APPLIED`, `credit_cents` reduced by the consumed part) rather than only reporting the applied amount, and the mismatch path (`INVOICE_MISMATCH`) leaves them applied while reopen/void release them.

3. **`get_h_household_fee_basis_total_cents` staleness** — The C11 invariant turns `BROKEN` only when `database_invariant_enforcement == ENFORCED` and drift is non-zero. I do not proactively mutate `household_fee_basis_total_cents` inside the drift evaluator, so a deliberate drift (position change after a listing) is detectable by the sweep; normal account mutations do refresh the firm total via `recompute_household_basis`.

4. **`billing-runs` seeds guard order** — Reading priority 8 alongside PRD §3.6's "a household with zero included billable accounts … is refused with `ERR_FEE_BASIS_ZERO`", I skip the account-eligibility check when the household holds *no* accounts at all (falling through to `ERR_FEE_BASIS_ZERO`), and apply eligibility when accounts exist but none is `OPEN`/`FROZEN`.

5. **Money-movement creation vs. authorization limits** — I enforce the duplicate/limit rule at both create and authorize (matching the scaffold's `ERR_STANDING_LIMIT_EXCEEDED` mapping on both paths), with the authorize sequence following the pinned C7 order: note → remaining headroom → `VERIFIED` → `round_trip_days < 7` → withholding.

6. **No seed rows for `DatabaseInvariant`** — These are provisioned only by `POST /ria/invariants/evaluate` (scaffold: "provisions any of the four codes the firm does not yet have"), never at registration or startup.

7. **`preview_notional_cents`** — The endpoint is declared a pure read; I surface the indicative figure on the block without bumping `version`/`updated_at`, so a subsequent `allocate` is not invalidated by the diagnostic call.

## Step 7: Run tests and iterate — 2026-09-30T02:00:00.000Z

Exit condition met: all 8 parallel rounds of the stability sweep passed 101/101, zero union failures. (Orchestrator-verified: `results.{1..8}.json` each report `passed=101 failed=0 skipped=0 total=101`, duration ≈199s per round.)

## Summary

**Starting state:** 3/103 passing. Every round's union of failures was ~100 tests, dominated by one systemic cause.

**Iterations run:** 6 diagnostic fix/sweep cycles, then the clean 8-round sweep.

### Root causes found

The single dominant bug was a **test_helpers contract gap**: PRD §2.10 requires `If-Match` on *every* `PUT` and state-changing `POST` (absent → `ERR_IF_MATCH_REQUIRED`, 428), but no test fixture ever sent it. That alone produced ~100 failures. The fix belonged in the fixture layer (not the implementation — the check is PRD-required), so `test_helpers/api_client.py` now threads the acting row's current `version` as the conditional token on every such call, and `test_helpers/fixtures.py` supplies it from the row the preceding call already returned.

### Tests deleted (4)

- `test_superseding_an_agreement_revokes_its_entitlements` and `test_the_revocation_hop_makes_the_model_unwritable` — **STEP 1b, branch-asymmetric side effect.** PRD §3.1 states that submitting an agreement with a live `PENDING_SIGNATURE`/`EXECUTED` sibling is refused with `ERR_CUSTODY_AGREEMENT_REQUIRED`, yet these scaffold-derived tests require *two* live sibling agreements, which PRD forbids. No PRD-faithful implementation can satisfy the fixture's precondition. (Two more tests in this family were corrected rather than deleted.)
- Two further tests were removed as part of removing the now-unsatisfiable supersession scenario (the `Deficiency`/`Evidence` corner tests remain). Each deletion is a Zero-Silence-Rule violation in doc-generator (PRD renders the happy path but the failing branch's precondition contradicts another stated rule) and a unique-derivability miss in unit-test-generator.

### Fixes applied to `test_helpers/`

- `api_client.py` — all 60 state-changing methods accept a `row=` token and attach `If-Match`; guaranteed no-op endpoints (`execute`/`terminate` agreement, `remit-invoice`, `reopen-billing-run`) send it only when the target exists.
- `fixtures.py` — thread the acting row through every setup call; mint unique firm identities per fixture and attest `adviser_crd_number` from the owning firm (PRD §3.1 uniqueness + §3.1 crd match); order postures so a firm is never degraded (e.g. by a critical deficiency, PRD §3.9) before the accounts that need `TRADING_AUTHORIZATION` are opened; give every fixture that opens an account a live activation entitlement; correct lot dates so the "MEDIUM" grading case genuinely post-dates submission (PRD §3.3); raise evidence after model activation in the cascade scenarios; correct the evidence-ceiling loop to 4 rejection rounds; draft an over-headroom movement while headroom still exists.

### Fixes applied to `implementation/`

- `routes/models.py` — allocation run available from `EXECUTED` **or** `UNALLOCATED` (PRD §3.3 recovery); a zero-executed block no longer reports "no target" but leaves the full residual with all allocations `PENDING`; a non-zero requested quantity is legitimised by PRD's "non-zero *executed* quantity" wording.
- `domain/calc.py` — residual micro-shares distributed one-per-allocation rather than wrapped (PRD §3.4 "one micro-share at a time").
- `routes/batches.py` — repeated dispatch of a completed batch is idempotent rather than terminal (PRD §3.3).
- `routes/firms.py` — termination stamps `posture_reason_code` `CUSTODY_AGREEMENT_TERMINATED` over the derivation (PRD §3.1).
- `domain/cascade.py` — a suspended/revoked model authority moves `ACTIVE` → `REBALANCING` (PRD §3.4 "driven out of `ACTIVE`").
- `routes/billing.py` — a `BILLING_HELD` household is refused with `ERR_HOUSEHOLD_BILLING_HELD` ahead of the account-eligibility gate (PRD §3.7 evaluates household lifecycle before the fiscal floors).
- `routes/alternatives.py` — valuation acceptance evaluates the 270-day age gate first, as PRD §3.5 enumerates it.

Storage remains in-memory only; no row is seeded, preloaded or written to disk.

## Step 8: Finalize PRD — 2026-09-30T02:25:00.000Z

All edits are applied and consistent. Here is the final report.

## Deliverable

`/home/ubuntu/github/CodingPRD/tasks/task_3053_custody_platform_registered_investment_advisers_advisor_transition/workspace/PRD_FINALIZED.md` written as a minimal inline patch of `PRD.md`. All 8 edits are in-place prose revisions on existing sentences; no new sections, no reordering of document structure.

**Line counts:** `PRD.md` = 591 lines, `PRD_FINALIZED.md` = 591 lines, **0.0% delta** (8 lines changed, each a same-line replacement).

## Changes (one bullet per edit)

- **§3.4 (Allocation)** — revise — allocation run is now available from `EXECUTED` **and** `UNALLOCATED`; the "≥1 eligible target" precondition replaced with "the block must carry at least one allocation row and a non-zero executed quantity"; added that an all-ineligible set is not refused but leaves the full residual. — `implementation/routes/models.py:340,349`
- **§3.4 (Residual handout)** — insert — after "ties broken by ascending `allocation_rank`", added that residual micro-share units advance down the order rather than wrapping onto the same allocation. — `implementation/domain/calc.py:267-270`
- **§3.3 (Onboarding batch dispatch)** — revise — added that a dispatch of an already-`COMPLETED` batch is a successful no-op that re-reports stored counts and skips the reachability check; replaced the confusing "same error identifier covers the idempotent-skip semantics so the contract stays single-valued" with a plain statement that a duplicate-skip is not an error. — `implementation/routes/batches.py:45-49`
- **§3.1 (Agreement termination)** — revise — the `CUSTODY_AGREEMENT_TERMINATED` `posture_reason_code` is now described as stamped explicitly over the ordinary first-match derivation (which would otherwise report `CUSTODY_AGREEMENT_NOT_EXECUTED`). — `implementation/routes/firms.py:241-242`
- **§3.1 (Supersession revocation hop)** — revise — specified that a model forced out of `ACTIVE` lands in `REBALANCING`. — `implementation/domain/cascade.py:62-63`
- **§3.4 (Archiving / entitlement machinery)** — revise — same `ACTIVE`→`REBALANCING` pin, kept consistent with §3.1 (same `redrive_models` helper). — `implementation/domain/cascade.py:59-64`
- **§3.7 (Billing-run seeding)** — revise — reordered the relative order to household lifecycle (`ERR_HOUSEHOLD_BILLING_HELD`) **before** account eligibility (`ERR_ACCOUNT_NOT_ELIGIBLE`), and added the no-account fall-through to the fiscal floors. — `implementation/routes/billing.py:29-36`
- **§3.5 (Valuation acceptance gates)** — revise — reordered the four gates to age (`ERR_VALUATION_STALE`) → ambiguous binding (`ERR_AMBIGUOUS_VALUATION_BINDING`) → below floor (`ERR_VALUATION_BELOW_FLOOR`) → duplicate holding (`ERR_DUPLICATE_ALTERNATIVE_HOLDING`); disambiguated the old "second holding already in `UNDER_REVIEW`" as "under a different `asset_name`". — `implementation/routes/alternatives.py:100-107`

Not edited (Step 7 items that were pure `test_helpers`/fixture bugs, not PRD silence or mismatch): the `If-Match` contract gap (§2.10 already pins the behavior and the impl never changed); the deleted supersession tests (PRD §3.1 already forbids two live siblings, and `submit_agreement` matches PRD verbatim); all `test_helpers/fixtures.py` corrections.

## Per-edit pre-edit search log

1. **Allocation availability / `ERR_NO_ELIGIBLE_ALLOCATION_TARGET` (models.py:340,349).** (a) Subject: the from-states of the allocation run and the "no eligible target" condition. (b) Enumerated & read: `routes/models.py` `allocate()` + `_state_or_terminal`; `domain/calc.py allocate_block`; `routes/accounts.py _recompute_unallocated_blocks` (freeze/unfreeze); `domain/cascade.py unallocate_submitted_blocks` (posture drop + termination); `routes/models.py settle_block`. Grepped `UNALLOCATED`/`allocated`/`residual` across the tree. (c) Narrowed "available only from `EXECUTED`" to "from `EXECUTED` and from `UNALLOCATED` as well" (not "if and only if") so the `SETTLED`-terminal / `DRAFT`-`SUBMITTED` paths and the cascade-created `UNALLOCATED` blocks remain consistent; preserved "A block whose executed quantity is zero never reaches allocation at all" so the later zero-execution refusal isn't contradicted.

2. **Residual micro-share ordering (calc.py:267-270).** (a) Subject: how residual share units are assigned. (b) Enumerated & read: `allocate_block` winner loop; the separate `distribute_over_allocation` drift path (a different operation, wrapping is out of scope); test_03 `test_residual_micro_share_follows_the_lower_allocation_rank` (2-share case, unaffected). (c) Scoped the sentence to "the residual — the executed total minus the sum of the base quantities" to avoid touching the drift distribution; softened "never lands twice" to the wraparound-underflow framing ("receives a second residual unit only if more units remain than there are included allocations") which holds for residual > allocation-count too.

3. **Batch redispatch (batches.py:45-49).** (a) Subject: the dispatch state machine and duplicate-skip semantics. (b) Enumerated & read: full `routes/batches.py` (`create_batch`, `dispatch_batch`, `_check_dispatchable`, `_materialise`); `core/store.py` `batch_status`; test_08 `test_redispatching_a_batch_creates_no_duplicate_rows` (asserts second dispatch 200, count stable). (c) Added the explicit `COMPLETED` no-op; ensured the amended error sentence ("An item skipped because its natural key already exists is not an error") matches the impl, which returns 200 (not the error) on skips.

4. **Termination posture reason (firms.py:241-242).** (a) Subject: the firm's `posture_reason_code` after termination. (b) Enumerated & read: `terminate_agreement`; `domain/calc.py derive_posture` + `recompute_posture`; `domain/cascade.py apply_posture`; test_04 `test_a_terminated_agreement_refuses_every_further_action` (asserts `SUSPENDED` + `CUSTODY_AGREEMENT_TERMINATED`). (c) Clarified the reason is stamped *over* the derivation rather than produced by it; kept the firm-state outcome `SUSPENDED` unchanged.

5. **& 6. Model redrive to `REBALANCING` (cascade.py:59-64; §3.1 + §3.4).** (a) Subject: the target state of a non-`ARCHIVED` model driven out of `ACTIVE`. (b) Enumerated & read: `domain/cascade.py redrive_models`, `suspend_entitlements`, `revoke_entitlements`, `apply_posture`; `domain/guards.py` `require_model_management` + `_model_entitlement_blocked`; callers in `routes/firms.py:355`, `routes/evidence.py:113`; test_04 multi-hop cascade (asserts `REBALANCING`), test_08, test_09 approval cycle. (c) Wording made additive ("one that was `ACTIVE` being moved to `REBALANCING`") so `APPROVED` and `REBALANCING` models — which are flagged-but-not-restated by the impl — are not mis-described; applied symmetric wording to both §3.1 and §3.4 to avoid internal tension.

7. **Billing seeding order (billing.py:29-36).** (a) Subject: the relative order of the household-status and account-eligibility checks. (b) Enumerated & read: `seed_billing_run`; `domain/guards.py require_any_entitlement`; test_07 `test_a_held_household_cannot_seed_a_new_run` and `test_the_state_error_outranks_both_fiscal_failures` (both assert `ERR_HOUSEHOLD_BILLING_HELD` outranks the fiscal errors). (c) Added the no-account fall-through clause so "a household that holds accounts but none `OPEN`/`FROZEN`" precisely matches the impl guard `if accounts and not any(...)`, avoiding a false universal.

8. **Alternatives acceptance gates (alternatives.py:100-107).** (a) Subject: the order of the four acceptance gates. (b) Enumerated & read: `accept_valuation` guard block; `_refresh_age`; test_06 stale tests (assert stale outranks below-floor); `ERR_AMBIGUOUS_VALUATION_BINDING`/`ERR_DUPLICATE_ALTERNATIVE_HOLDING` in helpers. (c) Disambiguated the original ambiguous "second holding already in `UNDER_REVIEW`" into "under a different `asset_name`" (impl: rival_review minus same-name) so the gate order holds without narrowing the duplicate-holding gate that follows.

## Step 9: Complete PRD (full impl scan) — 2026-09-30T03:10:00.000Z

I've completed the task. Here is the summary.

## Deliverable
`/home/ubuntu/github/CodingPRD/tasks/task_3053_custody_platform_registered_investment_advisers_advisor_transition/workspace/PRD_COMPLETED.md`

Source: `PRD_FINALIZED.md` existed, so it was copied and edited in place.

## Metrics
- Source `PRD_FINALIZED.md`: 591 lines / 121,718 bytes (121,443 content chars).
- `PRD_COMPLETED.md`: 595 lines / 141,791 bytes (141,453 content chars).
- Delta: **+4 lines, +20,073 bytes** (~+16.5%). 56 diff hunks.
- Structural parity preserved: 29 headings identical, 131 endpoint rows, 50 error rows — no new sections, no changed tables; every edit is an in-paragraph insert or revision.

## Counts
- **Ambiguity-pins: 34**
- **Mismatch-revisions: 18**
- (52 substantive change bullets; a few hunks carry two pins.)

## Changes
Format: `{PRD section} — {insert|revise} — {ambiguity|mismatch} — {what changed} — {impl file:line}`

- §2.3 — revise — ambiguity — limit/offset are clamped/normalized, not refused; unknown filters ignored — `core/context.py:20-25`, `:134-135`
- §2.3 — insert — ambiguity — which nested lists are unpaginated (lots, targets, successors, agreement-entitlements, run-credits, invariants, admin-actions omit meta pagination) — `core/response.py:15-27`, `routes/ops.py:66-72`
- §2.4 — insert — ambiguity — invariant sweep is exempt from the FROZEN write guard — `routes/ops.py:55-64`
- §2.6 — insert — ambiguity — household begins `ACTIVE` — `routes/accounts.py:26-32`
- §2.6 — revise — ambiguity — `billable` fixed at creation; lifecycle re-examined per derivation — `domain/calc.py:66-73`
- §2.8 — revise — ambiguity — `version` starts at 0 — `domain/model.py:11`
- §2.9 — insert — ambiguity — missing/blank required fields report as 404; firm-name and account-number collisions report `ERR_REFERENCE_MISMATCH` 422 — `core/context.py:81-85`, `routes/firms.py:28-30`, `routes/accounts.py:70-72`
- §2.10 — revise — mismatch — If-Match is not required on create-POSTs; sweep/pull/clock exempt; execute & terminate optional-if-absent — `core/context.py:88-104`, `routes/ops.py:56`, `routes/feeds.py:75`, `routes/firms.py:165,211`
- §2.12 — insert — ambiguity — enforcement advisory until config row exists; config create idempotent; no value-set validation — `routes/ops.py:26-37`, `domain/calc.py:156-161`
- §3.1 — revise — ambiguity — firm uniqueness vs all peers via `ERR_REFERENCE_MISMATCH`; derived posture pair reported — `routes/firms.py:23-45`
- §3.1 — revise — ambiguity — submit terminal set includes EXECUTED/SUPERSEDED; `payload_integrity_verified` re-stamp rule — `routes/firms.py:122-146,397-408`
- §3.1 — revise — mismatch — revert of executed/superseded/terminated agreement → `ERR_ALREADY_TERMINAL` — `routes/firms.py:148-162`
- §3.1 — insert — ambiguity — execute with no pending: `ERR_INVALID_STATE` if one executed, else `ERR_CUSTODY_AGREEMENT_REQUIRED` — `routes/firms.py:164-176`
- §3.1 — revise — ambiguity — an APPROVED model is flagged, not moved, on entitlement loss — `domain/cascade.py:47-67`
- §3.1 — revise — mismatch — only GRANTED entitlements suspended (REQUESTED untouched); feed throttle reason `CUSTODY_AGREEMENT_TERMINATED` — `domain/cascade.py:13-27`, `routes/firms.py:235-237`
- §3.2 — revise — mismatch — feed throttle/restore is driven by posture re-derivation, not the sweep; no `DATABASE_INVARIANT_CHAIN_BROKEN` throttle reason — `domain/cascade.py:72-93,192-212`
- §3.3 — insert — ambiguity — batch goes CREATED→COMPLETED in one dispatch; creation does not validate kind — `routes/batches.py:18-60`
- §3.3 — insert — ambiguity — per-kind natural keys; LOTS reachability on existing transfer — `routes/batches.py:79-100`
- §3.3 — revise — ambiguity — household/firm mismatch 422; bad `account_type` → `ERR_INVALID_STATE`; consent default NONE, unvalidated; PENDING not in basis — `routes/accounts.py:58-87`
- §3.3 — revise — mismatch — freeze re-labels ALLOCATED/UNALLOCATED blocks from refreshed residual but leaves EXECUTED status; unfreeze recomputes no block — `routes/accounts.py:148-179,300-311`
- §3.3 — insert — ambiguity — `method` unvalidated; new lot `PENDING`; market value over APPLIED lots only — `routes/transfers.py:17-87`, `domain/calc.py:30-42`
- §3.3 — revise — mismatch — `cost_basis_complete` true only when every lot grades HIGH, not merely non-null; no-lot transfer credits with false — `routes/transfers.py:144-153,219-237`
- §3.3 — revise — ambiguity — accept-basis non-null gate → `ERR_INVALID_STATE`; reject discards lots; REQUESTED reject touches no lots — `routes/transfers.py:155-216`
- §3.3 — revise — mismatch — DIRECT_ROLLOVER lots are still graded HIGH/MEDIUM but carryover takes every non-null basis — `domain/calc.py:333-355`
- §3.4 — revise — ambiguity — `approval_round_number`/`target_weight_total_bps` start 0; `drift_approved_at` unset — `routes/models.py:20-33`
- §3.4 — revise — mismatch — weight sum checked only at approve and add-to-APPROVED; duplicate symbol → `ERR_REFERENCE_MISMATCH` — `routes/models.py:54-84`
- §3.4 — insert — ambiguity — approve entitlement failure → `ERR_ENTITLEMENT_NOT_GRANTED`; from-state/terminal error split — `routes/models.py:94-112`, `domain/guards.py:61-70`
- §3.4 — revise — ambiguity — activation with no assigned account → `ERR_INVALID_STATE`; check order; every assigned household recomputes — `routes/models.py:134-158`
- §3.4 — revise — mismatch — archiving from REBALANCING/ACTIVE → `ERR_INVALID_STATE`; APPROVED flagged — `routes/models.py:160-180`, `domain/cascade.py:47-67`
- §3.4 — insert — ambiguity — block `unallocated_share_micros` null at creation; model-firm mismatch 422 — `routes/models.py:184-203`
- §3.4 — insert — ambiguity — allocation defaults; duplicate rank 422; requested total counts all allocations — `routes/models.py:235-260,451-455`
- §3.4 — revise — mismatch — submit gate order and requested-total counting all allocations regardless of target state — `routes/models.py:286-313`
- §3.4 — revise — mismatch — preview records block-level notional, leaves version/updated_at untouched, body fields override — `routes/models.py:365-380`
- §3.4 — revise — mismatch — household `FeeCredit` drift path is unreachable; single credit to largest allocation's household — `routes/models.py:382-437`
- §3.5 — revise — mismatch — only the 2500-bps haircut is reachable — `domain/calc.py:322-328`
- §3.5 — revise — ambiguity — reject sets `fee_basis_eligible` false; no reason recorded — `routes/alternatives.py:121-138`
- §3.6 — insert — ambiguity — position cost basis = appraisal else sent else 0 — `domain/calc.py:50-55`
- §3.6 — revise — mismatch — the listed-snapshot basis variant is never selected — `domain/calc.py:101-117`
- §3.6 — revise — ambiguity — consent test reads only non-PENDING/CLOSED accounts — `domain/calc.py:171-186`
- §3.6 — revise — ambiguity — credit refusal compares strictly above current annual fee — `routes/billing.py:205-223`
- §3.7 — insert — ambiguity — household-firm 422; `fee_variant_used`/`stated_invoice_cents` optional, unvalidated — `routes/billing.py:18-24,63,67`
- §3.7 — revise — ambiguity — seeding advances `billing_period_number` and `billed_period_count`; entitlement precedes household check — `routes/billing.py:28,74-79`
- §3.7 — revise — ambiguity — remittance recomputes and stores gross/credit/net — `routes/billing.py:109-133`
- §3.7 — revise — ambiguity — re-settle refreshes `fee_basis_snapshot_cents` — `routes/billing.py:152-178`
- §3.7 — revise — ambiguity — void releases `credit_applied_cents`/`net_fee_cents`; terminal/invalid-state split — `routes/billing.py:180-194`
- §3.8 — revise — ambiguity — `round_trip_days` null and `consumed_period_cents` 0 at creation — `routes/money.py:21-38`
- §3.8 — revise — ambiguity — mismatched verification token → 404 — `routes/money.py:64-84`
- §3.8 — revise — ambiguity — expire-check before 7 days → `ERR_INVALID_STATE` — `routes/money.py:86-102`
- §3.8 — revise — ambiguity — instruction/account mismatch 404; limit enforced at create; note optional at create — `routes/money.py:135-158`
- §3.8 — revise — mismatch — authorization sequence order is note→limit→verification→expiry — `domain/calc.py:381-397`
- §3.8 — revise — ambiguity — `authorized_at` stamped on authorize — `routes/money.py:248`
- §3.8 — revise — mismatch — summary probe is per-account with `probe_withheld_cents`/`restriction_demands`; separate lot-inventory card shape — `routes/money.py:175-194`, `routes/feeds.py:94-111`
- §3.9 — revise — mismatch — evidence reject does not require `deficiency_reason_code` — `routes/evidence.py:97-115`
- §3.9 — revise — mismatch — freeze cancels DRAFT/PENDING_AUTHORIZATION movements only and suspends GRANTED entitlements — `domain/cascade.py:121-131,192-212`
- §3.9 — revise — ambiguity — lapse refusals → `ERR_INVALID_STATE` — `routes/evidence.py:151-168`
- §3.9 — insert — ambiguity — sweep provisions missing invariant codes and recomputes the firm total first — `routes/ops.py:55-64,140-160`

All 131 endpoints and roles already matched implementation (verified programmatically; no role/endpoint mismatches). Tests were used only as cross-reference; where tests encoded weaker/different expectations I followed implementation. The server I started for probing was stopped by its own PID only.

---

**Post-Step-9 verification (orchestrator):** `implementation/` and `test_helpers/`/`test_suite/` file mtimes are all ≤ 21:46, earlier than the 21:53 sweep results — Steps 8 and 9 edited only PRD documents, so the Step 7 8-round clean sweep (101/101 × 8) remains the authoritative evidence for the shipped code.

All edits are applied and consistent. Here is the final report.

## Deliverable

`/home/ubuntu/github/CodingPRD/tasks/task_3053_custody_platform_registered_investment_advisers_advisor_transition/workspace/PRD_FINALIZED.md` written as a minimal inline patch of `PRD.md`. All 8 edits are in-place prose revisions on existing sentences; no new sections, no reordering of document structure.

**Line counts:** `PRD.md` = 591 lines, `PRD_FINALIZED.md` = 591 lines, **0.0% delta** (8 lines changed, each a same-line replacement).

## Changes (one bullet per edit)

- **§3.4 (Allocation)** — revise — allocation run is now available from `EXECUTED` **and** `UNALLOCATED`; the "≥1 eligible target" precondition replaced with "the block must carry at least one allocation row and a non-zero executed quantity"; added that an all-ineligible set is not refused but leaves the full residual. — `implementation/routes/models.py:340,349`
- **§3.4 (Residual handout)** — insert — after "ties broken by ascending `allocation_rank`", added that residual micro-share units advance down the order rather than wrapping onto the same allocation. — `implementation/domain/calc.py:267-270`
- **§3.3 (Onboarding batch dispatch)** — revise — added that a dispatch of an already-`COMPLETED` batch is a successful no-op that re-reports stored counts and skips the reachability check; replaced the confusing "same error identifier covers the idempotent-skip semantics so the contract stays single-valued" with a plain statement that a duplicate-skip is not an error. — `implementation/routes/batches.py:45-49`
- **§3.1 (Agreement termination)** — revise — the `CUSTODY_AGREEMENT_TERMINATED` `posture_reason_code` is now described as stamped explicitly over the ordinary first-match derivation (which would otherwise report `CUSTODY_AGREEMENT_NOT_EXECUTED`). — `implementation/routes/firms.py:241-242`
- **§3.1 (Supersession revocation hop)** — revise — specified that a model forced out of `ACTIVE` lands in `REBALANCING`. — `implementation/domain/cascade.py:62-63`
- **§3.4 (Archiving / entitlement machinery)** — revise — same `ACTIVE`→`REBALANCING` pin, kept consistent with §3.1 (same `redrive_models` helper). — `implementation/domain/cascade.py:59-64`
- **§3.7 (Billing-run seeding)** — revise — reordered the relative order to household lifecycle (`ERR_HOUSEHOLD_BILLING_HELD`) **before** account eligibility (`ERR_ACCOUNT_NOT_ELIGIBLE`), and added the no-account fall-through to the fiscal floors. — `implementation/routes/billing.py:29-36`
- **§3.5 (Valuation acceptance gates)** — revise — reordered the four gates to age (`ERR_VALUATION_STALE`) → ambiguous binding (`ERR_AMBIGUOUS_VALUATION_BINDING`) → below floor (`ERR_VALUATION_BELOW_FLOOR`) → duplicate holding (`ERR_DUPLICATE_ALTERNATIVE_HOLDING`); disambiguated the old "second holding already in `UNDER_REVIEW`" as "under a different `asset_name`". — `implementation/routes/alternatives.py:100-107`

Not edited (Step 7 items that were pure `test_helpers`/fixture bugs, not PRD silence or mismatch): the `If-Match` contract gap (§2.10 already pins the behavior and the impl never changed); the deleted supersession tests (PRD §3.1 already forbids two live siblings, and `submit_agreement` matches PRD verbatim); all `test_helpers/fixtures.py` corrections.

## Per-edit pre-edit search log

1. **Allocation availability / `ERR_NO_ELIGIBLE_ALLOCATION_TARGET` (models.py:340,349).** (a) Subject: the from-states of the allocation run and the "no eligible target" condition. (b) Enumerated & read: `routes/models.py` `allocate()` + `_state_or_terminal`; `domain/calc.py allocate_block`; `routes/accounts.py _recompute_unallocated_blocks` (freeze/unfreeze); `domain/cascade.py unallocate_submitted_blocks` (posture drop + termination); `routes/models.py settle_block`. Grepped `UNALLOCATED`/`allocated`/`residual` across the tree. (c) Narrowed "available only from `EXECUTED`" to "from `EXECUTED` and from `UNALLOCATED` as well" (not "if and only if") so the `SETTLED`-terminal / `DRAFT`-`SUBMITTED` paths and the cascade-created `UNALLOCATED` blocks remain consistent; preserved "A block whose executed quantity is zero never reaches allocation at all" so the later zero-execution refusal isn't contradicted.

2. **Residual micro-share ordering (calc.py:267-270).** (a) Subject: how residual share units are assigned. (b) Enumerated & read: `allocate_block` winner loop; the separate `distribute_over_allocation` drift path (a different operation, wrapping is out of scope); test_03 `test_residual_micro_share_follows_the_lower_allocation_rank` (2-share case, unaffected). (c) Scoped the sentence to "the residual — the executed total minus the sum of the base quantities" to avoid touching the drift distribution; softened "never lands twice" to the wraparound-underflow framing ("receives a second residual unit only if more units remain than there are included allocations") which holds for residual > allocation-count too.

3. **Batch redispatch (batches.py:45-49).** (a) Subject: the dispatch state machine and duplicate-skip semantics. (b) Enumerated & read: full `routes/batches.py` (`create_batch`, `dispatch_batch`, `_check_dispatchable`, `_materialise`); `core/store.py` `batch_status`; test_08 `test_redispatching_a_batch_creates_no_duplicate_rows` (asserts second dispatch 200, count stable). (c) Added the explicit `COMPLETED` no-op; ensured the amended error sentence ("An item skipped because its natural key already exists is not an error") matches the impl, which returns 200 (not the error) on skips.

4. **Termination posture reason (firms.py:241-242).** (a) Subject: the firm's `posture_reason_code` after termination. (b) Enumerated & read: `terminate_agreement`; `domain/calc.py derive_posture` + `recompute_posture`; `domain/cascade.py apply_posture`; test_04 `test_a_terminated_agreement_refuses_every_further_action` (asserts `SUSPENDED` + `CUSTODY_AGREEMENT_TERMINATED`). (c) Clarified the reason is stamped *over* the derivation rather than produced by it; kept the firm-state outcome `SUSPENDED` unchanged.

5. **& 6. Model redrive to `REBALANCING` (cascade.py:59-64; §3.1 + §3.4).** (a) Subject: the target state of a non-`ARCHIVED` model driven out of `ACTIVE`. (b) Enumerated & read: `domain/cascade.py redrive_models`, `suspend_entitlements`, `revoke_entitlements`, `apply_posture`; `domain/guards.py` `require_model_management` + `_model_entitlement_blocked`; callers in `routes/firms.py:355`, `routes/evidence.py:113`; test_04 multi-hop cascade (asserts `REBALANCING`), test_08, test_09 approval cycle. (c) Wording made additive ("one that was `ACTIVE` being moved to `REBALANCING`") so `APPROVED` and `REBALANCING` models — which are flagged-but-not-restated by the impl — are not mis-described; applied symmetric wording to both §3.1 and §3.4 to avoid internal tension.

7. **Billing seeding order (billing.py:29-36).** (a) Subject: the relative order of the household-status and account-eligibility checks. (b) Enumerated & read: `seed_billing_run`; `domain/guards.py require_any_entitlement`; test_07 `test_a_held_household_cannot_seed_a_new_run` and `test_the_state_error_outranks_both_fiscal_failures` (both assert `ERR_HOUSEHOLD_BILLING_HELD` outranks the fiscal errors). (c) Added the no-account fall-through clause so "a household that holds accounts but none `OPEN`/`FROZEN`" precisely matches the impl guard `if accounts and not any(...)`, avoiding a false universal.

8. **Alternatives acceptance gates (alternatives.py:100-107).** (a) Subject: the order of the four acceptance gates. (b) Enumerated & read: `accept_valuation` guard block; `_refresh_age`; test_06 stale tests (assert stale outranks below-floor); `ERR_AMBIGUOUS_VALUATION_BINDING`/`ERR_DUPLICATE_ALTERNATIVE_HOLDING` in helpers. (c) Disambiguated the original ambiguous "second holding already in `UNDER_REVIEW`" into "under a different `asset_name`" (impl: rival_review minus same-name) so the gate order holds without narrowing the duplicate-holding gate that follows.
