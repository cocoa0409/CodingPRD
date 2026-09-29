"""Payload factories — one per resource, carrying only client-supplied fields.

Money is always a JSON number in whole cents; catalog prices are JSON numbers
in whole micro-dollars; proportions are JSON numbers in whole basis points.
Instants are full ISO 8601 UTC instants; loaner and effective dates are the
date-granularity values the PRD declares for those fields.
"""

from .constants import TEST_DEFAULTS

_UNSET = object()


def _compact(payload: dict) -> dict:
    """Drop keys whose value is the _UNSET sentinel, keeping explicit Nones."""
    return {k: v for k, v in payload.items() if v is not _UNSET}


# --- Test-driving capabilities ------------------------------------------------


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}


def set_green_index_payload(index_micros: int) -> dict:
    return {"index_micros": index_micros}


# --- Route -------------------------------------------------------------------


def create_route_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["ROUTE_NAME"],
        "service_day": TEST_DEFAULTS["ROUTE_SERVICE_DAY"],
        "capacity_minutes": TEST_DEFAULTS["ROUTE_CAPACITY_MINUTES"],
        "travel_buffer_minutes": TEST_DEFAULTS["ROUTE_TRAVEL_BUFFER_MINUTES"],
    }
    payload.update(overrides)
    return payload


# --- EquipmentModel ----------------------------------------------------------


def create_equipment_model_payload(**overrides) -> dict:
    payload = {
        "model_code": TEST_DEFAULTS["MODEL_CODE"],
        "brewer_class": TEST_DEFAULTS["MODEL_BREWER_CLASS"],
        "cups_per_hour_capacity": TEST_DEFAULTS["MODEL_CUPS_PER_HOUR"],
        "min_headcount": TEST_DEFAULTS["MODEL_MIN_HEADCOUNT"],
        "max_headcount": TEST_DEFAULTS["MODEL_MAX_HEADCOUNT"],
        "monthly_rent_cents": TEST_DEFAULTS["MODEL_MONTHLY_RENT_CENTS"],
        "descale_interval_days": TEST_DEFAULTS["MODEL_DESCALE_INTERVAL_DAYS"],
        "list_value_cents": TEST_DEFAULTS["MODEL_LIST_VALUE_CENTS"],
    }
    payload.update(overrides)
    return payload


# --- ProductItem -------------------------------------------------------------


def create_product_item_payload(**overrides) -> dict:
    payload = {
        "sku": "SKU-COFFEE-001",
        "category": "COFFEE",
        "base_unit_price_micros": 4500000,
        "pack_units": 1,
    }
    payload.update(overrides)
    return payload


# --- EquipmentAsset ----------------------------------------------------------


def create_equipment_asset_payload(model_id: str, **overrides) -> dict:
    payload = {
        "model_id": model_id,
        "serial_number": "SN-0001",
        "asset_role": "PLACEMENT",
    }
    payload.update(overrides)
    return payload


# --- Account -----------------------------------------------------------------


def create_account_payload(**overrides) -> dict:
    payload = {
        "legal_name": TEST_DEFAULTS["ACCOUNT_LEGAL_NAME"],
        "billing_mode": "CONSOLIDATED",
        "green_index_baseline_micros": TEST_DEFAULTS["GREEN_INDEX_BASELINE_MICROS"],
    }
    payload.update(overrides)
    return payload


def cancel_account_payload(**overrides) -> dict:
    payload = {
        "cancel_reason": "Customer consolidating vendors",
        "retrieval_due_by": "2026-08-31T00:00:00Z",
    }
    payload.update(overrides)
    return payload


# --- Site --------------------------------------------------------------------


def create_site_payload(account_id: str, route_id: str, **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "route_id": route_id,
        "site_name": "Fourth Floor Break Room",
        "headcount": TEST_DEFAULTS["SITE_HEADCOUNT"],
        "days_per_week": TEST_DEFAULTS["SITE_DAYS_PER_WEEK"],
        "consumption_model": "HEADCOUNT_MODEL",
        "service_minutes_estimate": TEST_DEFAULTS["SITE_SERVICE_MINUTES_ESTIMATE"],
    }
    payload.update(overrides)
    return payload


def update_site_payload(**overrides) -> dict:
    """PATCH body: only the demand attributes the caller actually supplies."""
    return dict(overrides)


def size_and_plan_payload(brew_style: str = "DRIP") -> dict:
    return {"brew_style": brew_style}


