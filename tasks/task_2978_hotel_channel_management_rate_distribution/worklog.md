## Step 1: Create task directory — 2026-09-06T00:37:03.877667806Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2978_hotel_channel_management_rate_distribution and /home/ubuntu/github/CodingPRD/tasks/task_2978_hotel_channel_management_rate_distribution/workspace (pre-assigned path from orchestrator args; no index scan performed).

## Step 2: Generate scaffold — 2026-09-06T02:21:01.655256095Z

All three scaffold artifacts are complete and the lint is clean.

## Files

| File | Lines |
|---|---|
| SCAFFOLD.yaml | 3281 |
| SCAFFOLD_DIFFICULTY_DESIGN.yaml | 2293 |
| SCAFFOLD_CORNER_DESIGN.yaml | 3799 |

`SCAFFOLD.yaml` holds §1.0–§1.7 plus preamble only — no `scaffold_difficulty_design` / `scaffold_corner_design` keys; the two design files each have exactly one top-level key. The scenario is stored verbatim (including the `Generate task harder than expert level!` line), `difficulty_level: expert_plus`.

## SCAFFOLD.yaml counts
- 14 entities, 10 state machines, 2 concurrency rules (`allocation-create-stale-room-type`, `rate-plan-update-stale-version`)
- 16 calculations (2 dual-variant: `channel_net_adr`, `booking_pace_index`), 23 validation rules (strict priority order P1–P23, 4 declared priority pairs)
- 66 endpoints (35 mutations / 31 reads), 55 errors, 5 roles (`segregation_of_duties` role model, `ChannelPartner` entity-backed)
- Complexity layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers; graph topology, cyclic state machines, immediate consistency

## Design index counts
- §1.8 difficulty design: 25 instances across all 9 required `rule_id`s — dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 3, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 3, compensating_invariant 2.
- §1.9 corner design: 76 instances (57 with full `test_recipe`, 19 `excluded_because` stubs) over all 9 guide sections: entities 12, state_machines 10, calculations 15, validations 13, endpoints 7, errors 7, rbac 5, cross_cutting_complexity_layers 6, consistency_model 1. Every stub cites an existing §1.8 instance via `difficulty_instance` / `rationale` and carries no recipe; all 101 instance names are unique across the union of both files.
- Error coverage: all 55 error ids appear in at least one design instance.

## Lint verdict (verbatim)
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
Coverage
  §1.5 endpoints declared:    66
  §1.1 entities declared:     14
  §1.8 instances scanned:     25
  §1.9 instances scanned:     57
  Calls scanned (§1.8+§1.9):  1084

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Notable design traps caught while grounding literals against §1.4 priority order (each redesigned so the intended error is actually reachable): P15 InventoryDay prerequisite outranks the P16 horizon check; P17 overlap forbids two same-scope MIN_STAY windows; P19 stop-sell outranks the P20 ceiling (so the auto-guard makes a 4th overbooked booking unreachable); P3 role check precedes P4/P7/P10, and P6 override authority precedes every inventory check. Scratch dir `.scratch/step2/` was removed; sibling `.scratch/step*` dirs were left untouched.

ORCHESTRATOR NOTE: the subagent stored the difficulty directive line ("Generate task harder than expert level!") inside SCAFFOLD.yaml's `scenario:` key, which the Step 4 doc generator reads. Orchestrator stripped that one line from the scenario block immediately after this step so it cannot reach PRD.md. Verified: no occurrence of "harder than expert" remains in any scaffold file. All three files re-verified as parseable YAML with the expected top-level keys.

## Step 3: Copy shared files — 2026-09-06T02:21:01.668515458Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md to workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-09-06T02:45:13.504472585Z

The PRD is complete and all three Hard Contracts pass.

**Output:** `workspace/PRD.md` — **601 lines** (143,645 bytes), ends cleanly at the final `§5` error-table row (`| ERR_NO_ELIGIBLE_CHANNEL | 409 |`), no trailing fragment, no audit footer.

**Top-level section headings, in order:**
1. `# Hotel Channel Distribution API — Product Requirements Document`
2. `## 1. Introduction`
3. `## 2. Global Specifications & System-Wide Principles` — 2.1 Operators/Headers/RBAC, 2.2 API Response Structure (fixed verbatim block), 2.3 Pagination, 2.4 Resource Identity/Timestamps/Versioning, 2.5 The Logical Clock, 2.6 Money/Basis Points/Rounding, 2.7 Ordered Request Validation (all 23 priorities), 2.8 Optimistic Concurrency, 2.9 Derived State/Cascades/Conservation, 2.10 Nested Paths/Scoping/Status Codes
4. `## 3. Business Logic & Workflows` — 3.1 property/room types/sellable calendar, 3.2 rate plans & repricing, 3.3 channels/connectivity health/freeze windows, 3.4 mappings/parity/rate surveillance, 3.5 promotions & two-person approval, 3.6 sell-rate resolution & eligibility, 3.7 restrictions & propagation, 3.8 allotments/shared pool/overbooking, 3.9 booking/charging/cancellation, 3.10 batches/dispatch/retry, 3.11 analytics
5. `## 4. Endpoint Definitions` — 4-column table, all 66 rows
6. `## 5. Error Code Catalogue` — 2-column table, all 55 rows

**Contract reports**

```
Field coverage check:
- entities[].fields: 127 required, 127 present, 0 missing
- endpoints[].request_body: 63 required, 63 present, 0 missing
- endpoints[].query_params (incl. read output keys): 58 required, 58 present, 0 missing
- nested response keys (nightly_breakdown, ranked_channels): 5 required, 5 present, 0 missing
Status: PASS   (two independent passes: pre-built 158-token list + fresh scaffold extraction)
```
```
Rule coverage check:
- validations[] with priority: 23 checked, 23 expressed in prose with exact error_id + HTTP status, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (endpoint + expected_room_type_version / expected_rate_plan_version + ERR_STALE_*_VERSION + 412), 0 missing
- state_machines[].transitions: 46 checked, 46 fully expressed, 0 missing
- calculations[]: 16 checked, 16 fully expressed (evaluation order, constants, rounding mode, precision), 0 missing
- validations[] conditions: 23 checked, 23 matchable to error_id in §2/§3, 0 missing
- endpoints[].side_effects / applies_to: 66 checked, all expressed, 0 missing
- entities[].fields[] structured content: 32 input defaults + all computed/system initial values, reconstructible, 0 missing
- sibling-branch symmetry: 10 groups (heartbeat outcomes per state, 3 batch join outcomes, 3 job failure reasons, 2 ADR bases, 2 pace baselines, 3 restriction types, 2 lift triggers, 2 draw sources, allotment release/recall, promotion axes) — equal density, 0 asymmetric
- errors[]: 55 ids, every one mentioned in §2/§3 prose in addition to the §5 table
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 1794
- violations: 0
Status: PASS
```

