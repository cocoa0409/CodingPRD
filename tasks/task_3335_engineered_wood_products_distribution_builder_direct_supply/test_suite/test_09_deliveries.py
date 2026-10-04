"""Delivery scheduling tests: fee rounding, jobsite window containment, boom
capability, drop limits, 45-minute buffer, order-deliverability gating, and
the FAILED_ACCESS retry cycle."""
from test_helpers import (
    ApiErrorId,
    complete_delivery,
    confirm_order,
    create_active_builder,
    create_branch,
    create_job,
    create_order,
    create_product,
    create_truck_shift,
    get_delivery,
    get_order,
    get_shift,
    receive_lot,
    request_delivery,
    schedule_delivery,
    set_clock,
    setup_builder_with_job,
    setup_delivered_order,
    setup_order_confirmed,
    validate_error,
    validate_success,
)
from test_helpers import api_client as api
from test_helpers.fixtures import ACCT, CREDIT, FLEET


def _two_builder_scenario():
    """Stocked branch; two ACTIVE builders, each with a job open all day on
    2026-09-10, each with a CONFIRMED 10 mbf order."""
    product = create_product()
    branch = create_branch()
    receive_lot(branch["id"], product["id"], 100, 40000)

    out = {"product": product, "branch": branch}
    for name, state in (("1", "ID"), ("2", "WA")):
        builder = create_active_builder(9000000, f"Alpha Homes {name}", state)
        job = create_job(
            builder["id"],
            job_name=f"Lot {name}",
            access_window_start="2026-09-10T00:00:00Z",
            access_window_end="2026-09-10T23:59:59Z",
        )
        order = create_order(job["id"], branch["id"], builder["id"],
                             qty_mbf=10, unit_price_cents=100000,
                             product_id=product["id"])
        confirm_order(order["id"])
        out[f"builder{name}"] = builder
        out[f"job{name}"] = job
        out[f"order{name}"] = order
    return out


def test_delivery_fee_component_rounding_beats_sum_then_round():
    """PRD §3.7: "The fee is built from two components, each rounded half-up
    to integer cents before they are summed: the base component is 7501 cents
    times the job's placement multiplier, and the boom component — present
    only when boom_required is true — is 4003 cents times the same multiplier.
    ... Component-wise rounding then summation is pinned; rounding the
    combined amount once is the forbidden order."

    Design: Difficulty/combinatorial_formula/delivery_fee_component_rounding_beats_sum_then_round
    """
    set_clock("2026-09-01T00:00:00Z")
    scenario = setup_order_confirmed(placement_difficulty="CRANE_ASSIST")
    delivery = request_delivery(scenario["order"]["id"], boom_required=True)
    shift = create_truck_shift()
    scheduled = schedule_delivery(delivery["id"], shift["id"])

    assert scheduled["delivery_fee_cents"] == 17257, (
        "round_half_up(7501*1.5)=11252 plus round_half_up(4003*1.5)=6005; "
        f"the forbidden sum-then-round would give 17256, got {scheduled['delivery_fee_cents']}"
    )
    assert scheduled["delivery_status"] == "SCHEDULED"
    assert get_shift(shift["id"])["booked_drops"] == 1


def test_delivery_fee_standard_without_boom():
    """PRD §3.7: "the boom component — present only when boom_required is true"
    and "The multiplier is 1.0 for STANDARD, 1.25 for TIGHT_ACCESS, and 1.5
    for CRANE_ASSIST." A STANDARD, no-boom delivery prices at exactly the
    7501-cent base.

    Design: Difficulty/combinatorial_formula/delivery_fee_component_rounding_beats_sum_then_round
    """
    set_clock("2026-09-01T00:00:00Z")
    scenario = setup_order_confirmed()  # STANDARD placement by default
    delivery = request_delivery(scenario["order"]["id"], boom_required=False)
    shift = create_truck_shift()
    scheduled = schedule_delivery(delivery["id"], shift["id"])
    assert scheduled["delivery_fee_cents"] == 7501


