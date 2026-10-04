# HELPERS_MANIFEST — frozen Step 5a contract for Step 5b

Everything below is importable from the `test_helpers` package
(`from test_helpers import ...`). The package also re-exports the framework
generics: `validate_success`, `validate_error`, `validate_error_is_one_of`,
`validate_paginated`, `get_success_data`, `is_valid_uuid`,
`is_iso8601_timestamp`, `assert_cost_precision`, `assert_version_incremented`,
`assert_timestamp_format`, `assert_race_outcome`, `assert_exactly_one_succeeds`,
`assert_at_least_one_succeeds`, `run_race`, `build_user_headers`,
`NON_EXISTENT_UUID`.

Stage 2 must also create a `conftest.py` in its own output directory (sibling
of this package) exposing `api_client` as a session-scoped `api` fixture and
the three `TEST_USERS` entries as role-header fixtures.

## HTTP status contract (PRD §4)

- 201 on create: `POST /dealers`, `/end-users`, `/volume-agreements`,
  `/product-families`, `/configurations`, `/project-orders`,
  `/project-orders/{id}/phases`, `/install-windows`, `/punch-tickets`,
  `/warranty-claims`.
- 200 on everything else (reads, PATCHes, all action endpoints, clock set).
- Always pass the expected status explicitly: `validate_success(resp, 201)`
  for creates, `validate_success(resp, 200)` otherwise.

## Identity model (PRD §2.1) — MANDATORY

- `TEST_USERS["admin_headers"]` — ManufacturerAdmin, opaque id; canonical.
- `make_dealer_headers(dealer_id)` — REQUIRED for every DealerRep call that
  touches an owned resource. `TEST_USERS["dealer_headers"]` is an unbound
  fallback for non-ownership tests only (bad-payload 400s, role-denied 403s).
- `make_end_user_headers(end_user_id)` — same rule for EndUserRep.
- `make_admin_headers(user_id="test-admin-1")` — variant minting.
- In fixtures, `fixtures.ADMIN` is the shared admin header dict.

## ApiClient (`api_client` singleton; every method returns raw Response)

`create_dealer(payload, h)` · `update_dealer(dealer_id, payload, h)` ·
`create_end_user(payload, h)` · `create_volume_agreement(payload, h)` ·
`get_volume_agreement(agreement_id, h)` · `list_volume_agreements(h, params=None)` ·
`activate_volume_agreement(agreement_id, h)` ·
`create_product_family(payload, h)` · `update_product_family(family_id, payload, h)` ·
`create_configuration(payload, h)` · `get_configuration(configuration_id, h)` ·
`list_configurations(h, params=None)` ·
`lock_configuration(configuration_id, payload, h)` — payload key
`expected_configuration_version` ·
`revise_configuration(configuration_id, h)` ·
`get_configuration_bom(configuration_id, h)` ·
`create_project_order(payload, h)` · `get_project_order(order_id, h)` ·
`list_project_orders(h, params=None)` ·
`submit_project_order(order_id, payload, h)` — payload key
`expected_order_version` ·
`acknowledge_project_order(order_id, h)` ·
`cancel_project_order(order_id, payload, h)` — payload `{"reason": ...?}` ·
`create_phase(order_id, payload, h)` · `list_phases(order_id, h, params=None)` ·
`reserve_slot(phase_id, payload, h)` — `{plant_code, production_date}` ·
`start_install(phase_id, h)` · `complete_phase(phase_id, h)` ·
`create_install_window(payload, h)` · `list_install_windows(h, params=None)` ·
`get_install_window(window_id, h)` · `cancel_install_window(window_id, h)` ·
`create_punch_ticket(payload, h)` · `list_punch_tickets(h, params=None)` ·
`get_punch_ticket(ticket_id, h)` ·
`resolve_punch_ticket(ticket_id, payload, h)` — `{resolution_note}` ·
`verify_punch_ticket(ticket_id, payload, h)` — `{outcome: CONFIRMED|REJECTED}` ·
`create_warranty_claim(payload, h)` · `get_warranty_claim(claim_id, h)` ·
`list_warranty_claims(h, params=None)` ·
`review_warranty_claim(claim_id, payload, h)` — `{decision: APPROVE|DENY, review_note?}` ·
`set_clock(to_iso8601, h)`.

