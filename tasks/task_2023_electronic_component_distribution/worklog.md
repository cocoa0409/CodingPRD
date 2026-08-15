## Step 2: Generate Scaffold — 2026-08-15T08:48:30.000Z

Done. All three scaffold artifacts are generated, validated, and lint-clean.

## Completion Summary

**Output directory:** `/home/ubuntu/github/CodingPRD/tasks/task_2023_electronic_component_distribution/`

### Files produced
- `SCAFFOLD.yaml` (~1490 lines) — §1.0–§1.7; contains neither `scaffold_difficulty_design` nor `scaffold_corner_design` keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (~1385 lines) — single top-level key `scaffold_difficulty_design` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (~2370 lines) — single top-level key `scaffold_corner_design` (§1.9)

### Counts
- 12 entities, 8 state machines, 11 calculations, 9 ordered validation priorities, 52 endpoints, 51 error codes, 6 roles, 2 OCC concurrency rules
- §1.8: 18 instances (all 9 Difficulty Rules × 2, all active, all with structured `setup_api_calls`/`trigger` chains)
- §1.9: 70 instances (60 active + 10 `excluded_because` stubs), spanning all nine claim-extraction-guide sections: entities, state_machines, calculations, validations, endpoints, errors, rbac, complexity_layers, consistency_model

### Validation results (all passed)
- All three files parse as valid YAML; file-split rule honored
- `scaffold_lint.py` verdict, verbatim: **"VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5."** (52 endpoints, 12 entities, 18 §1.8 + 60 §1.9 instances, 688 calls scanned). Two lint findings were fixed en route: unquoted `$.data[N].id` JSONPaths and bracketed `grounds:` refs in flow context (YAML-illegal plain scalars), and the `GET /lots/{lotId}/exposures` sub-resource needed the literal `{id}` segment for check (f).
- Self-checks: no forbidden race vocabulary; 84 unique instance names across both design files; every error code referenced by a validation/transition AND exercised by a design instance; zero unbound `${var}` placeholders; all pinned numeric literals verified by executing the formulas (fair-share 45/45 vs 68/22; floor+remainder 31/40/30; claim 6000 vs 5600; buy-back 13500 → 11250; cap 148500 inclusive; cancel_by 2026-09-01; day counts 50/100/181).

### Notable design decisions
- **Archetype blend:** quota/allocation (fair-share shortage waterfall) + ledger reconciliation (ship-and-debit provisional vs audited claims); flat topology with FK bodies; cyclic state-machine shape (lot quarantine↔bake, claim dispute↔resubmit, registration EXHAUSTED→APPROVED restore); segregation-of-duties role model (lot receiver ≠ inspector).
- **Logical clock** `POST /_clock/set_current_utc` with the mandatory default `2026-08-01T00:00:00Z`; clock sets drive the MSL-quarantine and registration-expiry sweeps (the depth-3 cascade trigger: lot → line deallocation → order recompute).
- **Interval semantics deliberately opposed** for Rule 8: registration windows are CLOSED (touching conflicts) vs MSL exposure intervals half-open (adjacency at `sealed_at` allowed, nesting rejected).
- **Boundary pins:** cancel window strict `<` (exactly at `cancel_by_date` fails), buy-back cap inclusive `<=`, MSL breach at `>=` floor life, date-code fresh at `months_elapsed == limit`.
- **OCC** on `Part.version` (allocation-run supersede) and `CustomerOrder.version` (reschedule), both 412-resolved; stale tests replay a previously captured version variable rather than literals.
- Fixed during self-consistency replay: added an auto-transition for orders whose lines all cancel with none shipped (ACKNOWLEDGED→CANCELLED), disambiguated a same-priority state-error test by making the order PARTIALLY_SHIPPED, pinned list ordering (`created_at ASC`, same-request lines by array index) and staggered claim timestamps where list position is captured.

(Note: the subagent was interrupted once by an API rate-limit error after writing SCAFFOLD.yaml and SCAFFOLD_DIFFICULTY_DESIGN.yaml; it was resumed and completed SCAFFOLD_CORNER_DESIGN.yaml plus all validation.)

## Step 3: Copy Shared Files — 2026-08-15T08:49:10.000Z

Copied ./INSTRUCTION.md to tasks/task_2023_electronic_component_distribution/workspace/INSTRUCTION.md (bash-only step).

