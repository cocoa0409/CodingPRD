"""Domain thresholds and payload factories.

Every constant here is a numeric value the PRD names in prose; every factory
emits the input fields one create operation declares.
"""
import uuid

# ---------------------------------------------------------------------------
# Constants named in the PRD
# ---------------------------------------------------------------------------

CAREGIVER_EXPERIENCE_MIN_MONTHS = 12
SEAT_CAPACITY_MAX = 10
ACADEMIC_TERM_OPEN_DATE = "2026-08-15"

QUOTE_DISCREPANCY_DISCOUNT = 0.25
FINAL_LOCKED_DISCOUNT = 0.5
CREDIT_APPLY_PCT = 0.5

STRIKE_MEDIUM_MIN = 1
STRIKE_HIGH_MIN = 3
DRIVER_SUSPENSION_STRIKE_THRESHOLD = 3
BREACH_MEDIUM_MIN = 2

WAIT_BLOCK_MINUTES = 12
WAIT_BLOCK_MAX = 5
WAIT_TIME_MIN_BLOCKS = 2

LATE_DISPATCH_DISCOUNT = 0.5
NORMAL_MULTIPLIER = 1.0
PENALTY_MULTIPLIER = 1.5
GRADE_HIGH_MIN = 8.0
GRADE_MEDIUM_MIN = 4.0

PROXIMITY_FACTOR = 1.1
PIN_LENGTH = 6
MAX_HANDOFF_ATTEMPTS = 2

SUPPLY_STAFFED_RATIO = 0.8
SERIES_OVERLAP_BUFFER_MINUTES = 0
AVAILABILITY_BUFFER_MINUTES = 20

DEFAULT_CLOCK = "2026-09-01T00:00:00Z"
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100

PROGRAM_WEIGHT = {
    "FOSTER_CARE": 3.0,
    "HOMELESS_MCKINNEY_VENTO": 3.0,
    "SPECIAL_EDUCATION": 2.0,
    "GENERAL": 1.0,
}

# Standard fixture commercial terms used across the suite.
STANDARD_PER_RIDE_CENTS = 5300
STANDARD_PER_MILE_CENTS = 215
STANDARD_MINIMUM_BILLABLE_CENTS = 800

NON_EXISTENT_RIDER_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


