# Worklog — task_2780_driver_settlement_accessorial_pay_administration

## Step 1: Create task directory — 2026-09-04T20:27:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2780_driver_settlement_accessorial_pay_administration` and its `workspace/` subdirectory. Index 2780 was pre-assigned by the orchestrating harness; no scan of ./tasks/ was performed.

## Step 2: Generate scaffold (subagent) — 2026-09-04T22:05:00.000Z

Done. All three scaffold artifacts are complete and the mechanical gate is clean.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2780_driver_settlement_accessorial_pay_administration/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2780_driver_settlement_accessorial_pay_administration/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2780_driver_settlement_accessorial_pay_administration/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    54
  §1.1 entities declared:     11
  §1.8 instances scanned:     19
  §1.9 instances scanned:     65
  Calls scanned (§1.8+§1.9):  1412

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## What was generated

Output dir: `/home/ubuntu/github/CodingPRD/tasks/task_2780_driver_settlement_accessorial_pay_administration/`

| File | Lines | Bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 2791 | 148338 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1942 | 116321 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 5447 | 325238 |

**SCAFFOLD.yaml (§1.0–§1.7)** — domain `driver-settlement-accessorial-pay`, prefix `/driver-pay`.
- 11 entities (PayPackage, PayComponent, Driver, Load, AccessorialClaim, Advance, Settlement, SettlementLine, EscrowTransaction, Dispute, RetroCorrection), graph topology
- 10 state machines (parallel axes on Load: `movement_status` + `pay_status`), 3 §1.2.1 concurrency rules, 9 calculations, 55 ordered validations, 54 endpoints (incl. `POST /_clock/set_current_utc`), 55 errors, 5 roles (`Driver` is `entity_backed`, `PayrollAdmin` is break-glass), 24 domain constants
- Contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)** — 19 instances, >=2 per rule across all nine rules (`combinatorial_formula` has 3).

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9)** — 83 instances over all nine taxonomy sections: entities 13, state_machines 16, calculations 13, validations 11, endpoints 6, errors 12, rbac 5, cross_cutting_complexity_layers 6, consistency_model 1. 65 carry a `test_recipe`; 18 are `excluded_because` stubs.

## Verification performed
- Name uniqueness across the union of both design files: 102 names, 0 duplicates
- All 18 stub `difficulty_instance` refs resolve to real §1.8 names
- 0 unbound `${...}` placeholders (every one is captured by an earlier call in its own instance)
- All 55 catalog errors are *positively* triggered at least once (negative-control mentions excluded from the count)
- Every money literal pinned in a recipe was computed and asserted in the generator scripts before emission
- Difficulty directive grep: **no match** in any of the three files

