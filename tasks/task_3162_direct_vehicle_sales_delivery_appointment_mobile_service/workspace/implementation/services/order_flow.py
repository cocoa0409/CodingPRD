"""Order lifecycle: opening, placing, locking, allocating, transit, arrival, unwinding."""

from datetime import timedelta

from db import DB, CREATE_FEE, BASELINE_SOFTWARE_VERSION, new_id
from errors import fail, fmt
from repository import find, serialize, touch
from services import calculation as calc
from services import ledger
from services.scheduling import count_booked_slots

CONFIG_LOCK_DAYS = 14
NON_TERMINAL_ORDER_STATES = (
    "PLACED", "CONFIG_LOCKED", "ALLOCATED", "IN_TRANSIT", "AT_DELIVERY_CENTER")
APPRAISABLE_ORDER_STATES = NON_TERMINAL_ORDER_STATES
FINANCEABLE_ORDER_STATES = NON_TERMINAL_ORDER_STATES


def create_order(buyer_id, configuration_id, jurisdiction_id, delivery_center_id,
                 order_fee_cents=None):
    order = {
        "id": new_id(),
        "buyer_id": buyer_id,
        "configuration_id": configuration_id,
        "jurisdiction_id": jurisdiction_id,
        "delivery_center_id": delivery_center_id,
        "order_fee_cents": CREATE_FEE if order_fee_cents is None else order_fee_cents,
        "order_fee_paid_cents": 0,
        "placed_at": None,
        "configuration_lock_deadline": None,
        "order_total_due_cents": 0,
        "delivery_readiness_posture": "FROZEN",
        "estimate_shift_days_cumulative": 0,
        "issue_note_count": 0,
        "status": "DRAFT",
        "created_at": fmt(DB.now),
        "updated_at": fmt(DB.now),
        "version": 1,
    }
    DB.orders[order["id"]] = order
    DB.order_options[order["id"]] = []
    calc.recompute_total(order)
    return order


def option_rows(order):
    ids = DB.order_options.get(order["id"], [])
    return [DB.options[o] for o in ids if o in DB.options]


def apply_configuration_change(order, add_ids, remove_ids):
    current = list(DB.order_options.get(order["id"], []))
    for option_id in remove_ids:
        if option_id in current:
            current.remove(option_id)
    for option_id in add_ids:
        if option_id not in current:
            current.append(option_id)
    DB.order_options[order["id"]] = current


def assert_lock_window_open(order, error_id="ERR_CONFIG_LOCK_DEADLINE_PASSED"):
    """PRD 3.12: the lock-deadline check of entry 7 is this path's only non-concurrency guard."""
    deadline = order.get("configuration_lock_deadline")
    if deadline is not None and DB.now > deadline:
        fail(error_id)


def create_estimate(order, basis, buffer_days, prior, estimate_state, notification_state,
                    basis_equipment_at=None, stage="PROJECTED"):
    """`stage` records which rule produced the row, because PRD 3.4 pins two
    different shift readings. A row projected from an equipment basis (placement,
    allocation, an administrative re-projection) measures the shift from the new
    window start past the prior window end. A row produced by a *slippage* (a
    batch delay) keeps the prior window's width, so its start can never move past
    the prior end and its shift is 0 — which is what the PRD's own 9-day example
    yields inside the post-allocation 7-day window."""
    window_start = basis
    window_end = basis + timedelta(days=buffer_days)
    prior_end = prior["window_end"] if prior else None
    if stage != "PROJECTED":
        shift = 0
    elif prior is None:
        shift = 0
    else:
        shift = calc.shift_days_for(
            window_start, prior,
            prior_window_was_expired=(prior_end < DB.now
                                      or prior.get("estimate_state") == "CONSUMED"))
    estimate = {
        "id": new_id(),
        "order_id": order["id"],
        "prior_estimate_id": prior["id"] if prior else None,
        "window_start": window_start,
        "window_end": window_end,
        "basis_equipment_at": basis_equipment_at or basis,
        "shift_days": shift,
        "estimate_state": estimate_state,
        "notification_state": notification_state,
        "created_at": fmt(DB.now),
        "updated_at": fmt(DB.now),
        "version": 1,
    }
    DB.estimates[estimate["id"]] = estimate
    return estimate


