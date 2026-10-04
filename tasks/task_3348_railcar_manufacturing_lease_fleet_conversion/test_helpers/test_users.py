"""Pre-built role headers for every role the platform recognizes.

Six of the seven roles are opaque: when ``X-User-Role`` names one of them,
``X-User-ID`` is an operator identifier that is never compared to any entity's
``id``.  For those roles the shared constants below are the canonical form and
may be used for any call.

``Lessee`` is the exception — its ``X-User-ID`` *is* the ``id`` of the acting
lessee, and ownership checks compare the resource's foreign-key field to it.
Use :func:`make_lessee_headers` with the real ``Lessee.id`` for every
ownership-gated call; the shared constant is only a fallback for calls whose
success does not depend on owning the subject resource.

The default operator identifiers are distinct per role, which keeps the
segregation-of-duties rule (the endorsement creator may not be its approver)
satisfied by default.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# ─── Shared constants ─────────────────────────────────

TEST_USERS = {
    # entity_backed role: the shared constant is a NON-OWNING fallback only.
    "lessee_headers": build_user_headers("lessee-opaque-1", UserRole.LESSEE.value),
    # opaque roles: the shared constant is the canonical form.
    "platform_admin_headers": build_user_headers(
        "op-platform-admin-1", UserRole.PLATFORM_ADMIN.value
    ),
    "supply_chain_coordinator_headers": build_user_headers(
        "op-supply-chain-1", UserRole.SUPPLY_CHAIN_COORDINATOR.value
    ),
    "production_planner_headers": build_user_headers(
        "op-production-planner-1", UserRole.PRODUCTION_PLANNER.value
    ),
    "lease_administrator_headers": build_user_headers(
        "op-lease-administrator-1", UserRole.LEASE_ADMINISTRATOR.value
    ),
    "portfolio_manager_headers": build_user_headers(
        "op-portfolio-manager-1", UserRole.PORTFOLIO_MANAGER.value
    ),
    "regulatory_retrofitist_headers": build_user_headers(
        "op-regulatory-retrofitist-1", UserRole.REGULATORY_RETROFITIST.value
    ),
}

# ─── Second operators ─────────────────────────────────
# Useful wherever two different operators must act on the same resource:
# a second planner raising an endorsement, a second lease administrator
# approving one, or a second portfolio manager settling a return.

SECOND_OPERATORS = {
    "production_planner_2_headers": build_user_headers(
        "op-production-planner-2", UserRole.PRODUCTION_PLANNER.value
    ),
    "lease_administrator_2_headers": build_user_headers(
        "op-lease-administrator-2", UserRole.LEASE_ADMINISTRATOR.value
    ),
    "portfolio_manager_2_headers": build_user_headers(
        "op-portfolio-manager-2", UserRole.PORTFOLIO_MANAGER.value
    ),
    "supply_chain_coordinator_2_headers": build_user_headers(
        "op-supply-chain-2", UserRole.SUPPLY_CHAIN_COORDINATOR.value
    ),
}

TEST_USERS.update(SECOND_OPERATORS)


# ─── Per-instance builders ────────────────────────────

def make_lessee_headers(user_id: str) -> dict:
    """Headers for ``Lessee`` (entity-backed identity).

    Pass the actual ``Lessee.id`` as ``user_id`` whenever the call is
    ownership-gated — a lessee may read its own contracts, placements, cars
    and ledger balance, and the outstanding-balance read is available to a
    lessee only for its own ``id``.
    """
    return build_user_headers(user_id, UserRole.LESSEE.value)


def make_headers(user_id: str, role: str) -> dict:
    """Generic per-instance header builder for any role.

    Opaque roles accept any operator identifier; ``Lessee`` requires the
    acting lessee's ``id``.
    """
    return build_user_headers(user_id, role)
