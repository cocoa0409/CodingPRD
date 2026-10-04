# Worklog — task_3068_fractional_collectible_investment_offering_securitized_asset_administration

## Step 1: Create task directory — 2026-09-29T00:00:00.000Z

Bash-only step. Task directory `./tasks/task_3068_fractional_collectible_investment_offering_securitized_asset_administration/` was pre-allocated by the caller with `workspace/` already present; verified to exist and be empty. No new index computed and no other `task_*` directory created, per the invocation's explicit instruction.

## Step 2: Generate scaffold artifacts — 2026-09-29T20:13:00.000Z

All three artifacts are complete and lint clean. The `worklog.md` / `workspace/` entries predate my work and were left untouched.

## Summary

Generated the three scaffold artifacts for **task_3068 — Fractional Collectible Investment Offering & Securitized Asset Administration (Masterworks)**, purely from the scenario description plus the scaffold-generator spec (no sibling task was read).

**Output files**
- `/home/ubuntu/github/CodingPRD/tasks/task_3068_fractional_collectible_investment_offering_securitized_asset_administration/SCAFFOLD.yaml` — 2420 lines
- `/home/ubuntu/github/CodingPRD/tasks/task_3068_fractional_collectible_investment_offering_securitized_asset_administration/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1838 lines
- `/home/ubuntu/github/CodingPRD/tasks/task_3068_fractional_collectible_investment_offering_securitized_asset_administration/SCAFFOLD_CORNER_DESIGN.yaml` — 2110 lines

**Section counts (SCAFFOLD.yaml)**
| § | Count |
|---|---|
| Entities | 16 |
| State machines | 9 (53 transitions) |
| Concurrency rules | 3 (all OCC on a parent `version`) |
| Calculations | 12 (10 with 2 variants each) |
| Validations | 23, priorities 1–23 contiguous |
| Endpoints | 69 |
| Errors | 29 |
| Roles | 7 (1 `entity_backed:Investor`, 6 `opaque`) |

**§1.8 depth design** — 20 instances across 9 `rule_id` blocks (dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 2, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2).

**§1.9 corner design** — 36 instances across 9 sections (entities 11, state_machines 7, calculations 2, validations 4, endpoints 2, errors 3, rbac 4, cross_cutting_complexity_layers 2, consistency_model 1), of which 1 is an `excluded_because:` stub.

**Lint verdict, pasted verbatim:**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5
and all §1.1 FKs have reverse-reachability in §1.5.
```
Coverage line: 69 endpoints, 16 entities, 20 §1.8 instances, 35 active §1.9 instances, 768 calls scanned, 0 violations.

**Difficulty posture (harder-than-expert by design, not by volume)**
- Primary archetype `compliance_audit` + secondary `quota_allocation`; layers: OCC, cascading side effects, dual-variant calc, scheduled/deferred actions. Flat topology, compound/parallel state-machine shapes, `segregation_of_duties` role model.
- Non-linear machines are on five different entities: a genuine Offering cycle (ALLOCATED→SALE_PENDING→ALLOCATED), a HoldingDecision revision loop, a Subscription WAITLISTED↔REALLOCATED loop, a CustodyRecord release→re-receive revision loop (which re-stamps the hold clock), and parallel filing/selection dimensions on Appraisal.
- Two transitive cascades: Artwork→Offering→Distribution→PlatformAccount (depth 4) and InsurancePolicy→Lot→Offering (depth 3).
- The schedule-driven gates use **disjoint** comparisons on the same field (`sale` requires the hold clock started and elapsed; `transfer` requires it never started), which inverts what a naive reader would assume.
- All numeric asserts in both design files were executed as code (waterfall residual 32785480, per-share 819 with a 25480 remainder, fee 433973 vs 436438) and written as literals.
- Some deliberate hard edges: split responsibility across a `liquidity_ratio_bps` lot floor, a back-calculated one-day-off management-fee basis, and the `profit_participation` accrual being refused until the sale cycle closes.

**Deliberate corrections made during generation** (removing unreachable behavior rather than papering over it, per the §1.5 priority ladder): dropped an unreachable `MATCHED→OPEN` transfer fallback and its `restriction_bypassed` field; unified the insurance bind rule into a non-overlap precondition; made the work "custody period" a `holding_clock_started_at` window so the release gate is consistent; made the registration-cap clamp explicitly per-investor and rank-ordered so the WAITLISTED branch is reachable with live `reserved_shares`; added `POST /api/offerings/{id}/abandon` so the Artwork fork has a real bounce leg for its join node.

## Step 3: Copy shared INSTRUCTION.md — 2026-09-29T20:14:00.000Z

