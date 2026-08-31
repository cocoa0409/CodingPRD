"""Role boundaries, optimistic concurrency on parents, and cascade atomicity."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    book_road_test,
    carrier_version,
    complete_negative_drug_test,
    create_open_session,
    dq_file_version,
    fetch_carrier,
    fetch_dq_document,
    fetch_dq_file,
    make_applicant_headers,
    make_safety_director_headers,
    make_school_coordinator_headers,
    order_screening_check,
    pass_road_test,
    record_screening_check_result,
    reserve_seat,
    set_clock,
    setup_draft_application,
    setup_qualified_application,
    setup_submitted_application,
    validate_error,
    validate_paginated,
    validate_success,
)

RECRUITER = TEST_USERS["recruiter_headers"]
DER = TEST_USERS["der_headers"]
SAFETY_DIRECTOR = TEST_USERS["safety_director_headers"]
AUDITOR = TEST_USERS["compliance_auditor_headers"]


def test_a_recruiter_may_not_adjudicate_a_report(api):
    """PRD §2.1: "A `Recruiter` never adjudicates a report, never certifies a file, and never
    hires."
    PRD §2.1: "Where a role is not listed as authorised for the endpoint it calls, the request
    fails with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §3.4: "Adjudication belongs to the `SafetyDirector` and takes a single `decision`
    field valued `PASS`, `PRE_ADVERSE` or `ADVERSE_FINAL`."

    Design: Corner/rbac/recruiter_cannot_adjudicate_screening_check
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})
    check = order_screening_check(ctx["application_id"], "MVR")
    record_screening_check_result(check["id"], issued_on="2026-07-01")

    response = api.adjudicate_screening_check(check["id"], {"decision": "PASS"}, RECRUITER)

    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)
    assert validate_success(api.get_screening_check(check["id"], RECRUITER))["status"] == "RECEIVED"


def test_a_der_may_not_create_a_hire_record(api):
    """PRD §2.1: "A `DER` — the carrier's Designated Employer Representative — is the sole
    owner of the Clearinghouse queries and of the entire drug and alcohol testing chain, from
    specimen collection through laboratory result to Medical Review Officer verification."
    PRD §2.1: "Where a role is not listed as authorised for the endpoint it calls, the request
    fails with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §3.8: "Hiring is a `SafetyDirector`'s decision and the most heavily guarded operation
    in the system."

    Design: Corner/rbac/der_cannot_create_hire_record
    """
    ctx = setup_qualified_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})

    response = api.create_hire_record(
        {
            "application_id": ctx["application_id"],
            "hired_on": "2026-08-13",
            "expected_carrier_version": carrier_version(ctx["carrier_id"]),
        },
        DER,
    )

    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)
    assert fetch_carrier(ctx["carrier_id"])["filled_requisitions"] == 0
    application = validate_success(
        api.get_driver_application(ctx["application_id"], RECRUITER)
    )
    assert application["qualification_status"] == "QUALIFIED"


