"""Corner queue: validation-pipeline claims — authentication, role
authorization, existence-before-ownership, ownership, and sealing."""
from test_helpers import (
    TEST_USERS,
    UNKNOWN_UUID,
    ApiErrorId,
    assert_disclosure_record,
    assign_investigator_payload,
    build_user_headers,
    create_employer,
    create_complainant,
    create_systemic_case,
    file_charge,
    link_charge,
    make_charging_party_headers,
    make_director_headers,
    make_mediator_headers,
    setup_docketed_charge,
    setup_sealed_charge,
    setup_under_investigation,
    validate_error,
    validate_ok,
    validate_paginated,
)
from test_helpers import api_client

_INTAKE = TEST_USERS["intake_officer_headers"]
_DIRECTOR = TEST_USERS["director_headers"]


def test_missing_auth_header_returns_unauthenticated(api):
    """PRD section 2.1: "A request missing either header, or carrying a role string outside these nine, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/missing_auth_header_returns_unauthenticated
    """
    # No X-User-ID / X-User-Role headers at all.
    response = api_client.list_charges(headers={})
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)


def test_invalid_role_header_returns_unauthenticated(api):
    """PRD section 2.1: "A request missing either header, or carrying a role string outside these nine, is rejected with `ERR_UNAUTHENTICATED`."
    PRD section 2.1: "The system recognizes exactly nine roles: `PlatformAdmin`, `IntakeOfficer`, `ChargingParty`, `RespondentRep`, `Mediator`, `Investigator`, `Director`, `Commissioner`, and `StateAgencyOfficer`."

    Design: Corner/validations/invalid_role_header_returns_unauthenticated
    """
    # "Superuser" is not one of the nine declared roles: an authentication
    # failure (401), not an authorization failure (403).
    response = api_client.list_charges(
        headers=build_user_headers("test-superuser-1", "Superuser")
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)


def test_mediator_cannot_assign_investigator(api):
    """PRD section 2.1: "A properly authenticated caller whose role is not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/validations/mediator_cannot_assign_investigator
    """
    base = setup_under_investigation(basis_codes=["RACE"],
                                     incident_date="2026-06-01")
    case_id = base["investigation_case_id"]

    # Assignment is a Director exclusive (PRD section 4 endpoint table).
    forbidden = api_client.assign_investigator(
        case_id, assign_investigator_payload(investigator_user_id="inv-100"),
        make_mediator_headers("med-900"),
    )
    validate_error(forbidden, ApiErrorId.ERR_FORBIDDEN_ROLE)

    investigation = validate_ok(api_client.get_investigation_case(case_id, _DIRECTOR))
    assert investigation["assigned_investigator_id"] is None


def test_charging_party_cannot_read_others_charge(api):
    """PRD section 2.1: "When `X-User-Role` is `ChargingParty`, `X-User-ID` is the `id` of the acting `Complainant`; ownership checks on any resource that references a complainant compare the resource's `complainant_id` field to `X-User-ID`."
    PRD section 2.8: "**Ownership scope** — the caller's `X-User-ID` does not match the resource's owning party: `ERR_NOT_RESOURCE_OWNER` (403)."

    Design: Corner/validations/charging_party_cannot_read_others_charge
    """
    employer = create_employer(state_code="FL", employee_count_current=40,
                               legal_name="Own Co")
    caller = create_complainant(full_name="Eli Two", email="e2@x.com")
    owner = create_complainant(full_name="Eli Three", email="e3@x.com")
    charge = file_charge(employer, owner, basis_codes=["RACE"],
                         incident_date="2026-06-01", harm_description="fired",
                         employee_count_at_incident=40)

    # Existence succeeds (pipeline step 4); ownership fails (step 5).
    response = api_client.get_charge(
        charge["id"], make_charging_party_headers(caller["id"])
    )
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER)


def test_nonexistent_charge_id_not_found_for_scoped_role(api):
    """PRD section 2.6: "Existence therefore precedes ownership checks, state checks, and confidentiality checks; a read against a non-existent charge returns `ERR_CHARGE_NOT_FOUND` even if the caller could never have been entitled to see it."

    Design: Corner/validations/nonexistent_charge_id_not_found_for_scoped_role
    """
    complainant = create_complainant(full_name="Eli Four", email="e4@x.com")

    # A probing caller receives the 404, never an ownership 403.
    response = api_client.get_charge(
        UNKNOWN_UUID, make_charging_party_headers(complainant["id"])
    )
    validate_error(response, ApiErrorId.ERR_CHARGE_NOT_FOUND)


def test_sealed_charge_cannot_be_read_by_owner(api):
    """PRD section 2.9: "Reading a `SEALED` charge is restricted: any role outside the privileged set {`IntakeOfficer`, `Director`, `Commissioner`} that attempts to read it — including the charge's own `ChargingParty` and `RespondentRep` — is rejected with `ERR_CONFIDENTIALITY_SEALED`."

    Design: Corner/validations/sealed_charge_cannot_be_read_by_owner
    """
    base = setup_sealed_charge(basis_codes=["SEX"], basis_focus=["SEX"])
    charge = base["charge"]
    assert charge["disclosure_hold"] == "SEALED"

    # The seal overrides even the filing party's ownership.
    response = api_client.get_charge(
        charge["id"], make_charging_party_headers(charge["complainant_id"])
    )
    validate_error(response, ApiErrorId.ERR_CONFIDENTIALITY_SEALED)


def test_sealed_privileged_read_appends_internal_access_log(api):
    """PRD section 2.9: "When a privileged role does read a `SEALED` charge, the system appends an `INTERNAL_ACCESS` `DisclosureRecord` to the charge's audit log automatically."
    PRD section 3.9: "A `Director` records an explicit disclosure with a `legal_basis` of `COURT_ORDER`, `FEPA_WORK_SHARE`, or `PARTY_CONSENT` — the fourth value, `INTERNAL_ACCESS`, is never client-supplied; it is system-stamped on the automatic log rows that privileged reads of `SEALED` charges generate — and a `target_description` of who or what received the data (null on the automatic `INTERNAL_ACCESS` rows)."

    Design: Corner/validations/sealed_privileged_read_appends_internal_access_log
    """
    base = setup_docketed_charge(basis_codes=["SEX"], incident_date="2026-06-01")
    charge = base["charge"]
    systemic = create_systemic_case(title="Audit probe", basis_focus=["SEX"],
                                    commissioner_user_id="com-006")
    link_charge(systemic, charge, commissioner_user_id="com-006")

    # The Director's read of the sealed charge is itself audited.
    sealed_read = validate_ok(
        api_client.get_charge(charge["id"], make_director_headers("dir-900"))
    )
    assert sealed_read["disclosure_hold"] == "SEALED"

    rows, _meta = validate_paginated(
        api_client.list_disclosures(charge["id"], _DIRECTOR)
    )
    assert len(rows) == 1
    record = rows[0]
    assert_disclosure_record(record)
    assert record["legal_basis"] == "INTERNAL_ACCESS"
    assert record["accessor_role"] == "Director"
    assert record["accessor_user_id"] == "dir-900"
    assert record["target_description"] is None
