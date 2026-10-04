"""State machines: cycle publish/close gating, terminal lockdown, shipment
blocking on cancel, and points expiry under the ops epoch.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    add_line,
    add_offering,
    create_book_fair,
    create_cycle,
    create_donation_request,
    create_order,
    create_promotion,
    create_school,
    create_teacher,
    create_title,
    enroll_school,
    make_teacher_headers,
    publish_cycle,
    read_order,
    read_teacher,
    run_ops,
    run_shipping,
    set_clock,
    setup_submitted_order,
    submit_order,
    TEST_USERS,
)

CLUB_ADMIN = TEST_USERS["club_admin_headers"]
SCHOOL_ADMIN = TEST_USERS["school_admin_headers"]


def _world_with_published_cycle(api, name, low_income=False, grade_band="G3_5"):
    school = create_school(api, name=name, low_income_program=low_income)
    enroll_school(api, school["id"])
    teacher = create_teacher(api, school["id"], grade_band=grade_band, full_name=f"{name} Teacher")
    title = create_title(
        api, name=f"{name} Title", grade_band=grade_band, base_price_cents=1000, points_cost=10
    )
    cycle = create_cycle(api, school["id"], month="2026-10", grade_band=grade_band)
    offering = add_offering(api, cycle["id"], title["id"])
    publish_cycle(api, cycle["id"])
    return school, teacher, title, cycle, offering


def test_publishing_an_empty_cycle_is_rejected(api):
    """A DRAFT cycle with zero offerings cannot publish.

    PRD: "Third, the cycle must contain at least one offering; publishing an
    empty cycle is rejected with `ERR_EMPTY_CYCLE` (HTTP 422)."

    Design: Corner/state_machines/publish_empty_cycle_rejected
    """
    school = create_school(api, name="Empty Cycle School", low_income_program=False)
    enroll_school(api, school["id"])
    cycle = create_cycle(api, school["id"], month="2026-10", grade_band="K_2")

    rejected = api.publish_cycle(cycle["id"], CLUB_ADMIN)
    validate_error(rejected, "ERR_EMPTY_CYCLE", 422)

    cycle_after = validate_success(api.get_flyer_cycle(cycle["id"], CLUB_ADMIN))
    assert cycle_after["status"] == "DRAFT"


def test_closing_a_cycle_with_open_orders_is_rejected(api):
    """PUBLISHED -> CLOSED requires every order out of OPEN.

    PRD: "Closing from `PUBLISHED` requires that every class order in the cycle
    be out of `OPEN` — submitted or cancelled — else the transition is rejected
    with `ERR_INVALID_STATE`; lines still `BACKORDERED` at close time simply
    remain backordered, because backordered lines belong to their order, not to
    the cycle."

    Design: Corner/state_machines/invalid_transition_close_with_open_orders_rejected
    """
    school, teacher, _title, cycle, _offering = _world_with_published_cycle(api, "Open Close School")
    headers = make_teacher_headers(teacher["id"])
    validate_success(
        api.create_class_order({"cycle_id": cycle["id"], "teacher_id": teacher["id"]}, headers),
        201,
    )

    rejected = api.close_cycle(cycle["id"], CLUB_ADMIN)
    validate_error(rejected, "ERR_INVALID_STATE", 409)

    cycle_after = validate_success(api.get_flyer_cycle(cycle["id"], CLUB_ADMIN))
    assert cycle_after["status"] == "PUBLISHED"


def test_cancelled_order_is_terminal(api):
    """A second cancel on a CANCELLED order is ERR_ALREADY_TERMINAL.

    PRD: "From `CANCELLED`, nothing further is possible — the state is terminal
    and any further transition attempt is rejected with
    `ERR_ALREADY_TERMINAL`."

    Design: Corner/state_machines/terminal_cancelled_order_rejects_second_cancel
    """
    school, teacher, _title, cycle, offering = _world_with_published_cycle(api, "Terminal School")
    headers = make_teacher_headers(teacher["id"])
    order = validate_success(
        api.create_class_order({"cycle_id": cycle["id"], "teacher_id": teacher["id"]}, headers),
        201,
    )
    add_line(api, order["id"], offering["id"], qty=1, teacher_id=teacher["id"])

    cancelled = validate_success(api.cancel_class_order(order["id"], headers))
    assert cancelled["status"] == "CANCELLED"

    rejected = api.cancel_class_order(order["id"], headers)
    validate_error(rejected, "ERR_ALREADY_TERMINAL", 409)


def test_cancel_after_shipping_is_rejected(api):
    """Cancel-from-SUBMITTED requires ship_status PENDING; SHIPPED blocks it.

    PRD: "From `SUBMITTED`, cancellation additionally requires `ship_status` to
    be `PENDING` — once anything has shipped the order cannot be cancelled, and
    the attempt is rejected with `ERR_ORDER_HAS_SHIPPED` (HTTP 409)."

    Design: Corner/state_machines/cancel_submitted_after_partial_ship_blocked
    """
    world = setup_submitted_order(
        api,
        line_specs=[{"offering_index": 0, "qty": 1}],
        school_name="Shipped School",
        title_overrides=[{"base_price_cents": 1000, "points_cost": 10}],
    )
    order = world["order"]
    # With every line's title license-ACTIVE, the order ships at submit and the
    # sweep advances nothing further; run the sweep to exercise the ops path.
    run_shipping(api)
    shipped = read_order(api, order["id"], world["teacher"]["id"])
    assert shipped["ship_status"] == "SHIPPED"

    rejected = api.cancel_class_order(order["id"], world["teacher_headers"])
    validate_error(rejected, "ERR_ORDER_HAS_SHIPPED", 409)

    after = read_order(api, order["id"], world["teacher"]["id"])
    assert after["status"] == "SUBMITTED"


def test_completed_fair_cannot_be_cancelled(api):
    """Cancelling a COMPLETED fair is ERR_FAIR_NOT_CANCELLABLE.

    PRD: "Cancelling a `COMPLETED` fair is rejected with
    `ERR_FAIR_NOT_CANCELLABLE` (HTTP 409), and both `COMPLETED` and `CANCELLED`
    are terminal."

    Design: Corner/validations/fair_cancel_completed_rejected
    """
    school = create_school(api, name="Past Fair School", low_income_program=False)
    enroll_school(api, school["id"])
    fair = create_book_fair(api, school["id"], start_date="2026-09-10", end_date="2026-09-12")

    set_clock(api, "2026-09-20T00:00:00Z")
    completed = validate_success(api.get_book_fair(fair["id"], SCHOOL_ADMIN))
    assert completed["status"] == "COMPLETED"

    rejected = api.cancel_book_fair(fair["id"], SCHOOL_ADMIN)
    validate_error(rejected, "ERR_FAIR_NOT_CANCELLABLE", 409)


def test_promotion_expiry_excludes_it_from_the_award(api):
    """An EXPIRED promotion contributes zero bonus at submit.

    PRD: "A promotion's computed `status` is `ACTIVE` until the logical clock
    date reaches `ends_on`, at which point the clock advance flips it to
    `EXPIRED`, and expired promotions never apply."
    PRD: "Step two scans promotions: among promotions that are `ACTIVE`, whose
    `[starts_on, ends_on)` window contains the logical clock date, and whose
    `grade_band` is either null or equal to the ordering teacher's band, the
    `BONUS_POINTS` promotions contribute a single best multiplier — the highest
    `multiplier_bp`, with ties broken by the earliest promotion `created_at`
    and then by `name` in ascending order."

    Design: Corner/calculations/promotion_expiry_excludes_from_award
    """
    school = create_school(api, name="Expired Promo School", low_income_program=False)
    enroll_school(api, school["id"])
    teacher = create_teacher(api, school["id"], grade_band="G3_5", full_name="Expired Teacher")
    title = create_title(api, name="Expired Title", base_price_cents=1500, points_cost=15)
    create_promotion(
        api,
        name="September Double",
        kind="BONUS_POINTS",
        multiplier_bp=200,
        starts_on="2026-09-01",
        ends_on="2026-10-01",
    )
    cycle = create_cycle(api, school["id"], month="2026-10", grade_band="G3_5")
    offering = add_offering(api, cycle["id"], title["id"])
    publish_cycle(api, cycle["id"])

    order = create_order(api, cycle["id"], teacher["id"])
    add_line(api, order["id"], offering["id"], qty=2, teacher_id=teacher["id"])
    set_clock(api, "2026-10-15T00:00:00Z")

    submitted = submit_order(api, order["id"], teacher["id"])
    assert submitted["awarded_base_points"] == 30
    assert submitted["awarded_bonus_points"] == 0, "the September window expired before the submit"
    assert submitted["awarded_total_points"] == 30
    assert read_teacher(api, teacher["id"])["points_balance"] == 30


def test_ops_run_expires_points_older_than_twelve_months(api):
    """The monthly sweep expires year-old unconsumed earnings, FIFO.

    PRD: "Points from `EARN` entries whose ledger entry is older than 12
    calendar months before the logical clock date — and which have not yet been
    consumed by `REDEEM`, prior `EXPIRE`, or `CLAWBACK` entries — expire."
    PRD: "For each teacher, the expired points are aggregated into a single
    `EXPIRE` ledger entry referencing the ops run, the teacher's
    `points_expired_total` increases by the expired amount, and
    `points_balance` decreases by the same amount, preserving the invariant
    that the balance equals earned minus redeemed minus expired."
    PRD: "Step one derives base points from the earning base: the base is the
    `rewardable_subtotal_cents` divided by 100 cents per point and floored to
    an integer — 100 cents of rewardable spend earns one point. The earning
    base is the full rewardable subtotal; the tier discount never reduces it."

    Design: Corner/calculations/points_expiry_sweep_fifo_after_12_months
    """
    school = create_school(api, name="Expiry School", low_income_program=False)
    enroll_school(api, school["id"])
    teacher = create_teacher(api, school["id"], grade_band="G3_5", full_name="Expiry Teacher")
    title = create_title(api, name="Expiry Title", base_price_cents=2500, points_cost=25)
    cycle = create_cycle(api, school["id"], month="2026-10", grade_band="G3_5")
    offering = add_offering(api, cycle["id"], title["id"])
    publish_cycle(api, cycle["id"])

    order = create_order(api, cycle["id"], teacher["id"])
    add_line(api, order["id"], offering["id"], qty=2, teacher_id=teacher["id"])
    set_clock(api, "2026-10-15T00:00:00Z")
    submitted = submit_order(api, order["id"], teacher["id"])
    # 2 x 2500 = 5000 cents rewardable -> 50 base points (the 5% tier discount
    # never reduces the earning base).
    assert submitted["awarded_base_points"] == 50
    assert submitted["awarded_total_points"] == 50

    set_clock(api, "2027-11-01T00:00:00Z")
    summary = run_ops(api)
    assert summary["expired_total_points"] >= 50
    assert summary["teachers_affected"] >= 1

    teacher_after = read_teacher(api, teacher["id"])
    assert teacher_after["points_earned_total"] == 50
    assert teacher_after["points_expired_total"] == 50, (
        "the October 2026 earning is older than 12 calendar months at 2027-11-01"
    )
    assert teacher_after["points_balance"] == 0, "balance reconciles: 50 earned - 50 expired"

    ledger, _ = validate_paginated(
        api.list_teacher_points_ledger(teacher["id"], make_teacher_headers(teacher["id"]))
    )
    expire_entries = [e for e in ledger if e["entry_type"] == "EXPIRE"]
    assert expire_entries, "the sweep appends an EXPIRE ledger entry"
    assert sum(e["points"] for e in expire_entries) == -50
