# Worklog — task_2823_grain_bin_agricultural_steel_structure_manufacturing

## Step 1: Create task directory — 2026-09-05T02:44:00.000Z

Created `tasks/task_2823_grain_bin_agricultural_steel_structure_manufacturing/` and `.../workspace/` using the pre-assigned path from the orchestration prompt (index fixed by scenario number 2823; no auto-allocation scan performed, per instruction, to avoid collision with the ~32 concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-05T04:55:00.000Z

Subagent summary (verbatim):

All three scaffold artifacts are complete and lint-clean.

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2823_grain_bin_agricultural_steel_structure_manufacturing/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2823_grain_bin_agricultural_steel_structure_manufacturing/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2823_grain_bin_agricultural_steel_structure_manufacturing/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    62
  §1.1 entities declared:     15
  §1.8 instances scanned:     19
  §1.9 instances scanned:     50
  Calls scanned (§1.8+§1.9):  1052

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Files

| File | Lines | Bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 2897 | 141764 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2014 | 148616 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4716 | 359556 |

## Contents

**SCAFFOLD.yaml (§1.0–§1.7)** — 15 entities, 10 state machines, 62 endpoints, 12 calculations, 35 ordered validations, 56 errors, 7 roles, 2 OCC concurrency rules. `complexity_profile`: difficulty expert, archetypes compliance_audit_workflow + quota_allocation_workflow, layers `[cascading_side_effects, dual_variant_calculation, optimistic_concurrency, rate_threshold_triggers, derived_field_reconciliation, pagination_with_filtering]`, cyclic state machines, segregation_of_duties roles, immediate consistency. Neither design key is present.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)** — all 9 §0.5 rules, 19 instances (`combinatorial_formula` has 3, the rest 2 each), every one with a full structured `test_recipe`.

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9)** — 76 instances across all 9 claim-extraction sections: 50 real recipes + 26 `excluded_because` stubs (entities 11/0, state_machines 7/6, calculations 8/9, validations 12/7, endpoints 3/1, errors 2/0, rbac 3/0, complexity_layers 3/3, consistency_model 1/0).

## Scenario coverage

Every dimension of the scenario is load-bearing: bin sizing/structural design by grain type with Janssen lateral pressure, moisture surcharge and wind-vs-seismic governing-case selection; ASD vs LRFD as the dual-variant axis (allowable 90.0 vs 101.25 on identical geometry); roll-forming runs against coil lots with coating changeover buffers, line gauge limits and a conserved coil ledger; kit configuration (sidewall sheets, stiffeners, roof panels, anchor bolts, bolt packs, fans, unload system) with per-course bolt-pack rounding; dealer order processing with seasonal uplift, program tier, deposit and a credit ledger with a two-way CREDIT_HOLD cascade; aeration/drying/unloading capacity with depth and moisture penalties, fan-bank saturation and unload rate by system; engineering seal + permit review gating confirmation only in seal-required jurisdictions, with segregation of duties between author, sealer and second reviewer; high-cube freight with WEIGHT/CUBE proration, minimum cube utilization, rounding-residual absorption and dealer yard staging slots over closed windows; crew certification tiers by bin diameter plus expiry against the logical clock; and field-failure investigation whose root-cause determination drives the four-hop recall cascade (design RECALLED -> order HOLD_ENGINEERING -> load detach -> load CANCELLED).

## Verification performed

- `scaffold_lint.py`: clean (all six checks).
- Manual `grounds:` cross-reference (the lint does not validate `grounds:`): all 95 instance names checked, zero unresolved references.
- Stub contract: every `excluded_because.difficulty_instance` resolves to a real §1.8 `<rule_id> / <instance_name>` pair; no stub carries a `test_recipe`; all 95 names unique across both design files.
- No difficulty-directive leak ("harder than expert" appears nowhere in the artifacts).
- All formula-derived asserts are pre-computed literals verified against a task-scoped reference implementation at `/tmp/task2823/calc.py`.

Orchestrator verification: all three files present; `grep -ni "harder than\|expert level"` over all three returns nothing (no difficulty-directive leak); SCAFFOLD.yaml `scenario:` key holds the scenario text only.

## Step 3: Copy shared files — 2026-09-05T04:55:30.000Z

Copied `INSTRUCTION.md` into `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-05T05:10:00.000Z

Subagent summary (verbatim):

PRD generated at `workspace/PRD.md`.

**Size:** 454 lines. Written in 8 chunked heredoc appends; the document ends cleanly at the final row of the §5 error table (`ERR_DEPOSIT_REQUIRED | 402`) — no truncation, no audit footer.

**Top-level sections** (`grep -n '^## '`): `## 1. Introduction`, `## 2. Global Specifications & System-Wide Principles`, `## 3. Business Logic & Workflows`, `## 4. Endpoint Definitions`, `## 5. Error Code Catalogue`.

