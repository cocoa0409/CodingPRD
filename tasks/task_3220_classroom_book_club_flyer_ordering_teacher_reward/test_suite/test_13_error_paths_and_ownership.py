"""Error catalogue paths: clawback solvency, teacher ownership, parent line
channel ownership, and the order-open gate on line mutation.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    add_line,
    add_offering,
    create_cycle,
    create_order,
    create_redemption,
    create_school,
    create_teacher,
    create_title,
    enroll_school,
    make_teacher_headers,
    publish_cycle,
    read_order,
    read_teacher,
    setup_submitted_order,
    submit_order,
    TEST_USERS,
)

CLUB_ADMIN = TEST_USERS["club_admin_headers"]
PARENT = TEST_USERS["parent_headers"]


def test_cancel_blocked_when_clawback_would_drive_balance_negative(api):
    """A teacher who spent the award cannot cancel the submitted order.

    PRD: "Because the clawback may not drive the balance below zero, a teacher
    who has already redeemed part of the award may be insolvent for
    cancellation: if the teacher's `points_balance` is below the order's
    `awarded_total_points`, the cancel is rejected with
    `ERR_POINTS_BALANCE_NEGATIVE` (HTTP 422)."

    Design: Corner/errors/error_points_balance_negative_trigger
    """
    # The cap suspends the title at submission, backordering the line so
    # ship_status stays PENDING and the cancel reaches the solvency gate.
    world = setup_submitted_order(
        api,
        line_specs=[{"offering_index": 0, "qty": 1}],
        school_name="Solvency School",
        title_overrides=[{"base_price_cents": 2000, "points_cost": 15,
                          "royalty_cap_cents": 89}],
    )
    order = world["order"]
    teacher = world["teacher"]
    assert order["awarded_total_points"] == 20
    assert teacher["points_balance"] == 20
    assert order["ship_status"] == "PENDING"

    # Spend 15 of the 20 points on a second, license-ACTIVE title, leaving 5 —
    # below the 20-point clawback.
    spend_title = create_title(api, name="Solvency Spend Title",
                               base_price_cents=1500, points_cost=15)
    redemption = create_redemption(api, teacher["id"], kind="BOOK", qty=1,
                                   title_id=spend_title["id"])
    headers = make_teacher_headers(teacher["id"])
    validate_success(api.confirm_redemption(redemption["id"], headers))
    assert read_teacher(api, teacher["id"])["points_balance"] == 5

    rejected = api.cancel_class_order(order["id"], headers)
    validate_error(rejected, "ERR_POINTS_BALANCE_NEGATIVE", 422)

    after = read_order(api, order["id"], teacher["id"])
    assert after["status"] == "SUBMITTED", "the rejected cancel leaves the order submitted"
    assert after["points_status"] == "AWARDED"


def test_another_teacher_cannot_submit_the_order(api):
    """Only the owning teacher submits; a colleague is forbidden.

    PRD: "A `Teacher` submits an `OPEN` order — any other starting `status` is
    rejected with `ERR_INVALID_STATE` — and must be the order's owning teacher,
    else `ERR_FORBIDDEN_OWNERSHIP`."
    PRD: "ownership checks on any resource that references a `Teacher` — class
    orders, redemptions, donation requests, points ledgers — compare the
    resource's `teacher_id` field to `X-User-ID`, and a mismatch on an
    ownership-guarded action is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP
    403)."

    Design: Corner/errors/error_forbidden_ownership_teacher_mismatch
    """
    school = create_school(api, name="Ownership School", low_income_program=False)
    enroll_school(api, school["id"])
    owner = create_teacher(api, school["id"], grade_band="G3_5", full_name="Owner Teacher")
    other = create_teacher(api, school["id"], grade_band="G3_5", full_name="Other Teacher")
    title = create_title(api, name="Ownership Title")
    cycle = create_cycle(api, school["id"], month="2026-10", grade_band="G3_5")
    offering = add_offering(api, cycle["id"], title["id"])
    publish_cycle(api, cycle["id"])

    order = create_order(api, cycle["id"], owner["id"])
    add_line(api, order["id"], offering["id"], qty=1, teacher_id=owner["id"])
    version = read_order(api, order["id"], owner["id"])["version"]

    rejected = api.submit_class_order(
        order["id"],
        {"expected_class_order_version": version},
        make_teacher_headers(other["id"]),
    )
    validate_error(rejected, "ERR_FORBIDDEN_OWNERSHIP", 403)

    still_open = read_order(api, order["id"], owner["id"])
    assert still_open["status"] == "OPEN"


def test_line_mutation_after_submit_is_rejected(api):
    """Line mutations require the parent order OPEN on a PUBLISHED cycle.

    PRD: "Line creation, quantity updates, and line cancellation are permitted
    only while the parent order is `OPEN` and its cycle is `PUBLISHED`;
    otherwise the mutation is rejected with `ERR_ORDER_NOT_OPEN` (HTTP 409)."

    Design: Corner/errors/error_order_not_open_on_line_add_after_submit
    """
    world = setup_submitted_order(
        api,
        line_specs=[{"offering_index": 0, "qty": 1}],
        school_name="Closed Line School",
        title_overrides=[{"base_price_cents": 1000, "points_cost": 10}],
    )
    order = world["order"]
    offering = world["offerings"][0]

    late_add = api.add_order_line(
        order["id"],
        {
            "offering_id": offering["id"],
            "student_name": "Late Student",
            "submitted_by": "PARENT_ONLINE",
            "qty": 1,
        },
        PARENT,
    )
    validate_error(late_add, "ERR_ORDER_NOT_OPEN", 409)


def test_parent_cannot_cancel_a_teacher_submitted_line(api):
    """Parent line ownership is mediated by the submitted_by channel.

    PRD: "A parent may cancel only lines whose `submitted_by` is
    `PARENT_ONLINE`, and only while the parent order is `OPEN`; a parent
    attempting to cancel a teacher-entered line is rejected with
    `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."

    Design: Corner/roles/parent_cannot_cancel_teacher_submitted_line
    """
    school = create_school(api, name="Channel School", low_income_program=False)
    enroll_school(api, school["id"])
    teacher = create_teacher(api, school["id"], grade_band="G3_5", full_name="Channel Teacher")
    title = create_title(api, name="Channel Title")
    cycle = create_cycle(api, school["id"], month="2026-10", grade_band="G3_5")
    offering = add_offering(api, cycle["id"], title["id"])
    publish_cycle(api, cycle["id"])

    order = create_order(api, cycle["id"], teacher["id"])
    teacher_line = add_line(
        api, order["id"], offering["id"], qty=1, submitted_by="TEACHER",
        teacher_id=teacher["id"],
    )
    parent_line = add_line(
        api, order["id"], offering["id"], qty=1, submitted_by="PARENT_ONLINE"
    )

    rejected = api.delete_order_line(teacher_line["id"], PARENT)
    validate_error(rejected, "ERR_FORBIDDEN_OWNERSHIP", 403)

    cancelled = validate_success(api.delete_order_line(parent_line["id"], PARENT))
    assert cancelled["status"] == "CANCELLED", "the parent's own channel line may be cancelled"

    # The teacher may cancel their own line while the order is OPEN.
    cancelled_by_teacher = validate_success(
        api.delete_order_line(teacher_line["id"], make_teacher_headers(teacher["id"]))
    )
    assert cancelled_by_teacher["status"] == "CANCELLED"
