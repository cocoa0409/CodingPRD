# Worklog — task_2788_supermarket_in_store_bakery_production_planning

## Step 1: Create task directory — 2026-09-04T21:23:31.832Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2788_supermarket_in_store_bakery_production_planning` and its `workspace/` subdirectory. Index 2788 was pre-assigned by the invoking pipeline; no index scan/allocation performed.

## Step 2: Generate scaffold — 2026-09-04T22:56:00.000Z

All three scaffold artifacts for task 2788 are complete and pass the lint.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2788_supermarket_in_store_bakery_production_planning/`):

| path | lines | size |
|---|---|---|
| `SCAFFOLD.yaml` | 2913 | 141 KB |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1744 | 119 KB |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3487 | 232 KB |

**SCAFFOLD.yaml counts** — `api_prefix: /bakery`, `difficulty_level: expert`, `entity_topology: flat`, `state_machine_shape: parallel`, `role_model: segregation_of_duties`, `consistency_model: immediate`:
- 10 entities, 50 endpoints, 8 state-machine blocks (6 entities), 2 concurrency rules (OCC on BakeDay and BakeryDepartment), 17 calculations (3 dual-variant), 49 validations (priority 1-49), 49 error codes, 5 roles.
- Top-level keys are exactly scenario / domain_name / api_prefix / complexity_profile / response_envelope / entities / state_machines / concurrency_rules / calculations / validations / endpoints / errors / roles — neither design key leaks into it.

**Design indices:**
- `scaffold_difficulty_design`: 9 rule_ids, 22 instances (dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2) — >=2 per rule.
- `scaffold_corner_design`: 78 instances across all nine guide sections — entities 11, state_machines 14, calculations 13, validations 11, endpoints 5, errors 12, rbac 6, complexity_layers 5, consistency_model 1. 52 carry full `test_recipe`s, 26 are `excluded_because` stubs (every cited `difficulty_instance` resolves by name in the §1.8 file, and no stub carries a recipe).

**Verification run:**
- `scaffold_lint.py`: 50 endpoints / 10 entities / 22 §1.8 instances / 52 §1.9 recipe instances / 791 calls scanned →
  `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`
- All three files parse as YAML; instance names are unique across the union of both design files (0 duplicates).
- All 49 declared error codes are exercised by at least one instance in the two design files (0 uncovered).
- Forbidden concurrency vocabulary appears nowhere in any of the three files.
- No sibling task directory was read, listed, or grepped at any point.

**Orchestrator post-step correction (known generator failure):** the scaffold generator had copied the difficulty directive line `Generate task harder than expert level!` into `SCAFFOLD.yaml`'s `scenario:` block, from where it would have reached PRD.md via the doc generator. The orchestrator stripped that single line from `SCAFFOLD.yaml` (scenario now begins at `2788. Supermarket ...`). A repo-wide grep for `harder than expert` over the task dir now returns nothing.

## Step 3: Copy shared files — 2026-09-04T22:57:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T23:14:00.000Z

PRD generation for task 2788 is complete.

**Output:** `workspace/PRD.md` — **433 lines**, last heading `## 5. Error Code Catalogue`, final line `| ERR_SHELF_LIFE_OVERSTOCK | 422 |` (a complete 49-row table; no truncation). Written as one front-section `Write` plus heredoc `cat >>` appends.

**Section headings, in order**
1. `# Supermarket In-Store Bakery Production API — Product Requirements Document`
2. `## 1. Introduction`
3. `## 2. Global Specifications & System-Wide Principles` — 2.1 RBAC; 2.2 API Response Structure; 2.3 Pagination; 2.4 Common Resource Properties; 2.5 Optimistic Concurrency on Planning and Purchasing Writes; 2.6 Money, Minutes and Ratios: Precision Discipline; 2.7 The Bake Day's Two Independent Gates; 2.8 Allergen Segregation and Shared-Equipment Labeling; 2.9 Segregation of Duties; 2.10 Rejection Precedence; 2.11 The Logical Clock
4. `## 3. Business Logic & Workflows` — 3.1 Provisioning a Department and Its Reference Data; 3.2 Opening a Bake Day and Building the Forecast; 3.3 Generating the Production Plan; 3.4 Scheduling a Batch by Hand; 3.5 Executing the Bake; 3.6 Shelf Life, Markdown, Waste and Shrink; 3.7 Custom Cakes: Pickup Windows, Quoting and the Decoration Loop; 3.8 Buying Ingredients: Case Packs, Freight and the Purchase Commitment; 3.9 Locking and Closing the Operating Day
5. `## 4. Endpoint Definitions` (50 rows, 4 columns)
6. `## 5. Error Code Catalogue` (49 rows, 2 columns)

