"""Request-payload builders.

Each builder produces the field set the PRD declares for one write, with
plausible domain defaults. Optional fields are omitted rather than sent as null
unless a test explicitly asks for them, and every ``**overrides`` mapping is
applied last so a test can add, replace or blank any field. All money is an
integer number of cents and all rates are integer basis points - never strings.
"""

import itertools
from typing import Any, Dict, Optional

from .constants import CLOCK_START

_counter = itertools.count(1)


def unique_suffix() -> str:
    """A short monotonically increasing suffix for uniqueness-scoped fields."""
    return f"{next(_counter):04d}"


def _compact(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    body = {key: value for key, value in payload.items() if value is not None}
    body.update(overrides)
    return body


# ---------------------------------------------------------------------------
# The commercial estate (PRD 3.1)
# ---------------------------------------------------------------------------
def terminal_payload(
    iata_code: str = "SIN",
    name: str = "Changi Terminal 3 Duty Free",
    country_code: str = "SG",
    sealed_bag_regime: Optional[str] = None,
    liquid_limit_ml: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _compact(
        {
            "iata_code": iata_code,
            "name": name,
            "country_code": country_code,
            "sealed_bag_regime": sealed_bag_regime,
            "liquid_limit_ml": liquid_limit_ml,
        },
        overrides,
    )


def brand_payload(
    name: str = "Aurora Spirits",
    category: str = "LIQUOR",
    **overrides: Any,
) -> Dict[str, Any]:
    return _compact({"name": name, "category": category}, overrides)


def allowance_rule_payload(
    destination_country: str = "AU",
    category: str = "LIQUOR",
    allowance_units: int = 2,
    advisory_text: str = "Travellers arriving in Australia may import 2 litres of spirits duty free.",
    **overrides: Any,
) -> Dict[str, Any]:
    return _compact(
        {
            "destination_country": destination_country,
            "category": category,
            "allowance_units": allowance_units,
            "advisory_text": advisory_text,
        },
        overrides,
    )


def grant_payload(
    brand_id: str,
    terminal_id: str,
    category: str = "LIQUOR",
    scope: str = "TERMINAL_EXCLUSIVE",
    effective_from: str = CLOCK_START,
    effective_to: str = "2026-12-01T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    return _compact(
        {
            "brand_id": brand_id,
            "terminal_id": terminal_id,
            "category": category,
            "scope": scope,
            "effective_from": effective_from,
            "effective_to": effective_to,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Products (PRD 3.2)
# ---------------------------------------------------------------------------
def product_payload(
    brand_id: str,
    sku: Optional[str] = None,
    category: str = "LIQUOR",
    unit_price_cents: int = 8000,
    duty_rate_bps: int = 1500,
    vat_rate_bps: int = 900,
    target_nationality_code: str = "CN",
    is_liquid: Optional[bool] = None,
    liquid_ml: Optional[int] = None,
    required_nationality_share_bps: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _compact(
        {
            "brand_id": brand_id,
            "sku": sku if sku is not None else f"AUR-WHISKY-{unique_suffix()}",
            "category": category,
            "unit_price_cents": unit_price_cents,
            "duty_rate_bps": duty_rate_bps,
            "vat_rate_bps": vat_rate_bps,
            "target_nationality_code": target_nationality_code,
            "is_liquid": is_liquid,
            "liquid_ml": liquid_ml,
            "required_nationality_share_bps": required_nationality_share_bps,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Bonded stock (PRD 3.3)
# ---------------------------------------------------------------------------
def stock_item_payload(terminal_id: str, product_id: str, **overrides: Any) -> Dict[str, Any]:
    return _compact({"terminal_id": terminal_id, "product_id": product_id}, overrides)


def movement_payload(
    stock_item_id: str,
    movement_type: str = "RECEIPT",
    qty_delta: int = 10,
    **overrides: Any,
) -> Dict[str, Any]:
    return _compact(
        {
            "stock_item_id": stock_item_id,
            "movement_type": movement_type,
            "qty_delta": qty_delta,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Passenger itineraries (PRD 3.4)
# ---------------------------------------------------------------------------
def itinerary_payload(
    departure_terminal_id: str,
    passenger_ref: Optional[str] = None,
    nationality_code: str = "CN",
    boarding_pass_barcode: Optional[str] = None,
    departure_utc: str = "2026-08-20T09:00:00Z",
    destination_country: str = "AU",
    final_destination_country: str = "AU",
    has_connection: Optional[bool] = None,
    connection_country: Optional[str] = None,
    connection_departure_utc: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    suffix = unique_suffix()
    return _compact(
        {
            "passenger_ref": passenger_ref if passenger_ref is not None else f"PAX-{suffix}",
            "nationality_code": nationality_code,
            "boarding_pass_barcode": (
                boarding_pass_barcode if boarding_pass_barcode is not None else f"BP-{suffix}"
            ),
            "departure_terminal_id": departure_terminal_id,
            "departure_utc": departure_utc,
            "destination_country": destination_country,
            "final_destination_country": final_destination_country,
            "has_connection": has_connection,
            "connection_country": connection_country,
            "connection_departure_utc": connection_departure_utc,
        },
        overrides,
    )


def scan_payload(boarding_pass_barcode: str, **overrides: Any) -> Dict[str, Any]:
    return _compact({"boarding_pass_barcode": boarding_pass_barcode}, overrides)


def amend_payload(
    destination_country: str,
    final_destination_country: str,
    has_connection: Optional[bool] = None,
    connection_country: Optional[str] = None,
    connection_departure_utc: Optional[str] = None,
    departure_utc: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _compact(
        {
            "destination_country": destination_country,
            "final_destination_country": final_destination_country,
            "has_connection": has_connection,
            "connection_country": connection_country,
            "connection_departure_utc": connection_departure_utc,
            "departure_utc": departure_utc,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Baskets (PRD 3.5)
# ---------------------------------------------------------------------------
def sale_payload(itinerary_id: str, channel: str = "IN_STORE", **overrides: Any) -> Dict[str, Any]:
    return _compact({"itinerary_id": itinerary_id, "channel": channel}, overrides)


def sale_line_payload(
    product_id: str,
    qty: int,
    expected_sale_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    return _compact(
        {
            "product_id": product_id,
            "qty": qty,
            "expected_sale_version": expected_sale_version,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Sealed bags (PRD 3.6)
# ---------------------------------------------------------------------------
def sealed_bag_payload(
    sale_id: str,
    seal_number: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _compact(
        {
            "sale_id": sale_id,
            "seal_number": seal_number if seal_number is not None else f"STEB-{unique_suffix()}",
        },
        overrides,
    )


def verify_payload(outcome: str = "INTACT", **overrides: Any) -> Dict[str, Any]:
    return _compact({"outcome": outcome}, overrides)


# ---------------------------------------------------------------------------
# Pre-orders (PRD 3.8)
# ---------------------------------------------------------------------------
def pre_order_payload(
    itinerary_id: str,
    stock_item_id: str,
    qty: int,
    expected_stock_item_version: int,
    program: str = "PICKUP_ON_DEPARTURE",
    reservation_window_start: str = "2026-08-10T00:00:00Z",
    reservation_window_end: str = "2026-08-12T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    return _compact(
        {
            "itinerary_id": itinerary_id,
            "stock_item_id": stock_item_id,
            "qty": qty,
            "program": program,
            "reservation_window_start": reservation_window_start,
            "reservation_window_end": reservation_window_end,
            "expected_stock_item_version": expected_stock_item_version,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Concession settlement (PRD 3.10)
# ---------------------------------------------------------------------------
def agreement_payload(
    terminal_id: str,
    period_code: str = "2026-08",
    period_start_utc: str = CLOCK_START,
    period_end_utc: str = "2026-09-01T00:00:00Z",
    rent_pct_bps: int = 1200,
    minimum_guarantee_cents: int = 10000,
    **overrides: Any,
) -> Dict[str, Any]:
    return _compact(
        {
            "terminal_id": terminal_id,
            "period_code": period_code,
            "period_start_utc": period_start_utc,
            "period_end_utc": period_end_utc,
            "rent_pct_bps": rent_pct_bps,
            "minimum_guarantee_cents": minimum_guarantee_cents,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Customs audits (PRD 3.9)
# ---------------------------------------------------------------------------
def audit_payload(
    terminal_id: str,
    stock_item_id: str,
    period_code: str = "2026-08",
    **overrides: Any,
) -> Dict[str, Any]:
    return _compact(
        {
            "terminal_id": terminal_id,
            "stock_item_id": stock_item_id,
            "period_code": period_code,
        },
        overrides,
    )


def audit_submit_payload(counted_qty: int, **overrides: Any) -> Dict[str, Any]:
    return _compact({"counted_qty": counted_qty}, overrides)


def audit_info_payload(
    info_request_note: str = "Please recount the top shelf and photograph the seals.",
    **overrides: Any,
) -> Dict[str, Any]:
    return _compact({"info_request_note": info_request_note}, overrides)
