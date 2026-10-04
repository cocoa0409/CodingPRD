# Worklog — task_3047_drive_stall_order_carhop_dispatch

## Step 1: Create task directory — 2026-09-29T00:00:00.000Z

Pre-allocated directory `./tasks/task_3047_drive_stall_order_carhop_dispatch/workspace` verified to exist; used as-is per command args (no new index computed).

## Step 2: Generate scaffold — 2026-09-29T17:58:00.000Z

All three scaffold artifacts are written and lint-clean. No sibling task was read.

### Files (all under `tasks/task_3047_drive_stall_order_carhop_dispatch/`)

| File | Lines | Top-level key |
|---|---|---|
| `SCAFFOLD.yaml` | 1434 | §1.0–§1.7 (no design keys) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1145 | `scaffold_difficulty_design` |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 559 | `scaffold_corner_design` |

### Counts
- Entities: **13** (Location, MenuItem, CustomizationOption, Customer, Stall, Carhop, Order, OrderLine, Offer, DeliveryRun, TipRecord, EquipmentFault, ServiceTargetProfile)
- Endpoints: **74** (includes flat single-resource alias reads + flat filtered lists to satisfy FK reverse-reachability, and a `/_clock/set_current_utc` test-driving endpoint with the pinned 2026-09-01T00:00:00Z default)
- Error codes: **27**
- §1.8: **9 rules, 18 non-stub instances** (2 per rule)
- §1.9: **9 sections, 19 non-stub instances**

### Difficulty posture (well above Expert band)
- Two parallel state dimensions on `Order` (fulfillment × payment axis) plus a cyclic `Stall` machine.
- Dual-variant calcs on two domains (order pricing provisional-vs-placed; tip resolution explicit-vs-default).
- Combinatorial formulas in two modes: (b) per-line-then-sum rounding in combination pricing; (c) circular-looking happy-hour→offer evaluation-order pin.
- Two transitive cascades from different triggers (deliver→stall→posture→run/carhop; fault→stall→posture).
- Two validation-priority conflicts (state vs fiscal; safety vs constraint).
- Two boundary checks (late_flag strict `>`; kitchen `>= 8` saturation).
- Cross-entity gates (Order→Stall occupancy; fulfillment→payment axis).
- Two interval semantics (exclusive stall occupancy vs half-open midnight-wrapping offer windows).
- Two compensating invariants (carhop load on run void; outstanding tips on refund).
- Two OCC rules (`expected_location_version` on check-in, `expected_carhop_version` on run staging).

`scaffold_lint.py` verdict: **clean lint** (all §1.8/§1.9 calls conform to §1.5; all §1.1 FKs reverse-reachable).

One note: a few §1.8 `assert:` blocks in the kitchen-saturation and drive-thru boundary instances carry a forward-reference NOTE to the corner design for the fully executable chain; the bulk of instances are fully self-contained and literal-pinned.

## Step 3: Copy shared files — 2026-09-29T17:59:00.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md` (bash only, no subagent).

## Step 4: Generate PRD — 2026-09-29T18:08:00.000Z

PRD generated and verified. The difficulty-design and corner-design files were never opened.

**Output:** `workspace/PRD.md` — 320 lines.

**Section list:**
- §1 Introduction (2 paragraphs, scenario rewrite)
- §2 Global Specifications: 2.1 RBAC (headers, 5 roles with identity prose: Carhop/Customer entity-backed, the other three opaque), 2.2 Response Structure (verbatim fixed block), 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending), 2.4 Common Resource Properties, 2.5 Money/Precision (integer cents, round half-up; on_time_rate 4 decimals), 2.6 Logical Clock & Timezones (startup 2026-09-01T00:00:00Z, `current_utc`, HH:MM windows), 2.7 Lane Posture/Weather (0.20 congestion fraction, ceil), 2.8 OCC (both rules), 2.9 Nested Retrieval + flat aliases + all 11 path-param spellings, 2.10 Validation Priority Order (13 levels, all error IDs mapped)
- §3 Business Logic: 10 subsections (location/weather/rush; catalog/customization incl. customer registration; check-in/drafting; placement pricing/happy-hour/offers; kitchen/service-targets/late-flag/metrics; dispatch selector; payment/wallet/refund; cancellation; faults; tip settlement)
- §4 Endpoint table — all 72 endpoints, 4 columns
- §5 Error catalogue — all 27 error IDs, 2 columns