def place_order(order):
    order["status"] = "PLACED"
    order["placed_at"] = DB.now
    order["configuration_lock_deadline"] = DB.now + timedelta(days=CONFIG_LOCK_DAYS)
    create_estimate(order, *calc.estimate_basis(order), prior=None,
                    estimate_state="PROVISIONAL", notification_state="UNNOTIFIED",
                    basis_equipment_at=DB.now)
    calc.recompute_posture(order)
    order["delivery_readiness_posture"] = "FROZEN"
    touch(order)
    return order


def promote_consolidated(order):
    """The single live window: promote the newest unnotified estimate, and make
    sure no older provisional row survives a closure as a second live estimate."""
    rows = [e for e in DB.estimates.values() if e["order_id"] == order["id"]]
    rows.sort(key=lambda e: e["created_at"])
    for estimate in rows:
        if estimate["notification_state"] == "UNNOTIFIED":
            estimate["notification_state"] = "NOTIFIED"
            touch(estimate)
    if rows:
        newest = rows[-1]
        for estimate in rows:
            if estimate["id"] != newest["id"] and estimate["estimate_state"] in ("PROVISIONAL", "FIRM"):
                estimate["estimate_state"] = "SUPERSEDED"
                touch(estimate)


def lock_configuration(order):
    order["status"] = "CONFIG_LOCKED"
    promote_consolidated(order)
    calc.recompute_posture(order)
    touch(order)
    return order


def apply_deferred_lock(order):
    """Automatic PLACED -> CONFIG_LOCKED once the clock strictly exceeds the deadline."""
    if order["status"] != "PLACED":
        return False
    deadline = order.get("configuration_lock_deadline")
    if deadline is None or DB.now <= deadline:
        return False
    order["status"] = "CONFIG_LOCKED"
    promote_consolidated(order)
    calc.recompute_posture(order)
    touch(order)
    return True


def cancel_order(order):
    # PRD 3.8: the unwinding path covers an order that has not yet been
    # delivered; a delivered order is terminal and lies outside it.
    if order["status"] == "DELIVERED":
        fail("ERR_ALREADY_TERMINAL")
    order["status"] = "CANCELLED"
    order["delivery_readiness_posture"] = "FROZEN"
    for estimate in DB.estimates.values():
        if estimate["order_id"] == order["id"] and estimate["estimate_state"] in ("PROVISIONAL", "FIRM"):
            estimate["estimate_state"] = "SUPERSEDED"
            estimate["updated_at"] = fmt(DB.now)
            estimate["version"] += 1
    for appraisal in calc.visible_appraisals(order["id"]):
        if appraisal["status"] != "REJECTED":
            appraisal["status"] = "REJECTED"
            ledger.write_entry(order["id"], "TRADE_IN_CREDIT_REVERSAL",
                               -appraisal["net_credit_cents"], "ORDER_CANCELLED")
            touch(appraisal)
    for application in DB.applications.values():
        if application["order_id"] == order["id"] and application["status"] not in ("FUNDED", "DECLINED"):
            application["status"] = "DECLINED"
            touch(application)
            buyer = find("buyer", application["buyer_id"])
            if buyer is not None:
                buyer["credit_band"] = "SUBPRIME"
                touch(buyer)
    ledger.write_entry(order["id"], "ORDER_FEE_REFUND", -20000, "CANCELLATION_RETAINED_5000")
    order["delivery_readiness_posture"] = "FROZEN"
    touch(order)
    return order


