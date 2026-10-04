"""The suspension cascade and the delivery-confirmation cascade."""
from test_helpers import api_client, validate_success
from test_helpers.fixtures import (
    FUEL_COORDINATOR,
    OPERATOR,
    SERVICE_ENGINEER,
    dispatch_delivery,
    get_ppa,
    get_service_plan,
    get_site,
    schedule_delivery,
    set_clock,
    setup_active_ppa,
)


def test_freezing_a_site_suspends_its_contract_and_its_service_plan():
    """PRD §2.5: "Every contract hosted at that site
    in `PPA_ACTIVE` moves to `PPA_SUSPENDED` — a reachable state, not a terminal one".
    PRD §2.5: "Every service plan belonging to a suspended contract that is in `SERVICE_ACTIVE` or
    `SERVICE_MAINTENANCE_WINDOW_OPEN` moves to `SERVICE_SUSPENDED`, which releases its
    `radius_buffer_m` back to the site and forces a recomputation of the site's
    `clearance_zone_used`."

    Design: Difficulty/transitive_cascade/site_freeze_cascade_reaches_plan_and_replacement_stage
    """
    ctx = setup_active_ppa()
    plan_id = ctx["plan_id"]
    validate_success(
        api_client.schedule_replacement(ctx["ppa_id"], plan_id, SERVICE_ENGINEER)
    )

    validate_success(
        api_client.freeze_site(ctx["site_id"], OPERATOR, "GRID_INTERCONNECT_FAILURE")
    )

    site = get_site(ctx["site_id"])
    ppa = get_ppa(ctx["ppa_id"])
    plan = get_service_plan(ctx["ppa_id"], plan_id)

    assert site["status"] == "SITE_SUSPENDED"
    assert ppa["state"] == "PPA_SUSPENDED", (
        f"the freeze must suspend the hosted contract; got {ppa['state']}"
    )
    assert plan["lifecycle_state"] == "SERVICE_SUSPENDED", (
        f"the plan is suspended by its contract, not by the original request; got "
        f"{plan['lifecycle_state']}"
    )


def test_freezing_a_site_blocks_the_scheduled_replacement_stage():
    """PRD §3.7: "When a site is frozen, every plan whose stage is `REPLACEMENT_SCHEDULED` moves to
    `REPLACEMENT_BLOCKED`".

    Design: Difficulty/transitive_cascade/site_freeze_cascade_reaches_plan_and_replacement_stage
    """
    ctx = setup_active_ppa()
    plan_id = ctx["plan_id"]
    validate_success(
        api_client.schedule_replacement(ctx["ppa_id"], plan_id, SERVICE_ENGINEER)
    )

    validate_success(
        api_client.freeze_site(ctx["site_id"], OPERATOR, "GRID_INTERCONNECT_FAILURE")
    )

    plan = get_service_plan(ctx["ppa_id"], plan_id)
    assert plan["module_replacement_stage"] == "REPLACEMENT_BLOCKED", (
        f"the hardware axis is blocked by the freeze; got {plan['module_replacement_stage']}"
    )


def test_freezing_a_drawing_site_closes_its_resource_dimension():
    """PRD §2.5: "When the reason is `GRID_INTERCONNECT_FAILURE`,
    the site's own `lifecycle_state` moves from `RESOURCE_DRAWING` to `RESOURCE_CLOSED`, because
    an interconnect that has failed is no longer a resource the site can draw against."

    Design: Difficulty/transitive_cascade/site_freeze_cascade_reaches_plan_and_replacement_stage
    """
    ctx = setup_active_ppa()
    drawing = get_site(ctx["site_id"])
    assert drawing["lifecycle_state"] == "RESOURCE_DRAWING", (
        "activation moves the facility into draw mode; got "
        f"{drawing['lifecycle_state']}"
    )

    validate_success(
        api_client.freeze_site(ctx["site_id"], OPERATOR, "GRID_INTERCONNECT_FAILURE")
    )

    after = get_site(ctx["site_id"])
    assert after["lifecycle_state"] == "RESOURCE_CLOSED"
    assert after["status"] == "SITE_SUSPENDED"


def test_confirming_a_delivery_rebases_the_site_fuel_index_on_the_receipted_load():
    """PRD §3.3: "the site's
    `current_avoided_fuel_cost_cents_per_therm` is set to that delivery's
    `effective_commodity_rate_cents_per_therm`, so the whole portfolio's fuel basis now reads the
    real delivery".

    Design: Difficulty/transitive_cascade/delivery_confirm_cascade_reaches_site_fuel_basis
    """
    ctx = setup_active_ppa()
    set_clock("2026-03-10T00:00:00Z")
    assert get_site(ctx["site_id"])["current_avoided_fuel_cost_cents_per_therm"] == 0, (
        "no delivery has been confirmed yet, so the avoided-cost basis reads zero"
    )

    delivery = schedule_delivery(ctx["site_id"], volume_therms=200000)
    dispatch_delivery(ctx["site_id"], delivery["id"])
    confirmed = validate_success(
        api_client.confirm_fuel_delivery(
            ctx["site_id"], delivery["id"], FUEL_COORDINATOR
        )
    )

    site = get_site(ctx["site_id"])
    assert confirmed["lifecycle_state"] == "DELIVERY_CONFIRMED"
    assert site["current_avoided_fuel_cost_cents_per_therm"] == confirmed[
        "effective_commodity_rate_cents_per_therm"
    ], "the second hop is caused by the confirm, not by the delivery creation"


def test_confirmation_opens_the_charge_and_capacity_accruals_against_the_contract():
    """PRD §3.3: "a `PpaAccrual` of type `CHARGE_ACCRUAL` is opened in `ACCRUAL_OPEN` against the
    contract that won the allocation; a second `PpaAccrual` of type `CAPACITY_ACCRUAL` is opened
    against the same contract".

    Design: Difficulty/transitive_cascade/delivery_confirm_cascade_reaches_site_fuel_basis
    """
    ctx = setup_active_ppa()
    set_clock("2026-03-10T00:00:00Z")
    delivery = schedule_delivery(ctx["site_id"], volume_therms=200000)
    dispatch_delivery(ctx["site_id"], delivery["id"])
    confirmed = validate_success(
        api_client.confirm_fuel_delivery(
            ctx["site_id"], delivery["id"], FUEL_COORDINATOR
        )
    )

    body = validate_success(
        api_client.list_accruals(OPERATOR, {"ppa_id": ctx["ppa_id"]})
    )
    accruals = body["data"] if isinstance(body, dict) and "data" in body else body
    types = sorted(a["accrual_type"] for a in accruals)

    assert confirmed["lifecycle_state"] == "DELIVERY_CONFIRMED"
    assert types == ["CAPACITY_ACCRUAL", "CHARGE_ACCRUAL"], (
        f"a confirmation opens both accruals against the winning contract; got {types}"
    )
    assert all(a["lifecycle_state"] == "ACCRUAL_OPEN" for a in accruals)