**Repairs made during the contract passes** (worth noting for the record): seven `§3.x` cross-references were stale after the restrictions/allotments subsection split and were repointed; the repricing paragraph's priority claim was wrong (it said the version check follows the state check) and now states the true order — shape check P7, stale-version P10, state P11; the allotment-release paragraph never named the `OPEN -> RELEASED` / `EXHAUSTED -> RELEASED` edge; one "as appropriate" hand-wave over four 404s was replaced with an explicit identifier-to-error mapping; and eleven residual pseudocode expressions (`round_half_up(...)`, `==`, `<=`) were rewritten as narrative so the formulas stay reconstructible without operator syntax.

Scaffold inconsistencies were resolved as documented decisions rather than silently: the `failure_reason` enum admits `CONNECTION_UNHEALTHY`/`FREEZE_WINDOW_ACTIVE` that no specified path writes (PRD states the five values actually written and flags the two unused); `ConnectivityFreezeWindow.reason` has no declared default (documented as `MAINTENANCE`); promotion-load parity is documented under the flag-qualified reading; `InventoryDay.allocated_units` follows the formula (unconsumed held units), not the prose description. Scratch dir `.scratch/step4/` was removed; sibling step dirs untouched.

ORCHESTRATOR VERIFICATION (truncation guard): tail of PRD.md confirmed to end at a real section boundary — the last line is the final row of the §5 error table, not a mid-sentence fragment. Heading scan shows all six top-level sections present in order with §4 (endpoint table, lines 468-540) and §5 (error catalogue, lines 541-601) both fully materialised. Grep for "expert" / "harder than" / "difficulty" in PRD.md: zero hits, so the Step 2 difficulty directive did not leak into the implementer-visible contract.

## Step 6: Generate implementation — 2026-09-06T03:25:22.645564836Z

(Steps 5 and 6 were launched concurrently in a single assistant message so the implementation generator was physically isolated from `test_suite/`, which did not yet exist when it started. Step 6 returned first; its entry is recorded here out of numeric order. The Step 5 entry follows.)

Implementation complete and verified.

## Deliverables — `workspace/implementation/`

| file | lines | role |
|---|---|---|
| `errors.py` | 76 | all 55 §5 error ids -> HTTP status, `ApiError`, `fail()` |
| `store.py` | 104 | in-memory `DB` dicts, logical clock (epoch `2026-08-01T00:00:00Z`), id/version/timestamp helpers |
| `envelope.py` | 52 | §2.2 envelope, `req_`+20-char request id, pagination meta |
| `shape.py` | 305 | checks 1-3 and check 7 typed readers for body + query |
| `refs.py` | 169 | date maths, table access, entity navigation |
| `guards.py` | 51 | path resolution, paging, horizon and analytics-window guards |
| `calc.py` | 496 | 16 calculations: half-up `rdiv`, derivation, 6-step sell rate, pool arithmetic, restrictions, charging, loyalty, performance/pace/mix |
| `cascade.py` | 383 | batch fan-out and rollup, inventory/allotment refresh, overbooking guards, freeze evaluation, parity/mismatch, failure->suspend->recall->retire cascades, dispatch/apply/reject/retry |
| `serialize.py` | 148 | exact per-entity field tuples |
| `routes_property.py` | 187 | properties, room types, inventory days (10) |
| `routes_channel.py` | 235 | channels, connections, heartbeats, freeze windows (13) |
| `routes_rate.py` | 195 | rate plans incl. OCC reprice (6) |
| `routes_mapping.py` | 200 | mappings, parity, observed rates, quoted rate (8) |
| `routes_inventory.py` | 226 | allotments + restrictions (8) |
| `routes_promotion.py` | 198 | promotion authoring, 2-person approval, load (9) |
| `routes_dist.py` | 97 | batch dispatch, job retry, reads (6) |
| `routes_booking.py` | 193 | book/cancel/list/read stays (4) |
| `routes_analytics.py` | 81 | performance, pace, channel-mix, clock (4) |
| `app.py` | 67 | blueprint registration, `ApiError`/404/405/400 handlers, `0.0.0.0:$PORT` |
| `start.sh` | 15 | `$PORT` (default 10000), foreground `exec python3 app.py`, guarded flask check |
| `requirements.txt` | 1 | flask |

Total 3479 lines. No file I/O, no sqlite, no `/tmp`, no seeded data — verified by grep; storage is plain dicts wiped on every process start.

## Coverage
- Endpoints: 66/66. Programmatically diffed Flask's `url_map` against the §4 table — `missing: []`, `extra: []`.
- Error ids: 55/55. Diffed `ERROR_STATUS` against the §5 table — no id or HTTP-status mismatches, and all 55 are actually raised somewhere in the code (no dead ids, no undeclared ids).

