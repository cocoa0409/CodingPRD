"""Composite state builders.

The server is relaunched before every test, so each test starts against an
empty database and builds whatever state it needs exclusively through the
PRD's own endpoints. Setup steps read their responses through
get_success_data(), which is lenient about the exact 2xx code; the assertions
that matter belong in the tests.

Return-authorization requests reference the target order line by its server id,
which is resolved here by reading the order's line collection.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .constants import DEFAULT_CLOCK_ISO
from .factories import (
    brand_payload,
    clock_payload,
    exclusivity_grant_payload,
    fraud_flag_payload,
    order_line,
    order_payload,
    payment_payload,
    retailer_payload,
    return_auth_payload,
)
from .test_users import (
    ADMIN,
    RISK,
    make_anonymous_headers,
    make_brand_headers,
    make_retailer_headers,
)


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------
def set_clock(api, instant: str = DEFAULT_CLOCK_ISO) -> Dict[str, Any]:
    return get_success_data(api.set_clock(clock_payload(instant), ADMIN))


# --------------------------------------------------------------------------
# Retailers and verification
# --------------------------------------------------------------------------
def register_retailer(api, **kwargs) -> Dict[str, Any]:
    return get_success_data(api.create_retailer(retailer_payload(**kwargs),
                                                make_anonymous_headers()))


def review_document(api, retailer_id: str, document_type: str,
                    decision: str) -> Dict[str, Any]:
    return get_success_data(
        api.review_document(
            retailer_id, {"document_type": document_type, "decision": decision}, ADMIN
        )
    )


def confirm_documents(api, retailer_id: str) -> None:
    review_document(api, retailer_id, "STOREFRONT_PROOF", "CONFIRM")
    review_document(api, retailer_id, "RESALE_CERT", "CONFIRM")


def verify_retailer(api, retailer_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.verify_retailer(retailer_id, {"decision": "APPROVE"}, ADMIN)
    )


def verified_retailer(api, **kwargs) -> Dict[str, Any]:
    """Register, confirm both documents, and approve. Returns the retailer."""
    retailer = register_retailer(api, **kwargs)
    confirm_documents(api, retailer["id"])
    return verify_retailer(api, retailer["id"])


# --------------------------------------------------------------------------
# Brands
# --------------------------------------------------------------------------
def create_brand(api, **kwargs) -> Dict[str, Any]:
    """Create a brand as the Brand role. Creation is not ownership-gated, so
    a placeholder caller id suffices; activation below re-targets the id."""
    return get_success_data(
        api.create_brand(brand_payload(**kwargs), make_brand_headers("new-brand"))
    )


def activate_brand(api, brand_id: str) -> Dict[str, Any]:
    return get_success_data(api.activate_brand(brand_id, make_brand_headers(brand_id)))


def active_brand(api, **kwargs) -> Dict[str, Any]:
    """Create a brand and activate it as itself."""
    brand = create_brand(api, **kwargs)
    return activate_brand(api, brand["id"])


# --------------------------------------------------------------------------
# Credit accounts
# --------------------------------------------------------------------------
def open_credit_account(api, retailer_id: str) -> Dict[str, Any]:
    return get_success_data(api.create_credit_account({"retailer_id": retailer_id}, ADMIN))


def get_credit_account(api, account_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_credit_account(account_id, ADMIN))


def read_brand(api, brand_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_brand(brand_id, ADMIN))


def read_retailer(api, retailer_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_retailer(retailer_id, ADMIN))


def read_order(api, order_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_order(order_id, ADMIN))


def read_invoice(api, invoice_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_invoice(invoice_id, ADMIN))


# --------------------------------------------------------------------------
# Orders
# --------------------------------------------------------------------------
def place_order(api, retailer_id: str, brand_id: str,
                lines: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.create_order(
            order_payload(retailer_id, brand_id, lines),
            make_retailer_headers(retailer_id),
        )
    )


def get_order_lines(api, order_id: str) -> List[Dict[str, Any]]:
    data = get_success_data(api.list_order_lines(order_id, ADMIN))
    assert isinstance(data, list), "order lines must be returned as a list"
    return data


def first_line_id(api, order_id: str) -> str:
    lines = get_order_lines(api, order_id)
    assert lines, "expected the order to have at least one line"
    return lines[0]["id"]


def ship_order(api, order_id: str, brand_id: str) -> Dict[str, Any]:
    return get_success_data(api.ship_order(order_id, make_brand_headers(brand_id)))


def deliver_order(api, order_id: str, brand_id: str) -> Dict[str, Any]:
    return get_success_data(api.deliver_order(order_id, make_brand_headers(brand_id)))


def order_invoice(api, order_id: str) -> Dict[str, Any]:
    """Return the order's single invoice (the endpoint returns a 0-or-1 array)."""
    data = get_success_data(api.get_order_invoice(order_id, ADMIN))
    assert isinstance(data, list) and len(data) == 1, (
        f"expected exactly one invoice for order {order_id}"
    )
    return data[0]


def payouts_for_order(api, order_id: str) -> List[Dict[str, Any]]:
    data = get_success_data(api.list_payouts(ADMIN, {"order_id": order_id}))
    assert isinstance(data, list), "payout listing must be returned as a list"
    return data


def order_payout(api, order_id: str) -> Dict[str, Any]:
    payouts = payouts_for_order(api, order_id)
    assert payouts, f"expected at least one payout for order {order_id}"
    return payouts[0]