## Step 4: Generate PRD — 2026-08-15T08:55:30.000Z

All checks pass. The PRD is complete and ships.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2023_electronic_component_distribution/workspace/PRD.md`

**What was generated:** A prose-style PRD for the electronic component distribution domain (franchise/open-market sourcing, MSL handling, shortage allocation, ship-and-debit, scheduled orders, buy-backs), structured as:

- **§1** — 3-paragraph introduction from business-context and operational-pressure angles.
- **§2** — 11 subsections: §2.1 RBAC (all six roles with exact spellings; opaque vs `entity_backed:Customer` identity translated per role), §2.2 emitted verbatim from `section-2.2-response-structure.md` (byte-identical, verified programmatically), §2.3 pagination (limit default 10 / min 1 / max 100, offset 0, `created_at` ascending, order-line array-index tie-break), then domain-derived subsections: §2.4 logical clock + sweep (startup default `2026-08-01T00:00:00Z`), §2.5 franchise authenticity + segregation of duties, §2.6 moisture/date-code rules, §2.7 nested retrieval left-to-right, §2.8 common resource properties, §2.9 integer-cents precision + round-half-up, §2.10 the two OCC guards, §2.11 the 9-tier validation priority including NCNR-before-window and safety-before-fiscal.
- **§3** — 9 subsections organized by business process (catalog → registrations → orders/cancellation terms → allocation → quarantine/bake → shipping → claims → alternates → buy-backs), with all rules scattered into narrative and zero HTTP paths or bare methods.
- **§4** — 52-row endpoint table, exactly 4 columns.
- **§5** — 51-row error catalogue, exactly 2 columns, no trigger conditions.

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 75 required, 75 present, 0 missing
- endpoints[].request_body (incl. OCC fields): 52 required, 52 present, 0 missing
- endpoints[].query_params: 12 required, 12 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] priority ordering: 9 tiers expressed in §2.11 prose (incl. NCNR-before-window and safety-before-fiscal notes), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write capability + expected_part_version/expected_order_version + ERR_STALE_PART_VERSION/ERR_STALE_ORDER_VERSION + HTTP 412 all named), 0 missing
- state_machines[].transitions: 35 checked across 8 machines, 35 fully expressed (from/to states, preconditions paired with error_ids, side effects), 0 missing
- calculations[]: 11 checked, 11 fully expressed as reconstructible prose (floor-then-remainder waterfall, FEFO reserve/release, claim provisional/final, MSL accrual, month-age freshness, tiered buy-back credit, 15% cap, ship credit gate, order exposure, part availability, debit reconciliation), 0 missing
- validations[] conditions: 51 error_ids all matchable to trigger prose in §2/§3, 0 missing
- endpoints[].side_effects / applies_to: all expressed (clock sweep, acknowledge snapshots, publish cascade, ship cascades, claim ledger sync, buy-back receive lot creation), 0 missing
- entities[].fields[] structured content: defaults, snapshots, computed fields, system fields all reconstructible from prose, 0 missing
- sibling-branch symmetry: 8 parallel groups checked (inspect dispositions, registration decisions, claim tri-decision + dual reject branches, allocation basis variants, order vs line cancel, provisional vs final amounts, buy-back kinds, reserve vs release), all with equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 384
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

The two withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were not opened, grepped, or referenced at any point.

## Step 5: Generate Unit Tests — 2026-08-15T09:35:00.000Z

95 tests collected cleanly with zero errors. Generation is complete and verified.

## Summary

**Generated** in `/home/ubuntu/github/CodingPRD/tasks/task_2023_electronic_component_distribution/`:

**`test_helpers/`** (Stage 1):
- `types.py` — 12 entity TypedDicts + 13 status/role enums (all entities carry `common_fields: true`, so all keep `id`/`created_at`/`updated_at`/`version`)
- `api_client.py` — 52 endpoint methods covering every PRD §4 endpoint
- `api_errors.py` — 52-member `ApiErrorId` enum; HTTP status map registers only the 46 statuses in PRD §5. `ERR_BUYBACK_CAP_EXCEEDED` is deliberately **unmapped**: PRD §3.9 names it but §5 assigns no status (scaffold's 422 is invisible to a PRD-only implementer), so `validate_error` checks its error_id only
- `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (opaque roles as shared constants; `make_customer_buyer_headers(customer_id)` builder for the entity-backed role), `fixtures.py` (composite chains: acknowledged → allocated → shipped orders, submitted claims, quarantine-by-clock, buy-back scenarios), `__init__.py` barrel

**`test_suite/`** (Stage 2): `conftest.py` + 12 test files, **95 tests** — 36 Difficulty tags (all 18 §1.8 instances × 2) and 59 Corner tags covering 59 of 60 non-stub §1.9 instances. Every test carries a verbatim PRD citation (139 quoted spans machine-verified against PRD.md) and exactly one `Design:` tag resolving to a real instance (verified against both yamls; all 9 `excluded_because` stub cross-references resolve).

**Skips / deviations (PRD-first filter):**
1. **`Corner/errors/order_cancel_with_shipped_line_rejected` — SKIPPED.** Its scenario ships a line, which auto-moves the order to `PARTIALLY_SHIPPED` (PRD §3.6), then asserts order-cancel fails with `ERR_ORDER_HAS_SHIPPED_LINES`. PRD §3.3 derives `ERR_ORDER_NOT_ACKNOWLEDGED` for cancel-from-any-non-ACKNOWLEDGED state, and §2.11's priority order (state p4 before referential p8) confirms it — the asserted error is unreachable in the specified scenario. Gap left as a gap.
2. **`hold_state_beats_temporal_window`** — the reschedule-on-ON_HOLD assertion uses `validate_error_is_one_of([ERR_ORDER_ON_HOLD, ERR_ORDER_NOT_ACKNOWLEDGED])` (+409, ship_date unchanged), because PRD names `ERR_ORDER_ON_HOLD` only for ship; both candidates are priority-4 state errors, so the instance's state-beats-temporal claim is intact.
3. **`debit_dollar_conservation_settle_reverse` arithmetic bug** — the design index asserts `bal_3 == 5600` after reversing claim1, but the PRD event rules (settle adds `amount_final_cents`, reverse subtracts the same) yield 11600 − 5600 = **6000** (claim2's final remains). The PRD-derivable 6000 is asserted; the yaml's 5600 matches no consistent PRD reading.
4. Absolute version literals (e.g. `version == 1` at create) were converted to relative assertions (`v_after == v_before + 1` / unchanged-on-rejection), since PRD §2.8 pins the increment, not the starting value.

Verified: `py_compile` clean, pyflakes clean (except intentional barrel re-exports), full tag/coverage audit pass, no `skip`/`skipif`/`xfail` markers, `pytest --collect-only` collects 95 tests.

## Step 6: Generate Implementation — 2026-08-15T09:35:00.000Z

Implementation complete. All seven verification suites pass and the `start.sh` contract is verified under simulated per-test reboots.

## What was built

Python + Flask implementation in `/home/ubuntu/github/CodingPRD/tasks/task_2023_electronic_component_distribution/workspace/implementation/`:

- **`start.sh`** — foreground launcher with guarded dependency install (`if ! python3 -c "import flask"`), `exec python3 app.py`, honors `PORT` (default 10000), binds `0.0.0.0`
- **`app.py`** — entry point, blueprint registration, `ApiError`/404/405/fallback handlers producing the scaffold's error envelope
- **`db.py`** — in-memory stores, empty on every boot (no seeding)
- **`clock.py`** — logical clock pinned at `2026-08-01T00:00:00Z` at boot, never wall-clock; all entity timestamps and `meta.api_request_timestamp` read from it
- **`errors.py` / `response.py` / `middleware.py`** — exact error catalog, `meta`/`response_type`/`data` envelope with `limit`/`offset`/`total_count`/`has_more` pagination in `meta`, and `X-User-ID`/`X-User-Role` auth with the six declared roles plus `CustomerBuyer` entity-backed ownership
- **`routes/`** — one module per resource group: clock sweep, catalog (lines/parts), customers, registrations, orders (acknowledge/cancel/reschedule/ship/lines), alternates, lots (inspect/exposures/seal/bake), allocations, claims, buybacks
- **`services/helpers.py`** — MSL accrual (whole-hour floor, last_baked_at exclusion), FEFO reserve/release, quarantine cascade (deallocate newest-first: `created_at DESC, ship_date DESC`), order exposure/allocated-value recompute with per-parent version bumps, fair-share waterfall (floor + one-unit remainder passes ordered `created_at ASC, ship_date ASC, quantity DESC`, both BACKLOG/USAGE bases), serializers

## Key fidelity decisions (PRD-verified)

- Validation priority order enforced: auth → role/ownership → shape → FK existence → state → safety (SoD, date-code) → constraints → temporal (NCNR before window within the cancellation-terms group) → referential → fiscal last; safety beats fiscal at ship
- OCC: `expected_part_version` (412 `ERR_STALE_PART_VERSION`) on run create, `expected_order_version` (412 `ERR_STALE_ORDER_VERSION`) on reschedule — both required fields
- Boundary semantics: cancel window strict `<`, cancel_by computed as `ship_date - cancel_window_days_snapshot`, buy-back 180-day window inclusive, date-code months `<= limit` fresh, MSL breach at `>=` floor life, credit check equality allowed, buy-back cap inclusive
- Ship model: `qty <= allocated_qty - shipped_qty` with both fields mutated per ship (literal scaffold semantics); substitute ships draw from `qty_on_hand` of the substitute part and resolve claims against the shipped part
- Claims: provisional pinned at ship, final computed at APPROVE (audited defaults to registered), settle/reverse reconcile `open_debit_balance_cents` to zero net drift, REJECT/REVERSE restore registration qty with EXHAUSTED→APPROVED resurrection

## Verification

Seven in-process suites (~150 assertions) covering envelope/auth, CRUD, shortage waterfalls (34/33/33 backlog split, 15/30/45 usage split, zero-weight remainder passes), publish supply re-verification, quarantine cascade with order version bumps, bake cycle, registration overlap/expiry, ship/claims/settle/reverse ledger, substitutes, NCNR rules, credit-hold→ON_HOLD→release, buy-back tiers/cap/window/receive, nested 404 ordering, and pagination bounds — all pass. `start.sh` boot-tested twice with kill-between: clean empty state and correct default clock on every fresh process.

Note: this host runs concurrent agents sharing `/tmp` and process space — one debugging detour (a clobbered `/tmp/smoke.py`, servers killed by foreign `pkill`) was environment noise, not implementation issues; verification moved to namespaced paths and in-process WSGI transport.

## Step 7: Run Tests and Iterate — 2026-08-15T10:05:00.000Z

All 8 rounds pass — 95/95 in every round. Clean sweep.

## Summary

- **Iterations run**: 2 (initial sweep + post-fix sweep, both 8 rounds).
- **Tests deleted**: None.
- **Fixes applied to `test_helpers/`**:
  - `/home/ubuntu/github/CodingPRD/tasks/task_2023_electronic_component_distribution/test_helpers/api_errors.py`: added `ERR_ALLOCATION_RUN_NOT_PROVISIONAL` to the `ApiErrorId` enum (named by PRD §3.4 prose but absent from the §5 catalogue table); deliberately omitted from `HTTP_STATUS_CODES` map (same pattern as `ERR_BUYBACK_CAP_EXCEEDED`) so `validate_error` checks error_id only.
- **Fixes applied to `test_suite/`**: None.
- **Fixes applied to `implementation/`**:
  - `/home/ubuntu/github/CodingPRD/tasks/task_2023_electronic_component_distribution/workspace/implementation/services/helpers.py`: added `stamp_clock()` that emits `YYYY-MM-DDTHH:MM:SSZ` when the logical clock sits on a whole-second instant (PRD §2.8 mandates three fractional digits only for `created_at`/`updated_at`/`api_request_timestamp`; other clock-stamped fields like `sealed_at`/`opened_at`/`last_baked_at`/`last_shipped_at` are format-unspecified in PRD).
  - `/home/ubuntu/github/CodingPRD/tasks/task_2023_electronic_component_distribution/workspace/implementation/routes/lots.py`: switched `opened_at`, `sealed_at`, `last_baked_at` to `stamp_clock()`.
  - `/home/ubuntu/github/CodingPRD/tasks/task_2023_electronic_component_distribution/workspace/implementation/routes/orders.py`: switched `last_shipped_at` to `stamp_clock()`; fixed ship-quantity gate from `qty > allocated_qty - shipped_qty` to `qty > allocated_qty` (PRD §3.6 decrements `allocated_qty` on every ship, so it already IS the unshipped allocated remainder).
  - `/home/ubuntu/github/CodingPRD/tasks/task_2023_electronic_component_distribution/workspace/implementation/routes/allocations.py`: remainder-distribution sort now uses `_seq` (true insertion order) as the primary "line creation time" key, since the logical clock's millisecond-precision `created_at` ties across lines created within the same logical instant; PRD's `ship_date`/`quantity DESC` keys remain as documented tie-breaks.

## Step 8: Finalize PRD — 2026-08-15T10:12:00.000Z

The diff is minimal and complete. Final verification confirms all edits are in place.

## Summary

**File**: `/home/ubuntu/github/CodingPRD/tasks/task_2023_electronic_component_distribution/workspace/PRD_FINALIZED.md`

**Line counts**: PRD.md 320 lines → PRD_FINALIZED.md 323 lines (+3 lines, +0.94%).

### Changes (one bullet per change)

- **§2.8** — insert — new paragraph pinning the wire format of the four non-`created_at`/`updated_at` clock-stamped fields (`opened_at`, `sealed_at`, `last_baked_at`, `last_shipped_at`): ISO 8601 UTC at seconds precision (e.g. `2026-08-01T00:00:00Z`) when the logical clock sits on a whole-second instant, three fractional digits otherwise — `implementation/services/helpers.py:26-35` (`stamp_clock()`), call sites `routes/lots.py:181,221,242`, `routes/orders.py:469`.
- **§3.4** — revise — remainder-distribution iteration key changed from "line creation time" to "line creation order" (insertion sequence; same-request lines follow array index; total even when `created_at` timestamps tie); `ship_date` then descending-`quantity` tie-breaks unchanged — `implementation/routes/allocations.py:80` (sort key `(_seq, _ship_date, -quantity)`).
- **§3.6** — revise — ship-quantity gate: replaced the "(`allocated_qty` minus `shipped_qty`)" formula with "the line's current `allocated_qty`", since every successful ship already decrements `allocated_qty` — `implementation/routes/orders.py:425` (gate) and `orders.py:468` (decrement).
- **§5** — insert — added catalogue row `ERR_ALLOCATION_RUN_NOT_PROVISIONAL | 409 Conflict` (error_id was named in §3.4 prose but the HTTP status was PRD-silent) — `implementation/routes/allocations.py:188`.

The Step 7 `test_helpers/api_errors.py` fix itself was a fixture gap (enum membership), but it exposed the PRD silence on that error's HTTP status, which the §5 row now pins.

### Per-edit pre-edit search log

1. **§2.8 timestamp paragraph**
   - (a) Subject: wire format of logical-clock-stamped fields other than `created_at`/`updated_at`.
   - (b) Enumerated via grep for `stamp_clock|stamp_now|strftime|isoformat` across all of `implementation/`: `stamp_clock()` call sites are exactly the four fields (`lots.py:181` `opened_at`, `lots.py:221` `sealed_at`, `lots.py:242` `last_baked_at`, `orders.py:469` `last_shipped_at`); all `created_at`/`updated_at` use `stamp_now()` (always 3 fractional digits, ~20 sites incl. `routes/clock.py:29` sweep); `api_request_timestamp` (`response.py:20`) and the clock-advance response `now` (`routes/clock.py:58`) always use 3 fractional digits; `valid_from`/`valid_to`/`ship_date`/`cancel_by_date` are ISO dates, `date_code` is `YYYYMM`; serializers pass stored strings through verbatim.
   - (c) Wording scoped to the four fields named explicitly (rather than "all other clock-stamped fields") so the always-3-digit `now` in the clock-advance response and `api_request_timestamp` are not mis-described.
2. **§3.4 remainder ordering**
   - (a) Subject: ordering key for distributing leftover units in fair-share allocation.
   - (b) Enumerated: `allocations.py:80` (`_seq` primary, `_ship_date`, `-quantity`); `_seq` provenance in `orders.py:143-168` (array-index order within a request, monotonic across requests); other creation-ordered sites checked for collision — `_eligible_lines` sort (`allocations.py:44`, backs the untouched "stored lines sorted by creation time ascending" sentence), quarantine clawback (`helpers.py:465`, §3.5), list endpoints (`§2.3`); §2.3's array-index tie-break sentence echoed for consistency.
   - (c) Used "creation order / sequence in which the lines were created" instead of "creation timestamp" so the wording also holds if the logical clock is moved backward (`_seq` is timestamp-independent); kept the definition parenthetical inside the remainder clause so the adjacent stored-lines sentence is untouched.
3. **§3.6 ship gate**
   - (a) Subject: upper bound on ship `qty` / meaning of `allocated_qty` at ship time.
   - (b) Enumerated every `allocated_qty` path: publish assignment (`allocations.py:205`), ship gate (`orders.py:425`), ship decrement (`orders.py:468`), cancel zeroing (`orders.py:65-67`), quarantine-cascade decrement (`helpers.py:471-479`), `allocated_value_cents` recompute (`helpers.py:361`), run storage (`allocations.py:129,191`); cross-checked §3.6's later "allocated_qty down by `qty`" sentence and §2.11's "quantity sufficiency" mention.
   - (c) Phrased as "the line's current `allocated_qty`, which every successful ship decrements" — true at publish (nothing shipped yet), after partial ships, after cascade clawback, and for the zero-allocation `ALLOCATED` edge (gate rejects any `qty ≥ 1`); no enumerated path contradicts it.
4. **§5 catalogue row**
   - (a) Subject: HTTP status for `ERR_ALLOCATION_RUN_NOT_PROVISIONAL`.
   - (b) Enumerated: sole raise site `allocations.py:188` (HTTP 409, publish on non-`PROVISIONAL` run); constant declared `errors.py:74`; §3.4 prose already names the error_id; no other route raises it.
   - (c) No adjustment needed; row placed in the allocation-error group before the OCC entries. `ERR_BUYBACK_CAP_EXCEEDED` deliberately left absent (pre-existing pattern, not a Step 7 fix — hard scope).

## Step 9: Complete PRD — 2026-08-15T10:30:00.000Z

All edits verified — 26 hunks, all inline. The task is complete. Final summary:

## Summary

**Source vs output:** `workspace/PRD_FINALIZED.md` (323 lines / 50,923 bytes) → `workspace/PRD_COMPLETED.md` (324 lines / 56,439 bytes). Delta: **+1 line, +5,516 bytes (+5,464 chars)**. All changes are in-paragraph inserts/revisions plus one table row in §5 — no new sections, no new paragraphs.

**Counts:** 21 ambiguity-pins, 5 mismatch-revisions (26 hunks total).

### Mismatch-revisions (PRD described behavior impl does not exhibit)
- **§2.6** — revise — mismatch — `msl_exposure_hours` is the whole-hour floor of the *accumulated total* exposure across qualifying intervals (fraction discarded once on the total), not a sum of per-interval whole-hour floors; intervals whose end doesn't exceed their start contribute nothing — `implementation/services/helpers.py:299-313`
- **§2.11** — revise — mismatch — actual validation order is auth → endpoint role → request shape → path-identifier 404s (leftmost first) → `CustomerBuyer` ownership → body-FK 404s → state preconditions (incl. shipped-lines guard, and the §2.10 OCC guard immediately after state) → safety → business → temporal → referential → fiscal; previously PRD pinned ownership with role auth and all 404s after shape — `implementation/routes/registrations.py:41-55`, `orders.py:90-123,256-271,308-318`, `allocations.py:109-111`
- **§2.6** — revise — mismatch — `msl_level` recorded as any supplied integer without range validation (was "in the range 1 through 6") — `implementation/routes/catalog.py:114`
- **§3.1** — revise — mismatch — customer `status` may be supplied at creation (`GOOD_STANDING`/`CREDIT_HOLD`, else `ERR_INVALID_REQUEST`), defaulting to `GOOD_STANDING`; creation-time status is the only way into `CREDIT_HOLD` since no customer-update operation exists — `implementation/routes/customers.py:45-47`
- **§3.9** — revise — mismatch — non-positive `received_qty` is `ERR_INVALID_REQUEST` (§2.11 shape), only over-requested `qty` is `ERR_BUYBACK_QTY_EXCEEDED`; also pinned `lot_date_code` format rejection — `implementation/routes/buybacks.py:223-228`

### Ambiguity-pins (PRD silent/multi-interpretation → pinned to impl)
- **§2.1** — insert — GET reads perform no ownership check; ownership constrains mutating operations only — `implementation/middleware.py:33-49` + all GET routes
- **§2.3** — insert — non-integer/out-of-range `limit` (1–100) or negative `offset` rejected with `ERR_INVALID_REQUEST` — `implementation/services/helpers.py:169-191`
- **§2.3** — revise — `created_at` ties broken by creation sequence on *every* list endpoint (not just order lines) — e.g. `implementation/routes/catalog.py:86`
- **§2.4** — insert — unparseable `to_iso8601` is `ERR_INVALID_REQUEST`; clock applies the instant with no monotonicity check (backward sets allowed) — `implementation/routes/clock.py:51-58`, `clock.py:14-17`
- **§2.4** — insert — registration expiry compares calendar dates: expires only when the new current date is strictly after `valid_to` (live through its `valid_to` day) — `implementation/routes/clock.py:23-30`
- **§2.7** — insert — undefined paths → `ERR_NOT_FOUND` (404), unsupported method on a defined path → `ERR_METHOD_NOT_ALLOWED` (405) — `implementation/app.py:32-39`
- **§3.2** — insert — inverted validity windows (`valid_from` > `valid_to`) stored without rejection, simply never covering a ship date — `implementation/routes/registrations.py:46-47`
- **§3.2** — insert — optional `reason`/`note` on all decision-style operations accepted but never persisted or echoed — `implementation/routes/registrations.py:131-149`, `claims.py:78-112`, `alternates.py:108-133`, `buybacks.py:205-215`
- **§3.3** — insert — pinned the order monetary formulas: `open_exposure_cents` = Σ(`quantity`−`shipped_qty`)×`unit_price_cents` over `OPEN`/`ALLOCATED` lines; `allocated_value_cents` = Σ`allocated_qty`×`unit_price_cents` over all lines — `implementation/services/helpers.py:353-365`
- **§3.3** — revise — cancel window compared by calendar date; whole-order cancel validates the terms group on all open lines before cancelling any (atomic) — `implementation/routes/orders.py:56-61,269-276`
- **§3.3** — revise — reschedule: cutoff compared by calendar date; new date must be strictly later than the current calendar date; NCNR requires strictly later than current `ship_date` (same-day rejected); order-state check fires before the OCC version check — `implementation/routes/orders.py:315-329`
- **§3.4** — insert — all-zero weights (USAGE_BASIS) → all raw shares zero, whole supply distributed via remainder passes — `implementation/routes/allocations.py:68-91`
- **§3.4** — insert — publish skips run lines whose target is no longer `OPEN`, but supply re-verification and the FEFO reservation still use the run's full stored totals — `implementation/routes/allocations.py:191-212`
- **§3.6** — insert — substitute pick draws only what is available; the ship still commits the full requested `qty` against the line when substitute stock is short — `implementation/routes/orders.py:394-417,456-474`
- **§3.6** — revise — "shipped part" for claim coverage = the substitute part when `substitute_part_id` is supplied; `standard_cost_cents` snapshot also comes from the shipped part — `implementation/routes/orders.py:390,487-506`
- **§3.7** — revise — settle/reverse post the debit to the manufacturer line of the claim's order line's (primary) part, even for substitute-arisen claims — `implementation/routes/claims.py:33-40,135-139`
- **§3.8** — insert — same-part proposal (`alternate_part_id` == `primary_part_id`) is `ERR_INVALID_REQUEST` — `implementation/routes/alternates.py:41-44`
- **§3.9** — insert — covering buy-backs each contribute their requested `qty` (not `received_qty`); no verification that the named order line belongs to the named customer — `implementation/routes/buybacks.py:83-88`
- **§3.9** — insert — fee fraction stays 0.25 beyond 180 days (reachable only at receipt) — `implementation/routes/buybacks.py:43-50`
- **§3.9** — revise — 180-day excess-return window and 365-day cap window measured as exact elapsed durations (180/365 × 24 h) from the relevant instant, boundary inclusive — `implementation/routes/buybacks.py:96-103,130-141`
- **§5** — insert (table row) — added missing `ERR_BUYBACK_CAP_EXCEEDED` row at **422 Unprocessable Entity** — `implementation/routes/buybacks.py:144`

Output file: `/home/ubuntu/github/CodingPRD/tasks/task_2023_electronic_component_distribution/workspace/PRD_COMPLETED.md`
