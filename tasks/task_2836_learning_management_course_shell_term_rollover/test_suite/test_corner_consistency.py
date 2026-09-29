"""Immediate consistency: no settling delay between a write and the next read.

The service declares no asynchronous processing: a write's own response already
carries the settled figures of every record it touched, and the read that
follows it agrees exactly.
"""
from test_helpers import (
    assert_term_seat_ledger,
    create_content_item_payload,
    create_enrollment_payload,
    create_faculty,
    create_student,
    create_term,
    get_success_data,
    grade_record_payload,
    make_instructor_headers,
    provisioning_decision,
    request_shell,
    transition_term,
    validate_paginated,
)

#: Statuses a successful write may answer with. The service declares no
#: accepted-for-later-processing branch anywhere, so 202 is never one of them.
WRITE_STATUSES = (200, 201)


def test_every_write_is_visible_to_the_next_read_with_no_settling_delay(
    api, registrar_headers, lms_admin_headers
):
    """A term, shell, enrollment, item, grade and drop read back immediately.

    Each write in the walk answers 200 or 201 with the affected record already
    carrying its settled figures, and the very next read of every touched
    record - shell, term and enrollment - agrees with what the write returned.

    PRD 2.8: "Third, cascades run to completion inside the request that
    triggered them; there is no deferred or eventual reconciliation, so a caller
    reading any affected record immediately afterwards sees its settled
    figures."
    PRD 2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD 2.8: "A term's `total_active_enrollments` always equals the sum of
    `active_enrollment_count` across that term's shells whose
    `provisioning_state` is neither `REJECTED` nor `PURGED`."
    PRD 3.3: "On approval `effective_seat_cap` is set equal to `base_seat_cap`,
    `publish_readiness` is set to true, and `sandbox_expires_at` is set to sixty
    days after the term's `term_end_at` for a `SANDBOX` or `DEV` shell while
    remaining null for an `OFFICIAL` one."
    PRD 3.4: "Only in step five are the observables recomputed:
    `seat_utilization_pct` becomes `active_enrollment_count` divided by
    `base_seat_cap`, multiplied by 100, rounded half up to two decimal places,
    and `overflow_flag` becomes true exactly when `active_enrollment_count` is
    greater than `base_seat_cap`."
    PRD 3.8: "Each write re-derives the enrollment's `earned_points_total` as
    the sum of its grade records and its `graded_points_possible` as the sum of
    the `points_possible` of the items it now carries a record for, and
    re-derives that enrollment's `provisional_grade_pct`."
    PRD 3.8: "The **provisional** variant divides by the enrollment's own
    `graded_points_possible` — the work graded so far — which flatters an
    incomplete gradebook, and it writes `provisional_grade_pct`."
    PRD 3.4: "Zero is a live boundary: a shell whose only active row drops reads
    `active_enrollment_count` 0, `seat_utilization_pct` 0.00 and `overflow_flag`
    false, and the term falls by exactly one."
    PRD 2.3: "Both values are echoed back in the `meta` object of the envelope,
    alongside `total_count` (the number of records matching the filter before
    the page window is applied) and `has_more` (true when records remain beyond
    the current window)."

    Design: Corner/consistency_model/every_write_is_visible_to_the_next_read_with_no_settling_delay
    """
    term = create_term(
        api,
        headers=registrar_headers,
        term_code="IMM-2027-SP",
        term_start_at="2027-01-11T00:00:00Z",
        term_end_at="2027-05-14T00:00:00Z",
    )
    assert term["total_active_enrollments"] == 0
    term = transition_term(api, term["id"], "REGISTRATION_OPEN", registrar_headers)
    assert term["lifecycle_state"] == "REGISTRATION_OPEN"

    faculty = create_faculty(
        api, headers=registrar_headers, sis_person_id="IMM-F-01",
        full_name="Grace Hopper",
    )
    student = create_student(
        api, headers=registrar_headers, sis_person_id="IMM-S-01",
        full_name="Ravi Menon",
    )
    instructor = make_instructor_headers(faculty["id"])

    shell = request_shell(
        api, term["id"], faculty["id"], headers=lms_admin_headers,
        sis_section_code="IMM-120-001", shell_type="OFFICIAL", base_seat_cap=10,
    )
    shell = provisioning_decision(api, shell["id"], "APPROVE", headers=lms_admin_headers)
    assert shell["provisioning_state"] == "PROVISIONED"
    assert shell["effective_seat_cap"] == 10
    assert shell["active_enrollment_count"] == 0

    # ── enrolling one student is visible to the next shell and term read ──
    response = api.create_enrollment(
        create_enrollment_payload(shell["id"], student["id"], role="STUDENT"),
        registrar_headers,
    )
    assert response.status_code in WRITE_STATUSES, (
        "creating an enrollment must settle inside the request and answer with "
        f"the row, got HTTP {response.status_code}"
    )
    enrollment = get_success_data(response)
    assert enrollment["enrollment_state"] == "ACTIVE"

    shell_now = get_success_data(api.get_course_shell(shell["id"], lms_admin_headers))
    assert shell_now["active_enrollment_count"] == 1
    assert shell_now["seat_utilization_pct"] == 10.00
    assert shell_now["overflow_flag"] is False

    term_now = get_success_data(api.get_academic_term(term["id"], registrar_headers))
    assert term_now["total_active_enrollments"] == 1
    assert_term_seat_ledger(term_now, [shell_now])

    # ── the item write re-derives the shell's rollups in the same request ──
    response = api.create_content_item(
        create_content_item_payload(
            shell["id"],
            item_type="ASSIGNMENT",
            title="Trajectory worksheet",
            points_possible=25.00,
            storage_mb=3.00,
        ),
        instructor,
    )
    assert response.status_code in WRITE_STATUSES, (
        f"creating a content item must answer with the row, got HTTP {response.status_code}"
    )
    item = get_success_data(response)
    assert item["copy_state"] != "SKIPPED"

    shell_now = get_success_data(api.get_course_shell(shell["id"], instructor))
    assert shell_now["content_item_count"] == 1
    assert shell_now["total_points_possible"] == 25.00
    assert shell_now["storage_mb"] == 3.00

    # ── the grade write re-derives the enrollment's gradebook figures ──
    response = api.record_grade(
        grade_record_payload(enrollment["id"], item["id"], 20.00), instructor
    )
    assert response.status_code in WRITE_STATUSES, (
        f"recording a grade must answer with the row, got HTTP {response.status_code}"
    )
    graded = get_success_data(response)
    assert graded["earned_points_total"] == 20.00
    assert graded["graded_points_possible"] == 25.00
    assert graded["provisional_grade_pct"] == 80.00

    reread = get_success_data(api.get_enrollment(enrollment["id"], instructor))
    assert reread["earned_points_total"] == graded["earned_points_total"] == 20.00
    assert reread["graded_points_possible"] == graded["graded_points_possible"] == 25.00
    assert reread["provisional_grade_pct"] == graded["provisional_grade_pct"] == 80.00

    # ── the drop walks the seat ledger back down inside its own request ──
    response = api.enrollment_transition(
        enrollment["id"], {"action": "DROP", "reason": "schedule conflict"},
        registrar_headers,
    )
    assert response.status_code in WRITE_STATUSES, (
        f"dropping an enrollment must answer with the row, got HTTP {response.status_code}"
    )
    dropped = get_success_data(response)
    assert dropped["enrollment_state"] == "DROPPED"

    shell_now = get_success_data(api.get_course_shell(shell["id"], lms_admin_headers))
    assert shell_now["active_enrollment_count"] == 0
    assert shell_now["seat_utilization_pct"] == 0.00
    assert shell_now["overflow_flag"] is False

    term_now = get_success_data(api.get_academic_term(term["id"], registrar_headers))
    assert term_now["total_active_enrollments"] == 0
    assert_term_seat_ledger(term_now, [shell_now])

    # ── the filtered listings agree with the settled row immediately ──
    rows, meta = validate_paginated(
        api.list_enrollments(
            instructor,
            params={"shell_id": shell["id"], "enrollment_state": "DROPPED"},
        )
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1
    assert rows[0]["id"] == enrollment["id"]
    assert rows[0]["enrollment_state"] == "DROPPED"

    rows, meta = validate_paginated(
        api.list_enrollments(
            instructor,
            params={"shell_id": shell["id"], "enrollment_state": "ACTIVE"},
        )
    )
    assert meta["total_count"] == 0
    assert meta["has_more"] is False
    assert rows == []
