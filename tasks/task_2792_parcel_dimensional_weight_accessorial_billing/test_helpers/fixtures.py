"""Composite state builders for the parcel billing suite.

The server starts from an empty database for every single test, so every entity
a test needs is built here through the declared API endpoints only. Nothing is
assumed to be seeded, and no builder reaches around the API.

The builders are layered:

* Tier 1 - single state progressions (clock, suspend, activate, cancel).
* Tier 2 - the entity hierarchy an inducted parcel needs (account, service
  levels, activated contract, shipment).
* Tier 3 - lifecycle shortcuts that jump straight to a delivered parcel, an
  open / issued / settled invoice, or a proposed adjustment.
* Tier 4 - accumulation and threshold targeting: parcels engineered to breach
  the scan tolerance, to trip the oversize path, or to push an invoice over a
  discount tier break.
* Tier 5 - finalisation and terminal states: verified measurements, voided
  invoices, upheld disputes and refunded guarantee claims.

Every builder takes the api client as its first argument and returns either a
raw ``data`` payload or one of the context records from ``types``.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import (
    DEFAULT_CLOCK_UTC,
    FULL_TIER_TABLE,
    RESIDENTIAL_OVERRIDE_540,
    ZONE2_RATE_ROWS,
    ZONE5_RATE_ROWS,
)
from .test_users import (
    BILLING_OPS_ALT_HEADERS,
    BILLING_OPS_ALT_USER_ID,
    BILLING_OPS_HEADERS,
    BILLING_OPS_USER_ID,
    CARRIER_ADMIN_HEADERS,
    CARRIER_OPS_HEADERS,
    REVENUE_AUDITOR_HEADERS,
    make_shipper_user_headers,
)
from .types import (
    AdjustmentContext,
    ClaimContext,
    DisputeContext,
    Entity,
    InvoiceContext,
    Payload,
    ShipmentContext,
    ShipperContext,
)

# ===========================================================================
# Tier 1 - single state progressions
# ===========================================================================


def set_clock(api, now_utc: str) -> Entity:
    """Move the logical clock and return the echoed value."""
    return get_success_data(api.set_clock(now_utc, CARRIER_ADMIN_HEADERS))


def reset_clock(api) -> Entity:
    """Return the logical clock to the documented startup default."""
    return set_clock(api, DEFAULT_CLOCK_UTC)


def create_shipper_account(api, **kwargs: Any) -> Entity:
    """Create one ACTIVE shipper account."""
    return get_success_data(
        api.create_shipper_account(f.shipper_account_payload(**kwargs), CARRIER_ADMIN_HEADERS)
    )


def suspend_shipper_account(api, shipper_id: str) -> Entity:
    """Move a shipper account to SUSPENDED."""
    return get_success_data(
        api.suspend_shipper_account(shipper_id, CARRIER_ADMIN_HEADERS)
    )


def create_service_level(api, payload: Optional[Payload] = None, **kwargs: Any) -> Entity:
    """Create one service level."""
    body = payload if payload is not None else f.service_level_payload(**kwargs)
    return get_success_data(api.create_service_level(body, CARRIER_ADMIN_HEADERS))


def create_express_service_level(api, **kwargs: Any) -> Entity:
    """Create the guaranteed 24 hour EXPRESS service level."""
    return get_success_data(
        api.create_service_level(
            f.express_service_level_payload(**kwargs), CARRIER_ADMIN_HEADERS
        )
    )


def create_ground_service_level(api, **kwargs: Any) -> Entity:
    """Create the unguaranteed 120 hour GROUND service level."""
    return get_success_data(
        api.create_service_level(
            f.ground_service_level_payload(**kwargs), CARRIER_ADMIN_HEADERS
        )
    )


def draft_rate_contract(api, shipper_id: str, **kwargs: Any) -> Entity:
    """Create a DRAFT rate contract without activating it."""
    return get_success_data(
        api.create_rate_contract(
            f.rate_contract_payload(shipper_id, **kwargs), CARRIER_ADMIN_HEADERS
        )
    )


def activate_rate_contract(api, contract_id: str, shipper_version: int) -> Entity:
    """Activate a DRAFT contract, guarding on the shipper account version."""
    return get_success_data(
        api.activate_rate_contract(contract_id, shipper_version, CARRIER_ADMIN_HEADERS)
    )


def create_surcharge_window(api, **kwargs: Any) -> Entity:
    """Create a SCHEDULED surcharge window."""
    return get_success_data(
        api.create_surcharge_window(
            f.surcharge_window_payload(**kwargs), CARRIER_ADMIN_HEADERS
        )
    )


def activate_surcharge_window(api, window_id: str) -> Entity:
    """Move a SCHEDULED surcharge window to ACTIVE so pricing can see it."""
    return get_success_data(api.activate_surcharge_window(window_id, CARRIER_ADMIN_HEADERS))


def cancel_surcharge_window(api, window_id: str) -> Entity:
    """Move a surcharge window to CANCELLED."""
    return get_success_data(api.cancel_surcharge_window(window_id, CARRIER_ADMIN_HEADERS))


def active_surcharge_window(api, **kwargs: Any) -> Entity:
    """Create and activate a surcharge window in one step."""
    window = create_surcharge_window(api, **kwargs)
    return activate_surcharge_window(api, window["id"])


# ===========================================================================
# Tier 2 - the entity hierarchy behind an inducted parcel
# ===========================================================================


def shipper_with_active_contract(
    api,
    account_number: Optional[str] = None,
    name: str = "Northwind Freight",
    contract_kwargs: Optional[Dict[str, Any]] = None,
    with_express: bool = True,
    with_ground: bool = True,
) -> ShipperContext:
    """An ACTIVE shipper, its service levels and an ACTIVE rate contract.

    This is the prefix nearly every workflow needs: without an ACTIVE contract
    covering the pickup date no parcel can be inducted at all.
    """
    account = create_shipper_account(api, account_number=account_number, name=name)
    service_levels: Dict[str, str] = {}
    if with_express:
        service_levels["EXPRESS"] = create_express_service_level(api)["id"]
    if with_ground:
        service_levels["GROUND"] = create_ground_service_level(api)["id"]

    contract = draft_rate_contract(api, account["id"], **(contract_kwargs or {}))
    activate_rate_contract(api, contract["id"], account["version"])
    refreshed = get_success_data(api.get_shipper_account(account["id"], CARRIER_ADMIN_HEADERS))

    return ShipperContext(
        shipper_id=account["id"],
        shipper_version=refreshed["version"],
        contract_id=contract["id"],
        service_level_ids=service_levels,
        shipper_headers=make_shipper_user_headers(account["id"]),
    )


def shipper_with_residential_override(api, **kwargs: Any) -> ShipperContext:
    """A shipper whose contract overrides the RESIDENTIAL accessorial to 540."""
    contract_kwargs = dict(kwargs.pop("contract_kwargs", {}))
    contract_kwargs.setdefault("accessorial_rate_overrides", RESIDENTIAL_OVERRIDE_540)
    return shipper_with_active_contract(api, contract_kwargs=contract_kwargs, **kwargs)


def shipper_with_multi_zone_contract(api, **kwargs: Any) -> ShipperContext:
    """A shipper whose contract prices zones 2 and 5 and carries both tiers."""
    contract_kwargs = dict(kwargs.pop("contract_kwargs", {}))
    contract_kwargs.setdefault("rate_table", list(ZONE2_RATE_ROWS) + list(ZONE5_RATE_ROWS))
    contract_kwargs.setdefault("tier_discount_table", list(FULL_TIER_TABLE))
    contract_kwargs.setdefault("accessorial_rate_overrides", RESIDENTIAL_OVERRIDE_540)
    return shipper_with_active_contract(api, contract_kwargs=contract_kwargs, **kwargs)


def induct_shipment(
    api,
    shipper: ShipperContext,
    service_level: str = "GROUND",
    **kwargs: Any,
) -> ShipmentContext:
    """Induct one parcel against an existing shipper context."""
    service_level_id = kwargs.pop(
        "service_level_id", shipper.service_level_ids[service_level]
    )
    data = get_success_data(
        api.create_shipment(
            f.shipment_payload(shipper.shipper_id, service_level_id, **kwargs),
            CARRIER_OPS_HEADERS,
        )
    )
    return ShipmentContext(
        shipper=shipper,
        shipment_id=data["id"],
        shipment_version=data["version"],
        shipment=data,
    )


def refresh_shipment(api, shipment_id: str) -> Entity:
    """Re-read a shipment, which is how a caller learns its current version."""
    return get_success_data(api.get_shipment(shipment_id, CARRIER_OPS_HEADERS))


def refresh_shipper_account(api, shipper_id: str) -> Entity:
    """Re-read a shipper account and its five ledger aggregates."""
    return get_success_data(api.get_shipper_account(shipper_id, CARRIER_ADMIN_HEADERS))


def refresh_invoice(api, invoice_id: str) -> Entity:
    """Re-read an invoice, which is how a caller learns its current version."""
    return get_success_data(api.get_invoice(invoice_id, BILLING_OPS_HEADERS))


def refresh_invoice_line(api, line_id: str) -> Entity:
    """Re-read a single invoice line."""
    return get_success_data(api.get_invoice_line(line_id, BILLING_OPS_HEADERS))


def add_scan(
    api, shipment_id: str, expected_version: Optional[int] = None, **kwargs: Any
) -> Entity:
    """Capture one dimension scan, re-reading the shipment version when needed."""
    if expected_version is None:
        expected_version = refresh_shipment(api, shipment_id)["version"]
    return get_success_data(
        api.create_scan(
            shipment_id, f.scan_payload(expected_version, **kwargs), CARRIER_OPS_HEADERS
        )
    )


def add_manual_accessorial(api, shipment_id: str, code: str, **kwargs: Any) -> Entity:
    """Hand-enter one MANUAL accessorial charge against a parcel."""
    return get_success_data(
        api.create_accessorial(
            shipment_id, f.accessorial_payload(code=code, **kwargs), BILLING_OPS_HEADERS
        )
    )


def raise_exception(api, shipment_id: str, kind: str, **kwargs: Any) -> Entity:
    """Record a movement exception against a parcel."""
    return get_success_data(
        api.create_exception(
            shipment_id, f.exception_payload(kind, **kwargs), CARRIER_OPS_HEADERS
        )
    )


# ===========================================================================
# Tier 3 - lifecycle shortcuts
# ===========================================================================


def delivered_shipment(
    api, shipper: ShipperContext, service_level: str = "GROUND", **kwargs: Any
) -> ShipmentContext:
    """Induct a parcel and deliver it, which is the gate the sweep reads."""
    ctx = induct_shipment(api, shipper, service_level=service_level, **kwargs)
    get_success_data(api.deliver_shipment(ctx.shipment_id, CARRIER_OPS_HEADERS))
    refreshed = refresh_shipment(api, ctx.shipment_id)
    return ShipmentContext(
        shipper=shipper,
        shipment_id=ctx.shipment_id,
        shipment_version=refreshed["version"],
        shipment=refreshed,
    )


def line_ids_for_invoice(api, invoice_id: str) -> List[Entity]:
    """Every invoice line belonging to one invoice, in creation order."""
    return get_success_data(
        api.list_invoice_lines(BILLING_OPS_HEADERS, {"invoice_id": invoice_id, "limit": 100})
    )


def line_for_shipment(api, invoice_id: str, shipment_id: str) -> Entity:
    """The single invoice line that joins one invoice to one shipment."""
    rows = get_success_data(
        api.list_invoice_lines(
            BILLING_OPS_HEADERS, {"invoice_id": invoice_id, "shipment_id": shipment_id}
        )
    )
    assert len(rows) == 1, (
        f"expected exactly one line for shipment {shipment_id} on invoice "
        f"{invoice_id}, found {len(rows)}"
    )
    return rows[0]


def open_invoice(
    api,
    shipper: ShipperContext,
    shipment_ids: List[str],
    period_start: str = "2026-08-01",
    period_end: str = "2026-08-31",
    **kwargs: Any,
) -> InvoiceContext:
    """Sweep the delivered parcels of a period onto one OPEN invoice."""
    data = get_success_data(
        api.create_invoice(
            f.invoice_sweep_payload(
                shipper.shipper_id,
                period_start=period_start,
                period_end=period_end,
                **kwargs,
            ),
            BILLING_OPS_HEADERS,
        )
    )
    lines = line_ids_for_invoice(api, data["id"])
    return InvoiceContext(
        shipper=shipper,
        invoice_id=data["id"],
        invoice_version=data["version"],
        invoice=data,
        shipment_ids=list(shipment_ids),
        line_ids=[row["id"] for row in lines],
        line_by_shipment={row["shipment_id"]: row["id"] for row in lines},
    )


def issued_invoice(api, invoice: InvoiceContext) -> InvoiceContext:
    """Issue an OPEN invoice, freezing its tier row and opening the dispute window."""
    data = get_success_data(api.issue_invoice(invoice.invoice_id, BILLING_OPS_HEADERS))
    return invoice._replace(invoice=data, invoice_version=data["version"])


def settled_invoice(
    api, invoice: InvoiceContext, payment_reference: str = "ACH-0001"
) -> InvoiceContext:
    """Settle an ISSUED invoice."""
    data = get_success_data(
        api.settle_invoice(invoice.invoice_id, payment_reference, BILLING_OPS_HEADERS)
    )
    return invoice._replace(invoice=data, invoice_version=data["version"])


def voided_invoice(api, invoice: InvoiceContext) -> InvoiceContext:
    """Void an invoice, returning its parcels to the unbilled pool."""
    data = get_success_data(api.void_invoice(invoice.invoice_id, BILLING_OPS_HEADERS))
    return invoice._replace(invoice=data, invoice_version=data["version"])


def delivered_and_issued(
    api,
    shipper: ShipperContext,
    shipment_kwargs: Optional[Dict[str, Any]] = None,
    service_level: str = "GROUND",
    period_start: str = "2026-08-01",
    period_end: str = "2026-08-31",
) -> InvoiceContext:
    """One delivered parcel swept onto an invoice that is then ISSUED.

    This is the composite prefix every adjustment, dispute and guarantee-claim
    workflow starts from, because all three read a frozen invoice line.
    """
    parcel = delivered_shipment(
        api, shipper, service_level=service_level, **(shipment_kwargs or {})
    )
    invoice = open_invoice(
        api,
        shipper,
        [parcel.shipment_id],
        period_start=period_start,
        period_end=period_end,
    )
    return issued_invoice(api, invoice)


def propose_adjustment(
    api,
    invoice: InvoiceContext,
    invoice_line_id: str,
    delta_cents: int,
    reason: str = "MANUAL",
    proposer_headers: Optional[Dict[str, str]] = None,
    proposer_user_id: str = BILLING_OPS_USER_ID,
    releaser_user_id: str = BILLING_OPS_ALT_USER_ID,
    note: Optional[str] = "test adjustment",
    expected_invoice_version: Optional[int] = None,
) -> AdjustmentContext:
    """Propose a PENDING billing adjustment against one line."""
    if expected_invoice_version is None:
        expected_invoice_version = refresh_invoice(api, invoice.invoice_id)["version"]
    data = get_success_data(
        api.create_billing_adjustment(
            f.billing_adjustment_payload(
                invoice_line_id,
                delta_cents,
                expected_invoice_version,
                reason=reason,
                note=note,
            ),
            proposer_headers or BILLING_OPS_HEADERS,
        )
    )
    return AdjustmentContext(
        invoice=invoice,
        adjustment_id=data["id"],
        invoice_line_id=invoice_line_id,
        proposer_user_id=proposer_user_id,
        releaser_user_id=releaser_user_id,
    )


def apply_adjustment(api, adjustment: AdjustmentContext) -> Entity:
    """Release a proposed adjustment as a different operator than the proposer."""
    return get_success_data(
        api.apply_billing_adjustment(adjustment.adjustment_id, BILLING_OPS_ALT_HEADERS)
    )


def applied_adjustment(
    api, invoice: InvoiceContext, invoice_line_id: str, delta_cents: int, **kwargs: Any
) -> AdjustmentContext:
    """Propose and release an adjustment, moving the invoice to ADJUSTED."""
    adjustment = propose_adjustment(
        api, invoice, invoice_line_id, delta_cents, **kwargs
    )
    apply_adjustment(api, adjustment)
    return adjustment


# ===========================================================================
# Tier 4 - accumulation and threshold targeting
# ===========================================================================

# A 10 x 10 x 20 inch parcel at 30.0 lb cubes to 2000 in3, so a scanned height
# of 21 inches lifts the cube to 2100 in3 and lands the cube variance exactly on
# the 5.00 percent tolerance edge.
TOLERANCE_EDGE_DECLARED = {
    "declared_length_in": 10,
    "declared_width_in": 10,
    "declared_height_in": 20,
    "declared_weight_lbs": 30.0,
}

# A 100 x 20 x 20 inch parcel has a longest side over 96 inches, so it is
# oversize on the longest-side limb alone.
OVERSIZE_DECLARED = {
    "declared_length_in": 100,
    "declared_width_in": 20,
    "declared_height_in": 20,
    "declared_weight_lbs": 60.0,
}

# An 18.4 x 12.6 x 10.5 inch parcel at 9.2 lb exercises per-dimension rounding:
# each side rounds before the multiplication, never after.
ROUNDING_DECLARED = {
    "declared_length_in": 18.4,
    "declared_width_in": 12.6,
    "declared_height_in": 10.5,
    "declared_weight_lbs": 9.2,
}

# A 12 x 10 x 8 inch parcel at 6.0 lb cubes to 960 in3 and bills on 7 lb.
SMALL_DECLARED = {
    "declared_length_in": 12,
    "declared_width_in": 10,
    "declared_height_in": 8,
    "declared_weight_lbs": 6.0,
}


def shipment_at_tolerance_edge(
    api, shipper: ShipperContext, service_level: str = "GROUND"
) -> ShipmentContext:
    """A parcel declared so that a one inch height error breaches the tolerance."""
    return induct_shipment(
        api, shipper, service_level=service_level, **TOLERANCE_EDGE_DECLARED
    )


def oversize_shipment(
    api, shipper: ShipperContext, service_level: str = "GROUND", zone: int = 5
) -> ShipmentContext:
    """A parcel whose longest side alone trips the oversize assessment."""
    return induct_shipment(
        api, shipper, service_level=service_level, zone=zone, **OVERSIZE_DECLARED
    )


def tolerance_flagged_shipment(
    api, shipper: ShipperContext, service_level: str = "GROUND"
) -> ShipmentContext:
    """A parcel whose automated scan breached the cube tolerance."""
    ctx = shipment_at_tolerance_edge(api, shipper, service_level=service_level)
    add_scan(
        api,
        ctx.shipment_id,
        expected_version=ctx.shipment_version,
        scan_source="AUTOMATED_DWS",
        scanned_length_in=10,
        scanned_width_in=10,
        scanned_height_in=21,
        scanned_weight_lbs=30.0,
    )
    refreshed = refresh_shipment(api, ctx.shipment_id)
    return ctx._replace(shipment=refreshed, shipment_version=refreshed["version"])


def invoice_over_first_tier_break(
    api, shipper: ShipperContext
) -> InvoiceContext:
    """Two parcels whose combined transportation clears the first discount tier.

    The small residential EXPRESS parcel and the heavy oversize zone-5 GROUND
    parcel together push the pre-discount transportation subtotal well past the
    50000 cent break, so the tier row is selected and applied.
    """
    small = delivered_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        zone=2,
        residential_declared=True,
        **ROUNDING_DECLARED,
    )
    heavy = delivered_shipment(
        api, shipper, service_level="GROUND", zone=5, **OVERSIZE_DECLARED
    )
    return open_invoice(api, shipper, [small.shipment_id, heavy.shipment_id])


# ===========================================================================
# Tier 5 - finalisation and terminal states
# ===========================================================================


def verified_shipment(
    api, shipper: ShipperContext, service_level: str = "GROUND", **scan_kwargs: Any
) -> ShipmentContext:
    """A parcel whose measurement axis has reached its terminal VERIFIED state.

    A manual reweigh is the only pathway that finalises the measurement, and no
    further scan is admitted afterwards.
    """
    ctx = induct_shipment(
        api, shipper, service_level=service_level, **TOLERANCE_EDGE_DECLARED
    )
    defaults = {
        "scan_source": "MANUAL_REWEIGH",
        "scanned_length_in": 10,
        "scanned_width_in": 10,
        "scanned_height_in": 20,
        "scanned_weight_lbs": 30.0,
    }
    defaults.update(scan_kwargs)
    add_scan(api, ctx.shipment_id, expected_version=ctx.shipment_version, **defaults)
    refreshed = refresh_shipment(api, ctx.shipment_id)
    return ctx._replace(shipment=refreshed, shipment_version=refreshed["version"])


def filed_dispute(
    api,
    invoice: InvoiceContext,
    invoice_line_id: str,
    claim_type: str = "WEIGHT",
    disputed_codes: Optional[List[str]] = None,
    claimed_reason: str = "The billed weight does not match the parcel",
) -> DisputeContext:
    """A dispute filed by the owning shipper against an issued line."""
    line = refresh_invoice_line(api, invoice_line_id)
    data = get_success_data(
        api.create_dispute(
            f.dispute_payload(
                invoice_line_id,
                claim_type=claim_type,
                claimed_reason=claimed_reason,
                disputed_codes=disputed_codes,
            ),
            invoice.shipper.shipper_headers,
        )
    )
    return DisputeContext(
        invoice=invoice,
        dispute_id=data["id"],
        invoice_line_id=invoice_line_id,
        shipment_id=line["shipment_id"],
    )


def dispute_under_review(
    api, dispute: DisputeContext, required_item_type: str = "DELIVERY_PHOTO"
) -> Entity:
    """Drive a dispute through one evidence round so it sits UNDER_REVIEW."""
    get_success_data(
        api.request_evidence(
            dispute.dispute_id, required_item_type, REVENUE_AUDITOR_HEADERS
        )
    )
    get_success_data(
        api.submit_evidence(
            dispute.dispute_id,
            f.evidence_payload(item_type=required_item_type),
            dispute.invoice.shipper.shipper_headers,
        )
    )
    return get_success_data(
        api.get_dispute(dispute.dispute_id, REVENUE_AUDITOR_HEADERS)
    )


def dispute_at_round_cap(
    api, dispute: DisputeContext, required_item_type: str = "DELIVERY_PHOTO"
) -> Entity:
    """Exhaust both admissible evidence rounds on a dispute."""
    dispute_under_review(api, dispute, required_item_type=required_item_type)
    dispute_under_review(api, dispute, required_item_type=required_item_type)
    return get_success_data(api.get_dispute(dispute.dispute_id, REVENUE_AUDITOR_HEADERS))


def upheld_dispute(api, dispute: DisputeContext) -> Entity:
    """Resolve a dispute in the shipper's favour, minting the credit cascade."""
    return get_success_data(
        api.resolve_dispute(dispute.dispute_id, "UPHELD", REVENUE_AUDITOR_HEADERS)
    )


