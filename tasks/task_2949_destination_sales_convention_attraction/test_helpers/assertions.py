"""Entity assertions and domain invariant checkers for the destination-sales API."""
from typing import Any, Dict, Optional

import pytest
from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
)

from .api_client import canonical_instant, same_instant

MONEY_TOLERANCE = 0.005


def assert_money(value: Any, label: str = "amount") -> None:
    """A monetary field is a number with at most two fraction digits."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be a JSON number, got {value!r}"
    )
    assert_cost_precision(float(value))


def assert_money_equals(actual: Any, expected: float, label: str = "amount") -> None:
    assert_money(actual, label)
    assert float(actual) == pytest.approx(expected, abs=MONEY_TOLERANCE), (
        f"Expected {label} == {expected}, got {actual}"
    )


def assert_versioned_common_fields(data: Dict[str, Any], label: str = "resource") -> None:
    """id + created_at + updated_at + version, as the PRD requires of this kind."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 UTC instant, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 UTC instant, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer starting at 1, got {data.get('version')!r}"
    )


def assert_append_only_common_fields(data: Dict[str, Any], label: str = "record") -> None:
    """An append-only event record carries only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 UTC instant, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, f"{label} must not expose updated_at"
    assert "version" not in data, f"{label} must not expose version"


def assert_list_response(response) -> tuple:
    """Every list endpoint of this API is paginated by offset."""
    return validate_paginated(response)


def assert_unpaginated_list(response, expected_status: int = 200) -> list:
    """List-shaped payload with no pagination guarantees demanded of meta."""
    assert response.status_code == expected_status, (
        f"Expected {expected_status}, got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert isinstance(body.get("data"), list), "data must be an array"
    return body["data"]


def assert_pagination_meta(meta: Dict[str, Any], limit: int, offset: int,
                           total_count: int, has_more: bool) -> None:
    assert meta["limit"] == limit, f"Expected meta.limit {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"Expected meta.offset {offset}, got {meta['offset']}"
    assert meta["total_count"] == total_count, (
        f"Expected meta.total_count {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"Expected meta.has_more {has_more}, got {meta['has_more']}"
    )


# --- per-resource assertions -------------------------------------------------

def assert_meeting_planner(data: Dict[str, Any]) -> None:
    assert_versioned_common_fields(data, "MeetingPlanner")
    assert isinstance(data["org_name"], str) and 1 <= len(data["org_name"]) <= 120
    assert "@" in data["contact_email"]
    for field in (
        "legacy_definite_count",
        "legacy_definite_room_nights",
        "definite_count",
        "lost_count",
        "lifetime_definite_room_nights",
        "relationship_score_lifetime",
        "relationship_score_rolling_24m",
    ):
        assert isinstance(data[field], int), f"MeetingPlanner.{field} must be an integer"
        assert data[field] >= 0, f"MeetingPlanner.{field} must not be negative"
    assert 0 <= data["relationship_score_lifetime"] <= 100
    assert 0 <= data["relationship_score_rolling_24m"] <= 100
    assert data["tier"] in ("TIER_A", "TIER_B", "TIER_C")
    assert data["engagement_status"] in ("PROSPECT", "ENGAGED")
    if data.get("last_touch_at") is not None:
        assert is_iso8601_timestamp(data["last_touch_at"])


def assert_hotel(data: Dict[str, Any]) -> None:
    assert_versioned_common_fields(data, "Hotel")
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert isinstance(data["committable_rooms"], int) and data["committable_rooms"] >= 1
    assert isinstance(data["walk_distance_blocks"], int) and data["walk_distance_blocks"] >= 0
    assert data["participation_status"] in ("PARTICIPATING", "SUSPENDED")
    for field in ("committed_peak_rooms", "committed_room_nights", "pickup_room_nights"):
        assert isinstance(data[field], int) and data[field] >= 0


def assert_center_hall(data: Dict[str, Any]) -> None:
    assert_versioned_common_fields(data, "CenterHall")
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert isinstance(data["exhibit_sqft"], int) and data["exhibit_sqft"] >= 1
    assert isinstance(data["capacity_persons"], int) and data["capacity_persons"] >= 1
    assert isinstance(data["turnaround_hours"], int) and data["turnaround_hours"] >= 0
    assert data["hall_status"] in ("AVAILABLE", "UNDER_RENOVATION")
    assert isinstance(data["confirmed_hold_count"], int) and data["confirmed_hold_count"] >= 0


def assert_opportunity(data: Dict[str, Any]) -> None:
    assert_versioned_common_fields(data, "Opportunity")
    assert is_valid_uuid(data["planner_id"])
    assert isinstance(data["event_name"], str) and 1 <= len(data["event_name"]) <= 160
    assert data["arrival_date"] < data["departure_date"]
    assert isinstance(data["event_nights"], int) and data["event_nights"] >= 1
    assert data["sales_stage"] in (
        "LEAD", "QUALIFIED", "BIDDING", "DEFINITE", "SERVICED", "LOST",
    )
    assert data["hold_posture"] in (
        "NONE", "TENTATIVE", "CHALLENGED", "CONFIRMED", "RELEASED",
    )
    for field in (
        "peak_rooms_requested",
        "total_room_nights_requested",
        "attendance_estimate",
        "exhibit_sqft_requested",
        "committed_peak_rooms",
        "citywide_cutoff_days_before_arrival",
        "cutoff_alignment_spread_days",
        "definite_room_nights",
    ):
        assert isinstance(data[field], int), f"Opportunity.{field} must be an integer"
    assert_money(data["rate_ceiling_amount"], "Opportunity.rate_ceiling_amount")
    assert_money(data["attrition_settlement_amount"], "Opportunity.attrition_settlement_amount")
    coverage = data["block_coverage_pct"]
    assert isinstance(coverage, (int, float)), "block_coverage_pct must be a number"
    assert round(float(coverage), 2) == pytest.approx(float(coverage)), (
        "block_coverage_pct is stored with two decimal places"
    )
    if data.get("definite_at") is not None:
        assert is_iso8601_timestamp(data["definite_at"])


def assert_space_hold(data: Dict[str, Any]) -> None:
    assert_versioned_common_fields(data, "SpaceHold")
    assert is_valid_uuid(data["opportunity_id"])
    assert is_valid_uuid(data["center_hall_id"])
    assert data["status"] in ("HELD", "CHALLENGED", "CONFIRMED", "RELEASED", "EXPIRED")
    assert data["hold_rank"] in ("FIRST", "SECOND")
    assert is_iso8601_timestamp(data["move_in_start"])
    assert is_iso8601_timestamp(data["move_out_end"])
    assert canonical_instant(data["move_in_start"]) < canonical_instant(data["move_out_end"])
    assert is_iso8601_timestamp(data["expires_at"])
    if data.get("challenge_deadline") is not None:
        assert is_iso8601_timestamp(data["challenge_deadline"])
    if data.get("release_reason") is not None:
        assert data["release_reason"] in (
            "SCHEDULER_RELEASE", "CHALLENGE_LAPSED", "OPPORTUNITY_LOST",
            "SUPERSEDED_BY_CONFIRMED", "HOLD_EXPIRED", "EVENT_SERVICED",
        )


def assert_room_block_commitment(data: Dict[str, Any]) -> None:
    assert_versioned_common_fields(data, "RoomBlockCommitment")
    assert is_valid_uuid(data["opportunity_id"])
    assert is_valid_uuid(data["hotel_id"])
    assert isinstance(data["rooms_peak_invited"], int) and data["rooms_peak_invited"] >= 1
    assert data["status"] in ("INVITED", "OFFERED", "COMMITTED", "WITHDRAWN", "RELEASED")
    for field in (
        "rooms_peak_committed",
        "offer_round",
        "committed_room_nights",
        "picked_up_room_nights",
        "attrition_shortfall_nights",
    ):
        assert isinstance(data[field], int) and data[field] >= 0
    assert_money(data["attrition_damages_amount"], "RoomBlockCommitment.attrition_damages_amount")
    if data.get("rate_offered_amount") is not None:
        assert_money(data["rate_offered_amount"], "RoomBlockCommitment.rate_offered_amount")
    if data.get("withdraw_reason") is not None:
        assert data["withdraw_reason"] in (
            "PROPERTY_SOLD_OUT", "RATE_DISPUTE", "INVITE_DECLINED",
            "OPPORTUNITY_LOST", "EVENT_SERVICED",
        )


def assert_bid_package(data: Dict[str, Any]) -> None:
    assert_versioned_common_fields(data, "BidPackage")
    assert is_valid_uuid(data["opportunity_id"])
    assert isinstance(data["round_number"], int) and 1 <= data["round_number"] <= 3
    assert data["status"] in (
        "DRAFT", "INCENTIVE_PENDING", "APPROVED", "SUBMITTED", "ACCEPTED", "DECLINED",
    )
    assert isinstance(data["prepared_by_user_id"], str) and data["prepared_by_user_id"]
    assert isinstance(data["service_commitment_codes"], list)
    assert isinstance(data["support_letter_type_count"], int)
    for field in (
        "incentive_request_amount",
        "incentive_cap_amount",
        "approved_incentive_amount",
        "admin_fee_amount",
        "total_fund_charge_amount",
        "tax_payback_ratio",
    ):
        if data.get(field) is not None:
            assert_money(data[field], f"BidPackage.{field}")
    if data.get("planner_response") is not None:
        assert data["planner_response"] in ("ACCEPTED", "DECLINED", "REVISION_REQUESTED")
    if data.get("decline_reason") is not None:
        assert data["decline_reason"] in (
            "RATE_TOO_HIGH", "INSUFFICIENT_INCENTIVE",
            "LOST_TO_COMPETITOR", "REVISION_LIMIT_REACHED",
        )


def assert_incentive_fund(data: Dict[str, Any]) -> None:
    assert_versioned_common_fields(data, "IncentiveFund")
    assert isinstance(data["fiscal_year"], int) and data["fiscal_year"] >= 2020
    for field in (
        "budget_amount",
        "lodging_tax_receipts_total",
        "committed_amount",
        "disbursed_amount",
        "uncommitted_amount",
    ):
        assert_money(data[field], f"IncentiveFund.{field}")
    assert data["posture"] in ("OPEN", "CONSTRAINED", "EXHAUSTED")
    assert_fund_conservation_identity(data)
    assert_fund_posture_derivation(data)


def assert_fund_conservation_identity(fund: Dict[str, Any]) -> None:
    """budget_amount equals uncommitted plus committed plus disbursed."""
    total = (
        float(fund["uncommitted_amount"])
        + float(fund["committed_amount"])
        + float(fund["disbursed_amount"])
    )
    assert float(fund["budget_amount"]) == pytest.approx(total, abs=MONEY_TOLERANCE), (
        "budget_amount must equal uncommitted_amount + committed_amount + "
        f"disbursed_amount; got {fund['budget_amount']} vs {total}"
    )


def assert_fund_posture_derivation(fund: Dict[str, Any]) -> None:
    """posture follows from the residual: 0 -> EXHAUSTED, <10% -> CONSTRAINED."""
    residual = float(fund["uncommitted_amount"])
    budget = float(fund["budget_amount"])
    if residual == pytest.approx(0.0, abs=MONEY_TOLERANCE):
        expected = "EXHAUSTED"
    elif residual < budget * 0.10 - MONEY_TOLERANCE:
        expected = "CONSTRAINED"
    elif residual > budget * 0.10 + MONEY_TOLERANCE:
        expected = "OPEN"
    else:
        expected = "OPEN"  # a residual exactly at ten percent leaves posture OPEN
    assert fund["posture"] == expected, (
        f"Expected posture {expected} for residual {residual} of budget {budget}, "
        f"got {fund['posture']}"
    )


def assert_servicing_order(data: Dict[str, Any]) -> None:
    assert_versioned_common_fields(data, "ServicingOrder")
    assert is_valid_uuid(data["opportunity_id"])
    assert data["category"] in ("HOUSING", "TRANSPORTATION", "VOLUNTEER")
    assert isinstance(data["requested_units"], int) and data["requested_units"] >= 1
    assert isinstance(data["assigned_units"], int) and data["assigned_units"] >= 0
    assert isinstance(data["delivered_units"], int) and data["delivered_units"] >= 0
    assert data["status"] in ("REQUESTED", "SCHEDULED", "DELIVERED", "CANCELLED")
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])


def assert_board_report(data: Dict[str, Any]) -> None:
    assert_versioned_common_fields(data, "BoardReport")
    assert data["period_start"] < data["period_end"]
    for field in (
        "definite_opportunity_count",
        "definite_room_nights",
        "lost_opportunity_count",
    ):
        assert isinstance(data[field], int) and data[field] >= 0
    assert isinstance(data["lost_room_nights_by_reason"], dict)
    for field in (
        "incentive_spend_committed_amount",
        "lodging_tax_recognized_amount",
        "attrition_recovered_amount",
    ):
        assert_money(data[field], f"BoardReport.{field}")
    if data.get("cost_per_definite_room_night") is not None:
        assert_money(data["cost_per_definite_room_night"], "BoardReport.cost_per_definite_room_night")
    assert data["status"] in ("DRAFT", "PUBLISHED")


# --- append-only records -----------------------------------------------------

def assert_support_letter(data: Dict[str, Any]) -> None:
    assert_append_only_common_fields(data, "SupportLetter")
    assert is_valid_uuid(data["bid_package_id"])
    assert isinstance(data["organization_name"], str) and 1 <= len(data["organization_name"]) <= 120
    assert data["letter_type"] in (
        "MAYOR", "CHAMBER", "UNIVERSITY", "INDUSTRY_PARTNER", "CONVENTION_CENTER",
    )
    assert is_iso8601_timestamp(data["received_at"])


def assert_incentive_decision(data: Dict[str, Any]) -> None:
    assert_append_only_common_fields(data, "IncentiveDecision")
    assert is_valid_uuid(data["bid_package_id"])
    assert is_valid_uuid(data["fund_id"])
    assert data["decision"] in ("APPROVED", "REDUCED", "REJECTED")
    assert_money(data["requested_amount"], "IncentiveDecision.requested_amount")
    assert_money(data["approved_amount"], "IncentiveDecision.approved_amount")
    assert_money(data["admin_fee_amount"], "IncentiveDecision.admin_fee_amount")
    assert_money(data["total_charge_amount"], "IncentiveDecision.total_charge_amount")
    assert isinstance(data["decided_by_user_id"], str) and data["decided_by_user_id"]
    assert isinstance(data["rationale"], str) and 1 <= len(data["rationale"]) <= 500


def assert_economic_impact_estimate(data: Dict[str, Any]) -> None:
    assert_append_only_common_fields(data, "EconomicImpactEstimate")
    assert is_valid_uuid(data["opportunity_id"])
    assert data["variant"] in ("PROVISIONAL", "FINAL")
    assert isinstance(data["room_nights_basis"], int) and data["room_nights_basis"] >= 0
    for field in (
        "lodging_spend_amount",
        "delegate_spend_amount",
        "exhibitor_spend_amount",
        "direct_spend_amount",
        "total_impact_amount",
        "lodging_tax_yield_amount",
    ):
        assert_money(data[field], f"EconomicImpactEstimate.{field}")
    assert is_iso8601_timestamp(data["computed_at"])
    components = (
        float(data["lodging_spend_amount"])
        + float(data["delegate_spend_amount"])
        + float(data["exhibitor_spend_amount"])
    )
    assert float(data["direct_spend_amount"]) == pytest.approx(components, abs=MONEY_TOLERANCE), (
        "direct_spend_amount is the sum of the three already-rounded components"
    )


def assert_pickup_record(data: Dict[str, Any]) -> None:
    assert_append_only_common_fields(data, "PickupRecord")
    assert is_valid_uuid(data["room_block_commitment_id"])
    assert isinstance(data["night_date"], str) and len(data["night_date"]) == 10
    assert isinstance(data["rooms_picked_up"], int) and data["rooms_picked_up"] >= 0
    assert_money(data["rate_charged_amount"], "PickupRecord.rate_charged_amount")
    assert float(data["rate_charged_amount"]) > 0
    assert_money(data["room_night_revenue_amount"], "PickupRecord.room_night_revenue_amount")


def assert_lodging_tax_receipt(data: Dict[str, Any]) -> None:
    assert_append_only_common_fields(data, "LodgingTaxReceipt")
    assert is_valid_uuid(data["fund_id"])
    assert_money(data["amount"], "LodgingTaxReceipt.amount")
    assert float(data["amount"]) > 0
    assert is_iso8601_timestamp(data["received_at"])


def assert_error_envelope_shape(response) -> Dict[str, Any]:
    """An error envelope's meta carries only api_request_id and
    api_request_timestamp, and its data only error_id and message."""
    body = response.json()
    assert body["response_type"] == "error"
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, (
        f"Error meta must carry only api_request_id and api_request_timestamp, got {sorted(body['meta'])}"
    )
    assert set(body["data"].keys()) == {"error_id", "message"}, (
        f"Error data must carry only error_id and message, got {sorted(body['data'])}"
    )
    assert body["meta"]["api_request_id"].startswith("req_")
    return body