## Smoke test — passed
Booted `PORT=39781 bash start.sh` (foreground, listening on 0.0.0.0). Two scripted passes over ~60 calls, zero 500s: full onboarding -> channel/connection/activate -> rate plan + derived plan -> mapping/verify -> quoted-rate breakdown -> booking (per-night commission, ledger) -> inventory pool recompute -> restriction + batch fan-out -> dispatch (jobs APPLIED, `last_pushed_rate_cents` set) -> performance/mix/pace -> allotment (OCC + supersede) -> cancel (exact ledger reversal). Negative/cascade paths confirmed: `ERR_UNAUTHENTICATED`, `ERR_ROLE_NOT_PERMITTED`, `ERR_SEGREGATION_OF_DUTIES`, `ERR_MEMBER_RATE_NOT_ELIGIBLE`, `ERR_OVERBOOK_OVERRIDE_REQUIRED` -> override booking -> OVERSOLD -> two `AUTO_OVERBOOK_GUARD` stop-sells (one per ACTIVE plan) -> `ERR_OVERRIDE_NOT_PERMITTED` on lift -> `ERR_STOP_SELL_ACTIVE` -> cancellation auto-lifts with `AUTO_GUARD_CLEARED`; `ERR_STALE_ROOM_TYPE_VERSION`, `ERR_ALLOCATION_EXCEEDS_CEILING`; heartbeat streak HEALTHY->DEGRADED->DEGRADED->SUSPENDED, job rejection->retry (attempt_count preserved), revalidate to streak 2, freeze window with 60-min pre-buffer -> `ERR_CONNECTION_FROZEN`, retire -> mappings DISABLED; pagination and `limit=0` rejection. Killed by port only (`fuser -k 39781/tcp`) — never a broad pkill; port confirmed free. The second `bash start.sh` served empty lists on every table with the clock back at `2026-08-01T00:00:00.000Z`, proving zero residual state. Scratch cleaned with `rm -rf .scratch/step6`; siblings step5/7/8/9 untouched. `test_helpers/` and `test_suite/` were never read.

## Judgement calls worth knowing for Step 7
1. Check 15 before check 16 (literal §2.7 order): a stay or allotment beyond the horizon with no `InventoryDay` reports `ERR_INVENTORY_DAY_NOT_OPEN` (409), not `ERR_STAY_OUTSIDE_HORIZON`/`ERR_WINDOW_OUTSIDE_HORIZON`. The horizon errors stay reachable via days opened before a clock move.
2. Restriction lift: check 6 before check 11 — an already-`LIFTED` guard returns `ERR_OVERRIDE_NOT_PERMITTED` (§2.7 numbering overrides §3.7's prose order).
3. Reversed analytics window -> `ERR_ANALYTICS_WINDOW_INVALID` (422), per §3.11's explicit "at priority 22", not check 7's 400.
4. `ranked_channels` entries carry `channel_id` in addition to the five PRD-listed fields (only intentional field addition, so a ranking is identifiable).
5. `POST /_clock/set_current_utc` echoes `current_utc` in canonical 3-fractional-digit form per §2.4.
6. `ERR_GEO_MARKET_NOT_SERVED` is raised only from a channel's non-empty `geo_market_codes`; a non-matching `GEO_OFFER` promotion is merely ineligible (§3.6's empty-list sentence).

## Step 5: Generate unit tests — 2026-09-06T03:53:02.715937859Z

Generation complete and verified.

## Design-index coverage audit

Queue A — SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8): 25 instances, all non-stub, all 25 translated, every one carrying >=2 tests (min 2, no instance under target).

Queue B — SCAFFOLD_CORNER_DESIGN.yaml (§1.9): 76 instances, 57 non-stub (19 carry `excluded_because:` and were correctly never translated). All 57 non-stub instances translated, each with >=1 test.

Skipped for PRD-first filter failure: none. Every non-stub instance passed both conditions. Where an instance's yaml expectation contradicted the PRD, the PRD won and the individual non-derivable sub-assertion was dropped rather than the whole instance:
- `ERR_OVERBOOK_OVERRIDE_REQUIRED` asserted at 409 (PRD), not the yaml's 422.
- yaml `failure_code: "AUTH_FAILED"` and `protocol: "XML_PULL"` are undeclared enum values; replaced with the declared `AUTH_REJECTED` / `XML_PUSH`.
- TWIN night after two bookings is `TIGHT` with `shared_pool_units: 1` (ceiling 3 = floor(2 x 1.5)), not the yaml's EXHAUSTED/0.
- Connection `suspended_at` clearing on revalidate, batch `version` after dispatch, `verified_at`, and `sequence_index: 0` are not uniquely derivable — those sub-assertions omitted, not weakened.

Tag audit (AST + yaml cross-check): 0 problems. Every one of the 184 test functions ends its docstring with exactly one `Design:` line, none dual-tagged, none pointing at a stub or an unknown instance, `Design:` always the last docstring line. No `skip`/`xfail` markers anywhere.

## Files

`test_helpers/` (9 modules, 3,565 lines): `constants.py` 276, `api_errors.py` 167 (55-member `ApiErrorId` + full `HTTP_STATUS_CODES` + `set_error_http_status_map` at import), `api_client.py` 508 (60 route methods, `canonical_instant`), `test_users.py` 155, `types.py` 384, `assertions.py` 431, `factories.py` 584, `fixtures.py` 781, `__init__.py` 181 (81 exports).

`test_suite/` (conftest + 18 modules, 12,567 lines, 184 tests):

| module | lines | tests |
|---|---|---|
| test_difficulty_boundary_precision_check.py | 496 | 8 |
| test_difficulty_combinatorial_formula.py | 525 | 7 |
| test_difficulty_compensating_invariant.py | 678 | 7 |
| test_difficulty_cross_entity_state_dependency.py | 656 | 6 |
| test_difficulty_dual_variant_calc.py | 382 | 4 |
| test_difficulty_non_linear_state_machine.py | 773 | 6 |
| test_difficulty_priority_pair_validation_conflict.py | 267 | 6 |
| test_difficulty_resource_temporal_overlap.py | 624 | 8 |
| test_difficulty_transitive_cascade.py | 815 | 6 |
| test_corner_calculations.py | 860 | 14 |
| test_corner_consistency_model.py | 305 | 3 |
| test_corner_cross_cutting.py | 717 | 8 |
| test_corner_endpoints.py | 756 | 11 |
| test_corner_entities.py | 911 | 17 |
| test_corner_errors.py | 929 | 20 |
| test_corner_rbac.py | 1148 | 18 |
| test_corner_state_machines.py | 879 | 16 |
| test_corner_validations.py | 846 | 19 |

Total: 184 test functions; `pytest --collect-only` yields 213 collected nodes (parametrize expansions) in 0.45s against an unreachable base URL, so every module imports cleanly and every helper symbol resolves.

## Verification sweeps (all zero hits)

