"""Corner queue: RBAC matrix claims — role exclusions, the mediation/
investigation firewall, and the work-sharing partition."""
from test_helpers import (
    ApiErrorId,
    charge_investigation_case_id,
    create_deferral_agency,
    create_employer,
    create_employer_payload,
    create_complainant,
    create_evidence_request_payload,
    decline_mediation,
    file_charge,
    make_charging_party_headers,
    make_commissioner_headers,
    make_investigator_headers,
    make_mediator_headers,
    make_respondent_rep_headers,
    make_state_agency_officer_headers,
    offer_mediation,
    read_determination_via_list,
    review_determination_payload,
    setup_docketed_charge,
    setup_pending_review,
    setup_under_investigation,
    assign_investigator,
    validate_error,
    validate_paginated,
)
from test_helpers import api_client


def test_investigator_cannot_read_mediation_case(api):
    """PRD section 2.9: "The `Mediator` role is excluded from all investigation content, and the `Investigator` role is excluded from all mediation content — each receives `ERR_FORBIDDEN_ROLE` when reaching for the other side's resources."

    Design: Corner/rbac/investigator_cannot_read_mediation_case
    """
    base = setup_docketed_charge(basis_codes=["RACE"], incident_date="2026-06-01")
    mediation = offer_mediation(base["charge"])

    response = api_client.get_mediation_case(
        mediation["id"], make_investigator_headers("inv-200")
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_mediator_cannot_read_investigation_case(api):
    """PRD section 2.9: "The `Mediator` role is excluded from all investigation content, and the `Investigator` role is excluded from all mediation content — each receives `ERR_FORBIDDEN_ROLE` when reaching for the other side's resources."

    Design: Corner/rbac/mediator_cannot_read_investigation_case
    """
    base = setup_under_investigation(basis_codes=["RACE"],
                                     incident_date="2026-06-01")
    response = api_client.get_investigation_case(
        base["investigation_case_id"], make_mediator_headers("med-200")
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_charging_party_cannot_register_employer(api):
    """PRD section 2.1: "A properly authenticated caller whose role is not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/charging_party_cannot_register_employer
    """
    complainant = create_complainant(full_name="Gale Three", email="g3@x.com")

    # Employer registration is IntakeOfficer-exclusive (PRD section 4 table).
    response = api_client.create_employer(
        create_employer_payload(legal_name="Self Co", state_code="FL",
                                employee_count_current=40),
        make_charging_party_headers(complainant["id"]),
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_commissioner_cannot_review_determination(api):
    """PRD section 2.1: "A properly authenticated caller whose role is not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/commissioner_cannot_review_determination
    """
    base = setup_pending_review(outcome="NO_CAUSE",
                                investigator_user_id="inv-035")

    # Determination review is a Director exclusive; seniority does not help.
    response = api_client.review_determination(
        base["determination"]["id"],
        review_determination_payload(decision="APPROVE"),
        make_commissioner_headers("com-007"),
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)

    unchanged = read_determination_via_list(
        base["investigation_case_id"], base["determination"]["id"]
    )
    assert unchanged["status"] == "PENDING_REVIEW"


def test_respondent_cannot_issue_evidence_request(api):
    """PRD section 2.1: "A properly authenticated caller whose role is not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD section 3.5: "Once assigned, only that investigator may write to the case — evidence requests, interviews, and determinations all require the caller's `X-User-ID` to equal `assigned_investigator_id`, otherwise `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/respondent_cannot_issue_evidence_request
    """
    base = setup_under_investigation(basis_codes=["RACE"],
                                     incident_date="2026-06-01")
    assign_investigator(base["investigation_case_id"], "inv-036")

    # Even for a case against its own employer, the respondent's role is not
    # on the endpoint's list — the role check precedes any ownership question.
    response = api_client.create_evidence_request(
        base["investigation_case_id"],
        create_evidence_request_payload(request_type="RFI"),
        make_respondent_rep_headers(base["employer"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_respondent_cannot_read_other_cases_evidence(api):
    """PRD section 3.5: "When reading the request list, a `RespondentRep` sees only requests directed at its own employer."
    PRD section 2.8: "**Ownership scope** — the caller's `X-User-ID` does not match the resource's owning party: `ERR_NOT_RESOURCE_OWNER` (403)."

    Design: Corner/rbac/respondent_cannot_read_other_cases_evidence
    """
    employer_a = create_employer(state_code="FL", employee_count_current=40,
                                 legal_name="A Co")
    employer_b = create_employer(state_code="FL", employee_count_current=40,
                                 legal_name="B Co")
    complainant = create_complainant(full_name="Gale Six", email="g6@x.com")
    charge_b = file_charge(employer_b, complainant, basis_codes=["RACE"],
                           incident_date="2026-06-01", harm_description="fired",
                           employee_count_at_incident=40)
    mediation_b = offer_mediation(charge_b)
    decline_mediation(charge_b, mediation_b, party="complainant")
    case_b = charge_investigation_case_id(charge_b["id"])

    # The rep of employer A reaches for the case against employer B.
    response = api_client.list_evidence_requests(
        case_b, make_respondent_rep_headers(employer_a["id"])
    )
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER)


def test_state_agency_officer_limited_to_fepa_owned(api):
    """PRD section 3.2: "A `StateAgencyOfficer` participates only in the work-sharing partition: they see — in lists and in detail reads alike — only charges whose `investigation_owner` is `FEPA`, and any attempt to touch a Commission-owned charge is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/state_agency_officer_limited_to_fepa_owned
    """
    create_deferral_agency(
        state_code="NY", filing_deadline_days=300,
        work_sharing_policy="FEPA_EXCLUSIVE", covers_age=True,
        agency_name="NY FEPA",
    )
    emp_ny = create_employer(state_code="NY", employee_count_current=40,
                             legal_name="NY2 Co")
    emp_fl = create_employer(state_code="FL", employee_count_current=40,
                             legal_name="FL2 Co")
    cp_7 = create_complainant(full_name="Gale Seven", email="g7@x.com")
    cp_8 = create_complainant(full_name="Gale Eight", email="g8@x.com")
    charge_ny = file_charge(emp_ny, cp_7, basis_codes=["SEX"],
                            incident_date="2026-06-01", harm_description="ny case",
                            employee_count_at_incident=40)
    charge_fl = file_charge(emp_fl, cp_8, basis_codes=["SEX"],
                            incident_date="2026-06-01", harm_description="fl case",
                            employee_count_at_incident=40)
    assert charge_ny["investigation_owner"] == "FEPA"
    assert charge_fl["investigation_owner"] == "EEOC"

    officer = make_state_agency_officer_headers("fepa-200")
    rows, meta = validate_paginated(api_client.list_charges(officer))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == charge_ny["id"]

    # Detail reads obey the same partition.
    response = api_client.get_charge(charge_fl["id"], officer)
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
