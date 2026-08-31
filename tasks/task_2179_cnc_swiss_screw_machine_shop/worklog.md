# Worklog — task_2179_cnc_swiss_screw_machine_shop

## Step 1: Create task directory — 2026-08-30T04:28:39.000Z

Created `tasks/task_2179_cnc_swiss_screw_machine_shop/` and `tasks/task_2179_cnc_swiss_screw_machine_shop/workspace/`. Task index 2179 (highest existing was 2178).

## Step 3: Copy shared files — 2026-08-30T04:29:00.000Z

Copied `INSTRUCTION.md` from project root to `tasks/task_2179_cnc_swiss_screw_machine_shop/workspace/INSTRUCTION.md`.

## Step 2: Generate scaffold — 2026-08-30T05:09:00.000Z

All three artifacts are generated, mutually consistent, and lint-clean.

## Files

| Path | Lines |
|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_2179_cnc_swiss_screw_machine_shop/SCAFFOLD.yaml` | 2,575 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2179_cnc_swiss_screw_machine_shop/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 4,142 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2179_cnc_swiss_screw_machine_shop/SCAFFOLD_CORNER_DESIGN.yaml` | 10,073 |

## Scaffold contents (§1.0–§1.7)

- **Profile**: quota/allocation × compliance-audit, `entity_topology: graph`, `state_machine_shape: parallel`, `role_model: segregation_of_duties`, layers = OCC + cascading side effects + dual-variant calc + rate/threshold triggers. Expert-plus band.
- **13 entities**: Operator, Machine, Part, Characteristic, Gauge, BarStockLot, Quote, BlanketPO, KanbanRelease, WorkOrder, ToolAssignment, SpcSample (`common_fields: false`), RoutingStep (self-referential `predecessor_step_id`).
- **10 state machines**: WorkOrder emitted twice as two *parallel* dimensions (`machining_status` cyclic RUNNING<->INTERRUPTED, `quality_status` cyclic IN_SPC<->QUALITY_HOLD); ToolAssignment, Gauge, Machine, BlanketPO, RoutingStep all cyclic; KanbanRelease branching fork; Quote and BarStockLot linear.
- **12 calculations**, **32 validations** (priority 10->98), **51 endpoints**, **43 error codes**, **4 roles**, **2 OCC concurrency rules** (`BlanketPO.version` on release create, `Machine.version` on work-order schedule).

## Design instances

- **§1.8** — 9 rule groups, **21 instances** (dual_variant 2, combinatorial 3 covering modes a/b/c, non_linear_sm 2, transitive_cascade 2 x depth-4, priority_pair 3 distinct category pairs, boundary 2, cross_entity 3, temporal_overlap 2, compensating_invariant 2).
- **§1.9** — 9 guide sections, **71 instances** (65 with full `test_recipe`, 6 `excluded_because` stubs pointing at named §1.8 instances).

## Verification performed

Every formula-derived assert literal was executed in Python before being written: quote prices 289 / 305 / 284 / 315 / 541 / 620; rebate 2023000 -> 0.06 -> 272 -> 1904000; Cpk 1.385 / 1.615 / 1.292 / 1.357 and Ppk 1.917 / 1.717 / 1.684 / 0.529; bar ledger 72000 = 64800 + 7200 + 0; chip 3.504 / 2.861 kg with round-per-alloy-line credit **1743 != 1744** (sum-then-round) and net **1179**.

Audits run clean: zero unbound `${var}` across both design files, 92 unique instance names, all `grounds` resolve, all `excluded_because` targets exist, no forbidden race vocabulary, neither design key present in `SCAFFOLD.yaml`, no YAML aliases.

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5
and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints declared:    51
  §1.1 entities declared:     13
  §1.8 instances scanned:     21
  §1.9 instances scanned:     65
  Calls scanned (§1.8+§1.9):  1306
