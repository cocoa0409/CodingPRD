"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "SYSTEM_NAME": "Riverside Water",
    "MUNICIPALITY_NAME": "Riverside",
    "STATE_CODE": "PA",
    "SYSTEM_TYPE": "WATER",
    "CUSTOMER_COUNT": 100,
    "PERMITTED_METHODS": ["FMV_INDEPENDENT"],
    "NOTES": "field survey",
    "CATEGORY": "DISTRIBUTION",
    "HORIZON": "IMMEDIATE",
    "DESCRIPTION": "main replacement",
    "COST_LOW": 1000,
    "COST_HIGH": 1000,
    "CREWS": 1,
    "METHOD": "FMV_INDEPENDENT",
    "VALUE_CENTS": 5000000,
    "LAW_CITATION": "66 Pa.C.S. 1329",
    "HEARING_START": "2026-09-02T00:00:00Z",
    "HEARING_END": "2026-09-02T02:00:00Z",
    "PURCHASE_PRICE": 5000000,
    "RATE_BASE_METHOD": "AS_PAID",
    "ACCOUNT_REF": "ACCT-1",
    "DEPOSIT_CENTS": 0,
    "AR_BALANCE_CENTS": 0,
    "EMPLOYEE_REF": "EMP-1",
    "YEARS_OF_SERVICE": 3,
    "WEEKLY_SALARY_CENTS": 100000,
    "UNION_COVERED": False,
    "TARIFF_MODE": "STAND_ALONE",
    "OLD_BILL": 5000,
    "CONSOLIDATED_BILL": 5000,
}


def create_target_payload(**overrides) -> dict:
    defaults = {
        "system_name": DEFAULTS["SYSTEM_NAME"],
        "municipality_name": DEFAULTS["MUNICIPALITY_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
        "system_type": DEFAULTS["SYSTEM_TYPE"],
        "customer_count": DEFAULTS["CUSTOMER_COUNT"],
        "permitted_valuation_methods": list(DEFAULTS["PERMITTED_METHODS"]),
    }
    defaults.update(overrides)
    return defaults


def create_assessment_payload(**overrides) -> dict:
    defaults = {"notes": DEFAULTS["NOTES"]}
    defaults.update(overrides)
    return defaults


def create_capital_item_payload(**overrides) -> dict:
    defaults = {
        "category": DEFAULTS["CATEGORY"],
        "horizon": DEFAULTS["HORIZON"],
        "description": DEFAULTS["DESCRIPTION"],
        "cost_low_cents": DEFAULTS["COST_LOW"],
        "cost_high_cents": DEFAULTS["COST_HIGH"],
        "crews_required": DEFAULTS["CREWS"],
    }
    defaults.update(overrides)
    return defaults


def create_valuation_case_payload(expected_target_version, **overrides) -> dict:
    defaults = {"expected_target_version": expected_target_version}
    defaults.update(overrides)
    return defaults


def create_valuation_entry_payload(**overrides) -> dict:
    defaults = {
        "method": DEFAULTS["METHOD"],
        "value_cents": DEFAULTS["VALUE_CENTS"],
        "law_citation": DEFAULTS["LAW_CITATION"],
    }
    defaults.update(overrides)
    return defaults


def create_council_event_payload(kind="PUBLIC_HEARING", **overrides) -> dict:
    defaults = {
        "kind": kind,
        "scheduled_start": DEFAULTS["HEARING_START"],
        "scheduled_end": DEFAULTS["HEARING_END"],
    }
    defaults.update(overrides)
    return defaults


def create_regulatory_application_payload(**overrides) -> dict:
    defaults = {
        "purchase_price_cents": DEFAULTS["PURCHASE_PRICE"],
        "rate_base_method": DEFAULTS["RATE_BASE_METHOD"],
    }
    defaults.update(overrides)
    return defaults


def create_customer_account_payload(**overrides) -> dict:
    defaults = {
        "account_ref": DEFAULTS["ACCOUNT_REF"],
        "deposit_cents": DEFAULTS["DEPOSIT_CENTS"],
        "ar_balance_cents": DEFAULTS["AR_BALANCE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_employee_transition_payload(**overrides) -> dict:
    defaults = {
        "employee_ref": DEFAULTS["EMPLOYEE_REF"],
        "years_of_service": DEFAULTS["YEARS_OF_SERVICE"],
        "weekly_salary_cents": DEFAULTS["WEEKLY_SALARY_CENTS"],
        "union_covered": DEFAULTS["UNION_COVERED"],
    }
    defaults.update(overrides)
    return defaults


def create_tariff_case_payload(**overrides) -> dict:
    defaults = {
        "mode": DEFAULTS["TARIFF_MODE"],
        "representative_old_bill_cents": DEFAULTS["OLD_BILL"],
        "consolidated_monthly_bill_cents": DEFAULTS["CONSOLIDATED_BILL"],
    }
    defaults.update(overrides)
    return defaults
