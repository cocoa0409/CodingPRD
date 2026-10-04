"""Endpoints and consistency: reverse FK listings, pagination envelope,
missing-resource 404s, missing credentials, and immediate consistency.
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
    create_school,
    create_teacher,
    create_title,
    enroll_school,
    make_teacher_headers,
    publish_cycle,
    read_teacher,
    setup_submitted_order,
    submit_order,
    TEST_USERS,
)

CLUB_ADMIN = TEST_USERS["club_admin_headers"]
SCHOOL_ADMIN = TEST_USERS["school_admin_headers"]
DONOR = TEST_USERS["donor_headers"]

MISSING_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


def test_missing_path_id_returns_not_found(api):
    """A random UUID in the path yields ERR_NOT_FOUND.

    PRD: "Endpoints with hierarchical paths validate path identifiers strictly
    left to right — school before cycle, cycle before order, order before line.
    The first identifier that does not exist yields `ERR_NOT_FOUND` (HTTP 404),
    and later identifiers are not consulted."

    Design: Corner/entities/get_missing_entity_returns_not_found
    """
    rejected = api.get_title(MISSING_UUID, CLUB_ADMIN)
    validate_error(rejected, "ERR_NOT_FOUND", 404)

    rejected_school = api.get_school(MISSING_UUID, CLUB_ADMIN)
    validate_error(rejected_school, "ERR_NOT_FOUND", 404)


def test_list_schools_paginates_with_the_standard_envelope(api):
    """List endpoints honor limit/offset and report total_count and has_more.

    PRD: "All list endpoints accept two query parameters: `limit` and `offset`.
    The `limit` parameter defaults to 10, must be at least 1, and must not
    exceed 100. The `offset` parameter defaults to 0. List responses are always
    sorted by `created_at` in ascending order, and their `meta` object carries
    the four pagination fields `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/entities/list_schools_paginates_with_envelope
    """
    for name in ("Page A", "Page B", "Page C"):
        validate_success(api.create_school({"name": name, "address": f"{name} Rd"}, CLUB_ADMIN), 201)

    page, meta = validate_paginated(api.list_schools(CLUB_ADMIN, {"limit": 2, "offset": 0}))
    assert len(page) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0

    rest, meta2 = validate_paginated(api.list_schools(CLUB_ADMIN, {"limit": 2, "offset": 2}))
    assert len(rest) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_reverse_listings_return_the_children(api):
    """Every declared reverse listing returns its parent's children.

    PRD: "Because enrollment drives posture, enrollments can be listed per
    school, and teachers, flyer cycles, book fairs, and donation requests are
    all listed per school as well."
    PRD: "the pinned `awarded_total_points` is credited to the teacher's
    `points_balance` and `points_earned_total`, a points-ledger `EARN` entry
    referencing the class order is appended, and the order's `points_status`
    moves from `UNAWARDED` to `AWARDED`."

    Design: Corner/endpoints/fk_reverse_listings_return_children
    """
    school = create_school(api, name="Reverse School", low_income_program=False)
    enroll_school(api, school["id"])
    teacher = create_teacher(api, school["id"], grade_band="G3_5", full_name="Reverse Teacher")
    title = create_title(api, name="Reverse Title", base_price_cents=1000, points_cost=10)
    cycle = create_cycle(api, school["id"], month="2026-10", grade_band="G3_5")
    offering = add_offering(api, cycle["id"], title["id"])
    publish_cycle(api, cycle["id"])
    order = create_order(api, cycle["id"], teacher["id"])
    add_line(api, order["id"], offering["id"], qty=1, teacher_id=teacher["id"])
    submitted = submit_order(api, order["id"], teacher["id"])
    assert submitted["awarded_total_points"] == 10

    teachers, _ = validate_paginated(api.list_school_teachers(school["id"], CLUB_ADMIN))
    assert [t["id"] for t in teachers] == [teacher["id"]]

    offerings, _ = validate_paginated(api.list_cycle_offerings(cycle["id"], CLUB_ADMIN))
    assert [o["id"] for o in offerings] == [offering["id"]]

    lines, _ = validate_paginated(
        api.list_order_lines(order["id"], make_teacher_headers(teacher["id"]))
    )
    assert len(lines) == 1

    ledger, _ = validate_paginated(
        api.list_teacher_points_ledger(teacher["id"], make_teacher_headers(teacher["id"]))
    )
    earn_entries = [e for e in ledger if e["entry_type"] == "EARN"]
    assert len(earn_entries) == 1
    assert earn_entries[0]["points"] == 10
    assert earn_entries[0]["ref_type"] == "CLASS_ORDER"
    assert earn_entries[0]["ref_id"] == order["id"]


def test_submit_effects_are_visible_immediately(api):
    """The submit response and the immediate re-read agree — no async lag.

    PRD: "A successful submission performs all of the following. The order's
    `status` moves from `OPEN` to `SUBMITTED`. The pinned
    `awarded_total_points` is credited to the teacher's `points_balance` and
    `points_earned_total`, a points-ledger `EARN` entry referencing the class
    order is appended, and the order's `points_status` moves from `UNAWARDED`
    to `AWARDED`."

    Design: Corner/consistency_model/submit_effects_visible_immediately
    """
    world = setup_submitted_order(
        api,
        line_specs=[{"offering_index": 0, "qty": 2}],
        school_name="Immediate School",
        title_overrides=[{"base_price_cents": 1500, "points_cost": 15}],
    )
    submitted = world["order"]
    assert submitted["status"] == "SUBMITTED"
    assert submitted["points_status"] == "AWARDED"
    assert submitted["awarded_total_points"] == 30

    teacher_after = read_teacher(api, world["teacher"]["id"])
    assert teacher_after["points_balance"] == 30, (
        "the teacher's balance reflects the award in the same request stream"
    )
    assert teacher_after["points_earned_total"] == 30


def test_missing_credentials_are_unauthenticated(api):
    """No credentials at all yields ERR_UNAUTHENTICATED.

    PRD: "Every request must carry two headers: `X-User-ID` identifying the
    acting user and `X-User-Role` naming their role. A request missing either
    header, or carrying a role value outside the declared set, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/roles/missing_auth_headers_unauthenticated
    """
    rejected = api.list_schools({})
    validate_error(rejected, "ERR_UNAUTHENTICATED", 401)

    role_only = api.list_schools({"X-User-Role": "ClubAdmin"})
    validate_error(role_only, "ERR_UNAUTHENTICATED", 401)

    bad_role = api.list_schools({"X-User-ID": "someone", "X-User-Role": "SuperUser"})
    validate_error(bad_role, "ERR_UNAUTHENTICATED", 401)
