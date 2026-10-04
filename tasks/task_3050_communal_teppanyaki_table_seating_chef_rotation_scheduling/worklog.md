# Worklog — task_3050_communal_teppanyaki_table_seating_chef_rotation_scheduling

Scenario: Communal Teppanyaki Table Seating & Chef Rotation Scheduling (Benihana): reservation seating that combines separate parties at a shared grill table to reach table minimums, party-size to table-capacity matching with hold windows before seating strangers together, chef rotation scheduling so each chef covers a sequence of tables with staggered show start times, course timing coordination between the sushi and grill kitchens, per-table performance duration standards affecting turn times, birthday and celebration handling with special service moments, food cost control on protein portions cooked tableside, ventilation and grill maintenance downtime scheduling

## Step 1: Create task directory — 2026-09-29T18:15:44.197Z

bash-only. Task directory `./tasks/task_3050_communal_teppanyaki_table_seating_chef_rotation_scheduling/` was pre-allocated by the caller with `workspace/` inside; verified to exist and be empty. No new index computed, no other `task_*` directory created. `./INSTRUCTION.md` confirmed present at project root (1424 bytes).

## Step 2: Generate scaffold artifacts (§1.0–§1.9) — 2026-09-29T18:56Z

Generated all three scaffold files from the scenario text and the scaffold-generator skill spec only.
Per the caller's hard constraint, no sibling `task_*/` directory, SCAFFOLD, PRD, test or implementation
was listed, globbed, grepped or read; format conventions were taken from the skill's own
`SKILL.md`, `references/claim-extraction-guide.md`, `scaffold_lint.py` and `skills/prd-bench-scaffold-generator/`.

Design summary:
- Archetype `temporal_windowing` + `quota_allocation`; layers optimistic_concurrency,
  cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, selector_policy.
  `entity_topology: flat` (prioritised), `state_machine_shape: cyclic`, `role_model: peer_roles`,
  `consistency_model: immediate`. Not a `hybrid`/`posture_driven` scaffold.
- §1.1 12 entities, all FK descriptions using the canonical `FK -> {Entity}.id` prefix.
- §1.2 10 state-machine tables / 42 transitions; §1.2.1 3 OCC concurrency rules, all on
  `common_fields: true` parents whose write endpoints declare `expected_*_version` and bump
  the parent version.
- §1.3 14 calculations; §1.4 29 validations (priorities 1–30); §1.5 55 endpoints
  (54 under `/service-floor`, plus the `/_clock/set_current_utc` test-driving endpoint whose
  startup default time is fixed at `2026-09-01T00:00:00Z`); §1.6 41 errors; §1.7 5 roles.

Difficulty directive (harder than expert) applied by pushing §1.8 depth and §1.9 breadth to the
skill's own limits: 24 §1.8 instances across all nine §0.5 rules (every rule ≥2; depth rules
carry 3–4 with genuinely different subjects/triggers/error pairs/interval semantics/conserved
quantities), and 49 §1.9 corner instances across all nine guide sections (5 `excluded_because`
stubs, 44 active).

Self-checks run before finalising:
- `python3 scaffold_lint.py .` → `VERDICT: clean lint` (1131 calls scanned).
- Placeholder closure: 0 unbound `${var}` across both design files.
- Every `grounds:` ref resolves to a declared §1.1–§1.6 element.
- Extend test (§1.8 ≥18, ≥2 per rule; §1.9 name uniqueness across both files): pass.
- No `simultaneously` / `concurrently` / `in parallel` / `first-writer-wins` / `race winner` /
  `race loser` vocabulary anywhere.
- All 41 error ids are referenced by at least one validation, transition or corner instance.
- Rounding orders, evaluation orders, selector ranking keys and tie-breaks pinned explicitly;
  no `id`-based ordering in any business decision (fallbacks use canonical fields).

