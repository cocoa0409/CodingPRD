"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import THRESHOLDS


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------
def assert_identity_and_audit(data: dict):
    """`id` is a server-minted UUID; `created_at`/`updated_at` are ISO 8601 and
    `version` starts at 1 and increments by exactly 1 on every mutation."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert not str(data.get("id", "")).startswith(("cyc_", "team_", "emp_")), (
        "ids never carry a type prefix"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer starting at 1, got {data.get('version')!r}"
    )


def assert_two_decimals(value, label="value"):
    """Every non-integer derived quantity is carried to exactly two decimals."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be numeric, got {value!r}"
    )
    assert round(float(value), 2) == float(value), (
        f"{label} must carry at most two decimal places, got {value!r}"
    )


def assert_integer_cents(value, label="amount"):
    """Money is always an integer count of cents and never a decimal or string."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer count of cents, got {value!r} ({type(value).__name__})"
    )
    assert value >= 0, f"{label} must not be negative, got {value}"


def assert_error_envelope(body: dict):
    """The error envelope carries only api_request_id and api_request_timestamp in
    meta, and exactly error_id plus message in data."""
    assert body.get("response_type") == "error", (
        f"expected response_type 'error', got {body.get('response_type')!r}"
    )
    meta = body.get("meta", {})
    assert set(meta.keys()) == {"api_request_id", "api_request_timestamp"}, (
        f"error meta must contain only api_request_id and api_request_timestamp, "
        f"got {sorted(meta.keys())}"
    )
    assert str(meta["api_request_id"]).startswith("req_"), (
        f"api_request_id must start with req_, got {meta['api_request_id']!r}"
    )
    data = body.get("data", {})
    assert set(data.keys()) == {"error_id", "message"}, (
        f"error data must carry exactly error_id and message, got {sorted(data.keys())}"
    )
    assert isinstance(data["message"], str) and data["message"].strip(), (
        "message must be a non-empty human-readable explanation"
    )


def assert_single_resource_meta(body: dict):
    """Single-resource responses omit limit, offset, total_count and has_more."""
    meta = body.get("meta", {})
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field not in meta, (
            f"single-resource meta must omit {field}, got {sorted(meta.keys())}"
        )


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------
def assert_policy_cycle(data: dict):
    assert_identity_and_audit(data)
    assert isinstance(data["cycle_label"], str) and 1 <= len(data["cycle_label"]) <= 40
    assert data["posture"] in ("OPEN", "RECALIBRATING", "LOCKED")
    assert isinstance(data["days_in_office_floor"], int)
    assert 0 <= data["days_in_office_floor"] <= 5
    assert_two_decimals(data["badge_weight"], "badge_weight")
    assert_two_decimals(data["network_weight"], "network_weight")
    assert_two_decimals(data["collaboration_target_score"], "collaboration_target_score")
    assert_two_decimals(
        data["equity_variance_threshold_pct"], "equity_variance_threshold_pct"
    )
    assert isinstance(data["enrolled_team_count"], int)
    assert_two_decimals(data["aggregate_compliance_rate"], "aggregate_compliance_rate")
    assert 0.00 <= float(data["aggregate_compliance_rate"]) <= 100.00
    assert isinstance(data["formal_action_total"], int)


def assert_team(data: dict):
    assert_identity_and_audit(data)
    assert is_valid_uuid(data["policy_cycle_id"])
    assert isinstance(data["team_code"], str) and 1 <= len(data["team_code"]) <= 24
    assert isinstance(data["expected_days_in_office_per_week"], int)
    assert 0 <= data["expected_days_in_office_per_week"] <= 5
    assert isinstance(data["core_collaboration_days"], list)
    for day in data["core_collaboration_days"]:
        assert day in ("MON", "TUE", "WED", "THU", "FRI")
    assert isinstance(data["headcount_planned"], int)
    assert 1 <= data["headcount_planned"] <= 5000
    assert isinstance(data["signal_corroboration_required"], bool)
    for field in ("expected_daily_attendance", "base_entitlement",
                  "buffer_seats_entitled", "entitled_seats",
                  "escalated_headcount", "formal_action_count"):
        assert isinstance(data[field], int), f"{field} must be an integer"
        assert data[field] >= 0, f"{field} must not be negative"
    assert_seat_entitlement_invariants(data)


def assert_seat_entitlement_invariants(team: dict):
    """The five pinned entitlement steps must agree with each other."""
    assert team["base_entitlement"] == team["expected_daily_attendance"], (
        "base_entitlement is set equal to expected_daily_attendance"
    )
    assert team["entitled_seats"] == (
        team["base_entitlement"] + team["buffer_seats_entitled"]
    ), "entitled_seats is base_entitlement plus buffer_seats_entitled"


def assert_employee(data: dict):
    assert_identity_and_audit(data)
    assert is_valid_uuid(data["team_id"])
    assert isinstance(data["employee_number"], str) and 1 <= len(data["employee_number"]) <= 24
    assert "@" in data["work_email"], "work_email must contain an at-sign"
    assert data["demographic_band"] in ("BAND_A", "BAND_B", "BAND_C", "BAND_D")
    assert data["status"] in ("ACTIVE", "ON_LEAVE", "SEPARATED")
    assert data["current_eligibility_class"] in (
        "FULLY_REMOTE", "HYBRID", "ONSITE_REQUIRED"
    )
    assert data["compliance_state"] in ("COMPLIANT", "AT_RISK", "BREACH")
    assert data["escalation_stage"] in (
        "NONE", "COACHING", "WRITTEN_WARNING", "PERFORMANCE_PLAN",
        "REFERRED", "CURED", "CLOSED_SEPARATION",
    )
    assert isinstance(data["disability_accommodation_on_file"], bool)
    for field in ("cumulative_shortfall_days", "consecutive_breach_weeks",
                  "approved_relief_days_total"):
        assert isinstance(data[field], int) and data[field] >= 0
    assert_two_decimals(data["non_compliance_pressure"], "non_compliance_pressure")
    assert_pressure_invariants(data)


def assert_pressure_invariants(employee: dict):
    """Pressure is clamped at 12.00 and compliance_state follows directly from it."""
    pressure = float(employee["non_compliance_pressure"])
    assert 0.00 <= pressure <= THRESHOLDS["PRESSURE_CEILING"], (
        f"non_compliance_pressure must be clamped to a ceiling of 12.00, got {pressure}"
    )
    state = employee["compliance_state"]
    if pressure == 0.00:
        expected = "COMPLIANT"
    elif pressure < 2.00:
        expected = "AT_RISK"
    else:
        expected = "BREACH"
    assert state == expected, (
        f"pressure {pressure} implies compliance_state {expected}, got {state}"
    )


def assert_classification(data: dict):
    assert_identity_and_audit(data)
    assert is_valid_uuid(data["employee_id"])
    assert data["requested_class"] in ("FULLY_REMOTE", "HYBRID", "ONSITE_REQUIRED")
    assert data["justification_code"] in (
        "ROLE_DESIGN", "EQUIPMENT_BOUND", "CUSTOMER_ONSITE",
        "TALENT_RETENTION", "ACCOMMODATION_LINKED",
    )
    assert data["state"] in ("DRAFT", "PENDING_MANAGER", "APPROVED", "SUPERSEDED")
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]


def assert_attendance_week(data: dict):
    assert_identity_and_audit(data)
    assert is_valid_uuid(data["employee_id"])
    iso_week = data["iso_week"]
    # PRD 2.6: "ISO week labels are strings of the form `YYYY-Www`, four digits, a
    # literal `W`, then two digits" — the declared shape carries the hyphen, so the
    # `W` sits at index 5 and the two ordinal digits at indices 6 and 7.
    assert len(iso_week) == 8 and iso_week[4] == "-" and iso_week[5] == "W", (
        f"iso_week must match the YYYY-Www shape, got {iso_week!r}"
    )
    assert iso_week[:4].isdigit() and iso_week[6:].isdigit()
    assert data["status"] in ("OPEN", "FINALIZED", "AMENDED", "LOCKED")
    for field in ("required_days", "credited_days", "relief_days_credited",
                  "shortfall_days"):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"{field} must be a non-negative integer, got {data[field]!r}"
        )
    assert data["credited_days"] <= THRESHOLDS["MAX_CREDITED_DAYS"], (
        "the count of qualifying dates is capped at 5"
    )
    assert data["variant_applied"] in (None, "SIGNAL_UNION", "SIGNAL_CORROBORATED")
    assert data["relief_days_credited"] <= data["required_days"], (
        "relief credited never exceeds the week's required days"
    )


def assert_compliance_signal(data: dict):
    """A compliance signal carries only id and created_at — no updated_at, no
    version, and neither field appears in its response payload."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, (
        "a compliance signal has no updated_at field at all"
    )
    assert "version" not in data, (
        "a compliance signal has no version field at all"
    )
    assert data["signal_source"] in ("BADGE", "NETWORK", "MANUAL_ATTEST")
    assert isinstance(data["site_code"], str) and 1 <= len(data["site_code"]) <= 16
    assert isinstance(data["minutes_present"], int)
    assert 0 <= data["minutes_present"] <= 1440
    assert isinstance(data["dedupe_key"], str) and 1 <= len(data["dedupe_key"]) <= 64