§2 has 11 domain-derived subsections (Logical Plant Clock, Record Identity/Audit/Revision Counters, Cascade Propagation, Nested Path Resolution, Engineering Units & Rounding, Stale-Version Guards, Segregation of Engineering Duties, Order of Precedence Among Rejections). §3 has 9 subsections organised by plant workflow: reference data -> design authoring -> analysis/revision/seal -> order placement & kit pricing -> aeration/drying/unload sizing -> confirmation/credit/deposit -> coil & roll-forming -> freight/yard/linehaul -> crews & field-failure branches.

**Hard Contract reports**

```
Field coverage check:
- entities[].fields: 135 unique required, 135 present, 0 missing (162 field entries across 15 entities)
- endpoints[].request_body: 69 required, 69 present, 0 missing
- endpoints[].query_params: 21 required, 21 present, 0 missing
- endpoints[].path_params: 1 required, 1 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 35 checked, 35 expressed in prose (full ordered ladder in §2.11), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (POST /bin-designs/{id}/analyses + expected_bin_design_version + ERR_STALE_DESIGN_VERSION/412; POST /freight-loads + expected_dealer_version + ERR_STALE_DEALER_VERSION/412), 0 missing
- state_machines[].transitions: 36 checked, 36 fully expressed, 0 missing
- calculations[]: 12 checked, 12 fully expressed, 0 missing
- validations[] conditions: 35 checked, 35 matchable to error_id in prose (all 56 error IDs appear in §2/§3), 0 missing
- endpoints[].side_effects / applies_to: 30 side-effect sets + 62 endpoints checked, all expressed, 0 missing
- entities[].fields[] structured content: 162 checked, 162 reconstructible from prose, 0 missing
- sibling-branch symmetry: 9 groups checked, 9 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 908
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Other verifications:** §2.2 is byte-identical to `section-2.2-response-structure.md`. §4 table has exactly 4 columns and all 62 endpoint rows; §5 table has exactly 2 columns and all 56 error rows. All 7 role names, all state values and all enum members appear verbatim. No pseudocode operators and no fuzzy hedging words anywhere in the document.

**No leakage:** read only `SKILL.md`, `section-2.2-response-structure.md`, the heading list of `example-prd.md`, and `SCAFFOLD.yaml`. Neither design yaml was opened, grepped, or referenced.

Orchestrator verification (truncation guard): `wc -l` = 454 lines / 91792 bytes; `tail -25` ends at the final complete error-table row `| ERR_DEPOSIT_REQUIRED | 402 |` — a real section boundary, not mid-sentence. All 5 top-level sections present; §4 table has 62 data rows (64 lines incl. header+separator), §5 has 56 `ERR_` rows. `grep -ni "harder than|expert level|scaffold"` over PRD.md returns nothing — no difficulty-directive and no scaffold leak. PRD accepted; no regeneration needed.

## Step 6: Generate implementation — 2026-09-05T05:41:00.000Z

(Launched concurrently with Step 5 in a single assistant message, per the skill's physical-isolation requirement — the impl generator started before `test_suite/` existed and never saw it.)

Subagent summary (verbatim):

Implementation complete and verified.

## Files written (19 files, 3171 lines total)

`workspace/implementation/`

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | launcher (chmod +x) |
| `requirements.txt` | 1 | `Flask==3.0.3` |
| `app.py` | 97 | app factory, request lock, error handlers, 7 blueprints |
| `common.py` | 100 | Decimal/ROUND_HALF_UP helpers, id + timestamp formatting |
| `errors.py` | 128 | `ApiError` + HTTP status map for all 57 error codes |
| `store.py` | 125 | 15 in-memory tables, logical clock, insert/touch/ordered |
| `envelope.py` | 78 | meta/response_type/data envelope, pagination |
| `authz.py` | 30 | header auth, 7 roles |
| `shape.py` | 132 | request field validators |
| `calc.py` | 483 | every normative formula (geometry, loads, stiffeners, kits, pricing, freight, verdicts) |
| `serializers.py` | 296 | 15 entity projections |
| `services.py` | 214 | aggregate recomputation + the 4 cascade chains |
| `routes_config.py` | 168 | clock + 4 reference registers (10 endpoints) |
| `routes_parties.py` | 188 | engineers, dealers, installation crews (12) |
| `routes_designs.py` | 321 | bin designs, analyses, seal cycle (9) |
| `routes_production.py` | 224 | coil lots, roll-forming runs (8) |
| `routes_orders.py` | 262 | dealer orders, payments, crew assignment (8) |
| `routes_freight.py` | 201 | freight loads, dispatch/deliver (7) |
| `routes_failures.py` | 113 | field failures, analysis, determination (5) |

## Module decomposition

Layered: `common`/`errors`/`store`/`envelope`/`authz`/`shape` (infrastructure) -> `calc` (pure normative arithmetic, no I/O) -> `serializers` + `services` (projections and cross-entity effects) -> seven `routes_*` blueprints. **62 endpoints registered**, matching the PRD's 62-row endpoint table.

Storage is Python dicts only — no SQLite, no disk, no seeding (verified by grep; the only match is a comment in `store.py` asserting nothing is preloaded). `start.sh` reads `$PORT` (fallback 10000), installs Flask only when missing, and `exec`s `python3 app.py` in the foreground binding `0.0.0.0`, so it is idempotent across the harness's per-test kill/relaunch cycles.

## Smoke test (PORT=39123, real `bash start.sh`)

Booted in under a second. `POST /coating-specs` -> 201 with correct envelope, integer `zinc_mass_g_per_m2: 305` and derived `corrosion_class: "C3"`; `GET /coating-specs` -> 200 with `meta` `{limit:10, offset:0, total_count:1, has_more:false}` and `response_type:"array"`; `zinc_mass_g_per_m2: 305.5` -> 400 `ERR_INVALID_REQUEST`. Resolved the true listening PID via `ss -ltnp` and killed only that PID; port confirmed free. No pattern-based kill was used at any point.

Two in-process suites (`/tmp/task2823_impl/smoke.py`, `smoke2.py`) exit 0, covering all pinned numeric examples (load-demand tie-breaks, ASD 90.0 / LRFD 101.25 allowables, bolt-pack ceiling-then-multiply = 36, the 8-step price ladder, aeration and drying branches, gravity discharge 817 bph, WEIGHT-basis linehaul splits summing exactly, coil-mass conservation, all 4 determination cascades, both credit-hold directions, load self-cancel on emptying, and line-window/buffer/yard-slot edges).

Three bugs found and fixed during generation: `load_demands` was called with mismatched positional args (500 on `POST /bin-designs`), `consumed_kg`/`scrap_kg`/`amount_cents` had invented minimums that masked later ladder steps, and `zinc_mass_g_per_m2` was emitted as a float against the scaffold's declared integer type.

## Step 5: Generate unit tests — 2026-09-05T06:44:00.000Z

(Launched concurrently with Step 6 in the same assistant message.)

Subagent summary (verbatim):

Generation is complete for task 2823.

## Coverage (design-index-only)

| Queue | Live instances | Stubs (`excluded_because:`, not translated) | Instances covered | Tests emitted |
|---|---|---|---|---|
| A — `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8) | 19 | 0 | 19 (100%) | 38 |
| B — `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9) | 50 | 26 | 50 (100%) | 53 |
| **Total** | **69** | 26 | **69** | **91** |

**Instances SKIPPED: none.** Every non-stub instance in both indices passed the PRD-first two-condition filter and was translated. The 26 `excluded_because:` stubs were deliberately not translated, per the contract. No test was weakened, no `skip`/`xfail`, no placeholders.

Each of the 91 tests carries exactly one verbatim `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line; all 69 distinct tags resolve to a real `- name:` in the correct yaml, and no tag points at a stub.

## Files written — both at the TASK ROOT, nothing under `workspace/`

`test_helpers/` (2969 lines): `__init__.py` 54, `api_client.py` 270, `api_errors.py` 128, `assertions.py` 449, `constants.py` 165, `factories.py` 390, `fixtures.py` 990, `test_users.py` 77, `types.py` 446.

`test_suite/` (6062 lines): `conftest.py` 46, `test_01_structural_envelope.py` 348 (6 tests), `test_02_kit_pricing_and_sizing.py` 502 (10), `test_03_design_lifecycle.py` 787 (9), `test_04_orders_and_credit.py` 800 (13), `test_05_production_runs.py` 634 (9), `test_06_freight_and_linehaul.py` 844 (13), `test_07_failures_and_crews.py` 632 (10), `test_08_platform_rules.py` 1469 (21).

`workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation/` — no test directory. `workspace/implementation/` was never read, globbed, or executed; `worklog.md` untouched; no tests run; no process killed; scratch confined to `/tmp/task2823_tests/`.

## Verification run

- `python3 -m py_compile test_suite/*.py` — clean.
- `python3 -m pyflakes test_suite/*.py test_helpers/fixtures.py` — exit 0 (pruned 4 unused imports from test_08 and a stale `CLOCK_STARTUP_UTC` import in `fixtures.py`). Remaining pyflakes noise is only the intentional star re-exports in `test_helpers/__init__.py`.
- Citation verifier (`/tmp/task2823_tests/verify_citations.py`) — `problems: 0`: every test has a docstring, exactly one `Design:` tag resolving to a real instance, and every `PRD §x.y: "..."` quote is a verbatim substring of `workspace/PRD.md`.
- AST import sweep against the real `test_helpers` package — `missing: []`.

**Key finding worth carrying forward:** the last file's citations initially failed verbatim checking in 22 places for a single mechanical reason — the PRD uses em dashes (`—`, 119 occurrences, zero ASCII `" - "`), and the heredoc chunks for `test_08` had transcribed them as `" - "`. A scripted docstring-only dash normalisation fixed all 22 at once. Worth checking em-dash fidelity right after each chunked append rather than at the end.

Orchestrator verification: `test_helpers/` and `test_suite/` both exist at the task root; `ls -d workspace/test_*` returns nothing (no stray test dirs under `workspace/`, a known failure mode).

## Step 7: Run tests and iterate — 2026-09-05T07:02:00.000Z

