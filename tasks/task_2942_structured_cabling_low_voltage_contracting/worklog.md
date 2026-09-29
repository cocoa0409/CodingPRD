# Worklog — task_2942_structured_cabling_low_voltage_contracting

## Step 1: Create task directory — 2026-09-05T19:28:39.882810371Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2942_structured_cabling_low_voltage_contracting and its workspace/ subdirectory. Index 2942 was pre-assigned by the orchestrating caller; no index scan performed (concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-05T21:09:10.903108637Z

All three scaffold artifacts are complete, lint-clean, and self-consistent. `workspace/` and `worklog.md` are untouched (worklog not modified; only `.scratch/step2/` was created and deleted, leaving an empty `.scratch/`).

## Files

- `SCAFFOLD.yaml` — 2421 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1739 lines
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4282 lines

## SCAFFOLD.yaml (§1.0–§1.7)

`domain_name: structured-cabling-contracting`, `api_prefix: /cabling`. **12 entities** (CablingProject, TelecomRoom, Rack, RackUnitAssignment, PathwaySegment, CableType, Link, LinkPathwayRoute, TestResult, WarrantyRegistration, MacTicket, TradeCoordination), **63 endpoints**, **59 errors**, **15 calculations** (4 dual-variant), **35 validations** (priorities 10–205), **11 state-machine entries** (10 with transitions + a stateless Rack ledger entry; 5 cyclic; Link carries two independent dimensions install_state/record_state), **3 concurrency_rules** (route-create-stale-segment, rack-assignment-stale-rack, warranty-submit-stale-project), **7 roles** (ProjectManager, DesignEngineer, Installer, TestTechnician, Certifier, ManufacturerAgent, Client). Profile: primary `compliance_audit`, secondary `graph_constraint`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation]`, topology `graph`, shape `cyclic`, role model `segregation_of_duties`, consistency `immediate`, level `expert_plus`. The `scenario:` key holds only the domain text — the "harder than expert level" directive is not present anywhere.

## §1.8 — 9 rule_ids / 22 instances

`dual_variant_calc` (2), `combinatorial_formula` (3), `non_linear_state_machine` (2), `transitive_cascade` (2), `priority_pair_validation_conflict` (3), `boundary_precision_check` (3), `cross_entity_state_dependency` (3), `resource_temporal_overlap` (2), `compensating_invariant` (2).

## §1.9 — 9 sections in guide order / 97 instances (67 recipes + 30 `excluded_because` stubs)

entities 15, state_machines 12+8 stubs, calculations 12+9 stubs, validations 12+9 stubs, endpoints 5, errors 4, rbac 3, cross_cutting_complexity_layers 3+4 stubs, consistency_model 1.

## Coverage audit

- **Errors: 59/59 triggerable** — no ERR_* id in the catalog is unreferenced by the two design files.
- **Endpoints: 63/63 exercised.** The audit initially found 11 collection reads with no call anywhere (`GET /cabling/projects`, `telecom-rooms` (+ detail), `racks`, `rack-unit-assignments`, `pathway-segments`, `link-routes`, `test-results`, `warranty-registrations`, `mac-tickets`, `trade-coordinations`). I closed the gap by adding two `listing` instances to the entities section: `the_design_side_collections_answer_their_reverse_reachability_reads` (project/room/rack/assignment/segment ledger fields, filtered by each declared FK) and `the_downstream_collections_are_reachable_after_the_link_is_certified` (full route→pull→terminate→label→record→test→certify chain plus occupancy and one MAC ticket, then all five downstream lists).
- Name uniqueness holds across the union of both design files; no stub carries a `test_recipe`; every `excluded_because.difficulty_instance` resolves as `rule_id / instance_name` into §1.8; zero unbound `${var}` placeholders; no forbidden concurrency vocabulary in any of the three files.

```
Coverage
  §1.5 endpoints declared:    63
  §1.1 entities declared:     12
  §1.8 instances scanned:     22
  §1.9 instances scanned:     67
  Calls scanned (§1.8+§1.9):  1042

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Orchestrator verification: all three YAMLs present with the reported line counts; `grep -i "harder than expert"` across all three returns no match, so the difficulty directive did not leak into the scaffold.

## Step 3: Copy shared files — 2026-09-05T21:09:15.767222376Z

Copied ./INSTRUCTION.md to tasks/task_2942_structured_cabling_low_voltage_contracting/workspace/INSTRUCTION.md (bash only, no subagent).

## Step 4: Generate PRD — 2026-09-05T21:22:55.286717065Z

PRD generated and verified. Both withheld design files were never opened; `worklog.md` and `INSTRUCTION.md` are untouched; scratch subdir removed (shared `.scratch/` parent preserved).

**Output:** `workspace/PRD.md` — 473 lines, 14,110 words, 101,714 bytes. Built with 13 chunked `cat >>` appends, no single-Write truncation risk.

**Section list**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications: 2.1 Crew Identity and RBAC · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 Record Identity, Timestamps and Revision Counters · 2.5 The Logical Site Clock · 2.6 Units, Money and Rounding · 2.7 Optimistic Concurrency on Shared Drawings · 2.8 The Order in Which a Request Is Screened · 2.9 Cascades, Hop Ordering and Conserved Ledgers · 2.10 Resolving Paths and Reading the Collection Graph
- §3 Business Logic (9 subsections, lifecycle-ordered): 3.1 Project/Telecom Rooms/Grounding · 3.2 Rack Elevations and Room Power Ledger · 3.3 Pathway Graph, Reparent, Condemn (Cascade B) · 3.4 Cable Catalogue, Link Design, Two Length Variants · 3.5 Routing: Plenum, Separation, Continuity, Fill · 3.6 Trade Coordination, Pull, Terminate · 3.7 Records, Testing, Certification (Cascade A), Roll-ups · 3.8 Occupancy, MAC Ticketing, MAC Budget (Cascade C) · 3.9 Warranty Registration, Decision, Revocation
- §4 Endpoint Definitions (4 columns, 63 rows) · §5 Error Code Catalogue (2 columns, 59 rows)

