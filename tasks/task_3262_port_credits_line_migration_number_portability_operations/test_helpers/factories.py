"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS as D

MDN_SEQUENCE_START = 4155550000


def unique_mdn(offset: int = 0) -> str:
    """Deterministic ten-digit directory number; tests reserve disjoint ranges."""
    return str(MDN_SEQUENCE_START + offset)


def account_payload(**overrides) -> dict:
    payload = {
        "account_type": D["ACCOUNT_TYPE"],
        "tax_id_last4": D["TAX_ID_LAST4"],
        "payment_history_score": D["PAYMENT_HISTORY_SCORE"],
        "existing_deposit_cents": D["EXISTING_DEPOSIT_CENTS"],
    }
    payload.update(overrides)
    return payload


def subscriber_line_payload(account_id, mdn, **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "mdn": mdn,
        "billing_mode": "PREPAID",
    }
    payload.update(overrides)
    return payload


def port_request_payload(subscriber_line_id, line_version, **overrides) -> dict:
    payload = {
        "subscriber_line_id": subscriber_line_id,
        "losing_carrier_code": "ATTC",
        "account_number_at_losing_carrier": "ACC1",
        "transfer_pin": "1234",
        "requested_cutover_at": "2026-09-20T00:00:00Z",
        "expected_subscriber_line_version": line_version,
    }
    payload.update(overrides)
    return payload


def rejection_code_payload(rejection_code, **overrides) -> dict:
    payload = {
        "rejection_code": rejection_code,
        "description": "Carrier objection",
        "guidance_text": "Follow the carrier guidance to clear this objection",
        "resubmission_allowed": True,
        "retry_after_hours": 0,
        "requires_action_by": "CUSTOMER",
    }
    payload.update(overrides)
    return payload


def migration_request_payload(subscriber_line_id, **overrides) -> dict:
    payload = {
        "subscriber_line_id": subscriber_line_id,
        "source_billing_mode": "PREPAID",
        "target_billing_mode": "POSTPAID",
        "prepaid_balance_cents": D["PREPAID_BALANCE_CENTS"],
        "requested_cutover_at": "2026-10-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def device_plan_payload(subscriber_line_id, line_version, **overrides) -> dict:
    payload = {
        "subscriber_line_id": subscriber_line_id,
        "device_model": "Galaxy X1",
        "device_price_cents": D["DEVICE_PRICE_CENTS"],
        "down_payment_cents": D["DOWN_PAYMENT_CENTS"],
        "installment_months": D["INSTALLMENT_MONTHS"],
        "expected_subscriber_line_version": line_version,
    }
    payload.update(overrides)
    return payload


def trade_in_assessment_payload(installment_plan_id, **overrides) -> dict:
    payload = {
        "installment_plan_id": installment_plan_id,
        "device_model": "Galaxy X1",
        "declared_condition": "GOOD",
    }
    payload.update(overrides)
    return payload


def number_reservation_payload(account_id, mdn, **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "mdn": mdn,
        "pool_code": D["POOL_CODE"],
        "reserved_at": "2026-09-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def line_addition_payload(account_id, line_count, **overrides) -> dict:
    payload = {"account_id": account_id, "line_count": line_count}
    payload.update(overrides)
    return payload


def port_protection_case_payload(subscriber_line_id, **overrides) -> dict:
    payload = {
        "subscriber_line_id": subscriber_line_id,
        "protection_type": "PORT_FREEZE",
        "verified_identity": True,
        "reason_code": "CUSTOMER_REQUEST",
    }
    payload.update(overrides)
    return payload


def promo_schedule_payload(subscriber_line_id, line_version, **overrides) -> dict:
    payload = {
        "subscriber_line_id": subscriber_line_id,
        "promo_code": "SWITCH20",
        "monthly_credit_cents": D["MONTHLY_CREDIT_CENTS"],
        "installment_months": D["INSTALLMENT_MONTHS_PROMO"],
        "retention_requirement_cycles": D["RETENTION_REQUIREMENT_CYCLES"],
        "window_start": "2026-09-02T00:00:00Z",
        "expected_subscriber_line_version": line_version,
    }
    payload.update(overrides)
    return payload