# Worklog — task_3280_advertiser_account_policy_enforcement_auction_quality_scoring

## Step 1: Create task directory — 2026-09-30T16:45:23.756Z

Task directory was pre-allocated by the invoker: `./tasks/task_3280_advertiser_account_policy_enforcement_auction_quality_scoring/` with `workspace/` inside. Verified it exists; no new index computed and no other task_* directory created.

## Step 2: Generate scaffold — 2026-09-30T17:15:00.000Z

There's a stray `worklog.md` and `workspace/` dir in the task folder (not mine — likely created by the orchestrator). Leaving them untouched. All three required files are complete and lint-clean.

---

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3280_advertiser_account_policy_enforcement_auction_quality_scoring/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 plus `concurrency_rules` (§1.2.1); contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design` (§1.9)

**Lint verdict (verbatim):**
```
Coverage
  §1.5 endpoints declared:    39
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     35
  Calls scanned (§1.8+§1.9):  588

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(Note: the linter counts only non-stub §1.9 instances; total §1.9 entries are 44 = 35 non-stub + 9 stub.)

**Counts:**
- Entities: **12** (AdvertiserAccount, IdentityVerification, Appeal, BillingProfile, Campaign, AdGroup, Ad, Keyword, PolicyReview, AuctionEvent, DailySpendRecord, Invoice)
- State machines: **7** (AdvertiserAccount suspension/appeal branch, IdentityVerification, Appeal, Campaign with pause_origin, Ad review cycle, PolicyReview auto→human fork, Invoice payment lifecycle)
- Calculations: **7** (quality_score dual-variant, ad_rank_and_placement, actual_cpc pinned floor-then-increment-then-cap, daily_overdelivery_limit, monthly_spend_cap_and_credit provisional-vs-chronological, billing_threshold_charge ladder, invalid_click_credit)
- Validations: **11** (priority-ordered: auth → authz → existence → shape → OCC → state → safety → constraint → temporal → referential → fiscal)
- Endpoints: **39** (incl. `POST /_clock/set_current_utc` with mandated default 2026-09-01T00:00:00Z)
- Errors: **27**
- Roles: **5** (Anonymous, Advertiser entity-backed, PolicyReviewer/BillingAdmin/PlatformAdmin opaque)
- Concurrency (OCC) rules: **2**
- §1.8 difficulty instances: **18** (2 per rule × 9 rules; all with structured setup_api_calls, pre-computed literal asserts, placeholder closure)
- §1.9 corner instances: **44 total = 35 non-stub + 9 stub** (stubs cite covering §1.8 instances; all refs resolve)

**Difficulty highlights (per the "much harder than expert" directive):** dual-variant caps with mid-month budget-change divergence (60800 provisional vs 45600 final), CPC rounding-order trap (floor+1 = 199 vs naive 200), rank tie-break + bid cap + reserve gate in one auction, depth-3 cascades in both directions (policy violation down, appeal overturn up), half-open 30-day appeal window vs 14-day post-decision cooldown buffer, inclusive 2× daily overdelivery and billing-threshold boundaries, and two compensating invariants (account fiscal equation; campaign aggregate-vs-daily-parts reconciliation).

All design instances were self-audited: 62 unique instance names across both files, no dangling stub references, no forbidden concurrency vocabulary, and no sibling task directories were inspected.

Orchestrator verification: all three files exist and are non-empty (SCAFFOLD.yaml 775 lines / 59511 bytes; SCAFFOLD_DIFFICULTY_DESIGN.yaml 1572 lines / 82275 bytes; SCAFFOLD_CORNER_DESIGN.yaml 1718 lines / 85346 bytes).

## Step 3: Copy shared files — 2026-09-30T17:16:00.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-30T17:22:00.000Z

Generation complete. All three hard contracts pass.

**Output path:** `/home/ubuntu/github/CodingPRD/tasks/task_3280_advertiser_account_policy_enforcement_auction_quality_scoring/workspace/PRD.md`

**Line count:** 286 lines

