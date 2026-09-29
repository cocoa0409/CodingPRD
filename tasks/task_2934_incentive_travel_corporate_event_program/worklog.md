# Worklog — task_2934_incentive_travel_corporate_event_program

## Step 1: Create task directory — 2026-09-05T18:32:30.636015796Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2934_incentive_travel_corporate_event_program and /home/ubuntu/github/CodingPRD/tasks/task_2934_incentive_travel_corporate_event_program/workspace (pre-assigned path, no index scan). Also created per-step scratch dirs under .scratch/.

## Step 2: Generate scaffold — 2026-09-05T20:03:52.950538078Z

Subagent summary (verbatim):

All three scaffold artifacts are complete, lint-clean and parse as YAML.

## Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2934_incentive_travel_corporate_event_program/`)

| file | lines | contents |
|---|---|---|
| `SCAFFOLD.yaml` | 2867 | §1.0–§1.7 only (verified: no `scaffold_difficulty_design`, no `scaffold_corner_design`) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 4914 | single key `scaffold_difficulty_design` (§1.8) |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 11689 | single key `scaffold_corner_design` (§1.9) |

Verifier: `scaffold_lint.py` reports `§1.5 endpoints declared: 53 / §1.1 entities: 10 / §1.8 instances: 20 / §1.9 instances: 51 / calls scanned: 1560` -> **`VERDICT: clean lint`**.

## Domain model
`domain_name: incentive-travel-program`, `api_prefix: "/"`, difficulty `expert_plus`, consistency `immediate`, role_model `segregation_of_duties`, complexity layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers]`.

**10 entities** — Program, AwardTier (`common_fields: false`), Qualifier, Destination, SupplierContract, DepositMilestone, Registration, OnsiteActivity, ActivitySignup, TaxAwardReport.
**12 state machines, 11 calculations, 33 validations, 53 endpoints, 53 errors, 7 roles** (ProgramDirector, SourcingManager, ContractApprover, SalesOpsAnalyst, TravelDesk, TaxComplianceOfficer, Participant — the last with `entity_backed:Qualifier` identity). Two §1.2.1 OCC rules: `expected_program_version` on `POST /registrations`, `expected_activity_version` on `POST /activity-signups`.

## §1.8 — 9 rules / 20 instances
`dual_variant_calc` 3 · `combinatorial_formula` 3 · `non_linear_state_machine` 2 · `transitive_cascade` 2 · `priority_pair_validation_conflict` 2 · `boundary_precision_check` 2 · `cross_entity_state_dependency` 2 · `resource_temporal_overlap` 2 · `compensating_invariant` 2

## §1.9 — 9 sections / 71 instances (51 with recipes, 20 stubs)
entities 10 · state_machines 14 · calculations 15 · validations 10 · endpoints 6 · errors 4 · rbac 5 · cross_cutting_complexity_layers 5 · consistency_model 2

Every stub omits `test_recipe` and names a real §1.8 instance in `excluded_because`; names are unique across the union of both design files; zero unbound `${...}` placeholders in any `setup_api_calls`; zero occurrences of the forbidden concurrency vocabulary.

## Two SCAFFOLD.yaml edits made while closing §1.9
1. **`ERR_NO_EXECUTED_HOTEL_CONTRACT` was untriggerable.** A program can only enter CONTRACTED by executing a HOTEL contract, so "no executed hotel contract" is structurally unreachable once registration opens — the id would have produced an impossible downstream test. §1.4 priority 12 and the §1.2 confirm precondition already read "**exactly one** EXECUTED HOTEL contract", so I widened the §1.6 condition to match ("either none at all, or two or more, which leaves the room-night basis ambiguous") and wrote the reachable probe: a second HOTEL contract executed while the program is already CONTRACTED. That instance doubles as the only place the HOTEL cascade is shown *not* to run (it is gated on `Program.status == SOURCING`).
2. `OnsiteActivity.capacity`'s description said "Maximum simultaneously BOOKED signups" — reworded to "may be BOOKED at once" to keep the banned concurrency vocabulary out of the file.

## One thing for the orchestrator
`scenario:` retains the leading `Generate task harder than expert level!` line, because the instruction was to use the description verbatim. Per the usual convention that directive should be stripped from `SCAFFOLD.yaml` after Step 2 so it cannot reach PRD.md. `worklog.md` was not touched; scratch lives in `.scratch/step2/` (generator scripts `gen_common.py`, `gen_corner.py`, `gen_corner_p2..p8.py` — re-running `gen_corner_p8.py` regenerates the whole corner file).

### Orchestrator note
Acted on the generator's hand-off: stripped the line `Generate task harder than expert level!` (plus its trailing blank line) from the `scenario:` block of SCAFFOLD.yaml so the difficulty directive cannot reach PRD.md. Verified with grep (no remaining match in any of the three YAMLs) and re-validated SCAFFOLD.yaml parses (top keys: scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles). SCAFFOLD.yaml is now 2865 lines.

## Step 3: Copy shared files — 2026-09-05T20:03:52.965711486Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md -> workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T20:18:52.493856167Z

Subagent summary (verbatim):

PRD.md is complete and verified.

## Deliverable

`workspace/PRD.md` — **495 lines**, built with 1 `Write` + 11 heredoc appends (no single message near the output cap).

**Tail confirmation:** the file's last heading is `## 5. Error Code Catalogue` (line 437) and line 495 is that table's final row, `| ERR_ADVANCE_PREREQUISITES_UNMET | 422 |`. It ends on a genuine section boundary — complete table row, no mid-sentence/mid-list truncation, no audit footer.

