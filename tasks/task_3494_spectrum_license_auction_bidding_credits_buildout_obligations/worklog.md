## Step 1: Create task directory — 2026-10-02T17:07:36.295858085Z

Pre-allocated task directory verified/created: tasks/task_3494_spectrum_license_auction_bidding_credits_buildout_obligations/ with workspace/ inside. Index computation skipped per user instruction (directory pre-allocated as task_3494).

## Step 2: Scaffold generation — 2026-10-02

Generated SCAFFOLD.yaml (13 entities, 49 endpoints, 11 state machines, 11 calculations, 10 validation priority tiers, 42 errors, 4 roles, 2 OCC rules), SCAFFOLD_DIFFICULTY_DESIGN.yaml (9 rules / 19 instances), SCAFFOLD_CORNER_DESIGN.yaml (78 instances: 62 full + 16 excluded-because stubs). scaffold_lint.py: VERDICT clean (1398 calls scanned, all FKs reverse-reachable). Logical clock default 2026-09-01T00:00:00Z; api_prefix /spectrum-auctions; all 26 named constants pinned in calculations[].constants. Archetype: quota/allocation + compliance/audit; flat topology; segregation_of_duties (AuctionAdmin vs TransferReviewer).

## Step 2: Generate scaffold (subagent) — 2026-10-02T18:32:45.843724365Z

Scaffold generation complete. All three artifacts are written, parse cleanly, and pass `scaffold_lint.py` with a clean verdict (1398 recipe calls scanned, all FKs reverse-reachable, zero violations).

## Artifacts
- `/home/ubuntu/github/CodingPRD/tasks/task_3494_spectrum_license_auction_bidding_credits_buildout_obligations/SCAFFOLD.yaml` (1531 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_3494_spectrum_license_auction_bidding_credits_buildout_obligations/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1581 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_3494_spectrum_license_auction_bidding_credits_buildout_obligations/SCAFFOLD_CORNER_DESIGN.yaml` (2761 lines)

## Required summary
- **Entity count**: 13 — BandPlan, LicenseArea, LicenseBlock, Auction, Applicant (ownership disclosure embedded as array field), ClockRound, Bid, AssignmentBid, License, BuildoutMilestone, TransferApplication, Incumbent, RenewalApplication
- **Endpoint count (exact)**: 49 (48 business under prefix + 1 test-driving clock endpoint outside it)
- **State machine count**: 11 (six non-linear: Auction pause/postpone cycles, Applicant correction loop, BuildoutMilestone refile loop, TransferApplication info-request loop, License renewal cycle, Incumbent dispute cycle)
- **Calculation count**: 11 (bidding_eligibility, credit_tier_assignment, product_units_and_opening_price, clock_price_increment, activity_requirement, settlement_pricing [dual-variant], unjust_enrichment_repayment, buildout_coverage_check, relocation_cost_shares [dual-variant], assignment_ranking, license_lifecycle_windows)
- **Validation count**: 10 ordered priority tiers (auth → authz → existence → ownership → state → safety/anti-collusion → constraint → temporal → referential → fiscal)
- **Error catalog size**: 42 — all referenced by at least one design instance (script-verified)
- **Role count**: 4 — AuctionAdmin (opaque), Bidder (entity_backed:Applicant), IncumbentOperator (entity_backed:Incumbent), TransferReviewer (opaque); segregation_of_duties between auction operation and transfer/renewal adjudication
- **§1.8 difficulty design**: 19 instances total, 19 non-stub, 0 stub — dual_variant_calc 2, combinatorial_formula 3 (modes a/b/c all exercised), non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 2, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2
- **§1.9 corner design**: 78 instances total, 62 non-stub, 16 stub — entities 9+0, state_machines 12+3, calculations 5+4, validations 4+0, errors 22+6, rbac 6+0, cross_cutting_complexity_layers 3+3, consistency_model 1+0
- **api_prefix**: `/spectrum-auctions` (clock endpoint unprefixed at `/_clock/set_current_utc`)
- **Logical-clock start**: `2026-09-01T00:00:00Z` (pinned in the clock endpoint description; all fixture dates are clock-reachable — spot-checked date math with python: grant 2026-10-01, unjust-enrichment boundary days 1824/1825 = 2031-09-29/30, renewal window [2035-09-29, 2036-09-28])
- **Named constants (all pinned with values)**: UPFRONT_CENTS_PER_ELIGIBILITY_UNIT=2500; ATTRIBUTABLE_STAKE_PCT=25 (strictly-greater); SMALL_BIZ_TIER1_MAX_REVENUE_CENTS=400000000/35%, TIER2=2000000000/25%, TIER3=5500000000/15%; RURAL_SERVICE_POPULATION_CAP=250000, RURAL_CREDIT_PCT=15; CLOCK_INCREMENT tiers 3/2→15%, 6/5→10%, 1/1→5% (integer cross-multiplication); STAGE1_ACTIVITY_MILLI=800, STAGE2_ACTIVITY_MILLI=950; STAGE2_START_ROUND=4; INTERIM_MILESTONE_DAYS=1095/40%, FINAL_MILESTONE_DAYS=2190/70%, INTERIM_MISS_ACCELERATION_DAYS=365; UNJUST_ENRICHMENT schedule 100/80/60/40/20 over 5×365-day years; PAYMENT_DEADLINE_DAYS=30; LICENSE_TERM_DAYS=3650; RENEWAL_WINDOW_DAYS=365; RENEWAL_EXTENSION_DAYS=3650; INCUMBENT_TRANSITION_BUFFER_DAYS=30

## Key design decisions (harder-than-expert levers)
- Two genuine dual-variant calculations on different entity domains (License provisional-vs-final settlement basis; Incumbent proportional-vs-equal relocation shares with a pinned floor + largest-remainder rule, remainder cents distributed by units DESC then created_at ASC — never id).
- All three combinatorial modes: tiered per-product price increments (a), pinned round-per-license-then-sum proceeds where the two orders differ by exactly 1 cent on the fixture (b), and the activity/eligibility circular dependency with an explicit three-step evaluation order (c).
- Two depth-3 cascades from different triggers: clock-sweep FINAL-milestone MISS → license TERMINATED → pending transfers DENIED + supply restored; and DISQUALIFY → open-round bids VOIDED → live round-demand recompute (+forfeiture to the auction ledger).
- Two compensating invariants over different quantities (per-applicant upfront money `paid == held + refunded + forfeited`; per-product block supply `non-terminal licenses + available == supply_per_area`).
- Two temporal-overlap rules with deliberately different interval semantics (half-open lease windows on License — adjacency allowed; closed intervals + mandatory 30-day buffer for incumbent relocation windows per LicenseArea).
- Two OCC rules (Applicant disclosure, BuildoutMilestone filing), both exercised by stale-version tests using `${var} - 1` expressions.
- Replay fixes applied during authoring: incumbent gate relaxed to allow RELOCATING (otherwise relocation shares could never post — deadlock); renewal fixtures accept both buildout milestones before deep-future clock jumps (otherwise the milestone sweep terminates the license mid-recipe); milestone refile chain re-captures the version after REJECT (review bumps version); milestone list ordering pinned INTERIM-before-FINAL for same-instant creations.

Orchestrator verification (independent of hand-back): all three YAMLs parse via yaml.safe_load; SCAFFOLD.yaml endpoints=49, api_prefix=/spectrum-auctions; difficulty instances measured 19/19 non-stub; corner instances measured 78 total = 62 with test_recipe (non-stub) + 16 with excluded_because (stub) — matches hand-back; foreign-domain token scan (restaurant|hotel|ecommerce|hospital|grocery|deli|retail store) returned 0 hits across all three files; domain tokens (spectrum|auction|licens) 370 hits in SCAFFOLD.yaml.

## Step 3: Copy shared files — 2026-10-02T18:33:01.899646078Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md (53 lines) to workspace/INSTRUCTION.md.

## Step 4: Generate PRD (subagent) — 2026-10-02T19:02:05.666623353Z

All checks pass. The PRD is complete and verified.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3494_spectrum_license_auction_bidding_credits_buildout_obligations/workspace/PRD.md` — 320 lines (~59 KB; long prose lines), tail verified complete (ends on the final error-table row, no truncation).

**Sections:** §1 Introduction (2 paragraphs); §2 Global Specifications — 2.1 RBAC, 2.2 API Response Structure (verbatim block), 2.3 Pagination, 2.4 The Logical Clock and Its Maintenance Sweeps, 2.5 Resource Identity/Common Fields/Timestamp Rendering, 2.6 Money/Units/Arithmetic Discipline, 2.7 Validation Order and Error Precedence (10 tiers), 2.8 Optimistic Concurrency Control, 2.9 Flat Topology/Retrieval/Filters; §3 Business Logic in 9 subsections (band planning+incumbents → auction setup/upfront ledger → qualification/credits → quiet period/clock start → clock rounds → assignment phase/settlement pricing → settlement/clearing/grant → buildout milestones → transfers/leases/renewal/termination); §4 Endpoint Definitions (49 rows, 4 columns); §5 Error Code Catalogue (42 rows, 2 columns).

**Constants — all grep-verified present with values in full sentences:** 2500 cents/eligibility unit (floor division), ATTRIBUTABLE_STAKE_PCT strictly-greater-25 (exactly 25 not attributable), small-biz tiers 400000000→35% / 2000000000→25% / 5500000000→15% (inclusive boundaries), rural cap 250000→15%, clock increments 15%/10%/5% via integer cross-multiplication (2d≥3s, 5d≥6s, d≥s, inclusive lower side), STAGE1 800 milli / STAGE2 950 milli / stage 2 from round 4, milestones 1095d/40% + 2190d/70% + 365-day acceleration, unjust enrichment 100/80/60/40/20 over five 365-day years with the 1824-vs-1825 boundary stated, payment deadline 30 days, term 3650 days, renewal window 365 days, renewal extension 3650 days, incumbent buffer 30 days.

**Clock sentence:** present verbatim — "`POST /_clock/set_current_utc`, restricted to `AuctionAdmin`… intentionally lives outside the `/spectrum-auctions` prefix", with the startup default `2026-09-01T00:00:00Z` and never-falls-back-to-wall-clock stated. Timestamp two-family rule stated in §2.5 (3 fractional digits only for `api_request_timestamp`/`created_at`/`updated_at`; domain datetimes render exactly as the clock reads). Dashed-UUID id format stated.

**Hard contracts:** Contract 1 — 97 required field/input/query identifiers, 0 missing (mechanical check, fenced blocks stripped). Contract 2 — all 10 validation tiers with first-failure ordering, both OCC rules (endpoint + `expected_applicant_version`/`expected_milestone_version` + `ERR_STALE_VERSION`/412), all 11 state machines' transitions/preconditions/side-effects, all 11 calculations (incl. pinned rounding order and both price/share variants), all cascades (disqualify 2-hop, payment-lapse 2-hop, FINAL-miss, renewal-deny), all defaults and nullability, all applies_to scopes, sibling branches at equal density: PASS. Contract 3 — 527 §3 backtick tokens, 0 path/method violations: PASS.

**Ambiguities resolved in prose (flagged for downstream adjudication):** (1) the incumbent-clearance gate was written as biting on the *completing* settlement payment, per its position as a transition precondition on PENDING_PAYMENT→ACTIVE; (2) assignment-bid filing outside `ASSIGNMENT_PHASE` was pinned to `ERR_AUCTION_INVALID_STATE` (scaffold names the phase gate but no error); (3) disclosure updates against an applicant in a non-SUBMITTED/NEEDS_CORRECTION status were pinned to `ERR_APPLICANT_INVALID_STATE`; (4) OCC rejection was described as occurring "before any mutation is applied" without slotting it into the ten tiers, since the scaffold's §1.2.1 also treats OCC separately; (5) the `assignment_bid_cents` "(0 if none)" scaffold note is unreachable (completion requires every winner's bid), so it was written as the winner's amount; (6) opening a round while the previous round is not CLOSED is stated as a requirement with no error pinned (scaffold pins none).

