"""Entity assertions and harbor-ledger invariant checkers."""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

from .types import (
    BookingStatus,
    CrewStatus,
    DockFeeStatus,
    DockSlotPurpose,
    DockSlotStatus,
    EndorsementClass,
    HullClass,
    InspectionResult,
    InspectionType,
    InterruptionStatus,
    Posture,
    RedemptionStatus,
    RefundClaimStatus,
    RidePassStatus,
    ServiceMode,
    SurgeTier,
    TripOperationalStatus,
    TripSettlementStatus,
    VesselServiceState,
    ZoneTier,
)

_ENUM_VALUES = {e: [m.value for m in e] for e in (
    BookingStatus, CrewStatus, DockFeeStatus, DockSlotPurpose, DockSlotStatus,
    EndorsementClass, HullClass, InspectionResult, InspectionType,
    InterruptionStatus, Posture, RedemptionStatus, RefundClaimStatus,
    RidePassStatus, ServiceMode, SurgeTier, TripOperationalStatus,
    TripSettlementStatus, VesselServiceState, ZoneTier,
)}


def _assert_identity(data: dict, name: str) -> None:
    assert is_valid_uuid(data.get("id", "")), f"{name}.id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{name}.created_at must be an ISO 8601 UTC timestamp, got {data.get('created_at')!r}"
    )


def _assert_versioned(data: dict, name: str) -> None:
    """Resources that carry the full common-field set."""
    _assert_identity(data, name)
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{name}.updated_at must be an ISO 8601 UTC timestamp, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{name}.version must be an integer starting at 1, got {data.get('version')!r}"
    )


def _assert_enum(data: dict, field: str, enum_cls, name: str) -> None:
    assert data.get(field) in _ENUM_VALUES[enum_cls], (
        f"{name}.{field} must be one of {_ENUM_VALUES[enum_cls]}, got {data.get(field)!r}"
    )


# --- Per-entity assertions ------------------------------------------------

def assert_dock(data: dict) -> None:
    _assert_versioned(data, "Dock")
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 80
    for field in ("berth_count", "min_turnaround_minutes", "landing_fee_per_pax_cents",
                  "berth_minute_rate_cents", "monthly_fee_cap_cents",
                  "shared_operator_count", "accrued_fee_cents"):
        assert isinstance(data[field], int), f"Dock.{field} must be an integer"
    assert data["berth_count"] >= 1
    assert data["accrued_fee_cents"] >= 0
    _assert_enum(data, "fee_status", DockFeeStatus, "Dock")


def assert_stop(data: dict) -> None:
    _assert_versioned(data, "Stop")
    assert is_valid_uuid(data.get("dock_id", "")), "Stop.dock_id must be a UUID"
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 80
    assert isinstance(data["zone_index"], int) and 1 <= data["zone_index"] <= 6
    assert float(data["charted_depth_m"]) >= 0.0


def assert_vessel(data: dict) -> None:
    _assert_versioned(data, "Vessel")
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 80
    assert isinstance(data["seat_capacity"], int) and data["seat_capacity"] >= 1
    assert float(data["draft_m"]) > 0.0
    _assert_enum(data, "hull_class", HullClass, "Vessel")
    _assert_enum(data, "required_endorsement", EndorsementClass, "Vessel")
    _assert_enum(data, "service_state", VesselServiceState, "Vessel")


def assert_vessel_inspection(data: dict) -> None:
    """An inspection is an immutable event record: id and created_at only."""
    _assert_identity(data, "VesselInspection")
    assert "updated_at" not in data, "VesselInspection must not carry updated_at"
    assert "version" not in data, "VesselInspection must not carry version"
    assert is_valid_uuid(data.get("vessel_id", "")), "VesselInspection.vessel_id must be a UUID"
    _assert_enum(data, "inspection_type", InspectionType, "VesselInspection")
    _assert_enum(data, "result", InspectionResult, "VesselInspection")
    assert isinstance(data["deficiency_count"], int) and data["deficiency_count"] >= 0
    assert isinstance(data["performed_on"], str)
    assert isinstance(data.get("inspector_user_id"), str) and data["inspector_user_id"]