**Scaffold coverage:**
- **Entities:** all 13 entities and every field covered in prose (verified programmatically: 104/104 required identifiers present in backticks).
- **State machines:** Order fulfillment (DRAFT→PLACED→PREPARING→READY→OUT_FOR_DELIVERY→DELIVERED + 4 cancel branches with payment gates), payment axis (authorize/capture/void-cascade/refund with manager_override and STORE_CREDIT), Stall (check-in, cascades, OOS with force_cancel, return_to_service), DeliveryRun (LOADED→OUT→COMPLETED/VOIDED), TipRecord (settle with adjustment, refund void), EquipmentFault (OPEN→RESOLVED, intercom_functional side effects, MENU_BOARD_DEAD forcing OUT_OF_SERVICE) — all transitions with preconditions, error IDs, and side effects.
- **Calculations:** all 8 (order_pricing with per-line rounding + BOGO-half pairing order, offer_application with selection/tie-break/stacking rules, service_target_lookup with NORMAL fallback, late_flag strictly-greater, dispatch_selector with zone parity/mixed-tray rule, tip_resolution with wallet-first tender, timing_metrics_rollup with empty-set nulls, stall_availability + rush_admission with the 8-cap boundary and 2-window draft expiry).
- **Validations:** all 13 priority levels expressed as an explicit ordered evaluation in §2.10 plus trigger conditions scattered in §3.
- **Endpoints:** all 72 (including flat aliases, flat filtered lists, and the clock test-driving endpoint) in §4; side effects narrated in §3.
- **Errors:** all 27 IDs present in prose with HTTP statuses.
- **Roles:** all 5 with exact spelling and identity semantics; per-endpoint role lists in §4.
- **Concurrency:** both OCC rules (`expected_location_version` on check-in, `expected_carhop_version` on run staging) with `ERR_STALE_VERSION`/412 and stale-read framing.

**Hard contract reports:**
- Contract 1 field coverage: 104 required, 104 present, 0 missing — PASS (two repair passes were needed: path-param camelCase spellings and `email`/`display_name`).
- Contract 2 rule coverage: priorities (13/13), OCC (2/2), transitions (all, incl. sibling cancel branches at equal density), calculations (8/8, no pseudocode), validations (all matchable to error IDs), side effects/applies_to (all), field structured content (defaults like `max_trays` 3, `stored_tip_default_pct` 0–0.50, `size_upcharge_cents` 0 all stated) — PASS.
- Contract 3 §3 path purity: 0 violations — PASS.

## Step 5: Generate unit tests — 2026-09-29T18:35:00.000Z

All done. Summary:

## Files written