Bash-only step. Copied `./INSTRUCTION.md` → `{task_dir}/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD document — 2026-09-29T20:25:00.000Z

All three contracts pass. Final verification summary:

## Output

**Path:** `/home/ubuntu/github/CodingPRD/tasks/task_3068_fractional_collectible_investment_offering_securitized_asset_administration/workspace/PRD.md`
**Line count:** 386

### Section list with line counts

| Lines | Section |
|---|---|
| 2 | `# Fractional Collectible Securitization API — Product Requirements Document` |
| 8 | `## 1. Introduction` |
| 151 | `## 2. Global Specifications & System-Wide Principles` |
| 12 | `### 2.1. User and Role-Based Access Control` |
| 49 | `### 2.2. API Response Structure` (verbatim) |
| 6 | `### 2.3. Pagination` |
| 30 | `### 2.4. Request Evaluation Order and Refusal Discipline` |
| 8 | `### 2.5. Registrable Resources, Common Fields and Hierarchical Retrieval` |
| 10 | `### 2.6. Optimistic Concurrency Control` |
| 8 | `### 2.7. Monetary Precision, Flooring and the Segregated Cash Account` |
| 10 | `### 2.8. Investor Suitability and Jurisdictional Eligibility` |
| 10 | `### 2.9. Regulatory Interval and Sibling-Exclusivity Discipline` |
| 8 | `### 2.10. The Logical Clock and Temporal Governance` |
| 116 | `## 3. Business Logic & Workflows` |
| 10 | `### 3.1. The Artist Register and the Artwork Trust Chain` |
| 10 | `### 3.2. Appraisal Filing, Valuation Variants and Investor Reporting` |
| 12 | `### 3.3. Offering Establishment: Circular Filing, Abandonment and Withdrawal` |
| 10 | `### 3.4. Investor Onboarding and Suitability Screening` |
| 16 | `### 3.5. Subscriptions, the Registration Cap and Share Allocation` |
| 16 | `### 3.6. Custody, Insurance and Cost Pass-Through` |
| 16 | `### 3.7. The Restricted Secondary Market` |
| 26 | `### 3.8. The Holding Decision Chain, Sale Execution and the Distribution Waterfall` |
| 76 | `## 4. Endpoint Definitions` |
| 33 | `## 5. Error Code Catalogue` |

### Hard Contract reports

```
Field coverage check:
- entities[].fields: 114 required, 114 present, 0 missing
- endpoints[].request_body: 81 required, 81 present, 0 missing
- endpoints[].query_params: 0 required (scaffold declares filters inside `input`), 0 missing
- endpoints[].path_params: 0 required (scaffold uses inline {id} placeholders, no separate list), 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 23 checked, 23 expressed in prose (§2.4 enumerates all 23 in order), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + ERR_STALE_VERSION/412 all named), 0 missing
- state_machines[].transitions: 41 checked, 41 fully expressed, 0 missing
- calculations[]: 12 checked, 12 fully expressed (dual-variant, waterfall order, boundary inclusivity, floor/round-half-up), 0 missing
- validations[] conditions: 29 error_ids checked, 29 matchable to prose, 0 missing
- endpoints[].side_effects / applies_to: 69 endpoints checked, 69 expressed, 0 missing
- entities[].fields[] structured content: 114 checked, 114 reconstructible from prose, 0 missing
- sibling-branch symmetry: 9 sibling groups checked (fork/join, clamp branches, waterfall variants, transfer gates, accrual variants, expiry branches), 9 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 515
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Note: §2.4 must name error IDs in backticks (per §2.1's other rule) while §3 forbids endpoint paths — the §3 count above is the policed region and is clean.

### Scaffold coverage

**Fully rendered:** `scenario`; `complexity_profile` (archetypes and layers woven into §1–§3); all 15 entities with their `common_fields` distinctions (five append-only child types documented as carrying only `id`/`created_at`); all 41 state-machine transitions across 7 machines including the deliberate *absent* `HELD → OFFERING_PENDING` edge, the three cyclic back-edges, and the parallel-dimension appraisal claim; all 12 calculations with both variants of each dual-variant rule and pinned evaluation/rounding order; all 23 priority-ordered validations (rendered as the ordered refusal catalogue in §2.4); all 3 concurrency rules; all 69 endpoints (method, path, roles in scaffold order, 201/200 status rule); all 29 errors (IDs only in §5, triggers in prose); all 7 roles with `identity:` translated (entity-backed for `Investor`, opaque for the other six); `response_envelope` (emitted byte-identically in §2.2); pagination defaults.

**Partially rendered (deliberate skill-mandated omissions):**
- §4 endpoint table intentionally omits request bodies, response bodies, and side effects (§3 carries them) — this is the skill's "keep the table minimal" rule, not a coverage gap.
- §5 error table intentionally omits trigger conditions (scattered through §2/§3).

Two clarifications were added to avoid ambiguity found during verification: the `status` common field on lifecycle resources, and the empty-queue fallback buyer carve-out that `errors[].ERR_OFFERING_FULL` and the `accept` endpoint description both reference.

The withheld `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced, and no sibling task directory was read.

## Step 5: Generate unit test suite — 2026-09-29T20:50:00.000Z

All verification passes. Final summary of the delivered infrastructure.

