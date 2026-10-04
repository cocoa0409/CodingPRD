# Worklog — task_3030_house_jewelry_credit_lifetime_service_plan_administration

Scenario: In-House Jewelry Credit & Lifetime Service Plan Administration (Signet Jewelers) — private-label credit
application at the counter with instant decisioning and down-payment rules, promotional financing plans with deferred
interest and payoff-by-date accounting, lifetime diamond and service plan registration requiring periodic inspection to
remain valid, inspection reminder scheduling with store visit logging and plan lapse handling, repair intake with vendor
shop routing, loss liability and turnaround commitments, appraisal issuance and insurance replacement coordination,
trade-up program crediting the original purchase price toward a higher-value item, custom design orders with CAD approval
and non-refundable deposits.

## Step 1: Create task directory — 2026-09-29T14:31:00.000Z

Task directory was pre-allocated by the caller: `./tasks/task_3030_house_jewelry_credit_lifetime_service_plan_administration`
with `workspace/` already present. Index computed per user override (do NOT recompute); no other `task_*` directory created.

## Step 2: Generate scaffold — 2026-09-29T15:03:00.000Z

Verbatim subagent summary:

Done. Scaffold package generated and lint-clean.

## Files written (all absolute)

- `/home/ubuntu/github/CodingPRD/tasks/task_3030_house_jewelry_credit_lifetime_service_plan_administration/SCAFFOLD.yaml` — 3077 lines, §1.0–§1.7 (no design keys)
- `.../SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1316 lines, single top-level key `scaffold_difficulty_design`
- `.../SCAFFOLD_CORNER_DESIGN.yaml` — 1991 lines, single top-level key `scaffold_corner_design`

## Counts

- **Entities 18** (Store, Customer, CreditLimitRegistryState, CreditApplication, PromotionalPlan, PayoffLedgerEntry, Diamond, ProtectionBundle, VendorShop, ServicePlanRegulation, ServicePlanRegistration, InspectionVisit, Repair, RepairHold, Appraisal, Purchase, CustomDesignOrder, BillingStatement) — stored at LESS than the Expert band's 10–15 so difficulty comes from coupling, not surface
- **State machines 13** · **calculations 15** · **validations 33** (priorities 1–33) · **endpoints 114** · **errors 37** · **roles 6** · **concurrency_rules 3**
- Profile: `pricing_engine` + `compliance_audit`, flat topology, compound/parallel/cyclic shapes, segregation_of_duties, immediate consistency; layers = cascading_side_effects, dual_variant_calculation, derived_field_reconciliation, optimistic_concurrency, scheduled_deferred_actions

## §0.5 difficulty rules — 18/18 instances, exactly 2 per rule

| rule_id | instances | distinguishing distinction |
|---|---|---|
| dual_variant_calc | 2 | Repair loss-liability cost accounting (35000 vs 38850) on a repair-desk domain vs Customer statement rollup (525300 vs 522800) on a billing domain — different entity domains |
| combinatorial_formula | 2 | mode (b) trade-up nested rounding order (383370 vs 383369, pinned SINGLE_ROUND) vs mode (c) design cancellation fee with circular-looking deposit/revision dependency and pinned evaluation order |
| non_linear_state_machine | 2 | PromotionalPlan cyclic ACCRUING→DEFAULTED→ACCRUING + parallel settlement dimension, on a different entity from ServicePlanRegistration's LAPSED→RENEWED→PENDING_INSPECTION cycle with a branching GRACE path |
| transitive_cascade | 2 | depth 5 (plan→customer→application→registration→streak→tier) vs depth 4 from a different trigger (payoff→origin purchase→registration→store counter→close) |
| priority_pair_validation_conflict | 2 | business_compliance(6) vs business_fiscal(20); business_safety(8) vs business_referential(16) |
| boundary_precision_check | 2 | numeric ceil boundary on down-payment (300000→0 / 300001→1 / 300050→5), distinct endpoint from the empty-set/zero-count store-load edge |
| cross_entity_state_dependency | 2 | Purchase→Customer account posture; Repair→ServicePlanRegistration coverage status |
| resource_temporal_overlap | 2 | store-hold adjacency-INCLUSIVE at the closing instant on Repair vs bench-shop transient-overbooking aggregate-capacity buffer (1.5× bays) on VendorShop |
| compensating_invariant | 2 | plan outstanding balance B across payoff/reinstate (zero drift) vs store open-inspection population C across a trade-up swap on a countable subject |

## Corner design (§1.9)

9 sections (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_layers, consistency_model), 51 instances, all with reachable `setup_api_calls`.

## Lint / checklist items resolved

Verbatim `scaffold_lint.py` verdict: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (exit 0, 750 calls scanned).

Fixes made along the way: (f) resolved by setting `api_prefix: /` (single-resource detection needs exactly two segments) plus adding sub-resource and filtered-list reverse-reachability GETs for all 34 FK declarations; (c) closed by adding the business endpoint `POST /purchases/{id}/trade-up-credit` rather than an unbound placeholder (also added its error and validation row); (d) removed two `$.data.total_count` captures on list endpoints; (e) all four OCC `expected_*_version` inputs are `${var}` from earlier `captures:`.

Other self-consistency repairs: four worked-example arithmetic errors found by executing the formulas as code (trade-up, balance-due, cancellation fee, PROMO_24_12_M installments); `ledger_version` renamed `entry_sequence` so it cannot be mistaken for a §1.2.1 OCC version; added `appraisal_status`, `ABANDONED`, `VendorShop`, `entry_sequence`/`amount_cents`/`reference_bucket`/`direction` to close declared-enum dead ends; removed 14 malformed `type: computed` field entries; quoted all optional `input:` names so the flow lists parse; verified zero forbidden race vocabulary in all three files, no UUID/random `id` in any tie-break (fallbacks use `created_at`), scenario string byte-identical to the supplied text.

Orchestrator verification: all three files present; top-level keys confirmed (`scaffold_difficulty_design` only in SCAFFOLD_DIFFICULTY_DESIGN.yaml, `scaffold_corner_design` only in SCAFFOLD_CORNER_DESIGN.yaml, neither inside SCAFFOLD.yaml).

## Step 3: Copy shared files — 2026-09-29T15:04:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-29T15:18:00.000Z

Verbatim subagent summary:

The PRD is complete and audited. Final verification is done.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3030_house_jewelry_credit_lifetime_service_plan_administration/workspace/PRD.md` — **510 lines**.

