"""Caller identities and the two mandatory headers of PRD §2.1.

Seven of the eight roles act under an opaque operator identifier: "When
`X-User-Role` is `ProgramAdmin`, `PartnerManager`, `ComplianceAnalyst`,
`FinanceAnalyst`, `FinanceController`, `TrackingIngestor` or `Anonymous`,
`X-User-ID` is an opaque operator identifier not tied to any persisted
entity."  The eighth is different: "When `X-User-Role` is `AffiliatePartner`,
`X-User-ID` is the `id` of the acting `Affiliate`" — so a partner caller is
always built from a real Affiliate id through
:func:`make_affiliate_partner_headers`.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_AFFILIATE_PARTNER,
    ROLE_ANONYMOUS,
    ROLE_COMPLIANCE_ANALYST,
    ROLE_FINANCE_ANALYST,
    ROLE_FINANCE_CONTROLLER,
    ROLE_PARTNER_MANAGER,
    ROLE_PROGRAM_ADMIN,
    ROLE_TRACKING_INGESTOR,
)

# ── Operator identifiers ─────────────────────────────────────────────────────

PROGRAM_ADMIN_ID = "adm-001"
PARTNER_MANAGER_ID = "pm-001"
COMPLIANCE_ANALYST_ID = "cmp-001"
SECOND_COMPLIANCE_ANALYST_ID = "cmp-002"
FINANCE_ANALYST_ID = "fa-001"
FINANCE_CONTROLLER_ID = "fc-001"
TRACKING_INGESTOR_ID = "ing-001"
ANONYMOUS_ID = "anon-001"

# ── Pre-built header dictionaries ────────────────────────────────────────────

PROGRAM_ADMIN = build_user_headers(PROGRAM_ADMIN_ID, ROLE_PROGRAM_ADMIN)
PARTNER_MANAGER = build_user_headers(PARTNER_MANAGER_ID, ROLE_PARTNER_MANAGER)
COMPLIANCE_ANALYST = build_user_headers(
    COMPLIANCE_ANALYST_ID, ROLE_COMPLIANCE_ANALYST
)
SECOND_COMPLIANCE_ANALYST = build_user_headers(
    SECOND_COMPLIANCE_ANALYST_ID, ROLE_COMPLIANCE_ANALYST
)
FINANCE_ANALYST = build_user_headers(FINANCE_ANALYST_ID, ROLE_FINANCE_ANALYST)
FINANCE_CONTROLLER = build_user_headers(
    FINANCE_CONTROLLER_ID, ROLE_FINANCE_CONTROLLER
)
TRACKING_INGESTOR = build_user_headers(TRACKING_INGESTOR_ID, ROLE_TRACKING_INGESTOR)

# §2.1: partner self-registration "is deliberately reachable without
# credentials", so the anonymous caller sends no `X-User-ID` at all.
ANONYMOUS: Dict[str, str] = {
    "X-User-Role": ROLE_ANONYMOUS,
    "Content-Type": "application/json",
}

# A caller that omits `X-User-ID` while claiming an authenticated role.
NO_USER_ID_PROGRAM_ADMIN: Dict[str, str] = {
    "X-User-Role": ROLE_PROGRAM_ADMIN,
    "Content-Type": "application/json",
}

UNKNOWN_USER_PROGRAM_ADMIN = build_user_headers(
    "no-such-operator-9999", ROLE_PROGRAM_ADMIN
)


def make_affiliate_partner_headers(affiliate_id: str) -> Dict[str, str]:
    """Headers for an `AffiliatePartner` acting as the partner ``affiliate_id``.

    §2.1 makes the partner's own entity id the value of `X-User-ID`, and
    ownership checks compare "the resource's partner reference to `X-User-ID`".
    """
    return build_user_headers(affiliate_id, ROLE_AFFILIATE_PARTNER)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary (user_id, role) pair."""
    return build_user_headers(user_id, role)


#: Every role that may pin the logical clock, per the §4 route table.
CLOCK_CAPABLE_HEADERS = (
    PROGRAM_ADMIN,
    FINANCE_ANALYST,
    FINANCE_CONTROLLER,
    COMPLIANCE_ANALYST,
    PARTNER_MANAGER,
    TRACKING_INGESTOR,
)
