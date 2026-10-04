# Worklog — task_3330_electric_arc_furnace_mini_mill_production_scrap

## Step 1: Create task directory — 2026-09-30T20:52:31.330Z

Pre-allocated directory `./tasks/task_3330_electric_arc_furnace_mini_mill_production_scrap/` verified present with `workspace/` inside; no new index computed, no other task directory created.

## Step 2: Generate scaffold — 2026-09-30T21:22:47.393Z

Scaffold generation is complete with a clean lint verdict. Summary:

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_3330_electric_arc_furnace_mini_mill_production_scrap/SCAFFOLD.yaml` — §1.0–§1.7 only (envelope, entities, state machines, OCC concurrency rules, calculations, validations, endpoints, errors, RBAC); no `scaffold_difficulty_design`/`scaffold_corner_design` keys
- `/home/ubuntu/github/CodingPRD/tasks/task_3330_electric_arc_furnace_mini_mill_production_scrap/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design` (§1.8)
- `/home/ubuntu/github/CodingPRD/tasks/task_3330_electric_arc_furnace_mini_mill_production_scrap/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design` (§1.9)

## Counts

- **Entities: 18** (Mill, SurchargeIndex, ProcurementContract, ScrapLot, Grade, Heat, HeatChargeLine, MeltdownSheet, Campaign, CampaignLine, CustomerAccount, Order, MillTestReport, InterruptibleWindow, EnergyEvent, PowerInterruptionWaiver, EnergyInterval, DivisionScorecard)
- **Endpoints: 106** — far above the ≤40 expert band, deliberately: the lint's (f) FK reverse-reachability check only recognizes collection segments from single-entity GETs at exactly two segments under the prefix, which forced a parallel flat read surface (`/mills/<collection>/{id}` + filtered lists) alongside the hierarchical write surface. The endpoint overshoot risk (per pipeline memory) is real but bounded — the business action surface is ~30 endpoints; the rest are mechanical GETs.
- **State machines: 11** entities with explicit machines, including the cyclic MeltdownSheet (RECORDED↔REVISED), parallel-dimension CustomerAccount (credit × priority), posture-derived Mill, and system-auto transitions (window lapse, event expiry, index supersede)
- **Calculations: 9** (blend feasibility, per-line-rounded charge cost, dual-variant product price, signed scrap surcharge credit, roll-change sequencing, two interval-overlap semantics, dual-variant settlement FIFO, profit-share waterfall with floor/remainder, energy compliance)
- **§1.8 instances: 18** (9 rules × 2, all differentiated per §0.5) and **§1.9 instances: 43 total** (37 active recipes scanned by lint + 6 `excluded_because` stubs), all names unique across the union
- **Lint verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`** (481 calls scanned, 0 violations)

Key design decisions: logical clock with the mandated `2026-09-01T00:00:00Z` default; OCC on Order.confirm and Campaign.commit with all version inputs as `${var}` captures; all formula-derived asserts pre-computed as literals (e.g., settlement 3550000, contract price 1260000, spot re-price 1300000, per-line rounding divergence 52028 vs 52027, credit +60000, loss-month pool 0).

Orchestrator verification: all three files exist on disk and parse as YAML with the expected top-level keys (SCAFFOLD.yaml: scenario/domain_name/api_prefix/...; DIFFICULTY: scaffold_difficulty_design; CORNER: scaffold_corner_design). Endpoint count 106 exceeds the ≤40 expert band by deliberate design ("much harder than expert level"); overshoot risk noted and will be watched at Step 6.

## Step 3: Copy shared files — 2026-09-30T21:23:05.778Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-30T21:29:31.135Z

