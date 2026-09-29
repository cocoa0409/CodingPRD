# Worklog — task_2763_timeshare_exchange_network_operations

## Step 1: Create task directory — 2026-09-04T17:36:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2763_timeshare_exchange_network_operations` and its `workspace/` subdirectory. Index 2763 was pre-assigned by the orchestrating command; no scan/allocation performed.

## Step 2: Generate scaffold — 2026-09-04T18:59:00.000Z

All three scaffold artifacts are complete and lint-clean.

## Files written (`tasks/task_2763_timeshare_exchange_network_operations/`)

| File | Lines | Top-level key(s) |
|---|---|---|
| `SCAFFOLD.yaml` | 3080 | 20 keys, §1.0–§1.7; contains neither `scaffold_difficulty_design` nor `scaffold_corner_design` |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1580 | `scaffold_difficulty_design` only |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3665 | `scaffold_corner_design` only |

## Lint verdict (verbatim)

```
Coverage
  §1.5 endpoints declared:    57
  §1.1 entities declared:     12
  §1.8 instances scanned:     20
  §1.9 instances scanned:     54
  Calls scanned (§1.8+§1.9):  757

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Counts

- **SCAFFOLD.yaml**: 12 entities, 9 state machines, 3 concurrency (OCC) rules, 9 calculations, 4 invariants, 33 ordered validations, 57 endpoints, 42 errors, 4 roles (Member / ResortManager / NetworkOperator / DisputeAnalyst). Also carries `operational_constants`, `occupancy_model`, `season_band_interval_model` and a pinned 7-step `matching_run_step_order`.
- **§1.8**: all 9 required `rule_id`s, **20 instances** — dual_variant_calc 2, combinatorial_formula 2, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 2, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 2.
- **§1.9**: all **9 sections**, **69 instances** = **54 active** + **15 `excluded_because` stubs** (entities 8, state_machines 10, calculations 8, validations 14, endpoints 6, errors 11, rbac 4, cross_cutting_complexity_layers 7, consistency_model 1).
- Instance `name` is unique across the union of both design files; every stub cites a real §1.8 instance name; all 42 error_ids are referenced by at least one design instance.

## Coverage audit notes

1. **Unreachable getaway urgency bands (defect in SCAFFOLD.yaml).** `GETAWAY_URGENCY_BANDS` declares discount_pct 0 / 10 / 20 / 35, but only 35 is reachable. Sweep-listed offers require `expires_at − clock ≤ 45` and `expires_at = check_in + 730`, so `days_to_check_in ≤ −685`; cancellation-listed offers only exist when `days_out < 30`. Both paths always land in the 35% band. I deliberately did **not** write a §1.9 instance claiming a 60/59-day urgency boundary. `rate_threshold_triggers` was covered with `PROCESSING_FEE_BANDS` (subtotal 14999 vs 15000 → 15450 vs 16250) and `tiered_pricing` with `DEPOSIT_FIRST_CREDIT_BANDS` (9999 vs 10000 → 11199 vs 10700, a *negative* 499-cent step). If you want the band table exercised, either shorten `DEPOSIT_TTL_DAYS` or make the sweep window relative to check-in.
2. **`matching_run_step_order` step 3 has no member-status predicate.** `candidate_pool_filter` constrains only the deposit side, so a LAPSED member's request is still ranked and matched. The step-0-before-step-3 ordering is therefore observable only via the −25 `DUES_ARREARS_PENALTY` in the recomputed `priority_score` and the `LAPSED` flag, not via exclusion. I dropped the planned "lapse blocks the matching pass" claim and instead demonstrated step ordering with `hold_expiry_in_step_two_frees_the_deposit_for_step_three` (one POST yields both an EXPIRED request and a newly MATCHED one over the same released deposit).
3. **`PATCH /exchange-network/resorts/{resort_id}` takes no `expected_resort_version`**, so the resort-OCC instance establishes staleness by capturing `version` from the create 201 and letting affiliation + two deposits move the row on, asserting the current version differs.
4. Endpoint name to watch when authoring tests: extensions is **plural** — `POST /exchange-network/deposits/{deposit_id}/extensions`.
5. PyYAML mechanic: every `grounds:` element containing `[...]` must be double-quoted (a bare nested `[` inside a flow sequence is a parse error). `/tmp/fix_grounds.py` normalises this and re-verifies the parse plus per-section counts.

Orchestrator note: verified `grep -n "harder than expert"` returns nothing in any of the three scaffold files, so the difficulty directive did not leak past Step 2.

## Step 3: Copy shared files — 2026-09-04T19:00:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_2763_timeshare_exchange_network_operations/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-04T19:16:00.000Z

All checks re-verified clean after the two fixes.

**PRD written:** `workspace/PRD.md` — **419 lines**, ends at a genuine boundary (final row of the §5 error table, `ERR_INSUFFICIENT_TRADING_POWER | 402`), no audit footer, no Hard Contract reports written into the file or any sibling file.

**Section list**
- §1 Introduction (pain point → scope → the two governing properties: valuation-honest, checkpoint-driven; API mounted under `/exchange-network`)
- §2 Global Specifications & System-Wide Principles: 2.1 Membership Identity and RBAC · 2.2 API Response Structure · 2.3 Pagination · 2.4 Record Identity, Audit Fields and Path Resolution · 2.5 The Logical Clock and the Operations-Run Checkpoint · 2.6 Arithmetic, Rounding and Money Conventions · 2.7 The Two-Ledger Principle · 2.8 Derived Counters and Inventory Conservation · 2.9 Optimistic Concurrency on Contended Records · 2.10 Validation Precedence (all 33 rules as an ordered list with error ID, status, `applies_to`)
- §3 Business Logic & Workflows: 3.1 Bringing a Resort Into the Network · 3.2 Membership Tiers, Enrollment and Annual Dues · 3.3 Banking a Week and What It Is Worth · 3.4 Filing an Exchange Request · 3.5 The Operations Run: Seven Pinned Steps · 3.6 Confirming, Declining, Completing, Cancelling and Reinstating · 3.7 Unmatched Inventory: Getaway Listings, Pricing and Rentals · 3.8 Post-Stay Reviews and the Quality Ladder · 3.9 Disputes Over Valuations and Resort Quality
- §4 Endpoint Definitions (57 rows)
- §5 Error Code Catalogue (42 rows)

**Coverage confirmed:** 12 entities (MembershipTier, Resort, SeasonBand, Member, Deposit, ExchangeRequest, Confirmation, MatchingRun, GetawayOffer, Dispute, ResortQualityReview, LedgerEntry) · 9 state machines (incl. the two-dimension `deposit_status` × `rental_status` parallel machine on one Deposit row) · 9 calculations (incl. both variants of `deposit_trading_power`, `resort_deposit_obligation_shortfall`, `cancellation_settlement`) · 4 invariants (INV_POWER, INV_CASH, INV_NIGHTS, INV_ACTIVE_REQUESTS) · 33 validations · 57 endpoints · 42 errors · 4 roles.

**Hard Contract 1 — Field-Name Coverage: PASS** — entity fields 109/109; request-body inputs 54/54; query params 30/30; path params 12/12; errors 42/42; state values, enum values, roles: 0 missing.

**Hard Contract 2 — Rule Coverage: PASS** — all 33 validations in explicit numbered precedence order with error ID + status + full `applies_to`, plus two normative worked precedence cases (`ERR_MEMBER_NOT_ACTIVE` before `ERR_INSUFFICIENT_WALLET_CREDIT`; `ERR_RESORT_NOT_AFFILIATED` before `ERR_NO_SEASON_BAND_FOR_DATE`). All 3 concurrency rules in §2.9 with endpoint, `expected_*_version`, `ERR_STALE_VERSION` (412), untouched-fields-on-rejection rule, `version` increment on success. Sibling-branch symmetry verified for every fork. Two gaps found and repaired in this pass: (a) the `RESERVED → BANKED` release guard "no confirmation naming this week as `awarded_deposit_id` is still `CONFIRMED`", now stated once as governing all three release triggers; (b) the `GETAWAY_LISTING_FORFEIT` posting on the prorated-cancellation listing path, which shares the `NOT_LISTED → LISTED_GETAWAY` edge with run-driven listing.

**Hard Contract 3 — §3 Path Purity: PASS** — §3 backtick tokens scanned: 831; tokens starting with `/`: 0; bare HTTP-method tokens: 0; method+path combined tokens: 0; plain-text `/exchange-network` mentions in §3: 0.

Both withheld design files were never opened or grepped, and no sibling task directory was read. The two worked examples in the PRD (trading power `62`, exchange charge total `30260`) come from `SCAFFOLD.yaml` itself.

One scaffold discrepancy worth flagging upstream: the `difficulty_level` comment in `SCAFFOLD.yaml` claims "52 endpoints / 40 error codes / 8 calculations", but the authoritative `endpoints[]`, `errors[]` and `calculations[]` blocks contain 57 / 42 / 9. The PRD follows the blocks.

Orchestrator truncation check: `wc -c` = 101535 bytes over 419 (long) lines; `tail` confirms the file ends on the last error-table row, a real section boundary — not truncated. `grep -c "harder than expert" workspace/PRD.md` = 0, so the difficulty directive never reached the PRD.

## Step 6: Generate implementation — 2026-09-04T19:44:00.000Z

The implementation is complete and verified.

## Modules (all under `workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| `app.py` | 74 | Flask app, 7 blueprints at `/exchange-network`, `ApiError`/400/404/405/415/`HTTPException`/500 handlers in the standard envelope, `app.run(host="0.0.0.0", port=$PORT)` |
| `store.py` | 207 | In-memory `Store` (12 dicts) + all operational constants, enum vocabularies, instant/date helpers, `serialize`, `touch` (at most one version bump per HTTP request) |
| `errors.py` | 100 | `ApiError` + full 42-entry `ERROR_STATUS`/`ERROR_MESSAGE` catalogue |
| `response.py` | 95 | `req_` + 20-char ids, 3-digit-fraction ISO timestamps from the logical clock, object/array/error envelopes, pagination |
| `authz.py` | 67 | Role gate (priorities 1–3), acting identity (5), ownership (8), resort-manager scope (9) |
| `shapes.py` | 199 | Body/query shape validators and the 12 FK finders |
| `calc.py` | 227 | All 8 calculations with per-calculation rounding |
| `services/deposits.py` | 156 | Band lookup, occupancy window, `expires_at`, capacity, settlement freeze, expiry/withdrawal, getaway listing |
| `services/resorts.py` | 110 | Review window (8 + ties), quality recompute, inventory sync, affiliation year, compliance, complaint strikes |
| `services/matching.py` | 260 | The 7-step run (dues lapse, deposit expiry, request sweep, matching pass, completion, getaway listing, resort probation) + 9 counters |
| `services/ledger.py` | 53 | Two-ledger posting, clamped power debits, cash moves, balance recompute |
| `services/requests.py` | 50 | Active-request recount, hold release, charge refund |
| `routes/*.py` (8 files) | 61/122/162/186/362/163/196/108 | All endpoints |
| `start.sh` | — | `PORT`-aware, guarded flask install, `exec python3 app.py` in the foreground |

Total 2958 lines of Python. Every `.py` passes `ast.parse` (0 failures); `__pycache__` cleaned up.

## Coverage
- **57 endpoints** registered, exactly matching the 57 `- method:` entries in SCAFFOLD.yaml (verified by enumerating `url_map`): tiers 3, resorts 7, season-bands 3, quality reviews 3, members 6, ledger 2, deposits 6, exchange-requests 6, confirmations 5, matching-runs 3, getaway-offers 4, disputes 8, clock 1.
- **9 state machines**: Resort affiliation, Member enrollment, Deposit `deposit_status` and the parallel `rental_status`, ExchangeRequest (incl. the MATCHED→WAITLISTED→MATCHED loop), Confirmation (incl. REINSTATED successor rows), GetawayOffer, Dispute (cyclic, max 2 info rounds), MatchingRun.
- **8 calculations**: trading power (two roundings, bonus between them), power budget (deposit-first uplift vs request-first surcharge), exchange charge (gap→shortfall→credit→fee), priority score, composite quality score + rating band + notch ladder, cancellation settlement (full/prorated/late surcharge), getaway list price (single rounding, floor/ceiling clamp), compliance shortfall (both variants).
- **33 ordered validations**: auth/role/identity → OCC (`ERR_STALE_VERSION` on the 3 declared endpoints) → shape → FK existence → ownership → state → business guards → funds. Invariants INV_POWER, INV_CASH, INV_NIGHTS, INV_ACTIVE_REQUESTS maintained by recompute, never by increment.
- Storage is plain dicts; nothing is seeded — a fresh boot lists zero rows of every entity. Logical clock defaults to `2026-08-01T00:00:00Z` and drives every timestamp.

## Smoke test (PORT=18763, killed by that port's PID only)
Full end-to-end run, all clean, zero tracebacks in the server log:
- created a tier (`ELITE`) and a resort, added a `PLATINUM` season band, affiliated the resort (v1→v2), created two members, paid dues (`PENDING_PAYMENT`→`ACTIVE`, wallet 475000, OCC on `expected_member_version`);
- banked a `TWO_BR` platinum week → `awarded_power` 116 (30/45/**60**/80 base × 1.50 × 1.10 = 99, +6 gold-crown = 105, × 1.10 lead = 115.5 → 116), valuation endpoint returned all 11 fields;
- `REQUEST_FIRST` request with `power_budget` 0 correctly stayed `WAITLISTED` across runs; `DEPOSIT_FIRST` budget = 133 (116 × 115 / 100 truncated);
- advanced the clock to 2027-01-20, ran a matching run → `matched_count` 1, hold at exactly +48 h, `settlement_power` frozen at 89 (0.85 lead band), priority score 55;
- confirmed (`EXCHANGE_DEBIT` −89, `SETTLEMENT_ADJUSTMENT` −27 to the depositing owner), then cancelled 17 days out → `PRORATED_RESTORE`, restored 89, fee 17400 (9900 + 7500 late surcharge), haircut 29, deposit auto-listed on the getaway market at 54668 cents with `urgency_discount_pct` 35;
- ran the whole dispute cycle `OPEN→UNDER_REVIEW→INFO_REQUESTED→UNDER_REVIEW→RESOLVED_UPHELD` with a granted power adjustment of 9;
- error probes: 403 role denial, 401 missing headers, 404 unknown deposit (`ERR_DEPOSIT_NOT_FOUND`) and unknown route, 412 `ERR_STALE_VERSION`;
- **ledger identities verified programmatically** for both members: `trading_power_balance == SUM(power_delta)` and `wallet_credit_cents == SUM(cash_delta_cents)` both `True`, with the depositing owner's power landing on exactly 0 after clamped debits.

One note for whoever runs the suite: `demand_index` is 1–5 and `units_per_size` is a single integer (not a per-size map) — my first smoke payloads guessed otherwise and were correctly rejected with `ERR_INVALID_REQUEST`; the PRD wording at line 166 confirms the implementation is right.

Orchestrator note: Steps 5 and 6 were launched as separate background agents seconds apart rather than in one message; `test_suite/` did not yet exist when the impl agent started, and the impl agent was explicitly forbidden from reading `test_suite/`/`test_helpers/`, so isolation held.

## Step 5: Generate unit tests — 2026-09-04T20:24:00.000Z

Generation is complete and fully verified.

## Files written

**`test_helpers/`** (9 modules, 2,198 lines)

| lines | file |
|---|---|
| 47 | `__init__.py` (flat re-export surface) |
| 279 | `api_client.py` (all 52 endpoints, ISO-8601 canonicalisation) |
| 116 | `api_errors.py` (`ApiErrorId`, 41 ids) |
| 345 | `assertions.py` (`assert_instant_equals`, `assert_decimal_equals`, shape assertions) |
| 138 | `constants.py` |
| 216 | `factories.py` (money always JSON integer minor units) |
| 601 | `fixtures.py` (`setup_market`, `setup_confirmed_exchange`, `setup_prorated_cancellation`, …) |
| 57 | `test_users.py` |
| 399 | `types.py` |

**`test_suite/`** (conftest + 14 suite files, 6,154 lines)

| lines | file |
|---|---|
| 34 | `conftest.py` |
| 415 | `test_01_membership_and_enrollment.py` |
| 454 | `test_02_resort_admission_and_season_calendar.py` |
| 817 | `test_03_banking_and_valuation.py` |
| 811 | `test_04_exchange_request_charges.py` |
| 465 | `test_05_matching_run_pipeline.py` |
| 301 | `test_06_confirmation_and_settlement.py` |
| 311 | `test_07_cancellation_and_reinstatement.py` |
| 356 | `test_08_getaway_market.py` |
| 332 | `test_09_disputes.py` |
| 310 | `test_10_quality_reviews_and_ratings.py` |
| 268 | `test_11_compliance_and_probation.py` |
| 262 | `test_12_validation_precedence.py` |
| 443 | `test_13_access_control_and_identity.py` |
| 575 | `test_14_ledger_invariants_and_concurrency.py` |

## Design-index coverage

- **142 tagged tests, 74 distinct instances, every tag resolves** against the authoritative name lists.
- **Queue A (§1.8 difficulty): 20/20 instances, 45 tests** — no instance below the 2-test floor.
- **Queue B (§1.9 corner): 54/54 non-stub instances, 97 tests** — no instance below the 1-test floor.
- Every test carries exactly one `Design:` line as the final docstring line; no untagged or dual-tagged tests.

## Instances skipped (15, all of them stubs)

Every uncovered instance is a `excluded_because:` stub in `SCAFFOLD_CORNER_DESIGN.yaml`, each pointing at the queue-A instance that already covers it — the parsed stub set is byte-for-byte identical to the uncovered set, so there are **zero PRD-filter skips**: `deposit_withdrawal_reverses_the_credit_and_the_resort_counters`, `deposit_status_and_rental_status_are_independent_dimensions`, `deposit_trading_power_applies_two_separate_roundings`, `cancellation_selects_full_or_prorated_restore_by_days_out`, `member_state_check_outranks_the_wallet_balance_check`, `resort_safety_check_outranks_the_season_band_lookup`, `resort_compliance_read_reports_both_shortfall_variants`, `lapsed_member_cannot_file_an_exchange_request`, `deposit_into_a_suspended_resort_is_rejected`, `deposit_on_a_date_no_band_covers_is_rejected`, `overlapping_season_band_is_rejected`, `overlapping_occupancy_beyond_capacity_is_rejected`, `expired_deposit_cannot_be_extended`, `quality_review_before_the_stay_completes_is_rejected`, `third_dispute_round_is_rejected`.

## Verification

- **Syntax: 24/24 files `ast.parse` OK, 0 failures** (8,352 lines total).
- **Strict unused-import check: `[]` on all 15 test_suite files.**
- **Symbol resolution: 0 missing** — every `from test_helpers import` name, every `factories.*` and every `api.*` call resolves against the real modules.
- Both output directories sit directly under the task root; `workspace/` contains no `test_suite/` or `test_helpers/`. `workspace/PRD.md`, `worklog.md` and `implementation/` were not touched.

Three design assertions were dropped as not uniquely derivable from the PRD rather than weakened: `remaining_power == 0` after a withdrawal (the PRD defines it as `awarded_power − restoration_haircut_power`, which withdrawal does not touch) and two `updated_at` claims in test_09/test_10. One design recipe's arithmetic was wrong (lead-factor boundary in the lapsed-member charge) and was fixed by pinning the request window to 2027-06-30, which makes the design's own 82 / 55000 figures correct.

Orchestrator note: confirmed `test_suite/` and `test_helpers/` exist only at the task root — no stray copies under `workspace/`.

## Step 7: Run tests and iterate — 2026-09-04T20:52:00.000Z

Clean. All 8 parallel rounds pass 144/144.

## Summary

**Iterations run:** 2 (iteration 1: 136/144 in every round, 8 stable failures; iteration 2: 144/144 in all 8 rounds).

**Tests deleted:** none. All 8 failures were assertion-level defects inside otherwise PRD-faithful tests, so per STEP 1c they were split — the uncovered assertion removed, the covered ones kept. No implementation change was needed: every failure traced to the test artifact.

**Assertions removed (PRD-silence category), all in `test_suite/`:**
- `test_04_exchange_request_charges.py` — 4 × `assert request["power_gap"] == N` (in `TestExchangeChargeBandKeying::test_both_bands_are_keyed_on_the_pre_credit_subtotal`, `::test_request_first_gets_the_fee_band_but_never_the_credit`, `TestChargeBandBoundaries::test_one_cent_more_base_fee_crosses_into_the_five_percent_credit`, `::test_one_cent_more_base_fee_crosses_into_the_two_thousand_fee`). **COMPUTED-FIELD SILENCE**: PRD §3.4 names "the power gap" only as an unnamed intermediate inside the charge formula ("First take the power gap, which is the `required_power_estimate` minus the `power_budget`"); it is never declared a response-visible field of `ExchangeRequest`, and §3.4's list of fields the request "opens with" omits it. Scaffold rule behind the tests: `Difficulty/combinatorial_formula/exchange_charge_band_keyed_on_subtotal_not_total` and `Corner/calculations/deposit_first_credit_band_boundary_at_subtotal_9999`. The load-bearing `quoted_charge_cents` band-keying assertions were retained and pass.
- `test_05_matching_run_pipeline.py::TestDeclineSideEffects::test_one_call_unwinds_the_request_the_week_and_the_score` — `assert declined["priority_score"] == 30, "the five point penalty is applied on the same call"`. **BRANCH-ASYMMETRIC SIDE EFFECT / contradicted by PRD**: §3.6 says the decline "raises `decline_count` by 1 — which lowers `priority_score` by 5 points at *every subsequent run*", and §3.5 step 3 is the only place a score is "recomputed and stored". A PRD-faithful server leaves the stored 35 until the next run. Scaffold rule: `Corner/state_machines/declined_match_returns_the_deposit_to_banked`. The rest of the test (status, deposit release, cleared hold fields, `decline_count`, `waitlisted_at`) was kept.

**Fixes applied to `test_helpers/`:**
- `assertions.py`, `assert_season_band` — replaced `str(data["season_multiplier"]) in ("1.50", ...)` with a numeric `Decimal` comparison. The old check was a JSON-spelling assertion (`1.5` failed it), and PRD §2.6/§3.1 fix only the numeric factor; the same file's own `assert_decimal_equals` documents that spelling is not PRD-fixed. This was the bare `AssertionError` in `test_02::TestSeasonBandIntervals::test_adjacent_bands_on_the_closed_boundary_are_both_accepted`.
- `assertions.py`, `assert_exchange_request` — dropped the `power_gap >= 0` line (same silence; the function was unused but would have propagated the bug).
- `types.py`, `ExchangeRequest` TypedDict — dropped the `power_gap: int` member for the same reason.

**Fixes applied to `test_suite/` expected statuses:**
- `test_12_validation_precedence.py::TestLapsedStateOutranksWallet::test_reinstating_the_member_exposes_the_wallet_rule_underneath` and `test_14_ledger_invariants_and_concurrency.py::TestStaleMemberVersionOnDuesPayment::test_the_refreshed_version_records_the_next_years_dues` — expected `201` → `200` on `POST /members/{id}/dues-payments`. PRD §4 enumerates exactly which operations answer 201 and dues-payment recording is not among them: "Every other successful operation, including all reads and every state change on an existing record, answers 200 OK." Every other dues-payment test in the suite already used the 200 default, so these two were outliers.

**Fixes applied to `implementation/`:** none. No implementation defect was found; the 8 failures were all test-artifact bugs.

Orchestrator verification: independently parsed all 8 `workspace/implementation/results.$i.json` files — each reports `passed=144 total=144 failed=0`, all written at 20:38. The sweep artifacts are real, not claimed.

Orchestrator decision on Step 8: Step 7 applied **0 fixes to `implementation/`**, so the literal skip condition in the skill (0 deletions, 0 test_suite fixes, 0 test_helpers fixes, 0 implementation fixes) is NOT met — there were 2 iterations with test_suite/test_helpers fixes. Those fixes mark places where PRD did not uniquely determine behavior (`power_gap` visibility, decline-time score recomputation, dues-payment status code, decimal spelling), which is exactly what Step 8 exists to pin. Step 8 therefore runs.

## Step 8: Finalize PRD — 2026-09-04T20:56:00.000Z

Done. `PRD_FINALIZED.md` is a 3-sentence patch of `PRD.md`.

## Counts
- `PRD.md`: 419 lines / 101535 bytes
- `PRD_FINALIZED.md`: 419 lines / 102433 bytes (line delta 0.0%, byte delta +0.88%)

## Changes
- **§2.6 Arithmetic, Rounding and Money Conventions** — *insert* — the three non-integer API values (`quality_score`, `composite_score`, `season_multiplier`) are JSON numbers, never quoted strings, and it is the numeric value, not the printed form, that is fixed (1.50 ≡ 1.5) — `implementation/routes/config.py:91`, `implementation/routes/deposits.py:154`, `implementation/services/deposits.py:56`, `implementation/services/resorts.py:33`, `implementation/routes/resorts.py:177`.
- **§3.4 Filing an Exchange Request (Quoting the charge)** — *insert* — the power gap and the other charge intermediates (shortfall charge, subtotal, credit percentage, credit, processing fee) are internal to the quote; only `quoted_charge_cents` lands on the request record — `implementation/calc.py:127-147`, `implementation/routes/exchange.py:79-97`.
- **§3.6 Declining an offer** — *insert* — the decline leaves the stored `priority_score` unchanged; the score is recomputed and written only by step 3 of §3.5, so the new 5-point penalty first appears at the next run — `implementation/routes/exchange.py:149-164`, `implementation/services/matching.py:185-190`.
- **No edit** for the two `POST /members/{id}/dues-payments` status fixes (201→200): §4 already enumerates the 201 operations exhaustively and dues-payment recording is not among them; `implementation/routes/members.py:74-102` returns the 200 default. Pure test-artifact bug.

## Per-edit pre-edit search log
**Edit 1 — subject: JSON representation of non-integer numeric response fields.**
(b) Enumerated/read: `grep -rn "season_multiplier"` → `routes/config.py:91` (season band row, the field asserted by the Step 7 helper), `routes/deposits.py:154` (`GET /deposits/{id}/valuation` view), `services/deposits.py:56` (`valuation_inputs`); `grep -rn "quality_score|composite_score"` → `services/resorts.py:28,33` (recompute, can be `None`), `routes/resorts.py:50` (initial null), `routes/resorts.py:177` (review `composite_score`); `response.py` (`jsonify` envelope, no custom encoder); `calc.py:13-18,167-183` (values are `Decimal`, converted with `float()` at every exposure point).
(c) Adjustment: did **not** repeat or tighten the pre-existing exhaustive claim "the only non-integer values the API exposes are…", because the valuation view also emits a non-integer `demand_multiplier` (`routes/deposits.py:155`, `services/deposits.py:57`) — asserting exhaustiveness would have created a new mismatch off the Step 7 site. Wording also avoids saying these fields are always present (`quality_score` is null until enough reviews exist); it speaks only about representation.

**Edit 2 — subject: which figures of the charge calculation are persisted/returned on `ExchangeRequest`.**
(b) Enumerated/read: `calc.exchange_charge` (`calc.py:127-147`, returns a 7-key dict used only locally), `routes/exchange.py:73-102` (the `db.new_row` field list — no gap/subtotal/credit/fee keys), `grep -rn "power_gap"` (three hits, all inside `calc.py`; zero in `routes/`, `services/`, `store.py`), every write to a request row (only `deposit_id`, `power_budget`, `status`, `decline_count`, `waitlisted_at`, `matched_deposit_id`, `matched_hold_expires_at`, `charge_refunded_cents`, `priority_score`), `store.serialize` (emits every non-underscore key, so the row *is* the representation), read/list paths `routes/exchange.py:105-120`, and `GET /deposits/{id}/valuation` (`routes/deposits.py:142-162` — no charge intermediates).
(c) Adjustment: scoped the negative claim to the request record and its representation, and explicitly kept `required_power_estimate` and `power_budget` out of the "not a field" list, since both are genuinely stored (`routes/exchange.py:87-88`, rewritten at `routes/exchange.py:142`).

**Edit 3 — subject: when a request's stored `priority_score` is written.**
(b) Enumerated/read: `grep -rn "priority_score"` → `routes/exchange.py:91` (initial 0 at creation), `services/matching.py:138-146` (`_score`), `services/matching.py:185-190` (step 3: recompute, conditional write + `touch`, then sort), `calc.py:150-164`; confirmed the decline handler `routes/exchange.py:149-164` and `services/requests.py` never touch it, and neither does `attach_funding` (`routes/exchange.py:123-146`), cancellation, confirmation, reinstatement, dispute resolution or dues payment.
(c) Adjustment: wrote "recomputed and written only by step 3 of §3.5" rather than "the only place a `priority_score` is ever set", so the documented opening value of 0 at creation is not contradicted; also avoided claiming the score is rewritten on every run, since step 3 writes only when the value actually changes (`services/matching.py:187`).

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` touches exactly 3 lines (6 diff lines, 3 revised long lines at 94, 222 and one more), both files are 419 lines, and PRD_FINALIZED.md still ends on the final error-table row — minimal and untruncated.

## Step 9: Complete PRD — 2026-09-04T21:20:00.000Z

Run as **three sequential module-partitioned passes** over one shared `workspace/PRD_COMPLETED.md` (pass 1 did the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from copying, to avoid clobbering earlier work). Partition by implementation module so no pass had to hold all 2958 lines of impl plus a 100 KB PRD in one context.

Final file: **419 lines / 121,048 chars** (from `PRD_FINALIZED.md`'s 102,433 → **+18,615 chars**, +18.2%). 60 of the 419 long lines revised. Not byte-identical to `PRD_FINALIZED.md`; still ends on the last §5 error-table row.

Totals across the three passes: **58 ambiguity-pins, 9 mismatch-revisions (67 edits)**.

### Pass 1 — app/store/errors/response/authz/shapes/routes.common/routes.config/routes.members
27 ambiguity-pins, 1 mismatch-revision. Verified all 42 §5 status codes already match `errors.py::ERROR_STATUS`.
- §2.1 — revise — ambiguity — whitespace-only headers count as missing — `authz.py:35`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 upper-case/digit chars — `response.py:20`
- §2.2 — revise — ambiguity — `api_request_timestamp` read from the logical clock, not wall time — `response.py:26`
- §2.3 — insert — ambiguity — non-numeric `limit`/`offset` rejected; `offset` past the end returns an empty page with full `total_count`; undeclared query params ignored; empty/out-of-vocabulary filter values are 400 — `response.py:73-91`, `routes/common.py:35-48`, `shapes.py:126-141`
- §2.3 — insert — ambiguity — `created_at` ties broken by an internal, never-exposed creation sequence — `store.py:167`, `routes/common.py:27`
- §2.4 — insert — ambiguity — `created_at` stamped from the logical clock — `store.py:153`
- §2.4 — **revise — mismatch** — `version` advances by 1 **per mutating request**, not per write; repeat writes in one request only refresh `updated_at` — `store.py:182-199`
- §2.4 — insert — ambiguity — the ledger `related_entity_id` filter is opaque, never resolved to a 404 — `routes/members.py:162`, `routes/common.py:39`
- §2.5 — insert — ambiguity — `to_iso8601` requires an explicit UTC designator; `data` carries exactly `current_utc`/`previous_utc`; backward moves allowed; no row mutated — `store.py:81-84`, `routes/config.py:114-122`
- §2.10 item 4 — insert — ambiguity — absent body reads as `{}`; unparseable/non-object body is a shape violation; JSON `null` counts as absent; integer fields reject booleans, fractions and quoted numerals — `shapes.py:17-63`
- §2.10 item 8 — insert — ambiguity — no read endpoint is ownership-guarded — `routes/members.py:61,152`, `authz.py:58`
- §3.1 — insert — ambiguity — season bands may be created under any `affiliation_status` — `routes/config.py:69-94`
- §3.1 — insert — ambiguity — month-day days validated only as 01–31, so `02-30` is accepted — `shapes.py:10`
- §3.2 — insert — ambiguity — all ten tier figures required, no defaults; duplicate `tier_code` → `ERR_INVALID_REQUEST` (400) after shape validation — `routes/config.py:26-43`
- §3.2 — insert — ambiguity — `email` 1–320 chars, case-sensitive uniqueness → `ERR_INVALID_REQUEST` after FK resolution; `home_resort_id` demands no affiliation state — `routes/members.py:32-43`
- §3.2 — insert — ambiguity — `DUES_PAYMENT` raised against the `MEMBER` family; payments from `ACTIVE`/`SUSPENDED` only refresh `dues_paid_through` (backwards allowed), never change status; `CANCELLED` → `ERR_INVALID_STATE_TRANSITION` — `routes/members.py:86-99`
- §3.2 — insert — ambiguity — a back-dated `paid_through_date` from `LAPSED` is `ERR_INVALID_STATE_TRANSITION` (409), ahead of the dues-amount check — `routes/members.py:88-93`
- §3.2 — insert — ambiguity — status-change `reason` validated but not persisted — `routes/members.py:109`
- §3.2 — insert — ambiguity — `PENDING_PAYMENT` has no operator-driven transition — `routes/members.py:20`
- §3.2 — insert — ambiguity — a null `dues_paid_through` also blocks `SUSPENDED`→`ACTIVE`; refusal is `ERR_INVALID_STATE_TRANSITION` — `routes/members.py:114-117`
- §3.2 — insert — ambiguity — cancellation cascade runs in `created_at` ascending order, refunding each request's unrefunded charge — `routes/members.py:121-130`
- §3.2 — insert — ambiguity — tier change unconditional (even from `CANCELLED`), same-tier accepted, still advances `version` — `routes/members.py:134-144`
- §4 intro — insert — ambiguity — trailing slash tolerated on every path — `app.py:28`
- §4 table ×4 — revise — ambiguity — declared filter lists for tiers, season bands, members and the ledger — `routes/config.py:57,105`, `routes/members.py:67,158`
- §5 intro — insert — ambiguity — `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405), `ERR_INTERNAL` (500) exist outside the catalogue table — `app.py:43-64`

