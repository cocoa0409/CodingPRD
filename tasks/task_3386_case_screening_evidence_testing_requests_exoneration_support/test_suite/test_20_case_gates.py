"""Case lifecycle gates: the aggregate preconditions on BEGIN_TESTING and
BEGIN_LITIGATION, and the two unfinished-business gates on CLOSE."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_case,
    cancel_lab_analysis,
    case_advance_payload,
    create_legal_petition,
    get_case,
    setup_case_with_item,
    setup_case_in_litigation,
    setup_lab_analysis_scheduled,
    validate_error,
    validate_ok,
)

ATTORNEY = TEST_USERS["staff_attorney_headers"]
DECIDER = TEST_USERS["managing_attorney_headers"]


def test_begin_testing_requires_custody_confirmed_item(api):
    """PRD section 3.6: "From `INVESTIGATION`, beginning testing requires that
    at least one child evidence item be in `CUSTODY_CONFIRMED` — else
    `ERR_NO_PRESERVED_EVIDENCE` (HTTP 409)".

    Design: Corner/validations/begin_testing_requires_custody_confirmed_item
    """
    ctx = setup_case_with_item(
        jurisdiction_overrides={"state_code": "IN", "name": "Indiana"},
        location="LOCATED",
    )
    assert ctx["case"]["status"] == "INVESTIGATION"
    assert ctx["item"]["location_status"] == "LOCATED"

    resp = api.advance_case(
        ctx["case"]["id"], case_advance_payload("BEGIN_TESTING"), ATTORNEY
    )
    validate_error(resp, ApiErrorId.ERR_NO_PRESERVED_EVIDENCE)
    assert get_case(ctx["case"]["id"])["status"] == "INVESTIGATION"


def test_begin_litigation_requires_recorded_result(api):
    """PRD section 3.6: "From `TESTING`, beginning litigation requires that at
    least one lab analysis on a case evidence item has reached
    `RESULT_RECORDED` or `INTERPRETED` — else `ERR_NO_TEST_RESULTS`
    (HTTP 409)".

    Design: Corner/validations/begin_litigation_requires_recorded_result
    """
    # A SCHEDULED analysis (sample committed, no result yet) does not satisfy
    # the gate.
    ctx = setup_lab_analysis_scheduled(
        jurisdiction_overrides={"state_code": "TN", "name": "Tennessee"}
    )
    assert ctx["case"]["status"] == "TESTING"
    assert ctx["analysis"]["status"] == "SCHEDULED"

    resp = api.advance_case(
        ctx["case"]["id"], case_advance_payload("BEGIN_LITIGATION"), ATTORNEY
    )
    validate_error(resp, ApiErrorId.ERR_NO_TEST_RESULTS)
    assert get_case(ctx["case"]["id"])["status"] == "TESTING"


def test_close_blocked_by_open_petition(api):
    """PRD section 3.6: "any child petition still in `DRAFT`, `FILED`, or
    `APPEAL_FILED` rejects the close with `ERR_OPEN_PETITIONS_EXIST`
    (HTTP 409)".

    Design: Corner/validations/close_blocked_by_open_petition
    """
    ctx = setup_case_in_litigation(
        jurisdiction_overrides={"state_code": "GA", "name": "Georgia"}
    )
    # A single DRAFT petition (never even filed) blocks the close.
    create_legal_petition(
        ctx["case"]["id"], petition_type="DIRECT_APPEAL", court_name="GA Supreme Court"
    )

    resp = api.advance_case(
        ctx["case"]["id"],
        case_advance_payload("CLOSE", resolution="UNSUBSTANTIATED"),
        DECIDER,
    )
    validate_error(resp, ApiErrorId.ERR_OPEN_PETITIONS_EXIST)
    assert get_case(ctx["case"]["id"])["status"] == "LITIGATION"


def test_close_blocked_by_active_lab_analysis(api):
    """PRD section 3.6: "any lab analysis on a case item still in `SCHEDULED`
    or `SAMPLE_SHIPPED` rejects it with `ERR_ACTIVE_LAB_ANALYSES_EXIST`
    (HTTP 409)."
    PRD section 3.6: "A closed case records its `resolution`, sets
    `contact_interval_days` to null, and clears `contact_overdue`; `CLOSED` is
    terminal."

    Design: Corner/validations/close_blocked_by_active_lab_analysis
    """
    ctx = setup_lab_analysis_scheduled(
        jurisdiction_overrides={"state_code": "MO", "name": "Missouri"}
    )
    assert ctx["analysis"]["status"] == "SCHEDULED"

    resp = api.advance_case(
        ctx["case"]["id"],
        case_advance_payload("CLOSE", resolution="EVIDENCE_LOST"),
        DECIDER,
    )
    validate_error(resp, ApiErrorId.ERR_ACTIVE_LAB_ANALYSES_EXIST)

    # Cancelling makes the analysis terminal and refunds the reservation; the
    # same CLOSE then succeeds.
    cancel_lab_analysis(ctx["analysis"]["id"])
    data = validate_ok(
        api.advance_case(
            ctx["case"]["id"],
            case_advance_payload("CLOSE", resolution="EVIDENCE_LOST"),
            DECIDER,
        )
    )
    assert data["status"] == "CLOSED"
    assert data["resolution"] == "EVIDENCE_LOST"
    assert data["contact_interval_days"] is None
    assert data["contact_overdue"] is False