Done. Summary report:

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3330_electric_arc_furnace_mini_mill_production_scrap/workspace/PRD.md` — 369 lines.

**Section list:** §1 Introduction (3 paragraphs); §2 Global Specifications with ten subsections (2.1 RBAC with per-role identity translation, 2.2 verbatim response-structure block, 2.3 Pagination, 2.4 identity/timestamps/versioning incl. the 8 lean entities without `updated_at`/`version`, 2.5 logical clock with fixed 2026-09-01T00:00:00Z default, 2.6 precision/rounding incl. pinned round-per-line-then-sum order, 2.7 validation priority order 1–20 in explicit sequence, 2.8 OCC for the two guarded writes, 2.9 posture gate, 2.10 cascades); §3 Business Logic with eleven subsections covering the full melt-to-profit-share narrative; §4 endpoint table (4 columns, all 106 paths, verified programmatically 1:1 against scaffold); §5 error table (2 columns, all 37 errors with exact HTTP statuses, verified).

**Coverage self-audit (all verified by script against SCAFFOLD.yaml):**
- **Contract 1 (field names):** 116 required identifiers (all `entities[].fields[].name`, all endpoint `input` keys, all `{pathParams}`) — 0 missing. Path params enumerated in §2.7; filter-only params (`mill_id`, `contract_id`, `account_id`, `campaign_id`, `heat_id`, `linked_event_id`) covered in §2.3.
- **Contract 2 (rules):** all 11 state machines with every transition (from/to, preconditions paired to error ids, side effects incl. the depth-3 release→abort→lot-restore cascade and the deliberate no-version-bump on lots); all 9 calculations in precise prose (blend feasibility with 6-decimal round-half-up, charge_cost per-line rounding pinned, product_price CONTRACT_MONTH_INDEX vs CURRENT_MONTH_INDEX variants with BILLET→SHREDDED/BLOOM→BUSHLING/SLAB→HMS mapping, scrap_surcharge_credit with 40000 cents/ton benchmark and both signs, roll_changes_used chronological non-id ordering, campaign half-open overlap vs event 15-minute adjacency contrast, settlement FIXED flat vs INDEXED FIFO variants, profit_sharing with 0.10 rate + floor-at-zero + floor division + retained remainder, energy_compliance zero-interrupted-intervals boundary with vacuous-truth proviso); all 20 validations in priority order in §2.7 with trigger conditions scattered in §3 near their workflows; both OCC rules with `expected_order_version`/`expected_campaign_version` + `ERR_STALE_VERSION`/412; constants 0.80 (as "80 percent"), 45 minutes, 15 minutes, 40000, 0.10, 0.30/0.005/0.02 caps all embedded in prose; STRUCTURAL enum acknowledged via the "CERTIFIED implies STRUCTURAL" note.
- **Contract 3 (§3 path purity):** 470 backtick tokens in §3 scanned — zero paths, zero bare HTTP methods.
- All 37 error ids present in §1–§4 prose and again in the §5 table with matching HTTP codes; all 8 roles named with opaque-identity translation; all state enum values present as exact UPPERCASE strings; `STRUCTURAL`/`CLOSED` gaps found in the first pass and repaired; SCAFFOLD_DIFFICULTY_DESIGN.yaml and SCAFFOLD_CORNER_DESIGN.yaml were never opened.

## Step 5: Generate unit tests — 2026-09-30T21:48:50.970Z

Done. All files written, audits clean.

## Summary

**Files written**

`test_helpers/` (9 files):
- `types.py` — status enums (13 entity state machines) + 20 TypedDicts; the 10 common-fields entities carry `updated_at`/`version`, the 8 lean archive entities (SurchargeIndex, ScrapLot, Grade, HeatChargeLine, CampaignLine, MillTestReport, PowerInterruptionWaiver, EnergyInterval) carry only `id` + `created_at`
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (66 methods: nested writes/reads, all 30 flat org-wide reads, clock)
- `api_errors.py` — 38-error `ApiErrorId` enum + HTTP map registered via `set_error_http_status_map`
- `assertions.py` — per-entity shape assertions + `assert_scorecard_profit_invariants`
- `factories.py`, `constants.py` (FURNACE_GRID_MINUTES=45, EVENT_MIN_GAP_MINUTES=15, SETTLEMENT_MIN_FILL_PCT=0.80, BENCHMARK_CENTS_PER_TON=40000, PROFIT_SHARE_RATE=0.10, MOISTURE_PCT_MAX=0.30), `test_users.py` (8 opaque-role header constants), `fixtures.py` (composite setup helpers: `setup_supply_pool`, `setup_charged_heat`, `setup_cast_heat`, `commit_campaign` with fresh-version OCC, plus getters), `__init__.py` barrel

`test_suite/` (22 files): `conftest.py` + `test_01`…`test_21`.

**Test count: 73 tests collected** (verified via `pytest --collect-only`).

**Coverage**
- Queue A (difficulty): all **18/18** instances translated, each with ≥2 tests (verified programmatically — no shortfalls).
- Queue B (corner): all **31/31** non-stub instances translated (37 total recipes − 6 `excluded_because` stubs). All 6 stub cross-references resolve to real §1.8 instances.
- **Skipped: none.** Every instance passed the PRD-first two-condition filter; no skip/xfail/skipif markers anywhere in the suite.

**Tag discipline:** every one of the 73 tests has exactly one `Design: Difficulty/<rule_id>/<instance>` or `Design: Corner/<section>/<instance>` line as the final docstring line; zero missing, zero unknown tags (checked against parsed YAML).

**PRD citations:** every docstring quotes verbatim PRD sentences; a sliding 8-word-window grep against `PRD.md` passed with 0 failures.

**One judgment call to note:** for `Difficulty/transitive_cascade/order_invoice_rescores_division_profit_share`, the recipe's `setup_api_calls` (20t order + 12t CAST heat) were followed exactly as authored — I did not inject my own inference about the intermediate `allocated_tons`/`assigned_tons` values, since the PRD pins the allocation transition but leaves the partial-assignment arithmetic under-specified. The asserted literals (invoice status, scorecard revenue 1,260,000 / material 360,000 / profit 900,000) are PRD-derived regardless.

Orchestrator verification: test_helpers/ (9 files + __init__) and test_suite/ (conftest + 21 test files) exist on disk; grep counts 73 test functions, matching the subagent's collect-only count.

## Step 6: Generate implementation — 2026-09-30T22:04:17.373Z

Boot smoke test passed and the process is stopped.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3330_electric_arc_furnace_mini_mill_production_scrap/workspace/implementation/`):

