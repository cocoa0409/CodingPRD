# Worklog — task_3335_engineered_wood_products_distribution_builder_direct_supply

## Step 1: Create task directory — 2026-09-30T21:30:45.000Z

Pre-allocated task directory `./tasks/task_3335_engineered_wood_products_distribution_builder_direct_supply/` confirmed to exist with `workspace/` inside. No new index computed; using exactly this path per invocation instructions.

## Step 2: Generate scaffold — 2026-09-30T22:02:30.000Z

Scaffold generation complete. All three artifacts written and the lint verdict is clean.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3335_engineered_wood_products_distribution_builder_direct_supply/`):
- `SCAFFOLD.yaml` (1219 lines) — §1.0–§1.7 only; no difficulty/corner keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1409 lines) — single top-level `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (1664 lines) — single top-level `scaffold_corner_design`

**Counts:**
- Entities: 12 (MillCapacityWeek, Product, PriceIndexEntry, Branch, InventoryLot, Builder, BuilderJob, TakeoffRequest, SalesOrder, Delivery, TruckShift, LienFiling)
- State machines: 7 (cyclic shapes on TakeoffRequest, Delivery, InventoryLot, Builder)
- Endpoints: 39 (under the >40 overshoot threshold)
- Calculations: 8 (incl. FIFO-vs-weighted-average valuation, committed-vs-settled exposure, component-wise delivery-fee rounding, capacity waterfall, lien deadline)
- Validations: 9 priority layers; Errors: 24; Roles: 7 (segregation-of-duties model, BuilderContact is `entity_backed:Builder`)
- §1.8: 18 instances (9 rules × 2, all minimums met, differentiating clauses honored: dual variants on different entity domains, combinatorial modes (a) and (b), different cascade triggers, different error-category pairs, different boundary metrics/endpoints, different entity pairs, different interval semantics, different conserved quantities)
- §1.9: 33 active corner instances + 2 `excluded_because` stubs across 8 sections (entities, state_machines, calculations, validations, errors, rbac, cross_cutting_layers, consistency_model)

**Lint verdict (verbatim, final run):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (568 calls scanned.) Two fix rounds were needed: one hedged assert in a priority-conflict instance was restructured into a genuine state-vs-fiscal dual failure (DELIVERED-terminal order + suspended builder), and three FK sub-resource paths were renamed to the lint-required `{id}` placeholder plus pagination params added to `GET /sales-orders`.

All numeric asserts are pre-computed literals (e.g., valuation FIFO 600000 vs WAVG 550000; delivery fee 17257 vs naive 17256; credit boundary at exactly 5000000; lien deadline 2026-09-10 + 90d = 2026-12-09). No forbidden concurrency vocabulary; all `expected_*_version` payloads reference `${var}` captures.

## Step 3: Copy shared files — 2026-09-30T22:03:30.000Z

