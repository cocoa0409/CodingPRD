"""Post-conviction filing deadlines: the anniversary is inclusive, one day
past is rejected, and the from-state error outranks the temporal error when a
single FILE violates both."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_legal_petition,
    create_legal_petition,
    file_petition,
    list_rows,
    petition_advance_payload,
    set_clock,
    setup_case_in_litigation,
    validate_error,
    validate_ok,
)

ATTORNEY = TEST_USERS["staff_attorney_headers"]


def _litigation_case_with_deadline():
    """Case in LITIGATION in a jurisdiction with a 5-year post-conviction
    deadline; conviction 2018-06-01 -> filing deadline 2023-06-01T00:00:00Z.
    The logical clock is walked back to 2023 so the deadline is reachable."""
    set_clock("2023-05-01T00:00:00Z")
    return setup_case_in_litigation(
        jurisdiction_overrides={
            "state_code": "WV",
            "name": "West Virginia",
            "post_conviction_deadline_years": 5,
        },
        intake_overrides={
            "conviction_date": "2018-06-01T00:00:00Z",
            "years_served": 5,
        },
        outcome="INCONCLUSIVE",
        profile_obtained=False,
    )


def test_petition_deadline_equality_timely_and_excess_rejected(api):
    """PRD section 3.6: "when the jurisdiction's
    `post_conviction_deadline_years` is not null, the current clock must be no
    later than the anniversary of the intake request's `conviction_date` that
    many years out — filing exactly on the anniversary is timely; strictly
    later is rejected with `ERR_FILING_DEADLINE_EXCEEDED` (HTTP 422)."

    Design: Corner/calculations/petition_deadline_equality_timely_and_excess_rejected
    """
    ctx = _litigation_case_with_deadline()
    pet1 = create_legal_petition(
        ctx["case"]["id"], petition_type="POST_CONVICTION", court_name="WV Circuit Court"
    )
    pet2 = create_legal_petition(
        ctx["case"]["id"], petition_type="POST_CONVICTION", court_name="WV Circuit Court"
    )

    # Filing exactly on the anniversary is timely.
    set_clock("2023-06-01T00:00:00Z")
    filed = file_petition(pet1["id"])
    assert filed["status"] == "FILED"
    assert filed["filed_at"] is not None
    assert filed["filed_at"].startswith("2023-06-01T00:00:00")

    # One day past the deadline the same event is rejected.
    set_clock("2023-06-02T00:00:00Z")
    resp = api.advance_legal_petition(pet2["id"], {"event": "FILE"}, ATTORNEY)
    validate_error(resp, ApiErrorId.ERR_FILING_DEADLINE_EXCEEDED)
    rows, _ = list_rows(api.list_case_legal_petitions(ctx["case"]["id"], ATTORNEY))
    by_id = {row["id"]: row for row in rows}
    assert by_id[pet2["id"]]["status"] == "DRAFT", "the rejected filing leaves the petition in DRAFT"
    assert by_id[pet1["id"]]["status"] == "FILED"


def test_refiling_filed_petition_reports_state_error_not_deadline(api):
    """PRD section 2.9: "When a single request violates several rules, the
    system evaluates checks in a fixed priority order so that the error the
    caller receives is deterministic."
    PRD section 2.9 item 8: "The target resource's current status must admit
    the requested transition, including kind-conditional legality on testing
    authorizations (an agreement event on a motion, or vice versa, is illegal
    regardless of status) — else `ERR_INVALID_STATE` (HTTP 409)."
    PRD section 2.9 item 12: "Filing deadlines, lab-window overlaps, release
    dates, and service-window starts are enforced here —
    `ERR_FILING_DEADLINE_EXCEEDED` (HTTP 422)".

    Design: Difficulty/priority_pair_validation_conflict/petition_file_state_error_precedes_deadline_error
    """
    ctx = _litigation_case_with_deadline()
    petition = create_legal_petition(
        ctx["case"]["id"], petition_type="POST_CONVICTION", court_name="WV Circuit Court"
    )
    # FILED while timely (clock 2023-05-01 < deadline 2023-06-01).
    file_petition(petition["id"])

    # Now past the deadline: a second FILE violates BOTH the from-state rule
    # (status == FILED, not DRAFT) and the deadline rule. The from-state
    # category (priority 8) beats the temporal category (priority 12).
    set_clock("2023-07-01T00:00:00Z")
    resp = api.advance_legal_petition(petition["id"], {"event": "FILE"}, ATTORNEY)
    data = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert data["error_id"] != "ERR_FILING_DEADLINE_EXCEEDED"


def test_petition_file_stamps_filed_at_from_logical_clock(api):
    """PRD section 3.6: "Filing moves a petition from `DRAFT` to `FILED` and
    stamps `filed_at` from the logical clock."
    PRD section 2.9 item 8: the from-state check fires before the temporal
    gates, so a re-FILE of a FILED petition is `ERR_INVALID_STATE` even when
    the deadline has also passed.

    Design: Difficulty/priority_pair_validation_conflict/petition_file_state_error_precedes_deadline_error
    """
    ctx = _litigation_case_with_deadline()
    petition = create_legal_petition(
        ctx["case"]["id"], petition_type="POST_CONVICTION", court_name="WV Circuit Court"
    )
    filed = file_petition(petition["id"])
    assert filed["status"] == "FILED"
    assert filed["filed_at"].startswith("2023-05-01T00:00:00"), (
        "filed_at is stamped from the logical clock at FILE time"
    )

    set_clock("2023-07-01T00:00:00Z")
    resp = api.advance_legal_petition(petition["id"], {"event": "FILE"}, ATTORNEY)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    rows, _ = list_rows(api.list_case_legal_petitions(ctx["case"]["id"], ATTORNEY))
    assert rows[0]["status"] == "FILED", "the rejected re-FILE does not disturb the petition"
    assert rows[0]["filed_at"].startswith("2023-05-01T00:00:00")
