"""Class order workflows: the three parallel status dimensions, the shipping
sweep, cycle-state gating, and the school-suspension cascade.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    add_line,
    add_offering,
    create_cycle,
    create_donation_request,
    create_order,
    create_redemption,
    create_school,
    create_teacher,
    create_title,
    enroll_school,
    make_teacher_headers,
    publish_cycle,
    read_order,
    read_school,
    read_teacher,
    read_title,
    run_shipping,
    setup_submitted_order,
    submit_order,
    TEST_USERS,
)

CLUB_ADMIN = TEST_USERS["club_admin_headers"]
DONOR = TEST_USERS["donor_headers"]


def _school_with_teacher(api, name, low_income=False, grade_band="G3_5"):
    school = create_school(api, name=name, low_income_program=low_income)
    enroll_school(api, school["id"])
    teacher = create_teacher(api, school["id"], grade_band=grade_band, full_name=f"{name} Teacher")
    return school, teacher


def _published_cycle_with_offering(api, school_id, title_id, grade_band="G3_5"):
    cycle = create_cycle(api, school_id, month="2026-10", grade_band=grade_band)
    offering = add_offering(api, cycle["id"], title_id)
    publish_cycle(api, cycle["id"])
    return cycle, offering


def test_submit_backorders_suspended_title_and_shipping_sweep_ships_it(api):
    """Status, ship_status and points_status evolve independently.

    PRD: "The new order opens with three independent status dimensions, each
    evolving in parallel: `status` begins `OPEN` and tracks the order lifecycle
    (`OPEN`, `SUBMITTED`, `CANCELLED`); `ship_status` begins `PENDING` and
    tracks fulfillment (`PENDING`, `PARTIAL`, `SHIPPED`); and `points_status`
    begins `UNAWARDED` and tracks reward disposition (`UNAWARDED`, `AWARDED`,
    `CLAWED_BACK`). No dimension implies another; the workflows below advance
    each explicitly."
    PRD: "Then the backorder pass: every non-cancelled line whose title's
    license is now `SUSPENDED` moves from `ACTIVE` to `BACKORDERED`, and the
    order's `ship_status` is forced to remain `PENDING`; if zero non-cancelled
    lines are backordered after the pass, `ship_status` advances directly from
    `PENDING` to `SHIPPED`, otherwise it stays `PENDING`."
    PRD: "Within each such order, every `BACKORDERED` line whose title's
    license is `ACTIVE` ships — its status returns from `BACKORDERED` to
    `ACTIVE` and it counts as shipped for that run — while lines whose titles
    remain `SUSPENDED` stay `BACKORDERED`."

    Design: Difficulty/non_linear_state_machine/class_order_parallel_dimensions_ship_and_points
    """
    school, teacher = _school_with_teacher(api, "Parallel School")
    ok_title = create_title(api, name="Stocked Title", base_price_cents=1000, points_cost=10)
    susp_title = create_title(
        api, name="Thin License Title", base_price_cents=1000, points_cost=10, royalty_cap_cents=90
    )
    cycle = create_cycle(api, school["id"], month="2026-10", grade_band="G3_5")
    o1 = add_offering(api, cycle["id"], ok_title["id"])
    o2 = add_offering(api, cycle["id"], susp_title["id"])
    publish_cycle(api, cycle["id"])

    order = create_order(api, cycle["id"], teacher["id"])
    add_line(api, order["id"], o1["id"], qty=1, teacher_id=teacher["id"])
    susp_line = add_line(api, order["id"], o2["id"], qty=2, teacher_id=teacher["id"])

    submitted = submit_order(api, order["id"], teacher["id"])
    assert submitted["status"] == "SUBMITTED"
    assert submitted["points_status"] == "AWARDED"
    assert submitted["ship_status"] == "PENDING", (
        "the suspended-license line backorders, forcing ship_status to stay PENDING"
    )
    # 2 units at 90 cents = 180 > 90: the license flipped during this submit.
    assert read_title(api, susp_title["id"])["license_status"] == "SUSPENDED"

    lines, _ = validate_paginated(
        api.list_order_lines(order["id"], make_teacher_headers(teacher["id"]))
    )
    backordered = [l for l in lines if l["id"] == susp_line["id"]]
    assert backordered[0]["status"] == "BACKORDERED"

    # Raise the cap; the license recomputes to ACTIVE.
    title = read_title(api, susp_title["id"])
    reacquired = validate_success(
        api.acquire_title(
            susp_title["id"],
            {"royalty_cap_cents": 100000, "expected_title_version": title["version"]},
            CLUB_ADMIN,
        )
    )
    assert reacquired["license_status"] == "ACTIVE"

    summary = run_shipping(api)
    assert summary["shipped_line_count"] >= 1

    shipped = read_order(api, order["id"], teacher["id"])
    assert shipped["ship_status"] == "SHIPPED", "no lines remain backordered after the sweep"
    assert shipped["points_status"] == "AWARDED", "the shipping sweep never touches points_status"
    assert shipped["status"] == "SUBMITTED"


def test_submit_with_all_stocked_lines_advances_straight_to_shipped(api):
    """With zero backordered lines, submission ships immediately.

    PRD: "if zero non-cancelled lines are backordered after the pass,
    `ship_status` advances directly from `PENDING` to `SHIPPED`, otherwise it
    stays `PENDING`."
    PRD: "The new order opens with three independent status dimensions, each
    evolving in parallel ... `ship_status` begins `PENDING` and tracks
    fulfillment (`PENDING`, `PARTIAL`, `SHIPPED`) ..."

    Design: Difficulty/non_linear_state_machine/class_order_parallel_dimensions_ship_and_points
    """
    world = setup_submitted_order(
        api,
        line_specs=[{"offering_index": 0, "qty": 2}],
        school_name="Stocked School",
        title_overrides=[{"base_price_cents": 1500, "points_cost": 15}],
    )
    submitted = world["order"]
    assert submitted["status"] == "SUBMITTED"
    assert submitted["points_status"] == "AWARDED"
    assert submitted["ship_status"] == "SHIPPED", (
        "every line's title is license-ACTIVE, so nothing backorders"
    )
    assert submitted["awarded_base_points"] == 30
    assert world["teacher"]["points_balance"] == 30


def test_order_creation_requires_a_published_cycle(api):
    """A class order cannot be opened on a DRAFT cycle.

    PRD: "Once a cycle is `PUBLISHED`, a `Teacher` opens a class order on it by
    supplying `cycle_id` and their own `teacher_id`. The order's teacher must
    teach at the cycle's school and their `grade_band` must equal the cycle's
    `grade_band`, else the creation is rejected with `ERR_GRADE_BAND_MISMATCH`;
    and the cycle must be `PUBLISHED`, else `ERR_CYCLE_NOT_PUBLISHED` (HTTP
    409)."

    Design: Difficulty/cross_entity_state_dependency/submit_gated_by_cycle_published_state
    """
    school, teacher = _school_with_teacher(api, "Draft Cycle School")
    title = create_title(api, name="Draft Title", base_price_cents=1000, points_cost=10)
    cycle = create_cycle(api, school["id"], month="2026-10", grade_band="G3_5")
    add_offering(api, cycle["id"], title["id"])

    headers = make_teacher_headers(teacher["id"])
    rejected = api.create_class_order(
        {"cycle_id": cycle["id"], "teacher_id": teacher["id"]}, headers
    )
    validate_error(rejected, "ERR_CYCLE_NOT_PUBLISHED", 409)

    publish_cycle(api, cycle["id"])
    opened = validate_success(
        api.create_class_order({"cycle_id": cycle["id"], "teacher_id": teacher["id"]}, headers),
        201,
    )
    assert opened["status"] == "OPEN"
    assert opened["ship_status"] == "PENDING"
    assert opened["points_status"] == "UNAWARDED"


def test_submit_requires_the_cycle_to_be_published(api):
    """The same cycle-state gate applies from order creation through publish.

    PRD: "and the cycle must be `PUBLISHED`, else `ERR_CYCLE_NOT_PUBLISHED`
    (HTTP 409)."
    PRD: "Once a cycle is `PUBLISHED`, a `Teacher` opens a class order on it by
    supplying `cycle_id` and their own `teacher_id`."

    Design: Difficulty/cross_entity_state_dependency/submit_gated_by_cycle_published_state
    """
    school, teacher = _school_with_teacher(api, "Cycle Gate School")
    title = create_title(api, name="Gated Title", base_price_cents=1000, points_cost=10)

    # No cycle at all yet: an arbitrary missing cycle id is a body-reference
    # failure, distinct from the DRAFT-cycle state gate.
    headers = make_teacher_headers(teacher["id"])
    missing = api.create_class_order(
        {"cycle_id": "00000000-0000-4000-8000-000000000000", "teacher_id": teacher["id"]},
        headers,
    )
    validate_error(missing, "ERR_REFERENCE_NOT_FOUND", 404)

    # DRAFT cycle: creation is state-gated until publication.
    cycle = create_cycle(api, school["id"], month="2026-10", grade_band="G3_5")
    add_offering(api, cycle["id"], title["id"])
    rejected = api.create_class_order(
        {"cycle_id": cycle["id"], "teacher_id": teacher["id"]}, headers
    )
    validate_error(rejected, "ERR_CYCLE_NOT_PUBLISHED", 409)

    publish_cycle(api, cycle["id"])
    opened = validate_success(
        api.create_class_order({"cycle_id": cycle["id"], "teacher_id": teacher["id"]}, headers),
        201,
    )
    assert opened["status"] == "OPEN"


def test_suspension_cascades_from_school_to_open_order_lines(api):
    """Suspend flips posture, suspends enrollment, and cancels open orders.

    PRD: "When a `ClubAdmin` suspends the program of a school whose posture is
    `NORMAL` and which has an `ACTIVE` enrollment, four things happen in one
    cascade: the school's posture flips from `NORMAL` to `RESTRICTED`; the
    enrollment's `status` moves from `ACTIVE` to `SUSPENDED`; every class order
    still `OPEN` belonging to any teacher of that school is auto-cancelled —
    its status moves to `CANCELLED` and every one of its open order lines moves
    to `CANCELLED` with it; and the school's `active_fair_id` is recomputed
    (which changes nothing unless the clock has moved)."

    Design: Difficulty/transitive_cascade/school_suspension_cascades_to_open_order_lines
    """
    school, teacher = _school_with_teacher(api, "Cascade School")
    title = create_title(api, name="Cascade Title", base_price_cents=1000, points_cost=10)
    cycle, offering = _published_cycle_with_offering(api, school["id"], title["id"])
    order = create_order(api, cycle["id"], teacher["id"])
    add_line(api, order["id"], offering["id"], qty=1, teacher_id=teacher["id"])

    suspended = validate_success(api.suspend_program(school["id"], CLUB_ADMIN))
    assert suspended["posture"] == "RESTRICTED"

    enrollments, _ = validate_paginated(api.list_school_enrollments(school["id"], CLUB_ADMIN))
    assert enrollments[0]["status"] == "SUSPENDED"

    cancelled = read_order(api, order["id"], teacher["id"])
    assert cancelled["status"] == "CANCELLED", "the cascade cancels the school's OPEN orders"
    lines, _ = validate_paginated(
        api.list_order_lines(order["id"], make_teacher_headers(teacher["id"]))
    )
    assert lines and all(line["status"] == "CANCELLED" for line in lines)


def test_submitted_orders_survive_suspension_while_open_orders_cancel(api):
    """The cascade touches only OPEN orders; a submitted order is untouched.

    PRD: "every class order still `OPEN` belonging to any teacher of that
    school is auto-cancelled — its status moves to `CANCELLED` and every one of
    its open order lines moves to `CANCELLED` with it"
    PRD: "the school's posture flips from `NORMAL` to `RESTRICTED`"

    Design: Difficulty/transitive_cascade/school_suspension_cascades_to_open_order_lines
    """
    school, teacher = _school_with_teacher(api, "Selective Cascade School")
    title = create_title(api, name="Selective Title", base_price_cents=1000, points_cost=10)
    cycle, offering = _published_cycle_with_offering(api, school["id"], title["id"])

    submitted_order = create_order(api, cycle["id"], teacher["id"])
    add_line(api, submitted_order["id"], offering["id"], qty=1, teacher_id=teacher["id"])
    submit_order(api, submitted_order["id"], teacher["id"])

    open_order = create_order(api, cycle["id"], teacher["id"])
    add_line(api, open_order["id"], offering["id"], qty=1, teacher_id=teacher["id"])

    validate_success(api.suspend_program(school["id"], CLUB_ADMIN))

    assert read_order(api, submitted_order["id"], teacher["id"])["status"] == "SUBMITTED", (
        "only orders still OPEN are auto-cancelled"
    )
    assert read_order(api, open_order["id"], teacher["id"])["status"] == "CANCELLED"


def test_license_flip_backorders_the_line_and_gates_book_redemption(api):
    """A submit-driven license flip backorders and blocks a book redemption.

    PRD: "Then the backorder pass: every non-cancelled line whose title's
    license is now `SUSPENDED` moves from `ACTIVE` to `BACKORDERED`, and the
    order's `ship_status` is forced to remain `PENDING`..."
    PRD: "A `SUSPENDED` license is a hard gate on four operations: adding the
    title as a flyer offering, creating a donation request for it, matching a
    donation request for it, and confirming a book-kind redemption of it are
    each rejected with `ERR_LICENSE_SUSPENDED` (HTTP 409)."

    Design: Difficulty/transitive_cascade/title_license_flip_backorders_line_and_gates_redemption
    """
    school, teacher = _school_with_teacher(api, "Flip School")
    thin_title = create_title(
        api, name="Thin Title", base_price_cents=1000, points_cost=10, royalty_cap_cents=90
    )
    big_title = create_title(api, name="Big Title", base_price_cents=12500, points_cost=125)
    cycle = create_cycle(api, school["id"], month="2026-10", grade_band="G3_5")
    o_thin = add_offering(api, cycle["id"], thin_title["id"])
    o_big = add_offering(api, cycle["id"], big_title["id"])
    publish_cycle(api, cycle["id"])

    # Pre-load 250 points via an earlier submitted order.
    preload = create_order(api, cycle["id"], teacher["id"])
    add_line(api, preload["id"], o_big["id"], qty=2, teacher_id=teacher["id"])
    submit_order(api, preload["id"], teacher["id"])
    assert read_teacher(api, teacher["id"])["points_balance"] == 250

    # The redemption is created while the license is still ACTIVE.
    redemption = create_redemption(api, teacher["id"], kind="BOOK", qty=1, title_id=thin_title["id"])
    assert redemption["status"] == "PENDING"
    assert redemption["points_cost"] == 10

    order = create_order(api, cycle["id"], teacher["id"])
    flip_line = add_line(api, order["id"], o_thin["id"], qty=2, teacher_id=teacher["id"])
    submitted = submit_order(api, order["id"], teacher["id"])

    title_after = read_title(api, thin_title["id"])
    assert title_after["royalty_accrued_cents"] == 180
    assert title_after["license_status"] == "SUSPENDED"
    assert submitted["ship_status"] == "PENDING"

    lines, _ = validate_paginated(
        api.list_order_lines(order["id"], make_teacher_headers(teacher["id"]))
    )
    assert lines[0]["id"] == flip_line["id"] and lines[0]["status"] == "BACKORDERED"

    headers = make_teacher_headers(teacher["id"])
    blocked = api.confirm_redemption(redemption["id"], headers)
    validate_error(blocked, "ERR_LICENSE_SUSPENDED", 409)


def test_suspended_license_blocks_donation_request_creation(api):
    """The flip also gates donation request creation for the title.

    PRD: "A `SUSPENDED` license is a hard gate on four operations: adding the
    title as a flyer offering, creating a donation request for it, matching a
    donation request for it, and confirming a book-kind redemption of it are
    each rejected with `ERR_LICENSE_SUSPENDED` (HTTP 409)."
    PRD: "The school must carry `low_income_program` true, else the request is
    rejected with `ERR_NOT_LOW_INCOME` (HTTP 422), and the title's license must
    be `ACTIVE`, else `ERR_LICENSE_SUSPENDED`."

    Design: Difficulty/transitive_cascade/title_license_flip_backorders_line_and_gates_redemption
    """
    school, teacher = _school_with_teacher(api, "Flip Donation School", low_income=True)
    thin_title = create_title(
        api, name="Thin Donation Title", base_price_cents=1000, points_cost=10,
        royalty_cap_cents=90,
    )
    cycle, offering = _published_cycle_with_offering(api, school["id"], thin_title["id"])

    order = create_order(api, cycle["id"], teacher["id"])
    add_line(api, order["id"], offering["id"], qty=2, teacher_id=teacher["id"])
    submit_order(api, order["id"], teacher["id"])
    assert read_title(api, thin_title["id"])["license_status"] == "SUSPENDED"

    headers = make_teacher_headers(teacher["id"])
    blocked = api.create_donation_request(
        {
            "school_id": school["id"],
            "teacher_id": teacher["id"],
            "title_id": thin_title["id"],
            "qty_requested": 1,
        },
        headers,
    )
    validate_error(blocked, "ERR_LICENSE_SUSPENDED", 409)
