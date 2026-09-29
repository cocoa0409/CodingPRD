"""Build-slot scheduling on finite production-line capacity (PRD 3.4)."""
from flask import Blueprint

import auth
import domain
import envelope
import store
import validation
from errors import ApiError

bp = Blueprint("slots", __name__)

SLOT_STATUSES = ("RESERVED", "CONFIRMED", "IN_BUILD", "REWORK_HOLD", "DISPLACED",
                 "RELEASED", "COMPLETED")
SLOT_READERS = ("ProductionPlanner", "ApplicationEngineer", "QualityInspector",
                "PlatformAdmin")
PO_REACHED = ("PO_RECEIVED", "INVOICED", "PAID")


def _earliest_start(order):
    """PRD 3.4 / calculations.slot_earliest_start."""
    promised = [component["promised_date"]
                for component in domain.children("long_lead_components",
                                                 "machine_order_id", order["id"])
                if component["status"] in ("ON_ORDER", "RECEIVED")
                and component["promised_date"]]
    if not promised:
        return store.fmt_date(store.today())
    return max(promised)


@bp.post("/build-slots")
def create_build_slot():
    auth.authorize(("ProductionPlanner",))
    payload = validation.body()
    machine_order_id = validation.req_str(payload, "machine_order_id", 1, None)
    production_line_id = validation.req_str(payload, "production_line_id", 1, None)
    start_date = validation.req_date(payload, "start_date")
    requested_slot_days = validation.req_int(payload, "requested_slot_days", 1)
    expected_version = validation.req_int(
        payload, "expected_machine_order_version", None, None)
    order = domain.must_get("machine_orders", machine_order_id)
    line = domain.must_get("production_lines", production_line_id)
    if order["fulfillment_status"] != "ENGINEERED":
        raise ApiError("ERR_ORDER_NOT_ENGINEERED",
                       "The order is not ENGINEERED.")
    if line["status"] != "OPEN":
        raise ApiError("ERR_LINE_NOT_OPEN", "The production line is not OPEN.")
    components = domain.children("long_lead_components", "machine_order_id",
                                 order["id"])
    if any(component["status"] == "PLANNED" for component in components):
        raise ApiError("ERR_COMPONENT_PO_NOT_RELEASED",
                       "A long-lead component purchase order is still PLANNED.")
    if expected_version != int(order["version"]):
        raise ApiError("ERR_STALE_ORDER_VERSION",
                       "The machine order version has advanced.")
    earliest = _earliest_start(order)
    if store.parse_date(start_date) < store.parse_date(earliest):
        raise ApiError("ERR_SLOT_BEFORE_COMPONENTS",
                       "The build cannot start before %s." % earliest)
    model = domain.order_model(order)
    if line["machine_family"] != model["machine_family"]:
        raise ApiError("ERR_LINE_FAMILY_MISMATCH",
                       "The line builds %s, not %s."
                       % (line["machine_family"], model["machine_family"]))
    slot_days = requested_slot_days + int(order["rework_days"])
    end_date = store.add_days(start_date, slot_days)
    buffer_days = int(line["changeover_buffer_days"])
    for incumbent in store.rows("build_slots"):
        if incumbent["production_line_id"] != line["id"]:
            continue
        if incumbent["status"] not in domain.COMMITTED_SLOT_STATUSES:
            continue
        if domain.slots_collide(start_date, end_date, incumbent["start_date"],
                                incumbent["end_date"], buffer_days):
            raise ApiError("ERR_SLOT_OVERLAP",
                           "The requested window collides with an existing slot.")
    if int(line["committed_slot_days"]) + slot_days > int(
            line["capacity_days_per_quarter"]):
        raise ApiError("ERR_LINE_CAPACITY_EXCEEDED",
                       "The line has insufficient remaining capacity.")
    slot = store.insert("build_slots", {
        "machine_order_id": order["id"],
        "production_line_id": line["id"],
        "start_date": start_date,
        "end_date": end_date,
        "requested_slot_days": requested_slot_days,
        "slot_days": slot_days,
        "status": "RESERVED",
        "superseded_by_slot_id": None,
    })
    affected_lines = {line["id"]}
    for prior in store.rows("build_slots"):
        if (prior["id"] != slot["id"]
                and prior["machine_order_id"] == order["id"]
                and prior["status"] == "RESERVED"):
            prior["status"] = "RELEASED"
            prior["superseded_by_slot_id"] = slot["id"]
            store.touch(prior)
            affected_lines.add(prior["production_line_id"])
    for line_id in affected_lines:
        domain.recompute_line_committed_days(store.get("production_lines", line_id))
    store.touch(order)
    return envelope.created(slot)