**Contract 1 — Field-Name Coverage: PASS.** `entities[].fields` 116/116; `endpoints[].request_body` 71/71; `query_params` 24/24; nested object keys 10/10; `path_params` 10/10; roles 5/5; error ids 49/49. All state values across all 8 machines and all enum values present — one fix applied: `VOIDED` existed only inside the combined token `ACTIVE → VOIDED`, rewritten so it stands alone.

**Contract 2 — Rule Coverage: PASS.** All 49 validations represented, with §2.10 encoding the full priority order as 13 ordered bands and each rule's condition restated in the workflow it guards. Both `concurrency_rules` stated in §2.5 with OCC framing (`expected_bake_day_version` → `ERR_STALE_BAKE_DAY_VERSION` 412; `expected_department_version` → `ERR_STALE_DEPARTMENT_VERSION` 412) and no race/timing language. Every `side_effects` bullet on all 31 mutating endpoints is in prose, including the two big cascades (run completion: ingredient decrement → `replenishment_state` → `AUTO_REORDER` draft → department commitment → day rollups; day close: run cancellations with `DAY_CLOSED`, `DONATED`/`DAY_OLD_UNSOLD` sweep waste, cake orders → `EXPIRED` with reservation release, windows → `CLOSED`) and the waste void's three-hop reversal. All 17 calculations rendered with inputs, evaluation order, precision and every constant embedded in business context; all three dual-variant calculations distinguish their variants. Sibling-branch symmetry explicit.

**Contract 3 — §3 Path Purity: PASS.** 895 backtick tokens scanned between `## 3.` and `## 4.`: 0 path tokens, 0 bare HTTP-method tokens, 0 method+path tokens.

Also verified: §2.2 byte-identical to the canonical response-structure section; §4's 50 method+path pairs match the scaffold exactly; §5's 49 error ids and HTTP statuses match `errors[].http` exactly. Neither design yaml was opened, and no sibling `task_*/` directory was read.

**Orchestrator verification (anti-truncation guard):** independently re-ran `wc -l` (433), `tail -12` (ends on the complete final error-table row) and the heading scan; PRD.md terminates at a real section boundary. `grep -c "harder than expert" PRD.md` → 0, so the difficulty directive did not reach the PRD.

## Step 5: Generate unit tests — 2026-09-05T00:34:00.000Z

Test generation for task 2788 is complete. Everything is at the task root — nothing was written under `workspace/`, and `worklog.md` / `workspace/implementation/` were never touched.

### File inventory

`test_helpers/` (2478 lines): `__init__.py` 43, `api_client.py` 305, `api_errors.py` 112, `assertions.py` 311, `constants.py` 99, `factories.py` 481, `fixtures.py` 700, `test_users.py` 72, `types.py` 355.

`test_suite/` (4490 lines):
| file | lines | tests | A / B |
|---|---|---|---|
| `conftest.py` | 63 | — | — |
| `test_01_reference_data_provisioning.py` | 562 | 13 | 0 / 13 |
| `test_02_bake_day_forecast_and_plan.py` | 387 | 8 | 4 / 4 |
| `test_03_manual_run_scheduling.py` | 727 | 16 | 10 / 6 |
| `test_04_run_execution_and_labor.py` | 487 | 11 | 6 / 5 |
| `test_05_completion_cascade_and_purchasing.py` | 562 | 12 | 8 / 4 |
| `test_06_waste_shrink_and_markdown.py` | 599 | 14 | 8 / 6 |
| `test_07_custom_cake_orders.py` | 749 | 15 | 8 / 7 |
| `test_08_locking_closing_and_access.py` | 354 | 7 | 0 / 7 |

### Tests emitted: 96 (queue A 44, queue B 52)

### Design coverage (audited programmatically)
- Queue A: 22 rule instances, each translated by exactly 2 tests → 44. Zero A instances under-covered.
- Queue B: 78 instances, of which 26 carry `excluded_because:` (stubs, correctly not translated) and 52 are active. Each active instance has exactly 1 test → 52. Zero active B instances uncovered, zero tests tagged to a stub.
- Every test carries exactly one `Design:` line as the last docstring line, and every tag resolves to a real instance.

