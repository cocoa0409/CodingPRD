# Worklog — task_3017_supermarket_deli_made_order_sub_production

Scenario: Supermarket Deli & Made-to-Order Sub Production (Publix)

## Step 1: Create task directory — 2026-09-29T14:29:38.300Z

Task directory `./tasks/task_3017_supermarket_deli_made_order_sub_production/` was pre-allocated by the caller with `workspace/` already present. No index computation performed; no other `task_*` directory created.

## Step 2: Generate scaffold artifacts — 2026-09-29T15:22:37.000Z

Scaffold generation complete. All three artifacts are written and lint-clean.

### Files written

| Path | Lines |
|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_3017_supermarket_deli_made_order_sub_production/SCAFFOLD.yaml` | 2857 |
| `/home/ubuntu/github/CodingPRD/tasks/task_3017_supermarket_deli_made_order_sub_production/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1996 |
| `/home/ubuntu/github/CodingPRD/tasks/task_3017_supermarket_deli_made_order_sub_production/SCAFFOLD_CORNER_DESIGN.yaml` | 7556 |

### Counts

- **Entities 14 / state machines 12 (71 transitions) / endpoints 99 / errors 44 / roles 5 / calculations 14 / validations 42 (priorities 1–42) / concurrency rules 3**
- **Difficulty design: 9 rules × 2 instances = 18 instances** (one per §0.5 `rule_id`, every one meeting its ≥2 minimum)
- **Corner design: 9 sections / 53 instances** — entities 6, state_machines 11, calculations 6, validations 6, endpoints 7, errors 7, roles 4, cross_cutting_layers 5, consistency_model 1

### Key design decisions

- **Difficulty band is `beyond_expert`**, deliberately above §0.4's Expert ceiling: 14 entities (top of Expert), 99 endpoints, 44 error codes, 14 calculations, 3 OCC rules. Density came from coupling, not padding — e.g. `diffusion_index` gates `store_deli_posture`, which gates every child write.
- **Archetype**: temporal_windowing (primary) + workflow_orchestration, with layers optimistic_concurrency, scheduled_deferred_actions, rate_threshold_triggers, cascading_side_effects. Topology is **flat** (prioritized by §0.3) and `state_machine_shape: parallel`, so three machines carry genuinely parallel dimensions (ProductionBatch `production_status × hold_status`, SubTicket `fulfillment_status × bread_status`).
- **Non-linearity is structural, not label-deep**: 5 machine cycles by revisit (SlicerAsset, SanitationCycle, ScalePriceFile, Promotion, BreadSupplyOrder) plus 3 induced row cycles through materialized successors (rework, renewal, reopen) — the original row is never reversed.
- **Interval semantics are differentiated across resources** — slicer half-open no-buffer bitemporal occupancy, 15-minute aggregate pickup buckets with a 10-minute staging buffer, half-open markdown windows, half-open certifications, half-open price files. This is what separates the two Rule-8 instances.
- **Formula literals were computed, not estimated** (per §1.8 contract item 7): e.g. case yield cost 3269 → 3519, bread demand 720 → 372 across variants, waste base exactly 11500 → tier switch, catering quote 12575, label 1.234×899 = 1109 vs 1.235×899 = 1110.
- Two test-driving endpoints were added under the §1.5 priority ladder: `POST /_clock/set_current_utc` (with the mandated fixed default `2026-09-01T00:00:00Z`) and `POST /_rbac/role-permissions`; plus `POST /deli/posture-gate` and `PATCH /deli/run-production-day` as business/admin endpoints that make HALT and sweep states reachable without DB seeding.

### Verification

```
Coverage
  §1.5 endpoints declared:    99
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     53
  Calls scanned (§1.8+§1.9):  2037
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5
and all §1.1 FKs have reverse-reachability in §1.5.
```

Beyond the linter I ran an independent structural pass confirming: zero unbound `${var}` placeholders and zero uncaptured assert placeholders across all 71 instances, all `grounds:` resolve to declared calculations/validations/errors/entities/fields/roles/state-machines/concurrency rule ids, no duplicate instance names within or across the two design files, no `scaffold_difficulty_design:`/`scaffold_corner_design:` keys inside `SCAFFOLD.yaml`, and no forbidden concurrency vocabulary anywhere.

One deliberate deviation worth flagging: the FK reverse-reachability check requires 40 declared FKs to each have a reverse GET, so the endpoint surface is larger than a minimal design would need (99 vs. the ~20–32 Expert band). Those extra endpoints are contract-necessary, not padding. Six of them are nested (`GET /deli/items/{id}/slicer-usage` and siblings), kept isolated to reads because a flat filtered list genuinely cannot disambiguate *which* child collection is meant when a master record has several.

Orchestrator verification: `SCAFFOLD.yaml` 2857 lines (0 `scaffold_difficulty_design` keys, 0 `scaffold_corner_design` keys); `SCAFFOLD_DIFFICULTY_DESIGN.yaml` 1996 lines (1 top-level key); `SCAFFOLD_CORNER_DESIGN.yaml` 7556 lines (1 top-level key). All three present and correctly partitioned.

## Step 3: Copy shared INSTRUCTION.md — 2026-09-29T15:23:04.256Z

Copied `./INSTRUCTION.md` (1424 bytes) to `./tasks/task_3017_supermarket_deli_made_order_sub_production/workspace/INSTRUCTION.md`. Bash-only step; no subagent.

## Step 4: Generate PRD document — 2026-09-29T15:36:56.352Z

All three hard contracts verified mechanically. Here is the summary.

