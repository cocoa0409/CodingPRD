"""Payload factories — one per entity, input fields only.

Every money figure is a JSON-native integer number of cents and every name,
piece, page and square-inch figure is a JSON-native integer. Nothing here ever
sends a numeric value as a string.
"""
from .api_client import iso_utc

# Reference figures shared by the factories. The segment defaults score
# 40 + 30 + 30 = 100 points, so rfm_score is 1000 and segment_tier is BEST.
DEFAULTS = {
    "SEASON_CODE": "FW26",
    "FISCAL_YEAR": 2026,
    "SEGMENT_CODE": "S_A",
    "SEGMENT_RECENCY_DAYS": 45,
    "SEGMENT_ORDERS_12MO": 7,
    "SEGMENT_LTV_CENTS": 62000,
    "SEGMENT_HOUSEFILE_COUNT": 30000,
    "SEGMENT_AVG_ORDER_VALUE_CENTS": 18500,
    "SEGMENT_RESPONSE_BPS": 620,
    "RENTAL_NAME": "COOP_ALPHA",
    "RENTAL_REQUESTED_GROSS_NAMES": 25000,
    "RENTAL_CPM_CENTS": 8500,
    "PLAN_CODE": "FW26-CIRC-V1",
    "PLAN_BUDGET_CENTS": 20000000,
    "DROP_NUMBER": 1,
    "DROP_PAGE_COUNT": 64,
    "DROP_IN_HOME_DATE": iso_utc("2026-09-15"),
    "LINE_REQUESTED_QUANTITY": 20000,
    "PLACEMENT_SKU": "SKU-1",
    "PLACEMENT_NAME": "Wool Throw",
    "PLACEMENT_UNIT_PRICE_CENTS": 12900,
    "PLACEMENT_UNIT_COGS_CENTS": 5400,
    "PLACEMENT_DEMAND_PER_SQ_INCH_CENTS": 4200,
    "TEST_CELL_CODE": "OFFER_FREESHIP_T1",
    "SUPPRESSION_RULE_CODE": "CAP_ALL_90D",
}


def create_season_payload(**overrides) -> dict:
    """Season payload carrying only the two required fields by default, so the
    rate-card defaults apply."""
    payload = {
        "season_code": DEFAULTS["SEASON_CODE"],
        "fiscal_year": DEFAULTS["FISCAL_YEAR"],
    }
    payload.update(overrides)
    return payload


def create_suppression_rule_payload(**overrides) -> dict:
    payload = {
        "rule_code": DEFAULTS["SUPPRESSION_RULE_CODE"],
        "channel_scope": "ALL",
        "window_days": 90,
        "max_contacts_per_window": 5,
        "priority": 10,
    }
    payload.update(overrides)
    return payload


def create_segment_payload(season_id, **overrides) -> dict:
    payload = {
        "season_id": season_id,
        "segment_code": DEFAULTS["SEGMENT_CODE"],
        "recency_days": DEFAULTS["SEGMENT_RECENCY_DAYS"],
        "orders_12mo": DEFAULTS["SEGMENT_ORDERS_12MO"],
        "ltv_cents": DEFAULTS["SEGMENT_LTV_CENTS"],
        "housefile_count": DEFAULTS["SEGMENT_HOUSEFILE_COUNT"],
        "avg_order_value_cents": DEFAULTS["SEGMENT_AVG_ORDER_VALUE_CENTS"],
        "historical_response_rate_bps": DEFAULTS["SEGMENT_RESPONSE_BPS"],
    }
    payload.update(overrides)
    return payload


def create_rental_payload(season_id, **overrides) -> dict:
    payload = {
        "season_id": season_id,
        "list_source_name": DEFAULTS["RENTAL_NAME"],
        "requested_gross_names": DEFAULTS["RENTAL_REQUESTED_GROSS_NAMES"],
        "cost_per_thousand_cents": DEFAULTS["RENTAL_CPM_CENTS"],
        "housefile_overlap_bps": 1000,
        "inter_list_overlap_bps": 2000,
    }
    payload.update(overrides)
    return payload


def model_rental_payload(coop_model_score=640, **overrides) -> dict:
    payload = {"coop_model_score": coop_model_score}
    payload.update(overrides)
    return payload