### SKIPPED design instances
**None.** All 22 queue-A and all 52 active queue-B instances passed the PRD-first two-condition filter. What was dropped were individual non-derivable *sub-assertions* inside otherwise-derivable instances, plus ten places where the design yaml contradicts the PRD and the PRD won:
- MIDDAY slot times recomputed (yaml arithmetic was wrong); auto-reorder draft `target_bake_day_id` is null; `day_of_week` is `"WED"` not `WEDNESDAY`; ingredient stays `REORDER_DUE` after an AUTO_REORDER draft; gate value is `MANAGER_ONLY`.
- `forecast_line_naming_a_product_of_another_department_...`: yaml asserts `ERR_PRODUCT_NOT_FOUND` for a foreign-department product, but PRD §3.2 says verbatim that case is `ERR_INGREDIENT_NOT_IN_DEPARTMENT` (422) and only an unknown id is `ERR_PRODUCT_NOT_FOUND` (404). The test asserts both paths per the PRD.
- Dropped `created_at == logical clock` from the pickup-slot identity test, the cross-department manager GET from the all-roles test, `proof_required` (no such run field), and any `created_by_user_id`/`updated_by_user_id` assertions — those fields do not exist in this PRD.

### Quality gates
`pyflakes` clean; `py_compile` of all 18 files clean; every `from test_helpers import (...)` name verified to resolve at runtime. Citation audit: all 96 docstrings contain a >=8-word PRD quote, every quoted string matched verbatim against PRD.md (7 fabricated/mis-punctuated quotes corrected); every asserted `ERR_*` named in that test's prose (7 gaps corrected). No `skip`/`xfail`, no occurrence of the word "scaffold", no duplicate test names, no string-typed money or quantity values.

Note for the sweep: `test_01`'s oven-maintenance test drives a run to `BAKING` and back, and `test_08` closes days, so those two files are the most sensitive to clock handling — if failures cluster there, check `expires_utc`/`status_reason` derivation before suspecting the tests.

## Step 6: Generate implementation — 2026-09-05T00:34:00.000Z

Implementation complete. All modules written, compiled, and smoke-tested from a fresh boot.

### File inventory (`workspace/implementation/`, 3658 lines total)
`app.py` 100, `errors.py` 124, `guards.py` 354, `response.py` 98, `serializers.py` 217, `store.py` 94, `util.py` 152, `start.sh` 10 (chmod +x), `requirements.txt` 1, `routes/__init__.py` 0, `routes/departments.py` 62, `routes/products.py` 153, `routes/ingredients.py` 83, `routes/ovens.py` 103, `routes/bake_days.py` 240, `routes/production_runs.py` 270, `routes/waste_records.py` 107, `routes/pickup_slots.py` 98, `routes/cake_orders.py` 265, `routes/ingredient_orders.py` 238, `routes/clock.py` 23, `services/__init__.py` 0, `services/calc.py` 274, `services/plan.py` 156, `services/rollups.py` 201, `services/runs.py` 174, `services/purchasing.py` 61.

### Endpoint count: 50 — exact match to PRD §4
Enumerated from `app.url_map` after boot: 49 under `/bakery` + `POST /_clock/set_current_utc`. Storage is in-memory dicts only (no `open()`, sqlite, json dump or /tmp anywhere); nothing is seeded — a fresh boot answers `GET /bakery/departments` with `[]` and the logical clock reads exactly `2026-08-01T00:00:00Z`.

### The two OCC gates
Both are mandatory integers parsed in band 5 (`as_int(..., minimum=0)`, so absent/malformed → `ERR_INVALID_REQUEST`), compared in band 6 — after shape, before any state precondition — and no other endpoint reads a version field.
- `routes/bake_days.py:156` — `POST /bakery/bake-days/{id}/generate-plan`: `expected_bake_day_version != day["version"]` → `ERR_STALE_BAKE_DAY_VERSION` (412), checked before the CLOSED/LOCKED plan-shaping guard.
- `routes/ingredient_orders.py:77` — `POST /bakery/ingredient-orders`: `expected_department_version != department["version"]` → `ERR_STALE_DEPARTMENT_VERSION` (412), after the band-4 existence sweep and line shape, before the referential and shelf-life-cap checks.
Because a rejected write rolls back the whole-store snapshot taken in `before_request`, a 412 leaves no partial cascade.