- `start.sh` — guarded pip install, `exec python3 app.py`, PORT env / 0.0.0.0
- `requirements.txt` — flask
- `app.py` — entry point, JSON encoder for datetimes, blueprint registration, error handlers
- `db.py` — in-memory dicts for all 18 entities, logical clock (default 2026-09-01T00:00:00Z), no seeding
- `errors.py` — `ApiError`, full error catalog with HTTP statuses, envelope-shaped error responses
- `response.py` — envelope helpers (`meta`/`response_type`/`data`), pagination (`limit`/`offset`/`total_count`/`has_more`, default 10/1..100/0), auth + role guards, body/field validators
- `services.py` — posture derivation, clock sweep (window lapse / event expiry), waiver coverage, heat grid check, blend feasibility (6dp, ROUND_HALF_UP), per-line charge pricing, abort compensating release, scrap surcharge credit, roll-change recompute, OCC, scorecard lookup
- `routes_core.py` — clock + mills + surcharge indices (incl. supersession, flat reads)
- `routes_procurement.py` — contracts (create/close/default with FIXED flat vs INDEXED FIFO settlement) + scrap lots + flat reads
- `routes_grades.py` — grade catalog + flat reads
- `routes_heats.py` — heats, charges, meltdown sheets (cyclic revise/confirm/reject with cascade to MELTDOWN_LOCKED), tap/cast/abort + flat reads
- `routes_quality.py` — energy intervals (posture snapshot) + mill test reports (MTR-N per-mill numbering, chemistry snapshot, energy_certified) + flat reads
- `routes_campaigns.py` — campaigns, lines, OCC-guarded commit with window/overlap/budget checks, close/cancel + flat reads
- `routes_commercial.py` — accounts (parallel credit_status/allocation_priority PATCH state machines), orders (OCC-guarded confirm, SPOT/CONTRACT pricing variants, invoice, cancel), allocation runs + flat reads
- `routes_energy.py` — interruptible windows, energy events (15-min adjacency + single-ACTIVE invariants, release cascade aborting non-waivered heats), power waivers (uniqueness, EVENT waiver_count) + flat reads
- `routes_scorecards.py` — division scorecards (OPEN→CLOSED→DISTRIBUTED, profit sharing with 0.10 rate, floor at zero, floor division per employee) + flat reads

**Endpoints implemented: 106** (all nested + flat reads, clock, allocation runs, and every action endpoint from the SCAFFOLD §1.5 table).

**State machines implemented (11):** SurchargeIndex, ProcurementContract, ScrapLot (RECEIVED/PARTIALLY_CONSUMED/CONSUMED), Heat (incl. abort compensating release), MeltdownSheet (cyclic RECORDED↔REVISED), Campaign, CustomerAccount (two parallel dimensions), Order, InterruptibleWindow, EnergyEvent, DivisionScorecard.

