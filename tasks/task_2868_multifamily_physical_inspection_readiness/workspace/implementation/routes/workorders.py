"""Work orders: repair, closure verification and voiding (PRD 3.3)."""

from flask import Blueprint

import auth
import calc
import derive
import envelope
import shapes
import store
from errors import ApiError
from routes import common

bp = Blueprint("workorders", __name__)


def _sweep_of(work_order):
    return store.sweeps.get(work_order["sweep_id"])


def _deficiency_of(work_order):
    return store.deficiencies.get(work_order["deficiency_id"])


def _rederive_owning_property(work_order):
    sweep = _sweep_of(work_order)
    if sweep is None:
        return
    prop = store.properties.get(sweep["property_id"])
    if prop is not None:
        derive.rederive_property(prop, bump_version=True)


@bp.get("/work-orders/<work_order_id>")
def read_work_order(work_order_id):
    user_id, role = auth.authenticate(auth.ANY_ROLE)
    work_order = common.fetch("work_order", work_order_id)
    auth.require_owner(role, user_id, auth.property_of_work_order(work_order))
    return envelope.ok(work_order)


@bp.get("/work-orders")
def list_work_orders():
    user_id, role = auth.authenticate(auth.ANY_ROLE)
    return common.listing(
        store.work_orders.values(),
        ["sweep_id", "deficiency_id", "repair_status", "verification_status", "priority_tier"],
        role=role,
        user_id=user_id,
        property_getter=auth.property_of_work_order,
    )


@bp.post("/work-orders/<work_order_id>/complete")
def complete_work_order(work_order_id):
    user_id, _role = auth.authenticate([auth.TECHNICIAN])
    values = shapes.validate(
        [
            shapes.F("completed_at", "datetime"),
            shapes.F("resolution_note", "string"),
        ]
    )
    work_order = common.fetch("work_order", work_order_id)
    sweep = _sweep_of(work_order)
    if work_order["repair_status"] != "OPEN" or sweep is None or sweep["status"] != "IN_PROGRESS":
        raise ApiError(
            "ERR_WORK_ORDER_INVALID_STATE",
            "The repair may only be recorded on an OPEN work order of an IN_PROGRESS sweep.",
        )
    work_order["repair_status"] = "REPAIRED"
    work_order["completed_at"] = values["completed_at"]
    work_order["completed_by_user_id"] = user_id
    work_order["resolution_note"] = values["resolution_note"]
    store.touch(work_order, bump_version=True)

    deficiency = _deficiency_of(work_order)
    changed = False
    if deficiency is not None:
        siblings = [
            w
            for w in derive.deficiency_work_orders(deficiency["id"])
            if w["repair_status"] != "VOID"
        ]
        if siblings and all(w["repair_status"] == "REPAIRED" for w in siblings):
            if deficiency["status"] == "OPEN":
                deficiency["status"] = "CORRECTED"
                deficiency["corrected_at"] = values["completed_at"]
                store.touch(deficiency, bump_version=True)
                changed = True
    derive.recompute_sweep_counters(sweep)
    store.touch(sweep, bump_version=True)
    if changed:
        if deficiency.get("unit_id"):
            unit = store.units.get(deficiency["unit_id"])
            if unit is not None:
                derive.recompute_unit_open_count(unit)
        _rederive_owning_property(work_order)
    return envelope.ok(work_order)


