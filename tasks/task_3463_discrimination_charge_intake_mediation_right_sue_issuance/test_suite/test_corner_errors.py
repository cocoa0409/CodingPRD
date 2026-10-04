"""Corner queue: error-catalog triggerability — each 404 variant is reachable."""
from test_helpers import (
    UNKNOWN_UUID,
    ApiErrorId,
    create_employer,
    link_charge_payload,
    make_commissioner_headers,
    make_investigator_headers,
    make_respondent_rep_headers,
    read_charge,
    respond_evidence_payload,
    setup_docketed_charge,
    validate_error,
)
from test_helpers import api_client


def test_determination_submit_unknown_id_not_found(api):
    """PRD section 2.6: "Requests that target nested resources are validated hierarchically, left to right along the path. Existence of the parent identifier is confirmed before any child identifier is examined, and the request is rejected with the `404` variant naming the first missing resource: `ERR_CHARGE_NOT_FOUND`, `ERR_MEDIATION_CASE_NOT_FOUND`, `ERR_INVESTIGATION_CASE_NOT_FOUND`, `ERR_EVIDENCE_REQUEST_NOT_FOUND`, `ERR_DETERMINATION_NOT_FOUND`, `ERR_CONCILIATION_NOT_FOUND`, or `ERR_SYSTEMIC_CASE_NOT_FOUND`, depending on which identifier in the path fails to resolve."

    Design: Corner/errors/determination_submit_unknown_id_not_found
    """
    response = api_client.submit_determination(
        UNKNOWN_UUID, make_investigator_headers("inv-099")
    )
    validate_error(response, ApiErrorId.ERR_DETERMINATION_NOT_FOUND)


def test_evidence_respond_unknown_id_not_found(api):
    """PRD section 2.6: "Requests that target nested resources are validated hierarchically, left to right along the path. Existence of the parent identifier is confirmed before any child identifier is examined, and the request is rejected with the `404` variant naming the first missing resource: `ERR_CHARGE_NOT_FOUND`, `ERR_MEDIATION_CASE_NOT_FOUND`, `ERR_INVESTIGATION_CASE_NOT_FOUND`, `ERR_EVIDENCE_REQUEST_NOT_FOUND`, `ERR_DETERMINATION_NOT_FOUND`, `ERR_CONCILIATION_NOT_FOUND`, or `ERR_SYSTEMIC_CASE_NOT_FOUND`, depending on which identifier in the path fails to resolve."
    PRD section 2.6: "Existence therefore precedes ownership checks, state checks, and confidentiality checks; a read against a non-existent charge returns `ERR_CHARGE_NOT_FOUND` even if the caller could never have been entitled to see it."

    Design: Corner/errors/evidence_respond_unknown_id_not_found
    """
    employer = create_employer(state_code="FL", employee_count_current=40,
                               legal_name="Ghost Co")

    # Existence precedes the respondent-ownership check.
    response = api_client.respond_evidence_request(
        UNKNOWN_UUID,
        respond_evidence_payload(response_text="nobody home"),
        make_respondent_rep_headers(employer["id"]),
    )
    validate_error(response, ApiErrorId.ERR_EVIDENCE_REQUEST_NOT_FOUND)


def test_systemic_link_unknown_case_not_found(api):
    """PRD section 2.6: "Requests that target nested resources are validated hierarchically, left to right along the path. Existence of the parent identifier is confirmed before any child identifier is examined, and the request is rejected with the `404` variant naming the first missing resource: `ERR_CHARGE_NOT_FOUND`, `ERR_MEDIATION_CASE_NOT_FOUND`, `ERR_INVESTIGATION_CASE_NOT_FOUND`, `ERR_EVIDENCE_REQUEST_NOT_FOUND`, `ERR_DETERMINATION_NOT_FOUND`, `ERR_CONCILIATION_NOT_FOUND`, or `ERR_SYSTEMIC_CASE_NOT_FOUND`, depending on which identifier in the path fails to resolve."
    PRD section 2.6: "Body-supplied references are validated after the path identifiers — `complainant_id` and `employer_id` at charge intake (yielding `ERR_COMPLAINANT_NOT_FOUND` or `ERR_EMPLOYER_NOT_FOUND` when unknown), and `charge_id` when linking a charge into a systemic case."

    Design: Corner/errors/systemic_link_unknown_case_not_found
    """
    base = setup_docketed_charge(basis_codes=["RACE"], incident_date="2026-06-01")
    charge = base["charge"]

    # The path's systemic-case id resolves before the body's charge_id.
    response = api_client.link_charge(
        UNKNOWN_UUID, link_charge_payload(charge_id=charge["id"]),
        make_commissioner_headers("com-099"),
    )
    validate_error(response, ApiErrorId.ERR_SYSTEMIC_CASE_NOT_FOUND)

    assert read_charge(charge["id"])["systemic_case_id"] is None