## Errors (`ApiErrorId`, `HTTP_STATUS_CODES`)

All 37 PRD §5 ids; map is registered with the framework at import, so
`validate_error(resp, ApiErrorId.ERR_X)` auto-checks the HTTP status.
401: UNAUTHENTICATED. 403: UNAUTHORIZED_ROLE, FORBIDDEN_OWNERSHIP.
400: VALIDATION, DATE_WINDOW_INVALID. 404: per-resource NOT_FOUND x10.
412: STALE_VERSION. 409: INVALID_STATE, INVALID_LIFECYCLE_TRANSITION,
DEALER_SUSPENDED, SPEC_NOT_LOCKED, ORDER_NOT_ACKNOWLEDGED, WINDOW_CONFLICT.
422: all remaining business errors.

## Constants (value → PRD.md line)

- `DEFAULT_CLOCK_UTC` "2026-09-01T00:00:00Z" → §2.4 (line 80)
- `MODULE_BOM_RULES` 5 module recipes → §2.7 (lines 98-102)
- `MODULE_CATEGORY` module→SYSTEMS/SEATING/STORAGE → §2.7 (line 96)
- `ALL_PART_NUMBERS` sorted valid part numbers (derived from §2.7)
- `FABRIC_LEAD_DELTA_DAYS` A0/B7/C14/COM21 → §2.7 (line 104)
- `FABRIC_UPCHARGE_PCT` A0/B5/C12/COM18 → §2.7 (line 104)
- `STORAGE_FABRIC_DELTA_DAYS` 0, `STORAGE_FABRIC_UPCHARGE_PCT` 0 → line 104
- `CAPABILITY_REQUIRED` SYSTEMS 3 / SEATING 1 / STORAGE 2 → §2.7 (line 106)
- `PLANT_DAILY_CAPACITY` GR 120 / DAL 80 → §2.8 (line 110)
- `TRANSIT_DAYS` GR 4 / DAL 6 → §2.8 (line 110)
- `PRODUCTION_NOTICE_DAYS` 2 → §2.8 (line 110)
- `QUEUE_SMALL_MAX_UNITS` 49, `QUEUE_MEDIUM_MAX_UNITS` 199,
  `QUEUE_DAYS_SMALL` 3, `QUEUE_DAYS_MEDIUM` 7, `QUEUE_DAYS_LARGE` 12 → §2.8 (line 110)
- `TIER2_MIN_CENTS` 25000000, `TIER3_MIN_CENTS` 75000000 → §3.2 (line 138)
- `PARTS_WARRANTY_DAYS` 1826, `LABOR_WARRANTY_DAYS` 366 → §3.8 (line 210)
- `MIN_PARTS_SUPPORT_DAYS` 2557 → §3.3 (line 144)
- `ESCALATION_BUSINESS_DAYS` 5 → §3.8 (line 202)
- `FREIGHT_TURN_BUFFER_MIN` 15, `ZONE_MAX_CREW` 10, `UNION_MIN_CREW` 4 → §2.8 (line 112)
- `PAGINATION_DEFAULT_LIMIT` 10, `PAGINATION_MIN_LIMIT` 1,
  `PAGINATION_MAX_LIMIT` 100, `PAGINATION_DEFAULT_OFFSET` 0 → §2.3 (line 76)

## Calculation helpers (pure functions)

- `bom_expand(modules) -> {"lines", "parts_total_cents", "total_units"}` —
  lines sorted by part_number with `part_number`, `total_qty`,
  `unit_list_price_cents`, `extended_cents`. NOTE: PN-WRK-SRF is 15800c in
  workstation recipes but 21500c in PRIVATE_OFFICE; extended_cents sums each
  contribution's own recipe price (352411 for 2x6X6+1xPRIVATE_OFFICE proves
  this), and `unit_list_price_cents` is None for such divergent parts.
  PRD pins `parts_total_cents`/`total_units` but NOT the per-line JSON key
  names — assert totals exactly; treat line-field names as advisory.
- `module_unit_parts_cents(module_type) -> int` (85837/104737/180737/66300/125000)
- `queue_days_for_units(total_units) -> 3|7|12`
- `configuration_lead_time(modules, base_lead_by_category) -> int` —
  e.g. `{"SYSTEMS": 42, "SEATING": 28, "STORAGE": 21}`.
- `tier_for_basis(basis_cents) -> 1|2|3`
- `price_order(modules, agreement, tier_basis_cents) -> dict` with
  `pre_discount_total_cents`, `tier`, `discount_pct`, `total_cents`.
  PROVISIONAL basis = agreement cumulative excluding this order; FINAL basis
  = cumulative + this order's pre-discount total.
- `add_calendar_days(date_iso, days) -> date_iso`
- `business_age_days(created_date_iso, clock_date_iso) -> int`
- `escalated_expected(status, created_date_iso, clock_date_iso) -> bool`

## Assertions

`assert_dealer`, `assert_end_user`, `assert_volume_agreement`,
`assert_product_family`, `assert_configuration`, `assert_project_order`,
`assert_installation_phase`, `assert_install_window`, `assert_punch_ticket`,
`assert_warranty_claim` — each takes the entity `data` dict and checks PRD
§2.5 common fields plus typed/enum fields. Nullable system fields are
type-checked only when non-null.
`assert_agreement_volume_invariant(agreement, orders)` — PRD §3.2 ledger rule.

## Factories (payload dicts; **overrides win)

`make_dealer_payload()` (territories MI/OH, level 4) ·
`make_end_user_payload()` ·
`make_volume_agreement_payload(end_user_id)` (2026-01-01..2027-12-31, .10/.15/.20) ·
`make_product_family_payload()` (auto-unique family_code; default SEATING base 28) ·
`make_module_entry(module_type="TASK_CHAIR_SET", fabric_grade=<A, or None for STORAGE_WALL>, qty=4)` ·
`make_configuration_payload()` ·
`make_project_order_payload(agreement_id, configuration_id)` (territory MI,
install 2026-12-15) ·
`make_submit_payload(expected_order_version)` ·
`make_lock_payload(expected_configuration_version)` ·
`make_phase_payload()` (floor 1, seq 1, zone Z1, 10 units) ·
`make_reserve_slot_payload()` (PLANT_GR, 2026-11-02) ·
`make_install_window_payload(phase_id)` (2026-12-01 09:00-12:00Z, non-union,
elevator, crew 4) ·
`make_punch_ticket_payload(phase_id)` (MINOR) · `make_resolve_payload()` ·
`make_verify_payload(outcome="CONFIRMED")` ·
`make_warranty_claim_payload(order_id, phase_id)` (LABOR) ·
`make_review_payload(decision="APPROVE", review_note=None)` ·
`make_cancel_payload(reason=None)` · `make_clock_payload(to_iso8601)`.

## Fixtures (fixtures.py)

Primitives return the parsed `data` dict and raise on failure with the
framework's setup-style message. Composites return a context dict.

- `set_logical_clock(api, to_iso8601=DEFAULT_CLOCK_UTC)`
- `create_dealer(api, **o)` / `update_dealer(api, dealer_id, **fields)` /
  `suspend_dealer(api, dealer_id)` (showroom false route) /
  `reinstate_dealer(api, dealer_id)`
- `create_end_user(api, **o)`
- `create_product_family(api, **o)` — one per category per test
- `advance_family(api, family_id, **fields)` — lifecycle PATCH
- `create_volume_agreement(api, end_user_id, **o)` / `activate_agreement(api, id)` /
  `create_and_activate_agreement(api, end_user_id=None, **o) -> (agreement, end_user)`
