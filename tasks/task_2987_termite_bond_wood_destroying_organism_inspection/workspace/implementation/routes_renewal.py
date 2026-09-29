"""Renewal invoices: repricing, payment and the bond term roll-forward (PRD 3.8)."""

from flask import Blueprint

import calc
import validate as v
from auth import authenticate
from clock import clock
from common import (apply_filters, get_bond, get_inspection, get_inspector,
                    get_property, get_renewal, require_graphed,
                    require_license_active, require_license_unexpired,
                    require_purpose)
from envelope import listing, ok
from errors import ApiError, invalid_state
from ledger import past_due_days, renewal_window_open, roll_term_forward
from serialize import renewal_out
from store import by_created, db, touch

bp = Blueprint("renewal", __name__)

READERS = ("ComplianceOfficer", "BranchManager", "PropertyOwner")


@bp.get("/bond-renewals/<rid>")
def read_renewal(rid):
    authenticate(READERS)
    return ok(renewal_out(get_renewal(rid)))


@bp.get("/bond-renewals")
def list_renewals():
    authenticate(READERS)
    rows = apply_filters(by_created(list(db.renewals.values())), {
        "bond_id": v.query_str("bond_id"),
        "inspection_id": v.query_str("inspection_id"),
        "status": v.query_str("status"),
    })
    return listing(rows, renewal_out)


@bp.post("/bond-renewals/<rid>/complete")
def complete_renewal(rid):
    authenticate(("BranchManager",))
    renewal = get_renewal(rid)
    payload = v.body()
    inspection_id = v.get_string(payload, "inspection_id")
    amount = v.get_money(payload, "amount_usd", maximum="9999999.99")

    inspection = get_inspection(inspection_id)
    bond = get_bond(renewal["bond_id"])

    if renewal["status"] != "PENDING":
        raise ApiError("ERR_INVALID_RENEWAL_STATE", 409,
                       "only a PENDING invoice may be completed")
    if bond["status"] != "ACTIVE":
        raise invalid_state("Bond", "the bond is not ACTIVE")

    # Compliance outranks money: the signing inspector's licence is examined
    # before the graph itself and long before the payment (PRD 3.8).
    signer = get_inspector(inspection["inspector_id"])
    require_license_active(signer)
    require_license_unexpired(signer)

    require_graphed(inspection)
    require_purpose(inspection, "RENEWAL")
    if inspection["property_id"] != bond["property_id"]:
        raise ApiError("ERR_PROPERTY_MISMATCH", 422,
                       "the renewal graph belongs to another structure")

    if not renewal_window_open(bond):
        raise ApiError("ERR_RENEWAL_WINDOW_NOT_OPEN", 409,
                       "the clock date is outside the bond's renewal window")

    prop = get_property(bond["property_id"])
    c1, c2, c3, c4, total = calc.renewal_components(
        bond["annual_premium_usd"], prop["square_footage"],
        inspection["conducive_condition_count"], past_due_days(bond))
    if amount < total:
        raise ApiError("ERR_PAYMENT_INSUFFICIENT", 402,
                       "amount_usd is less than the repriced total of %s" % total)

    renewal["inspection_id"] = inspection["id"]
    renewal["base_renewal_fee_usd"] = c1
    renewal["inspection_fee_usd"] = c2
    renewal["conducive_surcharge_usd"] = c3
    renewal["late_fee_usd"] = c4
    renewal["invoice_total_usd"] = total
    renewal["status"] = "PAID"
    renewal["paid_at"] = clock.now()
    renewal["amount_paid_usd"] = calc.r2(amount)
    touch(renewal)

    roll_term_forward(bond)
    if inspection["active_infestation_found"]:
        bond["retreat_required"] = True
    touch(bond)

    return ok(renewal_out(renewal))
