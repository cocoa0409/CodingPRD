"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "BRAND_OWNER_NAME": "ColaCo",
    "BRAND_OWNER_COUNTRY": "US",
    "TERRITORY_CODE": "SO-ATL-07",
    "TERRITORY_REGION": "South Atlanta 07",
    "BOTTLER_NAME": "Dixie Bottling",
    "CONCENTRATE_BASE_INDEX": 100.0,
    "ACCRUAL_BASIS": "CASE_VOLUME",
    "SERVICE_BUDGET_CENTS": 1000000,
    "LINE_CODE": "COLA-12OZ-CAN",
    "LINE_BASE_PRICE": 12.0,
    "INDEX_QUARTER": "2026-Q2",
    "INDEX_VALUE": 110.00,
    "CUSTOMER_NAME": "QuickMart 12",
    "CUSTOMER_CHANNEL": "RETAIL",
    "CUSTOMER_LOCAL_PRICE": 190,
    "NCA_CODE": "NCA-2026-01",
    "NCA_PRICE": 200,
    "NCA_START": "2026-09-01",
    "NCA_END": "2026-12-31",
    "CPO_QUANTITY": 10000,
    "CPO_QUARTER": "2026-Q3",
    "ASSET_TAG": "CDE-0001",
    "TRANSFER_BUYER": "Peachtree Consolidated",
    "TRANSFER_EBITDA": 600000000,
    "LAUNCH_COMMITTED": 50000,
    "LAUNCH_START": "2026-09-01",
    "LAUNCH_END": "2026-10-31",
    "FUND_PERIOD": "2026-09",
}


def create_brand_owner_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["BRAND_OWNER_NAME"],
        "home_country": DEFAULTS["BRAND_OWNER_COUNTRY"],
    }
    defaults.update(overrides)
    return defaults


def create_territory_payload(**overrides) -> dict:
    defaults = {
        "brand_owner_id": None,
        "code": DEFAULTS["TERRITORY_CODE"],
        "region_label": DEFAULTS["TERRITORY_REGION"],
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_agreement_payload(**overrides) -> dict:
    defaults = {
        "bottler_name": DEFAULTS["BOTTLER_NAME"],
        "concentrate_base_index": DEFAULTS["CONCENTRATE_BASE_INDEX"],
        "marketing_accrual_basis": DEFAULTS["ACCRUAL_BASIS"],
        "service_budget_cents": DEFAULTS["SERVICE_BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_product_line_payload(**overrides) -> dict:
    defaults = {
        "brand_owner_id": None,
        "line_code": DEFAULTS["LINE_CODE"],
        "concentrate_base_price_per_gallon": DEFAULTS["LINE_BASE_PRICE"],
        "is_mandatory": True,
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_price_index_payload(**overrides) -> dict:
    defaults = {
        "brand_owner_id": None,
        "quarter": DEFAULTS["INDEX_QUARTER"],
        "index_value": DEFAULTS["INDEX_VALUE"],
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_cpo_payload(**overrides) -> dict:
    defaults = {
        "agreement_id": None,
        "product_line_id": None,
        "quantity_gallons": DEFAULTS["CPO_QUANTITY"],
        "delivery_quarter": DEFAULTS["CPO_QUARTER"],
        "expected_agreement_version": None,
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_nca_payload(**overrides) -> dict:
    defaults = {
        "brand_owner_id": None,
        "nca_code": DEFAULTS["NCA_CODE"],
        "national_price_cents": DEFAULTS["NCA_PRICE"],
        "effective_start": DEFAULTS["NCA_START"],
        "effective_end": DEFAULTS["NCA_END"],
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "agreement_id": None,
        "name": DEFAULTS["CUSTOMER_NAME"],
        "channel": DEFAULTS["CUSTOMER_CHANNEL"],
        "local_price_cents": DEFAULTS["CUSTOMER_LOCAL_PRICE"],
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_dsd_order_payload(**overrides) -> dict:
    defaults = {
        "customer_id": None,
        "lines": [],
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_equipment_payload(**overrides) -> dict:
    defaults = {
        "agreement_id": None,
        "asset_tag": DEFAULTS["ASSET_TAG"],
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_service_window_payload(**overrides) -> dict:
    defaults = {
        "technician_label": "T-7",
        "window_start": "2026-10-01T10:00:00Z",
        "window_end": "2026-10-01T11:00:00Z",
        "cost_cents": 100,
    }
    defaults.update(overrides)
    return defaults


def create_fountain_account_payload(**overrides) -> dict:
    defaults = {
        "customer_id": None,
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_syrup_delivery_payload(**overrides) -> dict:
    defaults = {
        "gallons": 10,
    }
    defaults.update(overrides)
    return defaults


def create_territory_transfer_payload(**overrides) -> dict:
    defaults = {
        "territory_id": None,
        "buyer_name": DEFAULTS["TRANSFER_BUYER"],
        "reported_ebitda_cents": DEFAULTS["TRANSFER_EBITDA"],
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_innovation_launch_payload(**overrides) -> dict:
    defaults = {
        "agreement_id": None,
        "product_line_id": None,
        "committed_cases": DEFAULTS["LAUNCH_COMMITTED"],
        "launch_start": DEFAULTS["LAUNCH_START"],
        "launch_end": DEFAULTS["LAUNCH_END"],
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_fund_entry_payload(**overrides) -> dict:
    defaults = {
        "agreement_id": None,
        "entry_type": "ACCRUAL",
        "period": DEFAULTS["FUND_PERIOD"],
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}
