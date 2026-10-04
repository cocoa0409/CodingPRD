# Worklog — task_3348_railcar_manufacturing_lease_fleet_conversion

Scenario: Railcar Manufacturing & Lease Fleet Conversion (Trinity Industries)

## Step 1: Create task directory — 2026-10-01T04:34:00.000Z

Task directory `./tasks/task_3348_railcar_manufacturing_lease_fleet_conversion` was pre-allocated by the caller with an empty `workspace/` inside; no index computation or directory creation was performed. Verified `workspace/` exists and is empty, and that `./INSTRUCTION.md` exists at project root (copied in Step 3).
## Step 2: Generate Scaffold — 2026-10-01T11:31:35.275189419Z

Step 2 was interrupted twice by host/model-endpoint failures and was completed across a resumed session. On resume, `SCAFFOLD.yaml` (112854 B) was verified complete and self-consistent — it ends at the §1.7 RBAC matrix and parses to 16 entities, 10 state machines, 12 calculations, 24 ordered validations, 77 endpoints, 27 errors, 7 roles — so it was kept as-is and NOT regenerated. The two design indices were incomplete and were finished from scratch.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)** — the interrupted run had written only 2 of 9 difficulty rules (`dual_variant_calc`, `combinatorial_formula`, 4 instances). Those 4 were kept (they lint clean and already satisfy their §0.5 differentiation clauses) and the remaining 7 rules were authored via focused subagents, then merged in §0.5 order. Final: **9 rules × 2 instances = 18 instances**, zero duplicate names.

| rule_id | instances |
|---|---|
| dual_variant_calc | quote_variant_divergence_wheelset_lapse; capital_allocation_retained_vs_sold_basis |
| combinatorial_formula | order_quote_line_rounding_order_pinned (mode b); fleet_reconciliation_circular_order_pinned (mode c) |
| non_linear_state_machine | car_assignment_suspend_reassign_fork (branching fork, CarAssignment); lease_fleet_car_sold_held_void_cycle (compensating cycle, LeaseFleetCar) |
| transitive_cascade | retained_completion_fleet_capital_cascade (depth 3); sale_settlement_realized_gain_cascade (depth 2) |
| priority_pair_validation_conflict | state_vs_business_fiscal_return_conflict; business_safety_vs_business_referential_placement_conflict |
| boundary_precision_check | boundary_mileage_allowance_exact_vs_one_mile_over; boundary_component_stock_exact_vs_one_short |
| cross_entity_state_dependency | settle_returns_gated_on_car_return_settlement (LeaseFleetCar←CarReturn); suspend_assignment_gated_on_contract_status (CarAssignment←LeaseContract) |
| resource_temporal_overlap | shop_line_half_open_touching_windows_allowed (half-open, adjacency OK); placement_interval_one_day_buffer_boundary (mandatory 1-day gap) |
| compensating_invariant | sale_void_conserves_realized_gain (monetary ledger scalar); reserve_cancel_conserves_component_on_hand (physical inventory count) |

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9)** — was an empty `scaffold_corner_design: []` stub. Authored across five section-group subagents walking the claim-extraction-guide taxonomy, then merged in guide order. Final: **213 instances (180 real recipes + 33 `excluded_because:` stubs)** across all nine sections — entities 39, state_machines 34, calculations 28, validations 28, endpoints 20, errors 27, rbac 18, cross_cutting_complexity_layers 16, consistency_model 3. All 27 §1.6 error codes are covered (21 real recipes + 6 stubs citing genuine §1.8 assertions); all 24 validation priorities p1..p24 are covered; all 7 roles have a CAN and a CANNOT case; both §1.2.1 concurrency rules have stale-version and correct-version cases.

Notable corrections made during authoring, where a brief's suggested shortcut was checked against source and found wrong: p18 (ERR_CREDIT_LIMIT_EXCEEDED) and p21 (ERR_CAR_NOT_HELD) could NOT be stubbed against the §1.8 priority-conflict instances, because those instances assert the two errors as the LOSING rule ("never ERR_CREDIT_LIMIT_EXCEEDED") — they were given full real recipes instead. Three §1.1 declaration holes were surfaced but not patched (scaffold frozen): `Component.shortfall_qty` named in §1.5 prose but not declared on the entity; `PortfolioLedger` has a §1.2 state machine and is a §1.5 output but is absent from §1.1; `POST /component-receipts/{id}/receive` returns no parent-PO status field.

