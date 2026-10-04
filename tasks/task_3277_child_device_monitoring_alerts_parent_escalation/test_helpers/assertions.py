"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

SUBSCRIPTION_TIERS = {"BASIC", "STANDARD", "PREMIUM"}
ANALYSIS_VARIANTS = {"LEXICAL_V1", "CONTEXTUAL_V2"}
ACCOUNT_STATUSES = {"ACTIVE", "SUSPENDED"}
AGE_BANDS = {"CHILD_9_UNDER", "PRETEEN_10_12", "TEEN_13_15", "OLDER_TEEN_16_17"}
SENSITIVITIES = {"LENIENT", "STANDARD", "STRICT"}
PAIRING_STATUSES = {"PAIRED", "UNPAIRED"}
DEVICE_POSTURES = {"NORMAL", "BYPASS_WATCH", "LOCKDOWN"}
CONSENT_STATUSES = {"AWAITING_CONSENT", "ACTIVE", "PAUSED", "REVOKED"}
SEVERITIES = {"LOW", "MODERATE", "HIGH", "SEVERE"}
ALERT_STATUSES = {"DELIVERED", "ACKNOWLEDGED", "RESOLVED", "REOPENED"}
CASE_STATUSES = {
    "OPEN",
    "GUIDANCE_ISSUED",
    "RESOURCE_REFERRED",
    "CRISIS_ESCALATED",
    "LEGAL_REPORTED",
    "CLOSED",
}
GRANT_STATUSES = {"SCHEDULED", "ACTIVE", "EXPIRED", "CANCELLED"}
LINK_STATUSES = {"PENDING_CONSENT", "ACTIVE", "WITHDRAWN"}
WINDOW_STATUSES = {"ACTIVE", "DISABLED"}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_family(data: dict):
    _assert_common(data)
    assert isinstance(data["family_name"], str) and data["family_name"]
    assert isinstance(data["primary_contact_email"], str)
    assert data["subscription_tier"] in SUBSCRIPTION_TIERS
    assert data["analysis_variant"] in ANALYSIS_VARIANTS
    assert data["account_status"] in ACCOUNT_STATUSES
    assert isinstance(data["device_limit"], int)
    assert isinstance(data["device_count"], int) and data["device_count"] >= 0
    assert isinstance(data["open_escalation_count"], int)
    assert isinstance(data["last_proration_charge_cents"], int)


def assert_parent_member(data: dict):
    _assert_common(data)
    assert isinstance(data["family_account_id"], str)
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["is_primary"], bool)
    assert data["member_status"] in {"ACTIVE", "REMOVED"}


def assert_child(data: dict):
    _assert_common(data)
    assert isinstance(data["family_account_id"], str)
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["birth_year"], int)
    assert data["age_band"] in AGE_BANDS
    assert data["monitoring_sensitivity"] in SENSITIVITIES
    assert data["profile_status"] in {"ACTIVE", "ARCHIVED"}
    assert isinstance(data["open_alert_count"], int) and data["open_alert_count"] >= 0


def assert_device(data: dict):
    _assert_common(data)
    assert isinstance(data["child_profile_id"], str)
    assert data["platform"] in {"ANDROID", "IOS", "CHROMEBOOK"}
    assert data["pairing_status"] in PAIRING_STATUSES
    assert data["device_posture"] in DEVICE_POSTURES
    assert isinstance(data["bypass_strike_count"], int) and data["bypass_strike_count"] >= 0


def assert_connection(data: dict):
    _assert_common(data)
    assert isinstance(data["child_profile_id"], str)
    assert data["service_type"] in {"MESSAGING", "SOCIAL", "EMAIL"}
    assert isinstance(data["external_handle"], str) and data["external_handle"]
    assert data["consent_status"] in CONSENT_STATUSES
    assert "credential_token" not in data, "credential_token must never be serialized"


def assert_content_item(data: dict):
    _assert_common(data)
    assert isinstance(data["service_connection_id"], str)
    assert data["direction"] in {"INBOUND", "OUTBOUND"}
    assert isinstance(data["thread_depth"], int) and data["thread_depth"] >= 1
    assert isinstance(data["signals"], list)
    assert data["analysis_variant_used"] in ANALYSIS_VARIANTS
    assert isinstance(data["risk_score"], int) and 0 <= data["risk_score"] <= 100
    assert data["severity"] in SEVERITIES
    assert isinstance(data["alert_created"], bool)


def assert_alert(data: dict):
    _assert_common(data)
    assert isinstance(data["child_profile_id"], str)
    assert isinstance(data["content_item_id"], str)
    assert data["category"] in {"BULLYING", "SELF_HARM", "EXPLICIT", "PREDATORY_CONTACT"}
    assert data["severity"] in SEVERITIES
    assert isinstance(data["excerpt_text"], str)
    assert data["alert_status"] in ALERT_STATUSES


def assert_escalation_case(data: dict):
    _assert_common(data)
    assert isinstance(data["alert_id"], str)
    assert isinstance(data["child_profile_id"], str)
    assert data["case_status"] in CASE_STATUSES
    assert isinstance(data["crisis_resource_codes"], list)


def assert_screen_time_window(data: dict):
    _assert_common(data)
    assert isinstance(data["device_id"], str)
    assert data["weekday"] in {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"}
    assert isinstance(data["start_minute"], int) and 0 <= data["start_minute"] <= 1439
    assert isinstance(data["end_minute"], int) and 1 <= data["end_minute"] <= 1440
    assert data["end_minute"] > data["start_minute"]
    assert data["window_kind"] in {"BLOCKED", "ALLOWED"}
    assert data["window_status"] in WINDOW_STATUSES


def assert_bypass_event(data: dict):
    _assert_common(data)
    assert isinstance(data["device_id"], str)
    assert data["bypass_kind"] in {
        "VPN",
        "SECONDARY_ACCOUNT",
        "TIMEZONE_SHIFT",
        "UNINSTALL_ATTEMPT",
    }
    assert is_iso8601_timestamp(data["detected_at"])


def assert_access_grant(data: dict):
    _assert_common(data)
    assert isinstance(data["device_id"], str)
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert data["grant_status"] in GRANT_STATUSES


def assert_district(data: dict):
    _assert_common(data)
    assert isinstance(data["district_name"], str) and data["district_name"]
    assert data["jurisdiction"] in {"MANDATED_REPORTING", "DISCRETIONARY"}
    assert data["district_status"] in ACCOUNT_STATUSES
    assert isinstance(data["open_obligation_count"], int)


def assert_district_link(data: dict):
    _assert_common(data)
    assert isinstance(data["district_id"], str)
    assert isinstance(data["child_profile_id"], str)
    assert data["link_status"] in LINK_STATUSES
    assert isinstance(data["pending_legal_report"], bool)
