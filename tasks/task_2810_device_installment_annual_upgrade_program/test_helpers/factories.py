"""Payload factories — one per write endpoint, input fields only.

Every cents figure is emitted as a JSON number (a Python int), never a string.
Unique identifier generators keep `email`, `sku`, `account_number` and `imei`
distinct inside a single test without any cross-test shared state.
"""
import itertools
from typing import Any, Dict

from .constants import CLOCK_ORIGIN, MODEL_A, MODEL_B

_email_seq = itertools.count(1)
_sku_seq = itertools.count(1)
_account_seq = itertools.count(1)
_imei_seq = itertools.count(1)


def next_email(prefix: str = "participant") -> str:
    return f"{prefix}.{next(_email_seq)}@example.com"


def next_sku(prefix: str = "MDL") -> str:
    return f"{prefix}-{next(_sku_seq):05d}"


def next_account_number(prefix: str = "ACC-2810") -> str:
    return f"{prefix}-{next(_account_seq):06d}"


def next_imei() -> str:
    """A well-formed handset serial: exactly 15 digits, unique per call."""
    return f"35693803564{next(_imei_seq):04d}"


def create_customer_payload(**overrides) -> Dict[str, Any]:
    """POST /customers — full_name, email, mobile_number are all required."""
    payload = {
        "full_name": "Ada Vance",
        "email": next_email("ada.vance"),
        "mobile_number": "+15550100001",
    }
    payload.update(overrides)
    return payload


def create_device_model_payload(**overrides) -> Dict[str, Any]:
    """POST /device-models — the financed model 'Handset B' by default.

    `concurrent_reservation_capacity` and `active` are optional at publication
    and are omitted unless a test overrides them.
    """
    payload = {
        "sku": next_sku("MDL-B"),
        "display_name": MODEL_B["display_name"],
        "retail_price_cents": MODEL_B["retail_price_cents"],
        "monthly_protection_premium_cents": MODEL_B["monthly_protection_premium_cents"],
        "trade_in_base_credit_cents": MODEL_B["trade_in_base_credit_cents"],
        "generation_year": MODEL_B["generation_year"],
    }
    payload.update(overrides)
    return payload


def create_target_model_payload(**overrides) -> Dict[str, Any]:
    """POST /device-models — the upgrade target 'Handset A'."""
    payload = {
        "sku": next_sku("MDL-A"),
        "display_name": MODEL_A["display_name"],
        "retail_price_cents": MODEL_A["retail_price_cents"],
        "monthly_protection_premium_cents": MODEL_A["monthly_protection_premium_cents"],
        "trade_in_base_credit_cents": MODEL_A["trade_in_base_credit_cents"],
        "generation_year": MODEL_A["generation_year"],
        "concurrent_reservation_capacity": MODEL_A["concurrent_reservation_capacity"],
    }
    payload.update(overrides)
    return payload


def create_carrier_account_payload(**overrides) -> Dict[str, Any]:
    """POST /customers/{id}/carrier-accounts — carrier_code and account_number are
    required; unlock_policy_days and port_freeze_flag are optional."""
    payload = {
        "carrier_code": "VERIZON",
        "account_number": next_account_number(),
    }
    payload.update(overrides)
    return payload


def create_credit_application_payload(customer_id: str, device_model_id: str,
                                      **overrides) -> Dict[str, Any]:
    """POST /credit-applications — declared_down_payment_cents is optional and
    defaults to zero when omitted."""
    payload = {
        "customer_id": customer_id,
        "device_model_id": device_model_id,
        "requested_term_months": 24,
    }
    payload.update(overrides)
    return payload


def decision_payload(credit_score_band: str = "PRIME", **overrides) -> Dict[str, Any]:
    """POST /credit-applications/{id}/decision — the band is the only writable input."""
    payload = {"credit_score_band": credit_score_band}
    payload.update(overrides)
    return payload


def create_loan_payload(credit_application_id: str, imei: str = None,
                        down_payment_cents: int = 0, **overrides) -> Dict[str, Any]:
    """POST /loans — credit_application_id, down_payment_cents and imei."""
    payload = {
        "credit_application_id": credit_application_id,
        "down_payment_cents": int(down_payment_cents),
        "imei": imei if imei is not None else next_imei(),
    }
    payload.update(overrides)
    return payload


def activation_payload(carrier_account_id: str, **overrides) -> Dict[str, Any]:
    """POST /device-units/{id}/activation — the carrier account to join."""
    payload = {"carrier_account_id": carrier_account_id}
    payload.update(overrides)
    return payload


