"""Header sets for the five roles, plus the malformed-header escape hatches.

Four of the five roles are operator identities: when the role is Actuary,
Underwriter, UnderwritingManager or ClaimsAdjuster the user identifier is an
opaque operator identifier that is not tied to any persisted entity. The fifth
role is entity-backed: when the role is Policyholder the user identifier is the
identifier of the acting policy, so a Policyholder's headers can only be built
once the policy exists.

Two adjuster identities and one manager identity are provided because
segregation of duties is enforced on the acting user's identity: the manager who
decides a referral must not be the underwriter who raised it, and the manager who
settles a claim must not be the adjuster who declared the basis.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# ─── Opaque operator identifiers ──────────────────────────────────────────────

ACTUARY_USER_ID = "act-1"
UNDERWRITER_USER_ID = "uw-1"
UNDERWRITER_2_USER_ID = "uw-2"
MANAGER_USER_ID = "mgr-1"
MANAGER_2_USER_ID = "mgr-2"
ADJUSTER_USER_ID = "adj-1"
ADJUSTER_2_USER_ID = "adj-2"

# ─── Ready-made header sets ───────────────────────────────────────────────────

ACTUARY = build_user_headers(ACTUARY_USER_ID, Role.ACTUARY)
UNDERWRITER = build_user_headers(UNDERWRITER_USER_ID, Role.UNDERWRITER)
UNDERWRITER_2 = build_user_headers(UNDERWRITER_2_USER_ID, Role.UNDERWRITER)
MANAGER = build_user_headers(MANAGER_USER_ID, Role.UNDERWRITING_MANAGER)
MANAGER_2 = build_user_headers(MANAGER_2_USER_ID, Role.UNDERWRITING_MANAGER)
ADJUSTER = build_user_headers(ADJUSTER_USER_ID, Role.CLAIMS_ADJUSTER)
ADJUSTER_2 = build_user_headers(ADJUSTER_2_USER_ID, Role.CLAIMS_ADJUSTER)


def make_policyholder_headers(policy_id: str) -> Dict[str, str]:
    """Headers for the named insured itself: the user identifier IS the policy."""
    return build_user_headers(policy_id, Role.POLICYHOLDER)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary identity, for tests that vary one dimension."""
    return build_user_headers(user_id, role)


# ─── Escape hatches for the authentication rungs ──────────────────────────────

def headers_without_user_id(role: str = Role.UNDERWRITER) -> Dict[str, str]:
    """A request that omits X-User-ID entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_blank_user_id(role: str = Role.UNDERWRITER) -> Dict[str, str]:
    """A request whose X-User-ID is present but blank.

    The blank value is the empty string rather than run of spaces: an HTTP
    header value may not carry leading whitespace, so a whitespace-only value
    is refused by the client before it ever reaches the service, while an empty
    value is transmitted and is exactly the blank header the specification
    rejects with ERR_UNAUTHENTICATED.
    """
    return {
        "X-User-ID": "",
        "X-User-Role": role,
        "Content-Type": "application/json",
    }


def headers_without_role(user_id: str = UNDERWRITER_USER_ID) -> Dict[str, str]:
    """A request that omits X-User-Role entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_with_blank_role(user_id: str = UNDERWRITER_USER_ID) -> Dict[str, str]:
    """A request whose X-User-Role is present but blank.

    Blank is spelled as the empty string for the same transmission reason given
    on ``headers_with_blank_user_id``.
    """
    return {
        "X-User-ID": user_id,
        "X-User-Role": "",
        "Content-Type": "application/json",
    }


def headers_with_unknown_role(
    role: str = "Broker", user_id: str = UNDERWRITER_USER_ID
) -> Dict[str, str]:
    """A request naming a role outside the recognised set of five."""
    return build_user_headers(user_id, role)


UNKNOWN_ROLE = "Broker"

# Every role that is not the one an endpoint authorises, for parametrised RBAC
# families that need a non-listed caller.
ALL_ROLE_HEADERS = {
    Role.ACTUARY: ACTUARY,
    Role.UNDERWRITER: UNDERWRITER,
    Role.UNDERWRITING_MANAGER: MANAGER,
    Role.CLAIMS_ADJUSTER: ADJUSTER,
}
