"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    """Primary resources carry id/created_at/updated_at/version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"version must be an integer, got {data.get('version')!r}"
    )


def _assert_append_only_fields(data: dict):
    """Append-only records carry only id + created_at; updated_at/version absent
    (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )


def assert_timestamp_matches_instant(actual: str, expected_iso: str):
    """A clock-stamped field equals the logical clock instant, tolerant of the
    optional three-fractional-digit rendering (PRD §2.4/§2.5)."""
    norm = actual.replace(".000Z", "Z") if isinstance(actual, str) else actual
    assert norm == expected_iso, f"Expected instant {expected_iso}, got {actual!r}"


def assert_launch_site(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["surface_wind_limit_kts"], int)
    assert isinstance(data["aloft_wind_limit_kts"], int)
    assert isinstance(data["per_use_fee_cents"], int)
    assert data["permission_status"] in ("PENDING", "GRANTED", "REVOKED")
    assert data.get("permission_granted_at") is None or is_iso8601_timestamp(
        data["permission_granted_at"]
    )
    assert isinstance(data["permission_expires_on"], str)


def assert_balloon(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["registration"], str) and data["registration"]
    assert isinstance(data["basket_capacity_passengers"], int)
    assert isinstance(data["max_gross_weight_lbs"], int)
    assert isinstance(data["empty_weight_lbs"], int)
    assert data["status"] in ("ACTIVE", "GROUNDED")
    assert data.get("last_inspection_on") is None or isinstance(
        data["last_inspection_on"], str
    )
    assert data.get("inspection_due_on") is None or isinstance(
        data["inspection_due_on"], str
    )


def assert_pilot(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["certificate_number"], str) and data["certificate_number"]
    assert isinstance(data["medical_expires_on"], str)
    assert isinstance(data["external_pic_hours_180d"], (int, float))
    assert isinstance(data["external_takeoffs_landings_90d"], int)
    assert isinstance(data["internal_pic_hours_180d"], (int, float))
    assert isinstance(data["internal_takeoffs_landings_90d"], int)
    assert isinstance(data["pic_hours_180d_total"], (int, float))
    assert isinstance(data["takeoffs_landings_90d_total"], int)
    assert isinstance(data["faa_currency_met"], bool)
    assert isinstance(data["operator_currency_met"], bool)
    assert data["currency_status"] in ("CURRENT", "EXPIRED")


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["wallet_credit_cents"], int)


def assert_flight(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["scheduled_date"], str)
    assert is_iso8601_timestamp(data["dawn_window_start"])
    assert is_iso8601_timestamp(data["dawn_window_end"])
    assert is_valid_uuid(data["launch_site_id"])
    assert is_valid_uuid(data["balloon_id"])
    assert is_valid_uuid(data["pilot_id"])
    assert data["kind"] in ("SHARED", "CHARTER")
    assert isinstance(data["fuel_lbs"], int)
    assert data["status"] in (
        "DRAFT", "SCHEDULED", "WEATHER_REVIEW", "CLEARED_FOR_LAUNCH",
        "AIRBORNE", "LANDED", "CLOSED", "NO_GO", "CANCELLED",
    )
    assert data["season_tier"] in ("PEAK", "REGULAR")
    assert isinstance(data["seats_sold"], int)
    assert isinstance(data["seats_available"], int)
    assert isinstance(data["payload_used_lbs"], int)
    assert data["weather_decision"] in ("NONE", "GO", "NO_GO")
    assert data.get("weather_decision_at") is None or is_iso8601_timestamp(
        data["weather_decision_at"]
    )
    assert data.get("cancel_reason") in (None, "WEATHER", "AIRCRAFT", "OPERATOR")
    assert data.get("duration_hours") is None or isinstance(
        data["duration_hours"], (int, float)
    )


def assert_reservation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["flight_id"])
    assert is_valid_uuid(data["customer_id"])
    assert isinstance(data["party_size"], int) and data["party_size"] >= 1
    assert isinstance(data["declared_weight_lbs"], int)
    assert data["photo_package_tier"] in ("NONE", "STANDARD", "DELUXE")
    assert data["booking_status"] in (
        "PENDING", "CONFIRMED", "CHECKED_IN", "FLOWN", "COMPLETED", "CANCELLED",
    )
    assert data["payment_status"] in (
        "UNPAID", "PAID", "PARTIALLY_REFUNDED", "REFUNDED",
    )
    assert isinstance(data["quoted_fare_cents"], int)
    assert data.get("final_fare_cents") is None or isinstance(data["final_fare_cents"], int)
    assert isinstance(data["paid_cents"], int)
    assert isinstance(data["refunded_cents"], int)
    assert isinstance(data["goodwill_credit_cents"], int)
    assert isinstance(data["retained_revenue_cents"], int)
    assert data.get("cancel_reason") in (
        None, "WEATHER_CANCEL", "OPERATOR_CANCEL",
        "CUSTOMER_CANCEL_EARLY", "CUSTOMER_CANCEL_LATE",
    )


def assert_passenger(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data["reservation_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["weight_lbs"], int)
    assert isinstance(data.get("is_minor", False), bool)


def assert_weather_briefing(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data["flight_id"])
    assert is_iso8601_timestamp(data["observed_at"])
    assert isinstance(data["surface_wind_kts"], int)
    assert isinstance(data["aloft_wind_kts"], int)
    assert isinstance(data["visibility_mi"], (int, float))
    assert isinstance(data["precipitation"], bool)
    assert data["decision"] in ("GO", "NO_GO")
    assert data["status"] in ("RECORDED", "SUPERSEDED")


def assert_chase_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["flight_id"])
    assert isinstance(data["crew_lead_name"], str) and data["crew_lead_name"]
    assert isinstance(data["vehicle_id"], str) and data["vehicle_id"]
    assert isinstance(data["crew_size"], int)
    assert data["status"] in (
        "ASSIGNED", "EN_ROUTE", "AT_LANDING", "RECOVERED", "DEBRIEFED",
    )
    assert data.get("landing_lat") is None or isinstance(data["landing_lat"], (int, float))
    assert data.get("landing_lon") is None or isinstance(data["landing_lon"], (int, float))


def assert_refund(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["reservation_id"])
    assert data["reason"] in (
        "WEATHER_CANCEL", "OPERATOR_CANCEL",
        "CUSTOMER_CANCEL_EARLY", "CUSTOMER_CANCEL_LATE",
    )
    assert isinstance(data["requested_amount_cents"], int)
    assert data.get("approved_amount_cents") is None or isinstance(
        data["approved_amount_cents"], int
    )
    assert data["status"] in ("REQUESTED", "APPROVED", "PAID", "DENIED")
    assert data.get("paid_via") in (None, "ORIGINAL_PAYMENT", "WALLET_CREDIT")
    assert data.get("paid_at") is None or is_iso8601_timestamp(data["paid_at"])


def assert_photo_package_record(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data["reservation_id"])
    assert data["tier"] in ("STANDARD", "DELUXE")
    assert isinstance(data["photo_count"], int)
    assert data["status"] in ("PENDING", "DELIVERED")
    assert data.get("delivered_at") is None or is_iso8601_timestamp(data["delivered_at"])


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------

def assert_seat_inventory(flight: dict, balloon: dict):
    """seats_sold + seats_available == basket_capacity_passengers (PRD §3.4)."""
    assert flight["seats_sold"] + flight["seats_available"] == (
        balloon["basket_capacity_passengers"]
    ), (
        f"Seat inventory leaked: seats_sold {flight['seats_sold']} + "
        f"seats_available {flight['seats_available']} != capacity "
        f"{balloon['basket_capacity_passengers']}"
    )


def assert_payment_conservation(reservation: dict):
    """paid_cents == refunded_cents + retained_revenue_cents (PRD §3.7)."""
    assert reservation["refunded_cents"] + reservation["retained_revenue_cents"] == (
        reservation["paid_cents"]
    ), (
        f"Money not conserved: refunded {reservation['refunded_cents']} + retained "
        f"{reservation['retained_revenue_cents']} != paid {reservation['paid_cents']}"
    )