**Verification** — `scaffold_lint.py .` verdict: **clean lint** — 77 §1.5 endpoints, 16 §1.1 entities, 18 §1.8 + 180 §1.9 instances, 2700 calls scanned, all calls conform to §1.5 and all §1.1 FKs reverse-reachable. Every formula-derived assert literal was produced by executing the scaffold's formula in Python against its declared constants, not estimated. Design working files (fragments, briefs, pre-merge backups) archived under `_design_work/`.

## Step 3: Copy Shared Files — 2026-10-01T11:31:50.376666268Z

Copied `./INSTRUCTION.md` (1424 B) from the project root to `workspace/INSTRUCTION.md` — the build contract the evaluator uses (produce `./implementation/start.sh`, listen on `$PORT` default 10000, bind 0.0.0.0, run in foreground, `bash start.sh` is the entire entrypoint contract).

## Step 4: Generate PRD — 2026-10-01T11:50:18.726574252Z

Spawned the doc-generator subagent with SCAFFOLD.yaml as the sole input; BOTH design indices (SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml) and the archived `_design_work/` directory were withheld by explicit read-ban so no `test_recipe` worked-example numbers could leak into the prose the implementer will read.

**Output** — `workspace/PRD.md`, 436 lines / 105044 B, written in 23 incremental one-tool-call messages. Structure: §1 Introduction; §2 Global Specifications (2.1 RBAC, 2.2 response structure emitted verbatim from the canonical source, 2.3 pagination, 2.4 resource identity, 2.5 logical clock, 2.6 money/rounding, 2.7 OCC, 2.8 regulatory life and shop capacity, 2.9 ledger/credit/capital, 2.10 cascading effects, 2.11 validation precedence); §3 Business Logic (3.1–3.9 covering order intake → sourcing → endorsements → release/changeover/completion → contracts → placements → returns → retrofits → sales/ledger); §4 endpoint table; §5 error catalogue. File ends on a complete table row — not truncated.

**Verified coverage** (scripted PRD-vs-SCAFFOLD diff): 86/86 entity fields, 82/82 request-body inputs, 2/2 path params present; 24/24 validations with condition + error_id + HTTP status; 40/40 state-machine transitions; 12/12 calculations with formulas/variants/constants; 77/77 endpoints with side effects; 27/27 error codes with matching status; 7/7 roles. §3 path purity: 0 method/path tokens leaked into prose. Sibling-branch symmetry: 14/14 dual-variant / sibling-transition groups have equal prose density.

**Key contract constants the PRD pins** (these govern every downstream fixture): logical clock starts at `2026-09-01T00:00:00Z` and never reads wall-clock time; all money is integer cents; rounding is ceiling-or-floor only (never half-up), with per-line ceiling before summation for the order quote; end dates are exclusive and intervals are half-open, except the placement buffer rule of §3.6 which deliberately demands a wider gap; OCC guards exist on exactly two writes (`POST /lease-contracts/{id}/amendments` via `expected_lease_version`, `POST /substitution-endorsements` via `expected_production_order_version`) and no other endpoint may require an `expected_*_version`; regulatory-life eligibility is inclusive of the end date itself.

## Step 5: Generate Unit Tests — 2026-10-01T14:33:45.32130638Z

Because the design index is unusually large (18 difficulty + 213 corner instances), Step 5 was split across one Stage-1 subagent and seven Stage-2 queue subagents, each writing its own files. Final suite: **197 tests collected** (`pytest --collect-only` clean, no import errors), **197 `Design:` tags, all resolvable, zero duplicates**, zero skip/xfail.

