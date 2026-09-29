# Worklog — task_2852_plant_breeding_program_variety_trials

## Step 1: Create task directory — 2026-09-05T06:56:44.794Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2852_plant_breeding_program_variety_trials` and `.../workspace` (pre-assigned path from the orchestrator invocation; no index auto-allocation performed, per instruction that other pipelines run concurrently on this host).

## Step 2: Generate scaffold — 2026-09-05T08:26:00.000Z

Scaffold package for task 2852 is complete and lint-clean.

## Files

| Path | Lines |
|---|---|
| `SCAFFOLD.yaml` | 2726 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1679 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3062 |

## SCAFFOLD.yaml contents (§1.0–§1.7 only; no `scaffold_difficulty_design` / `scaffold_corner_design` keys)

- scenario verbatim (including the leading `Generate task harder than expert level!` line — strip that line before Step 3 if you follow the usual leak-prevention step), domain `plant-breeding-variety-trials`, root API prefix
- 15 entities, 8 state machines, 2 §1.2.1 concurrency rules (`expected_line_version` -> ERR_STALE_LINE_VERSION, `expected_series_version` -> ERR_STALE_SERIES_VERSION), 8 calculations, 47 validations (priority ladder 1->47), 59 endpoints, 57 errors (409x21, 422x16, 404x13, 403x3, 412x2, 401x1, 400x1), 7 peer roles (PipelineDirector, ProgramLead, BreedingScientist, TrialAgronomist, DataAnalyst, RegulatoryOfficer, SupplyPlanner)
- complexity_profile: expert, workflow_orchestration/posture-driven gating, graph topology, parallel state shape, peer_roles, immediate consistency, layers `[cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, optimistic_concurrency]`

## §1.8 — 9 rules x 2 instances = 18

## §1.9 — all 9 sections, 58 instances (42 with executable calls, 16 `excluded_because:` stubs pointing at the §1.8 instance that already covers the corner)

entities 11 · state_machines 12 · calculations 12 · validations 7 · endpoints 5 · errors 2 · rbac 3 · cross_cutting_complexity_layers 5 · consistency_model 1

All 76 instance names are globally unique across both design files, and all 57 catalog errors are triggered or asserted at least once.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    59
  §1.1 entities declared:     15
  §1.8 instances scanned:     18
  §1.9 instances scanned:     42
  Calls scanned (§1.8+§1.9):  866

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Two lint constraints worth passing to the test generator: the linter rejects calls whose `as:` role is not in the endpoint's `roles`, and rejects payloads missing a required input field — so all 401/403 refusals and all malformed-body refusals in this scaffold are expressed as `assert:` prose rather than as `trigger:` calls, and stale-version tests are built by capturing a version placeholder that a later accepted write invalidates (check (e) forbids literal `expected_*_version` values).

**Orchestrator note:** as the subagent flagged, the difficulty directive line `Generate task harder than expert level!` had leaked into SCAFFOLD.yaml's `scenario:` block. The orchestrator deleted that line (and its trailing blank) with `sed -i '2,3d'` before Step 3, so the directive cannot reach PRD.md via the doc generator. Re-verified: `grep -rn "harder than expert"` across all three scaffold files returns no hits, and SCAFFOLD.yaml still parses as valid YAML with 13 top-level keys.

## Step 3: Copy shared files — 2026-09-05T08:26:20.847Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T08:42:00.000Z

PRD complete and verified.

**Deliverable:** `workspace/PRD.md` — **448 lines**, ends cleanly at the last row of the §5 table (`| \`ERR_INSUFFICIENT_SEED_INVENTORY\` | 409 Conflict |`). Last section heading: `## 5. Error Code Catalogue`.

**Section list**
- `# Plant Breeding Variety Trials API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim fixed contract) · 2.3 Pagination · 2.4 Resource Identity, Audit Fields and Record Versioning · 2.5 The Agronomic Calendar and the Logical Clock · 2.6 Decimal Discipline: Exact Arithmetic and Pinned Rounding Order · 2.7 Validation Order and the First-Failure Rule · 2.8 Nested Resource Retrieval and Path Resolution · 2.9 Optimistic Concurrency Control · 2.10 Cascading Consistency and Server-Derived State
- `## 3. Business Logic & Workflows` — 3.1 Establishing a Breeding Programme and Its Market Objectives · 3.2 Germplasm Origination · 3.3 Nursery Rotation, Occupancy and Generation Advancement · 3.4 Trait Integration Through Marker-Assisted Backcrossing · 3.5 Trial Sites, Capacity Posture and Entry Admission · 3.6 Committing a Series to the Ground · 3.7 Adjusted Means, the Environment Index and Stability Analysis · 3.8 Stage Gates: Advancement Index, Committee Decisions and Series Closure · 3.9 Regulatory Stewardship, Pre-Commercial Seed Increase and Launch Volume
- `## 4. Endpoint Definitions` (4-column table, 59 rows)
- `## 5. Error Code Catalogue` (2-column table, 57 rows)

