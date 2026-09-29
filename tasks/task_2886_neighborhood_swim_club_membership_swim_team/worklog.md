# Worklog — task_2886_neighborhood_swim_club_membership_swim_team

## Step 1: Create task directory — 2026-09-05T11:39:39.498Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2886_neighborhood_swim_club_membership_swim_team` and its `workspace/` subdirectory. Index 2886 was pre-assigned by the orchestrating harness (no scan of ./tasks/ was performed, per instruction, because up to 32 pipelines run concurrently on this host and auto-allocation would collide).

## Step 2: Generate scaffold — 2026-09-05T13:58:00.000Z

Scaffold generation for `task_2886_neighborhood_swim_club_membership_swim_team` is complete. All three files parse and the lint is clean.

## Output directory

```
-rw-rw-r-- 1 ubuntu ubuntu 194396 SCAFFOLD.yaml
-rw-rw-r-- 1 ubuntu ubuntu 352935 SCAFFOLD_CORNER_DESIGN.yaml
-rw-rw-r-- 1 ubuntu ubuntu 126733 SCAFFOLD_DIFFICULTY_DESIGN.yaml
-rw-rw-r-- 1 ubuntu ubuntu    470 worklog.md      (pre-existing, untouched)
drwxrwxr-x 2 ubuntu ubuntu   4096 workspace/      (pre-existing, still empty)
```

Line counts (all `yaml.safe_load` OK):

| file | lines |
|---|---|
| `.../SCAFFOLD.yaml` | 3789 |
| `.../SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1659 |
| `.../SCAFFOLD_CORNER_DESIGN.yaml` | 5005 |

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2886_neighborhood_swim_club_membership_swim_team/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2886_neighborhood_swim_club_membership_swim_team/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2886_neighborhood_swim_club_membership_swim_team/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    73
  §1.1 entities declared:     16
  §1.8 instances scanned:     18
  §1.9 instances scanned:     54
  Calls scanned (§1.8+§1.9):  1021

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Contents

- **SCAFFOLD.yaml** (§1.0–§1.7 only; verified no `scaffold_difficulty_design` / `scaffold_corner_design` keys): `neighborhood-swim-club`, prefix `/swim-club`, archetypes `compliance_audit` + `temporal_windowing`, layers `optimistic_concurrency, cascading_side_effects, dual_variant_calculation, ops_run_checkpoint`, graph topology, cyclic state machines, segregation-of-duties role model, immediate consistency, `difficulty_level: expert_plus`. 16 entities, 16 state-machine dimensions, 2 concurrency rules, 11 calculations, 61 validations, 73 endpoints, 59 errors, 8 roles.
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml**: all nine §0.5 rule blocks × 2 instances = 18, each with a falsifiable `distinguishing_aspect` and a full `test_recipe`.
- **SCAFFOLD_CORNER_DESIGN.yaml**: 8 guide sections (entities 15, state_machines 14, calculations 13, validations 16, endpoints 6, rbac 4, complexity_layers 6, consistency_model 1) = 75 instances, of which 54 carry recipes and 21 are `excluded_because` stubs citing §1.8 instances by name. Ends with a `§1.6 ERROR CATALOGUE AUDIT` comment mapping all 59 error codes to the recipe-bearing instance that triggers each — `uncovered: []`.

Notes worth relaying: `section: errors` is deliberately absent (guide Table 6 has no claim-type rows) and the every-error-triggerable requirement is discharged by that trailing audit; `entities/immutability` is empty because §1.5 declares no PATCH/PUT. The `scenario:` key holds the scenario text verbatim and does **not** contain the "harder than expert level" directive line, so the known difficulty-directive leak into PRD.md does not apply here. No sibling task directory was read at any point; nothing was written to `workspace/` and `worklog.md` was not created or modified.

**Orchestrator verification**: `grep -i "harder than expert" SCAFFOLD.yaml` returns no match — difficulty directive confirmed absent from the scaffold, so it cannot reach PRD.md.

## Step 3: Copy shared files — 2026-09-05T13:59:49.464Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T14:35:00.000Z

Step 4 required THREE subagent invocations. Orchestrator decision recorded here because it is a judgement call made without a user available:

**4a (crashed).** The first doc-generator subagent was killed by an infrastructure fault ("Agent terminated early due to an API error") after it had written §1, all of §2 (2.1-2.10), §3.1 and §3.2 — 187 lines / 41 KB. Because the orchestrator had mandated chunked `cat >>` appends rather than one giant Write, that prefix survived on disk intact. No agentId was returned, so the dead agent could not be resumed via SendMessage.

**Decision:** resume by continuation rather than regenerate from zero. The skill's truncation guidance ("if truncated, regenerate it — do not hand-patch it") is aimed at silent doc-generator truncation and at hand-patching by the orchestrator; neither applies here. This was an infrastructure kill with a verified-complete prefix that ends at a clean paragraph boundary, and the continuation agents were given the full existing PRD to read so they inherit its terminology, field names, role names, error ids and prose style. No orchestrator hand-patching occurred at any point — every byte of PRD.md was written by a doc-generator subagent.

**4b — completed §3.** Verbatim summary:

§3 is complete. PRD.md is now **309 lines** (was 187 when I resumed). All writes were append-only heredocs; the pre-existing 187 lines (§1, §2.1–§2.10, §3.1, §3.2) are byte-unchanged, and no §4/§5 was written. worklog.md untouched; the two withheld design files were never opened.

§3 subsection headings added (§3.1/§3.2 pre-existed):
- `### 3.3. Selling a Membership: Eligibility Gates and the Dues Assessment`
- `### 3.4. Invoicing, Settlement and the Delinquency Consequence`
- `### 3.5. The Gate: Guest Passes, Guest Fees and Voided Visits`
- `### 3.6. The Swim Team, Meet Hosting and the Volunteer Credit Ledger`
- `### 3.7. Private Parties: Zone Booking, Tiered Pricing and Refunds`
- `### 3.8. The Deck: Guards, Certifications and Ratio Compliance`
- `### 3.9. Conduct: Reporting, Sanction, Appeal and the Suspension Cascade`
- `### 3.10. The Capital Reserve: Resurfacing, Pumps and the Two-Counter Identity`

The volunteer-credit buyout landed in §3.6 as required by §3.2's forward reference; §3.1's forward reference to §3.7 (party refunds on closure) is satisfied; §3.6 and §3.7 both forward-reference §3.8 for the guard ratio, and §3.4's write-off cascade forward-references §3.9.

Tail of file (last two paragraphs) covers the reserve draw (`draw_amount_cents`, `expected_capital_project_version`, `ERR_STALE_PROJECT_VERSION`, `ERR_SEASON_MISMATCH`, `ERR_INSUFFICIENT_RESERVE`, `ERR_DRAW_EXCEEDS_BUDGET`, `APPROVED → FUNDED` on first draw) and the cancellation compensation restoring the two-counter identity.

**Contract 1 — Field coverage check** (whole PRD, fenced JSON blocks excluded from the token scan):
- `entities[].fields`: 172 required, 172 present, 0 missing
- `endpoints[].request_body`/`input`: 81 required, 81 present, 0 missing
- `endpoints[].query_params`/`path_params`: 33 required, 33 present, 0 missing
- Status: PASS

**Contract 2 — Rule coverage check:**
- `validations[]` with priority: 60 checked, 60 expressed in prose, 0 missing (all 59 `errors[].id` values appear; the 20 auth/shape/enum/pagination/existence codes are expressed in the §2.9 rejection ladder written earlier, which is their correct home)
- `concurrency_rules[]` OCC rejections: 2 checked, 2 expressed (`expected_household_version`/`ERR_STALE_HOUSEHOLD_VERSION` in §3.5, `expected_capital_project_version`/`ERR_STALE_PROJECT_VERSION` in §3.10, each with its write operation named by capability rather than path)
- `state_machines[].transitions`: 83 checked, 83 fully expressed, 0 missing (verified edge-by-edge against the scaffold table; every state literal appears in §3)
- `calculations[]`: 11 checked, 11 fully expressed with constants, evaluation order and rounding, 0 missing
- `validations[]` conditions: 60 checked, 60 matchable to their `error_id` in prose, 0 missing
- `side_effects` / `applies_to`: expressed, including all cascade orderings (`created_at` ASC, `start_iso` ASC then `created_at` ASC) and the shared suspension cascade reused by the dues write-off
- sibling-branch symmetry: checked (suspension vs expulsion cascade, the four party cancellation outcomes, the three refund rules, `STAFFED`/`UNDERSTAFFED` meet branches, `SUPERSEDED` from both `VALID` and `EXPIRED`) — 0 asymmetric, with the one deliberate asymmetry (auto-apply does not run on suspension cancellations) stated explicitly
- Status: PASS

**Contract 3 — Path purity check (§3 only, lines 147–309):**
- backtick tokens scanned: 1271
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
- (no token in §3 contains `/` at all)
- Status: PASS

Deliberate gaps left to §4/§5: HTTP methods, URL paths, status codes, the response envelope shape, pagination metadata, header names, and the error-code catalogue table. Two fidelity judgements worth flagging to whoever writes §4/§5: (a) the guard-shift cancellation precondition protecting overlapping confirmed parties has no dedicated scaffold error id, so §3.8 reports it as `ERR_GUARD_RATIO_NOT_MET`; (b) the appeal-window and two-appeal limits likewise have no dedicated ids, so §3.9 reports a late or third appeal as `ERR_INVALID_TRANSITION`.

**4c — wrote §4 + §5.** Verbatim summary:

§4 and §5 appended and verified. PRD.md is complete.

Appended (append-only, 10 heredoc chunks, each confirmed with `tail -3`; the existing 309 lines were never rewritten):

- `## 4. Endpoint Definitions` — an intro paragraph pinning the 201-on-create / 200-on-everything-else rule and pointing readers back to §2/§3 for payloads, plus a 73-row table grouped by resource in §3's introduction order (Season → MembershipCategory → Household → WaitlistEntry → Membership → GuestVisit → Lifeguard → Certification → GuardShift → SwimTeamRegistration → Meet → VolunteerAssignment → PartyReservation → InspectionFinding → ConductCase → CapitalProject → logical clock).
- `## 5. Error Code Catalogue` — an intro paragraph tying `error_id` to the §2.2 envelope and to §2.9's rejection ladder, plus a 59-row table.

Final numbers:
- `wc -l`: **455** (§1 line 3, §2 line 11, §3 line 147, §4 line 311, §5 line 391)
- Endpoint coverage: **73/73**, 0 missing, 0 extra, 0 duplicate rows; all 73 role lists match `endpoints[].roles` exactly (0 mismatches)
- Error coverage: **59/59**, 0 missing, 0 extra, 0 duplicates; all 59 HTTP statuses match `errors[].http` exactly
- Contract 1 (whole document): `entities[].fields` 142/142, request bodies 81/81, query params 33/33 — **PASS**
- Contract 3 re-run for safety: 1271 §3 backtick tokens, 0 slash-leading, 0 bare-method, 0 method+path — still PASS (§4 sits after the `## 4.` boundary)
- `tail -12` ends on a completed row: `ERR_DRAW_EXCEEDS_BUDGET | 422 Unprocessable Entity`

Fidelity notes honoured: no new error ids were invented; `ERR_GUARD_RATIO_NOT_MET` (guard-shift cancellation / meet hosting / reservation confirm) and `ERR_INVALID_TRANSITION` (late or third appeal) are catalogued as-is and the §4 descriptions for those transition endpoints stay neutral, so nothing contradicts §3.8/§3.9. Also verified no scaffold-internal references leaked into the new text; worklog.md and the two withheld design YAMLs were not touched or read.

One deliberate deviation from the orchestrator's brief, and it is correct: the orchestrator asked for per-endpoint request bodies / success codes / error lists in §4 and a "meaning" column in §5. SKILL.md explicitly forbids that — §4 is a 4-column table (Method, Path, Description, Authorized Roles) and §5 a 2-column table (Error ID, HTTP Status), both blocking Quality-Checklist items, and exposing request bodies in §4 would collapse the §3 scattering the benchmark depends on. The agent followed the skill. Orchestrator concurs; no revision requested.

**Orchestrator truncation check (mandated by the invocation):** `wc -l` 455, 118096 bytes. All five top-level sections present at lines 3 / 11 / 147 / 311 / 391. `tail -8` ends on the complete final error-catalogue row `| ERR_DRAW_EXCEEDS_BUDGET | 422 Unprocessable Entity |` — a real section boundary, not mid-sentence. `grep -ni "harder than expert|expert_plus|scaffold"` returns no match, so neither the difficulty directive nor any scaffold-internal reference reached PRD.md. PRD accepted; no regeneration needed.

## Step 6: Generate implementation — 2026-09-05T15:30:00.000Z

Note on ordering: Steps 5 and 6 ran concurrently, and Step 6 finished first, so its entry is recorded here ahead of Step 5's. Orchestrator slip worth recording: the two Agent calls were meant to go out in a SINGLE assistant message to guarantee concurrency; Step 5 went out alone and Step 6 followed in the next message about 20 seconds later. Because Step 5 was launched in the background, the two still ran concurrently in wall-clock terms, and the physical isolation that matters was preserved — `test_suite/` did not yet exist when Step 6 started, and Step 6 was additionally forbidden in its prompt from reading `test_helpers/` or `test_suite/`. Verified: Step 5's first files appeared roughly 15 minutes after Step 6 began.

Verbatim summary returned by the implementation generator:

FINAL REPORT

