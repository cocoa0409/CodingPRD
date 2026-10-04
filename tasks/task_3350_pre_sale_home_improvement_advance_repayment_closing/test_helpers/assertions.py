"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    CapacityWindowStatus,
    CasePosture,
    ChangeOrderReason,
    ChangeOrderStatus,
    ClosingStatementStatus,
    ConciergeCaseStatus,
    DisbursementKind,
    DisbursementStatus,
    DisputeKind,
    DisputeStatus,
    ImprovementProjectStatus,
    ListingEventKind,
    PayoffBasis,
    UpfrontPaymentTrack,
    VendorEngagementStatus,
    VendorTrade,
)

CASE_STATUSES = [s.value for s in ConciergeCaseStatus]
POSTURES = [s.value for s in CasePosture]
TRACKS = [s.value for s in UpfrontPaymentTrack]
PROJECT_STATUSES = [s.value for s in ImprovementProjectStatus]
VENDOR_TRADES = [s.value for s in VendorTrade]
ENGAGEMENT_STATUSES = [s.value for s in VendorEngagementStatus]
DISBURSEMENT_STATUSES = [s.value for s in DisbursementStatus]
DISBURSEMENT_KINDS = [s.value for s in DisbursementKind]
CHANGE_ORDER_STATUSES = [s.value for s in ChangeOrderStatus]
CHANGE_ORDER_REASONS = [s.value for s in ChangeOrderReason]
DISPUTE_STATUSES = [s.value for s in DisputeStatus]
DISPUTE_KINDS = [s.value for s in DisputeKind]
STATEMENT_STATUSES = [s.value for s in ClosingStatementStatus]
PAYOFF_BASES = [s.value for s in PayoffBasis]
LISTING_EVENT_KINDS = [s.value for s in ListingEventKind]
WINDOW_STATUSES = [s.value for s in CapacityWindowStatus]


def _assert_common_fields(data: dict, entity_label: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), f"{entity_label}.version must be an integer"


def assert_agent(data: dict):
    _assert_common_fields(data, "Agent")
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert isinstance(data["brokerage"], str) and data["brokerage"]


def assert_vendor(data: dict):
    _assert_common_fields(data, "Vendor")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["trade"] in VENDOR_TRADES
    assert isinstance(data["quality_score_bp"], int)
    assert 0 <= data["quality_score_bp"] <= 10000
    assert isinstance(data["on_time_streak"], int)


def assert_capacity_window(data: dict):
    _assert_common_fields(data, "VendorCapacityWindow")
    assert isinstance(data["vendor_id"], str) and data["vendor_id"]
    assert is_iso8601_timestamp(data.get("window_start", ""))
    assert is_iso8601_timestamp(data.get("window_end", ""))
    assert isinstance(data["capacity_crew_days"], int)
    assert isinstance(data["reserved_crew_days"], int)
    assert data["status"] in WINDOW_STATUSES


def assert_concierge_case(data: dict):
    _assert_common_fields(data, "ConciergeCase")
    assert isinstance(data["address_line"], str) and data["address_line"]
    assert isinstance(data["estimated_property_value_cents"], int)
    assert isinstance(data["expected_sale_proceeds_cents"], int)
    assert isinstance(data["listing_agreement_signed"], bool)
    assert isinstance(data["listing_agreement_disclosure_ack"], bool)
    assert isinstance(data["advance_total_cents"], int)
    assert data["status"] in CASE_STATUSES
    assert data["posture"] in POSTURES


def assert_improvement_project(data: dict):
    _assert_common_fields(data, "ImprovementProject")
    assert isinstance(data["concierge_case_id"], str) and data["concierge_case_id"]
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["recommended_by_agent"], bool)
    assert isinstance(data["expected_sale_price_lift_cents"], int)
    assert isinstance(data["estimated_cost_cents"], int)
    assert data["status"] in PROJECT_STATUSES


