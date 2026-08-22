"""Pre-built role headers for every role in the PRD.

Five roles carry an opaque identity: X-User-ID is an operator identifier that
is never compared to any record's id. The sixth, SubcontractorAdmin, is backed
by a Subcontractor record — its X-User-ID must be the acting Subcontractor's
own id, so ownership-gated calls MUST use
make_subcontractor_admin_headers(subcontractor["id"]).

Because three operations enforce segregation of duties on the acting
X-User-ID, the opaque builders accept a user id so a test can act as two
distinct people holding the same role.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "station_manager_headers": build_user_headers("sm-01", "StationManager"),
    "duty_officer_headers": build_user_headers("duty-01", "DutyOfficer"),
    "safety_officer_headers": build_user_headers("safety-01", "SafetyOfficer"),
    "billing_controller_headers": build_user_headers("bc-01", "BillingController"),
    "contract_auditor_headers": build_user_headers("ca-01", "ContractAuditor"),
    # Entity-backed role: this shared constant is a fallback for tests that do
    # not exercise ownership (it never equals a real Subcontractor id).
    "subcontractor_admin_headers": build_user_headers(
        "test-subcontractor-1", "SubcontractorAdmin"),
}


def make_station_manager_headers(user_id: str = "sm-01") -> dict:
    return build_user_headers(user_id, "StationManager")


def make_duty_officer_headers(user_id: str = "duty-01") -> dict:
    return build_user_headers(user_id, "DutyOfficer")


def make_safety_officer_headers(user_id: str = "safety-01") -> dict:
    return build_user_headers(user_id, "SafetyOfficer")


def make_billing_controller_headers(user_id: str = "bc-01") -> dict:
    return build_user_headers(user_id, "BillingController")


def make_contract_auditor_headers(user_id: str = "ca-01") -> dict:
    return build_user_headers(user_id, "ContractAuditor")


def make_subcontractor_admin_headers(user_id: str) -> dict:
    """For SubcontractorAdmin, whose X-User-ID is the acting Subcontractor's id.
    Pass the actual Subcontractor.id on every ownership-gated call."""
    return build_user_headers(user_id, "SubcontractorAdmin")