| Stage | Subagent scope | Files | Tests |
|---|---|---|---|
| 1 | `test_helpers/` (types, api_client, api_errors, assertions, factories, constants, test_users, fixtures, `__init__`) | 9 | — (4161 lines, 53 composite fixtures) |
| 2A | difficulty — all 9 rules × 2 instances | 5 `test_difficulty_*.py` | 18 |
| 2B | corner `entities` | 4 `test_entities_*.py` | 33 (1 instance skipped) |
| 2B | corner `state_machines` | 2 `test_state_machines_*.py` | 26 |
| 2B | corner `calculations` | 6 `test_calculations_*.py` + support | 26 |
| 2B | corner `validations` | 6 `test_validations_*.py` | 22 |
| 2B | corner `endpoints` + `errors` | 5 `test_endpoints_*` / `test_errors_*` | 39 (all 27 error codes covered) |
| 2B | corner `rbac` + `cross_cutting_complexity_layers` + `consistency_model` | 6 files | 33 |

Stage 1 verified: all 9 files AST-parse and import; 77/77 endpoints covered by `api_client`; 27/27 errors registered with matching HTTP statuses. A Stage-1 defect was found by the difficulty queue and fixed by the orchestrator: `setup_catalogue` passed `on_hand_qty` both as a named argument and inside the per-component `*_overrides` dict, raising `TypeError: got multiple values for keyword argument 'on_hand_qty'` at every `setup_order_at_stock_boundary` call site; the three component blocks now merge as `**{"on_hand_qty": stock, **(overrides or {})}` so an explicit override wins. A follow-up AST scan found no other literal-dict double-star kwarg clash.

**Recipe-vs-PRD discrepancies found and resolved toward the PRD** (these are the doc-generator silences Step 8 must patch):

1. **Four §1.8 recipes carried arithmetic matching no reading of the PRD** — the two inherited from the interrupted run plus two more. `quote_variant_divergence_wheelset_lapse` (recipe 8250000→8667000; PRD 2815000→2905000), `capital_allocation_retained_vs_sold_basis` (omitted the per-line surcharge; and its third assert is unreachable because the retained credit exceeds the sold debit, clamping the balance to 0), `order_quote_line_rounding_order_pinned` (lines and total recomputed; also its own inputs made per-line and sum-first coincide, so the pinned order was not actually demonstrated), `fleet_reconciliation_circular_order_pinned` (recomputed, and its sale could not settle at all — `ERR_SETTLEMENT_UNBALANCED` — so it was re-dated to 351 days of depreciation).
2. **`capital_allocation_cents` is contradictory across PRD §3.4 / §2.9 / §3.9.** Two readings: capital = live cars × unit_price, vs. the lessor-equity figure. Adopted **capital = live cars × unit_price**; the lessor-equity value has no API field and was dropped from the instances that asserted it. The design index itself contradicts across `transitive_cascade` (asserts capital) and `resource_temporal_overlap` (asserts the equity).
3. **Retrofit program cost basis.** The scaffold's base formula is completed-only; PRD §3.8 says a PLANNED/IN_PROGRESS program counts every non-CANCELLED work order (3740000 for the recipe's setup, not 1870000), with the completed-only basis reserved for a COMPLETED program. Asserted the PRD value. **If the implementation follows the scaffold base formula instead of the PRD prose, this test will fail.**
4. **Retained-order credit attribution is contradictory between two sibling calculation tests** — one requires a retained order released under a lessee's contract to subtract `unit_price × retained_cars` from the balance, the other requires it not to. Affected tests were made robust by releasing retained orders with no contract and no `lessee_id`.
5. **`ERR_INVALID_STATE` vs `ERR_ALREADY_TERMINAL`.** The terminality check guards only three writes (order completion, sale settlement, retrofit-program start); other illegal actions answer `ERR_INVALID_STATE`.
6. **Component `reserved_qty` includes the retrofit term** — sum of `component_qty_consumed` over every IN_PROGRESS work order whose program names that component (recipe said 0, PRD says 2). COATING rows are exempt from reservation-time stock commitment.
7. **Component opening stock IS settable at registration** (`on_hand_qty` honoured when supplied); the "input ignored" claim applies only to writes after creation. One `entities` instance was skipped entirely as a PRD-contradicting recipe.
8. **Default composite catalogue quote is 1450000**, not the 1275000 several recipes assumed (subtotal 1000000 for CS-200 + CT-200 + WS-200, labor 450000; the fee cap is not charged because the raw fee is 0 with no approved endorsement).
9. **Catalogue-shape mismatches** also forced recomputation of the default sale book value (1360000, gain 140000) and of several sale-ledger literals.
10. **Setup chains that were unreachable per the PRD** and were repaired: `reserve-components` on a car type with no bill-of-material rows (→ `ERR_PREREQUISITE_NOT_MET`); changeover windows whose width did not equal `build_hours × quantity`; placements whose `start_date` preceded the car's `built_date` or the pinned clock; a captured `expected_lease_version` that went stale between activation and amendment drafting; changeover lines not matching the car type's `line_count_family`.
11. **One assertion dropped as two-reader ambiguous** (`shop_line_half_open_touching_windows_allowed` asserted `program_cost_cents == 0` at work-order creation, but an implementer who re-derives on every program event gets the scheduled estimate) — the six shop-slot assertions were kept.
12. **Two §1.1 declaration holes**: `settled_charges_cents` / `credits_applied_cents` are never defined in PRD prose, only listed as read outputs.
13. **§3.4 fleet-cap self-contradiction**: "re-checked here … rejected as `ERR_FLEET_CAP_EXCEEDED`" vs. a later clause saying the overflow car is born scrapped and the order still reports COMPLETED. Tests assert the 402 rejection (which §2.11 priority 19 also demands); the "born scrapped" path needs a PRD ruling.
14. **`car_assignment_reassign` to a non-HELD target car**: PRD says the target "must be HELD" but names no error for that site, and §2.11's `ERR_CAR_NOT_HELD` enumeration omits it. Asserted `ERR_INVALID_STATE`; a PRD-only reader could plausibly ship `ERR_CAR_NOT_HELD`.
15. **`p1`'s recipe asserted a car-types list endpoint that §4 does not define**; replaced with a duplicate-create probe proving exactly one row exists.
16. **Non-UUID identifiers**: recipes probed misses with malformed ids; the PRD states no identifier-shape check, so well-formed-but-nonexistent UUIDs were used instead.

