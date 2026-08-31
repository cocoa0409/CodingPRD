"""Pre-built acting-identity headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for the four opaque roles, and for FirmRecallOfficer
# only in tests that never resolve to a recall the officer must own.
TEST_USERS = {
    # entity_backed: X-User-ID is the id of the acting Firm. The shared constant
    # is a deliberate non-owner used by firm-scoping tests only.
    "firm_officer_headers": build_user_headers("test-firm-officer-1", "FirmRecallOfficer"),
    # opaque roles
    "coordinator_headers": build_user_headers("coord-1", "RecallCoordinator"),
    "second_coordinator_headers": build_user_headers("coord-2", "RecallCoordinator"),
    "panel_headers": build_user_headers("panel-1", "HealthHazardPanel"),
    "investigator_headers": build_user_headers("inv-1", "FieldInvestigator"),
    "adjuster_headers": build_user_headers("adj-1", "InsuranceAdjuster"),
}

# Request headers carrying no acting identity at all.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}

# Header dict carrying an X-User-ID but no X-User-Role.
MISSING_ROLE_HEADERS = {"X-User-ID": "coord-1", "Content-Type": "application/json"}


def make_firm_officer_headers(firm_id: str) -> dict:
    """FirmRecallOfficer acts as the Firm itself: pass the real Firm.id so
    ownership checks on the recall's firm_id resolve."""
    return build_user_headers(firm_id, "FirmRecallOfficer")


def make_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RecallCoordinator")


def make_panel_headers(user_id: str = "panel-1") -> dict:
    return build_user_headers(user_id, "HealthHazardPanel")


def make_investigator_headers(user_id: str = "inv-1") -> dict:
    return build_user_headers(user_id, "FieldInvestigator")


def make_adjuster_headers(user_id: str = "adj-1") -> dict:
    return build_user_headers(user_id, "InsuranceAdjuster")
