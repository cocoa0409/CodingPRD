"""Legal petitions: the LITIGATION drafting gate, the conditional exoneration
cascade on grant-with-vacatur, the clemency jurisdictional flag, and the
clemency appeal ban."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_case,
    advance_legal_petition,
    create_legal_petition,
    create_legal_petition_payload,
    file_petition,
    get_case,
    list_rows,
    record_petition_decision,
    setup_case_in_litigation,
    setup_lab_result_recorded,
    validate_created,
    validate_error,
)

ATTORNEY = TEST_USERS["staff_attorney_headers"]


def test_petition_create_requires_case_in_litigation_gate(api):
    """PRD section 3.6: "Drafting requires the case to be in `LITIGATION`,
    else `ERR_CASE_NOT_IN_LITIGATION` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/petition_create_requires_case_in_litigation
    """
    # Case in TESTING with a recorded result: litigation-READY but not advanced.
    ctx = setup_lab_result_recorded(
        jurisdiction_overrides={"state_code": "WI", "name": "Wisconsin"},
        analysis_overrides={
            "scheduled_start": "2026-10-01T09:00:00Z",
            "scheduled_end": "2026-10-05T17:00:00Z",
        },
        outcome="INCONCLUSIVE",
        profile_obtained=False,
    )
    assert ctx["case"]["status"] == "TESTING"

    resp = api.create_legal_petition(
        create_legal_petition_payload(
            ctx["case"]["id"],
            petition_type="DIRECT_APPEAL",
            court_name="WI Court of Appeals",
        ),
        ATTORNEY,
    )
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_IN_LITIGATION)

    # Only the case's lifecycle changed: the identical payload now succeeds.
    advance_case(ctx["case"]["id"], "BEGIN_LITIGATION")
    ok = api.create_legal_petition(
        create_legal_petition_payload(
            ctx["case"]["id"],
            petition_type="DIRECT_APPEAL",
            court_name="WI Court of Appeals",
        ),
        ATTORNEY,
    )
    data = validate_created(ok)
    assert data["status"] == "DRAFT"


def test_petition_create_initial_state_and_failure_atomicity(api):
    """PRD section 3.6: "A new petition sits in `DRAFT`."
    PRD section 3.6: "Drafting requires the case to be in `LITIGATION`, else
    `ERR_CASE_NOT_IN_LITIGATION` (HTTP 409)."
    PRD section 2.6: "a field described as stamped, recorded, or computed by a
    particular event carries null until that event has occurred."

    Design: Difficulty/cross_entity_state_dependency/petition_create_requires_case_in_litigation
    """
    ctx = setup_lab_result_recorded(
        jurisdiction_overrides={"state_code": "WI", "name": "Wisconsin"},
        outcome="INCONCLUSIVE",
        profile_obtained=False,
    )
    resp = api.create_legal_petition(
        create_legal_petition_payload(ctx["case"]["id"]),
        ATTORNEY,
    )
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_IN_LITIGATION)
    _, meta = list_rows(api.list_case_legal_petitions(ctx["case"]["id"], ATTORNEY))
    assert meta["total_count"] == 0, "the rejected draft created nothing"

    advance_case(ctx["case"]["id"], "BEGIN_LITIGATION")
    data = validate_created(
        api.create_legal_petition(
            create_legal_petition_payload(
                ctx["case"]["id"],
                petition_type="DIRECT_APPEAL",
                court_name="WI Court of Appeals",
                claim_basis="PROCEDURAL",
            ),
            ATTORNEY,
        )
    )
    assert data["status"] == "DRAFT"
    assert data["petition_type"] == "DIRECT_APPEAL"
    assert data["claim_basis"] == "PROCEDURAL"
    assert data["filed_at"] is None
    assert data["decided_at"] is None
    assert data["decision_vacates_conviction"] is None
    _, meta = list_rows(api.list_case_legal_petitions(ctx["case"]["id"], ATTORNEY))
    assert meta["total_count"] == 1


def test_petition_grant_without_vacate_keeps_case_in_litigation(api):
    """PRD section 3.6: "A grant with `vacates_conviction` true fires the
    exoneration cascade: the petition's case moves to `EXONERATED`, its
    `exoneration_date` is set to the current logical clock,
    `release_readiness` becomes `PLANNING`, and the contact interval tightens
    to 14 days. A grant without vacatur, or any denial, leaves the case
    untouched".

    Design: Corner/state_machines/petition_grant_without_vacate_keeps_case_in_litigation
    """
    ctx = setup_case_in_litigation(
        jurisdiction_overrides={"state_code": "AR", "name": "Arkansas"},
        outcome="INCLUSIONARY",
    )
    petition = create_legal_petition(
        ctx["case"]["id"], petition_type="DIRECT_APPEAL", court_name="AR Supreme Court"
    )
    file_petition(petition["id"])
    decided = record_petition_decision(petition["id"], "GRANTED", vacates_conviction=False)
    assert decided["status"] == "DECIDED_GRANTED"
    assert decided["decision_vacates_conviction"] is False
    assert decided["decided_at"] is not None

    case = get_case(ctx["case"]["id"])
    assert case["status"] == "LITIGATION", "a non-vacating grant does not exonerate"
    assert case["exoneration_date"] is None
    assert case["release_readiness"] == "NOT_APPLICABLE"


def test_clemency_petition_requires_jurisdiction_flag(api):
    """PRD section 3.6: "a `CLEMENCY` petition requires the jurisdiction's
    `clemency_available` flag, else `ERR_CLEMENCY_NOT_AVAILABLE` (HTTP 422)".

    Design: Corner/validations/clemency_petition_requires_jurisdiction_flag
    """
    ctx = setup_case_in_litigation(
        jurisdiction_overrides={
            "state_code": "DE", "name": "Delaware", "clemency_available": False,
        }
    )
    resp = api.create_legal_petition(
        create_legal_petition_payload(
            ctx["case"]["id"],
            petition_type="CLEMENCY",
            court_name="DE Board of Pardons",
        ),
        ATTORNEY,
    )
    validate_error(resp, ApiErrorId.ERR_CLEMENCY_NOT_AVAILABLE)

    # The flag is petition-type-conditional: another type on the same case works.
    ok = api.create_legal_petition(
        create_legal_petition_payload(
            ctx["case"]["id"],
            petition_type="DIRECT_APPEAL",
            court_name="DE Supreme Court",
        ),
        ATTORNEY,
    )
    validate_created(ok)


def test_clemency_denial_not_appealable(api):
    """PRD section 3.6: "A denied petition may be appealed from
    `DECIDED_DENIED` to `APPEAL_FILED` — with one exception baked into the
    domain: clemency denials are unappealable, so appealing a `CLEMENCY`
    petition is rejected with `ERR_NOT_APPEALABLE` (HTTP 409)."

    Design: Corner/validations/clemency_denial_not_appealable
    """
    ctx = setup_case_in_litigation(
        jurisdiction_overrides={"state_code": "RI", "name": "Rhode Island"}
    )
    petition = create_legal_petition(
        ctx["case"]["id"], petition_type="CLEMENCY", court_name="RI Parole Board"
    )
    file_petition(petition["id"])
    denied = record_petition_decision(petition["id"], "DENIED")
    assert denied["status"] == "DECIDED_DENIED"
    assert denied["decision_vacates_conviction"] is False

    resp = api.advance_legal_petition(
        petition["id"], {"event": "APPEAL"}, ATTORNEY
    )
    validate_error(resp, ApiErrorId.ERR_NOT_APPEALABLE)

    rows, _ = list_rows(api.list_case_legal_petitions(ctx["case"]["id"], ATTORNEY))
    assert rows[0]["status"] == "DECIDED_DENIED", "the rejected appeal leaves the petition untouched"
