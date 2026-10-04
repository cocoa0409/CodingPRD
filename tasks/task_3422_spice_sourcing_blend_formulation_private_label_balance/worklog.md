# Worklog — task_3422_spice_sourcing_blend_formulation_private_label_balance

Scenario: Spice Sourcing, Blend Formulation & Private Label Balance (McCormick) — difficulty instruction: "Generate task much harder than expert level!"

## Step 1: Create task directory — 2026-10-01T23:12:07.455Z

Pre-allocated directory verified: `tasks/task_3422_spice_sourcing_blend_formulation_private_label_balance/` with `workspace/` inside. No new index computed; no other task_* directory created. `./INSTRUCTION.md` present at project root.

## Step 2: Generate scaffold — 2026-10-02T00:16:30.000Z

Subagent returned (verbatim):

  All three artifacts are complete, lint-clean, and verified. Summary:

  ## Files
  - `/home/ubuntu/github/CodingPRD/tasks/task_3422_spice_sourcing_blend_formulation_private_label_balance/SCAFFOLD.yaml` — 1424 lines
  - `/home/ubuntu/github/CodingPRD/tasks/task_3422_spice_sourcing_blend_formulation_private_label_balance/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 886 lines
  - `/home/ubuntu/github/CodingPRD/tasks/task_3422_spice_sourcing_blend_formulation_private_label_balance/SCAFFOLD_CORNER_DESIGN.yaml` — 1268 lines

  ## Counts
  - Entities: 12 (incl. self-referential BlendFormula.supersedes_formula_id, append-only SafetyTest with `common_fields: false`)
  - Endpoints: 40 (at the cap; flat `/spice` collections + one `/_clock/set_current_utc` test-driving endpoint with pinned default `2026-09-01T00:00:00Z`)
  - State machines: 6 (RawLot cyclic quarantine/retest/release, BlendFormula supersede, BlendRun with compensating void, ProductionRun, FinishedBatch parallel dimensions commercial×quality, RecallCase)
  - Calculations: 8 (dual-variant blend selection COST_MIN/FIFO_AGE, dual-variant recall scope PROVISIONAL/FINAL, pinned per-allocation-then-sum rounding under an exact-decimal rule, weekly surge capacity pools, changeover matrix, shelf-life gate, agreement rollup)
  - Validations: 29 priority-ordered rows; Errors: 29 (all triggerable, all covered by design instances); Roles: 8 (segregation-of-duties model: test-posting analyst may not disposition the same lot); Concurrency: 1 OCC rule (`expected_line_version`, 412)
  - Difficulty instances (§1.8): 18 — all 9 rules × 2, with differentiation honored (different entity domains, different error-category pairs, different interval semantics, different conserved quantities)
  - Corner instances (§1.9): 52 rows across all 9 taxonomy sections — 45 active + 7 `excluded_because` stubs citing §1.8 instances

  ## Verification
  - (a) all three files parse as YAML; (b) SCAFFOLD.yaml has neither design key; (c)/(d) each design file has exactly its single top-level key; (e) every enum member, error id, named constant, threshold literal, role name, and contract token used in the design files greps present in SCAFFOLD.yaml (only false positives: prose words, fixture product codes, and the intentionally invalid `TURMERIC` negative test)
  - 70/70 instance names unique; all `grounds:` resolve; no forbidden concurrency vocabulary; all fixture dates reachable from the clock default
  - All fixture arithmetic was executed in Python before pinning (COST_MIN 39330 vs FIFO_AGE 43470; rounding-order 261 vs naive 260 under exact decimal — a binary-float implementation silently gets 259/260 wrong; residual boundary exactly +2.000%; shelf boundary 405 days = 2027-01-14)
  - Final lint verdict, verbatim:
  ```
    §1.5 endpoints declared:    40
    §1.1 entities declared:     12
    §1.8 instances scanned:     18
    §1.9 instances scanned:     45
    Calls scanned (§1.8+§1.9):  992
  VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  ```

  Notable mid-course fixes: normalized `{lotId}`→`{id}` path placeholders (lint check (f) matches sub-resources by literal `{id}`); quoted list-indexed JSONPath captures; converted flow-style `grounds` containing `[`/`:` to block style; removed the dead `organic_capable` line field; redefined the ACCEPT gate as latest-test-per-type so the quarantine→retest→release reversal path is actually reachable; and reworked the capacity-invariant instance to probe with reservations (runs must equal their blend's target kg, which would have masked `ERR_CAPACITY_EXCEEDED` behind `ERR_QUANTITY_MISMATCH`).

Orchestrator verification: all three files exist on disk, parse as YAML, SCAFFOLD.yaml contains neither design key, design files each carry their single top-level key (confirmed via python yaml.safe_load).

## Step 3: Copy shared files — 2026-10-02T00:19:20.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T00:38:00.000Z

Subagent returned (verbatim):

  PRD generation is complete and all three hard contracts pass. The one MISS in the spot-check was a grep-pattern artifact — the SafetyTest `updated_at`/`version` absence is stated verbatim at line 74.

  ## Summary

  **Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3422_spice_sourcing_blend_formulation_private_label_balance/workspace/PRD.md` — 287 lines, complete, ends with the final §5 row (`ERR_RECALL_SCOPE_INVALID` | 422). The two design-index files were never opened or referenced.

  **Section list:**
  - §1 Introduction (2 paragraphs, business-context angle)
  - §2 Global Specifications: 2.1 RBAC + identity semantics, 2.2 API Response Structure (verbatim block — diff-verified byte-identical), 2.3 Pagination, 2.4 Common Resource Properties (incl. SafetyTest exception), 2.5 The Logical Clock, 2.6 Decimal Arithmetic & Rounding, 2.7 OCC on Line Scheduling, 2.8 Request Evaluation Pipeline (all 29 validations in priority order), 2.9 Nested Resources, 2.10 Masked Supplier View, 2.11 Quantity & Capacity Invariants
  - §3 Business Logic: 3.1 Supplier Registration & Raw-Lot Receiving, 3.2 Laboratory Testing & Disposition, 3.3 Proprietary Blend Formulation, 3.4 Blend Run Sourcing & Costing, 3.5 Production Scheduling & Weekly Capacity, 3.6 Run Completion & Shipping Gate, 3.7 Recall Operations & Adulterant Cascade, 3.8 Private-Label Agreements & Capacity Reservations
  - §4 Endpoint Definitions (4-column table, all 40 endpoints)
  - §5 Error Code Catalogue (2-column table, all 29 errors)

  **Coverage (scaffold → PRD):** §1.1 entities → §2.4/§2.10 + §3.1–3.8 narratives; §1.2 state machines (28 transitions incl. cascade/auto transitions) → §3.2–3.7; §1.2.1 concurrency rule → §2.7 + §3.5; §1.3 calculations (all 8, both variant pairs) → §2.6 + §3.4–3.7; §1.4 validations (29, priority-ordered) → §2.8 + trigger-local prose in §3; §1.5 endpoints (40) → §4 table with side effects in §3; §1.6 errors (29) → §5 + in-prose triggers; §1.7 roles (8, identity translated per role) → §2.1; clock default 2026-09-01T00:00:00Z and all constants pinned as literals in prose.

  **Hard contract reports:**
  ```
  Field coverage check:
  - entities[].fields + endpoints input/query/path + allocation members + common fields:
    92 required, 92 present, 0 missing
  Status: PASS

  Rule coverage check:
  - validations[] with priority: 29 checked, 29 expressed (§2.8 ordered pipeline), 0 missing
  - concurrency_rules[] OCC: 1 checked, 1 expressed (expected_line_version + ERR_STALE_VERSION/412), 0 missing
  - state_machines[].transitions: 28 checked, 28 fully expressed, 0 missing
  - calculations[]: 8 checked, 8 fully expressed (incl. pinned cost-rollup order, floor exceptions), 0 missing
  - validations[] conditions: 29 matchable to error_id in prose, 0 missing
  - endpoints[].side_effects / applies_to: 40 checked, 40 expressed, 0 missing
  - entities[].fields[] structured content (defaults/initials/nulls): all placed, 0 missing
  - sibling-branch symmetry: COST_MIN/FIFO_AGE, PROVISIONAL/FINAL, 3 disposition actions, commit/void branches — equal density, 0 asymmetric
  Status: PASS

  Path purity check (§3 only):
  - backtick tokens scanned: 533
  - tokens starting with `/`: 0
  - bare HTTP-method tokens: 0
  - method+path combined tokens: 0
  Status: PASS
  ```

  Additional verifications: §2.2 diff-verified byte-identical to the canonical source; all 22 state enum strings present; all pinned constants (2.00/0.10/100000/12.0 action levels with boundary inclusivity, 40.0% cap, 3-decimal ROUND_HALF_UP with floor exceptions, 540-day shelf life, 75.0%/405-day ship boundary, 5 shifts, surge 1.25× weeks 44–52, 3.5% overhead, crop years 2000–2100, CMP- prefix, full enum sets) appear as concrete literals; 45/45 targeted rule markers confirmed in prose.

Orchestrator verification: PRD.md is 287 lines, tail shows the final error-catalogue row (not truncated), 79 ERR_ mentions.

## Step 5: Generate unit tests — 2026-10-02T01:05:00.000Z

Subagent returned (verbatim):

  Generation complete and fully verified. Summary:

  ## Files written (34 total, 5067 lines)

  **test_helpers/ (9 files, 1211 lines)** — frozen before any test was written:
  `constants.py` (65), `types.py` (309), `api_errors.py` (71, 29 errors registered via `set_error_http_status_map`), `api_client.py` (154, all 31 endpoints), `test_users.py` (46, incl. `make_supplier_rep_headers` for the entity-backed role), `factories.py` (133), `assertions.py` (157, incl. `assert_lot_mass_invariant`), `fixtures.py` (255, composite chains: accept-lot, active-formula, committed-blend, schedule-with-OCC-read, produced-batch), `__init__.py` (21).

  **test_suite/ (25 files, 3856 lines)**: `conftest.py` + `test_01`…`test_24` (48–182 lines each).

  ## Verification results

  **(a) Collection**: `pytest test_suite/ --collect-only -q` exits 0 — **81 tests collected**, no dangling imports.

  **(b) AST tag audit** (real `ast` parse of every test docstring):
  - Expected non-stub instances: **63** (queue A: 18 difficulty; queue B: 45 corner)
  - Emitted distinct `Design:` tags: **63** — exact set match (missing: none, extra: none)
  - Every queue-A instance has ≥2 tests (36 tests); every queue-B instance has ≥1 (45 tests); every test carries exactly one tag
  - 7 `excluded_because:` stubs correctly not translated; all 7 cross-references resolve to real difficulty instances (e.g. `lot_reject_moves_mass_to_waste` → `terminal_lot_test_state_beats_safety`)

  **(c) Forbidden patterns**: no `pytest.mark.skip`/`skipif`/`xfail` anywhere; no bare `status_code == 200` asserts (the five explicit `status_code` checks are 401/403/412 companions to `validate_error`); all 26 creation validations pass explicit `201`, all fixtures likewise (learned-lesson rule 5).

  **Skipped instances: none.** Every non-stub instance has verbatim PRD coverage and a uniquely-derivable outcome. Two judgment notes: (1) initial `version == 1` is asserted per the pre-computed YAML (PRD pins only the +1-per-mutation delta; the standard reading was kept rather than skipping 3 instances); (2) `produced_at`/`best_by_date` are asserted as date prefixes (`2026-09-01` / `2028-02-23`) because PRD pins three-fractional-digit rendering only for `created_at`/`updated_at` — the load-bearing claim (+540 days, clock default) is preserved. All date arithmetic was verified against the pinned clock (`2026-09-01T00:00:00Z`): ISO week 44 = 2026-10-26, best_by = +540d = 2028-02-23, ship boundary = exactly 405 days (75.0%).

Orchestrator verification: `pytest --collect-only -q` exits 0 with 81 tests collected; test_helpers/ has all 9 files; test_suite/ has conftest.py + test_01..test_24. Judgment notes (1) initial `version == 1` and (2) date-prefix assertions flagged as Step 7 watch items.

## Step 6: Generate implementation — 2026-10-02T01:35:00.000Z

Subagent returned (verbatim):

  All done. Final state is clean — 19 source files, no caches, no stray processes.

  ## Summary

  **Task:** task_3422_spice_sourcing_blend_formulation_private_label_balance — full Flask implementation in `/home/ubuntu/github/CodingPRD/tasks/task_3422_spice_sourcing_blend_formulation_private_label_balance/workspace/implementation/`.

  ### File list (1959 lines total)
  | File | Lines | Contents |
  |---|---|---|
  | `start.sh` | 10 | Guarded pip install (`python3 -c "import flask"` check), `exec python3 app.py`, foreground |
  | `requirements.txt` | 1 | flask>=2.3 |
  | `app.py` | 52 | App factory, ApiError/404/405/500 envelope handlers, 11 blueprint registrations, `0.0.0.0:$PORT` (default 10000) |
  | `state.py` | 34 | Empty in-memory store + logical clock at `2026-09-01T00:00:00Z`, monotonic seq |
  | `errors.py` | 9 | `ApiError(error_id, status, message)` |
  | `helpers.py` | 324 | Envelope (`meta`/`response_type`/`data`, error shape), `require_roles` (X-User-ID/X-User-Role, 401/403), body validator `F` (400), range/404/state shortcuts, pagination (`limit`/`offset`/`total_count`/`has_more`, defaults 10/1/100/0), Decimal (`q3` ROUND_HALF_UP, `floor3` ROUND_FLOOR, `round_cents`), ISO8601 3-fractional-digit timestamps |
  | `routes/clock.py` | 15 | `POST /_clock/set_current_utc` |
  | `routes/suppliers.py` | 22 | supplier create |
  | `routes/lots.py` | 259 | lot receive/get/list (SupplierRep 404-invisibility), tests (pinned thresholds 2.00/0.10/100000/12.0, auto-quarantine + adulterant cascade), disposition (terminal→ERR_LOT_TERMINAL, SoD 403, latest-per-type FAIL gate, required-suite gate, quarantine-release unwind, REJECT mass write-off) |
  | `routes/formulas.py` | 175 | formula create (supersede/revision/duplicate rules), lines with CMP-A/B/… assignment, masked SupplierRep view, activate with |sum−100.0|≤0.01 gate + ACTIVE→RETIRED cascade |
  | `routes/blend_runs.py` | 149 | create/get/list, commit (DRAFT + ACTIVE gates; persists nothing on pool/quantity failure; persists computed fields + version bump on OUT_OF_SPEC; atomic consume + DEPLETED on success), void (COMPLETED-run guard, quantity restore, DEPLETED→ACCEPTED) |
  | `routes/lines.py` | 38 | line create/get |
  | `routes/production_runs.py` | 204 | schedule in exact PRD §2.8 pipeline order (shape→range→existence→412 OCC→changeover 409→formula-active→blend-committed→window conflict→agreement 422s→quantity/formula match→capacity 409), complete (batch creation + agreement rollup), cancel |
  | `routes/batches.py` | 94 | get/list, ship (state→not-shippable→75.0% whole-day-floor gate), manual hold |
  | `routes/recalls.py` | 117 | create (exactly-one-suspect 422 after FK existence), initiate (scope freeze + CLEAR→QUALITY_HOLD), close (RECALLED/WITHDRAWN by brand_type) |
  | `routes/agreements.py` | 45 | agreement create/get |
  | `routes/reservations.py` | 67 | reservation create with per-intersected-week pool check, get/list |
  | `services/blend.py` | 102 | lot selection (cap = floor3(needed×40%), COST_MIN/FIFO_AGE orderings), weighted flavor/moisture, per-allocation-round→sum→3.5% overhead cost rollup |
  | `services/capacity.py` | 144 | ISO-week pools (5 shifts, 1.25× surge weeks 44–52, whole-kg floor), reservation intersection, predecessor + changeover-class computation |
  | `services/recall.py` | 99 | PROVISIONAL/FINAL scope, initiated-recall coverage, adulterant cascade + quarantine-release unwind |

  ### Verification results
  - **`py_compile`**: all 19 .py files pass; `bash -n start.sh` passes; start.sh reads `$PORT` (default 10000), binds `0.0.0.0`, runs foreground via `exec`.
  - **Routes**: all 40 scaffold endpoints registered (verified via `url_map`; the 41st entry is Flask's built-in `/static`).
  - **Smoke test** (dynamic port 40277, server PID killed after; ~70 assertions, all OK):
    - (a) `POST /spice/suppliers` → 201, envelope `{meta, response_type:"object", data}`, `version:1`, default `knowledge_tier:"MASKED_ONLY"`
    - (b) `GET /spice/lots/{id}` → 200; SupplierRep reading another supplier's lot → 404 `ERR_NOT_FOUND`
    - (c) `quantity_kg:-5` → 422 `ERR_VALIDATION`; bad enum → 400 `ERR_INVALID_REQUEST`; bad FK → 404; no headers → 401 `ERR_UNAUTHENTICATED`; wrong role → 403 `ERR_UNAUTHORIZED`
    - (d) `POST /_clock/set_current_utc` → 200, `current_utc` echoed
    - Deep chain: MICRO at 100000 → PASS, ADULTERANT_SCREEN at 2.00 → FAIL + auto-quarantine; SoD 403 `ERR_DISPOSITION_FORBIDDEN`; masked line view (spice_code/proportion null, CMP-A visible); blend commit → allocations [4.0, 4.0, 2.0] kg (40% floor cap), line costs [400,400,200], total 1035 (3.5% overhead after per-allocation rounding), `WITHIN_SPEC`, version 2; OCC retry → 412 `ERR_STALE_VERSION`; window overlap → 409 `ERR_LINE_WINDOW_CONFLICT`; complete → batch (genealogy 3 lots, unit_cost 1035, shelf_life 540, produced_at = logical clock); ship → `SHIPPED`.
  - **Literal grep**: every PRD-pinned constant confirmed in code — `2.00`, `0.10`, `100000`, `12.0`, defaults `2.0`/`10.0`, `100.0`/`0.01`, `40.0`, `540`, `75.0`, `3.5`, weeks `44`/`52`, `1.25`, `5` shifts, `2000`/`2100`, `"CMP-"`, `datetime(2026, 9, 1)`, plus enum/source literals (`MASKED_ONLY`, `HIGH_SEGREGATION`, `AUTO_QUARANTINE`, `PROVISIONAL`, `FULL_SANITATION`).

  ### Judgment calls worth noting
  - **Commit version bump**: PRD says "every commit attempt (success or persisted failure)" bumps version, while candidate-pool/insufficient failures "persist nothing" — I bump version only on success and OUT_OF_SPEC (persisted failure), not on aborts.
  - **created_at/updated_at**: logical clock + monotonic microsecond offset, so list ordering (`created_at` ASC) and "latest test per type" are deterministic even when the clock is frozen.
  - **No seeding**: store boots empty; all state arrives via API. No guards beyond the PRD's stated checks.

Orchestrator verification at Step 6→7 hand-off: `py_compile` passes over all impl .py files; `bash -n start.sh` OK; clock default `2026-09-01` pinned in state.py; SHELF_LIFE_DAYS=540 and 405-day boundary present in routes/batches.py; test_helpers/constants.py literals (2.00/0.10/100000/12.0/40.0/540/75.0/405/1.25/3.5/2026-09-01) all grep present in PRD.md — no dead scaffold-carried constants.

## Step 7: Run tests and iterate — 2026-10-02T01:52:00.000Z

Subagent returned (verbatim):

  Clean 8-round parallel sweep achieved: all 8 rounds 81/81 passed, zero failures, zero errors.

  ## Summary

  - **Iterations run**: 2 (first sweep: 3 stable failures in all 8 rounds; fixes applied; second sweep: clean 8/8 × 81/81).

  - **Tests deleted**: none. Every failing assertion traced to verbatim PRD prose with a uniquely-derivable outcome.

  - **Fixes applied to `test_suite/`** (test-layer bug, not `test_helpers/`):
    - `/home/ubuntu/github/CodingPRD/tasks/task_3422_spice_sourcing_blend_formulation_private_label_balance/test_suite/test_09_compensating_invariants.py` — added `create_committed_blend_run` to the `from test_helpers import (...)` list. The class `TestWeeklyPoolConservation._setup` called it (used identically by 10+ other test files) but the import was omitted, producing `NameError` in `test_reservation_blocked_while_run_holds_pool` and `test_cancel_restores_pool_exactly`.

  - **Fixes applied to `implementation/`**:
    - `/home/ubuntu/github/CodingPRD/tasks/task_3422_spice_sourcing_blend_formulation_private_label_balance/workspace/implementation/routes/lots.py` — `disposition()` ACCEPT branch: replaced the `was_quarantined = lot["status"] == "QUARANTINED"` gate with an unconditional `release_cascade(lot, touch)` (plus docstring correction). Root cause of `test_release_unwinds_hold_and_auto_closes_recall` failing with batch stuck at `QUALITY_HOLD`: PRD §3.2's zero-FAIL gate makes direct ACCEPT-from-QUARANTINED unreachable after an adulterant FAIL (latest ADULTERANT_SCREEN is FAIL → `ERR_LOT_HAS_FAILING_TEST`), and any retest moves the lot QUARANTINED→IN_TEST — so the retest→IN_TEST→ACCEPT path is the *only* reachable release path, and the scaffold's `lot_release` side effects (batch hold unwind, DRAFT AUTO_QUARANTINE auto-close) must fire there. `release_cascade` is artifact-keyed (batch holds with `quality_hold_lot_id == lot.id` and DRAFT cases naming the lot), so it is a strict no-op for never-quarantined or manually-quarantined lots, making the unconditional call safe. REJECT path still does not unwind, matching PRD's silence on reject-release.

  - **Watch-item disposition**: the flagged items (a) initial `version == 1`, (b) date-prefix assertions, and (c) version-bump-on-persisted-failure-only all passed in every round; no drift observed. The final passing sweep's `results.1.json`–`results.8.json` remain in `workspace/implementation/` per the output contract.

Orchestrator verification: all 8 `results.${i}.json` read — every round passed=81 total=81 failed=0 errors=0; `release_cascade(lot, touch)` confirmed at `workspace/implementation/routes/lots.py:256` (import line 20); no .py source file in implementation/, test_suite/, or test_helpers/ is newer than results.1.json — the clean sweep reflects current code. Step 8 NOT skipped (1 test_suite fix + 1 implementation fix).

## Step 8: Finalize PRD — 2026-10-02T02:10:00.000Z

Subagent returned (verbatim):

  All edits verified. The diff shows exactly 6 lines revised inline (74, 148, 168, 184, 196, 198), everything else byte-identical. Here is the summary.

  ## Summary

  **Line counts:** PRD.md 287 lines, PRD_FINALIZED.md 287 lines — 0% line-count delta; 6 lines revised inline (2.1% of lines touched), no sections added or removed.

  **Changes (one bullet each):**
  - §2.4 — revise — `version` now pinned to "starts at exactly 1 when the resource is created" plus the existing +1-per-mutation rule — `workspace/implementation/helpers.py:97` (`new_entity` sets `version = 1` for every entity; watch item a).
  - §3.2 — revise — the disposition pointer now reads "A successful accept additionally unwinds any outstanding adulterant-cascade artifacts naming the lot…keyed to the cascade's artifacts, not to the lot sitting in `QUARANTINED` at the moment of acceptance" — `workspace/implementation/routes/lots.py:256` (unconditional `release_cascade` call; the Step 7 fix).
  - §3.4 — revise — abort sentence now adds "not even a `version` increment, so the run's `version` moves only on a successful commit or on a persisted out-of-spec failure" — `workspace/implementation/routes/blend_runs.py:108,120` (`touch(run)` only on OUT_OF_SPEC and success; aborts raise inside `select_allocations` before any mutation; watch item c).
  - §3.6 — revise — added "both `produced_at` and `best_by_date` are rendered as ISO 8601 UTC timestamps with three fractional digits, in the same format as `created_at` and `updated_at`" — `workspace/implementation/helpers.py:61-64,116-117` (all datetimes render via `iso()`; watch item b).
  - §3.7 — revise — auto-close trigger reworded from "released from quarantine" to "released via a successful accept disposition" — `workspace/implementation/services/recall.py:93-99`.
  - §3.7 — revise — unwinding paragraph rewritten: fires on any successful accept (retest path is the only reachable one after an adulterant FAIL, since the zero-FAIL gate blocks direct accept and the passing retest moves the lot QUARANTINED→IN_TEST); unwind keyed to artifacts; explicit no-op for never/manually-quarantined lots; explicit "reject disposition never unwinds" — `workspace/implementation/routes/lots.py:247-264`, `workspace/implementation/services/recall.py:79-99`.

  **Per-edit pre-edit search log:**
  - Edit 1 (version=1): (a) subject = initial `version` value. (b) Enumerated: `helpers.py:91-99` (universal `version=1` in `new_entity`) + all 12 creation callsites (`suppliers.py:20`, `lots.py:68`, `formulas.py:58,124`, `lines.py:27`, `blend_runs.py:43`, `production_runs.py:101,169`, `recalls.py:38`, `agreements.py:26`, `reservations.py:40`, `services/recall.py:66`); safety tests (`lots.py:166-176`) build manually without version — already carved out by the PRD's exception sentence; `touch()` is the sole mutator. (c) No adjustment needed.
  - Edits 2/3/4 (release cascade): (a) subject = when the cascade unwind fires and what it keys on. (b) Enumerated: `lots.py:209-265` (ACCEPT calls `release_cascade` unconditionally; QUARANTINE/REJECT branches call nothing), `services/recall.py:79-99` (artifact-keyed: `quality_hold_cause=="LOT_QUARANTINE"` + `quality_hold_lot_id==lot.id` + INITIATED-coverage check; DRAFT AUTO_QUARANTINE suspect match), `services/recall.py:49-76` (artifact creation), `lots.py:178-192` (retest transition and adulterant re-quarantine), `recalls.py:80-117` (initiate/close — cause stays NONE on recall-driven holds, so never cleared by release), `batches.py:81-94` (manual hold — cause MANUAL, never touched), `production_runs.py:181` (batch born cause NONE), plus witness `test_13_cascade_release_and_dedupe.py`. (c) Adjustments: dropped the status-gated "accepts a QUARANTINED lot" phrasing entirely; added the artifact-keyed no-op clause (covers the unconditional call on manual-quarantine accepts) and the reject-never-unwinds clause (pins the REJECT branch's silence noted in the diff).
  - Edit 5 (timestamp rendering): (a) subject = wire format of `produced_at`/`best_by_date`. (b) Enumerated: `production_runs.py:164,176` (stored as datetimes), `helpers.py:61-64` (`iso()` 3-fractional), `helpers.py:113-118` (`json_safe` routes every datetime through `iso()`), `helpers.py:131-148` (all bodies serialized via `json_safe`), `batches.py:28-56` (batch reads). (c) Scoped to exactly the two named fields; deliberately made no claim about `window_start`/`window_end` echoes to keep the edit minimal.
  - Edit 6 (version on commit aborts): (a) subject = `version` mutation on candidate-pool/quantity aborts. (b) Enumerated: `blend_runs.py:86-121` (touch only at :108 and :120), `services/blend.py:31-102` (aborts raise before returning; no DB mutation; caller assigns fields only after return), and re-checked §2.7's parallel sentence ("persists a failure") which defers to §3.4 and stays consistent unedited. (c) No adjustment needed.

  **No-edit items:** the `test_09_compensating_invariants.py` import fix is a pure test-layer bug (missing `create_committed_blend_run` import) with no PRD implication — no edit made.

  File produced: `/home/ubuntu/github/CodingPRD/tasks/task_3422_spice_sourcing_blend_formulation_private_label_balance/workspace/PRD_FINALIZED.md`

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` shows exactly the 6 reported line revisions (74, 148, 168, 184, 196, 198 — 12 diff lines = 6 old + 6 new) and nothing else; post-sweep source check still clean (no .py newer than results.1.json).

## Step 9: Complete PRD — 2026-10-02T02:20:00.000Z

Subagent returned (verbatim):

  All verification gates pass. Final report.

  ## Summary

  **Source vs output**: `PRD_FINALIZED.md` (287 lines / 60,677 chars) → `PRD_COMPLETED.md` (287 lines / 62,935 chars), char delta **+2,258**. `diff -q` confirms the files differ (9 paragraphs revised in place; no sections added).

  **Counts**: 9 ambiguity-pins, 1 mismatch-revision (prose tightening accompanying the impl fix), 1 impl-bug-fix (sweep re-run: **8/8 rounds green, 81/81 tests passed each round**, fresh `results.1..8.json` left in `workspace/implementation/`).

  ### Implementation bug fix (1)
  - **§3.7 cascade unwind** — `workspace/implementation/services/recall.py:85-93` — `release_cascade` matched batches solely on `quality_hold_cause == LOT_QUARANTINE` + `quality_hold_lot_id`, with no `quality_status` check. Since `close` leaves the cause fields untouched, a reachable sequence (cascade hold → initiate → close → exonerating retest → accept) would resurrect a `RECALLED`/`WITHDRAWN` batch back to `CLEAR`, contradicting PRD §3.6/§3.7's clearly and twice-stated "RECALLED and WITHDRAWN are terminal". Fixed by adding `b["quality_status"] == "QUALITY_HOLD"` to the unwind condition ("held" = currently on hold). No test exercised the resurrection path; the full 8-round sweep stayed green after the fix.

  ### PRD pins (one bullet per change)
  - §2.6 — insert — ambiguity — kilogram inputs (`quantity_kg` on receiving/scheduling, `target_batch_kg` on blend-run creation) are rounded half-up to 3 decimals at intake and stored at that precision — `routes/lots.py:67`, `routes/blend_runs.py:46`, `routes/production_runs.py:89,106`.
  - §2.3 — insert — ambiguity — malformed pagination params (non-integer, `limit` out of 1..100, negative `offset`), non-integer `crop_year` filter, and out-of-set enum list filters are rejected `ERR_INVALID_REQUEST` (400) — `helpers.py:280-324`.
  - §2.8 step 4 — insert — ambiguity — the §3-level field ranges (`flavor_intensity_units`>0, `moisture_pct` 0..100, `cost_per_kg_cents`≥0, `target_flavor_units`>0, `min_lot_flavor_units`≥0, `supported_changeover_classes` non-empty and containing `NONE`) are enforced at the same step with `ERR_VALIDATION` (422) — `routes/lots.py:55-64`, `routes/formulas.py:42-43,114-117`, `routes/lines.py:21-26`.
  - §3.2 — insert — ambiguity — a status-preserving test post is not a lot mutation (no `version`/`updated_at` bump) — `routes/lots.py:178-191`.
  - §3.2 — insert — ambiguity — a failing `ADULTERANT_SCREEN` retest on a `QUARANTINED` lot composes both rules in one request: retest moves it to `IN_TEST`, the auto-quarantine rule then re-quarantines it and re-fires the cascade (dedupe per §3.7) — `routes/lots.py:182-189`; confirmed by `test_13_cascade_release_and_dedupe.py`.
  - §3.2 — revise — ambiguity — disposition `reason` is accepted but not persisted on the lot representation — `routes/lots.py:213-214`.
  - §3.6 — insert — ambiguity — completion responds HTTP 200 carrying the updated production run; the created batch is retrievable via the batch listing filtered by `production_run_id` — `routes/production_runs.py:191`, `test_helpers/fixtures.py:176-184`.
  - §3.6 — revise — ambiguity — hold `note` is accepted but not persisted on the batch representation — `routes/batches.py:84`.
  - §3.7 — insert — ambiguity — closing a case changes only quality status; `quality_hold_cause`/`quality_hold_lot_id` are left unchanged — `routes/recalls.py:111-116`.
  - §3.7 — revise — mismatch (PRD-internal: terminality vs. field-defined unwind set) — unwind prose tightened to "still held … sitting in `QUALITY_HOLD`", explicitly stating terminal batches stay put; accompanies the impl fix above.

  ### Dead-code check
  None. Every pipeline-step check (§2.8 steps 1-29) has a live call site; every invoked helper (`adulterant_cascade`, `release_cascade`, `compute_scope`, `batch_covered_by_initiated_recall`, `select_allocations`, `changeover_class`, `find_predecessor`, `free_kg`, `weeks_intersecting`) is defined and importable; every guard-read field (`affected_batch_ids`, `quality_hold_cause`, `quality_hold_lot_id`, line `version`) has upstream writers. Pipeline evaluation order was verified per-endpoint against §2.8 (including the documented step-8-over-7 terminal-guard override on test-post/disposition, and changeover(10) before formula-active(13) on scheduling).

Orchestrator verification: PRD_COMPLETED.md exists (287 lines / 62,935 chars) and `diff -q` vs PRD_FINALIZED.md confirms they differ; the impl edit (`services/recall.py`, mtime 02:09) predates the fresh sweep (`results.1.json` mtime 02:13); all 8 fresh rounds read: passed=81 total=81 failed=0 errors=0; the `b["quality_status"] == "QUALITY_HOLD"` guard confirmed at `services/recall.py:88`; no .py source file newer than the fresh results — the final sweep reflects the final code.
