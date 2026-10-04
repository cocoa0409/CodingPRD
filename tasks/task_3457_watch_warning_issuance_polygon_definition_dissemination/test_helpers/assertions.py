"""Entity assertions and domain invariant checkers.

``assert_<entity>(data)`` validates the shape of one resource body: the four
system-managed fields (``id`` a bare UUID, ``created_at``/``updated_at`` ISO
8601, integer ``version``) plus presence, type and enum membership of every
entity-specific field. Assertions only demand fields the PRD guarantees on the
resource; nullable lifecycle fields are type-checked only when non-null.

``validate_created`` is the explicit-201 wrapper around the framework success
validator: creation endpoints return 201 (PRD §4), and tests must never let a
create call slide through a 200 default.
"""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_success,
)

from .types import (
    AreaMethod,
    ChannelStatus,
    ChannelType,
    CoordinationRequestStatus,
    DamageThreat,
    DisseminationRecordStatus,
    EmergencyActionStatus,
    EmergencyActionType,
    ForecasterLevel,
    HazardType,
    JsonObject,
    MatchingVariant,
    PerformanceBand,
    PopulationTier,
    ProductLevel,
    ProductStatus,
    StormEventStatus,
    SupersedeReason,
    VerificationEventStatus,
    VerificationStatus,
)


def validate_created(response) -> JsonObject:
    """Assert the 201 a creation endpoint owes (PRD §4) and return the data."""
    return validate_success(response, 201)


