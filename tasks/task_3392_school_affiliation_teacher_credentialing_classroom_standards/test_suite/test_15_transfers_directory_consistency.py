"""Student transfers (overdraft and cross-school rejections, the conservation
invariant), the public directory and parent-facing verification, and the
immediate read-after-write consistency of the school's computed fields.
"""

from test_helpers import (
    ANONYMOUS,
    ApiErrorId,
    assert_directory_verification,
    create_active_catalog,
    create_classroom,
    create_school,
    file_classroom_audit,
    make_school_admin_headers,
    read_classroom,
    read_school,
    reset_clock,
    set_standing,
    setup_member_school,
    transfer_students,
    transfer_students_payload,
    validate_error,
    validate_success,
)

FULL_MATERIALS = [{"domain": "PRACTICAL_LIFE", "required_count": 10, "present_count": 10}]


def test_transfer_rejects_overdraft_and_cross_school(api):
    """PRD section 3.3: "the two rooms must belong to the same school,
    otherwise `ERR_TRANSFER_CROSS_SCHOOL` (HTTP 422), and must serve the same
    `age_level`, otherwise `ERR_AGE_LEVEL_MISMATCH` (HTTP 422). The count must
    be at least one and no greater than the source room's
    `enrolled_student_count` — exceeding it fails with
    `ERR_TRANSFER_EXCEEDS_ENROLLMENT` (HTTP 422)".

    Each violation is exercised in isolation (a same-school overdraft, then a
    cross-school transfer within the count), so exactly one rule can fire.

    Design: Corner/endpoints/transfer_rejects_overdraft_and_cross_school
    """
    reset_clock()
    create_active_catalog()
    school_t = create_school(name="T School", display_name="T2 Schoolhouse")
    room_a = create_classroom(school_t["id"], name="CA", enrolled_student_count=40)
    room_b = create_classroom(school_t["id"], name="CB", enrolled_student_count=0)
    school_u = create_school(name="U School", display_name="U Schoolhouse")
    room_u = create_classroom(school_u["id"], name="CU", enrolled_student_count=5)

    overdraft = api.transfer_students(
        room_a["id"],
        transfer_students_payload(room_b["id"], 41),
        headers=make_school_admin_headers(school_t["id"]),
    )
    validate_error(overdraft, ApiErrorId.ERR_TRANSFER_EXCEEDS_ENROLLMENT)

    cross_school = api.transfer_students(
        room_a["id"],
        transfer_students_payload(room_u["id"], 5),
        headers=make_school_admin_headers(school_t["id"]),
    )
    validate_error(cross_school, ApiErrorId.ERR_TRANSFER_CROSS_SCHOOL)

    assert read_classroom(room_a["id"])["enrolled_student_count"] == 40
    assert read_classroom(room_b["id"])["enrolled_student_count"] == 0
    assert read_classroom(room_u["id"])["enrolled_student_count"] == 5


def test_transfer_of_entire_enrollment_conserves_school_total(api):
    """PRD section 3.3: "moving a room's entire enrollment is allowed, leaving
    the source at zero" and "a school's `total_enrollment` after a transfer
    equals its value before, by invariant".

    Design: Difficulty/compensating_invariant/classroom_transfer_conserves_school_enrollment
    """
    reset_clock()
    school = create_school(name="T School", display_name="T Schoolhouse")
    room_a = create_classroom(school["id"], name="CA", enrolled_student_count=40)
    room_b = create_classroom(school["id"], name="CB", enrolled_student_count=10)
    assert read_school(school["id"])["total_enrollment"] == 50

    moved = transfer_students(room_a["id"], room_b["id"], 40, school["id"])
    assert moved["from_enrolled_student_count"] == 0, "boundary: exactly the source enrollment"
    assert moved["to_enrolled_student_count"] == 50
    assert moved["school_total_enrollment"] == 50
    assert read_school(school["id"])["total_enrollment"] == 50