```

Note on scope: I did not read any sibling `task_*/` directory — the design is derived solely from the scenario text and the skill spec. The endpoint count (51) and error count (43) exceed the §0.4 Expert guideline, which I judged appropriate given the "harder than expert level" instruction; the excess is mostly FK reverse-reachability GETs and per-entity 404 codes rather than added mechanics.

## Step 4: Generate PRD — 2026-08-30T05:19:00.000Z

PRD generated and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2179_cnc_swiss_screw_machine_shop/workspace/PRD.md` — **385 lines**

Built incrementally in 6 append passes (title+§1+§2.1+§2.2 -> §2.3–2.10 -> §3.1–3.2 -> §3.3–3.4 -> §3.5–3.6 -> §3.7 -> §3.8 -> §3.9 -> §4+§5 generated from the scaffold), then repaired and re-verified.

**Structure:** §1 Introduction (3 paras) · §2 with 10 subsections (2.2 emitted verbatim) · §3 with 9 domain subsections · §4 endpoint table (4 columns) · §5 error table (2 columns). Ends at §5 — no audit footer.

**Verified per-category coverage** (mechanical diff of scaffold vs. backticked tokens in PRD, code fences stripped):

| Category | Scaffold | Covered | Missing |
|---|---|---|---|
| Entities | 13 | 13 | 0 |
| `entities[].fields[].name` | 120 | 120 | 0 |
| State machines | 10 | 10 | 0 |
| State transitions | 50 | 50 | 0 |
| State enum values | 28 distinct | 28 | 0 |
| Other enum values (alloys, gauge types, certs, operations, decisions) | all | all | 0 |
| Calculations | 12 | 12 | 0 |
| Validations | 32 | 32 | 0 |
| Endpoints (table rows) | 51 | 51 | 0 |
| Request-body identifiers | 90 | 90 | 0 |
| Query-param identifiers | 15 | 15 | 0 |
| Error codes (in §2/§3 prose) | 43 | 43 | 0 |
| Error codes (§5 table rows) | 43 | 43 | 0 |
| Roles (named + `identity:` translated) | 4 | 4 | 0 |
| OCC concurrency rules | 2 | 2 | 0 |

**Hard Contract reports**

Field coverage check: 120/120 entity fields, 90/90 request-body keys, 15/15 query params — PASS.
Rule coverage check: 32/32 validations, 2/2 OCC rejections, 50/50 transitions, 12/12 calculations, 51/51 endpoint side-effect sets, 120/120 structured field contents, 9/9 sibling-branch symmetry groups — PASS.
Path purity check (§3 only): 726 backtick tokens scanned, 0 paths / 0 bare methods / 0 method+path tokens — PASS.

