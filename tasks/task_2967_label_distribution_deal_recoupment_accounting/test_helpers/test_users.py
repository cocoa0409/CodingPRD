"""
Pre-built auth headers for the five roles of PRD Section 2.1.

Two of the five roles are *entity-backed*: "For a `DistributionPartner`, the
`X-User-ID` is the `id` of the `Distributor` record" and "For an `Artist`, the
`X-User-ID` is the `id` of the `Artist` record". There is therefore no usable
constant for those two - always build their headers from the id of the record
created in the fixture, using ``make_partner_headers`` / ``make_artist_headers``.

The other three - `LabelAdmin`, `RoyaltyAnalyst`, `BusinessAffairs` - are
"opaque operator identifiers that are never compared against any entity id", so
stable literals are fine. Two distinct operator ids are provided for each of
them because segregation of duties needs a second actor.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_ARTIST,
    ROLE_BUSINESS_AFFAIRS,
    ROLE_DISTRIBUTION_PARTNER,
    ROLE_LABEL_ADMIN,
    ROLE_ROYALTY_ANALYST,
    UNKNOWN_ROLE,
)

# --- Opaque operator identifiers -------------------------------------------
USER_LABEL_ADMIN = "label-admin-01"
USER_LABEL_ADMIN_2 = "label-admin-02"
USER_ANALYST = "analyst-01"
USER_ANALYST_2 = "analyst-02"
USER_BIZ_AFFAIRS = "biz-affairs-01"
USER_BIZ_AFFAIRS_2 = "biz-affairs-02"

# --- Ready-made headers for the three opaque roles -------------------------
LABEL_ADMIN = build_user_headers(USER_LABEL_ADMIN, ROLE_LABEL_ADMIN)
LABEL_ADMIN_2 = build_user_headers(USER_LABEL_ADMIN_2, ROLE_LABEL_ADMIN)
ANALYST = build_user_headers(USER_ANALYST, ROLE_ROYALTY_ANALYST)
ANALYST_2 = build_user_headers(USER_ANALYST_2, ROLE_ROYALTY_ANALYST)
BIZ_AFFAIRS = build_user_headers(USER_BIZ_AFFAIRS, ROLE_BUSINESS_AFFAIRS)
BIZ_AFFAIRS_2 = build_user_headers(USER_BIZ_AFFAIRS_2, ROLE_BUSINESS_AFFAIRS)


def make_label_admin_headers(user_id=USER_LABEL_ADMIN):
    return build_user_headers(user_id, ROLE_LABEL_ADMIN)


def make_analyst_headers(user_id=USER_ANALYST):
    return build_user_headers(user_id, ROLE_ROYALTY_ANALYST)


def make_biz_affairs_headers(user_id=USER_BIZ_AFFAIRS):
    """Business-affairs headers.

    Pass an explicit ``user_id`` whenever the call is subject to the
    segregation-of-duties test so the acting id can be made to collide with,
    or differ from, the stored preparer / requester id on purpose.
    """
    return build_user_headers(user_id, ROLE_BUSINESS_AFFAIRS)


def make_partner_headers(distributor_id):
    """DistributionPartner headers. ``distributor_id`` must be a Distributor.id."""
    return build_user_headers(distributor_id, ROLE_DISTRIBUTION_PARTNER)


def make_artist_headers(artist_id):
    """Artist headers. ``artist_id`` must be an Artist.id."""
    return build_user_headers(artist_id, ROLE_ARTIST)


def make_unknown_role_headers(user_id=USER_LABEL_ADMIN):
    """A well-formed header pair naming a role outside the closed five."""
    return build_user_headers(user_id, UNKNOWN_ROLE)


# --- Malformed / absent authentication ------------------------------------
# PRD 2.1: "A request that omits either header, or supplies an empty or
# whitespace-only value for either, is unauthenticated". The blank variants use
# "" rather than " " on purpose: requests raises InvalidHeader for a
# whitespace-only header value, so a space would never reach the server.

def headers_without_user_id(role=ROLE_LABEL_ADMIN):
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id=USER_LABEL_ADMIN):
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_blank_user_id(role=ROLE_LABEL_ADMIN):
    return {
        "X-User-ID": "",
        "X-User-Role": role,
        "Content-Type": "application/json",
    }


def headers_blank_role(user_id=USER_LABEL_ADMIN):
    return {
        "X-User-ID": user_id,
        "X-User-Role": "",
        "Content-Type": "application/json",
    }


NO_AUTH_HEADERS = {"Content-Type": "application/json"}