def allocate(order, batch):
    unit = pick_unit(order, batch)
    order["status"] = "ALLOCATED"
    unit["order_id"] = order["id"]
    unit["status"] = "ALLOCATED"
    unit["allocated_at"] = DB.now
    unit["transport_eta"] = calc.transport_eta_for(unit, order)
    touch(unit)
    batch["allocated_unit_count"] = sum(
        1 for u in DB.units.values()
        if u["batch_id"] == batch["id"] and u["status"] != "UNASSIGNED")
    batch["unallocated_unit_count"] = batch["unit_capacity"] - batch["allocated_unit_count"]
    touch(batch)
    prior = calc.current_estimate(order["id"])
    basis = unit["transport_eta"]
    # The estimate chain is single-valued: the row this one replaces stops being live.
    # PRD 2.11 — a fresh row is appended that "points back at what it replaced".
    for existing in DB.estimates.values():
        if existing["order_id"] == order["id"] and existing["estimate_state"] in ("PROVISIONAL", "FIRM"):
            existing["estimate_state"] = "SUPERSEDED"
            touch(existing)
    estimate = create_estimate(
        order, basis, 7, prior, "FIRM", "UNNOTIFIED",
        basis_equipment_at=(find("batch", unit["batch_id"]) or {}).get(
            "planned_completion_at", basis),
        stage="BOUND")
    order["estimate_shift_days_cumulative"] += estimate["shift_days"]
    calc.recompute_posture(order)
    touch(order)
    return order


def assert_eligible_unit(order, batch):
    """PRD 3.4: the named batch must contain at least one unit still UNASSIGNED
    whose batch model_code equals the ordered trim's model_code."""
    configuration = find("configuration", order["configuration_id"])
    model_code = configuration["model_code"] if configuration else None
    if batch["status"] == "SCHEDULED":
        fail("ERR_NO_ELIGIBLE_UNIT", "The batch has not been brought into production.")
    if batch["model_code"] != model_code:
        fail("ERR_NO_ELIGIBLE_UNIT", "The batch does not build the ordered model.")
    if not any(u["batch_id"] == batch["id"] and u["status"] == "UNASSIGNED"
               for u in DB.units.values()):
        fail("ERR_NO_ELIGIBLE_UNIT")


def pick_unit(order, batch):
    configuration = find("configuration", order["configuration_id"])
    model_code = configuration["model_code"]
    candidates = [u for u in DB.units.values()
                  if u["batch_id"] == batch["id"] and u["status"] == "UNASSIGNED"]
    if batch["model_code"] != model_code:
        fail("ERR_NO_ELIGIBLE_UNIT", "The batch does not build the ordered model.")
    if not candidates:
        fail("ERR_NO_ELIGIBLE_UNIT")
    candidates.sort(key=lambda u: (u["created_at"], u["vin"]))
    return candidates[0]


def unit_for_order(order_id):
    for unit in DB.units.values():
        if unit["order_id"] == order_id:
            return unit
    return None


def dispatch_to_transport(order):
    order["status"] = "IN_TRANSIT"
    unit = unit_for_order(order["id"])
    if unit is not None:
        unit["status"] = "IN_TRANSIT"
        touch(unit)
    calc.recompute_posture(order)
    touch(order)
    return order


def assert_handover_legal(order):
    """Franchise-law screening applied against the resolved site's own state_code."""
    center = find("center", order["delivery_center_id"])
    jurisdiction = find("jurisdiction", order["jurisdiction_id"])
    if not jurisdiction["direct_sales_permitted"] and center["state_code"] == jurisdiction["state_code"]:
        fail("ERR_OUT_OF_STATE_DELIVERY_REQUIRED")
    if jurisdiction["gallery_only_required"] and center["center_kind"] == "GALLERY":
        fail("ERR_GALLERY_HANDOVER_FORBIDDEN")
    if center["center_kind"] == "GALLERY":
        fail("ERR_GALLERY_SERIALIZATION_GAP")
    if center["status"] != "ACTIVE":
        fail("ERR_CENTER_NOT_FOUND_FOR_KIND")


def vehicle_for_order(order_id):
    for vehicle in DB.vehicles.values():
        if vehicle["order_id"] == order_id:
            return vehicle
    return None


def create_vehicle(order):
    unit = unit_for_order(order["id"])
    vehicle = {
        "id": new_id(),
        "order_id": order["id"],
        "vin": unit["vin"] if unit else None,
        "delivered_at": None,
        "odometer_miles": 0,
        "software_version": BASELINE_SOFTWARE_VERSION,
        "service_hold_state": "NONE",
        "status": "IN_SERVICE",
        "created_at": fmt(DB.now),
        "updated_at": fmt(DB.now),
        "version": 1,
    }
    DB.vehicles[vehicle["id"]] = vehicle
    return vehicle


