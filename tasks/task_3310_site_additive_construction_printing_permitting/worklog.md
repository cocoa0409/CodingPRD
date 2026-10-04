# Worklog — task_3310_site_additive_construction_printing_permitting

## Step 1: Create Task Directory — 2026-09-30T19:18:00.000Z

Task directory pre-allocated at ./tasks/task_3310_site_additive_construction_printing_permitting/ with workspace/ inside; verified existence (no new index computed, no other task_* directory created).

## Step 2: Generate Scaffold — 2026-09-30T20:00:00.000Z

Subagent summary (final hand-back after reduction passes):

  Endpoint count: 35
  Lint verdict: clean (616 calls scanned, 0 violations)
  Files changed: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml (all under /home/ubuntu/github/CodingPRD/tasks/task_3310_site_additive_construction_printing_permitting/)

Earlier subagent report (initial generation, pre-reduction):

  All three files on disk, lint-clean.
  Files written:
  - SCAFFOLD.yaml — §1.0–§1.7 (no design keys)
  - SCAFFOLD_DIFFICULTY_DESIGN.yaml — single top-level key scaffold_difficulty_design (§1.8)
  - SCAFFOLD_CORNER_DESIGN.yaml — single top-level key scaffold_corner_design (§1.9)
  Counts (initial): Entities 13 (Jurisdiction, Site, CommunityDeployment, StructuralPlan, PlanRevision, PermitApplication, PrinterSetup, MaterialBatch, WeatherObservation, PrintJob, PrintInterruption, LayerInspection, ConventionalTradeTask); Endpoints 85; State machines 11; Calculations 9 (permit_fee_calculation, print_window_utilization, learning_curve_factor, posture_derivation, print_schedule_overlap, cure_penalty_layers, foundation_cure_completion, pumping_window, layer_inspection_outcome); §1.8 test instances 18; §1.9 test instances 21.
  Difficulty-maximizing choices: 3 OCC concurrency rules on Site; dual-variant calculations on permit fee (PRESCRIPTIVE vs AM) and learning curve (FORWARD_LOOKING vs CHRONOLOGICAL); combinatorial formulas; two cyclic state machines (PermitApplication AM_REVIEW ↔ RESUBMIT_REQUIRED; LayerInspection repair loop); two transitive cascades; two priority-pair conflicts; two boundary checks; two cross-entity state dependencies; two temporal-overlap rules; two compensating invariants; segregation of duties; logical clock test-driving endpoint with fixed 2026-09-01T00:00:00Z default.

Orchestrator note: initial scaffold had 85 endpoints, which exceeds the known ≤40 ceiling for Step 6 impl-gen; directed the subagent through several reduction rounds (85 → 64 → 54 → 35) via endpoint folds (transition/action endpoints) and FK demotions. Verified on disk: 35 endpoints, 13 entities, 10 state machines, 9 calculations; design files present with correct single top-level keys.

## Step 3: Copy Shared Files — 2026-09-30T20:04:00.000Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-30T20:15:00.000Z