def assert_exception_request(data: dict):
    assert_identity_and_audit(data)
    assert is_valid_uuid(data["employee_id"])
    assert data["category"] in ("MEDICAL", "CAREGIVING", "DISABILITY_ACCOMMODATION")
    assert isinstance(data["requested_relief_days"], int)
    assert 1 <= data["requested_relief_days"] <= 5
    assert data["status"] in (
        "SUBMITTED", "INFO_REQUESTED", "APPROVED", "DENIED", "REVOKED", "WITHDRAWN"
    )
    assert isinstance(data["granted_relief_days"], int)
    assert isinstance(data["info_round_count"], int) and data["info_round_count"] >= 0
    assert isinstance(data["interactive_process_required"], bool)
    assert data["start_date"] <= data["end_date"], (
        "the relief window is a closed interval whose end is not before its start"
    )


def assert_relocation_request(data: dict):
    assert_identity_and_audit(data)
    assert is_valid_uuid(data["employee_id"])
    assert data["jurisdiction_code"] in ("US_CA", "US_TX", "US_NY", "IE", "IN", "BR")
    assert data["data_classification_tier"] in (
        "PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"
    )
    assert data["status"] in ("SUBMITTED", "UNDER_REVIEW", "APPROVED", "DENIED")
    assert data["tax_review_status"] in ("PENDING", "CLEARED", "BLOCKED")
    assert data["security_review_status"] in ("PENDING", "CLEARED", "BLOCKED")
    for field in ("licensing_gap_count", "control_gap_count"):
        assert isinstance(data[field], int) and 0 <= data[field] <= 20
    assert_integer_cents(
        data["tax_nexus_registration_cost_cents"], "tax_nexus_registration_cost_cents"
    )
    for field in ("preliminary_risk_score", "final_risk_score"):
        assert isinstance(data[field], int), f"{field} must be an integer"
        assert 0 <= data[field] <= THRESHOLDS["RISK_SCORE_CEILING"], (
            f"{field} is clamped to a ceiling of 100 points, got {data[field]}"
        )
    assert data["decision_reason"] in (
        None, "BOTH_REVIEWS_CLEARED", "REVIEW_BLOCKED", "RISK_CEILING_REACHED"
    )


