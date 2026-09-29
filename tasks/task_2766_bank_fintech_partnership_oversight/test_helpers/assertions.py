"""Entity shape assertions and the PRD's two conservation invariants."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AgreementStatus,
    AlertDisposition,
    AlertType,
    BusinessModel,
    CapabilityTier,
    ComplaintStatus,
    CustodyAccountStatus,
    CustodyAccountType,
    CycleStatus,
    DiligenceReviewStatus,
    FundingStatus,
    LedgerEntryType,
    MarketingReviewStatus,
    OversightPosture,
    PartnerStatus,
    ReconciliationStatus,
    WindDownPlanStatus,
)

_MEMBERS = lambda enum_cls: [m.value for m in enum_cls]


def assert_common_mutable_fields(data: dict):
    """Every mutable resource carries a UUID id, ISO 8601 stamps and a version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_partner(data: dict):
    assert_common_mutable_fields(data)
    assert data["status"] in _MEMBERS(PartnerStatus), data["status"]
    assert data["oversight_posture"] in _MEMBERS(OversightPosture), data["oversight_posture"]
    assert data["capability_tier"] in _MEMBERS(CapabilityTier), data["capability_tier"]
    assert data["business_model"] in _MEMBERS(BusinessModel), data["business_model"]
    assert isinstance(data["legal_name"], str) and 1 <= len(data["legal_name"]) <= 120
    assert isinstance(data["end_user_account_count"], int)
    assert data["end_user_account_count"] >= 0
    for cents_field in (
        "required_reserve_cents",
        "reserve_shortfall_cents",
        "cumulative_paid_out_cents",
        "cumulative_bank_fee_cents",
        "unreconciled_variance_cents",
    ):
        assert isinstance(data[cents_field], int), f"{cents_field} must be integer cents"
        assert data[cents_field] >= 0, f"{cents_field} must never be negative"
    assert isinstance(data["complaint_rate_bps"], int), "complaint_rate_bps is whole bps"
    assert data["consecutive_shortfall_cycles"] >= 0
    assert data["growth_breach_count"] >= 0
    assert data["open_sanctions_alert_count"] >= 0


def assert_diligence_review(data: dict):
    assert_common_mutable_fields(data)
    assert data["status"] in _MEMBERS(DiligenceReviewStatus), data["status"]
    assert data["tier"] in _MEMBERS(CapabilityTier), data["tier"]
    assert data["review_type"] in ("INITIAL", "RENEWAL"), data["review_type"]
    for score in (
        "business_model_score",
        "funding_score",
        "compliance_capability_score",
        "complaint_history_score",
    ):
        assert isinstance(data[score], int) and 0 <= data[score] <= 100, score
    assert isinstance(data["requested_info_items"], list)
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0


def assert_agreement(data: dict):
    assert_common_mutable_fields(data)
    assert data["status"] in _MEMBERS(AgreementStatus), data["status"]
    assert isinstance(data["termination_triggers"], list) and data["termination_triggers"]
    assert 1 <= data["audit_access_notice_days"] <= 30
    assert data["monthly_growth_cap_pct"] > 0
    assert 0 < data["concentration_cap_pct"] <= 100.00
    assert isinstance(data["max_end_user_balance_cents"], int)
    assert data["max_end_user_balance_cents"] > 0
    assert 1 <= data["reserve_requirement_bps"] <= 10000
    for owner_field in ("kyc_owner", "dispute_owner", "marketing_owner"):
        assert data[owner_field] in ("BANK", "PARTNER", "SHARED"), owner_field


def assert_custody_account(data: dict):
    assert_common_mutable_fields(data)
    assert data["account_type"] in _MEMBERS(CustodyAccountType), data["account_type"]
    assert data["status"] in _MEMBERS(CustodyAccountStatus), data["status"]
    assert isinstance(data["balance_cents"], int), "balance_cents must be integer cents"
    assert data["balance_cents"] >= 0, "no custody account may go negative"
    if data["status"] == CustodyAccountStatus.FROZEN.value:
        assert data["frozen_at"] is not None, "a FROZEN account carries frozen_at"
    else:
        assert data["frozen_at"] is None, "only a FROZEN account carries frozen_at"


def assert_marketing_review(data: dict):
    assert_common_mutable_fields(data)
    assert data["status"] in _MEMBERS(MarketingReviewStatus), data["status"]
    assert isinstance(data["risk_flags"], list)
    assert isinstance(data["disclosure_elements"], list)
    assert isinstance(data["change_requests"], list)
    assert isinstance(data["review_round"], int) and data["review_round"] >= 1
    assert isinstance(data["apr_disclosed"], bool)
    assert isinstance(data["fdic_signage_correct"], bool)
    assert_risk_flag_order(data["risk_flags"])


def assert_risk_flag_order(risk_flags):
    """risk_flags are always emitted in the fixed declaration order."""
    declared = ["MISSING_APR", "MISSING_FDIC_SIGNAGE", "MISSING_DISPUTE_RIGHTS"]
    positions = [declared.index(flag) for flag in risk_flags]
    assert positions == sorted(positions), (
        f"risk_flags must follow the declaration order {declared}, got {risk_flags}"
    )


def assert_settlement_batch(data: dict):
    assert_common_mutable_fields(data)
    assert data["reconciliation_status"] in _MEMBERS(ReconciliationStatus)
    assert data["funding_status"] in _MEMBERS(FundingStatus)
    for cents_field in (
        "gross_settlement_cents",
        "interchange_cents",
        "returns_cents",
        "bank_fee_cents",
        "reserve_funding_cents",
        "net_to_partner_cents",
        "shortfall_carry_cents",
    ):
        assert isinstance(data[cents_field], int), f"{cents_field} must be integer cents"
        assert data[cents_field] >= 0, f"{cents_field} must never be negative"
    assert isinstance(data["partner_reported_net_cents"], int)
    assert isinstance(data["variance_cents"], int)
    assert isinstance(data["variance_adjustment_cents"], int)


