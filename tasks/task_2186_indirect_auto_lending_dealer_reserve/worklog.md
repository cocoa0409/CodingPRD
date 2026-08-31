# Worklog — task_2186_indirect_auto_lending_dealer_reserve

## Step 1: Create task directory — 2026-08-30T10:51:26.787162677Z

Created `tasks/task_2186_indirect_auto_lending_dealer_reserve/` and `workspace/` (index 2186 = highest existing 2185 + 1).

## Step 3: Copy shared files — 2026-08-30T10:51:45.596883740Z

Copied `INSTRUCTION.md` from project root to `workspace/INSTRUCTION.md` (1424 bytes). Run out of order (before Step 2 completed) since it has no dependency on the scaffold.

## Step 2: Generate scaffold — 2026-08-30T11:43:07.532725877Z

All three artifacts are generated and pass the skill's linter clean on the first full run.

### Files

| File | Lines |
|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_2186_indirect_auto_lending_dealer_reserve/SCAFFOLD.yaml` | 2565 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2186_indirect_auto_lending_dealer_reserve/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2041 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2186_indirect_auto_lending_dealer_reserve/SCAFFOLD_CORNER_DESIGN.yaml` | 3849 |

### Scaffold contents (§1.0–§1.7)

12 entities · 10 state machines (54 transitions) · 2 concurrency rules · 6 calculations · 29 validations · 41 endpoints · 37 errors · 5 roles. Expert band, `api_prefix: /lending`, difficulty pushed above the band on endpoint/error surface as requested.

Profile: pricing_engine × compliance_audit, **flat** topology, **branching** state shape, **segregation_of_duties** role model — all three of the diversity-prioritized options in §0.3.

Design highlights that carry the difficulty:
- **Tier demotion trap**: demotions are counted once against the *base* tier's caps and the demoted tier's own caps are deliberately not re-evaluated (a re-checking implementation returns `ERR_NO_ELIGIBLE_TIER` where an approval is required).
- **Rounding-order pin**: chargeback rounds per accrual entry then sums (80530), where sum-then-round gives 80529.
- **Frozen benchmark**: fair-lending dollar-weighted benchmark is 119 bps computed once over the whole population; the unweighted (125) and control-only (75) alternatives produce different remediation pools, so the literal 53075 falsifies both.
- **Parallel dimensions**: `RetailContract.funding_status × reserve_status` on one row; buyback issue/withdraw moves only the reserve axis.
- Two OCC races on `Dealer.version` (supersede-agreement create, manual reserve adjustment), both passing the §1.2.1 serial-observability filter.

### Design indices

- **§1.8**: 19 instances across all 9 rule_ids (2 each, 3 for `combinatorial_formula` so modes (a)/(b)/(c) are each covered).
- **§1.9**: 59 instances over all 9 guide sections — 50 executable recipes + 9 `excluded_because` stubs pointing at named §1.8 instances.

### Verification performed

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5
and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints declared:    41
  §1.1 entities declared:     12
  §1.8 instances scanned:     19
  §1.9 instances scanned:     50
  Calls scanned (§1.8+§1.9):  1099