## Ordered headings

- `# Incentive Travel Program API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` (2.1 Actors/Headers/RBAC; 2.2 API Response Structure — byte-identical verbatim block; 2.3 Pagination/Filtering/List Ordering; 2.4 Resource Identity/Timestamps/Version Semantics; 2.5 The Logical Clock; 2.6 Money/Basis Points/Rounding Discipline; 2.7 Stale-Version Guards on Seat and Slot Creation; 2.8 Validation Order and Error Precedence; 2.9 Segregation of Duties; 2.10 Cascade Discipline and Conserved Quantities; 2.11 Path Resolution and Cross-Program Scope)
- `## 3. Business Logic & Workflows` (3.1 Program Design/Budget/Award Tier Ladder; 3.2 Qualifier Review; 3.3 Destination Sourcing/Site Inspection/Shortlisting; 3.4 Supplier Negotiation/Execution/Five-Level Cascade; 3.5 Deposit Schedules/Cancellation Exposure/Force-Majeure Relief; 3.6 Qualifier Communication/Enrolment/Guest Policy; 3.7 Seat Confirmation/Room-Night Capacity/Budget Headroom/Air Travel; 3.8 On-Site Agenda: Activities/Seats/Waitlists/Conflicts; 3.9 Reversals/Reconciliation/Measurement/Taxable Award Reporting)
- `## 4. Endpoint Definitions` (4-column table, 53 rows)
- `## 5. Error Code Catalogue` (2-column table, 53 rows)

## Hard Contract reports

**Contract 1 — Field-Name Coverage: PASS.** 150 required identifiers extracted programmatically from the scaffold (130 entity field names + endpoint input/query/path-parameter/response identifiers). Pass 1 (word-split tokenizer): 150/150 present, MISSING (0). Pass 2 (exact standalone backticked token): 0 missing.

**Contract 2 — Rule Coverage: PASS.** All 33 validations rendered in §2.8 with priority, error ID, HTTP status and full applies_to endpoint set, each also narrated in its §3 workflow; both concurrency rules (expected_program_version/ERR_STALE_PROGRAM_VERSION, expected_activity_version/ERR_STALE_ACTIVITY_VERSION, both 412) pinned in §2.7; every transition of all 12 state machines expressed in prose with its trigger and guards (Program 11, Destination status 4 + inspection 3, SupplierContract 8, DepositMilestone 4, Qualifier award 8 + tax 4, Registration attendance 7 + air 7, OnsiteActivity 2, ActivitySignup 3, TaxAwardReport 2); all 11 calculations reconstructible from prose alone (operand order, ROUND_HALF_UP, basis-point scaling, per-component evaluation order); all 53 endpoints' side effects, version bumps and cascade targets stated. Sibling symmetry checked on the cancel branches, the propose/counter pair, the three gross-up variants, the two exposure variants and the two shortlist gates. 0 missing.

**Contract 3 — §3 Path Purity: PASS.** 1100 backticked tokens scanned inside §3: 0 `/`-prefixed paths, 0 bare HTTP-method tokens, 0 method+path pairs. All routing lives in §4.

Additionally verified: all 53 error IDs are named in the §1–§4 narrative, not only in the §5 table; §2 is 30,265 chars and §3 is 62,013 chars.

Constraints honoured: neither SCAFFOLD_DIFFICULTY_DESIGN.yaml nor SCAFFOLD_CORNER_DESIGN.yaml was opened, grepped or referenced; no sibling task directory was read; worklog.md untouched; the only other files written are required_fields.txt and sections_4_5.md under .scratch/step4/, and the .scratch parent was not deleted.

### Orchestrator verification (truncation guard)
Independently confirmed: 495 lines; top-level headings are exactly 1..5 in order; §4 table = 55 pipe lines (53 endpoints + header + separator); §5 table = 55 pipe lines (53 errors + header + separator); tail is a complete table row. Grep for "harder than expert", "scaffold", "test_recipe" in PRD.md returns nothing — the difficulty directive and scaffold vocabulary did not leak. No regeneration needed.

## Step 6: Generate implementation — 2026-09-05T20:48:59.31308850Z

Subagent summary (verbatim):

Implementation is complete and verified.

## Location
`workspace/implementation/`

## Modules (3017 lines total, all `py_compile` clean)

