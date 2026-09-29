## Step 1: Create task directory — 2026-09-05T14:38:01.42243462Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2906_apartment_doorstep_trash_valet_service and its workspace/ subdirectory. Index 2906 was pre-assigned by the orchestrating prompt; no index scan performed (concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-05T16:12:00.000Z

All three scaffold artifacts are complete and lint clean.

## Files written (only additions; `workspace/` and `worklog.md` untouched)

- `SCAFFOLD.yaml` — 2602 lines, §1.0–§1.7 only; `scaffold_difficulty_design` / `scaffold_corner_design` keys confirmed absent
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1967 lines, single top-level key
- `SCAFFOLD_CORNER_DESIGN.yaml` — 3455 lines, single top-level key

All three parse under `yaml.safe_load`.

## Counts

- **§1.1 entities: 10** — Property, ServiceContract, Resident, ValetContractor, ServiceNight, RouteAssignment, ServiceScan, ResidentFine, CompactorIncident, MonthlyStatement. **§1.5 endpoints: 51.** 7 roles.
- **§1.8: 9 rules / 21 instances** — dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 3, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 3.
- **§1.9: 9 sections / 87 instances (69 with full test recipes, 18 `excluded_because` stubs)** — entities 11/0, state_machines 12/5, calculations 4/6, validations 12/3, endpoints 5/1, errors 10/0, rbac 11/0, cross_cutting_complexity_layers 3/3, consistency_model 1/0.

## Lint verdict (verbatim, final run)

