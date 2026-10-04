"""Entity assertions and domain invariant checkers."""
import requests

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _require(data: dict) -> dict:
    assert isinstance(data, dict), f"expected a response object, got {type(data).__name__}"
    return data


def assert_common_fields(data: dict):
    """id / created_at / updated_at / version are present on every persisted resource."""
    data = _require(data)
    assert is_valid_uuid(str(data.get("id", ""))), f"id must be a UUID string, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601 with milliseconds, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601 with milliseconds, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be an integer >= 1, got {data.get('version')!r}"


def assert_member(data: dict):
    data = _require(data)
    assert_common_fields(data)
    assert isinstance(data["member_number"], str) and data["member_number"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["member_status"] in ("PROSPECT", "MEMBER_ACTIVE", "MEMBER_AT_RISK", "MEMBER_LAPSED")
    assert data["member_tier"] in ("NONE", "BASE", "PLUS", "PREMIER")
    assert data["benefit_entitlement_state"] in ("NONE", "FULL", "PARTIAL", "SUSPENDED")
    assert data["member_since_at"] is None or is_iso8601_timestamp(data["member_since_at"])
    assert data["last_qualifying_deposit_at"] is None or is_iso8601_timestamp(data["last_qualifying_deposit_at"])
    assert isinstance(data["product_adoption_count"], int) and data["product_adoption_count"] >= 0
    assert isinstance(data["product_line_set"], list)
    assert isinstance(data["qualifying_deposit_balance_cents"], int)
    assert isinstance(data["rewards_points_balance"], int) and data["rewards_points_balance"] >= 0
    assert isinstance(data["churn_risk_score"], int) and 0 <= data["churn_risk_score"] <= 100


def assert_holding(data: dict):
    data = _require(data)
    assert_common_fields(data)
    assert data["product_line"] in ("LENDING", "BANKING", "INVESTING", "CAREER")
    assert data["adoption_status"] in ("PENDING", "ADOPTED", "SUSPENDED", "CLOSED")
    assert isinstance(data["balance_cents"], int)
    for flag in ("deposit_rate_eligible", "cross_sell_eligible", "reunderwriting_permitted"):
        assert isinstance(data[flag], bool), f"{flag} must be a boolean"


def assert_loan_account(data: dict):
    data = _require(data)
    assert_common_fields(data)
    assert data["loan_type"] in ("PERSONAL", "STUDENT", "AUTO", "REFINANCE")
    assert data["autopay_status"] in ("NOT_ENROLLED", "ENROLLED", "SUSPENDED")
    assert data["pricing_status"] in ("PROVISIONAL", "FINAL", "STEPPED_DOWN")
    assert isinstance(data["principal_cents"], int)
    assert isinstance(data["base_apr_bps"], int)
    assert isinstance(data["discount_stack_bps"], int) and data["discount_stack_bps"] >= 0
    assert isinstance(data["effective_apr_bps"], int)
    assert is_iso8601_timestamp(data["last_priced_at"])


def assert_deposit_enrollment(data: dict):
    data = _require(data)
    assert_common_fields(data)
    assert data["status"] in ("PENDING_VERIFICATION", "ACTIVE", "GRACE", "LAPSED")
    assert isinstance(data["required_monthly_amount_cents"], int)
    assert isinstance(data["consecutive_qualifying_months"], int) and data["consecutive_qualifying_months"] >= 0
    assert isinstance(data["missed_cycle_count"], int) and data["missed_cycle_count"] >= 0
    for field in ("qualified_at", "last_deposit_at", "requalification_due_at", "grace_deadline_at"):
        assert data[field] is None or is_iso8601_timestamp(data[field]), \
            f"{field} must be null or ISO 8601, got {data[field]!r}"


def assert_entitlement(data: dict):
    data = _require(data)
    assert_common_fields(data)
    assert data["benefit_code"] in (
        "LOAN_RATE_DISCOUNT", "DIRECT_DEPOSIT", "CAREER_COACHING_CREDIT",
        "INVESTING_FEE_WAIVER", "REWARDS_MULTIPLIER",
    )
    assert data["entitlement_status"] in (
        "PENDING", "GRANTED", "PENDING_REQUALIFICATION", "STEPPED_DOWN", "REVOKED",
    )
    assert data["reconciliation_state"] in ("IN_SYNC", "DRIFT_REPORTED", "RECONCILED")
    assert isinstance(data["value_bps"], int)
    assert data["granted_at"] is None or is_iso8601_timestamp(data["granted_at"])
    assert data["stepped_down_at"] is None or is_iso8601_timestamp(data["stepped_down_at"])


def assert_rule(data: dict):
    data = _require(data)
    assert_common_fields(data)
    assert isinstance(data["rule_code"], str) and data["rule_code"]
    assert data["discount_kind"] in (
        "MEMBER_TIER", "DIRECT_DEPOSIT", "AUTOPAY", "PROMOTIONAL", "CAREER_SERVICES",
    )
    assert data["stacking_class"] in ("BASE", "ADDITIVE", "CAP_CONTRIBUTING")
    assert isinstance(data["discount_bps"], int)
    assert data["status"] in ("DRAFT", "ACTIVE", "RETIRED")
    assert data["min_member_tier"] in ("NONE", "BASE", "PLUS", "PREMIER")
    assert isinstance(data["requires_direct_deposit"], bool)
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_to"])


def assert_application(data: dict):
    data = _require(data)
    assert_common_fields(data)
    assert isinstance(data["applied_bps"], int)
    assert data["application_state"] in ("APPLIED", "PREEMPTED", "ROLLED_BACK")
    assert is_iso8601_timestamp(data["applied_at"])
    assert is_iso8601_timestamp(data["window_from"])
    assert is_iso8601_timestamp(data["window_to"])
    if data["application_state"] == "PREEMPTED":
        assert data["preempted_by_application_id"] is not None, \
            "a PREEMPTED application must name the application that displaced it"
    else:
        assert data["preempted_by_application_id"] is None


def assert_ledger_entry(data: dict):
    data = _require(data)
    assert_common_fields(data)
    assert data["entry_type"] in ("EARN", "REDEEM_PRINCIPAL", "REVERSE", "ADJUST")
    assert isinstance(data["points_delta"], int)
    assert isinstance(data["principal_reduction_cents"], int)
    assert data["entry_status"] in ("POSTED", "REVERSED")


def assert_requalification_cycle(data: dict):
    data = _require(data)
    assert_common_fields(data)
    assert isinstance(data["cycle_index"], int) and data["cycle_index"] >= 1
    assert data["status"] in ("OPEN", "PASSED", "FAILED", "REMEDIATION", "CLOSED")
    assert is_iso8601_timestamp(data["opened_at"])
    assert is_iso8601_timestamp(data["due_at"])
    assert data["evaluated_at"] is None or is_iso8601_timestamp(data["evaluated_at"])
    assert isinstance(data["qualifying_month_count"], int)
    assert isinstance(data["qualifying_deposit_total_cents"], int)


def assert_churn_notice(data: dict):
    data = _require(data)
    assert_common_fields(data)
    assert data["notice_type"] in (
        "RATE_STEP_DOWN", "RATE_STEP_UP", "REQUALIFICATION_REMINDER", "BENEFIT_REVOCATION",
    )
    assert data["status"] in ("QUEUED", "SENT", "ACKNOWLEDGED", "VOIDED")
    assert is_iso8601_timestamp(data["issued_at"])
    assert is_iso8601_timestamp(data["effective_at"])


def assert_coaching_session(data: dict):
    data = _require(data)
    assert_common_fields(data)
    assert data["session_kind"] in ("CAREER_COACHING", "MEMBER_EVENT")
    assert data["status"] in ("SCHEDULED", "CONFIRMED", "COMPLETED", "CANCELLED")
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert isinstance(data["capacity_total"], int) and data["capacity_total"] >= 1
    assert isinstance(data["seats_reserved"], int)


def assert_cross_sell_check(data: dict):
    data = _require(data)
    assert_common_fields(data)
    assert data["target_product_line"] in ("LENDING", "BANKING", "INVESTING", "CAREER")
    assert data["status"] in ("PENDING", "CLEARED", "BLOCKED", "REUSE_PROHIBITED")
    assert isinstance(data["consent_recorded"], bool)
    assert isinstance(data["underwriting_reuse_permitted"], bool)
    assert isinstance(data["conditioning_blocked"], bool)


# --- Domain invariants ----------------------------------------------------

def assert_member_invariants(data: dict):
    """Rollups that must agree after any operation on the member."""
    data = _require(data)
    assert data["churn_risk_score"] >= 0
    assert data["churn_risk_score"] <= 100
    assert data["rewards_points_balance"] >= 0
    assert data["qualifying_deposit_balance_cents"] >= 0
    assert data["product_adoption_count"] >= 0


def assert_loan_pricing_invariants(data: dict):
    """The stack is capped and the effective rate never pierces the floor."""
    from .constants import APR_FLOOR_BPS, STACK_CAP_BPS
    data = _require(data)
    assert data["discount_stack_bps"] <= STACK_CAP_BPS, \
        f"stored stack {data['discount_stack_bps']} exceeds the {STACK_CAP_BPS} bps ceiling"
    assert data["effective_apr_bps"] >= APR_FLOOR_BPS, \
        f"effective APR {data['effective_apr_bps']} is below the {APR_FLOOR_BPS} bps floor"


def assert_points_balance_matches_ledger(api, member_id, headers):
    """The member's posted balance equals the sum of posted entry deltas."""
    resp = api.list_ledger_entries(headers, params={"member_id": member_id, "limit": 100})
    body = resp.json()
    rows = body["data"]
    posted = [row for row in rows if row.get("entry_status") == "POSTED"]
    expected = sum(row["points_delta"] for row in posted)
    member = api.get_member(member_id, headers).json()["data"]
    assert member["rewards_points_balance"] == expected, (
        f"member balance {member['rewards_points_balance']} does not match the "
        f"sum of posted deltas {expected}"
    )


def assert_status(response: requests.Response, expected: int):
    assert response.status_code == expected, (
        f"expected HTTP {expected}, got {response.status_code}: {response.text[:400]}"
    )


def assert_status_is_one_of(response: requests.Response, expected: tuple):
    assert response.status_code in expected, (
        f"expected one of HTTP {expected}, got {response.status_code}: {response.text[:400]}"
    )


__all__ = [name for name in dir() if name.startswith("assert_")]