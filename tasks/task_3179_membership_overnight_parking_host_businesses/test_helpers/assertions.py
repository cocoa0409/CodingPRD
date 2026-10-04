"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)

HOST_STATUSES = ["PENDING_REVIEW", "APPROVED", "SUSPENDED", "REJECTED"]
POSTURES = ["OPEN", "LIMITED", "UNAVAILABLE", "SUSPENDED"]
SITE_CLASSES = ["PULL_THROUGH", "BACK_IN"]
ELECTRIC_CODES = ["NONE", "ELECTRIC_30A", "ELECTRIC_50A"]
PLAN_TIERS = ["CLASSIC", "PLUS", "PREMIER"]
SUBSCRIPTION_STATUSES = ["PENDING", "ACTIVE", "LAPSED", "CANCELLED"]
REMOVAL_STATUSES = ["NONE", "REMOVED"]
VEHICLE_CLASSES = [
    "CLASS_A", "CLASS_B", "CLASS_C", "FIFTH_WHEEL", "TRAVEL_TRAILER", "CONVERSION_VAN",
]
WINDOW_KINDS = ["SEASONAL", "EVENT"]
WINDOW_STATUSES = ["SCHEDULED", "ACTIVE", "CANCELLED"]
STAY_STATUSES = [
    "REQUESTED", "CONFIRMED", "DECLINED", "CANCELLED",
    "CHECKED_IN", "CHECKED_OUT", "NO_SHOW",
]
STAY_ORIGINS = ["MEMBER_INITIATED", "HOST_INITIATED"]
REVIEW_AUTHOR_KINDS = ["HOST", "MEMBER"]
REVIEW_STATUSES = ["PUBLISHED", "WITHDRAWN"]
INCIDENT_SEVERITIES = ["MINOR", "MAJOR", "SEVERE"]
INCIDENT_ORIGINS = ["MEMBER_REPORT", "STAFF_FILING", "REVIEW_REPORT"]
INCIDENT_STATUSES = ["OPEN", "UPHELD", "DISMISSED", "WITHDRAWN"]
PURCHASE_KINDS = ["TASTING", "MERCHANDISE", "TICKET", "MEAL"]
VERIFICATION_STATUSES = ["PENDING", "VERIFIED", "REJECTED"]


# ---------------------------------------------------------------------------
# common_fields: true — id + created_at + updated_at + version
# ---------------------------------------------------------------------------

def assert_host_business(data: dict):
    assert is_valid_uuid(data.get("id", "")), "HostBusiness.id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), "HostBusiness.created_at must be ISO 8601"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), "HostBusiness.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "HostBusiness.version must be a positive integer"
    )
    assert isinstance(data["legal_name"], str) and data["legal_name"], (
        "HostBusiness.legal_name must be a non-empty string"
    )
    assert data["category"] in ["WINERY", "FARM", "BREWERY", "ATTRACTION"], (
        f"unexpected HostBusiness.category {data.get('category')!r}"
    )
    assert isinstance(data["address_line1"], str)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["arrival_window_start_hour"], int)
    assert isinstance(data["arrival_window_end_hour"], int)
    assert isinstance(data["self_contained_required"], bool)
    assert data["onboarding_status"] in HOST_STATUSES, (
        f"unexpected onboarding_status {data.get('onboarding_status')!r}"
    )
    assert data["posture"] in POSTURES, f"unexpected posture {data.get('posture')!r}"
    assert isinstance(data["effective_capacity"], int)
    assert isinstance(data["committed_sites"], int)
    assert isinstance(data["free_sites"], int)
    assert isinstance(data["seasonal_windows_reserved_sites"], int)
    assert isinstance(data["electric_site_count"], int)
    assert isinstance(data["patronization_credit_cents"], int)
    assert isinstance(data["host_rating_average"], (int, float))
    assert data["latest_checkout_at"] is None or is_iso8601_timestamp(
        data["latest_checkout_at"]
    ), "HostBusiness.latest_checkout_at must be null or ISO 8601"