def assert_ledger_entry(data: dict):
    """A ledger entry is immutable, so it carries neither updated_at nor version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "a ledger entry carries no updated_at"
    assert "version" not in data, "a ledger entry carries no version"
    assert data["entry_type"] in _MEMBERS(LedgerEntryType), data["entry_type"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] != 0
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1


def assert_ledger_sign_discipline(data: dict):
    """The sign of amount_cents is fixed by the movement classification."""
    positive_types = {"END_USER_CREDIT", "RESERVE_FUND", "CLAWBACK"}
    negative_types = {"END_USER_DEBIT", "RESERVE_RELEASE", "FEE"}
    entry_type = data["entry_type"]
    if entry_type in positive_types:
        assert data["amount_cents"] > 0, f"{entry_type} must carry a positive amount_cents"
    elif entry_type in negative_types:
        assert data["amount_cents"] < 0, f"{entry_type} must carry a negative amount_cents"
    assert data["amount_cents"] != 0, "amount_cents may never be zero"


def assert_complaint(data: dict):
    assert_common_mutable_fields(data)
    assert data["status"] in _MEMBERS(ComplaintStatus), data["status"]
    assert data["handling_owner"] in ("BANK", "PARTNER", "SHARED"), data["handling_owner"]
    assert is_iso8601_timestamp(data["response_due_at"]), "response_due_at must be ISO 8601"
    assert isinstance(data["escalation_count"], int) and data["escalation_count"] >= 0
    assert isinstance(data["redress_cents"], int) and data["redress_cents"] >= 0
    assert isinstance(data["is_reg_e_dispute"], bool)


def assert_alert(data: dict):
    assert_common_mutable_fields(data)
    assert data["alert_type"] in _MEMBERS(AlertType), data["alert_type"]
    assert data["disposition"] in _MEMBERS(AlertDisposition), data["disposition"]
    assert is_iso8601_timestamp(data["sla_due_at"]), "sla_due_at must be ISO 8601"
    assert isinstance(data["sla_breach_count"], int) and data["sla_breach_count"] >= 0
    assert data["transaction_volume_cents"] > 0


def assert_cycle(data: dict):
    assert_common_mutable_fields(data)
    assert data["status"] in _MEMBERS(CycleStatus), data["status"]
    assert isinstance(data["cycle_index"], int) and data["cycle_index"] >= 1
    for counter in (
        "partners_frozen_count",
        "marketing_approvals_expired_count",
        "complaints_escalated_count",
        "alerts_reopened_count",
        "growth_breach_partner_count",
        "plans_completed_count",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, counter


def assert_wind_down_plan(data: dict):
    assert_common_mutable_fields(data)
    assert data["status"] in _MEMBERS(WindDownPlanStatus), data["status"]
    assert isinstance(data["milestones"], list) and data["milestones"]
    assert "RETURN_FUNDS" in data["milestones"], "a plan must return the money"
    assert "CLOSE_CUSTODY" in data["milestones"], "a plan must shut the accounts"
    assert 1 <= data["notice_days"] <= 180
    assert isinstance(data["residual_balance_cents"], int)
    assert data["residual_balance_cents"] >= 0


# --- the two conservation invariants -----------------------------------

def conserved_settlement_cents(partner: dict, fbo_account: dict, reserve_account: dict) -> int:
    """FBO balance + RESERVE balance + cumulative payout + cumulative fee."""
    return (
        fbo_account["balance_cents"]
        + reserve_account["balance_cents"]
        + partner["cumulative_paid_out_cents"]
        + partner["cumulative_bank_fee_cents"]
    )


def assert_complaint_bucket_partition(partner: dict, expected_total: int = None):
    """The four complaint buckets partition the partner's complaints exactly."""
    bucket_sum = (
        partner["open_complaint_count"]
        + partner["escalated_complaint_count"]
        + partner["resolved_complaint_count"]
        + partner["withdrawn_complaint_count"]
    )
    assert bucket_sum == partner["total_complaint_count"], (
        f"buckets sum to {bucket_sum} but total_complaint_count is "
        f"{partner['total_complaint_count']}"
    )
    if expected_total is not None:
        assert partner["total_complaint_count"] == expected_total, (
            f"expected {expected_total} complaint rows, got "
            f"{partner['total_complaint_count']}"
        )


def assert_two_decimal_percentage(value, label="percentage"):
    """A two-decimal percentage must round-trip through two decimal places."""
    assert isinstance(value, (int, float)), f"{label} must be numeric, got {value!r}"
    assert round(float(value), 2) == float(value), (
        f"{label} must carry at most two decimal places, got {value!r}"
    )


def assert_one_decimal_score(value, label="composite_score"):
    assert isinstance(value, (int, float)), f"{label} must be numeric, got {value!r}"
    assert round(float(value), 1) == float(value), (
        f"{label} must carry at most one decimal place, got {value!r}"
    )


def parse_instant(value):
    """Parse an ISO-8601 UTC instant, tolerating either a Z suffix or +00:00."""
    from datetime import datetime

    assert isinstance(value, str), f"expected an ISO-8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def assert_same_instant(actual, expected, label="timestamp"):
    """Compare two ISO-8601 instants by value, not by textual width."""
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label} should be {expected}, got {actual}"
    )
