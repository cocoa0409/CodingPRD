"""Cascades and shared state-transition side effects (PRD 2.9, 3.2, 3.5-3.9)."""
import calc
import clock
import ledger
from store import db, touch

SUSPENDABLE_BENEFITS = ("RENTERS_INSURANCE", "AIR_QUALITY_GUARANTEE")
FORFEITABLE_BENEFITS = ("DAMAGE_WAIVER", "AIR_QUALITY_GUARANTEE")


# --------------------------------------------------------------------------
# shipment-side effects driven by the subscription
# --------------------------------------------------------------------------
def cancel_scheduled_shipments(sub):
    for sh in calc.shipments_of(sub["id"]):
        if sh["status"] == "SCHEDULED":
            sh["status"] = "CANCELLED"
            touch(sh)


def recall_in_flight_shipments(sub):
    for sh in calc.shipments_of(sub["id"]):
        if sh["status"] in ("SHIPPED", "DELIVERED"):
            sh["status"] = "RETURN_REQUESTED"
            touch(sh)


# --------------------------------------------------------------------------
# entitlement-side effects
# --------------------------------------------------------------------------
def activate_entitlements(sub):
    stamp = clock.now_iso()
    for row in calc.entitlements_of(sub["id"]):
        if row["state"] == "PENDING":
            row["state"] = "ACTIVE"
            row["effective_from"] = stamp
            touch(row)


def suspend_entitlements(sub):
    for row in calc.entitlements_of(sub["id"]):
        if row["state"] == "ACTIVE" and row["benefit_code"] in SUSPENDABLE_BENEFITS:
            row["state"] = "SUSPENDED"
            row["suspended_by_property_event"] = True
            touch(row)


def restore_entitlements(sub):
    for row in calc.entitlements_of(sub["id"]):
        if row["state"] == "SUSPENDED" and row["suspended_by_property_event"]:
            row["state"] = "ACTIVE"
            row["suspended_by_property_event"] = False
            touch(row)


def expire_entitlements(sub, reason, states=("PENDING", "ACTIVE", "SUSPENDED")):
    stamp = clock.now_iso()
    for row in calc.entitlements_of(sub["id"]):
        if row["state"] in states:
            row["state"] = "EXPIRED"
            row["terminated_at"] = stamp
            row["forfeit_reason"] = reason
            touch(row)


# --------------------------------------------------------------------------
# occupancy bookkeeping (PRD 3.2 / 3.9)
# --------------------------------------------------------------------------
def _unit_has_live_subscription(unit_id):
    return any(s["status"] in calc.LIVE_SUBSCRIPTION_STATUSES
               for s in calc.subscriptions_of_unit(unit_id))


def occupy_unit(unit_id):
    unit = db.units.get(unit_id)
    if unit is not None and unit["status"] == "AVAILABLE":
        unit["status"] = "OCCUPIED"
        touch(unit)


def release_unit_if_free(unit_id):
    unit = db.units.get(unit_id)
    if unit is None or unit["status"] != "OCCUPIED":
        return
    if not _unit_has_live_subscription(unit_id):
        unit["status"] = "AVAILABLE"
        touch(unit)


def start_residency(resident_id):
    resident = db.residents.get(resident_id)
    if resident is not None and resident["status"] == "PROSPECT":
        resident["status"] = "RESIDING"
        touch(resident)


def end_residency_if_free(resident_id):
    resident = db.residents.get(resident_id)
    if resident is None or resident["status"] != "RESIDING":
        return
    live = any(s["status"] in calc.LIVE_SUBSCRIPTION_STATUSES
               for s in db.subscriptions.values()
               if s["resident_id"] == resident_id)
    if not live:
        resident["status"] = "MOVED_OUT"
        touch(resident)


# --------------------------------------------------------------------------
# cascade B: property suspension / reactivation
# --------------------------------------------------------------------------
def suspend_property_cascade(prop):
    for sub in calc.subscriptions_of_property(prop["id"]):
        if sub["status"] != "ACTIVE":
            continue
        sub["status"] = "SUSPENDED"
        touch(sub)
        cancel_scheduled_shipments(sub)
        suspend_entitlements(sub)