Copied `./INSTRUCTION.md` to `tasks/task_3335_engineered_wood_products_distribution_builder_direct_supply/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-10-01T04:08:30.000Z

(Completed in the prior session at 2026-09-30T22:09; verified complete on disk after the host restart — all 5 sections present, 265 lines, error catalogue table ends cleanly with trailing newline.)

## Summary

**PRD generated:** `/home/ubuntu/github/CodingPRD/tasks/task_3335_engineered_wood_products_distribution_builder_direct_supply/workspace/PRD.md` — 265 lines.

**Section list:**
- §1 Introduction (3 paragraphs — business context angle)
- §2 Global Specifications & System-Wide Principles
  - 2.1 User and Role-Based Access Control (headers, 7 roles with identity semantics — `BuilderContact` entity-backed to `Builder.id`, other six opaque)
  - 2.2 API Response Structure (fixed verbatim block)
  - 2.3 Pagination (limit default 10/min 1/max 100, offset 0, `created_at` ascending, meta fields)
  - 2.4 Resource Identity, Timestamps, and the Logical Clock (UUID ids, ISO 8601 3-digit timestamps, startup clock 2026-09-01T00:00:00Z, clock-driving fields)
  - 2.5 Nested Resource Retrieval and Identifier Existence (left-to-right, `ERR_NOT_FOUND`, `ERR_INVALID_REQUEST`)
  - 2.6 Monetary Precision and Rounding (integer cents, round-half-up per line/per component, `fill_rate_pct` 4dp)
  - 2.7 Optimistic Concurrency Control (both rules: `expected_builder_version` on order create, `expected_capacity_week_version` on allocate, both `ERR_STALE_VERSION` 412)
  - 2.8 Validation Priority Ordering (the nine-tier priority list)
  - 2.9 Catalog Enumerations (families, species, placement difficulty, pricing modes, price bases)
- §3 Business Logic & Workflows — 8 subsections: mill-week waterfall, catalog/price index, branch inventory + dual valuation, builder credit lifecycle (incl. SUSPEND cascade), jobs + take-off quote cycle (14-day strict expiry), order entry + confirmation gauntlet (tier discounts 3%/5% at 50/100 mbf, atomic FIFO), fleet operations (45-minute buffer, fee 7501/4003 with multipliers 1.0/1.25/1.5, component-wise rounding), lien rights (90-day deadline, pinned check order)
- §4 Endpoint Definitions (39 endpoints, 4-column table)
- §5 Error Code Catalogue (24 errors, 2-column table)

**Hard-contract results:**
- Contract 1 (field-name coverage): PASS — 0 missing across entities, request bodies, query params
- Contract 2 (rule coverage): PASS — priorities, both OCC rules, all 8 calculations with pinned constants and rounding order, all state transitions with preconditions/side effects, all defaults pinned (max_drops 4, placement STANDARD, internal_grants empty, fill_rate_pct 0 until close, etc.), all 24 error IDs with trigger conditions in prose
- Contract 3 (§3 path purity): PASS — 425 tokens scanned, 0 violations

**One scaffold inconsistency handled:** the Delivery state machine names `ERR_TRUCK_SHIFT_CLOSED`, but the error catalog (§1.6) omits it; per validation-priority tier 5 the closed-shift schedule rejection was rendered as `ERR_INVALID_STATE`, keeping the PRD within the catalog's 24 codes.

## Step 5: Generate unit tests — 2026-10-01T04:30:31.000Z

Generation complete. Summary:

## Files written

**test_helpers/** (9 files) under `/home/ubuntu/github/CodingPRD/tasks/task_3335_engineered_wood_products_distribution_builder_direct_supply/test_helpers/`:
- `types.py` — 12 entity TypedDicts, 11 status/enum classes, role enum
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (30 endpoint methods)
- `api_errors.py` — `ApiErrorId` (24 codes) + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions + `assert_lot_quantity_conservation`
- `constants.py` — tier thresholds, fee components/multipliers, 45-min buffer, 14-day quote validity, 90-day lien window, startup clock literal
- `factories.py` — payload factories for every creatable entity
- `test_users.py` — shared headers for the 6 opaque roles + mandatory `make_builder_contact_headers(builder_id)` for the entity-backed role
- `fixtures.py` — composite setups (active builder+job, confirmed order, scheduled/delivered delivery, quoted takeoff, capacity-week allocate, lien filing)
- `__init__.py` — barrel export

**test_suite/** (13 files: `conftest.py` + 12 test files) under `/home/ubuntu/github/CodingPRD/tasks/task_3335_engineered_wood_products_distribution_builder_direct_supply/test_suite/`.

## Coverage

- **Total tests: 69.** Queue A (Difficulty): 18/18 instances, all with ≥2 tests each. Queue B (Corner): 33/33 non-stub instances, each with ≥1 test; both `excluded_because` stubs (`valuation_variants_covered_by_difficulty`, `exposure_variants_covered_by_difficulty`) verified — their difficulty-instance pointers resolve and own the assertions; no tests emitted for them.
- **Skipped instances: 0** — every non-stub instance passed the PRD-first two-condition filter (all rules have verbatim PRD coverage in §2–§3 and pin unique outcomes). All design-index fixture dates are reachable from the 2026-09-01T00:00:00Z startup clock via `POST /_clock/set_current_utc`; no clock-unreachable recipes.

## Verification performed

- All 22 files compile (`py_compile`), `test_helpers` imports cleanly.
- Every one of the 69 test docstrings ends with exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line, and every tag resolves to a real instance in the source YAML (programmatic cross-check: 0 unresolved, no under-covered instance).
- Verbatim-citation sweep: every double-quoted or backtick-quoted docstring span ≥30 chars survives a normalized literal match against PRD.md (0 failures after fixing two quote-boundary truncations).
- No `pytest.mark.skip`/`skipif`/`xfail` markers; no "scaffold"/table references in generated code.

## Step 6: Generate implementation — 2026-10-01T04:45:00.000Z

Clean boot verified. Summary:

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_3335_engineered_wood_products_distribution_builder_direct_supply/workspace/implementation/`:

| File | Lines |
|---|---|
| `start.sh` | 7 |
| `requirements.txt` | 1 |
| `app.py` | 48 |
| `db.py` | 29 |
| `errors.py` | 105 |
| `response.py` | 68 |
| `helpers.py` | 115 |
| `services/calc.py` | 145 |
| `services/order.py` | 265 |
| `routes/capacity.py` | 80 |
| `routes/catalog.py` | 140 |
| `routes/builders.py` | 143 |
| `routes/takeoffs.py` | 170 |
| `routes/orders.py` | 163 |
| `routes/deliveries.py` | 185 |
| `routes/liens.py` | 85 |
| **Total** | **1749** |

## Endpoints implemented: 39 / 39

1 clock, 3 capacity-week, 2 product, 1 price-index, 3 branch (incl. valuation + lot receipt), 2 inventory-lot, 3 builder (incl. credit-review + exposure), 3 job (create + 2 list/get), 6 takeoff (create + get + list + submit-design + revise + accept), 6 sales-order (create + get + list + confirm + cancel + deliveries), 5 delivery (get + list + schedule + complete + truck-shift create/get), 3 lien (file + release + list).

## Contract verification

- `start.sh` reads `$PORT` (default 10000 via `os.environ.get("PORT", "10000")` in `app.py`), binds `0.0.0.0`, runs in foreground via `exec python3 app.py`, and guards `pip install` with `if ! python3 -c "import flask"` so per-test reboots don't re-install.
- Storage is in-memory dicts only — no files, no SQLite, no /tmp cache. Logical clock defaults to exactly `2026-09-01T00:00:00Z` at boot, advanced only via `POST /_clock/set_current_utc`.
- No entity seeding at startup; all state constructed through declared endpoints.
- Real boot test: launched on a free port, `GET /inventory-lots` returned HTTP 200 with the correct `meta/response_type/data` envelope (with `limit/offset/total_count/has_more`), then killed exactly that PID.
- End-to-end smoke test: builder onboarding → credit APPROVE → product → branch → lot receipt → job → direct sales order with OCC → confirm (FIXED line, 60 mbf × 60000 × 0.97 = 3,492,000 cents, three-percent tier) → delivery request → truck shift → schedule (fee 7501) → complete → order cascades to DELIVERED.

(Orchestrator note: first spawn attempt errored with model_not_found for the inherited model; respawned with model=sonnet. Files verified on disk: 1748 lines across 16 .py/sh files, Blueprint-style route registration.)

## Step 7: Run tests and iterate — 2026-10-01T05:20:00.000Z

All 8 rounds pass 69/69. Clean sweep achieved.

## Summary

- **Iterations run:** 2 (initial sweep + post-fix confirmation sweep; both 8 parallel rounds each).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `test_suite/`:** none.

- **Fixes applied to `implementation/`:** 1 fix in `/home/ubuntu/github/CodingPRD/tasks/task_3335_engineered_wood_products_distribution_builder_direct_supply/workspace/implementation/routes/deliveries.py` (line 129, `schedule_delivery`): changed the 45-minute buffer overlap predicate from `d_start < o_end + BUFFER or o_start < d_end + BUFFER` to `d_start < o_end + BUFFER and o_start < d_end + BUFFER`. The `or` form made the second clause ("an existing delivery's window starts before the new window's end plus 45 minutes") almost always true for any chronologically later delivery, so ERR_TRUCK_SHIFT_OVERLAP fired even with gaps ≥ 45 minutes and pre-empted the drop-limit check.

