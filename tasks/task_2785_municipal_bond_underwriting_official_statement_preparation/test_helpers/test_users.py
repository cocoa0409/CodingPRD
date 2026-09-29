"""Actor identities and the header builders that thread them.

PRD section 2.1 splits the six roles in two. ``IssuerOfficial``,
``MunicipalAdvisor`` and ``Underwriter`` are *entity-backed*: their
``X-User-ID`` must resolve to an ``Issuer.id`` or a ``Firm.id``, so a header for
one of those roles can only be built once the backing row exists. ``BondCounsel``,
``RatingAnalyst`` and ``ComplianceOfficer`` are *opaque*: any stable identifier
serves, so they get module-level constants.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# --- Opaque identities (PRD section 2.1) ------------------------------------
# BondCounsel needs two distinct identities because MSRB Rule G-17 forbids the
# author of a section from approving it (PRD sections 2.8, 3.4).
BOND_COUNSEL_DRAFTER_ID = "bc-drafter-0001"
BOND_COUNSEL_REVIEWER_ID = "bc-reviewer-0002"
# RatingAnalyst needs two so the pinned-analyst rule can be exercised
# (PRD section 3.5).
RATING_ANALYST_PRIMARY_ID = "analyst-primary-0001"
RATING_ANALYST_OTHER_ID = "analyst-other-0002"
# ComplianceOfficer is never persisted nor compared (PRD section 2.1).
COMPLIANCE_OFFICER_ID = "compliance-0001"

BOND_COUNSEL_DRAFTER_HEADERS = build_user_headers(
    BOND_COUNSEL_DRAFTER_ID, UserRole.BOND_COUNSEL
)
BOND_COUNSEL_REVIEWER_HEADERS = build_user_headers(
    BOND_COUNSEL_REVIEWER_ID, UserRole.BOND_COUNSEL
)
RATING_ANALYST_HEADERS = build_user_headers(
    RATING_ANALYST_PRIMARY_ID, UserRole.RATING_ANALYST
)
RATING_ANALYST_OTHER_HEADERS = build_user_headers(
    RATING_ANALYST_OTHER_ID, UserRole.RATING_ANALYST
)
COMPLIANCE_HEADERS = build_user_headers(
    COMPLIANCE_OFFICER_ID, UserRole.COMPLIANCE_OFFICER
)


# --- Entity-backed header builders (PRD section 2.1) ------------------------
def make_issuer_official_headers(issuer_id):
    """Headers for an ``IssuerOfficial`` whose ``X-User-ID`` is an ``Issuer.id``."""
    return build_user_headers(issuer_id, UserRole.ISSUER_OFFICIAL)


def make_advisor_headers(firm_id):
    """Headers for a ``MunicipalAdvisor`` whose ``X-User-ID`` is a ``Firm.id``."""
    return build_user_headers(firm_id, UserRole.MUNICIPAL_ADVISOR)


def make_underwriter_headers(firm_id):
    """Headers for an ``Underwriter`` whose ``X-User-ID`` is a ``Firm.id``."""
    return build_user_headers(firm_id, UserRole.UNDERWRITER)


def make_bond_counsel_headers(user_id):
    """Headers for an arbitrary ``BondCounsel`` identity."""
    return build_user_headers(user_id, UserRole.BOND_COUNSEL)


def make_rating_analyst_headers(user_id):
    """Headers for an arbitrary ``RatingAnalyst`` identity."""
    return build_user_headers(user_id, UserRole.RATING_ANALYST)


def make_compliance_headers(user_id=COMPLIANCE_OFFICER_ID):
    """Headers for a ``ComplianceOfficer`` identity."""
    return build_user_headers(user_id, UserRole.COMPLIANCE_OFFICER)


def make_headers(user_id, role):
    """Headers for an arbitrary (identifier, role) pair."""
    return build_user_headers(user_id, role)


# --- Malformed credentials (PRD section 2.1) --------------------------------
def headers_missing_user_id(role):
    """Omit ``X-User-ID`` entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_missing_role(user_id):
    """Omit ``X-User-Role`` entirely."""
    return {"X-User-ID": str(user_id), "Content-Type": "application/json"}


def headers_empty_user_id(role):
    """Send a blank ``X-User-ID``."""
    return {
        "X-User-ID": "",
        "X-User-Role": role,
        "Content-Type": "application/json",
    }


def headers_empty_role(user_id):
    """Send a blank ``X-User-Role``."""
    return {
        "X-User-ID": str(user_id),
        "X-User-Role": "",
        "Content-Type": "application/json",
    }


def headers_no_credentials():
    """Send neither credential header."""
    return {"Content-Type": "application/json"}


def headers_unrecognised_role(user_id, role="Custodian"):
    """Send a role that is not one of the six recognised values."""
    return build_user_headers(user_id, role)


# --- Role cohorts used by authorisation assertions -------------------------
ALL_ROLES = UserRole.ALL
ENTITY_BACKED_ROLES = UserRole.ENTITY_BACKED
OPAQUE_ROLES = UserRole.OPAQUE