**Coverage counts (all scripted against SCAFFOLD.yaml)**
- Entities 15/15 · Endpoints 59/59 table rows · State machines 8/8, all 35 transitions described (incl. the parallel `pipeline_stage`/`stewardship_status` dimensions, the `CHANGES_REQUESTED -> SUBMITTED` cycle, the branching harvest, and the three cascade-only transitions) · Calculations 8/8 with every numeric constant present · Validations 47/47 as a strictly ordered numbered list in §2.7 (priorities 1–47, 28 distinct `applies_to` scopes rendered as capability names) · Errors 57/57, every one also referenced in §2/§3 prose (zero table-only orphans) · Roles 7/7 · Concurrency rules 2/2 in §2.9.

**Hard Contract results**
- Contract 1 (Field-Name Coverage): PASS — 129 distinct `entities[].fields[].name`, 94 request-body/output identifiers, 25 query params, 1 path param, 11 nested-object keys -> 0 missing.
- Contract 2 (Rule Coverage): PASS — all 47 validations, both OCC rules, all 35 transitions, all 8 calculations, 58 field-level defaults (null/false/`{}` defaults stated explicitly), both cascades (DISCARD's 5-stage pinned order, suspension's 4-level order), and every sibling-branch pair. The 54 scaffold identifiers absent from the PRD are exclusively internal names (constant labels like `MGMT_RATE_TIER_1`, calculation names, algorithm tags, formula locals) whose *semantics and values* are all present in prose — the intended prose projection.
- Contract 3 (§3 Path Purity): PASS — 1001 backticked tokens scanned in the §3 span; 0 leading-slash paths, 0 bare HTTP methods, 0 method+path tokens; also 0 unbackticked method words or slash-paths.

**Two repairs made during verification** (both in §4 descriptions, which had been auto-extracted from the scaffold): removed 12 occurrences of the scaffold-internal phrase "reverse-reachability for X.y" in favour of natural filter descriptions, and replaced `MIN_ADVANCE_SEED_G threshold (nursery_harvest_credit)` with "250-gram viability threshold" so no §4 cell references an identifier defined nowhere in the document. Line count unchanged at 448.

Constraints honoured: neither design yaml was opened, grepped or referenced; no sibling task directory was read; the file was built via chunked heredoc appends; no `pkill` was run; scratch stayed in `/tmp/task_2852_scratch/` and has been removed.

**Orchestrator truncation check (per the known doc-generator failure mode):** `wc` reports 448 lines / 119264 bytes; `tail -12` shows the file terminating at a complete error-catalogue table row, not mid-sentence; all 27 expected headings are present through `## 5. Error Code Catalogue`. Not truncated — no regeneration needed. Leak re-check for "harder than expert" / "scaffold" / "test_recipe" in PRD.md: no hits.

## Step 6: Generate implementation — 2026-09-05T09:16:00.000Z

Implementation complete.

## Files (`workspace/implementation/`)

| file | lines | role |
|---|---|---|
| `start.sh` | 10 | `cd $(dirname $0)`, guarded `pip install` (only if Flask missing), `exec python3 app.py` |
| `requirements.txt` | 1 | `Flask>=2.2` |
| `app.py` | 72 | app factory, 4 blueprints, `before_request` -> `mut.reset()` + `auth.authenticate()`, `ApiError`/`HTTPException`/`Exception` handlers, `0.0.0.0:$PORT` (default 10000) |
| `envelope.py` | 81 | `meta`/`response_type`/`data`, `req_` + 20 upper-alnum id, 3-digit-fraction timestamp, list meta, Decimal->float, datetime->`...Z`, date->`YYYY-MM-DD`, `_`-prefixed keys stripped |
| `errors.py` | 88 | all error ids -> HTTP status, `ApiError`, `fail`, `bad_request` |
| `store.py` | 90 | 15 in-memory dicts, logical clock (default `2026-08-01T00:00:00Z`), id/seq/record factory, `ordered()` |
| `mut.py` | 60 | one `version++`/`updated_at` bump per record per request, signature diff + explicit `force()` |
| `validators.py` | 352 | shape layer (step 3): enums, strict typing, date-only vs instant, pagination |
| `auth.py` | 62 | steps 1/2/5 (`ERR_UNAUTHENTICATED`, `ERR_ROLE_NOT_PERMITTED`, ProgramLead scope) |
| `lookup.py` | 78 | steps 4/6 404s + `program_open` (9) + `line_not_discarded` (16) |
| `calc.py` | 254 | all Decimal math: yield rollup, series cost tiers, bag/seed ceilings, marker recovery, posture ratio, Finlay–Wilkinson, dual-variant index |
| `derive.py` | 458 | navigation, all derived counters, site daily-peak sweep, series census/bubbling, readiness, index recompute, DISCARD + suspension cascades |
| `routes_program.py` | 219 | 9 endpoints |
| `routes_germplasm.py` | 552 | 19 endpoints |
| `routes_trials.py` | 585 | 16 endpoints |
| `routes_gates.py` | 469 | 15 endpoints |
| | **3431** | |

## Endpoints: 59 / 59

