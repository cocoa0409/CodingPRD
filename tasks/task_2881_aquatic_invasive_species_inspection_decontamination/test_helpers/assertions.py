"""Entity assertions, instant canonicalisation and domain invariant checkers."""
from datetime import datetime, timezone
from typing import Optional

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .types import (
    AgreementStatus,
    CampaignStatus,
    CertificationLevel,
    DeconOrderStatus,
    DetectionClass,
    DetectionReportStatus,
    EnforcementStatus,
    EvaluationMethod,
    InfestationStatus,
    InspectionStatus,
    InspectorStatus,
    QuarantineOrderStatus,
    ReferralReason,
    RiskBand,
    RiskTier,
    StaffingLevel,
    StationStatus,
    StationType,
    VesselType,
    WatchlistStatus,
    WaterBodyClass,
)


# ---------------------------------------------------------------------------
# Instant handling.  The program emits every timestamp as an ISO 8601 UTC
# instant with three fractional digits, so comparisons against a literal
# instant must canonicalise both sides rather than compare raw strings.
# ---------------------------------------------------------------------------
def parse_instant(value: str) -> datetime:
    assert isinstance(value, str) and value.strip(), f"expected an instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def instants_equal(actual: Optional[str], expected: Optional[str]) -> bool:
    if actual is None or expected is None:
        return actual is None and expected is None
    return parse_instant(actual) == parse_instant(expected)


def assert_instant_equals(actual, expected, label="instant"):
    assert actual is not None, f"{label} must be set, got None"
    assert instants_equal(actual, expected), (
        f"Expected {label} {expected}, got {actual}"
    )


