"""Payload factories — one per creatable resource, caller-supplied fields only."""

from .constants import TEST_DEFAULTS

# ─── Catalog part presets ─────────────────────────────────────────────────
# P1  CU-500-XHHW : copper, heavy master reel, 100 ft billing minimum.
# P3  AL-BARE-4/0 : aluminium, no copper pass-through, no cut charge.
# P4  CU-14-THHN  : copper, min_cut_length_ft sits on the 25 ft safety floor.

PRODUCT_P1 = {
    "part_number": "CU-500-XHHW",
    "conductor_metal": "COPPER",
    "copper_lbs_per_1000ft": 12.5,
    "base_price_cents_per_ft": 18,
    "min_cut_length_ft": 100,
    "cut_charge_cents": 3500,
    "reel_deposit_cents": 12500,
    "master_reel_length_ft": 2500,
    "reel_weight_lbs": 320.0,
    "allowed_put_ups": ["MASTER_REEL", "CUT"],
}

PRODUCT_P3 = {
    "part_number": "AL-BARE-4/0",
    "conductor_metal": "ALUMINUM",
    "copper_lbs_per_1000ft": 0,
    "base_price_cents_per_ft": 100,
    "min_cut_length_ft": 50,
    "cut_charge_cents": 0,
    "reel_deposit_cents": 0,
    "master_reel_length_ft": 1000,
    "reel_weight_lbs": 100.0,
    "allowed_put_ups": ["MASTER_REEL", "CUT"],
}

PRODUCT_P4 = {
    "part_number": "CU-14-THHN",
    "conductor_metal": "COPPER",
    "copper_lbs_per_1000ft": 2.0,
    "base_price_cents_per_ft": 4,
    "min_cut_length_ft": 25,
    "cut_charge_cents": 1500,
    "reel_deposit_cents": 7500,
    "master_reel_length_ft": 5000,
    "reel_weight_lbs": 90.0,
    "allowed_put_ups": ["MASTER_REEL", "CUT"],
}


def create_branch_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["BRANCH_NAME"],
        "region_code": TEST_DEFAULTS["REGION_CODE"],
        "concurrent_cut_capacity": 1,
        "delivery_surcharge_cents": 0,
    }
    payload.update(overrides)
    return payload


def create_customer_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["CUSTOMER_NAME"],
        "credit_limit_cents": TEST_DEFAULTS["CUSTOMER_CREDIT_LIMIT_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_product_payload(base=None, **overrides) -> dict:
    payload = dict(base if base is not None else PRODUCT_P1)
    payload.update(overrides)
    return payload


def create_copper_index_entry_payload(**overrides) -> dict:
    payload = {
        "effective_date": TEST_DEFAULTS["INDEX_EFFECTIVE_DATE"],
        "price_cents_per_lb": TEST_DEFAULTS["INDEX_PRICE_CENTS_PER_LB"],
    }
    payload.update(overrides)
    return payload


def create_truck_payload(branch_id, **overrides) -> dict:
    payload = {
        "branch_id": branch_id,
        "truck_code": "T-1",
        "has_boom_lift": False,
        "max_reel_slots": 6,
    }
    payload.update(overrides)
    return payload


def create_reel_payload(product_id, branch_id, **overrides) -> dict:
    payload = {
        "product_id": product_id,
        "branch_id": branch_id,
        "lot_code": TEST_DEFAULTS["LOT_CODE"],
        "nominal_length_ft": 1000,
    }
    payload.update(overrides)
    return payload


def create_quote_payload(customer_id, branch_id, **overrides) -> dict:
    payload = {"customer_id": customer_id, "branch_id": branch_id}
    payload.update(overrides)
    return payload


def create_quote_line_payload(product_id, expected_quote_version, **overrides) -> dict:
    payload = {
        "product_id": product_id,
        "put_up": "CUT",
        "requested_length_ft": 300,
        "parallel_set_size": 1,
        "expected_quote_version": expected_quote_version,
    }
    payload.update(overrides)
    return payload


def allocate_payload(expected_sales_order_version, **overrides) -> dict:
    payload = {
        "allocation_policy": "MINIMIZE_REMNANT",
        "expected_sales_order_version": expected_sales_order_version,
    }
    payload.update(overrides)
    return payload


def cut_payload(cut_window_start, cut_window_end, **overrides) -> dict:
    payload = {
        "cut_window_start": cut_window_start,
        "cut_window_end": cut_window_end,
    }
    payload.update(overrides)
    return payload


def create_delivery_run_payload(sales_order_id, truck_id, window_start,
                                window_end, **overrides) -> dict:
    payload = {
        "sales_order_id": sales_order_id,
        "truck_id": truck_id,
        "window_start": window_start,
        "window_end": window_end,
        "jobsite_address": TEST_DEFAULTS["JOBSITE_ADDRESS"],
        "jobsite_has_forklift": False,
    }
    payload.update(overrides)
    return payload


def return_reel_payload(reel_id, condition="GOOD", **overrides) -> dict:
    payload = {"reel_id": reel_id, "condition": condition}
    payload.update(overrides)
    return payload


def credit_adjustment_payload(reason="manual invoice posted", **overrides) -> dict:
    payload = {"reason": reason}
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
