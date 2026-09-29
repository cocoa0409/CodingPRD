# Worklog — task_2904_collision_repair_estimating_parts_procurement

## Step 1: Create task directory — 2026-09-05T14:03:30.955142376Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2904_collision_repair_estimating_parts_procurement and its workspace/ subdirectory. Index 2904 was pre-assigned by the orchestrator prompt; no scan of ./tasks/ was performed.

## Step 2: Generate scaffold — 2026-09-05T15:41:27.100031166Z

All three scaffold artifacts are complete and the linter is clean.

## Files
- `SCAFFOLD.yaml` (§1.0–§1.7 only; no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1970 lines, single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (4668 lines, single key `scaffold_corner_design`)

## SCAFFOLD.yaml surface
14 entities (Customer, Insurer, RepairOrder, DamageLine, EstimateLine, Supplement, PartsVendor, PartsLine, ProcedureRecord, CalibrationBay, Stall, StageAssignment, PartsDelayEvent, QcInspection) · 8 state machines / 44 transitions · 2 concurrency rules (both OCC on `expected_repair_order_version` -> 412 `ERR_STALE_REPAIR_ORDER_VERSION`) · 9 calculations · 62 ordered validations · **56 endpoints (33 POST, 22 GET, 1 PATCH)** · 61 errors · 7 roles. Profile: `multi_party_negotiation` / `workflow_orchestration`, layers `cascading_side_effects, dual_variant_calculation, optimistic_concurrency, derived_field_reconciliation`, `role_model: segregation_of_duties`, `consistency_model: immediate`, `expert_plus`.

## §1.8 — 9 rule ids / 21 instances
`dual_variant_calc` 2 · `combinatorial_formula` 2 · `non_linear_state_machine` 2 · `transitive_cascade` 2 · `priority_pair_validation_conflict` 3 · `boundary_precision_check` 3 · `cross_entity_state_dependency` 2 · `resource_temporal_overlap` 2 · `compensating_invariant` 3.

## §1.9 — 9 sections / 85 instances (66 real + 19 `excluded_because:` stubs)
entities 12 · state_machines 12 (2 stubs) · calculations 12 (4) · validations 10 (3) · endpoints 7 (1) · errors 17 (6) · rbac 6 · cross_cutting_complexity_layers 7 (3) · consistency_model 2. All 61 error ids are referenced by at least one instance; every stub citation resolves to an existing `<rule_id> / <instance_name>`.

## Lint verdict (verbatim)
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
Coverage
  §1.5 endpoints declared:    56
  §1.1 entities declared:     14
  §1.8 instances scanned:     21
  §1.9 instances scanned:     66
  Calls scanned (§1.8+§1.9):  1043

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
Also verified independently: no forbidden concurrency vocabulary anywhere, no duplicate instance names across the two design files, no stub carrying a `test_recipe`, and every `${var}` bound by an earlier `captures:`.

## Design adjudications made while generating
- **Blueprint from-set widened** to `{INTAKE, TEARDOWN}` in both the §1.2 precondition and validation 37, otherwise `ERR_NO_TEARDOWN_FINDINGS` was unreachable.
- **`WARRANTY_DAYS` pinned to 365** in the QcInspection field description and the QC side effect (was an unpinned constant).
- **`condition` enum pinned** on `POST /parts-lines/{id}/receive` to exactly `CORRECT | INCORRECT | DAMAGED`.
- `ERR_STAGE_SEQUENCE_INVALID` corrected from 422 to 409 in the difficulty file.
- **`ERR_CUSTOMER_CONSENT_REQUIRED` is only reachable via the declined path**: while a line is `PENDING_CONSENT` the posture is `CONSENT_REQUIRED` and rule 40's 409 pre-empts it; after the customer DECLINEs, the line leaves the totals, `customer_pay` falls to the 25000 deductible, the posture returns to OPEN and rule 79's 422 finally speaks on a still-`PRICE_LOCKED` line.
- **`ERR_INVALID_RECEIVE_QUANTITY` at install** needs the order already at REPAIR (else rule 37 pre-empts) plus a partial receive followed by a partial return, so zero un-returned units remain.
- **`ERR_OPEN_PARTS_DELAY`** is reachable only by receiving `INCORRECT` (opens an event nothing later closes), installing, passing QC, then delivering — which also demonstrates rule 81 before rule 82.
- Alternate part types land `PENDING_CONSENT`, which both freezes the posture and excludes the line from `estimate_totals`; recipes needing an alternate part inside the totals set `Customer.preferred_alternate_parts_ok: true`.
- Rule-order facts pinned by recipes: 73 outranks 74 (parts-installed before booking), 3 outranks 33 and 41, 2 outranks 20, 7 outranks 20, 1 outranks everything.

## Step 3: Copy shared files — 2026-09-05T15:41:31.961718100Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-05T15:57:32.811928955Z

PRD complete and verified.

**Output:** `workspace/PRD.md` — **509 lines** (106,728 bytes), written as one `Write` plus five `cat >> … <<'PRDEOF'` heredoc appends (no single call near the 64k cap).

**Final section heading:** `## 5. Error Code Catalogue`. The file ends on the last row of the 61-row error table (`| ERR_AUTHORIZED_AMOUNT_EXCEEDED | 402 |`) with a trailing newline — a real section boundary, nothing mid-sentence. Orchestrator independently confirmed the tail and the full §1–§5 heading list; NOT truncated.

**Section list**
- §1 Introduction
- §2 Global Specifications & System-Wide Principles — 2.1 Shop Operators, Outside Parties and Access Control; 2.2 API Response Structure (verbatim block); 2.3 Pagination; 2.4 Resource Identity, Timestamps and the Logical Clock; 2.5 Path Resolution and the Validation Ladder; 2.6 Money, Hours and Rounding Discipline; 2.7 Optimistic Concurrency on the Repair Order; 2.8 The Two Parallel Dimensions of a Repair Order, and of a Parts Line; 2.9 Cascades, Derived Fields and Conserved Quantities; 2.10 Insurer Policy, Shop Posted Rates and the Consent Threshold
- §3 Business Logic & Workflows — 3.1 Standing Registries; 3.2 Intake, Teardown and the Blueprint; 3.3 Procedure Research, Adherence Documentation and ADAS Calibration; 3.4 Building the Estimate, Allocating Refinish Time, and the Two Ways Out of a Blueprint; 3.5 Choosing a Part, Authorising the Money, and Negotiating the Price; 3.6 Ordering, Receipt, Returns, and the Commitment Ledger; 3.7 Supplements, Customer Consent, and the Authorisation Posture; 3.8 Booking the Shop and Driving the Stages; 3.9 Quality Control, the Warranty, Delivery, and Cycle Time
- §4 Endpoint Definitions (56-row table)
- §5 Error Code Catalogue (61-row table)

**Hard Contract 1 — Field-Name Coverage: PASS.** Run twice with independent extractions. Pass A used enumerated list (165 names) -> 0 missing. Pass B re-derived from the scaffold via a YAML parse: 146 `entities[].fields[].name` + 133 request_body/input/query_params/path_params/response keys = 229 required identifiers -> **0 missing**. (Both passes strip fenced code blocks before backtick pairing.) All 89 declared enum member values appear in backticks.

**Hard Contract 2 — Rule Coverage: PASS.** All 62 validations represented as the 17-rung ordered ladder in §2.5, priorities 1–90 preserved, both distinct `ERR_INVALID_REQUEST` rungs (shape at 5, numeric bounds at 9) written separately. All 61 error IDs appear in §1–§3 prose and in the §5 table. All 44 transitions across the 8 state dimensions covered. All 9 calculations plus the 3 variant pairs (PROVISIONAL/FINAL, ROLLING/LIFETIME, GROSS/NET) described with formulas and worked numbers. Both OCC rules, all `applies_to` scopes, all cross-entity cascades and all three conserved-quantity invariants stated.

**Hard Contract 3 — §3 Path Purity: PASS.** 1,182 backtick tokens in §3 (317 unique): 0 start with `/`, 0 are bare HTTP methods, 0 combine method+path, 0 contain a `/`. §1–§2 held to the same standard (0 violations). Paths/methods appear only in the §4 table.

**Coverage decisions** (scaffold self-contradictions, each resolved toward the better-corroborated source):
1. `warranty_expires_at` — field description and `QcInspection` PASS side effect both say logical clock + **365** days (`WARRANTY_DAYS = 365`); the qc-inspections endpoint `side_effects` says 1095. Wrote **365** (two sources + a named constant).
2. `unit_extended_cents` — field description adds `core_charge_cents` unconditionally; `parts_line_extended_price` adds it only when `part_type == RECONDITIONED`. Followed the **calculation** (conditional).
3. `restocking_fee_cents` — field description unconditional; calculation and return endpoint both restrict it to `return_reason == UNUSED`. Followed the **conditional** form.
4. `pay_type` vs `effective_rate_cents` — `pay_type` description implies only INSURER lines are rate-capped; `estimate_totals` step 1 applies `min(SHOP_RATE_CENTS, rate_ceiling_cents)` unconditionally. Followed the **formula**; `pay_type` records which party is billed, default `INSURER`.
5. `estimate_totals` step numbering — formula block puts supplies second, field descriptions number it fifth. Used the **field-description ordering**; results identical since supplies depends only on `labor_subtotal_cents`.

Constraints honoured: neither design yaml was opened, grepped or referenced; no sibling task directory read; scratch in `/tmp/task_2904_prd/`; no `pkill`.

## Step 6: Generate implementation — 2026-09-05T16:37:47.671875357Z

Implementation is complete, smoke-tested, and the smoke server is shut down (no listeners left on either test port; only targeted `kill <pid>` by port was used).

## Deliverable

`workspace/implementation/`

| File | Lines |
|---|---|
| `app.py` | 67 |
| `auth.py` | 74 |
| `calc.py` | 493 |
| `db.py` | 139 |
| `errors.py` | 90 |
| `guards.py` | 112 |
| `response.py` | 92 |
| `serialize.py` | 133 |
| `validate.py` | 144 |
| `routes/__init__.py` | 0 |
| `routes/registry.py` | 267 |
| `routes/orders.py` | 364 |
| `routes/estimate_lines.py` | 136 |
| `routes/supplements.py` | 233 |
| `routes/parts.py` | 479 |
| `routes/procedures.py` | 220 |
| `routes/assignments.py` | 216 |
| `requirements.txt` | 1 |
| `start.sh` (0755) | 15 |

Total 3275 lines. Every module passes `ast.parse`. No `__pycache__`, no data files — storage is a module-level dict-of-dicts in `db.py`, empty on every boot, nothing seeded (verified: all list endpoints return `total_count: 0` on a fresh process). `start.sh` reads `$PORT`, exports `PYTHONDONTWRITEBYTECODE`, and `exec`s `python3 app.py` in the foreground binding `0.0.0.0`.

## Endpoint coverage

**56 routes registered = 56 rows in the PRD §4 table**, matched path-for-path and method-for-method by diffing the Flask url_map against the table. Envelope verified: `meta.api_request_id` matches `req_[A-Z0-9]{20}`, `api_request_timestamp` is wall-clock with 3 fractional digits, lists carry `limit`/`offset`/`total_count`/`has_more`, errors are `response_type: "error"` with `data.error_id` + `data.message`. All 61 catalogue error ids are mapped to HTTP statuses in `errors.py`.

## Smoke tests — all green

Three scripted end-to-end runs under `/tmp/task_2904_impl/`:
1. Calculation spot-check, including the PRD's worked parts example (84,500 @ 7.5% discount -> `unit_extended_cents` 78,163).
2. Full happy path: registries -> order -> teardown finding -> procedure record -> blueprint -> estimate line -> lock -> parts line -> quote -> counter-offer -> requote -> accept-price -> order -> stall booking (+ conflict 409) -> REPAIR -> clock advance -> delay sweep (opened 1, idempotent 0 on repeat) -> receive -> vendor re-score 50->25 -> install -> adherence -> calibration schedule/result -> READY_FOR_QC (premature attempt correctly 422 `ERR_CALIBRATION_NOT_VERIFIED`) -> QC segregation 403 -> QC pass -> OCC 412 -> supplement -> deliver blocked 409 -> REQUEST_INFO -> resubmit -> invalid PARTIAL 422 -> APPROVE -> deliver -> cycle-time -> post-terminal 409.
3. Consent/return branch: PENDING_CONSENT parts line -> posture `CONSENT_REQUIRED` -> order refused -> wrong-customer consent 403 -> consent (OCC) -> line flips `CUSTOMER_CONSENTED` -> order/receive -> partial UNUSED return. **Conservation identity holds**: gross 30,303 = committed 20,202 + credit 8,081 + restocking loss 2,020. Plus total-loss terminality, unknown-field 400, bad-enum 400, unknown-route 404.

One apparent 10-test failure cluster in run 2 turned out to be a flawed test scenario (a 100,000-cent deductible clamped insurer authorization to 0, so `customer_pay_cents` legitimately crossed the 50,000 consent threshold and froze the order) — not an implementation defect; re-running with a realistic deductible passed clean.

## PRD ambiguities resolved

- **Warranty duration**: 365 days (PRD §3.9 + entity field) over the scaffold endpoint prose's 1095.
- **§2.5 ladder treated as normative** wherever section prose disagrees: (a) rung 13 `ERR_STAGE_PRECONDITION` fires before `ERR_PARTS_LINE_STATE`, against §3.6's prose order; (b) rung 14 safety outranks rung 16 constraints, so `ERR_PROCEDURE_ADHERENCE_MISSING` beats `ERR_PARTS_NOT_INSTALLED` on advance into REFINISH_CALIBRATION, against §3.8's bullet order; (c) rung 8 window validation precedes rung 13 `ERR_CALIBRATION_STATE`, against §3.3's "checked in this order".
- **Rung 10 existence order implemented literally**, including `vendor_id` -> `ERR_PARTS_VENDOR_NOT_FOUND` *before* the parts-line path id on `POST /parts-lines/{id}/quote`.
- **Rungs 3–4 skip when the order does not exist** so rung 10 can answer 404 rather than 403.
- **`effective_rate_cents`** is always `min(shop posted rate, insurer ceiling)`; `pay_type` does not alter it.
- **Core charge** added only for `part_type == RECONDITIONED`.
- **Restocking fee accumulates** per return (`existing + round_half_up(unit_extended * return_qty * pct)`, UNUSED only) — the entity text implies cumulative `returned_qty` while the calc block says `return_qty`; accumulation agrees with both for a single return, handles mixed reasons, and preserves the §2.9 identity.
- **Betterment** uses `unit_extended_cents * qty * 0.20` (gross qty, not net of returns), each product rounded half-up.
- **DECLINE** flips PENDING_CONSENT lines to `CUSTOMER_DECLINED` via an effective flag, while `consent_alternate_parts` is only written on CONSENT.
- **Vehicle age** = logical-clock calendar year - `vehicle_model_year`.
- **Stall conflicts** use a cleanup buffer closed on both sides; **bay overlap** is strictly half-open with no buffer.
- **Version discipline**: one `Bumper` per request so each row bumps at most once; install, procedure-record create and stage-assignment create do not bump the order.
- **List filters**: existence-validated only where each endpoint spec enumerates the filter; `repair_order_id` filters are not existence-validated; entity-backed roles get ownership filtering.
- **Timestamps**: server-stamped fields use the logical clock in canonical `...Z` 3-digit form; client-supplied instants are echoed verbatim.

## Step 5: Generate unit tests — 2026-09-05T16:47:38.62424335Z

Both waves are complete and every check passes.

## Deliverable

**Stage 1 — `test_helpers/` at the task root, 2,634 lines** (frozen before Stage 2 began; line counts unchanged after, so no writer touched it; `import test_helpers` succeeds):
`__init__.py` 52, `api_client.py` 403, `api_errors.py` 175, `assertions.py` 255, `constants.py` 306, `factories.py` 296, `fixtures.py` 698, `test_users.py` 146, `types.py` 303.

**Stage 2 — `test_suite/` at the task root, 7,792 lines:**
`conftest.py` 11, `test_01_refinish_allocation_and_labor_rollup.py` 428, `test_02_estimate_totals_and_parts_pricing.py` 592, `test_03_consent_threshold_and_authorisation_posture.py` 374, `test_04_supplier_performance_and_order_gates.py` 360, `test_05_parts_negotiation_returns_and_ledger.py` 554, `test_06_stage_workflow_and_quality_control.py` 584, `test_07_stall_and_bay_scheduling.py` 385, `test_08_registries_and_repair_order_intake.py` 829, `test_09_lifecycle_state_edges.py` 661, `test_10_cycle_time_and_parts_delays.py` 429, `test_11_documentation_gates_and_listings.py` 589, `test_12_error_catalogue_reachability.py` 670, `test_13_stage_gate_refusals.py` 387, `test_14_access_control.py` 519, `test_15_version_guards_and_immediate_consistency.py` 420.

## Counts

- **116 tests**, all collect: `116 tests collected in 0.29s` over the whole `test_suite/`.
- **Queue A (Difficulty): 50 tests** over all 21 instances (every instance >= 2 tests).
- **Queue B (Corner): 66 tests** over all 66 non-stub instances (exactly 1 each).
- 87 distinct `Design:` tags = 21 + 66, i.e. full coverage with no instance missed and none double-tagged.
- The 19 `excluded_because:` stubs emitted nothing.

## Audit results (script at `/tmp/task_2904_tests/audit.py`)

Zero problems: every test has exactly one `Design:` line, every tag resolves to a real instance in the correct yaml *and* correct `rule_id`/`section`, no tag references a stub, no under-covered instance. Separately, all **278** `PRD:` citations were confirmed byte-exact substrings of `workspace/PRD.md` with no elisions, and every test carries at least one. Trap sweep clean: no money-as-string, no float cents, no bare-date instant payloads (the one date literal in test_06 is an f-string prefix building full instants), no whitespace-only header values, no `["data"]` double-unwrap, no raw timestamp string equality, no `skip`/`xfail`, no mocking or file IO, no reference to `workspace/implementation/`. `worklog.md` untouched. `test_helpers/` and `test_suite/` are at the task root; neither exists under `workspace/` (orchestrator independently confirmed).

## Instances skipped

**None.** All 21 difficulty and all 66 non-stub corner instances passed the two-condition filter and were emitted. What was dropped instead was a small number of *individual sub-assertions* inside otherwise-emitted instances, each because the PRD does not derive that one clause — the instance's core grounds remain asserted:

- Three fields the design index asserts on the repair order do **not exist in the PRD**: `approved_supplement_total_cents` (test_13, test_14, test_15), `parts_delay_minutes_total` (test_10), `estimate_locked_at` (test_13). Each was replaced by a declared observable — the unchanged `version` after a refusal, or `parts_delay_minutes` on `GET /repair-orders/{id}/cycle-time`.
- `DamageLine.discovered_at_stage == INTAKE` for a first finding (test_11): §3.2's own sentence enumerates permitted values that exclude `INTAKE`, so the stamp is asserted only for the unambiguous `TEARDOWN` findings.
- A `PENDING_SUPPLEMENT` line's `allocated_hours` / `effective_rate_cents` / `line_amount_cents` being null (test_01): §3.4 defines those only for approved lines.
- "No Stall is created" after a rejected stall write (test_08): the API declares no stall listing, so it is unobservable.
- Row-to-page id mapping in multi-row listings (test_08, test_11): the logical clock never advances within a test, so `created_at` ties and §2.3 leaves the order unresolved. Counts, `total_count`, `has_more`, `limit`/`offset` and id *sets* are asserted; exact ordering only where a single row is expected.

## Fixture design decisions

- **`deductible_cents=25000` on nearly every order.** The factory default of 50,000 puts `customer_pay_cents` exactly on the inclusive 50,000 consent threshold, flipping `authorization_posture` to `CONSENT_REQUIRED` and turning every downstream gate test into `ERR_AUTHORIZATION_POSTURE_BLOCKED`. This is load-bearing, not cosmetic.
- **Index-vs-PRD repairs applied silently throughout:** `reason_code` hyphenated spellings -> declared enum members; `consent_state` initial value `NONE` (not `PENDING`); warranty term 365 days at 86,400 s/day; terminal parts status `VOID`; `rate_ceiling_cents` as one object keyed by labor type; `expected_repair_order_version` only on supplements-create and consent-decisions; optional keys the PRD does not declare for an endpoint omitted entirely (unknown fields are rejected at rung 5).
- **Two recipes were internally inconsistent and were adjusted to keep their own asserted outcome reachable:** `alternate_parts_min_vehicle_age_years` raised to 10 in test_02, and model years moved inside the min-age window in test_12, so alternate lines genuinely land `PENDING_CONSENT`/`CUSTOMER_CONSENTED` rather than `INSURER_ALLOWED`.
- **Ladder-ordering hazards designed around:** probes use otherwise-valid windows and enums so the intended rung is the first to fire, and the negative-DTC probe acts as an inspector distinct from `blueprint_by_user_id` so segregation cannot pre-empt the numeric-bounds rung.

**Two divergences from the design index worth attention as Step-7 discussion points**, both resolved by citing the PRD's normative ladder rather than the index:

1. test_05 asserts a second return on a fully-returned line fails **409 `ERR_PARTS_LINE_STATE`**, not the index's 422 `ERR_INVALID_RETURN_QUANTITY` — rung 13 (line state) precedes rung 16 (quantity), and returns are only available from `RECEIVED`/`INSTALLED`. It sits in its own test function so a divergent implementation cannot mask the conservation assertions beside it.
2. test_12 asserts a `BOTH` calibration record is refused `ERR_BAY_TYPE_UNSUPPORTED` even by a bay listing `STATIC`+`DYNAMIC` (§3.3 requires the bay itself to list `BOTH`), where the index's recipe expected success.

## Step 7: Test and fix loop — 2026-09-05T17:19:00.419336662Z

Clean 8-round sweep achieved. Final state verified.

## Summary

**Iterations run: 2**

Iteration 1: 112/116 passing in all 8 rounds — 4 failures, identical in every round (zero flakiness, so no load-induced noise to filter).
Iteration 2: **116/116 passing in all 8 of 8 parallel rounds.**

**Tests deleted: none.** All 4 failures survived STEP 1a (verbatim PRD coverage) and STEP 1b (unique derivability), so all were repaired rather than removed.

**Fixes applied to `test_suite/`** (3 sites, one bug class — STEP 2, test-side):
- `test_suite/test_02_estimate_totals_and_parts_pricing.py`, in `TestPartsRebateAverageRate`, `TestBettermentSplit`, `TestReconditionedCoreCharge` — each passed `vendor_id=vendor["id"]` as a keyword into `fx.quoted_part(...)` **on top of** the same value already supplied positionally, raising `TypeError: quoted_part() got multiple values for argument 'vendor_id'` before any request was issued. Removed the redundant kwarg at all three sites. The three tests' assertions (5% rebate tier, betterment 0.2 share, reconditioned core charge after per-unit discount rounding) had never actually been exercised; they pass on their first real run, so the money arithmetic was already correct.

**Fixes applied to `test_helpers/`: none** — the fixtures, factories, and role-header builders audited clean (notably `headers_with_empty_*` correctly use `""` rather than whitespace, and `api_client.canonical_instant` already normalises sub-second width).

**Fixes applied to `implementation/`** (1 fix — STEP 3, genuine defect):
- `workspace/implementation/db.py`, `parse_iso()` — accepted `"2026-08-01 08:00"` as a valid window bound and created the stall booking with HTTP 201. Python's `datetime.fromisoformat` tolerates a space date/time separator and a missing UTC designator, so the leniency leaked straight through validation rung 8. Added a guard rejecting any string without the `T` designator, so a bare calendar date or a space-separated form no longer parses. Backs PRD §2.5 rung 8 / §3.8 verbatim: *"`window_end` is strictly after `window_start` and both parse as ISO-8601 instants — otherwise `ERR_INVALID_WINDOW`."* Audited all 19 `parse_iso` call sites: the client-facing ones (`promised_eta`, clock `to_iso8601`, both window pairs) and every internal round-trip of server-persisted stamps all use `T…Z` form, so the tightening is regression-free.

**The two handed-over discussion points — both adjudicated in the test generator's favour; neither test failed, and both are backed by verbatim PRD prose:**
1. **test_05** (second return on a fully-returned line -> 409 `ERR_PARTS_LINE_STATE`, not 422 `ERR_INVALID_RETURN_QUANTITY`): upheld. §3.6 says *"a line at any other `procurement_status` is refused with `ERR_PARTS_LINE_STATE`"*, and a fully-returned line rests at `RETURNED` — outside the `RECEIVED`/`INSTALLED` from-state set. §2.5 places that check at rung 13 and return-quantity range at rung 16, and *"the first violated rule decides the response."*
2. **test_12** (`BOTH` calibration refused `ERR_BAY_TYPE_UNSUPPORTED` by a bay listing `STATIC`+`DYNAMIC`): upheld. §3.3 states the asymmetry verbatim — *"a record whose type is `BOTH` is satisfied **only** by a bay that itself lists `BOTH`, not by a bay listing `STATIC` and `DYNAMIC` separately."*

Hygiene: `worklog.md` untouched (orchestrator-owned), scratch confined to `/tmp/task_2904_step7/`, probe servers killed by explicit PID (never a broad `pkill`), `__pycache__` cleared, and storage confirmed in-memory dicts only with no seeding or on-disk persistence.

**Orchestrator verification:** independently read all 8 `results.$i.json` — every round reports `passed=116, total=116`.

## Step 8: Finalize PRD — 2026-09-05T17:22:43.302113976Z

`PRD_FINALIZED.md` is written. Exactly one PRD edit was warranted; the other Step 7 items were fixture bugs or already pinned verbatim.

## Line counts
- `PRD.md`: 509 lines (106,728 bytes); `PRD_FINALIZED.md`: 509 lines (107,441 bytes) — +0 lines, 0.0% line delta; one line revised in place (1/509 = 0.2% of lines touched). Orchestrator independently diffed the two files and confirmed a single changed line (line 86).

## Changes
- **§2.4 (Resource Identity, Timestamps and the Logical Clock)** — *revise* (sentence appended to the logical-clock paragraph, line 86) — defines what a **client-supplied** instant must look like to "parse as an ISO-8601 instant": it must carry the `T` date/time designator (either case); a bare calendar date (`2026-08-01`) or a space-separated form (`2026-08-01 08:00`) does not parse; a trailing `Z` or numeric offset is honoured when the instant is compared, and a value with no zone marker is read as UTC. — `implementation/db.py:87-107` (`parse_iso`, the Step 7 fix), consumed by `implementation/validate.py:116-130` (`window`, rung 8; `instant`, rung 9).

## Pre-edit search log
**Edit 1 — §2.4 instant parseability**
- (a) Subject: what string forms count as a parseable ISO-8601 instant, for every client-supplied instant input, plus the zone/offset interpretation.
- (b) Paths enumerated (all read or grepped):
  - `db.py:87-107` `parse_iso` — the single parse path; verified via `grep -rn "fromisoformat|strptime"` that no other code in `implementation/` parses timestamps.
  - All 19 `parse_iso` call sites (`grep -rn parse_iso`): `validate.py:118-119` (window rung 8), `validate.py:127` (rung 9 non-window instant), `calc.py:429-450` (cycle-time interval assembly over server-stamped `checkin_at`/`delivered_at`/`submitted_at`/`opened_at`/`closed_at`), `guards.py:86-87` (`delay_minutes` from server stamps), `routes/assignments.py:78-79` (stall conflict re-parse of stored windows), `routes/procedures.py:134-135` (bay overlap re-parse), `routes/parts.py:343,448` (`on_time` and the ETA-breach sweep re-parsing `promised_eta`). Server-stamped values all come from `db.iso()` (`T…Z` form), so the tightening cannot regress them; the only re-parsed *client* strings are `window_start`/`window_end` and `promised_eta`, which are stored verbatim (`routes/assignments.py:94-95`, `routes/parts.py:305`) and therefore already contain `T`.
  - Complete inventory of client-supplied instant inputs, via `grep -rn 'F("'` filtered for date/time-ish fields: only `window_start`/`window_end` (`routes/assignments.py:53-54`, `routes/procedures.py:127-128`), `to_iso8601` (`routes/registry.py:257,264`), `promised_eta` (`routes/parts.py:272,279`). The sentence's three-item enumeration is exhaustive.
  - Zone handling: `db.set_clock` (`db.py:63-65`) and `parse_iso`'s `astimezone(timezone.utc)`/naive-as-UTC branch; `serialize.py:52` confirms `promised_eta` is echoed as supplied, not canonicalised.
  - Existing PRD prose the new sentence must stay compatible with: §2.5 rung 8 (line 101), §3.3 calibration scheduling (line 196), §3.8 stall booking (line 342), §3.6 receipt/`on_time` (line 286), §2.4 clock paragraph (line 86) — all left verbatim.
- (c) Wording adjustments made to keep every enumerated path consistent: (1) added "(in either case)" because `parse_iso` accepts a lowercase `t`, so a case-sensitive reading would have been a false narrowing; (2) framed the offset/`Z` clause as *"honoured when that instant is compared against the clock or against another instant"* rather than "reduced to UTC and stored", because `window_start`, `window_end` and `promised_eta` are persisted and echoed byte-for-byte as supplied — a canonicalisation claim would have induced a new response-body mismatch; (3) scoped the whole sentence to *client-supplied* instants so it cannot be read as constraining the server's own `db.iso()` three-fractional-digit output format described in the same section; (4) deliberately omitted any error-code claim for `promised_eta`/`to_iso8601` (impl uses `ERR_INVALID_REQUEST` at rung 9) — that silence predates the Step 7 fix and is out of the hard scope, and asserting it risked over-pinning ladder position.

No edits made for the three `test_suite/` fixture repairs (a `TypeError` from a duplicated `vendor_id` kwarg — the rebate-tier, betterment-0.2 and core-charge arithmetic they assert is quoted verbatim from the PRD and passed unmodified), nor for the two adjudicated discussion points (`ERR_PARTS_LINE_STATE` on a `RETURNED` line is fixed by PRD line 290 plus rung 13/16 ordering; the `BOTH`-bay asymmetry is stated verbatim at PRD line 196).

## Step 9: Complete PRD — 2026-09-05T17:50:32.804932320Z

Run as **three sequential module-partitioned passes** over one shared `workspace/PRD_COMPLETED.md` (orchestrator decision: a single pass over 3,275 lines of implementation reliably under-scans; pass 1 owned the `cp` from `PRD_FINALIZED.md`, passes 2 and 3 were forbidden to re-copy so earlier edits survived).

**Aggregate result:** `PRD_FINALIZED.md` 509 lines / 107,441 chars -> `PRD_COMPLETED.md` 509 lines / 121,762 chars (**+14,321 chars**, 45 lines revised in place, no new sections or paragraphs). **Total 53 pinned behaviors: 33 ambiguity-pins, 20 mismatch-revisions.** Orchestrator verified: not byte-identical to `PRD_FINALIZED.md`, 27 headings intact, document ends at the §5 error table's last row.

### Pass 1 — envelope, errors, storage/clock, auth, ladder, guards, serialization, registries
(`app.py`, `db.py`, `errors.py`, `response.py`, `auth.py`, `validate.py`, `guards.py`, `serialize.py`, `routes/registry.py`) — 9 ambiguity-pins, 3 mismatch-revisions, +3,767 chars.

Verified-aligned (no change): the whole §5 catalogue — all 61 `error_id`->status pairs and even their order match `errors.py` exactly; every field name in `serialize.py`'s 14 projections already appears in the PRD; all registry defaults (0.2, 4, 30, 2, 3, 1.1, 50, `ACTIVE`/`AVAILABLE`, score 50, `order_seq_counter` 0) and all §4 role lists match `registry.py`; immutable-row rule, `touch()` versioning, `T`-designator instant parsing and the 2026-08-01 default clock already pinned.

- §2.2 — insert — ambiguity — `api_request_id` is `req_` plus exactly twenty uppercase-letter/digit characters — `db.py:53`
- §2.2 — revise — mismatch — `api_request_timestamp` is read from real wall-clock time, not the logical clock, so a clock move does not move it — `response.py:16` / `db.py:82`
- §2.4 — revise — mismatch — narrowed "server stamps are read from a logical clock, never wall clock" to timestamps stamped *onto a persisted row*, naming the envelope timestamp as the sole exception — `db.py:78-84`
- §2.4 — insert — ambiguity — the clock move answers 200 with `current_utc` alone and may move the clock backwards; no monotonicity enforced — `routes/registry.py:260`
- §2.3 — insert — ambiguity — omitted pagination params take defaults and undeclared query parameters are ignored rather than rejected — `response.py:58`
- §2.3 — insert — ambiguity — rows sharing a `created_at` are ordered by creation sequence; `total_count` counts filtered rows before the window and `has_more` is `offset + len(rows) < total_count` — `db.py:143`, `response.py:36`
- §2.5 rung 5 — insert — ambiguity — optional field sent as `null` is treated as absent (default applies); absent/empty body reads as `{}`; a present non-object/unparseable body is `ERR_INVALID_REQUEST`; string fields are type-checked only, so blank strings pass unless a stated length/format constraint exists — `validate.py:41-102`
- §2.5 rung 9 — insert — ambiguity — the five `rate_ceiling_cents` entries must each be integers and extra keys are stored verbatim; added the registry bounds enforced with the same error (`insurer_code` length+uniqueness, `alternate_parts_min_vehicle_age_years`, `supplement_round_limit`, `core_charge_cents`, `restocking_fee_pct`, `max_qty_per_line`, `cleanup_buffer_minutes`, `concurrent_capacity`); non-window datetime inputs that fail to parse give `ERR_INVALID_REQUEST`, not `ERR_INVALID_WINDOW` — `routes/registry.py:84-100,146-154,196,235`, `validate.py:125`
- §3.1 — insert — ambiguity — bad `insurer_code` length, a duplicate code, and a `rate_ceiling_cents` missing a key or holding a non-integer are all `ERR_INVALID_REQUEST` — `routes/registry.py:84-94`
- §3.1 — insert — ambiguity — a `part_types_offered` member outside the four (any JSON type) is `ERR_INVALID_ENUM_VALUE`, checked *before* emptiness/uniqueness which give `ERR_INVALID_REQUEST`; accepted arrays are echoed in supplied order — `routes/registry.py:24-29,144-148`
- §3.1 — insert — ambiguity — same enum-then-shape classification for a bay's `supported_types` — `routes/registry.py:231-234`
- §5 preamble — revise — mismatch — the catalogue covers requests that reached a §4 endpoint; an undeclared path answers `ERR_NOT_FOUND`/404 and a wrong method `ERR_METHOD_NOT_ALLOWED`/405, both outside the table and before any header/role/body check — `app.py:31-40`

### Pass 2 — calculations, repair-order lifecycle, estimate lines, supplements
(`calc.py`, `routes/orders.py`, `routes/estimate_lines.py`, `routes/supplements.py`) — 9 ambiguity-pins, 11 mismatch-revisions, +3,803 chars. Confirmed all six pass-1 marker sentences still present.

Verified-as-already-pinned (no change): all nine calc formulas (refinish PROVISIONAL/FINAL branches, ranking, rollup, eight steps and tiers, vendor score windows/weights, commitment ledger, stall/bay rollups, posture precedence and stale-consent compensation, cycle-time merge), QC verdict/failure-reason ranking/warranty format/365-day arithmetic, deliver gates and assignment completion, total-loss void sets, blueprint gates. Two impl orderings differ from §3.2/§3.4 prose ordering (ADAS check before finding-count; justification before no-drafts) but are provably unobservable and both match §2.5's ladder, so left alone.

- §3.2 — revise — mismatch — `vehicle_vin` no longer "17-character"; required string with no length/format constraint, empty accepted — `routes/orders.py:25` (pass-1 handover, resolved for impl)
- §3.2 — insert — ambiguity — `deductible_cents` must be zero or greater — `routes/orders.py:84`
- §3.2 — insert — ambiguity — birth values of every derived order field (hours 0.0, money/counters 0, `consent_alternate_parts` false, four nulls) — `routes/orders.py:33-72`
- §3.2 — revise — mismatch — order `version` increments on **every** teardown finding, not only the first — `routes/orders.py:155-157`
- §3.4 — revise — mismatch — a `DRAFT` line may be written anywhere not past `BLUEPRINTED` (`INTAKE`/`TEARDOWN` included), and a pre-lock `supplement_id` yields `PENDING_SUPPLEMENT` whatever that supplement's status — `routes/estimate_lines.py:39-40,66-68,88`
- §3.4 — insert — ambiguity — new line born with `allocated_hours`, `effective_rate_cents`, `line_amount_cents` null — `routes/estimate_lines.py:85-87`
- §3.4 — revise — mismatch — not-included justification gate rejects null **and** empty string, accepts whitespace-only — `routes/orders.py:208`
- §3.4 — revise — mismatch — the eight-step totals do **not** rerun on a `REQUEST_INFO` decision — `routes/supplements.py:133-136`
- §3.4 — revise — mismatch — total-loss hop three does not force `OPEN`; it is the ordinary derivation and can leave `CONSENT_REQUIRED` — `calc.py:396-420`, `routes/orders.py:256`
- §3.7 — revise — mismatch — raising a supplement has **no** stage precondition (any non-terminal stage, `INTAKE` included) — `routes/supplements.py:41-43`
- §3.7 — insert — ambiguity — supplement born with `approved_amount_cents`/`decided_at`/`info_request_note`/`adjuster_note` null — `routes/supplements.py:47-58`
- §3.7 — revise — mismatch — a `PARTIAL` decision reruns the `FINAL` refinish allocation too — `routes/supplements.py:95-100,154`
- §3.7 — insert — ambiguity — `REQUEST_INFO` neither refuses nor records an `approved_amount_cents`; a blanks-only note is refused — `routes/supplements.py:110-112,126`
- §3.7 — insert — ambiguity — `DECLINE` leaves `consent_basis_cents` and `consent_alternate_parts` untouched — `routes/supplements.py:219-221`
- §3.7 — revise — mismatch — raising a supplement reaches `SUPPLEMENT_PENDING` only when no consent condition outranks it — `calc.py:415-420`
- §3.7 — insert — ambiguity — a `DENY`-rejected line keeps its last-written `allocated_hours`; nothing clears the field — `calc.py:144-170`
- §3.9 — insert — ambiguity — `scan_report_ref` is optional and stored null when omitted — `routes/orders.py:267`
- §3.9 — revise — mismatch — cycle-time read is `ShopAdmin`/`Estimator` only — `routes/orders.py:338`
- §3.9 — revise — mismatch — `supplement_wait_minutes`/`parts_delay_minutes` floor each clamped interval before summing — `calc.py:461-470`
- §2.6 — revise — mismatch — the "floor after combining" rule gets its stated carve-out for those two unmerged tallies — `calc.py:466`

### Pass 3 — parts procurement, procedures/calibration, stage assignments
(`routes/parts.py`, `routes/procedures.py`, `routes/assignments.py`) — 15 ambiguity-pins, 6 mismatch-revisions, +6,751 chars. Confirmed pass-1 and pass-2 sentinels still present.

- §2.5 rung 10 — revise — mismatch — `bay_id` resolves **before** the procedure-record path identifier — `routes/procedures.py:146-147`
- §3.3 — revise — ambiguity — `calibration_type` accepts `NONE` explicitly; the two calibration inputs are not cross-validated; no stage precondition; creating a record leaves the order row untouched (no version bump, no posture); `bay_id` filter existence-checked but `repair_order_id` not — `routes/procedures.py:39-74, 88-95`
- §3.3 — insert — ambiguity — `bay_id`, `window_start`, `window_end`, `post_scan_dtc_count`, `scan_report_ref` null at birth; `version` 1 — `routes/procedures.py:57-72`
- §3.3 — insert — ambiguity — PATCH is a full replacement: omitted/null `adherence_doc_ref` overwrites with null; `adherence_documented` may go back to false; no stage/calibration gate; only the record's version moves — `routes/procedures.py:112-122`
- §3.3 — revise — mismatch — window check is the **first** of the four gates (rung 8), ahead of `calibration_status` — `routes/procedures.py:144-151`
- §3.3 — insert — ambiguity — window bounds stored/echoed verbatim, offsets honoured but never normalised (also covers §3.8 booking and `promised_eta`) — `routes/procedures.py:173-174`
- §3.3 — insert — ambiguity — `result` enum has exactly two members `PASS`/`FAIL` — `routes/procedures.py:185`
- §3.3 — insert — ambiguity — a pass leaves `bay_id`/`window_start`/`window_end` standing (only a failure clears them) — `routes/procedures.py:208-214`
- §3.5 — insert — ambiguity — no stage precondition and no `line_status` condition on attaching a part; `estimate_line_id`/`vendor_id` filters existence-checked — `routes/parts.py:87-94, 163-168`
- §3.5 — insert — ambiguity — full birth-value set of a parts line (nulls vs zeros, version 1) — `routes/parts.py:117-143`
- §3.5 — insert — ambiguity — the order's `version` increments on **every** parts-line creation, and creation does not rerun the totals — `routes/parts.py:145-147`
- §3.5 — insert — ambiguity — a first quote overwrites any creation-time `vendor_id` (mismatch gate binds only `COUNTERED`); `quoted_unit_price_cents` > 0 on rung 9; only the line's version moves — `routes/parts.py:191-214`
- §3.5 — insert — ambiguity — `counter_unit_price_cents` > 0 on rung 9; only the line's version moves — `routes/parts.py:225-238`
- §3.6 — revise — mismatch — stage precondition fires **before** `ERR_PARTS_LINE_STATE`; noted `QC_FAILED` exclusion — `routes/parts.py:284-285`
- §3.6 — insert — ambiguity — receipt has no stage precondition and consults neither posture nor supplier status — `routes/parts.py:333-334`
- §3.6 — revise — mismatch — `restocking_fee_cents` **accumulates** per return rather than being recomputed — `routes/parts.py:406-407`
- §3.6 — revise — ambiguity — the delay sweep fires only on a `promised_eta` **strictly** before the clock; any open event (any reason) suppresses — `routes/parts.py:449-451`
- §3.8 — insert — ambiguity — `stall_id` filter existence-checked, `repair_order_id` not; no stage/posture tie on booking — `routes/assignments.py:63-70, 117-124`
- §3.8 — insert — mismatch — on server-driven releases the stall's `version` moves only when `booked_minutes` actually changes — `guards.py:58-59` via `calc.stall_rollup`
- §3.8 — insert — ambiguity — `to_stage` is an enum over the eleven stages (rung 6 `ERR_INVALID_ENUM_VALUE`); only four stages are ever valid successors — `routes/assignments.py:153, 171-172`
- §3.8 — revise — mismatch — into `REFINISH_CALIBRATION` the STRUCTURAL adherence gate (rung 14) fires **before** `ERR_PARTS_NOT_INSTALLED` (rung 16) — `routes/assignments.py:186-201`

One knowingly-skipped item (pass 3): §3.6 claims the commitment ledger reruns "on every receipt"; `receive_part` does not call it, but the ledger's inputs are identical across `ORDERED`->`RECEIVED`, so the divergence is unobservable and the prose was left rather than weakened.

## Pipeline complete
Step 9 has written `workspace/PRD_COMPLETED.md`. Final sweep evidence retained: `workspace/implementation/results.{1..8}.json`, all 116/116.