def arrive_at_center(order):
    assert_handover_legal(order)
    order["status"] = "AT_DELIVERY_CENTER"
    unit = unit_for_order(order["id"])
    if unit is not None:
        unit["status"] = "ARRIVED"
        touch(unit)
    if vehicle_for_order(order["id"]) is None:
        create_vehicle(order)
    center = find("center", order["delivery_center_id"])
    center["booked_slot_count"] = count_booked_slots(center["id"])
    touch(center)
    calc.recompute_posture(order)
    touch(order)
    return order


def project_estimate(order, basis, window_days):
    prior = calc.current_estimate(order["id"])
    window_start = basis
    window_end = basis + timedelta(days=window_days)
    if prior is not None:
        if window_start == prior["window_start"] and window_end == prior["window_end"]:
            fail("ERR_NO_ESTIMATE_CHANGE")
        prior["estimate_state"] = "SUPERSEDED"
        touch(prior)
    estimate = create_estimate(order, basis, window_days, prior, "PROVISIONAL",
                               "UNNOTIFIED", basis_equipment_at=basis,
                               stage="PROJECTED")
    order["estimate_shift_days_cumulative"] += estimate["shift_days"]
    touch(order)
    return estimate


def restore_estimate(estimate):
    if estimate["window_start"] < DB.now:
        fail("ERR_ESTIMATE_WINDOW_EXPIRED")
    estimate["estimate_state"] = "FIRM"
    touch(estimate)
    order = find("order", estimate["order_id"])
    for other in DB.estimates.values():
        if other["id"] == estimate["id"] or other["order_id"] != estimate["order_id"]:
            continue
        if other["estimate_state"] in ("PROVISIONAL", "FIRM"):
            other["estimate_state"] = "SUPERSEDED"
            touch(other)
    order["estimate_shift_days_cumulative"] -= estimate["shift_days"]
    touch(order)
    return estimate


def delay_batch(batch, delay_days):
    batch["status"] = "DELAYED"
    batch["delay_days"] += delay_days
    batch["planned_completion_at"] = batch["planned_completion_at"] + timedelta(days=delay_days)
    touch(batch)
    for unit in DB.units.values():
        if unit["batch_id"] != batch["id"] or not unit["order_id"]:
            continue
        order = find("order", unit["order_id"])
        if order is None:
            continue
        unit["transport_eta"] = calc.transport_eta_for(unit, order)
    for order in calc.orders_for_batch_delay(batch["id"]):
        propagate_delay(order, delay_days)
    return batch


def propagate_delay(order, delay_days):
    """The chain is single-valued, so the newest row is the prior even after a
    booking consumed the live window.  PRD 3.4: a slippage "supersedes the
    order's current PROVISIONAL or FIRM estimate" where one is still live."""
    prior = calc.current_estimate(order["id"])
    if prior is None:
        prior = calc.latest_estimate(order["id"])
    if prior is None:
        return None
    if prior["estimate_state"] in ("PROVISIONAL", "FIRM"):
        prior["estimate_state"] = "SUPERSEDED"
        touch(prior)
    basis = prior["window_start"] + timedelta(days=delay_days)
    window_end = prior["window_end"] + timedelta(days=delay_days)
    estimate = {
        "id": new_id(),
        "order_id": order["id"],
        "prior_estimate_id": prior["id"],
        "window_start": basis,
        "window_end": window_end,
        "basis_equipment_at": prior["basis_equipment_at"],
        "shift_days": 0,
        "estimate_state": "PROVISIONAL",
        "notification_state": "UNNOTIFIED",
        "created_at": fmt(DB.now),
        "updated_at": fmt(DB.now),
        "version": 1,
    }
    DB.estimates[estimate["id"]] = estimate
    for appointment in DB.appointments.values():
        if appointment["order_id"] != order["id"] or appointment["status"] != "CONFIRMED":
            continue
        if window_end > appointment["scheduled_start"]:
            appointment["status"] = "AT_RISK"
            touch(appointment)
            order["status"] = "AT_DELIVERY_CENTER"
    touch(order)
    return estimate