def assert_parking_site(data: dict):
    assert is_valid_uuid(data.get("id", "")), "HostParkingSite.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int)
    assert is_valid_uuid(data.get("host_id", "")), "HostParkingSite.host_id must be a UUID"
    assert isinstance(data["site_label"], str) and data["site_label"]
    assert data["site_class"] in SITE_CLASSES, (
        f"unexpected site_class {data.get('site_class')!r}"
    )
    assert isinstance(data["max_vehicle_length_feet"], int)
    assert isinstance(data["has_electric"], bool)
    assert data["electric_service_code"] in ELECTRIC_CODES
    assert isinstance(data["blocks_sites"], str)
    assert isinstance(data["is_active"], bool)


def assert_member(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Member.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int)
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["plan_tier"] in PLAN_TIERS, f"unexpected plan_tier {data.get('plan_tier')!r}"
    assert data["subscription_status"] in SUBSCRIPTION_STATUSES
    assert isinstance(data["standing_score"], int)
    assert isinstance(data["strike_count"], int)
    assert data["removal_status"] in REMOVAL_STATUSES
    assert isinstance(data["guest_passes_remaining"], int)
    assert data["guest_passes_remaining"] >= 0
    assert isinstance(data["home_state_code"], str) and len(data["home_state_code"]) == 2
    assert isinstance(data["total_stays_completed"], int)
    assert isinstance(data["member_rating_average"], (int, float))


def assert_availability_window(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int)
    assert is_valid_uuid(data.get("host_id", ""))
    assert data["kind"] in WINDOW_KINDS, f"unexpected kind {data.get('kind')!r}"
    assert isinstance(data["label"], str) and data["label"]
    assert is_iso8601_timestamp(data["start_date"]), "start_date must be ISO 8601"
    assert is_iso8601_timestamp(data["end_date"]), "end_date must be ISO 8601"
    assert data["window_status"] in WINDOW_STATUSES
    assert isinstance(data["capacity_override"], int)
    assert isinstance(data["reserved_sites"], int)
    assert isinstance(data["member_capacity_ceiling"], int)
    assert data["member_capacity_ceiling"] >= 0


def assert_stay_request(data: dict):
    assert is_valid_uuid(data.get("id", "")), "StayRequest.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int)
    assert is_valid_uuid(data["host_id"])
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["vehicle_id"])
    assert data["request_status"] in STAY_STATUSES, (
        f"unexpected request_status {data.get('request_status')!r}"
    )
    assert isinstance(data["nights"], int) and data["nights"] >= 1
    assert isinstance(data["request_depth"], int)
    assert isinstance(data["count_toward_capacity"], bool)
    assert isinstance(data["same_day_hold"], bool)
    assert isinstance(data["ancillary_charge_cents"], int)
    assert data["ancillary_charge_cents"] >= 0
    assert isinstance(data["cancellation_fee_cents"], int)
    assert data["cancellation_fee_cents"] >= 0
    assert data["electric_request_code"] in ELECTRIC_CODES
    assert data["request_origin"] in STAY_ORIGINS
    assert is_iso8601_timestamp(data["arrival_date"])
    assert is_iso8601_timestamp(data["occupancy_start"])
    assert is_iso8601_timestamp(data["occupancy_end"])
    assert data["confirmed_site_id"] is None or is_valid_uuid(data["confirmed_site_id"])


def assert_incident(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["host_id"])
    assert data["severity"] in INCIDENT_SEVERITIES
    assert data["origin"] in INCIDENT_ORIGINS
    assert data["incident_status"] in INCIDENT_STATUSES
    assert isinstance(data["narrative"], str)
    assert isinstance(data["waived_days_remaining"], int)
    assert data["waived_days_remaining"] >= 0


def assert_patronization_record(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int)
    assert is_valid_uuid(data["host_id"])
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["stay_request_id"])
    assert isinstance(data["receipt_cents"], int)
    assert data["purchase_kind"] in PURCHASE_KINDS
    assert isinstance(data["verification_code"], str) and data["verification_code"]
    assert data["verification_status"] in VERIFICATION_STATUSES
    assert isinstance(data["host_credit_cents"], int)
    assert data["host_credit_cents"] >= 0


# ---------------------------------------------------------------------------
# common_fields: false — id + created_at only; no updated_at, no version
# ---------------------------------------------------------------------------