Subagent summary (verbatim):

All 8 rounds green. Loop complete.

## Summary

**Iterations run:** 2

**Tests deleted:** none. No test failed the STEP 1 PRD-coverage or unique-derivability checks.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none. The single failure was a test-side precondition bug; no implementation check was weakened or removed.

**Fixes applied to `test_suite/`:**
- `test_suite/test_05_production_runs.py` — `TestRunMassGates.test_over_reservation_and_over_consumption_are_refused_but_exact_equality_posts`: setup built the design with `create_design(ref)`, leaving it in `DRAFT`, then expected `POST /dealer-orders/{id}/confirm` to return 200. The default jurisdiction preset `NE-WEST` has `seal_required: False`, and PRD §3.6 states verbatim: "when the design's `seal_required` is true the design must have reached `SEALED`, and when `seal_required` is false the design must be in either `UNDER_REVIEW` or `SEALED`. A design that satisfies neither reading is refused with `ERR_DESIGN_NOT_SEALED`." A `DRAFT` design satisfies neither reading, so the implementation's 409 `ERR_DESIGN_NOT_SEALED` was PRD-correct (STEP 2: TEST IS WRONG). Changed the setup to `create_design_under_review(ref)` — the same pattern every other confirmation-dependent fixture in `test_helpers/fixtures.py` already uses (`setup_line_window_anchor`, `setup_depleted_coil_lot`, `setup_credit_ledger_orders`). Geometry defaults are untouched, so the design's `sheet_gauge_mm` still matches the 1.6 mm coil lot the test schedules against, and all run-mass-gate assertions were preserved verbatim. Added the corresponding `create_design_under_review` import.

**Final sweep (all 8 parallel rounds):**

| Round | Passed / Total |
| --- | --- |
| 1 | 91 / 91 |
| 2 | 91 / 91 |
| 3 | 91 / 91 |
| 4 | 91 / 91 |
| 5 | 91 / 91 |
| 6 | 91 / 91 |
| 7 | 91 / 91 |
| 8 | 91 / 91 |

Zero failures, zero errors, zero skips in every round. The failure was deterministic (all 8 rounds of iteration 1 failed the identical test with the identical error), so no flakiness was masked; nothing load-induced appeared in either sweep. Per-round results remain at `workspace/implementation/results.{1..8}.json` for verification. `worklog.md` was not touched.

