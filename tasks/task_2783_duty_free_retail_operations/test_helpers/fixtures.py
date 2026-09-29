"""Composite setup chains built exclusively through declared endpoints.

The server is restarted before every test, so each test begins with an empty
database and the logical clock at its boot value; every precondition below is
therefore built by calling the API the same way a client would. Each helper
validates the response it depends on, so a broken precondition fails loudly at
the line that created it rather than inside the assertion under test.
"""

from types import SimpleNamespace
from typing import Any, Dict, Optional

from . import factories
from .assertions import created, ok
from .test_users import (
    CUSTOMS_AUDITOR_HEADERS,
    SALES_ASSOCIATE_HEADERS,
    STOCK_CONTROLLER_HEADERS,
    TERMINAL_ADMIN_HEADERS,
    make_passenger_headers,
)


# ---------------------------------------------------------------------------
# The logical clock
# ---------------------------------------------------------------------------
def advance_clock(api, to_iso8601: str) -> str:
    """Drive the logical clock and return the ``current_utc`` it answers with."""
    data = ok(api.set_clock(to_iso8601, TERMINAL_ADMIN_HEADERS))
    return data["current_utc"]


# ---------------------------------------------------------------------------
# The commercial estate
# ---------------------------------------------------------------------------
def register_terminal(api, **overrides: Any) -> Dict[str, Any]:
    return created(api.create_terminal(factories.terminal_payload(**overrides), TERMINAL_ADMIN_HEADERS))


def register_brand(api, **overrides: Any) -> Dict[str, Any]:
    return created(api.create_brand(factories.brand_payload(**overrides), TERMINAL_ADMIN_HEADERS))


def publish_allowance_rule(api, **overrides: Any) -> Dict[str, Any]:
    return created(
        api.create_allowance_rule(factories.allowance_rule_payload(**overrides), TERMINAL_ADMIN_HEADERS)
    )


def grant_exclusivity(api, brand_id: str, terminal_id: str, **overrides: Any) -> Dict[str, Any]:
    return created(
        api.create_grant(factories.grant_payload(brand_id, terminal_id, **overrides), TERMINAL_ADMIN_HEADERS)
    )


def register_product(api, brand_id: str, **overrides: Any) -> Dict[str, Any]:
    """Create a product. The nationality-share gate defaults to 0 basis points so
    the assortment decision under test is the one the test names, not the mix."""
    overrides.setdefault("required_nationality_share_bps", 0)
    return created(api.create_product(factories.product_payload(brand_id, **overrides), TERMINAL_ADMIN_HEADERS))


def admit_product(api, product_id: str) -> Dict[str, Any]:
    return ok(api.list_product(product_id, TERMINAL_ADMIN_HEADERS))


def listed_product(api, brand_id: str, **overrides: Any) -> Dict[str, Any]:
    """Create a product and admit it into the assortment."""
    product = register_product(api, brand_id, **overrides)
    return admit_product(api, product["id"])


# ---------------------------------------------------------------------------
# Bonded stock
# ---------------------------------------------------------------------------
def open_ledger(api, terminal_id: str, product_id: str) -> Dict[str, Any]:
    return created(
        api.create_stock_item(factories.stock_item_payload(terminal_id, product_id), STOCK_CONTROLLER_HEADERS)
    )


