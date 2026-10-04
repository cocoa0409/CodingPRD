"""resolve_replacement_model and the ReplacementOrder lifecycle helpers.

RMA dispatch reads the replaced unit's own model_code; campaign activation
resolves the lot's model for the whole batch (PRD 3.7).
"""

import db
from errors import fail
from respond import iso, new_id, now_iso

from services import common


def classify(replaced_model, replacement_model):
    """Derive the compatibility class from the replaced unit's generation."""
    if replacement_model is None:
        return "INCOMPATIBLE"
    if replaced_model == replacement_model:
        return "IDENTICAL"
    if replaced_model in common.GEN1_MODELS and replacement_model in common.GEN2_MODELS:
        return "COMPATIBLE_UPGRADE"
    if replaced_model in common.GEN2_MODELS and replacement_model in common.GEN2_MODELS:
        return "COMPATIBLE_UPGRADE"
    return "INCOMPATIBLE"


def resolve_replacement_model(unit, lot):
    """The unit-informed resolution used by RMA dispatch.

    A GEN1 unit under a lot shipping IQ7 is forcibly promoted to IQ8; a
    candidate of None means no supported replacement exists.
    """
    candidate = lot.get("replacement_model_code") if lot else None
    model = unit.get("model_code")

    if model in common.GEN1_MODELS:
        if candidate == "IQ7" and model == "IQ7":
            compatibility_class = "IDENTICAL"
        else:
            if candidate == "IQ7":
                candidate = "IQ8"
            compatibility_class = "COMPATIBLE_UPGRADE"
    elif model == "IQ8":
        if candidate == "IQ8":
            compatibility_class = "IDENTICAL"
        else:
            compatibility_class = "COMPATIBLE_UPGRADE"
    else:
        compatibility_class = classify(model, candidate)

    if candidate is None:
        fail("ERR_NO_SUPPORTED_REPLACEMENT")
    return candidate, compatibility_class


def lot_only_model(lot):
    """The lot-only projection shown on a campaign preview."""
    return lot.get("replacement_model_code") if lot else None


def new_order(unit, model, compatibility_class, status, claim_id=None,
              campaign_id=None, dispatched_at=None, installed_serials=None):
    order = {
        "id": new_id(),
        "created_at": now_iso(),
        "claim_id": claim_id,
        "campaign_id": campaign_id,
        "unit_id": unit["id"],
        "replacement_model_code": model,
        "compatibility_class": compatibility_class,
        "status": status,
        "dispatched_at": dispatched_at,
        "installed_at": None,
        "installed_serials": list(installed_serials or []),
    }
    db.DB.replacement_orders[order["id"]] = order
    common.recompute_unit(unit)
    return order


def require_chargeable(unit_id, claim_id, campaign_id, allow_sourceless=False):
    """An order may carry at most one source, and a unit may not be double-shipped.

    A manual order is created "optionally" attached to a claim, and the order
    that is not attached to a claim is the goodwill path, so a sourceless manual
    order is admitted; an order carrying both sources never is.
    """
    if claim_id is not None and campaign_id is not None:
        fail("ERR_ORDER_NOT_CHARGEABLE",
             "an order may carry only one of claim_id / campaign_id")
    if claim_id is None and campaign_id is None and not allow_sourceless:
        fail("ERR_ORDER_NOT_CHARGEABLE",
             "an order must carry a claim_id or a campaign_id")

    for existing in db.live_orders_of_unit(unit_id):
        if existing.get("claim_id") == claim_id and existing.get("campaign_id") == campaign_id:
            fail("ERR_ORDER_NOT_CHARGEABLE",
                 "a live replacement order already exists for this unit")
        if claim_id is not None and existing.get("claim_id") == claim_id:
            fail("ERR_ORDER_NOT_CHARGEABLE",
                 "a live replacement order already exists for this unit")
        if campaign_id is not None and existing.get("campaign_id") == campaign_id:
            fail("ERR_ORDER_NOT_CHARGEABLE",
                 "a live replacement order already exists for this unit")


def serials_on_system(system_id):
    """Every serial number currently present on a system, whether original or
    installed as a replacement."""
    present = set()
    for unit in db.all_units_of_system(system_id):
        if unit.get("commissioning_state") == "DECOMMISSIONED":
            continue
        if unit.get("serial_number"):
            present.add(unit["serial_number"])
    for order in db.DB.replacement_orders.values():
        if order.get("status") != "INSTALLED":
            continue
        if order.get("unit_id") is None:
            continue
        target = db.DB.units.get(order["unit_id"])
        if target is None or target.get("system_id") != system_id:
            continue
        for serial in order.get("installed_serials") or []:
            present.add(serial)
    return present


def install_order(order, replacement_serial_number, installed_at_dt):
    """DISPATCHED -> INSTALLED and everything that cascades from it (PRD 3.7)."""
    unit = db.DB.units.get(order.get("unit_id"))
    if unit is None:
        fail("ERR_RESOURCE_NOT_FOUND", "the order's unit no longer exists")

    system = db.DB.systems.get(unit.get("system_id"))

    order["status"] = "INSTALLED"
    order["installed_at"] = iso(installed_at_dt)
    order["dispatched_at"] = order.get("dispatched_at") or iso(installed_at_dt)
    serials = list(order.get("installed_serials") or [])
    serials.append(replacement_serial_number)
    order["installed_serials"] = serials

    common.set_many(unit, {
        "monitored_status": "ONLINE",
        "last_performance_ratio": None,
        "underperformance_streak_hours": 0,
    })
    # failed_at is deliberately preserved: the unit's failure history survives
    # the repair, so it is never cleared here.
    common.touch(unit)
    common.recompute_unit(unit)

    claim_id = order.get("claim_id")
    if claim_id:
        claim = db.DB.claims.get(claim_id)
        if claim is not None:
            choose_claim_closed(claim)

    if system is not None:
        common.recompute_system(system)
        common.recompute_units_of_system(system["id"])

    campaign_id = order.get("campaign_id")
    if campaign_id:
        campaign = db.DB.campaigns.get(campaign_id)
        if campaign is not None:
            common.set_many(campaign, {
                "canceled_count": len([o for o in db.orders_of_campaign(campaign_id)
                                       if o.get("status") == "CANCELED"]),
            })
    return order


def choose_claim_closed(claim):
    """The replacement reached INSTALLED, so the claim it came from closes."""
    if claim.get("status") != "DISPATCHED":
        return
    common.set_many(claim, {"status": "CLOSED"})
    for reimbursement in db.reimbursements_of_claim(claim["id"]):
        if reimbursement.get("status") == "APPROVED":
            common.set_many(reimbursement, {
                "status": "PAID",
                "paid_at": now_iso(),
            })
    _recompute_installer_ledgers(claim.get("installer_id"))


def _recompute_installer_ledgers(installer_id):
    if not installer_id:
        return
    installer = db.DB.installers.get(installer_id)
    if installer is not None:
        common.recompute_installer(installer)


def recompute_campaign_counts(campaign):
    """`dispatched_count` is how many orders activation synthesized -- a lifetime
    tally -- while `canceled_count` tracks the withdrawals; reopening a withdrawn
    order lowers the withdrawal tally rather than the synthesis tally (PRD 3.5)."""
    common.set_many(campaign, {
        "canceled_count": len([o for o in db.orders_of_campaign(campaign["id"])
                               if o.get("status") == "CANCELED"]),
    })