def assert_neighborhood(data: dict):
    assert_identity_and_audit(data)
    assert is_valid_uuid(data["policy_cycle_id"])
    assert is_valid_uuid(data["anchor_team_id"])
    assert isinstance(data["neighborhood_code"], str)
    assert 1 <= len(data["neighborhood_code"]) <= 24
    assert isinstance(data["site_code"], str) and 1 <= len(data["site_code"]) <= 16
    assert isinstance(data["seat_count"], int) and 1 <= data["seat_count"] <= 500
    assert isinstance(data["buffer_seats"], int) and data["buffer_seats"] >= 0
    assert data["buffer_seats"] < data["seat_count"], (
        "buffer_seats must be strictly smaller than seat_count"
    )
    assert data["desk_index_from"] >= 1
    assert data["desk_index_to"] >= data["desk_index_from"]
    assert (data["desk_index_to"] - data["desk_index_from"] + 1) == data["seat_count"], (
        "the count of desk indices inclusive must equal seat_count"
    )
    assert isinstance(data["committed_seats"], int) and data["committed_seats"] >= 0
    assert isinstance(data["peak_committed_seats"], int)
    assert data["peak_committed_seats"] >= 0
    assert_two_decimals(data["utilization_pct"], "utilization_pct")
    assert data["allocation_state"] in ("OPEN", "TIGHT", "FROZEN")


def assert_seat_allocation(data: dict):
    assert_identity_and_audit(data)
    assert is_valid_uuid(data["neighborhood_id"])
    assert is_valid_uuid(data["team_id"])
    assert isinstance(data["allocated_seats"], int)
    assert 1 <= data["allocated_seats"] <= 500
    assert data["status"] in ("RESERVED", "COMMITTED", "RELEASED")
    assert_integer_cents(data["line_chargeback_cents"], "line_chargeback_cents")
    assert isinstance(data["weeks_in_window"], int) and data["weeks_in_window"] >= 1
    assert data["window_start_week"] < data["window_end_week"], (
        "window_end_week must be strictly later than window_start_week"
    )