def payment_payload(amount_cents: int, posting_type: str = "PAYMENT",
                    **overrides) -> Dict[str, Any]:
    """POST /loans/{id}/payments — reverses_posting_id only on a REVERSAL."""
    payload = {"posting_type": posting_type, "amount_cents": int(amount_cents)}
    payload.update(overrides)
    return payload


def reversal_payload(amount_cents: int, reverses_posting_id: str,
                     **overrides) -> Dict[str, Any]:
    """POST /loans/{id}/payments with posting_type REVERSAL."""
    payload = {
        "posting_type": "REVERSAL",
        "amount_cents": int(amount_cents),
        "reverses_posting_id": reverses_posting_id,
    }
    payload.update(overrides)
    return payload


def payoff_quote_payload(quote_type: str = "EARLY_CANCELLATION", **overrides) -> Dict[str, Any]:
    """POST /loans/{id}/payoff-quotes — quote_type is the only input."""
    payload = {"quote_type": quote_type}
    payload.update(overrides)
    return payload


def cancellation_payload(payoff_quote_id: str, payment_amount_cents: int,
                         **overrides) -> Dict[str, Any]:
    """POST /loans/{id}/cancellation — the quote being settled and the cash tendered."""
    payload = {
        "payoff_quote_id": payoff_quote_id,
        "payment_amount_cents": int(payment_amount_cents),
    }
    payload.update(overrides)
    return payload


def upgrade_request_payload(loan_id: str, target_device_model_id: str,
                            fulfillment_window_start: str, expected_loan_version: int,
                            **overrides) -> Dict[str, Any]:
    """POST /upgrade-requests — all four inputs are non-optional."""
    payload = {
        "loan_id": loan_id,
        "target_device_model_id": target_device_model_id,
        "fulfillment_window_start": fulfillment_window_start,
        "expected_loan_version": int(expected_loan_version),
    }
    payload.update(overrides)
    return payload


def trade_in_declaration_payload(device_unit_id: str, declared_condition: str = "GOOD",
                                 **overrides) -> Dict[str, Any]:
    """POST /upgrade-requests/{id}/trade-in-declaration."""
    payload = {"device_unit_id": device_unit_id, "declared_condition": declared_condition}
    payload.update(overrides)
    return payload


def diagnostic_report_payload(screen_grade: str = "PRISTINE", battery_health_pct: int = 90,
                              water_damage_flag: bool = False, functional_pass: bool = True,
                              **overrides) -> Dict[str, Any]:
    """POST /trade-ins/{id}/diagnostic-reports — the four bench measurements."""
    payload = {
        "screen_grade": screen_grade,
        "battery_health_pct": int(battery_health_pct),
        "water_damage_flag": bool(water_damage_flag),
        "functional_pass": bool(functional_pass),
    }
    payload.update(overrides)
    return payload


def regrade_payload(screen_grade: str = "PRISTINE", battery_health_pct: int = 90,
                    water_damage_flag: bool = False, functional_pass: bool = True,
                    override_reason: str = "Bench re-inspection after dispute",
                    **overrides) -> Dict[str, Any]:
    """POST /trade-ins/{id}/regrade — the four measurements plus a mandatory
    override_reason."""
    payload = {
        "screen_grade": screen_grade,
        "battery_health_pct": int(battery_health_pct),
        "water_damage_flag": bool(water_damage_flag),
        "functional_pass": bool(functional_pass),
        "override_reason": override_reason,
    }
    payload.update(overrides)
    return payload


def dispute_payload(dispute_reason: str = "Screen was intact at hand-over",
                    **overrides) -> Dict[str, Any]:
    """POST /trade-ins/{id}/dispute."""
    payload = {"dispute_reason": dispute_reason}
    payload.update(overrides)
    return payload


def completion_payload(payoff_quote_id: str, target_imei: str = None,
                       **overrides) -> Dict[str, Any]:
    """POST /upgrade-requests/{id}/completion — additional_down_payment_cents is
    optional and defaults to zero."""
    payload = {
        "payoff_quote_id": payoff_quote_id,
        "target_imei": target_imei if target_imei is not None else next_imei(),
    }
    payload.update(overrides)
    return payload


def clock_payload(to_iso8601: str = CLOCK_ORIGIN, **overrides) -> Dict[str, Any]:
    """POST /_clock/set_current_utc."""
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload
