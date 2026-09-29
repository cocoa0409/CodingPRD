"""Payload factories — one per write endpoint, input fields only.

Every monetary value is an integer count of cents and every percentage is a
decimal fraction, exactly as the PRD requires. Accounting months are
``YYYY-MM`` strings and every date is a date-only ``YYYY-MM-DD`` string.
"""

import itertools

_MID_COUNTER = itertools.count(1)
_CHECKSUM_COUNTER = itertools.count(1)


def unique_mid(prefix: str = "MID") -> str:
    """A processor merchant identifier that is unique within one test run."""
    return f"{prefix}-{next(_MID_COUNTER):06d}"


def unique_checksum(prefix: str = "sha256:auto") -> str:
    """A file checksum that is unique within one test run."""
    return f"{prefix}-{next(_CHECKSUM_COUNTER):06d}"


def create_processor_program_payload(**overrides) -> dict:
    payload = {
        "name": "FirstAtlantic Core",
        "buy_rate_bps": 45,
        "buy_rate_per_item_cents": 6,
        "assessment_bps": 13,
        "normalization_mode": "NET_REVENUE_SPLIT",
    }
    payload.update(overrides)
    return payload


def create_agent_payload(**overrides) -> dict:
    payload = {
        "name": "A1 Principal",
        "split_pct": 0.45,
        "override_pct": 0.45,
        "vesting_start_date": "2024-01-15",
    }
    payload.update(overrides)
    return payload


def create_merchant_payload(owning_agent_id: str, processor_program_id: str, **overrides) -> dict:
    payload = {
        "owning_agent_id": owning_agent_id,
        "processor_program_id": processor_program_id,
        "mid": unique_mid(),
        "monthly_minimum_cents": 2500,
        "per_transaction_fee_cents": 15,
        "equipment_lease_monthly_cents": 3900,
        "boarded_on": "2026-04-10",
    }
    payload.update(overrides)
    return payload


def create_residual_batch_payload(processor_program_id: str, **overrides) -> dict:
    payload = {
        "processor_program_id": processor_program_id,
        "period_month": "2026-07",
        "coverage_start": "2026-07-01",
        "coverage_end": "2026-08-01",
        "file_checksum": unique_checksum(),
    }
    payload.update(overrides)
    return payload


def create_residual_line_payload(merchant_id: str, **overrides) -> dict:
    payload = {
        "merchant_id": merchant_id,
        "transaction_count": 1240,
        "sales_volume_cents": 4812355,
        "interchange_cents": 92140,
        "assessments_cents": 6255,
        "gross_income_cents": 168430,
    }
    payload.update(overrides)
    return payload


def create_thin_residual_line_payload(merchant_id: str, **overrides) -> dict:
    """A small line: 125 authorizations, 3,200 cents of fee income."""
    payload = {
        "merchant_id": merchant_id,
        "transaction_count": 125,
        "sales_volume_cents": 100000,
        "interchange_cents": 1800,
        "assessments_cents": 130,
        "gross_income_cents": 3200,
    }
    payload.update(overrides)
    return payload


def create_chargeback_payload(**overrides) -> dict:
    payload = {
        "amount_cents": 4500,
        "occurred_on": "2026-07-12",
        "period_month": "2026-07",
        "liability": "AGENT_CHARGED",
    }
    payload.update(overrides)
    return payload


def create_advance_payload(expected_agent_version: int, **overrides) -> dict:
    """Straight-line amortization advance by default."""
    payload = {
        "advance_type": "CASH_ADVANCE",
        "recoupment_mode": "STRAIGHT_LINE_AMORTIZATION",
        "principal_cents": 30000,
        "amortization_months": 6,
        "first_recoupment_month": "2026-07",
        "last_recoupment_month": "2026-12",
        "funded_on": "2026-07-05",
        "expected_agent_version": expected_agent_version,
    }
    payload.update(overrides)
    return payload


def create_percent_advance_payload(expected_agent_version: int, **overrides) -> dict:
    """Percent-of-residual advance; ``amortization_months`` still bounds the window."""
    payload = {
        "advance_type": "CASH_ADVANCE",
        "recoupment_mode": "PERCENT_OF_RESIDUAL",
        "principal_cents": 30000,
        "recoupment_pct": 0.25,
        "amortization_months": 6,
        "first_recoupment_month": "2026-07",
        "last_recoupment_month": "2026-12",
        "funded_on": "2026-07-05",
        "expected_agent_version": expected_agent_version,
    }
    payload.update(overrides)
    return payload


def create_adjustment_payload(expected_statement_version: int, **overrides) -> dict:
    payload = {
        "kind": "DISPUTE_CREDIT",
        "amount_cents": 5000,
        "reason": "Interchange misposting credited back to the agent",
        "expected_statement_version": expected_statement_version,
    }
    payload.update(overrides)
    return payload


def attrite_merchant_payload(attrition_date: str = "2026-07-20", **overrides) -> dict:
    payload = {"attrition_date": attrition_date}
    payload.update(overrides)
    return payload


def reactivate_merchant_payload(reactivation_date: str = "2026-07-25", **overrides) -> dict:
    payload = {"reactivation_date": reactivation_date}
    payload.update(overrides)
    return payload


def reassign_agent_payload(new_agent_id: str, expected_merchant_version: int, **overrides) -> dict:
    payload = {
        "new_agent_id": new_agent_id,
        "expected_merchant_version": expected_merchant_version,
    }
    payload.update(overrides)
    return payload


def notice_payload(departure_effective_date: str, **overrides) -> dict:
    payload = {"departure_effective_date": departure_effective_date}
    payload.update(overrides)
    return payload


def transfer_portfolio_payload(target_agent_id: str, **overrides) -> dict:
    payload = {"target_agent_id": target_agent_id}
    payload.update(overrides)
    return payload


def hold_payload(hold_reason: str = "MANUAL_REVIEW", **overrides) -> dict:
    payload = {"hold_reason": hold_reason}
    payload.update(overrides)
    return payload


def settle_payload(paid_on: str = "2026-08-15", **overrides) -> dict:
    payload = {"paid_on": paid_on}
    payload.update(overrides)
    return payload


def request_info_payload(info_request_note: str = "Provide the processor dispute record", **overrides) -> dict:
    payload = {"info_request_note": info_request_note}
    payload.update(overrides)
    return payload


def resubmit_payload(**overrides) -> dict:
    payload: dict = {}
    payload.update(overrides)
    return payload


def reject_payload(**overrides) -> dict:
    payload: dict = {}
    payload.update(overrides)
    return payload


def restructure_advance_payload(**overrides) -> dict:
    payload: dict = {}
    payload.update(overrides)
    return payload
