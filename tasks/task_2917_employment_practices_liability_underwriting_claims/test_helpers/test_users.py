"""Principal identities and request headers.

Opaque-identity roles use stable pinned identifiers so that the four-eyes gates
can be exercised deliberately (one principal acts, a *different* principal of
the same role releases).  The two entity-backed roles carry the identifier of
the record they are: a ``PanelCounsel`` principal's ``X-User-ID`` is the
``DefensePanelFirm.id`` and a ``PolicyholderContact`` principal's ``X-User-ID``
is the ``Applicant.id``, so their headers must be built per resource.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import (
    ROLE_CLAIMS_ADJUSTER,
    ROLE_CLAIMS_MANAGER,
    ROLE_PANEL_COUNSEL,
    ROLE_PLATFORM_ADMIN,
    ROLE_POLICYHOLDER_CONTACT,
    ROLE_UNDERWRITER,
    ROLE_UNDERWRITING_MANAGER,
)

# --- Pinned opaque principals --------------------------------------------
ADMIN_001 = "admin-001"
UW_001 = "uw-001"
UW_002 = "uw-002"
UWM_001 = "uwm-001"
UWM_002 = "uwm-002"
ADJ_001 = "adj-001"
ADJ_002 = "adj-002"
CLM_001 = "clm-001"
CLM_002 = "clm-002"

ADMIN = build_user_headers(ADMIN_001, ROLE_PLATFORM_ADMIN)

UNDERWRITER = build_user_headers(UW_001, ROLE_UNDERWRITER)
UNDERWRITER_2 = build_user_headers(UW_002, ROLE_UNDERWRITER)

UW_MANAGER = build_user_headers(UWM_001, ROLE_UNDERWRITING_MANAGER)
UW_MANAGER_2 = build_user_headers(UWM_002, ROLE_UNDERWRITING_MANAGER)

ADJUSTER = build_user_headers(ADJ_001, ROLE_CLAIMS_ADJUSTER)
ADJUSTER_2 = build_user_headers(ADJ_002, ROLE_CLAIMS_ADJUSTER)

CLAIMS_MANAGER = build_user_headers(CLM_001, ROLE_CLAIMS_MANAGER)
CLAIMS_MANAGER_2 = build_user_headers(CLM_002, ROLE_CLAIMS_MANAGER)


def headers_for(user_id: str, role: str) -> dict:
    """Build headers for an arbitrary principal id / role pair."""
    return build_user_headers(user_id, role)


def panel_counsel(panel_firm_id: str) -> dict:
    """Headers for the PanelCounsel principal that *is* the given panel firm."""
    return build_user_headers(panel_firm_id, ROLE_PANEL_COUNSEL)


def policyholder_contact(applicant_id: str) -> dict:
    """Headers for the PolicyholderContact principal that *is* the given applicant."""
    return build_user_headers(applicant_id, ROLE_POLICYHOLDER_CONTACT)


def as_role(role: str, user_id: str = "probe-001") -> dict:
    """Headers for a syntactically valid principal of an arbitrary role."""
    return build_user_headers(user_id, role)


def blank_user_id(role: str = ROLE_PLATFORM_ADMIN) -> dict:
    """Headers whose X-User-ID is present but empty."""
    return {"X-User-ID": "", "X-User-Role": role}


def missing_user_id(role: str = ROLE_PLATFORM_ADMIN) -> dict:
    """Headers with no X-User-ID at all."""
    return {"X-User-Role": role}
