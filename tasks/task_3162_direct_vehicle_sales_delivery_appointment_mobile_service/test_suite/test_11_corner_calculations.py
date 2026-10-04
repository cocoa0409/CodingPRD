"""Corner coverage: the numeric rules behind money and delivery windows."""
from test_helpers import (
    canonical_instant,
    TEST_USERS,
    create_center,
    create_verified_buyer,
    get_order,
    get_success_data,
    set_clock,
    walk_order_to_at_delivery_center,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ADVISOR = TEST_USERS["delivery_advisor_headers"]


def test_delivery_fee_leaves_the_total_when_the_buyer_pays_up_front(api):
    """PRD §3.6: "For each `ACCEPTED` appraisal on the order an entry of type
    `TRADE_IN_CREDIT` for the positive `net_credit_cents` is written; when no
    appraisal was accepted, no such entry is written."
    PRD §3.6: "The order's `order_total_due_cents` is recomputed in its `final`
    variant"

    Design: Corner/calculations/delivery_fee_leaves_the_total_when_the_buyer_pays_up_front
    """
    set_clock()
    ctx = walk_order_to_at_delivery_center(options=[
        {"option_sku": "PAINT_WHITE", "option_category": "PAINT", "price_cents": 100000}])
    order = get_order(ctx["order"]["id"])
    appointment = get_success_data(api.book_delivery_appointment(
        {"order_id": order["id"], "delivery_center_id": ctx["center"]["id"],
         "delivery_mode": "CENTER",
         "scheduled_start": "2026-09-24T15:00:00Z",
         "scheduled_end": "2026-09-24T16:00:00Z",
         "expected_order_version": order["version"]},
        ADVISOR))
    get_success_data(api.confirm_delivery_appointment(appointment["id"], ADVISOR))
    order = get_order(order["id"])

    completed = get_success_data(api.complete_delivery_appointment(
        appointment["id"],
        {"acceptance_inspection_result": "CLEAN", "documented_issues": [],
         "expected_order_version": order["version"]},
        ADVISOR))
    assert completed["status"] == "DELIVERED"
    assert completed["order_total_due_cents"] == 4934000, (
        "with no accepted appraisal the final variant subtracts nothing"
    )

    buyer = get_success_data(api.get_buyer(ctx["buyer"]["id"], ADMIN))
    assert buyer["order_credit_balance_cents"] == 22500, (
        "25000-cent order fee settlement less the 2500-cent delivery-fee charge"
    )


def test_doc_fee_cap_of_zero_suppresses_the_documentation_fee(api):
    """PRD §2.4: "`doc_fee_cap_cents` is the statutory ceiling on the documentation
    fee, and the value 0 means that no documentation fee may be charged at all."
    PRD §3.7: "Third a documentation fee, which is the statutory ceiling
    `doc_fee_cents` of 7500 cents capped by the regime's `doc_fee_cap_cents` — the
    smaller of the two — with the special case that a regime whose
    `doc_fee_cap_cents` is 0 yields a documentation fee of 0."

    Design: Corner/calculations/doc_fee_cap_of_zero_suppresses_the_documentation_fee
    """
    set_clock()
    jur = get_success_data(api.create_jurisdiction(
        {"state_code": "AZ", "direct_sales_permitted": False,
         "gallery_only_required": True, "out_of_state_delivery_required": True,
         "cooling_off_days": 5, "doc_fee_cap_cents": 0,
         "mobile_service_permitted": False, "delivery_buffer_minutes": 45,
         "allocation_window_days": 14, "transport_lead_days": 10}, ADMIN))
    get_success_data(api.enact_jurisdiction(jur["id"], ADMIN))
    center = create_center(center_name="Las Vegas Delivery", state_code="NV",
                           bay_count=3, home_delivery_radius_miles=40, van_count=1)
    config = get_success_data(api.create_configuration(
        {"model_code": "MODEL_3_LR_RWD", "base_price_cents": 2999000}, ADMIN))
    buyer = create_verified_buyer(full_name="Ana Arizona",
                                  email="ana.arizona@example.com",
                                  residency_state_code="AZ")

    order = get_success_data(api.create_order(
        {"buyer_id": buyer["id"], "configuration_id": config["id"],
         "jurisdiction_id": jur["id"], "delivery_center_id": center["id"]}, ADMIN))

    assert order["order_total_due_cents"] == 2999000 + 25000 + 0 + 2500
    assert order["delivery_readiness_posture"] == "FROZEN"


def test_estimate_input_set_excludes_superseded_rows_from_the_live_window(api):
    """PRD §3.4: "This projection is admissible only if it actually moves the
    projected window start or the projected window end"
    PRD §3.11: "The ordering is the whole point of the algorithm"
    PRD §3.4: "Estimates of an order are ordered by `created_at` ascending"

    Design: Corner/calculations/estimate_input_set_excludes_superseded_rows_from_the_live_window
    """
    set_clock()
    ctx = walk_order_to_at_delivery_center()
    order_id = ctx["order"]["id"]

    fresh = get_success_data(api.project_delivery_estimate(
        order_id, {"basis_iso8601": "2026-09-21T00:00:00Z", "window_days": 7}, ADMIN))

    rows = get_success_data(api.list_order_estimates(order_id, ADMIN))
    # The chain is placement (PROVISIONAL, superseded by allocation), allocation
    # (FIRM), and the projection just made (PROVISIONAL) — three rows in all.
    assert len(rows) == 3
    live = [e for e in rows if e["estimate_state"] in ("PROVISIONAL", "FIRM")]
    assert len(live) == 1
    assert live[0]["id"] == fresh["id"]

    live_rows = get_success_data(api.list_delivery_estimates(
        ADMIN, params={"order_id": order_id}))
    assert len(live_rows) == 3, "every row remains queryable after the supersession"
    assert sum(1 for e in live_rows
               if e["estimate_state"] in ("PROVISIONAL", "FIRM")) == 1, (
        "only the newest row defines the live window"
    )


def test_shift_days_honours_the_floor_to_whole_days(api):
    """PRD §3.4: "The `shift_days` on a new estimate is 0 when it supersedes
    nothing, and otherwise is the number of whole days, rounded down, by which the
    new window start moved past the prior estimate's window end, floored at 0 so
    that a window that moves *earlier* never produces a negative shift."
    PRD §3.4: "Before any unit is bound to the order, the projection basis is the
    current logical clock instant plus the regime's `transport_lead_days` — this is
    the estimate shown at placement — and the usable window buffer is a minimum of
    five days, with the window spanning from the basis to the basis plus five days.
    Once a unit is `ALLOCATED` to the order, the basis switches to that unit's
    `transport_eta` and the window widens to seven days."

    Design: Corner/calculations/shift_days_honours_the_floor_to_whole_days
    """
    set_clock()
    ctx = walk_order_to_at_delivery_center()
    order_id = ctx["order"]["id"]

    first = get_success_data(api.project_delivery_estimate(
        order_id, {"basis_iso8601": "2026-09-23T12:00:00Z", "window_days": 7}, ADMIN))
    assert canonical_instant(first["window_start"]) == "2026-09-23T12:00:00.000Z"
    assert first["shift_days"] == 1, "36 hours after the prior window start floors to 1"

    second = get_success_data(api.project_delivery_estimate(
        order_id, {"basis_iso8601": "2026-10-03T00:00:00Z", "window_days": 7}, ADMIN))
    assert second["shift_days"] == 2, "48 hours after the prior start floors to 2"

    order = get_order(order_id)
    assert order["estimate_shift_days_cumulative"] == 3