**Section list:**
- `# Advertiser Policy Auction API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles`
  - 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim fixed block) · 2.3 Pagination · 2.4 Resource Identity and Common Properties · 2.5 The Logical Clock · 2.6 Lazy State Finalization · 2.7 Nested Resource Resolution · 2.8 Optimistic Concurrency Control · 2.9 Monetary Quantities, Precision, and Score Integers · 2.10 Validation Ordering · 2.11 Uniqueness and Conflict Rules · 2.12 Cascading State Propagation
- `## 3. Business Logic & Workflows`
  - 3.1 Account Onboarding and Identity Verification · 3.2 Suspension and the Appeal Lifecycle · 3.3 Campaigns, Budgets, and Flight Windows · 3.4 Ad Groups, Ads, and Policy Review · 3.5 Billing Profiles, Invoices, and the Monthly Close · 3.6 Quality Scoring and the Auction · 3.7 Click Pricing, Pacing, and Invalid-Traffic Remediation
- `## 4. Endpoint Definitions` (39-row table, 4 columns: Method / Path / Description / Authorized Role(s))
- `## 5. Error Code Catalogue` (27-row table, 2 columns)

**Self-audit results:**

```
Field coverage check (Contract 1):
- entities[].fields: 84 required, 84 present, 0 missing
- endpoints[].request_body: 37 required, 37 present, 0 missing
- endpoints[].query_params: 5 required, 5 present, 0 missing
Status: PASS (two passes run; first pass caught ad_group_id / automated_verdict / kind, repaired, second pass clean)

Rule coverage check (Contract 2):
- validations[] with priority: 11 checked, 11 expressed in §2.10 as an explicitly ordered cascade, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed in §2.8 (write operation + expected_campaign_version / expected_account_version + ERR_STALE_VERSION 412, no time-overlap framing), 0 missing
- state_machines[].transitions: 22 checked, 22 fully expressed (from/to, preconditions with error IDs, side effects incl. lazy SUSPENDED_FINAL/ENDED/OVERDUE, bubble-up resume, NO_ELIGIBLE_ADS cascade, voluntary-edit exemption), 0 missing
- calculations[]: 7 checked, 7 fully expressed in precise prose (quality score 50/30/20 weights, both variants; auction gates + 20000 reserve + tie-breaks; pinned floor → +1 cent → cap-at-bid CPC with 5-cent no-runner-up reserve; inclusive 2x daily pacing; 304/10 provisional vs. chronological final cap with single end floor; inclusive threshold ladder 50000→150000→300000→500000 with terminal repeat; invalid-click chronological unwind + oldest-unpaid-invoice credit routing), 0 missing
- validations[] conditions: 11 checked, 11 matchable to error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: all 39 endpoint side-effect entries and all multi-endpoint applies_to scopes expressed, 0 missing
- entities[].fields[] structured content: 84 checked, 84 reconstructible (defaults, nulls, enum spellings, ranges, ladder rungs), 0 missing
- sibling-branch symmetry: 6 groups checked (invoice payment transitions, appeal outcomes, policy-review outcomes, match types, cascade links, resume paths), 6 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only, Contract 3):
- backtick tokens scanned: 361
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Additional checklist results:** §2.2 verified byte-identical to the fixed source block; all 25 state values, 18 enum values, 5 role names, and 27 error IDs verified present; every error ID mentioned in §2/§3 prose with its trigger condition; no fuzzy/approximating wording detected; §4 table has exactly 4 columns; §5 table has exactly 2 columns; PRD.md ends at §5 with no audit footer. The two withheld design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, and no sibling task directories were accessed.

Orchestrator verification: `workspace/PRD.md` exists on disk, 286 lines / 46944 bytes.

## Step 5: Generate unit tests — 2026-09-30T17:38:00.000Z

All done. Every test has exactly one Design tag, no skips/xfails, everything compiles.

---

## Summary

**Files written under `test_helpers/` (9 files):**
- `/home/ubuntu/github/CodingPRD/tasks/task_3280_advertiser_account_policy_enforcement_auction_quality_scoring/test_helpers/__init__.py`
- `.../test_helpers/types.py` — 12 entity TypedDicts + 12 status/enum classes + `UserRole`
- `.../test_helpers/api_client.py` — `ApiClient(GenericApiClient)` with 31 endpoint methods covering all PRD endpoints
- `.../test_helpers/api_errors.py` — `ApiErrorId` enum (27 errors) + HTTP status map registered via `set_error_http_status_map`
- `.../test_helpers/assertions.py` — per-entity assertions + formula helpers (`quality_score_centi`, `actual_cpc_cents`, `provisional_monthly_cap_cents`) + fiscal/ledger invariant checkers
- `.../test_helpers/factories.py` — payload factories for all create/decide/pay/close payloads
- `.../test_helpers/constants.py` — THRESHOLDS (reserve 20000, reserve CPC 5, ladder, 304/10 factor, 100-cent floor, 30d/14d windows) + TEST_DEFAULTS
- `.../test_helpers/test_users.py` — TEST_USERS for 5 roles + `make_advertiser_headers(user_id)` entity-backed builder
- `.../test_helpers/fixtures.py` — composite fixtures: `set_clock`, `create_account`, `submit_identity_verification`, `approve/reject_verification`, `create_verified_account`, `create_billing_profile`, campaign state helpers, `create_ad_group`, `create_ad`, `create_eligible_general_ad`, `create_keyword`, `submit_ad_review`, `setup_auction_pair`, `setup_solo_auction_ad`, `run_clicked_auction`, `close_month`, `list_invoices`, refresh helpers, `suspend_account`, `file_appeal`, `decide_appeal`, `setup_suspended_account`

**Files written under `test_suite/` (13 files):**
- `conftest.py`, `test_01_baseline.py`, `test_02_envelope_rbac.py`, `test_03_verification_suspension.py`, `test_04_validations.py`, `test_05_occ.py`, `test_06_auction_quality.py`, `test_07_ad_review.py`, `test_08_suspension_appeals.py`, `test_09_priority_and_pending.py`, `test_10_pacing_billing.py`, `test_11_monthly_close_payments.py`, `test_12_invalid_click_invariants.py`

**Test counts:** 72 tests total.
- Queue A (§1.8 Difficulty): 18/18 instances covered with ≥2 tests each (one instance — `ad_rank_reserve_tiebreak_and_bid_cap` — has 3). Difficulty-tagged tests: 37.
- Queue B (§1.9 Corner): all 35 non-stub instances covered with exactly 1 test each. Corner-tagged tests: 35. The 9 `excluded_because:` stubs in the `errors` section were not translated; their `difficulty_instance` cross-references all resolve to real queue-A instances (verified during tag audit).

**Skipped instances:** none. Every non-stub instance in both queues passed the PRD-first two-condition filter (verbatim coverage + unique derivability).

**Notable adjudication:** for `Corner/calculations/monthly_overdelivery_credit_chronological_cap`, the design index's literal expected values (cap 1621, credit 1579) assume a 30-day divisor, but the recipe places the month in February 2027 (28 days) and the PRD pins "divide by ten times the number of days in the month." I kept the test but computed expectations directly from the PRD formula (`(28*100)*304 // (10*28)` = 3040, credit = 160) rather than copying the index's arithmetic, since the PRD is the contract and uniquely derives the outcome.

**Self-audit verdicts:**
- Stage 1: PASS — all helper modules compile (`py_compile` clean); Advertiser entity-backed identity threaded via `make_advertiser_headers(account_id)` in every ownership-gated fixture; no scaffold references in comments/docstrings.
- Stage 2: PASS — all 12 test modules compile; every test function's docstring ends with exactly one verbatim `Design:` tag resolving to a real instance (verified by grep: 72 tags, each queue-A instance ≥2, each non-stub queue-B instance =1, no untagged or dual-tagged tests); all citations quote verbatim PRD sentences with rule-bearing content; no `pytest.mark.skip`/`skipif`/`xfail` anywhere.

Orchestrator verification (spot-check against disk): test_helpers/ has all 9 modules; test_suite/ has conftest + 12 test modules; `grep -c "def test_"` totals exactly 72 tests; Design tag grep shows exactly 35 `Design: Corner/` and 37 `Design: Difficulty/`; 0 occurrences of pytest.mark.skip/xfail anywhere in test_suite/ or test_helpers/. Claims confirmed.

## Step 6: Generate implementation — 2026-09-30T17:47:00.000Z

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3280_advertiser_account_policy_enforcement_auction_quality_scoring/workspace/implementation/`):

- `core.py` — logical clock (default `2026-09-01T00:00:00Z`, no wall-clock fallback), in-memory `Store` for all 12 entities, error catalog with the 27 scaffold error IDs, success/error envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`), pagination (`limit`/`offset`, defaults 10/0, max 100), auth middleware (`X-User-ID` + `X-User-Role`, 5 roles), ownership check, `new_record` (UUID id, `created_at`/`updated_at`, `version=1`), query/text normalization.
- `services.py` — lazy state finalization (ENDED campaigns, OVERDUE invoices, SUSPENDED_FINAL accounts), quality-score formula (`50*ectr + 30*rel + 20*lp`), `eligible_ad_count` recompute, suspension and overturn cascades, `NO_ELIGIBLE_ADS` auto-pause / bubble-up resume, snapshot freeze on approval, billing helpers (threshold invoice issuance with pending-credit application, ladder escalation), keyword match rules (EXACT/PHRASE/BROAD), serializers that recompute derived fields (`lifetime_billed_cents`, `outstanding_balance_cents`, `monthly_cap_provisional_cents = budget*304//10`, `current_month_served_cents`).
- `routes_accounts.py` — clock set, account register/get/suspend, verification submit (with `expected_account_version` OCC, supersedes, pending-window conflict) / list / decide, appeal file (window half-open, cooldown, open-appeal conflict, auto-intake to UNDER_REVIEW) / list / decide (UPHELD → SUSPENDED, 2nd UPHELD → SUSPENDED_FINAL; OVERTURNED → resume cascade).
- `routes_billing.py` — billing profile create (uniqueness), get (array via account, single via id), invoice list (lazy OVERDUE), payment (overpayment/INVOICE_NOT_PAYABLE, threshold ladder escalation on full THRESHOLD payment), close-month (month fully past + strictly after last_closed, chronological per-day budget from history, single final floor `sum*304//(10*D)`, overdelivery credit to campaign + account, MONTHLY invoice with pending credits applied first).
- `routes_campaigns.py` — campaign CRUD (budget/date fiscal checks, `expected_campaign_version` OCC, budget history tracking for close-month), activate/pause with window + account-state gates in priority order (window error before account-state error), daily-spend list, ad-group create/list/get.
- `routes_ads.py` — ad create (restricted-category certification gate, case-insensitive headline uniqueness, score ranges), get/list, PUT edit (headline/url change → DRAFT + immediate count recompute without auto-pause; quality-score edits keep eligibility), submit-review (round++, CLEAN→AUTO_APPROVED→ELIGIBLE, FLAGGED_RESTRICTED→NEEDS_HUMAN), policy-review decide (HUMAN_APPROVED certification gate / HUMAN_VIOLATION cascade), list reviews and per-ad auction events, keyword create (negative-keyword shape rules, duplicate rule, both directions of negative-keyword conflict against canonical queries) and list with `is_negative` filter.
- `routes_auctions.py` — auction simulation (eligibility gates incl. lazy ENDED evaluation, negative block, bid = max matching keyword `max_cpc_cents` tie-broken by earliest `created_at`, rank = bid × live quality centi, reserve 20000, winner tie-break by ad `created_at`, pinned 3-step actual CPC `floor(runner_up/quality)+1` capped at bid, no-runner-up `min(bid,5)`, inclusive `2×daily_budget` pacing — over-limit records event with no-charge then 422), auction-event get with Advertiser ownership, flag-invalid (ERR_AUCTION_NOT_CLICKED/ERR_CLICK_ALREADY_INVALID, unwinds day/campaign/account accumulators, unbilled vs invoiced paths — invoiced applies to oldest unpaid invoice capped at `amount-paid`, remainder to `pending_credit_cents`).
- `app.py` — Flask app, blueprint registration, `ApiError` handler, generic 404/400 handlers, runs on `0.0.0.0:$PORT` (default 10000).
- `requirements.txt` — `flask>=3.0`.
- `start.sh` — bash, `set -euo pipefail`, cds to script dir, guards pip install with `python3 -c "import flask"`, then `exec python3 app.py` in the foreground.

