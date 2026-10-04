"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def same_instant(actual: str, expected: str) -> bool:
    """True when two ISO 8601 strings name the same UTC instant.

    PRD §2.7 pins the three-fractional-digit rendering only for the common
    `created_at`/`updated_at` stamps; it does not pin the rendering of derived
    instants such as `end_at` or `expires_at`, so a derivation assertion must
    compare the instant rather than its textual form.
    """
    def parse(value):
        text = str(value).strip()
        if text.endswith("Z") or text.endswith("z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    return parse(actual) == parse(expected)


def assert_same_instant(actual: str, expected: str, message: str = ""):
    assert same_instant(actual, expected), (
        f"{message}: expected the instant {expected}, got {actual}"
        if message else f"expected the instant {expected}, got {actual}")


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be an integer >= 1, got {data.get('version')!r}"


def assert_studio(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["home_state_code"] in ["CA", "NY", "TX", "WA", "CO"]
    assert data["status"] in ["TRIAL", "ACTIVE", "SUSPENDED", "CANCELLED"]
    assert data["subscription_tier"] in ["STARTER", "GROWTH", "ENTERPRISE"]
    assert data["data_ownership_state"] in [
        "OWNED", "PORTABILITY_PENDING", "PORTABILITY_GRANTED", "EXPORT_CLOSED"]
    assert isinstance(data["feature_gates"], dict)
    for gate in ["marketplace_listing", "staff_payroll", "instructor_substitution",
                 "waitlist_auto_promotion", "benefit_network_billing",
                 "client_portability_export"]:
        assert gate in data["feature_gates"], f"feature_gates must carry {gate}"
        assert isinstance(data["feature_gates"][gate], bool)
    assert isinstance(data["client_roster_count"], int)
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["outstanding_balance_cents"] >= 0, "outstanding balance is never negative"
    assert data["client_roster_count"] >= 0
    assert data["payroll_cap_mode"] in ["BONUS_OUTSIDE_CAP", "BONUS_INSIDE_CAP"]


def assert_subscription_tier(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "a tier is a configuration record and carries no updated_at"
    assert "version" not in data, "a tier is a configuration record and carries no version"
    assert data["tier"] in ["STARTER", "GROWTH", "ENTERPRISE"]
    assert data["monthly_fee_cents"] >= 0 and data["monthly_fee_cents"] % 100 == 0
    assert data["tier_rank"] >= 1
    assert 0 <= data["marketplace_commission_bps"] <= 10000


def assert_business_subscription(data: dict):
    _assert_common_fields(data)
    assert data["tier"] in ["STARTER", "GROWTH", "ENTERPRISE"]
    assert data["billing_period"] in ["MONTHLY", "ANNUAL"]
    assert data["status"] in ["TRIAL", "ACTIVE", "PAST_DUE", "GRACE", "SUSPENDED", "CANCELLED"]
    assert data["dunning_stage"] in ["CURRENT", "RETRY_SCHEDULED", "SUSPENDED", "CANCELLED"]
    assert isinstance(data["renewal_epoch"], int) and data["renewal_epoch"] >= 0
    assert isinstance(data["monthly_fee_cents_snapshot"], int)
    assert isinstance(data["staff_seat_count"], int)
    assert isinstance(data["seat_overage_count"], int) and data["seat_overage_count"] >= 0
    assert isinstance(data["payroll_hold"], bool)


def assert_staff_member(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["staff_role"] in ["INSTRUCTOR", "FRONT_DESK", "MANAGER"]
    assert data["status"] in ["ACTIVE", "SUBSTITUTE_ONLY", "INACTIVE"]
    assert isinstance(data["substitute_class_template_ids"], list)
    assert 0 <= data["commission_rate_bps"] <= 5000
    assert isinstance(data["accrued_commission_cents"], int)


def assert_client(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert data["home_state_code"] in ["CA", "NY", "TX", "WA", "CO"]
    assert data["status"] in ["ACTIVE", "FROZEN", "PORTABILITY_HOLD", "PORTED", "ANONYMIZED"]
    assert isinstance(data["no_show_strike_count"], int) and data["no_show_strike_count"] >= 0
    assert isinstance(data["late_cancel_count"], int) and data["late_cancel_count"] >= 0
    assert isinstance(data["outstanding_fee_cents"], int) and data["outstanding_fee_cents"] >= 0


def assert_class_template(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["duration_minutes"] >= 15
    assert data["base_price_cents"] >= 0
    assert data["default_capacity"] >= 1
    assert data["credit_cost"] >= 1
    assert isinstance(data["is_off_peak"], bool)
    assert data["buffer_minutes"] >= 0


def assert_class_session(data: dict):
    _assert_common_fields(data)
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert data["status"] in ["SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED_BY_STUDIO"]
    assert data["fullness_posture"] in ["OPEN", "WAITLIST_ONLY", "FULL", "CANCELLED"]
    assert data["capacity"] >= 1
    assert isinstance(data["seats_taken"], int) and data["seats_taken"] >= 0
    assert isinstance(data["seats_held"], int) and data["seats_held"] >= 0
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] >= 0
    assert isinstance(data["marketplace_price_cents"], int)
    assert data["price_version"] >= 1
    assert data["promo_offer_state"] in [
        "NONE", "SCHEDULED", "ACTIVE", "EXHAUSTED", "EXPIRED", "WITHDRAWN"]


def assert_booking(data: dict):
    _assert_common_fields(data)
    assert data["channel"] in ["STUDIO", "MARKETPLACE"]
    assert data["payment_source"] in [
        "DROP_IN", "MEMBERSHIP", "CLASS_PACK", "BENEFIT_NETWORK"]
    assert data["status"] in [
        "RESERVED", "CHECKED_IN", "NO_SHOW", "ATTENDED", "CANCELLED",
        "LATE_CANCELLED", "WAITLISTED"]
    assert data["fee_status"] in ["NONE", "CHARGED", "PAYROLL_DEDUCTED", "WAIVED"]
    assert isinstance(data["booking_fee_cents"], int) and data["booking_fee_cents"] >= 0
    assert isinstance(data["commission_base_cents"], int)
    assert data["benefit_claim_status"] in ["NOT_APPLICABLE", "SUBMITTED", "PAID", "DENIED"]
    assert isinstance(data["is_promotional_seat"], bool)
    assert isinstance(data["creation_seq"], int)
    assert isinstance(data["reminders_sent"], int) and data["reminders_sent"] >= 0


def assert_waitlist_entry(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [
        "ACTIVE", "STANDBY", "OFFERED", "CLAIMED", "EXPIRED", "CANCELLED"]
    assert data["position_mode"] in ["QUEUED", "STANDBY_ANY"]
    assert isinstance(data["raw_sequence_no"], int)
    assert isinstance(data["effective_sequence"], int)
    if data["position_mode"] == "STANDBY_ANY":
        assert data["effective_sequence"] == min(data["raw_sequence_no"], 0)
    else:
        assert data["effective_sequence"] == data["raw_sequence_no"]


def assert_membership(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [
        "PENDING", "ACTIVE", "FROZEN", "PAST_DUE", "LAPSED", "CANCELLED", "EXPIRED"]
    assert data["monthly_fee_cents"] >= 0
    assert data["included_credits_per_cycle"] >= 0
    assert 1 <= data["billing_anchor_day"] <= 28
    assert isinstance(data["auto_renew"], bool)
    assert isinstance(data["current_period_index"], int) and data["current_period_index"] >= 0
    assert isinstance(data["freeze_days_used"], int) and data["freeze_days_used"] >= 0
    assert isinstance(data["prorated_fee_cents"], int)
    assert isinstance(data["open_balance_cents"], int) and data["open_balance_cents"] >= 0


def assert_class_pack(data: dict):
    _assert_common_fields(data)
    assert data["pack_size"] >= 1
    assert isinstance(data["credits_remaining"], int) and data["credits_remaining"] >= 0
    assert data["credits_remaining"] <= data["pack_size"]
    assert data["status"] in ["ACTIVE", "EXPIRED", "DEPLETED", "FROZEN"]
    assert is_iso8601_timestamp(data["purchased_at"])
    assert is_iso8601_timestamp(data["expires_at"])
    assert isinstance(data["extension_days_used"], int) and data["extension_days_used"] >= 0


def assert_benefit_network(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data
    assert "version" not in data
    assert isinstance(data["network_code"], str) and data["network_code"]
    assert data["per_visit_allowance_cents"] >= 0
    assert isinstance(data["reimburse_full_list_price"], bool)


def assert_commission_entry(data: dict):
    _assert_common_fields(data)
    assert data["booking_channel"] in ["STUDIO", "MARKETPLACE"]
    assert data["status"] in ["ACCRUED", "PAID", "REVERSED"]
    assert isinstance(data["base_amount_cents"], int)
    assert isinstance(data["rate_bps"], int)
    assert isinstance(data["commission_cents"], int)
    if data["status"] == "REVERSED":
        assert data.get("reversal_reason"), "a reversed entry carries a reason"
    else:
        assert data.get("reversal_reason") is None


def assert_payroll_period(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["OPEN", "LOCKED", "CLOSED"]
    assert data["period_index"] >= 1
    assert is_iso8601_timestamp(data["start_date"])
    assert is_iso8601_timestamp(data["end_date"])
    assert isinstance(data["accrued_commission_cents"], int)
    assert isinstance(data["paid_commission_cents"], int)
    assert isinstance(data["reversal_correction_cents"], int)


def assert_portability_request(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [
        "PENDING", "OBJECTED", "RESOLVED_RELEASE", "RESOLVED_DENIED",
        "EXPORT_ISSUED", "EXPIRED", "WITHDRAWN"]
    assert is_iso8601_timestamp(data["requested_at"])
    assert isinstance(data["dispute_reason"], str)
    assert isinstance(data["export_download_count"], int)
    assert data["export_download_count"] >= 0


def assert_feature_gates_match_tier(data: dict, tier_row: dict):
    """The studio's derived gates must be the tier row's own booleans."""
    gates = data["feature_gates"]
    assert gates["marketplace_listing"] == tier_row["marketplace_listing_enabled"]
    assert gates["staff_payroll"] == tier_row["staff_payroll_enabled"]
    assert gates["instructor_substitution"] == tier_row["instructor_substitution_enabled"]
    assert gates["waitlist_auto_promotion"] == tier_row["waitlist_auto_promotion_enabled"]
    assert gates["client_portability_export"] == tier_row["crm_client_export_enabled"]


def assert_seat_occupancy_conserved(session: dict, live_bookings: int, offered_holds: int):
    """seats_taken is the live booking count and seats_held the offered holds."""
    assert session["seats_taken"] == live_bookings, (
        f"seats_taken should be {live_bookings}, got {session['seats_taken']}")
    assert session["seats_held"] == offered_holds, (
        f"seats_held should be {offered_holds}, got {session['seats_held']}")