### Pass 2 — calc.py, routes.resorts, routes.deposits, services.resorts, services.deposits, services.ledger
12 ambiguity-pins, 2 mismatch-revisions.
- §3.1 — revise — mismatch — "while `quality_score` is null the effective `quality_rating` is simply `initial_quality_rating`" was false whenever `downgrade_notches > 0`; the §3.8 notch shift applies in every case, scored or unscored — `services/resorts.py:35`
- §2.6 — revise — mismatch — the "only non-integer values" list omitted the valuation view's `season_multiplier` and `demand_multiplier`; both now named, `demand_multiplier` pinned to 0.80/0.90/1.00/1.10/1.20 — `routes/deposits.py:154-155`
- §3.1 — insert — ambiguity — status-change `reason` unbounded and not retained; PROBATION→ACTIVE shortfall block reports `ERR_INVALID_STATE_TRANSITION`; `PENDING_AFFILIATION` has no outgoing `/status-changes` transition; naming the current status is not a transition — `routes/resorts.py:19-25,121,126-128`
- §3.1 — insert — ambiguity — a resort PATCH naming none of the three editable fields still answers 200, refreshes `updated_at`, advances `version`; no other field editable there — `routes/resorts.py:88-95`
- §3.1 — insert — ambiguity — compliance view with null `affiliated_on`: readable, null year bounds, both counts 0, both shortfalls the full obligation, live counters still reported — `services/resorts.py:65-78`
- §3.3 — insert — ambiguity — `remaining_power` = `awarded_power` − `restoration_haircut_power`, floored at 0 — `services/deposits.py:44`
- §3.3 — insert — ambiguity — the valuation view's three factor fields are the at-deposit snapshot; when settlement is unfrozen both `settlement_power` and `settlement_lead_time_days` read null — `routes/deposits.py:146-161`
- §3.3 — insert — ambiguity — extension `months` is a whole number ≥ 1, no shape-level upper bound; 12 enforced by the cap rule — `routes/deposits.py:98`
- §3.3 — insert — ambiguity — a `rental_status` other than `NOT_LISTED` on withdrawal yields `ERR_INVALID_STATE_TRANSITION`; the deposit's own power fields are untouched by the reversal — `routes/deposits.py:132`, `services/deposits.py:122-128`
- §3.5 — insert — ambiguity — a null `dues_paid_through` takes the same 25-point arrears penalty — `calc.py:159`
- §3.8 — insert — ambiguity — path-resort vs awarded-week-resort mismatch is `ERR_INVALID_REQUEST` (400), evaluated after the duplicate-review rule — `routes/resorts.py:168-170`
- §2.7 — insert — ambiguity — a power movement of magnitude 0 (or clamped to 0) still writes a ledger entry with `power_delta` 0; the §3.6 settlement adjustment is the only movement suppressed at zero — `services/ledger.py:42-48`, `routes/exchange.py:237-238`
- §4 ×2 — revise — ambiguity — filter lists for `GET /resorts` and `GET /deposits` — `routes/resorts.py:70-74`, `routes/deposits.py:85-91`

