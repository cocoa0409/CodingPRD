# Worklog — task_2835_pipeline_nomination_scheduling

## Step 1: Create task directory — 2026-09-05T04:13:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2835_pipeline_nomination_scheduling` and `workspace/` (pre-assigned path from the entrance invocation; no index auto-allocation performed).

## Step 2: Generate scaffold — 2026-09-05T05:58:00.000Z

All three scaffold artifacts are complete and the linter is clean.

**Output** — `/home/ubuntu/github/CodingPRD/tasks/task_2835_pipeline_nomination_scheduling/`

| file | lines | bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 2477 | 125,831 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1995 | 145,618 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4756 | 319,456 |

**SCAFFOLD.yaml (§1.0–§1.7)** — `api_prefix: /pipeline`, `difficulty_level: expert`, `consistency_model: immediate`. 11 entities (Terminal, PipelineSegment, ProductGrade, Tariff, Shipper, ShippingHistoryRecord, NominationCycle, Nomination, BatchTicket, MaintenanceEvent, ImbalanceSettlement), 6 state machines, 2 optimistic-concurrency rules (NominationCycle, Terminal), 14 calculations (effective_capacity, capacity_proration with HISTORY_WEIGHTED/VOLUME_WEIGHTED variants, batch_sequencing, interface_transmix, tariff_pinning, tariff_charge with DELIVERED/SCHEDULED variants, loss_allocation, imbalance_charge, shipper_exposure, volumetric_conservation, terminal_bay_occupancy, …), 39 validations, 53 endpoints, 39 errors, 4 roles (Shipper entity-backed, PipelineScheduler, TerminalOperator, TariffAdministrator, plus a segregation-of-duties constraint). Contains neither design key. The "harder than expert level" directive is absent from `scenario:`.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)** — 9 rules × 2 instances = **18 instances**: dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant.

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9)** — **9 sections, 86 instances** (65 with full `test_recipe`, 21 `excluded_because` stubs citing §1.8): entities 12, state_machines 13, calculations 10, validations 20, endpoints 8, errors 11, rbac 5, cross_cutting_layers 6, consistency_model 1. All 104 instance names across both design files are unique and every stub's `difficulty_instance` resolves to a real §1.8 rule/instance pair.

**Linter** (`scaffold_lint.py`): VERDICT clean — 53 endpoints, 11 entities, 18 §1.8 instances, 65 §1.9 instances, 1208 calls scanned; all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.

Three consistency defects were found and fixed while finishing §1.9: (1) SCAFFOLD.yaml §1.4/§1.6 gave the inject cycle-status guard to both `ERR_TICKET_INVALID_STATE` and `ERR_CYCLE_INVALID_STATE` — §1.2 settles it on `ERR_CYCLE_INVALID_STATE`, so §1.4 and the §1.6 catalog were realigned (3 edits); (2) two calls used a non-existent role `MaintenancePlanner` (maintenance events belong to `PipelineScheduler`); (3) one `POST /pipeline/cycles/{id}/settle` call omitted the required `basis_mode` input.

Orchestrator verification: all three files present, parse as YAML, SCAFFOLD.yaml carries neither design key, and `grep -rn "harder than expert"` across all three returns nothing (no difficulty-directive leak).

## Step 3: Copy shared files — 2026-09-05T05:58:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T06:11:00.000Z

PRD generated and verified.

**Output**: `workspace/PRD.md` — **418 lines, 97,970 bytes**, built incrementally (one small `Write` + 8 heredoc appends + 5 targeted edits). Ends cleanly on the last row of the §5 error table; no audit footer.

**Section skeleton**
- §1 Introduction (3 paragraphs — common-carrier framing, operational pain, determinism/logical-clock contract)
- §2 Global Specifications — 11 subsections: 2.1 RBAC · 2.2 API Response Structure (byte-identical copy of `section-2.2-response-structure.md`) · 2.3 Pagination · 2.4 Resource Identity, Timestamps and the Logical Clock · 2.5 The Order in Which Requests Are Refused (19-rank priority ladder) · 2.6 Stale-View Guards on Repeatable Writes · 2.7 Volumetric Conservation Across the Terminal Book · 2.8 Capacity Conservation Within a Cycle · 2.9 Measurement, Money and Rounding · 2.10 Common Carrier Obligations and Segregation of Duties · 2.11 Cascade Semantics and Version Propagation
- §3 Business Logic — 9 subsections: 3.1 Standing Up the Network · 3.2 Tariff Catalogue & Rate Pinning · 3.3 Opening a Cycle / Collecting Nominations · 3.4 Closing the Window · 3.5 Prorating Capacity · 3.6 Sequencing, Interfaces, Publication & Bay Occupancy · 3.7 Injection, Quality Refusal, Delivery, Compensation · 3.8 Integrity Work, Derates & the Resequencing Loop · 3.9 Settlement, Loss Allocation & Billing
- §4 Endpoint Definitions — 4-column table, 53 rows
- §5 Error Code Catalogue — 2-column table, 39 rows

