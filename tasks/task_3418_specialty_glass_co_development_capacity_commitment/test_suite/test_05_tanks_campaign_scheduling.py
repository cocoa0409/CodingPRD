"""Tank funding/construction gates and campaign scheduling rules.

Covers the SECURED-funding gate, one-tank-per-commitment, construction
readiness against the logical clock (PRD section 3.5), the campaign window
length boundaries, the capacity cap, the start-time gate, and the tank
schedule conflict rules including the 45-day changeover buffer.
"""

from datetime import datetime

from test_helpers import (
    DEFAULT_CLOCK_ISO,
    TANK_CONSTRUCTION_DAYS,
    TEST_USERS,
    ApiErrorId,
    api_client,
    begin_testing,
    create_commissioned_tank,
    create_commitment,
    create_composition,
    create_program_with_nda,
    create_qual_cycle,
    create_secured_commitment,
    create_tank,
    create_qualified_composition,
    factories,
    record_qual_result,
    setup_supply_chain,
    shift_iso,
    sign_commitment,
    validate_created,
    validate_error,
    validate_paginated,
    get_success_data,
)

MANAGER = TEST_USERS["program_manager_headers"]
PLANNER = TEST_USERS["capacity_planner_headers"]

CAMPAIGN_START = "2028-03-01T00:00:00Z"
CAMPAIGN_END = "2029-03-01T00:00:00Z"


def _parse(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _setup_to_commissioned_tank(capacity_units_per_day: int = 1000):
    """Maker + program (NDA) + QUALIFIED composition + SECURED commitment +
    COMMISSIONED tank. Mirrors the shared supply-chain bootstrap minus the
    campaign, for tests that drive campaign creation themselves."""
    chain = create_program_with_nda()
    qual = create_qualified_composition(chain.program, chain.maker)
    commitment = create_secured_commitment(chain.program, chain.maker)
    tank = create_commissioned_tank(commitment, capacity_units_per_day)
    return chain, qual, commitment, tank


def test_tank_create_without_secured_commitment_returns_not_secured():
    """PRD section 3.5: "The referenced commitment must be `SECURED` —
    capacity investment is gated on a secured customer commitment, and any
    other status fails with `ERR_COMMITMENT_NOT_SECURED`" — a merely SIGNED
    commitment cannot fund a tank.

    Design: Corner/errors/tank_create_without_secured_commitment_returns_not_secured
    """
    chain = create_program_with_nda()
    # PROPOSED -> SIGNED only; prepayment is never confirmed.
    commitment = sign_commitment(create_commitment(chain.program), chain.maker)
    resp = api_client.create_tank(
        factories.create_tank_payload(commitment["id"], capacity_units_per_day=1000),
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_COMMITMENT_NOT_SECURED)


def test_second_tank_for_commitment_returns_tank_already_exists():
    """PRD section 3.5: "a commitment funds at most one tank: a second tank
    against the same commitment fails with `ERR_TANK_ALREADY_EXISTS`."

    Design: Corner/errors/second_tank_for_commitment_returns_tank_already_exists
    """
    chain = create_program_with_nda()
    commitment = create_secured_commitment(chain.program, chain.maker)
    create_tank(commitment, capacity_units_per_day=1000)
    resp = api_client.create_tank(
        factories.create_tank_payload(commitment["id"], capacity_units_per_day=2000),
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_TANK_ALREADY_EXISTS)


def test_commission_before_ready_returns_tank_under_construction():
    """PRD section 3.5: "its `construction_ready_date` is fixed at creation to
    its `created_at` plus 540 days (CONST.TANK_CONSTRUCTION_DAYS)" and "an
    early attempt fails with `ERR_TANK_UNDER_CONSTRUCTION`". PRD section 2.4:
    "Before any call to the clock-setting capability, the logical clock reads
    exactly 2026-09-01T00:00:00Z (CONST.DEFAULT_CLOCK_ISO)" — so a tank built
    on the default clock is ready at 2028-02-23T00:00:00Z.

    Design: Corner/errors/commission_before_ready_returns_tank_under_construction
    """
    chain = create_program_with_nda()
    commitment = create_secured_commitment(chain.program, chain.maker)
    tank = create_tank(commitment)  # clock never advanced
    expected_ready = shift_iso(DEFAULT_CLOCK_ISO, days=TANK_CONSTRUCTION_DAYS)
    assert expected_ready == "2028-02-23T00:00:00Z"
    assert _parse(tank["construction_ready_date"]) == _parse(expected_ready)
    resp = api_client.commission_tank(tank["id"], headers=PLANNER)
    validate_error(resp, ApiErrorId.ERR_TANK_UNDER_CONSTRUCTION)
    tank = get_success_data(api_client.get_tank(tank["id"], PLANNER))
    assert tank["status"] == "CONSTRUCTING"


def test_campaign_over_capacity_returns_over_capacity():
    """PRD section 3.5: "must not exceed the tank's `capacity_units_per_day`
    multiplied by the window's length in days, failing with
    `ERR_CAMPAIGN_OVER_CAPACITY`" — 5000 planned units over 365 days against a
    10-units-per-day tank (3650 maximum) exceeds it.

    Design: Corner/errors/campaign_over_capacity_returns_over_capacity
    """
    _, qual, _, tank = _setup_to_commissioned_tank(capacity_units_per_day=10)
    resp = api_client.create_campaign(
        factories.create_campaign_payload(
            tank["id"], qual.composition["id"], planned_units=5000
        ),
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_OVER_CAPACITY)


def test_campaign_364_days_returns_invalid_window():
    """PRD section 3.5: "the window's length in days must be at least 365 days
    (CONST.MIN_CAMPAIGN_DAYS, with exactly 365 allowed) and at most 1825 days
    (CONST.MAX_CAMPAIGN_DAYS); violations fail with
    `ERR_INVALID_CAMPAIGN_WINDOW`" — 364 days is one day short.

    Design: Corner/validations/campaign_364_days_returns_invalid_window
    """
    _, qual, _, tank = _setup_to_commissioned_tank()
    resp = api_client.create_campaign(
        factories.create_campaign_payload(
            tank["id"],
            qual.composition["id"],
            start_date=CAMPAIGN_START,
            end_date="2029-02-28T00:00:00Z",
            planned_units=10000,
        ),
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_CAMPAIGN_WINDOW)


def test_campaign_min_length_exactly_365_days_succeeds():
    """PRD section 3.5: "the window's length in days must be at least 365 days
    (CONST.MIN_CAMPAIGN_DAYS, with exactly 365 allowed)". The exactly-365-day
    window [2028-03-01, 2029-03-01) is accepted; with 10000 planned units the
    step-1 provisional yield floors to 6200 good units and the provisional unit
    cost is ceil((850 * 1.0 + 120) / 0.62) = 1565 with no changeover.

    Design: Difficulty/boundary_precision_check/campaign_min_length_exactly_365_days_succeeds
    """
    _, qual, _, tank = _setup_to_commissioned_tank()
    campaign = validate_created(
        api_client.create_campaign(
            factories.create_campaign_payload(
                tank["id"],
                qual.composition["id"],
                start_date=CAMPAIGN_START,
                end_date=CAMPAIGN_END,
                planned_units=10000,
            ),
            PLANNER,
        )
    )
    assert campaign["status"] == "SCHEDULED"
    assert campaign["expected_good_units"] == 6200  # floor(10000 * 0.62)
    assert campaign["provisional_unit_cost_cents"] == 1565  # ceil(970 / 0.62)


def test_start_before_start_date_returns_campaign_not_started():
    """PRD section 3.6: "the logical clock must have reached the campaign's
    `start_date` — an early start fails with `ERR_CAMPAIGN_NOT_STARTED`" — the
    clock still reads the tank's commission day 2028-02-23, before the
    2028-03-01 start.

    Design: Corner/errors/start_before_start_date_returns_campaign_not_started
    """
    chain = setup_supply_chain()
    resp = api_client.start_campaign(chain.campaign["id"], headers=PLANNER)
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_NOT_STARTED)
    campaign = get_success_data(api_client.get_campaign(chain.campaign["id"], PLANNER))
    assert campaign["status"] == "SCHEDULED"


