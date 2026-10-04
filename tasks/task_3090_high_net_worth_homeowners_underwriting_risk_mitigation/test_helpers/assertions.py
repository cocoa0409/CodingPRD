"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _is_timestamp(value) -> bool:
    """PRD 2.2/2.6 fix on the three-fractional-digit form, so a value the
    framework's lenient parser accepts without milliseconds still has to be
    normalised here."""
    return isinstance(value, str) and value.endswith("Z") and "." in value


def _assert_common(data: dict, with_history: bool = True):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert _is_timestamp(data.get("created_at")), (
        "created_at must be an ISO 8601 UTC timestamp with three fractional digits")
    if with_history:
        assert _is_timestamp(data.get("updated_at")), (
            "updated_at must be an ISO 8601 UTC timestamp with three fractional digits")
        assert isinstance(data.get("version"), int), "version must be an integer"
        assert data["version"] >= 1, "version is a system-managed counter starting at 1"


def assert_risk_zone(data: dict):
    _assert_common(data)
    assert isinstance(data["zone_code"], str) and data["zone_code"]
    assert data["wildland_urban_interface_band"] in ("WITHIN_WUI", "ADJACENT_WUI", "OUTSIDE_WUI")
    assert isinstance(data["sustained_wind_mph"], int) and data["sustained_wind_mph"] >= 0
    assert data["mitigation_band_multiplier"] > 0
    assert data["concentration_band"] in ("NORMAL", "ELEVATED", "CRITICAL")
    assert isinstance(data["freeze_active"], bool)
    assert data["exposure_band"] in ("STANDARD", "ELEVATED", "EXTREME")
    assert data["state_event"] in ("NONE", "WATCH", "ACTIVE")


def assert_agency(data: dict):
    _assert_common(data)
    assert isinstance(data["agency_code"], str) and data["agency_code"]
    assert data["servicing_tier"] in ("PREMIER", "SELECT", "STANDARD")
    assert isinstance(data["delegated_authority_limit_cents"], int)
    assert data["delegated_authority_limit_cents"] >= 0
    assert isinstance(data["active"], bool)
    assert data["concentration_band"] in ("NORMAL", "ELEVATED", "CRITICAL")


def assert_property(data: dict):
    _assert_common(data)
    assert data["base_posture"] in (
        "PENDING_APPRAISAL", "MITIGATION_REQUIRED", "UNDERWRITABLE", "DECLINED")
    assert data["posture"] in ("WRITE_FROZEN", "REFERRAL_REQUIRED", "WRITE_ELIGIBLE")
    assert data["mitigation_band"] in ("CLEARED", "PARTIAL", "FAILED", "UNVERIFIED")
    assert isinstance(data["defense_in_progress"], bool)
    assert isinstance(data["total_insured_value_cents"], int)
    assert data["total_insured_value_cents"] >= 0


def assert_appraisal(data: dict):
    _assert_common(data)
    assert data["valuation_method"] in ("SITE_MEASURED", "DESKTOP_ESTIMATE", "DRIVE_BY")
    assert data["status"] in (
        "PENDING_REVIEW", "REVIEWED", "APPROVED", "REJECTED", "SUPERSEDED", "WITHDRAWN")
    assert data["percent_complete"] in (0.0, 1.0)
    assert data["dwelling_cost_cents"] > 0
    assert 0 < data["valuation_confidence_pct"] <= 100


def assert_scheduled_item(data: dict):
    _assert_common(data)
    assert data["item_type"] in ("JEWELRY", "FINE_ART", "COLLECTION", "WINE")
    assert data["status"] in ("PENDING", "APPROVED", "ATTACHED", "REJECTED")
    assert data["declared_value_cents"] > 0
    assert isinstance(data["attached_value_cents"], int)


def assert_mitigation_requirement(data: dict):
    _assert_common(data)
    assert data["requirement_code"] in (
        "DEFENSIBLE_SPACE", "FIRE_RESISTANT_ROOF", "EMBER_VENT_SCREEN",
        "EXTERIOR_IRRIGATION", "FULL_MITIGATION_PROGRAM")
    assert data["band_awarded"] in ("CLEARED", "PARTIAL")
    assert data["source"] in ("UNDERWRITING", "RISK_CONSULTANT", "DEFENSE_FOLLOW_UP")
    assert data["status"] in ("IMPOSED", "VERIFIED", "LAPSED", "WAIVED")
    assert isinstance(data["verification_count"], int) and data["verification_count"] >= 0


