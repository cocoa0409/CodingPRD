"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ExceptionStatus,
    ExceptionType,
    FindingFieldName,
    FindingSeverity,
    ForeclosureMode,
    LoanStatus,
    MatchStatus,
    MemberStatus,
    MemberType,
    OrgIdType,
    ReportStatus,
    ReviewStatus,
    RoleScope,
    SanctionStatus,
    RunStatus,
    SignerStatus,
    StandingBand,
    TransferStatus,
    TransferType,
)


def _assert_common_spine(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}: id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}: created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}: updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}: version must be a positive integer, got {data.get('version')!r}"
    )


def assert_member(data: dict):
    _assert_common_spine(data, "Member")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["org_id"], str) and len(data["org_id"]) == 7 and data["org_id"].isdigit()
    assert data["org_id_type"] in {e.value for e in OrgIdType}
    assert data["member_type"] in {e.value for e in MemberType}
    assert data["status"] in {e.value for e in MemberStatus}
    assert "termination_effective_date" in data


def assert_signer(data: dict):
    _assert_common_spine(data, "AuthorizedSigner")
    assert isinstance(data["member_id"], str) and data["member_id"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert is_iso8601_timestamp(data["effective_from"])
    assert "effective_until" in data
    if data["effective_until"] is not None:
        assert is_iso8601_timestamp(data["effective_until"])
    assert data["role_scope"] in {e.value for e in RoleScope}
    assert data["status"] in {e.value for e in SignerStatus}


def assert_loan(data: dict):
    _assert_common_spine(data, "RegisteredLoan")
    assert isinstance(data["min"], str) and len(data["min"]) == 18 and data["min"].isdigit()
    assert isinstance(data["serial"], int) and data["serial"] >= 1
    assert isinstance(data["registering_member_id"], str) and data["registering_member_id"]
    assert isinstance(data["loan_amount_cents"], int) and data["loan_amount_cents"] > 0
    assert isinstance(data["property_state"], str) and len(data["property_state"]) == 2
    assert is_iso8601_timestamp(data["closing_date"])
    assert data["foreclosure_mode"] in {e.value for e in ForeclosureMode}
    assert isinstance(data["current_investor_id"], str) and data["current_investor_id"]
    assert isinstance(data["current_servicer_id"], str) and data["current_servicer_id"]
    assert data["status"] in {e.value for e in LoanStatus}
    assert "assigned_out_at" in data


def assert_transfer(data: dict):
    _assert_common_spine(data, "Transfer")
    assert isinstance(data["loan_id"], str) and data["loan_id"]
    assert isinstance(data["from_member_id"], str) and data["from_member_id"]
    assert isinstance(data["to_member_id"], str) and data["to_member_id"]
    assert data["transfer_type"] in {e.value for e in TransferType}
    assert is_iso8601_timestamp(data["effective_date"])
    assert isinstance(data["idempotency_key"], str) and data["idempotency_key"]
    assert isinstance(data["days_late"], int) and data["days_late"] >= 0
    assert isinstance(data["late_fee_cents"], int) and data["late_fee_cents"] >= 0
    assert data["status"] in {e.value for e in TransferStatus}


def assert_transfer_match(data: dict):
    _assert_common_spine(data, "TransferMatch")
    assert isinstance(data["transfer_id"], str) and data["transfer_id"]
    assert isinstance(data["reported_by_member_id"], str) and data["reported_by_member_id"]
    assert is_iso8601_timestamp(data["reported_at"])
    assert data["status"] in {e.value for e in MatchStatus}


def assert_qa_review(data: dict):
    _assert_common_spine(data, "QAReview")
    assert isinstance(data["member_id"], str) and data["member_id"]
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert data["status"] in {e.value for e in ReviewStatus}
    assert isinstance(data["created_by"], str) and data["created_by"]


def assert_qa_finding(data: dict):
    _assert_common_spine(data, "QAFinding")
    assert isinstance(data["review_id"], str) and data["review_id"]
    assert isinstance(data["loan_id"], str) and data["loan_id"]
    assert data["field_name"] in {e.value for e in FindingFieldName}
    assert data["severity"] in {e.value for e in FindingSeverity}


def assert_annual_report(data: dict):
    _assert_common_spine(data, "AnnualReport")
    assert isinstance(data["member_id"], str) and data["member_id"]
    assert isinstance(data["report_year"], int)
    assert isinstance(data["reporting_rate"], (int, float))
    assert isinstance(data["reporting_rate_amount_weighted"], (int, float))
    assert isinstance(data["discrepancy_rate"], (int, float))
    assert isinstance(data["open_exceptions"], int) and data["open_exceptions"] >= 0
    assert isinstance(data["standing_score"], (int, float))
    assert data["standing_band"] in {e.value for e in StandingBand}
    assert data["status"] in {e.value for e in ReportStatus}


def assert_sanction(data: dict):
    _assert_common_spine(data, "Sanction")
    assert isinstance(data["member_id"], str) and data["member_id"]
    assert isinstance(data["review_id"], str) and data["review_id"]
    assert isinstance(data["total_amount_cents"], int) and data["total_amount_cents"] >= 0
    assert isinstance(data["line_count"], int) and data["line_count"] >= 0
    assert data["status"] in {e.value for e in SanctionStatus}


def assert_sor_run(data: dict):
    _assert_common_spine(data, "SORReconciliationRun")
    assert isinstance(data["member_id"], str) and data["member_id"]
    for f in ("total_records", "matched_count", "registry_only_count",
              "platform_only_count", "field_mismatch_count"):
        assert isinstance(data[f], int) and data[f] >= 0, f"run field {f}"
    assert isinstance(data["match_rate"], (int, float))
    assert data["status"] in {e.value for e in RunStatus}


def assert_sor_exception(data: dict):
    _assert_common_spine(data, "SORException")
    assert isinstance(data["run_id"], str) and data["run_id"]
    assert "loan_id" in data
    assert data["exception_type"] in {e.value for e in ExceptionType}
    assert isinstance(data["detail"], str)
    assert data["status"] in {e.value for e in ExceptionStatus}


def assert_loan_rights_conserved(loan: dict):
    """A loan always has exactly one current investor and one current servicer."""
    assert loan.get("current_investor_id"), "loan must name exactly one current investor"
    assert loan.get("current_servicer_id"), "loan must name exactly one current servicer"
