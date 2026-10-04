"""Water-system aggregate conservation across hydrant outage and reactivation."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    get_success_data,
    make_field_analyst_headers,
    set_hydrant_status,
    setup_scoring_cycle,
    validate_error,
)

ANALYST = TEST_USERS["field_analyst_headers"]


def _two_certified_hydrants(api):
    """System with hydrants certified at 2172 and 1629 gpm (aggregates 3801/2)."""
    return setup_scoring_cycle(
        api, name="Hydra Springs", population=9000, area_sq_miles=18, rural_area_pct=10,
        needed_fire_flow_gpm=2000, supply_works_capacity_gpm=2500, daily_consumption_gpm=300,
        target_state="FIELD_VERIFICATION",
        hydrant_count=2,
        flow_tests=[
            {"hydrant": 0, "measured_flow_gpm": 1200, "outcome": "certified"},
            {"hydrant": 1, "measured_flow_gpm": 900, "outcome": "certified"},
        ],
    )


def test_hydrant_outage_drops_system_aggregates(api):
    """PRD §3.4: "Toggling a hydrant between `ACTIVE` and `OUT_OF_SERVICE` —
    again only while the data window is open — immediately recomputes them:
    `active_certified_flow_gpm`, the sum of `max_flow_gpm` over `ACTIVE`
    hydrants that hold a certified flow test, and
    `creditworthy_hydrant_count`, the count of `ACTIVE` hydrants whose
    `max_flow_gpm` is at least 1000 gallons per minute."

    Design: Difficulty/compensating_invariant/hydrant_outage_reactivation_flow_conservation
    """
    ctx = _two_certified_hydrants(api)
    system_id = ctx["system"]["id"]
    system = get_success_data(api.get_water_supply_system(system_id, ANALYST))
    assert system["active_certified_flow_gpm"] == 3801
    assert system["creditworthy_hydrant_count"] == 2
    set_hydrant_status(api, system_id, ctx["hydrants"][0]["id"], "OUT_OF_SERVICE")
    system = get_success_data(api.get_water_supply_system(system_id, ANALYST))
    assert system["active_certified_flow_gpm"] == 1629, "only hydrant B (1629) remains active"
    assert system["creditworthy_hydrant_count"] == 1


def test_hydrant_reactivation_restores_system_aggregates(api):
    """PRD §3.4: "Toggling a hydrant between `ACTIVE` and `OUT_OF_SERVICE` —
    again only while the data window is open — immediately recomputes them:
    `active_certified_flow_gpm`, the sum of `max_flow_gpm` over `ACTIVE`
    hydrants that hold a certified flow test, and
    `creditworthy_hydrant_count`, the count of `ACTIVE` hydrants whose
    `max_flow_gpm` is at least 1000 gallons per minute."

    Design: Difficulty/compensating_invariant/hydrant_outage_reactivation_flow_conservation
    """
    ctx = _two_certified_hydrants(api)
    system_id = ctx["system"]["id"]
    hydrant_a = ctx["hydrants"][0]["id"]
    set_hydrant_status(api, system_id, hydrant_a, "OUT_OF_SERVICE")
    drained = get_success_data(api.get_water_supply_system(system_id, ANALYST))
    assert drained["active_certified_flow_gpm"] == 1629
    assert drained["creditworthy_hydrant_count"] == 1
    set_hydrant_status(api, system_id, hydrant_a, "ACTIVE")
    restored = get_success_data(api.get_water_supply_system(system_id, ANALYST))
    assert restored["active_certified_flow_gpm"] == 3801, "compensating action restores the aggregate exactly"
    assert restored["creditworthy_hydrant_count"] == 2


def test_alternate_supply_insufficient_returns_error(api):
    """PRD §3.4: "A `FieldAnalyst` certifies the alternate supply during
    `FIELD_VERIFICATION` or `SCORING`, but only when the attested shuttle
    capacity is greater than zero and at least one alternate site exists;
    otherwise the verification is rejected with
    `ERR_ALTERNATE_SUPPLY_INSUFFICIENT` (HTTP 422)."

    Design: Corner/validations/alternate_supply_insufficient_returns_error
    """
    ctx = setup_scoring_cycle(
        api, name="NoAlt", rural_area_pct=80, target_state="FIELD_VERIFICATION",
    )
    system_id = ctx["system"]["id"]
    resp = api.verify_alternate_supply(system_id, make_field_analyst_headers())
    validate_error(resp, ApiErrorId.ERR_ALTERNATE_SUPPLY_INSUFFICIENT)
    system = get_success_data(api.get_water_supply_system(system_id, ANALYST))
    assert system["alternate_verified"] is False