**Clock reachability** was checked for every recipe against the PRD's `2026-09-01T00:00:00Z` start: all pinned positions are reachable via the operator clock endpoint and all date arithmetic checks out (e.g. 2026-09-15 + 25y = 2051-09-15; `[2026-10-01, 2026-10-31)` = 30 days = one allowance block; `[2026-10-01, 2026-10-11)` = 10 shop days). No instance required an unreachable clock position.

## Step 6: Generate Implementation — 2026-10-01T15:08:07.612816093Z

Spawned the implementation-generator with the ISOLATION RULE enforced verbatim: it was forbidden to read, grep, or open `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_suite/` or `test_helpers/`, implemented from `INSTRUCTION.md` + `SCAFFOLD.yaml` + `PRD.md` only, and did not run the test suite.

**Files written** to `workspace/implementation/` (13 files, 3133 lines): `start.sh` (15), `requirements.txt` (1), `app.py` (80), `store.py` (186), `errors.py` (90), `web.py` (273), `calc.py` (481), `serialize.py` (307), `svc_catalog.py` (607), `svc_lease.py` (531), `svc_retrofit.py` (401), `svc_sales.py` (161). All 77 `/api/v1` routes registered; all 16 entities, 10 state machines, 24 ordered validations and both OCC guards implemented; the endorsement PATCH's `expected_substitution_endorsement_version` left optional as §2.7 requires.

**Orchestrator verification on disk** (not relying on the subagent's report): line counts confirmed; `grep` for `sqlite` / `.db` / `json.dump` / `pickle` / `shelve` / file-write opens found nothing, and no `seed`/`preload`/`bootstrap` function exists — storage is in-memory dicts only, so a fresh `start.sh` wipes all state. Independent boot check: `PORT=18511 bash start.sh` bound `0.0.0.0`, answered within ~2s, `GET /` → 200, and `GET /api/v1/_clock/current` → `ERR_UNAUTHENTICATED` (registered and correctly gated on the role headers). `GET /api/v1/car-types` correctly answers method-not-allowed, matching the PRD §4 surface which declares no car-types list endpoint. `start.sh` guards the dependency install behind an `import flask` probe so the per-test-server isolation does not run hundreds of contended pip installs.

**Three PRD tensions the generator resolved** (recorded here because Step 7 will adjudicate them):
1. Material endorsements on release — PRD §3.4 says release "applies every APPROVED substitution endorsement" while the state machine's precondition requires material ones be APPLIED in the same request. It applies all of them, which makes `ERR_MATERIAL_ENDORSEMENT_PENDING` a post-application guard that cannot fire; the alternative reading would make the `APPLIED` state unreachable.
2. Fleet cap — hard `ERR_FLEET_CAP_EXCEEDED` (402) at release, but at completion the §3.4 compensating path wins: overflow cars are born `SCRAPPED` and the order still reports COMPLETED. The test suite asserts the 402 rejection at release.
3. Amendment redraft — drafting accepted from `AMENDMENT_DRAFTED` as well as `ACTIVE`, per §2.7/§3.5's "a second draft supersedes the first"; the state machine lists only `ACTIVE → AMENDMENT_DRAFTED`.

## Step 7: Run Tests and Iterate — 2026-10-01T16:13:44.491416293Z

One long-lived fix subagent owned the run→diagnose→fix→rerun loop. Each iteration was a parallel 8-round stability sweep under `prd-bench-local-run --isolation per-test-server`.

**Iterations run:** 2. Sweep 1 = 144/197 (53 deterministic failures, identical in all 8 rounds). Sweep 2 = **197/197 in all 8 rounds, 0 skipped**.

**Orchestrator verification:** all 8 `results.{1..8}.json` present on disk, each independently parsed at `passed=197 total=197`. No results file was deleted by the fix subagent this time.

**Tests deleted:** none. No test failed the PRD-coverage check, so nothing was removed.

**PRD-internal contradiction resolved (not a deletion):** `test_second_retained_completion_past_the_fleet_cap_returns_402` asserted a 402 at the *completion* site, which PRD §3.4's specific compensating-path paragraph ("must be honoured exactly … The order is never blocked by this overflow") negates. Resolved by lex specialis toward §3.4 and the test was rewritten to `…_is_compensated` (order completes, overflow car born `SCRAPPED`, live count stays at the cap). The release-site 402 assertions are untouched.

**Fixes applied to `test_helpers/`** (`test_helpers/fixtures.py`)
- `setup_catalogue`: default part numbers now derive from the model code (`WS-{code}`/`CS-{code}`/`CT-{code}`) — two catalogues in one scenario no longer collide on PRD §2.11's `part_number` uniqueness rule (fixed the two `ERR_DUPLICATE_ROW` setups).
- `setup_catalogue`: new `include_casting=True` switch, suppressing the casting component and its BOM row for recipes that name a one-row WHEELSET bill of materials.

**Fixes applied to `test_suite/`**
- Changeover line literals made equal to the car type's `line_count_family` (no ProductionLine entity exists in PRD or SCAFFOLD, so `{line}` must resolve to a persisted car type's family): `LINE-A-1`→`LINE-A`, `LINE-C-1`→`LINE-C`, `LINE-M-A`/`LINE-M-B`→`LINE-M`, `LINE-R-1`→`LINE-R`, `LINE-S-1`→`LINE-S`, `CR-L1`→`CR_LINE`, `S18-L1`→`S18_LINE`, `CAP-L1`→`CAP_LINE`, `S19-L1`→`S19_LINE`, `SL-L1`/`S20-L1`/`NC-L1`/`LM-L1`→families, `FLT-L1`→`FLT_LINE`, `R24-A-L1`/`R24-B-L1`→`R24_A_LINE`/`R24_B_LINE`.
- `test_difficulty_state_machines.py`: `_car_world` gained wheelset/casting shape parameters; fork and void-cycle instances now carry their recipes' CS-2000 casting row at qty 1.
- Wheelset-only BOMs for the shop-line and sale-void recipes (`include_casting=False`).
- Clock pinned *after* `setup_catalogue` in two `test_difficulty_cascades_and_compensation.py` instances (the helper was silently resetting it to the startup default).
- `_placed_car` no longer attaches the contract to the retained order, so the retained-order credit of PRD §3.9 is unattributable under either reading.
- Two accrual instances advance the clock to the return date; two retrofit instances start the work order before completing it; missing factory imports added; placement-create success expects 201; fleet read filtered by `production_order_id` (a HELD, never-placed car carries no contract stamp).
- Two scrap instances relaxed to `validate_error_is_one_of([ERR_INVALID_STATE, ERR_CAR_NOT_HELD])` — PRD §2.11 p5 and p21 name both codes for that site.

