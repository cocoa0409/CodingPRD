"""Pre-built role headers for every role in the PRD.

Every role in this API is opaque — none is backed by a persisted entity — so a
shared per-role constant is the canonical form and no per-instance builder is
required. Traveler ownership is established by matching X-User-ID against an
itinerary's traveler_user_id, so several distinct traveler identities are
supplied for tests that need two different travelers.
"""
from prd_bench_local_runner.testing import build_user_headers

TRAVELER_MARA = "tv-mara"
TRAVELER_OTIS = "tv-otis"
TRAVELER_RAE = "tv-rae"
TRAVELER_SOMEONE_ELSE = "tv-someone-else"

OPS_ID = "oa-desk-1"
RISK_ANALYST_ID = "ra-dmitri"
ADJUSTER_INGRID = "ca-ingrid"
ADJUSTER_PAVEL = "ca-pavel"
ADJUSTER_ROSA = "ca-rosa"
ADMIN_ID = "pa-root"
SYSTEM_OPERATOR_ID = "so-batch-1"

TEST_USERS = {
    "traveler_headers": build_user_headers(TRAVELER_MARA, "Traveler"),
    "traveler_otis_headers": build_user_headers(TRAVELER_OTIS, "Traveler"),
    "traveler_rae_headers": build_user_headers(TRAVELER_RAE, "Traveler"),
    "traveler_impostor_headers": build_user_headers(TRAVELER_SOMEONE_ELSE, "Traveler"),
    "ops_headers": build_user_headers(OPS_ID, "OpsAgent"),
    "risk_analyst_headers": build_user_headers(RISK_ANALYST_ID, "RiskAnalyst"),
    "adjuster_ingrid_headers": build_user_headers(ADJUSTER_INGRID, "ClaimsAdjuster"),
    "adjuster_pavel_headers": build_user_headers(ADJUSTER_PAVEL, "ClaimsAdjuster"),
    "adjuster_rosa_headers": build_user_headers(ADJUSTER_ROSA, "ClaimsAdjuster"),
    "admin_headers": build_user_headers(ADMIN_ID, "PlatformAdmin"),
    "system_operator_headers": build_user_headers(SYSTEM_OPERATOR_ID, "SystemOperator"),
}


def make_traveler_headers(user_id: str) -> dict:
    """Build headers for a specific traveler identity.

    Every role is opaque, so this helper exists only to make an explicit
    traveller identity readable at the call site.
    """
    return build_user_headers(user_id, "Traveler")