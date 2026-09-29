# Worklog — task_2836_learning_management_course_shell_term_rollover

## Step 1: Create task directory — 2026-09-05T04:28:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2836_learning_management_course_shell_term_rollover` and its `workspace/` subdirectory. Index 2836 was pre-assigned by the invocation; no scan of `./tasks/` was performed.

## Step 2: Generate Scaffold — 2026-09-05T06:41:00.000Z

All three scaffold artifacts for task 2836 are complete and lint clean.

### Files (in `/home/ubuntu/github/CodingPRD/tasks/task_2836_learning_management_course_shell_term_rollover/`)

| File | Lines | Size |
|---|---|---|
| `SCAFFOLD.yaml` (§1.0–§1.7) | 3717 | 184 KB |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8 only) | 2344 | 158 KB |
| `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9 only) | 5229 | 338 KB |

`scaffold_lint.py` final verdict: **clean lint** — 66 §1.5 endpoints, 14 §1.1 entities, 21 §1.8 instances, 60 §1.9 instances, 1273 calls scanned, all FKs reverse-reachable.

### SCAFFOLD.yaml (§1.0–§1.7)
14 entities, 66 endpoints, 14 state machines, 3 concurrency rules (all OCC/`ERR_STALE_VERSION`), 9 calculations, 43 prioritised validations, 55 error codes, 6 roles (Registrar, LmsAdmin, Instructor, PrivacyReviewer, AccessibilityReviewer, Student). Profile: `multi_party_negotiation` + `workflow_orchestration`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, soft_delete_archival]`, parallel state machines, segregation-of-duties role model, immediate consistency, `expert_plus`.

### §1.8 — 9 difficulty rules / 21 instances
dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 3, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 3.

### §1.9 — all 9 taxonomy sections / 74 instances (60 active + 14 `excluded_because` stubs)
entities 11, state_machines 15, calculations 13, validations 9, endpoints 6, errors 7, rbac 6, cross_cutting_complexity_layers 6, consistency_model 1. Every stub cites a §1.8 instance that exists by name; all claim types come from the claim-extraction guide's tables.

### Notable findings during generation
- **Error-catalog sweep is now complete: all 55 §1.6 codes are triggerable** somewhere in §1.8/§1.9. `ERR_STALE_VERSION` was the last hold-out and is covered by three new OCC instances (one per §1.2.1 rule), including the self-invalidating case where a successful `POST /continuity-windows` bumps the parent term's version so replaying the same `expected_term_version` must 412.
- Three §1.4 defects found and fixed in `SCAFFOLD.yaml` while auditing coverage: (1) `ERR_RETENTION_HOLD_ACTIVE` was unreachable because `ERR_PURGE_NOT_DUE` outranked it while `retention_purge_at` is null under `LEGAL_HOLD` — priorities 27/28 swapped; (2) priority 35 contradicted §1.2 on whether a `DROPPED` enrollment still blocks a fresh row — rewritten to match §1.2 (`{ACTIVE, WAITLISTED, DROPPED}`); (3) the reviewer peer-role binding (a `PrivacyReviewer` may only post `dimension: PRIVACY`) had no §1.4 grounding — priority 2 (`ERR_ROLE_NOT_PERMITTED`) extended to cover it.
- One thing to note for the pipeline: `SCAFFOLD.yaml`'s `scenario:` key retains the verbatim first line "Generate task harder than expert level!" because the scenario was to be used unmodified. Per the known leak path, that line should be stripped from the scenario key before PRD generation so it does not reach `PRD.md`. It does not appear in either design file.

**Orchestrator post-step action:** the leaked difficulty directive line ("Generate task harder than expert level!") was stripped from `SCAFFOLD.yaml`'s `scenario:` key by the orchestrator before Step 4, per the known leak path. Verified absent from all three scaffold files; all three re-verified as parsing YAML cleanly afterwards.

## Step 3: Copy Shared Files — 2026-09-05T06:42:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T07:02:00.000Z

PRD complete at `workspace/PRD.md` — written entirely by incremental heredoc appends (11 chunks), each verified with `wc -l`/`tail`. The two withheld design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped or referenced.

### Section list (24 headings)
- **§1** Introduction
- **§2** Global Specifications & System-Wide Principles — 2.1 User and Role-Based Access Control · 2.2 API Response Structure (fixed block, verified byte-identical to `section-2.2-response-structure.md`) · 2.3 Pagination and List Ordering · 2.4 Common Record Properties and Mutation Bookkeeping · 2.5 The Logical Clock · 2.6 Numeric Precision and Rounding · 2.7 Stale-View Rejection on Cross-List, Rollover and Continuity Writes · 2.8 Cascade Discipline and Conserved Aggregates · 2.9 Segregation of Duties · 2.10 Validation Precedence (all 43 priorities, numbered)
- **§3** Business Logic & Workflows — 3.1 Registering the Term and Its Retention Calendar · 3.2 The Term Lifecycle and Its Closing Cascades · 3.3 People, Shell Provisioning, Sandbox Governance and the Archival Tail · 3.4 Enrollment, Seats, the Waitlist and the SIS Feed · 3.5 Cross-Listing Two Sections Through a Merge Request · 3.6 Course Content and Rolling It Over Into the Next Term · 3.7 Third-Party Tool Governance and Placement · 3.8 Grades, Passback to the Registrar, and Grade Disputes · 3.9 Academic Continuity: Windows and the Term's Posture
- **§4** API Endpoint Definitions (intro + 66-row, 4-column table)
- **§5** Error Code Catalogue (55-row, 2-column table)

### Final line count: 481

### Hard Contracts
**Contract 1 — Field-Name Coverage: PASS.** All 148 `entities[].fields[].name` identifiers and all 88 distinct endpoint `input`/query/path identifiers appear verbatim in backticks (0 missing, machine-checked).

