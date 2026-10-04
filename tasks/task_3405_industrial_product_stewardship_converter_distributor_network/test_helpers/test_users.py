"""Pre-built role headers for every role in the PRD (§2.1).

Seven roles are opaque (X-User-ID is an operator identifier). Converter and
Distributor are entity-backed: their X-User-ID must equal the acting partner
record's id on ownership-gated calls, so fixtures must use the per-instance
builders below with the real entity id — never the shared fallback constants.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constants are the canonical form.
    "platform_admin_headers": build_user_headers("pa-1", "PlatformAdmin"),
    "product_manager_headers": build_user_headers("pm-1", "ProductManager"),
    "regulatory_manager_headers": build_user_headers("rm-1", "RegulatoryManager"),
    "channel_manager_headers": build_user_headers("cm-1", "ChannelManager"),
    "quality_auditor_headers": build_user_headers("qa-1", "QualityAuditor"),
    "technical_engineer_headers": build_user_headers("te-1", "TechnicalEngineer"),
    "finance_controller_headers": build_user_headers("fc-1", "FinanceController"),
    # Entity-backed roles: fallbacks for non-ownership tests only.
    "converter_headers": build_user_headers("test-converter-1", "Converter"),
    "distributor_headers": build_user_headers("test-distributor-1", "Distributor"),
}


def make_converter_headers(user_id: str) -> dict:
    """Converter is entity-backed: pass the actual Converter.id as user_id."""
    return build_user_headers(user_id, "Converter")


def make_distributor_headers(user_id: str) -> dict:
    """Distributor is entity-backed: pass the actual Distributor.id as user_id."""
    return build_user_headers(user_id, "Distributor")


def make_role_headers(user_id: str, role: str) -> dict:
    """Generic builder for ad-hoc identity tests (e.g. segregation-of-duties)."""
    return build_user_headers(user_id, role)
