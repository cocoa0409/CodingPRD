# Worklog — task_2867_comprehensive_plan_update_public_engagement

## Step 1: Create task directory — 2026-09-05T08:22:28.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2867_comprehensive_plan_update_public_engagement` and its `workspace/` subdirectory. Index 2867 was pre-assigned by the invoking pipeline (no auto-allocation scan performed, per orchestration instructions — up to 32 concurrent pipelines run on this host and scanning would collide).

## Step 2: Generate scaffold — 2026-09-05T10:30:48.000Z

All three scaffold artifacts are complete and lint-clean.

**Files** (`/home/ubuntu/github/CodingPRD/tasks/task_2867_comprehensive_plan_update_public_engagement/`)
- `SCAFFOLD.yaml` — 3131 lines (14 top-level keys, §1.0–§1.7; neither `scaffold_difficulty_design` nor `scaffold_corner_design` present)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2973 lines (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4979 lines (single key `scaffold_corner_design`)

**Lint verdict (verbatim)**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2867_comprehensive_plan_update_public_engagement/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2867_comprehensive_plan_update_public_engagement/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2867_comprehensive_plan_update_public_engagement/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    59
  §1.1 entities declared:     14
  §1.8 instances scanned:     25
  §1.9 instances scanned:     45
  Calls scanned (§1.8+§1.9):  1252

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Domain model shape**: 14 entities (PlanUpdate, InventoryDataset, GrowthScenario, HousingAllocation, PlanElement, ConsistencyLink, Venue, EngagementActivity, ParticipationRecord, EnvironmentalReview, PlanAlternative, Hearing, Amendment, ImplementationAction) · 59 endpoints under `api_prefix: /planning` · 11 state machines · 12 calculations · 28 validation priorities · 85 error codes · 5 peer roles (PlanningStaff, PlanningDirector, EnvironmentalConsultant, CommissionClerk, StateReviewer) with segregation of duties · 2 OCC concurrency rules (`scenario-create-stale-inventory`, `amendment-create-stale-element`, both 412).

**§1.8 difficulty rules — 25 instances**: dual_variant_calculation 2 · combinatorial_formula 3 · non_linear_state_machine 2 · transitive_cascade 3 · priority_pair_validation_conflict 4 · boundary_precision_check 3 · cross_entity_state_dependency 3 · resource_temporal_overlap 3 · compensating_invariant 2.

**§1.9 corner sections — 53 instances (45 with test recipes, 8 `excluded_because` stubs)**: entities 11 · state_machines 12 (9+3) · calculations 6 (4+2) · validations 6 (5+1) · endpoints 5 · errors 4 · rbac 3 · complexity_layers 5 (3+2) · consistency_model 1. No `bulk_action` instance because the API declares no bulk endpoint; every stub cites an existing §1.8 instance by name.

**Error coverage**: all 85 catalogued `ERR_*` ids appear in §1.8/§1.9 (`comm -23` over the two scratch files in `/tmp/task_2867_scaffold/` returns empty). The last nine holdouts were closed by the new rbac section (ERR_UNAUTHENTICATED), the heavy amendment/OCC chain (ERR_STALE_ELEMENT_VERSION, ERR_CROSS_PLAN_AMENDMENT, ERR_AMENDMENT_NOT_PROPOSED, ERR_AMENDMENT_NOT_ADOPTED, ERR_UNRESOLVED_AMENDMENTS, ERR_POLICY_COUNT_NEGATIVE), the inventory OCC instance (ERR_STALE_INVENTORY_VERSION) and the derived-field instance (ERR_TARGET_ELEMENT_NOT_REVIEWABLE).

One SCAFFOLD.yaml correction was made this session: StateReviewer's §1.7 `shared_operations` was missing `POST /_clock/set_current_utc`, which §1.5 grants to all five roles.

**Orchestrator post-step correction (not by the subagent):** the difficulty directive line `Generate task harder than expert level!` had leaked verbatim into SCAFFOLD.yaml's top-level `scenario:` key, from which it would reach PRD.md via the doc generator. Stripped that single line from `scenario:` before Step 4; a repo-wide grep for "harder than expert" over the task dir now returns nothing. The scenario body itself is unmodified.

## Step 3: Copy shared files — 2026-09-05T10:30:48.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T10:47:00.000Z

PRD generated and verified complete.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2867_comprehensive_plan_update_public_engagement/workspace/PRD.md` — **540 lines / 14,562 words / 106 KB**. Written incrementally (1 Write + 6 heredoc appends), no truncation; the file ends on the last row of the §5 error table (`ERR_INDICATOR_OFF_TRACK | 409`), a completed final section, with no audit footer.

**Section outline**
- `# Comprehensive Plan Update API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 11 subsections: 2.1 User and Role-Based Access Control; 2.2 API Response Structure (verbatim block); 2.3 Pagination; 2.4 Record Identity, Timestamps and Versioning; 2.5 Version Pinning on Cross-Aggregate Writes; 2.6 Numeric Precision and Rounding; 2.7 Segregation of Duties; 2.8 Validation Order (28-rung ladder); 2.9 The Compliance Posture Gate; 2.10 Derived Counters and Conservation Invariants; 2.11 Reading Nested Collections
- `## 3. Business Logic & Workflows` — 9 subsections: 3.1 Opening a Plan Cycle / Existing-Conditions Record; 3.2 Growth Scenarios (capacity, demand, adoption); 3.3 Housing Allocations and the Capacity Waterfall; 3.4 Statutory Elements and the Director Review Loop; 3.5 The Internal-Consistency Network; 3.6 Public Engagement, Venue Booking and the Equity Share; 3.7 Environmental Review, Alternatives and the Preferred-Alternative Selector; 3.8 Filing with the State and the Determination Cascade; 3.9 Adoption Hearings, Amendment Tracking and the Implementation Program
- `## 4. Endpoint Definitions` — 4-column table, **59 rows** (verified count and column arity)
- `## 5. Error Code Catalogue` — 2-column table, **85 rows** (statuses: 1×401, 3×403, 11×404, 64×409, 2×412, 4×422)

**Hard Contract reports (checked mechanically, not just by eye)**
- **Contract 1 — Field-Name Coverage: PASS.** All 122 `entities[].fields[].name` identifiers and all 83 distinct endpoint `input`/query/path/computed-output identifiers appear verbatim in backticks (0 missing). All enum literal tokens also appear (0 missing). Note the checker must strip fenced code blocks first — the §2.2 JSON fences otherwise break backtick parity and produce a false 137-missing result.
- **Contract 2 — Rule Coverage: PASS.** All 31 state tokens across the 11 state machines (PlanUpdate, InventoryDataset, GrowthScenario, PlanElement, ConsistencyLink, EngagementActivity, EnvironmentalReview, PlanAlternative, Hearing, Amendment, ImplementationAction) are present. All 28 validation priorities are mapped to exactly 28 ordered rungs in §2.8, and all 84 error IDs referenced by validations appear inside that ladder. All 85 error IDs appear in the prose *before* §5, not only in the catalogue. Both OCC rules, both conservation invariants, all 12 calculations (constants rendered as prose values, e.g. 85 percent market factor, 1.45 jobs per household, 30/20/20/30 tier shares, 35/25/20/20 impact weights, 15/10 percent credit tiers, 40.0 percent equity floor) and every cross-entity cascade are covered, including the 5-link DEFICIENT cascade, the 5-link amendment-adoption cascade and its 4-link rescission compensation, and the COUNCIL-DENY demotion cascade.
- **Contract 3 — §3 Path Purity: PASS.** 0 violations in §3: no backticked token starts with `/`, is a bare HTTP method, or combines method+path. The only method/path tokens in the document outside §4 are in §1–§2, where they are permitted (`/planning`, `POST /planning/amendments`, `POST /planning/growth-scenarios` in the §2.5 OCC discussion).

Also removed the four hedge words a style check would flag ("approximately", "typically", plus two idiomatic "about/around" uses reworded).

**One scaffold gap you should know about:** `IMPLEMENTATION_DUE_DAYS` has **no numeric value anywhere in SCAFFOLD.yaml** (the transition only says `due_at := adopted_at + IMPLEMENTATION_DUE_DAYS days`). Since the PRD must be implementable, I pinned it in prose as **365 days** ("the fixed implementation lead time of 365 days", §3.9). If the withheld design indices pin a different figure, this is the one line to reconcile.

**Orchestrator verification (post-step):** (a) truncation guard — `tail -25` confirms the document ends on the final `ERR_INDICATOR_OFF_TRACK | 409` table row, a real section boundary, so no regeneration was needed; (b) difficulty-directive leak — `grep -c "harder than expert" workspace/PRD.md` returns 0; (c) the doc generator's flagged `IMPLEMENTATION_DUE_DAYS` judgement call was reconciled by the orchestrator against the withheld index: `SCAFFOLD_CORNER_DESIGN.yaml:1509` asserts `due_at == "2027-10-19T18:00:00.000Z" (adopted_at + IMPLEMENTATION_DUE_DAYS == 365 days)`, so the PRD's 365-day pin agrees with what the tests will assert. No edit required.

## Step 6: Generate implementation — 2026-09-05T11:22:00.000Z

(Launched concurrently with Step 5 in a single assistant message, so the implementation generator had physical isolation from `test_suite/` — that directory did not exist when it started. Step 6 returned first; Step 5 was still running at the time of this entry.)

The implementation is complete and verified.

## Deliverable
`/home/ubuntu/github/CodingPRD/tasks/task_2867_comprehensive_plan_update_public_engagement/workspace/implementation/`

## Per-file line counts (3,098 total)
| File | Lines |
|---|---|
| `app.py` | 68 |
| `constants.py` | 114 |
| `db.py` | 172 |
| `errors.py` | 112 |
| `response.py` | 113 |
| `serial.py` | 180 |
| `validation.py` | 147 |
| `routes/plans.py` | 245 |
| `routes/capacity.py` | 257 |
| `routes/elements.py` | 261 |
| `routes/engagement.py` | 239 |
| `routes/environmental.py` | 208 |
| `routes/hearings.py` | 358 |
| `routes/implementation.py` | 123 |
| `services/calc.py` | 167 |
| `services/planservice.py` | 179 |
| `services/repo.py` | 144 |
| `start.sh` | 10 |
| `requirements.txt` | 1 |
| `routes/__init__.py`, `services/__init__.py` | 0 |

## Endpoints: 59/59, exact match
I parsed the PRD §4 endpoint table and diffed it against `application.url_map`: 59 PRD entries, 59 implemented, **zero missing and zero extra** (the count includes `POST /_clock/set_current_utc`).

## Coverage
- **State machines (11):** PlanUpdate (DRAFTING→STATE_SUBMITTED→STATE_CERTIFIED→COMMISSION_RECOMMENDED→ADOPTED plus the deficiency and council-denial loops back), InventoryDataset (+ supersession cascade to sibling datasets and their DRAFT scenarios), GrowthScenario, PlanElement (incl. escalation at `revision_round == 2` and the system-driven APPROVED→REVISION_REQUESTED / APPROVED→ADOPTED edges), ConsistencyLink (OPEN/STALE→CLEARED→STALE loop, CLEARED→OPEN on demotion), EngagementActivity, EnvironmentalReview, PlanAlternative (EVALUATED/PREFERRED/SUPERSEDED), Hearing (incl. SCHEDULED↔BLOCKED posture cascade, gavelled hearings never retro-blocked), Amendment (PROPOSED→ADOPTED→RESCINDED, WITHDRAWN), ImplementationAction (PENDING→SCHEDULED→COMPLETED with `due_at = adopted_at + 365d`).
- **Calculations (12):** gross/net land capacity, projected demand (trend + job-driven + POLICY max, vacancy allowance), capacity gap, income-tier waterfall with per-tier rounding and downward carryover, shortfall, participation weighting (base 1.0 / interpreter 2.0 on TARGETED_OUTREACH), activity and plan equity share, alternative raw/credit/net impact scoring and ranking, compliance-posture ladder, indicator on-track, plan derived counters (all 7 recomputed from scratch). Decimal + ROUND_HALF_UP throughout.
- **Validation rungs:** all 28 in PRD 2.8 order — auth → role → body/shape → enums → FK existence → cross-aggregate ownership → version pinning (412) → state preconditions → segregation of duties (3 sites, always after state) → uniqueness → temporal/graph/capacity rules. All 85 catalogue error codes are mapped to their pinned HTTP statuses in `errors.py`.

## Smoke check
1. **End-to-end in-process run** (`/tmp/task_2867_impl/smoke.py`, ~130 status/value assertions) drives the full lifecycle — plan → 4 inventories + certify cascade → TREND/POLICY scenarios → allocations → adopt → 5 elements → links → reviews → venue/activity/participation → EIR with alternatives → state filing/determination → commission hearing → amendment adopt/rescind → recommend → council adopt → monitoring action complete — plus negative paths (SoD, stale versions, cycles, venue/hearing conflicts, notice lead, auth, pagination bounds, 404 envelopes). Result: **0 failures.** Reference figures confirmed: GROSS 11700, NET 7115, waterfall 3510/2340/2340/3510, equity 40.0 and 71.4, alternative 70.00/10.50/59.50, conservation invariants hold on cancel and on amendment rescind.
2. **Real process on PORT=18867** via `bash start.sh`: boots in <4s, correct envelope/meta shape, 401 without headers, 422 on `limit=0`, 404 with `ERR_PLAN_UPDATE_NOT_FOUND`. Killed by listener PID from `lsof -tiTCP:18867` (never a broad pkill); relaunch returned an empty `plan-updates` list, confirming in-memory-only storage with zero seeding and a full state wipe on every reboot.

One test-expectation bug I found and fixed in my own smoke script (not an implementation bug): amendment adoption stales only links whose **target** is the amended element, per PRD §3.9 step 2, so a plan with no inbound links to the amended element legitimately stays `CLEAR`.

`__pycache__` directories were removed; `start.sh` is `chmod +x`, reads `$PORT`, binds 0.0.0.0, and `exec`s in the foreground with a guarded (missing-only) pip install to avoid per-test-reboot contention.

## Step 5: Generate unit tests — 2026-09-05T11:57:00.000Z

(Launched concurrently with Step 6 in a single assistant message; Step 5 finished second. Entry placed after Step 6's for chronological honesty about completion order.)

The suite is complete and statically green.

## Output locations (task root, nothing under `workspace/`)

`/home/ubuntu/github/CodingPRD/tasks/task_2867_comprehensive_plan_update_public_engagement/`

**`test_helpers/`** (Stage 1, unchanged since it was frozen): `__init__.py` 60, `api_client.py` 476, `api_errors.py` 227, `assertions.py` 370, `constants.py` 268, `factories.py` 387, `fixtures.py` 610, `test_users.py` 67, `types.py` 252 — 2717 lines.

**`test_suite/`**: `conftest.py` 18, then (lines / test functions)
test_01_capacity_and_demand_variants 605/15, test_02_review_and_hearing_forks 251/6, test_03_cascades 497/9, test_04_rule_precedence 415/12, test_05_inclusive_boundaries 345/9, test_06_cross_entity_gates 380/9, test_07_temporal_overlap 491/11, test_08_conserved_quantities 316/6, test_09_entity_shapes 845/21, test_10_state_machine_walks 902/15, test_11_calculation_branches 406/7, test_12_validation_gates 1402/30, test_13_endpoints 800/16, test_14_errors 1023/29, test_15_rbac 469/11, test_16_version_and_counter_layers 783/14, test_17_consistency_model 259/3 — **10 189 lines, 223 test functions, 250 pytest items after parametrisation.**

## Design coverage

- **Depth index: 25/25 live instances translated, all with >=2 tests** (most with 3). Nothing skipped.
- **Breadth index: 45/45 non-stub instances translated, all with >=1 test.** The 8 `excluded_because` stubs were not translated (verified programmatically — no test carries a stub tag).
- Every test docstring ends with exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line, and every tag resolves to a real live instance in the yamls.

## Verification performed

`/tmp/task_2867_tests/check.py` (reusable) re-parses both design yamls and every test file: 0 problems — no missing/duplicated/misplaced tags, no unknown or stub tags, no envelope double-unwrap (`validate_*(...)["data"]`), no scaffold vocabulary outside tag lines. Plus: `py_compile` clean on all 26 files, `pyflakes` clean (0 findings), `pytest --collect-only` imports all 17 modules and collects 250 items, no `skip`/`xfail`/`TODO` anywhere, no date-only datetime literals, and **all 225 quoted PRD citations verified as verbatim whitespace-normalised substrings of `workspace/PRD.md`** (I fixed 12 ASCII `->` arrows and 2 truncated quotes to reach this). Nothing was created, read, or written under `workspace/implementation/`; `test_helpers/` mtimes confirm no generator touched Stage 1.

## Findings worth carrying into the implementation/fix steps

1. **Design-index arithmetic defect (confirmed, worked around):** several instances pair `infrastructure_constrained_acres: 100` with `NET_CAPACITY == 7115`; the PRD's formula gives 6503 for 100 acres. All tests use the PRD's own reference row (400/250/**60**/18 -> GROSS 11700, NET 7115), so every literal is PRD-derived while each instance keeps its real subject.
2. **`jurisdiction_code "CA-0451"` in the design indices is invalid** under PRD §3.1 (2–12 uppercase alphanumerics); the suite uses `CA0451`. An implementation that accepts the hyphenated form will fail the `ERR_INVALID_REQUEST` checks.
3. **Design index vs PRD error id:** a projection pinning another plan's acreage dataset is `ERR_CROSS_PLAN_LINK` per §3.2, not `ERR_INVENTORY_TYPE_MISMATCH`; the PRD's id is what the suite asserts. Likewise `ERR_HORIZON_YEAR_MISMATCH` is 422 (catalogue), not 409.
4. **Exact-decimal arithmetic is load-bearing:** `raw_impact_score` 0.35*49.9 + 0.25*50 + 0.2*50 + 0.2*50 = 49.965 -> **49.97** under §2.6 half-up; a float implementation emits 49.96 and will fail. Same class of risk for the housing waterfall (pool 7115 -> 2135/1423/1423/2135 = 7116, deliberately one over the pool).
5. **Claims deliberately not asserted** because the PRD does not uniquely derive them (gaps left as gaps, no weakening): posture immediately after an amendment adoption (§3.7 step 4 says `CONSISTENCY_HOLD`, the §2.9 ladder says `CLEAR`), the DEFICIENT cascade's "SCHEDULED hearings blocked" link (no PRD-reachable state has both), empty-body PATCH acceptance, `updated_at > created_at`, activity `completed_at`, absence of DELETE endpoints, and null-vs-zero scenario fields on an empty compliance summary.
6. Two hearing/precedence recipes claimed an ordering the PRD contradicts; the tests assert the error id only and make no precedence claim there.

I did not append to `worklog.md` — say the word if the pipeline expects a Step 5 entry and I'll add one.

**Orchestrator note:** the Step 5 entry is this one, written by the orchestrator as the skill requires (subagents never write worklog.md). Output-path check passed — `test_helpers/` and `test_suite/` are both at the task root, not under `workspace/`, so no relocation was needed before Step 7.

## Step 7: Run tests and iterate — 2026-09-05T12:25:00.000Z

All 8 rounds are fully green at 250/250.

## Summary

**Iterations run:** 2 sweeps (baseline + confirming).

**Baseline sweep:** 246/250 in all 8 rounds — 4 deterministic failures, zero flakiness, all in `test_09_entity_shapes.py`. All four tripped on the same root cause: they pinned `created_at` / `updated_at` to the **logical clock** value (`2026-08-01T00:00:00.000Z`, or a clock instant set mid-test), while the implementation stamps them from wall time.

**STEP 1 verdict — unique derivability broken (timestamp-source silence).** PRD §2.4 describes `created_at` only as "an ISO 8601 UTC timestamp with three fractional digits, stamped once at creation and never modified" and `updated_at` only as "refreshed on every mutation of that row" — neither sentence names a source. The logical-clock paragraph scopes itself explicitly: "Every **deadline, notice period, comment period and activity-end comparison** in this specification is evaluated against the logical clock." Every field the PRD *does* clock-stamp is named verbatim — `opened_at`, `closed_at`, `circulated_at`, `certified_at`, `adopted_at`, `latest_reading_at`, each "stamped with the logical clock instant". `created_at`/`updated_at` are conspicuously absent from that enumeration, so a faithful PRD-only implementer can legitimately read it as exhaustive and use wall time. Two admissible implementations exist -> the clock-pinned assertions had to go. Per STEP 1c the tests were **split**, not deleted: only the uncovered clock-pin assertions were removed; every PRD-covered assertion in each test was kept (and now actually executes, since it previously sat below the tripping line).

**Tests deleted:** none. Four assertions removed / re-expressed under partial-coverage handling (all in `test_suite/test_09_entity_shapes.py`), category **DEFAULT-VALUE / COMPUTED-FIELD SILENCE — timestamp source unstated**; scaffold rules that drove them: `Corner/entities/plan_update_creation_returns_every_declared_field`, `Corner/entities/plan_update_retrieval_round_trips_stored_values`, `Corner/entities/element_system_fields_are_server_assigned`.
- `test_plan_update_creation_returns_its_declared_inputs_and_system_status` — dropped `created_at == CLOCK_STARTUP`; kept `assert_versioned_row` (which still enforces the PRD-covered three-digit-instant format) and `assert_created_equals_updated`.
- `test_plan_update_read_round_trips_and_never_refreshes_updated_at` — replaced the two `CLOCK_STARTUP` pins with the relative form (`fetched["created_at"] == created["created_at"]`, same for `updated_at`), which is the faithful expression of the test's own covered rule that a read is not a mutation.
- `test_element_creation_stamps_the_author_and_the_opening_workflow_fields` — dropped `created_at == CLOCK_STARTUP`.
- `test_element_revision_advances_version_and_leaves_the_stamped_fields_frozen` — replaced `updated_at == "2026-08-03T09:30:00.000Z"` with the covered rule "refreshed on every mutation" (`revised["updated_at"] != element["updated_at"]` plus three-digit-instant format), and made the `created_at` check relative to the pre-revision row ("stamped once at creation and never modified").

**Fixes applied to `test_helpers/`:** none — the fixtures, factories and role-header builders were all PRD-faithful.

**Fixes applied to `implementation/`:** none. No implementation defect was found; per the cardinal rules I did not add logical-clock stamping of `created_at`/`updated_at`, since no verbatim PRD sentence requires it.

**Final sweep evidence** (`results.1..8.json`): 250/250, 250/250, 250/250, 250/250, 250/250, 250/250, 250/250, 250/250 — 0 failed, 0 errors in every round.

Operational notes: both sweeps were launched via the pre-written `workspace/sweep.sh` under `setsid`; no `Terminated` server logs or same-instant round deaths appeared, and no round showed load-induced timeout/connection flakiness. The single-behaviour spot-check used a task-scoped server on port 18267, killed by explicit pid. `worklog.md` was not touched.

**Orchestrator verification (post-step):** the claimed clean sweep was re-verified directly rather than taken on trust (a known failure mode is a Step 7 agent reporting a green sweep with no artifacts on disk). All eight `workspace/implementation/results.$i.json` exist, are ~74 KB each, and carry the same 12:21 mtime; parsing each independently yields `passed=250 total=250 failed=0 errors=0` for rounds 1–8. Step 8 is therefore NOT skipped — the skip condition requires zero fixes in every layer, and Step 7 applied 4 `test_suite/` fixes (0 deletions, 0 `test_helpers/`, 0 `implementation/`).

## Step 8: Finalize PRD — 2026-09-05T12:28:00.000Z

Done. `PRD_FINALIZED.md` is a two-sentence-level patch of `PRD.md`, both edits confined to §2.4.

**Line counts:** PRD.md 540 lines / 106,036 bytes -> PRD_FINALIZED.md 540 lines / 106,421 bytes. Lines changed: 2 of 540 (0.37% of lines; +0.36% bytes). No lines added or removed.

**Changes**

- §2.4 (Record Identity, Timestamps and Versioning), line 86 — revise — appended to the `created_at` sentence that it is read from the server's real wall-clock time at the moment of the write, not from the logical clock defined at the end of the section, and is therefore unrelated to the clock's current position — `implementation/db.py:147-156` (`new_row` -> `now = wall_now()`), `implementation/db.py:90-91`.
- §2.4, line 88 — revise — inserted a clause into the `updated_at` sentence: likewise read from real wall-clock time rather than the logical clock, and carrying exactly the same instant as `created_at` on a row that has not yet been mutated — `implementation/db.py:159-163` (`bump` -> `wall_now()`), `implementation/db.py:149-152` (single `now` shared by both fields at creation).

**Per-edit pre-edit search log**

Edit 1 — `created_at` source.
(a) Subject: where every row's `created_at` value comes from, and whether any entity or endpoint stamps it differently.
(b) Paths enumerated: repo-wide grep for `created_at|updated_at|new_row|bump(|wall_now|clock_now|utcnow|now(|isoformat` across all non-`__pycache__` `.py`. Read `db.py` in full (`parse_instant`, `iso`, `wall_now`, `clock_now`, `new_row`, `bump`, `sort_rows`); `serial.py:106-122` (the one serialization site rendering `created_at`/`updated_at`, and the Venue/ParticipationRecord exemption); every `new_row` callsite — `routes/plans.py:33`, `routes/capacity.py:51,145,242`, `routes/elements.py:37,190`, `routes/engagement.py:31,80,200`, `routes/environmental.py:30,181`, `routes/hearings.py:54,205`, `routes/implementation.py:37`; all clock-sourced stamps to confirm they are disjoint fields only (`opened_at`, `closed_at`, `adopted_at`, `circulated_at`, `certified_at`, `latest_reading_at` in `routes/hearings.py:92,132,146`, `routes/environmental.py:83,147`, `routes/implementation.py:93`); `response.py:23` (`api_request_timestamp`, also wall time — left untouched as out of scope but not contradicted by the new wording).
(c) Adjustment: no path uses the logical clock for `created_at`, including the unversioned `Venue`/`ParticipationRecord` rows, so the claim could stay universal. I scoped the cross-reference as "the logical clock described at the end of this section" rather than naming clock-stamped fields, so the sentence makes no claim about `opened_at`/`certified_at`/`latest_reading_at` etc., which remain clock-sourced per the untouched prose. I deliberately did not touch §2.3's "ordered by `created_at` ascending" even though `sort_rows` adds an insertion-sequence tiebreaker (`db.py:168`) — out of Step 7 scope, and the new wording says nothing about ordering.

Edit 2 — `updated_at` source plus its value on an unmutated row.
(a) Subject: the source of every `updated_at` refresh, and whether `updated_at == created_at` holds for all freshly created rows anywhere in the impl.
(b) Paths enumerated: every `bump()` callsite (~60, in `routes/plans.py`, `routes/capacity.py`, `routes/elements.py`, `routes/engagement.py`, `routes/environmental.py`, `routes/hearings.py`, `routes/implementation.py`, `services/planservice.py:68,75,115,155,163`) — all route through `db.bump` -> `wall_now()`, none assigns `updated_at` directly. To validate the "same instant on an unmutated row" clause I specifically hunted for a create path that bumps its own new row in the same request: read `services/planservice.py` in full (`refresh`, `block_scheduled_hearings`, `unblock_hearings`, `run_waterfall`, `demote_approved_elements` — all iterate sibling/parent rows), and `routes/capacity.py:227-257`, where the allocation create passes `skip_bump_id=row["id"]` into `run_waterfall` so the new row stays at v1; also checked hearing create (`routes/hearings.py:40-68`, no `refresh` call) and the remaining creates, whose subsequent `bump`s target only parents/siblings.
(c) Adjustment: phrased the equality as holding "on a row that has not yet been mutated" rather than "at creation", so it stays true for the unversioned exempt entities (which have no `updated_at` at all) and cannot be read as forbidding a same-request cascade from later advancing `updated_at`; it also stays consistent with the pre-existing "starts at 1 on creation" version rule.

**Orchestrator verification (post-step):** `diff PRD.md PRD_FINALIZED.md` is 8 lines total — exactly the two §2.4 line replacements described above (86c86, 88c88), no other hunks, no section added or dropped, line count unchanged at 540. The diff is on-target for the sole Step 7 signal (timestamp source) and shows no padding with out-of-scope edits.

## Step 9: Complete PRD — 2026-09-05T13:12:00.000Z

Run as **three sequential module-partitioned passes over one shared `PRD_COMPLETED.md`** rather than a single scan: a one-shot Step 9 on a PRD this size reliably no-ops and leaves the output byte-identical to its input. Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden to copy and edited in place. Each pass was handed the previous passes' out-of-partition observations so nothing fell between the seams.

**Partition:** pass 1 = app/db/constants/errors/response/serial/validation + routes/plans + routes/capacity (all cross-cutting plumbing: envelope, pagination/ordering, error-status mapping, validation-ladder mechanics, serialization, logical clock, id minting, version/OCC). Pass 2 = routes/elements + routes/engagement + services/calc (element review loop, consistency links, engagement/equity, all twelve formulas). Pass 3 = routes/environmental + routes/hearings + routes/implementation + services/planservice + services/repo (environmental review/alternatives, hearings/amendments, implementation program, and all shared cascade/refresh machinery).

**Totals: 80 edits — 64 ambiguity-pins, 13 mismatch-revisions, 3 self-corrective edits by pass 3 to its own earlier wording.** `PRD_FINALIZED.md` 540 lines / 106,421 chars -> `PRD_COMPLETED.md` 542 lines / 129,102 chars (+2 lines, +22,681 chars). Nearly every edit is in-paragraph, which is why the line count barely moves.

### Pass 1 — core plumbing + plans + capacity (28 edits: 23 ambiguity, 5 mismatch)

- 2.1 — revise — ambiguity — a header present but empty/whitespace-only counts as absent for `ERR_UNAUTHENTICATED` — response.py:57-62
- 2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alphanumeric chars, minted for error responses too — response.py:13,17
- 2.2 — insert — ambiguity — every declared field appears in every serialization; inapplicable fields emitted as `null`, never omitted — serial.py:110-124
- 2.2 — revise — ambiguity — pagination `meta` fields are absent entirely from single-object, computed-read and error responses — response.py:20-24,37-44
- 2.2 — revise — **mismatch** — error envelope covers 5xx, not just 4xx (`ERR_INTERNAL` uses it) — app.py:56-58, errors.py:100
- 2.3 — insert — ambiguity — non-integer `limit`/`offset` is the same 422; empty value takes the default; `offset` has no upper bound — response.py:76-97
- 2.3 — revise — ambiguity — `created_at` ties are broken by server creation order, making list ordering total and stable — db.py:166-168
- 2.3 — insert — ambiguity — filters are plain equality tests; an unrecognised enum value yields an empty page rather than 422; empty value ignored — response.py:100-107
- 2.4 — insert — ambiguity — all emitted timestamps render exactly 3 fractional digits, finer precision **truncated** not rounded — db.py:80-87
- 2.4 — revise — **mismatch** — accepted instant grammar is lenient: 1-9 or zero fractional digits, `Z` or a zero UTC offset; date-only/naive/non-zero-offset/non-string rejected — db.py:51-77
- 2.4 — revise — ambiguity — `to_iso8601` is required (null/malformed -> 422); `data` carries `current_utc` alone — app.py:33-40
- 2.5 — revise — ambiguity — `expected_inventory_version` is an integer of at least 1 — capacity.py:121
- 2.6 — insert — ambiguity — numerics are JSON numbers never strings; trailing zeros insignificant (`59.50` on the wire as `59.5`) — db.py:126-132
- 2.8 rung 4 — insert — ambiguity — four uniform mechanics: missing/empty body = `{}`; JSON `null` == omitted; boolean never a number and fractional never an integer; strings untrimmed but blank-rejected — validation.py:19-31,34-39,60-70
- 2.8 rung 4 — revise — ambiguity — datetime clause now defers to 2.4's accepted forms instead of restating the strict 3-digit form — validation.py:121-130
- 2.8 rung 5 — revise — ambiguity — a body FK that is absent/`null`/non-string fails rung 4, not rung 5 — validation.py:42-57, repo.py:22
- 2.9 — revise — **mismatch** — posture is also recomputed at plan creation and on state *filings*, not only determinations — plans.py:54,119
- 2.11 — revise — ambiguity — `missing_element_types` in statutory order; the capacity trio is `null` with no adopted scenario; payload bears no `id`/`created_at`/`updated_at`/`version` — plans.py:169-183, planservice.py:174-179
- 3.1 — revise — ambiguity — a LAND_USE dataset stores `record_count` 0 and *ignores* a supplied one (asymmetric with acreage, which is rejected) — capacity.py:38
- 3.2 — insert — ambiguity — scenario body FKs resolve plan-then-inventory, so both unknown reports `ERR_PLAN_UPDATE_NOT_FOUND` — capacity.py:130-131
- 3.2 — insert — ambiguity — adoption's response carries the scenario, not the plan — capacity.py:222
- 3.3 — insert — ambiguity — allocation allowed at any non-`ADOPTED` plan status; created row returned at `version` 1 already carrying its four waterfall figures; plan `version` always +1 — capacity.py:237,254-257
- 3.8 — revise — ambiguity — `submission_note` is 1-2000 chars, whitespace-only accepted, zero-length rejected, bodyless request fine — plans.py:87
- 3.8 — revise — **mismatch** — an `ADOPTED` plan filing reports `ERR_PLAN_ALREADY_ADOPTED`, not `ERR_PLAN_NOT_DRAFTING` — plans.py:89-91
- 3.8 — revise — ambiguity — a resubmission *retains* the failed round's `state_findings`; only a first filing clears them — plans.py:115-118
- 3.8 — revise — ambiguity — `findings` required, <=4000 chars, may be blank; `deficient_element_types` duplicates collapsed, shape-checked but inert on `CERTIFIED` — plans.py:130-135
- 3.8 — insert — **mismatch** — a determination against an adopted plan reports `ERR_PLAN_NOT_SUBMITTED` (no terminal-plan guard on this endpoint) — plans.py:137-138
- 5 — insert — ambiguity — `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405), `ERR_INTERNAL` (500) live outside the catalogue but use the same envelope; trailing slashes accepted — app.py:46-58, errors.py:98-100

### Pass 2 — elements + engagement + calc (19 edits: 17 ambiguity, 2 mismatch)

- §2.8 rung 4 — revise — **mismatch** — pass 1's universal "a body that is not parseable JSON ... violates this rung" is false at endpoints that declare no body fields (they never read the body at all: garbage body to `submit-review` returns 200, verified live). Qualified with a one-clause exception — routes/elements.py:91, routes/engagement.py:129
- §3.2 (projected demand) — insert — ambiguity — the `POLICY` driver tie is immaterial, either selection gives the same figure — services/calc.py:42
- §3.4 (drafting) — insert — ambiguity — `policy_count` has no upper bound, and a negative value at creation or revision is `ERR_INVALID_REQUEST`, not `ERR_POLICY_COUNT_NEGATIVE` (verified live) — routes/elements.py:26,66
- §3.4 (revision) — insert — ambiguity — "any combination" includes none: a bodyless revision is accepted and still transitions + bumps `version`; `consistency_status` survives untouched; no plan counter/posture/`version` moves — routes/elements.py:63-87
- §3.4 (submit) — insert — ambiguity — the `DRAFTING`/`STATE_DEFICIENT` gate governs initial drafting only; revise/submit/review carry no plan-status gate beyond the `ADOPTED` guard — routes/elements.py:69,95,115
- §3.4 (review decision) — revise — **mismatch** — "Four further checks then apply" but only three are enumerated and only three exist -> "Three" — routes/elements.py:114-129
- §3.4 (review decision) — insert — ambiguity — `review_note` is 1-2000 chars, whitespace-only allowed, zero-length rejected (verified live) — routes/elements.py:112
- §3.4 (review decision) — insert — ambiguity — the HOUSING adopted-scenario gate keys on element type, not on the decision: `REQUEST_REVISION` is refused too (verified live) — routes/elements.py:118-122
- §3.5 (link creation) — insert — ambiguity — the three tests run FK -> ownership -> terminal-plan, so a cross-plan link reports `ERR_CROSS_PLAN_LINK` even when a plan is `ADOPTED` (§2.8's generic ladder would suggest the reverse) — routes/elements.py:177-180
- §3.5 (link creation) — insert — ambiguity — the `CLEARED -> PENDING` flip increments the source element's own `version`; a source already `PENDING`/`STALE` is untouched — routes/elements.py:200-202
- §3.5 (reconcile) — insert — ambiguity — `reconciliation_note` is mandatory, 1-2000 non-blank — routes/elements.py:239
- §3.5 (reconcile) — insert — ambiguity — source element's `version` moves only when its `consistency_status` actually changes — routes/elements.py:255-258
- §3.6 (venue) — insert — ambiguity — `seated_capacity` is a whole number, unbounded above, and is never compared against any attendance/participation figure — routes/engagement.py:26
- §3.6 (activity) — insert — ambiguity — `start_at`/`end_at` are never compared to the logical clock (an activity may be wholly in the past and completed at once); scheduling works at any plan status short of `ADOPTED` — routes/engagement.py:49-64
- §3.6 (record) — insert — ambiguity — `comment_text` <= 4000 chars, blank allowed, zero-length rejected — routes/engagement.py:185
- §3.6 (record scoring) — insert — ambiguity — the activity's own `interpretation_offered` never enters the weight arithmetic; the activity's `equity_share_pct` stays 0.0 until completion and no plan-level field moves on capture — routes/engagement.py:199,212-223
- §3.6 (completion) — insert — ambiguity — the two plan totals are re-derived as sums over `COMPLETED` activities and re-rounded to one decimal (the mechanism behind the 2.10 invariant) — routes/engagement.py:145 via services/planservice.py:41-51
- §3.6 (cancellation) — insert — ambiguity — `cancellation_reason` bounds; the `SCHEDULED` path leaves the plan's `version` untouched and carries **no** adopted-plan guard, so a scheduled activity can be cancelled after the plan is `ADOPTED` — routes/engagement.py:154-171
- §3.7 (selector ordering) — insert — ambiguity — `created_at` is not a total order; ties fall back to server creation order, the same order §2.3 gives lists — services/calc.py:141

### Pass 3 — environmental + hearings + implementation + planservice + repo (33 edits: 24 ambiguity, 6 mismatch, 3 corrective)

- §2.9 — insert — ambiguity — every posture recomputation re-derives the plan's *whole* counter set from scratch, including participation totals and `monitoring_on_track_count`, so an unrelated write such as a state filing re-derives them too — services/planservice.py:refresh -> recompute_counters
- §2.9 — revise — **mismatch** — replaced the symmetric-cascade sentence: blocking fires only when the recomputation actually leaves a non-`CLEAR` posture **and** either the previous posture was exactly `CLEAR` or the write is one of the three that force it (deficient state determination, council denial that demotes the plan, amendment adoption); the hearing whose own outcome is the write is exempt; unblocking is unconditional on any `CLEAR` recomputation — services/planservice.py:refresh (`force_block or previous == "CLEAR"`), force sites at routes/plans.py:150, routes/hearings.py:166, routes/hearings.py:288
- §3.1 — revise — **mismatch** — **softened the universal adopted-plan sentence** (see resolution notes below) — routes/*.py `ensure_not_adopted` call sites
- §3.3 — insert — ambiguity — a tier row's `updated_at`/`version` move only when one of its four computed figures actually changes — services/planservice.py:run_waterfall (`if changed and row["id"] != skip_bump_id`)
- §3.7 — insert — ambiguity — review `title` must be non-blank; no plan status precondition beyond not-adopted — routes/environmental.py:create_review
- §3.7 — insert — ambiguity — the adopted-plan guard is tested ahead of `ERR_REVIEW_NOT_DRAFT`; `label` non-blank; indices accepted as whole or fractional JSON numbers — routes/environmental.py:add_alternative
- §3.7 — insert — ambiguity — circulate carries the adopted guard first; plan status otherwise not consulted — routes/environmental.py:circulate_review
- §3.7 — insert — ambiguity — select-preferred carries the adopted guard, tested before `ERR_REVIEW_NOT_CIRCULATED` — routes/environmental.py:select_preferred
- §3.7 — insert — ambiguity — certify carries the adopted guard, recomputes no counters, no posture, fires no hearing cascade — only the two `version` bumps — routes/environmental.py:certify_review
- §3.8 — insert — ambiguity — each element the demotion cascade touches is bumped exactly once regardless of how many fields or links moved; already-`STALE` or already-demoted sources take no further increment — services/planservice.py:demote_approved_elements
- §3.8 — revise — **mismatch** (+ corrective) — the block fires because the determination is deficient, not because the posture had been `CLEAR`; now reads "one of the three writes that block unconditionally" — routes/plans.py:150
- §3.9 — insert — ambiguity — an `ADOPTED` plan reports `ERR_PLAN_ALREADY_ADOPTED` rather than `ERR_PLAN_NOT_CERTIFIED`; `compliance_posture` is not consulted at scheduling time — routes/hearings.py:create_hearing
- §3.9 — insert — ambiguity — none of a hearing's three instants is compared against the logical clock at scheduling time — routes/hearings.py:create_hearing
- §3.9 — insert — ambiguity — a hearing enters `SCHEDULED` whatever the posture is, and may later be moved to `BLOCKED` both by posture cascades and by a commission denial of a sibling hearing — routes/hearings.py:create_hearing / record_outcome
- §3.9 — insert — ambiguity — gavelling in carries no adopted-plan guard and touches nothing on the plan — routes/hearings.py:open_hearing
- §3.9 — insert — ambiguity — `minutes_note` is 1-4000 chars, may be whitespace-only but not zero-length, and is shape-checked without being persisted — routes/hearings.py:record_outcome
- §3.9 — insert — ambiguity — `CONTINUE` adds no precondition: either body, any plan status, no posture check, tolerates unresolved amendments — routes/hearings.py:record_outcome
- §3.9 — revise — **mismatch** — `ADOPT` re-derives no counters and does not recompute the posture; "locks its whole aggregate against further writes" replaced by a pointer to §3.1's enumerated exceptions — routes/hearings.py:record_outcome ADOPT branch
- §3.9 — revise — **mismatch** — `DENY`: reports `ERR_PLAN_NOT_CERTIFIED` for any other status; the commission branch also covers a `COUNCIL` hearing against a `STATE_CERTIFIED` plan; that block bypasses the ladder (posture untouched) and is therefore reversible by the next `CLEAR`-recomputing write; the council-demotion branch recomputes by the ladder — usually `CONSISTENCY_HOLD` but possibly back to `CLEAR`, in which case `BLOCKED` hearings are *released* instead — routes/hearings.py:158-172
- §3.9 — insert x2 — ambiguity — `summary` non-blank and `expected_element_version` an integer >= 1 (a `0` is a rung-4 violation, not a rung-7 stale-version rejection); and moving an amendment reaches no further than the docketing — no element status/policy_count/consistency change, no link movement, no plan counter/posture/version — routes/hearings.py:create_amendment
- §3.9 — insert — ambiguity — the target element's status is deliberately not re-examined at adoption time, so a since-demoted or since-`ADOPTED` element remains adoptable and its then-current status is what is captured as `prior_element_status` — routes/hearings.py:adopt_amendment
- §3.9 — revise — **mismatch** (+ corrective) — adoption-cascade steps 3-5: source elements bumped once only; posture recomputed *by the ladder* (`CONSISTENCY_HOLD` ordinarily, but confirmed `CLEAR` when the element had no inbound `CLEARED` link); hearings blocked whenever the recomputed posture is not `CLEAR` (unconditional force — "the last of the three writes that block unconditionally"), else `BLOCKED` hearings return to `SCHEDULED`; the amended hearing is `OPEN` so neither direction touches it — routes/hearings.py:288
- §3.9 — insert — ambiguity — `withdrawal_reason` 1-2000, may be whitespace-only, not persisted; `amendment_count` is never decremented and the hearing's `version` stands — routes/hearings.py:withdraw_amendment
- §3.9 — insert — ambiguity — `rescission_reason` is 1-2000 chars, may be whitespace-only but not zero-length — routes/hearings.py:rescind_amendment
- §3.9 — insert — ambiguity — a source element's `version` moves only when its `consistency_status` actually changes to `CLEARED`; the step-1 target element is not revisited — routes/hearings.py:rescind_amendment
- §3.9 — insert — ambiguity — action `title`/`indicator_name` non-blank; `baseline_value`/`target_value` required unbounded JSON numbers (negative and fractional allowed, never rounded); adopted guard tested before the ownership rule; `on_track` false by construction; adding an action touches nothing on the plan — routes/implementation.py:create_action
- §3.9 — insert x2 — ambiguity — `reading_value` is a required unbounded JSON number stored exactly as supplied; and the recomputation is a counter refresh only — the posture is *not* re-run, no hearing cascade fires, and the plan's `updated_at`/`version` do not move — routes/implementation.py:record_reading
- §3.9 — insert — ambiguity — completion moves only the two `version` counters; no counters or posture re-derived; a completed action stays counted in `monitoring_on_track_count` — routes/implementation.py:complete_action

### Pass 3's resolution of the forwarded hand-off items

- **§3.1 universal adopted-plan sentence (from pass 1)** — **pinned/softened.** The claim that once a plan is `ADOPTED` "every write anywhere in its aggregate is refused with `ERR_PLAN_ALREADY_ADOPTED`" is false in `implementation/`. It is now an enumerated guard list plus explicit exceptions: a state determination reports `ERR_PLAN_NOT_SUBMITTED`; a still-`SCHEDULED` participation activity may be cancelled; the hearing-floor writes (open, record outcome, amendment lifecycle) carry only their own state guards; and the two monitoring writes of §3.9 are *expected* after adoption. Established by grepping every `ensure_not_adopted` call site across all route modules — in `routes/hearings.py` it appears exactly once (line 32, `create_hearing`).
- **Asymmetric hearing cascade (from pass 1)** — **pinned**: §2.9 rewritten with the conditional-block / unconditional-unblock asymmetry and the three forcing writes; the three dependent sites (§3.8 step 5, §3.9 DENY, §3.9 adoption step 5) made consistent with it (these are the 3 corrective edits).
- **Whether `DENY` can recompute back to `CLEAR` (from pass 2)** — **pinned** into the §3.9 DENY paragraph, including the consequence that `BLOCKED` hearings are then released.
- **Amendment adoption against a dependency-free element (from pass 2)** — **pinned**: §3.9 adoption step 4 now states the posture can be confirmed `CLEAR` when the element had no inbound `CLEARED` link, in which case step 5 unblocks rather than blocks.
- **`links_of_plan` scoping (from pass 1)** — **already-covered**: PRD 2.9 already pins scoping by the source element's plan; `services/repo.py` agrees. No edit.
- **Rescission step ordering (impl clears links before recomputing element consistency; PRD numbers them the reverse) (from pass 2)** — **unreachable, left alone**: links staled by an amendment *target* the element, while `element_consistency_from_links` inspects links *sourced from* it, so the ordering is unobservable through the API. Nothing documented rather than pin a distinction with no observable consequence.
- **`calc.indicator_on_track`'s `latest_value is None -> False` branch (from pass 2)** — **unreachable, left alone**; the initial `on_track=false` comes from row creation, which pass 3 did pin.
- **`ERR_NOT_FOUND` on non-string ids (from pass 1)** — **already-covered** by pass 1's global rule; `services/repo.py:_fetch` matches.

**Orchestrator verification (post-step):**
- `PRD_COMPLETED.md` exists at 542 lines / 129,102 chars and is **not** byte-identical to `PRD_FINALIZED.md` (`cmp` differs), so the scan demonstrably ran — the known no-op failure mode did not occur.
- Truncation guard: the file ends on the final `ERR_INDICATOR_OFF_TRACK | 409` catalogue row and still has all 5 top-level sections, so no trailing section was lost across three sequential editing passes.
- Cross-pass integrity: pass 3 spot-checked nine distinctive strings from passes 1 and 2 and found each present exactly once; the orchestrator independently confirms the monotonic growth 106,421 -> 113,367 -> 117,404 -> 129,102 chars, consistent with three additive passes and no clobbering.
- Documentation-only guarantee: `find` over `implementation/`, `test_suite/` and `test_helpers/` for files newer than the green sweep's `results.1.json` returns only `results.5.json` and `results.8.json` — two rounds of the same 12:21 sweep that finished a few seconds later. No source file in any of the three directories was touched by Steps 8 or 9, so the verified 8x 250/250 sweep still describes the shipped artifact.
- Housekeeping: a single `worklog.md` at the task root (no cwd-drift strays under `workspace/`), `test_helpers/` and `test_suite/` correctly at the task root, and all `__pycache__` directories removed.

**Pipeline complete.** Step 9 has written `workspace/PRD_COMPLETED.md`; all nine steps are done.