**Coverage confirmation**: 11 entities · 6 state machines (all 37 transitions; all 35 non-null `from→to` pairs rendered as explicit arrow pairs) · 14 calculations (all 9 constants embedded in business prose) · 39 validations (all `error_id`s + `applies_to` scopes + explicit priority ordering) · 53 endpoints · 39 errors · 4 roles with every `identity:` translated · 2 `concurrency_rules` with `write_endpoint` + `expected_*_version` + exact error/status.

**Hard Contracts** — Field coverage: entities[].fields 109/109, request_body 67/67, query_params 20/20 → PASS. Rule coverage: 39/39 validations, 2/2 OCC, 37/37 transitions, 14/14 calculations, 39/39 conditions, 53/53 side_effects, 109/109 field content, 5/5 sibling-branch symmetry groups equal-density → PASS. Path purity (§3 only): 923 backtick tokens scanned, 0 starting with `/`, 0 bare HTTP-method tokens, 0 method+path tokens → PASS. No fuzzy/approximating words; §2.2 byte-identical to canonical source.

**Two scaffold self-conflicts resolved (flagged for downstream steps)**
1. `NominationCycle.proration_factor` — entity `default: 1.000000` vs. create-endpoint side effect "initialised to null". Followed the endpoint (null at creation); kept the substantive rule ("exactly 1.000000 when `nominated_total_bbl` is zero") on the proration path.
2. `schedule_version` — entity description + state machine say publication increments it; the `build-schedule` endpoint row also claims an increment. Followed the entity/state-machine majority (publication only) and stated explicitly that building does not advance it, so the reading is unique.

Design indices were not opened; no sibling task directories read; nothing outside `workspace/PRD.md` modified.

Orchestrator truncation check: `tail -c 1200` shows the §5 error table terminating on `ERR_CREDIT_LIMIT_EXCEEDED | 402` — a real section boundary, not mid-sentence. `grep -in "harder than expert\|scaffold" PRD.md` returns nothing, so neither the difficulty directive nor any scaffold reference leaked into the contract.

## Step 6: Generate implementation — 2026-09-05T06:52:00.000Z

Implementation complete and smoke-verified. Both smoke servers were reaped by exact PID (ports 18354 and 18933 confirmed free; no broad pkill used).

**Files written** — `workspace/implementation/`

| file | lines | contents |
|---|---|---|
| `core.py` | 492 | 39-id error catalogue + status map, `ApiError`/`fail`, Decimal helpers (`r2/r3/r6`, `dfloor` = ROUND_FLOOR, ROUND_HALF_UP everywhere, no floats for money), instant parse/format (always 3 fractional digits + `Z`), in-memory `Store` (11 dicts + logical clock, default `2026-08-01T00:00:00Z`), envelope/meta builders, `authenticate`, body/field coercers, pagination + filtering |
| `serializers.py` | 243 | 11 entity serializers with the §2.9 precision map (whole barrels as ints, money/volumes 2dp, rates 3dp, ratios 6dp) |
| `calc.py` | 350 | effective capacity, cycle aggregates, history base/`allocation_class`, dual-variant `capacity_proration` + single redistribution pass, interface transmix, sequencing, tariff pinning, exposure, bay occupancy, dual-basis tariff charge, imbalance tiers |
| `cascades.py` | 368 | segment derate recompute, 5-hop maintenance notify cascade, restore cascade, `prorate_cycle`, withdrawal re-proration, `build_schedule` (transmix reserve gate, 24h slots, predecessors), `settle_cycle` (loss allocation + remainder pass, both bases, pinned 8-step imbalance, one DRAFT row per billed shipper) |
| `routes_master.py` | 433 | clock, terminals, product grades, segments, shippers, shipping history, tariffs (incl. activate/supersede cascade) |
| `routes_cycles.py` | 188 | create/close/prorate/build-schedule/publish-schedule/settle + reads |
| `routes_nominations.py` | 258 | submit (twin supersede + OCC), withdraw, request-revision, resubmit + reads |
| `routes_tickets.py` | 219 | inject (quality refusal w/ persisted side effects + 4-hop cascade), deliver, cancel, reschedule-window + reads |
| `routes_maintenance.py` | 130 | create (24h buffer conflict), notify, start, complete + reads |
| `routes_settlements.py` | 85 | certify / invoice (both SoD checks) + reads |
| `app.py` | 65 | blueprint wiring, error handlers, `PORT` (default 10000), `0.0.0.0`, no reloader |
| `start.sh` + `requirements.txt` | 9 + 1 | guarded pip install then `exec python3 app.py`; executable |

**2841 lines total.** Storage is process-memory dicts only — no file, SQLite, or /tmp state; a fresh `start.sh` boot returns `total_count: 0` everywhere and the clock back at `2026-08-01T00:00:00Z`, with zero seeded rows.

