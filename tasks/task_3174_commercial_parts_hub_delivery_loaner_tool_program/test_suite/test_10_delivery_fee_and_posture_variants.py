"""The two-variant delivery fee and the two-variant account posture."""

from datetime import datetime, timedelta, timezone

from test_helpers import (
    advance_order_to,
    advance_order_to_delivered,
    api_client,
    confirm_order,
    create_account,
    create_hub,
    get_success_data,
    reload_account,
    set_clock,
    setup_satellite_with_part,
    stock,
    write_simple_order,
)

_ISO = "%Y-%m-%dT%H:%M:%S.%fZ"


def _parse(instant: str) -> datetime:
    return datetime.strptime(instant, _ISO).replace(tzinfo=timezone.utc)


def _format(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _deliver_on_its_own_route(account_id: str, items: list, driver_id: str,
                              route_code: str) -> dict:
    """Deliver an order through a route of its own, so driver conflicts never arise."""
    return advance_order_to_delivered(account_id, items, driver_id=driver_id,
                                      route_code=route_code)


def test_delivery_fee_is_zero_on_a_hub_route_when_the_service_level_is_exactly_hub_daily(
        api, sales_rep_headers, parts_manager_headers):
    """PRD §3.4: "Delivery is free when the order's `fulfillment_route` is exactly
    `STORE`, or when the route is exactly `HUB` and the account's
    `delivery_service_level` is exactly `HUB_DAILY`."

    Design: Difficulty/dual_variant_calc/delivery_fee_point_of_sale_vs_final_actual
    """
    set_clock("2026-09-01T08:00:00.000Z")
    hub = create_hub()
    store, part, _inv = setup_satellite_with_part(part_sku="PLUG-100",
                                                  list_price_cents=1673, hub=hub,
                                                  on_hand_units=0)
    stock(hub["id"], part["id"], 20)
    account = create_account(store["id"], delivery_service_level="HUB_DAILY")

    order = write_simple_order(account["id"], part["id"], quantity=1)

    assert order["fulfillment_route"] == "HUB", (
        "the satellite holds none of the part, so band 1 fails and band 2 selects the hub"
    )
    assert order["delivery_fee_cents"] == 0, (
        "route HUB with delivery_service_level exactly HUB_DAILY is the free-delivery clause"
    )


def test_delivery_fee_is_the_full_charge_on_an_identical_hub_route_for_a_near_miss_level(
        api, sales_rep_headers, parts_manager_headers):
    """PRD §3.4: "The comparison is exact-string on both sides: a service level
    whose name merely resembles `HUB_DAILY` does not satisfy the free-delivery
    clause, and neither does a route that differs from `STORE` or `HUB` by more
    than casing."
    PRD §3.4: "When delivery is not free, the fee is the full 795 cents."

    Design: Difficulty/dual_variant_calc/delivery_fee_point_of_sale_vs_final_actual
    """
    set_clock("2026-09-01T08:00:00.000Z")
    hub = create_hub()
    store, part, _inv = setup_satellite_with_part(part_sku="PLUG-100",
                                                  list_price_cents=1673, hub=hub,
                                                  on_hand_units=0)
    stock(hub["id"], part["id"], 20)
    account = create_account(store["id"], delivery_service_level="DELIVERY_DESK")

    order = write_simple_order(account["id"], part["id"], quantity=1)

    assert order["fulfillment_route"] == "HUB", (
        "the routing input is identical to the HUB_DAILY case"
    )
    assert order["delivery_fee_cents"] == 795, (
        "DELIVERY_DESK is not HUB_DAILY, so the exact-string free-delivery clause does not hold"
    )


def test_delivery_fee_point_of_sale_figure_stands_through_allocation(
        api, sales_rep_headers, parts_manager_headers, driver_headers):
    """PRD §3.4: "The fee is read at draft and confirmation as a point-of-sale
    quote, and read again at delivery as the final actual; the two readings are
    equal unless the confirmed source store differs from the delivered source
    store"
    PRD §3.4: "The fee is not recomputed at allocation and not recomputed at
    delivery, so the point-of-sale figure is what stands unless the source
    itself moved."

    Design: Difficulty/dual_variant_calc/delivery_fee_point_of_sale_vs_final_actual
    """
    set_clock("2026-09-01T08:00:00.000Z")
    hub = create_hub()
    store, part, _inv = setup_satellite_with_part(part_sku="PLUG-100",
                                                  list_price_cents=1673, hub=hub,
                                                  on_hand_units=0)
    stock(hub["id"], part["id"], 20)
    account = create_account(store["id"], delivery_service_level="HUB_DAILY")

    order = write_simple_order(account["id"], part["id"], quantity=1)
    quoted = order["delivery_fee_cents"]
    assert quoted == 0

    confirmed = confirm_order(order["id"], account["id"])
    assert confirmed["delivery_fee_cents"] == quoted

    allocated = advance_order_to(order["id"], account["id"], "ALLOCATED")
    assert allocated["delivery_fee_cents"] == quoted, (
        "the fee is not recomputed at allocation"
    )

    delivered = _deliver_on_its_own_route(account["id"], order["line_items"],
                                          "drv-fee", "R-FEE")
    assert delivered["order"]["delivery_fee_cents"] == quoted, (
        "the source store did not move, so the final actual equals the point-of-sale quote"
    )


def test_account_posture_reports_credit_suspended_for_an_aged_receivable(
        api, sales_rep_headers, credit_analyst_headers):
    """PRD §2.6: "When `receivable_balance_cents` is above zero and the account's
    oldest `PartOrder.delivered_payment_due_at` falls strictly earlier than the
    logical clock minus the sum of `credit_terms_days` and a 30-day aging grace,
    the posture derives to `CREDIT_SUSPENDED`."

    Design: Difficulty/dual_variant_calc/account_posture_aging_first_vs_exposure_first
    """
    set_clock("2026-09-01T08:00:00.000Z")
    store, part, _inv = setup_satellite_with_part(part_sku="AGING-1",
                                                  list_price_cents=200000)
    account = create_account(store["id"], credit_limit_cents=1000000,
                             credit_terms_days=30,
                             delivery_service_level="SHOP_DELIVERY")
    delivered = _deliver_on_its_own_route(account["id"],
                                          [{"part_id": part["id"], "quantity": 1}],
                                          "drv-age", "R-AGE")
    assert delivered["order"]["status"] == "DELIVERED"

    due_at = _parse(delivered["order"]["delivered_payment_due_at"])
    # The clock must be strictly past `due_at + credit_terms_days (30) + grace (30)`.
    set_clock(_format(due_at + timedelta(days=60, seconds=1)))

    posture = get_success_data(
        api_client.get_account_posture(account["id"], credit_analyst_headers))
    assert posture["account_posture"] == "CREDIT_SUSPENDED"
    assert posture["receivable_balance_cents"] == delivered["order"]["parts_subtotal_cents"]


def test_account_posture_is_strictly_earlier_so_the_exact_boundary_stays_open(
        api, sales_rep_headers, credit_analyst_headers):
    """PRD §2.6: "If that oldest due instant is exactly the allowed span before
    the clock, the account is not suspended — the test is strictly earlier."

    Design: Difficulty/dual_variant_calc/account_posture_aging_first_vs_exposure_first
    """
    set_clock("2026-09-01T08:00:00.000Z")
    store, part, _inv = setup_satellite_with_part(part_sku="AGING-1",
                                                  list_price_cents=4000)
    account = create_account(store["id"], credit_terms_days=90,
                             delivery_service_level="SHOP_DELIVERY")
    delivered = _deliver_on_its_own_route(account["id"],
                                          [{"part_id": part["id"], "quantity": 1}],
                                          "drv-bnd", "R-BND")
    due_at = _parse(delivered["order"]["delivered_payment_due_at"])

    # Exactly credit_terms_days (90) + the 30-day grace before the clock.
    set_clock(_format(due_at + timedelta(days=120)))
    at_boundary = get_success_data(
        api_client.get_account_posture(account["id"], credit_analyst_headers))
    assert at_boundary["account_posture"] != "CREDIT_SUSPENDED", (
        "the exact boundary is not a suspension: the comparison is strictly earlier"
    )

    # One second later the same account does suspend, so the boundary is exact.
    set_clock(_format(due_at + timedelta(days=120, seconds=1)))
    past_boundary = get_success_data(
        api_client.get_account_posture(account["id"], credit_analyst_headers))
    assert past_boundary["account_posture"] == "CREDIT_SUSPENDED"


def test_account_posture_is_suspended_rather_than_held_when_both_conditions_hold(
        api, sales_rep_headers, credit_analyst_headers):
    """PRD §2.6: "`ON_HOLD` is only ever set by the hold operation and only ever
    cleared by the release operation."
    PRD §3.8: "the posture read returns the account's `account_posture`, its
    `credit_exposure_cents`, its `receivable_balance_cents`, the `oldest_due_at`
    instant driving the aging test, and the `status_needed` instant at which the
    account would fall due under the test, and reading it does not mutate
    anything."

    Design: Difficulty/dual_variant_calc/account_posture_aging_first_vs_exposure_first
    """
    set_clock("2026-09-01T08:00:00.000Z")
    store, part, _inv = setup_satellite_with_part(part_sku="AGING-1",
                                                  list_price_cents=200000)
    account = create_account(store["id"], credit_limit_cents=1000,
                             credit_terms_days=30,
                             delivery_service_level="SHOP_DELIVERY")
    delivered = _deliver_on_its_own_route(account["id"],
                                          [{"part_id": part["id"], "quantity": 1}],
                                          "drv-both", "R-BOTH")
    due_at = _parse(delivered["order"]["delivered_payment_due_at"])
    set_clock(_format(due_at + timedelta(days=60, seconds=1)))

    before = reload_account(account["id"])
    posture = get_success_data(
        api_client.get_account_posture(account["id"], credit_analyst_headers))
    after = reload_account(account["id"])

    assert posture["account_posture"] == "CREDIT_SUSPENDED", (
        "the aging test alone yields CREDIT_SUSPENDED; ON_HOLD is only ever set by the hold operation"
    )
    assert posture["receivable_balance_cents"] == 200000
    assert posture["receivable_balance_cents"] > before["credit_limit_cents"], (
        "the exposure condition also holds, yet the posture is not ON_HOLD"
    )
    assert posture["oldest_due_at"] == delivered["order"]["delivered_payment_due_at"]
    assert after["account_posture"] != "ON_HOLD"
    assert after["version"] == before["version"], "the posture read is a pure read"