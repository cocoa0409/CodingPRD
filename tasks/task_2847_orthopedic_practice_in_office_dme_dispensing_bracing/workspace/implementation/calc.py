"""Derived-state recomputation, cascades and the seven pinned calculations."""
from decimal import Decimal

from common import dec, fail, now, round_half_up, today, whole_days
from store import db, find_par_level, sort_created, touch

DEC_085 = Decimal("0.85")
DEC_1 = Decimal("1")


# ------------------------------------------------- par posture / clinic posture

def critical_floor(par_min_qty):
    return (par_min_qty + 1) // 2


def posture_for(row):
    on_hand = row["on_hand_qty"]
    if on_hand <= 0:
        return "STOCKOUT"
    if on_hand < critical_floor(row["par_min_qty"]):
        return "CRITICAL"
    if on_hand < row["par_min_qty"]:
        return "BELOW_PAR"
    return "OK"


def apply_posture(par_level):
    """Recompute stock_posture in place; returns (old, new)."""
    old = par_level.get("stock_posture")
    new = posture_for(par_level)
    par_level["stock_posture"] = new
    return old, new


def clinic_posture_for(count):
    if count == 0:
        return "ACTIVE"
    if count == 1:
        return "RESTRICTED"
    return "SUSPENDED"


def set_clinic_holds(clinic, exclude_encounter_id=None):
    for row in sort_created(list(db["encounters"].values())):
        if row["clinic_id"] != clinic["id"]:
            continue
        if row["id"] == exclude_encounter_id:
            continue
        if row["clinical_status"] != "RESERVED":
            continue
        if row["compliance_hold"] and row["hold_reason"] == "CLINIC_SUSPENDED":
            continue
        row["compliance_hold"] = True
        row["hold_reason"] = "CLINIC_SUSPENDED"
        touch(row)


def clear_clinic_holds(clinic):
    for row in sort_created(list(db["encounters"].values())):
        if row["clinic_id"] != clinic["id"]:
            continue
        if row["compliance_hold"] and row["hold_reason"] == "CLINIC_SUSPENDED":
            row["compliance_hold"] = False
            row["hold_reason"] = None
            touch(row)


def recompute_clinic_posture(clinic, exclude_encounter_id=None):
    """Full recount of the clinic's shelves; cascades holds on status change."""
    count = 0
    for row in db["par_levels"].values():
        if row["clinic_id"] != clinic["id"]:
            continue
        if row["stock_posture"] == "STOCKOUT" and row["lifetime_received_qty"] > 0:
            count += 1
    old_status = clinic["dispensing_status"]
    new_status = clinic_posture_for(count)
    changed = (count != clinic["stockout_par_level_count"]) or (new_status != old_status)
    if not changed:
        return
    clinic["stockout_par_level_count"] = count
    clinic["dispensing_status"] = new_status
    touch(clinic)
    if new_status == "SUSPENDED" and old_status != "SUSPENDED":
        set_clinic_holds(clinic, exclude_encounter_id)
    elif old_status == "SUSPENDED" and new_status != "SUSPENDED":
        clear_clinic_holds(clinic)


def refresh_shelf(par_level, exclude_encounter_id=None):
    """Recompute a shelf's posture and, when STOCKOUT membership moved, the clinic."""
    old, new = apply_posture(par_level)
    if old != new and (old == "STOCKOUT" or new == "STOCKOUT"):
        clinic = db["clinics"].get(par_level["clinic_id"])
        if clinic is not None:
            recompute_clinic_posture(clinic, exclude_encounter_id)


# ------------------------------------------------------ same-or-similar lookback

def same_or_similar_lookback(encounter, product):
    """Returns (conflict, prior_encounter_id, prior_delivered_on, months)."""
    candidates = []
    for row in db["encounters"].values():
        if row["id"] == encounter["id"]:
            continue
        if row["patient_id"] != encounter["patient_id"]:
            continue
        if row["clinical_status"] != "DELIVERED":
            continue
        other = db["products"].get(row["product_id"])
        if other is None:
            continue
        if other["same_or_similar_group"] != product["same_or_similar_group"]:
            continue
        if row.get("delivered_at") is None:
            continue
        candidates.append(row)
    if not candidates:
        return False, None, None, None
    # greatest delivered_at wins; earliest created_at breaks a tie, never the id
    candidates.sort(key=lambda r: (r["created_at"], r["_seq"]))
    best = candidates[0]
    for row in candidates[1:]:
        if row["delivered_at"] > best["delivered_at"]:
            best = row
    prior = best["delivered_at"].date()
    clock = now()
    months = (clock.year - prior.year) * 12 + (clock.month - prior.month)
    if clock.day < prior.day:
        months -= 1
    conflict = months < product["reasonable_useful_lifetime_months"]
    return conflict, best["id"], prior, months


# ------------------------------------------------------------- ABN cash quote

def abn_cash_quote(encounter, product, reason, approved_units):
    quantity = encounter["quantity"]
    if reason == "UNITS_EXCEED_AUTH":
        quoted_units = quantity - (approved_units or 0)
    else:
        quoted_units = quantity
    if quoted_units < 0:
        quoted_units = 0
    cash = product["cash_price_cents"]
    if quoted_units >= 2:
        unit_net = round_half_up(dec(cash) * DEC_085)
    else:
        unit_net = cash
    subtotal = unit_net * quoted_units
    fee = 0 if subtotal >= 50000 else 2500
    return {
        "unit_net_price_cents": unit_net,
        "estimated_subtotal_cents": subtotal,
        "dispensing_fee_cents": fee,
        "estimated_cost_cents": subtotal + fee,
    }


# -------------------------------------------------- patient responsibility

def covered_units_for(encounter, product, verification, prior_auth):
    if verification is None or not verification["covered"]:
        return 0
    if product["requires_prior_auth"]:
        approved = 0
        if prior_auth is not None and prior_auth["approved_units"] is not None:
            approved = prior_auth["approved_units"]
        return min(encounter["quantity"], approved)
    return encounter["quantity"]


def patient_responsibility(encounter, product, verification, prior_auth, notice):
    quantity = encounter["quantity"]
    covered_units = covered_units_for(encounter, product, verification, prior_auth)
    excess = quantity - covered_units
    if covered_units == 0:
        estimated = notice["estimated_cost_cents"] if notice is not None else 0
        return {
            "covered_units": 0,
            "responsibility_variant": "ABN_CASH_SELFPAY",
            "patient_responsibility_cents": estimated,
            "billable_amount_cents": 0,
        }
    allowed_total = verification["allowed_amount_cents_snapshot"] * covered_units
    deductible_applied = min(verification["deductible_remaining_cents"], allowed_total)
    coinsurance_base = allowed_total - deductible_applied
    coinsurance = round_half_up(dec(coinsurance_base) * dec(verification["coinsurance_pct"]))
    cash = product["cash_price_cents"]
    if excess >= 2:
        excess_unit_net = round_half_up(dec(cash) * DEC_085)
    else:
        excess_unit_net = cash
    excess_cash = excess_unit_net * excess
    return {
        "covered_units": covered_units,
        "responsibility_variant": "INSURANCE_ASSIGNED",
        "patient_responsibility_cents": deductible_applied + coinsurance + excess_cash,
        "billable_amount_cents": allowed_total - deductible_applied - coinsurance,
    }


# --------------------------------------------------------------- return refund

RESTOCK_FEE_BASE = {
    "DEFECT": Decimal("0.00"),
    "WRONG_ITEM": Decimal("0.00"),
    "POOR_FIT": Decimal("0.10"),
    "PATIENT_REFUSED": Decimal("0.20"),
}


def restock_refund(product_return, encounter, product):
    condition = product_return["condition"]
    reason = product_return["reason"]
    days = product_return["days_since_delivery"]
    eligible = (
        condition == "SELLABLE"
        and product["category"] != "CUSTOM_FABRICATED"
        and days <= 30
    )
    pct = RESTOCK_FEE_BASE[reason]
    if not eligible and reason in ("POOR_FIT", "PATIENT_REFUSED"):
        pct = Decimal("0.25")
    charged = encounter["patient_responsibility_cents"] or 0
    device_component = round_half_up(dec(charged) * DEC_085)
    fitting_component = charged - device_component
    device_refund = round_half_up(dec(device_component) * (DEC_1 - pct))
    fitting_refund = round_half_up(dec(fitting_component) * (DEC_1 - pct * Decimal("0.5")))
    refund = device_refund + fitting_refund
    return {
        "restock_eligible": eligible,
        "restock_fee_pct": float(pct),
        "device_component_cents": device_component,
        "fitting_component_cents": fitting_component,
        "device_refund_cents": device_refund,
        "fitting_refund_cents": fitting_refund,
        "refund_cents": refund,
        "restock_fee_cents": charged - refund,
    }


# ------------------------------------------------------- supplier turnaround

def projected_score(first_delivery_days, promised):
    late = max(0, first_delivery_days - promised)
    return max(0, 100 - 4 * late)


def final_score(total_elapsed_days, promised, adjustment_rounds):
    late = max(0, total_elapsed_days - promised)
    return max(0, 100 - 4 * late - 6 * adjustment_rounds)


def refresh_supplier_rollup(supplier):
    accepted = [r for r in db["fab_orders"].values()
                if r["supplier_id"] == supplier["id"] and r["status"] == "ACCEPTED"]
    supplier["accepted_fab_order_count"] = len(accepted)
    if not accepted:
        supplier["turnaround_score"] = 100
    else:
        total = sum(r["final_turnaround_score"] or 0 for r in accepted)
        supplier["turnaround_score"] = round_half_up(dec(total) / dec(len(accepted)))
    touch(supplier)


# ---------------------------------------------------------- dispensing summary

def dispensing_summary(clinic):
    clinic_id = clinic["id"]
    shelves = [r for r in db["par_levels"].values() if r["clinic_id"] == clinic_id]
    units_received = sum(r["lifetime_received_qty"] for r in shelves)
    units_on_hand = sum(r["on_hand_qty"] for r in shelves)
    units_reserved = sum(r["reserved_qty"] for r in shelves)

    encounters = [r for r in db["encounters"].values() if r["clinic_id"] == clinic_id]
    units_dispensed = 0
    gross_charged = 0
    for row in encounters:
        product = db["products"].get(row["product_id"])
        countable = product is not None and product["category"] != "CUSTOM_FABRICATED"
        if countable and row["clinical_status"] in ("DELIVERED", "RETURN_PENDING", "RETURNED"):
            units_dispensed += row["quantity"]
        if row["financial_status"] in ("BILLED", "REFUNDED"):
            gross_charged += row["patient_responsibility_cents"] or 0

    encounter_ids = set(r["id"] for r in encounters)
    units_restocked = 0
    units_destroyed = 0
    refunded = 0
    restock_fee_retained = 0
    for row in db["returns"].values():
        if row["encounter_id"] not in encounter_ids:
            continue
        encounter = db["encounters"].get(row["encounter_id"])
        product = db["products"].get(encounter["product_id"]) if encounter else None
        countable = product is not None and product["category"] != "CUSTOM_FABRICATED"
        status = row["status"]
        if countable:
            if status == "RESTOCKED" or (status == "REFIT_ISSUED"
                                        and row["condition"] == "SELLABLE"):
                units_restocked += row["quantity_returned"]
            if status == "DESTROYED" or (status == "REFIT_ISSUED"
                                        and row["condition"] != "SELLABLE"):
                units_destroyed += row["quantity_returned"]
        if status in ("RESTOCKED", "DESTROYED", "REFIT_ISSUED"):
            refunded += row["refund_cents"] or 0
            restock_fee_retained += row["restock_fee_cents"] or 0

    return {
        "clinic_id": clinic_id,
        "dispensing_status": clinic["dispensing_status"],
        "stockout_par_level_count": clinic["stockout_par_level_count"],
        "units_received_total": units_received,
        "units_on_hand_total": units_on_hand,
        "units_reserved_total": units_reserved,
        "units_dispensed_total": units_dispensed,
        "units_restocked_total": units_restocked,
        "units_destroyed_total": units_destroyed,
        "units_accounted_total": units_on_hand + units_dispensed - units_restocked,
        "gross_charged_cents": gross_charged,
        "refunded_cents": refunded,
        "restock_fee_retained_cents": restock_fee_retained,
        "net_cash_position_cents": gross_charged - refunded,
    }