| file | lines | role |
|---|---|---|
| `errors.py` | 79 | `ApiError`, catalogue of all 53 error ids -> HTTP status, `fail()` |
| `store.py` | 112 | in-memory `Store` (10 dict tables), logical clock, id/version/timestamp stamping, ISO-8601 helpers |
| `envelope.py` | 102 | `meta`/`response_type`/`data` envelope, `req_` + 20-char id, 3-digit-ms timestamps, pagination |
| `auth.py` | 65 | 7 roles, ladder priorities 1-3, participant ownership (priority 6) |
| `schema.py` | 145 | priority-7 body validation in declared field order, null-as-absent, raw FK pass for priority 5 |
| `calc.py` | 422 | all 11 calculations (committed cost, budget rollup, room-night ledger, attrition, exposure, gross-up, air ladder, measurement, promotion, conflict) |
| `serialize.py` | 145 | per-entity field projections in SCAFFOLD order + lazy aggregate refresh |
| `cascades.py` | 300 | 5-level contract execution, 6-step program cancellation, window closure, reconciliation, registration reversal, activity close |
| `gates.py` | 61 | 404 lookups, program-status gates, list filters |
| `routes/*.py` (11 blueprints) | 1426 | programs 8, tiers 3, qualifiers 4, destinations 5, contracts 7, milestones 4, registrations 8, activities 4, signups 4, tax reports 5, clock 1 |
| `app.py` | 60 | app factory, error handlers, `0.0.0.0:$PORT` |
| `start.sh` + `requirements.txt` | — | foreground `exec python3 app.py`, `PORT` default 10000 |