def filed_guarantee_claim(
    api, shipment_id: str, claimed_reason: str = "Delivered past the commitment"
) -> Entity:
    """File a guarantee claim as the revenue auditor."""
    return get_success_data(
        api.create_guarantee_claim(
            f.guarantee_claim_payload(shipment_id, claimed_reason=claimed_reason),
            REVENUE_AUDITOR_HEADERS,
        )
    )


def late_delivered_express_parcel(
    api,
    shipper: ShipperContext,
    delivered_at: str = "2026-08-02T03:00:00Z",
    **shipment_kwargs: Any,
) -> ShipmentContext:
    """An EXPRESS parcel inducted at the default clock and delivered late.

    The commitment is 24 hours from pickup, so any delivery instant strictly
    after 2026-08-02T00:00:00Z is late.
    """
    payload_kwargs = dict(SMALL_DECLARED)
    payload_kwargs.update(shipment_kwargs)
    ctx = induct_shipment(api, shipper, service_level="EXPRESS", **payload_kwargs)
    set_clock(api, delivered_at)
    get_success_data(api.deliver_shipment(ctx.shipment_id, CARRIER_OPS_HEADERS))
    refreshed = refresh_shipment(api, ctx.shipment_id)
    return ctx._replace(shipment=refreshed, shipment_version=refreshed["version"])


