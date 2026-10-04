"""Pre-built role headers for every role in the PRD.

All roles in this PRD are identity-opaque: X-User-ID is never compared to any
persisted entity id, so shared constants are the canonical form for every role.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "production_director_headers": build_user_headers("test-director-1", "ProductionDirector"),
    "content_producer_headers": build_user_headers("test-producer-1", "ContentProducer"),
    "venue_scheduler_headers": build_user_headers("test-scheduler-1", "VenueScheduler"),
    "venue_ops_engineer_headers": build_user_headers("test-ops-1", "VenueOpsEngineer"),
    "sponsorship_manager_headers": build_user_headers("test-sponsor-1", "SponsorshipManager"),
    "box_office_agent_headers": build_user_headers("test-boxoffice-1", "BoxOfficeAgent"),
    "guest_headers": build_user_headers("test-guest-1", "Guest"),
}
