"""Entity-specific 404 codes for every path-parameter family (PRD §2.7)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    make_applicant_headers,
    placement_round_transition_payload,
    report_transition_payload,
    resolve_incident_payload,
    validate_error,
)


def test_entity_specific_not_found_family(
    api, platform_admin_headers, program_officer_headers,
):
    """PRD §2.7: "Each identifier in the path is resolved in left-to-right
    order: a missing cycle yields `ERR_CYCLE_NOT_FOUND`, country program
    `ERR_COUNTRY_PROGRAM_NOT_FOUND`, applicant `ERR_APPLICANT_NOT_FOUND`,
    application `ERR_APPLICATION_NOT_FOUND`, placement round
    `ERR_ROUND_NOT_FOUND`, grant `ERR_GRANT_NOT_FOUND`, visa sponsorship
    `ERR_VISA_NOT_FOUND`, residency ledger `ERR_LEDGER_NOT_FOUND`, report
    `ERR_REPORT_NOT_FOUND`, and incident `ERR_INCIDENT_NOT_FOUND` — all 404,
    and the first missing identifier wins."

    Each family is probed with a syntactically valid but unallocated UUID.
    (The application's own 404 is exercised by
    application_get_with_unknown_id_returns_application_not_found.)

    Design: Corner/errors/entity_specific_not_found_family
    """
    missing = NON_EXISTENT_UUID

    resp = api.get_cycle(missing, platform_admin_headers)
    validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_FOUND)

    resp = api.get_country_program(missing, platform_admin_headers)
    validate_error(resp, ApiErrorId.ERR_COUNTRY_PROGRAM_NOT_FOUND)

    resp = api.get_applicant(missing, program_officer_headers)
    validate_error(resp, ApiErrorId.ERR_APPLICANT_NOT_FOUND)

    resp = api.transition_placement_round(
        missing, placement_round_transition_payload("ACCEPT"),
        make_applicant_headers(missing),
    )
    validate_error(resp, ApiErrorId.ERR_ROUND_NOT_FOUND)

    resp = api.get_grant(missing, program_officer_headers)
    validate_error(resp, ApiErrorId.ERR_GRANT_NOT_FOUND)

    resp = api.get_visa_sponsorship(missing, program_officer_headers)
    validate_error(resp, ApiErrorId.ERR_VISA_NOT_FOUND)

    resp = api.get_residency_ledger(missing, program_officer_headers)
    validate_error(resp, ApiErrorId.ERR_LEDGER_NOT_FOUND)

    resp = api.transition_report(
        missing, report_transition_payload("ACCEPT"), program_officer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_REPORT_NOT_FOUND)

    resp = api.resolve_incident(
        missing, resolve_incident_payload("RESUME"), program_officer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INCIDENT_NOT_FOUND)
