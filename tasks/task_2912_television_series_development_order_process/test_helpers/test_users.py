"""Auth header builders for the seven roles of this API.

The contract identifies the caller with two headers, ``X-User-ID`` and
``X-User-Role``. Six roles are opaque: the user id is any non-empty string and the
server never resolves it to a stored row. ``AgencyRep`` is the exception — its
``X-User-ID`` must be the id of an existing Agency, and every agency-scoped
operation compares that id against the agency named in the request.

Committee decisions on a greenlight request are additionally segregated by user
id, so the named constants below give each committee its own distinct identity.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# ─── Roles ────────────────────────────────────────────
ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_DEVELOPMENT_EXEC = "DevelopmentExec"
ROLE_BUSINESS_AFFAIRS = "BusinessAffairs"
ROLE_FINANCE_CONTROLLER = "FinanceController"
ROLE_RESEARCH_ANALYST = "ResearchAnalyst"
ROLE_STUDIO_PARTNER = "StudioPartner"
ROLE_AGENCY_REP = "AgencyRep"

ALL_ROLES = (
    ROLE_PLATFORM_ADMIN,
    ROLE_DEVELOPMENT_EXEC,
    ROLE_BUSINESS_AFFAIRS,
    ROLE_FINANCE_CONTROLLER,
    ROLE_RESEARCH_ANALYST,
    ROLE_STUDIO_PARTNER,
    ROLE_AGENCY_REP,
)

# ─── Opaque user identities ───────────────────────────
# Distinct ids for owners the contract requires to differ.
USER_ADMIN = "u-admin-1"
USER_EXEC = "u-exec-1"
USER_EXEC_CREATIVE_1 = "u-creative-1"
USER_EXEC_CREATIVE_2 = "u-creative-2"
USER_BA_1 = "u-ba-1"
USER_BA_2 = "u-ba-2"
USER_BA_9 = "u-ba-9"
USER_FIN_1 = "u-fin-1"
USER_FINANCE_1 = "u-finance-1"
USER_SHARED_1 = "u-shared-1"
USER_RESEARCH = "u-research-1"
USER_STUDIO = "u-studio-1"


def platform_admin_headers(user_id: str = USER_ADMIN) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_PLATFORM_ADMIN)


def development_exec_headers(user_id: str = USER_EXEC) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_DEVELOPMENT_EXEC)


def business_affairs_headers(user_id: str = USER_BA_1) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_BUSINESS_AFFAIRS)


def finance_controller_headers(user_id: str = USER_FIN_1) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_FINANCE_CONTROLLER)


def research_analyst_headers(user_id: str = USER_RESEARCH) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_RESEARCH_ANALYST)


def studio_partner_headers(user_id: str = USER_STUDIO) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_STUDIO_PARTNER)


def agency_rep_headers(agency_id: str) -> Dict[str, str]:
    """AgencyRep is entity-backed: its X-User-ID is the Agency's own id."""
    return build_user_headers(agency_id, ROLE_AGENCY_REP)


def headers_for_role(role: str, user_id: str) -> Dict[str, str]:
    """Build headers for an arbitrary role/user pair."""
    return build_user_headers(user_id, role)


def no_auth_headers() -> Dict[str, str]:
    """No X-User-ID and no X-User-Role header at all."""
    return {"Content-Type": "application/json"}


def blank_auth_headers() -> Dict[str, str]:
    """Both identity headers present but empty. The empty string is not a role.

    The values are the empty string rather than whitespace: a whitespace-only
    header value is rejected by the HTTP client before it ever reaches the API.
    """
    return {"X-User-ID": "", "X-User-Role": "", "Content-Type": "application/json"}


def missing_role_headers(user_id: str = USER_EXEC) -> Dict[str, str]:
    """A user id with no role header."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def missing_user_id_headers(role: str = ROLE_DEVELOPMENT_EXEC) -> Dict[str, str]:
    """A role with no user id header."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