**Diagnosis trace (STEP 1/2/3):** PRD §3.7 verbatim covers the rule ("No other SCHEDULED delivery on the same shift may sit within a 45-minute buffer of the new window..."). The failing tests were faithful: the exactly-45-minutes test encodes the strict-inequality boundary, and the drop-limit test (windows 4 hours apart) requires overlap to not fire. The literal `or` reading of the PRD sentence is self-defeating (it would forbid nearly all sequential drops on a shift, contradicting `max_drops`/`booked_drops` semantics), so the coherent buffered-interval-overlap (AND) semantics is uniquely derivable; the implementation was the sole artifact at fault.

**Result:** 8/8 rounds at 69/69 passed. (Orchestrator-verified on disk: all 8 results.*.json show passed==total==69; deliveries.py:129 carries the `and` predicate.)

## Step 8: Finalize PRD — 2026-10-01T05:35:00.000Z

Subagent summary (verbatim):

**Line counts:** PRD.md 265 lines, PRD_FINALIZED.md 265 lines (0% line-count delta; one sentence rewritten in place on line 178).

**Changes (1):**
- PRD §3.7 — revise — the 45-minute buffer overlap sentence rewritten to pin buffered-interval-overlap semantics; `ERR_TRUCK_SHIFT_OVERLAP` (409) on violation; a gap of exactly 45 minutes explicitly allowed — `workspace/implementation/routes/deliveries.py:129`.

**Rationale for editing (rather than a byte-identical copy):** the original PRD sentence verbatim admitted the `or` reading — exactly the bug the original implementer wrote and Step 7 fixed — so the sentence genuinely under-determined the behavior and needed minimal tightening.

**Pre-edit search log:** overlap predicate exists at exactly one site (`routes/deliveries.py:119-130`); related non-overlap paths checked (shift/access-window containment, complete_delivery, order cancellation cascade, delivery creation, error definition) — no other path raises `ERR_TRUCK_SHIFT_OVERLAP`.

**Orchestrator correction:** the subagent's first rewrite mis-stated the connective ("if either condition fails"), which contradicts the code (`d_start < o_end + BUFFER and o_start < d_end + BUFFER` — rejection iff BOTH conditions hold) and would fail the drop-limit test (windows 4h apart satisfy exactly one condition). Orchestrator re-edited line 178 to: rejection fires "when the new window starts before an existing delivery's window end plus 45 minutes AND that existing delivery's window starts before the new window's end plus 45 minutes — only when both buffered-overlap conditions hold simultaneously; a gap of exactly 45 minutes is allowed." Verified verbatim against `deliveries.py:129`.

## Step 9: Complete PRD — 2026-10-01T08:48:24.000Z

Subagent summary (verbatim):

**Files:** PRD_FINALIZED.md 265 lines / 40,773 chars → PRD_COMPLETED.md 265 lines / 44,523 chars (+0 lines, +3,750 chars — all edits in-paragraph; no new sections). Fresh cp done first; the stale byte-identical copy from the interrupted attempt was overwritten. implementation/ untouched.

**Counts:** 22 edits across 24 paragraphs — 13 ambiguity-pins, 9 mismatch-revisions.

**Changes** ({section} — {insert|revise} — {ambiguity|mismatch} — {what} — {impl ref}):