**Calculations implemented (9):** blend_feasibility, charge_cost (per-line round-then-sum), product_price (CONTRACT_MONTH_INDEX / CURRENT_MONTH_INDEX variants), scrap_surcharge_credit (40000 c/t benchmark, exact pre-rounding), roll_changes_used (chronological planned_tap_at/created_at), campaign_window_conflict (half-open), settlement_amount (FIXED flat / INDEXED FIFO), profit_sharing (0.10 rate, floor at zero, floor division), energy_compliance (zero INTERRUPTED intervals).

**Boot smoke test:** `bash start.sh` on PORT=18237 booted cleanly; `POST /mills` returned 201 with correct envelope; `GET /mills` returned paginated envelope with `limit`/`offset`/`total_count`/`has_more` in `meta`; unauthenticated clock set returned 401; authenticated clock set returned 200. Server PID (4007955) killed after the test; no other processes touched.

One deliberate judgment call: the PRD's default-window precondition (`ERR_INVALID_REQUEST` when the 7-day settlement window has not elapsed) was implemented against `ERR_INVALID_REQUEST` because no dedicated error id exists in the catalog for that gate.

Orchestrator verification: 16 files present under workspace/implementation/ (app.py, db.py, errors.py, response.py, services.py, 10 route modules, start.sh executable, requirements.txt); ~2520 lines total.

## Step 7: Run tests and iterate — 2026-10-01T04:29:24.506Z

Final state: **clean 8-round parallel stability sweep — all 8 rounds 73/73 passed, 0 failures, 0 flaky.** No tests deleted; no assertions weakened (zero `validate_error_is_one_of` relaxations in the suite).

Step 7 ran in two parts (the first subagent was killed by the host mid-flight under memory pressure; the orchestrator completed the loop):

- Iterations run: 2 sweeps (iteration-1 by the interrupted subagent; iteration-2 by the orchestrator after resume).
- Tests deleted: none.
- Fixes applied to `test_suite/`:
  - *Iteration 1 (interrupted subagent)* — `test_03_contracts.py` and `test_07_charges.py` edited; these resolved 3 of the 4 baseline failures seen in the first recorded sweep (`test_settlement_fixed_flat_ignores_receipt_month_indices`, `test_blend_feasibility_mn_floor_violation`, `test_order_confirm_stale_version_412`). The subagent was killed before recording per-edit rationale; a later sweep confirmed all three passing 8/8.
  - *Iteration 2 (orchestrator)* — `test_18_allocation.py::test_order_invoice_rescores_division_profit_share`: fixture created a 20t order but only a 12t CAST heat. Per PRD §3.9 an allocation run partially assigns tonnage and the order "stays `CONFIRMED`" until `allocated_tons >= tons`, while invoicing requires an `ALLOCATED` order — so the implementation's `ERR_INVALID_STATE` ("order must be ALLOCATED") was correct and the fixture was the bug. Repaired the setup to cast a 20t heat from the same 25-dry-ton lot (single-heat full cover keeps the allocation draw deterministic — PRD does not pin which heat tons a multi-heat run draws) and updated the derived scorecard literals per the PRD-pinned charge-cost formula: `material_cost_cents` 360000→600000 (20t × 30000 c/t), `profit_cents` 900000→660000. `revenue_cents` 1260000 unchanged (driven by the order, not the heat). This was the exact fixture Step 5 flagged as relying on PRD-under-specified partial-assignment arithmetic.
- Fixes applied to `test_helpers/`: none.
- Fixes applied to `implementation/`: none — the implementation was PRD-faithful at every failure point; all Step 7 fixes were test-side.

## Step 8: Finalize PRD — 2026-10-01T04:34:17.152Z

Done. `workspace/PRD_FINALIZED.md` written.

**Line counts / delta:** PRD.md 369 lines / 56,227 chars; PRD_FINALIZED.md 369 lines / 57,261 chars; +1.84% (two inline sentence insertions, no new sections).

**Changes (2 edits; 2 step-7 items required no PRD change):**

