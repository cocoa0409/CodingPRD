"""Identity headers for the four peer roles.

The PRD binds `X-User-ID` differently for each role, and the binding is what makes
ownership checks meaningful:

* `Franchisor` — an opaque operator identifier never compared to any entity id.
* `Franchisee` — the `id` of the acting `Territory`.
* `Designer`   — the `id` of the acting `Designer`.
* `VendorRep`  — the `id` of the acting `Vendor`.

Two franchise owners are therefore two *different* `X-User-ID` values, and so are
two designers and two manufacturers. Never share one id between distinct owners.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_DESIGNER,
    ROLE_FRANCHISEE,
    ROLE_FRANCHISOR,
    ROLE_VENDOR_REP,
)
from .types import Headers

# The brand headquarters operator id. It is opaque on purpose: the server records
# it but never compares it to a persisted entity's id.
FRANCHISOR_USER_ID = "hq-ops"

# A second headquarters operator, to show the opaque id is not entity-bound.
FRANCHISOR_USER_ID_ALT = "hq-ops-night-desk"

# A syntactically valid uuid that resolves to no actor at all.
UNKNOWN_ACTOR_ID = "11111111-1111-4111-8111-111111111111"


def franchisor_headers(user_id: str = FRANCHISOR_USER_ID) -> Headers:
    """Headers for brand headquarters."""
    return build_user_headers(user_id, ROLE_FRANCHISOR)


def franchisee_headers(territory_id: str) -> Headers:
    """Headers for the franchise owner of one territory."""
    return build_user_headers(territory_id, ROLE_FRANCHISEE)


def designer_headers(designer_id: str) -> Headers:
    """Headers for one acting designer."""
    return build_user_headers(designer_id, ROLE_DESIGNER)


def vendor_rep_headers(vendor_id: str) -> Headers:
    """Headers for one manufacturer's dispatcher."""
    return build_user_headers(vendor_id, ROLE_VENDOR_REP)


# Aliases matching the identity-threading naming used across the suite.
make_franchisor_headers = franchisor_headers
make_franchisee_headers = franchisee_headers
make_designer_headers = designer_headers
make_vendor_rep_headers = vendor_rep_headers


def headers_for(role: str, user_id: str) -> Headers:
    """Headers for an arbitrary role/id pair."""
    return build_user_headers(user_id, role)


def missing_user_id_headers(role: str = ROLE_DESIGNER) -> Headers:
    """Headers whose `X-User-ID` is absent entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def empty_user_id_headers(role: str = ROLE_DESIGNER) -> Headers:
    """Headers whose `X-User-ID` is present but empty."""
    return build_user_headers("", role)


def unknown_user_id_headers(role: str = ROLE_DESIGNER) -> Headers:
    """Headers whose `X-User-ID` does not resolve to a known actor."""
    return build_user_headers(UNKNOWN_ACTOR_ID, role)


def missing_role_headers(user_id: str = FRANCHISOR_USER_ID) -> Headers:
    """Headers carrying no `X-User-Role` at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}