The two forbidden design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.

Orchestrator verification (independent): PRD.md 320 lines / 59,645 bytes; tail = final error-table rows (not truncated); all 14 constant tokens grep-present; clock endpoint unprefixed (2 hits); logical-clock start 2026-09-01 present; §4 table has 51 `|`-rows (49 data + header/separator); 44 unique backticked paths (multi-method paths share rows).

## Step 5a: Generate test helpers (subagent, Stage 1 of 2) — 2026-10-02T19:25:05.645749014Z

Stage 1 is complete. All ten files written, compiled, and import-verified; no test files exist; no server was started.

## File list (all under `/home/ubuntu/github/CodingPRD/tasks/task_3494_spectrum_license_auction_bidding_credits_buildout_obligations/`)

| File | Lines | Contents |
|---|---|---|
| `test_helpers/types.py` | 401 | 12 status enums, 6 action enums, `UserRole`, `BlockCategory`, 13 entity TypedDicts (all carry id/created_at/updated_at/version; nullable domain fields `Optional`) |
| `test_helpers/constants.py` | 325 | All pinned PRD values + pure expected-value calculators |
| `test_helpers/api_errors.py` | 109 | `ApiErrorId` (42 ids) + `HTTP_STATUS_CODES`, registered via `set_error_http_status_map` |
| `test_helpers/api_client.py` | 320 | `ApiClient(GenericApiClient)` — 49 endpoint methods; `api_client` singleton |
| `test_helpers/factories.py` | 215 | 14 payload factories + canonical product spec tables + canonical upfront amounts |
| `test_helpers/test_users.py` | 55 | `TEST_USERS` (4 roles) + 4 header builders |
| `test_helpers/assertions.py` | 329 | 13 `assert_<entity>` + 2 timestamp-family validators + 4 invariant checkers + 3 entry finders |
| `test_helpers/fixtures.py` | 773 | 70 composite setup helpers |
| `test_helpers/__init__.py` | 39 | Barrel export (framework + PRD-specific) |
| `test_suite/conftest.py` | 47 | `api` (session) + 4 role-header fixtures |

## Frozen helper API for Stage 2

