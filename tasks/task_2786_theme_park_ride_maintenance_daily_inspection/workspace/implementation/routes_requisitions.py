"""Part requisitions and the season parts budget ledger."""

from flask import Blueprint

import derive
import fetch
import store
import validate
from auth import ALL_ROLES, require_roles
from envelope import list_response
from errors import (
    fail,
    invalid,
    ERR_PARTS_BUDGET_EXCEEDED,
    ERR_REQUISITION_STATE_INVALID,
)
from reply import computed, made, saved

bp = Blueprint("requisitions", __name__)

CANCELLABLE = ("REQUESTED", "RESERVED", "BACKORDERED")
RELEASES_BUDGET = ("RESERVED", "BACKORDERED")


@bp.post("/park-ops/part-requisitions")
@require_roles("MaintenanceTechnician")
def create_requisition():
    data = validate.body()
    attraction = fetch.fk("attractions", data.get("attraction_id"))
    event = fetch.fk("downtime_events", data.get("downtime_event_id"))
    action = fetch.fk("bulletin_actions", data.get("bulletin_action_id"))
    validate.id_field(data, "attraction_id")
    part_number = validate.str_field(data, "part_number")
    quantity = validate.int_field(data, "quantity", minimum=1)
    unit_cost = validate.int_field(data, "unit_cost_cents", minimum=0)
    needed_by = validate.date_field(data, "needed_by_date")
    if event is not None and action is not None:
        invalid("At most one of downtime_event_id and bulletin_action_id may "
                "be supplied.")
    if event is not None and event["attraction_id"] != attraction["id"]:
        invalid("The downtime event belongs to a different attraction.")
    if action is not None and action["attraction_id"] != attraction["id"]:
        invalid("The fleet action belongs to a different attraction.")
    row = store.create(
        "requisitions",
        attraction_id=attraction["id"],
        downtime_event_id=event["id"] if event else None,
        bulletin_action_id=action["id"] if action else None,
        part_number=part_number,
        quantity=quantity,
        unit_cost_cents=unit_cost,
        total_cost_cents=quantity * unit_cost,
        needed_by_date=needed_by.isoformat(),
        expected_availability_date=None,
        status="REQUESTED",
        cancel_reason=None,
    )
    return made(derive.ser_requisition, row)


@bp.get("/park-ops/part-requisitions/<requisition_id>")
@require_roles(*ALL_ROLES)
def read_requisition(requisition_id):
    return computed(derive.ser_requisition(fetch.requisition(requisition_id)))


@bp.get("/park-ops/part-requisitions")
@require_roles(*ALL_ROLES)
def list_requisitions():
    return list_response(
        store.rows("requisitions"),
        derive.ser_requisition,
        filters=(("attraction_id", "str"), ("downtime_event_id", "str"),
                 ("bulletin_action_id", "str"), ("status", "str")),
        order=("created_at",),
    )


def _check_budget(requisition):
    attraction = store.db.attractions.get(requisition["attraction_id"])
    committed = derive.committed_cents(attraction)
    if committed + requisition["total_cost_cents"] > attraction["parts_budget_cents"]:
        fail(ERR_PARTS_BUDGET_EXCEEDED,
             "The commitment would exceed the attraction's parts budget.")


def _linked_event(requisition):
    if not requisition.get("downtime_event_id"):
        return None
    return store.db.downtime_events.get(requisition["downtime_event_id"])


@bp.post("/park-ops/part-requisitions/<requisition_id>/reserve")
@require_roles("MaintenanceManager")
def reserve_requisition(requisition_id):
    requisition = fetch.requisition(requisition_id)
    validate.body()
    if requisition["status"] != "REQUESTED":
        fail(ERR_REQUISITION_STATE_INVALID,
             "Only a REQUESTED requisition may be reserved.")
    _check_budget(requisition)
    requisition["status"] = "RESERVED"
    return saved(derive.ser_requisition, requisition)


@bp.post("/park-ops/part-requisitions/<requisition_id>/backorder")
@require_roles("MaintenanceManager")
def backorder_requisition(requisition_id):
    requisition = fetch.requisition(requisition_id)
    data = validate.body()
    expected = validate.date_field(data, "expected_availability_date")
    if requisition["status"] != "REQUESTED":
        fail(ERR_REQUISITION_STATE_INVALID,
             "Only a REQUESTED requisition may be backordered.")
    _check_budget(requisition)
    requisition["status"] = "BACKORDERED"
    requisition["expected_availability_date"] = expected.isoformat()
    event = _linked_event(requisition)
    if event is not None and event["status"] == "DIAGNOSED":
        event["status"] = "AWAITING_PARTS"
    return saved(derive.ser_requisition, requisition)


@bp.post("/park-ops/part-requisitions/<requisition_id>/receive")
@require_roles("MaintenanceTechnician")
def receive_requisition(requisition_id):
    requisition = fetch.requisition(requisition_id)
    validate.body()
    if requisition["status"] not in RELEASES_BUDGET:
        fail(ERR_REQUISITION_STATE_INVALID,
             "Only a RESERVED or BACKORDERED requisition may be received.")
    requisition["status"] = "RECEIVED"
    event = _linked_event(requisition)
    if event is not None and event["status"] == "AWAITING_PARTS":
        event["status"] = "DIAGNOSED"
    return saved(derive.ser_requisition, requisition)


@bp.post("/park-ops/part-requisitions/<requisition_id>/cancel")
@require_roles("MaintenanceManager")
def cancel_requisition(requisition_id):
    requisition = fetch.requisition(requisition_id)
    data = validate.body()
    reason = validate.str_field(data, "cancel_reason", allow_empty=True)
    if requisition["status"] not in CANCELLABLE:
        fail(ERR_REQUISITION_STATE_INVALID,
             "Only a REQUESTED, RESERVED or BACKORDERED requisition may be "
             "cancelled.")
    was_backordered = requisition["status"] == "BACKORDERED"
    requisition["status"] = "CANCELLED"
    requisition["cancel_reason"] = reason
    if was_backordered:
        event = _linked_event(requisition)
        if event is not None and event["status"] == "AWAITING_PARTS":
            event["status"] = "DIAGNOSED"
    return saved(derive.ser_requisition, requisition)