- §2.3 — insert — ambiguity — out-of-range/non-integer limit/offset → ERR_INVALID_REQUEST; list sort tie-break id ascending — helpers.py:89-115
- §2.4 — insert — ambiguity — version starts at 1 — all creators (e.g. routes/capacity.py:43)
- §2.4 — insert — ambiguity — created_at/updated_at are logical-clock-governed; meta.api_request_timestamp is the sole wall-clock exception — helpers.py:13-16, response.py:9-12
- §2.4 — revise — ambiguity — clock may be set to any parseable instant, forward or backward ("advance" implied forward-only) — routes/capacity.py:13-22
- §2.7 — insert — ambiguity — missing expected_builder_version on order create → ERR_INVALID_REQUEST — routes/orders.py:59-61
- §2.7 + §3.1 — revise — mismatch — allocate's expected_capacity_week_version is optional; omitted → no version check (PRD said "requires the request body to carry") — routes/capacity.py:56-58
- §2.8 — insert — ambiguity — ERR_INVALID_REQUEST is unranked, applied at field-read point; §3-pinned guard orders prevail — validators inline throughout
- §3.1 — revise — mismatch — week_start_date not validated as Monday, no per-mill uniqueness enforced — routes/capacity.py:29-44
- §3.1 — insert — ambiguity — allocation legs non-negative integers, zero allowed — routes/capacity.py:54-55
- §3.1 — revise — mismatch — waterfall tie-break "(never by id)" → id ascending as final tie-break after created_at — services/calc.py:30
- §3.2 — revise — mismatch — sku_code uniqueness not enforced; index_premium_cents must be non-negative — routes/catalog.py:24-31
- §3.2 — revise — mismatch — effective_week_start not validated as Monday; index-entry ties after created_at broken by larger id — routes/catalog.py:48, services/calc.py:87-88
- §3.3 — revise — mismatch — branch_code uniqueness not enforced; activity_score "0 to 100" → non-negative, no upper bound; target_stock_mbf zero allowed — routes/catalog.py:64-69
- §3.3 — insert — ambiguity — valuation lot walk adds id tie-break; delta_cents defined as fifo − wavg — services/calc.py:52,74
- §3.4 — revise — mismatch — lien_rights_state_code "two-letter" → any non-empty string — routes/builders.py:24
- §3.4 — insert — ambiguity — explicit ERR_INVALID_STATE for decisions from unlisted source statuses (incl. any decision on CLOSED) — routes/builders.py:52-80
- §3.5 — insert — ambiguity — job_exposure_cap_cents non-negative, zero allowed — routes/builders.py:116
- §3.5 — insert — ambiguity — accept guard order pinned (ownership → QUOTED → expiry → branch 404 → enum → credit); response is the created order with 201; lazy QUOTED→EXPIRED flip with version bump on get/list reads — routes/takeoffs.py:63-87,127-170
- §3.6 — insert — ambiguity — direct-order guard order pinned (job 404 → branch 404 → OCC → enum → per-line validation) — routes/orders.py:48-66
- §3.6 — revise — mismatch — confirm check order: PRD narrated fiscal-before-specialty; impl runs credit → specialty → pricing → fiscal → reservation — services/order.py:149-174
- §3.6 — revise — ambiguity — FLOAT_TO_SHIP orders are also priced and pinned to the confirm week at confirm (both modes), then re-priced at delivery completion — services/order.py:163-178,229-232
- §3.6 — insert — ambiguity — shortfall check is per-line independent; same-product lines reserve in turn from the shared pool — services/order.py:77-101
- §3.7 — insert — ambiguity — shift created with elapsed window_end is CLOSED from creation; status re-derived on reads and at schedule; max_drops must be positive when supplied — routes/deliveries.py:19-24,38,45,54,99
- §3.8 — revise — mismatch — lien EXPIRED evaluation "on lien-filing reads and on job mutations" → lazily on the per-job lien-filing list read only — routes/liens.py:16-24,75-85

**Precision/connective check:** no compound-condition rewrite needed; §3.7 45-minute overlap already says "AND … both … simultaneously", verified against routes/deliveries.py:129.

**Dead-code finding:** round_half_up_int (services/calc.py:10) defined with zero callsites — benign; mandated half-up rounding is performed inline in price_line, branch_valuation, delivery_fee_cents, and round_half_up_4 for fill_rate_pct. _refresh_lien_expiry reachable only from the list endpoint (pinned by the §3.8 revision).

**Orchestrator verification:** diff -q confirms PRD_COMPLETED.md differs from PRD_FINALIZED.md; no implementation/*.py newer than results.1.json (clean sweep still valid); all 8 results files present at 69/69; spot-check of the §3.6 confirm-order revision against services/order.py:149-174 confirms the claimed order (credit → specialty → pricing → fiscal → reservation) matches code verbatim.