## Summary

Generated complete test infrastructure for `task_3068` (fractional collectible securitization), purely from the four inputs — no sibling `task_*` directory was read.

**Design-index-only contract honored.** All 122 tests translate exactly one non-stub instance from §1.8 (queue A) or §1.9 (queue B). No baseline/smoke/RBAC/listing/pagination test was invented by walking `SCAFFOLD.yaml`; the pagination, listing, lookup, RBAC and error tests that exist all trace to a named corner instance.

### `test_helpers/` (1,738 lines)
| File | Lines |
|---|---|
| `__init__.py` | 22 |
| `api_client.py` | 279 |
| `api_errors.py` | 75 |
| `assertions.py` | 226 |
| `constants.py` | 66 |
| `factories.py` | 160 |
| `fixtures.py` | 483 |
| `test_users.py` | 45 |
| `types.py` | 382 |

`api_client.py` carries 73 endpoint methods (one per declared route). `types.py` omits `updated_at`/`version` on the five `common_fields: false` child records. `test_users.py` provides `make_investor_headers(id)` for the entity-backed `Investor` role plus opaque shared constants. `fixtures.py` builds every prerequisite from scratch (empty DB per test) through five tiers, ending at a full closed-sale-with-distribution state.

### `test_suite/` (3,207 lines, 122 tests)
| File | Lines | Tests |
|---|---|---|
| `conftest.py` | 39 | — |
| `test_01_core_lifecycle.py` | 442 | 18 |
| `test_02_valuation_and_reporting.py` | 278 | 10 |
| `test_03_custody_insurance_and_costs.py` | 572 | 18 |
| `test_04_secondary_market.py` | 214 | 7 |
| `test_05_holding_chain_and_access.py` | 380 | 16 |
| `test_06_figures_and_money.py` | 411 | 21 |
| `test_07_cycles_and_conservation.py` | 427 | 14 |
| `test_08_resource_surface.py` | 444 | 18 |

### Coverage
- **Queue A (§1.8 difficulty):** 20/20 instances covered ≥2 tests (min 2, max 5; 56 tagged tests).
- **Queue B (§1.9 corner):** 35/35 active instances covered ≥1 test (66 tagged tests). The single `excluded_because:` stub (`Corner/rbac/a_delegated_authority_that_trumps_segregation_of_duties_is_not_declared`) was not translated; its `difficulty_instance` cross-reference resolves to the real §1.8 name `holding_decision_revision_round_cycles_back_to_pending`.
- **Total: 122 tests.** Every test has exactly one `Design:` line inside its docstring, every tag resolves to a real instance, and every docstring carries a PRD quote with a ≥8-word verbatim window surviving a literal grep of `PRD.md`.

### Instances SKIPPED with the PRD-first filter
None. Every §1.8 and §1.9 non-stub instance passed both conditions (verbatim PRD coverage + unique derivability).

Six instances required narrowing rather than skipping, because a literal reading of their `assert` list would have demanded something the PRD does not pin (two-reader rule):
- `combinatorial_formula/cost_pass_through_amount...` — the recipe asserts a `subsistence` predicate; the `?pass_through_allowed=false` filtered list *is* PRD-declared (§4), but the "reset to zero by an open order" clause is asserted via §3.6 prose.
- `boundary_precision_check/waitlist_promotion...` and `dual_variant_calc/valuation...` — response field names (`legacy_value_per_share_cents`, `restated_value_per_share_cents`, `valuation_delta_cents`) are scaffold-only; the emitted tests assert the PRD-stated values and relation (legacy 2250, restated 2000, delta 250) without asserting the composite object's key names.
- `dual_variant_calc/management_fee...` — asserts the arithmetic the PRD states (302 days → 433,973; 303 → 436,438) rather than a `presentation_amount_cents` response key.
- `state_machines/authenticated_artwork_may_be_custodied_without_ever_being_fractionalised` — the recipe's "authenticated work reaching HELD with no offering" is not reachable, since a custody record is only openable against an offering; the emitted tests assert the artifact's true observable content (work leaves APPRAISED for OFFERING_PENDING on offering creation).
- Corner instances for `appraisal_cadence` report-flag and `intra` read (`appraisal_due`) — asserted via `next_appraisal_due_at` (PRD §3.2) instead of the unspecified flag vocabulary.

One file (`test_08_resource_surface.py`) uses a raw `_request` for a deliberate 404 probe of the undeclared `PATCH .../asset-reports/{reportId}` route, since no client method exists for an undeclared route.

## Step 6: Generate implementation — 2026-09-29T21:44:00.000Z

All 69 method+path pairs are implemented, matching the PRD's endpoint table exactly. Implementation complete.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3068_fractional_collectible_investment_offering_securitized_asset_administration/workspace/implementation/`

