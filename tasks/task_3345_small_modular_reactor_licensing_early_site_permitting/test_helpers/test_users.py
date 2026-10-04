"""Caller identities for the nine declared roles.

Every request carries an ``X-User-ID`` and an ``X-User-Role`` header. Eight
roles are opaque: the server never compares their ``X-User-ID`` against a
persisted entity's ``id``, so a stable identifier is enough. The ninth,
``UtilityParticipant``, is entity-backed: its ``X-User-ID`` is matched against
the ``utility_id`` stored on a ``SubscriptionCommitment``, so any
ownership-gated call (create/execute/withdraw a commitment) must present the
same ``utility_id`` the commitment carries. ``make_utility_headers`` is the
per-instance builder for that case.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Shared header sets for the eight opaque roles.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "dca_applicant": build_user_headers("applicant-1", "DcaApplicant"),
    "nrc_reviewer": build_user_headers("rev-1", "NrcReviewer"),
    "nrc_reviewer_2": build_user_headers("rev-2", "NrcReviewer"),
    "doe_program": build_user_headers("doe-1", "DoeProgram"),
    "supply_chain_manager": build_user_headers("scm-1", "SupplyChainManager"),
    "vendor_auditor": build_user_headers("auditor-1", "VendorAuditor"),
    "site_permit_applicant": build_user_headers("spa-1", "SitePermitApplicant"),
    "public_intervenor": build_user_headers("intervenor-1", "PublicIntervenor"),
    "workforce_coordinator": build_user_headers("wfc-1", "WorkforceCoordinator"),
}


def make_utility_headers(utility_id: str) -> Dict[str, str]:
    """Headers for a UtilityParticipant acting as ``utility_id``.

    The role is entity-backed: ownership-gated calls on a
    SubscriptionCommitment compare its ``utility_id`` to ``X-User-ID``, so
    pass the very identifier the commitment was created with.
    """
    return build_user_headers(utility_id, "UtilityParticipant")


def make_reviewer_headers(reviewer_id: str) -> Dict[str, str]:
    """Headers for a specific NrcReviewer identity.

    Segregation of duties on RAI acceptance compares ``X-User-ID`` against the
    RAI's ``authored_by_user_id``, so tests distinguishing author from accepter
    need two distinct reviewer identities.
    """
    return build_user_headers(reviewer_id, "NrcReviewer")
