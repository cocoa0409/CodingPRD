"""Refusal-surface compliance tests for the LMS course-shell service.

Every test in this module drives the public HTTP API only, through the `api`
fixture, and rebuilds all of its preconditions from an empty database. The
logical clock reads 2026-08-01T00:00:00Z at the start of each test.
"""
from test_helpers import (
    advance_clock,
    get_success_data,
    make_instructor_headers,
    make_lms_admin_headers,
    make_registrar_headers,
    make_student_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

TERM_START = "2026-08-24T00:00:00Z"
TERM_END = "2026-12-11T00:00:00Z"
SPRING_START = "2027-01-11T00:00:00Z"
SPRING_END = "2027-05-07T00:00:00Z"


def _num(value):
    """Compare a JSON money/decimal figure at two-decimal precision."""
    return round(float(value), 2)


def test_auth_role_and_ownership_gates_fire_before_any_business_rule(
    api, registrar_headers, lms_admin_headers
):
    """Trip the three highest refusal bands with three different requests.

    PRD 2.1: "Every request must carry two headers: `X-User-ID`, identifying the
    acting user, and `X-User-Role`, declaring the capacity in which they act. If
    either header is absent or empty, the request is rejected with
    `ERR_UNAUTHENTICATED` (401)."

    PRD 2.1: "A value of `X-User-Role` that is not one of those six, or that is
    not listed among the authorized roles for the endpoint being called, is
    rejected with `ERR_ROLE_NOT_PERMITTED` (403)."

    PRD 2.1: "Ownership enforcement produces `ERR_NOT_RESOURCE_OWNER` (403) and
    applies to exactly these operations: `POST /content-items`,
    `PATCH /content-items/{id}`, `DELETE /content-items/{id}`,
    `POST /tool-placements`, `POST /tool-placements/{id}/transitions`,
    `POST /grade-passbacks`, `POST /grade-passbacks/{id}/transitions`,
    `POST /grade-disputes`, `POST /grade-disputes/{id}/resolve`, and
    `GET /enrollments`."

    PRD 2.1: "An `Instructor` acting on a shell whose `owner_person_id` differs
    from their `X-User-ID` is rejected there, as is a `Student` acting on an
    enrollment whose `person_id` differs from their `X-User-ID`."

    Design: Corner/errors/authentication_and_ownership_gates_fire_before_any_business_rule
    """
    term = validate_success(
        api.create_academic_term(
            {
                "term_code": "2026FA",
                "term_start_at": TERM_START,
                "term_end_at": TERM_END,
            },
            registrar_headers,
        ),
        201,
    )
    prof_a = validate_success(
        api.create_person(
            {
                "sis_person_id": "F-6180",
                "full_name": "Emmy Noether",
                "primary_affiliation": "FACULTY",
            },
            registrar_headers,
        ),
        201,
    )
    prof_b = validate_success(
        api.create_person(
            {
                "sis_person_id": "F-6181",
                "full_name": "Sofya Kovalevskaya",
                "primary_affiliation": "FACULTY",
            },
            registrar_headers,
        ),
        201,
    )
    shell = validate_success(
        api.create_course_shell(
            {
                "term_id": term["id"],
                "owner_person_id": prof_a["id"],
                "sis_section_code": "PH101-01",
                "shell_type": "OFFICIAL",
                "base_seat_cap": 25,
            },
            lms_admin_headers,
        ),
        201,
    )

    validate_error(api.list_academic_terms({}), "ERR_UNAUTHENTICATED")

    validate_error(
        api.create_academic_term(
            {
                "term_code": "2027SP",
                "term_start_at": SPRING_START,
                "term_end_at": SPRING_END,
            },
            make_student_headers(prof_b["id"]),
        ),
        "ERR_ROLE_NOT_PERMITTED",
    )

    validate_error(
        api.create_content_item(
            {
                "shell_id": shell["id"],
                "item_type": "PAGE",
                "title": "not my shell",
                "points_possible": 0.00,
                "storage_mb": 1.00,
            },
            make_instructor_headers(prof_b["id"]),
        ),
        "ERR_NOT_RESOURCE_OWNER",
    )

    validate_success(
        api.create_content_item(
            {
                "shell_id": shell["id"],
                "item_type": "PAGE",
                "title": "my shell",
                "points_possible": 0.00,
                "storage_mb": 1.00,
            },
            make_instructor_headers(prof_a["id"]),
        ),
        201,
    )

    terms, terms_meta = validate_paginated(api.list_academic_terms(lms_admin_headers))
    assert terms_meta["total_count"] == 1
    assert [t["id"] for t in terms] == [term["id"]]


def test_merge_requests_refuse_cross_term_absorbed_and_chained_shell_pairs(
    api, registrar_headers, lms_admin_headers
):
    """Reject four illegal shell pairings around one applied cross-list merge.

    PRD 3.5: "The lifecycle runs `DRAFT` → `SUBMITTED` → `APPROVED` → `APPLIED`
    → `REVERSED`, with a divergent decision branch to the terminal `DECLINED`."

    PRD 3.5: "The child shell itself moves `PROVISIONED` → `MERGED`, or
    `PUBLISHED` → `MERGED` if it was live, taking `merged_into_shell_id` to the
    parent's identifier, zeroing its `active_enrollment_count` and
    `waitlisted_enrollment_count`, setting its `seat_utilization_pct` to 0.00 and
    its `overflow_flag` to false, and — in the published case only — lowering the
    term's `published_shell_count` by one."

    PRD 3.5: "The parent's `active_enrollment_count`, `seat_utilization_pct` and
    `overflow_flag` are re-derived and its `absorbed_child_count` rises by one."

    PRD 2.10: "20. The child shell of a merge is not already absorbed — its
    `merged_into_shell_id` is null and its `provisioning_state` is not `MERGED`.
    On `POST /merge-requests` and on `POST /merge-requests/{id}/transitions` with
    action `APPLY` — otherwise `ERR_SHELL_ALREADY_MERGED`."

    PRD 2.10: "21. Both shells of a merge share the same `term_id` and both have
    `shell_type` `OFFICIAL`, on `POST /merge-requests` — otherwise
    `ERR_CROSS_TERM_MERGE`."

    PRD 2.10: "22. No merge chains: the parent shell's own
    `merged_into_shell_id` is null and the child's `absorbed_child_count` is 0.
    On `POST /merge-requests` — otherwise `ERR_MERGE_CHAIN_FORBIDDEN`."

    Design: Corner/errors/merge_requests_refuse_cross_term_absorbed_and_chained_shell_pairs
    """
    adm_1 = make_lms_admin_headers("adm-1")
    adm_2 = make_lms_admin_headers("adm-2")

    t1 = validate_success(
        api.create_academic_term(
            {
                "term_code": "2026FA",
                "term_start_at": TERM_START,
                "term_end_at": TERM_END,
            },
            registrar_headers,
        ),
        201,
    )
    validate_success(
        api.term_lifecycle_transition(
            t1["id"], {"target_state": "REGISTRATION_OPEN"}, registrar_headers
        )
    )
    t2 = validate_success(
        api.create_academic_term(
            {
                "term_code": "2027SP",
                "term_start_at": SPRING_START,
                "term_end_at": SPRING_END,
            },
            registrar_headers,
        ),
        201,
    )
    validate_success(
        api.term_lifecycle_transition(
            t2["id"], {"target_state": "REGISTRATION_OPEN"}, registrar_headers
        )
    )
    prof = validate_success(
        api.create_person(
            {
                "sis_person_id": "F-6190",
                "full_name": "Grace Hopper",
                "primary_affiliation": "FACULTY",
            },
            registrar_headers,
        ),
        201,
    )

    def provisioned(term_id, section_code):
        created = validate_success(
            api.create_course_shell(
                {
                    "term_id": term_id,
                    "owner_person_id": prof["id"],
                    "sis_section_code": section_code,
                    "shell_type": "OFFICIAL",
                    "base_seat_cap": 20,
                },
                lms_admin_headers,
            ),
            201,
        )
        return validate_success(
            api.shell_provisioning_decision(
                created["id"], {"decision": "APPROVE"}, lms_admin_headers
            )
        )

    parent = provisioned(t1["id"], "LT100-01")
    child = provisioned(t1["id"], "LT100-02")
    spare = provisioned(t1["id"], "LT100-03")
    other_term_shell = provisioned(t2["id"], "LT100-01")

    m1 = validate_success(
        api.create_merge_request(
            {
                "parent_shell_id": parent["id"],
                "child_shell_id": child["id"],
                "expected_parent_shell_version": parent["version"],
                "justification": "cross-listed section",
            },
            adm_1,
        ),
        201,
    )
    validate_success(
        api.merge_request_transition(m1["id"], {"action": "SUBMIT"}, adm_1)
    )
    validate_success(
        api.merge_request_transition(m1["id"], {"action": "APPROVE"}, adm_2)
    )
    applied = validate_success(
        api.merge_request_transition(m1["id"], {"action": "APPLY"}, adm_2)
    )
    assert applied["merge_state"] == "APPLIED"

    child_after = validate_success(
        api.get_course_shell(child["id"], lms_admin_headers)
    )
    assert child_after["provisioning_state"] == "MERGED"
    assert child_after["merged_into_shell_id"] == parent["id"]

    parent_after = validate_success(
        api.get_course_shell(parent["id"], lms_admin_headers)
    )
    assert parent_after["absorbed_child_count"] == 1

    validate_error(
        api.create_merge_request(
            {
                "parent_shell_id": parent["id"],
                "child_shell_id": other_term_shell["id"],
                "expected_parent_shell_version": parent_after["version"],
            },
            adm_1,
        ),
        "ERR_CROSS_TERM_MERGE",
    )

    spare_now = validate_success(api.get_course_shell(spare["id"], lms_admin_headers))
    validate_error(
        api.create_merge_request(
            {
                "parent_shell_id": spare["id"],
                "child_shell_id": child["id"],
                "expected_parent_shell_version": spare_now["version"],
            },
            adm_1,
        ),
        "ERR_SHELL_ALREADY_MERGED",
    )

    child_now = validate_success(api.get_course_shell(child["id"], lms_admin_headers))
    validate_error(
        api.create_merge_request(
            {
                "parent_shell_id": child["id"],
                "child_shell_id": spare["id"],
                "expected_parent_shell_version": child_now["version"],
            },
            adm_1,
        ),
        "ERR_MERGE_CHAIN_FORBIDDEN",
    )

    validate_error(
        api.create_merge_request(
            {
                "parent_shell_id": spare["id"],
                "child_shell_id": parent["id"],
                "expected_parent_shell_version": spare_now["version"],
            },
            adm_1,
        ),
        "ERR_MERGE_CHAIN_FORBIDDEN",
    )

    merges, merges_meta = validate_paginated(
        api.list_merge_requests(
            lms_admin_headers, params={"parent_shell_id": parent["id"]}
        )
    )
    assert [m["id"] for m in merges] == [m1["id"]]
    assert merges_meta["total_count"] == 1

    all_merges, all_meta = validate_paginated(
        api.list_merge_requests(lms_admin_headers)
    )
    assert all_meta["total_count"] == 1


def test_enrollment_creation_refuses_wrong_shell_states_and_conflicting_roles(
    api, registrar_headers, lms_admin_headers
):
    """Refuse a REQUESTED shell and three separate role-integrity violations.

    PRD 2.10: "31. The shell's `provisioning_state` permits the operation:
    `PROVISIONED` or `PUBLISHED` for enrollment and placement, `PUBLISHED` or
    `CONCLUDED` for passback staging. `REQUESTED`, `REJECTED`, `MERGED`,
    `ARCHIVED` and `PURGED` shells reject all three. On `POST /enrollments`,
    `POST /tool-placements` and `POST /grade-passbacks` — otherwise
    `ERR_SHELL_STATE_BLOCKS_ENROLLMENT`."

    PRD 2.10: "35. Role-assignment integrity, on `POST /enrollments`,
    `POST /enrollment-sync-batches/{id}/transitions` and `POST /grade-disputes`
    — otherwise `ERR_ROLE_CONFLICT`. A person holds at most one enrollment per
    shell whose `enrollment_state` is `ACTIVE`, `WAITLISTED` or `DROPPED`; a
    dropped row must be reinstated rather than re-created, and only a
    `COMPLETED` row frees the pair for a fresh enrollment. A `STUDENT` role may
    not coexist with a `TEACHER` role for the same person and shell, the shell's
    `owner_person_id` may not hold a `STUDENT` enrollment in their own shell, and
    a student may hold at most one open dispute per enrollment."

    PRD 3.4: "The new row opens in `enrollment_state` `ACTIVE`; when its `role`
    is `STUDENT` the shell's `active_enrollment_count` and the term's
    `total_active_enrollments` each rise by one, and the shell's
    `seat_utilization_pct` and `overflow_flag` are re-derived."

    PRD 3.4: "**Dropping** takes `ACTIVE` → `DROPPED` and needs only that the
    shell be `PROVISIONED` or `PUBLISHED` (otherwise
    `ERR_SHELL_STATE_BLOCKS_ENROLLMENT`)."

    PRD 3.4: "Only rows whose `role` is `STUDENT` participate in any of this —
    `TEACHER`, `TA`, `DESIGNER` and `OBSERVER` rows never consume a seat and
    never appear on a waitlist."

    PRD 3.4: "Zero is a live boundary: a shell whose only active row drops reads
    `active_enrollment_count` 0, `seat_utilization_pct` 0.00 and `overflow_flag`
    false, and the term falls by exactly one."

    Design: Corner/errors/enrollment_creation_refuses_wrong_shell_states_and_conflicting_roles
    """
    term = validate_success(
        api.create_academic_term(
            {
                "term_code": "2026FA",
                "term_start_at": TERM_START,
                "term_end_at": TERM_END,
            },
            registrar_headers,
        ),
        201,
    )
    validate_success(
        api.term_lifecycle_transition(
            term["id"], {"target_state": "REGISTRATION_OPEN"}, registrar_headers
        )
    )
    prof = validate_success(
        api.create_person(
            {
                "sis_person_id": "F-6200",
                "full_name": "Maryam Mirzakhani",
                "primary_affiliation": "FACULTY",
            },
            registrar_headers,
        ),
        201,
    )
    student = validate_success(
        api.create_person(
            {
                "sis_person_id": "S-6201",
                "full_name": "Learner E",
                "primary_affiliation": "STUDENT",
            },
            registrar_headers,
        ),
        201,
    )
    sa = validate_success(
        api.create_course_shell(
            {
                "term_id": term["id"],
                "owner_person_id": prof["id"],
                "sis_section_code": "GE140-01",
                "shell_type": "OFFICIAL",
                "base_seat_cap": 10,
            },
            lms_admin_headers,
        ),
        201,
    )
    validate_success(
        api.shell_provisioning_decision(
            sa["id"], {"decision": "APPROVE"}, lms_admin_headers
        )
    )
    sb = validate_success(
        api.create_course_shell(
            {
                "term_id": term["id"],
                "owner_person_id": prof["id"],
                "sis_section_code": "GE140-02",
                "shell_type": "OFFICIAL",
                "base_seat_cap": 10,
            },
            lms_admin_headers,
        ),
        201,
    )
    assert sb["provisioning_state"] == "REQUESTED"

    validate_error(
        api.create_enrollment(
            {"shell_id": sb["id"], "person_id": student["id"], "role": "STUDENT"},
            registrar_headers,
        ),
        "ERR_SHELL_STATE_BLOCKS_ENROLLMENT",
    )

    e1 = validate_success(
        api.create_enrollment(
            {"shell_id": sa["id"], "person_id": student["id"], "role": "STUDENT"},
            registrar_headers,
        ),
        201,
    )
    assert e1["enrollment_state"] == "ACTIVE"

    validate_error(
        api.create_enrollment(
            {"shell_id": sa["id"], "person_id": student["id"], "role": "TA"},
            registrar_headers,
        ),
        "ERR_ROLE_CONFLICT",
    )
    validate_error(
        api.create_enrollment(
            {"shell_id": sa["id"], "person_id": prof["id"], "role": "STUDENT"},
            registrar_headers,
        ),
        "ERR_ROLE_CONFLICT",
    )

    e2 = validate_success(
        api.create_enrollment(
            {"shell_id": sa["id"], "person_id": prof["id"], "role": "TEACHER"},
            registrar_headers,
        ),
        201,
    )
    assert e2["role"] == "TEACHER"

    dropped = validate_success(
        api.enrollment_transition(e1["id"], {"action": "DROP"}, registrar_headers)
    )
    assert dropped["enrollment_state"] == "DROPPED"

    validate_error(
        api.create_enrollment(
            {"shell_id": sa["id"], "person_id": student["id"], "role": "OBSERVER"},
            registrar_headers,
        ),
        "ERR_ROLE_CONFLICT",
    )

    sa_after = validate_success(api.get_course_shell(sa["id"], lms_admin_headers))
    assert sa_after["active_enrollment_count"] == 0

    rows, meta = validate_paginated(
        api.list_enrollments(registrar_headers, params={"shell_id": sa["id"]})
    )
    assert meta["total_count"] == 2
    assert sorted(r["id"] for r in rows) == sorted([e1["id"], e2["id"]])


def test_passback_staging_refuses_duplicates_ungraded_books_and_submitted_items(
    api, registrar_headers, lms_admin_headers
):
    """Refuse a submitted-item delete, a duplicate passback and an empty book.

    PRD 2.10: "41. A content item whose `has_submissions` is true may not be
    deleted, on `DELETE /content-items/{id}` — otherwise
    `ERR_ITEM_HAS_SUBMISSIONS`."

    PRD 2.10: "10. At most one passback exists per `shell_id`, on
    `POST /grade-passbacks` — otherwise `ERR_DUPLICATE_PASSBACK`."

    PRD 2.10: "37. Submitting a passback requires at least one staged enrollment
    whose `graded_points_possible` is greater than 0, on
    `POST /grade-passbacks/{id}/transitions` with action `SUBMIT` — otherwise
    `ERR_NO_GRADES_STAGED`."

    PRD 3.6: "A submission is recorded against an item by naming the
    `enrollment_id` it belongs to; the item's `has_submissions` becomes true and
    its `submission_count` rises by one."

    PRD 3.8: "The passback opens in `passback_state` `STAGED` with `term_id`
    copied from the shell, `variant_applied` `PROVISIONAL`,
    `staged_enrollment_count` set to the number of gradable rows described above,
    and every provisional percentage computed."

    PRD 3.8: "Each write re-derives the enrollment's `earned_points_total` as the
    sum of its grade records and its `graded_points_possible` as the sum of the
    `points_possible` of the items it now carries a record for, and re-derives
    that enrollment's `provisional_grade_pct`."

    PRD 3.8: "The **provisional** variant divides by the enrollment's own
    `graded_points_possible` — the work graded so far — which flatters an
    incomplete gradebook, and it writes `provisional_grade_pct`."

    PRD 3.8: "Submitting flips `variant_applied` to `FINAL`, recomputes every
    staged enrollment's `final_grade_pct` under the final variant, sets
    `submitted_points_total` to the sum of the staged enrollments'
    `earned_points_total`, and sets `accepted_points_total` and
    `disputed_points_held` to 0.00."

    PRD 3.8: "The **final** variant divides by the shell's
    `total_points_possible` — every gradable point in the shell, graded or not —
    so missing work drags the figure down, and it writes `final_grade_pct`."

    PRD 4: "Successful creates answer with `201 Created`, successful reads,
    updates, transitions and decisions with `200 OK`, and the single delete with
    `204 No Content` and an empty body."

    Design: Corner/errors/passback_staging_refuses_duplicates_ungraded_books_and_submitted_item_deletion
    """
    term = validate_success(
        api.create_academic_term(
            {
                "term_code": "2026FA",
                "term_start_at": TERM_START,
                "term_end_at": TERM_END,
            },
            registrar_headers,
        ),
        201,
    )
    validate_success(
        api.term_lifecycle_transition(
            term["id"], {"target_state": "REGISTRATION_OPEN"}, registrar_headers
        )
    )
    prof = validate_success(
        api.create_person(
            {
                "sis_person_id": "F-6210",
                "full_name": "Mary Cartwright",
                "primary_affiliation": "FACULTY",
            },
            registrar_headers,
        ),
        201,
    )
    student = validate_success(
        api.create_person(
            {
                "sis_person_id": "S-6211",
                "full_name": "Learner F",
                "primary_affiliation": "STUDENT",
            },
            registrar_headers,
        ),
        201,
    )
    shell = validate_success(
        api.create_course_shell(
            {
                "term_id": term["id"],
                "owner_person_id": prof["id"],
                "sis_section_code": "MU160-01",
                "shell_type": "OFFICIAL",
                "base_seat_cap": 12,
            },
            lms_admin_headers,
        ),
        201,
    )
    validate_success(
        api.shell_provisioning_decision(
            shell["id"], {"decision": "APPROVE"}, lms_admin_headers
        )
    )
    published = validate_success(api.publish_shell(shell["id"], lms_admin_headers))
    assert published["provisioning_state"] == "PUBLISHED"

    enrollment = validate_success(
        api.create_enrollment(
            {"shell_id": shell["id"], "person_id": student["id"], "role": "STUDENT"},
            registrar_headers,
        ),
        201,
    )
    owner = make_instructor_headers(prof["id"])
    i1 = validate_success(
        api.create_content_item(
            {
                "shell_id": shell["id"],
                "item_type": "ASSIGNMENT",
                "title": "Midterm",
                "points_possible": 100.00,
                "storage_mb": 2.00,
            },
            owner,
        ),
        201,
    )
    i2 = validate_success(
        api.create_content_item(
            {
                "shell_id": shell["id"],
                "item_type": "PAGE",
                "title": "Reading list",
                "points_possible": 0.00,
                "storage_mb": 1.00,
            },
            owner,
        ),
        201,
    )
    get_success_data(
        api.create_submission(i1["id"], {"enrollment_id": enrollment["id"]}, owner)
    )
    submitted_item = validate_success(api.get_content_item(i1["id"], owner))
    assert submitted_item["has_submissions"] is True
    assert submitted_item["submission_count"] == 1

    validate_success(
        api.term_lifecycle_transition(
            term["id"], {"target_state": "IN_SESSION"}, registrar_headers
        )
    )
    in_finals = validate_success(
        api.term_lifecycle_transition(
            term["id"], {"target_state": "FINALS"}, registrar_headers
        )
    )
    assert in_finals["lifecycle_state"] == "FINALS"

    validate_error(
        api.delete_content_item(i1["id"], owner), "ERR_ITEM_HAS_SUBMISSIONS"
    )
    still_there = validate_success(api.get_content_item(i1["id"], owner))
    assert still_there["id"] == i1["id"]

    removed = api.delete_content_item(i2["id"], owner)
    assert removed.status_code == 204, removed.text

    passback = validate_success(
        api.create_grade_passback({"shell_id": shell["id"]}, owner), 201
    )
    assert passback["passback_state"] == "STAGED"
    assert passback["staged_enrollment_count"] == 1
    assert passback["variant_applied"] == "PROVISIONAL"

    validate_error(
        api.create_grade_passback({"shell_id": shell["id"]}, owner),
        "ERR_DUPLICATE_PASSBACK",
    )
    passbacks, passbacks_meta = validate_paginated(
        api.list_grade_passbacks(lms_admin_headers, params={"shell_id": shell["id"]})
    )
    assert [p["id"] for p in passbacks] == [passback["id"]]
    assert passbacks_meta["total_count"] == 1

    validate_error(
        api.grade_passback_transition(passback["id"], {"action": "SUBMIT"}, owner),
        "ERR_NO_GRADES_STAGED",
    )

    get_success_data(
        api.record_grade(
            {
                "enrollment_id": enrollment["id"],
                "content_item_id": i1["id"],
                "earned_points": 80.00,
            },
            owner,
        )
    )
    graded = validate_success(api.get_enrollment(enrollment["id"], owner))
    assert _num(graded["earned_points_total"]) == 80.00
    assert _num(graded["graded_points_possible"]) == 100.00
    assert _num(graded["provisional_grade_pct"]) == 80.00

    submitted = validate_success(
        api.grade_passback_transition(passback["id"], {"action": "SUBMIT"}, owner)
    )
    assert submitted["passback_state"] == "SUBMITTED"
    assert _num(submitted["submitted_points_total"]) == 80.00
    assert submitted["variant_applied"] == "FINAL"

    final = validate_success(api.get_enrollment(enrollment["id"], owner))
    assert _num(final["final_grade_pct"]) == 80.00


def test_student_reads_and_owner_provisioning_respect_access_and_ferpa_gates(
    api, registrar_headers, lms_admin_headers
):
    """Refuse a revoked owner's provisioning and an expired student read.

    PRD 3.3: "Two compliance switches may be set at registration or adjusted
    later, together with the display name: `ferpa_block`, which defaults to false
    and when true forbids exporting that person's records to a third-party tool
    or to the registrar, and `access_revoked_at`, the instant at which LMS access
    was withdrawn, which stays null while access is live."

    PRD 3.1: "A grace period of 0 days is legal and collapses
    `student_access_end_at` onto the term's own end date at 23:59:59, so a
    student read at exactly that instant still succeeds while one instant later
    fails with `ERR_STUDENT_ACCESS_EXPIRED`."

    PRD 3.3: "`APPROVE` moves `REQUESTED` → `PROVISIONED`, and requires the
    shell's term to be in `PLANNING`, `REGISTRATION_OPEN` or `IN_SESSION`
    (otherwise `ERR_INVALID_STATE_TRANSITION`) and the owner's
    `access_revoked_at` to be null (otherwise `ERR_FERPA_BLOCK_ACTIVE`)."

    PRD 3.1: "A `Student` reading their own enrollments, reading a single shell,
    or filing a dispute must act at or before the term's `student_access_end_at`,
    and the acting person's `access_revoked_at` must be either null or still in
    the future; otherwise the read or filing is refused with
    `ERR_STUDENT_ACCESS_EXPIRED`."

    PRD 2.10: "13. No person whose `ferpa_block` is true is exposed by the
    operation, on `POST /tool-placements/{id}/transitions` with action `ACTIVATE`
    and on `POST /grade-passbacks/{id}/transitions` with action `SUBMIT` —
    otherwise `ERR_FERPA_BLOCK_ACTIVE`."

    PRD 2.10: "14. A student read or dispute filing happens at or before the
    term's `student_access_end_at`, and the acting person's `access_revoked_at`
    is either null or still in the future. On `GET /enrollments`,
    `GET /course-shells/{id}` and `POST /grade-disputes` — otherwise
    `ERR_STUDENT_ACCESS_EXPIRED`."

    Design: Corner/errors/student_reads_and_owner_provisioning_respect_the_access_and_ferpa_gates
    """
    term = validate_success(
        api.create_academic_term(
            {
                "term_code": "2026FA",
                "term_start_at": TERM_START,
                "term_end_at": TERM_END,
                "access_grace_days": 0,
            },
            registrar_headers,
        ),
        201,
    )
    assert term["student_access_end_at"] == "2026-12-11T23:59:59Z"

    validate_success(
        api.term_lifecycle_transition(
            term["id"], {"target_state": "REGISTRATION_OPEN"}, registrar_headers
        )
    )
    prof = validate_success(
        api.create_person(
            {
                "sis_person_id": "F-6220",
                "full_name": "Rosalind Franklin",
                "primary_affiliation": "FACULTY",
            },
            registrar_headers,
        ),
        201,
    )
    revoked = validate_success(
        api.create_person(
            {
                "sis_person_id": "F-6221",
                "full_name": "Departed Lecturer",
                "primary_affiliation": "FACULTY",
                "access_revoked_at": "2026-07-01T00:00:00Z",
            },
            registrar_headers,
        ),
        201,
    )
    assert revoked["access_revoked_at"] == "2026-07-01T00:00:00Z"

    student = validate_success(
        api.create_person(
            {
                "sis_person_id": "S-6222",
                "full_name": "Learner G",
                "primary_affiliation": "STUDENT",
            },
            registrar_headers,
        ),
        201,
    )
    shell = validate_success(
        api.create_course_shell(
            {
                "term_id": term["id"],
                "owner_person_id": prof["id"],
                "sis_section_code": "PY230-01",
                "shell_type": "OFFICIAL",
                "base_seat_cap": 18,
            },
            lms_admin_headers,
        ),
        201,
    )
    validate_success(
        api.shell_provisioning_decision(
            shell["id"], {"decision": "APPROVE"}, lms_admin_headers
        )
    )
    enrollment = validate_success(
        api.create_enrollment(
            {"shell_id": shell["id"], "person_id": student["id"], "role": "STUDENT"},
            registrar_headers,
        ),
        201,
    )
    revoked_shell = validate_success(
        api.create_course_shell(
            {
                "term_id": term["id"],
                "owner_person_id": revoked["id"],
                "sis_section_code": "PY230-02",
                "shell_type": "OFFICIAL",
                "base_seat_cap": 18,
            },
            lms_admin_headers,
        ),
        201,
    )
    assert revoked_shell["provisioning_state"] == "REQUESTED"

    validate_error(
        api.shell_provisioning_decision(
            revoked_shell["id"], {"decision": "APPROVE"}, lms_admin_headers
        ),
        "ERR_FERPA_BLOCK_ACTIVE",
    )
    still_requested = validate_success(
        api.get_course_shell(revoked_shell["id"], lms_admin_headers)
    )
    assert still_requested["provisioning_state"] == "REQUESTED"

    learner = make_student_headers(student["id"])
    early_read = validate_success(api.get_course_shell(shell["id"], learner))
    assert early_read["provisioning_state"] == "PROVISIONED"

    advance_clock(api, "2026-12-12T00:00:00Z", lms_admin_headers)

    validate_error(
        api.get_course_shell(shell["id"], learner), "ERR_STUDENT_ACCESS_EXPIRED"
    )
    validate_error(
        api.list_enrollments(learner, params={"person_id": student["id"]}),
        "ERR_STUDENT_ACCESS_EXPIRED",
    )

    admin_read = validate_success(api.get_course_shell(shell["id"], lms_admin_headers))
    assert admin_read["provisioning_state"] == "PROVISIONED"

    registrar_read = validate_success(
        api.get_enrollment(enrollment["id"], registrar_headers)
    )
    assert registrar_read["enrollment_state"] == "ACTIVE"


def test_rollover_jobs_refuse_ineligible_sources_and_non_empty_targets(
    api, registrar_headers, lms_admin_headers
):
    """Refuse a live source shell and a target that still carries content.

    PRD 2.10: "33. A rollover job's source shell has a `provisioning_state` of
    `CONCLUDED` or `ARCHIVED` and belongs to a term other than the target term,
    on `POST /rollover-jobs` and on `POST /rollover-jobs/{id}/transitions` with
    action `VALIDATE` — otherwise `ERR_ROLLOVER_SOURCE_INELIGIBLE`."

    PRD 2.10: "34. A rollover job's target shell has a `provisioning_state` of
    `REQUESTED` or `PROVISIONED`, a `content_item_count` of 0, and no
    enrollments, on `POST /rollover-jobs` and on
    `POST /rollover-jobs/{id}/transitions` with action `VALIDATE` — otherwise
    `ERR_ROLLOVER_TARGET_NOT_EMPTY`."

    PRD 3.3: "The archival tail is driven by a `Registrar` supplying a
    `target_state`, and it can also arrive as the term-closing cascade of §3.2."

    PRD 3.6: "An `LmsAdmin` stages one by naming `source_shell_id`,
    `target_shell_id` and `target_term_id`, supplying the mandatory
    `expected_target_shell_version`, and optionally overriding four switches:
    `strip_dates` (default true), `strip_submissions` (default true),
    `strip_grades` (default true) and `date_shift_mode` (default
    `ANCHOR_PROPORTIONAL`, the alternative being `FIXED_OFFSET`)."

    PRD 3.6: "The job opens in `job_state` `DRAFT` with every tally at zero."

    PRD 3.6: "Validation sets `eligible_item_count` to the number of the source
    shell's items whose `copy_state` is not `SKIPPED`, and copies nothing."

    Design: Corner/errors/rollover_jobs_refuse_ineligible_sources_and_non_empty_targets
    """
    t1 = validate_success(
        api.create_academic_term(
            {
                "term_code": "2026FA",
                "term_start_at": TERM_START,
                "term_end_at": TERM_END,
            },
            registrar_headers,
        ),
        201,
    )
    validate_success(
        api.term_lifecycle_transition(
            t1["id"], {"target_state": "REGISTRATION_OPEN"}, registrar_headers
        )
    )
    t2 = validate_success(
        api.create_academic_term(
            {
                "term_code": "2027SP",
                "term_start_at": SPRING_START,
                "term_end_at": SPRING_END,
            },
            registrar_headers,
        ),
        201,
    )
    validate_success(
        api.term_lifecycle_transition(
            t2["id"], {"target_state": "REGISTRATION_OPEN"}, registrar_headers
        )
    )
    prof = validate_success(
        api.create_person(
            {
                "sis_person_id": "F-6230",
                "full_name": "Chien-Shiung Wu",
                "primary_affiliation": "FACULTY",
            },
            registrar_headers,
        ),
        201,
    )

    def provisioned(term_id, section_code):
        created = validate_success(
            api.create_course_shell(
                {
                    "term_id": term_id,
                    "owner_person_id": prof["id"],
                    "sis_section_code": section_code,
                    "shell_type": "OFFICIAL",
                    "base_seat_cap": 30,
                },
                lms_admin_headers,
            ),
            201,
        )
        return validate_success(
            api.shell_provisioning_decision(
                created["id"], {"decision": "APPROVE"}, lms_admin_headers
            )
        )

    owner = make_instructor_headers(prof["id"])
    source = provisioned(t1["id"], "PS410-01")
    assert source["provisioning_state"] == "PROVISIONED"
    validate_success(
        api.create_content_item(
            {
                "shell_id": source["id"],
                "item_type": "ASSIGNMENT",
                "title": "Lab 1",
                "due_at": "2026-09-10T23:59:00Z",
                "points_possible": 40.00,
                "storage_mb": 3.00,
            },
            owner,
        ),
        201,
    )
    validate_success(
        api.create_content_item(
            {
                "shell_id": source["id"],
                "item_type": "PAGE",
                "title": "Course policy",
                "points_possible": 0.00,
                "storage_mb": 1.00,
            },
            owner,
        ),
        201,
    )

    target_a = provisioned(t2["id"], "PS410-01")
    target_b = provisioned(t2["id"], "PS410-02")
    validate_success(
        api.create_content_item(
            {
                "shell_id": target_b["id"],
                "item_type": "PAGE",
                "title": "leftover draft",
                "points_possible": 0.00,
                "storage_mb": 1.00,
            },
            owner,
        ),
        201,
    )

    validate_error(
        api.create_rollover_job(
            {
                "source_shell_id": source["id"],
                "target_shell_id": target_a["id"],
                "target_term_id": t2["id"],
                "expected_target_shell_version": target_a["version"],
            },
            lms_admin_headers,
        ),
        "ERR_ROLLOVER_SOURCE_INELIGIBLE",
    )

    concluded = validate_success(
        api.shell_lifecycle_transition(
            source["id"], {"target_state": "CONCLUDED"}, registrar_headers
        )
    )
    assert concluded["provisioning_state"] == "CONCLUDED"

    target_b_now = validate_success(
        api.get_course_shell(target_b["id"], lms_admin_headers)
    )
    assert target_b_now["content_item_count"] == 1
    validate_error(
        api.create_rollover_job(
            {
                "source_shell_id": source["id"],
                "target_shell_id": target_b["id"],
                "target_term_id": t2["id"],
                "expected_target_shell_version": target_b_now["version"],
            },
            lms_admin_headers,
        ),
        "ERR_ROLLOVER_TARGET_NOT_EMPTY",
    )

    target_a_now = validate_success(
        api.get_course_shell(target_a["id"], lms_admin_headers)
    )
    assert target_a_now["content_item_count"] == 0
    job = validate_success(
        api.create_rollover_job(
            {
                "source_shell_id": source["id"],
                "target_shell_id": target_a["id"],
                "target_term_id": t2["id"],
                "expected_target_shell_version": target_a_now["version"],
            },
            lms_admin_headers,
        ),
        201,
    )
    assert job["job_state"] == "DRAFT"
    assert job["strip_dates"] is True
    assert job["date_shift_mode"] == "ANCHOR_PROPORTIONAL"

    validated = validate_success(
        api.rollover_job_transition(job["id"], {"action": "VALIDATE"}, lms_admin_headers)
    )
    assert validated["job_state"] == "VALIDATED"
    assert validated["eligible_item_count"] == 2

    jobs, jobs_meta = validate_paginated(
        api.list_rollover_jobs(
            lms_admin_headers, params={"target_shell_id": target_a["id"]}
        )
    )
    assert [j["id"] for j in jobs] == [job["id"]]
    assert jobs_meta["total_count"] == 1


def test_an_open_dispute_blocks_the_term_from_closing_until_it_is_resolved(
    api, lms_admin_headers
):
    """Block GRADING -> CLOSED while one dispute is open, then close cleanly.

    PRD 2.10: "38. Closing a term requires its `open_amendment_count` to be 0,
    meaning no passback of the term sits in `DISPUTED` or `AMENDED`. On
    `POST /academic-terms/{id}/lifecycle-transitions` targeting `CLOSED` —
    otherwise `ERR_OPEN_DISPUTES_BLOCK_CLOSE`."

    PRD 3.8: "**Accepting** takes `SUBMITTED` → `ACCEPTED` and sets
    `accepted_points_total` equal to `submitted_points_total`, leaving
    `disputed_points_held` at 0.00."

    PRD 3.8: "The dispute opens in `dispute_state` `OPEN` with `held_points` set
    to the enrollment's current `earned_points_total`, the enrollment's own
    `disputed_points_held` set to the same amount, and `filed_by_user_id`
    recorded from the acting user."

    PRD 3.8: "The **first** dispute against an accepted passback drives that
    passback `ACCEPTED` → `DISPUTED`, raising its `open_dispute_count` by one,
    moving the held points from accepted into disputed, and raising the term's
    `open_amendment_count` by one; a subsequent dispute against an
    already-disputed passback simply raises `open_dispute_count` and repeats the
    bucket move."

    PRD 3.8: "**Upholding** takes `OPEN` → `RESOLVED_UPHELD`, stamps
    `resolved_at` from the logical clock, leaves `adjusted_earned_points` null,
    leaves the enrollment's `earned_points_total` untouched while zeroing its
    `disputed_points_held`, and returns the held points from the passback's
    disputed bucket to its accepted bucket, restoring the accepted total to its
    pre-filing value with zero drift."

    PRD 3.8: "When the last open dispute resolves and **every** resolution in
    that round was upheld, the passback returns `DISPUTED` → `ACCEPTED` and the
    term's `open_amendment_count` falls by one — the round is ledger-neutral and
    costs the term nothing."

    PRD 2.5: "On startup the logical clock reads exactly
    `2026-08-01T00:00:00Z`, and it never falls back to real time."

    PRD 2.5: "Timestamps the server stamps itself — `dropped_at`, `resolved_at`,
    `closed_at` — are taken from the logical clock at the moment of the
    transition."

    PRD 3.2: "Hop one: every shell of the term whose `provisioning_state` is
    `PROVISIONED` or `PUBLISHED` and whose `merged_into_shell_id` is null
    transitions to `CONCLUDED`, processed in `created_at` ascending order."

    PRD 3.2: "Hop two: each of those conclusions moves that shell's enrollments
    whose `enrollment_state` is `ACTIVE` to `COMPLETED`."

    PRD 3.2: "The term's `published_shell_count` is then set to 0."

    Design: Corner/errors/an_open_dispute_blocks_the_term_from_closing_until_it_is_resolved
    """
    registrar = make_registrar_headers("reg-1")

    term = validate_success(
        api.create_academic_term(
            {
                "term_code": "2026FA",
                "term_start_at": TERM_START,
                "term_end_at": TERM_END,
            },
            registrar,
        ),
        201,
    )
    validate_success(
        api.term_lifecycle_transition(
            term["id"], {"target_state": "REGISTRATION_OPEN"}, registrar
        )
    )
    prof = validate_success(
        api.create_person(
            {
                "sis_person_id": "F-6240",
                "full_name": "Rita Levi-Montalcini",
                "primary_affiliation": "FACULTY",
            },
            registrar,
        ),
        201,
    )
    student = validate_success(
        api.create_person(
            {
                "sis_person_id": "S-6241",
                "full_name": "Learner H",
                "primary_affiliation": "STUDENT",
            },
            registrar,
        ),
        201,
    )
    shell = validate_success(
        api.create_course_shell(
            {
                "term_id": term["id"],
                "owner_person_id": prof["id"],
                "sis_section_code": "BI205-01",
                "shell_type": "OFFICIAL",
                "base_seat_cap": 15,
            },
            lms_admin_headers,
        ),
        201,
    )
    validate_success(
        api.shell_provisioning_decision(
            shell["id"], {"decision": "APPROVE"}, lms_admin_headers
        )
    )
    validate_success(api.publish_shell(shell["id"], lms_admin_headers))

    enrollment = validate_success(
        api.create_enrollment(
            {"shell_id": shell["id"], "person_id": student["id"], "role": "STUDENT"},
            registrar,
        ),
        201,
    )
    owner = make_instructor_headers(prof["id"])
    item = validate_success(
        api.create_content_item(
            {
                "shell_id": shell["id"],
                "item_type": "ASSIGNMENT",
                "title": "Final exam",
                "points_possible": 100.00,
                "storage_mb": 2.00,
            },
            owner,
        ),
        201,
    )
    get_success_data(
        api.record_grade(
            {
                "enrollment_id": enrollment["id"],
                "content_item_id": item["id"],
                "earned_points": 75.00,
            },
            owner,
        )
    )
    graded = validate_success(api.get_enrollment(enrollment["id"], owner))
    assert _num(graded["earned_points_total"]) == 75.00

    for target in ("IN_SESSION", "FINALS"):
        validate_success(
            api.term_lifecycle_transition(
                term["id"], {"target_state": target}, registrar
            )
        )

    passback = validate_success(
        api.create_grade_passback({"shell_id": shell["id"]}, owner), 201
    )
    submitted = validate_success(
        api.grade_passback_transition(passback["id"], {"action": "SUBMIT"}, owner)
    )
    assert _num(submitted["submitted_points_total"]) == 75.00

    accepted = validate_success(
        api.registrar_decision(
            passback["id"], {"decision": "ACCEPT", "note": "roster verified"}, registrar
        )
    )
    assert accepted["passback_state"] == "ACCEPTED"
    assert _num(accepted["accepted_points_total"]) == 75.00

    dispute = validate_success(
        api.create_grade_dispute(
            {
                "passback_id": passback["id"],
                "enrollment_id": enrollment["id"],
                "content_item_id": item["id"],
                "claimed_earned_points": 95.00,
            },
            make_student_headers(student["id"]),
        ),
        201,
    )
    assert dispute["dispute_state"] == "OPEN"
    assert _num(dispute["held_points"]) == 75.00

    disputed = validate_success(api.get_grade_passback(passback["id"], registrar))
    assert disputed["passback_state"] == "DISPUTED"
    assert disputed["open_dispute_count"] == 1
    assert _num(disputed["accepted_points_total"]) == 0.00
    assert _num(disputed["disputed_points_held"]) == 75.00

    grading = validate_success(
        api.term_lifecycle_transition(
            term["id"], {"target_state": "GRADING"}, registrar
        )
    )
    assert grading["lifecycle_state"] == "GRADING"
    assert grading["open_amendment_count"] == 1

    validate_error(
        api.term_lifecycle_transition(
            term["id"], {"target_state": "CLOSED"}, registrar
        ),
        "ERR_OPEN_DISPUTES_BLOCK_CLOSE",
    )
    blocked_term = validate_success(api.get_academic_term(term["id"], registrar))
    assert blocked_term["lifecycle_state"] == "GRADING"

    resolved = validate_success(
        api.resolve_grade_dispute(
            dispute["id"],
            {"outcome": "UPHELD", "note": "rubric re-checked, grade stands"},
            owner,
        )
    )
    assert resolved["dispute_state"] == "RESOLVED_UPHELD"
    assert resolved["resolved_at"] is not None
    assert resolved["resolved_at"].startswith("2026-08-01T00:00:00")

    after_resolve = validate_success(api.get_academic_term(term["id"], registrar))
    assert after_resolve["open_amendment_count"] == 0
    assert after_resolve["lifecycle_state"] == "GRADING"

    closed = validate_success(
        api.term_lifecycle_transition(
            term["id"], {"target_state": "CLOSED"}, registrar
        )
    )
    assert closed["lifecycle_state"] == "CLOSED"
    assert closed["published_shell_count"] == 0

    shell_after = validate_success(api.get_course_shell(shell["id"], registrar))
    assert shell_after["provisioning_state"] == "CONCLUDED"
    assert shell_after["active_enrollment_count"] == 0

    enrollment_after = validate_success(
        api.get_enrollment(enrollment["id"], registrar)
    )
    assert enrollment_after["enrollment_state"] == "COMPLETED"
