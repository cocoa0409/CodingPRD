"""Donation matching and point redemption: the low-income and posture gates,
all-or-nothing matching, donation-funded fulfillment, and redemption rules.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    create_donation_request,
    create_redemption,
    create_school,
    create_teacher,
    create_title,
    enroll_school,
    make_teacher_headers,
    setup_published_cycle,
    read_teacher,
    read_title,
    TEST_USERS,
)

CLUB_ADMIN = TEST_USERS["club_admin_headers"]
DONOR = TEST_USERS["donor_headers"]


def _low_income_world(api, name, grade_band="K_2"):
    school = create_school(api, name=name, low_income_program=True)
    enroll_school(api, school["id"])
    teacher = create_teacher(api, school["id"], grade_band=grade_band, full_name=f"{name} Teacher")
    title = create_title(
        api, name=f"{name} Title", grade_band=grade_band, base_price_cents=800, points_cost=8
    )
    return school, teacher, title


def test_non_low_income_create_and_restricted_match_are_rejected(api):
    """Creation needs the low-income flag; matching needs posture NORMAL.

    PRD: "The school must carry `low_income_program` true, else the request is
    rejected with `ERR_NOT_LOW_INCOME` (HTTP 422), and the title's license must
    be `ACTIVE`, else `ERR_LICENSE_SUSPENDED`."
    PRD: "Matching requires the school's `low_income_program` to be true and
    its posture to be `NORMAL`, and the title's license to be `ACTIVE`."
    PRD: "Submitting a class order, publishing a flyer cycle, matching a
    donation request, confirming a redemption, and scheduling a book fair all
    require the relevant school's posture to be `NORMAL`; while the school is
    `RESTRICTED`, each of these is rejected with `ERR_SCHOOL_RESTRICTED` (HTTP
    409)."

    Design: Difficulty/cross_entity_state_dependency/donation_match_gated_by_school_low_income_and_posture
    """
    # A low-income school whose request is created while NORMAL.
    school, teacher, title = _low_income_world(api, "Donation Gate School")
    request = create_donation_request(api, school["id"], teacher["id"], title["id"], qty_requested=5)
    assert request["status"] == "OPEN"

    # A NORMAL school without the low-income flag cannot create a request.
    other = create_school(api, name="Regular School", low_income_program=False)
    enroll_school(api, other["id"])
    other_teacher = create_teacher(api, other["id"], grade_band="K_2", full_name="Regular Teacher")
    rejected_create = api.create_donation_request(
        {
            "school_id": other["id"],
            "teacher_id": other_teacher["id"],
            "title_id": title["id"],
            "qty_requested": 3,
        },
        make_teacher_headers(other_teacher["id"]),
    )
    validate_error(rejected_create, "ERR_NOT_LOW_INCOME", 422)

    # Suspending the low-income school blocks the donor match.
    validate_success(api.suspend_program(school["id"], CLUB_ADMIN))
    rejected_match = api.match_donation_request(request["id"], DONOR)
    validate_error(rejected_match, "ERR_SCHOOL_RESTRICTED", 409)

    still_open = validate_success(api.get_donation_request(request["id"], DONOR))
    assert still_open["status"] == "OPEN"


def test_matching_requires_normal_posture_and_is_all_or_nothing(api):
    """The match sets qty_matched == qty_requested and only while NORMAL.

    PRD: "The match is all-or-nothing: `qty_matched` is set equal to
    `qty_requested`, the request moves from `OPEN` to `MATCHED`, and its
    `version` increments. Partial matches do not exist."
    PRD: "Matching requires the school's `low_income_program` to be true and
    its posture to be `NORMAL`, and the title's license to be `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/donation_match_gated_by_school_low_income_and_posture
    """
    school, teacher, title = _low_income_world(api, "Match School")
    request = create_donation_request(api, school["id"], teacher["id"], title["id"], qty_requested=6)

    matched = validate_success(api.match_donation_request(request["id"], DONOR))
    assert matched["status"] == "MATCHED"
    assert matched["qty_matched"] == 6, "the match is all-or-nothing"
    assert matched["version"] > request["version"], "the match increments the version"

    # After reinstatement from a suspension, matching works again.
    second = create_donation_request(api, school["id"], teacher["id"], title["id"], qty_requested=2)
    validate_success(api.suspend_program(school["id"], CLUB_ADMIN))
    blocked = api.match_donation_request(second["id"], DONOR)
    validate_error(blocked, "ERR_SCHOOL_RESTRICTED", 409)
    validate_success(api.reinstate_program(school["id"], CLUB_ADMIN))
    rematched = validate_success(api.match_donation_request(second["id"], DONOR))
    assert rematched["status"] == "MATCHED"
    assert rematched["qty_matched"] == 2


def test_fulfill_requires_a_matched_request(api):
    """Fulfilling an OPEN request is rejected with ERR_DONATION_NOT_MATCHED.

    PRD: "Fulfillment, performed by a `ClubAdmin` on a `MATCHED` request — any
    other status yields `ERR_DONATION_NOT_MATCHED` (HTTP 409) — requires the
    title's license still to be `ACTIVE` at fulfillment time and turns the
    match into a physical shipment."

    Design: Corner/state_machines/donation_fulfill_requires_matched
    """
    school, teacher, title = _low_income_world(api, "Premature Fulfill School")
    request = create_donation_request(api, school["id"], teacher["id"], title["id"], qty_requested=2)
    rejected = api.fulfill_donation_request(request["id"], CLUB_ADMIN)
    validate_error(rejected, "ERR_DONATION_NOT_MATCHED", 409)


def test_fulfill_creates_a_donation_funded_submitted_order(api):
    """Fulfillment ships zero-priced lines that never earn points.

    PRD: "Fulfillment creates a class order on the school's currently
    `PUBLISHED` cycle for the requesting teacher, in `SUBMITTED` status with
    `ship_status` `PENDING` and `points_status` `UNAWARDED`, containing
    `qty_matched` order lines marked `donation_funded` true at
    `unit_price_cents` zero."
    PRD: "Donation-funded lines never earn points, both because they are
    excluded from the earning base and because their price is zero."
    PRD: "Fulfillment then adds `qty_matched` to the teacher's
    `donated_books_received` and accrues royalty on the title for the matched
    units, which may flip the license to `SUSPENDED`."

    Design: Corner/state_machines/donation_fulfill_creates_donation_funded_order
    """
    school, teacher, title = _low_income_world(api, "Fulfill School")
    published = setup_published_cycle(api, school["id"], [title["id"]], grade_band="K_2")
    request = create_donation_request(api, school["id"], teacher["id"], title["id"], qty_requested=4)
    validate_success(api.match_donation_request(request["id"], DONOR))

    fulfilled = validate_success(api.fulfill_donation_request(request["id"], CLUB_ADMIN))
    assert fulfilled["status"] == "FULFILLED"
    assert fulfilled["qty_matched"] == 4

    orders, _ = validate_paginated(
        api.list_teacher_class_orders(teacher["id"], make_teacher_headers(teacher["id"]))
    )
    assert len(orders) == 1
    donation_order = orders[0]
    assert donation_order["status"] == "SUBMITTED"
    assert donation_order["ship_status"] == "PENDING"
    assert donation_order["points_status"] == "UNAWARDED"
    assert donation_order["subtotal_cents"] == 0

    lines, _ = validate_paginated(
        api.list_order_lines(donation_order["id"], make_teacher_headers(teacher["id"]))
    )
    assert lines, "the donation order carries the matched lines"
    total_qty = 0
    for line in lines:
        assert line["donation_funded"] is True
        assert line["unit_price_cents"] == 0
        total_qty += line["qty"]
    assert total_qty == 4

    teacher_after = read_teacher(api, teacher["id"])
    assert teacher_after["donated_books_received"] == 4
    assert teacher_after["points_balance"] == 0, "donation-funded lines earn no points"
    assert read_title(api, title["id"])["royalty_accrued_cents"] == 360, (
        "fulfillment accrues 90 cents per matched unit"
    )


def test_book_redemption_requires_a_title_and_supply_forbids_one(api):
    """The redemption basket shape is enforced at creation.

    PRD: "The basket shapes the payload: a `BOOK` redemption requires a
    `title_id` naming the classroom book title, while a `SUPPLY` redemption
    must not carry one — the wrong combination is rejected with
    `ERR_REDEMPTION_SHAPE_INVALID` (HTTP 422)."

    Design: Corner/validations/redemption_shape_book_requires_title
    """
    school = create_school(api, name="Shape School", low_income_program=False)
    enroll_school(api, school["id"])
    teacher = create_teacher(api, school["id"], grade_band="G3_5", full_name="Shape Teacher")
    title = create_title(api, name="Shape Title", base_price_cents=1000, points_cost=10)
    headers = make_teacher_headers(teacher["id"])

    missing_title = api.create_redemption(
        {"teacher_id": teacher["id"], "kind": "BOOK", "qty": 1}, headers
    )
    validate_error(missing_title, "ERR_REDEMPTION_SHAPE_INVALID", 422)

    supply_with_title = api.create_redemption(
        {"teacher_id": teacher["id"], "kind": "SUPPLY", "qty": 1, "title_id": title["id"]},
        headers,
    )
    validate_error(supply_with_title, "ERR_REDEMPTION_SHAPE_INVALID", 422)


def test_confirm_with_insufficient_points_is_rejected(api):
    """Confirm requires the balance to cover the computed points_cost.

    PRD: "The teacher's `points_balance` must be at least the redemption's
    `points_cost`, else the confirm is rejected with `ERR_INSUFFICIENT_POINTS`
    (HTTP 422)."
    PRD: "The `points_cost` is computed at creation: for `BOOK`, the `qty`
    times the title's `points_cost`; for `SUPPLY`, the `qty` times a flat 200
    points per unit."

    Design: Corner/validations/redeem_confirm_with_insufficient_points
    """
    school = create_school(api, name="Insolvent School", low_income_program=False)
    enroll_school(api, school["id"])
    teacher = create_teacher(api, school["id"], grade_band="G3_5", full_name="Insolvent Teacher")
    title = create_title(api, name="Pricey Title", base_price_cents=1500, points_cost=15)
    headers = make_teacher_headers(teacher["id"])

    redemption = validate_success(
        api.create_redemption(
            {"teacher_id": teacher["id"], "kind": "BOOK", "title_id": title["id"], "qty": 1},
            headers,
        ),
        201,
    )
    assert redemption["points_cost"] == 15

    rejected = api.confirm_redemption(redemption["id"], headers)
    validate_error(rejected, "ERR_INSUFFICIENT_POINTS", 422)

    still_pending = validate_success(api.get_redemption(redemption["id"], headers))
    assert still_pending["status"] == "PENDING"
