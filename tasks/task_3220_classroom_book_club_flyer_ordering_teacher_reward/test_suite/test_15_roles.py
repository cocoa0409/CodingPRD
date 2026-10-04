"""Role-based access control: role-per-endpoint authorization and the
Donor-exclusive match.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    create_donation_request,
    create_school,
    create_teacher,
    create_title,
    enroll_school,
    make_teacher_headers,
    setup_published_cycle,
    TEST_USERS,
)

CLUB_ADMIN = TEST_USERS["club_admin_headers"]
PARENT = TEST_USERS["parent_headers"]
DONOR = TEST_USERS["donor_headers"]


def test_parent_cannot_create_a_class_order(api):
    """POST /club/class-orders is Teacher-only.

    PRD: "A request whose role is not permitted for the target endpoint is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD: "**`Teacher`** — a classroom teacher. Creates, submits, and cancels
    their own class orders; creates, updates, and cancels order lines; creates,
    confirms, and cancels their own redemptions; creates donation requests;
    reads flyers, offerings, and their own points ledger."

    Design: Corner/roles/parent_cannot_create_class_order
    """
    school = create_school(api, name="RBAC School", low_income_program=False)
    enroll_school(api, school["id"])
    teacher = create_teacher(api, school["id"], grade_band="G3_5", full_name="RBAC Teacher")
    title = create_title(api, name="RBAC Title")
    published = setup_published_cycle(api, school["id"], [title["id"]])

    rejected = api.create_class_order(
        {"cycle_id": published["cycle"]["id"], "teacher_id": teacher["id"]},
        PARENT,
    )
    validate_error(rejected, "ERR_UNAUTHORIZED", 403)


def test_only_a_donor_matches_a_donation_request(api):
    """Match is Donor-exclusive; a Teacher is denied.

    PRD: "**`Donor`** — a sponsor. Matches donation requests and reads donation
    requests, schools, and titles."
    PRD: "A `Donor` matches an `OPEN` request. Matching requires the school's
    `low_income_program` to be true and its posture to be `NORMAL`, and the
    title's license to be `ACTIVE`. The match is all-or-nothing: `qty_matched`
    is set equal to `qty_requested`, the request moves from `OPEN` to
    `MATCHED`, and its `version` increments."
    PRD: "A request whose role is not permitted for the target endpoint is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/roles/donor_match_works_and_teacher_cannot_match
    """
    school = create_school(api, name="Donor School", low_income_program=True)
    enroll_school(api, school["id"])
    teacher = create_teacher(api, school["id"], grade_band="K_2", full_name="Donor Teacher")
    title = create_title(api, name="Donor Title", grade_band="K_2", base_price_cents=800,
                         points_cost=8)
    request = create_donation_request(api, school["id"], teacher["id"], title["id"], qty_requested=2)

    denied = api.match_donation_request(request["id"], make_teacher_headers(teacher["id"]))
    validate_error(denied, "ERR_UNAUTHORIZED", 403)

    matched = validate_success(api.match_donation_request(request["id"], DONOR))
    assert matched["status"] == "MATCHED"
    assert matched["qty_matched"] == 2