Scaffold/design-index leakage outside `Design:` lines; any reference to `implementation/`; `validate_success(...)["data"]` double-unwrap; bare `["data"]` indexing; whitespace-only header values; money or basis-point values sent as strings; `pkill`/`subprocess`/`app.py`. `test_helpers/` mtimes all predate every writer session — shared infrastructure untouched.

Constraint compliance: both directories are siblings of `workspace/` (`ls workspace/` shows only `INSTRUCTION.md PRD.md implementation sweep.sh`); `workspace/implementation/` was never read, listed, or referenced; nothing under `workspace/` modified; `worklog.md` untouched; only `.scratch/step5` removed (`step7`, `step8`, `step9` intact); both `__pycache__` dirs cleaned.

## Open items for Step 7 / Step 9

1. Genuine internal PRD contradiction (highest blast radius). PRD line 208: "Activation queues no distribution work of its own." PRD line 410: "a rate plan repricing or activation ... creates one `DistributionBatch`." The suite follows the specific rule (line 208). If the implementation queues a batch on activation, 19 `only_batch(` call sites across 9 modules fail with `expected exactly one batch matching ...` as a shared setup error. That signature means "adjudicate the PRD," not "fix the tests."
2. Secondary divergences already resolved PRD-first and worth re-checking against the implementation: `ERR_OVERBOOK_OVERRIDE_REQUIRED` at 409; TWIN night `TIGHT` with `shared_pool_units: 1`; `suspended_at`-clearing and batch-`version` assertions deliberately absent.

ORCHESTRATOR NOTE: verified after both concurrent generators exited — `test_helpers/` and `test_suite/` are siblings of `workspace/` (not nested inside it), `workspace/` contains only INSTRUCTION.md, PRD.md, implementation/ and the orchestrator's pre-written sweep.sh, and `.scratch/` retains only step7/step8/step9. The orchestrator pre-wrote `workspace/sweep.sh` (setsid-launchable, per-round logs, SWEEP_DONE sentinel after `wait`) so Step 7 does not have to inline the 8-round loop and cannot hit the shell-quoting failure that kills every round at t=0.

## Step 7: Run tests and iterate — 2026-09-06T04:14:20.673183293Z

Done — clean 8-round sweep, 213/213 in every round.

## Summary

**Iterations run:** 2 (iteration 1: 207/213 in all 8 rounds, 6 deterministic failures; iteration 2: 213/213 in all 8 rounds).

### PRD-contradiction adjudications

**1. Activation vs. DistributionBatch (the flagged high-blast-radius item) — NO batch on activation.**
- PRD §3.2 line 208: "On success `resolved_base_amount_cents` is recomputed by the derivation walk above and the plan's `version` is incremented by 1. **Activation queues no distribution work of its own.**"
- PRD §3.10 line 410: "Every event that changes what a channel should be selling — a rate plan repricing **or activation**, a restriction placed or lifted, a promotion loaded — creates one `DistributionBatch`..."

Chose line 208. It is the specific normative rule inside the section that owns the activation transition, against a general framing sentence opening §3.10. It is also the only self-consistent reading: mapping verification requires `plan_state` `ACTIVE` (§3.4) and `CLOSED` is terminal, so at the instant a plan activates no mapping of it can yet be `VERIFIED` — an activation batch would always fan out zero jobs and be permanently non-dispatchable (`total_jobs` must be >= 1 per §3.10 dispatch). No change was needed: the implementation already did not queue on activation, so the predicted 19 `only_batch(` failures never materialised. Step 8/9 should pin line 410 by striking "or activation".

**2. Reversed analytics window -> 422 `ERR_ANALYTICS_WINDOW_INVALID`, not check 7's 400.** §2.7 check 7 lists `window_end_date >= window_start_date` among shape checks (400), but §2.7 check 22, §3.11 line 440 ("all three refuse a malformed window with `ERR_ANALYTICS_WINDOW_INVALID` at priority 22") and line 460 all name the 422. Implementation already correct; no change.

**3. Restriction lift — check 6 before check 11.** §3.7 narrates state-then-origin, but §2.7 numbers override authority 6 and state 11 and says "The ordering is part of the contract". An already-`LIFTED` guard therefore returns `ERR_OVERRIDE_NOT_PERMITTED`. Implementation already correct; no change.

**4. `consumed_units` — draw-source, not raw channel occupancy.** §3.8 line 368 contains both "A new allotment starts with `consumed_units` 0" and "it is the peak per-night count of `CONFIRMED` reservations on this channel inside the allotment's window." These conflict when the channel already holds pool-drawn stays. Chose the draw-source reading: it is the only one satisfying "starts with 0", it matches §3.9 ("An allotment draw increments the consuming `ChannelAllocation`'s `consumed_units`" / cancellation returns a unit "to the shared pool or the consuming allotment's `consumed_units` falls by 1 depending on where the booking drew from"), and it is the only reading under which §3.8's aggregate ceiling check (which counts the requested units as fully held) agrees with the post-state it produces.

### Tests deleted
None. All 6 failures traced to verbatim PRD sentences and survived the unique-derivability check.

### Fixes to `test_suite/`
- `test_difficulty_transitive_cascade.py`, `test_the_guard_covers_only_active_plans_and_only_the_oversold_night` (2 lines): `rate_plan_state` -> `plan_state`. Test-artifact symbol bug — the PRD field is `plan_state` (§3.2 line 206 serialization list), spelled that way at all 35 other call sites across the suite; these two were the minority misspelling, so the assertion failed on field presence with no response body in the traceback.

### Fixes to `test_helpers/`
None — no fixture, factory, or role-header bug was found.

