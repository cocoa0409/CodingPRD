"""Pre-built role headers for the seven roles this API recognises.

`PlatformAdmin` is the only opaque principal: its `X-User-ID` is an operator
string that is never compared to an entity id, so a shared constant is the
canonical form.  Every other role is entity-backed — `ProjectManager`,
`Estimator` and `Controller` by a `StaffMember` id, `Client` by a `Client` id,
`Lender` by a `Lender` id and `Subcontractor` by a `Subcontractor` id — so
those roles must be built per instance from the real row's `id` whenever the
call is identity- or ownership-gated.  The shared constants below exist only
for tests that deliberately exercise an unknown or non-owning principal.
"""

from prd_bench_local_runner.testing import build_user_headers

PLATFORM_ADMIN_USER = "admin-operator-1"

TEST_USERS = {
    # Opaque role — the shared constant is the canonical form.
    "platform_admin_headers": build_user_headers(PLATFORM_ADMIN_USER, "PlatformAdmin"),
    # Entity-backed roles — these constants never resolve to a real row, so they
    # are only valid for identity-mismatch / ownership-denial scenarios.
    "unknown_project_manager_headers": build_user_headers(
        "no-such-staff-member", "ProjectManager"
    ),
    "unknown_estimator_headers": build_user_headers("no-such-staff-member", "Estimator"),
    "unknown_controller_headers": build_user_headers("no-such-staff-member", "Controller"),
    "unknown_client_headers": build_user_headers("no-such-client", "Client"),
    "unknown_lender_headers": build_user_headers("no-such-lender", "Lender"),
    "unknown_subcontractor_headers": build_user_headers(
        "no-such-subcontractor", "Subcontractor"
    ),
}


def make_platform_admin_headers(user_id: str = PLATFORM_ADMIN_USER) -> dict:
    """PlatformAdmin acts under an opaque operator identifier."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_project_manager_headers(staff_member_id: str) -> dict:
    """Pass the id of a StaffMember whose staff_function is PROJECT_MANAGER."""
    return build_user_headers(staff_member_id, "ProjectManager")


def make_estimator_headers(staff_member_id: str) -> dict:
    """Pass the id of a StaffMember whose staff_function is ESTIMATOR."""
    return build_user_headers(staff_member_id, "Estimator")


def make_controller_headers(staff_member_id: str) -> dict:
    """Pass the id of a StaffMember whose staff_function is CONTROLLER."""
    return build_user_headers(staff_member_id, "Controller")


def make_client_headers(client_id: str) -> dict:
    """Pass the id of the Client that owns the project being acted on."""
    return build_user_headers(client_id, "Client")


def make_lender_headers(lender_id: str) -> dict:
    """Pass the id of the Lender named by the project's lender_id."""
    return build_user_headers(lender_id, "Lender")


def make_subcontractor_headers(subcontractor_id: str) -> dict:
    """Pass the id of the Subcontractor that owns the task / waiver / defect."""
    return build_user_headers(subcontractor_id, "Subcontractor")