def approved_guarantee_claim(
    api, shipper: ShipperContext, delivered_at: str = "2026-08-02T03:00:00Z"
) -> ClaimContext:
    """A late EXPRESS parcel, invoiced, claimed and adjudicated APPROVED.

    Approval only proposes the refund adjustment; the claim does not become
    REFUNDED until that adjustment is released by a second operator.
    """
    parcel = late_delivered_express_parcel(api, shipper, delivered_at=delivered_at)
    invoice = open_invoice(api, shipper, [parcel.shipment_id])
    invoice = issued_invoice(api, invoice)
    line = line_for_shipment(api, invoice.invoice_id, parcel.shipment_id)
    claim = filed_guarantee_claim(api, parcel.shipment_id)
    get_success_data(
        api.adjudicate_guarantee_claim(claim["id"], "APPROVED", REVENUE_AUDITOR_HEADERS)
    )
    return ClaimContext(
        invoice=invoice,
        claim_id=claim["id"],
        shipment_id=parcel.shipment_id,
        invoice_line_id=line["id"],
        candidate_refund_cents=claim["candidate_refund_cents"],
    )


def adjustment_for_claim(api, claim_id: str) -> Entity:
    """The single billing adjustment a guarantee-claim approval proposed."""
    rows = get_success_data(
        api.list_billing_adjustments(BILLING_OPS_HEADERS, {"guarantee_claim_id": claim_id})
    )
    assert len(rows) == 1, (
        f"expected exactly one adjustment for claim {claim_id}, found {len(rows)}"
    )
    return rows[0]


def adjustments_for_line(api, invoice_line_id: str) -> List[Entity]:
    """Every billing adjustment hanging off one invoice line."""
    return get_success_data(
        api.list_billing_adjustments(
            BILLING_OPS_HEADERS, {"invoice_line_id": invoice_line_id, "limit": 100}
        )
    )


def accessorials_for_shipment(api, shipment_id: str, **params: Any) -> List[Entity]:
    """Every accessorial charge assessed against one parcel."""
    query: Dict[str, Any] = {"limit": 100}
    query.update(params)
    return get_success_data(api.list_accessorials(shipment_id, BILLING_OPS_HEADERS, query))
