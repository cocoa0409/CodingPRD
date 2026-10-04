"""Suspending an associate cascades four levels down to the promotion."""

from test_helpers import (
    api_client,
    clerk_headers,
    create_sub_ticket_payload,
    get_success_data,
    manager_headers,
    platform_admin_headers,
    produce_batch,
    set_clock,
    setup_deli_master_data,
    setup_price_file,
    setup_promo_bread_chain,
    validate_success,
)


def _setup_halting_scenario():
    """A store whose only slicing certification belongs to A1, a delivered bread
    order covering the promotion, and one TICKETED ticket reserving 12 rolls."""
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(
        capacity=420, store_number="101", store_name="Store One", slicer_count=3,
        clerk_allergy_set=("MILK", "WHEAT"),
    )
    extra_clerk = get_success_data(
        api_client.create_associate(
            {"store_id": master.s, "employee_number": "E-1005", "full_name": "Eve Five",
             "primary_role": "DELI_CLERK"},
            platform_admin_headers(),
        )
    )
    assert extra_clerk["status"] == "ACTIVE"
    promotion, order = setup_promo_bread_chain(
        master.s, master.b1["id"], master.j1["id"], forecast_uplift_pct=0.2,
        trailing_baseline_units=600, committed_units=816, coordinator_id=master.a3["id"],
    )
    produce_batch(master.s, master.j4["id"], master.a1["id"], "B-001", 20, produced_lbs=20,
                  slicer_id=master.slicers[0]["id"])
    produce_batch(master.s, master.j2["id"], master.a1["id"], "B-002", 50, produced_lbs=50,
                  slicer_id=master.slicers[1]["id"])

    ticket = get_success_data(
        api_client.create_sub_ticket(
            create_sub_ticket_payload(
                store_id=master.s,
                deli_item_id=master.j1["id"],
                bread_deli_item_id=master.b1["id"],
                order_channel="DIGITAL",
                lines=[{"deli_item_id": master.j2["id"], "half_lb_units": 3, "line_sequence_number": 1}],
            ),
            clerk_headers(master.a1["id"]),
        )
    )
    ticketed = get_success_data(
        api_client.ticket_sub_ticket(ticket["id"], clerk_headers(master.a1["id"]))
    )
    return master, promotion, order, ticketed


def test_suspension_halts_the_store_and_revokes_the_certification():
    """PRD §3.8: "The associate moves to `SUSPENDED`. Every certification they hold
    moves to `REVOKED`. The store's `certified_slicer_operator_count` is
    recomputed, and if that count has reached zero the store's `HALT` transition
    fires."

    Design: Difficulty/transitive_cascade/associate_suspension_cascade_to_promotion_degrade
    """
    master, _, _, _ = _setup_halting_scenario()
    result = validate_success(
        api_client.suspend_associate(
            master.a1["id"], "CERTIFICATION_EXPIRED", manager_headers(master.a3["id"])
        )
    )
    assert result["status"] == "SUSPENDED"

    cert = validate_success(
        api_client.get_certification(master.c_a1_sl["id"], platform_admin_headers())
    )
    assert cert["status"] == "REVOKED"

    store = validate_success(api_client.get_store(master.s, platform_admin_headers()))
    assert store["certified_slicer_operator_count"] == 0
    assert store["posture"] == "HALT", "the halt fires once the certified-operator count reaches zero"
    assert store["posture_reason"] == "CERTIFICATION_TRIGGERED"


def test_suspension_abandons_the_ticket_and_releases_its_bread_reserve():
    """PRD §3.8: "Every non-terminal sub ticket in the store then moves to
    `ABANDONED`, each abandoned ticket releases the bread units it was reserving,
    and each affected promotion is pushed to `DEGRADED` when its units-short
    count reaches zero."
    PRD §3.5: "The units-short figure is `required_units` minus `committed_units`,
    clamped at a minimum of zero, plus `reserved_units` minus `committed_units`,
    also clamped at a minimum of zero."

    Design: Difficulty/transitive_cascade/associate_suspension_cascade_to_promotion_degrade
    """
    master, promotion, order, ticket = _setup_halting_scenario()

    reserved_before = validate_success(
        api_client.get_bread_order(order["id"], platform_admin_headers())
    )
    assert reserved_before["reserved_units"] == 1, (
        "a TICKETED ticket reserves one roll against the order"
    )

    validate_success(
        api_client.suspend_associate(
            master.a1["id"], "CERTIFICATION_EXPIRED", manager_headers(master.a3["id"])
        )
    )

    ticket_after = validate_success(api_client.get_sub_ticket(ticket["id"], platform_admin_headers()))
    assert ticket_after["status"] == "ABANDONED"

    order_after = validate_success(api_client.get_bread_order(order["id"], platform_admin_headers()))
    assert order_after["reserved_units"] == 0
    assert order_after["unreserved_required_units"] == order_after["committed_units"]
    assert order_after["required_units"] == order_after["committed_units"], (
        "the commitment meets the forecast, so units_short is zero"
    )

    promotion_after = validate_success(
        api_client.get_promotion(promotion["id"], platform_admin_headers())
    )
    assert promotion_after["status"] == "ACTIVE", (
        "units_short returned to zero once the abandonment released the reserved rolls"
    )