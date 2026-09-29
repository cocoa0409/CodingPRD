"""Payload factories -- one per resource, client-supplied input fields only.

Money is always a JSON integer number of cents and every rate or ratio a JSON
integer number of basis points; calendar dates are year-month-day strings and
instants are full ISO 8601 UTC instants.
"""
import itertools

from .constants import DEFAULT_CLOCK_INSTANT, TEST_DEFAULTS

_counter = itertools.count(1)


def unique_suffix() -> str:
    """Monotonic suffix so uniqueness-keyed fields do not collide inside a test."""
    return f"{next(_counter):04d}"


def clock_payload(current_utc: str = DEFAULT_CLOCK_INSTANT, **overrides) -> dict:
    payload = {"current_utc": current_utc}
    payload.update(overrides)
    return payload


def institution_payload(**overrides) -> dict:
    """Bank registration payload (PRD §3.1)."""
    defaults = {
        "legal_name": "Ladder Bank NA",
        "cert_id": f"CERT-{unique_suffix()}",
        "capital_category": "WELL_CAPITALIZED",
        "core_deposits_cents": TEST_DEFAULTS["CORE_DEPOSITS_CENTS"],
        "total_liabilities_cents": TEST_DEFAULTS["TOTAL_LIABILITIES_CENTS"],
        "tier1_capital_cents": TEST_DEFAULTS["TIER1_CAPITAL_CENTS"],
        "liquidity_buffer_cents": TEST_DEFAULTS["LIQUIDITY_BUFFER_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def national_rate_cap_payload(**overrides) -> dict:
    """National rate benchmark publication payload (PRD §3.1)."""
    defaults = {
        "tenor_bucket": "DAYS_31_90",
        "published_national_rate_bps": TEST_DEFAULTS["PUBLISHED_NATIONAL_RATE_BPS"],
        "effective_date": TEST_DEFAULTS["BENCHMARK_EFFECTIVE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def broker_payload(**overrides) -> dict:
    """Counterparty registration payload (PRD §3.2)."""
    defaults = {
        "legal_name": "Ladder Deposit Brokers LLC",
        "broker_type": "DEPOSIT_BROKER",
        "has_placement_discretion": True,
        "fee_structure": "FLAT_FEE",
        "fee_flat_cents": 25000,
    }
    defaults.update(overrides)
    return defaults


def agreement_payload(**overrides) -> dict:
    """Deposit placement agreement payload (PRD §3.2).

    The default sub-scores give a composite of 74, which clears both the
    composite floor of 70 and the anti-money-laundering floor of 60.
    """
    defaults = {
        "agreement_ref": f"AGR-{unique_suffix()}",
        "fee_structure": "FLAT_FEE",
        "fee_flat_cents": 25000,
        "termination_notice_days": 30,
        "effective_date": TEST_DEFAULTS["AGREEMENT_EFFECTIVE_DATE"],
        "aml_program_score": 80,
        "financial_condition_score": 75,
        "insurance_coverage_score": 70,
        "recordkeeping_score": 65,
    }
    defaults.update(overrides)
    return defaults


def diligence_action_payload(action: str, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


def exception_payload(broker_id: str, institution_id: str, **overrides) -> dict:
    """Primary purpose exception filing payload (PRD §3.3)."""
    defaults = {
        "broker_id": broker_id,
        "institution_id": institution_id,
        "exception_basis": "TWENTY_FIVE_PERCENT_TEST",
        "designated_business_line": "Cash sweep for advisory accounts",
        "total_customer_assets_cents": 40_000_000_000,
        "deposits_placed_at_ifs_cents": 9_999_999_999,
    }
    defaults.update(overrides)
    return defaults


def program_payload(institution_id: str, **overrides) -> dict:
    """Funding program payload (PRD §3.4). Defaults describe a broker-less
    programme, so no counterparty gate applies unless the caller adds one."""
    defaults = {
        "institution_id": institution_id,
        "program_name": "60D Time Deposit Program",
        "funding_channel_claim": "CORE",
        "product_type": "TIME_DEPOSIT",
        "tenor_days": TEST_DEFAULTS["TENOR_DAYS"],
        "offered_rate_bps": TEST_DEFAULTS["OFFERED_RATE_BPS"],
        "early_withdrawal_penalty_days": 30,
        "titling_convention": "DIRECT_TITLED",
    }
    defaults.update(overrides)
    return defaults


def brokered_program_payload(institution_id: str, broker_id: str, agreement_id: str,
                             **overrides) -> dict:
    """Funding program raised through a counterparty (PRD §3.4)."""
    defaults = program_payload(
        institution_id,
        broker_id=broker_id,
        agreement_id=agreement_id,
        program_name="60D Brokered CD",
        funding_channel_claim="BROKERED",
    )
    defaults.update(overrides)
    return defaults


def classification_payload(program_id: str, expected_program_version: int,
                           **overrides) -> dict:
    """Classification determination payload (PRD §3.4)."""
    defaults = {
        "program_id": program_id,
        "expected_program_version": expected_program_version,
        "rationale_code": "PLACEMENT_DISCRETION_PRONG",
    }
    defaults.update(overrides)
    return defaults


def placement_payload(program_id: str, **overrides) -> dict:
    """Deposit tranche booking payload (PRD §3.5)."""
    defaults = {
        "program_id": program_id,
        "principal_cents": TEST_DEFAULTS["PRINCIPAL_CENTS"],
        "rate_bps": TEST_DEFAULTS["OFFERED_RATE_BPS"],
        "issue_date": TEST_DEFAULTS["ISSUE_DATE"],
        "tenor_days": TEST_DEFAULTS["TENOR_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def funding_action_payload(action: str, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


def rate_cap_check_payload(check_date: str = TEST_DEFAULTS["ISSUE_DATE"],
                           **overrides) -> dict:
    payload = {"check_date": check_date}
    payload.update(overrides)
    return payload


def concentration_limit_payload(**overrides) -> dict:
    """Board concentration limit payload (PRD §3.7)."""
    defaults = {
        "metric": "BROKERED_TO_TOTAL_DEPOSITS",
        "warning_threshold_bps": 1500,
        "breach_threshold_bps": 2000,
    }
    defaults.update(overrides)
    return defaults


def contingency_plan_payload(**overrides) -> dict:
    """Liquidity contingency plan payload (PRD §3.7)."""
    defaults = {
        "plan_version_label": f"CFP-{unique_suffix()}",
        "effective_from": "2026-08-01",
        "effective_to": "2026-12-31",
        "stage_1_trigger_bps": 300,
        "stage_2_trigger_bps": 1000,
        "stage_3_trigger_bps": 5000,
        "stage_1_action_code": "MONITOR_DAILY",
        "stage_2_action_code": "DRAW_SECURED_LINES",
        "stage_3_action_code": "ACTIVATE_CRISIS_TEAM",
    }
    defaults.update(overrides)
    return defaults


def call_report_filing_payload(**overrides) -> dict:
    """Call report filing payload (PRD §3.9)."""
    defaults = {
        "report_period": "2026Q3",
        "rc_e_brokered_reported_cents": 0,
        "rc_o_listing_reported_cents": 0,
        "rc_e_core_reported_cents": TEST_DEFAULTS["CORE_DEPOSITS_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def maturity_run_payload(as_of_date: str, **overrides) -> dict:
    payload = {"as_of_date": as_of_date}
    payload.update(overrides)
    return payload