def assert_risk_consultation(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED", "NO_SHOW")
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] > 0


def assert_dispatch(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "REQUESTED", "VENDOR_ASSIGNED", "ON_SITE", "COMPLETED", "CANCELLED")
    assert isinstance(data["priority_rank"], int)


def assert_enrollment(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "REFERRED", "APPROVED", "ATTACHED", "DECLINED", "WITHDRAWN")
    assert data["replacement_provision"] in ("GUARANTEED", "EXTENDED", "NONE")
    assert data["risk_tier"] in ("MANAGED", "REVIEW", "SURCHARGE", "REFER")
    assert isinstance(data["risk_score"], int)
    assert 0 <= data["risk_score"] <= 999
    assert data["dwelling_coverage_cents"] > 0


def assert_claim(data: dict):
    _assert_common(data)
    assert data["cause_of_loss"] in (
        "WILDFIRE", "WIND", "HALL", "WATER", "THEFT", "OTHER")
    assert data["status"] in (
        "REPORTED", "UNDER_REVIEW", "APPROVED", "SETTLED", "DENIED", "PAID", "REJECTED")
    assert isinstance(data["reported_indemnity_cents"], int)
    assert data["reported_indemnity_cents"] >= 0
    assert isinstance(data["cash_settlement_eligible"], bool)


def assert_non_renewal_notice(data: dict):
    _assert_common(data)
    assert data["ground"] in (
        "CONCENTRATION_REVIEW", "MITIGATION_FAILURE", "APPRAISAL_LAPSE", "NONPAYMENT")
    assert data["status"] in ("PENDING", "ISSUED", "EFFECTIVE", "RESCINDED")
    assert isinstance(data["required_notice_days"], int)
    assert isinstance(data["notice_period_days"], int)


def assert_appraisal_document(data: dict):
    """Append-only record: carries id and created_at only."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["item_class"] in ("JEWELRY", "FINE_ART", "COLLECTION", "WINE", "DWELLING")
    assert data["appraised_value_cents"] > 0
    assert data["currency_status"] in ("CURRENT", "AGING", "EXPIRED")
    assert isinstance(data["currency_months"], int)


def assert_managed_risk_event(data: dict):
    """Append-only record: carries id and created_at only."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["event_type"] in ("OVERDUE_WARNING", "REPEAT_INSPECTION_NOTICE")
    assert isinstance(data["derived_key"], str) and data["derived_key"]


def assert_property_invariants(data: dict):
    """Domain invariants that must hold after any property operation."""
    assert data["dwelling_replacement_cost_cents"] >= 0
    assert data["contents_replacement_cost_cents"] >= 0
    assert data["scheduled_valuation_cents"] >= 0
    assert data["total_insured_value_cents"] == (
        data["dwelling_replacement_cost_cents"]
        + data["contents_replacement_cost_cents"]
        + data["scheduled_valuation_cents"]
    ), "total insured value is dwelling + contents + scheduled, excluding loss-of-use"


def assert_enrollment_invariants(data: dict):
    """Domain invariants that must hold after any enrollment operation."""
    assert data["risk_score"] >= 0
    assert data["stress_reserve_cents"] == (
        data["dwelling_coverage_cents"]
        + data["contents_coverage_cents"]
        + data["scheduled_coverage_cents"]
    )
    if data["status"] in ("DECLINED", "WITHDRAWN"):
        assert data["committed_reserve_cents"] == 0


def assert_risk_tier_for_score(risk_score: int, risk_tier: str):
    """The published tier is derived from the score in a downward cascade."""
    if risk_score >= 700:
        expected = "REFER"
    elif risk_score >= 450:
        expected = "SURCHARGE"
    elif risk_score >= 200:
        expected = "REVIEW"
    else:
        expected = "MANAGED"
    assert risk_tier == expected, f"score {risk_score} should tier as {expected}, got {risk_tier}"