Diffed the registered URL map against PRD §4 mechanically (method + path, params normalised): **exact match, zero missing, zero extra**.

## Smoke test: PASS

Launched via `bash start.sh` with `PORT=21852..21855` (fresh process each time, killed by specific PID only — no broad `pkill`). Final run: **40 request/response assertions, 0 failures, no server-side traceback**.

- Envelope verified against §2.2: keys exactly `meta`/`response_type`/`data`; `api_request_id` = `req_` + 20 uppercase alnum (24 chars); timestamp with exactly 3 fractional digits + `Z`; error bodies carry `response_type: "error"` and `{error_id, message}` with meta limited to the two fields; list meta carries `limit/offset/total_count/has_more` (`total_count=6, limit=4, has_more=true` confirmed).
- End-to-end domain flow exercised: program -> objective -> lines -> crossing block -> pollinate -> progenies (auto-CLOSE at `progeny_line_count == realized_cross_count`) -> nursery planting -> plant -> harvest (seed banked, generation advanced) -> 3 sites -> series -> 6 entries -> plant (cost `1530.36 + 183.64 = 1714.00`) -> 18 observations -> finalize (plot mean `31.000`, `24800.00 kg/ha`) -> series `DATA_COMPLETE` -> BALANCED_CORE analysis (b `1.1391`/`0.8609`, MSE, environment index) -> ADVANCE decision (`decision_index_value 99.00`, NURSERY->STAGE_1) -> stewardship draft/submit/REQUEST_CHANGES/resubmit/APPROVE/suspend -> seed lot (`planned_units_bags 7`, `allocated_seed_g 4375`, ledger `6900 - 4375 + 175000 = 177525`) -> backcross to `CONVERTED` at `99.375%` -> pipeline report -> series close -> program close.
- Negative paths confirmed in ladder order: 401, 403 (role / scope / segregation-of-duties), 400 (weight sum, `donor==recurrent`, `limit=0`, `offset=-1`), 404 (unknown id and unknown path), 405, 412 (both stale-version guards), 409 (`ERR_DUPLICATE_CODE`, `ERR_BLOCK_NOT_POLLINATED`, `ERR_BLOCK_OCCUPANCY_CONFLICT`, `ERR_PLANTING_INVALID_STATE`, `ERR_DUPLICATE_TRIAL_ENTRY` before divisibility per §3.5, `ERR_DUPLICATE_OBSERVATION`, `ERR_LOT_INVALID_STATE`, `ERR_SERIES_INVALID_STATE` incl. the undecided-line close gate, `ERR_PROGRAM_CLOSED`), 422 (`ERR_PLOT_COUNT_NOT_DIVISIBLE`, `ERR_ENTRY_WINDOW_OUTSIDE_SEASON`, `ERR_STEWARDSHIP_NOT_APPROVED`, `ERR_MARKET_NOT_IN_AGREEMENT`).
- **No seeded data / no persistence:** killing the server and relaunching on the same port turns a previously `200` program read into `404`; the only artifact any run left on disk was `__pycache__`, which I removed. Nothing under `/tmp` is read or written by the app; my scratch stayed in `/tmp/task_2852_scratch_impl/`.

The test suite and the two design YAMLs were never read; everything derives from `PRD.md`, `SCAFFOLD.yaml`, and `INSTRUCTION.md`. Where the scaffold contradicted the PRD (harvest FAILED branch still banking seed, invalidation releasing plots while keeping the series census, the PRE_COMMERCIAL->COMMERCIAL stewardship gate, `revision_round` incrementing on re-submit) the PRD won.

**Orchestrator note on ordering:** Steps 5 and 6 were launched as background agents a few seconds apart rather than in one message. Isolation was preserved by an explicit absolute prohibition in the Step 6 prompt against reading `test_suite/` or `test_helpers/`; the Step 6 agent confirmed on exit that it never read them.

## Step 5: Generate unit tests — 2026-09-05T09:52:00.000Z

Step 5 is complete. Test infrastructure and the full design-driven suite are in place.

## Files (all under the task root)

**`test_helpers/`** (2093 lines): `__init__.py` 142, `api_client.py` 321, `api_errors.py` 154, `assertions.py` 269, `constants.py` 72, `factories.py` 358, `fixtures.py` 466, `test_users.py` 98, `types.py` 213.

**`test_suite/`** (6003 lines): `conftest.py` 22; queue A — `test_01_dual_variant_calculations.py` 319, `test_02_combinatorial_formulas.py` 148, `test_03_non_linear_state_machines.py` 215, `test_04_transitive_cascades.py` 315, `test_05_validation_priority_pairs.py` 229, `test_06_boundary_precision.py` 246, `test_07_cross_entity_state_dependency.py` 276, `test_08_resource_temporal_overlap.py` 318, `test_09_compensating_invariants.py` 332; queue B — `test_10_entity_surface.py` 654, `test_11_state_machines.py` 657, `test_12_calculations.py` 599, `test_13_validations.py` 570, `test_14_endpoints.py` 311, `test_15_errors.py` 200, `test_16_rbac.py` 267, `test_17_concurrency_and_consistency.py` 325.

