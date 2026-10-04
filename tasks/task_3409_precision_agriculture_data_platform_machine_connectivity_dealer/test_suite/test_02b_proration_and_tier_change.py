"""Mid-cycle tier changes: proration math, OCC guard, and response-carried
derived values."""

from test_helpers import (
    ApiErrorId,
    activate_plan,
    add_machine,
    change_plan_tier,
    create_plan,
    read_plan,
    set_clock,
    setup_connected_machine,
    setup_org_dealer,
    validate_error,
    validate_success,
)


def _plan_activated_october_first(api, tier, proration_method="CALENDAR_DAY"):
    """Plan created under the startup clock, then activated at 2026-10-01
    (cycle anchor day 1) with the clock advanced to 2026-10-15. Returns
    (ctx, plan_id, plan_version)."""
    ctx = setup_org_dealer(api)
    machine = add_machine(ctx, api)
    plan = create_plan(ctx, api, machine["id"], tier=tier,
                       proration_method=proration_method)
    set_clock(api, "2026-10-01T00:00:00Z")
    activate_plan(ctx, api, plan["id"])
    version = read_plan(ctx, api, plan["id"])["version"]
    set_clock(api, "2026-10-15T00:00:00Z")
    return ctx, plan["id"], version


def test_proration_downgrade_yields_signed_credit(api):
    """PRD section 3.2: "The delta is the new tier's monthly price minus the
    old tier's monthly price, in cents; a downgrade yields a negative delta,
    hence a credit." and "under `CALENDAR_DAY` it is the true calendar month —
    the number of calendar days in the month containing the current instant,
    28 through 31 — with the fraction formed from the days remaining after the
    current day-of-month over that month length". STANDARD -> BASIC on October
    15: round_half_up(-30000 * 16/31) = -15484.

    Design: Corner/calculations/proration_downgrade_yields_signed_credit
    """
    ctx, plan_id, version = _plan_activated_october_first(api, "STANDARD")
    plan = change_plan_tier(
        ctx, api, plan_id, "BASIC", expected_plan_version=version
    )
    assert plan["last_proration_charge_cents"] == -15484
    assert plan["tier"] == "BASIC"
    assert plan["monthly_price_cents"] == 30000


def test_change_tier_response_carries_proration_immediately(api):
    """PRD section 3.2: "On success the proration charge is computed before the
    new tier is stored. ... The charge is the delta multiplied by the remaining
    fraction, rounded half-up to integer cents, and stored as
    `last_proration_charge_cents`. The plan's `tier` and `monthly_price_cents`
    then update". BASIC -> STANDARD on October 15 (CALENDAR_DAY):
    round_half_up(30000 * 16/31) = 15484, all visible in the change-tier
    response itself.

    Design: Corner/consistency_model/change_tier_response_carries_proration_immediately
    """
    ctx, plan_id, version = _plan_activated_october_first(api, "BASIC")
    response = api.change_data_plan_tier(
        plan_id,
        {"new_tier": "STANDARD", "expected_plan_version": version},
        headers=ctx["grower_headers"],
    )
    plan = validate_success(response, 200)
    assert plan["tier"] == "STANDARD"
    assert plan["monthly_price_cents"] == 60000
    assert plan["last_proration_charge_cents"] == 15484


def test_occ_stale_plan_version_on_change_tier(api):
    """PRD section 2.8: "Changing a data plan's tier requires
    `expected_plan_version`, carrying the client's last observed `version` of
    the plan; a mismatch is rejected with `ERR_STALE_PLAN_VERSION` (HTTP 412),
    because a prior tier change legitimately repriced the plan and the current
    writer's pricing basis is stale."

    Design: Corner/cross_cutting/occ_stale_plan_version_on_change_tier
    """
    ctx = setup_connected_machine(api)
    plan_id = ctx["plan"]["id"]
    version = read_plan(ctx, api, plan_id)["version"]

    change_plan_tier(ctx, api, plan_id, "BASIC", expected_plan_version=version)

    response = api.change_data_plan_tier(
        plan_id,
        {"new_tier": "UNLIMITED", "expected_plan_version": version},
        headers=ctx["grower_headers"],
    )
    validate_error(response, ApiErrorId.ERR_STALE_PLAN_VERSION)

    plan = read_plan(ctx, api, plan_id)
    assert plan["tier"] == "BASIC"


def test_action_endpoint_response_carries_updated_entity(api):
    """PRD section 2.2: "Unless otherwise noted, operations that create or
    modify a resource will return the created or updated resource object in the
    data field." PRD section 3.2: "Suspension — by the grower or a
    `PlatformAdmin` — moves an `ACTIVE` plan to `SUSPENDED`" and "Each of these
    transitions increments the plan's `version`."

    Design: Corner/endpoints/action_endpoint_response_carries_updated_entity
    """
    ctx = setup_connected_machine(api)
    plan_id = ctx["plan"]["id"]
    response = api.suspend_data_plan(plan_id, headers=ctx["grower_headers"])
    plan = validate_success(response, 200)
    assert response.json()["response_type"] == "object"
    assert plan["status"] == "SUSPENDED"
    assert plan["version"] == 3
