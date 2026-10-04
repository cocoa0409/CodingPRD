"""Corner queue B — section: cross_cutting_layers.

Optimistic concurrency, derived-field reconciliation and idempotency of a repeated
acceptance.
"""
import pytest

from test_helpers import (
    api,
    create_hub,
    create_hub_with_clock,
    create_site,
    create_region,
    create_market,
    create_route,
    create_contractor,
    create_delivery_route,
    create_stop,
    create_subscriber,
    offer_retention_action,
    accept_retention_action,
    get_subscriber,
    plan_transfer,
    hub_version,
    validate_error,
    validate_success,
    TEST_USERS,
)
from test_helpers.constants import CLOCK_2026_09_01, CLOCK_2026_09_30

ADMIN = TEST_USERS["platform_admin_headers"]
PRINT_OPS = TEST_USERS["print_ops_headers"]
DELIVERY = TEST_USERS["delivery_manager_headers"]
CS = TEST_USERS["customer_service_headers"]


def test_stale_hub_version_is_rejected_on_market_transfer():
    """PRD §2.8: "When a market is directed onto a receiving print site, the request
    must carry `expected_hub_version`, the client's last observed `version` of the
    owning `RegionHub`."
    PRD §2.8: "if the submitted value does not equal the hub's current `version`,
    the write is refused with `ERR_STALE_VERSION` (HTTP 412) and no side effects
    fire."

    Design: Corner/cross_cutting_layers/stale_hub_version_is_rejected_on_market_transfer
    """
    api.set_current_utc({"current_utc": CLOCK_2026_09_01}, ADMIN)
    hub = create_hub()
    site = create_site(hub["id"])
    region = create_region(hub["id"])
    market = create_market(region["id"], name="Riverton")
    other = create_market(region["id"], name="Fallow", weighted_demand_units=6000)
    create_route(site["id"], market["id"])

    stale = hub_version(hub["id"])
    fresh = hub_version(hub["id"])

    planned = plan_transfer(market["id"], site["id"], expected_version=fresh)
    assert planned["status"] == "consolidation_planned", (
        "the fresh version is accepted"
    )

    version_after = hub_version(hub["id"])
    assert version_after >= fresh + 1, (
        f"the successful plan-transfer alone advances the version: {fresh} -> "
        f"{version_after}"
    )

    # The stale token now differs from the live version.
    stale_response = api.plan_market_transfer(
        other["id"],
        {"receiving_print_site_id": site["id"],
         "expected_hub_version": stale - 1},
        PRINT_OPS,
    )
    error = validate_error(stale_response, "ERR_STALE_VERSION")
    assert stale_response.status_code == 412, (
        f"a stale version carries HTTP 412, got {stale_response.status_code}"
    )
    assert error["error_id"] == "ERR_STALE_VERSION"


def test_derived_demand_weights_are_reconciled_on_frequency_apply():
    """PRD §3.7: "the market's `weighted_demand_units` is rescored to the former
    weight multiplied by the new frequency and divided by the former frequency,
    rounded half up to a whole number of units."
    PRD §3.8: "The region's `region_need_score` is the summed `weighted_demand_units`
    of its member markets — counting only markets in `active`,
    `consolidation_planned` or `transfer_in_progress`".

    Design: Corner/cross_cutting_layers/derived_demand_weights_are_reconciled_on_frequency_apply
    """
    api.set_current_utc({"current_utc": CLOCK_2026_09_01}, ADMIN)
    hub = create_hub()
    region = create_region(hub["id"])
    market = create_market(region["id"], name="Riverton", weighted_demand_units=7000,
                           print_edition_per_week=7)
    contractor = create_contractor(hub["id"])
    delivery_route = create_delivery_route(contractor["id"], market["id"])
    stop = create_stop(delivery_route["id"], market["id"], stop_code="S1")
    subscriber = create_subscriber(stop["id"], subscriber_ref="SUB-FREQ",
                                   remaining_print_issues=30,
                                   paid_through_utc="2027-06-01T00:00:00Z")
    assert subscriber["offer_recommendation"] in (
        "PRINT_CREDIT", "DIGITAL_UPGRADE", "FULL_REFUND")

    validate_success(api.open_frequency_change(
        market["id"], {"target_print_edition_per_week": 3}, PRINT_OPS), 200)
    validate_success(api.dispatch_frequency_notices(market["id"], PRINT_OPS), 200)
    # §3.7: the apply is *doubly* guarded -- 14 calendar days must elapse after the
    # notices went out, so the clock has to move before the reduction can land.
    validate_success(api.set_current_utc(
        {"current_utc": "2026-09-15T00:00:00Z"}, ADMIN), 200)

    applied = validate_success(api.apply_frequency_change(market["id"], PRINT_OPS), 200)

    assert applied["print_edition_per_week"] == 3
    assert applied["frequency_change_status"] == "applied"
    assert applied["weighted_demand_units"] == 3000, (
        f"7000 rescaled by 3/7 is 3000, got {applied['weighted_demand_units']}"
    )

    regions = validate_success(api.list_regions(hub["id"], PRINT_OPS), 200)
    assert regions[0]["region_need_score"] == 3.00, (
        f"the denormalized need score must be reconciled, got "
        f"{regions[0]['region_need_score']}"
    )


def test_idempotency_of_repeated_retention_acceptance():
    """PRD §3.6: "acceptance of an action that is `accepted`, `expired` or
    `cancelled` is refused with `ERR_RETENTION_ALREADY_SETTLED` (HTTP 409)."
    PRD §3.6: "Acceptance moves the action to `accepted` and returns the parent
    contract to `active` with `offer_status` `accepted`."

    Design: Corner/cross_cutting_layers/idempotency_of_repeated_retention_acceptance
    """
    api.set_current_utc({"current_utc": CLOCK_2026_09_01}, ADMIN)
    hub = create_hub()
    region = create_region(hub["id"])
    market = create_market(region["id"])
    contractor = create_contractor(hub["id"])
    delivery_route = create_delivery_route(contractor["id"], market["id"])
    stop = create_stop(delivery_route["id"], market["id"], stop_code="S1")
    subscriber = create_subscriber(stop["id"], subscriber_ref="SUB-IDEM",
                                   remaining_print_issues=40,
                                   paid_through_utc="2027-06-01T00:00:00Z")

    action = offer_retention_action(subscriber["id"])
    first = accept_retention_action(action["id"])
    assert first["status"] == "accepted"

    duplicate = api.accept_retention_action(action["id"], CS)
    error = validate_error(duplicate, "ERR_RETENTION_ALREADY_SETTLED")
    assert duplicate.status_code == 409, (
        f"the duplicate carries HTTP 409, got {duplicate.status_code}"
    )
    assert error["error_id"] == "ERR_RETENTION_ALREADY_SETTLED"

    contract = get_subscriber(subscriber["id"])
    assert contract["status"] == "active", (
        f"the duplicate changed nothing, got {contract['status']}"
    )