def unique_ref(prefix: str = "ref") -> str:
    """A short unique reference code, safe for repeated runs."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Payload factories
# ---------------------------------------------------------------------------

def create_district_payload(**overrides) -> dict:
    payload = {
        "name": "Aldine ISD",
        "billing_email": "ap@aldine.example",
        "contract_rate_per_ride_cents": STANDARD_PER_RIDE_CENTS,
        "contract_rate_per_mile_cents": STANDARD_PER_MILE_CENTS,
    }
    payload.update(overrides)
    return payload


def create_rider_payload(district_id: str, **overrides) -> dict:
    payload = {
        "district_id": district_id,
        "full_name": "Ana Ruiz",
        "date_of_birth": "2014-04-02",
        "program_type": "GENERAL",
        "spi_level": 1,
        "home_address": "12 Oak St",
        "school_name": "Lincoln Elementary",
        "emergency_contact_phone": "5550101",
        "authorized_adults": [],
        "notify_on_pickup": True,
        "notify_on_dropoff": True,
    }
    payload.update(overrides)
    return payload


def create_driver_payload(**overrides) -> dict:
    payload = {
        "full_name": "Dee Alvarez",
        "phone": "5550111",
        "employer_org": "CareGo",
        "caregiver_experience_months": 18,
        "language_codes": ["en"],
        "vehicle_class": "SUV",
        "seat_capacity": 6,
        "child_seat_type": "BOOSTER",
    }
    payload.update(overrides)
    return payload


def create_background_check_payload(**overrides) -> dict:
    payload = {
        "check_type": "FINGERPRINT_FBI",
        "reference_code": unique_ref("FBI"),
        "expires_on": "2027-03-01",
    }
    payload.update(overrides)
    return payload


def create_inspection_payload(**overrides) -> dict:
    payload = {
        "vehicle_class": "SUV",
        "seat_count": 6,
        "child_seat_type": "BOOSTER",
        "inspector_note": "clean",
        "expires_on": "2027-03-01",
    }
    payload.update(overrides)
    return payload


def create_contract_payload(district_id: str, **overrides) -> dict:
    payload = {
        "district_id": district_id,
        "effective_from": "2026-08-01",
        "through_date": "2027-06-30",
        "per_ride_rate_cents": STANDARD_PER_RIDE_CENTS,
        "per_mile_rate_cents": STANDARD_PER_MILE_CENTS,
        "minimum_billable_cents": STANDARD_MINIMUM_BILLABLE_CENTS,
        "billing_period": "MONTHLY",
    }
    payload.update(overrides)
    return payload


def create_ride_request_payload(
    district_id: str, rider_id: str, expected_district_version: int, **overrides
) -> dict:
    payload = {
        "expected_district_version": expected_district_version,
        "district_id": district_id,
        "rider_id": rider_id,
        "trip_type": "AM_SCHOOL",
        "required_specialty": "NONE",
        "window_start_at": "2026-09-10T07:30:00Z",
        "window_end_at": "2026-09-10T07:50:00Z",
        "max_window_minutes": 30,
        "min_lead_time_hours": 12,
        "pickup_address": "12 Oak St",
        "dropoff_address": "Lincoln Elementary",
        "planned_miles": 3.0,
        "is_recurring": False,
    }
    payload.update(overrides)
    return payload


def create_trip_payload(
    ride_request_id: str, expected_district_version: int, **overrides
) -> dict:
    payload = {
        "expected_district_version": expected_district_version,
        "ride_request_id": ride_request_id,
        "scheduled_date": "2026-09-10",
        "window_start_at": "2026-09-10T07:30:00Z",
        "window_end_at": "2026-09-10T07:50:00Z",
        "planned_miles": 3.0,
    }
    payload.update(overrides)
    return payload


def create_geofence_payload(district_id: str, **overrides) -> dict:
    payload = {
        "district_id": district_id,
        "label": "Lincoln campus",
        "center_lat": 29.7604,
        "center_lon": -95.3698,
        "radius_miles": 1.0,
    }
    payload.update(overrides)
    return payload


def pickup_handoff_payload(verified_party_name: str, **overrides) -> dict:
    # PRD §3.8: at a PICKUP leg the releasing party is checked against the
    # student's placement record. SCHOOL_STAFF "fails outright", and an
    # AUTHORIZED_ADULT passes only when the name is on the student's roster, so
    # the neutral, always-valid release is a PLACEMENT_WORKER with a
    # PHYSICAL_SIGNATURE — that pairing "passes only when the verification
    # method is a PHYSICAL_SIGNATURE" and is otherwise unconstrained by name.
    payload = {
        "leg": "PICKUP",
        "expected_party": "PLACEMENT_WORKER",
        "verified_party_name": verified_party_name,
        "verification_method": "PHYSICAL_SIGNATURE",
    }
    payload.update(overrides)
    return payload


def dropoff_handoff_payload(verified_party_name: str, **overrides) -> dict:
    # PRD §3.8: "a dropoff handoff may additionally carry the odometer reading
    # in billable_miles" — the field belongs to the DROPOFF leg alone, so a
    # caller that re-tags this payload with another leg must drop it.
    payload = {
        "leg": "DROPOFF",
        "expected_party": "SCHOOL_STAFF",
        "verified_party_name": verified_party_name,
        "verification_method": "PHOTO_ID",
        "billable_miles": 3.0,
    }
    payload.update(overrides)
    if payload.get("leg") != "DROPOFF":
        payload.pop("billable_miles", None)
    return payload


def billing_run_payload(
    expected_district_version: int, period_key: str, **overrides
) -> dict:
    payload = {
        "expected_district_version": expected_district_version,
        "period_key": period_key,
        "period_start": "2026-09-01",
        "period_end": "2026-09-30",
    }
    payload.update(overrides)
    return payload


__all__ = [
    "CAREGIVER_EXPERIENCE_MIN_MONTHS", "SEAT_CAPACITY_MAX",
    "ACADEMIC_TERM_OPEN_DATE", "QUOTE_DISCREPANCY_DISCOUNT",
    "FINAL_LOCKED_DISCOUNT", "CREDIT_APPLY_PCT", "STRIKE_MEDIUM_MIN",
    "STRIKE_HIGH_MIN", "DRIVER_SUSPENSION_STRIKE_THRESHOLD",
    "BREACH_MEDIUM_MIN", "WAIT_BLOCK_MINUTES", "WAIT_BLOCK_MAX",
    "WAIT_TIME_MIN_BLOCKS", "LATE_DISPATCH_DISCOUNT", "NORMAL_MULTIPLIER",
    "PENALTY_MULTIPLIER", "GRADE_HIGH_MIN", "GRADE_MEDIUM_MIN",
    "PROXIMITY_FACTOR", "PIN_LENGTH", "MAX_HANDOFF_ATTEMPTS",
    "SUPPLY_STAFFED_RATIO", "SERIES_OVERLAP_BUFFER_MINUTES",
    "AVAILABILITY_BUFFER_MINUTES", "DEFAULT_CLOCK", "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MAX_LIMIT", "PROGRAM_WEIGHT", "STANDARD_PER_RIDE_CENTS",
    "STANDARD_PER_MILE_CENTS", "STANDARD_MINIMUM_BILLABLE_CENTS",
    "NON_EXISTENT_RIDER_UUID", "unique_ref",
    "create_district_payload", "create_rider_payload", "create_driver_payload",
    "create_background_check_payload", "create_inspection_payload",
    "create_contract_payload", "create_ride_request_payload",
    "create_trip_payload", "create_geofence_payload", "pickup_handoff_payload",
    "dropoff_handoff_payload", "billing_run_payload",
]