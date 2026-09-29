"""Pre-built request headers for each role.

Every request carries an X-User-ID and an X-User-Role header.  For an
Underwriter, Broker, ClaimsAdjuster or Auditor the identifier is opaque and is
never compared against any stored entity, so a stable literal is used.  For an
OperatorUser the identifier is the acting operator's own id, so those headers
must be built per test from the operator created in setup.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import Headers, Role

# Opaque user identifiers.  Two distinct identifiers exist for the Underwriter
# and the ClaimsAdjuster because segregation of duties requires the second actor
# of a pair to differ from the first.
UNDERWRITER_ID = "uw-1"
SECOND_UNDERWRITER_ID = "uw-2"
BROKER_ID = "bkr-1"
CLAIMS_ADJUSTER_ID = "adj-1"
SECOND_CLAIMS_ADJUSTER_ID = "adj-2"
AUDITOR_ID = "aud-1"

UNDERWRITER = build_user_headers(UNDERWRITER_ID, Role.UNDERWRITER)
SECOND_UNDERWRITER = build_user_headers(SECOND_UNDERWRITER_ID, Role.UNDERWRITER)
BROKER = build_user_headers(BROKER_ID, Role.BROKER)
CLAIMS_ADJUSTER = build_user_headers(CLAIMS_ADJUSTER_ID, Role.CLAIMS_ADJUSTER)
SECOND_CLAIMS_ADJUSTER = build_user_headers(SECOND_CLAIMS_ADJUSTER_ID, Role.CLAIMS_ADJUSTER)
AUDITOR = build_user_headers(AUDITOR_ID, Role.AUDITOR)

# The four roles whose identifier is opaque, keyed by role name.
OPAQUE_HEADERS_BY_ROLE = {
    Role.UNDERWRITER: UNDERWRITER,
    Role.BROKER: BROKER,
    Role.CLAIMS_ADJUSTER: CLAIMS_ADJUSTER,
    Role.AUDITOR: AUDITOR,
}


def operator_user(operator_id: str) -> Headers:
    """Headers for an OperatorUser acting as the given operator."""
    return build_user_headers(operator_id, Role.OPERATOR_USER)


def headers_for_role(role: str, operator_id: str = None) -> Headers:
    """Headers for any of the five roles, threading the operator identity through."""
    if role == Role.OPERATOR_USER:
        assert operator_id is not None, (
            "an OperatorUser's X-User-ID is the acting operator's own id"
        )
        return operator_user(operator_id)
    return dict(OPAQUE_HEADERS_BY_ROLE[role])


def with_role(role: str) -> Headers:
    """Headers carrying an arbitrary role string, for unrecognised-role tests."""
    return build_user_headers(UNDERWRITER_ID, role)


def with_user_id(user_id: str, role: str = Role.UNDERWRITER) -> Headers:
    """Headers carrying an arbitrary user identifier."""
    return build_user_headers(user_id, role)


# ----------------------------------------------------------------------
# Malformed authentication headers.
#
# An absent header and a present-but-empty header are both treated as
# missing, so the empty variants use the empty string exactly.
# ----------------------------------------------------------------------
NO_HEADERS: Headers = {"Content-Type": "application/json"}

MISSING_USER_ID: Headers = {
    "X-User-Role": Role.UNDERWRITER,
    "Content-Type": "application/json",
}

MISSING_ROLE: Headers = {
    "X-User-ID": UNDERWRITER_ID,
    "Content-Type": "application/json",
}

EMPTY_USER_ID: Headers = build_user_headers("", Role.UNDERWRITER)
EMPTY_ROLE: Headers = build_user_headers(UNDERWRITER_ID, "")
WHITESPACE_USER_ID: Headers = build_user_headers("   ", Role.UNDERWRITER)
WHITESPACE_ROLE: Headers = build_user_headers(UNDERWRITER_ID, "   ")

UNKNOWN_ROLE: Headers = build_user_headers(UNDERWRITER_ID, "Actuary")

__all__ = [
    "UNDERWRITER_ID",
    "SECOND_UNDERWRITER_ID",
    "BROKER_ID",
    "CLAIMS_ADJUSTER_ID",
    "SECOND_CLAIMS_ADJUSTER_ID",
    "AUDITOR_ID",
    "UNDERWRITER",
    "SECOND_UNDERWRITER",
    "BROKER",
    "CLAIMS_ADJUSTER",
    "SECOND_CLAIMS_ADJUSTER",
    "AUDITOR",
    "OPAQUE_HEADERS_BY_ROLE",
    "operator_user",
    "headers_for_role",
    "with_role",
    "with_user_id",
    "NO_HEADERS",
    "MISSING_USER_ID",
    "MISSING_ROLE",
    "EMPTY_USER_ID",
    "EMPTY_ROLE",
    "WHITESPACE_USER_ID",
    "WHITESPACE_ROLE",
    "UNKNOWN_ROLE",
]
