"""Pre-built role headers for every role in PRD §2.1.

Eleven roles are opaque operators: `X-User-ID` is an opaque identifier that
is never compared to a persisted entity.  Three roles are entity-backed
(`CorpsOfficer` -> Unit, `BellRinger` -> BellRinger, `HostSiteManager` ->
HostSite): for those, callers must pass the real entity id, which is what
the `make_*_headers` builders below are for.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for entity-backed roles only
# in calls that do not exercise ownership.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "territorial_commander_headers": build_user_headers(
        "test-territorial-commander-1", "TerritorialCommander"),
    "divisional_officer_headers": build_user_headers(
        "test-divisional-officer-1", "DivisionalOfficer"),
    "corps_officer_headers": build_user_headers("test-corps-officer-1", "CorpsOfficer"),
    "kettle_coordinator_headers": build_user_headers(
        "test-kettle-coordinator-1", "KettleCoordinator"),
    "volunteer_coordinator_headers": build_user_headers(
        "test-volunteer-coordinator-1", "VolunteerCoordinator"),
    "bell_ringer_headers": build_user_headers("test-bell-ringer-1", "BellRinger"),
    "counting_room_teller_headers": build_user_headers(
        "test-counting-room-teller-1", "CountingRoomTeller"),
    "finance_officer_headers": build_user_headers("test-finance-officer-1", "FinanceOfficer"),
    "assistance_caseworker_headers": build_user_headers(
        "test-assistance-caseworker-1", "AssistanceCaseworker"),
    "program_director_headers": build_user_headers("test-program-director-1", "ProgramDirector"),
    "disaster_services_coordinator_headers": build_user_headers(
        "test-disaster-services-coordinator-1", "DisasterServicesCoordinator"),
    "digital_giving_processor_headers": build_user_headers(
        "test-digital-giving-processor-1", "DigitalGivingProcessor"),
    "host_site_manager_headers": build_user_headers("test-host-site-manager-1", "HostSiteManager"),
}


# --- Per-instance builders for entity_backed roles -----------------------
def make_corps_officer_headers(unit_id: str) -> dict:
    """CorpsOfficer is entity_backed:Unit — pass the real Unit.id whenever the
    call is ownership-gated or the resource references a unit."""
    return build_user_headers(unit_id, "CorpsOfficer")


def make_bell_ringer_headers(ringer_id: str) -> dict:
    """BellRinger is entity_backed:BellRinger.  Shift check-in is owner-scoped:
    PRD §3.3 requires `X-User-ID` to equal the shift's `bell_ringer_id`."""
    return build_user_headers(ringer_id, "BellRinger")


def make_host_site_manager_headers(host_site_id: str) -> dict:
    """HostSiteManager is entity_backed:HostSite — pass the real HostSite.id
    for the owner-scoped host site and kettle location reads."""
    return build_user_headers(host_site_id, "HostSiteManager")