Implementation directory: `/home/ubuntu/github/CodingPRD/tasks/task_2886_neighborhood_swim_club_membership_swim_team/workspace/implementation/`

**Per-file line counts** (4,273 lines total)

| File | Lines | Role |
|---|---|---|
| `app.py` | 78 | Flask factory, blueprint registration, `before_request` version scope, 404/405/ApiError/Exception envelope handlers, `/health` |
| `auth.py` | 87 | `X-User-Id`/`X-User-Role` parsing, endpoint-role guard, ownership, segregation-of-duties |
| `clock.py` | 106 | Logical UTC clock (starts `2026-08-01T00:00:00.000Z`), instant/date parsing, ISO formatting |
| `constants.py` | 188 | Enums, capacities, fee/credit/penalty tables, conduct points |
| `engine.py` | 796 | All 11 calculations, ratio compliance, delinquency, cascades, standing/posture derivations |
| `envelope.py` | 56 | `meta`/`response_type`/`data` envelope, `api_request_id`, list pagination fields |
| `errors.py` | 101 | The 59-code catalogue, `ApiError`, `fail()` |
| `money.py` | 66 | Integer cents, `ROUND_HALF_UP`, `allocate_evenly` |
| `routes_book.py` | 650 | Categories, households, waitlist, memberships, invoices, payments, billing run |
| `routes_deck.py` | 451 | Lifeguards, certifications, shifts, guest visits, reserve contributions |
| `routes_facility.py` | 627 | Parties, inspection findings, conduct cases, capital projects |
| `routes_seasons.py` | 264 | Seasons, posture, close, clock endpoint |
| `routes_team.py` | 424 | Swim-team registrations, meets, volunteer assignments |
| `store.py` | 130 | In-memory dict store, request-scoped version dedup, serialization |
| `validation.py` | 228 | Shape/enum/range/pagination validation, list filters |
| `start.sh` | 20 | Launcher |
| `requirements.txt` | 1 | `Flask>=2.2` |

**start.sh** — reads `$PORT` from the environment (`export PORT="${PORT:-8000}"`; the literal is only a fallback for a bare local run, `$PORT` always wins), and `app.py` binds `host="0.0.0.0", port=int(os.environ["PORT"])`. It ends in `exec python3 app.py` — foreground, no `&`, no `nohup`, so the evaluator's kill reaches the server directly. `pip install` runs only if Flask is missing, and is silenced/best-effort so it cannot delay or fail a boot.

**Storage** — in-memory only: plain Python dicts inside a single `Store` instance in `store.py`. No SQLite, no file writes, no `/tmp` cache, no external service. Zero seeded entities: a fresh boot reports 0 rows across all 16 collections and an empty `GET /swim-club/seasons` (`total_count: 0`), and the logical clock reads exactly `2026-08-01T00:00:00.000Z`. Verified by re-running `bash start.sh` after a populated smoke run — all state was gone.