- `create_configuration(api, dealer_id, modules=None, **o)` /
  `lock_configuration(api, spec, dealer_id)` (sends spec["version"]) /
  `revise_configuration(api, spec, dealer_id)` /
  `create_and_lock_configuration(api, dealer_id, modules=None, **o)`
- `create_order(api, agreement_id, configuration_id, dealer_id, **o)` /
  `submit_order(api, order, dealer_id)` (sends order["version"]) /
  `acknowledge_order(api, order_id)` /
  `cancel_order(api, order_id, headers, reason=None)` /
  `get_order(api, order_id, headers)` / `get_agreement(api, agreement_id, headers=None)`
- `create_phase(api, order_id, dealer_id, **o)` /
  `reserve_slot(api, phase_id, dealer_id, plant_code="PLANT_GR", production_date="2026-11-02")` /
  `start_install(api, phase_id, dealer_id)` / `complete_phase(api, phase_id, dealer_id)` /
  `schedule_and_start_install(api, phase_id, dealer_id, plant_code, production_date)`
- `create_window(api, phase_id, dealer_id, **o)` / `cancel_window(api, window_id, dealer_id)`
- `file_punch(api, phase_id, headers, **o)` / `resolve_punch(api, ticket_id, dealer_id, resolution_note)` /
  `verify_punch(api, ticket_id, end_user_id, outcome)`
- `file_claim(api, order_id, phase_id, dealer_id, **o)` / `review_claim(api, claim_id, decision, review_note)`

Composites (all assume the clock is at the 2026-09-01 default unless you pass
explicit dates):

- `setup_dealer_world(api, territories=("MI","OH"), capability=4,
  family_specs=(("SEAT-2200","SEATING",28),), agreement_start, agreement_end,
  discounts=(0.10,0.15,0.20), activate=True)`
  → `{"dealer", "end_user", "agreement", "families": {category: family}}`
- `setup_locked_world(api, modules=None, **world)` → + `"configuration"` (LOCKED)
- `setup_submitted_order(api, modules=None, territory_code="MI",
  requested_install_date="2026-12-15", **world)` → + `"order"` (SUBMITTED)
- `setup_acknowledged_order(api, ...)` → order ACKNOWLEDGED, agreement re-read
- `setup_scheduled_phase(api, planned_units=10, plant_code="PLANT_GR",
  production_date="2026-11-02", floor_number=1, phase_sequence=1,
  building_zone_id="Z1", **order_kwargs)` → + `"phase"` (SCHEDULED)
- `setup_phase_in_progress(api, production_date=..., ...)` → clock advanced
  to production_date, phase DELIVERED/IN_PROGRESS
- `setup_completed_phase(api, complete_on=None, ...)` → phase COMPLETE
  (completion date = complete_on else production_date), order re-read
  (single-phase orders bubble to CLOSED)
- `acknowledge_chair_order(api, ctx, qty)` → one more ACKNOWLEDGED order of
  qty TASK_CHAIR_SET A (adds qty*125000c to cumulative volume)

## Clock-reachability notes

All factory/composite date defaults are reachable from the 2026-09-01 default
clock: install 2026-12-15 clears every lead time these families produce
(<= 59d); production 2026-11-02 clears notice (+2d) and transit (GR -4d).
`setup_phase_in_progress` moves the clock FORWARD to production_date; if your
test already moved the clock past that, pass a later production_date.
Warranty/punch tests complete phases at an explicit `complete_on` date and
then advance the clock to the boundary under test (helpers:
`add_calendar_days`, `business_age_days`).

## Known upstream quirk

The corner index's parts-support instance says in prose "warranty still valid
until 2036-10-06" for a phase completed 2031-10-06; exact arithmetic (leap
days 2032 and 2036 inside the span) gives 2036-10-05. The instance's asserted
behavior (claim at 2033-10-06 rejected ERR_PARTS_SUPPORT_EXPIRED while the
parts warranty window is still open) is unaffected — both dates are far past
2033-10-06. `add_calendar_days` is authoritative.
