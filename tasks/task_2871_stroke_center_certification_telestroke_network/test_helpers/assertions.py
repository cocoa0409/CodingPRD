"""Entity assertions and domain invariant checkers.

Every helper here asserts only properties the PRD states, so a faithful
implementation cannot fail them.
"""
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant, instants_equal
from .constants import (
    CONGESTION_BY_POSTURE,
    ROUTING_POSTURE,
    TRANSFER_PROJECTION,
)


def round_half_up(value: float, places: int = 2) -> float:
    """PRD 2.6 rounds half up, which is not Python's default rounding mode."""
    quant = Decimal(1).scaleb(-places)
    return float(Decimal(repr(float(value))).quantize(quant, rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Common resource properties (PRD 2.5)
# ---------------------------------------------------------------------------
def assert_common_properties(data: dict, expected_version: Optional[int] = None) -> None:
    """id / created_at / updated_at / version, carried by all ten resources."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be an ISO 8601 UTC instant, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be an ISO 8601 UTC instant, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"version must be an integer, got {data.get('version')!r}"
    )
    assert data["version"] >= 1, "version begins at 1 on creation"
    if expected_version is not None:
        assert data["version"] == expected_version, (
            f"Expected version {expected_version}, got {data['version']}"
        )


def assert_three_fractional_digits(instant: str) -> None:
    """PRD 2.5: system instants carry three fractional digits."""
    assert isinstance(instant, str) and instant.endswith("Z"), (
        f"instant must be a UTC ISO 8601 string, got {instant!r}"
    )
    assert "." in instant, f"instant must carry fractional digits, got {instant!r}"
    frac = instant.split(".", 1)[1][:-1]
    assert len(frac) == 3, f"instant must carry three fractional digits, got {instant!r}"


def assert_two_decimal_places(value: float, field: str = "value") -> None:
    """PRD 2.6: money-style decimal quantities are carried to exactly 2 decimals."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be a JSON number, got {value!r}"
    )
    assert round(float(value), 2) == pytest.approx(float(value)), (
        f"{field} must be carried to at most 2 decimal places, got {value!r}"
    )


def assert_one_decimal_place(value: float, field: str = "value") -> None:
    """PRD 2.6: public_dtn_compliance_pct is published at 1 decimal place."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be a JSON number, got {value!r}"
    )
    assert round(float(value), 1) == pytest.approx(float(value)), (
        f"{field} must be carried to at most 1 decimal place, got {value!r}"
    )


# ---------------------------------------------------------------------------
# Stroke center (PRD 3.1, 2.9)
# ---------------------------------------------------------------------------
def assert_stroke_center(data: dict) -> None:
    assert_common_properties(data)
    assert isinstance(data["name"], str) and 0 < len(data["name"]) <= 120
    assert data["facility_type"] in ("HUB_PRIMARY", "SPOKE", "THROMBECTOMY_CAPABLE")
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["ems_region_code"], str) and 0 < len(data["ems_region_code"]) <= 16
    assert data["certification_status"] in (
        "PROVISIONAL", "CERTIFIED", "CONDITIONAL", "SUSPENDED", "WITHDRAWN",
    )
    assert isinstance(data["ct_scanner_ready"], bool)
    assert isinstance(data["video_cart_ready"], bool)
    assert data["equipment_readiness_posture"] in ("READY", "DEGRADED", "OFFLINE")
    assert isinstance(data["open_case_count"], int) and data["open_case_count"] >= 0
    assert data["ems_routing_posture"] in ("ROUTINE", "DIVERT_ADVISORY", "BYPASS")
    assert isinstance(data["consecutive_denied_report_count"], int)
    assert data["consecutive_denied_report_count"] >= 0
    assert_equipment_readiness_posture(data)
    assert_ems_routing_posture(data)


def assert_equipment_readiness_posture(center: dict) -> None:
    """PRD 2.9: READY when both flags are true, DEGRADED when exactly one is,
    OFFLINE when neither is."""
    ready_count = int(bool(center["ct_scanner_ready"])) + int(bool(center["video_cart_ready"]))
    expected = {2: "READY", 1: "DEGRADED", 0: "OFFLINE"}[ready_count]
    assert center["equipment_readiness_posture"] == expected, (
        f"Expected equipment_readiness_posture {expected} for "
        f"ct_scanner_ready={center['ct_scanner_ready']} "
        f"video_cart_ready={center['video_cart_ready']}, "
        f"got {center['equipment_readiness_posture']}"
    )


def expected_ems_routing_posture(center: dict) -> str:
    """PRD 2.9: the ordered three-clause rule, first matching clause wins."""
    if center["certification_status"] in ("SUSPENDED", "WITHDRAWN"):
        return "BYPASS"
    if center["equipment_readiness_posture"] == "OFFLINE":
        return "BYPASS"
    if center["equipment_readiness_posture"] == "DEGRADED":
        return "DIVERT_ADVISORY"
    if center["open_case_count"] >= ROUTING_POSTURE["OPEN_CASE_DIVERT_THRESHOLD"]:
        return "DIVERT_ADVISORY"
    if center["certification_status"] == "CONDITIONAL":
        return "DIVERT_ADVISORY"
    return "ROUTINE"


def assert_ems_routing_posture(center: dict) -> None:
    expected = expected_ems_routing_posture(center)
    assert center["ems_routing_posture"] == expected, (
        f"Expected ems_routing_posture {expected} for certification_status="
        f"{center['certification_status']} equipment={center['equipment_readiness_posture']} "
        f"open_case_count={center['open_case_count']}, got {center['ems_routing_posture']}"
    )


# ---------------------------------------------------------------------------
# Spoke agreement (PRD 3.1)
# ---------------------------------------------------------------------------
def assert_spoke_agreement(data: dict) -> None:
    assert_common_properties(data)
    assert is_valid_uuid(data["hub_center_id"])
    assert is_valid_uuid(data["spoke_center_id"])
    assert data["coverage_tier"] in ("TIER_1_FULL", "TIER_2_CONSULT_ONLY")
    assert isinstance(data["max_concurrent_consults"], int)
    assert 1 <= data["max_concurrent_consults"] <= 20
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "TERMINATED")
    assert isinstance(data["proxy_credentials"], list)
    assert isinstance(data["active_consult_count"], int) and data["active_consult_count"] >= 0
    for grant in data["proxy_credentials"]:
        assert_proxy_credential_grant(grant)


def assert_proxy_credential_grant(grant: dict) -> None:
    """PRD 2.5/3.1: an embedded grant carries exactly the enumerated fields and
    no id, updated_at or version of its own."""
    assert is_valid_uuid(grant["neurologist_id"])
    assert grant["privilege_scope"] in ("CONSULT_ONLY", "CONSULT_AND_THROMBOLYSIS")
    assert is_iso8601_timestamp(grant["expires_at"])
    assert grant["status"] in ("GRANTED", "EXPIRED")
    assert is_iso8601_timestamp(grant["granted_at"])
    assert "id" not in grant, "an embedded grant has no id of its own"
    assert "updated_at" not in grant, "an embedded grant has no updated_at of its own"
    assert "version" not in grant, "an embedded grant has no version of its own"


# ---------------------------------------------------------------------------
# Neurologist (PRD 3.1)
# ---------------------------------------------------------------------------
def assert_neurologist(data: dict) -> None:
    assert_common_properties(data)
    assert isinstance(data["full_name"], str) and 0 < len(data["full_name"]) <= 120
    assert is_valid_uuid(data["home_center_id"])
    assert isinstance(data["licensed_state_codes"], list) and data["licensed_state_codes"]
    for code in data["licensed_state_codes"]:
        assert isinstance(code, str) and len(code) == 2
    assert isinstance(data["board_certified"], bool)
    assert isinstance(data["roster_rank"], int) and 1 <= data["roster_rank"] <= 999
    assert isinstance(data["concurrent_consult_limit"], int)
    assert 1 <= data["concurrent_consult_limit"] <= 5
    assert data["on_call_state"] in ("OFF_DUTY", "ON_CALL", "IN_CONSULT", "UNAVAILABLE")
    assert isinstance(data["active_consult_count"], int) and data["active_consult_count"] >= 0
    assert isinstance(data["completed_consult_count"], int)
    assert data["completed_consult_count"] >= 0


# ---------------------------------------------------------------------------
# Code stroke case (PRD 3.2)
# ---------------------------------------------------------------------------
def assert_code_stroke_case(data: dict) -> None:
    assert_common_properties(data)
    assert is_valid_uuid(data["center_id"])
    assert isinstance(data["patient_ref"], str) and 0 < len(data["patient_ref"]) <= 40
    assert is_iso8601_timestamp(data["door_at"])
    assert data["lkw_precision"] in ("EXACT", "ESTIMATED", "UNKNOWN_WAKE_UP")
    assert data["arrival_mode"] in ("EMS", "WALK_IN", "INTERFACILITY_TRANSFER")
    assert is_iso8601_timestamp(data["activation_at"])
    assert data["status"] in (
        "ACTIVATED", "IMAGING_COMPLETE", "CONSULT_IN_PROGRESS", "ELIGIBILITY_DETERMINED",
        "THROMBOLYSIS_ADMINISTERED", "TRANSFER_INITIATED", "CLOSED", "ABORTED",
    )
    assert data["disposition"] in (
        "PENDING", "TREATED_LOCAL", "DRIP_AND_SHIP", "TRANSFER_ONLY", "NO_TREATMENT",
    )
    assert isinstance(data["activated_by_user_id"], str) and data["activated_by_user_id"]
    assert isinstance(data["deviation_count"], int) and data["deviation_count"] >= 0
    if data["lkw_precision"] == "UNKNOWN_WAKE_UP":
        assert data["last_known_well_at"] is None, (
            "an UNKNOWN_WAKE_UP capture leaves last_known_well_at null"
        )
    if data["thrombolytic_window_class"] is not None:
        assert data["thrombolytic_window_class"] in (
            "WITHIN_3H", "WITHIN_4_5H", "EXTENDED_UNKNOWN", "OUT_OF_WINDOW",
        )


def assert_case_clock_intervals(case: dict) -> None:
    """PRD 2.6: elapsed-time quantities are whole integers or null."""
    for field in ("door_to_imaging_minutes", "door_to_needle_minutes",
                  "lkw_to_needle_minutes", "door_in_door_out_minutes"):
        if field in case and case[field] is not None:
            assert isinstance(case[field], int) and not isinstance(case[field], bool), (
                f"{field} must be a whole integer, got {case[field]!r}"
            )
            assert case[field] >= 0, f"{field} must not be negative, got {case[field]}"


# ---------------------------------------------------------------------------
# Telestroke consult (PRD 3.3, 3.4)
# ---------------------------------------------------------------------------
def assert_telestroke_consult(data: dict) -> None:
    assert_common_properties(data)
    assert is_valid_uuid(data["case_id"])
    assert is_valid_uuid(data["agreement_id"])
    assert data["requested_privilege_scope"] in ("CONSULT_ONLY", "CONSULT_AND_THROMBOLYSIS")
    assert data["status"] in (
        "REQUESTED", "ASSIGNED", "IN_SESSION", "COMPLETED", "ESCALATED_UNFILLED", "CANCELLED",
    )
    assert is_iso8601_timestamp(data["requested_at"])
    assert isinstance(data["decline_count"], int) and data["decline_count"] >= 0
    assert isinstance(data["routing_attempt_count"], int) and data["routing_attempt_count"] >= 0
    assert isinstance(data["excluded_neurologist_ids"], list)
    assert isinstance(data["video_sessions"], list)
    assert isinstance(data["valid_video_session_count"], int)
    assert data["valid_video_session_count"] >= 0
    for session in data["video_sessions"]:
        assert_video_session_record(session)
    assert_valid_video_session_count(data)


def expected_session_valid(session: dict) -> bool:
    """PRD 3.4: duration_seconds >= 180 AND video_quality is not AUDIO_ONLY
    AND disconnect_count <= 2."""
    return (
        session["duration_seconds"] >= 180
        and session["video_quality"] != "AUDIO_ONLY"
        and session["disconnect_count"] <= 2
    )


def assert_video_session_record(session: dict) -> None:
    assert is_iso8601_timestamp(session["started_at"])
    assert session["video_quality"] in ("HD", "SD", "AUDIO_ONLY")
    assert isinstance(session["disconnect_count"], int)
    assert isinstance(session["duration_seconds"], int)
    assert isinstance(session["session_valid"], bool)
    assert "id" not in session, "an embedded video session record has no id of its own"
    assert "version" not in session, "an embedded video session record has no version"
    assert session["session_valid"] == expected_session_valid(session), (
        f"session_valid must be {expected_session_valid(session)} for "
        f"duration_seconds={session['duration_seconds']} "
        f"video_quality={session['video_quality']} "
        f"disconnect_count={session['disconnect_count']}, got {session['session_valid']}"
    )


def assert_valid_video_session_count(consult: dict) -> None:
    """PRD 2.8/3.4: the count of appended sessions with session_valid true."""
    expected = sum(1 for s in consult["video_sessions"] if s["session_valid"])
    assert consult["valid_video_session_count"] == expected, (
        f"valid_video_session_count must be {expected}, got "
        f"{consult['valid_video_session_count']}"
    )


# ---------------------------------------------------------------------------
# Thrombolytic checklist (PRD 3.5)
# ---------------------------------------------------------------------------
def assert_thrombolytic_checklist(data: dict) -> None:
    assert_common_properties(data)
    assert is_valid_uuid(data["case_id"])
    assert data["documentation_status"] in ("NOT_STARTED", "IN_PROGRESS", "DOCUMENTED", "AMENDED")
    assert data["determination_status"] in (
        "PENDING", "ELIGIBLE", "INELIGIBLE", "ELIGIBLE_WITH_RELATIVE_OVERRIDE",
    )
    assert isinstance(data["confirmed_inclusion_item_codes"], list)
    assert data["confirmed_inclusion_item_count"] == len(data["confirmed_inclusion_item_codes"]), (
        "confirmed_inclusion_item_count is the length of confirmed_inclusion_item_codes"
    )
    assert isinstance(data["contraindications"], list)
    absolute = sum(1 for c in data["contraindications"] if c["severity"] == "ABSOLUTE")
    relative = sum(1 for c in data["contraindications"] if c["severity"] == "RELATIVE")
    assert data["absolute_contraindication_count"] == absolute, (
        f"absolute_contraindication_count must be {absolute}, got "
        f"{data['absolute_contraindication_count']}"
    )
    assert data["relative_contraindication_count"] == relative, (
        f"relative_contraindication_count must be {relative}, got "
        f"{data['relative_contraindication_count']}"
    )
    assert_two_decimal_places(data["screening_eligibility_score"], "screening_eligibility_score")
    assert 0.0 <= data["screening_eligibility_score"] <= 100.0
    if data["attested_eligibility_score"] is not None:
        assert_two_decimal_places(data["attested_eligibility_score"], "attested_eligibility_score")
        assert 0.0 <= data["attested_eligibility_score"] <= 100.0
    assert isinstance(data["amendment_count"], int) and data["amendment_count"] >= 0
    for entry in data["contraindications"]:
        assert_documented_contraindication(entry)


def assert_documented_contraindication(entry: dict) -> None:
    assert isinstance(entry["code"], str) and entry["code"]
    assert entry["severity"] in ("ABSOLUTE", "RELATIVE")
    assert isinstance(entry["recorded_by_user_id"], str) and entry["recorded_by_user_id"]
    assert is_iso8601_timestamp(entry["recorded_at"])
    assert "id" not in entry, "an embedded contraindication has no id of its own"
    assert "version" not in entry, "an embedded contraindication has no version"


def expected_screening_score(inclusion_count: int, relative_count: int, absolute_count: int) -> float:
    """PRD 3.5 screening variant: 15.0 per inclusion item, -12.0 per relative,
    -100.0 per absolute, clamped into 0..100 then rounded to two decimals."""
    raw = 15.0 * inclusion_count - 12.0 * relative_count - 100.0 * absolute_count
    return round_half_up(min(100.0, max(0.0, raw)), 2)


def expected_attested_score(
    inclusion_count: int,
    relative_count: int,
    absolute_count: int,
    window_class: str,
    board_certified: bool,
) -> float:
    """PRD 3.5 attested variant: the screening expression minus the window
    penalty plus 6.0 of board-certification credit, clamped then rounded."""
    from .constants import WINDOW_PENALTY_BY_CLASS

    raw = (
        15.0 * inclusion_count
        - 12.0 * relative_count
        - 100.0 * absolute_count
        - WINDOW_PENALTY_BY_CLASS[window_class]
        + (6.0 if board_certified else 0.0)
    )
    return round_half_up(min(100.0, max(0.0, raw)), 2)


# ---------------------------------------------------------------------------
# Transfer decision (PRD 3.7)
# ---------------------------------------------------------------------------
def assert_transfer_decision(data: dict) -> None:
    assert_common_properties(data)
    assert is_valid_uuid(data["case_id"])
    assert is_valid_uuid(data["origin_center_id"])
    assert is_valid_uuid(data["destination_center_id"])
    assert data["mode"] in ("DRIP_AND_SHIP", "TRANSFER_ONLY")
    assert isinstance(data["transport_eta_minutes"], int)
    assert 1 <= data["transport_eta_minutes"] <= 600
    assert data["status"] in ("PROPOSED", "ACCEPTED", "DECLINED", "HANDOFF_COMPLETE", "CANCELLED")
    assert data["destination_posture_at_proposal"] in ("ROUTINE", "DIVERT_ADVISORY")
    assert_two_decimal_places(data["congestion_factor"], "congestion_factor")
    assert isinstance(data["adjusted_transport_minutes"], int)
    assert isinstance(data["projected_door_in_door_out_minutes"], int)
    assert isinstance(data["handoff_packet_items"], list)
    assert isinstance(data["handoff_packet_complete"], bool)
    assert is_iso8601_timestamp(data["proposed_at"])
    assert_transfer_projection(data)


def expected_adjusted_transport_minutes(transport_eta_minutes: int, posture: str) -> int:
    """PRD 3.7 step 3: transport_eta_minutes * congestion_factor taken up to the
    next whole minute."""
    import math

    product = transport_eta_minutes * CONGESTION_BY_POSTURE[posture]
    return int(math.ceil(round(product, 6)))


def expected_projected_dido_minutes(
    transport_eta_minutes: int, posture: str, mode: str
) -> int:
    """PRD 3.7 step 4: adjusted_transport_minutes + 20, plus a further 10 for
    DRIP_AND_SHIP.  The overheads are never multiplied."""
    adjusted = expected_adjusted_transport_minutes(transport_eta_minutes, posture)
    total = adjusted + TRANSFER_PROJECTION["HANDOFF_PREP_MIN"]
    if mode == "DRIP_AND_SHIP":
        total += TRANSFER_PROJECTION["DRIP_AND_SHIP_EXTRA_MIN"]
    return total


def assert_transfer_projection(transfer: dict) -> None:
    posture = transfer["destination_posture_at_proposal"]
    expected_factor = CONGESTION_BY_POSTURE[posture]
    assert transfer["congestion_factor"] == pytest.approx(expected_factor, abs=0.001), (
        f"congestion_factor must be {expected_factor} for a {posture} snapshot, "
        f"got {transfer['congestion_factor']}"
    )
    expected_adjusted = expected_adjusted_transport_minutes(
        transfer["transport_eta_minutes"], posture
    )
    assert transfer["adjusted_transport_minutes"] == expected_adjusted, (
        f"adjusted_transport_minutes must be {expected_adjusted}, got "
        f"{transfer['adjusted_transport_minutes']}"
    )
    expected_projection = expected_projected_dido_minutes(
        transfer["transport_eta_minutes"], posture, transfer["mode"]
    )
    assert transfer["projected_door_in_door_out_minutes"] == expected_projection, (
        f"projected_door_in_door_out_minutes must be {expected_projection}, got "
        f"{transfer['projected_door_in_door_out_minutes']}"
    )


# ---------------------------------------------------------------------------
# Protocol deviation (PRD 3.8)
# ---------------------------------------------------------------------------
def assert_protocol_deviation(data: dict) -> None:
    assert_common_properties(data)
    assert is_valid_uuid(data["case_id"])
    assert data["deviation_type"] in (
        "DTI_EXCEEDED", "DTN_EXCEEDED", "DIDO_EXCEEDED", "CONSULT_UNFILLED",
        "MISSING_CONTRAINDICATION_DOC", "INVALID_VIDEO_SESSION", "LKW_WINDOW_VIOLATION",
    )
    assert data["severity"] in ("MINOR", "MAJOR", "SENTINEL")
    assert isinstance(data["narrative"], str) and 0 < len(data["narrative"]) <= 500
    assert data["source"] in ("SYSTEM_DETECTED", "MANUAL")
    assert data["status"] in (
        "OPEN", "UNDER_REVIEW", "RETURNED_FOR_INFO", "SUBSTANTIATED", "DISMISSED",
    )
    assert isinstance(data["opened_by_user_id"], str) and data["opened_by_user_id"]
    assert isinstance(data["review_round"], int) and 0 <= data["review_round"] <= 3
    assert isinstance(data["debrief_completed"], bool)


def assert_system_detected_deviation(data: dict, deviation_type: str, severity: str) -> None:
    """PRD 3.8: system rows carry source SYSTEM_DETECTED and the literal
    opened_by_user_id 'system'."""
    assert_protocol_deviation(data)
    assert data["source"] == "SYSTEM_DETECTED", (
        f"Expected source SYSTEM_DETECTED, got {data['source']}"
    )
    assert data["opened_by_user_id"] == "system", (
        f"Expected opened_by_user_id 'system', got {data['opened_by_user_id']!r}"
    )
    assert data["deviation_type"] == deviation_type
    assert data["severity"] == severity
    assert data["status"] == "OPEN", f"a freshly opened deviation is OPEN, got {data['status']}"


# ---------------------------------------------------------------------------
# Quality measure abstraction (PRD 3.9)
# ---------------------------------------------------------------------------
def assert_quality_measure_abstraction(data: dict) -> None:
    assert_common_properties(data)
    assert is_valid_uuid(data["case_id"])
    assert data["measure_code"] in (
        "STK_4_THROMBOLYTIC_THERAPY", "STK_DTI_45", "STK_DTN_60", "STK_TELESTROKE_RESPONSE",
    )
    assert data["variant"] in ("PROVISIONAL", "CERTIFIED")
    assert isinstance(data["numerator_flag"], bool)
    assert isinstance(data["denominator_included"], bool)
    assert data["exclusion_reason"] in (
        "NONE", "OUT_OF_WINDOW", "ABORTED_CASE",
        "DOCUMENTED_ABSOLUTE_CONTRAINDICATION", "TRANSFER_ONLY",
    )
    assert data["status"] in ("DRAFT", "FINALIZED", "RETRACTED")
    assert isinstance(data["abstracted_by_user_id"], str) and data["abstracted_by_user_id"]
    if data["variant"] == "CERTIFIED":
        assert data["denominator_included"] == (data["exclusion_reason"] == "NONE"), (
            "under the certified variant denominator_included is true only when "
            "exclusion_reason is NONE"
        )


# ---------------------------------------------------------------------------
# Certification report (PRD 3.9)
# ---------------------------------------------------------------------------
def assert_certification_report(data: dict) -> None:
    assert_common_properties(data)
    assert is_valid_uuid(data["center_id"])
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "ACCEPTED", "RETURNED", "PUBLISHED", "SUPERSEDED",
    )
    assert isinstance(data["included_abstraction_count"], int)
    assert data["included_abstraction_count"] >= 0
    assert isinstance(data["closed_case_count_in_period"], int)
    assert data["closed_case_count_in_period"] >= 0
    for field in ("dtn_60_compliance_pct", "dti_45_compliance_pct",
                  "telestroke_response_compliance_pct", "composite_certification_score"):
        assert_two_decimal_places(data[field], field)
        assert 0.0 <= data[field] <= 100.0
    if data["mean_dtn_excess_pct"] is not None:
        assert_two_decimal_places(data["mean_dtn_excess_pct"], "mean_dtn_excess_pct")
    assert data["rate_variant"] in ("PROVISIONAL", "CERTIFIED")
    assert isinstance(data["substantiated_major_count"], int)
    assert isinstance(data["substantiated_sentinel_count"], int)
    assert data["decision"] in ("PENDING", "CERTIFIED", "CONDITIONAL", "DENIED")


def expected_composite_score(
    dtn_pct: float,
    dti_pct: float,
    resp_pct: float,
    major_count: int,
    sentinel_count: int,
    included_abstraction_count: int,
    facility_type: str,
) -> float:
    """PRD 3.9: (base - capped penalty + volume credit) * tier multiplier,
    clamped into 0..100 and rounded to two decimals half up exactly once."""
    from .constants import COMPOSITE, TIER_MULTIPLIER_BY_FACILITY_TYPE

    base = (
        COMPOSITE["W_DTN"] * dtn_pct
        + COMPOSITE["W_DTI"] * dti_pct
        + COMPOSITE["W_RESP"] * resp_pct
    )
    penalty = min(
        COMPOSITE["DEVIATION_PENALTY_CAP"],
        COMPOSITE["MAJOR_DEVIATION_PENALTY"] * major_count
        + COMPOSITE["SENTINEL_DEVIATION_PENALTY"] * sentinel_count,
    )
    if included_abstraction_count >= COMPOSITE["VOLUME_TIER_HIGH"]:
        credit = COMPOSITE["VOLUME_CREDIT_HIGH"]
    elif included_abstraction_count >= COMPOSITE["VOLUME_TIER_MID"]:
        credit = COMPOSITE["VOLUME_CREDIT_MID"]
    else:
        credit = 0.0
    raw = (base - penalty + credit) * TIER_MULTIPLIER_BY_FACILITY_TYPE[facility_type]
    return round_half_up(min(100.0, max(0.0, raw)), 2)


def expected_decision_for_score(score: float) -> str:
    """PRD 3.9: CERTIFIED at 85.00 or above, CONDITIONAL from 70.00 up to but
    not including 85.00, DENIED below 70.00."""
    if score >= 85.00:
        return "CERTIFIED"
    if score >= 70.00:
        return "CONDITIONAL"
    return "DENIED"


def expected_rate(numerator: int, denominator: int) -> float:
    """PRD 3.9: 0.00 when the denominator is 0, otherwise 100 * numerator /
    denominator rounded to two decimals half up."""
    if denominator == 0:
        return 0.00
    return round_half_up(100.0 * numerator / denominator, 2)


def expected_mean_dtn_excess_pct(door_to_needle_minutes_list) -> float:
    """PRD 3.9: per-case excess over 60 minutes as a whole percent half up,
    then the mean of those whole percents rounded to two decimals half up."""
    if not door_to_needle_minutes_list:
        return None
    per_case = []
    for dtn in door_to_needle_minutes_list:
        excess = max(0, dtn - 60)
        per_case.append(round_half_up(100.0 * excess / 60.0, 0))
    return round_half_up(sum(per_case) / len(per_case), 2)


def expected_public_dtn_compliance_pct(dtn_60_compliance_pct: float) -> float:
    """PRD 3.9/2.6: the report's stored 2-decimal rate rounded to one decimal
    place half up."""
    return round_half_up(dtn_60_compliance_pct, 1)


__all__ = [name for name in dir() if name.startswith(("assert_", "expected_"))] + [
    "canonical_instant",
    "instants_equal",
    "round_half_up",
]