def test_transfer_pair_conserves_school_total_across_both_writes(api):
    """PRD section 3.3: "The transfer subtracts the count from the source room
    and adds it to the destination, increments both classrooms' `version`, and
    answers with `from_classroom_id`, `to_classroom_id`,
    `from_enrolled_student_count`, `to_enrolled_student_count` and the
    unchanged `school_total_enrollment`: a school's `total_enrollment` after a
    transfer equals its value before, by invariant."

    Design: Difficulty/compensating_invariant/classroom_transfer_conserves_school_enrollment
    """
    reset_clock()
    school = create_school(name="T School", display_name="T Schoolhouse")
    room_a = create_classroom(school["id"], name="CA", enrolled_student_count=40)
    room_b = create_classroom(school["id"], name="CB", enrolled_student_count=10)

    transfer_students(room_a["id"], room_b["id"], 40, school["id"])
    reversed_move = transfer_students(room_b["id"], room_a["id"], 15, school["id"])
    assert reversed_move["from_enrolled_student_count"] == 35
    assert reversed_move["to_enrolled_student_count"] == 15
    assert reversed_move["school_total_enrollment"] == 50
    assert read_school(school["id"])["total_enrollment"] == 50


def test_directory_listing_and_parent_verification_track_visibility(api):
    """PRD section 3.8: "That flag is computed, and it demands four things at
    once: a membership level of `MEMBER` or `ACCREDITED`, a standing of
    `GOOD_STANDING`, a true `brand_compliant`, and a true `dues_current`." PRD
    section 3.8: "For a school the server knows but which is not currently
    listed, it answers with `listed` false and the `display_name` only —
    confirming existence without asserting standing."

    Design: Corner/endpoints/directory_listing_and_parent_verification_track_visibility
    """
    reset_clock()
    staged = setup_member_school()
    visible_id = staged.school["id"]
    unseen = create_school(name="Unseen School", display_name="Unseen Schoolhouse")

    listing = validate_success(api.list_directory(headers=ANONYMOUS), 200)
    assert listing["total_count"] == 1
    assert len(listing["items"]) == 1
    assert listing["has_more"] is False

    verified = validate_success(api.get_directory_school(visible_id, headers=ANONYMOUS), 200)
    assert_directory_verification(verified)
    assert verified["listed"] is True
    assert verified["membership_level"] == "MEMBER"
    assert verified["accredited"] is False

    unlisted = validate_success(api.get_directory_school(unseen["id"], headers=ANONYMOUS), 200)
    assert unlisted["listed"] is False
    assert unlisted["display_name"] == "Unseen Schoolhouse"

    set_standing(visible_id, "PROBATION", reason="Annual review finding")
    after = validate_success(api.list_directory(headers=ANONYMOUS), 200)
    assert after["total_count"] == 0
    assert after["items"] == []
    revoked_view = validate_success(api.get_directory_school(visible_id, headers=ANONYMOUS), 200)
    assert revoked_view["listed"] is False


def test_immediate_consistency_of_school_computed_fields(api):
    """PRD section 2.4: "Audit creation, classroom creation, student transfers,
    improvement-plan auto-creation, and the recomputation of computed fields
    (`compliant_classroom_count`, `directory_visible`, `annual_dues_cents`,
    `total_enrollment`) never bump `School.version`; those computed fields are
    derived on read." PRD section 3.2: "its `total_enrollment` — the sum of
    `enrolled_student_count` over all of its classrooms, regardless of audit
    state".

    Design: Corner/consistency_model/immediate_consistency_of_school_computed_fields
    """
    reset_clock()
    create_active_catalog()
    school = create_school(name="K School", display_name="K Schoolhouse")
    room1 = create_classroom(school["id"], name="K1", enrolled_student_count=10)
    create_classroom(school["id"], name="K2", enrolled_student_count=14)
    file_classroom_audit(
        room1["id"], students_present=10, adults_present=1, materials_groups=FULL_MATERIALS
    )

    school = read_school(school["id"])
    assert school["total_enrollment"] == 24, "10 + 14 visible immediately"
    assert school["compliant_classroom_count"] == 1, "the unaudited room does not count"