**Coverage (mechanically checked against SCAFFOLD.yaml)**
- 12 entities / 129 field names incl. the two computed-read shapes: 129 required, 0 missing
- 80 request-body identifiers: 0 missing · 33 query params: 0 missing · 12 path params: 0 missing. Re-run strictly on §1–§3 only (excluding §4/§5 tables), all 144 identifiers appear as standalone backticked tokens.
- 63 endpoints all in §4; 59 error IDs all mentioned in §2/§3 prose *and* tabulated in §5
- 15 calculations all expressed as precise prose with every constant embedded (fill tiers 53/31/40/50 with the non-monotonic warning, bend derate 2 pts and 25% floor, 1.2 cord derate, 90.00/100.00/0.9 limits, 0.40+0.19/m budget, 0.0 and 0.5 margin boundaries, 4750x2 labour with the pinned per-link rounding and the 26410-vs-26409 worked figure, 9600/hr with the 48000->55200 tier trap, 30-min buffer with crew capacity 2, AWG 6 / 5000 milliohms, 15/25/3/5/10 warranty years, both TIA-606 regexes, 8-hop graph ceiling)
- 11 state machines / 42 transitions: every `from -> to` pair named with its preconditions, error IDs and side effects, including all 5 cycles, Link's two independent dimensions, and the 3 system-driven cascades hop by hop
- 35 validations: full ordered screening ladder in §2.8 with every `applies_to` set enumerated and "compliance outranks capacity" stated
- 6 OCC-guarded write endpoints (3 `concurrency_rules` parents): each names its endpoint, `expected_*_version`, mismatch rejection, exact error ID and 412
- 7 roles, all named with exact spelling and all `identity: opaque` translated into §2.1 prose

**Hard contracts** — Contract 1 (field coverage): PASS, 0 missing across all four categories. Contract 2 (rule coverage): PASS — 35/35 validations with priority ordering, 6/6 OCC rejections, 42/42 transitions, 15/15 calculations, 59/59 error conditions matchable, all endpoint side effects and `applies_to` sets, all field-level defaults/initials, sibling branches rendered at equal density (SUBMITTED->SCHEDULED vs SUBMITTED->REJECTED; PASS vs FAIL test branches; the three grounding grades; PERMANENT_LINK vs CHANNEL; ESTIMATE vs FINAL; STRICT vs PROVISIONAL). Contract 3 (§3 path purity): PASS — 983 backtick tokens scanned in §3, 0 starting with `/`, 0 bare HTTP methods, 0 method+path combinations. No fuzzy/approximating words and no operator syntax anywhere in the document.

Three scaffold internal inconsistencies were resolved in favour of the §1.2 state machines plus the §1.4 priority ladder, so the prose has a single reading: a failed pull onto a condemned segment reports `ERR_SEGMENT_CONDEMNED` (state family screened before `ERR_LINK_NOT_ROUTED`); a grounding verification rejects outright only on `bonding_conductor_awg` above 6, with a missing busbar or high resistance recorded as `NON_COMPLIANT`; and a `REJECT` warranty decision sets the project's `warranty_status` to `REJECTED`.

**Tail confirmation** — the document ends at a complete section boundary: the last line is the final row of the §5 error table, `| ERR_MAC_BUDGET_EXCEEDED | 402 |`. No audit footer or contract-report block was written into PRD.md or any sibling file.

Orchestrator verification of the known truncation failure mode: `wc` reports 473 lines / 14,110 words / 101,714 bytes; `grep '^## '` finds all five top-level sections (§1 line 3, §2 line 11, §3 line 162, §4 line 339, §5 line 409); the §5 table holds 59 `ERR_*` rows and the file's last line is a complete table row. Not truncated — no regeneration needed. `grep -i "harder than expert\|scaffold"` over PRD.md returns no match, so neither the difficulty directive nor any scaffold reference leaked into the contract.

## Step 6: Generate implementation — 2026-09-05T21:53:06.75467833Z

Implementation complete. All 63 endpoints are live and the smoke run is green.

## Modules (`workspace/implementation/`)

Foundation — 1,003 lines: `app.py` 84, `store.py` 142, `errors.py` 137, `envelope.py` 91, `auth.py` 64, `validation.py` 189, `calc.py` 236 (plus `requirements.txt`, `start.sh` 10)
Domain services — 448 lines: `rollups.py` 311, `lookup.py` 61, `serial.py` 49, `identifiers.py` 27
Routes — 1,696 lines: `links.py` 246, `mac.py` 265, `trade.py` 172, `racks.py` 171, `warranty.py` 164, `pathways.py` 157, `link_routes.py` 147, `rooms.py` 140, `projects.py` 110, `tests.py` 102, `cables.py` 66, `clock.py` 16, `__init__.py` 0
Total 3,147 lines of Python.

## Coverage vs PRD

