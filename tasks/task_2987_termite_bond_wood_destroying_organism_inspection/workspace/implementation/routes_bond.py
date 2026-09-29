"""Underwriting, the term calendar, lapse, reinstatement and renewal invoices
(PRD 3.7, 3.8)."""

from flask import Blueprint

import calc
import validate as v
from auth import authenticate
from clock import clock, days_between, plus_days
from common import (apply_filters, get_bond, get_inspection, get_plan,
                    get_property, require_graphed, require_purpose)
from envelope import created, listing, ok
from errors import ApiError, invalid_state
from ledger import (bond_of_record, lapse_bond, recompute_property_ledger,
                    renewal_window_open, set_term_windows, terminate_bond)
from serialize import bond_out, renewal_out
from store import by_created, db, new_row, renewals_of, touch

bp = Blueprint("bond", __name__)

READERS = ("ComplianceOfficer", "BranchManager", "ClaimsAdjudicator",
           "FieldInspector", "PropertyOwner")
RENEWAL_READERS = ("ComplianceOfficer", "BranchManager", "PropertyOwner")


# --------------------------------------------------------------------------
# issuance
# --------------------------------------------------------------------------

@bp.post("/bonds")
def create_bond():
    user_id, _role = authenticate(("BranchManager",))
    payload = v.body()

    property_id = v.get_string(payload, "property_id")
    plan_id = v.get_string(payload, "treatment_plan_id")
    tier = v.get_enum(payload, "coverage_tier", calc.COVERAGE_TIERS)
    waivers = v.get_enum_array(payload, "conducive_waiver_codes",
                              calc.CONDUCIVE_CODES_NO_NONE, required=False,
                              default=[])

    prop = get_property(property_id)
    plan = get_plan(plan_id)
    inspection = get_inspection(plan["inspection_id"])

    # Stage 20, in the in-stage order PRD 2.6 fixes.
    require_graphed(inspection)
    require_purpose(inspection, "INITIAL")
    if plan["status"] != "COMPLETED":
        raise ApiError("ERR_PLAN_NOT_COMPLETED", 409,
                       "plan %s is %s, not COMPLETED" % (plan["id"], plan["status"]))
    if plan["property_id"] != prop["id"]:
        raise ApiError("ERR_PROPERTY_MISMATCH", 422,
                       "the bonded plan belongs to another structure")

    # Stage 21.
    if bond_of_record(prop["id"]) is not None:
        raise ApiError("ERR_DUPLICATE_ACTIVE_BOND", 409,
                       "the structure already carries an ACTIVE or LAPSED bond")

    base_premium, cap, annual = calc.bond_premium_and_cap(plan["quoted_price_usd"], tier)
    today = clock.today()
    row = new_row({
        "property_id": prop["id"],
        "treatment_plan_id": plan["id"],
        "coverage_tier": tier,
        "conducive_waiver_codes": list(waivers),
        "issued_by_user_id": user_id,
        "status": "ACTIVE",
        "issued_on": today,
        "current_term_start": today,
        "current_term_end": plus_days(today, calc.TERM_DAYS),
        "renewal_window_opens_on": None,
        "term_index": 1,
        "lapse_date": None,
        "reinstatement_count": 0,
        "base_premium_usd": base_premium,
        "repair_liability_cap_usd": cap,
        "annual_premium_usd": annual,
        "claims_paid_to_date_usd": calc.ZERO,
        "reserved_claim_amount_usd": calc.ZERO,
        "remaining_repair_cap_usd": cap,
        "retreat_credit_count": 0,
        "retreat_required": False,
        "coverage_watch": False,
    })
    set_term_windows(row, today, plus_days(today, calc.TERM_DAYS))
    db.bonds[row["id"]] = row

    recompute_property_ledger(prop)
    return created(bond_out(row))


@bp.get("/bonds/<bid>")
def read_bond(bid):
    authenticate(READERS)
    return ok(bond_out(get_bond(bid)))


@bp.get("/bonds")
def list_bonds():
    authenticate(READERS)
    rows = apply_filters(by_created(list(db.bonds.values())), {
        "property_id": v.query_str("property_id"),
        "treatment_plan_id": v.query_str("treatment_plan_id"),
        "status": v.query_str("status"),
        "coverage_tier": v.query_str("coverage_tier"),
    })
    return listing(rows, bond_out)


# --------------------------------------------------------------------------
# compliance sweep: lapse and termination
# --------------------------------------------------------------------------

@bp.post("/bonds/<bid>/term-review")
def term_review(bid):
    authenticate(("ComplianceOfficer",))
    bond = get_bond(bid)
    today = clock.today()

    if bond["status"] == "ACTIVE":
        if today > plus_days(bond["current_term_end"], calc.GRACE_DAYS):
            lapse_bond(bond)
            return ok(bond_out(bond))
    elif bond["status"] == "LAPSED":
        if bond["lapse_date"] is not None and today > plus_days(
                bond["lapse_date"], calc.REINSTATEMENT_WINDOW_DAYS):
            terminate_bond(bond)
            return ok(bond_out(bond))

    raise invalid_state("Bond", "no deadline has passed for bond %s" % bond["id"])


