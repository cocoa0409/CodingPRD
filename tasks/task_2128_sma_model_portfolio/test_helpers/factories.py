"""Payload factories — one per write endpoint, input fields only.

Every factory takes `**overrides`; optional inputs are omitted unless the caller
supplies them, so the server-side defaults declared by the PRD stay observable.
"""

DEFAULTS = {
    "SECURITY_NAME": "Alfa Industrials",
    "SECURITY_TICKER": "ALFA",
    "SECURITY_PRICE_CENTS": 10_000,
    "SPONSOR_NAME": "Northline Wealth",
    "SPONSOR_CODE": "NRTH",
    "REVENUE_SHARE_BPS": 3333,
    "MANAGER_NAME": "Cobalt Asset Mgmt",
    "MODEL_NAME": "Core Equity",
    "STRATEGY_CODE": "CORE",
    "ASSET_CLASS": "US_EQUITY",
    "BASE_FEE_BPS": 90,
    "ACCOUNT_NUMBER": "ACC-001",
    "PERIOD_START": "2026-01-01T00:00:00Z",
    "PERIOD_END": "2026-04-01T00:00:00Z",
    "AVERAGE_DAILY_VALUE_CENTS": 30_000_000,
    "EFFECTIVE_FROM": "2026-01-01T00:00:00Z",
}


def _payload(base: dict, overrides: dict) -> dict:
    base.update(overrides)
    return base


# --------------------------------------------------------------------- Security
def create_security_payload(**overrides) -> dict:
    return _payload(
        {
            "ticker": DEFAULTS["SECURITY_TICKER"],
            "name": DEFAULTS["SECURITY_NAME"],
            "asset_class": DEFAULTS["ASSET_CLASS"],
            "last_price_cents": DEFAULTS["SECURITY_PRICE_CENTS"],
        },
        overrides,
    )


def reprice_security_payload(last_price_cents: int) -> dict:
    return {"last_price_cents": last_price_cents}


# ---------------------------------------------------------------------- Sponsor
def create_sponsor_payload(**overrides) -> dict:
    return _payload(
        {
            "name": DEFAULTS["SPONSOR_NAME"],
            "platform_code": DEFAULTS["SPONSOR_CODE"],
            "revenue_share_bps": DEFAULTS["REVENUE_SHARE_BPS"],
        },
        overrides,
    )


# ------------------------------------------------------------------------ Model
def create_model_payload(**overrides) -> dict:
    return _payload(
        {
            "manager_name": DEFAULTS["MANAGER_NAME"],
            "name": DEFAULTS["MODEL_NAME"],
            "strategy_code": DEFAULTS["STRATEGY_CODE"],
            "asset_class": DEFAULTS["ASSET_CLASS"],
            "base_fee_bps": DEFAULTS["BASE_FEE_BPS"],
        },
        overrides,
    )


# ----------------------------------------------------------------- ModelVersion
def create_model_version_payload(model_id: str, **overrides) -> dict:
    return _payload({"model_id": model_id}, overrides)


def sleeves_payload(sleeves) -> dict:
    """`sleeves` is the complete replacement array of sleeve objects."""
    return {"sleeves": list(sleeves)}


def sleeve(security_id: str, target_weight_bps: int, max_position_bps=None) -> dict:
    entry = {"security_id": security_id, "target_weight_bps": target_weight_bps}
    if max_position_bps is not None:
        entry["max_position_bps"] = max_position_bps
    return entry


def reject_model_version_payload(rejection_note: str) -> dict:
    return {"rejection_note": rejection_note}


# --------------------------------------------------------- SponsorDistribution
def create_distribution_payload(
    sponsor_id: str,
    model_version_id: str,
    expected_model_version_version: int,
    effective_from: str = None,
    **overrides,
) -> dict:
    base = {
        "sponsor_id": sponsor_id,
        "model_version_id": model_version_id,
        "effective_from": effective_from or DEFAULTS["EFFECTIVE_FROM"],
        "expected_model_version_version": expected_model_version_version,
    }
    return _payload(base, overrides)


# ---------------------------------------------------------------------- Account
def create_account_payload(sponsor_id: str, model_id: str, **overrides) -> dict:
    return _payload(
        {
            "sponsor_id": sponsor_id,
            "model_id": model_id,
            "account_number": DEFAULTS["ACCOUNT_NUMBER"],
        },
        overrides,
    )


def deposit_payload(amount_cents: int) -> dict:
    return {"amount_cents": amount_cents}


def transfer_in_payload(
    security_id: str, shares: int, cost_basis_cents: int, **overrides
) -> dict:
    return _payload(
        {
            "security_id": security_id,
            "shares": shares,
            "cost_basis_cents": cost_basis_cents,
        },
        overrides,
    )


def drift_evaluation_payload(basis=None) -> dict:
    return {} if basis is None else {"basis": basis}


def performance_observation_payload(
    period_end: str, gross_return_bps: int, ending_value_cents: int
) -> dict:
    return {
        "period_end": period_end,
        "gross_return_bps": gross_return_bps,
        "ending_value_cents": ending_value_cents,
    }


# ----------------------------------------------------------- AccountRestriction
def create_restriction_payload(
    account_id: str, security_id: str, restriction_type: str, **overrides
) -> dict:
    return _payload(
        {
            "account_id": account_id,
            "security_id": security_id,
            "restriction_type": restriction_type,
        },
        overrides,
    )


# ------------------------------------------------------------------------ Block
def create_block_payload(trade_order_ids) -> dict:
    return {"trade_order_ids": list(trade_order_ids)}


def execute_block_payload(filled_shares: int, avg_fill_price_cents: int) -> dict:
    return {
        "filled_shares": filled_shares,
        "avg_fill_price_cents": avg_fill_price_cents,
    }


# --------------------------------------------------------------- HarvestProposal
def create_harvest_proposal_payload(
    account_id: str, security_id: str, shares: int, expected_account_version: int, **overrides
) -> dict:
    return _payload(
        {
            "account_id": account_id,
            "security_id": security_id,
            "shares": shares,
            "expected_account_version": expected_account_version,
        },
        overrides,
    )


def reject_harvest_payload(rejection_note: str) -> dict:
    return {"rejection_note": rejection_note}


# -------------------------------------------------------------------- FeeInvoice
def create_fee_invoice_payload(account_id: str, **overrides) -> dict:
    return _payload(
        {
            "account_id": account_id,
            "period_start": DEFAULTS["PERIOD_START"],
            "period_end": DEFAULTS["PERIOD_END"],
            "average_daily_value_cents": DEFAULTS["AVERAGE_DAILY_VALUE_CENTS"],
        },
        overrides,
    )


def void_invoice_payload(void_reason: str) -> dict:
    return {"void_reason": void_reason}


# ------------------------------------------------------------------------ Clock
def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