**Client**: `api_client.<method>` — 49 methods matching the PRD endpoint table exactly; `set_clock(to_iso8601, headers)` posts to the **unprefixed** `/_clock/set_current_utc` (verified by source inspection); all 48 business methods use `API_PREFIX="/spectrum-auctions"`. Creates return raw responses — callers pass `expected_status=201` to `validate_success`.

**Header builders**: `make_bidder_headers(applicant_id)`, `make_incumbent_operator_headers(incumbent_id)` (entity-backed — mandatory on ownership-gated calls), `make_auction_admin_headers()`, `make_transfer_reviewer_headers()` (opaque). `TEST_USERS["bidder_headers"]` is bootstrap-only (self-registration).

**Factories**: `create_{band_plan,license_area,license_block,auction,applicant,bid,assignment_bid,settlement_payment,file_notice,transfer_application,transfer_review,incumbent,incumbent_transition,disclosure_patch,resubmit}_payload(...)`, `sole_owner_interests()`; `CANONICAL_AREAS` (PEA001 pop 1M, PEA002 pop 500k, PEA003 pop 2M), `CANONICAL_BLOCKS` (A: 10MHz/2/50c, B: 20MHz/1/30c, C/D: 5MHz/4/100c), upfront amounts `UPFRONT_10M_UNITS`…`UPFRONT_ONE_UNIT`.

**Constants** (all derived from PRD text, all exercised by calculators/assertions): `UPFRONT_CENTS_PER_ELIGIBILITY_UNIT=2500`; `ATTRIBUTABLE_STAKE_PCT=25` (strictly-greater); tiers `400000000/35`, `2000000000/25`, `5500000000/15` (inclusive); `RURAL_SERVICE_POPULATION_CAP=250000`, `RURAL_CREDIT_PCT=15`; increments 3/2→15, 6/5→10, 1/1→5 with cross-multiplication; `STAGE1/2_ACTIVITY_MILLI=800/950`, `STAGE2_START_ROUND=4`; `INTERIM_MILESTONE_DAYS=1095`/`40%`, `FINAL_MILESTONE_DAYS=2190`/`70%`, `INTERIM_MISS_ACCELERATION_DAYS=365`; `UNJUST_ENRICHMENT_*` (365-day years, 100/80/60/40/20→0 schedule); `PAYMENT_DEADLINE_DAYS=30`, `LICENSE_TERM_DAYS=3650`, `RENEWAL_WINDOW_DAYS=365`, `RENEWAL_EXTENSION_DAYS=3650`, `INCUMBENT_TRANSITION_BUFFER_DAYS=30`; clock instants `CLOCK_EPOCH_ISO="2026-09-01T00:00:00Z"`, `QUIET_PERIOD_DAY_ISO`, `GRANT_DAY_ISO`, `TRANSITION_WINDOW_START/END_ISO`. Calculators: `eligibility_units_for`, `expected_attributable_revenue_cents`, `expected_credit_pct`, `bidding_units`, `opening_price_cents`, `round_half_up`, `expected_increment_pct`, `expected_next_price_cents`, `expected_stage`, `expected_eligibility_after_close`, `expected_provisional_net_price_cents`, `expected_net_price_cents`, `expected_credit_amount_cents`, `iso_after_days`, `days_between`, `expected_payment_deadline`, `expected_term_end`, `renewal_window_start`, `expected_milestone_due_date`, `coverage_acceptable`, `expected_unjust_enrichment_cents`, `expected_relocation_shares_proportional/_equal`.

**Assertions**: `assert_{band_plan,license_area,license_block,auction,applicant,clock_round,bid,assignment_bid,license,buildout_milestone,transfer_application,incumbent,renewal_application}`; `assert_millisecond_timestamp` (created_at/updated_at/api_request_timestamp — exactly 3 fractional digits) vs `assert_clock_timestamp` (domain datetimes — exact `...T00:00:00Z` clock form, no fraction normalization); `assert_upfront_ledger_conserved`, `assert_eligibility_from_held`, `assert_license_price_invariants`, `assert_shares_cover_cost`; finders `get_supply_entry`, `get_price_entry`, `get_demand_entry`.

**Fixtures** (all use `get_success_data`, thread entity-backed identities): clock (`set_clock`, `reset_clock`); plan (`create_draft_plan`, `add_area`, `add_block`, `publish_plan`, `create_published_plan`); auction (`create_auction`, `open_applications`, `create_open_auction`, `begin_quiet_period` (auto-advances clock past deadline), `postpone`, `start_clock`, `pause_clock`, `resume_clock`, `complete_assignment`, `get_auction`); applicants (`register_applicant`, `pay_upfront`, `start_review`, `qualify_applicant`, `create_qualified_applicant`, `patch_disclosure`, `resubmit_applicant`, `withdraw_applicant`); rounds/bids (`current_round`, `open_next_round`, `close_round`, `place_bid`, `run_round`, `list_rounds`, `get_round`); assignment (`file_assignment_bid`); licenses (`list_licenses`, `get_license`, `settle_license`, `settle_license_in_full`); milestones (`list_milestones`, `milestones_by_type`, `file_milestone_notice`, `review_milestone`, `file_and_accept_milestone`); incumbents (`register_incumbent`, `incumbent_submit_plan/dispute/resubmit_plan/begin_relocation/confirm_cleared`, `walk_incumbent_to_relocating`); transfers (`file_transfer`, `transfer_begin_review/request_info/provide_info/approve/deny/withdraw`, `get_transfer`); renewals (`file_renewal`, `decide_renewal`). Composite chains: `setup_clock_active_auction` (plan→auction→qualified bidders→quiet→round 1 OPEN), `setup_assignment_phase`, `setup_closed_auction_with_licenses`, `setup_active_license`.

## Verification

- `python3 -m py_compile` passes on every file individually and the whole tree; `import test_helpers.fixtures` and `import conftest` succeed with the task dir on PYTHONPATH (no dangling imports).
- Math smoke check (pure Python, no server): every calculator reproduces the design indices' pre-computed literals — increment tiers (1.5→15%, 1.25→10%, closure), provisional 212,500,000 / final 218,450,000 / credit 38,550,000, per-license round-then-sum 162,500,001×2=325,000,002, activity boundary 12,500,000 unchanged / 6,250,000 / stage-2 floor 18,947,368, unjust enrichment 7,710,000 at day 1824 / 0 at 1825, relocation shares 33,333,333+66,666,668 / 50,000,000+50,000,001.
- 49 client methods and 42 error ids match the PRD tables exactly.

## PRD subtleties routed around (verbatim quotes)

1. **Day arithmetic is 24-hour-multiple, not calendrical** — "a day is a 24-hour multiple, calendar-naive". Consequences verified against the corner index: grant 2026-10-01 + 3650 days = **2036-09-28** (leap days shift the calendar date), renewal grant lands term_end **2046-09-26**, license created 2026-09-16 has payment_deadline **2026-10-16**. `iso_after_days` uses plain `timedelta(days=…)` and matches all index literals; Stage 2 must use it rather than date arithmetic.
2. **Unjust-enrichment elapsed days are real seconds between instants** — day 1824/1825 after grant 2026-10-01 lands on 2031-09-29/30 (2028-02-29 contributes the extra day), exactly as the difficulty index asserts; `days_between` reproduces both.
3. **Renewal creation response status** — "the renewal application … passes through `FILED` and into `UNDER_REVIEW` within the same request": the 201 response reads `UNDER_REVIEW` (the corner index asserts this). Stage 2 must not assert FILED on the create response.
4. **Incumbent registration has no plan-state gate** in PRD §3.1 (the difficulty index registers incumbents on a PUBLISHED plan after COMPLETE_ASSIGNMENT); `register_incumbent` accordingly takes only plan/area ids.
5. **QUALIFY carries no auction-phase gate** (only DISQUALIFY and withdraw do); fixtures qualify during APPLICATION_OPEN, matching every design instance.
6. **Activity rule asymmetry Stage 2 must respect**: `assert_eligibility_from_held` holds only after payments and before any round close — close-time reductions mutate eligibility downward without touching the ledger.