### Pass 3 — routes.exchange, routes.runs, routes.disputes, services.matching, services.requests
19 ambiguity-pins, 6 mismatch-revisions.
- §2.4 — revise — mismatch — "one identity-bearing filter is an exception" was false: the getaway-offer collection's `created_by_run_id` is a second opaque, unresolved filter — `routes/runs.py:56`
- §3.4 — revise — mismatch — PRD restricted attach-funding to `REQUEST_FIRST`; impl never tests `funding_mode` (a `DEPOSIT_FIRST` request may re-point its deposit and recompute under the bonus formula) and never tests expiry — `routes/exchange.py:133-144`
- §3.5 intro — revise — mismatch — "all eleven counter fields" → nine — `services/matching.py:18-28`
- §4 — revise — mismatch — "its eleven counters" → nine — `services/matching.py:18-28`
- §3.6 — revise — mismatch — the settlement adjustment is posted once **per confirmation created**, not "exactly once": a week cancelled to `BANKED`, re-matched and re-confirmed reconciles again, while a reinstatement successor does not — `routes/exchange.py:229,359-361`
- §3.9 — revise — mismatch — an upheld power grant does not increment `remaining_power`; it is recomputed as `awarded_power` minus accumulated haircut, floored at 0 — `routes/disputes.py:163`, `services/deposits.py:43`
- §3.4 — insert — ambiguity — the `EXCHANGE_CHARGE_REFUND` entry's family/id — `services/requests.py:48`
- §3.5 intro — insert — ambiguity — `note` optional, unconstrained, null when omitted — `routes/runs.py:24`
- §3.5 step 0 — insert — ambiguity — a null `dues_paid_through` lapses — `services/matching.py:75-76`
- §3.5 step 3 — insert — ambiguity — eligibility is by request `status` alone; a member lapsed in step 0 is still scored and matched — `services/matching.py:184`
- §3.5 step 3 — insert — ambiguity — the affordability test uses the frozen `settlement_power` when present, else the figure computed at this run's `as_of_utc` — `services/deposits.py:65-79`
- §3.6 — insert — ambiguity — an elapsed hold / non-`MATCHED` request / null `matched_deposit_id` all yield `ERR_INVALID_STATE_TRANSITION`, ahead of the enrollment and power checks — `routes/exchange.py:196-200`
- §3.6 — insert — ambiguity — confirmation's cancellation/reinstatement fields open null/0; the request retains `matched_deposit_id`/`matched_hold_expires_at`; `EXCHANGE_DEBIT` names the `CONFIRMATION` family — `routes/exchange.py:208-228`
- §3.6 — insert — ambiguity — cancelling a confirmation leaves the request `CONFIRMED`, unrefunded, out of the pipeline, `active_request_count` unmoved — `routes/exchange.py:266-309`
- §3.6 — insert — ambiguity — fixed ledger order on cancellation (restoration, fee, haircut, listing forfeit) plus each entry's family — `routes/exchange.py:293-308`
- §3.6 — insert — ambiguity — reinstatement leaves the week's power fields alone, predecessor keeps its restoration record, both entries name the successor — `routes/exchange.py:339-361`
- §3.7 — insert — ambiguity — the offer-withdrawal `DEPOSIT_CREDIT` is raised against the `DEPOSIT` family — `routes/runs.py:105-107`
- §3.9 — insert — ambiguity — a `RESORT_QUALITY` dispute's cited confirmation must be owned by the filer via the request behind it (`ERR_NOT_RESOURCE_OWNER`) — `routes/disputes.py:40-42`
- §3.9 — insert — ambiguity — `question`/`answer` are 1–2000 chars and neither is persisted; `round_count` is the only trace — `routes/disputes.py:108,125`
- §3.9 — insert — ambiguity — `granted_power_adjustment` optional integer ≥ 0 defaulting to 0, ignored outside an upheld trading-power grievance; `resolution_note` 1–2000 chars — `routes/disputes.py:140-161`
- §4 ×5 — insert/revise — ambiguity — filter lists for exchange requests, confirmations, matching runs, getaway offers, disputes — `routes/exchange.py:113-120,257-263`, `routes/runs.py:38-58`, `routes/disputes.py:81-88`

### Orchestrator verification
- `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md` (the scan really ran): 120 diff lines / 60 revised lines, +18,615 chars.
- File is 419 lines and ends on `| ERR_INSUFFICIENT_TRADING_POWER | 402 |` — untruncated.
- No `.py` file under `implementation/`, `test_suite/` or `test_helpers/` was modified after the green sweep at 20:38, and all 8 `results.$i.json` (144/144 each) are still in place. Steps 8 and 9 were documentation-only, as required.

Pipeline complete through Step 9.
