"""Payload factories — one per creatable entity, input fields only."""


def create_rep_payload(**overrides) -> dict:
    defaults = {"full_name": "Rep One", "home_depot": "DEP-1"}
    defaults.update(overrides)
    return defaults


def create_store_payload(**overrides) -> dict:
    defaults = {
        "store_code": "SA",
        "name": "Store A",
        "format": "GROCERY",
        "credit_policy": "FULL_RETAIL",
        "delivery_window_start_minute": 480,
        "delivery_window_end_minute": 720,
        "store_credit_cap_cents": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "sku": "P-1",
        "name": "Chips",
        "case_price_cents": 500,
        "shelf_life_days": 60,
    }
    defaults.update(overrides)
    return defaults


def create_route_payload(rsr_id, **overrides) -> dict:
    defaults = {
        "territory_code": "T-1",
        "rsr_id": rsr_id,
        "base_capacity_cases": 100,
        "truck_cap_cases": 200,
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(route_id, store_id, **overrides) -> dict:
    defaults = {
        "route_id": route_id,
        "store_id": store_id,
        "service_weekdays": ["TUE"],
        "stop_sequence": 1,
    }
    defaults.update(overrides)
    return defaults


def create_route_day_payload(route_id, **overrides) -> dict:
    defaults = {"route_id": route_id, "service_date": "2026-09-01"}
    defaults.update(overrides)
    return defaults


def lot_entry(product_id, lot_code, expiration_date, loaded_cases) -> dict:
    return {
        "product_id": product_id,
        "lot_code": lot_code,
        "expiration_date": expiration_date,
        "loaded_cases": loaded_cases,
    }


def load_payload(lots) -> dict:
    return {"lots": lots}


def order_line(product_id, qty_ordered_cases, **overrides) -> dict:
    line = {"product_id": product_id, "qty_ordered_cases": qty_ordered_cases}
    line.update(overrides)
    return line


def create_order_payload(route_day_id, store_id, lines, **overrides) -> dict:
    payload = {"route_day_id": route_day_id, "store_id": store_id, "lines": lines}
    payload.update(overrides)
    return payload


def revise_order_payload(lines, expected_store_order_version) -> dict:
    return {
        "lines": lines,
        "expected_store_order_version": expected_store_order_version,
    }


def deliver_payload(lines) -> dict:
    return {"lines": lines}


def deliver_line(product_id, qty_delivered_cases) -> dict:
    return {"product_id": product_id, "qty_delivered_cases": qty_delivered_cases}


def create_shelf_execution_payload(route_day_id, store_id, product_id, **overrides) -> dict:
    defaults = {
        "route_day_id": route_day_id,
        "store_id": store_id,
        "product_id": product_id,
        "qty_placed_cases": 5,
        "rotated": True,
        "display_built": False,
    }
    defaults.update(overrides)
    return defaults


def shelf_verify_payload(outcome, **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def create_stale_credit_payload(route_day_id, store_id, product_id, qty_cases) -> dict:
    return {
        "route_day_id": route_day_id,
        "store_id": store_id,
        "product_id": product_id,
        "qty_cases": qty_cases,
    }


def reject_credit_payload(reject_reason) -> dict:
    return {"reject_reason": reject_reason}


def create_promo_agreement_payload(store_id, product_id, **overrides) -> dict:
    defaults = {
        "store_id": store_id,
        "product_id": product_id,
        "window_start": "2026-09-01",
        "window_end": "2026-09-10",
        "display_type": "ENDCAP",
        "rebate_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_promo_execution_payload(
    agreement_id, route_day_id, expected_promo_agreement_version, **overrides
) -> dict:
    payload = {
        "agreement_id": agreement_id,
        "route_day_id": route_day_id,
        "photo_url": "https://photos/x.jpg",
        "expected_promo_agreement_version": expected_promo_agreement_version,
    }
    payload.update(overrides)
    return payload


def create_settlement_payload(route_day_id) -> dict:
    return {"route_day_id": route_day_id}


def balance_payload(cash_collected_cents) -> dict:
    return {"cash_collected_cents": cash_collected_cents}


def create_snapshot_payload(period_start, period_end) -> dict:
    return {"period_start": period_start, "period_end": period_end}
