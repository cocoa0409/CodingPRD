"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from .constants import (
    AMPLE_CREDIT_LIMIT_CENTS,
    BOOK_PRICE_CENTS,
    STANDARD_COST_CENTS,
)


def create_manufacturer_line_payload(line_code="LIN-1", name="Test Line",
                                     sourcing_channel="FRANCHISED", **overrides) -> dict:
    """Optional terms (ncnr, cancel_window_days, reschedule_window_days,
    allocation_policy) are included only when explicitly overridden so default
    behaviour stays observable."""
    payload = {
        "line_code": line_code,
        "name": name,
        "sourcing_channel": sourcing_channel,
    }
    payload.update(overrides)
    return payload


def create_part_payload(manufacturer_line_id, part_number="PN-1", msl_level=3,
                        floor_life_hours=100, date_code_limit_months=24,
                        standard_cost_cents=STANDARD_COST_CENTS,
                        book_price_cents=BOOK_PRICE_CENTS, **overrides) -> dict:
    payload = {
        "manufacturer_line_id": manufacturer_line_id,
        "part_number": part_number,
        "msl_level": msl_level,
        "floor_life_hours": floor_life_hours,
        "date_code_limit_months": date_code_limit_months,
        "standard_cost_cents": standard_cost_cents,
        "book_price_cents": book_price_cents,
    }
    payload.update(overrides)
    return payload


def create_customer_payload(name="Test Customer",
                            credit_limit_cents=AMPLE_CREDIT_LIMIT_CENTS,
                            **overrides) -> dict:
    payload = {
        "name": name,
        "credit_limit_cents": credit_limit_cents,
    }
    payload.update(overrides)
    return payload


def create_design_registration_payload(customer_id, part_id, end_customer_name="EndCo",
                                       registered_cost_cents=700, max_registered_qty=20,
                                       valid_from="2026-08-01", valid_to="2026-12-31",
                                       **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "part_id": part_id,
        "end_customer_name": end_customer_name,
        "registered_cost_cents": registered_cost_cents,
        "max_registered_qty": max_registered_qty,
        "valid_from": valid_from,
        "valid_to": valid_to,
    }
    payload.update(overrides)
    return payload


def order_line_spec(part_id, quantity, ship_date="2026-10-01") -> dict:
    """One inline order line as carried in the POST /orders lines array."""
    return {
        "part_id": part_id,
        "quantity": quantity,
        "ship_date": ship_date,
    }


def create_order_payload(customer_id, lines, note=None, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "lines": lines,
    }
    if note is not None:
        payload["note"] = note
    payload.update(overrides)
    return payload


def create_alternate_approval_payload(customer_id, primary_part_id,
                                      alternate_part_id, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "primary_part_id": primary_part_id,
        "alternate_part_id": alternate_part_id,
    }
    payload.update(overrides)
    return payload


def create_lot_payload(part_id, date_code="202601", qty_received=100,
                       source_type="FRANCHISED", **overrides) -> dict:
    payload = {
        "part_id": part_id,
        "date_code": date_code,
        "qty_received": qty_received,
        "source_type": source_type,
    }
    payload.update(overrides)
    return payload


def create_allocation_run_payload(part_id, expected_part_version) -> dict:
    return {
        "part_id": part_id,
        "expected_part_version": expected_part_version,
    }


def create_buyback_payload(customer_id, order_line_id, kind="EXCESS_RETURN",
                           qty=1, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "order_line_id": order_line_id,
        "kind": kind,
        "qty": qty,
    }
    payload.update(overrides)
    return payload


def reschedule_payload(new_ship_date, expected_order_version) -> dict:
    return {
        "new_ship_date": new_ship_date,
        "expected_order_version": expected_order_version,
    }