**Endpoints: 53 / 53** — 31 POST (30 under `/pipeline` + `/_clock/set_current_utc`), 11 GET single, 11 GET list — enumerated and matched one-for-one against §4.

**Smoke coverage (all green)** — Full happy path (master data → tariff draft/activate → cycle → 2 nominations → close → prorate → build → publish → inject → deliver → settle → certify → invoice); hand-computed settlement checked digit-for-digit (`proration_factor 0.791667`, per-ticket rounding, `loss_allocation 251.32/248.68` summing exactly to the 500 bbl system loss, `imbalance_pct 0.005291` → `STANDARD`, `basis_delta 550.00`, `total_billed 52878.30/52328.30`); five-accumulator conservation exact (500000.00) and `allocated+unallocated == effective_capacity`; PUBLISHED→RESEQUENCING derate cascade with hop-4 re-cut and hop-5 ticket cancellation (`cancel_reason RESEQUENCING`), restore leaving RESEQUENCING intact; refusal spot-checks `ERR_UNAUTHENTICATED`, `ERR_FORBIDDEN_ROLE` (ahead of not-found), `ERR_NOT_RESOURCE_OWNER`, `ERR_STALE_CYCLE_VERSION`, `ERR_STALE_TERMINAL_VERSION`, `ERR_QUALITY_SPEC_VIOLATION`, `ERR_SEGREGATION_OF_DUTIES`, `ERR_TRANSMIX_RESERVE_EXCEEDED` (no tickets created), `ERR_LINEFILL_REQUIREMENT_NOT_MET`, `ERR_TERMINAL_BAY_CONFLICT`, `ERR_MAINTENANCE_WINDOW_CONFLICT`, `ERR_TARIFF_INVALID_STATE`, `ERR_SHIPPER_NOT_ACTIVE`, `ERR_REFERENCE_NOT_FOUND`, `ERR_INVALID_WINDOW`.

**PRD ambiguities resolved**
1. **Nomination `COMPLETED` at settle** — "nominations whose tickets have all reached `DELIVERED`" read literally: a nomination that also owns an earlier `CANCELLED` ticket (from a resequencing rebuild) stays `SCHEDULED`. Cancelled tickets are not excluded from the "all" test.
2. **`proration_factor` at close** — §3.4 refreshes it by the §3.5 formula, so a closed cycle reports `0.000000` (allocated 0 / nominated > 0), not null; a new cycle keeps null.
3. **Effective capacity recompute scope** — §2.7 line "a close, a proration, and any derate change" combined with §3.8 hop three: `prorate` always recomputes; a derate recomputes only intersecting cycles, and only `PUBLISHED` ones can fall to `RESEQUENCING`. A `PRORATED` cycle keeps its derated capacity across event completion.
4. **Manual `request-revision` `cancel_reason`** — unspecified by the PRD (only `RESEQUENCING` and `QUALITY_RETEST_LIMIT` are named); stores `"REVISION_REQUESTED"` and also recomputes `total_transmix_bbl` since a cancelled ticket drops out of that derived sum.
5. **Inventory adjustments have no volumetric guard** — the PRD names no error for driving `inventory_bbl` negative or past `shell_capacity_bbl`, and the catalogue has none, so adjustments are accepted as booked; `ERR_INSUFFICIENT_ORIGIN_INVENTORY` / `ERR_DESTINATION_CAPACITY_EXCEEDED` fire only at inject/deliver.
6. **Validation order on inject** — shape → cycle `PUBLISHED` → ticket state → quality → segment `SHUT` → shipper `ACTIVE` → origin inventory → credit.
7. **Maintenance window ordering** — `window_end <= window_start` returns `ERR_INVALID_WINDOW` (422), not `ERR_INVALID_REQUEST`.
8. **Path existence precedes Shipper ownership**; missing master-data ids in a body are `ERR_REFERENCE_NOT_FOUND`, duplicate unique codes and bad `role_kind` are `ERR_INVALID_REQUEST`; unknown enum values in list filters return an empty page rather than a 400.
9. **`schedule_version`** bumps only on publish, never on build; **transmix reserve gate** sums only the sequence the build would produce.
10. **`linefill_bbl`** is never a segment-creation input — it starts at 0 and moves only via a `LINEFILL` adjustment.

## Step 5: Generate unit tests — 2026-09-05T07:02:00.000Z

Stage 2 is complete. Full test suite generated, audited, and verified.

**Files written** (task root, never under `workspace/`)

`test_helpers/` — 2287 lines: `__init__.py` 44, `api_client.py` 257, `api_errors.py` 92, `assertions.py` 344, `constants.py` 97, `factories.py` 300, `fixtures.py` 727, `test_users.py` 75, `types.py` 351.

`test_suite/` — 5449 lines, 102 tests:

| file | lines | tests | source |
|---|---|---|---|
| `conftest.py` | 51 | — | fixtures only |
| `test_01_master_data_and_reads.py` | 617 | 12 | Corner/entities |
| `test_02_lifecycle_state_machines.py` | 528 | 11 | Corner/state_machines |
| `test_03_core_calculations.py` | 541 | 7 | Corner/calculations + consistency_model |
| `test_04_business_rule_validations.py` | 606 | 15 | Corner/validations |
| `test_05_endpoint_behaviour_and_error_codes.py` | 649 | 11 | Corner/endpoints + errors |
| `test_06_access_control_and_concurrency.py` | 575 | 9 | Corner/rbac + cross_cutting_layers |
| `test_07_proration_variants_and_billed_arithmetic.py` | 402 | 8 | Difficulty: dual_variant_calc, combinatorial_formula |
| `test_08_nomination_and_ticket_state_paths.py` | 243 | 5 | Difficulty: non_linear_state_machine |
| `test_09_transitive_cascades.py` | 242 | 4 | Difficulty: transitive_cascade |
| `test_10_validation_priority_and_boundaries.py` | 326 | 8 | Difficulty: priority_pair_validation_conflict, boundary_precision_check |
| `test_11_cross_entity_and_temporal_overlap.py` | 408 | 8 | Difficulty: cross_entity_state_dependency, resource_temporal_overlap |
| `test_12_compensating_invariants.py` | 261 | 4 | Difficulty: compensating_invariant |

**Coverage**
- Queue A (difficulty index, §1.8): **37 tests** across all **18** instances — every instance has ≥2 (one has 3).
- Queue B (corner index, §1.9): **65 tests** — exactly one per **65** non-stub instances. The **21** `excluded_because:` stubs were not translated.
- **Instances skipped: none.** Every instance in both indices passed the PRD-first two-condition filter.

