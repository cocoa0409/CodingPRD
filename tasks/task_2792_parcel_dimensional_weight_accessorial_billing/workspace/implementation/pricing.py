"""Line pricing, the seven-step invoice roll-up and the freeze-boundary
reconciliation branch (PRD 3.6, PRD 2.9)."""

from decimal import Decimal

import calc
import domain
from errors import ApiError
from store import db, new_record, touch

TRIGGER_SCAN_AUTOMATED = "SCAN_AUTOMATED"
TRIGGER_SCAN_MANUAL = "SCAN_MANUAL"
TRIGGER_EXCEPTION = "EXCEPTION"
TRIGGER_MANUAL_ACCESSORIAL = "MANUAL_ACCESSORIAL"
TRIGGER_WAIVER = "WAIVER"

FROZEN_TRIGGERS = (TRIGGER_EXCEPTION, TRIGGER_MANUAL_ACCESSORIAL, TRIGGER_WAIVER)


# --------------------------------------------------------------------------
# line pricing (PRD 3.6)
# --------------------------------------------------------------------------

def find_rate_row(contract, zone, billable_weight_lbs):
    for row in (contract or {}).get("rate_table") or []:
        if row["zone"] != zone:
            continue
        if row["min_lbs"] <= billable_weight_lbs <= row["max_lbs"]:
            return row
    raise ApiError("ERR_RATE_ROW_MISSING",
                   "The governing rate contract has no rate row covering this "
                   "zone and billable weight.")


def qualifying_windows(shipment):
    """ACTIVE windows over the half-open [start_date, end_date) pickup range."""
    pickup_date = shipment["pickup_date"]
    matches = []
    for window in db.surcharge_windows.values():
        if window["status"] != "ACTIVE":
            continue
        if not (window["start_date"] <= pickup_date < window["end_date"]):
            continue
        scope = window["service_level_id"]
        if scope is not None and scope != shipment["service_level_id"]:
            continue
        matches.append(window)
    return matches


def surcharge_cents_for(shipment):
    oversize = domain.has_assessed_oversize(shipment["id"])
    total = 0
    for window in qualifying_windows(shipment):
        total += window["per_package_cents"]
        if oversize:
            total += window["oversize_add_cents"]
    return total


def price_shipment(shipment):
    """The line-pricing rules, shared by the sweep, the preview and repricing."""
    contract = domain.contract_of_shipment(shipment)
    billable = shipment["billable_weight_lbs"]
    row = find_rate_row(contract, shipment["zone"], billable)

    rate_cents_per_lb = row["cents_per_lb"]
    uncapped = billable * rate_cents_per_lb
    min_charge = (contract or {}).get("min_charge_cents") or 0
    transportation_base_cents = max(uncapped, min_charge)

    surcharge = surcharge_cents_for(shipment)
    accessorial = domain.shipment_accessorial_total(shipment["id"])

    return {
        "shipment_id": shipment["id"],
        "contract_id": shipment["contract_id"],
        "billable_weight_lbs": billable,
        "billable_weight_basis": domain.shipment_basis(shipment),
        "rate_cents_per_lb": rate_cents_per_lb,
        "transportation_base_cents": transportation_base_cents,
        "surcharge_cents": surcharge,
        "accessorial_total_cents": accessorial,
        "line_total_cents": transportation_base_cents + surcharge + accessorial,
    }


def create_line(invoice, shipment):
    priced = price_shipment(shipment)
    record = new_record()
    record.update({
        "invoice_id": invoice["id"],
        "shipment_id": shipment["id"],
        "billable_weight_lbs": priced["billable_weight_lbs"],
        "billable_weight_basis": priced["billable_weight_basis"],
        "rate_cents_per_lb": priced["rate_cents_per_lb"],
        "transportation_base_cents": priced["transportation_base_cents"],
        "surcharge_cents": priced["surcharge_cents"],
        "accessorial_total_cents": priced["accessorial_total_cents"],
        "base_line_total_cents": priced["line_total_cents"],
        "voided": False,
    })
    db.invoice_lines[record["id"]] = record
    return record