- **Endpoints: 63/63.** Programmatic diff of Flask's `url_map` against the PRD §4 table (method + path, `{x}` normalised) returns empty `missing` and empty `extra`.
- **Errors: 59/59.** `errors.ERROR_HTTP` holds exactly the catalog's 59 IDs, every HTTP status matches the §5 table (verified by diff), and every code is reachable — 48 raised inline via `ApiError`, the 11 `*_NOT_FOUND` codes through `lookup.py`'s per-kind resolvers.
- **35 validation priorities** are encoded as call order, not a table: `auth.authenticate`/`require` (1-2) -> `validation.body` shape gate (3, unknown fields included) -> `lookup.*` left-to-right existence (4) -> per-endpoint state guard -> OCC -> life-safety/code -> capacity/money. Each route function reads top-to-bottom in ladder order.
- **11 state dimensions**: 10 machines guarded in their own route modules plus Link's second `record_state` dimension (label/record checked before `install_state`, per §3.5); Rack stays a stateless ledger recomputed in `rollups.recompute_rack_ledger`.
- **15 calculations** all live in `calc.py` with pinned `Decimal` constants and ROUND_HALF_UP (`rcents`/`r2`/`r4` in `store.py`); no float arithmetic on money.
- **OCC**: exactly 6 endpoints declare a version field (`expected_segment_version` x3, `expected_rack_version` x2, `expected_project_version`), each required; anywhere else it is an unknown field -> `ERR_INVALID_REQUEST`.
- **Cascades** A/B/C each bump every touched record's own `version` + `updated_at`: A and B in `rollups.py`, C hop-by-hop in `routes/mac.py:complete_ticket`.

## Smoke test (ports 38471/38472/38473, own PIDs only, each killed by PID)

Full lifecycle across every resource family: clock set -> project -> telecom room -> grounding verification -> rack -> RU assignment (OCC) -> pathway segment -> cable type -> link -> link-route (OCC) -> trade coordination confirm/release -> pull -> terminate -> label -> record -> test result (PASS) -> certify (Cascade A) -> certification report + summary -> warranty registration -> occupancy -> MAC ticket -> schedule -> start -> complete (Cascade C, CHANGE rename) -> relabel/record/retest/recertify -> registration READY -> submit (OCC) -> REGISTER decision; then all 12 list reads and 8 error paths (401, 403, 404 x2, 409, 400 x3). Envelope asserted on **every** response: `meta.api_request_id` matches `req_` + 20 uppercase alnum, `api_request_timestamp` is 3-fractional-digit UTC read from the logical clock, `response_type` in object/array/error, `data` present, and list `meta` carries `limit`/`offset`/`total_count`/`has_more`. Result: `SMOKE OK`.

Two PRD §3.8 worked examples reproduced exactly: 6.0 estimated hours -> `estimated_billed_cents` 62928 and 4.0 actual hours -> `final_billed_cents` 44160 (both on the expedited ticket; the tier keys on the subtotal, so 4.0 h takes 0% discount). `consumed_mac_cents` tracked 0 -> 62928 -> 44160 across schedule and completion, and Cascade C dropped `completeness_pct_strict` to 0.00 with `warranty_status` ELIGIBLE -> NOT_ELIGIBLE.

Three kill/relaunch cycles on one port each booted within a second and reported `total_count` 0 — the store is empty at boot (verified directly: all 12 dicts empty, clock at the 2026-08-01T00:00:00Z origin), nothing is seeded, and `start.sh` guards its pip install, reads `$PORT`, binds 0.0.0.0 and `exec`s in the foreground.

Two notes for the record. First, `POST /_clock/set_current_utc` accepts calls with or without auth headers (PRD §4 lists all seven roles; requiring headers would break a headerless caller, the lenient direction cannot break a header-supplying one). Second, `DRAFT -> READY` fires only at the instant `warranty_status` becomes ELIGIBLE (Cascade A hop 4, per §3.9), so a registration opened on an already-ELIGIBLE project stays DRAFT until the next certification — confirmed deliberate in the smoke run rather than patched. The scratch dir `.scratch/step6/` was removed; the sibling `.scratch/step5/` is untouched, and I neither read nor wrote `test_helpers/` or `test_suite/`.

## Step 5: Generate unit tests — 2026-09-05T22:21:52.575411178Z

All work is complete and verified. Final state:

## Deliverables

**`test_helpers/`** — 2365 lines
| file | lines |
|---|---|
| `__init__.py` | 1 |
| `types.py` | 424 |
| `constants.py` | 107 |
| `api_errors.py` | 141 (all 59 `ERR_*` + status map registered at import) |
| `api_client.py` | 351 (one method per §4 endpoint, `canonical_instant` sub-second normaliser) |
| `test_users.py` | 95 (7 role identities + 6 bad-auth header variants, blank cases send `""`) |
| `factories.py` | 363 |
| `assertions.py` | 226 (`assert_cents`, `assert_decimal_equals`, `assert_instant_equals`, `validate_unpaginated`, ledger identities) |
| `fixtures.py` | 657 (all setup via `get_success_data`, OCC versions re-read before every guarded write) |

