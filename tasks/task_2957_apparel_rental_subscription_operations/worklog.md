# Worklog — task_2957_apparel_rental_subscription_operations

## Step 1: Create task directory — 2026-09-05T22:00:45.736Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2957_apparel_rental_subscription_operations` and `workspace/` (pre-assigned path; no index auto-allocation performed, per orchestration directive).

## Step 2: Generate scaffold — 2026-09-06T00:01:16.323Z

Step 2 complete. All three scaffold artifacts are written, parse under PyYAML, and pass the scaffold linter.

**Deliverables**

| File | Lines |
|---|---|
| `SCAFFOLD.yaml` | 3313 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2751 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 6862 |

**SCAFFOLD.yaml (§1.0–§1.7 only; no `scaffold_difficulty_design` / `scaffold_corner_design` keys)**
- 13 entities, 68 endpoints, 7 state machines, 14 calculations, 50 validation rules (single global priority ladder), 60 error codes, 5 roles
- `complexity_profile`: entity_topology hybrid, state_machine_shape parallel+cyclic, role_model `segregation_of_duties`, consistency_model `immediate`, complexity_layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, selector_policy]`, `difficulty_level: expert_plus`
- The "Generate task harder than expert level!" directive line is deliberately **not** in `scenario:` (verified: 740 chars, no directive text) — it is recorded only as `difficulty_level`, per the known leak-via-scaffold hazard.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)** — 9 rule_ids, **24 instances**: dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 4, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 2.

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9)** — all 9 guide sections, **110 instances = 80 with full `test_recipe` + 30 `excluded_because` stubs** (entities 13, state_machines 18, calculations 18, validations 35, endpoints 9, errors 3, rbac 6, complexity_layers 6, consistency_model 2). Every stub cites a resolvable `rule_id / instance_name` from §1.8; no stub carries a test_recipe and no real instance is missing one; all 134 §1.8∪§1.9 names are globally unique.

**Lint verdict (verbatim, from repo root)**
```
Coverage
  §1.5 endpoints declared:    68
  §1.1 entities declared:     13
  §1.8 instances scanned:     24
  §1.9 instances scanned:     80
  Calls scanned (§1.8+§1.9):  1582

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Other checks**: zero hits for the forbidden race vocabulary across all three files (fixed one stray "simultaneously" in §1.8's `unit_reallocation_allowed_exactly_at_recondition_buffer_edge` — reworded to "already consumed", line count unchanged); all 60 declared error codes appear in §1.8/§1.9, so none is orphaned.

**Reachability fixes made to SCAFFOLD.yaml while designing corners** (all inside §1.1–§1.7, no new entities/endpoints): added the `NEEDS_CLEANING -> NEEDS_REPAIR` RentalUnit condition edge so `ERR_REPAIR_ATTEMPTS_EXHAUSTED` is reachable; extended validation priority 15 with a deferral clause so priority 16 `ERR_RESOURCE_TERMINAL` is reachable; re-inspection side effects on Job `PROCESSING -> INSPECTED` clear completed legs' sign-off stamps without resetting `repair_attempts`; `Member.size_profile` retyped to a length-0..8 string with default `""`.

**Untouched, as required**: `workspace/` (still empty) and `worklog.md` (325 bytes, mtime 22:00) are exactly as they were. Scratch lives only in `.scratch/step2/` (`gen_corner.py`, `gen_diff.py`, `run_corner.py`); the parent `.scratch/` was never deleted. No sibling task directory was listed, globbed, grepped, or read at any point.

Orchestrator verification: `grep -n "harder than expert"` across all three scaffold files returned zero hits; `grep -n "scaffold_difficulty_design|scaffold_corner_design" SCAFFOLD.yaml` returned zero hits.

## Step 3: Copy shared files — 2026-09-06T00:01:34.215Z

Copied `INSTRUCTION.md` (1424 bytes) from project root to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-06T00:23:26.868Z

PRD.md is complete at `workspace/PRD.md` — **524 lines / 125,704 bytes**, built with one `Write` plus fourteen `cat >>` heredoc appends (no single call near the 64k cap). Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, and no sibling task directory was read. `SCAFFOLD*.yaml`, `worklog.md` and `.scratch/` (other than my own `.scratch/step4/`) are untouched.

## Section list
`# Apparel Rental Subscription Operations API — Product Requirements Document`
- **§1 Introduction**
- **§2 Global Specifications & System-Wide Principles** — 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim fixed block) · 2.3 Pagination · 2.4 Resource Identity, Timestamps, Versioning and the Logical Clock · 2.5 Path Resolution and the Validation Ladder · 2.6 Optimistic Concurrency on the Two Repeatable Writes · 2.7 Money, Rounding and the Two Conserved Quantities · 2.8 The Two-Dimensional Unit State Model · 2.9 Cascade Discipline and Recomputation Duties · 2.10 Warehouse Duty Segregation and Technician Fitness
- **§3 Business Logic & Workflows** — 3.1 Catalog Acquisition, Depth Planning and Fleet Build-Out · 3.2 Membership Lifecycle and Plan Entitlements · 3.3 The Availability Engine: Matching, Waitlisting and Swaps · 3.4 Outbound Fulfilment, Delivery and Carrier Exceptions · 3.5 Return Initiation, Receipt and Late-Return Fees · 3.6 Reverse Logistics: Inspection, Reconditioning and Restock · 3.7 Damage, Loss, Disputes and the Fee Ledger · 3.8 Retirement and Resale Recovery · 3.9 Reading the Fleet Back: Personalization, Demand Signals and Per-Garment Economics
- **§4 API Endpoints** (status-code paragraph + 4-column table)
- **§5 Error Codes** (2-column table) — file ends at the last error row, no audit footer

## Coverage
| Item | Scaffold | Documented |
|---|---|---|
| Entities / fields | 13 / 152 | 13 / 152 |
| Endpoints | 68 | 68 (all in §4; 13 marked 201, rest 200) |
| State machines / transitions | 7 / 67 | 7 / 67 |
| Calculations (incl. 2 invariants) | 14 | 14, every constant literal present |
| Validations (with rank) | 50 | 50, each tagged with its explicit rank number |
| Errors | 60 | 60 in §5, and every one also named in prose |
| Roles | 5 | 5 |
| Concurrency rules | 2 | 2 |

## Contract reports