def assert_crew_member(data: dict) -> None:
    _assert_versioned(data, "CrewMember")
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 80
    _assert_enum(data, "endorsement_class", EndorsementClass, "CrewMember")
    _assert_enum(data, "status", CrewStatus, "CrewMember")
    assert isinstance(data["cert_expires_on"], str)
    assert isinstance(data["medical_expires_on"], str)
    assert isinstance(data["trips_mastered_count"], int) and data["trips_mastered_count"] >= 0


def assert_service_day(data: dict) -> None:
    _assert_versioned(data, "ServiceDay")
    assert isinstance(data["service_date"], str)
    assert float(data["wind_knots"]) >= 0.0
    assert float(data["wave_height_m"]) >= 0.0
    assert float(data["low_water_m"]) >= 0.0
    assert isinstance(data["manual_suspension"], bool)
    assert isinstance(data["expected_attendance"], int) and data["expected_attendance"] >= 0
    _assert_enum(data, "posture", Posture, "ServiceDay")
    _assert_enum(data, "surge_tier", SurgeTier, "ServiceDay")
    assert data["surge_multiplier_bp"] in (10000, 12500, 15000)
    assert data["planned_extra_vessels"] in (0, 1, 2)


def assert_trip(data: dict) -> None:
    _assert_versioned(data, "Trip")
    for fk in ("service_day_id", "vessel_id", "master_crew_id", "origin_stop_id",
               "destination_stop_id"):
        assert is_valid_uuid(data.get(fk, "")), f"Trip.{fk} must be a UUID"
    _assert_enum(data, "service_mode", ServiceMode, "Trip")
    _assert_enum(data, "operational_status", TripOperationalStatus, "Trip")
    _assert_enum(data, "settlement_status", TripSettlementStatus, "Trip")
    for field in ("effective_capacity", "seats_committed", "booked_pax", "boarded_pax",
                  "provisional_fee_cents", "final_fee_cents"):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"Trip.{field} must be a non-negative integer, got {data.get(field)!r}"
        )
    assert isinstance(data["scheduled_departure_utc"], str)
    assert isinstance(data["scheduled_arrival_utc"], str)


def assert_dock_slot(data: dict) -> None:
    _assert_versioned(data, "DockSlot")
    assert is_valid_uuid(data.get("dock_id", "")), "DockSlot.dock_id must be a UUID"
    assert is_valid_uuid(data.get("trip_id", "")), "DockSlot.trip_id must be a UUID"
    _assert_enum(data, "purpose", DockSlotPurpose, "DockSlot")
    _assert_enum(data, "status", DockSlotStatus, "DockSlot")
    for field in ("pax_basis", "berth_minutes", "rebate_bp", "projected_fee_cents",
                  "landing_fee_cents"):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"DockSlot.{field} must be a non-negative integer, got {data.get(field)!r}"
        )


def assert_ride_pass(data: dict) -> None:
    _assert_versioned(data, "RidePass")
    assert isinstance(data.get("rider_user_id"), str) and data["rider_user_id"]
    _assert_enum(data, "zone_tier", ZoneTier, "RidePass")
    _assert_enum(data, "status", RidePassStatus, "RidePass")
    assert isinstance(data["rides_purchased"], int) and data["rides_purchased"] >= 1
    for field in ("rides_remaining", "rides_consumed", "purchase_price_cents",
                  "refund_amount_cents"):
        assert isinstance(data[field], int) and data[field] >= 0
    assert data["refund_basis"] in (None, "PRO_RATA", "DIFFERENTIAL")


def assert_booking(data: dict) -> None:
    _assert_versioned(data, "Booking")
    assert isinstance(data.get("rider_user_id"), str) and data["rider_user_id"]
    for fk in ("origin_stop_id", "destination_stop_id"):
        assert is_valid_uuid(data.get(fk, "")), f"Booking.{fk} must be a UUID"
    _assert_enum(data, "service_mode", ServiceMode, "Booking")
    _assert_enum(data, "status", BookingStatus, "Booking")
    _assert_enum(data, "redemption_status", RedemptionStatus, "Booking")
    assert isinstance(data["party_size"], int) and 1 <= data["party_size"] <= 12
    assert isinstance(data["offer_round"], int) and 0 <= data["offer_round"] <= 3
    assert isinstance(data["declined_trip_ids"], list)
    for field in ("fare_quoted_cents", "fare_charged_cents", "fare_refunded_cents",
                  "credit_refunded_cents"):
        assert isinstance(data[field], int) and data[field] >= 0
    assert data["interrupted_from_status"] in (None, "OFFERED", "CONFIRMED", "BOARDED")