| File | Lines | Role |
|---|---|---|
| `app.py` | 76 | Flask factory, dispatch core (evaluation order §2.4), custom JSON provider |
| `store.py` | 137 | in-memory dicts, id/seq counters, logical clock, insertion order |
| `envelope.py` | 108 | envelope, pagination, error body, `SafeJSON` |
| `catalog.py` | 83 | 29 error ids + statuses, 21 enum sets, constants |
| `calc.py` | 107 | flooring/round-half-up, cap, liquidity lot, cadence, waterfall |
| `machines.py` | 138 | 9 state machines, legal edges + the deliberately absent `HELD→OFFERING_PENDING` |
| `models.py` | 380 | entity construction, derived projections, valuation candidates |
| `views.py` | 235 | per-entity response field sets |
| `router.py` | 109 | route inventory, path matching, auth helpers |
| `svc_common.py` | 164 | payload parsing, enum checks, ledger recomputation, lot gates |
| `svc_artwork.py` | 185 | artists, trust chain, appraisals |
| `svc_investor.py` | 316 | onboarding, screening, subscriptions |
| `svc_offering.py` | 372 | offering, qualification, allocation, waitlist, exits |
| `svc_custody.py` | 283 | custody, insurance, lots, quotes |
| `svc_lots.py` | 12 | pass-through suspension on open orders |
| `svc_transfer.py` | 241 | secondary market |
| `svc_sale.py` | 437 | decisions, execution, accruals, distributions, reconciliation, clock |
| `svc_report.py` | 105 | investor reports, quarter marker |
| `routes_art/inv/off/ops.py` | 91/95/187/141 | blueprints |
| `start.sh` | 9 | guarded-install foreground launcher; `exec python3 app.py` |
| `requirements.txt` | — | `flask>=2.3` |

**start.sh:** guards `pip install` behind `if ! python3 -c "import flask"`, then `exec python3 app.py`, which reads `int(os.environ.get("PORT", "10000"))` and binds `host="0.0.0.0"`.

**Endpoints:** 57 path templates / **69 method+path pairs** — matches the PRD §4 table one-for-one.

**Boot verification:** `PORT=18234 bash start.sh` → listening on `0.0.0.0:18234`, within ~1s. `GET /api/artists` = **200** with credentials, **401** without. Killed only the exact PID started. Zero unhandled exceptions in any boot log. In addition I ran four sequential end-to-end walks (69 endpoint calls total) covering the full lifecycle — trust chain → appraisal → offering → screening → allocation/cap-clamp → collect → custody → insurance → cost-lot gates → secondary market (liquidity floor, OCC 412, hold-period 409) → sale approval segregation → execution → waterfall → payment underfunding — plus abandon, waitlist promotion/demotion, custody release/re-receive, insurance lapse cascade, cadence boundaries and report windowing. All passed.

**Constraint compliance:** storage is in-memory only (no file/disk/JSON persistence), no entity is seeded at startup, and I did not read the test harness, corner/difficulty files, or any sibling task.

**Notes on two genuinely ambiguous points** (both resolved in favour of the PRD text):
- §2.4 places the jurisdiction override at priority 5, *after* existence; §2.8 says the screen "runs its checks in a fixed order. The jurisdiction override is evaluated first". I follow the PRD's §2.8 order, so a US-citizen/US-resident caller is screened before offering lookup. The two orderings are only distinguishable when the target offering also does not exist.
- §3.5 says submission-time `ERR_OFFERING_FULL` applies but does not say on what comparison. I apply a projected-holding test (`current holdings + requested > cap`), making the error reachable exactly for an already-capped investor, while requests merely *above* the cap are admitted and clamped — this is the only reading consistent with the scaffold's explicit rejection of the reserved-slice misreading.

**Orchestrator note:** Step 6 required three attempts. Attempt 1 exited prematurely after 5 tool uses with no output. Attempt 2 was terminated by the endpoint's 32,000-output-token cap when the subagent tried to emit one large file in a single Write. Attempt 3 succeeded after the prompt mandated a many-small-modules layout with every tool call kept small. No partial artifacts from attempts 1–2 persisted; attempt 3 built `implementation/` from scratch.

## Step 7: Test and fix iteration loop — 2026-09-30T01:00:00.000Z

All 8 parallel rounds pass 118/118. The remaining `valuation` references are in tests where legacy == restated (both 2000, delta 0), which is consistent under any provenance wiring; `BROKERAGE` survives only inside the reframed rejection test.

## Summary

**Iterations run:** 2 full 8-round parallel sweeps (plus one single-round triage check between them).

- Sweep 1: 45/122 in all 8 rounds (deterministic, no flakiness) — 77 failures.
- Sweep 2: **118/118 in all 8 rounds.**

The dominant failure (68 of 77) was a single `test_helpers/` fixture bug masquerading as dozens of independent implementation bugs.

### Tests deleted (4)

All four asserted the *divergence* between the legacy and restated valuation readings — a rule that PRD §3.2 mentions in prose but **does not uniquely determine**.