### Smoke test (three flows, high random port 26043, plus a fresh-boot check on 29526)
Planning/execution: department → ingredient → product → oven → bake day → forecast line → stale generate-plan (412) → good generate-plan (PLANNED, 144 planned units, 46.00 labor, `plan_unmet_unit_count` 6 from the rack-capacity floor) → run list (grid-aligned 04:00 proof / 05:00 bake / 05:25 end / 05:40 ready / 17:40 expiry) → lock → start-proof → start-bake → complete (ON_SHELF, basis 14c, final labor 40.00) → ingredient decremented.
Purchasing: stale order (412) → order (case pack 50, 120 required → 3 cases → 150 ordered → 1890c with 5% freight) → shelf-life cap boundary (1200 exactly pass, 1250 → 422) → submit → receive short (`RECEIVED_SHORT`, shortfall 50) → commitment released. Auto-reorder verified separately: a completion dropping on-hand to 93 against a reorder point of 100 minted one `AUTO_REORDER` draft with a 107-unit top-up line and moved the ingredient to `REORDER_DUE`.
Cakes/waste/close: pickup slot + overlap rejection (409); PREMIUM 3-tier rush cake quoted 21 units / 16950 subtotal / 1356 rush (8%) / 915 discount / 17391 total, lead 375 min, deadline 07:45; confirm → reserve 21 → start-decoration → revision → ready → pickup → slot released. Waste: SOD rejection (403) for the executing baker, attestation (5 x 3c = 15c), shrink ratio 0.1250 vs 0.0100 budget flipping `markdown_authorization` to MANAGER_ONLY, `ERR_MARKDOWN_WINDOW_NOT_OPEN` before the window then baker rejected / manager allowed, void reversal restoring 40 on-shelf, close sweep clearing the run and rejecting a later write with `ERR_BAKE_DAY_CLOSED`. Envelope, pagination meta, `req_`+20-char ids and 3-digit ISO timestamps all correct; 401/403/404 bands verified.

### Incident reported by the Step 6 subagent (orchestrator note)
During its final fresh-boot check the impl generator resolved the listening PID with `ss | tail -1` instead of filtering on its own port and killed **PID 2033466, which was listening on port 8899 and did not belong to it** — plausibly another concurrent pipeline's server. Its own servers (PIDs 744538, 753956) were killed by exact PID. No pattern-based kill was used. Nothing this orchestrator can restore; recorded here so a neighbouring pipeline's unexplained port-8899 death at ~2026-09-04T23:4x is attributable.

### Orchestrator verification
`test_helpers/` and `test_suite/` are at the task root (not under `workspace/`); `workspace/` holds only INSTRUCTION.md, PRD.md and implementation/. Test function count re-counted independently: 96 across 8 files.

## Step 7: Run tests and iterate — 2026-09-05T00:52:00.000Z

All 8 parallel rounds pass at 96/96.

**Iterations run:** 2 (sweep → 2 fixes → sweep).

**Tests deleted:** none. Both failures were STEP 2 test-vs-PRD consistency bugs (the asserted rules are verbatim in PRD and uniquely derivable), so both were fixed toward the PRD rather than removed.

