"""Corner coverage: role authorization, ownership, and segregation of duties."""

from test_helpers import (
    APPEALS_OFFICER_USER_ID,
    FIELD_OFFICER_USER_ID,
    IRS_DATA_AGENT_HEADERS,
    NO_AUTH_HEADERS,
    ApiErrorId,
    adjudicate_appeal,
    appeal_decision_payload,
    list_appeals,
    make_appeals_officer_headers,
    make_beneficiary_headers,
    rate_schedule_2026_payload,
    register_beneficiary,
    setup_appeal_under_review,
    validate_error,
)


def test_beneficiary_cannot_create_rate_schedule(client):
    """PRD section 2.1: "A well-authenticated request whose role is not in the
    endpoint's authorized role list is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)." PRD section 4: POST /medicare/rate-schedules is authorized
    for BenefitAdministrator only.

    Design: Corner/rbac/beneficiary_cannot_create_rate_schedule
    """
    beneficiary = register_beneficiary(client, date_of_birth="1960-01-15")
    response = client.create_rate_schedule(
        rate_schedule_2026_payload(),
        headers=make_beneficiary_headers(beneficiary["id"]),
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_beneficiary_cannot_read_other_beneficiary(client):
    """PRD section 2.1: "A `Beneficiary` acting on a resource whose
    `beneficiary_id` does not equal their `X-User-ID` — whether the
    beneficiary reference arrives in the URL path or through the entity that
    owns the target resource — is rejected with `ERR_NOT_RESOURCE_OWNER`
    (HTTP 403)."

    Design: Corner/rbac/beneficiary_cannot_read_other_beneficiary
    """
    owner = register_beneficiary(
        client, date_of_birth="1960-01-15", full_name="Owner A"
    )
    other = register_beneficiary(
        client, date_of_birth="1961-12-14", full_name="Other B"
    )
    response = client.get_beneficiary(
        other["id"], headers=make_beneficiary_headers(owner["id"])
    )
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER)


def test_irs_agent_cannot_adjudicate_appeal(client):
    """PRD section 2.1: "A well-authenticated request whose role is not in the
    endpoint's authorized role list is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)." PRD section 3.6: "Adjudication is exclusive to the
    `AppealsOfficer`".

    Design: Corner/rbac/irs_agent_cannot_adjudicate_appeal
    """
    beneficiary, _determination, appeal = setup_appeal_under_review(client)
    response = client.adjudicate_appeal(
        appeal["id"],
        appeal_decision_payload("APPROVED"),
        headers=IRS_DATA_AGENT_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)

    appeals = list_appeals(client, beneficiary)
    assert appeals[0]["status"] == "UNDER_REVIEW", "a role denial changes nothing"


def test_missing_auth_headers_unauthenticated(client):
    """PRD section 2.1: "A request missing either header, or presenting a role
    the system does not declare, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    beneficiary = register_beneficiary(client, date_of_birth="1961-12-14")
    response = client.get_beneficiary(beneficiary["id"], headers=NO_AUTH_HEADERS)
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)


def test_sod_same_actor_cannot_adjudicate_own_determination(client):
    """PRD section 3.6: "the adjudicator's `X-User-ID` must differ from the
    appealed determination's `created_by_user_id`, or the decision is rejected
    with `ERR_SOD_SAME_ACTOR` — the officer who authored a determination may
    never adjudicate an appeal against it." PRD section 3.6: "The case's
    `adjudicated_by_user_id` stays null while the appeal is open and is set to
    the deciding officer's `X-User-ID` on either final decision."

    Design: Corner/rbac/sod_same_actor_cannot_adjudicate_own_determination
    """
    _beneficiary, determination, appeal = setup_appeal_under_review(client)
    assert determination["created_by_user_id"] == FIELD_OFFICER_USER_ID

    same_actor = client.adjudicate_appeal(
        appeal["id"],
        appeal_decision_payload("DENIED"),
        headers=make_appeals_officer_headers(FIELD_OFFICER_USER_ID),
    )
    validate_error(same_actor, ApiErrorId.ERR_SOD_SAME_ACTOR)

    decided = adjudicate_appeal(client, appeal, "DENIED")
    assert decided["status"] == "DENIED"
    assert decided["adjudicated_by_user_id"] == APPEALS_OFFICER_USER_ID
