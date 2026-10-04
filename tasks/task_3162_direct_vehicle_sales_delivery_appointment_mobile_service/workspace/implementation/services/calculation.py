"""Every calculation rule from scaffold section 1.3, in integer cents (PRD 2.8)."""

from datetime import timedelta

from db import (
    DB, CREATE_FEE, DOC_FEE_CENTS, DELIVERY_FEE_CENTS,
    MILEAGE_DEDUCTION_THRESHOLD_MILES, MILEAGE_DEDUCTION_CAP_CENTS,
    PER_MILE_DEDUCTION_CENTS, TRADE_IN_FLOOR_CENTS,
    MOBILE_BASE_TRAVEL_CENTS, INCLUDED_MILES, PER_MILE_TRAVEL_CENTS,
    LABOR_RATE_CENTS_PER_HOUR, WARRANTY_MILEAGE_CEILING,
    MAX_BUNDLE_DISCOUNT_CENTS, TIER_2_DISCOUNT_BPS, TIER_3_DISCOUNT_BPS,
)
from repository import find, serialize


def all_appraisals(order_id):
    return [a for a in DB.appraisals.values() if a["order_id"] == order_id]


def visible_appraisals(order_id):
    """PRD 3.3: an appraisal becomes visible to the order when its offer is
    published; before that the row is the specialist's private worksheet, and
    after a terminal exit there is no offer left on the order to resolve."""
    return [a for a in all_appraisals(order_id)
            if a["status"] in ("OFFERED", "ACCEPTED")]


def accepted_credit(order_id):
    return sum(a["net_credit_cents"] for a in all_appraisals(order_id)
               if a["status"] == "ACCEPTED")


# --------------------------------------------------------------------------
# order_total_due_cents — dual variant
# --------------------------------------------------------------------------

def order_total_due_cents(order):
    # PRD 3.7: the core is the ordered trim's base price plus the sum of
    # price_cents over the ORDER'S chosen options whose is_software_entitlement
    # is false — the trim's own configured_price_cents counts every option the
    # trim offers, including ones this order never attached.
    configuration = find("configuration", order["configuration_id"])
    base = configuration["base_price_cents"] if configuration else 0
    chosen = [DB.options[o] for o in DB.order_options.get(order["id"], [])
              if o in DB.options]
    core = base + sum(o["price_cents"] for o in chosen
                      if not o["is_software_entitlement"])
    order_fee = order["order_fee_cents"]
    deadline = order.get("configuration_lock_deadline")
    late_fee = order_fee if (deadline is not None and DB.now > deadline) else 0
    jurisdiction = find("jurisdiction", order["jurisdiction_id"])
    cap = jurisdiction["doc_fee_cap_cents"] if jurisdiction else 0
    doc_fee = min(DOC_FEE_CENTS, cap)
    total = core + order_fee + late_fee + doc_fee + DELIVERY_FEE_CENTS
    if order["status"] == "DELIVERED":
        # The delivery fee is added before the trade-in credit is subtracted.
        total -= min(DELIVERY_FEE_CENTS, accepted_credit(order["id"]))
    return total


def recompute_total(order):
    order["order_total_due_cents"] = order_total_due_cents(order)


# --------------------------------------------------------------------------
# delivery_readiness_posture — constraint propagation, first matching clause wins
# --------------------------------------------------------------------------

def allocation_unit_for(order):
    for unit in DB.units.values():
        if unit["order_id"] == order["id"]:
            return unit
    return None


def has_open_blocking_note(order_id):
    for note in DB.notes.values():
        if note["order_id"] == order_id and note["status"] == "OPEN" and note["blocked_handover"]:
            return True
    return False


def delivery_readiness_posture(order):
    if order["status"] == "CANCELLED":
        return "FROZEN"
    unit = allocation_unit_for(order)
    if unit is None or unit["status"] != "ARRIVED":
        return "FROZEN"
    if has_open_blocking_note(order["id"]):
        return "FROZEN"
    if order["order_fee_paid_cents"] < order["order_total_due_cents"]:
        return "RESTRICTED"
    return "READY"