def reprice_line(line, shipment):
    """Rewrite an OPEN invoice's line from the shipment's current state."""
    priced = price_shipment(shipment)
    line["billable_weight_lbs"] = priced["billable_weight_lbs"]
    line["billable_weight_basis"] = priced["billable_weight_basis"]
    line["rate_cents_per_lb"] = priced["rate_cents_per_lb"]
    line["transportation_base_cents"] = priced["transportation_base_cents"]
    line["surcharge_cents"] = priced["surcharge_cents"]
    line["accessorial_total_cents"] = priced["accessorial_total_cents"]
    line["base_line_total_cents"] = priced["line_total_cents"]
    touch(line)
    return line


# --------------------------------------------------------------------------
# invoice roll-up (PRD 3.6 steps 1-5)
# --------------------------------------------------------------------------

def select_tier_bps(invoice, transportation_subtotal_cents):
    """Step 4: the tier table of the governing contract of the FIRST line."""
    lines = domain.active_lines_of_invoice(invoice["id"]) or domain.lines_of_invoice(invoice["id"])
    if not lines:
        return 0
    shipment = db.shipments.get(lines[0]["shipment_id"])
    contract = domain.contract_of_shipment(shipment or {})
    best = None
    for row in (contract or {}).get("tier_discount_table") or []:
        threshold = row["min_transportation_subtotal_cents"]
        if threshold <= transportation_subtotal_cents:
            if best is None or threshold > best["min_transportation_subtotal_cents"]:
                best = row
    return best["discount_bps"] if best else 0


def recompute_invoice(invoice):
    """Steps 1-5; legal only while OPEN and once more at issue."""
    lines = domain.active_lines_of_invoice(invoice["id"])
    transportation_subtotal = sum(l["transportation_base_cents"] + l["surcharge_cents"]
                                 for l in lines)
    accessorial_subtotal = sum(l["accessorial_total_cents"] for l in lines)
    gross = sum(l["base_line_total_cents"] for l in lines)

    bps = select_tier_bps(invoice, transportation_subtotal)
    discount = int(calc.round_half_up(
        Decimal(transportation_subtotal) * Decimal(bps) / Decimal(10000), 0))

    invoice["transportation_subtotal_cents"] = transportation_subtotal
    invoice["accessorial_subtotal_cents"] = accessorial_subtotal
    invoice["gross_charges_cents"] = gross
    invoice["tier_discount_bps"] = bps
    invoice["tier_discount_cents"] = discount
    return invoice


# --------------------------------------------------------------------------
# the freeze boundary (PRD 2.9)
# --------------------------------------------------------------------------

FROZEN_INVOICE_STATES = ("ISSUED", "ADJUSTED", "SETTLED")


def assert_not_frozen(shipment):
    """Reject a money-changing hand operation once the line's invoice is out of OPEN."""
    line = domain.live_line_for_shipment(shipment["id"])
    if line is None:
        return
    invoice = db.invoices.get(line["invoice_id"])
    if invoice is not None and invoice["status"] in FROZEN_INVOICE_STATES:
        raise ApiError("ERR_LINE_ALREADY_FROZEN",
                       "The shipment's invoice line is frozen; corrections must "
                       "travel as a billing adjustment.")


def reconcile(shipment, trigger):
    """The six-way branch, run after every charge-picture change."""
    line = domain.live_line_for_shipment(shipment["id"])
    if line is None:
        return None
    invoice = db.invoices.get(line["invoice_id"])
    if invoice is None:
        return None

    status = invoice["status"]

    if status == "OPEN":
        reprice_line(line, shipment)
        recompute_invoice(invoice)
        touch(invoice)
        return None

    if status in ("ISSUED", "ADJUSTED"):
        if trigger == TRIGGER_SCAN_AUTOMATED:
            recomputed = price_shipment(shipment)["line_total_cents"]
            delta = recomputed - line["base_line_total_cents"]
            if delta == 0:
                return None
            adjustment = new_record()
            adjustment.update({
                "invoice_line_id": line["id"],
                "reason": "WEIGHT_CORRECTION",
                "delta_cents": delta,
                "status": "PROPOSED",
                "note": None,
                "created_by_user_id": "system",
                "applied_by_user_id": None,
                "applied_at": None,
                "dispute_id": None,
                "guarantee_claim_id": None,
            })
            db.billing_adjustments[adjustment["id"]] = adjustment
            touch(invoice)
            return adjustment
        # manual reweigh, and any trigger the freeze check already rejected
        return None

    # SETTLED or VOID: nothing propagates
    return None
