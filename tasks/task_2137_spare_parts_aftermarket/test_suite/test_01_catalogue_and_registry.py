"""Part catalogue, installed-base registry, applicability map and common
resource properties."""

import pytest

from test_helpers import (
    ApiErrorId, CLOCK_DEFAULT_UTC, UNKNOWN_UUIDS, api_client,
    assert_equipment_model, assert_installed_unit, assert_ledger_entry,
    assert_part, assert_part_applicability, create_applicability, create_dealer,
    create_equipment_model, create_installed_unit, create_part,
    create_part_payload, create_dealer_payload, create_installed_unit_payload,
    create_part_line_payload, is_iso8601_timestamp, is_valid_uuid, list_ledger,
    read_applicability, read_part, receive_stock, set_clock,
    setup_catalogue, TEST_USERS, validate_error, validate_paginated,
    validate_success,
)

PLANNER = TEST_USERS["planner_headers"]
CONTROLLER = TEST_USERS["controller_headers"]
ADMIN = TEST_USERS["admin_headers"]


def test_part_create_returns_derived_defaults(api):
    """PRD 3.2: "Everything else about a newly registered part is derived. Its
    `lifecycle_state` is `ACTIVE` and its `superseded_by_part_id` is null — that
    self-referential successor pointer is non-null only while the part sits in
    `SUPERSEDED`. Its `criticality_score` is 0, its `criticality_class` is
    `DESIRABLE`, its `stocking_policy` is `MAKE_TO_ORDER`, and both
    `safety_stock_units` and `reorder_point_units` are 0. All four stock counters —
    `on_hand_units`, `allocated_units`, `quarantine_units` and `in_transit_units` —
    start at 0, `available_units` is therefore 0, and `replenishment_status` reads
    `NORMAL`."
    PRD 3.2: "The two catalogue price fields, `current_effective_uplift_pct` and
    `current_list_unit_price_cents`, are computed immediately when an active price
    rule for the `DESIRABLE` band exists; when no such rule has been published yet,
    both simply stay at 0 and registration still succeeds."
    PRD 2.5: "Every persisted resource carries an `id`, which is a server-minted
    UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC format
    with three fractional digits."

    Design: Corner/entities/part_create_returns_system_and_default_fields
    """
    resp = api.create_part(create_part_payload(
        part_number="CRN-1", description="Corner probe part",
        unit_cost_cents=2500, lead_time_days=14, weight_kg=0.5), PLANNER)
    created = validate_success(resp, 201)
    part = read_part(created["id"])
    assert_part(part)

    assert part["lifecycle_state"] == "ACTIVE"
    assert part["superseded_by_part_id"] is None
    assert part["criticality_class"] == "DESIRABLE"
    assert part["criticality_score"] == 0
    assert part["stocking_policy"] == "MAKE_TO_ORDER"
    assert part["safety_stock_units"] == 0 and part["reorder_point_units"] == 0
    assert part["hazmat"] is False, "hazmat defaults to false"
    assert part["max_stock_units"] == 0, "max_stock_units defaults to 0"
    assert part["on_hand_units"] == 0
    assert part["allocated_units"] == 0
    assert part["quarantine_units"] == 0
    assert part["in_transit_units"] == 0
    assert part["available_units"] == 0
    assert part["replenishment_status"] == "NORMAL"
    assert part["current_list_unit_price_cents"] == 0, \
        "no active DESIRABLE rule exists yet, so the catalogue price stays 0"
    assert part["version"] == 1
    assert is_valid_uuid(part["id"]) and "_" not in part["id"]


def test_parts_list_pagination_reports_total_count_and_has_more(api):
    """PRD 2.3: "Every collection-returning read accepts two optional query
    parameters. `limit` controls page size: it defaults to 10, may not be smaller
    than 1, and may not be larger than 100. `offset` controls the starting
    position: it defaults to 0 and may not be negative."
    PRD 2.3: "For every list response the `meta` object carries `limit` (the
    effective page size applied), `offset` (the effective starting position
    applied), `total_count` (the number of records matching the filter before
    pagination is applied), and `has_more` (true when records remain beyond the
    current page)."

    Design: Corner/entities/parts_list_paginates_with_total_count_and_has_more
    """
    for i in (1, 2, 3):
        create_part(part_number=f"PG-{i}", description=f"Page part {i}",
                    unit_cost_cents=100 * i, lead_time_days=5, weight_kg=0.1)

    first, meta_first = validate_paginated(
        api.list_parts(PLANNER, params={"limit": 2, "offset": 0}))
    assert len(first) == 2, f"expected 2 rows on the first page, got {len(first)}"
    assert meta_first["total_count"] == 3
    assert meta_first["has_more"] is True
    assert meta_first["limit"] == 2
    assert meta_first["offset"] == 0
    assert api.list_parts(PLANNER, params={"limit": 2, "offset": 0}).json()[
        "response_type"] == "array"

    second, meta_second = validate_paginated(
        api.list_parts(PLANNER, params={"limit": 2, "offset": 2}))
    assert len(second) == 1, f"expected 1 row on the second page, got {len(second)}"
    assert meta_second["total_count"] == 3
    assert meta_second["has_more"] is False


def test_get_part_with_unknown_id_returns_part_not_found(api):
    """PRD 2.5: "Each resource family has its own not-found code, all carrying HTTP
    404: `ERR_PART_NOT_FOUND`, `ERR_MODEL_NOT_FOUND`, `ERR_INSTALLED_UNIT_NOT_FOUND`,
    `ERR_DEALER_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, `ERR_PART_LINE_NOT_FOUND`,
    `ERR_CAMPAIGN_NOT_FOUND`, `ERR_ALLOCATION_REQUEST_NOT_FOUND`,
    `ERR_REPLENISHMENT_ORDER_NOT_FOUND`, `ERR_RETURN_NOT_FOUND` and
    `ERR_APPLICABILITY_NOT_FOUND`."

    Design: Corner/entities/part_get_with_unknown_uuid_returns_part_not_found
    """
    create_part(part_number="NF-1", description="Not found probe",
                unit_cost_cents=100, lead_time_days=5, weight_kg=0.1)

    resp = api.get_part(UNKNOWN_UUIDS["part"], PLANNER)
    validate_error(resp, ApiErrorId.ERR_PART_NOT_FOUND.value)
    assert resp.json()["response_type"] == "error"