Orchestrator verification (the subagent's claim was re-checked, not taken on trust): all eight `results.$i.json` files exist on disk and were independently parsed — every round reports `passed=91, failed=0, errors=0, skipped=0, total=91`. `grep -c Terminated workspace/sweep.log` = 0, so the sweep was not reaped (the setsid wrapper held). `worklog.md` carries no subagent-written step heading.

Step 8 skip-condition adjudication (orchestrator decision, recorded per the AUTONOMY directive): the literal skip condition in the skill requires 0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes. Step 7 reported one `test_suite/` fix, so the condition is NOT met and Step 8 will be run. It is expected to produce a near- or byte-identical `PRD_FINALIZED.md`, because the sole Step 7 item was a pure fixture-precondition bug against a rule the PRD already states verbatim, with zero implementation fixes — and Step 8's own method says to patch only where impl pinned a choice PRD left open. A byte-identical `PRD_FINALIZED.md` is a legitimate Step 8 outcome when Step 7 made no implementation fixes; only Step 9 must never be identical.

## Step 8: Finalize PRD — 2026-09-05T07:05:00.000Z

Subagent summary (verbatim):

## Verdict: `PRD_FINALIZED.md` is byte-identical to `PRD.md`

`workspace/PRD_FINALIZED.md` created via `cp` from `PRD.md` (md5 `87feef745b8a7a3ef5136edfec233af1` for both; `cmp` clean).

- **Line counts:** PRD.md 454 / PRD_FINALIZED.md 454 — **0% delta**.
- **Change bullets:** none. No edit traced to a genuine PRD silence or PRD/impl mismatch.

### Adjudication of the single `<step_7_diff>` item

**Item:** `test_suite/test_05_production_runs.py::TestRunMassGates::test_over_reservation_and_over_consumption_are_refused_but_exact_equality_posts` — setup changed from `create_design(ref)` (leaves `DRAFT`) to `create_design_under_review(ref)`.

**Subject identified:** the confirmation-time engineering-posture gate on the referenced design, and the `ERR_DESIGN_NOT_SEALED` status code.

**Impl paths enumerated (read/grepped, not just the Step 7 site):**
- `routes_orders.py:165-186` (`confirm_order`) — the gate itself: `if design["seal_required"]: if status != "SEALED" -> ERR_DESIGN_NOT_SEALED; elif status not in ("UNDER_REVIEW","SEALED") -> ERR_DESIGN_NOT_SEALED`, then the `seal_required`-only permit clock (`:175-178`), then the credit gate (`:180-181`). Evaluation order and both readings match PRD §3.6 (`PRD.md:254`) word for word; a `DRAFT` design satisfies neither reading, so the impl's refusal is PRD-determined. The order-state precheck at `:165` matches the separate `ERR_ORDER_STATE_INVALID` sentence at `PRD.md:252`.
- `errors.py:29` — `"ERR_DESIGN_NOT_SEALED": 409`, matching both `PRD.md:136` (listed among the 409 state-admissibility codes) and the code table at `PRD.md:415`. Status code is already uniquely pinned.
- Every other `seal_required` site, to confirm no off-site path is described differently: `routes_config.py:45` (jurisdiction register field), `routes_designs.py:120` (copied onto the design at creation — pinned at `PRD.md:184`), `serializers.py:17` and `:127` (exposed on jurisdiction and design payloads), plus `routes_orders.py:175` (permit gate). All consistent with existing prose; the `permit_ready_at is None` disjunct at `:177` is unreachable because `seal_required` true already forces `SEALED`, and sealing always writes `permit_ready_at` (`PRD.md:212`).
- Preset evidence: `test_helpers/factories.py:15-21` — `NE-WEST` has `seal_required: False`, `permit_review_days: 0`, confirming the failure was purely the fixture's `DRAFT` precondition.
- The preserved assertions in that test are §3.7 run-mass gates, quoted verbatim from the PRD in the test docstring; nothing there was weakened, so no §3.7 gap either.

**Wording adjustment made:** none required — no edit was committed, because the gate, its two readings, its ordering relative to the permit and credit gates, and its 409 status are all already uniquely derivable from the existing §3.6 and §4 prose.

Per the method, a `test_suite/` fixture-precondition bug against an already-verbatim PRD rule is not a PRD silence, so no edit was manufactured. Zero `implementation/` fixes and zero test deletions in Step 7 is consistent with this outcome.

Orchestrator note: a byte-identical `PRD_FINALIZED.md` is the correct Step 8 outcome here — Step 7 made zero `implementation/` fixes, so `PRD.md` already determined every behavior the implementation exhibits at the one site Step 7 touched. Step 9, by contrast, must not come out identical; it is being run as three sequential module-partitioned passes over one shared `PRD_COMPLETED.md` (pass 1 performs the `cp`; passes 2 and 3 must not) so that the full impl scan cannot be silently skipped.

## Step 9: Complete PRD — 2026-09-05T07:25:00.000Z

Run as THREE SEQUENTIAL module-partitioned passes over one shared `workspace/PRD_COMPLETED.md`. Rationale (orchestrator decision, recorded per the AUTONOMY directive): a single-shot Step 9 over a 3171-line implementation and a 454-line/92 KB PRD reliably under-scans and can silently emit a byte-identical file, which is the one outcome Step 9 must never produce. Partitioning by implementation module makes the scan auditable per module and lets each pass hold the whole of its modules in context. Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from re-copying so they append onto prior work, and each later pass spot-checked earlier passes' edits for survival.

Partition:
- Pass 1 — platform layer + reference data: `app.py`, `common.py`, `errors.py`, `store.py`, `envelope.py`, `authz.py`, `shape.py`, `serializers.py`, `routes_config.py`, `routes_parties.py`
- Pass 2 — formulas + cascades + design/production lifecycle: `calc.py`, `services.py`, `routes_designs.py`, `routes_production.py`
- Pass 3 — order/freight/failure state machines: `routes_orders.py`, `routes_freight.py`, `routes_failures.py`

### Pass 1 summary (verbatim)

Pass 1 complete.

## Setup
`cp workspace/PRD_FINALIZED.md -> workspace/PRD_COMPLETED.md` done. Passes 2 and 3 can append onto it.

## Line count
- Before edits: **454**
- After edits: **454** (every change is an in-paragraph insert/revision on an existing line — 17 lines replaced in place, no new paragraphs, no new sections)

## Counts
- **ambiguity-pins: 14**
- **mismatch-revisions: 3**

## Changes
- `§2.1` — insert — ambiguity — an empty-string `X-User-ID`/`X-User-Role` is treated exactly as absent (`ERR_MISSING_AUTH_HEADERS`); role names matched case-sensitively and never trimmed — `authz.py:24-27`
- `§2.2 (api_request_id bullet)` — insert — ambiguity — `req_` + exactly 20 chars from `A-Z0-9`, 24 chars total — `common.py:43-47`
- `§2.2 (api_request_timestamp bullet)` — insert — ambiguity — three fractional digits with literal `Z`, read from the **real wall clock**, never the logical plant clock — `envelope.py:17`, `common.py:54-69`
- `§2.2 (data bullet)` — insert — ambiguity — per-entity projection is a fixed field set independent of row state; absent values emit as explicit JSON `null`, never omitted; no field outside the set (the creation ordinal is never projected) — `serializers.py:93-133`, `common.py:94-100`, `store.py:53`
- `§2.3` — insert — ambiguity — `offset` has no upper bound; non-integer `limit`/`offset` (fraction or text) is `ERR_INVALID_REQUEST`; omitted **or empty-string** takes the default; an out-of-range `offset` yields an empty `data` with the true `total_count` — `envelope.py:38-60`
- `§2.3` — insert — ambiguity — `created_at` ties break by insertion order (ordering is total and stable); filter params are exact string matches, empty filter == absent, unmatched/nonexistent filter value yields an empty page not a 404, undeclared query params ignored — `store.py:83-84`, `routes_parties.py:60-62,119-121`
- `§2.4` — insert — ambiguity — `to_iso8601` mandatory, must parse, zoneless read as UTC, any instant accepted; `current_utc` is the **sole** key of `data` (no resource row) — `routes_config.py:26-32`
- `§2.5` — insert — ambiguity — `created_at`/`updated_at` are stamped from **real server time**, fully independent of the logical clock — `store.py:54-58,78`
- `§2.5` — insert — ambiguity — on insert `updated_at` equals `created_at` — `store.py:57`
- `§2.5` — insert — ambiguity — "exactly 1" is a per-request **ceiling**: a row touched several times in one cascade still advances `version` by 1 with one `updated_at` refresh; rows read only as gates are untouched — `store.py:63-80`, `app.py:31`
- `§2.8` — insert — ambiguity — integer-vs-float JSON emission enumerated: money/counts/`version`/`analysis_index`/`freight_sequence`/`order_count`/`max_weight_kg` and the integer register scalars emit as JSON integers; every decimal-width field emits as a JSON fractional number even when integral (`750` -> `750.0`); nothing emits as a numeric string — `common.py:94-100`, `serializers.py:*`, `calc.py:120`
- `§2.11 step 3` — insert — ambiguity — four shape conventions: all "between X and Y" ranges inclusive both ends; integer-declared fields reject fractions/numeric strings/booleans; explicit `null` == absent (so required-as-null is rejected); string fields length-checked only against declared bounds, so empty string is accepted where none is declared — `shape.py:28-33,58-68,71-88,36-46`
- `§2.10` — **revise** — **mismatch** — PRD's "`LAPSED` is terminal" implied a state rejection; impl has no gate: re-lapsing an already-lapsed engineer returns 200, keeps `LAPSED`, and still bumps `version` — `routes_parties.py:72-78`
- `§3.1` — **revise** — **mismatch** — PRD asserted `code`/`grain_code`/`coating_code`/`line_code`/`license_number` "must be unique"; impl enforces **no** uniqueness and §5 has no duplicate-key code, so a repeat natural key creates an independent row. Length/range bounds are enforced (`ERR_INVALID_REQUEST`) — `routes_config.py:38-156`, `routes_parties.py:42-53`
- `§3.1` — insert — ambiguity — `licensed_jurisdiction_codes` stored verbatim and **not** resolved against the jurisdiction register at registration; compared later by exact string equality. New engineer `status` always `ACTIVE`, client cannot supply it — `routes_parties.py:46-51`
- `§3.1` — insert — ambiguity — the four reference registers accept no filter; a filter param offered to them is ignored — `routes_config.py:58-61,95-98,132-135,159-162`
- `§4 intro` — **revise** — **mismatch** — trailing slash insignificant; unrouted path -> `ERR_INVALID_REQUEST` with **404**, undeclared method -> **405**, the only two places that code departs from §5's 400, and both precede any header check so an unrouted path never reports an auth error — `app.py:18,58-65`

## Partition coverage
All ten modules scanned exhaustively. **Fully already-pinned, no edit needed: `errors.py`** — its `ERROR_HTTP_STATUS` map is an exact, complete match for the §5 catalogue (all 57 codes, same statuses, no extras). Also verified already-uniquely-pinned and left untouched: the success/error envelope key sets and `response_type` values, `has_more` semantics, the 201-on-create / 200-otherwise rule, the five `id`+`created_at`-only immutable entities, UUID ids with no prefix, the §2.7 not-found code assignment, all-roles reads, and ladder ordering (authorize -> shape -> path -> body FK) in every route in the partition.

### Pass 2 summary (verbatim)

Pass 2 complete.

**File size:** 454 lines before, 454 lines after (every edit is in-paragraph; 91,792 -> ~99,262+ bytes of prose growth, no new sections, no new paragraphs).

**Counts:** 20 changes total — 17 ambiguity-pins, 3 mismatch-revisions.

**Changes**

- §3.2 Geometry/capacity — insert — ambiguity — radius, roof rise and both volumes are carried at full precision, never rounded individually and never persisted; the half-up quantisation to 2 dp applies once, to the sum — `calc.py:179-183`
- §3.2 Loading — insert — ambiguity — `moisture_factor` itself is never rounded, and `grain_demand_kpa` multiplies the already-rounded 3-dp `grain_lateral_kpa` by that unrounded factor — `calc.py:215-220`
- §3.2 Stiffeners — insert — ambiguity — the demand-moment product (governing demand x rounded circumference) is carried unrounded through both the ceiling and the utilization ratio and never persisted — `calc.py:246-251`
- §3.2 Gauge ladder — insert — ambiguity — the `governing_demand_kpa x 0.05` threshold is compared unrounded — `calc.py:253-258`
- §3.2 Gauge ladder — insert — ambiguity — the design row stores no allowable-per-stiffener capacity and no PASS/FAIL verdict; both are computed in passing and live only on analysis rows — `routes_designs.py:76-79`
- §3.3 Analysis register — insert — ambiguity — analysis creation is not gated on the design's `status` (DRAFT through RECALLED all admissible) and never moves it — `routes_designs.py:162-191`
- §3.3 Revision — insert — ambiguity — the two safety gates evaluate the *merged* moisture/wind, and all gates run before any field is written — `routes_designs.py:268-288`
- §3.3 Revision — insert — ambiguity — already-superseded analyses are rewritten and bump `version` again rather than being skipped — `routes_designs.py:294-296`
- §3.4 Price step two — insert — ambiguity — half up on the negative PRESEASON uplift means half *away from zero* (-0.5 -> -1) — `calc.py:391` + `common.py:28`
- §3.5 Airflow — insert — ambiguity — no intermediate in the four-factor product is rounded; first quantisation is the cap-then-ceiling — `calc.py:294-303`
- §3.6 Credit chain — insert — ambiguity — the hold/release sweep fires only on an actual `status` crossing; the sum is unchanged by the sweep so the ledger is never recomputed twice per request — `services.py:27-41`
- §3.7 Coil receipt — revise — **mismatch** — `heat_number` uniqueness is an unenforced convention; a duplicate receipt is accepted as an independent lot (PRD said "must be unique") — `routes_production.py:44-67`
- §3.7 Run scheduling — insert — ambiguity — booking recomputes the lot ledger and bumps the lot's `version` in the same call; the named order's three state dimensions are never consulted — `routes_production.py:119-156`
- §3.7 Run completion — insert — ambiguity — `consumed_kg`/`scrap_kg` carry no declared range bound; only their sum is compared — `routes_production.py:181-188`
- §3.7 Run completion — revise — **mismatch** — the QUEUED->KITTED hop is conditional; a non-QUEUED order is untouched, so two rows change rather than the three PRD enumerated — `routes_production.py:197-200`
- §3.7 Run void — revise — **mismatch** — the KITTED->QUEUED revert is conditional on the order actually being KITTED; otherwise only the run and lot change — `routes_production.py:219-223`
- §3.8 Yard staging — insert — ambiguity — the recall chain's self-cancelling load refreshes `staged_kit_count` *without* bumping the dealership's `version`/`updated_at` — `services.py:45-55,115`
- §3.8 Linehaul split — insert — ambiguity — an attached order whose sequence and share both come out unchanged is not touched and does not bump `version` — `services.py:86-92`
- §3.9 Recall chain — insert — ambiguity — SEALED/UNDER_REVIEW are the only entry states; against DRAFT/REVISION_REQUIRED/already-RECALLED the chain fires no hop at all. Also: the dealership is absent from the version enumeration by design — `services.py:147-162`
- §3.9 Coating quarantine — insert — ambiguity — lots visited in ascending creation order; an empty target set is a silent no-op — `services.py:170-181`
- §3.9 Crew decertification — insert — ambiguity — `CERTIFIED` is the branch precondition: a PROBATION/REVOKED crew is not downgraded twice and blocks nothing; same when the order names no crew — `services.py:184-190`

**Coverage:** all four partition modules walked exhaustively — `calc.py` (all 15 functions and every constant table), `services.py` (all 8 functions incl. the four cascades), `routes_designs.py` (all 9 endpoints + `run_pipeline` + the licensure/safety helpers), `routes_production.py` (all 8 endpoints + `_window_conflict`). Validation-ladder order in both route modules was verified against §2.11 and matches (schedule_run hits steps 7->18->19->21->25->31 exactly; seal hits 7->14->15; revise hits 7->9->10->15) — no edits needed there.

**Pass 1 integrity:** intact — 17 changed lines outside the partition, exactly the 17 reported. Spot-checked two: §2.1's empty-header clause and §2.2's `req_` + 20-character clause — both present verbatim.

### Pass 3 summary (verbatim)

Pass 3 complete.

**Line count:** 454 before -> 454 after (every change is an in-paragraph insert/revision; no new lines, no new sections).

**Counts:** 15 edits — 12 ambiguity-pins, 3 mismatch-revisions.

### Changes
- §3.4 (L220) — insert — ambiguity — placement writes only the order row and its kit lines; the dealership is not recomputed and its `version` does not move — `routes_orders.py:126-129`
- §3.4 (L220) — insert — ambiguity — the dealership's `status` is not consulted at placement (a `CREDIT_HOLD` dealer may still place/price) — `routes_orders.py:56-66`
- §3.6 (L254) — insert — ambiguity — a `RECALLED` design fails the seal-posture gate and surfaces `ERR_DESIGN_NOT_SEALED` at confirmation, not `ERR_DESIGN_RECALLED` — `routes_orders.py:169-173`
- §3.6 (L254) — insert — ambiguity — the money gate is the arithmetic comparison alone; dealer `status` and order `installation_readiness` are never read — `routes_orders.py:180`
- §3.6 (L262) — revise — mismatch — deposit gate order pinned: both state gates precede the amount comparison and the *financial* gate precedes the production gate, so a cancelled order (financial `VOIDED`) observably answers `ERR_DEPOSIT_ALREADY_PAID`; also pinned that the order is the only row written (no ledger recompute) — `routes_orders.py:198-207`
- §3.8 (L284) — insert — ambiguity — planning reads only the dealership's `version`, `staging_slots` and `high_cube_access`; its `status` is never consulted — `routes_freight.py:41-63`
- §3.8 (L286) — insert — ambiguity — a successful plan is itself a `staged_kit_count` recomputation, so it bumps the dealership's `version` (two rows) and the next plan needs a refreshed `expected_dealer_version` — `routes_freight.py:80-81`
- §3.8 (L290) — revise — mismatch — the notional capacity set counts the named order once, so re-offering an order to *its own* full trailer passes capacity and reaches `ERR_ORDER_ALREADY_ON_LOAD` (the old blanket "re-attaching to an already-full trailer surfaces the capacity error" was wrong for the same-load case); also pinned: comparison against the rounded 3-dp/2-dp sums, none of the order's three state dimensions consulted (`DRAFT`/hold/`CANCELLED` attachable), the attached order always bumps `version`, dealership row untouched — `routes_freight.py:112-128`
- §3.8 (L298) — revise — mismatch — dispatch gate order corrected to match the §2.11 step-7 precedence: the attached orders' `production_status` gate runs *first*, ahead of empty-set, utilization floor and deposit; `installation_readiness` is never consulted — `routes_freight.py:136-150`
- §3.8 (L300) — insert — ambiguity — delivery's financial advance is conditional (a non-`DEPOSIT_PAID` order keeps its status but still gets `credit_hold_cents` zeroed and `version` bumped); production stays `SHIPPED`; `staged_kit_count` is not recomputed — `routes_freight.py:170-179`
- §3.8 (L302) — insert — ambiguity — a cancelled load re-derives its aggregates over the emptied set (all five read 0) and the credit ledger is *not* recomputed — `routes_freight.py:190-200`
- §3.9 (L308) — insert — ambiguity — the already-assigned test precedes the production-state test; `financial_status` and `installation_readiness` are never consulted — `routes_orders.py:244-247`
- §3.9 (L308) — insert — ambiguity — assignment writes only the order; crew and design are read-only gates — `routes_orders.py:259-261`
- §3.9 (L310) — insert — ambiguity — the three measured inputs are range-checked but stored/projected/compared at the supplied precision (never quantised to 3 dp); intake writes only the investigation row — `routes_failures.py:38-58`
- §3.9 (L312) — insert — ambiguity — both verdicts read the design row *live* at analysis time (the intake freeze fixes which design, not its numbers), both are always fixed regardless of `failure_mode`, and the investigation is the only row written — `routes_failures.py:86-96`

### Coverage and integrity
- Scanned exhaustively: `routes_orders.py` (place, list, read, kit-lines, confirm, payments, cancel, assign-crew), `routes_freight.py` (plan, list, read, assign-order, dispatch, deliver, cancel), `routes_failures.py` (open, list, read, start-analysis, determine).
- Passes 1 and 2 intact (verified by word-level diff vs `PRD_FINALIZED.md`): pass 1 — §2.1 empty-header-equals-absent (L15), §2.2 `req_` + 20 chars / fixed-field-set projection (L44, L47); pass 2 — §3.2 full-precision radius/rise/volumes (L190), §3.7 conditional `QUEUED->KITTED` hop and shape-gate-only mass fields (L274) and conditional `KITTED` revert on void (L276). None of the `old_string` anchors overlapped prior-pass insertions.

### Step 9 totals and orchestrator verification

52 edits across the three passes — 43 ambiguity-pins, 9 mismatch-revisions.

Orchestrator verification: `workspace/PRD_COMPLETED.md` is 454 lines / 110656 bytes against `PRD_FINALIZED.md`'s 454 lines / 91792 bytes — **+18864 bytes** of pinning prose, and `cmp` reports the two files DIFFER (the byte-identical failure mode did not occur). Structural integrity held: all 25 `##`/`###` headings still present, the §5 catalogue still carries all 56 `ERR_` rows, and the file still ends at the final complete error-table row `| ERR_DEPOSIT_REQUIRED | 402 |` — no truncation from the chunked in-place editing. `find . -name worklog.md` returns only the single task-root copy (no stray drifted into `workspace/`).

## Pipeline complete — 2026-09-05T07:27:00.000Z

All nine steps done. Final state: SCAFFOLD.yaml + both design indices at the task root; `test_helpers/` (9 files, 2969 lines) and `test_suite/` (9 files, 6062 lines, 91 tests) at the task root; `workspace/` holds INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md and `implementation/` (19 files, 3171 lines, 62 endpoints) plus the eight passing `results.{1..8}.json`. Independently re-verified 8/8 rounds at 91/91 with zero failures, errors and skips.
