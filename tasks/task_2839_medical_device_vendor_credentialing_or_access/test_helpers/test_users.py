"""Identity headers for every role the PRD declares.

Section 2.1 splits the eight roles in two. Six of them carry an opaque operator
identifier in ``X-User-ID`` that the server merely records, so those roles get
stable module-level header dictionaries. The two entity-backed roles do not:
a ``VendorAdmin`` must send the acting ``Vendor.id`` and a ``VendorRepUser``
must send the acting ``VendorRep.id``, so those headers are built per entity
through :func:`make_vendor_admin_headers` and :func:`make_vendor_rep_headers`.

Several PRD rules compare ``X-User-ID`` values for inequality (segregation of
duties, section 2.10), so two distinct operator identifiers exist for each
operator role that has to both set something up and be barred from deciding it.
"""

from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CLINICAL_SPONSOR,
    ROLE_COMPLIANCE_ADMIN,
    ROLE_CREDENTIALING_OFFICER,
    ROLE_OR_COORDINATOR,
    ROLE_STERILE_PROCESSING_TECH,
    ROLE_VALUE_ANALYSIS_APPROVER,
    ROLE_VENDOR_ADMIN,
    ROLE_VENDOR_REP_USER,
)

# ── Opaque operator identifiers ───────────────────────────────────────────────
USER_CREDENTIALING_1 = "user_credentialing_1"
USER_CREDENTIALING_2 = "user_credentialing_2"
USER_ORC_1 = "user_orc_1"
USER_ORC_2 = "user_orc_2"
USER_COMPLIANCE_1 = "user_compliance_1"
USER_COMPLIANCE_2 = "user_compliance_2"
USER_SPONSOR_1 = "user_sponsor_1"
USER_SPONSOR_2 = "user_sponsor_2"
USER_VAC_1 = "user_vac_1"
USER_VAC_2 = "user_vac_2"
USER_SPD_1 = "user_spd_1"
USER_SPD_2 = "user_spd_2"
USER_ESCORT_NURSE_1 = "user_escort_nurse_1"
USER_ESCORT_NURSE_2 = "user_escort_nurse_2"

# ── Ready-made headers for the six opaque-identity roles ──────────────────────
CREDENTIALING_OFFICER = build_user_headers(
    USER_CREDENTIALING_1, ROLE_CREDENTIALING_OFFICER
)
CREDENTIALING_OFFICER_2 = build_user_headers(
    USER_CREDENTIALING_2, ROLE_CREDENTIALING_OFFICER
)
OR_COORDINATOR = build_user_headers(USER_ORC_1, ROLE_OR_COORDINATOR)
OR_COORDINATOR_2 = build_user_headers(USER_ORC_2, ROLE_OR_COORDINATOR)
COMPLIANCE_ADMIN = build_user_headers(USER_COMPLIANCE_1, ROLE_COMPLIANCE_ADMIN)
COMPLIANCE_ADMIN_2 = build_user_headers(USER_COMPLIANCE_2, ROLE_COMPLIANCE_ADMIN)
CLINICAL_SPONSOR = build_user_headers(USER_SPONSOR_1, ROLE_CLINICAL_SPONSOR)
CLINICAL_SPONSOR_2 = build_user_headers(USER_SPONSOR_2, ROLE_CLINICAL_SPONSOR)
VALUE_ANALYSIS_APPROVER = build_user_headers(USER_VAC_1, ROLE_VALUE_ANALYSIS_APPROVER)
VALUE_ANALYSIS_APPROVER_2 = build_user_headers(USER_VAC_2, ROLE_VALUE_ANALYSIS_APPROVER)
STERILE_PROCESSING_TECH = build_user_headers(USER_SPD_1, ROLE_STERILE_PROCESSING_TECH)
STERILE_PROCESSING_TECH_2 = build_user_headers(USER_SPD_2, ROLE_STERILE_PROCESSING_TECH)

# A ValueAnalysisApprover whose X-User-ID is the endorsing sponsor's identifier:
# the same human wearing the committee hat, which section 2.10 refuses.
VALUE_ANALYSIS_AS_SPONSOR_1 = build_user_headers(
    USER_SPONSOR_1, ROLE_VALUE_ANALYSIS_APPROVER
)

TEST_USERS: Dict[str, Dict[str, str]] = {
    "credentialing_officer": CREDENTIALING_OFFICER,
    "credentialing_officer_2": CREDENTIALING_OFFICER_2,
    "or_coordinator": OR_COORDINATOR,
    "or_coordinator_2": OR_COORDINATOR_2,
    "compliance_admin": COMPLIANCE_ADMIN,
    "compliance_admin_2": COMPLIANCE_ADMIN_2,
    "clinical_sponsor": CLINICAL_SPONSOR,
    "clinical_sponsor_2": CLINICAL_SPONSOR_2,
    "value_analysis_approver": VALUE_ANALYSIS_APPROVER,
    "value_analysis_approver_2": VALUE_ANALYSIS_APPROVER_2,
    "sterile_processing_tech": STERILE_PROCESSING_TECH,
    "sterile_processing_tech_2": STERILE_PROCESSING_TECH_2,
}

# Headers with no identity at all, for the authentication rung of section 2.9.
NO_IDENTITY_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}


def make_vendor_admin_headers(vendor_id: str) -> Dict[str, str]:
    """Headers for a VendorAdmin acting as the vendor whose ``id`` is ``vendor_id``."""
    return build_user_headers(vendor_id, ROLE_VENDOR_ADMIN)


def make_vendor_rep_headers(vendor_rep_id: str) -> Dict[str, str]:
    """Headers for a VendorRepUser acting as the representative ``vendor_rep_id``."""
    return build_user_headers(vendor_rep_id, ROLE_VENDOR_REP_USER)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary identifier and role pairing."""
    return build_user_headers(user_id, role)


def headers_for_every_role(
    vendor_id: str, vendor_rep_id: str
) -> Dict[str, Dict[str, str]]:
    """One header set per declared role, using the given entity-backed identities."""
    return {
        ROLE_CREDENTIALING_OFFICER: CREDENTIALING_OFFICER,
        ROLE_COMPLIANCE_ADMIN: COMPLIANCE_ADMIN,
        ROLE_OR_COORDINATOR: OR_COORDINATOR,
        ROLE_STERILE_PROCESSING_TECH: STERILE_PROCESSING_TECH,
        ROLE_CLINICAL_SPONSOR: CLINICAL_SPONSOR,
        ROLE_VALUE_ANALYSIS_APPROVER: VALUE_ANALYSIS_APPROVER,
        ROLE_VENDOR_ADMIN: make_vendor_admin_headers(vendor_id),
        ROLE_VENDOR_REP_USER: make_vendor_rep_headers(vendor_rep_id),
    }