def assert_three_fractional_digits(value: str, label="timestamp"):
    """Instants are rendered with exactly three fractional digits."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert value.endswith("Z"), f"{label} must end with Z, got {value!r}"
    assert "." in value, f"{label} must carry fractional digits, got {value!r}"
    fraction = value.rsplit(".", 1)[1][:-1]
    assert len(fraction) == 3, (
        f"{label} must carry exactly three fractional digits, got {value!r}"
    )


# ---------------------------------------------------------------------------
# Common field helpers
# ---------------------------------------------------------------------------
def assert_common_fields(data: dict, entity="entity"):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID: {data.get('id')!r}"
    assert not str(data.get("id", "")).startswith(f"{entity.lower()}_"), (
        f"{entity}.id must carry no prefix"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601: {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601: {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"
    assert data["version"] >= 1, f"{entity}.version starts at 1, got {data['version']}"


def assert_envelope_meta(body: dict):
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), (
        f"meta.api_request_id must start with req_, got {meta['api_request_id']!r}"
    )
    assert_three_fractional_digits(meta["api_request_timestamp"], "api_request_timestamp")


# ---------------------------------------------------------------------------
# Entity assertions
# ---------------------------------------------------------------------------
def assert_water_body(data: dict):
    assert_common_fields(data, "WaterBody")
    assert isinstance(data["name"], str) and data["name"]
    assert data["water_body_class"] in [e.value for e in WaterBodyClass]
    assert data["risk_tier"] in [e.value for e in RiskTier]
    assert data["infestation_status"] in [e.value for e in InfestationStatus]
    assert isinstance(data["detection_count"], int) and data["detection_count"] >= 0
    assert isinstance(data["live_detection_count"], int)
    assert data["live_detection_count"] <= data["detection_count"], (
        "live_detection_count counts a subset of the accepted reports"
    )


def assert_station(data: dict):
    assert_common_fields(data, "InspectionStation")
    assert data["station_type"] in [e.value for e in StationType]
    assert data["status"] in [e.value for e in StationStatus]
    assert isinstance(data["mandatory_inspection"], bool)
    assert isinstance(data["decon_bay_count"], int) and data["decon_bay_count"] >= 0
    assert isinstance(data["hot_water_capable"], bool)
    assert isinstance(data["seal_stock_count"], int)
    assert isinstance(data["seals_in_circulation_count"], int)
    assert isinstance(data["seals_retired_count"], int)
    assert isinstance(data["certified_inspector_count"], int)
    assert isinstance(data["decon_service_available"], bool)
    assert isinstance(data["collected_fees_cents"], int)
    assert isinstance(data["refunded_fees_cents"], int)
    assert isinstance(data["campaign_allocated_cents"], int)
    if data["station_type"] == "WATERBODY_ACCESS":
        assert data["water_body_id"], "a water-body access station names its water body"
        assert data["corridor_route_code"] is None
    else:
        assert data["water_body_id"] is None
        assert data["corridor_route_code"], "a corridor station names its route code"


def assert_station_hours(data: dict):
    assert_common_fields(data, "StationHours")
    assert data["staffing_level"] in [e.value for e in StaffingLevel]
    assert parse_instant(data["closes_at"]) > parse_instant(data["opens_at"]), (
        "closes_at must be strictly later than opens_at"
    )


def assert_inspector(data: dict):
    assert_common_fields(data, "Inspector")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["status"] in [e.value for e in InspectorStatus]
    assert data["certification_level"] in [e.value for e in CertificationLevel]
    assert isinstance(data["decon_endorsement"], bool)
    assert isinstance(data["training_hours_total"], (int, float))
    assert_cost_precision(float(data["training_hours_total"]), 2)


def assert_training_record(data: dict):
    """A training record is immutable: only id and created_at accompany it."""
    assert is_valid_uuid(data.get("id", "")), "TrainingRecord.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "TrainingRecord.created_at must be ISO 8601"
    )
    assert "version" not in data, (
        "a training record carries no version field"
    )
    assert "updated_at" not in data, (
        "a training record carries no updated_at field"
    )
    assert isinstance(data["hours"], (int, float)) and data["hours"] > 0
    assert isinstance(data["passed"], bool)


def assert_watercraft(data: dict):
    assert_common_fields(data, "Watercraft")
    assert data["vessel_type"] in [e.value for e in VesselType]
    assert data["watchlist_status"] in [e.value for e in WatchlistStatus]
    assert isinstance(data["compliance_strikes"], int) and data["compliance_strikes"] >= 0
    assert isinstance(data["mandatory_decon_flag"], bool)
    assert isinstance(data["hull_length_ft"], (int, float)) and data["hull_length_ft"] > 0


def assert_reciprocity_agreement(data: dict):
    assert_common_fields(data, "ReciprocityAgreement")
    assert data["status"] in [e.value for e in AgreementStatus]
    assert isinstance(data["honors_our_seals"], bool)
    assert isinstance(data["fee_waiver"], bool)
    assert isinstance(data["max_seal_age_hours"], int) and data["max_seal_age_hours"] > 0
    assert isinstance(data["accepted_seal_prefix"], str) and data["accepted_seal_prefix"]


def assert_inspection_record(data: dict):
    assert_common_fields(data, "InspectionRecord")
    assert data["inspection_status"] in [e.value for e in InspectionStatus]
    assert data["enforcement_status"] in [e.value for e in EnforcementStatus]
    assert data["risk_band"] in [e.value for e in RiskBand]
    if data["referral_reason"] is not None:
        assert data["referral_reason"] in [e.value for e in ReferralReason]
    for field in ("risk_score", "advisory_risk_score"):
        assert isinstance(data[field], int), f"{field} must be a whole number"
        assert 0 <= data[field] <= 100, f"{field} must be clamped into 0..100"
    for field in ("inspection_fee_cents", "decon_fee_cents", "surcharge_cents",
                  "total_fee_cents", "fee_refunded_cents", "penalty_cents"):
        assert isinstance(data[field], int), f"{field} must be whole cents"
        assert data[field] >= 0, f"{field} must never go negative"
    assert isinstance(data["decon_mandatory"], bool)
    assert isinstance(data["quarantine_warranted"], bool)
    assert data["total_fee_cents"] == (
        data["inspection_fee_cents"] + data["decon_fee_cents"] + data["surcharge_cents"]
    ), "total_fee_cents is the sum of its three components"


def assert_decon_order(data: dict):
    assert_common_fields(data, "DeconOrder")
    assert data["status"] in [e.value for e in DeconOrderStatus]
    assert data["band_at_order"] in [e.value for e in RiskBand]
    assert isinstance(data["attempt_count"], int) and data["attempt_count"] >= 0
    if data["treatment_effectiveness_pct"] is not None:
        pct = float(data["treatment_effectiveness_pct"])
        assert 0.0 <= pct <= 100.0, "effectiveness is clamped into 0.00..100.00"
        assert_cost_precision(pct, 2)
    if data["required_dry_hours"] is not None:
        assert isinstance(data["required_dry_hours"], int)
        assert data["required_dry_hours"] >= 6, "the dry floor is six hours"


def assert_quarantine_order(data: dict):
    assert_common_fields(data, "QuarantineOrder")
    assert data["status"] in [e.value for e in QuarantineOrderStatus]
    assert data["band_at_issue"] in [e.value for e in RiskBand]
    assert isinstance(data["seal_number"], str) and data["seal_number"]
    assert isinstance(data["seal_state_code"], str) and len(data["seal_state_code"]) == 2
    assert isinstance(data["rejected_release_count"], int)
    assert isinstance(data["hold_hours_required"], int)


def assert_detection_report(data: dict):
    assert_common_fields(data, "DetectionReport")
    assert data["status"] in [e.value for e in DetectionReportStatus]
    assert data["detection_class"] in [e.value for e in DetectionClass]
    assert isinstance(data["submission_count"], int) and data["submission_count"] >= 0


def assert_campaign(data: dict):
    assert_common_fields(data, "EducationCampaign")
    assert data["status"] in [e.value for e in CampaignStatus]
    if data["evaluation_method"] is not None:
        assert data["evaluation_method"] in [e.value for e in EvaluationMethod]
    assert isinstance(data["budget_cents"], int) and data["budget_cents"] > 0
    assert isinstance(data["impressions"], int) and data["impressions"] >= 0
    assert isinstance(data["station_allocations"], list)
    for allocation in data["station_allocations"]:
        assert "station_id" in allocation and "allocated_cents" in allocation
        assert isinstance(allocation["allocated_cents"], int)
    if data["effectiveness_score"] is not None:
        score = float(data["effectiveness_score"])
        assert 0.0 <= score <= 100.0, "effectiveness_score is clamped into 0.00..100.00"


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def assert_seal_inventory_conserved(station: dict):
    total = (
        station["seal_stock_count"]
        + station["seals_in_circulation_count"]
        + station["seals_retired_count"]
    )
    assert total == station["seal_stock_initial_count"], (
        "seal_stock_count + seals_in_circulation_count + seals_retired_count must "
        f"equal seal_stock_initial_count; got {total} vs "
        f"{station['seal_stock_initial_count']}"
    )


def assert_station_fee_ledger(station: dict, records: list):
    expected_collected = sum(r["total_fee_cents"] - r["fee_refunded_cents"] for r in records)
    expected_refunded = sum(r["fee_refunded_cents"] for r in records)
    assert station["collected_fees_cents"] == expected_collected, (
        f"collected_fees_cents must equal {expected_collected}, "
        f"got {station['collected_fees_cents']}"
    )
    assert station["refunded_fees_cents"] == expected_refunded, (
        f"refunded_fees_cents must equal {expected_refunded}, "
        f"got {station['refunded_fees_cents']}"
    )


def assert_campaign_allocations_sum_to_budget(campaign: dict):
    allocated = sum(a["allocated_cents"] for a in campaign["station_allocations"])
    assert allocated == campaign["budget_cents"], (
        f"the allocations must sum to budget_cents {campaign['budget_cents']}, "
        f"got {allocated}"
    )


def assert_strike_posture(watercraft: dict, expected_strikes: int):
    assert watercraft["compliance_strikes"] == expected_strikes, (
        f"expected {expected_strikes} strikes, got {watercraft['compliance_strikes']}"
    )
    expected_status = "WATCHLISTED" if expected_strikes >= 2 else "CLEAR"
    assert watercraft["watchlist_status"] == expected_status, (
        f"expected watchlist_status {expected_status}, got {watercraft['watchlist_status']}"
    )
    assert watercraft["mandatory_decon_flag"] is (expected_strikes >= 2), (
        "mandatory_decon_flag tracks the watchlist"
    )
