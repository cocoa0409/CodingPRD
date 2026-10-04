# Worklog — task_3333_electrical_contractor_prefabrication_model_coordination

## Step 1: Create task directory — 2026-10-01T00:00:00.000Z

Task directory `./tasks/task_3333_electrical_contractor_prefabrication_model_coordination/` was pre-allocated by the caller with `workspace/` inside. No new index computed, no other task_* directory created.

## Step 2: Generate scaffold — 2026-10-01T04:07:22.532Z

Completed after a process interruption (host killed background processes under memory pressure) and one earlier attempt that died on the 32000-output-token cap. Orchestrator verified all three artifacts on disk — complete files, all parse as valid YAML (no truncation):

- `SCAFFOLD.yaml` — 2864 lines, 154125 bytes. Top-level keys: scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles. Contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1188 lines, 47299 bytes. Single top-level key `scaffold_difficulty_design` (list of 9 rules, 19 instances).
- `SCAFFOLD_CORNER_DESIGN.yaml` — 622 lines, 100184 bytes. Single top-level key `scaffold_corner_design` (list of 3 sections, 17 instances).

Element counts in SCAFFOLD.yaml: 15 entities, 9 state machines, 16 calculations, 31 validations, 40 endpoints, 31 errors, 8 roles, 4 concurrency rules.

§1.8 difficulty rules (instances each): dual_variant_calc 2, combinatorial_formula 2, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 2, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 2 — 9 rules / 19 instances total.

§1.9 corner sections (instances each): entities 7, state_machines 6, calculations 4 — 3 sections / 17 instances total.

Endpoint count is exactly 40, at the stated ceiling (a prior memory notes >40 endpoints degrades the Step 6 implementation-generator); not above it, so proceeding.

## Step 3: Copy shared files — 2026-10-01T04:07:38.886Z

Copied `./INSTRUCTION.md` → `./tasks/task_3333_electrical_contractor_prefabrication_model_coordination/workspace/INSTRUCTION.md` (1424 bytes). md5 verified identical on both sides: `60ec3841647dd4af7332162d5ff7b3c1`.

## Step 4: Generate PRD — 2026-10-01T04:17:19.985Z

Output: `workspace/PRD.md` — 410 lines, 111,607 bytes. Orchestrator verified on disk independently of the subagent report: file exists, ends cleanly at the §5 error table (no footer, no truncation), 40 endpoint table rows + header, 31 error table rows + header, 31 distinct `ERR_*` ids.

Top-level headings: §1 Introduction; §2 Global Specifications & System-Wide Principles (2.1 RBAC · 2.2 API Response Structure · 2.3 Pagination · 2.4 Resource Identity/Versioning · 2.5 The Logical Clock · 2.6 Optimistic Concurrency on the Four Decision Points · 2.7 Numeric Precision and Rounding · 2.8 The Order in Which Validations Are Evaluated · 2.9 Hierarchical Addressability and Reference Resolution · 2.10 Derived Quantities, Recomputes and Conserved Balances · 2.11 Capacity and Conflict Guards); §3 Business Logic & Workflows (3.1–3.9); §4 Endpoint Definitions; §5 Error Code Catalogue.

Subagent's returned summary, verbatim:

```
Done. PRD generated and verified against the doc-generator skill's contracts.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3333_electrical_contractor_prefabrication_model_coordination/workspace/PRD.md`
**Size:** 411 lines, 111,607 bytes

**Top-level headings:**
- `# Electrical Contractor Prefabrication & Model Coordination API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` (2.1 RBAC · 2.2 API Response Structure · 2.3 Pagination · 2.4 Resource Identity/Versioning · 2.5 The Logical Clock · 2.6 Optimistic Concurrency on the Four Decision Points · 2.7 Numeric Precision and Rounding · 2.8 The Order in Which Validations Are Evaluated · 2.9 Hierarchical Addressability and Reference Resolution · 2.10 Derived Quantities, Recomputes and Conserved Balances · 2.11 Capacity and Conflict Guards)
- `## 3. Business Logic & Workflows` (3.1 Coordinated Model/Extraction/Racks · 3.2 Jobsite, Energization Anchor and Five-Tier Posture Ladder · 3.3 Work Packages and the Release Gate · 3.4 Fabricated Components, Chain Dependencies and Field Installation · 3.5 Trade Activities, Installation Sequence and Crew Days · 3.6 Labor Rates, Apprentice Ratio Cap and Payroll · 3.7 Design Revisions, Rework Loop and Two Cost Memos · 3.8 The Commercial Rollups · 3.9 Procurement Releases, Lead Times and the Material Gate)
- `## 4. Endpoint Definitions` (40-row table, 4 columns)
- `## 5. Error Code Catalogue` (31-row table, 2 columns)

**Hard contract reports (agent transcript only; no audit footer in PRD.md):**
```
Field coverage check:
- entities[].fields: 222 required, 222 present, 0 missing
- endpoints[].request_body: 124 required, 124 present, 0 missing
- endpoints[].query_params: 21 required, 21 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 31 checked, 31 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 4 checked, 4 expressed (write_endpoint + expected_<parent>_version + error_id named), 0 missing
- state_machines[].transitions: 45 checked, 45 fully expressed, 0 missing
- calculations[]: 16 checked, 16 fully expressed, 0 missing
- validations[] conditions: 31 checked, 31 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 40 checked, 40 expressed, 0 missing
- entities[].fields[] structured content: 222 checked, 222 reconstructible, 0 missing
- sibling-branch symmetry: 9 groups checked, 9 equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 993
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Also verified: §2.2 is byte-identical to `section-2.2-response-structure.md`; all 8 roles, all enum members and all state values appear as exact backticked strings; all 31 error IDs appear in §2/§3; every `calculations[].constants` value is embedded in business prose; document ends at §5 with no footer. Neither withheld design file nor any sibling task was read.
```