**Contract 2 — Rule Coverage: PASS (8 lines).**
1. Validations: 43/43 enumerated with explicit priority order in §2.10, each with its `applies_to` endpoint set.
2. Concurrency: all 3 OCC rules (`expected_parent_shell_version`, `expected_target_shell_version`, `expected_term_version`) stated in §2.7 and re-stated at their write sites in §3.5/§3.6/§3.9, each rejecting with `ERR_STALE_VERSION`.
3. State machines: all 14 machines, all 80 declared transitions, all target states present in backticks; includes the parallel dimensions (term lifecycle × posture; tool privacy × accessibility × approval), 4 cycles, and the undeclared `NORMAL`→`CONTINUITY_MODE` jump.
4. Calculations: all 9 expressed as prose with pinned evaluation/rounding order plus worked literals (110.00 overflow utilization, 66.67 rollover gate, 3.52 chargeback, 2,825,215 s vs 2,825,214 s, 2026-10-17T12:00:00Z vs 2026-10-13T00:00:00Z, 83.33 vs 62.50, 40.00/39.70/70.00/135.00→100.00/−5.00→0.00, 250/160/90/280 ledger).
5. Every validation condition is matchable to its `error_id`; all 55 error IDs appear in prose before §5 (the 14 record-specific 404s enumerated in §2.4).
6. Endpoint side effects and role authorization: every endpoint's effects are described in §2/§3, and §4 carries the authorized roles per row.
7. Entity field structured content: `EnrollmentSyncBatch.operations` documented as an ordered 1–200 element array of `{op, shell_id, person_id, role}` processed in array order.
8. Sibling-branch symmetry: all divergent forks written as paired branches — provisioning `APPROVE`/`REJECT`, merge `APPROVE`/`DECLINE`, batch `APPLIED`/`FAILED` (200 with the failed batch, not an error envelope), rollover `COMPLETED`/`FAILED`→`COMPENSATED`, three-way `FINALIZE_REVIEW`, registrar `ACCEPT`/`RETURN`, dispute `UPHELD`/`CHANGED`.

**Contract 3 — §3 Path Purity: PASS.** Zero backticked tokens in §3 start with `/`, are a bare HTTP method, or combine method+path; zero raw method+path or bare `/collection` mentions either. §3 uses state-pair, role+action and capability framing throughout. Also verified: no pseudocode operators anywhere (`==`, `>=`, `min(`, `floor(`, `IN {`, `round_half_up` all absent), no fuzzy hedges, and no difficulty meta-instruction (`expert`/`harder than` absent).

### Coverage audit, §1.1–§1.7
- **§1.1 Entities (14/14):** AcademicTerm §3.1–3.2, Person §3.3, CourseShell §3.3/3.5, Enrollment §3.4, EnrollmentSyncBatch §3.4, MergeRequest §3.5, ContentItem §3.6, RolloverJob §3.6, ToolIntegration §3.7, ToolReview §3.7 (its `common_fields: false` shape — id + created_at only, no version, append-only — stated explicitly), ToolPlacement §3.7, GradePassback §3.8, GradeDispute §3.8, ContinuityWindow §3.9.
- **§1.2 State machines (14/14, 80/80 transitions):** covered as above, incl. system cascades and compensating transitions (`MERGED`→`PROVISIONED` returning to `PROVISIONED` not `PUBLISHED`; `FAILED`→`COMPENSATED`).
- **§1.2.1 Concurrency (3/3):** §2.7 + write sites.
- **§1.3 Calculations (9/9):** §3.1 retention schedule, §3.2 rollover completion, §3.3 sandbox chargeback, §3.4 waitlist capacity + seat ledger, §3.6 due-date projection (both variants), §3.7 risk score, §3.8 grade percentage (both variants) + points ledger.
- **§1.4 Validations (43/43):** §2.10, repeated in workflow context in §3.
- **§1.5 Endpoints (66/66):** §4 table, generated directly from the scaffold (method, path, description, roles), incl. the two underscore test-driving endpoints; 201/200/204 codes explained in the §4 intro.
- **§1.6 Errors (55/55):** §5 table with statuses (1×401, 5×403, 14×404, 1×400, 20×409, 1×412, 13×422), generated from the scaffold.
- **§1.7 Roles (6/6):** §2.1, with the entity-backed (`Instructor`, `Student` → `Person`) vs opaque distinction and header semantics.

### Verbatim last 5 lines
```
| `ERR_OPEN_DISPUTES_BLOCK_CLOSE` | 422 |
| `ERR_ROLLOVER_INCOMPLETE` | 422 |
| `ERR_ITEM_HAS_SUBMISSIONS` | 409 |
| `ERR_SANDBOX_QUOTA_EXCEEDED` | 422 |
| `ERR_SEAT_CAP_EXCEEDED` | 422 |
```
The file ends at a real boundary: the last row of the §5 error table, with a trailing newline.

**Orchestrator truncation guard (per invocation instruction):** independently verified — `PRD.md` is 481 lines, §4's table holds exactly 66 endpoint rows, §5's table exactly 55 error rows, headings run §1→§5 in order, and the file's last line is a complete table row. Not truncated; no regeneration needed. Also independently grepped for the difficulty directive and "scaffold": zero hits.

## Step 6: Generate Implementation — 2026-09-05T07:45:00.000Z