def assert_vendor_engagement(data: dict):
    _assert_common_fields(data, "VendorEngagement")
    assert isinstance(data["improvement_project_id"], str) and data["improvement_project_id"]
    assert isinstance(data["vendor_id"], str) and data["vendor_id"]
    assert isinstance(data["agreed_price_cents"], int)
    assert is_iso8601_timestamp(data.get("start_date", ""))
    assert is_iso8601_timestamp(data.get("end_date", ""))
    assert data["status"] in ENGAGEMENT_STATUSES


def assert_disbursement(data: dict):
    _assert_common_fields(data, "Disbursement")
    assert isinstance(data["concierge_case_id"], str) and data["concierge_case_id"]
    assert isinstance(data["improvement_project_id"], str) and data["improvement_project_id"]
    assert isinstance(data["vendor_engagement_id"], str) and data["vendor_engagement_id"]
    assert isinstance(data["amount_cents"], int)
    assert data["kind"] in DISBURSEMENT_KINDS
    assert data["status"] in DISBURSEMENT_STATUSES


def assert_change_order(data: dict):
    _assert_common_fields(data, "ChangeOrder")
    assert isinstance(data["improvement_project_id"], str) and data["improvement_project_id"]
    assert isinstance(data["vendor_engagement_id"], str) and data["vendor_engagement_id"]
    assert isinstance(data["delta_cents"], int)
    assert data["reason"] in CHANGE_ORDER_REASONS
    assert data["status"] in CHANGE_ORDER_STATUSES


def assert_dispute(data: dict):
    _assert_common_fields(data, "Dispute")
    assert isinstance(data["concierge_case_id"], str) and data["concierge_case_id"]
    assert isinstance(data["improvement_project_id"], str) and data["improvement_project_id"]
    assert isinstance(data["vendor_engagement_id"], str) and data["vendor_engagement_id"]
    assert data["dispute_kind"] in DISPUTE_KINDS
    assert isinstance(data["claimed_amount_cents"], int)
    assert data["status"] in DISPUTE_STATUSES


def assert_closing_statement(data: dict):
    _assert_common_fields(data, "ClosingStatement")
    assert isinstance(data["concierge_case_id"], str) and data["concierge_case_id"]
    assert data["payoff_basis"] in PAYOFF_BASES
    assert isinstance(data["advance_repayment_cents"], int)
    assert isinstance(data["program_fee_cents"], int)
    assert isinstance(data["late_fee_cents"], int)
    assert isinstance(data["vendor_holdback_cents"], int)
    assert isinstance(data["net_repayment_cents"], int)
    assert data["status"] in STATEMENT_STATUSES


def assert_listing_event(data: dict):
    _assert_common_fields(data, "ListingEvent")
    assert isinstance(data["concierge_case_id"], str) and data["concierge_case_id"]
    assert data["event_kind"] in LISTING_EVENT_KINDS
    assert is_iso8601_timestamp(data.get("event_at", ""))


def assert_case_advance_invariants(case_data: dict):
    """The advance ledger must stay within the case's approved cap."""
    if "advance_limit_cents" in case_data and case_data["advance_limit_cents"] is not None:
        assert case_data["advance_total_cents"] <= case_data["advance_limit_cents"], (
            "advance_total_cents must never exceed advance_limit_cents"
        )
    assert case_data["advance_total_cents"] >= 0


def assert_closing_statement_invariants(stmt: dict):
    """Net repayment composition must hold on any finalized statement."""
    expected = (
        stmt["advance_repayment_cents"]
        + stmt["program_fee_cents"]
        + stmt["late_fee_cents"]
        - stmt["vendor_holdback_cents"]
    )
    if stmt["status"] == "WAIVED":
        # Waived statements carry only the advance principal.
        assert stmt["net_repayment_cents"] == stmt["advance_repayment_cents"]
    else:
        assert stmt["net_repayment_cents"] == expected, (
            f"net_repayment_cents {stmt['net_repayment_cents']} != composed {expected}"
        )