@bp.post("/work-orders/<work_order_id>/verify-closure")
def verify_closure(work_order_id):
    user_id, role = auth.authenticate([auth.OWNER, auth.REVIEWER])
    values = shapes.validate(
        [
            shapes.F("verification_result", "enum", values=shapes.VERIFICATION_RESULT),
            shapes.F("verified_at", "datetime"),
        ]
    )
    work_order = common.fetch("work_order", work_order_id)
    auth.require_owner(role, user_id, auth.property_of_work_order(work_order))
    if work_order["completed_by_user_id"] is not None and (
        user_id == work_order["completed_by_user_id"]
    ):
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The verifying operator may not be the completing operator.",
        )
    if work_order["repair_status"] != "REPAIRED" or work_order[
        "verification_status"
    ] not in ("UNVERIFIED", "REJECTED"):
        raise ApiError(
            "ERR_WORK_ORDER_INVALID_STATE",
            "Closure verification requires a REPAIRED, not-yet-verified work order.",
        )

    sweep = _sweep_of(work_order)
    deficiency = _deficiency_of(work_order)
    work_order["verified_at"] = values["verified_at"]
    work_order["verified_by_user_id"] = user_id
    changed = False

    if values["verification_result"] == "PASSED":
        work_order["verification_status"] = "VERIFIED"
        store.touch(work_order, bump_version=True)
        if deficiency is not None:
            siblings = [
                w
                for w in derive.deficiency_work_orders(deficiency["id"])
                if w["repair_status"] != "VOID"
            ]
            if siblings and all(
                w["verification_status"] == "VERIFIED" for w in siblings
            ):
                if deficiency["status"] != "VERIFIED":
                    deficiency["status"] = "VERIFIED"
                    deficiency["verified_at"] = values["verified_at"]
                    store.touch(deficiency, bump_version=True)
                    changed = True
    else:
        work_order["verification_status"] = "REJECTED"
        work_order["rejection_count"] = work_order["rejection_count"] + 1
        work_order["repair_status"] = "OPEN"
        work_order["completed_at"] = None
        work_order["completed_by_user_id"] = None
        store.touch(work_order, bump_version=True)
        if deficiency is not None and deficiency["status"] == "CORRECTED":
            deficiency["status"] = "OPEN"
            deficiency["corrected_at"] = None
            store.touch(deficiency, bump_version=True)
            changed = True

    if sweep is not None:
        derive.recompute_sweep_counters(sweep)
        store.touch(sweep, bump_version=True)
    if changed:
        if deficiency.get("unit_id"):
            unit = store.units.get(deficiency["unit_id"])
            if unit is not None:
                derive.recompute_unit_open_count(unit)
        _rederive_owning_property(work_order)
    return envelope.ok(work_order)


@bp.post("/work-orders/<work_order_id>/void")
def void_work_order(work_order_id):
    user_id, role = auth.authenticate([auth.OWNER, auth.ADMIN])
    values = shapes.validate([shapes.F("void_reason", "string")])
    work_order = common.fetch("work_order", work_order_id)
    auth.require_owner(role, user_id, auth.property_of_work_order(work_order))
    if work_order["repair_status"] not in ("OPEN", "REPAIRED") or (
        work_order["verification_status"] == "VERIFIED"
    ):
        raise ApiError(
            "ERR_WORK_ORDER_INVALID_STATE",
            "Only an unverified OPEN or REPAIRED work order may be voided.",
        )
    work_order["repair_status"] = "VOID"
    work_order["void_reason"] = values["void_reason"]
    store.touch(work_order, bump_version=True)

    sweep = _sweep_of(work_order)
    if sweep is not None:
        derive.recompute_sweep_counters(sweep)
        store.touch(sweep, bump_version=True)

    deficiency = _deficiency_of(work_order)
    if deficiency is not None:
        remaining = [
            w
            for w in derive.deficiency_work_orders(deficiency["id"])
            if w["repair_status"] != "VOID"
        ]
        if not remaining and deficiency["status"] != "VOIDED":
            deficiency["status"] = "VOIDED"
            deficiency["points_deducted"] = calc.d("0.00")
            store.touch(deficiency, bump_version=False)
            if deficiency.get("unit_id"):
                unit = store.units.get(deficiency["unit_id"])
                if unit is not None:
                    derive.recompute_unit_open_count(unit)
            _rederive_owning_property(work_order)
    return envelope.ok(work_order)
