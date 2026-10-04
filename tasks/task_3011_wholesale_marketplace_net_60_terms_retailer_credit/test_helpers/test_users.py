"""Caller identities and header builders.

Every request carries `X-User-Role` and `X-User-ID`. For the entity-backed
roles (Retailer, Brand) the `X-User-ID` must be the id of the acting entity
row, so those headers are always built per-instance via make_retailer_headers /
make_brand_headers. PlatformAdmin, RiskAnalyst and Anonymous identifiers are
opaque and safe to share.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

PLATFORM_ADMIN_USER_ID = "admin-1"
RISK_ANALYST_USER_ID = "risk-1"
ANONYMOUS_USER_ID = "anon-1"


def make_admin_headers(user_id: str = PLATFORM_ADMIN_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.PLATFORM_ADMIN.value)


def make_risk_headers(user_id: str = RISK_ANALYST_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.RISK_ANALYST.value)


def make_anonymous_headers(user_id: Optional[str] = ANONYMOUS_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id or ANONYMOUS_USER_ID, UserRole.ANONYMOUS.value)


def make_retailer_headers(retailer_id: str) -> Dict[str, str]:
    """Retailer caller headers; X-User-ID must be the acting Retailer's id."""
    return build_user_headers(retailer_id, UserRole.RETAILER.value)


def make_brand_headers(brand_id: str) -> Dict[str, str]:
    """Brand caller headers; X-User-ID must be the acting Brand's id."""
    return build_user_headers(brand_id, UserRole.BRAND.value)


ADMIN = make_admin_headers()
RISK = make_risk_headers()
ANON = make_anonymous_headers()

TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles: shared constants are the canonical form.
    "admin_headers": ADMIN,
    "risk_headers": RISK,
    "anonymous_headers": ANON,
    # Entity-backed roles: fallback constants for non-ownership tests only.
    # Any ownership-gated call MUST use make_retailer_headers /
    # make_brand_headers with the real entity id.
    "retailer_headers": make_retailer_headers("test-retailer-1"),
    "brand_headers": make_brand_headers("test-brand-1"),
}
