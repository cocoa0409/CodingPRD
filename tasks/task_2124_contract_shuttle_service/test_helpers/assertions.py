"""Entity assertions and domain invariant checkers for the shuttle service API."""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import LAYOVER_BUFFER_MIN

CONTRACT_STATUSES = ["DRAFT", "ACTIVE", "RENEWAL_PENDING", "RENEWED", "TERMINATED"]
ROUTE_STATUSES = ["DRAFT", "PUBLISHED", "DEGRADED", "RETIRED"]
VEHICLE_STATUSES = ["AVAILABLE", "IN_MAINTENANCE", "RETIRED"]
DISPATCH_STATUSES = [
    "SCHEDULED", "ASSIGNED", "IN_SERVICE", "COMPLETED", "MISSED", "CANCELLED",
]
SETTLEMENT_STATUSES = ["UNBILLED", "BILLED", "CREDITED", "WAIVED"]
REQUEST_STATUSES = ["PENDING", "MATCHED", "SERVED", "DENIED", "EXPIRED"]
REPORT_STATUSES = ["DRAFT", "SUBMITTED", "DISPUTED", "APPROVED"]
MEMO_STATUSES = ["ISSUED", "APPLIED", "VOIDED"]
OFFER_STATUSES = ["OPEN", "COUNTERED", "ACCEPTED", "DECLINED", "SUPERSEDED"]


