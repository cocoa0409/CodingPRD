"""Domain services: lookups, accessorial assessment, line pricing, invoice
roll-up, the reconciliation branch and the shipper ledger.

PRD 2.9 (cascade propagation / freeze boundary), PRD 2.11 (ledger),
PRD 3.3-3.9.
"""

from decimal import Decimal

import calc
from errors import ApiError
from store import (add_days, db, iso, new_record, now, order_key, parse_day,
                   sorted_records, touch)

# --------------------------------------------------------------------------
# generic lookups
# --------------------------------------------------------------------------

def require_record(collection, record_id, error_id):
    if not isinstance(record_id, str) or record_id not in collection:
        raise ApiError(error_id)
    return collection[record_id]


def shipper_or_404(shipper_id):
    return require_record(db.shipper_accounts, shipper_id, "ERR_SHIPPER_NOT_FOUND")


def contract_or_404(contract_id):
    return require_record(db.rate_contracts, contract_id, "ERR_CONTRACT_NOT_FOUND")


def service_level_or_404(service_level_id):
    return require_record(db.service_levels, service_level_id, "ERR_SERVICE_LEVEL_NOT_FOUND")


def window_or_404(window_id):
    return require_record(db.surcharge_windows, window_id, "ERR_SURCHARGE_WINDOW_NOT_FOUND")


def shipment_or_404(shipment_id):
    return require_record(db.shipments, shipment_id, "ERR_SHIPMENT_NOT_FOUND")


def charge_or_404(charge_id):
    return require_record(db.accessorial_charges, charge_id, "ERR_ACCESSORIAL_NOT_FOUND")


def invoice_or_404(invoice_id):
    return require_record(db.invoices, invoice_id, "ERR_INVOICE_NOT_FOUND")


def line_or_404(line_id):
    return require_record(db.invoice_lines, line_id, "ERR_INVOICE_LINE_NOT_FOUND")


def adjustment_or_404(adjustment_id):
    return require_record(db.billing_adjustments, adjustment_id, "ERR_ADJUSTMENT_NOT_FOUND")


def dispute_or_404(dispute_id):
    return require_record(db.disputes, dispute_id, "ERR_DISPUTE_NOT_FOUND")


def claim_or_404(claim_id):
    return require_record(db.guarantee_claims, claim_id, "ERR_CLAIM_NOT_FOUND")


# --------------------------------------------------------------------------
# relationship helpers
# --------------------------------------------------------------------------

def charges_of_shipment(shipment_id):
    return sorted_records([c for c in db.accessorial_charges.values()
                           if c["shipment_id"] == shipment_id])


def assessed_charges(shipment_id):
    return [c for c in charges_of_shipment(shipment_id) if c["status"] == "ASSESSED"]


def shipment_accessorial_total(shipment_id):
    return sum(c["amount_cents"] for c in assessed_charges(shipment_id))


def has_assessed_oversize(shipment_id):
    return any(c["code"] == "OVERSIZE" for c in assessed_charges(shipment_id))


def scans_of_shipment(shipment_id):
    return sorted_records([s for s in db.dimension_scans.values()
                           if s["shipment_id"] == shipment_id])


def governing_scan(shipment_id):
    """The most recently created scan: captured_at DESC then created_at DESC.

    The record id is never an ordering key; insertion order breaks exact ties.
    """
    scans = [s for s in db.dimension_scans.values() if s["shipment_id"] == shipment_id]
    if not scans:
        return None
    scans.sort(key=lambda s: (s["captured_at"], s["created_at"], s["_seq"]), reverse=True)
    return scans[0]


def lines_of_invoice(invoice_id):
    return sorted(
        [l for l in db.invoice_lines.values() if l["invoice_id"] == invoice_id],
        key=lambda l: (shipment_pickup_date(l["shipment_id"]), l["created_at"], l["_seq"]),
    )


def active_lines_of_invoice(invoice_id):
    return [l for l in lines_of_invoice(invoice_id) if not l["voided"]]


def shipment_pickup_date(shipment_id):
    shipment = db.shipments.get(shipment_id)
    return shipment["pickup_date"] if shipment else ""


def live_line_for_shipment(shipment_id):
    """The single non-voided InvoiceLine of a shipment; at most one exists."""
    candidates = [l for l in db.invoice_lines.values()
                  if l["shipment_id"] == shipment_id and not l["voided"]]
    if not candidates:
        return None
    candidates.sort(key=order_key)
    return candidates[-1]


