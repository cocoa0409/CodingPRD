"""Pre-built identity headers for every role the PRD declares.

Every request must carry `X-User-ID` and `X-User-Role`.

`ProgramAdmin`, `AccountManager` and `BillingSpecialist` have opaque
identities: the server never resolves the identifier against any entity, so a
shared constant is the canonical form for those three.

`RouteTechnician` is entity-backed by `Route` and `CustomerContact` is
entity-backed by `Account`: for those two the identifier must actually resolve,
so callers MUST use the per-instance builders below with a real row's `id`.
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque identities — the shared constant is the canonical form.
    "program_admin_headers": build_user_headers("operator-program-admin-1", "ProgramAdmin"),
    "account_manager_headers": build_user_headers(
        "operator-account-manager-1", "AccountManager"
    ),
    "billing_specialist_headers": build_user_headers(
        "operator-billing-specialist-1", "BillingSpecialist"
    ),
    # Entity-backed identities — these shared constants deliberately name no
    # existing row, so they are ONLY for tests that assert the unresolvable
    # identity rejection. Ownership-gated calls must use the builders below.
    "route_technician_headers": build_user_headers(
        "11111111-1111-4111-8111-111111111111", "RouteTechnician"
    ),
    "customer_contact_headers": build_user_headers(
        "22222222-2222-4222-8222-222222222222", "CustomerContact"
    ),
}


def make_program_admin_headers(user_id: str = "operator-program-admin-1") -> dict:
    """Headers for ProgramAdmin (opaque identity)."""
    return build_user_headers(user_id, "ProgramAdmin")


def make_account_manager_headers(user_id: str = "operator-account-manager-1") -> dict:
    """Headers for AccountManager (opaque identity)."""
    return build_user_headers(user_id, "AccountManager")


def make_billing_specialist_headers(
    user_id: str = "operator-billing-specialist-1",
) -> dict:
    """Headers for BillingSpecialist (opaque identity)."""
    return build_user_headers(user_id, "BillingSpecialist")


def make_route_technician_headers(route_id: str) -> dict:
    """Headers for RouteTechnician. `X-User-ID` is the acting Route's own id."""
    return build_user_headers(route_id, "RouteTechnician")


def make_customer_contact_headers(account_id: str) -> dict:
    """Headers for CustomerContact. `X-User-ID` is the acting Account's own id."""
    return build_user_headers(account_id, "CustomerContact")


ALL_ROLE_NAMES = [
    "ProgramAdmin",
    "AccountManager",
    "BillingSpecialist",
    "RouteTechnician",
    "CustomerContact",
]
