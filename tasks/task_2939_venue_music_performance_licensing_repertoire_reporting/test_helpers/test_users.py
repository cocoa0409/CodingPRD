"""
Acting identities and the header dictionaries that carry them.

PRD §2.1 fixes the two headers every request must carry and says how each role's
``X-User-ID`` relates to persisted data:

- ``LicensingAdmin``, ``ComplianceAuditor`` and ``SettlementOfficer`` each hold
  "an opaque operator identifier not tied to any persisted entity", so this
  module hands out stable, distinct opaque ids per acting person.
- ``VenueOperator`` is different: "``X-User-ID`` is the ``id`` of the acting
  ``Venue``".  There is therefore no constant operator id — callers must build
  the headers from the venue row they created, via
  :func:`venue_operator_headers`.

Segregation of duties (PRD §2.1) needs *two* auditors and *two* settlement
officers so that the person who issued findings can be told apart from the
person who negotiates the settlement.  Those four distinct identities live here.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_COMPLIANCE_AUDITOR,
    ROLE_LICENSING_ADMIN,
    ROLE_SETTLEMENT_OFFICER,
    ROLE_VENUE_OPERATOR,
)

# ─── Opaque operator identities ───────────────────────────────────────────

ADMIN_USER_ID = "admin-1"
ADMIN_USER_ID_ALT = "admin-2"

AUDITOR_USER_ID = "auditor-1"
AUDITOR_USER_ID_ALT = "auditor-2"

SETTLEMENT_USER_ID = "settlement-1"
SETTLEMENT_USER_ID_ALT = "settlement-2"


def admin_headers(user_id: str = ADMIN_USER_ID) -> Dict[str, str]:
    """Headers for a ``LicensingAdmin``, the society-side administrator."""
    return build_user_headers(user_id, ROLE_LICENSING_ADMIN)


def auditor_headers(user_id: str = AUDITOR_USER_ID) -> Dict[str, str]:
    """Headers for a ``ComplianceAuditor``.

    The default identity is the one that issues findings; pass
    ``AUDITOR_USER_ID_ALT`` for the second auditor used by segregation tests.
    """
    return build_user_headers(user_id, ROLE_COMPLIANCE_AUDITOR)


def settlement_headers(user_id: str = SETTLEMENT_USER_ID) -> Dict[str, str]:
    """Headers for a ``SettlementOfficer``."""
    return build_user_headers(user_id, ROLE_SETTLEMENT_OFFICER)


def venue_operator_headers(venue_id: str) -> Dict[str, str]:
    """Headers for the ``VenueOperator`` of one specific venue.

    PRD §2.1: "When ``X-User-Role`` is ``VenueOperator``, ``X-User-ID`` is the
    ``id`` of the acting ``Venue``."  Always pass the venue row's own ``id``.
    """
    return build_user_headers(venue_id, ROLE_VENUE_OPERATOR)


def headers_with_role(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary (user_id, role) pair, used by role-matrix tests."""
    return build_user_headers(user_id, role)


# ─── Malformed authentication headers (PRD §2.1, §2.12 rule 1) ────────────
#
# "Both must be present and non-empty".  Every builder below sends a *real*
# empty string or genuinely omits the header — never a whitespace filler, which
# would be a non-empty value and would not exercise the rule under test.


def headers_missing_user_id(role: str = ROLE_LICENSING_ADMIN) -> Dict[str, str]:
    """``X-User-Role`` present, ``X-User-ID`` entirely absent."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_missing_role(user_id: str = ADMIN_USER_ID) -> Dict[str, str]:
    """``X-User-ID`` present, ``X-User-Role`` entirely absent."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_empty_user_id(role: str = ROLE_LICENSING_ADMIN) -> Dict[str, str]:
    """``X-User-ID`` present but empty, which PRD §2.1 treats as absent."""
    return {
        "X-User-ID": "",
        "X-User-Role": role,
        "Content-Type": "application/json",
    }


def headers_empty_role(user_id: str = ADMIN_USER_ID) -> Dict[str, str]:
    """``X-User-Role`` present but empty."""
    return {
        "X-User-ID": user_id,
        "X-User-Role": "",
        "Content-Type": "application/json",
    }


def headers_unknown_role(
    user_id: str = ADMIN_USER_ID, role: str = "Auditor"
) -> Dict[str, str]:
    """A role outside the four recognised values."""
    return {
        "X-User-ID": user_id,
        "X-User-Role": role,
        "Content-Type": "application/json",
    }


def headers_none() -> Optional[Dict[str, str]]:
    """No authentication headers at all, for the clock endpoint of PRD §2.4."""
    return {"Content-Type": "application/json"}