Also confirmed: §2.2 is byte-identical to `section-2.2-response-structure.md`; no fuzzy/approximating words; no pseudocode operators outside the tables; §2.3 states limit default 10 / min 1 / max 100, offset default 0, `created_at` ascending. The two withheld design indices (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.

## Step 6: Generate implementation — 2026-08-30T05:36:00.000Z

Implementation complete at `workspace/implementation/`.

## Files written

| File | Lines | Contents |
|---|---|---|
| `app.py` | 51 | Flask entry point, blueprint registration, `ApiError`/HTTP/unhandled error handlers, `0.0.0.0:$PORT` (default 10000) |
| `core.py` | 279 | Logical clock (epoch `2026-08-01T00:00:00Z`), empty in-memory store, `Decimal` half-up rounding, ISO-8601 3-digit timestamps, `meta`/`response_type`/`data` envelope, 43-code error catalogue |
| `guards.py` | 228 | Validation ladder helpers: auth (10/20), body/enum/bound/pagination (30), path & body-FK existence (40/45), ACTIVE-operator (50), unique keys (98) |
| `calc.py` | 378 | All 12 calculations + pinned constants |
| `services.py` | 129 | Gauge lazy re-eval, routing-step block/unblock, 4-hop tool-hold chain, PO lazy expiry, fulfilment hops 2–4 |
| `routes_masters.py` | 425 | Clock, operators, machines (restore/reclaim), parts, characteristics, gauges, bar lots, tool assignments |
| `routes_commerce.py` | 263 | Quotes (price/accept), blanket POs (suspend/reinstate), kanban releases (short-close) |
| `routes_production.py` | 507 | Work orders (schedule/start/complete/cancel/disposition/quality-summary), SPC samples, routing steps |
| `start.sh` | 8 | `exec python3 app.py`, dependency install guarded on `import flask` |
| `requirements.txt` | 1 | flask |

**51 endpoints** implemented — exactly matching the PRD §4 table (verified by enumerating the Flask url_map).

## Verification

- Every file compiles (`python3 -m py_compile`).
- **Boot smoke test passed**: `PORT=18180 bash start.sh` from a cleared `__pycache__`, HTTP ready on attempt 2, `GET /swiss-shop/work-orders` -> 200 and `POST /_clock/set_current_utc` -> 200. Store confirmed empty at boot (no seeding anywhere).
- Hand-verified end-to-end run: quote pricing (`effective_qty 1020`, four separately-rounded components `104625/22000/61667/26281` -> lot `214573`, unit `275`), rebate tier from the pre-rebate total (`550000` -> 3% -> net `267`), bar reservation (`13800mm` -> 5 whole bars -> `15000mm`), chip/coolant accrual (`7.74 kg`, `2.139 L`), reclamation (`913 - 898 = 15` cents), cpk short-term `1.938` vs pooled ppk `3.113`, observed cycle time `45.8`.
- Cascades and gates exercised: 4-hop tool-hold chain (station -> machine DOWN -> WO INTERRUPTED -> steps BLOCKED), index/restore/restart with step unblocking, cancel returning length with the ledger conserved, machine half-open window with 45-min conditional buffer (12:30 conflicts, 12:45 adjacent passes), closed-interval feeder capacity, both OCC rules, PO/quote lazy expiry, and error codes `ERR_SPC_SAMPLING_INCOMPLETE`, `ERR_CAPABILITY_BELOW_MINIMUM`, `ERR_SEGREGATION_OF_DUTIES`, `ERR_PO_NOT_ACTIVE`, `ERR_PO_EXPIRED`, `ERR_TOOL_LIFE_EXPIRED`, `ERR_GAUGE_TYPE_MISMATCH`, and the auth/role/pagination family.

Two spots the sources left genuinely ambiguous, resolved toward the explicit PRD wording: (1) the fulfilment hop-2/hop-3 pair on a `BlanketPO` bumps `version` once, since §3.9 pins the increment on hop 2 only; (2) a gauge's lazy `IN_SERVICE -> CALIBRATION_DUE` re-evaluation does not bump `version`/`updated_at`, per §2.4's "advancing the clock does not itself rewrite any stored row".

## Step 5: Generate unit tests — 2026-08-30T05:56:00.000Z

Test infrastructure and suite generated. Summary:

## Files written

**`test_helpers/`** (1,892 lines)
| file | lines |
|---|---|
| `__init__.py` | 36 |
| `api_client.py` | 202 (one method per PRD endpoint, incl. the out-of-prefix `/_clock/set_current_utc`) |
| `api_errors.py` | 101 (43 error ids + HTTP map, registered with the framework) |
| `assertions.py` | 199 (per-entity assertions + the two conserved-ledger invariant checkers) |
| `constants.py` | 77 |
| `factories.py` | 240 |
| `fixtures.py` | 613 (single-step helpers + 8 composite scenarios) |
| `test_users.py` | 47 (opaque ShopPlanner/QualityManager constants; per-instance `make_machinist_headers` / `make_inspector_headers` for the two `entity_backed:Operator` roles) |
| `types.py` | 377 (`SpcSample` TypedDict deliberately omits `updated_at`/`version`) |

**`test_suite/`** (3,547 lines, 9 test files + `conftest.py`, 107 tests)
`test_01_quoting_and_pricing` 287 · `test_02_blanket_orders_and_kanban` 338 · `test_03_bar_stock_and_reservation` 301 · `test_04_scheduling_gates_and_occupancy` 518 · `test_05_spindle_and_secondary_routing` 384 · `test_06_tool_wear_and_machine_recovery` 466 · `test_07_gauges_and_spc_sampling` 423 · `test_08_disposition_and_fulfilment` 396 · `test_09_identity_roles_and_read_surface` 401 · `conftest.py` 33

## Coverage

- **Queue A (Difficulty): 42 tests** — all 21 instances covered by exactly 2 tests each.
- **Queue B (Corner): 65 tests** — all 65 non-stub instances covered by >=1 test. All 6 `excluded_because:` stubs verified to cross-reference a real difficulty instance; none translated.
- 107 tests, 107 `Design:` tags, zero untagged / dual-tagged / dangling tags. `pytest --collect-only` reports 107 collected; every file `py_compile`s; pyflakes clean; no `skip`/`skipif`/`xfail`; no scaffold references in comments or docstrings.
- An automated citation checker confirmed every docstring quotation survives a whitespace-normalised literal match against `workspace/PRD.md` (107/107).

## Instances skipped

**None.** All 21 difficulty instances and all 65 non-stub corner instances passed the PRD-first two-condition filter — every asserted rule, error id, threshold and cascade hop is stated verbatim in PRD §2–§3 and uniquely derivable.

## One design-index defect worked around (worth flagging)

`Corner/errors/accept_below_long_term_capability_minimum_is_rejected` is internally inconsistent: its `setup:` note says *"a characteristic with cpk_min 1.33"* but its `setup_api_calls` payload passes `cpk_min: 1.385`. With 1.385 the second subgroup (cpk 1.357) scores MARGINAL, driving the work order to `QUALITY_HOLD`, so the ACCEPT disposition would return `ERR_INVALID_STATE` from the generic state ladder and never reach the capability gate — a textbook ladder-mask. I used `cpk_min: 1.33` (the value the `setup:` note and all three asserted literals — `cpk_short_term_min 1.357`, `ppk_long_term_min 0.529`, `quality_status IN_SPC` — are consistent with), so the test actually exercises `ERR_CAPABILITY_BELOW_MINIMUM`.

All other pre-computed literals in both indices were re-derived independently and confirmed correct (quote pricing 289/305/284/315/541, rebate tiers 486900/500425, reclamation 1179 vs the 1180 sum-then-round trap, chip 3.504/2.861, coolant 0.817/1.342, cpk 1.385/1.615/1.292/1.357, ppk 1.917/1.717/0.529, bar reservation 6000->2 bars->7200 mm).

## Step 7: Run tests and iterate — 2026-08-30T06:04:00.000Z

Clean exit — all 8 parallel rounds green.

## Summary

**Iterations run:** 2

- **Iteration 1** — 8/8 rounds at 106/107. Exactly one failing test, identical in all 8 rounds (deterministic, not flaky): `test_02_blanket_orders_and_kanban.py::test_version_advances_by_exactly_one_on_each_mutation`, tripping `assert 2 == 1`.
- **Iteration 2** — 8/8 rounds at **107/107**.

**Tests deleted:** none. The single failure passed both STEP 1 sub-checks, so deletion was not the right disposition.

- STEP 1a (coverage): PRD §2.4 states verbatim *"`version`, an integer that begins at 1 on creation and increases by exactly one on every mutation of that row"*, and names `WorkOrder` explicitly among the entities carrying the full `id`/`created_at`/`updated_at`/`version` quartet.
- STEP 1b (unique derivability): PRD §3.6 says a successful start *"writes `machinist_operator_id` from `X-User-ID`"* and drives `machining_status` `SCHEDULED -> RUNNING`. That is unambiguously a mutation of the work-order row, so no PRD-faithful implementation can leave its `version` at 1 afterwards. Only one outcome is derivable: 2.

**Fixes applied to `test_helpers/`:** none — the fixture/factory/header layer was consistent with PRD throughout.

**Fixes applied to `test_suite/`:**
- `test_suite/test_02_blanket_orders_and_kanban.py`, `test_version_advances_by_exactly_one_on_each_mutation` — the assertion on the work order's own `version` after `start_work_order` expected `1`, contradicting the PRD §2.4 sentence quoted in the test's own docstring. Corrected to `2` (with a comment naming the two fields the start writes). The fix makes the test *more* faithful: it now actually exercises the "increases by exactly one on every mutation" rule for the work-order row, matching the 1 -> 2 -> 3 progression the same test already asserts for the machine row.

**Fixes applied to `implementation/`:** none. The implementation was already PRD-faithful on this rule (`start_work_order` in `workspace/implementation/routes_production.py` calls `touch(work_order)` after writing `machining_status` and `machinist_operator_id`); weakening it to satisfy the test would have violated the cardinal rule against downgrading a PRD-required behaviour.

**Deliverables:** the eight passing `results.{1..8}.json` files from the final sweep remain in `workspace/implementation/`.

Storage sanity re-verified: `workspace/implementation/core.py` holds all state in plain Python dicts (`Store.reset()` re-initialises every collection empty), with no SQLite file, no JSON dump, no `/tmp` cache and no startup seeding — so the `per-test-server` isolation wipes every byte of state between tests, which is consistent with the sweep's round-to-round stability.

**Orchestrator independent verification:** all 8 `results.*.json` re-read — each `passed=107 total=107 failed=0`. `test_suite/` still holds 107 test functions (42 `Design: Difficulty/` + 65 `Design: Corner/` tags), and contains zero `pytest.mark.skip` / `skipif` / `xfail` markers.

## Step 8: Finalize PRD — 2026-08-30T06:12:00.000Z

## Result: zero edits — `PRD_FINALIZED.md` is a byte-identical copy of `PRD.md`

`workspace/PRD_FINALIZED.md` created (md5 matches `PRD.md`; 385 lines each, 0.0% delta).

### Why no patch was warranted

The `<step_7_diff>` contains exactly one item, and it is a **test-side assertion error**, not a PRD silence or a PRD/impl mismatch: 0 implementation fixes, 0 test_helpers fixes, 0 deletions, 1 test_suite assertion corrected from `== 1` to `== 2`.

Step 7's STEP 1 conclusion was verified against the actual code rather than taken on trust:

1. **PRD already pins the rule.** §2.4 (line 82) states verbatim that `version` "begins at 1 on creation and increases by exactly one on every mutation of that row," and names `WorkOrder` explicitly in the list of entities carrying the full quartet.
2. **PRD already pins that a start is a mutation of that row.** §3.6: "A successful start writes `machinist_operator_id` from `X-User-ID`... on a restart it overwrites whatever operator was recorded before," alongside `machining_status` `SCHEDULED -> RUNNING`. Two fields written on the work-order row.
3. **Implementation matches.** `implementation/routes_production.py:162-164` writes `machining_status = "RUNNING"`, `machinist_operator_id = user_id`, then calls `touch(work_order)`; `implementation/core.py:212-216` shows `touch` unconditionally increments `version` when the key is present. So 1 -> 2 is the only outcome derivable from the PRD, and the implementation produces it.

The corrected test now agrees with both the PRD and the implementation. There is no place where the implementation made a behavioral choice the PRD left open, and no place where it diverged from the PRD, so per the HARD SCOPE rule every candidate edit would have been unsourced. Manufacturing prose here (e.g. restating in §3.6 that the start bumps the work order's own `version`) would only risk a new mismatch — it would imply the general §2.4 rule needs per-endpoint restatement, which the implementation's blanket `touch()` helper does not support, since `touch` is called on many rows the PRD never enumerates individually.

### Per-edit pre-edit search log

No edits committed. The one subject considered and rejected:

- **(a) Subject:** `WorkOrder.version` increment on `POST /swiss-shop/work-orders/{id}/start`.
- **(b) Impl paths enumerated/read:** `routes_production.py:137-178` (`start_work_order`, the Step 7 site); `routes_production.py:181-217+` (`complete_machining`, parallel work-order mutation, also `touch(work_order)`); `core.py:212-216` (`touch` — the single shared version-increment helper used by every mutation site, including machine, lot, release and blanket-PO cascades).
- **(c) Wording adjustment:** n/a — edit rejected before drafting, because §2.4 + §3.6 already uniquely determine the behavior and any §3.6-local restatement would sit inconsistently with the many other rows `touch()` advances that the PRD covers only via the §2.4 general rule.

## Step 9: Complete PRD — 2026-08-30T06:20:00.000Z

`workspace/PRD_COMPLETED.md` is written.

## Scale

- **Source:** `PRD_FINALIZED.md` — 385 lines, 79,078 chars (79,349 bytes)
- **Result:** `PRD_COMPLETED.md` — 385 lines, 83,454 chars (83,742 bytes), **delta +4,376 chars**
- 33 lines touched out of 385; §4 endpoint table and §5 error catalogue byte-identical; no sections added, no paragraphs added — every change is an in-paragraph insert or in-sentence revision.
- **30 ambiguity-pins, 3 mismatch-revisions.**

## Changes

**Mismatches (PRD described behavior impl does not exhibit)**

- §3.7 — revise — mismatch — PRD claimed a rejected inspection subgroup on a `RUNNING` machine carries the running work order to `INTERRUPTED`; impl's subgroup cascade only sets the machine `DOWN` (from any status) and clears `current_work_order_id` — it never interrupts a work order and never blocks a routing step — `routes_production.py:399-404` vs `services.py:55-74`
- §3.9 — revise — mismatch — "The note is recorded on the work order" was false; the `note` is validated as a string and discarded, no note field is ever written — `routes_production.py:264`
- §3.4 — revise — mismatch — §2.8's "response body is the primary resource named in the URL path" left quote-accept ambiguous; pinned that accept returns the newly minted BlanketPO in `data` with 201 — `routes_commerce.py:107-126`

**Ambiguity-pins**

- §2.1 — insert — a present-but-blank `X-User-ID` is also `ERR_UNAUTHENTICATED` — `guards.py:15-16`
- §2.3 — insert — `created_at` ties broken by ascending order of creation — `core.py:274-275`
- §2.3 — insert — non-numeric `limit`/`offset` text is `ERR_INVALID_REQUEST` — `guards.py:153-168`
- §2.4 — insert — `current_utc` echoes the supplied `to_iso8601` string verbatim — `routes_masters.py:22-24`
- §2.9 — insert — an empty string in a required string field is `ERR_INVALID_REQUEST` — `guards.py:55-56`
- §3.1 — insert — `badge_code` is at most 32 characters — `routes_masters.py:35`
- §3.2 — insert — the literal `QUARANTINE` is itself stored as the lot's `certificate_number` — `routes_masters.py:326-327`
- §3.3 — insert — the `expires_on` check precedes the 30-day re-evaluation; failing it leaves the quote in `PRICED` and never moves it to `EXPIRED` — `routes_commerce.py:95-101`
- §3.4 — insert — reinstate against a lapsed order is `ERR_INVALID_STATE` and does *not* move the order to `EXPIRED` — `routes_commerce.py:175-176`
- §3.4 — insert — short-close guard failures (and `FULFILLED`/`SHORT_CLOSED` origins) are `ERR_INVALID_STATE` — `routes_commerce.py:246-255`
- §3.5 — insert — `required_length_mm`, `bars_reserved` and `reserved_length_mm` are all persisted on the work order and appear in its representation — `routes_production.py:86-88`
- §3.5 — insert — the release's own `status` is never examined at schedule time — `routes_production.py:35, 67-70`
- §3.5 — insert — an illegal `machining_status` filter value is `ERR_INVALID_REQUEST` — `routes_production.py:118-120`
- §3.6 — insert — `qty_good`/`qty_scrap` are whole counts >= 0, `actual_run_seconds` >= 0 — `routes_production.py:185-187`
- §3.6 — insert — predecessor validity is checked ahead of the duplicate-`sequence` check — `routes_production.py:446-449`
- §3.6 — insert — routing-step advance precondition failures are `ERR_INVALID_STATE` — `routes_production.py:491-505`
- §3.7 — insert — `pieces_produced` is a whole count >= 0, `measured_drift_um` is a signed number; logging is declared only from `IN_SERVICE` (held or retired stations -> `ERR_INVALID_STATE`) — `routes_masters.py:386-391`
- §3.7 — insert — the offset log is not a stored resource; the response is the re-derived station, 200 OK — `routes_masters.py:402`
- §3.7 — insert — `retire` leaves the three accumulators standing (not reset); indexing an `IN_SERVICE` station is `ERR_INVALID_STATE` — `routes_masters.py:413-423`
- §3.7 — insert — reclamation settlement is declared from every machine status and never moves that status — `routes_masters.py:104-116`
- §3.8 — revise — gauge status derivation reordered to pin R&R-before-window and to add the fourth, previously unstated case (grr <= 10 with an already-lapsed `calibration_due_at` -> `CALIBRATION_DUE`) — `services.py:16-23`
- §3.8 — insert — the lazy `IN_SERVICE -> CALIBRATION_DUE` lapse bumps neither `version` nor `updated_at` — `services.py:9-13`
- §3.8 — insert — a calibration post at <= 10 % with a lapsed posted window lands in `CALIBRATION_DUE` — `services.py:21-23`
- §3.8 — insert — identical measurements give `sigma_within` 0, `cpk_short_term` null, and null is treated as satisfying `cpk_min` — `calc.py:176-192`
- §3.8 — insert — the long-term index is also null when every pooled reading is identical (zero overall sigma) — `calc.py:224-225`
- §3.8 — insert — `cpk_short_term_min` skips subgroups whose index is null — `calc.py:276, 284`
- §3.8 — insert — the no-transition rule extends to `ACCEPTED`/`REJECTED`, and the `REJECT` machine cascade fires only when a quality transition actually takes place — `routes_production.py:386-404`
- §3.9 — insert — the `note` is validated but never persisted, whichever decision was taken — `routes_production.py:264`
- §3.9 — insert — the four-hop fulfilment chain is skipped entirely when the release is not `IN_PRODUCTION`; the work order still reaches `ACCEPTED` — `routes_production.py:288-295`
- §3.9 — insert — same gating on the `REJECT` chain; the work order still reaches `REJECTED` — `routes_production.py:308-315`

## Coverage

Every line of all 9 implementation modules read end to end — `app.py` (51), `core.py` (279), `guards.py` (228), `calc.py` (378), `services.py` (129), `routes_masters.py` (425), `routes_commerce.py` (263), `routes_production.py` (507), plus `start.sh` and `requirements.txt`. None was sampled, grepped-for, or skimmed. All 51 endpoints, both work-order status dimensions and the other 8 state machines, all 12 calculations, the priority-10->98 ladder, all 43 error codes, the 4 roles and both OCC rules were checked against their governing PRD passage. `SCAFFOLD*.yaml` and `worklog.md` were not opened.

**Orchestrator independent verification:** `diff PRD_FINALIZED.md PRD_COMPLETED.md` reports exactly 66 changed lines (33 removed / 33 added), matching the reported 33 touched lines; all 8 `results.*.json` deliverables remain in `workspace/implementation/`.
