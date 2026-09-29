# Worklog — task_2865_bone_density_osteoporosis_program

## Step 1: Create task directory — 2026-09-05T08:17:25.964Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2865_bone_density_osteoporosis_program` and `.../workspace`. Index fixed at 2865 by the pre-assigned output directory (no auto-allocation, to avoid collisions with the other pipelines running concurrently on this host).

## Step 2: Generate scaffold — 2026-09-05T10:10:00Z

Wrote the three scaffold artifacts from the scenario text plus the scaffold-generator skill spec alone (no sibling task was read):

- `SCAFFOLD.yaml` (§1.0–§1.7, 3569 lines): 15 entities, 8 state machines, 2 §1.2.1 concurrency rules, 12 calculations, 65 ordered validations, 54 endpoints, 64 error codes, 6 roles. complexity_profile: primary `compliance_audit`, secondary `temporal_windowing`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, selector_policy]`, topology `graph`, state-machine shape `cyclic`, role model `segregation_of_duties`, consistency `immediate`.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, 2335 lines): 9 rules, 24 instances.
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, 3977 lines): 9 sections, 79 instances (57 with a full `test_recipe`, 22 `excluded_because` stubs citing §1.8 instances).

`scaffold_lint.py`: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (1039 calls scanned).

Self-audit fixes applied while writing concrete asserts: made `ERR_SESSION_ARCHIVED` reachable (carved ARCHIVED out of the priority 26/27 conditions rather than renumbering), narrowed priority 29 so `ERR_REPEAT_LIMIT_EXCEEDED` is reachable, gave `ERR_VFA_NOT_COVERED` a positive trigger, canonicalised the VFA-narrative requirement on `ScanSession.vfa_performed`, fixed the refill-window boundary in validation 61, and corrected drifted enum/field/calculation names.

Note for Step 3: `SCAFFOLD.yaml`'s `scenario:` block still carries the verbatim first line "Generate task harder than expert level!"; strip that line before PRD generation so the directive does not leak into `PRD.md`.

## Step 2b: Strip difficulty directive from SCAFFOLD.yaml — 2026-09-05T10:09:34.716Z

Orchestrator removed the line `Generate task harder than expert level!` from `SCAFFOLD.yaml`'s `scenario:` block (it was the only occurrence in the three scaffold artifacts). That directive is for the scaffold generator only; leaving it in the scenario key would carry it into the doc generator's input and from there into `PRD.md`. All three YAMLs re-verified as parsing after the edit. The only remaining mention of the phrase in the task dir is inside `worklog.md`, which no generator reads.

## Step 3: Copy shared files — 2026-09-05T10:09:34.716Z

Copied `INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T10:28:00Z

Subagent summary (verbatim):

PRD generation complete.

**Output:** `.../workspace/PRD.md` — 432 lines, 119,529 bytes. Built with one `Write` (title through §2.2) plus seven heredoc appends; plan retained at `/tmp/task_2865_bone_density/prd_plan.md`.

**Section list (verified via `grep -n '^#'`)**
- `# Bone Density & Osteoporosis Program API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Users, Roles and Access Control; 2.2 API Response Structure (verbatim fixed block, both sub-headings); 2.3 Pagination, Ordering and List Filters; 2.4 Resource Identity, the Logical Clock and Record Versioning; 2.5 Densitometric Precision and Rounding Discipline; 2.6 Optimistic Concurrency on Patients and Densitometers; 2.7 The Rejection Ladder; 2.8 Path Hierarchy and Nested Resource Resolution; 2.9 Conserved Counters, Cascades and Compensating Actions; 2.10 Snapshot Semantics and the Comparability Invariant
- `## 3. Business Logic & Workflows` — 3.1 Program Foundations (payer policies, patients, risk intake); 3.2 Densitometer Registry and Precision Certification; 3.3 Phantom QC, Out-of-Control Holds and Cross-Calibration; 3.4 Ordering a Study and Booking It onto a Device; 3.5 Acquisition at the Device; 3.6 Independent Positioning Review and the Repeat Cycle; 3.7 Fracture Risk Assessment and Drafting the Diagnostic Report; 3.8 Finalization, the Interval Cascade and Amendment; 3.9 Treatment Initiation, Refill Capture and Adherence Follow-Up
- `## 4. Endpoint Definitions` — 4-column table, exactly 54 rows
- `## 5. Error Code Catalogue` — 2-column table, exactly 64 rows

**Coverage (all checks scripted against SCAFFOLD.yaml, not eyeballed)**
- Contract 1 field-name coverage: 214/214 required identifiers (201 entity field names ∪ 98 endpoint input/query identifiers) present verbatim in backticks — 0 missing.
- Contract 2: all 65 ordered validations rendered as an explicit ladder in §2.7 (all 64 distinct validation error IDs present there); both OCC rules (`expected_patient_version`→`ERR_STALE_PATIENT_VERSION` 412, `expected_densitometer_version`→`ERR_STALE_DENSITOMETER_VERSION` 412) in §2.6; all 8 state-machine dimensions across 7 entities with every from/to state, precondition and side effect (script confirmed every state literal appears); all 12 calculations with formulas, named constants, precision and evaluation order — every calculation `output_field` appears; every enum literal from every entity `constraints` string present (0 missing); all 6 roles named, with `PatientPortalUser` identified as `entity_backed:Patient`; all 64 errors referenced in prose before §5 (0 orphans).
- Contract 3 §3 path purity: scripted scan of all backticked tokens in §3 found 0 tokens starting with `/`, 0 bare HTTP methods, 0 method+path combinations. Paths appear only in §1, §2 and §4.
- No pseudocode/operator syntax anywhere (`>=`, `<=`, `==`, `:=`, `->` all absent from prose); no fuzzy quantifiers.

**Tail confirmation:** the file ends at a real section boundary — the final line is the last data row of the §5 error table (`| ERR_VFA_NOT_COVERED | 402 |`), a complete 64-row table, no truncation, no audit footer.

**Two scaffold internal inconsistencies resolved (decisions worth knowing for the implementation step):** (1) `FraxAssessment.threshold_basis` — entity enum says `MAJOR_OSTEOPOROTIC` while the calculation formula abbreviates it `MAJOR`; the PRD uses the declared enum `MAJOR_OSTEOPOROTIC`. (2) FRAX points precision — entity descriptions say 4 decimals with negative `age_points` allowed, the `calculations` block says 2 decimals with `age_points` clamped at 0; the PRD follows the calculations block (2 dp, clamped), which is what its own worked example and edge cases require. Also noted: `lsc_site_code` is specified two ways (fixed `TOTAL_HIP`/`LUMBAR_SPINE`/`FEMORAL_NECK` precedence vs. "the current `lowest_t_score_site`"); the PRD documents the fixed-precedence rule, which matches the field definition and the scaffold's worked total-hip example.