### Fixes to `implementation/`
- **`calc.py` / `channel_mix()`** — removed the extra `channel_id` key from each `ranked_channels` entry. §3.11 line 464 enumerates the entry exhaustively as `rank`, `net_adr_cents`, `commission_bp`, `commission_cost_ratio_bp`, `room_nights`; the extra field was a self-declared deviation with no PRD sentence behind it. (Fixed 3 tests. `channel_id` on the performance read is legitimate per line 442 and was left alone.)
- **`calc.py` / `rederive_family()`** — a descendant plan whose `resolved_base_amount_cents` the cascade actually moves now takes its own `version` bump and `updated_at` refresh, per §2.9: "Every entity touched anywhere along such a chain has its own `version` incremented by 1 ... the fact that a change reached an entity indirectly does not exempt it from the version bump." Scoped to changed values so that activation's idempotent re-derivation (§3.2: "The parent's state is irrelevant to this arithmetic") bumps nothing.
- **`calc.py` / `consumed_units_for()` + `routes_booking.py` / `create_reservation()`** — `consumed_units` is now the peak per-night count of the reservations that drew from that allotment, tracked via an internal, never-serialized `_draw_allocation_id` on the reservation. Previously a newly carved allotment retroactively absorbed pre-existing shared-pool bookings on the same channel, giving it `consumed_units` 2 and `version` 2 at creation and corrupting the covered day's `allocated_units`/`shared_pool_units`/`pooled_state`.

No endpoint, response field, side effect, or seeded data was added; storage remains in-memory dicts only.

### Final sweep evidence
`results.1..8.json`, all left in place at `workspace/implementation/`:

| round | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| passed/total | 213/213 | 213/213 | 213/213 | 213/213 | 213/213 | 213/213 | 213/213 | 213/213 |

Union of failing tests across all 8 parallel rounds: 0. Cross-checked: extracted failing ids (0) == total - passed (0) in every round, so the parser is sound. Scratch dir `.scratch/step7` removed; `.scratch/step8` and `.scratch/step9` untouched; `worklog.md`, `PRD.md`, `INSTRUCTION.md` and `sweep.sh` not modified.

ORCHESTRATOR VERIFICATION: independently parsed all 8 `results.$i.json` on the "total"/"passed" keys (not "outcome") — every round reports passed 213 of total 213, duration ~380s per round for the baseline sweep. Step 8 is therefore NOT skipped: Step 7 ran 2 iterations with 1 `test_suite/` fix and 3 `implementation/` fixes, so PRD silences exist at those sites.

## Step 8: Finalize PRD — 2026-09-06T04:25:28.387785586Z

`PRD_FINALIZED.md` is written. 7 targeted line edits, no wholesale rewrite.

## Integrity
- PRD.md: 601 lines / 143,645 bytes. PRD_FINALIZED.md: 601 lines / 146,320 bytes (+2,675 B, +1.9% bytes, 0% line delta). Diff touches exactly lines 122, 154, 212, 338, 368, 378, 410.
- `tail -3` still ends at the final §5 error-table row (`| ERR_NO_ELIGIBLE_CHANNEL | 409 |`).
- `implementation/results.1..8.json` + `SWEEP_DONE` untouched; `.scratch/step9` untouched; scratch cleaned with `rm -rf .scratch/step8`.

## Changes
- §2.7 check 7 — revise — struck `window_end_date >= window_start_date` from the 400 shape clauses and added that the analytics window pair is shape-checked here only for presence/well-formedness, its relative order belonging to check 22 (422, never 400) — `guards.py:45-50`, `routes_analytics.py:28,63`.
- §2.9 — insert — "touched" now means the entity's stored values actually moved: a cascade that recomputes an entity to the derived values it already held bumps neither `version` nor `updated_at`; a directly requested modification bumps regardless — `cascade.py:120,131,220,228`, `calc.py:79`.
- §3.2 repricing — insert — the re-derivation reaches descendants in any `plan_state`, and each descendant whose `resolved_base_amount_cents` the walk actually moves takes its own `version`+1 and `updated_at` refresh, while an unchanged descendant is left alone — `calc.py:68-80`.
- §3.7 lifting — revise — reordered to origin-then-state and pinned that override authority is check 6 vs. state check 11, so an already-`LIFTED` `AUTO_OVERBOOK_GUARD` restriction reports `ERR_OVERRIDE_NOT_PERMITTED` — `routes_inventory.py:190-194`.
- §3.8 `consumed_units` — revise — redefined as the peak per-night count of `CONFIRMED` reservations that drew from *this* allotment (draw source fixed at admission), reconciling it with "starts with 0"; added that it freezes once the allotment is `RELEASED`/`RECALLED`/`SUPERSEDED` — `calc.py:216-240`, `cascade.py:110-123`, `routes_booking.py:128-130`.
- §3.8 booking admission — insert — draw allotment is on the booked room type, earliest-created wins when several qualify, pool otherwise; the recorded draw source is never a serialized reservation field — `routes_booking.py:25-36,130`, `refs.py:70-80`.
- §3.10 line 410 — revise — struck "or activation" from the batch-creating events, aligning with §3.2's "Activation queues no distribution work of its own" — `routes_rate.py:100-113` (no `cascade.rate_batch`).

No PRD edit for the two remaining Step 7 items: the `channel_id` removal from `ranked_channels` restored conformance with §3.11 line 464 as already written, and the `rate_plan_state`->`plan_state` test fix was a test-artifact symbol bug (§3.2 line 206 was already correct).

