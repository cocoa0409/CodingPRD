"""Request payload builders.

Every money value produced here is an integer number of cents and every rate is
an integer number of basis points -- never a decimal and never a string. Every
temporal value is a full ISO 8601 UTC instant, never a bare date. Optional
fields left at None are omitted from the payload entirely so that a caller can
distinguish "not supplied" from "supplied as null"; when a test needs an
explicit null it passes it through the ``extra`` mapping.
"""
from typing import Any, Dict, Optional

from .constants import (
    AUG_01,
    AUG_31,
    CLOCK_START,
)


def _clean(payload: Dict[str, Any], extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Drop unsupplied keys, then apply explicit overrides (including nulls)."""
    body = {key: value for key, value in payload.items() if value is not None}
    if extra:
        body.update(extra)
    return body


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5)
# ---------------------------------------------------------------------------


def clock_payload(to_iso8601: str = CLOCK_START, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The clock reposition body; the target instant travels in `to_iso8601`."""
    return _clean({"to_iso8601": to_iso8601}, extra)


# ---------------------------------------------------------------------------
# Stores (PRD 3.1)
# ---------------------------------------------------------------------------


def store_payload(
    name: str = "Fort Example Commissary",
    channel: str = "COMMISSARY",
    region: str = "CONUS",
    surcharge_rate_bp: Optional[int] = None,
    exchange_markup_bp: Optional[int] = None,
    shelf_block_capacity_facings: Optional[int] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Registration body for a commissary or exchange store."""
    return _clean(
        {
            "name": name,
            "channel": channel,
            "region": region,
            "surcharge_rate_bp": surcharge_rate_bp,
            "exchange_markup_bp": exchange_markup_bp,
            "shelf_block_capacity_facings": shelf_block_capacity_facings,
        },
        extra,
    )


# ---------------------------------------------------------------------------
# Patrons (PRD 3.2, 3.7)
# ---------------------------------------------------------------------------


def patron_payload(
    full_name: str = "SGT A Example",
    id_card_class: str = "ACTIVE_DUTY",
    sponsor_patron_id: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Enrolment body; only a dependent carries a sponsor."""
    return _clean(
        {
            "full_name": full_name,
            "id_card_class": id_card_class,
            "sponsor_patron_id": sponsor_patron_id,
        },
        extra,
    )


def card_status_payload(
    action: str,
    reason: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Card lifecycle body: SUSPEND, REINSTATE or REVOKE with an optional reason."""
    return _clean({"action": action, "reason": reason}, extra)


def compliance_review_payload(
    decision: str,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compliance judgement body: CONFIRM_STRIKE or CLEAR_WATCH."""
    return _clean({"decision": decision}, extra)


# ---------------------------------------------------------------------------
# Shopper delegations (PRD 3.3)
# ---------------------------------------------------------------------------


def delegation_payload(
    sponsor_patron_id: str,
    delegate_patron_id: str,
    expected_delegate_patron_version: int,
    valid_from: str = AUG_01,
    valid_to: str = AUG_31,
    per_sale_spend_cap_cents: int = 100000,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Grant body. The delegate patron's observed version is mandatory."""
    return _clean(
        {
            "sponsor_patron_id": sponsor_patron_id,
            "delegate_patron_id": delegate_patron_id,
            "valid_from": valid_from,
            "valid_to": valid_to,
            "per_sale_spend_cap_cents": per_sale_spend_cap_cents,
            "expected_delegate_patron_version": expected_delegate_patron_version,
        },
        extra,
    )


def delegation_revoke_payload(
    reason: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Withdrawal body; the reason is optional free text."""
    return _clean({"reason": reason}, extra)


# ---------------------------------------------------------------------------
# Products and assortment allocations (PRD 3.4)
# ---------------------------------------------------------------------------


def product_payload(
    sku: str,
    name: Optional[str] = None,
    category: str = "GROCERY_STAPLE",
    unit_cost_cents: int = 1000,
    unit_weight_grams: Optional[int] = None,
    quantity_limit_per_visit: Optional[int] = None,
    resale_restricted: Optional[bool] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Worldwide item file body. The sku must be unique across all products."""
    return _clean(
        {
            "sku": sku,
            "name": name if name is not None else f"Item {sku}",
            "category": category,
            "unit_cost_cents": unit_cost_cents,
            "unit_weight_grams": unit_weight_grams,
            "quantity_limit_per_visit": quantity_limit_per_visit,
            "resale_restricted": resale_restricted,
        },
        extra,
    )


def assortment_payload(
    store_id: str,
    product_id: str,
    expected_store_version: int,
    shelf_block: str = "A1",
    facings: int = 4,
    supply_mode: str = "WAREHOUSE",
    vendor_name: Optional[str] = None,
    promo_allowance_bp: Optional[int] = None,
    promo_window_start: Optional[str] = None,
    promo_window_end: Optional[str] = None,
    effective_from: str = AUG_01,
    effective_to: str = AUG_31,
    overseas_shipping_allowance_cents: Optional[int] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Shelf allocation body. The store's observed version is mandatory."""
    return _clean(
        {
            "store_id": store_id,
            "product_id": product_id,
            "shelf_block": shelf_block,
            "facings": facings,
            "supply_mode": supply_mode,
            "vendor_name": vendor_name,
            "promo_allowance_bp": promo_allowance_bp,
            "promo_window_start": promo_window_start,
            "promo_window_end": promo_window_end,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "overseas_shipping_allowance_cents": overseas_shipping_allowance_cents,
            "expected_store_version": expected_store_version,
        },
        extra,
    )


def assortment_retire_payload(
    reason: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Retirement body; the reason is optional free text."""
    return _clean({"reason": reason}, extra)


# ---------------------------------------------------------------------------
# Sales (PRD 3.5, 3.6)
# ---------------------------------------------------------------------------


def sale_payload(
    store_id: str,
    patron_id: str,
    acting_delegation_id: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Open-a-visit body; the delegation is named only for an authorized shopper."""
    return _clean(
        {
            "store_id": store_id,
            "patron_id": patron_id,
            "acting_delegation_id": acting_delegation_id,
        },
        extra,
    )


def sale_line_payload(
    product_id: str,
    quantity: int = 1,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Ring-an-item body: just the product and the quantity."""
    return _clean({"product_id": product_id, "quantity": quantity}, extra)


def tender_payload(
    collected_tax_cents: Optional[int] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Tender body; the declared tax figure is optional and must be 0 when given."""
    return _clean({"collected_tax_cents": collected_tax_cents}, extra)


def void_payload(
    voided_reason: str,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Void body; the reason is one of the three declared members."""
    return _clean({"voided_reason": voided_reason}, extra)


# ---------------------------------------------------------------------------
# Fund governance (PRD 3.9)
# ---------------------------------------------------------------------------


def mwr_program_payload(
    store_id: str,
    name: str = "Youth Sports",
    priority_rank: int = 1,
    funding_ceiling_cents: int = 100000,
    status: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Programme registration body; a lower priority rank is filled first."""
    return _clean(
        {
            "store_id": store_id,
            "name": name,
            "priority_rank": priority_rank,
            "funding_ceiling_cents": funding_ceiling_cents,
            "status": status,
        },
        extra,
    )


def capital_project_payload(
    store_id: str,
    title: str = "Deli Case Replacement",
    requested_amount_cents: int = 250000,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Project draft body; the request amount excludes contingency."""
    return _clean(
        {
            "store_id": store_id,
            "title": title,
            "requested_amount_cents": requested_amount_cents,
        },
        extra,
    )


def project_decision_payload(
    decision: str,
    note: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Board decision body: APPROVE, RETURN or REJECT with an optional note."""
    return _clean({"decision": decision, "note": note}, extra)


def project_close_payload(
    outlay_cents: int,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Close-out body carrying the actual outlay in cents."""
    return _clean({"outlay_cents": outlay_cents}, extra)


# ---------------------------------------------------------------------------
# Special orders (PRD 3.8)
# ---------------------------------------------------------------------------


def special_order_payload(
    store_id: str,
    patron_id: str,
    product_id: str,
    quantity: int = 1,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Special order body; the same eligibility gate as opening a visit applies."""
    return _clean(
        {
            "store_id": store_id,
            "patron_id": patron_id,
            "product_id": product_id,
            "quantity": quantity,
        },
        extra,
    )


def route_payload(route: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Routing body: LOCAL_FILL or OVERSEAS_SHIP."""
    return _clean({"route": route}, extra)


def cancel_payload(
    cancelled_reason: str,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Cancellation body; the reason is PATRON_REQUEST or ASSORTMENT_RETIRED."""
    return _clean({"cancelled_reason": cancelled_reason}, extra)