def deliver_rental_payload(delivered_gross_names=24000, **overrides) -> dict:
    payload = {"delivered_gross_names": delivered_gross_names}
    payload.update(overrides)
    return payload


def create_plan_payload(season_id, **overrides) -> dict:
    payload = {
        "season_id": season_id,
        "plan_code": DEFAULTS["PLAN_CODE"],
        "budget_cents": DEFAULTS["PLAN_BUDGET_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_merge_purge_run_payload(expected_plan_version, input_rental_ids=None,
                                   **overrides) -> dict:
    payload = {
        "expected_plan_version": expected_plan_version,
        "input_rental_ids": list(input_rental_ids or []),
    }
    payload.update(overrides)
    return payload


def create_drop_payload(**overrides) -> dict:
    payload = {
        "drop_number": DEFAULTS["DROP_NUMBER"],
        "in_home_date": DEFAULTS["DROP_IN_HOME_DATE"],
        "page_count": DEFAULTS["DROP_PAGE_COUNT"],
    }
    payload.update(overrides)
    return payload


def create_housefile_line_payload(housefile_segment_id, **overrides) -> dict:
    payload = {
        "audience_type": "HOUSEFILE",
        "housefile_segment_id": housefile_segment_id,
        "requested_quantity": DEFAULTS["LINE_REQUESTED_QUANTITY"],
    }
    payload.update(overrides)
    return payload


def create_rental_line_payload(prospect_list_rental_id, **overrides) -> dict:
    payload = {
        "audience_type": "RENTAL",
        "prospect_list_rental_id": prospect_list_rental_id,
        "requested_quantity": DEFAULTS["LINE_REQUESTED_QUANTITY"],
    }
    payload.update(overrides)
    return payload


def create_page_placement_payload(**overrides) -> dict:
    payload = {
        "product_sku": DEFAULTS["PLACEMENT_SKU"],
        "product_name": DEFAULTS["PLACEMENT_NAME"],
        "unit_price_cents": DEFAULTS["PLACEMENT_UNIT_PRICE_CENTS"],
        "unit_cogs_cents": DEFAULTS["PLACEMENT_UNIT_COGS_CENTS"],
        "demand_per_sq_inch_cents": DEFAULTS["PLACEMENT_DEMAND_PER_SQ_INCH_CENTS"],
        "page_number": 1,
        "sq_in_offset": 0,
        "square_inches": 44,
        "placement_position": "FRONT_COVER",
    }
    payload.update(overrides)
    return payload


def create_presort_batch_payload(piece_count, declared_tier="FIVE_DIGIT",
                                 **overrides) -> dict:
    payload = {"declared_tier": declared_tier, "piece_count": piece_count}
    payload.update(overrides)
    return payload


def create_contact_event_payload(housefile_segment_id, contact_date,
                                 channel="MAIL", **overrides) -> dict:
    payload = {
        "housefile_segment_id": housefile_segment_id,
        "channel": channel,
        "contact_date": contact_date,
    }
    payload.update(overrides)
    return payload


def create_test_cell_payload(quantity, cell_role="TEST", **overrides) -> dict:
    payload = {
        "cell_code": DEFAULTS["TEST_CELL_CODE"],
        "test_type": "OFFER",
        "cell_role": cell_role,
        "quantity": quantity,
    }
    payload.update(overrides)
    return payload


def measure_test_cell_payload(responders, demand_cents, **overrides) -> dict:
    payload = {"responders": responders, "demand_cents": demand_cents}
    payload.update(overrides)
    return payload


def create_matchback_run_payload(expected_drop_version,
                                 attribution_variant="LAST_TOUCH_MAIL",
                                 attribution_window_days=30, **overrides) -> dict:
    payload = {
        "expected_drop_version": expected_drop_version,
        "attribution_variant": attribution_variant,
        "attribution_window_days": attribution_window_days,
    }
    payload.update(overrides)
    return payload


def online_order(external_order_id, housefile_segment_id, order_date,
                 demand_cents) -> dict:
    """One element of the ecommerce order feed."""
    return {
        "external_order_id": external_order_id,
        "housefile_segment_id": housefile_segment_id,
        "order_date": order_date,
        "demand_cents": demand_cents,
    }


def ingest_orders_payload(orders) -> dict:
    return {"orders": list(orders)}


def set_clock_payload(current_utc) -> dict:
    return {"current_utc": current_utc}