**Endpoint count from the live URL map: 53** (exactly the PRD's declared set).

## Smoke-test results (all passed)

Boot/isolation: three back-to-back `PORT=18935 bash start.sh` boots each answered HTTP in <1s, each returned an **empty** `/programs` list after the previous boot had created a program — no persistence, no seed data, clock resets to `2026-08-01T00:00:00.000Z`. No errors in any boot log.

PRD worked examples reproduced exactly:
- `qualifier_committed_cost` = **921765** (per-component rounding; naive single rounding gives 921766)
- exposure projection: `attrition_floor_room_nights` **48**, `deposit_forfeiture_basis_cents` **1732500**
- air change-fee ladder from base fare 214000: **12500 / 31250 / 59375 / 85600 / 85600** (cap clamps 101563)
- `stay_end_at` 2026-11-09 + 5 nights = **2026-11-14T00:00:00.000Z**
- 45-min transfer buffer: 44-min gap -> `ERR_ACTIVITY_TIME_CONFLICT`, 45-min gap -> 201
- measurement: `sales_lift_pct` **38.33**, `satisfaction_index` **8.5** (scores 9/8)
- `FULL_GROSS_UP` pinned anti-circularity case: award 443198 -> `combined_rate_bp` 3265, reported **658052** (not 678191); tier boundaries 500000->3465 and 1500000->3665 confirmed

Lifecycle/cascade paths exercised: waitlist admission and promotion (`promoted_at` from the logical clock), duplicate-signup and closed-activity rejections, registration CONFIRMED->CANCELLED full reversal (room nights 10->5, available 15, qualifier REGISTERED->NOTIFIED, booked signup cancelled and waitlisted one promoted), program cancellation cascade (registrations/qualifiers/signups/activity cancelled, unpaid-vs-paid milestone -> REFUNDED, committed budget -> 0, second cancel -> 409), reconciliation, tax draft->file->void with `ERR_TAX_VOID_SELF_REVIEW`, `reported_award_total_cents` rising 1127952 then falling to 563976 on void, `ERR_TAX_REPORTING_INCOMPLETE` gating CLOSED until refiled.

Both conserved identities held after every reversal (`committed + headroom == total`; `blocked == confirmed + available`).

## Notes
- Two apparent anomalies were traced to my own smoke scripts, not the server: a second `/respond` on an already-ACCEPTED seat (correctly 409) leaving `waiver_on_file` false, and `ERR_AIR_STATE_INVALID` outranking `ERR_DEVIATION_LIMIT_EXCEEDED` (priority 11 before 25 — correct per §2.8).
- Server killed by exact port/PID (`ss -ltnp` -> pid 1250423 on 18934, plus the 18935 boots); no broad `pkill` was ever issued. Ports 18934/18935 are now free.
- `test_suite/` and `test_helpers/` were never read, listed, or grepped; `worklog.md` untouched; scratch confined to `.scratch/step6/`; `__pycache__` removed.

## Step 5: Generate unit tests — 2026-09-05T21:22:03.216804055Z

Subagent summary (verbatim):

Step 5 is complete.

## Output location (verified at TASK ROOT, nothing under `workspace/`)

**`test_helpers/` — 2,185 lines, 9 modules**
`__init__.py` 45 · `types.py` 429 · `api_client.py` 232 (53 endpoint methods + `canonical_instant`) · `api_errors.py` 130 (all 55 ids + registered status map) · `constants.py` 103 · `test_users.py` 103 · `factories.py` 179 · `assertions.py` 198 · `fixtures.py` 766 (49 Tier-0 primitives + 22 composite setups through Tier 5)

**`test_suite/` — 12,957 lines, 13 files, 344 tests**
`conftest.py` 62 · `test_01_exposure_and_gross_up_variants` 399/8 · `test_02_composite_cost_formulas` 543/10 · `test_03_negotiation_and_cascade_workflows` 692/12 · `test_04_validation_priority_and_boundaries` 577/13 · `test_05_cross_entity_gates_and_temporal_overlap` 596/12 · `test_06_conserved_invariants` 600/10 · `test_07_entity_contracts` 1662/43 · `test_08_state_machine_corners` 1264/43 · `test_09_calculation_corners` 1032/33 · `test_10_validation_corners` 1338/39 · `test_11_endpoint_and_error_corners` 2271/76 · `test_12_rbac_occ_and_consistency_corners` 1921/45

## Per-queue instance accounting

| Queue | Instances | Translated | Skipped |
|---|---|---|---|
| A — Difficulty (9 rules) | 20 | **20** (min 2 tests each, actual 2-5) | 0 |
| B — Corner (9 sections) | 71 (20 `excluded_because:` stubs) | **51 / 51 non-stub** (1-15 tests each) | 0 |

**No instance was skipped.** All 20 corner stubs emitted zero tests and every stub's `difficulty_instance:` pointer was confirmed to resolve to a real `name:` in SCAFFOLD_DIFFICULTY_DESIGN.yaml — no broken pointers.

Instead of dropping whole instances, agents dropped individual **non-derivable assertions** and reported them. The recurring ones: program `cancellation_exposure_cents` after a confirm (§3.5 lists the re-derive triggers and confirmation is not among them — asserted through the live `exposure-projection` read instead); `created_at == updated_at == <clock>` (§2.5 makes the audit pair clock-independent); `air_status -> VOIDED` in the registration-window sweep (stated only for request-driven cancels); `committed_budget_cents -> 0` on program cancellation (not a listed rollup trigger); exact `version` counts where the PRD does not fix how many mutations one request is; the error envelope's `details` key (§2.2 says otherwise). Three recipes were also **self-contradicting against §2.8 priority 10** (they set up a program status where the lifecycle gate would answer before the gate under test); those were rebuilt in a status that makes the pinned error genuinely reachable.

## Verification

- `py_compile` clean on all 22 generated `.py` files.
- `pytest --collect-only`: **344 tests collected, 0 errors** — every import, `ApiErrorId` member and `api_client` method resolves.
- AST audit: 344/344 tests have **exactly one** `Design:` line and it is the last docstring line; all 344 tags resolve to a real instance in the correct yaml/queue; zero untagged, zero dual-tagged, zero stub-tagged.
- Zero `skip` / `skipif` / `xfail` / `pytest.skip()` / `TODO` / `NotImplementedError` anywhere.
- Fixture hygiene: no money/bp sent as a string (the 4 string-typed literals are deliberate `ERR_INVALID_REQUEST` schema probes); no whitespace-only header (blank tests use `""`); no `validate_success(...)["data"]` double-unwrap; clock-field comparisons go through `assert_instant_equals`/`canonical_instant`.
- `test_helpers/` and `test_suite/` are at the task root; `workspace/` contains no test directories; `workspace/implementation/` was never read; `worklog.md` untouched by me or any subagent (its 20:48 edit is the orchestrator's own Step 6 entry); scratch confined to `.scratch/step5/` with the parent and all sibling subdirs intact.

### Orchestrator verification
Confirmed `test_helpers/` and `test_suite/` exist at the task root and that neither exists under `workspace/` (no move needed). Independent `pytest --collect-only -q` re-run confirms the collected test count with 0 collection errors.

## Step 7: Run tests and iterate — 2026-09-05T22:03:18.199809420Z

Subagent summary (verbatim):

All 8 rounds pass 344/344 on fresh results (22:01), and `worklog.md` was untouched.

## Summary

**Iterations run:** 3 sweeps (8 parallel rounds each).

**Tests deleted:** none. No test asserted a scaffold-only rule; all failures traced to one real implementation defect and two test-artifact bugs.

**Fixes applied to `test_helpers/`:** none — the fixture layer was clean.

**Fixes applied to `test_suite/`:**
- `test_suite/test_08_state_machine_corners.py` — `_build_three_seat_cohort()`: reordered so the GUEST seat is created *before* the WINNER seat is confirmed. PRD §3.6 gates enrolment on the qualifier's `award_status` being exactly `NOTIFIED`, and §3.7 moves that qualifier `NOTIFIED -> REGISTERED` on winner-seat confirmation — so the old order made the PRD-faithful server correctly reject the guest enrolment with `ERR_QUALIFIER_STATE_INVALID`, failing 3 tests as a shared setup error. Fixed with `enrol_and_confirm(..., confirm=False)` + an explicit `confirm_registration` after the guest is accepted.
- `test_suite/test_07_entity_contracts.py` — `test_a_rejected_body_persists_nothing_and_advances_no_version`: STEP 1c split. Its trailing `assert_budget_conserved(after)` ran on a `DESIGN` program that has never run a budget rollup, a window in which PRD §3.1 explicitly states the §2.10 identity is *not* yet in force ("The budget identity described in §2.10 takes hold the first time the budget rollup runs"). Replaced that one uncovered assertion with the covered purity check — `committed_budget_cents`, `budget_headroom_cents` and `budget_posture` unchanged across the rejected requests — which preserves the test's actual subject and is strictly PRD-traceable. All other 44 `assert_budget_conserved` call sites were left untouched and pass.

**Fixes applied to `implementation/`:**
- `workspace/implementation/serialize.py` — `refresh_program()`: the eager budget rollup on every serialization was overwriting the charter's seeded `budget_headroom_cents` of 0 with `budget_total_cents`, so even the `POST /programs` 201 body reported a non-zero headroom. Now gated on the rollup having actually run for that program.
- `workspace/implementation/calc.py` — `program_budget_rollup()`: sets the `budget_rollup_armed` marker, so the §2.10 identity arms exactly at the moment PRD §3.1 says it does (first real rollup event: adjudication, confirmation, cancellation, re-ticketing, contract execution). Verified by smoke test: fresh program reports headroom 0; after the first qualifier review it reports `total - committed`. The marker is internal and never serialized (`_project` filters to the declared field list).

**Key finding:** §2.10's "always equals" and §3.1's seeding list are reconciled by §3.1's own carve-out sentence, which is the controlling one — that single reading fixes 3 failures (the two seeding tests plus the one conservation assertion) coherently, where the opposite reading cannot satisfy both.

**Final sweep evidence** (`workspace/implementation/results.$i.json`, all written 22:01): rounds 1-8 each 344 / 344.

No flakiness appeared in any round; every failure seen was deterministic across all 8, and no load-induced timeout/connection failure occurred in the final sweep.

### Orchestrator verification
Independently re-read all eight results.$i.json (all timestamped 22:01): each reports passed=344, total=344, failed=0, errors=0. `pytest --collect-only` still collects 344 tests, so nothing was silently dropped. Grep confirms zero pytest.mark.skip / xfail / pytest.skip() in test_suite/, and zero sqlite3 / file-write / /tmp persistence in implementation/. Step 7 made implementation fixes, so Step 8 is NOT skipped.

## Step 8: Finalize PRD — 2026-09-05T22:12:14.635157010Z

Subagent summary (verbatim):

Done. Verified: 495 lines in both files, 3 lines revised (0.61% delta), file still ends on the final row of the §5 error table.

## Result
`PRD_FINALIZED.md` — 495 lines vs `PRD.md` 495 lines; **3 of 495 lines revised = 0.61% delta**. No insertions of new sections/lines, no deletions.

## Changes
- **§1 (intro, line 9)** — revise — the universal "the committed budget plus the remaining headroom always equals the approved total" now reads "once a program's budget rollup has run for the first time ..."; the room-night half left universal — `serialize.py:97-98`, `calc.py:106`
- **§2.10 (line 170)** — revise — the conserved-quantity sentence now scopes the budget identity to "from the first time a program's budget rollup actually runs (the arming moment fixed by §3.1, triggers per §3.7)", and states that before that first rollup the identity is not in force and the charter's seeded zeros are what the program reports — `serialize.py:89-101`, `calc.py:101-117`
- **§3.1 (line 184)** — revise — appended one sentence to the existing carve-out: until the first rollup, `committed_budget_cents`/`budget_headroom_cents`/`budget_posture` stay at seeded 0/0/`OK` however large `budget_total_cents` is, the creation response itself reports headroom 0 rather than the full budget, and reading a program neither arms the identity nor re-derives those three fields — `routes/programs.py:56-60,72`, `serialize.py:97-100`

## Pre-edit search log
**Edits 1, 2 and 3 share one subject** (searched once, exhaustively, before the first commit):

(a) **Subject** — when the budget identity `committed_budget_cents + budget_headroom_cents == budget_total_cents` is in force, and what the three budget fields report before that.

(b) **Impl paths enumerated** (grepped `budget_rollup_armed|program_budget_rollup|budget_headroom_cents|budget_posture|committed_budget_cents|refresh_program` across all `.py`, then read each site):
- `calc.py:101-126` — sole writer of the three fields, and the sole site that sets `budget_rollup_armed`
- `serialize.py:89-101` — the gate; `program_counts` and `reported_award_total` still run unconditionally on every read
- `serialize.py:12-20` — `PROGRAM_FIELDS` excludes `budget_rollup_armed`, so the marker is never serialized
- `routes/programs.py:52-72` (charter seeds 0/0/`OK`, then serializes), `:195-208` (measurement read -> `refresh_program` only, does not arm)
- `routes/qualifiers.py:96-117` — rollup runs **only** on the `QUALIFIED` branch; the `DISQUALIFIED` branch returns early and never arms
- `routes/registrations.py:207-225` — pre-headroom-gate rollup, post-confirm rollup, post-`NOTIFIED->REGISTERED` rollup; `:309` — any air action, but only when attendance is `CONFIRMED`/`TRAVELLED`
- `cascades.py:68-84` — execution cascade level 4 rollup only for `HOTEL` + program in `SOURCING`; `:87` level 5 reads current `budget_posture`; `:148` reconcile and `:222` program-cancel call `refresh_program` only (never arm); `:270` seat cancel rollup only on the `CONFIRMED` branch
- `store.py:91-108` — `stamp_new`/`touch`/`ordered` touch no aggregates
- room-night identity writers (`calc.py:155-165`, `cascades.py:42`, `routes/contracts.py:78-80`) — `available = blocked - confirmed` by construction and recomputed on every contract serialization, so that half of §2.10 holds unconditionally

(c) **Wording adjustments made** — (i) restricted the qualification to the *budget* identity only, leaving the room-night identity universal, after confirming the ledger holds from contract creation onward; (ii) expressed arming as a cross-reference to §3.1/§3.7 rather than re-listing triggers, because impl arms only in the `QUALIFIED`-only review branch, the `CONFIRMED`-only cancel branch and hotel/`SOURCING`-only cascade level 4 — restrictions already stated in §3.2/§3.9/§3.4, so a re-listing in §2.10 would have over-claimed; (iii) scoped the §3.1 "reading does not re-derive" clause to *those three fields*, because `qualified_count`, `travelled_count` and `reported_award_total_cents` **are** re-derived on every read; (iv) chose "the creation response itself" over naming `POST /programs` 201 to stay consistent with the §4 table's framing; (v) left §2.10's "recomputed, never patched" paragraph (line 168) untouched after verifying no reachable state exists where a rollup input is non-zero while the rollup is unarmed (both `QUALIFIED` and `CONFIRMED` are only reachable through a rollup call), so that paragraph is not contradicted.

**Items deliberately not patched:** the `test_08` cohort-ordering fix (PRD §3.6 already pins enrolment on `award_status` exactly `NOTIFIED`, confirmed at `routes/registrations.py:62`, and §3.7 already pins `NOTIFIED->REGISTERED` on winner-seat confirmation) and the `test_07` assertion split (same budget-arming subject, covered by the three edits above).

## Step 9: Complete PRD — 2026-09-05T22:39:08.189359787Z

Run as three sequential module-partitioned passes over one shared PRD_COMPLETED.md (pass 1 did the cp from PRD_FINALIZED.md; passes 2 and 3 edited in place and were verified not to clobber earlier edits).

### Pass 1 — app.py, envelope.py, errors.py, store.py, auth.py, schema.py, gates.py, serialize.py, routes/{clock,programs,tiers,qualifiers}.py (verbatim)

**Setup:** `cp workspace/PRD_FINALIZED.md workspace/PRD_COMPLETED.md` was done first; all subsequent work was surgical `Edit` calls on PRD_COMPLETED.md.

**Line/char counts:** PRD_FINALIZED.md 495 lines / 108,629 chars -> PRD_COMPLETED.md 495 lines / 111,544 chars (+2,915 chars, 0 lines). `diff` shows exactly 13 modified lines, all in-paragraph inserts/revisions — no new sections, no new paragraphs. Last line is still the final §5 error-table row.

**Counts:** 10 ambiguity-pins, 3 mismatch-revisions.

**Changes:**
- §2.1 — insert — ambiguity — whitespace-only header counts as empty; auth is checked before the body is parsed; role name matched exactly with no trimming/case-folding — `auth.py:39-41`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-letter/digit characters — `envelope.py:20-21`
- §2.3 (ordering) — insert — ambiguity — rows sharing a `created_at` millisecond keep insertion order, making the list sort total/stable — `store.py:106-108`
- §2.3 (filters) — insert — ambiguity — filters compared as exact strings (booleans as `true`/`false`), undeclared query params ignored, non-matching filter value yields an empty page not an error — `gates.py:52-61`
- §2.4 — insert — ambiguity — every declared field always present, unset values serialized as explicit JSON null; client-supplied instants canonicalised on write to three-fractional-digit UTC (offset converted, sub-millisecond truncated not rounded, bare calendar date accepted as midnight UTC) — `serialize.py:84-85`, `store.py:39-49`, `schema.py:127-130`
- §2.5 — revise — mismatch — logical-clock start literal corrected to `2026-08-01T00:00:00.000Z`, and `current_utc` is the response's only field — `store.py:12`, `routes/clock.py:17-18`
- §2.8 item 7 — insert — ambiguity — absent/empty/`null` body read as `{}`; unparseable or non-object body is itself `ERR_INVALID_REQUEST`; a field sent as JSON null is treated as absent (required -> missing, optional -> default) — `schema.py:15-28,104-113`
- §2.8 item 10 — revise — mismatch — lifecycle-gate exception list corrected: `POST /award-tiers` and `POST /programs/{program_id}/gross-up-policy` consult no program status either (phrased additively so passes 2/3 can extend) — `routes/tiers.py:18-25`, `routes/programs.py:140-149`
- §2.11 — insert — ambiguity — undeclared path -> `ERR_PROGRAM_NOT_FOUND` 404, undeclared method -> `ERR_INVALID_REQUEST` 400, neither depending on auth headers — `app.py:33-49`
- §3.1 (tier ladder) — insert — ambiguity — appending a rung is ungated on program lifecycle status, `CANCELLED`/`CLOSED` included — `routes/tiers.py:18-38`
- §3.1 (gross-up policy) — insert — ambiguity — the lock is the only gate; a first submission is accepted in any program status — `routes/programs.py:140-150`
- §3.1 (advance) — insert — ambiguity — a `to_status` outside the eight status names fails schema first as `ERR_INVALID_REQUEST`, ahead of the 409 edge check — `routes/programs.py:93-97`
- §3.6 (notification) — insert — ambiguity — the bulk run does not mutate the program row, so the program's `version` is unchanged — `routes/programs.py:153-178`

### Pass 2 — calc.py, cascades.py, routes/{destinations,contracts,milestones}.py (verbatim)

**Verification:** Pass 1's 13 edits all intact. Diff vs PRD_FINALIZED.md now shows **31 changed lines** (was 13). Line 133 is shared: pass 2 extended pass 1's item-10 exception list additively, preserving its clauses verbatim. 495 lines, 116,927 chars; **+5,383 chars** from this pass. Still ends on the final §5 row.

**Counts:** 16 ambiguity pins, 6 mismatch revisions across 19 lines.

**Changes:**
- §2.8 item 10 — revise — mismatch — added `POST /destinations`, `POST /supplier-contracts`, `POST /deposit-milestones` to the "consult no program status" list — `routes/destinations.py:22`, `routes/contracts.py:33`, `routes/milestones.py:20`
- §3.1 (window-close cascade) — insert — ambiguity — the `INVITED -> CANCELLED` sweep deliberately does **not** void air, unlike §3.9 seat cancellation — `cascades.py:111`
- §3.4 (contract create) — insert — ambiguity — no program-lifecycle gate, no destination-selection gate, and the "midnight" stay-start convention is not enforced — `routes/contracts.py:33`
- §3.4 (contract defaults) — revise — mismatch — the ledger is re-derived on every read of **any** contract (any kind, any status) from the program's confirmed seats, so a creation response can show non-zero `room_nights_confirmed` and negative `room_nights_available` — `calc.py:155`, `serialize.py:132`
- §3.4 (negotiation) — revise — mismatch — action is **not** bound to role: either authorized role may send `PROPOSE` or `COUNTER`; only contract status decides — `routes/contracts.py:114`
- §3.4 (negotiation `note`) — insert — ambiguity — `note` is ignored but still type-checked; a non-string / empty `note` is `ERR_INVALID_REQUEST` — `routes/contracts.py:125`
- §3.4 cascade level 2 — insert — ambiguity — a referenced destination that is not `SHORTLISTED` is left untouched, execution continues, it is still exempt from the level-3 sweep, and level 4 still takes the basis from it — `cascades.py:52`
- §3.4 cascade level 4 — revise — mismatch — "skipped entirely" was wrong: when the program is already `CONTRACTED` a **hotel** execution still re-derives `cancellation_exposure_cents` (program `version` does not increment); a non-hotel execution re-derives nothing — `cascades.py:83`
- §3.4 cascade level 5 — revise — mismatch — level 5 runs for every `supplier_kind` and reads the posture already on the program when level 4 was skipped — `cascades.py:87`
- §3.5 (milestone append) — revise — ambiguity — `sequence` uniqueness spans **all** milestones including `CANCELLED` ones (no re-use) — `routes/milestones.py:37`
- §3.5 (milestone append) — insert — ambiguity — gated on neither program status nor parent-contract status — `routes/milestones.py:20`
- §3.5 (milestone pay) — insert — ambiguity — the program's `version` does not move even though its exposure figure changes — `routes/milestones.py:99`
- §3.5 (exposure read) — insert — ambiguity — those 12 fields are the whole payload; available in every contract and program status (a `DRAFT`/`WITHDRAWN` contract gives floor 0 / shortfall 0); never bumps `version` — `routes/contracts.py:196`, `calc.py:204`
- §3.7 (cabin upgrade) — insert — ambiguity — a null `air_cabin_class` is worth 0 on the ladder, like `ECONOMY` — `calc.py:297`
- §3.8 (schedule conflict) — revise — mismatch — the agenda is keyed on `registration_id`, not the qualifier: another seat of the same qualifier (incl. their guest) never collides — `calc.py:352`
- §3.9 (`CONFIRMED -> CANCELLED`) — insert x3 — ambiguity — (a) cancelled guest seats keep their air, get no `cancellation_reason`, keep their own signups; (b) the promotion re-derives activity counters but does **not** version the activity; (c) the budget rollup re-derivation does not version the program — `cascades.py:236,259,270`
- §3.9 (program cancel step 1) — insert — ambiguity — seats' own `cancellation_reason` is not written; the reason lives on the program row only — `cascades.py:154`
- §3.9 (program cancel step 4) — insert — ambiguity — withdrawn qualifiers have `committed_cost_cents` reset to 0; tier id and the whole tax dimension are left alone — `cascades.py:199`
- §3.9 (program cancel step 6) — revise — ambiguity — the budget rollup is re-derived too (subject to §3.1 arming), and because step 5 already terminalised every `SCHEDULED`/`PAID` milestone, a `DEPOSIT_FORFEITURE_BASIS` contract contributes **0**; only `ATTRITION_BASIS` still contributes — `cascades.py:207,221`, `calc.py:213`
- §3.9 (reconciliation) — insert — ambiguity — executed hotel ledgers are re-derived in passing without versioning the contracts (and no figure moves, since `CONFIRMED` and `TRAVELLED` both feed `room_nights_confirmed`) — `cascades.py:147`

### Pass 3 — routes/{registrations,activities,signups,tax_reports}.py (verbatim)

**Verification:** changed-line count went 31 -> **47**; all 31 earlier lines still in the diff, untouched. 495 lines, 121,773 chars; **+4,846 chars** from this pass. Still ends on the final §5 row. `cmp` confirms NOT byte-identical to PRD_FINALIZED.md.

**Counts:** 16 changed lines — 14 ambiguity-pins, 2 mismatch-revisions.

- §2.7 — insert — ambiguity — neither `expected_program_version` nor `expected_activity_version` declares a numeric range, so any integer clears the schema step and 0/negative is a 412 stale-version, not a 400 — `routes/registrations.py:49,56`, `routes/signups.py:40,47`
- §3.6 — revise — ambiguity — a qualifier with no `assigned_tier_id` has an effective guest allowance of 0, and the allowance is consulted only on a `GUEST` enrolment — `routes/registrations.py:68-76`
- §3.7 — insert — ambiguity — the headroom gate reads a freshly re-derived `budget_headroom_cents`; the rollup runs immediately before the comparison — `routes/registrations.py:209-211`
- §3.7 — revise — **mismatch** — rollup trigger list said "every re-ticketing that moves a seat's `cost_cents`"; impl runs it on every accepted air action on a `CONFIRMED`/`TRAVELLED` seat — `routes/registrations.py:308-309`
- §3.7 — revise — **mismatch** — confirmation versions the seat exactly once (status move + `room_nights` stamp are one mutation, contra §2.4's two-mutation example); the ledger refresh does not version the contract and the rollup does not version the program; the qualifier move is conditional on it still being `NOTIFIED` — `routes/registrations.py:213-226`
- §3.7 — insert — ambiguity — air axis is examined before the attendance axis; the attendance precondition belongs to `REQUEST` alone, `TICKET`/`CHANGE` impose none — `routes/registrations.py:264-277`
- §3.7 — revise — ambiguity — `base_fare_cents` >= 0; a `TICKET` action stores none of the four commercial fields and is not subject to the deviation ceiling; a change's omitted deviation figure falls back to the stored value, not 0; the ceiling is evaluated before any write — `routes/registrations.py:250-256,279-294`
- §3.7 — revise — ambiguity — `REQUEST` and `CHANGE` re-derive the four figures and run the same conditional rollup; no rollup below `CONFIRMED`; the seat is the only row an air action versions — `routes/registrations.py:305-309`
- §3.8 — insert — ambiguity — publishing an activity leaves the program row untouched (no `version` move, no money re-derivation) — `routes/activities.py:42-55`
- §3.8 — revise — ambiguity — the signup lifecycle gate reads the **activity's** program, and the activity-state check precedes the registration-state check — `routes/signups.py:51-57`
- §3.8 — revise — ambiguity — on release, the parent activity's state is examined before the signup's own — `routes/signups.py:120-126`
- §3.9 — revise — ambiguity — `cancellation_reason` is a required, non-empty string with no declared upper length — `routes/registrations.py:235`
- §3.9 — insert — ambiguity — the survey has no state guard against re-submission (a later score overwrites and re-versions), and it does not re-stamp the program's `satisfaction_index` — `routes/registrations.py:319-326`
- §3.9 — insert — ambiguity — tax reports carry no uniqueness constraint per qualifier/tax-year; the filing gate, not the draft, keeps one report `FILED` at a time — `routes/tax_reports.py:31-43`
- §3.9 — revise — ambiguity — drafting versions the qualifier only in the `VOIDED -> PENDING_REPORT` branch and never touches the program — `routes/tax_reports.py:67-69`
- §3.9 — revise — ambiguity — filing a `DRAFT` whose qualifier is not `PENDING_REPORT` reports `ERR_QUALIFIER_STATE_INVALID` (previously unnamed), report status is checked first; `void_reason` is a required non-empty string and the void status check precedes the self-review comparison — `routes/tax_reports.py:101-104,122,127-130`

### Orchestrator verification (Step 9 close-out)
- PRD.md, PRD_FINALIZED.md and PRD_COMPLETED.md are each 495 lines; `cmp` confirms PRD_COMPLETED.md is NOT byte-identical to PRD_FINALIZED.md (the scan genuinely ran).
- Cumulative diff PRD_FINALIZED.md -> PRD_COMPLETED.md = 47 changed lines (94 diff rows), matching the sum of the three passes and confirming no pass clobbered another.
- Structure intact: 5 top-level `##` headings; §4 endpoint table 55 pipe rows (53 + header + separator); §5 error table 55 pipe rows; last line is the final error-table row, so no truncation.
- No .py file under implementation/, test_suite/ or test_helpers/ was modified after the green sweep at 22:01, so the 8x 344/344 evidence in results.1..8.json remains valid for the shipped code. Steps 8 and 9 touched only PRD documents, as designed.
- All seven .scratch/ per-step subdirs survive; no sibling scratch was deleted.

## Pipeline complete

Pipeline finished at 2026-09-05T22:39:08.202024913Z: Step 9 wrote workspace/PRD_COMPLETED.md.