def adjustments_of_line(line_id):
    return sorted_records([a for a in db.billing_adjustments.values()
                           if a["invoice_line_id"] == line_id])


def line_adjustment_total(line_id):
    return sum(a["delta_cents"] for a in db.billing_adjustments.values()
               if a["invoice_line_id"] == line_id and a["status"] == "APPLIED")


def line_total_cents(line):
    return line["base_line_total_cents"] + line_adjustment_total(line["id"])


def invoice_adjustment_total(invoice_id):
    total = 0
    for line in lines_of_invoice(invoice_id):
        total += line_adjustment_total(line["id"])
    return total


def invoice_pending_count(invoice_id):
    count = 0
    for line in lines_of_invoice(invoice_id):
        count += len([a for a in db.billing_adjustments.values()
                      if a["invoice_line_id"] == line["id"] and a["status"] == "PROPOSED"])
    return count


def invoice_net_amount(invoice):
    if invoice["status"] == "VOID":
        return 0
    return (invoice["gross_charges_cents"]
            - invoice["tier_discount_cents"]
            + invoice_adjustment_total(invoice["id"]))


def evidence_of_dispute(dispute_id):
    return sorted_records([e for e in db.evidence_items.values()
                           if e["dispute_id"] == dispute_id])


def accepted_evidence_count(dispute_id):
    return len([e for e in db.evidence_items.values()
                if e["dispute_id"] == dispute_id and e["accepted"]])


# --------------------------------------------------------------------------
# shipper ledger aggregates (PRD 2.11)
# --------------------------------------------------------------------------

def shipments_of_shipper(shipper_id):
    return [s for s in db.shipments.values() if s["shipper_id"] == shipper_id]


def invoices_of_shipper(shipper_id):
    return [i for i in db.invoices.values() if i["shipper_id"] == shipper_id]


def ledger_aggregates(shipper_id):
    shipments = shipments_of_shipper(shipper_id)
    total = len(shipments)
    unbilled = len([s for s in shipments if s["billing_status"] == "UNBILLED"])
    billed = len([s for s in shipments if s["billing_status"] in ("BILLED", "ADJUSTED")])

    open_charges = 0
    credit = 0
    for invoice in invoices_of_shipper(shipper_id):
        if invoice["status"] in ("ISSUED", "ADJUSTED"):
            open_charges += invoice_net_amount(invoice)
        if invoice["status"] != "VOID":
            credit -= invoice_adjustment_total(invoice["id"])

    return {
        "total_shipment_count": total,
        "unbilled_shipment_count": unbilled,
        "billed_shipment_count": billed,
        "credit_balance_cents": credit,
        "open_charges_cents": open_charges,
    }


# --------------------------------------------------------------------------
# contract selection (PRD 3.3)
# --------------------------------------------------------------------------

def select_contract(shipper_id, pickup_date):
    """ACTIVE contracts only, ranked by effective_from DESC then created_at ASC."""
    candidates = []
    for contract in db.rate_contracts.values():
        if contract["shipper_id"] != shipper_id:
            continue
        if contract["status"] != "ACTIVE":
            continue
        if contract["effective_from"] <= pickup_date <= contract["effective_to"]:
            candidates.append(contract)
    if not candidates:
        raise ApiError("ERR_NO_ACTIVE_CONTRACT",
                       "No ACTIVE rate contract of this shipper covers the pickup date.")
    candidates.sort(key=lambda c: (c["created_at"], c["_seq"]))
    candidates.sort(key=lambda c: c["effective_from"], reverse=True)
    return candidates[0]


def contract_of_shipment(shipment):
    return db.rate_contracts.get(shipment.get("contract_id"))


# --------------------------------------------------------------------------
# accessorial charge creation and re-assessment (PRD 3.3, 3.4, 3.5)
# --------------------------------------------------------------------------

def create_charge(shipment, code, source, amount_cents, assessed_basis,
                  reason=None, status="ASSESSED"):
    record = new_record()
    record.update({
        "shipment_id": shipment["id"],
        "code": code,
        "amount_cents": amount_cents,
        "source": source,
        "status": status,
        "reason": reason,
        "assessed_basis": assessed_basis,
    })
    db.accessorial_charges[record["id"]] = record
    return record


