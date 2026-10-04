"""Corner queue: state machine claims around mediation offer/response/conclude."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    conclude_mediation_payload,
    create_deferral_agency,
    create_employer,
    create_complainant,
    file_charge,
    make_charging_party_headers,
    make_mediator_headers,
    offer_mediation,
    read_charge,
    respond_mediation_payload,
    respond_to_mediation,
    setup_docketed_charge,
    setup_in_mediation,
    validate_error,
    validate_ok,
)
from test_helpers import api_client

_INTAKE = TEST_USERS["intake_officer_headers"]
_DIRECTOR = TEST_USERS["director_headers"]


def test_charge_delegated_to_fepa_exclusive_route(api):
    """PRD section 3.1: "Under `FEPA_EXCLUSIVE` the charge is dual-filed and the FEPA investigates — the charge lands directly in `DELEGATED_TO_FEPA`."
    PRD section 3.2: "`investigation_owner` is `EEOC` when no agency matched or the policy is `EEOC_RETAINS_ALL` or `DUAL_FILE_DEFAULT`, `FEPA` when the policy is `FEPA_EXCLUSIVE`, and `NONE` when the charge is dismissed at intake."
    PRD section 3.2: "`dual_filed` is true exactly when an agency matched and its policy is `DUAL_FILE_DEFAULT` or `FEPA_EXCLUSIVE`."
    PRD section 3.4: "An `IntakeOfficer` offers mediation on a charge that is `DOCKETED` or `UNDER_INVESTIGATION`, provided every prior mediation case on the charge is in a terminal state and fewer than 2 mediation cases already exist — offering a third is rejected with `ERR_MEDIATION_ROUND_EXHAUSTED`, the hard cap being 2 rounds per charge."

    Design: Corner/state_machines/charge_delegated_to_fepa_exclusive_route
    """
    create_deferral_agency(
        state_code="NY", filing_deadline_days=300,
        work_sharing_policy="FEPA_EXCLUSIVE", covers_age=True,
        agency_name="NY FEPA",
    )
    employer = create_employer(state_code="NY", employee_count_current=40,
                               legal_name="NY Co")
    complainant = create_complainant(full_name="Casey Eight", email="c8@x.com")

    charge = file_charge(employer, complainant, basis_codes=["SEX"],
                         incident_date="2026-03-04",
                         harm_description="harassment",
                         employee_count_at_incident=40)
    assert charge["case_status"] == "DELEGATED_TO_FEPA"
    assert charge["investigation_owner"] == "FEPA"
    assert charge["dual_filed"] is True
    # The Commission does not investigate FEPA-routed charges.
    assert charge["investigation_case_id"] is None

    # DELEGATED_TO_FEPA is not an offer-eligible state.
    rejected = api_client.offer_mediation(charge["id"], _INTAKE)
    validate_error(rejected, ApiErrorId.ERR_INVALID_STATE)


def test_decline_from_docketed_creates_investigation(api):
    """PRD section 3.4: "If either party declines, the case moves `OFFERED` → `DECLINED`; when this happens on a `DOCKETED` charge, the charge moves to `UNDER_INVESTIGATION` and an `InvestigationCase` is auto-created (status `OPEN`, `assigned_investigator_id` null, and the charge's `investigation_case_id` stamped with the new case's id), while a decline during an `UNDER_INVESTIGATION` re-offer leaves the charge where it is."

    Design: Corner/state_machines/decline_from_docketed_creates_investigation
    """
    base = setup_docketed_charge(basis_codes=["RACE"], incident_date="2026-06-01")
    charge = base["charge"]
    mediation = offer_mediation(charge)

    declined = respond_to_mediation(charge, mediation, "respondent", "DECLINED")
    assert declined["status"] == "DECLINED"
    assert declined["respondent_response"] == "DECLINED"
    assert declined["complainant_response"] == "PENDING"

    moved = read_charge(charge["id"])
    assert moved["case_status"] == "UNDER_INVESTIGATION"
    assert moved["investigation_case_id"]

    investigation = validate_ok(
        api_client.get_investigation_case(moved["investigation_case_id"], _DIRECTOR)
    )
    assert investigation["status"] == "OPEN"
    assert investigation["assigned_investigator_id"] is None


def test_second_response_same_party_rejected(api):
    """PRD section 3.4: "A party may respond only while its own response field is still `PENDING`."
    PRD section 2.8: "**State preconditions** — the target resource is in a state that forbids the transition: `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/second_response_same_party_rejected
    """
    base = setup_docketed_charge(basis_codes=["RACE"], incident_date="2026-06-01")
    charge = base["charge"]
    mediation = offer_mediation(charge)
    respond_to_mediation(charge, mediation, "complainant", "ACCEPTED")

    # The charging party's field is already recorded: a second respond fails.
    party = make_charging_party_headers(charge["complainant_id"])
    again = api_client.respond_mediation(
        mediation["id"], respond_mediation_payload(response="DECLINED"), party
    )
    validate_error(again, ApiErrorId.ERR_INVALID_STATE)

    # Flip-flopping is impossible: the recorded acceptance stands.
    unchanged = validate_ok(api_client.get_mediation_case(mediation["id"], _DIRECTOR))
    assert unchanged["status"] == "OFFERED"
    assert unchanged["complainant_response"] == "ACCEPTED"
    assert unchanged["respondent_response"] == "PENDING"


def test_conclude_from_offered_rejected(api):
    """PRD section 3.4: "Concluding an active mediation is the mediator's call, made with an `outcome` of `SETTLED` or `IMPASSE`, and is gated on the charge still being `IN_MEDIATION` — a mediation orphaned by a right-to-sue issuance (§3.8) can no longer settle, and its conclusion is rejected with `ERR_INVALID_STATE`."
    PRD section 2.8: "**State preconditions** — the target resource is in a state that forbids the transition: `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/conclude_from_offered_rejected
    """
    base = setup_docketed_charge(basis_codes=["RACE"], incident_date="2026-06-01")
    charge = base["charge"]
    mediation = offer_mediation(charge)
    assert mediation["status"] == "OFFERED"

    early = api_client.conclude_mediation(
        mediation["id"], conclude_mediation_payload(outcome="IMPASSE"),
        make_mediator_headers("med-040"),
    )
    validate_error(early, ApiErrorId.ERR_INVALID_STATE)

    # No side effects: the charge never left DOCKETED and no investigation
    # was auto-created.
    charge_after = read_charge(charge["id"])
    assert charge_after["case_status"] == "DOCKETED"
    assert charge_after["investigation_case_id"] is None


def test_settle_without_amount_invalid_request(api):
    """PRD section 3.4: "A `SETTLED` conclusion requires `settlement_amount_cents` to be present and greater than zero; supplying it with any other outcome, or omitting it here, fails schema validation."
    PRD section 2.8: "Every request passes through a fixed validation pipeline, and the first failing check wins — its error is returned and later checks are not evaluated."

    Design: Corner/state_machines/settle_without_amount_invalid_request
    """
    base = setup_in_mediation(basis_codes=["RACE"], incident_date="2026-06-01")
    charge = base["charge"]
    mediation = base["mediation_case"]
    assert mediation["status"] == "ACTIVE"

    # The conditional-required schema check fires before any state logic.
    missing_amount = api_client.conclude_mediation(
        mediation["id"], conclude_mediation_payload(outcome="SETTLED"),
        make_mediator_headers("med-041"),
    )
    validate_error(missing_amount, ApiErrorId.ERR_VALIDATION_FAILED)

    unchanged = validate_ok(api_client.get_mediation_case(mediation["id"], _DIRECTOR))
    assert unchanged["status"] == "ACTIVE"
    assert read_charge(charge["id"])["case_status"] == "IN_MEDIATION"
