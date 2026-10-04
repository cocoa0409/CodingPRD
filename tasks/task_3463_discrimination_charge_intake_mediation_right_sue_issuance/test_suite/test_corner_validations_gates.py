"""Corner queue: validation-pipeline claims — segregation of duties and the
business-temporal gates."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assign_investigator_payload,
    charge_investigation_case_id,
    conclude_mediation,
    create_charge_payload,
    create_employer,
    create_complainant,
    create_mediation_session_payload,
    issue_rts_as_director,
    log_interview,
    make_charging_party_headers,
    make_director_headers,
    make_mediator_headers,
    read_charge,
    read_determination_via_list,
    review_determination_payload,
    schedule_session,
    setup_in_mediation,
    setup_pending_review,
    setup_under_investigation,
    assign_investigator,
    setup_docketed_charge,
    validate_error,
    validate_ok,
    validate_paginated,
)
from test_helpers import api_client

_INTAKE = TEST_USERS["intake_officer_headers"]
_DIRECTOR = TEST_USERS["director_headers"]


def test_mediator_turned_investigator_rejected_by_sod(api):
    """PRD section 2.9: "The firewall also follows people across roles over time: assigning an investigator who previously served as `mediator_user_id` on any session of the same charge is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/mediator_turned_investigator_rejected_by_sod
    """
    base = setup_in_mediation(basis_codes=["RACE"], incident_date="2026-06-01")
    charge = base["charge"]
    mediation = base["mediation_case"]
    schedule_session(mediation, "med-011",
                     scheduled_start="2026-10-01T10:00:00Z",
                     scheduled_end="2026-10-01T11:00:00Z")
    conclude_mediation(mediation, outcome="IMPASSE", mediator_user_id="med-011")
    case_id = charge_investigation_case_id(charge["id"])

    # med-011 mediated a session on this charge: barred from investigating it.
    rejected = api_client.assign_investigator(
        case_id, assign_investigator_payload(investigator_user_id="med-011"),
        make_director_headers("dir-901"),
    )
    validate_error(rejected, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    investigation = validate_ok(api_client.get_investigation_case(case_id, _DIRECTOR))
    assert investigation["assigned_investigator_id"] is None


def test_director_cannot_review_own_draft(api):
    """PRD section 3.6: "Segregation of duties is enforced at this gate: the reviewer's `X-User-ID` must differ from `prepared_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/director_cannot_review_own_draft
    """
    base = setup_pending_review(outcome="NO_CAUSE",
                                investigator_user_id="inv-032")
    determination = base["determination"]

    # The role is correct (Director) but the person drafted the determination.
    rejected = api_client.review_determination(
        determination["id"], review_determination_payload(decision="APPROVE"),
        make_director_headers("inv-032"),
    )
    validate_error(rejected, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    unchanged = read_determination_via_list(
        base["investigation_case_id"], determination["id"]
    )
    assert unchanged["status"] == "PENDING_REVIEW"


def test_incident_date_in_future_rejected(api):
    """PRD section 3.2: "An `incident_date` after the current logical clock is rejected with `ERR_INCIDENT_DATE_FUTURE`, and it must never be after the charge's `received_date`."

    Design: Corner/validations/incident_date_in_future_rejected
    """
    employer = create_employer(state_code="FL", employee_count_current=40,
                               legal_name="Future Co")
    complainant = create_complainant(full_name="Eli Nine", email="e9@x.com")

    # 2026-12-01 is after the 2026-09-01 boot clock: the one intake-time
    # hard rejection (screening itself never rejects for lateness or size).
    response = api_client.create_charge(
        create_charge_payload(
            complainant_id=complainant["id"], employer_id=employer["id"],
            basis_codes=["RACE"], incident_date="2026-12-01",
            harm_description="future harm", employee_count_at_incident=40,
        ),
        _INTAKE,
    )
    validate_error(response, ApiErrorId.ERR_INCIDENT_DATE_FUTURE)


def test_session_scheduled_in_past_rejected(api):
    """PRD section 3.4: "Creating a session takes `scheduled_start` and `scheduled_end`; the start must not be before the current logical clock (a past start is rejected with `ERR_SESSION_IN_PAST`) and the end must be strictly after the start."

    Design: Corner/validations/session_scheduled_in_past_rejected
    """
    base = setup_in_mediation(basis_codes=["RACE"], incident_date="2026-06-01")
    mediation = base["mediation_case"]

    past = api_client.create_mediation_session(
        mediation["id"],
        create_mediation_session_payload(
            scheduled_start="2026-08-01T10:00:00Z",
            scheduled_end="2026-08-01T11:00:00Z",
        ),
        make_mediator_headers("med-042"),
    )
    validate_error(past, ApiErrorId.ERR_SESSION_IN_PAST)


def test_interview_may_be_logged_in_past(api):
    """PRD section 3.5: "Interviews are logged after the fact, so past dates are entirely legitimate — the `ERR_SESSION_IN_PAST` rule does not apply to them."

    Design: Corner/validations/interview_may_be_logged_in_past
    """
    base = setup_under_investigation(basis_codes=["RACE"],
                                     incident_date="2026-06-01")
    case_id = base["investigation_case_id"]
    assign_investigator(case_id, "inv-033")

    # Entirely in the past relative to the 2026-09-01 boot clock: accepted.
    interview = log_interview(
        case_id, "inv-033", witness_name="WP",
        interview_start="2026-08-10T10:00:00Z",
        interview_end="2026-08-10T11:00:00Z", summary="past interview",
    )
    assert interview["investigator_user_id"] == "inv-033"


def test_duplicate_rts_request_rejected(api):
    """PRD section 3.8: "Exactly one notice may ever exist for a charge; a request made when one already exists is rejected with `ERR_INVALID_STATE`."
    PRD section 2.8: "On a terminal charge the more specific `ERR_CHARGE_ALREADY_CLOSED` (409) is returned instead, and it outranks the business-temporal checks below — an operation on a closed charge reports its closedness, not a deadline failure."

    Design: Corner/validations/duplicate_rts_request_rejected
    """
    base = setup_docketed_charge(basis_codes=["RACE"], incident_date="2026-06-01")
    charge = base["charge"]

    # The first (Director-discretion) issuance lands the charge in the terminal
    # RTS_ISSUED state, so the second request reports closedness.
    issue_rts_as_director(charge)
    assert read_charge(charge["id"])["case_status"] == "RTS_ISSUED"

    duplicate = api_client.issue_right_to_sue(
        charge["id"], make_charging_party_headers(charge["complainant_id"])
    )
    validate_error(duplicate, ApiErrorId.ERR_CHARGE_ALREADY_CLOSED)

    notices, _meta = validate_paginated(
        api_client.list_right_to_sue_notices(charge["id"], _DIRECTOR)
    )
    assert len(notices) == 1
