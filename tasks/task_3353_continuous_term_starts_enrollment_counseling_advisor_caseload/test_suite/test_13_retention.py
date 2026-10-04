"""Retention outreach: rolling 14-day cadence and the REENROLLED gate."""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId, TEST_USERS, create_program, authorize_state, create_term,
    open_term, create_advisor, create_counselor, create_applicant,
    create_submitted_application, admit_application, create_completed_tce,
    create_enrollment, set_clock, make_advisor_headers,
    assert_retention_outreach,
)

REGISTRAR = TEST_USERS["registrar_headers"]

SECOND_TERM = {
    "name": "2027 Spring A",
    "start_date": "2027-01-11",
    "add_drop_end_date": "2027-01-18",
    "census_date": "2027-01-25",
    "end_date": "2027-03-21",
}


def _setup_withdrawn_enrollment_with_outreach():
    """E1 WITHDRAWN in term 1; outreach O1 queued into term 2 by the owning
    advisor; O1 advanced to SENT at 2026-10-26T00:00:00Z."""
    program = create_program()
    authorize_state(program["id"], state_code="CO")
    term1 = create_term()
    term2 = create_term(**SECOND_TERM)
    open_term(term1["id"])
    advisor = create_advisor()
    create_counselor(cap=5)
    applicant = create_applicant()
    application = create_submitted_application(
        applicant["id"], term1["id"], program["id"])
    application = admit_application(application["id"])
    create_completed_tce(application["id"])
    enrollment = create_enrollment(application, advisor["id"],
                                   tuition_cents=500000)
    validate_success(api_client.withdraw_enrollment(
        enrollment["id"], REGISTRAR, withdrawal_date="2026-09-10"),
        expected_status=200)
    advisor_headers = make_advisor_headers(advisor["id"])
    resp = api_client.create_retention_outreach(
        enrollment["id"], term2["id"], advisor_headers)
    outreach = validate_success(resp, expected_status=201)
    assert_retention_outreach(outreach)
    assert outreach["status"] == "QUEUED"
    set_clock("2026-10-26T00:00:00Z")
    resp = api_client.advance_retention_outreach(
        outreach["id"], "SENT", advisor_headers)
    outreach = validate_success(resp, expected_status=200)
    assert outreach["status"] == "SENT"
    return {
        "program": program, "term1": term1, "term2": term2,
        "advisor": advisor, "advisor_headers": advisor_headers,
        "applicant": applicant, "enrollment": enrollment,
        "outreach": outreach,
    }


class TestRetentionOutreachRolling14DayExclusion:
    def test_second_outreach_within_14_days_rejected(self):
        """PRD §3.9: "That cadence check runs at queue time across the
        applicant's history: the system finds the most recent outreach for
        the same `applicant_id` whose status is `SENT` or `RESPONDED` — ties
        broken by `created_at` descending, never by `id` — and if that
        outreach's `sent_at` is less than fourteen days before the current
        logical instant, the new outreach is rejected with
        `ERR_OUTREACH_CADENCE`."

        Design: Difficulty/resource_temporal_overlap/retention_outreach_rolling_14_day_exclusion
        """
        ctx = _setup_withdrawn_enrollment_with_outreach()
        # Clock is still 2026-10-26T00:00:00Z, the instant O1 was sent.
        resp = api_client.create_retention_outreach(
            ctx["enrollment"]["id"], ctx["term2"]["id"],
            ctx["advisor_headers"])
        validate_error(resp, ApiErrorId.ERR_OUTREACH_CADENCE)

    def test_outreach_at_exactly_14_days_allowed(self):
        """PRD §3.9: "The boundary is inclusive in the caller's favor: an
        outreach whose predecessor was sent exactly fourteen days ago is
        allowed, since only a gap strictly shorter than fourteen days
        rejects."

        Design: Difficulty/resource_temporal_overlap/retention_outreach_rolling_14_day_exclusion
        """
        ctx = _setup_withdrawn_enrollment_with_outreach()
        # O1 sent at 2026-10-26T00:00:00Z; exactly 14 days later is allowed.
        set_clock("2026-11-09T00:00:00Z")
        resp = api_client.create_retention_outreach(
            ctx["enrollment"]["id"], ctx["term2"]["id"],
            ctx["advisor_headers"])
        data = validate_success(resp, expected_status=201)
        assert_retention_outreach(data)
        assert data["status"] == "QUEUED"


def test_retention_reenrolled_requires_live_target_enrollment():
    """PRD §3.9: "`RESPONDED` → `REENROLLED` is permitted only once a new
    enrollment for the same applicant exists with `term_id` equal to the
    outreach's `target_term_id` in `REGISTERED`, `ACTIVE`, or `DEFERRED`
    status — without that live target enrollment the advance is rejected
    with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/retention_reenrolled_requires_live_target_enrollment
    """
    ctx = _setup_withdrawn_enrollment_with_outreach()
    resp = api_client.advance_retention_outreach(
        ctx["outreach"]["id"], "RESPONDED", ctx["advisor_headers"])
    validate_success(resp, expected_status=200)
    # No enrollment for this applicant into term2 exists yet.
    resp = api_client.advance_retention_outreach(
        ctx["outreach"]["id"], "REENROLLED", ctx["advisor_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