def recompute_posture(order):
    recompute_total(order)
    order["delivery_readiness_posture"] = delivery_readiness_posture(order)


# --------------------------------------------------------------------------
# delivery_estimate_window
# --------------------------------------------------------------------------

def transport_eta_for(unit, order):
    jurisdiction = find("jurisdiction", order["jurisdiction_id"])
    lead = jurisdiction["transport_lead_days"] if jurisdiction else 7
    batch = find("batch", unit["batch_id"])
    basis = batch["planned_completion_at"] if batch else DB.now
    return basis + timedelta(days=lead)


def estimate_basis(order):
    """(basis, buffer_days) for the next projected window."""
    unit = allocation_unit_for(order)
    if unit is not None and unit["status"] == "ALLOCATED":
        return unit["transport_eta"], 7
    jurisdiction = find("jurisdiction", order["jurisdiction_id"])
    lead = jurisdiction["transport_lead_days"] if jurisdiction else 7
    return DB.now + timedelta(days=lead), 5


def shift_days_for(new_start, prior, prior_window_was_expired=False):
    """PRD 3.4: the number of whole days, rounded down, by which the new window
    start moved past the prior estimate's window end, floored at 0.

    A prior window that is no longer a live promise — one that has already
    passed, or one that a booking consumed — is a window the customer has been
    moved off, so the measurement is taken from where that window *started*.
    """
    if prior is None:
        return 0
    anchor = prior["window_start"] if prior_window_was_expired else prior["window_end"]
    delta = new_start - anchor
    return max(0, delta.days)


def current_estimate(order_id):
    live = [e for e in DB.estimates.values()
            if e["order_id"] == order_id and e["estimate_state"] in ("PROVISIONAL", "FIRM")]
    if not live:
        return None
    live.sort(key=lambda e: e["created_at"])
    return live[-1]


def latest_estimate(order_id):
    """The newest row of the chain, whatever envelope state it has reached."""
    rows = [e for e in DB.estimates.values() if e["order_id"] == order_id]
    if not rows:
        return None
    rows.sort(key=lambda e: e["created_at"])
    return rows[-1]


# --------------------------------------------------------------------------
# trade_in_net_credit_cents — threshold
# --------------------------------------------------------------------------

def trade_in_net_credit_cents(gross_offer_cents, reconditioning_estimate_cents, mileage):
    raw = gross_offer_cents - reconditioning_estimate_cents
    excess = mileage - MILEAGE_DEDUCTION_THRESHOLD_MILES
    mileage_deduction = min(MILEAGE_DEDUCTION_CAP_CENTS, excess * PER_MILE_DEDUCTION_CENTS)
    if mileage_deduction < 0:
        mileage_deduction = 0
    return max(TRADE_IN_FLOOR_CENTS, raw - mileage_deduction)


# --------------------------------------------------------------------------
# financing_monthly_payment_cents — tiered pricing
# --------------------------------------------------------------------------

def apr_bps_for(credit_band, term_months):
    if credit_band == "PRIME":
        return 490 if term_months <= 48 else 590
    if credit_band == "NEAR_PRIME":
        return 790 if term_months <= 48 else 890
    return 1290


def applied_trade_in_credit(application):
    if not application["include_trade_in_credit"]:
        return 0
    return accepted_credit(application["order_id"])


def amount_financed_cents(application, order):
    total = order["order_total_due_cents"]
    return max(0, total - application["down_payment_cents"]
               - applied_trade_in_credit(application))


def monthly_payment_cents(amount, apr_bps, term_months):
    if amount <= 0:
        return 0
    monthly_rate = (apr_bps / 10000.0) / 12.0
    if monthly_rate == 0:
        return int(round(amount / term_months))
    factor = (1.0 + monthly_rate) ** (-term_months)
    from errors import round_half_up
    return round_half_up(amount * monthly_rate / (1.0 - factor))


