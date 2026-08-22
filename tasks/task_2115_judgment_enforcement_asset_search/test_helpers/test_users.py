"""Pre-built role headers for every role in the PRD.

Four roles are firm staff whose identities are opaque operator identifiers not
tied to any persisted entity: CaseManager, AssetInvestigator, EnforcementOfficer
and ComplianceOfficer.  The remaining two, Creditor and Debtor, are entity-backed
portal users whose X-User-ID must equal the id of the acting Creditor / Debtor row,
so ownership-gated calls MUST use the per-instance builders below.
"""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants.  Safe for the four opaque staff roles; the Creditor and
# Debtor entries are only usable where the call does not exercise ownership.
TEST_USERS = {
    "case_manager_headers": build_user_headers("cm-1", "CaseManager"),
    "asset_investigator_headers": build_user_headers("inv-1", "AssetInvestigator"),
    "enforcement_officer_headers": build_user_headers("eo-1", "EnforcementOfficer"),
    "compliance_officer_headers": build_user_headers("co-1", "ComplianceOfficer"),
    "creditor_headers": build_user_headers("test-creditor-1", "Creditor"),
    "debtor_headers": build_user_headers("test-debtor-1", "Debtor"),
}


# --- opaque staff roles: any identifier works, but tests often need a named one
def make_case_manager_headers(user_id: str = "cm-1") -> dict:
    return build_user_headers(user_id, "CaseManager")


def make_asset_investigator_headers(user_id: str = "inv-1") -> dict:
    """The identifier stamped onto verified_by_user_id when a finding is verified."""
    return build_user_headers(user_id, "AssetInvestigator")


def make_enforcement_officer_headers(user_id: str = "eo-1") -> dict:
    """The identifier stamped onto writ_requested_by_user_id and opposed_by_user_id."""
    return build_user_headers(user_id, "EnforcementOfficer")


def make_compliance_officer_headers(user_id: str = "co-1") -> dict:
    """The identifier stamped onto ruled_by_user_id when a claim is decided."""
    return build_user_headers(user_id, "ComplianceOfficer")


# --- entity-backed portal roles: pass the real row id
def make_creditor_headers(creditor_id: str) -> dict:
    """For Creditor callers.  Pass the acting Creditor row's id."""
    return build_user_headers(creditor_id, "Creditor")


def make_debtor_headers(debtor_id: str) -> dict:
    """For Debtor callers.  Pass the acting Debtor row's id."""
    return build_user_headers(debtor_id, "Debtor")