def assert_identity_and_audit(data: dict) -> None:
    """Every resource carries a bare UUID `id` and an ISO 8601 `created_at`."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be an ISO 8601 UTC timestamp, got {data.get('created_at')!r}"
    )


def assert_versioned(data: dict) -> None:
    """Most resources additionally carry `updated_at` and an integer `version`."""
    assert_identity_and_audit(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be an ISO 8601 UTC timestamp, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_contract(data: dict) -> None:
    assert_versioned(data)
    assert isinstance(data["client_name"], str) and 1 <= len(data["client_name"]) <= 120
    assert data["site_type"] in ["HOTEL", "CAMPUS", "CORPORATE"]
    assert isinstance(data["base_rate_cents_per_service_hour"], int)
    assert data["base_rate_cents_per_service_hour"] >= 1
    assert data["status"] in CONTRACT_STATUSES
    assert isinstance(data["credit_balance_cents"], int)
    assert isinstance(data["branded_vehicle_count"], int)
    assert isinstance(data["branded_ada_vehicle_count"], int)
    assert data["term_end_date"] >= data["term_start_date"]


def assert_route(data: dict) -> None:
    assert_versioned(data)
    assert data["status"] in ROUTE_STATUSES
    assert 1 <= data["loop_minutes"] <= 1440
    assert 1 <= data["headway_minutes"] <= 720
    assert 0 <= data["service_window_start_min"] <= 1439
    assert 0 <= data["service_window_end_min"] <= 1439
    assert data["service_window_end_min"] >= data["service_window_start_min"]
    assert isinstance(data["required_vehicle_count"], int)
    assert isinstance(data["ada_required_count"], int)


def assert_vehicle(data: dict) -> None:
    assert_versioned(data)
    assert data["status"] in VEHICLE_STATUSES
    assert isinstance(data["fleet_code"], str) and 1 <= len(data["fleet_code"]) <= 40
    assert data["seat_capacity"] >= 1
    assert isinstance(data["is_ada_accessible"], bool)
    assert data["odometer_km"] >= 0
    assert data["service_interval_km"] >= 1
    assert isinstance(data["committed_block_minutes"], int)
    assert data["committed_block_minutes"] >= 0


def assert_driver(data: dict) -> None:
    assert_versioned(data)
    assert data["license_class"] in ["CDL_B", "CDL_C"]
    assert isinstance(data["ada_certified"], bool)
    assert 1 <= data["max_duty_minutes_per_day"] <= 1440
    assert isinstance(data["assigned_duty_minutes_current_date"], int)
    assert data["assigned_duty_minutes_current_date"] >= 0


def assert_trip(data: dict) -> None:
    assert_versioned(data)
    assert data["dispatch_status"] in DISPATCH_STATUSES
    assert data["settlement_status"] in SETTLEMENT_STATUSES
    assert 0 <= data["scheduled_departure_min"] <= 1439
    assert data["scheduled_arrival_min"] >= data["scheduled_departure_min"]
    assert isinstance(data["counted_boardings"], int)
    assert isinstance(data["counted_ada_boardings"], int)
    assert isinstance(data["matched_party_seats"], int)


def assert_ridership_count(data: dict) -> None:
    """A ridership row is append-only: id and created_at only."""
    assert_identity_and_audit(data)
    assert "updated_at" not in data, "a ridership count row has no updated_at field"
    assert "version" not in data, "a ridership count row has no version field"
    assert data["source"] in ["DRIVER_TALLY", "APC_SENSOR"]
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
    assert data["boarded"] >= 0
    assert data["alighted"] >= 0
    assert 0 <= data["ada_boardings"] <= data["boarded"]


def assert_on_demand_request(data: dict) -> None:
    assert_versioned(data)
    assert data["status"] in REQUEST_STATUSES
    assert data["party_size"] >= 1
    assert 0 <= data["requested_pickup_min"] <= 1439
    assert isinstance(data["requires_ada"], bool)


def assert_maintenance_order(data: dict) -> None:
    assert_versioned(data)
    assert data["status"] in ["OPEN", "CLOSED"]
    assert data["kind"] in ["PREVENTIVE", "CORRECTIVE", "BRANDING_WRAP"]
    assert data["window_end_min"] >= data["window_start_min"]
    assert isinstance(data["displaced_trip_count"], int)


def assert_report(data: dict) -> None:
    assert_versioned(data)
    assert data["status"] in REPORT_STATUSES
    assert data["settlement_variant"] in ["NONE", "PROVISIONAL", "FINAL"]
    assert isinstance(data["revision_round"], int)
    assert data["period_end_date"] >= data["period_start_date"]


def assert_credit_memo(data: dict) -> None:
    assert_versioned(data)
    assert data["status"] in MEMO_STATUSES
    assert data["reason"] in ["MISSED_TRIP", "WAIT_SLA_BREACH", "GOODWILL"]
    assert data["amount_cents"] >= 1


def assert_renewal_offer(data: dict) -> None:
    assert_versioned(data)
    assert data["status"] in OFFER_STATUSES
    assert 1 <= data["proposed_term_months"] <= 60
    assert isinstance(data["round_index"], int) and data["round_index"] >= 1


# ─── Domain invariants ────────────────────────────────────────────────────────

def assert_credit_balance_matches_issued_memos(contract: dict, memos: list) -> None:
    """`credit_balance_cents` is the sum of `amount_cents` over the contract's
    memos whose `status` is `ISSUED`."""
    expected = sum(m["amount_cents"] for m in memos if m["status"] == "ISSUED")
    assert contract["credit_balance_cents"] == expected, (
        f"credit_balance_cents {contract['credit_balance_cents']} does not equal the "
        f"{expected}-cent sum over ISSUED memos"
    )


def assert_committed_block_matches_trips(vehicle: dict, trips: list) -> None:
    """`committed_block_minutes` is the sum, over the vehicle's ASSIGNED,
    IN_SERVICE and COMPLETED trips, of the scheduled duration plus the layover
    buffer."""
    expected = sum(
        (t["scheduled_arrival_min"] - t["scheduled_departure_min"]) + LAYOVER_BUFFER_MIN
        for t in trips
        if t.get("vehicle_id") == vehicle["id"]
        and t["dispatch_status"] in ("ASSIGNED", "IN_SERVICE", "COMPLETED")
    )
    assert vehicle["committed_block_minutes"] == expected, (
        f"committed_block_minutes {vehicle['committed_block_minutes']} does not equal "
        f"the recomputed {expected}"
    )


def assert_duty_minutes_match_trips(driver: dict, trips: list, service_date: str) -> None:
    """`assigned_duty_minutes_current_date` is the wheels-turning sum over the
    driver's ASSIGNED, IN_SERVICE and COMPLETED trips on the clock's date."""
    expected = sum(
        t["scheduled_arrival_min"] - t["scheduled_departure_min"]
        for t in trips
        if t.get("driver_id") == driver["id"]
        and t["service_date"] == service_date
        and t["dispatch_status"] in ("ASSIGNED", "IN_SERVICE", "COMPLETED")
    )
    assert driver["assigned_duty_minutes_current_date"] == expected, (
        f"assigned_duty_minutes_current_date {driver['assigned_duty_minutes_current_date']} "
        f"does not equal the recomputed {expected}"
    )


def assert_settlement_block_zeroed(report: dict) -> None:
    """Every settlement figure returns to 0 when a report is disputed."""
    for field in [
        "scheduled_trip_count", "completed_trip_count", "missed_trip_count",
        "waived_trip_count", "countable_trip_count", "on_time_trip_count",
        "on_time_pct", "total_boardings", "total_ada_boardings",
        "total_billable_minutes", "billable_service_hours", "gross_amount_cents",
        "penalty_tier_pct", "sla_penalty_cents", "missed_trip_penalty_cents",
        "penalty_amount_cents", "credit_amount_cents", "net_amount_cents",
    ]:
        assert report[field] == 0, f"{field} must return to 0 on dispute, got {report[field]}"