def pricing_for(application, order, credit_band):
    bps = apr_bps_for(credit_band, application["term_months"])
    principal = amount_financed_cents(application, order)
    return bps, principal, monthly_payment_cents(principal, bps, application["term_months"])


# --------------------------------------------------------------------------
# entitlement_bundle_price_cents — weighted scoring
# --------------------------------------------------------------------------

def active_entitlement_count(vehicle_id):
    return sum(1 for e in DB.entitlements.values()
               if e["vehicle_id"] == vehicle_id and e["status"] == "ACTIVE")


def entitlement_bundle_price_cents(vehicle_id, price_entries):
    existing = active_entitlement_count(vehicle_id)
    if existing <= 1:
        tier_bps = 0
    elif existing <= 3:
        tier_bps = TIER_2_DISCOUNT_BPS
    else:
        tier_bps = TIER_3_DISCOUNT_BPS
    raw_total = sum(price_entries)
    if raw_total <= 0:
        return 0, 0, [0 for _ in price_entries]
    gross_discount = raw_total * tier_bps // 10000
    applied_discount = min(MAX_BUNDLE_DISCOUNT_CENTS, gross_discount)
    bundle_discount_bps = applied_discount * 10000 // raw_total
    bundle_net = raw_total - applied_discount
    shares = []
    running = 0
    for price in price_entries:
        amount = bundle_net * price // raw_total
        whole_dollar = (amount // 100) * 100
        shares.append(whole_dollar)
        running += whole_dollar
    shares[-1] += bundle_net - running
    return bundle_discount_bps, bundle_net, shares


# --------------------------------------------------------------------------
# mobile_service_visit_cost_cents — aggregation
# --------------------------------------------------------------------------

def mobile_service_visit_cost_cents(visit):
    mileage = visit.get("visit_miles") or 0
    excess = max(0, mileage - INCLUDED_MILES)
    # PRD 3.10: "the platform's base travel charge is currently 0, so in the present
    # configuration the travel line is exactly the per-mile charge on the excess miles."
    travel = MOBILE_BASE_TRAVEL_CENTS + excess * PER_MILE_TRAVEL_CENTS
    from errors import round_half_up
    labor = round_half_up(visit["labor_hours"] * LABOR_RATE_CENTS_PER_HOUR)
    return travel + labor + visit["parts_cost_cents"]


def warranty_covers(severity, odometer_miles):
    return severity in ("HIGH", "CRITICAL") and odometer_miles <= WARRANTY_MILEAGE_CEILING


# --------------------------------------------------------------------------
# service_triage_outcome — ordered cascade, first matching clause wins
# --------------------------------------------------------------------------

def service_triage_outcome(vehicle_id, fault_code, severity, is_driveable,
                           mobile_service_permitted):
    priors = [r for r in DB.reports.values() if r["vehicle_id"] == vehicle_id]
    priors.sort(key=lambda r: r["created_at"])
    if severity == "LOW" and priors:
        if priors[-1]["fault_code"] == fault_code:
            return "NO_ACTION", False
    if not mobile_service_permitted and severity in ("LOW", "MEDIUM") and is_driveable:
        return "OTA_RESOLVABLE", False
    if severity in ("HIGH", "CRITICAL") or not is_driveable:
        outcome = "CENTER_REQUIRED"
    else:
        outcome = "MOBILE_REQUIRED"
    parts_required = (outcome in ("MOBILE_REQUIRED", "CENTER_REQUIRED")
                      and severity in ("MEDIUM", "HIGH", "CRITICAL"))
    return outcome, parts_required


# --------------------------------------------------------------------------
# batch_delay_propagation ordering
# --------------------------------------------------------------------------

def orders_for_batch_delay(batch_id):
    affected = []
    for unit in DB.units.values():
        if unit["batch_id"] != batch_id:
            continue
        if unit["status"] not in ("ALLOCATED", "IN_TRANSIT", "ARRIVED"):
            continue
        order = find("order", unit["order_id"])
        if order is not None:
            affected.append(order)
    affected.sort(key=lambda o: (o.get("placed_at") or "", o["created_at"]))
    return affected