Orchestrator verification (independent): all 10 files exist; whole-tree py_compile OK; `set_clock` in api_client.py confirmed present with unprefixed-clock PRD comment (body spot-checked lines 18–32); constants spot-check (2500, 25, 250_000, 4, 30/3650/365/30) matches PRD; no test_*.py files yet (Stage 2 boundary respected).

## Step 5b-1: Generate tests, part 1 (subagent, Stage 2 of 2, partition A) — 2026-10-02T20:06:48.528110678Z

All checks green. Final state verified: 41 tests collected, 0 citation misses, tag audit clean.

### Files written (12) and per-file test counts

| File | Tests |
|---|---|
| `test_suite/test_difficulty_dual_variant_calc.py` | 2 |
| `test_suite/test_difficulty_combinatorial_formula.py` | 3 |
| `test_suite/test_difficulty_non_linear_state_machine.py` | 2 |
| `test_suite/test_difficulty_transitive_cascade.py` | 2 |
| `test_suite/test_difficulty_priority_pair_validation_conflict.py` | 2 |
| `test_suite/test_difficulty_boundary_precision_check.py` | 2 |
| `test_suite/test_difficulty_cross_entity_state_dependency.py` | 2 |
| `test_suite/test_difficulty_resource_temporal_overlap.py` | 2 |
| `test_suite/test_difficulty_compensating_invariant.py` | 2 |
| `test_suite/test_corner_entities.py` | 9 |
| `test_suite/test_corner_state_machines.py` | 12 |
| `test_suite/test_corner_consistency_model.py` | 1 |

**Total emitted: 41 tests** (19 queue A + 22 queue B).

### Partition-count discrepancy (orchestrator attention)

The partition was quoted as 44 (19 + 25), with state_machines counted as "12 + 3 = 15 non-stub". Per the ground-truth rule (stub iff `excluded_because` replaces `test_recipe`), the second state_machines group — `auction_pause_resume_covered`, `applicant_correction_loop_covered`, `milestone_miss_cascade_covered` — are stubs pointing at §1.8 instances already covered. Skipped silently; **real partition = 19 + 9 + 12 + 1 = 41**. AST audit confirms 62 non-stub / 16 stub / 78 total in the corner file, matching orchestrator measured ground truth.

### Skipped instances

None. All 41 live instances in the partition were emitted. Two recipes needed adjudicated setup repairs (assertions unchanged, Design tags intact):

1. **`Difficulty/priority_pair_validation_conflict/closed_round_state_beats_eligibility_fiscal`** — as written, the recipe's auto-advance to ASSIGNMENT_PHASE makes the bid violate BOTH the round gate and the auction-CLOCK_ACTIVE gate (two tier-5 errors, no PRD-pinned intra-tier order → not uniquely derivable). Kept the exact claim (state tier 5 pre-empts fiscal tier 10; error is `ERR_ROUND_NOT_OPEN`, never `ERR_BID_EXCEEDS_ELIGIBILITY`, 409 not 422) but isolated the failure: round 1 closes with demand 3 > supply 2 so the auction stays CLOCK_ACTIVE and only the round-state + fiscal checks fail.
2. **`Difficulty/boundary_precision_check/unjust_enrichment_day_1824_vs_1825`** — the recipe jumps the clock to 2031-09-29/30 with both milestones PENDING; the milestone sweep (INTERIM due grant+1095d = 2029-09-29, FINAL accelerated to 2031-09-28) would MISS both and TERMINATE the license before either transfer filing. Repaired by filing + ACCEPTing both milestones before the deep-future jumps (same pattern the corner renewal recipe uses), so the license stays ACTIVE and the day-1824/1825 repayment literals (7,710,000 / 0) are reachable.

Also note: `applicant_correction_loop`'s literal `k_v_corr == k_v0 + 2` ignored the upfront-payment mutation; the test asserts the PRD-pinned per-mutation +1 chain from each captured response instead (creation v1 → payment v2 → START_REVIEW v3 → REQUEST_CORRECTION v4 → PATCH v5 → resubmit v6).

### Verification

- `python3 -m py_compile` passes on all 12 files (run after each write).
- `python3 -m pytest test_suite --collect-only -q` from the task root: **41 tests collected, 0 errors** — package graph has no dangling imports (no server started, no tests executed).
- AST tag audit (real parse, not regex): 41/41 tests carry exactly one `Design:` tag; all 41 tags resolve to live (non-stub) instances in the source YAMLs; zero live instances in the partition lack a tag.
- PRD citation audit: every ≥40-char quoted docstring string greps verbatim against `workspace/PRD.md` (0 misses; one C3 ellipsis violation found and fixed).
- Hard constraints honored: 201 only on resource-creating POSTs via `validate_success(resp, 201)`; renewal create asserted `UNDER_REVIEW` (not FILED); clock moved only via `set_clock`; day math via `iso_after_days`/`days_between`/`expected_term_end`/`expected_milestone_due_date`; `assert_millisecond_timestamp` only for envelope/created_at/updated_at, `assert_clock_timestamp` for domain datetimes; entity-backed calls use `make_bidder_headers(<that applicant id>)` / `make_incumbent_operator_headers(<that incumbent id>)`; `assert_eligibility_from_held` used only pre-round-close; helpers untouched.

## Step 5b-2: Generate tests, part 2 (subagent, Stage 2 of 2, partition B) — 2026-10-02T20:41:56.552490704Z

## Stage 2, Part 2 — complete

**Files emitted (all `py_compile`-clean, under `test_suite/`):**

| File | Tests |
|---|---|
| `test_corner_calculations.py` | 5 |
| `test_corner_validations.py` | 4 |
| `test_corner_errors.py` | 12 |
| `test_corner_errors_2.py` | 10 |
| `test_corner_rbac.py` | 6 |
| `test_corner_cross_cutting.py` | 3 |
| **Total** | **40** |

**Stub arithmetic (measured by parsing the YAML myself):** my sections hold 53 instances. Stubs (`excluded_because` key): calculations group 2 = 4 (`activity_boundary_covered`, `unjust_enrichment_boundary_covered`, `settlement_variants_covered`, `relocation_share_variants_covered`), errors group 2 = 6 (`err_round_not_open_covered`, `err_bid_exceeds_eligibility_shadowed_arm_covered`, `err_incumbents_not_cleared_covered`, `err_applicant_invalid_state_on_bid_covered`, `err_lease_window_overlap_covered`, `err_transition_window_conflict_covered`), cross_cutting = 3 (`cascading_side_effects_layer_covered`, `dual_variant_calculation_layer_covered`, `rate_threshold_layer_covered`) — 13 total, all skipped silently. Live: 53 − 13 = **40**, exactly the emitted count (calculations 5 live / 4 stub, validations 4/0, errors 22/6, rbac 6/0, cross_cutting 3/3).