Subagent summary (verbatim):

  All three contracts PASS. Final summary:

  **File written:** `/home/ubuntu/github/CodingPRD/tasks/task_3310_site_additive_construction_printing_permitting/workspace/PRD.md` — 324 lines.

  **Section list:**
  - §1 Introduction
  - §2 Global Specifications (2.1 RBAC, 2.2 API Response Structure verbatim, 2.3 Pagination, 2.4 Logical Clock, 2.5 Common Resource Properties, 2.6 Nested Retrieval, 2.7 Precision, 2.8 OCC, 2.9 Idempotency, 2.10 Site Posture, 2.11 Validation Ordering)
  - §3 Business Logic (3.1 Jurisdictions & Deployments, 3.2 Site lifecycle, 3.3 Plans & Revisions, 3.4 PrinterSetup, 3.5 MaterialBatch, 3.6 Weather, 3.7 PrintJob, 3.8 LayerInspection, 3.9 Learning Curve, 3.10 Permits & Trades)
  - §4 Endpoint Definitions (4-column table, 34 endpoints)
  - §5 Error Code Catalogue (2-column table, 27 errors)

  **Contract reports:**

  - **Contract 1 (Field-Name Coverage):** PASS — 106 required identifiers (entity fields + endpoint inputs + common fields), 106 present, 0 missing.
  - **Contract 2 (Rule Coverage):** PASS by construction — every state-machine transition (Site 8, StructuralPlan 7, PlanRevision 4, PermitApplication 11, PrinterSetup 5, MaterialBatch 4, PrintJob 7, PrintInterruption 2, LayerInspection 4, ConventionalTradeTask 5) is rendered with from/to states, preconditions paired to error IDs, and side effects; every calculation (permit_fee_calculation, print_window_utilization, learning_curve_factor, posture_derivation, print_schedule_overlap, cure_penalty_layers, foundation_cure_completion, pumping_window, layer_inspection_outcome) is expressed in precise business prose with constants embedded (250000/4500/175000/0.10, 8 min/layer, 3/3 windows, 30/20/45 min per mix, 60-min hard cap, 10-min cure window, 72-hour cure, 1.5 MPa / 6 mm, 15 mm slump tolerance, 40-60/55-75/30-50 kg/min windows); all three OCC rules named with expected_site_version + ERR_STALE_VERSION (HTTP 412); the 14-priority validation ordering is explicitly enumerated in §2.11.
  - **Contract 3 (§3 Path Purity):** PASS — 568 backticked tokens scanned in §3, 0 tokens starting with `/`, 0 bare HTTP-method tokens, 0 method+path combos.

  Every scaffold rule (state machines, calculations, validations, errors, roles, OCC) is covered in prose.

