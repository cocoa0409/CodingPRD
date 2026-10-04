"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "LEGAL_NAME": "Test Fund Co",
    "COMMERCIAL_RELATIONSHIP": "NONE",
    "TICKER": "TESTX",
    "INCEPTION_DATE": "2020-01-01",
    "R3_BP": 5000,
    "R5_BP": 5000,
    "RISK_BP": 3000,
    "AS_OF_DATE": "2026-08-31",
    "CATEGORY_CODE": "CAT1",
    "METHODOLOGY_CODE": "QM1",
    "METHODOLOGY_KIND": "QUANTITATIVE",
    "VERSION_NUMBER": 1,
    "EFFECTIVE_FROM": "2026-01-01",
    "WEIGHT_RETURN_BP": 6000,
    "WEIGHT_RISK_BP": 4000,
    "RATING_CEILINGS": [7000, 5000, 3000, 1000],
    "LICENSEE_NAME": "Test Licensee",
    "TIER": "DISPLAY",
    "SEAT_LIMIT": 5,
    "BASE_FEE_CENTS": 1000000,
    "INDEX_CODE": "IDX1",
    "MAX_CONSTITUENTS": 10,
    "CAP_BP": 5000,
    "TARGET_WEIGHT_BP": 4000,
    "CHANGE_EFFECTIVE_DATE": "2026-09-01",
}


def create_fund_company_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "commercial_relationship": DEFAULTS["COMMERCIAL_RELATIONSHIP"],
    }
    defaults.update(overrides)
    return defaults


def create_fund_payload(fund_company_id, **overrides) -> dict:
    defaults = {
        "fund_company_id": fund_company_id,
        "ticker": DEFAULTS["TICKER"],
        "inception_date": DEFAULTS["INCEPTION_DATE"],
        "trailing_return_3y_bp": DEFAULTS["R3_BP"],
        "trailing_return_5y_bp": DEFAULTS["R5_BP"],
        "risk_score_bp": DEFAULTS["RISK_BP"],
    }
    defaults.update(overrides)
    return defaults


def create_holdings_payload(holdings=None, **overrides) -> dict:
    """A valid snapshot payload. Default: one EQUITY/TECH holding at 10000 bp."""
    defaults = {
        "as_of_date": DEFAULTS["AS_OF_DATE"],
        "holdings": holdings
        if holdings is not None
        else [
            {
                "security_ticker": "AAA",
                "asset_class": "EQUITY",
                "sector": "TECH",
                "weight_bp": 10000,
            }
        ],
    }
    defaults.update(overrides)
    return defaults


def create_category_payload(**overrides) -> dict:
    defaults = {
        "category_code": DEFAULTS["CATEGORY_CODE"],
        "dominant_asset_class": "EQUITY",
        "dominant_sector": "MIXED",
        "min_weight_bp": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_methodology_payload(**overrides) -> dict:
    defaults = {
        "methodology_code": DEFAULTS["METHODOLOGY_CODE"],
        "methodology_kind": DEFAULTS["METHODOLOGY_KIND"],
        "version_number": DEFAULTS["VERSION_NUMBER"],
        "effective_from": DEFAULTS["EFFECTIVE_FROM"],
        "weight_return_bp": DEFAULTS["WEIGHT_RETURN_BP"],
        "weight_risk_bp": DEFAULTS["WEIGHT_RISK_BP"],
        "rating_ceilings": list(DEFAULTS["RATING_CEILINGS"]),
    }
    defaults.update(overrides)
    return defaults


def propose_change_payload(expected_methodology_version, **overrides) -> dict:
    defaults = {
        "restatement_required": False,
        "effective_date": DEFAULTS["CHANGE_EFFECTIVE_DATE"],
        "expected_methodology_version": expected_methodology_version,
    }
    defaults.update(overrides)
    return defaults


def create_licensee_payload(**overrides) -> dict:
    defaults = {"licensee_name": DEFAULTS["LICENSEE_NAME"]}
    defaults.update(overrides)
    return defaults


def create_agreement_payload(licensee_id, **overrides) -> dict:
    defaults = {
        "licensee_id": licensee_id,
        "tier": DEFAULTS["TIER"],
        "seat_limit": DEFAULTS["SEAT_LIMIT"],
        "effective_from": DEFAULTS["EFFECTIVE_FROM"],
        "base_fee_cents": DEFAULTS["BASE_FEE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def grant_seat_payload(expected_agreement_version, **overrides) -> dict:
    defaults = {
        "workstation_user_id": "ws-default",
        "expected_agreement_version": expected_agreement_version,
    }
    defaults.update(overrides)
    return defaults


def create_index_payload(methodology_id, **overrides) -> dict:
    defaults = {
        "index_code": DEFAULTS["INDEX_CODE"],
        "methodology_id": methodology_id,
        "max_constituents": DEFAULTS["MAX_CONSTITUENTS"],
        "single_constituent_cap_bp": DEFAULTS["CAP_BP"],
    }
    defaults.update(overrides)
    return defaults


def add_constituent_payload(fund_id, **overrides) -> dict:
    defaults = {
        "fund_id": fund_id,
        "target_weight_bp": DEFAULTS["TARGET_WEIGHT_BP"],
    }
    defaults.update(overrides)
    return defaults


def raise_dispute_payload(raised_by_company_id, **overrides) -> dict:
    defaults = {
        "raised_by_company_id": raised_by_company_id,
        "disputed_field": "RISK_SCORE",
        "corrected_value": 1000,
    }
    defaults.update(overrides)
    return defaults