**`test_suite/`** — 8448 lines, **127 tests**
| file | lines | tests |
|---|---|---|
| `conftest.py` | 71 | — |
| `test_01_length_variants_and_billing_variants.py` | 319 | 4 |
| `test_02_fill_tiers_cost_rounding_and_discounts.py` | 379 | 6 |
| `test_03_link_dimensions_and_ticket_cycle.py` | 255 | 4 |
| `test_04_certification_and_condemnation_cascades.py` | 231 | 4 |
| `test_05_screening_order_conflicts.py` | 329 | 6 |
| `test_06_boundaries.py` | 265 | 7 |
| `test_07_cross_entity_gates.py` | 323 | 6 |
| `test_08_interval_geometry.py` | 263 | 5 |
| `test_09_conserved_ledgers.py` | 204 | 4 |
| `test_10_entities_and_reads.py` | 1014 | 15 |
| `test_11_state_machines.py` | 741 | 12 |
| `test_12_calculations.py` | 1450 | 20 |
| `test_13_validations.py` | 1302 | 18 |
| `test_14_endpoints_errors_rbac_and_concurrency.py` | 1302 | 16 |

## Coverage
- **Queue A (§1.8 difficulty): 22 / 22 instances**, 46 tests, >=2 tests per instance, one file per rule_id.
- **Queue B (§1.9 corner): 67 / 67 non-stub instances**, 81 tests — entities 15, state_machines 12, calculations 12->20 tests, validations 12->18 tests, endpoints 5, errors 4, rbac 3, cross_cutting_complexity_layers 3, consistency_model 1.
- The 30 `excluded_because:` stubs got **no tests**, and all 30 `difficulty_instance:` cross-references resolve to a real instance in `SCAFFOLD_DIFFICULTY_DESIGN.yaml`.

## Instances SKIPPED
**None.** Every non-stub instance in both queues passed the PRD-first two-condition filter.

## Verification run
- `pytest --collect-only` collects exactly **127** tests; every module imports cleanly; every file passes `ast.parse`.
- Programmatic tag audit: exactly one `Design:` line per test, always the final docstring line, every tag resolves to a live (non-stub) instance, no dangling and no dual tags, no live instance left uncovered.
- Fixed one real defect found by collection: `test_01` had imported the factory `test_result_payload` unqualified, so pytest was collecting it as a 128th (broken) test; it is now aliased to `build_test_result`.

