"""Payload factories — one per creatable resource / action, input fields only.

Fields whose server-side default is itself under test (``Retailer.status``,
``Category.advisory_scope``, ``CategoryAnalysis.includes_competitor_data``,
``ShelfRecommendation.sku_adds``/``sku_drops``) are deliberately NOT
defaulted here — pass them explicitly via ``**overrides`` when a test wants
them present, so omission reaches the server as omission.
"""

DEFAULTS = {
    "RETAILER_NAME": "Retailer Alpha",
    "COUNTRY_CODE": "US",
    "CHANNELS": ["MASS", "GROCERY"],
    "CATEGORY_NAME": "Laundry Care",
    "FISCAL_YEAR": 2027,
    "GROWTH_TARGET_PCT": 8,
    "WEEKLY_BASELINE_CASES": 100,
    "AVG_UNIT_NET_PRICE_CENTS": 450,
    "ACCRUAL_RATE_PCT": 4,
    "EDLP_SPLIT_PCT": 60,
    "EVENT_NAME": "Feature A",
    "EVENT_TYPE": "FEATURE",
    "EVENT_START": "2027-03-01T00:00:00Z",
    "EVENT_END": "2027-03-10T00:00:00Z",
    "DISCOUNT_DEPTH_PCT": 20,
    "ANALYSIS_TITLE": "Category Review 2027H1",
    "PERIOD_LABEL": "2027-H1",
    "TOTAL_CATEGORY_GROWTH_PCT": 6,
    "MANUFACTURER_SHARE_PCT": 55,
    "SHELF_TITLE": "Reset A",
    "SPACE_CHANGE_PCT": 5,
    "TARGET_STORE_COUNT": 100,
    "PRODUCT_NAME": "UltraTabs",
    "PACK_FAMILY": "tabs",
    "LAUNCH_DATE": "2027-01-15T00:00:00Z",
    "TOTAL_TRADE_BUDGET_CENTS": 500000,
    "PHASE_DISTRIBUTION_TARGET_PCT": 10,
    "PHASE_CAPACITY_CASES": 100,
    "PHASE_TRADE_SPEND_CENTS": 1000,
    "ACCRUAL_PERIOD": "2027-01",
    "INVOICED_SALES_CENTS": 1000000,
    "DEDUCTION_BUCKET": "EDLP",
    "DEDUCTION_AMOUNT_CENTS": 1000,
    "WEEK_START": "2027-03-01T00:00:00Z",  # a Monday
    "BASELINE_CASES": 1000,
    "COMMITTED_CASES": 1100,
    "PPD_CHANNEL": "MASS",
    "PACK_CODE": "TB-6",
    "UNIT_COUNT": 6,
    "LIST_PRICE_CENTS": 600,
    "REVIEW_PERIOD_START": "2027-01-01T00:00:00Z",
    "REVIEW_PERIOD_END": "2027-12-31T00:00:00Z",
    "ACTUAL_SALES_CENTS": 900000,
    "SALES_TARGET_CENTS": 1000000,
    "TARGET_DISTRIBUTION_PCT": 90,
    "DISTRIBUTION_ACHIEVED_PCT": 90,
}


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

def create_retailer_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["RETAILER_NAME"],
        "country_code": DEFAULTS["COUNTRY_CODE"],
        "channels": list(DEFAULTS["CHANNELS"]),
    }
    payload.update(overrides)
    return payload


def create_category_payload(**overrides) -> dict:
    payload = {"name": DEFAULTS["CATEGORY_NAME"]}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Plans and the negotiation/activation actions
# ---------------------------------------------------------------------------