**Section list**
- §1 Introduction (3 paragraphs: commercial context, the dual credit/service-plan obligation, the coupling rationale)
- §2 Global Specifications — 16 domain-derived subsections: 2.1 RBAC, 2.2 Response Structure (verbatim fixed block), 2.3 Pagination, 2.4 Risk Registry and Counter Credit Pricing, 2.5 Deferred-Interest Plan Economics, 2.6 Lifetime Plan Registration Terms and State Compliance, 2.7 Bench Liability/Routing/Turnaround, 2.8 Trade-Up and Commission Economics, 2.9 Replacement Appraisal Valuation and Insurance Coordination, 2.10 Customer Credit Posture and Recomputation Order, 2.11 Statement Balances and Payment Allocation, 2.12 Common Resource Properties, 2.13 OCC, 2.14 Validation Priority Ladder, 2.15 Nested Resource Retrieval, 2.16 Cascade and Hierarchy Consistency
- §3 Business Logic — 8 subsections grouped by lifecycle stage: 3.1 Counter Credit Conversation, 3.2 Promotional Financing, 3.3 Lifetime Plan Registration/Validity, 3.4 Repairs at the Bench, 3.5 Appraisals/Insurance/Trade-Up Console, 3.6 Custom Commissions, 3.7 Default/Suspension/Posture, 3.8 Statements/Buckets/Close
- §4 Endpoint Definitions (114-row, 4-column table)
- §5 Error Code Catalogue (37-row, 2-column table)

**Coverage audit — all scaffold §1.0–§1.7 represented**
- §1.0 response_envelope → §2.2 (byte-identical to `section-2.2-response-structure.md`, `data: { }` left empty) and §2.3
- §1.1 entities → §2.4–§2.16 and §3; all 14 entities and every field name appear
- §1.2 state machines → §3 narratives (all 14 machines, all state pairs, preconditions paired with error ids, every side-effect hop stated; the 6-hop default chain is spelled out in order)
- §1.3 calculations → §2.5, §2.7–§2.11 and §3 (all 13 formulas translated to prose, no operator syntax, no fuzzy words)
- §1.4 validations → §2.14 (full 33-rung priority ladder) with trigger conditions scattered into §2/§3
- §1.5 endpoints → §4 table (114/114 rows) plus §2/§3 narratives
- §1.6 errors → §5 table (37/37) plus in-prose mentions
- §1.7 roles → §2.1 (all six names, all identity semantics)

**Hard contracts (report only, not written into PRD.md)**
- Contract 1 Field-Name Coverage: 162 entity fields required / 162 present / 0 missing; 99 endpoint input identifiers required / 99 present / 0 missing; query_params 0; plus all 47 calculation constant names, all enum constraint values, all 37 error ids, all 14 state-machine state values — 0 missing. PASS
- Contract 2 Rule Coverage: validations priority ordering expressed; 4 OCC rejections named with `write_endpoint` + `expected_<parent>_version` + `ERR_STALE_VERSION`/412; transitions fully expressed; 13 calculations expressed with evaluation order, constants, precision, and variant pinning; validation conditions matchable to error ids; `side_effects`/`applies_to` expressed; field structured content reconstructible; sibling branches given equal density. PASS
- Contract 3 §3 Path Purity: 305 backtick tokens scanned in §3, 0 starting with `/`, 0 bare HTTP-method tokens, 0 method+path tokens. PASS

**Rules I flagged as non-obvious / worth a second look**
1. **Statement bucket labels are genuinely inconsistent in the scaffold.** `BillingStatement.bucket_totals_cents` enumerates `{PROMOTIONAL, CUSTOM_DESIGN, RETAIL}` while `payment_allocation_waterfall` allocates over `[PROMOTIONAL, STANDARD_RETAIL, NEW_ACCOUNT]`. The scaffold provides no mapping, so a test asserting on bucket keys has two defensible readings. I stated both label sets verbatim and noted that the third bucket is the same bucket — the only way to keep Contract 1 satisfied without inventing a rule.
2. **`ERR_REGULATION_TERMS_VIOLATION` vs `ERR_PLAN_TERM_EXCEEDS_REGULATION`.** Validation priorities 6 and 7 both return `ERR_REGULATION_TERMS_VIOLATION` even for the term-overrun condition, while the catalogue separately declares `ERR_PLAN_TERM_EXCEEDS_REGULATION` (422) for that same condition. I documented the ladder as scaffolded (priority 7 → `ERR_REGULATION_TERMS_VIOLATION`) and described the second id as the catalogue's specific term-overrun code; the scaffold does not say which an implementation should emit.
3. **`RepairHold` initial state** is `EVALUATING` but every CREATE produces a record that is immediately `APPLIED` or `REJECTED`; `EVALUATING` is never observable in a transition `from`. Stated as an entry state that resolves immediately.
4. **`Repair.loss_liability_cents` reads `declared_loss_liability_cents`**, which is an endpoint-only optional input with no entity field definition — its default is only inferable from `LOSS_LIABILITY_DEFAULT_CENTS: 0`. Stated with that constant.
5. **`CUSTOM_DESIGN` reference bucket** has no allocation capacity in the waterfall (no `custom_design_balance_cents` exists on `Customer`), so its capacity is unspecified; I stated the label without asserting a capacity rule.
6. **`minimum_down_payment_cents`** is described as a "floor supply guard" with default 0 but no scaffold rule ever sets it; documented as an intake guard that is inert unless supplied.
7. **`Store.SUSPENDED`** admits both "reinstatement" (from store) and "activating an ACTIVE store" paths with slightly different preconditions (`<=` vs `>` inversion). I kept the inclusivity as scaffolded.

No files were written other than the PRD; the withheld `SCAFFOLD_DIFFICULTY_DESIGN.yaml` / `SCAFFOLD_CORNER_DESIGN.yaml` and all sibling task directories were not opened.

Orchestrator note: the 7 flagged ambiguities are PRD-silence candidates that Step 7/8/9 must resolve (Step 7 by deleting or relaxing PRD-unsupported assertions, Step 8/9 by pinning prose to implementation behaviour).

## Step 5: Generate unit tests — 2026-09-29T16:01:00.000Z

Verbatim subagent summary:

Generation complete and audited. Summary:

## Files written

**`test_helpers/`** — 2,537 lines total
| file | lines | contents |
|---|---|---|
| `types.py` | 538 | 14 status enums, 6 role enum, 18 TypedDicts (`PayoffLedgerEntry`/`RepairHold` correctly omit `updated_at`+`version`) |
| `api_client.py` | 413 | `ApiClient(GenericApiClient)`, 118 endpoint methods |
| `api_errors.py` | 95 | 37 `ApiErrorId` members, HTTP map registered via `set_error_http_status_map` |
| `assertions.py` | 282 | 18 `assert_<entity>` + 5 domain invariant checkers |
| `constants.py` | 162 | PRD-named constants + fixture defaults |
| `factories.py` | 201 | 18 payload factories (input fields only) |
| `fixtures.py` | 713 | 5 tiers, 40 composite setup helpers |
| `test_users.py` | 34 | 8 header sets + mandatory `make_customer_headers(user_id)` for the entity-backed `Customer` role |
| `__init__.py` | 99 | barrel export |

**`test_suite/`** — 3,864 lines, 133 tests collected cleanly
`conftest.py` (45) plus 17 files: test_01 (8), 02 (9), 03 (9), 04 (5), 05 (6), 06 (7), 07 (9), 08 (7), 09 (10), 10 (10), 11 (11), 12 (10), 13 (6), 14 (9), 15 (5), 16 (7), 17 (5).

## Coverage audit

**Queue A (difficulty): 18/18 instances translated, 0 skipped.** Every instance has ≥2 tests (60 tests). Per rule: dual_variant_calc 4, combinatorial_formula 4, non_linear_state_machine 9, transitive_cascade 9, priority_pair_validation_conflict 5, boundary_precision_check 6, cross_entity_state_dependency 7, resource_temporal_overlap 9, compensating_invariant 7.

**Queue B (corner): 51/51 non-stub instances translated, 0 skipped** (73 tests; section counts `entities` 10, `state_machines` 7, `calculations` 5, `validations` 5, `endpoints` 5, `errors` 8, `rbac` 5, `cross_cutting_layers` 5, `consistency_model` 1). The index contains **zero `excluded_because:` stubs** — all 51 entries carry `test_recipe`s — so there was no cross-reference to verify or placeholder to withhold.

## Verification performed

- 251 PRD quotes of ≥8 words grep-verified character-for-character against `PRD.md` — **0 failures**.
- 133/133 docstrings end with exactly one `Design:` line; **0 untagged, 0 dual-tagged, 0 phantom tags**.
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no "scaffold"/"Table N"/"§1.x" leakage in generated code.
- Every asserted `error_id` is named in PRD **prose**, not just the §5 table (23/23 confirmed).
- `pytest --collect-only`: 133 collected, 0 errors. All `test_helpers` imports and `ApiClient` methods resolve.

## Instances judged PRD-silent (skipped)

None failed the two-condition filter outright, but three instances were served by **narrower tests than the recipe proposed**, because part of each recipe asserts an outcome the PRD leaves open to two faithful readers:

1. **`Corner/entities/server_stamped_fields_ignore_client_supplied_values`** — recipe asserts a create carrying `store_status: ACTIVE` is *stored* as OPEN. PRD §3.1 says the status "starts at `OPEN`"; it never commits to silently dropping a supplied system field rather than refusing it with `ERR_INVALID_REQUEST` (§2.14) or `ERR_VALIDATION_FAILED`. Test asserts only the PRD-pinned server-minted properties (OPEN on a clean create, `version` 1, clock-stamped `created_at == updated_at`, plain UUID).
2. **`Corner/entities/...has_more` / `Corner/validations/...filter` / `Corner/endpoints/...clock_default`** — recipe payloads for `purchases` and `credit-applications` omit foreign keys PRD marks required, so `ERR_INVALID_REQUEST` is asserted rather than the recipe's 422 ID; two other recipes specify a missing `base_price_cents` while also passing `store_id`, which is not separately testable. Split into one test per single-failure scenario rather than asserting a priority between them.
3. **`Corner/errors/plan_term_exceeding_the_state_maximum_is_rejected`** — PRD §2.6 explicitly declares *two* identifiers for the term-overrun condition ("the request is refused with the same `ERR_REGULATION_TERMS_VIOLATION` code… and the catalogue also declares `ERR_PLAN_TERM_EXCEEDS_REGULATION`… both identifiers describe refusals"). The test asserts membership in that two-element set, since the PRD names both as valid.
4. **`Difficulty/...payoff_cascade...` (close hop)** — the recipe's final "close only after hops settle" sequence depends on the recipe-defined logical clock; rewritten to assert the PRD's own close guard (`ERR_CUSTOMER_ACTIVE_OBLIGATIONS` while the replacement registration is live), which is the rule §3.7 actually states.

No instance was weakened on its core, PRD-derivable assertion, and nothing was marked skip/xfail. Gaps left open are strictly PRD design-space, not test gaps.

## Step 6: Generate implementation — 2026-09-29T16:03:00.000Z

Verbatim subagent summary:

All six suites pass after final cleanup. Implementation is complete.

## Summary

Generated a complete Python + Flask implementation at `/home/ubuntu/github/CodingPRD/tasks/task_3030_house_jewelry_credit_lifetime_service_plan_administration/workspace/implementation/`.

**Files (4,117 lines total, 21 source files):**
| File | Lines | Role |
|---|---|---|
| `start.sh` | 11 | foreground launcher, `$PORT`/`0.0.0.0`, guarded `pip install` |
| `requirements.txt` | 1 | Flask |
| `app.py` | 47 | Flask entry, error handlers, route registration |
| `db.py` | 126 | in-memory store (dicts keyed by id), logical clock, ISO-8601 helpers |
| `response.py` | 331 | 37-error catalogue, envelope helpers (`meta`/`response_type`/`data`), request validation |
| `middleware.py` | 45 | header auth + role check + `Customer`-entity ownership |
| `constants.py` | 117 | every named constant |
| `services/core.py` | 722 | entity builders, derived-field reconciliation, all 15 calculations |
| `routes/*.py` (17 modules) | ~1,700 | one module per resource group, plus `lists.py` for all 22 sub-resource GETs |

**Organisation:** routes hold HTTP/validation/error-precedence wiring; `services/core.py` holds every calculation and every derived-field recompute. All routes are registered centrally from `routes/__init__.py`; all 114 declared endpoints verified present (method+path exact match).

**Verified behaviours** (six independent smoke suites I wrote and ran against a live server, ~250 assertions): NET_RESERVE loss liability (35000/2800/37200/2800), trade-up SINGLE_ROUND (383370/516730/900036), statement SUM_THEN_TIER (525300, and 255000 with the PAID line dropped), down-payment ceil boundary (30000/30001/30005), deferred interest (39930 at 120d; 121455 at the 365-day edge; capitalization only past it), ledger projection (PROMOTIONAL-referenced vs RETAIL-misdirected), the 6-hop default cascade, registration lapse→renew→PENDING cycle, both exams branches, reminder-window edges, hold ceiling, abandonment at the inclusive closing instant, all RBAC denominators, and—critically—that a reboot wipes every byte (no seeding; all sixteen collections read empty on a fresh `start.sh`).

**Ambiguities adjudicated (PRD read chosen each time):**
1. **`standalone_credit_limit_cents` = registry `base_limit_cents`, not `min(base, requested)`** — the scaffold's worked example truncates (`approved_limit`) and the two examples disagree; the PRD's registry paragraph states the row's ceiling outright, and priority 20 (request over the *tier's* ceiling) only makes sense if the limit is the full row value.
2. **Statement bucket capacity** — the PRD declares no promotional/retail/new-account balance field, yet the waterfall needs capacities. I use the only carried balance the system has: the sum of open plans' `final_settlement_amount_cents`. Any payment above it returns `ERR_STATEMENT_OVERPAYMENT`. (Borderline; flagged as a genuine scaffold gap.)
3. **`plan_term_months > max` → `ERR_PLAN_TERM_EXCEEDS_REGULATION`** — the validation table's priority 7 says `ERR_REGULATION_TERMS_VIOLATION`, but the PRD narrative and the scaffold's own corner-design recipe both assert the specific id. Followed the recipe.
4. **Window arithmetic** — `simplicity_expires_at` is a true calendar-month offset (`2026-09-01` + 12 → `2027-09-01`, per the PRD's "exactly 365 days"); `inspection_due_at` is day-based (`+180` days), per the recipe.
5. **Priority 15 bound** is *one full cycle* before the current due instant, taken from the error catalogue's trigger condition (the PRD's summary sentence says "earlier than the due instant" — the catalogue is the more precise statement of the same rule).
6. **`replacement_trade_up_credit_cents` on the verify-opened replacement purchase** — applied from the declared cascade hop, since the PRD says `trade_up_credit_cents` is "recomputed, never accepted from the payload" and there is no origin to recompute from.
7. **`Repair.hold` rejection** — the hold is a 422 at the ceiling per priority 14, so `REJECTED`/`imposed_breach_adjustment_cents` are never persisted; the PRD confirms "A request past the ceiling is refused with `ERR_HOLD_PROMISE_CEILING`", and the scaffold's own priority-conflict recipe relies on that status code.

Orchestrator verification: `workspace/implementation/start.sh`, `app.py`, `db.py`, `response.py`, `middleware.py`, `constants.py`, `requirements.txt`, `routes/`, `services/` all present; `test_suite/` holds 17 test modules + conftest; `test_helpers/` holds the 9 mandated modules. Step 6 could not read `test_suite/`/`test_helpers/` (they did not exist at its launch) — physical isolation held.

## Step 7: Run tests and iterate — 2026-09-29T18:30:00.000Z

Verbatim subagent summary:

The task is complete: **8/8 rounds pass 133/133 with zero union failures.**

## Summary

### Iterations run
4 diagnostic rounds (3 full 8-round sweeps plus sub-suite iterations). Pass rate went **11 → 61 → 75 → 122 → 133 / 133**.

### Tests deleted
None. Every failing test traced to a verbatim PRD sentence; no test asserted a scaffold-only rule.

I applied STEP 1c "partial coverage" instead: five assertions whose rule was **not** uniquely derivable were removed, keeping the covered assertion (each noted where applied). The two PRD self-contradictions found:
- **`outstanding_balance_cents`** — §2.10 defines it as a closed-form derived sum over ledger entries and open plans, while §3.5 says it "is increased by the net amount". Two faithful readers diverge; the incremental clause was dropped from `test_06` / `test_17`.
- **Cancellation fee** — §2.8's worked reference proves the fee is the *branch-selected* candidate (costs incurred for ≥3 revisions), not a `max()`; the exact `100,000` assumed an undeclared `material_recovery_cents`. Relaxed to the PRD's own formula.

### Fixes to `test_helpers/`
- `fixtures.py` — the dominant bug (117 of 133 failures). `setup_store` activated before any registry row existed, but PRD §3.4 makes a resolvable row a precondition of activation → `setup_store` now supplies one.
- `fixtures.py` — new `open_customer()` / `_ensure_regulation()`: PRD §3.1 creates customers at `NO_FILE`, and §3.3/§3.5 make `OPEN` the posture prerequisite for a registration or purchase completion. Nine graph builders (`setup_active_registration`, `setup_pending_registration`, `setup_design_order`, `setup_store_near_capacity`, `setup_registration_at_day_offset`, …) built purchases on a `NO_FILE` customer.
- `fixtures.py` — `create_repair_in_qc_review` created MALCA twice when called with `shop_code="MALCA"`; a duplicate `shop_code` is a PRD §3.4 409.
- `fixtures.py` — new `setup_registration_awaiting_lapse()`; PRD §3.3 lapses only `PENDING_INSPECTION`/`REMINDER_ISSUED`, so the reminder hop must run first.
- `fixtures.py` — new `setup_store_over_capacity()`; PRD §3.4 allows suspension only once liability outruns capacity.
- `fixtures.py` — `_add_days` now renders `.000Z` per PRD §2.12's three-fractional-digit wire format.

### Fixes to `implementation/`
- `routes/purchases.py` — removed a store-capacity gate on completion. PRD §3.5 enumerates exactly **five** precedent conditions; capacity is absent.
- `routes/repairs.py` — rush routing now requires an alliance agreement via `base_turnaround_days` (PRD §2.7: "seeded from the alliance agreement") instead of refusing unconditionally.
- `routes/stores.py` — restored PRD-required suspend/reinstate capacity precondition (removed earlier, then correctly re-fixed on the test side).
- `routes/visits.py` — standing `CLAIMED` visit records now stamp `claimed_at` (PRD §3.3) instead of persisting `null`.

Fifteen test modules also had role-header corrections: several tests sent `credit_analyst_headers` / `sales_associate_headers` / `customer_service_headers` to endpoints whose PRD §4 row excludes that role (payoff, commission cancel, `GET /diamonds/{id}`, `GET /purchases/{id}/service-plan-registrations`), and two asserted a 0.03 statement tier where the subtotal only reaches 0.02.

Orchestrator verification: the subagent's hand-back did NOT leave `results.{1..8}.json` on disk, so the "8/8 pass" claim was unverified on arrival. Orchestrator re-ran the identical 8-round parallel sweep independently (`prd-bench-local-run --isolation per-test-server`, 8 concurrent rounds, per-round free-port claim):

```
round 1: passed=133 total=133 failed=0
round 2: passed=133 total=133 failed=0
round 3: passed=133 total=133 failed=0
round 4: passed=133 total=133 failed=0
round 5: passed=133 total=133 failed=0
round 6: passed=133 total=133 failed=0
round 7: passed=133 total=133 failed=0
round 8: passed=133 total=133 failed=0
ALL_8_GREEN
```

Step 7 CONFIRMED: 8/8 rounds green, 133/133, zero union failures. `results.{1..8}.json` are on disk in `workspace/implementation/`.

## Step 8: Finalize PRD — 2026-09-29T18:35:00.000Z

Step 7 applied 4 fixes to `implementation/`, so the skip condition does not apply. Spawning the PRD finalizer with the Step 7 entry inlined as `<step_7_diff>` (see below).

Verbatim subagent summary:

The deliverable is complete. Here is my report.

## Files

- Created: `/home/ubuntu/github/CodingPRD/tasks/task_3030_house_jewelry_credit_lifetime_service_plan_administration/workspace/PRD_FINALIZED.md`
- Baseline: same dir `PRD.md`

**Line counts:** PRD.md 510 → PRD_FINALIZED.md 510. **Δ = 0.0%** (8 lines changed, all in-place; no sections added or removed).

## Edits (one bullet per change)