(Steps 5 and 6 ran concurrently; Step 6 returned first, so it is recorded first. Step 5's entry follows below.)

The implementation is complete and verified.

### Modules (30 files, 4,146 lines) — all under `workspace/implementation/`

| file | lines | file | lines |
|---|---|---|---|
| `start.sh` | 10 | `routes/terms.py` | 241 |
| `requirements.txt` | 1 | `routes/people.py` | 78 |
| `app.py` | 75 | `routes/shells.py` | 241 |
| `util.py` | 175 | `routes/content.py` | 170 |
| `errors.py` | 88 | `routes/enrollments.py` | 200 |
| `db.py` | 135 | `routes/batches.py` | 214 |
| `response.py` | 113 | `routes/merges.py` | 208 |
| `serialize.py` | 128 | `routes/rollovers.py` | 247 |
| `middleware.py` | 167 | `routes/tools.py` | 248 |
| `lookup.py` | 161 | `routes/placements.py` | 124 |
| `services/compute.py` | 349 | `routes/passbacks.py` | 198 |
| `services/cascade.py` | 122 | `routes/disputes.py` | 174 |
| `services/access.py` | 39 | `routes/continuity.py` | 143 |
| `routes/common.py` | 76 | `routes/testing.py` | 21 |

`services/__init__.py` and `routes/__init__.py` are empty; `__pycache__` removed.

### Endpoints
**66 URL rules** registered (`len(app.url_map.iter_rules())` minus `static`), matching the 66 rows of PRD §4 exactly. Storage is in-memory dicts only, nothing seeded at startup.

### Boot + smoke confirmation
Final fresh boot: `PORT=18471 bash start.sh` (setsid, foreground server, PID 569028, bound `0.0.0.0`). Smoke requests: unauthenticated `GET /academic-terms` → **401**; authenticated → **200** with the paginated array envelope (`limit 10 / offset 0 / total_count 0 / has_more false`); `POST /academic-terms` → **201** with correct derived fields (`add_drop_deadline_at 2026-09-07`, `finals_window_*`, `student_access_end_at 2027-01-10T23:59:59Z`, `retention_purge_at 2028-01-10T23:59:59Z`, `rollover_completion_pct 100.0`, `version 1`).

**Shutdown:** killed by exact PID only — `kill 569028` (port resolved via `ss -ltnp | grep :18471`), confirmed process gone and port free. The earlier smoke server was likewise ended with `kill 522451`; its `bash start.sh` wrapper (522449) exited with it. No `pkill` was used at any point.

### Verifications passed against a live server
- Sandbox chargeback per-shell rounding: SANDBOX 210.00 + DEV 175.00 + SANDBOX 187.50 → **3.52** (not 3.53); 4th live sandbox → `ERR_SANDBOX_QUOTA_EXCEEDED`.
- Merge round trip conserving seats: parent 1→3, child 2→0 (`MERGED`, `merged_into_shell_id` set), `seat_ledger_before/after` 3/3, term `total_active_enrollments` 3 throughout; REVERSE restores parent 1 / child 2 with child returning `PROVISIONED`. `ERR_STALE_VERSION` on bad `expected_parent_shell_version`; `ERR_SEGREGATION_OF_DUTIES` when the submitter tries to approve.
- Retention tail: term cascade concluded the shell at `GRADING`/`CLOSED`; `PROVISIONED → PURGED` → `ERR_INVALID_STATE_TRANSITION`; `ARCHIVED → PURGED` before the horizon → `ERR_PURGE_NOT_DUE`; after moving the logical clock to 2027-02-01 the purge succeeds, the shell vanishes from `GET /course-shells` but is returned under `provisioning_state=PURGED` and still readable by id. Clock restored to `2026-08-01T00:00:00Z`.
- `DELETE /content-items/{id}` → **204** empty body; missing id → 404 `ERR_CONTENT_ITEM_NOT_FOUND`; unknown route and 405 both come back in the standard error envelope with `ERR_INVALID_REQUEST`; `limit=0` → `ERR_INVALID_REQUEST`.
- All nine PRD calculations previously reproduced the PRD's own worked numbers in-process (ANCHOR_PROPORTIONAL `2026-10-17T12:00:00Z`, FIXED_OFFSET `2026-10-13T00:00:00Z`, 2,825,215 s half-up, risk-score clamps and the 40.00/70.00 boundaries, 36-hour window → 2 extension days).

One deliberate design note worth flagging: only `dropped_at`, `resolved_at` and `closed_at` are stamped from the logical clock, since PRD line 102 enumerates exactly those; `created_at`/`updated_at` use real time so `created_at` ASC ordering stays strictly increasing (with a monotonic `_seq` tie-break).

`worklog.md` was not touched, and no test/design artifacts were inspected.

## Step 5: Generate Unit Tests — 2026-09-05T07:52:00.000Z

All work is complete and audited.

### Output files

`test_helpers/` (9 files, 2,302 lines) — created earlier in this session, untouched by any Stage-2 writer (all mtimes ≤ 07:13):
`__init__.py` 43, `api_client.py` 278, `api_errors.py` 141, `assertions.py` 324, `constants.py` 85, `factories.py` 217, `fixtures.py` 678, `test_users.py` 72, `types.py` 464.

`test_suite/` (conftest + 18 test modules, 10,584 lines):

| file | lines | tests |
|---|---|---|
| conftest.py | 116 | – |
| test_difficulty_dual_variant_calc.py | 236 | 4 |
| test_difficulty_combinatorial_formula.py | 318 | 6 |
| test_difficulty_boundary_precision.py | 276 | 7 |
| test_difficulty_state_machine.py | 556 | 6 |
| test_difficulty_transitive_cascade.py | 460 | 6 |
| test_difficulty_priority_pair.py | 411 | 7 |
| test_difficulty_cross_entity_state.py | 319 | 4 |
| test_difficulty_temporal_overlap.py | 328 | 4 |
| test_difficulty_compensating_invariant.py | 624 | 6 |
| test_corner_entities.py | 684 | 11 |
| test_corner_state_machines.py | 734 | 10 |
| test_corner_calculations.py | 592 | 8 |
| test_corner_validations.py | 588 | 7 |
| test_corner_endpoints.py | 1103 | 6 |
| test_corner_errors.py | 1377 | 7 |
| test_corner_rbac.py | 938 | 5 |
| test_corner_cross_cutting.py | 721 | 4 |
| test_corner_consistency.py | 203 | 1 |

**Total: 109 test functions.**

### Coverage against the two design indices

- **Queue A (difficulty):** 21 instances, 0 stubs → **21/21 translated, 0 skipped**, every one with ≥2 tests (50 tests).
- **Queue B (corner):** 74 instances, 14 `excluded_because` stubs → 60 non-stub, **59 translated, 1 skipped** (59 tests). The 14 stubs got no tests; each stub's cited difficulty instance resolves.
  - Skipped: `Corner/calculations/revised_vendor_metadata_rescores_the_tool_without_advancing_its_approved_version` — the instance asserts new `risk_score` values after `PATCH /tool-integrations/{id}`, but PRD §3.7 enumerates the re-score triggers ("whenever the review is finalized, whenever a placement becomes active or is removed, and whenever the tool is suspended") and says a DRAFT tool's `risk_score` is null, so the asserted numbers are not uniquely derivable. No placeholder, no xfail.

### Verification performed (scratch under `/tmp/task_2836_scratch/`)

- `py_compile` clean on all 19 test-suite modules; `test_helpers` imports cleanly.
- Design-tag audit: 109/109 tests carry exactly one `Design:` line, it is the last docstring line, every tag resolves verbatim to a `name:` in the source yaml, and no tag points at an excluded stub. **0 problems.**
- PRD-quote audit: 605 quoted fragments checked as whitespace-normalised substrings of `workspace/PRD.md`. One real defect found and fixed (my `boundary_precision` tool-threshold quote had appended a `.` where the PRD has `;`); the single remaining "miss" is a known artifact of the checker's quote pairing around the PRD's own nested `"tool rejected"` literal — that citation is verbatim.
- Static reference audit: every `fx.*`, `fac.*`, `assertions.*`, `constants.*`, `api.*`, and framework import used anywhere in the suite exists. **0 missing.**
- No occurrence of "scaffold" or design-index vocabulary; no classes, no duplicate test names, every test cites the PRD.
- Nothing written under `workspace/`, no stray `test_helpers/`/`test_suite/` inside it, no implementation code read or written, and `worklog.md` was not touched by me.

Notable adjudications where the design indices contradicted the PRD were resolved in the PRD's favour and reported by each writer: `risk_score` is null (not 0.00) on a DRAFT tool; a merely `REQUESTED` tool placement leaves `publish_readiness` true (§3.7 "publish-ready exactly when `blocked_placement_count` is 0"); `shell_type` is not a declared list filter; absolute `version` literals were replaced with PRD-derived relative increments; under-determined timestamp widths are compared as parsed instants or prefixes.

**Orchestrator note on Step 5/6 concurrency:** the two agents were launched in consecutive assistant messages rather than a single one, so Step 6 began a few seconds after Step 5. Physical isolation still held — Step 6 was additionally given a hard constraint forbidding it from reading `test_helpers/`, `test_suite/`, or the two design indices, and it confirmed on exit that no test or design artifact was inspected.

## Step 7: Run Tests and Iterate — 2026-09-05T08:10:00.000Z

All 8 rounds clean. Final summary.

**Iterations run:** 2 (one diagnostic sweep, one verification sweep after the fix).

**Iteration 1 findings** — deterministic, identical in all 8 rounds: 120/122 passed, with the same 2 failures every round (so no flakiness, no sweep reaping, no load artifacts):
- `test_corner_cross_cutting.py::test_merge_request_creation_is_guarded_by_the_parent_shells_stored_version` — `AssertionError: a successful merge-request create increments the parent shell's version by one: expected 3, got 2`
- `test_corner_cross_cutting.py::test_rollover_job_creation_is_guarded_by_the_target_shells_stored_version` — same shape on the target shell.

**Diagnosis:** Both assertions trace to verbatim PRD §2.7 prose, so STEP 1a/1b pass and the rule is uniquely derivable:
- "A successful create increments the parent shell's `version` by one, so a superseding request must re-read the parent shell first."
- "A successful create increments the target shell's `version` by one."

STEP 2 audit of `test_helpers/` was clean: `open_merge_request` / `open_rollover_job` (`test_helpers/fixtures.py`) echo the parent/target record's live `version`, and the failing tests re-read the shell via `read_shell` before each create. Setup, identity (`LmsAdmin`), and payload shape all match PRD. The tests were faithful. Confirmed the third sibling case (`POST /continuity-windows`) already did the bump via `mark(term)` — the two shell-guarded creates were simply the ones that had been missed, which is why only those two failed.

**Tests deleted:** none. Both failures were genuine implementation defects backed by verbatim PRD sentences.

**Fixes applied to `test_helpers/`:** none required.

**Fixes applied to `implementation/`:**
- `workspace/implementation/routes/merges.py` — `create_merge()`: added `mark(parent)` after the merge row is stored, so a successful `POST /merge-requests` advances the guarded parent shell's `version`/`updated_at` per PRD §2.7.
- `workspace/implementation/routes/rollovers.py` — `create_job()`: added `mark(target)` after the job row is stored, same rule for the guarded target shell.

Both files already imported `mark` from `db`, and `db.flush()` skips records created in the same request, so the bump lands only on the pre-existing shell. Before applying, I verified no other test asserts the shell version is unchanged across these creates (`test_corner_rbac.py:879` reads the parent *before* the merge create; `test_difficulty_compensating_invariant.py` captures `target_before` after the create but only asserts `storage_mb`/`content_item_count`).

**Final per-round results:** rounds 1–8 all `122/122` passed, 0 failed, 0 errors, 0 skipped.

**Artifacts on disk:** all 8 files present at `workspace/implementation/results.1.json` through `results.8.json`.

`worklog.md` was not read, written, or modified.

**Orchestrator verification (per the Step 7 sweep-artifact guard):** independently re-read all 8 `results.$i.json` — each exists, each parses, each reports `passed=122 / total=122, failed=0, errors=0`, all written at 08:06. Confirmed genuine, not a claimed-clean sweep. Step 8 is NOT skipped: Step 7 applied 2 `implementation/` fixes.

## Step 8: Finalize PRD — 2026-09-05T08:14:00.000Z

`PRD_FINALIZED.md` created and is byte-identical to `PRD.md`. No edits were warranted.

### Line counts
- `PRD.md`: 481 lines
- `PRD_FINALIZED.md`: 481 lines
- Delta: 0 lines, 0.00% (`cmp` reports identical)

### Changes
None. Both Step 7 items were pure implementation defects against PRD prose that was already verbatim and uniquely derivable, so there is no PRD silence or PRD/impl mismatch left to pin.

### Per-item analysis (the mandatory pre-edit search, run even though it produced no edit)

**Item 1 — `merges.py::create_merge()` gained `mark(parent)`**
- (a) Subject: the parent `CourseShell`'s `version`/`updated_at` bump caused by a successful `POST /merge-requests`.
- (b) Impl paths enumerated and read: `routes/merges.py` in full (create at :88, plus every other `mark()` callsite — `relocate()` :118/:126/:130/:132, `send_home()` :143/:147/:150/:152, and all five transition branches :176/:191/:200/:210); `db.py` `mark()` :93, `set_field()` :106, `flush()` :115, `new_record()` :59; grep for all three `expected_*_version` names across `implementation/` (hits only in `routes/merges.py`, `routes/rollovers.py`, `routes/continuity.py`, `serialize.py`).
- (c) No wording adjustment: PRD §2.7 bullet 1 (line 116) already states "A successful create increments the parent shell's `version` by one, so a superseding request must re-read the parent shell first," §2.10 band 12 (line 151) already orders the check, and §2.4 (line 94) already covers the accompanying `updated_at` refresh. `flush()` bumps each dirty record exactly once per request and skips records created in that request, and the create marks only `parent` (never the child, never the term), so the observable is exactly +1 on the parent — matching the existing prose with no gap.

**Item 2 — `rollovers.py::create_job()` gained `mark(target)`**
- (a) Subject: the target `CourseShell`'s `version`/`updated_at` bump caused by a successful `POST /rollover-jobs`.
- (b) Impl paths enumerated and read: `routes/rollovers.py` in full (create at :90, `run_copy()` :178, `copy_grades()` :125, `drive_job()` VALIDATE/EXECUTE/COMPENSATE at :209/:230/:231/:243/:245/:248); `routes/continuity.py` :37–98 (the third sibling create, `mark(term)` at :97) to confirm the three guarded creates behave uniformly; `db.py` as above.
- (c) No wording adjustment: §2.7 bullet 2 (line 117) already states the target-shell bump verbatim, and the continuity sibling is additionally restated at §3.9 (line 338). The rollover create marks only `target` — not the source shell and not the target term — so nothing beyond the existing sentence is exhibited. I deliberately did **not** mirror the §3.9-style restatement into §3.5 (line 258) or §3.6 (line 272); those sections defer to §2.7 and adding redundant prose would be an invented edit with a fresh-mismatch risk and no behavioral gain.

One out-of-scope asymmetry noted but intentionally left untouched: `POST /rollover-jobs` persists and serializes `expected_target_shell_version` on the job record (`routes/rollovers.py:74`, `serialize.py:62`) while the merge and window records do not persist their echoed version. That was not part of the Step 7 diff and no test exercised it, so it is outside this step's hard scope.

**Orchestrator note:** a byte-identical `PRD_FINALIZED.md` is a legitimate Step 8 outcome here — Step 7's two fixes moved the *implementation* onto PRD prose that was already verbatim and uniquely derivable, so there was no silence or mismatch to pin. Independently confirmed with `cmp` (identical). Step 9 is a different matter and must not be identical; it is run below as three sequential impl-module-partitioned passes over one shared `PRD_COMPLETED.md`.

## Step 9: Complete PRD — 2026-09-05T09:05:00.000Z

Run as **three sequential passes partitioned by implementation module** over one shared `workspace/PRD_COMPLETED.md` (pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 edited in place and were forbidden from copying or reverting). Partitioning keeps each pass from having to hold the whole 4,146-line codebase in context, which is the known failure mode where a single monolithic pass silently no-ops and leaves `PRD_COMPLETED.md` byte-identical to its source.

Cumulative result: **481 → 483 lines, 109,368 → 130,552 chars (+21,184 chars, +19.4%), 75 edit sites — 56 ambiguity-pins, 19 mismatch-revisions.**

### Pass 1 — core/global layer + terms, people, shells, content (app.py, util.py, errors.py, db.py, response.py, serialize.py, middleware.py, lookup.py, routes/common.py, routes/testing.py, routes/terms.py, routes/people.py, routes/shells.py, routes/content.py, services/access.py)

483 lines / 116,804 chars after the pass (+7,436 chars). **22 ambiguity-pins, 4 mismatch-revisions.**

- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 upper-case-alphanumeric chars — `response.py:13,24`
- §2.2 — insert — ambiguity — `api_request_timestamp` comes from real wall-clock time, not the logical clock — `response.py:30`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset`, out-of-range `limit`, negative `offset` → `ERR_INVALID_REQUEST`; empty string = absent — `response.py:85-109`
- §2.3 — insert — ambiguity — `created_at` ties broken by monotonic insertion sequence — `db.py:132-135`
- §2.4 — insert — ambiguity — `created_at` read from real wall clock — `db.py:59-61,121`
- §2.4 — insert — ambiguity — one request advances a record's `version` by at most one; a record created in a request stays at 1; a no-op `PATCH` still counts as a mutation — `db.py:93-129`, `terms.py:136`, `people.py:77`, `content.py:116`, `tools.py:112`
- §2.4 — insert — ambiguity — body FK as `null`/empty string = absent; any other non-resolving value, including a non-string, → that type's 404 — `lookup.py:146-161`
- §2.5 — insert — ambiguity — clock endpoint answers 200 with `data` = `{to_iso8601, current_utc}`, the only non-resource `data`; every record instant besides `created_at`/`updated_at` renders without a fractional part on whole seconds — `testing.py:13-21`, `util.py:35-44`, `response.py:34-36`
- §2.7 — insert — ambiguity — only `expected_target_shell_version` is echoed in a response; the merge and window guards are consumed and never returned — `serialize.py:47-52,60-66,98-102`
- §2.10 band 3 — insert — ambiguity — ownership is judged only on a record that resolves; otherwise the 404 of bands 4/5 wins — `content.py:41-44,94-97,124-127`
- §3.1 — insert — ambiguity — `finals_window_start_at` carries no constraint at all — `terms.py:61-64`
- §3.1 — insert — ambiguity — term update accepts only those three fields, recomputes the retention pair unconditionally, and is `ERR_INVALID_STATE_TRANSITION` from `CLOSED`/`ARCHIVED` — `terms.py:118-137`
- §3.2 — insert — ambiguity — `reason` on term-lifecycle, posture and shell-lifecycle transitions is validated but never persisted — `terms.py:146,211`, `shells.py:208`
- §3.2 — **revise — mismatch** — `rollover_completion_pct` is also recomputed at the end of every successful term lifecycle transition, and the gate's recomputation persists only when the gate passes — `terms.py:169-181,200`
- §3.2 — insert — ambiguity — all four term aggregates are re-derived wholesale at the end of every lifecycle transition and posture change — `terms.py:199,239`
- §3.3 — **revise — mismatch** — `sis_person_id` uniqueness is not enforced and has no error code — `people.py:19-39`
- §3.3 — insert — ambiguity — person update accepts only `full_name`/`ferpa_block`/`access_revoked_at`; explicit `null` clears `access_revoked_at` — `people.py:61-77`
- §3.3 — **revise — mismatch** — the owner's `FACULTY`/`STAFF` affiliation is *not* verified; any registered person may own a shell — `shells.py:31-91`
- §3.3 — insert — ambiguity — a shell may be requested against a term in any `lifecycle_state`, and reads `publish_readiness` true / `blocked_placement_count` 0 while still `REQUESTED` — `shells.py:82-83`
- §3.3 — insert — ambiguity — `target_state` accepts all eight provisioning states; the five off the archival tail are `ERR_INVALID_STATE_TRANSITION`, not a shape failure — `shells.py:207,237-239`
- §3.6 — insert — ambiguity — `points_possible`/`storage_mb` default 0.00 and must be ≥ 0; authoring is gated only by ownership + sandbox expiry; reads are unscoped for `Student` — `content.py:37-52,73-88`
- §3.6 — insert — ambiguity — `due_at` cleared by explicit `null`; delete is a hard delete; submissions answer 201 with the item and validate only that `enrollment_id` resolves — `content.py:108-147`
- §3.8 ¶1 — insert — ambiguity — `_grade-records` answers 201 with the enrollment; `earned_points` has no lower bound; role/state and same-shell unchecked — `content.py:150-170`
- §3.9 — insert — ambiguity — the posture capacity sweep walks shells in `created_at` order over everything but `REJECTED`/`PURGED`, promoting only on `PROVISIONED`/`PUBLISHED` — `terms.py:232-238`
- §4 (4 list rows) — revise — ambiguity — actual filter sets for `/academic-terms`, `/people`, `/course-shells`, `/content-items` — `terms.py:103-108`, `people.py:45-51`, `shells.py:97-103`, `content.py:76-81`
- §4 submissions row — **revise — mismatch** — "against a graded item" → any content item type, answering with the updated item — `content.py:136-147`
- §5 intro — insert — mismatch-adjacent — framework fallbacks: unrouted path → 404 and undeclared method → 405, both with `error_id` `ERR_INVALID_REQUEST` despite the table pairing it with 400, decided before authentication; trailing slashes tolerated — `app.py:34-41,46,56-61`

Judged already uniquely pinned (no change): error-id→status table vs `errors.py:4-59`; six roles with 401/403 handling (`middleware.py:33-48`); `ToolReview` immutability; logical clock epoch `2026-08-01T00:00:00Z` and the three clock-stamped instants; retention calendar two-step with 23:59:59 and `LEGAL_HOLD` → null purge; publish precondition order; `PURGED` soft-delete listing; duplicate-section-code scoping and the three-shell sandbox quota; `total_count`/`has_more` semantics; term list ordering.

### Pass 2 — enrollments, batches, merges, rollovers, compute, cascade

483 lines / 124,020 chars after the pass (+7,216 chars, 0 new lines — every edit in-paragraph). **14 ambiguity-pins, 11 mismatch-revisions.**

- §3.2 — revise — mismatch — recompute-trigger list for `rollover_completion_pct` corrected to shell created/rejected/**purged**, job settling into `COMPLETED`, the registration gate, and the end of every successful term lifecycle transition; added that compensating a failed job, applying a merge and reversing one do **not** recompute it — `cascade.py:84`, `merges.py:194-211`, `rollovers.py:234-249`
- §2.1 — insert — mismatch — `GET /enrollments` carries only the Student half of the ownership rule; a Student omitting `person_id` is refused `ERR_NOT_RESOURCE_OWNER` — `enrollments.py:104-108`
- §3.1 — insert — ambiguity — the student post-term gate runs once per term represented in the matched rows, and its `access_revoked_at` half still runs on an empty page — `enrollments.py:117-124`
- §3.4 — insert — ambiguity — the seat cap is derived afresh from current posture on every gate; gates never read the stored `effective_seat_cap`; a refused `PROMOTE` leaves the freshly written cap behind with `version` unchanged — `compute.py:95-129`, `enrollments.py:161-163`
- §3.4 — revise — mismatch — removed "on both directions of a cross-list merge" from the capacity-rule trigger list; step four fires only on drops and posture changes over PROVISIONED/PUBLISHED shells; merges re-derive step five only — `compute.py:142-160`, `merges.py:109-152`
- §3.4 — insert — ambiguity — a new enrollment row's opening values (four money/pct fields 0.00, `final_grade_pct` null, `reinstatement_count` 0, `dropped_at` null) — `enrollments.py:37-60`
- §3.4 — insert — ambiguity — a transition `reason` must be non-empty if supplied and is not persisted — `enrollments.py:142`
- §3.4 — insert — ambiguity — batch staging resolves no per-operation ids; `operations` echoed back cleaned to `op`/`shell_id`/`person_id`/`role`; `failure_reason` opens null — `batches.py:21-48`
- §3.4 — insert — ambiguity — a supplied `batch_seq` is held to nothing beyond being an integer — `batches.py:74`
- §3.4 — insert — ambiguity — the APPLY ADD role-conflict sweep, including intra-batch duplicate pairs, outranks the feed-order check and the failure fork; the owner-as-own-student and sandbox bars are not re-applied — `batches.py:181-191`
- §3.4 — revise — ambiguity — a `DROP` with no ACTIVE row counts nothing yet still runs the promotion pass over that shell — `batches.py:126-135`
- §3.4 — revise — ambiguity — the two `failure_reason` literals and their precedence (rejected tally wins over drift) — `batches.py:199-205`
- §3.4 — revise — mismatch — waitlist degradation on batch `ADD` reaches a `STUDENT` role alone; every other role is created `ACTIVE` however full the shell — `batches.py:120-121`
- §2.10 bands 20/21/22 — revise — mismatch — endpoint lists now include `POST /merge-requests/{id}/transitions` with `APPROVE` — `merges.py:183-187`
- §2.10 band 35 — insert — mismatch — per-endpoint scoping of the `ERR_ROLE_CONFLICT` sub-rules — `batches.py:181-191`, `enrollments.py:84-90`
- §3.5 — revise — ambiguity — APPROVE re-applies all three linkage gates (not-already-merged, both-OFFICIAL-same-term, no-chain) — `merges.py:22-41,183-186`
- §3.5 — insert — ambiguity — WAITLISTED child rows do not travel on APPLY, keep their `waitlist_position`, and count nowhere while the child is MERGED — `merges.py:112-128`, `compute.py:191-196`
- §3.6 — revise — mismatch — VALIDATE also requires a source term different from the target term and no target enrollments; the `target_term_id`-matches-shell shape check is decided ahead of the DRAFT precondition — `rollovers.py:26-40,195-204`
- §3.6 — revise — mismatch — `strip_grades` false carries no points: the twin's `earned_points_total` is overwritten then immediately re-derived from the twin's own grade records, settling back at 0.00 with only a `version` bump — `rollovers.py:113-126`, `compute.py:234-245`
- §3.6 — insert — ambiguity — a copy carries the source item's `item_type`, `title`, `points_possible` and `storage_mb` unchanged — `rollovers.py:153-166`
- §3.6 — insert — ambiguity — completion advances the target term's `version` regardless of movement; the quota fork is weighed before settlement, so an unsettled but in-quota job rests permanently in `COPYING` with `failure_reason` null — `rollovers.py:212-232`
- §3.6 — revise — ambiguity — `copied_storage_mb` added to the deliberately-preserved audit list on COMPENSATE — `rollovers.py:236-249`
- §3.8 — insert — ambiguity — a grade record outlives its content item's deletion, so `earned_points_total` keeps the points while `graded_points_possible` drops them (a `provisional_grade_pct` above 100.00 is reachable); deletion does not re-derive the affected enrollments — `compute.py:234-245`, `content.py:121-132`

Pass 1's §3.2 hand-off flag — **resolved**: audited every `recompute_rollover_pct` call site (`shells.py:90`, `shells.py:150`, `terms.py:200`, `terms.py:169-181`, `rollovers.py:229`, `cascade.py:84`); neither `merges.py` APPLY/REVERSE nor the COMPENSATE branch touches it. The staleness is observable (2 eligible / 1 completed = 50.00; merging the incomplete child into the completed parent should read 100.00 but the stored figure stays 50.00).

### Pass 3 — tools, placements, passbacks, disputes, continuity (final pass)

483 lines / 130,552 chars after the pass (+6,532 chars). **20 ambiguity-pins, 4 mismatch-revisions.**

- §2.6 — revise — **mismatch** — `vpat_score` is stored exactly as supplied (unquantised) and enters the risk arithmetic at that precision — `tools.py:44,100`
- §3.1 — insert — ambiguity — boundary asymmetry of the student gate: `student_access_end_at` admits its instant, `access_revoked_at` does not — `access.py:32,37`
- §3.7 ¶290 — revise — ambiguity — named the "five governance attributes"; `vendor_name`/`tool_name` fixed at registration, editable in any `approval_state` — `tools.py:97-111`
- §3.7 ¶294 — revise — ambiguity — reviewer segregation-of-duties is scoped to the **current review round** — `tools.py:208-214`
- §3.7 ¶296 — revise — **mismatch** — only an `ACTIVE` removal re-scores; `PATCH` and review filing never do; `REQUESTED`/`BLOCKED` removal leaves the tool untouched — `tools.py:92-113`, `cascade.py:44-55`
- §3.7 ¶298 — insert — ambiguity — the rejection sweep re-derives count and re-scores once after the last blocking; since activation demands `APPROVED`/`CONDITIONAL` a finalizing tool holds no active placement; `REJECTED` is terminal — `tools.py:145-153`, `cascade.py:106-113`
- §3.7 ¶300 — revise — ambiguity — `active_placement_count` re-derived per blocking but `risk_score` recomputed **once** after the whole sweep; `approved_version` survives suspension — `cascade.py:97-113`, `tools.py:165-174`
- §3.7 ¶304 — insert — ambiguity — `ACTIVATE` runs from `REQUESTED` only, so `BLOCKED` can never be revived — `placements.py:99`
- §3.7 ¶306 — insert — ambiguity — removal never clears `blocked_reason`; regaining `publish_readiness` triggers no automatic re-publish — `cascade.py:44-55`
- §3.8 ¶312 — revise — **mismatch** — "`WAITLISTED`/`DROPPED` rows keep a `provisional_grade_pct` of 0.00" was a false universal; reworded to "no passback ever writes one; a row that never carried a grade record keeps 0.00" — `compute.py:234-255`, `passbacks.py:27-33`
- §3.8 ¶314 — insert — ambiguity — staging derives the provisional percentage from the enrollment's **stored** totals, never from grade records (so an above-100.00 figure is restated, not corrected), recomputes no point total, and re-derives `staged_enrollment_count` at staging, on every submission and on every restaging — `passbacks.py:27-33,94-100`
- §3.8 ¶318 — insert — ambiguity — an omitted `note` leaves the earlier `registrar_note` standing; SoD compares against the **most recent** `SUBMIT` — `passbacks.py:153,185-186,181`
- §3.8 ¶320 — revise — **mismatch** — the bucket-event list's "submission" is true only out of `STAGED`; a resubmission out of `AMENDED` writes no bucket at all — `passbacks.py:143-151`
- §3.8 ¶322 — revise — ambiguity — the access gate reads the **passback's own** term; the filing gate is exhaustive; `claimed_earned_points` stored as supplied, unbounded, never entering the ledger — `disputes.py:36-58`
- §3.8 ¶324 — revise — ambiguity — the resolution `note` is validated but persisted nowhere — `disputes.py:133`
- §3.8 ¶324 — insert — ambiguity — a `CHANGED` resolution leaves `graded_points_possible`/`provisional_grade_pct` standing, and the adjustment lands on the enrollment, so a later grade record supersedes it — `disputes.py:159-161`
- §3.8 ¶326 — revise/insert — ambiguity — the `open_dispute_count` gate is read only after the posture freeze; submission, dispute filing and the round-closing resolution each advance the term's `version` while staging/restaging/registrar decisions do not — `passbacks.py:144-149,155`, `disputes.py:77,117`
- §3.9 ¶330 — insert — ambiguity — `null`/empty `shell_id` yields a term-wide window; a supplied shell must resolve but need not belong to the named term — `continuity.py:42,59`, `lookup.py:146-161`
- §3.9 ¶334 — revise — ambiguity — the per-shell half-open exclusion is scoped to windows **of the same term** — `continuity.py:21-23,60-63`
- §3.9 ¶336 — insert — ambiguity — the two-outage cap is scope-blind (term-wide and shell-scoped outages share one pool) — `continuity.py:66-73`
- §3.9 ¶340 — insert — ambiguity — `closed_at` stays null on a cancelled window; neither transition advances the term's `version` — `continuity.py:131-142`
- §4 `GET /tool-integrations` — insert — ambiguity — filters `vendor_name`, `approval_state`, `data_sharing_scope` — `tools.py:78-82`
- §4 `GET /tool-reviews` — insert — ambiguity — filters `dimension`, `decision` — `tools.py:237-241`
- §4 `GET /continuity-windows` — insert — ambiguity — filters `kind`, `window_state` — `continuity.py:104-109`

(State-only list filters — `placement_state`, `passback_state`, `dispute_state` — were already pinned by §2.3's global rule, so those three §4 rows were left alone.)

Pass 2's three hand-off flags — **all resolved**: (1) the `student_gate` `<` / `<=` asymmetry is real and now pinned in §3.1, with §3.8 ¶322 separately pinning that the term read is the passback's own; band 14's "still in the future" already implies strictness and was left untouched. (2) `block_placement` calling only `recompute_tool_placements` is not a mismatch — ¶300 was tightened to "recomputed once, after the whole sweep", and the same split exposed the genuinely wrong claim next door in ¶296. (3) Passback staging reading stored totals is pinned in ¶314 and is consistent with pass 2's deleted-content-item insert.

**Contradiction found and reconciled by pass 3:** §3.8 ¶312's original claim that `WAITLISTED`/`DROPPED` rows keep `provisional_grade_pct` 0.00 contradicted pass 2's ¶310 insert (role and state are not checked when a grade record is written). Reworded so both paths are true. No pass-1 or pass-2 authored sentence was overwritten — all four of pass 3's mismatch fixes landed on prose byte-identical to the original PRD.

### Final integrity check (pass 3, then re-verified independently by the orchestrator)

- `PRD_COMPLETED.md` = **483 lines / 130,552 chars**; source `PRD_FINALIZED.md` = 481 lines / 109,368 chars → **+21,184 chars**. Confirmed with `cmp` that the two files differ (the scan did not silently no-op).
- File ends at the last row of the §5 error table (`| ERR_SEAT_CAP_EXCEEDED | 422 |`), not mid-sentence.
- §4 holds exactly **66** endpoint rows; §5 exactly **55** error rows; heading sequence §1 (L3) → §2 (L11) → §3 (L184) → §4 (L348) → §5 (L421) intact.
- Pass-1 and pass-2 spot-checks both still present after pass 3.
- Zero occurrences of "scaffold" or the difficulty directive.

## Pipeline complete — 2026-09-05T09:05:00.000Z

Step 9 has written `workspace/PRD_COMPLETED.md`. Final artifact set: `SCAFFOLD.yaml` + two design indices, `test_helpers/` (9 files), `test_suite/` (conftest + 18 modules, 122 collected tests), `workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}`, and `workspace/implementation/results.{1..8}.json` all at 122/122.