def create_plan_payload(retailer_id: str, category_id: str, **overrides) -> dict:
    payload = {
        "retailer_id": retailer_id,
        "category_id": category_id,
        "fiscal_year": DEFAULTS["FISCAL_YEAR"],
        "growth_target_pct": DEFAULTS["GROWTH_TARGET_PCT"],
        "weekly_baseline_cases": DEFAULTS["WEEKLY_BASELINE_CASES"],
        "avg_unit_net_price_cents": DEFAULTS["AVG_UNIT_NET_PRICE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_negotiate_payload(growth_target_pct=9, **overrides) -> dict:
    payload = {"growth_target_pct": growth_target_pct}
    payload.update(overrides)
    return payload


def create_plan_decide_payload(decision: str = "ACCEPT", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_activate_payload(**overrides) -> dict:
    payload = {
        "accrual_rate_pct": DEFAULTS["ACCRUAL_RATE_PCT"],
        "edlp_split_pct": DEFAULTS["EDLP_SPLIT_PCT"],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Promotional events
# ---------------------------------------------------------------------------

def create_event_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["EVENT_NAME"],
        "event_type": DEFAULTS["EVENT_TYPE"],
        "start_date": DEFAULTS["EVENT_START"],
        "end_date": DEFAULTS["EVENT_END"],
        "discount_depth_pct": DEFAULTS["DISCOUNT_DEPTH_PCT"],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Category analyses
# ---------------------------------------------------------------------------

def create_analysis_payload(**overrides) -> dict:
    payload = {
        "title": DEFAULTS["ANALYSIS_TITLE"],
        "period_label": DEFAULTS["PERIOD_LABEL"],
        "total_category_growth_pct": DEFAULTS["TOTAL_CATEGORY_GROWTH_PCT"],
        "manufacturer_share_pct": DEFAULTS["MANUFACTURER_SHARE_PCT"],
    }
    payload.update(overrides)
    return payload


def create_analysis_decide_payload(decision: str = "ACCEPT", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Shelf recommendations
# ---------------------------------------------------------------------------

def create_shelf_rec_payload(expected_plan_version: int, **overrides) -> dict:
    payload = {
        "expected_plan_version": expected_plan_version,
        "title": DEFAULTS["SHELF_TITLE"],
        "space_change_pct": DEFAULTS["SPACE_CHANGE_PCT"],
        "target_store_count": DEFAULTS["TARGET_STORE_COUNT"],
    }
    payload.update(overrides)
    return payload


def create_shelf_decide_payload(decision: str = "ACCEPT", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_verify_payload(implemented_store_count: int = 100, **overrides) -> dict:
    payload = {"implemented_store_count": implemented_store_count}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Launches and phases
# ---------------------------------------------------------------------------

def create_launch_payload(**overrides) -> dict:
    payload = {
        "product_name": DEFAULTS["PRODUCT_NAME"],
        "pack_family": DEFAULTS["PACK_FAMILY"],
        "launch_date": DEFAULTS["LAUNCH_DATE"],
        "total_trade_budget_cents": DEFAULTS["TOTAL_TRADE_BUDGET_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_phase_patch_payload(**overrides) -> dict:
    payload = {
        "distribution_target_pct": DEFAULTS["PHASE_DISTRIBUTION_TARGET_PCT"],
        "capacity_cases": DEFAULTS["PHASE_CAPACITY_CASES"],
        "trade_spend_cents": DEFAULTS["PHASE_TRADE_SPEND_CENTS"],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Funds, accruals, deductions
# ---------------------------------------------------------------------------

def create_accrual_payload(period: str = None, invoiced_sales_cents: int = None, **overrides) -> dict:
    payload = {
        "period": period if period is not None else DEFAULTS["ACCRUAL_PERIOD"],
        "invoiced_sales_cents": (
            invoiced_sales_cents if invoiced_sales_cents is not None else DEFAULTS["INVOICED_SALES_CENTS"]
        ),
    }
    payload.update(overrides)
    return payload


def create_deduction_payload(claim_reference: str, **overrides) -> dict:
    payload = {
        "claim_reference": claim_reference,
        "bucket": DEFAULTS["DEDUCTION_BUCKET"],
        "amount_cents": DEFAULTS["DEDUCTION_AMOUNT_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_deduction_resolve_payload(action: str = "DISPUTE", **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Forecasts
# ---------------------------------------------------------------------------

def create_forecast_payload(**overrides) -> dict:
    payload = {
        "week_start": DEFAULTS["WEEK_START"],
        "baseline_cases": DEFAULTS["BASELINE_CASES"],
    }
    payload.update(overrides)
    return payload


def create_forecast_commit_payload(committed_cases: int = None, **overrides) -> dict:
    payload = {
        "committed_cases": committed_cases if committed_cases is not None else DEFAULTS["COMMITTED_CASES"],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Price-pack decisions
# ---------------------------------------------------------------------------

def create_ppd_payload(**overrides) -> dict:
    payload = {
        "channel": DEFAULTS["PPD_CHANNEL"],
        "pack_family": DEFAULTS["PACK_FAMILY"],
        "pack_code": DEFAULTS["PACK_CODE"],
        "unit_count": DEFAULTS["UNIT_COUNT"],
        "list_price_cents": DEFAULTS["LIST_PRICE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_ppd_decide_payload(decision: str = "APPROVE", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Performance reviews
# ---------------------------------------------------------------------------

def create_review_payload(**overrides) -> dict:
    payload = {
        "period_start": DEFAULTS["REVIEW_PERIOD_START"],
        "period_end": DEFAULTS["REVIEW_PERIOD_END"],
        "actual_sales_cents": DEFAULTS["ACTUAL_SALES_CENTS"],
        "sales_target_cents": DEFAULTS["SALES_TARGET_CENTS"],
        "target_distribution_pct": DEFAULTS["TARGET_DISTRIBUTION_PCT"],
        "distribution_achieved_pct": DEFAULTS["DISTRIBUTION_ACHIEVED_PCT"],
    }
    payload.update(overrides)
    return payload


def create_review_finalize_payload(decision: str = "CONTINUE", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

def create_clock_payload(to_iso8601: str, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload
