"""Uptime contracts: downtime-event intake with OCC, close-month chronology,
the empty-fleet refusal, and the ROUTE_DAY / VEHICLE_HOUR pro-rating variants
feeding the tiered marginal breach credit."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    append_downtime,
    close_month_payload,
    create_fleet_customer,
    create_uptime_contract,
    downtime_event_payload,
    read_uptime_contract,
    set_logical_clock,
    setup_commissioned_fleet,
    setup_uptime_contract_with_fleet,
    validate_error,
    validate_success,
)

_ADMIN = TEST_USERS["platform_admin_headers"]
_TELEMATICS = TEST_USERS["telematics_ingestion_headers"]


def test_close_month_with_no_in_service_fleet_rejected(api):
    """PRD section 3.10: "The close measures the customer's in-service fleet —
    the vehicles whose orders belong to this customer and whose
    `delivery_status` is `AT_DEPOT` or `COMMISSIONED` at close time. If that
    fleet count is zero there is nothing to measure and the close is refused
    with `ERR_INVALID_STATE`."

    Design: Corner/calculations/close_month_with_no_in_service_fleet_rejected
    """
    set_logical_clock()
    customer = create_fleet_customer()
    contract = create_uptime_contract(customer)
    resp = api.close_uptime_month(contract["id"], close_month_payload("2026-09"), _ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    current = read_uptime_contract(customer, contract["id"])
    assert current["last_closed_month"] is None
    assert current["last_uptime_pct"] is None


def test_close_month_chronology_enforced(api):
    """PRD section 3.10: "The month must be well-formed (`ERR_WINDOW_INVALID`),
    may not precede the month containing `measurement_start_date`
    (`ERR_MONTH_OUT_OF_ORDER`), and months close strictly chronologically, each
    exactly once: closing the month already recorded in `last_closed_month` is
    `ERR_MONTH_ALREADY_CLOSED`, and closing an earlier one is
    `ERR_MONTH_OUT_OF_ORDER`."

    Design: Corner/calculations/close_month_chronology_enforced
    """
    scenario = setup_uptime_contract_with_fleet(num_vehicles=1)
    contract = scenario["contract"]
    early = api.close_uptime_month(contract["id"], close_month_payload("2026-08"), _ADMIN)
    validate_error(early, ApiErrorId.ERR_MONTH_OUT_OF_ORDER)
    closed = validate_success(
        api.close_uptime_month(contract["id"], close_month_payload("2026-09"), _ADMIN), 200
    )
    assert closed["last_uptime_pct"] == pytest.approx(100.0), "no downtime over the month"
    assert closed["last_credit_cents"] == 0
    assert closed["last_closed_month"] == "2026-09"
    duplicate = api.close_uptime_month(contract["id"], close_month_payload("2026-09"), _ADMIN)
    validate_error(duplicate, ApiErrorId.ERR_MONTH_ALREADY_CLOSED)
    backwards = api.close_uptime_month(contract["id"], close_month_payload("2026-08"), _ADMIN)
    validate_error(backwards, ApiErrorId.ERR_MONTH_OUT_OF_ORDER)


def test_downtime_append_with_stale_contract_version_rejected(api):
    """PRD section 2.6: "Appending a downtime event to an uptime contract
    requires `expected_uptime_contract_version` matching the contract's
    current `version`. The client may otherwise be extending an event list it
    has never observed, and the append is refused." — `ERR_STALE_VERSION`
    (HTTP 412); PRD section 3.10: "Each append carries the
    `expected_uptime_contract_version` guard of section 2.6 and increments the
    contract's `version` by 1."

    Design: Corner/complexity_layers/downtime_append_with_stale_contract_version_rejected
    """
    scenario = setup_uptime_contract_with_fleet(num_vehicles=1)
    customer = scenario["fleet"]["customer"]
    contract = scenario["contract"]
    veh_id = scenario["fleet"]["vehicles"][0]["id"]
    refreshed = append_downtime(
        contract, veh_id, "2026-09-05T08:00:00Z", ended_at="2026-09-05T12:00:00Z"
    )
    assert refreshed["version"] == contract["version"] + 1
    resp = api.append_downtime_event(
        contract["id"],
        downtime_event_payload(
            veh_id, "2026-09-06T08:00:00Z", contract["version"],
            ended_at="2026-09-06T09:00:00Z",
        ),
        _TELEMATICS,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    current = read_uptime_contract(customer, contract["id"])
    assert len(current["downtime_events"]) == 1, "the rejected append added nothing"


def _setup_contract_with_two_day_event(pro_rating):
    """Two-vehicle commissioned fleet; one uptime contract of the given
    pro_rating; one downtime event on vehicle 1 spanning 2026-09-02T06:00Z to
    2026-09-03T06:00Z (2 calendar days; 24.0 hours)."""
    scenario = setup_uptime_contract_with_fleet(num_vehicles=2, pro_rating=pro_rating)
    contract = scenario["contract"]
    veh1_id = scenario["fleet"]["vehicles"][0]["id"]
    append_downtime(
        contract, veh1_id, "2026-09-02T06:00:00Z", ended_at="2026-09-03T06:00:00Z"
    )
    return scenario, contract


def test_uptime_credit_route_day_variant(api):
    """PRD section 3.10: "Under `ROUTE_DAY`, downtime is summed per vehicle as
    the count of distinct UTC calendar days in the month overlapped by any of
    that vehicle's events — any overlap with a day, however brief, counts the
    whole day once." and "Measured uptime is then one minus
    downtime-vehicle-days divided by the product of fleet size and the number
    of UTC calendar days in the month, converted to a percentage and rounded
    half-up to one decimal." — 2 route-days over 2 vehicles x 30 days.

    Design: Difficulty/dual_variant_calc/uptime_credit_route_day_vs_vehicle_hour_divergence
    """
    _scenario, contract = _setup_contract_with_two_day_event("ROUTE_DAY")
    closed = validate_success(
        api.close_uptime_month(contract["id"], close_month_payload("2026-09"), _ADMIN), 200
    )
    assert closed["last_uptime_pct"] == pytest.approx(96.7), "1 - 2/(2 x 30)"
    assert closed["last_credit_cents"] == 12000, "shortfall 0.3 -> 0.6% of 2000000"


def test_uptime_credit_vehicle_hour_variant_diverges(api):
    """PRD section 3.10: "Under `VEHICLE_HOUR`, each event's overlap with the
    month is measured in hours, rounded half-up to a tenth of an hour per
    event before any summation, the per-event figures are summed, and the
    total is divided by 24 to yield vehicle-days." — 24.0 h is 1.0
    vehicle-day; and "The breach credit is a marginal tiered rate on the
    shortfall — the committed percentage minus the measured percentage,
    floored at zero."

    Design: Difficulty/dual_variant_calc/uptime_credit_route_day_vs_vehicle_hour_divergence
    """
    fleet = setup_commissioned_fleet(num_vehicles=2)
    customer = fleet["customer"]
    veh1_id = fleet["vehicles"][0]["id"]
    contract_rd = create_uptime_contract(customer, pro_rating="ROUTE_DAY")
    contract_vh = create_uptime_contract(customer, pro_rating="VEHICLE_HOUR")
    for contract in (contract_rd, contract_vh):
        append_downtime(
            contract, veh1_id, "2026-09-02T06:00:00Z", ended_at="2026-09-03T06:00:00Z"
        )
    closed_rd = validate_success(
        api.close_uptime_month(contract_rd["id"], close_month_payload("2026-09"), _ADMIN), 200
    )
    closed_vh = validate_success(
        api.close_uptime_month(contract_vh["id"], close_month_payload("2026-09"), _ADMIN), 200
    )
    assert closed_vh["last_uptime_pct"] == pytest.approx(98.3), "1 - 1.0/(2 x 30)"
    assert closed_vh["last_credit_cents"] == 0, "no breach under VEHICLE_HOUR"
    assert closed_rd["last_credit_cents"] == 12000
    assert closed_rd["last_credit_cents"] != closed_vh["last_credit_cents"], (
        "identical inputs, divergent variants"
    )


def _close_ten_day_route_day(api):
    """Four-vehicle commissioned fleet; ROUTE_DAY contract (committed 97.0,
    fee 2000000, start 2026-09-01); vehicle 1 down 2026-09-01T00:00Z through
    2026-09-11T00:00Z (10 distinct calendar days); close 2026-09."""
    scenario = setup_uptime_contract_with_fleet(num_vehicles=4, pro_rating="ROUTE_DAY")
    contract = scenario["contract"]
    veh1_id = scenario["fleet"]["vehicles"][0]["id"]
    append_downtime(
        contract, veh1_id, "2026-09-01T00:00:00Z", ended_at="2026-09-11T00:00:00Z"
    )
    return validate_success(
        api.close_uptime_month(contract["id"], close_month_payload("2026-09"), _ADMIN), 200
    ), contract


def test_uptime_credit_tiered_marginal_rates(api):
    """PRD section 3.10: "The first 2.0 percentage points of shortfall earn 2
    percent of the monthly fee per point, the next 3.0 points (beyond 2.0, up
    to 5.0) earn 5 percent per point, and any shortfall beyond 5.0 points
    earns 10 percent per point; the summed credit percentage is capped at 30.0
    percent. The credit in cents is the monthly fee multiplied by the capped
    percentage over 100, rounded half-up to integer cents."

    Design: Difficulty/combinatorial_formula/uptime_credit_tiered_marginal_rates
    """
    closed, _contract = _close_ten_day_route_day(api)
    assert closed["last_uptime_pct"] == pytest.approx(91.7), "1 - 10/(4 x 30)"
    assert closed["last_credit_cents"] == 440000, (
        "shortfall 5.3 -> 2.0x2 + 3.0x5 + 0.3x10 = 22.0% of 2000000"
    )


def test_uptime_close_accumulates_lifetime_credit(api):
    """PRD section 3.10: "A successful close records the `month` into
    `last_closed_month`, the measured figure into `last_uptime_pct`, the
    credit into `last_credit_cents`, accumulates the credit into
    `lifetime_credit_cents`, and increments the contract's `version`."

    Design: Difficulty/combinatorial_formula/uptime_credit_tiered_marginal_rates
    """
    closed, contract = _close_ten_day_route_day(api)
    assert closed["last_closed_month"] == "2026-09"
    assert closed["lifetime_credit_cents"] == 440000
    assert closed["version"] == contract["version"] + 2, (
        "one version bump each for the downtime append and the close"
    )