def test_part_create_without_unit_cost_is_rejected(api):
    """PRD 2.10: "The request body satisfies the endpoint's input schema: required
    fields present, enum members recognised, and integers inside their declared
    bounds — every quantity at least 1, `coverage_years` between 1 and 15 inclusive,
    `horizon_months` one of 12, 24 or 60, and `limit` between 1 and 100 inclusive.
    Otherwise `ERR_INVALID_REQUEST` (400). Applies to every endpoint."
    PRD 3.2: "An `AftermarketPlanner` registers a spare part with its OEM
    `part_number`, which must be unique across the catalogue, a human-readable
    `description`, a `unit_cost_cents` landed acquisition cost of at least 1 cent, a
    `lead_time_days` standard non-air replenishment lead time of zero days or more,
    and a `weight_kg` shipping weight per unit that must be strictly greater than
    zero."

    Design: Corner/entities/part_create_missing_required_unit_cost_returns_invalid_request
    """
    resp = api.create_part(
        {"part_number": "BAD-1", "description": "Missing cost",
         "lead_time_days": 5, "weight_kg": 0.1}, PLANNER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    _, meta = validate_paginated(api.list_parts(PLANNER))
    assert meta["total_count"] == 0, "a rejected create must store nothing"


def test_dealer_create_with_unknown_tier_is_rejected(api):
    """PRD 3.1: "A dealer is registered with a unique `dealer_code`, a commercial
    `tier` of `PLATINUM`, `GOLD` or `SILVER`, a primary service `region` drawn from
    the same four-value set as installed units, and a `credit_limit_cents` that may
    not be negative."
    PRD 2.10: "The request body satisfies the endpoint's input schema: required
    fields present, enum members recognised, and integers inside their declared
    bounds — every quantity at least 1, `coverage_years` between 1 and 15 inclusive,
    `horizon_months` one of 12, 24 or 60, and `limit` between 1 and 100 inclusive.
    Otherwise `ERR_INVALID_REQUEST` (400). Applies to every endpoint."

    Design: Corner/entities/dealer_create_with_invalid_tier_enum_returns_invalid_request
    """
    resp = api.create_dealer(create_dealer_payload(
        dealer_code="D-BAD", tier="BRONZE", region="NA",
        credit_limit_cents=1000), ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_stock_ledger_entry_carries_no_version_or_updated_at(api):
    """PRD 2.5: "The single exception is the stock ledger entry: because the ledger
    is append-only and a posted movement is never amended, a stock ledger entry
    carries only `id` and `created_at` — it has no `updated_at` field and no
    `version` field at all."
    PRD 3.7: "one ledger entry is appended with `entry_type` `RECEIPT`, a positive
    `delta_units` equal to `qty`, a `balance_after_units` equal to the part's
    `on_hand_units` plus `quarantine_units` immediately afterwards, and a
    `source_ref_type` of `REPLENISHMENT_ORDER` with the order's identifier in
    `source_ref_id`."
    PRD 2.4: "It maintains a single logical clock whose startup value is exactly
    `2026-08-01T00:00:00Z`; before any clock control call the logical clock reads
    that default, and it never falls back to real time."

    Design: Corner/entities/stock_ledger_entry_is_immutable_and_carries_no_version
    """
    part = create_part(part_number="LED-1", description="Ledger probe",
                       unit_cost_cents=500, lead_time_days=10, weight_kg=1.0)
    order = receive_stock(part["id"], 12)

    entries, meta = list_ledger(part["id"])
    assert meta["total_count"] == 1, "one movement produces exactly one entry"
    row = entries[0]
    assert_ledger_entry(row)
    assert row["entry_type"] == "RECEIPT"
    assert row["delta_units"] == 12
    assert row["balance_after_units"] == 12
    assert row["source_ref_type"] == "REPLENISHMENT_ORDER"
    assert row["source_ref_id"] == order["id"]
    assert "version" not in row
    assert "updated_at" not in row
    assert row["occurred_at"].startswith("2026-08-01T00:00:00"), (
        f"occurred_at must read the default logical clock {CLOCK_DEFAULT_UTC}, "
        f"got {row['occurred_at']}"
    )


def test_installed_unit_create_with_unknown_model_id(api):
    """PRD 2.5: "The same codes are used when a foreign key supplied in a request
    body fails to resolve; body foreign keys are validated in the order in which the
    endpoint's input list declares them."
    PRD 2.10: "Every foreign key in the request body resolves, checked in the order
    the endpoint declares its inputs — otherwise the matching not-found code (404).
    Applies to every creating endpoint carrying a foreign key."

    Design: Corner/entities/installed_unit_create_with_unknown_model_returns_model_not_found
    """
    dealer = create_dealer("D-PAR", "GOLD", "NA", 1000)

    resp = api.create_installed_unit(create_installed_unit_payload(
        UNKNOWN_UUIDS["part"], dealer["id"], serial_number="SN-PAR",
        build_revision=10), ADMIN)
    validate_error(resp, ApiErrorId.ERR_MODEL_NOT_FOUND.value)

    _, meta = validate_paginated(
        api.list_installed_units(ADMIN, params={"dealer_id": dealer["id"]}))
    assert meta["total_count"] == 0


def test_applicability_rows_are_listable_by_part_and_by_model(api):
    """PRD 3.2: "A planner declares that a part fits a model over a range of build
    revisions by supplying the `part_id`, the `model_id`, an
    `effective_from_build_revision` giving the lowest revision the part fits
    (inclusive, and never negative), an optional `effective_to_build_revision` giving
    the highest revision it fits (also inclusive, with omission or null meaning
    unbounded above), and a `qty_per_unit` of at least 1 recording how many of the
    part are installed on one machine of that model."
    PRD 3.2: "Applicability rows can be listed and filtered by `part_id`, `model_id`
    and `applicability_status`."

    Design: Corner/entities/applicability_junction_is_reachable_from_both_sides
    """
    model = create_equipment_model("EM-JN", "Junction model")
    assert_equipment_model(model)
    p1 = create_part(part_number="JN-1", description="Junction part 1",
                     unit_cost_cents=100, lead_time_days=5, weight_kg=0.1)
    p2 = create_part(part_number="JN-2", description="Junction part 2",
                     unit_cost_cents=100, lead_time_days=5, weight_kg=0.1)
    create_applicability(p1["id"], model["id"], 0, 99, 1)
    create_applicability(p2["id"], model["id"], 100, None, 2)

    by_model, meta_model = validate_paginated(
        api.list_part_applicabilities(PLANNER, params={"model_id": model["id"]}))
    assert meta_model["total_count"] == 2

    by_part, meta_part = validate_paginated(
        api.list_part_applicabilities(PLANNER, params={"part_id": p1["id"]}))
    assert meta_part["total_count"] == 1
    row = by_part[0]
    assert_part_applicability(row)
    assert row["qty_per_unit"] == 1
    assert row["effective_to_build_revision"] == 99
    for r in by_model:
        assert r["applicability_status"] == "ACTIVE"


def test_predecessor_is_found_by_superseded_by_part_id_filter(api):
    """PRD 3.2: "The catalogue can be listed with filters on `lifecycle_state`, on
    `criticality_class`, and — this is the self-referential reverse lookup — on
    `superseded_by_part_id`, which returns every predecessor part that points at one
    nominated successor."
    PRD 3.8: "On success the part's `superseded_by_part_id` is set to the nominated
    successor, its `lifecycle_state` becomes `SUPERSEDED`, and its `stocking_policy`
    becomes `NO_STOCK`."

    Design: Corner/entities/superseded_part_is_reachable_from_its_successor_by_filter
    """
    old = create_part(part_number="OLD-2", description="Predecessor",
                      unit_cost_cents=100, lead_time_days=5, weight_kg=0.1)
    new = create_part(part_number="NEW-2", description="Successor",
                      unit_cost_cents=120, lead_time_days=5, weight_kg=0.1)
    validate_success(api.supersede_part(old["id"], new["id"], PLANNER))

    rows, meta = validate_paginated(
        api.list_parts(PLANNER, params={"superseded_by_part_id": new["id"]}))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == old["id"]

    predecessor = read_part(old["id"])
    assert predecessor["lifecycle_state"] == "SUPERSEDED"
    assert predecessor["stocking_policy"] == "NO_STOCK"
    successor = read_part(new["id"])
    assert successor["lifecycle_state"] == "ACTIVE"
    assert successor["superseded_by_part_id"] is None


def test_supersession_chain_that_closes_on_itself_is_refused(api):
    """PRD 3.8: "Precisely because such chains are legal, the chain must be checked:
    walking the successor's own `superseded_by_part_id` pointer transitively must
    never arrive back at the part being superseded, and a chain that closes on itself
    is refused with `ERR_SUPERSESSION_CYCLE`."

    Design: Corner/entities/supersession_cycle_is_rejected
    """
    old = create_part(part_number="OLD-3", description="Cycle predecessor",
                      unit_cost_cents=100, lead_time_days=5, weight_kg=0.1)
    new = create_part(part_number="NEW-3", description="Cycle successor",
                      unit_cost_cents=120, lead_time_days=5, weight_kg=0.1)
    validate_success(api.supersede_part(old["id"], new["id"], PLANNER))

    resp = api.supersede_part(new["id"], old["id"], PLANNER)
    validate_error(resp, ApiErrorId.ERR_SUPERSESSION_CYCLE.value)

    still_active = read_part(new["id"])
    assert still_active["lifecycle_state"] == "ACTIVE"
    assert still_active["superseded_by_part_id"] is None


def test_reinstate_on_an_active_part_is_refused(api):
    """PRD 3.8: "Reinstating a part moves it from `PHASE_OUT` back to `ACTIVE`, but
    only when no campaign on that part is currently `SUBMITTED`, `APPROVED` or
    `ALLOCATING`; a part not in `PHASE_OUT`, or one with a live campaign in any of
    those three states, gives `ERR_PART_LIFECYCLE_INVALID`."

    Design: Corner/state_machines/part_reinstate_from_active_returns_lifecycle_invalid
    """
    part = create_part(part_number="INV-1", description="Invalid transition probe",
                       unit_cost_cents=100, lead_time_days=5, weight_kg=0.1)

    resp = api.reinstate_part(part["id"], PLANNER)
    validate_error(resp, ApiErrorId.ERR_PART_LIFECYCLE_INVALID.value)

    after = read_part(part["id"])
    assert after["lifecycle_state"] == "ACTIVE"
    assert after["version"] == 1, "a refused transition must not advance version"


def test_clock_cannot_move_backwards(api):
    """PRD 2.4: "The clock is monotonic: a requested instant earlier than the current
    logical instant is rejected with `ERR_CLOCK_NOT_MONOTONIC` and HTTP 409, while an
    instant equal to the current one is accepted."
    PRD 2.4: "A `PlatformAdmin` may advance the clock by supplying a `to_iso8601`
    instant, and the response reports the new setting as `current_utc`."

    Design: Corner/validations/clock_set_backwards_is_rejected
    """
    set_clock("2026-09-01T00:00:00Z")

    backwards = api.set_clock("2026-07-31T00:00:00Z", ADMIN)
    validate_error(backwards, ApiErrorId.ERR_CLOCK_NOT_MONOTONIC.value)

    same = validate_success(api.set_clock("2026-09-01T00:00:00Z", ADMIN))
    assert same["current_utc"].startswith("2026-09-01T00:00:00"), (
        f"an equal instant is accepted and reported back, got {same['current_utc']}"
    )


def test_applicability_withdraw_reopens_the_applicability_gate(api):
    """PRD 3.2: "Withdrawing an applicability row moves its `applicability_status` to
    `WITHDRAWN` and advances its `version`; from then on the row is ignored by the
    overlap check, ignored when validating whether a part may go on a work order
    line, and ignored by the installed-base leg of forecasting."
    PRD 3.6: "The part must be applicable to this exact machine — an `ACTIVE`
    applicability row must exist whose part matches, whose model matches the
    machine's `model_id`, and whose build-revision interval covers the machine's
    `build_revision` — or the line is refused with `ERR_PART_NOT_APPLICABLE`."

    Design: Corner/endpoints/applicability_withdraw_reopens_the_safety_gate
    """
    scenario = setup_catalogue(part_number="WDR-1", lead_time_days=0,
                               dealer_code="D-WDR", model_code="EM-AC1",
                               serial_prefix="SN-AC1")
    dealer_headers = scenario["dealer_headers"]
    wo1 = validate_success(api.create_work_order(
        {"installed_unit_id": scenario["unit"]["id"],
         "work_type": "SCHEDULED_MAINTENANCE", "downtime_priority": "PLANNED"},
        dealer_headers), 201)
    wo2 = validate_success(api.create_work_order(
        {"installed_unit_id": scenario["unit"]["id"],
         "work_type": "SCHEDULED_MAINTENANCE", "downtime_priority": "PLANNED"},
        dealer_headers), 201)
    line1 = validate_success(api.create_part_line(
        wo1["id"], create_part_line_payload(scenario["part"]["id"], 1),
        dealer_headers), 201)
    assert line1["line_status"] == "BACKORDERED", \
        "the line was accepted while the applicability row was ACTIVE"

    withdrawn = validate_success(api.withdraw_part_applicability(
        scenario["applicability"]["id"], PLANNER))
    assert withdrawn["applicability_status"] == "WITHDRAWN"

    resp = api.create_part_line(
        wo2["id"], create_part_line_payload(scenario["part"]["id"], 1),
        dealer_headers)
    validate_error(resp, ApiErrorId.ERR_PART_NOT_APPLICABLE.value)

    _, meta_lines = validate_paginated(
        api.list_part_lines(PLANNER, params={"part_id": scenario["part"]["id"]}))
    assert meta_lines["total_count"] == 1
    _, meta_active = validate_paginated(api.list_part_applicabilities(
        PLANNER, params={"part_id": scenario["part"]["id"],
                         "applicability_status": "ACTIVE"}))
    assert meta_active["total_count"] == 0


def test_part_version_increments_by_one_per_mutation(api):
    """PRD 2.5: "Almost every resource additionally carries an `updated_at` timestamp
    in the same format, refreshed on every mutation, and a `version`, an integer that
    starts at 1 when the resource is created and increases by exactly 1 on every
    mutation of that resource."
    PRD 2.8: "The derived counter `available_units` is always `on_hand_units` minus
    `allocated_units`, and it is recomputed after every movement that touches either
    operand."

    Design: Corner/cross_cutting_layers/version_increments_by_one_on_every_mutation
    """
    part = create_part(part_number="VER-1", description="Version probe",
                       unit_cost_cents=100, lead_time_days=5, weight_kg=0.1)
    created_at = part["created_at"]
    assert part["version"] == 1
    assert part["available_units"] == part["on_hand_units"] - part["allocated_units"]

    phased = validate_success(api.phase_out_part(part["id"], PLANNER))
    assert phased["version"] == 2
    assert phased["lifecycle_state"] == "PHASE_OUT"
    assert phased["available_units"] == \
        phased["on_hand_units"] - phased["allocated_units"]

    reinstated = validate_success(api.reinstate_part(part["id"], PLANNER))
    assert reinstated["version"] == 3
    assert reinstated["lifecycle_state"] == "ACTIVE"
    assert reinstated["available_units"] == \
        reinstated["on_hand_units"] - reinstated["allocated_units"]
    assert reinstated["created_at"] == created_at, "created_at never moves"
    assert is_iso8601_timestamp(reinstated["updated_at"])


def test_each_resource_family_has_its_own_not_found_code(api):
    """PRD 2.5: "Each resource family has its own not-found code, all carrying HTTP
    404: `ERR_PART_NOT_FOUND`, `ERR_MODEL_NOT_FOUND`, `ERR_INSTALLED_UNIT_NOT_FOUND`,
    `ERR_DEALER_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, `ERR_PART_LINE_NOT_FOUND`,
    `ERR_CAMPAIGN_NOT_FOUND`, `ERR_ALLOCATION_REQUEST_NOT_FOUND`,
    `ERR_REPLENISHMENT_ORDER_NOT_FOUND`, `ERR_RETURN_NOT_FOUND` and
    `ERR_APPLICABILITY_NOT_FOUND`."

    Design: Corner/errors/unknown_ids_return_entity_specific_not_found_errors
    """
    cases = [
        (api.get_equipment_model(UNKNOWN_UUIDS["model"], ADMIN),
         ApiErrorId.ERR_MODEL_NOT_FOUND.value),
        (api.get_installed_unit(UNKNOWN_UUIDS["installed_unit"], ADMIN),
         ApiErrorId.ERR_INSTALLED_UNIT_NOT_FOUND.value),
        (api.get_dealer(UNKNOWN_UUIDS["dealer"], ADMIN),
         ApiErrorId.ERR_DEALER_NOT_FOUND.value),
        (api.get_work_order(UNKNOWN_UUIDS["work_order"], PLANNER),
         ApiErrorId.ERR_WORK_ORDER_NOT_FOUND.value),
        (api.get_part_line(UNKNOWN_UUIDS["part_line"], PLANNER),
         ApiErrorId.ERR_PART_LINE_NOT_FOUND.value),
        (api.get_campaign(UNKNOWN_UUIDS["campaign"], PLANNER),
         ApiErrorId.ERR_CAMPAIGN_NOT_FOUND.value),
        (api.get_allocation_request(UNKNOWN_UUIDS["allocation_request"], PLANNER),
         ApiErrorId.ERR_ALLOCATION_REQUEST_NOT_FOUND.value),
        (api.get_replenishment_order(UNKNOWN_UUIDS["replenishment_order"], CONTROLLER),
         ApiErrorId.ERR_REPLENISHMENT_ORDER_NOT_FOUND.value),
        (api.get_return_authorization(UNKNOWN_UUIDS["return_authorization"], PLANNER),
         ApiErrorId.ERR_RETURN_NOT_FOUND.value),
        (api.withdraw_part_applicability(UNKNOWN_UUIDS["applicability"], PLANNER),
         ApiErrorId.ERR_APPLICABILITY_NOT_FOUND.value),
    ]
    for resp, expected in cases:
        assert resp.status_code == 404, (
            f"expected HTTP 404 for {expected}, got {resp.status_code}")
        validate_error(resp, expected)
        assert resp.json()["response_type"] == "error"


def test_touching_build_revision_intervals_are_rejected(api):
    """PRD 3.2: "The new build-revision range is treated as a **closed integer
    interval**, with a null upper bound treated as extending to positive infinity, and
    it must not intersect the range of any existing `ACTIVE` applicability row for the
    same part-and-model pair."
    PRD 3.2: "Note the integer geometry carefully: adjacency is permitted, so a new
    range whose lower bound is one greater than an existing row's upper bound is
    accepted, whereas a new range whose lower bound equals that existing upper bound
    is rejected with `ERR_APPLICABILITY_REVISION_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/applicability_build_revision_closed_interval_adjacency_allowed
    """
    model = create_equipment_model("EM-H10", "Hauler H10")
    part = create_part(part_number="IVL-1", description="Interval probe part",
                       unit_cost_cents=1000, lead_time_days=30, weight_kg=1.0)
    create_applicability(part["id"], model["id"], 100, 200, 1)

    resp = api.create_part_applicability(
        {"part_id": part["id"], "model_id": model["id"],
         "effective_from_build_revision": 200, "effective_to_build_revision": 300,
         "qty_per_unit": 1}, PLANNER)
    validate_error(resp, ApiErrorId.ERR_APPLICABILITY_REVISION_OVERLAP.value)

    _, meta = validate_paginated(api.list_part_applicabilities(
        PLANNER, params={"part_id": part["id"], "model_id": model["id"]}))
    assert meta["total_count"] == 1, "the rejected row must not be stored"


def test_adjacent_and_open_ended_build_revision_intervals_are_accepted(api):
    """PRD 3.2: "Note the integer geometry carefully: adjacency is permitted, so a new
    range whose lower bound is one greater than an existing row's upper bound is
    accepted, whereas a new range whose lower bound equals that existing upper bound
    is rejected with `ERR_APPLICABILITY_REVISION_OVERLAP`."
    PRD 3.2: "The new build-revision range is treated as a **closed integer
    interval**, with a null upper bound treated as extending to positive infinity, and
    it must not intersect the range of any existing `ACTIVE` applicability row for the
    same part-and-model pair."

    Design: Difficulty/resource_temporal_overlap/applicability_build_revision_closed_interval_adjacency_allowed
    """
    model = create_equipment_model("EM-H10", "Hauler H10")
    part = create_part(part_number="IVL-1", description="Interval probe part",
                       unit_cost_cents=1000, lead_time_days=30, weight_kg=1.0)
    create_applicability(part["id"], model["id"], 100, 200, 1)

    adjacent = validate_success(api.create_part_applicability(
        {"part_id": part["id"], "model_id": model["id"],
         "effective_from_build_revision": 201, "effective_to_build_revision": 300,
         "qty_per_unit": 1}, PLANNER), 201)
    assert adjacent["applicability_status"] == "ACTIVE"

    open_ended = validate_success(api.create_part_applicability(
        {"part_id": part["id"], "model_id": model["id"],
         "effective_from_build_revision": 400, "qty_per_unit": 1}, PLANNER), 201)
    assert open_ended["effective_to_build_revision"] is None, \
        "an omitted upper bound means unbounded above"

    inside_open_ended = api.create_part_applicability(
        {"part_id": part["id"], "model_id": model["id"],
         "effective_from_build_revision": 500, "effective_to_build_revision": 600,
         "qty_per_unit": 1}, PLANNER)
    validate_error(inside_open_ended,
                   ApiErrorId.ERR_APPLICABILITY_REVISION_OVERLAP.value)

    _, meta = validate_paginated(api.list_part_applicabilities(
        PLANNER, params={"part_id": part["id"], "model_id": model["id"]}))
    assert meta["total_count"] == 3
    assert read_applicability(open_ended["id"])["effective_to_build_revision"] is None
