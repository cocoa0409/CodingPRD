"""Pre-built role headers for every role in the PRD (§2.1).

CarrierRep and ShipperRep are entity-backed: their X-User-ID must equal the
id of the CarrierOrganization / ShipperAccount they act for. Use the
per-instance builders below for any ownership-gated call. The opaque roles
compare X-User-ID only where a workflow assigns responsibility
(ombuds officer, presiding judge), so those also get per-id builders.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are canonical for non-ownership calls.
    "admin_headers": build_user_headers("admin-1", "CommissionAdmin"),
    "docket_headers": build_user_headers("docket-1", "CommissionDocket"),
    "reviewer_headers": build_user_headers("reviewer-1", "ComplianceReviewer"),
    "ombuds_headers": build_user_headers("om-default", "OmbudsOfficer"),
    "alj_headers": build_user_headers("alj-1", "AdministrativeLawJudge"),
    "counsel_headers": build_user_headers("ec-1", "EnforcementCounsel"),
    # Entity-backed roles — fallback ONLY for tests that never touch
    # ownership-gated resources (bad-payload / not-found probes).
    "carrier_rep_headers": build_user_headers("test-carrier-1", "CarrierRep"),
    "shipper_rep_headers": build_user_headers("test-shipper-1", "ShipperRep"),
}


def make_carrier_rep_headers(carrier_id: str) -> dict:
    """CarrierRep is entity-backed: pass the acting CarrierOrganization's id."""
    return build_user_headers(carrier_id, "CarrierRep")


def make_shipper_rep_headers(shipper_id: str) -> dict:
    """ShipperRep is entity-backed: pass the acting ShipperAccount's id."""
    return build_user_headers(shipper_id, "ShipperRep")


def make_ombuds_officer_headers(officer_id: str) -> dict:
    """OmbudsOfficer is opaque, but close-ombuds requires X-User-ID to equal
    the complaint's assigned ombuds_officer_id."""
    return build_user_headers(officer_id, "OmbudsOfficer")


def make_alj_headers(judge_id: str) -> dict:
    """AdministrativeLawJudge is opaque; decide requires the presiding judge."""
    return build_user_headers(judge_id, "AdministrativeLawJudge")


def make_counsel_headers(counsel_id: str) -> dict:
    """EnforcementCounsel is opaque."""
    return build_user_headers(counsel_id, "EnforcementCounsel")
