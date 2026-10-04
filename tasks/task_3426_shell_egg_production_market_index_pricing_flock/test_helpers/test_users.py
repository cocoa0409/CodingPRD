"""Pre-built role headers for the nine roles the PRD recognises.

PRD §2.1: ``Customer`` and ``ComplexManager`` are entity-backed — the
``X-User-ID`` header must equal the acting Customer's or Complex's ``id`` — so
any ownership-gated call MUST be built with :func:`make_customer_headers` or
:func:`make_complex_manager_headers` and the real entity id.  The other seven
roles are opaque operator identifiers, for which the shared constants below
are the canonical form.
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers (PRD §2.1).
PLATFORM_ADMIN_USER_ID = "platform-admin-01"
PRODUCTION_PLANNER_USER_ID = "production-planner-01"
PLANT_MANAGER_USER_ID = "plant-manager-01"
PROCUREMENT_LEAD_USER_ID = "procurement-lead-01"
HEALTH_OFFICIAL_USER_ID = "health-official-01"
QUALITY_AUDITOR_USER_ID = "quality-auditor-01"
SALES_MANAGER_USER_ID = "sales-manager-01"

# Placeholder identities for the entity-backed roles: only safe for calls that
# fail before the ownership check (missing header, unknown role, 400 payloads)
# or that are not ownership-gated.
PLACEHOLDER_CUSTOMER_ID = "customer-unbound"
PLACEHOLDER_COMPLEX_ID = "complex-manager-unbound"


TEST_USERS = {
    "platform_admin_headers": build_user_headers(
        PLATFORM_ADMIN_USER_ID, "PlatformAdmin"
    ),
    "production_planner_headers": build_user_headers(
        PRODUCTION_PLANNER_USER_ID, "ProductionPlanner"
    ),
    "plant_manager_headers": build_user_headers(
        PLANT_MANAGER_USER_ID, "PlantManager"
    ),
    "procurement_lead_headers": build_user_headers(
        PROCUREMENT_LEAD_USER_ID, "ProcurementLead"
    ),
    "health_official_headers": build_user_headers(
        HEALTH_OFFICIAL_USER_ID, "HealthOfficial"
    ),
    "quality_auditor_headers": build_user_headers(
        QUALITY_AUDITOR_USER_ID, "QualityAuditor"
    ),
    "sales_manager_headers": build_user_headers(
        SALES_MANAGER_USER_ID, "SalesManager"
    ),
    # Fallbacks only — never use for an ownership-gated call.
    "customer_headers": build_user_headers(PLACEHOLDER_CUSTOMER_ID, "Customer"),
    "complex_manager_headers": build_user_headers(
        PLACEHOLDER_COMPLEX_ID, "ComplexManager"
    ),
}


def make_customer_headers(customer_id: str) -> dict:
    """Headers for a ``Customer`` acting as ``customer_id``.

    PRD §2.1 resolves the customer's ``X-User-ID`` to the acting Customer's
    ``id``, so this must be called with the created customer's id whenever the
    request is ownership-gated (book / cancel / read order, dispute).
    """
    return build_user_headers(customer_id, "Customer")


def make_complex_manager_headers(complex_id: str) -> dict:
    """Headers for a ``ComplexManager`` acting as ``complex_id``.

    PRD §2.1 resolves the manager's ``X-User-ID`` to the acting Complex's
    ``id``, so this must be called with the path complex's id whenever the
    request is ownership-gated (feed-batch create).
    """
    return build_user_headers(complex_id, "ComplexManager")