Orchestrator verification: PRD.md is 324 lines; all 35 scaffold endpoint paths appear verbatim in the PRD text (subagent's "34 endpoints" was a miscount — coverage is complete).

## Step 5: Generate Unit Tests — 2026-09-30T20:40:00.000Z

Subagent summary (verbatim):

  Done. All files verified on disk; everything compiles and imports cleanly; no skip/xfail markers anywhere.

  ## Files written

  **test_helpers/** (9 files):
  - `types.py` — 13 entity TypedDicts + status/enum classes (all entities carry full common fields per PRD §2.5)
  - `api_client.py` — `ApiClient(GenericApiClient)` with one method per §4 endpoint; POST helpers auto-attach a fresh `Idempotency-Key` (overridable via `idem_key`, suppressible via `idem_key=False` for the missing-key test)
  - `api_errors.py` — all 27 error IDs + HTTP status map, registered with `set_error_http_status_map`
  - `assertions.py` — per-entity assertions plus outcome/pumpability invariant checkers
  - `factories.py`, `constants.py` (fee/cure/slump/pump/bond/weather/learning-curve constants), `test_users.py` (8 opaque roles + per-user builders for SoD tests), `fixtures.py` (clock/jurisdiction/plan/pour-cure/printer/batch/weather/permit/site-ready/printing-job/completion composites), `__init__.py` barrel

  **test_suite/** (9 files): `conftest.py` + `test_01` access/idempotency/OCC, `test_02` entities/listing, `test_03` permits & fees, `test_04` plans & revisions, `test_05` print-job scheduling gates, `test_06` print execution & interruption invariants, `test_07` inspections & posture, `test_08` printer/batch/suspend/trades.

  ## Test count
  **67 test functions.** Every one ends with exactly one `Design:` line that resolves to a real instance; all quoted docstring citations were mechanically verified to appear verbatim in `workspace/PRD.md`.

  ## §1.8 Difficulty queue — 15 of 18 translated (each with ≥2 tests), 3 skipped
  - `dual_variant_calc/learning_curve_forward_looking_vs_chronological` — SKIP: its asserted literals (baseline=480, factors 0.8333/1.0000) depend on 4 units completing at identical durations under mixed variants; no verbatim PRD sentence uniquely derives those specific numbers.
  - `priority_pair_validation_conflict/posture_blocked_beats_invalid_state_on_print_start` — SKIP: asserts a validation-priority outcome (posture beats state); the "Silence patterns" validation-priority rule forbids it absent an explicit PRD ordering statement for that exact pair.
  - `priority_pair_validation_conflict/invalid_state_beats_business_referential_on_permit_decide` — SKIP: same category (state vs referential priority pair).

  ## §1.9 Corner queue — 21 of 21 non-stub instances translated (each ≥1 test), 0 skipped; no stubs exist in the index.

Orchestrator verification: test_helpers/ (9 files) and test_suite/ (conftest + 8 test files) on disk; 67 test functions counted via grep; Design: tags present in every test file.

## Step 6: Generate Implementation — 2026-09-30T20:50:00.000Z

Subagent summary (verbatim):

  Server boots cleanly, envelope shape is correct, logical clock drives `created_at`/`updated_at`, and the process was killed by its own PID only.

  ## Summary

  Implementation written to `/home/ubuntu/github/CodingPRD/tasks/task_3310_site_additive_construction_printing_permitting/workspace/implementation/`:

  **Files written (11 source modules + launcher + deps)**
  - `start.sh` — guarded pip install (no-op once flask present), `exec python3 app.py`, bash -n clean
  - `requirements.txt` — flask>=3.0,<4.0
  - `app.py` — app factory, global before_request auth + idempotency, after_request idempotency recording, ApiError/404/405/Exception handlers
  - `db.py` — in-memory store (13 entity dicts + idempotency map), logical clock starting 2026-09-01T00:00:00Z, ISO-8601 UTC 3-fractional-digit formatting
  - `errors.py` — full error catalog with exact IDs and HTTP statuses
  - `response.py` — `meta`/`response_type`/`data` envelope; list pagination fields `limit`/`offset`/`total_count`/`has_more` in meta
  - `middleware.py` — X-User-Role auth (8 roles), role gating, Idempotency-Key presence/replay-consistency (409 on body mismatch, replay returns original response), pagination parsing (default 10, 1–100)
  - `validate.py` — typed field validators raising ERR_INVALID_REQUEST
  - `services.py` — all derived fields, posture derivation (6-rule priority), lazy AM-expiry/OVERRUN evaluation, permit fee, interruption close/penalty, learning curve (both variants), utilization, trade-task startable/blockers
  - `routes_core.py` — clock, jurisdictions, community deployments
  - `routes_sites.py` — site CRUD + lifecycle action (POUR_FOUNDATION/CONFIRM_CURE/COMPLETE/SUSPEND with cascades)
  - `routes_plans.py` — structural plans + revisions + actions (SUBMIT/APPROVE/REJECT, void cascade to permits) + archive
  - `routes_permits.py` — permit applications + actions (SUBMIT with AM rerouting, PAY_FEE, DECIDE, RESUBMIT, WITHDRAW)
  - `routes_equipment.py` — printer setups (create/advance/demobilize), material batches (create/qualify/reject), weather observations
  - `routes_print_jobs.py` — print-job create (overlap check) + transition (READY_TO_PRINT/PRINTING/PAUSED/COMPLETED/ABORTED/CANCELLED, interruption lifecycle, hard-cap auto-abort)
  - `routes_inspections.py` — layer inspections (record/list/disposition with SoD and outcome gates)
  - `routes_trades.py` — trade tasks (create with OCC, transitions with TOO_EARLY/OVERRUN/posture gates)

  **Verification**: `bash -n start.sh` passes; `python3 -m compileall` passes; app imports and boots on `$PORT`, responds 200 with the correct envelope under the logical clock; no seeding at startup.

  - **Endpoints implemented: 35** (all entries from the §1.5 endpoint table including clock, archive, demobilize, reject)
  - **State machines implemented: 10** (Site, StructuralPlan, PlanRevision, PermitApplication, PrinterSetup, MaterialBatch, PrintJob, PrintInterruption, LayerInspection, ConventionalTradeTask) with preconditions and cascading side effects
  - **Calculations implemented: 9** (permit fee with floor-then-multiply + resubmission markup half-up rounding; print window utilization dual-variant; learning-curve factor/baseline with median + rolling average and FORWARD_LOOKING/CHRONOLOGICAL variants; posture derivation; half-open schedule overlap; cure penalty ceil/10 with cause gating and mix-code max-interruption bounds {A:30,B:20,C:45} and 60-min hard cap; foundation cure 72h inclusive; pumping windows with inclusive bounds + 15mm slump tolerance; layer inspection outcome with 1.5 MPa / 6 mm inclusive thresholds)

  One note: the scaffold's endpoint table had a duplicated trailing fragment (repeated `roles:`/`input:` lines after the trade-task transition entry) which I treated as a YAML authoring artifact, not a second endpoint.

Orchestrator verification: 16 source files + start.sh on disk; `bash -n start.sh` passes; `python3 -m compileall` passes.

## Step 7: Run Tests and Iterate — 2026-09-30T21:10:00.000Z

Subagent summary (verbatim):

  ## Summary

  **Iterations run:** 3 sweeps (initial diagnostic + 2 fix-verification sweeps). Final sweep: all 8 parallel rounds passed 67/67.

  **Tests deleted:** none — every failing test traced to verbatim PRD prose and survived both STEP 1a (coverage) and 1b (unique derivability).

  **Fixes applied to `test_suite/`:**
  - `test_06_print_execution_and_inspection.py` — `test_cure_penalty_nested_ceil_and_conditional`: added `post_clear_weather(site_id, "2026-09-04T08:19:00Z")` after the pause (and exported import). PRD §3.7 requires "the latest weather observation to be print-permissible" for resume; the fixture's only observation (07:30) was 50 minutes stale at the 08:20 resume, so the implementation was correct to reject with `ERR_WEATHER_NOT_PERMISSIBLE`. Test bug, fixed to match the sibling test in the same file that already posted fresh weather.
  - `test_08_printer_batch_suspend_trades.py` — `test_trade_task_start_too_early_returns_trade_too_early`: changed the pre-start assertion from `READY` to `PLANNED` (with comment). PRD §3.10's `start_blockers` enum includes `TOO_EARLY`, so a too-early task is not fully dependency-satisfied and stays `PLANNED` — the fixture's clock (09:00) was before `earliest_start_at` (10:00). The post-attempt `READY` assertion (startable-except-time tasks are READY; PRD's too-early-start rejection implies reaching the temporal gate from READY) is unchanged.

  **Fixes applied to `test_helpers/`:** none.

  **Fixes applied to `implementation/`:**
  - `services.py` — `lazy_eval_site` / `lazy_eval_permit` now stamp `am_expired_from_status = "AM_REVIEW"` when the lazy deadline auto-transition fires, so the DECIDE temporal gate (PRD §2.11 item 7: `ERR_AM_REVIEW_EXPIRED` outranks item 8 `ERR_INVALID_STATE`) can still report the temporal error after the application has auto-moved to `RESUBMIT_REQUIRED`. Also: both `lazy_eval_site` and `lazy_eval_all` now call `reevaluate_trade_tasks` — clock advance past `earliest_start_at` is a dependency change (PRD §3.10: "transitions from PLANNED to READY automatically ... re-evaluated on every dependency change", and §2's deferred-evaluations list runs on clock advance).
  - `routes_permits.py` — `_decide`: added the priority-7 AM-deadline check before the priority-8 state check; a `RESUBMIT_REQUIRED` application flagged as expired-from-`AM_REVIEW` rejects APPROVE with `ERR_AM_REVIEW_EXPIRED` (DENY still lands on `ERR_INVALID_STATE`, which no test contradicts).
  - `routes_print_jobs.py` — `_resume`: moved the interruption-cure-window check (including the `intr is None` but an `OVERRUN` interruption exists case) before the priority-6 STOP-posture gate. PRD §3.7 states "any subsequent resume attempt is rejected with `ERR_INTERRUPTION_CURE_EXCEEDED`" once the OVERRUN flag is set — and since the OVERRUN flag is itself what drives posture to STOP, checking posture first would have masked the operative error. The posture gate still runs for STOP caused by other sources (suspension, DEMOLISH_REQUIRED, another job's overrun).

Orchestrator verification: results.1-8.json all written at 21:07, AFTER the last implementation edit (routes_print_jobs.py, 21:04:56) — the final sweep post-dates all fixes. All 8 rounds: passed 67/67, failed 0. Since Step 7 made implementation/ fixes, Step 8 is REQUIRED (not skipped).

## Step 8: Finalize PRD — 2026-09-30T21:20:00.000Z

Subagent summary (verbatim):

  All 5 edits applied; 4 lines changed in place (line count unchanged at 324). Done.

  **File:** `workspace/PRD_FINALIZED.md`

  **Line counts / delta:** PRD.md 324 lines, PRD_FINALIZED.md 324 lines (0% line-count delta; 4 lines revised in place, all edits inline per the "no new sections" rule).

  ### Changes

  - **§2.4 — revise** — added trade-task readiness re-evaluation (`is_startable`/`start_blockers` and the PLANNED→READY auto-transition) to the clock-set deferred-evaluation list — `implementation/services.py:167-184` (`lazy_eval_all` calls `reevaluate_trade_tasks` per site), `implementation/routes_core.py:20`.
  - **§2.11 item 13 — revise** — carved out the resume path from strict priority ordering: the job's own interruption-cure check is evaluated before the priority-6 posture gate (an OVERRUN interruption is itself what drives posture to STOP), while the posture gate still applies for STOP from other sources — `implementation/routes_print_jobs.py:272-303` (`_resume`).
  - **§3.7 — revise** — resume weather gate pinned to require the latest observation to be print-permissible *and* within its 30-minute validity window (§3.6) — `implementation/routes_print_jobs.py:304` via `_fresh_weather_ok` (`routes_print_jobs.py:133-138`).
  - **§3.10 — revise** (DECIDE) — pinned that an application auto-transitioned to `RESUBMIT_REQUIRED` by AM-deadline expiry still rejects `DECIDE`/`APPROVE` with `ERR_AM_REVIEW_EXPIRED` (temporal gate outranks state gate), while `DECIDE`/`DENY` on it gets `ERR_INVALID_STATE` — `implementation/routes_permits.py:175-182`, flag stamped in `implementation/services.py:138,162`.
  - **§3.10 — revise** (READY promotion) — pinned that PLANNED→READY depends only on the work-dependency conditions (print job COMPLETED with no PENDING failing inspections, prior trade COMPLETED); `TOO_EARLY`/`SITE_STOPPED` remain `start_blockers` enforced at start time and do not hold a task in PLANNED; clock advance counts as a dependency change — `implementation/services.py:375-397` (`reevaluate_trade_tasks` ignores clock/posture for promotion), `implementation/routes_trades.py:110-129` (start gates).

  ### Per-edit pre-edit search log

  1. **§2.4 clock-set list** — (a) subject: deferred evaluations triggered by clock-set. (b) enumerated: `services.py` `lazy_eval_all`/`lazy_eval_site`/`lazy_eval_permit` (lines 129-184), all lazy-eval call sites across routes; confirmed clock-set runs only `lazy_eval_all` and trade-task reevaluation was the one list member missing from the PRD. (c) wording added as a conjunctive list item matching the existing style.
  2. **§2.11 item 13** — (a) subject: ordering of `ERR_INTERRUPTION_CURE_EXCEEDED` vs `ERR_POSTURE_BLOCKED` on resume. (b) enumerated: `_resume` full body, `_to_printing` dispatcher, OVERRUN flagging in services.py, posture rule 3. (c) wording scoped explicitly to "on a resume attempt" and "the job's own interruption", preserving the posture gate for other STOP sources.
  3. **§3.7 resume weather** — (a) subject: weather gate on resume. (b) enumerated: `_resume`, `_fresh_weather_ok` and its other call sites, `services.latest_weather`. (c) appended "and still within its 30-minute validity window (§3.6)" to the resume sentence only.
  4. **§3.10 DECIDE after expiry** — (a) subject: DECIDE on an application that auto-moved to RESUBMIT_REQUIRED by AM-deadline expiry. (b) enumerated: `_decide` gate order, all `am_expired_from_status` references, `_resubmit`. (c) behavioral wording (no internal field name), distinguishes APPROVE vs DENY outcomes, cites §2.11 item 7 > item 8 priority.
  5. **§3.10 READY promotion** — (a) subject: which conditions drive PLANNED→READY and when reevaluation fires. (b) enumerated: `reevaluate_trade_tasks`, `trade_blockers`/`recompute_trade_task`, all call sites, task creation, start gating, and the Step-7-modified test. (c) widened "dependencies" to "work-dependency conditions" with explicit enumeration; stated clock advance triggers re-evaluation; added that TOO_EARLY/SITE_STOPPED do not block READY but still block start.

Orchestrator verification: PRD_FINALIZED.md on disk, 324 lines; diff vs PRD.md shows exactly the 5 described in-place revisions, no other changes.

## Step 9: Complete PRD — 2026-09-30T21:30:00.000Z

Subagent summary (verbatim):

  The output is complete. All edits applied cleanly with in-paragraph revisions only.

  **File sizes:** `PRD_FINALIZED.md` = 324 lines / 48,368 chars → `PRD_COMPLETED.md` = 327 lines / 54,432 chars (+3 lines, +6,064 chars; 22 edited paragraphs, all in-place inserts/revisions — no new sections).

  **Counts:** 22 ambiguity-pins, 1 mismatch-revision.

  **Changes (PRD section — insert/revise — kind — what — impl anchor):**

  - §2.1 — revise — mismatch — `X-User-ID` is tolerated when missing (PRD said both headers mandatory; impl enforces only `X-User-Role`) — middleware.py:27-36
  - §2.2 — insert — ambiguity — `has_more` = `offset + len(items) < total_count` — response.py:35
  - §2.3 — revise — ambiguity — invalid/out-of-range `limit`/`offset` (incl. offset min 0) → `ERR_INVALID_REQUEST` — middleware.py:88-107
  - §2.8 — insert — ambiguity — missing or non-integer `expected_site_version` → `ERR_INVALID_REQUEST` — routes_equipment.py:34-41
  - §2.11 item 3 — insert — ambiguity — idempotency body comparison is canonicalized JSON (key order/whitespace insignificant) — middleware.py:56-60
  - §2.11 item 5 — insert — ambiguity — per-verb role checks on action/transition endpoints run after body parse but before state/temporal/posture gates — routes_permits.py:109-114, routes_sites.py:80-83, routes_trades.py:110-112
  - §3.1 — insert — ambiguity — deployment create 404s on unknown jurisdiction/plan; no plan-status check at create — routes_core.py:75-78
  - §3.3 — insert — ambiguity — revision create sets plan's `current_revision_id`; bad `supersedes_revision_id` → `ERR_NOT_FOUND` — routes_plans.py:66-83
  - §3.3 — revise — ambiguity — plan returns to `DRAFT` on rejection only when still `UNDER_REVIEW` — routes_plans.py:165
  - §3.3 — insert — ambiguity — archival moves plan to `ARCHIVED`; DRAFT permits on archived plans blocked by the submit gate — routes_plans.py:191
  - §3.10 — insert — ambiguity — site COMPLETE from a non-`SITE_READY` state → `ERR_INVALID_STATE` — routes_sites.py:120-121
  - §3.4 — insert — ambiguity — zero `measured_level_deviation_mm` accepted — routes_equipment.py:57
  - §3.5 — insert — ambiguity — batch creation does not bump site version — routes_equipment.py:143-165
  - §3.6 — revise — ambiguity — `wind_speed_mps` non-negative input; weather list is newest-first (explicit §2.3 override) — routes_equipment.py:226-252
  - §3.7 — insert — ambiguity — job-create defers permit/printer/batch/weather gating to READY_TO_PRINT; enforces only existence + overlap; initial null fields — routes_print_jobs.py:76-116
  - §3.7 — insert — ambiguity — READY_TO_PRINT picks earliest-created QUALIFIED pumpable batch into `consumed_batch_id`, latest APPROVED permit governs, bad schedule window → `ERR_INVALID_REQUEST` — routes_print_jobs.py:198-220
  - §3.7 — insert — ambiguity — early job start → `ERR_INVALID_STATE`; start re-checks weather 30-min validity — routes_print_jobs.py:231-234
  - §3.7 — insert — ambiguity — pause mirrors `max_permissible_interruption_minutes` onto the job — routes_print_jobs.py:264
  - §3.7 — revise — ambiguity — resume: elapsed == bound still allowed; `duration_minutes` = floor(elapsed seconds/60); MATERIAL resume swaps to earliest QUALIFIED batch and exhausts the old one; cap-triggered auto-abort carries abort side effects — routes_print_jobs.py:291-324, services.py:208-219
  - §3.7 — revise — ambiguity — `continuous_run_minutes` whole-minute, floored at zero; completion stamps job `utilization` for deployment sites — routes_print_jobs.py:340-355
  - §3.8 — insert — ambiguity — recorder's `X-User-ID` persisted as `recorded_by_user_id`; inspection recording recomputes posture — routes_inspections.py:68-75
  - §3.8 — revise — ambiguity — re-inspection may supersede any prior inspection on the job; range must overlap (`ERR_INVALID_REQUEST`), cross-job id → `ERR_NOT_FOUND`; prior disposition untouched — routes_inspections.py:50-56
  - §3.9 — insert — ambiguity — baseline median rounded half-up to whole minutes; per-unit job = earliest-created completed job; utilization windows in whole minutes; `utilization` null for non-deployment jobs — services.py:260-284, 253-257, 317-338
  - §3.10 — insert — ambiguity — permit create 404s on unknown revision; initial `fee_due_cents` = 0; fee payment accepts positive `amount_cents` in any non-terminal status, `ERR_INVALID_STATE` on terminal — routes_permits.py:44-54, 162-168
  - §3.10 — insert — ambiguity — SUBMIT blocked under `STOP` posture (`ERR_POSTURE_BLOCKED`); resubmission past round cap → `ERR_INVALID_STATE` and lands back in `AM_REVIEW`; `granted_path` pinned by approval source status — routes_permits.py:136-138, 189-191, 200-208
  - §3.10 — insert — ambiguity — `sequence_rank` is informational only; trade dependency refs must be same-site (`ERR_NOT_FOUND`); start from non-startable `READY` → `ERR_INVALID_STATE` — routes_trades.py:50-64, 122-125
  - §4 — insert — ambiguity — added table rows for `POST /construction/structural-plans/{id}/archive` (PlatformAdmin), `.../printer-setups/{setup_id}/demobilize` (PrintOperator), `.../material-batches/{batch_id}/reject` (PrintOperator) — routes_plans.py:173, routes_equipment.py:121, routes_equipment.py:200

Orchestrator verification: PRD_COMPLETED.md on disk, 327 lines / 54,432 chars. Pipeline complete.
