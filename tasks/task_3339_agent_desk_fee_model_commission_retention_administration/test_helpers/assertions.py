"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    AgentStatus, CdaStatus, ClosingLineStatus, ClosingLineType, ClosingLineVariant,
    EntryKind, EntryStatus, FeeAssignmentStatus, FeeScheduleStatus, InvoiceOrigin,
    InvoiceLineKind, InvoiceStatus, OfferStatus, OfficeStatus, ReferralStatus,
    ReportStatus, ReportVariant, TransactionStatus,
)


def _assert_common(data: dict, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    if with_version:
        assert isinstance(data.get("version"), int) and data["version"] >= 1, \
            f"version must be an integer >= 1, got {data.get('version')!r}"


def assert_office(data: dict):
    _assert_common(data)
    assert isinstance(data["office_name"], str) and data["office_name"]
    assert isinstance(data["market_code"], str) and data["market_code"]
    assert data["status"] in [s.value for s in OfficeStatus]
    assert isinstance(data["recruiting_target_agents"], int) and data["recruiting_target_agents"] >= 1
    assert isinstance(data["active_agent_count"], int) and data["active_agent_count"] >= 0
    assert isinstance(data["trust_balance_cents"], int)
    assert data.get("closed_at") is None or is_iso8601_timestamp(data["closed_at"])


def assert_fee_schedule(data: dict):
    _assert_common(data)
    assert isinstance(data["schedule_name"], str) and data["schedule_name"]
    assert isinstance(data["desk_fee_cents"], int) and data["desk_fee_cents"] >= 0
    assert isinstance(data["overhead_share_bps"], int) and 0 <= data["overhead_share_bps"] <= 10000
    assert isinstance(data["retention_bps"], int) and 0 <= data["retention_bps"] <= 10000
    assert isinstance(data["referral_fee_bps"], int) and 0 <= data["referral_fee_bps"] <= 5000
    assert isinstance(data["tech_subscription_monthly_cents"], int) and data["tech_subscription_monthly_cents"] >= 0
    assert isinstance(data["marketing_monthly_cents"], int) and data["marketing_monthly_cents"] >= 0
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_to"])
    assert data["status"] in [s.value for s in FeeScheduleStatus]


def assert_agent(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert data["status"] in [s.value for s in AgentStatus]
    assert isinstance(data["supervision_cadence_days"], int) and data["supervision_cadence_days"] > 0
    assert isinstance(data["unearned_advance_balance_cents"], int)
    for f in ("onboarded_at", "termination_requested_at", "terminated_at"):
        assert data.get(f) is None or is_iso8601_timestamp(data[f])


def assert_fee_assignment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["agent_id"])
    assert is_valid_uuid(data["fee_schedule_id"])
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_to"])
    assert data["status"] in [s.value for s in FeeAssignmentStatus]


def assert_offer(data: dict):
    _assert_common(data)
    assert isinstance(data["listing_reference"], str) and data["listing_reference"]
    assert isinstance(data["buyer_name"], str) and data["buyer_name"]
    assert isinstance(data["offer_price_cents"], int) and data["offer_price_cents"] > 0
    assert isinstance(data["offer_round"], int) and data["offer_round"] >= 1
    assert data["status"] in [s.value for s in OfferStatus]


def assert_transaction(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["listing_agent_id"])
    assert is_valid_uuid(data["selling_agent_id"])
    assert is_valid_uuid(data["offer_id"])
    assert isinstance(data["sale_price_cents"], int) and data["sale_price_cents"] > 0
    assert isinstance(data["gross_commission_cents"], int) and data["gross_commission_cents"] > 0
    assert data["status"] in [s.value for s in TransactionStatus]
    assert data.get("closed_at") is None or is_iso8601_timestamp(data["closed_at"])


def assert_cda(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["transaction_id"])
    assert isinstance(data["review_ladder"], list) and len(data["review_ladder"]) == 3
    assert isinstance(data["current_rung"], int) and data["current_rung"] >= 0
    assert data["status"] in [s.value for s in CdaStatus]


def assert_closing_statement_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["transaction_id"])
    assert data["line_type"] in [s.value for s in ClosingLineType]
    assert data.get("agent_id") is None or is_valid_uuid(data["agent_id"])
    assert isinstance(data["amount_cents"], int)
    assert data.get("applied_invoice_line_id") is None or isinstance(data["applied_invoice_line_id"], str)
    assert data["variant"] in [s.value for s in ClosingLineVariant]
    assert data["status"] in [s.value for s in ClosingLineStatus]


def assert_invoice(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["office_id"])
    assert is_valid_uuid(data["agent_id"])
    assert isinstance(data["billing_month"], str) and len(data["billing_month"]) == 7
    assert data["origin"] in [s.value for s in InvoiceOrigin]
    assert isinstance(data["amount_due_cents"], int)
    assert is_iso8601_timestamp(data["due_date"])
    assert isinstance(data["amount_paid_cents"], int) and data["amount_paid_cents"] >= 0
    assert data["status"] in [s.value for s in InvoiceStatus]


def assert_invoice_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["invoice_id"])
    assert data["line_kind"] in [s.value for s in InvoiceLineKind]
    assert isinstance(data["period_label"], str)
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["applied_at_closing_cents"], int) and data["applied_at_closing_cents"] >= 0


def assert_commission_entry(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["office_id"])
    assert data.get("transaction_id") is None or is_valid_uuid(data["transaction_id"])
    assert data["entry_kind"] in [s.value for s in EntryKind]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["entry_month"], str) and len(data["entry_month"]) == 7
    assert data["status"] in [s.value for s in EntryStatus]


def assert_referral_agreement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["referring_office_id"])
    assert is_valid_uuid(data["receiving_office_id"])
    assert is_valid_uuid(data["agent_id"])
    assert isinstance(data["referral_fee_bps"], int) and 0 <= data["referral_fee_bps"] <= 5000
    assert data["status"] in [s.value for s in ReferralStatus]
    assert data.get("replaces_agreement_id") is None or is_valid_uuid(data["replaces_agreement_id"])
    assert data.get("fulfilled_transaction_id") is None or is_valid_uuid(data["fulfilled_transaction_id"])


def assert_retention_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["office_id"])
    assert isinstance(data["period_month"], str) and len(data["period_month"]) == 7
    assert isinstance(data["headcount_start"], int) and data["headcount_start"] >= 0
    assert isinstance(data["headcount_end"], int) and data["headcount_end"] >= 0
    assert isinstance(data["retention_bps"], int) and 0 <= data["retention_bps"] <= 10000
    assert isinstance(data["churned_agent_count"], int) and data["churned_agent_count"] >= 0
    assert data["report_variant"] in [s.value for s in ReportVariant]
    assert data["status"] in [s.value for s in ReportStatus]


def assert_trust_balance_invariant(office: dict):
    """Domain invariant: trust balance is a non-negative derived figure."""
    assert isinstance(office["trust_balance_cents"], int)
    assert office["trust_balance_cents"] >= 0, \
        f"trust_balance_cents went negative: {office['trust_balance_cents']}"


def assert_advance_balance_non_negative(agent: dict):
    assert agent["unearned_advance_balance_cents"] >= 0, \
        f"unearned_advance_balance_cents went negative: {agent['unearned_advance_balance_cents']}"
