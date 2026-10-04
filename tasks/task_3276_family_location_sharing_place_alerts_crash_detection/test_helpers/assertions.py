"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_circle(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Circle.id must be a valid UUID"
    assert isinstance(data.get("name"), str) and data["name"]
    assert data["subscription_tier"] in ("FREE", "PLUS", "PROTECT")
    assert data["subscription_status"] in (
        "TRIALING", "ACTIVE", "PAST_DUE", "SUSPENDED", "CANCELLED",
    )
    assert data["circle_posture"] in ("OPEN", "RESTRICTED", "FROZEN")
    assert isinstance(data["assistance_units_balance"], int)
    assert isinstance(data["identity_protection_credits"], int)
    assert isinstance(data["history_retention_days"], int)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_member(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Member.id must be a valid UUID"
    assert data["role"] in ("OWNER", "ADMIN", "MEMBER", "MINOR")
    assert data["consent_state"] in ("PENDING", "GRANTED", "REVOKED", "EXPIRED")
    assert data["privacy_mode"] in ("PRECISE", "BLURRED", "HIDDEN")
    assert data["sampling_profile"] in ("HIGH", "BALANCED", "SAVER")
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int)


def assert_place(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Place.id must be a valid UUID"
    assert data["place_status"] in ("ACTIVE", "ARCHIVED")
    assert 50 <= data["radius_m"] <= 5000
    assert 10 <= data["accuracy_floor_m"] <= 500
    assert data["dwell_bucket_seconds"] in (60, 180, 300)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int)


def assert_location_fix(data: dict):
    assert is_valid_uuid(data.get("id", "")), "LocationFix.id must be a valid UUID"
    assert data["fix_status"] in (
        "ACCEPTED", "REJECTED_ACCURACY", "REJECTED_STALE",
        "REJECTED_CONSENT", "RETIRED",
    )
    assert data["motion_context"] in ("STILL", "WALKING", "DRIVING", "UNKNOWN")
    assert is_iso8601_timestamp(data.get("recorded_at", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_place_alert(data: dict):
    assert is_valid_uuid(data.get("id", "")), "PlaceAlert.id must be a valid UUID"
    assert data["event_kind"] in ("ARRIVAL", "DEPARTURE")
    assert data["alert_status"] in (
        "PENDING_DWELL", "CONFIRMED", "SUPPRESSED", "CANCELLED",
    )
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_trip_report(data: dict):
    assert is_valid_uuid(data.get("id", "")), "TripReport.id must be a valid UUID"
    assert data["trip_status"] in ("OPEN", "CLOSED", "ABANDONED")
    assert is_iso8601_timestamp(data.get("started_at", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_crash_event(data: dict):
    assert is_valid_uuid(data.get("id", "")), "CrashEvent.id must be a valid UUID"
    assert data["crash_status"] in (
        "DETECTED", "WELLNESS_PENDING", "CONFIRMED_OK", "ESCALATED",
        "DISPATCHED", "RESOLVED", "FALSE_ALARM",
    )
    assert data["severity"] in ("MINOR", "MAJOR", "SEVERE")
    assert is_iso8601_timestamp(data.get("detected_at", ""))
    assert isinstance(data["version"], int)


def assert_wellness_check(data: dict):
    assert is_valid_uuid(data.get("id", "")), "WellnessCheck.id must be a valid UUID"
    assert data["check_status"] in ("SENT", "ACKNOWLEDGED", "UNANSWERED", "CANCELLED")
    assert is_iso8601_timestamp(data.get("deadline_at", ""))


def assert_dispatch(data: dict):
    assert is_valid_uuid(data.get("id", "")), "EmergencyDispatch.id must be a valid UUID"
    assert data["dispatch_status"] in (
        "PENDING_VERIFICATION", "VERIFIED", "STAGED", "COMPLETED", "CANCELLED",
    )


def assert_subscription_event(data: dict):
    assert is_valid_uuid(data.get("id", "")), "SubscriptionEvent.id must be a valid UUID"
    assert data["event_kind"] in (
        "TIER_CHANGE", "RENEWAL", "PAYMENT_FAILED", "SUSPENDED", "REACTIVATED",
        "CANCELLED", "ASSISTANCE_GRANT", "ASSISTANCE_CONSUME",
        "IDENTITY_CREDIT_CONSUME",
    )
    assert isinstance(data["units_delta"], int)
    assert isinstance(data["billing_period_index"], int)


def assert_consent_record(data: dict):
    assert is_valid_uuid(data.get("id", "")), "ConsentRecord.id must be a valid UUID"
    assert data["scope"] in ("LOCATION", "DRIVING", "CRASH", "FULL")
    assert data["consent_action"] in ("GRANT", "REVOKE", "EXPIRE")


def assert_compliance_hold(data: dict):
    assert is_valid_uuid(data.get("id", "")), "ComplianceHold.id must be a valid UUID"
    assert data["hold_kind"] in (
        "DATA_SHARING_DISCLOSURE", "MONETIZATION_OPT_OUT_SWEEP", "MINOR_PRIVACY_AUDIT",
    )
    assert data["hold_status"] in ("OPEN", "RESOLVED")
