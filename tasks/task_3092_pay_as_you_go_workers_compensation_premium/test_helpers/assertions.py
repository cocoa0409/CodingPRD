"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be a positive integer, got {data.get('version')!r}"


def assert_employer(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["fein"], str) and data["fein"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert isinstance(data["home_state"], str) and data["home_state"]
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_state_rating_table(data: dict):
    _assert_common(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["monopolistic"], bool)
    assert data["ot_basis"] in ("GROSS", "NET")
    assert isinstance(data["class_rates"], list) and len(data["class_rates"]) > 0
    for rate in data["class_rates"]:
        assert isinstance(rate["class_code"], str)
        assert isinstance(rate["rate_per_100_cents"], int)
    for field in ("per_capita_admin_fee_cents", "expense_constant_cents",
                  "min_payroll_threshold_cents", "state_minimum_premium_cents",
                  "max_payroll_per_executive_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"


def assert_policy(data: dict):
    _assert_common(data)
    assert isinstance(data["employer_id"], str) and data["employer_id"]
    assert isinstance(data["policy_number"], str) and data["policy_number"]
    assert data["coverage_status"] in ("PENDING", "ACTIVE", "CANCELLED", "EXPIRED")
    assert data["reporting_status"] in ("COMPLIANT", "GRACE", "DELINQUENT",
                                        "NON_REPORTING")
    assert data["billing_status"] in ("CURRENT", "OVERDUE", "SUSPENDED")
    assert isinstance(data["consecutive_missed_cycles"], int)
    assert isinstance(data["cumulative_billed_cents"], int)
    assert isinstance(data["cumulative_collected_cents"], int)


def assert_policy_class_code(data: dict):
    _assert_common(data)
    assert isinstance(data["policy_id"], str) and data["policy_id"]
    assert isinstance(data["state_code"], str)
    assert isinstance(data["class_code"], str)
    assert isinstance(data["estimated_annual_payroll_cents"], int)
    assert data["assignment_status"] in ("ACTIVE", "DISPUTED", "REASSIGNED")


def assert_payroll_integration(data: dict):
    _assert_common(data)
    assert isinstance(data["policy_id"], str) and data["policy_id"]
    assert data["connection_status"] in ("CONNECTED", "DEGRADED", "BROKEN")


def assert_payroll_report(data: dict):
    _assert_common(data)
    assert isinstance(data["policy_id"], str) and data["policy_id"]
    assert data["status"] in ("SUBMITTED", "ACCEPTED", "REJECTED", "SUPERSEDED")
    assert isinstance(data["idempotency_key"], str) and data["idempotency_key"]
    if data["status"] == "REJECTED":
        assert isinstance(data["failure_code"], str) and data["failure_code"], \
            "a REJECTED report carries the error identifier of the failed check"
    else:
        assert data.get("failure_code") is None, \
            "a report with no failure carries a null failure_code"


def assert_payroll_line(data: dict):
    _assert_common(data)
    assert isinstance(data["payroll_report_id"], str) and data["payroll_report_id"]
    assert isinstance(data["state_code"], str)
    assert isinstance(data["class_code"], str)
    for field in ("gross_wages_cents", "ot_premium_cents", "severance_cents",
                  "executive_wages_cents", "headcount", "remuneration_basis_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_premium_invoice(data: dict):
    _assert_common(data)
    assert isinstance(data["policy_id"], str) and data["policy_id"]
    assert data["kind"] in ("PAYROLL", "RETRO_ADJUSTMENT", "AUDIT_TRUEUP",
                            "MINIMUM_PREMIUM")
    assert data["status"] in ("DRAFT", "ISSUED", "PAID", "VOID")
    for field in ("manual_premium_cents", "premium_after_mod_cents",
                  "per_capita_fees_cents", "expense_constant_cents", "total_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"


def assert_class_code_dispute(data: dict):
    _assert_common(data)
    assert isinstance(data["policy_id"], str) and data["policy_id"]
    assert isinstance(data["policy_class_code_id"], str)
    assert isinstance(data["requested_class_code"], str)
    assert data["status"] in ("FILED", "UNDER_REVIEW", "APPROVED", "DENIED")
    assert isinstance(data["filed_by"], str) and data["filed_by"]


def assert_audit_reconciliation(data: dict):
    _assert_common(data)
    assert isinstance(data["policy_id"], str) and data["policy_id"]
    assert data["status"] in ("OPEN", "FILED", "VERIFIED", "CLOSED", "WAIVED")


def assert_tax_filing_record(data: dict):
    _assert_common(data)
    assert isinstance(data["policy_id"], str) and data["policy_id"]
    assert isinstance(data["state_code"], str)
    assert isinstance(data["quarter"], str) and data["quarter"]
    assert isinstance(data["reported_wages_cents"], int)
    assert data["source"] in ("SUI", "IRS_941", "MANUAL")


def assert_policy_aggregates_invariants(policy: dict):
    """Fiscal aggregate invariants that must hold after any operation."""
    assert policy["cumulative_billed_cents"] >= 0
    assert policy["cumulative_collected_cents"] >= 0
    assert policy["cumulative_collected_cents"] <= policy["cumulative_billed_cents"], (
        "collected (PAID invoices) can never exceed billed (ISSUED + PAID invoices)")