def test_campaign_temporal_trumps_referential():
    """PRD section 2.8: "the failure reported is the one with the highest
    priority: checks are evaluated in the fixed order below and the first
    failure wins." The new window overlaps an existing campaign on the tank
    (tank schedule, priority 13) and its composition is still EXPERIMENTAL
    (composition maturity, priority 17); the earlier check wins, so the
    violation is reported as `ERR_TANK_SCHEDULE_CONFLICT`.

    Design: Difficulty/priority_pair_validation_conflict/campaign_temporal_trumps_referential
    """
    chain = setup_supply_chain()  # campaign A on QUALIFIED GX-100 occupies the tank
    cx2 = create_composition(chain.program, composition_code="GX-300")  # EXPERIMENTAL
    resp = api_client.create_campaign(
        factories.create_campaign_payload(
            chain.tank["id"],
            cx2["id"],
            start_date="2028-06-01T00:00:00Z",
            end_date="2029-06-01T00:00:00Z",
            planned_units=10000,
        ),
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_TANK_SCHEDULE_CONFLICT)
    _, meta = validate_paginated(
        api_client.list_campaigns(PLANNER, {"tank_id": chain.tank["id"]})
    )
    assert meta["total_count"] == 1


def test_tank_changeover_buffer_45_days_enforced():
    """PRD section 3.5: "versus every existing campaign on that tank with a
    different `composition_id`, the gap between the adjoining window edges must
    be at least 45 days (CONST.CHANGEOVER_GAP_DAYS) on whichever side they
    adjoin — same-composition neighbors may abut with a gap of zero. A
    violation fails with `ERR_TANK_SCHEDULE_CONFLICT`." A 14-day gap fails; a
    gap of exactly 45 days succeeds and pays changeover amortization:
    ceil((850 + 120) / 0.62) + ceil(4000 * 365 / 10000) = 1565 + 146 = 1711.

    Design: Difficulty/resource_temporal_overlap/tank_changeover_buffer_45_days_enforced
    """
    chain = setup_supply_chain()  # campaign A on GX-100: [2028-03-01, 2029-03-01)
    cx2 = create_composition(chain.program, composition_code="GX-300")
    cycle2 = create_qual_cycle(cx2, test_plan_ref="TP-2")
    cycle2 = begin_testing(cycle2, chain.maker["id"])
    record_qual_result(cycle2, chain.maker["id"], "PASSED")

    too_close = factories.create_campaign_payload(
        chain.tank["id"],
        cx2["id"],
        start_date="2029-03-15T00:00:00Z",
        end_date="2030-03-15T00:00:00Z",
        planned_units=10000,
    )
    resp = api_client.create_campaign(too_close, PLANNER)
    validate_error(resp, ApiErrorId.ERR_TANK_SCHEDULE_CONFLICT)

    exact_gap = factories.create_campaign_payload(
        chain.tank["id"],
        cx2["id"],
        start_date="2029-04-15T00:00:00Z",
        end_date="2030-04-15T00:00:00Z",
        planned_units=10000,
    )
    campaign_b = validate_created(api_client.create_campaign(exact_gap, PLANNER))
    assert campaign_b["status"] == "SCHEDULED"
    assert campaign_b["provisional_unit_cost_cents"] == 1711