## Per-edit pre-edit search log
1. §2.7 check 7. (a) Subject: where the reversed-window / ordering comparisons are enforced. (b) Grepped every `end_date < start_date`, `ends_at <= starts_at`, `ceiling < floor`, `window_*_date` site: `routes_inventory.py:36,136`, `routes_promotion.py:42`, `routes_channel.py:185`, `routes_rate.py:45,133`, `guards.py:45-50`, `routes_analytics.py:24-25,61-62`; confirmed only the two analytics reads carry the `window_*` pair and the pace read carries none. (c) Kept `end_date >= start_date` and `ceiling >= floor` in check 7 verbatim and scoped the new sentence to the `window_*` pair only, so allocation/restriction/promotion 400s are not re-homed.
2. §2.9 bump rule. (a) Subject: when a cascade-touched entity gets a `version`/`updated_at` bump. (b) Read every conditional-bump path (`cascade.refresh_days:131`, `refresh_allocations:120`, `refresh_alert_count:220`, `reparity_room_type:228`, `calc.rederive_family:79`, `cascade.rollup`/`dispatch:321-324`, `disable_mapping:290-294`, `retry_job:377-378`) and every unconditional-bump modification endpoint (`update_room_type:122`, `reprice/activate/close`, `verify_mapping:107`, `update_mapping_content:134`, `record_observed_rate:148`, heartbeat/activate/revalidate/retire, promotion submit/approve/reject/revise/load, `release_allocation:97`, `lift_restriction:198`). (c) Added the explicit "a directly requested modification bumps whether or not values differ" clause specifically because `update_room_type` and `update_mapping_content` bump unconditionally; scoped the negative clause to cascade recomputation of derived values so it cannot be read back onto direct writes, and phrased it per-cascade rather than per-request so §3.10's two pinned batch bumps during a dispatch stay legal.
3. §3.2 descendant bumps. (a) Subject: the derivation-chain re-derivation cascade. (b) `calc.rederive_family` and its only two callers `routes_rate.py:111` (activate) and `:152` (reprice); `refs.plan_family`/`descendants_of_plan` (no `plan_state` filter); `calc.resolve_base_amount`; `store.bump`. (c) Wrote the rule as changed-only, which keeps §3.2 line 208's activation walk (idempotent, since creation and every earlier reprice already settled descendants) bumping nothing — so no edit to line 208 was needed. Also added "regardless of what `plan_state` those descendants are in", since `plan_family` is state-blind.
4. §3.7 lift ordering. (a) Subject: precondition order on the restriction-lift endpoint. (b) `routes_inventory.lift_restriction:186-200`; the system-driven path `cascade.lift_guards:171-183` (origin-then-state, but no error codes so order unobservable); check 6's other guarded operation `routes_booking.py:43-48`. (c) Confined the claim to the human lift endpoint and left §3.7's auto-lift paragraph untouched, so the system trigger's narration is not mis-described.
5. §3.8 `consumed_units`. (a) Subject: `consumed_units` semantics and lifecycle. (b) `calc.consumed_units_for:216-240`, `cascade.refresh_allocations:110-123` (terminal states skipped), `calc.held_units_on:243-255`, `routes_inventory.create_allocation:79` (born 0) and its aggregate check `:63-67`, `routes_booking.create_reservation:130`, `refs.confirmed_reservations`. (c) Added the freeze clause after finding `refresh_allocations` skips `RELEASED`/`RECALLED`/`SUPERSEDED`, so the derived-count wording would otherwise falsely imply a released block's count still tracks later cancellations. Deliberately did not document `consumed_units_for`'s clamp at `allocated_units` — it is unreachable through the API, and asserting it would over-determine the PRD.
6. §3.8 draw source. (a) Subject: which allotment (if any) a booking draws from. (b) `routes_booking._allotment_draw:25-36`, `refs.where`/`store.ordered` (created_at then `_seq` ascending -> first match is earliest-created), `serialize.reservation_out` (confirmed `_draw_allocation_id` is not serialized). (c) Verified the impl's allotment-level `allocated_units - consumed_units >= 1` test is equivalent to the PRD's per-night phrasing (since `consumed_units` is the peak), so the PRD's per-night wording was kept verbatim rather than rewritten to the impl's aggregate form.
7. §3.10 line 410. (a) Subject: which events create a `DistributionBatch`. (b) All three factories and every callsite: `cascade.rate_batch` <- `routes_rate.py:153` (reprice only); `cascade.restriction_batch` <- `routes_inventory.py:182,199` and `cascade.py:168,183` (guard place/lift); `cascade.promotion_batch` <- `routes_promotion.py:173`; `routes_rate.activate_rate_plan:100-113` creates none. (c) No adjustment needed — guard-placed and auto-lifted restrictions are already covered by the surviving "a restriction placed or lifted", so striking only "or activation" leaves every real batch source described.

ORCHESTRATOR VERIFICATION: PRD_FINALIZED.md is NOT byte-identical to PRD.md (`cmp` differs; 14 changed lines = 7 edits x before/after), still 601 lines with all 29 heading lines intact, still ends at the final §5 error-table row, and contains no difficulty meta-commentary. All 8 `results.*.json` deliverables still present.

## Step 9: Complete PRD — 2026-09-06T05:25:59.272262361Z

ORCHESTRATOR DECISION (recorded per the autonomy instruction): Step 9 was run as FOUR SEQUENTIAL SUBAGENT PASSES over one shared `PRD_COMPLETED.md`, partitioned by implementation module, rather than as a single full-scan subagent. Rationale: PRD.md is 601 lines but 143 KB of very long paragraphs, and the implementation is 3,481 lines across 19 modules; a single subagent asked to scan all of it exhaustively cannot hold both sides in context and characteristically returns a byte-identical file, i.e. the scan silently never ran. Pass 1 performed the `cp` from PRD_FINALIZED.md; passes 2-4 were explicitly forbidden from copying so they could not destroy their predecessors' edits. Pass 4 was a dedicated reconciliation pass, because partitioned passes can only REPORT cross-pass contradictions from inside their own partition — they cannot fix them. Every pass was restricted to targeted Edit calls (never a whole-file Write, which would truncate at the 64k output cap and destroy the document) and each verified line count, heading count and the §5 tail before exiting.

