"""Pre-built role headers for every role in the PRD (§2.1).

Identity binding differs by role:
  - FacilityOwner: X-User-ID is the acting Facility's id   -> per-instance builder
  - Importer:      X-User-ID is the acting ImporterFirm id -> per-instance builder
  - PlatformAdmin / EntryReviewer / ComplianceOfficer / FieldInspector /
    RecallCoordinator: opaque operator identifiers — shared constants are the
    canonical form. Segregation-of-duties tests need TWO distinct
    ComplianceOfficer ids (alert creator vs petition adjudicator).

The shared ``facility_owner_headers`` / ``importer_headers`` constants are
fallbacks ONLY for tests that never exercise ownership (e.g. 401/403/404
paths). Any ownership-gated call MUST use make_facility_owner_headers(
facility["id"]) / make_importer_headers(importer["id"]) — the placeholder ids
in the shared constants never equal a real entity id, so every ownership
check would reject them.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    COMPLIANCE_OFFICER_ONE_ID,
    COMPLIANCE_OFFICER_TWO_ID,
    ENTRY_REVIEWER_ONE_ID,
    ENTRY_REVIEWER_TWO_ID,
    FIELD_INSPECTOR_ONE_ID,
    FIELD_INSPECTOR_TWO_ID,
    PLATFORM_ADMIN_ID,
    RECALL_COORDINATOR_ONE_ID,
    RECALL_COORDINATOR_TWO_ID,
)

TEST_USERS = {
    # Opaque roles — canonical shared form.
    "platform_admin_headers": build_user_headers(PLATFORM_ADMIN_ID, "PlatformAdmin"),
    "entry_reviewer_headers": build_user_headers(ENTRY_REVIEWER_ONE_ID, "EntryReviewer"),
    "entry_reviewer_two_headers": build_user_headers(
        ENTRY_REVIEWER_TWO_ID, "EntryReviewer"
    ),
    "compliance_officer_headers": build_user_headers(
        COMPLIANCE_OFFICER_ONE_ID, "ComplianceOfficer"
    ),
    "compliance_officer_two_headers": build_user_headers(
        COMPLIANCE_OFFICER_TWO_ID, "ComplianceOfficer"
    ),
    "field_inspector_headers": build_user_headers(
        FIELD_INSPECTOR_ONE_ID, "FieldInspector"
    ),
    "field_inspector_two_headers": build_user_headers(
        FIELD_INSPECTOR_TWO_ID, "FieldInspector"
    ),
    "recall_coordinator_headers": build_user_headers(
        RECALL_COORDINATOR_ONE_ID, "RecallCoordinator"
    ),
    "recall_coordinator_two_headers": build_user_headers(
        RECALL_COORDINATOR_TWO_ID, "RecallCoordinator"
    ),
    # Entity-backed roles — FALLBACK ONLY, never for ownership-gated calls.
    "facility_owner_headers": build_user_headers("test-facility-1", "FacilityOwner"),
    "importer_headers": build_user_headers("test-importer-1", "Importer"),
}


def make_platform_admin_headers(user_id: str = PLATFORM_ADMIN_ID) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_facility_owner_headers(facility_id: str) -> dict:
    """For FacilityOwner (entity-backed). Pass the acting Facility's id."""
    return build_user_headers(facility_id, "FacilityOwner")


def make_importer_headers(importer_id: str) -> dict:
    """For Importer (entity-backed). Pass the acting ImporterFirm's id."""
    return build_user_headers(importer_id, "Importer")


def make_entry_reviewer_headers(user_id: str = ENTRY_REVIEWER_ONE_ID) -> dict:
    return build_user_headers(user_id, "EntryReviewer")


def make_compliance_officer_headers(user_id: str = COMPLIANCE_OFFICER_ONE_ID) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_field_inspector_headers(user_id: str = FIELD_INSPECTOR_ONE_ID) -> dict:
    return build_user_headers(user_id, "FieldInspector")


def make_recall_coordinator_headers(user_id: str = RECALL_COORDINATOR_ONE_ID) -> dict:
    return build_user_headers(user_id, "RecallCoordinator")
