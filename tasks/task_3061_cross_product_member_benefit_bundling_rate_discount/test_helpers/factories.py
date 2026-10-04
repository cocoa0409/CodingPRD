"""Payload factories — one per entity, input fields only."""
import itertools
import uuid

from . import constants as C

_counter = itertools.count(1)


def unique_suffix() -> str:
    """A short collision-free token so parallel-safe entities never share keys."""
    return uuid.uuid4().hex[:10]


def create_member_payload(**overrides) -> dict:
    token = unique_suffix()
    payload = {
        "member_number": f"M-{token}",
        "full_name": "Test Member",
        "email": f"member.{token}@example.com",
    }
    payload.update(overrides)
    return payload


def create_holding_payload(member_id, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "product_line": "LENDING",
        "balance_cents": C.TEST_DEFAULTS["BALANCE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_loan_account_payload(member_id, holding_id, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "holding_id": holding_id,
        "loan_type": "PERSONAL",
        "principal_cents": C.TEST_DEFAULTS["PRINCIPAL_CENTS"],
        "base_apr_bps": C.TEST_DEFAULTS["BASE_APR_BPS"],
    }
    payload.update(overrides)
    return payload


def create_deposit_enrollment_payload(member_id, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "required_monthly_amount_cents": C.TEST_DEFAULTS["REQUIRED_MONTHLY_AMOUNT_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_entitlement_payload(source_holding_id, benefit_code, **overrides) -> dict:
    payload = {
        "source_holding_id": source_holding_id,
        "benefit_code": benefit_code,
        "value_bps": 50,
    }
    payload.update(overrides)
    return payload


def create_rule_payload(rule_code=None, **overrides) -> dict:
    payload = {
        "rule_code": rule_code or f"RULE_{unique_suffix()}",
        "discount_kind": "PROMOTIONAL",
        "stacking_class": "ADDITIVE",
        "discount_bps": C.TEST_DEFAULTS["DISCOUNT_BPS"],
        "effective_from": C.TEST_DEFAULTS["RULE_EFFECTIVE_FROM"],
        "effective_to": C.TEST_DEFAULTS["RULE_EFFECTIVE_TO"],
    }
    payload.update(overrides)
    return payload


def create_deposit_payload(enrollment_id, amount_cents, posted_at, **overrides) -> dict:
    payload = {
        "enrollment_id": enrollment_id,
        "amount_cents": amount_cents,
        "posted_at": posted_at,
    }
    payload.update(overrides)
    return payload


def redeem_principal_payload(loan_account_id, points, **overrides) -> dict:
    payload = {
        "loan_account_id": loan_account_id,
        "points": points,
    }
    payload.update(overrides)
    return payload


def rewards_adjust_payload(points_delta, **overrides) -> dict:
    payload = {
        "points_delta": points_delta,
        "source_event_code": "MANUAL_ADJUST",
    }
    payload.update(overrides)
    return payload


def create_application_payload(rule_id, expected_loan_account_version, **overrides) -> dict:
    payload = {
        "rule_id": rule_id,
        "expected_loan_account_version": expected_loan_account_version,
    }
    payload.update(overrides)
    return payload


def create_cross_sell_check_payload(member_id, target_product_line, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "target_product_line": target_product_line,
        "consent_recorded": False,
    }
    payload.update(overrides)
    return payload


def book_coaching_session_payload(member_id, coach_ref, session_kind, starts_at, ends_at, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "coach_ref": coach_ref,
        "session_kind": session_kind,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "capacity_total": 1,
    }
    payload.update(overrides)
    return payload


def decide_cross_sell_payload(outcome, **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def open_cycle_payload(expected_member_version, **overrides) -> dict:
    payload = {"expected_member_version": expected_member_version}
    payload.update(overrides)
    return payload


__all__ = [name for name in dir() if name.startswith(("create_", "redeem_", "rewards_", "book_", "decide_", "open_", "unique_"))]