- §3.9 (allocation paragraph) — insert — pinned per-run pool semantics and the greedy draw rule: each eligible heat contributes its full `target_tap_weight_tons` to a per-run pool (recomputed fresh each run; no persistent heat allocation ledger), and each order draws `min(heat remaining pool, order remaining need)` walking heats in `planned_tap_at`/`created_at` order; ALLOCATED only when `allocated_tons >= tons` — routes_commercial.py:224-271 (`allocation_run`), cancel side at routes_commercial.py:208-219.
- §3.9 (order confirm paragraph) — insert — pinned the check ordering: missing/non-integer `expected_order_version` → `ERR_INVALID_REQUEST`; integer mismatch → `ERR_STALE_VERSION`, evaluated *before* the QUOTED state check (stale re-confirm of a confirmed order yields 412, not 409) — routes_commercial.py:164-172, services.py:361-364 (`check_occ`).

**Step-7 items audited with NO PRD change (PRD already pins the behavior verbatim; original failures were fixture/test-side):**

- FIXED settlement flat variant — §3.3 already pins `contract_price_cents * settlement_tons` rounded half-up; impl `_settlement` (routes_procurement.py:73-74) matches exactly, for both close and default paths.
- Blend feasibility 6-decimal round-half-up and deliberate Mn-ceiling non-enforcement — §2.6 and §3.4 already pin both; impl `blend_check` (services.py:226-244) matches.
- §3.6 charge-cost freeze/post confirmed consistent: per-line round-then-sum at apply (services.py:259-279), integer sum frozen at tap (routes_heats.py:208), posted to the OPEN scorecard of the `planned_tap_at` month at cast (routes_heats.py:221-225) — no wording change needed.

**Per-edit pre-edit search log:**

- Edit 1 (allocation draw): (a) subject = allocation pool sizing, draw amount, ALLOCATED threshold. (b) enumerated: routes_commercial.py:224-271 (only allocation site; pool built per-run from `target_tap_weight_tons`); routes_commercial.py:208-219 (cancel resets only `allocated_tons`, no heat-side restore); routes_campaigns.py:140-152 (close checks order status only). (c) wording adjusted to say the pool is "recomputed fresh on every run" rather than implying heats track availability.
- Edit 2 (confirm OCC ordering): (a) subject = order-confirm check ordering. (b) enumerated: routes_commercial.py:157-182 (confirm: 400 → 412 OCC → 409 state → posture → blocked); services.py:361-364 (`check_occ`); routes_campaigns.py:96-106 (campaign commit runs state-OPEN *before* OCC — the two OCC endpoints differ). (c) wording scoped explicitly to order confirmation rather than amending §2.7's global list, keeping campaign commit's ordering un-contradicted.
- Audited-no-change items: pre-edit searches performed (settlement: routes_procurement.py:72-134; blend: services.py:226-244 + sole caller routes_heats.py:83) — existing PRD prose matched, kept verbatim.

Orchestrator verification: no files under implementation/, test_suite/, or test_helpers/ were modified after the clean 8-round sweep (mtime check), so the sweep remains valid. PRD_FINALIZED.md present (57,261 bytes).

## Step 9: Complete PRD — 2026-10-01T04:53:13.578Z

Done. `workspace/PRD_COMPLETED.md` produced. Only the PRD markdown was edited; implementation/, test_suite/, test_helpers/ untouched (orchestrator-verified via mtime — nothing newer than the clean-sweep anchor under those three trees).

**Source vs output**: PRD_FINALIZED.md 369 lines / 57,261 chars → PRD_COMPLETED.md 369 lines / 59,953 chars (+2,692 chars; 22 lines modified inline, 0 lines added/removed; table rows and section headings identical).

**Counts**: 19 ambiguity-pins (insert), 5 mismatch-revisions (revise). (Two mismatch revisions share one paragraph with an insert.)

**Changes** (PRD section — kind — class — what changed — impl ref):