def test_jobsite_window_closed_containment_allows_touching_endpoints():
    """PRD §3.7: "The delivery window must also lie within the job's access
    window [access_window_start, access_window_end] under closed containment —
    touching either endpoint is allowed — else
    ERR_JOBSITE_ACCESS_WINDOW_VIOLATION (HTTP 400)."

    Design: Difficulty/resource_temporal_overlap/jobsite_window_closed_containment_allows_touching_endpoints
    """
    set_clock("2026-09-01T00:00:00Z")
    product = create_product()
    branch = create_branch()
    receive_lot(branch["id"], product["id"], 100, 40000)
    builder = create_active_builder(9000000)
    job = create_job(
        builder["id"],
        access_window_start="2026-09-10T09:00:00Z",
        access_window_end="2026-09-10T15:00:00Z",
    )
    o1 = create_order(job["id"], branch["id"], builder["id"], qty_mbf=10,
                      unit_price_cents=100000, product_id=product["id"])
    confirm_order(o1["id"])
    o2 = create_order(job["id"], branch["id"], builder["id"], qty_mbf=10,
                      unit_price_cents=100000, product_id=product["id"])
    confirm_order(o2["id"])

    d1 = request_delivery(o1["id"], window_start="2026-09-10T09:00:00Z",
                          window_end="2026-09-10T15:00:00Z")
    d2 = request_delivery(o2["id"], window_start="2026-09-10T08:59:00Z",
                          window_end="2026-09-10T15:00:00Z")
    shift = create_truck_shift()

    scheduled = schedule_delivery(d1["id"], shift["id"])
    assert scheduled["delivery_status"] == "SCHEDULED"
    assert scheduled["delivery_fee_cents"] == 7501

    resp = api.schedule_delivery(d2["id"], {"truck_shift_id": shift["id"]}, FLEET)
    validate_error(resp, ApiErrorId.ERR_JOBSITE_ACCESS_WINDOW_VIOLATION)
    assert get_delivery(d2["id"])["delivery_status"] == "REQUESTED"


def test_jobsite_window_end_boundary_allowed_and_one_minute_past_rejected():
    """PRD §3.7: "The delivery window must also lie within the job's access
    window [access_window_start, access_window_end] under closed containment —
    touching either endpoint is allowed — else
    ERR_JOBSITE_ACCESS_WINDOW_VIOLATION (HTTP 400)." A delivery ending exactly
    at access_window_end schedules; one ending one minute past is rejected.

    Design: Difficulty/resource_temporal_overlap/jobsite_window_closed_containment_allows_touching_endpoints
    """
    set_clock("2026-09-01T00:00:00Z")
    product = create_product()
    branch = create_branch()
    receive_lot(branch["id"], product["id"], 100, 40000)
    builder = create_active_builder(9000000)
    job = create_job(
        builder["id"],
        access_window_start="2026-09-10T09:00:00Z",
        access_window_end="2026-09-10T15:00:00Z",
    )
    o1 = create_order(job["id"], branch["id"], builder["id"], qty_mbf=10,
                      unit_price_cents=100000, product_id=product["id"])
    confirm_order(o1["id"])
    o2 = create_order(job["id"], branch["id"], builder["id"], qty_mbf=10,
                      unit_price_cents=100000, product_id=product["id"])
    confirm_order(o2["id"])

    d_ok = request_delivery(o1["id"], window_start="2026-09-10T14:00:00Z",
                            window_end="2026-09-10T15:00:00Z")
    d_late = request_delivery(o2["id"], window_start="2026-09-10T14:00:00Z",
                              window_end="2026-09-10T15:01:00Z")
    shift = create_truck_shift()

    scheduled = schedule_delivery(d_ok["id"], shift["id"])
    assert scheduled["delivery_status"] == "SCHEDULED"

    resp = api.schedule_delivery(d_late["id"], {"truck_shift_id": shift["id"]}, FLEET)
    validate_error(resp, ApiErrorId.ERR_JOBSITE_ACCESS_WINDOW_VIOLATION)
    assert get_delivery(d_late["id"])["delivery_status"] == "REQUESTED"


def test_truck_shift_requires_forty_five_minute_buffer_between_drops():
    """PRD §3.7: "No other SCHEDULED delivery on the same shift may sit within
    a 45-minute buffer of the new window: if the new window starts before an
    existing delivery's window end plus 45 minutes, or an existing delivery's
    window starts before the new window's end plus 45 minutes, the attempt is
    ERR_TRUCK_SHIFT_OVERLAP (HTTP 409)." PRD §3.7: "An order that is not
    CONFIRMED, or that already has a non-terminal delivery outstanding,
    rejects the request with ERR_ORDER_NOT_DELIVERABLE (HTTP 400)".

    Design: Difficulty/resource_temporal_overlap/truck_shift_requires_forty_five_minute_buffer_between_drops
    """
    set_clock("2026-09-01T00:00:00Z")
    s = _two_builder_scenario()
    d1 = request_delivery(s["order1"]["id"], window_start="2026-09-10T09:00:00Z",
                          window_end="2026-09-10T10:00:00Z")
    d2 = request_delivery(s["order2"]["id"], window_start="2026-09-10T10:30:00Z",
                          window_end="2026-09-10T12:00:00Z")
    shift = create_truck_shift()
    schedule_delivery(d1["id"], shift["id"])

    # 30-minute gap < 45-minute buffer: rejected.
    resp = api.schedule_delivery(d2["id"], {"truck_shift_id": shift["id"]}, FLEET)
    validate_error(resp, ApiErrorId.ERR_TRUCK_SHIFT_OVERLAP)

    d2_now = get_delivery(d2["id"])
    assert d2_now["delivery_status"] == "REQUESTED"
    assert d2_now["truck_shift_id"] is None

    # One live delivery per order: a second request while d2 is REQUESTED is rejected.
    resp = api.create_delivery(
        s["order2"]["id"],
        {"boom_required": False, "window_start": "2026-09-10T10:45:00Z",
         "window_end": "2026-09-10T12:00:00Z"},
        ACCT,
    )
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_DELIVERABLE)

    assert get_shift(shift["id"])["booked_drops"] == 1


