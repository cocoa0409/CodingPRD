"""Request headers for each acting role.

Four roles are operational identities whose acting user identifier is opaque, so
their headers are fixed constants.  Two roles are entity-backed: the seller-side
representative acts as a seller and the brand-side approver acts as an
advertiser, so their acting user identifier IS that entity's own identifier.
Those two roles therefore have no usable constant — build their headers with
:func:`make_seller_rep_headers` and :func:`make_advertiser_client_headers` once
the seller or advertiser exists, passing the entity's ``id``.

Two distinct controller identifiers are provided because remittance requires an
acting controller whose identifier differs from the buyer that placed the buy.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# --------------------------------------------------------------------------
# Opaque operator identifiers
# --------------------------------------------------------------------------
PLANNER_USER_ID = "planner-01"
PLANNER_ALT_USER_ID = "planner-02"
BUYER_USER_ID = "buyer-01"
BUYER_ALT_USER_ID = "buyer-02"
CONTROLLER_USER_ID = "controller-01"
CONTROLLER_ALT_USER_ID = "controller-02"
MEASUREMENT_USER_ID = "measurement-01"


# --------------------------------------------------------------------------
# Entity-backed header builders — the entity id IS the acting user id
# --------------------------------------------------------------------------
def make_seller_rep_headers(seller_id: str) -> Dict[str, str]:
    """Headers for the seller-side representative acting as the given seller."""
    return build_user_headers(seller_id, UserRole.SELLER_REP.value)


def make_advertiser_client_headers(advertiser_id: str) -> Dict[str, str]:
    """Headers for the brand-side approver acting as the given advertiser."""
    return build_user_headers(advertiser_id, UserRole.ADVERTISER_CLIENT.value)


# --------------------------------------------------------------------------
# Opaque header builders
# --------------------------------------------------------------------------
def make_planner_headers(user_id: str = PLANNER_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.AGENCY_PLANNER.value)


def make_buyer_headers(user_id: str = BUYER_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.AGENCY_BUYER.value)


def make_controller_headers(user_id: str = CONTROLLER_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.AGENCY_CONTROLLER.value)


def make_measurement_provider_headers(
    user_id: str = MEASUREMENT_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.MEASUREMENT_PROVIDER.value)


# --------------------------------------------------------------------------
# Ready-made header sets for the opaque roles
# --------------------------------------------------------------------------
PLANNER_HEADERS = make_planner_headers()
PLANNER_ALT_HEADERS = make_planner_headers(PLANNER_ALT_USER_ID)
BUYER_HEADERS = make_buyer_headers()
BUYER_ALT_HEADERS = make_buyer_headers(BUYER_ALT_USER_ID)
CONTROLLER_HEADERS = make_controller_headers()
CONTROLLER_ALT_HEADERS = make_controller_headers(CONTROLLER_ALT_USER_ID)
MEASUREMENT_HEADERS = make_measurement_provider_headers()

#: Headers carrying neither identity header at all.
NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}

#: Headers carrying an acting user but no role.
NO_ROLE_HEADERS: Dict[str, str] = {
    "X-User-ID": CONTROLLER_USER_ID,
    "Content-Type": "application/json",
}

#: Headers naming a role outside the declared set.
UNDECLARED_ROLE_HEADERS: Dict[str, str] = {
    "X-User-ID": CONTROLLER_USER_ID,
    "X-User-Role": "MediaAuditor",
    "Content-Type": "application/json",
}

#: Headers carrying a role but an empty acting user identifier.
EMPTY_USER_ID_HEADERS: Dict[str, str] = {
    "X-User-ID": "",
    "X-User-Role": UserRole.AGENCY_CONTROLLER.value,
    "Content-Type": "application/json",
}

TEST_USERS: Dict[str, Dict[str, str]] = {
    "planner": PLANNER_HEADERS,
    "planner_alt": PLANNER_ALT_HEADERS,
    "buyer": BUYER_HEADERS,
    "buyer_alt": BUYER_ALT_HEADERS,
    "controller": CONTROLLER_HEADERS,
    "controller_alt": CONTROLLER_ALT_HEADERS,
    "measurement_provider": MEASUREMENT_HEADERS,
    "no_auth": NO_AUTH_HEADERS,
    "no_role": NO_ROLE_HEADERS,
    "undeclared_role": UNDECLARED_ROLE_HEADERS,
    "empty_user_id": EMPTY_USER_ID_HEADERS,
}
