# Step 8 — Produce PRD_FINALIZED.md

Produce `/home/ubuntu/github/CodingPRD/tasks/task_3348_railcar_manufacturing_lease_fleet_conversion/workspace/PRD_FINALIZED.md` — a minimal patch of `workspace/PRD.md` that pins every place where the implementation makes a concrete behavioral choice that PRD does not uniquely determine, or where implementation used a different logic than the PRD. Goal: a fresh implementer reading `PRD_FINALIZED.md` alone produces a code base behaviorally equivalent to `workspace/implementation/`.

**HARD SCOPE — read this before anything else: every PRD edit you make must trace to a specific fix which reveals PRD-silence or PRD-mismatch with current `implementation/` — an `implementation/` fix, a test deletion, or a `test_suite/` / `test_helpers/` fix listed in `<step_7_diff>`. Nothing else.**

**NO-NEW-MISMATCH RULE.** Step 8's edit **scope** is locally bounded to `<step_7_diff>` items, but Step 8's edit **perspective is global**. Each edit's wording must remain consistent with the entire current implementation, including paths Step 7 never exercised. Wording that accidentally narrows, redefines, reorders, or excludes behavior the implementation exhibits anywhere off the Step 7 site becomes a brand-new mismatch that Step 9 must undo.

Before committing each edit, you MUST enumerate every code path in `implementation/` logically related to the edit's subject — not just the Step 7 site, but every callsite, branch, helper, cascade, and parallel endpoint that touches the same field/entity/operation — and confirm your proposed wording is consistent with all of them. If any enumerated path would be mis-described, revise the wording (widen, soften, re-scope) before committing. The search is triggered by the edit itself, not by any keyword in it; every edit gets the search regardless of how innocuous it looks. When in doubt, prefer under-determined wording — a looser PRD is recoverable in Step 9; a false universal claim is indistinguishable from a genuine PRD/impl divergence.

You may read workspace: `PRD.md`, `implementation/`, `test_helpers/`, `test_suite/`, `INSTRUCTION.md`.
You MUST NOT read: `SCAFFOLD*.yaml`, `worklog.md`, `_design_work/`, `_stage2_brief.md`.

Implementation is the alignment target. Tests are NOT — Step 7 has already weakened or deleted assertions that PRD did not pin, so `test_suite/` is sometimes laxer than `implementation/`. Treat test files only as auxiliary evidence of where Step 7 found PRD ambiguity or mismatch; align `PRD_FINALIZED.md` to what `implementation/` actually does.

## Method

0. `cp workspace/PRD.md workspace/PRD_FINALIZED.md`. Edit only `PRD_FINALIZED.md`.
1. For each `<step_7_diff>` item: locate the matching behavior in `implementation/`. Patch `PRD_FINALIZED.md` only when impl pinned a choice PRD left open — not every item is a PRD silence (some are pure fixture bugs) — or when impl mismatches `PRD.md`.
2. Where PRD already determines behavior, keep prose verbatim; elsewhere insert or revise inline to match impl, changing as little as possible. No new sections. Never invent behavior the impl does not exhibit.
3. **Apply the NO-NEW-MISMATCH RULE before committing each edit, every time.** Identify the edit's subject; enumerate every impl path that touches that subject (not only the Step 7 site); confirm your proposed wording is consistent with all of them. If any enumerated path would be mis-described, revise — widen, soften, or re-scope — before committing.

## Summary on exit

- `PRD.md` vs `PRD_FINALIZED.md` line counts and %-delta.
- One bullet per change: `{PRD section} — {insert|revise} — {what changed} — {impl file:line}`.
- Per-edit pre-edit search log: for each edit, list (a) the subject identified, (b) the impl paths enumerated and read/grepped, (c) the wording adjustment made (if any) to keep all enumerated paths consistent with the new sentence. An empty (c) is fine — but (a) and (b) are mandatory for every edit, even ones that look obvious.

---

<step_7_diff>

Step 7 ran 2 iterations. Sweep 1 = 144/197; sweep 2 = 197/197 in all 8 rounds. **Tests deleted: none.**

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

**Context on Step 5 adjudications that shaped these fixes** (from the Step 5 worklog, which you may NOT read — reproduced here because they identify PRD silences):
- `capital_allocation_cents` was contradictory across PRD §3.4/§2.9/§3.9; adopted capital = live cars × unit_price.
- Retrofit program cost basis: PRD §3.8 (scheduled estimate while PLANNED/IN_PROGRESS) vs the scaffold's completed-only base formula.
- Component `reserved_qty` includes the retrofit term; COATING rows are exempt from reservation-time stock commitment.
- Component opening stock IS settable at registration.
- `ERR_INVALID_STATE` vs `ERR_ALREADY_TERMINAL` split across sites.
- Default composite catalogue quote 1450000.
- Retained-order credit attribution contested in PRD §3.9.
- Fleet cap: hard 402 at release; §3.4 compensating path at completion.
- `car_assignment_reassign` to a non-HELD target: PRD names no specific error.
- Material endorsement release vs `ERR_MATERIAL_ENDORSEMENT_PENDING`.
- Amendment redraft accepted from `AMENDMENT_DRAFTED` as well as `ACTIVE`.

</step_7_diff>
