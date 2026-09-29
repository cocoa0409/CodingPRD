"""Acting users and their request headers.

§2.1 pins two different identity bindings. "When `X-User-Role` is `Homeowner`,
`X-User-ID` is the `id` of the acting `Homeowner` record", so homeowner headers
must be built from a real homeowner row. "When `X-User-Role` is
`ServicingAgent`, `CreditUnderwriter`, `TitleAgent`, `FieldOpsCoordinator` or
`PortfolioAdmin`, `X-User-ID` is an opaque operator identifier that is not tied
to any persisted entity", so operator ids are free-form strings.

Two-person controls need two distinct operator ids per role, and the audit
fields are asserted against exactly the constants used to make the call.
"""

from .constants import (
    ROLE_CREDIT_UNDERWRITER,
    ROLE_FIELD_OPS,
    ROLE_HOMEOWNER,
    ROLE_PORTFOLIO_ADMIN,
    ROLE_SERVICING_AGENT,
    ROLE_TITLE_AGENT,
    ROLE_UNKNOWN,
)
from .types import Headers

# Operator identifiers. Every distinct actor gets a distinct id so that no
# segregation-of-duties check can pass or fail by accident.
AGENT_1 = "u_agent_1"
AGENT_2 = "u_agent_2"
ADMIN_1 = "u_admin_1"
ADMIN_2 = "u_admin_2"
CREDIT_1 = "u_credit_1"
TITLE_1 = "u_title_1"
TITLE_2 = "u_title_2"
OPS_1 = "u_ops_1"
OPS_2 = "u_ops_2"


def make_headers(user_id: str, role: str) -> Headers:
    """Build the two headers every business endpoint requires."""
    return {"X-User-ID": user_id, "X-User-Role": role}


def agent_headers(user_id: str = AGENT_1) -> Headers:
    return make_headers(user_id, ROLE_SERVICING_AGENT)


def admin_headers(user_id: str = ADMIN_1) -> Headers:
    return make_headers(user_id, ROLE_PORTFOLIO_ADMIN)


def underwriter_headers(user_id: str = CREDIT_1) -> Headers:
    return make_headers(user_id, ROLE_CREDIT_UNDERWRITER)


def title_headers(user_id: str = TITLE_1) -> Headers:
    return make_headers(user_id, ROLE_TITLE_AGENT)


def ops_headers(user_id: str = OPS_1) -> Headers:
    return make_headers(user_id, ROLE_FIELD_OPS)


def homeowner_headers(homeowner_id: str) -> Headers:
    """Homeowner headers carry the homeowner row's own `id` as `X-User-ID`."""
    return make_headers(homeowner_id, ROLE_HOMEOWNER)


def unknown_role_headers(user_id: str = ADMIN_1) -> Headers:
    """Headers carrying a value that is not one of the six role names."""
    return make_headers(user_id, ROLE_UNKNOWN)


# --- Authentication-failure header variants (§2.1, ladder rung 1) -----------
# "If either header is absent, or is present but carries the empty string".


def missing_user_id_headers(role: str = ROLE_SERVICING_AGENT) -> Headers:
    return {"X-User-Role": role}


def missing_role_headers(user_id: str = AGENT_1) -> Headers:
    return {"X-User-ID": user_id}


def empty_user_id_headers(role: str = ROLE_SERVICING_AGENT) -> Headers:
    return {"X-User-ID": "", "X-User-Role": role}


def empty_role_headers(user_id: str = AGENT_1) -> Headers:
    return {"X-User-ID": user_id, "X-User-Role": ""}


def no_headers() -> Headers:
    return {}


AUTH_FAILURE_HEADER_VARIANTS = [
    ("both_absent", {}),
    ("user_id_absent", {"X-User-Role": ROLE_SERVICING_AGENT}),
    ("role_absent", {"X-User-ID": AGENT_1}),
    ("user_id_empty", {"X-User-ID": "", "X-User-Role": ROLE_SERVICING_AGENT}),
    ("role_empty", {"X-User-ID": AGENT_1, "X-User-Role": ""}),
]