**Skipped live instances: none.** Every live instance passed the PRD-first two-condition filter. No helper gaps hit (all chains expressible with frozen fixtures; two file-local composition helpers for the "transferee registered during APPLICATION_OPEN" chain).

**Two documented deviations (re-derivation, not weakening):**
1. `unjust_enrichment_approval_requires_confirmation` — the YAML recipe asserts `unjust_enrichment_cents == 38,550,000`, but its own chain (gross 250,000,000; 15% rural credit; assignment bid 0) derives credit_amount = 37,500,000 and UJE at the 100% schedule = 37,500,000. Verified against the constants module's PRD-rule calculators. The test asserts the PRD-derived 37,500,000; Design tag unchanged.
2. Both OCC tests (`occ_disclosure_*`, `occ_milestone_*`) — the recipes probe with `expected_*_version = v − 1 = 0` on a freshly created (version-1) resource; whether 0 is 412-stale or 400-malformed is not uniquely derivable from the PRD. Each test first lands one legitimate mutation (version 1→2), then probes with the formerly-valid version 1 — the asserted claim (stale base refused 412 without mutation; fresh base lands at version+1) is unchanged and unambiguous.

**Collection:** `pytest --collect-only -q` passes with **81 tests = 41 (Part 1) + 40 (mine)**. No Part 1 file touched; helpers untouched; no skip/xfail marks; every docstring carries a whitespace-normalized verbatim PRD quote (AST-verified) and ends with exactly one `Design: Corner/...` tag resolving to a live instance (AST-verified, no stub collisions).

Orchestrator's independent AST audit (run after BOTH parts): live instances difficulty=19 corner=62 total=81, stubs=16; 81 test functions collected; every test has exactly one Design tag; no duplicate tags; no tags resolving to stubs or non-existent instances; no live instance untested — VERDICT: CLEAN. `pytest --collect-only` 81 collected, 0 errors.

## Step 6: Generate implementation (subagent) — 2026-10-02T21:13:53.318267739Z

All verification checks pass. The implementation is complete, compiles, boots fresh, and passes the end-to-end smoke test. Final report:

## Implementation complete: task_3494 spectrum license auction

**Files created** (all under `workspace/implementation/`):

| File | Lines | Role |
|---|---|---|
| start.sh | 10 | guarded pip install + `exec python3 app.py`, `$PORT`/0.0.0.0/foreground |
| requirements.txt | 1 | flask |
| app.py | 61 | blueprint registration, envelope-wrapped 404/405/500 handlers |
| store.py | 122 | in-memory dicts, logical clock (starts 2026-09-01T00:00:00Z), dashed-UUID ids, two timestamp renderers, creation sequence |
| errors.py | 59 | ApiError + success/error envelope builders (`meta`/`response_type`/`data`) |
| helpers.py | 143 | auth (X-User-ID/X-User-Role), role gates, body validators, pagination (limit/offset/total_count/has_more), OCC, per-request mutation dedup |
| serializers.py | 185 | 13 entity serializers |
| calcs.py | 209 | all constants + credit tiers, increments, activity, settlement (round-half-up per license then sum), unjust enrichment, relocation shares (floor + largest-remainder, units DESC / created_at ASC) |
| sweeps.py | 152 | clock sweeps (payment-lapse cancel, milestone MISS + acceleration + termination, lease reconcile) in created_at ASC order; shared cascade helpers |
| routes_clock.py | 22 | `POST /_clock/set_current_utc` (unprefixed) |
| routes_band.py | 138 | band plans / areas / blocks / publish |
| routes_auctions.py | 233 | auctions + phase driver (START_CLOCK, COMPLETE_ASSIGNMENT) |
| routes_applicants.py | 315 | register / disclosure(OCC) / upfront / review / resubmit(OCC) / withdraw |
| routes_rounds.py | 243 | round open/close (activity rule, auto-advance), bids |
| routes_assignment.py | 76 | assignment bids |
| routes_licenses.py | 88 | license registry, settlement → grant + milestones |
| routes_milestones.py | 80 | milestone list / file-notice(OCC) / review |
| routes_transfers.py | 190 | transfer filing + adjudication + withdraw |
| routes_incumbents.py | 168 | incumbent register + transition machine + share posting |
| routes_renewals.py | 87 | renewal file/decide |

Total 49 routes — exactly the endpoint table. Every `.py` passes `py_compile`.

**Smoke test** (dynamic port 43243, killed by exact PID afterward): 40 checks passed. Observed codes: 401 no-auth, 403 wrong-role, 200 clock set echoing `2026-09-01T00:00:00Z`, 201 band plan/area/block/auction/applicant/bid/assignment-bid, 200 publish/phase/qualify, 409 `ERR_APPLICATION_DEADLINE_NOT_PASSED` before deadline, full loop START_CLOCK → bid → close → auto-ASSIGNMENT_PHASE → COMPLETE_ASSIGNMENT (CLOSED, `total_proceeds_cents` 650325, supply 2→1), license minted with `net_price_cents` 650325 / `provisional_net_price_cents` 650000 / `credit_amount_cents` 350175 / `payment_deadline` 2026-10-15, 422 `ERR_OVERPAYMENT`, grant → ACTIVE with INTERIM (2029-09-14, 40) + FINAL (2032-09-13, 70) in order, 412 `ERR_STALE_VERSION`, 422 `ERR_COVERAGE_BELOW_REQUIREMENT` at 39.9% vs ACCEPT at exactly 40%, sweep past FINAL due → license TERMINATED + supply restored to 2. Two initial smoke "failures" were client-side arithmetic mistakes (eligibility 40 vs bid units 10,000 per PRD formula; term_end hand-count) — the implementation matched the PRD's calendar-naive `timedelta(days=…)` arithmetic exactly (verified: grant 2026-09-15 + 3650d = 2036-09-12).