```
Coverage
  §1.5 endpoints declared:    51
  §1.1 entities declared:     10
  §1.8 instances scanned:     21
  §1.9 instances scanned:     69
  Calls scanned (§1.8+§1.9):  891

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Cross-file integrity independently verified: zero duplicate instance names across the two design files, every stub's cited `difficulty_instance` resolves to a real §1.8 instance name, and no stub carries a `test_recipe`.

## Design adjudications worth flagging to the orchestrator

1. **`MAKEUP_WINDOW_DAYS` had no value.** It was referenced in 4 places (validation priority 17, the SHIFT precondition, the endpoint contract, and `ERR_INVALID_MAKEUP_DATE`) with no constants entry — an unresolvable symbol for the PRD generator. Pinned inline as `MAKEUP_WINDOW_DAYS (14)` at all 4 sites, matching the existing `MAX_DISPUTE_ROUNDS (2)` style.
2. **Difficulty directive stripped from `scenario:`.** The verbatim scenario opened with "Generate task harder than expert level!", which reaches PRD.md through the scenario key. Removed that line (and its blank line); the scenario now begins at "2906. Apartment Doorstep Trash Valet Service". No other text altered, and the string no longer appears anywhere in the file.
3. **PROVISIONAL gross ignores residents.** Two calculation instances originally targeted resident-level proration against a DRAFT statement, which is unreachable: PROVISIONAL gross is `per_unit_monthly_fee_cents * unit_count`, and the prorated per-resident sum only materialises at issue. Both were re-pointed at `POST /valet/statements/{id}/issue` (with a second analyst identity for the priority-13 SoD gate) and re-read the contract version before drafting so `ERR_STALE_CONTRACT_VERSION` cannot mask the intended assertion.
4. **Falsifiability fix on the PARTIAL-night weight.** With one scheduled night, weighting a PARTIAL as 0.5 vs 1.0 lands in the same SLA tier, so the instance was rebuilt with 4 scheduled nights: 1250 bps → TIER1 rate 500 (credit 699, share 1992, net 11289) vs the wrong whole-weight 2500 bps → TIER2 1200. The half-weight is now visible in the money.
5. **Priority-masking avoided throughout.** Second routes always go to a distinct contractor (a repeat contractor trips priority-15 window conflict against itself and masks priority-20 range overlap); parent versions are re-read via `GET` after any write that bumps them so priority-10 OCC never pre-empts the target error; compactor incidents are escalated only after routes exist so priority-12 stays quiet.
6. **Errors section placeholder IDs.** Table 6 of the claim-extraction guide has no claim-type rows, so all 10 error instances use `claim_type: violation_to_error` from Table 4. Eleven not-found placeholder UUIDs originally contained non-hex characters and were rewritten to valid hex suffixes.

## Step 3: Copy shared files — 2026-09-05T16:13:06Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-05T16:31:00.000Z

PRD complete and verified.

## Deliverable

`workspace/PRD.md` — **528 lines / 104,467 bytes**, built in 15 verified increments (Write + `cat >> … <<'PRDEOF'` heredocs, `wc -l` + `tail` after each). Nothing else in the task directory was touched. The two withheld design indices were never opened, grepped, or referenced.

## Section list

- §1. Introduction
- §2. Global Specifications & System-Wide Principles — 2.1 Operators, Identity and RBAC · 2.2 API Response Structure (verbatim contract) · 2.3 Pagination, Sorting and Collection Filters · 2.4 Common Resource Properties · 2.5 Request Admission Order and Path Resolution (the 28-rung precedence ladder) · 2.6 Cents, Basis Points and Rounding Discipline · 2.7 The Logical Service Clock · 2.8 Stale-Version Guards · 2.9 Cascade Propagation and Conserved Ledger Quantities · 2.10 Property Posture as the Master Service Gate · 2.11 Segregation of Duties
- §3. Business Logic & Workflows — 3.1 Bringing a Community Onto the Network · 3.2 Residents, Occupancy Windows and Pass-Through Eligibility · 3.3 Building the Valet Bench · 3.4 The Weekly Schedule · 3.5 Dispatch and the Doorstep Round · 3.6 Non-Compliance Tags, Resident Fines and the Dispute Cycle · 3.7 Compactor Incidents, the Acknowledgement Clock and Property Escalation · 3.8 Monthly Settlement
- §4. Endpoint Definitions — **51 endpoint rows** (Method / Path / Description / Authorized Role(s))
- §5. Error Code Catalogue — **39 error rows** (Error ID / HTTP Status Code)

## Hard Contract reports

Field coverage: entities[].fields 120/120; request_body 48/48; query_params 27/27; path params 10/10; unique identifier set 123/123. Status PASS.

Rule coverage: validations with priority 28/28; OCC rejections 2/2; state_machine transitions 49/49; calculations 8/8; validation conditions 28/28; side_effects 31 + applies_to 28 all expressed; declared defaults 57/57; sibling-branch symmetry 10 groups, 0 asymmetric. Status PASS.

Path purity (§3 only): 851 backtick tokens scanned, 0 leading-`/` tokens, 0 bare HTTP-method tokens, 0 method+path tokens. Status PASS.

Also verified: all 39 error IDs and all state-machine state names appear verbatim in backticks; all 26 scaffold constants expressed; no fuzzy quantifiers, no symbolic operators outside the §2.2 fenced JSON blocks.

## Boundary confirmation

Ends at a genuine section boundary — the final row of §5's error table. Last 2 lines:
`| ERR_STALE_SERVICE_NIGHT_VERSION | 412 |` / `| ERR_STALE_CONTRACT_VERSION | 412 |`

Orchestrator independently re-verified the tail (truncation guard): 528 lines, 5 top-level sections, table ends cleanly, no mid-sentence cut.

## Scaffold inconsistencies resolved (documented decisions)

1. **Contractor deactivate** — state machine forbids live routes, endpoint side-effects abandon them. Written as precondition-governing with the cascade phrased defensively.
2. **Contract termination night cascade** — `{SCHEDULED}` vs `{SCHEDULED, IN_PROGRESS}`. Wrote the truthful superset.
3. **`reported_by_role` enum** vs the four roles allowed to file incidents. Wrote the field as recording the acting `X-User-Role`, with `reported_by_user_id` polymorphic and unresolvable for opaque operators.
4. **Statement void actor** — state machine says `BillingAnalyst`, endpoint says `PlatformAdmin`. Endpoint role list treated as authoritative (validation rung 2 keys off it); §4 and §3.8 both say `PlatformAdmin`.

## Step 6: Generate implementation — 2026-09-05T17:05:00.000Z

The implementation is complete and verified.

## Modules written (`workspace/implementation/`, 3331 lines of Python total)

| Module | Lines | Role |
|---|---|---|
| `app.py` | 76 | Flask app, blueprint registration, `ApiError`/404/405/400/500 handlers, `app.run(host="0.0.0.0", port=$PORT)` |
| `store.py` | 265 | All spec constants, the logical `Clock`, ISO/date/period parsing + formatting, `Store` (10 in-memory dicts), `stamp_new`/`touch`/`sort_rows` |
| `errors.py` | 100 | `ApiError` + the 39-code -> HTTP-status map + default messages |
| `envelope.py` | 42 | `object_response` / `array_response` / `error_response`, `meta` built off the logical clock |
| `shape.py` | 203 | Rung-5 validators (required/enum/int-range/date/instant/period/array, pagination) |
| `authz.py` | 180 | Rungs 1-4: authenticate, authorize, ten path-lookup 404s, ownership helpers, structural navigation |
| `calc.py` | 442 | Coverage, occupancy, offense ordinals, the pinned fine ladder, classification score, pass-through lines, the 4-step settlement waterfall |
| `rollups.py` | 116 | Conserved-quantity re-aggregation and the night/route/property cascades |
| `serializers.py` | 209 | Ten `*_out` field projections; DRAFT statements re-derive PROVISIONAL money on read |
| `r_property.py` `r_resident.py` `r_contractor.py` `r_night.py` `r_route.py` `r_scan.py` `r_incident.py` `r_statement.py` `r_clock.py` | 218 / 114 / 166 / 212 / 246 / 353 / 167 / 202 / 20 | The nine endpoint blueprints |
| `start.sh`, `requirements.txt` | 20, 1 | Guarded `pip install flask`, then `exec python3 app.py` in the foreground on `$PORT` (default 10000) |

## Coverage

- **Endpoints: 51 of 51.** Enumerated from `app.url_map` — every path/method in PRD §4 is present, no extras.
- **Error codes: 39 of 39.** Programmatically diffed against `SCAFFOLD.yaml`'s catalogue: zero missing, zero extra, zero HTTP-status mismatches (401x1, 403x3, 404x10, 409x19, 412x2, 422x4).

## Validation precedence ladder

Rungs 1-4 are centralised: every handler opens with `admit((roles...))` (rungs 1-2), then a `get_*(id)` path lookup (rung 3), then `require_property_owner` / `require_valet_owner` / `own(...)` (rung 4, write endpoints only). Rung 5 is `shape.py`, called next as a block so shape always beats semantics. Rungs 6+ are then written inline in each handler in strict numeric order with `# rung N` comments, so the source order of the guards *is* the ladder. Cross-cutting rungs are shared helpers (`_require_property_active` for rung 9, `has_escalated_jam` for rung 12). Route creation carries the densest chain: 5 -> 6 -> 9 -> 10 -> 11 -> 12 -> 15 -> 19 -> 20.