```

Beyond the linter I ran custom checks confirming: zero unbound `${var}` and zero duplicate captures across 1099 calls; zero duplicate instance names across both files; every `grounds:` ref (entities/fields, calculations, validations-by-priority, errors, roles, endpoints, concurrency_rules, state-machine transitions) resolves into `SCAFFOLD.yaml`; every stub's cited §1.8 instance exists; no forbidden concurrency vocabulary anywhere. All 18 FKs use the canonical `FK -> X.id` prefix and each has a reverse-reachability GET.

Every formula-derived assertion literal (154055 / 7003 / 80530 / 15406 / 2987058 / 119 / 53075 / 995 / 695 / 395 / 845 / 250000 / 2706958 …) was computed in Python against the declared formulas and constants before being written in.

One correction applied after review: a corner instance originally claimed `ERR_DEALER_NOT_ACTIVE` on a decision call whose application would in fact be `ON_HOLD` (so `ERR_INVALID_STATE` would win); it was rewritten to trigger via `POST /lending/applications`, which has no state precondition and so genuinely reaches the priority-13 rule.

## Step 4: Generate PRD — 2026-08-30T11:50:55.72382163Z

PRD generated and verified.

**Output:** `workspace/PRD.md` — 390 lines, written incrementally (1 Write + 5 heredoc appends), file ends complete at §5.

**Sections present**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications — 2.1 RBAC, 2.2 API Response Structure (verbatim), 2.3 Pagination, 2.4 Resource Identity/Auditing/Logical Clock, 2.5 Money, Basis Points, Percentages, Rounding, 2.6 OCC on the Dealer Record, 2.7 Path Resolution and Order of Rejection, 2.8 The Dealer Roll-Up, 2.9 Pinning/Effectivity/Two Interval Conventions, 2.10 Compliance Holds & Segregation of Duties, 2.11 Ledger Discipline
- §3 Business Logic — 3.1 Onboarding & Agreement Chain, 3.2 Rate Sheets/Tiers/Program Pricing, 3.3 Application Intake/Decisioning/Revision Cycle, 3.4 Contract Booking & Funding Package, 3.5 Funding/Participation/Reserve Ledger, 3.6 Portfolio Events & Reserve Chargeback, 3.7 Repurchase Demands & Settlement, 3.8 Scorecards/Fair Lending/Remediation, 3.9 Suspension/Reinstatement/Termination Cascade
- §4 Endpoint Definitions (4-column table, 41 rows)
- §5 Error Code Catalogue (2-column table, 37 rows)

**Hard Contract reports**

```
Field coverage check:
- entities[].fields: 122 required, 122 present, 0 missing
- endpoints[].request_body: 56 required, 56 present, 0 missing
- endpoints[].query_params: 16 required, 16 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 29 checked, 29 expressed in prose (global ordering stated explicitly in §2.7), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_dealer_version + ERR_STALE_DEALER_VERSION/412 all named in §2.6), 0 missing
- state_machines[].transitions: 10 machines / 51 transitions checked, 51 fully expressed, 0 missing
- calculations[]: 6 checked, 6 fully expressed (incl. both dealer_reserve_amount variants, both scorecard basis variants, pinned rounding orders and all constants), 0 missing
- validations[] conditions: 29 checked, 29 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 41 endpoints checked, all side_effects expressed; every multi-endpoint applies_to set enumerated, 0 missing
- entities[].fields[] structured content: 12 entities / 122 fields checked, defaults, initial values, enums and computed derivations reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked (EARLY_PAYOFF vs DEFAULT; RATE_PARTICIPATION vs FLAT_FEE; agreement-window superseding vs non-superseding; scorecard TRAILING_WINDOW vs INCEPTION_TO_DATE; review WITHIN_TOLERANCE vs EXCEEDS_THRESHOLD publish fork; document VERIFY vs REJECT), 6 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 275
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Coverage audit:** all 12 entities (Dealer, DealerAgreement, RateSheet, RateSheetTier, CreditApplication, RetailContract, ContractDocument, ReserveEntry, ChargebackEvent, DealerScorecard, FairLendingReview, BuybackDemand), all 10 state machines (including RetailContract's two independent dimensions), all 6 calculations, all 29 validations, all 41 endpoints, all 37 errors, and all 5 roles (with `identity:` translated — `DealerPrincipal` entity-backed, the other four opaque) are represented. No fuzzy/approximating words and no pseudocode operators appear; §2.2 is byte-identical to the canonical block. The two withheld design indices were not opened.

**Orchestrator verification:** PRD.md = 390 lines, §4 table = 41 endpoint rows, §5 table = 37 error rows, file terminates cleanly. Withhold audit over the agent's own transcript: 22 tool_use calls scanned, 0 referenced `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml` — constraint held.

## Step 6: Generate implementation — 2026-08-30T12:09:32.143104944Z

All test servers are stopped. Implementation complete.

Generated a complete Python + Flask implementation at `workspace/implementation/`.

**Files written (2405 lines total)**

| File | Lines | Contents |
|---|---|---|
| `core.py` | 584 | Logical clock (2026-08-01T00:00:00Z default), in-memory `Store`, response envelope, 37-code error catalog, auth/RBAC/dealer-scope, field validators, exact `Fraction`-based `round_half_up`, pagination, path resolvers |
| `services.py` | 459 | Dealer roll-up, ledger posting, straight-line amortization, participation/incentive accrual, chargeback proration, buyback snapshot, termination cascade, tier/sheet/agreement selection, scorecard composite, fair-lending disparity |
| `routes_contracts.py` | 341 | Contracts, documents, verify, fund, chargeback-events |
| `routes_agreements.py` | 261 | Dealer agreements (OCC, notice buffer, supersession) + rate sheets/tiers/publish |
| `routes_misc.py` | 253 | Reserve ledger, buyback demands, fair-lending reviews |
| `routes_applications.py` | 217 | Application intake, decisioning pricing engine, revision cycle |
| `routes_dealers.py` | 208 | Clock, dealers, status actions, reserve adjustments, scorecards |
| `app.py` | 70 | Entry point, blueprint registration, error handlers, global request lock, `0.0.0.0:$PORT` |
| `start.sh` / `requirements.txt` | 10 / 2 | Guarded pip install (`if ! python3 -c "import flask"`), `exec python3 app.py` |

**Endpoints: 41/41** implemented, matching the PRD §4 table exactly.

**Key fidelity decisions**
- All money/bps arithmetic uses `fractions.Fraction` with an exact half-up-away-from-zero rounder — never float. Rounding order is per-component where the PRD pins it (chargeback, remediation pool, scorecard deductions) and single-at-the-end for rate participation.
- Global rejection order follows PRD §2.7 verbatim, including PRD-over-scaffold precedence where they disagree: approval runs **sheet selection before agreement selection** (PRD §3.3 step order), overriding `validations[].priority` 14/15.
- All timestamps read the logical clock (including `created_at`); client-supplied datetimes are echoed verbatim, system-stamped ones use the canonical `.000Z` 3-digit form. List sorts tie-break on an insertion sequence since the static clock makes `created_at` non-unique.
- Storage is pure Python dicts; no seeding, no disk, empty store on every boot.

**Smoke-test result: PASS.** Three suites (~200 assertions) run against fresh `bash start.sh` boots on ports 18633/18634/18635, confirmed bound to `0.0.0.0`. Coverage included: full onboard→agreement→sheet→application→contract→docs→fund→chargeback→scorecard chain with hand-verified figures (reserve 110000, incentive 5000, chargeback 57500, earned-to-date 11000, composite 795/grade B); OCC 412s; agreement notice buffer vs. supersession nesting; rate-sheet overlap vs. touching windows; two-step demotion; FLAT_FEE branch; fair-lending benchmark 150/disparity 100/pool 55000 with REMEDIATION posting and hold release; buyback issue→dispute→acknowledge→settle and withdraw; termination cascade issuing 3 `DEALER_TERMINATION` demands; segregation of duties; compliance hold; funding-line and funding-window gates; resubmission limit; suspend/reinstate ON_HOLD round-trip; envelope, pagination and error-shape checks.

**Orchestrator verification:** 10 files present in `workspace/implementation/`. Withhold audit over the agent's transcript: 50 tool_use calls scanned, 0 referenced `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_suite/`, or `test_helpers/` — no design-index leak, no test-answer leak.

## Step 5: Generate unit tests — 2026-08-30T12:13:51.696699721Z

Test infrastructure and suite are complete and audited.

### Files written

**`test_helpers/`** (1,547 lines) — `__init__.py` 23, `types.py` 407, `api_client.py` 212, `api_errors.py` 88, `assertions.py` 223, `factories.py` 129, `constants.py` 45, `test_users.py` 49, `fixtures.py` 371.

**`test_suite/`** (3,165 lines) — `conftest.py` 35 plus nine domain-named files: `test_01_onboarding_and_agreements.py` 307, `test_02_rate_sheets_and_pricing.py` 438, `test_03_application_lifecycle.py` 285, `test_04_contract_booking_and_documents.py` 268, `test_05_funding_and_reserve_ledger.py` 362, `test_06_portfolio_events_and_chargebacks.py` 319, `test_07_repurchase_demands.py` 417, `test_08_scorecards_and_fair_lending.py` 463, `test_09_access_control_and_listings.py` 271.

### Coverage

- **88 tests emitted**, all collecting cleanly under pytest.
- **Queue A (Difficulty): 38 tests** — exactly 2 per each of the 19 §1.8 instances, zero shortfalls.
- **Queue B (Corner): 50 tests** — 1 per each of the 50 non-stub §1.9 instances, zero gaps. The 9 `excluded_because:` stubs were not translated; all 9 `difficulty_instance` cross-references verified to resolve to real §1.8 `name:` values.
- **Zero instances skipped** — every instance passed the PRD-first two-condition filter.
- Automated audit confirms: every test docstring carries **exactly one** `Design:` tag, as its **last line**, resolving to a real instance; **183 PRD quotations all survive a whitespace-normalized literal match against PRD.md** (C1); no `skip`/`skipif`/`xfail` anywhere; no scaffold references in generated code.

### Two reconciliations you should know about

1. **Unbound constant `BASE_REQUIRED_DOC_TYPES`.** `SCAFFOLD.yaml:498` leaves it unbound; the design indices assumed **two** doc types (all their fixtures upload RIC + TITLE only, and `contract_computed_fields_copied_from_application` literally asserts a 2-element array), while PRD §3.4 binds it verbatim to **three** — `RETAIL_INSTALLMENT_CONTRACT`, `TITLE_APPLICATION`, `INSURANCE_BINDER`. PRD-first: every fixture uploads and verifies all three (four when stipulated), and the affected literals were recomputed accordingly (`verified_doc_count` 3 not 2, etc.). Money/ledger literals are unaffected. **The implementation must require three base types** — if it ships two, ~40 tests fail at setup.

2. **`POST /lending/fair-lending-reviews/{id}/transition` action tokens are not in the PRD.** Unlike the dealer-status and buyback-action endpoints (whose `action` values §2.1 names verbatim), the PRD never names the field or the `PUBLISH`/`CLOSE` tokens for review transitions — a PRD-only implementer could not uniquely derive them. Per the two-reader rule I dropped only the transition-dependent assertions from two instances, keeping their creation-time cores (which carry the actual claims):
   - `Difficulty/combinatorial_formula/fair_lending_benchmark_frozen_evaluation_order` — dropped the `REMEDIATION_ORDERED` status, `REMEDIATION` ledger entry, `compliance_hold` and post-PUBLISH balance asserts; kept the dollar-weighted benchmark 119, cohort averages 75/175, disparity 100, `EXCEEDS_THRESHOLD`, pool 53075, plus a GET re-read proving the benchmark is frozen.
   - `Corner/calculations/fair_lending_within_tolerance_publishes_without_remediation` — dropped the `PUBLISHED` status assert; kept benchmark 105, averages 100/110, disparity 10, `WITHIN_TOLERANCE`, pool 0, no hold, empty REMEDIATION ledger.

   This is a **PRD gap, not a test gap**: no test in the suite exercises review publication or closure, so §3.8's publication fork, the `ERR_RESERVE_BALANCE_NEGATIVE` pool guard, and the `CLOSED` compliance-hold release are unverified until the PRD names those action values.

One further per-assertion drop: `Corner/calculations/buyback_unpaid_principal_amortizes_straight_line_at_six_months` asserts `RetailContract.months_seasoned == 6`, but §3.7 describes the seasoning only as an input to the demand snapshot and never says the contract field is written — dropped that one line; the demand's 2520900 / 161058 / 25000 / 2706958 and the `HELD` reserve status are all asserted.

**Orchestrator verification:** 88 test functions across 9 files; `Design:` tag census = 38 Difficulty + 50 Corner = 88 (one per test). Cross-check on reconciliation #1: Step 6's implementation independently derived `BASE_REQUIRED_DOC_TYPES` from PRD §3.4 as the same three types (`core.py:61-65`), so the scaffold's unbound constant resolved consistently on both sides.

## Step 7: Run tests and iterate — 2026-08-30T12:22:15.106319646Z

Done. The task arrived already green and stayed green under stress.

**Iterations run:** 1 diagnostic sweep + 1 verifying sweep (plus one deliberate mutation round in between, see below).

**Result:** all 8 parallel rounds pass — `total=88, passed=88, failed=0, errors=0, skipped=0` in every round. The diagnostic protocol (STEPs 0–3) was never entered, because the union of failing tests across all 8 rounds was empty on the very first sweep.

**Tests deleted:** none. No test failed in any round, so no PRD-coverage or unique-derivability question was ever raised.

**Fixes applied to `test_helpers/`:** none required.

**Fixes applied to `implementation/`:** none required. The implementation is byte-identical to the state it arrived in (verified by `diff` against a pre-mutation snapshot).

### Guarding against a false green

A first-try 8/8 green is exactly what a vacuous or leak-tuned suite also looks like, so I verified the sweep is load-bearing before exiting:

- **No skips or escapes** — zero `skip`/`xfail` in `test_suite/` or `test_helpers/`; 88 `def test_` definitions match the 88 collected tests, so nothing is silently uncollected.
- **Storage is in-memory only** — `core.py` uses plain dicts; no sqlite, file I/O, `/tmp`, or pickle anywhere in `implementation/`, so `start.sh` re-invocation genuinely wipes state between tests.
- **Mutation test** — I perturbed three independent implementation constants in `workspace/implementation/core.py` (`PARTICIPATION_FACTOR` 55/100→56/100, `DISPARITY_THRESHOLD_BPS` 25→24, `AGREEMENT_NOTICE_BUFFER_DAYS` 30→29) and ran a full round: **20 of 88 tests went red**, spanning the reserve accrual, chargeback proration, buyback snapshot, termination cascade, and fair-lending benchmark/remediation families. The suite genuinely pins the money math. I then restored `core.py` byte-identically and re-ran the full 8-round sweep, which is the clean sweep reported above.

Note on the mutation: the notice-buffer change (30→29) was not detected — the two agreement-window tests use dates (`2027-02-01` touching, `2027-03-05` clear) that fall the same side of both a 29- and 30-day buffer. That is a gap in the fixture's chosen dates, not a fairness problem with any test, and no test failed on account of it.

### Deliverables

The 8 `results.{1..8}.json` files from the final clean sweep are in place at `workspace/implementation/`, all timestamped from the verifying run against the unmutated implementation. No stray `.bak`/`.orig`/analysis files were left in the task directory.

One incidental observation for triage records: the three generation-time concerns flagged in the prompt — the unnamed `PUBLISH`/`CLOSE` transition tokens, the independently-bound `BASE_REQUIRED_DOC_TYPES`, and the sheet-before-agreement selection order — all turned out consistent between the test suite and the implementation, so none of them surfaced as a failure.

**Orchestrator verification:** all 8 `results.{1..8}.json` present and independently re-parsed — each reports `total=88, passed=88, failed=0, errors=0, skipped=0`. `test_suite/` still holds 88 `def test_` functions (no silent deletions). No `.bak`/`.orig`/`.rej` files anywhere under the task directory.

## Step 8: Finalize PRD — SKIPPED — 2026-08-30T12:22:15.106319646Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the tests exercised, so there is no `<step_7_diff>` to patch against and no `PRD_FINALIZED.md` is produced. Step 9 therefore starts from `PRD.md` and is fully load-bearing for this task.

## Step 9: Complete PRD — 2026-08-30T12:29:32.484144670Z

Done. `PRD_COMPLETED.md` is written and verified.

### Verification
- **PRD.md**: 390 lines, 84,642 chars → **PRD_COMPLETED.md**: 390 lines, 89,789 chars (**+5,147 chars**, +0 lines — every edit is an in-paragraph insert/revision; each PRD paragraph is one line).
- All 5 top-level sections present (§1–§5, plus all 11 §2.x and 9 §3.x subsections); file ends on the complete error catalogue table.
- Diff touches exactly **24 lines**, carrying **26 pins** (§3.1 and §3.8 each have two edits landing in one paragraph). No new sections, no deleted prose.

### Counts
- **Ambiguity-pins (PRD silent): 23**
- **Mismatch-revisions (PRD said something else): 3** — §3.4 booking gate order, §2.8 `scorecard_stale` trigger breadth, §3.1 predecessor supersession precondition.

### Changes
- §2.1 — revise — ambiguity — header values are trimmed; whitespace-only is `ERR_UNAUTHENTICATED` — `core.py:322-330`
- §2.1 — insert — ambiguity — action-level role gate fires only for a *recognized* action token; missing/unknown `action` is `ERR_INVALID_REQUEST` after path resolution — `routes_dealers.py:86-95`, `routes_misc.py:92-102`
- §2.3 — revise — ambiguity — per-dealer scorecard listing ties broken by `created_at` ascending — `routes_dealers.py:186-187`
- §2.4 — insert — ambiguity — server-written instants use canonical 3-fractional-digit form; **client-supplied instants are echoed back verbatim** (`effective_from/to`, `contract_date`, `funding_date`, `event_date`, `period_*`, `window_*`, `settled_at`) — `core.py:169-181` (`stamp` vs `putdt`)
- §2.7 — insert — ambiguity — dealer-scope check precedes path resolution only where the dealership is named directly; otherwise it runs after the identifier resolves, so not-found wins over `ERR_DEALER_SCOPE_VIOLATION` — `routes_contracts.py:250-251`, `routes_misc.py:99-100`
- §2.8 — revise — mismatch — `scorecard_stale` is raised by a `CHARGEBACK` entry alone; `BUYBACK_OFFSET`/`REMEDIATION` move the balance without it — `routes_contracts.py:523-527`, `routes_misc.py:141-150`
- §2.11 — insert — ambiguity — system-posted entries carry `reason` == their own `entry_type`; only `MANUAL_ADJUSTMENT` takes it from the request — `routes_contracts.py:466-467`, `routes_misc.py:141`, `routes_misc.py:235`
- §3.1 — revise — ambiguity — successor's same-dealership + earlier-`effective_from` conditions are enforced at **drafting** time as `ERR_AGREEMENT_WINDOW_CONFLICT` — `routes_agreements.py:268-273`
- §3.1 — revise — mismatch — predecessor is superseded only when genuinely `ACTIVE` (otherwise untouched, countersignature still succeeds); truncated `effective_to` is rewritten canonically — `routes_agreements.py:341-344`
- §3.2 — insert — ambiguity — all eight tier fields required; duplicate `tier_code` → `ERR_INVALID_REQUEST` judged **before** the `DRAFT` gate; non-DRAFT sheet → `ERR_INVALID_STATE` — `routes_agreements.py:394-402`
- §3.3 — revise — ambiguity — `stipulation_count` is an integer ≥ 0 — `routes_applications.py:135`
- §3.4 — revise — mismatch — booking tests compliance hold **before** dealer ACTIVE — `routes_contracts.py:257-260`
- §3.4 — insert — ambiguity — `contract_apr_bps` has no independent range bound — `routes_contracts.py:247`
- §3.4 — insert — ambiguity — duplicate `doc_type` upload → `ERR_INVALID_REQUEST` — `routes_contracts.py:340-342`
- §3.4 — insert — ambiguity — `reserve_status` is written outright, so a portfolio event on a `HELD` contract still drives it to `CHARGED_BACK`/`EARNED` — `routes_contracts.py:521`
- §3.5 — insert — ambiguity — a `funding_date` earlier than `decisioned_at` is not a 30-day-window failure; only the `contract_date` floor bounds it below — `routes_contracts.py:442-445`
- §3.5 — insert — ambiguity — under `FLAT_FEE` there is no earned-to-date variant (basis months ignored, figure equals the accrued one); the 250,000-cent cap applies to the earned-to-date figure too — `services.py:215-228`, `routes_contracts.py:500`
- §3.6 — revise — ambiguity — the **contract's own** `months_seasoned` is set to the event seasoning — `routes_contracts.py:515`
- §3.7 — revise — ambiguity — `dispute_reason` is optional; a dispute without one writes null over any prior value — `routes_misc.py:103,119`
- §3.8 — insert — ambiguity — **the transition endpoint takes `action` ∈ {`PUBLISH`, `CLOSE`}**, anything else `ERR_INVALID_REQUEST` — `routes_misc.py:217`
- §3.8 — insert — ambiguity — the publication fork is on `finding` alone: a zero pool still enters `REMEDIATION_ORDERED`, still posts a zero-cent `REMEDIATION` entry, still raises the hold (`ERR_RESERVE_BALANCE_NEGATIVE` guard is `pool > reserve_balance_cents`) — `routes_misc.py:227-238`
- §3.8 — revise — ambiguity — closing from `REMEDIATION_ORDERED` advances `Dealer.version` whether or not the hold was actually cleared — `routes_misc.py:246-251`
- §3.9 — insert — ambiguity — both `REINSTATE` gates fail with `ERR_INVALID_STATE` — `routes_dealers.py:107-111`
- §3.9 — insert — ambiguity — `COMPLIANCE_HOLD`/`RELEASE_HOLD` have no state precondition (valid even on `TERMINATED`), are idempotent, and still bump `Dealer.version` — `routes_dealers.py:119-124`
- §3.9 — revise — ambiguity — termination link four skips contracts already carrying an `ISSUED`/`ACKNOWLEDGED`/`DISPUTED` demand; seasoning is measured to the current logical instant — `services.py:335-341`
- §4 — insert — ambiguity — auth precedes routing; an unmatched path or method answers `ERR_INVALID_REQUEST` (400), not a 404 code — `app.py:29-54`

**Both named items confirmed/addressed:** the transition endpoint's `action`/`PUBLISH`/`CLOSE` contract, the pool guard, and the `CLOSED` hold-release are now pinned; `BASE_REQUIRED_DOC_TYPES` (`core.py:61-65`) already matched §3.4's three base types and the `INCOME_VERIFICATION` stipulation rule (`routes_contracts.py:284-287`) — only the duplicate-upload error code was silent there.

**Orchestrator verification:** PRD.md 390 lines / 84,642 chars → PRD_COMPLETED.md 390 lines / 89,789 chars (+5,147). Diff = 48 changed lines total (24 removed + 24 added), matching the reported 24 touched lines. 28 headings present; file terminates on the complete §5 error table. Withhold audit over the agent's transcript: 16 tool_use calls scanned, 0 referenced any `SCAFFOLD*.yaml` or `worklog.md` — constraint held.