def assert_desk_assignment(data: dict):
    assert_identity_and_audit(data)
    assert is_valid_uuid(data["seat_allocation_id"])
    assert is_valid_uuid(data["employee_id"])
    assert isinstance(data["desk_index"], int) and data["desk_index"] >= 1
    assert data["status"] in ("ASSIGNED", "VACATED")
    assert data["assignment_mode"] in ("MANUAL", "AUTO")
    assert data["start_date"] <= data["end_date"], (
        "the occupancy interval is closed and not inverted"
    )
    if data["status"] == "ASSIGNED":
        assert data["vacated_at"] is None
    else:
        assert is_iso8601_timestamp(data["vacated_at"] or "")


def assert_escalation_case(data: dict):
    assert_identity_and_audit(data)
    assert is_valid_uuid(data["employee_id"])
    assert data["stage"] in (
        "COACHING", "WRITTEN_WARNING", "PERFORMANCE_PLAN", "REFERRED",
        "CURED", "CLOSED_SEPARATION",
    )
    assert_two_decimals(data["opened_pressure"], "opened_pressure")
    assert isinstance(data["discretionary_hold"], bool)
    if data["prior_case_id"] is not None:
        assert is_valid_uuid(data["prior_case_id"])


def assert_recalibration_review(data: dict):
    assert_identity_and_audit(data)
    assert is_valid_uuid(data["policy_cycle_id"])
    assert isinstance(data["review_label"], str) and 1 <= len(data["review_label"]) <= 40
    assert isinstance(data["proposed_days_in_office_delta"], int)
    assert -2 <= data["proposed_days_in_office_delta"] <= 2
    assert data["state"] in ("DRAFT", "SUBMITTED", "ADOPTED", "REJECTED")
    assert_two_decimals(data["collaboration_index"], "collaboration_index")
    assert_two_decimals(data["equity_variance_pct"], "equity_variance_pct")
    assert_integer_cents(
        data["total_space_chargeback_cents"], "total_space_chargeback_cents"
    )
    assert isinstance(data["qualifying_band_count"], int)
    assert 0 <= data["qualifying_band_count"] <= 4
    assert isinstance(data["meets_collaboration_target"], bool)
    assert isinstance(data["equity_flag"], bool)


# --------------------------------------------------------------------------
# Cross-entity invariant checkers
# --------------------------------------------------------------------------
def assert_stage_matches_pressure(case: dict, pressure: float):
    """The pressure-derived stage bands are inclusive at two decimal places."""
    if pressure >= 10.00:
        expected = "REFERRED"
    elif pressure >= 7.00:
        expected = "PERFORMANCE_PLAN"
    elif pressure >= 4.00:
        expected = "WRITTEN_WARNING"
    elif pressure >= 2.00:
        expected = "COACHING"
    else:
        expected = "CURED"
    assert case["stage"] == expected, (
        f"pressure {pressure} implies stage {expected}, got {case['stage']}"
    )


def assert_shortfall_arithmetic(week: dict):
    """shortfall_days is required minus credited minus relief, floored at zero."""
    expected = max(
        0,
        week["required_days"] - week["credited_days"] - week["relief_days_credited"],
    )
    assert week["shortfall_days"] == expected, (
        f"shortfall_days should be {expected}, got {week['shortfall_days']}"
    )


def assert_utilization_arithmetic(neighborhood: dict):
    """utilization_pct is 100 * peak_committed_seats / usable capacity."""
    usable = neighborhood["seat_count"] - neighborhood["buffer_seats"]
    raw = 100 * neighborhood["peak_committed_seats"] / usable
    expected = float(_round_half_up(raw, 2))
    assert abs(float(neighborhood["utilization_pct"]) - expected) < 0.005, (
        f"utilization_pct should be {expected}, got {neighborhood['utilization_pct']}"
    )


def _round_half_up(value: float, places: int) -> float:
    from decimal import Decimal, ROUND_HALF_UP
    quant = Decimal(1).scaleb(-places)
    return float(Decimal(repr(value)).quantize(quant, rounding=ROUND_HALF_UP))


def round_half_up(value, places: int = 2) -> float:
    """Round half up to `places` decimals, away from zero at the midpoint."""
    return _round_half_up(float(value), places)