def post_receipt(api, stock_item_id: str, qty: int = 10, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return created(
        api.create_movement(
            factories.movement_payload(stock_item_id, "RECEIPT", qty),
            headers or STOCK_CONTROLLER_HEADERS,
        )
    )


def post_adjustment(api, stock_item_id: str, qty_delta: int, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return created(
        api.create_movement(
            factories.movement_payload(stock_item_id, "AUDIT_ADJUSTMENT", qty_delta),
            headers or STOCK_CONTROLLER_HEADERS,
        )
    )


def stocked_ledger(api, terminal_id: str, product_id: str, qty: int = 10) -> Dict[str, Any]:
    """Open a ledger, receive ``qty`` units into bond and return the fresh item.

    A ``RECEIPT`` must carry a strictly positive ``qty_delta``, so a caller asking
    for zero units wants an empty ledger and no movement is posted at all.
    """
    item = open_ledger(api, terminal_id, product_id)
    if qty > 0:
        post_receipt(api, item["id"], qty)
    return ok(api.get_stock_item(item["id"], STOCK_CONTROLLER_HEADERS))


# ---------------------------------------------------------------------------
# Concession agreements
# ---------------------------------------------------------------------------
def draft_agreement(api, terminal_id: str, **overrides: Any) -> Dict[str, Any]:
    return created(
        api.create_agreement(factories.agreement_payload(terminal_id, **overrides), TERMINAL_ADMIN_HEADERS)
    )


def activate_agreement(api, agreement_id: str) -> Dict[str, Any]:
    return ok(api.activate_agreement(agreement_id, TERMINAL_ADMIN_HEADERS))


def active_agreement(api, terminal_id: str, **overrides: Any) -> Dict[str, Any]:
    """Draft an agreement and activate it, so turnover has somewhere to accrue."""
    agreement = draft_agreement(api, terminal_id, **overrides)
    return activate_agreement(api, agreement["id"])


def close_agreement(api, agreement_id: str) -> Dict[str, Any]:
    return ok(api.close_agreement_period(agreement_id, TERMINAL_ADMIN_HEADERS))


# ---------------------------------------------------------------------------
# Itineraries
# ---------------------------------------------------------------------------
def record_itinerary(api, terminal_id: str, **overrides: Any) -> Dict[str, Any]:
    return created(
        api.create_itinerary(factories.itinerary_payload(terminal_id, **overrides), SALES_ASSOCIATE_HEADERS)
    )


def scan_itinerary(api, itinerary: Dict[str, Any]) -> Dict[str, Any]:
    return ok(
        api.scan_boarding_pass(
            itinerary["id"],
            factories.scan_payload(itinerary["boarding_pass_barcode"]),
            SALES_ASSOCIATE_HEADERS,
        )
    )


def scanned_itinerary(api, terminal_id: str, **overrides: Any) -> Dict[str, Any]:
    """Record an itinerary and verify its boarding pass."""
    itinerary = record_itinerary(api, terminal_id, **overrides)
    scanned = scan_itinerary(api, itinerary)
    scanned["boarding_pass_barcode"] = itinerary["boarding_pass_barcode"]
    return scanned


# ---------------------------------------------------------------------------
# Baskets
# ---------------------------------------------------------------------------
def open_basket(api, itinerary_id: str, channel: str = "IN_STORE") -> Dict[str, Any]:
    return created(api.create_sale(factories.sale_payload(itinerary_id, channel), SALES_ASSOCIATE_HEADERS))


def append_line(api, sale_id: str, product_id: str, qty: int) -> Dict[str, Any]:
    """Append a line, quoting the basket's current version as the guard requires."""
    sale = ok(api.get_sale(sale_id, SALES_ASSOCIATE_HEADERS))
    return created(
        api.add_sale_line(
            sale_id,
            factories.sale_line_payload(product_id, qty, sale["version"]),
            SALES_ASSOCIATE_HEADERS,
        )
    )


def clear_basket(api, sale_id: str) -> Dict[str, Any]:
    return ok(api.clear_eligibility(sale_id, SALES_ASSOCIATE_HEADERS))


def hand_over(api, sale_id: str) -> Dict[str, Any]:
    return ok(api.pickup_sale(sale_id, SALES_ASSOCIATE_HEADERS))


def void_basket(api, sale_id: str) -> Dict[str, Any]:
    return ok(api.void_sale(sale_id, SALES_ASSOCIATE_HEADERS))


def issue_bag(api, sale_id: str, seal_number: Optional[str] = None) -> Dict[str, Any]:
    return created(
        api.create_sealed_bag(factories.sealed_bag_payload(sale_id, seal_number), SALES_ASSOCIATE_HEADERS)
    )


def verify_bag(api, sealed_bag_id: str, outcome: str = "INTACT") -> Dict[str, Any]:
    return ok(api.verify_sealed_bag(sealed_bag_id, factories.verify_payload(outcome), SALES_ASSOCIATE_HEADERS))


# ---------------------------------------------------------------------------
# Pre-orders
# ---------------------------------------------------------------------------
def place_reservation(api, itinerary_id: str, stock_item: Dict[str, Any], qty: int, **overrides: Any) -> Dict[str, Any]:
    """Place a reservation quoting the stock item's current version."""
    version = overrides.pop("expected_stock_item_version", stock_item["version"])
    payload = factories.pre_order_payload(itinerary_id, stock_item["id"], qty, version, **overrides)
    return created(api.create_pre_order(payload, make_passenger_headers(itinerary_id)))


def convert_reservation(api, pre_order_id: str) -> Dict[str, Any]:
    return ok(api.convert_pre_order(pre_order_id, STOCK_CONTROLLER_HEADERS))


def cancel_reservation(api, pre_order_id: str, itinerary_id: str) -> Dict[str, Any]:
    return ok(api.cancel_pre_order(pre_order_id, make_passenger_headers(itinerary_id)))


# ---------------------------------------------------------------------------
# Customs audits
# ---------------------------------------------------------------------------
def open_audit(api, terminal_id: str, stock_item_id: str, period_code: str = "2026-08", headers=None) -> Dict[str, Any]:
    return created(
        api.create_audit(
            factories.audit_payload(terminal_id, stock_item_id, period_code),
            headers or STOCK_CONTROLLER_HEADERS,
        )
    )


def submit_count(api, audit_id: str, counted_qty: int, headers=None) -> Dict[str, Any]:
    return ok(
        api.submit_audit(audit_id, factories.audit_submit_payload(counted_qty), headers or STOCK_CONTROLLER_HEADERS)
    )


def request_more_info(api, audit_id: str, headers=None, note: Optional[str] = None) -> Dict[str, Any]:
    payload = factories.audit_info_payload() if note is None else factories.audit_info_payload(note)
    return ok(api.request_audit_info(audit_id, payload, headers or CUSTOMS_AUDITOR_HEADERS))


def adjudicate_audit(api, audit_id: str, headers=None) -> Dict[str, Any]:
    return ok(api.close_audit(audit_id, headers or CUSTOMS_AUDITOR_HEADERS))


# ---------------------------------------------------------------------------
# Composite estates
# ---------------------------------------------------------------------------
def liquor_estate(
    api,
    iata_code: str = "SIN",
    country_code: str = "SG",
    sealed_bag_regime: str = "NONE",
    liquid_limit_ml: int = 3000,
    receipt_qty: int = 10,
    allowance_units: int = 2,
    allowance_country: str = "AU",
    unit_price_cents: int = 8000,
    duty_rate_bps: int = 1500,
    vat_rate_bps: int = 900,
    with_agreement: bool = True,
) -> SimpleNamespace:
    """A single-terminal spirits estate: brand, listed litre bottle, stocked
    ledger, published arrival allowance and an active concession agreement."""
    terminal = register_terminal(
        api,
        iata_code=iata_code,
        country_code=country_code,
        sealed_bag_regime=sealed_bag_regime,
        liquid_limit_ml=liquid_limit_ml,
    )
    brand = register_brand(api, name=f"Aurora Spirits {iata_code}", category="LIQUOR")
    product = register_product(
        api,
        brand["id"],
        category="LIQUOR",
        unit_price_cents=unit_price_cents,
        duty_rate_bps=duty_rate_bps,
        vat_rate_bps=vat_rate_bps,
        is_liquid=True,
        liquid_ml=700,
        target_nationality_code="CN",
    )
    stock_item = stocked_ledger(api, terminal["id"], product["id"], receipt_qty)
    product = admit_product(api, product["id"])
    rule = publish_allowance_rule(
        api,
        destination_country=allowance_country,
        category="LIQUOR",
        allowance_units=allowance_units,
    )
    agreement = (
        active_agreement(api, terminal["id"]) if with_agreement else None
    )
    return SimpleNamespace(
        terminal=terminal,
        brand=brand,
        product=product,
        stock_item=stock_item,
        allowance_rule=rule,
        agreement=agreement,
    )


def till_ready_basket(
    api,
    estate: SimpleNamespace,
    qty: int = 2,
    itinerary_overrides: Optional[Dict[str, Any]] = None,
) -> SimpleNamespace:
    """A scanned itinerary with a one-line basket still open in ``CART``."""
    itinerary = scanned_itinerary(api, estate.terminal["id"], **(itinerary_overrides or {}))
    sale = open_basket(api, itinerary["id"])
    line = append_line(api, sale["id"], estate.product["id"], qty)
    sale = ok(api.get_sale(sale["id"], SALES_ASSOCIATE_HEADERS))
    return SimpleNamespace(itinerary=itinerary, sale=sale, line=line)
