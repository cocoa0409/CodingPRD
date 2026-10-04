"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)

DEFAULTS = {
    "MONTHLY_FEE_CENTS": 3000,
    "COMMITMENT_MONTHS": 12,
    "UPGRADE_ELIGIBILITY_MONTHS": 6,
    "PAUSE_DAYS_PER_TERM": 30,
    "EARLY_CANCEL_FEE_FLOOR_CENTS": 5000,
    "MIN_PAID_MONTHS": 0,
}


def _next_email(prefix="member"):
    return f"{prefix}-{next(_counter)}@example.com"


def _next_serial():
    return f"SN-{next(_counter):06d}"


def create_member_payload(**overrides) -> dict:
    defaults = {"email": _next_email(), "full_name": "Test Member"}
    defaults.update(overrides)
    return defaults


def create_term_payload(**overrides) -> dict:
    defaults = {
        "plan_name": "Plan",
        "monthly_fee_cents": DEFAULTS["MONTHLY_FEE_CENTS"],
        "commitment_months": DEFAULTS["COMMITMENT_MONTHS"],
        "hardware_tier": "BAND_STD",
        "upgrade_eligibility_months": DEFAULTS["UPGRADE_ELIGIBILITY_MONTHS"],
        "pause_days_per_term": DEFAULTS["PAUSE_DAYS_PER_TERM"],
        "cancel_fee_policy": "REMAINING_MONTHS",
        "early_cancel_fee_floor_cents": DEFAULTS["EARLY_CANCEL_FEE_FLOOR_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_device_payload(member_id, term_id, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "term_id": term_id,
        "serial_number": _next_serial(),
        "hardware_tier": "BAND_STD",
    }
    defaults.update(overrides)
    return defaults


def create_ingest_payload(day_on="2026-09-01", **overrides) -> dict:
    defaults = {
        "day_on": day_on,
        "avg_hr": 100,
        "hrv_ms": 100,
        "resting_hr": 50,
        "sleep_minutes": 480,
    }
    defaults.update(overrides)
    return defaults


def create_pause_payload(start_on="2026-09-01", days=10, **overrides) -> dict:
    defaults = {"start_on": start_on, "days": days}
    defaults.update(overrides)
    return defaults


def create_payment_payload(outcome="SUCCEEDED") -> dict:
    return {"outcome": outcome}


def create_replacement_request_payload(reason="HARDWARE_FAILURE") -> dict:
    return {"reason": reason}


def create_decision_payload(decision="APPROVE", diagnosis=None) -> dict:
    payload = {"decision": decision}
    if diagnosis is not None:
        payload["diagnosis"] = diagnosis
    return payload


def create_release_payload(version=2, requires_member_ack=True, **overrides) -> dict:
    defaults = {
        "version": version,
        "requires_member_ack": requires_member_ack,
        "release_notes": f"Release v{version}",
    }
    defaults.update(overrides)
    return defaults


def create_team_payload(coach_user_id, **overrides) -> dict:
    defaults = {
        "name": f"Team {next(_counter)}",
        "team_type": "SPORTS",
        "coach_user_id": coach_user_id,
    }
    defaults.update(overrides)
    return defaults


def create_consent_payload(
    scope, expected_team_membership_version, action="GRANT", expires_on=None
) -> dict:
    payload = {
        "scope": scope,
        "action": action,
        "expected_team_membership_version": expected_team_membership_version,
    }
    if expires_on is not None:
        payload["expires_on"] = expires_on
    return payload


def create_study_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "code": f"STUDY-{n:04d}",
        "title": f"Study {n}",
        "min_paid_months": DEFAULTS["MIN_PAID_MONTHS"],
        "enrollment_window_start_on": "2026-09-01",
        "enrollment_window_end_on": "2026-09-30",
    }
    defaults.update(overrides)
    return defaults


def create_merch_order_payload(lines=None, **overrides) -> dict:
    if lines is None:
        lines = [
            {
                "sku": "SKU-DEFAULT",
                "category": "BAND_ACCESSORY",
                "unit_price_cents": 1000,
                "qty": 1,
            }
        ]
    payload = {"lines": lines}
    payload.update(overrides)
    return payload
