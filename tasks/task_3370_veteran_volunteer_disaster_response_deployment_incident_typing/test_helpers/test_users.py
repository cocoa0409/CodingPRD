"""Pre-built role headers for every role in the PRD.

Identity semantics (PRD user/role section): six roles use opaque operator
identifiers; `Volunteer` and `PartnerLiaison` are entity-backed — their
X-User-ID must equal the acting Volunteer.id / PartnerAgency.id whenever the
call is ownership-gated. Use the per-instance builders for those two roles.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the six opaque roles, and for tests whose
# outcome does not depend on the caller owning the subject resource.
TEST_USERS = {
    "system_admin_headers": build_user_headers("test-system-admin-1", "SystemAdmin"),
    "incident_commander_headers": build_user_headers("test-incident-commander-1", "IncidentCommander"),
    "operations_lead_headers": build_user_headers("test-operations-lead-1", "OperationsLead"),
    "safety_officer_headers": build_user_headers("test-safety-officer-1", "SafetyOfficer"),
    "intake_coordinator_headers": build_user_headers("test-intake-coordinator-1", "IntakeCoordinator"),
    "training_director_headers": build_user_headers("test-training-director-1", "TrainingDirector"),
    # Entity-backed fallbacks — only for non-ownership tests.
    "partner_liaison_headers": build_user_headers("test-partner-liaison-1", "PartnerLiaison"),
    "volunteer_headers": build_user_headers("test-volunteer-1", "Volunteer"),
}


def make_volunteer_headers(user_id: str) -> dict:
    """Volunteer is entity-backed: pass the actual Volunteer.id as user_id
    whenever the call is ownership-gated (own record, own deployment offer,
    own training enrollment)."""
    return build_user_headers(user_id, "Volunteer")


def make_partner_liaison_headers(user_id: str) -> dict:
    """PartnerLiaison is entity-backed: pass the actual PartnerAgency.id as
    user_id whenever the call sets or checks source_partner_id."""
    return build_user_headers(user_id, "PartnerLiaison")
