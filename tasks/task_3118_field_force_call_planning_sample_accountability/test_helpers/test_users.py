"""Pre-built role headers for the five roles named in PRD section 2.1.

Per PRD section 2.1:

- ``DistrictManager`` and ``FieldRep`` are entity-backed: ``X-User-ID`` is the
  ``id`` of the acting ``Representative`` row.  Tests that exercise an
  ownership gate MUST use ``make_field_rep_headers(rep["id"])`` or
  ``make_district_manager_headers(rep["id"])`` with the actual representative
  id — falling back to the shared constant would make every ownership check
  reject.
- ``PlatformAdmin``, ``ComplianceOfficer`` and ``QualityAssurance`` are
  opaque: the shared constant is the canonical form.  Note that the
  destruction-confirmation segregation rule compares the ComplianceOfficer's
  ``X-User-ID`` against the returning rep's id, so a distinct opaque id must
  be used for any self-confirm probe.
"""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for calls whose outcome does
# not depend on the caller owning the subject resource.
ADMIN_HEADERS = build_user_headers("ops-admin-0001", "PlatformAdmin")
COMPLIANCE_HEADERS = build_user_headers("compliance-0001", "ComplianceOfficer")
QA_HEADERS = build_user_headers("qa-0001", "QualityAssurance")

# Fallback constants for entity-backed roles — only for tests that do not
# exercise an ownership gate.
DISTRICT_MANAGER_HEADERS = build_user_headers("dm-fallback-0001", "DistrictManager")
FIELD_REP_HEADERS = build_user_headers("rep-fallback-0001", "FieldRep")

TEST_USERS = {
    "admin_headers": ADMIN_HEADERS,
    "compliance_headers": COMPLIANCE_HEADERS,
    "qa_headers": QA_HEADERS,
    "district_manager_headers": DISTRICT_MANAGER_HEADERS,
    "field_rep_headers": FIELD_REP_HEADERS,
}


def make_field_rep_headers(rep_id: str) -> dict:
    """FieldRep is entity-backed: pass the acting Representative's id."""
    return build_user_headers(rep_id, "FieldRep")


def make_district_manager_headers(rep_id: str) -> dict:
    """DistrictManager is entity-backed: pass the acting Representative's id."""
    return build_user_headers(rep_id, "DistrictManager")


def make_admin_headers(user_id: str = "ops-admin-0001") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_compliance_headers(user_id: str = "compliance-0001") -> dict:
    """ComplianceOfficer is opaque, but its id participates in the
    self-confirm segregation comparison — a probe for that rule must pass the
    returning rep's id here."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_qa_headers(user_id: str = "qa-0001") -> dict:
    return build_user_headers(user_id, "QualityAssurance")