```
Field coverage check:
- entities[].fields: 131 required, 131 present, 0 missing
- endpoints[].request_body: 64 required, 64 present, 0 missing
- endpoints[].query_params: 47 required, 47 present, 0 missing
- endpoints[].path_params: 13 required, 13 present, 0 missing
  (158 unique names; verified twice — word-level pass and exact `name` backtick pass)
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 50 checked, 50 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write action + expected_member_version / expected_rental_unit_version + ERR_STALE_MEMBER_VERSION / ERR_STALE_UNIT_VERSION + 412 all named), 0 missing
- state_machines[].transitions: 67 checked, 67 fully expressed, 0 missing
- calculations[]: 14 checked, 14 fully expressed, 0 missing
- validations[] conditions: 50 checked, 50 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 35 endpoints (116 bullets) checked, 35 expressed, 0 missing
- entities[].fields[] structured content: 152 checked, 152 reconstructible from prose (all 34 defaults stated), 0 missing
- sibling-branch symmetry: 11 groups checked, 11 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 1315
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

No pseudocode operators, no fuzzy quantifiers, no "and so on" survive outside the fixed §2.2 JSON block (scanned for `==`, `!=`, `>=`, `<=`, `IN {`, `round_half_up(`, `min(`, `max(`, `ceil(`, `+=`, bare `AND`/`OR`/`NOT`, "approximately", "roughly", "conservatively", "etc.").

## Verbatim last 30 lines

```
| `ERR_UNIT_CONDEMNED` | 409 |
| `ERR_OPEN_CLAIM_BLOCKS_RESTOCK` | 409 |
| `ERR_REPAIR_PENDING` | 409 |
| `ERR_REPAIR_ATTEMPTS_EXHAUSTED` | 409 |
| `ERR_DISPUTE_ROUNDS_EXHAUSTED` | 409 |
| `ERR_DISPUTE_WINDOW_CLOSED` | 409 |
| `ERR_SIZE_NOT_IN_SIZE_RUN` | 422 |
| `ERR_UNIT_NOT_ALLOCATABLE` | 409 |
| `ERR_UNIT_TURNS_EXHAUSTED` | 409 |
| `ERR_INVALID_SUPERSEDE_TARGET` | 422 |
| `ERR_LISTING_ALREADY_ACTIVE` | 409 |
| `ERR_FEEDBACK_NOT_ELIGIBLE` | 409 |
| `ERR_FEEDBACK_ALREADY_EXISTS` | 409 |
| `ERR_SHIPMENT_EXCEPTION_CAP_REACHED` | 409 |
| `ERR_SHIPMENT_ALREADY_EXISTS` | 409 |
| `ERR_INVALID_RENTAL_WINDOW` | 422 |
| `ERR_WINDOW_IN_PAST` | 422 |
| `ERR_UNIT_WINDOW_COLLISION` | 409 |
| `ERR_SHIPPING_CADENCE_COLLISION` | 409 |
| `ERR_LISTING_WINDOW_OPEN` | 409 |
| `ERR_UNIT_HAS_ACTIVE_COMMITMENT` | 409 |
| `ERR_UNIT_NOT_RETIRED` | 409 |
| `ERR_ITEM_SLOTS_EXHAUSTED` | 409 |
| `ERR_SWAP_ALLOWANCE_EXHAUSTED` | 409 |
| `ERR_WAIVER_NOT_AVAILABLE` | 409 |
| `ERR_NOTHING_TO_CHARGE` | 409 |
| `ERR_SETTLEMENT_EXCEEDS_BALANCE` | 422 |
| `ERR_SALE_PRICE_BELOW_FLOOR` | 422 |
| `ERR_OUTSTANDING_BALANCE` | 409 |
| `ERR_UNITS_STILL_OUT` | 409 |
```

One judgement call to flag: the scaffold makes `acquisition_cost_cents` optional on rental-unit creation without stating a default, so the PRD specifies it defaults to the parent style's `acquisition_cost_cents` — the least-inventive reading.

Orchestrator anti-truncation verification: `wc -l` = 524; tail is the final `ERR_UNITS_STILL_OUT` row of the §5 table, a real section boundary (not mid-sentence). §4 table holds exactly 68 method rows; §5 table holds exactly 60 `ERR_` rows. Leak grep for "harder than expert" / "expert_plus" / "scaffold" in PRD.md returned zero hits. PRD accepted without regeneration.

## Step 6: Generate implementation — 2026-09-06T02:17:28.000Z

Done. Task 2957 implementation is complete, verified, and green on my own end-to-end smoke suite.

## Files written (`workspace/implementation/`, 3,990 lines total)

| file | lines | contents |
|---|---|---|
| `start.sh` | 10 | `set -euo pipefail`, `cd "$(dirname "$0")"`, **guarded** install (`if ! python3 -c "import flask"`), `exec python3 app.py` (foreground, chmod +x) |
| `requirements.txt` | 1 | `flask>=2.0` |
| `app.py` | 66 | 7 blueprints, `before_request` per-request `g.touched` reset, `ApiError`/404/405/500 handlers, `app.run(host="0.0.0.0", port=int(os.environ.get("PORT","10000")))`. **No seeding anywhere.** |
| `core.py` | 354 | enums/constants, `DB = {name: {} for name in COLLECTIONS}` (13 in-memory dicts), logical clock, `ERROR_STATUS`, envelope helpers |
| `calc.py` | 573 | all 14 calculations + query helpers |
| `serialize.py` | 252 | 13 projections, computed fields derived at read time |
| `services.py` | 332 | `touch`, ledger append, delinquency edges, allocation/waitlist promotion, retirement, shipment loss, receipt cascade, fork-join |
| `guards.py` | 278 | the 50-rule ladder primitives incl. rank 25 SoD, rank 26 certification, rank 27 suspension |
| `routes_catalog.py` | 315 | 17 endpoints |
| `routes_members.py` | 245 | 12 |
| `routes_reservations.py` | 374 | 9 |
| `routes_shipments.py` | 257 | 7 |
| `routes_logistics.py` | 442 | 10 |
| `routes_claims.py` | 280 | 7 |
| `routes_resale.py` | 211 | 6 |

## Coverage (all programmatically cross-checked against SCAFFOLD.yaml)

- **Endpoints: 68/68.** `app.url_map` enumerates exactly 68 non-static rules; set-diff against the scaffold's 68 `endpoints:` entries returns `spec-not-impl: []` / `impl-not-spec: []`.
- **Entities: 13/13** (13 `DB` collections, 13 serializers). **State machines: 7/7. Calculations: 14/14. Validations: 50/50** in exact global ladder order (max priority rank 57). **Roles: 5/5** (`Member`, `WarehouseTech`, `ClaimsAdjuster`, `InventoryPlanner`, `PlatformAdmin`).
- **Errors: 60/60** present in `ERROR_STATUS` with **zero http_status mismatches** against the catalog, and every one of the 60 is actually raised somewhere outside core.py (no dead codes).

## Smoke test (my own script, `.scratch/step6/smoke.py`, PORT=48317) — **FAILURES: 0**

Full lifecycle passed: plan/style/unit/technician/member creation → reservation `MATCHED` on create → outbound shipment dispatch → delivery → `IN_POSSESSION` → clock advance → return-initiation (inbound leg 201) → dispatch → receipt → `RETURNED` with `rental_days 8, late_days 1, late_fee 500` → job inspection (`PROCESSING`, both legs, cost 1200) → repair completion → cleaning completion (`READY_FOR_PHOTO`, cost 5400) → photography → claim assessment (`MODERATE`, residual 16000, gross 9000, net 9000) → charge → ledger `LATE_FEE 500 / DAMAGE_FEE 9000` running balance 9500 → dispute → `OVERTURNED` reversal (outstanding back to 500, claim `DISMISSED`, net 0) → restock (unit `IN_STOCK`/`FLOOR_READY`, turns 1, servicing 6200, revenue 6000) → retirement → resale listing (base 12800, fee 2304, net 9596) → sale `SOLD` → `unit-economics` both variants → `personalization-summary` → `damage-risk?variant=ROLLING_12M`.

Negative paths confirmed: `ERR_DUPLICATE_CODE`, `ERR_SIZE_NOT_IN_SIZE_RUN`, `ERR_INVALID_RENTAL_WINDOW`, `ERR_SHIPMENT_ALREADY_EXISTS`, `ERR_REPAIR_PENDING` (cleaning before repair), `ERR_SEGREGATION_OF_DUTIES`, `ERR_OPEN_CLAIM_BLOCKS_RESTOCK`, `ERR_STALE_UNIT_VERSION` (412), `ERR_LISTING_WINDOW_OPEN`, `ERR_SALE_PRICE_BELOW_FLOOR`, and the ladder head `ERR_MISSING_AUTH_HEADERS`/`ERR_UNKNOWN_ROLE`/`ERR_ACTOR_NOT_FOUND` (all 401 per PRD line 15/25) → `ERR_ROLE_NOT_PERMITTED` (403) → `ERR_PLAN_NOT_FOUND` → `ERR_INVALID_PAGINATION` → `ERR_INVALID_ENUM_VALUE` → `ERR_INVALID_REQUEST` → `ERR_NOT_FOUND`.

Three earlier "failures" were **smoke-script expectation bugs, not implementation bugs**, and I corrected the script: (a) `charge` returned 409 `ERR_NOTHING_TO_CHARGE` because the fixture member had `waiver_active: true` and the waiver absorbed the whole 9,000-cent fee — rank 53 firing is correct; (b) `variant=TRAILING` is not a declared variant (PRD §3.9 declares `LIFETIME`/`ROLLING_12M`), so 422 was right; (c) I had expected 422/404 for `ERR_UNKNOWN_ROLE`/`ERR_ACTOR_NOT_FOUND` but the PRD says both are **401**.

**Fresh-boot / no-state verification:** booted cleanly on 4 different ports (48317, 51993, 51994, 51995) via `PORT=… bash start.sh`; all 12 listable collections return `total_count: 0` on a fresh process; zero tracebacks in the server log. Every server was killed by its **specific PID resolved from `ss -ltnp` on its own port** — no pattern kills. Sibling scratch dirs (`step2/step4/step5/step7`) are intact; I wrote only inside `workspace/implementation/` and `.scratch/step6/`.

## PRD ambiguities resolved (reading chosen)

1. Computed fields derived at **read time**, never persisted, so cascades can't leave them stale.
2. `touch()` is **idempotent per request** — at most +1 version per entity per request (PRD §2.6: "a successful swap increments the member's version by 1").
3. Style version is **not** bumped by depth/demand recomputation cascades (the scaffold only says "increments X.version by 1" for units/members).
4. Member version bumped only where explicitly stated or where a stored member field changes; bare ledger appends and assessment-time waiver recomputation do not bump it.
5. `occupied_until_date` rendered `YYYY-MM-DD` (every instant field ends `_at`, every date field `_date`).
6. Range/format violations use `ERR_INVALID_REQUEST` (400) at rank 8 — there is no dedicated validation error.
7. Unit `size` outside the parent style's `size_run` → `ERR_SIZE_NOT_IN_SIZE_RUN` (422), but `ERR_INVALID_ENUM_VALUE` first when the value is not a declared size at all.
8. Rank 5 vs 6: member-id paths compare as strings so **ownership precedes existence**; other resources resolve the row first, then check ownership.
9. Ranks 15/16 do not apply to fit-feedback (a create, not a transition), keeping rank 36 reachable.
10. Dispatch: rank 15 judges only the shipment's own state; the linked-reservation precondition runs **after** rank 38 (so a capped EXCEPTION leg reports `ERR_SHIPMENT_EXCEPTION_CAP_REACHED`) and reports `ERR_INVALID_STATE_TRANSITION` — no dedicated code exists.
11. Cleaning-completion rank 15 checks only the job (`PROCESSING` + `cleaning_required` + not yet completed), not the unit's condition, so rank 23 `ERR_REPAIR_PENDING` stays reachable (smoke-confirmed).
12. Quarantine clearance sets `cleaning_required := true` and moves `INSPECTED → PROCESSING` (PRD §3.6: "a quarantined garment therefore always passes through the cleaning leg… regardless of what its `soil_level` said"), resolving the otherwise-deadlocked path.
13. PARTIAL re-pricing uses `member_waiver_used_excluding(member_id, claim_id)` so a claim never double-counts itself.
14. UPHELD double-billing guard keys on `claim_has_unreversed_damage_fee(claim_id)`.
15. Zero-amount audit `WAIVER_CREDIT` on full absorption **is** written — PRD §3.7 wins over SCAFFOLD line 1561, which says it is not.
16. Waitlist promotion fires from restock, MATCHED release, retirement and delinquency hop 5; **cancellation does not promote**.
17. Retirement from `PROCESSING` closes the turn only when the job was already in `CONDEMNED_HOLD`.
18. Rank 27 `ERR_TECHNICIAN_SUSPENDED` applied to every WarehouseTech-callable **write** (5 shipment + 7 reverse-logistics), not to GETs — PRD line 156 "only an ACTIVE technician may **act** on reverse-logistics work" reads as actions.
19. Charge's "member not CANCELLED" precondition reports `ERR_MEMBER_NOT_ACTIVE` (409) at the rank-14 slot, before 15/16.
20. Assessment's "linked job carries at least one inspection" reports `ERR_INVALID_STATE_TRANSITION` (no dedicated code).
21. Unit condition on inspection assigned by **target state**, not edge matching — covers the declared FLOOR_READY edges plus the two re-inspection edges (`NEEDS_CLEANING→NEEDS_REPAIR`, `NEEDS_REPAIR→CONDEMNED`).
22. New damage claims initialise the four money fields to **0**, not null (matching the job's `servicing_cost_cents at 0` precedent).
23. Photography/restock's "unit must be FLOOR_READY" check sits **after** rank 27 so rank 21 `ERR_UNIT_CONDEMNED` stays reachable.

Orchestrator note: Step 6 was launched concurrently with the Step 5 continuation agent, but because the original Step 5 agent had already created `test_suite/` before dying, Step 6 no longer had *physical* isolation from the test artifacts. Isolation was enforced by explicit hard prohibition in the Step 6 prompt (no read/list/glob/grep of `test_suite/`, `test_helpers/`, or either design index) instead. The agent confirmed it built strictly from INSTRUCTION.md + SCAFFOLD.yaml + PRD.md and never ran pytest.

## Step 5: Generate unit tests — 2026-09-06T02:57:46.000Z

Orchestrator note on execution: the FIRST Step 5 agent was killed mid-run by an infrastructure API error ("The system encountered an unexpected error during processing") after it had completed all 9 files of `test_helpers/` and the first 4 files of `test_suite/` (test_01..test_04, conftest.py). It returned no agentId, so it could not be resumed via SendMessage. Rather than respawn a fresh full-suite generator (which would make the suite diverge from itself and rewrite the completed helpers), the orchestrator computed the exact remaining work — `grep -rhoP '^\s*Design:\s*\K.*' test_suite/*.py` diffed against every non-stub instance in both design indices — wrote the 62-instance to-do list to `.scratch/step5/remaining.txt`, and spawned an append-only continuation agent scoped to that list, forbidden from rewriting anything already on disk. Of the 48 `Design:` tag lines already present, 42 were unique; the 6 duplicates are each a single design instance that the first agent legitimately split into two sub-case test functions within one file (e.g. at-edge and one-past-edge), so they were left as-is.

Continuation agent's verbatim summary:

Step 5 continuation is complete. All remaining tests are written; nothing pre-existing was regenerated or restructured.

## New files (this resumed run)

| File | Lines | Tests | Design instances |
|---|---|---|---|
| `test_suite/test_09_damage_claims_and_ledger.py` | 831 | 15 | 11 |
| `test_suite/test_10_retirement_and_resale.py` | 628 | 13 | 10 |
| `test_suite/test_11_personalization_and_economics.py` | 594 | 10 | 6 |
| `test_suite/test_12_access_control_and_identifiers.py` | 433 | 9 | 7 |

Files `test_05`–`test_08` (479/411/661/555 lines, 36 tests) were already on disk from the earlier part of the run and were left untouched, as were `test_01`–`test_04` and `conftest.py`.

## Coverage

- **62 of 62** instances in `.scratch/step5/remaining.txt` are covered. **Zero skips** — every instance had verbatim PRD coverage and a uniquely-derivable outcome, so no gaps to report.
- `grep -rhoP '^\s*Design:\s*\K.*' test_suite/*.py | sort -u | wc -l` → **104** (42 pre-existing tags from `test_01`–`test_04` + the 62 to-do instances).
- 131 test functions in the suite, every one carrying exactly one `Design:` line; a programmatic check confirms every tag resolves to a real instance name in `SCAFFOLD_CORNER_DESIGN.yaml` / `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (0 malformed, 0 unknown, 0 dual-tagged).
- `pyflakes` is clean on both files written this session.

## Helper changes

`test_helpers/constants.py` only, append-only (498 → 526 lines), two appends: dispute/settlement literals earlier, then a "Personalization and long-horizon economics" block (`SHIP_DATE_AUG_13`, `SHIP_DATE_JUN_05_2025`, `CARRIER_OUT_JUN_05_2025`, `CARRIER_IN_JUN_11_2025`, `CLOCK_JUN_05_2025`, `CLOCK_JUN_11_2025`, two feedback comment strings). Needed because the rolling-12-month damage-risk read requires a 2025 turn and a second 2026 turn whose `planned_ship_date` clears the rank-43 cadence window of the first. No existing helper was renamed, reorganised or corrected — `test_users.py` already had the correct `""`-valued blank-header builders, which file 12 reuses.

## Notable content of the last two files

- File 11 pins the §3.9 arithmetic that only one evaluation order produces: `avg_margin_per_turn_cents == -20556` with explicit falsification against the aggregate-first `-61667` and the truncated `-20555`; REALIZED (3 units) vs PROJECTED (1 notional unit, 38400/24000/9000/2400/200) divergence under identical field names; LIFETIME 40/`ELEVATED` vs ROLLING_12M 0/`LOW` from one stored claim fourteen months old.
- File 12 covers the pre-business rungs: twelve path-id families each answering their own 404 (plus a `len({...}) == 12` guard that a shared generic code would fail), rank-7 body FKs naming the referenced family and beating the rank-13 OCC token, rank-1/2 header refusals, rank-3 actor resolution proven to read a different table per role, rank-4 role exclusivity split across three tests to stay inside the citation budget, rank-5 ownership between two peers on one plan, and the shared release operation for Member and PlatformAdmin.

Both test directories are at the task root (no `test_helpers/`or `test_suite/` under `workspace/`); `workspace/`, `worklog.md` and the `SCAFFOLD*.yaml` files were not created or modified; no server was started; scratch work stayed in `.scratch/step5/` with sibling step dirs (`step2`, `step4`, `step6`, `step7`) intact.

Orchestrator verification of the combined artifact: 13 files in `test_suite/` (conftest + 12 test modules), 9 in `test_helpers/`, **131 test functions**, `python3 -m py_compile` clean across all of both directories, 104/104 unique `Design:` tags, and `ls workspace/` shows only `INSTRUCTION.md`, `PRD.md`, `implementation` — no stray test dirs under workspace/.

## Step 7: Run tests and iterate — 2026-09-06T03:19:24.000Z

Done. All 8 rounds pass 131/131.

## Summary

**Iterations run:** 2 (each an 8-round parallel stability sweep, 131 tests per round).

Iteration 1 surfaced 4 failures, deterministic in all 8 rounds (no flakiness anywhere in the suite).

**Tests deleted:** none. Every failing test cited a verbatim PRD sentence and passed the unique-derivability check.

**Fixes applied to `test_suite/`**
- `test_suite/test_04_swaps_and_concurrency.py`, `test_swap_below_the_monthly_cap_succeeds_up_to_exact_equality` — the test swapped twice off the same chain (`first → second → third`) but then asserted `second` was still `MATCHED`. PRD §3.3 says "The original reservation moves `MATCHED → SUPERSEDED`", and `second` is the reservation the *second* swap was aimed at, so `SUPERSEDED` is required. Corrected to `SUPERSEDED` and added the complementary assertion that `third` rests in `MATCHED` with `superseded_reservation_id == second["id"]` — strictly more faithful to PRD, not less.

**Fixes applied to `implementation/`**
- `routes_logistics.py`, inspection handler (job-destination block) — the branch read `elif not biohazard_flag: READY_FOR_PHOTO`, so a biohazard inspection with `soil_level=NONE` and `damage_severity=NONE` matched no branch and the job was left resting in `INSPECTED`. PRD §3.6 requires the job to leave `INSPECTED` within the same request for one of three destinations; `CONDEMNED_HOLD` is conditioned on `LOSS` and `READY_FOR_PHOTO` explicitly requires "`biohazard_flag` false", leaving `PROCESSING` as the only destination. Now routes biohazard to `PROCESSING`.
- `routes_logistics.py`, `quarantine_clearance` — removed the `if job["state"] == "INSPECTED": job["state"] = "PROCESSING"` patch. It was a workaround for the bug above, is unreachable once inspection routes correctly, and PRD states clearance "moves the unit `QUARANTINED → NEEDS_CLEANING` and sets `quarantine_hold` back to false" with no job-state effect.
- `routes_shipments.py`, `dispatch_shipment` — the "linked reservation must be `MATCHED`" precondition was applied on the `EXCEPTION` recovery path as well. Because the first dispatch cascades the reservation `MATCHED → SHIPPED`, this made two verbatim PRD behaviours unreachable: "A leg may therefore cycle `IN_TRANSIT → EXCEPTION → IN_TRANSIT` exactly once via re-dispatch" and the loss branch "On an `OUTBOUND` leg the reservation moves `SHIPPED → WAITLISTED`" (reaching `exception_count == 2` requires a re-dispatch). The precondition is now scoped to the `CREATED` path, which is the hop that actually drives the reservation forward. `INBOUND` is unaffected (its reservation stays `RETURN_INITIATED` across the cycle).
- `routes_shipments.py`, `dispatch_shipment` cascade — guarded the reservation cascade on the declared edge (`res["state"] == "MATCHED"`), so a re-dispatch does not re-stamp `shipped_at` on an already-`SHIPPED` reservation. The unit hop already had the equivalent `RESERVED` guard.

**Fixes applied to `test_helpers/`:** none needed — no shared fixture bug was implicated.

**Final sweep evidence** (`workspace/implementation/results.$i.json`, i = 1..8): 131/131, 131/131, 131/131, 131/131, 131/131, 131/131, 131/131, 131/131 — 0 failed, 0 errors, 0 skipped in every round.

`worklog.md` was not touched (mtime still 02:58, before this session began).

Orchestrator independent verification: re-read all 8 `results.$i.json` directly — every round reports `passed=131 total=131 failed=0 errors=0 skipped=0`, all eight files written at 03:11 (a real completed sweep, not a stale or partial one). Grepped `.scratch/step7/round.*.log` for `Terminated`: zero hits, so no sweep-reaping contaminated the run. Step 8 will NOT be skipped — Step 7 applied 4 `implementation/` fixes and 1 `test_suite/` fix.

## Step 8: Finalize PRD — 2026-09-06T03:30:22.000Z

Done. `PRD_FINALIZED.md` written with three surgical edits (four `Edit` calls, two of which were softening revisions of my own draft wording before commit).

## Size
- `PRD.md`: 524 lines / 125,704 bytes
- `PRD_FINALIZED.md`: 524 lines / 127,214 bytes
- Line delta 0.0% (all edits are intra-paragraph); byte delta **+1.20%**

## Changes
- **§3.6 (inspection job destination, PRD ¶ "Within the very same request…")** — *revise* — the second `Otherwise` branch now also routes on `biohazard_flag` true, so a biohazard inspection with `soil_level=NONE` and `damage_severity=NONE` goes `INSPECTED → PROCESSING` instead of matching no branch — `routes_logistics.py:217-228`
- **§3.6 (quarantine clearance)** — *insert* — clearance sets the job's `cleaning_required` to true when it was not already true, and does **not** move the job's `state` — `routes_logistics.py:351-357`
- **§3.4 (dispatch)** — *revise* — the linked-reservation precondition (`MATCHED` / `RETURN_INITIATED`, `ERR_INVALID_STATE_TRANSITION` 409) is scoped to the `CREATED` hop only; member-`ACTIVE` on `OUTBOUND` stays on both paths; the `EXCEPTION` recovery path does not re-examine the reservation — `routes_shipments.py:143-171`
- **§3.4 (dispatch cascade)** — *insert* — both cascade hops fire only on their declared source states (`MATCHED` for the reservation, `RESERVED` for the unit), so a re-dispatch does not re-stamp `shipped_at` — `routes_shipments.py:178-188`

No edit for the `test_suite/test_04` swap fix: PRD §3.3 already pins `MATCHED → SUPERSEDED` and `superseded_reservation_id`, and `routes_reservations.py:236-244` matches verbatim — that item was a pure test bug.

## Per-edit pre-edit search log

**Edit 1 — biohazard job destination**
- (a) Subject: which state a job leaves `INSPECTED` for, and whether a job can rest in `PROCESSING` with no fork leg.
- (b) Enumerated: `routes_logistics.py:216-228` (destination block, shared by first inspection *and* re-inspection via the same handler); `routes_logistics.py:170-181` (unit condition precedence — biohazard outranks `LOSS`, but the destination block keys `LOSS` first, so branch order is preserved); `services.try_join` (`services.py:316-323`, only exit from `PROCESSING`, requires `quarantine_hold` false); `routes_logistics.py:334-358` (clearance is what flips `cleaning_required`, making the `PROCESSING` rest state escapable — confirmed no deadlock); `services.retire_unit` / `JOB_DRAIN_STATES` (`services.py:203-232`, drains any job state to `CONDEMNED_HOLD`); `calc.py:353` (cleaning cost is 0 for `soil_level=NONE`, so `cleaning_required=true` on a biohazard job adds no money); grep of `READY_FOR_PHOTO|CONDEMNED_HOLD` across all modules to confirm no second destination site.
- (c) Kept the third `Otherwise` clause verbatim (it already reads "`biohazard_flag` false"), so the edit adds a disjunct rather than re-partitioning the branch set; kept "one of three destinations" intact.

**Edit 2 — quarantine clearance effects**
- (a) Subject: everything a quarantine clearance mutates.
- (b) Enumerated: `routes_logistics.py:334-358` (the handler — unit hop, `quarantine_hold`, conditional `cleaning_required` flip, no job-state write, no `try_join` call); `cleaning_completion` / `repair_completion` rank-20 guards (`:249`, `:289`) confirming clearance is the only unblock; `services.try_join` (join fires on the next sign-off, not on clearance); PRD §2.10 rank 26 (`repair_certified`) consistency.
- (c) My first draft said "The clearance moves nothing else" — that is a false universal (it does `touch()` the unit, and the job when the flag flips, which under §2.9 bumps versions). Revised to the narrow claim "does not move the job's own `state`". Also worded the flag as "to true when it was not already true", which leaves impl's no-bump-when-already-true behavior consistent rather than contradicted.

**Edit 3 — dispatch linked-reservation precondition**
- (a) Subject: dispatch preconditions, and which of them apply on the `EXCEPTION` recovery path.
- (b) Enumerated: `routes_shipments.py:132-171` (whole handler: rank 14 member-`ACTIVE` is `OUTBOUND`-only and precedes the state guards on *both* paths; rank 16/15; rank 38 recovery-only; the reservation check now `CREATED`-only); `create_shipment` (`:28-87`, rank 39 `EXCEPTION` escape hatch and rank 43 cadence — neither reads reservation state); `exception_shipment` (`:224-248`) and `services.shipment_loss` (`services.py:238-264`) to confirm the `SHIPPED → WAITLISTED` and `RETURN_INITIATED → CLOSED` branches this unblocks; `return_initiation` (`routes_reservations.py:252+`) as the only other inbound-leg creator; `core.py:261` for the 409 status of `ERR_INVALID_STATE_TRANSITION`; PRD line 190's rank-14 five-operation list and the §4 endpoint row for consistency.
- (c) Explicitly wrote "the member must be `ACTIVE` **on either path**" so splitting the sentence does not accidentally scope rank 14 to `CREATED` too; named the error code/status rather than inventing a new rank number (impl assigns none).

**Edit 4 — dispatch cascade guards**
- (a) Subject: the `OUTBOUND` dispatch cascade onto the reservation and the allocated unit.
- (b) Enumerated: `routes_shipments.py:178-188` (both guards); `deliver_shipment` (`:211`, the parallel `SHIPPED` guard on the next hop); `services.shipment_loss` (`:251`, `:257` — the only paths that could put an `EXCEPTION` leg's reservation in a non-`SHIPPED` state, and they coincide with `exception_count == 2`, which rank 38 blocks from re-dispatch); `promote_for_freed_unit`/`promote_for_style` as the only route back to `MATCHED`.
- (c) Dropped a trailing "only the leg's own `dispatched_at` moves" clause (false universal — `carrier_reference` and versions also move), and hedged with "normally already `SHIPPED`" so the sentence stays true even in the theoretically-reachable-only-via-promotion case where the guard would fire.

Orchestrator verification: `cmp` confirms PRD_FINALIZED.md is NOT byte-identical to PRD.md (a real patch was produced, as expected given Step 7's 4 implementation fixes).

## Step 9: Complete PRD — 2026-09-06T03:59:38.396Z

Orchestrator decision: Step 9 was run as THREE SEQUENTIAL module-partitioned passes over one shared `PRD_COMPLETED.md`, rather than as a single agent. A lone agent asked to scan ~4,000 lines of implementation against a 125KB PRD reliably under-scans and can produce a file byte-identical to its input (which would mean the scan never ran). Pass 1 owned the `cp` that creates the file; passes 2 and 3 were explicitly forbidden from copying, so they extend rather than clobber. Partition: pass 1 = `app.py`, `core.py`, `guards.py`, `serialize.py`, `routes_catalog.py`, `routes_members.py`; pass 2 = `calc.py`, `services.py`, `routes_reservations.py`, `routes_shipments.py`; pass 3 = `routes_logistics.py`, `routes_claims.py`, `routes_resale.py`. Each pass could read any module for wording context but audited only its own.

**Aggregate result: 62 edits — 45 ambiguity-pins, 15 mismatch-revisions (pass 1: 15+7, pass 2: 12+6, pass 3: 18+2).** `PRD_FINALIZED.md` 524 lines / 127,214 chars → `PRD_COMPLETED.md` 527 lines / 148,748 chars (**+21,534 chars, +16.9%**; only +3 lines, so essentially all edits are in-paragraph inserts/revisions, no new sections).

### Pass 1 (app.py, core.py, guards.py, serialize.py, routes_catalog.py, routes_members.py) — 15 ambiguity-pins, 7 mismatch-revisions

- §2.1 — revise — mismatch — header values are whitespace-stripped before the rank-1 emptiness test, so a whitespace-only header is a missing header — `guards.py:17-31`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars (24 total) — `core.py:322-326`
- §2.3 — insert — ambiguity — identical `created_at` values are ubiquitous under the logical clock; ties break on server insertion order, and that same rule governs every "ascending `created_at`" ordering in the doc — `guards.py:256-257`
- §2.3 — insert — ambiguity — empty query values equal omitted (incl. `limit`/`offset`); non-enum identifier filters and the `size` filter are opaque strings that never 404; `replenishment_flag` accepts `true/false/1/0` case-insensitively else `ERR_INVALID_REQUEST` — `guards.py:200-216`
- §2.4 — revise — mismatch — `version` advances **at most once per request** no matter how many cascade hops write the row; a row created and mutated in one request stays at 1 — `app.py:33-35`, `services.py:13-39`
- §2.4 — revise — ambiguity — clock accepts any ISO-8601 instant spelling (Z / offset / naive→UTC), may move backwards, returns 200 with `data` = `{current_utc}` only — `routes_catalog.py:307-315`, `core.py:204-216`
- §2.5 (rank 6) — insert — mismatch — rank 5 precedes rank 6 only when the path carries `member_id`; for row-owned resources the row is resolved first, so 404 outranks `ERR_NOT_RESOURCE_OWNER` — `routes_members.py:212-217`
- §2.5 (rank 7) — insert — ambiguity — a body FK that is `null` or non-string is skipped at rank 7 and reported at rank 8 — `guards.py:92-102`
- §2.5 (rank 8) — insert — ambiguity — rank 8 owns all format/length/charset/range checks; non-string enum value is rank 8 not rank 9; strict booleans; JSON `null` == absent; absent/empty/`null` body == `{}`; other non-object bodies 400; undeclared fields ignored — `guards.py:77-183`
- §2.10 — revise — ambiguity — `employee_code` unique, 2–16 chars, no charset restriction; `full_name` >=1 char — `routes_catalog.py:71-79`
- §2.10 — insert — ambiguity — technician PATCH takes any subset of the three fields, omitted keep stored values; `employee_code`/`full_name` not revisable; no terminal state — `routes_catalog.py:86-100`
- §2.10 — insert — ambiguity — technician list's only domain filter is `status` (`ACTIVE`/`SUSPENDED`) — `routes_catalog.py:110-119`
- §3.1 — revise — ambiguity — plan `name` >=1 char, no upper bound — `routes_catalog.py:33`
- §3.1 — revise — ambiguity — `style_code` has no charset restriction; `brand` >=1 char, no upper bound — `routes_catalog.py:130-132`
- §3.1 — insert — mismatch — unit `size` outside `size_run` yields `ERR_SIZE_NOT_IN_SIZE_RUN` (422), and that check runs **before** the `unit_code` uniqueness check (rank 11) — `routes_catalog.py:218-221`
- §3.2 — revise — ambiguity — missing at-sign in `email` is `ERR_INVALID_REQUEST` (400) evaluated before uniqueness; plan FK 404 ahead of both; no other email validation or length bound — `routes_members.py:30-42`
- §3.2 — insert — mismatch — a `DELINQUENT` member cannot cancel: `ERR_INVALID_STATE_TRANSITION` (rank 15) is reported ahead of the rank-56 `ERR_OUTSTANDING_BALANCE` — `routes_members.py:145-151`
- §3.2 — revise — mismatch — member payload's `damage_risk_score`/`damage_risk_band` are recomputed fresh under `LIFETIME` at read time, not served from the persisted copy; the `damage_risk_band` list filter uses the same fresh value and accepts only LOW/ELEVATED/HIGH — `serialize.py:85-101`, `routes_members.py:78`
- §3.7 — insert — ambiguity — a `Member` listing ledger entries is force-scoped to self; a foreign `member_id` yields `ERR_NOT_RESOURCE_OWNER` (403), not an empty page — `routes_members.py:227-230`
- §3.7 — insert — ambiguity — settlement amount bound lives only at rank 54 (no rank-8 range check); `CANCELLED` -> `ERR_RESOURCE_TERMINAL` before the amount is read; `PAUSED`/`DELINQUENT` may settle — `routes_members.py:170-180`
- §3.8 — insert — ambiguity — `retirement_reason` required and never cross-validated against condition; `SOLD` -> `ERR_RESOURCE_TERMINAL` (rank 16), any other non-origin state incl. already-`RETIRED` -> `ERR_INVALID_STATE_TRANSITION` (rank 15) — `routes_catalog.py:278-287`
- §3.9 — insert — ambiguity — `variant` is enum-typed: omitted/empty takes the default, out-of-pair value is rank-9 `ERR_INVALID_ENUM_VALUE` (422) — `routes_catalog.py:198`, `routes_members.py:195`
- §5 — insert — ambiguity — three off-ladder identifiers documented: `ERR_NOT_FOUND` 404 (unknown path), `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500; trailing slashes insignificant — `app.py:22, 41-55`

Pass 1 also flagged forward to pass 2: `routes_reservations.py:344` raises `ERR_FEEDBACK_NOT_FOUND`, absent from `core.ERROR_STATUS` (so it degrades to HTTP 400) and absent from §5.

### Pass 2 (calc.py, services.py, routes_reservations.py, routes_shipments.py) — 12 ambiguity-pins, 6 mismatch-revisions

- §2.5 — insert — mismatch — unresolvable `feedback_id` raises `ERR_FEEDBACK_NOT_FOUND` at HTTP **400**, not 404, because the id is absent from the status map — `routes_reservations.py:344` / `core.py:236-300`
- §5 — insert — mismatch — added error-table row `| ERR_FEEDBACK_NOT_FOUND | 400 |` — `routes_reservations.py:344`
- §3.3 — insert — ambiguity — `requested_size` is a free-form non-empty string, never rank-9 enum-checked; empty -> rank 8 `ERR_INVALID_REQUEST`, any value outside the style's `size_run` -> rank 31 `ERR_SIZE_NOT_IN_SIZE_RUN` — `routes_reservations.py:21,35`
- §3.3 — revise — mismatch — rank 50 applies on reservation create **only** (swap exempt; its sole fiscal guard is rank 51); plus a foreign `member_id` list filter -> `ERR_NOT_RESOURCE_OWNER` 403 raised after rank 9 and before rank 10 — `routes_reservations.py:113-116,142-146`
- §3.3 — insert — ambiguity — WAITLISTED->CANCELLED release bumps only the reservation's `version`; no unit and no member counter moves — `routes_reservations.py:189-191`
- §3.3 — revise — mismatch — promotion fires from **four** places (the delinquency unwinding is the fourth); not on a swap, not on the membership-cancellation unwinding — `services.py:70,106,231`, `routes_members.py:156-160`
- §3.3 — insert — ambiguity — retirement uses the style-wide promotion form: per distinct queued `requested_size`, the head is offered the best of the style's whole candidate set, at most one promotion per size; neither promotion form consults `item_slots` — `services.py:143-166`
- §3.3 — insert — ambiguity — swap's guard-time allowances: the about-to-be-freed unit passes rank 32 while still `RESERVED`, and the superseded reservation's interval is excluded from the rank-42 collision scan — `routes_reservations.py:224-229`
- §3.4 — revise — mismatch — rank 39: once a reservation carries an INBOUND leg it accepts no further leg of **either** direction — `routes_shipments.py:47-54`
- §3.4 — revise — mismatch — cadence window re-subjected onto the requested `planned_ship_date`; forward-only, closed at both ends, scanned over all the member's non-EXCEPTION OUTBOUND legs; an earlier-planned leg never collides; INBOUND exempt; rank-27 tech fitness evaluated ahead of rank 14 on this endpoint — `routes_shipments.py:41-70`
- §3.4 — insert — ambiguity — a delivery aimed at an INBOUND leg -> `ERR_INVALID_STATE_TRANSITION` (409) through the same rank-15 test — `routes_shipments.py:202`
- §3.4 — revise — ambiguity — the inbound-loss path resets `late_days` as well as `late_fee_cents` to 0 — `services.py:259-264`
- §3.4 — insert — ambiguity — the carrier-loss cascade runs **no** waitlist promotion; a reservation pushed back to WAITLISTED stays queued — `services.py:238-264`
- §3.5 — insert — ambiguity — a receipt failing either the state or the direction test yields rank 15 `ERR_INVALID_STATE_TRANSITION` (409) — `routes_shipments.py:261`
- §3.7 — revise — ambiguity — ledger `direction` is `DEBIT` only when `amount_cents` > 0 and `CREDIT` otherwise, so the audit-only zero-amount `WAIVER_CREDIT` lands in `CREDIT` — `services.py:53`
- §3.2 — revise — ambiguity — delinquency hop 5 also offers each freed unit to its style-and-size waitlist head; because WAITLISTED rows are cancelled before MATCHED ones are released, only another member can be promoted — `services.py:70,86-107`
- §3.9 — revise — ambiguity — `WAITLISTED` added to the rank-36 refused-state list for fit feedback — `routes_reservations.py:319`
- §3.7 — insert — ambiguity — "unreversed" defined as a replay of the claim's own entries in append order (`DAMAGE_FEE` raises a flag, `DISPUTE_REVERSAL` lowers it, everything else including `WAIVER_CREDIT` leaves it alone) — `calc.py:claim_has_unreversed_damage_fee`

Pass 2 notes: none of `calc.py`'s 14 rules needed an edit — the PRD already pins the interval geometry, `rank_candidates` ordering, depth ceiling, demand cap, fit clamp, damage-risk weights, fee floor/ceiling, resale tier arithmetic, half-on-swap turn revenue, servicing cost, late-fee cap, swap month window and per-unit-then-average economics. One near-miss avoided: `calc.damage_risk()` returns `closed_reservation_count`, which §3.9's field list omits — but `routes_members.py` pops that key before serializing, so the PRD was already correct.

### Pass 3 (routes_logistics.py, routes_claims.py, routes_resale.py) — 18 ambiguity-pins, 2 mismatch-revisions

- §3.6 job-intro — insert — ambiguity — every job action endpoint (cleaning, repair, clearance, photography, restock) responds with the job row, clearance included; only inspection returns its own record — `routes_logistics.py:265,328,358,393,441`
- §3.6 filing an inspection — insert — ambiguity — the unit-must-be-`PROCESSING` check is tested *after* rank 27 and reports `ERR_INVALID_STATE_TRANSITION` — `routes_logistics.py:134-138`
- §3.6 condition-precedence — insert — ambiguity — when no branch applies (pristine finding), `condition_state` is left untouched; grade overwrite and version bump still occur — `routes_logistics.py:171-181`
- §3.6 damage-opens-a-claim — insert — ambiguity — a new claim's four money fields open at 0; the lifetime risk refresh fires on any non-`NONE` severity even when no claim row changed — `routes_logistics.py:202-214`
- §3.6 re-inspection — insert — ambiguity — claim located by `rental_unit_id`+`reservation_id` (newest by `created_at`), `inspection_id` re-pointed, and a claim already `DISPUTED`/`CHARGED`/`WAIVED`/`DISMISSED` is neither reopened nor duplicated — `routes_logistics.py:29-38,186-212`
- §3.6 clearing a quarantine — insert — ambiguity — clearance's only preconditions are rank-16 terminality and `quarantine_hold` true (`ERR_INVALID_STATE_TRANSITION` at rank 15); no job-state guard, and it never runs the join — `routes_logistics.py:341-358`
- §3.6 the repair leg — revise — ambiguity — outstanding-leg guard also requires job `PROCESSING`, reported as rank-15 `ERR_INVALID_STATE_TRANSITION` ahead of rank 20 — `routes_logistics.py:282-290`
- §3.6 the cleaning leg — insert — ambiguity — same rank-15 outstanding-leg guard; rank 20 before rank 23, rank 27 after both; no certification required — `routes_logistics.py:242-257`
- §3.6 re-photography — revise — ambiguity — job-state failure is rank-15; the `FLOOR_READY` test runs *last*, after ranks 26 and 27 — `routes_logistics.py:371-388`
- §3.6 restock — revise — ambiguity — full guard order 15/20/21/22/27 then the `FLOOR_READY` test last; no certification required — `routes_logistics.py:406-428`
- §3.7 ¶1 — revise+insert — mismatch — `assessed_at` is *not* re-stamped by a `PARTIAL` re-price (former prose said "most recent assessment"); plus claim read/list filters, 404-before-ownership order, and `Member` confinement with `ERR_NOT_RESOURCE_OWNER` — `routes_claims.py:51-87,236-239`
- §3.7 pricing a claim — insert — ambiguity — "no inspection on the linked job" reports `ERR_INVALID_STATE_TRANSITION` (409) after ranks 16/15 — `routes_claims.py:103-113`
- §3.7 charging a claim — insert — ambiguity — `CANCELLED` member -> `ERR_MEMBER_NOT_ACTIVE` at rank 14, ahead of the claim's state guards; `PAUSED`/`DELINQUENT` charge normally — `routes_claims.py:162-168`
- §3.7 disputing a claim — insert — ambiguity — `dispute_reason` is a required string of >=1 char; empty/null/omitted -> rank-8 `ERR_INVALID_REQUEST` — `routes_claims.py:189-191`
- §3.7 `PARTIAL` verdict — insert — ambiguity — the claim's own prior waiver reservation is excluded from `waiver_coverage_used_cents` on the re-price; `assessed_at` preserved — `routes_claims.py:31-32,239`
- §3.7 `PARTIAL` verdict — insert — ambiguity — delinquency re-evaluated in both directions on the restated balance — `routes_claims.py:247-248`
- §3.7 `OVERTURNED` verdict — insert — ambiguity — only `net_fee_cents` is zeroed; residual/gross/waiver_applied stand — `routes_claims.py:267-269`
- §3.8 listing a retired unit — insert — ambiguity — creation applies no ceiling to the inherited `markdown_step`; only reprice is bounded at 3 — `routes_resale.py:76`
- §3.8 expiring a listing — insert — ambiguity — expiry leaves `listed_at` standing; only a reprice re-stamps it — `routes_resale.py:146`
- §3.8 recording a sale — insert — ambiguity — `sale_price_cents` min 0, so a negative amount is rank-8 `ERR_INVALID_REQUEST` — `routes_resale.py:186`
- §3.8 recording a sale — revise — mismatch — PRD claimed "Steps 4 through 7 are re-run"; impl re-runs only the Step-4 fee and Step-7 net. Revised to pin that Step 6's floor correction is *not* re-applied, `list_price_cents`/`floor_adjusted` are frozen, `net_recovery_cents` may fall below 2,000 cents or negative, and the fee pct is the one from the most recent pricing pass (creation *or* reprice) — `routes_resale.py:202-205`, `calc.py:322-328`

Pass 3 closing error-table consistency check: **clean.** All 25 codes raised directly by its three modules, plus the 5 raised via `guards.py`, appear in §5 with exactly the status `core.ERROR_STATUS` assigns. `ERR_FEEDBACK_NOT_FOUND` remains the only code absent from the status map anywhere in the implementation; pass 2 documented the resulting HTTP 400 rather than changing the code, per Step 9's align-PRD-to-code contract.

### Orchestrator final verification

- `PRD_COMPLETED.md` is 527 lines / 148,748 chars and is NOT byte-identical to `PRD_FINALIZED.md` (the scan genuinely ran in all three passes; each pass's edits were spot-checked as surviving by the next pass).
- `find workspace/implementation test_suite test_helpers -name '*.py' -newermt '2026-09-06 03:12'` returns nothing: no implementation or test file was modified after the clean 03:11 sweep, so the 8×131/131 result still describes the shipped code.
- `.scratch/` retains step2, step4, step5, step6, step7, step8; no pass deleted a sibling's artifacts.
- Pipeline complete through Step 9.