def test_a_school_coordinator_may_not_certify_an_annual_review(api):
    """PRD §2.1: "A `ComplianceAuditor` does exactly two things and nothing else: certify an
    annual review of a qualification file, and revoke such a certification."
    PRD §2.1: "Where a role is not listed as authorised for the endpoint it calls, the request
    fails with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.9: "First, authentication and authorisation: the two headers must be present and
    non-empty, then `X-User-Role` must name one of the six declared roles (both failures
    reporting `ERR_UNAUTHENTICATED` at HTTP 401), then the acting role must appear in the
    endpoint's authorised list (`ERR_FORBIDDEN_ROLE`, 403), then — on the Clearinghouse consent
    decision and on the screening dispute only — an acting `Applicant` must own the targeted
    resource (`ERR_NOT_RESOURCE_OWNER`, 403)."

    Design: Corner/rbac/school_coordinator_cannot_certify_annual_review
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})
    set_clock("2027-09-01T00:00:00Z")

    response = api.annual_review(
        ctx["dq_file_id"],
        {"certification_note": "not my job"},
        make_school_coordinator_headers("sch-100"),
    )

    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)
    dq_file = fetch_dq_file(ctx["dq_file_id"])
    assert dq_file["review_state"] == "OVERDUE"
    assert dq_file["certified_by_user_id"] is None


def test_a_driver_may_read_their_application_but_not_submit_it(api):
    """PRD §2.1: "Read access is deliberately broad: every one of the six roles may call every
    read endpoint and may advance the logical clock."
    PRD §2.1: "Finally, an `Applicant` is the driver themselves; they may grant or deny
    Clearinghouse consent on their own queries and dispute a pre-adverse screening finding."
    PRD §2.1: "Where a role is not listed as authorised for the endpoint it calls, the request
    fails with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §3.2: "Submission is the pivot of the whole system, and it is a `Recruiter`'s
    privilege."

    Design: Corner/rbac/applicant_can_read_but_cannot_submit_application
    """
    ctx = setup_draft_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})
    driver_headers = make_applicant_headers(ctx["applicant_id"])

    read = validate_success(
        api.get_driver_application(ctx["application_id"], driver_headers)
    )
    assert read["id"] == ctx["application_id"]

    response = api.submit_application(ctx["application_id"], driver_headers)
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    application = validate_success(
        api.get_driver_application(ctx["application_id"], RECRUITER)
    )
    assert application["screening_status"] == "DRAFT"
    assert application["recruiter_user_id"] is None


def test_a_stale_carrier_version_blocks_the_hire_until_it_is_refreshed(api):
    """PRD §2.7: "Creating a hire record consumes one of the carrier's funded requisition
    seats and advances the carrier's `version`, so it must carry `expected_carrier_version`
    matching the target carrier's current `version`. If another writer has advanced the carrier
    since the client last read it, the client's view of how many seats remain is stale and its
    seat arithmetic cannot be trusted, so the create is refused with `ERR_STALE_VERSION` at HTTP
    412."
    PRD §2.7: "The declared value is a required, non-optional field in the request body; if it
    does not equal the parent's current `version` at the moment the write is evaluated, the
    request is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is written."
    PRD §3.8: "The application's `qualification_status` advances `QUALIFIED → HIRED`, and the
    carrier's `filled_requisitions`, `deficiency_ratio` and `posture` are recomputed with the
    carrier's `version` incremented by one."

    Design: Corner/cross_cutting_layers/occ_stale_carrier_version_on_hire_returns_412
    """
    ctx = setup_qualified_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})
    live_version = carrier_version(ctx["carrier_id"])

    stale = api.create_hire_record(
        {
            "application_id": ctx["application_id"],
            "hired_on": "2026-08-13",
            "expected_carrier_version": live_version - 1,
        },
        SAFETY_DIRECTOR,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value, 412)
    carrier = fetch_carrier(ctx["carrier_id"])
    assert carrier["version"] == live_version, "a refused write leaves the parent untouched"
    assert carrier["filled_requisitions"] == 0

    hire = validate_success(
        api.create_hire_record(
            {
                "application_id": ctx["application_id"],
                "hired_on": "2026-08-13",
                "expected_carrier_version": live_version,
            },
            SAFETY_DIRECTOR,
        ),
        201,
    )
    assert hire["status"] == "ACTIVE"
    carrier = fetch_carrier(ctx["carrier_id"])
    assert carrier["version"] == live_version + 1
    assert carrier["filled_requisitions"] == 1


def test_a_stale_session_version_blocks_the_reservation_until_it_is_refreshed(api):
    """PRD §2.7: "Creating an orientation enrollment consumes one of the session's capacity
    seats and advances the session's `version`, so it must carry `expected_session_version`; a
    value older than the session currently holds means the client's reading of the enrolled
    count predates a seat that has already been taken or released, and the create is refused
    with `ERR_STALE_VERSION` at HTTP 412."
    PRD §3.6: "On success the enrollment is minted in `RESERVED`, the session's
    `enrolled_count` increments by one and the session's `version` increments by one."
    PRD §3.6: "Cancelling a reservation is a `Recruiter` action carrying a `reason`; it moves
    the enrollment `RESERVED → CANCELLED`, decrements the session's `enrolled_count` by one and
    increments the session's `version` by one."

    Design: Corner/cross_cutting_layers/occ_stale_session_version_on_enrollment_returns_412
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})
    complete_negative_drug_test(ctx["application_id"])
    pass_road_test(ctx["application_id"])
    session = create_open_session(ctx["carrier_id"])
    version_after_open = session["version"]
    enrollment = reserve_seat(session["id"], ctx["application_id"], version_after_open)
    validate_success(
        api.cancel_orientation_enrollment(
            enrollment["id"], {"reason": "CANDIDATE_RESCHEDULED"}, RECRUITER
        )
    )

    stale = api.create_orientation_enrollment(
        {
            "session_id": session["id"],
            "application_id": ctx["application_id"],
            "expected_session_version": version_after_open,
        },
        RECRUITER,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value, 412)

    session_now = validate_success(api.get_orientation_session(session["id"], RECRUITER))
    assert session_now["enrolled_count"] == 0
    assert session_now["version"] == version_after_open + 2

    retry = validate_success(
        api.create_orientation_enrollment(
            {
                "session_id": session["id"],
                "application_id": ctx["application_id"],
                "expected_session_version": session_now["version"],
            },
            RECRUITER,
        ),
        201,
    )
    assert retry["status"] == "RESERVED"
    assert validate_success(
        api.get_orientation_session(session["id"], RECRUITER)
    )["enrolled_count"] == 1