**Fixes applied to `implementation/`**
- `calc.py::capital_allocation_for_order` — returns live cars × `unit_price_cents` (the 7 % lessor-equity factor had been applied to a field PRD §3.4 defines as the capital figure).
- `calc.py::order_price_quote`/`_row_unit_cost` — the endorsed substitute's own unit cost prices its row.
- `calc.py::utilization_credit` — extracted; the 12 % credit now also applies to the restated basis.
- `serialize.py::fleet_car` — `retrofit_required` returns the stored flag (the work-order write sets it true per §3.8).
- `serialize.py::portfolio_ledger` — `fleet_nbv_cents` re-derived on read (time-dependent derived field).
- `svc_retrofit.py::create_work_order` — regulatory-life test compares against the current clock date (§2.8's inclusive boundary).
- `svc_lease.py::create_return` — restated accrual recomputed when a return closes a placement.
- `svc_lease.py::reassign_assignment` — non-HELD target answers `ERR_INVALID_STATE`.
- `svc_lease.py::draft_amendment` — the drafted rate/bearer are stored on the contract row.
- `svc_catalog.py::release_order` — a material `APPROVED` endorsement blocks release with `ERR_MATERIAL_ENDORSEMENT_PENDING`.

## Step 8: Finalize PRD — 2026-10-01T16:26:18.856479445Z

Step 8 ran because Step 7 applied 10 `implementation/` fixes (the skip condition requires zero). The subagent copied `PRD.md` → `PRD_FINALIZED.md` and patched only at Step 7 fix sites, applying the mandatory per-edit pre-search (enumerate every impl path touching the edit's subject, then confirm the wording is consistent with all of them).

**Output** — `workspace/PRD_FINALIZED.md`, 436 lines (0.0% line delta; 107516 B vs 105044 B), 14 paragraph-lines rewritten in place across 9 hunks. Orchestrator verification: `diff -q` confirms a real edit (not a `cp`-only no-op) and the file ends on its final table row.

**Edits, each traced to a Step 7 item:**
- §2.8 — `retrofit_required` is a *stored* boolean whose derived test is enrollment; §3.8 writes set it directly, and it is re-derived at every recompute site plus on every clock move. Pre-search caught a first draft that enumerated recomputes by section and omitted the retained-completion car creation; rewrote to name all four recompute occasions.
- §2.9 and §2.11 item 19 — fleet-cap breach on **release** → 402, while the same overflow at **completion** is compensated rather than rejected, so the precedence list no longer contradicts §3.4.
- §3.1 — a substituted BOM row is priced at the standing-in component's `unit_cost_cents`; scoped to the line-amount sentence only, leaving `production_feasibility_gate`'s row-own-component lead-time rule verbatim.
- §3.3 — an `APPROVED` material endorsement **blocks** the release (`ERR_MATERIAL_ENDORSEMENT_PENDING`) and is never applied by one.
- §3.4 — the **capital figure** (live cars × `unit_price_cents`) is what is written to `capital_allocation_cents`; the 700-bps lessor equity is not a field.
- §3.4 — completion's fleet-cap re-check compensates instead of raising 402.
- §3.4 — insert: the `{line}` path segment resolves against car types' `line_count_family` (`ERR_NOT_FOUND` when no car type carries it, `ERR_INVALID_STATE` when the order's family differs).
- §3.5 — amendment drafting is legal from `AMENDMENT_DRAFTED` as well as `ACTIVE`; the drafted rate/bearer are stored **on the contract row** so a second draft supersedes the first.
- §3.6 — insert: the 12 % utilization credit applies to the **restated** basis as well as the open basis.
- §3.6 — a reassignment target that is not `HELD`, or carries a different contract, answers `ERR_INVALID_STATE`.
- §3.9 — retained-order credit attribution (named lessee, else the release contract's lessee) and count (cars the order produced, live or not).
- §3.9 — scrapping a non-`HELD` car answers `ERR_CAR_NOT_HELD`, not the generic `ERR_INVALID_STATE`.
- §3.9 — insert: `fleet_nbv_cents` is re-derived from the live fleet and current clock on every read that reports it.

**Adjudicated as needing no edit** (PRD already determines the behavior): `create_work_order`'s regulatory-life comparison (§2.8 pins the current-clock-date inclusive boundary); `create_return`'s restated accrual (§3.6 already says a restated accrual is produced at a return); and all pure-fixture Step 7 items (part-number derivation, `include_casting`, wheelset-only BOMs, clock pinning, factory imports, 201-on-create, `production_order_id` filter).

## Step 9: Complete PRD — 2026-10-01T16:54:36.613453323Z

Started from `PRD_FINALIZED.md` (Step 8 ran), copied to `PRD_COMPLETED.md`, and walked `implementation/` exhaustively — all 10 modules / ~3.2k lines, route by route, formula by formula, field by field. Step 8 had already patched the sites Step 7's fixes touched; this step's job was the residual: behaviors impl resolved at generation time that no test ever asserted, so no failure signal ever surfaced.

**Output** — `workspace/PRD_COMPLETED.md`, 436 lines / 118416 B (vs PRD_FINALIZED.md 436 lines / 107516 B), **+10.9 kB (+10.1%)**, 47 in-place paragraph rewrites, zero structural lines added, no new sections. Orchestrator verification: `diff -q` confirms a real edit (47 hunks, not a `cp`-only no-op) and the file ends intact on the error catalogue.

**Counts:** 48 ambiguity-pins + 10 mismatch-revisions.

**Mismatch-revisions (PRD described a different behavior than impl):**
- §2.1 — a `Lessee` reads every §4 read on the same terms as other roles; only the outstanding-balance read is self-scoped (`svc_lease.py:88-89`).
- §2.4 — `on_hand_qty` falls by reservation and retrofit consumption, has no floor, and can go negative (`calc.py:169-195`, `svc_retrofit.py:266-268`); cascade writes bump `version` on every resource they visit even when no figure moved (`svc_retrofit.py:94-96,119-121`).
- §2.11 — body fields the later gates read are parsed/range-checked first.
- §3.2 — `expected_receipt_date` is never derived from lead time (`svc_retrofit.py:313-326`).
- §3.5 — termination does not touch the lessee ledger at all (`svc_lease.py:216-241`).
- §3.8 — replaced the "may not already be enrolled"/alternative-route prose with the actual `HELD` precondition (`svc_retrofit.py:209-211`); inserted that the scrap-versus-retrofit decision has no endpoint and is an internal (uncalled) computation (`calc.py:455-467`).
- §3.9 — the sale life test is inclusive, reconciling §3.9's "strictly later" with §2.8 (`svc_sales.py:33-38`); a bare `fleet_nbv_cents` refresh on sale create/void does not advance the ledger's `version` (`svc_sales.py:72,133`).

**Representative ambiguity-pins (48 total):** unmapped path → `ERR_NOT_FOUND` / wrong method → `ERR_INVALID_REQUEST`; pagination out-of-band values and same-millisecond ordering; clock echo and bad-`to_iso8601` handling; whole-calendar-year life advance with 29 Feb → 28 Feb; deadline-day inclusivity; `CANCELLED` vs `COMPLETED` work orders and shop-slot occupancy; the definition of "projected charge"; numeric floors across seven modules; forecast-basis scope and the 120-day horizon's applicability to only the wheelset/casting uplift; most-recently-created endorsement governs a row; endorsement approve's status-before-self-approval precedence and its no-version-bump re-quote; `decides_material` default; release-branch error selection and lessee attribution; sold-branch lessee chain and charge-by-re-derivation; cancellation restoring only wheelset/casting rows at the effective endorsed quantity; contract activation/ratification/termination gates; placement enrollment, suspend/resume/reassign semantics; return window arithmetic; retrofit work start/complete/cancel and program void/completion semantics; sale settlement, void, and balance-read clamp ordering.

**Post-Step-9 sweep-validity check (orchestrator):** Steps 8 and 9 are documentation-only, but per the known failure mode of post-sweep implementation writes invalidating a green sweep, mtimes were checked. Newest `implementation/` source file is `calc.py` at **15:50:20**; the clean 8-round sweep completed at **16:11**; no file under `test_suite/` or `test_helpers/` was modified after 16:11. **The 197/197 sweep remains valid — no re-run required.**

## Final Verification — 2026-10-01T17:03:01.182453777Z

**Pipeline complete.** Independent orchestrator confirmation run after Steps 8 and 9 (documentation-only steps):

```
prd-bench-local-run --isolation per-test-server --timeout 120 --test-timeout 30
  → 197 passed in 331.18s (0:05:31)
  → Results: 197/197 passed, 0 failed, 0 errors, 0 skipped
  → Server stopped; port-registry released port 33155
```

**Sweep validity:** Steps 8 and 9 touched only `workspace/PRD*.md`. Newest `implementation/` source file mtime is 15:50:20; the clean 8-round sweep finished at 16:11; nothing under `test_suite/` or `test_helpers/` changed after 16:11. The 8 canonical `results.{1..8}.json` files are present in `workspace/implementation/`, each independently parsed at `passed=197 total=197`. No post-sweep implementation writes, so no re-run was required — and the confirmation run above re-verifies the shipped state end-to-end anyway.

**Scaffold lint (final):** `scaffold_lint.py .` → clean — 77 §1.5 endpoints, 16 §1.1 entities, 18 §1.8 + 180 §1.9 instances, 2700 calls scanned, all calls conform to §1.5 and all §1.1 FKs reverse-reachable.

**Delivered artifacts**
- `SCAFFOLD.yaml` (112854 B) — §1.0–§1.7: 16 entities, 10 state machines, 12 calculations, 24 ordered validations, 77 endpoints, 27 errors, 7 roles.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (127561 B) — §1.8 depth index, 9 rules × 2 instances.
- `SCAFFOLD_CORNER_DESIGN.yaml` (895394 B) — §1.9 breadth index, 213 instances (180 real recipes + 33 stubs) across all nine taxonomy sections; all 27 error codes and all 24 validation priorities covered.
- `test_helpers/` — 9 files, 53 composite fixtures.
- `test_suite/` — 37 test files, **197 tests**, every one carrying exactly one resolving `Design:` tag; zero skip/xfail.
- `workspace/INSTRUCTION.md`, `workspace/PRD.md` (436 lines), `workspace/PRD_FINALIZED.md` (436 lines, 14 paragraph-lines patched), `workspace/PRD_COMPLETED.md` (436 lines, +10.1%, 48 ambiguity-pins + 10 mismatch-revisions).
- `workspace/implementation/` — 13 files, 3133 lines, in-memory storage, no seeding, boots via `bash start.sh`; `results.{1..8}.json` each at 197/197.
- `_design_work/` — archived design fragments, briefs and pre-merge backups (not part of the delivery contract).

**Outstanding PRD tensions recorded for downstream review** (all resolved toward PRD prose, with the resolution pinned in PRD_COMPLETED.md): the scaffold's completed-only retrofit-cost base formula vs PRD §3.8's scheduled estimate; the §3.4 fleet-cap self-contradiction (hard 402 at release vs compensated overflow at completion); retained-order credit attribution; `capital_allocation_cents` vs the lessor-equity figure; and `settled_charges_cents`/`credits_applied_cents` being listed as read outputs without ever being defined in prose.
