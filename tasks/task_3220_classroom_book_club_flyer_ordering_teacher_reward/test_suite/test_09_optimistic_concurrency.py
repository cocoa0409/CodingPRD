"""Optimistic concurrency: the two OCC-guarded writes reject stale versions
and accept the current one.
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
    submit_order,
    TEST_USERS,
)

CLUB_ADMIN = TEST_USERS["club_admin_headers"]


def test_submit_with_a_stale_version_is_rejected_then_fresh_version_succeeds(api):
    """A line add between read and submit invalidates the quoted version.

    PRD: "A class order submission must carry `expected_class_order_version`,
    equal to the class order's current `version`. Because adding, updating, or
    cancelling a line recomputes the order's aggregates and bumps the order's
    `version`, a client whose priced view predates the latest line mutation
    holds a stale version; if `expected_class_order_version` does not match the
    order's current `version`, the submission is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/endpoints/occ_stale_version_on_submit_rejected
    """
    school = create_school(api, name="Stale School", low_income_program=False)
    enroll_school(api, school["id"])
    teacher = create_teacher(api, school["id"], grade_band="G3_5", full_name="Stale Teacher")
    title = create_title(api, name="Stale Title", base_price_cents=1000, points_cost=10)
    cycle = create_cycle(api, school["id"], month="2026-10", grade_band="G3_5")
    offering = add_offering(api, cycle["id"], title["id"])
    publish_cycle(api, cycle["id"])

    headers = make_teacher_headers(teacher["id"])
    order = validate_success(
        api.create_class_order({"cycle_id": cycle["id"], "teacher_id": teacher["id"]}, headers),
        201,
    )
    observed_version = order["version"]

    # The line add bumps the order's version.
    add_line(api, order["id"], offering["id"], qty=1, teacher_id=teacher["id"])
    fresh = validate_success(api.get_class_order(order["id"], headers))
    assert fresh["version"] == observed_version + 1

    stale = api.submit_class_order(
        order["id"], {"expected_class_order_version": observed_version}, headers
    )
    validate_error(stale, "ERR_STALE_VERSION", 412)

    submitted = validate_success(
        api.submit_class_order(
            order["id"], {"expected_class_order_version": fresh["version"]}, headers
        )
    )
    assert submitted["status"] == "SUBMITTED"


def test_acquire_with_a_stale_version_is_rejected_then_current_succeeds(api):
    """The OCC-guarded renegotiation rejects any version but the current one.

    PRD: "A title license renegotiation must carry `expected_title_version`,
    equal to the title's current `version`. If another acquisition or a
    royalty-driven license flip has advanced the title's `version` since the
    client last read it, the renegotiation is rejected with `ERR_STALE_VERSION`
    (HTTP 412), since the client based its proposed cap on a cap-and-accrual
    picture that no longer exists."

    Design: Corner/cross_cutting_layers/occ_stale_version_on_title_acquire
    """
    title = create_title(api, name="OCC Title", base_price_cents=1000, points_cost=10,
                         royalty_cap_cents=100000)
    observed_version = title["version"]

    first = validate_success(
        api.acquire_title(
            title["id"],
            {"royalty_cap_cents": 200000, "expected_title_version": observed_version},
            CLUB_ADMIN,
        )
    )
    assert first["royalty_cap_cents"] == 200000
    assert first["version"] == observed_version + 1, "the acquire bumps the title's version"

    stale = api.acquire_title(
        title["id"],
        {"royalty_cap_cents": 300000, "expected_title_version": observed_version},
        CLUB_ADMIN,
    )
    validate_error(stale, "ERR_STALE_VERSION", 412)

    second = validate_success(
        api.acquire_title(
            title["id"],
            {"royalty_cap_cents": 300000, "expected_title_version": first["version"]},
            CLUB_ADMIN,
        )
    )
    assert second["royalty_cap_cents"] == 300000