def auto_code_set(shipment, contract):
    """The four automatic codes implied by the governing measurement set."""
    codes = {}
    if shipment["residential_declared"] and not (contract or {}).get("residential_waived"):
        codes["RESIDENTIAL"] = "residential_declared=true"
    if shipment["delivery_area_class"] != "NONE":
        codes["DELIVERY_AREA"] = "delivery_area_class=%s" % shipment["delivery_area_class"]
    if shipment["oversize_flag"]:
        codes["OVERSIZE"] = shipment.get("_oversize_basis") or "oversize_flag=true"
    if shipment["additional_handling_flag"]:
        codes["ADDITIONAL_HANDLING"] = (shipment.get("_additional_handling_basis")
                                       or "additional_handling_flag=true")
    return codes


def reassess_auto_accessorials(shipment, contract):
    """Two-directional reconciliation of AUTO charges (PRD 3.4).

    MANUAL charges and WAIVED charges are never created, reversed or repriced.
    """
    implied = auto_code_set(shipment, contract)
    existing = [c for c in charges_of_shipment(shipment["id"])
                if c["source"] == "AUTO" and c["status"] == "ASSESSED"]
    existing_codes = set(c["code"] for c in existing)

    for code, basis in implied.items():
        if code in existing_codes:
            continue
        amount = calc.resolve_accessorial_rate(contract, code,
                                               shipment["delivery_area_class"])
        create_charge(shipment, code, "AUTO", amount, basis)

    reversible = ("RESIDENTIAL", "DELIVERY_AREA", "OVERSIZE", "ADDITIONAL_HANDLING")
    for charge in existing:
        if charge["code"] in reversible and charge["code"] not in implied:
            charge["status"] = "REVERSED"
            touch(charge)


# --------------------------------------------------------------------------
# shipment measurement determinations (PRD 3.3, 3.4)
# --------------------------------------------------------------------------

def apply_preliminary_measurement(shipment):
    """PRELIMINARY variant: reads the shipper's declaration only."""
    result = calc.billable_weight(
        shipment["declared_length_in"], shipment["declared_width_in"],
        shipment["declared_height_in"], shipment["declared_weight_lbs"],
        shipment["divisor_used"], shipment["non_conveyable_declared"],
    )
    shipment["declared_cube_in3"] = result["cube_in3"]
    shipment["preliminary_dim_weight_lbs"] = result["dim_weight_lbs"]
    shipment["preliminary_billable_weight_lbs"] = result["billable_weight_lbs"]
    shipment["preliminary_basis"] = result["basis"]
    shipment["oversize_flag"] = result["oversize_flag"]
    shipment["additional_handling_flag"] = result["additional_handling_flag"]
    shipment["_oversize_basis"] = result["oversize_basis"]
    shipment["_additional_handling_basis"] = result["additional_handling_basis"]
    shipment["billable_weight_lbs"] = result["billable_weight_lbs"]
    return result


def apply_final_measurement(shipment, scan):
    """FINAL variant: reads the governing scan, re-deriving both flags."""
    result = calc.billable_weight(
        scan["scanned_length_in"], scan["scanned_width_in"],
        scan["scanned_height_in"], scan["scanned_weight_lbs"],
        shipment["divisor_used"], scan["non_conveyable_observed"],
    )
    shipment["scanned_cube_in3"] = result["cube_in3"]
    shipment["final_dim_weight_lbs"] = result["dim_weight_lbs"]
    shipment["final_billable_weight_lbs"] = result["billable_weight_lbs"]
    shipment["final_basis"] = result["basis"]
    shipment["oversize_flag"] = result["oversize_flag"]
    shipment["additional_handling_flag"] = result["additional_handling_flag"]
    shipment["_oversize_basis"] = result["oversize_basis"]
    shipment["_additional_handling_basis"] = result["additional_handling_basis"]
    shipment["billable_weight_lbs"] = result["billable_weight_lbs"]
    shipment["dim_variance_pct"] = scan["dim_variance_pct"]
    shipment["weight_variance_lbs"] = scan["weight_variance_lbs"]
    return result


def shipment_basis(shipment):
    """final_basis when a scan governs, else preliminary_basis."""
    if shipment.get("final_basis") is not None:
        return shipment["final_basis"]
    return shipment["preliminary_basis"]