Note: the subagent reported 411 lines while `wc -l` reports 410 — an off-by-one from whether a trailing newline is counted. The file is complete either way; no action needed.

## Step 5: Generate unit tests — 2026-10-01T04:31:30.733Z

The subagent terminated with a transient API error (`model_not_found` on deepseek-v4p1-flash-wave) partway through, but it had already flushed every file to disk. The orchestrator did NOT trust an absent hand-back report and instead audited the artifacts directly. Status: **complete**.

Files on disk — `test_helpers/` (1783 lines total), 9 modules matching the skill's required layout:
- `__init__.py` 778 B · `types.py` 11571 B · `api_client.py` 8320 B · `api_errors.py` 3735 B · `assertions.py` 5147 B · `factories.py` 7424 B · `constants.py` 3309 B · `test_users.py` 912 B · `fixtures.py` 21608 B

`test_suite/` (2293 lines total):
- `conftest.py` 1036 B · `test_10_design_revision_pricing.py` · `test_11_state_shapes_and_invariants.py` · `test_12_booking_conflicts.py` · `test_20_entity_creation_and_validation.py` · `test_21_state_machine_boundaries.py` · `test_22_project_rollups_and_boundaries.py` · `test_23_cross_entity_gates.py` · `test_24_validation_order_and_boundaries.py`

Independent verification performed by the orchestrator:
- `python3 -m py_compile` on all 17 files → ALL COMPILE OK (no truncation mid-expression).
- Every test file ends at a complete statement (no dangling parens / half-written assert).
- 62 test functions in total; 62 `Design:` tag occurrences; **0 untagged** (AST-parsed docstrings, not grep).
- Tag-to-instance cross-check against both design YAMLs: 36 expected instances (19 §1.8 + 17 §1.9), 36 distinct tags found, **0 missing, 0 extra** — full instance coverage with no skip/xfail placeholders.
- Every tag names an instance that actually exists in the source yaml's `name:` field.

62 functions across 36 instances reflects some instances being translated into more than one test (multi-phase scenarios such as the cascade and compensating-invariant rules), which the design-index-only contract permits as long as each test carries exactly one valid tag.

### Step 5 addendum — pre-Step-7 artifact repair (found by the orchestrator)

**Correction to Step 5 / pre-Step-7 repair.** Before the Step 7 fix agent could start, the orchestrator ran a single diagnostic round and found the suite could not even be collected:

```
ImportError while loading conftest '.../test_suite/conftest.py'
conftest.py:4: from test_helpers import TEST_USERS, ApiClient, api_client
../test_helpers/__init__.py:25: from .factories import *
../test_helpers/factories.py:2: from .constants import (... RATE_EFFECTIVE_FROM_ISO ...)
E   ImportError: cannot import name 'RATE_EFFECTIVE_FROM_ISO' from 'test_helpers.constants'
```

The Step 5 results reported 0/0 passed with 1 error, i.e. zero tests ran — the apparent "36/36 instance coverage" the orchestrator verified in Step 5 was structurally correct (all files present, all tags valid, all files compile) but the package could not import. My Step 5 audit checked tags, line counts and `py_compile` per file, none of which exercise cross-module imports. Two defects, both caused by the Step 5 subagent dying mid-write:

1. `test_helpers/constants.py` — `RATE_EFFECTIVE_FROM_ISO` existed only as a key inside the `TEST_DEFAULTS` dict, never as a module-level name, yet `factories.py:5` imports it directly and uses it at `factories.py:146` for a rate row's `effective_from_iso`. Fixed by adding the module-level constant (value `2026-01-01T00:00:00Z`, matching the value already present in `TEST_DEFAULTS`).
2. `test_suite/test_10_design_revision_pricing.py` — imported `install_foreman_headers` from `test_helpers`; that name is a dict *key* in `test_users.TEST_USERS`, never a module-level export. The canonical alias is `INSTALL` (`fixtures.py:19`). The imported name was never referenced anywhere in the file, so the correct fix was deleting the dead import rather than inventing an alias.

Both fixes are test-side (Step 5 artifact repair), not implementation-side. After them, `python3 -m pytest test_suite --collect-only` collects **62 tests, 0 errors**.

A systematic audit was then run to rule out further instances of the same defect class: AST-based comparison of every name imported from `test_helpers` (12 distinct names across all test modules) against the actual package namespace, and of every intra-package `from <module> import <name>` against what each module defines. Result: 0 remaining missing names. Note the first check performed (before the fix) found the `install_foreman_headers` case but not the `constants` case, because the latter is an intra-package import between helper modules rather than a test-suite import; both audits were needed.

History of failed Step 7 launches (all model-endpoint failures, no work lost): the first long-lived Step 7 subagent was spawned and immediately died on the same `model_not_found` (HTTP 404) endpoint error that killed Steps 5 and 6. It had issued the 8-round sweep, which produced 8 identical `results.${i}.json` files each reading `{"total": 0, "passed": 0, "errors": 1}` — the collection error above. Those stale files were deleted before re-running.

**Lesson recorded for future runs:** a Step 5 subagent that dies mid-write leaves a package whose files each compile but whose cross-module imports dangle. `py_compile` and per-file tag audits do not catch it. The only reliable check is a real `pytest --collect-only` (or importing the package) before handing off to Step 7.

## Step 6: Generate implementation — 2026-10-01T04:50:53.468Z

The Step 6 subagent died twice: first on the model-endpoint 404, then a retry died again after writing 11 modules but before the entry point. The orchestrator inspected disk state rather than trusting the absent report, found `app.py` / `start.sh` / `requirements.txt` missing, and launched a **Step 6b completion subagent** scoped to the launcher plus surgical gap fixes. Status: **complete**.