**Mechanical verification performed**
- Verbatim citations: a purpose-built checker normalises whitespace and greps all 278 `PRD <n.n>: "..."` docstring quotes against `workspace/PRD.md` — **0 mismatches**. It caught and fixed 3 real defects: two paraphrases in `test_07` and one **fabricated PRD sentence** in `test_10` (an invented general-atomicity rule; the PRD has no such sentence, so the assertion is now grounded in §3.3's cycle-version/recompute sentence instead).
- `Design:` tags: all 102 tests carry exactly one tag, last non-blank line of the docstring; all resolve to a real `name:` in the correct source yaml; no dangling tags and no tag pointing at an excluded stub.
- Collection: `pytest --collect-only` → **102 tests collected**, all modules import cleanly. All files `py_compile` clean, zero unused imports.
- Hygiene: no `pytest.mark.skip/skipif/xfail` anywhere; no scaffold/corner/difficulty/design-index vocabulary leaks (the `Design:` tag is the only exception); `__pycache__`/`.pytest_cache` removed; nothing written under `workspace/` (only `PRD.md` was read); `worklog.md` untouched; scratch confined to `/tmp/task_2835_testgen/`; no `pkill` of any kind.

**Two items noted for the parent**
1. Design/PRD divergence flagged, not encoded: the entities design asserts a freshly created cycle has `proration_factor == 1.000000`, but PRD §3.3 says it is null. The test asserts the PRD's value. Four further sub-assertions (three in the entities file, one in RBAC) were dropped as not uniquely derivable from the PRD; the parent instances are still covered.
2. Untested against a running server. The runner has no `-k` selector, so the only real verification is a full sweep — the arithmetic literals (95312.92, 0.580833, 69700, 58334/41666, the 26350 bbl compensation) were hand-re-derived from the PRD rather than observed.

Orchestrator note: Steps 5 and 6 were launched back-to-back as background agents, so they ran concurrently. `find workspace/ -maxdepth 2` confirms neither `test_helpers/` nor `test_suite/` was misplaced under `workspace/` — both are at the task root as required.

## Step 7: Run tests and iterate — 2026-09-05T07:13:00.000Z

All 8 result files are on disk and confirmed clean.

**Iterations run: 1.** The first 8-round parallel stability sweep came back fully green, so no diagnostic protocol steps were triggered.

**Sweep result:** all 8 rounds `passed == total` at **102 / 102**, `failed == 0`, `errors == 0`, `skipped == 0`. Per-round duration ~186s.

Because a first-iteration clean sweep is the shape a false-clean result also takes, the subagent verified it was genuine rather than a collection artifact:
- The suite defines exactly 102 `test_` functions across the 12 files, and all 102 were collected and executed in every round (per-file counts: 12/11/7/15/11/9/8/5/4/8/8/4).
- The collected test-name set was **byte-identical across all 8 rounds**, so no round silently collected a subset; the union of failing tests is empty.
- Every test entry carries a non-zero `duration_seconds`, so no test was a no-op or short-circuited before hitting the server.
- Zero `pytest.mark.skip` / `xfail` markers anywhere in `test_suite/`, and `skipped == 0` in each round — nothing passed by being suppressed.

**Tests deleted:** none. No test failed in any round, so no PRD-silence or unique-derivability review was required.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

The artifact was already consistent as delivered: `test_suite/` (12 files, 102 tests), `test_helpers/` (9 modules), and `workspace/implementation/` (11 modules) were left untouched. Result files are at `workspace/implementation/results.{1..8}.json`.

One note for the record, bearing on interpreting the green sweep rather than on any fix: none of the known fixture-bug patterns applied here. The factories already send money and volumes as JSON numbers, full ISO-8601 instants (`2026-08-01T00:00:00Z`) where the PRD declares instants, and `test_helpers/assertions.py` unwraps the envelope exactly once via `get_success_data()`. The fixtures also thread the cycle OCC token correctly — `nominate()` re-reads the cycle before each submission, which is what PRD §2.6 requires and a common source of spurious `ERR_STALE_CYCLE_VERSION` wipeouts.

**Orchestrator independent re-verification** (not taking the subagent at its word, per the known "clean sweep with no artifacts" failure mode): parsed all 8 `results.*.json` directly — each reports `passed 102 / failed 0 / total 102 / errors 0 / skipped 0` with 102 distinct test names. `grep -rh "^def test_" test_suite/*.py | wc -l` = 102, matching. `grep -rn "mark.skip\|mark.xfail"` across `test_suite/` and `test_helpers/` = 0 hits. The green sweep is genuine.

## Step 8: Finalize PRD — SKIPPED — 2026-09-05T07:14:00.000Z

Skip condition from the skill met exactly: Step 7 exited on the first 8-round sweep with **0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes** — zero iterations beyond the baseline. There is therefore no `<step_7_diff>` to hand off and no Step-7-identified PRD silence to patch, so no subagent was spawned and no `PRD_FINALIZED.md` was produced. Step 9 will consequently start from `workspace/PRD.md`.

Note this is *not* the "byte-identical PRD" failure mode — that mode is a Step 9 hazard. A legitimately absent `PRD_FINALIZED.md` when Step 7 made no implementation fixes is the specified behaviour.

## Step 9: Complete PRD — 2026-09-05T07:45:00.000Z

Run as **three sequential module-partitioned passes** over one shared `workspace/PRD_COMPLETED.md`. A single-shot full scan of a 98KB PRD against 2841 lines of implementation reliably under-scans (and risks a one-shot rewrite truncating the document), so the implementation was partitioned by module: pass 1 performed the `cp` and later passes were explicitly forbidden from re-copying.

**Final size**: `PRD.md` 418 lines / 97,970 chars → `PRD_COMPLETED.md` 419 lines / **126,475 chars** (**+28,505 chars, +29.1%**). Line count grew by only 1 because nearly every edit was an in-paragraph insert/revision; no new sections were added.

**Total: 64 edits — 55 ambiguity-pins, 11 mismatch-revisions.**

### Pass 1 — `core.py`, `app.py`, `serializers.py`, `calc.py`
19 edits (19 pins... of which 2 were mismatch-revisions). 97,970 → 105,077 chars.
- §2.1 — insert — ambiguity — both auth headers read whitespace-stripped (whitespace-only = empty); trimmed values are what get compared/recorded; role match case-sensitive — `core.py:307-314`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A-Z0-9` (24 total) — `core.py:263-267`
- §2.3 — insert — ambiguity — `has_more` = `offset + len(page) < total_count`; offset past the end yields an empty array, not an error — `core.py:287`
- §2.3 — insert — ambiguity — every `created_at` sort key is followed by in-process creation order (descending for the tariff sort; applied twice in the settlement sort), making all 12 list sorts total under the frozen logical clock — `core.py:255-257`
- §2.3 — insert — ambiguity — filters are raw-string equality (no case-folding/partial match), unknown query params ignored, non-matching value gives an empty page, `is_transmix_grade` must be literally true/false → 400 — `core.py:470-485`
- §2.4 — insert — ambiguity — instant parsing accepts `Z`/`z`, any numeric offset (normalised to UTC), zone-less values (read as UTC), any fractional width; rendering **truncates** below the millisecond — `core.py:153-184`
- §2.5 rank 5 — insert — ambiguity — `null` FK treated as omitted; present non-string FK fails at rank 5 with `ERR_REFERENCE_NOT_FOUND`, not as a rank-6 shape error — `core.py:432-439`
- §2.5 rank 6 — insert — ambiguity — absent/whitespace body = empty object; non-JSON or non-object body → 400; `null` field = omitted; numeric strings, integral-valued decimals for int fields, and `"true"`/`"false"` accepted; JSON booleans never accepted as numbers — `core.py:332-403`
- §2.9 — insert — ambiguity — `total_transmix_bbl` is an integer — `serializers.py:152`
- §2.9 — insert — ambiguity — `derate_pct_applied` carried to 2 dp — `serializers.py:147`
- §2.9 — insert — ambiguity — `nominated_total_bbl` and ticket `volume_bbl` carried to 2 dp — `serializers.py:148,189`
- §2.9 — insert (new bullet) — ambiguity — the client-supplied master-data numerics get no imposed scale, round-trip exactly, render integral values as bare integers — `serializers.py:7-14` *(later corrected by pass 2, see below)*
- §2.11 — insert — ambiguity — one `version`/`updated_at` bump per row per **request** regardless of how many cascade hops touch it; rows created in the request stay at version 1 with `updated_at == created_at` — `core.py:224-252`
- §3.2 — insert — ambiguity — pinning tie-break extends to creation order, latest first — `calc.py:234`
- §3.4 — **revise** — **mismatch** — PRD said truncation happens on the derated nameplate "not on the final result"; impl clamps to 0 and then floors the post-subtraction figure as well (observable whenever linefill make-up is fractional) — `calc.py:64-68`
- §3.5 — insert — ambiguity — redistribution ordering tie-break extends to creation order, earliest first — `calc.py:178-179`
- §3.6 — insert — ambiguity — sequencing ordering tie-break extends to creation order, earliest first — `calc.py:206`
- §3.7 — insert — ambiguity — exposure uses only `base_rate_usd_per_bbl` (never tiers/tender minimum), the summed total is itself rounded to 2 dp, an unpinned ticket contributes nothing — `calc.py:240-262`
- §3.9 — insert — ambiguity — a ticket whose nomination has no `pinned_tariff_id` is skipped on both bases — `calc.py:336-338`
- §4 — insert — ambiguity — trailing slash is insignificant in path matching — `app.py:22`
- §5 — insert — **mismatch** — undefined path → `ERR_REFERENCE_NOT_FOUND` 404 (before auth); wrong method → `ERR_INVALID_REQUEST` at HTTP **405**, the sole exception to the table's 400; unhandled fault → `ERR_INTERNAL` 500, an id absent from the catalogue — `app.py:39-55`

### Pass 2 — `cascades.py`, `routes_cycles.py`, `routes_nominations.py`
24 edits (18 pins, 6 mismatch-revisions). 105,077 → 112,889 chars. Pass-1 edits verified intact by spot-grep.
- §2.9 — revise — mismatch — `nominated_bbl` removed from the "no scale imposed" list; it is rounded half up to 2dp at storage on both submit and resubmit, and the tender-minimum / revision-increase gates compare the *raw* request value — `routes_nominations.py:124,228` **(this minimally corrects a pass-1 sentence — see the note below)**
- §3.3 — insert — ambiguity — duplicate `cycle_code` on the same segment → `ERR_INVALID_REQUEST` 400 at rank 6, tested before window ordering; uniqueness scoped per segment — `routes_cycles.py:34`
- §3.3 — insert — ambiguity — omitted/null `shipper_id` is a missing-field error not an ownership error; body FK resolution order `cycle_id, shipper_id, grade_id, origin, destination, supersedes` — `routes_nominations.py:46,54`
- §3.3 — insert — ambiguity — explicit `supersedes_nomination_id` is the stored value and *both* it and the newest open twin are superseded when they differ; the explicit target need not share the twin key, cycle or shipper — `routes_nominations.py:99`
- §3.3 — insert — ambiguity — withdrawal re-proration reuses existing `effective_capacity_bbl`, does not re-freeze history, rewrites only `PRORATED` rows, no status change, no tender-minimum cleanup — `cascades.py:184`
- §3.4 — insert — ambiguity — closing is not gated on the logical clock; the pinning instant is always `window_close_at` — `routes_cycles.py:70`
- §3.5 — insert — ambiguity — every prorate run recomputes `effective_capacity_bbl` and re-snapshots `derate_pct_applied` unconditionally, before the input set is chosen — `cascades.py:128`
- §3.5 — revise — mismatch — input set also admits `REVISION_REQUESTED` under `RESEQUENCING`; empty input set still drives the cycle to `PRORATED` — `cascades.py:114,153`
- §3.5 — insert — ambiguity — cleanup pass exempts nominations with no `pinned_tariff_id`; they settle into `PRORATED` — `cascades.py:168`
- §3.5 — revise — mismatch — four settle hops, adding `SCHEDULED → PRORATED` — `cascades.py:174`
- §3.5 — insert — ambiguity — `RESEQUENCING` pre-check skips unpinned rows; rejected rows leave the set before the history re-freeze — `cascades.py:135,145`
- §3.6 — insert — ambiguity — a rebuild mints new tickets from `sequence_position` 1 and leaves surviving nominations' old `PLANNED` tickets in place (double tickets, both counted in `total_transmix_bbl`); an empty build still reaches `SCHEDULED` — `cascades.py:211,239`
- §3.6 — insert — ambiguity — 24h slot arithmetic is unbounded; windows may run past `ship_end_at` without refusal — `cascades.py:215`
- §3.6 — insert — ambiguity — reserve gate tests only this build's sequence total (not the cycle's `total_transmix_bbl`), strictly — `cascades.py:206`
- §3.8 — insert — ambiguity — hops 3–5 short-circuit when `derate_pct` and `operational_status` are both unchanged, which is why `NOTIFIED → ACTIVE` re-sizes nothing — `cascades.py:84`
- §3.8 — revise — mismatch — hop three's "survives untouched" now excludes the cycle row itself: `effective_capacity_bbl`, `derate_pct_applied`, `unallocated_capacity_bbl` and `version` all move; `proration_factor` does not — `cascades.py:92`
- §3.8 — insert — ambiguity — hop four never raises an allocation, and runs no tender-minimum cleanup (cut-below-minimum → `REVISION_REQUESTED`, not `REJECTED`) — `cascades.py:68`
- §3.8 — insert — ambiguity — the completion restore pass is unconditional, confined to `RESEQUENCING` cycles, raises no allocation, leaves `proration_factor` alone — `cascades.py:96`
- §3.8 — revise — mismatch — request-revision records `cancel_reason` `REVISION_REQUESTED` and also recomputes `total_transmix_bbl` (not `proration_factor`) — `routes_nominations.py:191,194`
- §3.8 — insert — ambiguity — resubmit has no cycle-status gate, leaves `revision_count` alone, keeps `pinned_tariff_id` — `routes_nominations.py:205`
- §3.9 — revise — mismatch — settlement writes **nothing** to the segment's `system_loss_bbl` (PRD said it "reconciles" it); `SCHEDULED → COMPLETED` needs ≥1 ticket and *all* `DELIVERED`, so any `CANCELLED` ticket or no ticket blocks it — `cascades.py:354,358`
- §3.9 — insert — ambiguity — loss remainder tie-break adds creation order; pass skipped when the remainder is exactly 0 — `cascades.py:307`
- §3.9 — insert — ambiguity — penalty rate drawn from the lowest-`sequence_position` *billing* ticket, ties by `created_at` then creation order; 0 when that nomination is unpinned — `cascades.py:273`
- §3.9 — insert — ambiguity — settlement row creation order tie-break by shipper creation order — `cascades.py:269`

**Pass 2's correction of a pass-1 sentence** (reported explicitly, as instructed): pass 1's new §2.9 bullet asserted `nominated_bbl` "is stored and echoed back exactly as it was given" with proration weighting the unrounded value. That is wrong against the implementation — `routes_nominations.py:124` and `:228` both store `r2(volume)` and `serializers.py:171` echoes the stored 2dp figure. Pass 2 removed `nominated_bbl` from that bullet's field list and replaced the trailing claim with the actual rounding rule, preserving the rest of the bullet. Pass 3 was told not to re-add it and confirmed it did not.

### Pass 3 — `routes_master.py`, `routes_tickets.py`, `routes_maintenance.py`, `routes_settlements.py`
21 edits (18 pins, 3 mismatch-revisions). 112,889 → 126,475 chars.
- §2.5 rank 6 — revise — mismatch — `capacity_derate_pct` was documented as "0 through 1 inclusive"; impl requires strictly greater than 0 (`positive=True`) and no greater than 1 — `routes_maintenance.py:36-38`
- §2.5 rank 6 / rank 11 — revise — mismatch — rank 6 claimed `window_end` after `window_start` yields `ERR_INVALID_REQUEST`; every window-ordering test in impl reports `ERR_INVALID_WINDOW` (422). Removed from rank 6, enumerated at rank 11 — `routes_maintenance.py:42`, `routes_tickets.py:177`, `routes_cycles.py:37`
- §4 tariff-activate row — revise — mismatch — table said "any *older* overlapping EFFECTIVE tariff"; impl supersedes every overlapping EFFECTIVE peer regardless of filing order — `routes_master.py:404-413`
- §2.3 — insert — ambiguity — product-grade list ties on `sequence_rank` broken by `created_at` then creation order (plus matching §4 table cell) — `routes_master.py:151`
- §2.5 rank 3 — insert — ambiguity — ownership is judged only after the target row resolves, so a `Shipper` naming a nonexistent ticket/settlement gets the family 404, not 403 — `routes_tickets.py:200-204`, `routes_settlements.py:62-65`
- §2.5 rank 4 — insert — ambiguity — master-data path ids (terminal, grade, segment, shipper, history, tariff) yield `ERR_REFERENCE_NOT_FOUND` — `routes_master.py:70,95,142,209,322,398`
- §2.5 rank 6 — insert — ambiguity — code-uniqueness tests live at rank 6, report `ERR_INVALID_REQUEST`, and run after all other shape checks — `routes_master.py:20-23,53,126,183,247`
- §2.5 rank 6 — insert — ambiguity — undeclared body members are ignored; the no-body actions accept any parseable JSON object — `routes_maintenance.py:72`, `routes_settlements.py:23`
- §2.4 — insert — ambiguity — clock endpoint returns 200 with empty `data`; may be wound backwards or to its current value — `routes_master.py:29-35`
- §3.1 — insert — ambiguity — no relation enforced between `min_operating_inventory_bbl` and `shell_capacity_bbl`; `injection_bays` has no upper bound — `routes_master.py:48-52`
- §3.1 — insert — ambiguity — `LINEFILL` without `segment_id` → `ERR_INVALID_REQUEST`, evaluated before the stale-version guard; `segment_id` still resolved on `INVENTORY`; the segment row is versioned too; `adjustment_bbl` unconstrained (may drive balances negative/over shell) — `routes_master.py:72-88`
- §3.1 — insert — ambiguity — proration-policy filing has no from-state guard and re-filing the same value still bumps `version` — `routes_master.py:206-214`
- §3.1 — insert — ambiguity — re-suspending a `SUSPENDED` shipper is accepted, overwrites `suspended_reason`, bumps version; no reinstatement exists — `routes_master.py:260-269`
- §3.1 — insert — ambiguity — no uniqueness on a history row's `cycle_code`; duplicates each qualify and each counts toward `allocation_class`; `cycle_end_at` unconstrained vs the clock — `routes_master.py:293-316`
- §3.2 — insert — ambiguity — activation overlap is half-open (abutting peers survive), null `effective_to` is unbounded, DRAFT/SUPERSEDED peers untouched, peers versioned — `routes_master.py:385-413`
- §3.6 — insert — ambiguity — reschedule window-ordering is `ERR_INVALID_WINDOW`; containment in the shipping window is inclusive at both ends; no cycle-status gate — `routes_tickets.py:177-182`
- §3.6 — insert — ambiguity — a `PLANNED` bay peer counts regardless of its cycle's or nomination's status — `calc.py:295-311`
- §3.7 — insert — ambiguity — injection measurement constraints (measurements ≥ 0, `injected_bbl` > 0) — `routes_tickets.py:38-40`
- §3.7 — insert — ambiguity — a second off-spec presentation writes `REJECTED` over `REJECTED`; a passing retest never resets `retest_count` — `routes_tickets.py:46-59`
- §3.7 — insert — ambiguity — quality hop three: only the status change is conditional on `SCHEDULED`; `revision_count`/`allocated_bbl` unconditional. Hop four also refreshes `nominated_total_bbl` and leaves `proration_factor` — `routes_tickets.py:61-70`
- §3.7 — insert — ambiguity — the origin-floor test and volumetric debits use raw supplied `injected_bbl`, before 2-dp storage rounding — `routes_tickets.py:81-97`
- §3.7 — insert — ambiguity — delivery is gated only by ticket state, volume ceiling (inclusive, vs stored `injected_bbl`) and shell room: no cycle-status, segment-status, shipper-standing or credit test — `routes_tickets.py:107-124`
- §3.7 — insert — ambiguity — explicit cancellation leaves the nomination and the cycle's allocation totals alone; `cancel_reason` is free text — `routes_tickets.py:137-161`
- §3.8 — insert — ambiguity — a gap of exactly 24 h still conflicts (only strictly >24 h clears); conflict test runs after the ordering test; cross-segment and `COMPLETED` peers never conflict — `routes_maintenance.py:45-52`
- §3.8 — insert — ambiguity — `notified_at`/`notified_shipper_count` are frozen at notification; scope counted before hops 2-5; start/complete never recompute them — `routes_maintenance.py:79-99`
- §3.9 — insert — ambiguity — `invoice_number` required, non-unique, validated before the from-state guard; both duty tests are exact trimmed string compares and are skipped when the recorded id is null — `routes_settlements.py:29,43-50`

### Orchestrator final verification
- `cmp PRD.md PRD_COMPLETED.md` → **DIFFERENT** (the byte-identical failure mode did not occur; +28,505 chars).
- `PRD_COMPLETED.md` ends on `| ERR_CREDIT_LIMIT_EXCEEDED | 402 |` — a real section boundary, not mid-sentence. All 39 §5 error rows and all 28 headings intact, so no pass truncated the document.
- `grep -in "harder than expert\|SCAFFOLD"` on `PRD_COMPLETED.md` → no hits. No difficulty-directive or scaffold leakage into the final contract.
- Every `implementation/*.py` and `start.sh` mtime is 06:19–06:31, all predating the 07:05 sweep results — Step 9 modified no implementation code, so the verified 8/8 × 102/102 green sweep still describes the shipped implementation.
- `PRD_FINALIZED.md` is intentionally absent (Step 8 skipped with zero Step 7 fixes); Step 9 correctly sourced from `PRD.md`.

**Pipeline complete.** `workspace/PRD_COMPLETED.md` written.