**Endpoint count:** all 39 endpoints from the scaffold endpoint table are implemented (clock, 9 account/verification/appeal, 6 billing, 8 campaign/ad-group, 11 ad/review/keyword, 4 auction/invoice-payment — total matches 39).

**start.sh contract:** reads `$PORT` (default 10000), binds `0.0.0.0` via Flask's `app.run(host="0.0.0.0", port=...)`, runs in the foreground via `exec`, installs deps only when Flask is not already importable so per-test reboots are fast.

**Smoke test result:** server booted cleanly on port 19876. Verified: account registration (201, `PENDING_VERIFICATION`, counters 0), clock set (`current_utc` echoed), verification submit (OCC accepted at version 1) → approve → account ACTIVE with `verified_business_name` and `disclosure_text="Ads by B Inc"`, full campaign → ad group → GENERAL ad → submit-review (auto-approved to ELIGIBLE) → EXACT keyword → auction with `clicked=true` returned winner with `winner_ad_rank=400000` (bid 500 × quality 800), `runner_up_ad_rank=null`, `charged_cents=5` (min(bid=500, reserve=5)). Server PID was saved and killed after the test.

No entities are seeded at startup; the store starts empty on every boot.

Orchestrator verification (spot-check against disk): all 9 files + executable start.sh present; route decorators use `@bp.<method>()` shorthand — grep counts exactly **39** route decorators across routes_*.py with 0 duplicate paths; start.sh reads $PORT, binds via app.py on 0.0.0.0, execs in foreground, guarded pip install. Claims confirmed.

