"""Pre-built role headers. All nine roles are opaque identities per the PRD:
the server never compares X-User-ID against a resource id, so shared constants
are sufficient for every role."""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "event_director_headers": build_user_headers("test-director-1", "EventDirector"),
    "logistics_coordinator_headers": build_user_headers(
        "test-logistics-1", "LogisticsCoordinator"
    ),
    "volunteer_coordinator_headers": build_user_headers(
        "test-volcoord-1", "VolunteerCoordinator"
    ),
    "credentialing_officer_headers": build_user_headers(
        "test-credofficer-1", "CredentialingOfficer"
    ),
    "queue_marshal_headers": build_user_headers("test-marshal-1", "QueueMarshal"),
    "station_lead_headers": build_user_headers("test-stationlead-1", "StationLead"),
    "sterilization_tech_headers": build_user_headers(
        "test-stertech-1", "SterilizationTech"
    ),
    "community_partner_rep_headers": build_user_headers(
        "test-partner-1", "CommunityPartnerRep"
    ),
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
}