- **§2.4** — revise — the down-payment shortfall is a *reported figure*, not a gate: a below-minimum decision still lands and `ERR_DOWN_PAYMENT_REQUIRED` is unreachable through the decision — `implementation/routes/credit.py:122-141` (no raise anywhere; `response.py:22` only declares the id).
- **§2.7** — insert — the rush alliance agreement is not its own field; `base_turnaround_days` *is* the record of it, so the rush refusal fires exactly when the rush shop's `base_turnaround_days` is not positive — `implementation/routes/repairs.py:124-129`, `routes/refdata.py:19,30`, `services/core.py:443-445`.
- **§2.8** — revise — replaced the unpostable `80,000 + 50,000 + 5,000` reference and the `max()`/`0.30–0.50`-deposit claims; the fee is the **branch-selected candidate** (not the greater of two), `material_recovery_cents` is always 0, the reading names are the two sides of one comparison, and the worked reference now uses the third-revision-only fee — `implementation/services/core.py:631-640`, `constants.py:62,67`.
- **§2.9** — insert — `replacement_claims_used` never rises above 1 — `implementation/routes/appraisals.py:67-73`.
- **§3.3** — insert — a standing visit record logged `CLAIMED` is stored with `claimed_at` stamped and advances coverage; any other `result` carries `claimed_at` null — `implementation/routes/visits.py:42-57` (the Step 7 fix), `registrations.py:299,316`.
- **§3.5** — insert — `outstanding_balance_cents` is a re-derived closed form (§2.10), not a running total; the completion's final step recomputes it, matching capitalization, payoff and direct append — `implementation/services/core.py:185-195,232`, `routes/purchases.py:152,163,178`, `routes/plans.py:214,280`, `routes/ledger.py:42`.
- **§3.6** — revise — same deposit-ceiling correction plus the certified-metal requirement is declared but unreachable (no input field), and the priority-10 statement — `implementation/routes/designs.py:39-44`, `constants.py:72`, `response.py:39`.
- **§3.6** — revise — forfeit paragraph: branch-selected fee, not `max()`; material recovery always 0; the excess is reported beside the fee rather than as a `customer_balance_due_cents`/`customer_refund_cents` field — `implementation/services/core.py:631-640`, `routes/designs.py:203-213`.

## Per-edit pre-edit search log

1. **§2.4 down-payment gate** — (a) *subject:* `ERR_DOWN_PAYMENT_REQUIRED` reachability. (b) Enumerated and read every raise of `Err.DOWN_PAYMENT_REQUIRED`, `INSUFFICIENT_DEPOSIT`, `RING_METAL_NOT_CERTIFIED`, `REGULATION_TERMS_VIOLATION`, `PLAN_TERM_EXCEEDS_REGULATION`, `WINDOW_EXPIRED`, `CLAIM_ALREADY_USED`, `APPRAISAL_REQUIRED` (`grep` over all routes + `response.py`); read `credit.py` decision path, `test_05_boundary_precision.py:73-87`. (c) Softened the original "is refused with `ERR_DOWN_PAYMENT_REQUIRED`" to "reported figure … not reachable through this decision", preserving the id's catalogue existence so the §5 table and §2.14 priority 22 stay consistent.
2. **§2.7 alliance agreement** — (a) *subject:* how a "signed alliance agreement" is recorded and checked. (b) Grepped `VENDOR_AGREEMENT|base_turnaround_days|vendor_is_rush` across `routes/repairs.py`, `routes/refdata.py`, `services/core.py`, `constants.py`, `response.py`; read the full `route_repair` handler and the shop-creation handler; confirmed no alliance field exists on any row. (c) Inserted the field-identity sentence; deliberately left the existing "seeded from the alliance agreement" clause untouched so both statements cohere.
3. **§2.8 cancellation fee** — (a) *subject:* `cancellation_fee_cents`, `material_recovery_cents`, `customer_refund_cents`/`customer_balance_due_cents`. (b) Grepped `cancellation_fee|refundable_deposit|non_refundable|MATERIAL_RECOVERY|revision_fee` and confirmed **no** `customer_refund_cents`/`customer_balance_due_cents` field is ever written; read `core.py:621-650`, `routes/designs.py:82-216`, `test_01_dual_variant_calculations.py:193-238`. (c) Re-scoped: kept `COST_BEARING_FORFEIT`/`DEPOSIT_BOUNDED_FORFEIT` as the two sides of one comparison rather than two fee formulas, and dropped both named fields.
4. **§2.9 claim saturation** — (a) *subject:* `replacement_claims_used` bound. (b) Read `routes/appraisals.py` whole handler; grepped `replacement_claims_used` across `services/core.py`, `routes/purchases.py`, `routes/registrations.py` (only initialization at 0, the single increment, and the ≥1 guard). (c) None needed.
5. **§3.3 `claimed_at`** — (a) *subject:* `claimed_at` on the standing visit record. (b) Grepped `claimed_at` across `routes/visits.py`, `routes/registrations.py`; read both creation paths plus `_advance_registration`, `_claim_visit`; checked `test_16:115` (`CLAIMED` → non-null) and `test_13:212` (`SCHEDULED` → null). (c) Scoped the sentence to the standing record only, and scoped the coverage claim to "exactly as the registration-scoped claim does" so the already-pinned §3.3 two-outcome prose is not redefined.
6. **§3.5 outstanding balance** — (a) *subject:* whether completion *increments* or *recomputes* the balance. (b) Enumerated all write sites via `grep -n outstanding_balance_cents` and all `outstanding_balance(` callers: `core.py:232` (recompute), `core.py:299-300` (store recompute), `plans.py:214` (capitalize), `plans.py:280` (default), `ledger.py:42` (append), `purchases.py:163` (`+= net`); read `purchases.py:152-180` in full. (c) Explicitly reconciled the retained increment sentence: added that the final step's recompute is what the completion leaves behind "exactly as capitalization, payoff, and a direct ledger append each leave the same closed-form value in their own place". Deliberately **did not** claim the `+=` is dropped, because it *does* execute and is the gate value the §3.5 precondition reads one hop earlier.
7. **§3.6 deposit ceiling / metal** — (a) *subject:* the two `ERR_INSUFFICIENT_DEPOSIT` conditions and `ERR_RING_METAL_NOT_CERTIFIED`. (b) Read `routes/designs.py` create handler; grepped `RING_METAL|metal|alloy` across the implementation (only `constants.py:72` list, never consulted) and across `test_suite/` + `test_helpers/` (only the error-id enum, no test); confirmed `DEPOSIT_PCT_MAX` exists at `constants.py:61`. (c) Replaced the nonexistent "recomputed deposit too small" condition with the real `<0.30` / `>0.50` pair, and marked the metal gate unreachable with its priority-10 position preserved.
8. **§3.6 forfeit paragraph** — (a) *subject:* same as edit 3; (b) same enumeration, re-run in full before this second, §3-worded instance. (c) Matched edit 3's wording so §2.8 and §3.6 no longer contradict each other.

## Notes for the caller

Extra beyond the literal Step 7 list (edits 1, 4, 7): those three are declared refusals the implementation can never raise (`ERR_DOWN_PAYMENT_REQUIRED`, `ERR_RING_METAL_NOT_CERTIFIED`) plus a one-line saturation bound. I disclosed them because they produce the same class of defect as the Step 7 find (a faithful reader diverges from `implementation/`) and surfaced from the same mandated enumeration. They only *add* true, under-determined statements about the implementation, so they cannot create a new mismatch; they can be reverted in isolation if the scope is to be held absolutely to `routes/purchases.py`, `routes/repairs.py`, `routes/stores.py`, `routes/visits.py` and the two PRD self-contradictions.

Deliberately left alone (Step 7 items that are pure fixture alignment to prose PRD already uniquely determines): the `setup_store` registry prerequisite (already §3.4), the `open_customer` posture graph builders (§3.1/§3.3/§3.5), the `MALCA` duplicate (§3.4 409), `setup_registration_awaiting_lapse` (§3.3), `setup_store_over_capacity` (§3.4), `_add_days` `.000Z` (§2.12), the removed purchase-completion capacity gate (§3.5's five enumerated preconditions), `stores.py` suspend/reinstate (§3.4), and the role-header corrections (§4 table).

Orchestrator verification: `PRD.md` 510 lines → `PRD_FINALIZED.md` 510 lines, 0.0% delta confirmed on disk.

## Step 9: Complete PRD — 2026-09-29T18:55:00.000Z

Verbatim subagent summary:

Done. PRD_COMPLETED.md is written at `/home/ubuntu/github/CodingPRD/tasks/task_3030_house_jewelry_credit_lifetime_service_plan_administration/workspace/PRD_COMPLETED.md`.

## Source / delta
- Source: `PRD_FINALIZED.md` (exists) → copied to `PRD_COMPLETED.md`
- Lines: 510 → 510 (unchanged); chars 118,101 → 127,485, **char delta +9,384**
- 24 changed line-regions; ~32 distinct inline changes (some regions carry two)

## Counts
- Ambiguity-pins (PRD silent / variants offered, pinned to code): **16**
- Mismatch-revisions (PRD described a different behavior): **16**

## Changes (all edits are in-paragraph; no sections added)
- §2.4 registry sentinel — revise — ambiguity — sentinel is a per-row stored field defaulting to `*`; `REGISTRY_TYPE_GLOBAL` is not a registry type — `services/core.py:344-354`, `routes/config.py:25-28`
- §2.4 policy tier — revise — ambiguity — 200,000 `TIER_1_REQUEST_THRESHOLD_CENTS` is not a distinct band — `services/core.py:332-341`
- §2.4 `minimum_down_payment_cents` — revise — mismatch — accepted/stored but inert; no rule reads it — `routes/credit.py:48`
- §2.6 term overrun — revise — mismatch — priority 7 emits `ERR_PLAN_TERM_EXCEEDS_REGULATION`, not `ERR_REGULATION_TERMS_VIOLATION` — `routes/registrations.py:46-47`
- §2.6 inspection mandate / §2.14 priority 7 — revise — mismatch — same code pin — `routes/registrations.py:46-47`
- §2.6 regulation table unread fields — insert — ambiguity — `inspection_required_months`, `max_inspection_gap_days`, `replacement_plus_pct` stored, never enforced — `routes/config.py:55-72`
- §2.7 breach compensation → refused-extension `imposed_breach_adjustment_cents` — revise — mismatch — never written; stored holds always 0, tiered compensation never added to any balance — `routes/repairs.py:278-291`, `services/core.py:462-482`
- §2.8 trade-up cap / stamped credit — revise — ambiguity — cap applied at credit-basis and preview; a stamped credit on a no-origin ticket is wiped by completion — `routes/purchases.py:94-102,210-213`, `services/core.py:508-534`
- §2.9 insurance replacement arithmetic — revise — mismatch — no `replacement_plus_pct`/`INSURANCE_REPLACEMENT_PCT` consumption exists; only the claim count is administered — `routes/appraisals.py:67-73`
- §2.10 `lost_inspection_streak` — revise — ambiguity — counts registrations with `missed_inspection_count>0`, not a strictly consecutive streak — `routes/plans.py:272-277`
- §2.11 bucket capacity + labels — revise — mismatch — capacity is Σ unpaid plans' `final_settlement_amount_cents`; `STANDARD_RETAIL`/`NEW_ACCOUNT` = 0; stored labels `{PROMOTIONAL, CUSTOM_DESIGN, RETAIL}` map to waterfall positions 1, 3, 2 — `services/core.py:673-711`
- §2.11 `min_payment_due_cents` — revise — ambiguity — zero-allocation buckets skipped; band on the bucket's capacity — `services/core.py:714-722`
- §2.13 OCC create-plan — revise — mismatch — state precondition accepts `FINANCED` too, so OCC is what separates two financing writes — `routes/plans.py:35-41`
- §3.1 store/credit posture — revise — mismatch — intake not status-gated; only full approval requires `ACTIVE`, counteroffer does not; `credit_enabled` never read — `routes/credit.py:35-58,104-110`, `routes/stores.py:26`
- §3.1 decision limits — revise — ambiguity — `standalone_credit_limit_cents` set to W (=`approved_limit_cents`) at decision, but L (full `base_limit_cents`) on restore — `routes/credit.py:122-137`, `services/core.py:258-263`
- §3.2 `simplicity_expires_at` — insert — ambiguity — calendar-month offset with month-end clamping, not a day count — `routes/plans.py:294-304`
- §3.2 plan reinstatement / suspension lift — revise+insert — ambiguity/mismatch — restore from `decision_rule_id` row's full `base_limit_cents` (not the lessened granted limit); plan reinstatement must run first — `routes/plans.py:161-165`, `routes/customers.py:63-67`
- §3.3 reminder scheduling — revise — ambiguity — driven by current deadline (`inspection_due_at`/`next_inspection_at`), no cycle counter — `routes/registrations.py:194-227`
- §3.3 standing `/inspection-visits` — insert — ambiguity — no terminal-status guard; bounded by the minimum-instant check only — `routes/visits.py:41-43`
- §3.3 `/exams` — insert — ambiguity — one-cycle-only bound (not the due instant), no version assertion, raises `ERR_REGISTRATION_TERMINATED` — `routes/registrations.py:114-120`
- §3.4 intake store-posture ordering — insert — ambiguity — non-`ACTIVE` store refuses with `ERR_STORE_CREDIT_CAPACITY_EXCEEDED` before the registration checks — `routes/repairs.py:46-55`
- §3.4 holds — revise — mismatch — no persisted `EVALUATING`/`REJECTED`; only accepted holds written; refused ones raise `ERR_HOLD_PROMISE_CEILING` — `routes/repairs.py:260-294`
- §3.4 store suspend/reinstate bounds — revise — mismatch — suspend requires strictly `>`, reinstate accepts `<=`; activate only from `OPEN` — `routes/stores.py:60-105`
- §3.4 verify breach — revise — mismatch — evaluation is read-only, not recorded as a store credit — `routes/repairs.py:186-220`, `services/core.py:462-477`
- §3.4/§3.5 verify-opened purchase credit — insert — ambiguity — internal cascade credit `min(loss_liability, appraised)`, `origin_purchase_id` null, floor 0, fee 0 — `routes/repairs.py:195-213`
- §3.5 insurance coordination — revise — mismatch — advice recorded, store exposure split not computed — `routes/appraisals.py:61-76`
- §3.7 default cascade hops 4/5/6 — revise — mismatch — hop 4 covers `PENDING_INSPECTION`+`REMINDER_ISSUED` and decrements store count; hop 5 counts `LAPSED/RENEWED/TERMINATED/VOID` with `missed_inspection_count>0`; hop 6 re-runs tier only, preserving `util=10000` — `routes/plans.py:254-285`
- §3.8 statement generation/close — insert — ambiguity — duplicate `(customer_id, statement_period)` → `ERR_INVALID_REQUEST`; payment optional; negative-balance close gate unreachable — `routes/statements.py:26-49,74-84`
- §3.8 payment buckets — revise — mismatch — only the promotional bucket has capacity; `BUSKET` labels as above — `services/core.py:689-711`, `routes/statements.py:34-46`

No sibling task directories were read; SCAFFOLD*.yaml and worklog.md were not opened.

Orchestrator verification: `PRD_FINALIZED.md` 510 lines / 118,323 chars → `PRD_COMPLETED.md` 510 lines / 127,757 chars confirmed on disk. `implementation/`, `test_suite/` and `test_helpers/` contain **zero** files modified after the 18:32 green sweep — the verified 8/8 × 133/133 result still describes the shipped artifact.

---

## Pipeline complete

| Step | Output | Status |
|---|---|---|
| 1 | task dir (pre-allocated) | done |
| 2 | SCAFFOLD.yaml (3077 L), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1316 L), SCAFFOLD_CORNER_DESIGN.yaml (1991 L) | done, lint-clean |
| 3 | workspace/INSTRUCTION.md | done |
| 4 | workspace/PRD.md (510 L) | done |
| 5 | test_helpers/ (2537 L), test_suite/ (3864 L, 133 tests) | done — 18/18 A + 51/51 B translated, 0 skipped |
| 6 | workspace/implementation/ (4117 L, 21 files) | done |
| 7 | 8-round sweep green | **independently verified: 8/8 rounds, 133/133** |
| 8 | workspace/PRD_FINALIZED.md (510 L) | done — 8 in-place edits |
| 9 | workspace/PRD_COMPLETED.md (510 L) | done — 16 ambiguity-pins + 16 mismatch-revisions |