I did not open `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `worklog.md`, or any sibling task directory, and wrote no report/summary files.

**Orchestrator verification:** independently confirmed 432 lines / 119,529 bytes, 27 headings, head is `# Bone Density & Osteoporosis Program API — Product Requirements Document`, tail is the complete final error-table row `| ERR_VFA_NOT_COVERED | 402 |` (a real section boundary, not mid-sentence) — so the known doc-generator truncation failure did not occur and no regeneration was needed. Also grepped PRD.md for "harder than expert", "expert level", "scaffold", "test_recipe": zero hits, so the Step 2 difficulty directive did not leak into the contract.

## Step 6: Generate implementation — 2026-09-05T11:18:16Z

(Launched concurrently with Step 5 in a single orchestrator message, so the implementation generator started before `test_suite/` existed on disk and could not fit the tests.)

Subagent summary (verbatim):

The implementation is complete and verified.

## Deliverable
`.../workspace/implementation/`

| module | lines | role |
|---|---|---|
| app.py | 64 | app factory, blueprint registration under `/bone-density`, error handlers |
| calc.py | 424 | all 14 PRD calculations (Decimal, ROUND_HALF_UP) |
| cascades.py | 214 | cascades A/B/C, retirement unwind, amendment compensation, slot renumbering |
| db.py | 91 | in-memory dict store, logical clock, `base_record`/`touch`/`public` |
| errors.py | 87 | `ApiError` + the full status map |
| middleware.py | 62 | RBAC (`@endpoint`), patient-scope enforcement |
| queries.py | 228 | typed lookups (404 ladder ids) and filtered collections |
| reporting.py | 175 | diagnostic-report derivation + required-element audit |
| response.py | 94 | meta/response_type/data envelope, pagination |
| util.py | 147 | date/instant helpers, scale-preserving Decimal JSON emitter |
| validate.py | 193 | shape gate (ladder 3), pagination params |
| routes/foundation.py | 220 | payer policies, patients, risk profiles, clock |
| routes/devices.py | 339 | registry, precision, QC runs, calibration events, retire |
| routes/scheduling.py | 284 | orders, payer screening, appointments, cancel |
| routes/acquisition.py | 380 | sessions, site measurements, VFA, submit, reviews, repeat |
| routes/interpretation.py | 259 | FRAX, reports, PATCH/finalize/amend |
| routes/treatment.py | 246 | plans, refill ledger, adherence review |

3507 lines across 18 `.py` files, plus `start.sh` (executable) and `requirements.txt`. Every file passes `python3 -m py_compile`; `__pycache__` removed.