**Interpretations chosen (pre-flagged arbitration candidates for Step 7):**
1. OCC placement (outside the 10 tiers): after existence/ownership/state, before tier-6+ checks; file-notice order = ownership → milestone-state → OCC → license-state (scaffold's listing).
2. Quiet-freeze vs applicant-state conflict: followed §2.7 (state tier 5 fires before quiet tier 6) over §3.2's "regardless of the applicant's status".
3. Freeze scope: disclosure/resubmit rejected with `ERR_QUIET_PERIOD_VIOLATION` whenever the auction is not APPLICATION_OPEN (scaffold "until CLOSED" vs tier-6 "QUIET_PERIOD or later" reconciled this way).
4. Auction creation against a non-PUBLISHED plan → `ERR_INVALID_REQUEST` 400 (no catalog error exists for this).
5. Bidder X-User-ID not an applicant of the round's auction → `ERR_APPLICANT_INVALID_STATE` 409.
6. Bid tier-5 gate order: round OPEN → auction CLOCK_ACTIVE → bidder QUALIFIED → product open (PRD §3.5 textual order).
7. Opening next round while previous still OPEN → `ERR_AUCTION_INVALID_STATE` (catalog's `ERR_ROUND_NOT_OPEN` covers only bid/close).
8. Upfront `amount_cents` must be a positive integer, else 400 (ERR_OVERPAYMENT's `<= 0` clause covers settlement only).
9. No applicant-status gate on upfront payments (PRD states only the auction window).
10. Eligibility recomputed from held on every refund/forfeiture (§3.2 "reduce live eligibility").
11. START_CLOCK eligibility snapshot bumps applicant version (+1 per mutation, §2.5).
12. One version bump per resource per request across multi-hop cascades.
13. INTERIM-miss acceleration applies only while FINAL is PENDING/FILED/REJECTED.
14. FINAL-miss termination only when license is ACTIVE (License machine precondition).
15. Share arrays stored in distribution order; `relocation_share_owed_cents` accumulates across cleared incumbents.
16. No area↔plan cross-check at incumbent registration; allowed in any plan state (no invented guard).
17. lease_start/lease_end on FULL_ASSIGNMENT ignored (permissive).
18. Pagination: out-of-range integers clamped (1..100 / >=0); unparseable → 400.
19. Body-shape validation (400) runs right after role authz, before path existence (needed for per-action role checks anyway).
20. `ownership_interests` required at registration (no `?` in scaffold input), entries strictly typed, sum-to-100 with 1e-9 float tolerance, enforced at create/PATCH/QUALIFY.
21. `aggregate_demand` includes zero-demand open products.
22. Renewal persisted directly as UNDER_REVIEW v1 (filing+review-open are one request).
23. `confirm_unjust_enrichment_repayment` must be JSON `true` strictly.
24. Clock settable to any instant (no monotonicity rule stated); sweeps fire on `deadline < now` strictly, lease clear on `end <= now`.
25. DISQUALIFY voids SUBMITTED bids in every OPEN round of the auction.

**Contradictory/unimplementable PRD requirements:** none unimplementable. Two genuine internal conflicts (resolved as above): (1) §3.2 *"the anti-collusion freeze of §3.4 rejects it with ERR_QUIET_PERIOD_VIOLATION regardless of the applicant's status"* vs §2.7's fixed tier ordering (state=5 < anti-collusion=6); (2) SCAFFOLD tier-6 note *"rejected … until the auction reaches CLOSED"* vs §2.7 tier 6 *"rejected while the auction is QUIET_PERIOD or later (until CLOSED)"* — self-contradictory on whether CLOSED lifts the freeze. One catalog gap: no error_id for "auction creation against non-PUBLISHED plan".

**Fidelity confirmations:** dashed UUIDs (`str(uuid.uuid4())`; the only `.hex` is the `req_` request id, not a resource id) · clock endpoint unprefixed at `/_clock/set_current_utc` · two timestamp families (`created_at`/`updated_at`/`api_request_timestamp` always `.NNNZ` 3-digit; domain datetimes render as the logical clock reads) · in-memory dicts only (no sqlite/file/tmp — grep-verified) · zero seeding (store starts empty; all data arrives via API) · zero invented guards (all gates trace to PRD/scaffold; permissive readings recorded above) · no test files were read or consulted.

Orchestrator verification (independent): all 20 files compile; `str(uuid.uuid4())` in store.py:51 with the only `.hex` on the envelope `req_` id; clock route at `/_clock/set_current_utc` mounted unprefixed; start.sh execs foreground, app.py reads `$PORT` and binds 0.0.0.0; no sqlite/open/json.dump//tmp/pickle tokens; independent boot smoke on dynamic port 51455 — clock set 200 with correct envelope, band-plan create responded (400 on orchestrator's deliberately-minimal payload), server killed by its own saved PID.

## Step 7: Run tests and iterate (long-lived subagent) — 2026-10-02T21:36:10.836405909Z

Clean 8-round sweep achieved — all 81 tests pass in every round. Summary:

**Iterations run:** 2 (baseline sweep: 74/81 × 8 rounds, identical deterministic failure set; fix sweep: 81/81 × 8 rounds)

**Tests deleted:** none — every failure traced to a fixable test-artifact defect or a re-derivable literal; no PRD-silence deletions were needed.

**Fixes applied to `test_helpers/`:**
- `test_helpers/assertions.py` — `assert_applicant`: `attributable_revenue_cents` now accepts `None` or non-negative int (PRD §3.2's zeroed-ledger list excludes it — SCAFFOLD confirms no default, unlike `credit_pct`'s `default: 0` — so its pre-QUALIFY value is not PRD-determined; the other seven fields stay strict ints). `assert_incumbent`: `shares_proportional`/`shares_equal` accept `None` pre-workflow (PRD §3.1 "stay unset" does not uniquely determine null vs `[]`); entries still validated once filled.

**Fixes applied to `test_suite/`:**
- `test_corner_errors_2.py` — added missing `transfer_approve` import (helper existed in fixtures.py; NameError at line 273).
- `test_difficulty_cross_entity_state_dependency.py` — added missing `register_incumbent` import (same class of bug, line 63).
- `test_difficulty_boundary_precision_check.py` (`test_unjust_enrichment_day_1824_vs_1825`) — corrected three literals to the PRD-derived values: the chain files a 0-cent assignment bid, so `gross_final` = 250,000,000 and the 15% rural credit yields `credit_amount_cents` 37,500,000 (was the stale recipe literal 38,550,000, which belongs to a 7M-assignment-bid chain) and day-1824 repayment 7,500,000 (was 7,710,000). Same re-derivation the worklog documented for the sibling test; the day counts (1824/1825) verified exact.
- `test_difficulty_combinatorial_formula.py` (`test_activity_eligibility_evaluation_order`) — the rounds 1–3 loop never opened rounds 2/3 (PRD §3.5: the administrator opens each next round explicitly), so iteration 2 bid into the CLOSED round 1 → `ERR_ROUND_NOT_OPEN`. Added `open_next_round` inside the loop for the first two iterations.
- `test_corner_entities.py` (`test_applicant_get_returns_stored_fields`) — dropped the pre-QUALIFY `attributable_revenue_cents == 0` assertion (default-value silence; kept `credit_pct == 0`, which §3.2 verbatim zeroes). `test_incumbent_window_fields_default_null` — share arrays asserted `in (None, [])` instead of `== []` ("unset" is not uniquely one rendering); window-null and version assertions unchanged.
- `test_corner_cross_cutting.py` (`test_occ_milestone_filing_stale_version_returns_412`) — restructured to reach the stale base via a review decision (FILED→REJECTED bumps version per §2.5) instead of re-filing from FILED. §3.8's "allowed from PENDING or REJECTED" vs §2.8's "an earlier filing … invalidates a stale base" leave filing-from-FILED genuinely ambiguous (the impl rejects it with `ERR_MILESTONE_INVALID_STATE`); REJECTED is fileable under both readings, so the stale→412 assertion, no-mutation check, and fresh-base version chain are now all uniquely derivable. Added `review_milestone`/`MilestoneDecision` imports.

**Fixes applied to `implementation/`:** none — the implementation was PRD-faithful on every tripped path; all seven failures were test-side.

**Final per-round passed/total:** round 1: 81/81, round 2: 81/81, round 3: 81/81, round 4: 81/81, round 5: 81/81, round 6: 81/81, round 7: 81/81, round 8: 81/81. All `results.1.json` … `results.8.json` preserved in `workspace/implementation/`.

Orchestrator verification (independent): all 8 results.*.json exist and each parses to passed=81 total=81 failed=0; mtime audit — no .py source file in implementation/, test_suite/, or test_helpers/ is newer than the oldest results file (sweep is current; no post-sweep edits); spot-checked both import fixes in source (transfer_approve at test_corner_errors_2.py:48/274, register_incumbent at test_difficulty_cross_entity_state_dependency.py:23/64).

## Step 8: Finalize PRD (subagent) — 2026-10-02T21:45:20.468325002Z

All three edits verified against the diff — exactly 3 lines revised in place, no new sections. Task complete.

## Summary

**File:** `workspace/PRD_FINALIZED.md`

**Line counts:** PRD.md 320 → PRD_FINALIZED.md 320 (0% delta; 3 lines revised in place, no insertions of new sections)

### Changes (one bullet per edit)

- **§3.1** — revise — incumbent registration sentence now pins that `transition_window_start`, `transition_window_end`, `shares_proportional`, and `shares_equal` each **render as null** while unset — `implementation/routes_incumbents.py:37-40` (all four init `None`), `implementation/serializers.py:169-176` (None→null), `implementation/store.py:104-105` (`render_domain(None)`→None)
- **§3.2** — revise — registration sentence now pins that `attributable_revenue_cents` is not part of the zeroed ledger and **renders as null from registration until a successful qualification computes it**, with no other writer — `implementation/routes_applicants.py:85` (init `None`), `implementation/routes_applicants.py:220` (QUALIFY writes), `implementation/serializers.py:66` (raw render)
- **§3.8** — revise — filing gate changed from "allowed from `PENDING` or `REJECTED`" with only `ACCEPTED`/`MISSED` enumerated as failures, to "allowed **only** from `PENDING` or `REJECTED`" with `FILED`, `ACCEPTED`, `MISSED` all failing with `ERR_MILESTONE_INVALID_STATE` — `implementation/routes_milestones.py:41-43`

### Per-edit pre-edit search log

1. **§3.2 attributable_revenue_cents edit** — (a) subject: field lifecycle of applicant `attributable_revenue_cents`. (b) paths enumerated via `grep -rn "attributable_revenue_cents"` over `implementation/`: `serializers.py:66`, `routes_applicants.py:85,220`, `calcs.py:104-125`; also read `update_disclosure` (routes_applicants.py:118-162, never touches the field), REJECT/WITHDRAW/DISQUALIFY branches (never touch it). (c) added "and nothing else ever writes it" to cover the no-recompute-on-disclosure-update and never-qualified-terminal cases.
2. **§3.1 incumbent unset-fields edit** — (a) subject: pre-workflow rendering of the four deferred incumbent fields. (b) paths: `routes_incumbents.py:37-40` (init None), `134-135` (BEGIN_RELOCATION fills windows only), `156-157` (CONFIRM_CLEARED fills shares), `serializers.py:169-176`, `store.py:99-110`, `calcs.py:186-187` (no-ACTIVE-licenses case returns `([],[])` — arrays, post-fill, consistent with §3.7's "both arrays are empty"). (c) chose "stay unset — each rendering as null — until that workflow fills them in" (widened to all four fields, since `render_domain(None)` also yields null for the window fields; shares stay null through RELOCATING until CONFIRM_CLEARED, which the "until the workflow fills them" phrasing covers).
3. **§3.8 filing-from-FILED edit** — (a) subject: file-notice state gate's rejection set. (b) paths: `routes_milestones.py:41-43` (sole filing path; state gate precedes `check_occ` at line 44, so FILED+stale-version also yields 409), `routes_milestones.py:64` (review requires FILED — unaffected), `sweeps.py:90-111` (sweep transits PENDING/FILED/REJECTED→MISSED — endpoint wording does not touch sweep semantics), `routes_licenses.py:74-87` (grant creates PENDING pair). Cross-checked §2.8's "an earlier filing" invalidator: remains accurate because a filing plus a review decision bridges back to fileable REJECTED with a bumped version; "supersedes/overwriting" language matches the REJECTED re-file loop already in §3.8. (c) enumerated all three rejected statuses explicitly ("`FILED`, `ACCEPTED`, or `MISSED` alike") rather than a partial enumeration.

### Per-item verdict log (every step_7_diff item)

- `assert_applicant` `attributable_revenue_cents` None-or-int → **edited** (§3.2) — impl initializes to `None` and renders null pre-QUALIFY (`routes_applicants.py:85`, `serializers.py:66`); PRD's zeroed-ledger list excluded it.
- `assert_incumbent` `shares_proportional`/`shares_equal` None-or-[] → **edited** (§3.1) — impl initializes both to `None` and renders null until CONFIRM_CLEARED (`routes_incumbents.py:39-40,156-157`); "stay unset" did not determine null vs `[]`.
- `test_corner_errors_2.py` missing `transfer_approve` import → **no-edit-pure-test-bug** — NameError fix, no response-visible behavior.
- `test_difficulty_cross_entity_state_dependency.py` missing `register_incumbent` import → **no-edit-pure-test-bug** — NameError fix, no response-visible behavior.
- `test_unjust_enrichment_day_1824_vs_1825` literal corrections → **no-edit-PRD-already-pins** — §3.9 explicitly states day-1824 owes 20% and day-1825 owes 0%; impl matches (`calcs.py:37-39,171-176`: `1824//365=4→20%`, `1825//365=5→0%`).
- `test_activity_eligibility_evaluation_order` `open_next_round` addition → **no-edit-PRD-already-pins** — §3.5 "the administrator opens the next round" + §4 `POST /auctions/{id}/rounds` (AuctionAdmin); impl opens rounds only via that endpoint (`routes_rounds.py:18-35`).
- `test_applicant_get_returns_stored_fields` dropped pre-QUALIFY `== 0` → **edited** (same §3.2 edit as the assertions.py item above; the dropped assertion's site is now pinned to null).
- `test_incumbent_window_fields_default_null` shares `in (None, [])` → **edited** (same §3.1 edit; impl is exactly null pre-workflow).
- `test_occ_milestone_filing_stale_version_returns_412` restructured via REJECT → **edited** (§3.8) — impl rejects filing from FILED with `ERR_MILESTONE_INVALID_STATE` at `routes_milestones.py:41-43`; PRD's failure enumeration omitted FILED, now pinned.

Orchestrator verification (independent): `diff -q` shows files differ; diff line count = 6 (3 old + 3 new, in-place revisions at PRD lines 129/135/199 — matching the §3.1/§3.2/§3.8 claims exactly); no other hunks; wording is inline and minimal.

## Step 9: Complete PRD (subagent) — 2026-10-02T22:07:41.246745036Z

Done. PRD_COMPLETED.md is written at `workspace/PRD_COMPLETED.md` — 320 lines (same as source), 62,381 chars vs 59,905 (+2,476), 14 paragraphs touched, no new sections.

## Summary

**Counts:** 14 ambiguity-pins, 1 mismatch-revision (plus one consistency follow-on in §2.7).

**Changes (one bullet each):**
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` → `ERR_INVALID_REQUEST` (400); out-of-range values clamped (limit→[1,100], offset→0 floor); `created_at` ties break by creation order, never id — `implementation/helpers.py:108-133`, `store.py:119-122`
- §2.4 — revise — ambiguity — clock endpoint accepts any parseable instant (no monotonicity gate; sweeps evaluate against whatever is set); `current_utc` echoes in the domain rendering family — `implementation/routes_clock.py:14-22`
- §2.8 — revise — **mismatch (internal PRD contradiction)**: §2.8 said "Two write operations" are OCC-guarded but §3.3 names resubmission as a third OCC carrier; impl enforces OCC on all three — revised to "Three", added the resubmit endpoint (`expected_applicant_version`) — `implementation/routes_applicants.py:274-283`
- §2.8 — insert — ambiguity — OCC placement: after ownership and the guarded resource's own state gate, before remaining gates (precedes quiet-period freeze on applicant endpoints, precedes license-state check on file-notice) — `routes_applicants.py:129-138,280-288`, `routes_milestones.py:41-48`
- §2.7 — revise — consistency — "two optimistic-concurrency endpoints" → "three"
- §3.1 — revise — ambiguity — band edges are numbers; lower edge not strictly below upper → `ERR_INVALID_REQUEST` (400) — `routes_band.py:23-27`
- §3.1 — revise — ambiguity — incumbent registration validates existence of plan and area only; no plan↔area linkage required — `routes_incumbents.py:29-30`
- §3.2 — revise — ambiguity — auction creation against a non-`PUBLISHED` plan → `ERR_INVALID_REQUEST` (400) — `routes_auctions.py:29-31`
- §3.2 — revise — ambiguity — registration field shapes: `service_population` non-negative int; ownership entries (non-empty `holder_name`, non-negative-number `stake_pct` with fractions admitted, non-negative-int revenue); malformed → 400 — `routes_applicants.py:20-42,60-69`
- §3.2 — revise — ambiguity — stake-sum check tolerates floating-point error (within 1e-9 of 100 passes) — `routes_applicants.py:45-50`
- §3.2 — revise — ambiguity — upfront `amount_cents` must be a positive integer; non-positive → `ERR_INVALID_REQUEST` (400) — `routes_applicants.py:171`
- §3.5 — revise — ambiguity — opening the next round while auction not `CLOCK_ACTIVE` or current round not `CLOSED` → `ERR_AUCTION_INVALID_STATE` — `routes_rounds.py:23-35`
- §3.5 — revise — ambiguity — bid caller whose `X-User-ID` is not an applicant of the auction → `ERR_APPLICANT_INVALID_STATE`, evaluated after product resolution and before the round-open gate — `routes_rounds.py:165-168`
- §3.8 — revise — ambiguity — `covered_population` is a non-negative integer — `routes_milestones.py:32-33`
- §3.8 — revise — ambiguity — INTERIM-miss acceleration applies only while the sibling FINAL is `PENDING`/`FILED`/`REJECTED`; a terminal FINAL is untouched — `sweeps.py:101-107`
- §3.9 — revise — ambiguity — transferee may be any existing applicant including the holder itself; `lease_start`/`lease_end` ignored (stored null) on `FULL_ASSIGNMENT` — `routes_transfers.py:28,33,62-63`

### IMPL BUGS
None. Every constant (2500/unit, >25% attribution, credit tiers 4e8/35, 2e9/25, 5.5e9/15, rural 250000/15, increment tiers 3/2→15, 6/5→10, 1/1→5, stage 2 from round 4, 800/950 milli-activity, 30d payment deadline, 3650d term/extension, 365d renewal window, 30d incumbent buffer, unjust-enrichment schedule {100,80,60,40,20,0} at 365d years, 40%/70% coverage at 1095/2190d, 365d acceleration) matches the PRD exactly; all 49 endpoints exist with the pinned verbs, paths, roles, and 201/200 split; every error ordering traced matches §2.7 tiers.

**Hunt results:**
1. **Dead-code checks: none.** All 42 catalog error ids have live raise sites (grep-verified). Writer-side reachability spot-checked: `ERR_QUIET_PERIOD_VIOLATION` reachable (NEEDS_CORRECTION applicant + quiet period), `ERR_TRANSITION_WINDOW_CONFLICT` reachable (second RELOCATING incumbent in area), `ERR_PRODUCT_CLOSED` reachable (product in plan, absent from round prices).
2. **None-crash paths: none.** Enumerated nullable fields: `attributable_revenue_cents` (serializer-only read), `grant_date` (read in `calcs.py:168` under the ACTIVE gate; grant sets it atomically), `term_end` (renewal paths guarded by ACTIVE / open-renewal existence), `payment_deadline` (sweep None-guarded, set at creation), `active_lease_*` (None-guarded in `sweeps.py:140`), `covered_population` (read at `routes_milestones.py:72` only under FILED, which sets it), `transition_window_*` (read only under RELOCATING, which sets them), `lease_start/end` (read only for LEASE type, required at lease filing), `shares_*` (None-safe serializer), `final_round_id` (read only under ASSIGNMENT_PHASE, set atomically with it). No live smoke needed — no suspect path found.
3. **Prose-only uniqueness rules: none missing.** Every uniqueness/invariant claim carries a catalog error id and is enforced (area_code, block category, bid triple, assignment bid, open-renewal singleton); no unenforced prose-only rule exists.
4. **Timestamp families: match.** `render_house` (exactly 3 fractional digits) for `created_at`/`updated_at`/`api_request_timestamp`; `render_domain` (as the clock reads, no padding) for all 11 PRD-listed domain fields; the clock echo joins the domain family (now pinned).
5. **Sweep coverage: match.** Payment sweep strict `<` (deadline == now survives); milestone sweep strict `<` across PENDING/FILED/REJECTED; INTERIM-miss accelerates the sibling FINAL −365d with version bump, and a FINAL pushed past due is caught later in the same pass (grant creates INTERIM before FINAL, and the sweep runs created_at ASC); FINAL-miss terminates an ACTIVE license with transfer-denial + supply-restore cascades; lease reconcile activates on half-open containment and clears at `end <= now`. Sweep class order payment → milestone → lease, each created_at ASC with creation-sequence tie-break.

Orchestrator verification (independent): PRD_COMPLETED.md exists (62,381 bytes, matches hand-back); diff vs PRD_FINALIZED.md = 14 replacement lines; spot-checks — "Three write operations" present in PRD_COMPLETED and absent in PRD_FINALIZED (the §2.8 mismatch-revision landed), clamping pin present; mtime audit — no .py source file in implementation//test_suite//test_helpers/ is newer than the oldest results file (the 8-round sweep remains authoritative; Step 9 touched no code); all 8 results.*.json intact and each parses to 81/81. No Step 9b needed (zero impl bugs reported).

PIPELINE COMPLETE — final state: 81/81 tests × 8/8 rounds passing; PRD.md → PRD_FINALIZED.md (3 pins) → PRD_COMPLETED.md (+15 pins); zero test deletions; zero implementation fixes required after generation.