Artifacts written (line counts as of this step):
- `SCAFFOLD.yaml` — 2115 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1852 lines (single top-level key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 2211 lines (single top-level key `scaffold_corner_design`)
## Step 2 (orchestrator record): Generate scaffold — 2026-09-29T18:57:10.000Z

Subagent returned summary, verbatim:

All three scaffold artifacts are written and verified.

## Files written

| File | Lines |
|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_3050_communal_teppanyaki_table_seating_chef_rotation_scheduling/SCAFFOLD.yaml` | 2115 |
| `.../SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1852 (single top-level key `scaffold_difficulty_design`) |
| `.../SCAFFOLD_CORNER_DESIGN.yaml` | 2211 (single top-level key `scaffold_corner_design`) |

## Counts

- Entities: **12**
- State machines: **10** tables / **42** transitions
- Concurrency rules (§1.2.1): **3**
- Calculations: **14**
- Validations: **29** (priorities 1-30)
- Endpoints: **55** (54 under `/service-floor` + `/_clock/set_current_utc`)
- Errors: **41**
- Roles: **5**
- **§1.8 difficulty instances: 24** across all nine §0.5 rules — `dual_variant_calc` 4, `combinatorial_formula` 2, `non_linear_state_machine` 3, `transitive_cascade` 3, `priority_pair_validation_conflict` 2, `boundary_precision_check` 2, `cross_entity_state_dependency` 2, `resource_temporal_overlap` 2, `compensating_invariant` 4
- **§1.9 corner instances: 49** across all nine claim-extraction-guide sections (5 `excluded_because` stubs, 44 active)

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    55
  §1.1 entities declared:     12
  §1.8 instances scanned:     24
  §1.9 instances scanned:     44
  Calls scanned (§1.8+§1.9):  1131

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Key design decisions

Applied the difficulty directive by raising depth and breadth to the skill's own limits rather than padding entity count: every §0.5 rule carries more than its minimum, and the extra instances are differentiated as the rules demand (different entity domains, different formula modes from {(a),(b),(c)}, different triggering transitions, different error-category pairs, opposite interval semantics, different conserved quantities).

- Archetype `temporal_windowing` + `quota_allocation`; `entity_topology: flat` and `state_machine_shape: cyclic` — both flagged "0% / PRIORITIZE" in §0.3, and deliberately not `hybrid`/`posture_driven` (the over-represented shapes).
- Three arithmetic invariants are fully pinned and hand-computed into literals: the band-then-ceil true-up (1000→band 1 factor 0.50→500 vs 1200→band 2→725), the closed-interval sushi-counter rule versus the half-open grill-table rule, and the two-pass credit-cap evaluation order (13500→cap 1620, not the 1425 the naive order gives).
- Concurrency rules were kept to three after applying §1.2.1's serial-observability filter — most apparent races here reduce to state preconditions, so they live in §1.2/§1.4 with 412 reserved for genuine OCC staleness.
- The test-driving `/_clock/set_current_utc` endpoint states the mandated `2026-09-01T00:00:00Z` startup default in its description.

Two notes worth flagging: the caller's constraint was honored throughout — no sibling `task_*/` directory, SCAFFOLD, PRD, test or implementation was listed, globbed, grepped or read; all format conventions came from the skill directory only. And `worklog.md` already existed from the caller's pre-allocation, so I appended to it rather than creating a new file.

Orchestrator verification: `wc -l` confirms 2115 / 1852 / 2211 lines; `scaffold_difficulty_design:` is the single top-level key at SCAFFOLD_DIFFICULTY_DESIGN.yaml:10; `scaffold_corner_design:` is the single top-level key at SCAFFOLD_CORNER_DESIGN.yaml:10; SCAFFOLD.yaml contains neither key (correct).

## Step 3: Copy shared INSTRUCTION.md — 2026-09-29T18:57:40.000Z

bash-only. Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` (1424 bytes) to `./tasks/task_3050_communal_teppanyaki_table_seating_chef_rotation_scheduling/workspace/INSTRUCTION.md`. Content confirmed: build contract requiring `./implementation/start.sh`, `$PORT` (default 10000), bind `0.0.0.0`, foreground server, evaluator runs `bash start.sh`.

## Orchestrator repair note (between Step 2 and Step 4) — 2026-09-29T19:05:00.000Z

The Step 4 subagent flagged a malformation in `SCAFFOLD.yaml`'s `roles:` block. Verified by YAML parse: the tail of `ProteinTicket`'s `fields` list had leaked into `roles[4] (SushiChef).shared_operations` as two mapping entries (`cost_cents`, `status`), making `shared_operations` a mixed list of strings and dicts. This is a real structural defect — downstream consumers that iterate `roles[].shared_operations` expecting strings would break.

Scope check before touching anything: `ProteinTicket.fields` in §1.1 is intact (all 9 fields including `cost_cents` and `status`), so the leaked lines are pure duplicates, not data loss. Fix applied: deleted exactly the two leaked mapping lines at SCAFFOLD.yaml:2115-2116 (backup at /tmp/SCAFFOLD.yaml.bak.3050). Nothing else was altered. SCAFFOLD.yaml is now 2114 lines.

Post-fix verification: `yaml.safe_load` succeeds; top-level keys unchanged (`scenario, domain_name, api_prefix, complexity_profile, entities, state_machines, concurrency_rules, calculations, validations, response_envelope, endpoints, errors, roles`); all `roles[].shared_operations` / `exclusive_operations` entries are now strings; counts unchanged (12 entities, 10 state machines, 55 endpoints). `python3 scaffold_lint.py` re-run → `VERDICT: clean lint` (1131 calls scanned, 24 §1.8 + 44 §1.9 instances).

Note: the same subagent also claimed the state-machine `field:` key was missing; direct inspection disproved this — all 10 state machines carry `field:`. That part of its report was inaccurate and no change was made for it.

## Step 4: Generate PRD — 2026-09-29T19:05:30.000Z

Subagent returned summary, verbatim:

All three hard contracts pass mechanically. Here is the final report.

## Output

- **Path**: `/home/ubuntu/github/CodingPRD/tasks/task_3050_communal_teppanyaki_table_seating_chef_rotation_scheduling/workspace/PRD.md`
- **Line count**: 369
- **Word count**: 10,527

## Section headings emitted

- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles`
  - `### 2.1. User and Role-Based Access Control`
  - `### 2.2. API Response Structure` (verbatim from `section-2.2-response-structure.md` — byte-for-byte confirmed, incl. `req_RANDOMALPHANUM123456`, `2025-05-24T10:30:00.123Z`, `UNIQUE_ERROR_IDENTIFIER_STRING`, `"data": { }`)
  - `### 2.3. Pagination`
  - `### 2.4. Floor-Truth Identifiers, Timestamps and Versioning`
  - `### 2.5. The Hood Bank, the Freeze, and Ventilation Discipline`
  - `### 2.6. Shared-Grill Occupancy: Half-Open Intervals and the Closed Counter`
  - `### 2.7. Monetary Precision and Rounding Discipline`
  - `### 2.8. Optimistic Concurrency on Holds, Clock-Ins and Check Closing`
  - `### 2.9. Downtime, Cascades and Compensation`
  - `### 2.10. Nested Resource Retrieval and Left-to-Right Resolution`
- `## 3. Business Logic & Workflows` (9 domain-derived subsections, 3.1–3.9)
- `## 4. Endpoint Definitions` (4-column table, 55 rows)
- `## 5. Error Code Catalogue` (2-column table, 41 rows)

## Coverage note

- **§1.1 entities**: all 12 (`Venue`, `Party`, `TableTier`, `GrillTable`, `Reservation`, `TableSeating`, `ChefAssignment`, `ShowPerformance`, `MaintenanceWindow`, `SushiTicket`, `VenueLedgerEntry`, `ProteinTicket`). All 85 field names appear verbatim in backticks, including the leaked `ProteinTicket.cost_cents`/`status` rows at the file tail.
- **§1.2 state machines**: all 10 tables / 42 transitions represented — state values (`DRAFT→…`, `AVAILABLE/SEATED/TURNING/MAINTENANCE`, `OFF_SHIFT/ON_STATION/CLEARING`, `PLANNED/STARTED/FINISHED/SKIPPED`, `SCHEDULED/ACTIVE/COMPLETED`, `RAW_CUT/ROLLED/PLATED`, `POSTED/VOIDED`, `ACTIVE/VACATED`) all present; every precondition paired with its `error_id`; all multi-hop cascades (HOP 1–5 ventilation abandonment, turn-debt restriction) expressed.
- **§1.3 calculations**: all 14 fully expressed in precise prose with constants embedded in context (settlement dual-variant, protein_cost, table_minimum_trueup, seat_surcharge, credit_application, chef_rotation selector ranking, protein_portion_standard, sushi_plating, course_timing, turn_over_window, turn_debt, restaurant_charge, venue_cost_report, sushi_plate_dwell). No pseudocode and no fuzzy/approximating wording.
- **§1.4 validations**: all 29 (priorities 1–30) with their conditions and `error_id`s; priority ordering stated explicitly in §2.10 ("the higher-priority rule is reported").
- **§1.5 endpoints**: all 55 listed; §4 deliberately carries Method/Path/Description/Roles only.
- **§1.6 errors**: all 41 error IDs mentioned in §2/§3 prose, and all 41 in the §5 table.
- **§1.7 roles**: all 5 named; both `entity_backed:ChefAssignment` identities (`Chef`, `SushiChef`) and all three `opaque` identities (`PlatformAdmin`, `FloorManager`, `Host`) translated per the skill's required sentence forms.

## Hard-contract reports

```
Field coverage check:
- entities[].fields: 85 required, 85 present, 0 missing
- endpoints[].request_body: 57 required, 57 present, 0 missing
- endpoints[].query_params: 0 required, 0 present, 0 missing
- endpoints[].path_params: 0 required, 0 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 29 checked, 29 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + ERR_STALE_VERSION/412 all named), 0 missing
- state_machines[].transitions: 42 checked, 42 fully expressed, 0 missing
- calculations[]: 14 checked, 14 fully expressed, 0 missing
- validations[] conditions: 29 checked, 29 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 55 checked, 55 expressed, 0 missing
- entities[].fields[] structured content: 85 checked, 85 reconstructible from prose, 0 missing
- sibling-branch symmetry: 10 state-machine groups checked, 10 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 625
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Two notes worth flagging: (1) the scaffold's `roles:` block is malformed — the tail of `ProteinTicket`'s `fields` list (`cost_cents`, `status`) leaked into `roles[].SushiChef.shared_operations`, and the `field:` key on each state machine is missing; I read those entities from the entity table where they are defined correctly, and this malformation may matter to downstream scaffold consumers. (2) The PRD contains no audit footer and ends at §5 as required; no sibling task directory or either withheld design file was opened.

Orchestrator note: item (1) of the subagent's flag was confirmed and repaired by the orchestrator before this entry (see repair note above). Its claim about the missing state-machine `field:` key was disproved and no change was made. Coverage of the withheld design indices is not assessed here — neither file was read by the PRD subagent, by design.

## Step 5: Generate unit tests — 2026-09-29T19:55:00.000Z

Subagent returned summary, verbatim:

All 99 tests pass collection and every audit check. Here is the summary.

## Files written

| File | Lines |
|---|---|
| `test_helpers/__init__.py` | 18 |
| `test_helpers/types.py` | 318 |
| `test_helpers/api_client.py` | 226 |
| `test_helpers/api_errors.py` | 97 |
| `test_helpers/assertions.py` | 173 |
| `test_helpers/constants.py` | 150 |
| `test_helpers/factories.py` | 86 |
| `test_helpers/test_users.py` | 29 |
| `test_helpers/fixtures.py` | 419 |
| `test_suite/conftest.py` | 38 |
| `test_suite/test_01_floor_setup.py` | 273 (10 tests) |
| `test_suite/test_02_floor_state_machines.py` | 319 (9) |
| `test_suite/test_03_validation_order.py` | 513 (16) |
| `test_suite/test_04_money_calculations.py` | 197 (6) |
| `test_suite/test_05_difficulty_pricing.py` | 444 (12) |
| `test_suite/test_06_difficulty_cascades.py` | 661 (18) |
| `test_suite/test_07_difficulty_window_and_precedence.py` | 706 (18) |
| `test_suite/test_08_coverage_gaps.py` | 393 (10) |

All paths under `/home/ubuntu/github/CodingPRD/tasks/task_3050_communal_teppanyaki_table_seating_chef_rotation_scheduling/`.

## Tests emitted

**99 tests, 99 `Design:` tags** — 1 tag per test, zero untagged, zero dual-tagged.

## Coverage

- **Queue A (Difficulty):** all **24** instances have ≥2 tests. Every difficulty test is tagged.
- **Queue B (Corner):** all **44** non-stub instances have ≥1 test. The **5 `excluded_because:` stubs** (`settlement_variant_divergence_…`, `protein_cost_variant_divergence_…`, `trueup_ceiling_order_…`, `seating_overlap_adjacency_…`, `credit_cap_evaluation_order_…`) are correctly NOT translated; their cited difficulty instances are covered under queue A.
- **Zero instances skipped.** Every non-stub instance in both indices passed the PRD-first two-condition filter (verbatim PRD coverage AND unique derivability), so there is no skipped-instance list and no failing filter condition to report.

## Full list of Design: tags emitted

**Difficulty (24 instances × 2 = 48 tags)**
```
Difficulty/dual_variant_calc/settlement_quote_vs_final_celebration_fee_gap                         (2)
Difficulty/dual_variant_calc/protein_cost_posted_vs_settled_control_allowance_gap                  (2)
Difficulty/dual_variant_calc/turn_over_window_standard_vs_celebration_tenure_variant              (2)
Difficulty/dual_variant_calc/protein_cost_role_variant_on_the_documented_control_report           (2)
Difficulty/combinatorial_formula/trueup_band_then_ceiling_order                                    (2)
Difficulty/combinatorial_formula/credit_cap_read_before_then_applied_after                         (2)
Difficulty/non_linear_state_machine/chef_rotation_cyclic_clearing_return_to_on_station             (2)
Difficulty/non_linear_state_machine/show_parallel_dessert_and_celebration_phases_same_table        (2)
Difficulty/non_linear_state_machine/sushi_prep_phase_cyclic_restart_from_plated                    (2)
Difficulty/transitive_cascade/ventilation_hold_five_hop_cascade_to_party_credit                    (2)
Difficulty/transitive_cascade/turn_vacate_three_hop_cascade_to_party_restriction                  (2)
Difficulty/transitive_cascade/no_show_three_hop_cascade_to_reusable_credit                         (2)
Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_a_closed_booking_at_a_scheduled_downtime_table (2)
Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_a_restricted_party_at_a_frozen_venue       (2)
Difficulty/boundary_precision_check/trueup_band_boundary_at_exactly_one_thousand_cents_is_inclusive (2)
Difficulty/boundary_precision_check/hold_count_boundary_third_hold_allowed_fourth_refused          (2)
Difficulty/cross_entity_state_dependency/reservation_holds_only_while_venue_is_not_frozen          (2)
Difficulty/cross_entity_state_dependency/show_start_waits_on_the_assigned_chefs_clearing_state     (2)
Difficulty/resource_temporal_overlap/half_open_table_seating_intervals_abut_without_conflict       (2)
Difficulty/resource_temporal_overlap/closed_sushi_counter_intervals_touching_at_an_instant_conflict (2)
Difficulty/compensating_invariant/abandon_then_reopen_keeps_venue_party_credit_debt_at_zero        (2)
Difficulty/compensating_invariant/run_ops_recompute_leaves_the_restaurant_charge_a_fixed_point     (2)
Difficulty/compensating_invariant/window_reopen_four_hop_cascade_back_to_a_serviceable_floor       (2)
Difficulty/compensating_invariant/resume_at_threshold_five_hop_cascade_to_hood_filter_reset       (2)
```

**Corner (44 instances, 51 tags)** — `Corner/entities/…` (10), `Corner/state_machines/…` (6), `Corner/calculations/…` (6), `Corner/validations/…` (5, two covered twice), `Corner/endpoints/…` (4), `Corner/errors/…` (4), `Corner/rbac/…` (4, `platform_admin_cannot_clock_a_chef_in` twice), `Corner/cross_cutting_complexity_layers/…` (3, two twice), `Corner/consistency_model/…` (2, one twice). Names copied verbatim from the yamls.

## Verification performed

- Static scan confirms every tag resolves to a real instance in the cited yaml, in the correct namespace, never to a stub.
- **PRD citation verbatim sweep:** 185 quoted fragments (≥8 words) across all docstrings all reduce to literal substrings of `workspace/PRD.md` after whitespace normalisation — 0 failures.
- **Error-id sweep:** all 25 asserted `error_id`s are named in PRD §2/§3 prose (not only the §5 table), each located in a trigger-condition sentence.
- `pytest --collect-only` collects **99 tests** with no import errors; `pyflakes` is clean outside the barrel-export re-exports.
- No `scaffold` / `Table N` / `§1.x` leakage anywhere in generated code; no `pytest.mark.skip` / `skipif` / `xfail` anywhere.

Note: only test code was written — no server was started, so the suite has not been executed against an implementation.

## Step 6: Generate implementation — 2026-09-29T21:20:00.000Z

Subagent returned summary, verbatim:

I've completed the implementation. Here is the final summary.

## Files written

| File | Lines |
|---|---|
| `workspace/implementation/start.sh` | 9 |
| `workspace/implementation/requirements.txt` | 1 |
| `workspace/implementation/app.py` | 73 |
| `workspace/implementation/db.py` | 160 |
| `workspace/implementation/errors.py` | 56 |
| `workspace/implementation/response.py` | 54 |
| `workspace/implementation/middleware.py` | 38 |
| `workspace/implementation/helpers.py` | 142 |
| `workspace/implementation/constants.py` | 125 |
| `workspace/implementation/calculations.py` | 386 |
| `workspace/implementation/services.py` | 1312 |
| `workspace/implementation/routes/__init__.py` | 12 |
| `workspace/implementation/routes/clock.py` | 18 |
| `workspace/implementation/routes/venues.py` | 108 |
| `workspace/implementation/routes/parties.py` | 45 |
| `workspace/implementation/routes/tiers.py` | 52 |
| `workspace/implementation/routes/tables.py` | 119 |
| `workspace/implementation/routes/reservations.py` | 365 |
| `workspace/implementation/routes/seatings.py` | 56 |
| `workspace/implementation/routes/chefs.py` | 67 |
| `workspace/implementation/routes/shows.py` | 53 |
| `workspace/implementation/routes/maintenance.py` | 83 |
| `workspace/implementation/routes/sushi.py` | 62 |
| `workspace/implementation/routes/ledger.py` | 40 |
| `workspace/implementation/routes/protein.py` | 56 |

**Total endpoints implemented: 55** (29 POST, 26 GET) — exactly matching the 55 rows of the PRD §4 endpoint table.

## Contract compliance (verified by running it)

- `start.sh` at `workspace/implementation/start.sh`, reads `$PORT` (default `10000` via `app.py`), binds `0.0.0.0`, ends with `exec python3 app.py` in the foreground; the `pip install` is guarded by `if ! python3 -c "import flask"`.
- Storage is in-memory only: a single `db.DB` dict-of-dicts keyed by id plus one module-level clock. No SQLite, no JSON dump, no `/tmp` cache, no `tempfile`/`open(...'w')` — verified by grep across every module.
- Nothing is seeded at startup. A fresh boot reports `total_count=0` for all twelve families and the clock reads exactly `2026-09-01T00:00:00Z`. No `seed_*`/`preload`/bootstrap code exists.
- Concurrent boot verified: 4 simultaneous `start.sh` launches on distinct ports each served HTTP 200; no stray listeners left behind (only PIDs I started were killed).

## Test results

`prd-bench-local-run --isolation per-test-server` (kills and relaunches via `start.sh` before every test): **75/99 passed, 0 errors** — every test boots cleanly, so the per-test isolation contract holds. The 24 failures are behavioral.

## Unimplemented / conflicting PRD requirements

Two genuine contradictions inside the given spec, which I could not satisfy in both directions:

1. **Restaurant charge rounding.** PRD §2.7/§3.8 says it is "integer cents" whose "per-table product is a whole number" (so 12 tables × 299 × 0.90 = 3588), but one pinned example asserts 12 × 299 × 0.90 exactly. I chose the literal PRD statement (+1 test).

2. **Seat surcharge rounding.** The scaffold's formula is `floor(base_rate × min(party_size,3) / (party_size+1))` then ceil to 25 (party 4 → 1925), but two adjacent pinned examples in the same test require party 4 → 2400 (= rate × min(4,3), no division). I chose the literal scaffold formula (+3 tests across the suite).

Also worth flagging: the fixture default clock (`2026-09-02T12:00:00Z`) precedes the fixture default `scheduled_time` (`2026-09-03T19:00:00Z`), so a booking is seated ~31 hours before its own show; the turn-over rule then computes `expected_vacate_at` ≈ `seated_at + 75 min` (i.e. ≈31h in the past). I implemented the PRD rule literally rather than re-anchoring it, which costs the shortfall/occupancy-window group.

The 24 remaining failures cluster in: the occupancy/shortfall group (the seated_at-vs-expected_vacate_at coupling above), chef-rotation acceptance breadth (my selector needs a "finished show + 3 min reset" gate that the fixtures' single-chef setups don't always satisfy), credit-cap evaluation order, and false-close settlement.

Orchestrator verification: 25 files present under `workspace/implementation/`; `start.sh` confirmed to `cd` to its own directory, guard the pip install, and end with `exec python3 app.py` (foreground); `requirements.txt` pins `Flask>=3.0.0`. Baseline recorded as 75/99 for Step 7 to improve on.

## Step 7: Run tests and iterate — 2026-09-29T22:22:00.000Z

Subagent returned summary, verbatim:

All 8 parallel rounds pass 99/99 with zero failures in the union. Done.

## Summary

**Iterations run:** 2 (baseline 8-round sweep at 75/99, then one fix cycle, then a clean 8-round sweep at 99/99 — no flakiness, every round identical).

**Tests deleted:** none. No failing test asserted a scaffold-only rule; every failure traced to either a wrong implementation behavior or a test artifact whose setup was inconsistent with PRD.

**Fixes applied to `test_helpers/`:** none required. The fixture layers (factories, role-header builders, assertion library) were faithful; the bugs were in test bodies and one fixture's arithmetic.

**Fixes applied to `implementation/`:**
- `services.py::finish_show` — removed a non-PRD chef write: GRILL finish was silently forcing the chef `ON_STATION → CLEARING`. PRD §3.1 says only the explicit `CLEAR_FINISH` event performs that move, and §3.5 lists the GRILL-finish side effects exhaustively without it. Now the GRILL finish stamps the settlement (§3.9: "the final variant runs when a GRILL phase finishes … and writes `final_bill_cents` and `check_cents`") and leaves the chef alone.
- `services.py::chef_candidates` / `calculations.py::rotation_key` — the rotation selector honoured neither of §3.4's candidate conditions: it ignored "`current_table_id == null`", and it ranked by a fabricated `completed_show_count` term the PRD never names. Added an active-occupancy busy filter and dropped the invented key component.
- `services.py::accept_window` — reordered so a GRILL_REBUILD accept against a non-`AVAILABLE`/`TURNING` table reports `ERR_INVALID_STATE` (state) ahead of `ERR_MAINTENANCE_WINDOW_LATE` (business), per §2.10.
- `services.py::reopen_window` — the SEATED-booking guard wrongly blocked releasing a ventilation hold. Scoped it to a venue that is still `VENTILATION_HOLD`, and made released tables return to `SEATED` (not `AVAILABLE`) when they still carry an ACTIVE occupancy.
- `services.py::close_reservation` — the credit-cap term was measured against a check that omitted the table-minimum true-up. §3.6 settles `final_bill`, then `check`, then credit over the check, so the true-up is now folded into the first check evaluation.
- `services.py::skip_show` — aligned to §3.5 ("a phase may be driven to SKIPPED from either PLANNED or STARTED"); the impl had restricted STARTED skips to SUSHI phases only.
- `services.py::sushi_event` — the ROLLED→PLATED time cap returned `ERR_INVALID_STATE`; §3.5 routes it to the sushi-plate rule, now `ERR_SUSHI_PLATE_LATE`. VOID now requires an OPEN ticket.
- `routes/reservations.py` — hold grant now evaluates the venue-freeze safety guard (priority 12) before the party-restriction guard (priority 22) per §2.10; reopen gained the §3.7 SEATED-booking guard; seat picks a replacement table by the booking's own tier code before any other fitting table.
- `routes/shows.py` — show-event responses for a GRILL phase now carry `final_bill_cents`/`check_cents`/`quote_final_cents`, satisfying §2.2's "operations that … modify a resource will return the created or updated resource object" and the four tests that read the settled bill off the GRILL response.

**Test-artifact fixes (STEP 2, test bodies):**
- `test_05` credit fixture — restored the party's own credit as the application source (splitting mint/consumer broke §3.6's "consumed amount moves out of `loyalty_credit_cents`"); aligned `credit_to_apply_cents` to the pinned cap 1620, since PRD requires an over-cap request be refused.
- `test_07` true-up test — retargeted to a T4 sole-tier floor auto-holding demands `surcharge 1925`; the inner `12800` reading was unreachable (the auto-hold closed the booking and claimed the table). Also pinned the T2 minimum so the shortfall lands exactly on the 1000-cent band edge (the pinned T2 minimum yields 1600, never exactly 1000).
- `test_07` celebration fixture — added `clear_chef` before the CELEBRATION start; §3.5 requires the chef to be CLEARING.
- `test_07` reopen fixtures — moved the window's `planned_start_at` inside the 30-minute acceptance grace so the accept succeeds.
- `test_07` party-restricted pair — the third booking is now submitted while the party is still ACTIVE (SUBMIT correctly rejects a RESTRICTED party; the test targets the hold gate).
- `test_07` half-open seat — first party right-sized to 2 so a second party still fits the shared table; `seated_at` assertion corrected to the clock (18:55) rather than the turn-over start (19:00), which §3.4 reserves for `expected_vacate_at`; removed a double `validate_success` around the data-returning `grant_hold` fixture.
- `test_07` / `test_03` hold-count tests — retargeted from the 2-seat table (party of 4 correctly refused) and advanced the clock past `hold_until` before the fourth attempt, so the hold-cap rule is the one that fires.
- `test_03` RBAC tests — added `clock_in=0` so the "cannot clock a chef in" cases start from `OFF_SHIFT` (the fixture otherwise clocks every chef in).
- `test_08` close test — `4800` was wrong for a T4 party of 4; the survcharge is `1925`.
- `test_04` cost-report test — asserted the mid-band charge `12 * 299` (no band); the LOW band (0.90) applies below 50, and two sibling tests in `test_06` pin `12 * 299 * 0.90`, so this one contradicted a PRD-pinned value.

**Note on the implementer's three hypotheses:** the restaurant-charge and seat-surcharge "contradictions" were both resolved against PRD prose — the charge keeps its LOW-band multiplier and the surcharge keeps the §3.9 formula; neither pinned example needed a literal compromise once the real test bugs (a band-less assertion and a single-party mint) were fixed. The `expected_vacate_at` coupling was not the cause of the occupancy group: the actual culprit was the auto-CLEARING write on GRILL finish, which stripped the venue of every seatable chef and cascaded into the shortfall, occupancy, and cascade failures.

**Sweep result:** 8/8 rounds, 99/99 passed, 0 failed, 0 errors.

Orchestrator verification: all 8 `results.{1..8}.json` present (mtime 2026-09-29 22:21) and each reports `passed=99 total=99 failed=0 errors=0`.

Step 8 trigger assessment: Step 7 made 9 `implementation/` fixes and 11 `test_suite/` fixes (0 deletions, 0 `test_helpers/` fixes), so the skip condition (0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 implementation fixes) is NOT met — **Step 8 runs**.

## Step 8: Finalize PRD — 2026-09-30T00:00:00.000Z

Subagent returned summary, verbatim:

PRD_FINALIZED.md is complete. Final verification: 368 lines vs PRD.md's 368 lines, 0.00% delta (10 single-line in-place edits, no sections added/removed).

## Summary of changes (10 edits; each traceable to a `<step_7_diff>` item)

- **§2.2** — revise — show-phase event responses for a `GRILL` phase additionally carry the booking's `final_bill_cents`/`check_cents`/`quote_final_cents` — `routes/shows.py:57-70`
- **§3.4** (seating gates) — insert — a held booking whose own table can no longer take the party rolls onto another fitting table, preferring one whose `tier_code` matches the booking's own — `routes/reservations.py:245-254`
- **§3.4** (chef gate) — revise — candidate condition is `ON_STATION` **and not committed to a table that still carries an `ACTIVE` occupancy** (replacing "no `current_table_id`") — `services.py:497-524`
- **§3.4** (rotation selector) — revise — same candidate-set condition; added the selector's fallback to all `ON_STATION` chefs, the population that actually governs `ERR_CHEF_ROTATION_EXHAUSTED` — `services.py:534-548`, `calculations.py:211-232`
- **§3.5** (GRILL finish) — revise — GRILL finish recomputes `final_bill_cents`/`check_cents` and leaves the chef's status untouched; removed the false "resets `minutes_since_show` to 0" and "moves a celebration booking's chef into `CLEARING`" claims — `services.py:1161-1191`
- **§3.5** (skip) — revise — a `STARTED` skip is legal for a phase of any course (removed the SUSHI-only restriction) — `services.py:1194-1206`
- **§3.5** (sushi) — revise — a plating past the lateness bound reports `ERR_SUSHI_PLATE_LATE`, not a state failure; VOID takes a ticket out of `OPEN` — `services.py:1280-1328`
- **§3.6** (close settlement order) — revise — the true-up is folded into the first `check_cents` evaluation and the credit cap read over that true-up-bearing check — `services.py:1003-1056`
- **§3.7** (accept/reopen) — revise — accept's state guards (sibling hold, grill-rebuild table state) are reported ahead of lateness; reopen returns venue-wide tables out of service (by occupancy → `AVAILABLE`/`SEATED`) and a table-scoped window's target to `AVAILABLE`, clearing `maintenance_resume_at` — `services.py:692-729`, `772-810`
- **§3.7** (reservation reopen) — insert — reopen requires the venue `ACTIVE` and holding no booking still `SEATED` — `routes/reservations.py:357-364`

## Per-edit pre-edit search log

**1. §2.2 GRILL show-event money slots**
(a) Subject: `data` field of a GRILL `show_event` response. (b) Enumerated: `routes/shows.py::show_event`/`_show_event_data` (only GRILL added), `routes/__init__.py` registration, all other show events (`START/FINISH/SKIP/REINSTATE` all route through it), `response.ok`, `db.public`. (c) Added clause in §2.2's global `data` bullet rather than altering the resource-object sentence; scoped to "a `GRILL` phase" so it does not over-claim non-GRILL responses.

**2. §3.4 seat table fallback**
(a) Subject: which table `seat` picks. (b) Enumerated: `routes/reservations.py::seat_reservation` (held-table-first, then same-`tier_code`, then any fitting), `routes/tables.py::_seat` (table-event path — uses the *named* table directly, no fallback, so the sentence is scoped to `HELD` bookings), `services.seatable_tables`/`best_table_for`/`capacity_limit`. (c) Narrowed wording to "a **held** booking whose own table can no longer take the party" so the table-event SEAT path is not mis-described.

**3 & 4. §3.4 chef gate + rotation selector**
(a) Subject: chef-candidate condition and exhaust condition. (b) Enumerated: `services.chef_candidates`, `_chef_pinned_to_active_seating`, `_has_finished_show`, `minutes_since_show`, `select_chef_for` (fallback), `pin_chef`, `calculations.rotation_key`/`select_chef`, both callsites (`routes/reservations.py:271`, `routes/tables.py:86`), and every `current_table_id` write (`services.py:202,557,1237,1241,1253`, `routes/chefs.py:28`). (c) Replaced the literal `current_table_id` test with the behavioral form "not already committed to a table that still carries an `ACTIVE` occupancy" and reworded the already-inert "`minutes_since_show` descending" clause as a documentation of the (never-triggered) fabricated term; added the fallback sentence scoped to the exhaust refusal. `routes/tables.py::_seat` calls the same selector.

**5. §3.5 GRILL finish**
(a) Subject: GRILL `FINISH` side effects. (b) Enumerated: `services.finish_show` (stamps `stamp_final(..., ledger_final=False)`, recomputes chef rollup, closes booking when all phases FINISHED), `stamp_quote`/`stamp_final`/`reconcile_pricing`, `clear_station_chefs`, `chef_event` CLEAR_FINISH, `recompute_chef_derived`; confirmed no `db.touch(..., status="CLEARING")` on the GRILL/close path. (c) Replaced the two false claims with "leaves the chef's status untouched" plus an explicit cross-reference that `ON_STATION → CLEARING` is exclusively `CLEAR_FINISH` (§3.1).

**6. §3.5 skip**
(a) Subject: which phase states may be skipped. (b) Enumerated: `services.skip_show` (PLANNED→guarded on booking CLOSED; STARTED→allowed for any course; else `ERR_INVALID_STATE`), `services.reinstate_show`, `routes/tables.py:110-112` (`MAINTENANCE_ENTER` drives PLANNED/STARTED shows to SKIPPED — a different trigger, unaffected by the phase restriction). (c) Changed "only legal for a `SUSHI` phase" to "legal for a phase of any course".

**7. §3.5 sushi**
(a) Subject: sushi late-plating error family and VOID. (b) Enumerated: `services.sushi_event` (`ROLLED→PLATED` time gate → `ERR_SUSHI_PLATE_LATE`, plate-interval conflict → `ERR_SUSHI_PLATE_LATE`, `RESTAGE`/`RESTART`/`VOID` all require `status=="OPEN"`), `calculations.sushi_plate_interval`/`plate_intervals_touch`. (c) Added a sentence pinning the late-plating error to the sushi-plate rule; appended "a void takes a ticket out of the `OPEN` state" (the existing `ERR_INVALID_STATE unless OPEN` text already implies the guard).

**8. §3.6 close settlement order**
(a) Subject: order of true-up vs credit cap at close. (b) Enumerated: `services.close_reservation` (final_bill, then trueup, then `check_before` with trueup, then credit gates read `credit_cap(check_before)`, then `credit_applied`, then `check_final`), `calculations.settlement` (check = final_bill + seat_surcharge − credit + trueup), `stamp_final`, `credit_cap`/`credit_applied`. (c) Inserted the true-up step into the pinned order and added "the cap being read over that first (true-up-bearing) evaluation of the check".

**9. §3.7 accept/reopen**
(a) Subject: accept validation order; reopen table restore. (b) Enumerated: `services.accept_window` (GRILL_REBUILD target-state check, then sibling-ACTIVE check, then lateness), `services.reopen_window` (SEATED guard gated on `VENTILATION_HOLD`; sibling-ACTIVE; venue-wide loop → `SEATED` if still occupied else `AVAILABLE`; table-scoped branch → `AVAILABLE`), `_complete_window`, `release_table_from_maintenance`, `routes/maintenance.py`. (c) Wrapped the reopen restore in "where the window is venue-wide … and where the window is table-scoped" so the table-scoped branch is not mis-described by a venue-wide-only sentence.

**10. §3.7 reservation reopen**
(a) Subject: the reservation-reopen preconditions. (b) Enumerated: `routes/reservations.py::reopen_reservation` (ABANDONED check, freeze, venue ACTIVE, the "no other SEATED booking at the venue" guard, hold cap, table eligibility, maintenance conflict), `services.reopen_reservation`. (c) Added "and to hold no booking still `SEATED`" to the existing venue-`ACTIVE` requirement; kept the rest of the sentence verbatim.

Note: many other Step 7 items were pure fixture/test-artifact bugs (test_05 mint/consumer split, test_07 true-up retarget, celebration `clear_chef`, half-open seat right-sizing, hold-count retargeting, test_03 `clock_in=0`, test_08/01/04 numeric fixtures) and required no PRD change.

Orchestrator verification: `wc -l` → PRD.md 368, PRD_FINALIZED.md 368. `diff PRD.md PRD_FINALIZED.md` shows exactly 10 changed lines, each a single-line in-place edit, no section added or removed.

## Step 9: Complete PRD — 2026-09-30T00:20:00.000Z

Subagent returned summary, verbatim:

Done. PRD_COMPLETED.md is written at `/home/ubuntu/github/CodingPRD/tasks/task_3050_communal_teppanyaki_table_seating_chef_rotation_scheduling/workspace/PRD_COMPLETED.md`.

## Summary

**Source vs output:** `PRD_FINALIZED.md` 368 lines / 72,376 chars → `PRD_COMPLETED.md` 368 lines / 73,845 chars (+1,469 chars, same line count; 24 lines edited in place, no sections added).

**Counts:** 20 ambiguity-pins, 4 mismatch-revisions (24 total edits).

**Changes** (line = PRD_COMPLETED.md):

- §2.1 L25 — revise — ambiguity — kept the segregation-of-duties rule but removed the "or has not been explicitly delegated it" clause (no delegation input exists anywhere) — `routes/maintenance.py:58`, `routes/reservations.py:330`, `errors.py:43`.
- §2.5 L99 — revise — mismatch — hood index `+1` on `GRILL` *start*, not finish — `services.py:1108`.
- §2.8 L121 — revise — ambiguity — the three version fields are accepted-if-present; omitted ⇒ no staleness check — `routes/reservations.py:125,334`, `routes/chefs.py:61`, `routes/tables.py:57`.
- §2.9 L135 — insert — ambiguity — grill-rebuild cascade duration = 120 minutes — `services.py:726`, `constants.py:101`.
- §3.1 L155 — insert — ambiguity — `ROTATE_SUPPRESS` clears `current_table_id` — `services.py:1252`.
- §3.2 L163 — revise — ambiguity — tier capacity band = `seat_capacity × over_capacity_ratio` — `services.py:938`.
- §3.3 L167 — revise — ambiguity — hold over-capacity limit also uses `over_capacity_ratio` — `routes/reservations.py:190`.
- §3.3 L171 — revise — ambiguity — shared grace band = 60 minutes — `routes/reservations.py:219`, `constants.py:99`.
- §3.4 L179 — insert — ambiguity — re-home prefers the booking's own tier `tier_code` — `routes/reservations.py:251`.
- §3.4 L183 — revise — mismatch — fallback population = all `ON_STATION` chefs ranked by the same composite key (not "candidates minus reset") — `services.py:534`.
- §3.4 L187 — revise — ambiguity — hold-collision on extend is reported as `ERR_MAINTENANCE_CONFLICT` — `routes/seatings.py:52`.
- §3.5 L197 — revise — mismatch — hood index `+1` on `GRILL` start (same as L99) — `services.py:1108`.
- §3.5 L201 — revise — ambiguity — booking → `CLOSED` when every *currently recorded* phase row is `FINISHED` — `services.py:1187`.
- §3.5 L205 — revise — ambiguity — restage/restart additionally require the booking to be `SEATED`; restart only once past the lateness bound — `services.py:1308`.
- §3.5 L207 — revise — mismatch — the advance delta does not move `requested_at` (only restage does) — `services.py:1283`.
- §3.6 L213 — revise — ambiguity — party-size over-capacity uses `over_capacity_ratio`, and `HELD` bookings are accepted too — `routes/reservations.py:284,294`.
- §3.6 L219 — insert — ambiguity — true-up ledger row posted only when the banded amount is non-zero — `services.py:1055`, `calculations.py:167`.
- §3.7 L223 — insert — ambiguity — a supplied `table_id` must belong to the named venue (else `ERR_TABLE_NOT_FOUND`) — `routes/maintenance.py:23`.
- §3.7 L225 — insert — ambiguity — a completing ventilation window also resets `hood_filter_life_index` to 0 — `services.py:186`.
- §3.8 L239 — insert — ambiguity — turn-debt cap = 40 minutes per closed booking — `constants.py:77`.
- §3.8 L241 — insert — ambiguity — escalation threshold = 60 minutes — `constants.py:76`, `services.py:896`.
- §3.9 L249 — revise — ambiguity — final variant also written on any terminal status (no-show/abandonment/vacate), not only the three listed triggers — `services.py:337`.
- §3.9 L251 — revise — ambiguity — T is held-based only; the `tier TABLE_TIER` condition was dropped (matches the shared-split hold rule) — `calculations.py:40`.
- §3.9 L253 — insert — ambiguity — compliment requires T to hold at least two bookings (a set of one never gets it) — `calculations.py:114`.

**Not changed (deliberately):** impl's `check_cents` uses the literal crews-constant 3 (ignoring sushi billing) — an arithmetic reduction only, not a wording mismatch, so prudence favored leaving §2.7/§3.9 untouched. Impl's turn-debt account omits `turn-debt escalation threshold`'s 480-min pool machinery (the PRD's `accumulate_course_debt` and pool allocator have no live callsite), but those sentences are self-consistent and unused, so no rewrite was warranted. One residual tension noted: §2.9's batch-epoch version bump (+1 from `run_ops`) is consistent with `test_04`/`test_08`; a passive `before_request` sweep mutates state outside an epoch, which is inherent to the scaffold's clock-driven design and not PRD-pinned either way.

Orchestrator verification: `wc -l` → PRD.md 368, PRD_FINALIZED.md 368, PRD_COMPLETED.md 368. Steps 8 and 9 touched only `*.md` files — `find` over `workspace/implementation/`, `test_suite/`, `test_helpers/` shows the newest code/results mtime is 2026-09-29 22:21 (the files Step 7's clean sweep ran against), while PRD_FINALIZED.md is 22:44 and PRD_COMPLETED.md is 23:03. The passing 8/8 sweep therefore remains valid for the shipped code.

## Pipeline complete — 2026-09-30T00:21:00.000Z

Final state: 8/8 parallel rounds at 99/99 passed, 0 failed, 0 errors against the current `implementation/`. Deliverables present: SCAFFOLD.yaml (2114 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1852), SCAFFOLD_CORNER_DESIGN.yaml (2211), test_helpers/ (9 files), test_suite/ (9 files, 99 tests), workspace/INSTRUCTION.md, workspace/PRD.md, workspace/PRD_FINALIZED.md, workspace/PRD_COMPLETED.md, workspace/implementation/ (25 files incl. start.sh and results.{1..8}.json).
