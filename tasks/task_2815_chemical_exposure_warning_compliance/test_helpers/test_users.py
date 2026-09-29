"""Auth header sets for every declared role.

Five of the six roles are opaque: any stable user identifier works, so a shared
constant header set is enough.  ``SupplierPortalUser`` is different — its
``X-User-ID`` *is* the identifier of the supplier row it speaks for, so callers
must mint a header set per supplier with
:func:`make_supplier_portal_user_headers`.  Segregation-of-duties rules also key
off ``X-User-ID`` rather than the role, so a second identity is provided for
every role that reviews, approves or executes somebody else's work.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_COMPLIANCE_ANALYST,
    ROLE_LABELING_SPECIALIST,
    ROLE_REGISTRY_ADMIN,
    ROLE_REGULATORY_COUNSEL,
    ROLE_SUPPLIER_PORTAL_USER,
    ROLE_TOXICOLOGY_REVIEWER,
)
from .types import Headers

# ─── Canonical user identifiers ───────────────────────────────────────────────
ADMIN_1 = "admin_1"
CA_1 = "ca_1"
CA_2 = "ca_2"
TOX_1 = "tox_1"
TOX_2 = "tox_2"
LS_1 = "ls_1"
LS_2 = "ls_2"
RC_1 = "rc_1"
RC_2 = "rc_2"

# A single human who legitimately holds two roles.  Used to show that
# segregation of duties is enforced on the identifier, not on the role.
DUAL_1 = "dual_1"

UNKNOWN_ROLE = "AuditorGeneral"


# ─── Shared header sets for the five opaque roles ─────────────────────────────
REGISTRY_ADMIN = build_user_headers(ADMIN_1, ROLE_REGISTRY_ADMIN)
COMPLIANCE_ANALYST = build_user_headers(CA_1, ROLE_COMPLIANCE_ANALYST)
TOXICOLOGY_REVIEWER = build_user_headers(TOX_1, ROLE_TOXICOLOGY_REVIEWER)
LABELING_SPECIALIST = build_user_headers(LS_1, ROLE_LABELING_SPECIALIST)
REGULATORY_COUNSEL = build_user_headers(RC_1, ROLE_REGULATORY_COUNSEL)

# Second identities, same roles — the counterparties for peer review, approval
# and settlement execution.
COMPLIANCE_ANALYST_2 = build_user_headers(CA_2, ROLE_COMPLIANCE_ANALYST)
TOXICOLOGY_REVIEWER_2 = build_user_headers(TOX_2, ROLE_TOXICOLOGY_REVIEWER)
LABELING_SPECIALIST_2 = build_user_headers(LS_2, ROLE_LABELING_SPECIALIST)
REGULATORY_COUNSEL_2 = build_user_headers(RC_2, ROLE_REGULATORY_COUNSEL)

TEST_USERS = {
    ROLE_REGISTRY_ADMIN: REGISTRY_ADMIN,
    ROLE_COMPLIANCE_ANALYST: COMPLIANCE_ANALYST,
    ROLE_TOXICOLOGY_REVIEWER: TOXICOLOGY_REVIEWER,
    ROLE_LABELING_SPECIALIST: LABELING_SPECIALIST,
    ROLE_REGULATORY_COUNSEL: REGULATORY_COUNSEL,
}


# ─── Per-identity builders ────────────────────────────────────────────────────

def make_registry_admin_headers(user_id: str = ADMIN_1) -> Headers:
    return build_user_headers(user_id, ROLE_REGISTRY_ADMIN)


def make_compliance_analyst_headers(user_id: str = CA_1) -> Headers:
    return build_user_headers(user_id, ROLE_COMPLIANCE_ANALYST)


def make_toxicology_reviewer_headers(user_id: str = TOX_1) -> Headers:
    return build_user_headers(user_id, ROLE_TOXICOLOGY_REVIEWER)


def make_labeling_specialist_headers(user_id: str = LS_1) -> Headers:
    return build_user_headers(user_id, ROLE_LABELING_SPECIALIST)


def make_regulatory_counsel_headers(user_id: str = RC_1) -> Headers:
    return build_user_headers(user_id, ROLE_REGULATORY_COUNSEL)


def make_supplier_portal_user_headers(supplier_id: str) -> Headers:
    """Headers for the portal account of one specific supplier.

    The portal role is entity backed: the caller's ``X-User-ID`` is the
    ``Supplier.id`` it acts for, and a material whose ``supplier_id`` differs
    from that identifier is out of reach.
    """
    return build_user_headers(supplier_id, ROLE_SUPPLIER_PORTAL_USER)


def make_headers_for_role(role: str, user_id: str) -> Headers:
    """Headers for an arbitrary role/identity pair."""
    return build_user_headers(user_id, role)


# ─── Deliberately malformed header sets ───────────────────────────────────────

def headers_without_role(user_id: str = CA_1) -> Headers:
    """A request that carries an identity but no ``X-User-Role`` at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str = ROLE_COMPLIANCE_ANALYST) -> Headers:
    """A request that names a role but carries no ``X-User-ID``."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_unknown_role(
    user_id: str = CA_1, role: str = UNKNOWN_ROLE
) -> Headers:
    """A request naming a role the API does not declare."""
    return build_user_headers(user_id, role)
