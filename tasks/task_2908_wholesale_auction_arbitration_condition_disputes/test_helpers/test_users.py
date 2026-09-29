"""Header builders for the six roles of PRD section 2.1.

`AuctionAdmin`, `BlockClerk`, `Arbitrator` and `Inspector` are opaque operator
identities.  `BuyerRep` and `SellerRep` are entity-backed: the `X-User-ID` must
be the id of the Buyer (respectively Seller) the caller speaks for, so those
builders take the entity id.
"""
from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ADMIN_USER_ID,
    ARB_DECIDE_USER_ID,
    ARB_INTAKE_USER_ID,
    CLERK_USER_ID,
    INSPECTOR_USER_ID,
)
from .types import UserRole


def admin_headers(user_id: str = ADMIN_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.AUCTION_ADMIN.value)


def clerk_headers(user_id: str = CLERK_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.BLOCK_CLERK.value)


def arbitrator_headers(user_id: str = ARB_INTAKE_USER_ID) -> Dict[str, str]:
    """Arbitrator identity.  Two distinct ids are needed for segregation of
    duties: the intake arbitrator may not also decide the case."""
    return build_user_headers(user_id, UserRole.ARBITRATOR.value)


def intake_arbitrator_headers() -> Dict[str, str]:
    return arbitrator_headers(ARB_INTAKE_USER_ID)


def deciding_arbitrator_headers() -> Dict[str, str]:
    return arbitrator_headers(ARB_DECIDE_USER_ID)


def inspector_headers(user_id: str = INSPECTOR_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.INSPECTOR.value)


def buyer_rep_headers(buyer_id: str) -> Dict[str, str]:
    """BuyerRep speaks for exactly one Buyer: X-User-ID is that buyer's id."""
    return build_user_headers(buyer_id, UserRole.BUYER_REP.value)


def seller_rep_headers(seller_id: str) -> Dict[str, str]:
    """SellerRep speaks for exactly one Seller: X-User-ID is that seller's id."""
    return build_user_headers(seller_id, UserRole.SELLER_REP.value)


def headers_for_role(role: str, user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, role)


ALL_ROLES = [role.value for role in UserRole]


def headers_missing_role(user_id: str = ADMIN_USER_ID) -> Dict[str, str]:
    """Omit X-User-Role entirely: a missing header must yield ERR_UNAUTHENTICATED."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_blank_role(user_id: str = ADMIN_USER_ID) -> Dict[str, str]:
    """A blank (empty-string, never whitespace) role header."""
    return {
        "X-User-ID": user_id,
        "X-User-Role": "",
        "Content-Type": "application/json",
    }


def headers_missing_user_id(role: str = UserRole.AUCTION_ADMIN.value) -> Dict[str, str]:
    """Omit X-User-ID entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_blank_user_id(role: str = UserRole.AUCTION_ADMIN.value) -> Dict[str, str]:
    """A blank (empty-string, never whitespace) identity header."""
    return {
        "X-User-ID": "",
        "X-User-Role": role,
        "Content-Type": "application/json",
    }


def headers_unknown_role(
    user_id: str = ADMIN_USER_ID, role: str = "Auctioneer"
) -> Dict[str, str]:
    """A syntactically present but unrecognised role value."""
    return build_user_headers(user_id, role)


def other_roles_than(*allowed: str) -> list:
    """Every role except the supplied allowed ones — the ERR_UNAUTHORIZED set."""
    allowed_set = {a for a in allowed}
    return [role for role in ALL_ROLES if role not in allowed_set]


def headers_for(role: str, entity_id: Optional[str] = None) -> Dict[str, str]:
    """Build headers for `role`, defaulting the opaque roles to their operator id."""
    if role == UserRole.BUYER_REP.value or role == UserRole.SELLER_REP.value:
        if entity_id is None:
            raise ValueError(f"{role} is entity-backed and requires an entity id")
        return build_user_headers(entity_id, role)
    defaults = {
        UserRole.AUCTION_ADMIN.value: ADMIN_USER_ID,
        UserRole.BLOCK_CLERK.value: CLERK_USER_ID,
        UserRole.ARBITRATOR.value: ARB_INTAKE_USER_ID,
        UserRole.INSPECTOR.value: INSPECTOR_USER_ID,
    }
    return build_user_headers(entity_id or defaults.get(role, "user-01"), role)
