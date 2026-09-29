"""Payload factories — one per resource, input fields only (PRD §3, §4).

Money is always an integer number of minor units and percentages are JSON
numbers carrying at most four decimals (PRD §2.6). Instants are full ISO-8601
UTC strings with exactly three fractional digits (PRD §2.4).
"""
from typing import Any, Dict

from .constants import (
    CANONICAL_CAT_LAYER,
    CANONICAL_QUOTA_SHARE_LAYER,
    CANONICAL_XOL_LAYER,
    CLOCK,
    TEST_DEFAULTS,
)


def _merge(defaults: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(defaults)
    payload.update(overrides)
    return {key: value for key, value in payload.items() if value is not _OMIT}


_OMIT = object()
OMIT = _OMIT  # pass OMIT as an override value to drop a defaulted field entirely


# --------------------------------------------------------------------------
# Registry (PRD §3.1)
# --------------------------------------------------------------------------
def create_cedent_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "name": TEST_DEFAULTS["CEDENT_NAME"],
            "domicile_code": TEST_DEFAULTS["DOMICILE_CODE"],
            "financial_rating": TEST_DEFAULTS["FINANCIAL_RATING"],
        },
        overrides,
    )


def create_reinsurer_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "name": "Alpha Re",
            "security_rating": "AA",
            "capacity_limit_minor": TEST_DEFAULTS["REINSURER_CAPACITY_MINOR"],
            "max_line_pct": TEST_DEFAULTS["REINSURER_MAX_LINE_PCT"],
            "lead_authorised": True,
        },
        overrides,
    )


def suspend_cedent_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {"status": "SUSPENDED", "suspension_reason": "Regulatory review"}, overrides
    )


def security_status_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {"security_status": "SUSPENDED", "reason": "Rating downgrade"}, overrides
    )


# --------------------------------------------------------------------------
# Programs (PRD §3.1)
# --------------------------------------------------------------------------
def create_program_payload(cedent_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "cedent_id": cedent_id,
            "program_name": TEST_DEFAULTS["PROGRAM_NAME"],
            "line_of_business": TEST_DEFAULTS["LINE_OF_BUSINESS"],
            "underwriting_year": TEST_DEFAULTS["UNDERWRITING_YEAR"],
            "inception_date": CLOCK["INCEPTION"],
            "expiry_date": CLOCK["EXPIRY"],
            "estimated_premium_income_minor": TEST_DEFAULTS[
                "ESTIMATED_PREMIUM_INCOME_MINOR"
            ],
            "brokerage_pct": TEST_DEFAULTS["BROKERAGE_PCT"],
        },
        overrides,
    )


def withdraw_program_payload(**overrides) -> Dict[str, Any]:
    return _merge({"reason": "Cedent cancelled the renewal"}, overrides)


# --------------------------------------------------------------------------
# Exposure submissions (PRD §3.2)
# --------------------------------------------------------------------------
def create_exposure_submission_payload(**overrides) -> Dict[str, Any]:
    """Defaults score 40*0.98 + 25 + 22.5 + 10 = 96.70 (PRD §3.2)."""
    return _merge(
        {
            "package_label": TEST_DEFAULTS["PACKAGE_LABEL"],
            "exposure_records_count": 1000,
            "data_quality_flags_count": 20,
            "historical_years_supplied": 5,
            "cat_model_version": TEST_DEFAULTS["CAT_MODEL_VERSION"],
            "loss_history_completeness_pct": 90.0000,
            "actuarial_report_attached": True,
        },
        overrides,
    )


def signoff_payload(decision: str = "SIGNED_OFF", **overrides) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


def revise_exposure_submission_payload(**overrides) -> Dict[str, Any]:
    return _merge({}, overrides)


# --------------------------------------------------------------------------
# Layers (PRD §3.3)
# --------------------------------------------------------------------------
def create_layer_payload(**overrides) -> Dict[str, Any]:
    """The canonical catastrophe layer (frozen gross premium 97,125,000)."""
    return _merge(dict(CANONICAL_CAT_LAYER), overrides)


def create_quota_share_layer_payload(**overrides) -> Dict[str, Any]:
    """The canonical quota-share layer (frozen gross premium 740,000,000)."""
    return _merge(dict(CANONICAL_QUOTA_SHARE_LAYER), overrides)