### Output

**Path:** `/home/ubuntu/github/CodingPRD/tasks/task_3017_supermarket_deli_made_order_sub_production/workspace/PRD.md`
**Length:** 468 lines / ~99.5 KB (largest in the family so far — the scaffold is 2,858 lines with 14 entities, 12 state machines, 14 calculations, 42 validations, 99 endpoints, 44 errors, 5 roles)

### Major sections

| Section | Subsections |
|---|---|
| **§1 Introduction** | 3 paragraphs — from the perishable-countdown angle, the live-queue angle, and the food-safety-regime angle |
| **§2 Global Specifications** | 2.1 RBAC · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 Common Resource Properties · 2.5 Postal Address of the Logical Clock · 2.6 Store Posture as the Admission Gate · 2.7 Protection and Diffusion Indices · 2.8 Certified Staffing and the Certification Ledger · 2.9 Precision, Rounding and Monetary Representation · 2.10 Optimistic Concurrency Control on Three Writes · 2.11 Failure Order and Validation Priority · 2.12 Hierarchical Consistency and Cascade Semantics |
| **§3 Business Logic** | 3.1 Planning the Production Day · 3.2 Slicer Custody, Sanitation and Allergen Changeover · 3.3 Case Yield Cost and the Waste Liability Ledger · 3.4 The Digital Sub Queue, Ticketing and Promised Times · 3.5 Weekly Promotions and the Bread Supply Chain · 3.6 Weight-Based Labeling and the Scale Price File · 3.7 Catering Platters, Pickup Windows and Bucket Capacity · 3.8 Associate Lifecycle, Suspension and Store Halt |
| **§4 Endpoint Definitions** | prose on 201/200 rules + 4-column table, 99 rows |
| **§5 Error Code Catalogue** | 2-column table, 45 rows (44 errors + `ERR_WASTE_SEQUENCE_VIOLATION`, which the transition preconditions use but the `errors[]` table omits — flagged in the report below) |

Note: §2.4–§2.12 titles are domain-derived (posture gate, protection/diffusion indices, slicer custody) rather than the example's generic slots; §3 uses a mixed strategy — entity lifecycle for batches/slicers/waste, role perspective for associates, and chronological process order for catering.

### Deliberate information scattering

- **Batch-start parameters split across three subsections:** `planned_lbs`/`batch_code`/`produced_by_associate_id` in §3.1; `expected_store_version` in §2.10; `slicer_id` and the certification/sanitation/allergen prerequisites in §3.1's start-paragraph, with the slicer-side mechanics in §3.2.
- **Ticket parameters split four ways:** `lines`/`half_lb_units`/`order_channel`/`placed_by_customer_ref` in §3.4's creation narrative; `net_weight_lbs` at the completion step there; `bread_deli_item_id` in §3.5; allergy/shelf guards in §3.4's completion refusal list.
- **Waste inputs split three ways:** `discard_lbs` in §3.3's discard step; `verifier_associate_id`/`verified_by_certification_id` in the verification step; `markdown_by_associate_id` in the markdown step — plus `expected_batch_version` in §2.10.
- **Numeric constants embedded in business context:** `SLICER_CUTS_PER_FEE_UNIT: 20` as "divided by 20" in a fee sentence; `CUTS_PER_BATCH_DIVISOR: 5` as "divided by five"; `RUSH_LIMIT_HOURS: 24` written as "at least 24" hours in the lead-time rule while the same constant appears as "below 24" in the quote tier; `TIMED_MULTIPLIER: 3` as "three times"; `MINUTES_PER_REQUIRED_BATCH: 12` and `MINUTES_PER_HALF_LB: 1` inside a worked 29-minute example; `BUCKET_HEADCOUNT_LIMIT: 40` in §3.7's aggregate-capacity sentence; `INVENTORY_TRIGGERED` threshold 30 stated in §2.6 with the inclusive boundary spelled out, and re-touched in §3.8.
- **Relationships through action, no foreign keys declared:** "payload containing the `production_batch_id`", "the `promotion_id` whose forecast drives it", "the `bread_deli_item_id` it is served on" — parent-child implied by workflow, never by a schema table.
- **OCC rules in §2.10 with the trigger consequence restated where the workflow lives:** §3.1 for `expected_store_version`, §3.3's verify step for `expected_batch_version`, §3.5's confirm step for `expected_promotion_version` (plus `expected_item_version`/`expected_slicer_version`, which the scaffold carries in `input` but which appear in no `concurrency_rules` entry).
- **Validation priority order stated as one enumerated ladder in §2.11** with the two ordering notes (replay-check pre-emption; `RESTRICTED`-on-start folded into preconditions), while each condition sits near the workflow it guards.
- **Cascade chains narrated in four places** (§2.12 summary, §3.1 completion, §3.8 suspension, §3.2/§3.6 supersession) rather than in one concentrated block.

### Hard Contract Reports