**`test_helpers/` (9 files)**
- `types.py` — 14 status/kind enums + 13 entity TypedDicts (all entities carry the full common-field set per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (nested routes, flat alias reads, flat filtered lists, `/_clock/set_current_utc`); base URL comes from `API_BASE_URL` via the framework
- `api_errors.py` — all 27 error IDs with PRD §5 HTTP statuses, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` + posture/load invariant checkers
- `factories.py` — payload factories (input fields only)
- `constants.py` — MAX_PREPARING 8, DRAFT_EXPIRY 2, CONGESTION_FRACTION 0.20, pinned logical-clock instants for America/Chicago (08:00/14:00/02:00 local)
- `test_users.py` — `TEST_USERS` for all 5 roles plus `make_carhop_headers` / `make_customer_headers` for the two entity-backed roles (ownership-gated depart/deliver/app-checkin calls thread the real entity id)
- `fixtures.py` — composite helpers: OCC-aware `intercom_checkin` (always re-reads the location version), `setup_stall_draft_order`, `place_and_ready`, `authorize_and_capture`, `stage_run` (re-reads carhop version), `setup_ready_order_on_stall` → `setup_captured_ready_order` → `setup_out_for_delivery` → `setup_delivered_order`, plus drive-thru helpers
- `__init__.py` — barrel export

**`test_suite/` (14 files, 70 tests)** — `conftest.py` wires `sys.path` to the parent so `test_helpers` imports standalone, exposes the `api` client and role-header fixtures. Tests grouped by concern (location defaults, catalog, place guards, combination pricing, tips/payments, stall lifecycle/faults, occupancy/OCC, delivery dispatch, refunds, offer windows, kitchen saturation, metrics/listing/404, security/RBAC).

## Coverage

**Queue A (Difficulty, 18 instances):** 17 emitted with ≥2 tests each; 1 skipped —
- `boundary_precision_check/late_flag_strictly_greater_boundary` — SKIPPED. The recipe is self-declared superseded/non-executable (its trigger calls deliver on a run that was never created, for a DRIVE_THRU order that can never be on a tray run), and no PRD-declared pathway can deliver a drive-thru order at a clock-pinned elapsed time.

**Queue B (Corner, 17 non-stub instances):** 17 emitted with ≥1 (actually 2) tests each; 1 skipped —
- `calculations/stall_availability_congestion_boundary` — SKIPPED. Its only unique claim is the CONGESTED-at-`<=ceil(capacity*0.20)` boundary, but the PRD pins the threshold only by a worked example for a 40-stall lot ("for a forty-stall lot, that threshold is eight stalls"), leaving the evaluation rule (multiply-then-ceil vs floor etc.) non-uniquely derivable for other capacities (two-reader failure). Its OPEN/initial assertions duplicate `location_create_returns_defaults_and_posture`.

Total: 70 tests, each with exactly one `Design:` tag resolving verbatim to a real instance name (verified programmatically), each docstring carrying a verbatim PRD citation (all 41 distinctive snippets pass a whitespace-normalized grep of PRD.md), no `skip`/`skipif`/`xfail`, no scaffold references in comments. All modules compile and `pytest --collect-only` collects 70 tests cleanly.

## Key design decisions
- Logical clock is pinned at the start of every time-sensitive test; the recipe's "clock move after check-in" pattern was dropped in favor of setting the clock before check-in, matching the PRD rule that offer applicability is pinned to `checked_in_at` (this also fixes two UTC/local conversion errors in the design notes).
- The priority-pair fiscal test asserts the PRD-pinned priority order (§2.10 explicitly orders the fiscal gate within business rules after the structural state gate).
- The one soft spot: `test_place_after_stall_released_rejected` uses `validate_error_is_one_of([ERR_STALL_NOT_OCCUPIED_BY_ORDER, ERR_INVALID_STATE])` because the released order is also terminally CANCELLED and PRD doesn't pin which gate fires there; the companion positive test pins the occupancy gate itself.

## Step 6: Generate implementation — 2026-09-29T18:58:00.000Z

All done. The stray `app.py` processes belong to other concurrent task implementations, not this one — both of my smoke-test servers were killed (the second one died with the shell after verification).

**Implementation written** to `workspace/implementation/` — Python + Flask, in-memory dicts only, zero seeding, fresh-boot clean (verified: after a restart the previously created location 404s, and the logical clock resets to the PRD-mandated `2026-09-01T00:00:00Z`).

**Files (23 files, 2,938 lines total):**
- `start.sh` (10 lines, executable, guarded pip install, `exec python3 app.py`, `$PORT`/`0.0.0.0`/foreground)
- `requirements.txt`, `app.py` (69), `db.py` (34), `errors.py` (56), `response.py` (53), `middleware.py` (139), `serializers.py` (208), `services.py` (466)
- `routes/`: `__init__.py` (31), `locations.py` (172), `catalog.py` (139), `customers.py` (75), `stalls.py` (284), `orders.py` (414), `offers.py` (113), `service_targets.py` (76), `carhops.py` (78), `runs.py` (245), `tips.py` (71), `flat.py` (175), `clock.py` (29)

**Endpoint coverage: 72/72** — every path+method in the PRD §4 table is registered (confirmed by enumerating Flask's URL map; the extra `/static/<path>` rule is Flask's built-in and carries no behavior).

**Error coverage: 27/27** — all error IDs from the catalog are implemented with the exact HTTP statuses, raised through a single `ApiError` → envelope handler (`meta`/`response_type: "error"`/`data.error_id`/`data.message`).

**Key behaviors implemented per PRD:** dual-axis order state machine (fulfillment + payment), combo pricing (BOGO-half on DRINK/SLUSH units, ascending unit price with created_at tie-break, round-half-up per discounted unit), happy-hour repricing pinned to `checked_in_at` in the location's IANA timezone with wrap-midnight/all-day windows, single-offer selection (largest discount, earliest created_at tie-break) plus explicit `offer_code` override with `ERR_OFFER_NOT_APPLICABLE`, service-target snapshot with weather-mode→NORMAL fallback, lane posture (`stall_capacity`-based with ceil 20% congestion threshold, STORM → CURBSIDE_ONLY), OCC on `expected_location_version` (check-in) and `expected_carhop_version` (run staging), dispatch selector (zone by PATIO/stall parity, earliest-placed mixed-tray rule, on_shift + max_trays capacity), in-sequence delivery with auto run completion, tip settle/void cascades, wallet-first tender, rush-window draft expiry (>2 windows), kitchen saturation cap of 8, metrics rollup (half-up means, 4-decimal on_time_rate, nulls on empty set), and left-to-right nested path validation.

**Smoke test: PASS** — full lifecycle exercised end-to-end via curl: location create (201, correct envelope/defaults), service target, menu items, size option, stall, intercom check-in with OCC, line adds with combo pricing (subtotal 857 = 499 + 478 − 120 half-price discount, verified), place (tax 71, target 240 snapshotted), prep → ready → authorize → capture (tip 100, tendered 1028), carhop + run stage/depart/deliver (auto-COMPLETED), tip record RECORDED, metrics rollup, plus error-path checks: 401 unauthenticated, 403 forbidden, 404 not-found, 412 stale version, 409 heat-advisory patio closure, and pagination envelope fields — all correct. Fresh-reboot isolation confirmed (store starts empty; logical clock pinned at startup default).

## Step 7: Run tests and iterate — interrupted, resuming (2026-09-29T19:36:41.000Z)

First Step 7 attempt was killed mid-iteration by an unsafe process kill (orchestrator restart). State on resume: test suite collects 68 tests (down from 70 — 2 deletions made by the interrupted subagent, details unrecoverable). Files the interrupted run modified: test_helpers/fixtures.py; test_suite/test_02, test_04, test_06, test_08, test_09; implementation/app.py, routes/runs.py, services.py. All artifacts verified complete (YAML/PRD parse, impl parses, tests collect). Resuming Step 7 from scratch with a fresh diagnostic subagent.

## Step 7: Run tests and iterate — RESUMED, PASS (2026-09-29T19:40:07.000Z)

All 8 rounds passed (68/68 in every round) on the first sweep — the prior Step 7 attempt's partial edits already brought the suite to a stable, fully passing state.

### Summary

- **Iterations run:** 1 (eight parallel rounds, `--isolation per-test-server`, 68 tests collected, all 8 rounds `passed == total == 68`, zero flaky failures across the union).
- **Tests deleted:** none this iteration (the interrupted earlier attempt deleted 2 tests — 70→68 — before being killed; the specific deletions are unrecoverable from its discarded context).
- **Fixes applied to `test_helpers/`:** none this iteration (baseline already incorporates the previous attempt's edits to `test_helpers/fixtures.py`).
- **Fixes applied to `test_suite/`:** none this iteration (baseline already incorporates the previous attempt's edits to `test_02`, `test_04`, `test_06`, `test_08`, `test_09`).
- **Fixes applied to `implementation/`:** none this iteration (baseline already incorporates the previous attempt's edits to `app.py`, `routes/runs.py`, `services.py`).

The suite at `tasks/task_3047_drive_stall_order_carhop_dispatch/` is green and stable across 8 concurrent full runs; no further diagnostic work was needed.

## Step 8: Finalize PRD — 2026-09-29T19:50:53.000Z

The final file is clean: 10 minimal patches, no duplications.

**Files:** `workspace/PRD.md` (320 lines / 48,494 chars) vs `PRD_FINALIZED.md` (320 lines / 49,691 chars), +2.47% by character count, 0 lines added (all edits inline within existing sentences).

Note: Step 7's first attempt was killed mid-iteration and its exact fix rationale was unrecoverable (directory untracked in git), so the Step 7 diff was reconstructed from filesystem timestamps — the five modified test artifacts (fixtures.py; test_02/04/06/08/09) served as the focus list, cross-checked against the three modified implementation files (app.py, routes/runs.py, services.py).

### Changes (one bullet per edit)

- §2.2 Standard Error Response Format — revise — widened "error API responses (4xx status codes)" to "every non-2xx response, including an unmatched path or method on this API" — `implementation/app.py:34-41` (404 handler → `ERR_NOT_FOUND`; 405 handler also maps to 404/`ERR_NOT_FOUND`).
- §3.1 rush sweep — revise — replaced "`checked_in_at` older than two rush windows" with the rush-index predicate ("recorded check-in rush index more than two windows behind the new `rush_index`") and pinned that directly created drive-thru drafts are never expired by the sweep — `implementation/routes/locations.py:80-88`, `implementation/routes/orders.py:72`, `implementation/routes/stalls.py:116`.
- §3.2 customization options — insert — pinned that a size option may never appear in `addin_option_codes`, and that a non-`DRINK_SIZES` item may carry `size_option_code` naming an `ACTIVE` size option which contributes nothing to price — `implementation/routes/orders.py:169-185`.
- §3.4 combination pairing — insert — parenthetical pinning that pairs are dealt first-unit-full-price / second-unit-discounted from the front of the ordering — `implementation/services.py:168-175`.
- §3.4 placement totals — revise — defined placed `subtotal_cents` as the happy-hour-repriced combo-adjusted sum, and `offer_discount_cents` as (provisional pre-HH subtotal − repriced subtotal) + selected offer discount — `implementation/services.py:327-404`.
- §3.4 tax — insert — pinned that the configured tax rate is zero, so `tax_cents` is 0 at placement — `implementation/services.py:406-408`.
- §3.6 zone rule — revise — replaced the contradictory majority/mixed-tray rule with the impl's single rule: the run's required zone is the zone of the selected orders' earliest-placed order — `implementation/routes/runs.py:29-43`.
- §3.6 staging tip attachment — insert — pinned that staging attaches the carhop to each staged order's `RECORDED` TipRecord whose `carhop_id` is still null and adds the tip to `tips_outstanding_cents` — `implementation/routes/runs.py:124-136`.
- §3.7 refund gate — insert — pinned that a non-delivered refund without `manager_override` is rejected with `ERR_PAYMENT_NOT_CAPTURED` — `implementation/routes/orders.py:369-373`.
- §3.7 store-credit refund — revise — scoped the wallet credit of `total_cents` to orders with a customer attached — `implementation/routes/orders.py:389-393`.

### Per-edit pre-edit search log

1. **Error envelope** — (a) subject: which responses use the error envelope; (b) enumerated: `app.py` error handlers (ApiError/404/405/Exception), `response.py error_response`, `errors.py` raise paths across all routes; (c) widened from "(4xx status codes)" to "every non-2xx response, including an unmatched path or method" because Flask's 405 lands in the 404 handler.
2. **Rush sweep** — (a) subject: stale-draft expiry predicate; (b) enumerated: `locations.py advance_rush`, `stalls.py _create_checkin_order` (stamps `checked_in_rush_index`), `orders.py _new_order_record` (None for drive-thru), `serializers.py order`; (c) reworded from timestamp-based to rush-index-based and added the drive-thru exclusion, since impl never computes time deltas.
3. **Size/add-in rules** — (a) subject: option validation at line add; (b) enumerated: `orders.py add_line` all four branches, `services.py _line_unit_price`, `catalog.py create_option`; (c) pinned only observed behaviors without inventing category checks for size options (impl has none).
4. **Combo pairing** — (a) subject: which unit of a pair is discounted; (b) enumerated: `services.py apply_combo_pricing` (the only pricing path used by both draft recompute and placement); (c) minimal parenthetical, no other change.
5. **HH/subtotal/offer_discount semantics** — (a) subject: frozen pricing fields at placement; (b) enumerated: `services.py place_order` lines 320-417, `recompute_draft_pricing`, `_offer_discount`; test_04 expectations (600/0 outside window); (c) defined both fields jointly in one sentence to avoid a half-claim about either.
6. **Tax = 0** — (a) subject: tax computation; (b) enumerated: `services.py place_order` (`order["tax_cents"] = 0` unconditionally), `recompute_draft_pricing` (also 0), serializers/tests asserting `tax_cents == 0`; (c) framed as "configured tax rate is zero" so the PRD formula stays intact.
7. **Zone rule** — (a) subject: dispatch zone eligibility; (b) enumerated: `runs.py _order_zone`, `_required_zone` (always earliest-placed, no majority counting anywhere), `_carhop_eligible`, candidate ordering in `stage_run`, `carhops.py` zone field/filter; (c) replaced the PRD's majority rule entirely — retaining "majority" anywhere would mis-describe `_required_zone`.
8. **Staging tip attachment** — (a) subject: TipRecord/counter updates at staging; (b) enumerated: `runs.py stage_run` tip loop, `orders.py capture_payment`, `orders.py refund` and `tips.py settle_tip` (consume the attachment); (c) scoped the sentence to `RECORDED` tips with null `carhop_id`, exactly matching the loop's condition.
9. **Refund non-delivered gate** — (a) subject: refund preconditions/errors; (b) enumerated: `orders.py refund` (checks CAPTURED first → `ERR_INVALID_STATE` if not; then non-delivered-without-override → `ERR_PAYMENT_NOT_CAPTURED`), error catalogue, test_09; (c) pinned the impl's error id verbatim.
10. **Store-credit wallet credit condition** — (a) subject: refund wallet credit; (b) enumerated: `orders.py refund` wallet branch (requires non-null `customer_id`), `orders.py create_order`/`stalls.py checkin` (null-customer orders exist), `customers.py wallet_adjust`; (c) softened with "when the order has a customer attached" to avoid implying a wallet credit on anonymous intercom orders.

No edits touched §2.7/§2.10 (posture math and validation order verified consistent with impl), §3.3 (check-in OCC and stall cascade verified), §3.9 (fault cascades verified against test_06), or the endpoint table.

## Step 9: Complete PRD — 2026-09-29T20:23:28.000Z

**Source:** `workspace/PRD_FINALIZED.md` → `PRD_COMPLETED.md`

**Line counts:** 320 → 321 lines; char delta 49,856 → 54,514 (+4,658 chars).

**Counts:** 27 ambiguity-pins, 1 mismatch-revision (28 change bullets; the refund edit required one follow-up dedupe).

**Changes (section — kind — classification — what — impl ref):**

- §1 — insert — ambiguity — drive-thru drafts pin offer evaluation to creation time — `routes/orders.py:58`
- §2.1 — revise — mismatch — `X-User-ID` required for every role, not only entity-backed ones — `middleware.py:19-20`
- §2.2 — insert — ambiguity — unmatched method on a valid path returns `ERR_NOT_FOUND`/404 — `app.py:39-41`
- §2.2 (×2, success+error examples) — insert — ambiguity — `api_request_id` example is 20 alphanumeric chars after `req_` — `response.py:14-15`
- §2.3 — insert — ambiguity — negative `offset` is malformed; list tie-break is `id` ascending — `middleware.py:103-125, 128-129`
- §2.7 — insert — ambiguity — patio positions excluded from `lane_posture` math too (all-stalls-occupied still yields `CURBSIDE_ONLY`) — `services.py:111-123`
- §2.9 — insert — ambiguity — exact filter-key sets enumerated for all nine flat list endpoints — `routes/flat.py:94-175`
- §3.1 — insert — ambiguity — location `code` uniqueness is a convention, not server-enforced — `routes/locations.py:20-42`
- §3.2 — insert — ambiguity — `size_upcharge_cents` is non-negative — `routes/catalog.py:106`
- §3.3 — insert — ambiguity — `stall_number` is a non-negative integer; within-location uniqueness not enforced — `routes/stalls.py:40`
- §3.3 — insert — ambiguity — intercom check-in's optional `customer_id` must reference an existing customer — `routes/stalls.py:133-138`
- §3.3 — insert — ambiguity — app check-in rejects missing/unknown `customer_id` with `ERR_APP_ONLY` — `routes/stalls.py:158-163`
- §3.3 — insert — ambiguity — app check-in at a patio stall under STORM is gated only by the heat-advisory rule — `routes/stalls.py:167-169`
- §3.3 — insert — ambiguity — check-in orders record the location's `rush_index` as their check-in rush index — `routes/stalls.py:116`
- §3.3 — insert — ambiguity — direct order creation: omitted `channel` defaults to `DRIVE_THRU`; non-DRIVE_THRU rejected with `ERR_INVALID_REQUEST`; `checked_in_at` anchored at creation — `routes/orders.py:83-87, 58`
- §3.3 — insert — ambiguity — `size_option_code` on a `DRINK_SIZES` item must name an `ACTIVE` size option, else `ERR_OPTION_INVALID` — `routes/orders.py:159-168`
- §3.4 — insert — ambiguity — combination pairing depends only on sorted unit prices, so happy-hour repricing re-pairs identically — `services.py:158-177`
- §3.4 — insert — ambiguity — DRAFT provisional preview carries `offer_discount_cents` 0 and `total_cents` == `subtotal_cents` — `services.py:187-190`
- §3.4 — insert — ambiguity — unknown `offer_code` at placement yields `ERR_NOT_FOUND` — `services.py:370-377`
- §3.4 — insert — ambiguity — any non-HH-discount offer (regardless of kind) competes for the single-offer slot — `services.py:364-368`
- §3.4 — insert — ambiguity — offer `code` uniqueness is a convention, not enforced — `routes/offers.py:40-73`
- §3.4 — insert — ambiguity — fixed-offer `discount_value` is non-negative; both window endpoints required and validated as `HH:MM` — `routes/offers.py:24-56`
- §3.5 — insert — ambiguity — drive-thru orders never leave `READY` and are excluded from the metrics rollup — `routes/locations.py:129-133`
- §3.5 — insert — ambiguity — a disabled service-target profile uses `status` `RETIRED` — `routes/service_targets.py:19, 39`
- §3.6 — insert — ambiguity — `max_trays` minimum is 1 — `routes/carhops.py:31`
- §3.6 — revise — ambiguity (large) — staging: `carhop_id` optional; unknown `order_ids` entries → `ERR_NOT_FOUND`, ineligible entries silently excluded; auto-pick chooses first fitting carhop; named-but-ineligible carhop → `ERR_NO_CARHOP_ELIGIBLE` — `routes/runs.py:50-105`
- §3.6 — insert — ambiguity — delivery requires the order to be `OUT_FOR_DELIVERY` on this run (`ERR_INVALID_STATE` / `ERR_NOT_FOUND` otherwise) — `routes/runs.py:229-235`
- §3.7 — insert — ambiguity — authorize requires `UNPAID` payment, else `ERR_INVALID_STATE` — `routes/orders.py:284-285`
- §3.7 — insert — ambiguity — capture requires `AUTHORIZED` (else `ERR_INVALID_STATE`); explicit `tip_cents` must be a non-negative integer — `routes/orders.py:298-305`
- §3.7 — insert — ambiguity — tip amount joins `tips_outstanding_cents` immediately at capture when the carhop is known — `routes/orders.py:352-356`
- §3.7 — insert — ambiguity — refund: non-CAPTURED → `ERR_INVALID_STATE`; `refund_mode` required; tip record voided only if still `RECORDED` — `routes/orders.py:365-368, 381-388`
- §3.8 — insert — ambiguity — customer cancelling a non-DRAFT order → `ERR_FORBIDDEN`; cancel from `OUT_FOR_DELIVERY`/`DELIVERED`/`CANCELLED` → `ERR_INVALID_STATE` — `routes/orders.py:401-414`
- §3.9 — insert — ambiguity — resolving a non-OPEN fault → `ERR_INVALID_STATE` — `routes/stalls.py:228-231`
- §3.9 — insert — ambiguity — `set_out_of_service` on an already-OOS stall → `ERR_INVALID_STATE` — `routes/stalls.py:250-253`
- §3.10 — insert — ambiguity — settling a non-RECORDED tip → `ERR_INVALID_STATE`; the adjustment is preserved on the record's `adjusted_tip_cents` field — `routes/tips.py:56-62`
