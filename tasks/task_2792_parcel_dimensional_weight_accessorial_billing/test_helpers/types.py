"""Shared type aliases and small record types for the parcel billing suite.

These exist purely to make helper signatures and fixture return values
self-documenting. Nothing here is validated at runtime.
"""

from typing import Any, Dict, List, NamedTuple, Optional

# A decoded ``data`` payload from a success envelope.
Entity = Dict[str, Any]

# A JSON request body. Money values inside are always ``int`` cents.
Payload = Dict[str, Any]

# An auth header dict as produced by test_users.
Headers = Dict[str, str]

# A rate-table row: zone, inclusive weight band and the per-pound rate.
RateRow = Dict[str, int]

# A tier-discount row: the pre-discount transportation break and its bps.
TierRow = Dict[str, int]

Cents = int


class ShipperContext(NamedTuple):
    """An ACTIVE shipper with an ACTIVE contract and at least one service level."""

    shipper_id: str
    shipper_version: int
    contract_id: str
    service_level_ids: Dict[str, str]
    shipper_headers: Headers


class ShipmentContext(NamedTuple):
    """An inducted shipment together with the account context that produced it."""

    shipper: ShipperContext
    shipment_id: str
    shipment_version: int
    shipment: Entity


class InvoiceContext(NamedTuple):
    """A swept invoice, its lines and the shipments behind them."""

    shipper: ShipperContext
    invoice_id: str
    invoice_version: int
    invoice: Entity
    shipment_ids: List[str]
    line_ids: List[str]
    line_by_shipment: Dict[str, str]


class AdjustmentContext(NamedTuple):
    """A proposed billing adjustment and the invoice line it hangs off."""

    invoice: InvoiceContext
    adjustment_id: str
    invoice_line_id: str
    proposer_user_id: str
    releaser_user_id: str


class DisputeContext(NamedTuple):
    """A dispute filed against an issued invoice line."""

    invoice: InvoiceContext
    dispute_id: str
    invoice_line_id: str
    shipment_id: str


class ClaimContext(NamedTuple):
    """A filed guarantee claim against a late, invoiced shipment."""

    invoice: InvoiceContext
    claim_id: str
    shipment_id: str
    invoice_line_id: str
    candidate_refund_cents: Optional[Cents]