```
Field coverage check:
- entities[].fields: 140 required, 140 present, 0 missing
- endpoints[].request_body/input: 101 required, 101 present, 0 missing
- endpoints[].query_params: 0 required (scaffold encodes filters as input-with-? suffix), 0 present, 0 missing
- endpoints[].path_params: 0 required (paths use literal {id}/{batchId} placeholders, no named param list)
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 42 checked, 42 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + ERR_STALE_VERSION/412 all named), 0 missing
- state_machines[].transitions: 71 checked, 71 fully expressed, 0 missing
- calculations[]: 14 checked, 14 fully expressed, 0 missing
- validations[] conditions: 42 checked, 42 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 99 endpoints and 42 applies_to scopes checked, all expressed, 0 missing
- entities[].fields[] structured content: 140 checked, 140 reconstructible from prose, 0 missing
- sibling-branch symmetry: 10 branch groups checked (ProductionBatch hold dimension, SanitationCycle, ScalePriceFile, Promotion, BreadSupplyOrder, SubTicket, CateringOrder, Associate, Certification, WasteRecord), 10 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 770
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

§2.2 is byte-identical to `section-2.2-response-structure.md` (verified by diff; only appended separator differs, matching the reference example).

### Two findings worth flagging to the orchestrator

1. **`ERR_WASTE_SEQUENCE_VIOLATION` is used by a scaffold transition precondition but is absent from the scaffold's `errors[]` catalogue.** The `ProductionBatch` `HOLDING → MARKED_DOWN` precondition cites it, and §3.1 therefore mentions it in prose, so it appears in the PRD's §5 table as a 45th row with status 409. If the hidden tests treat §5 as a strict 44-row set, that extra row is the one divergence; if they expect the code to be implementable, the row is necessary. I expressed it rather than dropping it, per Contract 2's "no omitted rules".
2. **`ERR_SLICER_WINDOW_CONFLICT` is reused across two distinct conditions** — slicer interval overlap at batch start, and "no other OPEN SanitationCycle exists for this slicer" at cycle open. Both are stated explicitly in §3.2 so an implementer does not collapse them into one check.

Orchestrator verification: `workspace/PRD.md` present, 467 lines / 100407 bytes, 5 top-level sections. Both design indices were withheld from this step as required.

## Step 5: Generate unit test suite — 2026-09-29T16:19:27.828Z

Generation is complete and self-audited. Here is the summary.

### Files written

`/home/ubuntu/github/CodingPRD/tasks/task_3017_supermarket_deli_made_order_sub_production/test_helpers/`
- `__init__.py` (barrel export), `types.py` (14 entity TypedDicts + 22 status enums), `api_client.py` (104 endpoint methods), `api_errors.py` (45 error IDs + HTTP map registered via `set_error_http_status_map`), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (shared constants + mandatory `make_*_headers(user_id)` builders), `fixtures.py` (656 lines: identity-threading helpers, 5 fixture tiers, `setup_deli_master_data`, `setup_promo_bread_chain`, `setup_waste_records_open`, `setup_catering_ready`, `setup_case_stock_at`, `setup_waste_verified`, etc.)

`.../test_suite/`
- `conftest.py` + 25 numbered test files (`test_01_` … `test_28_`, no numbering for queue-B-only gaps) — 98 test functions.

### Counts
- **Total tests: 98**
- **§1.8 queue-A instances translated: 18 of 18** (44 tests, every instance covered by ≥2)
- **§1.9 queue-B instances translated: 53 of 53** (54 tests, every non-stub instance covered by ≥1). This corner index contains **zero `excluded_because:` stubs** — all 53 instances are non-stub, so all 53 were translated.
- **Skipped instances: 0** — no instance failed the PRD-first two-condition filter, so no placeholder/skip/xfail markers exist anywhere.

### Verification performed
- Every docstring ends with exactly one `Design:` line resolving to a real index instance; programmatic audit shows no untagged, dual-tagged, or dangling-tag tests, no shortfall, and no extra tags.
- Every docstring citation was checked against a literal normalized grep of `workspace/PRD.md`; 38 citations were rewritten to quote the verbatim PRD sentence (rather than a scaffold-derived paraphrase) and the final pass reports **0 misses**.
- `pyflakes` clean on all helper and test modules; all files byte-compile; `pytest --collect-only` yields 98 tests.

### Deliberate PRD-first narrowing (documented in-test, not skipped)
Three assertions were reduced to what PRD independently pins, while still translating the instance:
- `Corner/cross_cutting_layers/certification_expiry_…`: the contract names a **72-hour** grace window (PRD §2.8), not the 24-hour figure the corner index's wording implies — the test asserts the 72-hour comparison it can uniquely derive.
- `Corner/state_machines/sanitation_threshold_inclusive_…`: PRD does not state how a batch's slicer minutes map to `in_use_minutes`, so the test asserts the TIMED form is *not* due after one batch and the inclusive ROUTINE threshold passes, without asserting a minute count.
- `Difficulty/priority_pair…`: PRD §2.11 orders *categories* ("state-shape … business safety"), so the two tests assert a state error outranking `ERR_ALLERGEN_CHANGEOVER_REQUIRED`, and a business-safety error outranking `ERR_NO_CLEAN_SLICER` — not the scaffold's numeric priority 5-vs-12 paraphrase.

Orchestrator verification: `test_helpers/` contains 9 modules (`__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `test_users.py`, `fixtures.py`); `test_suite/` contains `conftest.py` + 24 `test_*.py` files. Combined 6530 lines.

## Step 6: Generate implementation — 2026-09-29T16:19:27.828Z

Implementation complete and verified. Final state:

**File tree** (`workspace/implementation/`, 24 files, **4,765 lines**):

```
start.sh              11   requirements.txt      1
app.py                66   util.py             107
db.py                 62   errors.py           119
response.py           55   auth.py              81
http_support.py      166   views.py            307
calc.py              421   services.py         573
routes/__init__.py     1   routes/platform.py   63
routes/stores.py     150   routes/catalog.py   166
routes/staff.py      301   routes/equipment.py 312
routes/production.py 394   routes/subtickets.py 305
routes/promotions.py 292   routes/scales.py    228
routes/catering.py   302   routes/waste.py     284
```