def reactivate_property_cascade(prop):
    for sub in calc.subscriptions_of_property(prop["id"]):
        if sub["status"] != "SUSPENDED":
            continue
        sub["status"] = "ACTIVE"
        touch(sub)
        restore_entitlements(sub)


# --------------------------------------------------------------------------
# cascade A: confirmed non-installation
# --------------------------------------------------------------------------
def confirm_non_install_cascade(sub):
    """Forfeits the two riders, posts one WAIVER_REVERSAL credit per forfeited
    row in ascending benefit_code order, then re-derives the benefit set and the
    monthly fee from the surviving codes."""
    stamp = clock.now_iso()
    rows = [row for row in calc.entitlements_of(sub["id"])
            if row["state"] in ("ACTIVE", "SUSPENDED")
            and row["benefit_code"] in FORFEITABLE_BENEFITS]
    rows.sort(key=lambda r: r["benefit_code"])
    for row in rows:
        was_suspended = row["state"] == "SUSPENDED"
        row["state"] = "FORFEITED"
        row["forfeit_reason"] = "NON_INSTALL_CONFIRMED"
        row["terminated_at"] = stamp
        if was_suspended:
            row["suspended_by_property_event"] = False
        touch(row)

    today = clock.today()
    for row in rows:
        credit = calc.waiver_reversal_credit(row["benefit_code"], today)
        ledger.post_one_off(sub, "WAIVER_REVERSAL", -credit,
                            "waiver reversal %s" % row["benefit_code"], row["id"],
                            on_date=today)

    prop = db.properties[sub["property_id"]]
    sub["installation_posture"] = "NON_INSTALL_CONFIRMED"
    sub["entitled_benefit_codes"] = calc.benefit_codes(
        prop, sub["billing_party"], "NON_INSTALL_CONFIRMED")
    sub["monthly_fee_cents"] = calc.recompute_fee(sub)
    touch(sub)


# --------------------------------------------------------------------------
# cancellation (PRD 3.9) — settlement is computed before any shipment moves
# --------------------------------------------------------------------------
def void_subscription(sub, effective_date, cancel_reason):
    sub["status"] = "VOIDED"
    sub["cancel_effective_date"] = clock.fmt_date(effective_date)
    sub["cancel_reason"] = cancel_reason
    touch(sub)
    cancel_scheduled_shipments(sub)
    expire_entitlements(sub, "SUBSCRIPTION_VOIDED", states=("PENDING",))


def settle_and_cancel_subscription(sub, effective_date, cancel_reason):
    settlement = calc.cancellation_settlement(sub, effective_date)
    sub["gross_prorated_credit_cents"] = settlement["gross_prorated_credit_cents"]
    # PRD 3.9 names exactly one representation for waiver_credit_pct: "a decimal
    # string, one of 0.00, 0.25, 0.50 or 0.75".
    sub["waiver_credit_pct"] = calc.pct_string(settlement["waiver_credit_pct"])
    sub["unreturned_fee_gross_cents"] = settlement["unreturned_fee_gross_cents"]
    sub["unreturned_fee_net_cents"] = settlement["unreturned_fee_net_cents"]
    sub["net_settlement_cents"] = settlement["net_settlement_cents"]
    sub["status"] = "CANCELLED"
    sub["cancel_effective_date"] = clock.fmt_date(effective_date)
    sub["cancel_reason"] = cancel_reason
    touch(sub)

    cancel_scheduled_shipments(sub)
    recall_in_flight_shipments(sub)
    expire_entitlements(sub, "SUBSCRIPTION_CANCELLED")

    ledger.post(sub, "PRORATION_CREDIT",
                -settlement["gross_prorated_credit_cents"],
                settlement["period_start"], settlement["period_end"],
                "cancellation prorated credit", sub["id"])
    if settlement["unreturned_fee_net_cents"] > 0:
        ledger.post_one_off(sub, "UNRETURNED_SHIPMENT_FEE",
                            settlement["unreturned_fee_net_cents"],
                            "cancellation unreturned reconciliation", sub["id"])

    end_residency_if_free(sub["resident_id"])
    release_unit_if_free(sub["unit_id"])
    return settlement
