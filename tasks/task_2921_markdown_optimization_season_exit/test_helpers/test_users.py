"""Pre-built auth headers for every role, plus identity-aware builders.

Role identity is not uniform (PRD 2.1). For ``PricingAnalyst``,
``MerchandiseDirector``, ``VendorRep`` and ``Controller`` the ``X-User-ID`` is
an opaque operator identifier that the server never compares to any entity's
``id``. For ``StoreManager`` the ``X-User-ID`` is the ``id`` of the acting
``Store``, so store-manager headers must be built from a real store id at
test time -- use :func:`make_store_manager_headers`.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CONTROLLER,
    ROLE_MERCHANDISE_DIRECTOR,
    ROLE_PRICING_ANALYST,
    ROLE_STORE_MANAGER,
    ROLE_VENDOR_REP,
)

# Opaque operator identifiers. Distinct ids inside one role exist so that the
# three separations of duty can be exercised without changing role.
ANALYST_ONE_ID = "pa-1"
ANALYST_TWO_ID = "pa-2"
DIRECTOR_ONE_ID = "md-1"
DIRECTOR_TWO_ID = "md-2"
VENDOR_REP_ONE_ID = "vr-1"
VENDOR_REP_TWO_ID = "vr-2"
CONTROLLER_ONE_ID = "ctl-1"
CONTROLLER_TWO_ID = "ctl-2"

# A store manager id that is not any real store's id -- used to show that a
# store-scope execution rejects a manager who does not own the store.
UNOWNED_STORE_MANAGER_ID = "11111111-1111-1111-1111-111111111111"


TEST_USERS: Dict[str, Dict[str, str]] = {
    "analyst": build_user_headers(ANALYST_ONE_ID, ROLE_PRICING_ANALYST),
    "analyst_two": build_user_headers(ANALYST_TWO_ID, ROLE_PRICING_ANALYST),
    "director": build_user_headers(DIRECTOR_ONE_ID, ROLE_MERCHANDISE_DIRECTOR),
    "director_two": build_user_headers(DIRECTOR_TWO_ID, ROLE_MERCHANDISE_DIRECTOR),
    "vendor_rep": build_user_headers(VENDOR_REP_ONE_ID, ROLE_VENDOR_REP),
    "vendor_rep_two": build_user_headers(VENDOR_REP_TWO_ID, ROLE_VENDOR_REP),
    "controller": build_user_headers(CONTROLLER_ONE_ID, ROLE_CONTROLLER),
    "controller_two": build_user_headers(CONTROLLER_TWO_ID, ROLE_CONTROLLER),
    # A store manager whose X-User-ID resolves to no store at all.
    "store_manager": build_user_headers(UNOWNED_STORE_MANAGER_ID, ROLE_STORE_MANAGER),
}

ANALYST_HEADERS = TEST_USERS["analyst"]
ANALYST_TWO_HEADERS = TEST_USERS["analyst_two"]
DIRECTOR_HEADERS = TEST_USERS["director"]
DIRECTOR_TWO_HEADERS = TEST_USERS["director_two"]
VENDOR_REP_HEADERS = TEST_USERS["vendor_rep"]
VENDOR_REP_TWO_HEADERS = TEST_USERS["vendor_rep_two"]
CONTROLLER_HEADERS = TEST_USERS["controller"]
CONTROLLER_TWO_HEADERS = TEST_USERS["controller_two"]


def make_analyst_headers(user_id: str) -> Dict[str, str]:
    """Headers for a ``PricingAnalyst`` acting under an explicit operator id."""
    return build_user_headers(user_id, ROLE_PRICING_ANALYST)


def make_director_headers(user_id: str) -> Dict[str, str]:
    """Headers for a ``MerchandiseDirector`` under an explicit operator id."""
    return build_user_headers(user_id, ROLE_MERCHANDISE_DIRECTOR)


def make_vendor_rep_headers(user_id: str) -> Dict[str, str]:
    """Headers for a ``VendorRep`` under an explicit operator id."""
    return build_user_headers(user_id, ROLE_VENDOR_REP)


def make_controller_headers(user_id: str) -> Dict[str, str]:
    """Headers for a ``Controller`` under an explicit operator id."""
    return build_user_headers(user_id, ROLE_CONTROLLER)


def make_store_manager_headers(store_id: str) -> Dict[str, str]:
    """Headers for the ``StoreManager`` that acts for the given store.

    ``X-User-ID`` must be the ``id`` of the acting ``Store``, because ownership
    checks compare the resource's store foreign key to ``X-User-ID``.
    """
    return build_user_headers(store_id, ROLE_STORE_MANAGER)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary id/role pair."""
    return build_user_headers(user_id, role)


def headers_for_role(role: str) -> Dict[str, str]:
    """A canonical header set for each declared role name."""
    return {
        ROLE_PRICING_ANALYST: ANALYST_HEADERS,
        ROLE_MERCHANDISE_DIRECTOR: DIRECTOR_HEADERS,
        ROLE_STORE_MANAGER: TEST_USERS["store_manager"],
        ROLE_VENDOR_REP: VENDOR_REP_HEADERS,
        ROLE_CONTROLLER: CONTROLLER_HEADERS,
    }[role]


# Malformed identity header sets. A blank value must be an empty string, not
# whitespace, so that the header is actually transmitted.
MISSING_USER_ID_HEADERS = {
    "X-User-Role": ROLE_PRICING_ANALYST,
    "Content-Type": "application/json",
}
MISSING_ROLE_HEADERS = {
    "X-User-ID": ANALYST_ONE_ID,
    "Content-Type": "application/json",
}
BLANK_USER_ID_HEADERS = {
    "X-User-ID": "",
    "X-User-Role": ROLE_PRICING_ANALYST,
    "Content-Type": "application/json",
}
BLANK_ROLE_HEADERS = {
    "X-User-ID": ANALYST_ONE_ID,
    "X-User-Role": "",
    "Content-Type": "application/json",
}
NO_IDENTITY_HEADERS = {"Content-Type": "application/json"}
UNDECLARED_ROLE_HEADERS = build_user_headers(ANALYST_ONE_ID, "MarkdownWizard")