## Step 7: Test-fix iteration loop — 2026-09-30T18:08:00.000Z

All 8 rounds pass 70/70. Clean sweep.

## Summary

**Iterations run:** 3 sweeps (sweep 1: 6 deterministic failures in all 8 rounds; sweep 2: 6 fixed but surfaced a flaky tie-break failure in 4/8 rounds; sweep 3: 8/8 rounds clean, 70/70 each).

**Tests deleted (2):**
- `test_occ_verification_supersede_stale_version_returns_412` (test_05_occ.py) — unique-derivability collapse. The test's hinge was "decide REJECTED advances the account's version", but PRD §3.1 describes rejection as mutating only the verification record ("the account remains PENDING_VERIFICATION") with no account-field write, while the PRD explicitly names the account version bump for approval, suspension, and appeal filing. Two faithful PRD-only readers diverge; the scaffold's own endpoint table lists only "REJECTED: sets rejection_reason" as the side effect. The PRD-covered remainder (`supersedes_id` set on resubmission) is already asserted by `test_submission_after_rejection_allowed` in test_09.
- `test_ended_campaign_put_reports_invalid_state_not_fiscal` (test_09_priority_and_pending.py) — unique-derivability collapse. The test presumed PUT on an ENDED campaign is a priority-6 transition-legality violation, but the PRD's campaign-update prose (§2.8/§3.3) names no from-state gate for updates, and `ERR_INVALID_STATE` is only ever tied in the PRD to decide/pause/activate transitions. A faithful reader may apply the fiscal check and return `ERR_BUDGET_BELOW_MINIMUM`. Driven by scaffold design instance `state_error_beats_fiscal_error_on_ended_campaign_put`.

**Fixes applied to `test_helpers/`:**
- `fixtures.py` — `setup_auction_pair` gained `start_date`/`end_date` kwargs forwarded to `create_and_activate_campaign`; the default flight window (2026-09-01..2026-12-31) made the February-2027 scenario in `test_monthly_overdelivery_credit_chronological_cap` fail activation with 409.

**Fixes applied to `test_suite/`:**
- `test_11_monthly_close_payments.py` — the overdelivery test now passes `start_date="2027-02-01", end_date="2027-02-28"` so the flight window covers the logical clock it sets (PRD-faithful: activation requires the logical date inside the window).