# --- ParLevel ----------------------------------------------------------------


def create_par_level_payload(site_id: str, product_id: str, **overrides) -> dict:
    payload = {
        "site_id": site_id,
        "product_id": product_id,
        "par_units": 10,
        "reorder_point_units": 4,
    }
    payload.update(overrides)
    return payload


def update_par_level_payload(**overrides) -> dict:
    return dict(overrides)


# --- EquipmentPlacement ------------------------------------------------------


def create_placement_payload(
    site_id: str, asset_id: str, expected_site_version: int, **overrides
) -> dict:
    payload = {
        "site_id": site_id,
        "asset_id": asset_id,
        "terms_type": "LOAN",
        "minimum_purchase_cents": 75000,
        "min_term_months": 12,
        "expected_site_version": expected_site_version,
    }
    payload.update(overrides)
    return payload


def retrieve_placement_payload(retrieved_asset_condition: str = "SERVICEABLE") -> dict:
    return {"retrieved_asset_condition": retrieved_asset_condition}


# --- ServiceVisit ------------------------------------------------------------


def create_visit_payload(site_id: str, **overrides) -> dict:
    payload = {
        "site_id": site_id,
        "window_start": "2026-08-03T09:00:00Z",
        "window_end": "2026-08-03T09:45:00Z",
        "planned_minutes": 45,
    }
    payload.update(overrides)
    return payload


def append_visit_line_payload(product_id: str, requested_units: int) -> dict:
    return {"product_id": product_id, "requested_units": requested_units}


def reschedule_visit_payload(window_start: str, window_end: str) -> dict:
    return {"window_start": window_start, "window_end": window_end}


def complete_visit_payload(delivered_lines=None) -> dict:
    return {"delivered_lines": delivered_lines if delivered_lines is not None else []}


def delivered_line(product_id: str, delivered_units: int) -> dict:
    return {"product_id": product_id, "delivered_units": delivered_units}


def void_visit_payload(void_reason: str = "Recorded against the wrong stop") -> dict:
    return {"void_reason": void_reason}


# --- MaintenanceWorkOrder ----------------------------------------------------


def create_work_order_payload(asset_id: str, wo_type: str = "REPAIR", **overrides) -> dict:
    payload = {"asset_id": asset_id, "wo_type": wo_type}
    payload.update(overrides)
    return payload


def advance_work_order_payload(
    to_status: str, parts_eta=_UNSET, resolution_note=_UNSET
) -> dict:
    return _compact(
        {
            "to_status": to_status,
            "parts_eta": parts_eta,
            "resolution_note": resolution_note,
        }
    )


def loaner_swap_payload(
    loaner_asset_id: str, loaner_out_date: str, loaner_due_back_date: str
) -> dict:
    return {
        "loaner_asset_id": loaner_asset_id,
        "loaner_out_date": loaner_out_date,
        "loaner_due_back_date": loaner_due_back_date,
    }


def loaner_return_payload(returned_on: str) -> dict:
    return {"returned_on": returned_on}


# --- ConsolidatedInvoice -----------------------------------------------------


def create_invoice_payload(
    account_id: str,
    period_start: str,
    period_end: str,
    expected_account_version: int,
    site_id=_UNSET,
    **overrides,
) -> dict:
    payload = _compact(
        {
            "account_id": account_id,
            "period_start": period_start,
            "period_end": period_end,
            "expected_account_version": expected_account_version,
            "site_id": site_id,
        }
    )
    payload.update(overrides)
    return payload


def credit_invoice_payload(
    target_line_id: str, amount_cents: int, credit_reason: str = "Equipment returned"
) -> dict:
    return {
        "target_line_id": target_line_id,
        "amount_cents": amount_cents,
        "credit_reason": credit_reason,
    }


# --- PriceAdjustment ---------------------------------------------------------


def create_price_adjustment_payload(account_id: str, **overrides) -> dict:
    payload = {"account_id": account_id, "effective_at": "2026-09-01T00:00:00Z"}
    payload.update(overrides)
    return payload


def respond_payload(disposition: str, dispute_reason=_UNSET) -> dict:
    return _compact({"disposition": disposition, "dispute_reason": dispute_reason})


def revise_payload(revised_adjustment_pct_bps: int) -> dict:
    return {"revised_adjustment_pct_bps": revised_adjustment_pct_bps}