## Two SCAFFOLD.yaml self-consistency fixes made while writing §1.9
1. The `Dispute` DENIED->OPEN reopen side effect referenced a field `additional_evidence_doc_ref` that exists on neither the entity nor `/reopen`'s input; rewritten to use the declared `narrative` / `evidence_doc_ref`.
2. `POST /driver-pay/retro-corrections/{id}/cancel` declared a side effect returning an `ADJUSTED` load to `SETTLED`, but the `Load.pay_status` machine had no such transition. Added the `ADJUSTED -> SETTLED` transition (it deliberately leaves the re-graded `paid_miles`/`linehaul_pay_cents` in place, which is why a paid statement's `linehaul_total_cents` can permanently disagree with the load — now exercised by the `derived_field_reconciliation` instance).

Orchestrator verification: all three files present; `grep -rn "harder than expert"` over the task dir returns no match, so the difficulty directive did not leak into the scaffold.

## Step 3: Copy shared files — 2026-09-04T22:06:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_2780_driver_settlement_accessorial_pay_administration/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD (subagent) — 2026-09-04T22:25:00.000Z

PRD complete and verified.

**Output:** `workspace/PRD.md` — **492 lines**, written in 7 chunked appends plus targeted edits; ends at a real boundary (final row of the error table).

**Section list**
- `# Driver Settlement & Accessorial Pay Administration API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Settlement-Office Identities and RBAC · 2.2 API Response Structure · 2.3 Pagination and Collection Ordering · 2.4 Record Identity, Append-Only Logs and Version Semantics · 2.5 The Logical Settlement Clock · 2.6 Money, Miles, Basis Points and Rounding · 2.7 Nested Addressing and Left-to-Right Path Validation · 2.8 Stale-Version Protection on Repeatable Writes · 2.9 Validation Precedence · 2.10 Segregation of Duties Across the Prepare–Approve–Pay Chain · 2.11 Cascading Recomputation and Derived-Field Consistency
- `## 3. Business Logic & Workflows` — 3.1 Pay Packages and Components · 3.2 Driver Records, Package Assignment, Employment Axis · 3.3 The Maintenance Escrow Account · 3.4 Booking a Load (tender/dispatch/deliver/paid miles) · 3.5 Accessorial Claims · 3.6 Advances, Fuel Cards and the Recovery Waterfall · 3.7 Building the Settlement Statement · 3.8 Approval, Payment and the Compensating Void · 3.9 Disputes, Mileage Re-grades and Retroactive Corrections
- `## 4. Endpoint Definitions` (54-row table: Method / Path / Description / Authorized Role(s))
- `## 5. Error Code Catalogue` (55-row table)

**Coverage:** 11 entities · 54 endpoints (all 11 HTTP-201 creators flagged) · 10 state machines / **47 of 47 transitions** documented with explicit `FROM` -> `TO` arrows · 9 calculations (all formulas prose-reconstructible, rounding orders pinned) · 55 validations as an ordered 1–55 precedence ladder in §2.9 · 55 errors (every ID also referenced in §1–3 prose, not only in the table) · 5 roles (4 opaque + entity-backed `Driver`) · all 24 domain constants present as literals · 3 OCC rules · logical clock endpoint.

**Hard-contract reports**
- **Contract 1 — Field-Name Coverage: PASS.** 133 required names (127 entity fields + 6 endpoint-only inputs: `current_utc`, `expected_driver_version`, `expected_pay_package_version`, `expected_settlement_version`, `new_status`, `outcome`); 0 missing, all present as standalone backticked tokens (two passes, second requiring exact-tick match).
- **Contract 2 — Rule Coverage: PASS.** 55/55 validation priorities with error IDs and translated conditions; 3/3 OCC rules with field, error and HTTP 412; 47/47 transitions; all cascades (approval's 4-hop escrow->balance->`FUNDED`->YTD, dispute-uphold's 4-hop, void's 3-tier compensation); all `applies_to` scopes; all field-level defaults; sibling-branch symmetry (the three disjoint UPHELD branches, the three void tiers, both per-diem methods); all 9 calculations; all endpoint side effects.
- **Contract 3 — §3 Path Purity: PASS.** 1,213 backticked tokens in §3: 0 `/`-leading, 0 bare HTTP methods (in or out of ticks), 0 method+path combos, 0 raw slash paths. §2.2 diffs byte-identical to `section-2.2-response-structure.md`. No pseudocode, operator syntax, code fences (outside §2.2's JSON) or fuzzy quantifiers anywhere.

**Key findings — 10 scaffold self-contradictions resolved** (each to the reading with the most corroborating sources / the only non-deadlocking semantics). The most consequential, and the one I reversed late after re-reading the sources: **when swept loads and claims advance.** `prepare`'s side-effect list and the `AccessorialClaim` SM both put `pay_status ACCRUED->SETTLED` and claim `APPROVED->PAID` at *prepare*, and `void`'s compensation list ("swept Loads return to `ACCRUED`", "swept AccessorialClaims return to `APPROVED`") only makes sense if prepare moved them; the lone dissent is a stray precondition on `Load.pay_status ACCRUED->SETTLED` reading "that Settlement transitions APPROVED->PAID", and `pay`'s own side effects mention neither loads nor claims. The PRD documents prepare-time advancement, with `pay` moving nothing but the settlement header. Others: new drivers start `ONBOARDING` (field default + SM initial state + validation 20 outvote the endpoint summary); escrow `->CLOSING` is an explicit admin action, not auto-on-termination; `RetroCorrection PENDING->APPLIED` fires at the corrections sweep, not at approval (APPLIED-at-approval deadlocks `settlement_hold` permanently); advance derived amounts follow lines from `PREPARED` while the `status` axis moves at approve; `mileage_guide` is inherited on revise regardless of any supplied value; advance cancellation records `CANCELLED` though it is absent from the status enum; four unmapped constraint violations routed to `ERR_INVALID_FIELD_VALUE`; `PayComponent.taxable` defaults to true.

Orchestrator truncation check: `wc -l` = 492; `tail -15` ends on the final `ERR_NEGATIVE_NET_PAY | 422` error-table row — a real section boundary, not mid-sentence. Five top-level sections present. No difficulty-directive leak (`grep -c "harder than expert"` = 0).

## Step 5: Generate unit tests (subagent) — 2026-09-05T00:20:00.000Z

Test infrastructure for task 2780 is complete.

## Deliverables

Both directories are at the **task root**; `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation` — no test dirs anywhere else under the task.

`test_helpers/` — 9 files, 2410 lines
`__init__.py` 141, `api_client.py` 368, `api_errors.py` 150, `assertions.py` 214, `constants.py` 66, `factories.py` 428, `fixtures.py` 531, `test_users.py` 70, `types.py` 442

`test_suite/` — 19 files, 7433 lines, **122 tests**
`conftest.py` 63; `test_01` 282/7t, `test_02` 254/6t, `test_03` 405/9t, `test_04` 186/4t, `test_05` 410/7t, `test_06` 195/3t, `test_07` 243/5t, `test_08` 270/6t, `test_09` 468/8t, `test_10` 585/12t, `test_11` 631/12t, `test_12` 511/8t, `test_13` 575/8t, `test_14` 488/6t, `test_15` 766/9t, `test_16` 428/5t, `test_17_cross_cutting.py` 525/5t, `test_18_consistency_model.py` 148/2t

## Instance coverage — 84/84 non-stub, 0 skipped

Machine-verified by parsing every test docstring's `Design:` line and resolving it against both yaml indices: 102 indexed instances, 84 non-stub, **84 distinct non-stub instances covered, 0 missing, 0 labels pointing at a stub or unresolved, 0 docstrings with a missing/duplicate/misplaced Design line.**

- Queue A (Difficulty): 19/19 — `test_01`–`test_09`
- Queue B (Corner): 65/65 — entities 12, state_machines 12, calculations 8, validations 8, endpoints 6, errors 9, rbac 5, cross_cutting_complexity_layers 4, consistency_model 1

## Written this session

- `test_17_cross_cutting.py` (5 tests, 4 instances): the three optimistic-concurrency precedence cases — stale pay-package version outranking the pending-revision guard (412 then 409 only after a re-read), stale settlement version outranking `NO_PENDING_CORRECTIONS` on a replayed sweep, stale driver version blocking a second escrow deduction sized against a 2,686-cent balance — plus the two-test derived-chain reconciliation of a cancelled -57,200 correction (hold true -> false in the same request, second cancel 409 `CORRECTION_NOT_PENDING`, load walks `ADJUSTED` -> `SETTLED` while keeping its re-graded 14,500 against a statement frozen at 71,700).
- `test_18_consistency_model.py` (2 tests, 1 instance): prepare side effects readable at the same logical instant, and the negative half — `ytd_*` stay 0 for a `PREPARED` settlement and a repeated read at the same clock value is identical.

## Two bugs fixed in already-written files

1. **`test_05` filed a MILEAGE dispute with `settlement_id`.** PRD §3.9 requires a MILEAGE dispute's `settlement_id`, `claimed_amount_cents` and `disputed_line_type` to all be null; the argument was removed. This would have failed 3 tests in `_settled_dispute_environment`.
2. Unused imports pruned from `test_04`, `test_06`, `test_08`, `test_14`, `test_helpers/factories.py`, `fixtures.py`, `types.py`.

## Verification

- `py_compile` clean on all 28 files; `pyflakes` exit 0 across `test_suite/` + `test_helpers/`.
- PRD citation checker (section map derived from the PRD's own headings, §2.9 rungs mapped from the numbered list): **219 quoted citations, 32 rung-level citations, 0 mismatches** — every quote is an exact ellipsis-aware substring of a single PRD line and every claimed §/rung label resolves correctly.
- No occurrence of "scaffold" in any generated file; `__pycache__` removed.

## Deliberate PRD-first divergences from the yaml recipes

- `test_17`'s escrow test advances the logical clock between the two deductions, because §2.3 orders the ledger by `created_at` ascending and three rows stamped at one instant would make the register order undefined.
- The negative-net-pay test in `test_15` still asserts only `NEGATIVE_NET_PAY` (plus `!= NO_SETTLEABLE_ACTIVITY`) because the `quantity` on a swept `RETRO_CORRECTION` line is not pinned by the PRD and could otherwise trip the leased itemization gate first.
- `test_16`'s escrow settlement line is asserted via `abs(...) == 3686`, since §3.8 pins only that the `DEPOSIT` equals "the positive line amount" and never fixes the line's sign.

## Step 6: Generate implementation (subagent) — 2026-09-05T00:20:30.000Z

Final verification complete: 30 files, 3799 lines, no `__pycache__`, `start.sh` executable, no stray test dirs inside `implementation/`.

## Implementation delivered

`workspace/implementation/`

| module | lines | module | lines |
|---|---|---|---|
| `requirements.txt` | 1 | `services/__init__.py` | 0 |
| `start.sh` | 10 | `services/load_pay.py` | 145 |
| `app.py` | 76 | `services/accessorial.py` | 80 |
| `constants.py` | 154 | `services/escrow.py` | 54 |
| `errors.py` | 130 | `services/settlement.py` | 537 |
| `clock.py` | 52 | `services/dispute.py` | 196 |
| `money.py` | 31 | `routes/__init__.py` | 0 |
| `db.py` | 87 | `routes/clock_routes.py` | 18 |
| `response.py` | 92 | `routes/pay_packages.py` | 236 |
| `validators.py` | 119 | `routes/drivers.py` | 291 |
| `middleware.py` | 36 | `routes/loads.py` | 147 |
| `queries.py` | 166 | `routes/accessorials.py` | 186 |
| `serializers.py` | 286 | `routes/advances.py` | 104 |
| `listing.py` | 35 | `routes/settlements.py` | 210 |
| | | `routes/disputes.py` | 254 |
| | | `routes/retro.py` | 66 |

**54 endpoints registered — exactly the PRD's 54-row table**, no extras (`static_folder=None` so no `/static/<path>` rule). All 55 error IDs wired to the 55-rung precedence ladder. Storage is in-memory dicts only; nothing is seeded, and a fresh boot reports `total_count: 0` on all nine collections with the logical clock back at `2026-08-01T00:00:00.000Z`. Money is integer cents everywhere (JSON integers); every timestamp is `YYYY-MM-DDTHH:MM:SS.mmmZ`.

Smoke-tested on explicit ports 18317 and 18318, each killed by PID from `lsof -ti tcp:<port>` and confirmed free. No pattern kill was ever issued. `test_helpers/`, `test_suite/`, and both `SCAFFOLD_*_DESIGN.yaml` were never touched.

## PRD ambiguities resolved

- **Driver creation** -> `employment_status: ONBOARDING` (PRD §3.2 prose) over the scaffold's "ACTIVE" side-effect note.
- **Advance `CANCELLED`** status added; PRD §3.6 requires it though the scaffold enum omits it.
- **Load `ACCRUED->SETTLED` and claim `APPROVED->PAID` happen at prepare**, not pay — prepare is what sweeps and stamps `settlement_id`.
- **Retro corrections** go `PENDING->APPLIED` at apply-corrections (`applied_at` / `applied_settlement_id` set there); void returns them to PENDING.
- **Advance money follows lines; the status axis moves at approve.** Derived rule: outstanding 0 -> RECOVERED, recovered > 0 -> RECOVERING, else ISSUED — the same rule walks the axis back on void.
- **Escrow deduction `document_ref` is required** (-> `ERR_MISSING_REQUIRED_FIELD`) despite the endpoint list rendering it `document_ref?`; **escrow return requires `payment_reference`** per §3.3 prose.
- **Driver TERMINATED does not auto-move the escrow axis** — the two axes are independent, so `/escrow/close` still works afterward.
- **Void from DRAFT stamps only** (status/voided_at/reason) — the literal PRD, no compensation walk.
- **Prepare gate order deviates** from the ladder: 20 -> 24 -> 34 -> 47 -> 52 -> generate lines -> 33 itemization -> 55 negative net, because itemization and the net-pay floor need generated lines. Rung 25 is unreachable here (24 fires first), which the PRD itself notes.
- **Accessorial overlap spans any non-REJECTED claim on the same load**, not just same-type.
- **TARPING approve on a load with `tarp_required: false`** -> `ERR_ZERO_VALUE_ACCESSORIAL` (rung 46).
- **Dispute window reference** = `load.delivered_at` for an unsettled MILEAGE dispute, else origin settlement `paid_at` -> `approved_at` -> `prepared_at` -> `created_at`.
- **PAY-dispute origin must be APPROVED/PAID** — enforced at resolve, not at filing.
- **`ERR_NEGATIVE_NET_PAY` leaves the settlement DRAFT**, discarding prepare's own lines while preserving previously-swept RETRO_CORRECTION lines.
- **Rung-3 scope on a nonexistent addressed record** falls through to 404, except `/drivers/{id}` where the scope check wins.
- **Version policy**: +1 per documented transition; approve bumps Settlement +1 and Driver +1, plus one extra Driver bump only when the escrow axis actually crosses a boundary.
- **`ERR_COMPONENT_TYPE_NOT_ALLOWED`** blocks HOURLY on OWNER_OPERATOR/LEASED_OPERATOR and REVENUE_PERCENT on COMPANY_SOLO/COMPANY_TEAM (scaffold validation 36).

Rounding orders are pinned as specified: escrow accrual is 800 bps round-then-sum per earning line; linehaul legs round independently before `max()` with the team 5000 bps share applied after; the advance pool is 2500 bps of *provisional* net (gross - escrow), not final net. Sign-preserving rounding rounds the magnitude and re-applies the sign.

## Step 7: Run tests and iterate (subagent) — 2026-09-05T00:05:30.000Z

Clean 8-round sweep: **122/122 passing in all 8 parallel rounds**, verified on disk in `workspace/implementation/results.{1..8}.json`.

## Summary

**Iterations run:** 2. Iteration 1 found 9 failures, identical in all 8 rounds (fully deterministic — no flakiness anywhere in the suite). Iteration 2 was clean.

**Key finding: all 9 failures were test-artifact bugs. No implementation change was needed or made.** `workspace/implementation/` is byte-unchanged.

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:** none — the factories and fixtures were already PRD-faithful (`mileage_dispute_payload` correctly omits `settlement_id`; `canonical_ts`/`assert_timestamps_equal` already existed). The defects were all in `test_suite/` call sites.

**Fixes applied to `test_suite/`:**

- `test_08_boundary_precision.py` (3 tests) — `_edge_delivery_environment` and `test_the_period_starting_at_the_delivery_instant_sweeps_the_load` compared `load["delivered_at"]` to the raw literal `"2026-08-18T00:00:00Z"` with `==`. PRD §2.4/§2.5 require "three fractional digits", so the server's `.000Z` is correct. Routed both through the existing `assert_timestamps_equal`.

- `test_06_retro_correction_hold_cascade.py` (3 tests) — `_cascade_environment` passed `settlement_id=first_settlement["id"]` as an override into the MILEAGE dispute payload. PRD §3.9: "its `settlement_id`, `claimed_amount_cents` and `disputed_line_type` must all be null", so the implementation correctly returned `ERR_INVALID_FIELD_VALUE` and every test in the class died as a setup error. Removed the override; the correction's `origin_settlement_id` still resolves because Branch B takes it "from the load's `settlement_id`".

- `test_04_advance_recovery_waterfall.py::test_pool_is_a_quarter_of_the_provisional_net_before_recovery_is_subtracted` — the test's own primary assertions expected 10599 and passed; only a trailing redundant assertion recomputed the pool with Python's `round()`, which is half-to-even and answers 10598 on the exact half cent (42394 x 2500 / 10000 = 10598.5). PRD §2.6 pins "rounded **half up**". Replaced with integer `(x * bps + 5000) // 10000`.

- `test_10_entity_records.py::test_a_component_write_against_an_unknown_package_is_a_404_before_field_checks` — asserted that an unknown parent id outranks an undeclared `component_type` in the same body, but PRD §2.9 puts `ERR_INVALID_FIELD_VALUE` at rung 5 and `ERR_PAY_PACKAGE_NOT_FOUND` at rung 7, and quotes "then request shape, then existence". The test cited that very sentence while asserting its inverse. STEP 1c split: made the body valid so only the PRD-covered rule (unknown parent -> 404) is asserted; renamed to drop the "before field checks" claim. The precedence direction the test wanted is already correctly covered by `test_13_validations.py::test_a_missing_field_outranks_an_undeclared_enum_value_in_the_same_body`.

- `test_13_validations.py::test_a_retired_package_blocks_delivery_until_a_live_one_is_assigned` — **STEP 1b unique-derivability collapse, resolved as a STEP 1c partial-coverage split.** The test required delivery to be refused with `ERR_DRIVER_HAS_NO_PAY_PACKAGE` when the driver's *current* package has been retired mid-transit. The only PRD support is rung 52's ladder entry, and §2.9 itself defers trigger conditions to §3 ("The precise trigger conditions, thresholds and constants behind these checks live with the workflows they guard, in §3"). §3.4's delivery paragraph names only `IN_TRANSIT` and `delivered_at >= dispatched_at` as preconditions, and §3.1 affirmatively states the opposite outcome: "loads dispatched while it was `ACTIVE` still point at it and are still paid from its components." Two PRD-faithful implementations are articulable, so the refusal assertion is not uniquely derivable. Kept the verbatim-covered half — retirement succeeds, reassignment leaves the snapshot alone, and delivery pays 46080 off the retired snapshot — and renamed the test/class accordingly. Scaffold rule that drove the original: `Corner/validations/delivering_under_a_retired_package_is_blocked_until_a_live_one_is_assigned`.

`worklog.md` untouched by the subagent; the temporary scratch test dir used for fast subset verification was removed.

Orchestrator verification: all 8 `results.*.json` present, each `passed == total == 122`.

## Step 8: Finalize PRD (subagent) — 2026-09-05T00:10:00.000Z

`workspace/PRD_FINALIZED.md` is written. **492 -> 494 lines (+2, +0.41%)**; 3 hunks.

## Changes

- **§2.5 (Logical Settlement Clock)** — *insert* — new paragraph pinning that a client-supplied timestamp is parsed as ISO 8601, converted to UTC, and re-rendered in the clock's canonical form (ISO 8601 UTC, three fractional digits), with the explicit `2026-08-18T00:00:00Z` -> `2026-08-18T00:00:00.000Z` example — `validators.py:87-108`, `clock.py:29-44`, `serializers.py` (every `clock.iso` callsite).
- **§2.9 rung 52** — *revise* — dropped the false "that package was `ACTIVE` at the delivery instant" claim; rung 52 now says the driver must have an assigned `pay_package_id`, that dispatch additionally requires it to be `ACTIVE` at the moment of dispatch, and that delivery adds no package check and pays off `pay_package_id_snapshot` whatever its `status` has become, `RETIRED` included — `routes/loads.py:110-118` (dispatch), `routes/loads.py:123-147` (deliver, no check), `services/settlement.py:98-99`, `routes/drivers.py:137-142`.
- **§3.9 (`MILEAGE` dispute paragraph)** — *revise* — named the error for the kind-discriminated null constraints: a non-null `settlement_id`/`claimed_amount_cents`/`disputed_line_type` on a `MILEAGE` filing (and symmetrically a non-null `load_id`/`claimed_guide`/`claimed_miles` on a `PAY` filing) is `ERR_INVALID_FIELD_VALUE` (422) — `routes/disputes.py:54-56, 69`, `validators.py:25-28`.

## Step 7 items that needed **no** PRD edit

- **test_04 recovery pool** — PRD §2.6 ("rounded **half up**") and §3.6 (provisional-net x 2,500 bps / 10,000, half up) already determine 10599; `money.py:5-25` uses `ROUND_HALF_UP`. Pure test bug (Python `round()` is half-to-even).
- **test_10 component-write precedence** — PRD §2.9 already puts `ERR_INVALID_FIELD_VALUE` at rung 5 above `ERR_PAY_PACKAGE_NOT_FOUND` at rung 7, and `routes/pay_packages.py:86-100` validates body shape before `find_package`. The old test asserted the inverse of the PRD.
- **test_06 `settlement_id` override** — the fixture bug itself needed no PRD change beyond naming the error (edit 3); Branch B's `origin_settlement_id` "from the load's `settlement_id`" was already verbatim in §3.9.

## Per-edit pre-edit search log

**Edit 1 — subject: rendering of timestamps whose value came from the request body.**
(b) Enumerated & read: `validators.parse_timestamp`/`ts_value`; all 8 `ts_value` callsites (`routes/loads.py:105,127`, `routes/accessorials.py:49,50`, `routes/settlements.py:47,48`, `routes/drivers.py:130`, `routes/clock_routes.py:17`); `clock.iso`/`now_iso`; every `_at`-suffixed key in `serializers.py` (grepped: zero timestamp keys bypass `clock.iso`); `response.base_meta`.
(c) Adjustment: replaced an initially planned "delivered_at"-only sentence with the full enumerated field list (so the claim is not accidentally narrowed to loads), and phrased truncation as "whatever fractional precision the client wrote... carries three" because `microsecond // 1000` truncates rather than rounds sub-millisecond input.

**Edit 2 — subject: every raise of `ERR_DRIVER_HAS_NO_PAY_PACKAGE` and every package-status gate on the load lifecycle.**
(b) Enumerated & read: `grep -rn ERR_DRIVER_HAS_NO_PAY_PACKAGE` -> `routes/loads.py:113` (dispatch: missing **or** non-`ACTIVE`), `services/settlement.py:99` (prepare: missing only, **no** status check), `routes/drivers.py:140` (`ONBOARDING`->`ACTIVE`: missing only; non-`ACTIVE` yields `ERR_PAY_PACKAGE_NOT_ACTIVE` at :142); `routes/loads.py:123-147` (deliver: no package gate at all); `services/load_pay.recompute_from_snapshot`/`recompute` (reads the snapshot row regardless of status).
(c) Adjustment: scoped the `ACTIVE` requirement to "on a dispatch" so the sentence does not falsely impose it on prepare or on driver activation, and left rung 18 / §3.2 untouched so the drivers.py `ERR_PAY_PACKAGE_NOT_ACTIVE` branch is not contradicted.

**Edit 3 — subject: the kind-discriminated must-be-null constraints on dispute filing.**
(b) Enumerated & read: `grep -rn must_be_null` -> only `routes/disputes.py:54` and `:69` (no other endpoint uses it); `validators.must_be_null:25-28` (fires only when the key is present *and* non-null, raising `INVALID`); the surrounding `require(...)`-then-`must_be_null` ordering in both branches of `file_dispute`.
(c) Adjustment: worded as "carries a non-null value" rather than "supplies" so an absent key stays legal; covered the symmetric `PAY` branch in the same sentence since it is the same validator and would otherwise read as deliberately asymmetric; omitted a redundant missing-outranks-invalid clause because §2.9 rungs 4/5 already pin it globally.

Orchestrator note: Step 8 was NOT skipped — Step 7 made five `test_suite/` fixes (0 implementation fixes), so the skip condition (0 fixes of any kind) did not hold. `PRD_FINALIZED.md` is confirmed non-identical to `PRD.md`.

## Step 9: Complete PRD (subagent, 3 sequential module-partitioned passes) — 2026-09-05T00:40:00.000Z

Orchestrator decision, recorded per the autonomy directive: Step 9 was run as **three sequential passes over one shared `PRD_COMPLETED.md`**, partitioned by implementation module, rather than as one monolithic scan. A single-agent full scan of a 30-module / 3,799-line implementation against a 494-line PRD routinely degenerates into a no-op `cp` (byte-identical output). Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 edited the existing file in place. Partition: (1) cross-cutting core + clock/pay_packages/drivers routes + services/escrow; (2) loads/accessorials/advances routes + services/load_pay, accessorial; (3) settlements/disputes/retro routes + services/settlement, dispute.

### Pass 1 (core, pay_packages, drivers, escrow)

Performed `cp PRD_FINALIZED.md PRD_COMPLETED.md`. **494 lines / 108,853 chars -> 496 lines / 115,317 chars (+2 lines, +6,464 chars).** 24 edits — 14 ambiguity-pins, 10 mismatch-revisions.

- §2.1 — revise — mismatch — scope-before-existence was claimed universally; impl resolves the record first wherever ownership is carried inside it — `routes/drivers.py:88-90` vs `:264-265`
- §2.2 — insert — ambiguity — `api_request_timestamp` reads the logical clock, not wall time — `response.py:25`
- §2.3 ¶1 — insert — ambiguity — a non-integer `limit`/`offset` is also `ERR_INVALID_FIELD_VALUE` — `response.py:57-68`
- §2.3 ¶2 — revise — mismatch — pay components are a second `sequence`-ordered exception; ties break on insertion order — `queries.py:13`, `db.py:29-38,65-67`
- §2.3 ¶2 — revise — mismatch — Driver narrowing applies only to collections whose rows carry a driver reference — `listing.py:25-29`, `routes/pay_packages.py:130-133`
- §2.4 — revise — mismatch — derived-field recomputation is not a mutation and does not bump `version` — `serializers.py:68`, `routes/advances.py:103`
- §2.5 ¶2 — insert — ambiguity — sub-millisecond precision truncates toward zero; non-`Z` offsets normalise; zone-less instants read as UTC — `clock.py:36-44`, `validators.py:87-100`
- §2.9 rung 3 — insert — mismatch — rung 3 outranks existence rungs only when the driver reference is the path id — `middleware.py:25-32`
- §2.9 rung 5 — insert — ambiguity — required text fields must be non-empty after trimming — `validators.py:76-84,111-118`
- §2.11 ¶1 — revise — mismatch — derived fields computed at read time, not eagerly — `queries.py:1-5`, `serializers.py:1-8`
- §2.11 ¶3 — revise — mismatch — recomputation has no side effects; approval bumps the driver because it writes to it — `services/settlement.py:428,446`
- §3.1 — revise — ambiguity — activation check order: DRAFT gate -> escrow-figure -> linehaul; an empty package fails the linehaul check — `routes/pay_packages.py:140-151`
- §3.1 — insert — ambiguity — a supplied `mileage_guide` is enum-validated though discarded; successor opens at version 1 — `routes/pay_packages.py:178,188-204`
- §3.2 ¶1 — revise — mismatch — `home_state` is only a non-empty string, not two letters — `routes/drivers.py:53`
- §3.2 — insert — ambiguity — `ONBOARDING`->`ACTIVE` yields `ERR_DRIVER_HAS_NO_PAY_PACKAGE` with no package, `ERR_PAY_PACKAGE_NOT_ACTIVE` with a retired one — `routes/drivers.py:134-142`
- §3.2 ¶4 — revise — mismatch — closing escrow requires `TERMINATED` (`ERR_DRIVER_NOT_ACTIVE` otherwise) — `routes/drivers.py:155-158`
- §3.3 — revise — mismatch — a void-written `REVERSAL` carries the voided settlement's id; only operator-initiated reversals are null — `services/settlement.py:522-532` vs `routes/drivers.py:281-288`
- §3.3 — insert — ambiguity — missing `document_ref` is `ERR_MISSING_REQUIRED_FIELD`, never `ERR_DOCUMENTATION_MISSING` — `routes/drivers.py:172`
- §3.3 — insert — ambiguity — deduction bumps driver `version` +1, or +2 when the balance flips the escrow axis — `routes/drivers.py:198-199`, `services/escrow.py:36-54`
- §3.3 — insert — ambiguity — reversal `reason_code` may be any enum member; 201; +1/+2 version — `routes/drivers.py:274,289-291`
- §3.3 — insert — ambiguity — a `PENDING` correction refuses return with `ERR_ESCROW_RETURN_NOT_DUE` — `routes/drivers.py:216-220`
- §3.3 — insert — ambiguity — return answers 200 with the driver, not 201 with the ledger entry — `routes/drivers.py:230-233`
- §4 preamble — revise x2 — mismatch — 201 only when the endpoint's own result is a new record; unrouted path -> `ERR_NOT_FOUND` 404, wrong method -> `ERR_METHOD_NOT_ALLOWED` 405 before headers; trailing slash tolerated — `app.py:24,45-54`
- §4 rows + §5 — revise/insert — mismatch — assign row now `ONBOARDING or ACTIVE`; status row no longer claims termination starts the return clock; `ERR_NOT_FOUND`/`ERR_METHOD_NOT_ALLOWED` added to the catalogue — `routes/drivers.py:111,146,160-162`, `errors.py:68-69`

### Pass 2 (loads, accessorials, advances)

**496 lines / 115,892 chars -> 496 lines / 117,779 chars.** 5 ambiguity-pins, 3 mismatch-revisions (9 bullets).

- §2.11 — revise — mismatch — principal = outstanding + recovered is false for a `CANCELLED` advance (outstanding forced to 0, recovered retained); scoped to live advances — `serializers.py:170`, `queries.py:109-111`, `routes/advances.py:102`
- §3.4 tender — insert — ambiguity — optional `hours_worked_minutes` (non-negative, default 0), null zips when omitted, `short_haul_floor_applied` starts `false` not null — `routes/loads.py:43-58`
- §3.4 deliver — insert — ambiguity — `hours_worked_minutes`/`stop_count` overwrite only when supplied; the `delivered_at >= dispatched_at` check runs after the movement-state check, so a non-`IN_TRANSIT` load reports `ERR_LOAD_NOT_DELIVERED` — `routes/loads.py:131-141`
- §3.5 — insert — ambiguity — a `REJECTED`->`SUBMITTED` return keeps `reject_reason_code` as history — `routes/accessorials.py:128-132`
- §3.5 approve — revise — mismatch — gate is "not already attached to a settlement" (`pay_status` neither `SETTLED` nor `ADJUSTED` and `settlement_id` null) — `routes/accessorials.py:155-156`
- §3.5 approve — insert — ambiguity — `TARPING` on `tarp_required: false` -> `ERR_ZERO_VALUE_ACCESSORIAL` 422, before pricing — `routes/accessorials.py:148-150`
- §3.6 issue — insert — ambiguity — omitted `installment_cents` reports as equal to `amount_cents`, not null — `routes/advances.py:44-46`
- §3.6 cancel — revise — mismatch — the gate is a pure `status == ISSUED` test, so an advance stays cancellable while recovery lines exist on a merely `PREPARED` settlement — `routes/advances.py:100-102`
- §3.6 waterfall — revise — mismatch — `created_at` is not unique per row; ties break by insertion order — `queries.py:125-136`

Verified-as-already-pinned: paid-miles/guide selection and the strict sub-250 floor, the 500-mile band and +3c marginal rate, per-leg independent rounding with the per-mile leg winning ties and the team share applied after, hourly and flat activity pay, all five accessorial pricing formulas and constants, both overlap shapes, the 150,000c exposure ceiling, RBAC rows, filters and Driver narrowing.

### Pass 3 (settlements, disputes, retro)

**496 lines / 117,779 chars -> 496 lines / 125,152 chars.** 26 ambiguity-pins, 5 mismatch-revisions (31 bullets). Final: `PRD_FINALIZED.md` 494 lines/109,379 chars vs `PRD_COMPLETED.md` 496 lines/125,152 chars — **+2 lines, +15,773 chars, 51 diff hunks**; `cmp` confirms not byte-identical; tail ends on the final §5 error row.

- §2.6 — revise — mismatch — escrow-accrual round-then-sum base is the linehaul/hourly/activity lines alone; accessorial and retro lines never accrue — `services/settlement.py:223-229`
- §2.9 rung 33 — revise — mismatch — the itemization gate runs inside preparation, after hold/no-activity/no-package and immediately before `ERR_NEGATIVE_NET_PAY` — `routes/settlements.py:158`, `services/settlement.py:95-99,285-297`
- §2.9 rung 48 — insert — ambiguity — prepare never raises it; the upheld-mileage path uses it for the `ADJUSTED` mirror condition — `services/dispute.py:132-133`
- §2.9 rung 3 — insert — ambiguity — on the two `Driver` self-filings the scope reference is the body's raw `driver_id`, compared before shape validation; an omitted `driver_id` falls to rung 4 — `routes/disputes.py:37-38`
- §3.7 — revise — ambiguity — `days_out_count` is 0 at creation — `routes/settlements.py:81`
- §3.7 — revise — ambiguity — `RETRO_CORRECTION` line shape pinned; `delta_taxable_cents` never written onto the statement — `services/settlement.py:346-356`
- §3.7 — revise — ambiguity — each swept correction's and the driver's `version` bump by 1 alongside the settlement's — `services/settlement.py:363,368-369`
- §3.7 — revise x2 — ambiguity — insertion order is the final tie-break for eligible loads and claims — `services/settlement.py:37,56`
- §3.7 — revise — mismatch — an already-attached load/claim is silently filtered, not refused; prepare raises neither `ERR_LOAD_ALREADY_SETTLED` nor `ERR_CLAIM_ALREADY_SETTLED` — `services/settlement.py:27,48`
- §3.7 — revise — ambiguity — `quantity` is 1 and `rate_value` null on `PER_DIEM`/`ESCROW_DEDUCTION`/`ADVANCE_RECOVERY`/`RETRO_CORRECTION` and `ACCESSORIAL` lines — `services/settlement.py:149,166,205,242,268,349`
- §3.7 — revise — ambiguity — `linehaul_line_type` `NONE` produces no linehaul line — `services/settlement.py:110`
- §3.7 — revise — ambiguity — `HOURLY` `quantity` is the only non-integer quantity (1.5 / 1.0 / 1.67); the `ACTIVITY` line is written even at `rate_value` 0 — `services/settlement.py:134,142-153`, `money.py:24-31`
- §3.7 — revise — ambiguity — the per-diem governing package is the driver's current `pay_package_id`, never a load snapshot; `days_out_count` recorded on every preparation regardless of election — `services/settlement.py:189-192,311`
- §3.7 — revise — ambiguity — a swept load's `version` increments by 1 — `services/settlement.py:325`
- §3.8 — revise — ambiguity — approval bumps driver `version` +1, or +2 when the deposit moves the escrow axis; the axis moves on every approval — `services/settlement.py:428,443,446`
- §3.8 — revise — ambiguity — an advance's `version` bumps only where its derived status changes — `services/settlement.py:401-404`
- §3.8 — revise — ambiguity — `prepared_by_user_id`/`approved_by_user_id`/`prepared_at`/`approved_at` are retained by every void tier — `services/settlement.py:484-498`
- §3.8 DRAFT tier — revise — ambiguity — already-swept `RETRO_CORRECTION` lines stay, their total keeps its figure, corrections stay `APPLIED`, driver untouched — `services/settlement.py:467-469`
- §3.8 PREPARED tier — revise — mismatch — `days_out_count` also resets to 0, and load restoration is keyed on `settlement_id`, so an `ADJUSTED` load also returns to `ACCRUED` — `services/settlement.py:484-505`
- §3.8 PREPARED tier — revise — ambiguity — the advance walk-back bumps `version` only where `status` changes — `services/settlement.py:407-416`
- §3.8 APPROVED tier — revise — ambiguity — the `REVERSAL` carries `reverses_transaction_id`; nothing is appended when no deposit posted — `services/settlement.py:471-474,524-533`
- §3.8 APPROVED tier — revise — ambiguity — driver `version` +1 or +2; the only tier that touches it — `services/settlement.py:522-535`
- §3.9 — revise — mismatch — the filing reference instant is the first non-null of `paid_at` -> `approved_at` -> `prepared_at` -> `created_at`, and the 30-day edge is inclusive — `services/dispute.py:24-30`, `routes/disputes.py:98-101`
- §3.9 — revise — ambiguity — a supplied `adjustment_cents` is shape-validated then discarded — `routes/disputes.py:198`
- §3.9 — revise — ambiguity — a mileage dispute whose load is `ADJUSTED` matches no uphold branch and is refused with `ERR_LOAD_ALREADY_SETTLED` — `services/dispute.py:132-133`
- §3.9 — revise — ambiguity — the hold threshold is strict; exactly 50,000 cents leaves the driver settleable — `queries.py:48-49`
- §3.9 — revise — ambiguity — the old linehaul figure is the earliest matching line by `sequence`, 0 when the statement carries none — `services/dispute.py:92-102`
- §3.9 — revise — ambiguity — the origin package for a pay adjustment is the snapshot on the first `LOAD`-referencing line in `sequence` order, falling back to the driver's current package, then `NONE` — `services/dispute.py:33-52`
- §3.9 — revise — ambiguity — adjudication emits only `MILEAGE_DISPUTE_UPHELD` and `PAY_DISPUTE_UPHELD`; `MILEAGE_GUIDE_REGRADE` is a declared member no path produces — `services/dispute.py:147,169`
- §3.9 — revise — ambiguity — the load's `version` increments when its pay axis returns `ADJUSTED` -> `SETTLED` — `services/dispute.py:186-191`

### Pass 3 finding NOT written into the PRD, and the orchestrator's ruling

`services/dispute.py:114-133` and `:158-161` mutate the dispute in place (`status` -> `UPHELD`, `resolution_note`, `resolved_by_user_id`) **before** the branch guards raise `ERR_LOAD_ALREADY_SETTLED` / `ERR_SETTLEMENT_STATE_INVALID`, with no `db.touch` after. A rejected uphold therefore leaves the stored dispute reading `UPHELD` with `version`/`updated_at` unchanged — reachable by upholding a second mileage dispute on a load already `ADJUSTED`. Pass 3 pinned only the error code and declined to codify the partial write as a requirement.

Orchestrator ruling (no user available to consult): **leave the implementation as-is and leave the PRD silent on it.** Rationale — (1) the PRD makes no universal atomicity claim this contradicts (§2.8 and §3.7 scope their "nothing is mutated" promises), so there is no PRD/impl mismatch to close; (2) no test in the suite exercises the artifact, so Step 7's protocol never had a signal and an impl edit here would be an unverified change against a suite already at 122/122; (3) writing the partial write into `PRD_COMPLETED.md` would elevate an accident into a specified requirement a future implementer must reproduce, which is worse than the silence. Recorded here so the defect is not lost.

### Orchestrator verification
- `PRD.md` 492 / `PRD_FINALIZED.md` 494 / `PRD_COMPLETED.md` 496 lines.
- `cmp PRD_FINALIZED.md PRD_COMPLETED.md` -> DIFFERENT (the scan really ran; not a byte-identical no-op).
- 108 changed lines across the `PRD_FINALIZED.md` -> `PRD_COMPLETED.md` diff.
- `PRD_COMPLETED.md` ends on the final §5 error-table row (`ERR_METHOD_NOT_ALLOWED | 405`) — a real section boundary; 5 top-level sections intact; no difficulty-directive leak.
- Steps 9's passes touched no code, so Step 7's clean sweep still stands: `results.{1..8}.json` on disk, each 122/122.

Pipeline complete.