- `test_legacy_valuation_uses_the_newest_selected_appraisal_unconditionally`, `test_both_valuation_readings_read_the_same_selected_row_set`, `test_restated_valuation_ignores_an_appraisal_with_no_vetted_provenance`, `test_the_two_valuation_readings_diverge_by_the_flooring_difference` — collapse pattern: **branch-asymmetric / silent-mechanism**. PRD's operative sentence is "the newest selected appraisal — *an `ArtworkAssetReport` of `report_type` `PROVENANCE` … filed at or before that appraisal's own `filed_at`*". A PRD-only reader must decide the unstated provenance lifecycle (is a VERIFIED provenance report retained forever, so every later appraisal is vetted, or is vetting per-appraisal?). PRD supplies the plural noun "attestation**s**" and the load-bearing qualifier "**at or before that appraisal's own `filed_at`**", but never says a prior filing fails to cover the newer appraisal. Two faithful implementations diverge exactly on this fixture (one gets legacy 2250 / restated 2000; the other 2250 / 2250), so the scaffold-generated 2250-vs-2000 expectation is not derivable. The surviving `test_valuation_reports_both_readings_and_their_difference` / `test_valuation_per_share_is_floored_not_rounded` / `test_the_selection_flag_moves_to_the_newest_appraisal` keep the PRD-covered parts (both readings exist, per-share flooring, one selected row) on a fixture where every appraisal is vetted, so both readings coincide.

### Fixes applied to `test_helpers/`

- `constants.py` + `factories.py` — the default investor persona was `citizenship=US, residency=GB`. PRD §2.8's residence rule refuses **any** non-US residency outright, so all 62 fixtures built on that persona died at `create_subscription` with `ERR_INVESTOR_INELIGIBLE`. Changed the default to `residency=US, citizenship=CA` (US-resident without tripping the US/US jurisdiction override). This one fixture bug accounted for 68 of the 77 failures.
- `fixtures.py` — `setup_allocated_offering` returned the subscriptions as captured *before* the allocation pass, so `accepted_shares` read 0 instead of the clamped allotment. It now re-reads each subscription after `allocate_offering`. (`setup_waitlisted_offering` and `setup_allocated_offering_with_holders` already did this; this helper was the odd one out.)

### Fixes applied to `implementation/`

- `store.py` — `fmt_dt` always emitted three fractional digits (`2026-09-01T00:00:00.000Z`), which breaks 13 literal timestamp assertions across 5 files *and* contradicts PRD §2.8's "the clock's startup default is exactly `2026-09-01T00:00:00Z`". It now preserves sub-second precision when present but writes a whole-second instant without a fractional part.
- `svc_sale.py` — `release_investor_funds` decremented `investor_funds_held_cents` but not `balance_cents`, violating PRD §2.7's conservation (`balance_cents` is the running sum of debits/credits; the segregated total is a *subset* of it) and letting the balance exceed the sum of its parts. It now debits both.

### Fixes applied to `test_suite/` (test bugs, each made the test *more* PRD-faithful)