## Counts

- **82 test functions**, each carrying exactly one `Design:` tag: **40 from queue A** (Difficulty) and **42 from queue B** (Corner).
- Coverage: all 18 difficulty instances translated with >=2 tests each; all 42 non-stub corner instances translated with >=1 test each; **0** of the 16 `excluded_because:` corner stubs translated.
- **Skipped design instances: none.** Every non-stub instance in both indices passed the PRD-first filter, so there is no PRD-silence or non-derivability gap to report.

## Verification

- `python3 -m pytest test_suite --collect-only -q` -> **82 tests collected**, no import or collection errors; `compileall` clean; `pyflakes` clean on every `test_suite/*.py`.
- Citation checker: 235 verbatim PRD citations across the 17 files, all surviving a whitespace-flattened literal grep of `workspace/PRD.md` — **BAD 0**. No file mentions "scaffold".
- Placement confirmed: `test_helpers/` and `test_suite/` sit directly under the task root; `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `run_sweep.sh` and `implementation/` (never read or written by me); no stray `test_helpers`/`test_suite`/`worklog.md` anywhere under `workspace/`; `__pycache__`/`.pytest_cache` removed.

## Notable judgements in the final file (`test_17`)

- The `consistency_model` recipe asserts `committed_budget_usd 882.00` / `budget_remaining_usd 1999118.00` from "18 x 45.00 x 1.09 at MGMT_RATE_TIER_1". PRD §3.6 pins tier 1 at **0.12** for a subtotal strictly below 10000.00, so 810.00 + 97.20 = **907.20**; I asserted the PRD-derived figure. I also dropped the `budget_remaining_usd` assertion on the programme record, since PRD §3.1 declares that field only on the pipeline report, not on `BreedingProgram`.
- The site record has no `utilisation` field in the PRD, so the design's "utilisation 0.18" is asserted as `peak_committed_plot_count 18` / `available_plot_count 82` / `capacity_posture OPEN`.
- Both concurrency tests use an objective spec'd `{"PROTEIN_MIN": 13.0}` only, which is what makes the quality component 100.00, provisional **104.55** and the frozen cumulative **94.10** (104.55 x 0.90 at NURSERY) — consistent with the same pins already used in `test_14` and `test_15`.

**Orchestrator placement re-verification:** `test_helpers/` and `test_suite/` confirmed at the task root, and `workspace/` holds only `INSTRUCTION.md`, `PRD.md`, `run_sweep.sh`, `implementation/` — no stray test directories to relocate before Step 7.

## Step 7: Run tests and iterate — 2026-09-05T10:23:00.000Z

Storage is in-memory only, no skip/xfail markers, worklog untouched (mtime 10:01, before I started), scratch confined to `/tmp/task_2852_scratch_step7/`. The loop is complete.

## Summary

**Iterations run:** 2 sweeps (8 rounds each). Iteration 1 = 79/82 in all 8 rounds with 3 deterministic failures (zero flakiness — identical failure set every round). Iteration 2 = clean.

**Tests deleted:** none. One assertion removed under STEP 1c partial-coverage split (below).

**Fixes applied to `test_helpers/`:**
- `test_helpers/types.py` — added `INVALIDATED = "INVALIDATED"` to the `EntryStatus` class. The enum member was simply missing, so `test_the_last_entry_to_leave_planted_bubbles_the_series_whichever_exit_it_takes` died with `AttributeError: type object 'EntryStatus' has no attribute 'INVALIDATED'` before it ever reached the server. PRD 3.6 states the member verbatim: "the entry moves `PLANTED -> INVALIDATED`", so this made the helper *more* faithful to PRD, not less.

**Fixes applied to `test_suite/`:**
- `test_10_entity_surface.py`, `test_line_retrieval_exposes_both_state_dimensions_and_the_seed_ledger` — removed the single assertion `assert line["advancement_index_provisional"] is None` (and the now-orphaned PRD 3.8 quote from the docstring). **Non-derivability, STEP 1b:** the cited sentence is "It is written to `BreedingLine.advancement_index_provisional`, stays null until the line has at least one of the three components available, and is recomputed whenever a series analysis includes the line, whenever the line's `disease_resistance_scores` change … and whenever its `quality_trait_values` change." The line under test is created *with* non-empty `disease_resistance_scores` and `quality_trait_values`, so two of the three components are available at creation and the quoted null-condition is not satisfied — the sentence arguably points the other way from the assertion. Meanwhile the recompute-trigger list omits creation, and §3.2's registration paragraph enumerates the initial derived values (stage, stewardship, cumulative seed, readiness, `active_line_count`) without mentioning this field, while §2.10 lists "provisional index" among values "computed by the server from the records that justify them". Both readings are articulable, so the outcome is not uniquely determined and the implementation's 77.00 (= 0.50x60 + 0.30x100 + 0.20x85) is a legitimate PRD-faithful reading. The other 12 assertions in the test are all verbatim-covered by §3.2/§3.9 and were kept; a sibling assertion at line 335 that expects null for a line with *empty* trait maps is unambiguous and still passes.

**Fixes applied to `implementation/`:**
- `workspace/implementation/routes_gates.py`, `create_decision()` — `to_stage` was initialised to `from_stage` and only overwritten on the `ADVANCE` branch, so a `DISCARD` decision recorded `to_stage: "NURSERY"`. Added an `elif decision == "DISCARD": to_stage = "DISCARDED"` branch. PRD 3.8 pins both halves: the server "records … `to_stage` as its stage immediately after", and the discard cascade's first step is "First the line itself: `pipeline_stage` becomes `DISCARDED`". Verified no other test asserts `to_stage` on a DISCARD, and the ADVANCE/HOLD readings are untouched, so the change is regression-free.

**Final sweep evidence:** 82/82, 82/82, 82/82, 82/82, 82/82, 82/82, 82/82, 82/82 — 0 failed, 0 errors, 0 skipped in every round.

Two notes for the record: no `pkill` was used at any point (my private spot-check server on port 18521 was killed by resolving its PID via `ss -lptn 'sport = :18521'`), and storage remains in-memory-only — `grep` for `sqlite3|json.dump|pickle|shelve|open("` across the implementation returns nothing.

**Orchestrator independent verification of the sweep artifacts** (per the known failure mode where a Step 7 agent claims a clean sweep without leaving evidence): all 8 `workspace/implementation/results.$i.json` exist (mtime 10:13, i.e. from the final sweep, ~24.3 KB each) and each parses to `passed=82 failed=0 errors=0 skipped=0 total=82`. `grep` for `pytest.mark.skip|pytest.mark.xfail` across `test_suite/` returns 0 hits, and the suite still contains 82 `def test_` functions — matching Step 5's emitted count, confirming the one repair was an assertion removal rather than a test deletion.

## Step 8: Finalize PRD — 2026-09-05T10:33:00.000Z

PRD_FINALIZED.md produced with a single surgical edit.

## Line counts
- `PRD.md`: 448 lines / `PRD_FINALIZED.md`: 448 lines — 0% line delta (one long paragraph line revised in place; +~470 characters).

## Changes
- **§3.8 (PROVISIONAL variant paragraph)** — *revise* — the sentence defining `BreedingLine.advancement_index_provisional` listed only three recompute triggers (series analysis, `disease_resistance_scores` change, `quality_trait_values` change) and omitted line registration, while the implementation computes the index at creation with the yield component MISSING (hence imputed). Added the registration-time computation, stated that no analysis can yet cite a brand-new line so yield is MISSING/imputed, and that the field is null at registration only when both trait maps are empty — `implementation/routes_germplasm.py:192` (`_new_line`, `rec["advancement_index_provisional"] = calc.provisional_index(objective, rec, None)`), backed by `implementation/calc.py:237-246`.

## No-edit determinations (traced to the other two Step 7 items)
- `test_helpers/types.py` `EntryStatus.INVALIDATED` — pure fixture bug. PRD §3.6 (line 262) already states `PLANTED -> INVALIDATED` verbatim. No PRD silence, no edit.
- `routes_gates.py create_decision()` `to_stage = "DISCARDED"` on DISCARD — PRD §3.8 already pins both halves ("`to_stage` as its stage immediately after" + "First the line itself: `pipeline_stage` becomes `DISCARDED`"). This was an impl-side mismatch with an already-determined PRD, so PRD prose stays verbatim.

## Pre-edit search log (the one edit)
- **(a) Subject:** every write of `advancement_index_provisional` and every trigger that recomputes it.
- **(b) Paths enumerated / read:** grep for `advancement_index_provisional|provisional` across `implementation/` -> 4 write/compute sites: `routes_germplasm.py:186` (initial `None`), `routes_germplasm.py:192` (registration compute), `routes_germplasm.py:550` (backcross conversion -> `derive.recompute_provisional_index(recurrent)`), `routes_trials.py:565` (analysis creation, per `entry_means` row, with the series id). Read `derive.py:382-391` (`recompute_provisional_index`, incl. `source_mean_anywhere` for the no-series case) and `calc.py:190-246` (`index_components`, `provisional_index`, null-iff-all-three-MISSING). Grepped every writer of `disease_resistance_scores` (only registration + backcross conversion) and of `quality_trait_values` (only registration — never mutated post-creation), and every `BreedingLine` creation site (`store.lines[...] = rec` occurs exactly once, in `_new_line`, shared by the progeny and direct-registration routes). Also cross-read §3.2's registration paragraphs and §2.10's derived-field list to confirm neither contradicts the new clause (§3.2 enumerates initial derived values non-exhaustively; §2.10 already lists "provisional index" as server-computed).
- **(c) Wording adjustments made:** scoped the new clause to "either origination route" rather than naming one endpoint, since both routes share `_new_line`; wrote "its yield component is MISSING and imputed" without restating the constant 60 (already pinned earlier in the same paragraph) so the sentence cannot conflict with the imputation rule; qualified the null claim as "null **at registration** only when both of those maps are empty" so it does not become a false universal about the post-registration recompute paths, where a `source_mean` may exist and the yield component alone can carry the value. Deliberately left the `source_mean_anywhere` selection rule for the trait-map-change recompute (latest non-superseded analysis, `BALANCED_CORE` preferred, any series) untouched — that is a separate PRD under-determination not surfaced by the Step 7 diff, and widening the yield-source sentence would exceed hard scope.

**Orchestrator verification:** `PRD_FINALIZED.md` is 119642 bytes vs PRD.md's 119264 (+378 bytes), both 448 lines, `cmp` reports DIFFERS, and the file still ends at the final row of the §5 error-catalogue table — not truncated. Step 8 was correctly NOT skipped because Step 7 applied one `implementation/` fix.

## Step 9: Complete PRD — 2026-09-05T11:05:00.000Z

Step 9 was run as **three sequential file-partitioned passes** over one shared `workspace/PRD_COMPLETED.md` (pass 1 did the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden to re-copy, so each pass's edits accumulated instead of overwriting). Partition was by implementation module, which keeps the passes from colliding on the same paragraphs. Totals: **48 edits — 35 ambiguity-pins, 13 mismatch-revisions**; 448 -> 452 lines, 119,642 -> 132,228 chars (+12,586).

### Pass 1 — cross-cutting modules + `routes_program.py` (`app.py`, `envelope.py`, `errors.py`, `store.py`, `mut.py`, `validators.py`, `auth.py`, `lookup.py`)

Created `PRD_COMPLETED.md` from `PRD_FINALIZED.md` (448 lines / 119,642 chars) -> 452 lines / 124,688 chars. Heading list byte-identical to the source; table row count unchanged (120 -> 120). **14 ambiguity-pins, 2 mismatch-revisions:**

- §2.1 — revise — ambiguity — `X-User-ID` that is empty or whitespace-only is treated as absent -> `ERR_UNAUTHENTICATED` — `auth.py:23`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A`–`Z`/`0`–`9` — `envelope.py:21-22`
- §2.3 — revise — ambiguity — non-integer `limit`/`offset` text is 400; `offset` at/past `total_count` is an empty page, not an error; undeclared query params ignored — `validators.py:293-315,350-352`
- §2.3 — revise — ambiguity — `created_at` ties (second precision) break on the server's monotonic creation sequence, so ordering is always mint order — `store.py:87-90`
- §2.3 — revise — ambiguity — `has_more` is exactly `offset + len(returned) < total_count` — `envelope.py:66`
- §2.4 — insert — ambiguity — one `version` bump per request regardless of how many fields/cascade steps touch the record; a cascade re-derivation landing on unchanged counters leaves `version`/`updated_at` alone; `updated_at == created_at` at creation — `mut.py:16-60`, `store.py:80-83`
- §2.5 — insert — ambiguity — `created_at`/`updated_at` are stamped from real server UTC, never from the logical clock; clock endpoint accepts `current_utc` with or without fractional seconds and returns `data` = `{current_utc}` at second precision — `store.py:62-63`, `validators.py:198`, `routes_program.py:213-219`
- §2.6 — insert — ambiguity — decimals are wired as JSON numbers (never strings) with trailing zeros not preserved (`0.00` -> `0.0`, `1234.50` -> `1234.5`) — `envelope.py:38-39`
- §2.7 step 3 — insert — ambiguity — strict typing (bools != ints, quoted numerals rejected), required strings non-empty, explicit `null` = omitted, map keys restricted to the recognised set, enum and boolean query filters (`true/false/1/0`, case-insensitive) validated, `Content-Type` not inspected, empty body = `{}`, non-object body rejected — `validators.py:38-50,56-57,83,99,141-151,218-219,318-347`
- §2.8 — insert — ambiguity — unmatched path -> `ERR_INVALID_REQUEST` @ **404**, wrong method -> `ERR_INVALID_REQUEST` @ **405** (the only non-400 client statuses that id carries); both decided by the router *before* the §2.7 ladder, so they outrank the missing-header check; trailing slash insignificant — `app.py:24,42-50`
- §3.1 — revise — **mismatch** — `total_budget_usd` is stored rounded half up to 2dp; extra places are rounded, not rejected — `routes_program.py:33`
- §3.1 — revise — ambiguity — closing an already-`CLOSED` programme is refused with `ERR_PROGRAM_CLOSED` (not idempotent); close advances the programme's `version` — `routes_program.py:67-75`
- §3.1 — revise — ambiguity — `lines_by_stage` always carries all seven stage keys, with 0 where the programme has no line — `routes_program.py:179`
- §3.1 — insert — ambiguity — `required_disease_resistances` and `quality_trait_specs` are optional in the body; omission = `[]` / `{}` — `routes_program.py:87-93`
- §3.1 — revise — **mismatch** — the three objective weights are stored exactly as supplied, not re-rounded to two decimal places (only the exact-1.00 sum is enforced) — `routes_program.py:94-98`
- §3.1 — revise — ambiguity — `min_advancement_index` must be >= 0 and is stored as supplied — `routes_program.py:99`

Pass 1 also diffed `errors.py`'s full `ERROR_HTTP` map programmatically against the §5 catalogue: perfect agreement on all identifiers and statuses, so §5 needed no edit in any pass.

### Pass 2 — `calc.py`, `derive.py`, `routes_germplasm.py`

124,688 -> 129,238 chars (+4,550), still 452 lines — every edit in-paragraph. **9 ambiguity-pins, 6 mismatch-revisions:**

- §2.1 — revise — mismatch — scope compares exactly one programme id (the path resource or the body's own `program_id`); a secondary body FK is not scope-checked, so a cross-programme `objective_id`/parent on a direct line registration reports its own 422 rather than 403 — `routes_germplasm.py:251`
- §2.7 step 5 — revise — mismatch — same delimitation, plus: a top-level collection endpoint names no programme-owned resource, so this step neither rejects nor narrows it (a `ProgramLead` sees every matching record) — `routes_germplasm.py:106,285,502`
- §2.7 step 3 — revise — mismatch — the "unparseable/non-object body is rejected" rule bites only where the operation declares body fields; the eight field-less transitions never inspect the body — `routes_germplasm.py:392`
- §3.2 — insert — ambiguity — `realized_cross_count > planned_cross_count` -> `ERR_INVALID_REQUEST` (400), evaluated after the programme-open and `PLANNED`-state checks — `routes_germplasm.py:138`
- §3.2 — insert — mismatch — `progeny_line_count` is re-derived only on progeny registration; the discard cascade never revisits the block, so the stored count keeps counting a later-discarded line — `derive.py:414`, `routes_germplasm.py:228`
- §3.3 — insert — ambiguity — `harvested_seed_g` may not be negative; `actual_harvest_date` earlier than `sow_date` -> `ERR_INVALID_REQUEST` (400) after the `PLANTED`-state check — `routes_germplasm.py:416,425`
- §3.3 — insert — ambiguity — the line's `version` advances on both harvest branches, including a 0-gram FAILED harvest that changes no line field — `routes_germplasm.py:428`
- §3.5 — revise — mismatch — `entry_count`/`location_count` count every entry not withdrawn (`ENTERED`, `PLANTED`, `HARVESTED`, `INVALIDATED`), which is why §3.6's invalidation rule leaves the census alone — `derive.py:261-270`
- §3.7 — insert — ambiguity — a zero regression divisor (all points share one site `index_kg_per_ha`) yields null `b`, null `deviation_mse` and `UNCLASSIFIED` regardless of n — `calc.py:149`
- §3.8 — revise — ambiguity — the yield source falls back to `UNBALANCED_INCLUSIVE` when a live `BALANCED_CORE` analysis exists but carries no `entry_means` row for the line — `derive.py:361-368`
- §3.8 — insert — ambiguity — a trait-map-driven provisional recompute cites no series, so it searches the most recent live `BALANCED_CORE` row for the line across all series, then `UNBALANCED_INCLUSIVE` — `derive.py:371-379`, `routes_germplasm.py:550`
- §3.8 — revise — ambiguity — the cumulative stage-confidence factor is 1.00 for any stage the table omits, so a `HOLD`/`DISCARD` on a `COMMERCIAL` line takes no discount — `calc.py:21-27,253`
- §3.8 — revise — mismatch — dropped the false universal "the cited series … entries of other series never contribute"; now scoped to the row the selection rule picks — `derive.py:382-391`
- §3.8 — revise — ambiguity — a discard-cascade withdrawal also re-derives the parent series' `entry_count`/`location_count` — `derive.py:405-411`
- §3.8 — insert — ambiguity — the `ADVANCE` supersession spans all series (HOLD/DISCARD untouched), and the cascade leaves nursery plantings (still holding plots) and the stewardship agreement alone — `derive.py:436-445`

Verified as already uniquely pinned (no edit): yield rollup order, per-hectare factor 800, cost tiers and strict boundaries, ceil-then-sum bag plan, marker recovery + 2.5-point bonus + 99.900 cap after rounding, posture ratio thresholds, F–W coefficient/MSE (unrounded `b` in residuals, n-2, class from rounded `b`), all three index components, PROVISIONAL/CUMULATIVE imputation, programme counters, block occupancy/half-open conflict, site daily peak (impl's window-start sweep is provably equivalent to the full sweep), `bubble_series_data_complete`, seed ledger, readiness, and all 19 germplasm endpoints' roles/filters/ladder positions.

### Pass 3 — `routes_trials.py`, `routes_gates.py`

129,238 -> 132,228 chars (+2,990), still 452 lines — all in-paragraph. **12 ambiguity-pins, 5 mismatch-revisions:**

- §2.7 step 16 — revise — mismatch — list said "eight operations" and omitted decision recording; impl calls `line_not_discarded` for every decision -> now "nine operations… recording an advancement decision of any kind" — `routes_gates.py:53`
- §2.7 step 34 — revise — mismatch — the `rep_number >= 1` lower bound is a step-3 range rule (400), only the upper bound draws `ERR_DUPLICATE_OBSERVATION`; also pinned range-before-duplicate order — `routes_trials.py:300,313`
- §2.9 — insert — ambiguity — `expected_line_version` / `expected_series_version` are integers >= 1, so 0 or negative is a 400 shape failure, not a 412 — `routes_trials.py:453`, `routes_gates.py:41`
- §3.5 (site registration) — revise — ambiguity — `plot_cost_usd` is stored rounded half up to 2 places rather than rejected; a `season_end_date` not strictly later than the start draws `ERR_INVALID_REQUEST` (400) at the shape step, before the `site_code` uniqueness check — `routes_trials.py:36,39-45`
- §3.5 (trial series) — insert — ambiguity — `season_year` is a whole number of at least 1 — `routes_trials.py:78`
- §3.5 (trial entry creation) — revise — ambiguity — new entry also carries `withdrawal_reason` null — `routes_trials.py:175`
- §3.6 (observations) — revise — mismatch — `value` is stored exactly as supplied; more than three decimals is neither rejected nor re-rounded; `rep_number` at least 1 — `routes_trials.py:300-301`
- §3.6 (observations) — revise — mismatch — split the two `rep_number` bounds: below 1 -> `ERR_INVALID_REQUEST`, above `replication_count` -> `ERR_DUPLICATE_OBSERVATION`, range check before duplicate scan — `routes_trials.py:313-319`
- §3.8 (ADVANCE ladder) — insert — ambiguity — an `ADVANCE` aimed at a line already `COMMERCIAL` has no rung and is refused with `ERR_SERIES_INVALID_STATE` — `routes_gates.py:61-64`
- §3.8 (ADVANCE plot budget) — insert — ambiguity — `granted_plots` is tested against `plot_budget_remaining` *before* the superseded decision's plots are released — `routes_gates.py:101` vs `119`
- §3.8 (commercial gate) — insert — ambiguity — a zero `planned_launch_units_bags` also draws `ERR_STEWARDSHIP_NOT_APPROVED`, tested after the two stewardship checks — `routes_gates.py:77-79`
- §3.8 (series closure) — revise — ambiguity — the live decision must cite that same series, and any decision kind counts — `routes_trials.py:244-247`
- §3.9 (agreement drafting) — revise — ambiguity — `suspension_reason` opens null; drafting sets `stewardship_status` to `PENDING` whatever it held, including `SUSPENDED` — `routes_gates.py:203,207-208`
- §3.9 (review) — revise — ambiguity — empty/whitespace `requested_changes` on `REQUEST_CHANGES` is a 400 at the shape step, ahead of the agreement state check; `APPROVE` ignores the field — `routes_gates.py:266-268,279-286`
- §3.9 (lot reservation) — revise — ambiguity — allocations are stored as exactly `market_code`+`demand_kg` (other keys dropped), allocation `market_code`s are not checked against the agreement, `launch_year` >= 1 — `routes_gates.py:344,366`, `validators.py:268-287`
- §3.9 (lot cancel) — revise — ambiguity — an omitted `hold_reason` leaves the stored one intact (`STEWARDSHIP_SUSPENDED` out of `ON_HOLD`, null out of `RESERVED`) — `routes_gates.py:466-467`
- §4 `/trial-entries/{id}/invalidate` row — revise — mismatch — the row claimed "the plots stay committed"; `recompute_program` excludes `INVALIDATED` from the active set, so the plots are released while the series census keeps its place (as §3.6 already states) — `routes_trials.py:424` + `derive.py:16,118`

Verified as already uniquely pinned (no edit): all 31 role lists for these endpoints match §4; the full entry-admission check order (§3.5) and series-planting/costing order (§3.6); posture re-derivation trigger list; `bubble_series_data_complete`; analysis inclusion/core-site rule, both array orderings with `created_at`+sequence tie-breaks, supersession and provisional-index recompute order; decision supersession/`from_stage`/`to_stage`/index freezing; suspension cascade order; lot lifecycle and ledger arithmetic.

### Orchestrator final verification

- `PRD_COMPLETED.md` is **452 lines / 132,228 chars** vs `PRD_FINALIZED.md`'s 448 / 119,642 — `cmp` reports **DIFFERS**, so the scan demonstrably ran (a byte-identical Step 9 output would mean it did not).
- The file still ends at a real section boundary: the final row of the §5 error-catalogue table (`ERR_INSUFFICIENT_SEED_INVENTORY | 409 Conflict`) — not truncated.
- `find` over `workspace/implementation/`, `test_suite/` and `test_helpers/` for anything modified after the 10:13 green sweep returns **nothing** (excluding `results.*.json` and `__pycache__`), so Steps 8 and 9 were documentation-only and the 8/8 × 82/82 sweep evidence still describes the shipped code.
- Exactly one `worklog.md` exists, at the task root — no stray copy drifted into `workspace/`.

**Pipeline complete: Step 9 has written `workspace/PRD_COMPLETED.md`.**