**Endpoints: 99 implemented = 99 declared** in the scaffold's endpoint table (plus an unlisted `GET /_health`).

**Verification performed** — booted the server via `start.sh` under `PORT`, exercised ~230 live assertions across every resource group: envelope/pagination/auth, OCC on all three guarded writes, both case-yield variants (3045 provisional / 3315 final, matching the pinned formula by hand), the mandate waste sequence with the tiered fee, slicer sanitation cycle including dueness/reopen-dirtying/interval conflicts, allergen changeover (blocked on divergence, cleared only by an `ALLERGEN_CHANGEOVER` cycle), the HALT cascade (revoke → tickets ABANDONED), pickup-window freeze, catering quote tiers (3600/4950/10500/10437), bucket capacity, promotion forecast variants (168 provisional / 156 settled) and the price-file supersede→void→REMADE cascade. Zero server-side tracebacks. Confirmed the store starts empty at import and that re-invoking `start.sh` wipes all state.

**Notable bugs found and fixed during verification**: `activate` never set a promotion to ACTIVE; `recompute_store` bumped the store version on every call (defeating the OCC), now bumps only on actual derived change with explicit bumps on the scaffold's named paths; the allergen-changeover gate was inverted for a CLEAN slicer; `markdown_window_open` conflated the pre-window HOLDING state with the window itself; an empty `_rbac/role-permissions` list was treated as "no restriction" instead of "deny all"; `resolve_active_price_file`'s tie-break sort was wrong.

**Ambiguities and how they were resolved** (all PRD-wins-over-scaffold):

1. **Slicer commitment interval** — the PRD names a `[clock, clock+case_life)` conflict but not what creates one. Resolved: an OPEN/COMPLETED `SanitationCycle` commits `[started_at, started_at+cycle_minutes)`, and an in-flight `IN_PRODUCTION` batch commits `[start, start+case_life)`. Previous `ON_LINE` batches do not, which is what makes a slicer re-claimable after sanitation.
2. **Markdown window** — the scaffold's `markdown_allowed = HOLDING|MARKDOWN_WINDOW` contradicts PRD 3.1 ("requested before the window opens … fails"). PRD wins: only `MARKDOWN_WINDOW` is eligible.
3. **DEGRADED threshold** — the scaffold's state machine says `units_short > 0.5 × required`, but its own calculation sets DEGRADED iff `units_short > 0`, and PRD 3.5's coverage paragraph agrees. Implemented the binary form (the 0.5 clause would make coverage restoration unreachable).
4. **`reserved_units` / `available_bread_units`** — conflicting unit semantics between the calculation and the field descriptions. Resolved: `reserved_units` = count of `TICKETED`/`IN_PROGRESS` tickets for that bread item (per the calculation), `available_bread_units` = delivered − `BREAD_HOLD` ticket count (per the field descriptions).
5. **Unmodeled mechanics with no mastering endpoint** — the "assigned station" (`TICKETED`→`IN_PROGRESS`), `in_use_minutes` accrual, line-item→batch routing, and the open-WasteRecord block. Resolved: a TICKETED ticket with a CLEAN slicer advances automatically (on read and on complete); `in_use_minutes` accrues at completion from the claim instant; prep minutes count distinct items across the ticket's lines; a mark-down against a batch that already holds a DRAFT waste record assigns that record's markdown associate rather than creating a second one.
6. **OCC field presence** — PRD 2.10 makes the three version fields non-optional; a missing field is `ERR_INVALID_REQUEST` (malformed), a mismatch is `ERR_STALE_VERSION`/412. The scaffold's priority-38 wording alone would suggest 412 for both; followed the PRD.
7. **`ERR_WASTE_SEQUENCE_VIOLATION`** appears in the error catalog and PRD but not the scaffold's errors table — implemented at 409 per the catalog.
8. **Retract's promotion gate** — implemented the literal conjunction (no ISSUED labels; promotion not already `CANCELLED`/`SETTLED`), so a live in-week `SCHEDULED` promotion also blocks.
9. **Non-terminal definitions** — the HALT cascade and `pending_waste_verification_count` key off `DRAFT|MARKED_DOWN|DISCARDED` (count) and non-`PICKED_UP`/`ABANDONED` tickets (cascade), which differ between the scaffold's state machine and its field description; used each in its own context as written.

Orchestrator verification: `workspace/implementation/` contains `start.sh` (executable), `requirements.txt`, and 11 top-level Python modules plus a `routes/` package with 11 modules; 4754 lines of Python. Steps 5 and 6 ran concurrently in a single assistant message, so neither subagent could read the other's output.

## Step 7: Run tests and iterate to a clean sweep — 2026-09-29T20:34:49.417Z

Clean sweep: **98/98 in all 8 rounds.**

### Summary

**Iterations run:** 17 diagnostic/fix cycles (one initial sweep + 16 fix-and-rerun rounds, plus intermediate in-process diagnosis runs).

**Tests deleted:** 1 —
- `test_09_validation_priority_pairs.py::test_missing_certified_staff_outranks_the_clean_slicer_check_at_ticketing` — **error-precedence silence**. The scaffold rule (`posture_conflict_state_before_business_safety`) asserts `ERR_NO_CERTIFIED_STAFF` on a ticketing race whose loser is, under every PRD-faithful serialization, a store whose last-operator revocation (PRD §3.8) has already driven it to `HALT` and abandoned the ticket book (PRD §2.6/§2.12). PRD §2.11 orders "required state" and "`HALT` posture" **above** "certified staff at ticketing", so the named error is unreachable on that path. The instance's other leg (state-vs-allergen at batch start) is still covered by tests 1–3 of the file.