Final `workspace/implementation/` — 14 files, ~4300 lines, all pass `python3 -m py_compile`:
`app.py` 71 · `calculations.py` 581 · `compliance.py` 128 · `components.py` 192 · `core.py` 398 · `labor.py` 450 · `models.py` 231 · `orders.py` 635 · `procurement.py` 138 · `projects.py` 281 · `revisions.py` 598 · `requirements.txt` · `routes.py` 415 · `start.sh` (executable)

**Orchestrator verification, independent of the subagent reports:**
- All 40 endpoints in PRD §4 are present in `routes.py`, verified by a symmetric method+path diff against the PRD table (0 missing).
- The blueprint is registered as `app.register_blueprint(routes.bp, url_prefix="/prefab")` (app.py:26), matching the PRD's stated `/prefab` mount prefix — route decorators are written bare.
- **Boot verified by the orchestrator itself**: launched `PORT=18771 bash start.sh` in the background, confirmed a `0.0.0.0` listener, `GET /prefab/_clock` → 200 with the §2.2 envelope, missing headers → 401 `ERR_UNAUTHORIZED`, and a full `POST /prefab/projects` → 201 returning derived posture/balance fields. Server then stopped by killing the exact PIDs started (no broad patterns).
- Storage remains in-memory (no SQLite/JSON/tmp persistence); no entity data is seeded at startup.

Subagent's returned summary (Step 6b), verbatim:

```
Step 6 complete. The server boots and serves the `/prefab`-prefixed API.

**Files written**
- `workspace/implementation/app.py` (71 lines) — Flask app; registers `routes.bp` with `url_prefix="/prefab"`; `ApiError` handler renders the §2.2 error envelope; 404/405/500 fallbacks also emit the envelope; exposes `app`; reads `PORT` (default 10000), binds `0.0.0.0`. No seeding.
- `workspace/implementation/requirements.txt` (6 lines) — Flask 3.1.3 + transitive pins matching the host's install (verified via `importlib.metadata`).
- `workspace/implementation/start.sh` (12 lines, executable) — guards `pip install` behind `python3 -c "import flask"`, defaults `PORT`, `exec python3 app.py` in foreground.

**Boot command** (from the implementation dir): `bash start.sh` — verified via a real background launch on ports 17333/17344; `GET /prefab/_clock` returned 200 within ~1.5s and `ss` confirmed a `0.0.0.0` listener.

**Smoke evidence** (17 resource groups + full lifecycle, driven through `bash start.sh` and a test client): project create 201; `GET /prefab/projects/{id}` 200; unknown project 404 `ERR_PROJECT_NOT_FOUND`; missing headers 401 `ERR_UNAUTHORIZED`; wrong role 403 `ERR_FORBIDDEN`; `limit=999` 409; unprefixed `/` and `/prefab/nope` 404; all list endpoints 200 with `limit/offset/total_count/has_more` in `meta`. Ran an end-to-end loop (project → model version → assemblies → takeoff line → coordinate → racks → order → component → release → fabricate → material release → declare → revision → submit → approve → `POST /prefab/revisions` rework cascade), confirming approve produced `impact_values` and `approved_change_value_cents: 36816`, with a smoke-level scan finding zero internal errors. All five smoke-server PIDs were stopped individually; no broad kill patterns used.

**Surgical fixes (all genuine gaps, not rewrites)**
1. `projects.py` — added the missing `require_project()` (routes.py line 55 called it; `AttributeError` on every `GET /projects/{id}` and every posture recompute). Matches the canonical helper in `labor.py`.
2. `procurement.py` (×2) and `revisions.py` (×1) — `from orders import recompute_all_releasable, fabrication_locked` raised `ImportError`: `fabrication_locked` lives in `projects.py`. Split the imports. This broke material-release creation/declaration and revision cascades entirely.
3. `procurement.py` — removed the `receiving_user_id` existence check against `workers`. PRD §2.1 states explicitly that `receiving_user_id` is an opaque operator identity, never compared to a persisted entity; the check rejected any valid release.

**Two notes for downstream steps (not fixed, no legal error id exists)**
- PRD §3.9 and the `MaterialRelease.lead_time_days` field description say a `SWITCHGEAR` release's quoted lead time must be at least 90 days. No `ERR_*` constant in PRD §5 or the scaffold error catalogue covers this, and both omit it from `validations[]`, so I left it unenforced rather than inventing an error id.
- `errors.py`, `db.py`, `response.py` and `middleware.py` from the skill's suggested layout do not exist; the surviving 11 modules consolidated those concerns into `core.py`, which is what I wired against (envelope helper `build_envelope`/`envelope_error`, store `DB`, clock `CLOCK`, auth `require`). No entity data is seeded at startup, and storage remains in-memory only.
```

**Orchestrator note on a PRD/scaffold disagreement found during verification (for Step 7 attention, NOT fixed here):**
`POST /prefab/assemblies` is implemented and is exercised by the test fixtures, and the `Assembly` entity is one of the scaffold's 15 entities — but that endpoint is **absent from the PRD §4 endpoint table and from `SCAFFOLD.yaml`'s `endpoints[]`**. The generator nevertheless emitted it (correctly: without it no assembly catalog can exist, and takeoff lines reference `assembly_code`). This is a doc-generator coverage gap of the same class as the two notes above; flagged so Step 7 does not mistake the endpoint for an invented capability.

## Step 7: Run tests and iterate — 2026-10-01T04:55:45.786Z

Status: **COMPLETE — verified green.**

**Baseline established by the orchestrator** (8-round parallel sweep, `--isolation per-test-server`): **38/62 passing, 24 failing, byte-identical across all 8 rounds** — fully deterministic, zero flakiness.

