"""Pre-built role headers for every role in the PRD (PRD §2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# CustomerAdmin ownership. For ownership-gated CustomerAdmin calls, always use
# make_customer_admin_headers(org["id"]) with the real Organization id.
TEST_USERS = {
    "program_admin_headers": build_user_headers("test-program-admin-1", "ProgramAdministrator"),
    "licensing_specialist_headers": build_user_headers("test-licensing-specialist-1", "LicensingSpecialist"),
    "customer_admin_headers": build_user_headers("test-customer-admin-1", "CustomerAdmin"),
    "auditor_headers": build_user_headers("test-auditor-1", "Auditor"),
}


def make_customer_admin_headers(user_id: str) -> dict:
    """CustomerAdmin is entity-backed by Organization: X-User-ID must equal the
    owning Organization.id for every ownership-gated call (PRD §2.1)."""
    return build_user_headers(user_id, "CustomerAdmin")