@bp.get("/build-slots")
def list_build_slots():
    auth.authorize(SLOT_READERS)
    limit, offset = validation.pagination()
    filters = {
        "machine_order_id": validation.query_str("machine_order_id"),
        "production_line_id": validation.query_str("production_line_id"),
        "status": validation.query_enum("status", SLOT_STATUSES),
        "superseded_by_slot_id": validation.query_str("superseded_by_slot_id"),
    }
    items = [row for row in store.rows("build_slots")
             if all(value is None or row.get(key) == value
                    for key, value in filters.items())]
    return envelope.ok_list(validation.paginate(items, limit, offset),
                            limit, offset, len(items))


@bp.get("/build-slots/<build_slot_id>")
def read_build_slot(build_slot_id):
    auth.authorize(SLOT_READERS)
    return envelope.ok(domain.must_get("build_slots", build_slot_id))


@bp.post("/build-slots/<build_slot_id>/confirm")
def confirm_build_slot(build_slot_id):
    auth.authorize(("ProductionPlanner",))
    slot = domain.must_get("build_slots", build_slot_id)
    line = store.get("production_lines", slot["production_line_id"])
    order = store.get("machine_orders", slot["machine_order_id"])
    if line["status"] != "OPEN":
        raise ApiError("ERR_LINE_NOT_OPEN", "The production line is not OPEN.")
    if slot["status"] != "RESERVED":
        raise ApiError("ERR_INVALID_SLOT_STATE",
                       "Only a RESERVED slot may be confirmed.")
    if order["fulfillment_status"] != "ENGINEERED":
        raise ApiError("ERR_INVALID_ORDER_STATE",
                       "The order is not ENGINEERED.")
    if order["commercial_status"] not in PO_REACHED:
        raise ApiError("ERR_COMMERCIAL_STATUS_BLOCKS_CONFIRM",
                       "The money track has not reached PO_RECEIVED.")
    slot["status"] = "CONFIRMED"
    store.touch(slot)
    domain.set_order_fulfillment(order, "SLOTTED")
    return envelope.ok(slot)


@bp.post("/build-slots/<build_slot_id>/start-build")
def start_build(build_slot_id):
    auth.authorize(("ProductionPlanner",))
    slot = domain.must_get("build_slots", build_slot_id)
    order = store.get("machine_orders", slot["machine_order_id"])
    if slot["status"] not in ("CONFIRMED", "REWORK_HOLD"):
        raise ApiError("ERR_INVALID_SLOT_STATE",
                       "Only a CONFIRMED or REWORK_HOLD slot may start a build.")
    required_order_state = ("SLOTTED" if slot["status"] == "CONFIRMED"
                            else "FAT_FAILED")
    if order["fulfillment_status"] != required_order_state:
        raise ApiError("ERR_INVALID_ORDER_STATE",
                       "The order must be %s to start this build."
                       % required_order_state)
    components = domain.children("long_lead_components", "machine_order_id",
                                 order["id"])
    if any(component["status"] != "RECEIVED" for component in components):
        raise ApiError("ERR_COMPONENTS_NOT_RECEIVED",
                       "Not every long-lead component has been received.")
    slot["status"] = "IN_BUILD"
    store.touch(slot)
    domain.set_order_fulfillment(order, "IN_BUILD")
    return envelope.ok(slot)


@bp.post("/build-slots/<build_slot_id>/release")
def release_build_slot(build_slot_id):
    auth.authorize(("ProductionPlanner",))
    slot = domain.must_get("build_slots", build_slot_id)
    if slot["status"] not in ("RESERVED", "CONFIRMED"):
        raise ApiError("ERR_INVALID_SLOT_STATE",
                       "Only a RESERVED or CONFIRMED slot may be released.")
    was_confirmed = slot["status"] == "CONFIRMED"
    slot["status"] = "RELEASED"
    store.touch(slot)
    domain.recompute_line_committed_days(
        store.get("production_lines", slot["production_line_id"]))
    if was_confirmed:
        order = store.get("machine_orders", slot["machine_order_id"])
        if order is not None and order["fulfillment_status"] == "SLOTTED":
            domain.set_order_fulfillment(order, "ENGINEERED")
    return envelope.ok(slot)