def test_a_stale_file_version_blocks_the_document_write_until_it_is_refreshed(api):
    """PRD §2.7: "Writing a qualification document recomputes the parent file's completeness
    figures and status and advances that file's `version`, so it must carry
    `expected_dq_file_version`; a stale value means the completeness picture the edit was based
    on has already been superseded by a cascade from screening, drug testing or the road test,
    and the write is refused with `ERR_STALE_VERSION` at HTTP 412."
    PRD §3.7: "Every such write recomputes the parent file's `completeness_pct`,
    `deficiency_count` and `status`, increments the file's `version` by one, re-evaluates the
    application's qualification join and the carrier's posture, and — when the row being written
    is the `MEDICAL_CERT` row — recomputes the applicant's downgrade risk."

    Design: Corner/cross_cutting_layers/occ_stale_dq_file_version_on_document_update_returns_412
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})
    stale_version = dq_file_version(ctx["dq_file_id"])

    check = order_screening_check(ctx["application_id"], "MVR")
    record_screening_check_result(check["id"], issued_on="2026-07-01")
    validate_success(
        api.adjudicate_screening_check(check["id"], {"decision": "PASS"}, SAFETY_DIRECTOR)
    )
    cdl_copy = fetch_dq_document(ctx["dq_file_id"], "CDL_COPY")

    stale = api.update_dq_document(
        cdl_copy["id"],
        {
            "status": "PRESENT",
            "effective_on": "2026-08-01",
            "expected_dq_file_version": stale_version,
        },
        RECRUITER,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value, 412)

    assert validate_success(api.get_dq_document(cdl_copy["id"], RECRUITER))["status"] == "MISSING"
    dq_file = fetch_dq_file(ctx["dq_file_id"])
    assert float(dq_file["completeness_pct"]) == 21.43
    assert dq_file["version"] == stale_version + 1

    retry = validate_success(
        api.update_dq_document(
            cdl_copy["id"],
            {
                "status": "PRESENT",
                "effective_on": "2026-08-01",
                "expected_dq_file_version": dq_file["version"],
            },
            RECRUITER,
        )
    )
    assert retry["status"] == "PRESENT"
    refreshed = fetch_dq_file(ctx["dq_file_id"])
    assert float(refreshed["completeness_pct"]) == 28.57
    assert refreshed["version"] == stale_version + 2


def test_a_stale_predecessor_version_blocks_a_second_reapplication(api):
    """PRD §2.7: "Re-applying mints a superseding application against a predecessor and
    advances that predecessor's `version`, so it must carry `expected_application_version`; a
    stale value means a superseding application has already been minted against that same
    predecessor, and the request is refused with `ERR_STALE_VERSION` at HTTP 412."
    PRD §3.2: "A `Recruiter` names the predecessor in the path, supplies
    `expected_application_version` matching that predecessor's current `version` and a fresh
    `position_type`; the service increments the predecessor's `version` by one and mints a
    brand-new application for the same applicant at `DRAFT` and `NOT_STARTED`, with
    `prior_application_id` pointing back at the predecessor."

    Design: Corner/cross_cutting_layers/occ_stale_application_version_on_reapply_returns_412
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})
    validate_success(
        api.disqualify_application(
            ctx["application_id"], {"reason": "CANDIDATE_PAUSED"}, SAFETY_DIRECTOR
        )
    )
    prior_version = validate_success(
        api.get_driver_application(ctx["application_id"], RECRUITER)
    )["version"]
    successor = validate_success(
        api.reapply(
            ctx["application_id"],
            {"expected_application_version": prior_version, "position_type": "REGIONAL"},
            RECRUITER,
        ),
        201,
    )

    # The successor is deliberately left where reapply minted it (DRAFT /
    # NOT_STARTED).  PRD §2.9 puts the optimistic-concurrency rung strictly above
    # the duplicate-active-application rung, so the stale retry below reports
    # ERR_STALE_VERSION whether or not a non-terminal successor exists — and PRD
    # §3.2 declares SUBMITTED, SCREENING and INFO_REQUESTED as the only origins
    # of a disqualification, so a DRAFT successor cannot be disqualified at all.
    response = api.reapply(
        ctx["application_id"],
        {"expected_application_version": prior_version, "position_type": "OTR"},
        RECRUITER,
    )

    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value, 412)
    refreshed = validate_success(
        api.get_driver_application(ctx["application_id"], RECRUITER)
    )
    assert refreshed["version"] == prior_version + 1
    rows, meta = validate_paginated(
        api.list_driver_applications(
            RECRUITER, params={"prior_application_id": ctx["application_id"]}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == successor["id"]


def test_a_road_test_pass_returns_every_cascade_in_the_same_response(api):
    """PRD §2.11: "When a single operation changes several rows, all of them are written, all
    of their `version` counters increment, and all of their `updated_at` values move — the
    cascade is atomic, not eventual."
    PRD §3.6: "On success the test moves `SCHEDULED → PASSED`, which is its terminal state; the
    application's `qualification_status` advances `IN_PROGRESS → ROAD_TEST_PASSED`; the
    `ROAD_TEST_CERT` document of the application's qualification file becomes `PRESENT` with
    `effective_on` at the current logical-clock date; and the file's `completeness_pct`,
    `deficiency_count` and status are recomputed with its `version` incremented by one."
    PRD §3.6: "Those three already-rounded section values are then added together and the sum
    is rounded half up to one decimal place, and that one-decimal figure is `composite_score`."

    Design: Corner/consistency_model/immediate_consistency_road_test_pass_response_reflects_every_cascade
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})
    complete_negative_drug_test(ctx["application_id"])
    road_test = book_road_test(ctx["application_id"])

    result = validate_success(
        api.record_road_test_result(
            road_test["id"],
            {"outcome": "PASSED", "score_pretrip": 90, "score_skills": 86, "score_road": 78},
            make_safety_director_headers("exam-501"),
        )
    )

    assert float(result["composite_score"]) == 83.8, "the cascade is visible in the same body"
    assert result["status"] == "PASSED"

    application = validate_success(
        api.get_driver_application(ctx["application_id"], RECRUITER)
    )
    assert application["qualification_status"] == "ROAD_TEST_PASSED"

    certificate = fetch_dq_document(ctx["dq_file_id"], "ROAD_TEST_CERT")
    assert certificate["status"] == "PRESENT"
    assert certificate["effective_on"] == "2026-08-01"

    dq_file = fetch_dq_file(ctx["dq_file_id"])
    # APPLICATION_FORM (3, seeded at submission) + DRUG_TEST_RESULT (3, filed by
    # the MRO_VERIFIED_NEGATIVE of this setup) + ROAD_TEST_CERT (3, filed by the
    # pass) = 9 of the provisional denominator of 28 -> 32.14; 10 in-scope rows
    # less the 3 satisfied ones leaves a deficiency_count of 7.
    assert float(dq_file["completeness_pct"]) == 32.14
    assert dq_file["deficiency_count"] == 7
    assert dq_file["status"] == "OPEN"