def shipped_order(api, retailer_id: str, brand_id: str,
                  lines: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    order = place_order(api, retailer_id, brand_id, lines)
    return ship_order(api, order["id"], brand_id)


def delivered_order(api, retailer_id: str, brand_id: str,
                    lines: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    order = shipped_order(api, retailer_id, brand_id, lines)
    return deliver_order(api, order["id"], brand_id)


# --------------------------------------------------------------------------
# Payments
# --------------------------------------------------------------------------
def pay_invoice(api, invoice_id: str, retailer_id: str,
                amount_cents: int) -> Dict[str, Any]:
    return get_success_data(
        api.record_payment(
            invoice_id, payment_payload(amount_cents), make_retailer_headers(retailer_id)
        )
    )


# --------------------------------------------------------------------------
# Returns
# --------------------------------------------------------------------------
def request_return(api, retailer_id: str, order_id: str, order_line_id: str,
                   qty: int) -> Dict[str, Any]:
    return get_success_data(
        api.create_return_authorization(
            return_auth_payload(order_id, order_line_id, qty),
            make_retailer_headers(retailer_id),
        )
    )


def approve_return(api, ra_id: str, brand_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.review_return_authorization(ra_id, {"decision": "APPROVE"},
                                        make_brand_headers(brand_id))
    )


def receive_return(api, ra_id: str) -> Dict[str, Any]:
    return get_success_data(api.receive_return_authorization(ra_id, ADMIN))


def returned_all(api, retailer_id: str, brand_id: str, order_id: str) -> Dict[str, Any]:
    """Request, approve, and receive a return of every unit on the order's
    single line. Returns the received authorization."""
    line_id = first_line_id(api, order_id)
    qty = get_order_lines(api, order_id)[0]["qty"]
    ra = request_return(api, retailer_id, order_id, line_id, qty)
    approve_return(api, ra["id"], brand_id)
    return receive_return(api, ra["id"])


# --------------------------------------------------------------------------
# Fraud flags
# --------------------------------------------------------------------------
def raise_flag(api, retailer_id: str, flag_type: str,
               order_id: Optional[str] = None) -> Dict[str, Any]:
    return get_success_data(
        api.create_fraud_flag(fraud_flag_payload(retailer_id, flag_type, order_id), RISK)
    )


def confirm_flag(api, flag_id: str) -> Dict[str, Any]:
    return get_success_data(api.confirm_fraud_flag(flag_id, ADMIN))


def raise_return_abuse_flags(api, retailer_id: str, order_id: str,
                             count: int = 5) -> List[Dict[str, Any]]:
    """Raise and confirm `count` RETURN_ABUSE flags against the brand of the
    given order."""
    flags = []
    for _ in range(count):
        flag = raise_flag(api, retailer_id, "RETURN_ABUSE", order_id)
        flags.append(confirm_flag(api, flag["id"]))
    return flags


# --------------------------------------------------------------------------
# Exclusivity grants
# --------------------------------------------------------------------------
def create_grant(api, brand_id: str, retailer_id: str, **kwargs) -> Dict[str, Any]:
    """Create an exclusivity grant as the brand, re-reading the brand version
    immediately beforehand so the OCC guard passes."""
    brand = read_brand(api, brand_id)
    return get_success_data(
        api.create_exclusivity_grant(
            exclusivity_grant_payload(brand_id, retailer_id, brand["version"], **kwargs),
            make_brand_headers(brand_id),
        )
    )


# --------------------------------------------------------------------------
# Composite scenario builders
# --------------------------------------------------------------------------
def verified_retailer_with_account(api, **kwargs) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """A VERIFIED retailer plus its credit account. Returns (retailer, account)."""
    retailer = verified_retailer(api, **kwargs)
    account = open_credit_account(api, retailer["id"])
    return retailer, account


def standard_market(api, brand_kwargs: Optional[Dict[str, Any]] = None,
                    retailer_kwargs: Optional[Dict[str, Any]] = None
                    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """VERIFIED retailer + credit account + ACTIVE brand.
    Returns (retailer, account, brand)."""
    retailer, account = verified_retailer_with_account(api, **(retailer_kwargs or {}))
    brand = active_brand(api, **(brand_kwargs or {}))
    return retailer, account, brand


def shipped_invoice_scenario(api, unit_price_cents: int = 10000, qty: int = 1,
                             sku: str = "S1",
                             retailer_kwargs: Optional[Dict[str, Any]] = None,
                             brand_kwargs: Optional[Dict[str, Any]] = None
                             ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
                                        Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Retailer + account + ACTIVE brand + one shipped order.
    Returns (retailer, account, brand, order, invoice, payout)."""
    retailer, account, brand = standard_market(api, brand_kwargs, retailer_kwargs)
    order = shipped_order(api, retailer["id"], brand["id"],
                          [order_line(sku, unit_price_cents, qty)])
    invoice = order_invoice(api, order["id"])
    payout = order_payout(api, order["id"])
    return retailer, account, brand, order, invoice, payout


def delivered_invoice_scenario(api, unit_price_cents: int = 5000, qty: int = 4,
                               sku: str = "S1",
                               retailer_kwargs: Optional[Dict[str, Any]] = None,
                               brand_kwargs: Optional[Dict[str, Any]] = None
                               ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
                                          Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """As shipped_invoice_scenario but the order is DELIVERED.
    Returns (retailer, account, brand, order, invoice, payout)."""
    retailer, account, brand = standard_market(api, brand_kwargs, retailer_kwargs)
    order = delivered_order(api, retailer["id"], brand["id"],
                            [order_line(sku, unit_price_cents, qty)])
    invoice = order_invoice(api, order["id"])
    payout = order_payout(api, order["id"])
    return retailer, account, brand, order, invoice, payout