def test_truck_shift_buffer_exactly_forty_five_minutes_allowed():
    """PRD §3.7: "No other SCHEDULED delivery on the same shift may sit within
    a 45-minute buffer of the new window: if the new window starts before an
    existing delivery's window end plus 45 minutes ... the attempt is
    ERR_TRUCK_SHIFT_OVERLAP (HTTP 409)." A gap of exactly 45 minutes is not
    "before" window end plus 45, so it schedules.

    Design: Difficulty/resource_temporal_overlap/truck_shift_requires_forty_five_minute_buffer_between_drops
    """
    set_clock("2026-09-01T00:00:00Z")
    s = _two_builder_scenario()
    d1 = request_delivery(s["order1"]["id"], window_start="2026-09-10T09:00:00Z",
                          window_end="2026-09-10T10:00:00Z")
    d2 = request_delivery(s["order2"]["id"], window_start="2026-09-10T10:45:00Z",
                          window_end="2026-09-10T10:45:00Z")
    shift = create_truck_shift()
    schedule_delivery(d1["id"], shift["id"])

    scheduled = schedule_delivery(d2["id"], shift["id"])
    assert scheduled["delivery_status"] == "SCHEDULED"
    assert get_shift(shift["id"])["booked_drops"] == 2


def test_boom_required_delivery_on_non_boom_shift_rejected():
    """PRD §3.7: "A delivery with boom_required true may only take a shift
    whose boom_capable is true, else ERR_BOOM_CAPABILITY_MISMATCH (HTTP 409)."

    Design: Corner/errors/boom_required_delivery_on_non_boom_shift_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    scenario = setup_order_confirmed()
    delivery = request_delivery(scenario["order"]["id"], boom_required=True)
    shift_van = create_truck_shift(fleet_code="FLT-VAN", boom_capable=False)
    shift_boom = create_truck_shift(fleet_code="FLT-BOOM", boom_capable=True)

    resp = api.schedule_delivery(
        delivery["id"], {"truck_shift_id": shift_van["id"]}, FLEET
    )
    validate_error(resp, ApiErrorId.ERR_BOOM_CAPABILITY_MISMATCH)

    scheduled = schedule_delivery(delivery["id"], shift_boom["id"])
    assert scheduled["delivery_status"] == "SCHEDULED"
    assert scheduled["delivery_fee_cents"] == 11504


def test_shift_drop_limit_reached_rejects_next_schedule():
    """PRD §3.7: "And the shift's booked_drops must be below max_drops, else
    ERR_SHIFT_DROP_LIMIT_REACHED (HTTP 409)."

    Design: Corner/errors/shift_drop_limit_reached_rejects_next_schedule
    """
    set_clock("2026-09-01T00:00:00Z")
    s = _two_builder_scenario()
    d1 = request_delivery(s["order1"]["id"], window_start="2026-09-10T09:00:00Z",
                          window_end="2026-09-10T10:00:00Z")
    d2 = request_delivery(s["order2"]["id"], window_start="2026-09-10T13:00:00Z",
                          window_end="2026-09-10T13:00:00Z")
    shift = create_truck_shift(max_drops=1)
    schedule_delivery(d1["id"], shift["id"])

    resp = api.schedule_delivery(d2["id"], {"truck_shift_id": shift["id"]}, FLEET)
    validate_error(resp, ApiErrorId.ERR_SHIFT_DROP_LIMIT_REACHED)
    assert get_delivery(d2["id"])["delivery_status"] == "REQUESTED"
    assert get_shift(shift["id"])["booked_drops"] == 1


def test_delivery_schedule_gated_by_order_confirmed_not_on_hold():
    """PRD §3.7: "The delivery's order must be CONFIRMED, else
    ERR_ORDER_NOT_DELIVERABLE." PRD §3.4: "suspension is not self-healing:
    orders parked ON_HOLD by the suspension are not automatically re-confirmed
    and each requires an explicit confirm call afterward."

    Design: Difficulty/cross_entity_state_dependency/delivery_schedule_gated_by_order_confirmed_not_on_hold
    """
    set_clock("2026-09-01T00:00:00Z")
    scenario = setup_order_confirmed()
    order = scenario["order"]
    builder = scenario["builder"]
    delivery = request_delivery(order["id"])
    shift = create_truck_shift()

    resp = api.credit_review(builder["id"], {"decision": "SUSPEND"}, CREDIT)
    validate_success(resp)

    resp = api.schedule_delivery(
        delivery["id"], {"truck_shift_id": shift["id"]}, FLEET
    )
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_DELIVERABLE)
    d_now = get_delivery(delivery["id"])
    assert d_now["delivery_status"] == "REQUESTED"
    assert d_now["truck_shift_id"] is None

    resp = api.credit_review(
        builder["id"],
        {"decision": "APPROVE", "credit_limit_cents": 5000000},
        CREDIT,
    )
    validate_success(resp)
    confirm_order(order["id"])

    scheduled = schedule_delivery(delivery["id"], shift["id"])
    assert scheduled["delivery_status"] == "SCHEDULED"
    assert scheduled["truck_shift_id"] == shift["id"]
    assert get_shift(shift["id"])["booked_drops"] == 1


def test_delivery_schedule_on_draft_order_rejected_not_deliverable():
    """PRD §3.7: "Delivery begins when an AccountManager requests one against
    a CONFIRMED order ... An order that is not CONFIRMED, or that already has
    a non-terminal delivery outstanding, rejects the request with
    ERR_ORDER_NOT_DELIVERABLE (HTTP 400)".

    Design: Difficulty/cross_entity_state_dependency/delivery_schedule_gated_by_order_confirmed_not_on_hold
    """
    set_clock("2026-09-01T00:00:00Z")
    product = create_product()
    branch = create_branch()
    receive_lot(branch["id"], product["id"], 20, 40000)
    builder, job = setup_builder_with_job(5000000)
    order = create_order(job["id"], branch["id"], builder["id"], qty_mbf=10,
                         unit_price_cents=100000, product_id=product["id"])

    resp = api.create_delivery(
        order["id"],
        {"boom_required": False, "window_start": "2026-09-10T09:00:00Z",
         "window_end": "2026-09-10T12:00:00Z"},
        ACCT,
    )
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_DELIVERABLE)


def test_delivery_failed_access_retry_cycle_completes():
    """PRD §3.7: "When outcome is FAILED_ACCESS, the delivery instead moves to
    FAILED_ACCESS, fail_count increments by 1, the shift's booked_drops
    decrements by 1, and truck_shift_id is cleared to null — the delivery is
    then eligible to be scheduled again under the same seven checks."

    Design: Difficulty/non_linear_state_machine/delivery_failed_access_retry_cycle_completes
    """
    set_clock("2026-09-01T00:00:00Z")
    scenario = setup_order_confirmed(order_qty=10, unit_price_cents=100000)
    order = scenario["order"]
    delivery = request_delivery(order["id"])
    shift1 = create_truck_shift(fleet_code="FLT-1")
    shift2 = create_truck_shift(fleet_code="FLT-2")

    schedule_delivery(delivery["id"], shift1["id"])
    failed = complete_delivery(delivery["id"], "FAILED_ACCESS")
    assert failed["fail_count"] == 1
    assert failed["delivery_status"] == "FAILED_ACCESS"
    assert failed["truck_shift_id"] is None
    assert get_shift(shift1["id"])["booked_drops"] == 0

    retried = schedule_delivery(delivery["id"], shift2["id"])
    assert retried["delivery_status"] == "SCHEDULED"

    set_clock("2026-09-10T13:00:00Z")
    completed = complete_delivery(delivery["id"], "COMPLETED")
    assert completed["delivery_status"] == "COMPLETED"
    assert completed["truck_shift_id"] == shift2["id"]
    assert get_order(order["id"])["order_status"] == "DELIVERED"


def test_delivery_failed_access_fail_count_increments_per_failure():
    """PRD §3.7: "When outcome is FAILED_ACCESS, the delivery instead moves to
    FAILED_ACCESS, fail_count increments by 1, the shift's booked_drops
    decrements by 1, and truck_shift_id is cleared to null". Two successive
    failures on the same delivery leave fail_count at 2.

    Design: Difficulty/non_linear_state_machine/delivery_failed_access_retry_cycle_completes
    """
    set_clock("2026-09-01T00:00:00Z")
    scenario = setup_order_confirmed(order_qty=10, unit_price_cents=100000)
    order = scenario["order"]
    delivery = request_delivery(order["id"])

    for i in (1, 2):
        shift = create_truck_shift(fleet_code=f"FLT-{i}")
        schedule_delivery(delivery["id"], shift["id"])
        failed = complete_delivery(delivery["id"], "FAILED_ACCESS")
        assert failed["fail_count"] == i
        assert failed["delivery_status"] == "FAILED_ACCESS"
        assert failed["truck_shift_id"] is None
        assert get_shift(shift["id"])["booked_drops"] == 0
