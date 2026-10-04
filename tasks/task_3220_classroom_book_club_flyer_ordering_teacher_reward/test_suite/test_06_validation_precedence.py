"""Fixed validation precedence: the §2.8 priority order decides which error
surfaces when several rules could reject the same request.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    add_line,
    add_offering,
    create_cycle,
    create_order,
    create_school,
    create_teacher,
    create_title,
    enroll_school,
    make_teacher_headers,
    publish_cycle,
    read_order,
    submit_order,
    TEST_USERS,
)

CLUB_ADMIN = TEST_USERS["club_admin_headers"]


def test_school_posture_outranks_order_emptiness_on_submit(api):
    """An empty order at a restricted school surfaces ERR_SCHOOL_RESTRICTED.

    PRD: "7. School posture (`ERR_SCHOOL_RESTRICTED`) — the school's posture
    gates the operation."
    PRD: "24. Submit non-emptiness (`ERR_ORDER_EMPTY`)."
    PRD: "When several validation rules could reject the same request, the
    server evaluates them in a fixed priority order and reports the first
    failure."

    Design: Difficulty/priority_pair_validation_conflict/restricted_school_beats_empty_order_on_submit
    """
    school = create_school(api, name="Precedence School", low_income_program=False)
    enroll_school(api, school["id"])
    teacher = create_teacher(api, school["id"], grade_band="G3_5", full_name="Precedence Teacher")
    title = create_title(api, name="Precedence Title", base_price_cents=1000, points_cost=10)
    cycle = create_cycle(api, school["id"], month="2026-10", grade_band="G3_5")
    add_offering(api, cycle["id"], title["id"])
    publish_cycle(api, cycle["id"])

    # Order creation is not posture-gated, so the empty order can be opened
    # while the school is RESTRICTED.
    validate_success(api.suspend_program(school["id"], CLUB_ADMIN))
    headers = make_teacher_headers(teacher["id"])
    order = validate_success(
        api.create_class_order({"cycle_id": cycle["id"], "teacher_id": teacher["id"]}, headers),
        201,
    )

    rejected = api.submit_class_order(
        order["id"], {"expected_class_order_version": order["version"]}, headers
    )
    # Both posture (priority 7) and non-emptiness (priority 24) could fire;
    # posture is evaluated first.
    validate_error(rejected, "ERR_SCHOOL_RESTRICTED", 409)


def test_empty_order_at_a_normal_school_reports_its_own_error(api):
    """With posture satisfied, the emptiness rule surfaces ERR_ORDER_EMPTY.

    PRD: "24. Submit non-emptiness (`ERR_ORDER_EMPTY`)."
    PRD: "at least one line must exist with a status other than `CANCELLED`
    (else `ERR_ORDER_EMPTY`, HTTP 422)"

    Design: Difficulty/priority_pair_validation_conflict/restricted_school_beats_empty_order_on_submit
    """
    school = create_school(api, name="Normal Empty School", low_income_program=False)
    enroll_school(api, school["id"])
    teacher = create_teacher(api, school["id"], grade_band="G3_5", full_name="Empty Teacher")
    title = create_title(api, name="Empty Title", base_price_cents=1000, points_cost=10)
    cycle = create_cycle(api, school["id"], month="2026-10", grade_band="G3_5")
    add_offering(api, cycle["id"], title["id"])
    publish_cycle(api, cycle["id"])

    headers = make_teacher_headers(teacher["id"])
    order = validate_success(
        api.create_class_order({"cycle_id": cycle["id"], "teacher_id": teacher["id"]}, headers),
        201,
    )
    rejected = api.submit_class_order(
        order["id"], {"expected_class_order_version": order["version"]}, headers
    )
    validate_error(rejected, "ERR_ORDER_EMPTY", 422)

    still_open = read_order(api, order["id"], teacher["id"])
    assert still_open["status"] == "OPEN"


def test_royalty_cap_rule_outranks_stale_version_on_acquire(api):
    """A below-accrued cap and a stale version together surface the cap error.

    PRD: "9. Royalty cap sanity (`ERR_ROYALTY_CAP_INVALID`)."
    PRD: "25. Optimistic concurrency (`ERR_STALE_VERSION`)."
    PRD: "When several validation rules could reject the same request, the
    server evaluates them in a fixed priority order and reports the first
    failure."
    PRD: "a proposed `royalty_cap_cents` below the title's current
    `royalty_accrued_cents` is rejected with `ERR_ROYALTY_CAP_INVALID` (HTTP
    422), because a license can never cap below what is already owed."

    Design: Difficulty/priority_pair_validation_conflict/royalty_cap_shape_beats_stale_version_on_acquire
    """
    school = create_school(api, name="Cap Precedence School", low_income_program=False)
    enroll_school(api, school["id"])
    teacher = create_teacher(api, school["id"], grade_band="G3_5", full_name="Cap Teacher")
    title = create_title(api, name="Cap Title", base_price_cents=1000, points_cost=10,
                         royalty_cap_cents=100000)
    stale_version = title["version"]
    cycle = create_cycle(api, school["id"], month="2026-10", grade_band="G3_5")
    offering = add_offering(api, cycle["id"], title["id"])
    publish_cycle(api, cycle["id"])

    order = create_order(api, cycle["id"], teacher["id"])
    add_line(api, order["id"], offering["id"], qty=1, teacher_id=teacher["id"])
    submit_order(api, order["id"], teacher["id"])
    # The submit accrued 90 cents of royalty against the title.

    rejected = api.acquire_title(
        title["id"],
        {"royalty_cap_cents": 50, "expected_title_version": stale_version},
        CLUB_ADMIN,
    )
    # Both cap sanity (priority 9) and OCC (priority 25) could fire; the cap
    # rule is evaluated first.
    validate_error(rejected, "ERR_ROYALTY_CAP_INVALID", 422)


def test_a_valid_cap_with_a_stale_version_surfaces_stale_version(api):
    """Once the cap rule passes, the OCC rule reports ERR_STALE_VERSION.

    PRD: "25. Optimistic concurrency (`ERR_STALE_VERSION`)."
    PRD: "A title license renegotiation must carry `expected_title_version`,
    equal to the title's current `version`. If another acquisition or a
    royalty-driven license flip has advanced the title's `version` since the
    client last read it, the renegotiation is rejected with `ERR_STALE_VERSION`
    (HTTP 412), since the client based its proposed cap on a cap-and-accrual
    picture that no longer exists."

    Design: Difficulty/priority_pair_validation_conflict/royalty_cap_shape_beats_stale_version_on_acquire
    """
    title = create_title(api, name="Stale Title", base_price_cents=1000, points_cost=10,
                         royalty_cap_cents=100000)
    stale_version = title["version"]

    first = validate_success(
        api.acquire_title(
            title["id"],
            {"royalty_cap_cents": 200000, "expected_title_version": stale_version},
            CLUB_ADMIN,
        )
    )
    assert first["version"] == stale_version + 1

    rejected = api.acquire_title(
        title["id"],
        {"royalty_cap_cents": 300000, "expected_title_version": stale_version},
        CLUB_ADMIN,
    )
    validate_error(rejected, "ERR_STALE_VERSION", 412)