Partition:
- Pass A — app.py, envelope.py, errors.py, store.py, shape.py, guards.py, refs.py, serialize.py, routes_property.py, routes_channel.py
- Pass B — calc.py, cascade.py (the two densest modules: 16 calculations + all cascades)
- Pass C — routes_rate.py, routes_mapping.py, routes_inventory.py, routes_promotion.py, routes_dist.py, routes_booking.py, routes_analytics.py
- Pass D — reconciliation only (cross-pass contradictions, the passes' own over-claims, global invariants)

### Pass A (foundation + property/channel) — 24 changes: 19 ambiguity-pins, 5 mismatch-revisions
`cp PRD_FINALIZED.md PRD_COMPLETED.md` ran from PRD_FINALIZED.md (existed; no fallback). 601/146,320 -> 602/156,721 (+10,401 B).
Highlights: §2.1 whitespace-only header counts as empty (401); §2.2 `api_request_id` is `req_` + exactly 20 uppercase-alnum chars and `api_request_timestamp` reads the logical clock, not wall time; §2.3 `limit`/`offset` grammar, empty value == omitted, `offset` unbounded, `created_at` ties broken by server creation order never by `id`; §2.4 canonical lowercase 36-char UUID and one universal `...SS.mmmZ` instant rendering; §2.5 clock moves are unconstrained in either direction and the echo is canonicalised; §2.7 check 7 — the full typed-reader block (integers reject bools/numeric strings/`5.0`, booleans reject `"true"`, the exact accepted instant grammar including `+0000`, explicit-`null` semantics per field class, query literals matched without resolution); §2.7 check 7 MISMATCH — "every amount and every count is a non-negative integer" was false for the signed `sell_adjustment_bp`/`offset_bp`/`offset_amount_cents`, softened; §2.7 check 16 MISMATCH — "inside that same horizon" pinned as strictly after the clock's date through clock date + `booking_horizon_days`; §2.9 underscore-prefixed internals never serialized; §2.10 unrouted path -> `ERR_INVALID_REQUEST` 404 and undeclared method -> 405, trailing slash insignificant; §3.1 MISMATCH "four remaining property inputs" -> "five"; §3.1 room-type PATCH null semantics and `{}`-is-a-valid-modification; §3.3 "the connection of a channel" = the non-`RETIRED` one else newest retired; §3.3 MISMATCH — a `RETIRED` connection does NOT refuse everything (freeze-window creation has no state precondition), narrowed to heartbeat/activate/revalidate/retire; §3.3 new bullet — a failure event from `PENDING`/`SUSPENDED` moves streak and code and bumps version but not state; §3.3 MISMATCH freeze-window instants need not carry three fractional digits; §3.3 overlap compares half-open buffered intervals so touching windows are accepted.
Verified needing no change: the whole §5 error table against errors.py, and every serialized field tuple in the partition.

### Pass B (calc.py + cascade.py) — 13 changes: 7 ambiguity-pins, 6 mismatch-revisions
602/156,721 -> 602/161,281 (+4,560 B), zero line delta (all in-paragraph).
- §3.2 derivation — a derived plan whose `offset_kind` is `NONE` copies the parent's resolved base unchanged (PRD covered only PERCENT/AMOUNT and the null-parent case) — calc.py:60-65
- §3.2 closure MISMATCH — closure routes through the same disable helper, so it also abandons `QUEUED`/`REJECTED` jobs and re-rolls-up their batches — routes_rate.py:167 -> cascade.py:283-295
- §3.3 failure events MISMATCH — `RETIRED` included: a job dispatched against a retired connection still increments `consecutive_failures`, sets `last_failure_code` and bumps `version` — cascade.py:235-249, 342-352
- §3.3 retirement MISMATCH — retirement's mapping disable carries the §3.4 job-abandonment cascade (closes pass A note 2) — cascade.py:272-295
- §3.6 step two — same-kind promotion tie on `created_at` resolves to the earlier-created row — calc.py:135-137
- §3.6 rate eligibility MISMATCH — "a `MEMBER_RATE` promotion is claimed" was circular; it is in play when `APPROVED` and its window covers any priced date, independent of `member_flag`, so an unclaimed offer still forces `ERR_MEMBER_RATE_NOT_ELIGIBLE` — calc.py:106-115
- §3.7 propagation — restriction fan-out is scoped by room type alone; a plan-scoped restriction still pushes to every `VERIFIED` mapping of that room type — cascade.py:61-65
- §3.8 pool arithmetic — `shared_pool_units` is never floored at zero and goes negative when capacity is cut below held+sold; such a day is not `EXHAUSTED` — calc.py:285, 268-275
- §3.10 job shape MISMATCH — `payload_rate_cents` is the promotion-free rate of the job's OWN mapping's plan, snapshotted at fan-out and never recomputed — cascade.py:41-44
- §3.10 APPLIED — the mapping bumps on every applied job even when nothing moved (direct write, not a re-derivation); the channel bumps only if `mismatch_alert_count` moved — cascade.py:328-339
- §3.10 REJECTED — `last_failure_code` is always `MAPPING_REJECTED`, even for a `CONNECTION_UNAVAILABLE` rejection — cascade.py:352
- §3.10 settlement MISMATCH — `PARTIALLY_APPLIED`/`FAILED` were stated in terms of `rejected_jobs` alone; abandoned children count the same way — cascade.py:96-101
- §3.11 channel mix — `created_at` ties in the ranking fall through to server creation order — calc.py:495-500
Per-calculation verdict: 11 of 16 already pinned; 5 pinned now (`resolve_base_amount`, `eligible_promotions`, `approved_member_promo_in_play`, `day_numbers`/`pooled_state_of`, `channel_mix`). Left undocumented as unobservable through the API: the `peak > allocated_units` clamp in `consumed_units_for`; the `unconsumed > 0` filter in `held_units_on`; the `HEALTHY`+streak>=3 branch of `record_failure`; `rederive_family` on activation can never move a descendant; `apply_bp` is dead code.

### Pass C (the seven remaining route modules) — 28 changes: 13 ambiguity-pins, 15 mismatch-revisions
602/161,281 -> 602/174,035 (+12,754 B).
Highlights: §2.7 check 5 — partner channel-ownership on stay creation reads the still-unvalidated body, so it bites only when `channel_id` is present AND a JSON string; on cancellation check 4 wins, giving `ERR_RESERVATION_NOT_FOUND`; §2.7 check 6 — the `override_overbooking` gate fires on literal JSON `true` only and sits above check 7, so `ERR_OVERRIDE_NOT_PERMITTED` beats `ERR_INVALID_REQUEST`; §2.7 check 20 MISMATCH — the parity gate applies only to `VERIFIED` mappings whose channel has `requires_content_parity` true and tests the freshly recomputed verdict, not stored `parity_state`; §2.7 check 16 MISMATCH — promotion creation added to the horizon-guarded operation list; §2.7 check 18 MISMATCH — the geo test reads the channel alone (`GEO_OFFER` disjunct deleted), member-rate re-pointed at §3.6, four sub-tests in written order so `ERR_OPAQUE_RATE_NOT_ALLOWED` beats the geo failure; §2.7 check 21 — freeze is an all-or-nothing union over every connection the operation reaches; §3.2 — offset/kind consistency is one-directional and `negotiated_account_code` is inert on non-NEGOTIATED classes; §3.2 repricing MISMATCH — none of the six fields is clearable, an echo-only body is a valid repricing that still bumps and queues, and six other fields are immutable and merely unrecognised; §3.4 MISMATCH — mapping creation follows §2.7's global order (scope 9 > connection-missing 15 > duplicate 17) and consults neither `plan_state` nor `connection_state`; §3.4 — content update fields ARE clearable, no version echo, `DISABLED` accepted; §3.5 MISMATCH — the 3000bp stacking cap decides before the `DRAFT` test on submit, and since the cap is never enforced at creation an over-cap PERCENT promotion is creatable but can never leave `DRAFT`; §3.5 MISMATCH — promotion load's four gates land in §2.7 order 11/14/15/21, not the narrated order; §3.6 — the quoted-rate query contract in full, with no state precondition at all; §3.8 MISMATCH — allotment creation evaluates check 15 before check 16; §3.8 MISMATCH — allotment-draw availability is BLOCK-scoped, not per stay night (closes pass B note 1), with a worked Jan 1-10 example; §3.9 MISMATCH — booking admission never consults `plan_state`, no `ChannelMapping` need exist, `ERR_CHANNEL_MAPPING_MISSING` is never raised by a booking, and the nonexistent `geo_markets` field name was removed; §3.9 — reservation list applies the partner's `channel_id` as an implicit pre-filter (empty page, no refusal) while the single read masks a foreign row as a 404; §3.10 MISMATCH — the dispatch freeze test is a union over every currently-`QUEUED` child's connection; §3.11 — the channel-mix window is measured against the `mix_window_days` of the property owning the path channel and may lie wholly in the past; §4 table MISMATCH x2 — the `GET /distribution/rate-plans/{id}` row carried the reprice description verbatim, and the promotion-load row wrongly said "an approved promotion".
All §4 role lists in the partition were checked against every `shape.auth(...)` call: already correct.

### Pass D (reconciliation) — 4 targeted edits
602/174,035 -> 602/174,799 (+764 B).
Cross-pass contradictions found and adjudicated from source:
1. §3.4 vs §3.10 — the rejection failure record. §3.4 read the `last_failure_code = MAPPING_REJECTED` write as part of what makes `MAPPING_NOT_VERIFIED`/`PARITY_BLOCKED` special; §3.10 said every rejection records it. `cascade.py:341-352` decides it: the `VERIFIED -> ERRORED` mapping move is reason-guarded, but `record_failure(connection, "MAPPING_REJECTED")` runs for every reason. §3.4 rescoped to the mapping move only.
2. §3.8 vs §4 — who may send `override_overbooking`. §3.8 claimed `RevenueManager` or `RevenueDirector`, but `routes_booking.py:41` admits only `("RevenueManager","ChannelPartner")`, so a director never reaches the flag. §3.8 rewritten to the impl's real predicate.
3. §2.7 check 7 vs check 8 — check 7 asserted the body is read "without regard to the declared content type". False: `request.get_json(silent=True)` returns `None` for a non-JSON mimetype (`shape.py:50-62`), so a non-JSON body reads as `{}`. Softened both directions.
Check-8 `channel_mapping_id` item (handed up by pass C): RESOLVED as the zero-over-claim reading. The only client-facing occurrence is `shape.q_id("channel_mapping_id")` at `routes_dist.py:81` — a job-list query filter matched literally under check 7 — so no path can raise `ERR_CHANNEL_MAPPING_NOT_FOUND` from check 8. Check 8's field list is now `channel_id`, `rate_plan_id`, `room_type_id`, `parent_rate_plan_id` with only the three corresponding 404s; `ERR_CHANNEL_MAPPING_NOT_FOUND` remains correct in §5 and in the check-4 prose.
Over-claims introduced by passes 1-3 and softened: the fabricated `channel_mapping_id` body identifier; check 7's content-type universal; §3.4's implied "only for these two reasons" conditionality; §3.8's false `RevenueDirector` override claim.
All notes in passA/passB/passC `cross_pass_notes.md` confirmed closed.
Global invariants: §5 — 55 rows == 55 `errors.ERROR_STATUS` entries, ids and statuses identical, no unknown `ERR_` token in prose, every prose attribution matched its raising site (the one intentional divergence — `ERR_INVALID_REQUEST` at 404/405 from `app.py:45-52` — is now stated in §3's intro). §4 — 66 rows == 66 `@bp.<method>` routes, every role list equal to that handler's first `shape.auth(...)`. §2.7 — checks 1-23 each appear exactly once in order, and all 20 "check N"/"priority N" references in §2/§3 resolve correctly and match the real evaluation order.
Verdict: PRD_COMPLETED.md is free of PRD silence and PRD/impl mismatch as far as reconciliation could establish. The only residual softness is deliberate — check 18's member-rate clause defers its "in play" definition to §3.6 rather than restating the predicate inline; under-determined at that point, but not false.

### Step 9 net result
PRD_FINALIZED.md 601 lines / 146,320 bytes -> PRD_COMPLETED.md 602 lines / 174,799 bytes (+28,479 bytes, +19.5%). 69 changes total across the four passes (24 + 13 + 28 + 4): 39 ambiguity-pins, 26 mismatch-revisions, 4 reconciliation corrections.

ORCHESTRATOR FINAL VERIFICATION:
- PRD_COMPLETED.md is NOT byte-identical to PRD_FINALIZED.md (`cmp` differs, +28,479 bytes), so the scan demonstrably ran; PRD_FINALIZED.md is likewise not identical to PRD.md.
- 602 lines, 29 heading lines, still ends at the final §5 error-table row.
- No occurrence of the Step 2 difficulty directive in any of PRD.md / PRD_FINALIZED.md / PRD_COMPLETED.md.
- `workspace/implementation/` newest .py mtime is 04:05 (Step 7's last fix), i.e. no Step 8 or Step 9 pass modified code — so the passing sweep remains valid for the shipped implementation.
- All 8 `results.*.json` present and each reports passed 213 of total 213.

PIPELINE COMPLETE. Steps 1-9 all executed; final deliverable workspace/PRD_COMPLETED.md written.