**Fixes applied to `implementation/`:**
- `core.py` — `new_record`/`touch` now stamp `created_at`/`updated_at` from the logical clock (new `entity_ts()`, 3 fractional digits) instead of wall-clock `req_ts()`; PRD §2.5: "Time in this platform never comes from the wall clock."
- `core.py` — added a monotonic `_seq` counter on every record (never serialized; serializers whitelist `PUBLIC_FIELDS`) so PRD's "earliest creation" tie-breaks stay deterministic when records share one logical-clock instant.
- `routes_auctions.py` — keyword bid tie-break, winner ad-rank tie-break, and oldest-unpaid-invoice selection now order by `(created_at, _seq, id)`.
- `routes_accounts.py` — appeal filing reordered: lazy SUSPENDED_FINAL evaluation → `ERR_APPEAL_ALREADY_OPEN` (reachable, since an open appeal means APPEAL_PENDING) → `ERR_APPEAL_WINDOW_CLOSED` (PRD requires this error even when lazy evaluation already finalized the account) → state gate → cooldown. Also `_seq` tiebreaks for supersedes target and UPHELD-appeal selection.
- `routes_ads.py`, `routes_billing.py`, `routes_campaigns.py`, `routes_accounts.py` — list-endpoint sorts gained `_seq` between `created_at` and `id` so pagination order matches creation order under a fixed logical clock.

Orchestrator verification (against disk): all 8 `results.{1..8}.json` files exist, all show passed=70 failed=0 total=70 errors=0; results mtimes (18:07) are newer than every implementation source file (latest 18:04:53), so no post-sweep edits occurred; test count on disk is exactly 70 (72 − 2 deletions) with 0 skip/xfail markers. Clean sweep independently confirmed.

## Step 8: Finalize PRD — 2026-09-30T18:12:00.000Z

The diff is minimal and scoped. Done — PRD_FINALIZED.md written.

## Summary

**Line counts:** PRD.md 286 lines, PRD_FINALIZED.md 286 lines (0% line-count delta; 4 lines revised inline, no sections added or removed).

**Changes (one bullet each):**
- **§2.4** — revise — pinned that entity `created_at`/`updated_at` stamps come from the logical clock (never wall clock) and that all timestamp-based ordering/selection (list ordering, "created earliest" ties, oldest-unpaid-invoice, supersede target, latest UPHELD appeal) resolves records sharing one logical instant by actual persistence sequence — `implementation/core.py:230-255` (`entity_ts`, `new_record._seq`, `touch`); consumers at `routes_auctions.py:70,82,203`, `routes_accounts.py:145,247`, all list sorts in `routes_ads.py`/`routes_billing.py`/`routes_campaigns.py`.
- **§2.10 item 9** — revise — added a cross-reference that appeal filing pins its own check order (per §3.2), resolving the tension with the generic tier-6-before-tier-9 cascade — `implementation/routes_accounts.py:225-251`.
- **§3.1** — revise — `supersedes_id` now described as pointing at the account's *most recent* `REJECTED` verification — `implementation/routes_accounts.py:141-146`.
- **§3.2** — revise — pinned the appeal-filing check order (lazy SUSPENDED_FINAL eval → `ERR_APPEAL_ALREADY_OPEN` → `ERR_APPEAL_WINDOW_CLOSED`, reported even when lazy eval already finalized the account → SUSPENDED state gate → cooldown against the most recently decided UPHELD appeal) — `implementation/routes_accounts.py:225-251`.

**No edits for:** the two deleted tests (unique-derivability collapses — PRD legitimately admits both readings; pinning forbidden), the fixture/test-suite fixes (pure test bugs, impl untouched), and rejection-not-bumping-account-version (PRD already implies it; deletion accepts the looseness).