def assert_member_vehicle(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, (
        "MemberVehicle is append-only and must not carry updated_at"
    )
    assert "version" not in data, (
        "MemberVehicle is append-only and must not carry version"
    )
    assert is_valid_uuid(data["member_id"])
    assert data["vehicle_class"] in VEHICLE_CLASSES
    assert isinstance(data["length_feet"], int)
    assert isinstance(data["self_contained"], bool)
    assert isinstance(data["inspection_state_code"], str)
    assert isinstance(data["is_primary"], bool)


def assert_host_review(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, (
        "HostReview is append-only and must not carry updated_at"
    )
    assert "version" not in data, (
        "HostReview is append-only and must not carry version"
    )
    assert data["author_kind"] in REVIEW_AUTHOR_KINDS
    assert data["review_status"] in REVIEW_STATUSES
    assert isinstance(data["rating"], int) and 1 <= data["rating"] <= 5
    assert isinstance(data["public_note"], str)
    assert isinstance(data["counter_review_count"], int)
    assert data["counter_review_count"] >= 0
    if data.get("author_review_id") is not None:
        assert is_valid_uuid(data["author_review_id"])


def assert_conduct_disposition(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, (
        "ConductDisposition is append-only and must not carry updated_at"
    )
    assert "version" not in data, (
        "ConductDisposition is append-only and must not carry version"
    )
    assert is_valid_uuid(data["incident_id"])
    assert is_valid_uuid(data["member_id"])
    assert data["decision"] in ["UPHELD", "DISMISSED"]
    assert isinstance(data["decided_by_display_name"], str)
    assert is_iso8601_timestamp(data["decided_at"])


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------

def assert_host_capacity_invariants(data: dict):
    """Invariants that must hold after any capacity-affecting operation."""
    assert data["effective_capacity"] >= 0
    assert data["committed_sites"] >= 0
    assert data["free_sites"] >= 0, "free_sites is floored at zero and never negative"
    assert data["free_sites"] == max(
        0, data["effective_capacity"] - data["committed_sites"]
    ), "free_sites must equal max(0, effective_capacity - committed_sites)"
    if data["posture"] in ("UNAVAILABLE", "SUSPENDED"):
        assert data["effective_capacity"] == 0, (
            "effective_capacity is forced to 0 when posture is UNAVAILABLE or SUSPENDED"
        )


def assert_capacity_summary_invariants(data: dict):
    assert data["capacity_basis"] in ["base", "live"]
    # free_sites = max(0, effective_capacity - committed_sites): the reserved
    # basis holds first-round REQUESTED requests plus CONFIRMED stays.
    assert data["free_sites"] == max(
        0, data["effective_capacity"] - data["committed_sites_reserved_basis"]
    ), "free_sites must follow the reserved basis"
    assert data["committed_sites_occupied_basis"] <= data[
        "committed_sites_reserved_basis"
    ], "the occupied basis counts a subset of the reserved basis"
    assert data["posture"] in POSTURES


def assert_member_conduct_invariants(data: dict):
    assert 0 <= data["standing_score"] <= 100, (
        "standing_score starts at 100 and is floored at 0"
    )
    assert data["strike_count"] >= 0
    if data["strike_count"] >= STRIKE_REMOVAL_THRESHOLD:
        assert data["removal_status"] == "REMOVED"
    if data["removal_status"] == "REMOVED":
        assert data["subscription_status"] == "CANCELLED", (
            "a removed member has their subscription cancelled in the same pass"
        )


STRIKE_REMOVAL_THRESHOLD = 3


def assert_posture_matches_capacity(data: dict):
    """The four-step posture ladder evaluated against the reported numbers."""
    if data["onboarding_status"] in ("SUSPENDED", "REJECTED"):
        expected = "SUSPENDED"
    elif data["effective_capacity"] < 1:
        expected = "UNAVAILABLE"
    elif data["free_sites"] < 1:
        expected = "LIMITED"
    elif data["free_sites"] <= -(-data["effective_capacity"] * 20 // 100):
        # ceil(effective_capacity * 0.20) computed in integers
        expected = "LIMITED"
    else:
        expected = "OPEN"
    assert data["posture"] == expected, (
        f"posture {data['posture']!r} does not follow the ladder; "
        f"capacity={data['effective_capacity']} free={data['free_sites']} "
        f"status={data['onboarding_status']} -> expected {expected!r}"
    )