"""Production runs, cancellation fees, and the return policy (PRD 3.8)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    approve_order_art,
    boot_clock,
    create_art_approved_order,
    create_completed_order,
    create_in_production_order,
    create_order,
    create_print_slot,
    create_product_line,
    create_colorway_drop,
    create_return_requested_order,
    decide_return,
    get_drop,
    get_order,
    get_slot,
    make_buyer_headers,
    make_customer_care_headers,
    request_return_payload,
    decide_return_payload,
    reserve_slot,
    set_clock,
    submit_order,
    submit_proof,
    approve_proof,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    TEST_USERS,
)

_PRODUCTION = TEST_USERS["production_lead_headers"]


def test_start_production_requires_locked_slot(api):
    """CONFIRMED -> IN_PRODUCTION is gated on the SLOT's state, not on any
    order-local field: the same call fails while the slot is OPEN and succeeds
    once it locks.

    PRD section 3.8: "Starting a run requires the order to be `ACTIVE` with its
    reservation `CONFIRMED` and the slot `LOCKED` — starting against a slot
    that is not locked is rejected with `ERR_SLOT_NOT_LOCKED`"

    Design: Difficulty/cross_entity_state_dependency/start_production_requires_locked_slot
    """
    bundle = create_art_approved_order(
        buyer_ref="buyer-lock",
        line_overrides={"name": "Mug 14 oz", "base_sku": "MUG14",
                        "base_custom_price_cents": 2600, "map_price_cents": 3199,
                        "min_custom_quantity": 5},
        slot_overrides={"station_code": "L-3",
                        "window_start": "2026-09-14T09:00:00Z",
                        "window_end": "2026-09-14T11:00:00Z",
                        "capacity_minutes": 120},
        quantity=5)
    order_id = bundle["order"]["id"]
    assert bundle["order"]["reservation_status"] == "CONFIRMED"

    resp_open = api.start_production(order_id, _PRODUCTION)
    validate_error(resp_open, ApiErrorId.ERR_SLOT_NOT_LOCKED)

    validate_success(api.lock_print_slot(bundle["slot"]["id"], _PRODUCTION))
    assert get_slot(bundle["slot"]["id"])["status"] == "LOCKED"

    started = validate_success(api.start_production(order_id, _PRODUCTION))
    assert started["schedule_status"] == "IN_PRODUCTION", \
        "only the slot's state changed between the two attempts"


def test_qc_fail_rework_loop_then_pass_captures_payment(api):
    """A FAIL loops the schedule back to CONFIRMED and counts the rework; the
    later PASS completes the order, captures payment, and consumes the
    reservation (minutes stay booked).

    PRD section 3.8: "A `PASS` moves the schedule to `COMPLETE`, moves the
    reservation to `CONSUMED` — the minutes stay booked, because the capacity
    was genuinely spent — captures payment by moving `payment_status` from
    `AUTHORIZED` to `CAPTURED` for the `final_quote_cents` amount, and stamps
    `completed_at` with the logical clock, which anchors both the warranty and
    the return windows. A `FAIL` is the rework loop: the schedule falls back
    from `IN_PRODUCTION` to `CONFIRMED` and the order's `qc_fail_count`
    increments."

    Design: Corner/state_machines/qc_fail_rework_loop_then_pass_captures_payment
    """
    bundle = create_in_production_order()
    order_id, slot_id = bundle["order"]["id"], bundle["slot"]["id"]

    failed = validate_success(api.complete_production(
        order_id, {"qc_outcome": "FAIL"}, _PRODUCTION))
    assert failed["schedule_status"] == "CONFIRMED"
    assert failed["qc_fail_count"] == 1
    assert failed["payment_status"] == "AUTHORIZED"

    validate_success(api.start_production(order_id, _PRODUCTION))
    done = validate_success(api.complete_production(
        order_id, {"qc_outcome": "PASS"}, _PRODUCTION))
    assert done["schedule_status"] == "COMPLETE"
    assert done["payment_status"] == "CAPTURED"
    assert done["reservation_status"] == "CONSUMED"
    assert done.get("completed_at"), "completion stamps the logical clock"
    assert get_slot(slot_id)["booked_minutes"] == 40, \
        "CONSUMED minutes remain booked — the capacity was spent"


def test_cancel_or_release_in_production_returns_order_in_production(api):
    """Once IN_PRODUCTION, cancel is rejected with ERR_ORDER_IN_PRODUCTION and
    release-slot is rejected as a state error; nothing moves.

    PRD section 3.8: "Cancellation is available to the `Buyer` and to a
    `PlatformAdmin` while the order is `ACTIVE` and its schedule is
    `UNSCHEDULED`, `RESERVED`, or `CONFIRMED`; an order already `IN_PRODUCTION`
    rejects cancellation with `ERR_ORDER_IN_PRODUCTION`"
    PRD section 3.7: "Releasing a reservation is the inverse act by the
    `Buyer`, available from `RESERVED` or `CONFIRMED` schedules on an `ACTIVE`
    order with the reservation in `HELD`, `CONFIRMED`, or `WAITLISTED`."
    (The PRD names the exact error only for cancel; the release rejection is
    the same state gate, so either state error id satisfies the contract.)

    Design: Corner/state_machines/cancel_or_release_in_production_returns_order_in_production
    """
    bundle = create_in_production_order()
    order_id, slot_id = bundle["order"]["id"], bundle["slot"]["id"]

    resp_cancel = api.cancel_order(order_id, make_buyer_headers("buyer-std"))
    validate_error(resp_cancel, ApiErrorId.ERR_ORDER_IN_PRODUCTION)

    resp_release = api.release_slot(order_id, make_buyer_headers("buyer-std"))
    validate_error_is_one_of(resp_release, [
        ApiErrorId.ERR_ORDER_IN_PRODUCTION,
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
    ])

    order = get_order(order_id)
    assert order["order_state"] == "ACTIVE"
    assert order["schedule_status"] == "IN_PRODUCTION"
    assert order["reservation_status"] == "CONFIRMED"
    assert get_slot(slot_id)["booked_minutes"] == 40, "nothing freed"


def test_cancel_after_art_approval_charges_ten_percent_fee(api):
    """Cancelling with art approved bills 10% of the final quote, voids the
    uncaptured authorization (refund 0), and releases the reservation.

    PRD section 3.8: "The cancellation fee is zero while the artwork axis is
    anything other than `ART_APPROVED`; once art is approved the fee is 10
    percent of the `final_quote_cents`, rounded half up. The refund is zero
    when payment was merely `AUTHORIZED` — the authorization is simply voided"
    PRD section 3.8: "Cancellation moves `order_state` to `CANCELLED`,
    releases any held, confirmed, or waitlisted reservation with the
    waitlist-promotion cascade of section 3.7, and moves `payment_status` to
    `REFUNDED` when it had been `AUTHORIZED` or `CAPTURED`"

    Design: Corner/endpoints/cancel_after_art_approval_charges_ten_percent_fee
    """
    bundle = create_art_approved_order()
    order_id, slot_id = bundle["order"]["id"], bundle["slot"]["id"]
    assert bundle["order"]["final_quote_cents"] == 38000
    assert get_slot(slot_id)["booked_minutes"] == 40

    cancelled = validate_success(
        api.cancel_order(order_id, make_buyer_headers("buyer-std")))
    assert cancelled["cancellation_fee_cents"] == 3800, \
        "round_half_up(38000 x 0.10)"
    assert cancelled["refund_cents"] == 0, "authorization voided, nothing captured"
    assert cancelled["order_state"] == "CANCELLED"
    assert cancelled["payment_status"] == "REFUNDED"

    slot = get_slot(slot_id)
    assert slot["booked_minutes"] == 0 and slot["available_minutes"] == 180, \
        "release cascade with an empty waitlist is a no-op for capacity"

    resp_again = api.cancel_order(order_id, make_buyer_headers("buyer-std"))
    validate_error(resp_again, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


def test_return_window_closed_at_exactly_45_days(api):
    """The 45-day return window is strict: one second before the deadline the
    request is accepted, at exactly completed_at + 45 days it is rejected.

    (Two orders are used so the accepted leg runs at the earlier clock and the
    rejected leg at the later one — the logical clock only moves forward.)

    PRD section 3.8: "A `Buyer` may request a return on an order that is
    `ACTIVE`, schedule `COMPLETE`, and payment `CAPTURED`, within 45 days of
    `completed_at` — at or after that deadline the request is rejected with
    `ERR_RETURN_WINDOW_CLOSED`."

    Design: Corner/validations/return_window_closed_at_exactly_45_days
    """
    bundle_a = create_completed_order(buyer_ref="buyer-rw-a",
                                      complete_clock="2026-09-14T11:30:00Z")
    bundle_b = create_completed_order(
        buyer_ref="buyer-rw-b",
        line_overrides={"base_sku": "RAMRW2"},
        slot_overrides={"station_code": "L-C2"},
        complete_clock="2026-09-14T11:30:00Z")
    for bundle in (bundle_a, bundle_b):
        assert bundle["order"]["completed_at"].startswith("2026-09-14T11:30")

    # One second before the deadline: accepted.
    set_clock("2026-10-29T11:29:59Z")
    ok = validate_success(api.request_return(
        bundle_b["order"]["id"],
        request_return_payload("DEFECT", 1),
        make_buyer_headers("buyer-rw-b")))
    assert ok["return_status"] == "RETURN_REQUESTED"

    # At exactly completed_at + 45 days (2026-10-29T11:30:00Z): rejected.
    set_clock("2026-10-29T11:30:00Z")
    resp = api.request_return(
        bundle_a["order"]["id"],
        request_return_payload("DEFECT", 1),
        make_buyer_headers("buyer-rw-a"))
    validate_error(resp, ApiErrorId.ERR_RETURN_WINDOW_CLOSED)


def test_buyers_remorse_approval_rejected_but_deny_allowed(api):
    """Personalized goods cannot be restocked: a BUYERS_REMORSE return can be
    requested but never approved; DENY closes it without leaking a refund.

    PRD section 3.8: "A `BUYERS_REMORSE` return is never approvable, because
    personalized goods cannot be restocked, and the attempt is rejected with
    `ERR_PERSONALIZED_NOT_RETURNABLE`."
    PRD section 3.8: "The return decision belongs to `CustomerCare`, whose
    `decision` either denies the request — landing `return_status` in
    `RETURN_DENIED` — or approves it into `RETURN_SETTLED`"

    Design: Corner/validations/buyers_remorse_approval_rejected_but_deny_allowed
    """
    bundle = create_return_requested_order(reason="BUYERS_REMORSE",
                                           affected_unit_count=2)
    order_id = bundle["order"]["id"]

    resp = api.decide_return(
        order_id,
        decide_return_payload("APPROVE", resolution="FULL_REFUND",
                              decision_notes="feeling generous"),
        make_customer_care_headers("cc-1"))
    validate_error(resp, ApiErrorId.ERR_PERSONALIZED_NOT_RETURNABLE)

    denied = decide_return(order_id, "DENY",
                           decision_notes="personalized goods are final sale")
    assert denied["return_status"] == "RETURN_DENIED"
    assert denied["refund_cents"] == 0
    assert denied["payment_status"] == "CAPTURED", "no refund leaked"


def test_return_resolution_mismatch_cases(api):
    """ARTWORK_MISMATCH admits only FULL_REFUND or REMAKE, and PARTIAL_CREDIT
    with every unit affected is rejected — the full refund then settles at
    exactly final_quote_cents.

    PRD section 3.8: "An `ARTWORK_MISMATCH` return admits only `FULL_REFUND`
    or `REMAKE`; proposing `PARTIAL_CREDIT` there is rejected with
    `ERR_RETURN_RESOLUTION_MISMATCH`. And `PARTIAL_CREDIT` requires the
    `affected_unit_count` to be strictly below the order's `quantity` — when
    every unit is affected the correct resolution is a full refund — else
    `ERR_RETURN_RESOLUTION_MISMATCH` again. A `FULL_REFUND` settles
    `refund_cents` to the full `final_quote_cents` and moves payment to
    `REFUNDED`."

    Design: Corner/validations/return_resolution_mismatch_cases
    """
    boot_clock()
    line = create_product_line()
    drop = create_colorway_drop(line["id"])
    slot = create_print_slot()  # 180 minutes, fits both orders (40 each)

    def completed(buyer_ref):
        order = create_order(line["id"], drop["id"], buyer_ref=buyer_ref,
                             quantity=10)
        submit_order(order["id"], buyer_ref)
        reserve_slot(order["id"], slot["id"], buyer_ref)
        approved = approve_order_art(order["id"], buyer_ref)
        return approved["order"]

    order_m = completed("buyer-m1")
    order_q = completed("buyer-q1")
    assert order_m["final_quote_cents"] == 38000  # 10 x 3000 + 8000, off-peak

    validate_success(api.lock_print_slot(slot["id"], _PRODUCTION))
    for order in (order_m, order_q):
        validate_success(api.start_production(order["id"], _PRODUCTION))
        validate_success(api.complete_production(
            order["id"], {"qc_outcome": "PASS"}, _PRODUCTION))

    validate_success(api.request_return(
        order_m["id"], request_return_payload("ARTWORK_MISMATCH", 5),
        make_buyer_headers("buyer-m1")))
    validate_success(api.request_return(
        order_q["id"], request_return_payload("DEFECT", 10),
        make_buyer_headers("buyer-q1")))

    resp_m = api.decide_return(
        order_m["id"],
        decide_return_payload("APPROVE", resolution="PARTIAL_CREDIT",
                              decision_notes="half-hearted"),
        make_customer_care_headers("cc-1"))
    validate_error(resp_m, ApiErrorId.ERR_RETURN_RESOLUTION_MISMATCH)

    resp_q = api.decide_return(
        order_q["id"],
        decide_return_payload("APPROVE", resolution="PARTIAL_CREDIT",
                              decision_notes="all units but partial"),
        make_customer_care_headers("cc-1"))
    validate_error(resp_q, ApiErrorId.ERR_RETURN_RESOLUTION_MISMATCH)

    settled = decide_return(order_q["id"], "APPROVE", resolution="FULL_REFUND",
                            decision_notes="full defect refund")
    assert settled["refund_cents"] == 38000
    assert settled["payment_status"] == "REFUNDED"
    assert settled["return_status"] == "RETURN_SETTLED"
    assert get_order(order_m["id"])["return_status"] == "RETURN_REQUESTED", \
        "the rejected decide leaves the return open"


def test_partial_credit_rounds_half_up_single_step(api):
    """PARTIAL_CREDIT prorates the final quote in one round-half-up step and
    never restocks the returned unit.

    PRD section 3.8: "A `PARTIAL_CREDIT` settles `refund_cents` to the
    `final_quote_cents` prorated by the affected units over the `quantity`,
    rounded half up in a single step, and moves payment to
    `PARTIALLY_REFUNDED`. In both money resolutions the goods are written off
    and never restocked — no units return to any pool."
    PRD section 2.8: "refund and cancellation-fee math performs a single
    rounding step per refund and never rounds per unit and then sums."

    Design: Corner/calculations/partial_credit_rounds_half_up_single_step
    """
    bundle = create_completed_order(
        buyer_ref="buyer-pc",
        line_overrides={"name": "Partial Credit Line", "base_sku": "RAMPC",
                        "base_custom_price_cents": 3000, "map_price_cents": 3499,
                        "min_custom_quantity": 1},
        quantity=3)
    order = bundle["order"]
    assert order["final_quote_cents"] == 17000  # 3 x 3000 + 8000, off-peak
    drop_before = get_drop(bundle["drop"]["id"])

    validate_success(api.request_return(
        order["id"], request_return_payload("DEFECT", 1),
        make_buyer_headers("buyer-pc")))
    settled = decide_return(order["id"], "APPROVE", resolution="PARTIAL_CREDIT",
                            decision_notes="one unit scuffed")
    assert settled["refund_cents"] == 5667, "round_half_up(17000 x 1 / 3)"
    assert settled["payment_status"] == "PARTIALLY_REFUNDED"
    assert settled["return_status"] == "RETURN_SETTLED"

    drop_after = get_drop(bundle["drop"]["id"])
    assert drop_after["unallocated_units"] == drop_before["unallocated_units"], \
        "the returned unit is written off, never restocked"
