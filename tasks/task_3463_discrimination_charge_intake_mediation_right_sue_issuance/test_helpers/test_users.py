"""Pre-built role headers for the nine PRD roles (section 2.1).

Two roles are entity-backed and MUST be built per resource:
- ChargingParty  -> X-User-ID must equal the acting Complainant's id
- RespondentRep  -> X-User-ID must equal the acting Employer's id
Use make_charging_party_headers(complainant["id"]) /
make_respondent_rep_headers(employer["id"]) for every ownership-gated call.
The shared TEST_USERS entries for those two roles are fallbacks for tests
whose outcome does not depend on ownership (400/404 probes).

The other seven roles carry opaque identities; the shared constants are
canonical, and the make_* builders exist so a test can pin a specific
operator id (segregation-of-duties and caseload assertions depend on exact
X-User-ID values).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles and for non-ownership probes.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "intake_officer_headers": build_user_headers("test-intake-1", "IntakeOfficer"),
    # entity_backed — fallback only, never for ownership-gated calls:
    "charging_party_headers": build_user_headers("test-complainant-1", "ChargingParty"),
    # entity_backed — fallback only, never for ownership-gated calls:
    "respondent_rep_headers": build_user_headers("test-employer-1", "RespondentRep"),
    "mediator_headers": build_user_headers("test-mediator-1", "Mediator"),
    "investigator_headers": build_user_headers("test-investigator-1", "Investigator"),
    "director_headers": build_user_headers("test-director-1", "Director"),
    "commissioner_headers": build_user_headers("test-commissioner-1", "Commissioner"),
    "state_agency_officer_headers": build_user_headers(
        "test-state-agency-1", "StateAgencyOfficer"
    ),
}


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_intake_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "IntakeOfficer")


def make_charging_party_headers(user_id: str) -> dict:
    """entity_backed:Complainant — pass the actual Complainant.id whenever the
    call is ownership-gated (amend, withdraw, respond, accept, RTS request,
    own-charge reads)."""
    return build_user_headers(user_id, "ChargingParty")


def make_respondent_rep_headers(user_id: str) -> dict:
    """entity_backed:Employer — pass the actual Employer.id whenever the call
    is ownership-gated (respond, evidence respond, offers, own-charge reads)."""
    return build_user_headers(user_id, "RespondentRep")


def make_mediator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Mediator")


def make_investigator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Investigator")


def make_director_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Director")


def make_commissioner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Commissioner")


def make_state_agency_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "StateAgencyOfficer")