**Fixes applied to `test_helpers/`:**
- `fixtures.py :: setup_deli_master_data` — provisions an ACTIVE price file and re-reads the store, because PRD §2.6 makes a null `active_price_file_id` derive `RESTRICTED` (blocking all batch creation) and PRD §3.6 makes label-generating calls fail `ERR_PRICE_FILE_STALE`. Also added `with_price_file=False` opt-out, per-store-unique sku/employee_number/asset_tag/file_label suffixes (the old constants collided chain-wide on a second helper call), and returned `price_file`/refreshed `store`.
- `fixtures.py :: setup_promo_bread_chain` — sequences the clock through the two disjoint PRD §3.5 windows (submit at `week_start − 72h`, activate inside the week) instead of parking it in one.
- `fixtures.py` — added `open_markdown_window()` and `close_markdown_window()` helpers so fixtures place the clock correctly relative to PRD §3.1's half-open markdown window.
- `test_suite/*` — ~40 fixture/assertion corrections tracing to PRD prose: `reserved_units` is a ticket **count** (§3.5) not a roll quantity; `validate_success(expected_status=201)` for creation endpoints (§4); postal-code-style stale OCC tokens replaced with fresh reads; catering pickup windows made lead-time/ready-window feasible; `c_a2_sl` references removed; slicer counts raised where fixture production dirtied the only slicer; unreachable test continuations that depended on invalid fixture identity.

**Fixes applied to `workspace/implementation/`:**
- `routes/production.py`, `routes/scales.py`, `routes/subtickets.py` — `fail(id, 400)` passed the HTTP status as the message, making `data.message` an int; removed the stray argument (7 sites).
- `routes/subtickets.py :: complete` — the `COMPLETED` state write had been dropped; restored, and the label's `unit_price_cents` now resolves from the line item rather than the ticket's SUB shell row.
- `calc.py :: sub_ticket_line_total` / `services.py :: recompute_ticket_price` — lines were priced with the ticket's top-level item; now each line prices from its own `deli_item_id` (PRD §3.4).
- `calc.py :: batch_case_yield_cost` / `services.py :: settle_batch_costs` — the final variant re-derived its base from a post-verification `discard_lbs`; PRD §3.3 says it "adds two further terms to the same base", so verification now adds only the handling fee and markdown recovery on top of the sealed provisional.
- `services.py :: recompute_label_counts` / supersede cascade — counted all labels; PRD §3.6 counts labels **written against** the file, so voided labels retire their contribution.
- `routes/scales.py :: reactivate` — reactivation now supersedes the incumbent and runs the label-void → ticket-remake cascade, exactly as a fresh activation does (PRD §3.6).
- `routes/subtickets.py :: complete` — implemented PRD §3.4's explicit "allowed exactly one late completion, and the grace it grants is the grace it must then keep" as the slip rule.
- `routes/equipment.py :: open_cycle` — added PRD §3.2's aborted-cycle reintroduction carve-out.
- `routes/catering.py` — removed a `reason` enum check the PRD never declares.
- `auth.py :: _permitted` — the replaced permission list now names operations derived from the path/method (so `["read","create","ticket"]` grants ticketing), matching PRD §2.1's "a set that omits an operation".

**Final observed pass rate:** 98/98 in each of the 8 concurrent per-test-server rounds (failed=0, errors=0, skipped=0). No skips, xfails, or seeded data; implementation storage stays in-memory. Nothing was committed.

Orchestrator verification: all 8 `results.{1..8}.json` report `passed=98 total=98 failed=0`. 25 `test_*.py` files in `test_suite/`. This step did NOT exit on the first sweep (17 iterations, 1 deletion, both `test_helpers/` and `implementation/` fixes), so Step 8 is NOT skipped.

## Step 8: Finalize PRD — align documentation to implementation — 2026-09-29T20:58:47.482Z

PRD_FINALIZED.md is written. Summary below.

### Deliverable
`/home/ubuntu/github/CodingPRD/tasks/task_3017_supermarket_deli_made_order_sub_production/workspace/PRD_FINALIZED.md`

**Line counts:** PRD.md 467 → PRD_FINALIZED.md 467 (unchanged). Char delta +3233 (~+3.2%). Headings identical; 12 prose sentences revised in place, untouched prose kept verbatim.

### Changes (one bullet per edit)