An earlier baseline of 24/62 was measured before the orchestrator noticed that an interrupted Step 7 subagent had already edited `test_suite/test_12`, `test_24`, `test_10`, `test_23`, `test_helpers/fixtures.py`, `test_11`, `test_22` (mtimes 05:12–05:37, well after Step 5's 04:20–04:30). Per the standing rule that post-sweep artifact writes invalidate a sweep, that stale 24/62 figure was discarded and the sweep re-run to get the 38/62 ground truth.

**Failure clusters handed to the Step 7 subagent** (all diagnosed by the orchestrator from the sweep JSON, with root causes verified against PRD text and, for two clusters, empirically against a live server):
- Cluster A (~10 tests): revision approved without being submitted. PRD §3.7 line 282 states *"It requires the revision to be `SUBMITTED`"*; `setup_revision_ready` returned a DRAFT revision. `test_24`'s passing submit-then-approve pattern was the reference.
- Cluster B (2 tests): `SLIP_FREEZE_AT: 0.60` literal with slippage 1.2 asserted `HOLD`; PRD §3.2 makes 1.2 > 0.60 `FROZEN`.
- Cluster C (2 tests): clock literals `2026-10-03`/`04` with a 100-day activity gave shortfall 0; PRD §3.2's formula is `clock − planned_start − planned_duration_days`. Verified empirically: clock `2027-01-11` → shortfall 2, span 100, slippage 0.02, ON_TRACK.
- Cluster D (3 tests): `ERR_APPRENTICE_RATIO_EXCEEDED` during crew-day setup.
- Cluster E (7 tests): individual off-by-ones, ordering and persistence-on-refusal defects.

**Orchestrator verification of the subagent's green claim** (the hand-back was NOT taken on trust):
- All 8 `results.{i}.json` read directly: `passed=62/62, failed=0, errors=0, skipped=0` in every round.
- `find … -name '*.py' -newer results.1.json` returns empty → every source edit predates the green sweep, so the sweep is not stale.
- No `pytest.mark.skip` / `xfail` / `skipif` anywhere in `test_suite/` or `test_helpers/`; 0 tests deleted.
- No `sqlite3` / `json.dump` / file writes / `/tmp` paths in `implementation/*.py` — storage remains in-memory.
- Test suite still collects 62 tests with 36 distinct design tags (unchanged coverage).
- Spot-checked three claimed implementation fixes against source and confirmed each: `revisions.py::create_revision` fails before any `DB.put`; `compliance.py` ledger rows are activity-scoped (`ledger_rows_for_activity`); `labor.py` carries the `DISALLOWED → ACTIVE` "resume" transition and clears `suspension_reason`.

Subagent's returned summary, verbatim:

```
Sanity checks all pass: the newest source file (08:56:01) predates the results files (08:58:15), so the green sweep post-dates every edit; `pytest --collect-only` still reports 62 tests with 0 errors; no `skip`/`xfail` and no new persistence were introduced; all 8 results files are on disk.

## Summary

**Iterations run:** 1 full 8-round sweep (from the orchestrator's 38/62 baseline) → **8/8 rounds at 62/62, 0 failed, 0 errors, 0 skipped**. No tests deleted. Two PRD-internal tensions were resolved in favour of the normative definition rather than by weakening assertions (both flagged below).

**`test_helpers/` fixes**
- `fixtures.py::setup_revision_ready` — successor now gets a takeoff line and the revision is **submitted**; PRD §3.7 requires `revised_version_id` to name a version "whose zone quantity total is at least 1" and approval "requires the revision to be `SUBMITTED`". The fixture previously handed callers a DRAFT revision.
- `fixtures.py::setup_loaded_component` — fabricate components **while the order is `IN_FABRICATION`**, then advance the order to `FABRICATED`; PRD §3.4 requires the owning package to be `IN_FABRICATION` to fabricate.
- `fixtures.py::setup_loaded_component` — books arrival inside the frozen hoisting window (`LOADED_REQUIRED_ON_SITE_ISO`); PRD §3.3 makes loading conditional on `required_on_site_iso` falling inside that window.
- `fixtures.py::setup_crew_pair` — new `project_journeyman_hours` ballast on a second activity; PRD §3.6 refuses any report pushing the **project-wide** apprentice total past `ratio_limit` × journeyman total, so an activity-scoped breach (§3.5) is only reportable while the project stays legal.
- `fixtures.py::setup_crew_pair` — returns the **live** activity row; acknowledgment is what drives the §3.5 ratio cascade, and the old return was a creation-time snapshot.

**`implementation/` fixes**
- `compliance.py::recompute_ledger_row` — cumulative hours are scoped to the **activity**, not the worker; PRD §3.6 says "on the activity", and that is what makes `excess_apprentice_hours` a statement about the crew.
- `compliance.py::recompute_ledger_row` — `original_apprentice_hours` is seeded before the delta, so a fresh row satisfies the §3.6 conservation identity (`apprentice_hours == original + adjustment_delta_hours`).
- `compliance.py::refresh_ledger_for_crew_day` — sibling rows of the same activity are recomputed together, since they carry the same activity totals.
- `labor.py::acknowledge_crew_day` — **resumes** a `DISALLOWED` activity when the crew returns inside the cap and recomputes `apprentice_breach_flag`; PRD §3.5 states the activity "returns to `ACTIVE`, its `suspension_reason` is cleared to null".
- `revisions.py::create_revision` — validates **before** `DB.put`; a refused creation no longer writes a row (PRD §2.4, no partial mutation).
- `revisions.py::affected_components` (new) + approval cascade — expands takeoff-hash and rack-code impacts to their components; PRD §3.7 says "each naming impact drives the affected `FABRICATED` component to `REWORK`", but only component-keyed impacts were being queued.

**Test-literal corrections (test-side, PRD-driven)**
- `test_10` — `math.ceil(9.6) == 10`, not `int(9.6) == 9` (§3.3 "rounded up to a whole number of days"); `_aggregation_scenario` returns the post-release order because `assembly_count` is derived (§3.3); local pricing fixture submitted.
- `test_12::_capacity_one_scenario` — the two packages now differ in `hoisting_window_id` **and** `stage_code`; the old shared window tripped the hoisting guard, which §2.8 evaluates *before* the laydown-slot guard.
- `test_21` — compares the component status before/after the refused call instead of asserting a stale `FABRICATED` literal (the shop dimension had advanced, not the component).
- `test_22` — clock literals moved to `2027-01-11`/`2027-01-12`; the old `2026-10-03`/`04` gave a shortfall of 0 because §3.2 measures `clock − planned_start − planned_duration_days`; ring-hours setup uses 16.0 journeyman hours behind two 8.0-hour apprentice reports.
- `test_23` — posture ladder `SLIP_FREEZE_AT` 0.60 → 1.50 (slippage is 1.2, so 0.60 put the project in `FROZEN`, not the intended `HOLD`); `_create_order` arrival moved inside the frozen window; the declared-commodity gate now asserts `ALLOWED`.

**Two PRD tensions resolved (worth a doc pass):** §3.3's ladder ("`ALLOWED` when the posture is `ON_TRACK` and every gate passes") contradicts §3.9's narrative "recomputes from `MATERIAL_HOLD` to `READY`" — I kept the §3.3 definition. Likewise §3.6's project-scoped ratio **guard** coexists with its activity-scoped **ledger** hours; the two must differ or `DISALLOWED` is unreachable.
```

**Orchestrator note — the two PRD tensions the subagent flagged are genuine doc-generator defects** and are carried forward to Step 9 as ambiguity-pin candidates:
1. §3.3 vs §3.9 on the release-gate value after a commodity is declared (`ALLOWED` per the §3.3 ladder vs `READY` per the §3.9 narrative).
2. §3.6 project-scoped ratio guard vs activity-scoped ledger hours — the two scopes must differ or `DISALLOWED` is unreachable.

Also carried forward: the `POST /prefab/assemblies` coverage gap (implemented and fixture-used, absent from the §4 table) and the two known silences (no error id for the §3.9 SWITCHGEAR lead time; `receiving_user_id` opaque per §2.1).

## Step 8: Finalize PRD — 2026-10-01T09:20:50.166Z

Not skipped: Step 7 ran with 5 `test_helpers/` fixes, 6 `implementation/` fixes and multiple `test_suite/` literal corrections, so `PRD.md` did not already determine every behavior the implementation exhibits.

Output: `workspace/PRD_FINALIZED.md` — 410 lines / 113,827 bytes vs `PRD.md` 410 lines / 111,607 bytes (0.0% line delta; all 9 edits are inline within existing lines). Orchestrator verified the file exists, matches `PRD.md`'s line count, and that the §2–§5 headings, 31 error-table rows and 40 endpoint-table rows are all preserved.

Nine inline edits across 6 hunks: §2.4 (refused creation stores no row), §3.5 (acknowledgment recomputes the ledger row from the activity's non-voided crew days), §3.6 ×3 (activity-scoped ledger hours; `original_apprentice_hours` seeding; the ratio guard's project-scoped journeyman side), §3.7 ×2 (impact-key expansion to components; rejection lifts the gate under §3.3 precedence), §3.9 ×2 (receipt and declaration lift `MATERIAL_HOLD` under §3.3 precedence). Each was traced to a Step 7 fix and verified against the running implementation (the subagent ran 12 targeted behavioral checks, 12/12 passing).

Subagent's returned summary, verbatim:

```
All checks pass and my server is cleaned up (port 18473 released; I killed only the PID I started). Final state verified: PRD_FINALIZED.md is 410 lines (identical line count to PRD.md, 0.0% delta — every edit is inline within an existing line), all §2–§5 headings, all 31 error-table rows and all 40 endpoint rows preserved, and `implementation/` still compiles untouched.

**Sanity check:** I booted `implementation/` on a private port and ran 12 targeted behavioral assertions covering every edit — all 12 pass. That included catching a real trap: my first "restarts" never bound the port (I had killed the wrong PID), so stale server state was producing a false FAIL on the edit-6 rack-code expansion; after killing the actual listener (2817374) and re-running on a verified-fresh server, all checks pass. Result: `/home/ubuntu/github/CodingPRD/tasks/task_3333_electrical_contractor_prefabrication_model_coordination/workspace/PRD_FINALIZED.md`

**Changes (9 edits, 6 hunks, 16 changed lines):**
- §2.4 — insert — a refused creation stores no row for the resource it would have created — `implementation/revisions.py:190-191` (validation moved before `DB.put`), consistent with `components.py:70-78` (post-put rollback)
- §3.5 — revise — acknowledgment recomputes the ledger row's cumulative hours "from the activity's non-voided crew-day rows" and re-derives those totals on every other ledger row of the activity — `implementation/compliance.py:51-58,133-137`
- §3.6 — insert — `apprentice_hours`/`journeyman_hours` are the activity's totals over all crew days booked to it (whichever worker), so sibling rows agree — `implementation/compliance.py:51-60`
- §3.6 — insert — `original_apprentice_hours` is seeded to the hours a fresh row just accumulated, `adjustment_delta_hours` starts at 0 and later carries the signed difference — `implementation/compliance.py:64-72,113`
- §3.6 — revise — the ratio guard's journeyman side is the project's, counted across every crew day of the project, and is explicitly a different total from the ledger row's activity scope — `implementation/labor.py:378-387` (+ rate path `:112-125`)
- §3.7 — revise — approval expands each impact key to the components it reaches (takeoff hash → components on that line, rack code → components on that rack, component code → itself); FABRICATED → REWORK + open job, SCRAPPED → deferred job, any other status kept with an open job — `implementation/revisions.py:337-347,452-454,476-486`
- §3.7 — revise — rejection lifts the gate under the §3.3 precedence (ALLOWED on ON_TRACK, not READY) — `implementation/revisions.py:460-473` → `orders.py:161-184`
- §3.9 — revise — receipt lifts MATERIAL_HOLD under the §3.3 precedence — `implementation/procurement.py:118-133` → `orders.py:174-183`
- §3.9 — revise — declaration lifts MATERIAL_HOLD under the §3.3 precedence, and an undeclared gate commodity still holds — `implementation/procurement.py:127-129` → `orders.py:145-158,177-184`

**Per-edit pre-edit search log (subject / paths enumerated / wording adjustment):**
1. *Refused-creation persistence.* Enumerated all 15 `DB.put` callsites (`grep -rn DB.put`) and read each creation function: every failing path validates before `put` except `create_component`, which deletes the row and restores rack occupancy. Adjustment: wrote "stores no row for the resource it would have created" rather than "leaves no trace", because `create_revision` calls `new_record`/`DB.next_seq()` before validating and `create_component` stores then rolls back.
2. *§3.5 acknowledgment recompute source.* Enumerated `acknowledge_crew_day` → `refresh_ledger_for_crew_day` → `recompute_ledger_row` → sibling loop; confirmed `refresh_project_ledger` and `set_activity_status` never recompute rows. Adjustment: attributed the recompute to acknowledgment only (creation never touches the ledger) and pointed at §3.6 for the scope.
3. *Ledger cumulative-hour scope.* Enumerated `recompute_ledger_row`, `refresh_ledger_for_crew_day`, `_project_wide_hours`, `refresh_project_ledger`, `labor.activity_crew_excess`, `set_activity_status` (complete/suspend/resume), `projects.apprentice_breach_active`. Adjustment: said "every crew-day row booked to that project and activity" — deliberately not "acknowledged", since the sum includes unacknowledged days.
4. *Conservation baseline.* Enumerated both writers of `original_apprentice_hours`/`adjustment_delta_hours` (only `recompute_ledger_row`) and confirmed no other module reads them. No adjustment needed.
5. *Ratio guard scope.* Enumerated `labor.project_hours`, `enforce_ratio_cap` (incl. the zero-journeyman branch, already implied by the PRD's inequality), `check_rate_ratio_impact` (rate-row path sums the same project-wide set), and contrasted with the ledger scope from edit 3. Adjustment: qualified only "the journeyman hours" as the project's, leaving the existing "summed per project and per classification" verbatim.
6. *Impact-key expansion.* Enumerated `resolve_impact_key`, `affected_components`, the approval loop, `_queue_rework`, `create_rework_job`, `affected_orders_for`, `commodities_for_impacts`, `revision_cost_impact`. Adjustment: defined only how each key *expands to components*, not what a component key resolves to, since `resolve_impact_key` also accepts an `assembly_code` — that existing PRD sentence is left untouched.
7–9. *Gate value when a hold lifts.* Enumerated the single precedence function `orders.compute_releasable_status` and every caller that lifts a hold (`procurement.declare_release`, `revisions._reject_revision`, submission's `close_affected_release_gates`, plus all `recompute_all_releasable` sites). Adjustment: fixed all three sites that asserted "back to `READY`" (§3.7 rejection, §3.9 receipt, §3.9 gate) so no site contradicts the others; added "any engineering hold that still applies continuing to win" so the wording is not narrowed to the material case.

**Out-of-scope divergences I found but did NOT edit** (no `<step_7_diff>` item traces to them): the ledger row's `regular_hours`/`overtime_hours` are seeded with the first crew day's hours and then accumulate that same day again (`compliance.py:97-98` vs `:121-122`), double-counting the first day — §3.6 never defines those two fields; `_tied_shipment_hours` (`revisions.py:250-259`) has no `return` (a stray `print_guard = None` at module level) so `tied_shipment_hours` is always 0.0; and the ratio guard resolves its `ratio_limit` as of the logical clock (`labor.py:380`, `as_of=None`) where §3.6 says the governing row is chosen by the crew day's `work_date_iso` (the ledger path does use the work date).
```

**Orchestrator follow-up — the three out-of-scope divergences were verified against source and all three were real.** Rather than leave known PRD contradictions in the shipped implementation, the orchestrator fixed them and re-validated:

1. `revisions.py::_tied_shipment_hours` — the function accumulated `total` and then fell off the end (line 259 was a module-level stray `print_guard = None`, so the body ended at 258), making the function return `None` and `tied_shipment_hours` always 0.0. PRD §3.7 defines the field as the craft hours of components on the superseded lines whose install status is `FABRICATED`, `LOADED` or `SET` — and the implementation's status filter already matched that sentence exactly, so the *only* defect was the missing return. Added `return total` and removed the stray statement. Verified no test asserts `tied_shipment_hours`/`shipment_tied_flag`, so this is a strict gain in PRD fidelity.
2. `compliance.py::recompute_ledger_row` — a new ledger row was seeded with the crew day's `regular_hours`/`overtime_hours` and then accumulated the same crew day again at lines 121-122, double-counting the first day. Changed the seed to `0.0` (matching the other accumulators). Verified by grep that the ledger row's `regular_hours`/`overtime_hours` are written but never read anywhere — every consumer reads the crew day's own fields — so this is behaviorally inert and cannot perturb the suite.
3. `labor.py::enforce_ratio_cap` — resolved `ratio_limit` via `ratio_limit_resolution(project, worker)` with no `as_of`, i.e. as of the logical clock, while PRD §3.6 states verbatim that the governing row is *"the latest rate row for the project's `jurisdiction_key` whose `effective_from_iso` is at or before the crew day's `work_date_iso`"*. Added a `work_date_iso` parameter and threaded `body.get("work_date_iso")` from the single callsite (labor.py:331), matching what the ledger path (`compliance.py:87`) already did.

**Re-validation:** because these edits touch `implementation/` after a green sweep, the full 8-round parallel sweep was re-run. Result: **62/62 passing, 0 failed, 0 errors, 0 skipped in all 8 rounds**, and `find … -newer results.1.json` confirms every source file predates the new green sweep.

Note: `PRD_FINALIZED.md` was written *before* these three fixes, so its §2.4/§3.5/§3.6/§3.7/§3.9 wording was derived from the pre-fix code. None of the three fixes changes any behavior that Step 8 pinned (two are inert, and the third only changes which rate row governs when several straddle the work date), but Step 9 — whose scan is explicitly full-coverage — will re-verify the whole document against the current implementation.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-10-01T09:41:58.524Z

Output: `workspace/PRD_COMPLETED.md` — 421 lines / 116,664 bytes, over `PRD_FINALIZED.md` 410 lines / 113,827 bytes (**+11 lines, +2,837 bytes**; the only added lines are the 11 new §4 endpoint-table rows). The subagent's own report quoted 422 lines / 116,349 chars — a slightly stale measurement taken before its final edit; the file on disk is the larger, complete one. Orchestrator verified the file ends cleanly at the §5 error table, carries the same 25 sub-headings as `PRD_FINALIZED.md` (no new sections), still holds all 31 distinct `ERR_*` ids, and retains all five top-level sections.

Counts reported: **28 mismatch-revisions, 18 ambiguity-pins** (11 of the pins are endpoint-table rows). The §4 endpoint table is now complete at **51 data rows = 51 implemented routes** (was 40), the 11 additions being `GET /model-versions/{id}`, `POST`+`GET /assemblies`, `GET /workers`, `GET /workers/{id}/roster-summary`, `GET /trade-contract-rates`, `GET /prefab-orders/{id}`, `GET /prefab-components/{id}`, `GET /material-releases/{id}`, `GET /_clock` and `POST /_clock/clear`. Error catalogue unchanged at 31 rows.

**Orchestrator verification of the two gate tensions carried forward from Step 8:** the only surviving occurrence of the string `` to `READY` `` in the document is the corrective clause *"the gate lifts to `ALLOWED`, not to `READY`"* — i.e. every sentence that used to assert a `READY` outcome has been reconciled to the §3.3 precedence, and the one remaining mention explicitly denies it. Confirmed by direct grep, not by trusting the report.

**Sweep validity after Steps 8 and 9:** both steps edited only `workspace/*.md`. `find workspace/implementation -name '*.py' -newer results.1.json` returns empty, so the green sweep produced after the Step 8 follow-up fixes still post-dates every implementation edit. The eight `results.{1..8}.json` files remain on disk as required by the output contract.

Subagent's returned summary, verbatim:

```
All checks pass. Final verification summary: endpoint cross-check 51 impl routes ↔ 51 table rows (exact match), 28 section headings unchanged (no new sections), error catalogue still 31 rows, and a grep sweep confirms none of the superseded claims survive.

**Source vs output:** `PRD_FINALIZED.md` 411 lines / 113,517 chars → `PRD_COMPLETED.md` 422 lines / 116,349 chars (**+11 lines, +2,832 chars**; the only added lines are the 11 new §4 table rows).

**Counts: 28 mismatch-revisions, 18 ambiguity-pins** (11 of the pins are endpoint-table rows).

**Post-Step-8 items the task flagged:**
- `_tied_shipment_hours` (revisions.py:250-259) — live behavior counts `FABRICATED`/`LOADED`/`SET`; §3.7 already matched, §3.1's takeoff-line sentence still said "already `SET`" → revised so the two agree.
- `recompute_ledger_row` (compliance.py:97-98, 121-122) — PRD only lists the ledger row's `regular_hours`/`overtime_hours` as recorded fields and defines no accumulation rule, so per instruction it was left silent.
- `enforce_ratio_cap` (labor.py:379-391) — §3.6 now reads correctly for both the guard path and the ledger path (both dated by the crew day's `work_date_iso`) and no longer over-claims for the rate-registration path (no crew day → the new row's own cap). Also removed the claim that acknowledgment re-runs the guard (it does not; it re-derives and suspends).
- `receiving_user_id` already pinned as opaque in §2.1 → left untouched.

**Changes (PRD section — insert/revise — ambiguity/mismatch — what changed — impl ref):**
- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` is rejected with `ERR_INVALID_PREFAB_TRANSITION` (409) — core.py:375-376
- §2.11 — revise — mismatch — the hoisting-conflict guard bites at the release that freezes the window, not at creation — orders.py:296-316,376
- §3.1 — revise — mismatch — tied shipment hours cover `FABRICATED`/`LOADED`/`SET` components (was `SET`-only) — revisions.py:250-259
- §3.2 — revise — mismatch — RECOVERY_MODE landing only recomputes craft-hours credit and `releasable_status`; the overtime/ledger/`DISALLOWED` cascade does not exist — projects.py:263-271
- §3.2 — revise — mismatch — HOLD landing re-derives `releasable_status` + `fabrication_locked`; no hoisting-window recompute — projects.py:263-271
- §3.2 — revise — mismatch — FROZEN forces `ENGINEERING_HOLD` and blocks new declarations only; no rack-binding suppression or release-timing re-derivation — projects.py:263-271, orders.py:171-173
- §3.2 — revise — mismatch — HOLD→RECOVERY_MODE recomputes `releasable_status`, not hoisting windows — projects.py:263-271
- §3.2 — revise — mismatch — FROZEN→RECOVERY_MODE has no `IN_TRANSIT`/`LOCKED` precondition — projects.py:263-271
- §3.2 — revise — mismatch — `delivery_gate` is never closed by any operation (`set_external_gate` is dead code) — projects.py:286-291
- §3.3 — insert — ambiguity — a delivery-status call may set a bare `shipment_status` (how `RESERVED`/`LOCKED` are reached) — orders.py:522-527
- §3.3 — insert — mismatch — `FROZEN` is an engineering-hold condition in the release-gate precedence — orders.py:171-173
- §3.3 — insert — ambiguity — the window is derived at release, so an unreleased package carries null window fields — orders.py:374-393
- §3.3 — insert — ambiguity — loading is also refused on an engineering or material hold — orders.py:544-548
- §3.3 — revise — mismatch — dispatch is an explicit move only, no system event — orders.py:549-552
- §3.3 — revise — mismatch — `planned_delivery_iso` uses `transport_kind` lags plus the max lead time over the package's commodity releases (not the appliance profile) — orders.py:329-344
- §3.3 — revise — mismatch — `rework_hours` sums crafted hours of `REWORK` components; `fabrication_utilisation_pct` is zero until release — orders.py:110-116,395-396,455-469
- §3.4 — revise — ambiguity — `contractual_credit_cents` = value + qty×core − qty×recycled — orders.py:616-623
- §3.4 — insert — ambiguity — field installation also requires the package's `releasable_status` not to be `ENGINEERING_HOLD` — components.py:158-162
- §3.5 — revise — mismatch — `work_date_iso` is a report key, not unique (several reports per key) — labor.py:312-358, calculations.py:426-449
- §3.5 — revise — mismatch — `shift_band_delta` is body-supplied, default 0 (not derived from `qualification_state_code`) — labor.py:58
- §3.6 — revise — ambiguity/mismatch — governing row matched on classification/apprentice period; both crew-day paths dated by `work_date_iso`; rate-row path uses the new row's own cap; null caps fall back to tier defaults — projects.py:38-59, calculations.py:471-489
- §3.6 — revise — mismatch — the ratio guard runs on reporting and rate registration, not on acknowledgment — labor.py:331,379-391
- §3.6 — revise — mismatch — `journey_ring_claim_hours` is re-derived on read, never reset by an upgrade — calculations.py:496-505
- §3.7 — insert — mismatch — the payload checks also run at creation and write no row on refusal — revisions.py:190,214-220
- §3.7 — revise — mismatch — supersession is refused at creation, not submission — revisions.py:128-134,219
- §3.7 — revise — mismatch — the craft-hours ceiling guards approval only, not the rework-job path — revisions.py:547-604
- §3.7 — revise — mismatch — a rejection needs a resolution containing `REJECT`; other resolutions approve — revisions.py:414-421
- §3.7 — revise — ambiguity — re-draft runs through `POST /prefab/revisions` with `revision_id` — revisions.py:148-153,223-233
- §3.7 — revise — ambiguity — kludge/negotiated rates and markup are revision-supplied with 8,500/7,800/0.18 defaults — calculations.py:539-542
- §3.7 — revise — mismatch — `revised_trade_hours` = `impact_qualified_hours`; shop-parts basis 12,000 cents; `peak_multiplier` 2.0/1.0 by safety program; `excess_flow_hours` minus the revision's own `rework_hours` — calculations.py:566-581, revisions.py:242-246
- §3.7 — revise — mismatch — `reason_option_code` only has to be present (no admissibility table) — revisions.py:563-565
- §3.7 — revise — mismatch — opened jobs record `SHOP_CONFIRMATION` for both confirmation modes — revisions.py:511-512
- §3.9 — revise — mismatch — the 90-day switchgear lead time is an expectation, not a validated constraint — procurement.py:16-56
- §3.9 — revise — mismatch — the deadline error exposes no `num_days_late` in the §2.2 envelope — core.py:336-344, app.py:28-30
- §3.9 — revise — mismatch — `list_value_cents` = `unit_price_cents`×`quantity`; `ship_cost_cents` is zero; `value_cents` = list + ship — procurement.py:59-66
- §4 — insert — ambiguity — 11 missing endpoint rows added: `GET /model-versions/{id}`, `POST`/`GET /assemblies` (no role restriction), `GET /workers`, `GET /workers/{id}/roster-summary`, `GET /trade-contract-rates`, `GET /prefab-orders/{id}`, `GET /prefab-components/{id}`, `GET /material-releases/{id}`, `GET /_clock`, `POST /_clock/clear` — routes.py:79-90,136-177,251-256,315-320,412-418,436-444

Both §3.3-vs-§3.9 gate tensions are carried forward in favour of the §3.3 ladder: §3.7, §3.9 (receipt) and §3.9 (material gate) all lift to `ALLOWED` on an `ON_TRACK` project, and no sentence anywhere still claims a lift returns to `READY` on `ON_TRACK`.
```

**Orchestrator note — several Step 9 revisions record genuine implementation gaps, not PRD defects.** The largest is §3.2: the PRD's per-tier landing cascades (RECOVERY_MODE's overtime/ledger/`DISALLOWED` propagation, HOLD's hoisting-window recompute, FROZEN's rack-binding suppression and release-timing re-derivation, and the FROZEN→RECOVERY_MODE `IN_TRANSIT`/`LOCKED` precondition) are **not implemented** — `projects.py:263-271` performs a reduced recompute. Step 9's mandate is to make `PRD_COMPLETED.md` describe what the implementation actually does, so it documented the reduced behavior rather than the PRD's fuller prose. Likewise `projects.py::set_external_gate` is dead code, so the §3.2 `delivery_gate` closure path is now described as never firing. These are recorded here as the pipeline's honest statement of implementation scope: the shipped code passes all 62 tests, and `PRD_COMPLETED.md` is faithful to that code, but the document is now narrower than the original `PRD.md` in these areas. `PRD.md` itself is left untouched as the original contract.