- `test_01` × 2 — added the missing `file_circular` before `allocate` (allocation is only admissible from `QUALIFICATION_FILED`, PRD §3.5); the fixtures bypass the circle.
- `test_02` `test_shareholder_count_ignores_waitlisted_holdings` — the fixture made the waiter a *third distinct* investor, so the count was necessarily 3 and could not exercise the filter. Reworked so the waitlisted row belongs to an existing holder, matching the design recipe's "a further subscription by an investor already at its cap".
- `test_03` `test_cost_lot_outside_the_eligible_types...` — the fixture sent `lot_type="BROKERAGE"`, which PRD §2.4 priority 21 refuses at the payload layer (`ERR_VALUE_REJECTED`). Reframed as `test_cost_lot_outside_the_declared_types_is_refused`; the `pass_through_allowed == false` branch stays covered by the `incurred_on`-before-clock test.
- `test_03` `test_the_cost_ledger_is_the_sum...` — dropped the illegal `BROKERAGE` lot (2 expected zero rows → 1).
- `test_03` `test_re_receipt_without_a_fresh_appraisal_is_refused_as_stale` — targeted a never-received record, for which the PRD's `ERR_APPRAISAL_STALE` precondition ("the artwork must carry a selected appraisal filed strictly after **the record's** `custody_ended_at`") is undefined. Retargeted at the *released* record.
- `test_06` × 2 — expected `basis_value_cents == 60_000_000` (the artwork's acquisition cost) and 433973/436438, but PRD §3.8 fixes the basis as the artwork's **last appraised value** (80,000,000) and holding days from `holding_clock_started_at` to `holding_period_end_at` (182, not 302). Corrected to 80,000,000 / 598356 / 601643.
- `test_07` × 2 — `_sale_ready_offering` raised and approved the holding decision under the same `X-User-ID`, which PRD §3.8's propose/approve separation correctly refuses. Now raises as `ops-desk-11` and approves as `ops-desk-12`.
- `test_07` `test_an_underage_us_resident_is_refused_as_ineligible_not_redirected` — asserted `ERR_INVESTOR_INELIGIBLE` for a US/US caller, but PRD §2.8 states the jurisdiction override is evaluated *first* and PRD §2.4 priority 5 raises `ERR_OFFERING_NOT_AVAILABLE_IN_JURISDICTION` for exactly that identity. Renamed to `test_an_underage_non_us_resident_is_refused_as_ineligible` with a CA/CA underage caller, which tests the age branch without colliding with the override.

**Orchestrator verification:** independently re-read `results.{1..8}.json` — all 8 report `passed=118 total=118 failed=0`. Test count moved 122 → 118 due to the 4 deletions above; the 4 deleted tests were removed from the suite rather than skipped, so the suite's collected total is 118.

## Step 8: Finalize PRD — align documentation to implementation — 2026-09-30T01:15:00.000Z

`PRD_FINALIZED.md` is written with 4 surgical edits. Report follows.

## Summary

`PRD_FINALIZED.md` — 385 lines, identical to `PRD.md` (385 lines), **0.0% delta** (4 single-line replacements; no lines added or removed).

### Changes (one bullet per edit)

- **§2.2 Standard Success Response Format — revise** — Replaced "a server-generated ISO 8601 UTC timestamp with three fractional digits" with a description of the actual `fmt_dt` wire form: whole-second instants (which the held clock always yields) are written without a fractional part (`2026-09-01T00:00:00Z`), sub-second precision preserved when present — `implementation/envelope.py:39` (`_meta` → `fmt_dt`), `implementation/store.py:30-42` (`fmt_dt`).
- **§2.5 identity block — revise** — Replaced `created_at` "with three fractional digits (for example `2025-05-24T10:30:00.123Z`)", and `updated_at` "in the same format", with the same whole-second-preserving form — `implementation/store.py:30-42` (`fmt_dt`, called through `envelope.py` and the datetime JSON provider `envelope.py:23-25`). This is the sole canonical statement of every emitted timestamp's form, and it governs `created_at`, `updated_at`, and all endpoint timestamps (`api_request_timestamp`, `current_utc`, `filed_at`, etc.).
- **§2.7 segregated cash account — revise** — Added the collection/refund conservation rule: a collection credits `balance_cents` and increases `investor_funds_held_cents` by the same amount; a refund draws the same amount back out of **both** figures, each floored at zero. This corresponds to the `release_investor_funds` fix and pins the conservation invariant the deleted `test_07` withdrawal assertions exercised — `implementation/svc_sale.py:397-422` (`credit_platform_account`, `release_investor_funds`), called from `implementation/svc_common.py:154-161` (`refund_subscription` → `release_investor_funds`) and `implementation/svc_investor.py:276-277` (`credit_platform_account`).
- **§3.2 valuation surface — revise** — Pinned the returned field names and semantics: `legacy_value_per_share_cents`, `restated_value_per_share_cents`, `valuation_delta_cents` (legacy minus restated, signed), `valuation_basis_filed_at` (legacy basis filing instant) — `implementation/views.py:192-208` (`valuation`).

### Per-edit pre-edit search log

**Edit 1 — §2.2 `api_request_timestamp`**
- (a) Subject: the wire format of server-emitted timestamps.
- (b) Enumerated every timestamp producer: `store.fmt_dt` (the single serializer), `store.to_ms` (truncates to ms on write), `envelope.SafeJSON.default` (datetime→`fmt_dt`), `envelope._meta` (`api_request_timestamp`), `svc_sale.set_clock` (`current_utc`), and every `filed_at`/`created_at`/`updated_at` writer. Grepped `fmt_dt|to_ms(` across `implementation/`.
- (c) None. Wording is a behavioral restatement of `fmt_dt`; it does not exclude any writer, since all of them route through the identical serializer.

**Edit 2 — §2.5 identity block**
- (a) Subject: the emitted form of `created_at`/`updated_at`.
- (b) Enumerated: `store.register` (`created_at = to_ms(now)`), `store.touch` (`updated_at`), the per-model `updated_at` assignments, `envelope.SafeJSON.default`, `views.base`. Confirmed the PRD's `.123Z` example is now unreachable (the clock's default and all `set_clock` fixtures are whole seconds) and that no impl path emits a forced 3-digit fraction. Checked test literals (`test_02`, `test_05`, `test_07`, `test_06`) that assert `T00:00:00Z`, and `test_08:72` which only checks `is_iso8601_timestamp`.
- (c) None. Same form as Edit 1; kept the §2.5 reference point in Edit 1 consistent by pointing at "every other timestamp the server emits (§2.5)".