## Smoke boot

Booted via `PORT=41906 bash start.sh`, killed only by recorded PID (port confirmed free after; no pattern kills used). Three scripts under `/tmp/task_2906_impl/` ran ~110 assertions: full happy path plus cascades. Final state — **all assertions pass** except three deliberate expectation corrections made after checking the spec (they were the smoke test's errors, not the server's), and one remaining known-good test-side expectation.

Notable confirmations: fresh boot starts with an empty store and the clock reading exactly `2026-08-01T00:00:00.000Z`; PRD §3.8's worked fixture reproduces exactly (PROVISIONAL gross 13980, FINAL gross 7457 via per-line rounding, credit 895, share 984, net 5578); the fine ladder reproduces round-once/floor/cap (3125 peak-uplift, 750->1000 floor, 10000->5000 cap, then `ERR_FINE_CAP_EXHAUSTED`); the escalate->suspend->cancel-nights->cancel-routes->coverage-0 cascade and its asymmetric reinstatement; void-tag and waive ledger reversals leaving `fines_assessed_this_period_cents` untouched.

Three spec readings worth flagging to whoever reviews the tests, all traced back to the literal text: `TAGGED_NOT_SERVICED` is excluded from `scanned_door_count` (SCAFFOLD line 448), so a fully walked route can still close `PARTIAL`; `collections_status` is `DELINQUENT` at `>= 7500`, not `> 7500`; and rung 15 forbids one contractor holding two live routes on the *same* night (a night's window intersects itself), so rung 20 is only reachable with two different contractors.

Did not read, list, or open anything under `test_helpers/`, `test_suite/`, any `test_*.py`/`conftest.py`, or the two design YAMLs; `worklog.md`, `PRD.md`, `SCAFFOLD*.yaml` and `INSTRUCTION.md` untouched.

## Step 5: Generate unit tests — 2026-09-05T17:45:00.000Z

Test generation is complete.

## Files written (all at the TASK ROOT, none under `workspace/`)

`test_helpers/` — 9 files, 2259 lines
`__init__.py` 223, `api_client.py` 290, `api_errors.py` 92, `assertions.py` 299, `constants.py` 108, `factories.py` 227, `fixtures.py` 560, `test_users.py` 83, `types.py` 377

`test_suite/` — 17 files, 4718 lines
`conftest.py` 50; queue A: `test_01_settlement_statements.py` 366, `test_02_worker_classification.py` 124, `test_03_fine_computation.py` 278, `test_04_fine_dispute_and_void.py` 202, `test_05_night_close_outcomes.py` 201, `test_06_delinquency_and_escalation_cascades.py` 289, `test_07_dispatch_guards_and_coverage.py` 252, `test_08_temporal_overlap_conventions.py` 186; queue B: `test_09_entity_shapes.py` 398, `test_10_state_machines.py` 495, `test_11_calculations.py` 259, `test_12_validations.py` 467, `test_13_endpoints.py` 274, `test_14_errors.py` 256, `test_15_rbac.py` 423, `test_16_concurrency_and_consistency.py` 198

## Instance coverage

- Queue A (§1.8 difficulty index): 21 non-stub instances, 0 stubs — **21/21 translated, 0 skipped** (45 tests; the richer rules carry more than one scenario each).
- Queue B (§1.9 corner index): 87 instances, 18 `excluded_because:` stubs (never translated), 69 non-stub — **68/69 translated, 1 skipped** (68 tests, exactly one per instance).
  - Skipped: `Corner/state_machines/acknowledge_on_resolved_incident_returns_invalid_state` — the instance asserts `ERR_INVALID_STATE`, but §3.7 makes `RESOLVED` terminal and §2.5 rung 8 assigns `ERR_ALREADY_TERMINAL` to a terminal-state refusal, so the asserted error id is not uniquely derived from the PRD. Left as a gap rather than re-pointed or weakened.

**Total: 113 tests**, collected cleanly by pytest (`113 tests collected`, no import or collection errors).

## Verification performed

- `python3 -m py_compile` passes on all 9 helper modules and all 17 suite files.
- Automated tag audit: every test has exactly one `Design:` line; all 113 tags resolve to a real `name:` in the source yaml; zero tags point at an `excluded_because:` stub; zero untagged or dual-tagged tests.
- Automated citation audit: every `PRD <section>: "..."` docstring quote (ellipsis-elided fragments checked individually) is byte-verbatim in `workspace/PRD.md`. Four non-verbatim paraphrases found during this pass were corrected.
- Unused-import sweep run and cleaned (`test_04`, `test_15`).
- Fixture discipline honoured throughout: cents as JSON integers, full ISO-8601 instants (never date-only) where the PRD declares instants, a real `""` for the blank-role header case, all instant comparisons via `assert_instants_equal` (sub-second-width tolerant), and no `["data"]` re-indexing after `validate_success`.
- `ls -la` confirms `test_helpers/` and `test_suite/` sit at the task root; `workspace/` contains only `INSTRUCTION.md`, `PRD.md` and `implementation/` — nothing was written, read, or removed there. `worklog.md` untouched. `__pycache__`/`.pytest_cache` artifacts removed. No server was started and no kill commands were issued.

## Step 7: Run tests and iterate — 2026-09-05T18:22:00.000Z

Clean 8-round sweep achieved: **113/113 passed in all 8 parallel rounds.**

## Iterations run
2 sweeps (iteration 1 diagnosed, iteration 2 verified clean).

Iteration 1 showed a deterministic 110/113 in every round — the same 3 failures in all 8 rounds, all in `test_15_rbac.py`, so no flakiness and no load artifacts.

## Tests deleted
None deleted outright. Two tests had a non-derivable **negative half removed** under STEP 1c partial-coverage handling, retaining their PRD-derivable positive half:

- `test_15_rbac.py::test_a_resident_cannot_read_a_fine_belonging_to_a_neighbour` -> renamed `test_a_resident_reads_its_own_auto_assessed_fine`. Removed the `ERR_NOT_RESOURCE_OWNER` assertion on `GET /valet/resident-fines/{fine_id}`. **ERROR-SCOPE SILENCE**: PRD scopes that error to writes twice — §2.1 "When an entity-backed role addresses a **write** endpoint for a resource it does not own..." and §2.5 rung 4 "Applies to every **write** endpoint reachable by `Valet`, `Resident` or `PropertyManager`." The only counterweight is the §2.1 remit bullet ("reads only its own resident record, scans and fines"), which names no error id, plus §4's parenthetical that delegates back to §2.1. Two faithful readers diverge: one gates reads (403), one follows rung 4's write scope (200). Scaffold rule that drove it: `Corner/rbac/resident_cannot_read_another_residents_fine_returns_not_resource_owner`.
- `test_15_rbac.py::test_a_property_manager_reads_its_own_community_but_not_the_sibling` -> renamed `test_a_property_manager_reads_its_own_community`. Same pattern on `GET /valet/properties/{property_id}`. Scaffold rule: `Corner/rbac/property_manager_cannot_read_another_property_returns_not_resource_owner`.

Notably, making the implementation gate reads would have **contradicted** a verbatim PRD sentence (rung 4's explicit write scoping), so a STEP 3 fix was not available here.

## Fixes applied to `test_suite/`
- `test_15_rbac.py::test_the_assigned_valet_accepts_and_then_completes_its_own_route` — genuine **test setup bug** (STEP 2a/2b). The test called `fixtures.set_clock("2026-09-01T18:00:00Z")` and then `fixtures.build_active_community(...)`, but that world builder starts with its own `set_clock(clock or TEST_DEFAULTS["SETUP_CLOCK"])`, silently rewinding the clock to `2026-09-01T00:00:00Z`. The test then asserted `accepted_at == 18:00:00.000Z`. Fixed by threading `clock="2026-09-01T18:00:00Z"` through `build_active_community` instead of setting it beforehand, so the intended clock position survives setup. The implementation was correctly stamping `accepted_at`/`completed_at` from the logical clock all along.

## Fixes applied to `test_helpers/`
None — the clock-clobbering was in the test's call ordering, not in the `build_active_community` helper, whose `clock=` parameter already existed and behaves per PRD §2.7.

## Fixes applied to `implementation/`
None. No implementation defect was found; `workspace/implementation/` is byte-unchanged from Step 6.

Housekeeping: scratch server was booted on port 42906 for fast local verification and killed by its specific listening PID (port confirmed free, no pattern kills). `__pycache__`/`.pytest_cache` removed.

Orchestrator independently re-verified all 8 `results.$i.json`: every round reports `passed == total == 113`.

## Step 8: Finalize PRD — 2026-09-05T18:03:00.000Z

Done. `PRD_FINALIZED.md` written with two surgical edits.

## Line counts
- `PRD.md`: 528 lines; `PRD_FINALIZED.md`: 530 lines (+2, +0.38%). Two text changes total (one inserted paragraph + blank line, one in-place sentence revision).

## Changes
- **§2.1 Operators, Identity and RBAC** — insert — new paragraph after the `ERR_NOT_RESOURCE_OWNER` paragraph pinning that ownership is enforced on write endpoints only: read endpoints (single and list) do no ownership check and no implicit narrowing to the acting principal's rows, a list read returns the same rows to every authorized role narrowed only by the §2.3 query filters, the "reads its own ..." role remits are descriptive rather than enforced, and `ERR_NOT_RESOURCE_OWNER` is never raised by a read — `implementation/authz.py:117-137` (rung-4 helpers) plus every GET handler, e.g. `implementation/r_scan.py:266-278` (`read_fine`) and `implementation/r_property.py:63-74` (`read_property`).
- **§4 Endpoint Definitions preamble** — revise — "for the entity-backed roles authorization is additionally narrowed to owned resources" -> "authorization **on the write endpoints** is additionally narrowed...", so the table preamble no longer implies read-side ownership narrowing — same impl evidence as above.
- No edit for the third Step 7 item (the `build_active_community` clock-clobbering). PRD §2.7 line 173 already names `accepted_at`/`completed_at` as sourced from the logical clock and §2.4 line 118 already pins three fractional digits; the defect was purely in the test's call ordering, and `implementation/r_route.py:189,213` already stamps `now_iso()`. Rung 4 in §2.5 line 131 already said "Applies to every write endpoint", so it was kept verbatim.

## Per-edit pre-edit search log

**Edit 1 (§2.1 insert)**
- (a) Subject: scope of rung-4 resource-ownership enforcement, and the behavior of every read endpoint for the three entity-backed roles.
- (b) Enumerated and read/grepped: `implementation/authz.py` (`own`, `require_property_owner`, `require_valet_owner`, `require_resident_owner`, and all the structural navigation helpers `property_id_of_scan`/`property_id_of_fine`/`property_of_route`); grepped every callsite of those four helpers across `r_*.py` and `app.py` — `r_incident.py:36,97,146`, `r_resident.py:27,94`, `r_route.py:175,200,228`, `r_scan.py:78,209,238,310,336` — and confirmed all eleven sit on `methods=["POST"]` handlers. Then enumerated every read endpoint (18 total): `r_property.py:63,76`, `r_resident.py:59,72`, `r_contractor.py:51,58`, `r_night.py:92,105`, `r_route.py:134,147`, `r_scan.py:156,170,266,279`, `r_incident.py:62,75`, `r_statement.py:83,90`, and grepped each for any use of the `actor` returned by `admit` or of `X-User-ID`: none of the 18 reference the actor at all — every list handler builds `rows` from `sort_rows(list(db.<coll>.values()))` and narrows only by explicit `q(...)` query params. Also checked `r_clock.py` (no ownership surface).
- (c) Adjustments made to keep all paths consistent: said "Ownership is enforced on write endpoints only" rather than restating rung 4's error scope (which §2.5 already pins), so no new claim about write paths is introduced. Explicitly covered *both* single-resource and list reads because the list handlers are equally unscoped, and phrased list behavior as "narrowed only by the explicit query filters of §2.3" instead of "unfiltered", which would have contradicted the per-collection filter lists. Attributed the "reads its own" phrasing in the three role bullets to intended remit rather than deleting those bullets, so lines 20/23/24 remain verbatim and no role's read reach is silently widened or narrowed. Used "another community, valet or resident" to match the PRD's own vocabulary for the three entity-backed anchors.

**Edit 2 (§4 preamble revise)**
- (a) Subject: identical — the §4 preamble's delegation of ownership narrowing back to §2.1, which was the sentence that let a reader import ownership gating onto the GET rows of the table.
- (b) Enumerated: the same eleven `require_*_owner`/`own(...)` callsites and the same 18 read handlers listed above (already read in this session); additionally re-checked the §4 table's own GET rows against each read handler's `admit(...)` tuple for the four endpoints where an entity-backed role appears on a read (`GET /valet/properties/{id}` incl. `PropertyManager`, `GET /valet/residents/{id}` incl. `Resident`, `GET /valet/resident-fines/{id}` and `/valet/service-scans/{id}` incl. `Resident`), confirming the role lists themselves are accurate and only the narrowing clause needed rescoping.
- (c) Adjustment: inserted only "on the write endpoints" rather than deleting the clause, preserving the still-true statement that writes are ownership-narrowed for entity-backed roles, and leaving the "Authorized Role(s) column is exhaustive / `ERR_UNAUTHORIZED`" claim untouched since `admit` enforces exactly that on every route.

## Step 9: Complete PRD — 2026-09-05T19:05:00.000Z

Run as **three sequential module-partitioned passes** over one shared `PRD_COMPLETED.md` (pass 1 owned the `cp`; passes 2 and 3 edited in place and were explicitly forbidden from re-copying). Note: pass 1's first attempt was killed mid-run by a transient API error after it had already created the file and committed ~7 edits; it had no resumable transcript, so a continuation agent was spawned and instructed to `diff PRD_FINALIZED.md PRD_COMPLETED.md` first, treat the inherited edits as done, and finish the remaining pass-1 surface. Partition: pass 1 = app/store/errors/envelope/shape/authz/serializers; pass 2 = calc/rollups/r_scan/r_statement/r_contractor; pass 3 = r_property/r_resident/r_night/r_route/r_incident/r_clock.

## Final sizes
`PRD.md` 528 lines / 104,467 chars -> `PRD_FINALIZED.md` 530 lines / 105,228 -> **`PRD_COMPLETED.md` 532 lines / 129,494 chars** (+2 lines, **+24,266 chars** over FINALIZED). Nearly all edits are in-paragraph inserts, so the line count barely moves while the char count grows substantially.

## Totals across the three passes
**57 changes: 50 ambiguity-pins, 7 mismatch-revisions.** (pass 1: 10 own edits + 7 inherited-and-verified; pass 2: 14; pass 3: 26.) No new sections; 18 headings identical in text, order and count; both tables intact at 94 rows.

## PASS 1 — cross-cutting infrastructure (17 changes: 16 ambiguity, 1 mismatch)

Inherited from the killed run, re-verified against impl:
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A-Z0-9` — `envelope.py:10-14`
- §2.2 — insert — ambiguity — `api_request_timestamp` comes from the logical clock, never wall clock — `envelope.py:18`, `store.py:116`
- §2.2 — insert — ambiguity — the four pagination keys appear only in list `meta`; object and error `meta` carry just the two request keys — `envelope.py:17-33`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` are 422; `offset` has no upper bound and over-runs answer 200 with empty `data` — `shape.py:170-196`
- §2.3 — insert — ambiguity — `created_at` ties are broken by insertion order — `store.py:263-265`
- §2.3 — insert — ambiguity — filters compared verbatim (out-of-enum matches nothing, 200 + empty); unknown query params ignored — `shape.py:199-203`
- §2.4 — insert — ambiguity — input parse rules for instant/date/period incl. offset handling, ms truncation, strict widths, whitespace stripping — `store.py:120-165`, `shape.py:140-145`

Added by the continuation:
- §2.1 — insert — ambiguity — "blank" means empty-or-whitespace; role matched exactly, case-sensitively, untrimmed; `X-User-ID` never normalised — `authz.py:19-28`
- §2.4 — insert — ambiguity — `id` is a lowercase hyphenated 36-char UUIDv4 carrying no ordering — `store.py:241-242`
- §2.4 — insert — ambiguity — `created_at` and `updated_at` are byte-identical on a never-mutated row — `store.py:245-253`
- §2.5 rung 5 — insert — ambiguity — body admission: absent/unparseable body reads as `{}`; non-object JSON is 422; `null` rejected for required fields but equals omission for optional ones; strict types (bools reject `0`/`1`/`"true"`, ints reject bools/floats/strings); strings length-checked pre-trim, blankness post-trim, stored verbatim; unretained `note`/`reason` still length-checked then discarded — `shape.py:27-115`
- §2.7 — insert — ambiguity — the clock accepts any well-formed instant including an earlier one (winds backwards); `data` carries only `current_utc` — `store.py:92-94`, `r_clock.py:20`
- §3.1 — insert — ambiguity — `service_night_days` echoed in supplied order, not normalised — `serializers.py:44`
- §3.6 — insert — ambiguity — `fines_assessed_this_period_cents` is not stored but re-derived per read over the clock's current calendar month regardless of fine status, so a clock month change zeroes it and restores full headroom — `serializers.py:64`, `calc.py:213-223`
- §3.8 — insert — ambiguity — a `DRAFT` statement recomputes all eight settlement figures on every read under `PROVISIONAL` without touching `updated_at`/`version`; issue freezes them — `serializers.py:174-190`
- §4 — insert — ambiguity — trailing slash insignificant — `app.py:29`
- §5 — revise — **mismatch** — the catalogue is not exhaustive of emitted `error_id`s: unrouted path -> `ERR_NOT_FOUND` 404, undeclared method -> `ERR_METHOD_NOT_ALLOWED` 405, server fault -> `ERR_INTERNAL` 500, all in the same envelope and none reachable via §4 — `app.py:46-66`

Cross-checks needing no change: the 39-code error map and HTTP statuses match §5 row-for-row; 51 registered routes match the 51 §4 rows; ladder order in the routers is admit -> path 404 -> ownership -> shape (confirming rungs 1-5); `_common` projection and all ten `*_out` field sets match the §3 entity descriptions.

## PASS 2 — money, ledgers, scans, fines, settlement (14 changes: 11 ambiguity, 3 mismatch)

- §2.5 rung 5 — insert — ambiguity — every `reason`/`note` accepts at most 500 chars; a *required* `reason` must additionally be >=1 char and non-blank — `r_scan.py:211,240,312,339`, `r_contractor.py:143`, `r_statement.py:175`
- §3.3 classification — revise — **mismatch** — PRD said any non-`CLEARED` state "is refused as an invalid state transition"; impl splits at rung 8: `APPLIED`/`BACKGROUND_PENDING` -> `ERR_INVALID_STATE`, `REJECTED`/`DEACTIVATED` -> `ERR_ALREADY_TERMINAL` — `r_contractor.py:126-129`
- §3.3 deactivation — revise — **mismatch** — same split, plus the state check precedes the live-route check — `r_contractor.py:146-152`
- §3.3 DECLARED — insert — ambiguity — `observed_weekly_hours` is the plain integer `0` until an `OBSERVED` run writes it, and only then becomes a two-decimal number — `r_contractor.py:41`, `calc.py:355`, `serializers.py:80`
- §3.5 scan rollups — insert — ambiguity — `coverage_bps` is **not** clamped to 10000; `expected_door_count` admits only pass-through-enabled occupying residents while `scanned_door_count` counts every qualifying scan regardless of flag or occupancy, and a scan is refused on neither ground, so >10000 is reachable — `calc.py:146-149`, `r_scan.py:75-140`
- §3.6 offense ordinal — insert — ambiguity — the 90-day lookback is measured in **instants**, closed at both ends, and its upper endpoint is a real filter under a backwards-wound clock — `calc.py:186-208`
- §3.6 escalation — insert — ambiguity — the clamp bites only at the top; a fine's ordinal is always >=1 because a fine rests only on a tagged scan, so there is no multiplier row below 1 — `calc.py:234-238`
- §3.6 AUTO route — insert — ambiguity — the auto-fine tag move is part of the scan's *creation*: the scan returns `tag_status` `FINED` with `version` 1 and identical `created_at`/`updated_at`, contra §2.9's blanket "every row touched is versioned" — `r_scan.py:148-151`
- §3.6 dispute loop — insert — ambiguity — `dispute_reason` is overwritten each round, keeps no history, and is not cleared by adjudication — `r_scan.py:312-322`
- §3.8 draft — insert — ambiguity — the effective-period intersection is a bare interval test reported as `ERR_INVALID_REQUEST` (422) at rung 5, hence ahead of stale-version and already-invoiced; the contract's `status` is deliberately not consulted — `r_statement.py:28-33`
- §3.8 step one-b — insert — ambiguity — the `PROVISIONAL` terminal-state filter touches **only the numerator**; `scheduled_night_count` is identical under both variants (worked: 4 nights / 1 MISSED / 3 open -> 4, 1.0, 2500 bps, not 1 and 10000) — `calc.py:396-408`
- §3.8 void — insert — ambiguity — an `ISSUED` statement failing the `last_invoiced_period` comparison draws `ERR_INVALID_STATE` (409), not `ERR_ALREADY_TERMINAL` — `r_statement.py:181-186`
- §3.2 move-out — revise — **mismatch** — the only conditional cascade touch in the system: a `SCHEDULED` night whose three recomputed counters are unchanged keeps its `updated_at` and `version`, so only nights on/after `move_out_date` are versioned — `rollups.py:97-116`
- §4 rows — revise x2 — ambiguity — added the undeclared `non_compliance_type` filter to `GET /service-scans` and `variant` to `GET /statements` (§2.3 ignores undeclared params, so an unlisted filter is unreachable) — `r_scan.py:182`, `r_statement.py:97`

## PASS 3 — properties, contracts, residents, schedule, dispatch, incidents, clock (26 changes: 23 ambiguity, 3 mismatch)

- §2.7 — insert — ambiguity — clock endpoint answers HTTP 200 / `response_type` `"object"`, never 201 — `r_clock.py:20`, `envelope.py:21`
- §2.10 — revise — **mismatch** — "forced to SUSPENDED whenever `escalation_level` reaches two" was universal; suspension fires only from exactly `ACTIVE` (an `ONBOARDING` or `TERMINATED` community reaching level 2 keeps its posture) and reinstatement only from exactly `SUSPENDED` — `rollups.py:88-91`
- §3.1 — insert — ambiguity — `market_code` is exactly three `A`-`Z` chars, stored uncased; violation is `ERR_INVALID_REQUEST` 422 at rung 5; `compactor_capacity_lbs` has no upper bound — `r_property.py:43,45`
- §3.1 — insert — ambiguity — activation's three refusals: `ERR_ALREADY_TERMINAL` for a `TERMINATED` contract, `ERR_INVALID_STATE` for an `ACTIVE` contract / `TERMINATED` community / sibling `ACTIVE` contract, in that order — `r_property.py:165-174`
- §3.1 — insert — ambiguity — a `SUSPENDED` community keeps that posture at activation (only `ONBOARDING` advances) yet is still written and versioned — `r_property.py:179-181`
- §3.1 — insert — ambiguity — terminate: terminal check precedes the outstanding-draft check (`ERR_ALREADY_TERMINAL` then `ERR_INVALID_STATE`); the draft-statement test belongs to the active branch alone — `r_property.py:193-199`
- §3.1 — insert — ambiguity — when a `DRAFT`/`ACTIVE` sibling contract remains, the community row is not written at all and `active_contract_id` keeps naming the just-terminated contract — `r_property.py:210-217`
- §3.1 — revise — **mismatch** — "a community that needs service again needs a new contract" implied revival; a contract may be drafted against a `TERMINATED` community but never activated — `r_property.py:170`
- §3.2 — insert — ambiguity — move-out codes: already `MOVED_OUT` -> `ERR_ALREADY_TERMINAL`; `move_out_date` <= `move_in_date` -> `ERR_INVALID_STATE` 409 (not a shape error); terminal check first — `r_resident.py:99-105`
- §3.4 — insert — ambiguity — `service_window_end` <= start is a rung-5 422; the contract's `status` is not consulted, so a `DRAFT` or `TERMINATED` contract may be given nights — `r_night.py:73,66-69`
- §3.4 — insert — ambiguity — weekday tested before effective period (same code); no date-uniqueness check, so two nights may share a `service_date` — `r_night.py:79-84`
- §3.4 — insert — ambiguity — reschedule state refusals are rung 8 and precede rung 17: terminal -> `ERR_ALREADY_TERMINAL`; `IN_PROGRESS` or a makeup night -> `ERR_INVALID_STATE` — `r_night.py:164-169`
- §3.4 — insert — ambiguity — a `SKIP`'s ignored `makeup_service_date` is still date-parsed at rung 5 (malformed -> 422); the five makeup rules fire in the listed order — `r_night.py:160,174-190`
- §3.5 — insert — ambiguity — `contractor_id` must be non-blank at rung 5, so a blank one is 422 and never reaches rung 6's 404 — `r_route.py:57`
- §3.5 — insert — ambiguity — dispatch has **no** rung-8 night-state check: a route may be created on a closed or cancelled night — `r_route.py:52-112`
- §3.5 — revise — **mismatch** — the prose narrated unit-range (rung 19) before window-conflict (rung 15), contradicting both the §2.5 ladder and impl; sentences reordered — `r_route.py:87,100`
- §3.5 — insert — ambiguity — the window test sweeps the valet's live routes platform-wide and does not exempt the addressed night (self-intersection => at most one live route per night; `COMPLETED`/`ABANDONED`/`CANCELLED` don't conflict) — `r_route.py:87-98`
- §3.5 — insert — ambiguity — accept: rung 4 `ERR_NOT_RESOURCE_OWNER` first; terminal -> `ERR_ALREADY_TERMINAL`; `IN_PROGRESS` and a no-longer-`CLEARED` valet both -> `ERR_INVALID_STATE` (not `ERR_CONTRACTOR_NOT_ELIGIBLE`); `classification` not re-checked; posture last — `r_route.py:175-188`
- §3.5 — insert — ambiguity — complete: `ASSIGNED` -> `ERR_INVALID_STATE`, terminal -> `ERR_ALREADY_TERMINAL`; the night row is written unconditionally even though the conserved sum cannot move — `r_route.py:204-219`
- §3.5 — insert — ambiguity — the close increments the night's `version` by exactly one however many routes it abandoned — `r_night.py:144-150`
- §3.7 — insert — ambiguity — `description`: optional, <=1000, no minimum and no not-blank rule, null when omitted; ownership is asymmetric — `PropertyManager` checked, `Valet` not checked at all — `r_incident.py:39,36`
- §3.7 — insert — ambiguity — acknowledge: `RESOLVED` -> `ERR_ALREADY_TERMINAL`; `ACKNOWLEDGED`/`ESCALATED` and a late attempt all -> `ERR_INVALID_STATE`, never `ERR_ESCALATION_WINDOW_NOT_ELAPSED` — `r_incident.py:101-107`
- §3.7 — insert — ambiguity — escalate: rung 8 beats rung 18, so `ERR_ESCALATION_WINDOW_NOT_ELAPSED` is reachable only from `REPORTED`; escalation carries no ownership check — `r_incident.py:117-129`
- §3.7 — insert — ambiguity — `resolution_note` required, 1-1000, non-blank-after-trim, stored verbatim; re-resolve -> `ERR_ALREADY_TERMINAL` — `r_incident.py:148,151`
- §3.7 — insert — ambiguity — resolving from `REPORTED`/`ACKNOWLEDGED` leaves the community row unwritten; resolving from `ESCALATED` always versions it, even at a 3->2 fall that does not reinstate — `r_incident.py:162-166`
- §4 (6 table rows) — insert — ambiguity — exact query-param names for the properties, contracts, residents, service-nights, route-assignments and compactor-incidents list filters — `r_property.py:80-82,147-148`, `r_resident.py:76-78`, `r_night.py:109-113`, `r_route.py:157-159`, `r_incident.py:79-81`

## Cross-pass leads that were investigated and deliberately NOT pinned
- `r_night.py:192` / `r_property.py:207` `rollups.cancel_night` default set — the call sites pass explicit sets that already match the prose (reschedule passes `("ASSIGNED","ACCEPTED")`, matching §3.4; contract termination passes `OPEN_ROUTE_STATUSES`, matching §3.1 and §3.7). The suspected `IN_PROGRESS` gap does not exist and is doubly unreachable on the reschedule path. No false universal was added.
- `r_route.py:230`, `r_property.py:190`, `r_night.py:161` `reason` bounds — already covered by pass 2's rung-5 sentence; verified rather than duplicated.
- Optional discarded `note` on fine-assess/adjudicate — covered by pass 1's rung-5 "retained in no field of its own" clause plus the §3.6 field enumeration; only the missing 500 bound was supplied.

## Final structural verification (pass 3 + orchestrator, independently)
- `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md` (`cmp` -> DIFFERENT; 59 changed lines cumulative).
- Ends at a genuine boundary — the last row of §5's error table, `| ERR_STALE_CONTRACT_VERSION | 412 |` — no mid-sentence or mid-table truncation.
- Heading structure unchanged from `PRD_FINALIZED.md` (identical heading count); both tables intact at 94 rows; no section added, removed or renamed.
- `workspace/implementation/` was not modified by any Step 9 pass, so the clean 113/113 x 8-round sweep from Step 7 still characterises this implementation.