**Per-edit pre-edit search log:**
1. **§2.4 timestamp/ordering edit.** (a) Subject: source of entity `created_at`/`updated_at` and semantics of timestamp-based ordering. (b) Enumerated paths: `core.py` `new_record`/`touch`/`entity_ts` (sole writers of entity stamps); `req_ts()` (envelope meta timestamp — wall clock, deliberately excluded from wording scope); `suspended_at`/`decided_at`/`occurred_date` (already logical-clock per existing PRD prose); all eight list sorts (`routes_ads.py:108,209,221,346`, `routes_billing.py:88`, `routes_campaigns.py:94,201,228`, `routes_accounts.py:171,278`); keyword-bid tie (`routes_auctions.py:70`), winner-rank tie (`routes_auctions.py:82`), oldest-unpaid-invoice (`routes_auctions.py:203`), supersedes target (`routes_accounts.py:145` — picks *latest* REJECTED), UPHELD selection (`routes_accounts.py:247` — sorts by `decided_at`, picks latest). (c) Wording adjusted twice: first draft said "ordered by `created_at`/created earliest/oldest", which mis-described the two latest-record selections and the `decided_at` sort; final wording is direction-neutral ("orders or selects records by timestamp") and enumerates all five selection kinds.
2. **§2.10 item 9 cross-reference.** (a) Subject: error-priority cascade vs. appeal-filing check order. (b) Enumerated: `routes_accounts.py:file_appeal` (only filing path); other tier-6-vs-tier-9 endpoints — campaign update (`routes_campaigns.py` PUT: OCC then fiscal checks, no state gate — consistent with the deleted-test looseness), activate/pause (state gate genuinely precedes window gates there, matching §3.3's explicit "priority order of §2.10"). (c) Wording scoped as a pointer ("as specified in §3.2") rather than re-listing rules, so it cannot contradict other endpoints' orderings.
3. **§3.1 supersedes target.** (a) Subject: which REJECTED verification `supersedes_id` references. (b) Enumerated: `routes_accounts.py:141-146` (sorts REJECTED by `(created_at, _seq)`, takes last = most recent); `test_09`'s `test_submission_after_rejection_allowed` asserts this behavior and survived Step 7. (c) "the previous REJECTED verification" → "the account's most recent REJECTED verification"; no other path reads `supersedes_id`, so no wider impact.
4. **§3.2 appeal-filing order.** (a) Subject: ordering and reachability of `ERR_APPEAL_ALREADY_OPEN`, `ERR_APPEAL_WINDOW_CLOSED`, `ERR_INVALID_STATE`, `ERR_APPEAL_COOLDOWN`, and lazy SUSPENDED_FINAL on filing. (b) Enumerated: `routes_accounts.py:213-266` in full; §2.6 (already states lazy eval runs on every appeal creation attempt — consistent); `decide_appeal` (`routes_accounts.py:283-319`) untouched by the wording since it acts on `UNDER_REVIEW` appeals only; §2.11 ALREADY_OPEN definition (SUBMITTED/UNDER_REVIEW) matches the impl's filter. (c) Cooldown wording changed from "that decision's `decided_at`" to "the most recently decided such appeal's `decided_at`" to match `routes_accounts.py:247-249`; ordering pinned exactly as impl executes, preserving the existing sentence that `ERR_APPEAL_WINDOW_CLOSED` surfaces even after lazy finalization.

Orchestrator verification (against disk): PRD_FINALIZED.md exists at 286 lines, diff vs PRD.md is exactly 8 changed diff-lines (4 lines revised inline) matching the four reported edits; no sections added or removed. Claims confirmed.

## Step 9: Complete PRD — 2026-09-30T18:22:00.000Z

Done. PRD_COMPLETED.md produced at `/home/ubuntu/github/CodingPRD/tasks/task_3280_advertiser_account_policy_enforcement_auction_quality_scoring/workspace/PRD_COMPLETED.md` (286 lines both files; 48,037 → 51,930 chars, +3,893 delta; 18 changed paragraphs, all inline insert/revise edits — no new sections).

**Counts:** 17 ambiguity-pins (insert), 1 mismatch-revision (revise).

**Changes (section — insert|revise — ambiguity|mismatch — what — impl ref):**

- §2.2 — insert — ambiguity — `api_request_id` pinned as `req_` + 20 random alphanumerics — core.py:68-69
- §2.2 — insert — ambiguity — `api_request_timestamp` pinned as wall-clock (the one non-logical timestamp) — core.py:63-65
- §2.3 — insert — ambiguity — non-integer `limit`/`offset`, out-of-range limit, negative offset → `ERR_VALIDATION` — core.py:144-158
- §3.1 — insert — ambiguity — approval increments account `version`; rejection leaves account untouched — routes_accounts.py:193-205
- §3.1 — insert — ambiguity — verification submit responds 201 with the verification record; decide responds 200 with the verification — routes_accounts.py:159,206
- §3.2 — insert — ambiguity — appeal automatic intake increments appeal `version` to 2 — routes_accounts.py:263-265
- §3.2 — insert — ambiguity — appeal file/decide respond with the appeal record — routes_accounts.py:266,319
- §3.2 — insert — ambiguity — appeal decision increments account `version` (both outcomes) — routes_accounts.py:307,318
- §3.2 — insert — ambiguity — overturn-resume cascade only revives campaigns still `PAUSED` (a lazily `ENDED` campaign is not resurrected) — services.py:158-166
- §3.3 — insert — ambiguity — update date-range check compares effective end date against the campaign's immutable `start_date` — routes_campaigns.py:131-133
- §3.3 — insert — ambiguity — lapsed flight window: lazy `ENDED` fires on access, so activate reports `ERR_INVALID_STATE` (409) before the 422 gates — routes_campaigns.py:169-171
- §3.4 — revise — mismatch — review decision state lives in `outcome`, born `AUTO_APPROVED`/`NEEDS_HUMAN` at creation; removed the never-observable `PENDING_AUTO` — routes_ads.py:186-193
- §3.4 — insert — ambiguity — voluntary content edit of an `ELIGIBLE` ad recomputes count and touches (version-bumps) the campaign — routes_ads.py:159-169
- §3.4 — insert — ambiguity — `is_negative` list filter accepts case-insensitive "true"/"false"; other values leave list unfiltered — routes_ads.py:340-345
- §3.5 — insert — ambiguity — close-month has no account-state gate (settles DRAFT campaigns and non-ACTIVE accounts), malformed `month` is `ERR_VALIDATION`, per-day cap uses creation budget for pre-existence days, `unbilled_cost_cents` resets even when no invoice issues, response shape `{"closed_month","invoice_id","total_overdelivery_credit_cents"}` (200), pre-creation months closable when `last_closed_month` is null — routes_billing.py:124-197
- §3.5 — insert — ambiguity — at issuance, `overdelivery_credit_cents` carries month-close credit and `invalid_click_credit_cents` carries pending credit applied; latter also grows on remediation — services.py:180-205
- §3.6 — insert — ambiguity — auction eligibility runs lazy `SUSPENDED_FINAL` on the account; simulation responds 201 with the event — routes_auctions.py:54,142
- §3.6 — insert — ambiguity — a click simulated already-invalid is never charged (`charged_cents` 0, no pipeline) — routes_auctions.py:133-139
- §3.7 — insert — ambiguity — overdelivery-rejected event is persisted (retrievable via event reads) with clicked=false/charged=0, treated as already invoiced — routes_auctions.py:99-121
- §3.7 — insert — ambiguity — invalid-click invoice credit: "unpaid" = ISSUED/PARTIALLY_PAID/OVERDUE (never PAID); applied amount capped at `amount_cents - paid_cents` — routes_auctions.py:199-215

One deliberate non-pin: `lifetime_billed_cents`/`outstanding_balance_cents` being derived at serialization time (vs stored) is an internal detail with identical observable values, so the PRD prose was left as-is.

Orchestrator verification (against disk): PRD_COMPLETED.md exists, 286 lines / 51,930 chars vs PRD_FINALIZED.md 286 lines / 48,037 chars (+3,893 delta, matches report). Confirmed NO post-sweep writes to implementation/ (all .py mtimes ≤ 18:04:53, final sweep ran 18:07) and no post-sweep writes to test_suite//test_helpers/ (mtimes ≤ 18:00:19) by Steps 8/9 — the clean 8-round sweep remains valid and does not need re-running.