def assert_service_interruption(data: dict) -> None:
    _assert_versioned(data, "ServiceInterruption")
    assert is_valid_uuid(data.get("service_day_id", "")), (
        "ServiceInterruption.service_day_id must be a UUID"
    )
    assert data["cause"] in ("WEATHER", "TIDE", "MECHANICAL", "DOCK_CLOSURE")
    _assert_enum(data, "status", InterruptionStatus, "ServiceInterruption")
    assert isinstance(data.get("declared_by_user_id"), str) and data["declared_by_user_id"]
    assert isinstance(data["affected_booking_count"], int) and data["affected_booking_count"] >= 0
    assert isinstance(data["total_provisional_refund_cents"], int)


def assert_refund_claim(data: dict) -> None:
    _assert_versioned(data, "RefundClaim")
    assert is_valid_uuid(data.get("booking_id", "")), "RefundClaim.booking_id must be a UUID"
    assert is_valid_uuid(data.get("service_interruption_id", "")), (
        "RefundClaim.service_interruption_id must be a UUID"
    )
    assert isinstance(data.get("declarer_user_id"), str) and data["declarer_user_id"]
    _assert_enum(data, "status", RefundClaimStatus, "RefundClaim")
    for field in ("entitlement_cents", "cash_refund_cents", "credit_refund_cents"):
        assert isinstance(data[field], int) and data[field] >= 0
    assert isinstance(data["ride_restored"], bool)


# --- Conserved-quantity invariants (PRD 2.9) -------------------------------

def assert_dock_fee_conservation(api, dock_id, headers) -> None:
    """A dock's accrued_fee_cents equals the sum of landing_fee_cents over its
    CONSUMED slots plus projected_fee_cents over its RESERVED slots."""
    dock = validate_success(api.get_dock(dock_id, headers))
    slots, _meta = validate_paginated(
        api.list_dock_slots(headers, params={"dock_id": dock_id, "limit": 100})
    )
    expected = sum(s["landing_fee_cents"] for s in slots if s["status"] == "CONSUMED")
    expected += sum(s["projected_fee_cents"] for s in slots if s["status"] == "RESERVED")
    assert dock["accrued_fee_cents"] == expected, (
        f"Dock accrual {dock['accrued_fee_cents']} != CONSUMED landing fees + "
        f"RESERVED projected fees ({expected})"
    )


def assert_ride_credit_conservation(api, ride_pass_id, headers) -> None:
    """rides_purchased == rides_remaining + sum(party_size over REDEEMED bookings)."""
    ride_pass = validate_success(api.get_ride_pass(ride_pass_id, headers))
    bookings, _meta = validate_paginated(
        api.list_bookings(headers, params={"ride_pass_id": ride_pass_id, "limit": 100})
    )
    redeemed = sum(b["party_size"] for b in bookings if b["redemption_status"] == "REDEEMED")
    assert ride_pass["rides_purchased"] == ride_pass["rides_remaining"] + redeemed, (
        f"rides_purchased {ride_pass['rides_purchased']} != rides_remaining "
        f"{ride_pass['rides_remaining']} + redeemed {redeemed}"
    )


def assert_seat_commitment(api, trip_id, headers) -> None:
    """A trip's seats_committed equals the sum of party_size over its bookings in
    CONFIRMED or BOARDED."""
    trip = validate_success(api.get_trip(trip_id, headers))
    bookings, _meta = validate_paginated(
        api.list_bookings(headers, params={"trip_id": trip_id, "limit": 100})
    )
    committed = sum(b["party_size"] for b in bookings
                    if b["status"] in ("CONFIRMED", "BOARDED"))
    assert trip["seats_committed"] == committed, (
        f"seats_committed {trip['seats_committed']} != sum of party_size over "
        f"CONFIRMED/BOARDED bookings ({committed})"
    )
