"""Pre-built role headers for every role in the PRD.

`X-User-ID` means something different per role (PRD §2.1):

* `CaseManager` — the `id` of the acting `PartnerAgency`.  Every call a case
  manager makes against a scoped resource must therefore carry the *real*
  agency id, which is what `make_case_manager_headers()` is for.
* `Volunteer` — the `id` of the acting `Volunteer` row; use
  `make_volunteer_headers()`.
* `PlatformAdmin`, `IntakeCoordinator`, `DispatchPlanner`, `WarehouseLead` —
  opaque operator identifiers never compared to any entity's `id`.  The
  warehouse lead's identifier is nevertheless recorded on the offer it
  inspects, so the two constants below give two distinct warehouse people.
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque warehouse identities: the lead who inspects and the lead who releases
# must be two different people for a quarantine release to be accepted.
WAREHOUSE_INSPECTOR_ID = "wl-inspector-1"
WAREHOUSE_RELEASER_ID = "wl-release-2"

TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "intake_coordinator_headers": build_user_headers("test-intake-1", "IntakeCoordinator"),
    "dispatch_planner_headers": build_user_headers("test-dispatch-1", "DispatchPlanner"),
    "warehouse_lead_headers": build_user_headers(WAREHOUSE_INSPECTOR_ID, "WarehouseLead"),
    "warehouse_releaser_headers": build_user_headers(WAREHOUSE_RELEASER_ID, "WarehouseLead"),
    # Entity-backed roles — these shared constants are ONLY safe for calls that
    # never reach an ownership comparison (401/403/404 probes).
    "case_manager_headers": build_user_headers("test-case-manager-1", "CaseManager"),
    "volunteer_headers": build_user_headers("test-volunteer-1", "Volunteer"),
}

ADMIN = TEST_USERS["platform_admin_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]
DISPATCH = TEST_USERS["dispatch_planner_headers"]
WAREHOUSE = TEST_USERS["warehouse_lead_headers"]
WAREHOUSE_RELEASER = TEST_USERS["warehouse_releaser_headers"]


def make_case_manager_headers(agency_id: str) -> dict:
    """For CaseManager. `agency_id` must be the real PartnerAgency id, because
    agency scoping compares the resource's agency foreign key to X-User-ID."""
    return build_user_headers(agency_id, "CaseManager")


def make_volunteer_headers(volunteer_id: str) -> dict:
    """For Volunteer. `volunteer_id` must be the real Volunteer row id, because
    self-scoping compares the assignment's volunteer_id to X-User-ID."""
    return build_user_headers(volunteer_id, "Volunteer")


def make_warehouse_lead_headers(user_id: str) -> dict:
    """For WarehouseLead. The identifier is opaque but is stamped onto
    DonationOffer.inspector_user_id and later compared on quarantine release."""
    return build_user_headers(user_id, "WarehouseLead")


def make_platform_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_intake_coordinator_headers(user_id: str = "test-intake-1") -> dict:
    return build_user_headers(user_id, "IntakeCoordinator")


def make_dispatch_planner_headers(user_id: str = "test-dispatch-1") -> dict:
    return build_user_headers(user_id, "DispatchPlanner")
