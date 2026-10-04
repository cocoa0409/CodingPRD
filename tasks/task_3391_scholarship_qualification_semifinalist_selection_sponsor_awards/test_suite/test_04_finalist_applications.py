"""Finalist applications: endorsement, submission gates, the correction loop,
OCC-guarded review, and publish-finalists — PRD §2.7, §3.5.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock,
    create_finalist_application_payload,
    endorse_application,
    get_application,
    list_applications,
    list_notifications,
    make_school_official_headers,
    make_student_headers,
    publish_finalists,
    review_application,
    setup_finalists_selected,
    setup_semifinalists_selected,
    submit_application,
    validate_error,
    validate_success,
)

PA = TEST_USERS["program_admin_headers"]


def test_submit_without_endorsement_rejected(api):
    """PRD §3.5: "endorsement_status` must be `ENDORSED` (else
    `ERR_APPLICATION_INCOMPLETE`, HTTP 422)".
    
    Design: Corner/validations/submit_without_endorsement_rejected
    """
    ctx = setup_finalists_selected(student_specs=[{"apply": "create"}], publish=False)
    app = ctx["application"]
    resp = api.submit_application(
        app["id"], make_student_headers(ctx["student"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_APPLICATION_INCOMPLETE)
    after = get_application(app["id"])
    assert after["status"] == "IN_PROGRESS"
    assert after["endorsement_status"] == "PENDING"
    assert after["submitted_at"] is None


def test_confirming_floor_boundary_at_submit_rejected(api):
    """PRD §3.5: "confirming_selection_index` must be at least the cycle's
    `confirming_floor` (else `ERR_CONFIRMING_SCORE_BELOW_FLOOR`, HTTP 422)".
    
    Design: Corner/validations/confirming_floor_boundary_at_submit_rejected
    """
    ctx = setup_finalists_selected(
        student_specs=[{"apply": "endorse", "confirming_selection_index": 199}],
        publish=False,
    )  # cycle confirming_floor is 200; endorsement is complete
    app = ctx["application"]
    resp = api.submit_application(
        app["id"], make_student_headers(ctx["student"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_CONFIRMING_SCORE_BELOW_FLOOR)
    assert get_application(app["id"])["status"] == "IN_PROGRESS"


def test_application_create_after_deadline_rejected(api):
    """PRD §3.5: "Creation must also happen while the logical clock is at or
    before the cycle's `application_deadline`; later attempts are
    `ERR_APPLICATION_WINDOW_CLOSED` (HTTP 422)."
    
    Design: Corner/validations/application_create_after_deadline_rejected
    """
    ctx = setup_semifinalists_selected()
    advance_clock("2027-12-16T00:00:00Z")  # deadline is 2027-12-15T00:00:00Z
    resp = api.create_finalist_application(
        create_finalist_application_payload(ctx["entry"]["id"]),
        make_student_headers(ctx["student"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_APPLICATION_WINDOW_CLOSED)
    assert list_applications(entry_id=ctx["entry"]["id"]) == []


def test_application_create_after_publish_rejected(api):
    """PRD §3.5: "Once the cycle reaches `SEMIFINALISTS_SELECTED` — application
    creation in any other posture is `ERR_CYCLE_POSTURE_INVALID` (HTTP 409)".
    
    Design: Corner/validations/application_create_after_publish_rejected
    """
    ctx = setup_finalists_selected(
        student_specs=[{"apply": "confirm"}, {"apply": None}], publish=True
    )  # cycle now FINALISTS_SELECTED; s2's entry is still SELECTED_SEMIFINALIST
    e2, s2 = ctx["entries"][1], ctx["students"][1]
    assert e2["status"] == "SELECTED_SEMIFINALIST"
    resp = api.create_finalist_application(
        create_finalist_application_payload(e2["id"], gpa_scaled=3.8,
                                            course_rigor="ADVANCED",
                                            confirming_selection_index=208),
        make_student_headers(s2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CYCLE_POSTURE_INVALID)


def test_publish_auto_denies_in_progress_application(api):
    """PRD §3.5: "every application still `IN_PROGRESS` flips to `DENIED`
    (auto-denial at the deadline of the process), every `FINALIST_CONFIRMED`
    application spawns a `FINALIST_NOTICE` notification (sequence 2, embargoed
    until the cycle's `finalist_embargo_until`), and the cycle moves
    `SEMIFINALISTS_SELECTED` → `FINALISTS_SELECTED`".
    
    Design: Corner/state_machines/publish_auto_denies_in_progress_application
    """
    ctx = setup_finalists_selected(
        student_specs=[{"apply": "confirm"}, {"apply": "create"}], publish=True
    )
    assert ctx["cycle"]["status"] == "FINALISTS_SELECTED"
    a2 = get_application(ctx["applications"][1]["id"])
    assert a2["status"] == "DENIED"
    assert a2["return_reason"] is None
    s1, s2 = ctx["students"]
    notes2 = list_notifications(s2["id"])
    assert [n["notice_type"] for n in notes2] == ["SEMIFINALIST_NOTICE"]
    notes1 = list_notifications(s1["id"])
    assert [n["sequence_number"] for n in notes1] == [1, 2]
    assert all(n["status"] == "EMBARGOED" for n in notes1)
    assert notes1[1]["notice_type"] == "FINALIST_NOTICE"


def test_publish_blocked_by_pending_application_rejected(api):
    """PRD §3.5: "Publishing finalists refuses to fire while any application of
    the cycle's entries is `UNDER_REVIEW` or `RETURNED_FOR_CORRECTION` — the
    rejection is `ERR_PENDING_APPLICATIONS_REMAIN` (HTTP 409)".
    
    Design: Corner/state_machines/publish_blocked_by_pending_application_rejected
    """
    ctx = setup_finalists_selected(student_specs=[{"apply": "submit"}], publish=False)
    cycle_id = ctx["cycle"]["id"]
    resp = api.publish_finalists(cycle_id, PA)
    validate_error(resp, ApiErrorId.ERR_PENDING_APPLICATIONS_REMAIN)
    app = ctx["application"]  # UNDER_REVIEW; the response carried its version
    review_application(app["id"], "CONFIRM", app["version"])
    cycle = publish_finalists(cycle_id)
    assert cycle["status"] == "FINALISTS_SELECTED"


def test_return_resubmit_confirm_walks_correction_loop(api):
    """PRD §3.5: "Submission moves the application `IN_PROGRESS` → `UNDER_REVIEW`
    — and, after a return, `RETURNED_FOR_CORRECTION` → `UNDER_REVIEW`; this
    correction cycle may repeat without bound while the cycle stays
    `SEMIFINALISTS_SELECTED`", and a RETURN review "moves the application
    `UNDER_REVIEW` → `RETURNED_FOR_CORRECTION` and records the payload value
    in `return_reason` for the student".
    
    Design: Difficulty/non_linear_state_machine/finalist_application_return_resubmit_cycle
    """
    ctx = setup_finalists_selected(student_specs=[{"apply": "submit"}], publish=False)
    app = ctx["application"]  # version 3 after create -> endorse -> submit
    student_id = ctx["student"]["id"]

    returned = review_application(
        app["id"], "RETURN", app["version"],
        return_reason="Add honors coursework detail",
    )
    assert returned["status"] == "RETURNED_FOR_CORRECTION"
    resubmitted = submit_application(app["id"], student_id)
    assert resubmitted["status"] == "UNDER_REVIEW"
    confirmed = review_application(app["id"], "CONFIRM", resubmitted["version"])
    assert confirmed["status"] == "FINALIST_CONFIRMED"


def test_return_reason_set_then_cleared_and_version_counts_edges(api):
    """PRD §3.5: a RETURN decision "records the payload value in `return_reason`
    for the student" and each submit "clears `return_reason` to null". PRD
    §2.4: version "starts at 1 on creation and increments by exactly 1 on
    every mutation of that resource".
    
    Design: Difficulty/non_linear_state_machine/finalist_application_return_resubmit_cycle
    """
    ctx = setup_finalists_selected(student_specs=[{"apply": "submit"}], publish=False)
    app = ctx["application"]
    student_id = ctx["student"]["id"]
    assert app["version"] == 3  # create(1) -> endorse(2) -> submit(3)

    returned = review_application(
        app["id"], "RETURN", app["version"], return_reason="Add honors coursework detail"
    )
    assert returned["return_reason"] == "Add honors coursework detail"
    assert returned["version"] == 4
    resubmitted = submit_application(app["id"], student_id)
    assert resubmitted["return_reason"] is None
    assert resubmitted["version"] == 5
    confirmed = review_application(app["id"], "CONFIRM", resubmitted["version"])
    assert confirmed["version"] == 6  # exactly +1 per edge of the loop


def test_review_with_stale_version_rejected(api):
    """PRD §2.7: "Reviewing a finalist application requires the request to carry
    `expected_finalist_application_version`, holding the application's
    `version` as the reviewer last observed it. If the application's `version`
    has advanced since that read — a school endorsement or a resubmission
    landing after the reviewer's read — the review is rejected with
    `ERR_STALE_VERSION` (HTTP 412)".
    
    Design: Corner/cross_cutting_layers/review_with_stale_version_rejected
    """
    ctx = setup_finalists_selected(student_specs=[{"apply": "submit"}], publish=False)
    app = ctx["application"]  # UNDER_REVIEW at version 3
    student_id = ctx["student"]["id"]

    returned = review_application(
        app["id"], "RETURN", app["version"], return_reason="Add honors coursework detail"
    )
    assert returned["version"] == 4
    resp = api.review_application(
        app["id"],
        {"decision": "CONFIRM", "expected_finalist_application_version": app["version"]},
        PA,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert get_application(app["id"])["status"] == "RETURNED_FOR_CORRECTION"

    resubmitted = submit_application(app["id"], student_id)
    assert resubmitted["version"] == 5
    confirmed = review_application(app["id"], "CONFIRM", resubmitted["version"])
    assert confirmed["status"] == "FINALIST_CONFIRMED"