## Design-index values overridden by the PRD (relevant to Step 7 triage)
1. `ERR_PATHWAY_FILL_EXCEEDED` asserted at **422** (PRD §5) where recipes say 409.
2. `allowed_fill_pct` is the allowance for **one more cable than currently carried** (PRD §3.3), so no post-admission `53` literal is asserted anywhere; the empty-segment value is used instead, and `test_12` re-derives 45->25, 53->31->40->31.
3. `one_link_occupies_two_pathway_segments...` builds PS-B as PS-A's child, because §3.5 chain continuity would otherwise make the recipe's two unrelated roots yield `ERR_ROUTE_SEQUENCE_GAP`.
4. `graded_length_m` asserted on the per-link certification report, not on `TestResult` (§3.7).
5. `rack_code` literal `"RK-A"` corrected to `"A"` (§3.2 single-uppercase-letter pattern); recipe `insertion_loss_db: 12.00` on a 40 m permanent link corrected because the §3.7 budget is 8.00 dB and the link would grade `TESTED_FAIL`; a recipe that moved the logical clock backwards was re-expressed monotonically (PRD states no backwards semantics).
6. Two non-derivable sub-assertions omitted (a pre-verification `bonding_conductor_awg` value; exact fractional-second width, which the suite's own `canonical_instant` normalises).

Nothing was written under `workspace/`, `workspace/implementation/` was never read, `worklog.md` was untouched, and `.scratch/` is empty of my step's subdirectories.

Orchestrator verification: `test_helpers/` and `test_suite/` are both at the TASK ROOT (not under `workspace/`); `find workspace -maxdepth 2 -type d -name "test_*"` returns nothing, so no stray copies were written into the workspace. Steps 5 and 6 were launched in a single assistant message, so the implementation generator started before `test_suite/` existed on disk and could not have read it.

## Step 7: Run tests and iterate — 2026-09-05T22:43:38.154566069Z

Loop complete — clean 8-round sweep at 127/127.

## Summary

**Iterations run:** 2 (sweep -> diagnose -> fix -> sweep). Final sweep: all 8 parallel rounds `127 passed / 0 failed / 127 total`.

**Iteration 1 baseline:** 124/127 in every one of the 8 rounds — 3 deterministic failures, zero flakiness, no load-induced timeouts or connection errors.

**Tests deleted:** none. All three failures were test-artifact defects under STEP 2 (assertion mis-translates PRD) or STEP 1c (partial coverage — uncovered assertion removed, covered assertion kept). No test lost its PRD-covered assertion, and no `skip`/`xfail` was added.

**Fixes applied to `test_suite/`:**

1. `test_suite/test_06_boundaries.py` — `test_a_link_measuring_exactly_ninety_metres_is_pulled`: removed `assert pulled["installer_user_id"] == INSTALLER_ID` (STEP 1c partial coverage). PRD §2.1 states verbatim that the server records "`installer_user_id` on a link at termination", and §3.6's pull paragraph enumerates its four preconditions and says only "Success increments the link's `version` by 1" — pull never writes that field. The boundary assertion under test (`install_state == PULLED` at exactly 90.00 m) was kept intact; the docstring was reworded to match.

2. `test_suite/test_07_cross_entity_gates.py` — `test_confirming_the_ceiling_milestone_admits_the_identical_pull`: same one-line removal, same PRD basis. The trade-gate assertions (`ERR_TRADE_NOT_COORDINATED` before confirmation, `PULLED` after, coordination left in `CONFIRMED`) were all kept.

3. `test_suite/test_14_endpoints_errors_rbac_and_concurrency.py` — `test_a_write_response_already_carries_every_derived_field_it_moved`: corrected the expected `fill_ratio` literal from `0.0856` to `0.0855` (STEP 2, wrong literal). PRD §3.5: "`fill_ratio` is the used area divided by `usable_area_sq_mm`, rounded half up to **four** decimal places." With the 7.9 mm CAT6A's `cross_section_area_sq_mm` of 49.02 in a 573.0 sq mm conduit, 49.02 / 573.0 = 0.08554973... -> **0.0855**. Confirmed against a live server and against exact `Decimal` arithmetic, and `test_12_calculations.py` lines 346/435/449 already assert `0.0855` for the identical segment/cable pair — so the failing literal was a lone typo, not an implementation defect.

**Fixes applied to `test_helpers/`:** none needed — no shared-fixture bug of the usual shapes (money-as-string, date-only-vs-instant, timestamp width, blank auth header, envelope double-unwrap, paginated/unpaginated mismatch) was present.

**Fixes applied to `implementation/`:** **none.** All 3,147 lines are byte-identical to what Step 6 produced (mtimes unchanged). The fill-ratio failure looked like an arithmetic bug but the implementation's `calc.fill_ratio` / `rollups.recompute_segment_fill` were already exactly PRD-faithful — rounding the used area to 2 dp before dividing, then quantizing to 4 dp with `ROUND_HALF_UP` on `Decimal`.

**One observation, not acted on (no test exercises it):** `POST /_clock/set_current_utc` in `routes/clock.py` enforces the auth headers, whereas PRD §2.5 says it "is the only endpoint that does not require the `X-User-ID` and `X-User-Role` headers". Every test calls it with headers, so it neither fails nor is covered; I left it alone rather than change implementation behaviour outside the failing set.

Orchestrator verification: all 8 `workspace/implementation/results.$i.json` files independently re-read and each reports `passed == total == 127`. The sweep ran under `setsid` via the pre-written `workspace/sweep.sh` with its `SWEEP_DONE` sentinel, so neither the reaping failure mode nor the early-return-relaunch failure mode applied. Step 7 did not touch `worklog.md`.

Orchestrator note on the clock-auth observation: Step 6's own summary claimed the opposite (that `POST /_clock/set_current_utc` accepts calls with or without headers), so the two subagents disagree about what the code does. This is left for Step 9, which walks `implementation/` exhaustively and aligns the PRD to whatever the code actually does — the correct owner of an untested PRD/impl divergence. Step 8's scope is bounded to the `<step_7_diff>` items, so it must not touch this.

## Step 8: Finalize PRD — 2026-09-05T22:51:45.780739538Z

## Verdict: zero PRD edits warranted — PRD_FINALIZED.md is byte-identical to PRD.md

`workspace/PRD_FINALIZED.md` created via `cp`. **473 lines vs 473 lines, 0% delta, identical md5 on both.** Step 7 applied zero implementation fixes, and all three of its test-side fixes trace to test-artifact defects at sites where PRD.md already uniquely determines the implementation's behavior. Per the task's explicit note, no edits were manufactured.

### Change list
None.

### Per-item pre-edit search log

**Items 1 & 2 — `installer_user_id` removed from the two pull assertions (`test_06_boundaries.py`, `test_07_cross_entity_gates.py`)**
- (a) Subject: which operations write, clear, or read `installer_user_id`.
- (b) Enumerated every impl path (grep across `implementation/`, 4 hits, all read): `routes/links.py:73` (design stamps it `None`), `routes/links.py:168` (terminate sets `g.user_id`), `routes/links.py:222` (certification segregation-of-duties compare), `rollups.py:296` (Cascade B hop 3 clears it alongside `certifier_user_id`), plus `routes/mac.py:256,259` (Cascade C hop 2 clears `record_state`/`certifier_user_id` and deliberately **not** `installer_user_id`). Read `pull_link` in full (`routes/links.py:150-152`): it sets `install_state = "PULLED"` and `touch(link)` only — it never touches the field.
- PRD already pins all six paths verbatim: §2.1 line 19 ("`installer_user_id` on a link at termination"), §3.6 line 223 (created link has it null), §3.6 line 255 ("On success `installer_user_id` is set to the acting `X-User-ID`, overwritten on every re-termination"), §3.7 line 279 (segregation compare), §3.3 line 204 ("both `installer_user_id` and `certifier_user_id` are cleared"), §3.8 hop 2 (clears `certifier_user_id` only). §3.6's pull paragraph closes with "Success increments the link's `version` by 1" — a complete effect list. A fresh implementer cannot conclude pull stamps the installer.
- (c) No wording adjustment — no edit made. Any sentence added to the pull paragraph saying "pull does not set `installer_user_id`" would be redundant with §2.1/§3.6 and risks contradicting the terminate/cascade paths.

**Item 3 — `fill_ratio` literal corrected `0.0856` -> `0.0855` in `test_14_endpoints_errors_rbac_and_concurrency.py:1287`**
- (a) Subject: how `fill_ratio` (and the used area feeding it) is computed and rounded, at every site that writes it.
- (b) Enumerated: `calc.py:140-145` (`fill_ratio` = `r4(used / usable)`, with a usable==0 guard), `calc.py:136` (`allowed_fill_area_sq_mm`), `rollups.py:68-80` (`recompute_segment_fill` — the single writer: `fill_area_used_sq_mm = r2(sum of OCCUPYING consumed areas)`, then `allowed_fill_pct`, then `fill_ratio` from that already-2dp value), and its callers on the route-create / withdraw / condemn-hop-2 paths. Also checked `calc.py` cross-section derivation feeding the 49.02 figure.
- PRD already pins every step: §2.6 line 92 (round half up on exact decimals; `fill_ratio` is the one four-decimal quantity, `allowed_fill_pct` whole-number; "where a rule computes a value from an already-rounded value ... the rounded intermediate is the input"), §3.5 line 239 (used area rounded half up to 2 dp), §3.5 line 241 ("`fill_ratio` is the used area divided by `usable_area_sq_mm`, rounded half up to **four** decimal places"), §3.4 line 213 (`cross_section_area_sq_mm` from pi = 3.141592653589793, 2 dp -> 49.02), §3.5 line 243 and §3.3 line 203 (recompute on withdrawal and on suspension). 49.02 / 573.0 = 0.08554973... -> 0.0855, which three pre-existing assertions in `test_12_calculations.py` (lines 346/435/449) already encoded for the identical segment/cable pair. The failing literal was a lone typo.
- (c) No wording adjustment — no edit made.

No files other than PRD_FINALIZED.md were written; PRD.md, `implementation/`, `test_suite/`, `test_helpers/` and `worklog.md` were not modified, and SCAFFOLD*.yaml / worklog.md were not read.

Orchestrator adjudication: a byte-identical PRD_FINALIZED.md is the legitimate outcome here, because Step 7 changed zero lines of `implementation/` — there is no implementation choice made after PRD.md was written for Step 8 to pin. Step 8 was still run rather than skipped, since the skip condition requires all four fix counts to be zero and Step 7 made 3 `test_suite/` fixes. The residual PRD-vs-impl gaps (including the `/_clock/set_current_utc` auth-header question the two earlier subagents disagreed about) are Step 9's scope, not Step 8's.

## Step 9: Complete PRD — 2026-09-05T23:13:45.968301894Z

Run as THREE sequential passes partitioned by implementation module over one shared `workspace/PRD_COMPLETED.md` (pass 1 did the `cp`; passes 2 and 3 were explicitly forbidden from re-copying so they could not clobber prior edits). Final: **473 lines / 117,397 chars vs the 473 lines / 101,714 chars it started from — +15,683 chars across 47 changed lines, 52 edits total (44 ambiguity-pins, 8 mismatch-revisions).** No new sections, no added or deleted lines — every edit is an in-paragraph insert or revision.

### Pass 1 — foundation layer (app.py, store.py, errors.py, envelope.py, auth.py, validation.py, lookup.py, serial.py, identifiers.py)
13 edits (12 ambiguity-pins, 1 mismatch-revision), +4,236 chars.
- §2.1 — revise — ambiguity — whitespace-only header value counts as empty; `X-User-Role` matched as an exact, untrimmed, case-sensitive string — `auth.py:36-41`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 chars from uppercase letters and digits — `store.py:62-64`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` (empty, fractional, `+`-prefixed, non-numeric) is also `ERR_INVALID_REQUEST`, surrounding whitespace tolerated; `offset` has no upper bound and an out-of-range offset yields an empty page with true `total_count` and `has_more` false — `envelope.py:49-72`, `envelope.py:32`
- §2.3 — insert — ambiguity — list ordering ties on identical `created_at` (the common case, since the clock only moves explicitly) are broken by ascending acceptance order — `store.py:136-138`, `store.py:125`
- §2.4 — revise — ambiguity — `created_at`/`updated_at` render with a `Z` suffix and sub-millisecond precision is **truncated**, not rounded, to three digits — `store.py:67-72`
- §2.4 — revise — ambiguity — `updated_at` equals `created_at` at creation — `store.py:120-126`
- §2.5 — revise — **mismatch/ambiguity** — clock control is genuinely unauthenticated (headers absent/empty/any value all succeed, supplied values ignored); payload is the single required `to_iso8601`, no other field allowed; any well-formed instant accepted including one earlier than the current reading (clock may wind backwards); reply is HTTP 200 with `data.current_utc` in the three-digit form — `routes/clock.py:12-16`, `app.py:36-40`
- §2.6 — insert — ambiguity — rounded decimals are carried as JSON numbers, so rounding pins the value not its textual width (`88.00` may render `88.0`); money always a plain integer — `store.py:104-114`
- §2.8 step 3 — insert — ambiguity — unknown-field check runs before required/type checks; explicit JSON `null` on a declared field is rejected rather than read as absent; numbers must be JSON numbers not strings; booleans never satisfy numeric fields; integral floats (`5.0`) coerce to integers — `validation.py:156-174`, `validation.py:61-103`
- §2.8 step 3 — insert — ambiguity — accepted datetime grammar (`T`/`t`, 1-9 fractional digits, optional `Z`/`z`/`+00:00`/`-00:00`, bare instant read as UTC, non-zero offset malformed); date fields accept only `YYYY-MM-DD` — `validation.py:14-17`, `validation.py:43-58`, `validation.py:121-128`
- §2.8 step 3 — insert — ambiguity — absent/empty body reads as `{}`; non-JSON or non-object body is malformed; no-payload endpoints accept an absent or empty body and reject any field — `validation.py:142-153`, `validation.py:177-181`
- §2.10 — insert — ambiguity — trailing slash addresses the same endpoint — `app.py:28`
- §2.10 — insert — ambiguity — enum-valued filters reject undeclared members with `ERR_INVALID_REQUEST`; identifier-valued filters are exact string matches never resolved for existence (unknown id -> empty page, not 404); undeclared query params ignored — `envelope.py:84-91`, `routes/projects.py:69-81`
- §4 clock row — revise — **mismatch** — the `Authorized Role(s)` cell listed all seven roles, implying headers are required; changed to "None — this endpoint is unauthenticated, so any role and no role alike are admitted" — `routes/clock.py:12`
- §5 — insert — ambiguity — the id->status table has two out-of-band cases: unrouted path -> `ERR_INVALID_REQUEST` with **HTTP 404**, disallowed method -> `ERR_INVALID_REQUEST` with **HTTP 405**, both in the normal error envelope — `app.py:58-66`

**Resolution of the disputed clock-auth question** (Step 6 and Step 7 disagreed): the code requires **no** headers. `routes/clock.py:12-13` registers the view with no `@require(...)` decorator, and `app.py`'s only `before_request` (`_acquire_lock`) just takes the store lock — there is no global authentication hook. `auth.authenticate()` is reached exclusively through `require()` (`auth.py:45-64`), which the clock blueprint never applies. PRD §2.5's sentence was therefore **correct** and was strengthened; the §4 table row was the actual defect and was fixed. Step 7's observation was mistaken.

### Pass 2 — calculation / derived-state layer (calc.py, rollups.py)
11 edits (8 ambiguity-pins, 3 mismatch-revisions), +3,309 chars. Pass 1's edits verified intact by grep before and after.
- §2.6 — revise — **mismatch** — removed `worst margin` from the two-decimal list; `worst_margin_db` is a selection between two client-submitted measurements, stored/reported at submitted precision, never re-rounded — `calc.py:172-175`, `routes/tests.py:61`
- §3.7 (grading) — revise — **mismatch** — `worst_margin_db` copied verbatim at submitted precision, and it is that verbatim value the 0.0 / 0.5 thresholds compare against — `calc.py:172-188`
- §3.7 (test roll-up) — revise — **mismatch** — `latest_test_outcome` is stamped **forward** from the result being filed, not recomputed from greatest `recorded_at` (so a backwards clock wind still leaves it naming the newly filed result); separately pinned that the latest test result **record** is greatest `recorded_at` with ties to the most recently created — `routes/tests.py:73` vs `rollups.py:53-62`
- §3.7 (as-built cost) — revise — **mismatch** — `material_cost_cents` is restamped on **every** link the roll-up walks, priced or not; only priced links contribute labour + material to the sum — `rollups.py:178-187`
- §3.4 — insert — ambiguity — only the finished cross-sectional area is rounded; half the outer diameter is carried at full precision and never rounded before squaring — `calc.py:72-75`
- §3.5 (fill tiers) — insert — ambiguity — the bend derate applies to `CABLE_TRAY` too (50 is count-invariant, not bend-invariant; five bends -> 44 percent) — `calc.py:111-125`
- §3.5 (post-admission recompute) — insert — ambiguity — recomputed `allowed_fill_pct` is again the allowance for one more cable than the segment now carries (so it can move either way given the non-monotone table), and `fill_ratio`'s numerator is the stored two-place `fill_area_used_sq_mm`, not the unrounded sum — `rollups.py:68-80`, `calc.py:128-145`
- §3.3 (reparent) — insert — ambiguity — only descendants whose `pathway_depth` actually changed get a `version`/`updated_at` bump — `rollups.py:140-158`
- §3.3 (Cascade B hop 3) — insert — ambiguity — every link that lost an occupying routing is versioned, including one already `DESIGNED`, because `routed_segment_count` was recomputed — `rollups.py:291-298`
- §3.3 (Cascade B hop 4) — insert — ambiguity — the warranty consequence moves only `ELIGIBLE` and `REGISTERED`; `SUBMITTED`, `REJECTED` and `REVOKED` projects and their registrations are left untouched — `rollups.py:232-249`
- §3.7 (Cascade A hops 3-4) — insert — ambiguity — the warranty status change adds no second project `version` bump (exactly 1 across the whole cascade), and hop 4 fires only on the actual `NOT_ELIGIBLE -> ELIGIBLE` edge, so a `DRAFT` registration opened while already `ELIGIBLE` is not promoted — `rollups.py:239-243, 258-263`. (This confirms and documents the behaviour Step 6 flagged as deliberate.)

### Pass 3 — route layer (all 12 route modules, all 63 endpoints)
28 edits over 27 lines (24 ambiguity-pins, 4 mismatch-revisions), +8,138 chars. Passes 1 and 2 verified intact by grep.
- §3.1 — revise — ambiguity — `room_code` uniqueness is project-scoped, collision is `ERR_INVALID_REQUEST` after `project_id` resolves — rooms.py:37-41
- §3.1 — insert — ambiguity — a new room's `bonding_conductor_awg`/`ground_resistance_milliohms` start null — rooms.py:51-52
- §3.1 — insert — ambiguity — all three verification fields required; neither numeric measurement is bounded at the shape stage — rooms.py:89-93
- §3.1 — insert — ambiguity — a `COMPLIANT` grade on an already-`GROUNDED` room is a self-loop — rooms.py:109-111
- §3.1 — insert — ambiguity — energize's state guard rejects only `ENERGIZED`; a `ROUGH_IN` room falls to `ERR_ROOM_NOT_GROUNDED` — rooms.py:124-128
- §3.2 — revise — ambiguity — `rack_code` uniqueness is room-scoped, collision is `ERR_INVALID_REQUEST` — racks.py:35-39
- §3.3 — revise — **mismatch** — `segment_code` must be >=1 char (undeclared before), is project-scoped, and its uniqueness test runs **last**, after cross-project and depth — pathways.py:28-57
- §3.3 — insert — ambiguity — segment-create `allowed_fill_pct` initialisation sequence — pathways.py:74-79
- §3.3 — insert — ambiguity — reparent's `upstream_segment_id` is required-but-nullable (null => root at depth 0); self-parent is a cycle; the 8-hop ceiling is tested on the moved segment alone, descendants may end past 8 — pathways.py:127-152
- §3.4 — insert — ambiguity — the catalogue enforces no uniqueness; duplicate cable types are distinct rows — cables.py:22-44
- §3.4 — insert — ambiguity — link design runs the full roll-up and applies the warranty consequence (`ELIGIBLE->NOT_ELIGIBLE`, `READY->DRAFT`) but never revokes — links.py:83, rollups.py:258-263
- §3.5 — insert — ambiguity — the link's state is screened before the segment's — link_routes.py:33-38
- §3.5 — insert — ambiguity — the admission uses the percentage computed afresh for the resulting count, identical to the stored `allowed_fill_pct` — link_routes.py:73-77
- §3.5 — revise — ambiguity — `consumed_area_sq_mm` is snapshotted only after the fill test admits, carrying the 2dp catalogue figure — link_routes.py:78-87
- §3.5 — insert — ambiguity — withdraw screens route state before link state, both before the OCC check — link_routes.py:130-138
- §3.6 — revise — ambiguity — the predecessor-chain ceiling counts coordinations (predecessor inclusive), not hops — trade.py:52-60
- §3.7 — insert — ambiguity — label's `record_state` guard precedes its `install_state` guard — links.py:181-186
- §3.7 — insert — ambiguity — `length_measured_m` carries no sign/range constraint — tests.py:32
- §3.7 — insert — ambiguity — the exact field set a test result serializes; graded length is not one of them — tests.py:52-68, serial.py:9
- §3.7 — insert — ambiguity — the strict-`PASS` gate reads the `latest_test_outcome` field while the SoD gate reads the latest *record* — links.py:221-231
- §3.8 — revise — ambiguity — `occupancy_status` is a single-member enum (`PRE_OCCUPANCY` => `ERR_INVALID_REQUEST`); the CEILING gate is milestone-agnostic and passes vacuously with no rows — projects.py:87-96
- §3.8 — revise — ambiguity — a non-null `new_identifier` on `MOVE`/`ADD` is `ERR_INVALID_REQUEST` pre-existence; not screened at raise; the link may be in any state — mac.py:66-71
- §3.8 — revise — **mismatch** — completion resolves `new_identifier`: payload non-null wins and is written back; omitted-or-null falls back to the value stored at raise, so a `CHANGE` ticket renames even with a silent completion payload; on `MOVE`/`ADD` it is stored and renames nothing — mac.py:233-239
- §3.8 — revise — **mismatch** — hop 1 stated the project bump twice; the project's `version` moves exactly 1 across all of Cascade C (hops 3-4 do not bump) — mac.py:248-264
- §3.8 — revise — **mismatch** — "completed without a `new_identifier`" -> "whose *resolved* `new_identifier` is still null" — mac.py:235-236
- §3.9 — insert — ambiguity — a project may hold any number of registrations, opened in any project state — warranty.py:27-45
- §3.9 — revise — ambiguity — both decision companion fields default to null, an empty string counts as missing, and the other branch's field is ignored rather than stored — warranty.py:110-120
- §3.9 — insert — ambiguity — reopen recomputes the project status only; the reopened `DRAFT` is not re-promoted to `READY` — warranty.py:162, rollups.py:252-255

**Pass 3 coverage:** all **63** endpoints examined (5 projects, 5 rooms, 7 racks, 5 pathways, 3 cables, 9 links, 4 link-routes, 3 test-results, 6 warranty, 8 MAC, 7 trade, 1 clock). Every §4 Authorized-Role cell was re-derived from the `@require(...)` decorators: all 62 non-clock rows already matched the implementation exactly, so §4 needed no further edit. §2.7's six-endpoint OCC inventory verified exact (route create, route withdraw, segment reparent, placement, placement release, warranty submit; all required, all guarding the record §2.7 names). One deliberate non-edit: free-text fields (`equipment_label`, `released_reason`, `condemned_reason`, `drawing_sheet_ref`, `tester_model`, `block_reason`) carry no length floor in impl and none in PRD, and the PRD's convention is that string constraints are stated where they exist — so silence already reads as unconstrained; only `segment_code`, where impl does enforce a floor, needed pinning.

### Orchestrator final verification
- `PRD_COMPLETED.md` md5 `4208dff9...` differs from `PRD_FINALIZED.md`/`PRD.md` md5 `c0500c5b...` — the scan demonstrably ran (a byte-identical Step 9 output would have been a bug).
- 47 changed lines vs the source; 473 lines preserved; all 5 top-level sections present; the §5 table still holds all 59 `ERR_*` rows; the file ends at its real final boundary.
- `find implementation -name '*.py' -newer PRD_FINALIZED.md` is empty — Step 9 edited only the PRD and did not touch the implementation, so the passing sweep remains valid.
- All 8 `results.$i.json` re-read one last time: each reports `127 / 127`.

Pipeline complete through Step 9.