**Fixes applied to `test_helpers/`:** none — the fixture/factory layer was already PRD-faithful (money and quantities emitted as JSON integers, `api_client.canonical_instant` already normalising ISO-8601 sub-second width, `make_department_manager_headers` already binding the manager's `X-User-ID` to the department id).

**Fixes applied to `implementation/`:** none. Neither failure traced to the implementation; in both cases the PRD-faithful server was correctly rejecting a request the test issued wrongly.

**Fixes applied to `test_suite/`:**
- `test_suite/test_01_reference_data_provisioning.py`, `test_a_new_pickup_window_mints_its_own_identity_and_opens_empty` (line 332): the request was issued with `REGIONAL_ADMIN` headers, but PRD §4 authorises `POST /bakery/pickup-slots` for `CakeDesk, DepartmentManager` only, so the server correctly answered `ERR_ROLE_NOT_PERMITTED` (403) instead of 201. Switched the identity to `CAKE_DESK`. Request-identity fix; the assertions (server-minted id, `slot_status` `OPEN`, `reserved_decoration_units` 0, `version` 1) are untouched.
- `test_suite/test_04_run_execution_and_labor.py`, `test_run_completion_effects_are_visible_in_the_same_response_and_next_read`: the test completed a `PAR_BAKED` run straight out of `SCHEDULED`, which PRD §3.5 explicitly forbids — "a `SCRATCH` or `PAR_BAKED` run still sitting in `SCHEDULED` is rejected with `ERR_INVALID_RUN_STATE`" — so the server correctly returned 409. Inserted the missing `drive_run_to_baking(run, "PAR_BAKED")` deck-load hop (PRD §3.5: "a `PAR_BAKED` run goes straight from `SCHEDULED`"), and updated the completion `version` assertion from 2 to 3 to account for that legitimate intervening mutation (PRD §2.4/§3.5: the `SCHEDULED → BAKING` transition "increments the run's `version` by 1"). Every cascade assertion — `final_labor_minutes` 27.00, `unit_cost_basis_cents` 8, day rollups 600 cents / 80 produced / 81 planned, flour down to 40 and `REORDER_DUE`, the single 2363-cent `AUTO_REORDER` draft and the matching `open_purchase_commitment_cents` — is preserved exactly.

**Final sweep evidence** (`workspace/implementation/results.{1..8}.json`, left in place): all eight rounds 96/96, 0 failed, 0 errors.

Note from the subagent: the first sweep's `sweep.log`-level grep suggested a third failing test, but the per-round `results.$i.json` files showed only the two above — the spliced shared-fd log misattributes `FAILED` tokens. Both real failures were fully deterministic (all 8 rounds, identical error bodies), so no flakiness or load-induced failure was present in either sweep.

**Orchestrator verification:** independently re-read all eight `results.$i.json` — each reports `passed=96 total=96 failed=0 errors=0`, all timestamped 2026-09-05T00:45. The files exist on disk; the clean-sweep claim is confirmed rather than taken on trust.

**Step 8 skip decision:** NOT skipped. Step 7 ran 2 iterations with 2 `test_suite/` fixes, so the zero-iteration skip condition does not hold. Step 8 will run with the above entry inlined as `<step_7_diff>`; note for that step that both diffs are request/precondition test bugs, so it may legitimately conclude that few or no PRD edits are warranted.

## Step 8: Finalize PRD — 2026-09-05T00:55:00.000Z

`workspace/PRD_FINALIZED.md` created. **Zero edits were warranted** — it is byte-identical to `PRD.md` (both 433 lines, 0.0% delta).

### Changes
None. Both `<step_7_diff>` items were test-side request/precondition bugs against behavior the PRD already determines verbatim in prose *and* in the §4 table, and the implementation exhibits exactly that behavior.

### Per-item pre-edit search log

**Item 1 — pickup-slot creation authorisation (test_01 line 332, REGIONAL_ADMIN → CAKE_DESK)**
- (a) Subject: which roles may `POST /bakery/pickup-slots`, plus the birth state of a new window (`slot_status`, `reserved_decoration_units`, `version`).
- (b) Enumerated/read: `routes/pickup_slots.py` (all 99 lines — `create_pickup_slot` line 29 `authenticate(("CakeDesk", "DepartmentManager"))`, `close_pickup_slot` line 86 same tuple, both read endpoints on `ANY_ROLE`); `response.py` (`mark_new`/`touch` ledger, lines 60-74) for the `version == 1` claim; `services/rollups.py` `recompute_slot`/`reserved_excluding` (lines 131-149) as the parallel paths that later move `reserved_decoration_units`; `test_suite/test_01_...py` lines 311-343.
- Finding: PRD §3.7 prose already pins it — "Either a `CakeDesk` operator or a `DepartmentManager` opens a window on a bake day…" — and the §4 row agrees; §2.1 grants `RegionalAdmin` only reference-data provisioning and the clock. Birth state (`OPEN`, `0`) is verbatim in §3.7; `version` starting at 1 is §2.4.
- (c) No wording adjustment — no edit committed.

**Item 2 — PAR_BAKED deck-load hop and the run `version` sequence (test_04 completion cascade)**
- (a) Subject: (i) `PAR_BAKED` entering `BAKING` straight from `SCHEDULED`, (ii) rejection of a `SCRATCH`/`PAR_BAKED` completion attempted from `SCHEDULED`, (iii) the run's `version` advancing by exactly 1 on `SCHEDULED → BAKING`.
- (b) Enumerated/read: `routes/production_runs.py` (`start_proof` 177-193, `start_bake` 196-220, `complete` 223-241, `markdown` 244-270, `guard_execution_day` 36-41 — every run-mutating endpoint); `services/runs.py` (`create_run`, `cancel_run`, `complete_run`, `recompute_run_shelf`, `attest_waste` — every other writer of a run row); `services/rollups.py` (`recompute_labels` 109-121, `recompute_bake_day` 34-89 — the two cascades that could double-bump); `response.py` (`touch` ledger, one bump per row per request); `services/calc.py` (`final_labor_minutes`/`deck_predecessor`/`changeover_allowance`/`unit_cost_basis_cents`/`cost_order_line`/`auto_reorder_topup`).
- Finding: all three verbatim and uniquely derivable in PRD §3.5 — "a `PAR_BAKED` run goes straight from `SCHEDULED`", "a `SCRATCH` or `PAR_BAKED` run still sitting in `SCHEDULED` is rejected with `ERR_INVALID_RUN_STATE`", "each of these transitions increments the run's `version` by 1" — and §2.4 already forbids the label-refresh cascade from bumping the same row twice. Every cascade figure the test asserts traces to existing §3.5/§3.6/§3.8 prose with no impl-side choice left open.
- (c) No wording adjustment — no edit committed.

### Key finding
Consistent with the diff's own note (zero `implementation/` fixes, zero `test_helpers/` fixes, zero deletions), Step 7 surfaced no PRD silence and no PRD/impl divergence — only two tests that had drifted from prose the PRD states explicitly.

**Orchestrator note:** a byte-identical `PRD_FINALIZED.md` is the legitimate outcome when Step 7 applied zero `implementation/` fixes, which is the case here (verified: `md5sum` of PRD.md and PRD_FINALIZED.md match). Step 9, by contrast, must not be identical — it runs a full impl-vs-PRD scan and will be executed as three sequential module-partitioned passes over one shared `PRD_COMPLETED.md`.

## Step 9: Complete PRD — 2026-09-05T01:25:00.000Z

Run as **three sequential module-partitioned passes** over one shared `workspace/PRD_COMPLETED.md` (pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from copying so they could not destroy earlier work). Source `PRD_FINALIZED.md` 433 lines / 94,975 chars → `PRD_COMPLETED.md` 433 lines / 110,184 chars (**+15,209 chars, 0 lines**; all edits in-paragraph, no new/renumbered sections, §4's 50 endpoint rows and §5's 49 error rows untouched). **52 changes total: 43 ambiguity-pins, 9 mismatch-revisions.**

### Pass 1 — core + reference data (app, errors, guards, response, serializers, store, util, routes/{departments,products,ingredients,ovens,clock}) — 18 changes (16 ambiguity, 2 mismatch)
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase alphanumerics; `api_request_timestamp` from the host wall clock, not the logical clock — response.py:14-18, util.py:151
- §2.3 — revise — ambiguity — non-integer `limit`/`offset` → `ERR_INVALID_REQUEST`; empty-string value treated as omitted — response.py:77-98
- §2.3 — revise — ambiguity — `created_at` ties broken by server write sequence; filters matched literally, empty-string filter = absent, out-of-set enum and non-`true/false/1/0` boolean filters rejected, filter naming a nonexistent id yields an empty page not 404 — store.py:92-94, guards.py:336-354, routes/products.py:144-152
- §2.4 — revise — ambiguity — undeclared / server-derived body properties are ignored, not rejected — guards.py:177-189
- §2.4 — revise — ambiguity — `created_at`/`updated_at` are wall-clock, not logical-clock, stamps — store.py:79-80, response.py:66-74
- §2.6 — revise — ambiguity — ratios/labor emitted as JSON numbers never strings; numeric string inputs rejected; integer fields accept only fraction-free numbers; booleans never numeric; over-precise rates rounded half up rather than rejected — guards.py:217-261, util.py:43-68, routes/departments.py:34-36
- §2.10 band 3 — revise — **mismatch** — a path-named target's existence resolves *before* the scope check, so a nonexistent path id yields its own 404 ahead of `ERR_DEPARTMENT_SCOPE_VIOLATION` — routes/ovens.py:86-88
- §2.10 band 5 — revise — ambiguity — absent/empty body read as `{}`; unparseable/non-object body → `ERR_INVALID_REQUEST`; unknown route → `ERR_INVALID_REQUEST` at HTTP 404, undeclared method → HTTP 405 (both diverge from the §5 table's 400) — guards.py:177-189, app.py:66-79
- §2.10 — revise — ambiguity — rejections are atomic; rows already created/modified in the request are rolled back — app.py:49-58, store.py:54-72
- §2.11 — revise — ambiguity — `to_iso8601` required, clock may move backwards, call answers 200 with `data.current_utc` — routes/clock.py:17-23
- §2.11 — revise — ambiguity — accepted instants may carry any offset and are normalised to UTC, offsetless read as UTC; `business_date` exactly `YYYY-MM-DD`; emitted instants carry exactly 3 fractional digits, finer precision truncated not rounded — util.py:79-121
- §3.1 — revise — ambiguity — duplicate `store_number` → `ERR_DUPLICATE_SKU` — routes/departments.py:27-29
- §3.1 — revise — ambiguity — product `allergen_tags` defaults `[]`, stored as supplied (order preserved, repeats not collapsed); `allergen_free_claim` defaults false — routes/products.py:70-71, guards.py:308-319
- §3.1 — revise — ambiguity — recipe `units_per_rack` required non-negative integer; duplicate `ingredient_id` in `recipe_lines` → `ERR_INVALID_REQUEST` — routes/products.py:86-94
- §3.1 — revise — ambiguity — duplicate ingredient `name` in a department → `ERR_DUPLICATE_SKU` — routes/ingredients.py:42-44
- §3.1 — revise — ambiguity — ingredient `allergen_tags` defaults `[]` — guards.py:308-311
- §3.1 — revise — ambiguity — `oven_status`/`status_reason` are not creation inputs; a new oven is always `AVAILABLE` with null reason — routes/ovens.py:51-52
- §3.1 — revise — **mismatch** — a status write whose desired `oven_status` equals the current one → `ERR_INVALID_RUN_STATE`; `status_reason` capped at 500 chars and omitting it clears the previous note — routes/ovens.py:91-94

Pass 1 also confirmed `errors.py` matches §5 exactly (49 codes, same statuses) and the registered routes match §4 exactly.

### Pass 2 — bake days / runs / waste (routes/{bake_days,production_runs,waste_records}, services/{plan,runs,rollups}) — 20 changes (17 ambiguity, 3 mismatch)
- §2.5 — insert — ambiguity — `expected_bake_day_version` must be a non-negative JSON integer; absent/non-integer/negative → `ERR_INVALID_REQUEST` at band 5, before the comparison — routes/bake_days.py:156
- §2.7 — revise — **mismatch** — the markdown gate is re-evaluated only on a recomputation that actually moves `shrink_cost_basis_pct`; an explicitly-opened `MANAGER_ONLY` survives rollups leaving the ratio unchanged — services/rollups.py:71,80-85
- §3.2 — insert — ambiguity — a newly opened day's twelve derived figures all read zero — routes/bake_days.py:83-93
- §3.2 — insert — ambiguity — a recomputation writes only moved rollups and bumps `version`/`updated_at` only when at least one moved — services/rollups.py:70-88
- §3.3 — insert — ambiguity — an `ERR_EMPTY_PRODUCTION_PLAN` rejection rolls the supersede pass back; prior plan-generated runs stay `SCHEDULED` at their old `version` — services/plan.py:149-150, store.py:61
- §3.3 — insert — ambiguity — runs created earlier in the same pass occupy their decks against later forecast lines in the collision test — services/plan.py:62,142
- §3.4 — insert — ambiguity — a wrong oven/method pairing suspends the method-conditional field rules: answer is `ERR_OVEN_METHOD_MISMATCH` (band 12), never `ERR_INVALID_REQUEST`; higher bands still outrank it and temporal checks are skipped — routes/production_runs.py:66,83-86,102,124-125
- §3.4 — insert — ambiguity — an oven-consistent request breaking the `deck_index`/`proof_start_utc`/`bake_start_utc` rules → `ERR_INVALID_REQUEST` — routes/production_runs.py:72-82
- §3.4 — insert — ambiguity — deck collision spans bake days (absolute-instant comparison, no `bake_day_id` filter) — services/calc.py:158-180
- §3.4 — insert — ambiguity — pre-completion run shape: seven execution fields null, `wasted_units_total` 0, `shared_equipment_label_tags` an array — services/runs.py:44-52
- §3.5 — revise — **mismatch** — recipe consumption is driven by `rack_count` not yield (a zero-yield completion consumes fully), is not floored at zero (negative `on_hand_units` possible), and bumps every named ingredient's `version` even on a 0-per-rack line — services/runs.py:94-102
- §3.5 — revise — **mismatch** — reorder candidacy is at-or-below the reorder point while the state boundary is strictly below, so an ingredient landing exactly on its point gets a top-up line while reading `OK`; state re-derived only for a candidate currently `OK`; a candidate already covered by a DRAFT/SUBMITTED order is skipped untouched — services/runs.py:106-114, rollups.py:190-194
- §3.5 — insert — ambiguity — at most one auto draft per completion (one line per candidate, `recipe_lines` order); none minted when nothing is eligible and the department is then untouched; when minted the department bumps even at a zero-cent total — services/purchasing.py:50-61, rollups.py:159-171
- §3.6 — insert — ambiguity — a second markdown of a `MARKED_DOWN` run → `ERR_INVALID_RUN_STATE`, and that state check outranks the expiry check — routes/production_runs.py:254-260
- §3.6 — insert — ambiguity — the reason grouping is descriptive only (all five attestable by hand, all roll up identically); attestation accepted in any posture but `CLOSED` — routes/waste_records.py:37-41
- §3.6 — insert — ambiguity — `void_reason` is 1–500 non-blank characters; the voiding manager need not be the attestor and §2.9 does not apply — routes/waste_records.py:90
- §3.9 — insert — ambiguity — locking out of `DRAFT` or `LOCKED` → `ERR_INVALID_RUN_STATE`, checked before the plan's content; lock takes no body — routes/bake_days.py:170-176
- §3.9 — insert — ambiguity — closing a `DRAFT`/`PLANNED` day → `ERR_INVALID_RUN_STATE`; an already-closed day → `ERR_BAKE_DAY_CLOSED` — routes/bake_days.py:191-193
- §3.9 — insert — ambiguity — the day-old sweep is exempt from segregation of duties — routes/bake_days.py:211, services/runs.py:152
- §3.9 — insert — ambiguity — `INTAKE`/`PICKED_UP`/`EXPIRED` cake orders survive the close; an already-`CLOSED` window is not rewritten; a window that both releases capacity and closes advances `version` by exactly 1 — routes/bake_days.py:219-235, response.py:66-74

### Pass 3 — cakes / purchasing / calculations (routes/{pickup_slots,cake_orders,ingredient_orders}, services/{calc,purchasing}) — 14 changes (10 ambiguity, 4 mismatch)
- §2.5 — insert — ambiguity — `expected_department_version` must be a non-negative JSON integer; absent/non-integer/negative → `ERR_INVALID_REQUEST` before the comparison — routes/ingredient_orders.py:62
- §2.10 band 5 — revise — **mismatch** — band 5 said `required_units` need only be non-negative; impl requires >= 1 — routes/ingredient_orders.py:70
- §3.7 (windows) — revise — **mismatch** — "rejects four operations" → five: closing an already-`CLOSED` window is also `ERR_PICKUP_SLOT_CLOSED`, while `ready` and `pickup` are explicitly exempt — routes/pickup_slots.py:93, routes/cake_orders.py:239,256
- §3.7 (intake) — insert — ambiguity — the wrong-day window 404 fires in the existence band before any body field; `customer_name` may not be blank; base product must share the day's department (`ERR_INGREDIENT_NOT_IN_DEPARTMENT`) and that test precedes the `is_custom_cake_base` test; the full quote, lead minutes and deadline are computed at intake and returned on the 201 while intake reserves no capacity — routes/cake_orders.py:72-87,111
- §3.7 (revision) — insert — ambiguity — the re-quote reads the order's original `rush_requested` / `allergen_free_required`, neither being revisable — routes/cake_orders.py:224
- §3.7 (revision) — revise — **mismatch** — PRD claimed the window's `version` always increments; impl only writes when the reserved total actually moves — services/rollups.py recompute_slot
- §3.8 (create) — insert — ambiguity — `target_bake_day_id` is existence-checked only: any `plan_posture` (incl. `LOCKED`/`CLOSED`) and even another department's day is accepted — routes/ingredient_orders.py:56-57
- §3.8 (create) — revise — **mismatch** — the three line tests are not sequential: existence (band 4, array order) → duplicate as `ERR_INVALID_REQUEST` (band 5) → department (band 12, after the OCC gate); a non-string `ingredient_id` is an existence failure while an omitted key is a shape failure; `required_units` >= 1; an empty `lines` array is accepted at creation with `order_total_cents` 0 — routes/ingredient_orders.py:34-92
- §3.8 (create) — insert — ambiguity — a new manual order's full opening field set (null `submitted_at_utc`, empty `received_lines`, `shortfall_units_total` 0, null `cancel_reason`) — services/purchasing.py:33-44
- §3.8 (auto drafts) — insert — ambiguity — each auto line's `required_units` is the top-up quantity; the shelf-life cap is **not** applied to automatic drafts; same opening field set as a manual order — services/purchasing.py:50-57 vs routes/ingredient_orders.py:89-92
- §3.8 (submit) — insert — ambiguity — empty `lines` → `ERR_INVALID_REQUEST` but the `DRAFT` precondition is taken first; ingredients moved to `ON_ORDER` advance `version` by 1 while one already `ON_ORDER` is untouched; the department's `version` does not advance — routes/ingredient_orders.py:134-154, services/rollups.py recompute_commitment
- §3.8 (receipt) — insert — ambiguity — `received_units` is a non-negative integer, uncapped by `ordered_units`; a duplicated `ingredient_id` is not rejected — stored `received_lines` echoes every entry, last value wins for stock and shortfall — routes/ingredient_orders.py:177-181
- §3.8 (receipt) — insert — ambiguity — every line's ingredient advances `version` by exactly 1 even when `received_units` is 0 and the state does not move — routes/ingredient_orders.py:199-201
- §3.8 (cancel) — insert — ambiguity — `cancel_reason` is 1–500 non-blank characters; cancellation writes nothing else to the ingredient, so one already on the derived state does not advance its `version` (contrast with receipt) — routes/ingredient_orders.py:220,233-237

### Orchestrator verification
- `PRD_COMPLETED.md` md5 `f5ad3369…` differs from `PRD_FINALIZED.md`/`PRD.md` md5 `bbeafa75…` — the scan genuinely ran (46 changed lines, 92 diff hunks lines). A byte-identical Step 9 output would have meant the scan never happened.
- Line count still 433; file still ends on the complete final error-table row `| ERR_SHELF_LIFE_OVERSTOCK | 422 |`; §4 still 50 rows, §5 still 49 rows.
- `find implementation -newer results.1.json` returns nothing, so Steps 8 and 9 changed no implementation file — the 8×96/96 passing sweep still describes the shipped code exactly.
- Cleaned stray `__pycache__`/`*.pyc` left by the sweep. `results.{1..8}.json` retained under `workspace/implementation/`.

**Pipeline complete through Step 9.**