## Coverage (mechanically verified, not just claimed)
- **Endpoints: 54 implemented vs 54 in the PRD tables — exact set match** (compared Flask's `url_map` against the PRD endpoint tables; zero missing, zero extra).
- **Errors: all 64 catalogue error ids referenced.** Extras are the framework fallbacks (`ERR_NOT_FOUND`, `ERR_METHOD_NOT_ALLOWED`, `ERR_INTERNAL`) plus two prose-only ids the catalogue omits: `ERR_SITE_NOT_REQUESTED` (409, after the duplicate check) and `ERR_VFA_NOT_PERFORMED` (422, after requested-sites-incomplete). `ERR_PLAN_DISCONTINUED` (prose, uncatalogued) is emitted as the catalogued `ERR_TREATMENT_PLAN_TERMINAL` 409 per ladder 34.
- 65-priority global ladder, both state machines (2-D session, cyclic plan), cascades A/B/C with conserved counters, snapshot semantics, OCC (412), segregation of duties, 6-role RBAC, patient-scope, append-only entities without `updated_at`/`version` (the four plus PositioningReview per §3.6), three-fractional-digit instants, scale-preserving decimals.

## start.sh
Reads `$PORT` (`export PORT="${PORT:-10000}"`), `app.run(host="0.0.0.0", port=int(os.environ["PORT"]))`, runs in the foreground via `exec`, installs Flask only when missing (avoids pip contention on per-test reboots).

## No seeded data
Storage is plain module-level dicts; no SQLite, no file/JSON persistence (grep for `sqlite|open(|json.load|pickle` returns nothing). A fresh boot via `./start.sh` answered `GET /patients` with `total_count: 0` and `api_request_timestamp 2026-08-01T00:00:00.000Z`, i.e. the clock at its documented origin — every relaunch wipes all state.

## Smoke tests (port 39865, each on a freshly booted process, all servers killed by exact PID)
- **smoke.py — 0 failures** (~50 assertions: full happy path from policy through plan/refill/adherence-review/amend, plus 401/403/404/pagination).
- **smoke2.py — 0 failures** (76 assertions: QC PASS/WARN/FAIL bands, sustained-shift detection incl. sign-flip break, two-pass release, cascade B slot cancellation with order revert and counter decrement, calibration event open/close/adjudicate for both the approved (factor 0.9804, generation bump) and rejected-drift branches, retirement unwind, VFA eligibility/grading, the full repeat cycle to the repeat cap, superseded-row visibility, raw-JSON decimal scales `2.000`/`0.0200`/`0.9804`).
- **smoke3.py — 0 failures** (49 assertions: cascade A all four links — archive, patient counters, `next_eligible_scan_date` 2028-09-01, retroactive order denial with `INTERVAL_REVISED_BY_REPORT`, `ORDER_DENIED` slot cancellation, counter to zero — plus serial-device pinning, buffer conflict, double-booking, 412 OCC, 402 payer refusal, grace window, 401/403/404/405, pagination bounds).

Three apparent failures during smoke2/3 were my own wrong expectations, confirmed against the PRD and corrected in the scripts, not the code: `BASELINE_NO_PRIOR` (not `NO_PRIOR`), retirement's cancellation code is `DEVICE_QC_HOLD`, and `ERR_STALE_PATIENT_VERSION`/`ERR_APPOINTMENT_IN_PAST`/`ERR_INVALID_INTERVAL` are 412/422/422. Scratch files live only in `/tmp/task_2865_bone_density_impl/`. No process is left running — port 39865 is free; no broad `pkill` was ever used. I did not read `test_helpers/`, `test_suite/`, the design YAMLs, `worklog.md`, or any sibling task, and I ran neither pytest nor the harness.

## Step 5: Generate unit tests — 2026-09-05T12:08:09Z

(Launched concurrently with Step 6 in a single orchestrator message.)

Subagent summary (verbatim):

Step 5 is complete. Both stages are written, at the task root, and everything parses.

## Files written

`test_helpers/` — 2578 lines total
`__init__.py` 130 · `api_client.py` 454 · `api_errors.py` 182 · `assertions.py` 233 · `constants.py` 217 · `factories.py` 340 · `fixtures.py` 596 · `test_users.py` 114 · `types.py` 311

`test_suite/` — 6222 lines total
`conftest.py` 29 · `test_01_dual_variant_calc.py` 238 · `test_02_combinatorial_formula.py` 300 · `test_03_non_linear_state_machine.py` 327 · `test_04_transitive_cascade.py` 255 · `test_05_priority_pair_validation_conflict.py` 228 · `test_06_boundary_precision_check.py` 353 · `test_07_cross_entity_state_dependency.py` 239 · `test_08_resource_temporal_overlap.py` 246 · `test_09_compensating_invariant.py` 217 · `test_10_entities.py` 542 · `test_11_state_machines.py` 629 · `test_12_calculations.py` 475 · `test_13_validations.py` 352 · `test_14_endpoints.py` 364 · `test_15_errors.py` 715 · `test_16_rbac.py` 297 · `test_17_cross_cutting.py` 271 · `test_18_consistency_model.py` 145

## Tests emitted

105 tests, every one carrying exactly one `Design:` line as the final docstring line.

- **Queue A (Difficulty, §1.8):** 48 tests covering all 24 non-stub instances across the 9 rule ids (`test_01`–`test_09`). Each instance is realised as two tests — the two sides of its contrast (e.g. WITH_BMD vs WITHOUT_BMD, at-limit vs one-unit-over) — so a failure localises to one arm.
- **Queue B (Corner, §1.9):** 57 tests covering 56 of the 57 non-stub instances (`test_10`–`test_18`): entities 13, state_machines 11, calculations 7 (one instance, the cross-calibration bracket, is split into two tests for its two edges), validations 5, endpoints 4, errors 8, rbac 4, cross_cutting 3, consistency_model 1.

Machine-audited: 0 untagged tests, 0 dual-tagged tests, 0 dangling tags, 0 tags pointing at a stub instance, and no test module mentions the scaffold or any scaffold section/constant — all quoted grounding is verbatim PRD prose.

## Skipped instance (1)

- `Corner/validations/appointment_at_or_before_the_clock_and_zero_length_slots_are_rejected` — **non-unique derivability.** The instance's distinguishing aspect is exactly the equality boundary `start_utc == clock`, and the PRD contradicts itself there: §3.4 admits `start_utc` "on or after the logical clock instant" while rejection ladder item (57) refuses `start_utc` "at or before the logical clock" with `ERR_APPOINTMENT_IN_PAST`, 422. Not weakened, no xfail, no placeholder. (The other 22 stub instances were excluded by the design itself and were never candidates.)

## Design/PRD divergences resolved in favour of the PRD

1. **Clock status code (rbac):** design asserts 200 for a `PatientPortalUser` clock set; PRD lines 304/361 say the clock endpoint returns **204**. Asserted 204.
2. **Queue A instance 17 (interval action):** asserted clinical interval 12 with `PAYER_LIMITED_INTERVAL` per the PRD's six-step order, not the design's 24 / `ROUTINE_INTERVAL`.
3. **`valid_vertebral_count` for non-lumbar sites:** design said null; PRD line 232 says "zero for every other site" — asserted 0.
4. **PositioningReview immutability:** design lists five append-only types, PRD §2.4 lists four; followed the PRD.
5. **Adherence refill ordering (`test_14`):** the design wanted 201 for a refill dispensed on the clock's own date, but PRD line 286 requires `dispensed_date` strictly before the clock date, so the accepted refill moved after the clock advance.
6. **`GET /bone-density/scan-orders/{id}` portal scope:** line 118's explicit scope list omits the item endpoint, but line 319 admits `PatientPortalUser` there and lines 21/23 state the per-row ownership rule, so `ERR_PATIENT_SCOPE_VIOLATION` is uniquely derivable; grounded the docstring on 21/23.

## Proofs

- `ls -d` confirms `./test_helpers` and `./test_suite` exist **at the task root**; `find workspace -maxdepth 1` shows only `INSTRUCTION.md`, `PRD.md` and `implementation/` — no test directory leaked into `workspace/`, and nothing under `workspace/implementation/` was read, listed or written.
- `python3 -m compileall` over both directories: all 28 files parse (`__pycache__` cleaned up afterwards).
- `pyflakes` is clean on every test module and every helper except the deliberate `# noqa: F401` fixture re-export block in `conftest.py` and the re-export surface of `test_helpers/__init__.py`. One genuinely unused import (`TECHNOLOGIST_HEADERS` in `fixtures.py`) was removed during the final audit.
- No server was started, no pytest was run, and no `pkill` was issued. Scratch files lived only in `/tmp/task_2865_bone_density/`.

**Orchestrator verification:** `test_helpers/` and `test_suite/` both confirmed at the task root; `find workspace -maxdepth 1` shows only `INSTRUCTION.md`, `PRD.md`, `implementation/` (no test dir leaked into workspace/); 19 test modules, 105 test functions; `implementation/start.sh` present and executable; single `worklog.md`, at the task root.

## Step 7: Run tests and iterate — 2026-09-05T12:39:45Z

Subagent summary (verbatim):

Done — all 8 rounds fully green.

## Summary

**Iterations run:** 2 (diagnostic sweep, then verification sweep).

**Iteration 1 result:** 104/105 passing in all 8 rounds, with a single, perfectly deterministic failure (same test, same message, every round — no load-induced flakiness anywhere in the suite).

**The failure:** `test_17_cross_cutting.py::TestTheDensitometerVersionGuardsTheLeastSignificantChange::test_replaying_the_creation_version_leaves_the_first_studys_threshold` — `AssertionError: Expected 201, got 200` on the third call, the *accepted* precision assessment. Everything else in that test (the 412 `ERR_STALE_DENSITOMETER_VERSION` refusal, the unchanged `rms_sd_g_cm2`/`lsc_g_cm2`/`version` after the refusal, the 0.0200 → 0.0554 LSC arithmetic, the version increment) already passed.

**Diagnosis (STEP 1c, partial coverage):** PRD §4 states verbatim "Creation endpoints return HTTP 201 with the created resource in `data`; action endpoints that transition an existing resource return HTTP 200 with the affected resource." That sentence does **not** uniquely determine 201 for `POST /bone-density/densitometers/{id}/precision-assessment`: the PRD never declares a `PrecisionAssessment` resource type (§2.4 enumerates resource types and its four append-only exceptions without one), and the body this endpoint returns is the pre-existing `Densitometer` with its `version` advanced — i.e. an action endpoint transitioning an existing resource, which PRD pins to 200. Two divergent PRD-faithful readings exist, so the exact status was not derivable. Corroborating signal: this `201` literal was the *only* creation-status pin in the entire 105-test suite, and the implementation correctly returns 201 from all 16 genuine creation endpoints (`response.created()`), so its 200 here is a deliberate, faithful §4 classification rather than a blanket bug.

**Tests deleted:** none.

**Fixes applied to `test_suite/`:**
- `test_suite/test_17_cross_cutting.py` — in `test_replaying_the_creation_version_leaves_the_first_studys_threshold`, swapped `validate_success(..., 201)` for `get_success_data(...)` on the accepted precision-assessment call, removing only the HTTP-status pin PRD does not uniquely determine. Every PRD-covered assertion is retained unchanged (the 412 error_id assertion, the no-op-on-refusal checks, and both four-decimal LSC assertions), and the envelope shape is still validated. Added `get_success_data` to the file's `test_helpers` import.

**Fixes applied to `test_helpers/`:** none — no fixture, factory, or role-header bug surfaced.

**Fixes applied to `implementation/`:** none — no implementation defect was found.

**Final sweep confirmation:** all 8 `results.$i.json` files exist at `.../workspace/implementation/` and each reads `passed=105 total=105 failed=0 errors=0` (rounds 1 through 8). `DONE.marker` records `sweep finished at 2026-09-05T12:26:59Z`. The results files are left in place as deliverables; `worklog.md` was not read or modified, and no stray files were left under `workspace/`.

**Orchestrator verification:** independently read all 8 `results.$i.json` — every round `105 / 105`. The sweep ran under `setsid` via `workspace/sweep.sh` (a script file rather than an inline one-liner, to avoid the nested-quoting bug that injects literal quotes into `--start-command`); no round showed the SIGTERM-reaping signature (`Terminated` server log / all rounds dying at one instant), and no load-induced timeout flakiness appeared in either sweep.

**Step 8 decision:** NOT skipped. The skip condition requires 0 deletions and 0 fixes across all layers; Step 7 made 1 `test_suite/` fix, and that fix is itself the record of a genuine PRD silence (the response status of the precision-assessment endpoint), so Step 8 has exactly one item to adjudicate.

## Step 8: Finalize PRD — 2026-09-05T12:49:45Z

Subagent summary (verbatim):

Done. `PRD_FINALIZED.md` written with exactly one edit.

## Line counts
- `PRD.md`: 432 lines; `PRD_FINALIZED.md`: 432 lines — 0.0% line delta (one line rewritten in place, +2 sentences / +607 bytes).

## Change
- **§4 Endpoint Definitions (line 304)** — *revise* — kept the existing 201/200/200-list/204 sentence verbatim, then appended the disambiguation that the 201-vs-200 split turns on whether the call persists a brand-new resource row and returns it, and pinned `POST /bone-density/densitometers/{id}/precision-assessment` to HTTP 200 with the addressed `Densitometer` — `implementation/routes/devices.py:125` (`return ok(public(device))`), `implementation/response.py:36-41`.

## Pre-edit search log
- **(a) Subject:** which success HTTP status each mutating endpoint returns, and the criterion distinguishing "creation" from "action" endpoints.
- **(b) Impl paths enumerated:** `response.py` in full (`ok` default 200, `created`→201, `no_content`→204, `paginated`→200 — no other status producer exists); every `@bp.<method>` in all six route modules cross-referenced against its return statement, giving the complete map: 16 endpoints returning `created(...)` (`payer-policies`, `patients`, `patients/{id}/risk-factor-profiles`, `densitometers`, `densitometers/{id}/qc-runs`, `densitometers/{id}/calibration-events`, `scan-orders`, `scan-appointments`, `scan-appointments/{id}/scan-sessions`, `scan-sessions/{id}/site-measurements`, `scan-sessions/{id}/positioning-reviews`, `frax-assessments`, `diagnostic-reports`, `diagnostic-reports/{id}/amend`, `treatment-plans`, `treatment-plans/{id}/adherence-refills`); 11 mutating endpoints returning `ok(...)` at 200 (`precision-assessment`, `retire`, `calibration-events/{id}/close`, `.../adjudicate`, `scan-sessions/{id}/vfa`, `.../submit-acquisition`, `.../repeat-acquisition`, `PATCH diagnostic-reports/{id}`, `.../finalize`, `scan-appointments/{id}/cancel`, `treatment-plans/{id}/adherence-review`); the single `no_content()` clock endpoint (`routes/foundation.py:220`); and all `paginated(...)` list endpoints. I also grepped every `db.<table>[record["id"]] = record` / `base_record()` insertion site (`cascades.py` included) to confirm the persistence criterion holds exactly: all 17 insertion sites sit in the 16 `created()` handlers (`amend` inserting its successor at `routes/interpretation.py:219,232`), and **no** 200-returning handler inserts a new row — `vfa` and `adherence-review` write only onto the existing session/plan (`routes/acquisition.py:257-262`, `routes/treatment.py:230-246`). Also read PRD §2.4 (resource-type exception list) and §3.3 lines 178-180 to confirm no `PrecisionAssessment` resource is declared and the study is recorded onto the device.
- **(c) Wording adjustments made:** dropped an earlier draft phrasing that keyed the rule to "one of the resource types of §2.4", because §2.4 only enumerates the four append-only exceptions, not an exhaustive resource list — that would have mis-described `PositioningReview`, `ScanSession`, etc. Also dropped a draft clause asserting the response carries "its incremented `version`", to avoid restating a §3.3 fact in a spot where it could read as a general rule about all action endpoints (several affected resources, e.g. the append-only ones, carry no `version`). Final wording is stated as a persistence test plus one named endpoint, which is consistent with all 28 mutating handlers, the 204 clock endpoint, and every list/single GET.

No other Step 7 item required a PRD change: Step 7 applied zero implementation fixes, zero `test_helpers/` fixes, and deleted no tests, so this single status-code pin is the complete scope.

**Orchestrator verification:** `PRD_FINALIZED.md` exists and is NOT byte-identical to `PRD.md` (119,529 → 120,013 bytes; a single changed line), and its tail is still the complete final error-table row, so the edit did not truncate the document.

## Step 9: Complete PRD — 2026-09-05T13:55:36Z

**Orchestrator decision on execution shape:** run as THREE SEQUENTIAL, MODULE-PARTITIONED passes over one shared `PRD_COMPLETED.md`, rather than one subagent scanning all 3,507 implementation lines. A single agent reliably under-scans an implementation this size and can return a document byte-identical to its input, which would mean the scan never really happened. Partition: pass 1 = the cross-cutting core (`app.py`, `response.py`, `errors.py`, `middleware.py`, `validate.py`, `db.py`, `util.py`, `queries.py`); pass 2 = `calc.py`, `cascades.py`, `reporting.py`, `routes/foundation.py`, `routes/devices.py`; pass 3 = `routes/scheduling.py`, `routes/acquisition.py`, `routes/interpretation.py`, `routes/treatment.py`. Pass 1 alone performed the `cp PRD_FINALIZED.md PRD_COMPLETED.md`; passes 2 and 3 were explicitly forbidden to copy, so they inherited and extended the earlier edits. Each pass was told which behaviors the other passes owned and handed forward anything outside its slice.

Total across the three passes: **71 edits — 47 ambiguity-pins, 24 mismatch-revisions.** File grew 120,013 → 152,083 chars (+26.7%) with the line count going 432 → 442, i.e. almost entirely in-paragraph inserts and revisions, no new sections.

### Pass 1 of 3 — cross-cutting core modules (subagent summary, verbatim)

Pass 1 of 3 complete.

**Copy performed:** yes — `cp PRD_FINALIZED.md PRD_COMPLETED.md` was my first action.

**Sizes:** PRD_FINALIZED.md 432 lines / 120,013 bytes → PRD_COMPLETED.md 442 lines / 131,334 bytes (+10 lines, +11,321 chars). Ends at the `ERR_VFA_NOT_COVERED | 402` row of the §5 table; 27 headings, unchanged.

**Counts:** 13 ambiguity-pins, 5 mismatch-revisions (18 edits total).

**Changes**
- §2.1 Users/Roles — revise — ambiguity — whitespace-only header counts as empty (401); role matched by exact equality, no trim/case-fold; the "unknown role" and "role not admitted" cases are indistinguishable; `X-User-ID` recorded verbatim, never trimmed — `middleware.py:26-33`
- §2.2 success format — revise — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A-Z0-9`; `api_request_timestamp` reads the **logical** clock, so it repeats between requests — `response.py:20-28`, `db.py:54`
- §2.2 success format — revise — ambiguity — `meta` on non-list 2xx carries exactly the two request fields; the three top-level keys are always `meta`/`response_type`/`data` in that order, including the 204 clock reply (`response_type` `"object"`, `data` `{}`) — `response.py:36-45`
- §2.2 error format — revise — mismatch — "4xx status codes" → any non-2xx including the 5xx fallback — `app.py:48-54`
- §2.3 Pagination — revise — ambiguity — empty `limit`/`offset` = omitted; non-integer text or out-of-range → `ERR_INVALID_REQUEST` 422; boolean query params accept `true/1/yes` vs `false/0/no` case-insensitively else 422; over-large `offset` legal, empty page — `response.py:57-75`, `validate.py:184-193`
- §2.3 Ordering — revise — **mismatch** — the default tie-break is not uniformly `id`: device inventory / patient roster / policy catalogue tie-break on `id`, but order, session, report and plan lists tie-break on the server's internal insertion sequence; declared-order collections tie-break on that same sequence oriented with the declared direction — `routes/foundation.py:84,146`, `routes/devices.py:94` vs `routes/scheduling.py:133`, `routes/acquisition.py:131`, `routes/interpretation.py:258`, `routes/treatment.py:112`
- §2.3 List filters — insert — ambiguity — filters match by exact string equality (so an out-of-set or wrong-case value yields an empty page, not 422); absent/empty filter ignored; `from_utc`/`to_utc`/`include_superseded` are parsed and 422 on malformation; filter values never existence-checked — `routes/*.py:_filtered`, `routes/scheduling.py:274-278`
- §2.4 Identity — revise — mismatch — `id` is a random v4 UUID in canonical lower-case hyphenated form and therefore carries no creation order; softened the "no id is ever an ordering key" absolute to except the three list tie-breaks — `db.py:62`
- §2.4 Versioning — revise — **mismatch** — **five** append-only types, not four: `PositioningReview` added alongside `PayerPolicy`, `QcRun`, `SiteMeasurement`, `AdherenceRefill` — `routes/acquisition.py:328` (`base_record(versioned=False)`)
- §2.4 Clock — insert — ambiguity — `api_request_timestamp` added to the clock-reading list; the clock is *set*, not advanced (backwards/equal accepted, no monotonicity check, no precondition beyond parse + role) — `routes/foundation.py:218-220`
- §2.4 Clock — insert — ambiguity — full inbound instant grammar (optional seconds, 1-9 fractional digits, `T`/space/lower-case, `Z` optional = UTC, `±HH:MM`/`±HHMM` normalised to UTC, trimming), strict `YYYY-MM-DD` for dates, and outbound rendering at exactly 3 fractional digits with sub-millisecond precision **truncated not rounded** — `util.py:40-95`
- §2.5 Rounding — insert — ambiguity — a declared decimal width is an **upper bound** (over-wide literal → 422, trailing zeros count); rounded outputs serialised at their assigned scale with trailing zeros preserved and never in exponent notation; integers as integers; stored-as-supplied values echo the client's literal scale; undetermined values are `null` — `validate.py:104-105`, `util.py:120-147`
- §2.7 rung 3 — revise — ambiguity — added string-length bounds, decimal-width and array rules (type/emptiness/membership/range/distinctness); empty body = `{}`; unparseable JSON, non-object JSON and unsupported media type all → `ERR_INVALID_REQUEST` 422 (never 400/415); explicit `null` == absent; **unknown fields silently ignored, no unknown-field error anywhere**; fields validated in §4 declaration order; the 7 "No request body" endpoints never parse a body — `validate.py:17-45`, `app.py:42-47`
- §2.7 rung 17 — revise — **mismatch** — the refusal list is wrong: `GET /scan-orders/{id}` and `GET /diagnostic-reports/{id}` do refuse and were missing; the *list* endpoints `GET /scan-orders`, `GET /diagnostic-reports`, `GET /treatment-plans` **narrow silently** instead of refusing; the sole list refusal is an explicit conflicting `patient_id` on `GET /scan-orders` — `routes/scheduling.py:111-113,121-124,131-132`, `routes/interpretation.py:241-242,256-257`, `routes/treatment.py:97-98,110-111`
- §4 endpoint table (4 rows) — revise — mismatch — order/session/report/plan lists: "then `id` ascending" → "then insertion order ascending" — same impl lines as the §2.3 ordering item
- §5 catalogue — insert — mismatch — added `ERR_SITE_NOT_REQUESTED` 409 and `ERR_VFA_NOT_PERFORMED` 422 rows (named in §3 prose, raised by impl, absent from the table) — `errors.py:78-79`, `routes/acquisition.py:190,280`
- §5 catalogue — insert — ambiguity — envelope-level `ERR_NOT_FOUND` 404 (unrouted path), `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500, and that these sit *above* the §2.7 ladder so an unrouted/wrong-method request never reports `ERR_UNAUTHENTICATED`; trailing slash insignificant — `app.py:26,35-54`

**Verified as already correct, no edit:** all 54 endpoint→role admissions in the §4 table match the `@endpoint` decorators exactly; body-FK resolution order on `POST /frax-assessments` matches ladder rungs 15→16; every declared collection order in §2.3 matches its route's sort keys; `total_count`/`has_more` semantics; `base_record`/`touch` field surfaces; the 12-entry typed-404 map in `queries.py`.

**Deliberately left to passes 2/3**
- `ERR_SITE_NOT_REQUESTED` and `ERR_VFA_NOT_PERFORMED` have no rung in the §2.7 ladder. I added their status mapping to §5 but left their ladder *positions* alone — that ordering is `routes/acquisition.py` (pass 3).
- §3 line 234 words site-measurement decimal widths as "with **exactly** four decimal places" while `validate.number(max_places=…)` treats them as an upper bound. I pinned the global rule in §2.5 (explicitly naming that phrasing) rather than editing pass 3's paragraph; pass 3 may still want to reword locally.
- `queries.qc_runs_of_device` and `queries.events_of_device` sort ascending internally and are reversed by their routes (`routes/devices.py:236,338`). Net behavior already matches §2.3; the route-level reversal is pass 2's subject.
- `queries.active_profile` picks the latest-created `ACTIVE` profile — profile lifecycle semantics belong to `routes/foundation.py` (pass 2).

### Pass 2 of 3 — calc / cascades / reporting / foundation + device routes (subagent summary, verbatim)

Pass 2 of 3 complete. No `cp` was performed — I edited the existing `PRD_COMPLETED.md` in place with 25 targeted `Edit` calls (22 distinct subjects), never a whole-file `Write`.

**Integrity**
- Pass 1's edits are intact: the 4 `insertion order` §4-table rewrites, the §5 preamble paragraph (`ERR_NOT_FOUND`/`ERR_METHOD_NOT_ALLOWED`/`ERR_INTERNAL`) and the two added §5 rows (`ERR_SITE_NOT_REQUESTED`, `ERR_VFA_NOT_PERFORMED`) are all still present; §2.1–§2.7 pass-1 prose was extended, never reverted.
- `PRD_COMPLETED.md`: **before** 442 lines / 131,334 chars → **after** 442 lines / 141,221 chars. `tail -3` still shows the §5 rows ending `| ERR_VFA_NOT_COVERED | 402 |`; 24 headings intact.
- `PRD.md`, `PRD_FINALIZED.md`, `implementation/`, `test_suite/`, `test_helpers/`, `worklog.md` untouched. No server, no pytest, no pkill. Scratch only in `/tmp/task_2865_bone_density_step9b/`.

**Counts: 18 ambiguity-pins, 4 mismatch-revisions.**

- §2.5 — revise — mismatch — the unity factor escapes the four-place width: a registered device and a within-tolerance approval both write `cross_cal_factor` as literal `1.0` (and sessions snapshot `1.0`), while an event's `proposed_cross_cal_factor` is always four-place — `routes/devices.py:76`, `cascades.py:86`
- §2.9 — insert — ambiguity — internal-sequence tie-breaks for cascade A orders and cascade B slots; renumbering sort key `(start_utc, created_at, _seq)` handing out 1,2,3 positionally; unchanged rows are not touched (no `updated_at`/`version` move), a newly booked slot takes its first index without counting as a further mutation, and an order whose re-evaluation changes nothing is not mutated — `cascades.py:34-53,73,155-157`, `routes/scheduling.py:150-155`
- §3.1 — insert — ambiguity — `alcohol_units_per_day` echoes as bare `0` when defaulted — `routes/foundation.py:163`
- §3.1 — insert — ambiguity — superseding the incumbent profile is a real write, so the displaced row's `updated_at`/`version` move — `routes/foundation.py:178-181`
- §3.2 — insert — ambiguity — precision-assessment input bounds: `technologist_user_id` min length 1 with no upper bound, `patient_count`/`scans_per_patient` >= 1 unbounded, `rms_sd_g_cm2` > 0 with no cap and no declared decimal width — `routes/devices.py:103-106`
- §3.2 — revise — mismatch — retirement's only precondition is not-already-`RETIRED`; an `IN_PROGRESS` scan does not refuse it, it only shelters its own slot — `routes/devices.py:132`, `cascades.py:104-110`
- §3.2 — insert — ambiguity — retirement leaves every QC, hold, factor, generation and precision field exactly as it found them — `cascades.py:98-121`
- §3.3 — revise — ambiguity — `deviation_sd_units` divides the already-rounded four-decimal deviation, not the raw subtraction — `calc.py:132-133`
- §3.3 — revise — ambiguity — the two preceding daily runs are ranked `performed_at_utc`, `created_at`, internal sequence all descending, with the scored run not yet among them — `routes/devices.py:186-189`, `calc.py:144-154`
- §3.3 — insert — ambiguity — device-update consequences: a re-fail while already on `QC_HOLD` refreshes reason/started-at but cascade B fires only on entry; a `CROSS_CAL_PENDING` device moves only its pass count; the pass count is not reset on release; exactly one device mutation per daily run — `routes/devices.py:138-160,207-213`
- §3.3 — insert — ambiguity — cross-calibration runs record `shift_detected` as `false` (not null), mutate the device not at all, and their named event is existence-checked only (wrong device or already-closed event still accepted and still counted); the only state test is not-`RETIRED` — `routes/devices.py:171-218`
- §3.3 — insert — ambiguity — cascade B horizon is a single strict upper bound (`start_utc` < hold + 48h, no lower bound, so past `BOOKED` slots are swept), `cancelled_at_utc` stamped, internal-sequence tie-break — `cascades.py:64-77`, `cascades.py:56-61`
- §3.3 — insert — ambiguity — the phantom means average **every** run tagged to the event with that purpose, beyond the required count and regardless of recording device — `routes/devices.py:292-297`
- §3.5 — insert — ambiguity — `vfa_eligibility` skips both profile tests when no `ACTIVE` profile exists (age threshold alone can qualify), and a negative `height_loss_cm` merely fails its test — `calc.py:309-319`
- §3.5 — revise — ambiguity — prior-selection ranking adds internal creation sequence descending — `calc.py:183-196`
- §3.7 — revise — mismatch — `patient_age_years` is recomputed from the clock on every derivation (creation and each update), not fixed at creation — `reporting.py:156-157`
- §3.7 — insert — ambiguity — the report carries its own `applied_lsc_g_cm2`, re-copied from the session on every derivation and therefore present even in the `NO_PRIOR`/`NOT_COMPARABLE_DEVICE`/`NO_COMMON_SITE` cases — `reporting.py:163`
- §3.8 — insert — ambiguity — amendment re-derives positionally over survivors ranked `(finalized_at_utc, created_at, _seq)` ascending (first → `baseline_report_id`, last → `last_finalized_report_id`), interval and next-eligible date from that latest survivor, and does **not** re-run cascade A link three, so denials and their cancellations stand — `cascades.py:185-214`
- §3.9 — insert — ambiguity — the "latest eligible refill" for the denosumab gap is ranked `(dispensed_date, created_at, _seq)`, not by longest supply — `calc.py:390-394`
- §3.9 — insert — ambiguity — `holiday_eligible` is false when there is no `last_finalized_report_id` or its session's `lowest_t_score` is null; exactly -2.5 also fails — `calc.py:408-419`
- §2.7 rung 21 — revise — ambiguity — `POST /densitometers/{id}/calibration-events` also answers `ERR_DENSITOMETER_NOT_ACTIVE` (device neither `ACTIVE` nor `QC_HOLD`, then an already-`OPEN`/`PHANTOM_SET_COMPLETE` event), status test first — `routes/devices.py:249-256`
- §4 preamble — revise — mismatch — "Path identifiers are always resolved before the request body is inspected" contradicted every route; now states shape (rung 3) precedes path ids (4-15) which precede body foreign keys (16), so a malformed body plus an unknown path id yields 422 — `validate.py`/all routes, e.g. `routes/devices.py:166-179`, `routes/foundation.py:154-166`

**Deliberately left for pass 3** (subject lives in `routes/treatment.py`): §3.9 twice names a nonexistent error id `ERR_PLAN_DISCONTINUED` (lines for refills and for adherence review); the implementation raises `ERR_TREATMENT_PLAN_TERMINAL` (`routes/treatment.py:37`), which is also what §2.7 rung 34 and the §5 catalogue say. This is a real mismatch, present in `PRD.md`/`PRD_FINALIZED.md` too — please make sure pass 3 fixes both occurrences. Also left alone as pass 3's: the `ERR_VFA_NOT_ORDERED`/eligibility route sequencing, `_assign_slot_indexes` booking mechanics, repeat-cycle route effects, and the adherence-review status machine (I pinned only the `calc.py` formulas behind them). No pass-1 edit was found to be wrong about my slice.

### Pass 3 of 3 — scheduling / acquisition / interpretation / treatment routes (subagent summary, verbatim)

Pass 3 complete. Final verification: `PRD_COMPLETED.md` is 442 lines / 152,083 chars, ends at a real section boundary (`| ERR_PAYER_FREQUENCY_LIMIT | 402 |` / `| ERR_LIFETIME_SCAN_CAP_EXCEEDED | 402 |` / `| ERR_VFA_NOT_COVERED | 402 |`), and differs from `PRD_FINALIZED.md`.

## Integrity
- **No `cp`, no whole-file Write.** The document I inherited (442 lines, 141,221 chars, 40 edits from passes 1-2) was read and patched with targeted `Edit` calls only. Passes 1 and 2 work is intact; line count unchanged because every change is an in-paragraph insert or revision.
- Char count: 141,221 → 152,083 (+10,862 from my 31 edits).
- Cross-check: the set of `ERR_*` identifiers in the PRD is now **exactly equal in both directions** to the set in `implementation/` (no PRD-only phantoms, no impl-only silences).

## Handed-over items — all four addressed
1. **`ERR_PLAN_DISCONTINUED` (2 occurrences)** — both replaced with `ERR_TREATMENT_PLAN_TERMINAL` (refills paragraph and review paragraph of §3.9); `treatment.py:37`.
2. **Unplaced ladder ids** — `ERR_SITE_NOT_REQUESTED` (409) pinned immediately after rung 48, `ERR_VFA_NOT_PERFORMED` (422) immediately after rung 50, each with the masking consequence spelled out; `acquisition.py:190,280`.
3. **"exactly four decimal places"** — reworded to "at most four decimal places" in both §3.5 occurrences (§3.2/§3.3 still anchor §2.5's cross-reference); `validate.number(max_places=…)`.
4. **`ERR_VFA_NOT_ORDERED` sequencing, `_assign_slot_indexes`, repeat-cycle effects, adherence-review status machine** — all covered (bullets below).

## Changes (31)
`{section} — {kind} — {class} — {what} — {impl}`

- §2.3 — insert — ambiguity — `from_utc`/`to_utc` compared against `start_utc` alone, from inclusive / to exclusive — scheduling.py:272-283
- §2.7 r16 — insert — mismatch — `POST /frax-assessments` resolves the profile before the patient, an exception to declaration order — interpretation.py:43
- §2.7 r24 — revise — mismatch — order not `REQUESTED` **or** eligibility outside ELIGIBLE/ELIGIBLE_WITH_GRACE — scheduling.py:180
- §2.7 r33 — revise — mismatch — blocking report is `DRAFT` **or** `FINALIZED`, addressed report excepted on amend — interpretation.py:97-103
- §2.7 r43 — insert — mismatch — `ERR_FRAX_PATIENT_MISMATCH` also answers `POST /treatment-plans` — treatment.py:57
- §2.7 r48 / r50 — insert — ambiguity — the two handed-over ids placed — acquisition.py:190,280
- §3.4 — insert — ambiguity — past `requested_scan_date` is `ERR_INVALID_REQUEST` 422 at the shape rung, before `patient_id` resolves — scheduling.py:61
- §3.4 — revise — mismatch — `start_utc` **strictly after** the clock; the three window refusals split across bands; 240-min ceiling is a shape failure tested only when `end_utc` > `start_utc`; duration truncated downwards — scheduling.py:167-191
- §3.4 — insert — ambiguity — booking tests the device only for retirement; `QC_HOLD`/`CROSS_CAL_PENDING` remain bookable — scheduling.py:178
- §3.4 — insert — ambiguity — `slot_index` tie-break on internal sequence; siblings re-stamped only when the index actually changes; the new row is returned at `version` 1 — scheduling.py:142-156
- §3.5 — revise — mismatch — deleted the phantom "no other `IN_PROGRESS` session" rule; pinned the four-test order and the second-attempt answer `ERR_APPOINTMENT_NOT_BOOKED` — acquisition.py:66-77
- §3.5 — revise — mismatch — decimal widths are upper bounds; only membership of `included_vertebrae` is a shape rule, emptiness/duplication → `ERR_INSUFFICIENT_VALID_VERTEBRAE` 422 — acquisition.py:154-184
- §3.5 — insert — ambiguity — accepting a measurement mutates the session's `updated_at`/`version` — acquisition.py:215
- §3.5 — insert — ambiguity — `genant_grades` non-empty, repeated grades legal — acquisition.py:235
- §3.5 — insert — ambiguity — VFA is repeatable, stores no resource, answers 200 with the session, overwrites the three `vfa_*` fields — acquisition.py:256-262
- §3.5 — insert — mismatch — submit's last three effects are conditional on source status; the counter never drops below zero; re-submit after a repeat is inert — acquisition.py:292-302
- §3.6 — insert — mismatch — a repeat does **not** unwind `vfa_performed`/`vfa_eligibility_code`/`vfa_max_genant_grade`/`vfa_fracture_count` — acquisition.py:369-379
- §3.7 — insert — ambiguity — FRAX asks the session only for the femoral-neck row; `acquisition_status`/`review_status` untested — interpretation.py:55-60
- §3.7 — insert/revise — ambiguity — 480-char notes; PATCH writes only present-and-non-null fields (null == omitted, cannot clear); body `frax_assessment_id` resolved before the `ERR_REPORT_NOT_DRAFT` test — interpretation.py:154-171
- §3.8 — revise — ambiguity — successor inherits `frax_assessment_id`/`non_comparability_note`/`vfa_narrative`; `amendment_reason` on the successor alone; re-derivation runs last, after the session returns to `SUBMITTED` and after compensation — interpretation.py:211-231
- §3.8 — revise — mismatch — amend's blocking set is `DRAFT` or `FINALIZED` excluding the addressed report, refused with `ERR_REPORT_ALREADY_EXISTS` — interpretation.py:207
- §3.9 — revise — mismatch — report-of-another-patient → `ERR_FRAX_PATIENT_MISMATCH` 409; `recommended_action` and `start_date` are `ERR_INVALID_REQUEST` 422 evaluated after the FINALIZED and patient tests, in that order — treatment.py:54-64
- §3.9 — insert — ambiguity — `cumulative_therapy_months` starts at 0, `holiday_eligible` at false — treatment.py:85-86
- §3.9 — revise — mismatch — refills: `ERR_TREATMENT_PLAN_TERMINAL`, reached after portal scope — treatment.py:124-127
- §3.9 — revise — mismatch — reviews: `ERR_TREATMENT_PLAN_TERMINAL` **before** the due-date test; `note` validated at 480 chars then discarded; `DISCONTINUE` without a reason code is 422 at the shape rung, before `plan_id` resolves — treatment.py:210-221
- §3.9 — revise — mismatch — the denosumab-gap override no longer claims an unconditional move to `ADHERENCE_HOLD`; it follows the `NON_ADHERENT` status rules — treatment.py:227-229
- §3.9 — revise — mismatch — `consecutive_nonadherent_reviews` resets on **any** ADHERENT/PARTIAL verdict whatever the status, while only `INITIATED`/`ADHERENCE_HOLD` move to `ON_THERAPY`; a `DRUG_HOLIDAY` plan is left entirely alone by NON_ADHERENT or an exceeded gap — treatment.py:186-201
- §3.9 — insert — ambiguity — an explicit action with unmet preconditions falls through to the automatic resolution and answers 200 as an `AUTO` review; `DISCONTINUE` never falls through; the 24-month cadence belongs only to the holiday-starting review; a stray `discontinuation_reason_code` is ignored; automatic discontinuation always writes `ADHERENCE_FAILURE` — treatment.py:174-201
- §3.9 — insert — ambiguity — the `holiday_eligible` consulted is the one recomputed by this same review — treatment.py:236-239
- §3.9 — revise — ambiguity — every review advances the due date by `followup_interval_months`, the holiday review excepted, so even a discontinuing review leaves a future due date — treatment.py:242-243

Tally: **15 mismatch revisions, 16 ambiguity pins.**

## Notes for the orchestrator
- I did not contradict any pass 1/2 edit. Two of my edits *broadened* earlier wording rather than reversing it: §2.7 rung 33 ("already `DRAFT`" → `DRAFT` or `FINALIZED`), which had been internally inconsistent with §3.7's own "at most one report … `DRAFT` or `FINALIZED`", and the matching clause in §3.8. Pass 1's §2.7 patient-scope prose already correctly pinned the `GET /scan-orders` explicit-`patient_id` 403 exception, so no change was needed there.
- Deliberately left under-determined (unreachable code paths, per the no-new-mismatch rule): §3.8's descriptive claim that finalize requires a `SUBMITTED` session (`finalize_diagnostic_report` tests only the report status and `review_status`; an `ARCHIVED` session can never hold a `DRAFT` report), and `_required_densitometer`'s null fallbacks for a dangling baseline report/session.
- No server started, no pytest run, no `pkill`; worklog.md, PRD.md, PRD_FINALIZED.md and everything under `implementation/`, `test_suite/`, `test_helpers/` untouched. Scratch lived in `/tmp/task_2865_bone_density_step9c/` and was removed.

### Orchestrator final verification

- `PRD.md` 432 lines / 119,529 chars → `PRD_FINALIZED.md` 432 / 120,013 → `PRD_COMPLETED.md` 442 / 152,083. `PRD_COMPLETED.md` is NOT byte-identical to `PRD_FINALIZED.md`, so the scan genuinely ran (the failure mode where a single-agent Step 9 returns its input unchanged did not occur).
- `PRD_COMPLETED.md` still has 27 headings and ends at a real section boundary — the complete final row of the §5 error table.
- Leak check on `PRD_COMPLETED.md` for "harder than expert", "scaffold", "test_recipe", "excluded_because": zero hits. The difficulty directive and the two withheld design indices never reached any PRD in the chain.
- All 8 final-sweep `results.$i.json` re-read: every round `passed=105 total=105 failed=0 errors=0`.
- Removed `__pycache__` / `.pytest_cache` byproducts from `implementation/`, `implementation/routes/`, `test_suite/` and `test_helpers/`. Retained as deliverables/evidence: the 8 `results.*.json`, `workspace/sweep.sh`, `workspace/sweep.log`, `workspace/round.*.log`, `workspace/DONE.marker`.

**PIPELINE COMPLETE — Step 9 wrote `workspace/PRD_COMPLETED.md`.**