def _assert_common_fields(data: JsonObject, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a bare UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601: {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601: {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer: {data.get('version')!r}"
    )


def _assert_nullable_timestamp(data: JsonObject, field: str, entity: str):
    value = data.get(field)
    assert value is None or is_iso8601_timestamp(value), (
        f"{entity}.{field} must be null or ISO 8601: {value!r}"
    )


def assert_forecast_office(data: JsonObject):
    _assert_common_fields(data, "ForecastOffice")
    assert isinstance(data["office_code"], str) and 2 <= len(data["office_code"]) <= 4
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region"], str) and data["region"]
    assert data["area_method"] in {m.value for m in AreaMethod}
    assert data["performance_band"] in {b.value for b in PerformanceBand}
    _assert_nullable_timestamp(data, "last_statistic_at", "ForecastOffice")


def assert_county_zone(data: JsonObject):
    _assert_common_fields(data, "CountyZone")
    assert isinstance(data["zone_code"], str) and data["zone_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert is_valid_uuid(data.get("office_id", "")), "CountyZone.office_id must be a UUID"
    assert data["lat_max"] > data["lat_min"], "northern boundary strictly north of southern"
    assert data["lon_max"] > data["lon_min"], "eastern boundary strictly east of western"
    assert data["surveyed_area_sq_km"] > 0
    assert data["population_tier"] in {t.value for t in PopulationTier}
    assert isinstance(data["coastal"], bool)


def assert_neighbor_agreement(data: JsonObject):
    _assert_common_fields(data, "NeighborAgreement")
    assert is_valid_uuid(data.get("office_a_id", "")), "office_a_id must be a UUID"
    assert is_valid_uuid(data.get("office_b_id", "")), "office_b_id must be a UUID"
    assert isinstance(data["hazard_types"], list) and data["hazard_types"]
    assert all(h in {t.value for t in HazardType} for h in data["hazard_types"])
    assert isinstance(data["coordination_timeout_minutes"], int)
    assert data["coordination_timeout_minutes"] > 0


def assert_alert_channel(data: JsonObject):
    _assert_common_fields(data, "AlertChannel")
    assert isinstance(data["name"], str) and data["name"]
    assert data["channel_type"] in {t.value for t in ChannelType}
    assert isinstance(data["supports_levels"], list) and data["supports_levels"]
    assert all(lvl in {p.value for p in ProductLevel} for lvl in data["supports_levels"])
    assert isinstance(data["max_message_chars"], int) and data["max_message_chars"] > 0
    if data["channel_type"] == ChannelType.WEA.value:
        assert data["max_message_chars"] <= 360, "WEA channels cap at the 360-char absolute maximum"
    assert isinstance(data["requires_confirmation"], bool)
    assert data["status"] in {s.value for s in ChannelStatus}


def assert_forecaster(data: JsonObject):
    _assert_common_fields(data, "Forecaster")
    assert is_valid_uuid(data.get("office_id", "")), "Forecaster.office_id must be a UUID"
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["employee_code"], str) and data["employee_code"]
    assert data["level"] in {lvl.value for lvl in ForecasterLevel}


def assert_storm_event(data: JsonObject):
    _assert_common_fields(data, "StormEvent")
    assert is_valid_uuid(data.get("office_id", "")), "StormEvent.office_id must be a UUID"
    assert data["hazard_type"] in {h.value for h in HazardType}
    assert isinstance(data["max_wind_mph"], int)
    assert isinstance(data["max_hail_inches"], (int, float))
    assert isinstance(data["rainfall_rate_in_hr"], (int, float))
    assert isinstance(data["rotation_couplet"], bool)
    assert isinstance(data["debris_signature"], bool)
    assert isinstance(data["motion_degrees"], int)
    assert isinstance(data["speed_kt"], int)
    assert is_iso8601_timestamp(data.get("detected_at", "")), "detected_at must be ISO 8601"
    assert data["status"] in {s.value for s in StormEventStatus}
    _assert_nullable_timestamp(data, "dissipated_at", "StormEvent")
    if data["status"] == StormEventStatus.DISSIPATED.value:
        assert data["dissipated_at"] is not None, "a DISSIPATED storm carries dissipated_at"


def assert_product(data: JsonObject):
    _assert_common_fields(data, "Product")
    assert data["product_level"] in {p.value for p in ProductLevel}
    assert data["hazard_type"] in {h.value for h in HazardType}
    assert is_valid_uuid(data.get("issuing_office_id", "")), "issuing_office_id must be a UUID"
    storm_id = data.get("storm_event_id")
    assert storm_id is None or is_valid_uuid(storm_id), "storm_event_id must be null or a UUID"
    zone_ids = data.get("zone_ids")
    assert zone_ids is None or isinstance(zone_ids, list)
    polygon = data.get("polygon")
    if polygon is not None:
        vertices = polygon.get("vertices", [])
        assert 3 <= len(vertices) <= 12, "a polygon carries between 3 and 12 vertices"
        for v in vertices:
            assert isinstance(v.get("lat"), (int, float)) and isinstance(v.get("lon"), (int, float))
    assert isinstance(data["resolved_zone_ids"], list)
    area = data.get("polygon_area_sq_km")
    assert area is None or isinstance(area, (int, float))
    assert data["damage_threat"] in {d.value for d in DamageThreat}
    assert isinstance(data["wea_360"], bool)
    assert data["wea_360"] == (data["damage_threat"] != DamageThreat.NONE.value), (
        "wea_360 is true exactly when damage_threat is not NONE"
    )
    _assert_nullable_timestamp(data, "effective_from", "Product")
    assert is_iso8601_timestamp(data.get("expires_at", "")), "expires_at must be ISO 8601"
    for field in ("issued_at", "cancelled_at", "superseded_at", "expired_at", "window_end"):
        _assert_nullable_timestamp(data, field, "Product")
    prior = data.get("supersedes_product_id")
    assert prior is None or is_valid_uuid(prior), "supersedes_product_id must be null or a UUID"
    reason = data.get("supersede_reason")
    assert reason is None or reason in {r.value for r in SupersedeReason}
    assert isinstance(data["coordination_required"], bool)
    assert isinstance(data["verified_event_count"], int) and data["verified_event_count"] >= 0
    assert data["verification_status"] in {s.value for s in VerificationStatus}
    assert data["status"] in {s.value for s in ProductStatus}


def assert_product_window_consistent(data: JsonObject):
    """window_end is the earliest non-null of cancelled_at / superseded_at /
    expires_at (PRD §3.4); the active window is [issued_at, window_end)."""
    candidates = [
        data.get("cancelled_at"),
        data.get("superseded_at"),
        data.get("expired_at"),
        data.get("expires_at"),
    ]
    present = [c for c in candidates if c is not None]
    expected = min(present) if present else None
    assert data.get("window_end") == expected, (
        f"window_end {data.get('window_end')!r} != earliest of {present!r}"
    )


def assert_coordination_request(data: JsonObject):
    _assert_common_fields(data, "CoordinationRequest")
    assert is_valid_uuid(data.get("product_id", "")), "product_id must be a UUID"
    assert is_valid_uuid(data.get("from_office_id", "")), "from_office_id must be a UUID"
    assert is_valid_uuid(data.get("to_office_id", "")), "to_office_id must be a UUID"
    assert data["hazard_type"] in {h.value for h in HazardType}
    assert data["status"] in {s.value for s in CoordinationRequestStatus}
    assert is_iso8601_timestamp(data.get("requested_at", "")), "requested_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("deadline_at", "")), "deadline_at must be ISO 8601"
    _assert_nullable_timestamp(data, "responded_at", "CoordinationRequest")


def assert_dissemination_record(data: JsonObject):
    _assert_common_fields(data, "DisseminationRecord")
    assert is_valid_uuid(data.get("product_id", "")), "product_id must be a UUID"
    assert is_valid_uuid(data.get("channel_id", "")), "channel_id must be a UUID"
    assert data["channel_type"] in {t.value for t in ChannelType}
    assert data["status"] in {s.value for s in DisseminationRecordStatus}
    assert isinstance(data["retry_count"], int) and 0 <= data["retry_count"] <= 3, (
        "retry_count stays within the three-attempt maximum"
    )
    assert is_iso8601_timestamp(data.get("queued_at", "")), "queued_at must be ISO 8601"
    _assert_nullable_timestamp(data, "sent_at", "DisseminationRecord")
    _assert_nullable_timestamp(data, "confirmed_at", "DisseminationRecord")


def assert_verification_event(data: JsonObject):
    _assert_common_fields(data, "VerificationEvent")
    assert is_valid_uuid(data.get("zone_id", "")), "zone_id must be a UUID"
    storm_id = data.get("storm_event_id")
    assert storm_id is None or is_valid_uuid(storm_id), "storm_event_id must be null or a UUID"
    assert data["hazard_type"] in {h.value for h in HazardType}
    assert is_iso8601_timestamp(data.get("observed_at", "")), "observed_at must be ISO 8601"
    assert isinstance(data["location_lat"], (int, float))
    assert isinstance(data["location_lon"], (int, float))
    assert isinstance(data["magnitude"], str)
    assert data["status"] in {s.value for s in VerificationEventStatus}
    assert isinstance(data["matched_product_ids"], list)
    _assert_nullable_timestamp(data, "adjudicated_at", "VerificationEvent")


def assert_verification_statistic(data: JsonObject):
    _assert_common_fields(data, "VerificationStatistic")
    assert is_valid_uuid(data.get("office_id", "")), "office_id must be a UUID"
    assert data["hazard_type"] in {h.value for h in HazardType}
    assert is_iso8601_timestamp(data.get("period_start", "")), "period_start must be ISO 8601"
    assert is_iso8601_timestamp(data.get("period_end", "")), "period_end must be ISO 8601"
    assert data["matching_variant"] in {v.value for v in MatchingVariant}
    for field in ("total_warnings", "events_total", "events_warned", "events_unwarned", "false_alarms"):
        assert isinstance(data[field], int) and data[field] >= 0, f"{field} must be a non-negative integer"
    assert data["events_unwarned"] == data["events_total"] - data["events_warned"]
    for field in ("pod", "far", "avg_lead_time_minutes"):
        value = data.get(field)
        assert value is None or isinstance(value, (int, float)), f"{field} must be null or numeric"
    assert is_iso8601_timestamp(data.get("computed_at", "")), "computed_at must be ISO 8601"


def assert_emergency_action(data: JsonObject):
    _assert_common_fields(data, "EmergencyAction")
    assert is_valid_uuid(data.get("zone_id", "")), "zone_id must be a UUID"
    assert is_valid_uuid(data.get("product_id", "")), "product_id must be a UUID"
    assert data["action_type"] in {t.value for t in EmergencyActionType}
    assert is_iso8601_timestamp(data.get("effective_from", "")), "effective_from must be ISO 8601"
    assert is_iso8601_timestamp(data.get("effective_until", "")), "effective_until must be ISO 8601"
    assert data["effective_until"] > data["effective_from"], "the window end lies strictly after the start"
    assert data["status"] in {s.value for s in EmergencyActionStatus}
    assert isinstance(data["decided_by"], str) and data["decided_by"], (
        "decided_by records the creating manager's X-User-ID"
    )
    _assert_nullable_timestamp(data, "ordered_at", "EmergencyAction")
    _assert_nullable_timestamp(data, "lifted_at", "EmergencyAction")


def assert_wea_preview(data: JsonObject):
    """The read-only WEA preview body (PRD §3.6)."""
    assert isinstance(data["message"], str)
    assert isinstance(data["included_zone_ids"], list)
    assert isinstance(data["dropped_zone_ids"], list)
    assert isinstance(data["char_count"], int)
    assert data["char_count"] == len(data["message"]), "char_count is the exact message length"
    assert isinstance(data["would_overflow"], bool)


__all__ = [
    "validate_created",
    "assert_forecast_office",
    "assert_county_zone",
    "assert_neighbor_agreement",
    "assert_alert_channel",
    "assert_forecaster",
    "assert_storm_event",
    "assert_product",
    "assert_product_window_consistent",
    "assert_coordination_request",
    "assert_dissemination_record",
    "assert_verification_event",
    "assert_verification_statistic",
    "assert_emergency_action",
    "assert_wea_preview",
]
