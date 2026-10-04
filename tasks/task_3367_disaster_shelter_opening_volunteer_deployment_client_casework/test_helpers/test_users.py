"""Pre-built role headers for every role in the API.

`ShelterManager` and `Volunteer` are entity-backed by `Volunteer`; `Client` is
entity-backed by `Client`. For those three the shared constants below are only
safe for calls that are not ownership-gated. Any ownership-gated call MUST use
the per-instance builder with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "national_hq_admin_headers": build_user_headers("hq_admin_1", "NationalHQAdmin"),
    "regional_coordinator_headers": build_user_headers("rc_gl", "RegionalCoordinator"),
    "caseworker_headers": build_user_headers("cw_1", "Caseworker"),
    "finance_officer_headers": build_user_headers("fo_1", "FinanceOfficer"),
    "second_finance_officer_headers": build_user_headers("fo_2", "FinanceOfficer"),
    "blood_services_coordinator_headers": build_user_headers(
        "bsc_1", "BloodServicesCoordinator"
    ),
    # entity-backed roles: shared constants are fallbacks for non-ownership calls only.
    "shelter_manager_headers": build_user_headers("volunteer-1", "ShelterManager"),
    "volunteer_headers": build_user_headers("volunteer-1", "Volunteer"),
    "client_headers": build_user_headers("client-1", "Client"),
}


def make_shelter_manager_headers(volunteer_id: str) -> dict:
    """ShelterManager is entity_backed:Volunteer. Pass the acting Volunteer.id."""
    return build_user_headers(volunteer_id, "ShelterManager")


def make_volunteer_headers(volunteer_id: str) -> dict:
    """Volunteer is entity_backed:Volunteer. Pass the acting Volunteer.id."""
    return build_user_headers(volunteer_id, "Volunteer")


def make_client_headers(client_id: str) -> dict:
    """Client is entity_backed:Client. Pass the acting Client.id."""
    return build_user_headers(client_id, "Client")
