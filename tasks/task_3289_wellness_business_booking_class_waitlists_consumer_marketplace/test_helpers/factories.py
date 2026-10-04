"""Payload factories — input fields only, one per resource."""
from .constants import TEST_DEFAULTS


def create_studio_payload(**overrides) -> dict:
    payload = {
        "legal_name": TEST_DEFAULTS["LEGAL_NAME"],
        "home_state_code": TEST_DEFAULTS["HOME_STATE"],
        "owner_full_name": TEST_DEFAULTS["OWNER_NAME"],
        "tier": "GROWTH",
        "billing_period": "MONTHLY",
        "payroll_cap_mode": "BONUS_OUTSIDE_CAP",
    }
    payload.update(overrides)
    return payload


def create_staff_member_payload(**overrides) -> dict:
    payload = {
        "full_name": TEST_DEFAULTS["INSTRUCTOR_NAME"],
        "staff_role": "INSTRUCTOR",
        "commission_rate_bps": 0,
    }
    payload.update(overrides)
    return payload


def create_client_payload(**overrides) -> dict:
    payload = {
        "display_name": TEST_DEFAULTS["CLIENT_NAME"],
        "email": TEST_DEFAULTS["CLIENT_EMAIL"],
        "home_state_code": TEST_DEFAULTS["HOME_STATE"],
    }
    payload.update(overrides)
    return payload


def create_class_template_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["TEMPLATE_NAME"],
        "duration_minutes": TEST_DEFAULTS["DURATION_MINUTES"],
        "base_price_cents": TEST_DEFAULTS["BASE_PRICE_CENTS"],
        "default_capacity": TEST_DEFAULTS["DEFAULT_CAPACITY"],
        "credit_cost": TEST_DEFAULTS["CREDIT_COST"],
        "is_off_peak": True,
        "buffer_minutes": TEST_DEFAULTS["BUFFER_MINUTES"],
    }
    payload.update(overrides)
    return payload


def create_class_session_payload(**overrides) -> dict:
    payload = {"room_code": "ROOM-A", "start_at": "2026-06-20T17:00:00Z"}
    payload.update(overrides)
    return payload


def create_booking_payload(**overrides) -> dict:
    payload = {"channel": "STUDIO", "payment_source": "DROP_IN"}
    payload.update(overrides)
    return payload


def join_waitlist_payload(**overrides) -> dict:
    payload = {"position_mode": "QUEUED"}
    payload.update(overrides)
    return payload


def create_class_pack_payload(**overrides) -> dict:
    payload = {
        "pack_size": 5,
        "purchased_at": "2026-06-01T00:00:00Z",
        "expiry_scheme": "NONE",
    }
    payload.update(overrides)
    return payload


def create_membership_payload(**overrides) -> dict:
    payload = {
        "plan_name": "Unlimited Monthly",
        "monthly_fee_cents": 9000,
        "included_credits_per_cycle": 8,
        "minimum_term_months": 3,
        "freeze_allowed": True,
        "freeze_max_days_per_cycle": 10,
        "billing_anchor_day": 1,
        "auto_renew": True,
    }
    payload.update(overrides)
    return payload


def create_payroll_period_payload(**overrides) -> dict:
    payload = {
        "period_index": 1,
        "start_date": "2026-06-01T00:00:00Z",
        "end_date": "2026-06-30T23:59:59Z",
    }
    payload.update(overrides)
    return payload


def create_benefit_network_payload(**overrides) -> dict:
    payload = {
        "network_code": "WELLPASS",
        "name": "WellPass Network",
        "per_visit_allowance_cents": 2500,
        "reimburse_full_list_price": False,
        "remit_days_after_visit": 30,
        "claim_denial_window_hours": 72,
    }
    payload.update(overrides)
    return payload


def create_portability_request_payload(**overrides) -> dict:
    payload = {"dispute_reason": "relocating"}
    payload.update(overrides)
    return payload


def create_marketplace_booking_payload(**overrides) -> dict:
    payload = {"payment_ref": "pm_ok_1", "promo_redeem": False}
    payload.update(overrides)
    return payload