def create_xol_layer_payload(**overrides) -> Dict[str, Any]:
    """The canonical excess-of-loss layer (frozen gross premium 9,750,000)."""
    return _merge(dict(CANONICAL_XOL_LAYER), overrides)


def update_layer_payload(**overrides) -> Dict[str, Any]:
    return _merge({}, overrides)


# --------------------------------------------------------------------------
# Market submissions, quotes and firm orders (PRD §3.4, §3.5)
# --------------------------------------------------------------------------
def create_market_submission_payload(reinsurer_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "reinsurer_id": reinsurer_id,
            "response_deadline": CLOCK["RESPONSE_DEADLINE"],
        },
        overrides,
    )


def create_quote_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "offered_line_pct": 100.0000,
            "quoted_rate_pct": 8.0000,
            "ceding_commission_pct": 0.0000,
            "reinstatements_offered": 1,
            "sublimit_minor": 0,
            "expires_at": CLOCK["QUOTE_EXPIRY"],
            "is_lead": True,
        },
        overrides,
    )


def requote_payload(**overrides) -> Dict[str, Any]:
    return create_quote_payload(**overrides)


def counter_payload(counter_note: str = "please sharpen the rate", **overrides) -> Dict[str, Any]:
    return _merge({"counter_note": counter_note}, overrides)


def decline_payload(**overrides) -> Dict[str, Any]:
    return _merge({"decline_reason": "outside appetite"}, overrides)


def firm_order_payload(accepted_line_pct: float, expected_layer_version: int, **overrides):
    return _merge(
        {
            "accepted_line_pct": accepted_line_pct,
            "expected_layer_version": expected_layer_version,
        },
        overrides,
    )


# --------------------------------------------------------------------------
# Brokerage disclosures (PRD §3.6)
# --------------------------------------------------------------------------
def create_brokerage_disclosure_payload(**overrides) -> Dict[str, Any]:
    return _merge({"brokerage_pct": TEST_DEFAULTS["BROKERAGE_PCT"]}, overrides)


def disclosure_decision_payload(decision: str = "ACKNOWLEDGE", **overrides) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


# --------------------------------------------------------------------------
# Contract documents (PRD §3.7)
# --------------------------------------------------------------------------
def create_contract_document_payload(
    document_type: str = "SLIP", wording_reference: str = "NW-PROP-2026-SLIP", **overrides
) -> Dict[str, Any]:
    return _merge(
        {"document_type": document_type, "wording_reference": wording_reference}, overrides
    )


# --------------------------------------------------------------------------
# Fiduciary transactions (PRD §3.8)
# --------------------------------------------------------------------------
def create_fiduciary_transaction_payload(
    txn_type: str, amount_minor: int, expected_program_version: int, **overrides
) -> Dict[str, Any]:
    return _merge(
        {
            "txn_type": txn_type,
            "amount_minor": amount_minor,
            "expected_program_version": expected_program_version,
        },
        overrides,
    )


# --------------------------------------------------------------------------
# Claims advocacy (PRD §3.9)
# --------------------------------------------------------------------------
def create_claim_advocacy_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "claim_reference": "CLM-2026-0001",
            "event_date": "2026-03-01T00:00:00.000Z",
            "gross_claim_minor": 2_600_000_000,
        },
        overrides,
    )


def advocacy_route_payload(route: str = "NEGOTIATION", **overrides) -> Dict[str, Any]:
    return _merge({"route": route}, overrides)


def create_cession_dispute_payload(
    signing_line_id: str, disputed_minor: int, **overrides
) -> Dict[str, Any]:
    return _merge(
        {
            "signing_line_id": signing_line_id,
            "disputed_minor": disputed_minor,
            "dispute_reason": "EXCLUSION_APPLIES",
        },
        overrides,
    )


def resolve_dispute_payload(resolution: str, settled_minor: int, **overrides) -> Dict[str, Any]:
    return _merge({"resolution": resolution, "settled_minor": settled_minor}, overrides)


def create_collection_payload(
    signing_line_id: str, amount_minor: int, **overrides
) -> Dict[str, Any]:
    return _merge(
        {"signing_line_id": signing_line_id, "amount_minor": amount_minor}, overrides
    )