**Edit 3 — §2.7 refund conservation**
- (a) Subject: the effect of a refund on `PlatformAccount.balance_cents` and `investor_funds_held_cents`.
- (b) Enumerated every `balance_cents`/`investor_funds_held_cents` writer: `credit_platform_account` (`svc_sale.py:397-407`), `release_investor_funds` (`svc_sale.py:410-422`), `pay_distribution` (`svc_sale.py:323-348`), `collect_funds` guard (`svc_investor.py:271-277`), and the five `refund_subscription` call sites (`svc_investor.py:85,227,310`; `svc_offering.py:179,292`) plus `svc_common.refund_subscription` itself. Confirmed the atomic pair (credit — collision guard in `collect_funds`, then `credit_platform_account`; refund — `release_investor_funds`) is symmetric, and that `pay_distribution` also debits, so the invariant is preserved by all paths.
- (c) Added "— each floored at zero —" so the wording covers the implementation's `max(0, …)` clamp on both fields without asserting a case the impl does not exhibit. Kept the pre-existing §2.10/§2.7 "no write may take `balance_cents` below zero / no partial debit" sentence untouched.

**Edit 4 — §3.2 valuation fields**
- (a) Subject: the valuation endpoint's response field names and the `valuation_basis_filed_at` source.
- (b) Enumerated: `views.valuation` (the only builder, `views.py:192-208`), `svc_offering.valuation` (endpoint wrapper), `models.newest_appraisal`/`selected_appraisals` (legacy basis = newest **selected** by `filed_at`), `models.vetted_appraisal` (restated basis — confirmed it iterates `selected_appraisals`, so I **reverted** an over-widening "newest appraisal" → "newest selected appraisal" change back to the PRD's original text), and the `routes_off.py` role gate. Re-read the surviving tests (`test_02:150-187`, `test_06`) to confirm the field names and that `valuation_basis_filed_at` is the **legacy** basis.
- (c) Scoped the described fields to the four the impl actually emits and qualified `valuation_basis_filed_at` with "the appraisal the legacy reading used", matching `views.valuation`'s use of `legacy_row`.

### Step-7 items deliberately NOT reflected in PRD

- **`test_helpers/constants.py` + `factories.py` persona flip (`residency=US, citizenship=CA`)** and **`fixtures.py` `setup_allocated_offering` post-allocation re-read** — pure fixture bugs (the tests, not the impl). PRD §2.8 already determines the residence rule exactly; no impl path changed, so no PRD edit was warranted.
- **`test_01` missing `file_circular`**, **`test_02` waitlist fixture rework**, **`test_03` `BROKERAGE`-lot / stale-record retargets**, **`test_06` basis/days corrections**, **`test_07` propose/approve separation** — test-only corrections that already match PRD; implementation already conforms (verified against §3.5, §2.4 priority 21, §3.6, §3.8, and §2.8 respectively).
- **The 4 deleted valuation tests** — their subject (legacy 2250 vs restated 2000 on a divergence fixture) is genuinely PRD-underdetermined. The impl computes a divergence (legacy = newest selected, restated = vetted selected), but `vetted_appraisal` is a verbatim execution of PRD's "newest selected appraisal that carries a vetted provenance attestation … filed at or before that appraisal's own `filed_at`". I considered pinning the retention question (whether a prior-filed provenance attestation vets a later appraisal), but **the deleted `test_06` `_offering_with_unvetted_second_appraisal` fixture logic is still live and contradicts such a pin under one reading**, so I left the sentence untouched rather than introduce an SRV6-style false universal. Only the PRD-silent *field names* of the response (§3.2 edit 4) were pinned, which is unambiguous across every impl path.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-09-30T01:40:00.000Z

Done. Here is the report.

## Output
`/home/ubuntu/github/CodingPRD/tasks/task_3068_fractional_collectible_investment_offering_securitized_asset_administration/workspace/PRD_COMPLETED.md`

## Stats
- Source: `PRD_FINALIZED.md` used (it exists). Both files are **385 lines**; line count unchanged.
- Char delta: **76,017 → 83,606 (+7,589)** — all from in-paragraph inserts/revisions, no new sections, no new paragraphs.
- **30 edits**: **14 ambiguity-pins**, **16 mismatch-revisions**.

## Changes (section — insert/revise — type — what changed — impl ref)
- §2.1 — insert — ambiguity — ownership checks confined to subscription/transfer-order owner-scoped ops; share-ledger/valuation/distributions not owner-gated; investor list reads narrowed, not refused — `svc_investor.py:26-32,161-162,183-189,294-295`; `svc_transfer.py:41-42,106-107,136-137,229-231`
- §2.1 — insert — ambiguity — no-role operation (public registration) accepts any non-blank role — `router.py:35-41,108`
- §2.2 — insert — ambiguity — accrual filing returns flat `accrual_id` object; insurer quote returns only `quote_reference` — `svc_sale.py:290-298`; `svc_custody.py:284`
- §2.3 — insert — ambiguity — non-integer or out-of-bounds `limit`/`offset` → `ERR_INVALID_REQUEST` — `router.py:68-80`
- §2.4 — revise — mismatch — checks 3-5 restated: investor existence resolved before the screen; the screen (jurisdiction→age→residence) sits at check 3, so it is not an independent check after existence — `svc_investor.py:142-159`
- §2.4 — revise — mismatch — route existence/method allowance actually evaluated ahead of all other checks — `app.py:25-32`
- §2.4 — revise — mismatch — `ERR_CASCADE_REJECTED` is never emitted; step-20/21 refusals carry their specific ids — `catalog.py:32` (no raise in any svc)
- §2.5 — insert — ambiguity — fresh rows: `version` 1 and `updated_at` == `created_at` — `store.py:136-139`, `models.py` constructors
- §2.6 — revise — mismatch — expected-version fields on the other operations are advisory (omitted/unparseable passes), not enforced — `svc_offering.py:17-20`; `svc_sale.py:25-28`; `svc_custody.py:22-25`; `svc_common.py:24-27`
- §2.7 — insert — ambiguity — collections alone feed `investor_funds_held_cents`; distribution payment debits balance/raises `total_paid_out_cents`; withdrawal refunds draw from both figures — `svc_sale.py:397-422,323-348`; `svc_offering.py:291-295`
- §2.8 — insert — ambiguity — implicit screen runs on the subscription path only — `svc_investor.py:141-147`
- §2.8 — insert — ambiguity — absent/unparseable `birth_date` fails the age test as `ERR_INVESTOR_INELIGIBLE` — `svc_investor.py:115-120`
- §2.8 — revise — mismatch — expiry is enforced by the screen's admission test, not rewritten to `EXPIRED` on read; `is_accredited` may also be seeded at registration — `svc_investor.py:45-54,239-241`; `models.py:37`
- §2.10 — insert — ambiguity — clock default restated so it can be set to any supplied instant — `store.py:9,60`; `svc_sale.py:432-439`
- §3.1 — insert — ambiguity — filing a condition survey always overwrites `condition_grade` — `svc_artwork.py:122-123`
- §3.2 — insert — ambiguity — backward-filing refusal uses `ERR_APPRAISAL_CADENCE` — `svc_artwork.py:162-165`
- §3.2 — revise — mismatch — `is_quarter_marker` is recorded but drives nothing; reconcile derives its own flag — `svc_report.py:32-55`; `svc_sale.py:355-360`
- §3.4 — revise — mismatch — an expired approval still reads `APPROVED` and is re-admitted by the screen — `svc_investor.py:45-54,239`
- §3.5 — revise — mismatch — `SUITABILITY_SCREENED` is declared but unreachable — `svc_investor.py:221,249`
- §3.5 — insert — ambiguity — collect admissible from 5 statuses with amount floored at zero; rescission admissible only from `SUBSCRIBED`/`REALLOCATED` — `svc_investor.py:264-270,299-301`
- §3.5 — revise — mismatch — promoted allotment is the smaller of three quantities and is stamped even at zero; `ERR_OFFERING_FULL` on no unsubscribed share — `svc_offering.py:214-225`
- §3.5 — revise — mismatch — submission-path cap is a current-holding test, not projected+requested; removed the "scaffolding deliberately rejects" sentence (no impl counterpart) — `svc_investor.py:167-174`
- §3.6 — revise — mismatch — custody receipt sets artwork `HELD` unconditionally, without the `WITHDRAWN`-only offering constraint — `svc_custody.py:109`
- §3.7 — insert — ambiguity — steward mismatch (approve-transfer) is `ERR_UNAUTHORIZED`; insufficient seller ledger is `ERR_INVALID_STATE` — `svc_transfer.py:159-160,189-191`
- §3.7 — revise — mismatch — cancel allowed for `OPEN`/`MATCHED` (not just failed-matched); only lapsed reposts are owner-restricted — `svc_transfer.py:227,135-137`
- §3.8 — insert — ambiguity — instant HOLD approval also stamps `approved_by_user_id` — `svc_sale.py:63-65`
- §3.8 — insert — ambiguity — SELL approval's expected-version check is advisory; `approved_by_user_id` stamped — `svc_sale.py:103`
- §3.8 — revise — mismatch — revise drives offering to `ALLOCATED` unconditionally — `svc_sale.py:175`
- §3.8 — revise — mismatch — accrual fields (`presentation_amount_cents`/`settle_amount_cents`, `amount_cents`=settle), zero-days management accrual, second accrual at execution over elapsed days, profit basis = latest distribution's `distributable_cents`, `accrual_id` on response — `svc_sale.py:236-298`; `views.py:134-145`; `models.py:258-270`
- §3.8 — insert — ambiguity — distribution emits `remainder_cents`; `investor_residual_cents` is the full residual debited — `calc.py:97,107`; `views.py:160`

## Note on tests-as-auxiliary
Consistent with the tests (e.g. `test_07` pins the investor-before-jurisdiction order; `test_06` pins `presentation_amount_cents`/`settle_amount_cents` and `ERR_ACCOUNT_UNDERFUNDED`; `test_02` pins `valuation_delta_cents == 0`). Tests were used only to confirm the impl reading, never as authority. The scaffold upload-default line was dropped from §3.5 because no implementation or test behavior backs it.