# --------------------------------------------------------------------------
# reinstatement
# --------------------------------------------------------------------------

@bp.post("/bonds/<bid>/reinstate")
def reinstate(bid):
    authenticate(("BranchManager",))
    bond = get_bond(bid)
    payload = v.body()
    inspection_id = v.get_string(payload, "reinstatement_inspection_id")
    amount = v.get_money(payload, "amount_usd", maximum="9999999.99")

    inspection = get_inspection(inspection_id)

    if bond["status"] != "LAPSED":
        raise invalid_state("Bond", "only a LAPSED bond may be reinstated")

    require_graphed(inspection)
    require_purpose(inspection, "REINSTATEMENT")
    if inspection["property_id"] != bond["property_id"]:
        raise ApiError("ERR_PROPERTY_MISMATCH", 422,
                       "the reinstatement graph belongs to another structure")

    today = clock.today()
    if today > plus_days(bond["lapse_date"], calc.REINSTATEMENT_WINDOW_DAYS):
        raise ApiError("ERR_REINSTATEMENT_WINDOW_EXPIRED", 409,
                       "the 90-day reinstatement window has closed")
    earliest_signature = plus_days(clock.now(),
                                   -calc.REINSTATEMENT_INSPECTION_MAX_AGE_DAYS)
    if inspection["graph_completed_at"] < earliest_signature:
        raise ApiError("ERR_REINSTATEMENT_INSPECTION_STALE", 422,
                       "the reinstatement graph was signed more than 30 days ago")
    if inspection["active_infestation_found"]:
        raise ApiError("ERR_REINSTATEMENT_INSPECTION_STALE", 422,
                       "a graph showing live activity cannot support reinstatement")

    lapse_days = max(0, days_between(bond["lapse_date"], today))
    variant, _premium_charge, owed = calc.reinstatement_settlement(
        bond["annual_premium_usd"], lapse_days)
    if amount < owed:
        raise ApiError("ERR_REINSTATEMENT_PAYMENT_INSUFFICIENT", 402,
                       "amount_usd is less than the settlement of %s" % owed)

    if variant == "PRORATED_REMAINDER":
        term_start = bond["lapse_date"]
        term_end = plus_days(bond["current_term_end"], calc.TERM_DAYS)
    else:
        term_start = today
        term_end = plus_days(today, calc.TERM_DAYS)

    bond["status"] = "ACTIVE"
    bond["lapse_date"] = None
    bond["reinstatement_count"] = bond["reinstatement_count"] + 1
    bond["term_index"] = bond["term_index"] + 1
    set_term_windows(bond, term_start, term_end)
    touch(bond)
    return ok(bond_out(bond))


# --------------------------------------------------------------------------
# renewal invoices
# --------------------------------------------------------------------------

@bp.post("/bonds/<bid>/renewals")
def open_renewal(bid):
    authenticate(("BranchManager",))
    bond = get_bond(bid)

    if bond["status"] != "ACTIVE":
        raise invalid_state("Bond", "only an ACTIVE bond may be renewed")
    for other in renewals_of(bond["id"]):
        if other["status"] == "PENDING":
            raise ApiError("ERR_RENEWAL_ALREADY_PENDING", 409,
                           "an invoice is already PENDING on this bond")
    if not renewal_window_open(bond):
        raise ApiError("ERR_RENEWAL_WINDOW_NOT_OPEN", 409,
                       "the clock date is outside the bond's renewal window")

    prop = get_property(bond["property_id"])
    c1, c2, c3, c4, total = calc.renewal_components(
        bond["annual_premium_usd"], prop["square_footage"], 0, 0)
    row = new_row({
        "bond_id": bond["id"],
        "inspection_id": None,
        "term_index": bond["term_index"],
        "status": "PENDING",
        "due_on": bond["current_term_end"],
        "base_renewal_fee_usd": c1,
        "inspection_fee_usd": c2,
        "conducive_surcharge_usd": c3,
        "late_fee_usd": c4,
        "invoice_total_usd": total,
        "paid_at": None,
        "amount_paid_usd": calc.ZERO,
    })
    db.renewals[row["id"]] = row
    return created(renewal_out(row))


@bp.get("/bonds/<bid>/renewals")
def list_bond_renewals(bid):
    authenticate(RENEWAL_READERS)
    bond = get_bond(bid)
    rows = apply_filters(renewals_of(bond["id"]), {"status": v.query_str("status")})
    return listing(rows, renewal_out)