**Endpoints** — exactly **73** routes under `/swim-club` in `app.url_map`, matching PRD §4 one for one (plus an unprefixed `/health`, which is outside the contract's namespace).

**Error codes** — all **59** ids from PRD §5 are both defined in `errors.py` and actually raised from handler/engine code (audited by grepping each id outside `errors.py`; none is dead).

**Verification** — every module passes `python3 -m py_compile`. A 70+ call end-to-end smoke script (`/tmp/task_2886_swimclub_impl/smoke.py`, task-scoped scratch) exercises the season lifecycle, dues/invoice/payment/settlement, guest visits with OCC, party pricing and refunds, registrations/meets/volunteer credits and the understaffed penalty, the capital reserve two-counter identity, the conduct-sanction cascade and appeal path, and the critical-finding closure cascade — it prints `SMOKE OK`. Both smoke servers were launched on high random ports and killed by their own PIDs; no broad `pkill` was ever used, nothing is left running, and `__pycache__` was removed.

**Ambiguous PRD passages and the interpretation chosen**

1. **§2.9 ladder vs. §3.x narrative ordering.** Where a domain section lists checks in a different order than the 16-band ladder, the ladder wins. So `ERR_OUTSIDE_SEASON_WINDOW` (band 13) precedes `ERR_ZONE_DOUBLE_BOOKED`/`ERR_BATHER_CAPACITY_EXCEEDED` (band 14), and `ERR_HOUSEHOLD_SUSPENDED` precedes `ERR_MEMBERSHIP_NOT_IN_GOOD_STANDING`, even though §3.7 reads the other way.
2. **`ERR_ALREADY_TERMINAL` vs. `ERR_INVALID_TRANSITION`.** Terminal is checked first everywhere, otherwise the code is unreachable — except that a band-11 precheck (season OPEN for registration CONFIRMED; facility posture for meet HOSTED and party CONFIRMED) precedes both, per the ladder.
3. **Per-transition role narrowing.** Applied *before* ownership/existence (bands 2 then 3) and only for genuinely requestable edges, so a Member naming a system-only target such as `CANCELLED_BY_CLOSURE` gets `ERR_INVALID_TRANSITION` rather than a role error.
4. **RESTRICTED posture on OPEN-only operations.** §3.1 confines `ERR_FACILITY_RESTRICTED` to exactly two operations, so party confirm and meet host under RESTRICTED report `ERR_FACILITY_CLOSED`.
5. **Temporal preconditions on transitions** (meet HOSTED before `end_iso`, party COMPLETED before `end_iso`, host-cancel at/after `start_iso`, the 10-day appeal and closure windows, IN_PROGRESS with zero funding) all report `ERR_INVALID_TRANSITION`, there being no dedicated temporal code for them.
6. **Party rejection refund.** Credits the same household counters as a cancellation, but does *not* run auto-apply; only host and closure cancellations auto-apply against an open membership balance.
7. **Season version bumps.** Verify-close advances the season's `version` unconditionally (PRD says so explicitly); finding creation and other posture re-derivations advance it only when the row actually changed, per §2.4. Cancelling a capital project touches the season only when `funded_cents > 0`, honouring §2.4 over §3.10's unconditional phrasing.
8. **`draw_amount_cents` minimum.** Accepts 0 (band 5: money fields are "integers of at least 0"), whereas `budget_cents` requires >= 1 because §3.10 states that explicitly.
9. **`POST .../fund` accepts an optional `season_id`.** The route carries no season, so without this the documented `ERR_SEASON_MISMATCH` on that endpoint would be unreachable.
10. **List filters with unrecognised enum values** return an empty page rather than `ERR_INVALID_ENUM`; §2.9 band 6 governs request *bodies*, and §2.7 describes filters as equality matches.
11. **Delinquency has zero tolerance** (§3.4): any outstanding `guest_fee_owed_cents` or `party_charges_owed_cents` makes the household delinquent, not merely a DELINQUENT/WRITTEN_OFF membership — this is what makes `ERR_DUES_DELINQUENT` fire on registration for a household that only owes party charges.
12. **Understaffed-penalty allocation** divides evenly across *distinct* memberships holding a CONFIRMED registration in the meet's season, ordered by `created_at`, and skips zero shares so no row's version moves for a no-op.

## Step 5: Generate unit tests — 2026-09-05T16:45:00.000Z

Verbatim summary returned by the unit-test generator:

All 18 test files are complete and audited. Final state below.

## Output locations (task root, as required)

`.../test_helpers/` — 3550 lines
```
__init__.py      184     api_client.py    466     api_errors.py    156
assertions.py    617     constants.py     102     factories.py     538
fixtures.py      827     test_users.py    112     types.py         548
```

`.../test_suite/` — 10490 lines
```
conftest.py                             17
test_01_dual_variant_calculations.py   274   test_10_entities.py                   1021
test_02_combinatorial_formulas.py      241   test_11_state_machines.py             1014
test_03_independent_state_machines.py  277   test_12_calculations.py                834
test_04_transitive_cascades.py         354   test_13_validations_admission.py       662
test_05_validation_priority_pairs.py   294   test_14_validations_facility.py        771
test_06_boundary_precision.py          282   test_15_validations_scope_and_money.py 576
test_07_cross_entity_state.py          283   test_16_endpoints.py                  1262
test_08_temporal_overlap.py            347   test_17_rbac.py                       1035
test_09_compensating_invariants.py     355   test_18_complexity_and_consistency.py  591
```
`ls -d workspace/test_helpers workspace/test_suite` returns nothing; `workspace/implementation/` was never read or written; `__pycache__` cleaned.

## Coverage

- **Total tests: 274**, every one carrying exactly one `Design:` tag; **70 distinct instances** resolved, 0 tag problems.
- **Queue A (§1.8 difficulty): 18/18 instances.**
- **Queue B (§1.9 corner): 52/54 recipe-bearing instances** — calculations 6/6, complexity_layers 2/2, consistency_model 1/1, endpoints 6/6, entities 13/15, rbac 4/4, state_machines 8/8, validations 12/12.
- Verbatim-citation audit: `real mismatches: 0`; section-attribution audit: `section problems: 0`; import audit: no unused imports; whole tree compiles.

## Instances SKIPPED entirely (2, both contradicted by the PRD)

1. `Corner/entities/defaults_membership_category_optional_flags_default_to_true` — the recipe asserts `waitlist_required` defaults to `true`; PRD line 175 states it defaults to `false`. The asserted outcome is not derivable (it is refuted).
2. `Corner/entities/required_fields_season_create_without_capacity_returns_validation` — the recipe expects a validation error when `bather_load_capacity` is omitted; PRD line 152 gives it a default of 120, so an omission is legal and no error is uniquely derivable.

## Partial omissions inside otherwise-covered instances

- `validations` instance 1: the `ERR_CATEGORY_MISMATCH` probe (fires only on an accepted-waitlist conversion, which the recipe's fixture does not establish).
- `validations` instance 3: the `guest_count: 0` probe (PRD names `ERR_GUEST_LIMIT_EXCEEDED` for >6; the code for a sub-minimum count is not uniquely derivable against the generic validation band).
- `rbac` instance 4: the tr-002 approval probe expecting `ERR_SEGREGATION_OF_DUTIES` (tr-002 != the proposer tr-001, so §2.8's identity check passes and no code is named for a Treasurer on the BoardPresident's edge).
- `consistency_model` instance: the `invoice_total_cents == 0`-at-creation probe (no creation default for that field appears anywhere in the PRD).

## Design-mechanism corrections applied (recipe path replaced with the PRD-legal one, assertions preserved)

- Queue-A rules 5 and 7: reached the delinquent state via billing-checkpoint expiry instead of the recipes' PRD-illegal revocation path.
- Queue-B `validations` instance 12: promotion driven through `PENDING`.
- `endpoints` instance 2: `required_guard_count` is 1 at zero bather load, not 0.
- `endpoints` instance 4: a guard becomes `INACTIVE` when its last lifeguard certification expires.
- `rbac` instance 1: `PROBATION` is reached from `SUSPENDED` (the PRD describes that endpoint only as the softening/reinstatement path).

Late finding worth flagging for Step 7 triage: the membership money dimension is `UNBILLED -> INVOICED` (there is no `DuesStatus.PENDING`; `PENDING` belongs to the access dimension), and the membership balance identity is `invoice_total_cents + volunteer_buyout_cents - amount_paid_cents` floored at 0 — `dues_paid_cents` does not exist. test_18 was corrected accordingly before completion.

**Orchestrator verification:** `test_helpers/` and `test_suite/` both sit at the task root; `ls -d workspace/test_helpers workspace/test_suite` returns nothing, so the known "test dirs land under workspace/" failure did not occur. 274 `def test_` definitions and 274 `Design:` tag lines — exactly one-to-one.

## Step 7: Run tests and iterate — 2026-09-05T17:35:00.000Z

Verbatim summary returned by the Step 7 fix subagent:

All 8 parallel rounds pass 274/274. No persistence, no seeded data, `worklog.md` untouched.

## Summary

**Iterations run:** 2 (baseline sweep, one batch of 9 fixes, verification sweep).

Iteration 1 showed **261/274 in all 8 rounds with an identical 13-test failure set** — fully deterministic, zero flakiness, so no load-contention triage was needed.

### Tests deleted
None. One assertion was removed under STEP 1c (partial coverage), and the test itself was kept and renamed:

- `test_04_transitive_cascades.py` -> `TestConductSuspensionCascadeReachesTheMeetRoster` — dropped only `understaffed_penalty_cents == 15000`; renamed to `test_the_meet_slides_back_and_the_roster_stays_closed`. **Category: non-unique derivability.** PRD §3.6 gates the recompute on *"when the meet **was** `STAFFED` ... the meet slides back and `understaffed_penalty_cents` is recomputed from the new shortfall"*. The cascade releases the two assignments one registration at a time (§3.9, `created_at` ascending), so the second release finds an already-`UNDERSTAFFED` meet. PRD is silent on whether the penalty then tracks the deeper shortfall (15000) or keeps the figure the slide stamped (7500) — both implementations are consistent with the quoted sentence. The PRD-covered assertions (`volunteer_slots_filled == 0`, status `UNDERSTAFFED`, `roster_closed_at` not cleared) were kept.

### Fixes applied to `test_suite/`
- **test_01** `test_the_initiation_fee_line_fires_on_both_variant_memberships` — second membership now expects `0`, not `45000`. The assertion contradicted PRD §3.2 (*"it becomes true once the household has ever held a membership"*): the same household is sold twice, so the second sale legitimately escapes the fee.
- **test_06** `_book(...)` x 3 call sites — `Zone.SHALLOW_END, 1, 0` -> `0, 1`. PRD §3.7 pins the inputs asymmetrically (`guest_count` "may be 0", `host_party_size` "at least 1"); the fixture sent `host_party_size=0`, which the PRD-faithful implementation correctly rejected as `ERR_VALIDATION`. The load stays 1, so all pinned arithmetic (51 bathers, 3 guards) is unchanged.
- **test_11** `_a_suspended_household_with_a_revoked_swimmer` — re-read the meet after the assignment and before the sanction. The test asserted `volunteer_slots_filled == 2` against the meet's *creation* snapshot, which PRD §3.6 requires to be 0.
- **test_13** line 607 — `assert_registration(newcomer, status=...)` -> `expected_status=...`; wrong keyword raised `TypeError` before any assertion ran.
- **test_17** `test_every_refused_call_left_no_row_and_no_field_change_behind` — `join_date` moved to the season's `open_date`. It joined mid-season (correctly prorating to 28175) while asserting the un-prorated `COUPLE_INVOICE_TOTAL` (31050).
- **test_18** `test_the_invoice_response_already_carries_every_recomputed_field` — wrapped `invoiced_at` in `canonical_instant(...)`; it compared a raw 3-fractional-digit server instant (PRD §2.4) against a canonicalised literal.

### Fixes applied to `test_helpers/`
None — no fixture bug reached this batch.

### Fixes applied to `implementation/`
- **`routes_book.py` / `respond_waitlist`** — hoisted the offer-live check out of the `ACCEPT` branch so it also guards a requeueing `DECLINE`, ahead of the deferral-budget check. PRD §2.9 band 11 orders *"the waitlist offer is live (`ERR_OFFER_EXPIRED`) ; the deferral budget is not exhausted (`ERR_MAX_DEFERRALS_REACHED`)"* — a pair that is only jointly observable on that edge, which makes the ordering meaningless unless expiry applies there.
- **`routes_facility.py` / `transition_project`** — moved the two-person-control check ahead of the per-edge role narrowing. A self-approving Treasurer is on the endpoint's §4 role list (`BoardPresident, Treasurer`), so it clears ladder band 2; §2.8 says the segregation check is *"evaluated before any state or business rule"* and §3.10 names this exact caller: *"a treasurer-turned-president approving their own proposal is `ERR_SEGREGATION_OF_DUTIES`"*. It had been answering `ERR_UNAUTHORIZED`.

### Final sweep evidence
`274/274` x 8 rounds — 0 failed, 0 errors in every round.

**Orchestrator verification:** the orchestrator read all 8 `results.$i.json` itself, independently of the subagent's report. Iteration-1 baseline was confirmed as 261/274 in every one of the 8 rounds (identical failure count in all rounds = deterministic, not load-induced), and the final sweep was confirmed as 274/274 in all 8 rounds. The results files are real and present on disk, so the known "Step 7 claims a clean sweep with no results.*.json behind it" failure did not occur. Step 8 will NOT be skipped: Step 7 applied 2 `implementation/` fixes, 6 `test_suite/` fixes and 1 partial-coverage assertion removal.

## Step 8: Finalize PRD — 2026-09-05T17:24:00.000Z

Step 8 was NOT skipped: Step 7 applied 2 `implementation/` fixes plus 6 `test_suite/` fixes and one partial-coverage assertion removal, so the skip condition (zero iterations beyond baseline) did not hold. Verbatim summary returned by the finalizer subagent:

PRD_FINALIZED.md is written. Four edits, all traceable to `<step_7_diff>` items.

**Line counts:** PRD.md 455 -> PRD_FINALIZED.md 457 (+2 lines, +0.44%; bytes 118,096 -> 120,357, +1.9%). Four hunks, three of them in-paragraph revisions.

**Changes**
- §2.4 — insert — pins the one instant rendering the impl uses everywhere: every instant-valued field (server-stamped `*_at` fields and client-supplied `*_iso` inputs echoed back) is normalised to UTC, sub-millisecond precision dropped, exactly three fractional digits + `Z`. Traces to the test_18 `canonical_instant(invoiced_at)` fix; PRD §2.4 previously pinned the width only for `created_at`/`updated_at`. `implementation/clock.py:57-65`, `validation.py:63-70`, `routes_book.py:546`.
- §3.2 (waitlist respond) — revise — the offer-live check guards every `ACCEPT` and every `DECLINE` (requeueing or not) against an `OFFERED` entry and runs ahead of the deferral-budget check; `WITHDRAW` is not subject to it. `implementation/routes_book.py:344-359`.
- §3.6 (roster slide) — revise — `understaffed_penalty_cents` is recomputed only on the `STAFFED -> UNDERSTAFFED` slide (or at roster closure); a credit leaving an already-`UNDERSTAFFED` meet lowers `volunteer_slots_filled` but leaves the stamped penalty alone. This is the silence behind the dropped `== 15000` assertion. `implementation/engine.py:481-497`, `routes_team.py:216-224`.
- §3.10 (project approve/reject) — revise — the two-person control is settled before the per-edge narrowing that reserves `APPROVED`/`REJECTED` for the `BoardPresident`, so a self-approving `Treasurer` gets `ERR_SEGREGATION_OF_DUTIES`, while a non-proposer `Treasurer` (or any other caller off the edge) still gets `ERR_UNAUTHORIZED`. `implementation/routes_facility.py:530-536`.

**Pre-edit search log**
1. §3.2 offer expiry. (a) Subject: `ERR_OFFER_EXPIRED` / offer-window liveness. (b) Enumerated `grep -rn "offer_expires_at|ERR_OFFER_EXPIRED|offered_at"` across all impl modules: `engine.py:778-779` (offer minting, +14d), `routes_book.py:344-348` (the only `ERR_OFFER_EXPIRED` raise, gated on `decision in ACCEPT|DECLINE and status == OFFERED`), `routes_book.py:360-366` (requeue clears both instants), `routes_seasons.py:174-176` (billing-checkpoint step 2 expiry, strict `<`), `create_membership`'s consumption of an `ACCEPTED` entry (no expiry re-check). (c) Adjustment: scoped the sentence to `ACCEPT`/`DECLINE` "aimed at an entry in `OFFERED`" and added the explicit `WITHDRAW` carve-out, so the checkpoint expiry path and the membership-conversion path stay untouched.
2. §3.6 penalty. (a) Subject: `understaffed_penalty_cents`. (b) All five write sites: `routes_team.py:216-223` (close roster stamps), `engine.py:481-497` (`recompute_meet_filled` — slide + penalty, only when status is `STAFFED`), `routes_team.py:244` (host-time distribution reads it), `routes_team.py:301` (cancel zeroes it), plus both callers of the recompute (`transition_assignment` NO_SHOW at `routes_team.py:403-404` and `release_assignments_of` at `engine.py:502+`). (c) Adjustment: said "recomputed only on that slide ... as the roster closure or the earlier slide stamped it" rather than "never recomputed", which would have contradicted close-roster and the cancel-to-zero path; deliberately made no claim about an `UNDERSTAFFED -> STAFFED` direction, which the impl never performs.
3. §3.10 ordering. (a) Subject: two-person control vs per-edge role narrowing. (b) `auth.py:41-87` (`authorize`, `require_transition_role`, `require_segregation`), and all three shared transition endpoints: `routes_facility.py:266-277` (finding — narrowing *before* segregation), `routes_facility.py:379-391` (case — narrowing before segregation), `routes_facility.py:516-536` (project — segregation before narrowing); §4 role list confirmed as `BoardPresident, Treasurer` at PRD line 385. (c) Adjustment: the sentence is scoped to the capital-project `APPROVED`/`REJECTED` request only, and §2.8's general sentence was left verbatim, so no general "segregation precedes narrowing" rule is implied that would mis-describe the finding and case endpoints. Also left existence-resolution ordering unmentioned (impl resolves the project 404 before both checks).
4. §2.4 instants. (a) Subject: instant field rendering. (b) `clock.py:57-65` (`iso`, 3 digits, truncating `microsecond // 1000`), `clock.py:21-41` (parser accepts 1-9 fractional digits and offsets), `validation.py:63-70` (every `"instant"` input is re-rendered through `clock.iso` before storage), all seven `V.f(..., "instant")` specs (`routes_facility.py:30-31`, `routes_team.py:161-162`, `routes_deck.py:29`, `routes_deck.py:315-316`, `routes_seasons.py:255`), every `clock.now_iso()`/`clock.iso()` stamp site (`store.py:90-107`, `routes_book.py:360/546`, `routes_team.py:223`, `routes_deck.py:135`, `routes_facility.py:295/422`, `engine.py:205/284/778-779`), and `envelope.py:27`. (c) Adjustment: restricted the universal to *instant*-valued fields (date-typed fields like `join_date`, `open_date`, `expires_on` are stored verbatim as `YYYY-MM-DD`) and phrased inputs as "echoed back ... normalised" rather than "server-stamped", since client instants are canonicalised rather than re-stamped.

**Orchestrator verification:** `PRD_FINALIZED.md` exists and is NOT byte-identical to `PRD.md` (455 -> 457 lines, 118096 -> 120357 bytes), which is the expected shape given Step 7 made real implementation fixes.

## Step 9: Complete PRD — 2026-09-05T18:20:00.000Z

**Orchestrator decision (no user available, recorded per the autonomy directive):** Step 9 was run as THREE SEQUENTIAL module-partitioned passes over one shared `PRD_COMPLETED.md`, rather than as a single subagent. The implementation is 4273 lines across 17 modules; a single agent cannot walk that exhaustively without silently truncating its scan, and the classic failure signature is a `PRD_COMPLETED.md` that comes back byte-identical to `PRD_FINALIZED.md`. Pass 1 owned the `cp` and was the only pass permitted to run it; passes 2 and 3 were explicitly forbidden from copying so they inherited their predecessors' edits. Each pass was given the previous passes' edits as do-not-contradict constraints, plus any out-of-partition silences its predecessor had spotted but was forbidden to touch.

Partition:
- **Pass 1** — cross-cutting infrastructure (`app.py`, `envelope.py`, `errors.py`, `auth.py`, `validation.py`, `money.py`, `clock.py`, `constants.py`, `store.py`) plus `routes_seasons.py` and `routes_book.py`.
- **Pass 2** — `routes_deck.py`, `routes_team.py`, `routes_facility.py` (handler-level ordering, validation, status codes, transition gating, response shaping, side-effect sequencing).
- **Pass 3** — `engine.py` (all 11 calculations, both ratio probes, all four cascades, delinquency, standing/posture derivations), plus a final cross-pass consistency read.

**Aggregate: 78 changes — 63 ambiguity-pins, 15 mismatch-revisions.** `PRD_FINALIZED.md` 457 lines / 120,357 chars -> `PRD_COMPLETED.md` 457 lines / 148,627 chars (+28,270 chars, +23.5%). Line count is unchanged across all three passes because every edit was an in-paragraph insert or revision — no new paragraphs and no new sections, as the skill requires.

### Pass 1 verbatim summary (30 changes: 26 ambiguity-pins, 4 mismatch-revisions)

`cp workspace/PRD_FINALIZED.md workspace/PRD_COMPLETED.md` performed exactly once at the start. 457 lines / 120,357 chars -> 457 lines / 129,301 chars (+8,871). 28 lines changed, all in-paragraph. Both Step 8 edits inside the partition (§2.4 instant rendering line 84, §3.2 offer-live check line 189) verified intact — line 189 was extended around the Step 8 sentence, not over it. Also verified with a script that the 59-entry error catalogue in `errors.py` matches §5 exactly (ids and statuses) — no §5 edits needed.

Changes: §2.1 whitespace-only header counts as empty, both header values trimmed (auth.py:31-38) · §2.2 `api_request_id` is `req_` + exactly 20 chars from `A-Z0-9`, minted per response including errors (envelope.py:20-21) · §2.2 `api_request_timestamp` reads the logical clock, not wall time (envelope.py:27) · §2.3 `created_at` ties break on insertion order (store.py:86,130) · §2.3 filters exact/case-sensitive, uninterpretable values match no rows, bool accepts true/1/yes and false/0/no, list reads never scoped to the caller so a `Member` sees all rows (validation.py:183-228) · §2.4 a row changed twice in one request advances `version` once, not per hop (store.py:101-112, app.py:38-42) · §2.5 clock may move backwards or repeat; no monotonicity (clock.py:87-88) · §2.9 band 3 request-named household compared before lookup (403 even for unknown id), indirect ownership on a missing row falls through to band 9's 404 (auth.py:58-68) · §2.9 band 5 absent/unparseable body treated as `{}`, non-object body is `ERR_VALIDATION`, explicit `null` == omitted, whitespace-only string not non-empty, JSON types literal (bool is not an int), instant must carry `Z` or offset, undeclared fields ignored (validation.py:36-93) · §2.9 band 6 band 5 exhausted over the whole payload before any enum check (validation.py:96-113) · **§2.9 band 11 MISMATCH** `ERR_ALREADY_TERMINAL` precedes `ERR_INVALID_TRANSITION` when both apply (ladder had listed the reverse); verified universal across all five route modules · §2.10 unknown path -> `ERR_VALIDATION` 404, bad method -> `ERR_VALIDATION` 405 (the only status deviations from §5), server fault -> 500, trailing slash insignificant (app.py:27,48-64) · §3.1 duplicate season `year` -> `ERR_VALIDATION`, `dues_due_date` not window-constrained · §3.1 `baseline_bather_load` recorded only, feeds neither the §3.8 ratio nor the §3.7 capacity test · §3.1 open/close transition codes · §3.1 checkpoint step three leaves an unfillable slot unfilled, never an error · **§3.1 MISMATCH** season close skips `WRITTEN_OFF` memberships and recomputes BOTH required and earned credits (PRD said earned only), balance floored at 0 · §3.2 duplicate category `code` -> `ERR_VALIDATION` · §3.2 front-desk bond ceiling uses the household's most recently created membership's category; no membership -> ceiling 0 · §3.2 withdraw-from-`OFFERED` and accept/decline-from-`WAITING` -> `ERR_INVALID_TRANSITION`, resolved entry -> `ERR_ALREADY_TERMINAL` ahead of the offer-live check · **§3.2 MISMATCH** "only the charged household may respond" narrowed to `Member`; the authorised `MembershipChair`'s opaque id is never compared · §3.3 `join_date` window mandatory and inclusive · §3.3 waitlist gate matches any `ACCEPTED` entry in any season and does not mutate it · §3.3 remaining money/credit fields born at 0, `invoiced_at` null, `bond_status` -> `INSTALLMENTS` only from `NONE` · §3.4 invoice re-attempt codes · §3.4 payment status codes · §3.4 membership `BOND` payments never overwrite `TRANSFERRED` and are capped only by `balance_due_cents`, so `bond_paid_cents` may pass `bond_cents` · §3.8 `at_iso` mandatory, settled before the season resolves · §3.9 reinstatement codes · §3.10 lump reserve contribution not gated by season lifecycle · §4 `GET /health` liveness probe outside the prefix and the envelope.

### Pass 2 verbatim summary (33 changes: 27 ambiguity-pins, 6 mismatch-revisions)

No `cp` was run. 457 lines / 129,301 chars -> 457 lines / 142,719 chars. Pass 1's and Step 8's edits all still present and none contradicted.

Changes: §2.9 band 3 ownership comparison waits on the payload where the owning resource is body-named or a shared `/transitions` endpoint must read `to_status` first · §2.9 band 7 pair list extended with the meet's `start_iso`/`end_iso` and the certification's `issued_on`/`expires_on`, date pairs compared as dates · §3.5 `guest_count` floor of 1 is band-5 `ERR_VALIDATION`, ceiling of 6 is `ERR_GUEST_LIMIT_EXCEEDED` · §3.5 the void has no season, posture or standing gate, only the terminal test · §3.6 withdrawal from `WAITLISTED` also releases `ASSIGNED` assignments; promotion fires only from `PENDING`/`CONFIRMED` · §3.6 `expected_swimmers` recorded only; meet window compared at day granularity, inclusive · §3.6 registration resolved before the meet, the registration's own status is not a gate, volunteer assignments carry NO ownership check · §3.6 a second close-roster answers `ERR_ROSTER_ALREADY_CLOSED` ahead of `ERR_INVALID_TRANSITION`, terminal ahead of both · §3.6 `NO_SHOW` against a `SCHEDULED`/`CANCELLED` meet is `ERR_INVALID_TRANSITION` · §3.6 hosting before `end_iso` is `ERR_INVALID_TRANSITION`, two ratio probes named · **§3.6 MISMATCH** meet cancellation releases in `created_at` order and does NOT recompute `volunteer_slots_filled` or slide the meet · §3.6 on confirming a registration `ERR_SEASON_NOT_OPEN` outranks `ERR_ALREADY_TERMINAL`; membership posture tested only on the confirm edge · §3.6 one penalty share per membership, a 0-cent share leaves `balance_due_cents` and `version` untouched · §3.8 cert range failure is `ERR_INVALID_TIME_RANGE` settled before `lifeguard_id` resolves; new cert born with `revoked_reason` null · §3.8 revoking an `EXPIRED` cert is `ERR_INVALID_TRANSITION`, a second revoke `ERR_ALREADY_TERMINAL` · §3.8 revocation's shift cancellations run in `created_at` order, unconditional (no ratio guard), then `scheduled_hours` recomputed · §3.8 shift season window at day granularity, both endpoints inclusive · §3.8 an `INACTIVE` guard on `CONFIRMED` is `ERR_CERT_NOT_VALID_FOR_SHIFT` (roster tested before the wall); early `COMPLETED`/`NO_SHOW` are `ERR_INVALID_TRANSITION` · **§3.7 MISMATCH** the gate wall reordered to the implemented order: `party_privileges` `ERR_VALIDATION` first, household `standing` before membership `access_status`, season window before the zone/capacity pass; window at day granularity; the pass covers this membership's own season only · §3.7 zone conflict reported on the first conflicting row, ahead of the capacity total · §3.7 per-edge narrowing decided from `to_status` before lookup and before ownership · **§3.7 MISMATCH** rejection also raises `account_credit_cents` and does NOT run the §3.4 auto-apply; early `COMPLETED` is `ERR_INVALID_TRANSITION` · §3.7 host-cancel at or after `start_iso` is `ERR_INVALID_TRANSITION` · §3.1 finding narrowing decided before lookup; conditional `remediation_note` `ERR_VALIDATION` after the finding resolves and ahead of the state tests · §3.1 verify-close two-person control settled as soon as the finding resolves · **§3.1 MISMATCH** a finding write advances the season's `version` only where the posture actually moved; verify-close is the sole unconditional exception · §3.9 case narrowing decided before lookup and before ownership · §3.9 segregation settled ahead of the missing-`sanction_type` `ERR_VALIDATION`, both ahead of the state tests · §3.9 closure at or before the ten-day boundary is `ERR_INVALID_TRANSITION` · **§3.10 MISMATCH** `fund`'s optional `season_id` is a cross-check only (the charged season is always `funding_season_id`); a `PROPOSED` draw is `ERR_INVALID_TRANSITION`, a terminal one `ERR_ALREADY_TERMINAL`, both after the version guard · §3.10 a 0-cent draw is legal, promotes `APPROVED -> FUNDED`, advances both versions · §3.10 `IN_PROGRESS` against a `FUNDED` project holding nothing is `ERR_INVALID_TRANSITION` · **§3.10 MISMATCH** on cancellation the season's `version` advances only where cents actually returned.

Pass-1 leads assigned to pass 2: (a) volunteer-assignment ownership — CONFIRMED and pinned; `transition_assignment` and `read_assignment` call `guard(...)` and never `require_owner`, so any authorised `Member` may complete or no-show ANY assignment and read any of them. (b) remainder-to-earliest split — CONFIRMED, already uniquely pinned by §3.6; pass 2 added only the two facts the callsite left silent. Brief-vs-code note: the partition brief listed "reserve contributions" under `routes_deck.py`, but the endpoint actually lives at `routes_seasons.py:211` — pass 2 correctly left it to pass 1/3 rather than reaching outside its partition.

### Pass 3 verbatim summary (15 changes: 10 ambiguity-pins, 5 mismatch-revisions)

No `cp` was run. 457 lines / 142,719 chars -> 457 lines / 148,627 chars (+5,908).

Changes: §3.1 closure cascade order — each hop walks `created_at` ascending, the reservation hop completes (refund + auto-apply) before the shift hop starts, a guard losing two shifts has `scheduled_hours` recomputed once at the end (engine.py:219-248) · **§3.1 MISMATCH** the season's `version` advances when the derivation moves ANY of the four values it maintains (both finding counters, posture, `closure_started_at`), not only the posture (engine.py:181-216) · §3.1 closing an `OPEN` season re-derives the posture onto `CLOSED`, so it stamps `closure_started_at` and fires the whole two-hop closure cascade BEFORE the memberships lapse; a season already `CLOSED` on a critical finding repeats neither · **§3.4 MISMATCH** write-off suspension cancels every future reservation in `REQUESTED` OR `CONFIRMED` (was "confirmed" only) · §3.4 the auto-apply reaches exactly one membership — earliest `created_at` in that season with `dues_status` `INVOICED`/`DELINQUENT` — and stops there whether or not the credit covered it · **§3.6 MISMATCH** the discount ladder: it is the FIFTH and later swimmers that share the capped 25% (PRD said "fourth"; impl gives the fourth 18.75%) · §3.6 a `swim_team_fee_cents`/`volunteer_credits_required` recompute rewrites that field alone; `invoice_total_cents`/`balance_due_cents` are never re-derived after the invoice · §3.6 exactly one sibling promoted per freed slot, and the promoted row's own membership has credits/fee recomputed and `version` advanced in the same request · §3.6 `volunteer_credits_earned` recomputed from scratch and re-capped at ten rather than incremented · **§3.7 MISMATCH** a rejection's credit sits until a later refund's auto-apply; `account_credit_cents` is moved by nothing else (no payment draws on it) · **§3.7 MISMATCH** suspension cancellation covers `REQUESTED` OR `CONFIRMED` future reservations, reconciling §3.7 with §3.9 · §3.7 the refund's `party_charges_owed_cents` subtraction is plain and NOT floored at 0; a pre-paid household goes negative and that negative enters the §3.4 delinquency sum as-is · §3.8 `scheduled_hours` is the sum of already-rounded per-shift `duration_hours` carried to two decimals (`4.0` versus the plain `0` a never-scheduled guard was hired with), retaken in full on every recompute, guard untouched when the total is unchanged · §3.8 the cancellation probe rule in full — strict overlap both ends, past parties included, up to two candidates per reservation clamped into the shift's closed interval, clamped instants outside the reservation's half-open window discarded, duplicates collapsed, each survivor tested with this shift's coverage removed, first failure refuses · §3.9 the cascade fires only where the derived standing actually moves; a re-derivation onto the standing already held runs no cascade and advances `version` only if `conduct_points` changed.

Dispositions of the eight handed-down leads: (1) `refund_reservation` overwriting `refunded_cents` — NOT a silence, every refund path lands the reservation terminal so no row can be refunded twice; the adjacent real gap (unfloored `party_charges_owed_cents`) was pinned instead. (2) `recompute_scheduled_hours` rounding + int/float rendering — PINNED; the `+1e-9` nudge left unpinned as pure float-error defence. (3) `cancellation_preserves_ratio` clamping — PINNED in full. (4) `squad_seq_for`'s `birthdate <=` tie — ALREADY PINNED by §3.6 plus §2.3's insertion-order tie-break, which is exactly `<=`. (5) `recompute_credits_earned` recompute-and-cap — PINNED. (6) `apply_account_credit` stopping at the first match — PINNED, and narrower than the lead (it stops at the first membership that is ALSO `INVOICED`/`DELINQUENT`). (7) `derive_posture`/`harden_standing`/`apply_standing` — partly already pinned (§3.9's three-candidate max and rank order), partly pinned by pass 3 ("cascade only on arrival"); the `derive_posture` half produced the §3.1 version mismatch fix. (8) `_reserve_booked` flag — NOT a silence, §3.4 and §3.10 both pin "exactly once per membership" and the flag is response-stripped and unobservable; left unpinned, agreeing with pass 1.

Final-pass consistency cleanup (pass 3 acting as last reader): pass 2's "advance the season's `version` only if the derivation actually changed the posture" contradicted `derive_posture`, which also reports changed on a finding-counter move — revised. Pass 2's "until a payment or a later auto-apply reaches it" implied a payment could draw down `account_credit_cents`; nothing does — revised. §3.7 vs §3.9 disagreed (pre-existing in PRD_FINALIZED, not introduced by a pass) on whether the suspension cascade cancels `REQUESTED` reservations; §3.7 and §3.4 now match §3.9 and the implementation.

Closing statement: `engine.py` has no PRD-silent observable behavior remaining — all 11 calculations, both ratio probes, all four cascades, the dues assessment, the pricing ladder, the waitlist selector and every derived counter/standing rule are pinned uniquely. Deliberately left unpinned, each unobservable through the API: `ceil_hours`' seconds->minutes pre-rounding in `price_party` (identical to a direct ceiling at millisecond input precision); `apply_cert_change`'s internal ordering (its `INACTIVE -> ACTIVE` branch is unreachable); `expel_household_cascade` marking `TERMINATED` before running the suspension effects (nothing inside reads `access_status`, so end state and version counts are identical); `assess_dues`' unreachable guards (`join_date` is constrained to the season window); the `created_at` order of the expulsion waitlist-withdrawal hop (every row lands on the same status with one version bump).

### Orchestrator final verification

- `PRD.md` 455 lines / 118,096 bytes -> `PRD_FINALIZED.md` 457 / 120,357 -> `PRD_COMPLETED.md` 457 / 148,627. All three md5s distinct. `cmp` confirms `PRD.md` != `PRD_FINALIZED.md` and, critically, `PRD_FINALIZED.md` != `PRD_COMPLETED.md` — so the Step 9 scan genuinely ran; the known "byte-identical PRD_COMPLETED means the scan never happened" failure did not occur.
- All 8 `results.$i.json` present and re-read directly by the orchestrator: `274/274` in every round, `all green: True`.
- `test_helpers/` and `test_suite/` at the task root, no strays under `workspace/`.
- `find . -name worklog.md` returns exactly one file, `./worklog.md` — no cwd-drift copy under `workspace/`.
- `grep` for `sqlite3` / file-write / `json.dump` across `workspace/implementation/*.py` returns nothing: storage is in-memory only, so per-test-server isolation wipes all state on every `start.sh` re-invocation.
- Two orchestrator-owned artifacts remain in `workspace/` beyond the skill's manifest and are intentional: `sweep.sh` (the Step 7 sweep script, written as a file specifically to avoid the inline-`setsid` quoting bug that injects literal quotes into `--start-command`) and `sweep.log` (spliced 8-round output, retained only as evidence that the sweep ran; never used for diagnosis).

**PIPELINE COMPLETE.** Steps 1-9 all executed; `workspace/PRD_COMPLETED.md` written.