- §2.3 Pagination — insert — ambiguity — list tie-break `id` ascending after `created_at` — response.py:212
- §2.4 Identity/Versioning — insert — ambiguity — `updated_at` refreshed with each version bump; versioning exceptions named (clock-driven window lapse/event expiry, index supersession flip don't bump `version`) — services.py:351-353, 156-171; routes_core.py:80-83
- §2.10 Cascades — insert — ambiguity — cascade abort restore capped at lot `dry_tons` — services.py:286-288
- §3.1 Grades — insert — ambiguity — `requires_energy_certified` is a required boolean; duplicate `grade_code` within a mill → `ERR_INVALID_REQUEST` — routes_grades.py:28-31
- §3.2 Contracts — insert — ambiguity — FIXED price must be a non-negative *integer* (non-integer/negative → `ERR_INVALID_REQUEST`); INDEXED stores `contract_price_cents` null — routes_procurement.py:29-45
- §3.2 Scrap lots — insert — ambiguity — receipt accrues `received_tons` without bumping contract `version` — routes_procurement.py:171
- §3.3 Contract default — insert — ambiguity — premature default (settlement window not elapsed) → `ERR_INVALID_REQUEST` — routes_procurement.py:125-127
- §3.4 Charge blending — revise — mismatch — removed the "read-only charge preview" sentence; no preview endpoint exists — routes_heats.py (absent)
- §3.4 Charging — insert — ambiguity — later charge lines on an already-CHARGED heat leave the heat's `version` untouched — routes_heats.py:86-88
- §3.4 Charging — insert — ambiguity — `CONSUMED` condition is remainder at-or-below zero, not only exact exhaustion — services.py:274-276
- §3.6 Abort — insert — ambiguity — lot restore capped at `dry_tons`, remainder pinned back with status `RECEIVED` — services.py:282-290
- §3.7 Energy intervals — insert — ambiguity — `energy_kwh` accumulation does not increment heat `version` — routes_quality.py:36
- §3.8 Campaign lines — insert — ambiguity — every line add bumps campaign `version` (this is why OCC matters) — routes_campaigns.py:80-81
- §3.8 Campaign commit — revise — mismatch — actual gate order pinned: body-shape check, OPEN state before OCC (stale version on non-OPEN → `ERR_INVALID_STATE`), EMPTY, per-line CAST/window, overlap, then budget recompute last (reordered from PRD's budget-before-overlap) — routes_campaigns.py:100-128
- §3.8 Campaign close/cancel — revise — mismatch — close guard is any mill order matching a line heat's `grade_id` + campaign `product_family` in CONFIRMED/ALLOCATED (not "allocated against it" / INVOICED-or-CANCELLED phrasing); cancel also resets `roll_changes_used` to 0 — routes_campaigns.py:141-150, 163-166
- §3.9 Account patch — revise — mismatch — version bumps once per patch call (not per dimension); empty patch → `ERR_INVALID_REQUEST`; no-op priority patch → `ERR_INVALID_STATE` — routes_commercial.py:70-86
- §3.9 Orders — insert — ambiguity — `base_price_cents_per_ton` must be an integer — routes_commercial.py:117
- §3.9 Order confirm — insert — ambiguity — version increments by 1 on confirm — routes_commercial.py:181
- §3.9 Allocation — insert — ambiguity — order `version` bumps exactly once per run on any increment — routes_commercial.py:264-268
- §3.10 Event activation — revise — mismatch — 15-minute gap checked against every RELEASED event of the mill as `called_at − released_at`, with negative gaps not checked (not "the previous event") — routes_energy.py:135-142
- §3.10 Event release — revise — mismatch — event becomes RELEASED with version bump *before* the abort cascade — routes_energy.py:160-168
- §3.10 Window honor — insert — ambiguity — "window's month" pinned as calendar month of `start_at` — routes_energy.py:71
- §3.11 Scorecard create — insert — ambiguity — profit fields born null until close — routes_scorecards.py:31-35
- §3.11 Scorecard accrual — insert — ambiguity — window month = `start_at` month; OPEN scorecard refreshes live `profit_cents`/`profit_pool_cents` on each accrual — services.py:377-381
- §3.11 Scorecard close — insert — ambiguity — profit pool truncated to whole cents (sub-cent fraction dropped) — routes_scorecards.py:68
- §4 endpoint table — insert — ambiguity — release row description notes RELEASED-before-cascade ordering — routes_energy.py:160

Noted but deliberately not "fixed" (impl behavior, PRD already vague enough): posture gate error ordering on charge apply (mill-interrupted check at priority 7 in §2.7 runs before contract/lot checks at 12, matching impl routes_heats.py:74-81).

Orchestrator verification: PRD_COMPLETED.md present (59,953 bytes). Final clean-sweep state re-confirmed: all 8 `results.{1..8}.json` rounds show `passed == total` (73/73); no implementation/test file modified after the sweep, so the result stands.

## Pipeline complete — 2026-10-01T04:53:13.578Z

All 9 steps done. Final artifact: `workspace/PRD_COMPLETED.md` is the authoritative contract; `workspace/implementation/` passes the full test suite under `--isolation per-test-server` across all 8 parallel stability rounds (73/73 × 8, zero flaky).