- §2.1 — **insert** — pinned the derived operation tokens a replaced permission list may name (transition verb; resource noun + `read`/`create`/`update`; plus `ticket` for collection writes; `*`/prefix-`*`), and that filtering is engaged only when the role's replacement entry exists — `auth.py:97` (`_permitted`/`_operations`), `auth.py:53` (`authorize`), `http_support.py:150` (`Endpoint.dispatch`), `routes/platform.py:29` (`role_permissions`).
- §3.1 (batch complete) — **revise** — both case-yield variants are written equal at completion because no waste record is `VERIFIED` yet — `routes/production.py:275`, `services.py:272` (`settle_batch_costs`), `calc.py:119`.
- §3.2 — **insert** — an aborted-latest cycle at `NEEDS_SANITATION` admits a fresh routine/timed cycle without re-testing dueness; the one-open-cycle rule still applies — `routes/equipment.py:199`, `:140` (`_latest_cycle_status`), `:171`.
- §3.3 (final variant) — **revise** — "same base" is the pounds subtotal less the recovery credit already reported as the provisional, not a base re-derived from a post-verification `discard_lbs`; provisional is not rewritten by verification — `calc.py:139`, `services.py:289`, `routes/waste.py:216`.
- §3.4 (line pricing) — **revise** — the per-pound price comes from the item each line's entries name (two lines naming different items price independently); the price file gates freshness only — `calc.py:151`, `services.py:525`.
- §3.4 (completion label) — **revise** — the label takes the first line item's `retail_price_per_lb_cents`, not the ticket's top-level SUB shell row — `routes/subtickets.py:243`, `services.py:591` (`unit_price_for`).
- §3.4 (slip basis) — **revise** — basis is the max lateness over prior `COMPLETED`/`PICKED_UP` tickets; `ERR_NO_COMPLETED_TICKET_YET` is declared in §5 for the closed-basis condition but is never raised — `routes/subtickets.py:214-232`, `routes/stores.py:141`, `errors.py:106`.
- §3.4 (slip lock) — **insert** — basis is 0 until a late completion sets it, so a zero-basis store admits any lateness and lets it set the basis; the bound moves as later completions raise it — `routes/subtickets.py:225-232`.
- §3.6 (`synced_scale_count`) — **revise** — counts labels still at status `ISSUED`, so a voided label retires its contribution — `services.py:304`, `services.py:352`, `routes/scales.py:112`/`:181`/`:217`.
- §3.6 (`Label`) — **revise** — `unit_price_cents` is supplied or resolved (standalone from the request, workflow from the subject's catalog price), not "from the ACTIVE file" — `services.py:571`, `routes/scales.py:210`.
- §3.6 (standalone label) — **insert** — `subject_type` enum check, `ERR_PRICE_FILE_STALE` on no active file, negative unit price malformed — `routes/scales.py:198-220`.
- §3.6 (reactivate) — **revise** — permitted only when no price file is ACTIVE-and-clock-containing; the full activation edge runs (supersede any ACTIVE file, void its labels, remake their tickets) — `routes/scales.py:148-183`.
- §3.7 (cancel) — **insert** — free-text `reason`, recorded without a constrained vocabulary — `routes/catering.py:245-266`.

### Per-edit pre-edit search log

Each of the 12 edits was preceded by enumerating every impl path touching the subject (reads + greps across all `routes/*.py`, `calc.py`, `services.py`, `auth.py`, `views.py`, `db.py`, `errors.py`):

1. **§3.3 base** — subject: final-variant base. Enumerated: `calc.batch_case_yield_cost`, `services.settle_batch_costs`, `services.recompute_batch_discard`, callsites `production.complete`(seal)/`waste.verify`/`waste.unverify`; serializers `views.batch`. (c) widened to state the base is the reported provisional and explicitly not a re-derived `discard_lbs` — chosen to avoid a false universal over a from-scratch path (created/rework rows write 0).
2. **§3.1 completion equal variants** — subject: the two cost fields at completion. Enumerated: `production.complete` (settle+seal), `settle_batch_costs`, `calc.batch_case_yield_cost`, create/rework initializers. (c) qualified "both carrying the same figure at this instant … because both further terms are zero".
3. **§3.4 slip basis (`ERR_NO_COMPLETED_TICKET_YET`)** — subject: the slip-basis check. Enumerated: `subtickets.complete` basis loop, `subtickets.get_ticket`, `stores.posture_report`, `errors.py` id and message, `test_helpers/errors`. (c) rewrote twice: first draft implied the id is raised on the closed-basis path (false — the code never raises it); final wording defines the basis and states the id is declared but unraised. Directly enabled by the one test deletion in `<step_7_diff>`.
4. **§3.4 slip lock scope** — subject: slip-lock bound. Enumerated: `subtickets.complete` rejection condition (`basis > 0 and lateness > basis`), allowing the test's "first late completion passes, equal lateness passes" behavior. (c) added the zero-basis sentence so the "exactly one late completion" summary matches the observed first-late-pass.
5. **§3.4 per-line item pricing** — subject: line price source. Enumerated: `calc.sub_ticket_line_total`, `services.recompute_ticket_price`, callsites `create_ticket`/`complete`, `views.ticket`. (c) widened from "the ordered item's" to "the item the line's entries name", since a ticket carries multiple items.
6. **§3.4 label unit price** — subject: ticket-label price. Enumerated: `subtickets.complete` label block, `svc.unit_price_for`, `svc.synthesize_label`, batch/platter/standalone label callsites. (c) scoped to "the completed build's own line items", preserving that batch/platter/standalone labels supply/resolve a price elsewhere.
7. **§3.6 `synced_scale_count`** — subject: the derived counter. Enumerated: `services.recompute_label_counts`, `supersede_price_file_cascade`, `scales.activate`/`reactivate`/`create_label`/`create_file`, `views.price_file`. (c) added "those still at status `ISSUED`" so a voided label is correctly described as retiring its contribution.
8. **§3.6 standalone label** — subject: `create_label` validation surface. Enumerated: `scales.create_label` (subject_type/weight/unit_price/active-file checks), other label paths. (c) no narrowing; folded all three behaviors into the existing sentence.
9. **§3.6 reactivation cascade** — subject: reactivation's precondition and effect. Enumerated: `scales.reactivate`, `resolve_active_price_file`, `supersede_price_file_cascade`. (c) replaced "currently ACTIVE file is expired" with the actual predicate (no ACTIVE file containing the clock) and added the full-cascade consequence.
10. **§3.7 cancel reason** — subject: catering cancel `reason`. Enumerated: `catering.cancel`, `db.Store.cancel_reason`, `api_client.cancel_catering_order`, tests 22/24/25/26/28 supplying arbitrary strings. (c) first draft over-reached by pinning clerk/INQUIRY cancellation role ordering not exercised; reverted to only the reason-vocabulary claim.
11. **§2.1 permission tokens** — subject: replaced-list matching. Enumerated: `auth._permitted`/`_operations`/`COLLECTION_NOUNS`/`ROLE_WILDCARDS`, `authorize`, `Endpoint.dispatch`, `platform.role_permissions`, tests 27. (c) first draft recited per-method/collection-modifier rules; softened to the framework-level derivation ("resource noun together with the method's own verb (read, create, update)"), avoiding enumeration blowup.
12. **§3.6 `Label` unit price provenance** — subject: label price sourcing consistency. Enumerated: `synthesize_label`, `subtickets.complete`, `catering.mark_ready`, `scales.create_label`. (c) added only to keep §3.6 from contradicting the §3.4/§3.7 edits; worded map-agnostically ("supplies or resolves … the labelled subject's catalog price").

### Deliberately not patched (traced to `<step_7_diff>` but PRD already pins the behavior, or pure fixture/impl-bug)
- `routes/*` `fail(id, 400)` int-message removal (7 sites) — `message` must be human-readable (PRD §2.2); impl bug, not PRD silence. `grep` confirms no remaining `fail(..., <int>)`.
- `fixtures.setup_deli_master_data` price-file provisioning; `setup_promo_bread_chain` two-window clock sequencing; `open/close_markdown_window` helpers — all describe behavior PRD already fixes (§2.6/§3.6, §3.5, §3.1/§3.3).
- `test_suite/*` assertion corrections (`reserved_units` as a ticket count §3.5, `validate_success(201)` §4, fresh OCC tokens §2.10, catering window feasibility §3.7, removed `c_a2_sl`, slicer counts) — each states what PRD already requires.

No implementation behavior outside the Step 7 sites would be mis-described by any edit. No files staged or committed.

Orchestrator verification: `PRD_FINALIZED.md` present, 467 lines / 103640 bytes (char delta +3233 vs PRD.md, line count unchanged — minimal in-place edits as required).

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-09-29T21:16:52.521Z

Done. The PRD_COMPLETED.md has been written as a minimal patch over PRD_FINALIZED.md, with every change pinned to observed `implementation/` behavior.

### Source vs output

| | PRD_FINALIZED.md | PRD_COMPLETED.md | Delta |
|---|---|---|---|
| Lines | 467 | 467 | 0 |
| Chars | 103,640 | 108,713 | +5,073 |

No sections added or removed; all edits are in-paragraph inserts or in-place revisions.

### Counts
- **Ambiguity-pins: 28**
- **Mismatch-revisions: 10**
- Total changes: 38

### Change bullets

- §2.1 RBAC — insert — ambiguity — entity-backed `X-User-ID` is resolved against `Associate` only on the two acting-associate reads, and an unmatched identifier reads as empty allergy set / no certifications (never rejected) — `auth.py:118-125`, `routes/subtickets.py:195`, `routes/catering.py:130`
- §2.5 clock — revise — mismatch — default instant is `2026-09-01T00:00:00.000Z` (three fractional digits), not the bare `Z` form — `util.py:12`
- §2.5 clock — insert — ambiguity — `current_utc` is normalised to canonical UTC and the normalised value is echoed back — `routes/platform.py:19-26`, `util.py:58-60`
- §2.5 clock — insert — ambiguity — since no wall clock is read, `api_request_timestamp` is the logical clock instant — `response.py:24-28`
- §3.2 slicer — revise — mismatch — `in_use_minutes` does not accumulate in-use time; it is zeroed by a completed cycle and otherwise stays zero; `last_sanitized_at` = registration instant for a fresh asset — `calc.py:311-316`, `routes/equipment.py:68-69`, `routes/equipment.py:278`
- §3.2 slicer — insert — ambiguity — cycle opening requires `sanitation_status` in `{NEEDS_SANITATION, CLEAN, SANITIZING}` — `routes/equipment.py:206-208`
- §3.2 cycle — insert — ambiguity — `buffer_minutes` is recorded on the cycle and does not alter its `cycle_minutes` — `routes/equipment.py:162`, `:220`
- §3.2 cycle — insert — ambiguity — abort (manager-only) takes a `reason` and clears `open_sanitation_cycle_id` — `routes/equipment.py:320-331`
- §3.2 cycle — insert — ambiguity — reopen carries an optional, unconstrained `reason` — `routes/equipment.py:297-298`
- §3.1 batch create — insert — ambiguity — producer, `slicer_id` and `rework_of_batch_id` must be same-store; mismatch → `ERR_NOT_FOUND` — `routes/production.py:74-84`
- §3.1 batch start — insert — ambiguity — the slicer commitment set is non-aborted sanitation cycles plus in-flight `IN_PRODUCTION` batches — `routes/production.py:210-239`
- §3.1 batch complete — insert — ambiguity — completion clears the slicer's `assigned_deli_item_id` — `routes/production.py:282`
- §3.1 batch mark-down — insert — ambiguity — `recorded_by_associate_id` is optional and becomes the synthesized record's `markdown_by_associate_id` — `routes/production.py:370-392`
- §3.1 batch mark-down — insert — ambiguity — a successful mark-down synthesizes a `DRAFT` waste record with reason `HOLD_EXPIRED` — `routes/production.py:377-393`
- §3.1 rework — insert — ambiguity — the successor's own `batch_code`/`planned_lbs`/producer/`slicer_id` are required and reuse the fresh-batch rules — `routes/production.py:308-322`
- §3.1 sweep — insert — ambiguity — the chain-wide sweep returns the array of swept stores — `routes/stores.py:105`
- §3.3 waste — insert — ambiguity — a second concurrent open record on one batch → `ERR_MARKDOWN_REQUIRED_BEFORE_DISCARD` — `routes/waste.py:51-54`
- §3.3 waste — insert — ambiguity — unverify clears verifier and certification references — `routes/waste.py:232-234`
- §3.4 queue — insert — ambiguity — `QUEUED`→`IN_PROGRESS` only fires from `TICKETED`; a read or a completion advances an eligible `TICKETED` ticket rather than refusing it — `services.py:535-567`, `routes/subtickets.py:186`
- §3.4 completion — insert — ambiguity — allergen coverage is screened only for entity-backed acting roles — `routes/subtickets.py:195`
- §3.4 completion — insert — ambiguity — `net_weight_lbs` is subject to the 10-lb scale lock → `ERR_LABEL_WEIGHT_EXCEEDED` — `routes/subtickets.py:190-192`
- §3.4 queue read — insert — ambiguity — returns `ordered`/`queue_depth`/`ordered_total_count` and applies `limit`/`offset` to the ordered set — `routes/subtickets.py:296-315`
- §3.5 bread submit — insert — ambiguity — `required_units` is (re)copied from the promotion's provisional forecast at submit — `routes/promotions.py:217-220`
- §3.5 bread reopen — insert — ambiguity — manager-level, takes a `reason`, clears `delivered_units` — `routes/promotions.py:276-284`
- §3.5 bread hold — revise — mismatch — `QUEUED`→`BREAD_HOLD` fires only on the allergen-changeover cascade, not on bread unavailability or `RESTRICTED` posture — `services.py:369-379`
- §3.6 label — insert — ambiguity — `unit_price_cents`, `total_price_cents` and `printed_at` are server-computed at issue, not echoed — `services.py:571-588`
- §3.6 supersession — insert — ambiguity — a label issued against a just-superseded file survives the cascade and is counted against it — `routes/scales.py:106-113`, `services.py:352-366`
- §3.7 confirm — insert — ambiguity — planner-certification test runs first; the ACTIVE `FOOD_HANDLING` floor-waiver also honours the acting entity-backed associate — `routes/catering.py:125-132`
- §3.7 confirm — insert — ambiguity — the non-`OPEN` store gate reports `ERR_POSTURE_RESTRICTED` (also when posture is `HALT`) — `routes/catering.py:143-144`
- §3.7 mark-ready — insert — ambiguity — requires an ACTIVE price file (`ERR_PRICE_FILE_STALE`) and clock ≥ window start − 2h, else `ERR_INVALID_STATE`; label weight = `servings_per_platter` — `routes/catering.py:214-227`
- §3.7 cancel — insert — ambiguity — cancel from `IN_PRODUCTION`/`READY` is `ERR_UNAUTHORIZED` below manager; `reason` optional and unconstrained — `routes/catering.py:250-262`
- §4 endpoint table — revise — mismatch — `/deli/slicers/{id}/assign-operator` and `PATCH /deli/slicers/{id}` authorise `PlatformAdmin, DeliManager` — `routes/equipment.py:28,30`
- §4 endpoint table — revise — mismatch — `/deli/sanitation-cycles/{id}/reopen` and `/abort` authorise `PlatformAdmin, DeliManager` — `routes/equipment.py:37-40`
- §4 endpoint table — revise — mismatch — the four `/deli/promotions/{id}/*` transitions authorise `PlatformAdmin, DeliManager` — `routes/promotions.py:23-26`
- §4 endpoint table — revise — mismatch — `/deli/bread-supply-orders/{id}/reopen` authorises `PlatformAdmin, DeliManager` — `routes/promotions.py:37-38`
- §4 endpoint table — revise — mismatch — `/deli/waste-records/{id}/verify`, `/unverify`, `/void` authorise `PlatformAdmin, DeliManager` — `routes/waste.py:30-33`

Verification notes: the four §4 table role changes were found by enumerating every `Endpoint(...)` call in `routes/*.py` (99 routes) and diffing its role list against the table; the PRD's §4 prose ("a manager-level caller", "a platform-admin-only capability") otherwise left the two-manager endpoints under-specified. `ERR_NO_COMPLETED_TICKET_YET` is declared in §5 but raised by no code path — the PRD already says so explicitly in §3.4, so it was left unchanged. No files were staged or committed.

Orchestrator verification: `PRD_COMPLETED.md` present, 467 lines / 108713 bytes (char delta +5073 vs PRD_FINALIZED.md, line count unchanged — minimal in-place edits as required). Steps 8 and 9 were documentation-only; neither touched `test_suite/`, `test_helpers/`, or `workspace/implementation/`.

## Post-pipeline confirmation sweep — 2026-09-29T21:31:00.000Z

Orchestrator re-ran the full 8-round parallel stability sweep against the final on-disk artifacts (after Steps 8 and 9 wrote their documentation-only edits, so the shipped directory is verified in its delivered state rather than only in its Step 7 state).

All 8 rounds report `passed=98 total=98 failed=0 errors=0 skipped=0`. `results.{1..8}.json` in `workspace/implementation/` are the artifacts of this final sweep. Single-round wall time ≈ 176 s.

Package is complete and verified: